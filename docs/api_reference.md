# 🔧 API Reference

> **Complete API documentation for IPFS Datasets Python**  
> Production-ready interfaces for decentralized AI data processing.

## 🚀 **Quick Reference**

### Core Classes

```python
from ipfs_datasets_py import (
    # Data Management
    DatasetManager,           # Load and manage datasets
    IPFSVectorStore,         # Distributed vector search
    
    # Document Processing  
    PDFProcessor,            # AI-powered PDF processing
    GraphRAGIntegrator,      # Knowledge graph construction
    
    # Multimedia
    YtDlpWrapper,           # Universal media downloading  
    MediaProcessor,         # Media format conversion
    
    # Theorem Proving
    LogicProcessor,         # Natural language to formal logic
    ProofEngine,            # Mathematical theorem proving
    
    # Monitoring & Security
    AuditLogger,            # Comprehensive audit trails
    SecurityManager,        # Access control and governance
)
```

## 📊 **Core APIs**

### DatasetManager

**Purpose**: Central hub for dataset operations with IPFS backing

```python
class DatasetManager:
    def __init__(self, ipfs_node: str = "localhost:5001", cache_dir: str = "./cache"):
        """Initialize with IPFS connection and local caching."""
        
    async def load_dataset(self, 
                          dataset_name: str, 
                          split: str = "train",
                          streaming: bool = False,
                          ipfs_pin: bool = True) -> Dataset:
        """Load dataset from HuggingFace, local files, or IPFS.
        
        Args:
            dataset_name: HuggingFace dataset name or local path
            split: Dataset split to load  
            streaming: Enable streaming for large datasets
            ipfs_pin: Pin data to IPFS for persistence
            
        Returns:
            Dataset object with IPFS-backed storage
        """
        
    async def save_dataset(self,
                          dataset: Dataset,
                          path: str,
                          format: str = "parquet",
                          push_to_ipfs: bool = True) -> str:
        """Save dataset with IPFS content addressing.
        
        Returns:
            IPFS CID of saved dataset
        """
```

**Example Usage**:
```python
manager = DatasetManager()
dataset = await manager.load_dataset("wikipedia", split="train[:1000]")
cid = await manager.save_dataset(dataset, "processed_wiki.parquet")
print(f"Dataset saved to IPFS: {cid}")
```

---

### IPFSVectorStore

**Purpose**: Distributed semantic search with IPFS storage

```python
class IPFSVectorStore:
    def __init__(self, 
                 dimension: int,
                 metric: str = "cosine",
                 ipfs_node: str = "localhost:5001"):
        """Initialize vector store with IPFS backing."""
        
    async def add_documents(self,
                           documents: List[str],
                           metadata: Optional[List[Dict]] = None,
                           embeddings: Optional[np.ndarray] = None) -> List[str]:
        """Add documents to vector store.
        
        Args:
            documents: Text documents to index
            metadata: Optional metadata for each document
            embeddings: Pre-computed embeddings (auto-generated if None)
            
        Returns:
            List of document IDs
        """
        
    async def search(self,
                    query: str,
                    k: int = 5,
                    filters: Optional[Dict] = None) -> List[SearchResult]:
        """Semantic search with natural language queries.
        
        Returns:
            List of SearchResult objects with scores and metadata
        """
        
    async def get_ipfs_cid(self) -> str:
        """Get IPFS CID of the vector index."""
```

**Example Usage**:
```python
store = IPFSVectorStore(dimension=768)
doc_ids = await store.add_documents([
    "IPFS enables decentralized data storage",
    "Machine learning models process unstructured data"
])

results = await store.search("What is decentralized storage?")
for result in results:
    print(f"Score: {result.score:.3f} - {result.text}")
```

---

### PDFProcessor  

**Purpose**: AI-powered document processing with GraphRAG

```python
class PDFProcessor:
    def __init__(self, 
                 enable_ocr: bool = True,
                 ocr_engines: List[str] = ["surya", "tesseract", "easyocr"],
                 enable_monitoring: bool = True):
        """Initialize PDF processor with multi-engine OCR."""
        
    async def process_pdf(self,
                         pdf_path: str,
                         extract_entities: bool = True,
                         build_knowledge_graph: bool = True,
                         store_in_ipld: bool = True) -> ProcessingResult:
        """Process PDF through complete GraphRAG pipeline.
        
        Returns:
            ProcessingResult with entities, relationships, and IPFS CIDs
        """
        
    async def query_processed_document(self,
                                      document_id: str,
                                      query: str,
                                      max_hops: int = 2) -> QueryResult:
        """Query processed document using natural language."""
```

**Example Usage**:
```python
processor = PDFProcessor()
result = await processor.process_pdf("research_paper.pdf")

print(f"Entities found: {result.entities_count}")
print(f"Knowledge graph CID: {result.ipfs_cid}")

# Query the processed document
query_result = await processor.query_processed_document(
    result.document_id, 
    "What are the main conclusions?"
)
```

---

### YtDlpWrapper

**Purpose**: Universal media downloading from 1000+ platforms

```python
class YtDlpWrapper:
    def __init__(self,
                 output_dir: str = "./downloads",
                 quality: str = "best"):
        """Initialize media downloader."""
        
    async def download_video(self,
                            url: str,
                            quality: str = None,
                            audio_only: bool = False,
                            subtitle_langs: List[str] = None) -> DownloadResult:
        """Download video/audio from any supported platform.
        
        Supports: YouTube, Vimeo, TikTok, SoundCloud, and 1000+ more
        """
        
    async def download_playlist(self,
                               playlist_url: str,
                               max_downloads: int = None) -> PlaylistResult:
        """Download entire playlists with parallel processing."""
        
    async def search_videos(self,
                           query: str,
                           max_results: int = 10,
                           platform: str = "youtube") -> List[VideoInfo]:
        """Search for videos across platforms."""
```

**Example Usage**:
```python
downloader = YtDlpWrapper()
result = await downloader.download_video(
    "https://youtube.com/watch?v=example",
    quality="720p",
    subtitle_langs=["en", "es"]
)
print(f"Downloaded: {result.title} ({result.duration}s)")
```

---

### LogicProcessor & ProofEngine

**Purpose**: Convert natural language to formal logic and execute proofs

```python
class LogicProcessor:
    def convert_to_fol(self,
                      text: str,
                      domain_predicates: List[str] = None) -> FOLResult:
        """Convert natural language to First-Order Logic."""
        
    def convert_to_deontic(self,
                          legal_text: str,
                          jurisdiction: str = "us") -> DeonticResult:
        """Convert legal text to deontic logic."""

class ProofEngine:
    def __init__(self, auto_install_provers: bool = True):
        """Initialize with automatic theorem prover installation."""
        
    async def prove_formula(self,
                           formula: str,
                           prover: str = "z3",
                           timeout: int = 30) -> ProofResult:
        """Execute mathematical proof using theorem provers.
        
        Supported provers: z3, cvc5, lean, coq
        """
```

**Example Usage**:
```python
logic_processor = LogicProcessor()
proof_engine = ProofEngine()

# Convert legal text to formal logic
deontic_result = logic_processor.convert_to_deontic(
    "Citizens must pay taxes by April 15th"
)

# Execute mathematical proof
proof_result = await proof_engine.prove_formula(
    deontic_result.formula,
    prover="z3"
)

print(f"Proof: {proof_result.status} ({proof_result.execution_time}s)")
```

## 🛠️ **MCP Tools API**

### Development Tools

Access 200+ development tools through the MCP server:

```python
from ipfs_datasets_py.mcp_server.tools.development_tools import (
    TestGeneratorTool,
    DocumentationGeneratorTool, 
    CodebaseSearchEngine,
    LintingTools,
    TestRunner
)

# Generate tests from specifications
test_gen = TestGeneratorTool()
result = await test_gen.execute("generate_test", {
    "class_name": "MyTestClass",
    "functions": ["test_basic_functionality"]
})

# Generate documentation
doc_gen = DocumentationGeneratorTool()  
docs = await doc_gen.execute("generate_docs", {
    "source_file": "my_module.py"
})
```

### Dataset Tools

```python
from ipfs_datasets_py.mcp_server.tools.dataset_tools import (
    load_dataset,
    process_dataset,
    save_dataset,
    text_to_fol,
    legal_text_to_deontic
)

# Load and process datasets
dataset_result = await load_dataset("wikipedia", options={"split": "train"})
processed = await process_dataset(dataset_result["dataset_id"], [{
    "type": "filter",
    "column": "length", 
    "condition": ">",
    "value": 1000
}])
```

### Multimedia Tools

```python
from ipfs_datasets_py.mcp_server.tools.media_tools import (
    ytdlp_download_video,
    ytdlp_search_videos,
    ytdlp_batch_download
)

# Download media through MCP interface
video_result = await ytdlp_download_video(
    url="https://youtube.com/watch?v=example",
    quality="720p"
)
```

## 📊 **Monitoring & Analytics**

### Audit & Security

```python
from ipfs_datasets_py.audit import (
    AuditLogger,
    SecurityManager,
    EnhancedSecurityManager
)

# Comprehensive audit logging
audit = AuditLogger.get_instance()
audit.data_access("read", resource_id="dataset_123")

# Security management
security = EnhancedSecurityManager.get_instance()
decision = security.check_access(
    user_id="analyst_1",
    resource_id="sensitive_data", 
    action="process"
)
```

### Performance Monitoring

```python
from ipfs_datasets_py.monitoring import MonitoringSystem

monitor = MonitoringSystem()
with monitor.track_operation("data_processing"):
    # Your processing code here
    process_large_dataset()
```

## 🔧 **Configuration**

### Global Configuration

```python
from ipfs_datasets_py.config import Config

config = Config()
config.set_ipfs_node("https://ipfs.infura.io:5001")
config.set_cache_dir("/opt/ipfs_datasets/cache")  
config.enable_auto_install(True)
```

### Environment Variables

```bash
export IPFS_DATASETS_IPFS_NODE="localhost:5001"
export IPFS_DATASETS_CACHE_DIR="./cache"
export IPFS_DATASETS_AUTO_INSTALL="true"
export IPFS_DATASETS_LOG_LEVEL="INFO"
```

## 🚨 **Error Handling**

All APIs use consistent error handling patterns:

```python
from ipfs_datasets_py.exceptions import (
    IPFSConnectionError,
    ProcessingError,
    ProofExecutionError,
    MediaDownloadError
)

try:
    result = await processor.process_pdf("document.pdf")
except ProcessingError as e:
    logger.error(f"Processing failed: {e.message}")
    # Fallback logic
except IPFSConnectionError as e:
    logger.warning(f"IPFS unavailable: {e.message}")
    # Use local storage fallback
```

## 📈 **Performance Considerations**

### Async Operations
- All I/O operations are async-first
- Use `asyncio.gather()` for parallel processing
- Connection pooling for IPFS and database operations

### Caching
- Automatic result caching with IPFS content addressing
- Configurable cache expiration and cleanup
- Memory-efficient streaming for large datasets

### Resource Management
- Automatic resource cleanup with context managers
- Configurable memory limits and timeouts
- Built-in resource monitoring and alerts

---

## 📚 **Additional Resources**

- **[Complete Examples](../examples/)** - Working code for all APIs
- **[Testing Guide](guides/TESTING_GUIDE.md)** - How to test your code
- **[Performance Guide](performance_optimization.md)** - Optimization strategies
- **[Troubleshooting](guides/TROUBLESHOOTING.md)** - Common issues and solutions

---

**🔄 API Version**: v0.2.0  
**📊 Coverage**: 100% documented  
**✅ Status**: Production ready  

[← Back to Documentation](MASTER_DOCUMENTATION_INDEX_NEW.md) | [Examples →](../examples/)