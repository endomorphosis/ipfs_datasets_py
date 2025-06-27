"""
Test configuration and shared fixtures for the IPFS Datasets test suite.
"""

import pytest
import asyncio
import tempfile
import shutil
from pathlib import Path
from typing import Dict, Any, Generator
import json

# Test configuration
TEST_CONFIG = {
    "pdf_processing": {
        "enable_monitoring": False,  # Disable monitoring for tests
        "enable_audit": False,       # Disable audit for unit tests
        "test_timeout": 30,          # 30 second timeout for tests
        "mock_llm_models": True,     # Use mock models to avoid downloading
    },
    "mcp_server": {
        "test_port": 8091,          # Different port for testing
        "enable_logging": False,     # Reduce log noise in tests
        "mock_tools": True,         # Use mock tools when possible
    },
    "storage": {
        "use_temp_dirs": True,      # Use temporary directories
        "cleanup_after_test": True, # Clean up test data
    }
}

@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    temp_path = tempfile.mkdtemp()
    yield Path(temp_path)
    shutil.rmtree(temp_path)

@pytest.fixture
def sample_pdf_content():
    """Mock PDF content for testing."""
    return {
        "text": "This is a sample PDF document with multiple pages. It contains information about IPFS and decentralized storage systems.",
        "pages": [
            {
                "page_number": 1,
                "text": "Introduction to IPFS\n\nIPFS is a peer-to-peer hypermedia protocol.",
                "images": [],
                "metadata": {"page_type": "title"}
            },
            {
                "page_number": 2, 
                "text": "IPFS uses content addressing to create a permanent and decentralized method of storing and sharing files.",
                "images": [],
                "metadata": {"page_type": "content"}
            }
        ],
        "metadata": {
            "title": "IPFS Overview",
            "author": "Test Author",
            "page_count": 2,
            "created_date": "2025-06-27"
        }
    }

@pytest.fixture
def sample_ipld_structure():
    """Sample IPLD structure for testing."""
    return {
        "document_id": "test_doc_001",
        "title": "Test Document",
        "processing_pipeline": "pdf_to_graphrag",
        "chunks": [
            {
                "chunk_id": "chunk_001",
                "text": "Introduction to IPFS",
                "page_number": 1,
                "start_char": 0,
                "end_char": 20,
                "metadata": {"section": "introduction"}
            },
            {
                "chunk_id": "chunk_002", 
                "text": "IPFS is a peer-to-peer protocol",
                "page_number": 1,
                "start_char": 21,
                "end_char": 52,
                "metadata": {"section": "definition"}
            }
        ],
        "entities": [
            {
                "entity_id": "entity_001",
                "name": "IPFS",
                "type": "technology",
                "mentions": [{"chunk_id": "chunk_001", "start": 0, "end": 4}]
            }
        ],
        "relationships": [
            {
                "relationship_id": "rel_001",
                "source": "entity_001",
                "target": "entity_002", 
                "type": "is_type_of",
                "confidence": 0.9
            }
        ]
    }

@pytest.fixture
def mock_llm_response():
    """Mock LLM response for testing."""
    return {
        "summary": "This document provides an overview of IPFS technology.",
        "key_entities": [
            {"name": "IPFS", "type": "technology", "confidence": 0.95},
            {"name": "peer-to-peer", "type": "concept", "confidence": 0.88}
        ],
        "relationships": [
            {
                "source": "IPFS", 
                "target": "peer-to-peer",
                "relation": "uses",
                "confidence": 0.92
            }
        ],
        "embedding": [0.1, 0.2, 0.3] * 256  # Mock 768-dim embedding
    }

@pytest.fixture
def mcp_tool_request():
    """Sample MCP tool request for testing."""
    return {
        "method": "tools/call",
        "params": {
            "name": "pdf_ingest_to_graphrag",
            "arguments": {
                "pdf_path": "/test/sample.pdf",
                "options": {
                    "enable_ocr": True,
                    "chunk_size": 1024,
                    "overlap": 200
                }
            }
        }
    }

@pytest.fixture
def mcp_tool_response():
    """Expected MCP tool response for testing."""
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps({
                    "status": "success",
                    "document_id": "test_doc_001",
                    "chunks_created": 8,
                    "entities_extracted": 12,
                    "relationships_found": 5,
                    "processing_time": "45.2s",
                    "ipld_cid": "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"
                })
            }
        ]
    }

class MockLLMOptimizer:
    """Mock LLM optimizer for testing."""
    
    def __init__(self):
        self.model_name = "mock-model"
        self.max_chunk_size = 2048
    
    async def optimize_document(self, content, metadata=None):
        return {
            "optimized_chunks": [
                {"text": "Mock optimized chunk 1", "metadata": {}},
                {"text": "Mock optimized chunk 2", "metadata": {}}
            ],
            "summary": "Mock document summary",
            "key_entities": [{"name": "Mock Entity", "type": "concept"}]
        }

class MockOCREngine:
    """Mock OCR engine for testing."""
    
    def __init__(self):
        self.primary_engine = "mock-ocr"
        self.fallback_engines = []
    
    async def process_image(self, image_path):
        return {
            "text": "Mock OCR extracted text",
            "confidence": 0.95,
            "engine_used": "mock-ocr"
        }

class MockGraphRAGIntegrator:
    """Mock GraphRAG integrator for testing."""
    
    def __init__(self, storage=None):
        self.storage = storage
    
    async def create_knowledge_graph(self, document_data):
        return {
            "graph_id": "mock_graph_001",
            "entities_count": 5,
            "relationships_count": 3,
            "status": "success"
        }

@pytest.fixture
def mock_pdf_processor_components():
    """Mock components for PDF processor testing."""
    return {
        "llm_optimizer": MockLLMOptimizer(),
        "ocr_engine": MockOCREngine(), 
        "graphrag_integrator": MockGraphRAGIntegrator()
    }
