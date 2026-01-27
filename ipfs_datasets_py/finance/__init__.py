"""
Finance Data Package.

This module provides core finance data collection and analysis functionality.
It re-exports tools from the MCP server for direct package use.

Components:
- Stock market data scrapers
- News scrapers (AP, Reuters, Bloomberg)  
- GraphRAG news analyzer
- Embedding correlation analysis
- Financial theorems

Usage:
    from ipfs_datasets_py.finance import StockScraper, NewsScraper
"""

# Import from MCP server tools (these are the core implementations)
try:
    from ipfs_datasets_py.mcp_server.tools.finance_data_tools.stock_scrapers import (
        StockDataPoint,
        get_stock_data,
        get_stock_data_yfinance,
    )
    STOCK_AVAILABLE = True
except ImportError:
    STOCK_AVAILABLE = False
    StockDataPoint = None
    get_stock_data = None
    get_stock_data_yfinance = None

try:
    from ipfs_datasets_py.mcp_server.tools.finance_data_tools.news_scrapers import (
        scrape_reuters_news,
        scrape_ap_news,
        scrape_bloomberg_news,
        scrape_financial_news,
    )
    NEWS_AVAILABLE = True
except ImportError:
    NEWS_AVAILABLE = False
    scrape_reuters_news = None
    scrape_ap_news = None
    scrape_bloomberg_news = None
    scrape_financial_news = None

try:
    from ipfs_datasets_py.mcp_server.tools.finance_data_tools.graphrag_news_analyzer import (
        analyze_news_with_graphrag,
        create_financial_knowledge_graph,
    )
    GRAPHRAG_AVAILABLE = True
except ImportError:
    GRAPHRAG_AVAILABLE = False
    analyze_news_with_graphrag = None
    create_financial_knowledge_graph = None

try:
    from ipfs_datasets_py.mcp_server.tools.finance_data_tools.embedding_correlation import (
        calculate_embedding_correlation,
        analyze_multimodal_correlations,
    )
    EMBEDDING_AVAILABLE = True
except ImportError:
    EMBEDDING_AVAILABLE = False
    calculate_embedding_correlation = None
    analyze_multimodal_correlations = None

try:
    from ipfs_datasets_py.mcp_server.tools.finance_data_tools.finance_theorems import (
        list_finance_theorems,
        apply_theorem,
        validate_theorem_assumptions,
    )
    THEOREMS_AVAILABLE = True
except ImportError:
    THEOREMS_AVAILABLE = False
    list_finance_theorems = None
    apply_theorem = None
    validate_theorem_assumptions = None


__all__ = [
    # Stock tools
    'StockDataPoint',
    'get_stock_data',
    'get_stock_data_yfinance',
    'STOCK_AVAILABLE',
    
    # News tools
    'scrape_reuters_news',
    'scrape_ap_news',
    'scrape_bloomberg_news',
    'scrape_financial_news',
    'NEWS_AVAILABLE',
    
    # GraphRAG tools
    'analyze_news_with_graphrag',
    'create_financial_knowledge_graph',
    'GRAPHRAG_AVAILABLE',
    
    # Embedding tools
    'calculate_embedding_correlation',
    'analyze_multimodal_correlations',
    'EMBEDDING_AVAILABLE',
    
    # Theorem tools
    'list_finance_theorems',
    'apply_theorem',
    'validate_theorem_assumptions',
    'THEOREMS_AVAILABLE',
]
