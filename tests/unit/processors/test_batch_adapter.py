"""
Tests for BatchProcessorAdapter.

Tests batch/folder processing functionality through the unified processor interface.
"""

import pytest
from pathlib import Path
import tempfile
import shutil

from ipfs_datasets_py.processors.adapters.batch_adapter import BatchProcessorAdapter
from ipfs_datasets_py.processors.protocol import (
    ProcessingResult,
    ProcessingStatus,
    InputType,
    KnowledgeGraph,
    VectorStore
)


class TestBatchProcessorAdapter:
    """Tests for BatchProcessorAdapter class."""
    
    @pytest.fixture
    def adapter(self):
        """Create batch processor adapter."""
        return BatchProcessorAdapter()
    
    @pytest.fixture
    def temp_folder(self):
        """Create temporary folder with test files."""
        temp_dir = tempfile.mkdtemp()
        
        # Create some test files
        (Path(temp_dir) / "test1.txt").write_text("Test file 1")
        (Path(temp_dir) / "test2.txt").write_text("Test file 2")
        (Path(temp_dir) / "test3.md").write_text("# Test markdown")
        
        # Create subdirectory
        subdir = Path(temp_dir) / "subdir"
        subdir.mkdir()
        (subdir / "test4.txt").write_text("Test file in subdir")
        
        yield temp_dir
        
        # Cleanup
        shutil.rmtree(temp_dir)
    
    @pytest.mark.asyncio
    async def test_can_process_directory(self, adapter, temp_folder):
        """
        GIVEN: A batch processor adapter and directory path
        WHEN: Checking if it can process the directory
        THEN: Returns True
        """
        can_process = await adapter.can_process(temp_folder)
        assert can_process is True
    
    @pytest.mark.asyncio
    async def test_cannot_process_file(self, adapter, temp_folder):
        """
        GIVEN: A batch processor adapter and file path
        WHEN: Checking if it can process a single file
        THEN: Returns False
        """
        file_path = Path(temp_folder) / "test1.txt"
        can_process = await adapter.can_process(str(file_path))
        assert can_process is False
    
    @pytest.mark.asyncio
    async def test_can_process_glob_pattern(self, adapter):
        """
        GIVEN: A batch processor adapter and glob pattern
        WHEN: Checking if it can process the pattern
        THEN: Returns True
        """
        can_process = await adapter.can_process("/path/to/*.txt")
        assert can_process is True
    
    @pytest.mark.asyncio
    async def test_process_empty_folder(self, adapter):
        """
        GIVEN: An empty directory
        WHEN: Processing the directory
        THEN: Returns result with warning about no files
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            result = await adapter.process(temp_dir)
            
            assert isinstance(result, ProcessingResult)
            assert result.metadata.status in (ProcessingStatus.SUCCESS, ProcessingStatus.PARTIAL)
            assert len(result.metadata.warnings) > 0
            assert result.content["total_files"] == 0
    
    @pytest.mark.asyncio  
    async def test_process_folder_aggregates_results(self, adapter, temp_folder):
        """
        GIVEN: A directory with multiple files
        WHEN: Processing the directory
        THEN: Returns aggregated knowledge graph and statistics
        """
        result = await adapter.process(temp_folder, recursive=False)
        
        # Check result structure
        assert isinstance(result, ProcessingResult)
        assert isinstance(result.knowledge_graph, KnowledgeGraph)
        assert isinstance(result.vectors, VectorStore)
        
        # Check that folder was processed
        assert result.content["total_files"] >= 3  # At least 3 files in top level
        assert result.content["folder_path"] == temp_folder
        
        # Check knowledge graph has folder entity
        folder_entities = result.knowledge_graph.find_entities("Folder")
        assert len(folder_entities) >= 1
    
    @pytest.mark.asyncio
    async def test_process_recursive(self, adapter, temp_folder):
        """
        GIVEN: A directory with subdirectories
        WHEN: Processing recursively
        THEN: Processes files in subdirectories too
        """
        result = await adapter.process(temp_folder, recursive=True)
        
        # Should find more files with recursive=True
        assert result.content["total_files"] >= 4  # Includes file in subdir
    
    @pytest.mark.asyncio
    async def test_error_isolation(self, adapter, temp_folder):
        """
        GIVEN: A directory with some files that might fail
        WHEN: Processing the directory
        THEN: One file failure doesn't stop the batch
        """
        result = await adapter.process(temp_folder)
        
        # Even if some files fail, should still process others
        # At minimum, should track errors
        assert "errors" in result.content
        assert isinstance(result.content["errors"], list)
    
    def test_get_supported_types(self, adapter):
        """
        GIVEN: A batch processor adapter
        WHEN: Getting supported types
        THEN: Returns folder/directory/batch types
        """
        types = adapter.get_supported_types()
        
        assert "folder" in types
        assert "directory" in types
        assert "batch" in types
    
    def test_get_priority(self, adapter):
        """
        GIVEN: A batch processor adapter
        WHEN: Getting priority
        THEN: Returns high priority (15) for specialized processing
        """
        priority = adapter.get_priority()
        assert priority == 15
    
    def test_get_name(self, adapter):
        """
        GIVEN: A batch processor adapter
        WHEN: Getting name
        THEN: Returns BatchProcessor
        """
        name = adapter.get_name()
        assert name == "BatchProcessor"
    
    @pytest.mark.asyncio
    async def test_aggregate_knowledge_graphs(self, adapter):
        """
        GIVEN: Multiple processing results
        WHEN: Aggregating knowledge graphs
        THEN: Creates unified graph with folder entity
        """
        # Create mock results
        from ipfs_datasets_py.processors.protocol import Entity, ProcessingMetadata
        
        result1 = ProcessingResult(
            knowledge_graph=KnowledgeGraph(source="file1.txt"),
            vectors=VectorStore(),
            content={},
            metadata=ProcessingMetadata(processor_name="Test")
        )
        result1.knowledge_graph.add_entity(Entity(id="e1", type="Document", label="Doc1"))
        
        result2 = ProcessingResult(
            knowledge_graph=KnowledgeGraph(source="file2.txt"),
            vectors=VectorStore(),
            content={},
            metadata=ProcessingMetadata(processor_name="Test")
        )
        result2.knowledge_graph.add_entity(Entity(id="e2", type="Document", label="Doc2"))
        
        # Aggregate
        aggregated = adapter._aggregate_knowledge_graphs([result1, result2], "/test/folder")
        
        # Check aggregation
        assert len(aggregated.entities) == 3  # 2 docs + 1 folder
        assert len(aggregated.relationships) == 2  # folder CONTAINS both docs
        
        # Check folder entity exists
        folder_entities = aggregated.find_entities("Folder")
        assert len(folder_entities) == 1
        assert folder_entities[0].properties["file_count"] == 2


class TestBatchProcessorIntegration:
    """Integration tests with UniversalProcessor."""
    
    @pytest.mark.asyncio
    async def test_universal_processor_routes_folder(self):
        """
        GIVEN: UniversalProcessor with BatchProcessor registered
        WHEN: Processing a folder
        THEN: Routes to BatchProcessor
        """
        from ipfs_datasets_py.processors import UniversalProcessor
        
        processor = UniversalProcessor()
        
        # Check BatchProcessor is registered
        processors_list = processor.list_processors()
        assert "BatchProcessor" in processors_list
        
        # Check it can find batch processor for folders
        with tempfile.TemporaryDirectory() as temp_dir:
            processors = await processor.registry.find_processors(temp_dir)
            processor_names = [p.get_name() for p in processors]
            assert "BatchProcessor" in processor_names
