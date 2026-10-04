# Bounded UI event validation and resumable native checks

This extension adds a narrow timed event-calculus interpretation to explicitly
declared UI behavior. It also lets native validation resume prepared targets
without rerunning model inference. The forty-family inventory, modality minimum
floors, source-fidelity rules, and strict training gate are unchanged.

The preceding owner remains available in
[native DCEC/UI validation v6](native_dcec_interpretation_validation_v6.md).
The independent source-decoder fidelity work is described in
[the conditioning ablation specification](source_conditioning_fidelity_ablation.md).

## Entry points

| Task | Explicit owner |
| --- | --- |
| Prepare source-bound UI targets with optional timed observations | `logic.formalization.autoencoder.ui_source_contract_384_v5.prepare_family_targets` |
| Construct the immutable occurrence declaration | `native_ui_bounded_event_calculus.UIBoundedECInterpretation.from_dict` |
| Parse, lower, and build the actual projection declarations | `native_family_lake_v7.build_native_family_lake` |
| Schedule native jobs using the existing shared resource scheduler | `parallel_projection_checks_v3.run_parallel_projection_checks` |
| Retain attempts and retry only observed pre-lease failures | `resumable_native_validation.run_resumable_native_validation` |
| Apply the unchanged complete-modality gate to live observations | `projection_validation_contract_v7.require_projection_training_batch` |
| Train structural features only after that gate passes | `optimizers.logic_theorem_optimizer.autoencoder_family_training_validated_v7.train_validated_family_projection_autoencoder` |

These are separate versioned owners. There is no implicit conversion of v6
checkpoints or live handles, no change to the 8D linguistic teacher or 384D source
decoder, and no newly learned formula decoder in this extension. All active
projection payloads still participate in the structural objective; an archived
failed target is evidence, not a target silently dropped from loss.

## What the event declaration means

The existing `happens(event,from,to)` UI projection is an untimed edge relation.
It is insufficient for timed event calculus. The new caller must supply all of:

* An exact source text and UI candidate, a bound `UIBehaviorInterpretation`,
  and an explicit frozen Boolean `UIGuardInterpretation`.
* One native `TraceIR` finite prefix with an explicit discrete clock, nonempty
  epoch, unit, positive integral resolution, and an aligned integral origin.
* Between one and sixteen contiguous signed tick observations. Every transition
  identity must be explicitly true or false at every tick. A missing sign is
  unknown and blocks this profile; it is never converted to false.
* The exact single initial control-state fluent and explicit one-hot initial
  interpretation. The profile supports at most thirty-two states and eight
  transitions. These are declared bounds, not pruning rules.
* The complete immutable policy: effects at the next resolution tick, persistence
  unless terminated, at most one transition-qualified occurrence per tick,
  and no simultaneous conflicts, releases, self-loops, or physical timeouts.

Each positive occurrence must have a true frozen guard **and** an active source
state. The owner derives every event × fluent × observed-tick initiation and
termination cell, all signed occurrence cells, and all fluent/time cells. It
checks one-hot state throughout. The future occurrence at the prefix boundary is
unknown; the final derived successor state is known, then later states are
unknown. The UI state and TLA+ projections retain their v4 payloads and exact v4
report binding when emitted through the new owner.

`native_ec_formulas` contains parsed causal rules and signed facts using
`Happens`, `HoldsAt`, `Initiates`, and `Terminates`. Native parse/print/parse is
checked against the full expected AST, including operator positions, symbols,
polarity, binders, and Time coordinates. The finite prefix, symbol tables,
initial-state interpretation, and discrete successor/inertia recurrence complete
the interpretation. The string list alone is not a standalone axiomatization.

Lean evaluates the recurrence, event-enabled conditions, exhaustive effects and
fluent values, plus unknown boundary checks. Only an actual `lake build UIUXIR`
is Lean execution evidence. This checks the supplied bounded interpretation;
it does not authenticate UI events or establish fidelity to natural language.
It does not establish unbounded progress, continuous time, timeout, or arbitrary
event-calculus support.

## Replacing the old blocker without losing evidence

Without `event_interpretation`, the v5 adapter delegates to v4 exactly. With a
complete declaration, only `ui_ux_ir:event_calculus` is replaced by
`ui_ux_ir/explicit_guards/bounded_event_calculus/v1`. The full original row,
including payload, validation failures and hash, remains under
`superseded_bounded_event_observations`, explicitly inactive and linked to its
replacement. Exact source replay verifies this archive as well as every active
row. All other family gaps remain visible.

The bounded EC profile can count toward that family for its supplied fragment
after native validation. This is not complete UI modality qualification. The
authored fixtures in this change still cannot enter strict numerical training.
Fixture success is not a new held-out reconstruction result.

## Durable validation without repeated inference

Construct typed jobs once from the already prepared immutable targets:

```python
from ipfs_datasets_py.logic.formalization.autoencoder import (
    parallel_projection_checks_v3 as checks,
    resumable_native_validation as durable,
)

jobs = [checks.NativeProjectionJob("ui-001", prepared["report"],
                                   prepared["source_inputs"])]
owner = durable.NativeValidationOwner.from_module(checks)
result = durable.run_resumable_native_validation(
    jobs, owner=owner, output_directory=validation_directory,
    resume=False, max_attempts_per_job=3, max_admission_seconds=300,
    retry_backoff_seconds=1, max_workers=2,
    native_memory_mb=1024, native_cpu_slots=2, native_child_process_slots=2,
    lease_wait_timeout_seconds=30, native_step_timeout_seconds=60,
    lake_executable=local_lake, java_executable=local_java,
    tla2tools_jar=local_tla2tools,
)
```

For a subsequent invocation, reconstruct the same known typed inputs, select
the same owner and settings, and pass `resume=True`. There is no arbitrary object
deserializer, model inference callback, or portfolio invocation in this wrapper.
The v2 native owner remains an explicitly supported alternative for old jobs.

The wrapper observes the existing scheduler's acquire calls and delegates every
admission to that same scheduler with unchanged policy and state. A retry requires
an actual scheduler `LeaseTimeoutError`, recorded wait and timeout phases, no
granted lease, and no native job artifact. A matching error string is insufficient.
Parser failures, native failures, post-grant failures, and uncertain interrupted
executions remain terminal or explicitly unknown. Safety checks are not relaxed.

The admission budget is cumulative across restarts and includes preparation,
waiting and backoff inside the wrapper. Remaining time caps a new lease wait.
Already admitted work may finish under the native owner's existing per-step
bound. A job deferred before acquisition is recorded as unstarted; restarting
does not reset its spent admission budget. This is not a hard deadline for the
entire batch or an operating-system limit on aggregate child RSS.

`plan.json` binds exact report/source/review bytes, owner versions and policy,
resource settings and wrapper identity. Atomic, locked manifests retain every
round, artifact hashes, admission phases and pressure observations. An interrupted
in-flight round is not replayed automatically because its execution is uncertain.
Source, report, settings, producer, or evidence drift rejects resume.

`live_jobs` contains only handles issued in the current invocation.
`archived_jobs` contains historical evidence with no restored live handle.
Even a completed archive cannot satisfy the live training gate. Revalidate if
fresh training authority is required; retain the old evidence rather than
mutating it. A partial projection build remains partial regardless of resume.

## Reproduction and evidence

Use a frozen export of the canonical workspace tree with explicit `PYTHONPATH`;
the driver verifies the compiler/decompiler/parser tree pin. Never rely on a bare
import resolving the editable HACC installation. Source exports must be immutable
during validation. Installed Lake, Java, and SANY executable hashes are pinned;
the driver downloads neither tools nor weights.

```bash
python scripts/ops/autoencoder/check_ui_event_validation_resume.py \
  --previous-native-directory /absolute/path/to/native-dcec-ui-20261002/native-r2 \
  --output /absolute/path/to/new-validation

# Same source, inputs, tools and resource settings in a new process:
python scripts/ops/autoencoder/check_ui_event_validation_resume.py \
  --previous-native-directory /absolute/path/to/native-dcec-ui-20261002/native-r2 \
  --output /absolute/path/to/new-validation --resume
```

The driver replays exactly the six previously unfinished prepared reports,
without loading an autoencoder, plus three positive and six negative explicit
EC fixtures. It keeps all attempts, actual build logs, source and tool provenance,
strict-gate probes, wall times and Python RSS scope. Its resume check must return
no live handles for completed historical jobs. This is native projection/resource
evidence; no bridge-on legal-IR evaluation or model convergence is measured.

Completed measurements are in
[the machine-readable result](../implementation/reports/evidence/ui-event-validation-resume-20261002/results.json).
The accompanying evidence archive retains inputs, source producers and every
attempt. Local durable directories retain native build artifacts for resume;
portable evidence archives do not confer live authority.

The final 2026-10-02 run passed 208 tests without skips. Nine native jobs passed
actual Lake builds, including all three positive EC fixtures; six negative EC
fixtures stopped before Lake. The nine-job batch used two workers and finished
in 65.69 seconds including preparation and evidence checks. Its Python peak RSS
was 799,596 KiB; this excludes native children. All nine results remained partial,
and all nine live strict-training probes refused qualification.

A separate controlled-capacity test recorded a real pre-lease timeout, released
the deliberately held capacity, and passed actual Lake on its second attempt
in 11.74 seconds. It retained the real host-pressure sampler and safety rules;
the contention was deliberately induced, not a natural-host performance result.
Its shorter 0.25-second lease wait was specific to that negative control.

Restart of the completed nine-job batch took 5.64 seconds for preparation and
integrity checks, ran no additional build, and returned nine archived records and
zero live handles. The returned manifest and on-disk manifest have the same
verified digest. These times are validation/restart measurements, not legal-IR
bridge-on timings or evidence of improved model reconstruction. The archive also
retains earlier attempts and the driver/receipt defects found before this final
validation.
