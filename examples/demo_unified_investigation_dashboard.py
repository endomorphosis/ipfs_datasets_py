#!/usr/bin/env python3
"""
Unified Investigation Dashboard Demo

This script demonstrates the new unified investigation dashboard that removes
role-specific buttons and provides a single entity-centric interface for
analyzing large unstructured archives.
"""

import anyio
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent))

from ipfs_datasets_py.dashboards.news_analysis_dashboard import (
    create_unified_investigation_dashboard,
    MCPDashboardConfig
)

logger = logging.getLogger(__name__)


def main():
    """Run the unified investigation dashboard demo."""
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    logger.info("Starting Unified Investigation Dashboard Demo")
    
    try:
        # Create dashboard configuration
        config = MCPDashboardConfig()
        
        # Create unified investigation dashboard
        logger.info("Creating unified investigation dashboard...")
        dashboard = create_unified_investigation_dashboard(config)
        
        logger.info("Dashboard created successfully!")
        logger.info("Starting server...")
        
        # Start the dashboard server
        dashboard.start_server(host="localhost", port=8080)
        
    except KeyboardInterrupt:
        logger.info("Dashboard stopped by user")
    except Exception as e:
        logger.error(f"Dashboard error: {str(e)}")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())