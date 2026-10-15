# Typed source responses and pending adjudication

`logic/autoformal/corpus_source_review_responses.py` records explicit source and
context answer declarations, checks the content referenced by signed reviews,
and preserves every pending question and differing answer. The fixed
`corpus_source_review` owner still regenerates the original source population and
authenticates signatures. This layer accepts no adjudication, selects no
governing source, changes no original context, and admits no graph, training
target or Lean statement. Public import performs no source, crypto, model,
network or clock operation.

## Record a response before signing

`record_source_review_response(request, subject, response, *,
expected_request_sha256, expected_subject_sha256,
expected_preparation_manifest_sha256, limits=None)` returns a sealed candidate
record. Request and subject pins are their FULL canonical SHA256 values,
including their record CIDs. The preparation root also uses its FULL canonical
hash. These differ from payload-CID hashes and pretty/raw transport hashes.
Authoring checks the supplied identities and declarations; it does not replay
the source or authenticate the author. Qualification requires the assessment
step below.

The response input has exactly these fields:

- `review_id`, `principal_id`, `role`, `issued_at_utc`: explicit declarations that
  later must match the signed claim. Roles are `legal_review` or `formal_review`;
  time is explicit UTC seconds. No identity or clock is supplied automatically.
- `process_declaration`: `identity_evidence_refs`, `independence_evidence_refs`
  and `process_evidence_refs`, each an ordered list of at most eight exact
  `{artifact_id, sha256}` references. These declarations establish no human
  identity, competence or independence.
- `exposure_declaration`: `candidate_interpretations_exposed` and
  `organizer_source_metadata_exposed`, each boolean or explicit unknown `null`,
  plus `other_exposure`, nonblank text or unknown `null`. Unknown exposure never
  becomes false by default. A known absence of other exposure needs an explicit
  statement. Exposure remains declared, not verified.
- `answers`: all nine original active slots in their original order.

Each answer has `slot_id`, `category`, `kind`, `disposition`, `finding`,
`rationale` and `evidence_refs`. The first three fields match the original
question. Finding is a closed `{status, statement}` object. Finding status
`unavailable` or `ambiguous` requires disposition `unresolved`;
`evidence_declared` and `not_applicable` require their corresponding
dispositions. Statements and rationales are explicit nonblank text. Resolved and
not-applicable declarations require at least one evidence reference; unresolved
answers may have none. Tags prevent explicit unknown/resolved contradictions;
they do not independently judge the legal truth of prose assertions.

The record preserves all seven deferred question identities, exact source
binding, questions hash and dependency-manifest hash. It intentionally does not
embed its eventual signed-claim hash, which would create a hash cycle. Key, DID,
selected registry/policy, expiry and the actual signature remain in the signed
claim. `validate_source_review_response(record, request, subject, response,
**pins)` repeats authoring checks and compares every field.

## Reference exact response bytes in the existing signing domain

Serialize the sealed response into exact retained bytes before constructing the
signed claim. The raw SHA256 of those bytes is independently pinned. Each signed
review has one distinct response artifact; all nine ordered signed obligations
reference exactly that artifact ID and raw SHA256. Their dispositions map as:

| Typed answer | Signed obligation |
| --- | --- |
| `unresolved` | `open` |
| `evidence_declared` | `resolved_by_evidence` |
| `not_applicable` | `not_applicable` |

The signed `unresolved` list exactly preserves the ordered IDs of unresolved
typed slots. `declared_complete` cannot accompany any unresolved answer.
A conservatively `open` declaration is allowed even when every answer is
resolved; then its unresolved list is empty. The actual answer/process evidence
references are inside the response body, so the response hash binds them without
placing additional references in the signed obligations. The typed owner checks
their supplied raw bodies and hashes separately and rejects missing, changed or
self-referential evidence.

Retain the existing source claim schema/action/audience and Profile G signer.
There is no new signer, registry default or trusted-key generator. Legacy graph
and definition review domains do not substitute for this source domain.

## Assess the complete original population

`assess_source_review_responses(preparation, registry, policy, review_groups, *,
response_bindings, expected_response_bindings_sha256, source_review_limits=None,
limits=None, **source_inputs)` takes the unchanged complete source assessment
inputs. `source_inputs` contains exactly the existing preparation, registry,
policy, group pins, explicit evaluation time and five source-replay arguments.
There are no callbacks or packet-loader defaults. Optional `source_review_limits`
lowers the inherited profile; `limits` lowers this response profile.

Response bindings are a complete ordered list, one group per original request:
`{request_cid, responses: [{review_id, artifact_id, raw_sha256}]}`. Entries match
every signed review in order; groups with no reviews have empty responses.
Independently pin the entire list's canonical SHA256. Response bodies live in
that group's independently pinned `evidence_artifacts`; omitting or deduplicating
a review is refused. No response or interpretation is fabricated for an empty
group.

The fixed source assessment regenerates once for the whole batch. Every original
raw group assessment and all its blockers remain unchanged. Each response gets
a separate content result: valid declared content or rejected, its raw body
reference, and its original signature status. Invalid or unauthenticated bodies
retain their evidence identity but supply no authenticated answer variant. Only
valid bodies with authenticated signatures contribute variants. This means
authentication of bytes and validity of their typed contents stay separate.

Distinct reviewers usually reference distinct response bodies, producing
different raw context-declaration hashes even when their answer bytes agree.
The original `authenticated_context_declarations_disagree` blocker is retained.
Exact typed answer equality does not clear it or supply eligible legal consensus.
The comparison includes the entire answer: finding, rationale and evidence
references. Different prose or evidence remains a separate variant; this layer
does not infer equivalence.

The six output components are `manifest`, `pages`, `records`, `response_results`,
`answer_variants` and `adjudication_requests`. Pages preserve the complete global
request order. Every active slot has a pending adjudication request, including
missing answers, unresolved answers and equal declarations. Requests retain all
authenticated variants/respondents and explicit issues; adjudicator, decision,
rationale and evidence remain blank. A later authority/profile must accept
adjudication and decision application. Seven semantic/proof questions remain
deferred and original contexts remain required-unavailable.

## Bounds and regeneration

The common record/page envelope stays 1 MiB. This profile has a separate 64 MiB
output cap, 1 MiB response-body and binding-list caps, at most 8,192 groups or
responses, 32 signed reviews per group, 32,768 variants or adjudication requests,
and 256 pages of at most 64 group references. These interacting caps can refuse
a complete population; they never qualify a prefix. Known group, response and
nine-per-group adjudication limits are checked before source replay. Response
body limits are checked before hashing; inherited byte budgets still bound other
evidence. Producer file hashes are checked before and after operation.

`validate_source_review_responses(report, *inputs, **pins)` bounds the entire
offered output before regenerating the complete source/typed assessment once and
comparing every component. Repaired outer seals, edited blank decisions or
removed disagreements cannot replace that replay. Seals, pins, signature status
and exact answer equality are distinct from reviewed legal truth, authenticated
human identity and source/semantic/Lean qualification.
