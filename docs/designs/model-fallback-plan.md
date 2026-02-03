# Agent Zero 模型 Fallback 开发计划

> **版本**: 1.0  
> **创建日期**: 2026-01-30  
> **优先级**: 🔴 高 (稳定性关键)  
> **目标**: 当主模型调用失败时，自动切换到备用模型继续执行

---

## 1. 功能概述

### 1.1 问题背景

当前 Agent Zero 调用 LLM 时，如果遇到以下问题会直接报错：
- API Key 过期或无效 (401)
- 配额用尽 (402/429)
- 模型暂时不可用 (503)
- 请求超时
- 上下文过长 (400)

**用户体验差**: 工作流程中断，需要手动切换模型重试。

### 1.2 目标

```
主模型失败时，自动尝试备用模型，实现：

┌─────────────┐    失败    ┌─────────────┐    失败    ┌─────────────┐
│  主模型     │ ─────────▶ │  备用模型 1  │ ─────────▶ │  备用模型 2  │
│  GPT-4.1    │            │  Claude     │            │  Gemini     │
└─────────────┘            └─────────────┘            └─────────────┘
       │                          │                          │
       ▼                          ▼                          ▼
     成功                       成功                       成功
       │                          │                          │
       └──────────────────────────┴──────────────────────────┘
                                  │
                                  ▼
                            返回结果给用户
```

---

## 2. 错误分类

参考 OpenClaw 的错误分类策略：

| 错误类型 | HTTP 状态码 | 说明 | 是否触发 Fallback |
|----------|-------------|------|-------------------|
| `auth` | 401, 403 | 认证失败、Key 无效 | ✅ 是 |
| `billing` | 402 | 账户余额不足 | ✅ 是 |
| `rate_limit` | 429 | 请求频率限制 | ✅ 是 |
| `timeout` | 408, ETIMEDOUT | 请求超时 | ✅ 是 |
| `context_overflow` | 400 | 上下文过长 | ✅ 是 (降级到更大窗口模型) |
| `model_unavailable` | 503, 502 | 模型暂时不可用 | ✅ 是 |
| `abort` | - | 用户主动取消 | ❌ 否 (直接终止) |
| `unknown` | 其他 | 未知错误 | ⚠️ 视配置 |

---

## 3. 架构设计

### 3.1 模块结构

```
python/
├── helpers/
│   ├── model_fallback.py        # 核心 Fallback 逻辑
│   ├── fallback_error.py        # 错误分类
│   └── fallback_config.py       # Fallback 配置
```

### 3.2 配置格式

**在 `conf/settings.yaml` 或 Settings UI 中配置**:

```yaml
model_fallback:
  enabled: true
  
  # 主模型 (使用现有配置)
  # chat_model: openai/gpt-4.1
  
  # 备用模型列表 (按优先级排序)
  fallbacks:
    - anthropic/claude-sonnet-4
    - google/gemini-2.5-pro
    - openai/gpt-4.1-mini
  
  # 单个模型最大重试次数
  max_retries_per_model: 1
  
  # 重试间隔 (秒)
  retry_delay: 1.0
  
  # 是否在超时后尝试 fallback
  fallback_on_timeout: true
  
  # 日志级别
  log_attempts: true
```

---

## 4. 实现模块

### 4.1 模块 1: 错误分类器

**文件**: `python/helpers/fallback_error.py`

```python
import re
from enum import Enum
from typing import Optional
from dataclasses import dataclass

class FailoverReason(Enum):
    """Fallback 触发原因"""
    AUTH = "auth"                    # 认证失败
    BILLING = "billing"              # 余额不足
    RATE_LIMIT = "rate_limit"        # 频率限制
    TIMEOUT = "timeout"              # 超时
    CONTEXT_OVERFLOW = "context_overflow"  # 上下文过长
    MODEL_UNAVAILABLE = "model_unavailable"  # 模型不可用
    UNKNOWN = "unknown"              # 未知错误

@dataclass
class FailoverError(Exception):
    """可触发 Fallback 的错误"""
    message: str
    reason: FailoverReason
    provider: str = ""
    model: str = ""
    status_code: Optional[int] = None
    original_error: Optional[Exception] = None

# 错误消息关键词匹配
ERROR_PATTERNS = {
    FailoverReason.AUTH: [
        r"invalid.*(api|key|token)",
        r"authentication",
        r"unauthorized",
        r"forbidden",
    ],
    FailoverReason.BILLING: [
        r"billing",
        r"quota.*exceeded",
        r"insufficient.*funds",
        r"payment.*required",
    ],
    FailoverReason.RATE_LIMIT: [
        r"rate.?limit",
        r"too many requests",
        r"throttl",
        r"retry.?after",
    ],
    FailoverReason.TIMEOUT: [
        r"timeout",
        r"timed?.?out",
        r"deadline.*exceeded",
        r"ETIMEDOUT",
        r"ECONNRESET",
    ],
    FailoverReason.CONTEXT_OVERFLOW: [
        r"context.*(length|limit|window)",
        r"max.*(token|length)",
        r"too many tokens",
        r"input.*too long",
    ],
    FailoverReason.MODEL_UNAVAILABLE: [
        r"model.*not.*available",
        r"service.*unavailable",
        r"temporarily.*unavailable",
        r"overloaded",
    ],
}

def classify_error(error: Exception, status_code: Optional[int] = None) -> Optional[FailoverReason]:
    """
    分类错误类型
    
    Args:
        error: 原始异常
        status_code: HTTP 状态码 (如有)
    
    Returns:
        FailoverReason 或 None (不触发 Fallback)
    """
    # 1. 根据状态码判断
    if status_code:
        if status_code in (401, 403):
            return FailoverReason.AUTH
        elif status_code == 402:
            return FailoverReason.BILLING
        elif status_code == 429:
            return FailoverReason.RATE_LIMIT
        elif status_code == 408:
            return FailoverReason.TIMEOUT
        elif status_code in (502, 503):
            return FailoverReason.MODEL_UNAVAILABLE
    
    # 2. 根据错误消息判断
    message = str(error).lower()
    
    for reason, patterns in ERROR_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, message, re.IGNORECASE):
                return reason
    
    return None

def coerce_to_failover_error(
    error: Exception,
    provider: str = "",
    model: str = "",
    status_code: Optional[int] = None
) -> Optional[FailoverError]:
    """
    将普通异常转换为 FailoverError
    
    Returns:
        FailoverError 或 None (不应触发 Fallback)
    """
    reason = classify_error(error, status_code)
    
    if reason is None:
        return None
    
    return FailoverError(
        message=str(error),
        reason=reason,
        provider=provider,
        model=model,
        status_code=status_code,
        original_error=error
    )

def is_abort_error(error: Exception) -> bool:
    """判断是否为用户主动取消"""
    name = type(error).__name__
    return name in ("CancelledError", "AbortError", "KeyboardInterrupt")
```

---

### 4.2 模块 2: Fallback 执行器

**文件**: `python/helpers/model_fallback.py`

```python
import asyncio
import logging
from typing import Callable, TypeVar, List, Optional, Any
from dataclasses import dataclass, field

from .fallback_error import (
    FailoverReason,
    FailoverError,
    coerce_to_failover_error,
    is_abort_error
)

logger = logging.getLogger(__name__)
T = TypeVar('T')

@dataclass
class ModelCandidate:
    """模型候选项"""
    provider: str
    model: str

@dataclass
class FallbackAttempt:
    """单次尝试记录"""
    provider: str
    model: str
    success: bool
    error: Optional[str] = None
    reason: Optional[FailoverReason] = None
    duration_ms: float = 0

@dataclass
class FallbackResult:
    """Fallback 执行结果"""
    result: Any
    provider: str
    model: str
    attempts: List[FallbackAttempt] = field(default_factory=list)
    
    @property
    def used_fallback(self) -> bool:
        """是否使用了备用模型"""
        return len(self.attempts) > 1

class ModelFallbackManager:
    """
    模型 Fallback 管理器
    
    使用示例:
        manager = ModelFallbackManager(
            primary=ModelCandidate("openai", "gpt-4.1"),
            fallbacks=[
                ModelCandidate("anthropic", "claude-sonnet-4"),
                ModelCandidate("google", "gemini-2.5-pro"),
            ]
        )
        
        result = await manager.run(
            call_fn=lambda p, m: call_llm(provider=p, model=m, messages=msgs)
        )
    """
    
    def __init__(
        self,
        primary: ModelCandidate,
        fallbacks: List[ModelCandidate] = None,
        max_retries: int = 1,
        retry_delay: float = 1.0,
        log_attempts: bool = True,
    ):
        self.primary = primary
        self.fallbacks = fallbacks or []
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.log_attempts = log_attempts
    
    @property
    def candidates(self) -> List[ModelCandidate]:
        """所有候选模型 (主模型 + 备用)"""
        return [self.primary] + self.fallbacks
    
    async def run(
        self,
        call_fn: Callable[[str, str], T],
        on_error: Callable[[FallbackAttempt], None] = None,
    ) -> FallbackResult:
        """
        执行带 Fallback 的模型调用
        
        Args:
            call_fn: 实际调用函数，签名为 (provider, model) -> result
            on_error: 错误回调
        
        Returns:
            FallbackResult 包含结果和尝试记录
        
        Raises:
            Exception: 所有模型都失败时抛出
        """
        import time
        
        attempts: List[FallbackAttempt] = []
        last_error: Optional[Exception] = None
        
        for candidate in self.candidates:
            for retry in range(self.max_retries):
                start_time = time.time()
                
                try:
                    # 执行调用
                    if asyncio.iscoroutinefunction(call_fn):
                        result = await call_fn(candidate.provider, candidate.model)
                    else:
                        result = call_fn(candidate.provider, candidate.model)
                    
                    # 成功
                    duration_ms = (time.time() - start_time) * 1000
                    attempts.append(FallbackAttempt(
                        provider=candidate.provider,
                        model=candidate.model,
                        success=True,
                        duration_ms=duration_ms
                    ))
                    
                    if self.log_attempts and len(attempts) > 1:
                        logger.info(
                            f"[Fallback] Success with {candidate.provider}/{candidate.model} "
                            f"after {len(attempts)} attempts"
                        )
                    
                    return FallbackResult(
                        result=result,
                        provider=candidate.provider,
                        model=candidate.model,
                        attempts=attempts
                    )
                    
                except Exception as e:
                    duration_ms = (time.time() - start_time) * 1000
                    
                    # 用户取消，直接抛出
                    if is_abort_error(e):
                        raise
                    
                    # 尝试转换为 FailoverError
                    failover_error = coerce_to_failover_error(
                        e,
                        provider=candidate.provider,
                        model=candidate.model
                    )
                    
                    # 不是可 Fallback 的错误，直接抛出
                    if failover_error is None:
                        raise
                    
                    attempt = FallbackAttempt(
                        provider=candidate.provider,
                        model=candidate.model,
                        success=False,
                        error=str(e),
                        reason=failover_error.reason,
                        duration_ms=duration_ms
                    )
                    attempts.append(attempt)
                    last_error = e
                    
                    if self.log_attempts:
                        logger.warning(
                            f"[Fallback] {candidate.provider}/{candidate.model} failed: "
                            f"{failover_error.reason.value} - {str(e)[:100]}"
                        )
                    
                    if on_error:
                        on_error(attempt)
                    
                    # 重试延迟
                    if retry < self.max_retries - 1:
                        await asyncio.sleep(self.retry_delay)
        
        # 所有模型都失败
        summary = " | ".join(
            f"{a.provider}/{a.model}: {a.reason.value if a.reason else 'unknown'}"
            for a in attempts if not a.success
        )
        raise Exception(
            f"All models failed ({len(attempts)} attempts): {summary}"
        ) from last_error


async def run_with_fallback(
    primary_provider: str,
    primary_model: str,
    fallbacks: List[tuple] = None,
    call_fn: Callable = None,
    max_retries: int = 1,
    retry_delay: float = 1.0,
) -> FallbackResult:
    """
    便捷函数：执行带 Fallback 的调用
    
    Args:
        primary_provider: 主模型提供商
        primary_model: 主模型名称
        fallbacks: 备用模型列表 [(provider, model), ...]
        call_fn: 调用函数
        max_retries: 每个模型最大重试次数
        retry_delay: 重试延迟
    
    Returns:
        FallbackResult
    """
    manager = ModelFallbackManager(
        primary=ModelCandidate(primary_provider, primary_model),
        fallbacks=[
            ModelCandidate(p, m) for p, m in (fallbacks or [])
        ],
        max_retries=max_retries,
        retry_delay=retry_delay,
    )
    return await manager.run(call_fn)
```

---

### 4.3 模块 3: 与 Agent 集成

**修改**: `models.py` 或 LLM 调用处

```python
from python.helpers.model_fallback import run_with_fallback, ModelCandidate

# 在 LLM 调用处使用 Fallback
async def call_llm_with_fallback(messages, config):
    """带 Fallback 的 LLM 调用"""
    
    # 从配置读取 Fallback 设置
    fallback_config = config.get("model_fallback", {})
    
    if not fallback_config.get("enabled", False):
        # Fallback 未启用，直接调用
        return await call_llm(messages, config)
    
    # 解析主模型
    primary_model = config.get("chat_model", "openai/gpt-4.1")
    provider, model = primary_model.split("/", 1)
    
    # 解析备用模型
    fallbacks = []
    for fb in fallback_config.get("fallbacks", []):
        if "/" in fb:
            p, m = fb.split("/", 1)
            fallbacks.append((p, m))
    
    # 执行带 Fallback 的调用
    result = await run_with_fallback(
        primary_provider=provider,
        primary_model=model,
        fallbacks=fallbacks,
        call_fn=lambda p, m: call_llm(
            messages=messages,
            provider=p,
            model=m,
            config=config
        ),
        max_retries=fallback_config.get("max_retries_per_model", 1),
        retry_delay=fallback_config.get("retry_delay", 1.0),
    )
    
    # 如果使用了 Fallback，记录日志
    if result.used_fallback:
        print(f"[Fallback] Used {result.provider}/{result.model} after primary failed")
    
    return result.result
```

---

## 5. UI 集成

### 5.1 Settings UI 添加 Fallback 配置

在设置页面添加新的配置区域：

```python
# python/helpers/settings.py

fallback_section: SettingsSection = {
    "id": "model_fallback",
    "title": "Model Fallback",
    "description": "Configure automatic model fallback when primary model fails.",
    "fields": [
        {
            "id": "fallback_enabled",
            "title": "Enable Fallback",
            "type": "checkbox",
            "description": "Automatically try backup models when primary fails.",
            "value": True,
        },
        {
            "id": "fallback_models",
            "title": "Fallback Models",
            "type": "text",
            "description": "Comma-separated list: anthropic/claude-sonnet-4, google/gemini-2.5-pro",
            "value": "anthropic/claude-sonnet-4, google/gemini-2.5-pro",
        },
        {
            "id": "fallback_max_retries",
            "title": "Max Retries Per Model",
            "type": "number",
            "description": "Maximum retry attempts for each model.",
            "value": 1,
            "min": 1,
            "max": 3,
        },
    ]
}
```

---

## 6. 实施计划

```
┌──────────────────────────────────────────────────────────────────────┐
│  Phase 1: 核心实现 (1.5 天)                                          │
├──────────────────────────────────────────────────────────────────────┤
│  Step 1.1 (0.5天): 错误分类器                                        │
│    - 创建 fallback_error.py                                          │
│    - 实现错误类型识别                                                │
│    - 单元测试                                                        │
├──────────────────────────────────────────────────────────────────────┤
│  Step 1.2 (1天): Fallback 执行器                                     │
│    - 创建 model_fallback.py                                          │
│    - 实现 ModelFallbackManager                                       │
│    - 单元测试                                                        │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│  Phase 2: 集成 (1 天)                                                │
├──────────────────────────────────────────────────────────────────────┤
│  Step 2.1 (0.5天): 与 LLM 调用集成                                   │
│    - 修改 models.py 或相关调用处                                     │
│    - 集成测试                                                        │
├──────────────────────────────────────────────────────────────────────┤
│  Step 2.2 (0.5天): Settings UI                                       │
│    - 添加 Fallback 配置区域                                          │
│    - 配置持久化                                                      │
└──────────────────────────────────────────────────────────────────────┘

总计: 2.5 天
```

---

## 7. 测试计划

### 7.1 单元测试

```python
# tests/test_model_fallback.py

import pytest
from python.helpers.fallback_error import classify_error, FailoverReason
from python.helpers.model_fallback import ModelFallbackManager, ModelCandidate

def test_classify_auth_error():
    """测试认证错误识别"""
    error = Exception("Invalid API key")
    assert classify_error(error) == FailoverReason.AUTH

def test_classify_rate_limit():
    """测试频率限制识别"""
    error = Exception("Rate limit exceeded")
    assert classify_error(error) == FailoverReason.RATE_LIMIT

def test_classify_by_status_code():
    """测试按状态码识别"""
    error = Exception("Error")
    assert classify_error(error, status_code=429) == FailoverReason.RATE_LIMIT
    assert classify_error(error, status_code=401) == FailoverReason.AUTH

@pytest.mark.asyncio
async def test_fallback_to_second_model():
    """测试 Fallback 到第二个模型"""
    call_count = 0
    
    async def mock_call(provider, model):
        nonlocal call_count
        call_count += 1
        if provider == "openai":
            raise Exception("Rate limit exceeded")
        return "success"
    
    manager = ModelFallbackManager(
        primary=ModelCandidate("openai", "gpt-4"),
        fallbacks=[ModelCandidate("anthropic", "claude")],
    )
    
    result = await manager.run(mock_call)
    
    assert result.result == "success"
    assert result.provider == "anthropic"
    assert len(result.attempts) == 2
    assert result.used_fallback == True
```

### 7.2 手动测试

1. **测试 API Key 失效 Fallback**
   - 故意配置错误的 OpenAI Key
   - 配置有效的 Anthropic Key 作为备用
   - 发送消息，验证是否自动切换到 Anthropic

2. **测试频率限制 Fallback**
   - 使用低配额账户
   - 快速发送多条消息触发 429
   - 验证是否自动切换到备用模型

---

## 8. 依赖

```
# 无需额外依赖，使用 Python 标准库
# Agent Zero 已有的依赖足够
```

---

> **文档维护者**: AI Assistant  
> **最后更新**: 2026-01-30
