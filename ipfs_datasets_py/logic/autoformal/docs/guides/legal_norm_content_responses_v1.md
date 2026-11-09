# Typed norm interpretation responses

`legal_norm_content_responses_v1` records and authenticates typed reviewer
proposals about one exact candidate from the existing
[norm interpretation review](legal_norm_interpretation_review_v1.md). It binds
substantive answers to the source and typed AST inventories already replayed by
that owner. It supplies no reviewer, signer, trust registry, policy, clock,
accepted interpretation or training admission.

The companion uses the existing norm signing domain. Every signed context
obligation must reference the complete response body by its artifact ID and
exact raw-byte SHA256. Reviewer identity, role, issue time, candidate decision,
answer dispositions and unresolved population must agree with the signed claim.
Existing claims without those body references cannot authenticate later-added
answers. Original subjects and signatures are not rewritten.

## Prepare and submit content

Use the same complete original inputs and independent commitments accepted by
`build_norm_review_subject_v1`:

```python
from ipfs_datasets_py.logic.autoformal import legal_norm_content_responses_v1 as content

template = content.build_norm_content_template_v1(
    preparation, dependency_manifest, **subject_build_inputs,
)
record = content.build_norm_content_response_v1(
    preparation, dependency_manifest, supplied_response, **subject_build_inputs,
)
```

Both operations replay the original norm preparation, source/context
correspondence and dependency subject. The template includes exact original
obligations, source rows, typed context inventory and context nominations. Its
null reviewer and answer fields are blank, unsubmitted fields, not responses.

A supplied response has exactly these fields:

| Field | Content |
| --- | --- |
| `review_id`, `principal_id`, `role`, `issued_at_utc` | Explicit reviewer metadata matching the original-domain signed claim. |
| `process_declaration` | Ordered identity, independence and process evidence references. Their contents remain supplied declarations. |
| `exposure_declaration` | Candidate/organizer exposure booleans or explicit unknown values, plus other exposure text or unknown. |
| `candidate_proposal` | Support, reject or unresolved; exact existing typed-expression/native-AST hashes; rationale and evidence references. No replacement AST. |
| `answers` | One explicit ordered answer per original context obligation, unresolved issue and interpretation question. |
| `governing_definition_use` | Explicit `None` in this profile. |

Each answer binds `slot_id`, `kind` and the exact original obligation hash, then
supplies a disposition, rationale, evidence references and a closed typed
finding. Dispositions are `evidence_declared`, `not_applicable` or `unresolved`.
Non-unresolved answers and support/reject proposals require supplied evidence.

| Finding family | Bound content |
| --- | --- |
| Original context or issue | Exact original record hash and a supplied statement. |
| Source meaning | Existing ordered source rows with support/dispute/unresolved assertions. |
| Participant roles | Exact source-linked typed targets, complete inverse source paths, declared roles and assessments. A reused symbol name is insufficient. |
| Condition/modal scope or exceptions/time | Exact existing typed contexts, binder/argument/ancestry records and inverse source anchors, with the relevant scope aspect and a statement. |
| Source coverage | Every original source row, in order, declared covered/missing/uncertain. |
| Unsupported grammar | Exact source anchors and cited constructs, or an explicit none-declared finding. |
| Definition applicability | Explicitly unresolved, with null governing use. |

These are typed claims about an offered interpretation. Matching their source
and AST references does not establish their legal truth. The existing
[definition evidence companion](legal_norm_definition_evidence_v1.md) retains
term-use nominations and alternatives separately; this response profile neither
selects those links nor imports a replacement definition assessment.

## Authenticate the complete population

`assess_norm_content_responses_v1` accepts the same subject, registry, policy,
reviews, dependency manifest and full keyword inputs as
`assess_norm_reviews_v1`, plus `response_bindings` and
`expected_response_bindings_sha256`. There must be one ordered binding per signed
review, with exactly `review_id`, `artifact_id` and `raw_sha256`.

Supply the exact response bytes in `evidence_artifacts`. Every signed obligation
references that whole body; its disposition must match the corresponding typed
answer. Signed closure status and the ordered unresolved-slot list must also
match. Supporting answer, proposal and process evidence must be supplied
separately. No submitted response body, body ID or byte-identical alias can serve
as that supporting evidence.

The assessment retains the complete original norm authentication report, every
response result, exact answer variants and a pending record for every original
obligation. Missing or malformed bodies remain rejected content results beside
their original authentication status. Authenticated reject/unresolved responses
and different answers remain visible. No majority, agreement or signature
automatically selects an interpretation: all content decisions and governing
definition uses remain null, readiness remains false, and semantic/training/gold
authority and masks remain false/zero.

## Hashes, replay and bounds

Raw response references hash exact UTF8 bytes. `norm_content_sha256(value)` uses
the existing bounded norm canonical UTF8 recipe and hashes the complete offered
value, including an embedded digest when present. Compact subject, registry,
policy, review and response-binding pins keep the graph-review digest recipe.
Profile G signs the existing claim CID; the companion adds no signature codec.

`validate_norm_content_assessment_v1(report, ..., expected_report_sha256=pin)`
requires an independently retained complete-report pin and all original
assessment inputs, regenerates the assessment and compares exact canonical
content. An edited report cannot acquire authority by recomputing its own hash.
Input snapshots and producer checks surround replay and final serialization.

Response bodies use the existing strict JSON reader and integer review profile:
8 MiB, depth 32 and 100,000 nodes. Duplicate keys, nonfinite values and invalid
UTF8 are rejected. Findings allow at most 128 assertions and evidence lists at
most eight references. Complete coverage retains its full upstream population.
The existing 512-obligation and 32-unresolved-slot signing limits remain; inputs
are rejected rather than truncated to fit. Full preparation/report limits remain
with the existing norm owners.

The enclosing workspace's [qualification record](../../../../../../../artifacts/legal-norm-content-responses-20261016-01/README.md)
records 121 passing cases with fictional source/context evidence and signature
fixtures. Fresh original-input replays also produced blank templates for both
retained §7213 hypotheses, each preserving all 19 obligations. They concern one
physical use and contain no submitted reviews or selected meanings. Actual
statutory responses require supplied substantive reviews and selected trust inputs.
Content adjudication, governing-definition applicability, reviewed target masks,
graph/Lean4 admission and training remain subsequent integrations.


## Unsigned parent review worksheet

`build_parent_norm_content_template_v1` and
`validate_parent_norm_content_template_v1` add a blank manual consumer for
[unsigned parent review evidence](legal_norm_interpretation_review_v1.md#unsigned-parent-literal-occurrence-review-evidence).
The schema is `legal-parent-norm-content-template/v1`, with profile
`unsigned-parent-literal-content-worksheet/v1`. This worksheet is not a
submitted response or an extension of the signing/assessment domain above.

```python
worksheet = content.build_parent_norm_content_template_v1(
    parent_preparation,
    expected_preparation_sha256=independent_parent_preparation_sha256,
    correspondence=parent_correspondence,
    expected_correspondence_sha256=independent_parent_correspondence_sha256,
    correspondence_inputs=complete_original_parent_correspondence_inputs,
)
content.validate_parent_norm_content_template_v1(
    worksheet,
    parent_preparation,
    expected_report_sha256=independent_worksheet_sha256,
    expected_preparation_sha256=independent_parent_preparation_sha256,
    correspondence=parent_correspondence,
    expected_correspondence_sha256=independent_parent_correspondence_sha256,
    correspondence_inputs=complete_original_parent_correspondence_inputs,
)
```

Both full canonical hashes must come from retained independent inputs.
`norm_content_sha256(worksheet)` computes the complete worksheet digest; no
embedded seal, CID, raw-byte hash or copied validation flag substitutes for it.
`correspondence_inputs` remains the exact nine-field original parent-v2 replay
mapping accepted by the unsigned parent review owner. There is no external
context input, offered dependency manifest, registry, policy, clock or signer
argument on this route.

Preparation and validation each invoke genuine parent-review validation at
opening and finally closing. The review validator in turn regenerates the
original correspondence and physical parent source. Original/detached inputs,
parsed requests, actual selected producer sources, returned preparation and
final detached output remain fenced, including on failure. A separate parent
producer baseline avoids the legacy signing/context route. Offered producer
paths do not select files to read. The original error remains primary if
closing custody checks also fail.

The worksheet retains the complete `preparation`, its full independent hash,
source identity, genuine original context, ordered obligations, exact source
rows, typed context inventory and the preparation's declared dependency
manifest. This last manifest remains custody evidence for the preparation; it
is not an assertion of complete legal dependencies or current freshness.

Its `response` uses familiar blank fields:

- Reviewer/principal IDs, role, issue time, candidate decision, rationale and
  answer dispositions remain null.
- Process and supporting evidence-reference lists remain empty. Exposure
  declarations remain unknown rather than asserting that no exposure occurred.
- Candidate typed-expression and native-AST hashes retain the original syntax
  commitments; no replacement formula or accepted interpretation is inserted.
- Every ordered parent-context, source-issue and interpretation-question row
  gets one blank answer with its exact obligation hash.

For `original_parent_context`, the finding has `family`, a null `statement` and
`original_sha256` committing that complete derived obligation payload. Other
families reuse the existing blank-finding construction: definition applicability
stays explicitly `unresolved` with null governing use, coverage retains all
source rows, and grammar/source/role/scope assertions remain blank. No answer is
inferred from a matched anchor or valid typed expression.

`subject`, `subject_sha256`, `signature`, `clock`, `registry` and `policy` remain
null. `unsigned_only` is true and `response_submission_allowed` is false. The
existing response, signing, declaration-binding and adjudication consumers keep
their closed profiles and reject this worksheet. Completing fields in a copy
cannot turn it into an accepted worksheet: validation regenerates the exact
blank result from complete original inputs. A later reviewed compatibility
profile is required for supplied responses or authentication; no signatures or
trust inputs are constructed here.

The complete report stays within the existing 8 MiB bound; snapshots retain
the 128 MiB aggregate input and 512-obligation limits and inherited node/depth
bounds. Larger material is refused without flattening, truncating or dropping
rows. The old signed-body limits above are not silently relaxed by this unsigned
profile.

The selected literal occurrence may be a fragment or unclassified region.
Edition, all six context requirements, source issues, partial semantics,
definition applicability and substantive legal meaning stay unresolved. All
authority and readiness flags remain false; semantic, consumer, training and
evaluation-gold masks remain integer zero. Human reviews, signatures,
admissions, model/training/native process counts and governing selections remain
zero or null. No graph, training target, solver or Lean process is supplied.

The [saved owning qualification](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-programme-review-20261022-05/parent-norm-review-20261024-root-c5a19e73/qualification-summary-v01.json) passed **40 cases / 120 phases**: 35 new parent controls and five selected legacy cases on the captured current producers. Original native, source READ and storage closed. This namespace-scoped qualification covers custody, refusal behavior and blank unsigned preparation only; it does not establish whole-package startup, completed statutory review, signatures, legal meaning, model accuracy, graph or Lean admission. The historical parent scope 185-case qualification and peer wire results remain separate.

## Parent review and blank worksheet: closing custody, 2026-10-24

Use the existing `prepare_parent_norm_review_evidence_v1` and `validate_parent_norm_review_evidence_v1` under `unsigned-parent-literal-occurrence-review/v1` (`legal-parent-norm-review-evidence/v1`). Supply the complete parent correspondence v2, its independently retained canonical hash and the closed nine-field original `correspondence_inputs`, including the exact physical-parent replay. The evidence retains explicit manifest/source-version/occurrence/companion/context identities, all six unavailable context requirements, every repeated issue, seven semantic questions, complete authored typed syntax and declared dependency custody. Reuse `build_parent_norm_content_template_v1` and `validate_parent_norm_content_template_v1` in the existing content owner for `unsigned-parent-literal-content-worksheet/v1` (`legal-parent-norm-content-template/v1`). Both require the complete preparation and its independent hash plus the original correspondence/hash/replay; worksheet validation also requires its independent complete report hash. All answers, process/exposure declarations, evidence and governing decisions remain blank or unknown. This worksheet cannot be submitted through legacy response/signing/adjudication APIs. The selected literal can be an interior slice or unclassified region. Whole-field context, governing edition, legal meaning, definition applicability and graph/Lean corpus admission remain open; training/gold masks remain zero. Existing 128 MiB aggregate snapshot, 8 MiB output and 512-obligation limits refuse overflow without truncation. The narrow hardening checks original/detached inputs, parsed requests and actual retained validator/dependency objects after the final genuine callback, then checks the returned bytes through direct encoding. Public schemas, fields and function signatures retain the selected peer contract.

The fresh focused qualification passed **16 cases / 48 phases from 10 selectors**, including genuine preparation/worksheet controls and targeted late-mutation refusals. It uses declared parent namespaces and checked source buffers; bypassed initializers, entire owning modules and full package startup remain unqualified. The peer original 40-case/120-phase campaign retains its own frozen generation. The earlier alternate 74-case/222-phase candidate was not installed after overlap was discovered; these counts are never combined. Its failed fixture attempt, supported 256 MiB storage closeout and unrun stale capture remain separate evidence. No model, training, law download or Lean build ran for this hardening. See the [qualification evidence](../../../../../docs/autoformalization/evidence/legal-ir-parent-norm-review-closing-custody-20261024.json).


## Filled unsigned parent response

The existing content owner adds a separate response transport to the blank
parent worksheet: `build_parent_norm_content_response_v1` and
`validate_parent_norm_content_response_v1`. Its report schema is
`legal-parent-norm-content-response/v1` and its explicit profile is
`unsigned-parent-literal-content-response/v1`. A filled response is a caller's
declaration, not an authenticated review, completed legal interpretation or
adjudication. The older blank worksheet and all signing and assessment profiles
keep their existing contracts.

Extract and fill the worksheet's `response` fields as an ordinary JSON object,
then independently retain its full `norm_content_sha256` commitment. Do not
edit a worksheet and present it to the blank-template validator: that validator
still regenerates the exact blank form. The new builder instead receives the
complete original preparation, its independent full hash, the filled response
and its independent full hash, the original parent correspondence/hash and the
same closed nine-field `correspondence_inputs` used above. It does not require
a nested worksheet, signing subject, registry, policy, clock or credential.

```python
report = content.build_parent_norm_content_response_v1(
    parent_preparation,
    filled_response,
    expected_preparation_sha256=independent_preparation_sha256,
    expected_response_sha256=independent_filled_response_sha256,
    evidence_manifest=evidence_manifest,
    expected_evidence_manifest_sha256=independent_evidence_manifest_sha256,
    evidence_artifacts=exact_raw_evidence_bodies,
    correspondence=parent_correspondence,
    expected_correspondence_sha256=independent_correspondence_sha256,
    correspondence_inputs=complete_original_parent_correspondence_inputs,
)
content.validate_parent_norm_content_response_v1(
    report,
    parent_preparation,
    filled_response,
    expected_report_sha256=independent_complete_report_sha256,
    expected_preparation_sha256=independent_preparation_sha256,
    expected_response_sha256=independent_filled_response_sha256,
    evidence_manifest=evidence_manifest,
    expected_evidence_manifest_sha256=independent_evidence_manifest_sha256,
    evidence_artifacts=exact_raw_evidence_bodies,
    correspondence=parent_correspondence,
    expected_correspondence_sha256=independent_correspondence_sha256,
    correspondence_inputs=complete_original_parent_correspondence_inputs,
)
```

The evidence manifest has exactly these fields:

```json
{
  "schema": "legal-parent-norm-response-evidence/v1",
  "artifacts": [
    {
      "artifact_id": "declared-evidence-1",
      "bytes": 123,
      "sha256": "<SHA256 of those exact 123 raw bytes>"
    }
  ]
}
```

The independently retained `norm_content_sha256(evidence_manifest)` commits the
entire ordered artifact population. `evidence_artifacts` is a plain mapping of
exactly the same IDs to `bytes` objects. IDs are declarations and are never
interpreted as paths to open. Manifest IDs are unique; byte lengths are positive
plain integers, not booleans. Empty populations are permitted for entirely
unresolved declarations. At most 256 artifacts and 8 MiB of aggregate exact
body bytes are accepted. Every supplied body is hashed before any upstream
validator runs, including bodies not cited by an answer. A missing, extra,
truncated, rehashed or otherwise differing population is refused rather than
silently reduced.

Each evidence-reference list has at most eight distinct IDs and exact
`artifact_id`/`sha256` fields. Every reference must match the manifest and the
supplied raw body. Direct body hashes equal to the pinned response,
preparation, correspondence or offered validation report are refused as
self-support. These structural checks do not detect all alternate encodings or
substantively circular documents. They do not verify evidence identity,
independence, relevance or truth. Raw evidence bodies remain separately retained
inputs: the report contains the full manifest and ordered byte/hash
observations, without embedding all bodies again. Later validation requires
the original bytes again.

The filled response retains the exact familiar `INPUT_FIELDS`. Reviewer and
principal IDs must match `[a-z0-9][a-z0-9_.:@/-]{0,255}`; the declared role is
`legal_review` or `formal_review`. `issued_at_utc` supplies a valid calendar time
in `YYYY-MM-DDTHH:MM:SSZ` form. These are caller declarations only. No clock,
identity, independence, competence, registry or signature check is inferred.
Process references receive the same raw-body checks. Exposure fields retain
explicit boolean-or-unknown values; no lack of exposure is invented.

The candidate proposal references the original typed-expression and native-AST
hashes and supplies a nonblank rationale. Support or rejection requires a
supplied raw evidence reference. Each original ordered obligation requires one
exact matching slot/kind/obligation hash, explicit disposition, nonblank
rationale and a closed typed finding. Non-unresolved dispositions require
supplied evidence references; their content remains a proposal only.

For every `original_parent_context` answer, the finding is exactly
`family`, `statement` and `original_sha256`, with the full original derived
requirement hash. All six genuine context requirements remain
`required_unavailable`, and every such answer must stay `unresolved`, even if it
cites bytes. The existing finding validators handle all other families against
the unchanged source rows, typed targets and context ancestry. Definition
applicability must remain explicitly `unresolved`, with no governing use.
Answers cannot change the original occurrence, its extent, source edition,
context population or authored formula. No interpretation is selected.

Build and validation perform genuine parent-review validation at opening and
finally closing using the complete original correspondence and physical replay
inputs. They retain the current parent producer closure, without invoking the
legacy signing/HTML-context owner path. Caller and detached inputs, parsed
declarations, all raw evidence, trusted producers and actual retained validator
returns are checked through closing. The final encoder rechecks producer pins
and direct input/returned-object fingerprints after its callback; independent
serialization then checks the actual detached return. An earlier operation
error remains primary if closing checks also fail, with secondary failures
retained as notes. These sequential checks are not an atomic snapshot or a
substitute for later original-input replay.

The report preserves the complete preparation, source identity/context,
ordered obligations and source/typed inventories, custody-only dependency
manifest, full filled response and all independent commitments. Its status is
`declared_unsigned_parent_response_not_authenticated`.
`unresolved_obligation_ids` follows the exact original answer order. No legal
completion or readiness flag is created. Subject, signature, registry, policy,
clock, governing use and accepted interpretation remain null. All authority,
evidence identity/independence/truth and reviewer-verification flags remain
false; semantic, consumer, training and evaluation-gold masks remain integer
zero. No human-review credit, authentication, content adjudication, semantic
graph, model/training process or Lean admission is supplied.

Existing bounds still apply: 8 MiB complete output, 128 MiB aggregate snapshots,
512 complete obligations and inherited assertion/node/depth limits. A larger
parent preparation or evidence collection cannot raise these limits. Overflow
is refused without truncation, omitted answers or invented completion.

The [saved focused qualification](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-programme-review-20261022-05/parent-norm-responses-20261024-root-a64d82f1/qualification-summary-v01.json) passed **23 cases / 69 phases**: 20 new unsigned-response controls and three selected legacy cases on the original frozen195 snapshot, including imported adapter `2d977fa6…`. Later canonical adapter `0de6dafb…` is preserved through the independently pinned static selected-parent-path review; the new coordinate APIs are not qualified by this run. Original native, source READ and storage closed. This namespace-scoped qualification covers exact declaration/evidence custody, genuine parent replay and refusal behavior only; it supplies no authenticated review, completed statutory meaning, whole-package startup, signing/adjudication, model accuracy, graph or Lean admission. Earlier 40-case / 120-phase review/worksheet and peer 16-case / 48-phase closing-custody results retain separate generations.

## Selected parent response and parallel result reconciliation, 2026-10-24

Use the installed raw-evidence contract above, source `7bc2fb42`: both APIs require the independently pinned evidence manifest and exact complete raw evidence bodies. All six unavailable parent-context obligations stay unresolved. Its original **23 cases / 69 phases** belong to its frozen generation; the later graph-adapter update retains the separately documented static selected-path compatibility limit. A parallel declared-references-only candidate (`e242bacb`) subsequently passed **42 cases / 126 phases**, including one tiny isolated cold export check, with original compute/storage/source READ closed and zero live processes. That candidate is **uninstalled**. Despite sharing API and profile strings, it omits the mandatory raw-evidence parameters and allows context answer declarations the selected contract refuses. Its result is retained as a separate alternative, supplies no cases or current-source qualification to this owner, and is not another active implementation. Reuse the installed contract for future work; any useful additional refusal coverage needs a compatible, source-bound owning test change. No authentication, substantive review, meaning, training/gold, graph or Lean authority follows from either transport. See the [reconciliation evidence](../../../../../docs/autoformalization/evidence/legal-ir-parent-response-peer-reconciliation-20261024.json).


## Collection of supplied unsigned parent responses

`collect_parent_norm_content_responses_v1` and
`validate_parent_norm_content_collection_v1` retain a bounded, explicitly
supplied population for one exact parent candidate. The collection report uses
`legal-parent-norm-content-collection/v1` and the distinct profile
`unsigned-parent-literal-response-collection/v1`. It supplies an inventory of
declarations and exact answer variants. It does not authenticate reviews,
establish a quorum, choose a meaning or extend a signing/adjudication domain.

The population manifest is ordinary JSON with exactly these fields:

```json
{
  "schema": "legal-parent-norm-response-population/v1",
  "responses": [
    {"review_id": "declared-review-1", "report_sha256": "<full independent report SHA256>"}
  ]
}
```

Independently retain `norm_content_sha256(population_manifest)`. Its ordered rows
must correspond exactly to an ordered `reports` list and an ordered
`evidence_artifacts` list. Each evidence entry is the original raw-body mapping
for that report, as required by the single-response consumer above. Raw bytes
do not go in the JSON population manifest and cannot be hashed by calling
`norm_content_sha256` on a packet containing `bytes` values.

There may be zero through 32 rows. Declared review IDs must be unique; duplicate
IDs are refused rather than silently deduplicated. All member reports bind the
same complete preparation and correspondence, supplied under independently
retained full hashes and the original closed nine-field replay mapping.

```python
collection = content.collect_parent_norm_content_responses_v1(
    parent_preparation,
    population_manifest,
    current_response_reports,
    expected_preparation_sha256=independent_preparation_sha256,
    expected_population_manifest_sha256=independent_population_manifest_sha256,
    evidence_artifacts=original_raw_body_maps_in_population_order,
    correspondence=parent_correspondence,
    expected_correspondence_sha256=independent_correspondence_sha256,
    correspondence_inputs=complete_original_parent_correspondence_inputs,
)
content.validate_parent_norm_content_collection_v1(
    collection,
    parent_preparation,
    population_manifest,
    current_response_reports,
    expected_report_sha256=independent_complete_collection_sha256,
    expected_preparation_sha256=independent_preparation_sha256,
    expected_population_manifest_sha256=independent_population_manifest_sha256,
    evidence_artifacts=original_raw_body_maps_in_population_order,
    correspondence=parent_correspondence,
    expected_correspondence_sha256=independent_correspondence_sha256,
    correspondence_inputs=complete_original_parent_correspondence_inputs,
)
```

The complete member report independently commits its filled response and
raw-evidence manifest. The collection derives these original arguments from
that pinned report and invokes the existing genuine
`validate_parent_norm_content_response_v1`, with its raw bytes and complete
original replay inputs. It does not accept a saved validation flag or a
same-schema declared-reference-only report. The separately qualified `e242`
alternative remains uninstalled and incompatible, as recorded above; its
cases are not collection qualification.

Appending this owner changes its whole-file producer hash. Member reports must
therefore be freshly rebuilt with the existing single-response builder under
the selected collection-owner source generation, from complete original
declarations, evidence and replay inputs. Historical `7bc2` reports retain their
own source generation. Removing, normalizing or replacing their producer pins,
or recomputing only their outer hash, cannot make them current.

Before any producer pinner or upstream validator, the collection checks the
complete population/report order, independent hashes, closed response and
evidence shapes, every raw body and every reference. It also checks each
report's retained raw-byte observations, aggregate byte count and unresolved
slot inventory against the original declarations. Missing, extra, malformed or
reordered inputs refuse the entire operation; no member is dropped from an
otherwise successful collection. All per-response limits remain. The aggregate
raw evidence across all supplied members is additionally limited to 8 MiB;
repeated supplied bytes still count in their supplied positions.

An exact raw evidence hash cannot equal any cohort report or input-response
hash, the shared preparation/correspondence hash, the population manifest hash,
or the offered collection hash when validating. This prevents direct cohort
bodies from masquerading as supporting artifacts. It does not authenticate
independence, detect every alternate encoding or decide substantive circularity,
truth or relevance. Artifact IDs are scoped to each original response; no
locator is fetched and no new evidence is manufactured.

For nonempty populations, each existing member validator runs once and performs
its own genuine opening/finally-closing original replay. The first actual
validated member's nested preparation supplies the independently checked shared
preparation. One additional genuine shared-preparation validator runs finally
after the collection is rendered, protecting the common original physical
source through the whole collection. An empty population still performs genuine
preparation opening and closing and retains every original pending obligation.
Closing begins before the first genuine member call, so an earlier failure
still attempts that final source replay and preserves secondary custody notes.

All caller/detached raw inputs, parsed inventories, trusted producer pins and
actual retained member/preparation returns are fenced. After the final encoder
callback, producer pins and callback-free input/returned-object fingerprints are
checked, then independent direct serialization checks the actual detached
output. These remain sequential bounded checks, not an atomic physical snapshot
or a guarantee about later source changes. Complete original inputs are required
again on each validation.

The result retains one full preparation and its exact source/context/typed
inventories, all original ordered obligations, declared dependency custody,
complete population manifest, every filled response and candidate proposal,
and per-member report/evidence commitments. Raw body maps and redundant full
member preparations are not embedded again.

`answer_variants` groups by the SHA256 of the whole exact answer, including its
finding, statement, rationale and evidence references. Order is original
obligation order, then first-seen exact answer in manifest order. Equal wording
with a different rationale or reference list remains a different variant.
Every respondent's source ordinal, declared reviewer/principal/role and full
report hash remains attached. This is exact JSON grouping, not semantic
normalization, disagreement adjudication or a vote.

`pending_questions` preserves every original slot with its full obligation
commitment, variant references, all declared respondents and explicit issues.
Repeated declared principal IDs are retained and flagged. Missing role strings,
a missing pair of distinct declared principal strings, unresolved answers and
distinct exact variants remain visible. A present `legal_review`/`formal_review`
string pair does not establish two independent humans or an authenticated
quorum. Neither agreement nor a majority selects an interpretation.

All six unavailable original parent-context requirements, every original source
issue and definition applicability remain open. Pending decisions and
adjudicator declarations are null. `supplied_population_fully_replayed` concerns
only the explicit bounded list, not a global review population or legal corpus
census. Subject, clock, registry, policy, signature, governing use and accepted
meaning remain null. All authority, authentication, evidence-verification,
readiness and quorum flags remain false; semantic/consumer/training/gold masks
and review/authentication/admission/model/native counts stay zero.

The existing 8 MiB output, 128 MiB aggregate snapshot, 512-obligation and inherited
node/depth limits still apply. Not every maximum-sized independent report
population fits those combined bounds; overflow refuses without truncating
answers, variants, respondents or source issues. Existing signed assessment,
declaration-binding and adjudication APIs retain their closed contracts. Real
governing source/context/edition, substantive independent reviews and every-use
definition applicability remain separate requirements before legal, graph,
training or Lean admission.

The [saved focused collection qualification](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-programme-review-20261022-05/parent-norm-response-collection-20261024-root-f2c91b64/qualification-summary-v02.json) passed **19 cases / 57 phases**: 17 new collection controls and two selected legacy cases on captured selected producers and freshly regenerated member reports. Original native, source READ and storage closed. This namespace-scoped qualification covers explicit population custody, genuine original replay, exact grouping and refusal behavior only. It supplies no authenticated cohort, human independence, quorum, accepted statutory meaning, whole-package startup, signing/adjudication, training/gold, graph or Lean admission. Historical response 23/69, review/worksheet 40/120, peer hardening 16/48, parent 185/555, wire corpus 90/270 and uninstalled references-only 42/126 remain separate generations.
