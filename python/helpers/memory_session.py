"""Session persistence module for conversation history management.

This module provides SessionManager for persisting and retrieving conversation
history using JSONL format. Sessions are stored as files with one message per
line, enabling efficient append operations and incremental loading.
"""

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class SessionMessage:
    """A single message in a session.
    
    Attributes:
        session_id: Unique session identifier
        role: Message role (user, assistant, system)
        content: Message content
        timestamp: ISO format timestamp
        metadata: Additional message metadata
    """
    session_id: str
    role: str
    content: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionMessage":
        """Create from dictionary."""
        return cls(**data)


class SessionManager:
    """Session persistence manager.
    
    Manages conversation history using JSONL files for efficient
    append-only storage and incremental loading.
    
    Attributes:
        sessions_dir: Directory for session files
        _cache: In-memory cache of loaded sessions
    
    Example:
        >>> manager = SessionManager("memory/default/sessions")
        >>> await manager.save_message("sess-1", "user", "Hello!")
        >>> messages = await manager.load_session("sess-1")
        >>> print(len(messages))
        1
    """
    
    def __init__(self, sessions_dir: str):
        """Initialize SessionManager.
        
        Args:
            sessions_dir: Directory path for session JSONL files
        """
        self.sessions_dir = Path(sessions_dir)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self._cache: Dict[str, List[SessionMessage]] = {}
        logger.info(f"SessionManager initialized at {sessions_dir}")
    
    def _get_session_path(self, session_id: str) -> Path:
        """Get the file path for a session.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Path to session JSONL file
        """
        # Sanitize session_id for safe filename
        safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_id)
        return self.sessions_dir / f"{safe_id}.jsonl"
    
    async def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> SessionMessage:
        """Save a message to a session.
        
        Appends the message to the session's JSONL file and updates the cache.
        
        Args:
            session_id: Session identifier
            role: Message role (user, assistant, system)
            content: Message content
            metadata: Optional additional metadata
            
        Returns:
            The saved SessionMessage
        """
        message = SessionMessage(
            session_id=session_id,
            role=role,
            content=content,
            metadata=metadata or {}
        )
        
        # Append to file
        session_path = self._get_session_path(session_id)
        with open(session_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(message.to_dict(), ensure_ascii=False) + "\n")
        
        # Update cache
        if session_id not in self._cache:
            self._cache[session_id] = []
        self._cache[session_id].append(message)
        
        logger.debug(f"Saved message to session {session_id}: {role}")
        return message
    
    async def load_session(
        self,
        session_id: str,
        use_cache: bool = True
    ) -> List[SessionMessage]:
        """Load all messages from a session.
        
        Args:
            session_id: Session identifier
            use_cache: Whether to use cached data if available
            
        Returns:
            List of SessionMessage objects
        """
        # Check cache first
        if use_cache and session_id in self._cache:
            return self._cache[session_id]
        
        session_path = self._get_session_path(session_id)
        
        if not session_path.exists():
            return []
        
        messages = []
        with open(session_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        data = json.loads(line)
                        messages.append(SessionMessage.from_dict(data))
                    except json.JSONDecodeError as e:
                        logger.warning(f"Skipping malformed line in {session_id}: {e}")
        
        # Update cache
        self._cache[session_id] = messages
        
        return messages
    
    async def get_recent_messages(
        self,
        session_id: str,
        limit: int = 10
    ) -> List[SessionMessage]:
        """Get the most recent messages from a session.
        
        Args:
            session_id: Session identifier
            limit: Maximum number of messages to return
            
        Returns:
            List of most recent SessionMessage objects
        """
        messages = await self.load_session(session_id)
        return messages[-limit:] if messages else []
    
    async def search_sessions(
        self,
        query: str,
        session_ids: Optional[List[str]] = None,
        limit: int = 10
    ) -> List[SessionMessage]:
        """Search for messages containing query text.
        
        Simple text-based search across sessions.
        
        Args:
            query: Search query string
            session_ids: Optional list of session IDs to search (None = all)
            limit: Maximum results to return
            
        Returns:
            List of matching SessionMessage objects
        """
        query_lower = query.lower()
        results = []
        
        # Get session IDs to search
        if session_ids is None:
            session_ids = self.list_sessions()
        
        for session_id in session_ids:
            messages = await self.load_session(session_id)
            for msg in messages:
                if query_lower in msg.content.lower():
                    results.append(msg)
                    if len(results) >= limit:
                        return results
        
        return results
    
    def list_sessions(self) -> List[str]:
        """List all session IDs.
        
        Returns:
            List of session identifiers
        """
        sessions = []
        for path in self.sessions_dir.glob("*.jsonl"):
            sessions.append(path.stem)
        return sessions
    
    async def delete_session(self, session_id: str) -> bool:
        """Delete a session and its file.
        
        Args:
            session_id: Session identifier
            
        Returns:
            True if deleted, False if not found
        """
        session_path = self._get_session_path(session_id)
        
        # Remove from cache
        self._cache.pop(session_id, None)
        
        # Delete file
        if session_path.exists():
            session_path.unlink()
            logger.info(f"Deleted session {session_id}")
            return True
        
        return False
    
    def clear_cache(self):
        """Clear the in-memory cache."""
        self._cache.clear()
    
    async def get_session_stats(self, session_id: str) -> Dict[str, Any]:
        """Get statistics for a session.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Dictionary with session statistics
        """
        messages = await self.load_session(session_id)
        
        if not messages:
            return {"exists": False}
        
        role_counts = {}
        for msg in messages:
            role_counts[msg.role] = role_counts.get(msg.role, 0) + 1
        
        return {
            "exists": True,
            "message_count": len(messages),
            "role_counts": role_counts,
            "first_message": messages[0].timestamp if messages else None,
            "last_message": messages[-1].timestamp if messages else None,
        }
    
    def __repr__(self) -> str:
        return f"SessionManager(sessions_dir='{self.sessions_dir}')"
