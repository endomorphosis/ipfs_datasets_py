# Typed responses for legacy source review

`logic.autoformal.corpus_legacy_source_responses` checks structured answers to
the [legacy source-review requests](legal_legacy_source_review.md). It reuses
their full source replay and fixed signature domain. It does not select source
occurrences, adjudicate legal meanings or admit training examples.

The profile is `typed-legacy-source-context-responses/v1`. It adapts the typed
answer protocol from the historical complete-parent response implementation;
that incompatible lineage profile is not restored or imported.

## Prepare and record

Prepare a blank template against an independently pinned, replayable request:

```python
from ipfs_datasets_py.logic.autoformal import corpus_legacy_source_responses as responses

template = responses.prepare_legacy_source_response_template(
    preparation,
    request_ordinal=ordinal,
    expected_preparation_manifest_sha256=preparation_manifest_sha256,
    **original_join_inputs,
)
```

`original_join_inputs` contains the original `join_bytes`, `paired_row_bytes`,
`expected_join_sha256`, expected row population, producer receipt and its hash,
and complete source sections and independent descriptors. Every call replays
the complete supplied bank before binding a request.

`template["response"]` contains null reviewer identity, role and issue time,
unknown exposure declarations, empty process-evidence lists, nine blank answers
and a blank occurrence proposal. It is explicitly unsubmitted and cannot be
passed as a completed response. No unavailable finding or review time is
invented from an empty field.

After receiving actual declarations, pass the completed response to
`record_legacy_source_response(preparation, response, **same_arguments)`.
`validate_legacy_source_response(record, preparation, response,
**same_arguments)` reproduces it. Recording does not sign or authenticate it.

The response requires these fields:

| Field | Required content |
| --- | --- |
| `review_id`, `principal_id`, `role`, `issued_at_utc` | Explicit declared identity, legal/formal review role and UTC issue time; later matched to the signed claim |
| `process_declaration` | Exact evidence references for identity, independence and process; empty references establish none of these |
| `exposure_declaration` | Candidate-interpretation and organizer-metadata exposure as explicit booleans or unknown, plus other exposure text or unknown |
| `answers` | Exactly nine ordered answers matching the original active slot, category and kind |
| `occurrence_proposal` | An unresolved proposal, or an explicit present-day proposal naming one original candidate CID with supporting evidence |

Each answer contains `slot_id`, `category`, `kind`, `disposition`,
`finding: {status, statement}`, `rationale` and `evidence_refs`. References
contain `artifact_id` and the exact raw `sha256`, with at most eight per list.

| Finding status | Answer disposition | Signed obligation disposition |
| --- | --- | --- |
| `unavailable` or `ambiguous` | `unresolved` | `open` |
| `evidence_declared` | `evidence_declared` | `resolved_by_evidence` |
| `not_applicable` | `not_applicable` | `not_applicable` |

Evidence-declared and not-applicable answers require supporting evidence.
Unknown findings cannot be relabeled resolved. The seven semantic/proof
questions remain deferred and cannot be inserted into the active answer list.
A present-day occurrence proposal is bound to the exact source candidate,
including its derived CID/hash reference; it never attests what the original
producer selected. Its supporting evidence is checked along with answer and
process evidence.

## Authenticate and inspect answers

Serialize the completed record and retain its exact raw bytes. Each original
legacy-domain signed claim must reference only that response body's
`{artifact_id, sha256}` in every active context obligation. Each obligation's
disposition must match the corresponding typed answer. The closure's unresolved
list must exactly enumerate the unresolved slots, and its status must be
`open` if any remain, otherwise `declared_complete`.

Call `assess_legacy_source_responses` with the same preparation, registry,
policy, reviews and independently pinned inputs used by
`assess_legacy_source_review`, plus:

```python
response_bindings = [
    {"review_id": review_id, "artifact_id": response_artifact_id,
     "raw_sha256": exact_response_bytes_sha256},
    # One entry for every signed review, in its original order.
]
```

Supply the independently expected canonical digest as
`expected_response_bindings_sha256`. Put exact response bodies and all cited
supporting/process/proposal evidence bodies in `evidence_artifacts`. No keys,
signer, policy, trust or evaluation clock is supplied by this module.

The assessment preserves separate facts:

- `raw_source_assessment`: original signature and dependency results, with
  every original blocker unchanged.
- `response_results`: one result per submitted review, including missing or
  rejected content; signature authentication and typed-content validity are
  separate fields.
- `answer_variants`: exact authenticated typed answers grouped by complete
  canonical bytes. Different wording, rationale or evidence creates a distinct
  exact variant; this is not proof of semantic contradiction.
- `pending_questions`: all nine source/context slots, including unresolved,
  missing and differing answers. Even identical signed answers remain pending
  separate adjudication.
- `occurrence_proposals`: independently supplied authenticated proposals,
  with no selected winner or change to original source records.

Different reviewers' response bodies naturally produce different signed
context-declaration hashes. The original
`authenticated_context_declarations_disagree` blocker remains visible even
when typed answers match. The separate [common adjudication declaration](legal_legacy_source_adjudication.md)
binds consideration of these variants and disagreement; the typed checker does
not erase the original blocker.

`validate_legacy_source_responses(report, ...original_arguments)` regenerates
the complete result. Canonical-byte comparison rejects boolean/integer
substitutions such as `false` → `0`; unchanged CIDs cannot validate altered
records. Noncanonical JSON whitespace is allowed only when the signed raw
hash matches those exact bytes and the decoded content reproduces correctly.

## Scope and limits

The existing limits remain: 32 reviews, 256 evidence bodies, 8 MiB aggregate
authentication input and assessment serialization, and 1 MiB individual corpus
records. Complete-population and byte-bound violations refuse the operation;
invalid individual response content remains in the result denominator.
Complete source-bank replay still precedes authentication. Code-version custody
remains an external execution-manifest responsibility.

Typed validation checks structure, bindings and declaration consistency. It
does not assess whether the legal evidence is adequate or the finding is true,
verify human competence/independence, or apply a source decision. A compatible
decision-application path and actual independent review remain necessary before
these cache observations can become reviewed semantic training targets.

The enclosing workspace's
`artifacts/legal-paired-typed-responses-20261016-01/` contains the bounded
qualification, exact source capture and retained-data results. Its public-data
inputs contain no actual responses; fabricated legal reviews are not used to
make that cohort complete.
