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

`report.py` makes that replay rule executable. A replay must use a distinct run
ID and cold cache namespace, a detached `WorktreeSafetyReceipt` at the pinned
source commit, and source/replay `RunContract` records with the same frozen
configuration. It reparses both case results, validates every stage against the
pinned environment, and compares stable case, route, adapter, backend, input,
output, terminal, kernel, and reconstruction identities. Corruption, stale
environment or source state, same-cache reuse, and backend drift fail closed.

The same module records the complete failure-injection matrix (missing tools,
malformed output, timeout, cancellation, corrupt cache, and backend drift).
Each observation must be classified with the frozen taxonomy, stay within its
recorded time ceiling, affect only its injected case, and account for every
child process. Bounded commands run without a shell in a new process group;
timeout and cancellation terminate and reap the group, and a surviving child
is an immediate `orphaned_child` stop rather than a logical miss.

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

## Worktree and capability preflight

`prepare_isolated_worktree` resolves the requested revision before creating
state, rejects any run root that overlaps the active checkout or shared Git
directory, and creates a detached worktree below the selected `RunPaths`.
The active checkout's HEAD, branch, and complete porcelain status are compared
before and after preparation. The resulting canonical receipt binds the pinned
commit, detached worktree, run state root, no-auto-merge invariant, and every
submodule gitlink recorded in the pinned tree.

`probe_runtime_capabilities` then emits exactly one status-bearing record for
each preregistered runtime: spaCy, SyMAI, llm_router, Hammer solvers, Leanstral,
Lean/Lake, cache, and resource scheduler. Probes are read-only and do not
import optional backends, install providers, make inference calls, or start
services. Secrets are reduced to redaction/presence evidence. A missing probe,
exception, partial configuration, or explicit fallback remains `unavailable`
or `degraded`; `require_capabilities` accepts only the exact fully available
request and never selects a different arm.

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
python -m pytest tests/unit/benchmarks/logic_pipeline/test_capabilities.py -q
python -m pytest tests/integration/benchmarks/logic_pipeline/test_worktree_isolation.py -q
```

## Frozen A0 baseline

`runner.py` validates and measures the exact current effective modal-codec
architecture without enabling experimental stages. The checked-in manifest
pins source revisions and files, protocol and corpus identities, immutable
pilot membership, requested and effective configuration, the observed spaCy
blank-model fallback, and isolated cold/warm run contracts.

Validation is read-only and does not import the production codec:

```bash
python benchmarks/logic_pipeline/runner.py --variant A0 --split pilot --validate-only
```

An operator can execute both cache arms into the manifest's isolated run root
by omitting `--validate-only`, or select a new empty destination with
`--output-root`. Execution emits one strict case result for each of the ten
pilot cases in each requested cache mode. It invokes only the existing
`DeterministicModalLogicCodec.encode` entry point, retains backend failures as
case results, and refuses to overwrite an existing measurement.

## Reviewed corpus

`tests/fixtures/logic_pipeline_benchmark/corpus.jsonl` is the frozen revision-1
ground-truth corpus. It contains ten pilot, ten development, and ten holdout
cases across ten strata. Every case has a stable ID, source digest, expected
class, semantic IR target, provenance, review attestation, and a theorem or
countermodel obligation when its expected class is `proved` or `disproved`.
Ambiguous and unsupported cases instead carry an adjudicated semantic reason.
Two distinct reviewer roles attest every target, and both review and provenance
explicitly prohibit model output from establishing ground truth.

`manifest.json` binds exact JSONL bytes, ordered per-case/source digests,
coverage counts, the frozen protocol revision, and a separate digest over the
reviewed semantic targets. Revision 1 identities are:

```text
corpus_sha256   a2720cee073bfe4221594c5b29d8a4557865f272f4d2c2c3553dfeab74c03509
semantic_sha256 9a1747aac8ab7393147795b7f756318a67f66b6f4eedd6ed368b0337c5e46932
manifest_sha256 58b9122c24e4d9d4cc2ad01c7437dfeb45c80ad2535df769d81a89acbda24a26
```

`load_reviewed_corpus` validates both files before returning deeply immutable
records. It rejects unknown or duplicate fields, noncanonical JSON, absent
splits/classes, invalid review claims, source changes, semantic changes,
reordering, and any byte/content digest mismatch. Importing the package does
not read the fixture.

Run the corpus evidence with:

```bash
python -m pytest tests/unit/benchmarks/logic_pipeline/test_cases.py -q
```

## Provenance-preserving fixture imports

`fixture_import.py` reuses selected repository fixtures without copying their
expected results into a new source of truth. The canonical
`fixture_import_manifest.json` selects nine existing records by exact upstream
path and original identifier: two adjudicated Legal IR ambiguity packets, two
first-order/deontic/modal conformance cases, three positive and negative Hammer
cases, and two negative Leanstral mutation regressions. The set contains five
positive and four negative examples.

Each import binds the complete source-file SHA-256, selected-record SHA-256,
source selector, semantic family/tags, adapter polarity, and an explicit
`existing_fixture` expectation origin. Source paths must stay inside the
repository. Ambiguous selectors, duplicate keys or references, schema drift,
source or record changes, missing family/polarity coverage, and any indication
that a model supplied an expected result invalidate the entire import set.
Returned payloads and indexes are deeply immutable. The frozen manifest
identity is:

```text
93bc8297c84b85a018305edc311c42d0df345978af767e4b93b1e509d974a0fd
```

Loading is explicit and performs no optional backend imports:

```python
from benchmarks.logic_pipeline import load_fixture_imports

fixtures = load_fixture_imports()
```

Run the fixture-import evidence with:

```bash
python -m pytest tests/unit/benchmarks/logic_pipeline/test_fixture_import.py -q
```

## Adversarial and negative proof controls

`adversarial.py` places a deterministic trust boundary in front of improvement
statistics. Its frozen control suite has one independently identified case for
each required class: invalid, contradictory, unsupported, prompt-like, copied,
`sorry`-bearing, and `admit`-bearing. Canonical JSONL records and their manifest
bind order, complete taxonomy coverage, reviewed rationales, per-control
digests, and exact file bytes. The frozen controls and manifest identities are:

```text
controls SHA-256 41cf374ccc4cbf9fd0605ee1156f78d7656b213f3b0cfb9b4bdf3715f599974b
manifest SHA-256 3bd5ef467195f246f66e2ecd07251e1a942608adaba2babd2ad401d01bc0e235
```

`classify_candidate` fails closed on malformed candidate or protected-copy
input. `gate_candidate` makes every classified or declared control ineligible
for a verified improvement, even when an upstream component claims success.
If such a candidate also presents a structurally complete native-kernel claim,
the result is a fatal `INVALID_CONTROL_VERIFIED` safety incident rather than an
eligible success. A benign candidate is eligible only with a claimed and
accepted native-kernel receipt digest; otherwise it remains `not_verified`.

Run the adversarial-control evidence with:

```bash
python -m pytest tests/integration/benchmarks/logic_pipeline/test_adversarial_controls.py -q
```

## Frozen split and holdout integrity

The reviewed corpus is also sealed as three ordered split manifests. Each
manifest binds the corpus-manifest identity, split name, case IDs, case
digests, source digests, and normalized-source digests. The revision-1
identities are:

```text
pilot           a050371dae1248deecfb17f2d9e610124c6e493a1a227ec3c161008891ce1881
development     530860019b164c9750083ec5affd6ae71202b695c8c8042400d0f02488436b74
holdout         c7b969ed19a1248143740068e2853ca6132ba3d65dfeec4133e37fad55dbab4a
split integrity dd68177636a3db87752de54399ed8f066d5fdefe568649d9551bb29a0fb529d0
```

Before the corpus can be used, `validate_split_integrity` rejects exact source
copies, Unicode/case/punctuation-normalized copies, reused source provenance,
and token-trigram near copies across splits. The near-copy Jaccard threshold
is frozen at `0.8`; it is not a tuning parameter. Holdout provenance must state
that the case was not exposed in a prompt. `validate_holdout_prompt_isolation`
additionally screens the actual frozen prompt examples against holdout IDs,
normalized sources, and near-copy fingerprints.

Every holdout use produces a `HoldoutAccessAudit` from a validated
`RunContract`. The receipt binds the frozen corpus and holdout identities,
accessed cases in manifest order, run, variant, split-scoped cold/warm cache,
configuration and selection-input digests, prompt-example fingerprints, and
audit sequence. Construction fails unless prompts, policy, model identities,
and thresholds are frozen and tuning is forbidden. Receipts contain no
timestamps or random values, so equivalent access declarations have identical
canonical SHA-256 identities and can be replayed independently.

Run the split and holdout evidence with:

```bash
python -m pytest tests/unit/benchmarks/logic_pipeline/test_holdout_integrity.py -q
```

## Pilot shortlist phase gate

The pilot/shortlist gate validates the transition between preregistered pilot
work and the still-locked holdout phase:

```bash
python benchmarks/logic_pipeline/report.py --gate pilot-shortlist
```

By default, the command validates
`workspace/benchmarks/hammer-symai-spacy-leanstral/results/pilot-shortlist-v1.json`
against its allowlisted source artifacts. The companion
`docs/performance_snapshots/2026-07-24_pilot_shortlist.json` publishes the
validated result for point-in-time comparison. The result must normalize the
complete pilot coordinate set:

```text
(A0 through A12, plus S1) × 10 frozen pilot cases × (cold, warm) = 280
```

Every coordinate is retained. An unavailable capability or a preregistered
exclusion is explicit typed missingness with null measurements, not a silently
substituted arm, omitted row, logical failure, success, or zero-efficacy
observation. The gate separately validates invalid-control kernel false
positives, infrastructure failures, candidate eligibility, shortlist
membership, frozen selection inputs, and holdout authorization.

A `valid` structural gate does not mean that a candidate has demonstrated
efficacy. In particular, the checked-in pilot receipt records zero observed
invalid-control kernel false positives and no infrastructure failures, while
its unavailable/excluded evidence leaves efficacy null. It therefore has an
empty nonbaseline shortlist and an `incomplete` decision. Holdout remains
unauthorized. This is the intended fail-closed result: the artifacts completely
and honestly describe the available evidence, but do not turn missing
measurements into a safety pass, efficacy claim, or permission to access
holdout.

Before any future holdout authorization, the validator requires the protocol,
corpus and case identities, arm registry, prompts, routing/fallback policy,
backend/model/solver identities, resource and cache policy, and decision
thresholds to be frozen. It rejects missing or duplicate coordinates,
manufactured values, shortlist drift, an eligible S1 diagnostic, an incomplete
decision that claims efficacy, or any holdout authorization unsupported by a
completed shortlist decision.

## Paired holdout phase gate

The holdout phase is validated with:

```bash
python benchmarks/logic_pipeline/report.py --gate holdout
```

The canonical
`workspace/benchmarks/hammer-symai-spacy-leanstral/results/holdout-evaluation-v1.json`
artifact is recomputed from the allowlisted pilot gate and the frozen manifest.
The dated
`docs/performance_snapshots/2026-07-24_holdout_evaluation.json` snapshot
publishes its content-addressed result.

The current result is deliberately `blocked`, not a completed efficacy
evaluation. The pilot gate is incomplete, its nonbaseline shortlist is empty,
and holdout access is unauthorized. A0 is therefore not run alone. The seal
records zero scheduled or observed pairs and no access, result, receipt,
replay, tuning, or promotion state. Safety, quality, latency, resource, and
routing fields remain explicit null missingness; structural validity does not
turn those nulls into zero-cost measurements or a safety pass.

The sealed contract binds the ten ordered holdout identities without loading
their semantic targets, A0 and the exact frozen shortlist, separate cold and
warm modes, identical-manifest pairing, counterbalanced order, frozen resource
limits, independent-native-kernel success authority, and fresh-worktree
replay. A future authorized run must satisfy all of those boundaries. Generic
`execute_ablation` calls reject holdout plans before any filesystem or backend
work so an arbitrary access-log label cannot bypass pilot authorization and
per-contract access audits.
