"""Compatibility shim for the P2P workflow scheduler.

Tests and older integrations import `ipfs_datasets_py.p2p_workflow_scheduler`.
The implementation lives in `ipfs_datasets_py.p2p_networking.p2p_workflow_scheduler`.
"""

from ipfs_datasets_py.p2p_networking.p2p_workflow_scheduler import *  # noqa: F401,F403
