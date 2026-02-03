"""
Channel Security Module

File: python/channels/security.py
"""

import time
import logging
from typing import Dict, Set, Optional
from dataclasses import dataclass, field
from collections import defaultdict

from .base import InboundMessage

logger = logging.getLogger("channels.security")


@dataclass
class RateLimitConfig:
    """Rate limit configuration"""
    max_requests: int = 10
    window_seconds: int = 60


@dataclass
class RateLimitState:
    """Rate limit state"""
    requests: list = field(default_factory=list)

    def is_limited(self, config: RateLimitConfig) -> bool:
        now = time.time()
        # Clean expired requests
        self.requests = [t for t in self.requests if now - t < config.window_seconds]
        if len(self.requests) >= config.max_requests:
            return True
        self.requests.append(now)
        return False


class SecurityManager:
    """Security manager"""

    def __init__(self, config):
        self.config = config
        self._whitelists: Dict[str, Set[str]] = {}
        self._blacklists: Dict[str, Set[str]] = {}
        self._rate_limits: Dict[str, RateLimitState] = defaultdict(RateLimitState)
        self._rate_config = RateLimitConfig()

        self._load_lists()

    def _load_lists(self):
        """Load whitelist/blacklist from config"""
        channels = self.config.channels if hasattr(self.config, 'channels') else {}
        for channel_name, channel_cfg in channels.items():
            if isinstance(channel_cfg, dict):
                whitelist = channel_cfg.get("whitelist", [])
                if whitelist:
                    self._whitelists[channel_name] = set(str(u) for u in whitelist)
                blacklist = channel_cfg.get("blacklist", [])
                if blacklist:
                    self._blacklists[channel_name] = set(str(u) for u in blacklist)

                # Load rate limit config
                rate_limit = channel_cfg.get("rate_limit", {})
                if rate_limit:
                    self._rate_config = RateLimitConfig(
                        max_requests=rate_limit.get("max_requests", 10),
                        window_seconds=rate_limit.get("window_seconds", 60)
                    )

    def check_access(self, message: InboundMessage) -> bool:
        """Check access permission"""
        channel = message.channel
        user_id = message.channel_user_id

        # Blacklist check
        if channel in self._blacklists:
            if user_id in self._blacklists[channel]:
                logger.warning(f"Blocked blacklisted user: {channel}:{user_id}")
                return False

        # Whitelist check
        if channel in self._whitelists:
            if user_id not in self._whitelists[channel]:
                logger.warning(f"Blocked non-whitelisted user: {channel}:{user_id}")
                return False

        return True

    def check_rate_limit(self, message: InboundMessage) -> bool:
        """Check rate limit"""
        key = f"{message.channel}:{message.channel_user_id}"
        state = self._rate_limits[key]

        if state.is_limited(self._rate_config):
            logger.warning(f"Rate limited: {key}")
            return False
        return True

    def validate_message(self, message: InboundMessage) -> bool:
        """Validate message"""
        # Content length check
        if len(message.content) > 10000:
            logger.warning(f"Message too long from {message.channel}:{message.channel_user_id}")
            return False

        return True

    def sanitize_output(self, content: str) -> str:
        """Sanitize output content"""
        # Remove potentially dangerous content
        # Extensible: XSS protection, etc.
        return content

    def reload_config(self, new_config):
        """Reload configuration"""
        self.config = new_config
        self._load_lists()
        logger.info("Security config reloaded")

    def add_to_whitelist(self, channel: str, user_id: str):
        """Add user to whitelist"""
        if channel not in self._whitelists:
            self._whitelists[channel] = set()
        self._whitelists[channel].add(str(user_id))

    def remove_from_whitelist(self, channel: str, user_id: str):
        """Remove user from whitelist"""
        if channel in self._whitelists:
            self._whitelists[channel].discard(str(user_id))

    def add_to_blacklist(self, channel: str, user_id: str):
        """Add user to blacklist"""
        if channel not in self._blacklists:
            self._blacklists[channel] = set()
        self._blacklists[channel].add(str(user_id))

    def remove_from_blacklist(self, channel: str, user_id: str):
        """Remove user from blacklist"""
        if channel in self._blacklists:
            self._blacklists[channel].discard(str(user_id))
