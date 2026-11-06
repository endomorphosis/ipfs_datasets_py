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

## Public source integration (2026-10-24)

The existing owner and owning test are published unchanged from the original source-pinned generation. The [fresh 11-case / 33-phase integration](../../../../../docs/autoformalization/evidence/legal-ir-norm-content-responses-public-integration-20261024.json) covers nine response cases and two original norm-review controls. The historical 121 cases remain separate: 67 response cases plus 54 norm-review regressions, with their original legacy resource lease. The fresh cases reuse existing tests; the full 121-case population and original statutory template preparations were not rerun.

The public 25,432-byte norm-review owner and its fixture match that original generation; the later counted successor is not substituted. The paired-manifest reader preserves the exact `_wire` and `_read_json` helper bodies consumed here. Fresh checks required 19 source execution paths and four genuine pytest modules, within 171 source files / 4,342,668 bytes and 197 request pins. They retained 115 actual source compile/exec-filename observations, 112 module entries and 110 physical origins.

The signature fixtures used genuine Profile G Ed25519 API bindings from cryptography 49.0.0. The worker performed no extra signature operations and does not attest independent crypto operation counts or third-party binary equivalence. Six pinned initializer bypasses were declared; only `logic/__init__.py` was observed bypassed and five were unused. Checked source buffers do not establish code-object identity, the initial worker loader, cached third-party bytecode or full public-package/environment equivalence. Original compute/storage and source READs closed, retaining ten files / 2,803,822 bytes. The 24.405-second worker and 74.701-second owned interval are nested, not additive.

Keep the older blank A/B templates bound to their original subjects. This source publication supplies no substantive response, signature authority, civil legal-as-of date, selected meaning, governing definition, second statutory norm, training target or graph/Lean admission. Obtain the missing independently supplied review/context/applicability inputs through the existing owners; declaration-binding, adjudication and applicability source migrations remain separate.
