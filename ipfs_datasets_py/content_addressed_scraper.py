#!/usr/bin/env python3
"""
Content-Addressed Scraping System with Version Tracking

This module provides a comprehensive content-addressed scraping system that:
1. Checks if URLs have been scraped before (via CID lookup)
2. Tracks multiple versions of the same URL (like Wayback Machine)
3. Uses IPFS content addressing for deduplication
4. Integrates with unified scraping architecture
5. Stores both content CIDs and metadata CIDs
6. Supports multi-index Common Crawl searches
7. Integrates Interplanetary Wayback Machine
"""

import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
import asyncio

logger = logging.getLogger(__name__)

# Try to import IPFS and content addressing tools
try:
    import sys
    # Try to import ipfs_multiformats for fast CID computation
    parent_paths = [
        Path(__file__).parent.parent / "ipfs_datasets_py",
        Path(__file__).parent.parent / "ipfs_datasets_py" / "ipfs_datasets_py",
        Path("/home/devel/ipfs_datasets_py/ipfs_datasets_py")
    ]
    for parent_path in parent_paths:
        if parent_path.exists():
            sys.path.insert(0, str(parent_path))
            break
    
    from ipfs_multiformats import compute_cid, cid_to_string
    HAVE_IPFS_MULTIFORMATS = True
    logger.info("Using ipfs_multiformats for CID computation")
except ImportError as e:
    HAVE_IPFS_MULTIFORMATS = False
    logger.warning(f"ipfs_multiformats not available ({e}), will try Kubo fallback")

try:
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from unified_scraping_adapter import UnifiedScrapingAdapter, get_unified_scraper
    HAVE_UNIFIED_SCRAPER = True
except ImportError:
    HAVE_UNIFIED_SCRAPER = False
    logger.warning("Unified scraping adapter not available")


class ContentAddressedScraper:
    """
    Content-addressed scraper with version tracking and deduplication.
    
    This scraper:
    - Generates CIDs for both content and metadata
    - Tracks URL → CID mappings over time
    - Detects if we've already scraped this exact content
    - Stores multiple versions of the same URL
    - Integrates with IPFS for persistent storage
    """
    
    def __init__(self, 
                 cache_dir: str = "./content_addressed_cache",
                 ipfs_storage_manager=None):
        """
        Initialize content-addressed scraper.
        
        Args:
            cache_dir: Directory for storing CID mappings and version history
            ipfs_storage_manager: Optional IPFS storage manager instance
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # CID tracking databases
        self.url_to_cid_db = self.cache_dir / "url_to_cid.json"
        self.cid_to_metadata_db = self.cache_dir / "cid_metadata.json"
        self.version_history_db = self.cache_dir / "version_history.json"
        
        # Load existing mappings
        self.url_mappings = self._load_json(self.url_to_cid_db, {})
        self.cid_metadata = self._load_json(self.cid_to_metadata_db, {})
        self.version_history = self._load_json(self.version_history_db, {})
        
        # Unified scraper integration
        if HAVE_UNIFIED_SCRAPER:
            self.unified_scraper = get_unified_scraper()
        else:
            self.unified_scraper = None
        
        # IPFS integration
        self.ipfs_storage = ipfs_storage_manager
        
        logger.info(f"ContentAddressedScraper initialized with {len(self.url_mappings)} tracked URLs")
    
    def _load_json(self, path: Path, default: Any) -> Any:
        """Load JSON file or return default."""
        try:
            if path.exists():
                with open(path, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load {path}: {e}")
        return default
    
    def _save_json(self, path: Path, data: Any) -> None:
        """Save data to JSON file."""
        try:
            with open(path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save {path}: {e}")
    
    def compute_content_cid(self, content: bytes) -> str:
        """
        Compute content-addressed identifier for content.
        
        Uses ipfs_multiformats (fast), falls back to Kubo, then SHA256.
        
        Args:
            content: Raw content bytes
            
        Returns:
            CID string (IPFS-compatible or SHA256 hash)
        """
        # Method 1: Use ipfs_multiformats (fastest)
        if HAVE_IPFS_MULTIFORMATS:
            try:
                cid = compute_cid(content)
                cid_str = cid_to_string(cid)
                logger.debug(f"Computed CID using ipfs_multiformats: {cid_str}")
                return cid_str
            except Exception as e:
                logger.warning(f"ipfs_multiformats failed: {e}, trying Kubo")
        
        # Method 2: Use Kubo (ipfs add --only-hash)
        try:
            import subprocess
            result = subprocess.run(
                ['ipfs', 'add', '--only-hash', '--quiet', '-'],
                input=content,
                capture_output=True,
                timeout=5
            )
            if result.returncode == 0:
                cid_str = result.stdout.decode('utf-8').strip()
                logger.debug(f"Computed CID using Kubo: {cid_str}")
                return cid_str
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
            logger.warning(f"Kubo CID computation failed: {e}, using SHA256 fallback")
        
        # Method 3: Fallback to SHA256
        sha256_hash = hashlib.sha256(content).hexdigest()
        fallback_cid = f"sha256-{sha256_hash}"
        logger.debug(f"Using SHA256 fallback: {fallback_cid}")
        return fallback_cid
    
    def compute_metadata_cid(self, metadata: Dict[str, Any]) -> str:
        """
        Compute CID for metadata.
        
        Args:
            metadata: Metadata dictionary
            
        Returns:
            CID string for the metadata
        """
        # Normalize metadata to canonical JSON
        canonical = json.dumps(metadata, sort_keys=True, separators=(',', ':'))
        return self.compute_content_cid(canonical.encode('utf-8'))
    
    def check_url_scraped(self, url: str) -> Dict[str, Any]:
        """
        Check if a URL has been scraped before.
        
        Returns information about all versions scraped for this URL.
        
        Args:
            url: URL to check
            
        Returns:
            Dict containing:
                - scraped: bool - Whether URL has been scraped
                - versions: list - All versions scraped
                - latest_cid: str - CID of latest version
                - latest_scraped_at: str - Timestamp of latest scrape
                - total_versions: int - Number of versions
        """
        url_versions = self.version_history.get(url, [])
        
        if not url_versions:
            return {
                "scraped": False,
                "versions": [],
                "total_versions": 0
            }
        
        # Sort by timestamp to get latest
        sorted_versions = sorted(url_versions, key=lambda x: x.get('scraped_at', ''), reverse=True)
        latest = sorted_versions[0] if sorted_versions else {}
        
        return {
            "scraped": True,
            "versions": sorted_versions,
            "latest_cid": latest.get('content_cid'),
            "latest_metadata_cid": latest.get('metadata_cid'),
            "latest_scraped_at": latest.get('scraped_at'),
            "total_versions": len(url_versions)
        }
    
    def check_content_exists(self, content_cid: str) -> Dict[str, Any]:
        """
        Check if content with this CID already exists.
        
        Args:
            content_cid: Content CID to check
            
        Returns:
            Dict containing:
                - exists: bool - Whether content exists
                - metadata: dict - Metadata for this CID
                - urls: list - All URLs with this content
                - first_seen: str - Timestamp of first scrape
        """
        metadata = self.cid_metadata.get(content_cid, {})
        
        if not metadata:
            return {
                "exists": False,
                "metadata": {},
                "urls": [],
                "first_seen": None
            }
        
        return {
            "exists": True,
            "metadata": metadata,
            "urls": metadata.get('urls', []),
            "first_seen": metadata.get('first_seen'),
            "total_references": len(metadata.get('urls', []))
        }
    
    async def scrape_with_content_addressing(
        self,
        url: str,
        metadata: Optional[Dict[str, Any]] = None,
        force_rescrape: bool = False,
        check_version_changes: bool = True
    ) -> Dict[str, Any]:
        """
        Scrape URL with full content addressing and version tracking.
        
        This is the main scraping method that:
        1. Checks if URL already scraped
        2. Compares CIDs to detect content changes
        3. Uses unified scraper for retrieval
        4. Stores content and metadata with CIDs
        5. Tracks version history
        
        Args:
            url: URL to scrape
            metadata: Additional metadata to store
            force_rescrape: Force rescrape even if already scraped
            check_version_changes: Check if content changed from last version
            
        Returns:
            Dict containing:
                - status: str - "success", "cached", or "error"
                - content_cid: str - CID of the content
                - metadata_cid: str - CID of the metadata
                - content: bytes - Actual content (if scraped)
                - cached: bool - Whether using cached version
                - changed: bool - Whether content changed from last version
                - version: int - Version number for this URL
                - scraped_at: str - Timestamp
                - error: str - Error message (if failed)
        """
        scraped_at = datetime.utcnow().isoformat() + "Z"
        
        # Check if already scraped
        scrape_status = self.check_url_scraped(url)
        
        if scrape_status['scraped'] and not force_rescrape:
            logger.info(f"URL already scraped: {url} (CID: {scrape_status['latest_cid']})")
            
            if not check_version_changes:
                return {
                    "status": "cached",
                    "content_cid": scrape_status['latest_cid'],
                    "metadata_cid": scrape_status['latest_metadata_cid'],
                    "cached": True,
                    "changed": False,
                    "version": scrape_status['total_versions'],
                    "message": "Using cached version (no version check)"
                }
        
        # Scrape the URL using unified scraper
        logger.info(f"Scraping URL with content addressing: {url}")
        
        try:
            if self.unified_scraper:
                # Use unified scraper with fallbacks
                result = await self._scrape_with_unified(url)
            else:
                # Fallback to basic scraping
                result = await self._scrape_basic(url)
            
            if result['status'] != 'success':
                return result
            
            content = result['content']
            
            # Compute CIDs
            content_cid = self.compute_content_cid(content)
            
            # Build full metadata
            full_metadata = {
                "url": url,
                "scraped_at": scraped_at,
                "content_length": len(content),
                "content_type": result.get('content_type', 'unknown'),
                "status_code": result.get('status_code', 200),
                **(metadata or {})
            }
            
            metadata_cid = self.compute_metadata_cid(full_metadata)
            
            # Check if content changed
            content_changed = True
            version_number = 1
            
            if scrape_status['scraped']:
                version_number = scrape_status['total_versions'] + 1
                if scrape_status['latest_cid'] == content_cid:
                    content_changed = False
                    logger.info(f"Content unchanged for {url} (CID: {content_cid})")
                else:
                    logger.info(f"Content changed for {url}: {scrape_status['latest_cid']} → {content_cid}")
            
            # Store content CID metadata
            if content_cid not in self.cid_metadata:
                self.cid_metadata[content_cid] = {
                    "first_seen": scraped_at,
                    "urls": [],
                    "content_length": len(content),
                    "versions": []
                }
            
            # Add URL to CID mapping
            if url not in self.cid_metadata[content_cid]['urls']:
                self.cid_metadata[content_cid]['urls'].append(url)
            
            # Add version to CID metadata
            self.cid_metadata[content_cid]['versions'].append({
                "url": url,
                "metadata_cid": metadata_cid,
                "scraped_at": scraped_at,
                "version": version_number
            })
            
            # Store version history
            if url not in self.version_history:
                self.version_history[url] = []
            
            self.version_history[url].append({
                "version": version_number,
                "content_cid": content_cid,
                "metadata_cid": metadata_cid,
                "scraped_at": scraped_at,
                "content_length": len(content),
                "changed": content_changed
            })
            
            # Update URL to CID mapping (latest)
            self.url_mappings[url] = {
                "latest_content_cid": content_cid,
                "latest_metadata_cid": metadata_cid,
                "last_scraped": scraped_at,
                "total_versions": version_number
            }
            
            # Save databases
            self._save_json(self.url_to_cid_db, self.url_mappings)
            self._save_json(self.cid_to_metadata_db, self.cid_metadata)
            self._save_json(self.version_history_db, self.version_history)
            
            # Store in IPFS if available
            ipfs_result = {}
            if self.ipfs_storage:
                try:
                    ipfs_result = await self._store_in_ipfs(url, content, full_metadata, content_cid)
                except Exception as e:
                    logger.warning(f"IPFS storage failed: {e}")
            
            return {
                "status": "success",
                "content_cid": content_cid,
                "metadata_cid": metadata_cid,
                "content": content,
                "metadata": full_metadata,
                "cached": False,
                "changed": content_changed,
                "version": version_number,
                "scraped_at": scraped_at,
                "ipfs": ipfs_result
            }
        
        except Exception as e:
            logger.error(f"Failed to scrape {url}: {e}")
            return {
                "status": "error",
                "error": str(e),
                "url": url
            }
    
    async def _scrape_with_unified(self, url: str) -> Dict[str, Any]:
        """Scrape using unified web scraper with full fallback chain."""
        try:
            # Use the comprehensive unified_web_scraper
            import sys
            sys.path.insert(0, str(Path(__file__).parent))
            from unified_web_scraper import scrape_url_async
            
            result = await scrape_url_async(url)
            
            if result.success:
                return {
                    "status": "success",
                    "content": result.content if isinstance(result.content, bytes) else result.content.encode(),
                    "content_type": result.content_type or "unknown",
                    "status_code": result.status_code or 200,
                    "method": result.scraping_method
                }
            else:
                return {
                    "status": "error",
                    "error": result.error or "Unknown error"
                }
        except ImportError as e:
            logger.warning(f"unified_web_scraper not available ({e}), falling back to basic scraping")
        except Exception as e:
            logger.warning(f"Unified web scraper failed: {e}, falling back to basic scraping")
        
        # Fallback to basic requests
        import requests
        
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            response = requests.get(url, timeout=30, headers=headers)
            response.raise_for_status()
            
            return {
                "status": "success",
                "content": response.content,
                "content_type": response.headers.get('content-type', 'unknown'),
                "status_code": response.status_code,
                "method": "requests_fallback"
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e)
            }
    
    async def _scrape_basic(self, url: str) -> Dict[str, Any]:
        """Basic scraping fallback."""
        return await self._scrape_with_unified(url)
    
    async def _store_in_ipfs(
        self,
        url: str,
        content: bytes,
        metadata: Dict[str, Any],
        content_cid: str
    ) -> Dict[str, Any]:
        """Store content and metadata in IPFS."""
        if not self.ipfs_storage:
            return {"stored": False, "reason": "IPFS not available"}
        
        try:
            # Store content
            content_result = await self.ipfs_storage.add_dataset(
                name=f"scraped_{content_cid}",
                data=content,
                metadata=metadata,
                format="raw",
                pin=True
            )
            
            return {
                "stored": True,
                "ipfs_cid": content_result.get('cid'),
                "pinned": content_result.get('pinned', False)
            }
        except Exception as e:
            logger.error(f"IPFS storage failed: {e}")
            return {"stored": False, "error": str(e)}
    
    def get_url_versions(self, url: str) -> List[Dict[str, Any]]:
        """
        Get all versions of a URL.
        
        Args:
            url: URL to get versions for
            
        Returns:
            List of version dictionaries, sorted by timestamp (newest first)
        """
        versions = self.version_history.get(url, [])
        return sorted(versions, key=lambda x: x.get('scraped_at', ''), reverse=True)
    
    def find_duplicate_content(self, content_cid: str) -> List[str]:
        """
        Find all URLs with identical content (same CID).
        
        Args:
            content_cid: Content CID to search for
            
        Returns:
            List of URLs with this exact content
        """
        metadata = self.cid_metadata.get(content_cid, {})
        return metadata.get('urls', [])
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get scraping statistics."""
        total_urls = len(self.url_mappings)
        total_cids = len(self.cid_metadata)
        total_versions = sum(len(versions) for versions in self.version_history.values())
        
        # Find most duplicated content
        duplicate_counts = {
            cid: len(meta.get('urls', []))
            for cid, meta in self.cid_metadata.items()
            if len(meta.get('urls', [])) > 1
        }
        
        return {
            "total_urls_tracked": total_urls,
            "total_unique_content_cids": total_cids,
            "total_versions_scraped": total_versions,
            "duplicate_content_instances": len(duplicate_counts),
            "avg_versions_per_url": total_versions / total_urls if total_urls > 0 else 0,
            "most_duplicated_cids": sorted(
                duplicate_counts.items(),
                key=lambda x: x[1],
                reverse=True
            )[:10]
        }


# Global instance
_content_addressed_scraper = None

def get_content_addressed_scraper(
    cache_dir: str = "./content_addressed_cache",
    ipfs_storage_manager=None
) -> ContentAddressedScraper:
    """Get or create global content-addressed scraper instance."""
    global _content_addressed_scraper
    if _content_addressed_scraper is None:
        _content_addressed_scraper = ContentAddressedScraper(
            cache_dir=cache_dir,
            ipfs_storage_manager=ipfs_storage_manager
        )
    return _content_addressed_scraper


if __name__ == "__main__":
    # Example usage
    logging.basicConfig(level=logging.INFO)
    
    async def example():
        print("=" * 70)
        print("Content-Addressed Scraping System Demo")
        print("=" * 70)
        
        scraper = get_content_addressed_scraper()
        
        # Example URL
        test_url = "https://example.com"
        
        print(f"\n1. Checking if URL already scraped: {test_url}")
        status = scraper.check_url_scraped(test_url)
        print(f"   Scraped before: {status['scraped']}")
        print(f"   Total versions: {status['total_versions']}")
        
        print(f"\n2. Scraping URL with content addressing...")
        result = await scraper.scrape_with_content_addressing(test_url)
        print(f"   Status: {result['status']}")
        print(f"   Content CID: {result.get('content_cid', 'N/A')}")
        print(f"   Changed: {result.get('changed', 'N/A')}")
        print(f"   Version: {result.get('version', 'N/A')}")
        
        print(f"\n3. Getting statistics...")
        stats = scraper.get_statistics()
        print(f"   Total URLs tracked: {stats['total_urls_tracked']}")
        print(f"   Unique content CIDs: {stats['total_unique_content_cids']}")
        print(f"   Total versions: {stats['total_versions_scraped']}")
        
        print("\n✅ Demo complete!")
    
    asyncio.run(example())
