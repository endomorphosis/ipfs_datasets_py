# Source-first review intake

`logic.autoformal.legal_source_sampling_review` connects the whole-source
sampler to separately recorded reviewer declarations. It retains every ordered
unit, control and withheld paragraph context, with the complete sampler report
stored once. It does not interpret legal text, authenticate a reviewer, select
governing law, or admit meanings into training, a semantic graph or Lean.

This is an additive intake profile. The historical parent/alignment review
requests keep their own replay identities and signing domains. The new catalog
retains all thirteen prepared definition-review question IDs and prompts, then
adds two questions for complete norm meaning and arguments/qualifiers. Catalog
provenance is recorded in the module; the byte-exact origin is retained in
[the integration evidence](../../../../../docs/autoencoders/evidence/legal-source-review-integration-20261015-01/packet-fit-v01.json).
Question reuse does not establish authentication or admission equivalence.

## Prepare a bundle

```python
from copy import deepcopy
from ipfs_datasets_py.logic.autoformal import legal_source_sampling_review as review

# replay_inputs includes the independently retained FULL sampler report hash,
# descriptor, descriptor hash, raw source hash and expected byte count.
bundle = review.prepare_sampling_review_bundle(raw, **replay_inputs)
bundle_pin = review.sampling_review_bundle_sha256(bundle)
review.validate_sampling_review_bundle(
    bundle, raw, expected_bundle_sha256=bundle_pin, **replay_inputs
)
declaration = deepcopy(bundle["guides"][0]["response_template"])
declaration["bundle_sha256"] = bundle_pin
# A reviewer must supply findings, rationale, evidence and declarations.
# The remaining blank fields intentionally cannot be recorded as a response.
```

The replay inputs are `expected_sampling_report_sha256`, `descriptor`,
`expected_descriptor_sha256`, `expected_raw_sha256`, and `expected_raw_bytes`.
The sampler hash is canonical FULL JSON, including its internal payload digest;
it differs from a transport-file hash. Optional `view_limits` and
`sampling_limits` belong to the existing extraction and sampler owners.
`limits` may only lower this adapter's hard bounds: 64 MiB per bundle, 4,096
subjects, 8,192 responses, 1 MiB per response and 64 MiB per response population.
Source bytes are limited to 8,000,000. Existing canonical record limits also
apply. Overflow refuses the complete operation rather than returning a prefix.

Blank guides retain unknown reviewer/exposure fields and unanswered questions.
Their embedded `bundle_sha256` is null to avoid a circular hash reference. Fill
it explicitly after computing the full bundle hash; the catalog reference is
already fixed. The recorder checks both declarations against the current bundle.

## Record and validate declarations

`record_sampling_review_response(bundle, declaration, raw, *,
expected_bundle_sha256, **replay_inputs)` accepts exactly the template fields:
bundle hash, catalog reference, subject reference, reviewer declaration,
exposure declaration, source answers and meaning proposals.

Every question needs a typed disposition, nonblank finding and rationale.
Substantive source findings use `evidence_declared`; semantic suggestions use
`proposal`. Either category can instead record `unresolved`, `disputed`,
`unsupported`, or explained `not_applicable`. Unresolved answers must identify
their gaps. Evidence must name exact available subject or shared-view references.
Another occurrence cannot replace the anchored subject.

Use `validate_sampling_review_response` with both the independently retained
canonical response hash and bundle hash, plus the original replay inputs. It
regenerates the typed declaration after complete source replay. Changed bundle,
catalog, selectors, masks or authority cannot be authorized by resealing alone.

Reviewer identity, role, time and exposure remain unverified declarations.
Unknown exposure stays null; it never defaults to candidate-blind review.
External identity/independence evidence IDs are retained without retrieval or
authentication. No signer, policy, clock, model or loader callback is accepted.

## Account for the population

`summarize_sampling_review_population` takes the bundle, ordered response list,
raw source, independent bundle hash, one canonical hash per response, and replay
inputs. It checks every bounded response before replaying the source once.
Every unit/control/withheld subject receives a state: `pending`, `disputed`,
`unsupported`, or `declarations_recorded`. Dispute/unsupported precedence retains
all unresolved-question and unknown-exposure reasons. No latest response wins.

The summary detects explicit disputed or incompatible dispositions; it does not
infer agreement or disagreement from different prose. All response references
remain available. Empty or unavailable source populations cannot count as
completed review. Every authentication, meaning/graph/gold/Lean/proof flag and
training/evaluation mask remains false or zero, including after all declarations
have been recorded.

The sampler's markup-v2 coordinates are not raw HTML or native-v1 coordinates.
Multi-paragraph selectors may be proposed in findings with the shared full-view
reference, but this intake does not verify or assemble those prose proposals.
Unavailable context stays unresolved. A downstream typed assembly must separately
bind every source occurrence and establish correspondence to its native view.
Supported typed interpretation, independent review and admission remain separate
steps before graph or Lean generation.

The tests exercise real sampler/source/CID owners using fictional HTML and
synthetic reviewer declarations. They include complete-population preservation,
Unicode occurrences, withheld context, changed bundle/catalog bindings, bounds,
unresolved states, resealed tampering and a module-body cold-import control.
They do not qualify actual statutory meanings or the entire package bootstrap.

## Migrate source only preparation packets

The earlier `legal-v2-actual-source-review-handoff-input/v1` packets contain
thirteen unanswered navigation questions. They are not declarations accepted by
this recorder. `legal_source_sampling_review_handoff` checks their original
bytes, exact sampler unit and occurrence, original context and V2 context packet
against the complete current bundle. It then prepares a new fifteen-question
blank template with explicit origin commitments.

```python
from ipfs_datasets_py.logic.autoformal import legal_source_sampling_review_handoff as handoff

draft = handoff.prepare_sampling_review_handoff(
    original_handoff_bytes, bundle, raw,
    expected_handoff_sha256=independent_original_handoff_file_hash,
    expected_bundle_sha256=bundle_pin,
    **replay_inputs,
)
draft_pin = handoff.sampling_review_handoff_sha256(draft)
handoff.validate_sampling_review_handoff(
    draft, original_handoff_bytes, bundle, raw,
    expected_handoff_record_sha256=draft_pin,
    expected_handoff_sha256=independent_original_handoff_file_hash,
    expected_bundle_sha256=bundle_pin,
    **replay_inputs,
)
declaration = deepcopy(draft["response_template"])
```

The bundle hash is filled in the migrated template. Answers, reviewer and exposure
fields remain blank; a recorder submission still requires explicit declarations.
The adapter refuses already answered packets rather than discarding answers
during migration. The old raw-file hash, full canonical hash and context-packet
hash remain distinct commitments. Scope and definition navigation labels supply
no legal role, attachment, applicability or typed AST.
The initial migration profile accepts the original six default open context
slots. Packets containing supplied dependency requests need a separate explicit
migration contract; their context cannot be silently replaced with missing slots.

Record unavailability as an explicit unresolved answer naming missing evidence.
An unanswered template and an unresolved declaration represent different stages.
The v1 recorder accepts an explained `not_applicable` disposition without
requiring a citation; downstream review policy must separately decide whether
the stated evidence is adequate. The population summary preserves different
prose declarations but does not decide whether those statements agree or
contradict one another. `declarations_recorded` denotes retained unverified
declarations, not agreement, independent reviewers or accepted meanings.

## Contextual source and definition delegation

The original contextual implementations now have canonical source paths in the same module. Reuse these APIs and their existing companions; each call retains complete original evidence and exact occurrence/context references. The [source-port ledger](../../../../../docs/autoformalization/evidence/legal-ir-bound-definition-owner-port-20261023.json) records their source generation and the closed selected52-case /156-phase authored public integration.

| Public facade | Context APIs | Existing implementation |
| --- | --- | --- |
| `legal_source_sampling_review` | `prepare_sampling_review_context`, `sampling_review_context_sha256`, `validate_sampling_review_context`, `record_sampling_review_context_response`, `validate_sampling_review_context_response`, `summarize_sampling_review_context_population` | [`legal_source_sampling_review_context`](../../legal_source_sampling_review_context.py) |
| `legal_source_sampling_definition_binding_v2` | `prepare_contextual_definition_binding_v2`, `contextual_definition_binding_sha256`, `validate_contextual_definition_binding_v2` | [`legal_source_sampling_context_definition_binding_v2`](../../legal_source_sampling_context_definition_binding_v2.py) |
| `legal_source_sampling_definition_review_v2` | `prepare_contextual_definition_review_correspondence_v2`, `contextual_definition_review_correspondence_sha256`, `validate_contextual_definition_review_correspondence_v2` | [`legal_source_sampling_context_definition_review_v2`](../../legal_source_sampling_context_definition_review_v2.py) |

Context attachments and responses supply custody and explicit nominations. They do not select a governing definition, prove membership or establish source/meaning/applicability review. The relational norm/definition and [bound-variable conditional](legal_bound_variable_definition_v1.md) consumers replay the original inputs; they preserve unresolved alternatives, null selections and zero training/evaluation eligibility masks. The bound-variable consumer emits conditional definition instances without rewriting or compiling the surrounding norm.
