# Crypto IR Authority and Policy Baseline

Status: normative for CRYPTOIR-G010 / CRYPTOIR-001  
Companion: [`THREAT_MODEL.md`](THREAT_MODEL.md)  
Machine policy: the fenced JSON block labeled `crypto-ir-authority-policy-v1` in this file  
Evidence test: `ipfs_datasets_py/tests/unit/logic/crypto_ir/test_policy_baseline.py`

This document freezes result-authority, policy, freshness, and fail-closed rules
for Crypto IR **before** schemas, chain adapters, or transaction gates are
implemented. It is an engineering assurance baseline, not a legal opinion, OFAC
license, or authorization to move funds.

## 1. Pinned repository baseline

Authoritative documents and later Crypto IR code bind these reviewed revisions
from `docs/planning/CRYPTO_IR_COMPLIANCE_PLAN.md`. Consumers must fail closed if
any required pin is missing, rewritten without review, or silently swapped for a
moving branch tip.

| Component | Pinned revision |
| --- | --- |
| 211-AI tree | `34b536b59bfb7fcb4c7772b7078fe04709e92fc8` |
| `ipfs_datasets_py` | `75ae1de0fd5d8bc3625d26de3ccdd65f3a070dc9` |
| `ipfs_accelerate_py` | `c3988ec5e4c55edf8ce541825d82c10e11318745` |
| `ipfs_kit_py` | `276d766b8076b725a5a9e53bcf0c057f067acd10` |

Policy identity:

- `policy_id`: `crypto-ir-authority-policy-v1`
- `policy_version`: `1.0.0`
- `schema_version`: `ipfs-datasets.crypto-ir-authority-policy.v1`
- Goal: `CRYPTOIR-G010`
- Task: `CRYPTOIR-001`

## 2. Conceptual interfaces

The following conceptual interfaces are vocabulary contracts. They are not
runtime classes yet; every later receipt, analysis result, and preflight decision
must use them without silent coercion.

### `AnalysisAuthority`

Terminal vocabulary for a named security or compliance **analysis** obligation
evaluated under named assumptions, model, code epoch, and toolchain bindings.

Closed analysis outcomes: `PROVED`, `DISPROVED`, `UNKNOWN`, `UNSUPPORTED`,
`INCONCLUSIVE`, `STALE`, `ERROR`.

### `PolicyAuthority`

Vocabulary and combination rules for **legal/compliance policy** evaluation over
designations, ownership evidence, licenses, jurisdiction, and risk policy.
Policy authority never invents designations and never elevates heuristics.

### `TransactionVerdict`

Terminal vocabulary for a **transaction policy decision** bound to one exact
unsigned intent and one exact serialized candidate. Closed outcomes used by
enforcement: `ALLOW`, `REVIEW`, `DENY`, plus fail-closed carriers
`INCONCLUSIVE`, `STALE`, and `ERROR`.

For production signing or broadcast, every result other than a current `ALLOW`
blocks automated execution.

### `EvidenceFreshness`

Binding that records whether each critical input is current for the decision
epoch. Freshness covers sanctions snapshots, flow-graph snapshots, code epochs,
proxy/upgrade state, capability probes, policy revisions, and receipt expiry.
Stale critical inputs cannot produce `ALLOW`.

## 3. Authority lattice (non-interchangeable)

Authority kinds are **not** a scalar trust score and are **not** totally ordered
into a single number. A lower or different kind never becomes a higher kind by
aggregation, ranking, or model confidence.

| Authority kind | May assert | Must not assert |
| --- | --- | --- |
| `observation` | Chain/list/source facts with finality, time, and completeness | Proof, designation, or transaction authorization |
| `evidence` | Provenance-bound artifacts, digests, coverage, assumptions | Silent elevation to proof or designation |
| `proof` | Named obligation proved/disproved by an **executed** proof backend under named assumptions | Transaction `ALLOW` by itself; universal security |
| `monitor` | Bounded-trace satisfaction/violation only | Theorem proof or designation |
| `heuristic` | Prioritization signals (cluster, fuzzy match, GraphRAG, mixer tags) | Designation, blocked-party conclusion, or sole basis for `ALLOW` |
| `designation` | Exact listed identifier or reviewed designated party from an authoritative snapshot | Invention from graph distance or heuristics |
| `policy` | Reviewed legal/risk rule evaluation under bound jurisdiction and revisions | Creation of new list entries or rewriting of proof status |
| `authorization` | Transaction verdict for one exact candidate under live revalidation | Conversion of failed/stale/unsupported analysis into success |

**Non-escalation rule.** Observation or high risk scores cannot be relabeled
designation. Satisfiability, monitor, heuristic, GraphRAG, or model output
cannot be relabeled theorem proof. Proof results cannot themselves authorize a
transaction. Only `authorization` under `PolicyAuthority` may emit
`TransactionVerdict`.

## 4. Exact analysis outcome semantics

| Outcome | Meaning | Fail-closed for automation |
| --- | --- | --- |
| `PROVED` | Named obligation proved for the exact model, assumptions, code epoch, and executed backend | No (analysis success only; still not a transaction `ALLOW`) |
| `DISPROVED` | Valid counterexample or proof of negation for the named obligation | Yes for any required obligation |
| `UNKNOWN` | Represented in model but undecided within budget or incomplete solver answer | Yes when the outcome is required |
| `UNSUPPORTED` | Material semantics outside every reviewed model or frontend coverage | Yes when the outcome is required |
| `INCONCLUSIVE` | Required evidence, capability, or binding missing | Yes |
| `STALE` | Formerly usable result expired or an input epoch changed | Yes |
| `ERROR` | Evaluation did not complete safely | Yes |

Narrow evidence-bound claims are preferred to broad claims the current models
cannot prove. The strongest permissible security claim is that named
obligations were proved under named assumptions for an exact code epoch and
toolchain—not that a contract is “secure.”

Solver answers `SATISFIABLE` / `UNSATISFIABLE` and monitor outcomes
`MONITOR_SATISFIED` / `MONITOR_VIOLATED` are related analysis sub-vocabularies.
They never silently coerce into `PROVED` or `DISPROVED`.

## 5. Exact transaction policy verdict semantics

| Verdict | Meaning | Automated sign/broadcast |
| --- | --- | --- |
| `ALLOW` | All policy-required evidence and obligations pass and are fresh for the exact candidate | Permitted only with a short-lived one-use capability |
| `REVIEW` | Configured risk or ambiguity requires human authority | Blocked |
| `DENY` | Hard prohibition or disqualifying security/compliance result | Blocked |
| `INCONCLUSIVE` | Required evidence or capability missing | Blocked |
| `STALE` | Decision or critical input expired or epoch-changed | Blocked |
| `ERROR` | Evaluation did not complete safely | Blocked |

## 6. Legal and policy boundary

- This library produces evidence, analysis results, and workflow states.
- It does **not** declare that any person or transaction is lawful.
- Jurisdiction, sanctions programs, ownership rules (for example aggregate 50
  Percent Rule application), licenses, escalation thresholds, retention,
  reporting, and release policy require named human legal/compliance owners
  before enforcement is enabled.
- Automatic external reporting to OFAC or law enforcement is out of scope unless
  a later reviewed objective adds authority.
- There is no universal allowlist bypass.

### Match-authority levels (must not collapse)

1. Exact listed digital-currency identifier from an authoritative snapshot.
2. Named designated party with source-backed identity.
3. Owned entity under an approved ownership rule and evidence.
4. Direct transaction association with (1)–(3).
5. Indirect flow exposure under bounded path policy (risk, not designation).
6. Heuristic association (review prioritization only).

**Prohibitions.**

- Unbounded guilt by association is forbidden: graph distance, taint alone,
  shared infrastructure, mixers, bridges, or fuzzy names cannot create a
  blocked-party or designation conclusion.
- Heuristics cannot produce `ALLOW` and cannot alone produce designation.
- Treating every address that once received funds from a listed address as a
  blocked person is forbidden without an approved, versioned risk policy and
  explicit human authority for that policy class.

## 7. Fail-closed and freshness rules

Critical inputs include: exact candidate digest, chain/network identity, code
epoch and proxy/upgrade state, sanctions snapshot, flow-graph snapshot and
completeness receipt, ownership evidence, policy/jurisdiction/license
revisions, capability probes, and receipt effective/expiry times.

Rules:

1. Unsupported or stale critical inputs fail closed — no automated `ALLOW`.
2. Missing, inconsistent, reorged, poisoned, truncated, or schema-drifted
   critical evidence fails closed.
3. Unavailable capability for a required obligation yields `INCONCLUSIVE` or
   `UNSUPPORTED`, never a silent pass.
4. Any material change to a bound input invalidates the decision; a new
   evaluation is required.
5. Pre-sign and pre-broadcast revalidation must re-check live facts; a bare
   boolean or caller-supplied “approved” flag is not authorization.
6. Overrides may hold, reject, request evidence, or attach a scoped license;
   they cannot convert a failed proof into a proof or make stale evidence fresh.

## 8. Normative machine policy

The following JSON is the machine-readable authority matrix. The human text
above explains intent. Tests evaluate the fixtures inside this block. If the
document prose and the JSON disagree, consumers must fail closed.

```json crypto-ir-authority-policy-v1
{
  "schema_version": "ipfs-datasets.crypto-ir-authority-policy.v1",
  "policy_id": "crypto-ir-authority-policy-v1",
  "policy_version": "1.0.0",
  "normative": true,
  "goal_id": "CRYPTOIR-G010",
  "task_id": "CRYPTOIR-001",
  "human_readable_companion": "THREAT_MODEL.md",
  "pinned_baseline": {
    "tree_revision": "34b536b59bfb7fcb4c7772b7078fe04709e92fc8",
    "ipfs_datasets_py": "75ae1de0fd5d8bc3625d26de3ccdd65f3a070dc9",
    "ipfs_accelerate_py": "c3988ec5e4c55edf8ce541825d82c10e11318745",
    "ipfs_kit_py": "276d766b8076b725a5a9e53bcf0c057f067acd10"
  },
  "conceptual_interfaces": {
    "AnalysisAuthority": {
      "role": "analysis_terminal_result",
      "vocabulary_ref": "analysis_outcomes",
      "meaning": "Terminal analysis vocabulary for one named obligation under bound assumptions and model.",
      "required_fields": ["id", "terminal", "fail_closed", "meaning", "claim_limit"]
    },
    "PolicyAuthority": {
      "role": "legal_policy_evaluation",
      "vocabulary_ref": "authority_kinds",
      "meaning": "Legal and risk policy evaluation authority; never invents designations from heuristics.",
      "required_fields": ["id", "may_assert", "must_not_assert"]
    },
    "TransactionVerdict": {
      "role": "transaction_policy_decision",
      "vocabulary_ref": "transaction_verdicts",
      "meaning": "Terminal policy decision for one exact transaction candidate.",
      "required_fields": ["id", "terminal", "blocks_automation", "meaning"]
    },
    "EvidenceFreshness": {
      "role": "input_currency_binding",
      "vocabulary_ref": "freshness_rules",
      "meaning": "Whether each critical input is current for the decision epoch.",
      "required_fields": ["critical_inputs", "stale_blocks_allow"]
    }
  },
  "authority_kinds": [
    {
      "id": "observation",
      "may_assert": ["chain_fact", "list_fact", "source_fact"],
      "must_not_assert": ["proof", "designation", "authorization"]
    },
    {
      "id": "evidence",
      "may_assert": ["artifact_digest", "coverage", "assumption"],
      "must_not_assert": ["proof", "designation", "authorization"]
    },
    {
      "id": "proof",
      "may_assert": ["proved_obligation", "disproved_obligation"],
      "must_not_assert": ["authorization", "universal_security"]
    },
    {
      "id": "monitor",
      "may_assert": ["bounded_trace_result"],
      "must_not_assert": ["proof", "designation", "authorization"]
    },
    {
      "id": "heuristic",
      "may_assert": ["review_priority"],
      "must_not_assert": ["designation", "blocked_party", "sole_allow"]
    },
    {
      "id": "designation",
      "may_assert": ["exact_listed_identifier", "reviewed_designated_party"],
      "must_not_assert": ["invented_from_graph_distance", "invented_from_heuristic"]
    },
    {
      "id": "policy",
      "may_assert": ["risk_evaluation", "ownership_rule_application", "license_scope"],
      "must_not_assert": ["new_list_entry", "rewrite_proof_status"]
    },
    {
      "id": "authorization",
      "may_assert": ["transaction_verdict"],
      "must_not_assert": ["convert_failed_proof_to_proved", "refresh_stale_evidence"]
    }
  ],
  "non_escalation_rules": [
    "observation_cannot_become_designation",
    "heuristic_cannot_become_designation",
    "monitor_cannot_become_proof",
    "satisfiability_cannot_become_proof",
    "proof_cannot_alone_authorize_transaction",
    "graph_distance_cannot_create_blocked_party",
    "absence_of_findings_is_not_proved"
  ],
  "analysis_outcomes": [
    {
      "id": "PROVED",
      "terminal": true,
      "fail_closed": false,
      "meaning": "Named obligation proved for exact model, assumptions, code epoch, and executed backend.",
      "claim_limit": "Does not imply universal security or transaction ALLOW."
    },
    {
      "id": "DISPROVED",
      "terminal": true,
      "fail_closed": true,
      "meaning": "Valid counterexample or proof of negation for the named obligation.",
      "claim_limit": "Disproof applies only to the bound obligation and assumptions."
    },
    {
      "id": "UNKNOWN",
      "terminal": true,
      "fail_closed": true,
      "meaning": "Represented in model but undecided within resource bounds.",
      "claim_limit": "Never treat as PROVED."
    },
    {
      "id": "UNSUPPORTED",
      "terminal": true,
      "fail_closed": true,
      "meaning": "Material semantics outside every reviewed model or frontend coverage.",
      "claim_limit": "Never invent unsupported chain behavior."
    },
    {
      "id": "INCONCLUSIVE",
      "terminal": true,
      "fail_closed": true,
      "meaning": "Required evidence, capability, or binding missing.",
      "claim_limit": "Cannot complete a required obligation."
    },
    {
      "id": "STALE",
      "terminal": true,
      "fail_closed": true,
      "meaning": "Formerly usable result expired or an input epoch changed.",
      "claim_limit": "Cannot produce ALLOW until revalidated."
    },
    {
      "id": "ERROR",
      "terminal": true,
      "fail_closed": true,
      "meaning": "Evaluation did not complete safely.",
      "claim_limit": "Must not be coerced to any success outcome."
    }
  ],
  "transaction_verdicts": [
    {
      "id": "ALLOW",
      "terminal": true,
      "blocks_automation": false,
      "meaning": "All required evidence and obligations pass and are fresh for the exact candidate."
    },
    {
      "id": "REVIEW",
      "terminal": true,
      "blocks_automation": true,
      "meaning": "Configured risk or ambiguity requires human authority."
    },
    {
      "id": "DENY",
      "terminal": true,
      "blocks_automation": true,
      "meaning": "Hard prohibition or disqualifying security or compliance result."
    },
    {
      "id": "INCONCLUSIVE",
      "terminal": true,
      "blocks_automation": true,
      "meaning": "Required evidence or capability missing."
    },
    {
      "id": "STALE",
      "terminal": true,
      "blocks_automation": true,
      "meaning": "Decision or critical input expired or epoch-changed."
    },
    {
      "id": "ERROR",
      "terminal": true,
      "blocks_automation": true,
      "meaning": "Evaluation did not complete safely."
    }
  ],
  "freshness_rules": {
    "critical_inputs": [
      "exact_candidate_digest",
      "chain_network_identity",
      "code_epoch",
      "proxy_or_upgrade_state",
      "sanctions_snapshot",
      "flow_graph_snapshot",
      "completeness_receipt",
      "ownership_evidence",
      "policy_jurisdiction_license_revisions",
      "capability_probes",
      "receipt_effective_expiry"
    ],
    "stale_blocks_allow": true,
    "unsupported_critical_blocks_allow": true,
    "missing_critical_blocks_allow": true,
    "material_change_invalidates_decision": true,
    "automation_requires_current_allow": true
  },
  "prohibitions": [
    "unbounded_guilt_by_association",
    "universal_security_claim",
    "heuristic_sole_allow",
    "heuristic_as_designation",
    "silent_authority_coercion",
    "bare_boolean_authorization",
    "stale_critical_allow",
    "unsupported_critical_allow"
  ],
  "match_authority_levels": [
    "exact_listed_digital_currency_identifier",
    "named_designated_party",
    "owned_entity_under_approved_rule",
    "direct_transaction_association",
    "indirect_flow_exposure",
    "heuristic_association"
  ],
  "claim_rule": "Report only claims justified by the named model, bound assumptions, current inputs, complete coverage, and the authority kind of the checked evidence. Narrow evidence-bound claims are preferable to broad claims that the current models cannot prove.",
  "decision_fixtures": [
    {
      "id": "allow_fresh_exact_candidate_all_required_pass",
      "analysis_outcome": "PROVED",
      "authority_kind": "authorization",
      "transaction_verdict": "ALLOW",
      "fresh_critical_inputs": true,
      "heuristic_only": false,
      "exact_designation_hit": false,
      "required_obligation_disproved": false,
      "expected_blocks_automation": false,
      "expected_satisfies_allow": true
    },
    {
      "id": "deny_exact_listed_identifier",
      "analysis_outcome": "UNKNOWN",
      "authority_kind": "designation",
      "transaction_verdict": "DENY",
      "fresh_critical_inputs": true,
      "heuristic_only": false,
      "exact_designation_hit": true,
      "required_obligation_disproved": false,
      "expected_blocks_automation": true,
      "expected_satisfies_allow": false
    },
    {
      "id": "deny_required_obligation_disproved",
      "analysis_outcome": "DISPROVED",
      "authority_kind": "proof",
      "transaction_verdict": "DENY",
      "fresh_critical_inputs": true,
      "heuristic_only": false,
      "exact_designation_hit": false,
      "required_obligation_disproved": true,
      "expected_blocks_automation": true,
      "expected_satisfies_allow": false
    },
    {
      "id": "review_indirect_flow_exposure",
      "analysis_outcome": "INCONCLUSIVE",
      "authority_kind": "policy",
      "transaction_verdict": "REVIEW",
      "fresh_critical_inputs": true,
      "heuristic_only": false,
      "exact_designation_hit": false,
      "required_obligation_disproved": false,
      "expected_blocks_automation": true,
      "expected_satisfies_allow": false
    },
    {
      "id": "reject_heuristic_as_designation",
      "analysis_outcome": "UNKNOWN",
      "authority_kind": "heuristic",
      "transaction_verdict": "DENY",
      "fresh_critical_inputs": true,
      "heuristic_only": true,
      "exact_designation_hit": false,
      "required_obligation_disproved": false,
      "treats_as_designation": true,
      "expected_blocks_automation": true,
      "expected_satisfies_allow": false,
      "expected_authority_violation": "heuristic_cannot_become_designation"
    },
    {
      "id": "reject_heuristic_sole_allow",
      "analysis_outcome": "UNKNOWN",
      "authority_kind": "heuristic",
      "transaction_verdict": "ALLOW",
      "fresh_critical_inputs": true,
      "heuristic_only": true,
      "exact_designation_hit": false,
      "required_obligation_disproved": false,
      "expected_blocks_automation": true,
      "expected_satisfies_allow": false,
      "expected_authority_violation": "heuristic_sole_allow"
    },
    {
      "id": "reject_stale_critical_allow",
      "analysis_outcome": "PROVED",
      "authority_kind": "authorization",
      "transaction_verdict": "ALLOW",
      "fresh_critical_inputs": false,
      "heuristic_only": false,
      "exact_designation_hit": false,
      "required_obligation_disproved": false,
      "expected_blocks_automation": true,
      "expected_satisfies_allow": false,
      "expected_authority_violation": "stale_critical_allow"
    },
    {
      "id": "reject_unsupported_as_allow",
      "analysis_outcome": "UNSUPPORTED",
      "authority_kind": "authorization",
      "transaction_verdict": "ALLOW",
      "fresh_critical_inputs": true,
      "heuristic_only": false,
      "exact_designation_hit": false,
      "required_obligation_disproved": false,
      "expected_blocks_automation": true,
      "expected_satisfies_allow": false,
      "expected_authority_violation": "unsupported_critical_allow"
    },
    {
      "id": "reject_unknown_as_allow",
      "analysis_outcome": "UNKNOWN",
      "authority_kind": "authorization",
      "transaction_verdict": "ALLOW",
      "fresh_critical_inputs": true,
      "heuristic_only": false,
      "exact_designation_hit": false,
      "required_obligation_disproved": false,
      "expected_blocks_automation": true,
      "expected_satisfies_allow": false
    },
    {
      "id": "reject_inconclusive_as_allow",
      "analysis_outcome": "INCONCLUSIVE",
      "authority_kind": "authorization",
      "transaction_verdict": "ALLOW",
      "fresh_critical_inputs": true,
      "heuristic_only": false,
      "exact_designation_hit": false,
      "required_obligation_disproved": false,
      "expected_blocks_automation": true,
      "expected_satisfies_allow": false
    },
    {
      "id": "reject_error_as_allow",
      "analysis_outcome": "ERROR",
      "authority_kind": "authorization",
      "transaction_verdict": "ALLOW",
      "fresh_critical_inputs": true,
      "heuristic_only": false,
      "exact_designation_hit": false,
      "required_obligation_disproved": false,
      "expected_blocks_automation": true,
      "expected_satisfies_allow": false
    },
    {
      "id": "reject_proof_alone_as_transaction_allow",
      "analysis_outcome": "PROVED",
      "authority_kind": "proof",
      "transaction_verdict": "ALLOW",
      "fresh_critical_inputs": true,
      "heuristic_only": false,
      "exact_designation_hit": false,
      "required_obligation_disproved": false,
      "expected_blocks_automation": true,
      "expected_satisfies_allow": false,
      "expected_authority_violation": "proof_cannot_alone_authorize_transaction"
    },
    {
      "id": "reject_observation_as_designation",
      "analysis_outcome": "UNKNOWN",
      "authority_kind": "observation",
      "transaction_verdict": "DENY",
      "fresh_critical_inputs": true,
      "heuristic_only": false,
      "exact_designation_hit": false,
      "required_obligation_disproved": false,
      "expected_blocks_automation": true,
      "expected_satisfies_allow": false,
      "expected_authority_violation": "observation_cannot_become_designation"
    },
    {
      "id": "reject_monitor_as_proof",
      "analysis_outcome": "PROVED",
      "authority_kind": "monitor",
      "transaction_verdict": "REVIEW",
      "fresh_critical_inputs": true,
      "heuristic_only": false,
      "exact_designation_hit": false,
      "required_obligation_disproved": false,
      "expected_blocks_automation": true,
      "expected_satisfies_allow": false,
      "expected_authority_violation": "monitor_cannot_become_proof"
    },
    {
      "id": "reject_universal_security_claim",
      "analysis_outcome": "PROVED",
      "authority_kind": "proof",
      "transaction_verdict": "ALLOW",
      "fresh_critical_inputs": true,
      "heuristic_only": false,
      "exact_designation_hit": false,
      "required_obligation_disproved": false,
      "claims_universal_security": true,
      "expected_blocks_automation": true,
      "expected_satisfies_allow": false,
      "expected_authority_violation": "universal_security_claim"
    },
    {
      "id": "reject_guilt_by_association_as_designation",
      "analysis_outcome": "UNKNOWN",
      "authority_kind": "heuristic",
      "transaction_verdict": "DENY",
      "fresh_critical_inputs": true,
      "heuristic_only": true,
      "exact_designation_hit": false,
      "required_obligation_disproved": false,
      "guilt_by_association": true,
      "expected_blocks_automation": true,
      "expected_satisfies_allow": false,
      "expected_authority_violation": "unbounded_guilt_by_association"
    }
  ]
}
```

## 9. Implementation boundary for this goal

CRYPTOIR-G010 freezes policy only. It does **not** implement chain parsing,
wallet signing, SDN ingestion, or gate services. Those remain later objectives
that must consume this authority lattice without widening it.
