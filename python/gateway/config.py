"""
Gateway Configuration Management

Supports:
- YAML configuration files
- Environment variable overrides
- Hot reload with file watching
"""

import os
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Callable
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    WATCHDOG_AVAILABLE = True
except ImportError:
    Observer = None
    WATCHDOG_AVAILABLE = False
    # Fallback base class when watchdog is not available
    class FileSystemEventHandler:
        pass

logger = logging.getLogger("gateway.config")


@dataclass
class GatewayConfig:
    """Gateway configuration"""
    # Basic settings
    port: int = 18900
    host: str = "127.0.0.1"
    config_path: str = "conf/gateway.yaml"

    # Security settings
    auth_token: Optional[str] = None
    auth_password: Optional[str] = None

    # Feature flags
    hot_reload: bool = True
    verbose: bool = False

    # Session settings
    session_max_idle_hours: int = 24
    session_cleanup_interval_seconds: int = 3600

    # Channel configurations
    channels: Dict[str, Any] = field(default_factory=dict)

    # Advanced settings
    max_payload_size: int = 10 * 1024 * 1024  # 10MB
    tick_interval_ms: int = 30000  # 30s heartbeat
    websocket_timeout: int = 60  # WebSocket timeout

    @classmethod
    def load(cls, config_path: str = None) -> "GatewayConfig":
        """Load configuration from file and environment"""
        path = config_path or os.environ.get("GATEWAY_CONFIG_PATH", "conf/gateway.yaml")
        
        config = cls(config_path=path)

        # Load from file
        if os.path.exists(path) and yaml:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f) or {}

                # Gateway settings
                gateway = data.get("gateway", {})
                config.port = gateway.get("port", config.port)
                config.host = gateway.get("host", config.host)
                config.hot_reload = gateway.get("hot_reload", config.hot_reload)
                config.verbose = gateway.get("verbose", config.verbose)

                # Session settings
                session = gateway.get("session", {})
                config.session_max_idle_hours = session.get("max_idle_hours", config.session_max_idle_hours)
                config.session_cleanup_interval_seconds = session.get("cleanup_interval_seconds", config.session_cleanup_interval_seconds)

                # Auth settings
                auth = gateway.get("auth", {})
                config.auth_token = auth.get("token")
                config.auth_password = auth.get("password")

                # Channel settings
                config.channels = data.get("channels", {})

                logger.info(f"Loaded config from {path}")
            except Exception as e:
                logger.warning(f"Failed to load config from {path}: {e}")

        # Environment variable overrides
        config.port = int(os.environ.get("GATEWAY_PORT", config.port))
        config.host = os.environ.get("GATEWAY_HOST", config.host)
        config.auth_token = os.environ.get("GATEWAY_AUTH_TOKEN", config.auth_token)

        # Replace environment variables in channel configs
        config.channels = cls._replace_env_vars(config.channels)

        return config

    @staticmethod
    def _replace_env_vars(obj: Any) -> Any:
        """Recursively replace environment variable references"""
        if isinstance(obj, str) and obj.startswith("${") and obj.endswith("}"):
            env_key = obj[2:-1]
            return os.environ.get(env_key, "")
        elif isinstance(obj, dict):
            return {k: GatewayConfig._replace_env_vars(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [GatewayConfig._replace_env_vars(item) for item in obj]
        return obj

    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary"""
        return {
            "gateway": {
                "port": self.port,
                "host": self.host,
                "hot_reload": self.hot_reload,
                "verbose": self.verbose,
                "auth": {
                    "token": "***" if self.auth_token else None,
                    "password": "***" if self.auth_password else None,
                },
            },
            "channels": {
                name: {**cfg, "token": "***"} if "token" in cfg else cfg
                for name, cfg in self.channels.items()
            },
        }


class ConfigFileHandler(FileSystemEventHandler):
    """File system event handler for config watching"""

    def __init__(self, callback: Callable):
        self.callback = callback
        self._last_modified = 0

    def on_modified(self, event):
        if not event.is_directory:
            import time
            current_time = time.time()
            # Debounce: ignore if modified within 1 second
            if current_time - self._last_modified > 1:
                self._last_modified = current_time
                self.callback()


class ConfigWatcher:
    """Configuration file watcher with hot reload support"""

    def __init__(self, config_path: str, callback: Callable):
        self.config_path = Path(config_path)
        self.callback = callback
        self.observer = None
        self._debounce_task: Optional[asyncio.Task] = None
        self._debounce_delay = 1.0  # Debounce delay in seconds

    async def start(self):
        """Start watching config file"""
        if not WATCHDOG_AVAILABLE:
            logger.warning("watchdog not installed, hot reload disabled")
            return

        if not self.config_path.exists():
            logger.warning(f"Config file not found: {self.config_path}")
            return

        handler = ConfigFileHandler(self._on_change)
        self.observer = Observer()
        self.observer.schedule(handler, str(self.config_path.parent), recursive=False)
        self.observer.start()
        logger.info(f"Watching config file: {self.config_path}")

    async def stop(self):
        """Stop watching config file"""
        if self.observer:
            self.observer.stop()
            self.observer.join(timeout=5)
            self.observer = None

        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()

    def _on_change(self):
        """Handle config file change with debouncing"""
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()

        async def debounced_callback():
            await asyncio.sleep(self._debounce_delay)
            try:
                if yaml:
                    with open(self.config_path, 'r', encoding='utf-8') as f:
                        new_config = yaml.safe_load(f)
                    await self.callback(new_config)
                    logger.info("Config reloaded successfully")
            except Exception as e:
                logger.error(f"Failed to reload config: {e}")

        try:
            loop = asyncio.get_running_loop()
            self._debounce_task = loop.create_task(debounced_callback())
        except RuntimeError:
            # No running event loop, try to run in new loop
            try:
                asyncio.run(debounced_callback())
            except Exception as e:
                logger.warning(f"Could not run config reload callback: {e}")
