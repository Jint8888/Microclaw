"""
Unit tests for process_registry.py

Run with: pytest tests/test_process_registry.py -v
"""

import pytest
import time
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from python.helpers.process_registry import (
    ProcessRegistry,
    ProcessEntry,
    ProcessStatus,
    get_registry,
)


class TestProcessStatus:
    """Tests for ProcessStatus enum"""

    def test_status_values(self):
        """Test that all status values are strings"""
        for status in ProcessStatus:
            assert isinstance(status.value, str)

    def test_status_pending(self):
        """Test PENDING status value"""
        assert ProcessStatus.PENDING.value == "pending"

    def test_status_running(self):
        """Test RUNNING status value"""
        assert ProcessStatus.RUNNING.value == "running"

    def test_status_completed(self):
        """Test COMPLETED status value"""
        assert ProcessStatus.COMPLETED.value == "completed"


class TestProcessEntry:
    """Tests for ProcessEntry dataclass"""

    def test_entry_creation(self):
        """Test creating a ProcessEntry"""
        entry = ProcessEntry(command="echo hello")
        assert entry.command == "echo hello"
        assert entry.status == ProcessStatus.PENDING
        assert entry.id is not None

    def test_entry_id_unique(self):
        """Test that entry IDs are unique"""
        entry1 = ProcessEntry(command="cmd1")
        entry2 = ProcessEntry(command="cmd2")
        assert entry1.id != entry2.id

    def test_entry_duration(self):
        """Test duration calculation"""
        entry = ProcessEntry(command="test")
        entry.started_at = time.time() - 1.0  # 1 second ago
        assert entry.duration_seconds >= 1.0

    def test_entry_duration_ms(self):
        """Test duration in milliseconds"""
        entry = ProcessEntry(command="test")
        entry.started_at = time.time() - 0.5  # 0.5 seconds ago
        assert entry.duration_ms >= 500

    def test_entry_is_running(self):
        """Test is_running property"""
        entry = ProcessEntry(command="test")
        entry.status = ProcessStatus.RUNNING
        assert entry.is_running is True

        entry.status = ProcessStatus.COMPLETED
        assert entry.is_running is False

    def test_entry_is_finished(self):
        """Test is_finished property"""
        entry = ProcessEntry(command="test")
        entry.status = ProcessStatus.RUNNING
        assert entry.is_finished is False

        entry.status = ProcessStatus.COMPLETED
        assert entry.is_finished is True

    def test_entry_to_dict(self):
        """Test to_dict method"""
        entry = ProcessEntry(command="test", pid=12345)
        entry.started_at = time.time()
        d = entry.to_dict()

        assert d["command"] == "test"
        assert d["pid"] == 12345
        assert "id" in d
        assert "status" in d


class TestProcessRegistry:
    """Tests for ProcessRegistry class"""

    def setup_method(self):
        """Clear registry before each test"""
        registry = ProcessRegistry.get_instance()
        registry.clear_history(keep_running=False)

    def test_singleton_pattern(self):
        """Test that registry is a singleton"""
        r1 = ProcessRegistry.get_instance()
        r2 = ProcessRegistry.get_instance()
        assert r1 is r2

    def test_get_registry_function(self):
        """Test get_registry convenience function"""
        r1 = get_registry()
        r2 = ProcessRegistry.get_instance()
        assert r1 is r2

    def test_register_entry(self):
        """Test registering a process entry"""
        registry = get_registry()
        entry = ProcessEntry(command="test command")

        entry_id = registry.register(entry)

        assert entry_id == entry.id
        assert entry.started_at > 0
        assert entry.status == ProcessStatus.RUNNING

    def test_get_entry(self):
        """Test getting a registered entry"""
        registry = get_registry()
        entry = ProcessEntry(command="test")
        registry.register(entry)

        retrieved = registry.get(entry.id)
        assert retrieved is not None
        assert retrieved.command == "test"

    def test_get_nonexistent_entry(self):
        """Test getting non-existent entry returns None"""
        registry = get_registry()
        result = registry.get("nonexistent-id")
        assert result is None

    def test_mark_running(self):
        """Test marking entry as running with PID"""
        registry = get_registry()
        entry = ProcessEntry(command="test")
        registry.register(entry)

        result = registry.mark_running(entry.id, pid=12345)

        assert result is True
        assert entry.pid == 12345
        assert entry.status == ProcessStatus.RUNNING

    def test_mark_completed(self):
        """Test marking entry as completed"""
        registry = get_registry()
        entry = ProcessEntry(command="test")
        registry.register(entry)

        result = registry.mark_completed(entry.id, exit_code=0)

        assert result is True
        assert entry.status == ProcessStatus.COMPLETED
        assert entry.exit_code == 0
        assert entry.ended_at is not None

    def test_mark_failed(self):
        """Test marking entry as failed"""
        registry = get_registry()
        entry = ProcessEntry(command="test")
        registry.register(entry)

        result = registry.mark_failed(entry.id, exit_code=1, error="Test error")

        assert result is True
        assert entry.status == ProcessStatus.FAILED
        assert entry.exit_code == 1
        assert entry.metadata.get("error") == "Test error"

    def test_mark_timeout(self):
        """Test marking entry as timed out"""
        registry = get_registry()
        entry = ProcessEntry(command="test")
        registry.register(entry)

        result = registry.mark_timeout(entry.id)

        assert result is True
        assert entry.status == ProcessStatus.TIMEOUT
        assert entry.metadata.get("timeout") is True

    def test_mark_backgrounded(self):
        """Test marking entry as backgrounded"""
        registry = get_registry()
        entry = ProcessEntry(command="test")
        registry.register(entry)

        result = registry.mark_backgrounded(entry.id)

        assert result is True
        assert entry.status == ProcessStatus.BACKGROUNDED

    def test_list_running(self):
        """Test listing running processes"""
        registry = get_registry()

        entry1 = ProcessEntry(command="cmd1")
        entry2 = ProcessEntry(command="cmd2")
        entry3 = ProcessEntry(command="cmd3")

        registry.register(entry1)
        registry.register(entry2)
        registry.register(entry3)

        registry.mark_completed(entry2.id)

        running = registry.list_running()
        assert len(running) == 2

    def test_list_by_status(self):
        """Test listing by status"""
        registry = get_registry()

        entry1 = ProcessEntry(command="cmd1")
        entry2 = ProcessEntry(command="cmd2")

        registry.register(entry1)
        registry.register(entry2)
        registry.mark_completed(entry1.id)

        completed = registry.list_by_status(ProcessStatus.COMPLETED)
        assert len(completed) == 1
        assert completed[0].id == entry1.id

    def test_get_status(self):
        """Test get_status summary"""
        registry = get_registry()

        entry1 = ProcessEntry(command="cmd1")
        entry2 = ProcessEntry(command="cmd2")

        registry.register(entry1)
        registry.register(entry2)
        registry.mark_completed(entry1.id)

        status = registry.get_status()

        assert status["total"] == 2
        assert status["running"] == 1
        assert status["completed"] == 1

    def test_exit_callback(self):
        """Test exit callback is called"""
        registry = get_registry()
        callback_called = []

        def on_exit(entry):
            callback_called.append(entry.id)

        registry.on_exit(on_exit)

        entry = ProcessEntry(command="test")
        registry.register(entry)
        registry.mark_completed(entry.id)

        assert entry.id in callback_called

        # Cleanup
        registry.remove_exit_callback(on_exit)

    def test_clear_history(self):
        """Test clearing history"""
        registry = get_registry()

        entry1 = ProcessEntry(command="cmd1")
        entry2 = ProcessEntry(command="cmd2")

        registry.register(entry1)
        registry.register(entry2)
        registry.mark_completed(entry1.id)

        # Clear but keep running
        cleared = registry.clear_history(keep_running=True)

        assert cleared == 1  # Only completed entry cleared
        assert registry.get(entry2.id) is not None  # Running entry still exists


class TestCleanupZombies:
    """Tests for zombie cleanup functionality"""

    def setup_method(self):
        registry = ProcessRegistry.get_instance()
        registry.clear_history(keep_running=False)

    def test_cleanup_old_processes(self):
        """Test that old processes are cleaned up"""
        registry = get_registry()

        entry = ProcessEntry(command="old process")
        registry.register(entry)
        # Simulate old process by backdating started_at
        entry.started_at = time.time() - 3700  # Over 1 hour ago

        cleaned = registry.cleanup_zombies(max_age_seconds=3600)

        # Process should be marked for cleanup (but may not actually kill without PID)
        assert entry.id in cleaned or entry.status in (ProcessStatus.FAILED, ProcessStatus.COMPLETED)

    def test_cleanup_preserves_recent(self):
        """Test that recent processes are not cleaned up"""
        registry = get_registry()

        entry = ProcessEntry(command="recent process")
        registry.register(entry)
        # Process just started, should not be cleaned

        cleaned = registry.cleanup_zombies(max_age_seconds=3600)

        assert entry.id not in cleaned
        assert entry.status == ProcessStatus.RUNNING


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
