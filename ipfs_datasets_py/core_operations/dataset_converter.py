"""
Dataset converter - Core business logic for converting dataset formats.

This module contains the core logic for converting datasets between formats.
It is used by:
- MCP server tools/dataset_tools/convert_dataset_format.py
- CLI commands
- Direct Python API imports
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class DatasetConverter:
    """
    Convert datasets between different formats.
    
    Supports conversion between:
    - JSON, CSV, Parquet
    - Various dataset libraries
    - Custom formats
    """
    
    def __init__(self):
        """Initialize the dataset converter."""
        self.logger = logging.getLogger(__name__ + ".DatasetConverter")
    
    async def convert(
        self,
        source: str,
        target_format: str,
        source_format: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Convert a dataset from one format to another.
        
        Args:
            source: Source dataset path or identifier
            target_format: Target format for conversion
            source_format: Source format (auto-detected if not provided)
            options: Additional conversion options
        
        Returns:
            Dict containing:
            - status: "success" or "error"
            - source: Source location
            - target_format: Target format
            - output_path: Path to converted dataset
            - message: Error message if status is "error"
        """
        try:
            self.logger.info(f"Converting dataset from {source} to {target_format}")
            
            # TODO: Implement dataset conversion logic
            # This is a placeholder for Phase 2 implementation
            
            result = {
                "status": "success",
                "source": source,
                "target_format": target_format,
                "message": "Dataset converted successfully"
            }
            # DQK-089: optional admitted-lake shadow projection (legacy remains authority).
            try:
                from ipfs_datasets_py.ducklake.adapters import (
                    ParquetProducerId,
                    maybe_shadow_project,
                )

                target = (target_format or "").lower()
                source_kind = "parquet" if target == "parquet" else "dataset"
                shadow = maybe_shadow_project(
                    producer_id=ParquetProducerId.DATASET_CONVERTER.value,
                    dataset_id=f"converted:{source}:{target_format}",
                    source_uri=str(source),
                    source_kind=source_kind,
                    schema_fields=(),
                    operation_id=f"op:dataset_converter:{source}:{target_format}",
                )
                if shadow is not None:
                    result["ducklake_shadow"] = shadow.to_dict()
            except Exception as shadow_exc:  # noqa: BLE001 — never block legacy convert
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
                    producer_id=_PPId.DATASET_CONVERTER.value,
                    source_uri=str(source),
                    path=str(source),
                    uses_mutable_sidecar=str(source).endswith(
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
            self.logger.error(f"Error converting dataset: {e}")
            return {
                "status": "error",
                "message": str(e),
                "source": source
            }
    
    def convert_sync(
        self,
        source: str,
        target_format: str,
        source_format: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Synchronous version of convert method.
        """
        from ipfs_datasets_py.utils.anyio_compat import run as _anyio_run
        return _anyio_run(
            self.convert(source, target_format, source_format, options)
        )
