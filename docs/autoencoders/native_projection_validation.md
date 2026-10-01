# Native projection validation for each modality

For the additive v4 target producer and v2 validation/training APIs, including
ProgramIR, Intent/UI and real SANY coverage, see
[native projection coverage v2](native_projection_coverage_v2.md).
The APIs and measurements below describe the preserved first version.

Use native target preparation, per-projection validation, and the modality's
actual Lake build before treating a training panel as projection-validated.
The older structural feature recipes remain diagnostic. Their reconstruction
loss and generic `DecoderSchema` builds do not establish this stronger gate.

The new APIs are additive. Existing v1/v2 target producers, the historical 8D
linguistic runtime, the 384D runtime, and their saved checkpoint identities are
unchanged. These APIs train auxiliary domain projection heads; they do not
replace either lineage's text decoder or establish source-text fidelity.

## Files and entry points

| Task | Module under `ipfs_datasets_py` | Entry point |
| --- | --- | --- |
| Prepare native targets | `logic/formalization/autoencoder/family_training_v3.py` | `prepare_family_training_targets_v3` |
| Supply explicit formal declarations | `logic/formalization/autoencoder/native_formula_evidence.py` | `NativeFormulaEvidence`, `named_logic_routes` |
| Inspect Lean coverage without running a backend | `logic/formalization/autoencoder/native_family_lake.py` | `prepare_native_family_lean` |
| Execute actual modality validation | same module | `build_native_family_lake` |
| Validate a live build against exact targets | same module | `verify_native_family_lake` |
| Review complete applicability and required coverage | `logic/formalization/autoencoder/projection_validation_contract.py` | `validate_projection_report`, `evaluate_projection_training_batch` |
| Refuse optimization on incomplete evidence | same module | `require_projection_training_batch` |
| Train or infer with the live gate enforced | `optimizers/logic_theorem_optimizer/autoencoder_family_training_validated.py` | `train_validated_family_projection_autoencoder`, `infer_validated_family_projection_autoencoder` |

Each report inventories all 40 canonical logic families. This is an inventory,
not a claim that every family applies to every sentence. An absent family needs
an explicit source-bound applicability review. A present projection cannot be
waived as inapplicable. A narrower `requested_families` list cannot pass the
complete gate. Required modality capabilities are checked across the batch;
individual sources do not need to express every operator.

## New supported declarations

Legal's named floor distinguishes first-order, deontic first-order, temporal
first-order, temporal deontic first-order, cognitive event calculus, deontic
cognitive event calculus, frame logic, and propositional logic. Their native
ASTs must contain the characteristic operators. A first-order predicate called
`K` does not count as knowledge, and a predicate called `G` does not count as an
always operator. The native TDFOL frontend does recognize its real `G` alias;
the gate checks the resulting temporal AST node.

`NativeFormulaEvidence(requirement_id, formula, source_ref)` accepts explicit
formal declarations. Obtain the exact source reference using
`family_training_v3.supplemental_source_ref(domain_id, **source_inputs)`.
Joining a formula to that reference does **not** certify that the formula is a
faithful translation of the source. Nothing fills missing formal targets by
inventing source semantics.

The bounded CEC/DCEC route preserves ground agent-indexed K/B/I, Boolean and
deontic structure, and event-atom spelling and arity. It requires actual
cognition and event atoms, plus deontic structure for DCEC. It does not assert
event-calculus axioms, derive events from prose, or support arbitrary quantified
cognitive formulas. Unsupported forms fail explicitly.

V3 also exposes Security's existing native transition/TLA+ artifact as a
distinct training profile, and accepts explicit source-bound Intent program,
contract, state, transition, and temporal models through their native owners.
Producing a TLA+ artifact does not mean SANY, TLC, or Lean validated it. The
separate TLA+ profile remains blocked at strict validation until its full
lowering and required syntax evidence exist.

V3 also corrects an inherited Legal ModalIR classification error: a temporal
`F` (eventually) could appear in the old deontic view as prohibition `F`.
The replacement views partition by the actual operator family and retain the
complete native formula records. Superseded observations are archived with the
reason for replacement. Opaque conditions and exceptions remain blocked; this
correction does not silently convert them to unqualified formulas.

## What Lake checks

The gate runs `lake build IntentIR`, `lake build SecurityIR`,
`lake build UIUXIR`, or `lake build LegalIR` in a fresh workspace using an
already installed Lean toolchain. It does not import Mathlib or download a
toolchain. Generated definitions preserve the supported native formula
operators, with explicit interpretation parameters for predicates and modal
operators; supported temporal operators use discrete `Nat` traces. Supported
finite state declarations preserve their typed bounds and transition relations.

These builds check those declarations. They do not prove the declared
propositions, validate a learned model's decoded output against prose, establish
event/modal axioms, or formalize the Constitution. All admission, qualification,
and source-semantic flags remain false. Existing legal admission still requires
its own real Lake path and the unchanged success criteria.

Every emitted projection has a result, including unsupported projections.
Building supported declarations does not turn the rest green. Generic JSON
shape encodings, saved receipts, and one representative projection cannot
replace a live, source-replayed per-projection check. A live execution handle
is local to its process; machines must rerun validation rather than trusting a
downloaded JSON flag.

The strict numerical entry takes live training and tuning observations, obtains
their exact native reports, checks source separation, and requires a loss term
for every emitted projection. It rechecks the live evidence before publishing
an artifact and at inference. The numerical model retains the existing four
tensors, per-family loss, calibration and Adam refinement. This first strict
artifact has a distinct schema and does not migrate or resume older checkpoints.
Its vocabulary remains training-only and bounded; unknown or pruned structural
atoms are reported and are not evidence of full formula reconstruction.

## Run the integration matrix

From the canonical repository, select an existing native Lake executable:

```bash
PYTHONPATH="$PWD" python scripts/ops/autoencoder/check_native_projection_lake.py \
  --lake /home/barberb/.elan/toolchains/leanprover--lean4---v4.30.0/bin/lake \
  --output workspace/test-logs/native-projection-check-new
```

The output directory must be new. The runner exercises all projections emitted
by four authored native fixtures and eight supplied formula declarations in
each domain. It saves targets, Lean source, actual build output, per-projection
failures, and the full policy audit. Its exit status checks the 32 named-formula
cases; inspect `batch_validation.strict_training_allowed` separately. A passing
integration case does not imply the whole domain is ready for strict training.

For the positive Lake-to-optimizer integration case, run
`scripts/ops/autoencoder/smoke_validated_projection_training.py` with the same
`--lake` and a separate fresh `--output`. It uses three closed authored LegalIR
declarations, nine projections each, and explicit applicability reviews. Two
sources train and one tunes. This tests the strict gate and numerical handoff;
it is not a held-out reconstruction or legal-corpus quality measurement.

Concurrent source edits invalidate producer provenance. For reproducible
validation, export a reviewed commit plus the exact candidate files to a clean
workspace, initialize its Git root, and run with that tree explicitly pinned.
Record the source hashes and results. Do not switch to the HACC editable install.

## Remaining evidence must stay visible

Unsupported program semantics, richer UI control flow, bounded TLA+ artifacts,
heaps/protocols/hyperproperties, and other owner-specific structures need their
own faithful emitters and tests. A name in the catalog or a related profile is
not support. Improving numerical throughput may reuse prepared targets, sparse
updates, and Arrow data; it cannot remove these projections from validation or
weaken the required floor. Report target preparation, actual Lake validation,
and numerical optimization timings separately.

## Measured integration results, 2026-10-01

The clean source export passed **251 tests**, including real native Lake tests.
The final four-modality matrix passed all **32 named-formula cases**. It also
tested every existing projection emitted for each authored input:

| Library actually built | Passed projections | Emitted projections | Preparation + build + audit wall seconds | Full panel allowed to train |
| --- | ---: | ---: | ---: | --- |
| `IntentIR` | 15 | 23 | 3.220 | No |
| `SecurityIR` | 10 | 16 | 2.853 | No |
| `UIUXIR` | 10 | 16 | 2.882 | No |
| `LegalIR` | 9 | 11 | 6.658 | No |

These were fresh Lake workspaces on a shared host while regression tests and a
separate smoke also ran. They measure validation of authored declarations,
with no bridge evaluation, provers, weights download, or corpus throughput
claim. All 22 incomplete/unsupported projections retain their blocking reasons.

The positive closed LegalIR smoke validated **27 projection occurrences** over
three sources, ran **two optimizer steps**, saved a separate structural head,
and passed gated inference. Total wall time was 16.857 seconds. Its tuning
objective stayed at `0.001113658980810743`; the selected parameters remained the
initializer. This establishes the gated numerical handoff, with no claimed
reconstruction improvement or held-out fidelity gain.

See the checked-in
[evidence manifest](../implementation/reports/evidence/native-modality-projections-20261001/manifest.json)
and archive for inputs, source hashes, generated Lean, actual Lake output,
numerical metrics, and retained superseded attempts.
