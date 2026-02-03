"""
Gateway Communication Protocol

Defines message formats for gateway-client communication.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional, Dict
from enum import Enum


class EventType(Enum):
    """Event types for gateway communication"""
    # Connection events
    HELLO = "hello"
    PING = "ping"
    PONG = "pong"

    # System events
    SHUTDOWN = "shutdown"
    CONFIG_RELOAD = "config_reload"

    # Agent events
    AGENT_START = "agent_start"
    AGENT_CHUNK = "agent_chunk"
    AGENT_END = "agent_end"
    AGENT_ERROR = "agent_error"

    # Channel events
    CHANNEL_MESSAGE = "channel_message"
    CHANNEL_STATUS = "channel_status"

    # Status events
    PRESENCE = "presence"
    TICK = "tick"


@dataclass
class GatewayEvent:
    """Gateway event message"""
    type: EventType
    payload: Dict[str, Any] = field(default_factory=dict)
    seq: Optional[int] = None
    timestamp: datetime = field(default_factory=datetime.now)

    def to_json(self) -> str:
        return json.dumps({
            "type": self.type.value,
            "payload": self.payload,
            "seq": self.seq,
            "timestamp": self.timestamp.isoformat(),
        })

    @classmethod
    def from_json(cls, data: str) -> "GatewayEvent":
        obj = json.loads(data)
        return cls(
            type=EventType(obj["type"]),
            payload=obj.get("payload", {}),
            seq=obj.get("seq"),
            timestamp=datetime.fromisoformat(obj["timestamp"]) if "timestamp" in obj else datetime.now(),
        )


@dataclass
class GatewayRequest:
    """Gateway request message"""
    id: str
    method: str
    params: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps({
            "type": "req",
            "id": self.id,
            "method": self.method,
            "params": self.params,
        })

    @classmethod
    def from_json(cls, data: str) -> "GatewayRequest":
        obj = json.loads(data)
        return cls(
            id=obj["id"],
            method=obj["method"],
            params=obj.get("params", {}),
        )


@dataclass
class GatewayResponse:
    """Gateway response message"""
    id: str
    ok: bool
    payload: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None

    def to_json(self) -> str:
        result = {
            "type": "res",
            "id": self.id,
            "ok": self.ok,
        }
        if self.ok:
            result["payload"] = self.payload
        else:
            result["error"] = self.error
        return json.dumps(result)

    @classmethod
    def from_json(cls, data: str) -> "GatewayResponse":
        obj = json.loads(data)
        return cls(
            id=obj["id"],
            ok=obj["ok"],
            payload=obj.get("payload"),
            error=obj.get("error"),
        )
