# Shared original catalog and planned replay schedule

`legal_shared_source_replay_v1` provides a bounded foundation for sharing
immutable source bodies. It catalogs exact designated originals, retains every
origin and physical reference, and constructs a complete independently pinned
planned epoch schedule. It regenerates the original source packet through the
existing public correspondence validator.

It does not implement shared parsed validation, authenticated history replay,
signature verification, authority memoization or source adoption. Planned
epochs are not executed review/history epochs. Content reuse cannot establish
legal meaning, permission, training eligibility, Lean admission or convergence.

## Public API

```python
prepare_shared_source_replay_commitments_v1(
    original_banks, epochs, *, limits=None,
)

prepare_shared_source_replay_v1(
    packet, source_request_raw, replay_request_raw, *,
    expected_packet_sha256, expected_source_request_sha256,
    expected_replay_request_sha256, original_banks, limits=None,
)

shared_source_replay_sha256(report, *, limits=None)

validate_shared_source_replay_v1(
    report, packet, source_request_raw, replay_request_raw, *,
    expected_report_sha256, expected_packet_sha256,
    expected_source_request_sha256, expected_replay_request_sha256,
    original_banks, limits=None,
)
```

The commitments helper returns `catalog`, `catalog_sha256`, `schedule`,
`schedule_sha256`, ordered `bank_commitments` and `catalog_work`. It bounds and
hashes supplied content and planned coordinates only. It calls no source
validator, parses no original body, and authenticates neither the origin nor
the completeness of a caller's independently selected population.

`source_request_raw`, `packet` and `original_banks` retain the installed
correspondence contract. Original bank commitments bind full stored source text,
metadata and every designated byte body. Expected pins must originate outside
offered changed records. Computing a new pin does not recover an omitted source
or authenticate a claimed table coordinate.

The report hash helper bounds content only. The public validator regenerates
the entire report from originals and checks exact canonical equality. Wrapper
contract failures raise `SharedSourceReplayError`, a `ValueError` subclass;
delegated original-source contract failures may retain their existing types.

## Original body catalog

The catalog includes exactly each bank's immutable `join_bytes`, every ordered
`paired_row_bytes` body and its `producer_receipt_bytes` when present. No second
raw-catalog argument is accepted, so unused supplied raw records cannot be
silently retained. Missing receipts remain an explicit null bank binding.
Complete source texts are retained through bank commitments and the unchanged
source packet; they are not relabeled as independently cataloged raw artifacts.

Each catalog record contains:

```text
content_id
sha256             SHA256 of exact raw body bytes
bytes              exact raw byte length
media_type         application/json
parser_profile     fixed by designated origin kind
```

Profiles are `legacy-source-join-canonical-record/v1`,
`paired-span-census-record/v1` and `legacy-producer-receipt-json/v1` for joins,
paired rows and receipts respectively. A parser profile describes a designated
body role; this catalog does not execute that parser or validate original JSON.

The content ID is `sha256:` plus SHA256 of compact sorted Unicode UTF8 JSON of
`{sha256, bytes, media_type, parser_profile}`, without LF. Equal raw bytes under
different parser profiles retain distinct content identities. Within one
catalog construction pass, the bounded existing-record list is searched by
fixed profile and length, then full exact byte equality. Only that equality
allows reuse before another raw-body SHA256 call. Conflicting bytes under the
same complete descriptor are refused. No hash-only equality or lossy text
normalization is used.

Catalog `records` are sorted by `content_id`. `origins` retain original bank
order, then join, logical paired-row order and optional receipt. Each origin
contains `origin_id`, `bank_id`, `kind`, `logical_row_ordinal`, `content_id`,
`raw_sha256` and `raw_bytes`. `kind` is `join`, `paired` or `receipt`;
`logical_row_ordinal` is an integer only for paired rows and is null otherwise.
Its ID is `sha256:` plus SHA256 of compact sorted Unicode JSON of
`{bank_id, kind, logical_row_ordinal}`, without LF. An origin is distinct even
when its content is reused elsewhere.

Catalog bank bindings retain each join-origin ID, all paired-origin IDs and the
receipt-origin ID or null. Coverage reports unique content records and bytes
separately from all origin references and their expanded bytes. Equal content
never collapses physical occurrences, logical requests, banks or evidence roles.
No raw original body is emitted in the catalog or output report.

## Independently pinned plan

The new `replay_request_raw` is canonical compact sorted-key Unicode UTF8 JSON
without final LF. It has exactly:

```json
{
  "schema": "legal-shared-source-replay-request/v1",
  "profile": "shared-original-catalog-planned-replay/v1",
  "bank_commitments": [
    {"bank_id": "paired-v1", "original_bank_sha256": "<independent hash>"}
  ],
  "catalog_sha256": "<independently expected complete catalog hash>",
  "schedule_sha256": "<independently expected complete schedule hash>",
  "epochs": [
    {"epoch_id": "plan:root", "parent_epoch_id": null},
    {"epoch_id": "plan:successor", "parent_epoch_id": "plan:root"}
  ]
}
```

The first epoch is the sole root. Every later epoch must name an earlier
declared parent. IDs are canonical distinct lowercase review-style IDs. This
rules out cycles, later/unknown parents, repeated IDs and second roots. Visible
forks are permitted, retained in input order and explicitly enumerated; no
branch is silently selected, merged or discarded. This is planning custody,
not an assertion that a forked authenticated history is eligible for use.

The schedule contains the entire ordered epoch list, expanded `requests`,
explicit `forks` and coverage. Every epoch expands every original bank and
every logical paired row in unchanged order. A request retains its epoch/bank,
logical ordinal, join/paired/receipt origin references, and all matching
bank-local `physical_row_ordinals`. Thus logical fanout preserves every physical
reference rather than charging another invented logical row or dropping an
occurrence.

The full report retains unchanged source-packet `physical_references`, including
their identities, logical mapping and every candidate occurrence ID. Joining
these to each schedule request's bank and physical ordinals recovers the full
planned physical/candidate population for every branch. No catalog parser is
needed to infer those candidates.

## Planned accounting and actual composition

`expanded_reference_bytes` sums join bytes plus the selected paired-row bytes
plus receipt bytes for every scheduled logical request. The separate
`expanded_receipt_reference_bytes` charges just its receipt body, repeated per
logical request and epoch. These are forecast references, not newly allocated
copies, parsed bodies, actual history work, process RSS or elapsed time.

The legacy history limit remains 536,870,912 bytes (512 MiB). The field
`receipt_reference_lower_bound_exceeds_legacy_cap` compares only the receipt
forecast to that limit. A false value establishes no history eligibility:
other metadata, bodies, repeated validation and current history policies still
apply. The new accounting allowance never changes the old history owner.

For the retained two-bank/16-request cohort, receipt bodies of 24,509,016 and
20,282,871 bytes produce 358,335,096 receipt-reference bytes per epoch. A
two-epoch plan retains 32 scheduled logical requests, 32 physical references and
300 candidate references, forecasting **716,670,192 receipt-reference bytes**.
That exceeds the old cap before additional metadata. This foundation does not
make that historical replay executable or qualified.

One successful public preparation calls the existing correspondence validator
once. Its genuine composition regenerates each supplied bank once, independently
of how many epochs are planned: the actual two-bank case has two source-bank
preparations, not 32 scheduled source-bank replays. Public validation performs
another full regeneration. Separate helper, preparation and validation calls
are separate operations; do not pool their counts or call one operation a
memoized authority result.

`work` reports zero catalog body parses, history epoch replays and authority
memoizations. It records source-validator/bank composition counts and planned
candidate references. Catalog raw-body SHA counters are scoped to **one catalog
construction pass**: one call per unique exact body/profile and the bytes
actually supplied to those calls. Descriptor and origin-ID hashes are excluded.
The equality-comparison count charges each profile/length-eligible comparison;
the candidate-byte count is an upper bound on comparison input length, not
measured CPU bytes visited by Python equality.

Lookup has a finite quadratic worst case, distinct from the custody-byte cap.
Every logical row needs a physical reference, so 256 physical references and 16
banks allow at most 288 designated origins (256 paired rows plus 32 join/receipt
slots). One pass therefore makes at most 41,328 candidate equality comparisons.
A conservative compared-candidate byte upper bound is 287 times the 64 MiB
aggregate input cap, or 19,260,243,968 bytes; fixed profile/length restrictions
can reduce it. The actual per-pass counters remain available. This derived
ceiling does not qualify worst-case runtime or claim that input bytes alone
bound all computational work to one linear pass.

Outer input commitments and closing guards perform additional original hashing
passes through existing helpers. Those are outside the per-catalog-pass counters
and are not instrumented as total runtime hashing. No parse-once, whole-API
hash-once, performance, memory, token-saving or source-authentication claim is
made. Future shared parsed validation and history execution require their own
versioned contract and qualification.

## Finite bounds and cooperative custody

All earlier lower-only bounds remain: 16 banks, 256 physical references, 64 MiB
aggregate original inputs, 32 MiB complete output, 256 KiB request bytes,
1,000,000 visited nodes, depth 48 and 512 KiB per UTF8 string. New lower-only
keys add `max_epochs=8`, `max_scheduled_requests=128` and
`max_expanded_reference_bytes=1,073,741,824` (1 GiB). The last applies only to
forecast accounting, not actual legacy work admission. New keys are removed
before forwarding limits to the unchanged correspondence owner. Per-bank
32 MiB receipt and 8 MiB complete preparation caps stay unchanged.

A shared mixed input graph includes original banks, source packet, both request
byte values, complete planned epochs and offered validator report before any
original body hashing or full serialization. A bounded request parse discovers
the epoch graph first; duplicate keys, invalid types or nonfinite values fail.
Canonical wire equality and independent hashes are checked after the complete
original root is bounded. Repeated aliases are charged; cycles and malformed
objects are refused without successful truncation.

Caller inputs, detached snapshots, offered report and limits are compared at
closing cooperative boundaries. The first operational failure remains primary
when a closing check also fails. Source output is detached; no original file
path, receipt path, parent Parquet or shard is followed by this owner. These
checks do not prove an OS sandbox, an atomic external snapshot or bounded RSS.
