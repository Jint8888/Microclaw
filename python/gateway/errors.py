"""
Gateway Error Handling Module

File: python/gateway/errors.py
"""

import logging
import asyncio
from typing import Dict, Optional
from enum import Enum
from dataclasses import dataclass

logger = logging.getLogger("gateway.errors")


class ErrorType(Enum):
    """Error types"""
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    ACCESS_DENIED = "access_denied"
    INVALID_MESSAGE = "invalid_message"
    AGENT_ERROR = "agent_error"
    NETWORK_ERROR = "network_error"
    INTERNAL_ERROR = "internal_error"


@dataclass
class ErrorMessage:
    """Error message configuration"""
    user_message: str  # Message shown to user
    log_level: str     # Log level
    include_retry: bool = False  # Include retry hint


# Multi-language error message configuration
ERROR_MESSAGES: Dict[str, Dict[ErrorType, ErrorMessage]] = {
    "zh": {
        ErrorType.TIMEOUT: ErrorMessage(
            user_message="处理时间过长，请稍后重试",
            log_level="warning",
            include_retry=True
        ),
        ErrorType.RATE_LIMIT: ErrorMessage(
            user_message="请求太频繁，请稍后再试",
            log_level="warning",
            include_retry=True
        ),
        ErrorType.ACCESS_DENIED: ErrorMessage(
            user_message="抱歉，您没有使用权限",
            log_level="warning"
        ),
        ErrorType.INVALID_MESSAGE: ErrorMessage(
            user_message="消息格式不正确，请重新发送",
            log_level="info"
        ),
        ErrorType.AGENT_ERROR: ErrorMessage(
            user_message="AI 处理时遇到问题，请重试",
            log_level="error",
            include_retry=True
        ),
        ErrorType.NETWORK_ERROR: ErrorMessage(
            user_message="网络连接出现问题，请稍后重试",
            log_level="error",
            include_retry=True
        ),
        ErrorType.INTERNAL_ERROR: ErrorMessage(
            user_message="系统出现问题，工程师正在处理中",
            log_level="error"
        ),
    },
    "en": {
        ErrorType.TIMEOUT: ErrorMessage(
            user_message="Request timed out, please try again later",
            log_level="warning",
            include_retry=True
        ),
        ErrorType.RATE_LIMIT: ErrorMessage(
            user_message="Too many requests, please slow down",
            log_level="warning",
            include_retry=True
        ),
        ErrorType.ACCESS_DENIED: ErrorMessage(
            user_message="Sorry, you don't have permission",
            log_level="warning"
        ),
        ErrorType.INVALID_MESSAGE: ErrorMessage(
            user_message="Invalid message format, please try again",
            log_level="info"
        ),
        ErrorType.AGENT_ERROR: ErrorMessage(
            user_message="AI encountered an issue, please retry",
            log_level="error",
            include_retry=True
        ),
        ErrorType.NETWORK_ERROR: ErrorMessage(
            user_message="Network error, please try again later",
            log_level="error",
            include_retry=True
        ),
        ErrorType.INTERNAL_ERROR: ErrorMessage(
            user_message="System error, we're working on it",
            log_level="error"
        ),
    }
}


class ErrorHandler:
    """Error handler"""

    def __init__(self, default_language: str = "zh"):
        self.default_language = default_language

    def classify_error(self, error: Exception) -> ErrorType:
        """Classify exception to error type"""
        error_str = str(error).lower()

        if isinstance(error, asyncio.TimeoutError):
            return ErrorType.TIMEOUT
        elif "timeout" in error_str:
            return ErrorType.TIMEOUT
        elif "rate limit" in error_str or "too many" in error_str:
            return ErrorType.RATE_LIMIT
        elif "access denied" in error_str or "permission" in error_str:
            return ErrorType.ACCESS_DENIED
        elif "invalid" in error_str or "format" in error_str:
            return ErrorType.INVALID_MESSAGE
        elif "network" in error_str or "connection" in error_str:
            return ErrorType.NETWORK_ERROR
        elif "agent" in error_str:
            return ErrorType.AGENT_ERROR
        else:
            return ErrorType.INTERNAL_ERROR

    def format_error(
        self,
        error: Exception,
        language: str = None,
        log_error: bool = True
    ) -> str:
        """
        Format error to user-friendly message

        Args:
            error: Exception object
            language: Language code (zh/en)
            log_error: Whether to log the error

        Returns:
            User-friendly error message
        """
        lang = language or self.default_language
        error_type = self.classify_error(error)

        messages = ERROR_MESSAGES.get(lang, ERROR_MESSAGES["en"])
        error_msg = messages.get(error_type, messages[ErrorType.INTERNAL_ERROR])

        # Log error
        if log_error:
            log_func = getattr(logger, error_msg.log_level, logger.error)
            log_func(f"[{error_type.value}] {error}")

        # Build user message
        user_message = f"⚠️ {error_msg.user_message}"
        if error_msg.include_retry:
            retry_hint = " 🔄" if lang == "zh" else " (retry)"
            user_message += retry_hint

        return user_message

    def get_error_response(
        self,
        error_type: ErrorType,
        language: str = None
    ) -> str:
        """Get error message for specified type"""
        lang = language or self.default_language
        messages = ERROR_MESSAGES.get(lang, ERROR_MESSAGES["en"])
        error_msg = messages.get(error_type, messages[ErrorType.INTERNAL_ERROR])
        return f"⚠️ {error_msg.user_message}"


# Global error handler instance
error_handler = ErrorHandler()
