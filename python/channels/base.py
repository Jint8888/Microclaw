"""
Channel Adapter Base Class and Message Models (V4 Enhanced)

File: python/channels/base.py
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Callable, Awaitable
from enum import Enum
from datetime import datetime
from abc import ABC, abstractmethod
import asyncio


class MessageType(Enum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    FILE = "file"


@dataclass
class Attachment:
    """Attachment model (enhanced)"""
    type: MessageType
    url: Optional[str] = None
    data: Optional[bytes] = None
    filename: Optional[str] = None
    mime_type: Optional[str] = None
    size: Optional[int] = None  # File size (bytes)
    local_path: Optional[str] = None  # Local file path after download

    @property
    def is_large(self) -> bool:
        """Is large file (>10MB)"""
        return self.size and self.size > 10 * 1024 * 1024


@dataclass
class InboundMessage:
    """Inbound message (User → Agent)"""
    channel: str
    channel_user_id: str
    channel_chat_id: str
    content: str
    message_id: str
    timestamp: datetime = field(default_factory=datetime.now)
    attachments: List[Attachment] = field(default_factory=list)
    is_group: bool = False
    reply_to_id: Optional[str] = None
    user_name: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OutboundMessage:
    """Outbound message (Agent → User)"""
    content: str
    attachments: List[Attachment] = field(default_factory=list)
    parse_mode: str = "markdown"
    reply_to_id: Optional[str] = None


@dataclass
class ChannelCapabilities:
    """Channel capability declaration"""
    supports_markdown: bool = True
    supports_html: bool = False
    supports_reactions: bool = False
    supports_threads: bool = False
    supports_edit: bool = True
    supports_delete: bool = True
    max_message_length: int = 4096
    supports_attachments: bool = True
    supports_voice: bool = False
    # New: Streaming response related
    supports_streaming_edit: bool = False  # Supports editing message for streaming
    edit_rate_limit_ms: int = 1000  # Edit message rate limit


MessageHandler = Callable[[InboundMessage], Awaitable[OutboundMessage]]


class ChannelAdapter(ABC):
    """Channel adapter abstract base class (V4 Enhanced)"""

    def __init__(self, config: dict, account_id: str = "default"):
        self.config = config
        self.account_id = account_id
        self.name = self.__class__.__name__
        self._handler: Optional[MessageHandler] = None
        self._running = False
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 5
        self._reconnect_base_delay = 1.0
        self._max_reconnect_delay = 300  # Max reconnect delay 5 minutes

    @property
    @abstractmethod
    def capabilities(self) -> ChannelCapabilities:
        pass

    def on_message(self, handler: MessageHandler):
        self._handler = handler

    @abstractmethod
    async def start(self):
        pass

    @abstractmethod
    async def stop(self):
        pass

    @abstractmethod
    async def send(self, chat_id: str, message: OutboundMessage):
        pass

    async def handle(self, message: InboundMessage) -> OutboundMessage:
        if self._handler:
            return await self._handler(message)
        return OutboundMessage(content="Handler not configured")

    # Error recovery methods
    async def reconnect(self) -> bool:
        """Reconnect with exponential backoff"""
        if self._reconnect_attempts >= self._max_reconnect_attempts:
            return False

        # Add delay cap to avoid excessive waiting
        delay = min(
            self._reconnect_base_delay * (2 ** self._reconnect_attempts),
            self._max_reconnect_delay
        )
        self._reconnect_attempts += 1

        await asyncio.sleep(delay)

        try:
            await self.stop()
            await self.start()
            self._reconnect_attempts = 0
            return True
        except Exception:
            return False

    async def handle_rate_limit(self, retry_after: float):
        """Handle rate limit"""
        await asyncio.sleep(retry_after)

    def reset_reconnect_counter(self):
        """Reset reconnect counter"""
        self._reconnect_attempts = 0
