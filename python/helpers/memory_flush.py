"""Memory flush module for pre-compaction memory preservation.

This module provides MemoryFlush for automatically triggering memory saves
before session context is compressed due to token limits.
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional, Set
import logging

logger = logging.getLogger(__name__)


@dataclass
class MemoryFlushConfig:
    """Memory flush configuration.
    
    Attributes:
        enabled: Whether memory flush is enabled
        soft_threshold_tokens: Soft threshold before context window limit
        reserve_tokens_floor: Reserved tokens for new messages
        system_prompt: System prompt for flush trigger
        user_prompt: User prompt for flush trigger
    """
    enabled: bool = True
    soft_threshold_tokens: int = 4000
    reserve_tokens_floor: int = 20000
    system_prompt: str = "Session nearing compaction. Store durable memories now."
    user_prompt: str = "Write any lasting notes to memory; reply with NO_REPLY if nothing to store."


class MemoryFlush:
    """Memory flush manager for pre-compaction preservation.
    
    Monitors session token counts and triggers silent memory saves before
    context window compression. Each compaction cycle only triggers once.
    
    Attributes:
        config: MemoryFlushConfig instance
    
    Example:
        >>> flush = MemoryFlush()
        >>> if flush.should_flush("sess-1", 50000, 64000):
        ...     await flush.flush(agent, "sess-1")
    """
    
    def __init__(self, config: Optional[MemoryFlushConfig] = None):
        """Initialize MemoryFlush.
        
        Args:
            config: Optional configuration, uses defaults if None
        """
        self.config = config or MemoryFlushConfig()
        self._flush_triggered: Set[str] = set()
        self._flush_counts: Dict[str, int] = {}
    
    def should_flush(
        self,
        session_id: str,
        session_tokens: int,
        context_window: int
    ) -> bool:
        """Check if memory flush should be triggered.
        
        Args:
            session_id: Session identifier
            session_tokens: Current token count in session
            context_window: Maximum context window size
            
        Returns:
            True if flush should be triggered
        """
        if not self.config.enabled:
            return False
        
        # Already triggered in this compaction cycle
        if session_id in self._flush_triggered:
            return False
        
        # Calculate threshold
        threshold = (
            context_window
            - self.config.reserve_tokens_floor
            - self.config.soft_threshold_tokens
        )
        
        should_trigger = session_tokens >= threshold
        
        if should_trigger:
            logger.debug(
                f"Session {session_id} at {session_tokens} tokens, "
                f"threshold {threshold} (window {context_window})"
            )
        
        return should_trigger
    
    async def flush(self, agent: Any, session_id: str) -> Optional[str]:
        """Trigger memory flush for a session.
        
        Executes a silent agent turn to save important memories before
        context compression.
        
        Args:
            agent: Agent instance with execute method
            session_id: Session identifier
            
        Returns:
            Agent response or None if flush skipped/failed
        """
        if session_id in self._flush_triggered:
            logger.debug(f"Flush already triggered for session {session_id}")
            return None
        
        logger.info(f"Triggering memory flush for session {session_id}")
        
        # Construct flush prompt
        flush_prompt = f"""{self.config.system_prompt}

{self.config.user_prompt}"""
        
        try:
            # Execute silent memory save
            # Note: agent.execute_silent may not exist, using standard execute
            if hasattr(agent, 'execute_silent'):
                response = await agent.execute_silent(flush_prompt)
            elif hasattr(agent, 'message_loop'):
                # Standard Agent Zero execution
                response = await agent.message_loop(flush_prompt)
            else:
                logger.warning("Agent does not support execution methods")
                return None
            
            # Mark as triggered
            self._flush_triggered.add(session_id)
            
            # Update count
            self._flush_counts[session_id] = self._flush_counts.get(session_id, 0) + 1
            
            # Check response
            response_text = str(response) if response else ""
            if "NO_REPLY" not in response_text.upper():
                logger.info(f"Memory flush completed: {response_text[:100]}...")
            else:
                logger.debug(f"Memory flush: nothing to store for {session_id}")
            
            return response_text
            
        except Exception as e:
            logger.error(f"Memory flush failed for session {session_id}: {e}")
            return None
    
    def reset(self, session_id: str):
        """Reset flush state for a new compaction cycle.
        
        Call this after context compression to allow future flushes.
        
        Args:
            session_id: Session identifier
        """
        self._flush_triggered.discard(session_id)
        logger.debug(f"Reset flush state for session {session_id}")
    
    def reset_all(self):
        """Reset flush state for all sessions."""
        self._flush_triggered.clear()
        logger.debug("Reset all flush states")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get flush statistics.
        
        Returns:
            Dictionary with statistics
        """
        return {
            "enabled": self.config.enabled,
            "triggered_sessions": len(self._flush_triggered),
            "total_flushes": sum(self._flush_counts.values()),
            "flush_counts": dict(self._flush_counts)
        }
    
    def is_triggered(self, session_id: str) -> bool:
        """Check if flush was already triggered for a session.
        
        Args:
            session_id: Session identifier
            
        Returns:
            True if already triggered
        """
        return session_id in self._flush_triggered
    
    def __repr__(self) -> str:
        return (
            f"MemoryFlush(enabled={self.config.enabled}, "
            f"triggered={len(self._flush_triggered)})"
        )
