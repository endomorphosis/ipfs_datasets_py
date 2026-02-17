"""Router integration helper for vector stores.

This module provides integration between vector stores and the embeddings_router
and ipfs_backend_router for automatic embedding generation and IPFS storage.
"""

import logging
from typing import List, Dict, Any, Optional, Union
import anyio

logger = logging.getLogger(__name__)


class RouterIntegration:
    """Helper class for integrating routers with vector stores.
    
    Provides convenient methods for:
    - Generating embeddings via embeddings_router
    - Storing data to IPFS via ipfs_backend_router
    - Loading data from IPFS
    """
    
    def __init__(self, 
                 use_embeddings_router: bool = True,
                 use_ipfs_router: bool = True,
                 embeddings_provider: Optional[str] = None,
                 ipfs_backend: Optional[str] = None,
                 router_deps: Optional[Any] = None):
        """Initialize router integration.
        
        Args:
            use_embeddings_router: Enable embeddings router
            use_ipfs_router: Enable IPFS router
            embeddings_provider: Preferred embeddings provider
            ipfs_backend: Preferred IPFS backend
            router_deps: Optional RouterDeps instance
        """
        self.use_embeddings_router = use_embeddings_router
        self.use_ipfs_router = use_ipfs_router
        self.embeddings_provider = embeddings_provider
        self.ipfs_backend = ipfs_backend
        self.router_deps = router_deps
        
        # Lazy-loaded routers
        self._embeddings_module = None
        self._ipfs_module = None
    
    def _get_embeddings_module(self):
        """Lazy-load embeddings router module."""
        if self._embeddings_module is None:
            try:
                from .. import embeddings_router
                self._embeddings_module = embeddings_router
            except ImportError as e:
                logger.warning(f"Failed to import embeddings_router: {e}")
                self._embeddings_module = None
        return self._embeddings_module
    
    def _get_ipfs_module(self):
        """Lazy-load IPFS router module."""
        if self._ipfs_module is None:
            try:
                from .. import ipfs_backend_router
                self._ipfs_module = ipfs_backend_router
            except ImportError as e:
                logger.warning(f"Failed to import ipfs_backend_router: {e}")
                self._ipfs_module = None
        return self._ipfs_module
    
    async def generate_embeddings(self, 
                                  texts: Union[str, List[str]],
                                  model: Optional[str] = None,
                                  **kwargs) -> List[List[float]]:
        """Generate embeddings for texts using embeddings_router.
        
        Args:
            texts: Text or list of texts to embed
            model: Model name to use (optional)
            **kwargs: Additional parameters for embedding generation
            
        Returns:
            List of embedding vectors
            
        Raises:
            ValueError: If embeddings router is not enabled
            RuntimeError: If embedding generation fails
        """
        if not self.use_embeddings_router:
            raise ValueError("Embeddings router is not enabled")
        
        embeddings_module = self._get_embeddings_module()
        if embeddings_module is None:
            raise RuntimeError("Embeddings router module not available")
        
        # Normalize to list
        if isinstance(texts, str):
            texts = [texts]
        
        try:
            # Use the generate_embeddings function from embeddings_router
            if hasattr(embeddings_module, 'generate_embeddings'):
                results = await anyio.to_thread.run_sync(
                    embeddings_module.generate_embeddings,
                    texts,
                    provider=self.embeddings_provider or kwargs.pop('provider', None),
                    model=model,
                    **kwargs
                )
                return results
            else:
                # Fallback to simpler interface if available
                logger.warning("generate_embeddings not found, attempting fallback")
                raise RuntimeError("Embeddings generation interface not available")
                
        except Exception as e:
            logger.error(f"Failed to generate embeddings: {e}")
            raise RuntimeError(f"Embedding generation failed: {e}")
    
    async def store_to_ipfs(self, 
                           data: bytes,
                           pin: bool = False,
                           codec: str = "raw") -> str:
        """Store data to IPFS using ipfs_backend_router.
        
        Args:
            data: Bytes to store
            pin: Whether to pin the data
            codec: IPLD codec to use
            
        Returns:
            CID of the stored data
            
        Raises:
            ValueError: If IPFS router is not enabled
            RuntimeError: If storage fails
        """
        if not self.use_ipfs_router:
            raise ValueError("IPFS router is not enabled")
        
        ipfs_module = self._get_ipfs_module()
        if ipfs_module is None:
            raise RuntimeError("IPFS router module not available")
        
        try:
            # Get backend from router
            backend = None
            if hasattr(ipfs_module, 'get_ipfs_backend'):
                backend = ipfs_module.get_ipfs_backend(
                    backend_name=self.ipfs_backend
                )
            elif hasattr(ipfs_module, '_get_backend'):
                backend = ipfs_module._get_backend()
            
            if backend is None:
                raise RuntimeError("Could not obtain IPFS backend")
            
            # Store data
            if codec == "raw":
                cid = backend.add_bytes(data, pin=pin)
            else:
                cid = backend.block_put(data, codec=codec)
            
            logger.debug(f"Stored data to IPFS: {cid}")
            return cid
            
        except Exception as e:
            logger.error(f"Failed to store to IPFS: {e}")
            raise RuntimeError(f"IPFS storage failed: {e}")
    
    async def load_from_ipfs(self, cid: str) -> bytes:
        """Load data from IPFS using ipfs_backend_router.
        
        Args:
            cid: CID to retrieve
            
        Returns:
            Retrieved data bytes
            
        Raises:
            ValueError: If IPFS router is not enabled
            RuntimeError: If retrieval fails
        """
        if not self.use_ipfs_router:
            raise ValueError("IPFS router is not enabled")
        
        ipfs_module = self._get_ipfs_module()
        if ipfs_module is None:
            raise RuntimeError("IPFS router module not available")
        
        try:
            # Get backend from router
            backend = None
            if hasattr(ipfs_module, 'get_ipfs_backend'):
                backend = ipfs_module.get_ipfs_backend(
                    backend_name=self.ipfs_backend
                )
            elif hasattr(ipfs_module, '_get_backend'):
                backend = ipfs_module._get_backend()
            
            if backend is None:
                raise RuntimeError("Could not obtain IPFS backend")
            
            # Retrieve data
            data = backend.cat(cid)
            logger.debug(f"Loaded data from IPFS: {cid}")
            return data
            
        except Exception as e:
            logger.error(f"Failed to load from IPFS: {e}")
            raise RuntimeError(f"IPFS retrieval failed: {e}")
    
    async def block_put(self, data: bytes, codec: str = "dag-cbor") -> str:
        """Store IPLD block to IPFS.
        
        Args:
            data: Block data
            codec: IPLD codec (dag-cbor, dag-json, raw, etc.)
            
        Returns:
            CID of the block
        """
        return await self.store_to_ipfs(data, codec=codec)
    
    async def block_get(self, cid: str) -> bytes:
        """Retrieve IPLD block from IPFS.
        
        Args:
            cid: Block CID
            
        Returns:
            Block data
        """
        return await self.load_from_ipfs(cid)
    
    async def dag_export(self, root_cid: str) -> bytes:
        """Export a DAG as CAR data.
        
        Args:
            root_cid: Root CID of the DAG
            
        Returns:
            CAR format bytes
            
        Raises:
            RuntimeError: If export fails
        """
        if not self.use_ipfs_router:
            raise ValueError("IPFS router is not enabled")
        
        ipfs_module = self._get_ipfs_module()
        if ipfs_module is None:
            raise RuntimeError("IPFS router module not available")
        
        try:
            backend = None
            if hasattr(ipfs_module, 'get_ipfs_backend'):
                backend = ipfs_module.get_ipfs_backend(
                    backend_name=self.ipfs_backend
                )
            elif hasattr(ipfs_module, '_get_backend'):
                backend = ipfs_module._get_backend()
            
            if backend is None:
                raise RuntimeError("Could not obtain IPFS backend")
            
            if not hasattr(backend, 'dag_export'):
                raise RuntimeError("Backend does not support dag_export")
            
            car_data = backend.dag_export(root_cid)
            logger.debug(f"Exported DAG to CAR: {root_cid}")
            return car_data
            
        except Exception as e:
            logger.error(f"Failed to export DAG: {e}")
            raise RuntimeError(f"DAG export failed: {e}")
    
    def is_embeddings_available(self) -> bool:
        """Check if embeddings router is available and enabled.
        
        Returns:
            True if embeddings router can be used
        """
        return self.use_embeddings_router and self._get_embeddings_module() is not None
    
    def is_ipfs_available(self) -> bool:
        """Check if IPFS router is available and enabled.
        
        Returns:
            True if IPFS router can be used
        """
        return self.use_ipfs_router and self._get_ipfs_module() is not None


def create_router_integration(
    use_embeddings: bool = True,
    use_ipfs: bool = True,
    embeddings_provider: Optional[str] = None,
    ipfs_backend: Optional[str] = None
) -> RouterIntegration:
    """Create a router integration instance.
    
    Args:
        use_embeddings: Enable embeddings router
        use_ipfs: Enable IPFS router
        embeddings_provider: Preferred embeddings provider
        ipfs_backend: Preferred IPFS backend
        
    Returns:
        RouterIntegration instance
    """
    return RouterIntegration(
        use_embeddings_router=use_embeddings,
        use_ipfs_router=use_ipfs,
        embeddings_provider=embeddings_provider,
        ipfs_backend=ipfs_backend
    )


__all__ = [
    'RouterIntegration',
    'create_router_integration',
]
