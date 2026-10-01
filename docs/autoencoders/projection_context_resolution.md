# Resolving missing context and semantics in native projections

The three remaining default blockers are **three projections of two authored
fixtures**, not three sampled federal-law passages. They identify real gaps in
the framework, but do not establish a corpus failure rate, a parser regression,
or intrinsically unresolvable legal language. This analysis uses committed
`6bd6eaabd2d3dde46e664b7386efb134253eb928`, with a separate frozen export for
reproduction. Concurrent unpublished source/contract implementations are not
treated as shipped APIs.

## What the inputs actually contain

| Source | Blocked projection | Observed cause | What additional evidence would help |
| --- | --- | --- | --- |
| `legal_ir:pair:0:2:0`: `custodian must publish record within 10 days.` | `legal-ir/modal-family/deontic/v3` | The obligation has a raw condition string, with no typed attachment to a deadline and its trigger | A source-supported trigger, temporal model and scoped norm body |
| Same Legal source | `legal-ir/modal-family/temporal/v3` | A separate eventually formula carries the same raw condition, without a declared relationship to the obligation | The same shared temporal context, plus an explicit derived-view relationship |
| `ui_ux_ir:pair:0:2:0`: high-risk, single-confirm `publish_ledger` binding | `ui_ux_ir:tdfol` | Generated `confirm(action) before invoke(action)` lacks an operational confirmation contract | A versioned application policy and, separately, joined runtime evidence |

`domain_reconstruction_panel.source_inputs` constructs both Legal formulas
directly. No text-to-logic compiler parses this example. The fixture has no
parent section, definitions or citations to retrieve. The ten-day quantity and
unit are explicit; the triggering event, clock/calendar conventions and boundary
policy are not. `ModalIRFormula` has one operator/predicate plus string qualifiers,
rather than a nested modal/temporal expression.

`family_training_v3._correct_modal_family_views` preserves the complete original
records and refuses uninterpreted conditions. That behavior is correct. The
current evidence therefore shows **underspecified fixture premises and a missing
typed composition**, not demonstrated loss by the natural-language parser.

The UI source is structured data, not a clipped prose span. It contains a
high-risk/single-confirm/non-idempotent binding, one synthetic activation event,
and a declared `pending → finished` transition. It contains no observed
confirmation, invocation, cancellation or completed backend call. The native
TDFOL compiler branches on risk and emits a `before` string; confirmation class
and idempotency are not represented in that formula. Its existing treatment of
destructive and double-confirm/consent policies also needs separate review.

Adjacent text cannot recover a policy that was never supplied. The runtime's
`confirmation_granted` Boolean is not a declaration of freshness, request/token
association or consumption. An interface identity proves a descriptor join,
not an application authorization policy.

## Why filling in defaults would produce bad training labels

Suppose an action occurs at tick 12. A ten-tick deadline from origin 0 is missed;
the same duration from origin 5 is satisfied. The original sentence does not
select either origin. An actual timestamp need not be known when formalizing a
general rule, but the trigger and its binding must be specified. An unresolved
trigger is not the same as a correctly quantified trigger variable.

There is also an essential modal distinction:

`O(within_10_days(publish))` does not imply actual publication.

An obligation can exist while its subject violates it. A temporal view extracted
from that obligation must retain its position inside the norm. It cannot become
an independently asserted event fact. Moving modality across temporal operators
can also change meaning: obligations over eventual outcomes do not generally
imply one common time at which every ideal alternative has that outcome.

For UI, the same confirmation and invocation sequence may satisfy an explicitly
declared ten-tick freshness policy and fail a five-tick policy. Neither value can
be inferred from `before`. A truncated observation may omit an earlier
confirmation; that is incomplete evidence, not necessarily a policy violation.
Conversely, a complete observed prefix with no invocation can satisfy a safety
predicate vacuously without proving successful execution.

The counterexample script below uses small, explicitly authored finite models
to demonstrate these distinctions through actual Lake builds. It selects no
interpretation for the source fixtures and grants no qualification or admission.

## Diagnosis before repair

Use evidence to distinguish these classes; more than one may apply:

| Class | Evidence needed | Correct next action |
| --- | --- | --- |
| Missing or truncated source/context | Missing parent/span row, unresolved explicit citation, incomplete definition closure | Retrieve the identified source dependency |
| Underspecified semantic policy | Required slot absent after the available context is accounted for | Request a policy/source interpretation; retain alternatives |
| Parser or adapter retention loss | Required information is present in exact input and absent or changed after a specific stage | Repair that stage against a preserved counterexample |
| Unsupported typed lowering | Complete typed input is present but a backend cannot express it | Add the lowering and adversarial semantic tests |
| Failed conformance | A declared policy and sufficiently complete joined observations disagree | Preserve the violation; do not weaken the policy |
| Incomplete training review/floor | Missing applicability evidence or required capability | Supply the missing evidence; do not reinterpret it as a language defect |

For these authored fixtures, the corpus-context search is **not applicable** and
NLP retention testing is **not performed**. Those observations must not be
reported as successful context retrieval or a failed parser. The original
fixtures should remain negative controls. Context-completed companions should
have new identities and explicit declared premises.

## Reuse the existing infrastructure

These components were verified in the released revision:

| Existing component | Reusable capability | Boundary |
| --- | --- | --- |
| `logic/ir_core/provenance.py`: `SourceRef`, `SourceSpan` | Exact source/container digests, byte ranges and review status | A reference does not prove meaning |
| `logic/deontic/ir.py`: `LegalNormIR` | Parent/support spans, temporal constraints, section context, definitions and cross-references | Retained fields still need typed interpretation |
| `logic/legal_ir/typed_adapter.py`: `record_ambiguity` | Temporal-anchor, scope and unsupported-interpretation records | No proof or learned-label authority |
| `logic/legal_ir/logic_slice_v2.py`: `LegalTemporalModelBinding` | Time density, trace model, anchors and metric-interval declaration | Must be bound to actual source premises |
| `logic/autoformal/entity_cache.py`: `assign_span_context`, `assign_definition_closure` | Source-bound containment and bounded reference/definition closure | Unresolved references remain unresolved |
| `logic/autoformal/corpus_index.py` | Sparse source and explicit citation links | Do not invent implicit dependencies |
| `logic/formalization/typed_slots.py` | Exact referent bindings and KG snapshot identity | Does not supply a missing temporal policy |
| `logic/autoformal/repair_intake.py`, `repair_context.py` | Hydration review and exact failure/preserve context | Distinguish data gaps from source-code defects |
| `logic/ui_ux_ir/model/bindings.py` | Action target, risk, confirmation class, idempotency and condition/effect refs | No complete confirmation lifecycle contract |
| `logic/ui_ux_ir/runtime/mediator.py`, `receipts.py` | Request identity and declaration/event/state/policy/decision/invocation lineage | Boolean confirmation is not a token lifecycle; lineage is not event authenticity |
| `logic/autoformal/paired_span_census.py` | Hash-bound paired outputs, artifacts and deferred goals | Unknown reasons currently fall back to `compiler_abstain` in `_portable_repairs` |

That last fallback matters: missing context or policy must not automatically
become a goal to edit the compiler. The diagnostic work items produced here use
their own non-importable schema until a reviewed typed goal router exists. They
are not enqueued, published to Hugging Face, or passed to an agent supervisor.

## Implementation sequence

1. **Introduce a shared context envelope and typed resolution requests.** Reuse
   source/provenance owners instead of creating a second span identity system.
   Bind selected bytes, parent revision, support spans and their relation to the
   selection, referenced definitions, immutable policy revision, unresolved
   semantic slots and competing interpretations. Distinguish observed evidence,
   supplied declarations and reviewed resolution. Deduplicate source-level
   requests: one Legal temporal-context request feeds both failed projections.

2. **Hydrate only identified dependencies.** For real legal spans, retrieve their
   governing paragraph/section, definitions and explicit references with the
   existing bounded closure machinery. Preserve source revisions and scope; a
   nearby sentence is not automatically governing context. Prefer structured
   context facts and targeted retrieval within the existing context window.
   Return unresolved or conflicting evidence explicitly when closure cannot be
   completed. The two authored fixtures have no hidden corpus to hydrate.

3. **Build a single scoped Legal representation.** Bind the norm, activation
   conditions, exception scope, trigger and deadline in one typed AST. Derive
   family views from that AST and retain node/path mappings and enclosing
   modalities. Use the existing temporal-model and ambiguity types. Canonical
   v1 deliberately rejects nonempty definitions/cross-references/definition
   scope as unrepresented facets; do not stuff richer context through v1 and
   erase those facets. Add a reviewed adapter/profile with explicit losses or
   abstention for unsupported cases. Preserve legacy lineage interfaces and
   checkpoints through versioned adapters.

4. **Add a UI policy provider and separate trace adapter.** Key policy evidence by
   action binding, interface revision and source digest. Require explicit
   ordering, clock unit/authority, freshness, request association, cancellation,
   consumption and history scope. These are profile-specific choices; expiring,
   single-use tokens are not an implicit requirement for every application.
   Alternative policies need their own supported, explicit interpretation.
   Preserve risk, confirmation class and
   idempotency in typed projection/decompilation instead of a `before` string.
   Join runtime receipts separately. Use opaque correlation IDs or hashes, never
   credential tokens: the raw event owner explicitly forbids tokens. Keep policy
   availability, supported lowering, observed-prefix compliance and whole-workflow
   verification as four separate statuses.
   Receipt replay is integrity checking, not executor replay: `ALLOW`, a request
   ID or `replay_ok` does not prove the backend ran. Bind observed event content,
   ingestion scope and clock evidence explicitly; receipt observational fields
   and a finished replay do not establish completed workflow behavior.

5. **Connect resolution to the census and incremental workers.** Add versioned
   context-review, policy-review and adapter-repair work-item routes before
   exporting them through the existing paired census. Preserve complete source,
   direct/compiler-guided outputs, alternative interpretations and failure
   evidence in artifact records. A review item should name the missing evidence
   and acceptance criteria, not just request a higher score. Use shared,
   content-addressed context/target artifacts through the existing owner control
   plane; cache keys must include context, policy and producer hashes. Changing
   one definition or policy invalidates only dependent targets, not all weights.

6. **Validate the new evidence-to-target handoff before enabling it in training.**
   Add paired missing-context/context-completed cases, stale/foreign/conflicting
   context, obligation-without-fulfillment, modal-scope permutations, deadline
   origins and boundary cases. For UI include wrong request/action, expired,
   cancelled and consumed confirmations, same-tick ordering, missing prefix,
   double-confirm/consent/destructive mismatches and declared behavior versus
   observed invocation. Run all required family checks and actual modality Lake
   builds. Split corpus holdouts by shared parent/context/reference groups to
   prevent context leakage.

The first delivery in this work is diagnosis and an executable counterexample
audit. The context envelope, automatic resolver, typed goal router and new
production adapters above are **planned**, not implemented by this audit.

## Training implications

Resolving these three projections is necessary for their strict targets, but is
not sufficient to qualify the complete default panels: applicability reviews
and capability floors are separate requirements. Existing masks handle absent
features across valid observations; they do not authorize dropping an emitted
unsupported projection or its loss. Strict training must keep all current gates.

Workers can train other fully eligible batches and retain unresolved samples
as diagnostics. Any use of incomplete samples for feature learning must stay in
the separately labeled feature-only path, with no invented formal labels or
qualification. The new explicit Legal/UI interpreters are useful lowerers after
premises are supplied; their existence is not a source-context resolver.

Measure resolution by evidence-backed slot completion, conflict/abstention rates,
retained source-to-AST/projection correspondences, context leakage checks and
end-to-end time, not by making the negative fixtures pass. Report context lookup,
shared-target preparation, native checks and numerical training separately.

## Reproduce the diagnosis

Run from the pinned canonical tree or a reviewed export with an explicit
`PYTHONPATH`, using fresh output paths:

```bash
PYTHONPATH="$PWD" python scripts/ops/autoencoder/audit_default_projection_context.py \
  --output workspace/test-logs/projection-context-diagnosis-new.json

python scripts/ops/autoencoder/check_projection_context_counterexamples.py \
  --lake /path/to/installed/lean-toolchain/bin/lake \
  --output workspace/test-logs/projection-context-counterexamples-new
```

The diagnosis prepares exact targets and lowerings without issuing Lake evidence.
The second command runs small finite-model Lake checks, including rejection of
false claims. Neither command trains a model, mutates gates, downloads weights,
increases a context window, runs a supervisor, or marks a source formalized.
The Constitution remains unformalized.

## Delivered audit and validation

The read-only audit reproduced the exact **three semantic blockers across two
sources**, retaining all **27 Legal/UI projections** and the complete 40-family
inventory for each source. It generated **two source-grouped diagnostic review
items**; the Legal projections share one missing-context request. No policy was
inferred, and no item was enqueued or made supervisor-importable. The audit
itself executes no Lake or SANY commands.

The focused suite passed **16 tests** in **19.49 seconds**, including source and
producer drift, rehashed report tampering, work-item authority flags, preservation
of unsupported rows and refusal to overwrite an existing output file. Two fresh
CLI runs produced the same report digest:
`a0072a9b115dca0a7a4ff9143ccc352741811e0d3468f7a83900f1b089a3eab2`.

The separate finite-model diagnostic executed four actual Lake commands using
installed Lean 4.30.0 in **1.295 seconds**. Two positive libraries checked nine
Legal and six UI claims. Two negative libraries deliberately asserted false
equalities; Lean rejected both because `decide` established falsity. Source and
tool hashes, complete generated Lean, stdout/stderr and the earlier failed
diagnostic attempt are retained. These tests demonstrate why context matters;
they do not assign their toy interpretations to the source fixtures.

See the [diagnostic report](../implementation/reports/evidence/projection-context-audit-20261001/diagnosis.json),
[results](../implementation/reports/evidence/projection-context-audit-20261001/results.json),
and [evidence manifest](../implementation/reports/evidence/projection-context-audit-20261001/manifest.json).
Production parsers, training gates, model weights and corpus admission flags were
not changed by this work.
