"""Common Crawl Search Engine Dashboard Integration.

This module provides integration of the Common Crawl dashboard as a subdashboard
within the main IPFS Datasets Python dashboard system.
"""

import logging
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class CommonCrawlDashboardIntegration:
    """
    Integration wrapper for the Common Crawl dashboard.
    
    This class provides methods to:
    1. Embed the Common Crawl dashboard as an iframe subdashboard
    2. Proxy requests to a standalone Common Crawl MCP server
    3. Provide unified navigation between subdashboards
    
    The Common Crawl dashboard can run in two modes:
    - **Embedded**: Dashboard runs within the same process
    - **Remote**: Dashboard proxies to a standalone MCP server
    """
    
    def __init__(
        self,
        mode: str = "embedded",
        remote_endpoint: Optional[str] = None,
        port: int = 8788,
        **kwargs
    ):
        """
        Initialize the Common Crawl dashboard integration.
        
        Args:
            mode: "embedded" or "remote"
            remote_endpoint: URL of remote MCP server (for remote mode)
            port: Port to run embedded dashboard on (default: 8788)
            **kwargs: Additional configuration
        """
        self.mode = mode
        self.remote_endpoint = remote_endpoint
        self.port = port
        self.dashboard_app = None
        self.is_running = False
        
        # Check if submodule is available
        submodule_path = Path(__file__).parent.parent / "web_archiving" / "common_crawl_search_engine"
        self.submodule_available = submodule_path.exists()
        
        if not self.submodule_available and mode == "embedded":
            logger.warning("Common Crawl submodule not available, falling back to remote mode")
            self.mode = "remote"
    
    def start_embedded_dashboard(self) -> bool:
        """
        Start the embedded Common Crawl dashboard.
        
        Returns:
            True if started successfully, False otherwise
        """
        if self.mode != "embedded" or not self.submodule_available:
            logger.error("Cannot start embedded dashboard")
            return False
        
        try:
            # Import dashboard module from submodule
            from common_crawl_search_engine.ccindex import dashboard_app
            
            # Start dashboard in background
            import threading
            
            def run_dashboard():
                try:
                    dashboard_app.run(host="127.0.0.1", port=self.port)
                except Exception as e:
                    logger.error(f"Dashboard failed: {e}")
            
            thread = threading.Thread(target=run_dashboard, daemon=True)
            thread.start()
            
            self.is_running = True
            logger.info(f"Common Crawl dashboard started on port {self.port}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start embedded dashboard: {e}")
            return False
    
    def get_dashboard_url(self) -> str:
        """
        Get the URL for the Common Crawl dashboard.
        
        Returns:
            Dashboard URL
        """
        if self.mode == "embedded":
            return f"http://127.0.0.1:{self.port}"
        elif self.mode == "remote" and self.remote_endpoint:
            return self.remote_endpoint
        else:
            return ""
    
    def get_iframe_config(self) -> Dict[str, Any]:
        """
        Get configuration for embedding as iframe.
        
        Returns:
            Dict with iframe configuration
        """
        return {
            "name": "common_crawl",
            "title": "Common Crawl Search",
            "url": self.get_dashboard_url(),
            "icon": "🌐",
            "description": "Search and analyze Common Crawl data",
            "category": "web_archive",
            "features": [
                "Domain search across Common Crawl archives",
                "WARC record fetching",
                "Collection management",
                "Index building and querying"
            ]
        }
    
    def get_nav_item(self) -> Dict[str, str]:
        """
        Get navigation item for main dashboard menu.
        
        Returns:
            Dict with nav item configuration
        """
        return {
            "id": "common-crawl",
            "label": "Common Crawl",
            "icon": "🌐",
            "url": "/subdashboard/common-crawl",
            "category": "Web Archive"
        }
    
    def get_mcp_proxy_config(self) -> Dict[str, Any]:
        """
        Get configuration for MCP endpoint proxying.
        
        Returns:
            Dict with proxy configuration
        """
        return {
            "path": "/api/mcp/common-crawl",
            "target": f"{self.get_dashboard_url()}/mcp",
            "methods": ["POST"],
            "description": "Proxy for Common Crawl MCP JSON-RPC endpoint"
        }
    
    def health_check(self) -> Dict[str, Any]:
        """
        Check if the dashboard is accessible.
        
        Returns:
            Dict with health status
        """
        import requests
        
        url = self.get_dashboard_url()
        if not url:
            return {
                "status": "unavailable",
                "mode": self.mode,
                "message": "No dashboard URL configured"
            }
        
        try:
            response = requests.get(f"{url}/api/health", timeout=5)
            if response.status_code == 200:
                return {
                    "status": "healthy",
                    "mode": self.mode,
                    "url": url
                }
            else:
                return {
                    "status": "unhealthy",
                    "mode": self.mode,
                    "url": url,
                    "status_code": response.status_code
                }
        except Exception as e:
            return {
                "status": "error",
                "mode": self.mode,
                "url": url,
                "error": str(e)
            }


def create_dashboard_integration(**kwargs) -> CommonCrawlDashboardIntegration:
    """
    Create a Common Crawl dashboard integration instance.
    
    Args:
        **kwargs: Configuration options
        
    Returns:
        CommonCrawlDashboardIntegration instance
    """
    return CommonCrawlDashboardIntegration(**kwargs)


# Export dashboard routes for Flask/FastAPI integration
def register_dashboard_routes(app, prefix="/subdashboard/common-crawl"):
    """
    Register Common Crawl dashboard routes with a Flask/FastAPI app.
    
    Args:
        app: Flask or FastAPI application instance
        prefix: URL prefix for dashboard routes
    """
    integration = CommonCrawlDashboardIntegration()
    
    # Check if Flask or FastAPI
    try:
        from flask import render_template_string, jsonify
        
        # Flask routes
        @app.route(f"{prefix}")
        def common_crawl_dashboard():
            """Render Common Crawl dashboard page."""
            template = """
            <!DOCTYPE html>
            <html>
            <head>
                <title>Common Crawl Search Engine</title>
                <style>
                    body, html { margin: 0; padding: 0; height: 100%; overflow: hidden; }
                    iframe { width: 100%; height: 100%; border: none; }
                </style>
            </head>
            <body>
                <iframe src="{{ dashboard_url }}" sandbox="allow-same-origin allow-scripts allow-forms allow-popups"></iframe>
            </body>
            </html>
            """
            return render_template_string(template, dashboard_url=integration.get_dashboard_url())
        
        @app.route(f"{prefix}/health")
        def common_crawl_health():
            """Health check endpoint."""
            return jsonify(integration.health_check())
        
        @app.route(f"{prefix}/config")
        def common_crawl_config():
            """Get dashboard configuration."""
            return jsonify(integration.get_iframe_config())
        
        logger.info(f"Registered Common Crawl dashboard routes at {prefix}")
        
    except ImportError:
        logger.warning("Flask not available, skipping route registration")


__all__ = [
    "CommonCrawlDashboardIntegration",
    "create_dashboard_integration",
    "register_dashboard_routes",
]
