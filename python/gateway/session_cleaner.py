"""
Session Cleaner

File: python/gateway/session_cleaner.py
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, List, Tuple

if TYPE_CHECKING:
    from .agent_bridge import AgentBridge

logger = logging.getLogger("gateway.session_cleaner")


class SessionCleaner:
    """Session cleaner"""

    def __init__(
        self,
        agent_bridge: "AgentBridge",
        max_idle_hours: int = 24,
        check_interval_seconds: int = 3600
    ):
        """
        Initialize session cleaner

        Args:
            agent_bridge: AgentBridge instance
            max_idle_hours: Maximum idle time (hours)
            check_interval_seconds: Check interval (seconds)
        """
        self.agent_bridge = agent_bridge
        self.max_idle_hours = max_idle_hours
        self.check_interval = check_interval_seconds
        self._task: asyncio.Task = None
        self._running = False

    async def start(self):
        """Start cleanup task"""
        if self._task is None or self._task.done():
            self._running = True
            self._task = asyncio.create_task(self._cleanup_loop())
            logger.info(
                f"Session cleaner started (max_idle: {self.max_idle_hours}h, "
                f"interval: {self.check_interval}s)"
            )

    async def stop(self):
        """Stop cleanup task"""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Session cleaner stopped")

    async def _cleanup_loop(self):
        """Cleanup loop"""
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
        Clean up idle sessions

        Returns:
            Number of cleaned sessions
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.max_idle_hours)

        # Collect sessions to remove
        sessions_to_remove: List[Tuple[str, str]] = []

        for key, session in self.agent_bridge.list_sessions().items():
            if session.last_activity and session.last_activity < cutoff:
                sessions_to_remove.append((session.channel, session.channel_user_id))

        # Execute cleanup
        cleaned_count = 0
        for channel, user_id in sessions_to_remove:
            if self.agent_bridge.remove_session(channel, user_id):
                cleaned_count += 1

        if cleaned_count > 0:
            logger.info(f"Cleaned up {cleaned_count} idle session(s)")

        return cleaned_count

    def get_idle_sessions(self, idle_hours: int = None) -> List[dict]:
        """
        Get list of idle sessions

        Args:
            idle_hours: Idle time threshold, defaults to config value

        Returns:
            List of idle session info
        """
        hours = idle_hours or self.max_idle_hours
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

        idle_sessions = []
        for key, session in self.agent_bridge.list_sessions().items():
            if session.last_activity and session.last_activity < cutoff:
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
