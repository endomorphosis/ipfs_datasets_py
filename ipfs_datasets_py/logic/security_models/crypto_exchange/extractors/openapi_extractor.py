"""OpenAPI extractor for HTTP-facing exchange models."""

from __future__ import annotations

from typing import Any, Mapping


class OpenAPIExtractor:
    """Extract operation metadata from an OpenAPI-like mapping."""

    def extract(self, spec: Mapping[str, Any]) -> dict[str, Any]:
        operations: list[dict[str, Any]] = []
        for path, methods in spec.get('paths', {}).items():
            for method, definition in methods.items():
                operations.append({'path': path, 'method': method.lower(), 'operation_id': definition.get('operationId', '')})
        return {'operations': operations}
