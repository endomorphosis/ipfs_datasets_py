"""Core logic conversion APIs.

These functions live in the package (not the MCP server tool layer) so they can be
used directly by Python callers. MCP tools should wrap these APIs.
"""

from .text_to_fol import convert_text_to_fol
from .legal_text_to_deontic import convert_legal_text_to_deontic

__all__ = [
    "convert_text_to_fol",
    "convert_legal_text_to_deontic",
]
