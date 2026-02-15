"""
Test suite for core/output_formatter/_formatted_output.py converted from unittest to pytest.
"""
import pytest
import tempfile
import os
import stat
import json
import threading
import time
from dataclasses import asdict, fields
from unittest.mock import Mock, MagicMock, patch

from core.output_formatter._formatted_output import FormattedOutput
from configs import configs, Configs
from core.text_normalizer._normalized_content import NormalizedContent
from types_ import Logger


def make_sample_formatted_output() -> FormattedOutput:
    """
    Create a sample FormattedOutput instance for testing.
    
    Returns:
        FormattedOutput instance with sample data.
    """
    return FormattedOutput(
        content="Sample content for testing",
        format="txt",
        metadata={'author': 'test_user', 'created': '2024-01-01'},
        output_path="/tmp/test_output.txt"
    )


def make_mock_resources() -> dict[str, MagicMock]:
    """
    Factory function to create mock resources for OutputFormatter.
    
    Returns:
        A dictionary of mock resources configured with proper dependencies.
    """
    resources = {
        "normalized_content": MagicMock(spec=NormalizedContent),
        "formatted_output": MagicMock(spec=FormattedOutput),
        "logger": MagicMock(spec=Logger),
    }
    return resources


@pytest.mark.unit
class TestFormattedOutputInitialization:
    """Test FormattedOutput dataclass initialization."""

    @pytest.fixture
    def sample_data(self):
        """Provide sample data for testing."""
        return {
            'content': "Sample content",
            'format': "txt",
            'metadata': {'author': 'test', 'date': '2024-01-01'},
            'output_path': "/path/to/output.txt"
        }

    def test_init_with_all_parameters(self, sample_data):
        """
        GIVEN all parameters for FormattedOutput
        WHEN FormattedOutput is initialized with:
            - content="Sample content"
            - format="txt"
            - metadata={'author': 'test', 'date': '2024-01-01'}
            - output_path="/path/to/output.txt"
        THEN expect:
            - Instance created successfully
            - All attributes set correctly
            - No defaults overridden unintentionally
        """
        # Act
        output = FormattedOutput(
            content=sample_data['content'],
            format=sample_data['format'],
            metadata=sample_data['metadata'],
            output_path=sample_data['output_path']
        )
        
        # Assert
        assert output.content == sample_data['content']
        assert output.format == sample_data['format']
        assert output.metadata == sample_data['metadata']
        assert output.output_path == sample_data['output_path']

    def test_init_with_minimal_parameters(self, sample_data):
        """
        GIVEN only required parameters
        WHEN FormattedOutput is initialized with:
            - content="Sample content"
            - format="txt"
        THEN expect:
            - Instance created successfully
            - metadata is empty dict (default)
            - output_path is empty string (default)
        """
        # Act
        output = FormattedOutput(
            content=sample_data['content'],
            format=sample_data['format']
        )
        
        # Assert
        assert output.content == sample_data['content']
        assert output.format == sample_data['format']
        assert output.metadata == {}
        assert output.output_path == ""

    def test_init_metadata_default_factory(self):
        """
        GIVEN multiple FormattedOutput instances
        WHEN created without specifying metadata
        THEN expect:
            - Each instance has its own empty dict
            - Modifying one doesn't affect others
            - Default factory creates new dict each time
        """
        # Act
        output1 = FormattedOutput(content="content1", format="txt")
        output2 = FormattedOutput(content="content2", format="txt")
        
        # Modify one instance's metadata
        output1.metadata['test'] = 'value'
        
        # Assert
        assert output1.metadata == {'test': 'value'}
        assert output2.metadata == {}
        assert output1.metadata is not output2.metadata

    def test_init_with_none_values(self, sample_data):
        """
        GIVEN None values for optional parameters
        WHEN FormattedOutput is initialized with metadata=None
        THEN expect:
            - TypeError or proper handling
            - Clear indication that dict expected
        """
        # Act & Assert
        with pytest.raises(TypeError):
            FormattedOutput(
                content=sample_data['content'],
                format=sample_data['format'],
                metadata=None
            )

    def test_init_immutability_considerations(self, sample_data):
        """
        GIVEN FormattedOutput is a dataclass
        WHEN attempting to verify if frozen=True
        THEN expect:
            - Determine if attributes can be modified after creation
            - Document mutability behavior
        """
        # Act
        output = FormattedOutput(
            content=sample_data['content'],
            format=sample_data['format']
        )
        
        # Try to modify an attribute (should work if not frozen)
        try:
            output.content = "Modified content"
            is_mutable = True
        except AttributeError:
            is_mutable = False
        
        # Assert - document the behavior
        assert isinstance(output, FormattedOutput)
        # Note: This test documents the mutability behavior