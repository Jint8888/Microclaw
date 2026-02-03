"""
Agent Zero Bridge Layer (V4.1 Thread-Safe Version)

Responsible for:
- Managing AgentContext lifecycle
- Converting channel messages to Agent-processable format
- Handling streaming responses and passing them to channels

File: python/gateway/agent_bridge.py
"""

import asyncio
import logging
import threading
from typing import AsyncGenerator, Dict, Optional, Any, Callable, Awaitable
from datetime import datetime, timezone
from dataclasses import dataclass

logger = logging.getLogger("gateway.agent_bridge")


@dataclass
class ChannelSession:
    """Channel session information"""
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
    """Gateway and Agent Zero Bridge Layer (Thread-Safe Version)"""

    # Streaming response end marker
    _STREAM_END = object()

    def __init__(self, default_config: Any = None):
        """
        Initialize bridge layer

        Args:
            default_config: Default Agent configuration, auto-fetched if not provided
        """
        # Lazy import to avoid circular dependencies
        self._default_config = default_config
        self._config_initialized = False
        self._sessions: Dict[str, ChannelSession] = {}
        self._lock = threading.Lock()  # Thread lock protection

    def _ensure_config(self):
        """Ensure configuration is initialized"""
        if not self._config_initialized:
            if self._default_config is None:
                try:
                    from initialize import initialize_agent
                    self._default_config = initialize_agent()
                except ImportError:
                    logger.warning("Could not import initialize_agent, using None config")
            self._config_initialized = True

    @property
    def default_config(self):
        """Get default configuration (lazy loaded)"""
        self._ensure_config()
        return self._default_config

    def _make_session_key(self, channel: str, channel_user_id: str) -> str:
        """
        Generate session key

        Use prefix to distinguish channels, avoiding conflicts with Web UI's random IDs
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
    ):
        """
        Get or create AgentContext (thread-safe)

        Session key format: {prefix}:{user_id}
        Example: tg:456789, dc:123456789
        """
        # Lazy import
        from agent import AgentContext, AgentContextType

        session_key = self._make_session_key(channel, channel_user_id)

        with self._lock:  # Thread lock protection
            # Try to get existing context
            existing_ctx = AgentContext.get(session_key)
            if existing_ctx:
                # Update activity time
                if session_key in self._sessions:
                    self._sessions[session_key].last_activity = datetime.now(timezone.utc)
                return existing_ctx

            # Create new context
            config = self._build_config(channel_config)

            ctx = AgentContext(
                config=config,
                id=session_key,
                name=f"{channel}:{user_name or channel_user_id}",
                type=AgentContextType.USER,
            )

            # Record session info
            self._sessions[session_key] = ChannelSession(
                context_id=session_key,
                channel=channel,
                channel_user_id=channel_user_id,
                channel_chat_id=channel_chat_id,
                user_name=user_name,
            )

            logger.info(f"Created new context: {session_key}")
            return ctx

    def _build_config(self, channel_config: Optional[dict] = None):
        """Build Agent configuration with channel-specific overrides"""
        if not channel_config:
            return self.default_config

        model_override = channel_config.get("model_override", {})
        if not model_override:
            return self.default_config

        import copy
        config = copy.deepcopy(self.default_config)
        # Support channel-specific model configuration (extend as needed)
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
        Process channel message

        Args:
            channel: Channel name (telegram, discord)
            channel_user_id: Channel user ID
            channel_chat_id: Channel chat ID
            content: Message content
            user_name: Username
            attachments: Attachment file path list (must be local paths)
            metadata: Extra metadata
            channel_config: Channel configuration
            stream_callback: Streaming response callback async def(chunk: str, full: str)

        Returns:
            Agent's complete response
        """
        # Lazy import
        from agent import UserMessage

        # Get or create context
        ctx = self.get_or_create_context(
            channel=channel,
            channel_user_id=channel_user_id,
            channel_chat_id=channel_chat_id,
            user_name=user_name,
            channel_config=channel_config,
        )

        # Build UserMessage
        user_msg = UserMessage(
            message=content,
            attachments=attachments or [],
            system_message=[],
        )

        # Store channel metadata in context
        ctx.set_data("channel_metadata", {
            "channel": channel,
            "chat_id": channel_chat_id,
            "user_id": channel_user_id,
            "user_name": user_name,
            **(metadata or {}),
        })

        # Register streaming callback (via Extension mechanism)
        if stream_callback:
            ctx.set_data("gateway_stream_callback", stream_callback)

        try:
            # Call Agent's communicate method
            task = ctx.communicate(user_msg)

            # Wait for task completion
            if task:
                response = await task.result()  # Use result() not wait()
                return response or ""
            return ""

        finally:
            # Clean up streaming callback
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
        Process message and return streaming response (race condition fixed)

        Uses sentinel value to mark end, avoiding race conditions

        Yields:
            Response chunks
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
                # Use sentinel value to explicitly mark end
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
        """Get session info (thread-safe)"""
        session_key = self._make_session_key(channel, channel_user_id)
        with self._lock:
            return self._sessions.get(session_key)

    def list_sessions(self) -> Dict[str, ChannelSession]:
        """List all sessions (thread-safe)"""
        with self._lock:
            return self._sessions.copy()

    def remove_session(self, channel: str, channel_user_id: str) -> bool:
        """Remove session (thread-safe)"""
        from agent import AgentContext

        session_key = self._make_session_key(channel, channel_user_id)
        with self._lock:
            if session_key in self._sessions:
                del self._sessions[session_key]
                AgentContext.remove(session_key)
                logger.info(f"Removed session: {session_key}")
                return True
            return False

    def get_sessions_by_channel(self, channel: str) -> Dict[str, ChannelSession]:
        """Get all sessions for a specific channel"""
        with self._lock:
            return {
                k: v for k, v in self._sessions.items()
                if v.channel == channel
            }

    def get_active_session_count(self) -> int:
        """Get active session count"""
        with self._lock:
            return len(self._sessions)
