# Comprehensive Logic Refactoring Plan 2026 — v16
> Supersedes: `COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v15.md`  
> Date: 2026-02-23  
> Branch: `copilot/create-refactoring-plan-again`

---

## 1. Purpose

This document captures the complete refactoring status for the
`ipfs_datasets_py/logic/` subsystem including all v24 session changes.

---

## 2. v24 Session Changes

### `ipfs_datasets_py/mcp_server/ucan_delegation.py`

#### active_tokens_by_resource (EI197)
- `active_tokens_by_resource(resource)` generator; yields `(cid, token)` from
  `active_tokens()` where any capability matches resource (exact or wildcard)

#### active_token_count caching (EO203)
- Multiple `revoke()` calls each invalidate `_metrics_cache`
- `active_token_count == len(list(active_tokens()))` invariant confirmed

### `ipfs_datasets_py/logic/integration/nl_ucan_policy_compiler.py`

#### compile_batch_with_explain (EJ198)
- `compile_batch_with_explain(sentences_list, policy_ids) -> List[Tuple[result,str]]`
- Pairs each result with `result.explain()` string

#### compile_batch fail_fast (EN202)
- `compile_batch(*, fail_fast=False)`: stops after first result with errors
- Default `False` preserves previous all-compile behaviour

### `ipfs_datasets_py/mcp_server/compliance_checker.py`

#### ComplianceMergeResult.total (EK199)
- `total` `@property` = `added + skipped_protected + skipped_duplicate`

### `ipfs_datasets_py/logic/api.py`

#### conflict_density (EL200)
- `I18NConflictReport.conflict_density()` = `total_conflicts / len(by_language)`
- `0.0` for empty report

#### detect_all_languages 9th language (EM201)
- `_SUPPORTED_LANGS` → `("fr","es","de","en","pt","nl","it","ja","zh")`

### `ipfs_datasets_py/logic/CEC/nl/nl_policy_conflict_detector.py`

#### Chinese keywords (EM201)
- `_ZH_DEONTIC_KEYWORDS` — 3 types, inline, always available
- `_load_i18n_keywords("zh")` returns `_ZH_DEONTIC_KEYWORDS`

---

## 3. All-Phase Status Table

| Phase | Component | Status | Version |
|-------|-----------|--------|---------|
| 1 | FOL/DCEC base types | ✅ Complete | v13 |
| 2a | DID key management | ✅ Complete | v13 |
| 2b | DID signing (sign_delegation_token) | ✅ Complete | v15 |
| 3a | NL policy compiler | ✅ Complete | v13 |
| 3b | Grammar NL Stage 1b fallback | ✅ Complete | v15 |
| 4 | UCAN policy bridge | ✅ Complete | v14 |
| 5 | logic/api.py exports | ✅ Complete | v15→v24 |
| 6 | Evaluator caches | ✅ Complete | v15 |
| 7 | Security validator atomic + vault | ✅ Complete | v15 |
| 8 | Policy audit log | ✅ Complete | v15 |
| ZKP | ZKP bridge + Groth16 Rust FFI | ✅ Complete | v16 |
| CONFLICT | NL conflict detection + i18n (9 langs) | ✅ Complete | v15→v24 |
| DELEGATION | DelegationManager + async merge + metrics + active_tokens + by_resource | ✅ Complete | v15→v24 |
| COMPLIANCE | ComplianceChecker + ComplianceMergeResult + total | ✅ Complete | v14→v24 |
| PIPELINE | DispatchPipeline + stages | ✅ Complete | v14→v16 |
| PORTUGUESE | PortugueseParser + sentence splitting + get_clauses_by_type | ✅ Complete | v21→v23 |
| ITALIAN | _IT_DEONTIC_KEYWORDS | ✅ Complete | v22 |
| JAPANESE | _JA_DEONTIC_KEYWORDS | ✅ Complete | v23 |
| CHINESE | _ZH_DEONTIC_KEYWORDS | ✅ Complete | v24 |
| BATCH | compile_batch() + fail_fast + with_explain | ✅ Complete | v23→v24 |
| DENSITY | conflict_density() | ✅ Complete | v24 |

---

## 4. API Quick Reference (v24 additions)

```python
# EI197 – filter active tokens by resource
for cid, tok in mgr.active_tokens_by_resource("tools/invoke"):
    ...

# EJ198 – batch compile with explanation strings
pairs = compiler.compile_batch_with_explain([sentences_a, sentences_b])
result, explain_str = pairs[0]

# EK199 – total items processed by merge()
r = checker.merge(other)
print(r.total)  # added + skipped_protected + skipped_duplicate

# EL200 – conflict density
report = detect_all_languages(text)
print(report.conflict_density())  # float: conflicts / num_languages

# EM201 – Chinese keywords available
from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import _ZH_DEONTIC_KEYWORDS
# detect_all_languages() now includes "zh" slot

# EN202 – fail-fast batch compile
results = compiler.compile_batch([batch_a, batch_b], fail_fast=True)
```

---

## 5. Evergreen Backlog (v25 candidates)

| Session | Target | Effort | Priority |
|---------|--------|--------|----------|
| ES207 | `active_tokens_by_resource("*")` edge case tests | Low | 🟢 Low |
| ET208 | `compile_batch_with_explain` + `fail_fast=True` combined | Low | 🟢 Low |
| EU209 | `ComplianceMergeResult.to_dict()` | Low | 🟢 Low |
| EV210 | `I18NConflictReport.least_conflicted_language()` | Low | 🟢 Low |
| EW211 | `_ZH_DEONTIC_KEYWORDS` obligation coverage tests | Low | 🟢 Low |
| EX212 | `compile_batch` `policy_ids` shorter than batches auto-ID | Low | 🟡 Med |
| EY213 | `active_tokens_by_resource` + revocation combined | Low | 🟢 Low |
| EZ214 | Chinese text → `by_language["zh"]` non-empty E2E | Med | 🔴 High |
| FA215 | `conflict_density()` with all 9 languages populated | Low | 🟡 Med |
| FB216 | `compile_batch_with_explain` `fail_fast=True` variant | Low | 🟡 Med |

---

## 6. Success Criteria (v16)

| Criterion | Target | Status |
|-----------|--------|--------|
| Tests (total) | 3,000+ | ✅ 3,457 |
| Test pass rate | 100% | ✅ 0 failing (1 pre-existing v16 unrelated) |
| NL→UCAN phases | All 8 | ✅ Complete |
| DID signing | Real Ed25519 | ✅ v15 Phase 2b |
| Grammar NL | Stage 1b fallback | ✅ v15 Phase 3b |
| Conflict detection | 9 languages | ✅ v24 (fr/es/de/en/pt/nl/it/ja/zh) |
| Delegation merge | sync + async + event_type | ✅ CQ153/CY161/DK173/DQ179 |
| Compliance merge | ComplianceMergeResult + total | ✅ DA163/DH170/DS181/EC191/EK199 |
| Audit JSONL I/O | round-trip with metadata, clear() | ✅ CS155/CZ162/DG169/DR180/EB190/ER206 |
| Compiler explain | eager + lazy + batch + with_explain | ✅ CW159/DB164/DI171/DT182/DZ188/EJ198 |
| Portuguese parser | sentence-level multi-clause + filter | ✅ DJ172/DP178/DY187 |
| Italian keywords | _IT_DEONTIC_KEYWORDS | ✅ DO177 |
| Japanese keywords | _JA_DEONTIC_KEYWORDS | ✅ ED192 |
| Chinese keywords | _ZH_DEONTIC_KEYWORDS | ✅ EM201 |
| Active token count | property + generator + by_resource | ✅ DV184/EA189/EF194/EI197 |
| Conflict report | most_conflicted_language() + conflict_density() | ✅ EG195/EL200 |
| Groth16 wired | Rust binary + UCAN bridge | ✅ v16 |
