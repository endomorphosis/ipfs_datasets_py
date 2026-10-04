# Comprehensive Logic Module Refactoring & Improvement Plan — 2026 v2.0

**Date:** 2026-02-22  
**Status:** 🟢 Active Plan — Synthesizes MASTER_REFACTORING_PLAN_2026 + NL_UCAN_POLICY_COMPILER_PLAN + EVERGREEN_IMPROVEMENT_PLAN  
**Scope:** `ipfs_datasets_py/logic/` (285 Python files, 95,051 LOC, 69 active docs)

---

## Executive Summary

The `logic/` module is production-ready at ~97% test coverage with 5,500+ passing tests
across TDFOL, CEC, integration, ZKP, FOL, deontic, common, and security layers.

This plan v2.0 focuses on **four strategic pillars** for the next improvement cycle:

1. **NL→UCAN Policy Compiler** (Phase 1 ✅ complete; Phase 2/3 planned)
2. **Grammar-Based NL Parsing** (upgrade from regex patterns to compositional semantics)
3. **ZKP→UCAN Bridge** (use ZKP proofs as cryptographic capability evidence in UCAN tokens)
4. **Import Hygiene & API Surface** (blessed API, shims, layering enforcement)

---

## Current State Snapshot (2026-02-22)

| Component | Tests | Coverage | Status |
|-----------|-------|----------|--------|
| TDFOL (Phases 1–12) | 1,526+ | ~97% | ✅ Production-ready |
| CEC Native (Phases 1–3) | 450+ | ~97% | ✅ Production-ready |
| CEC NL Parsers | 200+ | ~100% | ✅ All 4 parsers 100% |
| Integration Layer | 2,907+ | 99% | ✅ 55 uncovered = dead/symai |
| MCP Server B2 Tools | 1,457+ | — | ✅ 53 categories |
| ZKP Module | 35+ | ~85% | ⚠️ Simulation only |
| FOL Converter | ~40 | ~95% | ✅ Production-ready |
| Deontic Converter | ~40 | ~95% | ✅ Production-ready |
| **NL→UCAN Pipeline** | **64** | **new** | ✅ Phase 1 complete |

---

## Architecture Overview

```
Natural Language Text
        │
        ▼  [Stage 1: Pattern OR Grammar]
┌──────────────────────────────────────────────────┐
│  CEC NL Layer (logic/CEC/nl/)                    │
│  ┌─────────────────┐  ┌─────────────────────┐   │
│  │ PatternMatcher  │  │ DCECEnglishGrammar   │   │
│  │ (regex, 37 pat) │  │ (grammar-based) ✅  │   │
│  └─────────────────┘  └─────────────────────┘   │
│                                                   │
│  Grammar NL Compiler (grammar_nl_policy_compiler) │
│  Produces: DeonticFormula(OBLIGATION/PERMISSION/  │
│            PROHIBITION, Predicate, agent)          │
└───────────────────────┬──────────────────────────┘
                        │
                        ▼  [Stage 2: DCEC → Policy]
┌──────────────────────────────────────────────────┐
│  NLToDCECCompiler (logic/CEC/nl/nl_to_policy.py) │
│  DeonticFormula → PolicyClause → PolicyObject     │
└───────────────────────┬──────────────────────────┘
                        │
          ┌─────────────┴──────────────┐
          ▼                            ▼
   [Stage 3a: UCAN]           [Stage 3b: ZKP Evidence]
┌─────────────────────┐   ┌──────────────────────────┐
│ DCECToUCANBridge    │   │ ZKPToUCANBridge           │
│ DCEC → Capability/  │   │ logic/zkp/ucan_zkp_bridge │
│ DelegationToken     │   │ ZKP proof → UCAN caveats  │
└────────────┬────────┘   └────────────┬─────────────┘
             │                         │
             └───────────┬─────────────┘
                         ▼
              ┌─────────────────────┐
              │ NLUCANPolicyCompiler│
              │ Full pipeline coord │
              │ + DIDKeyManager     │
              │ + SecretsVault      │
              └─────────────────────┘
```

---

## Phase 2: Grammar-Based NL Parsing (Planned)

### Goal
Replace pure regex matching with compositional semantics using `DCECEnglishGrammar`.

### Deliverables

#### 2.1 `logic/CEC/nl/grammar_nl_policy_compiler.py` ✅ Created this session

```python
class GrammarNLPolicyCompiler:
    """Grammar-based (non-regex) NL → PolicyClause compiler."""
    def compile(self, text: str) -> GrammarCompilationResult
    def _parse_tree_to_clauses(self, tree) -> List[PolicyClause]
    def _resolve_agent(self, agent_node) -> str
    def _resolve_action(self, action_node) -> str
```

#### 2.2 Compositional Semantics Engine (Phase 2.2 — Future)

- Parse tree → lambda calculus terms
- Handle quantification: "every X must Y" → ∀x: O(Y(x))
- Handle conditionals: "if A then X may Y" → A → P(Y, X)
- Handle temporal: "X may Y until Z" → P(Y, X) U Z

#### 2.3 Multi-Language NL Policy Compilation (Phase 2.3 — Future)

- Extend `grammar_nl_policy_compiler.py` to French/German/Spanish
- Use language-specific grammars in `CEC/nl/domain_vocabularies/`

### Test Strategy
- 30+ tests in `test_grammar_nl_policy_compiler.py`
- Compare grammar vs pattern results for same inputs
- Test compositional sentences: "Bob must read and Alice may write"

---

## Phase 3: ZKP→UCAN Bridge

### Goal
Enable cryptographic capability evidence: a ZKP proof of theorem satisfaction
becomes a UCAN caveat proving the policy was verified without revealing inputs.

### Deliverables

#### 3.1 `logic/zkp/ucan_zkp_bridge.py` ✅ Created this session

```python
class ZKPCapabilityEvidence:
    """ZKP proof embedded as UCAN caveat."""
    proof_hash: str
    theorem_cid: str
    verifier_id: str

class ZKPToUCANBridge:
    """Convert ZKP proofs to UCAN DelegationTokens with evidence caveats."""
    def prove_and_delegate(self, theorem, actor, resource, ability) -> BridgeResult
    def verify_delegated_capability(self, token_dict) -> bool
    def proof_to_caveat(self, proof) -> Dict
```

#### 3.2 Integration with `NLUCANPolicyCompiler` (Phase 3.2 — Future)

- Add `zkp_mode=True` parameter to `NLUCANPolicyCompiler.compile()`
- When enabled: generate ZKP proof for each clause, embed as caveat
- Use `DIDKeyManager` to sign the resulting ZKP-backed UCAN tokens

#### 3.3 Real Groth16 ZKP Backend (Phase 3.3 — Long-term)

- Follow `zkp/PRODUCTION_UPGRADE_PATH.md` 
- Phase A: Rust FFI adapter for Groth16
- Phase B: Circom circuit for DCEC theorem satisfaction
- Phase C: Trusted setup ceremony
- Phase D: On-chain verifier (EVM/Filecoin)

---

## Phase 4: TDFOL Strategy Coverage

### Goal
Bring `strategies/modal_tableaux.py` from 74% → 95%+.

### Remaining Uncovered Paths (Session 40 analysis)

| Path | Reason Uncovered | Fix |
|------|-----------------|-----|
| `_prove_basic_modal` — formula in KB | Test with axiom in KB | Add test with formula as axiom |
| `_prove_basic_modal` — not in KB | Test without KB match | Add test with empty KB |
| `_select_modal_logic_type` — D logic | Deontic formula input | Test with `DeonticFormula` |
| `_select_modal_logic_type` — S4 | Nested temporal | Test with nested `TemporalFormula` |
| `_select_modal_logic_type` — K | Non-modal | Test with `AtomicFormula` |
| `estimate_cost` — nested temporal | Depth ≥ 2 | Nest `TemporalFormula` in `TemporalFormula` |
| `estimate_cost` — deontic + temporal | Both present | Combine `DeonticFormula` + `TemporalFormula` |
| `_has_nested_temporal` — depth ≥ 2 | Two layers | Temporal wrapping temporal |
| `_traverse_formula` — `DeonticFormula` child | Nested deontic | Wrap deontic in deontic |

### Deliverable
`tests/unit_tests/logic/TDFOL/strategies/test_modal_tableaux_session_v13.py` ✅ Created this session

---

## Phase 5: Import Hygiene & Blessed API Surface

### Goal
Establish a canonical `logic/api.py` with explicit `__all__`, import-quiet, no side effects.

### Current Issues
- Multiple overlapping entry points (`ConversionResult` defined in 3 places)
- Some modules import at module-level from optional deps
- No single blessed import path

### Deliverable: `logic/api.py` (Phase 5.1)

```python
# logic/api.py — Blessed, stable, import-quiet API surface
from .integration import UnifiedLogicEngine, LogicConverter
from .CEC.native.nl_converter import NaturalLanguageConverter, ConversionResult
from .CEC.nl.nl_to_policy_compiler import NLToDCECCompiler, compile_nl_to_policy
from .CEC.nl.dcec_to_ucan_bridge import DCECToUCANBridge
from .integration.nl_ucan_policy_compiler import NLUCANPolicyCompiler, compile_nl_to_ucan_policy
from .zkp.ucan_zkp_bridge import ZKPToUCANBridge
from .TDFOL.tdfol_prover import TDFOLProver
from .types import ProofResult, ProofStatus
```

---

## Phase 6: Security Layer Integration

### Goal
Wire `logic/security/` validators into the NL→UCAN pipeline for input sanitization.

### Items
- Validate NL text length and character set before parsing
- Rate-limit policy compilation (prevent regex DoS)
- Add input sanitization to `GrammarNLPolicyCompiler`

---

## Phase 7: TDFOL NL (spaCy) — Deferred

### Goal
Improve `TDFOL/nl/tdfol_nl_preprocessor.py` from 60% → 75%+ (requires spaCy).

### Blocker
spaCy is not in base CI environment. When added:
- Run ~65 deferred TDFOL NL tests
- Cover preprocessing lemmatization, NER, dependency parsing paths

---

## Test Coverage Targets (v2.0)

| Component | Current | Target (v2) | Session |
|-----------|---------|-------------|---------|
| `TDFOL/strategies/modal_tableaux.py` | 74% | 95% | v13 ✅ |
| `CEC/nl/grammar_nl_policy_compiler.py` | new | 90%+ | v13 ✅ |
| `zkp/ucan_zkp_bridge.py` | new | 90%+ | v13 ✅ |
| `TDFOL/nl/tdfol_nl_preprocessor.py` | 60% | 75% | deferred (spaCy) |
| `integration/` 55 uncovered | dead | n/a | intentionally excluded |
| Logic API surface | none | 95%+ | Phase 5 |

---

## Roadmap Timeline

```
Session v13 (2026-02-22):  ✅ grammar_nl_policy_compiler.py
                           ✅ zkp/ucan_zkp_bridge.py
                           ✅ modal_tableaux coverage tests
                           ✅ COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v2.md

Session v14 (planned):     logic/api.py blessed API surface
                           Integration tests: NL→ZKP→UCAN E2E
                           Security layer wiring

Session v15 (planned):     Multi-language grammar NL compiler
                           Compositional semantics engine
                           Quantified policy support

Session v16 (planned):     spaCy CI integration (TDFOL NL 60%→75%)
                           Performance regression gates

Session v17+ (long-term):  Real Groth16 Rust FFI
                           On-chain EVM verifier
                           Trusted setup ceremony automation
```

---

## Guardrails (Non-Negotiable)

1. **Import stability**: All existing `ipfs_datasets_py.logic.*` import paths preserved
2. **Import-quiet**: No network/threads/env mutation at import time
3. **Layering**: `common/types` → `CEC/TDFOL/fol/deontic` → `integration` → `api`
4. **Simulation warnings**: ZKP module always emits `UserWarning` at runtime
5. **Determinism**: All logic reasoning is deterministic under fixed seed
6. **Security**: No secrets in logic modules; use `mcp_server/secrets_vault.py` for keys

---

**Document Status:** Active — v2.0 created 2026-02-22  
**Supersedes:** `MASTER_REFACTORING_PLAN_2026.md` (still valid, this is an addendum)  
**Related Docs:** `NL_UCAN_POLICY_COMPILER_PLAN.md`, `EVERGREEN_IMPROVEMENT_PLAN.md`
