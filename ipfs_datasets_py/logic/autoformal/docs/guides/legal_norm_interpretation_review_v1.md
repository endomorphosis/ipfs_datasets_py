# Review evidence for source-to-relational norm alternatives

**Public relational source profile:** this delivery includes the original `prepare_norm_review_evidence_v1`, `build_norm_review_subject_v1`, `assess_norm_reviews_v1`, `validate_norm_review_assessment_v1` and `norm_review_sha256` implementation. The later private counted-only norm-review successor is not ported. Its signing/input contracts must not be inferred from this relational profile. The [source-port ledger](../../../../../docs/autoformalization/evidence/legal-ir-bound-definition-owner-port-20261023.json) attributes the original103-case fixture qualification separately; the separate selected52-case /156-phase current-public fixture integration has now passed. This does not qualify every owning suite or statutory meaning.

[`legal_norm_interpretation_review_v1`](../../legal_norm_interpretation_review_v1.py) prepares and authenticates evidence about one existing, explicitly unreviewed source-to-relational correspondence. It reuses the existing graph-review verifier and dependency invalidation owner. It supplies no reviewer, signer, trust registry, clock, accepted interpretation or training admission.

The wrapper has a distinct signing domain. Its action is `record_norm_interpretation_review_evidence/v1`, its audience is `legal-autoformalization-norm-interpretation-review/v1`, and its subject and claim schemas are `legal-norm-interpretation-review-subject/v1` and `legal-norm-interpretation-review-signed-claim/v1`. Existing graph or definition review signatures do not authorize this new alternative. Original reports and their signing domains remain unchanged.

The [qualification report](../../../../../docs/autoencoders/legal_ir_norm_interpretation_review_20261016.md) records the bounded execution and its limitations separately from this API contract.

## Exact inputs and full replay

Preparation requires the complete output of `legal_norm_scope_correspondence_v1`, its independently retained full canonical hash, and all original inputs needed to replay it. `correspondence_inputs` is a closed dictionary containing these fields:

```python
correspondence_inputs = {
    "scope_report": scope_report,
    "relational_report": relational_report,
    "mapping_request_raw": mapping_request_raw,
    "expected_scope_report_sha256": scope_report_pin,
    "expected_relational_report_sha256": relational_report_pin,
    "expected_mapping_request_sha256": mapping_request_byte_pin,
    "scope_replay_inputs": scope_replay_inputs,
    "relational_request_raw": relational_request_raw,
    "expected_relational_request_sha256": relational_request_byte_pin,
}
```

Here the reports, original byte strings and pins come from retained inputs. `scope_replay_inputs` is the complete original argument dictionary accepted by the source-scope owner: original sampler report and raw HTML, descriptor, exact selected unit reference, scope request/declaration bytes and all their independent commitments. Raw request-byte hashes remain distinct from canonical JSON hashes. Rehashing a changed input does not establish the identity of an earlier artifact.

The wrapper bounds and detaches JSON/byte inputs, reuses the original request parsers, pins producer sources before correspondence replay, and checks both input and producer stability around operations. It replays the source/scope and relational owners through the correspondence owner; a stored flag or self-consistent replacement hash cannot substitute for that replay. Public import does not invoke the operation owners.

Snapshot serialization validates and encodes each immutable JSON scalar once.
It retains that scalar directly after validation; dictionaries and lists are
still copied independently at every occurrence. Shared inputs are not memoized
or discounted, and all mutation fences, type-separated digest tokens and
byte/node/depth bounds remain. This optimization does not permit reuse of a
previous replay result or establish meaning-review eligibility.

```python
from ipfs_datasets_py.logic.autoformal import (
    legal_graph_dependencies as dependencies,
    legal_norm_interpretation_review_v1 as norm_review,
)

preparation_inputs = {
    "correspondence": correspondence_report,
    "expected_correspondence_sha256": retained_correspondence_pin,
    "correspondence_inputs": correspondence_inputs,
    "context_inputs": None,  # Explicitly no additional contextual nominations.
}
preparation = norm_review.prepare_norm_review_evidence_v1(**preparation_inputs)
manifest = dependencies.build_dependency_manifest(
    preparation["artifacts"],
    preparation["edges"],
    expected_artifact_ids=preparation["required_dependency_ids"],
)
```

Retain the complete preparation, dependency manifest and their identities before downstream review. `norm_review_sha256(preparation)` computes the complete bounded canonical JSON digest. The manifest uses its existing `manifest_sha256` recipe. These are different hash recipes and must not be interchanged.

## Optional source context

`context_inputs` is either explicit `None` or this closed structure:

```python
context_inputs = {
    "packet": retained_context_packet,
    "sources": original_context_sources,
    "attachments": original_attachment_nominations,
    "expected_context_sha256": retained_context_packet_pin,
    "expected_attachments_sha256": retained_attachment_pin,
    "limits": None,  # Or the original permitted lowered context limits.
}
```

The existing `legal_source_sampling_review_context.validate` operation fully replays the packet, source bundles and attachments. The wrapper requires one exact target source bundle matching the scope's complete sampling report, descriptor and raw source commitments. The selected unit guide must match the original occurrence and context references, and the packet must contain a nomination addressed to that exact target. A matching phrase in a different edition or physical occurrence is insufficient. Complete raw bytes for every supplied contextual source are required.

The preparation retains the selected nominations and commitments to the complete context packet and its sources. These establish source custody and declared associations. They do not establish that a related definition governs the norm, that an attached provision applies, or that a contextual response has been independently reviewed. This profile does not accept typed definition-review assessments or resolve definition use: `typed_definition_reviews_supplied` remains false and `governing_definition_use` remains null.

## Obligations and compact signed subject

Every preparation retains an ordered obligation population:

1. The six unchanged original source-context slots.
2. One obligation for each original unresolved source issue, with its original content.
3. Seven interpretation questions: source meaning, participant roles, condition/modal scope, definition applicability, exceptions/time, unsupported grammar and source coverage.

No mapped anchor or authenticated review silently removes the original issues. This declared population is not an exhaustive inventory of legal dependencies or ambiguities. The profile rejects more than 512 obligations instead of truncating them.

The signed subject is compact, but assessment still requires the complete external preparation and original replay inputs. `native_binding` contains exact hashes of the preparation, correspondence, obligations, contextual evidence, producers, source scope, typed expression, native AST and original issues. It does not embed or rewrite those payloads. This preserves the existing signature engine's shallower, integer-only JSON contract without changing accepted source or typed-AST payloads to fit it.

The inherited field names have explicit meanings here: `graph_id` identifies the correspondence artifact, `graph_sha256` hashes that complete correspondence, `ast_sha256` hashes its typed expression, and `native_ast_sha256` hashes the separate native AST. Preparing this subject does not create or admit a semantic graph.

```python
# These expected identities are read back from the separately retained manifest.
subject = norm_review.build_norm_review_subject_v1(
    preparation,
    manifest,
    expected_preparation_sha256=retained_preparation_pin,
    expected_manifest_sha256=retained_dependency_manifest_pin,
    required_dependency_ids=retained_required_dependency_ids,
    **preparation_inputs,
)
```

The builder regenerates the complete preparation, requires the exact ordered artifact inventory and dependency edges, checks reachability, and constructs the compact subject. A forged preparation or subject does not pass merely because its own digest was recomputed.

## Explicit review assessment

Assessment delegates authentication to the existing `legal_graph_review` engine under the fixed norm domain. The caller supplies independently selected registry and policy objects, their hashes, the complete review population and its hash, an explicit UTC evaluation time, observed artifact/pin values, and exact evidence bytes. No default trust inputs are synthesized. An explicitly unavailable registry and an empty review population can produce a pending assessment.

```python
assessment_inputs = {
    "preparation": preparation,
    "expected_preparation_sha256": retained_preparation_pin,
    **preparation_inputs,
    "expected_subject_sha256": retained_subject_pin,
    "expected_registry_sha256": selected_registry_pin,
    "expected_policy_sha256": selected_policy_pin,
    "expected_reviews_sha256": retained_complete_review_population_pin,
    "expected_manifest_sha256": retained_dependency_manifest_pin,
    "at_time_utc": explicit_evaluation_time,
    "observed_artifact_sha256s": observed_artifact_sha256s,
    "observed_pins": observed_pins,
    "evidence_artifacts": exact_evidence_bytes_by_id,
}
assessment = norm_review.assess_norm_reviews_v1(
    subject, selected_registry, selected_policy, retained_reviews, manifest,
    **assessment_inputs,
)
norm_review.validate_norm_review_assessment_v1(
    assessment,
    subject, selected_registry, selected_policy, retained_reviews, manifest,
    **assessment_inputs,
)
```

The examples assume retained evidence and an independently selected trust configuration; they do not construct signed reviews. Registry and policy hashes use the existing review engine's canonical digest. `observed_pins` follows the existing dependency owner's root, source, revision, context, definition, model and policy categories. Current observations must be obtained independently; copying expected values is not an observation of current state.

The verifier checks detached Ed25519 signatures through Profile G, authorized key/principal/role/scope bindings, validity intervals and revocations, exact subjects, the complete review population, dependency freshness, ordered context obligations and evidence-byte hashes. Its two required roles are `legal_review` and `formal_review`, with distinct authorized principals and keys. It retains conflicts, ambiguity and unresolved context. A disposition of `not_applicable` still requires evidence. The caller's clock, registry identity, human competence and human independence are not authenticated by this dictionary API.

Signature authentication establishes statements under the selected keys. It does not establish legal truth, context completeness, applicability or source-to-formula equivalence. The engine's `review_prerequisites_satisfied_under_selected_trust` is distinct from `norm_interpretation_ready`, which remains false in this profile. Original partial/unassessed coverage, unresolved source issues, unverified governing definitions and independent semantic validation remain explicit norm-readiness blockers. Accepted-view, semantic, proof and training authority flags remain false, and training/evaluation masks remain zero.

No actual solver, Lean build, model inference, training or automatic publication is performed. The relational owner may retain generated Lean text as authored syntax evidence; authenticating a norm review does not turn that text into a statutory proof or a qualified learning target.

The [typed norm-response companion](legal_norm_content_responses_v1.md) adds
substantive role, scope, coverage and grammar declarations for this exact
candidate. It requires newly signed whole-body evidence references in the
existing domain; earlier claims without those references cannot authenticate
later-added answers. It preserves every original obligation and pending variant,
with definition applicability unresolved and all semantic/training masks zero.

## Unsigned parent literal-occurrence review evidence

`prepare_parent_norm_review_evidence_v1` and
`validate_parent_norm_review_evidence_v1` add an explicit unsigned companion for
[parent literal-occurrence correspondence v2](legal_norm_scope_correspondence_v1.md#explicit-parent-occurrence-correspondence-v2).
The existing relational signing domain and counted APIs keep
their original closed contracts. This companion creates neither a signable
subject nor a review assessment.

The schema is `legal-parent-norm-review-evidence/v1`; the profile is
`unsigned-parent-literal-occurrence-review/v1`.

```python
parent_preparation = norm_review.prepare_parent_norm_review_evidence_v1(
    parent_correspondence,
    expected_correspondence_sha256=independent_parent_correspondence_sha256,
    correspondence_inputs=original_parent_correspondence_inputs,
)
norm_review.validate_parent_norm_review_evidence_v1(
    parent_preparation,
    parent_correspondence,
    expected_report_sha256=independent_parent_preparation_sha256,
    expected_correspondence_sha256=independent_parent_correspondence_sha256,
    correspondence_inputs=original_parent_correspondence_inputs,
)
```

`correspondence_inputs` has exactly the nine fields shown in the original input
example above. Here its `scope_report` is the explicit parent scope profile,
its mapping request has schema `legal-norm-scope-correspondence-request/v2`,
and `scope_replay_inputs` contains all original arguments for
`prepare_parent_norm_scope_v1`: complete parent bundle, explicit manifest,
occurrence and companion CIDs, all three original report byte populations and
raw/canonical pins, complete physical replay inputs, lexical request/declaration
bytes and their pins, plus any original lower-only limits. Sampled HTML or
counted inputs cannot replace this closed parent profile. This API has no
`context_inputs` argument and applies no external context nominations.

The complete independently pinned correspondence is regenerated through the
existing public v2 validator at opening and closing. That validator itself
replays the original parent and relational inputs. Caller and detached inputs,
parsed requests, trusted producer sources, returned upstream objects and final
serialized output are checked on success and failure. Once replay begins,
closing checks are attempted even if the body fails; a primary error retains
its identity while secondary custody failures become notes. These are
sequential checks, not an atomic physical snapshot or permission to reuse a
stored validation flag.

The selected producer closure and first-use baseline are separate from the
legacy relational and counted baselines. Offered producer maps must equal the
trusted parent-correspondence closure before the upstream validator is called;
caller-supplied paths are not opened to discover trust. The dependency owner
retains its known sibling path and reviewed SHA256
`86cb7c3b09102a94237d0455d610d437e558cca4250242201becd06c775ca2e8`.

The report retains the entire correspondence and genuine
`original_parent_context`. Its `source_identity` explicitly records the parent
manifest, source-version, occurrence, companion and context CIDs, plus the
original source-binding SHA256. `source_identity_sha256` hashes that explicit
identity JSON. It does not reinterpret a CID as the SHA256 of source bytes.

`obligations` preserves this order without deduplication:

1. All six original missing context requirements, in their original order:
   definition, authority, antecedent, shared qualifier, temporal origin and
   referenced provision.
2. Every original unresolved issue, including repeated payloads.
3. The seven existing semantic interpretation questions.

Each context obligation has kind `original_parent_context`. Its `original`
contains the whole exact genuine context record, source-version/occurrence/
context CIDs, requirement ordinal and requirement name. Its ID is
`parent-norm-context:` followed by the canonical SHA256 of this explicit JSON:

```json
{
  "schema": "legal-parent-norm-review-context-id/v1",
  "source_version_cid": "<original CID>",
  "source_occurrence_cid": "<original CID>",
  "context_record_cid": "<original CID>",
  "requirement_ordinal": 0,
  "missing_requirement": "definition"
}
```

These are newly derived parent-review IDs, not original HTML dependency-slot
IDs. Equal text at another physical occurrence retains different provenance.
Issue and question IDs also commit the parent preparation schema, complete
correspondence hash, original ordinal and payload. `obligation_ids` retains the
full order; `context_obligation_ids` identifies the six parent-context rows.
All six requirements remain `required_unavailable`; the inventory is not an
exhaustive account of legal dependencies or ambiguities.

The existing dependency owner builds and validates `dependency_manifest` over
the complete correspondence, explicit identity JSON, retained input commitments
and trusted producer map. `required_dependency_ids` gives its exact ordered
population. The manifest is declared artifact custody only. It supplies no
current observations, freshness decision, legal dependency closure or semantic
graph admission. Its `manifest_sha256` recipe remains distinct from the full
`norm_review_sha256(parent_preparation)` output hash. Retain the latter in an
independent manifest before validation.

The existing bounds remain 8 MiB for complete output, 128 MiB aggregate snapshot
inputs and 512 complete obligations, with inherited byte/node/depth limits.
The parent correspondence's own larger output allowance does not raise this
review profile's 8 MiB bound. Oversized input or output is refused without
truncation or omission.

The [separate closing-custody summary](../../../../../docs/autoformalization/evidence/legal-ir-parent-norm-review-closing-custody-20261024.json)
records 16 authored cases / 48 phases across the parent review and separate
content worksheet owners. Its original source generations and case scopes
remain separate from the parent nomination qualification. The parent review
APIs retain unresolved source, edition, context and meaning; governing
definition applicability and graph/Lean admission remain open, with false
authority and integer-zero semantic, consumer, training and gold masks.
