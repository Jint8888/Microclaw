"""
MessageDeduplicator Tests

File: tests/gateway/test_deduplicator.py
"""

import pytest
import time
import threading


class TestMessageDeduplicator:
    """Message deduplicator tests"""

    @pytest.fixture
    def deduplicator(self):
        from python.gateway.deduplicator import MessageDeduplicator
        return MessageDeduplicator(ttl_seconds=2, max_size=100)

    def test_first_message_not_duplicate(self, deduplicator):
        """First message should not be detected as duplicate"""
        assert deduplicator.is_duplicate("msg_1", "telegram") is False

    def test_same_message_is_duplicate(self, deduplicator):
        """Same message should be detected as duplicate"""
        deduplicator.is_duplicate("msg_1", "telegram")
        assert deduplicator.is_duplicate("msg_1", "telegram") is True

    def test_different_channel_not_duplicate(self, deduplicator):
        """Same ID from different channel should not be duplicate"""
        deduplicator.is_duplicate("msg_1", "telegram")
        assert deduplicator.is_duplicate("msg_1", "discord") is False

    def test_different_message_not_duplicate(self, deduplicator):
        """Different message ID should not be duplicate"""
        deduplicator.is_duplicate("msg_1", "telegram")
        assert deduplicator.is_duplicate("msg_2", "telegram") is False

    def test_expired_message_not_duplicate(self, deduplicator):
        """Expired message should not be detected as duplicate"""
        deduplicator.is_duplicate("msg_1", "telegram")
        time.sleep(2.5)  # Wait for TTL to expire
        assert deduplicator.is_duplicate("msg_1", "telegram") is False

    def test_max_size_limit(self, deduplicator):
        """Test max size limit is enforced"""
        # Add more than max_size messages
        for i in range(150):
            deduplicator.is_duplicate(f"msg_{i}", "telegram")
        
        assert deduplicator.size <= 100

    def test_clear(self, deduplicator):
        """Test clear method"""
        deduplicator.is_duplicate("msg_1", "telegram")
        deduplicator.is_duplicate("msg_2", "telegram")
        
        deduplicator.clear()
        
        assert deduplicator.size == 0
        # Should not be duplicate after clear
        assert deduplicator.is_duplicate("msg_1", "telegram") is False

    def test_thread_safety(self, deduplicator):
        """Test thread safety under concurrent access"""
        errors = []
        
        def check_duplicates(thread_id: int):
            try:
                for i in range(100):
                    deduplicator.is_duplicate(f"msg_{thread_id}_{i}", "telegram")
            except Exception as e:
                errors.append(e)
        
        threads = [
            threading.Thread(target=check_duplicates, args=(i,))
            for i in range(10)
        ]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(errors) == 0, f"Thread safety errors: {errors}"

    def test_size_property(self, deduplicator):
        """Test size property accuracy"""
        assert deduplicator.size == 0
        
        deduplicator.is_duplicate("msg_1", "telegram")
        assert deduplicator.size == 1
        
        deduplicator.is_duplicate("msg_2", "discord")
        assert deduplicator.size == 2
        
        # Duplicate should not increase size
        deduplicator.is_duplicate("msg_1", "telegram")
        assert deduplicator.size == 2
