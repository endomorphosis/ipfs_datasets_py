# Native semantic projections and gated training, version 3

This additive release extends [native coverage v2](native_projection_coverage_v2.md)
with finite-heap and two-trace Security interpretations, role-aware Intent
targets, and optional explicit interpretations for Legal and UI qualifiers.
Use these entry points together:

| Task | Module under `ipfs_datasets_py` | Function |
| --- | --- | --- |
| Prepare targets | `logic/formalization/autoencoder/family_training_v5.py` | `prepare_family_training_targets_v5` |
| Prepare or execute native checks | `logic/formalization/autoencoder/native_family_lake_v3.py` | `prepare_native_family_lean`, `build_native_family_lake` |
| Validate a live execution and its policy | `logic/formalization/autoencoder/projection_validation_contract_v3.py` | `validate_projection_report`, `evaluate_projection_training_batch` |
| Train or infer with live gates | `optimizers/logic_theorem_optimizer/autoencoder_family_training_validated_v3.py` | `train_validated_family_projection_autoencoder`, `infer_validated_family_projection_autoencoder` |

Older versioned producers and their source-bound artifacts remain unchanged.
The trainer fits auxiliary structural projection features; it does not replace
or train the historical 8D linguistic decoder or the 384D text/formula decoder.
The three-source demonstrations below are authored integration fixtures. Their
tuning loss is not corpus holdout fidelity or evidence of better legal translation.

## What the new interpretations mean

**Security heaps:** `native_security_lean.py` interprets the exact native heap
model as a finite partial heap. It supports `emp`, typed integer/Boolean
points-to values, and separating conjunction with existential disjoint heap
splits. Address interpretation need not be injective: two location names do
not invent a nonaliasing guarantee. Full exclusive permissions are supported;
fractional permissions, ownership extensions, opaque predicates and unsupported
quantifiers fail explicitly. Empty heap descriptions cannot supply the stronger
capability floor.

**Security noninterference:** the same module preserves the canonical supplied
two-trace low-equivalence/observation-equivalence implication over aggregate
execution views. Native trace/pair limits remain sampling budgets. This does
not invent step-indexed HyperLTL, temporal execution or exhaustive verification.
It is therefore marked `capability_floor_eligible: false` and cannot supply a
stronger temporal hyperproperty capability. Independent named formulas and other required native
capabilities still have to pass.

**Intent roles:** `intent_semantic_training_views.py` replaces the old mixed
goal/action facts and declaration-field Datalog/CHC targets. An asserted
assumption becomes a first-order proposition. Required, permitted and prohibited
statements retain their modal operators. A uniquely actor-bound asserted goal
is an intention. An action declaration and its joined preconditions, effects
and postconditions stay in a Hoare contract, not in observed execution facts.
Unsupported or unjoined roles remain active blockers. Rich atomic Intent input
uses the existing exact native owner; there is no heuristic text fallback.

The new Datalog and CHC profiles contain ground semantic atoms with exhaustive
typed-formula bindings. Native rule parsing and lossless CHC lowering are
checked. The Lean definitions state program satisfaction; they do not prove
that a goal was achieved or that declared facts are true. Modal-only rule views
cannot satisfy a stronger rule capability floor. Superseded original targets
and statement/action accounting remain in the report for audit.

**Legal and UI qualifiers:** `native_qualified_lean.py` accepts an immutable
`ExplicitProjectionInterpretation` supplied by the caller. Opaque source text
remains blocked when no declaration is supplied. The API does not infer the
missing interpretation. Every declaration binds the whole source reference,
original projection ID, original source digest, payload digest and the complete
ordered set of formula digests. Foreign, partial, duplicate or stale bindings
are rejected.

The supported Legal declaration fixes a discrete natural-number day/hour clock,
a caller-supplied evaluation origin, closed interval boundaries, exact duration
kind/quantity/unit, and typed exceptions with activation-time waiver semantics.
The UI declaration fixes strict prior confirmation for each invocation, or
prohibition of an unconfirmed invocation, correlated by action ID. Confirmation
freshness, token consumption and cancellation are explicitly unmodeled. An
atomic `weaken_norm` prohibition retains its atom and modality. All these
caller interpretations are ineligible for the named capability floor and make
no claim that the caller's choice is the correct meaning of arbitrary prose.

## Supplying an explicit interpretation

First prepare a v4 report from the exact intended source inputs, including any
supplied native formulas. Construct `ExplicitProjectionInterpretation.from_dict`
using its original row identity/digests, `supplemental_source_ref`, and the
schema described in `native_qualified_lean.py`. Then pass the immutable object
through `qualified_inputs` to v5. Keep the same objects in the `source_inputs`
dictionary supplied to `build_native_family_lake`.

See the closed examples in
`optimizers/logic_theorem_optimizer/authored_semantic_projection_panel.py` for
complete Legal and UI declarations. That module deliberately accepts only its
three authored fixtures; it is not a policy generator for new text.

The report retains `explicit_interpretation_inputs`,
`superseded_qualified_observations`, `superseded_intent_observations`, and
`intent_semantic_replacement_accounting`. Archived observations are not active
training rows. Replaying a report without the originally supplied interpretation
objects fails; a caller cannot authorize training by copying embedded report JSON.

## Full validation and numerical handoff

Both training and inference require live v3 execution handles from the exact
current source tree and report. A serialized receipt, old-version handle,
schema-only build or partial successful build cannot replace them. All active
projections must pass their native checks and the modality-specific build.
Every emitted projection needs a numerical loss term. All 40 families remain
in the applicability inventory; missing families require source-bound review,
and neither review nor a narrower request can waive a modality's capability floor.

Run from the pinned canonical tree, or a reviewed export with its own Git root
and explicit `PYTHONPATH`. A HACC-first import is a different runtime. Concurrent
source changes invalidate loaded producers and require a fresh reviewed export.
Use existing native tool binaries; these runners do not download tools or weights.

```bash
PYTHONPATH="$PWD" python scripts/ops/autoencoder/check_native_projection_lake_v3.py \
  --lake /path/to/installed/lean-toolchain/bin/lake \
  --java-executable /path/to/installed/java17/bin/java \
  --tla2tools-jar /path/to/installed/tla2tools.jar \
  --output workspace/test-logs/native-semantic-matrix-new

PYTHONPATH="$PWD" python scripts/ops/autoencoder/smoke_semantic_projection_training.py \
  --lake /path/to/installed/lean-toolchain/bin/lake \
  --java-executable /path/to/installed/java17/bin/java \
  --tla2tools-jar /path/to/installed/tla2tools.jar \
  --output workspace/test-logs/native-semantic-training-new
```

Output directories must be fresh. The first command exposes default blockers;
it supplies no qualified interpretations. The second uses explicit authored
interpretations where needed and three separate sources per modality, with two
training sources and one tuning source. It performs two optimizer steps and
gated inference, retaining every target, generated Lean declaration, tool output,
applicability review, gate report, checkpoint and per-projection numerical loss.
It continues across modalities after a failure and exits nonzero if any fails.

The native commands are `lake build IntentIR`, `lake build SecurityIR`,
`lake build UIUXIR` and `lake build LegalIR`. TLA profiles additionally require
actual SANY parse and level checks. These builds check interpretation definitions
and contract propositions, not the truth or source fidelity of laws. No compile,
decompilation, loss, database row, or successful interpretation build independently
grants an admission. Qualification, source-fidelity and admission flags remain
false; the Constitution remains unformalized.

Measure target preparation, native validation and numerical training separately.
The fixture runs are not legal-span or bridge-on autoencoder throughput benchmarks.
No projection may be omitted to claim a speed improvement.

## Measured results, 2026-10-01

The focused suites passed **116 distinct tests**, including real Lake semantic
examples and rejection of false heap/noninterference/goal-compliance proofs.
One native-clock test initially skipped without its explicit executable setting;
it subsequently passed with the installed Lake executable. The complete default
matrix passed all 32 named-formula cases and all three bounded TLA SANY checks.
Supported active native projection checks increased from **57/66 to 63/66**;
the old Intent declaration views are retained as superseded observations.

| Library | Default supported / emitted | Preparation + validation + audit seconds |
| --- | ---: | ---: |
| `IntentIR` | 23 / 23 | 4.656 |
| `SecurityIR` | 16 / 16 | 3.397 |
| `UIUXIR` | 15 / 16 | 3.498 |
| `LegalIR` | 9 / 11 | 6.621 |

The default matrix still blocks all four complete training panels: absent
applicability reviews, unmet capability requirements and the three remaining
opaque Legal/UI targets stay visible. A successful library build does not
override those blockers.

The separate positive smoke supplied reviewed, authored qualifier declarations
and closed-fixture applicability reviews. All **198 projection occurrences**
across 12 sources passed native checks, with 12 actual modality Lake builds and
nine SANY checks. Every domain passed training and tuning gates, completed two
optimizer steps, and passed gated inference with a loss for every active
projection. Total smoke wall time was **69.720 seconds**.

| Domain | Projection count per source | Complete smoke seconds | Tuning objective before → selected |
| --- | ---: | ---: | --- |
| Intent | 23 | 19.242 | 0.000682396449 → 0.000682358750 |
| Security | 16 | 14.786 | 0.001087194936 → unchanged |
| UI/UX | 16 | 15.350 | 0.000671655356 → unchanged |
| Legal | 11 | 20.325 | 0.001027059375 → 0.001027024956 |

The tiny Intent/Legal changes came from decoder calibration; no optimizer epoch
was selected. These are structural tuning measurements on authored sources with
repeated supplied formulas. They establish the gated numerical handoff, not
better holdout reconstruction or improved 8D/384D source decoders. Native builds
used fresh workspaces on a shared host while tests ran concurrently. No weights
or tools were downloaded, and no external model checker ran.

The initial authored Intent fixture had an explicit action precondition. Its
native state producer reports
`action_preconditions_have_no_reviewed_state_binding`, so its workflow remains
blocked. The positive smoke uses a different, explicit effect-only action
contract and a separate assumption; it does not claim to solve that precondition
case. A regression retains and checks the unsupported case. Richer heap,
ownership, hyperproperty, control-flow and qualifier semantics remain outside
these bounded profiles and continue to fail explicitly.

The [evidence manifest](../implementation/reports/evidence/native-semantic-projections-20261001/manifest.json)
contains hashes, raw native checks, training artifacts, source snapshots and
failed attempts. Results are also summarized in
[results.json](../implementation/reports/evidence/native-semantic-projections-20261001/results.json).
