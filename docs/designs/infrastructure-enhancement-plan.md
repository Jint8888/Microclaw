# Agent Zero 基础设施增强开发计划

> **版本**: 1.2
> **创建日期**: 2026-01-31
> **更新日期**: 2026-01-31
> **优先级**: 🔴 高
> **目标**: 增强 Agent Zero 的基础设施能力，包含敏感信息脱敏、诊断日志、命令队列、进程管理和 TTY 终端增强

---

## 📋 目录

- [1. 项目概述](#1-项目概述)
- [2. 模块一: 敏感信息脱敏](#2-模块一-敏感信息脱敏)
- [3. 模块二: 诊断日志系统](#3-模块二-诊断日志系统)
- [4. 模块三: 命令队列管理](#4-模块三-命令队列管理)
- [5. 模块四: 进程注册表](#5-模块四-进程注册表)
- [6. 模块五: TTY 终端增强](#6-模块五-tty-终端增强)
- [7. 实施计划](#7-实施计划)
- [8. 测试与验收](#8-测试与验收)

---

## 1. 项目概述

### 1.1 背景

Agent Zero 在执行任务时涉及大量敏感信息（API Key、Token 等）、复杂的日志输出和长时间运行的命令。当前缺少：
- 自动脱敏敏感信息防止泄露
- 结构化的诊断日志系统
- 命令执行的队列管理和超时控制

### 1.2 功能清单

| 模块 | 功能 | 优先级 | 工作量 |
|------|------|--------|--------|
| 敏感信息脱敏 | 自动识别并掩码敏感数据 | ⭐⭐⭐⭐⭐ | 1 天 |
| 诊断日志系统 | 结构化子系统日志 | ⭐⭐⭐⭐ | 1.5 天 |
| 命令队列管理 | 命令执行队列与超时控制 | ⭐⭐⭐⭐ | 2 天 |
| 进程注册表 | 进程追踪与生命周期管理 | ⭐⭐⭐⭐ | 1.5 天 |
| ~~PTY 终端支持~~ | ~~伪终端交互式命令执行~~ | ~~⭐⭐⭐~~ | ~~3 天~~ |
| TTY 终端增强 | 增强现有 tty_session.py | ⭐⭐⭐ | 0.5 天 |
| **合计** | | | **6.5 天** |

> ⚠️ **变更说明 (v1.2)**:
> - PTY 终端支持模块已删除，因 `python/helpers/tty_session.py` 已完整实现该功能
> - 新增 TTY 终端增强模块，对现有实现进行功能增强
> - 总工时从 9 天调整为 6.5 天

### 1.3 文件结构

```
python/helpers/
├── redact.py                # 🆕 敏感信息脱敏 (模式匹配)
├── diagnostic.py            # 🆕 诊断日志系统
├── command_queue.py         # 🆕 命令队列管理
├── process_registry.py      # 🆕 进程注册表
├── tty_session.py           # 🔧 增强现有实现
├── secrets.py               # ✅ 已存在 (值匹配脱敏)
└── ...
```

### 1.4 模块依赖关系

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         模块依赖关系图                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ┌──────────────────┐                                                      │
│   │   redact.py      │ ← 独立模块，无外部依赖                                 │
│   │   (敏感信息脱敏)  │                                                      │
│   └────────┬─────────┘                                                      │
│            │                                                                │
│            ▼                                                                │
│   ┌──────────────────┐                                                      │
│   │  diagnostic.py   │ ← 依赖 redact.py (日志脱敏)                           │
│   │  (诊断日志系统)   │                                                      │
│   └────────┬─────────┘                                                      │
│            │                                                                │
│            ├────────────────────┬───────────────────┐                       │
│            ▼                    ▼                   ▼                       │
│   ┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐            │
│   │ command_queue.py │ │process_registry.py│ │  tty_session.py │            │
│   │ (命令队列管理)    │ │ (进程注册表)      │ │ (TTY 终端增强)   │            │
│   └────────┬─────────┘ └────────┬─────────┘ └────────┬─────────┘            │
│            │                    │                    │                       │
│            └────────────────────┼────────────────────┘                       │
│                                 ▼                                           │
│                    ┌──────────────────────┐                                 │
│                    │  command_queue.py    │                                 │
│                    │  与 process_registry │ ← 双向集成                       │
│                    │  进行状态同步         │                                 │
│                    └──────────────────────┘                                 │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

开发顺序 (必须按此顺序):
  1️⃣ redact.py        → 独立，无依赖
  2️⃣ diagnostic.py    → 依赖 redact.py
  3️⃣ command_queue.py → 依赖 diagnostic.py
  4️⃣ process_registry.py → 依赖 diagnostic.py
  5️⃣ tty_session.py 增强 → 依赖 process_registry.py (可选集成)
```

### 1.5 日志系统初始化入口

> ⚠️ **重要**: 日志系统必须在应用启动时初始化，否则诊断功能不会生效！

**初始化位置**: 在 Agent Zero 启动入口处调用

```python
# 在 run_ui.py 或 initialize.py 的启动逻辑中添加:

from python.helpers.diagnostic import configure_diagnostics
from python.helpers.redact import install_redaction_to_handler
import logging
import os

def init_infrastructure():
    """初始化基础设施 - 必须在应用启动时调用"""

    # 1. 配置诊断日志系统
    log_level = os.getenv("A0_LOG_LEVEL", "INFO")
    log_file = os.getenv("A0_LOG_FILE", "logs/agent-zero.log")

    configure_diagnostics(
        default_level=getattr(logging, log_level.upper(), logging.INFO),
        log_file=log_file if os.getenv("A0_LOG_TO_FILE", "false").lower() == "true" else None,
        enable_console=True
    )

    # 2. 验证日志系统已启动
    from python.helpers.diagnostic import get_logger, Subsystem
    log = get_logger(Subsystem.AGENT)
    log.info("Agent Zero infrastructure initialized", version="1.0")

# 在启动时调用
init_infrastructure()
```

**环境变量配置**:

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `A0_LOG_LEVEL` | `INFO` | 日志级别 (DEBUG/INFO/WARNING/ERROR) |
| `A0_LOG_FILE` | `logs/agent-zero.log` | 日志文件路径 |
| `A0_LOG_TO_FILE` | `false` | 是否输出到文件 |

---

## 2. 模块一: 敏感信息脱敏

### 2.1 功能描述

自动识别日志和输出中的敏感信息，将其替换为掩码形式，防止泄露。

> ⚠️ **与现有 secrets.py 的关系**:
>
> | 对比项 | 现有 secrets.py | 新建 redact.py |
> |--------|----------------|----------------|
> | **匹配方式** | 值匹配 - 从 secrets.env 加载已知值 | 模式匹配 - 正则识别未知 Token |
> | **占位符格式** | `§§secret(KEY)` | `sk-abc1…789` (部分掩码) |
> | **适用场景** | 掩码已注册的 secrets | 捕获未注册的 API Key |
> | **触发时机** | 用户配置的密钥 | 意外出现在日志中的敏感信息 |
>
> 两者**功能互补**，建议同时启用：
> 1. `secrets.py` 作为第一道防线，处理已知密钥
> 2. `redact.py` 作为第二道防线，捕获漏网之鱼

**掩码示例**:
```
sk-abc123xyz456789 → sk-abc1…6789
ghp_xxxxxxxxxxxxxxxxxxxx → ghp_xx…xxxx
Authorization: Bearer eyJxxx... → Authorization: Bearer eyJx…xxx
```

### 2.2 支持的敏感模式

| 类型 | 模式示例 | 说明 |
|------|----------|------|
| OpenAI API Key | `sk-*` | OpenAI API Key |
| GitHub Token | `ghp_*`, `github_pat_*` | GitHub Personal Access Token |
| Google API Key | `AIza*` | Google API Key |
| Slack Token | `xox*-*` | Slack Bot/App Token |
| Groq API Key | `gsk_*` | Groq API Key |
| 环境变量 | `KEY=xxx`, `TOKEN=xxx` | ENV 格式赋值 |
| JSON 字段 | `"apiKey": "xxx"` | JSON 中的敏感字段 |
| Auth Header | `Bearer xxx` | Authorization 头 |
| PEM 私钥 | `-----BEGIN PRIVATE KEY-----` | 私钥块 |

### 2.3 实现代码

**文件**: `python/helpers/redact.py`

```python
import re
from typing import List, Optional
from dataclasses import dataclass

# === 配置 ===

REDACT_MIN_LENGTH = 18        # 最短需要脱敏的 Token 长度
REDACT_KEEP_START = 6         # 保留开头字符数
REDACT_KEEP_END = 4           # 保留结尾字符数

# 默认脱敏模式 (正则表达式)
DEFAULT_REDACT_PATTERNS = [
    # 环境变量风格: KEY=xxx
    r'\b[A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD)\b\s*[=:]\s*(["\']?)([^\s"\'\\\n]+)\1',

    # JSON 字段
    r'"(?:apiKey|token|secret|password|passwd|accessToken|refreshToken)"\s*:\s*"([^"]+)"',

    # CLI 参数
    r'--(?:api[-_]?key|token|secret|password|passwd)\s+(["\']?)([^\s"\']+)\1',

    # Authorization 头
    r'Authorization\s*[:=]\s*Bearer\s+([A-Za-z0-9._\-+=]+)',
    r'\bBearer\s+([A-Za-z0-9._\-+=]{18,})\b',

    # PEM 私钥块
    r'-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z ]*PRIVATE KEY-----',

    # 常见 Token 前缀
    r'\b(sk-[A-Za-z0-9_-]{8,})\b',           # OpenAI
    r'\b(ghp_[A-Za-z0-9]{20,})\b',           # GitHub PAT
    r'\b(github_pat_[A-Za-z0-9_]{20,})\b',   # GitHub Fine-grained PAT
    r'\b(xox[baprs]-[A-Za-z0-9-]{10,})\b',   # Slack
    r'\b(xapp-[A-Za-z0-9-]{10,})\b',         # Slack App
    r'\b(gsk_[A-Za-z0-9_-]{10,})\b',         # Groq
    r'\b(AIza[0-9A-Za-z\-_]{20,})\b',        # Google API Key
    r'\b(pplx-[A-Za-z0-9_-]{10,})\b',        # Perplexity
    r'\b(npm_[A-Za-z0-9]{10,})\b',           # NPM Token
    r'\b(\d{6,}:[A-Za-z0-9_-]{20,})\b',      # Telegram Bot Token
]


def _mask_token(token: str) -> str:
    """掩码单个 Token"""
    if len(token) < REDACT_MIN_LENGTH:
        return "***"
    start = token[:REDACT_KEEP_START]
    end = token[-REDACT_KEEP_END:]
    return f"{start}…{end}"


def _redact_pem_block(block: str) -> str:
    """脱敏 PEM 私钥块"""
    lines = block.split('\n')
    if len(lines) < 2:
        return "***"
    return f"{lines[0]}\n…redacted…\n{lines[-1]}"


def _redact_match(match: re.Match) -> str:
    """处理单个匹配"""
    full = match.group(0)

    # PEM 块特殊处理
    if 'PRIVATE KEY-----' in full:
        return _redact_pem_block(full)

    # 提取最后一个捕获组作为敏感值
    groups = [g for g in match.groups() if g and len(g) > 0]
    token = groups[-1] if groups else full

    masked = _mask_token(token)
    if token == full:
        return masked
    return full.replace(token, masked)


def redact_sensitive(
    text: str,
    patterns: List[str] = None,
    enabled: bool = True
) -> str:
    """
    脱敏文本中的敏感信息

    Args:
        text: 输入文本
        patterns: 自定义正则模式列表 (默认使用内置模式)
        enabled: 是否启用脱敏

    Returns:
        脱敏后的文本

    Example:
        >>> redact_sensitive("API Key: sk-abc123456789xyz")
        'API Key: sk-abc1…xyz'
    """
    if not enabled or not text:
        return text

    use_patterns = patterns or DEFAULT_REDACT_PATTERNS
    result = text

    for pattern in use_patterns:
        try:
            regex = re.compile(pattern, re.IGNORECASE)
            result = regex.sub(_redact_match, result)
        except re.error:
            continue

    return result


def get_default_patterns() -> List[str]:
    """获取默认脱敏模式列表"""
    return DEFAULT_REDACT_PATTERNS.copy()


# === 日志集成 ===

class RedactedFormatter:
    """
    脱敏日志格式化器

    用于包装现有的日志 Formatter，自动脱敏日志消息

    Usage:
        import logging
        handler = logging.StreamHandler()
        handler.setFormatter(RedactedFormatter(logging.Formatter('%(message)s')))
    """

    def __init__(self, original_formatter):
        self.original_formatter = original_formatter

    def format(self, record):
        original = self.original_formatter.format(record)
        return redact_sensitive(original)


def install_redaction_to_handler(handler, enabled: bool = True):
    """
    为日志 Handler 安装脱敏功能

    Args:
        handler: logging.Handler 实例
        enabled: 是否启用
    """
    if not enabled:
        return

    original = handler.formatter
    if original:
        handler.setFormatter(RedactedFormatter(original))
```

### 2.4 使用示例

```python
# 1. 直接使用
from python.helpers.redact import redact_sensitive

text = "API Key: sk-abc123456789xyz, Token: ghp_xxxxxxxxxxxxxxxxxxxx"
safe_text = redact_sensitive(text)
print(safe_text)
# 输出: API Key: sk-abc1…xyz, Token: ghp_xx…xxxx

# 2. 日志集成
import logging
from python.helpers.redact import install_redaction_to_handler

logger = logging.getLogger()
for handler in logger.handlers:
    install_redaction_to_handler(handler)

# 3. 与 secrets.py 协同使用
from python.helpers.secrets import get_secrets_manager
from python.helpers.redact import redact_sensitive

# 第一层: secrets.py 处理已知密钥
manager = get_secrets_manager()
text = manager.mask_values(raw_text)

# 第二层: redact.py 捕获漏网敏感信息
safe_text = redact_sensitive(text)
```

### 2.5 集成点

| 集成位置 | 说明 |
|----------|------|
| `python/helpers/print_style.py` | 包装输出函数 |
| 日志系统初始化 | 安装脱敏 Formatter |
| WebUI 消息输出 | 前端显示前脱敏 |

---

## 3. 模块二: 诊断日志系统

### 3.1 功能描述

提供结构化的诊断日志系统，支持子系统隔离、级别控制和错误上下文捕获。

### 3.2 子系统分类

| 子系统 | Logger 名称 | 说明 |
|--------|-------------|------|
| Agent | `a0.agent` | Agent 核心逻辑 |
| Memory | `a0.memory` | 记忆系统 |
| Tool | `a0.tool` | 工具执行 |
| LLM | `a0.llm` | LLM 调用 |
| MCP | `a0.mcp` | MCP 服务器 |
| Browser | `a0.browser` | 浏览器控制 |
| Channel | `a0.channel` | 渠道适配 |
| Plugin | `a0.plugin` | 插件系统 |

### 3.3 实现代码

**文件**: `python/helpers/diagnostic.py`

```python
import logging
import sys
import time
import traceback
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from contextlib import contextmanager
from functools import wraps
from enum import Enum

# === 子系统定义 ===

class Subsystem(str, Enum):
    AGENT = "a0.agent"
    MEMORY = "a0.memory"
    TOOL = "a0.tool"
    LLM = "a0.llm"
    MCP = "a0.mcp"
    BROWSER = "a0.browser"
    CHANNEL = "a0.channel"
    PLUGIN = "a0.plugin"


# === 日志级别覆盖 ===

_level_overrides: Dict[str, int] = {}


def set_subsystem_level(subsystem: str, level: int):
    """设置子系统日志级别"""
    _level_overrides[subsystem] = level
    logger = logging.getLogger(subsystem)
    logger.setLevel(level)


def get_subsystem_level(subsystem: str) -> int:
    """获取子系统日志级别"""
    return _level_overrides.get(subsystem, logging.INFO)


# === 诊断 Logger ===

class DiagnosticLogger:
    """
    诊断日志器

    提供结构化日志、上下文追踪和性能测量

    Usage:
        log = DiagnosticLogger(Subsystem.TOOL)
        log.info("Executing tool", tool_name="code_execution")

        with log.measure("tool_execution"):
            result = execute_tool()
    """

    def __init__(self, subsystem: Subsystem):
        self.subsystem = subsystem
        self.logger = logging.getLogger(subsystem.value)
        self._context: Dict[str, Any] = {}

    def _format(self, msg: str, **kwargs) -> str:
        """格式化消息，附加上下文"""
        parts = [msg]
        all_ctx = {**self._context, **kwargs}
        if all_ctx:
            ctx_str = " ".join(f"{k}={v}" for k, v in all_ctx.items())
            parts.append(f"[{ctx_str}]")
        return " ".join(parts)

    def debug(self, msg: str, **kwargs):
        self.logger.debug(self._format(msg, **kwargs))

    def info(self, msg: str, **kwargs):
        self.logger.info(self._format(msg, **kwargs))

    def warning(self, msg: str, **kwargs):
        self.logger.warning(self._format(msg, **kwargs))

    def error(self, msg: str, exc: Exception = None, **kwargs):
        formatted = self._format(msg, **kwargs)
        if exc:
            formatted += f"\n{traceback.format_exc()}"
        self.logger.error(formatted)

    @contextmanager
    def context(self, **kwargs):
        """临时添加上下文"""
        old = self._context.copy()
        self._context.update(kwargs)
        try:
            yield
        finally:
            self._context = old

    @contextmanager
    def measure(self, operation: str):
        """测量操作耗时"""
        start = time.time()
        try:
            yield
        finally:
            duration_ms = (time.time() - start) * 1000
            self.debug(f"{operation} completed", duration_ms=f"{duration_ms:.2f}")


# === 全局诊断日志器 ===

_loggers: Dict[Subsystem, DiagnosticLogger] = {}


def get_logger(subsystem: Subsystem) -> DiagnosticLogger:
    """获取子系统诊断日志器"""
    if subsystem not in _loggers:
        _loggers[subsystem] = DiagnosticLogger(subsystem)
    return _loggers[subsystem]


# === 装饰器 ===

def log_calls(subsystem: Subsystem, level: int = logging.DEBUG):
    """
    函数调用日志装饰器

    Usage:
        @log_calls(Subsystem.TOOL)
        async def execute_tool(name, params):
            ...
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            log = get_logger(subsystem)
            log.debug(f"Calling {func.__name__}", args=str(args)[:100], kwargs=str(kwargs)[:100])
            try:
                result = await func(*args, **kwargs)
                log.debug(f"{func.__name__} returned", result_type=type(result).__name__)
                return result
            except Exception as e:
                log.error(f"{func.__name__} failed", exc=e)
                raise
        return wrapper
    return decorator


# === 初始化 ===

def configure_diagnostics(
    default_level: int = logging.INFO,
    format_string: str = None,
    enable_console: bool = True,
    log_file: str = None
):
    """
    配置诊断日志系统

    Args:
        default_level: 默认日志级别
        format_string: 日志格式
        enable_console: 是否输出到控制台
        log_file: 日志文件路径 (可选)
    """
    fmt = format_string or "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
    formatter = logging.Formatter(fmt)

    # 配置根 Logger
    root = logging.getLogger("a0")
    root.setLevel(default_level)

    if enable_console:
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(formatter)
        root.addHandler(console)

    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    # 应用脱敏
    from python.helpers.redact import install_redaction_to_handler
    for handler in root.handlers:
        install_redaction_to_handler(handler)
```

### 3.4 使用示例

```python
# 1. 基础使用
from python.helpers.diagnostic import get_logger, Subsystem

log = get_logger(Subsystem.TOOL)
log.info("Executing tool", tool_name="code_execution", user="admin")

# 2. 上下文追踪
with log.context(session_id="sess-123"):
    log.info("Processing request")  # 自动附加 session_id

# 3. 性能测量
with log.measure("llm_call"):
    response = await call_llm(messages)
# 输出: llm_call completed [duration_ms=1234.56]

# 4. 装饰器
@log_calls(Subsystem.TOOL)
async def execute_tool(name, params):
    ...
```

---

## 4. 模块三: 命令队列管理

### 4.1 功能描述

管理长时间运行的命令执行，提供队列管理、超时控制和并发限制。

### 4.2 核心功能

| 功能 | 说明 |
|------|------|
| 命令队列 | FIFO 队列，按顺序执行 |
| 超时控制 | 单个命令最大执行时间 |
| 并发限制 | 限制同时执行的命令数 |
| 进度回调 | 实时输出流回调 |
| 取消支持 | 支持取消正在执行的命令 |

### 4.3 实现代码

**文件**: `python/helpers/command_queue.py`

```python
import asyncio
import subprocess
import time
from typing import Callable, Optional, Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum
from asyncio import Queue, Task
import uuid

# === 数据结构 ===

class CommandStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


@dataclass
class CommandResult:
    """命令执行结果"""
    id: str
    status: CommandStatus
    exit_code: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    duration_ms: float = 0
    error: Optional[str] = None


@dataclass
class CommandRequest:
    """命令请求"""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    command: str = ""
    cwd: Optional[str] = None
    timeout: float = 300  # 默认 5 分钟
    env: Dict[str, str] = field(default_factory=dict)
    on_output: Optional[Callable[[str], None]] = None
    on_complete: Optional[Callable[[CommandResult], None]] = None


# === 命令执行器 ===

class CommandExecutor:
    """
    单个命令执行器
    """

    def __init__(self, request: CommandRequest):
        self.request = request
        self.process: Optional[asyncio.subprocess.Process] = None
        self._cancelled = False

    async def execute(self) -> CommandResult:
        """执行命令"""
        start_time = time.time()
        stdout_chunks: List[str] = []
        stderr_chunks: List[str] = []

        try:
            self.process = await asyncio.create_subprocess_shell(
                self.request.command,
                cwd=self.request.cwd,
                env={**dict(subprocess.os.environ), **self.request.env},
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            # 读取输出
            async def read_stream(stream, chunks: List[str], is_stdout: bool):
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    text = line.decode('utf-8', errors='replace')
                    chunks.append(text)
                    if self.request.on_output and is_stdout:
                        self.request.on_output(text)

            # 并行读取 stdout 和 stderr
            await asyncio.wait_for(
                asyncio.gather(
                    read_stream(self.process.stdout, stdout_chunks, True),
                    read_stream(self.process.stderr, stderr_chunks, False),
                    self.process.wait()
                ),
                timeout=self.request.timeout
            )

            duration_ms = (time.time() - start_time) * 1000

            if self._cancelled:
                return CommandResult(
                    id=self.request.id,
                    status=CommandStatus.CANCELLED,
                    duration_ms=duration_ms
                )

            result = CommandResult(
                id=self.request.id,
                status=CommandStatus.COMPLETED if self.process.returncode == 0 else CommandStatus.FAILED,
                exit_code=self.process.returncode,
                stdout="".join(stdout_chunks),
                stderr="".join(stderr_chunks),
                duration_ms=duration_ms
            )

        except asyncio.TimeoutError:
            duration_ms = (time.time() - start_time) * 1000
            if self.process:
                self.process.kill()
            result = CommandResult(
                id=self.request.id,
                status=CommandStatus.TIMEOUT,
                duration_ms=duration_ms,
                error=f"Command timed out after {self.request.timeout}s"
            )

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            result = CommandResult(
                id=self.request.id,
                status=CommandStatus.FAILED,
                duration_ms=duration_ms,
                error=str(e)
            )

        # 回调
        if self.request.on_complete:
            self.request.on_complete(result)

        return result

    def cancel(self):
        """取消命令"""
        self._cancelled = True
        if self.process:
            self.process.kill()


# === 命令队列管理器 ===

class CommandQueueManager:
    """
    命令队列管理器

    Usage:
        manager = CommandQueueManager(max_concurrent=2)
        await manager.start()

        result = await manager.enqueue(CommandRequest(
            command="pip install requests",
            timeout=60
        ))

        await manager.stop()
    """

    def __init__(
        self,
        max_concurrent: int = 3,
        default_timeout: float = 300
    ):
        self.max_concurrent = max_concurrent
        self.default_timeout = default_timeout
        self._queue: Queue[CommandRequest] = Queue()
        self._active: Dict[str, CommandExecutor] = {}
        self._results: Dict[str, CommandResult] = {}
        self._workers: List[Task] = []
        self._running = False

    async def start(self):
        """启动队列处理"""
        self._running = True
        for i in range(self.max_concurrent):
            worker = asyncio.create_task(self._worker(i))
            self._workers.append(worker)

    async def stop(self):
        """停止队列处理"""
        self._running = False
        # 取消所有活动命令
        for executor in self._active.values():
            executor.cancel()
        # 取消 workers
        for worker in self._workers:
            worker.cancel()
        self._workers.clear()

    async def _worker(self, worker_id: int):
        """工作线程"""
        while self._running:
            try:
                request = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            executor = CommandExecutor(request)
            self._active[request.id] = executor

            try:
                result = await executor.execute()
                self._results[request.id] = result
            finally:
                del self._active[request.id]
                self._queue.task_done()

    async def enqueue(self, request: CommandRequest) -> CommandResult:
        """
        添加命令到队列并等待结果

        Args:
            request: 命令请求

        Returns:
            命令执行结果
        """
        if request.timeout == 0:
            request.timeout = self.default_timeout

        event = asyncio.Event()
        original_callback = request.on_complete

        def on_done(result: CommandResult):
            if original_callback:
                original_callback(result)
            event.set()

        request.on_complete = on_done
        await self._queue.put(request)
        await event.wait()

        return self._results.get(request.id, CommandResult(
            id=request.id,
            status=CommandStatus.FAILED,
            error="Result not found"
        ))

    def enqueue_async(self, request: CommandRequest):
        """异步添加命令 (不等待结果)"""
        asyncio.create_task(self.enqueue(request))

    def cancel(self, command_id: str) -> bool:
        """取消命令"""
        if command_id in self._active:
            self._active[command_id].cancel()
            return True
        return False

    def get_status(self) -> Dict[str, Any]:
        """获取队列状态"""
        return {
            "queue_size": self._queue.qsize(),
            "active": len(self._active),
            "max_concurrent": self.max_concurrent,
            "active_commands": list(self._active.keys())
        }


# === 全局实例 ===

_queue_manager: Optional[CommandQueueManager] = None


def get_command_queue() -> CommandQueueManager:
    """获取全局命令队列管理器"""
    global _queue_manager
    if _queue_manager is None:
        _queue_manager = CommandQueueManager()
    return _queue_manager


async def run_command(
    command: str,
    cwd: str = None,
    timeout: float = 300,
    on_output: Callable[[str], None] = None
) -> CommandResult:
    """
    便捷函数: 执行命令

    Args:
        command: 命令字符串
        cwd: 工作目录
        timeout: 超时时间 (秒)
        on_output: 输出回调

    Returns:
        命令执行结果
    """
    manager = get_command_queue()
    if not manager._running:
        await manager.start()

    return await manager.enqueue(CommandRequest(
        command=command,
        cwd=cwd,
        timeout=timeout,
        on_output=on_output
    ))
```

### 4.4 使用示例

```python
# 1. 简单使用
from python.helpers.command_queue import run_command

result = await run_command("pip list", timeout=30)
print(result.stdout)

# 2. 带输出回调
async def on_output(line):
    print(f">>> {line}", end="")

result = await run_command(
    "pip install requests",
    on_output=on_output
)

# 3. 队列管理
from python.helpers.command_queue import get_command_queue, CommandRequest

manager = get_command_queue()
await manager.start()

# 并行提交多个命令
for cmd in ["echo 1", "echo 2", "echo 3"]:
    manager.enqueue_async(CommandRequest(command=cmd))

# 检查状态
print(manager.get_status())

# 4. 取消命令
manager.cancel("cmd-id")

await manager.stop()
```

### 4.5 与现有系统集成

| 集成点 | 说明 |
|--------|------|
| `python/tools/code_execution_tool.py` | 使用命令队列执行代码 |
| `python/helpers/shell_local.py` | 包装本地 Shell 执行 |
| `python/helpers/docker.py` + `python/helpers/shell_ssh.py` | 包装 Docker/SSH 执行 |

---

## 5. 模块四: 进程注册表

### 5.1 功能描述

进程注册表用于追踪所有由 Agent Zero 启动的进程，提供生命周期管理和状态查询。

### 5.2 核心功能

| 功能 | 说明 |
|------|------|
| 进程注册 | 记录启动的进程信息 |
| 状态追踪 | 实时追踪进程状态 (running/completed/failed) |
| 后台任务 | 支持进程后台化 |
| 资源清理 | 自动清理僵尸进程 |
| 会话恢复 | Agent 重启后恢复进程管理 |

### 5.3 实现代码

**文件**: `python/helpers/process_registry.py`

```python
import time
import signal
import asyncio
from typing import Dict, Optional, List, Callable, Any
from dataclasses import dataclass, field
from enum import Enum
import uuid

# === 数据结构 ===

class ProcessStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BACKGROUNDED = "backgrounded"
    TIMEOUT = "timeout"


@dataclass
class ProcessSession:
    """进程会话"""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    command: str = ""
    pid: Optional[int] = None
    status: ProcessStatus = ProcessStatus.PENDING
    started_at: float = 0
    ended_at: Optional[float] = None
    exit_code: Optional[int] = None
    exit_signal: Optional[str] = None
    cwd: Optional[str] = None

    # 输出缓冲
    stdout: str = ""
    stderr: str = ""
    aggregated: str = ""  # 合并输出

    # 后台支持
    backgrounded: bool = False
    notify_on_exit: bool = False

    @property
    def duration_ms(self) -> float:
        if self.ended_at:
            return (self.ended_at - self.started_at) * 1000
        return (time.time() - self.started_at) * 1000


# === 进程注册表 ===

class ProcessRegistry:
    """
    进程注册表 - 追踪所有活动进程

    Usage:
        registry = ProcessRegistry()

        # 注册进程
        session = ProcessSession(command="pip install requests")
        registry.register(session)

        # 更新状态
        registry.mark_running(session.id, pid=12345)

        # 查询
        running = registry.list_running()

        # 清理
        registry.cleanup_zombies()
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._sessions = {}
            cls._instance._on_exit_callbacks = []
        return cls._instance

    def __init__(self):
        self._sessions: Dict[str, ProcessSession] = getattr(self, '_sessions', {})
        self._on_exit_callbacks: List[Callable] = getattr(self, '_on_exit_callbacks', [])

    def register(self, session: ProcessSession) -> str:
        """注册新进程会话"""
        session.started_at = time.time()
        session.status = ProcessStatus.RUNNING
        self._sessions[session.id] = session
        return session.id

    def get(self, session_id: str) -> Optional[ProcessSession]:
        """获取进程会话"""
        return self._sessions.get(session_id)

    def mark_running(self, session_id: str, pid: int):
        """标记为运行中"""
        session = self._sessions.get(session_id)
        if session:
            session.status = ProcessStatus.RUNNING
            session.pid = pid

    def mark_completed(self, session_id: str, exit_code: int = 0):
        """标记为完成"""
        session = self._sessions.get(session_id)
        if session:
            session.status = ProcessStatus.COMPLETED
            session.exit_code = exit_code
            session.ended_at = time.time()
            self._notify_exit(session)

    def mark_failed(self, session_id: str, exit_code: int = 1, signal: str = None):
        """标记为失败"""
        session = self._sessions.get(session_id)
        if session:
            session.status = ProcessStatus.FAILED
            session.exit_code = exit_code
            session.exit_signal = signal
            session.ended_at = time.time()
            self._notify_exit(session)

    def mark_backgrounded(self, session_id: str):
        """标记为后台运行"""
        session = self._sessions.get(session_id)
        if session:
            session.backgrounded = True
            session.status = ProcessStatus.BACKGROUNDED

    def append_output(self, session_id: str, stream: str, data: str):
        """追加输出"""
        session = self._sessions.get(session_id)
        if session:
            if stream == "stdout":
                session.stdout += data
            else:
                session.stderr += data
            session.aggregated += data

    def list_running(self) -> List[ProcessSession]:
        """列出运行中的进程"""
        return [s for s in self._sessions.values()
                if s.status in (ProcessStatus.RUNNING, ProcessStatus.BACKGROUNDED)]

    def list_all(self) -> List[ProcessSession]:
        """列出所有进程"""
        return list(self._sessions.values())

    def kill_session(self, session_id: str) -> bool:
        """终止进程"""
        session = self._sessions.get(session_id)
        if session and session.pid:
            try:
                import os
                os.kill(session.pid, signal.SIGKILL)
                self.mark_failed(session_id, exit_code=-9, signal="SIGKILL")
                return True
            except ProcessLookupError:
                return False
        return False

    def cleanup_zombies(self, max_age_seconds: float = 3600):
        """清理超时的僵尸进程"""
        now = time.time()
        cleaned = []
        for sid, session in list(self._sessions.items()):
            if session.status == ProcessStatus.RUNNING:
                if now - session.started_at > max_age_seconds:
                    self.kill_session(sid)
                    cleaned.append(sid)
        return cleaned

    def on_exit(self, callback: Callable[[ProcessSession], None]):
        """注册退出回调"""
        self._on_exit_callbacks.append(callback)

    def _notify_exit(self, session: ProcessSession):
        """通知退出"""
        if session.notify_on_exit:
            for callback in self._on_exit_callbacks:
                try:
                    callback(session)
                except Exception:
                    pass

    def get_status(self) -> Dict[str, Any]:
        """获取注册表状态"""
        running = [s for s in self._sessions.values() if s.status == ProcessStatus.RUNNING]
        backgrounded = [s for s in self._sessions.values() if s.status == ProcessStatus.BACKGROUNDED]
        return {
            "total": len(self._sessions),
            "running": len(running),
            "backgrounded": len(backgrounded),
            "running_pids": [s.pid for s in running if s.pid]
        }


# 全局实例
registry = ProcessRegistry()


def get_registry() -> ProcessRegistry:
    """获取全局进程注册表"""
    return registry
```

### 5.4 使用示例

```python
from python.helpers.process_registry import get_registry, ProcessSession

registry = get_registry()

# 1. 注册进程
session = ProcessSession(
    command="npm install",
    cwd="/workspace",
    notify_on_exit=True
)
registry.register(session)
registry.mark_running(session.id, pid=12345)

# 2. 追加输出
registry.append_output(session.id, "stdout", "Installing packages...\n")

# 3. 标记完成
registry.mark_completed(session.id, exit_code=0)

# 4. 查询状态
running = registry.list_running()
print(f"Running processes: {len(running)}")

# 5. 清理僵尸进程
cleaned = registry.cleanup_zombies(max_age_seconds=1800)
```

### 5.5 与命令队列集成

```python
# command_queue.py 中集成
from python.helpers.process_registry import get_registry, ProcessSession

class CommandExecutor:
    async def execute(self) -> CommandResult:
        # 注册到进程表
        session = ProcessSession(
            command=self.request.command,
            cwd=self.request.cwd
        )
        registry = get_registry()
        registry.register(session)

        # ... 执行逻辑 ...

        # 完成时更新状态
        if result.status == CommandStatus.COMPLETED:
            registry.mark_completed(session.id, result.exit_code)
        else:
            registry.mark_failed(session.id, result.exit_code)
```

---

## 6. 模块五: TTY 终端增强

> ⚠️ **说明**: 此模块替代原计划的 "PTY 终端支持" 模块，因 `python/helpers/tty_session.py` 已完整实现 PTY 功能。

### 6.1 现有实现分析

`python/helpers/tty_session.py` 已实现：
- ✅ Windows PTY (`winpty.PtyProcess.spawn`)
- ✅ Unix PTY (`pty.openpty` + `termios`)
- ✅ 异步读写 (`start/send/sendline/read/close`)
- ✅ 超时控制 (`read_full_until_idle`)
- ✅ Echo 控制 (`termios.ECHO`)
- ✅ 流式输出 (`read_chunks_until_idle`)

### 6.2 增强功能

| 功能 | 当前状态 | 增强内容 |
|------|---------|---------|
| 窗口尺寸 | ❌ Windows 硬编码 80x25 | 添加 `resize(cols, rows)` 方法 |
| 退出码 | ❌ Windows 始终返回 0 | 正确获取实际退出码 |
| 进程状态 | ❌ 无 `is_alive` 属性 | 添加 `is_alive` 属性 |
| 信号发送 | ❌ 无 | 添加 `send_signal()` / `interrupt()` |
| 上下文管理 | ❌ 无 | 支持 `async with` 语法 |
| 进程注册 | ❌ 无 | 与 `process_registry` 集成 |

### 6.3 增强代码

在 `python/helpers/tty_session.py` 中添加：

```python
# === 在 TTYSession 类中添加 ===

@property
def is_alive(self) -> bool:
    """检查进程是否存活"""
    if self._proc is None:
        return False
    return getattr(self._proc, 'returncode', None) is None

@property
def returncode(self) -> Optional[int]:
    """获取退出码"""
    if self._proc is None:
        return None
    return getattr(self._proc, 'returncode', None)

def resize(self, cols: int, rows: int):
    """调整终端窗口尺寸"""
    if self._proc is None:
        return
    if _IS_WIN:
        # Windows: winpty 支持 resize
        if hasattr(self._proc, '_child') and hasattr(self._proc._child, 'setwinsize'):
            self._proc._child.setwinsize(rows, cols)
    else:
        # Unix: 使用 TIOCSWINSZ ioctl
        import fcntl
        import struct
        import termios
        if hasattr(self._proc, '_master_fd'):
            winsize = struct.pack('HHHH', rows, cols, 0, 0)
            fcntl.ioctl(self._proc._master_fd, termios.TIOCSWINSZ, winsize)

async def interrupt(self):
    """发送中断信号 (Ctrl+C)"""
    await self.send('\x03')  # ETX character

async def send_eof(self):
    """发送 EOF (Ctrl+D)"""
    await self.send('\x04')  # EOT character

# === 上下文管理器支持 ===

async def __aenter__(self):
    await self.start()
    return self

async def __aexit__(self, exc_type, exc_val, exc_tb):
    await self.close()
    return False
```

### 6.4 Windows 退出码修复

修改 `_spawn_winpty` 函数中的 `_Proc` 类：

```python
class _Proc:
    def __init__(self):
        self.stdin = _Stdin()
        self.stdout = reader
        self.pid = child.pid
        self.returncode = None
        self._child = child  # 保存引用以便访问

    async def wait(self):
        while child.isalive():
            await asyncio.sleep(0.2)
        # 获取实际退出码
        self.returncode = child.exitstatus if hasattr(child, 'exitstatus') else 0
        return self.returncode
```

### 6.5 使用示例

```python
from python.helpers.tty_session import TTYSession

# 1. 上下文管理器 (推荐)
async with TTYSession("bash") as term:
    await term.sendline("echo hello")
    output = await term.read_full_until_idle(1, 5)
    print(output)

# 2. 中断正在运行的命令
term = TTYSession("bash")
await term.start()
await term.sendline("sleep 100")
await asyncio.sleep(1)
await term.interrupt()  # 发送 Ctrl+C
await term.close()

# 3. 调整窗口尺寸
term.resize(120, 40)

# 4. 检查状态
if term.is_alive:
    print("Process is running")
print(f"Exit code: {term.returncode}")
```

---

## 7. 实施计划

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Day 1: 敏感信息脱敏                                                          │
├─────────────────────────────────────────────────────────────────────────────┤
│ Step 1.1 (0.5天): 核心脱敏函数                                               │
│   - 创建 redact.py                                                          │
│   - 实现正则匹配与掩码                                                        │
│   - 单元测试                                                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│ Step 1.2 (0.5天): 日志集成                                                   │
│   - 实现 RedactedFormatter                                                  │
│   - 集成到现有日志系统                                                        │
│   - 文档说明与 secrets.py 的协作关系                                          │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ Day 2-2.5: 诊断日志系统                                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│ Step 2.1 (0.5天): DiagnosticLogger 类                                       │
│   - 创建 diagnostic.py                                                      │
│   - 子系统分类                                                               │
│   - 上下文管理                                                               │
├─────────────────────────────────────────────────────────────────────────────┤
│ Step 2.2 (0.5天): 性能测量与装饰器                                            │
│   - measure 上下文                                                          │
│   - log_calls 装饰器                                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│ Step 2.3 (0.5天): 集成与测试                                                 │
│   - 配置函数                                                                 │
│   - 与脱敏集成                                                               │
│   - 集成测试                                                                 │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ Day 3-4.5: 命令队列管理                                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│ Step 3.1 (0.5天): 数据结构                                                   │
│   - CommandRequest, CommandResult                                           │
│   - CommandStatus 枚举                                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│ Step 3.2 (1天): CommandExecutor                                             │
│   - 异步执行                                                                 │
│   - 超时控制                                                                 │
│   - 输出流处理                                                               │
├─────────────────────────────────────────────────────────────────────────────┤
│ Step 3.3 (0.5天): CommandQueueManager                                       │
│   - 队列管理                                                                 │
│   - 并发控制                                                                 │
│   - Worker 实现                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ Day 5-6: 进程注册表                                                          │
├─────────────────────────────────────────────────────────────────────────────┤
│ Step 4.1 (0.5天): 数据结构                                                   │
│   - ProcessSession, ProcessStatus                                           │
│   - 进程生命周期状态机                                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│ Step 4.2 (0.5天): ProcessRegistry 核心                                       │
│   - 注册、查询、更新接口                                                      │
│   - 单例模式实现                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│ Step 4.3 (0.5天): 与命令队列集成                                              │
│   - 自动注册执行的命令                                                        │
│   - 状态同步                                                                 │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ Day 6.5: TTY 终端增强                                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│ Step 5.1 (0.5天): 增强现有 tty_session.py                                    │
│   - 添加 resize() 方法                                                       │
│   - 修复 Windows 退出码                                                      │
│   - 添加 is_alive 属性                                                       │
│   - 添加 interrupt() / send_eof()                                           │
│   - 添加 async with 支持                                                     │
│   - 单元测试                                                                 │
└─────────────────────────────────────────────────────────────────────────────┘

总计: 6.5 天 (原计划 9 天，节省 2.5 天)
```

---

## 8. 测试与验收

### 8.1 每个 Step 的验收检查点

> ⚠️ **重要**: 每完成一个 Step，必须通过对应的验收检查后才能进入下一步！

#### 模块一: 敏感信息脱敏 (redact.py)

| Step | 完成标志 | 验证命令 |
|------|----------|----------|
| **1.1** 核心脱敏函数 | ✅ `redact_sensitive()` 函数可用 | `python -c "from python.helpers.redact import redact_sensitive; print(redact_sensitive('sk-abc123456789xyz'))"` → 输出 `sk-abc1…6789` |
| | ✅ OpenAI Key 脱敏正确 | `python -c "from python.helpers.redact import redact_sensitive; assert 'sk-abc1' in redact_sensitive('sk-abc123456789xyz') and '123456789' not in redact_sensitive('sk-abc123456789xyz')"` |
| | ✅ GitHub Token 脱敏正确 | `python -c "from python.helpers.redact import redact_sensitive; print(redact_sensitive('ghp_xxxxxxxxxxxxxxxxxxxx'))"` → 包含 `ghp_xx…` |
| | ✅ 单元测试通过 | `pytest tests/test_redact.py -v` |
| **1.2** 日志集成 | ✅ `RedactedFormatter` 类可用 | `python -c "from python.helpers.redact import RedactedFormatter; print('OK')"` |
| | ✅ Handler 安装成功 | `python -c "import logging; from python.helpers.redact import install_redaction_to_handler; h = logging.StreamHandler(); h.setFormatter(logging.Formatter('%(message)s')); install_redaction_to_handler(h); print('OK')"` |

#### 模块二: 诊断日志系统 (diagnostic.py)

| Step | 完成标志 | 验证命令 |
|------|----------|----------|
| **2.1** DiagnosticLogger | ✅ `Subsystem` 枚举可用 | `python -c "from python.helpers.diagnostic import Subsystem; print(list(Subsystem))"` |
| | ✅ `get_logger()` 返回日志器 | `python -c "from python.helpers.diagnostic import get_logger, Subsystem; log = get_logger(Subsystem.AGENT); log.info('test'); print('OK')"` |
| **2.2** 性能测量 | ✅ `measure` 上下文可用 | `python -c "from python.helpers.diagnostic import get_logger, Subsystem; log = get_logger(Subsystem.TOOL); exec('import time\\nwith log.measure(\"test\"): time.sleep(0.1)'); print('OK')"` |
| | ✅ `log_calls` 装饰器可用 | `python -c "from python.helpers.diagnostic import log_calls, Subsystem; print('OK')"` |
| **2.3** 集成测试 | ✅ `configure_diagnostics()` 可调用 | `python -c "from python.helpers.diagnostic import configure_diagnostics; configure_diagnostics(); print('OK')"` |
| | ✅ 日志输出包含脱敏 | 手动测试: 日志中的敏感信息被正确掩码 |

#### 模块三: 命令队列管理 (command_queue.py)

| Step | 完成标志 | 验证命令 |
|------|----------|----------|
| **3.1** 数据结构 | ✅ `CommandRequest` 可创建 | `python -c "from python.helpers.command_queue import CommandRequest; r = CommandRequest(command='echo hello'); print(r.id)"` |
| | ✅ `CommandStatus` 枚举完整 | `python -c "from python.helpers.command_queue import CommandStatus; print(list(CommandStatus))"` |
| **3.2** CommandExecutor | ✅ 命令可执行 | `python -c "import asyncio; from python.helpers.command_queue import run_command; r = asyncio.run(run_command('echo hello', timeout=5)); print(r.stdout)"` → 输出 `hello` |
| | ✅ 超时生效 | `python -c "import asyncio; from python.helpers.command_queue import run_command; r = asyncio.run(run_command('sleep 10', timeout=1)); print(r.status)"` → 输出 `timeout` |
| **3.3** 队列管理 | ✅ 队列状态可查询 | `python -c "from python.helpers.command_queue import get_command_queue; print(get_command_queue().get_status())"` |
| | ✅ 并发测试通过 | `pytest tests/test_command_queue.py -v` |

#### 模块四: 进程注册表 (process_registry.py)

| Step | 完成标志 | 验证命令 |
|------|----------|----------|
| **4.1** 数据结构 | ✅ `ProcessSession` 可创建 | `python -c "from python.helpers.process_registry import ProcessSession; s = ProcessSession(command='test'); print(s.id)"` |
| | ✅ `ProcessStatus` 枚举完整 | `python -c "from python.helpers.process_registry import ProcessStatus; print(list(ProcessStatus))"` |
| **4.2** Registry 核心 | ✅ 注册/查询可用 | `python -c "from python.helpers.process_registry import get_registry, ProcessSession; r = get_registry(); s = ProcessSession(command='test'); r.register(s); print(r.get(s.id).command)"` → 输出 `test` |
| | ✅ 单例模式正确 | `python -c "from python.helpers.process_registry import get_registry; r1 = get_registry(); r2 = get_registry(); print(r1 is r2)"` → 输出 `True` |
| **4.3** 集成测试 | ✅ 状态同步正确 | 手动测试: 命令执行后进程状态正确更新 |

#### 模块五: TTY 终端增强 (tty_session.py)

| Step | 完成标志 | 验证命令 |
|------|----------|----------|
| **5.1** TTY 增强 | ✅ `is_alive` 属性存在 | `python -c "from python.helpers.tty_session import TTYSession; t = TTYSession('echo'); print(hasattr(t, 'is_alive'))"` → 输出 `True` |
| | ✅ `resize()` 方法存在 | `python -c "from python.helpers.tty_session import TTYSession; t = TTYSession('echo'); print(hasattr(t, 'resize'))"` → 输出 `True` |
| | ✅ `interrupt()` 方法存在 | `python -c "from python.helpers.tty_session import TTYSession; t = TTYSession('echo'); print(hasattr(t, 'interrupt'))"` → 输出 `True` |
| | ✅ 上下文管理器可用 | `python -c "from python.helpers.tty_session import TTYSession; print(hasattr(TTYSession, '__aenter__') and hasattr(TTYSession, '__aexit__'))"` → 输出 `True` |

### 8.2 单元测试清单

| 测试文件 | 覆盖模块 | 测试点 |
|----------|----------|--------|
| test_redact.py | redact.py | 各种 Token 格式、PEM 块、边界情况 |
| test_diagnostic.py | diagnostic.py | 子系统日志、上下文、性能测量 |
| test_command_queue.py | command_queue.py | 队列、超时、并发、取消 |
| test_process_registry.py | process_registry.py | 注册、状态更新、清理、回调 |
| test_tty_session.py | tty_session.py | resize、退出码、中断、上下文管理器 |

### 8.3 验收标准

| 功能 | 验收标准 |
|------|----------|
| 敏感信息脱敏 | 所有已知 Token 格式正确掩码 |
| 诊断日志 | 子系统日志独立可控 |
| 命令队列 | 超时命令正确终止 |
| 并发控制 | 不超过配置的并发数 |
| 进程注册表 | 进程状态准确追踪 |
| 僵尸清理 | 超时进程自动清理 |
| TTY 增强 | resize/interrupt 正常工作 |
| 跨平台 | Linux/macOS/Windows 均可工作 |

---

## 9. 故障排查指南

### 9.1 错误码定义

| 模块 | 错误码范围 | 说明 |
|------|-----------|------|
| redact | `REDACT_001` - `REDACT_099` | 脱敏模块错误 |
| diagnostic | `DIAG_001` - `DIAG_099` | 诊断日志错误 |
| command_queue | `CMD_001` - `CMD_099` | 命令队列错误 |
| process_registry | `PROC_001` - `PROC_099` | 进程注册表错误 |
| tty_session | `TTY_001` - `TTY_099` | TTY 会话错误 |

**常见错误码**:

| 错误码 | 含义 | 解决方案 |
|--------|------|----------|
| `CMD_001` | 命令执行超时 | 增加 timeout 参数或检查命令是否卡住 |
| `CMD_002` | 命令被取消 | 用户主动取消，无需处理 |
| `CMD_003` | 进程创建失败 | 检查命令路径和权限 |
| `PROC_001` | 进程不存在 | 进程已退出或 ID 错误 |
| `PROC_002` | 杀死进程失败 | 进程可能已退出或权限不足 |
| `TTY_001` | PTY 创建失败 | Windows 需安装 pywinpty，Unix 检查 pty 权限 |
| `TTY_002` | 写入 PTY 失败 | 进程可能已退出 |

### 9.2 日志级别说明

| 级别 | 使用场景 | 示例 |
|------|----------|------|
| `DEBUG` | 详细调试信息，开发时使用 | 函数入口/出口、变量值 |
| `INFO` | 正常运行信息，生产环境默认 | 服务启动、请求处理 |
| `WARNING` | 潜在问题，不影响运行 | 配置缺失使用默认值 |
| `ERROR` | 错误发生，功能受影响 | API 调用失败、文件不存在 |

**按子系统调整日志级别**:

```python
from python.helpers.diagnostic import set_subsystem_level, Subsystem
import logging

# 只看 TOOL 的详细日志
set_subsystem_level(Subsystem.TOOL.value, logging.DEBUG)

# 关闭 LLM 日志噪音
set_subsystem_level(Subsystem.LLM.value, logging.WARNING)
```

### 9.3 健康检查命令

快速验证各模块是否正常工作:

```bash
# 一键健康检查脚本
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
    check('redact', 'from python.helpers.redact import redact_sensitive; redact_sensitive(\"test\")'),
    check('diagnostic', 'from python.helpers.diagnostic import get_logger, Subsystem; get_logger(Subsystem.AGENT)'),
    check('command_queue', 'from python.helpers.command_queue import get_command_queue; get_command_queue()'),
    check('process_registry', 'from python.helpers.process_registry import get_registry; get_registry()'),
    check('tty_session', 'from python.helpers.tty_session import TTYSession; TTYSession(\"echo\")'),
]

print(f'\\n总计: {sum(results)}/{len(results)} 模块正常')
sys.exit(0 if all(results) else 1)
"
```

### 9.4 常见问题 FAQ

#### Q1: 日志没有输出怎么办？

**症状**: 调用 `log.info()` 但控制台没有任何输出

**原因**: 日志系统未初始化

**解决**:
```python
# 确保在应用启动时调用
from python.helpers.diagnostic import configure_diagnostics
configure_diagnostics()
```

#### Q2: 敏感信息没有被脱敏？

**症状**: 日志中仍然显示完整的 API Key

**检查步骤**:
1. 确认 `configure_diagnostics()` 已调用
2. 确认 Token 长度 >= 18 字符 (短 Token 不脱敏)
3. 确认 Token 格式在支持列表中

**调试**:
```python
from python.helpers.redact import redact_sensitive, get_default_patterns
print(get_default_patterns())  # 查看支持的模式
print(redact_sensitive("your-token-here"))  # 测试脱敏
```

#### Q3: 命令执行超时但进程还在运行？

**症状**: `run_command()` 返回 TIMEOUT 状态，但 `ps` 显示进程仍存在

**原因**: 进程可能是僵尸进程或有子进程

**解决**:
```python
from python.helpers.process_registry import get_registry
registry = get_registry()

# 强制清理僵尸进程
cleaned = registry.cleanup_zombies(max_age_seconds=60)
print(f"Cleaned {len(cleaned)} zombie processes")
```

#### Q4: Windows 上 TTY 不工作？

**症状**: `TTYSession` 创建失败，报 `winpty` 相关错误

**解决**:
```bash
# 安装 pywinpty
pip install pywinpty
```

#### Q5: 如何查看当前运行的进程？

```python
from python.helpers.process_registry import get_registry

registry = get_registry()
status = registry.get_status()
print(f"Running: {status['running']}")
print(f"Backgrounded: {status['backgrounded']}")
print(f"PIDs: {status['running_pids']}")

# 详细列表
for session in registry.list_running():
    print(f"  {session.id}: {session.command[:50]}... (PID: {session.pid})")
```

#### Q6: 如何调试命令队列阻塞？

```python
from python.helpers.command_queue import get_command_queue

manager = get_command_queue()
status = manager.get_status()

print(f"Queue size: {status['queue_size']}")
print(f"Active: {status['active']}/{status['max_concurrent']}")
print(f"Active commands: {status['active_commands']}")

# 如果队列满了，可以取消某个命令
# manager.cancel("command-id")
```

---

## 附录

### A. 依赖清单

```
# requirements.txt (无新增依赖)
# tty_session.py 已有的依赖:
# - pywinpty (Windows)
# - nest_asyncio
```

### B. 参考资料

- [OpenClaw Redact](https://github.com/your-org/openclaw/blob/main/src/logging/redact.ts)
- [OpenClaw Diagnostic](https://github.com/your-org/openclaw/blob/main/src/logging/diagnostic.ts)
- [OpenClaw Command Queue](https://github.com/your-org/openclaw/blob/main/src/process/command-queue.ts)
- [OpenClaw Bash Tools](https://github.com/your-org/openclaw/blob/main/src/agents/bash-tools.exec.ts)
- [pywinpty Documentation](https://github.com/spyder-ide/pywinpty)

### C. 架构图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                   Agent Zero 执行基础设施                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│ ┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐          │
│ │命令队列          │◄──►│ 进程注册表       │◄───│ TTY 会话        │          │
│ │(调度)            │   │(追踪)            │   │(交互) [增强]     │          │
│ └──────────────────┘   └──────────────────┘   └──────────────────┘          │
│        │                       │                       │                    │
│        └───────────────────────┴───────────────────────┘                    │
│                                ▼                                            │
│                  ┌──────────────────────────┐                               │
│                  │ 诊断日志系统              │                               │
│                  │(可观测性)                 │                               │
│                  └──────────────┬───────────┘                               │
│                                 │                                           │
│                                 ▼                                           │
│                  ┌──────────────────────────┐                               │
│                  │ 敏感信息脱敏              │                               │
│                  │(安全)                     │                               │
│                  │ ┌────────┐ ┌────────┐    │                               │
│                  │ │secrets │ │ redact │    │                               │
│                  │ │(值匹配)│ │(模式)  │    │                               │
│                  │ └────────┘ └────────┘    │                               │
│                  └──────────────────────────┘                               │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### D. 变更历史

| 版本 | 日期 | 变更内容 |
|------|------|---------|
| 1.0 | 2026-01-31 | 初始版本 |
| 1.1 | 2026-01-31 | 添加 redact.py 与 secrets.py 关系说明 |
| 1.2 | 2026-01-31 | 删除 PTY 模块（已存在），新增 TTY 增强模块；修正集成点文件名；工时从 9 天调整为 6.5 天 |

---

> **文档维护者**: AI Assistant
> **最后更新**: 2026-01-31
