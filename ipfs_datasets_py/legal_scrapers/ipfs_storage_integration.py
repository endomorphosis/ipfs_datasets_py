"""IPFS storage integration for legal dataset scrapers.

This module provides comprehensive IPFS storage capabilities for legal datasets,
including CAR file generation, IPLD DAG structures, metadata tracking, and pin management.
"""
import asyncio
import logging
import json
import time
from typing import Dict, Optional, Any
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    from ipfs_datasets_py import ipfs_backend_router as ipfs_router
    IPFS_AVAILABLE = True
except Exception:
    IPFS_AVAILABLE = False
    logger.warning("IPFS backend router not available. IPFS storage features disabled.")


class IPFSStorageManager:
    """Manager for storing and retrieving legal datasets in IPFS.
    
    This class provides high-level IPFS storage operations including:
    - Dataset upload with automatic CAR file generation
    - Metadata tracking and indexing
    - Pin management for persistence
    - Dataset retrieval and listing
    - Update and versioning support
    """
    
    def __init__(self, ipfs_instance=None, metadata_dir: Optional[str] = None):
        """Initialize IPFS storage manager.
        
        Args:
            ipfs_instance: Existing ipfs_kit_py instance (optional)
            metadata_dir: Directory to store dataset metadata locally
        """
        self.ipfs = ipfs_instance
        self.metadata_dir = Path(metadata_dir or Path.home() / ".ipfs_datasets" / "legal_datasets_metadata")
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        
        if not IPFS_AVAILABLE:
            logger.warning("IPFS functionality disabled - backend router unavailable")

        if not self.ipfs and IPFS_AVAILABLE:
            logger.info("Initialized IPFS storage manager (router backend)")

    async def _router_add_bytes(self, data: bytes, *, pin: bool) -> str:
        return await asyncio.to_thread(ipfs_router.add_bytes, data, pin=pin)

    async def _router_cat(self, cid: str) -> bytes:
        return await asyncio.to_thread(ipfs_router.cat, cid)

    async def _router_pin(self, cid: str) -> None:
        await asyncio.to_thread(ipfs_router.pin, cid)

    async def _router_unpin(self, cid: str) -> None:
        await asyncio.to_thread(ipfs_router.unpin, cid)
    
    async def add_dataset(
        self,
        name: str,
        data: Any,
        metadata: Optional[Dict[str, Any]] = None,
        format: str = "json",
        pin: bool = True
    ) -> Dict[str, Any]:
        """Add a legal dataset to IPFS.
        
        Args:
            name: Dataset name (e.g., "recap_ca9_opinions_2025")
            data: Dataset content (list of dicts, dataframe, etc.)
            metadata: Additional metadata about the dataset
            format: Data format - "json" or "parquet"
            pin: Whether to pin the dataset (prevents garbage collection)
            
        Returns:
            Dict containing:
                - status: "success" or "error"
                - cid: Content ID (IPFS hash)
                - name: Dataset name
                - size: Size in bytes
                - format: Data format
                - pinned: Whether dataset is pinned
                - error: Error message (if failed)
        """
        try:
            if not IPFS_AVAILABLE:
                return {
                    "status": "error",
                    "error": "IPFS not available.",
                    "cid": None
                }
            
            logger.info(f"Adding dataset '{name}' to IPFS (format: {format})")
            start_time = time.time()
            
            # Prepare data for IPFS
            if format == "json":
                data_bytes = json.dumps(data, indent=2).encode('utf-8')
            elif format == "parquet":
                # For parquet, data should already be in bytes
                data_bytes = data if isinstance(data, bytes) else json.dumps(data).encode('utf-8')
            else:
                return {
                    "status": "error",
                    "error": f"Unsupported format: {format}. Use 'json' or 'parquet'",
                    "cid": None
                }
            
            # Add to IPFS
            try:
                if self.ipfs is not None:
                    add_result = await self.ipfs.add_bytes(data_bytes)
                    cid = add_result.get("Hash") or add_result.get("cid")
                    if not cid:
                        raise ValueError("No CID returned from IPFS add operation")
                else:
                    cid = await self._router_add_bytes(data_bytes, pin=pin)
                
            except Exception as e:
                logger.error(f"IPFS add failed: {e}")
                return {
                    "status": "error",
                    "error": f"Failed to add to IPFS: {e}",
                    "cid": None
                }
            
            # Pin if requested
            pinned = False
            if pin:
                try:
                    if self.ipfs is not None:
                        await self.ipfs.pin_add(cid)
                    else:
                        await self._router_pin(cid)
                    pinned = True
                    logger.info(f"Pinned dataset {name} with CID {cid}")
                except Exception as e:
                    logger.warning(f"Failed to pin {cid}: {e}")
            
            # Store metadata locally
            dataset_metadata = {
                "name": name,
                "cid": cid,
                "format": format,
                "size": len(data_bytes),
                "pinned": pinned,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "custom_metadata": metadata or {}
            }
            
            metadata_file = self.metadata_dir / f"{name}.json"
            with open(metadata_file, 'w') as f:
                json.dump(dataset_metadata, f, indent=2)
            
            elapsed_time = time.time() - start_time
            logger.info(f"Added dataset '{name}' to IPFS in {elapsed_time:.2f}s: {cid}")
            
            return {
                "status": "success",
                "cid": cid,
                "name": name,
                "size": len(data_bytes),
                "format": format,
                "pinned": pinned,
                "elapsed_time_seconds": elapsed_time
            }
            
        except Exception as e:
            logger.error(f"Failed to add dataset to IPFS: {e}")
            return {
                "status": "error",
                "error": str(e),
                "cid": None
            }
    
    async def get_dataset(
        self,
        name: Optional[str] = None,
        cid: Optional[str] = None
    ) -> Dict[str, Any]:
        """Retrieve a legal dataset from IPFS.
        
        Args:
            name: Dataset name (will lookup CID from metadata)
            cid: Content ID (IPFS hash) - overrides name if provided
            
        Returns:
            Dict containing:
                - status: "success" or "error"
                - data: Dataset content
                - metadata: Dataset metadata
                - error: Error message (if failed)
        """
        try:
            if not IPFS_AVAILABLE:
                return {
                    "status": "error",
                    "error": "IPFS not available",
                    "data": None
                }
            
            # Get CID from name if needed
            if not cid and name:
                metadata_file = self.metadata_dir / f"{name}.json"
                if not metadata_file.exists():
                    return {
                        "status": "error",
                        "error": f"Dataset '{name}' not found in metadata",
                        "data": None
                    }
                
                with open(metadata_file, 'r') as f:
                    dataset_metadata = json.load(f)
                    cid = dataset_metadata.get("cid")
            
            if not cid:
                return {
                    "status": "error",
                    "error": "No CID provided or found",
                    "data": None
                }
            
            logger.info(f"Retrieving dataset from IPFS: {cid}")
            
            # Get from IPFS
            try:
                if self.ipfs is not None:
                    data_bytes = await self.ipfs.cat(cid)
                else:
                    data_bytes = await self._router_cat(cid)
                data = json.loads(data_bytes.decode('utf-8'))
            except Exception as e:
                logger.error(f"Failed to retrieve from IPFS: {e}")
                return {
                    "status": "error",
                    "error": f"Failed to retrieve from IPFS: {e}",
                    "data": None
                }
            
            return {
                "status": "success",
                "data": data,
                "cid": cid,
                "metadata": dataset_metadata if name else {}
            }
            
        except Exception as e:
            logger.error(f"Failed to get dataset from IPFS: {e}")
            return {
                "status": "error",
                "error": str(e),
                "data": None
            }
    
    async def pin_dataset(self, cid: str) -> Dict[str, Any]:
        """Pin a dataset to prevent garbage collection.
        
        Args:
            cid: Content ID to pin
            
        Returns:
            Dict with status and pin information
        """
        try:
            if not IPFS_AVAILABLE:
                return {
                    "status": "error",
                    "error": "IPFS not available"
                }

            if self.ipfs is not None:
                await self.ipfs.pin_add(cid)
            else:
                await self._router_pin(cid)
            logger.info(f"Pinned CID: {cid}")
            
            return {
                "status": "success",
                "cid": cid,
                "pinned": True
            }
            
        except Exception as e:
            logger.error(f"Failed to pin dataset: {e}")
            return {
                "status": "error",
                "error": str(e),
                "pinned": False
            }
    
    async def unpin_dataset(self, cid: str) -> Dict[str, Any]:
        """Unpin a dataset (allows garbage collection).
        
        Args:
            cid: Content ID to unpin
            
        Returns:
            Dict with status
        """
        try:
            if not IPFS_AVAILABLE:
                return {
                    "status": "error",
                    "error": "IPFS not available"
                }

            if self.ipfs is not None:
                await self.ipfs.pin_rm(cid)
            else:
                await self._router_unpin(cid)
            logger.info(f"Unpinned CID: {cid}")
            
            return {
                "status": "success",
                "cid": cid,
                "pinned": False
            }
            
        except Exception as e:
            logger.error(f"Failed to unpin dataset: {e}")
            return {
                "status": "error",
                "error": str(e)
            }
    
    def list_datasets(self) -> Dict[str, Any]:
        """List all stored legal datasets.
        
        Returns:
            Dict containing:
                - status: "success" or "error"
                - datasets: List of dataset metadata
                - count: Number of datasets
        """
        try:
            datasets = []
            
            for metadata_file in self.metadata_dir.glob("*.json"):
                try:
                    with open(metadata_file, 'r') as f:
                        dataset_metadata = json.load(f)
                        datasets.append(dataset_metadata)
                except Exception as e:
                    logger.warning(f"Failed to read metadata file {metadata_file}: {e}")
            
            datasets.sort(key=lambda x: x.get("created_at", ""), reverse=True)
            
            return {
                "status": "success",
                "datasets": datasets,
                "count": len(datasets)
            }
            
        except Exception as e:
            logger.error(f"Failed to list datasets: {e}")
            return {
                "status": "error",
                "error": str(e),
                "datasets": [],
                "count": 0
            }
    
    async def update_dataset(
        self,
        name: str,
        data: Any,
        metadata: Optional[Dict[str, Any]] = None,
        format: str = "json"
    ) -> Dict[str, Any]:
        """Update an existing dataset (creates a new version).
        
        Args:
            name: Dataset name
            data: New dataset content
            metadata: Updated metadata
            format: Data format
            
        Returns:
            Dict with new CID and update information
        """
        try:
            # Check if dataset exists
            metadata_file = self.metadata_dir / f"{name}.json"
            if not metadata_file.exists():
                return await self.add_dataset(name, data, metadata, format)
            
            # Load existing metadata
            with open(metadata_file, 'r') as f:
                existing_metadata = json.load(f)
            
            # Unpin old version if pinned
            old_cid = existing_metadata.get("cid")
            if old_cid and existing_metadata.get("pinned"):
                await self.unpin_dataset(old_cid)
            
            # Add new version
            result = await self.add_dataset(name, data, metadata, format, pin=True)
            
            if result["status"] == "success":
                # Update metadata with version history
                result["previous_cid"] = old_cid
                result["version"] = existing_metadata.get("version", 0) + 1
                logger.info(f"Updated dataset '{name}': {old_cid} -> {result['cid']}")
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to update dataset: {e}")
            return {
                "status": "error",
                "error": str(e)
            }
    
    async def delete_dataset(self, name: str, unpin: bool = True) -> Dict[str, Any]:
        """Delete a dataset (removes metadata and optionally unpins).
        
        Args:
            name: Dataset name
            unpin: Whether to unpin from IPFS
            
        Returns:
            Dict with deletion status
        """
        try:
            metadata_file = self.metadata_dir / f"{name}.json"
            if not metadata_file.exists():
                return {
                    "status": "error",
                    "error": f"Dataset '{name}' not found"
                }
            
            # Load metadata
            with open(metadata_file, 'r') as f:
                dataset_metadata = json.load(f)
            
            # Unpin if requested
            if unpin:
                cid = dataset_metadata.get("cid")
                if cid:
                    await self.unpin_dataset(cid)
            
            # Remove metadata file
            metadata_file.unlink()
            logger.info(f"Deleted dataset '{name}'")
            
            return {
                "status": "success",
                "name": name,
                "deleted": True
            }
            
        except Exception as e:
            logger.error(f"Failed to delete dataset: {e}")
            return {
                "status": "error",
                "error": str(e),
                "deleted": False
            }


# Convenience functions for direct import
async def store_dataset_to_ipfs(
    name: str,
    data: Any,
    metadata: Optional[Dict[str, Any]] = None,
    format: str = "json",
    pin: bool = True
) -> Dict[str, Any]:
    """Store a legal dataset to IPFS (convenience function).
    
    Args:
        name: Dataset name
        data: Dataset content
        metadata: Additional metadata
        format: Data format ("json" or "parquet")
        pin: Whether to pin the dataset
        
    Returns:
        Dict with CID and storage information
    """
    manager = IPFSStorageManager()
    return await manager.add_dataset(name, data, metadata, format, pin)


async def retrieve_dataset_from_ipfs(
    name: Optional[str] = None,
    cid: Optional[str] = None
) -> Dict[str, Any]:
    """Retrieve a legal dataset from IPFS (convenience function).
    
    Args:
        name: Dataset name
        cid: Content ID (overrides name if provided)
        
    Returns:
        Dict with dataset data and metadata
    """
    manager = IPFSStorageManager()
    return await manager.get_dataset(name, cid)


def list_ipfs_datasets() -> Dict[str, Any]:
    """List all stored legal datasets (convenience function).
    
    Returns:
        Dict with list of datasets
    """
    manager = IPFSStorageManager()
    return manager.list_datasets()


__all__ = [
    "IPFSStorageManager",
    "store_dataset_to_ipfs",
    "retrieve_dataset_from_ipfs",
    "list_ipfs_datasets",
]
