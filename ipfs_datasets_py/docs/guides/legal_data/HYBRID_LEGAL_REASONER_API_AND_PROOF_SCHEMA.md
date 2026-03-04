# Hybrid Legal Reasoner API and Proof Schema

## Overview

The Hybrid Legal Reasoner provides a V2/V3 IR-based pipeline for parsing Controlled Natural Language (CNL), normalizing it to an Intermediate Representation (IR), compiling to DCEC/TDFOL formulas, and producing traceable proof objects.

## API Reference

### CNL Parsing

#### `parse_cnl_to_ir_with_diagnostics(sentence, jurisdiction='default')`

Parses a CNL sentence to `LegalIRV2` with diagnostics.

**Returns:** `(LegalIRV2, dict)` where diagnostics includes:
- `parse_mode`: `"norm"` or `"definition"`
- `parse_confidence`: float in [0.85, 1.0]
- `parse_alternatives`: ranked modal alternatives
- `ambiguity_flags`: list of detected ambiguities
- `temporal_detected`: bool
- `activation_marker`: if/when marker or None
- `exception_marker`: unless/except marker or None

**Raises:** `CNLParseError` with `error_code`, `ambiguity_flags`, `parse_candidates` for empty or ambiguous input.

**Supported templates:**
```
<Agent> shall <VerbPhrase> [Temporal] [if/when <Clause>] [unless/except <Clause>]
<Agent> shall not <VerbPhrase> ...
<Agent> may <VerbPhrase> ...
<Term> means <Definition>
<Term> includes <Member1>, <Member2>, ...
```

#### `parse_cnl_to_ir(sentence, jurisdiction='default')`

Convenience wrapper returning just `LegalIRV2`.

### IR Validation

#### `validate_ir_v2_contract(ir, strict=True)`

Validates V2 IR/provenance contract. Raises `IRContractValidationError` on failure.

**Returns:** `{'ok': True, 'strict': bool, 'warnings': [...], 'warning_codes': [...], 'counts': {...}}`

#### `validate_v2_canonical_id_registry(ir, strict=True)`

Validates canonical ID namespaces and cross-references. Raises `IDRegistryValidationError` on failure.

### V3 Payload Validation

#### `validate_v3_ir_payload(payload, strict=True)`

Validates a V3 IR payload dict (used for JSON schema compliance checking).

**Validates:**
- `ir_version` must be `"3.0"`
- `cnl_version` must be `"3.0"`
- All entity refs start with `ent:`, frames with `frm:`, temporals with `tmp:`, norms with `nrm:`, sources with `src:`
- No unknown target_frame_ref, temporal_ref, or source_ref
- Orphan frame/temporal IDs become errors in strict mode

**Error codes:** `V3_SCHEMA_INVALID_NAMESPACE`, `V3_SCHEMA_ID_KEY_MISMATCH`, `V3_SCHEMA_UNKNOWN_TARGET_FRAME_REF`, `V3_SCHEMA_ORPHAN_FRAME_ID`, etc.

#### `map_v2_payload_to_v3(payload)`

Maps a V2 payload dict to V3-compatible shape. Normalizes version fields, renames `temporal` → `temporals`, and normalizes IDs to namespace-prefixed form.

#### `deterministic_v3_canonical_id(namespace, parts)`

Creates a deterministic canonical ID string. `namespace` must be one of `{ent, frm, tmp, nrm, src}`.

### Compilation

#### `compile_ir_to_dcec(ir)`

Compiles `LegalIRV2` to DCEC/Event Calculus formulas.

**Output format per norm:**
```
Frame(frm:HASH, action, predicate)
forall t (activation and temporal_guard and not(exceptions) -> O(frm:HASH))
```

Deontic operators (`O`/`P`/`F`) wrap `FrameRef` references, never raw predicates.

#### `compile_ir_to_temporal_deontic_fol(ir)`

Compiles to Temporal Deontic FOL formulas.

**Output format per norm:**
```
forall t (activation and temporal_guard and not(exceptions) -> O(frm:HASH, t))
```

The time variable `t` is always universally quantified — no free-variable leakage.

#### `build_v2_compiler_parity_report(ir, dcec_formulas=None, tdfol_formulas=None)`

Compares DCEC and TDFOL outputs for semantic parity.

**Returns:** `{'summary': {'norm_count', 'dcec_count', 'tdfol_count', 'inconsistency_count', 'has_inconsistencies'}, 'entries': [...], 'inconsistencies': [...]}`

Each entry has `checks.modal_consistent`, `checks.target_ref_consistent`, `checks.temporal_guard_consistent`.

### CNL Regeneration

#### `generate_cnl_from_ir(norm_ref, ir, lexicon_overrides=None)`

Deterministically regenerates CNL from a norm in `LegalIRV2`.

**Round-trip contract:**
- Strict mode output is deterministic for canonical templates
- Preserves all semantic IDs and scope (modality, temporal, activation, exceptions)
- Generated NL is suitable for proof explanation rendering

### Query APIs

#### `check_compliance(query, time_context)`

```python
query = {
    'ir': LegalIRV2,      # required
    'facts': dict,         # predicate -> bool (optional)
    'events': list[str],   # happened frame refs (optional)
}
result = check_compliance(query, time_context={})
```

**Returns:**
```python
{
    'api': 'check_compliance',
    'schema_version': '1.0',
    'status': 'compliant' | 'non_compliant',
    'violation_count': int,
    'violations': [{'norm_id', 'frame_id', 'type': 'omission'|'forbidden_action'}],
    'proof_id': str,
    'checked_norms': list[str],
    'time_context': dict,
}
```

#### `find_violations(state, time_range)`

```python
state = {'ir': LegalIRV2, 'facts': dict, 'events': list}
result = find_violations(state, ('2025-01-01', '2025-12-31'))
```

**Returns:** `{'api', 'schema_version', 'time_range', 'violation_count', 'violations', 'proof_id'}`

#### `explain_proof(proof_id, format='nl')`

Retrieves a stored proof by ID and renders it.

**Format `'nl'`:**
```python
{
    'api': 'explain_proof',
    'schema_version': '1.0',
    'proof_id': str,
    'format': 'nl',
    'root_conclusion': str,
    'text': str,   # natural language explanation
    'steps': list,
}
```

**Raises:** `KeyError` for unknown or evicted proof IDs.

### Optimizer and KG Hooks

#### `run_v2_pipeline(sentence, *, jurisdiction='default', optimizer_hook=None, kg_hook=None, prover_hook=None, drift_threshold=0.05, strict_contract=True)`

Full pipeline with optional hooks.

**Optimizer governance** (issue #1170):
- Optimizer output is rejected if `drift_score > drift_threshold`
- Optimizer output is rejected if `semantic_equivalence_assertion` is False
- Optimizer output is rejected if modality operators or target frame identity change
- Decision envelope always has: `accepted`, `drift_score`, `semantic_equivalence_assertion`, `rejection_reasons`, `decision_id`

**Returns:** `{'ir', 'contract_report', 'dcec', 'tdfol', 'optimizer_report', 'kg_report', 'prover_report'}`

#### `DefaultOptimizerHookV2`

Default optimizer adapter. Performs safe no-op canonical mutations (enforces `priority >= 0`). Backed by `build_optimizer_acceptance_decision`.

#### `DefaultKGHookV2`

Default KG enrichment adapter. Backed by `build_entity_link_adapter`, `build_relation_enrichment_adapter`, `apply_kg_enrichment`.

**KG enrichment invariants** (issue #1171):
- Does not mutate canonical IDs
- Does not change normative operator semantics
- Reports deterministic counters: `entity_link_count`, `relation_candidate_count`, `entity_write_count`, `relation_write_count`
- Fully reversible via `rollback_kg_enrichment(ir, rollback_plan)`

## Proof Schema

### ProofObject

```python
@dataclass
class ProofObject:
    proof_id: str
    query: dict
    root_conclusion: str
    steps: list[ProofStep]
    status: Literal['proved', 'refuted', 'inconclusive']
    schema_version: str = '1.0'
    proof_hash: str = ''
    created_at: Optional[str] = None
    certificates: list[ProofCertificate] = []
    certificate_trace_map: dict[str, list[IRReference]] = {}
```

### ProofStep

```python
@dataclass
class ProofStep:
    step_id: str
    rule_id: str
    premises: list[str]
    conclusion: str
    ir_refs: list[IRReference]    # required: non-empty
    provenance: list[SourceProvenance]  # required: non-empty
    timestamp: Optional[str] = None
    confidence: float = 1.0
```

**Contract:** All proof steps must have non-empty `ir_refs` and `provenance`. Violation raises `ValueError("invalid_proof_trace:missing_ir_refs:...")`.

### ProofCertificate

Per-backend certificate payloads:

| Backend | Required payload keys |
|---|---|
| `smt_style` / `mock_smt` | `backend`, `format`, `solver`, `theorem_hash_hint` |
| `first_order` / `mock_fol` | `backend`, `format`, `prover`, `assumption_count` |

The normalized envelope always includes `certificate_id`, `format`, `normalized_hash`, `payload`.

### Prover Envelope Schema

```python
{
    'schema_version': '1.0',
    'backend': str,
    'status': str,
    'theorem': str,
    'assumptions': list[str],
    'certificate': {
        'certificate_id': str,    # 'cert_' + hash[:12]
        'format': str,
        'normalized_hash': str,   # SHA-256 hex
        'payload': dict,
    },
}
```

## Error Codes

### CNL Parse Errors (`V2_CNL_PARSE_*`)
- `V2_CNL_PARSE_EMPTY_SENTENCE` — input is empty
- `V2_CNL_PARSE_UNSUPPORTED_MODAL` — no supported modal operator found
- `V2_CNL_PARSE_AMBIGUOUS_MARKERS` — conflicting or duplicate activation/exception markers

### IR Contract Errors (`V2_CONTRACT_*`)
- `V2_CONTRACT_UNSUPPORTED_IR_VERSION`
- `V2_CONTRACT_UNKNOWN_TARGET_FRAME_REF`
- `V2_CONTRACT_UNKNOWN_TEMPORAL_REF`
- `V2_CONTRACT_MISSING_SOURCE_REF`

### ID Registry Errors (`V2_IDREG_*`)
- `V2_IDREG_ENTITY_NAMESPACE_MISMATCH`
- `V2_IDREG_UNKNOWN_TARGET_FRAME_REF`
- `V2_IDREG_ORPHAN_FRAME_ID`

### V3 Schema Errors (`V3_SCHEMA_*`)
- `V3_SCHEMA_INVALID_NAMESPACE`
- `V3_SCHEMA_ID_KEY_MISMATCH`
- `V3_SCHEMA_UNKNOWN_TARGET_FRAME_REF`
- `V3_SCHEMA_ORPHAN_FRAME_ID`
- `V3_SCHEMA_ORPHAN_TEMPORAL_ID`
