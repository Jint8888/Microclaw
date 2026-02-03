"""
MCP Settings Sync for Gateway Process

Syncs MCP configuration from settings file when needed (on-demand).
This solves the process isolation issue where WebUI and Gateway run
as separate Python processes with independent MCPConfig singletons.

File: python/gateway/mcp_watcher.py
"""

import logging
import os
import json
from typing import Optional

logger = logging.getLogger("gateway.mcp_sync")


class MCPSettingsSync:
    """
    On-demand MCP settings synchronization.
    
    Since WebUI and Gateway run as separate processes, MCPConfig updates
    in WebUI don't propagate to Gateway. This class checks the settings
    file for changes when requested (typically before processing a message).
    """
    
    _instance: Optional["MCPSettingsSync"] = None
    
    def __init__(self, settings_file: str):
        """
        Initialize MCP settings sync.
        
        Args:
            settings_file: Path to settings.json file
        """
        self.settings_file = settings_file
        self._last_mcp_config: Optional[str] = None
        self._last_modified: Optional[float] = None
        self._initialized = False
        
    @classmethod
    def get_instance(cls, settings_file: str = None) -> "MCPSettingsSync":
        """Get or create singleton instance."""
        if cls._instance is None:
            if settings_file is None:
                settings_file = get_settings_file_path()
            cls._instance = cls(settings_file)
        return cls._instance
    
    async def initialize(self):
        """Initialize MCP config from settings file at startup."""
        if self._initialized:
            return
            
        await self._load_and_apply_config(is_initial=True)
        self._initialized = True
        logger.info("MCP settings sync initialized")
        
    async def check_and_reload_if_changed(self) -> bool:
        """
        Check if MCP config has changed and reload if necessary.
        Call this before processing each user request.
        
        Returns:
            True if config was reloaded, False otherwise
        """
        try:
            if not os.path.exists(self.settings_file):
                return False
                
            # Quick check: file modification time
            mtime = os.path.getmtime(self.settings_file)
            if self._last_modified and mtime <= self._last_modified:
                return False  # File hasn't changed
                
            # File changed, check MCP config content
            with open(self.settings_file, 'r', encoding='utf-8') as f:
                settings = json.load(f)
                
            current_mcp = settings.get("mcp_servers", "")
            
            if current_mcp == self._last_mcp_config:
                # File changed but MCP config is the same
                self._last_modified = mtime
                return False
                
            # MCP config changed, reload
            logger.info("MCP configuration changed, reloading...")
            await self._apply_mcp_config(current_mcp)
            self._last_mcp_config = current_mcp
            self._last_modified = mtime
            return True
            
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse settings file: {e}")
            return False
        except Exception as e:
            logger.error(f"Error checking MCP config: {e}")
            return False
            
    async def _load_and_apply_config(self, is_initial: bool = False):
        """Load and apply MCP configuration from file."""
        try:
            if not os.path.exists(self.settings_file):
                logger.warning(f"Settings file not found: {self.settings_file}")
                return
                
            with open(self.settings_file, 'r', encoding='utf-8') as f:
                settings = json.load(f)
                
            mcp_config = settings.get("mcp_servers", "")
            self._last_mcp_config = mcp_config
            self._last_modified = os.path.getmtime(self.settings_file)
            
            if mcp_config and mcp_config.strip():
                await self._apply_mcp_config(mcp_config)
                
                from python.helpers.mcp_handler import MCPConfig
                instance = MCPConfig.get_instance()
                server_count = len(instance.servers) if instance.servers else 0
                server_names = [s.name for s in instance.servers] if instance.servers else []
                
                action = "Initialized" if is_initial else "Reloaded"
                logger.info(f"{action} MCP config: {server_count} servers - {server_names}")
            else:
                logger.info("No MCP servers configured in settings")
                
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse settings file: {e}")
        except Exception as e:
            logger.error(f"Error loading MCP config: {e}")
            
    async def _apply_mcp_config(self, mcp_config: str):
        """Apply MCP configuration to MCPConfig singleton."""
        from python.helpers.mcp_handler import MCPConfig
        MCPConfig.update(mcp_config)


def get_settings_file_path() -> str:
    """Get the settings file path."""
    from python.helpers import files
    return files.get_abs_path("tmp/settings.json")


# Convenience function for checking before message processing
async def check_mcp_config_update() -> bool:
    """
    Check and reload MCP config if changed.
    Call this before processing each user request.
    
    Returns:
        True if config was reloaded
    """
    sync = MCPSettingsSync.get_instance()
    return await sync.check_and_reload_if_changed()
