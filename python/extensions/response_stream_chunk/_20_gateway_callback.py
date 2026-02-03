"""
Gateway Streaming Response Extension

Passes Agent's streaming responses to Gateway registered callback functions.
Gateway registers callback via ctx.set_data("gateway_stream_callback", callback)

File: python/extensions/response_stream_chunk/_20_gateway_callback.py
"""

from python.helpers.extension import Extension
from typing import TYPE_CHECKING
import logging

if TYPE_CHECKING:
    from agent import Agent

logger = logging.getLogger("gateway.extension")


class GatewayCallback(Extension):
    """
    Gateway streaming callback extension

    Passes Agent's streaming responses to Gateway registered callback functions.
    Gateway registers callback via ctx.set_data("gateway_stream_callback", callback)
    """

    async def execute(self, loop_data=None, stream_data=None, **kwargs):
        """
        Execute streaming callback

        Args:
            loop_data: Agent loop data
            stream_data: Streaming data {"chunk": str, "full": str}
        """
        if not stream_data:
            return

        agent: "Agent" = self.agent
        ctx = agent.context

        # Get Gateway registered callback from context.data
        callback = ctx.get_data("gateway_stream_callback")
        if callback:
            chunk = stream_data.get("chunk", "")
            full = stream_data.get("full", "")
            try:
                await callback(chunk, full)
            except Exception as e:
                # Silently handle callback errors, don't affect main flow
                logger.debug(f"Gateway stream callback error: {e}")
