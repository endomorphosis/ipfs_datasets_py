"""
Test suite for WikipediaProcessor class following project standards.

Tests the core functionality of Wikipedia dataset processing with IPFS integration.
Follows GIVEN/WHEN/THEN format and project testing patterns.
"""

import pytest
import unittest
from unittest.mock import Mock, patch, MagicMock
import os

# Ensure the module exists
assert os.path.exists('/home/runner/work/ipfs_datasets_py/ipfs_datasets_py/ipfs_datasets_py/wikipedia_x/index.py'), \
    "index.py does not exist at the specified directory."

# Import the classes to test
from ipfs_datasets_py.wikipedia_x.index import (
    WikipediaProcessor,
    WikipediaConfig,
    test_ipfs_datasets_py
)


class TestWikipediaConfig(unittest.TestCase):
    """Test WikipediaConfig dataclass."""
    
    def test_default_config_values(self):
        """
        GIVEN no configuration parameters
        WHEN WikipediaConfig is created with defaults
        THEN expect all default values are set correctly
        """
        config = WikipediaConfig()
        
        assert config.cache_dir is None
        assert config.trust_remote_code is False
        assert config.revision is None
        assert config.use_auth_token is False
    
    def test_custom_config_values(self):
        """
        GIVEN custom configuration parameters
        WHEN WikipediaConfig is created with custom values
        THEN expect all custom values are preserved
        """
        config = WikipediaConfig(
            cache_dir="/tmp/test",
            trust_remote_code=True,
            revision="main",
            use_auth_token="test_token"
        )
        
        assert config.cache_dir == "/tmp/test"
        assert config.trust_remote_code is True
        assert config.revision == "main"
        assert config.use_auth_token == "test_token"


class TestWikipediaProcessorInitialization(unittest.TestCase):
    """Test WikipediaProcessor initialization."""
    
    def test_init_with_default_config(self):
        """
        GIVEN no configuration parameters
        WHEN WikipediaProcessor is initialized with defaults
        THEN expect instance created with default configuration
        """
        processor = WikipediaProcessor()
        
        assert processor.config is not None
        assert isinstance(processor.config, WikipediaConfig)
        assert processor.db == {}
        assert processor.logger is not None
    
    def test_init_with_custom_config(self):
        """
        GIVEN custom WikipediaConfig
        WHEN WikipediaProcessor is initialized
        THEN expect instance uses custom configuration
        """
        config = WikipediaConfig(cache_dir="/custom/path")
        processor = WikipediaProcessor(config)
        
        assert processor.config == config
        assert processor.config.cache_dir == "/custom/path"
        assert processor.db == {}


class TestWikipediaProcessorLoadDataset(unittest.TestCase):
    """Test WikipediaProcessor load_dataset functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.processor = WikipediaProcessor()
    
    def test_load_dataset_empty_name_raises_error(self):
        """
        GIVEN empty dataset name
        WHEN load_dataset is called
        THEN expect ValueError to be raised
        """
        with pytest.raises(ValueError, match="dataset_name cannot be empty"):
            self.processor.load_dataset("")
    
    @patch('ipfs_datasets_py.wikipedia_x.index.datasets.load_dataset')
    def test_load_dataset_success(self, mock_load_dataset):
        """
        GIVEN valid dataset name
        WHEN load_dataset is called successfully
        THEN expect dataset is loaded and stored
        """
        # Arrange
        mock_dataset = MagicMock()
        mock_load_dataset.return_value = mock_dataset
        dataset_name = "laion/Wikipedia-X"
        
        # Act
        result = self.processor.load_dataset(dataset_name)
        
        # Assert
        assert result == mock_dataset
        assert self.processor.db[dataset_name] == mock_dataset
        mock_load_dataset.assert_called_once()
    
    @patch('ipfs_datasets_py.wikipedia_x.index.datasets.load_dataset')
    def test_load_dataset_with_kwargs(self, mock_load_dataset):
        """
        GIVEN dataset name and additional kwargs
        WHEN load_dataset is called
        THEN expect kwargs are passed to datasets.load_dataset
        """
        # Arrange
        mock_dataset = MagicMock()
        mock_load_dataset.return_value = mock_dataset
        dataset_name = "laion/Wikipedia-X"
        
        # Act
        self.processor.load_dataset(dataset_name, split="train", streaming=True)
        
        # Assert
        call_args = mock_load_dataset.call_args
        assert call_args[0][0] == dataset_name
        assert call_args[1]['split'] == "train"
        assert call_args[1]['streaming'] is True
    
    @patch('ipfs_datasets_py.wikipedia_x.index.datasets.load_dataset')
    def test_load_dataset_failure_raises_runtime_error(self, mock_load_dataset):
        """
        GIVEN dataset loading fails
        WHEN load_dataset is called
        THEN expect RuntimeError to be raised
        """
        # Arrange
        mock_load_dataset.side_effect = Exception("Network error")
        dataset_name = "laion/Wikipedia-X"
        
        # Act & Assert
        with pytest.raises(RuntimeError, match="Failed to load dataset"):
            self.processor.load_dataset(dataset_name)


class TestWikipediaProcessorProcessDatasets(unittest.TestCase):
    """Test WikipediaProcessor process_datasets functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.processor = WikipediaProcessor()
    
    def test_process_datasets_none_input_raises_error(self):
        """
        GIVEN None as dataset_names input
        WHEN process_datasets is called
        THEN expect ValueError to be raised
        """
        with pytest.raises(ValueError, match="dataset_names cannot be None"):
            self.processor.process_datasets(None)
    
    def test_process_datasets_invalid_type_raises_error(self):
        """
        GIVEN invalid type as dataset_names input
        WHEN process_datasets is called
        THEN expect TypeError to be raised
        """
        with pytest.raises(TypeError, match="dataset_names must be a string or list"):
            self.processor.process_datasets(123)
    
    def test_process_datasets_empty_list_raises_error(self):
        """
        GIVEN empty list as dataset_names input
        WHEN process_datasets is called
        THEN expect ValueError to be raised
        """
        with pytest.raises(ValueError, match="dataset_names cannot be empty"):
            self.processor.process_datasets([])
    
    def test_process_datasets_string_input_converts_to_list(self):
        """
        GIVEN string dataset name
        WHEN process_datasets is called
        THEN expect string is converted to list internally
        """
        with patch.object(self.processor, 'load_dataset') as mock_load:
            mock_load.return_value = MagicMock()
            dataset_name = "laion/Wikipedia-X"
            
            result = self.processor.process_datasets(dataset_name)
            
            assert dataset_name in result
            mock_load.assert_called_once_with(dataset_name)
    
    def test_process_datasets_list_input_processes_all(self):
        """
        GIVEN list of dataset names
        WHEN process_datasets is called successfully
        THEN expect all datasets are processed
        """
        with patch.object(self.processor, 'load_dataset') as mock_load:
            mock_load.return_value = MagicMock()
            dataset_names = ["laion/Wikipedia-X", "laion/Wikipedia-M3"]
            
            result = self.processor.process_datasets(dataset_names)
            
            assert len(result) == 2
            assert all(name in result for name in dataset_names)
            assert mock_load.call_count == 2


class TestWikipediaProcessorUtilityMethods(unittest.TestCase):
    """Test WikipediaProcessor utility methods."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.processor = WikipediaProcessor()
    
    def test_get_dataset_info_nonexistent_returns_none(self):
        """
        GIVEN dataset name not in cache
        WHEN get_dataset_info is called
        THEN expect None to be returned
        """
        result = self.processor.get_dataset_info("nonexistent")
        
        assert result is None
    
    def test_get_dataset_info_existing_returns_info(self):
        """
        GIVEN dataset exists in cache
        WHEN get_dataset_info is called
        THEN expect dataset info to be returned
        """
        # Arrange
        mock_dataset = MagicMock()
        mock_dataset.features = "mock_features"
        mock_dataset.__len__ = Mock(return_value=100)
        dataset_name = "test_dataset"
        self.processor.db[dataset_name] = mock_dataset
        
        # Act
        result = self.processor.get_dataset_info(dataset_name)
        
        # Assert
        assert result is not None
        assert result['name'] == dataset_name
        assert 'features' in result
        assert result['num_rows'] == 100
    
    def test_clear_cache_empties_database(self):
        """
        GIVEN processor with cached datasets
        WHEN clear_cache is called
        THEN expect database to be empty
        """
        # Arrange
        self.processor.db['test'] = MagicMock()
        assert len(self.processor.db) == 1
        
        # Act
        self.processor.clear_cache()
        
        # Assert
        assert len(self.processor.db) == 0
    
    def test_loaded_datasets_property_returns_names(self):
        """
        GIVEN processor with cached datasets
        WHEN loaded_datasets property is accessed
        THEN expect list of dataset names
        """
        # Arrange
        dataset_names = ["dataset1", "dataset2"]
        for name in dataset_names:
            self.processor.db[name] = MagicMock()
        
        # Act
        result = self.processor.loaded_datasets
        
        # Assert
        assert set(result) == set(dataset_names)


class TestLegacyCompatibilityClass(unittest.TestCase):
    """Test legacy test_ipfs_datasets_py compatibility class."""
    
    def test_legacy_class_initialization(self):
        """
        GIVEN legacy compatibility requirements
        WHEN test_ipfs_datasets_py is initialized
        THEN expect WikipediaProcessor backend is created
        """
        legacy = test_ipfs_datasets_py()
        
        assert hasattr(legacy, 'processor')
        assert isinstance(legacy.processor, WikipediaProcessor)
        assert legacy.db is legacy.processor.db
    
    def test_legacy_load_dataset_delegates(self):
        """
        GIVEN legacy class instance
        WHEN load_dataset is called
        THEN expect call is delegated to WikipediaProcessor
        """
        with patch('ipfs_datasets_py.wikipedia_x.index.WikipediaProcessor.load_dataset') as mock_load:
            mock_load.return_value = MagicMock()
            legacy = test_ipfs_datasets_py()
            dataset_name = "laion/Wikipedia-X"
            
            result = legacy.load_dataset(dataset_name)
            
            mock_load.assert_called_once_with(dataset_name)
    
    def test_legacy_test_method_delegates(self):
        """
        GIVEN legacy class instance
        WHEN test method is called
        THEN expect call is delegated to WikipediaProcessor.process_datasets
        """
        with patch('ipfs_datasets_py.wikipedia_x.index.WikipediaProcessor.process_datasets') as mock_process:
            mock_process.return_value = {}
            legacy = test_ipfs_datasets_py()
            dataset_names = ["laion/Wikipedia-X"]
            
            result = legacy.test(dataset_names)
            
            mock_process.assert_called_once_with(dataset_names)


if __name__ == '__main__':
    unittest.main()