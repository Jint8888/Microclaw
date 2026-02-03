"""Session policy module for per-session configuration overrides.

This module provides SessionPolicy and SessionPolicyManager for managing
per-session configuration such as model overrides, log levels, and context limits.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class SessionPolicy:
    """Session policy configuration.
    
    Allows per-session overrides for model, logging, and context settings.
    
    Attributes:
        session_id: Session identifier
        model_override: Override LLM model for this session
        fallback_model: Fallback model if primary fails
        log_level_override: Override log level (DEBUG, INFO, WARNING, ERROR)
        max_context_messages: Maximum messages in context
        send_mode: Message send mode (default, immediate, batched, silent)
        metadata: Additional custom metadata
    """
    session_id: str
    model_override: Optional[str] = None
    fallback_model: Optional[str] = None
    log_level_override: Optional[str] = None
    max_context_messages: int = 50
    send_mode: str = "default"
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def get_effective_model(self, default_model: str) -> str:
        """Get effective model considering overrides.
        
        Args:
            default_model: Default model to use if no override
            
        Returns:
            Model name to use
        """
        return self.model_override or default_model
    
    def get_effective_log_level(self, default_level: str = "INFO") -> str:
        """Get effective log level considering overrides.
        
        Args:
            default_level: Default level to use if no override
            
        Returns:
            Log level string
        """
        return self.log_level_override or default_level
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "session_id": self.session_id,
            "model_override": self.model_override,
            "fallback_model": self.fallback_model,
            "log_level_override": self.log_level_override,
            "max_context_messages": self.max_context_messages,
            "send_mode": self.send_mode,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionPolicy":
        """Create from dictionary."""
        return cls(**data)


class SessionPolicyManager:
    """Manager for session policies.
    
    Provides centralized management of per-session configuration overrides.
    
    Example:
        >>> manager = SessionPolicyManager()
        >>> manager.set_policy("sess-1", model_override="gpt-4o")
        >>> policy = manager.get_policy("sess-1")
        >>> print(policy.model_override)
        gpt-4o
    """
    
    def __init__(self):
        """Initialize SessionPolicyManager."""
        self._policies: Dict[str, SessionPolicy] = {}
        self._default_policy = SessionPolicy(session_id="__default__")
    
    def get_policy(self, session_id: str) -> SessionPolicy:
        """Get policy for a session.
        
        Args:
            session_id: Session identifier
            
        Returns:
            SessionPolicy (session-specific or default)
        """
        return self._policies.get(session_id, self._default_policy)
    
    def set_policy(
        self,
        session_id: str,
        model_override: Optional[str] = None,
        fallback_model: Optional[str] = None,
        log_level_override: Optional[str] = None,
        max_context_messages: int = 50,
        send_mode: str = "default",
        **metadata
    ) -> SessionPolicy:
        """Set policy for a session.
        
        Args:
            session_id: Session identifier
            model_override: Override LLM model
            fallback_model: Fallback model
            log_level_override: Override log level
            max_context_messages: Maximum context messages
            send_mode: Message send mode
            **metadata: Additional metadata
            
        Returns:
            Created SessionPolicy
        """
        policy = SessionPolicy(
            session_id=session_id,
            model_override=model_override,
            fallback_model=fallback_model,
            log_level_override=log_level_override,
            max_context_messages=max_context_messages,
            send_mode=send_mode,
            metadata=metadata
        )
        
        self._policies[session_id] = policy
        logger.debug(f"Set policy for session {session_id}")
        
        return policy
    
    def update_policy(self, session_id: str, **updates) -> Optional[SessionPolicy]:
        """Update existing policy fields.
        
        Args:
            session_id: Session identifier
            **updates: Fields to update
            
        Returns:
            Updated policy or None if not found
        """
        if session_id not in self._policies:
            return None
        
        policy = self._policies[session_id]
        
        for key, value in updates.items():
            if hasattr(policy, key):
                setattr(policy, key, value)
            else:
                policy.metadata[key] = value
        
        logger.debug(f"Updated policy for session {session_id}")
        return policy
    
    def clear_policy(self, session_id: str) -> bool:
        """Clear policy for a session.
        
        Args:
            session_id: Session identifier
            
        Returns:
            True if removed, False if not found
        """
        if session_id in self._policies:
            del self._policies[session_id]
            logger.debug(f"Cleared policy for session {session_id}")
            return True
        return False
    
    def get_effective_model(self, session_id: str, default_model: str) -> str:
        """Get effective model for a session.
        
        Args:
            session_id: Session identifier
            default_model: Default model to use
            
        Returns:
            Model name to use
        """
        policy = self.get_policy(session_id)
        return policy.get_effective_model(default_model)
    
    def list_sessions(self) -> list:
        """List all sessions with custom policies.
        
        Returns:
            List of session IDs
        """
        return list(self._policies.keys())
    
    def get_all_policies(self) -> Dict[str, SessionPolicy]:
        """Get all policies.
        
        Returns:
            Dictionary of session_id to SessionPolicy
        """
        return dict(self._policies)
    
    def set_default_policy(
        self,
        max_context_messages: int = 50,
        send_mode: str = "default"
    ):
        """Set default policy values.
        
        Args:
            max_context_messages: Default max context messages
            send_mode: Default send mode
        """
        self._default_policy = SessionPolicy(
            session_id="__default__",
            max_context_messages=max_context_messages,
            send_mode=send_mode
        )
    
    def __repr__(self) -> str:
        return f"SessionPolicyManager(sessions={len(self._policies)})"


# Global instance for convenience
_policy_manager: Optional[SessionPolicyManager] = None


def get_policy_manager() -> SessionPolicyManager:
    """Get global SessionPolicyManager instance.
    
    Returns:
        SessionPolicyManager singleton
    """
    global _policy_manager
    if _policy_manager is None:
        _policy_manager = SessionPolicyManager()
    return _policy_manager


def get_session_policy(session_id: str) -> SessionPolicy:
    """Get policy for a session.
    
    Convenience function using global manager.
    
    Args:
        session_id: Session identifier
        
    Returns:
        SessionPolicy
    """
    return get_policy_manager().get_policy(session_id)


def set_session_policy(session_id: str, **kwargs) -> SessionPolicy:
    """Set policy for a session.
    
    Convenience function using global manager.
    
    Args:
        session_id: Session identifier
        **kwargs: Policy settings
        
    Returns:
        Created SessionPolicy
    """
    return get_policy_manager().set_policy(session_id, **kwargs)
