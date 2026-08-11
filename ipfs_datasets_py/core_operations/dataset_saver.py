"""
Dataset saver - Core business logic for saving datasets.

This module contains the core logic for saving datasets to various destinations.
It is used by:
- MCP server tools/dataset_tools/save_dataset.py
- CLI commands
- Direct Python API imports
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class DatasetSaver:
    """
    Save datasets to various destinations.
    
    Supports:
    - Local file system
    - Hugging Face Hub
    - IPFS
    - Various formats (JSON, CSV, Parquet, etc.)
    """
    
    def __init__(self):
        """Initialize the dataset saver."""
        self.logger = logging.getLogger(__name__ + ".DatasetSaver")
    
    async def save(
        self,
        dataset: Any,
        destination: str,
        format: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Save a dataset to a destination.
        
        Args:
            dataset: The dataset object to save
            destination: Destination path or identifier
            format: Output format (json, csv, parquet, etc.)
            options: Additional save options
        
        Returns:
            Dict containing:
            - status: "success" or "error"
            - destination: Where the dataset was saved
            - format: Format used
            - size: Size of saved data (if available)
            - message: Error message if status is "error"
        """
        try:
            self.logger.info(f"Saving dataset to {destination} with format {format}")
            
            # TODO: Implement dataset saving logic
            # This is a placeholder for Phase 2 implementation
            
            result = {
                "status": "success",
                "destination": destination,
                "format": format if format else "auto",
                "message": "Dataset saved successfully"
            }
            # DQK-089: optional admitted-lake shadow projection (legacy remains authority).
            try:
                from ipfs_datasets_py.ducklake.adapters import (
                    ParquetProducerId,
                    maybe_shadow_project,
                )

                fmt = (format or "auto").lower()
                source_kind = "parquet" if fmt == "parquet" else "dataset"
                shadow = maybe_shadow_project(
                    producer_id=ParquetProducerId.DATASET_SAVER.value,
                    dataset_id=f"saved:{destination}",
                    source_uri=str(destination),
                    source_kind=source_kind,
                    schema_fields=(),
                    operation_id=f"op:dataset_saver:{destination}",
                )
                if shadow is not None:
                    result["ducklake_shadow"] = shadow.to_dict()
            except Exception as shadow_exc:  # noqa: BLE001 — never block legacy save
                self.logger.debug(
                    "ducklake shadow projection skipped: %s", shadow_exc
                )
            # DQK-100: cutover discovery fence (no-op until lake authority promoted).
            try:
                from ipfs_datasets_py.ducklake.cutover import (
                    maybe_enforce_lake_discovery,
                )
                from ipfs_datasets_py.ducklake.adapters import (
                    ParquetProducerId as _PPId,
                )

                cutover = maybe_enforce_lake_discovery(
                    producer_id=_PPId.DATASET_SAVER.value,
                    source_uri=str(destination),
                    path=str(destination),
                    uses_mutable_sidecar=str(destination).endswith(
                        (".json", ".manifest", ".manifest.json")
                    ),
                )
                if cutover is not None:
                    result["ducklake_cutover"] = cutover
            except Exception as cutover_exc:
                from ipfs_datasets_py.ducklake.cutover import (
                    CutoverBlockedError,
                    is_lake_authority_active,
                )

                if is_lake_authority_active() and isinstance(
                    cutover_exc, CutoverBlockedError
                ):
                    raise
                self.logger.debug(
                    "ducklake cutover discovery fence skipped: %s", cutover_exc
                )
            return result
        except Exception as e:
            self.logger.error(f"Error saving dataset: {e}")
            return {
                "status": "error",
                "message": str(e),
                "destination": destination
            }
    
    def save_sync(
        self,
        dataset: Any,
        destination: str,
        format: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Synchronous version of save method.
        """
        from ipfs_datasets_py.utils.anyio_compat import run as _anyio_run
        return _anyio_run(self.save(dataset, destination, format, options))
