# Knowledge Graphs — Gate Runbook (KGP-G010 … KGP-G100)

**Status:** active  
**Tasks:** `KGP-049` (collector); `KGP-035` (release evidence gate)  
**Policy:** `kg-release-evidence/v1`  
**Collector schema:** `kg-release-evidence-collector/v1`  
**Code:** `ipfs_datasets_py.knowledge_graphs.release_evidence`, `ipfs_datasets_py.knowledge_graphs.release_gate`  
**Companion:** `docs/operations/knowledge_graphs_release.md`  

## Purpose

This runbook explains **all ten child gates** (`KGP-G010` through
`KGP-G100`) and the **root release decision** produced by
`GraphReleaseGate` / `ReleaseEvidenceCollector`.

The platform is **not production ready** until the collector builds a
complete evidence bundle bound to an **explicit clean repository tree**
and `GraphReleaseGate` emits a signed decision with
`production_ready=True`. Task status, coverage, prose, skips,
expected failures (xfail), sample-only corpus runs, absent soak/chaos,
missing UCAN deny proof, unknown environments, foreign trees, stale
receipts, and unsigned evidence (when signatures are required) are
**never** accepted as substitutes.

## Standing rule (fail-closed)

Missing, failed, skipped, expected-failure, stale, foreign-tree,
dirty-tree, partial, contradicted, or unsigned evidence **fails closed**.
There is no partial credit toward production readiness.

## Collector workflow

```python
from ipfs_datasets_py.knowledge_graphs.release_evidence import (
    ReleaseEvidenceCollector,
    TestCounts,
    resolve_clean_tree,
)

collector = ReleaseEvidenceCollector(
    signing_key=b"<operator-hmac-key>",
    require_signatures=True,
    package_version="0.x.y",
)
collector.bind_clean_repository("/path/to/repo")
collector.set_environment("lab-kg-release-1", "labelled lab")

# For each child goal G010..G090: run validation, then accept only
# clean pass evidence (exit 0, no fails/skips/xfails, digests present).
collector.record_and_accept_goal(
    goal_id="KGP-G010",
    command="python -m pytest -q tests/knowledge_graphs/contract",
    exit_status=0,
    test_counts=TestCounts(passed=12),
    artifact_digests=("sha256:<artifact>",),
    signature="hmac-sha256:<mac>",
)

# Ingest special evidence classes required by the root DoD:
collector.ingest_corpus_signoff(
    corpus_id="cvefixes", producer_id="…", signer="…",
    signature="hmac-sha256:<mac>",
)
collector.ingest_ucan_deny_proof(
    deny_receipt_cids=("sha256:<deny-receipt>",),
    signature="hmac-sha256:<mac>",
)
collector.ingest_load_soak_chaos(
    soak_receipt_digest="sha256:<soak>",
    chaos_receipt_digest="sha256:<chaos>",
    load_receipt_digest="sha256:<load>",
    signature="hmac-sha256:<mac>",
)

decision = collector.evaluate()
assert decision.production_ready  # only when fully green
collector.write_runbook("docs/operations/knowledge_graphs_gate_runbook.md")
```

### Evidence fields recorded per command

| Field | Meaning |
| --- | --- |
| `command` | Exact validation command executed |
| `timestamp` | UTC collection time (ISO-8601 `…Z`) |
| `environment_label` | Labelled environment (never `unknown`) |
| `exit_status` | Process exit code (must be `0` to accept) |
| `test_counts` | `passed` / `failed` / `skipped` / `xfailed` / `errors` |
| `artifact_digests` | Content digests of retained artifacts |
| `tree_id` | Explicit clean repository tree binding |

### Refusal matrix

| Condition | Refusal code |
| --- | --- |
| Nonzero exit or failed/error tests | `failed` / `nonzero_exit` |
| Skipped tests or skip status | `skipped` |
| Expected-failure / xfail | `expected_failure` |
| Receipt older than max age | `stale` |
| `tree_id` ≠ collector tree | `foreign_tree` |
| Dirty working tree | `dirty_tree` |
| Signature required but missing/invalid | `unsigned` |
| Task status / coverage / prose substitutes | `rejected_substitute` |
| Sample-only corpus mode | `sample_only` |
| Unknown / empty environment | `unknown_environment` |

## Ten child gates

### KGP-G010 — Executable truth baseline and compatibility contract

- **Evidence kind:** `contract_probe`
- **Default validation:** `python -m pytest -q tests/knowledge_graphs/contract`
- **Release role:** Child goal receipt required by the root gate.

### KGP-G020 — Canonical graph identity, manifest, catalog, and service

- **Evidence kind:** `validation_receipt`
- **Default validation:** `python -m pytest -q tests/unit/knowledge_graphs/contracts tests/integration/knowledge_graphs/test_catalog_service.py`
- **Release role:** Child goal receipt required by the root gate.

### KGP-G030 — Durable concurrency, transactions, and recovery

- **Evidence kind:** `concurrency_receipt`
- **Default validation:** `python -m pytest -q tests/unit/knowledge_graphs/test_transactions.py tests/integration/knowledge_graphs/concurrency tests/chaos/knowledge_graphs`
- **Release role:** Child goal receipt required by the root gate.

### KGP-G040 — Interchangeable Parquet, IPFS/IPLD, and ipfs_kit_py storage

- **Evidence kind:** `storage_contract`
- **Default validation:** `python -m pytest -q tests/contract/knowledge_graphs/storage tests/integration/knowledge_graphs/test_storage_restart.py`
- **Release role:** Child goal receipt required by the root gate.

### KGP-G050 — Versioned sharding and bounded unified query

- **Evidence kind:** `sharding_integrity`
- **Default validation:** `python -m pytest -q tests/unit/search/test_sharded_car tests/integration/knowledge_graphs/test_sharded_query.py tests/knowledge_graphs/contract/test_query_budgets.py`
- **Release role:** Child goal receipt required by the root gate.

### KGP-G060 — Python, CLI, MCP, and MCP++ surface parity

- **Evidence kind:** `surface_conformance`
- **Default validation:** `python -m pytest -q tests/knowledge_graphs/conformance tests/cli/test_graph_commands.py tests/mcp/test_graph_tools.py`
- **Release role:** Child goal receipt required by the root gate.

### KGP-G070 — MCP++ UCAN authorization and audit

- **Evidence kind:** `ucan_audit_receipt`
- **Default validation:** `python -m pytest -q tests/security/knowledge_graphs tests/mcp/test_graph_ucan.py`
- **Release role:** Child goal receipt required by the root gate.

### KGP-G080 — Real corpus adapters and differential validation

- **Evidence kind:** `corpus_differential`
- **Default validation:** `python -m pytest -q tests/integration/knowledge_graphs/corpora`
- **Release role:** Child goal receipt required by the root gate.

### KGP-G090 — Load, soak, chaos, observability, and operability

- **Evidence kind:** `load_receipt`
- **Default validation:** `python -m pytest -q tests/load/knowledge_graphs tests/chaos/knowledge_graphs`
- **Release role:** Child goal receipt required by the root gate.

### KGP-G100 — Reversible adoption and production release (root gate)

- **Evidence kind:** `migration_receipt`
- **Default validation:** `python -m pytest -q tests/integration/knowledge_graphs/test_shadow_migration.py tests/integration/knowledge_graphs/test_rollback.py tests/integration/knowledge_graphs/test_release_gate.py tests/integration/knowledge_graphs/test_release_evidence_collector.py`
- **Role:** Root adoption / production-release gate. Depends on
  fresh passing receipts for `KGP-G010`…`KGP-G090` plus root
  definition-of-done clauses (corpus sign-off, UCAN deny,
  load/soak/chaos, labelled environment, migration reversibility).
- **Decision authority:** `GraphReleaseGate.evaluate` /
  `ReleaseEvidenceCollector.evaluate`.

## Root definition-of-done clauses

In addition to child-goal receipts, the root release decision requires
exact fresh passing receipts for every clause below:

| `clause_id` | Meaning |
| --- | --- |
| `concurrent_identity_durability` | At least 16 graph IDs can be read and written concurrently without identity confusion, lost updates, or cross-tenant leakage. |
| `storage_profiles_contract` | Parquet, direct IPFS/IPLD, and ipfs_kit_py profiles pass the same contract suite, including restart and crash recovery. |
| `four_surface_parity` | Python, CLI, MCP, and MCP++ pass the same operation/query/error vectors. |
| `ucan_fail_closed` | UCAN allow, attenuation, expiry, revocation, replay, and denial tests pass with fail-closed audit evidence. |
| `sharded_integrity` | v1 and v2 sharded graphs pass integrity and cross-shard traversal tests. |
| `corpora_differential` | CVEfixes, SkillCenter, 211-AI, and code/evidence graph fixtures pass differential and representative workload tests. |
| `load_soak_chaos_ops` | Load, soak, chaos, backup/restore, observability, and resource bounds pass on a labelled environment. |
| `migration_reversible` | Migration runbooks, rollback, compatibility policy, and deprecation warnings are published, with no legacy codepath moved before its gate. |

### Special ingest requirements

| Class | Required items |
| --- | --- |
| Corpus sign-off (full mode) | `cvefixes`, `skillcenter`, `two_eleven`, `code_evidence` |
| UCAN negative proof | ≥1 deny receipt CID bound to the tree |
| Load / soak / chaos | Non-empty soak **and** chaos digests (load recommended) |
| Environment | Labelled `environment_id` + label on the same tree |

## Root release decision

The root decision is the only authority for **production readiness**.

```text
production_ready  ⇔  outcome == pass
                 ∧  zero blockers
                 ∧  all G010–G090 receipts satisfied
                 ∧  all root DoD clauses satisfied
                 ∧  corpus + UCAN + soak/chaos + environment OK
                 ∧  (optional) HMAC signature verifies
```

Until then, treat the platform as **not production ready**.

### Evaluating

```python
from ipfs_datasets_py.knowledge_graphs.release_gate import GraphReleaseGate
from ipfs_datasets_py.knowledge_graphs.release_evidence import (
    ReleaseEvidenceCollector,
)

decision = collector.evaluate()  # fail-closed GraphReleaseGate under the hood
if not decision.production_ready:
    for blocker in decision.blockers:
        print(blocker.code, blocker.subject, blocker.message)
# Retain decision.decision_cid + decision.signature on the release ticket.
```

### Current decision snapshot

No evaluation has been run in this collector session. Default posture:
**not production ready**.

## Validation

```bash
python -m pytest -q \
  tests/integration/knowledge_graphs/test_release_gate.py \
  tests/integration/knowledge_graphs/test_release_evidence_collector.py
```

## Related documents

| Topic | Location |
| --- | --- |
| Release / cutover ops | `docs/operations/knowledge_graphs_release.md` |
| Day-2 ops & DR | `docs/operations/knowledge_graphs_runbook.md` |
| SLOs | `docs/operations/knowledge_graphs_slos.md` |
| Gate implementation | `ipfs_datasets_py/knowledge_graphs/release_gate.py` |
| Collector implementation | `ipfs_datasets_py/knowledge_graphs/release_evidence.py` |

