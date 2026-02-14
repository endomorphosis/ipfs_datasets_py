#!/usr/bin/env python3
import sys
import traceback

from ipfs_datasets_py.dashboards.mcp_dashboard import MCPDashboard, MCPDashboardConfig


def main():
    dash = MCPDashboard()
    dash.configure(MCPDashboardConfig(host="127.0.0.1", port=8899, open_browser=False))
    app = dash.app
    app.testing = True
    client = app.test_client()
    try:
        resp = client.get('/mcp/caselaw')
        print('Status:', resp.status)
        print('Data head:', resp.data[:500])
    except Exception:
        print('Exception during GET /mcp/caselaw:')
        traceback.print_exc()
        raise


if __name__ == '__main__':
    main()
