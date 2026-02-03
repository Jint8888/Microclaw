# Agent Zero 多渠道网关开发计划

> **版本**: 2.1
> **创建日期**: 2026-01-30
> **更新日期**: 2026-02-01
> **目标**: 为 Agent Zero 构建统一的消息网关，**所有请求（Web UI + 渠道）统一经过 Gateway**，实现统一入口、统一认证、统一会话管理

---

## 📋 目录

- [1. 项目概述](#1-项目概述)
- [2. 整体架构设计](#2-整体架构设计)
- [3. 分阶段实施计划](#3-分阶段实施计划)
- [4. Gateway 核心框架](#4-gateway-核心框架)
- [5. 渠道适配器](#5-渠道适配器)
- [6. 高级功能](#6-高级功能)
- [7. 部署与运维](#7-部署与运维)
- [8. 测试与验收](#8-测试与验收)

---

## 1. 项目概述

### 1.1 背景

OpenClaw 的核心设计是一个 **常驻运行的 Gateway 进程**，所有渠道连接（Telegram、Discord、WhatsApp 等）都作为 Gateway 的插件运行在其内部。本项目为 Agent Zero 构建类似的网关架构。

### 1.2 核心概念

**统一入口原则**：所有客户端请求（Web UI 浏览器前端 + Telegram/Discord 等渠道）都必须通过 Gateway 访问 Agent Zero。

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Gateway 进程                                  │
│                  (常驻运行，统一入口，端口: 18900)                    │
│                                                                      │
│   ┌───────────────────────────────────────────────────────────┐     │
│   │                      客户端接入层                          │     │
│   │                                                            │     │
│   │   🌐 Web UI        📱 Telegram     💬 Discord    ...      │     │
│   │   (浏览器前端)      (Bot API)       (Bot API)              │     │
│   │   ├─ HTTP API      ├─ Polling      ├─ Gateway             │     │
│   │   └─ WebSocket     └─ Webhook      └─ WebSocket           │     │
│   │         │                │                │                │     │
│   │         └────────────────┴────────────────┘                │     │
│   │                          │                                 │     │
│   └──────────────────────────┼─────────────────────────────────┘     │
│                              ▼                                       │
│   ┌──────────────────────────────────────────────────────────┐      │
│   │                   ChannelManager                          │      │
│   │            (统一消息路由、会话管理、白名单)                 │      │
│   │                                                            │      │
│   │   会话键格式: {channel}:{account_id}:{user_id}            │      │
│   │   ├─ web:default:session_abc123     (浏览器用户)          │      │
│   │   ├─ telegram:main:456789           (Telegram 用户)       │      │
│   │   └─ discord:main:123456789         (Discord 用户)        │      │
│   └──────────────────────────┬───────────────────────────────┘      │
│                              │                                       │
│   ┌──────────────────────────┴───────────────────────────────┐      │
│   │                   Gateway Server                          │      │
│   │                                                            │      │
│   │  【Web UI 专用 API】                                       │      │
│   │  ├─ POST /api/chat           (Web UI 发送消息)            │      │
│   │  ├─ GET  /api/chat/history   (获取对话历史)               │      │
│   │  ├─ WS   /ws/chat            (Web UI 实时对话+流式响应)   │      │
│   │                                                            │      │
│   │  【通用管理 API】                                          │      │
│   │  ├─ GET  /api/health         (健康检查)                   │      │
│   │  ├─ GET  /api/status         (网关状态)                   │      │
│   │  ├─ GET  /api/channels       (渠道列表)                   │      │
│   │  ├─ POST /api/send           (发送消息到指定渠道)         │      │
│   │  ├─ POST /api/reload         (热重载配置)                 │      │
│   │  └─ WS   /ws                 (系统事件推送)               │      │
│   └──────────────────────────────────────────────────────────┘      │
│                              │                                       │
└──────────────────────────────┼───────────────────────────────────────┘
                               │
                               ▼
                     ┌───────────────────┐
                     │   Agent Zero Core │
                     └───────────────────┘
```

### 1.3 设计原则

| 原则 | 说明 |
|------|------|
| **统一入口** | Web UI 和所有渠道都通过 Gateway 访问 Agent |
| **网关优先** | Gateway 是核心，渠道和 Web UI 都是客户端 |
| **统一认证** | 所有请求在 Gateway 层统一验证 Token |
| **统一会话** | 跨渠道会话使用统一格式管理 |
| **常驻运行** | 7x24 运行，支持系统服务托管 |
| **可观测性** | 健康检查、状态 API、日志 |
| **可维护性** | 配置热重载、优雅重启 |
| **可扩展性** | 插件化渠道、统一接口 |

---

## 2. 整体架构设计

### 2.1 文件结构

```
python/
├── gateway/                        # 🆕 网关核心
│   ├── __init__.py
│   ├── server.py                   # Gateway 服务器 (HTTP + WebSocket)
│   ├── config.py                   # 配置管理 + 热重载
│   ├── health.py                   # 健康检查
│   └── protocol.py                 # 通信协议定义
│
├── channels/                       # 渠道模块 (网关插件)
│   ├── __init__.py
│   ├── base.py                     # 适配器基类 + 消息模型
│   ├── manager.py                  # 渠道管理器
│   ├── security.py                 # 安全模块
│   ├── telegram_adapter.py         # Telegram 适配器
│   └── discord_adapter.py          # Discord 适配器
│
└── agent.py                        # Agent Zero 核心

conf/
├── gateway.yaml                    # 🆕 网关配置
└── channels.yaml                   # 渠道配置

run_gateway.py                      # 🆕 网关启动入口
```

### 2.2 运行模式

```bash
# 启动网关 (前台运行，开发调试)
python run_gateway.py

# 启动网关 (指定端口)
python run_gateway.py --port 18900

# 启动网关 (后台服务模式)
python run_gateway.py --daemon

# 健康检查
curl http://localhost:18900/api/health

# 发送消息 (通过 HTTP API)
curl -X POST http://localhost:18900/api/send \
  -H "Content-Type: application/json" \
  -d '{"channel": "telegram", "chat_id": "123", "message": "Hello"}'
```

---

## 3. 分阶段实施计划

### 3.1 开发阶段概览

```
┌──────────────────────────────────────────────────────────────────────┐
│  Phase 1: Gateway 核心 + Web UI 集成 (Day 1-4)            【最优先】 │
│  ├─ Gateway Server (HTTP API + WebSocket 基础框架)                  │
│  ├─ Web UI 对话 API (/api/chat, /ws/chat)        【浏览器前端入口】 │
│  ├─ Web UI 流式响应支持                                             │
│  ├─ 会话管理 (统一会话键格式)                                       │
│  ├─ 配置管理 + 热重载                                               │
│  ├─ 健康检查 + 状态 API                                             │
│  ├─ ChannelManager 框架                                             │
│  └─ 消息模型 + 适配器基类                                           │
├──────────────────────────────────────────────────────────────────────┤
│  Phase 2: Telegram 适配器 (Day 5-6)                                 │
│  ├─ Bot 连接 + 消息监听                                             │
│  ├─ 群聊 @提及检测                                                   │
│  ├─ 消息格式转换                                                     │
│  └─ 与 Gateway 集成测试                                              │
├──────────────────────────────────────────────────────────────────────┤
│  Phase 3: Discord 适配器 (Day 7-9)                                  │
│  ├─ Bot 连接 + 消息监听                                             │
│  ├─ 并发启动处理                                                     │
│  ├─ 斜杠命令支持                                                     │
│  └─ 与 Gateway 集成测试                                              │
├──────────────────────────────────────────────────────────────────────┤
│  Phase 4: 高级功能 + 服务化 (Day 10-11)                             │
│  ├─ 远程访问 (Token 认证)                                            │
│  ├─ 对话历史 API                                                     │
│  ├─ systemd/launchd 服务配置                                        │
│  └─ 完整测试 + 文档                                                  │
└──────────────────────────────────────────────────────────────────────┘
```

### 3.2 Phase 1 详细任务 (Gateway + Web UI)

> **核心目标**: 完成 Gateway 框架，使 Web UI 浏览器前端可以通过 Gateway 与 Agent Zero 对话。

| Day | 任务 | 交付物 |
|-----|------|--------|
| **Day 1** | Gateway 基础框架 | `server.py`, `config.py`, `protocol.py` |
| **Day 1** | 配置加载 + 环境变量 | `gateway.yaml` 配置文件 |
| **Day 2** | Web UI 对话 API | `POST /api/chat`, `GET /api/chat/history` |
| **Day 2** | WebSocket 实时对话 | `WS /ws/chat` (支持流式响应) |
| **Day 3** | 会话管理 | 统一会话键、会话存储 |
| **Day 3** | 健康检查 | `health.py`, `/api/health`, `/api/status` |
| **Day 4** | ChannelManager 框架 | `manager.py`, `base.py` |
| **Day 4** | 集成测试 | Web UI 能通过 Gateway 对话 |

**Phase 1 验收标准**:
- ✅ Gateway 启动成功，监听端口 18900
- ✅ Web UI 通过 `POST /api/chat` 发送消息，收到 Agent 响应
- ✅ Web UI 通过 `WS /ws/chat` 实现流式对话
- ✅ `/api/health` 返回健康状态
- ✅ 配置热重载生效

---

## 4. Gateway 核心框架

### 4.1 Gateway Server

**文件**: `python/gateway/server.py`

```python
"""
Agent Zero Gateway Server

核心网关服务器，提供:
- HTTP API (健康检查、状态、消息发送)
- WebSocket (实时事件推送)
- 配置热重载
- 渠道生命周期管理
"""

import asyncio
import logging
import signal
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import uvicorn

from .config import GatewayConfig, ConfigWatcher
from .health import HealthChecker, HealthStatus
from .protocol import GatewayEvent, EventType
from ..channels.manager import ChannelManager
from ..channels.base import OutboundMessage

logger = logging.getLogger("gateway.server")


@dataclass
class GatewayState:
    """网关运行状态"""
    started_at: datetime = field(default_factory=datetime.now)
    config: GatewayConfig = None
    channel_manager: ChannelManager = None
    health_checker: HealthChecker = None
    config_watcher: ConfigWatcher = None
    websocket_clients: set = field(default_factory=set)
    is_shutting_down: bool = False


# 全局状态
state = GatewayState()
security = HTTPBearer(auto_error=False)


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> bool:
    """验证 API Token"""
    if not state.config or not state.config.auth_token:
        return True  # 未配置 token 则允许

    if not credentials:
        raise HTTPException(status_code=401, detail="Missing authorization token")

    if credentials.credentials != state.config.auth_token:
        raise HTTPException(status_code=403, detail="Invalid token")

    return True


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("Gateway starting...")

    # 初始化
    await startup()

    yield

    # 清理
    await shutdown()


async def startup():
    """启动初始化"""
    from ..channels.telegram_adapter import TelegramAdapter
    from ..channels.discord_adapter import DiscordAdapter

    # 加载配置
    state.config = GatewayConfig.load()
    logger.info(f"Loaded config from {state.config.config_path}")

    # 初始化健康检查器
    state.health_checker = HealthChecker(state)

    # 初始化渠道管理器
    # 注意: 这里需要根据实际的 Agent Zero 接口调整
    from ..agent import AgentContext
    agent_context = AgentContext()

    state.channel_manager = ChannelManager(agent_context)

    # 注册渠道
    channels_config = state.config.channels
    for channel_name, channel_cfg in channels_config.items():
        if not channel_cfg.get("enabled", False):
            continue

        try:
            if channel_name == "telegram" and channel_cfg.get("token"):
                adapter = TelegramAdapter(channel_cfg, channel_cfg.get("account_id", "default"))
                state.channel_manager.register(f"telegram:{adapter.account_id}", adapter)
                logger.info(f"Registered channel: telegram:{adapter.account_id}")

            elif channel_name == "discord" and channel_cfg.get("token"):
                adapter = DiscordAdapter(channel_cfg, channel_cfg.get("account_id", "default"))
                state.channel_manager.register(f"discord:{adapter.account_id}", adapter)
                logger.info(f"Registered channel: discord:{adapter.account_id}")

        except Exception as e:
            logger.error(f"Failed to register {channel_name}: {e}")

    # 启动渠道
    if state.channel_manager.channels:
        await state.channel_manager.start_all()
        logger.info(f"Started {len(state.channel_manager.channels)} channel(s)")

    # 启动配置热重载监视器
    if state.config.hot_reload:
        state.config_watcher = ConfigWatcher(state.config.config_path, on_config_change)
        await state.config_watcher.start()
        logger.info("Config hot-reload enabled")

    logger.info(f"Gateway started on port {state.config.port}")


async def shutdown():
    """优雅关闭"""
    logger.info("Gateway shutting down...")
    state.is_shutting_down = True

    # 通知所有 WebSocket 客户端
    await broadcast_event(GatewayEvent(
        type=EventType.SHUTDOWN,
        payload={"reason": "Gateway shutting down"}
    ))

    # 停止配置监视器
    if state.config_watcher:
        await state.config_watcher.stop()

    # 停止渠道
    if state.channel_manager:
        await state.channel_manager.stop_all()

    logger.info("Gateway stopped")


async def on_config_change(new_config: dict):
    """配置变更回调"""
    logger.info("Config changed, reloading...")

    # 广播配置变更事件
    await broadcast_event(GatewayEvent(
        type=EventType.CONFIG_RELOAD,
        payload={"message": "Configuration reloaded"}
    ))

    # 这里可以实现更细粒度的热重载逻辑
    # 例如只重载变更的渠道，而不是全部重启


async def broadcast_event(event: GatewayEvent):
    """广播事件到所有 WebSocket 客户端"""
    if not state.websocket_clients:
        return

    message = event.to_json()
    disconnected = set()

    for ws in state.websocket_clients:
        try:
            await ws.send_text(message)
        except:
            disconnected.add(ws)

    state.websocket_clients -= disconnected


# ============ FastAPI 应用 ============

app = FastAPI(
    title="Agent Zero Gateway",
    version="2.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============ HTTP API ============

@app.get("/api/health")
async def health_check():
    """健康检查

    返回网关健康状态，用于监控和负载均衡探针。
    """
    status = await state.health_checker.check()
    return {
        "status": status.status,
        "uptime_seconds": status.uptime_seconds,
        "channels": status.channels,
        "checks": status.checks,
        "timestamp": status.timestamp.isoformat(),
    }


@app.get("/api/status")
async def gateway_status(authorized: bool = Depends(verify_token)):
    """网关状态

    返回详细的网关运行状态。
    """
    return {
        "started_at": state.started_at.isoformat(),
        "uptime_seconds": (datetime.now() - state.started_at).total_seconds(),
        "config": {
            "port": state.config.port,
            "hot_reload": state.config.hot_reload,
        },
        "channels": state.channel_manager.list_channels() if state.channel_manager else {},
        "websocket_clients": len(state.websocket_clients),
        "is_shutting_down": state.is_shutting_down,
    }


@app.get("/api/channels")
async def list_channels(authorized: bool = Depends(verify_token)):
    """列出所有渠道"""
    if not state.channel_manager:
        return {"channels": {}}
    return {"channels": state.channel_manager.list_channels()}


@app.post("/api/send")
async def send_message(
    channel: str,
    chat_id: str,
    message: str,
    reply_to: Optional[str] = None,
    authorized: bool = Depends(verify_token)
):
    """发送消息

    通过 HTTP API 发送消息到指定渠道。
    """
    if not state.channel_manager:
        raise HTTPException(status_code=503, detail="Channel manager not initialized")

    adapter = state.channel_manager.get_channel(channel)
    if not adapter:
        raise HTTPException(status_code=404, detail=f"Channel not found: {channel}")

    try:
        await adapter.send(chat_id, OutboundMessage(
            content=message,
            reply_to_id=reply_to
        ))
        return {"success": True, "channel": channel, "chat_id": chat_id}
    except Exception as e:
        logger.error(f"Failed to send message: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/reload")
async def reload_config(authorized: bool = Depends(verify_token)):
    """手动触发配置重载"""
    try:
        new_config = GatewayConfig.load()
        await on_config_change(new_config.__dict__)
        return {"success": True, "message": "Configuration reloaded"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============ WebSocket ============

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 连接

    实时事件推送：
    - agent: Agent 响应流
    - presence: 状态变更
    - config_reload: 配置重载
    - shutdown: 网关关闭
    """
    await websocket.accept()
    state.websocket_clients.add(websocket)
    logger.info(f"WebSocket client connected, total: {len(state.websocket_clients)}")

    try:
        # 发送欢迎消息
        await websocket.send_json({
            "type": "hello",
            "payload": {
                "version": "2.0.0",
                "uptime_seconds": (datetime.now() - state.started_at).total_seconds(),
                "channels": list(state.channel_manager.channels.keys()) if state.channel_manager else [],
            }
        })

        # 保持连接
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                # 处理客户端消息（如果需要）
            except asyncio.TimeoutError:
                # 发送心跳
                await websocket.send_json({"type": "ping"})

    except WebSocketDisconnect:
        pass
    finally:
        state.websocket_clients.discard(websocket)
        logger.info(f"WebSocket client disconnected, remaining: {len(state.websocket_clients)}")


# ============ 启动函数 ============

def run_gateway(
    host: str = "127.0.0.1",
    port: int = 18900,
    reload: bool = False,
    log_level: str = "info"
):
    """运行 Gateway 服务器"""
    uvicorn.run(
        "python.gateway.server:app",
        host=host,
        port=port,
        reload=reload,
        log_level=log_level,
    )
```

### 4.2 配置管理 + 热重载

**文件**: `python/gateway/config.py`

```python
"""
Gateway 配置管理

支持:
- YAML 配置文件
- 环境变量覆盖
- 配置热重载
"""

import os
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Callable
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import yaml

logger = logging.getLogger("gateway.config")


@dataclass
class GatewayConfig:
    """网关配置"""
    # 基础配置
    port: int = 18900
    host: str = "127.0.0.1"
    config_path: str = "conf/gateway.yaml"

    # 安全配置
    auth_token: Optional[str] = None
    auth_password: Optional[str] = None

    # 功能开关
    hot_reload: bool = True
    verbose: bool = False

    # 渠道配置
    channels: Dict[str, Any] = field(default_factory=dict)

    # 高级配置
    max_payload_size: int = 10 * 1024 * 1024  # 10MB
    tick_interval_ms: int = 30000  # 30秒心跳
    websocket_timeout: int = 60  # WebSocket 超时

    @classmethod
    def load(cls, config_path: str = None) -> "GatewayConfig":
        """加载配置"""
        path = config_path or os.environ.get("GATEWAY_CONFIG_PATH", "conf/gateway.yaml")

        config = cls(config_path=path)

        # 从文件加载
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}

            # 网关配置
            gateway = data.get("gateway", {})
            config.port = gateway.get("port", config.port)
            config.host = gateway.get("host", config.host)
            config.hot_reload = gateway.get("hot_reload", config.hot_reload)
            config.verbose = gateway.get("verbose", config.verbose)

            # 认证配置
            auth = gateway.get("auth", {})
            config.auth_token = auth.get("token")
            config.auth_password = auth.get("password")

            # 渠道配置
            config.channels = data.get("channels", {})

        # 环境变量覆盖
        config.port = int(os.environ.get("GATEWAY_PORT", config.port))
        config.host = os.environ.get("GATEWAY_HOST", config.host)
        config.auth_token = os.environ.get("GATEWAY_AUTH_TOKEN", config.auth_token)

        # 替换渠道配置中的环境变量
        config.channels = cls._replace_env_vars(config.channels)

        return config

    @staticmethod
    def _replace_env_vars(obj):
        """递归替换环境变量"""
        if isinstance(obj, str) and obj.startswith("${") and obj.endswith("}"):
            env_key = obj[2:-1]
            return os.environ.get(env_key, "")
        elif isinstance(obj, dict):
            return {k: GatewayConfig._replace_env_vars(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [GatewayConfig._replace_env_vars(item) for item in obj]
        return obj


class ConfigWatcher:
    """配置文件监视器"""

    def __init__(self, config_path: str, callback: Callable):
        self.config_path = Path(config_path)
        self.callback = callback
        self.observer = None
        self._debounce_task = None
        self._debounce_delay = 1.0  # 防抖延迟

    async def start(self):
        """启动监视"""
        if not self.config_path.exists():
            logger.warning(f"Config file not found: {self.config_path}")
            return

        handler = ConfigFileHandler(self._on_change)
        self.observer = Observer()
        self.observer.schedule(handler, str(self.config_path.parent), recursive=False)
        self.observer.start()
        logger.info(f"Watching config file: {self.config_path}")

    async def stop(self):
        """停止监视"""
        if self.observer:
            self.observer.stop()
            self.observer.join()

    def _on_change(self):
        """配置变更处理（带防抖）"""
        if self._debounce_task:
            self._debounce_task.cancel()

        async def debounced_callback():
            await asyncio.sleep(self._debounce_delay)
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    new_config = yaml.safe_load(f)
                await self.callback(new_config)
            except Exception as e:
                logger.error(f"Failed to reload config: {e}")

        self._debounce_task = asyncio.create_task(debounced_callback())


class ConfigFileHandler(FileSystemEventHandler):
    """文件系统事件处理器"""

    def __init__(self, callback: Callable):
        self.callback = callback

    def on_modified(self, event):
        if not event.is_directory:
            self.callback()
```

### 4.3 健康检查

**文件**: `python/gateway/health.py`

```python
"""
Gateway 健康检查

提供:
- 存活探针 (liveness)
- 就绪探针 (readiness)
- 详细状态报告
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Any, Optional
from enum import Enum

logger = logging.getLogger("gateway.health")


class HealthStatusLevel(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class HealthCheck:
    """单项健康检查结果"""
    name: str
    status: HealthStatusLevel
    message: Optional[str] = None
    latency_ms: Optional[float] = None


@dataclass
class HealthStatus:
    """整体健康状态"""
    status: str  # healthy, degraded, unhealthy
    uptime_seconds: float
    timestamp: datetime
    channels: Dict[str, Any]
    checks: List[Dict[str, Any]]


class HealthChecker:
    """健康检查器"""

    def __init__(self, gateway_state):
        self.state = gateway_state

    async def check(self) -> HealthStatus:
        """执行健康检查"""
        checks = []
        overall_status = HealthStatusLevel.HEALTHY

        # 检查 1: 网关核心
        gateway_check = await self._check_gateway()
        checks.append(gateway_check)
        if gateway_check.status != HealthStatusLevel.HEALTHY:
            overall_status = gateway_check.status

        # 检查 2: 渠道状态
        channel_checks = await self._check_channels()
        checks.extend(channel_checks)
        for check in channel_checks:
            if check.status == HealthStatusLevel.UNHEALTHY:
                overall_status = HealthStatusLevel.UNHEALTHY
            elif check.status == HealthStatusLevel.DEGRADED and overall_status == HealthStatusLevel.HEALTHY:
                overall_status = HealthStatusLevel.DEGRADED

        # 检查 3: Agent 连接
        agent_check = await self._check_agent()
        checks.append(agent_check)
        if agent_check.status == HealthStatusLevel.UNHEALTHY:
            overall_status = HealthStatusLevel.UNHEALTHY

        # 构建渠道状态摘要
        channels_summary = {}
        if self.state.channel_manager:
            for name, adapter in self.state.channel_manager.channels.items():
                channels_summary[name] = {
                    "type": adapter.__class__.__name__,
                    "running": adapter._running,
                    "capabilities": adapter.capabilities.__dict__,
                }

        return HealthStatus(
            status=overall_status.value,
            uptime_seconds=(datetime.now() - self.state.started_at).total_seconds(),
            timestamp=datetime.now(),
            channels=channels_summary,
            checks=[{
                "name": c.name,
                "status": c.status.value,
                "message": c.message,
                "latency_ms": c.latency_ms,
            } for c in checks],
        )

    async def _check_gateway(self) -> HealthCheck:
        """检查网关核心"""
        if self.state.is_shutting_down:
            return HealthCheck(
                name="gateway",
                status=HealthStatusLevel.UNHEALTHY,
                message="Gateway is shutting down"
            )

        return HealthCheck(
            name="gateway",
            status=HealthStatusLevel.HEALTHY,
            message="Gateway running"
        )

    async def _check_channels(self) -> List[HealthCheck]:
        """检查渠道状态"""
        checks = []

        if not self.state.channel_manager or not self.state.channel_manager.channels:
            return [HealthCheck(
                name="channels",
                status=HealthStatusLevel.DEGRADED,
                message="No channels registered"
            )]

        for name, adapter in self.state.channel_manager.channels.items():
            if adapter._running:
                checks.append(HealthCheck(
                    name=f"channel:{name}",
                    status=HealthStatusLevel.HEALTHY,
                    message="Connected"
                ))
            else:
                checks.append(HealthCheck(
                    name=f"channel:{name}",
                    status=HealthStatusLevel.UNHEALTHY,
                    message="Not running"
                ))

        return checks

    async def _check_agent(self) -> HealthCheck:
        """检查 Agent 连接"""
        # 这里可以添加与 Agent Zero 核心的连接检查
        return HealthCheck(
            name="agent",
            status=HealthStatusLevel.HEALTHY,
            message="Agent context available"
        )
```

### 4.4 通信协议

**文件**: `python/gateway/protocol.py`

```python
"""
Gateway 通信协议

定义网关与客户端之间的消息格式。
"""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Optional, Dict
from enum import Enum


class EventType(Enum):
    """事件类型"""
    # 连接事件
    HELLO = "hello"
    PING = "ping"
    PONG = "pong"

    # 系统事件
    SHUTDOWN = "shutdown"
    CONFIG_RELOAD = "config_reload"

    # Agent 事件
    AGENT_START = "agent_start"
    AGENT_CHUNK = "agent_chunk"
    AGENT_END = "agent_end"
    AGENT_ERROR = "agent_error"

    # 渠道事件
    CHANNEL_MESSAGE = "channel_message"
    CHANNEL_STATUS = "channel_status"

    # 状态事件
    PRESENCE = "presence"
    TICK = "tick"


@dataclass
class GatewayEvent:
    """网关事件"""
    type: EventType
    payload: Dict[str, Any] = field(default_factory=dict)
    seq: Optional[int] = None
    timestamp: datetime = field(default_factory=datetime.now)

    def to_json(self) -> str:
        return json.dumps({
            "type": self.type.value,
            "payload": self.payload,
            "seq": self.seq,
            "timestamp": self.timestamp.isoformat(),
        })

    @classmethod
    def from_json(cls, data: str) -> "GatewayEvent":
        obj = json.loads(data)
        return cls(
            type=EventType(obj["type"]),
            payload=obj.get("payload", {}),
            seq=obj.get("seq"),
            timestamp=datetime.fromisoformat(obj["timestamp"]) if "timestamp" in obj else datetime.now(),
        )


@dataclass
class GatewayRequest:
    """网关请求"""
    id: str
    method: str
    params: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps({
            "type": "req",
            "id": self.id,
            "method": self.method,
            "params": self.params,
        })


@dataclass
class GatewayResponse:
    """网关响应"""
    id: str
    ok: bool
    payload: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None

    def to_json(self) -> str:
        result = {
            "type": "res",
            "id": self.id,
            "ok": self.ok,
        }
        if self.ok:
            result["payload"] = self.payload
        else:
            result["error"] = self.error
        return json.dumps(result)
```

---

## 5. 渠道适配器

### 5.1 消息模型 + 适配器基类

**文件**: `python/channels/base.py`

（内容与之前文档中的相同，包含 `InboundMessage`、`OutboundMessage`、`ChannelCapabilities`、`ChannelAdapter` 等）

### 5.2 渠道管理器

**文件**: `python/channels/manager.py`

（内容与之前文档中的相同，包含并发启动修复、多账号支持等）

### 5.3 Telegram 适配器

**文件**: `python/channels/telegram_adapter.py`

（内容与之前文档中的相同，包含 @提及检测、话题支持等）

### 5.4 Discord 适配器

**文件**: `python/channels/discord_adapter.py`

（内容与之前文档中的相同，包含斜杠命令、并发处理等）

---

## 6. 高级功能

### 6.1 远程访问

```yaml
# conf/gateway.yaml

gateway:
  host: "0.0.0.0"  # 允许远程访问
  port: 18900

  auth:
    token: "${GATEWAY_AUTH_TOKEN}"  # 必须设置 Token
```

**安全建议**:

1. **Token 认证**: 必须设置 `auth.token`
2. **HTTPS**: 生产环境使用 Nginx 反向代理 + SSL
3. **Tailscale/VPN**: 推荐使用 Tailscale 进行安全远程访问
4. **SSH 隧道**: `ssh -N -L 18900:127.0.0.1:18900 user@host`

### 6.2 热重载

配置文件变更时自动重载，无需重启 Gateway：

```yaml
# conf/gateway.yaml

gateway:
  hot_reload: true  # 启用热重载

  # 热重载模式
  reload:
    mode: "hybrid"  # hybrid: 安全变更热应用，关键变更重启
    # mode: "off"   # 禁用热重载
```

**热重载支持的变更**:
- ✅ 渠道启用/禁用
- ✅ 白名单更新
- ✅ 日志级别
- ⚠️ Token 变更需要重启
- ⚠️ 端口变更需要重启

### 6.3 健康检查集成

```bash
# Kubernetes liveness probe
livenessProbe:
  httpGet:
    path: /api/health
    port: 18900
  initialDelaySeconds: 10
  periodSeconds: 30

# Kubernetes readiness probe
readinessProbe:
  httpGet:
    path: /api/health
    port: 18900
  initialDelaySeconds: 5
  periodSeconds: 10
```

---

## 7. 部署与运维

### 7.1 配置文件

**文件**: `conf/gateway.yaml`

```yaml
# Agent Zero Gateway 配置
# 版本: 2.0

gateway:
  # 服务配置
  host: "127.0.0.1"  # 仅本地访问，远程设为 "0.0.0.0"
  port: 18900

  # 安全配置
  auth:
    token: "${GATEWAY_AUTH_TOKEN}"  # 可选，建议设置

  # 功能开关
  hot_reload: true
  verbose: false

  # 高级配置
  max_payload_size: 10485760  # 10MB
  tick_interval_ms: 30000

# 渠道配置
channels:
  telegram:
    enabled: true
    token: "${TELEGRAM_BOT_TOKEN}"
    account_id: "main"
    require_mention_in_groups: true

  discord:
    enabled: true
    token: "${DISCORD_BOT_TOKEN}"
    account_id: "main"
    sync_commands: false
    respond_to_dms: true
```

### 7.2 启动脚本

**文件**: `run_gateway.py`

```python
#!/usr/bin/env python
"""
Agent Zero Gateway 启动入口
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def main():
    parser = argparse.ArgumentParser(description="Agent Zero Gateway")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    parser.add_argument("--port", "-p", type=int, default=18900, help="Bind port")
    parser.add_argument("--config", "-c", default="conf/gateway.yaml", help="Config file")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload (dev)")

    args = parser.parse_args()

    # 设置环境变量
    os.environ["GATEWAY_CONFIG_PATH"] = args.config
    os.environ["GATEWAY_PORT"] = str(args.port)
    os.environ["GATEWAY_HOST"] = args.host

    # 启动
    from python.gateway.server import run_gateway
    run_gateway(
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="debug" if args.verbose else "info",
    )


if __name__ == "__main__":
    main()
```

### 7.3 systemd 服务 (Linux)

**文件**: `/etc/systemd/user/agent-zero-gateway.service`

```ini
[Unit]
Description=Agent Zero Gateway
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/python /path/to/run_gateway.py --port 18900
Restart=always
RestartSec=5
Environment=TELEGRAM_BOT_TOKEN=your_token
Environment=DISCORD_BOT_TOKEN=your_token
Environment=GATEWAY_AUTH_TOKEN=your_secret
WorkingDirectory=/path/to/agent-zero

[Install]
WantedBy=default.target
```

**启用服务**:
```bash
# 用户服务
systemctl --user enable agent-zero-gateway
systemctl --user start agent-zero-gateway
systemctl --user status agent-zero-gateway

# 查看日志
journalctl --user -u agent-zero-gateway -f
```

### 7.4 launchd 服务 (macOS)

**文件**: `~/Library/LaunchAgents/com.agent-zero.gateway.plist`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.agent-zero.gateway</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>/path/to/run_gateway.py</string>
        <string>--port</string>
        <string>18900</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>TELEGRAM_BOT_TOKEN</key>
        <string>your_token</string>
        <key>DISCORD_BOT_TOKEN</key>
        <string>your_token</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>WorkingDirectory</key>
    <string>/path/to/agent-zero</string>
    <key>StandardOutPath</key>
    <string>/tmp/agent-zero-gateway.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/agent-zero-gateway.err</string>
</dict>
</plist>
```

**启用服务**:
```bash
launchctl load ~/Library/LaunchAgents/com.agent-zero.gateway.plist
launchctl start com.agent-zero.gateway
```

### 7.5 CLI 管理命令

```bash
# 启动网关
python run_gateway.py

# 查看状态
curl http://localhost:18900/api/status

# 健康检查
curl http://localhost:18900/api/health

# 列出渠道
curl http://localhost:18900/api/channels

# 发送消息
curl -X POST http://localhost:18900/api/send \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your_token" \
  -d '{"channel": "telegram:main", "chat_id": "123456", "message": "Hello!"}'

# 重载配置
curl -X POST http://localhost:18900/api/reload \
  -H "Authorization: Bearer your_token"
```

---

## 8. 测试与验收

### 8.1 测试矩阵

| 测试类型 | 测试点 | 方法 |
|----------|--------|------|
| 单元测试 | 配置加载 | pytest |
| 单元测试 | 消息模型 | pytest |
| 单元测试 | 健康检查 | pytest |
| 集成测试 | Gateway 启动 | 手动 + 脚本 |
| 集成测试 | Telegram 收发 | 手动 |
| 集成测试 | Discord 收发 | 手动 |
| 集成测试 | HTTP API | curl + pytest |
| 集成测试 | WebSocket | wscat + pytest |
| 压力测试 | 并发消息 | locust |
| 稳定性测试 | 长时间运行 | 24小时监控 |

### 8.2 验收标准

| 功能 | 标准 | 测试方法 |
|------|------|----------|
| Gateway 启动 | 10秒内就绪 | 脚本 |
| 健康检查 | 返回正确状态 | curl |
| Telegram 消息 | 延迟 <2s | 手动 |
| Discord 消息 | 延迟 <2s | 手动 |
| 配置热重载 | 5秒内生效 | 修改配置 |
| 远程访问 | Token 认证正常 | curl |
| 服务托管 | 崩溃自动重启 | kill -9 |
| 长时间运行 | 24小时稳定 | 监控 |

---

## 附录

### A. 依赖清单

```
# requirements-gateway.txt

# 核心框架
fastapi>=0.100.0
uvicorn>=0.23.0
websockets>=11.0

# 配置
pyyaml>=6.0
python-dotenv>=1.0
watchdog>=3.0

# 渠道
python-telegram-bot>=20.0
discord.py>=2.0

# 工具
httpx>=0.24.0
```

### B. 环境变量

```bash
# .env

# Gateway
GATEWAY_PORT=18900
GATEWAY_AUTH_TOKEN=your_secret_token

# Telegram
TELEGRAM_BOT_TOKEN=your_telegram_token

# Discord
DISCORD_BOT_TOKEN=your_discord_token
```

### C. 更新日志

| 版本 | 日期 | 更新内容 |
|------|------|----------|
| 1.0 | 2026-01-30 | 初始版本 |
| 2.0 | 2026-02-01 | 重构：网关优先架构、远程访问、健康检查、热重载、服务化部署 |

---

> **文档维护者**: AI Assistant
> **最后更新**: 2026-02-01
