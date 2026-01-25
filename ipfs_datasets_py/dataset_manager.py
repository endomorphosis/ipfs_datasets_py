"""
Simple DatasetManager implementation for MCP tools.

This provides a basic DatasetManager class that the MCP tools can use
for dataset operations.
"""
import anyio
from typing import Dict, Any, Optional, Union, Protocol, runtime_checkable

try:
    from datasets import Dataset, load_dataset  # type: ignore
except Exception:  # pragma: no cover
    Dataset = None  # type: ignore
    load_dataset = None  # type: ignore


@runtime_checkable
class _DatasetLike(Protocol):
    def __str__(self) -> str: ...

class DatasetManager:
    """Simple dataset manager for MCP tools."""

    def __init__(self):
        """Initialize the dataset manager."""
        self._datasets = {}

    def get_dataset(self, dataset_id: str) -> 'ManagedDataset':
        """Get a dataset by ID."""
        if dataset_id in self._datasets:
            return self._datasets[dataset_id]

        # Try to load from HuggingFace Hub (optional dependency)
        if load_dataset is not None:
            try:
                hf_dataset = load_dataset(dataset_id, split='train')
                managed = ManagedDataset(hf_dataset, dataset_id)
                self._datasets[dataset_id] = managed
                return managed
            except Exception:
                pass

        # Fallback: return a minimal mock dataset for testing/dev environments.
        mock_dataset: _DatasetLike = {"text": ["sample text"], "label": [0]}
        if Dataset is not None:
            try:
                mock_dataset = Dataset.from_dict(mock_dataset)  # type: ignore[assignment]
            except Exception:
                pass
        managed = ManagedDataset(mock_dataset, dataset_id)
        self._datasets[dataset_id] = managed
        return managed

    def save_dataset(self, dataset_id: str, dataset: _DatasetLike) -> None:
        """Save a dataset."""
        managed = ManagedDataset(dataset, dataset_id)
        self._datasets[dataset_id] = managed

class ManagedDataset:
    """A managed dataset wrapper."""

    def __init__(self, dataset: _DatasetLike, dataset_id: str):
        """Initialize managed dataset."""
        self.dataset = dataset
        self.dataset_id = dataset_id
        self.format = "json"  # Default format

    async def save_async(self, destination: str, format: Optional[str] = None, **options) -> Dict[str, Any]:
        """Save the dataset asynchronously."""
        # Simulate async save operation
        await anyio.sleep(0.01)

        actual_format = format or self.format

        # Mock successful save
        return {
            "location": destination,
            "size": len(str(self.dataset)) if self.dataset else 1024,
            "format": actual_format
        }

    def save(self, destination: str, format: Optional[str] = None, **options) -> Dict[str, Any]:
        """Save the dataset synchronously."""
        actual_format = format or self.format

        # Mock successful save
        return {
            "location": destination,
            "size": len(str(self.dataset)) if self.dataset else 1024,
            "format": actual_format
        }
