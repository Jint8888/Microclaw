"""
Telegram Bot Adapter (V4.1 Enhanced with Streaming)

Features:
- Text message send/receive
- Image/file support
- Group @mention detection
- Long message auto-chunking
- Streaming response (message editing)

Dependency: pip install python-telegram-bot>=20.0

File: python/channels/telegram_adapter.py
"""

import asyncio
import logging
import time
from typing import Optional, AsyncGenerator, TYPE_CHECKING

from .base import (
    ChannelAdapter, ChannelCapabilities,
    InboundMessage, OutboundMessage, Attachment, MessageType
)

if TYPE_CHECKING:
    from python.gateway.attachment_handler import AttachmentHandler

logger = logging.getLogger("channels.telegram")


class TelegramAdapter(ChannelAdapter):
    """Telegram Bot Adapter"""

    def __init__(self, config: dict, account_id: str = "default"):
        super().__init__(config, account_id)
        self.token = config["token"]
        self.app = None

        # Configuration options
        self.require_mention_in_groups = config.get("require_mention_in_groups", True)
        self.allowed_users = config.get("whitelist", [])  # User whitelist
        self.blocked_users = config.get("blacklist", [])  # User blacklist

        # Attachment handler (lazy loaded)
        self._attachment_handler: Optional["AttachmentHandler"] = None

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
            supports_streaming_edit=True,
            edit_rate_limit_ms=1500,  # Telegram has stricter edit limits
        )

    @property
    def attachment_handler(self) -> "AttachmentHandler":
        """Lazy load attachment handler"""
        if self._attachment_handler is None:
            from python.gateway.attachment_handler import AttachmentHandler
            self._attachment_handler = AttachmentHandler()
        return self._attachment_handler

    async def start(self):
        """Start Telegram Bot"""
        try:
            from telegram.ext import Application, MessageHandler, filters
        except ImportError:
            raise ImportError(
                "python-telegram-bot not installed. "
                "Install with: pip install python-telegram-bot>=20.0"
            )

        self.app = Application.builder().token(self.token).build()

        # Register message handlers
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
        self.reset_reconnect_counter()
        logger.info(f"Telegram adapter started: {self.account_id}")

    async def stop(self):
        """Stop Telegram Bot"""
        if self.app:
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()
        self._running = False
        logger.info(f"Telegram adapter stopped: {self.account_id}")

    async def send(self, chat_id: str, message: OutboundMessage):
        """Send message"""
        if not self.app:
            raise RuntimeError("Telegram adapter not started")

        # Chunk long messages (Telegram limit 4096 chars)
        content = message.content
        max_len = 4000  # Leave some margin

        for i in range(0, len(content), max_len):
            chunk = content[i:i + max_len]
            parse_mode = "Markdown" if message.parse_mode == "markdown" else None
            try:
                await self.app.bot.send_message(
                    chat_id=int(chat_id),
                    text=chunk,
                    parse_mode=parse_mode
                )
            except Exception as e:
                # Retry without parse_mode if formatting fails
                logger.warning(f"Send with parse_mode failed, retrying plain: {e}")
                await self.app.bot.send_message(
                    chat_id=int(chat_id),
                    text=chunk
                )

        # Send attachments
        for att in message.attachments:
            try:
                if att.type == MessageType.IMAGE:
                    await self.app.bot.send_photo(
                        chat_id=int(chat_id),
                        photo=att.url or att.data or att.local_path
                    )
                elif att.type == MessageType.FILE:
                    await self.app.bot.send_document(
                        chat_id=int(chat_id),
                        document=att.url or att.data or att.local_path,
                        filename=att.filename
                    )
            except Exception as e:
                logger.error(f"Failed to send attachment: {e}")

    async def send_streaming(
        self,
        chat_id: str,
        stream: AsyncGenerator[str, None],
        reply_to_id: Optional[str] = None
    ):
        """
        Send streaming response message

        Args:
            chat_id: Chat ID
            stream: Response stream generator
            reply_to_id: Message ID to reply to

        Returns:
            Final sent message object
        """
        if not self.app:
            raise RuntimeError("Telegram adapter not started")

        # Send initial message
        sent_msg = await self.app.bot.send_message(
            chat_id=int(chat_id),
            text="▌",  # Cursor indicator
            reply_to_message_id=int(reply_to_id) if reply_to_id else None
        )

        full_response = ""
        last_update_time = time.time()
        edit_count = 0
        max_edits = 30  # Telegram edit limit
        min_edit_interval = 1.5  # seconds

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
                    await self._safe_edit_message(
                        chat_id=int(chat_id),
                        message_id=sent_msg.message_id,
                        text=full_response + "▌"
                    )
                    last_update_time = now
                    edit_count += 1

            # Final update (remove cursor)
            if full_response:
                await self._safe_edit_message(
                    chat_id=int(chat_id),
                    message_id=sent_msg.message_id,
                    text=full_response
                )
            else:
                # If no response content, delete placeholder message
                await self.app.bot.delete_message(
                    chat_id=int(chat_id),
                    message_id=sent_msg.message_id
                )
                sent_msg = await self.app.bot.send_message(
                    chat_id=int(chat_id),
                    text="(No response content)"
                )

        except Exception as e:
            logger.error(f"Streaming error: {e}")
            # Try to send error status
            try:
                error_text = full_response or "Error processing message"
                await self._safe_edit_message(
                    chat_id=int(chat_id),
                    message_id=sent_msg.message_id,
                    text=f"⚠️ {error_text}"
                )
            except Exception:
                pass

        return sent_msg

    async def _keep_typing(self, chat_id: int, context, interval: float = 4.0):
        """
        Keep sending typing indicator until cancelled.

        Telegram typing indicator lasts ~5 seconds, so we refresh every 4 seconds.
        This creates the "three dots" effect that shows the bot is working.

        Args:
            chat_id: Chat ID to send typing to
            context: Telegram context
            interval: Refresh interval in seconds (default 4.0)
        """
        from telegram.constants import ChatAction

        try:
            while True:
                await self.app.bot.send_chat_action(
                    chat_id=chat_id,
                    action=ChatAction.TYPING
                )
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            # Task was cancelled, this is expected
            pass
        except Exception as e:
            logger.debug(f"Typing indicator stopped: {e}")

    async def _safe_edit_message(
        self,
        chat_id: int,
        message_id: int,
        text: str
    ) -> bool:
        """
        Safely edit message (handle various error cases)

        Returns:
            Whether edit succeeded
        """
        from telegram.error import BadRequest, RetryAfter

        try:
            # Truncate overly long text
            if len(text) > 4000:
                text = text[:3990] + "...(truncated)"

            await self.app.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                parse_mode=None  # Disable parsing during streaming to avoid format errors
            )
            return True

        except BadRequest as e:
            error_msg = str(e).lower()
            if "message is not modified" in error_msg:
                # Content unchanged, ignore
                return True
            elif "message to edit not found" in error_msg:
                logger.warning("Message was deleted, cannot edit")
                return False
            else:
                logger.error(f"Edit message error: {e}")
                return False

        except RetryAfter as e:
            # Rate limited
            logger.warning(f"Rate limited, waiting {e.retry_after}s")
            await asyncio.sleep(e.retry_after)
            return await self._safe_edit_message(chat_id, message_id, text)

        except Exception as e:
            logger.error(f"Unexpected edit error: {e}")
            return False

    async def _send_attachments(self, chat_id: int, attachments: list):
        """
        Send attachment list to chat (DRY refactor)

        Args:
            chat_id: Chat ID to send to
            attachments: List of Attachment objects
        """
        for att in attachments:
            try:
                if att.type == MessageType.IMAGE:
                    await self.app.bot.send_photo(
                        chat_id=chat_id,
                        photo=att.local_path or att.url or att.data
                    )
                elif att.type == MessageType.FILE:
                    await self.app.bot.send_document(
                        chat_id=chat_id,
                        document=att.local_path or att.url or att.data,
                        filename=att.filename
                    )
            except Exception as e:
                logger.error(f"Failed to send attachment: {e}")

    async def _handle_with_typing(
        self,
        update,
        context,
        msg: InboundMessage,
        placeholder_text: str
    ):
        """
        Unified message handling with typing indicator (DRY refactor)

        Args:
            update: Telegram update object
            context: Telegram context
            msg: Converted inbound message
            placeholder_text: Initial placeholder text to show
        """
        chat_id = int(msg.channel_chat_id)

        # Start typing indicator task
        typing_task = asyncio.create_task(self._keep_typing(chat_id, context))

        try:
            # Send initial placeholder message
            placeholder_msg = await self.app.bot.send_message(
                chat_id=chat_id,
                text=placeholder_text,
                reply_to_message_id=int(msg.message_id)
            )

            # Process message
            response = await self.handle(msg)

            # Update with final response
            if response.content:
                await self._safe_edit_message(
                    chat_id=chat_id,
                    message_id=placeholder_msg.message_id,
                    text=response.content
                )
            else:
                await self._safe_edit_message(
                    chat_id=chat_id,
                    message_id=placeholder_msg.message_id,
                    text="(无响应内容)"
                )

            # Send attachments using unified method
            await self._send_attachments(chat_id, response.attachments)

        except Exception as e:
            logger.error(f"Error handling message: {e}")
            try:
                await self.app.bot.send_message(
                    chat_id=chat_id,
                    text=f"⚠️ 处理消息时出错: {str(e)[:200]}"
                )
            except Exception:
                pass
        finally:
            # Stop typing indicator
            typing_task.cancel()
            try:
                await typing_task
            except asyncio.CancelledError:
                pass

    async def _on_message(self, update, context):
        """Handle text message with typing indicator and streaming response"""
        if not self._should_respond(update):
            return
        msg = self._convert(update)
        await self._handle_with_typing(update, context, msg, "🤔 思考中...")

    async def _on_photo(self, update, context):
        """Handle photo message with typing indicator (DRY refactored)"""
        if not self._should_respond(update):
            return

        msg = self._convert(update)

        # Get largest size photo
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)

        # Download to local
        try:
            local_path = await self.attachment_handler.download_from_url(
                url=file.file_path,
                original_filename=f"photo_{photo.file_id}.jpg"
            )
            msg.attachments.append(Attachment(
                type=MessageType.IMAGE,
                url=file.file_path,
                local_path=local_path,
            ))
        except Exception as e:
            logger.error(f"Failed to download photo: {e}")

        # Use unified handler
        await self._handle_with_typing(update, context, msg, "🖼️ 正在分析图片...")

    async def _on_document(self, update, context):
        """Handle document message with typing indicator (DRY refactored)"""
        if not self._should_respond(update):
            return

        msg = self._convert(update)

        doc = update.message.document
        file = await context.bot.get_file(doc.file_id)

        # Download to local
        try:
            local_path = await self.attachment_handler.download_from_url(
                url=file.file_path,
                original_filename=doc.file_name
            )
            msg.attachments.append(Attachment(
                type=MessageType.FILE,
                url=file.file_path,
                local_path=local_path,
                filename=doc.file_name,
                mime_type=doc.mime_type,
                size=doc.file_size,
            ))
        except Exception as e:
            logger.error(f"Failed to download document: {e}")

        # Use unified handler
        await self._handle_with_typing(update, context, msg, "📄 正在处理文件...")

    def _should_respond(self, update) -> bool:
        """Determine if should respond to this message"""
        message = update.message
        if not message:
            return False

        user_id = str(message.from_user.id)

        # Blacklist check
        if self.blocked_users and user_id in [str(u) for u in self.blocked_users]:
            return False

        # Whitelist check
        if self.allowed_users:
            if user_id not in [str(u) for u in self.allowed_users]:
                return False

        # Require @mention in groups
        if message.chat.type in ["group", "supergroup"]:
            if self.require_mention_in_groups:
                bot_username = self.app.bot.username
                text = message.text or message.caption or ""
                if f"@{bot_username}" not in text:
                    return False

        return True

    def _convert(self, update) -> InboundMessage:
        """Convert Telegram message to unified format"""
        m = update.message

        # Remove @mention
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
