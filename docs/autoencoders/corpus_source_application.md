# Signed genesis candidate source-answer snapshots

`logic/autoformal/corpus_source_application.py` copies exact adjudicated answer
variant references into a separately authorized candidate snapshot. This is an
application of declared answers to a fixed candidate use. Prose findings remain
prose declarations: no governing edition, jurisdiction, effective date or physical
source occurrence is inferred. Original contexts remain `required_unavailable`;
graph, training and Lean admission remain false.

## Fixed effect and explicit genesis scope

The profile is `signed-genesis-candidate-source-answer-snapshot/v1`. Its effect is
`copy_exact_declared_answer_variant_references_only`. Supply this exact descriptor:

```python
descriptor = {
    "snapshot_id": "local:connected-pilot-source-answer-snapshot",
    "use_scope": "candidate_source_context_answers",
    "generation": 1,
    "previous_snapshot_manifest_ref": None,
}
```

Snapshot identity is a caller-declared namespace. The manifest's CID and FULL
canonical SHA256 identify exact content; a name and generation do not establish
global uniqueness, a latest version or an authoritative history. Generation two
and any non-null predecessor are refused. Validating a predecessor's seal alone
cannot establish its historical reviewer trust, dependency freshness or source
population. Authenticated revisions need a separate historical replay contract.
This genesis owner does not qualify cross-generation invalidation or inheritance.

Every original request receives one output row. An eligible request atomically
activates all nine answer references; a blocked request activates none. A snapshot
may therefore have eligible and blocked requests, but its complete original
population must remain present. There is no partial activation within a request
or qualified filtered population. The seven deferred semantic/proof questions
remain pending regardless of source-answer activation.

## Separate authorization through the shared signature engine

Application uses the existing original source subjects and dependency manifests,
with a fixed new claim schema/action/audience:

```text
legal-corpus-source-application-signed-claim/v1
activate_candidate_source_answer_snapshot/v1
legal-autoformalization-candidate-source-application/v1
```

The selected application registry and policy use the unchanged closed trust
schemas and this action/audience. The caller supplies independent FULL canonical
registry/policy hashes and an explicit evaluation time in the replay inputs.
There is no default signer, key, registry, clock or authority-selection callback.
Legal and formal authority roles attest the same application body. The same
adjudicator actors may separately authorize this action; the earlier declaration
action does not itself authorize activation.

The shared verifier owns signatures, key authorization, roles, intervals,
revocation, age, scope and dependency custody. The application wrapper excludes
all original reviewer principal IDs, declared DIDs and registered public-key
fingerprints from the complete supplied original batch, including rejected claims
and other requests. Relabeling an original key in another registry does not
create a separate actor. Human identity, competence and independence remain
unverified; caller-selected trust is an explicit technical premise.

## Author one common application body

`record_source_application_declaration(request, subject, adjudication_group,
descriptor, *, expected_request_sha256, expected_subject_sha256,
expected_adjudication_group_sha256, expected_preparation_manifest_sha256,
expected_typed_response_manifest_sha256, expected_adjudication_manifest_sha256,
declared_at_utc, rationale, evidence_refs, limits=None)` returns a sealed
unauthenticated candidate. All hashes here are FULL canonical record/root hashes,
including record CIDs; raw artifact/file hashes and payload CID hashes are
separate namespaces.

The common body binds the exact original request, subject, review authorization
scope, queue ordinal, adjudication group, all three upstream roots, descriptor,
fixed effect, declared time and ordered nine selected answer references. It copies
the complete adjudication's exact selections. It contains no new answer text,
changed source selectors or eventual signer-specific claim hash. Unsupported
effects, missing/extra/reordered selections and an unresolved adjudication slot
cannot author this profile. `rationale` must be explicit, and at least one exact
supporting `{"artifact_id": ..., "sha256": ...}` reference is required.

Authoring checks identity and structure; it does not authenticate the supplied
adjudication result. A structurally plausible repaired authority flag supplies no
eligibility. Complete assessment independently regenerates the original source,
typed response and adjudication population before checking application.
`validate_source_application_declaration(record, *inputs, **pins)` rebuilds the
declared body and compares every field.

Retain the exact serialized body bytes before signing. In each legal/formal
application claim, all nine obligations reference only the identical body
artifact ID/raw SHA256. Their dispositions match the selected typed variants:
`resolved_by_evidence` or `not_applicable`. Every claim must declare the exact
complete nine-slot closure with no unresolved entries. A conservatively open
application claim blocks activation. Supporting evidence must be present and
byte-exact; a missing, changed or self-referential body reference is rejected.

The application declaration cannot precede its adjudication declaration or any
supplied adjudication claim for the same request. It cannot postdate evaluation,
and application claims cannot precede their common body. These are declared
review chronology checks, not authentication of legal event clocks.

## Complete assessment and regeneration

```python
report = assess_source_applications(
    adjudication_report, application_registry, application_policy,
    application_groups, descriptor,
    expected_adjudication_manifest_sha256=adjudication_root_full_sha256,
    expected_application_registry_sha256=application_registry_full_sha256,
    expected_application_policy_sha256=application_policy_full_sha256,
    expected_application_group_pins=application_group_pins,
    adjudication_replay_inputs=complete_original_adjudication_inputs,
)
```

`adjudication_replay_inputs` is a closed object containing all named arguments
for `assess_source_adjudications`: the original preparation, source trust/groups,
complete typed report, adjudication trust/groups, their independent pins, exact
response bindings, evaluation time and fixed original source/alignment replay
inputs. Optional `source_review_limits`, `typed_response_limits` and `limits`
lower their respective upstream profiles. The outer application's `limits`
lowers this application profile. Unknown replay keys and custom callback/loaders
are refused.

Every application input group has exactly `request_cid`, `reviews`,
`app_artifact_id`, `evidence_artifacts`, `observed_artifact_sha256s` and
`observed_pins`. Empty review groups require a null body ID; nonempty groups
identify one common retained body. Independent pins contain `request_cid`,
`app_artifact_id`, `reviews_sha256`, `evidence_sha256s`,
`observed_artifacts_sha256` and `observed_pins_sha256`. Supplied groups and pins
must cover the entire original queue in order.

Complete original-source, adjudication and application evidence populations are
preflighted for raw and mixed JSON budgets before indexed evidence body hashing.
Trust, preparation, offered reports, pins and signed groups are detached and
independently checked. The fixed adjudication validator runs once per complete
application batch; it regenerates the full typed/source assessment once.
Original verifier results, differing declaration hashes and all alternatives
remain unchanged. A new application signature cannot bypass a current required
source/adjudication authority or dependency failure. Retained rejected reviews
remain visible; eligibility requires the current required authority pairs.

Activation requires valid application content, complete current original and
adjudication prerequisites, no separation/chronology blockers, and complete new
application authority prerequisites under selected trust. The result flag is
`source_answer_snapshot_activated_under_selected_profile`. Only then does
`activated_answer_variant_refs` contain the exact nine references; otherwise it
is empty. This flag qualifies the narrow copying effect, not the legal truth of
those answers or their physical governing source.

Output has `manifest`, `pages` and `records`. Each record embeds its complete
unchanged original adjudication group, new raw application authority assessment,
body reference/content result, blockers and active references. Upstream pending
slot and variant bodies remain available through independently pinned full roots.
Rejected application bodies retain exact raw references. Counts distinguish
bodies, authenticated claims, activated candidate snapshots/slots and blocked
groups/slots. Source decisions and physical governing bindings applied stay zero.
Every semantic, accepted-graph, training, human-independence and Lean flag remains
false; original selected-occurrence/governing bindings remain null.

The common record/page envelope is 1 MiB. Output and each stage's complete signed
evidence batch have separate 64 MiB caps; evidence groups have an 8 MiB cap with
at most 32 claims and 256 raw bodies. The profile supports at most 8,192 groups
and 256 pages of at most 64 rows. Limits can only be lowered. All populations
are retained completely or refused. These custody limits do not guarantee total
process memory or qualify an installed cryptographic distribution.

`validate_source_applications(report, *inputs, **pins)` bounds the offered
collection, repeats complete assessment and compares every component and producer
pin. Edited activation flags, repaired seals, filtered rows and hidden blockers
cannot replace regeneration. Engineering fixtures validate this behavior; actual
reviewer trust, signed decisions and snapshot activations remain separately
counted. Historical revisions, structured applicability choices, cross-generation
invalidation, reviewed statutory interpretations and graph/training/Lean admission
are subsequent contracts.
