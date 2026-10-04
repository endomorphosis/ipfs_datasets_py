# From retrieved context to executable Legal/UI projections

The [provisional context workflow](provisional_context_workflow.md) now has an
executable handoff. A context bundle can supply explicit, typed slot declarations
to the existing v7 Legal/UI lowerers, followed by all native projection checks
and actual modality Lake builds. Its original source stays unchanged.

The supported path is:

```text
exact source → bounded context retrieval → explicit slot declarations
            → context-bound v7 targets → native syntax + Lake (+ UI SANY)
```

This is conditional interpretation infrastructure. It does not infer the
meaning of arbitrary neighboring prose, authenticate a reviewer, grant
applicability reviews or capability-floor credit, or establish that a statute
or application has the declared policy. The original three negative projections
remain available. The Constitution remains unformalized.

## Public entry points

| Module under `ipfs_datasets_py.logic.formalization` | API | Result |
| --- | --- | --- |
| `context_slot_bindings` | `prepare_context_binding`, `validate_context_binding` | Immutable, replayable `ContextBindingDeclaration` |
| `context_slot_manifests` | `prepare_manifest_binding_proposals` | Exact structured values, missing slots and conflicting alternatives |
| Same | `bind_manifest_proposals` | Cited declarations after replay and an explicit caller review record |
| `autoencoder.context_declaration_bridge` | `prepare_contextual_targets` | Live `PreparedContextualTargets` handle with native inputs, report and context receipt |
| Same | `validate_contextual_targets` | Fresh reconstruction from the original source, index, bundle and bindings |
| Same | `build_contextual_family_lake` | Existing native execution and validation handles, plus a serializable receipt |

No production parser, autoencoder checkpoint, numerical optimizer, database
schema, supervisor queue or Hub upload path is modified. The historical 8D and
384D lineages retain their existing interfaces.

## Two explicit binding modes

`fixture_assumption` must exactly match an assumption already recorded for the
slot in its context bundle. It cannot carry citation or reviewer claims.

`source_cited_declaration` requires one or more exact quotations from candidates
retrieved for that slot, explicit scope/alternative notes, and a caller-supplied
reviewer record. Each citation has:

```json
{"span_id":"policy-span","start_byte":0,"end_byte":29,
 "quote":"An exact source byte excerpt."}
```

Offsets are absolute UTF-8 byte offsets in the original source, not character
offsets in a normalized excerpt. The quote must lie inside the candidate span.
The binding retains native source references, candidate and quote hashes, the
complete slot/projection join, and all prior fixture assumptions. A changed
fixture is marked `superseded_not_discharged`; finding a citation does not prove
the prior assumption or its replacement.

Scope records contain `relation`, `governing_scope`, and
`alternatives_disposition`. Reviewer records contain `reviewer_id`,
`review_method`, and `rationale`. Methods are `caller_declaration`,
`human_review_declared`, or `machine_review_declared`. These are declarations,
not authenticated identities. `source_binding_verified`,
`reviewer_authenticated`, `governing_scope_verified`, and qualification flags
remain false in both modes.

Bindings are bounded inert JSON. Limits include 4 KiB per slot value/quotation,
16 quotations and 16 KiB of quote bytes per binding, bounded depth/node counts,
and 256 KiB per serialized binding. Native code or tactics are never taken
from those values.

## Automatically collect values from structured manifests

The manifest adapter recognizes only this closed format:

```json
{
  "schema": "source-bound-context-slot-manifest/v1",
  "selected_source_ref": {"...": "the complete exact native SourceRef"},
  "scope_note": "The author explicitly declares this policy for that source.",
  "slots": [{
    "slot_id": "legal.temporal_model",
    "sort": "temporal_model",
    "projection_ids": ["legal-ir/modal-family/deontic/v3",
                       "legal-ir/modal-family/temporal/v3"],
    "value": {"temporal_kind":"within_duration","quantity":10,"unit":"day",
              "time_domain":"discrete_nat","lower_inclusive":true,
              "upper_inclusive":true}
  }]
}
```

The SourceRef abbreviation above is explanatory; the real manifest must supply
every exact native field. Manifests can contain several slots or occupy several
retrieved spans. Their whole UTF-8 text must fit the 4 KiB citation bound.
Duplicate JSON keys, foreign sources, changed projection sets, unrecognized
formats and oversized documents cannot silently supply values. Nonfinite JSON
numbers are rejected. Arbitrary prose remains unresolved.

Repeated equal values retain their citations. Different values remain explicit
conflicts, regardless of BM25 score or candidate order. Successful extraction
means there is one declared value per required slot *within this retrieved
bundle*. It establishes neither corpus completeness nor source truth.

```python
proposals = prepare_manifest_binding_proposals(bundle, index=context_index)
bindings = bind_manifest_proposals(
    proposals, bundle=bundle, index=context_index,
    reviewer_record={
        "reviewer_id": "your-context-worker",
        "review_method": "machine_review_declared",
        "rationale": "Exact structured declarations; governing authority unverified.",
    },
)
```

For unstructured retrieved text, a separate interpreter/reviewer must propose
the typed value and quotations through `prepare_context_binding`. This release
does not install a generic natural-language slot resolver.

## Supported projection profiles

Legal requires three slots sharing both original deontic and temporal
projection IDs:

| Slot | Typed declaration |
| --- | --- |
| `legal.temporal_anchor` | Caller evaluation origin, explicit trigger-reference label, and declared origin/trigger association |
| `legal.temporal_model` | Within/minimum duration, integer quantity, day/hour unit, natural-number time and closed boundaries |
| `legal.scope` | Exact norm/body projection IDs, enclosing O/P/F modality, auxiliary-body relationship, activation/exception scope, no independent event fact |

This bridge supports a duration-only Legal pair with matching predicates,
exactly one original formula per partition, and no additional conditions or
exceptions. Other legal profiles remain available through existing APIs; this
bridge rejects them rather than discarding their qualifiers. A trigger label is
retained as a declared association; the existing lowerer still takes an origin
parameter. No trigger occurrence or native AST-containment repair is proved.

UI requires two slots targeting `ui_ux_ir:tdfol`:

| Slot | Typed declaration |
| --- | --- |
| `ui.confirmation_policy` | Every exact action ID, strict sequence order, monotonic natural-number clock, integer maximum age, action/request/token correlation, explicit cancellation and consumption policy |
| `ui.trace_scope` | Finite prefix, caller sequence origin, unknown future, no event attestation or completed-workflow claim |

The existing high-risk, single-confirm profile is required. A weak permission,
double confirmation, destructive policy or consent cannot be silently replaced
by this profile. See the smoke script's `_values` helper for complete runnable
value dictionaries and the existing
[qualifier semantics](legal_ui_qualifier_coverage.md) for supported operators.

## Exact source join, cache identity and execution

Legal context must match both the supplied source text and the native document.
UI must match the entire canonical training-row JSON; a DOM excerpt, similar
sentence, different SourceRef metadata or `source_text` override is rejected.
The context-selected span must cover those exact source bytes in full.

```python
prepared = prepare_contextual_targets(
    domain_id,
    source_inputs=original_inputs,
    context_index=context_index,
    context_bundle=bundle,
    bindings=bindings,
)
checked = build_contextual_family_lake(
    prepared,
    source_inputs=original_inputs,
    context_index=context_index,
    context_bundle=bundle,
    bindings=bindings,
    lake_executable=installed_lake,
    output_directory=fresh_output_directory,
    java_executable=installed_java,
    tla2tools_jar=installed_tla2tools,
)
```

Keep the **original inputs**, without qualifier overrides, for replay. The
wrapper regenerates the typed declarations and targets before and after native
execution. Detached receipts cannot replace its live handles. All 40 catalog
families stay accounted for; every emitted projection remains in the checks.
The unchanged batch gate still reports missing reviews/floors separately.

Use `prepared.to_dict()["contextual_target_sha256"]` for context-dependent
artifact keys. It binds source, index revision/content, bundle, declarations,
producer pins and both native reports. Using only the inner v7 report hash is
insufficient: two declared trigger associations can have the same parameterized
formula while requiring different context provenance. Distributed cache
integration and training-worker scheduling are not enabled by this wrapper.

## Run the integrated smoke

```bash
PYTHONPATH="$PWD" HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
python scripts/ops/autoencoder/smoke_context_projection_handoff.py \
  --output workspace/test-logs/context-handoff-new \
  --lake /path/to/installed/lean-toolchain/bin/lake \
  --java-executable /path/to/installed/java17/bin/java \
  --tla2tools-jar /path/to/installed/tla2tools.jar
```

The smoke retrieves authored manifests for the actual target-source bytes,
then exercises both fixture and cited declarations. It changes UI maximum age
from ten to twelve ticks and checks that the value reaches the native
projection, changes target/cache identity, retains the original negative
controls, and runs LegalIR/UIUXIR Lake plus required SANY. These are authored
integration examples, not sampled federal-law conversions, training epochs or
heldout reconstruction measurements. No weight downloads or context-window
changes are needed.

Hammer/tactician plans remain useful for finding lemmas and reviewing proposed
links. The current hammer Lean reconstruction path invokes Lean directly;
its success cannot replace the required actual Lake execution. No retrieved
prose is registered as a theorem, and no supervisor work is enqueued here.

## Validated handoff: 2026-10-01

The frozen-source smoke used two authored sources and both fixture and cited
variants. It retained the three original blockers and checked all 27 emitted
native projections in each mode: **54 projection checks, four successful actual
`lake build LegalIR`/`lake build UIUXIR` executions, and two successful UI SANY
syntax/semantic-processing checks**. SANY was not a model-checking run.
The complete integration took **26.978 seconds**; this is an integration-test
wall time, not a corpus conversion or bridge-on autoencoder benchmark.

The combined context, retrieval, binding, manifest and bridge suite passed
**148 tests in 23.012 seconds**, without skips. Exact source identity, quotation
offsets, conflicting values, incomplete declarations, stale context, unsupported
inputs and detached-handle replay have negative coverage. The UI manifest's
changed maximum age (10 to 12 ticks) reached the native projection, and both
domains changed their context-dependent target keys when their declarations
changed.

All four interpreted variants kept `training_allowed: false`. Their conditional
native executions do not resolve the original source semantics, supply missing
applicability reviews, grant capability-floor credit or admit a corpus span.
Full-catalog native receipts remain `partial`: families without emitted
projections are still listed as missing, rather than silently excluded.
No training, holdout evaluation, weight download or supervisor execution ran.
See the [results and evidence manifest](../implementation/reports/evidence/context-projection-handoff-20261001/results.json)
for raw receipts, exact source snapshots, generated Lean and test attempts.
