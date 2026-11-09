# Reviewing a combined V2 definition-use candidate

`logic.autoformal.corpus_definition_use_review_v2` prepares, binds and assesses
review evidence for [the explicit V2 alias-use candidate](corpus_definition_use_v2.md).
It replays the whole candidate and both original source/context populations,
then delegates authentication and dependency freshness to the existing engines.
It supplies no signer, registry, clock, actual legal review or admission default.

## What a review covers

The subject binds the **full joint native AST**:

```text
donor_definition ∧ (consumer_definition ∧ explicit_alias_assumption)
```

The original two ASTs remain unchanged. The alias is a separate unproved unary
biconditional assumption between one complete local consumer predicate and the
selected donor head. Every repeated consumer body role remains bound. The
single lookup is tied to the first matching role in original binding order,
with `lookup_coverage=representative_first_occurrence_whole_predicate_assumption`
and `per_occurrence_lookup_verified=false`.

A fixed `review_contract` is part of the signed subject. A legal review declares
support, rejection or unresolved status for this exact combined source
interpretation and alias assumption. A formal review declares its decision
about the exact joint representation, source bindings and complete declared
context population. The engine authenticates these declarations under selected
keys; it does not establish their truth, a human identity or legal expertise.

Neither an original endpoint review nor a key scoped only to one original
definition authorizes the combined component. The new combined review scope
record binds the ordered donor/consumer source-version and scope identities,
their exact declared applicability, the new binding CID and the fixed review
profile. Its CID is the subject's `scope_id`. Review-registry keys must name
that scope explicitly.

## Independent inputs

```python
prepare_definition_use_review_evidence_v2(
    component_raw, *, expected_component_pin, use_inputs
)

validate_definition_use_review_evidence_v2(
    preparation, component_raw, *, expected_component_pin, use_inputs
)
```

`component_raw` is the exact original UTF8 candidate file, not a regenerated
substitute. `expected_component_pin` has exactly four independent fields:

- `component_sha256`: SHA256 of those original file bytes;
- `component_cid`: the complete sealed candidate's record CID;
- `graph_cid`: its graph snapshot record CID;
- `joint_ast_sha256`: SHA256 of the full joint AST's canonical DAG JSON.

`use_inputs` is the complete original argument dictionary for
`prepare_definition_use_v2`, including `request_raw`. Its twelve closed fields
are the alias request and expected raw hash, both endpoint evidence groups,
and the original lookup registry, lookup and query bytes with their independent
hashes/CIDs. The lookup registry is distinct from the review trust registry.

Both endpoint groups retain all six original candidate/source byte inputs,
twelve independent candidate pins, complete contexts and independently expected
preparation CIDs. Existing owners replay caller-lowered view, sampling and
compiler limits. Raw sampler/descriptor JSON hashes remain distinct from full
canonical hashes. A seal or self-supplied expected hash does not authenticate
where an input came from.

Preparation retains the joint AST, separate alias AST record, exact binding and
interpretation records, original definition/source/scope/symbol references and
role bindings, every distinct physical context and all ordered context slots.
It supplies a separately sealed review-policy/domain binding and a combined
scope record. No original source, interpretation, graph, lookup or native owner
is replaced.

## Subject and dependency generation

```python
build_definition_use_review_subject_v2(
    preparation,
    dependency_manifest,
    *,
    component_raw,
    expected_component_pin,
    use_inputs,
    expected_manifest_sha256,
    required_dependency_ids,
)
```

Build the manifest through the existing dependency owner using preparation's
`artifacts`, `edges` and `expected_artifact_ids`. Preserve the independently
retained `required_dependency_ids` from preparation when building the subject.
This is the ordered graph-reachable closure; it can differ from artifact order.

All original component artifact rows and dependency edges remain exact and in
their original order. Four artifacts and four root dependencies are appended:
the original component raw commitment, its separate full canonical commitment,
the combined scope record and the new policy/domain binding. That policy record
carries the new review-owner source pins. Original graph policy rows remain
unchanged. Negative and unsearched supplied lookup partitions remain part of
the conservative original inventory.

This profile accepts the exact new dependency generation. Missing, changed,
reordered, extra or unreachable rows/edges cannot be silently substituted.
The subject explicitly binds the manifest hash, complete ordered closure,
artifact hash references and each declared dependency reference.

## Authentication and domains

```python
assess_definition_use_reviews_v2(
    subject, registry, policy, reviews, dependency_manifest,
    *, component_raw, expected_component_pin, use_inputs,
    expected_subject_sha256, expected_registry_sha256,
    expected_policy_sha256, expected_reviews_sha256,
    expected_manifest_sha256, at_time_utc,
    observed_artifact_sha256s, observed_pins, evidence_artifacts,
)

validate_definition_use_review_assessment_v2(report, *args, **kwargs)
```

The schemas/domains are fixed by code, never selected from review JSON:

| Field | Value |
| --- | --- |
| Preparation | `legal-corpus-v2-definition-use-review-evidence/v1` |
| Subject | `legal-corpus-v2-definition-use-review-subject/v1` |
| Signed claim | `legal-corpus-v2-definition-use-review-signed-claim/v1` |
| Action | `record_v2_definition_use_review_evidence/v1` |
| Audience | `legal-autoformalization-v2-definition-use-review/v1` |
| Assessment | `legal-corpus-v2-definition-use-review-assessment/v1` |
| Review profile | `complete-v2-combined-definition-use-alias-review/v1` |

The existing `legal_graph_review._ReviewDomain` and `_assess_reviews` enforce
exact signed subjects, the two legal/formal roles, distinct authorized keys and
principals, explicit combined scope, intervals, revocations, current declared
dependencies and complete ordered context declarations with actual evidence
bytes. Old graph, definition-plus-norm and V2 definition-only domains cannot
authorize this new subject by relabeling a signature. Source and original
component replay occur before the authentication call.

An empty review population with unavailable trust remains pending and blocked.
Synthetic fixtures exercise signatures without supplying real reviewers.
Even credentials shaped as external pinned trust establish only prerequisites
under caller-selected trust; they do not authenticate a human, legal meaning,
clock, official source, governing applicability, software distribution or Lean
proof. The assessment retains `accepted_view_eligible=false` and explicit
downstream semantic/Lean blockers in every case.

## Bounds and source pins

Original component bytes plus both complete endpoint input groups, packets,
requests, metadata and original alias/lookup inputs share a 48-MiB budget.
The existing per-input ceilings remain: one MiB for sealed records/packets,
8,000,000 bytes for each HTML body, and 32 MiB for each complete sampler body.
Raw hashes, typed metadata and aggregate bounds are checked before optional
operation-owner loading. Public import loads no compiler, resolver, signature
backend, model or operation owner.

Combined contexts retain at most 256 physical occurrences and 1,536 obligations.
Preparation and subject use the existing one-MiB record/depth/node bounds.
The dependency engine retains its 4,096-artifact/16,384-edge limits. Shared
authenticated intake retains its 8-MiB aggregate, 32-review and 256-evidence-body
limits. A complete over-budget population refuses; nothing is truncated.

Pure owners are content-pinned at import. Lazy review owners and the actual
`profile_g.py` signature-owner file are pinned at first explicit operation and
checked before/after authentication. Existing component/native/source owners
also check their own pins during replay. These checks do not continuously
observe filesystem changes or authenticate a distribution.

## Remaining corpus gates

Review authentication does not mutate the original candidate flags or prove
the alias assumption. All semantic/authenticity/applicability, independent-human
review, per-occurrence lookup, admission, training/gold, backend/Lean execution
and proof authority flags remain false. Actual statutory interpretation and
source/use qualification require independently supplied decisions and reviews.

Per-occurrence governing lookup, same-document multiple-definition scope
carriers, arbitrary norm uses and compatible V2 native build qualification
remain separate extensions. No native Lean process, model training, resource
action or corpus/cache publication occurs through this review API.


## Plaintext parent combined-use review

The same owner also provides a separate fixed parent profile:

```python
prepare_parent_definition_use_review_evidence_v1(
    component_raw, *, expected_component_pin, use_inputs
)
validate_parent_definition_use_review_evidence_v1(
    preparation, component_raw, *, expected_component_pin, use_inputs
)
build_parent_definition_use_review_subject_v1(
    preparation, dependency_manifest, *, component_raw,
    expected_component_pin, use_inputs, expected_manifest_sha256,
    required_dependency_ids,
)
assess_parent_definition_use_reviews_v1(
    subject, registry, policy, reviews, dependency_manifest,
    *, component_raw, expected_component_pin, use_inputs,
    expected_subject_sha256, expected_registry_sha256,
    expected_policy_sha256, expected_reviews_sha256,
    expected_manifest_sha256, at_time_utc,
    observed_artifact_sha256s, observed_pins, evidence_artifacts,
)
validate_parent_definition_use_review_assessment_v1(report, *args, **kwargs)
```

The independent four-field component pin and twelve-field `use_inputs` envelope
are unchanged. Each endpoint instead supplies the complete parent evidence group
accepted by `corpus_definition_use_v2.prepare_parent_definition_use_v1`: original
candidate/report/request bytes, all independently expected candidate and parent
identities, the complete physical-parent replay inputs, all ordered context
packets and declarations, and its independently expected preparation CID. Parent
limits remain explicit and pass through the existing endpoint owner.

The parent route first validates complete input budgets, then regenerates the
parent alias candidate through its existing public validator. That validator
replays the installed parent-definition review preparation for both endpoints.
No XML, HTML, sampler or official paragraph binding is synthesized. Both complete
logical endpoint transports count toward the 48-MiB aggregate even when they
share physical storage. Parent byte/metadata commitments are checked again after
preparation and authentication; physical files are replayed during preparation,
without an atomic filesystem snapshot guarantee.

The combined parent scope binds each endpoint separately, preserving its full
source version, unknown edition, declared scope, independent candidate pins,
preparation CID and original physical-parent source binding. There is no invented
`declared_applicability` field or compatibility inferred from two equal unknown
edition sentinels. Both original candidate input bindings, source occurrences and
ordered source-role bindings remain in the review preparation. Full joint AST,
explicit alias, lookup provenance, graph identity, complete contexts and original
dependency generation receive the same exact replay and closure checks as the
existing combined-use owner.

| Field | Fixed parent value |
| --- | --- |
| Preparation | `legal-corpus-parent-definition-use-review-evidence/v1` |
| Subject | `legal-corpus-parent-definition-use-review-subject/v1` |
| Signed claim | `legal-corpus-parent-definition-use-review-signed-claim/v1` |
| Action | `record_parent_definition_use_review_evidence/v1` |
| Audience | `legal-autoformalization-parent-definition-use-review/v1` |
| Assessment | `legal-corpus-parent-definition-use-review-assessment/v1` |
| Review profile | `complete-parent-combined-definition-use-alias-review/v1` |

The shared authentication engine receives this fixed domain from the entry point;
review JSON cannot choose it. Existing official combined-use signatures and
parent endpoint signatures do not authorize this new combined interpretation.
The parent scope and policy binding use separate schemas, and newly appended
canonical/owner/dependency-reference identities use parent-specific labels.
Original component artifact rows and edges remain unchanged.

All existing false authority flags remain false, including governing scope,
governing edition, contributor completeness and source-region role verification.
The fixed review contract records that the alias is assumed, matching unknown
editions do not establish compatibility, and endpoint reviews do not authorize
combination. Authentication establishes only declarations under explicitly
selected keys and policy. Synthetic signatures establish no human identity,
independence, qualifications, statutory meaning or actual legal review. Unavailable
reviews and context evidence remain pending or blocked.

This interface prepares and assesses review custody only. It supplies no default
reviewer, clock, trust registry, training/gold eligibility, admission or native
Lean execution. `legal_corpus_definition_use_lake_v2` still requires its official
combined-review intake. A separately versioned parent intake should reuse that
owner's existing four-fragment, six-module conditional rendering; it must replay
this parent assessment and preserve all explicit premises before any native
qualification. The generic shared/incremental paragraph-bound intake remains a
separate compatibility task. No compiler or controller is added here.
