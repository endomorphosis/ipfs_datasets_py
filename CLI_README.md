# IPFS Datasets CLI

A command line interface that provides convenient access to the IPFS Datasets Python MCP tools with simplified syntax. This tool allows users to interact with datasets, IPFS, vector stores, and other features without the complexity of the full MCP protocol.

## Installation

The CLI tool is included with the IPFS Datasets Python package. No additional installation is required.

## Usage

The CLI tool can be used in two ways:

1. **Direct Python execution:**
   ```bash
   python ipfs_datasets_cli.py [command] [options]
   ```

2. **Using the wrapper script (recommended):**
   ```bash
   ./ipfs-datasets [command] [options]
   ```

## Available Commands

### System Information

Get system status and list available tools:

```bash
# Check system status
./ipfs-datasets info status

# List all available tool categories
./ipfs-datasets info list-tools

# Get detailed information in JSON format
./ipfs-datasets --format json info status
```

### Dataset Operations

Work with datasets from various sources:

```bash
# Load a dataset from Hugging Face
./ipfs-datasets dataset load squad

# Load a local dataset file
./ipfs-datasets dataset load /path/to/data.json --format json

# Save dataset to a file
./ipfs-datasets dataset save my_data /path/to/output.csv --format csv

# Convert dataset format
./ipfs-datasets dataset convert /path/to/data.json csv /path/to/output.csv
```

### IPFS Operations

Interact with IPFS network:

```bash
# Get data from IPFS by hash
./ipfs-datasets ipfs get QmHash123... --output /path/to/save

# Pin data to IPFS
./ipfs-datasets ipfs pin "Hello, World!" --recursive
```

### Vector Operations

Create and search vector indices:

```bash
# Create vector index from documents
./ipfs-datasets vector create /path/to/documents.txt --index-name my_index

# Search vector index
./ipfs-datasets vector search "search query" --index-name my_index --limit 5
```

### Knowledge Graph Operations

Query knowledge graphs:

```bash
# Query with SPARQL
./ipfs-datasets graph query "SELECT * WHERE { ?s ?p ?o } LIMIT 10"

# Query with natural language (if supported)
./ipfs-datasets graph query "Find all documents about machine learning" --format natural
```

## Command Structure

The CLI follows a hierarchical command structure:

```
ipfs-datasets [global-options] <category> <action> [action-options] [arguments]
```

### Global Options

- `--format {pretty,json}`: Output format (default: pretty)
- `--verbose, -v`: Enable verbose output
- `--help, -h`: Show help information

### Categories

- `info`: System information and tool discovery
- `dataset`: Dataset loading, saving, and processing
- `ipfs`: IPFS network operations
- `vector`: Vector indexing and search
- `graph`: Knowledge graph operations

## Examples

### Basic Usage

```bash
# Check if the CLI is working
./ipfs-datasets info status

# See what tools are available
./ipfs-datasets info list-tools

# Get help for a specific command
./ipfs-datasets dataset --help
./ipfs-datasets dataset load --help
```

### Working with Data

```bash
# Load a popular dataset
./ipfs-datasets dataset load squad --split train

# Load local JSON data
./ipfs-datasets dataset load ./data.json --format json

# Convert CSV to JSON
./ipfs-datasets dataset convert data.csv json output.json

# Create a vector index for search
./ipfs-datasets vector create ./documents/ --index-name docs
```

### IPFS Integration

```bash
# Pin important data
./ipfs-datasets ipfs pin ./important_dataset.json

# Retrieve data by hash
./ipfs-datasets ipfs get QmYourHashHere --output retrieved_data.json
```

## Error Handling

The CLI provides clear error messages and status codes:

- ✅ Success operations show green checkmarks
- ❌ Failed operations show red X marks
- Error messages include helpful context

Use `--verbose` for detailed error information and debugging.

## Integration with Development Environment

### VS Code Tasks

The following VS Code tasks are available:

- **Test IPFS Datasets CLI**: Quick status check
- **List IPFS Datasets CLI Tools**: Show available tools
- **IPFS Datasets CLI Help**: Display help information

Access these through the Command Palette (`Ctrl+Shift+P`) → "Tasks: Run Task"

### Bash Completion

For bash completion support, add this to your `.bashrc`:

```bash
# Add the CLI tool directory to PATH
export PATH="$PATH:/path/to/ipfs_datasets_py"

# Enable completion (if available)
complete -W "info dataset ipfs vector graph" ipfs-datasets
```

## Troubleshooting

### Common Issues

1. **ImportError: Missing dependencies**
   - Some features require additional Python packages
   - Install missing dependencies: `pip install numpy datasets`

2. **Permission denied when running wrapper script**
   - Make the script executable: `chmod +x ipfs-datasets`

3. **Command not found**
   - Ensure you're in the correct directory
   - Use the full path to the script

### Getting Help

1. Use the built-in help system:
   ```bash
   ./ipfs-datasets --help
   ./ipfs-datasets <category> --help
   ./ipfs-datasets <category> <action> --help
   ```

2. Check system status:
   ```bash
   ./ipfs-datasets info status
   ```

3. List available tools:
   ```bash
   ./ipfs-datasets info list-tools
   ```

## Development

### Adding New Commands

To add new commands to the CLI:

1. Define a new command class in `ipfs_datasets_cli.py`
2. Add the command parser in `create_parser()`
3. Add the command handler in `main()`
4. Update this README with examples

### Testing

Test the CLI tool using the VS Code tasks or directly:

```bash
# Test basic functionality
./ipfs-datasets info status

# Test with verbose output
./ipfs-datasets --verbose info list-tools
```

## Architecture

The CLI tool is designed to:

- Provide a simplified interface to MCP tools
- Work independently of the MCP server protocol
- Support both interactive and programmatic usage
- Handle errors gracefully
- Provide clear, actionable output

The tool directly imports and calls the underlying MCP tool functions, bypassing the need for a running MCP server for most operations.