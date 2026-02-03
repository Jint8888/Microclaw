"""
Agent Zero Process Registry

Tracks all processes started by Agent Zero, providing lifecycle management,
status tracking, and zombie process cleanup.

Usage:
    from python.helpers.process_registry import ProcessRegistry, ProcessEntry

    registry = ProcessRegistry.get_instance()

    # Register a process
    entry = ProcessEntry(command="pip install requests")
    registry.register(entry)
    registry.mark_running(entry.id, pid=12345)

    # Query running processes
    running = registry.list_running()

    # Cleanup zombies
    cleaned = registry.cleanup_zombies(max_age_seconds=1800)
"""

import time
import os
import signal
import threading
from typing import Dict, Optional, List, Callable, Any
from dataclasses import dataclass, field
from enum import Enum
import uuid


class ProcessStatus(str, Enum):
    """Process lifecycle status"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BACKGROUNDED = "backgrounded"
    TIMEOUT = "timeout"


@dataclass
class ProcessEntry:
    """
    Process entry representing a tracked process

    Attributes:
        id: Unique identifier for this process entry
        command: The command that was executed
        pid: Operating system process ID
        status: Current process status
        started_at: Unix timestamp when process started
        ended_at: Unix timestamp when process ended (if ended)
        exit_code: Process exit code (if ended)
        cwd: Working directory for the process
        metadata: Additional metadata dict
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    command: str = ""
    pid: Optional[int] = None
    status: ProcessStatus = ProcessStatus.PENDING
    started_at: float = 0
    ended_at: Optional[float] = None
    exit_code: Optional[int] = None
    cwd: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def duration_seconds(self) -> float:
        """Get process duration in seconds"""
        end = self.ended_at or time.time()
        return end - self.started_at if self.started_at else 0

    @property
    def duration_ms(self) -> float:
        """Get process duration in milliseconds"""
        return self.duration_seconds * 1000

    @property
    def is_running(self) -> bool:
        """Check if process is currently running"""
        return self.status in (ProcessStatus.RUNNING, ProcessStatus.BACKGROUNDED)

    @property
    def is_finished(self) -> bool:
        """Check if process has finished (success or failure)"""
        return self.status in (ProcessStatus.COMPLETED, ProcessStatus.FAILED, ProcessStatus.TIMEOUT)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation"""
        return {
            "id": self.id,
            "command": self.command,
            "pid": self.pid,
            "status": self.status.value,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "cwd": self.cwd,
            "metadata": self.metadata,
        }


class ProcessRegistry:
    """
    Process Registry - Singleton pattern

    Tracks all processes started by Agent Zero for lifecycle management
    and zombie cleanup.

    Thread-safe implementation using locks for concurrent access.

    Usage:
        registry = ProcessRegistry.get_instance()

        # Register and track process
        entry = ProcessEntry(command="npm install")
        registry.register(entry)
        registry.mark_running(entry.id, pid=12345)

        # When process completes
        registry.mark_completed(entry.id, exit_code=0)

        # Query status
        print(registry.get_status())

        # Cleanup old zombies
        registry.cleanup_zombies(max_age_seconds=3600)
    """

    _instance: Optional["ProcessRegistry"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._entries: Dict[str, ProcessEntry] = {}
                    instance._entry_lock = threading.Lock()
                    instance._exit_callbacks: List[Callable[[ProcessEntry], None]] = []
                    instance._max_history = 1000  # Max entries to keep in history
                    cls._instance = instance
        return cls._instance

    @classmethod
    def get_instance(cls) -> "ProcessRegistry":
        """Get the singleton instance"""
        return cls()

    def register(self, entry: ProcessEntry) -> str:
        """
        Register a new process entry

        Args:
            entry: ProcessEntry to register

        Returns:
            The entry ID
        """
        with self._entry_lock:
            entry.started_at = time.time()
            if entry.status == ProcessStatus.PENDING:
                entry.status = ProcessStatus.RUNNING
            self._entries[entry.id] = entry
            self._trim_history()
        return entry.id

    def get(self, entry_id: str) -> Optional[ProcessEntry]:
        """
        Get a process entry by ID

        Args:
            entry_id: The process entry ID

        Returns:
            ProcessEntry if found, None otherwise
        """
        with self._entry_lock:
            return self._entries.get(entry_id)

    def mark_running(self, entry_id: str, pid: int) -> bool:
        """
        Mark a process as running with its PID

        Args:
            entry_id: The process entry ID
            pid: Operating system process ID

        Returns:
            True if entry was found and updated
        """
        with self._entry_lock:
            if entry := self._entries.get(entry_id):
                entry.status = ProcessStatus.RUNNING
                entry.pid = pid
                return True
        return False

    def mark_completed(self, entry_id: str, exit_code: int = 0) -> bool:
        """
        Mark a process as completed

        Args:
            entry_id: The process entry ID
            exit_code: Process exit code

        Returns:
            True if entry was found and updated
        """
        with self._entry_lock:
            if entry := self._entries.get(entry_id):
                entry.status = ProcessStatus.COMPLETED
                entry.exit_code = exit_code
                entry.ended_at = time.time()
                self._notify_exit(entry)
                return True
        return False

    def mark_failed(self, entry_id: str, exit_code: int = 1, error: Optional[str] = None) -> bool:
        """
        Mark a process as failed

        Args:
            entry_id: The process entry ID
            exit_code: Process exit code
            error: Optional error message

        Returns:
            True if entry was found and updated
        """
        with self._entry_lock:
            if entry := self._entries.get(entry_id):
                entry.status = ProcessStatus.FAILED
                entry.exit_code = exit_code
                entry.ended_at = time.time()
                if error:
                    entry.metadata["error"] = error
                self._notify_exit(entry)
                return True
        return False

    def mark_timeout(self, entry_id: str) -> bool:
        """
        Mark a process as timed out

        Args:
            entry_id: The process entry ID

        Returns:
            True if entry was found and updated
        """
        with self._entry_lock:
            if entry := self._entries.get(entry_id):
                entry.status = ProcessStatus.TIMEOUT
                entry.exit_code = -1
                entry.ended_at = time.time()
                entry.metadata["timeout"] = True
                self._notify_exit(entry)
                return True
        return False

    def mark_backgrounded(self, entry_id: str) -> bool:
        """
        Mark a process as running in background

        Args:
            entry_id: The process entry ID

        Returns:
            True if entry was found and updated
        """
        with self._entry_lock:
            if entry := self._entries.get(entry_id):
                entry.status = ProcessStatus.BACKGROUNDED
                return True
        return False

    def list_running(self) -> List[ProcessEntry]:
        """
        List all currently running processes

        Returns:
            List of running ProcessEntry objects
        """
        with self._entry_lock:
            return [e for e in self._entries.values() if e.is_running]

    def list_all(self) -> List[ProcessEntry]:
        """
        List all tracked processes

        Returns:
            List of all ProcessEntry objects
        """
        with self._entry_lock:
            return list(self._entries.values())

    def list_by_status(self, status: ProcessStatus) -> List[ProcessEntry]:
        """
        List processes by status

        Args:
            status: ProcessStatus to filter by

        Returns:
            List of matching ProcessEntry objects
        """
        with self._entry_lock:
            return [e for e in self._entries.values() if e.status == status]

    def kill(self, entry_id: str, force: bool = False) -> bool:
        """
        Kill a process by entry ID

        Args:
            entry_id: The process entry ID
            force: Use SIGKILL instead of SIGTERM

        Returns:
            True if process was killed successfully
        """
        with self._entry_lock:
            entry = self._entries.get(entry_id)
            if not entry or not entry.pid:
                return False

            try:
                sig = signal.SIGKILL if force else signal.SIGTERM
                os.kill(entry.pid, sig)
                entry.status = ProcessStatus.FAILED
                entry.exit_code = -9 if force else -15
                entry.ended_at = time.time()
                entry.metadata["killed"] = True
                entry.metadata["signal"] = "SIGKILL" if force else "SIGTERM"
                self._notify_exit(entry)
                return True
            except ProcessLookupError:
                # Process already dead
                if entry.is_running:
                    entry.status = ProcessStatus.COMPLETED
                    entry.ended_at = time.time()
                return False
            except PermissionError:
                entry.metadata["kill_error"] = "Permission denied"
                return False
            except Exception as e:
                entry.metadata["kill_error"] = str(e)
                return False

    def cleanup_zombies(self, max_age_seconds: float = 3600) -> List[str]:
        """
        Cleanup zombie processes that have been running too long

        Args:
            max_age_seconds: Maximum age in seconds before killing

        Returns:
            List of cleaned up entry IDs
        """
        now = time.time()
        cleaned = []

        with self._entry_lock:
            for entry_id, entry in list(self._entries.items()):
                if entry.is_running and entry.started_at:
                    age = now - entry.started_at
                    if age > max_age_seconds:
                        # Release lock temporarily for kill
                        pass

        # Kill outside the lock to avoid deadlock
        entries_to_kill = []
        with self._entry_lock:
            now = time.time()
            for entry_id, entry in self._entries.items():
                if entry.is_running and entry.started_at:
                    age = now - entry.started_at
                    if age > max_age_seconds:
                        entries_to_kill.append(entry_id)

        for entry_id in entries_to_kill:
            if self.kill(entry_id, force=True):
                cleaned.append(entry_id)
                # Mark as timeout
                with self._entry_lock:
                    if entry := self._entries.get(entry_id):
                        entry.metadata["zombie_cleanup"] = True

        return cleaned

    def get_status(self) -> Dict[str, Any]:
        """
        Get registry status summary

        Returns:
            Dict with status information
        """
        with self._entry_lock:
            running = [e for e in self._entries.values() if e.status == ProcessStatus.RUNNING]
            backgrounded = [e for e in self._entries.values() if e.status == ProcessStatus.BACKGROUNDED]
            completed = [e for e in self._entries.values() if e.status == ProcessStatus.COMPLETED]
            failed = [e for e in self._entries.values() if e.status == ProcessStatus.FAILED]

            return {
                "total": len(self._entries),
                "running": len(running),
                "backgrounded": len(backgrounded),
                "completed": len(completed),
                "failed": len(failed),
                "running_pids": [e.pid for e in running if e.pid],
                "backgrounded_pids": [e.pid for e in backgrounded if e.pid],
            }

    def on_exit(self, callback: Callable[[ProcessEntry], None]) -> None:
        """
        Register a callback for process exit events

        Args:
            callback: Function to call when a process exits
        """
        self._exit_callbacks.append(callback)

    def remove_exit_callback(self, callback: Callable[[ProcessEntry], None]) -> bool:
        """
        Remove an exit callback

        Args:
            callback: The callback to remove

        Returns:
            True if callback was found and removed
        """
        try:
            self._exit_callbacks.remove(callback)
            return True
        except ValueError:
            return False

    def clear_history(self, keep_running: bool = True) -> int:
        """
        Clear process history

        Args:
            keep_running: Whether to keep running processes

        Returns:
            Number of entries cleared
        """
        with self._entry_lock:
            if keep_running:
                running = {k: v for k, v in self._entries.items() if v.is_running}
                cleared = len(self._entries) - len(running)
                self._entries = running
            else:
                cleared = len(self._entries)
                self._entries = {}
            return cleared

    def _notify_exit(self, entry: ProcessEntry) -> None:
        """Notify exit callbacks"""
        for callback in self._exit_callbacks:
            try:
                callback(entry)
            except Exception:
                pass  # Don't let callback errors break the registry

    def _trim_history(self) -> None:
        """Trim old entries if we exceed max history"""
        if len(self._entries) <= self._max_history:
            return

        # Sort by ended_at (finished entries first), then by started_at
        finished = [(k, v) for k, v in self._entries.items() if v.is_finished]
        finished.sort(key=lambda x: x[1].ended_at or 0)

        # Remove oldest finished entries
        to_remove = len(self._entries) - self._max_history
        for entry_id, _ in finished[:to_remove]:
            del self._entries[entry_id]


# Convenience function
def get_registry() -> ProcessRegistry:
    """Get the global ProcessRegistry instance"""
    return ProcessRegistry.get_instance()
