"""
pytest shared fixtures for Gateway tests

File: tests/conftest.py
"""

import pytest
import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_agent_context():
    """Mock AgentContext"""
    ctx = MagicMock()
    ctx.get.return_value = None
    ctx.set_data = MagicMock()
    ctx.get_data = MagicMock(return_value=None)
    ctx.communicate = MagicMock()
    return ctx


@pytest.fixture
def mock_agent_config():
    """Mock AgentConfig"""
    config = MagicMock()
    return config


@pytest.fixture
def mock_channel_config():
    """Mock channel configuration"""
    return {
        "enabled": True,
        "token": "test_token",
        "whitelist": [],
        "blacklist": [],
        "rate_limit": {
            "max_requests": 10,
            "window_seconds": 60
        }
    }
