"""
Logger configuration for IPFS Datasets MCP server.
"""
import logging
import sys
from pathlib import Path


mcp_log_path = Path(__file__).parent / "mcp_server.log"
mcp_log_path.touch()  # Create the log file if it doesn't exist

# Configure root logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        #logging.StreamHandler(sys.stdout),
        logging.FileHandler(mcp_log_path, mode="a"),
    ],
)

# Create logger for this module
logger = logging.getLogger("ipfs_datasets.mcp_server")

# Create logger for MCP-specific messages
mcp_logger = logging.getLogger("ipfs_datasets.mcp")

# Set log levels
logger.setLevel(logging.INFO)
mcp_logger.setLevel(logging.INFO)

# Ensure the log directory exists
log_dir = Path.home() / ".ipfs_datasets"
log_dir.mkdir(exist_ok=True)

