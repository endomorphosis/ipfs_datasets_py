# Fresh source review over shared validated banks

`legal_shared_bank_source_reviews_v1` reuses complete original-validated bank
preparations while evaluating each explicitly supplied source-review call
freshly. The unchanged public bank-context preparation regenerates originals
once; the new batch mints private complete-preparation capabilities and invokes
the same fixed-domain source assessment kernel for every positive call.

Only immutable source request/geometry data is reused. Selected trust, registry
and policy validity, review signatures, revocations, time/age, roles/scope,
dependency observations, evidence and conflicts are checked on every call.
No review eligibility, authority or history result is cached.

## APIs

```python
assess_shared_bank_source_reviews_v1(
    shared_report, packet, source_request_raw, replay_request_raw, review_calls, *,
    expected_shared_report_sha256, expected_packet_sha256,
    expected_source_request_sha256, expected_replay_request_sha256,
    expected_review_calls_sha256, original_banks, limits=None,
)

shared_bank_source_review_calls_sha256(review_calls, *, limits=None)
shared_bank_source_reviews_sha256(report, *, limits=None)

validate_shared_bank_source_reviews_v1(
    report, shared_report, packet, source_request_raw, replay_request_raw,
    review_calls, *, expected_report_sha256, expected_shared_report_sha256,
    expected_packet_sha256, expected_source_request_sha256,
    expected_replay_request_sha256, expected_review_calls_sha256,
    original_banks, limits=None,
)
```

Existing shared/source requests, original banks and expected pins retain their
original contracts. JSON identities are full canonical compact sorted Unicode
UTF8 without LF; request pins bind exact immutable request bytes. Transport
files may have distinct final-LF hashes. A newly calculated pin authenticates
neither an input's provenance nor missing members outside the declared scope.

`SharedBankSourceReviewsError` is a `ValueError` subclass for batch failures.
Positive assessment contract failures retain existing source/authentication
errors. A malformed positive input refuses the operation; no blanket exception
turns it into an unassessed or successful row.

## Complete ordered calls

`review_calls` contains exactly one ordered item per complete planned schedule
request, including every epoch, bank and logical request:

```text
epoch_id
bank_id
request_ordinal
assessment_inputs
```

Coordinates and count are checked against the bounded offered schedule before
expensive original replay, then checked again against genuine validated
projections. The first check grants no trust. Reordered, duplicated, dropped or
misbound calls cannot silently redefine the scheduled population. Logical
fanout retains all original physical references and candidate IDs.

`assessment_inputs=None` explicitly means no source assessment was performed
because the caller supplied no inputs. It creates neither an empty registry nor
a synthetic source assessment. In particular, actual retained-data calls may
all remain unassessed when no actual trust/review evidence exists.

A positive `assessment_inputs` has exactly:

```text
registry, policy, reviews
expected_preparation_manifest_sha256
expected_registry_sha256, expected_policy_sha256, expected_reviews_sha256
at_time_utc
observed_artifact_sha256s, observed_pins
evidence_artifacts
```

These are the existing dynamic source-review inputs. Static join/paired/receipt
arguments are supplied only through the genuine mint boundary. Evidence bodies
must be exact immutable bytes, not paths or claims that data was previously
checked. The source owner retains its independent pin, explicit UTC time,
registry/policy mode, distinct legal/formal role, complete review population,
subject/dependency and evidence contracts. Signature authentication establishes
declared byte custody under selected trust, not human competence or law.

The review-call commitment keeps the complete ordered call list unchanged,
except that each positive `evidence_artifacts` body is replaced by exactly
`{"bytes": len(raw), "sha256": SHA256(raw)}`. Hash its canonical compact Unicode
JSON without LF. Explicit null inputs remain null; there is no wrapper record.
The helper bounds the whole review graph before hashing evidence. It validates
no source, key, signature or review truth.

## Exact legacy assessment kernel

`corpus_legacy_source_review.assess_legacy_source_review` keeps its exact public
signature, initial preflight ordering, complete original regeneration, source
signing domain, caps and returned assessment structure. Its original request
builder and validators remain unchanged. After regeneration, both public paths
use the same fixed private authentication/report kernel.

The kernel accepts a private `_SourceReviewPreparation` capability, not a parsed
dictionary or caller `verified` flag. It is minted only by fixed internal
callers after genuine original regeneration: the original public source owner,
or the new owner after public bank-context preparation. It holds the complete
preparation manifest, request/subject/dependency rosters and all source sections
under the unchanged 8 MiB preparation cap. Canonical identity bytes and an
immutable tagged tuple payload are bound to a local strong registry,
generation and fresh operation token. Construction/mutation/serialization are
refused; no capability is public output or a portable cache input.

The new batch checks fresh dynamic input preconditions for each call and then
invokes the genuine fixed `_assess_reviews` verifier. Its nested `assessment`
is the exact legacy JSON result for the same original bank and dynamic inputs.
Registry, policy, roles, expiry/age, key/principal revocation, observed dependency
changes, closure evidence and reviewer conflicts are not inherited from an
earlier call. Mutating a subsequent call's evaluation time or trust observations
can change its result even when the immutable source context is identical.

The capability payload is thawed to detached plain structures. Existing
preflight copies, JSON encoding/decoding, evidence hashing, signature checks and
closing comparisons remain work. `source_bank_reparses_during_assessment=0`
means no additional **original join/paired/receipt regeneration** during the
fresh assessment loop; it is not a claim that no preparation JSON is copied or
decoded by existing preflight helpers.

The type/registry boundary is cooperative Python custody. Private functions are
not a security boundary against arbitrary reflection, monkeypatching or native
code. No mutable cached authority or caller-supplied parsed positive is accepted
by either public path.

## Results and work

The report retains the complete genuine `bank_context_report`, its canonical
hash, review-call hash and ordered `rows`. Each row binds epoch/bank/request,
context ID and all physical references, with:

- `assessment_status="not_assessed_missing_inputs"`, `assessment=None` and a
  null assessment hash for an explicit null input.
- `assessment_status="assessed_fresh_under_supplied_inputs"` and the complete
  unchanged legacy assessment/hash for a positive input.

Every `decision_applied` remains false. Positive source prerequisites may be
satisfied under selected trust, as in the old owner; that authenticates
declarations and never applies a source or meaning choice. Top-level authority
flags remain false, masks integer zero and inference view null.

Coverage separates planned, freshly assessed and missing-input calls, complete
physical/candidate references and the full declared population. Work records
one bank-context preparation, genuine source-bank preparations, complete
capability mints, fresh assessments and fixed verifier calls. It records zero
history epoch replays and authority-cache hits.

The small authored differential must compare complete assessments and refusals
with a separately pinned original source owner. Signature fixtures are
fictional engineering controls. Actual retained-data input does not acquire
reviews merely because those controls pass. Original, reference, preparation
and validation calls have separate counts; the public report validator remints
and freshly reassesses all supplied positive calls from originals.

No measured runtime, memory, token saving, statutory accuracy, task completion
or convergence follows from reduced original-parser call counts.

## Bounds and closing checks

All bank-context/shared-source limits remain lower-only and unchanged, including
64 MiB complete original graph, 32 MiB complete report, 16 MiB canonical bank
context payload, 128 projections, 32 MiB per receipt, 8 MiB per source-review
preparation, and the legacy 512 MiB history limit. Context-only keys remain
separate from old owner contracts. New lower-only batch bounds are:

| Key | Maximum |
| --- | ---: |
| `max_review_calls` | 128 |
| `max_review_input_bytes` | 8 MiB, all supplied review metadata/evidence |
| `max_review_evidence_bytes` | 8 MiB, repeated supplied evidence references charged |

Each individual positive call also keeps the old aggregate 8 MiB authentication
input cap. New review keys are removed before invoking the existing bank-context
owner. No old cap is raised and no oversized successful output is truncated.

One mixed prehash graph counts original raw bodies, shared/source reports,
request bytes, all review evidence bytes and offered validator output. Review
subgraph budgets and cheap immutable request/type/count guards precede original
body hashing. Plain node/depth/string/cycle limits are reused. Raw bytes are
allowed only in designated original/evidence positions; ordinary metadata is
separately checked as plain JSON.

Caller and detached original/review inputs, offered reports and limits are
compared at closing boundaries. Fresh verifier input copies are checked across
the actual verifier call, including dependency-observation maps. The first
operational failure remains primary if a closing comparison also fails. These
checks do not establish an OS sandbox, atomic snapshot or RSS bound.

## Remaining history and source gates

Typed response validation, adjudication, cohort exclusions, application/revision
authorization and authenticated history still need a versioned shared-original
composition. Current history unions track **source-reviewer** identities over
all supplied branches, including rejected, mismatched and unknown-key reviews;
they do not inventory every role or prove general human independence. Broader
actor exclusions require a separately explicit policy and role inventory.

The actual two-bank receipts account for 358,335,096 expanded receipt bytes per
epoch and 716,670,192 for two epochs, already above the old 536,870,912-byte
history cap. Avoiding repeated bank parsing does not change that old input
accounting or make a planned history executable. Preserve legacy refusals and
signed bodies; a new storage/replay profile needs its own exact budget and
original-bound differential qualification.

Actual nine-question typed reviews, exact-text context resolution, new applied
source-effect authorization, accepted definition/norm/genuine second-use meaning,
global dependency/split eligibility, training, full Lean admission and convergence
remain separate gates. Original `required_unavailable` contexts stay unchanged.
