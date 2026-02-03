# Agent Zero 基础设施增强 - Walkthrough 文档

> **版本**: 1.0
> **创建日期**: 2026-01-31
> **作者**: AI Assistant
> **状态**: ✅ 开发完成

---

## 📋 目录

- [1. 概述](#1-概述)
- [2. 新增模块说明](#2-新增模块说明)
- [3. 快速开始](#3-快速开始)
- [4. 详细使用指南](#4-详细使用指南)
- [5. 与现有模块集成](#5-与现有模块集成)
- [6. 测试说明](#6-测试说明)
- [7. 故障排查](#7-故障排查)

---

## 1. 概述

### 1.1 开发背景

本次开发基于对 Agent Zero 现有代码的深度评估，采用**复用优先**的原则：

| 原计划 | 评估结果 | 最终决策 |
|--------|----------|----------|
| 新建 redact.py | ❌ secrets.py 已有完善实现 | 直接复用 |
| 新建 command_queue.py | ❌ 超时机制已完善 | 直接复用 |
| 增强 tty_session.py | ❌ 现有实现已达生产级 | 直接复用 |
| 新建 diagnostic.py | ⚠️ 缺统一配置 | **简化为 log_config.py** |
| 新建 process_registry.py | ⚠️ 确实缺失 | **开发** |

### 1.2 新增文件清单

```
python/helpers/
├── log_config.py        # 🆕 统一日志配置 (约 230 行)
└── process_registry.py  # 🆕 进程注册表 (约 320 行)

tests/
├── __init__.py
├── test_log_config.py        # 🆕 日志配置测试
└── test_process_registry.py  # 🆕 进程注册表测试

docs/designs/
├── infrastructure-enhancement-plan.md    # 原始计划
└── infrastructure-enhancement-plan-v2.md # 优化后计划
```

---

## 2. 新增模块说明

### 2.1 log_config.py - 统一日志配置

**功能**: 提供简单的日志配置入口，复用标准 logging 模块，自动集成 secrets.py 脱敏。

**核心组件**:

| 组件 | 说明 |
|------|------|
| `LogSubsystem` | 日志子系统枚举 (AGENT, MEMORY, TOOL, LLM, MCP, BROWSER, CHANNEL, PLUGIN) |
| `configure_logging()` | 一次性配置函数，设置日志级别、文件输出、脱敏等 |
| `get_logger()` | 获取子系统日志器 |
| `set_subsystem_level()` | 动态调整子系统日志级别 |
| `log_duration()` | 测量操作耗时的上下文管理器 |
| `RedactionFilter` | 自动脱敏过滤器，复用 secrets.py |

### 2.2 process_registry.py - 进程注册表

**功能**: 追踪所有由 Agent Zero 启动的进程，提供生命周期管理和僵尸清理。

**核心组件**:

| 组件 | 说明 |
|------|------|
| `ProcessStatus` | 进程状态枚举 (PENDING, RUNNING, COMPLETED, FAILED, BACKGROUNDED, TIMEOUT) |
| `ProcessEntry` | 进程条目数据类，包含命令、PID、状态、时间等 |
| `ProcessRegistry` | 单例模式的进程注册表，提供注册、查询、终止、清理等功能 |
| `get_registry()` | 获取全局注册表实例的便捷函数 |

---

## 3. 快速开始

### 3.1 日志配置快速开始

```python
# 在应用启动时调用一次
from python.helpers.log_config import configure_logging, get_logger, LogSubsystem

# 初始化日志系统
configure_logging(
    level="INFO",                    # 日志级别
    log_file="logs/agent.log",       # 可选：输出到文件
    enable_redaction=True            # 自动脱敏敏感信息
)

# 获取子系统日志器
log = get_logger(LogSubsystem.TOOL)

# 记录日志
log.info("Tool execution started")
log.debug("Debug info", extra={"tool_name": "code_execution"})
log.warning("Something might be wrong")
log.error("An error occurred")
```

### 3.2 进程注册表快速开始

```python
from python.helpers.process_registry import get_registry, ProcessEntry

# 获取注册表实例
registry = get_registry()

# 注册新进程
entry = ProcessEntry(command="pip install requests")
registry.register(entry)

# 标记进程状态
registry.mark_running(entry.id, pid=12345)

# 进程完成时
registry.mark_completed(entry.id, exit_code=0)

# 查看状态
print(registry.get_status())
# {'total': 1, 'running': 0, 'completed': 1, ...}
```

---

## 4. 详细使用指南

### 4.1 日志子系统分类

```python
from python.helpers.log_config import get_logger, LogSubsystem

# 不同子系统使用不同的 logger
agent_log = get_logger(LogSubsystem.AGENT)    # Agent 核心逻辑
memory_log = get_logger(LogSubsystem.MEMORY)  # 记忆系统
tool_log = get_logger(LogSubsystem.TOOL)      # 工具执行
llm_log = get_logger(LogSubsystem.LLM)        # LLM 调用
mcp_log = get_logger(LogSubsystem.MCP)        # MCP 服务器
browser_log = get_logger(LogSubsystem.BROWSER) # 浏览器控制
```

### 4.2 动态调整日志级别

```python
from python.helpers.log_config import set_subsystem_level, LogSubsystem

# 调试工具时，提高 TOOL 日志级别
set_subsystem_level(LogSubsystem.TOOL, "DEBUG")

# 减少 LLM 日志噪音
set_subsystem_level(LogSubsystem.LLM, "WARNING")
```

### 4.3 测量操作耗时

```python
from python.helpers.log_config import get_logger, log_duration, LogSubsystem

log = get_logger(LogSubsystem.LLM)

# 使用上下文管理器测量耗时
with log_duration(log, "llm_api_call"):
    response = await call_llm(messages)
# 自动输出: "llm_api_call completed in 1234.56ms"
```

### 4.4 进程生命周期管理

```python
from python.helpers.process_registry import get_registry, ProcessEntry, ProcessStatus

registry = get_registry()

# 完整的进程生命周期
entry = ProcessEntry(
    command="npm install",
    cwd="/workspace/project",
    metadata={"user": "admin", "task_id": "task-123"}
)

# 1. 注册
registry.register(entry)
print(f"Registered: {entry.id}")

# 2. 进程启动后更新 PID
registry.mark_running(entry.id, pid=54321)

# 3. 进程完成
registry.mark_completed(entry.id, exit_code=0)
# 或失败: registry.mark_failed(entry.id, exit_code=1, error="Permission denied")
# 或超时: registry.mark_timeout(entry.id)

# 4. 查询进程信息
entry = registry.get(entry.id)
print(f"Duration: {entry.duration_ms:.2f}ms")
print(f"Status: {entry.status}")
```

### 4.5 进程退出回调

```python
from python.helpers.process_registry import get_registry, ProcessEntry

registry = get_registry()

# 注册退出回调
def on_process_exit(entry):
    print(f"Process {entry.id} exited with code {entry.exit_code}")
    if entry.exit_code != 0:
        # 发送告警
        send_alert(f"Process failed: {entry.command}")

registry.on_exit(on_process_exit)

# 当进程结束时，回调会自动触发
```

### 4.6 僵尸进程清理

```python
from python.helpers.process_registry import get_registry

registry = get_registry()

# 清理运行超过 1 小时的进程
cleaned = registry.cleanup_zombies(max_age_seconds=3600)
print(f"Cleaned {len(cleaned)} zombie processes")

# 可以设置定时任务定期清理
import asyncio

async def periodic_cleanup():
    while True:
        await asyncio.sleep(1800)  # 每 30 分钟
        registry.cleanup_zombies(max_age_seconds=3600)
```

---

## 5. 与现有模块集成

### 5.1 与 secrets.py 集成

日志系统自动集成 secrets.py 进行脱敏：

```python
from python.helpers.log_config import configure_logging, get_logger, LogSubsystem

# 启用脱敏 (默认已启用)
configure_logging(enable_redaction=True)

log = get_logger(LogSubsystem.AGENT)

# 敏感信息会自动被替换为占位符
log.info("Using API key: sk-abc123456789xyz")
# 输出: "Using API key: §§secret(OPENAI_API_KEY)"
```

### 5.2 与 code_execution_tool.py 集成建议

在代码执行工具中使用进程注册表：

```python
# 在 python/tools/code_execution_tool.py 中可以添加:

from python.helpers.process_registry import get_registry, ProcessEntry
from python.helpers.log_config import get_logger, LogSubsystem

log = get_logger(LogSubsystem.TOOL)
registry = get_registry()

async def execute_code(command: str, timeout: int):
    # 注册进程
    entry = ProcessEntry(command=command)
    registry.register(entry)

    log.info(f"Executing command", extra={"entry_id": entry.id})

    try:
        # 执行命令...
        process = await asyncio.create_subprocess_shell(command, ...)
        registry.mark_running(entry.id, pid=process.pid)

        # 等待完成
        exit_code = await asyncio.wait_for(process.wait(), timeout=timeout)
        registry.mark_completed(entry.id, exit_code=exit_code)

    except asyncio.TimeoutError:
        registry.mark_timeout(entry.id)
        log.warning(f"Command timed out", extra={"entry_id": entry.id})

    except Exception as e:
        registry.mark_failed(entry.id, error=str(e))
        log.error(f"Command failed", extra={"entry_id": entry.id, "error": str(e)})
```

### 5.3 与 tty_session.py 集成建议

```python
from python.helpers.tty_session import TTYSession
from python.helpers.process_registry import get_registry, ProcessEntry
from python.helpers.log_config import get_logger, log_duration, LogSubsystem

log = get_logger(LogSubsystem.TOOL)
registry = get_registry()

async def run_interactive_command(command: str):
    entry = ProcessEntry(command=command)
    registry.register(entry)

    session = TTYSession("bash")

    with log_duration(log, f"tty_session:{entry.id}"):
        await session.start()
        registry.mark_running(entry.id, pid=session._proc.pid if session._proc else None)

        await session.sendline(command)
        output = await session.read_full_until_idle(1, 30)

        await session.close()
        registry.mark_completed(entry.id, exit_code=0)

    return output
```

---

## 6. 测试说明

### 6.1 运行测试

```bash
# 进入项目目录
cd H:\AI\agent-zero

# 运行所有测试
pytest tests/ -v

# 只运行日志配置测试
pytest tests/test_log_config.py -v

# 只运行进程注册表测试
pytest tests/test_process_registry.py -v

# 运行并显示覆盖率
pytest tests/ -v --cov=python/helpers --cov-report=html
```

### 6.2 健康检查

```bash
# 一键验证模块是否正常
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
    check('log_config', 'from python.helpers.log_config import configure_logging, get_logger, LogSubsystem; configure_logging(); get_logger(LogSubsystem.AGENT)'),
    check('process_registry', 'from python.helpers.process_registry import get_registry, ProcessEntry; r = get_registry(); e = ProcessEntry(command=\"test\"); r.register(e); print(r.get_status())'),
    check('secrets (existing)', 'from python.helpers.secrets import SecretsManager'),
    check('tty_session (existing)', 'from python.helpers.tty_session import TTYSession'),
]

print(f'\\n总计: {sum(results)}/{len(results)} 模块正常')
sys.exit(0 if all(results) else 1)
"
```

---

## 7. 故障排查

### 7.1 常见问题

#### Q1: 日志没有输出

**原因**: 未调用 `configure_logging()`

**解决**:
```python
from python.helpers.log_config import configure_logging
configure_logging()  # 在应用启动时调用
```

#### Q2: 日志重复输出

**原因**: `configure_logging()` 被调用多次

**解决**: 该函数设计为只执行一次，后续调用会被忽略。检查是否有多处调用。

#### Q3: 敏感信息没有被脱敏

**检查步骤**:
1. 确认 `configure_logging(enable_redaction=True)`
2. 确认密钥已在 `secrets.env` 中注册
3. 测试 secrets.py:
```python
from python.helpers.secrets import SecretsManager
manager = SecretsManager.get_instance()
print(manager.mask_values("sk-abc123"))
```

#### Q4: 进程注册表获取不到进程

**原因**: 进程已被清理或 ID 错误

**解决**:
```python
registry = get_registry()
print(registry.get_status())  # 查看当前状态
print([e.to_dict() for e in registry.list_all()])  # 列出所有进程
```

#### Q5: 僵尸进程清理不生效

**原因**: 进程没有 PID 或权限不足

**解决**:
```python
# 确保注册时提供了 PID
registry.mark_running(entry.id, pid=actual_pid)

# 检查进程是否存在
import os
try:
    os.kill(pid, 0)  # 信号 0 只检查不杀
    print("Process exists")
except ProcessLookupError:
    print("Process not found")
```

---

## 附录

### A. 文件结构总览

```
agent-zero/
├── python/
│   └── helpers/
│       ├── log_config.py        # 🆕 统一日志配置
│       ├── process_registry.py  # 🆕 进程注册表
│       ├── secrets.py           # ✅ 现有 - 敏感信息管理
│       ├── tty_session.py       # ✅ 现有 - TTY 会话
│       └── ...
├── tests/
│   ├── __init__.py
│   ├── test_log_config.py       # 🆕 日志配置测试
│   └── test_process_registry.py # 🆕 进程注册表测试
└── docs/
    └── designs/
        ├── infrastructure-enhancement-plan.md
        ├── infrastructure-enhancement-plan-v2.md
        └── infrastructure-walkthrough.md  # 🆕 本文档
```

### B. API 快速参考

#### log_config.py

| 函数/类 | 说明 |
|---------|------|
| `configure_logging(level, log_file, format_string, enable_redaction, enable_console)` | 配置日志系统 |
| `get_logger(subsystem, context)` | 获取子系统日志器 |
| `set_subsystem_level(subsystem, level)` | 设置子系统日志级别 |
| `get_subsystem_level(subsystem)` | 获取子系统日志级别 |
| `log_duration(logger, operation, level)` | 测量操作耗时 |
| `is_configured()` | 检查是否已配置 |
| `reset_configuration()` | 重置配置 (仅用于测试) |

#### process_registry.py

| 函数/类 | 说明 |
|---------|------|
| `get_registry()` | 获取全局注册表实例 |
| `ProcessRegistry.register(entry)` | 注册进程 |
| `ProcessRegistry.get(entry_id)` | 获取进程条目 |
| `ProcessRegistry.mark_running(entry_id, pid)` | 标记为运行中 |
| `ProcessRegistry.mark_completed(entry_id, exit_code)` | 标记为完成 |
| `ProcessRegistry.mark_failed(entry_id, exit_code, error)` | 标记为失败 |
| `ProcessRegistry.mark_timeout(entry_id)` | 标记为超时 |
| `ProcessRegistry.list_running()` | 列出运行中进程 |
| `ProcessRegistry.kill(entry_id, force)` | 终止进程 |
| `ProcessRegistry.cleanup_zombies(max_age_seconds)` | 清理僵尸进程 |
| `ProcessRegistry.get_status()` | 获取状态摘要 |
| `ProcessRegistry.on_exit(callback)` | 注册退出回调 |

---

> **文档维护者**: AI Assistant
> **最后更新**: 2026-01-31
