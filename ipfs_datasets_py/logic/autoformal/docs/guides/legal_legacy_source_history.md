# Legacy candidate answer-reference history

`logic.autoformal.corpus_legacy_source_history` replays an explicitly supplied
genesis and revision graph. Each revision separately authorizes the same narrow
effect as [genesis application](legal_legacy_source_application.md): copying
exactly nine adjudicated candidate answer references, or none, per request.
Historical activation and eligibility for current use are separate observations.

The separate [legacy source-binding owner](legal_legacy_source_bindings.md)
consumes a fully replayed eligible history to authenticate an explicit candidate
stored-section/occurrence/applicability declaration. Governing-source adoption
and legal meaning remain separate requirements.

The profile is `signed-legacy-source-answer-history/v1`. The
[owner](../../corpus_legacy_source_history.py)
creates no signer, policy, revision, authoritative head, source binding, training
target or proof. It preserves every supplied epoch, including failed revisions
and visible sibling branches.

## Replay a complete declared history

```python
assess_legacy_source_history(
    genesis_report, genesis_inputs, revision_steps, *,
    genesis_epoch_id, current_epoch_id, at_time_utc,
    expected_genesis_assessment_sha256, expected_revision_step_sha256s,
)

validate_legacy_source_history(report, *args, **kwargs)
```

`genesis_report` is the complete application assessment. `genesis_inputs` is a
closed dictionary containing all arguments needed to regenerate that assessment:

```python
genesis_inputs = {
    "cohort": original_cohort,
    "banks": complete_banks,
    "adjudications": complete_ordered_adjudications,
    "applications": complete_ordered_applications,
    "descriptor": genesis_descriptor,
    "expected_population": independently_expected_population,
    "expected_population_sha256": population_sha256,
    "expected_cohort_sha256": cohort_sha256,
    "expected_adjudication_assessment_sha256s": ordered_adjudication_hashes,
    "expected_application_input_sha256s": ordered_application_input_hashes,
    "at_time_utc": original_application_evaluation_time,
}
```

The bank, typed-response, adjudication and application input contracts remain
those of the [cohort](legal_legacy_source_cohort.md) and application owners.
Their exact raw evidence and full populations are required; an earlier success
flag is insufficient. Genesis is regenerated through the existing application
validator at its original declared time.

Each revision step has exactly this envelope:

```python
step = {
    "epoch_id": new_epoch_id,
    "previous_epoch_id": earlier_epoch_id,
    "inputs": revision_inputs,
}
```

`revision_inputs` has the same common fields as `genesis_inputs`, replacing
`applications` and `expected_application_input_sha256s` with `revisions` and
`expected_revision_input_sha256s`. Its `descriptor` has a distinct revision
shape:

```python
revision_descriptor = {
    "snapshot_id": predecessor_snapshot_id,
    "use_scope": "candidate_source_context_answers",
    "generation": predecessor_generation + 1,
    "previous_snapshot_report_ref": {
        "schema": predecessor_report_schema,
        "sha256": predecessor_complete_report_sha256,
    },
}
```

The generation is an integer of at least two and must be exactly the
predecessor's plus one. Snapshot ID and use scope must remain unchanged. This
`previous_snapshot_report_ref` is a two-field reference to the complete report,
not a record CID. Genesis retains its separate integer-one descriptor and null
`previous_snapshot_manifest_ref`; do not rename that field or feed a revision
descriptor to the genesis application owner.

`expected_genesis_assessment_sha256` and report references hash the canonical
complete report, including its embedded `assessment_sha256`. They differ from
that embedded digest and from the hash of an indented JSON file. Source and
answer references remain their existing `{record_cid, sha256, schema}` triples.
Supporting evidence references still bind artifact identity and raw byte hash.

`legacy_source_history_step_sha256(step)` commits the complete step, including
its epoch IDs and immutable raw evidence. Supply the independently pinned hashes
in the same order as `revision_steps`; omissions or reordering cannot silently
change the declared graph.

## Author and separately authorize a revision

```python
record_legacy_source_revision_declaration(
    genesis_report, genesis_inputs, revision_steps, revision_inputs, *,
    genesis_epoch_id, epoch_id, previous_epoch_id, bank_id, request_ordinal,
    expected_genesis_assessment_sha256, expected_revision_step_sha256s,
    declared_at_utc, rationale, evidence_refs,
)

validate_legacy_source_revision_declaration(record, *args, **kwargs)
legacy_source_revision_input_sha256(entry)
```

Authoring requires `revision_inputs["revisions"] == []` and
`revision_inputs["expected_revision_input_sha256s"] == []`: it records supplied
unsigned intent before authority claims exist. The candidate's complete inputs
count toward graph bounds before replay. The owner regenerates the predecessor
graph and candidate source/adjudication cohort, then binds the exact predecessor
report, predecessor request result, new epoch, source population and nine resolved
answer choices. Supporting evidence and rationale must be nonempty. The output
does not authorize itself.

For assessment, supply one revision entry per original request, preserving bank
and request order, including absent declarations:

```python
entry = {
    "bank_id": bank_id,
    "request_ordinal": ordinal,
    "revision_registry": registry,
    "revision_policy": policy,
    "revision_reviews": complete_claim_list,
    "assessment_inputs": {
        "declaration_artifact_id": declaration_id_or_none,
        "expected_declaration_sha256": raw_body_sha256_or_none,
        "expected_revision_registry_sha256": registry_sha256,
        "expected_revision_policy_sha256": policy_sha256,
        "expected_revision_reviews_sha256": complete_claim_list_sha256,
        "observed_artifact_sha256s": current_artifact_observations,
        "observed_pins": current_pin_observations,
        "evidence_artifacts": exact_immutable_raw_bytes_by_id,
    },
}
```

`legacy_source_revision_input_sha256(entry)` checks the closed entry shape and
commits its full metadata and raw evidence. This hash does not authenticate
trust, signatures or meaning. Absence requires a null declaration hash and an
empty claim list; it remains visible in the assessment.

Revision authority has its own fixed domain:

| Item | Value |
| --- | --- |
| Claim schema | `legal-corpus-legacy-source-revision-signed-claim/v1` |
| Action | `revise_legacy_candidate_source_answer_snapshot/v1` |
| Audience | `legal-autoformalization-legacy-source-history/v1` |

Separate legal and formal claims must authorize the exact same complete revision
body. All nine signed obligations bind that body's artifact identity and raw
hash, preserve each selected answer's disposition, declare complete closure and
have no unresolved slots. Supporting bodies must exist, match their hashes and
not refer to the revision declaration itself. Application or adjudication
signatures cannot be relabeled as revision authorization.

## Keep historical and current checks separate

Each revision replays its original source/typed/adjudication cohort, then checks
source, adjudicator and new revision authority at the revision's explicit
`at_time_utc`. Dependency observations come from its revision entries. The
original reports remain unchanged; fresh per-request adjudication reports and
their complete hashes are retained separately.

Evaluation cannot predate the predecessor or any considered original
adjudication assessment. The declaration cannot predate its predecessor or
considered adjudication evidence, follow its evaluation, or follow the issuance
of claims authorizing it. Registry/policy snapshots and caller clocks are
explicit inputs; replay does not establish that they are the latest external
snapshots or the legal effective date.

Source preparation, bank order, request references and subject references must
match genesis throughout the graph. New reviews and authority inputs can be
supplied for that fixed population. Source migrations require another profile.
A failed predecessor remains retained; a fresh, independently qualified
successor may activate its own complete choices. It does not inherit success
from its parent or erase the parent's failure.

Actor exclusion has two scopes:

| Assessment | Source-review identities excluded |
| --- | --- |
| Historical revision | Its own cohort and every exact ancestor's cohort |
| Current-use projection | All supplied epochs, including other branches |

Both revision signers and adjudicators are checked against claimed and registered
source-review principals/DIDs and known raw public keys. Rejected source claims
remain part of the declared inventory. Unknown source keys block eligibility in
the applicable scope. Adding a sibling does not rewrite an earlier sealed
revision; its identities still participate in the separate current-use check.
These checks do not establish human identity or independence.

## Whole-graph and current-leaf behavior

Steps must be in topological order. Duplicate epoch IDs, unknown or later
predecessors, relabeled duplicate revision inputs, duplicate report roots,
generation gaps and changed predecessor references are refused. The owner does
not return a favorable prefix after an invalid supplied step.

`current_epoch_id` must explicitly name a supplied leaf. Its evaluation time must
equal the outer `at_time_utc`, and no supplied epoch may be later than that time.
Each visible parent with multiple children is retained in `forks`. Any such
fork blocks current use throughout the supplied history, even if sibling answers
agree. This owner provides no fork-resolution authority.

Genesis-only history is representable, but every current result includes
`fresh_revision_authorization_required`, even when genesis historically activated
answers. A revision leaf needs its own fresh authority and must pass the full
graph and actor checks before `current_use_eligible` can become true. Historical
activation is never automatically current authorization.

The history report retains every epoch's original report and exact
`{schema, sha256}` reference. `current_request_results` bind each selected
historical request result by its complete hash, preserve blockers and deferred
questions, and expose nine `active_answer_variant_refs` only when eligible.
Otherwise that list is empty. Original source/governing fields remain null;
`decision_applied` remains false; source decisions and physical governing
bindings remain zero. Semantic, training, proof and Lean authority remain false.
The graph is complete only relative to the supplied, pinned inputs. Head
authenticity and exhaustive external-history discovery remain false.

## Bounds and evidence scope

The complete graph allows at most eight epochs, including genesis, and 128
request observations summed across epochs. Mixed metadata and repeated raw byte
inputs share a 512 MiB bound; canonical commitment metadata is additionally
limited to 64 MiB, two million visited nodes and depth 64. Repeated byte references
count repeatedly for the input bound. These are structural/work bounds, not
measurements of unique memory or runtime.

Commitments tag raw bytes with their SHA256 and length. The
`_legacy_history_raw_bytes_v1` dictionary key is reserved throughout inputs to
prevent caller metadata from impersonating a byte commitment. Nonfinite values,
unsupported objects and invalid UTF-8 metadata are refused. Existing cohort,
review, one-MiB declaration and aggregate revision-authority bounds still apply;
the complete serialized report must also fit the existing eight-MiB report
bound. Oversized populations are refused without cropping a bank or branch.
Obtain resource admission before replaying these bounded but repeated checks.

Validators regenerate full results and compare canonical bytes, preserving
boolean/integer distinctions. Unit fixtures construct synthetic signatures and
exercise successors, failed predecessors, stale authority, source migration,
ancestor exclusion and equal-answer forks. Such fixtures do not establish
reviewer competence, statutory meaning or real deployment history.

The retained-data qualification profile uses the prior application report as
genesis with no revision steps. Its source banks contain no actual reviews,
applications or revision declarations. That profile inspects evidence continuity
and refusal of current use; it cannot demonstrate successful human review,
source selection, a legal graph, training quality or a Lean corpus. Qualification
outcomes and resource receipts are recorded separately from this API contract.
