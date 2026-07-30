# Crypto IR Release and Rollback

Status: normative for CRYPTOIR-G610 / CRYPTOIR-035  
Companion: [`OPERATIONS.md`](OPERATIONS.md)  
Authority baseline: [`AUTHORITY_AND_POLICY.md`](AUTHORITY_AND_POLICY.md)  
Threat model: [`THREAT_MODEL.md`](THREAT_MODEL.md)  
Machine policy: the fenced JSON block labeled `crypto-ir-release-gate-v1` in this file  
Evidence tests:

- `ipfs_datasets_py/tests/contract/logic/crypto_ir/test_multichain_conformance.py`
- `ipfs_datasets_py/tests/contract/processors/smart_contracts/test_security_gate.py`
- `ipfs_datasets_py/tests/contract/processors/wallets/test_transaction_preflight.py`

This document freezes the **release gate**, staged enforcement promotion, and
**rollback plan** for Crypto IR cross-chain conformance. It is an engineering
assurance baseline, not a legal opinion, OFAC license, or authorization to
move funds. Processors remain non-custodial and never sign or broadcast.

## 1. Mission

Prove that every supported chain family meets adversarial conformance before
any enforcement class may leave observation or shadow mode, and that any
regression returns the affected surface to shadow or fail-closed review while
**preserving all audit evidence**.

AST conceptual surfaces named by this goal:

| Surface | Role |
| --- | --- |
| `MultichainConformance` | Cross-chain adversarial corpus and case catalog |
| `ReleaseGate` | Checklist that must pass before promotion |
| `RollbackPlan` | Reversible demotion that never deletes audit receipts |
| `TransactionPreflight` | Exact-candidate, one-use admissibility gate |

## 2. Pinned repository baseline

Release and rollback bind these reviewed revisions from
`docs/planning/CRYPTO_IR_COMPLIANCE_PLAN.md`. Silent drift to a moving tip is
out of policy.

| Component | Pinned revision |
| --- | --- |
| 211-AI tree | `34b536b59bfb7fcb4c7772b7078fe04709e92fc8` |
| `ipfs_datasets_py` | `75ae1de0fd5d8bc3625d26de3ccdd65f3a070dc9` |
| `ipfs_accelerate_py` | `c3988ec5e4c55edf8ce541825d82c10e11318745` |
| `ipfs_kit_py` | `276d766b8076b725a5a9e53bcf0c057f067acd10` |

Policy identity:

- `policy_id`: `crypto-ir-release-gate-v1`
- `policy_version`: `1.0.0`
- `schema_version`: `ipfs-datasets.crypto-ir-release-gate.v1`
- Goal: `CRYPTOIR-G610`
- Task: `CRYPTOIR-035`

## 3. Staged enforcement classes

Promote **one reviewed enforcement class at a time**. Observation and shadow
must run first for every class.

| Stage | Class id | Signing impact | Promotion prerequisite |
| --- | --- | --- | --- |
| 1 | `observe` | None — ingest/normalize only | Multichain corpus green offline |
| 2 | `shadow` | None — emit decisions beside existing paths | Observe stable; zero false ALLOW in hard-deny fixtures |
| 3 | `review_only` | Automated signing remains disabled; holds/queues consume receipts | Shadow false-positive review by compliance/legal |
| 4 | `direct_list` | Hard deny for exact authoritative identifiers | Named jurisdiction/list policy reviewed |
| 5 | `contract` | Contract obligations with fresh proof may block | Obligation sets with coverage and proof evidence approved |
| 6 | `indirect_flow` | Bounded exposure policy may block | Mixer/exchange/bridge false-positive/negative review |
| 7 | `broader_automatic` | Broader automated use | Production telemetry, recovery drills, explicit authorization |

Any stale binding, provider/list/capability loss, proof disagreement,
current-tree regression, resource violation, or audit failure returns the
**affected** behavior to `shadow` or fail-closed `review_only`. Never skip
stages; never promote two classes in the same change without dual owner
approval.

## 4. ReleaseGate checklist

A release may leave shadow only when **all** of the following hold for the
current tree:

1. **Zero false ALLOW** — every hard-deny fixture yields `DENY` (or another
   non-ALLOW blocking outcome); never `ALLOW`.
2. **Zero stale critical ALLOW** — every stale-critical-evidence fixture
   yields `STALE`, `INCONCLUSIVE`, `ERROR`, or `DENY`; never `ALLOW`.
3. **Authority non-elevation** — heuristic, monitor, SAT, model, and graph
   outputs never promote to theorem or designation authority.
4. **Semantic coverage** — every chain family either has explicit coverage for
   the evaluated semantics or returns fail-closed `UNSUPPORTED`.
5. **Deterministic identities** — request, candidate, epoch, obligation, and
   receipt digests reproduce across processes.
6. **Non-custodial processors** — no secret material, signing key, broadcast
   handle, or external-reporting path in processor imports or public APIs
   without a consumed one-use capability.
7. **Resource and egress budgets** — measured latency, memory, storage,
   provider, proof, and graph budgets hold; offline suites open no sockets.
8. **Invalidation** — upgrade/list/graph/policy changes invalidate prior
   receipts and capabilities.
9. **Rollback drill** — demotion to shadow/review preserves audit evidence and
   restores non-enforcement behavior within the recovery objective.
10. **Named owner approvals** — security, privacy, compliance/legal,
    operations, and release owners approve the staged enforcement class.

### Multichain case catalog (required)

For each chain family in `{evm, solana, bitcoin, xrpl, worldcoin}` the corpus
must include at least one of each:

| Case kind | Expected automation effect |
| --- | --- |
| `positive` | Current ALLOW only with full fresh evidence |
| `adversarial` | Substitution / privilege abuse → non-ALLOW |
| `unsupported` | Outside model coverage → non-ALLOW |
| `stale` | Expired critical input → non-ALLOW |
| `reorg` | Finality retraction / reorg → non-ALLOW or explicit review |
| `substitution` | Candidate / epoch / list swap → non-ALLOW |
| `incomplete_evidence` | Missing requirement or coverage → non-ALLOW |

## 5. RollbackPlan

### Principles

1. **Preserve audit evidence.** Rollback never deletes decision receipts,
   capability consumption records, sanctions snapshot digests, code-epoch
   bindings, or conformance run artifacts.
2. **Demote, do not erase.** Affected enforcement classes return to `shadow`
   or `review_only`. Config pointers change; historical rows stay immutable.
3. **Scope narrowly.** Demote only the failing class/chain/capability when
   possible; do not disable unrelated observe pipelines.
4. **Re-entry requires the ReleaseGate.** Returning to enforcement re-runs the
   full checklist for that class on the current tree.
5. **No silent bypass.** Rollback must not introduce `approved=true`,
   `force_allow`, or other forbidden surfaces.

### Triggers

| Trigger | Immediate action |
| --- | --- |
| Hard-deny fixture obtains `ALLOW` | Freeze promotion; demote class to `review_only` |
| Stale-critical fixture obtains `ALLOW` | Demote class to `shadow`; open incident |
| Resource or egress budget breach | Pause live providers; keep offline gates |
| Proof disagreement / capability loss | Demote contract class; keep observe |
| Upstream pin conflict unresolved | Hold release; reconcile pins explicitly |
| Privacy / legal / security owner veto | Demote to previous approved stage |

### Drill steps

1. Snapshot current enforcement class map and pin digests into the audit log.
2. Set the target class to `shadow` (or `review_only` if holds must continue).
3. Confirm signing/broadcast paths refuse without a current capability.
4. Confirm observe pipelines still emit normalized artifacts.
5. Archive the demotion receipt with actor, time, reason codes, and prior class.
6. File recovery follow-ups; do not re-promote until ReleaseGate is green.

### Recovery objective

- **Detection to demotion:** within one incident window of validated evidence.
- **Audit retention:** indefinite for receipt digests; operational logs per
  privacy policy.
- **Customer impact:** automated signing may pause; observe and shadow continue.

## 6. Upstream reconciliation

When the pinned baseline conflicts with reviewed upstream changes:

1. Record the conflict (component, pin, upstream tip, semantic delta).
2. Prefer fail-closed: do not silently retarget pins.
3. Update pins only after review owners approve and conformance re-runs green.
4. Attach reconciliation notes to the release evidence pack.

## 7. Named owners (approval lattice)

| Owner role | Approves |
| --- | --- |
| Security | Threat model residual risk, contract enforcement class |
| Privacy | Data minimization, nullifier/commitment handling, retention |
| Compliance / legal | Direct-list and indirect-flow jurisdiction/policy bindings |
| Operations | Resource budgets, recovery drills, observe/shadow health |
| Release | Final gate sign-off and pin reconciliation |

All five must approve any promotion from `shadow` into an enforcement class
that can block or allow automated signing.

## 8. Acceptance evidence

Current-tree evidence for this goal includes:

- Multichain adversarial conformance suite
  (`test_multichain_conformance.py`) covering every chain family and case kind.
- Contract safety gate suite (`test_security_gate.py`).
- Transaction preflight suite (`test_transaction_preflight.py`).
- This release/rollback playbook and [`OPERATIONS.md`](OPERATIONS.md).

Validation command:

```bash
python -m pytest -q \
  ipfs_datasets_py/tests/contract/logic/crypto_ir/test_multichain_conformance.py \
  ipfs_datasets_py/tests/contract/processors/smart_contracts/test_security_gate.py \
  ipfs_datasets_py/tests/contract/processors/wallets/test_transaction_preflight.py
```

## 9. Machine policy (`ReleaseGate` / `RollbackPlan`)

```json crypto-ir-release-gate-v1
{
  "schema_version": "ipfs-datasets.crypto-ir-release-gate.v1",
  "policy_id": "crypto-ir-release-gate-v1",
  "policy_version": "1.0.0",
  "normative": true,
  "goal_id": "CRYPTOIR-G610",
  "task_id": "CRYPTOIR-035",
  "conceptual_interfaces": {
    "MultichainConformance": {
      "role": "cross_chain_adversarial_corpus",
      "chain_families": ["evm", "solana", "bitcoin", "xrpl", "worldcoin"],
      "required_case_kinds": [
        "positive",
        "adversarial",
        "unsupported",
        "stale",
        "reorg",
        "substitution",
        "incomplete_evidence"
      ]
    },
    "ReleaseGate": {
      "role": "promotion_checklist",
      "zero_false_allow": true,
      "zero_stale_critical_allow": true,
      "require_owner_approvals": [
        "security",
        "privacy",
        "compliance_legal",
        "operations",
        "release"
      ]
    },
    "RollbackPlan": {
      "role": "reversible_demotion",
      "preserve_audit_evidence": true,
      "delete_receipts_forbidden": true,
      "default_demotion_target": "shadow",
      "fail_closed_demotion_target": "review_only"
    },
    "TransactionPreflight": {
      "role": "exact_candidate_one_use_admissibility",
      "non_allow_blocks_automation": true
    }
  },
  "enforcement_stages": [
    "observe",
    "shadow",
    "review_only",
    "direct_list",
    "contract",
    "indirect_flow",
    "broader_automatic"
  ],
  "promotion_rules": {
    "observe_and_shadow_first": true,
    "one_class_at_a_time": true,
    "reentry_requires_full_gate": true
  },
  "prohibitions": [
    "false_allow_on_hard_deny",
    "allow_with_stale_critical_evidence",
    "silent_pin_retarget",
    "delete_audit_evidence_on_rollback",
    "approved_true_bypass",
    "force_allow_bypass",
    "secret_or_sign_or_broadcast_in_processors_without_capability"
  ],
  "pinned_baseline": {
    "tree_revision": "34b536b59bfb7fcb4c7772b7078fe04709e92fc8",
    "ipfs_datasets_py": "75ae1de0fd5d8bc3625d26de3ccdd65f3a070dc9",
    "ipfs_accelerate_py": "c3988ec5e4c55edf8ce541825d82c10e11318745",
    "ipfs_kit_py": "276d766b8076b725a5a9e53bcf0c057f067acd10"
  },
  "acceptance": {
    "all_chain_families_cased": true,
    "identities_and_receipts_reproduce": true,
    "resource_and_egress_budgets_hold": true,
    "rollback_preserves_audit_evidence": true,
    "staged_enforcement_owner_approved": true
  }
}
```

## 10. Related documents

- [`OPERATIONS.md`](OPERATIONS.md) — day-2 operate, observe, shadow, recovery.
- [`AUTHORITY_AND_POLICY.md`](AUTHORITY_AND_POLICY.md) — authority lattice.
- [`THREAT_MODEL.md`](THREAT_MODEL.md) — TCB and fail-closed outcomes.
- [`SANCTIONS_POLICY.md`](SANCTIONS_POLICY.md) — sanctions authority boundary.
- `docs/planning/CRYPTO_IR_COMPLIANCE_PLAN.md` — program plan (read-only).
- `docs/planning/CRYPTO_IR_COMPLIANCE_OBJECTIVES.md` — objective heap (read-only).
