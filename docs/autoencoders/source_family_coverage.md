# Source-bound Intent and UI family coverage

The [frozen-projection comparison](projection_freeze_development.md) exposed
missing family coverage in the small Intent and UI reconstruction panel. A
successful decoder reconstruction only reproduces the supplied target. It
cannot add assumptions, intentions, action effects, clocks, or observations
that the source and target never contained.

The canonical catalog contains 40 families to review. It does not say that all
40 apply to every input. The unchanged v7 policy separately requires a minimum
capability floor across each training batch. Missing applicability reviews stay
unresolved, and an inapplicability review cannot waive that floor. Each emitted
projection still needs its parser, supported native lowering, and actual Lake
execution. Saved JSON receipts never reopen a live training gate.

## What the previous samples actually supplied

| Domain | Input | Coverage limitation |
| --- | --- | --- |
| Intent | A required, permitted, or prohibited action | Permission is not intention; a goal is not an asserted assumption; an action without effects supplies no meaningful postcondition |
| UI | Component identity, role, privacy and presentation | No state transitions, Boolean guards, cognitive or normative policy, clock, or signed event history is supplied |

The existing Intent semantic owners already support asserted assumptions,
explicit intended actions, and action contracts. Existing UI owners already
support explicit behavior models, guards, and bounded event-calculus
interpretations. The small post-generation candidate pipeline did not expose
these richer inputs. The new adapters make those contracts reachable without
changing the original model output.

## Explicit source contracts

`intent_source_coverage_384` provides a bounded whole-input grammar for explicit
assumptions, intentions, norms, and action conditions. Its reference document
is constructed for post-generation comparison. An unchanged candidate must
match every field. Preconditions and effects must refer to the exact declared
action. No sequencing, state updates, execution result, or additional source
fact is inferred. Optional finite interpretations remain explicit caller data.
The native Intent schema requires a goal. A standalone assumption therefore
remains unsupported; the adapter cannot invent a goal to satisfy that schema.
Finite effect checks concern the supplied abstract state/update interpretation,
not the behavior of an external implementation or the truth of an event.

`ui_declared_source_fidelity` reads a separately named structured source format.
It contains a complete native UI document and explicit interpretation bodies:
behavior, optional Boolean guards, and optional bounded signed event prefix.
The source document is compared with the complete candidate before projection.
Only provenance-binding hashes are derived; substantive guard values, temporal
conventions, initial state and event signs must already be supplied. A declared
event prefix is not authenticated runtime history.

`intent_ui_candidate_pipeline_v3` retains the existing compact candidate paths
and adds these explicitly selected source contracts. Parsing and source audit
run after inference. They cannot replace an incorrect prediction or fill absent
candidate fields. Missing, conflicting, or unsupported context is retained as
a blocked observation.

The public entry points are:

| Module | Entry points | Purpose |
| --- | --- | --- |
| `intent_source_coverage_384` | `source_target`, `audit_candidate`, `prepare_family_targets`, `validate_prepared` | Author bounded reference labels separately; compare a full candidate; prepare and replay native targets |
| `ui_declared_source_fidelity` | `audit_candidate`, `prepare_family_targets` | Compare the declared complete document and bind its explicit interpretation bodies |
| `intent_ui_candidate_pipeline_v3` | `infer_and_audit`, `audit_candidates` | Keep target-free inference and subsequent source audit separate |
| `family_coverage_frontier` | `diagnose_family_coverage` | Report the exact remaining coverage and evidence gaps |

For example, after generation:

```python
from ipfs_datasets_py.logic.formalization.autoencoder import intent_source_coverage_384 as intent

packet = intent.prepare_family_targets(source_text, predicted_candidate)
# packet["report"] and packet["source_inputs"] go together to the native owner.
# source_target(source_text) is a reference helper, never a replacement prediction.
```

These modules are additive. Existing decoder checkpoints and pinned v1–v7
native owners remain unchanged. They do not introduce a new learned decoder.
Full native documents can exceed the current experimental decoder's 64-token
target ceiling. The coverage smoke counts the complete lexical target and
reports that limitation; it never truncates a target or raises the ceiling.
No semantic embeddings are produced for these new declarations. Their source
length has not been qualified against the semantic encoder's context budget.
Training readiness therefore still requires a reviewed representation within
the existing source and target limits, followed by verified local embeddings
and measured decoder fidelity.

## Diagnosing the remaining work

`family_coverage_frontier.diagnose_family_coverage(report,
native_receipt=receipt)` reports separate categories:

- Missing catalog-family targets and unresolved applicability reviews.
- Missing or ineligible minimum-floor projections.
- Native parser and lowering failures for emitted projections.
- Missing or failed Lake execution observations.
- Named formula fragments and their actual operator evidence.

The diagnostic binds the exact report, source, and fixed policy. It can inspect
an archived receipt but issues no live execution or qualification authority.
The caller must still use the existing native owner and live validation policy
for training admission. Diagnostic context requirements identify what evidence
to retrieve or author; they are not automatically supplied interpretations.

Broad family membership is not evidence for every named fragment. For example,
a ground obligation accepted by a TDFOL parser contains no temporal operator.
Named TDFOL evidence needs deontic and temporal structure, and named DCEC
evidence needs its cognitive, deontic, and event structure. UI role/privacy
labels alone cannot provide those meanings.

## End-to-end validation

`scripts/ops/autoencoder/benchmark_family_coverage_context.py` exercises all
predeclared positive and negative authored fixtures, preserves complete source
and candidate records, and runs eligible reports through the existing parallel
native validator. All 40 families remain requested. The validator runs actual
`lake build IntentIR` or `lake build UIUXIR`, plus the existing SANY check when a
TLA+ projection is present. It retains unsupported projections and strict gate
results rather than interpreting a partial build as complete coverage.

Run it in a frozen canonical workspace export, through the existing resource
reservation guardian:

```bash
python3 scripts/ops/autoencoder/benchmark_family_coverage_context.py \
  --output /absolute/path/to/new-reserved-results
```

The output directory must be new. The CLI uses the installed pinned Lake,
Java, and TLA tools; it downloads nothing. It requests up to two native workers
from the shared scheduler. Each native step and lease wait remains bounded.
Source hashes are checked before and after the run, so concurrent edits to
another checkout cannot change the chosen implementation mid-validation.

This smoke runs no neural inference, model training, embedding generation,
checkpoint loading, or bridge-on evaluation. Its timings measure source and
projection preparation and native validation only. It is authored contract
coverage evidence, not fresh holdout reconstruction or natural-language
qualification.

## Measured coverage on 2026-10-02

The [sealed results](../implementation/reports/evidence/family-coverage-context-20261002/results.json)
retain all 26 authored cases: 11 prepared reports and 15 expected blocked
observations. The frozen regression suite passed 544 tests; four separate
guardian cleanup tests also passed. An independent audit verified the original
sources, candidates, native command inputs, tool hashes, and source manifest.

| Domain | Prepared / blocked | Actual Lake builds passed | SANY checks passed | Supported family union | Batch minimum floor |
| --- | --- | --- | --- | --- | --- |
| Intent | 8 / 7 | 8 `lake build IntentIR` | 7 | 12 of 40 catalog families | Satisfied across these authored cases |
| UI | 3 / 8 | 3 `lake build UIUXIR` | 3 | 4 of 40 catalog families | Missing temporal, TDFOL, and DCEC |

These counts describe emitted and validated projections, not applicability of
every catalog family. TLA+ is an additional validation profile of the state
projection; it does not add another distinct catalog family. SANY checked
syntax; no TLC model checking ran. All strict source and training gates remain
false because complete reviewed coverage has not been established. In
particular, a contract without a finite interpretation retains
`workflow_requires_unique_exact_native_linear_state_projection` even though
its supported subset passes Lake.

The complete smoke took 115.01 seconds with up to two native workers. Maximum
Python parent RSS was 810,640 KiB; this excludes native child memory. Fresh
native job workspaces used the installed toolchain and standard library.
Prepared Intent source/projection cases took 1.25–2.02 seconds each, and UI
cases took 2.36–2.44 seconds each. These are preparation timings, not neural
inference or bridge-on evaluation throughput. There is no matched speed
baseline for this new panel.

Only the existing compact Intent baseline fits the unchanged 64-token decoder
ceiling (31 tokens). All ten newly supported full-document targets exceed it:
224–318 tokens for Intent and 475 for UI, including beginning/end markers.
No model has been trained or qualified on those targets. The next training
step needs a lossless representation within the existing limits, verified
local semantic embeddings, and separate reconstruction measurements. UI also
needs explicit normative, temporal, and cognitive source evidence with
supported interpretations before its remaining floor entries can pass.
