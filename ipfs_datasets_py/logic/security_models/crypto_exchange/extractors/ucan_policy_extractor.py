"""UCAN policy extractor for capability-centered security models."""

from __future__ import annotations

from typing import Any, Iterable


class UCANPolicyExtractor:
    """Extract minimal capability facts from delegation-like records."""

    def extract(self, capabilities: Iterable[dict[str, Any]]) -> dict[str, Any]:
        return {'capabilities': [dict(capability) for capability in capabilities]}
