# Native projection coverage, second version

This version adds faithful lowerings for bounded ProgramIR/Hoare contracts,
Intent declarations and linear workflows, typed UI interfaces and finite event
observations, and bounded equality-state TLA+ models. It extends the strict
[native projection validation](native_projection_validation.md) path. The
historical 8D and 384D autoencoder implementations and their checkpoint formats
are unchanged. These are auxiliary projection heads, not replacements for the
lineages' text decoders.

## Entry points

| Task | Module under `ipfs_datasets_py` | Entry point |
| --- | --- | --- |
| Prepare every native projection | `logic/formalization/autoencoder/family_training_v4.py` | `prepare_family_training_targets_v4` |
| Inspect exact-source Lean preparation | `logic/formalization/autoencoder/native_family_lake_v2.py` | `prepare_native_family_lean` |
| Execute native parsers and modality Lake build | same module | `build_native_family_lake` |
| Check live evidence against the full policy | `logic/formalization/autoencoder/projection_validation_contract_v2.py` | `validate_projection_report`, `evaluate_projection_training_batch` |
| Fit or infer with that gate enforced | `optimizers/logic_theorem_optimizer/autoencoder_family_training_validated_v2.py` | `train_validated_family_projection_autoencoder`, `infer_validated_family_projection_autoencoder` |

Use the v4 target producer, v2 Lake issuer, v2 policy, and v2 trainer together.
Old modules remain available for existing source-bound artifacts. Archived JSON
receipts and handles issued by the older gate cannot authorize this gate.
Training and inference both require fresh, matching live observations. Training
checks source separation, every emitted projection's numerical loss coverage,
and both training and tuning panels before optimization.

All 40 canonical families remain in the applicability inventory. A missing
family requires an explicit source-bound review; existing projections cannot be
waived, and a review cannot waive the modality's required capability floor.
An interpretation that is useful but weaker than its family's floor carries
`capability_floor_eligible: false`. It cannot supply the missing capability.

## Supported semantics and boundaries

**ProgramIR:** a single straight-line function/block with bounded integer and
Boolean syntax supports assignments, return, skip, assert, assume, and reviewed
operators. Assertion failure and a blocked assumption are distinct outcomes.
Paired contracts preserve preconditions, postconditions, old/result expressions,
and read/write frames. The contract is a proposition about the interpreted
program, not an automatically established theorem. Calls, loops, arbitrary CFGs,
heap operations, undefined reads, and opaque effects fail explicitly.

**Intent:** ordered predicate arguments and required/permitted/prohibited
operators remain distinct. Intention binds to its native action actor. Hoare
declarations preserve pre/postconditions and their supplied action relation;
they do not invent executable code. A vacuous contract cannot satisfy the
program capability requirement. The supported workflow is an exact closed
linear control graph with a reviewed terminal self-loop and explicit bound.
An unexecuted action is not asserted as an observed fact. The inherited mixed
goal/action facts and JSON-field Datalog/CHC declarations remain blocked until
their native target classification/semantics are corrected.

**UI:** method input/output schemas become typed records connected to the exact
interface/action/component identity. Declared edges retain their source and
target states and fluent effects; they do not become timed observed events.
Cognitive declarations retain the actor and operator. Finite-prefix traces
preserve their observation policy, clock, rational time, ordering, and unknown
future values. Untimed edges, cognition without event/deontic structure, and
finite observations cannot satisfy stronger event-calculus, DCEC, or temporal
requirements on their own. Ambiguous `before` propositions and unsupported
control structures stay blocked.

**TLA+:** v4 replaces the active old TLA profile with a separate exact bounded
state projection and retains the full superseded artifact and replacement
reason. The old compiler accepts predicate name aliases in the native model but
can miss them when emitting updates; the new producer resolves both names and
IDs. It preserves guards, assignments (including zero/false), write frames,
action labels, typed finite bounds, and the step budget. It emits no source-
undeclared liveness obligation. TLA's specification stuttering is explicit in
the matching Lean trace semantics. This is a bounded interpretation, not an
unbounded verification result or a source-program equivalence proof.
This profile accepts finite typed equality maps and printable ASCII string
symbols; unsupported predicates or symbol encodings fail explicitly.

The reviewed UI state profile also checks the exact state-map, origin/action,
guard/update, frame, event, source-reference, and terminal-state joins. It
retains the default `cancelable` declaration while explicitly recording
`cancellation_execution_modeled: false`; it creates no cancellation edge.
Terminal means no declared outgoing action. Specification stuttering remains
possible, and no completion or deadlock-freedom property is inferred. Empty
event IDs and richer UI controls remain unsupported in this profile.

TLA syntax validation runs the explicitly supplied local SANY installation with
level checking and nonzero error exit codes. It requires a Java 17+ version
probe and matching SANY parse/semantic-processing output, as well as exit code
zero. Java and the JAR are hashed into the live evidence. Missing or failed
SANY blocks that projection even if Lean builds. TLC model checking is not run
by this gate.

## Run and inspect

Use the canonical checkout with explicit `PYTHONPATH`, or an exact reviewed
export with its own Git root. Do not allow the HACC editable install to select
a different parser. For a reproducible run, concurrent source edits require a
new reviewed export and fresh validation; changing a file while it is loaded
invalidates its producer identity.

```bash
PYTHONPATH="$PWD" python scripts/ops/autoencoder/check_native_projection_lake_v2.py \
  --lake /path/to/installed/lean-toolchain/bin/lake \
  --java-executable /path/to/installed/java17/bin/java \
  --tla2tools-jar /path/to/installed/tla2tools.jar \
  --output workspace/test-logs/native-projection-v2-new
```

Supply a native Lake binary, not an Elan shim that might download a toolchain.
Each output directory must be fresh. The runner retains every target, generated
Lean, actual build output, SANY evidence, and per-projection failure. It runs
`lake build IntentIR`, `lake build SecurityIR`, `lake build UIUXIR`, and
`lake build LegalIR`. Inspect parser **and** Lake results and
`batch_validation.strict_training_allowed`; successful formula cases do not
mean the entire source panel passes.

The positive numerical handoff is
`scripts/ops/autoencoder/smoke_validated_projection_training_v2.py`, with the
same tool options and another fresh output directory. It validates three
authored LegalIR sources, trains on two and tunes on one, and exercises gated
inference. Its reconstruction metric measures retained structural features.
Unknown/pruned features remain reported. It is not held-out corpus fidelity,
learned text-to-formula accuracy, or evidence of an improved 8D/384D decoder.

## Meaning of success

Only an actual `lake build <Lib>` supplies Lake execution evidence. These builds
type-check the supported interpretation definitions and contract propositions;
they do not prove a law's truth or the fidelity of text translation. No compile,
vector loss, database row, TLA parse, or interpretation build independently
grants an admission. Qualification/admission/source-fidelity flags remain
false, and the Constitution remains unformalized.

Performance reports must separate target preparation, native syntax/Lake
validation, and numerical optimization. These integration fixtures are not a
bridge-on legal-IR speed benchmark. Reusing targets or sparse/Arrow weight
storage cannot remove a projection or weaken a gate.

## Measured integration results, 2026-10-01

The regression and focused suites passed **375 distinct tests**, including
actual Lake and SANY checks. The final source change was followed by a fresh
42-test TLA/gate run, the full matrix, and the positive training smoke. Earlier
attempts and their source snapshots are retained in the evidence archive.

All **32 named-formula cases** pass. Supported native projection checks increased
from **44/66 to 57/66** on the four authored panels; none of the remaining nine
rows was removed or accepted through a fallback.

| Actual library build | Passed / emitted projections | Preparation + validation + audit seconds | Complete strict panel allowed to train |
| --- | ---: | ---: | --- |
| `IntentIR` | 20 / 23 | 3.956 | No |
| `SecurityIR` | 13 / 16 | 3.192 | No |
| `UIUXIR` | 15 / 16 | 3.368 | No |
| `LegalIR` | 9 / 11 | 6.588 | No |

All three bounded TLA profiles passed actual SANY syntax and level checks.
These timings came from fresh Lake workspaces on a shared host, while focused
tests and the training smoke ran concurrently. The integration fixtures are
not natural-language span throughput or bridge-on autoencoder evaluations.
No weights were downloaded and no external model checker was run.

The positive LegalIR smoke validated 27 projection occurrences over three
authored sources, completed two optimizer steps, and passed gated inference.
Total wall time was **18.059 seconds**: native preparation/Lake took 12.382
seconds, numerical preparation 2.472 seconds, and optimization 0.209 seconds;
the remainder includes live-evidence revalidation and inference. All nine
projection losses were present. The tuning objective remained
`0.001113658980810743` and selected the initializer. This demonstrates the
gated handoff, with **no measured reconstruction improvement**.

The nine remaining projection blockers are:

- Intent: mixed goal/action facts and the two declaration-data Datalog/CHC views
  need corrected native semantic targets.
- Security: heap, separation-logic, and hyperproperty models need dedicated
  faithful lowerings.
- UI: `before` needs explicit occurrence and precedence semantics.
- Legal: opaque condition/exception fields remain unsupported in two ModalIR
  family views.

The matrix also retains missing applicability reviews and unmet capability
requirements. It does not authorize full-domain training merely because its
supported declarations compile. See the
[evidence manifest](../implementation/reports/evidence/native-modality-coverage-20261001/manifest.json)
for hashes, receipts, exact sources, and retained attempts.
