"""Backend protocol definition (single source of truth).

The backend protocol lives in `backends/__init__.py` so callers can import a
single stable symbol from the package.

This file remains as a backward-compatible import location.
"""

from . import ZKBackend

__all__ = ["ZKBackend"]
