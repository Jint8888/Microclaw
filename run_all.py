#!/usr/bin/env python
"""
Agent Zero 统一启动入口 (V4.1)

单进程并行架构：
- Web UI (Flask) 在主线程运行
- Gateway (FastAPI/uvicorn) 在后台线程运行
- 共享 AgentContext._contexts 内存字典
"""

import argparse
import logging
import os
import sys
import threading
import time
from pathlib import Path

# 确保项目根目录在 Python 路径中
sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("agent-zero")


def run_gateway_in_thread(host: str, port: int, log_level: str):
    """在独立线程中运行 Gateway"""
    import asyncio
    import uvicorn

    # 创建新的事件循环
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    config = uvicorn.Config(
        "python.gateway.server:app",
        host=host,
        port=port,
        log_level=log_level,
        loop="asyncio",
    )
    server = uvicorn.Server(config)

    try:
        loop.run_until_complete(server.serve())
    except Exception as e:
        logger.error(f"Gateway error: {e}")
    finally:
        loop.close()


def main():
    parser = argparse.ArgumentParser(
        description="Agent Zero - Web UI + Gateway 统一启动"
    )

    # Web UI 参数
    parser.add_argument("--ui-host", default="0.0.0.0", help="Web UI bind host")
    parser.add_argument("--ui-port", type=int, default=50001, help="Web UI port")

    # Gateway 参数
    parser.add_argument("--gateway-host", default="127.0.0.1", help="Gateway bind host")
    parser.add_argument("--gateway-port", type=int, default=18900, help="Gateway port")
    parser.add_argument("--gateway-config", default="conf/gateway.yaml", help="Gateway config")

    # 通用参数
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    parser.add_argument("--gateway-only", action="store_true", help="Only run Gateway")
    parser.add_argument("--ui-only", action="store_true", help="Only run Web UI")

    args = parser.parse_args()

    # 设置环境变量
    os.environ["GATEWAY_CONFIG_PATH"] = args.gateway_config
    os.environ["GATEWAY_PORT"] = str(args.gateway_port)
    os.environ["GATEWAY_HOST"] = args.gateway_host

    log_level = "debug" if args.verbose else "info"

    if args.gateway_only:
        # 仅运行 Gateway
        logger.info(f"Starting Gateway only on {args.gateway_host}:{args.gateway_port}")
        from python.gateway.server import run_gateway
        run_gateway(
            host=args.gateway_host,
            port=args.gateway_port,
            log_level=log_level,
        )
        return

    if args.ui_only:
        # 仅运行 Web UI
        logger.info(f"Starting Web UI only on {args.ui_host}:{args.ui_port}")
        from run_ui import main as run_ui_main
        sys.argv = [sys.argv[0], "--host", args.ui_host, "--port", str(args.ui_port)]
        run_ui_main()
        return

    # 同时运行 Gateway 和 Web UI
    logger.info("=" * 60)
    logger.info("Agent Zero - 单进程并行架构启动")
    logger.info("=" * 60)
    logger.info(f"Web UI:  http://{args.ui_host}:{args.ui_port}")
    logger.info(f"Gateway: http://{args.gateway_host}:{args.gateway_port}")
    logger.info("AgentContext: 共享内存模式")
    logger.info("=" * 60)

    # 启动 Gateway 线程
    gateway_thread = threading.Thread(
        target=run_gateway_in_thread,
        args=(args.gateway_host, args.gateway_port, log_level),
        daemon=True,
        name="GatewayThread"
    )
    gateway_thread.start()
    logger.info("Gateway thread started")

    # 等待 Gateway 启动
    time.sleep(1)

    # 在主线程运行 Web UI
    try:
        from run_ui import main as run_ui_main
        logger.info("Starting Web UI in main thread...")
        sys.argv = [sys.argv[0], "--host", args.ui_host, "--port", str(args.ui_port)]
        run_ui_main()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.error(f"Web UI error: {e}")


if __name__ == "__main__":
    main()
