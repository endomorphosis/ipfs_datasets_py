# Legacy candidate answer-reference application

`logic.autoformal.corpus_legacy_source_application` authorizes an atomic candidate
snapshot of nine adjudicated answer references. It fully replays the
[complete declared cohort](legal_legacy_source_cohort.md), then rechecks every
request's source and adjudicator authority at one explicit application time.
Earlier signed bodies and assessments retain their original identities and clocks.

The profile is `signed-genesis-legacy-source-answer-snapshot/v1`. Its fixed effect
is `copy_exact_declared_answer_variant_references_only`. The snapshot does not
select a governing source, verify legal meaning or create eligible training data.

## Bind and declare the action

Pass the original `cohort`, `banks` and complete ordered `adjudications` accepted
by `assess_legacy_source_cohort_adjudications`, together with its four independent
commitments: `expected_population`, `expected_population_sha256`,
`expected_cohort_sha256` and `expected_adjudication_assessment_sha256s`.
No successful flag substitutes for replay.

The genesis descriptor has exactly these fields:

```python
descriptor = {
    "snapshot_id": supplied_snapshot_id,
    "use_scope": "candidate_source_context_answers",
    "generation": 1,
    "previous_snapshot_manifest_ref": None,
}
```

The generation must be the integer one. This application owner refuses revisions
and predecessors. The separate [legacy history owner](legal_legacy_source_history.md)
replays genesis and separately authorized successors, preserving visible forks
and checking current use. A snapshot name does not establish global uniqueness,
a latest version or a published head.

`record_legacy_source_application_declaration(cohort, banks, adjudications,
descriptor, **keywords)` takes the four commitments plus `bank_id`,
`request_ordinal`, `declared_at_utc`, a nonempty `rationale` and nonempty
`evidence_refs`. It regenerates the cohort and original adjudication batch,
then records the selected request's nine resolved choices. Absent or unresolved
choices cannot become an application declaration. The output is unsigned.

The body binds the whole cohort and original batch, exact request/subject,
typed assessment, adjudication report/declaration, descriptor and nine selected
variant triples in slot order. It cannot predate any considered original cohort
assessment or its own adjudication declaration and claims. Supporting references
name raw artifact bytes by identity and SHA256.

## Submit separately signed evidence

`assess_legacy_source_applications(cohort, banks, adjudications, applications,
descriptor, **keywords)` takes the same four commitments, `at_time_utc` and
`expected_application_input_sha256s`. Supply exactly one entry per request in
the original bank/request order, including absent applications:

```python
entry = {
    "bank_id": bank_id,
    "request_ordinal": ordinal,
    "application_registry": registry,
    "application_policy": policy,
    "application_reviews": complete_claim_list,
    "assessment_inputs": {
        "declaration_artifact_id": declaration_id_or_none,
        "expected_declaration_sha256": raw_body_sha256_or_none,
        "expected_application_registry_sha256": registry_sha256,
        "expected_application_policy_sha256": policy_sha256,
        "expected_application_reviews_sha256": complete_claim_list_sha256,
        "observed_artifact_sha256s": current_artifact_observations,
        "observed_pins": current_pin_observations,
        "evidence_artifacts": exact_raw_bytes_by_id,
    },
}
```

`legacy_source_application_input_sha256(entry)` hashes the complete metadata
and replaces each evidence body with its SHA256 and length for serialization.
It performs bounded structural/trust-shape checks, not signature qualification.
Pin the complete ordered hash list independently of the output. An absent
declaration requires a null hash and empty claim list and stays pending.
The owner generates no reviewers, policies or keys.

Application has its own fixed `CLAIM_SCHEMA`, `ACTION` and `AUDIENCE`. Separate
legal/formal claims must support the same complete body under independently
pinned application trust. Each of their nine obligations must refer only to that
application artifact and raw hash, with the selected answer's disposition,
complete closure and no unresolved slots. Supporting bytes must match their
hashes and cannot refer to the application body itself. Old adjudication
signatures cannot authorize this action; adjudicators may sign it separately.

## Requalify at application time

For every member, the owner regenerates the original cohort assessment at its
original times, then regenerates its adjudication assessment at `at_time_utc`.
That also rechecks source signatures and dependencies at this new time. Original
source/typed/adjudicator bodies, claims and registry/policy snapshots remain exact.
The application entry independently binds new dependency observations. Full
fresh reports and their canonical digests remain separately available as
`current_adjudication_assessment` and `current_adjudication_assessment_sha256`.

Both the original cohort prerequisite and current per-request prerequisite must
pass. The separate application verifier checks authority, signatures, conflict,
role separation, evidence and dependency closure. Application claims cannot
predate their declaration, and evaluation cannot predate the original cohort
or declaration. Expired source, adjudicator or application claims prevent use
under the supplied snapshots; old success cannot be copied forward.

Application signers' claimed and registered principals/DIDs and registered keys
are checked against all source reviewers in the cohort. Structurally accepted
rejected source claims remain in that inventory; unknown source keys block
activation throughout it. Other requests' pending decisions remain visible.
Activation is atomic per request, not a transaction across all banks.

## Output and limits

Every request remains in `request_results`. Successful
`source_answer_snapshot_activated_under_selected_profile` exposes exactly nine
`activated_answer_variant_refs` in slot order; all other requests have an empty
list. Original/current assessment commitments, content failures, authority checks,
identity matches and chronology blockers remain visible. Seven deferred
semantic/proof questions per request remain deferred.

`decision_applied` stays false, as do source selection, governing-source, meaning,
graph, training and Lean authority. `source_decisions_applied` and
`physical_governing_bindings_applied` stay zero. Logical reference activation has
its own counts. No filesystem/database publication occurs in this API.

Existing cohort bounds still apply. Complete application metadata and raw bodies
have an additional aggregate 8 MiB bound; each claim list retains the 32-review
limit, each declaration the 1 MiB record limit, and output serialization is
bounded. Oversized input is refused without selecting a smaller population.
Logical byte limits do not measure memory or guarantee elapsed time; obtain
resource admission before replay.

`validate_legacy_source_application_declaration` and
`validate_legacy_source_applications` regenerate results and compare canonical
bytes, including boolean/integer distinctions. Completeness remains relative
to the declared population. Caller time, latest registry generation, human
identity/independence, source authenticity and applicability need other evidence.

The workspace's `artifacts/legal-paired-application-20261016-01/` retains bounded
qualification results. Synthetic applications are software fixtures; the selected
retained public banks contain no actual reviews or applications.
