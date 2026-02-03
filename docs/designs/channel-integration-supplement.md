# Agent Zero 多渠道网关开发计划 - 补充文档

> **版本**: 1.0
> **创建日期**: 2026-02-01
> **作者**: 浮浮酱 (AI Assistant)
> **关联文档**: [channel-integration-plan-v4.md](./channel-integration-plan-v4.md)
> **目的**: 对 V4 开发计划的审阅修正与功能增强

---

## 📋 目录

- [1. 文档概述](#1-文档概述)
- [2. 高风险问题修正](#2-高风险问题修正)
- [3. 中风险问题修正](#3-中风险问题修正)
- [4. 遗漏模块补充](#4-遗漏模块补充)
- [5. 流式响应完整实现](#5-流式响应完整实现)
- [6. 文件结构补充](#6-文件结构补充)
- [7. 实施优先级建议](#7-实施优先级建议)

---

## 1. 文档概述

### 1.1 审阅结论

| 维度 | 评分 | 说明 |
|------|------|------|
| **架构设计** | ⭐⭐⭐⭐⭐ | 单进程并行架构设计合理，充分利用了 AgentContext 共享机制 |
| **API 验证** | ⭐⭐⭐⭐⭐ | 调研文档非常详尽，关键修正已经到位 |
| **代码完备性** | ⭐⭐⭐⭐☆ | 核心模块完整，但有几处细节需要补充 |
| **可行性** | ⭐⭐⭐⭐⭐ | 技术路径验证充分，完全可行 |
| **风险控制** | ⭐⭐⭐⭐☆ | 大部分风险已考虑，但有遗漏 |

### 1.2 本文档内容

本文档包含以下修正与增强：

| 类别 | 内容 | 重要性 |
|------|------|--------|
| 🔴 高风险修正 | AgentBridge 线程安全、Discord 生命周期管理 | 必须修复 |
| 🟡 中风险修正 | 流式响应竞态、附件清理、优雅降级 | 建议修复 |
| 🟢 功能补充 | 消息去重、会话清理、Extension 文件 | 可选增强 |
| 📝 实现补充 | Telegram/Discord 流式编辑完整实现 | 必须补充 |

---

## 2. 高风险问题修正

### 2.1 AgentBridge 线程安全修正

**问题描述**:

V4 文档中的 `AgentBridge.get_or_create_context()` 方法没有线程锁保护，在多线程环境下（Gateway 线程 + Web UI 线程）可能导致：
- 竞态条件：同时创建相同 session_key 的 context
- 数据不一致：`_sessions` 字典的并发读写

**修正后的完整 AgentBridge 实现**:

```python
"""
Agent Zero 桥接层 (V4.1 线程安全修正版)

文件: python/gateway/agent_bridge.py
"""

import asyncio
import logging
import threading
from typing import AsyncGenerator, Dict, Optional, Any, Callable, Awaitable
from datetime import datetime, timezone
from dataclasses import dataclass

from agent import Agent, AgentContext, AgentConfig, UserMessage, AgentContextType
from initialize import initialize_agent

logger = logging.getLogger("gateway.agent_bridge")


@dataclass
class ChannelSession:
    """渠道会话信息"""
    context_id: str
    channel: str
    channel_user_id: str
    channel_chat_id: str
    user_name: Optional[str] = None
    created_at: datetime = None
    last_activity: datetime = None

    def __post_init__(self):
        now = datetime.now(timezone.utc)
        self.created_at = self.created_at or now
        self.last_activity = self.last_activity or now


class AgentBridge:
    """Gateway 与 Agent Zero 的桥接层 (线程安全版)"""

    # 流式响应结束标记
    _STREAM_END = object()

    def __init__(self, default_config: AgentConfig = None):
        """
        初始化桥接层

        Args:
            default_config: 默认 Agent 配置，如果不提供则自动获取
        """
        self.default_config = default_config or initialize_agent()
        self._sessions: Dict[str, ChannelSession] = {}
        self._lock = threading.Lock()  # ✅ 线程锁保护

    def _make_session_key(self, channel: str, channel_user_id: str) -> str:
        """
        生成会话键

        使用前缀区分渠道，避免与 Web UI 的纯随机 ID 冲突
        """
        prefix_map = {
            "telegram": "tg",
            "discord": "dc",
            "email": "em",
            "slack": "sl",
            "wechat": "wx",
            "whatsapp": "wa",
            "matrix": "mx",
        }
        prefix = prefix_map.get(channel, channel[:2])
        return f"{prefix}:{channel_user_id}"

    def get_or_create_context(
        self,
        channel: str,
        channel_user_id: str,
        channel_chat_id: str,
        user_name: Optional[str] = None,
        channel_config: Optional[dict] = None,
    ) -> AgentContext:
        """
        获取或创建 AgentContext (线程安全)

        会话键格式: {prefix}:{user_id}
        例如: tg:456789, dc:123456789
        """
        session_key = self._make_session_key(channel, channel_user_id)

        with self._lock:  # ✅ 线程锁保护
            # 尝试获取现有 context
            existing_ctx = AgentContext.get(session_key)
            if existing_ctx:
                # 更新活动时间
                if session_key in self._sessions:
                    self._sessions[session_key].last_activity = datetime.now(timezone.utc)
                return existing_ctx

            # 创建新的 context
            config = self._build_config(channel_config)

            ctx = AgentContext(
                config=config,
                id=session_key,
                name=f"{channel}:{user_name or channel_user_id}",
                type=AgentContextType.USER,
            )

            # 记录会话信息
            self._sessions[session_key] = ChannelSession(
                context_id=session_key,
                channel=channel,
                channel_user_id=channel_user_id,
                channel_chat_id=channel_chat_id,
                user_name=user_name,
            )

            logger.info(f"Created new context: {session_key}")
            return ctx

    def _build_config(self, channel_config: Optional[dict] = None) -> AgentConfig:
        """构建 Agent 配置，支持渠道专用配置覆盖"""
        if not channel_config:
            return self.default_config

        model_override = channel_config.get("model_override", {})
        if not model_override:
            return self.default_config

        import copy
        config = copy.deepcopy(self.default_config)
        # 支持渠道专用模型配置（根据需要扩展）
        return config

    async def process_message(
        self,
        channel: str,
        channel_user_id: str,
        channel_chat_id: str,
        content: str,
        user_name: Optional[str] = None,
        attachments: list = None,
        metadata: dict = None,
        channel_config: dict = None,
        stream_callback: Callable[[str, str], Awaitable[None]] = None,
    ) -> str:
        """
        处理渠道消息

        Args:
            channel: 渠道名称 (telegram, discord)
            channel_user_id: 渠道用户 ID
            channel_chat_id: 渠道会话 ID
            content: 消息内容
            user_name: 用户名
            attachments: 附件文件路径列表 (必须是本地路径)
            metadata: 额外元数据
            channel_config: 渠道配置
            stream_callback: 流式响应回调 async def(chunk: str, full: str)

        Returns:
            Agent 的完整响应
        """
        # 获取或创建 context
        ctx = self.get_or_create_context(
            channel=channel,
            channel_user_id=channel_user_id,
            channel_chat_id=channel_chat_id,
            user_name=user_name,
            channel_config=channel_config,
        )

        # 构建 UserMessage
        user_msg = UserMessage(
            message=content,
            attachments=attachments or [],
            system_message=[],
        )

        # 存储渠道元数据到 context
        ctx.set_data("channel_metadata", {
            "channel": channel,
            "chat_id": channel_chat_id,
            "user_id": channel_user_id,
            "user_name": user_name,
            **(metadata or {}),
        })

        # 注册流式回调 (通过 Extension 机制)
        if stream_callback:
            ctx.set_data("gateway_stream_callback", stream_callback)

        try:
            # 调用 Agent 的 communicate 方法
            task = ctx.communicate(user_msg)

            # 等待任务完成
            if task:
                response = await task.result()
                return response or ""
            return ""

        finally:
            # 清理流式回调
            ctx.set_data("gateway_stream_callback", None)

    async def process_message_stream(
        self,
        channel: str,
        channel_user_id: str,
        channel_chat_id: str,
        content: str,
        user_name: Optional[str] = None,
        attachments: list = None,
        metadata: dict = None,
        channel_config: dict = None,
    ) -> AsyncGenerator[str, None]:
        """
        处理消息并以流式方式返回响应 (竞态条件修正版)

        使用 sentinel 值标记结束，避免竞态条件

        Yields:
            响应片段
        """
        response_queue: asyncio.Queue = asyncio.Queue()

        async def stream_callback(chunk: str, full: str):
            await response_queue.put(chunk)

        async def process_task():
            try:
                await self.process_message(
                    channel=channel,
                    channel_user_id=channel_user_id,
                    channel_chat_id=channel_chat_id,
                    content=content,
                    user_name=user_name,
                    attachments=attachments,
                    metadata=metadata,
                    channel_config=channel_config,
                    stream_callback=stream_callback,
                )
            finally:
                # ✅ 使用 sentinel 值明确标记结束
                await response_queue.put(self._STREAM_END)

        task = asyncio.create_task(process_task())

        try:
            while True:
                chunk = await response_queue.get()
                if chunk is self._STREAM_END:
                    break
                yield chunk
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    def get_session(self, channel: str, channel_user_id: str) -> Optional[ChannelSession]:
        """获取会话信息 (线程安全)"""
        session_key = self._make_session_key(channel, channel_user_id)
        with self._lock:
            return self._sessions.get(session_key)

    def list_sessions(self) -> Dict[str, ChannelSession]:
        """列出所有会话 (线程安全)"""
        with self._lock:
            return self._sessions.copy()

    def remove_session(self, channel: str, channel_user_id: str) -> bool:
        """移除会话 (线程安全)"""
        session_key = self._make_session_key(channel, channel_user_id)
        with self._lock:
            if session_key in self._sessions:
                del self._sessions[session_key]
                AgentContext.remove(session_key)
                logger.info(f"Removed session: {session_key}")
                return True
            return False

    def get_sessions_by_channel(self, channel: str) -> Dict[str, ChannelSession]:
        """获取指定渠道的所有会话"""
        with self._lock:
            return {
                k: v for k, v in self._sessions.items()
                if v.channel == channel
            }
```

### 2.2 Discord 适配器生命周期管理修正

**问题描述**:

V4 文档中的 Discord 适配器 `stop()` 方法存在问题：
- `call_soon_threadsafe` 后没有等待事件循环真正停止
- 可能导致资源泄漏和未完成的协程

**修正后的 Discord 适配器关键方法**:

```python
"""
Discord Bot 适配器 (V4.1 生命周期修正版)

文件: python/channels/discord_adapter.py
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
    """Discord Bot 适配器 (生命周期修正版)"""

    def __init__(self, config: dict, account_id: str = "default"):
        super().__init__(config, account_id)
        self.token = config["token"]
        self.respond_to_dms = config.get("respond_to_dms", True)
        self.require_mention = config.get("require_mention", True)
        self.allowed_guilds = config.get("allowed_guilds", [])

        intents = discord.Intents.default()
        intents.message_content = True
        self.bot = commands.Bot(command_prefix="!", intents=intents)

        # 线程通信
        self._main_loop: Optional[asyncio.AbstractEventLoop] = None
        self._discord_loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._shutdown_event = threading.Event()  # ✅ 新增: 关闭事件

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
            supports_streaming_edit=True,
            edit_rate_limit_ms=1000,
        )

    def _setup(self):
        @self.bot.event
        async def on_ready():
            logger.info(f"Discord: Logged in as {self.bot.user}")
            self.reset_reconnect_counter()

        @self.bot.event
        async def on_message(message: discord.Message):
            if message.author == self.bot.user:
                return
            if not self._should_respond(message):
                return

            inbound = self._convert(message)

            # 使用 run_coroutine_threadsafe 在主线程处理
            future = asyncio.run_coroutine_threadsafe(
                self._handle_in_main_loop(inbound),
                self._main_loop
            )

            try:
                # 使用 run_in_executor 避免阻塞 Discord 事件循环
                response = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: future.result(timeout=300)
                )
                await self._send_response(message.channel, response)
            except asyncio.TimeoutError:
                logger.error(f"Message processing timeout")
                await message.channel.send("⚠️ 处理超时，请稍后重试")
            except Exception as e:
                logger.error(f"Error handling message: {e}")
                await message.channel.send("⚠️ 处理消息时出错")

        @self.bot.event
        async def on_disconnect():
            logger.warning("Discord disconnected, will reconnect...")

        @self.bot.event
        async def on_error(event, *args, **kwargs):
            logger.error(f"Discord error in {event}")

    async def _handle_in_main_loop(self, inbound: InboundMessage) -> OutboundMessage:
        """在主事件循环中处理消息（线程安全）"""
        return await self.handle(inbound)

    async def start(self):
        """启动 Discord Bot"""
        self._main_loop = asyncio.get_running_loop()
        self._discord_loop = asyncio.new_event_loop()
        self._shutdown_event.clear()

        self._thread = threading.Thread(target=self._run_in_thread, daemon=True)
        self._thread.start()

        self._running = True
        logger.info(f"Discord adapter started: {self.account_id}")

    def _run_in_thread(self):
        """独立线程运行 Discord 事件循环"""
        asyncio.set_event_loop(self._discord_loop)
        try:
            self._discord_loop.run_until_complete(self.bot.start(self.token))
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Discord thread error: {e}")
        finally:
            self._discord_loop.run_until_complete(self._cleanup())
            self._discord_loop.close()
            self._shutdown_event.set()

    async def _cleanup(self):
        """清理 Discord 资源"""
        try:
            if not self.bot.is_closed():
                await self.bot.close()
        except Exception as e:
            logger.error(f"Error during Discord cleanup: {e}")

    async def stop(self):
        """停止 Discord Bot (优雅关闭)"""
        self._running = False

        if self._discord_loop and self._discord_loop.is_running():
            # ✅ 在 Discord 事件循环中安排关闭
            future = asyncio.run_coroutine_threadsafe(
                self.bot.close(),
                self._discord_loop
            )
            try:
                future.result(timeout=10)
            except Exception as e:
                logger.warning(f"Discord close timeout: {e}")
                # 强制停止事件循环
                self._discord_loop.call_soon_threadsafe(self._discord_loop.stop)

        # ✅ 等待线程结束
        if self._thread and self._thread.is_alive():
            self._shutdown_event.wait(timeout=15)
            if self._thread.is_alive():
                logger.warning("Discord thread did not terminate gracefully")

        logger.info(f"Discord adapter stopped: {self.account_id}")

    async def send(self, chat_id: str, message: OutboundMessage):
        """发送消息到指定频道"""
        channel = self.bot.get_channel(int(chat_id))
        if channel:
            await self._send_response(channel, message)

    async def _send_response(self, channel, message: OutboundMessage):
        """发送响应消息"""
        content = message.content
        max_len = 1900

        for i in range(0, len(content), max_len):
            chunk = content[i:i + max_len]
            await channel.send(chunk)

    def _should_respond(self, message: discord.Message) -> bool:
        if isinstance(message.channel, discord.DMChannel):
            return self.respond_to_dms
        if self.allowed_guilds:
            if message.guild and message.guild.id not in self.allowed_guilds:
                return False
        if self.require_mention:
            if self.bot.user not in message.mentions:
                return False
        return True

    def _convert(self, message: discord.Message) -> InboundMessage:
        content = message.content
        if self.bot.user:
            content = content.replace(f"<@{self.bot.user.id}>", "").strip()
            content = content.replace(f"<@!{self.bot.user.id}>", "").strip()

        attachments = []
        for a in message.attachments:
            att_type = MessageType.IMAGE if a.content_type and a.content_type.startswith("image") else MessageType.FILE
            attachments.append(Attachment(
                type=att_type,
                url=a.url,
                filename=a.filename,
                mime_type=a.content_type,
                size=a.size,
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
            }
        )
```

---

## 3. 中风险问题修正

### 3.1 附件清理机制

**问题描述**:

调研文档说明附件必须下载到本地 `tmp/uploads` 目录，但没有清理机制，长期运行会导致磁盘空间耗尽。

**完整的附件处理器实现**:

```python
"""
Gateway 附件处理器

文件: python/gateway/attachment_handler.py
"""

import os
import asyncio
import logging
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timedelta
from typing import Optional
import aiohttp
from werkzeug.utils import secure_filename

logger = logging.getLogger("gateway.attachment")


class AttachmentHandler:
    """Gateway 附件处理器 (带 TTL 清理)"""

    def __init__(self, upload_folder: str = None, ttl_hours: int = 24):
        """
        初始化附件处理器

        Args:
            upload_folder: 上传目录，默认为 tmp/uploads
            ttl_hours: 文件保留时间（小时）
        """
        from python.helpers import files, runtime

        self.upload_folder = upload_folder or files.get_abs_path("tmp/uploads")
        self.internal_path_prefix = "/a0/tmp/uploads"  # Docker 内部路径
        self.ttl_hours = ttl_hours
        self.is_docker = runtime.is_dockerized() if hasattr(runtime, 'is_dockerized') else False

        # 确保目录存在
        os.makedirs(self.upload_folder, exist_ok=True)

        # 清理任务
        self._cleanup_task: Optional[asyncio.Task] = None

    async def start_cleanup_task(self):
        """启动定期清理任务"""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            logger.info(f"Attachment cleanup task started (TTL: {self.ttl_hours}h)")

    async def stop_cleanup_task(self):
        """停止清理任务"""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

    async def _cleanup_loop(self):
        """定期清理过期文件"""
        while True:
            try:
                await asyncio.sleep(3600)  # 每小时检查一次
                await self._cleanup_old_files()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Cleanup error: {e}")

    async def _cleanup_old_files(self):
        """清理过期文件"""
        cutoff = datetime.now() - timedelta(hours=self.ttl_hours)
        cutoff_timestamp = cutoff.timestamp()
        cleaned_count = 0

        try:
            for f in Path(self.upload_folder).iterdir():
                if f.is_file() and f.stat().st_mtime < cutoff_timestamp:
                    f.unlink(missing_ok=True)
                    cleaned_count += 1

            if cleaned_count > 0:
                logger.info(f"Cleaned up {cleaned_count} expired attachment(s)")
        except Exception as e:
            logger.error(f"Error during file cleanup: {e}")

    async def download_from_url(
        self,
        url: str,
        original_filename: str = None,
        timeout: int = 60
    ) -> str:
        """
        从 URL 下载附件并返回本地路径

        Args:
            url: 媒体文件 URL
            original_filename: 原始文件名（用于保留扩展名）
            timeout: 下载超时时间（秒）

        Returns:
            本地文件路径（用于传给 UserMessage.attachments）
        """
        # 提取扩展名
        if original_filename:
            ext = os.path.splitext(secure_filename(original_filename))[1]
        else:
            ext = os.path.splitext(url.split('?')[0])[1] or '.bin'

        # 生成唯一文件名
        unique_filename = f"{uuid4().hex}{ext}"
        local_path = os.path.join(self.upload_folder, unique_filename)

        # 下载文件
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status == 200:
                    with open(local_path, 'wb') as f:
                        f.write(await resp.read())
                else:
                    raise Exception(f"Failed to download attachment: HTTP {resp.status}")

        logger.debug(f"Downloaded attachment: {unique_filename}")

        # 返回适当的路径
        if self.is_docker:
            return os.path.join(self.internal_path_prefix, unique_filename)
        else:
            return local_path

    async def save_from_bytes(self, data: bytes, filename: str) -> str:
        """
        从二进制数据保存附件

        Args:
            data: 文件二进制数据
            filename: 原始文件名

        Returns:
            本地文件路径
        """
        safe_name = secure_filename(filename)
        ext = os.path.splitext(safe_name)[1] or '.bin'
        unique_filename = f"{uuid4().hex}{ext}"
        local_path = os.path.join(self.upload_folder, unique_filename)

        with open(local_path, 'wb') as f:
            f.write(data)

        if self.is_docker:
            return os.path.join(self.internal_path_prefix, unique_filename)
        else:
            return local_path

    def cleanup_file(self, file_path: str):
        """
        立即清理指定文件

        Args:
            file_path: 文件路径（支持 Docker 内部路径）
        """
        try:
            # 转换为实际本地路径
            if file_path.startswith(self.internal_path_prefix):
                filename = os.path.basename(file_path)
                actual_path = os.path.join(self.upload_folder, filename)
            else:
                actual_path = file_path

            if os.path.exists(actual_path):
                os.remove(actual_path)
                logger.debug(f"Cleaned up attachment: {actual_path}")
        except Exception as e:
            logger.warning(f"Failed to cleanup attachment {file_path}: {e}")

    def get_local_path(self, internal_path: str) -> str:
        """将内部路径转换为实际本地路径"""
        if internal_path.startswith(self.internal_path_prefix):
            filename = os.path.basename(internal_path)
            return os.path.join(self.upload_folder, filename)
        return internal_path
```

### 3.2 优雅降级与用户友好错误消息

**问题描述**:

当前错误消息直接暴露内部错误信息，对用户不友好且可能泄露敏感信息。

**错误处理增强模块**:

```python
"""
Gateway 错误处理模块

文件: python/gateway/errors.py
"""

import logging
import asyncio
from typing import Dict, Optional
from enum import Enum
from dataclasses import dataclass

logger = logging.getLogger("gateway.errors")


class ErrorType(Enum):
    """错误类型"""
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    ACCESS_DENIED = "access_denied"
    INVALID_MESSAGE = "invalid_message"
    AGENT_ERROR = "agent_error"
    NETWORK_ERROR = "network_error"
    INTERNAL_ERROR = "internal_error"


@dataclass
class ErrorMessage:
    """错误消息配置"""
    user_message: str  # 显示给用户的消息
    log_level: str     # 日志级别
    include_retry: bool = False  # 是否包含重试提示


# 多语言错误消息配置
ERROR_MESSAGES: Dict[str, Dict[ErrorType, ErrorMessage]] = {
    "zh": {
        ErrorType.TIMEOUT: ErrorMessage(
            user_message="处理时间过长，请稍后重试",
            log_level="warning",
            include_retry=True
        ),
        ErrorType.RATE_LIMIT: ErrorMessage(
            user_message="请求太频繁，请稍后再试",
            log_level="warning",
            include_retry=True
        ),
        ErrorType.ACCESS_DENIED: ErrorMessage(
            user_message="抱歉，您没有使用权限",
            log_level="warning"
        ),
        ErrorType.INVALID_MESSAGE: ErrorMessage(
            user_message="消息格式不正确，请重新发送",
            log_level="info"
        ),
        ErrorType.AGENT_ERROR: ErrorMessage(
            user_message="AI 处理时遇到问题，请重试",
            log_level="error",
            include_retry=True
        ),
        ErrorType.NETWORK_ERROR: ErrorMessage(
            user_message="网络连接出现问题，请稍后重试",
            log_level="error",
            include_retry=True
        ),
        ErrorType.INTERNAL_ERROR: ErrorMessage(
            user_message="系统出现问题，工程师正在处理中",
            log_level="error"
        ),
    },
    "en": {
        ErrorType.TIMEOUT: ErrorMessage(
            user_message="Request timed out, please try again later",
            log_level="warning",
            include_retry=True
        ),
        ErrorType.RATE_LIMIT: ErrorMessage(
            user_message="Too many requests, please slow down",
            log_level="warning",
            include_retry=True
        ),
        ErrorType.ACCESS_DENIED: ErrorMessage(
            user_message="Sorry, you don't have permission",
            log_level="warning"
        ),
        ErrorType.INVALID_MESSAGE: ErrorMessage(
            user_message="Invalid message format, please try again",
            log_level="info"
        ),
        ErrorType.AGENT_ERROR: ErrorMessage(
            user_message="AI encountered an issue, please retry",
            log_level="error",
            include_retry=True
        ),
        ErrorType.NETWORK_ERROR: ErrorMessage(
            user_message="Network error, please try again later",
            log_level="error",
            include_retry=True
        ),
        ErrorType.INTERNAL_ERROR: ErrorMessage(
            user_message="System error, we're working on it",
            log_level="error"
        ),
    }
}


class ErrorHandler:
    """错误处理器"""

    def __init__(self, default_language: str = "zh"):
        self.default_language = default_language

    def classify_error(self, error: Exception) -> ErrorType:
        """将异常分类为错误类型"""
        error_str = str(error).lower()

        if isinstance(error, asyncio.TimeoutError):
            return ErrorType.TIMEOUT
        elif "timeout" in error_str:
            return ErrorType.TIMEOUT
        elif "rate limit" in error_str or "too many" in error_str:
            return ErrorType.RATE_LIMIT
        elif "access denied" in error_str or "permission" in error_str:
            return ErrorType.ACCESS_DENIED
        elif "invalid" in error_str or "format" in error_str:
            return ErrorType.INVALID_MESSAGE
        elif "network" in error_str or "connection" in error_str:
            return ErrorType.NETWORK_ERROR
        elif "agent" in error_str:
            return ErrorType.AGENT_ERROR
        else:
            return ErrorType.INTERNAL_ERROR

    def format_error(
        self,
        error: Exception,
        language: str = None,
        log_error: bool = True
    ) -> str:
        """
        格式化错误为用户友好的消息

        Args:
            error: 异常对象
            language: 语言代码 (zh/en)
            log_error: 是否记录日志

        Returns:
            用户友好的错误消息
        """
        lang = language or self.default_language
        error_type = self.classify_error(error)

        messages = ERROR_MESSAGES.get(lang, ERROR_MESSAGES["en"])
        error_msg = messages.get(error_type, messages[ErrorType.INTERNAL_ERROR])

        # 记录日志
        if log_error:
            log_func = getattr(logger, error_msg.log_level, logger.error)
            log_func(f"[{error_type.value}] {error}")

        # 构建用户消息
        user_message = f"⚠️ {error_msg.user_message}"
        if error_msg.include_retry:
            retry_hint = " 🔄" if lang == "zh" else " (retry)"
            user_message += retry_hint

        return user_message

    def get_error_response(
        self,
        error_type: ErrorType,
        language: str = None
    ) -> str:
        """直接获取指定类型的错误消息"""
        lang = language or self.default_language
        messages = ERROR_MESSAGES.get(lang, ERROR_MESSAGES["en"])
        error_msg = messages.get(error_type, messages[ErrorType.INTERNAL_ERROR])
        return f"⚠️ {error_msg.user_message}"


# 全局错误处理器实例
error_handler = ErrorHandler()
```

### 3.3 热重载配置变更检测

**问题描述**:

热重载行为矩阵中提到 `token` 变更需要重启，但代码中没有检测并警告。

**增强的配置变更检测**:

```python
"""
配置变更检测增强

添加到: python/channels/manager.py
"""

class ChannelManager:
    # ... 现有代码 ...

    async def apply_config_change(self, new_config: dict):
        """应用配置变更 (增强版)"""
        channels_config = new_config.get("channels", {})
        changes_summary = []
        restart_required = []

        for channel_name, channel_cfg in channels_config.items():
            full_name = f"{channel_name}:{channel_cfg.get('account_id', 'default')}"

            # 检测需要重启的变更
            if full_name in self.channels:
                old_cfg = self.channels[full_name].config

                # Token 变更检测
                if old_cfg.get("token") != channel_cfg.get("token"):
                    restart_required.append(f"{full_name}: token changed")
                    logger.warning(
                        f"⚠️ Token changed for {full_name}, restart required!"
                    )

                # 其他需要重启的配置
                restart_fields = ["token", "application_id", "client_id"]
                for field in restart_fields:
                    if old_cfg.get(field) != channel_cfg.get(field):
                        if field not in [f.split(":")[1] for f in restart_required if full_name in f]:
                            restart_required.append(f"{full_name}: {field} changed")

            # 禁用渠道
            if not channel_cfg.get("enabled", False):
                if full_name in self.channels:
                    await self._stop_channel(full_name, self.channels[full_name])
                    self.unregister(full_name)
                    changes_summary.append(f"Disabled: {full_name}")

            # 更新可热重载的配置
            if full_name in self.channels:
                adapter = self.channels[full_name]

                # 白名单/黑名单即时生效
                if "whitelist" in channel_cfg:
                    adapter.config["whitelist"] = channel_cfg["whitelist"]
                    changes_summary.append(f"Updated whitelist: {full_name}")

                if "require_mention" in channel_cfg:
                    adapter.config["require_mention"] = channel_cfg["require_mention"]
                    changes_summary.append(f"Updated require_mention: {full_name}")

        # 重载安全配置
        if self.security_manager:
            self.security_manager.reload_config(
                type('Config', (), {'channels': channels_config})()
            )

        # 日志摘要
        if changes_summary:
            logger.info(f"Config changes applied: {', '.join(changes_summary)}")
        if restart_required:
            logger.warning(
                f"⚠️ Restart required for changes: {', '.join(restart_required)}"
            )

        return {
            "applied": changes_summary,
            "restart_required": restart_required
        }
```

---

## 4. 遗漏模块补充

### 4.1 消息去重器

**用途**: 防止因网络抖动导致的重复消息处理

```python
"""
消息去重器

文件: python/gateway/deduplicator.py
"""

import logging
from collections import OrderedDict
from datetime import datetime, timedelta
from typing import Optional
import threading

logger = logging.getLogger("gateway.deduplicator")


class MessageDeduplicator:
    """消息去重器 (线程安全)"""

    def __init__(self, ttl_seconds: int = 60, max_size: int = 1000):
        """
        初始化去重器

        Args:
            ttl_seconds: 消息 ID 保留时间（秒）
            max_size: 最大缓存消息数
        """
        self.ttl_seconds = ttl_seconds
        self.max_size = max_size
        self._seen: OrderedDict[str, datetime] = OrderedDict()
        self._lock = threading.Lock()

    def is_duplicate(self, message_id: str, channel: str) -> bool:
        """
        检查消息是否重复

        Args:
            message_id: 消息 ID
            channel: 渠道名称

        Returns:
            True 如果是重复消息
        """
        key = f"{channel}:{message_id}"
        now = datetime.now()

        with self._lock:
            # 清理过期记录
            self._cleanup(now)

            if key in self._seen:
                logger.debug(f"Duplicate message detected: {key}")
                return True

            self._seen[key] = now
            return False

    def _cleanup(self, now: datetime):
        """清理过期记录 (需要在锁内调用)"""
        cutoff = now - timedelta(seconds=self.ttl_seconds)

        # 清理过期
        while self._seen:
            key, timestamp = next(iter(self._seen.items()))
            if timestamp < cutoff:
                del self._seen[key]
            else:
                break

        # 限制大小
        while len(self._seen) > self.max_size:
            self._seen.popitem(last=False)

    def clear(self):
        """清空所有记录"""
        with self._lock:
            self._seen.clear()

    @property
    def size(self) -> int:
        """当前缓存大小"""
        with self._lock:
            return len(self._seen)
```

### 4.2 会话清理器

**用途**: 定期清理长期未活跃的会话，释放内存

```python
"""
会话清理器

文件: python/gateway/session_cleaner.py
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, List, Tuple

if TYPE_CHECKING:
    from .agent_bridge import AgentBridge

logger = logging.getLogger("gateway.session_cleaner")


class SessionCleaner:
    """会话清理器"""

    def __init__(
        self,
        agent_bridge: "AgentBridge",
        max_idle_hours: int = 24,
        check_interval_seconds: int = 3600
    ):
        """
        初始化会话清理器

        Args:
            agent_bridge: AgentBridge 实例
            max_idle_hours: 最大空闲时间（小时）
            check_interval_seconds: 检查间隔（秒）
        """
        self.agent_bridge = agent_bridge
        self.max_idle_hours = max_idle_hours
        self.check_interval = check_interval_seconds
        self._task: asyncio.Task = None
        self._running = False

    async def start(self):
        """启动清理任务"""
        if self._task is None or self._task.done():
            self._running = True
            self._task = asyncio.create_task(self._cleanup_loop())
            logger.info(
                f"Session cleaner started (max_idle: {self.max_idle_hours}h, "
                f"interval: {self.check_interval}s)"
            )

    async def stop(self):
        """停止清理任务"""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Session cleaner stopped")

    async def _cleanup_loop(self):
        """清理循环"""
        while self._running:
            try:
                await asyncio.sleep(self.check_interval)
                if self._running:
                    await self.cleanup_idle_sessions()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Session cleanup error: {e}")

    async def cleanup_idle_sessions(self) -> int:
        """
        清理空闲会话

        Returns:
            清理的会话数量
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.max_idle_hours)

        # 收集需要清理的会话
        sessions_to_remove: List[Tuple[str, str]] = []

        for key, session in self.agent_bridge.list_sessions().items():
            if session.last_activity < cutoff:
                sessions_to_remove.append((session.channel, session.channel_user_id))

        # 执行清理
        cleaned_count = 0
        for channel, user_id in sessions_to_remove:
            if self.agent_bridge.remove_session(channel, user_id):
                cleaned_count += 1

        if cleaned_count > 0:
            logger.info(f"Cleaned up {cleaned_count} idle session(s)")

        return cleaned_count

    def get_idle_sessions(self, idle_hours: int = None) -> List[dict]:
        """
        获取空闲会话列表

        Args:
            idle_hours: 空闲时间阈值，默认使用配置值

        Returns:
            空闲会话信息列表
        """
        hours = idle_hours or self.max_idle_hours
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

        idle_sessions = []
        for key, session in self.agent_bridge.list_sessions().items():
            if session.last_activity < cutoff:
                idle_time = datetime.now(timezone.utc) - session.last_activity
                idle_sessions.append({
                    "session_key": key,
                    "channel": session.channel,
                    "user_id": session.channel_user_id,
                    "user_name": session.user_name,
                    "idle_hours": idle_time.total_seconds() / 3600,
                    "last_activity": session.last_activity.isoformat(),
                })

        return idle_sessions
```

### 4.3 Gateway 流式响应 Extension

**用途**: 将 Agent 的流式响应传递给 Gateway 注册的回调函数

```python
"""
Gateway 流式响应扩展

文件: python/extensions/response_stream_chunk/_20_gateway_callback.py
"""

from python.helpers.extension import Extension
from typing import TYPE_CHECKING
import logging

if TYPE_CHECKING:
    from agent import Agent

logger = logging.getLogger("gateway.extension")


class GatewayCallback(Extension):
    """
    Gateway 流式回调扩展

    将 Agent 的流式响应传递给 Gateway 注册的回调函数。
    Gateway 通过 ctx.set_data("gateway_stream_callback", callback) 注册回调。
    """

    async def execute(self, loop_data=None, stream_data=None, **kwargs):
        """
        执行流式回调

        Args:
            loop_data: Agent 循环数据
            stream_data: 流式数据 {"chunk": str, "full": str}
        """
        if not stream_data:
            return

        agent: "Agent" = self.agent
        ctx = agent.context

        # 从 context.data 获取 Gateway 注册的回调
        callback = ctx.get_data("gateway_stream_callback")
        if callback:
            chunk = stream_data.get("chunk", "")
            full = stream_data.get("full", "")
            try:
                await callback(chunk, full)
            except Exception as e:
                # 静默处理回调错误，不影响主流程
                logger.debug(f"Gateway stream callback error: {e}")
```

---

## 5. 流式响应完整实现

### 5.1 Telegram 流式编辑实现

**在 Telegram 适配器中添加的完整流式编辑支持**:

```python
"""
Telegram 流式响应支持

添加到: python/channels/telegram_adapter.py
"""

import time
import asyncio
from typing import Optional, AsyncGenerator
from telegram import Message
from telegram.error import BadRequest, RetryAfter

from .streaming import StreamingConfig, StreamingStrategy


class TelegramAdapter(ChannelAdapter):
    # ... 现有代码 ...

    async def send_streaming(
        self,
        chat_id: str,
        stream: AsyncGenerator[str, None],
        reply_to_id: Optional[str] = None
    ) -> Message:
        """
        发送流式响应消息

        Args:
            chat_id: 聊天 ID
            stream: 响应流生成器
            reply_to_id: 回复的消息 ID

        Returns:
            最终发送的消息对象
        """
        if not self.app:
            raise RuntimeError("Telegram adapter not started")

        # 发送初始消息
        sent_msg = await self.app.bot.send_message(
            chat_id=int(chat_id),
            text="▌",  # 光标指示符
            reply_to_message_id=int(reply_to_id) if reply_to_id else None
        )

        full_response = ""
        last_update_time = time.time()
        edit_count = 0
        max_edits = 30  # Telegram 编辑限制
        min_edit_interval = 1.5  # 秒

        try:
            async for chunk in stream:
                full_response += chunk
                now = time.time()

                # 控制编辑频率
                should_update = (
                    now - last_update_time >= min_edit_interval and
                    edit_count < max_edits
                )

                if should_update:
                    await self._safe_edit_message(
                        chat_id=int(chat_id),
                        message_id=sent_msg.message_id,
                        text=full_response + "▌"
                    )
                    last_update_time = now
                    edit_count += 1

            # 最终更新（移除光标）
            if full_response:
                await self._safe_edit_message(
                    chat_id=int(chat_id),
                    message_id=sent_msg.message_id,
                    text=full_response
                )
            else:
                # 如果没有响应内容，删除占位消息
                await self.app.bot.delete_message(
                    chat_id=int(chat_id),
                    message_id=sent_msg.message_id
                )
                sent_msg = await self.app.bot.send_message(
                    chat_id=int(chat_id),
                    text="(无响应内容)"
                )

        except Exception as e:
            logger.error(f"Streaming error: {e}")
            # 尝试发送错误状态
            try:
                error_text = full_response or "处理消息时出错"
                await self._safe_edit_message(
                    chat_id=int(chat_id),
                    message_id=sent_msg.message_id,
                    text=f"⚠️ {error_text}"
                )
            except Exception:
                pass

        return sent_msg

    async def _safe_edit_message(
        self,
        chat_id: int,
        message_id: int,
        text: str
    ) -> bool:
        """
        安全地编辑消息（处理各种错误情况）

        Returns:
            是否编辑成功
        """
        try:
            # 截断过长的文本
            if len(text) > 4000:
                text = text[:3990] + "...(截断)"

            await self.app.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                parse_mode=None  # 流式更新时禁用解析，避免格式错误
            )
            return True

        except BadRequest as e:
            error_msg = str(e).lower()
            if "message is not modified" in error_msg:
                # 内容未变化，忽略
                return True
            elif "message to edit not found" in error_msg:
                logger.warning("Message was deleted, cannot edit")
                return False
            else:
                logger.error(f"Edit message error: {e}")
                return False

        except RetryAfter as e:
            # 速率限制
            logger.warning(f"Rate limited, waiting {e.retry_after}s")
            await asyncio.sleep(e.retry_after)
            return await self._safe_edit_message(chat_id, message_id, text)

        except Exception as e:
            logger.error(f"Unexpected edit error: {e}")
            return False

    async def _on_message_with_streaming(
        self,
        update,
        context
    ):
        """处理消息并使用流式响应"""
        if not self._should_respond(update):
            return

        msg = self._convert(update)

        # 获取流式响应
        stream = self.agent_bridge.process_message_stream(
            channel=msg.channel,
            channel_user_id=msg.channel_user_id,
            channel_chat_id=msg.channel_chat_id,
            content=msg.content,
            user_name=msg.user_name,
            attachments=[],  # TODO: 处理附件
        )

        # 发送流式响应
        await self.send_streaming(
            chat_id=msg.channel_chat_id,
            stream=stream,
            reply_to_id=msg.message_id
        )
```

### 5.2 Discord 流式编辑实现

**在 Discord 适配器中添加的完整流式编辑支持**:

```python
"""
Discord 流式响应支持

添加到: python/channels/discord_adapter.py
"""

import time
import asyncio
from typing import Optional, AsyncGenerator
import discord


class DiscordAdapter(ChannelAdapter):
    # ... 现有代码 ...

    async def send_streaming(
        self,
        channel: discord.TextChannel,
        stream: AsyncGenerator[str, None],
        reply_to: Optional[discord.Message] = None
    ) -> discord.Message:
        """
        发送流式响应消息

        Args:
            channel: Discord 频道
            stream: 响应流生成器
            reply_to: 回复的消息

        Returns:
            最终发送的消息对象
        """
        # 发送初始消息
        sent_msg = await channel.send(
            "▌",
            reference=reply_to if reply_to else None
        )

        full_response = ""
        last_update_time = time.time()
        edit_count = 0
        max_edits = 50
        min_edit_interval = 1.0  # 秒

        try:
            async for chunk in stream:
                full_response += chunk
                now = time.time()

                # 控制编辑频率
                should_update = (
                    now - last_update_time >= min_edit_interval and
                    edit_count < max_edits
                )

                if should_update:
                    display_text = self._truncate_for_discord(full_response + "▌")
                    await self._safe_edit_message(sent_msg, display_text)
                    last_update_time = now
                    edit_count += 1

            # 最终更新
            if full_response:
                # 分割长消息
                await self._finalize_streaming_message(
                    channel, sent_msg, full_response
                )
            else:
                await sent_msg.edit(content="(无响应内容)")

        except Exception as e:
            logger.error(f"Discord streaming error: {e}")
            try:
                await sent_msg.edit(content=f"⚠️ 处理消息时出错")
            except Exception:
                pass

        return sent_msg

    async def _safe_edit_message(
        self,
        message: discord.Message,
        text: str
    ) -> bool:
        """安全地编辑消息"""
        try:
            await message.edit(content=text)
            return True
        except discord.HTTPException as e:
            if e.status == 429:  # Rate limited
                retry_after = e.retry_after if hasattr(e, 'retry_after') else 1
                await asyncio.sleep(retry_after)
                return await self._safe_edit_message(message, text)
            else:
                logger.error(f"Discord edit error: {e}")
                return False
        except Exception as e:
            logger.error(f"Unexpected Discord edit error: {e}")
            return False

    def _truncate_for_discord(self, text: str, max_length: int = 1900) -> str:
        """截断文本以适应 Discord 限制"""
        if len(text) <= max_length:
            return text
        return text[:max_length - 10] + "...(继续)"

    async def _finalize_streaming_message(
        self,
        channel: discord.TextChannel,
        original_msg: discord.Message,
        full_response: str
    ):
        """
        完成流式消息发送

        如果响应超过 Discord 限制，将分割成多条消息
        """
        max_length = 1900

        if len(full_response) <= max_length:
            await original_msg.edit(content=full_response)
        else:
            # 编辑原消息为第一部分
            await original_msg.edit(content=full_response[:max_length])

            # 发送剩余部分
            remaining = full_response[max_length:]
            while remaining:
                chunk = remaining[:max_length]
                remaining = remaining[max_length:]
                await channel.send(chunk)
```

---

## 6. 文件结构补充

### 6.1 完整的文件结构

基于 V4 文档，补充遗漏的文件：

```
python/
├── gateway/                        # 网关核心
│   ├── __init__.py
│   ├── server.py                   # Gateway 服务器 (FastAPI)
│   ├── config.py                   # 配置管理 + 热重载
│   ├── health.py                   # 健康检查
│   ├── protocol.py                 # 通信协议定义
│   ├── agent_bridge.py             # Agent 桥接层 (线程安全版)
│   ├── metrics.py                  # 监控指标
│   ├── errors.py                   # 🆕 错误处理模块
│   ├── deduplicator.py             # 🆕 消息去重器
│   ├── session_cleaner.py          # 🆕 会话清理器
│   └── attachment_handler.py       # 🆕 附件处理器
│
├── channels/                       # 渠道模块
│   ├── __init__.py
│   ├── base.py                     # 适配器基类 + 消息模型
│   ├── manager.py                  # 渠道管理器 (增强版)
│   ├── security.py                 # 安全模块
│   ├── capability_adapter.py       # 能力适配器
│   ├── streaming.py                # 流式响应策略
│   ├── telegram_adapter.py         # Telegram 适配器 (流式增强)
│   └── discord_adapter.py          # Discord 适配器 (生命周期修正)
│
├── extensions/
│   └── response_stream_chunk/
│       ├── _10_mask_stream.py      # 现有: 敏感信息过滤
│       └── _20_gateway_callback.py # 🆕 Gateway 流式回调
│
└── agent.py                        # Agent Zero 核心 (不修改)

conf/
├── gateway.yaml                    # 网关配置
└── channels.yaml                   # 渠道配置 (可选拆分)

run_gateway.py                      # 网关启动入口
run_all.py                          # 统一启动入口
```

### 6.2 需要添加的依赖

```txt
# requirements-gateway.txt 补充

# 附件下载
aiohttp>=3.8.0,<4.0.0
```

---

## 7. 实施优先级建议

### 7.1 Phase 1: 核心修正 (必须)

| 任务 | 优先级 | 工作量 | 说明 |
|------|--------|--------|------|
| AgentBridge 线程锁 | 🔴 最高 | 0.5h | 修改 `agent_bridge.py` |
| Discord 生命周期修正 | 🔴 最高 | 1h | 修改 `discord_adapter.py` |
| 创建 Gateway Extension | 🔴 高 | 0.5h | 创建 `_20_gateway_callback.py` |
| 流式响应竞态修正 | 🟡 中 | 0.5h | 修改 `process_message_stream` |

### 7.2 Phase 2: 功能增强 (建议)

| 任务 | 优先级 | 工作量 | 说明 |
|------|--------|--------|------|
| 附件处理器 | 🟡 中 | 1h | 创建 `attachment_handler.py` |
| 错误处理模块 | 🟡 中 | 0.5h | 创建 `errors.py` |
| Telegram 流式编辑 | 🟡 中 | 1.5h | 增强 `telegram_adapter.py` |
| Discord 流式编辑 | 🟡 中 | 1.5h | 增强 `discord_adapter.py` |

### 7.3 Phase 3: 可选增强 (推荐)

| 任务 | 优先级 | 工作量 | 说明 |
|------|--------|--------|------|
| 消息去重器 | 🟢 低 | 0.5h | 创建 `deduplicator.py` |
| 会话清理器 | 🟢 低 | 0.5h | 创建 `session_cleaner.py` |
| 配置变更检测增强 | 🟢 低 | 0.5h | 增强 `manager.py` |

### 7.4 总工作量估算

| 阶段 | 工作量 | 累计 |
|------|--------|------|
| Phase 1 | 2.5h | 2.5h |
| Phase 2 | 4.5h | 7h |
| Phase 3 | 1.5h | 8.5h |

---

## 附录 A: 修改检查清单

### A.1 高风险修正检查

- [ ] `agent_bridge.py`: 添加 `self._lock = threading.Lock()`
- [ ] `agent_bridge.py`: `get_or_create_context()` 使用 `with self._lock:`
- [ ] `agent_bridge.py`: `get_session()` 使用 `with self._lock:`
- [ ] `agent_bridge.py`: `list_sessions()` 使用 `with self._lock:`
- [ ] `agent_bridge.py`: `remove_session()` 使用 `with self._lock:`
- [ ] `agent_bridge.py`: `process_message_stream()` 使用 sentinel 结束标记
- [ ] `discord_adapter.py`: 添加 `_shutdown_event = threading.Event()`
- [ ] `discord_adapter.py`: `stop()` 方法等待线程结束

### A.2 功能补充检查

- [ ] 创建 `python/extensions/response_stream_chunk/_20_gateway_callback.py`
- [ ] 创建 `python/gateway/attachment_handler.py`
- [ ] 创建 `python/gateway/errors.py`
- [ ] 创建 `python/gateway/deduplicator.py`
- [ ] 创建 `python/gateway/session_cleaner.py`

### A.3 流式响应检查

- [ ] `telegram_adapter.py`: 添加 `send_streaming()` 方法
- [ ] `telegram_adapter.py`: 添加 `_safe_edit_message()` 方法
- [ ] `discord_adapter.py`: 添加 `send_streaming()` 方法
- [ ] `discord_adapter.py`: 添加 `_safe_edit_message()` 方法

---

> **文档维护者**: 浮浮酱 (AI Assistant)
> **最后更新**: 2026-02-01

---

## 附录 B: 单元测试用例

### B.1 测试文件结构

```
tests/
├── gateway/
│   ├── __init__.py
│   ├── test_agent_bridge.py       # AgentBridge 线程安全测试
│   ├── test_deduplicator.py       # 消息去重器测试
│   ├── test_session_cleaner.py    # 会话清理器测试
│   ├── test_attachment_handler.py # 附件处理器测试
│   └── test_errors.py             # 错误处理模块测试
│
├── channels/
│   ├── __init__.py
│   ├── test_telegram_adapter.py   # Telegram 适配器测试
│   ├── test_discord_adapter.py    # Discord 适配器测试
│   ├── test_manager.py            # 渠道管理器测试
│   └── test_streaming.py          # 流式响应测试
│
└── conftest.py                    # pytest 公共 fixtures
```

### B.2 AgentBridge 线程安全测试

```python
"""
AgentBridge 线程安全测试

文件: tests/gateway/test_agent_bridge.py
"""

import pytest
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

# 假设导入路径
# from python.gateway.agent_bridge import AgentBridge, ChannelSession


class TestAgentBridgeThreadSafety:
    """AgentBridge 线程安全测试"""

    @pytest.fixture
    def mock_config(self):
        """模拟 AgentConfig"""
        return MagicMock()

    @pytest.fixture
    def bridge(self, mock_config):
        """创建 AgentBridge 实例"""
        with patch('python.gateway.agent_bridge.initialize_agent', return_value=mock_config):
            from python.gateway.agent_bridge import AgentBridge
            return AgentBridge(mock_config)

    def test_concurrent_get_or_create_context(self, bridge):
        """测试并发创建 context 不会产生重复"""
        results = []
        errors = []

        def create_context(user_id: str):
            try:
                with patch('python.gateway.agent_bridge.AgentContext') as mock_ctx:
                    mock_ctx.get.return_value = None
                    ctx = bridge.get_or_create_context(
                        channel="telegram",
                        channel_user_id=user_id,
                        channel_chat_id="chat_123",
                        user_name="test_user"
                    )
                    results.append(ctx)
            except Exception as e:
                errors.append(e)

        # 使用相同的 user_id 并发创建
        threads = [
            threading.Thread(target=create_context, args=("user_123",))
            for _ in range(10)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 验证没有错误
        assert len(errors) == 0, f"Errors occurred: {errors}"

        # 验证 _sessions 中只有一个条目
        assert len(bridge._sessions) == 1

    def test_concurrent_list_and_remove_sessions(self, bridge):
        """测试并发列出和删除会话的线程安全性"""
        # 预先创建一些会话
        for i in range(5):
            bridge._sessions[f"tg:user_{i}"] = MagicMock()

        errors = []

        def list_sessions():
            try:
                for _ in range(100):
                    _ = bridge.list_sessions()
            except Exception as e:
                errors.append(e)

        def remove_sessions():
            try:
                for i in range(5):
                    bridge.remove_session("telegram", f"user_{i}")
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=list_sessions)
        t2 = threading.Thread(target=remove_sessions)

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert len(errors) == 0, f"Thread safety errors: {errors}"


class TestProcessMessageStream:
    """流式消息处理测试"""

    @pytest.fixture
    def bridge(self):
        with patch('python.gateway.agent_bridge.initialize_agent'):
            from python.gateway.agent_bridge import AgentBridge
            return AgentBridge()

    @pytest.mark.asyncio
    async def test_stream_ends_with_sentinel(self, bridge):
        """测试流式响应正确使用 sentinel 结束"""
        chunks_received = []

        # 模拟 process_message 返回一些内容
        async def mock_process(*args, **kwargs):
            callback = kwargs.get('stream_callback')
            if callback:
                await callback("Hello ", "Hello ")
                await callback("World", "Hello World")
            return "Hello World"

        with patch.object(bridge, 'process_message', mock_process):
            async for chunk in bridge.process_message_stream(
                channel="telegram",
                channel_user_id="user_123",
                channel_chat_id="chat_123",
                content="test"
            ):
                chunks_received.append(chunk)

        assert chunks_received == ["Hello ", "World"]

    @pytest.mark.asyncio
    async def test_stream_handles_empty_response(self, bridge):
        """测试空响应的处理"""
        async def mock_process(*args, **kwargs):
            return ""

        with patch.object(bridge, 'process_message', mock_process):
            chunks = [chunk async for chunk in bridge.process_message_stream(
                channel="telegram",
                channel_user_id="user_123",
                channel_chat_id="chat_123",
                content="test"
            )]

        assert chunks == []
```

### B.3 Discord 适配器生命周期测试

```python
"""
Discord 适配器生命周期测试

文件: tests/channels/test_discord_adapter.py
"""

import pytest
import asyncio
import threading
from unittest.mock import MagicMock, patch, AsyncMock


class TestDiscordAdapterLifecycle:
    """Discord 适配器生命周期测试"""

    @pytest.fixture
    def adapter_config(self):
        return {
            "token": "test_token",
            "respond_to_dms": True,
            "require_mention": True,
            "allowed_guilds": []
        }

    @pytest.fixture
    def adapter(self, adapter_config):
        with patch('discord.ext.commands.Bot'):
            from python.channels.discord_adapter import DiscordAdapter
            return DiscordAdapter(adapter_config, "test")

    @pytest.mark.asyncio
    async def test_start_creates_thread(self, adapter):
        """测试 start() 创建独立线程"""
        with patch.object(adapter, '_run_in_thread'):
            await adapter.start()

        assert adapter._thread is not None
        assert adapter._running is True
        assert adapter._main_loop is not None
        assert adapter._discord_loop is not None

    @pytest.mark.asyncio
    async def test_stop_waits_for_thread(self, adapter):
        """测试 stop() 等待线程结束"""
        # 模拟已启动状态
        adapter._running = True
        adapter._discord_loop = MagicMock()
        adapter._discord_loop.is_running.return_value = True
        adapter._thread = MagicMock()
        adapter._thread.is_alive.return_value = False
        adapter._shutdown_event = threading.Event()
        adapter._shutdown_event.set()  # 模拟线程已结束

        with patch('asyncio.run_coroutine_threadsafe') as mock_run:
            mock_future = MagicMock()
            mock_future.result.return_value = None
            mock_run.return_value = mock_future

            await adapter.stop()

        assert adapter._running is False

    @pytest.mark.asyncio
    async def test_stop_handles_timeout(self, adapter):
        """测试 stop() 处理超时情况"""
        adapter._running = True
        adapter._discord_loop = MagicMock()
        adapter._discord_loop.is_running.return_value = True
        adapter._thread = MagicMock()
        adapter._thread.is_alive.return_value = True  # 线程未结束
        adapter._shutdown_event = threading.Event()
        # 不设置 event，模拟超时

        with patch('asyncio.run_coroutine_threadsafe') as mock_run:
            mock_future = MagicMock()
            mock_future.result.side_effect = TimeoutError()
            mock_run.return_value = mock_future

            # 应该不会抛出异常
            await adapter.stop()

        assert adapter._running is False
```

### B.4 消息去重器测试

```python
"""
消息去重器测试

文件: tests/gateway/test_deduplicator.py
"""

import pytest
import time
import threading
from datetime import datetime, timedelta


class TestMessageDeduplicator:
    """消息去重器测试"""

    @pytest.fixture
    def deduplicator(self):
        from python.gateway.deduplicator import MessageDeduplicator
        return MessageDeduplicator(ttl_seconds=2, max_size=100)

    def test_first_message_not_duplicate(self, deduplicator):
        """首次消息不是重复"""
        assert deduplicator.is_duplicate("msg_1", "telegram") is False

    def test_same_message_is_duplicate(self, deduplicator):
        """相同消息是重复"""
        deduplicator.is_duplicate("msg_1", "telegram")
        assert deduplicator.is_duplicate("msg_1", "telegram") is True

    def test_different_channel_not_duplicate(self, deduplicator):
        """不同渠道的相同 ID 不是重复"""
        deduplicator.is_duplicate("msg_1", "telegram")
        assert deduplicator.is_duplicate("msg_1", "discord") is False

    def test_expired_message_not_duplicate(self, deduplicator):
        """过期消息不是重复"""
        deduplicator.is_duplicate("msg_1", "telegram")
        time.sleep(2.5)  # 等待超过 TTL
        assert deduplicator.is_duplicate("msg_1", "telegram") is False

    def test_max_size_limit(self, deduplicator):
        """测试最大容量限制"""
        # 添加超过 max_size 的消息
        for i in range(150):
            deduplicator.is_duplicate(f"msg_{i}", "telegram")

        assert deduplicator.size <= 100

    def test_thread_safety(self, deduplicator):
        """测试线程安全性"""
        errors = []

        def check_duplicates(thread_id: int):
            try:
                for i in range(100):
                    deduplicator.is_duplicate(f"msg_{thread_id}_{i}", "telegram")
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=check_duplicates, args=(i,))
            for i in range(10)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
```

### B.5 pytest conftest.py

```python
"""
pytest 公共配置

文件: tests/conftest.py
"""

import pytest
import asyncio
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


@pytest.fixture(scope="session")
def event_loop():
    """创建事件循环 fixture"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_agent_context():
    """模拟 AgentContext"""
    from unittest.mock import MagicMock
    ctx = MagicMock()
    ctx.get.return_value = None
    ctx.set_data = MagicMock()
    ctx.get_data = MagicMock(return_value=None)
    ctx.communicate = MagicMock()
    return ctx


@pytest.fixture
def mock_agent_config():
    """模拟 AgentConfig"""
    from unittest.mock import MagicMock
    config = MagicMock()
    return config
```

---

## 附录 C: 监控告警阈值

### C.1 MetricsCollector 告警增强

```python
"""
监控指标收集器 (告警增强版)

文件: python/gateway/metrics.py (增强部分)
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, Optional, List, Callable
import time
import logging

logger = logging.getLogger("gateway.metrics")


@dataclass
class AlertThresholds:
    """告警阈值配置"""
    error_rate: float = 0.1  # 错误率超过 10% 告警
    avg_response_time_ms: float = 30000  # 平均响应超过 30s 告警
    reconnect_count: int = 5  # 重连次数超过 5 次告警
    messages_per_minute: int = 100  # 每分钟消息数超过 100 告警
    queue_depth: int = 50  # 队列深度超过 50 告警


@dataclass
class Alert:
    """告警信息"""
    level: str  # warning, critical
    channel: str
    metric: str
    value: float
    threshold: float
    message: str
    timestamp: datetime = field(default_factory=datetime.now)


class MetricsCollectorWithAlerts:
    """带告警功能的指标收集器"""

    def __init__(
        self,
        thresholds: AlertThresholds = None,
        alert_callback: Callable[[Alert], None] = None
    ):
        """
        初始化指标收集器

        Args:
            thresholds: 告警阈值配置
            alert_callback: 告警回调函数，用于发送通知
        """
        self._metrics: Dict[str, ChannelMetrics] = {}
        self._start_time = datetime.now()
        self.thresholds = thresholds or AlertThresholds()
        self.alert_callback = alert_callback
        self._alerts_history: List[Alert] = []
        self._last_alert_time: Dict[str, float] = {}  # 防止告警风暴
        self._alert_cooldown_seconds = 300  # 5 分钟冷却

    def _check_thresholds(self, channel: str):
        """检查指标是否超过阈值"""
        metrics = self._metrics.get(channel)
        if not metrics:
            return

        alerts = []

        # 检查错误率
        if metrics.messages_sent > 0:
            error_rate = metrics.errors / metrics.messages_sent
            if error_rate > self.thresholds.error_rate:
                alerts.append(Alert(
                    level="critical" if error_rate > 0.5 else "warning",
                    channel=channel,
                    metric="error_rate",
                    value=error_rate,
                    threshold=self.thresholds.error_rate,
                    message=f"Error rate {error_rate:.1%} exceeds threshold {self.thresholds.error_rate:.1%}"
                ))

        # 检查平均响应时间
        avg_response = metrics.average_response_time_ms
        if avg_response > self.thresholds.avg_response_time_ms:
            alerts.append(Alert(
                level="warning",
                channel=channel,
                metric="avg_response_time_ms",
                value=avg_response,
                threshold=self.thresholds.avg_response_time_ms,
                message=f"Avg response time {avg_response:.0f}ms exceeds threshold {self.thresholds.avg_response_time_ms:.0f}ms"
            ))

        # 检查重连次数
        if metrics.reconnect_count > self.thresholds.reconnect_count:
            alerts.append(Alert(
                level="warning",
                channel=channel,
                metric="reconnect_count",
                value=metrics.reconnect_count,
                threshold=self.thresholds.reconnect_count,
                message=f"Reconnect count {metrics.reconnect_count} exceeds threshold {self.thresholds.reconnect_count}"
            ))

        # 发送告警
        for alert in alerts:
            self._send_alert(alert)

    def _send_alert(self, alert: Alert):
        """发送告警（带冷却）"""
        alert_key = f"{alert.channel}:{alert.metric}"
        now = time.time()

        # 检查冷却
        last_time = self._last_alert_time.get(alert_key, 0)
        if now - last_time < self._alert_cooldown_seconds:
            return  # 在冷却期内，不发送

        self._last_alert_time[alert_key] = now
        self._alerts_history.append(alert)

        # 记录日志
        log_func = logger.critical if alert.level == "critical" else logger.warning
        log_func(f"[ALERT] {alert.message}")

        # 调用回调
        if self.alert_callback:
            try:
                self.alert_callback(alert)
            except Exception as e:
                logger.error(f"Alert callback error: {e}")

    def record_message_sent(self, channel: str, response_time_ms: float):
        """记录发送消息并检查阈值"""
        self._ensure_channel(channel)
        self._metrics[channel].messages_sent += 1
        self._metrics[channel].total_response_time_ms += response_time_ms
        self._metrics[channel].last_activity = datetime.now()

        # 检查阈值
        self._check_thresholds(channel)

    def record_error(self, channel: str, error: str):
        """记录错误并检查阈值"""
        self._ensure_channel(channel)
        self._metrics[channel].errors += 1
        self._metrics[channel].last_error = error

        # 检查阈值
        self._check_thresholds(channel)

    def get_alerts_history(self, limit: int = 100) -> List[dict]:
        """获取告警历史"""
        return [
            {
                "level": a.level,
                "channel": a.channel,
                "metric": a.metric,
                "value": a.value,
                "threshold": a.threshold,
                "message": a.message,
                "timestamp": a.timestamp.isoformat(),
            }
            for a in self._alerts_history[-limit:]
        ]

    def clear_alerts_history(self):
        """清空告警历史"""
        self._alerts_history.clear()
```

### C.2 配置文件中的告警阈值

```yaml
# conf/gateway.yaml (告警配置部分)

gateway:
  # ... 现有配置 ...

  # 🆕 监控告警配置
  alerts:
    enabled: true
    thresholds:
      error_rate: 0.1           # 错误率超过 10% 告警
      avg_response_time_ms: 30000  # 平均响应超过 30s 告警
      reconnect_count: 5        # 重连次数超过 5 次告警
      messages_per_minute: 100  # 每分钟消息数超过 100 告警

    # 告警通知方式
    notifications:
      # 日志告警（默认启用）
      log: true

      # Webhook 告警（可选）
      webhook:
        enabled: false
        url: "https://your-webhook-url.com/alerts"
        headers:
          Authorization: "Bearer ${ALERT_WEBHOOK_TOKEN}"

      # 邮件告警（可选）
      email:
        enabled: false
        smtp_host: "smtp.example.com"
        smtp_port: 587
        from_addr: "alerts@example.com"
        to_addrs:
          - "admin@example.com"
```

---

## 附录 D: Docker 部署配置

### D.1 Docker Compose 配置

```yaml
# docker-compose.gateway.yml

version: "3.8"

services:
  agent-zero:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: agent-zero-gateway
    ports:
      - "50001:50001"   # Web UI
      - "18900:18900"   # Gateway API
    environment:
      # Gateway 配置
      - GATEWAY_PORT=18900
      - GATEWAY_HOST=0.0.0.0
      - GATEWAY_AUTH_TOKEN=${GATEWAY_AUTH_TOKEN}

      # 渠道 Token
      - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
      - DISCORD_BOT_TOKEN=${DISCORD_BOT_TOKEN}

      # Agent Zero 配置
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}

    volumes:
      # 配置文件
      - ./conf:/app/conf:ro

      # 持久化数据
      - ./data:/app/data
      - ./memory:/app/memory
      - ./knowledge:/app/knowledge

      # 临时文件（附件上传）
      - ./tmp/uploads:/app/tmp/uploads

      # 日志
      - ./logs:/app/logs

    restart: unless-stopped

    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:18900/api/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s

    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"

    networks:
      - agent-zero-network

networks:
  agent-zero-network:
    driver: bridge
```

### D.2 Dockerfile 补充

```dockerfile
# Dockerfile (Gateway 相关补充)

# ... 现有内容 ...

# 安装 Gateway 依赖
COPY requirements-gateway.txt .
RUN pip install --no-cache-dir -r requirements-gateway.txt

# 暴露端口
EXPOSE 50001 18900

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:18900/api/health || exit 1

# 启动命令（使用统一入口）
CMD ["python", "run_all.py", "--ui-host", "0.0.0.0", "--gateway-host", "0.0.0.0"]
```

### D.3 环境变量模板

```bash
# .env.example (Gateway 相关)

# ========================================
# Gateway 配置
# ========================================

# Gateway 服务端口
GATEWAY_PORT=18900

# Gateway 认证 Token（远程访问时必须设置）
GATEWAY_AUTH_TOKEN=your_secure_random_token_here

# ========================================
# 渠道配置
# ========================================

# Telegram Bot Token
# 从 @BotFather 获取
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz

# Discord Bot Token
# 从 Discord Developer Portal 获取
DISCORD_BOT_TOKEN=your_discord_bot_token_here

# ========================================
# 告警配置（可选）
# ========================================

# Webhook 告警 Token
ALERT_WEBHOOK_TOKEN=your_webhook_token

# ========================================
# LLM API Keys
# ========================================

OPENAI_API_KEY=sk-xxx
ANTHROPIC_API_KEY=sk-ant-xxx
```

### D.4 快速启动脚本

```bash
#!/bin/bash
# scripts/start-gateway.sh

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Agent Zero Gateway 启动脚本${NC}"
echo -e "${GREEN}========================================${NC}"

# 检查 .env 文件
if [ ! -f .env ]; then
    echo -e "${YELLOW}警告: .env 文件不存在${NC}"
    echo -e "${YELLOW}正在从 .env.example 创建...${NC}"
    cp .env.example .env
    echo -e "${RED}请编辑 .env 文件填入必要的配置后重新运行${NC}"
    exit 1
fi

# 检查必要的环境变量
source .env

if [ -z "$GATEWAY_AUTH_TOKEN" ]; then
    echo -e "${RED}错误: GATEWAY_AUTH_TOKEN 未设置${NC}"
    exit 1
fi

# 创建必要的目录
mkdir -p tmp/uploads logs data memory knowledge conf

# 检查配置文件
if [ ! -f conf/gateway.yaml ]; then
    echo -e "${YELLOW}创建默认 gateway.yaml 配置...${NC}"
    cat > conf/gateway.yaml << 'EOF'
gateway:
  host: "0.0.0.0"
  port: 18900
  hot_reload: true
  auth:
    token: "${GATEWAY_AUTH_TOKEN}"

channels:
  telegram:
    enabled: true
    token: "${TELEGRAM_BOT_TOKEN}"
    require_mention_in_groups: true
    whitelist: []

  discord:
    enabled: true
    token: "${DISCORD_BOT_TOKEN}"
    respond_to_dms: true
    require_mention: true
    allowed_guilds: []
EOF
fi

# 启动方式选择
if [ "$1" == "docker" ]; then
    echo -e "${GREEN}使用 Docker Compose 启动...${NC}"
    docker-compose -f docker-compose.gateway.yml up -d
    echo -e "${GREEN}查看日志: docker-compose -f docker-compose.gateway.yml logs -f${NC}"
else
    echo -e "${GREEN}使用 Python 直接启动...${NC}"
    python run_all.py --ui-host 0.0.0.0 --gateway-host 0.0.0.0
fi

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}启动完成！${NC}"
echo -e "${GREEN}Web UI: http://localhost:50001${NC}"
echo -e "${GREEN}Gateway: http://localhost:18900${NC}"
echo -e "${GREEN}========================================${NC}"
```

---

## 附录 E: 完整依赖清单

### E.1 requirements-gateway.txt (完整版)

```txt
# Agent Zero Gateway 依赖清单
# 版本: 1.1
# 更新日期: 2026-02-01

# ========================================
# 核心框架
# ========================================

# FastAPI 及相关
fastapi>=0.100.0,<1.0.0
uvicorn[standard]>=0.23.0,<1.0.0
websockets>=11.0,<13.0

# HTTP 客户端
httpx>=0.24.0,<1.0.0
aiohttp>=3.8.0,<4.0.0

# ========================================
# 配置管理
# ========================================

pyyaml>=6.0,<7.0
python-dotenv>=1.0,<2.0
watchdog>=3.0,<5.0

# ========================================
# 渠道适配器
# ========================================

# Telegram
python-telegram-bot>=20.0,<21.0

# Discord
discord.py>=2.0,<3.0

# ========================================
# 工具库
# ========================================

# 文件名安全处理
werkzeug>=2.3.0,<4.0.0

# ========================================
# 可选依赖（分布式部署时使用）
# ========================================

# Redis (如果需要跨进程共享)
# redis>=4.5.0,<6.0

# ========================================
# 开发依赖
# ========================================

# 测试
pytest>=7.0.0,<9.0.0
pytest-asyncio>=0.21.0,<1.0.0
pytest-cov>=4.0.0,<6.0.0

# 类型检查
mypy>=1.0.0,<2.0.0

# 代码格式化
black>=23.0.0,<25.0.0
isort>=5.12.0,<6.0.0
```

### E.2 依赖安装命令

```bash
# 安装 Gateway 依赖
pip install -r requirements-gateway.txt

# 仅安装生产依赖（不含开发工具）
pip install -r requirements-gateway.txt --ignore-installed pytest pytest-asyncio pytest-cov mypy black isort

# 使用 conda 环境
conda create -n agent-zero-gateway python=3.11
conda activate agent-zero-gateway
pip install -r requirements-gateway.txt
```

---

## 附录 F: 更新后的修改检查清单

### F.1 完整实施检查清单

#### 阶段 1: 核心修正 (必须)

- [ ] **AgentBridge 线程安全**
  - [ ] 添加 `self._lock = threading.Lock()`
  - [ ] `get_or_create_context()` 使用 `with self._lock:`
  - [ ] `get_session()` 使用 `with self._lock:`
  - [ ] `list_sessions()` 使用 `with self._lock:`
  - [ ] `remove_session()` 使用 `with self._lock:`
  - [ ] `process_message_stream()` 使用 sentinel 结束标记

- [ ] **Discord 生命周期修正**
  - [ ] 添加 `_shutdown_event = threading.Event()`
  - [ ] `stop()` 方法等待线程结束
  - [ ] 添加 `_cleanup()` 方法

- [ ] **Gateway Extension**
  - [ ] 创建 `python/extensions/response_stream_chunk/_20_gateway_callback.py`

#### 阶段 2: 功能增强 (建议)

- [ ] **附件处理**
  - [ ] 创建 `python/gateway/attachment_handler.py`
  - [ ] 实现 TTL 自动清理

- [ ] **错误处理**
  - [ ] 创建 `python/gateway/errors.py`
  - [ ] 实现多语言支持

- [ ] **流式编辑**
  - [ ] Telegram: 添加 `send_streaming()` 方法
  - [ ] Telegram: 添加 `_safe_edit_message()` 方法
  - [ ] Discord: 添加 `send_streaming()` 方法
  - [ ] Discord: 添加 `_safe_edit_message()` 方法

#### 阶段 3: 可选增强 (推荐)

- [ ] **消息去重**
  - [ ] 创建 `python/gateway/deduplicator.py`

- [ ] **会话清理**
  - [ ] 创建 `python/gateway/session_cleaner.py`

- [ ] **配置变更检测**
  - [ ] 增强 `ChannelManager.apply_config_change()`

#### 阶段 4: 测试与部署

- [ ] **单元测试**
  - [ ] 创建 `tests/gateway/test_agent_bridge.py`
  - [ ] 创建 `tests/channels/test_discord_adapter.py`
  - [ ] 创建 `tests/gateway/test_deduplicator.py`
  - [ ] 创建 `tests/conftest.py`
  - [ ] 运行测试并确保通过

- [ ] **监控告警**
  - [ ] 增强 `MetricsCollector` 添加告警功能
  - [ ] 配置告警阈值

- [ ] **Docker 部署**
  - [ ] 创建 `docker-compose.gateway.yml`
  - [ ] 创建 `.env.example`
  - [ ] 创建启动脚本

- [ ] **稳定性测试**
  - [ ] 24 小时运行测试
  - [ ] 压力测试
  - [ ] 断线重连测试
