"""Compatibility exports for the public ``ipfs_datasets_py.web_archiving`` namespace.

The active implementations currently live under
``ipfs_datasets_py.processors.web_archiving``. Re-exporting them here lets
callers use the stable top-level namespace directly.
"""

from .contracts import *  # noqa: F401,F403
from .unified_api import *  # noqa: F401,F403
from .unified_web_scraper import *  # noqa: F401,F403
