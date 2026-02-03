"""
Agent Zero Gateway Server

Core gateway server using parallel coexistence architecture:
- Gateway focuses on channel integration
- Web UI maintains existing Flask architecture
- Unified sessions via shared AgentContext

File: python/gateway/server.py
"""

import asyncio
import logging
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger("gateway.server")


@dataclass
class GatewayState:
    """Gateway runtime state"""
    started_at: datetime = field(default_factory=datetime.now)
    config: "GatewayConfig" = None
    channel_manager: "ChannelManager" = None
    agent_bridge: "AgentBridge" = None
    security_manager: "SecurityManager" = None
    metrics: "MetricsCollector" = None
    health_checker: "HealthChecker" = None
    config_watcher: "ConfigWatcher" = None
    session_cleaner: "SessionCleaner" = None
    mcp_sync: "MCPSettingsSync" = None  # On-demand MCP config sync
    is_shutting_down: bool = False


# Global state
state = GatewayState()


def create_app():
    """Create FastAPI application"""
    from fastapi import FastAPI, HTTPException, Depends
    from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
    from fastapi.middleware.cors import CORSMiddleware
    from contextlib import asynccontextmanager

    security = HTTPBearer(auto_error=False)

    def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> bool:
        """Verify API Token"""
        if not state.config or not state.config.auth_token:
            return True
        if not credentials:
            raise HTTPException(status_code=401, detail="Missing authorization token")
        if credentials.credentials != state.config.auth_token:
            raise HTTPException(status_code=403, detail="Invalid token")
        return True

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Application lifecycle management"""
        logger.info("Gateway starting...")
        await startup()
        yield
        await shutdown()

    async def startup():
        """Startup initialization"""
        from .config import GatewayConfig, ConfigWatcher
        from .agent_bridge import AgentBridge
        from .health import HealthChecker
        from .metrics import MetricsCollector
        from .session_cleaner import SessionCleaner
        from python.channels.manager import ChannelManager
        from python.channels.security import SecurityManager

        # Load configuration
        state.config = GatewayConfig.load()
        logger.info(f"Loaded config from {state.config.config_path}")

        # Initialize metrics collector
        state.metrics = MetricsCollector()

        # Initialize security manager
        state.security_manager = SecurityManager(state.config)

        # Initialize AgentBridge
        state.agent_bridge = AgentBridge()

        # Initialize channel manager
        state.channel_manager = ChannelManager(
            agent_bridge=state.agent_bridge,
            security_manager=state.security_manager,
            metrics=state.metrics,
        )

        # Register channels from config
        await _register_channels_from_config()

        # Start channels
        if state.channel_manager.channels:
            await state.channel_manager.start_all()

        # Initialize health checker
        state.health_checker = HealthChecker(state)

        # Initialize session cleaner
        state.session_cleaner = SessionCleaner(
            agent_bridge=state.agent_bridge,
            max_idle_hours=state.config.session_max_idle_hours,
            check_interval_seconds=state.config.session_cleanup_interval_seconds,
        )
        await state.session_cleaner.start()

        # Start config hot reload
        if state.config.hot_reload:
            state.config_watcher = ConfigWatcher(state.config.config_path, on_config_change)
            await state.config_watcher.start()

        # Initialize MCP settings sync for cross-process config sync
        # (checks on-demand when processing requests, not polling)
        from .mcp_watcher import MCPSettingsSync, get_settings_file_path
        state.mcp_sync = MCPSettingsSync.get_instance(get_settings_file_path())
        await state.mcp_sync.initialize()

        logger.info(f"Gateway started on port {state.config.port}")

    async def _register_channels_from_config():
        """Register channels from configuration"""
        channels_config = state.config.channels

        for channel_name, channel_cfg in channels_config.items():
            if not channel_cfg.get("enabled", False):
                continue

            try:
                if channel_name == "telegram" and channel_cfg.get("token"):
                    from python.channels.telegram_adapter import TelegramAdapter
                    adapter = TelegramAdapter(channel_cfg, channel_cfg.get("account_id", "default"))
                    state.channel_manager.register(f"telegram:{adapter.account_id}", adapter)

                elif channel_name == "discord" and channel_cfg.get("token"):
                    from python.channels.discord_adapter import DiscordAdapter
                    adapter = DiscordAdapter(channel_cfg, channel_cfg.get("account_id", "default"))
                    state.channel_manager.register(f"discord:{adapter.account_id}", adapter)

            except ImportError as e:
                logger.warning(f"Could not import adapter for {channel_name}: {e}")
            except Exception as e:
                logger.error(f"Failed to register {channel_name}: {e}")

    async def shutdown():
        """Graceful shutdown"""
        logger.info("Gateway shutting down...")
        state.is_shutting_down = True

        if state.session_cleaner:
            await state.session_cleaner.stop()
        if state.config_watcher:
            await state.config_watcher.stop()
        if state.channel_manager:
            await state.channel_manager.stop_all()

        logger.info("Gateway stopped")

    async def on_config_change(new_config: dict):
        """Config change callback"""
        logger.info("Config changed, applying hot reload...")
        await state.channel_manager.apply_config_change(new_config)

    # FastAPI application
    app = FastAPI(
        title="Agent Zero Gateway",
        version="4.1.0",
        lifespan=lifespan
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # HTTP API endpoints
    @app.get("/api/health")
    async def health_check():
        """Health check"""
        if state.health_checker:
            status = await state.health_checker.check()
            return status.to_dict()
        return {"status": "starting"}

    @app.get("/api/status")
    async def gateway_status(authorized: bool = Depends(verify_token)):
        """Gateway status"""
        return {
            "started_at": state.started_at.isoformat(),
            "uptime_seconds": (datetime.now() - state.started_at).total_seconds(),
            "channels": state.channel_manager.list_channels() if state.channel_manager else {},
            "sessions": state.agent_bridge.get_active_session_count() if state.agent_bridge else 0,
            "metrics": state.metrics.get_summary() if state.metrics else {},
        }

    @app.get("/api/channels")
    async def list_channels(authorized: bool = Depends(verify_token)):
        """List all channels"""
        if not state.channel_manager:
            return {"channels": {}}
        return {"channels": state.channel_manager.list_channels()}

    @app.get("/api/sessions")
    async def list_sessions(authorized: bool = Depends(verify_token)):
        """List all sessions"""
        if not state.agent_bridge:
            return {"sessions": {}}
        sessions = state.agent_bridge.list_sessions()
        return {
            "sessions": {
                k: {
                    "channel": v.channel,
                    "user_id": v.channel_user_id,
                    "chat_id": v.channel_chat_id,
                    "user_name": v.user_name,
                    "created_at": v.created_at.isoformat() if v.created_at else None,
                    "last_activity": v.last_activity.isoformat() if v.last_activity else None,
                }
                for k, v in sessions.items()
            },
            "count": len(sessions),
        }

    @app.get("/api/metrics")
    async def get_metrics(authorized: bool = Depends(verify_token)):
        """Get monitoring metrics"""
        if not state.metrics:
            return {"metrics": {}}
        return {"metrics": state.metrics.get_summary()}

    @app.post("/api/reload")
    async def reload_config(authorized: bool = Depends(verify_token)):
        """Manually trigger config reload"""
        try:
            from .config import GatewayConfig
            new_config = GatewayConfig.load()
            await on_config_change(new_config.to_dict())
            return {"success": True}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    return app


# Create application instance
app = create_app()


def run_gateway(host: str = "127.0.0.1", port: int = 18900, reload: bool = False, log_level: str = "info"):
    """Run Gateway server"""
    import uvicorn

    # 禁用 uvloop 以兼容 nest_asyncio
    uvicorn.run(
        "python.gateway.server:app",
        host=host,
        port=port,
        reload=reload,
        log_level=log_level,
        loop="asyncio",  # 使用标准 asyncio 而不是 uvloop
    )
