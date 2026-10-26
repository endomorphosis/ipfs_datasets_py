# Legacy candidate stored-source bindings

`logic.autoformal.corpus_legacy_source_bindings` authenticates an explicitly
declared stored-section, occurrence, context and applicability tuple after
replaying the complete [source history](legal_legacy_source_history.md). Its
profile is `signed-legacy-candidate-structured-source-bindings/v1` and its effect
is `record_exact_declared_stored_section_occurrence_applicability_tuple_only`.

The [owner](../../corpus_legacy_source_bindings.py)
checks exact retained text geometry and separate signature authority. Declared
legal applicability remains a declaration: it does not become verified meaning,
governing-source adoption, training gold or a Lean theorem. Original candidate
records and governing/source-selection fields remain unchanged.

## Replay history before declaring a binding

```python
record_legacy_source_binding_declaration(
    history_report, history_replay_inputs, choice, *,
    bank_id, request_ordinal, expected_history_assessment_sha256,
    declared_at_utc, rationale, evidence_refs,
)

validate_legacy_source_binding_declaration(record, *args, **kwargs)

assess_legacy_source_bindings(
    history_report, history_replay_inputs, bindings, *,
    expected_history_assessment_sha256, expected_binding_input_sha256s,
)

validate_legacy_source_bindings(report, *args, **kwargs)
legacy_source_binding_input_sha256(entry)
```

`history_replay_inputs` is the complete closed argument dictionary for the
history assessor:

```python
history_replay_inputs = {
    "genesis_report": original_application_report,
    "genesis_inputs": complete_original_application_inputs,
    "revision_steps": complete_ordered_revision_steps,
    "genesis_epoch_id": supplied_genesis_epoch_id,
    "current_epoch_id": explicitly_selected_leaf_epoch_id,
    "at_time_utc": selected_leaf_evaluation_time,
    "expected_genesis_assessment_sha256": original_application_report_sha256,
    "expected_revision_step_sha256s": independently_pinned_ordered_step_hashes,
}
```

The owner regenerates all supplied epochs and their source, typed-response,
adjudication and signature checks. It reconstructs the selected leaf's source
population from those inputs rather than accepting a caller's source catalog.
The request's history result must be eligible for current use with all nine
answer references. Genesis-only history, visible forks, failed revision
authority or incomplete source-key inventories cannot authorize a binding.

`expected_history_assessment_sha256` hashes the canonical complete history
report, including its embedded `assessment_sha256`. It is distinct from that
embedded digest and the raw hash of an indented JSON file. The history report
reference has `{schema, sha256}` fields. Source and answer references use the
existing `{record_cid, sha256, schema}` record triples.

## Supply the exact stored-source choice

The closed `choice` dictionary is:

```python
choice = {
    "source_section_index": index_in_this_bank_preparation,
    "source_section_sha256": canonical_complete_section_sha256,
    "source_version_ref": source_version_record_ref,
    "source_occurrence_ref": occurrence_record_ref,
    "context_ref": context_declaration_record_ref,
    "declared_region_role": explicitly_declared_region_role,
    "applicability": {
        "scope_id": declared_scope_id,
        "jurisdiction_id": declared_jurisdiction_id,
        "instrument_id": declared_instrument_id,
        "legal_as_of_civil_date": declared_date_or_none,
        "evidence_occurrence_refs": supporting_occurrence_record_refs,
    },
}
```

`source_section_index` addresses the bank preparation's section list. It is not
the source Parquet row number. The full canonical section hash must match, and
the section must belong to the original request's declared section population.
Its exact SourceVersion reference must agree with the selected section. The
occurrence and context must be one linked candidate already retained for that
same request and section; mixing individually valid records from different
candidates is refused.

The existing geometry validators recheck the source version against the complete
stored text and its UTF-8 bytes, the occurrence against that version/text, and
the context declaration against that occurrence. Coordinates are half-open
Unicode-codepoint and UTF-8-byte ranges in the exact retained plain text.
Stored-text byte identity is distinct from the parent Parquet artifact hash and
from any official HTML representation. This profile creates no HTML alignment,
official-document comparison or recovered missing parent record.

The applicability evidence list must be nonempty, contain at most 256 distinct
occurrence references, and use exact original request candidates in the selected
section/version. These checks establish record membership and linkage. They do
not establish that a cited occurrence actually supports a legal applicability
claim.

The permitted region-role literals are `operative_body`, `editorial_note`,
`source_credit` and `unknown`. `unknown` can be preserved in a declaration but
blocks a complete positive binding assessment. The legal-as-of value must be a
real civil date in canonical `YYYY-MM-DD` form or explicit null. Null remains
visible and blocks a positive assessment; the string `"unknown"` is not a date.
Neither edition metadata nor signature time fills this field automatically.

Scope, jurisdiction and instrument IDs are explicit caller-supplied identifiers.
Their syntax is checked, but this owner does not resolve them against a legal
authority registry or verify their meaning. A syntactically valid label does
not establish jurisdiction, effective law, exceptions or repeal status.

Authoring also requires nonempty rationale and supporting artifact references.
The declaration binds the exact history/current-result hashes, request and
subject, preparation/source bindings, nine active answer references, and the
complete choice. It cannot follow the selected history evaluation or predate
the selected revision declaration and its claims. It remains unsigned intent.

## Submit complete separately authorized evidence

Assessment requires one ordered entry for every request in the current history
population, including absent bindings:

```python
entry = {
    "bank_id": bank_id,
    "request_ordinal": ordinal,
    "binding_registry": registry,
    "binding_policy": policy,
    "binding_reviews": complete_claim_list,
    "assessment_inputs": {
        "declaration_artifact_id": declaration_id_or_none,
        "expected_declaration_sha256": raw_declaration_sha256_or_none,
        "expected_binding_registry_sha256": registry_sha256,
        "expected_binding_policy_sha256": policy_sha256,
        "expected_binding_reviews_sha256": complete_claim_list_sha256,
        "observed_artifact_sha256s": current_artifact_observations,
        "observed_pins": current_pin_observations,
        "evidence_artifacts": exact_immutable_raw_bytes_by_id,
    },
}
```

`legacy_source_binding_input_sha256(entry)` checks the closed entry shape and
commits the complete metadata and tagged raw byte hashes/lengths through the
history commitment contract. It does not verify signature authority. Supply
its ordered hashes independently of the result. An absent declaration requires
a null hash and no claims; no default signer or policy fills the absence.

The binding signing domain is fixed:

| Item | Value |
| --- | --- |
| Claim schema | `legal-corpus-legacy-source-binding-signed-claim/v1` |
| Action | `record_legacy_candidate_structured_source_binding/v1` |
| Audience | `legal-autoformalization-legacy-source-bindings/v1` |

Legal and formal claims must authorize the same complete body under pinned
binding trust. Each of their nine obligations names only that declaration's
artifact identity and raw hash, preserves the selected answer's disposition,
and declares complete closure with no unresolved slots. Supporting artifacts
must match their raw hashes and cannot reference the declaration itself.
Prior revision or application signatures do not authorize this new action.

The binding verifier checks signatures, role separation, conflicts, evidence
and dependency closure at the history report's explicit evaluation time. Binding
claims cannot predate their common declaration. Binding signers are excluded
against every supplied epoch's source-review principals, DIDs and known raw keys,
including rejected original claims. Unknown source keys block eligibility.
Source history separately retains its adjudicator/revision checks. Human
identity, independence, current external registry state and clock authenticity
remain unverified.

## Read the output without promoting its meaning

The report retains the complete `history_assessment`, its canonical reference,
input commitments, selected epoch, evaluation time and all-epoch actor inventory
hash. Every request remains in `request_results`, with its exact current-history
result hash, authority assessment, declared content status, identity matches,
blockers and deferred semantic/proof questions.

`structured_source_binding_declared_under_selected_profile` becomes true only
when the current history prerequisite, exact body/geometry, a supported
non-`unknown` role literal, a non-null civil date, supporting bytes, signature
authority and actor checks all pass.
Then `declared_binding_refs` contains one reference to the authenticated
declaration. Otherwise it is empty. This is a declaration-authentication result,
not a proof that the occurrence is governing law.

`original_contexts_remain_required_unavailable` remains true. No candidate
occurrence or context is rewritten. `selected_occurrence` and governing fields
stay null; `decision_applied`, `structured_binding_establishes_legal_truth`,
`applicability_semantics_verified` and `governing_source_adoption_applied` remain
false. Source-decision and physical-governing-binding counts remain zero.
Meaning, graph, training and Lean authority are not promoted. There is no
filesystem/database publication or automatic current-head discovery.

## Bounds and qualification scope

One preflight bound covers the full history, replay inputs and prospective
binding data before expensive replay. The existing history limits remain in
force, including the combined 512 MiB input budget, 64 MiB commitment-metadata
budget and structural bounds. Binding entries additionally share an eight-MiB
metadata/evidence budget. Existing review/evidence limits, one-MiB declaration
limits and eight-MiB serialized-report limit still apply. Complete population
and ordered pins are required; failed or oversized rows are not silently cropped.

The owner performs bounded deterministic inspection but can replay substantial
upstream work. Obtain resource admission before invoking it. Validation helpers
regenerate complete results and compare canonical bytes, preserving distinctions
such as boolean false versus integer zero.

Synthetic fixtures can exercise positive declarations, signature and geometry
rejection, unknown role/date fields, and actor separation. They provide software
contract evidence, not real legal review. The selected retained public-data
profile supplies empty binding claims/declarations over a genesis-only history.
It tests preservation and refusal with absent prerequisites; it does not supply
a successful real binding or exercise a newly authorized real source choice.
Qualification outcomes and timing receipts are recorded separately from this
API contract.
