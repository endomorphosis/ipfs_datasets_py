"""
Wikipedia X Dataset Processing Module

Provides functionality for processing Wikipedia datasets with IPFS integration.
Based on patterns from existing working implementations in the repository.
"""

import datasets
import logging
from typing import List, Dict, Any, Optional, Union
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class WikipediaConfig:
    """Configuration for Wikipedia dataset processing."""
    cache_dir: Optional[str] = None
    trust_remote_code: bool = False
    revision: Optional[str] = None
    use_auth_token: Union[bool, str] = False


class WikipediaProcessor:
    """
    Wikipedia dataset processor with IPFS integration capabilities.

    Handles loading and processing of Wikipedia datasets including:
    - laion/Wikipedia-X
    - laion/Wikipedia-X-Full
    - laion/Wikipedia-X-Concat
    - laion/Wikipedia-M3

    Args:
        config: WikipediaConfig object with processing settings

    Example:
        >>> processor = WikipediaProcessor()
        >>> dataset = processor.load_dataset("laion/Wikipedia-X")
        >>> processed_data = processor.process_dataset(dataset)
    """

    def __init__(self, config: Optional[WikipediaConfig] = None):
        """Initialize Wikipedia processor with optional configuration.

        Args:
            config: Configuration object, uses defaults if None
        """
        self.config = config or WikipediaConfig()
        self.db: Dict[str, Any] = {}
        self.logger = logging.getLogger(__name__ + ".WikipediaProcessor")

    def load_dataset(self, dataset_name: str, **kwargs) -> Any:
        """
        Load a Wikipedia dataset by name.

        Args:
            dataset_name: Name of the dataset to load (e.g., "laion/Wikipedia-X")
            **kwargs: Additional arguments passed to datasets.load_dataset

        Returns:
            Loaded dataset object

        Raises:
            ValueError: If dataset_name is invalid
            RuntimeError: If dataset loading fails

        Example:
            >>> dataset = processor.load_dataset("laion/Wikipedia-X")
        """
        if not dataset_name:
            raise ValueError("dataset_name cannot be empty")

        try:
            self.logger.info(f"Loading dataset: {dataset_name}")

            # Merge config with kwargs, giving precedence to kwargs
            load_kwargs = {
                'cache_dir': self.config.cache_dir,
                'trust_remote_code': self.config.trust_remote_code,
                'revision': self.config.revision,
                'use_auth_token': self.config.use_auth_token,
                **kwargs
            }

            # Remove None values
            load_kwargs = {k: v for k, v in load_kwargs.items() if v is not None}

            dataset = datasets.load_dataset(dataset_name, **load_kwargs)

            # Store in internal database for compatibility with old tests
            self.db[dataset_name] = dataset

            self.logger.info(f"Successfully loaded dataset: {dataset_name}")
            return dataset

        except Exception as e:
            self.logger.error(f"Failed to load dataset {dataset_name}: {e}")
            raise RuntimeError(f"Failed to load dataset {dataset_name}: {e}") from e

    def process_datasets(self, dataset_names: Union[str, List[str]]) -> Dict[str, Any]:
        """
        Process multiple datasets.

        Args:
            dataset_names: Single dataset name or list of dataset names

        Returns:
            Dictionary mapping dataset names to loaded datasets

        Raises:
            TypeError: If dataset_names is not string or list
            ValueError: If dataset_names is empty

        Example:
            >>> datasets = processor.process_datasets(["laion/Wikipedia-X", "laion/Wikipedia-M3"])
        """
        if dataset_names is None:
            raise ValueError("dataset_names cannot be None")

        if isinstance(dataset_names, str):
            dataset_names = [dataset_names]

        if not isinstance(dataset_names, list):
            raise TypeError("dataset_names must be a string or list")

        if not dataset_names:
            raise ValueError("dataset_names cannot be empty")

        results = {}
        for dataset_name in dataset_names:
            try:
                dataset = self.load_dataset(dataset_name)
                results[dataset_name] = dataset
            except Exception as e:
                self.logger.error(f"Failed to process dataset {dataset_name}: {e}")
                # Continue processing other datasets
                continue

        return results

    def get_dataset_info(self, dataset_name: str) -> Optional[Dict[str, Any]]:
        """
        Get information about a loaded dataset.

        Args:
            dataset_name: Name of the dataset

        Returns:
            Dataset information if available, None otherwise
        """
        if dataset_name not in self.db:
            return None

        dataset = self.db[dataset_name]
        try:
            return {
                'name': dataset_name,
                'features': str(dataset.features) if hasattr(dataset, 'features') else None,
                'num_rows': len(dataset) if hasattr(dataset, '__len__') else None,
                'splits': list(dataset.keys()) if isinstance(dataset, dict) else None
            }
        except Exception as e:
            self.logger.warning(f"Could not get info for dataset {dataset_name}: {e}")
            return {'name': dataset_name, 'error': str(e)}

    def clear_cache(self) -> None:
        """Clear the internal dataset cache."""
        self.db.clear()
        self.logger.info("Dataset cache cleared")

    @property
    def loaded_datasets(self) -> List[str]:
        """Get list of currently loaded dataset names."""
        return list(self.db.keys())


# Compatibility class for old tests
class test_ipfs_datasets_py:
    """
    Legacy compatibility class for existing tests.
    Wraps the new WikipediaProcessor implementation.
    """

    def __init__(self):
        """Initialize with WikipediaProcessor backend."""
        self.processor = WikipediaProcessor()
        self.db = self.processor.db

    def load_dataset(self, dataset_name: str):
        """Load dataset using WikipediaProcessor."""
        return self.processor.load_dataset(dataset_name)

    def test(self, datasets_list):
        """Process multiple datasets for compatibility."""
        return self.processor.process_datasets(datasets_list)
