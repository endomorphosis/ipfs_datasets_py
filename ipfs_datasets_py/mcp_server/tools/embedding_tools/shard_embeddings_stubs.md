# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/embedding_tools/shard_embeddings.py'

Files last updated: 1751408933.6964564

Stub file last updated: 2025-07-07 02:26:16

## merge_embedding_shards

```python
async def merge_embedding_shards(manifest_file: str, output_file: str, merge_strategy: str = "sequential", **kwargs) -> Dict[str, Any]:
    """
    Merge previously sharded embeddings back into a single file.

Args:
    manifest_file: Path to the sharding manifest file
    output_file: Path for the merged output file
    merge_strategy: Strategy for merging (sequential, clustered)
    **kwargs: Additional parameters

Returns:
    Dict containing merge results
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## shard_embeddings_by_cluster

```python
async def shard_embeddings_by_cluster(embeddings_data: Union[str, List[Dict[str, Any]]], output_directory: str, num_clusters: int = 10, clustering_method: str = "kmeans", shard_size: int = 1000, **kwargs) -> Dict[str, Any]:
    """
    Shard embeddings by clustering similar vectors together.

Args:
    embeddings_data: Path to embeddings file or list of embedding dicts
    output_directory: Directory to save sharded embeddings
    num_clusters: Number of clusters to create
    clustering_method: Clustering algorithm to use (kmeans, hierarchical)
    shard_size: Maximum number of embeddings per shard within each cluster
    **kwargs: Additional parameters

Returns:
    Dict containing cluster-based sharding results
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## shard_embeddings_by_dimension

```python
async def shard_embeddings_by_dimension(embeddings_data: Union[str, List[Dict[str, Any]]], output_directory: str, shard_size: int = 1000, dimension_chunks: Optional[int] = None, metadata: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
    """
    Shard embeddings by splitting high-dimensional vectors into smaller chunks.

Args:
    embeddings_data: Path to embeddings file or list of embedding dicts
    output_directory: Directory to save sharded embeddings
    shard_size: Maximum number of embeddings per shard
    dimension_chunks: Number of dimensions per chunk (for dimension-based sharding)
    metadata: Additional metadata to include
    **kwargs: Additional parameters

Returns:
    Dict containing sharding results and metadata
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A
