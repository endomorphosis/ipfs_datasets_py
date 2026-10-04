# Intent and UI source fidelity and projection gap repairs

The additive candidate pipeline now requires a generated UI component to agree
with the complete supported source sentence before preparing its logic-family
targets. A valid component with the wrong role or classification stays a failed
prediction. Intent gains a separately checked ground deontic projection. UI
graph declarations preserve more supplied structure, and behavior projections
require an explicit, source-bound native interpretation.

These changes do not retrain an autoencoder, alter existing checkpoints, change
the 8D linguistic lineage, or promote a model. They leave earlier source-pinned
modules intact. The earlier [candidate coverage report](intent_ui_candidate_coverage.md)
describes the previous pipeline; use the v2 entry points below for the new UI
source gate.

## Entry points

All modules below are in
`ipfs_datasets_py.logic.formalization.autoencoder`.

| Module | Public API | Responsibility |
| --- | --- | --- |
| [ui_candidate_fidelity.py](../../ipfs_datasets_py/logic/formalization/autoencoder/ui_candidate_fidelity.py) | `audit_ui_candidate(source_text, candidate)` | Compare the unchanged generated UI component with the bounded whole-source grammar |
| [intent_candidate_fidelity.py](../../ipfs_datasets_py/logic/formalization/autoencoder/intent_candidate_fidelity.py) | `audit_intent_candidate(source_text, candidate)` | Existing complete typed Intent source comparison |
| [intent_ui_candidate_pipeline_v2.py](../../ipfs_datasets_py/logic/formalization/autoencoder/intent_ui_candidate_pipeline_v2.py) | `infer_and_audit(runtime, rows, *, requested_families=None, **inference_options)` | Complete inference before source auditing and family preparation |
| Same pipeline | `audit_candidates(report, source_rows, *, requested_families=None)` | Audit an existing 384D report without another generation pass |
| [intent_source_contract_384.py](../../ipfs_datasets_py/logic/formalization/autoencoder/intent_source_contract_384.py) | `prepare_family_targets`, `qualify_source_candidate`, `validate_prepared` | Preserve existing family targets and add a complete ground DFOL formula when supported |
| [ui_source_contract_384_v3.py](../../ipfs_datasets_py/logic/formalization/autoencoder/ui_source_contract_384_v3.py) | `prepare_family_targets`, `qualify_source_candidate`, `validate_prepared` | Preserve literal graph declarations and explicitly supplied behavior interpretation |
| Same UI adapter | `UIBehaviorInterpretation.from_model(source_text, target, model)` | Bind a complete caller-supplied native behavior model to the exact source and candidate |
| [native_family_lake_v5.py](../../ipfs_datasets_py/logic/formalization/autoencoder/native_family_lake_v5.py) | `build_native_family_lake(...)` | Replay typed family inputs and execute the modality-specific Lake build |

## Generate first, audit second

```python
from ipfs_datasets_py.logic.formalization.autoencoder import (
    intent_ui_candidate_pipeline_v2 as pipeline,
)

# A previously loaded 384D GRU or structured runtime; no reference targets.
rows = [{"id": span_id, "source_text": original_text, "embedding": embedding_384}]
audited = pipeline.infer_and_audit(runtime, rows)
```

Inference inputs have exactly `id`, `source_text`, and `embedding`. Parser
references, targets and repaired candidates are rejected as additional input
fields. The runtime completes before the source parser or projection owner
runs. The returned report retains generated tokens, reconstructed embeddings,
original candidates and unsuccessful rows.

For an existing report, `source_rows` contains exactly `id` and `source_text`.
The pipeline checks the report's 384D identity, source hashes, unique IDs, row
count, `target_access=False`, `teacher_forcing=False`, and false authority flags.
It copies the report. Source disagreement, unsupported source syntax, native
invalidity, or a projection failure prevents family eligibility without hiding
successful siblings.

When a runtime rejected generation and retained only `raw_candidate_ir`, the
pipeline can diagnose that raw value while preserving `candidate_ir=None`.
Even agreement of the raw value cannot override the runtime rejection; its
status remains `native_generation_rejected` and no projection runs.

## The bounded UI source contract

The supported source is this complete authored sentence pair:

```text
Component approve_toggle has role button. Its privacy sensitivity is high and its presentation classification is interactive.
```

The corresponding candidate is:

```json
{
  "kind": "ui_component",
  "document": {
    "component_id": "approve_toggle",
    "role": "button",
    "privacy_sensitivity": "high",
    "presentation_classification": "interactive"
  }
}
```

ASCII spaces, tabs and line breaks can vary. Keywords, identifiers and labels
remain case-sensitive. All four values must be explicit. The grammar accepts
bounded ASCII identifier tokens and uses the existing semantic validator for
native values. Privacy and presentation classifications follow its closed
vocabularies; role validation retains its support for custom stable tokens.
The grammar's narrower token syntax does not claim coverage of every native
role spelling.

Trailing exceptions, additional sentences, paraphrases, omitted classifications,
ambiguous pronouns and full UI specifications remain `source_unsupported`.
No missing field is inferred from neighboring prose or a native default. A
future broader parser needs its own fidelity evidence before expanding this
contract.

The audit reports `native_invalid`, `source_unsupported`,
`source_disagreement`, or `source_agreement`. It retains both native and source
errors when both apply. Complete typed JSON comparison records missing,
additional, differently typed and unequal fields as JSON-pointer differences.
For example, predicting `textbox` yields a mismatch at `/document/role`.
An omitted native optional field remains missing; an extra default-valued field
remains additional. Neither is silently normalized into agreement.

Source text and candidate hashes bind the receipt. Direct producer modules are
checked for loaded-code and on-disk changes before and after auditing, and the
workspace logic tree pin still applies. This direct-owner scope is explicit;
it does not claim a complete transitive call-graph attestation. The audit accepts
no model or checkpoint and does not execute inference, training or Lake.

## What the additional projections mean

The Intent adapter starts from an unchanged rich AST that passed its existing
bounded source agreement check. When its rich native projection supports it,
the adapter reparses a complete ground DFOL formula and compares every modal
operator, branch, predicate, ordered argument, source surface and sort against
the candidate. Obligations, permissions and prohibitions retain their distinct
operators. Guards and Boolean connectives retain their structure. Ordered
actions are not rewritten as Boolean conjunctions to force DFOL coverage.

The supplemental formula is ground: it does not create quantified referents,
clock semantics, observed events, cognitive states, execution preconditions or
norm compliance. Unsupported supplemental DFOL remains an explicit gap while
supported existing projections remain available.

UI v3 retains field presence, parent declarations, child positions and list
lengths, component membership, edge identity/kind/endpoints, explicit slot
labels, reference sets and literal purpose/accessibility strings as ground
declarations. Its reversible symbol table preserves exact typed values.
Recording a purpose string does not interpret that prose; recording a binding
reference does not validate its target. Explicit empty fields are declarations,
not assertions that the modeled world has no other relationships. Count and
position symbols do not introduce an arithmetic ordering theory.

An explicit `UIBehaviorInterpretation` can supply a complete validated native
behavior model for a full UI document. The adapter checks exact source and
candidate hashes, complete field presence, state and transition identities,
endpoints, initial states and supplied event/guard/effect/priority declarations.
It does not derive behavior from a four-field component or invent an event
label from a transition ID. Missing or inconsistent context blocks the route.
Available behavior routes still require their native syntax checks and Lake
build; absent behavior does not earn temporal or event-calculus coverage.

The direct v3 adapter accepts explicit typed full documents and caller-supplied
interpretations without claiming to translate their natural-language source.
The v2 inference pipeline is stricter: its bounded four-field source agreement
gate does not automatically qualify full-document natural-language inputs.

## Coverage and Lake evidence

The default request retains the existing inventory of 40 families. Unsupported
families remain in the denominator. Supplying a shorter `requested_families`
list changes the scope and must be reported. Family eligibility means only that
preparation can proceed; it does not mean all families are covered.

`prepare_family_targets` returns `report`, exact typed `source_inputs`, and a
JSON `audit`. Use `validate_prepared` before passing the unchanged report and
inputs to `native_family_lake_v5.build_native_family_lake`. A compiler result,
formula AST, schema check, decoder agreement or projection report is not a Lean
admit. Only the actual `lake build <Lib>` result supplies Lake evidence, and a
successful build of partial projections does not establish full modality or
source qualification. No Mathlib or downloaded weights are needed here.

## Regression evidence

The focused UI fidelity suite passed **108 tests**. Its canonical cases cover
complete typed comparison, native classification vocabularies, unsupported
whole sources, bounded transports, candidate preservation and producer drift.
This subset is included in the final aggregate suite; do not add its count
to that aggregate as independent tests.

A separate audit rechecked all six preselected, already exposed UI GRU outputs
from the previous native follow-up. **All six are native-valid and their source
sentences are supported; all six disagree with their sources.** There are five
role mismatches, three privacy mismatches and one presentation mismatch across
those six outputs. These are prediction errors, not missing context or source
ambiguity. The receipt retains each original prediction, exact input hashes,
typed mismatch paths and producer pins. It executes no generation or training
and is not a fresh held-out result.

Local evidence lives under
`workspace/test-logs/intent-ui-gap-repair-20261002/`:

- `archived-ui-fidelity-r1.json` and `audit_archived_ui_failures.py` retain the
  six-row diagnosis and reproducible audit.
- `ui-fidelity-tests-r1.xml` and `.log` retain the focused suite.
- Final frozen aggregate suite: **458 passed, zero skipped**, in 23.62 seconds.
  This includes the focused UI tests and the corrected archived-case fixture;
  the earlier focused XML is retained as subset history, not added to this count.
- `native-r1/summary.json` retains all **29 attempts**, including the 12
  pre-build failures. **17 actual Lake builds passed**, all with partial family
  coverage.
- Release evidence: [results](../implementation/reports/evidence/intent-ui-gap-repair-20261002/results.json),
  [manifest](../implementation/reports/evidence/intent-ui-gap-repair-20261002/manifest.json),
  and [archive](../implementation/reports/evidence/intent-ui-gap-repair-20261002/evidence.tar.gz).

The native regression entry point is
[check_intent_ui_gap_repairs.py](../../scripts/ops/autoencoder/check_intent_ui_gap_repairs.py).
It replays the original six fits with their unchanged weights, preserves the
previous sampling plan and all unsuccessful attempts, compares the generated
outputs with their archived values, and invokes the new source/coverage path.
This is a regression check on an exposed panel, not new training convergence or
a new generalization comparison. Timing scopes must distinguish loaded-model
inference, post-inference source auditing, projection preparation and actual
native builds.

### Completed native regression

The run retained all 18 previously selected learned-output attempts and 11
authored fixtures. The unchanged learned predictions produced eight actual
Lake builds and ten source-gate failures: four Intent predictions and six UI
predictions disagreed with their complete supported sources. The authored
fixtures produced nine builds and two pre-build failures: a wrong Intent
modality and an inconsistent UI behavior initial state. None of these failures
was repaired or removed from the denominator.

The run executed `lake build IntentIR` or `lake build UIUXIR` using
`/home/barberb/.elan/toolchains/leanprover--lean4---v4.30.0/bin/lake`.
Every passing build remained partial. In particular:

| Authored case | Prepared families / requested | Native-passing families | Remaining gap |
| --- | --- | --- | --- |
| Rich Intent `if`, negative `if`, `and`, and `or` | 4 / 40 each | 3 each | The new DFOL route passes; the existing DCEC route fails strict independent reparsing |
| UI ordered graph | 2 / 40 | 2 | No behavior is inferred from graph declarations |
| UI state without an interpretation | 2 / 40 | 2 | State wire data alone does not supply a native behavior interpretation |
| UI explicitly declared behavior | 4 / 40 | 4 | Five projections pass; 36 requested families remain unavailable |
| UI timeout frontier | 3 / 40 | 2 | Event calculus remains blocked; 37 families are unavailable and the prepared event-calculus family does not count as passing |

The rich Intent DCEC failure is an open parser-interoperability defect: native
DCEC accepts prefix `implies`, `and`, and `or`, while the independent strict
TDFOL reparser rejects those formulas. A naive infix rewrite changes the AST.
The failed receipts remain visible; this run neither bypasses the independent
checker nor claims that prepared DCEC targets passed it.

The declared UI behavior's five passing projections are FOL, frame logic,
event calculus, the declared-state projection and bounded-state TLA+. The TLA+
route ran the actual SANY parser and its Lake projection build. **It did not run
TLC or establish model-checked behavior.** The timeout fixture retains its
unsupported temporal information and a blocked event-calculus receipt instead
of erasing that information to obtain coverage. The authored recommendation
fixture also retains its unsupported norm and other route diagnostics despite
passing builds for its supported partial projections.

The complete regression took **124.942 seconds**. The Python process peak RSS
was **836,468 KiB**, excluding native child-process RSS. These totals include
regression orchestration and native checks, not training throughput.

### Full public-pipeline replay

All **144 model-row predictions** matched the archived predictions after the
public inference pipeline ran again. Across the two UI GRU checkpoints, all
**43 incorrect outputs out of 48** were blocked by the complete source gate;
the remaining five agreed. The UI ridge checkpoint agreed on **24 / 24**.
Intent agreement remained 3 / 24 and 8 / 24 for the GRU checkpoints and
24 / 24 for the ridge checkpoint. These are replays of exposed results, not
fresh held-out measurements.

| Domain | Runtime / seed | Source agreement / rows | Total seconds | Milliseconds per input span |
| --- | --- | --- | --- | --- |
| Intent | GRU v1 / 3517 | 3 / 24 | 1.204 | 50.174 |
| Intent | GRU v1 / 3518 | 8 / 24 | 2.297 | 95.726 |
| Intent | Structured ridge | 24 / 24 | 6.260 | 260.833 |
| UI | GRU v1 / 3517 | 3 / 24 | 0.863 | 35.964 |
| UI | GRU v1 / 3518 | 2 / 24 | 0.781 | 32.547 |
| UI | Structured ridge | 24 / 24 | 2.477 | 103.224 |

Each timing is one warm loaded-model observation of actual readout, source
auditing and eligible family preparation, excluding embedding production and
Lake. Source failures stop before family preparation, so the successful-work
denominators differ substantially between arms. These figures do not establish
a speed improvement, are not bridge-on evaluation timings, and cannot be
compared directly with decoder-only timings from the earlier report. No new
training, checkpoint selection, promotion or fresh holdout was performed.

No result on this page grants `qualified`, `admitted`, `formalized`,
`roundtrip_ok`, proof authority or execution authority. The Constitution remains
unformalized.
