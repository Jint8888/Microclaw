"""
Agent Zero Gateway Module

Multi-channel messaging gateway for Agent Zero.
Provides unified interface for Telegram, Discord, and other messaging platforms.

Architecture:
- Gateway runs in a separate thread alongside Web UI
- Shares AgentContext with Web UI through in-memory dict
- Uses Extension mechanism for streaming responses
"""

from .config import GatewayConfig
from .agent_bridge import AgentBridge, ChannelSession
from .protocol import GatewayEvent, EventType, GatewayRequest, GatewayResponse

__all__ = [
    "GatewayConfig",
    "AgentBridge",
    "ChannelSession",
    "GatewayEvent",
    "EventType",
    "GatewayRequest",
    "GatewayResponse",
]

__version__ = "4.1.0"
