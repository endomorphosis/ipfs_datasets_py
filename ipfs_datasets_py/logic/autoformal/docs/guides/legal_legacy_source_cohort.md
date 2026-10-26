# Complete legacy source-review cohorts

`logic.autoformal.corpus_legacy_source_cohort` binds all declared banks, requests
and supplied source reviews before checking adjudicator separation. A source
reviewer on one request cannot escape exclusion by adjudicating another request
or bank. Rejected signatures and invalid typed bodies remain in the inventory.

The module extends the [common adjudication assessment](legal_legacy_source_adjudication.md)
without changing its signed declaration bytes. Its profile is
`complete-declared-legacy-source-review-cohort/v1`. A cohort assessment is a
separately bound check, not a claim that adjudicators signed the cohort or that
distinct keys represent independent people.

## Supply an independently fixed population

`prepare_legacy_source_review_cohort` takes a nonempty list of banks. Each bank
has exactly these fields:

```python
bank = {
    "bank_id": bank_id,
    "preparation": original_preparation,
    "source_registry": original_registry,
    "source_policy": original_policy,
    "requests": [
        {"typed_assessment": original_typed_report,
         "source_reviews": complete_original_review_list,
         "response_inputs": original_typed_assessment_keyword_inputs},
        # Every prepared request, in preparation order, including empty reviews.
    ],
}
```

`response_inputs` is the complete input set for
`assess_legacy_source_responses`, including original byte bodies, independent
source/response/trust pins, response bindings, observations and evaluation time.
The new owner fully regenerates each typed assessment through the existing
source and response owners. It does not accept a stored successful status alone.

Supply `expected_population` independently of the new cohort output. It is an
ordered list of bank descriptors:

```python
expected_bank = {
    "bank_id": bank_id,
    "preparation_sha256": whole_preparation_canonical_sha256,
    "registry_sha256": registry_canonical_sha256,
    "policy_sha256": policy_canonical_sha256,
    "requests": [
        {"request_ref": {"record_cid": request_cid,
                         "sha256": whole_request_canonical_sha256,
                         "schema": request_schema},
         "typed_assessment_sha256": whole_typed_report_canonical_sha256,
         "source_reviews_sha256": complete_review_list_canonical_sha256},
    ],
}
```

The canonical recipe is the existing `legal_graph_review.wire` / `digest`
recipe, including embedded report hashes. Pin the entire expected list with
`expected_population_sha256`. Missing, reordered or duplicated banks/requests
are refused. A smaller expected request list cannot hide requests still present
in a prepared bank. The same request CID cannot appear under two bank labels.
Completeness is relative to this explicitly selected population; an authoritative
submission service must establish that no externally submitted reviews were
omitted. The owner cannot discover submissions or authenticate scope selection.

## Preserve every supplied identity

The sealed cohort retains each review's digest, declared principal, DID, key,
role, signature status and typed-content status. For a known key it also retains
the registered principal, DID and public-key bytes. A rejected claim that names
a mismatching identity excludes both its claimed identity and the registered
identity of the referenced key. Structurally accepted claims that fail
authentication or typed-content checks are not silently discarded or treated
as proof that the claimed person participated. Malformed claim schemas refuse
the operation instead of entering this inventory.

`excluded_principal_ids`, `excluded_signer_dids` and `excluded_public_keys`
cover the complete supplied cohort. An unknown key retains available claimed
identities and increments `counts.unknown_key_reviews`. This incomplete key
inventory blocks every combined prerequisite result; it cannot establish clean
key separation. The conservative exclusion policy may require an external
review of erroneous submissions. It supplies no automatic deletion or override.

`validate_legacy_source_review_cohort(cohort, banks, **same_arguments)` fully
regenerates the record and compares canonical bytes.

## Check all adjudications against the cohort

`assess_legacy_source_cohort_adjudications` takes the cohort, the original banks
and a flat adjudication list in the same bank/request order. Each entry contains:

```python
entry = {
    "bank_id": bank_id, "request_ordinal": ordinal,
    "assessment": original_adjudication_report,
    "adjudication_registry": registry,
    "adjudication_policy": policy,
    "adjudication_reviews": complete_claim_list,
    "assessment_inputs": original_adjudication_keyword_inputs,
}
```

Omit `response_inputs` and `expected_typed_assessment_sha256` from
`assessment_inputs`: the owner derives them from the bound cohort member.
All remaining original adjudication keywords, including exact evidence bytes,
trust pins, declaration references, observations and evaluation time, are required.
Along with the expected population and its hash, independently supply
`expected_cohort_sha256` and the complete ordered
`expected_adjudication_assessment_sha256s` list.

The batch replays the whole cohort and every original adjudication assessment.
Each result binds its bank, request and original assessment hash. It reports
the original prerequisite result, identity exclusion matches, blockers and
`cohort_authority_prerequisites_satisfied`. Original prerequisite failure,
any cross-cohort identity match, or incomplete source-key coverage prevents a
positive combined result. Rejected adjudication claims remain in the checked
claim population as well.

`validate_legacy_source_cohort_adjudications(report, ...same_arguments)` repeats
the full operation. All assessment hashes and canonical type distinctions are
preserved; `false` cannot be replaced with `0`.

## Scope, resources and next handoff

Limits are eight banks, 64 total requests and 256 total **source** claims,
alongside the existing per-request 32-review limits. The 512 MiB logical input
budget counts repeated supplied byte references; it is not measured memory,
physical I/O or an elapsed-work guarantee. Individual sealed cohorts remain
bounded to 1 MiB. Adjudication inputs and the final batch report have separate
8 MiB bounds. The caller is responsible for resource admission before execution.

Each request retains its explicit evaluation time and pinned registry snapshot.
The batch does not establish a simultaneous current-time view or discover newer
revocations. An application must requalify source and adjudication authority
and dependencies at its own evaluation time, bind the complete cohort and obtain
separate application authorization.

The [legacy genesis application adapter](legal_legacy_source_application.md)
implements this separate action for nine logical answer references. Successor
history and physical source-binding decisions remain distinct contracts.

Even positive combined results leave source selection, governing source, meaning,
graph admission and training qualification pending. Applied-decision counts stay
zero. Human identity, competence and independence, source authenticity and legal
meaning still need their own evidence. The historical logical application effect
copies selected answer references; physical source binding and semantic admission
are distinct contracts.

The enclosing workspace's `artifacts/legal-paired-review-cohort-20261016-01/`
contains the qualification and retained-input inventory. Synthetic positive
tests are engineering fixtures; the retained public banks contain no actual
reviews or adjudication declarations.
