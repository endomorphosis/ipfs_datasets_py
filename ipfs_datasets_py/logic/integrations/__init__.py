"""Integrations exposed under the consolidated logic namespace.

This package is designed to be safe for `from ... import *` (used by legacy
compatibility shims). Avoid listing module names in `__all__` unless they are
actual attributes.
"""

from __future__ import annotations

import logging

# Optional integrations may depend on heavyweight or extra dependencies.
try:  # pragma: no cover
	from .enhanced_graphrag_integration import *  # noqa: F401,F403
except Exception as e:  # pragma: no cover
	logging.getLogger(__name__).warning(
		"Enhanced GraphRAG integration unavailable: %s", e
	)

try:  # pragma: no cover
	from .unixfs_integration import *  # noqa: F401,F403
except Exception as e:  # pragma: no cover
	logging.getLogger(__name__).warning("UnixFS integration unavailable: %s", e)

# Do not define __all__ here; the imported modules may define their own.
