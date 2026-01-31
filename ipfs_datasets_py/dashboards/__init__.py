"""Dashboard modules for IPFS Datasets Python."""

# NOTE:
# Keep this package initializer lightweight.
# Dashboard modules can have heavy/optional dependencies; importing them all here
# can break test collection in minimal environments.

__all__ = [
    'admin_dashboard',
    'advanced_analytics_dashboard',
    'common_crawl_dashboard',
    'discord_dashboard',
    'mcp_dashboard',
    'mcp_investigation_dashboard',
    'news_analysis_dashboard',
    'patent_dashboard',
    'provenance_dashboard',
    'unified_monitoring_dashboard',
]
