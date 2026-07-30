"""Cross-surface knowledge-graph conformance suite (KGP-017 … KGP-020).

KGP-020 adds transport-neutral golden vectors executed over Python, CLI, MCP,
and MCP++ with exact rows / revision / error-code parity after metadata
normalization.
"""

from __future__ import annotations

CONFORMANCE_CONTRACT = "kg-conformance-vectors/v1"
SURFACES = ("python", "cli", "mcp", "mcp_plus")

__all__ = ["CONFORMANCE_CONTRACT", "SURFACES"]
