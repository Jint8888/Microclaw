"""
Discord Bot Adapter (V4.1 Thread-Safe with Lifecycle Management)

Fixes:
- ✅ Use run_coroutine_threadsafe for safe cross-thread calls
- ✅ Use run_in_executor to avoid blocking Discord event loop
- ✅ Properly manage event loops for each thread
- ✅ Graceful shutdown with proper cleanup

Dependency: pip install discord.py>=2.0

File: python/channels/discord_adapter.py
"""

import asyncio
import logging
import threading
import time
from typing import Optional, AsyncGenerator, TYPE_CHECKING

from .base import (
    ChannelAdapter, ChannelCapabilities,
    InboundMessage, OutboundMessage, Attachment, MessageType
)

if TYPE_CHECKING:
    from python.gateway.attachment_handler import AttachmentHandler

logger = logging.getLogger("channels.discord")


class DiscordAdapter(ChannelAdapter):
    """Discord Bot Adapter (Thread-Safe with Lifecycle Management)"""

    def __init__(self, config: dict, account_id: str = "default"):
        super().__init__(config, account_id)
        self.token = config["token"]
        self.respond_to_dms = config.get("respond_to_dms", True)
        self.require_mention = config.get("require_mention", True)
        self.allowed_guilds = config.get("allowed_guilds", [])
        self.allowed_users = config.get("whitelist", [])
        self.blocked_users = config.get("blacklist", [])

        self.bot = None
        self._attachment_handler: Optional["AttachmentHandler"] = None

        # Thread communication
        self._main_loop: Optional[asyncio.AbstractEventLoop] = None
        self._discord_loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._shutdown_event = threading.Event()  # Shutdown event

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

    @property
    def attachment_handler(self) -> "AttachmentHandler":
        """Lazy load attachment handler"""
        if self._attachment_handler is None:
            from python.gateway.attachment_handler import AttachmentHandler
            self._attachment_handler = AttachmentHandler()
        return self._attachment_handler

    def _setup_bot(self):
        """Setup Discord bot with event handlers"""
        try:
            import discord
            from discord.ext import commands
        except ImportError:
            raise ImportError(
                "discord.py not installed. "
                "Install with: pip install discord.py>=2.0"
            )

        intents = discord.Intents.default()
        intents.message_content = True
        self.bot = commands.Bot(command_prefix="!", intents=intents)

        @self.bot.event
        async def on_ready():
            logger.info(f"Discord: Logged in as {self.bot.user}")
            self.reset_reconnect_counter()

        @self.bot.event
        async def on_message(message):
            if message.author == self.bot.user:
                return
            if not self._should_respond(message):
                return

            inbound = await self._convert(message)
            await self._handle_with_typing(message, inbound)

        @self.bot.event
        async def on_disconnect():
            logger.warning("Discord disconnected, will reconnect...")

        @self.bot.event
        async def on_error(event, *args, **kwargs):
            logger.error(f"Discord error in {event}")

    async def _handle_in_main_loop(self, inbound: InboundMessage) -> OutboundMessage:
        """Handle message in main event loop (thread-safe)"""
        return await self.handle(inbound)

    async def _keep_typing(self, channel, interval: float = 8.0):
        """
        Keep sending typing indicator until cancelled.
        
        Discord typing indicator lasts ~10 seconds, so we refresh every 8 seconds.
        This shows the "Bot is typing..." indicator to users.
        
        Args:
            channel: Discord channel to send typing to
            interval: Refresh interval in seconds (default 8.0)
        """
        try:
            while True:
                async with channel.typing():
                    await asyncio.sleep(interval)
        except asyncio.CancelledError:
            # Task was cancelled, this is expected
            pass
        except Exception as e:
            logger.debug(f"Typing indicator stopped: {e}")

    async def _handle_with_typing(self, message, inbound: InboundMessage):
        """
        Handle message with typing indicator and placeholder message.
        
        Provides immediate feedback to users by:
        1. Sending a placeholder message immediately
        2. Showing typing indicator while processing
        3. Updating the placeholder with the actual response
        
        Args:
            message: Discord message object
            inbound: Converted InboundMessage
        """
        channel = message.channel
        
        # 1. Send placeholder message immediately
        placeholder = await channel.send("🤔 思考中...")
        
        # 2. Start typing indicator task
        typing_task = asyncio.create_task(self._keep_typing(channel))
        
        try:
            # 3. Process message in main thread
            future = asyncio.run_coroutine_threadsafe(
                self._handle_in_main_loop(inbound),
                self._main_loop
            )
            
            # Use run_in_executor to avoid blocking Discord event loop
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: future.result(timeout=300)
            )
            
            # 4. Update placeholder with response
            if response.content:
                # Truncate if too long (Discord limit 2000 chars)
                content = response.content
                if len(content) > 1900:
                    content = content[:1900] + "...(续)"
                await placeholder.edit(content=content)
                
                # Send remaining content as new messages if needed
                if len(response.content) > 1900:
                    remaining = response.content[1900:]
                    max_len = 1900
                    while remaining:
                        chunk = remaining[:max_len]
                        remaining = remaining[max_len:]
                        await channel.send(chunk)
            else:
                await placeholder.edit(content="(无响应内容)")
            
            # 5. Send attachments
            await self._send_attachments(channel, response.attachments)
            
        except asyncio.TimeoutError:
            logger.error("Message processing timeout")
            await placeholder.edit(content="⚠️ 处理超时，请重试")
        except Exception as e:
            logger.error(f"Error handling message: {e}")
            await placeholder.edit(content="⚠️ 处理消息时出错")
        finally:
            # Stop typing indicator
            typing_task.cancel()
            try:
                await typing_task
            except asyncio.CancelledError:
                pass

    async def _send_attachments(self, channel, attachments: list):
        """
        Send attachments to Discord channel.
        
        Args:
            channel: Discord channel to send to
            attachments: List of Attachment objects
        """
        import discord
        import os
        
        for att in attachments:
            try:
                if att.local_path and os.path.exists(att.local_path):
                    await channel.send(file=discord.File(att.local_path))
                elif att.url:
                    await channel.send(att.url)
            except Exception as e:
                logger.error(f"Failed to send Discord attachment: {e}")

    async def start(self):
        """Start Discord Bot"""
        self._setup_bot()

        # Get current running event loop (main thread)
        self._main_loop = asyncio.get_running_loop()
        self._discord_loop = asyncio.new_event_loop()
        self._shutdown_event.clear()

        self._thread = threading.Thread(target=self._run_in_thread, daemon=True)
        self._thread.start()

        self._running = True
        logger.info(f"Discord adapter started: {self.account_id}")

    def _run_in_thread(self):
        """Run Discord event loop in separate thread"""
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
        """Cleanup Discord resources"""
        try:
            if self.bot and not self.bot.is_closed():
                await self.bot.close()
        except Exception as e:
            logger.error(f"Error during Discord cleanup: {e}")

    async def stop(self):
        """Stop Discord Bot (graceful shutdown)"""
        self._running = False

        if self._discord_loop and self._discord_loop.is_running():
            # Schedule close in Discord event loop
            future = asyncio.run_coroutine_threadsafe(
                self.bot.close(),
                self._discord_loop
            )
            try:
                future.result(timeout=10)
            except Exception as e:
                logger.warning(f"Discord close timeout: {e}")
                # Force stop event loop
                self._discord_loop.call_soon_threadsafe(self._discord_loop.stop)

        # Wait for thread to finish
        if self._thread and self._thread.is_alive():
            self._shutdown_event.wait(timeout=15)
            if self._thread.is_alive():
                logger.warning("Discord thread did not terminate gracefully")

        logger.info(f"Discord adapter stopped: {self.account_id}")

    async def send(self, chat_id: str, message: OutboundMessage):
        """Send message to specified channel"""
        channel = self.bot.get_channel(int(chat_id))
        if channel:
            await self._send_response(channel, message)

    async def _send_response(self, channel, message: OutboundMessage):
        """Send response message with attachments"""
        import discord
        import os

        content = message.content
        max_len = 1900

        # Send text chunks
        for i in range(0, len(content), max_len):
            chunk = content[i:i + max_len]
            await channel.send(chunk)

        # Send attachments
        for att in message.attachments:
            try:
                if att.local_path and os.path.exists(att.local_path):
                    await channel.send(file=discord.File(att.local_path))
                elif att.url:
                    await channel.send(att.url)
            except Exception as e:
                logger.error(f"Failed to send Discord attachment: {e}")

    async def send_streaming(
        self,
        channel,
        stream: AsyncGenerator[str, None],
        reply_to=None
    ):
        """
        Send streaming response message

        Args:
            channel: Discord channel
            stream: Response stream generator
            reply_to: Message to reply to

        Returns:
            Final sent message object
        """
        import discord

        # Send initial message
        sent_msg = await channel.send(
            "▌",
            reference=reply_to if reply_to else None
        )

        full_response = ""
        last_update_time = time.time()
        edit_count = 0
        max_edits = 50
        min_edit_interval = 1.0  # seconds

        try:
            async for chunk in stream:
                full_response += chunk
                now = time.time()

                # Control edit frequency
                should_update = (
                    now - last_update_time >= min_edit_interval and
                    edit_count < max_edits
                )

                if should_update:
                    display_text = self._truncate_for_discord(full_response + "▌")
                    await self._safe_edit_message(sent_msg, display_text)
                    last_update_time = now
                    edit_count += 1

            # Final update
            if full_response:
                await self._finalize_streaming_message(
                    channel, sent_msg, full_response
                )
            else:
                await sent_msg.edit(content="(No response content)")

        except Exception as e:
            logger.error(f"Discord streaming error: {e}")
            try:
                await sent_msg.edit(content="⚠️ Error processing message")
            except Exception:
                pass

        return sent_msg

    async def _safe_edit_message(self, message, text: str) -> bool:
        """Safely edit message"""
        import discord

        try:
            await message.edit(content=text)
            return True
        except discord.HTTPException as e:
            if e.status == 429:  # Rate limited
                retry_after = getattr(e, 'retry_after', 1)
                await asyncio.sleep(retry_after)
                return await self._safe_edit_message(message, text)
            else:
                logger.error(f"Discord edit error: {e}")
                return False
        except Exception as e:
            logger.error(f"Unexpected Discord edit error: {e}")
            return False

    def _truncate_for_discord(self, text: str, max_length: int = 1900) -> str:
        """Truncate text to fit Discord limit"""
        if len(text) <= max_length:
            return text
        return text[:max_length - 10] + "...(cont.)"

    async def _finalize_streaming_message(
        self,
        channel,
        original_msg,
        full_response: str
    ):
        """
        Finalize streaming message

        If response exceeds Discord limit, split into multiple messages
        """
        max_length = 1900

        if len(full_response) <= max_length:
            await original_msg.edit(content=full_response)
        else:
            # Edit original message to first part
            await original_msg.edit(content=full_response[:max_length])

            # Send remaining parts
            remaining = full_response[max_length:]
            while remaining:
                chunk = remaining[:max_length]
                remaining = remaining[max_length:]
                await channel.send(chunk)

    def _should_respond(self, message) -> bool:
        """Determine if should respond to this message"""
        import discord

        user_id = str(message.author.id)

        # Blacklist check
        if self.blocked_users and user_id in [str(u) for u in self.blocked_users]:
            return False

        # Whitelist check
        if self.allowed_users:
            if user_id not in [str(u) for u in self.allowed_users]:
                return False

        # DM handling
        if isinstance(message.channel, discord.DMChannel):
            return self.respond_to_dms

        # Guild filter
        if self.allowed_guilds:
            if message.guild and message.guild.id not in self.allowed_guilds:
                return False

        # Mention requirement
        if self.require_mention:
            if self.bot.user not in message.mentions:
                return False

        return True

    async def _convert(self, message) -> InboundMessage:
        """Convert Discord message to unified format"""
        import discord

        content = message.content
        if self.bot.user:
            content = content.replace(f"<@{self.bot.user.id}>", "").strip()
            content = content.replace(f"<@!{self.bot.user.id}>", "").strip()

        attachments = []
        for a in message.attachments:
            att_type = MessageType.IMAGE if a.content_type and a.content_type.startswith("image") else MessageType.FILE

            # Download to local
            local_path = None
            try:
                local_path = await self.attachment_handler.download_from_url(
                    url=a.url,
                    original_filename=a.filename
                )
            except Exception as e:
                logger.error(f"Failed to download Discord attachment: {e}")

            attachments.append(Attachment(
                type=att_type,
                url=a.url,
                local_path=local_path,
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
