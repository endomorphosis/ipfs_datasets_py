# Frozen Logic-Pipeline Benchmark Protocol

This directory contains the non-production benchmark for deciding whether
Hammer, SyMAI/SymbolicAI, spaCy, and Leanstral improve the current legal-logic
pipeline. This document is the human-readable preregistration. The normative,
machine-readable record is `DEFAULT_PROTOCOL` in `contracts.py`.

Protocol revision 1 was frozen before pilot results were inspected. Its
canonical SHA-256 digest is:

```text
a12067c4239b9628fde065db3fe10e623148c95a55891a642306e0c90dee8fa3
```

Any change to a hypothesis, arm, metric, threshold, exclusion, trust boundary,
holdout rule, or stop condition creates a new schema/version and digest. A
record bearing this digest may never be edited in place. Pilot results cannot
be used to amend revision 1, and holdout results cannot be used for tuning.

## Decision and hypotheses

Every enabled arm processes the same immutable case IDs and manifest. A missing
capability produces an explicit `unavailable` record for the requested arm; it
never silently falls back to another effective configuration.

- H1: full spaCy improves normalized IR accuracy on difficult syntax.
- H2: SyMAI improves semantic accuracy primarily on ambiguous inputs.
- H3: Hammer improves completion for structured proof obligations.
- H4: Leanstral improves Lean-native completion and bounded repair.
- H5: Hammer-first with Leanstral fallback is safer and cheaper.
- H6: conditional routing retains quality with fewer calls and lower latency.
- H7: apparent gains in unverified “proved” claims disappear under independent
  kernel verification.

Each hypothesis carries the same explicit null: the addition does not improve
paired kernel-verified outcomes enough to justify its latency, resource use,
and operational complexity.

## Paired arms

`A0` is the only baseline. The older planning typo `V00` is not a protocol
identifier. Every other arm is paired against A0 on case, manifest, split, and
cache mode.

| Arm | Frozen configuration | Purpose |
|---|---|---|
| A0 | Exact current effective configuration and revisions | Frozen baseline |
| A1 | Full spaCy; SyMAI and Leanstral off; native proof routes | Deterministic core |
| A2 | A1 plus deterministic Hammer and verified reconstruction | Hammer marginal value |
| A3 | A2 plus Leanstral only after bounded proof failure | Proof cascade |
| A4 | A3 plus ambiguity-gated SyMAI | Conditional stack |
| A5 | A4 with SyMAI always on | SyMAI gate efficiency |
| A6 | A4 with Leanstral before Hammer | Proof ordering |
| A7 | A4 with regex/legal parser instead of spaCy | spaCy marginal value |
| A8 | A4 with forced spaCy blank-model fallback | Full model versus fallback |
| A9 | A4 without Hammer; native then Leanstral | Hammer marginal value |
| A10 | A4 with the pinned learned Hammer selector | Learned selector |
| A11 | A4 with SyMAI/LLM premise ranking | Premise-ranking overlap |
| A12 | SyMAI always; Leanstral first; Hammer always | Duplicated-work stress |
| S1 | Legacy SymbolicAI prediction compared with kernel truth | Safety diagnostic only |

S1 can measure false claims but cannot enter a primary quality comparison or a
shortlist. Requested and effective arm IDs must match. A full-model request
whose model is absent remains that requested arm with status `unavailable`;
substitution with A0, A7, A8, or any other arm is invalid.

## Trust and outcome invariants

spaCy observations, SyMAI semantic hypotheses, external solver verdicts,
Hammer evidence, Leanstral drafts, and legacy router confidence are untrusted
inputs. Only an accepted receipt from the independent native kernel may set
`verified`. A verified record must contain that receipt digest.

An invalid control accepted by the kernel is retained as a safety incident,
never erased or counted as an improvement, and immediately stops the run. The
tolerance is exactly zero. Infrastructure failures and capability exclusions
also retain case records. They are explicit missingness and are never silently
converted to a logical failure, a success, or a poor-result exclusion.

The only paired-statistics exclusions are:

- `capability_unavailable`, when the arm's preregistered capability is absent;
- `fixture_invalid`, established independently of the arm's answer.

Bad answers, kernel rejections, timeouts caused by the evaluated logic path,
and regressions remain in the appropriate denominator.

## Metrics and frozen decision gates

Primary metrics are kernel-verified completion, invalid-control kernel false
positives, normalized IR exact match, deterministic semantic-equivalence
acceptance, and paired verified delta versus A0. Quality metrics cover
ambiguity, premise recall, reconstruction, and fail-closed classification.
Resource metrics cover p95 latency, peak RSS, model calls, and accelerator
minutes. Routing metrics cover unnecessary calls, escalation precision, and
unique kernel-verified wins. Cold and warm measurements are reported
separately.

All percentage-like values below are fractions:

| Gate | Frozen value |
|---|---:|
| Invalid controls verified | 0 |
| Confidence level | 0.95 |
| Lower bound allowed for paired regression interval | -0.01 |
| Hard-case verified gain | at least 0.05 |
| Distance from best quality for efficiency route | at most 0.01 |
| p95 latency or model-use reduction for efficiency route | at least 0.20 |
| A0-solved regression rate | at most 0.01 |
| Unexplained A0-solved regressions | 0 |
| Non-baseline shortlist candidates | at most 4 |

A candidate must have no invalid verification, keep its paired confidence
interval above the regression floor, and either improve hard-case completion
by five points or remain within one point of best while reducing p95 latency or
model use by twenty percent. It must remain within the A0 regression tolerance,
explain every A0 regression, and bind every claimed success to a replayable
kernel receipt. Any unresolved infrastructure failure makes the decision
`incomplete`, not passed or logically failed.

## Cache, holdout, and execution isolation

Each cache namespace binds the benchmark, protocol digest, run ID, requested
arm, split, and `cold`/`warm` mode:

```text
hammer-symai-spacy-leanstral/protocol-v1/run/<run>/
protocol/<digest>/variant/<arm>/split/<split>/cache/<cold-or-warm>
```

Reusing a namespace across any of those dimensions is invalid. The corpus
manifest and effective configuration also have independent SHA-256 identities
in each run contract.

Pilot, development, and holdout IDs and their manifest digest are frozen before
comparison. Shortlisting uses pilot and development only. Before the first
holdout access, prompts, policy, model identities, and thresholds must all be
frozen. Each holdout access has an audit ID; tuning is structurally forbidden.
Successful receipts and sampled failures are replayed in a fresh worktree and
cache namespace. Benchmark code is shadow-only: it cannot auto-merge or promote
production routing.

## Failure and stop policy

`FailureCode` in `contracts.py` is the complete stable taxonomy. In particular,
`benchmark_infrastructure_failure`, `resource_lease_cancellation`,
`out_of_memory`, and `orphaned_child` are infrastructure outcomes rather than
logical misses.

The affected run or arm stops immediately for:

- a verified invalid control or other safety-control failure;
- cache contamination or holdout leakage;
- a corrupt provenance/receipt chain;
- an orphaned child process.

It stops after two consecutive out-of-memory failures or three consecutive
general benchmark-infrastructure failures. These thresholds are part of the
protocol digest. Resource limits, subprocess cancellation, bounded retries,
one shared Leanstral service, distinct model/kernel resource lanes, no
recursive routing, no automatic merge, and no production promotion remain
mandatory safety invariants.

## Records and validation

`ProtocolRecord` validates the protocol payload against its digest.
`RunContract` binds configuration, corpus, cache, and holdout state.
`OutcomeRecord` enforces verification authority and separates logical,
excluded, unavailable, and infrastructure outcomes. `validate_paired_outcomes`
enforces same-case pairing, and `evaluate_candidate_gate` applies the frozen
decision rule.

Run the executable protocol evidence with:

```bash
python -m pytest tests/unit/benchmarks/logic_pipeline/test_contracts.py -q
```
