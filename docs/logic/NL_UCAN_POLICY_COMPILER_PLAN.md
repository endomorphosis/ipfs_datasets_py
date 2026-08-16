# NL → DCEC → UCAN Policy Compiler — Comprehensive Plan

**Date:** 2026-02-22  
**Version:** 1.0  
**Status:** Phase 1 ✅ COMPLETE · Phase 2 🔄 Planned · Phase 3 🔄 Planned  
**Scope:** `ipfs_datasets_py/logic/` + `ipfs_datasets_py/mcp_server/`

---

## Executive Summary

This document describes the **Natural Language → Deontic Policy → UCAN Delegation** compiler system, which allows rigorous access-control policies to be specified in plain English and automatically compiled into:

1. **DCEC formulas** (Deontic Cognitive Event Calculus) — the formal semantic representation
2. **PolicyObject/PolicyClause** (MCP server temporal policy system) — evaluated at runtime
3. **UCAN DelegationToken** (Profile C from MCP++ spec) — cryptographic delegation chain

The system bridges the existing production-ready logic module (93k+ LOC, 5,500+ tests) with the new MCP++ spec alignment work.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                   NL Input (plain English)                       │
│  "Alice must not delete records"                                  │
│  "Bob is permitted to read files"                                 │
│  "Carol is required to audit all access events"                   │
└──────────────────────────┬──────────────────────────────────────┘
                           │ Stage 1: NL → DCEC
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│        CEC NL Parser  (logic/CEC/native/nl_converter.py)         │
│                                                                   │
│  PatternMatcher (37+ regex patterns) + DCECEnglishGrammar        │
│  Produces: DeonticFormula(PROHIBITION, delete(alice:Agent))       │
│            DeonticFormula(PERMISSION, read(bob:Agent))            │
│            DeonticFormula(OBLIGATION, audit(carol:Agent))         │
└──────────────────────────┬──────────────────────────────────────┘
                           │ Stage 2: DCEC → PolicyClause
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│   NLToDCECCompiler  (logic/CEC/nl/nl_to_policy_compiler.py)     │
│                                                                   │
│  PROHIBITION → clause_type="prohibition", actor, action          │
│  OBLIGATION  → clause_type="obligation",  actor, action          │
│  PERMISSION  → clause_type="permission",  actor, action          │
│                                                                   │
│  Result: PolicyObject(clauses=[...]) with policy_cid             │
└──────────────────────────┬──────────────────────────────────────┘
                           │ Stage 3: DCEC → UCAN tokens
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  DCECToUCANBridge  (logic/CEC/nl/dcec_to_ucan_bridge.py)       │
│                                                                   │
│  OBLIGATION  → DelegationToken(issuer, audience, [Capability])   │
│  PERMISSION  → DelegationToken(issuer, audience, [Capability])   │
│  PROHIBITION → DenyCapability marker (no delegation issued)      │
│                                                                   │
│  Capabilities: resource="logic/<action>", ability="<action>/invoke"│
└──────────────────────────┬──────────────────────────────────────┘
                           │ Stage 4: Evaluation
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  NLUCANPolicyCompiler (logic/integration/nl_ucan_policy_compiler)│
│                                                                   │
│  PolicyEvaluator: evaluate(IntentObject, policy_cid, actor)      │
│  DelegationEvaluator: can_invoke(did, resource, ability, leaf)   │
│                                                                   │
│  MCP Tool: nl_ucan_policy_tool.py                                │
│    - nl_compile_policy()   → policy_id + clauses + tokens        │
│    - nl_evaluate_policy()  → allow/deny decision                  │
│    - nl_inspect_policy()   → full policy details                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Phase 1: Core Pipeline ✅ COMPLETE (2026-02-22)

### New Production Modules

| Module | Purpose | Tests |
|--------|---------|-------|
| `logic/CEC/nl/nl_to_policy_compiler.py` | NL → DCEC → PolicyClause/PolicyObject | Phase A tests |
| `logic/CEC/nl/dcec_to_ucan_bridge.py` | DCEC formulas → UCAN Capability/DelegationToken | Phase B tests |
| `logic/integration/nl_ucan_policy_compiler.py` | Full 3-stage pipeline coordinator | Phase C tests |
| `mcp_server/tools/logic_tools/nl_ucan_policy_tool.py` | MCP server tools (compile/evaluate/inspect) | Phase D tests |
| `tests/unit_tests/logic/test_nl_ucan_policy_compiler.py` | 64 tests, all passing | ✅ |

### Semantic Mapping

| DCEC Operator | PolicyClause type | UCAN outcome | Evaluator behavior |
|--------------|------------------|--------------|-------------------|
| `OBLIGATION` | `"obligation"` | `DelegationToken` (ability: `<action>/execute`) | ALLOW_WITH_OBLIGATIONS if permission also present |
| `OBLIGATORY` | `"obligation"` | `DelegationToken` (ability: `<action>/execute`) | same |
| `PERMISSION` | `"permission"` | `DelegationToken` (ability: `<action>/invoke`) | ALLOW |
| `PROHIBITION` | `"prohibition"` | `DenyCapability` (no delegation) | DENY |
| `RIGHT/LIBERTY/POWER/IMMUNITY/SUPEREROGATION` | `"permission"` | `DelegationToken` | ALLOW |

### Deontic Operator Coverage in NL Patterns

Current `PatternMatcher` in `nl_converter.py` maps:
- "must", "is obligated to", "is required to" → `OBLIGATION`
- "may", "is permitted to", "is allowed to", "can" → `PERMISSION`
- "must not", "is forbidden from", "is prohibited from" → `PROHIBITION`
- "believes", "thinks" → `COGNITIVE (Belief)`
- "knows" → `COGNITIVE (Knowledge)`

---

## Phase 2: Feature Completeness Improvements 🔄 Planned

### 2.1 NL Parser Accuracy

**Current coverage (pattern-matching only):**
- Simple single-clause sentences: ~80%
- Negation phrases ("must not"): ~90%
- Temporal clauses ("until", "after", "when"): ~40%
- Compound conditions ("if X then Y must Z"): ~10%

**Planned improvements:**

#### 2.1.1 Temporal Clause Extraction
```python
# target input:
"Alice must not access the database after 6pm"

"Bob may read files until 2027-01-01"
# current output: valid_until ignored
# target output:  PolicyClause(valid_until=datetime_to_timestamp("6pm"))
```

**Implementation:** Extend `_dcec_formula_to_clause()` to extract temporal windows
from `TemporalFormula` wrappers. Requires extending NL patterns in `nl_converter.py`
to produce `TemporalFormula(operator=AFTER/UNTIL, ...)`.

#### 2.1.2 Conditional Policy Clauses
```python
# target input:
"If the user is an admin then they may delete records"
# target output:
#   PolicyClause(clause_type="permission", condition="is_admin", action="delete")
```

**Implementation:** Add `condition` field parsing to `PatternMatcher` using IF/THEN
regex patterns. Map `condition` to `PolicyClause.condition`.

#### 2.1.3 Resource Scoping
```python
# target input:
"Alice may read only the public database"
# target output:
#   PolicyClause(clause_type="permission", actor="alice", action="read",
#               resource="public_database")
```

**Implementation:** Parse object noun phrases after the action verb as `resource`.

#### 2.1.4 Multi-Agent Policies
```python
# target input:
"Only administrators and auditors may delete records"
# target output:
#   [PolicyClause(actor="administrator", ...), PolicyClause(actor="auditor", ...)]
```

**Implementation:** Detect "and"/"or" conjunctions in agent phrase; expand into
multiple clauses.

### 2.2 UCAN Delegation Improvements

#### 2.2.1 Full UCAN Chain Construction
Currently `DelegationEvaluator` stores flat tokens. Planned: chain construction
following `proof_cid` links (already partially implemented in `ucan_delegation.py`).

#### 2.2.2 Resource Wildcards
Map NL "all resources" → `Capability(resource="*", ability="*")`.

#### 2.2.3 Scoped Delegation from Policy Hierarchy
If NL says "managers may delegate read access to employees", produce a
delegating token where `issuer="did:key:manager"` and the token includes
delegation rights.

### 2.3 TDFOL (Temporal Deontic First-Order Logic) Integration

The existing TDFOL system provides richer temporal reasoning. Planned bridge:

```
NL text
  │
  ▼ TDFOL NL Parser (to be built, uses TDFOL inference rules)
TDFOL DeonticFormula (with quantifiers: ∀x ∈ Admins: O(audit(x)))
  │
  ▼ TDFOLToUCANBridge (Phase 3)
Parameterized PolicyObject (expanded per actor set)
```

**Key requirement:** TDFOL formulas can be universally quantified — "all users
must notify admin". This requires expanding quantified formulas into individual
per-actor PolicyClauses or wildcard clauses.

---

## Phase 3: Advanced Features 🔄 Planned

### 3.1 Grammar-Based NL Parsing (spaCy integration)

Current `PatternMatcher` uses regex. The `DCECEnglishGrammar` module provides
grammar-based parsing when `spacy` is installed. Phase 3 will connect the
grammar parser output to the policy compiler pipeline.

**Target accuracy:** 90%+ on the NL policy benchmark suite.

### 3.2 Multi-Language Support

The `CEC/nl/` package already has stubs for French, German, Spanish parsers.
Extend `NLToDCECCompiler` to accept a `language` parameter and route through
the appropriate parser.

### 3.3 ZKP (Zero-Knowledge Proof) Integration

For high-assurance policies, integrate with `logic/zkp/` to produce
ZKP circuits that prove policy compliance without revealing the policy itself.

**Use case:** "Prove you are authorized without revealing the policy."

### 3.4 Policy Conflict Detection

Use the TDFOL theorem prover to detect logical conflicts:
```python
# Detect: "Alice must delete AND Alice must not delete"
# → ConflictError with proof trace
```

**Implementation:** Feed PolicyClauses back into TDFOL KB; run `prove_contradiction()`.

### 3.5 Policy Versioning and Audit Trail

Extend `PolicyRegistry` to maintain version history and audit trail using
CID-linked EventNode chain (Profile B, `cid_artifacts.py`).

---

## Phase 4: Integration with Existing Logic Subsystems 🔄 Planned

### 4.1 CEC Inference Rules

The 67 CEC inference rules in `CEC/native/inference_rules/` can derive implied
obligations. Example: if "Alice must audit" and "audit implies notify", then
infer "Alice must notify". Connect to the policy compiler via:

```python
result = compiler.compile_with_inference(sentences, kb=existing_knowledge_base)
```

### 4.2 TDFOL Proof Verification

After compiling, use TDFOL to formally verify that the policy does not contain
contradictions or vacuously true/false clauses.

### 4.3 ZKP Policy Attestation

Produce a ZKP circuit from a compiled policy so a party can attest compliance
without revealing the policy content. Integration point:
`logic/zkp/circuits.py` → `DCECPolicyCircuit`.

---

## Known Limitations and Gaps (Current State)

### NL Parser Limitations
1. **No temporal window extraction** — "until 2027" in NL is not captured
2. **No resource extraction** — "read files in /public" loses "/public"  
3. **No compound conditions** — "if admin then may delete" not parsed
4. **No multi-agent expansion** — "admins and auditors may..." → single clause
5. **Single sentence at a time** — no discourse tracking across sentences
6. **English only** — French/German/Spanish stubs not connected to pipeline

### UCAN Delegation Gaps
1. **No chain verification** — `DelegationChain.is_valid()` does not check
   cryptographic signatures (stub only, as documented)
2. **No UCAN library dependency** — uses CID-based stubs, not production UCAN
3. **No revocation checking** — revoked tokens not detected
4. **No attenuation validation** — audience cannot exceed issuer's capabilities

### Policy Evaluator Gaps
1. **Closed-world assumption** — any action not explicitly permitted is denied.
   Obligation-only policies deny without explicit permission clause.
2. **No actor hierarchy** — "admin" does not implicitly include "super-admin"
3. **No temporal evaluation** — `valid_from/valid_until` enforced but NL does not populate them

---

## Improvement Roadmap

| Phase | Priority | Description | Complexity |
|-------|----------|-------------|------------|
| 2.1.1 | P0 | Temporal window extraction in NL→PolicyClause | Medium |
| 2.1.2 | P1 | Conditional IF/THEN policy parsing | High |
| 2.1.3 | P1 | Resource scoping from NL | Medium |
| 2.1.4 | P1 | Multi-agent expansion | Low |
| 2.2.1 | P1 | UCAN proof chain validation | High |
| 2.2.3 | P2 | Scoped delegation from hierarchy NL | High |
| 2.3 | P2 | TDFOL→UCAN bridge (quantified policies) | Very High |
| 3.1 | P1 | spaCy grammar parser integration | High |
| 3.2 | P2 | Multi-language policy compilation | Medium |
| 3.4 | P2 | Policy conflict detection via TDFOL | High |
| 3.5 | P3 | Policy versioning with CID audit trail | Low |
| 4.1 | P3 | CEC inference rule integration | High |
| 4.3 | P3 | ZKP policy attestation | Very High |

---

## Files Created in Phase 1

```
ipfs_datasets_py/logic/CEC/nl/
├── nl_to_policy_compiler.py         # NEW: Stage 1+2 bridge
├── dcec_to_ucan_bridge.py           # NEW: Stage 3 bridge
└── (existing: base_parser.py, language_detector.py, ...)

ipfs_datasets_py/logic/integration/
└── nl_ucan_policy_compiler.py       # NEW: Full pipeline orchestrator

ipfs_datasets_py/mcp_server/tools/logic_tools/
└── nl_ucan_policy_tool.py           # NEW: 3 MCP tools

tests/unit_tests/logic/
└── test_nl_ucan_policy_compiler.py  # NEW: 64 tests
```

---

## Test Coverage Summary (Phase 1)

| Component | Tests | Pass Rate |
|-----------|-------|-----------|
| `NLToDCECCompiler` basic construction/compile | 14 | 100% |
| `_extract_actor`, `_extract_action`, `_dcec_formula_to_clause` | 6 | 100% |
| `DCECToUCANBridge` all formula types | 12 | 100% |
| `NLUCANPolicyCompiler` E2E compile | 13 | 100% |
| MCP tools (compile/evaluate/inspect) | 11 | 100% |
| Policy evaluation correctness | 8 | 100% |
| **TOTAL** | **64** | **100%** |

---

## References

- `logic/MASTER_REFACTORING_PLAN_2026.md` — overall logic module plan
- `logic/CEC/EXTENDED_NL_SUPPORT_ROADMAP.md` — NL parser improvement plan
- `logic/CEC/native/nl_converter.py` — existing NL→DCEC converter
- `mcp_server/temporal_policy.py` — PolicyEvaluator/PolicyObject (Profile D)
- `mcp_server/ucan_delegation.py` — DelegationToken/DelegationEvaluator (Profile C)
- `mcp_server/cid_artifacts.py` — IntentObject/DecisionObject (Profile B)
- `mcp_server/interface_descriptor.py` — compute_cid/_canonicalize (Profile A)
- `mcp_server/ADR-006-mcp++-alignment.md` — MCP++ profile alignment decisions
- `https://github.com/endomorphosis/Mcp-Plus-Plus/blob/main/docs/index.md` — MCP++ spec
