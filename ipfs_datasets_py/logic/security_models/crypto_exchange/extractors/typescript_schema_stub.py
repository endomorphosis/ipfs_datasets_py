"""TypeScript/WASM schema stub emitter."""

from __future__ import annotations

import json

from ..ir.schema import SecurityModelIR, validate_ir


class TypeScriptSchemaStub:
    """Emit deterministic JSON for future TypeScript schema generation."""

    def emit_schema(self, model: SecurityModelIR) -> str:
        validated = validate_ir(model)
        return json.dumps(
            {
                'todo': 'Generate branded TypeScript/WASM-facing schema and validators.',
                'model_id': validated.model_id,
                'schema_version': validated.schema_version,
            },
            sort_keys=True,
            separators=(',', ':'),
        )
