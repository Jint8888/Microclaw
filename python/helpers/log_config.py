"""
Agent Zero Unified Logging Configuration

Provides a simple logging configuration entry point, reusing the standard logging module.
Integrates with existing secrets.py for automatic sensitive information redaction.

Usage:
    from python.helpers.log_config import configure_logging, get_logger, LogSubsystem

    # Initialize at application startup
    configure_logging(level="INFO", log_file="logs/agent.log")

    # Get subsystem logger
    log = get_logger(LogSubsystem.TOOL)
    log.info("Executing tool", extra={"tool_name": "code_execution"})
"""

import logging
import sys
import os
from typing import Optional, Dict, Any
from enum import Enum
from contextlib import contextmanager
import time


class LogSubsystem(str, Enum):
    """Log subsystem classification for Agent Zero"""
    AGENT = "a0.agent"
    MEMORY = "a0.memory"
    TOOL = "a0.tool"
    LLM = "a0.llm"
    MCP = "a0.mcp"
    BROWSER = "a0.browser"
    CHANNEL = "a0.channel"
    PLUGIN = "a0.plugin"


# Global configuration state
_configured = False
_config_lock = None

try:
    import threading
    _config_lock = threading.Lock()
except ImportError:
    pass


class RedactionFilter(logging.Filter):
    """
    Log filter that redacts sensitive information using secrets.py

    Automatically masks secrets registered in SecretsManager with
    placeholder format: §§secret(KEY)
    """

    def __init__(self):
        super().__init__()
        self._manager = None
        self._init_attempted = False

    def _get_manager(self):
        """Lazy load SecretsManager to avoid circular imports"""
        if not self._init_attempted:
            self._init_attempted = True
            try:
                from python.helpers.secrets import SecretsManager
                self._manager = SecretsManager.get_instance()
            except (ImportError, Exception):
                pass
        return self._manager

    def filter(self, record: logging.LogRecord) -> bool:
        """Apply redaction to log message"""
        manager = self._get_manager()
        if manager and hasattr(record, 'msg') and isinstance(record.msg, str):
            try:
                record.msg = manager.mask_values(record.msg)
            except Exception:
                pass  # Don't break logging if redaction fails
        return True


class ContextAdapter(logging.LoggerAdapter):
    """
    Logger adapter that supports context injection

    Usage:
        log = get_logger(LogSubsystem.AGENT)
        log.info("Processing request", extra={"session_id": "abc123"})
    """

    def process(self, msg, kwargs):
        # Merge extra context
        extra = kwargs.get('extra', {})
        if self.extra:
            extra = {**self.extra, **extra}
        kwargs['extra'] = extra
        return msg, kwargs


def configure_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    format_string: Optional[str] = None,
    enable_redaction: bool = True,
    enable_console: bool = True
) -> None:
    """
    Configure Agent Zero logging system

    This function should be called once at application startup.
    Subsequent calls will be ignored.

    Args:
        level: Log level (DEBUG/INFO/WARNING/ERROR/CRITICAL)
        log_file: Optional log file path for file output
        format_string: Custom format string (uses default if not provided)
        enable_redaction: Whether to enable sensitive info redaction (default: True)
        enable_console: Whether to output to console (default: True)

    Example:
        >>> from python.helpers.log_config import configure_logging
        >>> configure_logging(level="DEBUG", log_file="logs/agent.log")
    """
    global _configured

    # Thread-safe configuration check
    if _config_lock:
        with _config_lock:
            if _configured:
                return
            _configured = True
    else:
        if _configured:
            return
        _configured = True

    # Default format with timestamp, subsystem, level, and message
    fmt = format_string or "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
    formatter = logging.Formatter(fmt, datefmt="%Y-%m-%d %H:%M:%S")

    # Configure root a0 logger
    root = logging.getLogger("a0")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Prevent propagation to root logger to avoid duplicate output
    root.propagate = False

    # Console handler
    if enable_console:
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(formatter)
        console.setLevel(getattr(logging, level.upper(), logging.INFO))
        root.addHandler(console)

    # File handler (optional)
    if log_file:
        try:
            log_dir = os.path.dirname(log_file)
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setFormatter(formatter)
            file_handler.setLevel(getattr(logging, level.upper(), logging.INFO))
            root.addHandler(file_handler)
        except (OSError, IOError) as e:
            # Log to console if file handler fails
            root.warning(f"Failed to create log file handler: {e}")

    # Install redaction filter
    if enable_redaction:
        redaction_filter = RedactionFilter()
        root.addFilter(redaction_filter)

    root.info("Agent Zero logging configured", extra={"level": level, "redaction": enable_redaction})


def get_logger(subsystem: LogSubsystem, context: Optional[Dict[str, Any]] = None) -> logging.Logger:
    """
    Get a logger for a specific subsystem

    Args:
        subsystem: LogSubsystem enum value
        context: Optional context dict to attach to all log messages

    Returns:
        Configured Logger instance

    Example:
        >>> from python.helpers.log_config import get_logger, LogSubsystem
        >>> log = get_logger(LogSubsystem.TOOL)
        >>> log.info("Executing tool", extra={"tool_name": "code_execution"})
    """
    logger = logging.getLogger(subsystem.value)

    if context:
        return ContextAdapter(logger, context)

    return logger


def set_subsystem_level(subsystem: LogSubsystem, level: str) -> None:
    """
    Set log level for a specific subsystem

    Args:
        subsystem: LogSubsystem enum value
        level: Log level string (DEBUG/INFO/WARNING/ERROR/CRITICAL)

    Example:
        >>> set_subsystem_level(LogSubsystem.LLM, "WARNING")  # Reduce LLM noise
        >>> set_subsystem_level(LogSubsystem.TOOL, "DEBUG")   # Debug tools
    """
    logger = logging.getLogger(subsystem.value)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))


def get_subsystem_level(subsystem: LogSubsystem) -> int:
    """
    Get current log level for a subsystem

    Args:
        subsystem: LogSubsystem enum value

    Returns:
        Current log level as integer
    """
    logger = logging.getLogger(subsystem.value)
    return logger.level or logger.getEffectiveLevel()


@contextmanager
def log_duration(logger: logging.Logger, operation: str, level: int = logging.DEBUG):
    """
    Context manager to log operation duration

    Args:
        logger: Logger instance
        operation: Operation name for logging
        level: Log level for the duration message

    Example:
        >>> log = get_logger(LogSubsystem.LLM)
        >>> with log_duration(log, "llm_call"):
        ...     response = await call_llm(messages)
        # Logs: "llm_call completed in 1234.56ms"
    """
    start = time.time()
    try:
        yield
    finally:
        duration_ms = (time.time() - start) * 1000
        logger.log(level, f"{operation} completed in {duration_ms:.2f}ms")


def is_configured() -> bool:
    """Check if logging has been configured"""
    return _configured


def reset_configuration() -> None:
    """
    Reset logging configuration (mainly for testing)

    WARNING: This removes all handlers from the a0 logger.
    Only use in test environments.
    """
    global _configured
    _configured = False

    root = logging.getLogger("a0")
    for handler in root.handlers[:]:
        root.removeHandler(handler)
    for filter_ in root.filters[:]:
        root.removeFilter(filter_)
