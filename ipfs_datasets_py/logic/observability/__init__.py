"""
Observability utilities for MCP++ and GraphRAG systems.

Provides:
- Structured JSON logging with standard schema
- Performance measurement and tracking  
- Log context propagation
- Log parsing and analysis helpers
"""

from .structured_logging import (
    # Schema
    LOG_SCHEMA_VERSION,
    LogField,
    EventType,
    
    # Context
    LogContext,
    get_current_context,
    set_context,
    clear_context,
    
    # Logging
    get_logger,
    JSONLogFormatter,
    
    # Convenience functions
    log_event,
    log_error,
    log_performance,
    log_mcp_tool,
    
    # Performance tracking
    LogPerformance,
    
    # Analysis
    parse_json_log_file,
    filter_logs,
)

__all__ = [
    # Schema
    "LOG_SCHEMA_VERSION",
    "LogField",
    "EventType",
    
    # Context
    "LogContext",
    "get_current_context",
    "set_context",
    "clear_context",
    
    # Logging
    "get_logger",
    "JSONLogFormatter",
    
    # Convenience
    "log_event",
    "log_error",
    "log_performance",
    "log_mcp_tool",
    
    # Performance
    "LogPerformance",
    
    # Analysis
    "parse_json_log_file",
    "filter_logs",
]
