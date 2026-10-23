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
