"""InterPlanetary Wayback Machine (IPWB) integration for decentralized web archiving.

Business logic has been extracted to the canonical package module:
    ipfs_datasets_py/web_archiving/ipwb_engine.py

This file is now a thin re-export shim so existing imports continue to work.
"""
from ipfs_datasets_py.web_archiving.ipwb_engine import (  # noqa: F401
    index_warc_to_ipwb,
    start_ipwb_replay,
    search_ipwb_archive,
    get_ipwb_content,
    verify_ipwb_archive,
)
