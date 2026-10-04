# Hybrid Legal Reasoner Release Checklist Template

> Copy this template for each release. Fill in version, date, and sign-offs.

**Release version:** ___________  
**Release date:** ___________  
**Preparer:** ___________  
**Reviewer:** ___________

---

## 1. Pre-Release Quality Checks

- [ ] All reasoner tests pass: `python -m pytest ipfs_datasets_py/tests/reasoner/ -v --tb=short`
- [ ] No import errors in reasoner package
- [ ] `clear_v2_proof_store()` called between tests that use `explain_proof`
- [ ] Smoke test passes (see Runbook "Quick Smoke Test" section)

---

## 2. WS11 Gates (108 tests green, all 6 test files pass)

| Test File | Command | Status |
|---|---|---|
| `test_hybrid_v2_blueprint.py` | `pytest ipfs_datasets_py/tests/reasoner/test_hybrid_v2_blueprint.py -v` | [ ] Pass |
| `test_hybrid_v2_parse_replay.py` | `pytest ipfs_datasets_py/tests/reasoner/test_hybrid_v2_parse_replay.py -v` | [ ] Pass |
| `test_hybrid_v2_compiler_parity.py` | `pytest ipfs_datasets_py/tests/reasoner/test_hybrid_v2_compiler_parity.py -v` | [ ] Pass |
| `test_kg_enrichment_adapter.py` | `pytest ipfs_datasets_py/tests/reasoner/test_kg_enrichment_adapter.py -v` | [ ] Pass |
| `test_prover_backend_registry.py` | `pytest ipfs_datasets_py/tests/reasoner/test_prover_backend_registry.py -v` | [ ] Pass |
| `test_hybrid_v2_query_api_matrix.py` | `pytest ipfs_datasets_py/tests/reasoner/test_hybrid_v2_query_api_matrix.py -v` | [ ] Pass |

- [ ] Total WS11 test count: **108 tests passing**

---

## 3. WS12 Gates (all 8 WS12 items complete, evidence manifest valid)

| # | Test File | Status |
|---|---|---|
| WS12-01 | `test_policy_pack_schema.py` | [ ] Pass |
| WS12-02 | `test_policy_resolver_determinism.py` | [ ] Pass |
| WS12-03 | `test_hybrid_v2_jurisdiction_matrix.py` | [ ] Pass |
| WS12-04 | `test_hybrid_v2_conflict_reason_codes.py` | [ ] Pass |
| WS12-05 | `test_conflict_triage_report_builder.py` | [ ] Pass |
| WS12-06 | `test_perf_budget_sentinel.py` | [ ] Pass |
| WS12-07 | `test_release_evidence_pack_v2.py` | [ ] Pass |
| WS12-08 | Runbook + TODO updated | [ ] Done |

- [ ] Evidence manifest valid (`all_present: true`)

Run all WS12 gates at once:
```bash
bash ipfs_datasets_py/scripts/ops/legal_data/run_hybrid_v2_release_evidence_pack.sh
```

---

## 4. Latency / Performance Gates

Run the benchmark and assert budget sentinel:
```bash
python ipfs_datasets_py/scripts/ops/legal_data/benchmark_hybrid_v2_reasoner.py
python ipfs_datasets_py/scripts/ops/legal_data/assert_hybrid_v2_perf_budgets.py
```

| Phase | p95 Budget | Measured p95 | Status |
|---|---|---|---|
| Parse CNL → IR | ≤ 50 ms | _______ ms | [ ] Pass |
| Compile IR → DCEC | ≤ 50 ms | _______ ms | [ ] Pass |
| Compile IR → TDFOL | ≤ 50 ms | _______ ms | [ ] Pass |
| Check compliance | ≤ 100 ms | _______ ms | [ ] Pass |
| Explain proof | ≤ 200 ms | _______ ms | [ ] Pass |

- [ ] Budget sentinel exits 0 (no budget exceeded)

---

## 5. Triage Checks

```bash
python ipfs_datasets_py/scripts/ops/legal_data/build_hybrid_legal_conflict_triage.py
```

- [ ] Conflict triage report generated (JSON output valid)
- [ ] Conflict triage report generated (Markdown output valid)
- [ ] No `PC_CONFLICT_UNRESOLVED` entries in triage report
- [ ] All conflicts have remediation hints

---

## 6. Evidence Pack

```bash
python ipfs_datasets_py/scripts/ops/legal_data/build_hybrid_v2_evidence_manifest.py
```

- [ ] Manifest generated with `manifest_version: "2.0"`
- [ ] All 13 required artifacts present (`all_present: true`)
- [ ] All artifact sha256 hashes recorded
- [ ] No `missing_artifacts` entries

---

## 7. Sign-Off

| Role | Name | Date | Signature |
|---|---|---|---|
| Preparer | | | |
| Reviewer | | | |
| Release approver | | | |

**Release decision:** [ ] APPROVED  [ ] BLOCKED (see notes below)

**Notes:**

_______________________________________________________________________

_______________________________________________________________________
