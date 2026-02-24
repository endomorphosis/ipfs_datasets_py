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
import json
import base64
import re
from pathlib import Path
from typing import Dict, List, Optional, Any, Union, Literal

logger = logging.getLogger(__name__)

def _discover_common_crawl_import_roots() -> List[Path]:
    """Discover likely sys.path roots that contain `common_crawl_search_engine`."""
    here = Path(__file__).resolve().parent
    candidates: List[Path] = []

    search_roots = [here, *here.parents]
    seen: set[str] = set()

    for root in search_roots:
        # Layout: <root>/common_crawl_search_engine/__init__.py
        direct_pkg = root / "common_crawl_search_engine" / "__init__.py"
        if direct_pkg.exists():
            key = str(root)
            if key not in seen:
                seen.add(key)
                candidates.append(root)

        # Layout: <root>/src/common_crawl_search_engine/__init__.py
        src_pkg = root / "src" / "common_crawl_search_engine" / "__init__.py"
        if src_pkg.exists():
            src_root = root / "src"
            key = str(src_root)
            if key not in seen:
                seen.add(key)
                candidates.append(src_root)

    return candidates


def _ensure_common_crawl_import_path() -> Optional[Path]:
    """Ensure a valid import root for `common_crawl_search_engine` is on sys.path."""
    for root in _discover_common_crawl_import_roots():
        root_str = str(root)
        if root_str not in sys.path:
            sys.path.insert(0, root_str)
        try:
            __import__("common_crawl_search_engine")
            return root
        except Exception:
            continue
    return None


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
            import_root = _ensure_common_crawl_import_path()
            if import_root is None:
                raise ImportError("common_crawl_search_engine package not found on discoverable paths")
            from common_crawl_search_engine.ccindex import api
            self.api = api
            self._available = True
            logger.info("Common Crawl Search Engine initialized in local mode (root=%s)", import_root)
        except ImportError as e:
            logger.warning(f"Common Crawl Search Engine not available in local mode: {e}")
            logger.info("Make sure common_crawl_search_engine sources are available (e.g., in src/common_crawl_search_engine)")
            self.api = None
            self._available = False
    
    def _init_remote_mode(self) -> None:
        """Initialize remote mode with MCP JSON-RPC client."""
        if not self.mcp_endpoint:
            raise ValueError("mcp_endpoint is required for remote mode")
        
        try:
            # Import MCP client from submodule
            import_root = _ensure_common_crawl_import_path()
            if import_root is None:
                raise ImportError("common_crawl_search_engine package not found on discoverable paths")
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
        year = kwargs.get("year")
        if year is None and collection:
            match = re.search(r"(\d{4})", str(collection))
            if match:
                year = match.group(1)

        parquet_root = kwargs.get("parquet_root")
        year_db = kwargs.get("year_db")
        collection_db = kwargs.get("collection_db")
        max_parquet_files = int(kwargs.get("max_parquet_files", 200) or 200)
        per_parquet_limit = int(kwargs.get("per_parquet_limit", 2000) or 2000)

        result = self.api.search_domain_via_meta_indexes(
            domain,
            parquet_root=Path(parquet_root) if parquet_root else Path("/storage/ccindex_parquet"),
            master_db=(self.master_db_path if self.master_db_path else Path("/storage/ccindex_duckdb/cc_pointers_master/cc_master_index.duckdb")),
            year_db=(Path(year_db) if year_db else None),
            collection_db=(Path(collection_db) if collection_db else None),
            year=(str(year) if year else None),
            max_parquet_files=max_parquet_files,
            max_matches=int(max_matches),
            per_parquet_limit=per_parquet_limit,
        )
        return self._normalize_records(result.records)
    
    def _search_domain_remote(
        self,
        domain: str,
        max_matches: int,
        collection: Optional[str],
        **kwargs
    ) -> List[Dict[str, Any]]:
        """Search using remote MCP JSON-RPC client."""
        try:
            year = kwargs.get("year")
            if year is None and collection:
                match = re.search(r"(\d{4})", str(collection))
                if match:
                    year = match.group(1)

            # Dashboard/MCP tool name is `search_domain_meta`.
            result = self.mcp_client.call_tool(
                "search_domain_meta",
                {
                    "domain": domain,
                    "max_matches": int(max_matches),
                    "year": (str(year) if year else None),
                },
            )

            if isinstance(result, dict):
                records = result.get("records", [])
                if isinstance(records, list):
                    return self._normalize_records(records)
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
        cmd = [
            self.cli_command,
            "search", "meta",
            "--domain", domain,
            "--max-matches", str(max_matches)
        ]

        year = kwargs.get("year")
        if year is None and collection:
            match = re.search(r"(\d{4})", str(collection))
            if match:
                year = match.group(1)
        if year:
            cmd.extend(["--year", str(year)])

        if self.master_db_path:
            cmd.extend(["--master-db", str(self.master_db_path)])

        parquet_root = kwargs.get("parquet_root")
        if parquet_root:
            cmd.extend(["--parquet-root", str(parquet_root)])
        
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

            records: List[Dict[str, Any]] = []
            for line in (result.stdout or "").splitlines():
                text = line.strip()
                if not text:
                    continue
                try:
                    item = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    records.append(item)

            return self._normalize_records(records)
        except subprocess.TimeoutExpired:
            logger.error("CLI search timed out")
            return []
        except Exception as e:
            logger.error(f"CLI search failed: {e}")
            raise

    @staticmethod
    def _normalize_records(records: Any) -> List[Dict[str, Any]]:
        """Normalize records into a predictable list[dict] shape for callers."""
        out: List[Dict[str, Any]] = []
        if not isinstance(records, list):
            return out

        for item in records:
            if not isinstance(item, dict):
                continue
            rec = dict(item)

            url = str(rec.get("url") or rec.get("target_uri") or "").strip()
            if url:
                rec["url"] = url

            if "warc_filename" not in rec and "filename" in rec:
                rec["warc_filename"] = rec.get("filename")
            if "warc_offset" not in rec and "offset" in rec:
                rec["warc_offset"] = rec.get("offset")
            if "warc_length" not in rec and "length" in rec:
                rec["warc_length"] = rec.get("length")

            timestamp = str(rec.get("timestamp") or "").strip()
            if url and timestamp and "archive_url" not in rec and "wayback_url" not in rec:
                wb = f"https://web.archive.org/web/{timestamp}/{url}"
                rec["wayback_url"] = wb
                rec["archive_url"] = wb

            out.append(rec)

        return out
    
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
            if self.mode == "local":
                fetch, _source, _local_path = self.api.fetch_warc_record(
                    warc_filename=str(warc_filename),
                    warc_offset=int(warc_offset),
                    warc_length=int(warc_length),
                    prefix=str(kwargs.get("prefix") or "https://data.commoncrawl.org/"),
                    timeout_s=float(kwargs.get("timeout_s") or 30.0),
                    max_bytes=int(kwargs.get("max_bytes") or 2_000_000),
                    decode_gzip_text=False,
                    max_preview_chars=0,
                    cache_mode=str(kwargs.get("cache_mode") or "range"),
                    full_warc_cache_dir=(Path(str(kwargs.get("full_warc_cache_dir"))) if kwargs.get("full_warc_cache_dir") else None),
                )
                if not fetch.ok or not fetch.raw_base64:
                    raise RuntimeError(fetch.error or "empty WARC payload")
                return base64.b64decode(fetch.raw_base64)

            if self.mode == "remote":
                result = self.mcp_client.call_tool(
                    "fetch_warc_record",
                    {
                        "warc_filename": str(warc_filename),
                        "warc_offset": int(warc_offset),
                        "warc_length": int(warc_length),
                        "max_bytes": int(kwargs.get("max_bytes") or 2_000_000),
                    },
                )
                if isinstance(result, dict) and result.get("raw_base64"):
                    return base64.b64decode(str(result.get("raw_base64")))
                raise RuntimeError("remote fetch_warc_record did not include raw_base64")

            cmd = [
                self.cli_command,
                "warc",
                "fetch-record",
                "--warc-filename",
                str(warc_filename),
                "--warc-offset",
                str(int(warc_offset)),
                "--warc-length",
                str(int(warc_length)),
                "--include-raw-base64",
                "--no-http",
            ]
            if self.ssh_host:
                cmd = ["ssh", self.ssh_host] + cmd

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "CLI fetch-record failed")

            payload = json.loads(result.stdout or "{}")
            raw_b64 = payload.get("raw_base64") if isinstance(payload, dict) else None
            if not raw_b64:
                raise RuntimeError("CLI fetch-record returned no raw_base64")
            return base64.b64decode(str(raw_b64))
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
            if self.mode == "local":
                year = kwargs.get("year")
                refs = self.api.list_collections(
                    master_db=(self.master_db_path if self.master_db_path else Path("/storage/ccindex_duckdb/cc_pointers_master/cc_master_index.duckdb")),
                    year=(str(year) if year else None),
                )
                return [str(r.collection) for r in refs if getattr(r, "collection", None)]

            if self.mode == "remote":
                info = self.mcp_client.collinfo_list(prefer_cache=bool(kwargs.get("prefer_cache", True)))
                collections = info.get("collections", []) if isinstance(info, dict) else []
                out: List[str] = []
                for item in collections:
                    if not isinstance(item, dict):
                        continue
                    collection_name = str(item.get("id") or item.get("name") or "").strip()
                    if collection_name:
                        out.append(collection_name)
                return out

            cmd = [self.cli_command, "mcp", "call", "--tool", "cc_collinfo_list", "--args-json", "{}"]
            if self.ssh_host:
                cmd = ["ssh", self.ssh_host] + cmd
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                return []
            payload = json.loads(result.stdout or "{}")
            collections = payload.get("collections", []) if isinstance(payload, dict) else []
            out: List[str] = []
            for item in collections:
                if not isinstance(item, dict):
                    continue
                collection_name = str(item.get("id") or item.get("name") or "").strip()
                if collection_name:
                    out.append(collection_name)
            return out
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
            collection_s = str(collection).strip()
            if not collection_s:
                return {}

            if self.mode == "local":
                try:
                    from common_crawl_search_engine.ccindex.orchestrator_manager import load_collinfo
                    data = load_collinfo(prefer_cache=bool(kwargs.get("prefer_cache", True)))
                    collections = data.get("collections", []) if isinstance(data, dict) else []
                    for item in collections:
                        if not isinstance(item, dict):
                            continue
                        if str(item.get("id") or item.get("name") or "").strip() == collection_s:
                            return item
                except Exception:
                    pass

                for ref in self.api.list_collections(
                    master_db=(self.master_db_path if self.master_db_path else Path("/storage/ccindex_duckdb/cc_pointers_master/cc_master_index.duckdb"))
                ):
                    if str(getattr(ref, "collection", "")).strip() == collection_s:
                        return {
                            "id": collection_s,
                            "year": getattr(ref, "year", None),
                            "collection_db_path": str(getattr(ref, "collection_db_path", "")),
                        }
                return {}

            if self.mode == "remote":
                info = self.mcp_client.collinfo_list(prefer_cache=bool(kwargs.get("prefer_cache", True)))
                collections = info.get("collections", []) if isinstance(info, dict) else []
                for item in collections:
                    if not isinstance(item, dict):
                        continue
                    if str(item.get("id") or item.get("name") or "").strip() == collection_s:
                        return item
                return {}

            names = self.list_collections(**kwargs)
            if collection_s in names:
                return {"id": collection_s}
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
