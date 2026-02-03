"""
Message Deduplicator

File: python/gateway/deduplicator.py
"""

import logging
from collections import OrderedDict
from datetime import datetime, timedelta
from typing import Optional
import threading

logger = logging.getLogger("gateway.deduplicator")


class MessageDeduplicator:
    """Message deduplicator (thread-safe)"""

    def __init__(self, ttl_seconds: int = 60, max_size: int = 1000):
        """
        Initialize deduplicator

        Args:
            ttl_seconds: Message ID retention time (seconds)
            max_size: Maximum cached message count
        """
        self.ttl_seconds = ttl_seconds
        self.max_size = max_size
        self._seen: OrderedDict[str, datetime] = OrderedDict()
        self._lock = threading.Lock()

    def is_duplicate(self, message_id: str, channel: str) -> bool:
        """
        Check if message is duplicate

        Args:
            message_id: Message ID
            channel: Channel name

        Returns:
            True if duplicate message
        """
        key = f"{channel}:{message_id}"
        now = datetime.now()

        with self._lock:
            # Clean expired records
            self._cleanup(now)

            if key in self._seen:
                logger.debug(f"Duplicate message detected: {key}")
                return True

            self._seen[key] = now
            return False

    def _cleanup(self, now: datetime):
        """Clean expired records (must be called within lock)"""
        cutoff = now - timedelta(seconds=self.ttl_seconds)

        # Clean expired
        while self._seen:
            key, timestamp = next(iter(self._seen.items()))
            if timestamp < cutoff:
                del self._seen[key]
            else:
                break

        # Limit size (use >= to ensure room for new entry)
        while len(self._seen) >= self.max_size:
            self._seen.popitem(last=False)

    def clear(self):
        """Clear all records"""
        with self._lock:
            self._seen.clear()

    @property
    def size(self) -> int:
        """Current cache size"""
        with self._lock:
            return len(self._seen)
