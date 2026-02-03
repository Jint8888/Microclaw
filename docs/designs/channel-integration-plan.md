# Agent Zero 多渠道接入开发计划

> **版本**: 1.0  
> **创建日期**: 2026-01-30  
> **目标**: 为 Agent Zero 添加多渠道消息接入能力，参考 OpenClaw 的渠道架构设计

---

## 📋 目录

- [1. 项目概述](#1-项目概述)
- [2. 整体架构设计](#2-整体架构设计)
- [3. 分阶段实施计划](#3-分阶段实施计划)
- [4. 模块详细设计](#4-模块详细设计)
- [5. Phase 1: Discord + Telegram](#5-phase-1-discord--telegram)
- [6. 后续渠道参考](#6-后续渠道参考)
- [7. 测试与验收](#7-测试与验收)

---

## 1. 项目概述

### 1.1 背景

OpenClaw 支持 15+ 种通讯渠道（Telegram、WhatsApp、Discord、Slack 等），使用户可以在任意平台与 AI 助手交互。本项目旨在为 Agent Zero 添加类似的多渠道接入能力。

### 1.2 Phase 1 目标

| 渠道 | Python 库 | 优先级 | 状态 |
|------|-----------|--------|------|
| **Discord** | discord.py | ⭐⭐⭐⭐⭐ | 🔵 Phase 1 |
| **Telegram** | python-telegram-bot | ⭐⭐⭐⭐⭐ | 🔵 Phase 1 |
| Email | smtplib/imaplib | ⭐⭐⭐ | 🟡 后续 |
| Slack | slack-sdk | ⭐⭐⭐ | 🟡 后续 |
| WeChat | wechaty/itchat | ⭐⭐ | 🟡 后续 |
| WhatsApp | yowsup | ⭐⭐ | 🟡 后续 |

### 1.3 预期效果

```
用户 (Telegram/Discord)
        │
        ▼
┌───────────────┐      ┌───────────────┐
│ Telegram Bot  │      │ Discord Bot   │
└───────┬───────┘      └───────┬───────┘
        │                      │
        └──────────┬───────────┘
                   ▼
          ┌───────────────┐
          │ChannelManager │
          └───────┬───────┘
                  ▼
          ┌───────────────┐
          │ Agent Zero    │
          └───────────────┘
                  │
                  ▼
            响应返回用户
```

---

## 2. 整体架构设计

### 2.1 架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                         渠道接入层                                   │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   ┌─────────────┐    ┌─────────────┐    ┌─────────────┐            │
│   │  Telegram   │    │   Discord   │    │   Web UI    │            │
│   │   Adapter   │    │   Adapter   │    │   (现有)    │            │
│   └──────┬──────┘    └──────┬──────┘    └──────┬──────┘            │
│          │                  │                  │                    │
│          └──────────────────┴──────────────────┘                    │
│                             │                                       │
│                             ▼                                       │
│                    ┌─────────────────┐                             │
│                    │ ChannelAdapter  │  统一消息接口                │
│                    │ (Abstract Base) │                             │
│                    └────────┬────────┘                             │
│                             │                                       │
│                             ▼                                       │
│                    ┌─────────────────┐                             │
│                    │ ChannelManager  │  渠道管理 + 路由             │
│                    └────────┬────────┘                             │
│                             │                                       │
└─────────────────────────────┼───────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      AgentContext (现有)                            │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 文件结构

```
python/
├── channels/                       # 🆕 渠道模块
│   ├── __init__.py
│   ├── base.py                     # 适配器基类 + 消息模型
│   ├── manager.py                  # 渠道管理器
│   ├── telegram_adapter.py         # Telegram 适配器
│   └── discord_adapter.py          # Discord 适配器
│
├── helpers/
│   └── ...
└── tools/
    └── ...

conf/
└── channels.yaml                   # 🆕 渠道配置

run_channels.py                     # 🆕 渠道启动入口
```

---

## 3. 分阶段实施计划

### 3.1 Phase 1: 核心框架 + Discord + Telegram (7 天)

```
┌──────────────────────────────────────────────────────────────────────┐
│  Day 1-2: 核心框架                                                   │
│  ├─ 消息模型 (InboundMessage, OutboundMessage)                      │
│  ├─ 适配器基类 (ChannelAdapter)                                      │
│  └─ 渠道管理器 (ChannelManager)                                      │
├──────────────────────────────────────────────────────────────────────┤
│  Day 3-4: Telegram 适配器                                            │
│  ├─ Bot 连接和消息监听                                               │
│  ├─ 消息格式转换                                                     │
│  ├─ 富媒体支持 (图片/文件)                                            │
│  └─ 与 Agent 集成测试                                                │
├──────────────────────────────────────────────────────────────────────┤
│  Day 5-6: Discord 适配器                                             │
│  ├─ Bot 连接和消息监听                                               │
│  ├─ 消息格式转换                                                     │
│  ├─ 频道/私信支持                                                    │
│  └─ 与 Agent 集成测试                                                │
├──────────────────────────────────────────────────────────────────────┤
│  Day 7: 整合测试 + 文档                                              │
│  ├─ 多渠道同时运行测试                                               │
│  ├─ 配置文档                                                         │
│  └─ 使用说明                                                         │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 4. 模块详细设计

### 4.1 消息模型

**文件**: `python/channels/base.py`

```python
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum
from datetime import datetime
from abc import ABC, abstractmethod

class MessageType(Enum):
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
    message_id: str
    timestamp: datetime = field(default_factory=datetime.now)
    attachments: List[Attachment] = field(default_factory=list)
    is_group: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class OutboundMessage:
    """出站消息 (Agent → 用户)"""
    content: str
    attachments: List[Attachment] = field(default_factory=list)
    parse_mode: str = "markdown"
```

### 4.2 适配器基类

```python
class ChannelAdapter(ABC):
    """渠道适配器抽象基类"""
    
    def __init__(self, config: dict):
        self.config = config
        self.name = self.__class__.__name__
        self._handler = None
    
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
    
    def on_message(self, handler):
        """注册消息处理器"""
        self._handler = handler
    
    async def handle(self, message: InboundMessage) -> OutboundMessage:
        """处理消息"""
        if self._handler:
            return await self._handler(message)
        return OutboundMessage(content="Handler not configured")
```

### 4.3 渠道管理器

**文件**: `python/channels/manager.py`

```python
class ChannelManager:
    """渠道管理器"""
    
    def __init__(self, agent_context):
        self.agent_context = agent_context
        self.channels: Dict[str, ChannelAdapter] = {}
    
    def register(self, name: str, adapter: ChannelAdapter):
        """注册渠道"""
        adapter.on_message(self._process_message)
        self.channels[name] = adapter
    
    async def start_all(self):
        """启动所有渠道"""
        await asyncio.gather(*[ch.start() for ch in self.channels.values()])
    
    async def stop_all(self):
        """停止所有渠道"""
        await asyncio.gather(*[ch.stop() for ch in self.channels.values()])
    
    async def _process_message(self, msg: InboundMessage) -> OutboundMessage:
        """路由消息到 Agent"""
        session_key = f"{msg.channel}:{msg.channel_user_id}"
        response = await self.agent_context.process(
            message=msg.content,
            session_key=session_key
        )
        return OutboundMessage(content=response)
```

---

## 5. Phase 1: Discord + Telegram

### 5.1 Telegram 适配器

**文件**: `python/channels/telegram_adapter.py`

**依赖**: `pip install python-telegram-bot>=20.0`

```python
from telegram import Update
from telegram.ext import Application, MessageHandler, filters
from .base import ChannelAdapter, InboundMessage, OutboundMessage, Attachment, MessageType

class TelegramAdapter(ChannelAdapter):
    """Telegram Bot 适配器"""
    
    def __init__(self, config: dict):
        super().__init__(config)
        self.token = config["token"]
        self.app = None
    
    async def start(self):
        self.app = Application.builder().token(self.token).build()
        self.app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            self._on_message
        ))
        self.app.add_handler(MessageHandler(filters.PHOTO, self._on_photo))
        
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()
    
    async def stop(self):
        if self.app:
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()
    
    async def send(self, chat_id: str, message: OutboundMessage):
        # 分块发送长消息 (Telegram 限制 4096 字符)
        content = message.content
        for i in range(0, len(content), 4000):
            await self.app.bot.send_message(
                chat_id=int(chat_id),
                text=content[i:i+4000],
                parse_mode="Markdown"
            )
        
        for att in message.attachments:
            if att.type == MessageType.IMAGE:
                await self.app.bot.send_photo(chat_id=int(chat_id), photo=att.url or att.data)
    
    async def _on_message(self, update: Update, context):
        msg = self._convert(update)
        response = await self.handle(msg)
        await self.send(msg.channel_chat_id, response)
    
    async def _on_photo(self, update: Update, context):
        msg = self._convert(update)
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        msg.attachments.append(Attachment(type=MessageType.IMAGE, url=file.file_path))
        response = await self.handle(msg)
        await self.send(msg.channel_chat_id, response)
    
    def _convert(self, update: Update) -> InboundMessage:
        m = update.message
        return InboundMessage(
            channel="telegram",
            channel_user_id=str(m.from_user.id),
            channel_chat_id=str(m.chat_id),
            content=m.text or m.caption or "",
            message_id=str(m.message_id),
            is_group=m.chat.type in ["group", "supergroup"],
            metadata={"username": m.from_user.username}
        )
```

**创建 Bot 步骤**:
1. 在 Telegram 搜索 `@BotFather`
2. 发送 `/newbot` 并按提示操作
3. 获取 Bot Token

---

### 5.2 Discord 适配器

**文件**: `python/channels/discord_adapter.py`

**依赖**: `pip install discord.py>=2.0`

```python
import discord
from discord.ext import commands
from .base import ChannelAdapter, InboundMessage, OutboundMessage, Attachment, MessageType

class DiscordAdapter(ChannelAdapter):
    """Discord Bot 适配器"""
    
    def __init__(self, config: dict):
        super().__init__(config)
        self.token = config["token"]
        
        intents = discord.Intents.default()
        intents.message_content = True
        self.bot = commands.Bot(command_prefix="!", intents=intents)
        self._setup()
    
    def _setup(self):
        @self.bot.event
        async def on_ready():
            print(f"Discord: Logged in as {self.bot.user}")
        
        @self.bot.event
        async def on_message(message: discord.Message):
            if message.author == self.bot.user:
                return
            msg = self._convert(message)
            response = await self.handle(msg)
            await self.send(msg.channel_chat_id, response)
    
    async def start(self):
        await self.bot.start(self.token)
    
    async def stop(self):
        await self.bot.close()
    
    async def send(self, chat_id: str, message: OutboundMessage):
        channel = self.bot.get_channel(int(chat_id))
        if not channel:
            return
        
        # 分块发送 (Discord 限制 2000 字符)
        content = message.content
        for i in range(0, len(content), 1900):
            await channel.send(content[i:i+1900])
    
    def _convert(self, message: discord.Message) -> InboundMessage:
        attachments = [
            Attachment(
                type=MessageType.IMAGE if a.content_type and a.content_type.startswith("image") else MessageType.FILE,
                url=a.url,
                filename=a.filename
            )
            for a in message.attachments
        ]
        return InboundMessage(
            channel="discord",
            channel_user_id=str(message.author.id),
            channel_chat_id=str(message.channel.id),
            content=message.content,
            message_id=str(message.id),
            attachments=attachments,
            is_group=isinstance(message.channel, discord.TextChannel),
            metadata={"username": message.author.name}
        )
```

**创建 Bot 步骤**:
1. 访问 [Discord Developer Portal](https://discord.com/developers/applications)
2. 创建 Application → Bot
3. 开启 `MESSAGE CONTENT INTENT`
4. 获取 Bot Token
5. 使用 OAuth2 URL 邀请 Bot 到服务器

---

### 5.3 配置文件

**文件**: `conf/channels.yaml`

```yaml
# 渠道配置
channels:
  telegram:
    enabled: true
    token: "${TELEGRAM_BOT_TOKEN}"  # 环境变量
  
  discord:
    enabled: true
    token: "${DISCORD_BOT_TOKEN}"   # 环境变量
```

---

### 5.4 启动入口

**文件**: `run_channels.py`

```python
#!/usr/bin/env python
import asyncio
import os
import yaml
from python.channels.manager import ChannelManager
from python.channels.telegram_adapter import TelegramAdapter
from python.channels.discord_adapter import DiscordAdapter
from agent import AgentContext  # 假设现有

def load_config():
    with open("conf/channels.yaml") as f:
        config = yaml.safe_load(f)
    
    # 替换环境变量
    for channel, cfg in config.get("channels", {}).items():
        if "token" in cfg and cfg["token"].startswith("${"):
            env_key = cfg["token"][2:-1]
            cfg["token"] = os.environ.get(env_key, "")
    
    return config

async def main():
    config = load_config()
    context = AgentContext()  # 初始化 Agent
    manager = ChannelManager(context)
    
    channels_config = config.get("channels", {})
    
    if channels_config.get("telegram", {}).get("enabled"):
        manager.register("telegram", TelegramAdapter(channels_config["telegram"]))
    
    if channels_config.get("discord", {}).get("enabled"):
        manager.register("discord", DiscordAdapter(channels_config["discord"]))
    
    print(f"Starting {len(manager.channels)} channels...")
    
    try:
        await manager.start_all()
        await asyncio.Event().wait()  # 保持运行
    except KeyboardInterrupt:
        await manager.stop_all()

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 6. 后续渠道参考

### 6.1 Email (IMAP/SMTP)

**Python 库**: 标准库 `imaplib`, `smtplib`, `email`

```python
# 参考实现
class EmailAdapter(ChannelAdapter):
    def __init__(self, config):
        self.imap_host = config["imap_host"]
        self.smtp_host = config["smtp_host"]
        self.username = config["username"]
        self.password = config["password"]
    
    async def start(self):
        # 定期轮询 IMAP 收件箱
        self.imap = imaplib.IMAP4_SSL(self.imap_host)
        self.imap.login(self.username, self.password)
    
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

### 6.2 Slack

**Python 库**: `pip install slack-sdk`

```python
# 参考实现
from slack_sdk import WebClient
from slack_sdk.socket_mode import SocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest

class SlackAdapter(ChannelAdapter):
    def __init__(self, config):
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
    
    async def send(self, channel_id: str, message: OutboundMessage):
        self.client.chat_postMessage(
            channel=channel_id,
            text=message.content
        )
```

**创建 App 步骤**:
1. 访问 [Slack API](https://api.slack.com/apps)
2. 创建 App → From scratch
3. 添加 Bot Token Scopes: `chat:write`, `app_mentions:read`
4. 启用 Socket Mode
5. 安装到 Workspace

---

### 6.3 WeChat (企业微信)

**Python 库**: `pip install wechatpy` 或 `wechaty`

```python
# 参考实现 (企业微信)
from wechatpy.enterprise import WeChatClient

class WeChatAdapter(ChannelAdapter):
    def __init__(self, config):
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

### 6.4 WhatsApp

**Python 库**: Twilio API 或 WhatsApp Business API

```python
# 参考实现 (Twilio)
from twilio.rest import Client

class WhatsAppAdapter(ChannelAdapter):
    def __init__(self, config):
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

### 6.5 Matrix (开源 IM)

**Python 库**: `pip install matrix-nio`

```python
# 参考实现
from nio import AsyncClient, MatrixRoom, RoomMessageText

class MatrixAdapter(ChannelAdapter):
    def __init__(self, config):
        self.homeserver = config["homeserver"]
        self.user_id = config["user_id"]
        self.password = config["password"]
        self.client = AsyncClient(self.homeserver, self.user_id)
    
    async def start(self):
        await self.client.login(self.password)
        self.client.add_event_callback(self._on_message, RoomMessageText)
        await self.client.sync_forever()
    
    async def send(self, room_id: str, message: OutboundMessage):
        await self.client.room_send(
            room_id=room_id,
            message_type="m.room.message",
            content={"msgtype": "m.text", "body": message.content}
        )
```

---

## 7. 测试与验收

### 7.1 单元测试

| 测试文件 | 覆盖模块 | 测试点 |
|----------|----------|--------|
| test_message.py | base.py | 消息序列化/反序列化 |
| test_telegram.py | telegram_adapter.py | 消息转换、发送 |
| test_discord.py | discord_adapter.py | 消息转换、分块发送 |
| test_manager.py | manager.py | 多渠道注册、路由 |

### 7.2 集成测试

```python
# tests/integration/test_channels_e2e.py

async def test_telegram_roundtrip():
    """Telegram 端到端测试"""
    adapter = TelegramAdapter({"token": TEST_TOKEN})
    # 模拟收到消息
    # 验证响应发送

async def test_multi_channel():
    """多渠道同时运行"""
    manager = ChannelManager(mock_context)
    manager.register("telegram", TelegramAdapter(...))
    manager.register("discord", DiscordAdapter(...))
    await manager.start_all()
    # 验证两个渠道都能响应
```

### 7.3 验收标准

| 功能 | 标准 | 测试方法 |
|------|------|----------|
| Telegram 文本消息 | 收发正常 | 手动测试 |
| Telegram 图片消息 | 能接收图片 | 手动测试 |
| Discord 文本消息 | 收发正常 | 手动测试 |
| Discord 频道/私信 | 都能响应 | 手动测试 |
| 长消息分块 | 不报错 | 发送 5000 字 |
| 多渠道同时运行 | 稳定 | 运行 1 小时 |

---

## 附录

### A. 依赖清单

```
# requirements.txt 新增
python-telegram-bot>=20.0
discord.py>=2.0
pyyaml>=6.0
```

### B. 环境变量

```bash
# .env
TELEGRAM_BOT_TOKEN=your_telegram_token
DISCORD_BOT_TOKEN=your_discord_token
```

### C. 参考资料

- [python-telegram-bot Docs](https://docs.python-telegram-bot.org/)
- [discord.py Docs](https://discordpy.readthedocs.io/)
- [OpenClaw Channel Architecture](https://github.com/user/openclaw)

---

> **文档维护者**: AI Assistant  
> **最后更新**: 2026-01-30
