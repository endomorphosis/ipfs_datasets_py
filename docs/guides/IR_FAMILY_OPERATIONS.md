# IR Family Operations

Status: reviewed rollout runbook  
Interface: `IRFamilyRollout@1`  
Default stage: `off`

This runbook operates the shared Legal, Security, and Intent IR family and the
learned Intent formalization advisor. It is fail closed: missing, stale,
inconclusive, or mismatched evidence keeps the advisor at `off` or returns it
there. A passing task board, model confidence, retrieval score, evidence gate,
or policy decision is not a proof and cannot authorize a stage transition.

The architecture and gate policy are defined in
`docs/architecture/IR_FAMILY_REFACTOR_AND_INTENT_IR_PLAN.md`. Security legacy
migration is defined in
`docs/security_verification/SECURITY_IR_MIGRATION.md`.

## Roles and separation of duties

| Role | Responsibility | Cannot do alone |
| --- | --- | --- |
| operator | Run preflight, admit a bounded cohort, monitor, and rollback | Approve licenses, proof authority, or promotion |
| data steward | Approve source/license/privacy policy and quarantine disposition | Approve a proof receipt |
| benchmark reviewer | Review split, gold labels, paired metrics, and reproducibility | Waive a hard zero gate |
| security reviewer | Review high-risk semantics, backends, receipts, and incidents | Turn an evidence or policy result into a theorem |
| release owner | Record stage, cohort, budget, expiry, and rollback decision | Self-approve an artifact they produced |

One person may fill multiple roles only where project policy permits it. The
producer and final reviewer of a release-grade promoted artifact must remain
distinct.

## Stage contract

Stages are strictly ordered `off -> shadow -> assist -> canary`. There is no
automatic transition and no implicit general-availability stage.

| Stage | Behavior | Allowed outputs | Forbidden effect |
| --- | --- | --- | --- |
| `off` | Do not load or invoke the learned advisor. Run the deterministic compiler and normal typed backend path only. | Deterministic formalization, diagnostics, obligations, and typed results | Learned candidate generation |
| `shadow` | Run a pinned advisor on a bounded allowlisted copy of input after deterministic compilation. | Audit-only candidate, metrics, diagnostics, and run manifest | Changing canonical IR, consumer responses, proof/policy decisions, or source state |
| `assist` | Show validated bounded candidates to named reviewers. Human acceptance creates a new review artifact. | Candidate and review artifact with parent digests | Direct mutation of canonical artifacts or any proof, trust, license, permission, or execution authority |
| `canary` | Admit only a manifest-bounded allowlisted cohort. Candidates must traverse schema/type checks, source-map checks, deterministic comparison, configured verifiers/provers, and required review. | Typed validated artifacts and receipts within the approved cohort | Unbounded routing, bypassing deterministic controls, or using confidence/retrieval as authority |

Restarting a process does not change its stage. A stage is valid only when the
loaded content-addressed rollout manifest says so, has not expired, and all
parent identities match. Unknown stage values fail to `off`.

## Promotion manifest

Before `shadow`, create an immutable rollout manifest that binds:

- stage, bounded cohort/query selectors, start, expiry, operator, monitoring
  owner, and rollback owner;
- repository tree/commit and the exact validation receipt;
- `SkillCenterSnapshot.snapshot_id`, dataset ID, full immutable dataset
  revision, repository filename, expected byte size, and expected SHA-256;
- source-policy version and reviewed license decision summary;
- Intent schema, ontology, view registry, compiler, configuration, and prompt
  template identities;
- split-manifest digest plus graph and embedding snapshot IDs;
- advisor arm and checkpoint manifest/digest;
- backend ID/version and `BackendCapabilities` digest;
- paired benchmark report digest, thresholds, measured latency/memory/cost,
  and all human approval records;
- parent and output artifact digests.

Do not use timestamps, branch names, `main`, `latest`, directory mtimes, or
filenames as identity. Nondeterministic environment/timing observations belong
in a separate bounded section and do not change deterministic output identity.

## Preflight

Run from the repository root:

```bash
python -m pytest \
  tests/integration/logic/test_ir_compatibility_exports.py \
  tests/integration/logic/test_ir_family_conformance.py \
  tests/integration/logic/test_intent_ir_pipeline.py \
  tests/benchmarks/logic/test_intent_ir_benchmark.py \
  tests/integration/logic/test_ir_rollout_contract.py -q
```

Archive the complete command, selected test population, exit status,
repository tree, and environment/tool versions in the rollout evidence. A
partial or stale test receipt is not a substitute.

### License and hostile-input gate

Every record must have a `SourcePolicyDecision` bound to the exact source
digest and policy version. Only records classified by the human-approved
allowlist as `allow_train_and_publish` may enter training or published
artifacts. `allow_internal_evaluation` stays internal; `metadata_only` cannot
contribute bodies or labels; `quarantined_unknown` and `excluded` do not enter
normalization, retrieval content, training, evaluation truth, or publication.

Unknown, absent, contradictory, unparseable, or policy-version-mismatched
license terms fail closed. Secret/PII, prompt-injection, tool-directive,
unsafe-metadata, generated-binary, and source-anomaly findings remain
quarantined pending a recorded human disposition. Source text and commands are
hostile quoted data: no rollout stage executes, imports, or installs anything
found in a source record.

### Snapshot pinning gate

Materialize input only through `SkillCenterSnapshotCache` with a
`SkillCenterSnapshot` using:

- a full immutable dataset revision, never `main` or another moving ref;
- exact repository filename, expected size, and expected SHA-256;
- verified cache alias and cache bytes;
- read-only immutable SQLite access with `query_only`, extensions disabled,
  schema checks, stable keyset pagination, and resource bounds.

A cache miss in offline operation, stale alias, size/digest mismatch,
unexpected SQLite/schema/row count, or snapshot ID mismatch blocks admission.
Pin GraphRAG, embedding, feature, checkpoint, compiler, and configuration
snapshots independently; one snapshot ID cannot stand in for another.

### Solver capability gate

Registry discovery and `BackendCapabilities` inspection are side-effect free.
They must not import or install an optional solver, start a process, or write a
file. Before executing an obligation, confirm that the selected backend
declares the requested logic family and `QueryKind`, its explicit availability
probe succeeds, its version is approved, and its resource bounds fit the
manifest.

Unsupported or unavailable capability produces a typed unavailable/unsupported
attempt and blocks a required proof. It never falls through to another result
family or becomes manual proof. Only a human-approved backend/version and a
valid `ProofResult`/`ProofReceipt` for `QueryKind.THEOREM_PROOF` may carry
theorem authority. `MonitorResult`, `EvidenceGateResult`, `PolicyDecision`,
retrieval, and learned candidates cannot.

### Source-group split and retrieval gate

Deduplicate before assigning partitions. Build the immutable
`IntentSplitManifest` by connected source families, never random rows. Group
on every available:

- `primary_source_id`;
- source repository and document;
- exact content digest and near-duplicate family;
- declared duplicate family;
- generation prompt/model family;
- source revision/time boundary.

All variants of a family remain in one partition. Evaluation uses the same
held-out example IDs for all arms. Record the split-manifest, graph, and
embedding snapshot identities. `validate_retrieval_partition_fence` must keep
training documents and same-family neighbors out of test, held-out-domain, and
held-out-time/revision retrieval. Any crossing or snapshot mismatch means
`leakage_count > 0` and blocks promotion.

## Benchmark and promotion thresholds

Use the content-addressed
`intent-formalization-benchmark-report/v1` receipt over the complete arm
matrix:

- `deterministic_only`;
- `intent_from_scratch`;
- `legal_encoder_transfer`.

Every arm must use identical held-out examples and the same split, graph, and
embedding snapshots. Select the learned arm before reading final held-out
results. The candidate may advance only when all of the following hold:

| Gate | Threshold |
| --- | --- |
| complete arm matrix and paired population | exact match; no missing or extra example |
| material improvement | at least `+0.02` absolute versus `deterministic_only` in one of `view_accuracy`, `modality_f1`, `control_f1`, `proof_obligation_closure`, `unsupported_recall`, or `round_trip_accuracy` |
| bounded regression | no listed primary metric decreases by more than `0.01` absolute and every primary metric remains at least `0.95` |
| structural validity | `grounding_accuracy == 1.0`, `schema_validity == 1.0`, `type_validity == 1.0`, `round_trip_accuracy == 1.0`, and `semantic_mutation_rate == 0.0` |
| false proof | `false_proof_count == 0` in every arm and aggregate receipt |
| false completion | `false_completion_count == 0` in every arm and aggregate receipt |
| authority boundary | `authority_violation_count == 0` in every arm and aggregate receipt |
| data/retrieval leakage | `leakage_count == 0` in every arm and aggregate receipt |
| reproducibility | deterministic artifact/report digests match on a clean rerun with the same pinned inputs |
| resources | p95 latency, peak memory, and estimated cost are within the human-approved canary budget |

The four zero gates are hard gates. No maintainer, incident process, aggregate
score, latency improvement, or business priority may waive them. The `0.02`
material-improvement and `0.01` regression policy are versioned rollout
defaults; changing them requires human approval before, not after, viewing a
new held-out result and creates a new policy/manifest identity.

## Artifact lifecycle

1. Write bounded generated output to `runs/<run-id>/` under a unique immutable
   run identity. Never write directly to `promoted/`.
2. Recompute all digests, validate schemas/source maps/authority types, scan
   hostile content, and compare the manifest with the loaded pinned inputs.
3. Quarantine malformed, stale, unlicensed, mismatched, or hard-gate-failing
   output. Preserve the reason and parents.
4. Have an independent reviewer approve the exact digests, intended use,
   license/privacy disposition, expiry, and rollback owner.
5. Create a new content-addressed artifact manifest whose parents include the
   run and approval records. Promote by immutable copy; never mutate an
   existing promoted object.
6. Consumers resolve a reviewed manifest digest, not `latest`, `-new`, an
   unmanifested path, or a run directory.

Generated run artifacts, model weights, caches, and transient solver output
remain outside Git unless a separate reviewed task explicitly selects a small
golden fixture. Do not delete or rewrite failed evidence during promotion.

## Stage transitions

### Enter `shadow`

Require Gates 0-4, complete license/snapshot/split/capability preflight, a
pinned rollout manifest, and named monitoring/rollback owners. Shadow output
must prove it did not alter canonical or consumer-visible digests.

### Enter `assist`

Require a safe paired receipt, passing thresholds, clean shadow monitoring,
and recorded data-steward, benchmark-reviewer, security-reviewer, and release
owner approvals. Bind the named reviewers and assisted workflow in the
manifest. An accepted suggestion creates a child review artifact and still
requires normal deterministic and verification gates.

### Enter `canary`

Require all Gate 5 conditions, a bounded allowlisted cohort, duration and
expiry, approved resource budget, backend allowlist, on-call operator, and
tested rollback. Start with the smallest cohort. Expansion is a new human
approval and manifest; a quiet interval is not automatic approval.

## Monitoring and stop conditions

Every run exports bounded counters, rates, digests, and stage/cohort labels for:

- rollout manifest, repository, snapshot/cache, source-policy, split, graph,
  embedding, checkpoint, compiler, configuration, and backend identities;
- accepted, metadata-only, quarantined, excluded, secret/PII, hostile-input,
  and license-policy counts;
- split crossings, retrieval-fence violations, and snapshot mismatches;
- candidate schema/type/source-map rejection and unsupported-semantics counts;
- false proofs, false completions, authority violations, and receipt failures;
- backend unavailable/unsupported/timeout/error/result statuses;
- deterministic/candidate agreement, each benchmark metric, and digest drift;
- p50/p95 latency, peak memory, estimated tokens/compute/cost, queue depth, and
  error rate;
- Security legacy/v1 compatibility and Legal regression failures;
- any attempted source command, tool call, import, installation, secret
  access, or canonical-artifact mutation.

Page the operator and automatically stop new canary admission on any hard-zero
event, source execution attempt, digest/snapshot/split mismatch, unapproved or
expired manifest, proof-receipt integrity failure, required backend loss,
Security/Legal regression, or resource-budget breach. Missing telemetry is a
stop condition, not evidence of zero.

## Rollback and incident response

Rollback is configuration- and manifest-based:

1. atomically route new work to `off`; if control state is unreadable, startup
   defaults to `off`;
2. stop new advisor/canary admission and allow only bounded deterministic
   compilation and already-authorized backend work;
3. revoke the active rollout manifest in the control plane and record time,
   actor, reason, affected cohort, and last accepted artifact;
4. quarantine incomplete candidate/review/promotion artifacts; do not delete,
   overwrite, or relabel them;
5. preserve logs, receipts, counterexamples, snapshot/cache bytes, manifests,
   and digests for incident review;
6. verify deterministic-only health, Security legacy compatibility, and Legal
   regressions before reopening normal work;
7. notify the data steward, security reviewer, release owner, and downstream
   consumers of any promoted digest that is affected;
8. require a new root-cause record, validation receipt, approvals, and rollout
   manifest before returning to `shadow`.

Rollback never removes legacy Security shims or source artifacts, silently
switches snapshots/backends/checkpoints, or interprets an unavailable solver
as success. If the control plane cannot atomically select `off`, stop the
advisor service and fail requests closed while deterministic service is
restored.

## Decisions requiring human approval

Humans must approve:

- license allowlists/exceptions, training/publication use, new source domains
  or bundles, secret/PII policy, quarantine disposition, and retention;
- immutable source-snapshot expansion;
- ontology/view versions and high-risk semantic mappings;
- CID/multicodec identity policy;
- solver/model provisioning or updates and the solver/backend/version
  proof-authority allowlist;
- gold-set reviewers, sampling, corrections, and source-group split;
- learned arm, benchmark receipt/threshold changes, and resource budget;
- every `assist`/`canary` cohort, duration, expiry, expansion, monitoring
  owner, and rollback owner;
- release-grade artifact promotion, incident disposition, and Security
  legacy-path removal.

Automation may enforce these records. It may not manufacture an approval,
approve its own output, or waive a hard zero gate.
