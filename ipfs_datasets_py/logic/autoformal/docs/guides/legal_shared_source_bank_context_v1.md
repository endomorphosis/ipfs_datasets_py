# Immutable validated bank contexts for planned projections

`legal_shared_source_bank_context_v1` reuses validated source-bank request and
geometry outputs within one public operation. It calls the genuine public
shared-source report validator once, mints a private immutable context for each
validated bank, then projects every planned logical request without replaying
that bank's legacy join/review parser again for each epoch.

This is reuse of already validated pure request outputs. It does not share the
internal receipt JSON parser across unrelated owners, execute authenticated
history, cache review authority or apply a governing source. Original contexts,
flags, alternatives, complete source text and physical fanout remain unchanged.

## Public API

```python
prepare_shared_source_bank_context_v1(
    shared_report, packet, source_request_raw, replay_request_raw, *,
    expected_shared_report_sha256, expected_packet_sha256,
    expected_source_request_sha256, expected_replay_request_sha256,
    original_banks, limits=None,
)

shared_source_bank_context_sha256(report, *, limits=None)

validate_shared_source_bank_context_v1(
    report, shared_report, packet, source_request_raw, replay_request_raw, *,
    expected_report_sha256, expected_shared_report_sha256,
    expected_packet_sha256, expected_source_request_sha256,
    expected_replay_request_sha256, original_banks, limits=None,
)
```

The original bank, source packet/request and shared catalog/schedule contracts
remain unchanged. Expected hashes bind full canonical compact sorted Unicode
UTF8 JSON without LF, or exact immutable request bytes as specified by the
original owners. Physical transport files may have separate final-LF hashes.
Pins must be independently supplied; a newly computed hash alone authenticates
neither provenance nor an omitted population.

Only plain JSON reports are public inputs and outputs. No public constructor,
context loader, saved-context input or parsed-bank bypass is offered. The hash
helper bounds content identity only; it neither mints contexts nor validates
originals. The public validator independently remints from exact originals and
compares the complete canonical report, including all projections and counters.
Wrapper failures raise `SharedSourceBankContextError`, a `ValueError` subclass;
existing delegated source-contract errors may retain their original subclasses.

## Genuine mint boundary

The public shared-source validator first regenerates the complete independently
pinned source packet and planned schedule from the original immutable join,
paired-row and receipt bodies and complete source sections. There is no caller
flag saying a bank was previously validated, and no positive path from a saved
report alone. Every successful preparation crosses that public boundary.

Contexts are private exact `_BankContext` objects created only inside that
operation's validated composition. Their plain JSON payloads are converted into
tagged immutable tuples. A bank's source-section tree is shared immutably among
its logical request payloads. Complete canonical bank bytes are retained for
identity; they are not decoded on every projection.

Normal attribute assignment/deletion and construction are refused. Contexts are
nonserializable and never returned. An operation-local registry strongly owns
each minted object and records its exact identity, bank ID, generation, immutable
payload/byte objects and a fresh local mint token. Projection requires the exact
private type plus matching registry witness and generation/token. A dictionary,
serialized descriptor or context from another operation cannot enter the public
projection path. The private implementation is not a public service accepting
caller-minted contexts.

These are cooperative Python custody checks. They do not attest against arbitrary
reflection, monkeypatching, native code or replacement of all independent inputs.
The private object is not a portable proof or authorization token. Implementation
byte custody belongs to the separately frozen source/execution environment.

## Context generation and identity

`context_generation` binds:

- The versioned generation schema, owner profile and fixed `OWNER_RECIPE` hash.
- The complete shared report, source packet, source request and replay request
  hashes, plus catalog, schedule and original-bank commitments.
- Fixed parser profiles and explicit declared owner profiles for this module,
  the shared catalog, correspondence, legacy source review and legacy join.
- Every ordered bank's source-version CID/schema, media type, extraction profile
  and normalization profile.
- Every effective limit, including lowered context and projection bounds.

These owner/profile/version values are explicit declared recipe identities, not
runtime code hashes. This pure in-memory API performs no filesystem source
verification. Full original-bank commitments bind receipt bytes and source
metadata even when those bodies are absent from returned projections.

The generation SHA is the full canonical JSON hash. Each context ID is
`sha256:` plus the hash of canonical JSON of exactly:

```text
generation_sha256
bank_id
bank_ordinal
bank_bundle_sha256
```

The bank bundle is the complete exact entry from the validated source packet's
ordered `banks` list, not a hand-selected request subset. Descriptors record its
hash/byte length and counts of logical requests, physical references, sections
and candidate references. No mutable or executable context is serialized.

## Complete detached projections

The report contains the unchanged `shared_report`, generation, ordered context
descriptors and one projection for each unchanged schedule request. Each
projection retains:

```text
epoch_id, parent_epoch_id
bank_id, request_ordinal
context_id, context_generation_sha256
request
subject
dependency_manifest
source_sections
physical_references
```

The four original request/subject/dependency/section payloads remain exact. All
bank source sections are retained, including those not referenced by one
candidate. Physical references include every original record for that bank and
logical request, retaining fanout, dispositions, candidate IDs, null selections,
integer-zero masks and original authority flags. Bundle-local section indices
are not interpreted as global indices.

Each projection thaws the immutable payload into fresh plain JSON containers.
Mutating one returned request, section or physical reference cannot change a
different projection, the caller's originals, the immutable bank or a validator
result. Thawing is output materialization; it does not decode original receipt,
paired-row or join JSON and performs no legacy bank parser call.

Every declared planned epoch and fork remains. The complete schedule's physical
ordinals must match the minted request's physical roster before projection.
There is no first-match, unique-candidate selection, inferred role or source-use
decision. Missing source evidence stays missing in every projection.

## Work scopes

One successful preparation validates the shared report once. Its underlying
genuine composition replays each original bank once before minting. The actual
two-bank cohort therefore has two original bank preparations and two context
mints followed by 32 planned logical context accesses for a two-epoch schedule.
It preserves 32 physical references and 300 candidate references across those
projections. It does not execute 32 review/history epochs or parse two large
receipts 32 additional times.

The small fictional differential compares each full projected payload with a
fresh genuine unchanged legacy bank preparation for that planned request. Two
banks, two logical rows per bank and two planned epochs yield two mint-boundary
bank preparations versus eight deliberately naive comparison preparations. The
actual retained-data qualification need not repeat the large receipts 32 times
to establish that small engineering differential. Its original replay and
validation counters stay separate from the fictional reference workload.

Public report validation independently remints from original bodies and thus
performs another two genuine bank preparations for the actual cohort. It does
not reuse the first preparation's opaque contexts. Preparation and validation
are distinct operations; observer counts may overlap their underlying owner
calls and must not be added as independent examples.

`work.shared_bank_projection_reuse_implemented=true` is narrow operational
metadata. All authority flags stay false, including the unchanged shared
report's historical broad `shared_parsed_validation_implemented=false` flag.
This increment qualifies reuse of validated request/geometry outputs, not a
new shared internal receipt parser or authenticated history engine.

Original hashing, parsing at the mint boundary, tuple freezing, output thawing,
serialization and closing comparisons remain work. No measured speedup, peak
memory bound, token saving, statutory accuracy, source equivalence or convergence
follows from operation counts.

## Bounds and closing checks

All shared-source lower-only limits remain: 16 banks, 256 physical references,
64 MiB aggregate original graph, 32 MiB complete output, 256 KiB request bytes,
1,000,000 visited nodes, depth 48, 512 KiB UTF8 strings, eight planned epochs,
128 scheduled logical requests and the 1 GiB forecast-reference accounting cap.
The original per-receipt 32 MiB, per-bank review preparation 8 MiB and legacy
history 512 MiB caps are unchanged. Context-only keys are stripped before
forwarding effective limits to the existing public shared validator.

Two additional lower-only limits are `max_context_bytes=16,777,216` and
`max_projection_count=128`. Context bytes bound the aggregate canonical validated
bank payload, not the Python tuple heap or RSS. Projection count bounds the
complete output population. The complete original/shared/offered-output graph
is bounded before hashing; offered payload/count checks can refuse before the
genuine validator, and verified payloads are checked again after it.

Output byte/node bounds are checked after each complete projection and on the
final report. Nothing is truncated to make a successful result fit. Expanding
all source sections into many projections can legitimately refuse a plan even
when its catalog-only report fits.

Caller originals, shared/offered reports, detached snapshots and limits are
compared at closing boundaries. The first operational error remains primary if
a closing comparison also fails. No file path, original parent Parquet,
metadata shard, cache table, network, clock, trust policy or model is accessed
by this owner. Current source adoption, context closure, accepted meanings,
training/gold eligibility, global splits, Lean and convergence remain open.
