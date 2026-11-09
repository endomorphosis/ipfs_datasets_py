# Common declarations for legacy source adjudication

`logic.autoformal.corpus_legacy_source_adjudication` binds a separately signed
common declaration to the complete retained [typed source assessment](legal_legacy_source_responses.md).
It authenticates declared choices under explicitly supplied trust. Source
selection, statutory meaning, graph admission and training eligibility remain
pending.

The profile is `explicit-dual-role-legacy-source-adjudication/v1`. It reuses
the current legacy source requests, full replay and shared signature verifier.
Its claim schema, action and audience are distinct from source review:

| Contract | Value |
| --- | --- |
| Claim schema | `legal-corpus-legacy-source-adjudication-signed-claim/v1` |
| Action | `record_legacy_source_adjudication_declaration/v1` |
| Audience | `legal-autoformalization-legacy-source-adjudication/v1` |

## Replay and record

Pass the original preparation, typed assessment, source registry, source
policy and complete source-review list. Independently pin the canonical digest
of the **whole** typed assessment as `expected_typed_assessment_sha256`;
this includes its embedded assessment hash. `response_inputs` contains every
keyword input originally supplied to `assess_legacy_source_responses`, including
the complete source-bank bytes, original source/dependency observations, trust
pins, evidence, response bindings and evaluation time. The owner regenerates
the complete typed assessment before trusting any variant.

```python
from ipfs_datasets_py.logic.autoformal import corpus_legacy_source_adjudication as adjudication

template = adjudication.prepare_legacy_source_adjudication_template(
    preparation, typed_assessment, source_registry, source_policy, source_reviews,
    expected_typed_assessment_sha256=typed_assessment_sha256,
    response_inputs=original_response_inputs,
)
```

`template["declaration"]` contains a null declaration time and nine ordered
choices with null decisions, rationale and selected references. It is not a
submitted declaration. Actual supplied choices have this shape:

```python
choice = {
    "slot_id": original_slot_id,
    "decision": "select_existing_variant",  # Or "unresolved".
    "selected_variant_ref": existing_variant_ref,  # None when unresolved.
    "rationale": supplied_rationale,
    "evidence_refs": [{"artifact_id": evidence_id, "sha256": raw_evidence_sha256}],
}
```

There must be exactly nine choices in the original slot order. Selection may
name only an existing authenticated typed variant with an `evidence_declared`
or `not_applicable` answer and supporting evidence. Unavailable or ambiguous
variants cannot be selected. Unresolved choices retain a null selected reference.
The seven deferred semantic/proof questions remain deferred.

Call `record_legacy_source_adjudication_declaration(..., decisions,
declared_at_utc=..., **same_replay_arguments)` to record explicit choices.
The sealed declaration binds the request, source, questions, preparation,
complete typed assessment, all pending slots, all considered variants and the
occurrence-proposal population. Recording does not authenticate it. Declaration
time must follow the considered assessment and original review issue times.

## Authenticate the common body

Retain the declaration's exact serialized bytes. Separately authorized legal
and formal reviewers sign claims in the new fixed domain. Every claim must
reference **that same artifact identity and raw hash** in all nine context
obligations. The obligation dispositions must match the declared selected
variants, or be `open` for unresolved choices. The closure must list precisely
the unresolved slots and use `open` if any remain, otherwise `declared_complete`.

Call `assess_legacy_source_adjudication` with the five replay inputs, followed
by the separately supplied adjudication registry, policy and reviews. Supply:

- The same independently pinned typed assessment and `response_inputs`.
- `declaration_artifact_id` and `expected_declaration_sha256`, both null when
  no declaration exists. An absent declaration requires an empty claim list.
- Independent `expected_adjudication_registry_sha256`,
  `expected_adjudication_policy_sha256` and
  `expected_adjudication_reviews_sha256` pins.
- `at_time_utc`, current `observed_artifact_sha256s` and `observed_pins`.
- `evidence_artifacts`, containing exact declaration and supporting bytes.

Both source and adjudication authority are checked at the new evaluation time.
The original source registry/policy snapshots remain pinned; the owner cannot
discover later revocations or authenticate the caller's clock. Every supplied
original source review must still authenticate, and its original typed content
must validate. Distinct typed-valid legal/formal source roles are required.
A valid signature alone cannot supply a role when the response body is invalid.

Adjudicators must differ from every supplied original reviewer by principal,
DID and known public-key bytes. Both adjudication roles must independently
meet the shared verifier's trust, scope, time, signature, support, ambiguity,
common-body and dependency checks. Claims cannot predate their declaration;
the declaration cannot postdate evaluation. These identity checks cover the
supplied request's population. They do not attest human independence or detect
an original reviewer omitted from that population or appearing only in another
request. The separate [cohort owner](legal_legacy_source_cohort.md) binds the
complete declared bank/request population and checks these identities across it.
A future application must consume that bound check; per-request authentication
alone cannot claim reviewer separation across both banks.

## Results and limits

`original_typed_assessment` retains all original responses, exact variants,
occurrence proposals and blockers. `current_source_authority_assessment`
records the fresh source check; `authority_assessment` records the separate
adjudication claims. `declaration_content_status` distinguishes absent, valid
declared content and rejected content. Missing or changed body bytes and
inconsistent signed choices cannot satisfy the combined prerequisites.

`authority_prerequisites_satisfied_under_selected_trust` describes declaration
authentication only. Original context-declaration differences and dissent stay
visible; they need not disappear merely because an adjudicator considers them.
All nine `pending_slots` keep `decision_applied=false`. The selected occurrence,
source-selection, source-meaning, semantic-admission and training flags remain
null or false, including for a fully authenticated declaration.

The two validators regenerate the exact declaration or assessment; canonical
byte comparison rejects boolean/integer substitutions. Individual declarations
are bounded to 1 MiB. The shared 32-review, 256-evidence and 8 MiB authentication
limits apply, along with the original complete source replay limits. Supporting
evidence must exist and match its raw hash; self-referential declaration evidence
is rejected. These checks establish custody and internal consistency, not the
adequacy or legal truth of the evidence.

The enclosing workspace's `artifacts/legal-paired-adjudication-20261016-01/`
holds the qualification records. Its retained-data replay has no actual review
or adjudication declarations. Synthetic test identities and findings exercise
the software contracts and cannot substitute for statutory source review.
