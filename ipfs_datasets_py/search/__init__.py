# ipfs_datasets_py/search/__init__.py
try:
    from .search_embeddings import search_embeddings
    __all__ = ['search_embeddings']
except ImportError as e:
    from .search_embeddings_mock import search_embeddings
    __all__ = ['search_embeddings']
    import warnings
    warnings.warn(f"search_embeddings using mock implementation due to missing dependencies: {e}")

# Also make the module available for patching
try:
    from . import search_embeddings as search_embeddings_module
except ImportError:
    from . import search_embeddings_mock as search_embeddings_module
