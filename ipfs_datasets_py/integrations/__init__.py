"""
External Service Integrations for Web Scraping

This module provides wrappers for external archive and search services:
- Common Crawl (multi-index searches)
- Wayback Machine (Internet Archive)
- IPWB (InterPlanetary Wayback Machine)
- WARC file handling (import/export)
- IPFS CID computation (multiformats + Kubo fallback)
"""

from .common_crawl import (
    CommonCrawlClient,
    CommonCrawlRecord,
    search_common_crawl
)

from .ipfs_cid import (
    IPFSCIDComputer,
    compute_cid_for_content,
    compute_cid_for_file,
    get_cid_computer
)

# WaybackMachineClient, IPWBClient, WARCHandler not yet implemented
# These will be added in future commits

__all__ = [
    # Common Crawl
    'CommonCrawlClient',
    'CommonCrawlRecord',
    'search_common_crawl',
    
    # IPFS CID
    'IPFSCIDComputer',
    'compute_cid_for_content',
    'compute_cid_for_file',
    'get_cid_computer',
    
    # TODO: Add when implemented
    # 'WaybackMachineClient',
    # 'IPWBClient',
    # 'WARCHandler',
]
