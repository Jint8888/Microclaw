# Agent Zero 多渠道网关开发计划

> **版本**: 3.0
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
- [7. 后续渠道参考](#7-后续渠道参考)
- [8. 部署与运维](#8-部署与运维)
- [9. 测试与验收](#9-测试与验收)

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

### 1.3 Phase 1 目标渠道

| 渠道 | Python 库 | 优先级 | 状态 |
|------|-----------|--------|------|
| **Discord** | discord.py | ⭐⭐⭐⭐⭐ | 🔵 Phase 1 |
| **Telegram** | python-telegram-bot | ⭐⭐⭐⭐⭐ | 🔵 Phase 1 |
| Email | smtplib/imaplib | ⭐⭐⭐ | 🟡 后续 |
| Slack | slack-sdk | ⭐⭐⭐ | 🟡 后续 |
| WeChat | wechatpy | ⭐⭐ | 🟡 后续 |
| WhatsApp | Twilio | ⭐⭐ | 🟡 后续 |
| Matrix | matrix-nio | ⭐⭐ | 🟡 后续 |

### 1.4 设计原则

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
│  ├─ 富媒体支持 (图片/文件)                                          │
│  └─ 与 Gateway 集成测试                                              │
├──────────────────────────────────────────────────────────────────────┤
│  Phase 3: Discord 适配器 (Day 7-9)                                  │
│  ├─ Bot 连接 + 消息监听                                             │
│  ├─ 并发启动处理                                                     │
│  ├─ 斜杠命令支持                                                     │
│  ├─ 频道/私信支持                                                    │
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
    version="3.0.0",
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
                "version": "3.0.0",
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

### 5.1 消息模型

**文件**: `python/channels/base.py`

```python
"""
渠道适配器基类和消息模型

定义:
- 统一的消息格式
- 适配器抽象基类
- 渠道能力声明
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Callable, Awaitable
from enum import Enum
from datetime import datetime
from abc import ABC, abstractmethod


class MessageType(Enum):
    """消息类型"""
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    FILE = "file"


@dataclass
class Attachment:
    """附件模型"""
    type: MessageType
    url: Optional[str] = None
    data: Optional[bytes] = None
    filename: Optional[str] = None
    mime_type: Optional[str] = None


@dataclass
class InboundMessage:
    """入站消息 (用户 → Agent)"""
    channel: str                          # telegram, discord
    channel_user_id: str                  # 渠道用户 ID
    channel_chat_id: str                  # 渠道会话 ID
    content: str                          # 文本内容
    message_id: str                       # 消息 ID
    timestamp: datetime = field(default_factory=datetime.now)
    attachments: List[Attachment] = field(default_factory=list)
    is_group: bool = False                # 是否群聊
    reply_to_id: Optional[str] = None     # 回复的消息 ID
    user_name: Optional[str] = None       # 用户名
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OutboundMessage:
    """出站消息 (Agent → 用户)"""
    content: str
    attachments: List[Attachment] = field(default_factory=list)
    parse_mode: str = "markdown"          # markdown, html, plain
    reply_to_id: Optional[str] = None     # 回复的消息 ID


@dataclass
class ChannelCapabilities:
    """渠道能力声明"""
    supports_markdown: bool = True
    supports_html: bool = False
    supports_reactions: bool = False
    supports_threads: bool = False
    supports_edit: bool = True
    supports_delete: bool = True
    max_message_length: int = 4096
    supports_attachments: bool = True
    supports_voice: bool = False


# 消息处理器类型
MessageHandler = Callable[[InboundMessage], Awaitable[OutboundMessage]]


class ChannelAdapter(ABC):
    """渠道适配器抽象基类"""

    def __init__(self, config: dict, account_id: str = "default"):
        self.config = config
        self.account_id = account_id
        self.name = self.__class__.__name__
        self._handler: Optional[MessageHandler] = None
        self._running = False

    @property
    @abstractmethod
    def capabilities(self) -> ChannelCapabilities:
        """返回渠道能力"""
        pass

    def on_message(self, handler: MessageHandler):
        """注册消息处理器"""
        self._handler = handler

    @abstractmethod
    async def start(self):
        """启动渠道"""
        pass

    @abstractmethod
    async def stop(self):
        """停止渠道"""
        pass

    @abstractmethod
    async def send(self, chat_id: str, message: OutboundMessage):
        """发送消息"""
        pass

    async def handle(self, message: InboundMessage) -> OutboundMessage:
        """处理消息 (调用注册的处理器)"""
        if self._handler:
            return await self._handler(message)
        return OutboundMessage(content="Handler not configured")
```

### 5.2 渠道管理器

**文件**: `python/channels/manager.py`

```python
"""
渠道管理器

负责:
- 渠道注册和生命周期管理
- 消息路由
- 多账号支持
"""

import asyncio
import logging
from typing import Dict, Optional, List
from .base import ChannelAdapter, InboundMessage, OutboundMessage

logger = logging.getLogger("channels.manager")


class ChannelManager:
    """渠道管理器"""

    def __init__(self, agent_context):
        """
        初始化渠道管理器

        Args:
            agent_context: Agent Zero 上下文，需要实现 process() 方法
        """
        self.agent_context = agent_context
        self.channels: Dict[str, ChannelAdapter] = {}

    def register(self, name: str, adapter: ChannelAdapter):
        """注册渠道"""
        adapter.on_message(self._process_message)
        self.channels[name] = adapter
        logger.info(f"Registered channel: {name}")

    def unregister(self, name: str):
        """注销渠道"""
        if name in self.channels:
            del self.channels[name]
            logger.info(f"Unregistered channel: {name}")

    def get_channel(self, name: str) -> Optional[ChannelAdapter]:
        """获取渠道"""
        return self.channels.get(name)

    def list_channels(self) -> Dict[str, dict]:
        """列出所有渠道"""
        return {
            name: {
                "type": adapter.__class__.__name__,
                "account_id": adapter.account_id,
                "running": adapter._running,
                "capabilities": adapter.capabilities.__dict__,
            }
            for name, adapter in self.channels.items()
        }

    async def start_all(self):
        """启动所有渠道 (并发)"""
        if not self.channels:
            logger.warning("No channels to start")
            return

        # 使用 gather 并发启动，但捕获单个失败
        results = await asyncio.gather(
            *[self._start_channel(name, ch) for name, ch in self.channels.items()],
            return_exceptions=True
        )

        # 记录启动结果
        for (name, _), result in zip(self.channels.items(), results):
            if isinstance(result, Exception):
                logger.error(f"Failed to start channel {name}: {result}")

    async def _start_channel(self, name: str, adapter: ChannelAdapter):
        """启动单个渠道"""
        try:
            await adapter.start()
            adapter._running = True
            logger.info(f"Started channel: {name}")
        except Exception as e:
            adapter._running = False
            raise e

    async def stop_all(self):
        """停止所有渠道"""
        await asyncio.gather(
            *[self._stop_channel(name, ch) for name, ch in self.channels.items()],
            return_exceptions=True
        )

    async def _stop_channel(self, name: str, adapter: ChannelAdapter):
        """停止单个渠道"""
        try:
            await adapter.stop()
            adapter._running = False
            logger.info(f"Stopped channel: {name}")
        except Exception as e:
            logger.error(f"Error stopping channel {name}: {e}")

    async def _process_message(self, msg: InboundMessage) -> OutboundMessage:
        """路由消息到 Agent"""
        # 构建统一的会话键
        session_key = f"{msg.channel}:{msg.channel_user_id}"

        try:
            # 调用 Agent 处理消息
            response = await self.agent_context.process(
                message=msg.content,
                session_key=session_key,
                metadata={
                    "channel": msg.channel,
                    "user_id": msg.channel_user_id,
                    "chat_id": msg.channel_chat_id,
                    "user_name": msg.user_name,
                    "is_group": msg.is_group,
                    "attachments": [a.__dict__ for a in msg.attachments],
                }
            )
            return OutboundMessage(content=response)
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            return OutboundMessage(content=f"Error: {str(e)}")
```

### 5.3 Telegram 适配器

**文件**: `python/channels/telegram_adapter.py`

**依赖**: `pip install python-telegram-bot>=20.0`

```python
"""
Telegram Bot 适配器

功能:
- 文本消息收发
- 图片/文件支持
- 群聊 @提及检测
- 长消息自动分块
"""

import logging
from typing import Optional
from telegram import Update, Bot
from telegram.ext import Application, MessageHandler, filters, ContextTypes

from .base import (
    ChannelAdapter, ChannelCapabilities,
    InboundMessage, OutboundMessage, Attachment, MessageType
)

logger = logging.getLogger("channels.telegram")


class TelegramAdapter(ChannelAdapter):
    """Telegram Bot 适配器"""

    def __init__(self, config: dict, account_id: str = "default"):
        super().__init__(config, account_id)
        self.token = config["token"]
        self.app: Optional[Application] = None

        # 配置选项
        self.require_mention_in_groups = config.get("require_mention_in_groups", True)
        self.allowed_users = config.get("whitelist", [])  # 用户白名单

    @property
    def capabilities(self) -> ChannelCapabilities:
        return ChannelCapabilities(
            supports_markdown=True,
            supports_html=True,
            supports_reactions=False,
            supports_threads=False,
            supports_edit=True,
            supports_delete=True,
            max_message_length=4096,
            supports_attachments=True,
            supports_voice=True,
        )

    async def start(self):
        """启动 Telegram Bot"""
        self.app = Application.builder().token(self.token).build()

        # 注册消息处理器
        self.app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            self._on_message
        ))
        self.app.add_handler(MessageHandler(filters.PHOTO, self._on_photo))
        self.app.add_handler(MessageHandler(filters.Document.ALL, self._on_document))

        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()

        self._running = True
        logger.info(f"Telegram adapter started: {self.account_id}")

    async def stop(self):
        """停止 Telegram Bot"""
        if self.app:
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()
        self._running = False
        logger.info(f"Telegram adapter stopped: {self.account_id}")

    async def send(self, chat_id: str, message: OutboundMessage):
        """发送消息"""
        if not self.app:
            raise RuntimeError("Telegram adapter not started")

        # 分块发送长消息 (Telegram 限制 4096 字符)
        content = message.content
        max_len = 4000  # 留一些余量

        for i in range(0, len(content), max_len):
            chunk = content[i:i + max_len]
            await self.app.bot.send_message(
                chat_id=int(chat_id),
                text=chunk,
                parse_mode="Markdown" if message.parse_mode == "markdown" else None
            )

        # 发送附件
        for att in message.attachments:
            if att.type == MessageType.IMAGE:
                await self.app.bot.send_photo(
                    chat_id=int(chat_id),
                    photo=att.url or att.data
                )
            elif att.type == MessageType.FILE:
                await self.app.bot.send_document(
                    chat_id=int(chat_id),
                    document=att.url or att.data,
                    filename=att.filename
                )

    async def _on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理文本消息"""
        if not self._should_respond(update):
            return

        msg = self._convert(update)
        response = await self.handle(msg)
        await self.send(msg.channel_chat_id, response)

    async def _on_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理图片消息"""
        if not self._should_respond(update):
            return

        msg = self._convert(update)

        # 获取最大尺寸的图片
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        msg.attachments.append(Attachment(
            type=MessageType.IMAGE,
            url=file.file_path
        ))

        response = await self.handle(msg)
        await self.send(msg.channel_chat_id, response)

    async def _on_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理文件消息"""
        if not self._should_respond(update):
            return

        msg = self._convert(update)

        doc = update.message.document
        file = await context.bot.get_file(doc.file_id)
        msg.attachments.append(Attachment(
            type=MessageType.FILE,
            url=file.file_path,
            filename=doc.file_name,
            mime_type=doc.mime_type
        ))

        response = await self.handle(msg)
        await self.send(msg.channel_chat_id, response)

    def _should_respond(self, update: Update) -> bool:
        """判断是否应该响应此消息"""
        message = update.message
        if not message:
            return False

        # 白名单检查
        if self.allowed_users:
            if message.from_user.id not in self.allowed_users:
                return False

        # 群聊中需要 @提及
        if message.chat.type in ["group", "supergroup"]:
            if self.require_mention_in_groups:
                bot_username = self.app.bot.username
                text = message.text or message.caption or ""
                if f"@{bot_username}" not in text:
                    return False

        return True

    def _convert(self, update: Update) -> InboundMessage:
        """转换 Telegram 消息为统一格式"""
        m = update.message

        # 移除 @mention
        text = m.text or m.caption or ""
        if self.app and self.app.bot.username:
            text = text.replace(f"@{self.app.bot.username}", "").strip()

        return InboundMessage(
            channel="telegram",
            channel_user_id=str(m.from_user.id),
            channel_chat_id=str(m.chat_id),
            content=text,
            message_id=str(m.message_id),
            is_group=m.chat.type in ["group", "supergroup"],
            user_name=m.from_user.username or m.from_user.first_name,
            metadata={
                "chat_type": m.chat.type,
                "chat_title": m.chat.title if m.chat.type != "private" else None,
            }
        )
```

**创建 Telegram Bot 步骤**:

1. 在 Telegram 搜索 `@BotFather`
2. 发送 `/newbot` 并按提示操作
3. 获取 Bot Token（格式如 `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`）
4. 可选：使用 `/setprivacy` 设置隐私模式

---

### 5.4 Discord 适配器

**文件**: `python/channels/discord_adapter.py`

**依赖**: `pip install discord.py>=2.0`

```python
"""
Discord Bot 适配器

功能:
- 文本消息收发
- 频道/私信支持
- 附件处理
- 长消息自动分块
- 独立事件循环处理
"""

import asyncio
import logging
import threading
from typing import Optional

import discord
from discord.ext import commands

from .base import (
    ChannelAdapter, ChannelCapabilities,
    InboundMessage, OutboundMessage, Attachment, MessageType
)

logger = logging.getLogger("channels.discord")


class DiscordAdapter(ChannelAdapter):
    """Discord Bot 适配器"""

    def __init__(self, config: dict, account_id: str = "default"):
        super().__init__(config, account_id)
        self.token = config["token"]

        # 配置选项
        self.respond_to_dms = config.get("respond_to_dms", True)
        self.require_mention = config.get("require_mention", True)
        self.allowed_guilds = config.get("allowed_guilds", [])  # 服务器白名单

        # Discord 客户端
        intents = discord.Intents.default()
        intents.message_content = True
        self.bot = commands.Bot(command_prefix="!", intents=intents)

        # 独立事件循环（解决与 FastAPI 的冲突）
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        self._setup()

    @property
    def capabilities(self) -> ChannelCapabilities:
        return ChannelCapabilities(
            supports_markdown=True,
            supports_html=False,
            supports_reactions=True,
            supports_threads=True,
            supports_edit=True,
            supports_delete=True,
            max_message_length=2000,
            supports_attachments=True,
            supports_voice=False,
        )

    def _setup(self):
        """设置 Discord 事件处理"""

        @self.bot.event
        async def on_ready():
            logger.info(f"Discord: Logged in as {self.bot.user}")

        @self.bot.event
        async def on_message(message: discord.Message):
            # 忽略自己的消息
            if message.author == self.bot.user:
                return

            # 检查是否应该响应
            if not self._should_respond(message):
                return

            # 转换并处理消息
            msg = self._convert(message)
            response = await self.handle(msg)
            await self.send(msg.channel_chat_id, response)

    async def start(self):
        """在独立线程中启动 Discord Bot"""
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_in_thread,
            daemon=True
        )
        self._thread.start()
        self._running = True
        logger.info(f"Discord adapter started: {self.account_id}")

    def _run_in_thread(self):
        """独立线程运行事件循环"""
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self.bot.start(self.token))

    async def stop(self):
        """停止 Discord Bot"""
        if self.bot:
            await self.bot.close()
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._running = False
        logger.info(f"Discord adapter stopped: {self.account_id}")

    async def send(self, chat_id: str, message: OutboundMessage):
        """发送消息"""
        channel = self.bot.get_channel(int(chat_id))
        if not channel:
            # 尝试作为用户 DM
            try:
                user = await self.bot.fetch_user(int(chat_id))
                channel = await user.create_dm()
            except:
                logger.error(f"Cannot find channel or user: {chat_id}")
                return

        # 分块发送长消息 (Discord 限制 2000 字符)
        content = message.content
        max_len = 1900  # 留一些余量

        for i in range(0, len(content), max_len):
            chunk = content[i:i + max_len]
            await channel.send(chunk)

        # 发送附件
        for att in message.attachments:
            if att.url:
                await channel.send(att.url)
            elif att.data:
                file = discord.File(att.data, filename=att.filename or "file")
                await channel.send(file=file)

    def _should_respond(self, message: discord.Message) -> bool:
        """判断是否应该响应此消息"""
        # 私信处理
        if isinstance(message.channel, discord.DMChannel):
            return self.respond_to_dms

        # 服务器白名单检查
        if self.allowed_guilds:
            if message.guild and message.guild.id not in self.allowed_guilds:
                return False

        # 频道中需要 @提及
        if self.require_mention:
            if self.bot.user not in message.mentions:
                return False

        return True

    def _convert(self, message: discord.Message) -> InboundMessage:
        """转换 Discord 消息为统一格式"""
        # 移除 @mention
        content = message.content
        if self.bot.user:
            content = content.replace(f"<@{self.bot.user.id}>", "").strip()
            content = content.replace(f"<@!{self.bot.user.id}>", "").strip()

        # 处理附件
        attachments = []
        for a in message.attachments:
            att_type = MessageType.IMAGE if a.content_type and a.content_type.startswith("image") else MessageType.FILE
            attachments.append(Attachment(
                type=att_type,
                url=a.url,
                filename=a.filename,
                mime_type=a.content_type
            ))

        return InboundMessage(
            channel="discord",
            channel_user_id=str(message.author.id),
            channel_chat_id=str(message.channel.id),
            content=content,
            message_id=str(message.id),
            attachments=attachments,
            is_group=isinstance(message.channel, discord.TextChannel),
            user_name=message.author.name,
            metadata={
                "guild_id": str(message.guild.id) if message.guild else None,
                "guild_name": message.guild.name if message.guild else None,
                "channel_name": message.channel.name if hasattr(message.channel, 'name') else None,
            }
        )
```

**创建 Discord Bot 步骤**:

1. 访问 [Discord Developer Portal](https://discord.com/developers/applications)
2. 点击 "New Application"，输入名称
3. 进入 "Bot" 页面，点击 "Add Bot"
4. **重要**: 开启 `MESSAGE CONTENT INTENT`（Privileged Gateway Intents 下）
5. 复制 Bot Token
6. 进入 "OAuth2" → "URL Generator"：
   - Scopes: 选择 `bot`
   - Bot Permissions: 选择 `Send Messages`, `Read Message History`
7. 使用生成的 URL 邀请 Bot 到服务器

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
```

**热重载支持的变更**:
- ✅ 渠道启用/禁用
- ✅ 白名单更新
- ✅ 日志级别
- ⚠️ Token 变更需要重启
- ⚠️ 端口变更需要重启

### 6.3 健康检查集成

```yaml
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

## 7. 后续渠道参考

### 7.1 Email (IMAP/SMTP)

**Python 库**: 标准库 `imaplib`, `smtplib`, `email`

```python
"""Email 适配器参考实现"""
import imaplib
import smtplib
from email.mime.text import MIMEText
from .base import ChannelAdapter, OutboundMessage

class EmailAdapter(ChannelAdapter):
    def __init__(self, config: dict, account_id: str = "default"):
        super().__init__(config, account_id)
        self.imap_host = config["imap_host"]
        self.smtp_host = config["smtp_host"]
        self.username = config["username"]
        self.password = config["password"]
        self.poll_interval = config.get("poll_interval", 30)

    async def start(self):
        # 定期轮询 IMAP 收件箱
        self.imap = imaplib.IMAP4_SSL(self.imap_host)
        self.imap.login(self.username, self.password)
        self._running = True

    async def stop(self):
        if hasattr(self, 'imap'):
            self.imap.logout()
        self._running = False

    async def send(self, to_addr: str, message: OutboundMessage):
        msg = MIMEText(message.content)
        msg["Subject"] = "Agent Zero Response"
        msg["From"] = self.username
        msg["To"] = to_addr

        with smtplib.SMTP_SSL(self.smtp_host) as server:
            server.login(self.username, self.password)
            server.send_message(msg)
```

**配置参考**:
```yaml
email:
  enabled: false
  imap_host: "imap.gmail.com"
  smtp_host: "smtp.gmail.com"
  username: "${EMAIL_USERNAME}"
  password: "${EMAIL_PASSWORD}"
  poll_interval: 30  # 秒
```

---

### 7.2 Slack

**Python 库**: `pip install slack-sdk`

```python
"""Slack 适配器参考实现"""
from slack_sdk import WebClient
from slack_sdk.socket_mode import SocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from .base import ChannelAdapter, OutboundMessage

class SlackAdapter(ChannelAdapter):
    def __init__(self, config: dict, account_id: str = "default"):
        super().__init__(config, account_id)
        self.bot_token = config["bot_token"]
        self.app_token = config["app_token"]
        self.client = WebClient(token=self.bot_token)

    async def start(self):
        self.socket = SocketModeClient(
            app_token=self.app_token,
            web_client=self.client
        )
        self.socket.socket_mode_request_listeners.append(self._on_event)
        self.socket.connect()
        self._running = True

    async def stop(self):
        if hasattr(self, 'socket'):
            self.socket.close()
        self._running = False

    async def send(self, channel_id: str, message: OutboundMessage):
        self.client.chat_postMessage(
            channel=channel_id,
            text=message.content
        )
```

**创建 Slack App 步骤**:
1. 访问 [Slack API](https://api.slack.com/apps)
2. 创建 App → From scratch
3. 添加 Bot Token Scopes: `chat:write`, `app_mentions:read`
4. 启用 Socket Mode
5. 安装到 Workspace

---

### 7.3 WeChat (企业微信)

**Python 库**: `pip install wechatpy`

```python
"""企业微信适配器参考实现"""
from wechatpy.enterprise import WeChatClient
from .base import ChannelAdapter, OutboundMessage

class WeChatAdapter(ChannelAdapter):
    def __init__(self, config: dict, account_id: str = "default"):
        super().__init__(config, account_id)
        self.corp_id = config["corp_id"]
        self.secret = config["secret"]
        self.agent_id = config["agent_id"]
        self.client = WeChatClient(self.corp_id, self.secret)

    async def send(self, user_id: str, message: OutboundMessage):
        self.client.message.send_text(
            agent_id=self.agent_id,
            user_ids=[user_id],
            content=message.content
        )
```

> ⚠️ **注意**: 个人微信接入存在合规风险，建议使用企业微信。

---

### 7.4 WhatsApp

**Python 库**: Twilio API 或 WhatsApp Business API

```python
"""WhatsApp (Twilio) 适配器参考实现"""
from twilio.rest import Client
from .base import ChannelAdapter, OutboundMessage

class WhatsAppAdapter(ChannelAdapter):
    def __init__(self, config: dict, account_id: str = "default"):
        super().__init__(config, account_id)
        self.account_sid = config["account_sid"]
        self.auth_token = config["auth_token"]
        self.from_number = config["from_number"]
        self.client = Client(self.account_sid, self.auth_token)

    async def send(self, to_number: str, message: OutboundMessage):
        self.client.messages.create(
            body=message.content,
            from_=f"whatsapp:{self.from_number}",
            to=f"whatsapp:{to_number}"
        )
```

---

### 7.5 Matrix (开源 IM)

**Python 库**: `pip install matrix-nio`

```python
"""Matrix 适配器参考实现"""
from nio import AsyncClient, MatrixRoom, RoomMessageText
from .base import ChannelAdapter, OutboundMessage

class MatrixAdapter(ChannelAdapter):
    def __init__(self, config: dict, account_id: str = "default"):
        super().__init__(config, account_id)
        self.homeserver = config["homeserver"]
        self.user_id = config["user_id"]
        self.password = config["password"]
        self.client = AsyncClient(self.homeserver, self.user_id)

    async def start(self):
        await self.client.login(self.password)
        self.client.add_event_callback(self._on_message, RoomMessageText)
        # 注意：sync_forever 会阻塞，需要在独立任务中运行
        self._running = True

    async def stop(self):
        await self.client.close()
        self._running = False

    async def send(self, room_id: str, message: OutboundMessage):
        await self.client.room_send(
            room_id=room_id,
            message_type="m.room.message",
            content={"msgtype": "m.text", "body": message.content}
        )
```

---

## 8. 部署与运维

### 8.1 配置文件

**文件**: `conf/gateway.yaml`

```yaml
# Agent Zero Gateway 配置
# 版本: 3.0

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
    whitelist: []  # 用户 ID 白名单，空为允许所有

  discord:
    enabled: true
    token: "${DISCORD_BOT_TOKEN}"
    account_id: "main"
    respond_to_dms: true
    require_mention: true
    allowed_guilds: []  # 服务器 ID 白名单，空为允许所有
```

### 8.2 启动脚本

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

### 8.3 systemd 服务 (Linux)

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

### 8.4 launchd 服务 (macOS)

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

### 8.5 CLI 管理命令

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

## 9. 测试与验收

### 9.1 单元测试

| 测试文件 | 覆盖模块 | 测试点 |
|----------|----------|--------|
| test_message.py | base.py | 消息序列化/反序列化 |
| test_telegram.py | telegram_adapter.py | 消息转换、发送、分块 |
| test_discord.py | discord_adapter.py | 消息转换、分块发送 |
| test_manager.py | manager.py | 多渠道注册、路由 |
| test_config.py | config.py | 配置加载、环境变量替换 |
| test_health.py | health.py | 健康检查逻辑 |

### 9.2 集成测试

```python
# tests/integration/test_channels_e2e.py

import pytest
import asyncio
from python.channels.manager import ChannelManager
from python.channels.telegram_adapter import TelegramAdapter
from python.channels.discord_adapter import DiscordAdapter

class MockAgentContext:
    """模拟 Agent 上下文"""
    async def process(self, message: str, session_key: str, **kwargs) -> str:
        return f"Echo: {message}"


@pytest.mark.asyncio
async def test_telegram_roundtrip():
    """Telegram 端到端测试"""
    # 需要设置 TEST_TELEGRAM_TOKEN 环境变量
    adapter = TelegramAdapter({"token": "TEST_TOKEN"})
    # 模拟收到消息并验证响应


@pytest.mark.asyncio
async def test_discord_roundtrip():
    """Discord 端到端测试"""
    adapter = DiscordAdapter({"token": "TEST_TOKEN"})
    # 模拟收到消息并验证响应


@pytest.mark.asyncio
async def test_multi_channel():
    """多渠道同时运行"""
    context = MockAgentContext()
    manager = ChannelManager(context)

    # 注册多个渠道
    manager.register("telegram:test", TelegramAdapter({"token": "TOKEN1"}))
    manager.register("discord:test", DiscordAdapter({"token": "TOKEN2"}))

    # 验证渠道列表
    channels = manager.list_channels()
    assert "telegram:test" in channels
    assert "discord:test" in channels


@pytest.mark.asyncio
async def test_message_routing():
    """消息路由测试"""
    context = MockAgentContext()
    manager = ChannelManager(context)

    from python.channels.base import InboundMessage

    msg = InboundMessage(
        channel="test",
        channel_user_id="user123",
        channel_chat_id="chat456",
        content="Hello",
        message_id="msg789"
    )

    response = await manager._process_message(msg)
    assert response.content == "Echo: Hello"
```

### 9.3 测试矩阵

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

### 9.4 验收标准

| 功能 | 标准 | 测试方法 |
|------|------|----------|
| Gateway 启动 | 10秒内就绪 | 脚本 |
| 健康检查 | 返回正确状态 | curl |
| Telegram 文本消息 | 收发正常，延迟 <2s | 手动 |
| Telegram 图片消息 | 能接收图片 | 手动 |
| Discord 文本消息 | 收发正常，延迟 <2s | 手动 |
| Discord 频道/私信 | 都能响应 | 手动 |
| 长消息分块 | 不报错 | 发送 5000 字 |
| 配置热重载 | 5秒内生效 | 修改配置 |
| 远程访问 | Token 认证正常 | curl |
| 服务托管 | 崩溃自动重启 | kill -9 |
| 多渠道同时运行 | 稳定运行 1 小时 | 监控 |
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

### C. 参考资料

- [python-telegram-bot Docs](https://docs.python-telegram-bot.org/)
- [discord.py Docs](https://discordpy.readthedocs.io/)
- [FastAPI Docs](https://fastapi.tiangolo.com/)
- [OpenClaw Architecture](https://github.com/user/openclaw)

### D. 更新日志

| 版本 | 日期 | 更新内容 |
|------|------|----------|
| 1.0 | 2026-01-30 | 初始版本：核心框架 + Discord + Telegram |
| 2.0 | 2026-02-01 | 重构：网关优先架构、远程访问、健康检查、热重载、服务化部署 |
| 3.0 | 2026-02-01 | 合并版：完整代码实现 + 后续渠道参考 + Bot 创建指南 + 集成测试 |

---

> **文档维护者**: AI Assistant
> **最后更新**: 2026-02-01
