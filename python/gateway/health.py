"""
Gateway Health Check

Provides:
- Liveness probe
- Readiness probe
- Detailed status report

File: python/gateway/health.py
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Any, Optional, TYPE_CHECKING
from enum import Enum

if TYPE_CHECKING:
    from .server import GatewayState

logger = logging.getLogger("gateway.health")


class HealthStatusLevel(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class HealthCheck:
    """Single health check result"""
    name: str
    status: HealthStatusLevel
    message: Optional[str] = None
    latency_ms: Optional[float] = None


@dataclass
class HealthStatus:
    """Overall health status"""
    status: str  # healthy, degraded, unhealthy
    uptime_seconds: float
    timestamp: datetime
    channels: Dict[str, Any]
    checks: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "uptime_seconds": self.uptime_seconds,
            "timestamp": self.timestamp.isoformat(),
            "channels": self.channels,
            "checks": self.checks,
        }


class HealthChecker:
    """Health checker"""

    def __init__(self, gateway_state: "GatewayState"):
        self.state = gateway_state

    async def check(self) -> HealthStatus:
        """Execute health check"""
        checks = []
        overall_status = HealthStatusLevel.HEALTHY

        # Check 1: Gateway core
        gateway_check = await self._check_gateway()
        checks.append(gateway_check)
        if gateway_check.status != HealthStatusLevel.HEALTHY:
            overall_status = gateway_check.status

        # Check 2: Channel status
        channel_checks = await self._check_channels()
        checks.extend(channel_checks)
        for check in channel_checks:
            if check.status == HealthStatusLevel.UNHEALTHY:
                overall_status = HealthStatusLevel.UNHEALTHY
            elif check.status == HealthStatusLevel.DEGRADED and overall_status == HealthStatusLevel.HEALTHY:
                overall_status = HealthStatusLevel.DEGRADED

        # Check 3: Agent connection
        agent_check = await self._check_agent()
        checks.append(agent_check)
        if agent_check.status == HealthStatusLevel.UNHEALTHY:
            overall_status = HealthStatusLevel.UNHEALTHY

        # Build channel status summary
        channels_summary = {}
        if self.state.channel_manager:
            for name, adapter in self.state.channel_manager.channels.items():
                channels_summary[name] = {
                    "type": adapter.__class__.__name__,
                    "running": adapter._running,
                    "capabilities": adapter.capabilities.__dict__ if hasattr(adapter, 'capabilities') else {},
                }

        return HealthStatus(
            status=overall_status.value,
            uptime_seconds=(datetime.now() - self.state.started_at).total_seconds(),
            timestamp=datetime.now(),
            channels=channels_summary,
            checks=[{
                "name": c.name,
                "status": c.status.value,
                "message": c.message,
                "latency_ms": c.latency_ms,
            } for c in checks],
        )

    async def _check_gateway(self) -> HealthCheck:
        """Check gateway core"""
        if self.state.is_shutting_down:
            return HealthCheck(
                name="gateway",
                status=HealthStatusLevel.UNHEALTHY,
                message="Gateway is shutting down"
            )

        return HealthCheck(
            name="gateway",
            status=HealthStatusLevel.HEALTHY,
            message="Gateway running"
        )

    async def _check_channels(self) -> List[HealthCheck]:
        """Check channel status"""
        checks = []

        if not self.state.channel_manager or not self.state.channel_manager.channels:
            return [HealthCheck(
                name="channels",
                status=HealthStatusLevel.DEGRADED,
                message="No channels registered"
            )]

        for name, adapter in self.state.channel_manager.channels.items():
            if adapter._running:
                checks.append(HealthCheck(
                    name=f"channel:{name}",
                    status=HealthStatusLevel.HEALTHY,
                    message="Connected"
                ))
            else:
                checks.append(HealthCheck(
                    name=f"channel:{name}",
                    status=HealthStatusLevel.UNHEALTHY,
                    message="Not running"
                ))

        return checks

    async def _check_agent(self) -> HealthCheck:
        """Check Agent connection"""
        if self.state.agent_bridge:
            session_count = self.state.agent_bridge.get_active_session_count()
            return HealthCheck(
                name="agent",
                status=HealthStatusLevel.HEALTHY,
                message=f"Agent context available, {session_count} active sessions"
            )
        return HealthCheck(
            name="agent",
            status=HealthStatusLevel.DEGRADED,
            message="Agent bridge not initialized"
        )
