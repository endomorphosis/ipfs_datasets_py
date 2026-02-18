# ipfs_datasets_py/mcp_server/tools/index_management_tools/index_management_tools.py
"""
Index Management Tools for MCP Server

Thin wrapper module that provides MCP tool interfaces for index management.
All core business logic has been extracted to ipfs_datasets_py.indexing.index_manager_core.

This module maintains backwards compatibility while delegating to the core implementation.
"""

from typing import Dict, Any, List, Optional

# Import all core functionality from the indexing module
from ipfs_datasets_py.indexing import (
    # Enums
    IndexType,
    IndexStatus,
    ShardingStrategy,
    
    # Classes
    MockIndexManager,
    
    # Core functions
    load_index_core,
    manage_shards_core,
    monitor_index_status_core,
    manage_index_configuration_core,
)


async def load_index(
    action: str,
    dataset: Optional[str] = None,
    knn_index: Optional[str] = None,
    dataset_split: str = "train",
    knn_index_split: str = "train",
    columns: str = "text",
    index_config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Load and manage vector indices.
    
    MCP tool wrapper that delegates to core implementation.
    
    Args:
        action: Action to perform ('load', 'create', 'reload', 'unload', 'status', 'optimize')
        dataset: Dataset name to load index for
        knn_index: KNN index name or path
        dataset_split: Dataset split to use ('train', 'test', 'validation', 'all')
        knn_index_split: Index split to use
        columns: Columns to include in the index
        index_config: Index configuration parameters
        
    Returns:
        Dictionary containing operation result and metadata
    """
    return await load_index_core(
        action=action,
        dataset=dataset,
        knn_index=knn_index,
        dataset_split=dataset_split,
        knn_index_split=knn_index_split,
        columns=columns,
        index_config=index_config
    )


async def manage_shards(
    action: str,
    dataset: Optional[str] = None,
    num_shards: int = 4,
    shard_size: str = "auto",
    sharding_strategy: str = "clustering",
    models: Optional[List[str]] = None,
    shard_ids: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Manage index shards and distributed indexing.
    
    MCP tool wrapper that delegates to core implementation.
    
    Args:
        action: Shard management action ('create_shards', 'list_shards', 'rebalance', 'merge_shards', 'status', 'distribute')
        dataset: Dataset name for shard operations
        num_shards: Number of shards to create
        shard_size: Size strategy for shards ('auto', '1GB', '500MB', etc.)
        sharding_strategy: Strategy for sharding ('clustering', 'hash', 'round_robin', 'size_based')
        models: List of models to consider for sharding
        shard_ids: List of shard IDs for operations like merging
        
    Returns:
        Dictionary containing shard operation result and metadata
    """
    return await manage_shards_core(
        action=action,
        dataset=dataset,
        num_shards=num_shards,
        shard_size=shard_size,
        sharding_strategy=sharding_strategy,
        models=models,
        shard_ids=shard_ids
    )


async def monitor_index_status(
    index_id: Optional[str] = None,
    metrics: Optional[List[str]] = None,
    time_range: str = "24h",
    include_details: bool = False
) -> Dict[str, Any]:
    """
    Monitor index health and performance.
    
    MCP tool wrapper that delegates to core implementation.
    
    Args:
        index_id: Specific index ID to monitor (if None, monitors all indices)
        metrics: List of metrics to include ('performance', 'health', 'usage', 'errors', 'all')
        time_range: Time range for metrics ('1h', '6h', '24h', '7d', '30d')
        include_details: Whether to include detailed diagnostics
        
    Returns:
        Dictionary containing index status and performance metrics
    """
    return await monitor_index_status_core(
        index_id=index_id,
        metrics=metrics,
        time_range=time_range,
        include_details=include_details
    )


async def manage_index_configuration(
    action: str,
    index_id: Optional[str] = None,
    config_updates: Optional[Dict[str, Any]] = None,
    optimization_level: int = 1
) -> Dict[str, Any]:
    """
    Manage index configuration and optimization settings.
    
    MCP tool wrapper that delegates to core implementation.
    
    Args:
        action: Configuration action ('get_config', 'update_config', 'optimize_config', 'reset_config')
        index_id: Index ID to configure
        config_updates: Configuration updates to apply
        optimization_level: Level of optimization (1-3, higher is more aggressive)
        
    Returns:
        Dictionary containing configuration operation result
    """
    return await manage_index_configuration_core(
        action=action,
        index_id=index_id,
        config_updates=config_updates,
        optimization_level=optimization_level
    )


# Convenience wrapper functions for backwards compatibility
async def index_loading_tool(**kwargs) -> Dict[str, Any]:
    """Convenience wrapper for load_index function."""
    return await load_index(**kwargs)


async def shard_management_tool(**kwargs) -> Dict[str, Any]:
    """Convenience wrapper for manage_shards function."""
    return await manage_shards(**kwargs)


async def index_status_tool(**kwargs) -> Dict[str, Any]:
    """Convenience wrapper for monitor_index_status function."""
    return await monitor_index_status(**kwargs)


async def index_config_tool(**kwargs) -> Dict[str, Any]:
    """Convenience wrapper for manage_index_configuration function."""
    return await manage_index_configuration(**kwargs)
