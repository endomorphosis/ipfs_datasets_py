# Comprehensive Logic Module Refactoring & Improvement Plan — 2026 v4.0

**Date:** 2026-02-22  
**Status:** 🟢 Active Plan — Supersedes `COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v3.md`  
**Scope:** `ipfs_datasets_py/logic/` + `mcp_server/`  
**Reference:** See `ARCHITECTURE_UCAN_PIPELINE.md` for full ASCII diagrams.

---

## Executive Summary

All 8 phases of the NL→Policy→UCAN improvement cycle are now **complete** (v15 session).

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Core NL→UCAN pipeline | ✅ Complete (v13) |
| 2 | DID-Signed UCAN Tokens (2b) | ✅ Complete (v15) |
| 3 | Grammar-Based NL Parsing (3b) | ✅ Complete (v15) |
| 4 | ZKP→UCAN Bridge | ⚠️ Simulation only (v13, Groth16 future) |
| 5 | Import Hygiene & Blessed API | ✅ Complete (v15) |
| 6 | Performance & Caching | ✅ Complete (v15) |
| 7 | Security Hardening | ✅ Complete (v15) |
| 8 | Observability & CI Integration | ✅ Complete (v15) |

---

## 1. What Was Built (v15 Session)

### Phase 2b — DID-Signed UCAN Tokens

**`mcp_server/did_key_manager.py`** additions:
- `sign_delegation_token(token, audience_did, lifetime_seconds)` → signed UCAN JWT (real with py-ucan, `"stub:…"` base64 without)
- `verify_signed_token(signed_token, required_capabilities)` → bool

**`logic/integration/ucan_policy_bridge.py`** additions:
- `SignedPolicyResult` dataclass (compile_result / signed_jwts / signing_available / jwt_count)
- `UCANPolicyBridge.compile_and_sign(nl_text, audience_did, lifetime_seconds)` → `SignedPolicyResult`

### Phase 3b — Grammar NL Fallback

**`logic/CEC/nl/nl_to_policy_compiler.py`** — `compile_sentence()` now runs:
1. Stage 1: `NaturalLanguageConverter` (37+ regex patterns) — primary path
2. Stage 1b: `GrammarNLPolicyCompiler` (grammar + keyword heuristic) — fallback when Stage 1 yields nothing
Result: improved NL accuracy for sentences the regex patterns miss.

### Phase 5 — Import Hygiene & Blessed API

**`logic/api.py`**:
- `from typing import Any, Optional` added
- `_lazy_nl_ucan()` — lazy loader for NL-UCAN namespace (no hard dependency)
- `compile_nl_to_policy`, `evaluate_nl_policy`, `build_signed_delegation` — public functions
- `NLToDCECCompiler`, `DCECToUCANBridge`, `GrammarNLPolicyCompiler`, `NLUCANPolicyCompiler`, `UCANPolicyBridge`, `SignedPolicyResult`, `BridgeCompileResult`, `BridgeEvaluationResult` — added to `__all__`
- Import-quiet: no `DeprecationWarning` emitted on `import ipfs_datasets_py.logic.api`

### Phase 6 — Performance & Caching

**`mcp_server/temporal_policy.py`** — `PolicyEvaluator`:
- `_decision_cache: Dict[Tuple, DecisionObject]` — memoize `(policy_cid, intent_cid, actor)` → `DecisionObject`
- Cache invalidated on new policy registration (different `policy_cid` only)
- `clear_cache() → int` — explicit invalidation
- `evaluate()` new params: `use_cache=True` (default), `at_time=None` (explicit at_time bypasses cache)

**`mcp_server/ucan_delegation.py`** — `DelegationEvaluator`:
- `_chain_cache: Dict[str, DelegationChain]` — memoize `leaf_cid → DelegationChain`
- Cache invalidated when a new (previously unseen) token is added
- `build_chain(leaf_cid, use_cache=True)` — new `use_cache` parameter

### Phase 7 — Security Hardening

**`mcp_server/ucan_delegation.py`** — `RevocationList`:
- `save(path)` — persist to JSON (0o600) or encrypted via `SecretsVault` (path ends with `.enc`)
- `load(path) → int` — restore and merge

**`logic/TDFOL/security_validator.py`** — two bugs fixed:
1. **TOCTOU race** in concurrent limit: replaced `_check_concurrent_limit()` + separate increment with atomic `_acquire_concurrent_slot()` + GIL yield (`time.sleep(0)`)
2. **Proof hash** bug: `_check_proof_integrity()` now hashes only non-`metadata` fields, matching what external signers produce. The old code used a shallow copy that mutated the original dict.

### Phase 8 — Observability

**`mcp_server/policy_audit_log.py`** (new):
- `AuditEntry` dataclass — timestamp, policy_cid, intent_cid, decision, actor, tool, justification, obligations, extra
- `PolicyAuditLog` — thread-safe ring buffer (default 10,000 entries), optional JSONL file sink, optional custom callable sink
- `record()` / `record_decision()` / `recent()` / `all_entries()` / `decision_counts()` / `total_recorded()` / `clear()` / `stats()`
- `get_audit_log()` — process-global singleton

### Architecture Documentation

**`logic/ARCHITECTURE_UCAN_PIPELINE.md`** (new):
Full ASCII-art diagrams covering:
1. Full NL→Policy→UCAN pipeline (Stages 1, 1b, 2, 3a/3b/3c/3d, 4)
2. DID-signing track (stub vs real Ed25519)
3. ZKP evidence track (simulation mode; future Groth16)
4. Temporal policy evaluation with memoization
5. Delegation chain + revocation with caching
6. Policy audit log flow
7. Module map (logic/ + mcp_server/)

---

## 2. Session Log

| Session | Date | New Modules | New Tests | Phases |
|---------|------|------------|-----------|--------|
| v13 NL pipeline | 2026-02-22 | `nl_to_policy_compiler.py`, `dcec_to_ucan_bridge.py`, `nl_ucan_policy_compiler.py`, MCP tool | 64 | 1 ✅ |
| v13 Logic refactoring | 2026-02-22 | `grammar_nl_policy_compiler.py`, `zkp/ucan_zkp_bridge.py`, plan v2 | 60 | 3/4 partial |
| v13 DID/UCAN | 2026-02-22 | `did_key_manager.py`, `secrets_vault.py`, dep additions | 43 | 2 partial |
| v14 Logic+UCAN | 2026-02-22 | `ucan_policy_bridge.py`, `RevocationList`, `DelegationStore`, plan v3 | 59 | 2/8 |
| **v15 Phases 2b–8** | **2026-02-22** | `policy_audit_log.py`, `ARCHITECTURE_UCAN_PIPELINE.md`, plan v4 | **63** | **2b/3b/5/6/7/8 ✅** |

**Grand total: 2,678 tests** (2,615 + 63) · 0 failing

---

## 3. Remaining Work

### Phase 4b — Real Groth16 ZKP (Deferred)

Requires Rust FFI backend. Will be implemented when:
- `IPFS_DATASETS_ENABLE_GROTH16=1` environment variable
- `bellman` or `arkworks` crate available via PyO3 bindings
- `ZKPCapabilityEvidence.is_simulation` will be set to `False`
- No `UserWarning` emitted

### Continuous Improvement

- Increase NL accuracy beyond ~75% (spaCy NER planned for Phase 9)
- Spanish/Portuguese language NL policy support
- Prometheus metrics endpoint (`/metrics`) for `PolicyAuditLog`
- Wire performance baselines into GitHub Actions CI
- Real conflict detection between permission/prohibition clauses

---

## 4. Success Criteria (Updated)

| Metric | Before v15 | After v15 | Target |
|--------|-----------|-----------|--------|
| DelegationToken signing | ❌ stub | ✅ stub + real JWT | ✅ |
| PolicyEvaluator cache | ❌ none | ✅ memoized | ✅ |
| DelegationEvaluator cache | ❌ none | ✅ chain cache | ✅ |
| security_validator TOCTOU | ❌ race | ✅ atomic | ✅ |
| security_validator proof hash | ❌ bug | ✅ fixed | ✅ |
| RevocationList persistence | ❌ none | ✅ JSON + vault | ✅ |
| Policy audit trail | ❌ none | ✅ JSONL + sink | ✅ |
| logic/api.py NL-UCAN symbols | ❌ missing | ✅ in __all__ | ✅ |
| Grammar NL fallback (Stage 1b) | ❌ none | ✅ integrated | ✅ |
| ZKP → real Groth16 | ❌ sim | ❌ deferred | Phase 4b |
| spaCy NER | ❌ none | ❌ deferred | Phase 9 |

---

*This document supersedes `COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v3.md` (archived).*  
*Architecture diagrams: `ARCHITECTURE_UCAN_PIPELINE.md`*
