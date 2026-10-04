"""Log trace extractor for runtime monitoring inputs."""

from __future__ import annotations

from typing import Any, Iterable


class LogTraceExtractor:
    """Normalize raw audit events into monitor-friendly dictionaries."""

    def extract(self, events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        return [dict(event) for event in events]
