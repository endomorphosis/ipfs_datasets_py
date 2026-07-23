"""Launcher for the native IPFS Datasets MCP dashboard."""

from __future__ import annotations

import argparse
import signal
import time

from ipfs_datasets_py.dashboards.mcp_dashboard import MCPDashboard, MCPDashboardConfig


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch the IPFS Datasets MCP dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8899)
    parser.add_argument("--mcp-host", default="127.0.0.1")
    parser.add_argument("--mcp-port", type=int, default=3002)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dashboard = MCPDashboard()
    dashboard.configure(
        MCPDashboardConfig(
            host=args.host,
            port=args.port,
            open_browser=False,
            mcp_server_host=args.mcp_host,
            mcp_server_port=args.mcp_port,
        )
    )

    if not dashboard.start():
        return 1

    running = True

    def _shutdown(_signum: int, _frame: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    try:
      while running:
        time.sleep(1)
    finally:
      dashboard.stop()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())