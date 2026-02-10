"""Integrations exposed under the consolidated logic namespace.

This package is designed to be safe for `from ... import *` (used by legacy
compatibility shims). Avoid listing module names in `__all__` unless they are
actual attributes.
"""

from __future__ import annotations

# Re-export integration symbols for convenience.
from .graphrag_integration import *  # noqa: F401,F403
from .enhanced_graphrag_integration import *  # noqa: F401,F403
from .unixfs_integration import *  # noqa: F401,F403

# Do not define __all__ here; the imported modules may define their own.
