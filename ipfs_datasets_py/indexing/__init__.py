"""
Index Management Module

This module provides core index management functionality including:
- Index loading and creation
- Shard management and distribution
- Index status monitoring and performance tracking
- Index optimization and configuration

The module is designed to be used by MCP tools and other components
that need index management capabilities.
"""

from .index_manager_core import (
    # Enums
    IndexType,
    IndexStatus,
    ShardingStrategy,
    
    # Core classes
    MockIndexManager,
    IndexManagerCore,
    
    # Core functions
    load_index_core,
    manage_shards_core,
    monitor_index_status_core,
    manage_index_configuration_core,
)

__all__ = [
    # Enums
    "IndexType",
    "IndexStatus",
    "ShardingStrategy",
    
    # Classes
    "MockIndexManager",
    "IndexManagerCore",
    
    # Core functions
    "load_index_core",
    "manage_shards_core",
    "monitor_index_status_core",
    "manage_index_configuration_core",
]
