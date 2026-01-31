# Frequently Asked Questions (FAQ)

Quick answers to common questions about IPFS Datasets Python.

## Getting Started

### What is IPFS Datasets Python?

IPFS Datasets Python is a comprehensive platform that combines:
- **Decentralized Storage**: IPFS-native data management
- **AI Document Processing**: GraphRAG with knowledge graphs
- **Theorem Proving**: Convert text to verified formal logic
- **Multimedia Processing**: Download from 1000+ platforms with FFmpeg
- **Vector Search**: Semantic search across datasets

### What are the main use cases?

1. **Legal Research**: Convert legal documents to verified mathematical proofs
2. **Document Analysis**: AI-powered PDF processing with knowledge graphs
3. **Media Archiving**: Download and process multimedia from 1000+ platforms
4. **Research Data**: Manage and search research datasets with provenance
5. **Enterprise Knowledge Management**: Build searchable knowledge bases

### What makes it different?

- **Decentralized**: IPFS-native for permanent, distributed storage
- **AI-Powered**: Advanced NLP, embeddings, and knowledge graphs
- **Formally Verified**: Mathematical proof generation and verification
- **Production-Ready**: 182+ tests, comprehensive documentation

## Installation & Setup

### How do I install it?

```bash
# Basic installation
pip install ipfs-datasets-py

# With all features
pip install ipfs-datasets-py[all]

# Specific features
pip install ipfs-datasets-py[graphrag]        # Document AI
pip install ipfs-datasets-py[theorem_proving] # Logic & proofs
pip install ipfs-datasets-py[multimedia]      # Media processing
```

See [Installation Guide](installation.md) for details.

### What are the system requirements?

**Minimum:**
- Python 3.12+
- 4GB RAM
- 10GB disk space

**Recommended for production:**
- Python 3.12+
- 16GB+ RAM
- 100GB+ SSD storage
- GPU (optional, for faster embeddings)

### Do I need to run an IPFS node?

For basic usage: **No** - the library can use public IPFS gateways.

For production: **Yes, recommended** - Run your own IPFS daemon for:
- Better performance
- More control
- Privacy
- Reliability

```bash
# Install IPFS
# See https://docs.ipfs.tech/install/

# Start IPFS daemon
ipfs daemon
```

### How long does setup take?

- **Quick start**: 5 minutes with pip
- **Full setup with IPFS**: 15-20 minutes
- **Production deployment**: 30 minutes with Docker, 2 hours for full enterprise setup

## Features & Capabilities

### Can I process PDFs?

Yes! Advanced PDF processing with:
- Text extraction
- Entity recognition
- Knowledge graph generation
- Semantic search
- LLM-optimized formatting

See [PDF Processing Guide](guides/pdf_processing.md).

### Does it support multimedia?

Yes! Download and process from 1000+ platforms:
- YouTube, Vimeo, TikTok, Instagram
- Audio (Spotify, SoundCloud, podcasts)
- Live streams and archives
- FFmpeg integration for conversion

See [Multimedia Processing Guide](guides/tools/ffmpeg_tools_integration.md).

### What about web scraping?

Comprehensive web scraping:
- Legal databases (US Code, state laws, PACER)
- Common Crawl integration
- Internet Archive support
- Custom scrapers

See [Web Scraping Guide](guides/comprehensive_web_scraping_guide.md).

### Can it prove theorems?

Yes! Convert natural language to formal logic:
- Legal text → Deontic logic
- Automated proof generation
- SymbolicAI integration
- Verification with proof checkers

See [Theorem Prover Guide](guides/THEOREM_PROVER_INTEGRATION_GUIDE.md).

## Usage

### How do I load a dataset?

```python
from ipfs_datasets_py import DatasetManager

# Initialize
dm = DatasetManager()

# Load dataset
dataset = dm.load_dataset("squad")

# Or from IPFS
dataset = dm.load_from_ipfs("QmHash...")
```

### How do I generate embeddings?

```python
from ipfs_datasets_py.embeddings import EmbeddingGenerator

# Initialize
generator = EmbeddingGenerator()

# Generate embeddings
embeddings = generator.generate(texts)

# Store in vector database
vector_store.add(embeddings)
```

### How do I search documents?

```python
from ipfs_datasets_py.search import SearchEngine

# Initialize
search = SearchEngine()

# Semantic search
results = search.search("your query here", top_k=10)
```

See [User Guide](user_guide.md) for more examples.

## Performance

### How fast is it?

Performance depends on your hardware and configuration:
- **Embedding generation**: ~100-1000 docs/sec (with GPU)
- **Vector search**: <100ms for millions of vectors
- **PDF processing**: ~10-50 pages/sec
- **IPFS operations**: Depends on network and node

See [Performance Optimization Guide](guides/performance_optimization.md).

### Can I use GPUs?

Yes! GPU acceleration for:
- Embedding generation (2-10x faster)
- LLM inference
- Vector operations

Configure with:
```python
# Use GPU for embeddings
generator = EmbeddingGenerator(device="cuda")
```

### How do I scale for production?

- **Horizontal scaling**: Multiple workers
- **Caching**: Redis recommended
- **Load balancing**: Nginx or similar
- **Database optimization**: Vector store tuning

See [Deployment Guide](deployment.md).

## Troubleshooting

### IPFS connection fails

1. Check IPFS daemon is running: `ipfs daemon`
2. Verify API access: `curl http://127.0.0.1:5001/api/v0/version`
3. Check firewall settings
4. Try public gateway as fallback

### Out of memory errors

1. Reduce batch size
2. Use smaller embedding models
3. Enable disk caching
4. Add more RAM or swap

### Slow performance

1. Enable GPU if available
2. Tune vector store settings
3. Increase batch size (if memory allows)
4. Use faster storage (SSD)
5. Profile and optimize

See [Troubleshooting Section](user_guide.md#troubleshooting) in User Guide.

## Development

### How do I contribute?

We welcome contributions! See the [Developer Guide](developer_guide.md) for:
- Development setup
- Coding standards
- Testing requirements
- Pull request process

### How do I report bugs?

1. Check existing issues
2. Create new issue with:
   - System information
   - Steps to reproduce
   - Expected vs actual behavior
   - Logs/error messages

### Where can I get help?

- **Documentation**: Start with [Getting Started Guide](getting_started.md)
- **GitHub Issues**: For bugs and feature requests
- **Discussions**: For questions and community support

## Advanced Topics

### Can I customize the embedding model?

Yes! Use any Hugging Face model:
```python
generator = EmbeddingGenerator(
    model_name="sentence-transformers/all-mpnet-base-v2"
)
```

### How does data provenance work?

Every operation is tracked:
- Data source
- Transformations applied
- Timestamps
- IPFS hashes

See [Data Provenance Guide](guides/data_provenance.md).

### What about security?

Built-in security features:
- Access control
- Audit logging
- Encryption support
- Secure API keys

See [Security & Governance Guide](guides/security/security_governance.md).

## Still Have Questions?

- **📖 Full Documentation**: [Documentation Index](index.md)
- **🚀 Getting Started**: [Quick Start Guide](getting_started.md)
- **📘 User Guide**: [Complete User Guide](user_guide.md)
- **👨‍💻 Developer Guide**: [Development Guide](developer_guide.md)
