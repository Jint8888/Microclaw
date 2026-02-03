# Agent Zero 基础设施增强开发计划 (优化版)

> **版本**: 2.0
> **创建日期**: 2026-01-31
> **基于**: infrastructure-enhancement-plan.md v1.2 的重新评估
> **优先级**: 🟡 中
> **目标**: 基于现有实现进行针对性增强，避免重复造轮子

---

## 📋 目录

- [1. 评估背景](#1-评估背景)
- [2. 现有实现复用指南](#2-现有实现复用指南)
- [3. 需要开发的功能](#3-需要开发的功能)
- [4. 实施计划](#4-实施计划)
- [5. 验收检查点](#5-验收检查点)
- [6. 故障排查指南](#6-故障排查指南)

---

## 1. 评估背景

### 1.1 原计划 vs 优化后计划

在深入分析项目现有代码后，发现原计划存在**重复造轮子**问题：

| 原计划模块 | 原计划工时 | 评估结果 | 优化后 |
|------------|-----------|----------|--------|
| 敏感信息脱敏 (redact.py) | 1 天 | ❌ `secrets.py` 已完善实现 | **取消** |
| 诊断日志系统 (diagnostic.py) | 1.5 天 | ⚠️ 有基础 logging，缺统一配置 | **简化为 0.5 天** |
| 命令队列管理 (command_queue.py) | 2 天 | ❌ 超时机制已完善 | **取消** |
| 进程注册表 (process_registry.py) | 1.5 天 | ⚠️ 确实缺失，但非必需 | **可选 (1 天)** |
| TTY 终端增强 | 0.5 天 | ❌ 现有实现已达生产级 | **取消** |
| **原计划总计** | **6.5 天** | | **优化后: 0.5-1.5 天** |

### 1.2 优化原则

1. **复用优先**: 充分利用现有实现
2. **按需开发**: 只开发确实缺失的功能
3. **最小改动**: 增强而非重写

---

## 2. 现有实现复用指南

### 2.1 敏感信息脱敏 ✅ 直接复用

**现有实现**: `python/helpers/secrets.py` (541 行)

**核心能力**:
```python
# 流式过滤器 - 实时屏蔽敏感信息
class StreamingSecretsFilter:
    """
    - 前缀匹配机制，防止跨块泄露
    - 最小触发长度 (min_trigger=3)
    - 未解析部分用 *** 掩码
    """
    def process_chunk(self, chunk: str) -> str: ...
    def finalize(self) -> str: ...

# 密钥管理器
class SecretsManager:
    """
    - 占位符系统: §§secret(KEY)
    - 支持多文件合并 (全局 + 项目级)
    - 线程安全缓存
    """
    def mask_values(self, text: str) -> str: ...
    def replace_aliases(self, text: str) -> str: ...
```

**使用示例**:
```python
from python.helpers.secrets import SecretsManager

# 获取管理器实例
manager = SecretsManager.get_instance()

# 脱敏文本
safe_text = manager.mask_values("API Key: sk-abc123456789xyz")
# 输出: API Key: §§secret(OPENAI_API_KEY)

# 流式脱敏 (适合实时输出)
from python.helpers.secrets import StreamingSecretsFilter

filter = StreamingSecretsFilter(manager.secrets)
for chunk in stream:
    safe_chunk = filter.process_chunk(chunk)
    print(safe_chunk, end="")
final = filter.finalize()  # 处理剩余缓冲
```

**结论**: ❌ 不需要新建 `redact.py`

---

### 2.2 命令执行与超时 ✅ 直接复用

**现有实现**: `python/tools/code_execution_tool.py` (512 行)

**核心能力**:
```python
# 多级超时配置
CODE_EXEC_TIMEOUTS = {
    "first_output_timeout": 30,   # 首次输出超时
    "between_output_timeout": 15, # 输出间隔超时
    "max_exec_timeout": 180,      # 最大执行时间
    "dialog_timeout": 5,          # 对话框检测超时
}

# Shell 提示符检测
prompt_patterns = [...]  # 自动检测命令完成

# 对话框检测
dialog_patterns = [...]  # 检测交互式对话
```

**结论**: ❌ 不需要新建 `command_queue.py`

---

### 2.3 TTY 终端会话 ✅ 直接复用

**现有实现**: `python/helpers/tty_session.py` (327 行)

**核心能力**:
```python
class TTYSession:
    """跨平台 PTY 管理"""

    # 已有功能:
    async def start(self): ...           # 启动会话
    async def send(self, data): ...      # 发送数据
    async def sendline(self, line): ...  # 发送行
    async def read_full_until_idle(self, idle_timeout, total_timeout): ...
    async def read_chunks_until_idle(self, idle_timeout, total_timeout): ...  # 流式读取
    def kill(self): ...                  # 终止进程
    async def close(self): ...           # 优雅关闭

    # 平台支持:
    # - Windows: winpty
    # - POSIX: pty + termios
```

**结论**: ❌ 不需要增强，现有实现已完善

---

## 3. 需要开发的功能

### 3.1 统一日志配置 (必要)

**问题**: 项目有基础 logging，但缺少统一配置入口

**目标**: 提供简单的日志配置函数，不重写日志系统

**文件**: `python/helpers/log_config.py` (新建，约 80 行)

```python
"""
Agent Zero 统一日志配置

提供简单的日志配置入口，复用标准 logging 模块
"""

import logging
import sys
import os
from typing import Optional
from enum import Enum


class LogSubsystem(str, Enum):
    """日志子系统分类"""
    AGENT = "a0.agent"
    MEMORY = "a0.memory"
    TOOL = "a0.tool"
    LLM = "a0.llm"
    MCP = "a0.mcp"
    BROWSER = "a0.browser"


# 全局配置状态
_configured = False


def configure_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    format_string: Optional[str] = None,
    enable_redaction: bool = True
) -> None:
    """
    配置 Agent Zero 日志系统

    Args:
        level: 日志级别 (DEBUG/INFO/WARNING/ERROR)
        log_file: 可选的日志文件路径
        format_string: 自定义格式字符串
        enable_redaction: 是否启用敏感信息脱敏

    Example:
        >>> from python.helpers.log_config import configure_logging
        >>> configure_logging(level="DEBUG", log_file="logs/agent.log")
    """
    global _configured
    if _configured:
        return

    # 默认格式
    fmt = format_string or "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
    formatter = logging.Formatter(fmt)

    # 配置根 logger
    root = logging.getLogger("a0")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # 控制台输出
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    # 文件输出 (可选)
    if log_file:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    # 脱敏集成 (复用现有 secrets.py)
    if enable_redaction:
        _install_redaction(root)

    _configured = True
    root.info("Agent Zero logging configured", extra={"level": level})


def _install_redaction(logger: logging.Logger) -> None:
    """为 logger 安装脱敏过滤器"""
    try:
        from python.helpers.secrets import SecretsManager

        class RedactionFilter(logging.Filter):
            def __init__(self):
                super().__init__()
                self.manager = SecretsManager.get_instance()

            def filter(self, record: logging.LogRecord) -> bool:
                if hasattr(record, 'msg') and isinstance(record.msg, str):
                    record.msg = self.manager.mask_values(record.msg)
                return True

        logger.addFilter(RedactionFilter())
    except ImportError:
        pass  # secrets.py 不可用时跳过


def get_logger(subsystem: LogSubsystem) -> logging.Logger:
    """
    获取子系统日志器

    Args:
        subsystem: 子系统枚举

    Returns:
        配置好的 Logger 实例

    Example:
        >>> from python.helpers.log_config import get_logger, LogSubsystem
        >>> log = get_logger(LogSubsystem.TOOL)
        >>> log.info("Executing tool", extra={"tool_name": "code_execution"})
    """
    return logging.getLogger(subsystem.value)


def set_subsystem_level(subsystem: LogSubsystem, level: str) -> None:
    """
    设置子系统日志级别

    Args:
        subsystem: 子系统枚举
        level: 日志级别字符串
    """
    logger = logging.getLogger(subsystem.value)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
```

---

### 3.2 进程注册表 (可选)

**问题**: 缺少进程追踪，长期运行可能有僵尸进程

**适用场景**:
- ✅ 长期运行的服务
- ✅ 多用户环境
- ❌ 容器/短生命周期环境 (不需要)

**文件**: `python/helpers/process_registry.py` (新建，约 150 行)

> ⚠️ **注意**: 此模块为**可选开发**，建议先监控实际运行情况，确认有僵尸进程问题后再开发。

```python
"""
Agent Zero 进程注册表

追踪所有启动的进程，提供生命周期管理和僵尸清理
"""

import time
import os
import signal
from typing import Dict, Optional, List, Callable, Any
from dataclasses import dataclass, field
from enum import Enum
import uuid
import threading


class ProcessStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BACKGROUNDED = "backgrounded"


@dataclass
class ProcessEntry:
    """进程条目"""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    command: str = ""
    pid: Optional[int] = None
    status: ProcessStatus = ProcessStatus.PENDING
    started_at: float = 0
    ended_at: Optional[float] = None
    exit_code: Optional[int] = None

    @property
    def duration_seconds(self) -> float:
        end = self.ended_at or time.time()
        return end - self.started_at if self.started_at else 0


class ProcessRegistry:
    """
    进程注册表 - 单例模式

    Usage:
        registry = ProcessRegistry.get_instance()

        # 注册进程
        entry = ProcessEntry(command="pip install requests")
        registry.register(entry)
        registry.mark_running(entry.id, pid=12345)

        # 查询
        running = registry.list_running()

        # 清理僵尸
        cleaned = registry.cleanup_zombies(max_age_seconds=1800)
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._entries: Dict[str, ProcessEntry] = {}
                    cls._instance._callbacks: List[Callable] = []
        return cls._instance

    @classmethod
    def get_instance(cls) -> "ProcessRegistry":
        return cls()

    def register(self, entry: ProcessEntry) -> str:
        """注册新进程"""
        entry.started_at = time.time()
        entry.status = ProcessStatus.RUNNING
        self._entries[entry.id] = entry
        return entry.id

    def get(self, entry_id: str) -> Optional[ProcessEntry]:
        """获取进程条目"""
        return self._entries.get(entry_id)

    def mark_running(self, entry_id: str, pid: int) -> None:
        """标记为运行中"""
        if entry := self._entries.get(entry_id):
            entry.status = ProcessStatus.RUNNING
            entry.pid = pid

    def mark_completed(self, entry_id: str, exit_code: int = 0) -> None:
        """标记为完成"""
        if entry := self._entries.get(entry_id):
            entry.status = ProcessStatus.COMPLETED
            entry.exit_code = exit_code
            entry.ended_at = time.time()
            self._notify_exit(entry)

    def mark_failed(self, entry_id: str, exit_code: int = 1) -> None:
        """标记为失败"""
        if entry := self._entries.get(entry_id):
            entry.status = ProcessStatus.FAILED
            entry.exit_code = exit_code
            entry.ended_at = time.time()
            self._notify_exit(entry)

    def list_running(self) -> List[ProcessEntry]:
        """列出运行中的进程"""
        return [e for e in self._entries.values()
                if e.status in (ProcessStatus.RUNNING, ProcessStatus.BACKGROUNDED)]

    def kill(self, entry_id: str) -> bool:
        """终止进程"""
        if entry := self._entries.get(entry_id):
            if entry.pid:
                try:
                    os.kill(entry.pid, signal.SIGKILL)
                    self.mark_failed(entry_id, exit_code=-9)
                    return True
                except (ProcessLookupError, PermissionError):
                    pass
        return False

    def cleanup_zombies(self, max_age_seconds: float = 3600) -> List[str]:
        """清理超时的僵尸进程"""
        now = time.time()
        cleaned = []
        for entry_id, entry in list(self._entries.items()):
            if entry.status == ProcessStatus.RUNNING:
                if now - entry.started_at > max_age_seconds:
                    self.kill(entry_id)
                    cleaned.append(entry_id)
        return cleaned

    def get_status(self) -> Dict[str, Any]:
        """获取注册表状态"""
        running = [e for e in self._entries.values() if e.status == ProcessStatus.RUNNING]
        return {
            "total": len(self._entries),
            "running": len(running),
            "running_pids": [e.pid for e in running if e.pid]
        }

    def on_exit(self, callback: Callable[[ProcessEntry], None]) -> None:
        """注册退出回调"""
        self._callbacks.append(callback)

    def _notify_exit(self, entry: ProcessEntry) -> None:
        """通知退出"""
        for callback in self._callbacks:
            try:
                callback(entry)
            except Exception:
                pass
```

---

## 4. 实施计划

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          优化后实施计划                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Day 1 (0.5 天): 统一日志配置 [必要]                                         │
│  ├── Step 1.1: 创建 log_config.py                                          │
│  ├── Step 1.2: 集成 secrets.py 脱敏                                        │
│  └── Step 1.3: 添加单元测试                                                 │
│                                                                             │
│  Day 1-2 (1 天): 进程注册表 [可选]                                           │
│  ├── Step 2.1: 创建 process_registry.py                                    │
│  ├── Step 2.2: 添加僵尸清理功能                                             │
│  └── Step 2.3: 添加单元测试                                                 │
│                                                                             │
│  总计: 0.5 天 (必要) + 1 天 (可选) = 最多 1.5 天                             │
│  对比原计划 6.5 天，节省 5 天                                                │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.1 开发顺序与依赖

```
┌──────────────────┐
│  log_config.py   │ ← 独立模块，复用 secrets.py
│  (统一日志配置)   │
└────────┬─────────┘
         │ (可选依赖)
         ▼
┌──────────────────┐
│process_registry.py│ ← 可集成日志
│  (进程注册表)     │
└──────────────────┘
```

---

## 5. 验收检查点

### 5.1 统一日志配置 (log_config.py)

| Step | 完成标志 | 验证命令 |
|------|----------|----------|
| **1.1** 基础配置 | ✅ `configure_logging()` 可调用 | `python -c "from python.helpers.log_config import configure_logging; configure_logging(); print('OK')"` |
| | ✅ `get_logger()` 返回 Logger | `python -c "from python.helpers.log_config import get_logger, LogSubsystem; log = get_logger(LogSubsystem.AGENT); log.info('test'); print('OK')"` |
| **1.2** 脱敏集成 | ✅ 日志自动脱敏 | 手动测试: 日志中的敏感信息被 `§§secret(KEY)` 替换 |
| **1.3** 单元测试 | ✅ 测试通过 | `pytest tests/test_log_config.py -v` |

### 5.2 进程注册表 (process_registry.py) [可选]

| Step | 完成标志 | 验证命令 |
|------|----------|----------|
| **2.1** 基础功能 | ✅ 单例模式正确 | `python -c "from python.helpers.process_registry import ProcessRegistry; r1 = ProcessRegistry.get_instance(); r2 = ProcessRegistry.get_instance(); print(r1 is r2)"` → `True` |
| | ✅ 注册/查询可用 | `python -c "from python.helpers.process_registry import ProcessRegistry, ProcessEntry; r = ProcessRegistry.get_instance(); e = ProcessEntry(command='test'); r.register(e); print(r.get(e.id).command)"` → `test` |
| **2.2** 僵尸清理 | ✅ 清理功能可用 | `python -c "from python.helpers.process_registry import ProcessRegistry; r = ProcessRegistry.get_instance(); print(r.cleanup_zombies(max_age_seconds=1))"` |
| **2.3** 单元测试 | ✅ 测试通过 | `pytest tests/test_process_registry.py -v` |

### 5.3 健康检查脚本

```bash
# 一键验证所有模块
python -c "
import sys

def check(name, code):
    try:
        exec(code)
        print(f'✅ {name}')
        return True
    except Exception as e:
        print(f'❌ {name}: {e}')
        return False

results = [
    # 现有模块 (应该都能通过)
    check('secrets.py', 'from python.helpers.secrets import SecretsManager; SecretsManager.get_instance()'),
    check('tty_session.py', 'from python.helpers.tty_session import TTYSession'),

    # 新开发模块
    check('log_config.py', 'from python.helpers.log_config import configure_logging, get_logger'),
    # check('process_registry.py', 'from python.helpers.process_registry import ProcessRegistry'),  # 可选
]

print(f'\\n总计: {sum(results)}/{len(results)} 模块正常')
sys.exit(0 if all(results) else 1)
"
```

---

## 6. 故障排查指南

### 6.1 日志没有输出

**症状**: 调用 `log.info()` 但控制台没有任何输出

**解决**:
```python
# 确保在应用启动时调用
from python.helpers.log_config import configure_logging
configure_logging(level="DEBUG")  # 设置为 DEBUG 查看更多信息
```

### 6.2 敏感信息没有被脱敏

**症状**: 日志中仍然显示完整的 API Key

**检查步骤**:
1. 确认 `configure_logging(enable_redaction=True)` (默认已启用)
2. 确认密钥已在 `secrets.env` 中注册
3. 测试 secrets.py 是否正常工作:

```python
from python.helpers.secrets import SecretsManager
manager = SecretsManager.get_instance()
print(manager.mask_values("sk-abc123456789xyz"))
```

### 6.3 复用现有模块的最佳实践

```python
# ✅ 推荐: 使用现有 secrets.py 进行脱敏
from python.helpers.secrets import SecretsManager
manager = SecretsManager.get_instance()
safe_text = manager.mask_values(raw_text)

# ✅ 推荐: 使用现有 tty_session.py 进行终端交互
from python.helpers.tty_session import TTYSession
session = TTYSession("bash")
await session.start()
await session.sendline("echo hello")
output = await session.read_full_until_idle(1, 10)
await session.close()

# ✅ 推荐: 使用现有超时配置
from python.tools.code_execution_tool import CODE_EXEC_TIMEOUTS
print(CODE_EXEC_TIMEOUTS)  # 查看当前超时配置
```

---

## 附录

### A. 与原计划对比

| 指标 | 原计划 v1.2 | 优化版 v2.0 |
|------|------------|-------------|
| 新建文件数 | 5 个 | 1-2 个 |
| 代码行数 | ~1500 行 | ~230 行 |
| 开发工时 | 6.5 天 | 0.5-1.5 天 |
| 重复代码 | 大量 | 无 |
| 现有代码复用 | 低 | 高 |

### B. 文件结构

```
python/helpers/
├── secrets.py           # ✅ 已存在 - 敏感信息管理 (直接复用)
├── tty_session.py       # ✅ 已存在 - TTY 会话管理 (直接复用)
├── shell_local.py       # ✅ 已存在 - 本地 Shell 执行 (直接复用)
├── log_config.py        # 🆕 新建 - 统一日志配置 (必要)
└── process_registry.py  # 🆕 新建 - 进程注册表 (可选)

python/tools/
└── code_execution_tool.py  # ✅ 已存在 - 命令执行与超时 (直接复用)
```

### C. 变更历史

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| 1.0 | 2026-01-31 | 原始计划 |
| 1.2 | 2026-01-31 | 添加验收检查点和故障排查 |
| **2.0** | **2026-01-31** | **重新评估后优化: 取消 3 个重复模块，保留 2 个必要/可选模块** |

---

> **文档维护者**: AI Assistant
> **最后更新**: 2026-01-31
> **状态**: 待开发确认
