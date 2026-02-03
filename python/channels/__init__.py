"""
Agent Zero Channels Module

Channel adapters for various messaging platforms.
Each adapter implements the ChannelAdapter base class.

Supported Channels (Phase 1):
- Telegram: python-telegram-bot
- Discord: discord.py

Future Channels:
- Email: smtplib/imaplib
- Slack: slack-sdk
- WeChat: wechatpy
- WhatsApp: Twilio
- Matrix: matrix-nio
"""

from .base import (
    ChannelAdapter,
    ChannelCapabilities,
    InboundMessage,
    OutboundMessage,
    Attachment,
    MessageType,
)
from .manager import ChannelManager
from .security import SecurityManager

__all__ = [
    "ChannelAdapter",
    "ChannelCapabilities",
    "InboundMessage",
    "OutboundMessage",
    "Attachment",
    "MessageType",
    "ChannelManager",
    "SecurityManager",
]
