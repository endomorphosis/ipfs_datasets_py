# Shared-bank typed source responses, version 1

This owner reuses complete original-validated source preparation while freshly
authenticating and checking every supplied typed-response call. It preserves
the exact legacy response assessment, including rejected content, answer
variants, respondents, pending questions and occurrence proposals. It does not
apply a source decision or establish legal meaning.

The public batch accepts full source/shared reports, exact request bytes,
independent pins and all original banks. It accepts no portable context, caller
preverified assessment, callback, signer factory or default trust. Internally it
calls the genuine public bank-context preparation once. Each bank is replayed
from its original join, paired rows, producer receipt and source sections before
the source owner mints an operation-local immutable preparation capability.
Only that private capability can enter the fixed response kernel. Every
positive call performs fresh source-domain authentication inside the kernel,
followed by the existing typed-content and variant logic.

The separately retained shared-bank review leaf remains unchanged. This response
batch is a sibling over the same genuine bank-context boundary; a saved review
report is not a positive input to this owner.

## Public API

```python
assess_shared_bank_source_responses_v1(
    shared_report, packet, source_request_raw, replay_request_raw, response_calls,
    *, expected_shared_report_sha256, expected_packet_sha256,
    expected_source_request_sha256, expected_replay_request_sha256,
    expected_response_calls_sha256, original_banks, limits=None)

shared_bank_source_response_calls_sha256(response_calls, *, limits=None)
shared_bank_source_responses_sha256(report, *, limits=None)

validate_shared_bank_source_responses_v1(
    report, shared_report, packet, source_request_raw, replay_request_raw,
    response_calls, *, expected_report_sha256, expected_shared_report_sha256,
    expected_packet_sha256, expected_source_request_sha256,
    expected_replay_request_sha256, expected_response_calls_sha256,
    original_banks, limits=None)
```

The module is `ipfs_datasets_py.logic.autoformal.legal_shared_bank_source_responses_v1`.
Structural, budget, commitment, roster and custody refusals use
`SharedBankSourceResponsesError`, a `ValueError` subclass. Existing original and
response/authentication refusals retain their legacy exception behavior. The
validator bounds the offered report together with all originals before hashing,
independently remints through the genuine original replay, freshly reassesses
all positive calls, and compares the full canonical JSON. It does not validate
only counts, hashes stored inside the report or caller-supplied eligibility.

The report digest helper checks bounded ordinary JSON identity only. The call
digest helper checks bounded call shape and exact evidence commitments only.
Neither helper authenticates a source, review, response, principal or policy.

## Complete ordered response calls

`response_calls` is a nonempty plain list containing exactly one entry for every
ordered logical request in the supplied shared schedule, including every planned
epoch and bank. An entry has exactly these fields:

```python
{
    "epoch_id": "explicit planned epoch ID",
    "bank_id": "explicit bank ID",
    "request_ordinal": 0,
    "response_inputs": None,
}
```

The ordinal must be a plain integer; booleans are refused. Dropped, extra,
duplicate, reordered or mismatched coordinates refuse the entire batch. A
bounded cheap comparison against the offered schedule precedes original bank
replay; the same correspondence is checked against the genuinely validated
context projections afterward. The cheap check grants no trust to that offered
schedule. Physical fanout remains in each projection and row even when two
physical records point at the same logical request.

A literal `None` records missing response-assessment inputs. The resulting row
has `assessment_status="not_assessed_missing_inputs"`, `assessment=None`,
`assessment_sha256=None`, and `decision_applied=False`. It does not call source
authentication, construct an empty trust registry, turn blank templates into
answers or create a typed assessment with zero responses. Missing inputs are
different from explicit positive inputs that contain a valid empty review list.

A positive `response_inputs` has exactly these fields:

```python
{
    "registry": registry,
    "policy": policy,
    "reviews": complete_ordered_signed_reviews,
    "expected_preparation_manifest_sha256": preparation_manifest_sha256,
    "expected_registry_sha256": registry_sha256,
    "expected_policy_sha256": policy_sha256,
    "expected_reviews_sha256": reviews_sha256,
    "at_time_utc": explicit_assessment_time,
    "observed_artifact_sha256s": dependency_observations,
    "observed_pins": dependency_pin_observations,
    "evidence_artifacts": {"artifact ID": immutable_bytes},
    "response_bindings": complete_ordered_body_bindings,
    "expected_response_bindings_sha256": bindings_sha256,
}
```

The current planned request supplies `request_ordinal`; the selected capability
supplies the exact full preparation. Callers cannot supply either inside the
positive object. All other source/join/receipt inputs come from the independently
replayed original bank. Extra fields, including raw assessments, preverified
flags, selected candidates, old source join arguments, callbacks or contexts,
are refused by the closed shape.

The response bindings use the existing exact ordered shape:
`{"review_id": ..., "artifact_id": ..., "raw_sha256": ...}`. There is one
binding for every supplied signed review, including rejected content or invalid
authentication. Review order and body identities must agree with the old owner.

To compute `expected_response_calls_sha256`, retain the complete ordered call
list and every supplied field, replacing only each positive
`response_inputs.evidence_artifacts` byte body with
`{"bytes": len(raw), "sha256": SHA256(raw)}`. Hash compact, sorted-key,
Unicode-preserving JSON with no LF. The new bounded metadata domain is plain
`None`/boolean/signed-64-bit-integer/string/list/dict, as in the installed bank
foundation; booleans remain distinct from integers and floats are not admitted.
This does not narrow the old public response owner's JSON domain. A missing body is not
invented; a changed body changes the commitment. JSON bytes outside that
designated mapping, custom objects, aliases that exceed the expanded node bound
and cycles are refused. Byte bodies remain immutable and are never serialized
into the report.

## Existing response behavior is retained

The staged `corpus_legacy_source_responses.py` retains every old public signature:
record/validate a response, prepare a blank template, assess responses, and
validate the assessment by full regeneration. The record/template functions and
all typed-answer, evidence, content, variant and pending logic are unchanged.
The assessment wrapper keeps the old guard order: exact source-input fields,
complete preparation detach, signed-review detach and list bound, independently
pinned ordered response bindings, immutable bounded evidence, source preflight,
then complete original source regeneration and source-owner capability mint.

The source owner is not edited. The wrapper composes its existing fixed private
preflight, full public original regeneration, mint and fresh-auth kernel. The
private response kernel `_assess_source_responses_prepared` accepts the exact
owner-minted capability and fresh authentication inputs, performs fresh source
authentication itself, and then executes the original typed-response report
logic. It accepts no caller assessment argument and never bypasses source
authentication based on a previously reported prerequisite or authenticated
review count.

Every positive batch call executes the source signing domain's trust checks:
independent registry/policy/review pins, Ed25519 verification, role and scope,
key/principal binding, assessment time, expiry and age, revocation, complete
dependency observations and supplied closure evidence. Registry, policy, time,
reviews and evidence may differ between planned calls. Reuse covers immutable
source preparation only; these mutable checks are fresh each time.

Then the unchanged content owner loads each exact response body, checks its
sealed record and request/subject/preparation binding, binds review/principal/
role/time to the signed claim, checks all nine ordered answers and signed closure
dispositions, and verifies supporting evidence without self-reference. Typed
body content is not inferred from the source signature alone.

Malformed binding-list structure or an independent pin mismatch refuses the
call. A missing, malformed, changed or otherwise invalid individual response
body remains a rejected `response_results` row with its blockers, while the raw
authentication result survives. Valid declared content with rejected source
authentication also survives as declared content and does not become an
authenticated answer variant.

The exact legacy condition for `authenticated_typed_content` is an authenticated
raw review row and no content blockers. It does not additionally require the
whole raw source prerequisite to be true. A correctly authenticated unresolved
answer therefore remains an authenticated typed declaration, creates its exact
unresolved answer variant and retains the relevant pending issue. Unknown
exposure declarations and differing occurrence proposals remain explicit.

Answer equality is exact canonical answer equality, including rationale and
evidence references. The owner does not merge semantically similar answers.
All variant respondents, principals and roles remain. Nine active pending
question records and all seven deferred slot IDs survive. No variant,
respondent count or legal/formal role pair selects a source or substitutes for
separate adjudication authority.

## Report and work scope

The report schema is `legal-shared-bank-source-responses/v1`, profile
`fresh-typed-source-responses-from-minted-banks/v1`, status
`complete_declared_source_response_call_population`. It includes the full
unchanged `bank_context_report`, its digest, the source shared-report pin,
`response_calls_sha256`, complete ordered `rows`, coverage, work and limitations.

Each row carries epoch/bank/request coordinates, context ID, all physical
references, assessment status, the complete exact legacy typed assessment or
`None`, the assessment's full canonical JSON digest or `None`, and
`decision_applied=False`. A positive row has status
`assessed_fresh_under_supplied_inputs`; that label records evaluation under the
explicit supplied inputs, not legal acceptance or a completed source decision.
The nested assessment retains its own legacy `assessment_sha256` recipe; the
row digest hashes the full nested object including that field.

Coverage counts planned calls, assessed calls, missing-input calls, scheduled
physical references and candidate-occurrence references, with
`full_declared_population_retained=True`. Complete population means the declared
supplied schedule, not the entire federal corpus or every statutory edition.

Work fields describe successful composition within one batch operation:

| Field | Scope |
| --- | --- |
| `bank_context_prepare_calls` | One genuine public original-bound bank-context preparation |
| `source_bank_preparations` | One original replay for every source bank in that preparation |
| `private_preparation_capability_mints` | One complete immutable capability for every bank |
| `fresh_typed_response_assessments` | Positive response calls evaluated |
| `fresh_source_assessments` | Fresh source kernel calls, one per positive response call |
| `fresh_fixed_domain_verifier_calls` | Fresh fixed-domain verifier calls, one per positive call |
| `typed_response_content_checks` | All individual body checks attempted, including rejected content |
| `source_bank_reparses_during_assessment` | Zero original join/paired/receipt regenerations during response-call processing |
| `history_epoch_replays` / `authority_cache_hits` | Zero |

These are scoped composition counts, not profiler measurements or a claim that
the whole API hashes/parses each byte once. Complete preparation thaws, bounded
JSON detachments, canonical commitments, typed body decoding and closing
comparisons still do work. A full report validation is a new operation and
repeats genuine original bank replay and every positive source/content check.
The source, bank-context and shared-replay nested reports retain all their old
flags and limitations unchanged.

## Bounds and custody

All limits are plain positive integers and lower-only. Unknown limits, booleans,
zero, negatives and raised values refuse. The batch inherits the bank-context
limits, including the 64 MiB complete original-input graph, 32 MiB full output,
16 MiB aggregate immutable context payload, 128 projections and existing
depth/node/string/request/epoch/physical-row bounds. It adds:

| Limit | Hard maximum |
| --- | --- |
| `max_response_calls` | 128 |
| `max_response_input_bytes` | 8 MiB for the complete expanded response-call graph |
| `max_response_evidence_bytes` | 8 MiB aggregate designated evidence across calls |

The response-call budget counts raw evidence before descriptor replacement;
repeated references are charged for each logical occurrence. Evidence is also
part of the single 64 MiB root alongside both reports, both request byte bodies,
all original banks and any offered validation report. Shape/count and raw-request
guards, then finite expanded depth/node/string/aggregate bounds, precede any
SHA operation or complete serialization. The bounded response subgraph is
checked before original-bank commitments. Complete closed field maps are length
and plain-string checked before key-set allocation.

Existing per-bank preparation remains 8 MiB, original receipts remain subject
to the old per-receipt 32 MiB limit, and existing source-review evidence checks
and complete-source limits are unchanged. The shared schedule's 1 GiB expanded
reference accounting limit remains a forecast bound. It does not admit that
amount of input to an old source or history API.

The operation records detached bounded snapshots of caller inputs and effective
limits, then checks caller and detached copies on both success and failure.
Positive-call source preflight also detaches its trust/dependency/evidence maps;
the batch fingerprints those exact inputs and response bindings around the
genuine source/content kernel. The validator additionally includes the offered
report in its root and closing comparison. An existing operation error is
preserved if a closing comparison also fails, with a closing-failure note.

Immutable bytes and tagged immutable complete preparations stay private to the
operation. Returned JSON is detached. Capabilities require the exact private
type, live owner-minted registry witness, payload, generation and mint token;
they are not serializable or publicly accepted. These are cooperative Python
custody checks. They do not establish runtime code identity against arbitrary
reflection, malicious monkeypatches, a compromised interpreter or host. Declared
owner/parser/normalization recipes remain generation identities rather than
runtime source attestation. There is no file, network, clock, model or database
access in either product owner and no automatic trust or as-of time.

## Qualification and remaining gates

The staged implementation and tests must be independently reviewed and admitted
before native qualification; this guide reports no new runtime results. Useful
controls compare the entire new legacy response output with the exact retained
old response/source preimages, and compare each positive batch assessment with
that old oracle. Refusal parity should cover malformed binding order/pins,
preparation/original substitution and signature, role, time, revocation,
dependency and evidence changes. Content controls must distinguish call refusal
from retained rejected bodies; exact variant disagreements and unresolved
authenticated answers must survive. Instrument genuine source preparation and
authentication in tiny cases to establish bank replay reuse without an
authentication cache. Test whole-root prehash refusal and caller, detached
evidence, offered-report and limit mutation at genuine work boundaries.

For the retained two-bank case, the declared schedule contains two planned
epochs, 32 logical call slots, 32 scheduled physical references and 300 candidate
references over 13 source sections, 16 original physical records and 150 original
candidate occurrences. If actual response inputs are absent, preserve all 32
literal missing calls and assess none. Do not fabricate real reviews from signed
test fixtures. Source decisions, training/evaluation masks and authority remain
false/zero; the inference view remains `None`.

The original receipt-reference forecast is 358,335,096 bytes for one complete
epoch and 716,670,192 bytes for two, exceeding the unchanged old history input
cap of 536,870,912 bytes. This owner does not execute that history or raise its
cap. Next work must adapt fresh adjudication/cohort/history checks with a
separately versioned shared-input budget and preserve chronology, forks,
revocation, conflict and exclusion semantics. Existing history unions cover
source-review actors across branches, including rejected/mismatched/unknown-key
claims; a broader all-role inventory needs explicit policy and inputs.

Actual exact-text source-context evidence, reviewed typed responses, authorized
adjudication and source adoption remain required before accepted meaning can
enter the terms/entities/definitions graph. Lean compilation, premise auditing,
whole-task satisfaction, empirical optimization convergence and analytic
convergence are separate gates. None follows from parsed-output reuse, content
authentication, a planned epoch, an answer-equality bucket or a hash cache.
