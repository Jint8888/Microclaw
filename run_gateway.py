#!/usr/bin/env python3
"""
Agent Zero Gateway - Startup Entry Point

This script starts the multi-channel gateway service that enables
Agent Zero to communicate via Telegram, Discord, and other channels.

Usage:
    python run_gateway.py [--host HOST] [--port PORT] [--config CONFIG]

Architecture:
    - Gateway runs as a FastAPI service with uvicorn
    - Channels (Telegram, Discord) run as background tasks
    - Shares AgentContext with Web UI for unified sessions
"""

import argparse
import logging
import os
import sys
from pathlib import Path

# Ensure project root is in Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("agent-zero.gateway")


def main():
    parser = argparse.ArgumentParser(
        description="Agent Zero Gateway - Multi-channel messaging service"
    )

    # Server configuration
    parser.add_argument(
        "--host",
        default=os.environ.get("GATEWAY_HOST", "127.0.0.1"),
        help="Bind host (default: 127.0.0.1, use 0.0.0.0 for remote access)"
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=int(os.environ.get("GATEWAY_PORT", "50002")),
        help="Bind port (default: 50002)"
    )
    parser.add_argument(
        "--config", "-c",
        default=os.environ.get("GATEWAY_CONFIG_PATH", "conf/gateway.yaml"),
        help="Configuration file path"
    )

    # Runtime options
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging"
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload (development mode)"
    )

    args = parser.parse_args()

    # Set environment variables for the gateway
    os.environ["GATEWAY_CONFIG_PATH"] = args.config
    os.environ["GATEWAY_PORT"] = str(args.port)
    os.environ["GATEWAY_HOST"] = args.host

    log_level = "debug" if args.verbose else "info"

    # Print startup banner
    logger.info("=" * 60)
    logger.info("Agent Zero Gateway - Multi-Channel Messaging Service")
    logger.info("=" * 60)
    logger.info(f"Host:   {args.host}")
    logger.info(f"Port:   {args.port}")
    logger.info(f"Config: {args.config}")
    logger.info(f"Health: http://{args.host}:{args.port}/api/health")
    logger.info("=" * 60)

    # Start the gateway
    try:
        from python.gateway.server import run_gateway
        run_gateway(
            host=args.host,
            port=args.port,
            reload=args.reload,
            log_level=log_level,
        )
    except ImportError as e:
        logger.error(f"Failed to import gateway module: {e}")
        logger.error("Please ensure all dependencies are installed:")
        logger.error("  pip install fastapi uvicorn python-telegram-bot discord.py")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Gateway startup failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
