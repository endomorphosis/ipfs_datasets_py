# VS Code MCP Server Configuration Guide

This guide explains how to configure the IPFS Datasets MCP server to work with VS Code Copilot.

## ✅ Configuration Complete

**Status:** MCP server is now configured for VS Code Copilot integration

### 🎯 What Was Configured

1. **✅ VS Code Extensions Installed:**
   - GitHub Copilot (`github.copilot`)
   - GitHub Copilot Chat (`github.copilot-chat`)  
   - Copilot MCP (`automatalabs.copilot-mcp`) - **NEWLY INSTALLED**

2. **✅ MCP Server Configuration:**
   - Created `__main__.py` for module execution
   - Updated `.vscode/settings.json` with MCP server settings
   - Created `start_mcp_server.sh` startup script

3. **✅ Python Dependencies:**
   - `mcp` package (v1.9.1 installed)
   - All IPFS datasets dependencies available

## 🚀 How to Use MCP Tools in VS Code Copilot

### Step 1: Start the MCP Server
```bash
./start_mcp_server.sh
```
*OR*
```bash
python -m ipfs_datasets_py.mcp_server --host 127.0.0.1 --port 8000 --debug
```

### Step 2: Open Copilot Chat
1. Open VS Code in this workspace
2. Press `Ctrl+Shift+P` → "GitHub Copilot: Open Chat"
3. Start chatting with access to MCP tools!

### Step 3: Use IPFS Dataset Tools
Try these example prompts in Copilot Chat:

**📊 Dataset Operations:**
- "Load a dataset from `/path/to/dataset.json`"
- "Save this dataset to IPFS and pin it"
- "Convert this dataset to parquet format"

**🔍 Search & Analysis:**
- "Create a vector index for this dataset"
- "Search for documents similar to 'machine learning'"
- "Generate an audit report for recent operations"

**🗂️ IPFS Operations:**
- "Pin this content to IPFS: `QmHash123...`"
- "Retrieve content from IPFS hash `QmTest456...`"

## 🛠️ Available MCP Tools (21 total)

### 📊 Dataset Management
- `load_dataset` - Load datasets from various sources
- `save_dataset` - Save datasets to storage  
- `process_dataset` - Apply operations to datasets
- `convert_dataset_format` - Convert between formats

### 🗂️ IPFS Operations
- `get_from_ipfs` - Retrieve content from IPFS
- `pin_to_ipfs` - Pin content to IPFS

### 🔍 Vector & Search
- `create_vector_index` - Create vector search index
- `search_vector_index` - Search vector index
- `query_knowledge_graph` - Query knowledge graphs

### 📋 Audit & Reporting
- `record_audit_event` - Record audit events
- `generate_audit_report` - Generate audit reports
- `record_provenance` - Record data provenance

### 🔒 Security
- `check_access_permission` - Check access permissions

### 🌐 Web Archive Tools
- `extract_text_from_warc` - Extract text from WARC files
- `extract_metadata_from_warc` - Extract metadata
- `extract_links_from_warc` - Extract links  
- `index_warc` - Index WARC files

*Plus 5 more specialized tools...*

## ⚙️ Configuration Details

### VS Code Settings (`.vscode/settings.json`)
```json
{
    "mcp.servers": {
        "ipfs-datasets": {
            "command": "python",
            "args": ["-m", "ipfs_datasets_py.mcp_server", "--host", "127.0.0.1", "--port", "8000"],
            "cwd": "/home/barberb/ipfs_datasets_py",
            "env": {
                "PYTHONPATH": "/home/barberb/ipfs_datasets_py",
                "IPFS_DATASETS_CONFIG": "/home/barberb/ipfs_datasets_py/config/mcp_config.yaml"
            }
        }
    },
    "copilot-mcp.servers": {
        "ipfs-datasets": { /* same config */ }
    }
}
```

### Startup Script (`start_mcp_server.sh`)
- Sets environment variables
- Activates virtual environment
- Starts MCP server with debug logging

## ✅ Verification Steps

### 1. Test MCP Server
```bash
# Check if server starts
python -m ipfs_datasets_py.mcp_server --help

# Start server (in background)
./start_mcp_server.sh &

# Test server health (if health endpoint exists)
curl http://127.0.0.1:8000/health
```

### 2. Test in VS Code Copilot
1. Start the MCP server
2. Open Copilot Chat in VS Code
3. Try: "What IPFS dataset tools are available?"
4. Try: "Load a dataset and show me its structure"

## 🔧 Troubleshooting

### If Tools Don't Appear in Copilot:
1. **Restart VS Code** after configuration changes
2. **Check MCP server is running:** `ps aux | grep mcp_server`
3. **Verify extensions:** Ensure Copilot MCP extension is enabled
4. **Check Developer Console:** Help → Toggle Developer Tools

### If Server Won't Start:
1. **Check Python environment:** Virtual environment activated?
2. **Verify dependencies:** `pip list | grep mcp`
3. **Check port availability:** `netstat -tulpn | grep 8000`
4. **Review logs:** Look for error messages in terminal

### Common Issues:
- **Port 8000 in use:** Change port in settings and startup script
- **Python path issues:** Verify PYTHONPATH in environment
- **Missing dependencies:** Run `pip install -r requirements.txt`

## 🎯 Next Steps

1. **✅ DONE:** Configuration complete
2. **▶️ START SERVER:** Run `./start_mcp_server.sh`  
3. **🗣️ CHAT:** Open Copilot Chat and start using tools
4. **🧪 TEST:** Try the example prompts above

**Your IPFS Datasets MCP tools are now ready for VS Code Copilot! 🎉**
- IPFS tools work in mock mode when IPFS daemon is not available
- Vector tools fall back to numpy when FAISS is not available
