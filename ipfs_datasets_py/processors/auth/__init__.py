"""
Authentication module for IPFS Datasets Python.

This module provides authentication and authorization utilities including
UCAN (User Controlled Authorization Networks) support.

Migrated from data_transformation in v2.0.0 migration.

Components:
    - ucan: UCAN token generation and verification
"""

from .ucan import *

__all__ = ['ucan']

# Auth engine (moved from mcp_server/tools)
try:
    from .auth_engine import MockAuthService
except ImportError:
    pass
