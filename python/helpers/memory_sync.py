"""Incremental sync module for hash-based change detection.

This module provides MemorySync for tracking file changes using content hashing
and managing synchronization state. Only changed files are re-indexed.
"""

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import logging

# Prefer pysqlite3 for consistency
try:
    import pysqlite3 as sqlite3
except ImportError:
    import sqlite3

logger = logging.getLogger(__name__)


@dataclass
class SyncState:
    """State of a synced file.
    
    Attributes:
        filepath: Absolute file path
        content_hash: SHA-256 hash of file content
        synced_at: ISO format timestamp of last sync
        size_bytes: File size in bytes
    """
    filepath: str
    content_hash: str
    synced_at: str
    size_bytes: int


class MemorySync:
    """Incremental sync manager using content hashing.
    
    Tracks file content hashes to detect changes and avoid redundant
    re-indexing of unchanged files.
    
    Attributes:
        state_db_path: Path to SQLite database for sync state
    
    Example:
        >>> sync = MemorySync("memory/default/sync_state.db")
        >>> if sync.is_file_changed("docs/guide.md"):
        ...     # Re-index the file
        ...     sync.mark_synced("docs/guide.md")
    """
    
    def __init__(self, state_db_path: str):
        """Initialize MemorySync.
        
        Args:
            state_db_path: Path to SQLite database for sync state
        """
        self.state_db_path = Path(state_db_path)
        self.state_db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()
    
    def _init_db(self):
        """Initialize the sync state database."""
        self._conn = sqlite3.connect(str(self.state_db_path))
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_state (
                filepath TEXT PRIMARY KEY,
                content_hash TEXT NOT NULL,
                synced_at TEXT NOT NULL,
                size_bytes INTEGER NOT NULL
            )
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_synced_at ON sync_state(synced_at)
        """)
        self._conn.commit()
        logger.debug(f"Sync state database initialized at {self.state_db_path}")
    
    @staticmethod
    def compute_hash(filepath: str) -> str:
        """Compute SHA-256 hash of file content.
        
        Args:
            filepath: Path to file
            
        Returns:
            Hex-encoded SHA-256 hash
        """
        hasher = hashlib.sha256()
        with open(filepath, "rb") as f:
            while chunk := f.read(8192):
                hasher.update(chunk)
        return hasher.hexdigest()
    
    def get_state(self, filepath: str) -> Optional[SyncState]:
        """Get sync state for a file.
        
        Args:
            filepath: Path to file
            
        Returns:
            SyncState if found, None otherwise
        """
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT filepath, content_hash, synced_at, size_bytes FROM sync_state WHERE filepath = ?",
            (str(filepath),)
        )
        row = cursor.fetchone()
        
        if row:
            return SyncState(
                filepath=row[0],
                content_hash=row[1],
                synced_at=row[2],
                size_bytes=row[3]
            )
        return None
    
    def is_file_changed(self, filepath: str) -> bool:
        """Check if a file has changed since last sync.
        
        Args:
            filepath: Path to file
            
        Returns:
            True if file is new or changed, False if unchanged
        """
        filepath = str(filepath)
        
        if not os.path.exists(filepath):
            return False
        
        state = self.get_state(filepath)
        
        if state is None:
            # New file
            return True
        
        # Quick check: file size
        current_size = os.path.getsize(filepath)
        if current_size != state.size_bytes:
            return True
        
        # Full check: content hash
        current_hash = self.compute_hash(filepath)
        return current_hash != state.content_hash
    
    def mark_synced(self, filepath: str) -> SyncState:
        """Mark a file as synced (update its stored hash).
        
        Args:
            filepath: Path to file
            
        Returns:
            Updated SyncState
        """
        filepath = str(filepath)
        
        content_hash = self.compute_hash(filepath)
        size_bytes = os.path.getsize(filepath)
        synced_at = datetime.now().isoformat()
        
        self._conn.execute("""
            INSERT OR REPLACE INTO sync_state (filepath, content_hash, synced_at, size_bytes)
            VALUES (?, ?, ?, ?)
        """, (filepath, content_hash, synced_at, size_bytes))
        self._conn.commit()
        
        logger.debug(f"Marked synced: {filepath}")
        
        return SyncState(
            filepath=filepath,
            content_hash=content_hash,
            synced_at=synced_at,
            size_bytes=size_bytes
        )
    
    def mark_deleted(self, filepath: str) -> bool:
        """Mark a file as deleted (remove from sync state).
        
        Args:
            filepath: Path to file
            
        Returns:
            True if removed, False if not found
        """
        cursor = self._conn.cursor()
        cursor.execute("DELETE FROM sync_state WHERE filepath = ?", (str(filepath),))
        self._conn.commit()
        
        if cursor.rowcount > 0:
            logger.debug(f"Marked deleted: {filepath}")
            return True
        return False
    
    def get_changed_files(self, filepaths: List[str]) -> List[str]:
        """Filter list to only files that have changed.
        
        Args:
            filepaths: List of file paths to check
            
        Returns:
            List of changed file paths
        """
        return [fp for fp in filepaths if self.is_file_changed(fp)]
    
    def get_all_states(self) -> List[SyncState]:
        """Get all sync states.
        
        Returns:
            List of all SyncState objects
        """
        cursor = self._conn.cursor()
        cursor.execute("SELECT filepath, content_hash, synced_at, size_bytes FROM sync_state")
        
        return [
            SyncState(filepath=row[0], content_hash=row[1], synced_at=row[2], size_bytes=row[3])
            for row in cursor.fetchall()
        ]
    
    def clear(self):
        """Clear all sync state."""
        self._conn.execute("DELETE FROM sync_state")
        self._conn.commit()
        logger.info("Sync state cleared")
    
    def stats(self) -> Dict[str, int]:
        """Get sync statistics.
        
        Returns:
            Dictionary with statistics
        """
        cursor = self._conn.cursor()
        cursor.execute("SELECT COUNT(*), SUM(size_bytes) FROM sync_state")
        row = cursor.fetchone()
        
        return {
            "tracked_files": row[0] or 0,
            "total_bytes": row[1] or 0
        }
    
    def close(self):
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
    
    def __repr__(self) -> str:
        stats = self.stats()
        return f"MemorySync(tracked_files={stats['tracked_files']})"
    
    def __enter__(self) -> "MemorySync":
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
