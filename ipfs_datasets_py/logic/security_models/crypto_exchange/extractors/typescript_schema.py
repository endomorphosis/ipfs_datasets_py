"""TypeScript/WASM schema emitter for the security IR."""

from __future__ import annotations

import json

from ..ir.schema import REQUIRED_SEQUENCE_FIELDS, SecurityModelIR, validate_ir


class TypeScriptSchemaEmitter:
    """Emit a deterministic TypeScript module for ``SecurityModelIR``."""

    def emit_schema(self, model: SecurityModelIR) -> str:
        validated = validate_ir(model)
        metadata = {
            'schemaVersion': validated.schema_version,
            'requiredFields': list(REQUIRED_SEQUENCE_FIELDS),
            'proverTargets': list(validated.prover_targets),
            'assumptionIds': [
                assumption['id'] if isinstance(assumption, dict) else assumption
                for assumption in validated.assumptions
            ],
        }
        lines = [
            'export type SecurityRecord = Record<string, unknown>;',
            '',
            'export interface SecurityAssumption {',
            '  id: string;',
            '  description: string;',
            '}',
            '',
            'export interface SecurityModelIR {',
            '  schema_version: string;',
            '  model_id: string;',
            '  entities: SecurityRecord[];',
            '  assets: SecurityRecord[];',
            '  wallets: SecurityRecord[];',
            '  accounts: SecurityRecord[];',
            '  roles: SecurityRecord[];',
            '  principals: SecurityRecord[];',
            '  capabilities: SecurityRecord[];',
            '  policies: SecurityRecord[];',
            '  events: SecurityRecord[];',
            '  state_machines: SecurityRecord[];',
            '  invariants: SecurityRecord[];',
            '  assumptions: Array<string | SecurityAssumption>;',
            '  prover_targets: string[];',
            '  metadata: SecurityRecord;',
            '}',
            '',
            f'export const SECURITY_MODEL_IR_SCHEMA_VERSION = {json.dumps(validated.schema_version)} as const;',
            f'export const SECURITY_MODEL_IR_METADATA = {json.dumps(metadata, indent=2, sort_keys=True)} as const;',
            '',
            'export function isSecurityModelIR(value: unknown): value is SecurityModelIR {',
            '  if (!value || typeof value !== "object") {',
            '    return false;',
            '  }',
            '  const candidate = value as Record<string, unknown>;',
            '  if (typeof candidate.schema_version !== "string" || typeof candidate.model_id !== "string") {',
            '    return false;',
            '  }',
            '  return SECURITY_MODEL_IR_METADATA.requiredFields.every((field) => Array.isArray(candidate[field]));',
            '}',
            '',
            'export function assertSecurityModelIR(value: unknown): asserts value is SecurityModelIR {',
            '  if (!isSecurityModelIR(value)) {',
            '    throw new TypeError("value is not a valid SecurityModelIR payload");',
            '  }',
            '}',
        ]
        return '\n'.join(lines) + '\n'
