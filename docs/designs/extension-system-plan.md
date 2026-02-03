# Agent Zero 扩展系统开发计划

> **版本**: 1.0  
> **创建日期**: 2026-01-30  
> **目标**: 为 Agent Zero 添加完整的扩展能力，包含 Hook 系统和插件系统

---

## 📋 目录

- [1. 项目概述](#1-项目概述)
- [2. 整体架构](#2-整体架构)
- [3. Phase 1: Hook 系统](#3-phase-1-hook-系统)
- [4. Phase 2: 插件系统](#4-phase-2-插件系统)
- [5. 分步实施计划](#5-分步实施计划)
- [6. 测试与验收](#6-测试与验收)

---

## 1. 项目概述

### 1.1 背景

Agent Zero 当前的扩展方式存在以下问题：
- 添加功能需要修改核心代码
- 升级项目时自定义修改容易丢失
- 第三方难以贡献扩展

### 1.2 目标

| 目标 | 描述 |
|------|------|
| **可扩展性** | 不修改核心代码即可添加功能 |
| **可插拔性** | 扩展可以随时启用/禁用 |
| **模块化** | 各扩展相互独立，问题易定位 |

### 1.3 分层架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                         用户扩展层                                   │
│   ┌───────────────┐ ┌───────────────┐ ┌───────────────┐            │
│   │   插件 A      │ │   插件 B      │ │   插件 C      │            │
│   └───────┬───────┘ └───────┬───────┘ └───────┬───────┘            │
│           │                 │                 │                     │
├───────────┴─────────────────┴─────────────────┴─────────────────────┤
│                       Phase 2: 插件系统                              │
│   ┌─────────────────────────────────────────────────────────────┐   │
│   │  PluginLoader → PluginRegistry → PluginAPI                  │   │
│   └─────────────────────────────┬───────────────────────────────┘   │
├─────────────────────────────────┴───────────────────────────────────┤
│                       Phase 1: Hook 系统                             │
│   ┌─────────────────────────────────────────────────────────────┐   │
│   │  HookManager.register() / trigger()                          │   │
│   └─────────────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────────────┤
│                       Agent Zero 核心                               │
│   agent.py │ AgentContext │ Tools │ Memory                          │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. 整体架构

### 2.1 文件结构

```
python/
├── extensions/                      # 扩展系统目录
│   ├── __init__.py
│   ├── hooks/                       # Phase 1: Hook 系统
│   │   ├── __init__.py
│   │   ├── manager.py               # HookManager 核心类
│   │   ├── events.py                # 事件类型定义
│   │   └── decorators.py            # @hook 装饰器
│   │
│   ├── plugins/                     # Phase 2: 插件系统
│   │   ├── __init__.py
│   │   ├── loader.py                # 插件加载器
│   │   ├── registry.py              # 插件注册表
│   │   ├── api.py                   # 插件 API
│   │   └── schema.py                # 配置验证
│   │
│   └── builtin/                     # 内置扩展示例
│       ├── logging_plugin.py
│       └── safety_plugin.py
│
├── helpers/
│   └── ...
└── tools/
    └── ...

plugins/                             # 用户插件目录 (新建)
└── my_plugin/
    ├── plugin.yaml                  # 插件配置
    └── __init__.py                  # 插件入口
```

---

## 3. Phase 1: Hook 系统

### 3.1 概述

Hook 系统是扩展的基础设施，允许在 Agent 执行流程的关键点插入自定义逻辑。

**工作量**: 2 天

---

### 3.2 模块 1: HookManager 核心类

**文件**: `python/extensions/hooks/manager.py`

```python
from typing import Callable, Dict, List, Any, Optional
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
import asyncio
import logging

logger = logging.getLogger(__name__)

class HookPriority(Enum):
    """钩子优先级"""
    HIGHEST = 100
    HIGH = 75
    NORMAL = 50
    LOW = 25
    LOWEST = 0

@dataclass
class HookHandler:
    """钩子处理器"""
    name: str
    handler: Callable
    priority: int = HookPriority.NORMAL.value
    enabled: bool = True

@dataclass
class HookContext:
    """钩子上下文 - 传递给处理器的数据"""
    event: str
    data: Dict[str, Any] = field(default_factory=dict)
    cancelled: bool = False
    cancel_reason: Optional[str] = None

class HookManager:
    """
    Hook 管理器
    
    使用示例:
        hooks = HookManager()
        
        # 注册钩子
        hooks.register("before_send", my_handler, priority=HookPriority.HIGH)
        
        # 触发钩子
        ctx = HookContext(event="before_send", data={"message": "Hello"})
        ctx = await hooks.trigger("before_send", ctx)
        
        if not ctx.cancelled:
            send_message(ctx.data["message"])
    """
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._hooks = defaultdict(list)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self._hooks: Dict[str, List[HookHandler]] = defaultdict(list)
            self._initialized = True
    
    def register(
        self, 
        event: str, 
        handler: Callable,
        name: str = None,
        priority: int = HookPriority.NORMAL.value,
        enabled: bool = True
    ) -> HookHandler:
        """
        注册钩子处理器
        
        Args:
            event: 事件名称 (如 "before_send", "after_tool_call")
            handler: 处理函数，签名为 (ctx: HookContext) -> HookContext | None
            name: 处理器名称 (用于调试和移除)
            priority: 优先级，越高越先执行
            enabled: 是否启用
        
        Returns:
            HookHandler 实例
        """
        hook_handler = HookHandler(
            name=name or handler.__name__,
            handler=handler,
            priority=priority,
            enabled=enabled
        )
        self._hooks[event].append(hook_handler)
        # 按优先级排序 (高优先级在前)
        self._hooks[event].sort(key=lambda h: h.priority, reverse=True)
        logger.debug(f"Registered hook '{hook_handler.name}' for event '{event}'")
        return hook_handler
    
    def unregister(self, event: str, name: str) -> bool:
        """移除钩子"""
        original_len = len(self._hooks[event])
        self._hooks[event] = [h for h in self._hooks[event] if h.name != name]
        return len(self._hooks[event]) < original_len
    
    def enable(self, event: str, name: str) -> bool:
        """启用钩子"""
        for h in self._hooks[event]:
            if h.name == name:
                h.enabled = True
                return True
        return False
    
    def disable(self, event: str, name: str) -> bool:
        """禁用钩子"""
        for h in self._hooks[event]:
            if h.name == name:
                h.enabled = False
                return True
        return False
    
    async def trigger(self, event: str, ctx: HookContext) -> HookContext:
        """
        触发钩子
        
        所有已注册的处理器会按优先级顺序执行。
        如果任何处理器设置 ctx.cancelled = True，后续处理器仍会执行，
        但调用方应检查 cancelled 状态。
        
        Args:
            event: 事件名称
            ctx: 钩子上下文
        
        Returns:
            可能被修改的 HookContext
        """
        handlers = self._hooks.get(event, [])
        
        for handler in handlers:
            if not handler.enabled:
                continue
            
            try:
                if asyncio.iscoroutinefunction(handler.handler):
                    result = await handler.handler(ctx)
                else:
                    result = handler.handler(ctx)
                
                if result is not None:
                    ctx = result
                    
            except Exception as e:
                logger.error(f"Hook error [{event}:{handler.name}]: {e}")
                # 继续执行其他处理器
        
        return ctx
    
    def trigger_sync(self, event: str, ctx: HookContext) -> HookContext:
        """同步触发 (仅用于同步处理器)"""
        handlers = self._hooks.get(event, [])
        
        for handler in handlers:
            if not handler.enabled:
                continue
            
            try:
                result = handler.handler(ctx)
                if result is not None:
                    ctx = result
            except Exception as e:
                logger.error(f"Hook error [{event}:{handler.name}]: {e}")
        
        return ctx
    
    def list_hooks(self, event: str = None) -> Dict[str, List[str]]:
        """列出所有钩子"""
        if event:
            return {event: [h.name for h in self._hooks.get(event, [])]}
        return {e: [h.name for h in handlers] for e, handlers in self._hooks.items()}
    
    def clear(self):
        """清除所有钩子 (主要用于测试)"""
        self._hooks.clear()


# 全局单例
hooks = HookManager()
```

---

### 3.3 模块 2: 事件类型定义

**文件**: `python/extensions/hooks/events.py`

```python
from enum import Enum
from typing import TypedDict, Optional, Any, Dict

class HookEvent(str, Enum):
    """支持的钩子事件"""
    
    # ===== 消息生命周期 =====
    MESSAGE_RECEIVED = "message_received"      # 收到用户消息
    MESSAGE_SENDING = "message_sending"        # 准备发送回复
    MESSAGE_SENT = "message_sent"              # 回复已发送
    
    # ===== Agent 生命周期 =====
    AGENT_START = "agent_start"                # Agent 开始处理
    AGENT_END = "agent_end"                    # Agent 处理完成
    AGENT_ERROR = "agent_error"                # Agent 发生错误
    
    # ===== 工具调用 =====
    BEFORE_TOOL_CALL = "before_tool_call"      # 工具调用前
    AFTER_TOOL_CALL = "after_tool_call"        # 工具调用后
    TOOL_ERROR = "tool_error"                  # 工具执行错误
    
    # ===== LLM 调用 =====
    BEFORE_LLM_CALL = "before_llm_call"        # LLM 调用前
    AFTER_LLM_CALL = "after_llm_call"          # LLM 调用后
    
    # ===== 会话管理 =====
    SESSION_START = "session_start"            # 会话开始
    SESSION_END = "session_end"                # 会话结束
    
    # ===== 记忆系统 =====
    BEFORE_MEMORY_SAVE = "before_memory_save"  # 记忆保存前
    AFTER_MEMORY_LOAD = "after_memory_load"    # 记忆加载后


# ===== 事件数据类型定义 =====

class MessageEventData(TypedDict, total=False):
    """消息事件数据"""
    message: str
    channel: str
    user_id: str
    metadata: Dict[str, Any]

class ToolEventData(TypedDict, total=False):
    """工具事件数据"""
    tool_name: str
    params: Dict[str, Any]
    result: Any
    error: Optional[str]
    duration_ms: float

class LLMEventData(TypedDict, total=False):
    """LLM 事件数据"""
    model: str
    prompt: str
    response: str
    tokens_used: int
    duration_ms: float

class SessionEventData(TypedDict, total=False):
    """会话事件数据"""
    session_id: str
    user_id: str
    message_count: int
    duration_ms: float
```

---

### 3.4 模块 3: 装饰器语法

**文件**: `python/extensions/hooks/decorators.py`

```python
from functools import wraps
from .manager import hooks, HookPriority

def hook(event: str, priority: int = HookPriority.NORMAL.value, name: str = None):
    """
    装饰器：注册钩子处理器
    
    使用示例:
        @hook("before_send", priority=HookPriority.HIGH)
        async def add_signature(ctx):
            ctx.data["message"] += "\\n-- AI Assistant"
            return ctx
    """
    def decorator(func):
        hooks.register(
            event=event,
            handler=func,
            name=name or func.__name__,
            priority=priority
        )
        
        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        
        return wrapper
    
    return decorator
```

---

### 3.5 核心代码集成点

需要在以下位置添加钩子触发：

| 文件 | 位置 | 事件 | 说明 |
|------|------|------|------|
| `agent.py` | `message_loop` 开始 | `message_received` | 收到消息 |
| `agent.py` | `message_loop` 结束前 | `message_sending` | 发送前 |
| `agent.py` | LLM 调用前 | `before_llm_call` | 可修改 prompt |
| `agent.py` | LLM 调用后 | `after_llm_call` | 可处理响应 |
| `agent.py` | 工具调用前 | `before_tool_call` | 可拦截 |
| `agent.py` | 工具调用后 | `after_tool_call` | 可记录 |

**示例改动** (`agent.py`):

```python
from python.extensions.hooks import hooks, HookContext, HookEvent

class Agent:
    async def process_tool_call(self, tool_name, params):
        # 🪝 工具调用前
        ctx = HookContext(
            event=HookEvent.BEFORE_TOOL_CALL,
            data={"tool_name": tool_name, "params": params, "agent": self}
        )
        ctx = await hooks.trigger(HookEvent.BEFORE_TOOL_CALL, ctx)
        
        if ctx.cancelled:
            return f"Tool call blocked: {ctx.cancel_reason}"
        
        # 执行工具 (可能被 hook 修改了参数)
        tool_name = ctx.data["tool_name"]
        params = ctx.data["params"]
        
        result = await self.execute_tool(tool_name, params)
        
        # 🪝 工具调用后
        ctx = HookContext(
            event=HookEvent.AFTER_TOOL_CALL,
            data={"tool_name": tool_name, "params": params, "result": result}
        )
        ctx = await hooks.trigger(HookEvent.AFTER_TOOL_CALL, ctx)
        
        return ctx.data.get("result", result)
```

---

## 4. Phase 2: 插件系统

### 4.1 概述

插件系统基于 Hook 系统，提供更完整的扩展能力。

**工作量**: 4 天

---

### 4.2 模块 1: 插件加载器

**文件**: `python/extensions/plugins/loader.py`

```python
import os
import sys
import yaml
import importlib.util
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

@dataclass
class PluginManifest:
    """插件清单"""
    id: str
    name: str
    version: str = "1.0.0"
    description: str = ""
    author: str = ""
    enabled: bool = True
    dependencies: List[str] = None
    config_schema: Dict = None

@dataclass  
class PluginInfo:
    """插件信息"""
    manifest: PluginManifest
    path: Path
    module: object = None
    status: str = "unloaded"  # unloaded, loaded, error
    error: str = None

class PluginLoader:
    """插件加载器"""
    
    def __init__(self, plugin_dirs: List[str] = None):
        self.plugin_dirs = plugin_dirs or [
            "plugins",           # 用户插件
            "python/extensions/builtin"  # 内置插件
        ]
        self.plugins: Dict[str, PluginInfo] = {}
    
    def discover(self) -> List[PluginInfo]:
        """发现所有插件"""
        discovered = []
        
        for plugin_dir in self.plugin_dirs:
            dir_path = Path(plugin_dir)
            if not dir_path.exists():
                continue
            
            for item in dir_path.iterdir():
                if not item.is_dir():
                    continue
                
                manifest_path = item / "plugin.yaml"
                if not manifest_path.exists():
                    # 尝试 __init__.py 作为简单插件
                    init_path = item / "__init__.py"
                    if init_path.exists():
                        manifest = PluginManifest(
                            id=item.name,
                            name=item.name,
                        )
                        discovered.append(PluginInfo(manifest=manifest, path=item))
                    continue
                
                try:
                    with open(manifest_path, "r", encoding="utf-8") as f:
                        data = yaml.safe_load(f)
                    
                    manifest = PluginManifest(
                        id=data.get("id", item.name),
                        name=data.get("name", item.name),
                        version=data.get("version", "1.0.0"),
                        description=data.get("description", ""),
                        author=data.get("author", ""),
                        enabled=data.get("enabled", True),
                        dependencies=data.get("dependencies", []),
                        config_schema=data.get("config_schema"),
                    )
                    discovered.append(PluginInfo(manifest=manifest, path=item))
                    
                except Exception as e:
                    logger.error(f"Failed to load manifest for {item.name}: {e}")
        
        return discovered
    
    def load(self, plugin_info: PluginInfo) -> bool:
        """加载单个插件"""
        if not plugin_info.manifest.enabled:
            plugin_info.status = "disabled"
            return False
        
        try:
            init_path = plugin_info.path / "__init__.py"
            if not init_path.exists():
                raise FileNotFoundError(f"Plugin entry point not found: {init_path}")
            
            spec = importlib.util.spec_from_file_location(
                plugin_info.manifest.id,
                init_path
            )
            module = importlib.util.module_from_spec(spec)
            sys.modules[plugin_info.manifest.id] = module
            spec.loader.exec_module(module)
            
            # 调用插件的 register 或 activate 函数
            if hasattr(module, "register"):
                from .api import PluginAPI
                api = PluginAPI(plugin_info)
                module.register(api)
            elif hasattr(module, "activate"):
                from .api import PluginAPI
                api = PluginAPI(plugin_info)
                module.activate(api)
            
            plugin_info.module = module
            plugin_info.status = "loaded"
            self.plugins[plugin_info.manifest.id] = plugin_info
            
            logger.info(f"Loaded plugin: {plugin_info.manifest.name} v{plugin_info.manifest.version}")
            return True
            
        except Exception as e:
            plugin_info.status = "error"
            plugin_info.error = str(e)
            logger.error(f"Failed to load plugin {plugin_info.manifest.id}: {e}")
            return False
    
    def load_all(self) -> Dict[str, PluginInfo]:
        """加载所有发现的插件"""
        discovered = self.discover()
        
        for plugin_info in discovered:
            self.load(plugin_info)
        
        return self.plugins
    
    def unload(self, plugin_id: str) -> bool:
        """卸载插件"""
        if plugin_id not in self.plugins:
            return False
        
        plugin_info = self.plugins[plugin_id]
        
        if hasattr(plugin_info.module, "deactivate"):
            try:
                plugin_info.module.deactivate()
            except Exception as e:
                logger.error(f"Error deactivating plugin {plugin_id}: {e}")
        
        if plugin_id in sys.modules:
            del sys.modules[plugin_id]
        
        del self.plugins[plugin_id]
        logger.info(f"Unloaded plugin: {plugin_id}")
        return True
```

---

### 4.3 模块 2: 插件 API

**文件**: `python/extensions/plugins/api.py`

```python
from typing import Callable, List, Dict, Any
from ..hooks import hooks, HookPriority, HookEvent
from .loader import PluginInfo
import logging

logger = logging.getLogger(__name__)

class PluginAPI:
    """
    插件 API - 提供给插件的标准接口
    
    使用示例:
        def register(api: PluginAPI):
            # 注册钩子
            api.on("before_send", add_footer)
            
            # 注册工具
            api.register_tool(MyCustomTool)
            
            # 注册命令
            api.register_command("status", show_status)
    """
    
    def __init__(self, plugin_info: PluginInfo):
        self.plugin = plugin_info
        self.id = plugin_info.manifest.id
        self.name = plugin_info.manifest.name
        self.version = plugin_info.manifest.version
        self.logger = logging.getLogger(f"plugin.{self.id}")
        
        # 注册的资源 (用于卸载时清理)
        self._registered_hooks: List[tuple] = []
        self._registered_tools: List[str] = []
        self._registered_commands: List[str] = []
    
    # ===== Hook 相关 =====
    
    def on(
        self, 
        event: str, 
        handler: Callable,
        priority: int = HookPriority.NORMAL.value
    ):
        """
        注册事件钩子
        
        Args:
            event: 事件名，可用 HookEvent 枚举或字符串
            handler: 处理函数
            priority: 优先级
        """
        name = f"{self.id}:{handler.__name__}"
        hooks.register(event=event, handler=handler, name=name, priority=priority)
        self._registered_hooks.append((event, name))
        self.logger.debug(f"Registered hook: {event} -> {handler.__name__}")
    
    def off(self, event: str, handler: Callable):
        """移除钩子"""
        name = f"{self.id}:{handler.__name__}"
        hooks.unregister(event, name)
        self._registered_hooks = [(e, n) for e, n in self._registered_hooks if not (e == event and n == name)]
    
    # ===== 工具注册 =====
    
    def register_tool(self, tool_class, name: str = None):
        """
        注册自定义工具
        
        Args:
            tool_class: 工具类 (继承自 Tool)
            name: 工具名称 (可选)
        """
        # TODO: 与 Agent Zero 的 Tool 系统集成
        tool_name = name or tool_class.__name__
        self._registered_tools.append(tool_name)
        self.logger.debug(f"Registered tool: {tool_name}")
    
    # ===== 命令注册 =====
    
    def register_command(self, name: str, handler: Callable, description: str = ""):
        """
        注册 /斜杠命令 (绕过 LLM 直接执行)
        
        Args:
            name: 命令名 (不含 /)
            handler: 处理函数
            description: 命令描述
        """
        # TODO: 与命令系统集成
        self._registered_commands.append(name)
        self.logger.debug(f"Registered command: /{name}")
    
    # ===== 配置相关 =====
    
    def get_config(self, key: str = None, default: Any = None) -> Any:
        """获取插件配置"""
        # TODO: 从配置文件读取
        return default
    
    # ===== 工具方法 =====
    
    def log(self, message: str, level: str = "info"):
        """记录日志"""
        getattr(self.logger, level, self.logger.info)(message)
    
    def cleanup(self):
        """清理插件注册的所有资源"""
        for event, name in self._registered_hooks:
            hooks.unregister(event, name)
        
        self._registered_hooks.clear()
        self._registered_tools.clear()
        self._registered_commands.clear()
```

---

### 4.4 模块 3: 插件配置验证

**文件**: `python/extensions/plugins/schema.py`

```python
from typing import Dict, Any, List, Tuple
from dataclasses import dataclass

@dataclass
class ValidationResult:
    valid: bool
    errors: List[str] = None
    
    def __post_init__(self):
        if self.errors is None:
            self.errors = []

def validate_plugin_config(schema: Dict, config: Dict) -> ValidationResult:
    """
    验证插件配置是否符合 schema
    
    简化版 JSON Schema 验证
    """
    errors = []
    
    if not schema:
        return ValidationResult(valid=True)
    
    required = schema.get("required", [])
    properties = schema.get("properties", {})
    
    # 检查必填字段
    for field in required:
        if field not in config:
            errors.append(f"Missing required field: {field}")
    
    # 检查字段类型
    for field, value in config.items():
        if field not in properties:
            continue
        
        expected_type = properties[field].get("type")
        if expected_type:
            type_map = {
                "string": str,
                "number": (int, float),
                "integer": int,
                "boolean": bool,
                "array": list,
                "object": dict,
            }
            expected = type_map.get(expected_type)
            if expected and not isinstance(value, expected):
                errors.append(f"Field '{field}' should be {expected_type}, got {type(value).__name__}")
    
    return ValidationResult(valid=len(errors) == 0, errors=errors)
```

---

### 4.5 插件示例

**文件**: `plugins/my_plugin/plugin.yaml`

```yaml
id: my_plugin
name: My Custom Plugin
version: 1.0.0
description: A sample plugin demonstrating the API
author: Your Name
enabled: true

config_schema:
  type: object
  properties:
    api_key:
      type: string
      description: API Key for external service
    log_level:
      type: string
      default: info
  required:
    - api_key
```

**文件**: `plugins/my_plugin/__init__.py`

```python
from python.extensions.plugins.api import PluginAPI
from python.extensions.hooks import HookContext, HookEvent

def register(api: PluginAPI):
    """插件入口"""
    api.log(f"Loading plugin: {api.name} v{api.version}")
    
    # 注册钩子: 消息发送前添加签名
    @api.on(HookEvent.MESSAGE_SENDING)
    async def add_signature(ctx: HookContext):
        if "message" in ctx.data:
            ctx.data["message"] += "\n\n-- Powered by MyPlugin"
        return ctx
    
    # 注册钩子: 监控工具调用
    @api.on(HookEvent.AFTER_TOOL_CALL)
    async def log_tool_calls(ctx: HookContext):
        tool_name = ctx.data.get("tool_name", "unknown")
        duration = ctx.data.get("duration_ms", 0)
        api.log(f"Tool '{tool_name}' executed in {duration}ms")
        return ctx

def deactivate():
    """插件卸载时调用"""
    print("MyPlugin deactivated")
```

---

## 5. 分步实施计划

```
┌──────────────────────────────────────────────────────────────────────┐
│  Phase 1: Hook 系统 (2 天)                                           │
├──────────────────────────────────────────────────────────────────────┤
│  Step 1.1 (0.5天): HookManager 核心类                                │
│    - 创建 manager.py                                                 │
│    - 实现 register/trigger/unregister                               │
│    - 单元测试                                                        │
├──────────────────────────────────────────────────────────────────────┤
│  Step 1.2 (0.5天): 事件定义和装饰器                                   │
│    - 创建 events.py                                                  │
│    - 创建 decorators.py                                             │
│    - 单元测试                                                        │
├──────────────────────────────────────────────────────────────────────┤
│  Step 1.3 (1天): 核心代码集成                                        │
│    - 在 agent.py 添加触发点                                          │
│    - 在关键工具添加触发点                                             │
│    - 集成测试                                                        │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│  Phase 2: 插件系统 (4 天)                                            │
├──────────────────────────────────────────────────────────────────────┤
│  Step 2.1 (1天): 插件加载器                                          │
│    - 创建 loader.py                                                  │
│    - 实现 discover/load/unload                                       │
│    - 单元测试                                                        │
├──────────────────────────────────────────────────────────────────────┤
│  Step 2.2 (1天): 插件 API                                            │
│    - 创建 api.py                                                     │
│    - 实现 on/register_tool/register_command                         │
│    - 单元测试                                                        │
├──────────────────────────────────────────────────────────────────────┤
│  Step 2.3 (1天): 配置验证和示例插件                                   │
│    - 创建 schema.py                                                  │
│    - 创建示例插件                                                    │
│    - 集成测试                                                        │
├──────────────────────────────────────────────────────────────────────┤
│  Step 2.4 (1天): 与启动流程集成                                       │
│    - 在 main.py/initialize.py 加载插件                               │
│    - 配置文件支持                                                    │
│    - 端到端测试                                                      │
└──────────────────────────────────────────────────────────────────────┘

总计: 6 天
```

---

## 6. 测试与验收

### 6.1 单元测试清单

| 模块 | 测试文件 | 测试点 |
|------|----------|--------|
| HookManager | test_hooks.py | register/trigger/unregister/priority |
| PluginLoader | test_loader.py | discover/load/unload |
| PluginAPI | test_api.py | on/off/register_tool |
| Schema | test_schema.py | validate_plugin_config |

### 6.2 集成测试

```python
# tests/integration/test_extension_system.py

async def test_hook_blocks_dangerous_tool():
    """测试钩子可以阻止危险工具调用"""
    from python.extensions.hooks import hooks, HookContext, HookEvent
    
    # 注册安全检查钩子
    def block_rm_rf(ctx):
        if "rm -rf" in str(ctx.data.get("params", {})):
            ctx.cancelled = True
            ctx.cancel_reason = "Dangerous command blocked"
        return ctx
    
    hooks.register(HookEvent.BEFORE_TOOL_CALL, block_rm_rf)
    
    # 触发
    ctx = HookContext(
        event=HookEvent.BEFORE_TOOL_CALL,
        data={"tool_name": "code_execution", "params": {"code": "rm -rf /"}}
    )
    ctx = await hooks.trigger(HookEvent.BEFORE_TOOL_CALL, ctx)
    
    assert ctx.cancelled == True
    assert "Dangerous" in ctx.cancel_reason

async def test_plugin_loads_and_registers_hooks():
    """测试插件加载并注册钩子"""
    from python.extensions.plugins.loader import PluginLoader
    
    loader = PluginLoader(["plugins"])
    plugins = loader.load_all()
    
    # 验证插件已加载
    assert "my_plugin" in plugins
    assert plugins["my_plugin"].status == "loaded"
```

### 6.3 验收标准

| 功能 | 标准 | 验证方法 |
|------|------|----------|
| Hook 注册 | 能注册多个处理器 | 单元测试 |
| 优先级 | 高优先级先执行 | 单元测试 |
| 取消机制 | cancelled=True 可阻止操作 | 集成测试 |
| 插件发现 | 自动发现 plugins/ 目录 | 集成测试 |
| 插件加载 | 调用 register() | 集成测试 |
| 热卸载 | unload 后钩子失效 | 集成测试 |

---

## 附录

### A. 依赖

```
# 无需额外依赖，使用 Python 标准库
# 可选: pyyaml (插件配置文件)
pyyaml>=6.0
```

### B. 配置文件

```yaml
# conf/extensions.yaml
extensions:
  enabled: true
  plugin_dirs:
    - plugins
    - python/extensions/builtin
  
  disabled_plugins:
    - some_plugin_to_disable
```

---

> **文档维护者**: AI Assistant  
> **最后更新**: 2026-01-30
