# IPFS Datasets CLI Tools

A comprehensive command line interface that provides convenient access to the IPFS Datasets Python MCP tools with simplified syntax. This collection includes multiple CLI tools for different use cases.

## Installation

The CLI tools are included with the IPFS Datasets Python package. Install dependencies first:

```bash
pip install numpy pandas flask pydantic datasets transformers nltk psutil beautifulsoup4 cachetools pillow
```

## Available CLI Tools

### 1. Main CLI Tool (`ipfs_datasets_cli.py`)

The primary CLI tool with a curated selection of the most commonly used functions.

```bash
python ipfs_datasets_cli.py [command] [options]
# or
./ipfs-datasets [command] [options]
```

**Available Commands:**
- `info` - System information and tool discovery
- `dataset` - Dataset loading, saving, and processing
- `ipfs` - IPFS network operations
- `vector` - Vector indexing and search
- `graph` - Knowledge graph operations
- `cli` - Command execution (limited for security)

### 2. Enhanced CLI Tool (`enhanced_cli.py`)

A comprehensive CLI that provides access to ALL 31+ tool categories available in the package.

```bash
python enhanced_cli.py <category> <tool> [arguments]
```

**Features:**
- Dynamic discovery of all available tools
- Access to 31+ tool categories
- 100+ individual tools
- Flexible argument passing

## Usage Examples

### System Information

```bash
# Check system status
./ipfs-datasets info status

# List all available tool categories
python enhanced_cli.py --list-categories

# List tools in a specific category
python enhanced_cli.py --list-tools dataset_tools

# Get detailed information in JSON format
./ipfs-datasets --format json info status
```

### Dataset Operations

```bash
# Load a dataset from Hugging Face
./ipfs-datasets dataset load squad

# Load a local dataset file
./ipfs-datasets dataset load /path/to/data.json --format json

# Save dataset to a file
./ipfs-datasets dataset save my_data /path/to/output.csv --format csv

# Convert dataset format
./ipfs-datasets dataset convert /path/to/data.json csv /path/to/output.csv

# Using enhanced CLI for more dataset tools
python enhanced_cli.py dataset_tools load_dataset --source squad --format json
```

### IPFS Operations

```bash
# Get data from IPFS by hash
./ipfs-datasets ipfs get QmHash123... --output /path/to/save

# Pin data to IPFS
./ipfs-datasets ipfs pin "Hello, World!" --recursive

# Using enhanced CLI
python enhanced_cli.py ipfs_tools get_from_ipfs --hash QmHash123
python enhanced_cli.py ipfs_tools pin_to_ipfs --data "test data"
```

### Vector Operations

```bash
# Create vector index from documents
./ipfs-datasets vector create /path/to/documents.txt --index-name my_index

# Search vector index
./ipfs-datasets vector search "search query" --index-name my_index --limit 5

# Using enhanced CLI
python enhanced_cli.py vector_tools create_vector_index --data "text data" --index_name test_index
```

### Advanced Tool Categories

The enhanced CLI provides access to many specialized tool categories:

```bash
# PDF processing tools
python enhanced_cli.py pdf_tools pdf_analyze_relationships --input document.pdf

# Media processing tools
python enhanced_cli.py media_tools ffmpeg_info --input video.mp4

# Web archive tools
python enhanced_cli.py web_archive_tools common_crawl_search --query "machine learning"

# Analysis tools
python enhanced_cli.py analysis_tools analysis_tools

# System monitoring
python enhanced_cli.py bespoke_tools system_status
python enhanced_cli.py bespoke_tools system_health
```

## Tool Categories Available

The enhanced CLI provides access to 31+ tool categories:

| Category | Tools | Description |
|----------|-------|-------------|
| `admin_tools` | 2 tools | Administrative functions |
| `analysis_tools` | 1 tool | Data analysis capabilities |
| `audit_tools` | 3 tools | Audit and compliance |
| `auth_tools` | 2 tools | Authentication management |
| `background_task_tools` | 2 tools | Background task management |
| `bespoke_tools` | 7 tools | System utilities and status |
| `cache_tools` | 2 tools | Caching operations |
| `dataset_tools` | 7 tools | Dataset manipulation |
| `development_tools` | 8 tools | Development utilities |
| `embedding_tools` | 7 tools | Embedding generation and management |
| `graph_tools` | 1 tool | Knowledge graph operations |
| `ipfs_tools` | 3 tools | IPFS network operations |
| `media_tools` | 9 tools | Audio/video processing |
| `monitoring_tools` | 2 tools | System monitoring |
| `pdf_tools` | 7 tools | PDF processing and analysis |
| `provenance_tools` | 2 tools | Data provenance tracking |
| `security_tools` | 1 tool | Security operations |
| `storage_tools` | 1 tool | Storage management |
| `vector_tools` | 5 tools | Vector operations |
| `web_archive_tools` | 11 tools | Web archiving and crawling |
| `workflow_tools` | 2 tools | Workflow automation |

## Config Defaults

You can set persistent defaults for the main CLI in `~/.ipfs_datasets/cli.json` or pass a path via `--config` (or env `IPFS_DATASETS_CLI_CONFIG`):

```json
{
   "host": "127.0.0.1",
   "port": "8899",
   "gateway": "https://ipfs.io"
}
```

Precedence order for defaults resolution:
- Command-line flags: `--host`, `--port`, `--gateway`
- Environment variables: `IPFS_DATASETS_HOST`, `IPFS_DATASETS_PORT`, `IPFS_HTTP_GATEWAY` (or `IPFS_DATASETS_IPFS_GATEWAY`), `IPFS_DATASETS_CLI_CONFIG`
- Config file: `--config <path>` or `~/.ipfs_datasets/cli.json`
- Hardcoded defaults: `127.0.0.1:8899` and no gateway

These defaults apply to the `mcp`, `tools`, and `ipfs` command families.

### Inspecting Defaults

Quickly see the resolved values the CLI will use:

```bash
# Human-readable
./ipfs-datasets info defaults

# JSON for scripts
./ipfs-datasets --json info defaults

# With overrides
./ipfs-datasets info defaults --host 0.0.0.0 --port 9000 --gateway https://cloudflare-ipfs.com

# Using an alternate config file
./ipfs-datasets info defaults --config /tmp/cli.json

### Persisting Defaults

Save your preferred defaults (host/port/gateway) to the config file:

```bash
# Save to default path ~/.ipfs_datasets/cli.json using current resolutions
./ipfs-datasets info save-defaults

# Explicit values and custom path
./ipfs-datasets info save-defaults \
   --host 127.0.0.1 --port 8899 --gateway https://ipfs.io \
   --config /tmp/cli.json

# Verify
./ipfs-datasets --json info defaults --config /tmp/cli.json
```
```

## Global Options

Both CLI tools support these global options:

- `--format {pretty,json}`: Output format (default: pretty)
- `--verbose, -v`: Enable verbose output
- `--help, -h`: Show help information

## Testing

### Basic Test

```bash
python test_cli.py
```

### Comprehensive Test

```bash
python comprehensive_cli_test.py
```

The comprehensive test suite validates:
- Basic CLI functionality
- Tool category access
- Data processing capabilities
- Wrapper script functionality

## Current Status

✅ **Working:**
- Basic CLI operations (info, status, list-tools)
- Dataset loading and conversion
- Wrapper script functionality
- JSON output formatting
- Enhanced CLI tool discovery

⚠️ **Limited by Dependencies:**
- Some tools require additional packages (PyTorch, TensorFlow, tiktoken, etc.)
- Advanced ML features need deep learning frameworks
- Some media tools require FFmpeg
- PDF tools need additional libraries

❌ **Security Limitations:**
- CLI execute command is limited for security reasons
- Some operations may be restricted in certain environments

## Dependencies

### Core Dependencies (Required)
```
numpy>=2.3.0
pandas>=2.3.0
flask>=3.1.0
pydantic>=2.11.0
datasets>=4.0.0
transformers>=4.56.0
nltk>=3.9.0
psutil>=7.0.0
beautifulsoup4>=4.13.0
cachetools>=6.2.0
pillow>=11.3.0
```

### Optional Dependencies (For Full Functionality)
```
torch>=1.9.0              # Deep learning features
tiktoken>=0.6.0           # Token processing
openai>=1.97.0            # LLM integration
ffmpeg-python>=0.2.0      # Media processing
PyMuPDF>=1.26.0           # PDF processing
opencv-contrib-python-headless>=4.11.0  # Computer vision
```

## Troubleshooting

### Common Issues

1. **Missing Dependencies**
   - Install core dependencies: `pip install numpy pandas flask pydantic datasets transformers nltk psutil beautifulsoup4 cachetools pillow`
   - For advanced features: `pip install torch tiktoken openai`

2. **Tool Not Found Errors**
   - Use `python enhanced_cli.py --list-categories` to see available categories
   - Use `python enhanced_cli.py --list-tools <category>` to see tools in a category

3. **Permission Errors**
   - Make wrapper script executable: `chmod +x ipfs-datasets`
   - Check file permissions for input/output files

4. **Import Errors**
   - Ensure you're in the correct directory
   - Check that all dependencies are installed
   - Use `--verbose` flag for detailed error information

### Getting Help

1. Use built-in help:
   ```bash
   ./ipfs-datasets --help
   ./ipfs-datasets <category> --help
   python enhanced_cli.py --help
   ```

2. Check system status:
   ```bash
   ./ipfs-datasets info status
   python enhanced_cli.py bespoke_tools system_status
   ```

3. List available tools:
   ```bash
   ./ipfs-datasets info list-tools
   python enhanced_cli.py --list-categories
   ```

## Architecture

The CLI tools are designed to:

- Provide simplified access to MCP tools without protocol complexity
- Work independently of MCP server infrastructure
- Support both interactive and programmatic usage
- Handle errors gracefully with clear error messages
- Provide flexible output formats for both humans and machines

### Design Principles

1. **Simplicity**: Easy-to-use command structure
2. **Comprehensive**: Access to all available functionality
3. **Flexible**: Multiple output formats and usage patterns
4. **Robust**: Graceful error handling and clear messaging
5. **Extensible**: Easy to add new tools and categories

The tools directly import and call underlying MCP functions, bypassing the need for a running MCP server for most operations while maintaining access to the full feature set of the library.