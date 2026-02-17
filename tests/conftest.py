"""
Test configuration and shared fixtures for the IPFS Datasets test suite.

Includes:
- Commit-hash based test caching
- Test execution optimizations
- Shared fixtures
"""

from datetime import datetime
from pathlib import Path
import os
import shutil
import subprocess
import sys
from typing import Optional

import pytest


# ==================== Test Gating (LLM / Network / Heavy) ====================

_LLM_KEYWORDS = (
    "openai",
    "anthropic",
    "claude",
    "gemini",
    "vertexai",
    "bedrock",
    "ollama",
    "llm",
    "chatcompletion",
    "completions",
    "responses",
    "transformers",
    "pipeline(",
    "autotokenizer",
    "automodelforcausallm",
)

_NETWORK_KEYWORDS = (
    "requests.",
    "http://",
    "https://",
    "aiohttp",
    "httpx",
    "websocket",
    "websockets",
    "socket.",
    "urllib",
    "selenium",
    "playwright",
)

_HEAVY_KEYWORDS = (
    "cuda",
    "torch",
    "tensorflow",
    "jax",
    "accelerate",
    "bitsandbytes",
    "faiss",
    "sentence_transformers",
    "chromadb",
    "milvus",
)


def _truthy_env(name: str) -> bool:
    value = os.environ.get(name, "").strip().lower()
    return value in {"1", "true", "yes", "y", "on"}


def pytest_addoption(parser):
    """Add custom command line options."""
    group = parser.getgroup("gating")
    group.addoption(
        "--run-llm",
        action="store_true",
        default=False,
        help="Run tests that require an LLM / large model stack.",
    )
    group.addoption(
        "--run-network",
        action="store_true",
        default=False,
        help="Run tests that require external network access.",
    )
    group.addoption(
        "--run-heavy",
        action="store_true",
        default=False,
        help="Run tests that are resource-heavy (GPU/large deps/datasets).",
    )

    # Preserve existing options (cache plugin)
    cache_group = parser.getgroup("cache")
    cache_group.addoption(
        "--show-cache-info",
        action="store_true",
        default=False,
        help="Show cache information and exit",
    )
    cache_group.addoption(
        "--force-cache-clear",
        action="store_true",
        default=False,
        help="Force clear cache regardless of commit hash",
    )


# ==================== Optional pytest-benchmark Support ====================

try:
    import pytest_benchmark  # type: ignore[import-not-found]  # noqa: F401
    _PYTEST_BENCHMARK_AVAILABLE = True
except Exception:
    _PYTEST_BENCHMARK_AVAILABLE = False


if not _PYTEST_BENCHMARK_AVAILABLE:
    @pytest.fixture
    def benchmark():
        """Fallback `benchmark` fixture when pytest-benchmark isn't installed.

        Behaves like a simple callable wrapper: `benchmark(func, *args, **kwargs)`.
        """

        def _run(func, *args, **kwargs):
            return func(*args, **kwargs)

        return _run


# ==================== Commit-Hash Based Caching Plugin ====================

def get_git_commit_hash() -> Optional[str]:
    """Get the current git commit hash."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def get_git_uncommitted_changes() -> bool:
    """Check if there are uncommitted changes."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
        )
        return bool(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def pytest_configure(config):
    """Configure the plugin with commit-hash tracking."""
    if config.option.show_cache_info:
        show_cache_info(config)
        pytest.exit("Cache info displayed", returncode=0)

    # Get current commit hash
    current_commit = get_git_commit_hash()
    has_uncommitted = get_git_uncommitted_changes()
    
    # Access pytest cache
    cache = config.cache
    
    # Store commit info
    if current_commit:
        last_commit = cache.get("commit_hash", None)
        
        # Update stored values
        cache.set("commit_hash", current_commit)
        cache.set("uncommitted_changes", has_uncommitted)
        
        # Store metadata
        cache.set("last_run_commit", current_commit)
        cache.set("last_run_uncommitted", has_uncommitted)


def show_cache_info(config):
    """Display cache information."""
    cache = config.cache
    cache_dir = Path(config.cache._cachedir)
    
    print("\n" + "=" * 60)
    print("Pytest Cache Information")
    print("=" * 60)
    
    # Cache directory info
    if cache_dir.exists():
        cache_size = sum(f.stat().st_size for f in cache_dir.rglob('*') if f.is_file())
        cache_size_mb = cache_size / (1024 * 1024)
        print(f"Cache directory: {cache_dir}")
        print(f"Cache size: {cache_size_mb:.2f} MB")
    else:
        print(f"Cache directory: {cache_dir} (does not exist)")
    
    # Git commit info
    current_commit = get_git_commit_hash()
    if current_commit:
        print(f"\nCurrent commit: {current_commit[:8]}")
        
        last_commit = cache.get("commit_hash", None)
        if last_commit:
            print(f"Cached commit: {last_commit[:8]}")
            if current_commit != last_commit:
                print("⚠️  Commit has changed - cache may be stale")
            else:
                print("✓ Cache is up to date with current commit")
        
        if get_git_uncommitted_changes():
            print("⚠️  Uncommitted changes detected")
    else:
        print("\nNot in a git repository")
    
    # Last run info
    last_run_commit = cache.get("last_run_commit", None)
    if last_run_commit:
        print(f"\nLast successful run: {last_run_commit[:8]}")
    
    # Cache statistics
    lastfailed = cache.get("cache/lastfailed", {})
    if lastfailed:
        print(f"\nLast failed tests: {len(lastfailed)}")
    
    print("=" * 60 + "\n")


@pytest.hookimpl(trylast=True)
def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Add cache information to terminal summary."""
    if config.option.verbose >= 1:
        commit = get_git_commit_hash()
        if commit:
            terminalreporter.write_sep("=", "Cache Info")
            terminalreporter.write_line(f"Commit hash: {commit[:8]}")
            
            if get_git_uncommitted_changes():
                terminalreporter.write_line("Note: Uncommitted changes present")


    def pytest_collection_modifyitems(config, items):
        """Skip LLM/network/heavy tests by default; allow opt-in via flags or env vars.

        This is intentionally conservative to prevent OOM/system crashes in default runs.
        """
        run_llm = bool(getattr(config.option, "run_llm", False)) or _truthy_env("RUN_LLM_TESTS")
        run_network = bool(getattr(config.option, "run_network", False)) or _truthy_env("RUN_NETWORK_TESTS")
        run_heavy = bool(getattr(config.option, "run_heavy", False)) or _truthy_env("RUN_HEAVY_TESTS")

        file_cache: dict[str, tuple[bool, bool, bool]] = {}

        def _classify_file(path: str) -> tuple[bool, bool, bool]:
            cached = file_cache.get(path)
            if cached is not None:
                return cached

            is_llm = False
            is_network = False
            is_heavy = False
            try:
                text = Path(path).read_text(encoding="utf-8", errors="ignore").lower()
                is_llm = any(k in text for k in _LLM_KEYWORDS)
                is_network = any(k in text for k in _NETWORK_KEYWORDS)
                is_heavy = any(k in text for k in _HEAVY_KEYWORDS)
            except Exception:
                pass

            file_cache[path] = (is_llm, is_network, is_heavy)
            return file_cache[path]

        skip_llm = pytest.mark.skip(reason="Skipped by default (LLM). Use --run-llm or RUN_LLM_TESTS=1")
        skip_network = pytest.mark.skip(reason="Skipped by default (network). Use --run-network or RUN_NETWORK_TESTS=1")
        skip_heavy = pytest.mark.skip(reason="Skipped by default (heavy). Use --run-heavy or RUN_HEAVY_TESTS=1")

        for item in items:
            # Respect explicit markers first.
            marked_llm = item.get_closest_marker("llm") is not None
            marked_network = item.get_closest_marker("network") is not None
            marked_heavy = item.get_closest_marker("heavy") is not None

            # Auto-detect based on file contents if not explicitly marked.
            try:
                path = str(item.fspath)
            except Exception:
                path = ""

            auto_llm = False
            auto_network = False
            auto_heavy = False
            if path:
                auto_llm, auto_network, auto_heavy = _classify_file(path)

            if (marked_llm or auto_llm) and not run_llm:
                item.add_marker(skip_llm)
            if (marked_network or auto_network) and not run_network:
                item.add_marker(skip_network)
            if (marked_heavy or auto_heavy) and not run_heavy:
                item.add_marker(skip_heavy)


# ==================== End of Caching Plugin ====================


def _ensure_test_path_entries() -> None:
	venv_bin = Path(sys.executable).resolve().parent
	tools_bin = Path(__file__).resolve().parent.parent / '.tools' / 'bin'

	path_entries = [str(venv_bin)]
	if tools_bin.exists():
		path_entries.append(str(tools_bin))

	current_path = os.environ.get('PATH', '')
	for entry in reversed(path_entries):
		if entry and entry not in current_path.split(os.pathsep):
			current_path = f"{entry}{os.pathsep}{current_path}"
	os.environ['PATH'] = current_path


def _ensure_github_token() -> None:
	if os.environ.get('GITHUB_TOKEN'):
		return

	if shutil.which('gh') is None:
		return

	try:
		result = subprocess.run(
			['gh', 'auth', 'token'],
			check=False,
			capture_output=True,
			text=True,
			timeout=10
		)
		token = result.stdout.strip()
		if token:
			os.environ['GITHUB_TOKEN'] = token
	except Exception:
		return


_ensure_test_path_entries()
_ensure_github_token()


@pytest.fixture
def sample_graphrag_system():
	"""Create sample GraphRAG system for tests that need it."""
	try:
		from ipfs_datasets_py.content_discovery import ContentManifest
		from ipfs_datasets_py.knowledge_graphs.knowledge_graph_extraction import (
			KnowledgeGraph,
			Entity,
			Relationship,
		)
		from ipfs_datasets_py.processors.multimodal_processor import (
			ProcessedContentBatch,
			ProcessedContent,
		)
		from ipfs_datasets_py.processors.graphrag.website_system import WebsiteGraphRAGSystem
	except ModuleNotFoundError as e:
		pytest.skip(f"Optional GraphRAG dependencies not installed: {e}")
	except ImportError as e:
		pytest.skip(f"GraphRAG components not available: {e}")

	html_content = ProcessedContent(
		source_url="https://example.com/ai-intro.html",
		content_type="html",
		text_content="Introduction to artificial intelligence and machine learning algorithms.",
		metadata={"title": "AI Introduction"},
		confidence_score=0.9,
	)

	pdf_content = ProcessedContent(
		source_url="https://example.com/research.pdf",
		content_type="pdf",
		text_content="Research paper on deep learning neural networks and their applications.",
		metadata={"title": "Deep Learning Research"},
		confidence_score=0.85,
	)

	processed_batch = ProcessedContentBatch(
		base_url="https://example.com",
		processed_items=[html_content, pdf_content],
		processing_stats={"html": 1, "pdf": 1, "total": 2},
	)

	ai_entity = Entity(name="Artificial Intelligence", entity_type="concept")
	ml_entity = Entity(name="Machine Learning", entity_type="concept")
	dl_entity = Entity(name="Deep Learning", entity_type="concept")

	kg = KnowledgeGraph()
	kg.add_entity(ai_entity)
	kg.add_entity(ml_entity)
	kg.add_entity(dl_entity)
	kg.add_relationship(Relationship(ai_entity, ml_entity, "includes"))
	kg.add_relationship(Relationship(ml_entity, dl_entity, "includes"))

	manifest = ContentManifest(
		base_url="https://example.com",
		html_pages=[],
		pdf_documents=[],
		media_files=[],
		structured_data=[],
		total_assets=2,
		discovery_timestamp=datetime.now(),
	)

	return WebsiteGraphRAGSystem(
		url="https://example.com",
		content_manifest=manifest,
		processed_content=processed_batch,
		knowledge_graph=kg,
		graphrag=None,
	)

# import pytest
# import anyio
# import tempfile
# import shutil
# from pathlib import Path
# from typing import Dict, Any, Generator
# import json
# from unittest.mock import Mock


# # Test configuration
# TEST_CONFIG = {
#     "pdf_processing": {
#         "enable_monitoring": False,  # Disable monitoring for tests
#         "enable_audit": False,       # Disable audit for unit tests
#         "test_timeout": 30,          # 30 second timeout for tests
#         "mock_llm_models": True,     # Use mock models to avoid downloading
#     },
#     "mcp_server": {
#         "test_port": 8091,          # Different port for testing
#         "enable_logging": False,     # Reduce log noise in tests
#         "mock_tools": True,         # Use mock tools when possible
#     },
#     "storage": {
#         "use_temp_dirs": True,      # Use temporary directories
#         "cleanup_after_test": True, # Clean up test data
#     }
# }

# @pytest.fixture(scope="function")
# def event_loop():
#     """Create an instance of the default event loop for each test function."""
#     loop = asyncio.new_event_loop()
#     yield loop
#     loop.close()

# @pytest.fixture
# def temp_dir():
#     """Create a temporary directory for test files."""
#     temp_path = tempfile.mkdtemp()
#     yield Path(temp_path)
#     shutil.rmtree(temp_path)

# @pytest.fixture
# def sample_pdf_content():
#     """Mock PDF content for testing."""
#     return {
#         "text": "This is a sample PDF document with multiple pages. It contains information about IPFS and decentralized storage systems.",
#         "pages": [
#             {
#                 "page_number": 1,
#                 "text": "Introduction to IPFS\n\nIPFS is a peer-to-peer hypermedia protocol.",
#                 "images": [],
#                 "metadata": {"page_type": "title"}
#             },
#             {
#                 "page_number": 2, 
#                 "text": "IPFS uses content addressing to create a permanent and decentralized method of storing and sharing files.",
#                 "images": [],
#                 "metadata": {"page_type": "content"}
#             }
#         ],
#         "metadata": {
#             "title": "IPFS Overview",
#             "author": "Test Author",
#             "page_count": 2,
#             "created_date": "2025-06-27"
#         }
#     }

# @pytest.fixture
# def sample_ipld_structure():
#     """Sample IPLD structure for testing."""
#     return {
#         "document_id": "test_doc_001",
#         "title": "Test Document",
#         "processing_pipeline": "pdf_to_graphrag",
#         "chunks": [
#             {
#                 "chunk_id": "chunk_001",
#                 "text": "Introduction to IPFS",
#                 "page_number": 1,
#                 "start_char": 0,
#                 "end_char": 20,
#                 "metadata": {"section": "introduction"}
#             },
#             {
#                 "chunk_id": "chunk_002", 
#                 "text": "IPFS is a peer-to-peer protocol",
#                 "page_number": 1,
#                 "start_char": 21,
#                 "end_char": 52,
#                 "metadata": {"section": "definition"}
#             }
#         ],
#         "entities": [
#             {
#                 "entity_id": "entity_001",
#                 "name": "IPFS",
#                 "type": "technology",
#                 "mentions": [{"chunk_id": "chunk_001", "start": 0, "end": 4}]
#             }
#         ],
#         "relationships": [
#             {
#                 "relationship_id": "rel_001",
#                 "source": "entity_001",
#                 "target": "entity_002", 
#                 "type": "is_type_of",
#                 "confidence": 0.9
#             }
#         ]
#     }

# @pytest.fixture
# def mock_llm_response():
#     """Mock LLM response for testing."""
#     return {
#         "summary": "This document provides an overview of IPFS technology.",
#         "key_entities": [
#             {"name": "IPFS", "type": "technology", "confidence": 0.95},
#             {"name": "peer-to-peer", "type": "concept", "confidence": 0.88}
#         ],
#         "relationships": [
#             {
#                 "source": "IPFS", 
#                 "target": "peer-to-peer",
#                 "relation": "uses",
#                 "confidence": 0.92
#             }
#         ],
#         "embedding": [0.1, 0.2, 0.3] * 256  # Mock 768-dim embedding
#     }

# @pytest.fixture
# def mcp_tool_request():
#     """Sample MCP tool request for testing."""
#     return {
#         "method": "tools/call",
#         "params": {
#             "name": "pdf_ingest_to_graphrag",
#             "arguments": {
#                 "pdf_path": "/test/sample.pdf",
#                 "options": {
#                     "enable_ocr": True,
#                     "chunk_size": 1024,
#                     "overlap": 200
#                 }
#             }
#         }
#     }

# @pytest.fixture
# def mcp_tool_response():
#     """Expected MCP tool response for testing."""
#     return {
#         "content": [
#             {
#                 "type": "text",
#                 "text": json.dumps({
#                     "status": "success",
#                     "document_id": "test_doc_001",
#                     "chunks_created": 8,
#                     "entities_extracted": 12,
#                     "relationships_found": 5,
#                     "processing_time": "45.2s",
#                     "ipld_cid": "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"
#                 })
#             }
#         ]
#     }

# class MockLLMOptimizer:
#     """Mock LLM optimizer for testing."""
    
#     def __init__(self):
#         self.model_name = "mock-model"
#         self.max_chunk_size = 2048
    
#     async def optimize_document(self, content, metadata=None):
#         return {
#             "optimized_chunks": [
#                 {"text": "Mock optimized chunk 1", "metadata": {}},
#                 {"text": "Mock optimized chunk 2", "metadata": {}}
#             ],
#             "summary": "Mock document summary",
#             "key_entities": [{"name": "Mock Entity", "type": "concept"}]
#         }

# class MockOCREngine:
#     """Mock OCR engine for testing."""
    
#     def __init__(self):
#         self.primary_engine = "mock-ocr"
#         self.fallback_engines = []
    
#     async def process_image(self, image_path):
#         return {
#             "text": "Mock OCR extracted text",
#             "confidence": 0.95,
#             "engine_used": "mock-ocr"
#         }

# class MockGraphRAGIntegrator:
#     """Mock GraphRAG integrator for testing."""
    
#     def __init__(self, storage=None):
#         self.storage = storage
    
#     async def create_knowledge_graph(self, document_data):
#         return {
#             "graph_id": "mock_graph_001",
#             "entities_count": 5,
#             "relationships_count": 3,
#             "status": "success"
#         }

# @pytest.fixture
# def mock_pdf_processor_components():
#     """Mock components for PDF processor testing."""
#     return {
#         "llm_optimizer": MockLLMOptimizer(),
#         "ocr_engine": MockOCREngine(), 
#         "graphrag_integrator": MockGraphRAGIntegrator()
#     }

# @pytest.fixture
# def mock_embedding_service():
#     return Mock()

# @pytest.fixture
# def mock_vector_service():
#     return Mock()