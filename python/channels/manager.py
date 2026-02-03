"""
Channel Manager

Responsible for:
- Channel registration and lifecycle management
- Message routing
- Multi-account support

File: python/channels/manager.py
"""

import asyncio
import logging
import time
from typing import Dict, Optional, TYPE_CHECKING

from .base import ChannelAdapter, InboundMessage, OutboundMessage
from python.gateway.deduplicator import MessageDeduplicator
from python.gateway.errors import error_handler

if TYPE_CHECKING:
    from python.gateway.agent_bridge import AgentBridge
    from python.gateway.metrics import MetricsCollector
    from .security import SecurityManager

logger = logging.getLogger("channels.manager")


class ChannelManager:
    """Channel manager"""

    def __init__(
        self,
        agent_bridge: "AgentBridge",
        security_manager: "SecurityManager" = None,
        metrics: "MetricsCollector" = None
    ):
        """
        Initialize channel manager

        Args:
            agent_bridge: AgentBridge bridge layer
            security_manager: Security manager
            metrics: Metrics collector
        """
        self.agent_bridge = agent_bridge
        self.security_manager = security_manager
        self.metrics = metrics
        self.channels: Dict[str, ChannelAdapter] = {}
        # Message deduplicator (CHG-004)
        self.deduplicator = MessageDeduplicator(ttl_seconds=60, max_size=1000)

    def register(self, name: str, adapter: ChannelAdapter):
        """Register channel"""
        adapter.on_message(self._process_message)
        self.channels[name] = adapter
        logger.info(f"Registered channel: {name}")

    def unregister(self, name: str):
        """Unregister channel"""
        if name in self.channels:
            del self.channels[name]
            logger.info(f"Unregistered channel: {name}")

    def get_channel(self, name: str) -> Optional[ChannelAdapter]:
        """Get channel"""
        return self.channels.get(name)

    def list_channels(self) -> Dict[str, dict]:
        """List all channels"""
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
        """Start all channels (concurrent)"""
        if not self.channels:
            logger.warning("No channels to start")
            return

        # Use gather for concurrent startup, but capture individual failures
        results = await asyncio.gather(
            *[self._start_channel(name, ch) for name, ch in self.channels.items()],
            return_exceptions=True
        )

        # Log startup results
        for (name, _), result in zip(self.channels.items(), results):
            if isinstance(result, Exception):
                logger.error(f"Failed to start channel {name}: {result}")

    async def _start_channel(self, name: str, adapter: ChannelAdapter):
        """Start single channel"""
        try:
            await adapter.start()
            adapter._running = True
            logger.info(f"Started channel: {name}")
        except Exception as e:
            adapter._running = False
            raise e

    async def stop_all(self):
        """Stop all channels"""
        await asyncio.gather(
            *[self._stop_channel(name, ch) for name, ch in self.channels.items()],
            return_exceptions=True
        )

    async def _stop_channel(self, name: str, adapter: ChannelAdapter):
        """Stop single channel"""
        try:
            await adapter.stop()
            adapter._running = False
            logger.info(f"Stopped channel: {name}")
        except Exception as e:
            logger.error(f"Error stopping channel {name}: {e}")

    async def apply_config_change(self, new_config: dict):
        """Apply configuration change (enhanced)"""
        channels_config = new_config.get("channels", {})
        changes_summary = []
        restart_required = []

        for channel_name, channel_cfg in channels_config.items():
            full_name = f"{channel_name}:{channel_cfg.get('account_id', 'default')}"

            # Detect changes requiring restart
            if full_name in self.channels:
                old_cfg = self.channels[full_name].config

                # Token change detection
                if old_cfg.get("token") != channel_cfg.get("token"):
                    restart_required.append(f"{full_name}: token changed")
                    logger.warning(
                        f"⚠️ Token changed for {full_name}, restart required!"
                    )

            # Disable channel
            if not channel_cfg.get("enabled", False):
                if full_name in self.channels:
                    await self._stop_channel(full_name, self.channels[full_name])
                    self.unregister(full_name)
                    changes_summary.append(f"Disabled: {full_name}")

            # Update hot-reloadable configs
            if full_name in self.channels:
                adapter = self.channels[full_name]

                # Whitelist/blacklist takes effect immediately
                if "whitelist" in channel_cfg:
                    adapter.config["whitelist"] = channel_cfg["whitelist"]
                    changes_summary.append(f"Updated whitelist: {full_name}")

                if "require_mention" in channel_cfg:
                    adapter.config["require_mention"] = channel_cfg["require_mention"]
                    changes_summary.append(f"Updated require_mention: {full_name}")

        # Reload security config
        if self.security_manager:
            self.security_manager.reload_config(
                type('Config', (), {'channels': channels_config})()
            )

        # Log summary
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

    async def _process_message(self, msg: InboundMessage) -> OutboundMessage:
        """Route message to Agent"""
        start_time = time.time()

        # Message deduplication check (CHG-004)
        if self.deduplicator.is_duplicate(msg.message_id, msg.channel):
            logger.debug(f"Duplicate message ignored: {msg.channel}:{msg.message_id}")
            return None

        # Security checks
        if self.security_manager:
            if not self.security_manager.check_access(msg):
                return OutboundMessage(content="⚠️ Access denied")
            if not self.security_manager.check_rate_limit(msg):
                return OutboundMessage(content="⚠️ Rate limit exceeded, please slow down")
            if not self.security_manager.validate_message(msg):
                return OutboundMessage(content="⚠️ Invalid message")

        # Record receive metrics
        if self.metrics:
            self.metrics.record_message_received(msg.channel)

        try:
            # Process attachments - convert to local paths
            attachment_paths = []
            for att in msg.attachments:
                if att.local_path:
                    attachment_paths.append(att.local_path)

            # Process message via AgentBridge
            response = await self.agent_bridge.process_message(
                channel=msg.channel,
                channel_user_id=msg.channel_user_id,
                channel_chat_id=msg.channel_chat_id,
                content=msg.content,
                user_name=msg.user_name,
                attachments=attachment_paths,
                metadata=msg.metadata,
            )

            # Record send metrics
            if self.metrics:
                response_time = (time.time() - start_time) * 1000
                self.metrics.record_message_sent(msg.channel, response_time)

            # Extract image attachments from response (Gateway only, does not affect WebUI)
            response_attachments = self._extract_image_attachments(response)

            return OutboundMessage(content=response, attachments=response_attachments)

        except Exception as e:
            logger.error(f"Error processing message: {e}")
            if self.metrics:
                self.metrics.record_error(msg.channel, str(e))

            # Use error handler for user-friendly message (CHG-005)
            user_message = error_handler.format_error(e, language="zh")
            return OutboundMessage(content=user_message)

    def _extract_image_attachments(self, response: str) -> list:
        """
        Extract image paths from Agent response and convert to Attachment objects.

        This only affects Gateway channels (Telegram, Discord, etc.),
        WebUI communicates directly with Agent and is not affected.

        Supported patterns:
        - /a0/tmp/xxx.jpg
        - /a0/data/xxx.png
        - /git/agent-zero/tmp/xxx.gif
        - Docker container paths

        Returns:
            List of Attachment objects for detected images
        """
        import re
        import os
        from .base import Attachment, MessageType

        attachments = []

        # Image file extensions
        image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}

        # Path patterns to detect (Docker container paths)
        # Match any image file under these base directories
        path_patterns = [
            r'(/a0/[^\s\"\'\)\]]*\.(?:jpg|jpeg|png|gif|webp|bmp))',
            r'(/git/agent-zero/[^\s\"\'\)\]]*\.(?:jpg|jpeg|png|gif|webp|bmp))',
            r'(/app/[^\s\"\'\)\]]*\.(?:jpg|jpeg|png|gif|webp|bmp))',
        ]

        found_paths = set()

        for pattern in path_patterns:
            matches = re.findall(pattern, response, re.IGNORECASE)
            found_paths.update(matches)

        for path in found_paths:
            # Verify file exists
            if os.path.isfile(path):
                ext = os.path.splitext(path)[1].lower()
                if ext in image_extensions:
                    attachments.append(Attachment(
                        type=MessageType.IMAGE,
                        local_path=path,
                        filename=os.path.basename(path),
                    ))
                    logger.info(f"Extracted image attachment: {path}")

        return attachments
