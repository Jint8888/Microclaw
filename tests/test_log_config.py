"""
Unit tests for log_config.py

Run with: pytest tests/test_log_config.py -v
"""

import pytest
import logging
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from python.helpers.log_config import (
    configure_logging,
    get_logger,
    set_subsystem_level,
    get_subsystem_level,
    log_duration,
    is_configured,
    reset_configuration,
    LogSubsystem,
    RedactionFilter,
)


class TestLogSubsystem:
    """Tests for LogSubsystem enum"""

    def test_subsystem_values(self):
        """Test that all subsystems have correct prefix"""
        for subsystem in LogSubsystem:
            assert subsystem.value.startswith("a0.")

    def test_subsystem_agent(self):
        """Test AGENT subsystem value"""
        assert LogSubsystem.AGENT.value == "a0.agent"

    def test_subsystem_tool(self):
        """Test TOOL subsystem value"""
        assert LogSubsystem.TOOL.value == "a0.tool"


class TestConfigureLogging:
    """Tests for configure_logging function"""

    def setup_method(self):
        """Reset configuration before each test"""
        reset_configuration()

    def teardown_method(self):
        """Cleanup after each test"""
        reset_configuration()

    def test_configure_once(self):
        """Test that configuration only happens once"""
        assert not is_configured()
        configure_logging(level="INFO")
        assert is_configured()

        # Second call should be ignored
        configure_logging(level="DEBUG")
        assert is_configured()

    def test_configure_with_level(self):
        """Test configuration with different log levels"""
        configure_logging(level="DEBUG")
        root = logging.getLogger("a0")
        assert root.level == logging.DEBUG

    def test_configure_without_console(self):
        """Test configuration without console output"""
        configure_logging(enable_console=False)
        root = logging.getLogger("a0")
        # Should have no handlers if console is disabled and no file
        console_handlers = [h for h in root.handlers if isinstance(h, logging.StreamHandler)]
        assert len(console_handlers) == 0

    def test_configure_with_custom_format(self):
        """Test configuration with custom format string"""
        custom_format = "%(levelname)s - %(message)s"
        configure_logging(format_string=custom_format)
        root = logging.getLogger("a0")
        assert len(root.handlers) > 0


class TestGetLogger:
    """Tests for get_logger function"""

    def setup_method(self):
        reset_configuration()
        configure_logging(level="DEBUG", enable_redaction=False)

    def teardown_method(self):
        reset_configuration()

    def test_get_logger_returns_logger(self):
        """Test that get_logger returns a Logger instance"""
        log = get_logger(LogSubsystem.AGENT)
        assert isinstance(log, logging.Logger)

    def test_get_logger_correct_name(self):
        """Test that logger has correct name"""
        log = get_logger(LogSubsystem.TOOL)
        assert log.name == "a0.tool"

    def test_get_logger_with_context(self):
        """Test get_logger with context dict"""
        log = get_logger(LogSubsystem.AGENT, context={"session_id": "test123"})
        # Should return a LoggerAdapter
        assert hasattr(log, 'extra')


class TestSetSubsystemLevel:
    """Tests for set_subsystem_level function"""

    def setup_method(self):
        reset_configuration()
        configure_logging(level="INFO")

    def teardown_method(self):
        reset_configuration()

    def test_set_level_debug(self):
        """Test setting subsystem level to DEBUG"""
        set_subsystem_level(LogSubsystem.TOOL, "DEBUG")
        level = get_subsystem_level(LogSubsystem.TOOL)
        assert level == logging.DEBUG

    def test_set_level_warning(self):
        """Test setting subsystem level to WARNING"""
        set_subsystem_level(LogSubsystem.LLM, "WARNING")
        level = get_subsystem_level(LogSubsystem.LLM)
        assert level == logging.WARNING


class TestLogDuration:
    """Tests for log_duration context manager"""

    def setup_method(self):
        reset_configuration()
        configure_logging(level="DEBUG", enable_redaction=False)

    def teardown_method(self):
        reset_configuration()

    def test_log_duration_executes(self):
        """Test that log_duration executes the block"""
        log = get_logger(LogSubsystem.TOOL)
        executed = False

        with log_duration(log, "test_operation"):
            executed = True

        assert executed

    def test_log_duration_with_exception(self):
        """Test that log_duration logs even on exception"""
        log = get_logger(LogSubsystem.TOOL)

        with pytest.raises(ValueError):
            with log_duration(log, "failing_operation"):
                raise ValueError("Test error")


class TestRedactionFilter:
    """Tests for RedactionFilter class"""

    def test_filter_creation(self):
        """Test that RedactionFilter can be created"""
        filter = RedactionFilter()
        assert filter is not None

    def test_filter_returns_true(self):
        """Test that filter always returns True (doesn't block logs)"""
        filter = RedactionFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test message",
            args=(),
            exc_info=None
        )
        result = filter.filter(record)
        assert result is True


class TestResetConfiguration:
    """Tests for reset_configuration function"""

    def test_reset_clears_configured_flag(self):
        """Test that reset clears the configured flag"""
        configure_logging()
        assert is_configured()

        reset_configuration()
        assert not is_configured()

    def test_reset_removes_handlers(self):
        """Test that reset removes handlers"""
        configure_logging()
        root = logging.getLogger("a0")
        initial_handlers = len(root.handlers)

        reset_configuration()
        assert len(root.handlers) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
