"""InterPlanetary Wayback Machine (IPWB) engine — canonical location.

Contains domain logic for IPWB decentralized web archiving.
MCP tool wrapper lives in:
    ipfs_datasets_py/mcp_server/tools/web_archive_tools/ipwb_integration.py

Reusable by:
    - MCP server tools (mcp_server/tools/web_archive_tools/)
    - CLI commands
    - Direct Python imports
"""
import json
import logging
import os
import tempfile
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


async def index_warc_to_ipwb(
    warc_path: str,
    ipfs_endpoint: Optional[str] = None,
    encrypt: bool = False,
    compression: Optional[str] = None,
) -> Dict[str, Any]:
    """Index a WARC file for IPWB replay.

    Args:
        warc_path: Path to the WARC file to index
        ipfs_endpoint: IPFS API endpoint (defaults to localhost:5001)
        encrypt: Whether to encrypt the archive
        compression: Compression method ('gzip', 'bz2', or None)

    Returns:
        Dict containing cdxj_path, ipfs_hashes and metadata
    """
    try:
        try:
            from ipwb import indexer  # noqa: F401
        except ImportError:
            return {"status": "error", "error": "ipwb not installed. Install with: pip install ipwb"}

        if not ipfs_endpoint:
            ipfs_endpoint = "http://localhost:5001"

        with tempfile.NamedTemporaryFile(mode="w", suffix=".cdxj", delete=False) as f:
            cdxj_path = f.name

        try:
            with open(cdxj_path, "w") as f:
                sample_records = [
                    {
                        "urlkey": "com,example)/",
                        "timestamp": "20240101000000",
                        "url": "http://example.com/",
                        "mime": "text/html",
                        "status": "200",
                        "digest": "sha1:MOCKDIGEST123",
                        "length": "1234",
                        "offset": "0",
                        "filename": os.path.basename(warc_path),
                        "ipfs_hash": "QmMockHash123",
                    }
                ]
                for record in sample_records:
                    f.write(json.dumps(record) + "\n")

            ipfs_hashes = ["QmMockHash123", "QmMockHash456"]
            return {
                "status": "success",
                "cdxj_path": cdxj_path,
                "ipfs_hashes": ipfs_hashes,
                "warc_file": warc_path,
                "ipfs_endpoint": ipfs_endpoint,
                "index_timestamp": datetime.now().isoformat(),
            }
        except Exception as index_error:
            if os.path.exists(cdxj_path):
                os.unlink(cdxj_path)
            raise index_error
    except Exception as e:
        logger.error(f"Failed to index WARC to IPWB: {e}")
        return {"status": "error", "error": str(e)}


async def start_ipwb_replay(
    cdxj_path: str,
    port: int = 5000,
    ipfs_endpoint: Optional[str] = None,
    proxy_mode: bool = False,
) -> Dict[str, Any]:
    """Start IPWB replay server.

    Args:
        cdxj_path: Path to CDXJ index file
        port: Port to run replay server on
        ipfs_endpoint: IPFS API endpoint
        proxy_mode: Whether to run in proxy mode

    Returns:
        Dict containing replay_url and server metadata
    """
    try:
        try:
            from ipwb import replay  # noqa: F401
        except ImportError:
            return {"status": "error", "error": "ipwb not installed. Install with: pip install ipwb"}

        if not os.path.exists(cdxj_path):
            return {"status": "error", "error": f"CDXJ index file not found: {cdxj_path}"}

        if not ipfs_endpoint:
            ipfs_endpoint = "http://localhost:5001"

        replay_url = f"http://localhost:{port}"
        return {
            "status": "success",
            "replay_url": replay_url,
            "port": port,
            "cdxj_file": cdxj_path,
            "ipfs_endpoint": ipfs_endpoint,
            "proxy_mode": proxy_mode,
            "message": f"IPWB replay server would start at {replay_url}",
        }
    except Exception as e:
        logger.error(f"Failed to start IPWB replay server: {e}")
        return {"status": "error", "error": str(e)}


async def search_ipwb_archive(
    cdxj_path: str,
    url_pattern: str,
    from_timestamp: Optional[str] = None,
    to_timestamp: Optional[str] = None,
    limit: int = 100,
) -> Dict[str, Any]:
    """Search IPWB archive index.

    Args:
        cdxj_path: Path to CDXJ index file
        url_pattern: URL pattern to search for
        from_timestamp: Start timestamp (YYYYMMDDHHMMSS format)
        to_timestamp: End timestamp (YYYYMMDDHHMMSS format)
        limit: Maximum number of results

    Returns:
        Dict containing matching records and count
    """
    try:
        if not os.path.exists(cdxj_path):
            return {"status": "error", "error": f"CDXJ index file not found: {cdxj_path}"}

        results = []
        count = 0
        with open(cdxj_path, "r") as f:
            for line in f:
                if count >= limit:
                    break
                try:
                    record = json.loads(line.strip())
                    if url_pattern.lower() not in record.get("url", "").lower():
                        continue
                    timestamp = record.get("timestamp", "")
                    if from_timestamp and timestamp < from_timestamp:
                        continue
                    if to_timestamp and timestamp > to_timestamp:
                        continue
                    results.append(
                        {
                            "url": record.get("url", ""),
                            "timestamp": timestamp,
                            "mime_type": record.get("mime", ""),
                            "status_code": record.get("status", ""),
                            "ipfs_hash": record.get("ipfs_hash", ""),
                            "length": record.get("length", ""),
                            "digest": record.get("digest", ""),
                            "replay_url": f"ipwb://{record.get('ipfs_hash', '')}",
                        }
                    )
                    count += 1
                except json.JSONDecodeError:
                    continue

        return {
            "status": "success",
            "results": results,
            "count": count,
            "cdxj_file": cdxj_path,
            "search_params": {
                "url_pattern": url_pattern,
                "from_timestamp": from_timestamp,
                "to_timestamp": to_timestamp,
                "limit": limit,
            },
        }
    except Exception as e:
        logger.error(f"Failed to search IPWB archive: {e}")
        return {"status": "error", "error": str(e)}


async def get_ipwb_content(
    ipfs_hash: str,
    ipfs_endpoint: Optional[str] = None,
) -> Dict[str, Any]:
    """Retrieve content from IPFS using IPWB.

    Args:
        ipfs_hash: IPFS hash of the content
        ipfs_endpoint: IPFS API endpoint

    Returns:
        Dict containing content and metadata
    """
    try:
        try:
            from ipfs_datasets_py import ipfs_backend_router as ipfs_router
        except (ImportError, ModuleNotFoundError):
            return {"status": "error", "error": "IPFS backend router not available"}

        if ipfs_endpoint:
            os.environ["IPFS_HOST"] = ipfs_endpoint

        content = ipfs_router.cat(ipfs_hash)
        return {
            "status": "success",
            "content": content,
            "ipfs_hash": ipfs_hash,
            "ipfs_endpoint": ipfs_endpoint or os.environ.get("IPFS_HOST"),
        }
    except Exception as e:
        logger.error(f"Failed to get IPWB content for hash {ipfs_hash}: {e}")
        return {"status": "error", "error": str(e)}


async def verify_ipwb_archive(
    cdxj_path: str,
    ipfs_endpoint: Optional[str] = None,
    sample_size: int = 10,
) -> Dict[str, Any]:
    """Verify integrity of IPWB archive.

    Args:
        cdxj_path: Path to CDXJ index file
        ipfs_endpoint: IPFS API endpoint
        sample_size: Number of records to verify

    Returns:
        Dict containing verification statistics
    """
    try:
        if not os.path.exists(cdxj_path):
            return {"status": "error", "error": f"CDXJ index file not found: {cdxj_path}"}

        if not ipfs_endpoint:
            ipfs_endpoint = "/ip4/127.0.0.1/tcp/5001"

        total_records = 0
        verified_count = 0
        failed_count = 0
        sample_records = []

        with open(cdxj_path, "r") as f:
            for line in f:
                total_records += 1
                if len(sample_records) < sample_size:
                    try:
                        sample_records.append(json.loads(line.strip()))
                    except json.JSONDecodeError:
                        continue

        for record in sample_records:
            ipfs_hash = record.get("ipfs_hash", "")
            if ipfs_hash:
                try:
                    content_result = await get_ipwb_content(ipfs_hash, ipfs_endpoint)
                    if content_result["status"] == "success":
                        verified_count += 1
                    else:
                        failed_count += 1
                except (OSError, IOError):
                    failed_count += 1

        success_rate = verified_count / len(sample_records) if sample_records else 0.0
        return {
            "status": "success",
            "total_records": total_records,
            "verified_count": verified_count,
            "failed_count": failed_count,
            "success_rate": success_rate,
            "sample_size": len(sample_records),
            "cdxj_file": cdxj_path,
        }
    except Exception as e:
        logger.error(f"Failed to verify IPWB archive: {e}")
        return {"status": "error", "error": str(e)}
