"""Backward-compat shim: exposes interactive.interactive_fol_constructor as a
top-level attribute of the integration package.

Usage::

    from ipfs_datasets_py.logic.integration import interactive_fol_constructor
    constructor = interactive_fol_constructor.InteractiveFOLConstructor()
"""
from .interactive.interactive_fol_constructor import (  # noqa: F401
    InteractiveFOLConstructor,
)
from .interactive import interactive_fol_constructor as _mod  # noqa: F401

# Re-export at module level so callers can do
#   interactive_fol_constructor.InteractiveFOLConstructor()
__all__ = ["InteractiveFOLConstructor"]
