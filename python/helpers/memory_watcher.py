"""File system watcher module for automatic memory index updates.

This module provides MemoryFileWatcher for monitoring knowledge base directories
and triggering index updates when files change. Uses debouncing to batch
rapid changes and avoid redundant updates.
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from threading import Thread, Event
from typing import Callable, List, Optional, Set
import fnmatch

logger = logging.getLogger(__name__)

# Try to import watchdog
try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileSystemEvent
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    Observer = None
    FileSystemEventHandler = object
    FileSystemEvent = None


class MemoryFileWatcherError(Exception):
    """Base exception for MemoryFileWatcher errors."""
    pass


class WatchdogNotAvailableError(MemoryFileWatcherError):
    """Raised when watchdog is not installed."""
    pass


class DebouncedHandler(FileSystemEventHandler):
    """File event handler with debouncing.
    
    Collects file changes and triggers callback after debounce period.
    """
    
    def __init__(
        self,
        callback: Callable[[Set[str]], None],
        debounce_seconds: float = 2.0,
        file_patterns: Optional[List[str]] = None
    ):
        """Initialize handler.
        
        Args:
            callback: Function to call with changed file paths
            debounce_seconds: Seconds to wait before triggering callback
            file_patterns: Glob patterns for files to watch (e.g., ["*.md", "*.txt"])
        """
        super().__init__()
        self.callback = callback
        self.debounce_seconds = debounce_seconds
        self.file_patterns = file_patterns or ["*.md", "*.txt"]
        self._pending_changes: Set[str] = set()
        self._debounce_timer: Optional[asyncio.TimerHandle] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_event = Event()
    
    def set_loop(self, loop: asyncio.AbstractEventLoop):
        """Set the event loop for scheduling callbacks."""
        self._loop = loop
    
    def _matches_pattern(self, filepath: str) -> bool:
        """Check if filepath matches any of the file patterns."""
        filename = Path(filepath).name
        return any(fnmatch.fnmatch(filename, pattern) for pattern in self.file_patterns)
    
    def _schedule_callback(self):
        """Schedule the debounced callback."""
        if self._loop is None:
            logger.warning("Event loop not set, cannot schedule callback")
            return
        
        def trigger():
            if self._pending_changes:
                changes = self._pending_changes.copy()
                self._pending_changes.clear()
                self._debounce_timer = None
                self.callback(changes)
        
        # Cancel existing timer
        if self._debounce_timer is not None:
            self._debounce_timer.cancel()
        
        # Schedule new timer
        self._debounce_timer = self._loop.call_later(
            self.debounce_seconds,
            trigger
        )
    
    def on_modified(self, event: FileSystemEvent):
        """Handle file modification events."""
        if event.is_directory:
            return
        
        if self._matches_pattern(event.src_path):
            self._pending_changes.add(event.src_path)
            if self._loop:
                self._loop.call_soon_threadsafe(self._schedule_callback)
    
    def on_created(self, event: FileSystemEvent):
        """Handle file creation events."""
        if event.is_directory:
            return
        
        if self._matches_pattern(event.src_path):
            self._pending_changes.add(event.src_path)
            if self._loop:
                self._loop.call_soon_threadsafe(self._schedule_callback)
    
    def on_deleted(self, event: FileSystemEvent):
        """Handle file deletion events."""
        if event.is_directory:
            return
        
        if self._matches_pattern(event.src_path):
            # Mark as deleted with special prefix
            self._pending_changes.add(f"DELETED:{event.src_path}")
            if self._loop:
                self._loop.call_soon_threadsafe(self._schedule_callback)


class MemoryFileWatcher:
    """File system watcher for knowledge base directories.
    
    Monitors directories for file changes and triggers index updates
    with debouncing to batch rapid changes.
    
    Attributes:
        watch_dirs: List of directories to watch
        debounce_seconds: Seconds to wait before triggering callback
        file_patterns: Glob patterns for files to watch
    
    Example:
        >>> async def on_change(files):
        ...     print(f"Files changed: {files}")
        >>> watcher = MemoryFileWatcher(
        ...     watch_dirs=["knowledge/default"],
        ...     on_change_callback=on_change
        ... )
        >>> watcher.start()
        >>> # ... files change ...
        >>> watcher.stop()
    """
    
    def __init__(
        self,
        watch_dirs: List[str],
        on_change_callback: Callable[[Set[str]], None],
        debounce_seconds: float = 2.0,
        file_patterns: Optional[List[str]] = None
    ):
        """Initialize MemoryFileWatcher.
        
        Args:
            watch_dirs: List of directory paths to monitor
            on_change_callback: Function called with set of changed file paths
            debounce_seconds: Seconds to wait before triggering callback
            file_patterns: Glob patterns for files to watch
            
        Raises:
            WatchdogNotAvailableError: If watchdog is not installed
        """
        if not WATCHDOG_AVAILABLE:
            raise WatchdogNotAvailableError(
                "watchdog is not installed. Install with: pip install watchdog"
            )
        
        self.watch_dirs = [Path(d) for d in watch_dirs]
        self.debounce_seconds = debounce_seconds
        self.file_patterns = file_patterns or ["*.md", "*.txt"]
        self._callback = on_change_callback
        
        self._observer: Optional[Observer] = None
        self._handler: Optional[DebouncedHandler] = None
        self._running = False
    
    def start(self, loop: Optional[asyncio.AbstractEventLoop] = None):
        """Start watching directories.
        
        Args:
            loop: Event loop for scheduling callbacks (uses current if None)
        """
        if self._running:
            logger.warning("Watcher already running")
            return
        
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
        
        self._handler = DebouncedHandler(
            callback=self._callback,
            debounce_seconds=self.debounce_seconds,
            file_patterns=self.file_patterns
        )
        self._handler.set_loop(loop)
        
        self._observer = Observer()
        
        for watch_dir in self.watch_dirs:
            if watch_dir.exists():
                self._observer.schedule(
                    self._handler,
                    str(watch_dir),
                    recursive=True
                )
                logger.info(f"Watching directory: {watch_dir}")
            else:
                logger.warning(f"Watch directory does not exist: {watch_dir}")
        
        self._observer.start()
        self._running = True
        logger.info("MemoryFileWatcher started")
    
    def stop(self):
        """Stop watching directories."""
        if not self._running:
            return
        
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5.0)
            self._observer = None
        
        self._handler = None
        self._running = False
        logger.info("MemoryFileWatcher stopped")
    
    @property
    def is_running(self) -> bool:
        """Return whether the watcher is running."""
        return self._running
    
    def add_watch_dir(self, path: str):
        """Add a directory to watch.
        
        Args:
            path: Directory path to add
        """
        watch_path = Path(path)
        if watch_path not in self.watch_dirs:
            self.watch_dirs.append(watch_path)
            
            if self._running and self._observer and self._handler:
                if watch_path.exists():
                    self._observer.schedule(
                        self._handler,
                        str(watch_path),
                        recursive=True
                    )
                    logger.info(f"Added watch directory: {watch_path}")
    
    def __repr__(self) -> str:
        return (
            f"MemoryFileWatcher("
            f"dirs={[str(d) for d in self.watch_dirs]}, "
            f"running={self._running})"
        )
    
    def __enter__(self) -> "MemoryFileWatcher":
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
