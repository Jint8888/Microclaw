"""
Metrics Collector

File: python/gateway/metrics.py
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, Optional
import logging

logger = logging.getLogger("gateway.metrics")


@dataclass
class ChannelMetrics:
    """Channel runtime metrics"""
    messages_received: int = 0
    messages_sent: int = 0
    errors: int = 0
    last_error: Optional[str] = None
    last_activity: Optional[datetime] = None
    total_response_time_ms: float = 0.0
    reconnect_count: int = 0

    @property
    def average_response_time_ms(self) -> float:
        if self.messages_sent == 0:
            return 0.0
        return self.total_response_time_ms / self.messages_sent


class MetricsCollector:
    """Metrics collector"""

    def __init__(self):
        self._metrics: Dict[str, ChannelMetrics] = {}
        self._start_time = datetime.now()

    def _ensure_channel(self, channel: str):
        if channel not in self._metrics:
            self._metrics[channel] = ChannelMetrics()

    def record_message_received(self, channel: str):
        self._ensure_channel(channel)
        self._metrics[channel].messages_received += 1
        self._metrics[channel].last_activity = datetime.now()

    def record_message_sent(self, channel: str, response_time_ms: float):
        self._ensure_channel(channel)
        self._metrics[channel].messages_sent += 1
        self._metrics[channel].total_response_time_ms += response_time_ms
        self._metrics[channel].last_activity = datetime.now()

    def record_error(self, channel: str, error: str):
        self._ensure_channel(channel)
        self._metrics[channel].errors += 1
        self._metrics[channel].last_error = error

    def record_reconnect(self, channel: str):
        self._ensure_channel(channel)
        self._metrics[channel].reconnect_count += 1

    def get_channel_metrics(self, channel: str) -> Optional[ChannelMetrics]:
        return self._metrics.get(channel)

    def get_summary(self) -> Dict:
        return {
            "uptime_seconds": (datetime.now() - self._start_time).total_seconds(),
            "channels": {
                name: {
                    "messages_received": m.messages_received,
                    "messages_sent": m.messages_sent,
                    "errors": m.errors,
                    "last_error": m.last_error,
                    "average_response_time_ms": m.average_response_time_ms,
                    "reconnect_count": m.reconnect_count,
                    "last_activity": m.last_activity.isoformat() if m.last_activity else None,
                }
                for name, m in self._metrics.items()
            },
            "totals": {
                "total_messages_received": sum(m.messages_received for m in self._metrics.values()),
                "total_messages_sent": sum(m.messages_sent for m in self._metrics.values()),
                "total_errors": sum(m.errors for m in self._metrics.values()),
            }
        }

    def reset(self):
        """Reset all metrics"""
        self._metrics.clear()
        self._start_time = datetime.now()
