# Captured CodebaseIR feature training

`codebase_ir/codebase_feature_v1` trains an eight-dimensional numerical candidate
from a bounded cohort of captured Python integer-offset functions and explicit
contracts. The current-source owner observes the repository head, prepares exact
replayable targets, runs the CPU trainer in an isolated process, and registers an
immutable candidate in the existing autoencoder registry. Resource admission and
process limits apply by default through this owner API.

This is a feature-reconstruction objective for the closed
`python-integer-offset@1` profile. It does not learn a general source-to-logic
translator, generate formulas, run proof solvers, discharge IntentIR obligations,
or promote a model. Its reports retain false behavior, execution, completion,
qualification, and promotion authority fields. The separately dispatched
`source_bound_feature_v1` runtime is outside the scope of this document and its
qualification record.

## Source, target, and model identities

The [target adapter](../../ipfs_datasets_py/logic/formalization/autoencoder/codebase_targets.py)
exports:

```python
prepare_codebase_targets(source: bytes, contract: IntegerOffsetContract,
                         *, revision: str) -> DomainTargetEnvelope
validate_codebase_targets(target: DomainTargetEnvelope) -> DomainTargetEnvelope
```

It uses the existing checked source-to-VC/SMT compilation path for a single
supported function per file. Captured ASCII source is limited to 64 KiB; guards,
calls, extra statements, and unsupported syntax fail closed. The compiled
mathematical model assumes an exact built-in integer argument, direct sequential
invocation, and unbounded integer arithmetic. Source annotations do not enforce
these assumptions; runtime allocation failures and module-loading behavior remain
outside the model.

Each envelope contains one `program` logic-family projection:

| Identity | Value |
| --- | --- |
| Domain | `codebase_ir` |
| Runtime | `codebase_feature_v1` |
| Target profile | `codebase-integer-offset-features@1` |
| Projection | `codebase-integer-offset-smt@1` |
| Representation | `ordered_typed_smt_obligation` |

The feature expression retains the ordered, typed source-body assumption and
requested contract goal, including literal values and operators. Parameter and
result symbols use normalized roles. Paths, spans, source bytes, and revisions
remain in the replay evidence rather than the numerical vocabulary. A requested
goal can differ from the captured function body; preparing that target does not
claim the goal holds.

Validation recompiles the captured bytes and compares the complete canonical
envelope, including native artifacts, source CID, raw-byte SHA-256, contract,
revision, producer identities, and authority fields. A digest or a caller's
`passed` flag alone is insufficient. Targets are bounded to 256 KiB each and do
not require executing repository code or launching a solver.

The [runtime registry](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_runtime_registry.py)
exposes `build_codebase_feature_runtime(training_targets, latent_width=8)` and
explicit `open_runtime`/`load_version` dispatch. The feature basis is fitted only
from training targets. Model state includes weights, Adam moments and steps, and
the bound feature/implementation identities; loading or inference does not fit
the model. No generic native-domain or 384-dimensional capability is implied.

## Train against a current repository head

First create a current catalog-backed `RepositoryCodebaseIndex` and obtain an
exact `CodebaseHead` using the
[structural foundation API](CODEBASE_IR_FOUNDATION.md). The head identifies the
repository view, captured snapshot, and structural generation. The trainer
requires it explicitly and refuses a stale live checkout or superseded head.

The owner API is in
[codebase_feature_training.py](../../ipfs_datasets_py/logic/software_contracts/codebase_feature_training.py):

```python
from pathlib import Path

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.logic.software_contracts.codebase_integer_profile import (
    IntegerOffsetContract,
)
from ipfs_datasets_py.logic.software_contracts.codebase_feature_training import (
    CodebaseFeatureSample,
    train_current_codebase_features,
)

# index, repository, and head come from prepare_current for this repository view.
# These files must already be present in that captured head. Each contains one
# supported function with the named parameter and the indicated integer offset.
samples = [
    CodebaseFeatureSample("training", IntegerOffsetContract("counter.py", "increment", "n", 1)),
    CodebaseFeatureSample("training", IntegerOffsetContract("second.py", "second", "n", 2)),
    CodebaseFeatureSample("tuning", IntegerOffsetContract("tune.py", "tune", "n", 1)),
    CodebaseFeatureSample("canary", IntegerOffsetContract("canary.py", "canary", "n", 2)),
]
cache = Path("/absolute/path/outside-the-repository/model-cache")
with AutoencoderRegistry(
    cache / "models.duckdb", cache / "artifacts",
    max_artifact_bytes=16 * 1024 * 1024,
) as registry:
    result = train_current_codebase_features(
        index, repository, expected_head=head,
        registry=registry, directory=cache / "candidate-001", samples=samples,
    )
    if result["status"] == "candidate_registered":
        candidate_id = result["candidate"]["version_id"]
```

Keep model artifacts and staging outside the repository under examination. The
staging directory must be new. Use a separate model-registry database: its
existing native owner and immutable artifact store remain the authority for
numerical versions; the structural catalog remains the authority for source
heads. This route does not add numerical-weight blobs to the source CAS or a
competing model-version table to the structural database.

The function accepts `parent_version_id`, `scheduler` or `parent_lease`,
`cancel_event`, `epochs`, `learning_rate`, `seed`, `timeout_seconds`,
`admission_timeout_seconds`, and `memory_mb`. Without an injected scheduler or
parent lease, it uses the shared datasets scheduler. An injected parent must be
a real datasets resource lease; the caller retains ownership of that parent.

## Frozen basis and durable split history

Every cohort has nonempty `training`, `tuning`, and `canary` roles. The owner
records exact source and contract bindings, full replayable targets, the source
head, numerical parent, feature-basis hash, and split policy under
`report.codebase_cohort` (`codebase-feature-cohort@1`). Its commitment is stored
with the existing immutable numerical candidate.

To continue training, supply the registered `parent_version_id`, a fresh staging
directory, and the current structural head. Resume preserves the parent's basis
and exact numerical state, including Adam state; it does not silently start a
new optimizer. Training sources may change or new training paths may be added
within the bounds. Tuning and canary paths, contracts, and captured bytes must
remain fixed. The owner reuses their original target envelopes, including the
original revision, even after a new source snapshot is published.

Split history tracks both the stable repository-relative path and raw source
SHA-256 across every ancestor. Renaming the function at the same path cannot
move that unit to another role. Identical bytes copied to a different path also
cannot cross roles. Current duplicate paths or bytes are refused. This detects
these exact identity leaks, not every semantic clone or edited copy at a new
path. Resume checks the full bounded ancestry, including every ancestor's
training/tuning report hashes, parent artifact/state commitments, role ledger,
and fixed held-out envelopes. A recomputed cohort hash cannot erase earlier
roles.

The numerical feature representation can discard unseen atoms, causing different
unseen literals to produce identical vectors. The owner therefore rejects
unknown atoms in **every role**, before launching numerical work. The worker
repeats this check. Tuning and canary data never expand the training vocabulary.
New atoms require an explicit new basis/variant and lineage; this API does not
automatically migrate a basis. Low-level runtime inference instead exposes
coverage and `feature_coverage_complete`, and never promises semantic
discrimination from a distance between vectors.

## Tuning and canary gates

The numerical trainer uses tuning targets for candidate selection. After fitting,
the worker measures reconstruction mean-squared error on the fixed canary cohort.
The first candidate establishes an `initial_baseline`; it has no parent against
which to claim improvement. A continuation uses `parent_nonregression` and is
registered only if each projection's canary error is at most the parent's error
plus `1e-12`. Otherwise the owner returns `candidate_rejected` with no candidate
registration.

Both cohorts are reused for selection or acceptance across generations. They are
not an untouched final test set, and these gates do not establish generalization
or source behavior. No accepted candidate is automatically promoted to a model
head, a planner fact, or a proof result.

## Default resource and process bounds

The owner requires the native Linux process guard, trusted installed Python and
Torch, and the installed `prlimit` helper. It reserves resources before source
work and invokes the
[numerical worker](../../ipfs_datasets_py/logic/software_contracts/codebase_feature_worker.py)
in an isolated CPU subprocess. The worker receives inert captured targets and
state; it does not import repository-under-test modules. It sets Torch intra-op
and inter-op thread counts to one inside that subprocess and hides GPU devices.

| Bound | Owner route |
| --- | --- |
| Latent width | Fixed at 8 |
| Targets | 3–32 total; 1–16 in each role |
| Feature columns | At most 512 |
| Model ancestry | At most 32 generations and 128 ancestral role bindings |
| Epochs | Default 2; allowed 1–8 |
| Learning rate / seed | Default `0.02` / `1729`; rate in `(0, 0.1]` |
| Overall deadline | Default 120 seconds; at most 300 seconds |
| Admission wait | Default 30 seconds, bounded by remaining overall deadline |
| Numerical fitting budget | At most 120 seconds and remaining deadline |
| Root reservation | Default 2048 MiB, one CPU slot and one process slot; configurable to 8192 MiB |
| Worker RSS guard | Root reservation minus 512 MiB; default 1536 MiB, sampled every 100 ms |
| Worker address-space limit | 16 GiB |
| Worker request / response | Each at most 16 MiB |
| Worker temporary workspace | At most 64 MiB and 8 output files |
| Owner parent artifact read | At most 16 MiB |

The shared scheduler considers system pressure at admission and backs off rather
than admitting work when resources are unavailable. Admission has a deadline;
lease cancellation is propagated to the bounded runner. The runner enforces the
worker deadline and process limits, terminates the process group on cancellation
or failure, and cleans its temporary workspace.

The root reservation is cooperative resource accounting, not a hard memory limit
on the whole owning application. The worker's 16 GiB virtual-address-space limit
allows native libraries to map their runtime; it is separate from the sampled
1536 MiB default resident-memory guard. Sampling can overshoot between checks.
Caller activity, owner-side Python allocation, and existing structural SQL reads
are not covered by a blanket whole-system OOM guarantee. In particular, inherited
AST catalog row-count bounds do not make arbitrary hostile SQL values universally
byte-bounded. Configure the underlying DuckDB owner appropriately as described
in the foundation document.

Worker memory observations in the report describe that worker process after
training and before response serialization. They are not the entire owner's
peak RSS or a full lifetime measurement of every descendant.

## Publication, failure, and low-level APIs

The owner observes the source before target preparation, after worker completion,
and after candidate registration or rejection. It also checks deadline,
cancellation, and installed implementation identities. These are point-in-time
observations: they cannot freeze subsequent checkout changes. If source drift or
cancellation occurs after a registry commit, an immutable historical candidate
can remain registered while successful current-source delivery is withheld.
There is no cross-database atomic transaction between model registration and the
source head, and this path neither changes that head nor promotes a model head.

The low-level `CodebaseFeatureRuntime.train` interface accepts trusted replayable
targets and runs the cooperative numerical backend directly. It does not acquire
the owner resource budget, observe live source, or enforce the owner's split
history. `register_candidate_result` can register a trusted worker's returned
state/report without retraining; it checks numerical identity, not the
authenticity of an arbitrary producer. Use `train_current_codebase_features` for
the default resource isolation, source checks, fixed-role lineage, and canary gate
described here. Explicit `load_version(..., domain="codebase_ir",
version="codebase_feature_v1")` preserves cohort metadata for inspection but does
not assert that a historical model matches the current checkout.

## Qualification

The qualification record is
[workspace/codebase-feature-qualification-20261002/qualification.md](../../workspace/codebase-feature-qualification-20261002/qualification.md).
It records the actual native environment, focused tests, and benchmark observations;
this document does not claim coverage of other runtime profiles.

Relevant executable checks include the target adapter and runtime unit suites,
the current-source training integration suite, worker limit and cancellation
tests, and
[ancestor-forgery regressions](../../tests/integration/logic/software_contracts/test_codebase_feature_lineage.py).
Those lineage regressions create real registry artifacts after one native initial
fit and verify refusal of altered historical roles, source bindings, omitted
ancestors, and numerical-report commitments.
