"""
AgentBridge Thread Safety and Functionality Tests

File: tests/gateway/test_agent_bridge.py
"""

import pytest
import asyncio
import threading
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime, timezone


class TestAgentBridgeThreadSafety:
    """AgentBridge thread safety tests"""

    @pytest.fixture
    def mock_config(self):
        """Mock AgentConfig"""
        return MagicMock()

    @pytest.fixture
    def bridge(self, mock_config):
        """Create AgentBridge instance"""
        with patch('python.gateway.agent_bridge.logger'):
            from python.gateway.agent_bridge import AgentBridge
            bridge = AgentBridge(mock_config)
            bridge._config_initialized = True
            return bridge

    def test_session_key_format(self, bridge):
        """Test session key generation format"""
        assert bridge._make_session_key("telegram", "123") == "tg:123"
        assert bridge._make_session_key("discord", "456") == "dc:456"
        assert bridge._make_session_key("email", "user@test.com") == "em:user@test.com"
        assert bridge._make_session_key("unknown", "789") == "un:789"

    def test_thread_safe_list_sessions(self, bridge):
        """Test list_sessions returns a copy"""
        from python.gateway.agent_bridge import ChannelSession
        
        # Add a session
        bridge._sessions["tg:123"] = ChannelSession(
            context_id="tg:123",
            channel="telegram",
            channel_user_id="123",
            channel_chat_id="chat_123"
        )
        
        # Get sessions
        sessions = bridge.list_sessions()
        
        # Verify it's a copy
        assert sessions is not bridge._sessions
        assert len(sessions) == 1
        assert "tg:123" in sessions

    def test_thread_safe_remove_session(self, bridge):
        """Test thread-safe session removal"""
        from python.gateway.agent_bridge import ChannelSession
        
        # Add session
        bridge._sessions["tg:123"] = ChannelSession(
            context_id="tg:123",
            channel="telegram",
            channel_user_id="123",
            channel_chat_id="chat_123"
        )
        
        # Mock AgentContext.remove at the agent module level
        with patch('agent.AgentContext') as mock_ctx:
            mock_ctx.remove = MagicMock()
            result = bridge.remove_session("telegram", "123")
        
        assert result is True
        assert len(bridge._sessions) == 0

    def test_concurrent_list_and_modify(self, bridge):
        """Test concurrent access doesn't cause errors"""
        from python.gateway.agent_bridge import ChannelSession
        
        errors = []
        
        # Pre-populate some sessions
        for i in range(5):
            bridge._sessions[f"tg:user_{i}"] = ChannelSession(
                context_id=f"tg:user_{i}",
                channel="telegram",
                channel_user_id=f"user_{i}",
                channel_chat_id=f"chat_{i}"
            )
        
        def list_sessions():
            try:
                for _ in range(50):
                    _ = bridge.list_sessions()
            except Exception as e:
                errors.append(e)
        
        def modify_sessions():
            try:
                for i in range(5, 15):
                    bridge._sessions[f"tg:user_{i}"] = ChannelSession(
                        context_id=f"tg:user_{i}",
                        channel="telegram",
                        channel_user_id=f"user_{i}",
                        channel_chat_id=f"chat_{i}"
                    )
            except Exception as e:
                errors.append(e)
        
        t1 = threading.Thread(target=list_sessions)
        t2 = threading.Thread(target=modify_sessions)
        
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        
        assert len(errors) == 0, f"Thread safety errors: {errors}"

    def test_get_sessions_by_channel(self, bridge):
        """Test filtering sessions by channel"""
        from python.gateway.agent_bridge import ChannelSession
        
        bridge._sessions["tg:user_1"] = ChannelSession(
            context_id="tg:user_1",
            channel="telegram",
            channel_user_id="user_1",
            channel_chat_id="chat_1"
        )
        bridge._sessions["dc:user_2"] = ChannelSession(
            context_id="dc:user_2",
            channel="discord",
            channel_user_id="user_2",
            channel_chat_id="chat_2"
        )
        
        telegram_sessions = bridge.get_sessions_by_channel("telegram")
        discord_sessions = bridge.get_sessions_by_channel("discord")
        
        assert len(telegram_sessions) == 1
        assert len(discord_sessions) == 1
        assert "tg:user_1" in telegram_sessions
        assert "dc:user_2" in discord_sessions


class TestProcessMessageStream:
    """Streaming message processing tests"""

    @pytest.fixture
    def bridge(self):
        with patch('python.gateway.agent_bridge.logger'):
            from python.gateway.agent_bridge import AgentBridge
            bridge = AgentBridge()
            bridge._config_initialized = True
            bridge._default_config = MagicMock()
            return bridge

    @pytest.mark.asyncio
    async def test_stream_uses_sentinel(self, bridge):
        """Test streaming uses sentinel value for end"""
        chunks_received = []
        
        async def mock_process(*args, **kwargs):
            callback = kwargs.get('stream_callback')
            if callback:
                await callback("Hello ", "Hello ")
                await callback("World", "Hello World")
            return "Hello World"
        
        with patch.object(bridge, 'process_message', mock_process):
            async for chunk in bridge.process_message_stream(
                channel="telegram",
                channel_user_id="user_123",
                channel_chat_id="chat_123",
                content="test"
            ):
                chunks_received.append(chunk)
        
        assert chunks_received == ["Hello ", "World"]

    @pytest.mark.asyncio
    async def test_stream_handles_empty_response(self, bridge):
        """Test empty response handling"""
        async def mock_process(*args, **kwargs):
            return ""
        
        with patch.object(bridge, 'process_message', mock_process):
            chunks = [chunk async for chunk in bridge.process_message_stream(
                channel="telegram",
                channel_user_id="user_123",
                channel_chat_id="chat_123",
                content="test"
            )]
        
        assert chunks == []

    @pytest.mark.asyncio
    async def test_stream_cancellation(self, bridge):
        """Test stream can be cancelled gracefully"""
        chunks_received = []
        
        async def slow_process(*args, **kwargs):
            callback = kwargs.get('stream_callback')
            if callback:
                for i in range(10):
                    await asyncio.sleep(0.1)
                    await callback(f"chunk_{i}", f"chunk_{i}")
            return "done"
        
        with patch.object(bridge, 'process_message', slow_process):
            try:
                async for chunk in bridge.process_message_stream(
                    channel="telegram",
                    channel_user_id="user_123",
                    channel_chat_id="chat_123",
                    content="test"
                ):
                    chunks_received.append(chunk)
                    if len(chunks_received) >= 2:
                        break  # Cancel early
            except asyncio.CancelledError:
                pass
        
        # Should have received at least some chunks before cancellation
        assert len(chunks_received) >= 2
