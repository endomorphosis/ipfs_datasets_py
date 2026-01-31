"""Integration wrapper for Common Crawl Search Engine.

This module provides a clean interface to the common_crawl_search_engine submodule,
enabling advanced web archiving and internet search capabilities as a fallback/redundancy
system that avoids Cloudflare bottlenecks for RAG data retrieval from the internet.

Supports three integration modes:
1. Local/Embedded - Direct package imports when submodule is local
2. Remote MCP JSON-RPC - Connect to standalone MCP server on another machine
3. CLI - Execute CLI commands (local or remote via SSH)
"""

import logging
import os
import sys
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Any, Union, Literal

logger = logging.getLogger(__name__)

# Add the submodule to the Python path if not already there
SUBMODULE_PATH = Path(__file__).parent / "common_crawl_search_engine"
if SUBMODULE_PATH.exists() and str(SUBMODULE_PATH) not in sys.path:
    sys.path.insert(0, str(SUBMODULE_PATH))


class CommonCrawlSearchEngine:
    """
    Wrapper class for the Common Crawl Search Engine integration.
    
    This class provides a clean, pythonic interface to the common_crawl_search_engine
    submodule for searching and retrieving data from Common Crawl archives. It serves
    as a redundancy/fallback system for internet data retrieval when dealing with
    Cloudflare bottlenecks or other access restrictions.
    
    Supports three integration modes:
    1. **local** - Direct package imports (default, when submodule is available)
    2. **remote** - MCP JSON-RPC client to connect to standalone server on another machine
    3. **cli** - Execute CLI commands (for local or remote via SSH)
    
    Key Features:
    - Fast domain/URL lookups using rowgroup slicing
    - Per-collection and per-year rowgroup index support
    - WARC record fetching and content extraction
    - Integration with MCP server for AI assistant access
    - Support for batch operations and parallel queries
    - Seamless fallback between local and remote modes
    
    Attributes:
        mode: Integration mode ("local", "remote", or "cli")
        master_db_path: Path to the master DuckDB index (local mode)
        state_dir: Directory for storing state and event logs (local mode)
        mcp_endpoint: MCP server endpoint URL (remote mode)
        mcp_client: MCP JSON-RPC client instance (remote mode)
        
    Examples:
        Local mode (default):
        >>> engine = CommonCrawlSearchEngine()
        >>> results = engine.search_domain("example.com", max_matches=50)
        
        Remote mode (connect to standalone MCP server):
        >>> engine = CommonCrawlSearchEngine(
        ...     mode="remote",
        ...     mcp_endpoint="http://ccindex-server.example.com:8787"
        ... )
        >>> results = engine.search_domain("example.com", max_matches=50)
        
        CLI mode:
        >>> engine = CommonCrawlSearchEngine(mode="cli")
        >>> results = engine.search_domain("example.com", max_matches=50)
    """
    
    def __init__(
        self,
        mode: Literal["local", "remote", "cli"] = "local",
        master_db_path: Optional[Union[str, Path]] = None,
        state_dir: Optional[Union[str, Path]] = None,
        rowgroup_index_dir: Optional[Union[str, Path]] = None,
        year_index_dir: Optional[Union[str, Path]] = None,
        mcp_endpoint: Optional[str] = None,
        mcp_timeout: float = 30.0,
        cli_command: str = "ccindex",
        ssh_host: Optional[str] = None,
        **kwargs
    ):
        """
        Initialize the Common Crawl Search Engine integration.
        
        Args:
            mode: Integration mode - "local", "remote", or "cli"
            master_db_path: Path to master DuckDB index (local mode only)
            state_dir: Directory for state/logs (local mode, defaults to "state")
            rowgroup_index_dir: Per-collection rowgroup index directory (local mode)
            year_index_dir: Per-year rowgroup index directory (local mode)
            mcp_endpoint: MCP server endpoint (remote mode, e.g., "http://host:8787")
            mcp_timeout: MCP request timeout in seconds (remote mode, default: 30.0)
            cli_command: CLI command name (cli mode, default: "ccindex")
            ssh_host: SSH host for remote CLI execution (cli mode, optional)
            **kwargs: Additional configuration options
        """
        self.mode = mode
        self.master_db_path = Path(master_db_path) if master_db_path else None
        self.state_dir = Path(state_dir) if state_dir else Path("state")
        self.rowgroup_index_dir = Path(rowgroup_index_dir) if rowgroup_index_dir else None
        self.year_index_dir = Path(year_index_dir) if year_index_dir else None
        self.mcp_endpoint = mcp_endpoint
        self.mcp_timeout = mcp_timeout
        self.cli_command = cli_command
        self.ssh_host = ssh_host
        
        # Initialize based on mode
        if mode == "local":
            self._init_local_mode()
        elif mode == "remote":
            self._init_remote_mode()
        elif mode == "cli":
            self._init_cli_mode()
        else:
            raise ValueError(f"Invalid mode: {mode}. Must be 'local', 'remote', or 'cli'")
    
    def _init_local_mode(self) -> None:
        """Initialize local/embedded mode with direct package imports."""
        # Create state directory if it doesn't exist
        self.state_dir.mkdir(parents=True, exist_ok=True)
        
        # Set environment variables for ccindex
        self._configure_environment()
        
        # Import ccindex API (lazy import to avoid issues if submodule isn't initialized)
        try:
            from common_crawl_search_engine.ccindex import api
            self.api = api
            self._available = True
            logger.info("Common Crawl Search Engine initialized in local mode")
        except ImportError as e:
            logger.warning(f"Common Crawl Search Engine not available in local mode: {e}")
            logger.info("Make sure to initialize the submodule: git submodule update --init --recursive")
            self.api = None
            self._available = False
    
    def _init_remote_mode(self) -> None:
        """Initialize remote mode with MCP JSON-RPC client."""
        if not self.mcp_endpoint:
            raise ValueError("mcp_endpoint is required for remote mode")
        
        try:
            # Import MCP client from submodule
            from common_crawl_search_engine.mcp_client import CcindexMcpClient
            
            self.mcp_client = CcindexMcpClient(
                endpoint=self.mcp_endpoint,
                timeout_s=self.mcp_timeout
            )
            self._available = True
            logger.info(f"Common Crawl Search Engine initialized in remote mode: {self.mcp_endpoint}")
        except ImportError as e:
            logger.error(f"Failed to import MCP client: {e}")
            self.mcp_client = None
            self._available = False
    
    def _init_cli_mode(self) -> None:
        """Initialize CLI mode."""
        # Check if ccindex CLI is available
        try:
            cmd = [self.cli_command, "--help"]
            if self.ssh_host:
                cmd = ["ssh", self.ssh_host] + cmd
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=5
            )
            self._available = (result.returncode == 0)
            if self._available:
                logger.info(f"Common Crawl Search Engine initialized in CLI mode: {self.cli_command}")
            else:
                logger.warning(f"CLI command '{self.cli_command}' not available or returned error")
        except Exception as e:
            logger.error(f"Failed to initialize CLI mode: {e}")
            self._available = False
    
    def _configure_environment(self) -> None:
        """Configure environment variables for ccindex."""
        os.environ.setdefault("CCINDEX_STATE_DIR", str(self.state_dir))
        os.environ.setdefault("CCINDEX_EVENT_LOG_PATH", str(self.state_dir / "ccindex_events.jsonl"))
        os.environ.setdefault("CCINDEX_BRAVE_TRACE", "1")
        os.environ.setdefault("BRAVE_RESOLVE_STRATEGY", "domain_url_join_parallel")
        os.environ.setdefault("BRAVE_RESOLVE_ROWGROUP_SLICE_MODE", "auto")
        os.environ.setdefault("BRAVE_RESOLVE_SKIP_LEGACY_SCHEMA", "1")
        os.environ.setdefault("BRAVE_RESOLVE_ROWGROUP_WORKERS", "8")
        
        if self.rowgroup_index_dir:
            os.environ["BRAVE_RESOLVE_ROWGROUP_INDEX_DIR"] = str(self.rowgroup_index_dir)
        if self.year_index_dir:
            os.environ["BRAVE_RESOLVE_ROWGROUP_YEAR_DIR"] = str(self.year_index_dir)
    
    def is_available(self) -> bool:
        """Check if the Common Crawl Search Engine is available."""
        return self._available
    
    def search_domain(
        self,
        domain: str,
        max_matches: int = 100,
        collection: Optional[str] = None,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """
        Search Common Crawl for URLs from a specific domain.
        
        Works in all three modes: local, remote, and CLI.
        
        Args:
            domain: Domain to search for (e.g., "example.com")
            max_matches: Maximum number of matches to return
            collection: Specific Common Crawl collection (e.g., "CC-MAIN-2024-10")
            **kwargs: Additional search parameters
            
        Returns:
            List of matching records with URL, timestamp, and WARC location info
            
        Raises:
            RuntimeError: If the search engine is not available
        """
        if not self._available:
            raise RuntimeError(f"Common Crawl Search Engine is not available in {self.mode} mode")
        
        logger.info(f"Searching Common Crawl for domain: {domain} (mode: {self.mode})")
        
        try:
            if self.mode == "local":
                return self._search_domain_local(domain, max_matches, collection, **kwargs)
            elif self.mode == "remote":
                return self._search_domain_remote(domain, max_matches, collection, **kwargs)
            elif self.mode == "cli":
                return self._search_domain_cli(domain, max_matches, collection, **kwargs)
        except Exception as e:
            logger.error(f"Error searching Common Crawl: {e}")
            raise
    
    def _search_domain_local(
        self,
        domain: str,
        max_matches: int,
        collection: Optional[str],
        **kwargs
    ) -> List[Dict[str, Any]]:
        """Search using local package imports."""
        # TODO: Call actual ccindex search API when available
        logger.warning("Local search functionality not yet fully implemented - placeholder return")
        return []
    
    def _search_domain_remote(
        self,
        domain: str,
        max_matches: int,
        collection: Optional[str],
        **kwargs
    ) -> List[Dict[str, Any]]:
        """Search using remote MCP JSON-RPC client."""
        try:
            # Call MCP tool for domain search
            result = self.mcp_client.call_tool(
                "search_domain",
                {
                    "domain": domain,
                    "max_matches": max_matches,
                    "collection": collection
                }
            )
            
            # Extract results from MCP response
            if isinstance(result, dict):
                return result.get("results", [])
            return []
        except Exception as e:
            logger.error(f"Remote search failed: {e}")
            raise
    
    def _search_domain_cli(
        self,
        domain: str,
        max_matches: int,
        collection: Optional[str],
        **kwargs
    ) -> List[Dict[str, Any]]:
        """Search using CLI command."""
        import json
        
        cmd = [
            self.cli_command,
            "search", "meta",
            "--domain", domain,
            "--max-matches", str(max_matches)
        ]
        
        if collection:
            cmd.extend(["--collection", collection])
        
        if self.ssh_host:
            cmd = ["ssh", self.ssh_host] + cmd
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode != 0:
                logger.error(f"CLI search failed: {result.stderr}")
                return []
            
            # Parse JSON output
            try:
                data = json.loads(result.stdout)
                return data if isinstance(data, list) else []
            except json.JSONDecodeError:
                logger.warning("Failed to parse CLI output as JSON")
                return []
        except subprocess.TimeoutExpired:
            logger.error("CLI search timed out")
            return []
        except Exception as e:
            logger.error(f"CLI search failed: {e}")
            raise
    
    def fetch_warc_record(
        self,
        warc_filename: str,
        warc_offset: int,
        warc_length: int,
        **kwargs
    ) -> bytes:
        """
        Fetch a WARC record from Common Crawl.
        
        Args:
            warc_filename: WARC file name
            warc_offset: Byte offset in the WARC file
            warc_length: Length of the record in bytes
            **kwargs: Additional fetch parameters
            
        Returns:
            Raw WARC record bytes
            
        Raises:
            RuntimeError: If the search engine is not available
        """
        if not self._available:
            raise RuntimeError("Common Crawl Search Engine is not available")
        
        logger.info(f"Fetching WARC record: {warc_filename} @ {warc_offset}:{warc_length}")
        
        try:
            # TODO: Call actual ccindex WARC fetch API when available
            raise NotImplementedError("WARC fetch functionality not yet implemented")
        except Exception as e:
            logger.error(f"Error fetching WARC record: {e}")
            raise
    
    def list_collections(self, **kwargs) -> List[str]:
        """
        List available Common Crawl collections.
        
        Args:
            **kwargs: Additional parameters
            
        Returns:
            List of collection names (e.g., ["CC-MAIN-2024-10", ...])
            
        Raises:
            RuntimeError: If the search engine is not available
        """
        if not self._available:
            raise RuntimeError("Common Crawl Search Engine is not available")
        
        try:
            # TODO: Call actual ccindex list collections API when available
            logger.warning("List collections functionality not yet implemented - placeholder return")
            return []
        except Exception as e:
            logger.error(f"Error listing collections: {e}")
            raise
    
    def get_collection_info(self, collection: str, **kwargs) -> Dict[str, Any]:
        """
        Get information about a specific Common Crawl collection.
        
        Args:
            collection: Collection name (e.g., "CC-MAIN-2024-10")
            **kwargs: Additional parameters
            
        Returns:
            Dictionary with collection metadata
            
        Raises:
            RuntimeError: If the search engine is not available
        """
        if not self._available:
            raise RuntimeError("Common Crawl Search Engine is not available")
        
        try:
            # TODO: Call actual ccindex collection info API when available
            logger.warning("Collection info functionality not yet implemented - placeholder return")
            return {}
        except Exception as e:
            logger.error(f"Error getting collection info: {e}")
            raise


# Convenience function for quick access
def create_search_engine(**kwargs) -> CommonCrawlSearchEngine:
    """
    Create a CommonCrawlSearchEngine instance with default configuration.
    
    Args:
        **kwargs: Configuration options passed to CommonCrawlSearchEngine
        
    Returns:
        Configured CommonCrawlSearchEngine instance
    """
    return CommonCrawlSearchEngine(**kwargs)


__all__ = [
    "CommonCrawlSearchEngine",
    "create_search_engine",
]
