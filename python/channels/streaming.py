"""
Streaming Response Strategy

Select optimal streaming response strategy based on channel capabilities

File: python/channels/streaming.py
"""

from enum import Enum
from dataclasses import dataclass
from typing import Optional, Callable, Awaitable
from .base import ChannelCapabilities
import time


class StreamingStrategy(Enum):
    """Streaming response strategy"""
    BUFFER_ALL = "buffer_all"      # Wait until complete then send
    EDIT_MESSAGE = "edit_message"  # Periodically edit message
    TYPING_INDICATOR = "typing"    # Send "typing" indicator
    CHUNKED_MESSAGES = "chunked"   # Send in paragraph chunks


@dataclass
class StreamingConfig:
    """Streaming response configuration"""
    strategy: StreamingStrategy
    edit_interval_ms: int = 1000   # Edit interval
    chunk_size: int = 500          # Chunk size
    typing_timeout: int = 5        # Typing indicator timeout
    max_edits: int = 50            # Maximum edit count


class StreamingStrategySelector:
    """Streaming strategy selector"""

    @staticmethod
    def select(capabilities: ChannelCapabilities) -> StreamingConfig:
        """Select optimal strategy based on channel capabilities"""

        if capabilities.supports_streaming_edit:
            return StreamingConfig(
                strategy=StreamingStrategy.EDIT_MESSAGE,
                edit_interval_ms=max(capabilities.edit_rate_limit_ms, 1000),
            )
        else:
            return StreamingConfig(
                strategy=StreamingStrategy.BUFFER_ALL,
            )

    @staticmethod
    def get_strategy_for_channel(channel: str) -> StreamingConfig:
        """Get channel-specific strategy"""
        strategies = {
            "telegram": StreamingConfig(
                strategy=StreamingStrategy.EDIT_MESSAGE,
                edit_interval_ms=1500,  # Telegram has stricter edit limits
                max_edits=30,
            ),
            "discord": StreamingConfig(
                strategy=StreamingStrategy.EDIT_MESSAGE,
                edit_interval_ms=1000,
                max_edits=50,
            ),
            "email": StreamingConfig(
                strategy=StreamingStrategy.BUFFER_ALL,  # Email doesn't support streaming
            ),
        }
        return strategies.get(channel, StreamingConfig(strategy=StreamingStrategy.BUFFER_ALL))


class StreamingHandler:
    """Streaming response handler"""

    def __init__(self, config: StreamingConfig, send_func: Callable):
        self.config = config
        self.send_func = send_func
        self._buffer = ""
        self._message_id: Optional[str] = None
        self._edit_count = 0
        self._last_edit_time = 0

    async def handle_chunk(self, chunk: str, full: str):
        """Handle streaming response chunk"""
        if self.config.strategy == StreamingStrategy.BUFFER_ALL:
            self._buffer = full  # Only buffer

        elif self.config.strategy == StreamingStrategy.EDIT_MESSAGE:
            now = time.time() * 1000

            if self._edit_count >= self.config.max_edits:
                self._buffer = full
                return

            if now - self._last_edit_time >= self.config.edit_interval_ms:
                await self._edit_or_send(full)
                self._last_edit_time = now
                self._edit_count += 1

    async def finalize(self) -> str:
        """Finalize streaming response"""
        if self._buffer:
            await self._edit_or_send(self._buffer, final=True)
        return self._buffer

    async def _edit_or_send(self, content: str, final: bool = False):
        """Edit or send message"""
        # Implementation depends on specific channel
        await self.send_func(content, self._message_id, final)

    def set_message_id(self, message_id: str):
        """Set the message ID for editing"""
        self._message_id = message_id

    def reset(self):
        """Reset handler state"""
        self._buffer = ""
        self._message_id = None
        self._edit_count = 0
        self._last_edit_time = 0
