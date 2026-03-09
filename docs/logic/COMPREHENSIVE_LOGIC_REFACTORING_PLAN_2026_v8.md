# Comprehensive Logic Refactoring Plan 2026 — v8

**Date:** 2026-02-22  
**Supersedes:** `COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v7.md`  
**Status:** All 8 phases complete through v16 · v17 candidates listed

---

## 1. Current State (v16 snapshot)

### Test Counts

| Session | New Tests | Total |
|---------|-----------|-------|
| v13 (logic) | 60 + 77 | 2,805 |
| v14 (logic) | 59 + 35 | 2,884 |
| v15 (logic) | 63 + 69 | 2,953 |
| **v16 (this session)** | **63** | **3,016** |

### Phase Status

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | NL→UCAN Pipeline | ✅ Complete |
| 2 | DID-signed UCAN tokens | ✅ Complete (2b done) |
| 3 | Grammar-based NL parsing | ✅ Complete (3b done) |
| 4 | ZKP→UCAN bridge | ✅ Simulation + Groth16 backend wired |
| 5 | Import hygiene & blessed API | ✅ Complete (BW133 done) |
| 6 | Performance & caching | ✅ Complete (v14 caches) |
| 7 | Security hardening | ✅ Complete (v15 atomic slot) |
| 8 | Observability & CI | ✅ Audit log, metrics bridge, audit-on-invoke |

---

## 2. Module Map (v8)

```
ipfs_datasets_py/
├── logic/
│   ├── api.py                          ← Phase 5 ✅ + BW133 (DelegationManager + ConflictDetector)
│   ├── ARCHITECTURE_UCAN_PIPELINE.md   ← Phase 8 diagrams ✅
│   ├── CEC/nl/
│   │   ├── nl_to_policy_compiler.py    ← Phase 1 ✅
│   │   ├── dcec_to_ucan_bridge.py      ← Phase 1 ✅
│   │   ├── grammar_nl_policy_compiler.py ← Phase 3b ✅
│   │   ├── language_detector.py        ← BC113 ✅
│   │   ├── french_parser.py            ← BC113 ✅
│   │   ├── spanish_parser.py           ← BC113 ✅
│   │   ├── german_parser.py            ← BC113 ✅
│   │   └── nl_policy_conflict_detector.py ← BL122 ✅ + BO125 wired to bridge
│   ├── integration/
│   │   ├── nl_ucan_policy_compiler.py  ← Phase 1 ✅
│   │   └── ucan_policy_bridge.py       ← Phase 1 ✅ + BO125 conflicts field
│   └── zkp/
│       ├── ucan_zkp_bridge.py          ← Phase 4 ✅ + Groth16 auto-select
│       └── GROTH16_INTEGRATION_PLAN_2026.md ← v16 reference
│
└── mcp_server/
    ├── ucan_delegation.py              ← Profile C + DelegationManager ✅
    │                                     BN124: revoke_chain() handles empty chain
    │                                     BR128: can_invoke_audited() added
    ├── dispatch_pipeline.py            ← Profile E ✅ + BS129: make_delegation_stage()
    ├── audit_metrics_bridge.py         ← BG117 ✅ + BP126 smoke test
    ├── policy_audit_log.py             ← Phase 8 ✅
    ├── compliance_checker.py           ← AV106 ✅
    ├── risk_scorer.py                  ← AW107 ✅
    ├── mcp_p2p_transport.py            ← AU105 ✅ (canonical transport)
    ├── grpc_transport.py               ← Optional secondary (docstring clarified)
    ├── did_key_manager.py              ← Phase 2a/2b ✅
    ├── secrets_vault.py                ← Phase 7 ✅
    └── temporal_policy.py              ← Profile D ✅
```

---

## 3. Key Invariants (v8 additions)

### DelegationManager.revoke_chain() (BN124 fix)
- Returns ≥ 1 always
- Empty chain (unknown CID) → revoke root_cid, return 1
- Exception path → revoke root_cid, return 1

### DelegationManager.can_invoke_audited() (BR128)
- Keyword-only: `audit_log=None`, `policy_cid="delegation"`, `intent_cid="intent"`
- If `audit_log is None` → identical to `can_invoke()`
- Records `"allow"` or `"deny"` string (not bool)

### BridgeCompileResult.conflicts (BO125)
- Always a list (never None)
- `conflict_count` property = `len(conflicts)`
- Populated best-effort (silent on import failure)

### make_delegation_stage() (BS129)
- Returns `PipelineStage(name="delegation")`
- Calls `manager.can_invoke(actor, tool, "tools/invoke", leaf_cid=leaf_cid)`
- Missing fields → `{"allowed": False, "reason": "delegation error: ..."}`

### logic/api.py imports (BW133)
- Use `import ipfs_datasets_py.logic.api as api` (not `from ipfs_datasets_py.logic import api`)
- The `__getattr__` in `logic/__init__.py` causes `RecursionError` with the `from ... import api` pattern

---

## 4. Evergreen Backlog (v17 candidates)

| Session | Target | Effort | Priority |
|---------|--------|--------|----------|
| BX134 | `nl_policy_conflict_detector.py` — emit conflicts as MCP tool warnings | Low | 🔴 High |
| BY135 | `DelegationManager.save_encrypted(password)` — AES-256-GCM store | Med | 🟡 Med |
| BZ136 | `UCANPolicyBridge.evaluate()` with real `DelegationManager` | Med | 🔴 High |
| CA137 | `dispatch_pipeline.py` audit integration — record every stage result | Low | 🟡 Med |
| CB138 | `NLPolicyConflictDetector` i18n — French/Spanish/German | Med | 🟡 Med |
| CC139 | `DelegationChain` ASCII visualization | Low | 🟢 Low |
| CD140 | `logic/api.py` smoke tests — all `__all__` symbols load | Low | 🟡 Med |
| CE141 | `PipelineMetricsRecorder` writes audit entries | Low | 🟡 Med |
| CF142 | Groth16 circuit_version=2 Phase 4b | High | 🟢 Low |
| CG143 | TDFOL NL spaCy integration tests (skip-guarded) | Med | 🟡 Med |
| CH144 | `DelegationManager` + `PolicyAuditLog` MCP tool | Med | 🟡 Med |

---

## 5. Success Criteria (v8)

| Criterion | Target | Status |
|-----------|--------|--------|
| Tests (total) | 3,000+ | ✅ 3,016 |
| Test pass rate | 100% | ✅ 0 failing |
| NL→UCAN phases | All 8 | ✅ Complete |
| DelegationManager | Full lifecycle | ✅ Complete |
| Conflict detection | Auto in bridge | ✅ BO125 |
| Audit logging | All can_invoke | ✅ BR128 |
| Pipeline delegation | Stage factory | ✅ BS129 |
| Blessed API | logic/api.py | ✅ BW133 |
| TDFOL NL dataclasses | Pattern/Parse | ✅ TDFOL-NL-T3/T4 |
