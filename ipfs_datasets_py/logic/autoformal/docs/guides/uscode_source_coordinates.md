# Exact supplied-text coordinates for U.S. Code spans

`logic.autoformal.uscode_ingest` owns the new, explicitly selected coordinate inventory and its replay validator. Historical `inventory_uscode_documents` output and span identity recipes stay unchanged. This is a source mapping contract; it does not change sentence boundaries or qualify an interpretation.

```python
from ipfs_datasets_py.logic.autoformal.uscode_ingest import (
    inventory_uscode_source_coordinates,
    uscode_source_coordinates_sha256,
    validate_uscode_source_coordinates,
)

original_documents = [{"legal_id": "fixture:1", "text": "  Café shall\tretain records.\r\nCafé may inspect.  "}]
report = inventory_uscode_source_coordinates(
    original_documents, query="review", release_id="fixture-release")
# Retain this full-report commitment independently of the transported report.
expected_pin = uscode_source_coordinates_sha256(report)
validate_uscode_source_coordinates(
    report, original_documents, expected_report_sha256=expected_pin,
    query="review", release_id="fixture-release")
```

The input is a finite list/tuple of mappings with an exact string `text` field. Each retained document has its input ordinal, exact source text/hash, Unicode count, UTF-8 byte count and normalized text/hash. Whitespace-only documents remain visible even though the historical inventory emits no spans for them. The filtered legacy document ordinal and original input ordinal are separate identities.

Each span retains its legacy ID and normalized text, its normalized character interval, and the corresponding half-open character and UTF-8 intervals in the supplied source text. Its selected original substring and digest preserve internal tabs/newlines/Unicode whitespace. Repeated sentences and repeated document IDs remain distinct occurrences. The versioned normalization collapses Python whitespace; it does not strip HTML or classify operative legal text. Replay reconstructs the entire report from independently supplied documents and query/release/limit arguments, and checks a separately retained full-report pin. Rehashing a changed selector does not make it consistent with the original inputs.

Default limits are 128 documents, 1 MiB per source text, 8 MiB total source text, 8,192 spans, 64 KiB metadata per document and 32 MiB report bytes. Overrides may only lower the declared limits. No truncation, partial report or auto-increased bound is permitted. The original span inventory is called only after source and span-population preflight. Byte-boundary calculation reuses `legal_parent_text_views._byte_positions`.

The coordinate origin is the exact supplied decoded `text` field. It is **not** a Parquet-file offset, raw HTML byte map, official-edition authentication or historical producer-occurrence decision. Source authenticity, meaning, review, model inference, training eligibility and Lean admission remain separate.

## Explicit cache transport profile

The explicit cache transport profile is installed with the same source bytes tested in immutable private candidate copies. The [candidate qualification](../../../../../workspace/test-logs/federal-corpus-audits/coordinate-cache-20261020-01/candidate-validation-retry/qualification.json) records **36 passed cases / 108 passed phases** and 75 hash-checked sealed files, with original source/native/storage release. Its receipt remains explicitly candidate-only: installation binds those tested byte identities, without claiming a separate runtime test of the installed checkout. The earlier 31-case qualification below covers the supplied-text inventory and replay API.

The profile adds `SpanCache.enqueue_source_coordinates(...)` and `read_source_coordinate_report(...)` on the existing native owner. Enqueue independently checks the full-report pin and replays the supplied documents before atomically storing fresh normalized spans, one complete report in existing `cache_meta`, and per-span references. Exact retries are idempotent. Existing rows without the same binding and conflicting occurrences are refused; historical coordinates are not backfilled.

An existing native cache owner selects the profile explicitly:

```python
inserted = cache.enqueue_source_coordinates(
    report, original_documents, expected_report_sha256=expected_pin,
    query="review", release_id="fixture-release")
assert cache.read_source_coordinate_report(expected_pin) == report
```

Pending rows, legacy claims and live fenced source reads carry an optional `source_provenance_json` reference. The closed fenced claim schema stays unchanged. The fenced worker path retains this reference in the complete observation and existing exchange `input_json`, rejects worker-supplied conflicts, and charges it to the source-batch byte limit. Hashes establish identity and replay consistency; every semantic, training and admission flag remains false.

The 36-case cohort comprises 24 cache controls, eight new fenced-transport controls and four existing fenced regressions. It covers exact Unicode slices, reopen/retry behavior, no-backfill and occurrence conflicts, corrupted evidence, atomic rollback, source replacement, owner/lease boundaries and immutable exchange transport. These are authored fixture contracts, without a model, training, solver, native Lean, network or remote publication run.

The [first attempt](../../../../../workspace/test-logs/federal-corpus-audits/coordinate-cache-20261020-01/candidate-validation/failure-reconciliation.json) was stopped by the 64 MiB storage watchdog. Its completed-case count is unknown; progress dots are not counted as passes. Compute and source READ closed with no live processes, while its storage remains retained. The successful retry used the same 36 cases and source bytes with a 128 MiB storage allowance; CPU, memory, process, time, policy and acceptance rules stayed fixed.

## Portable complete-report bytes

The existing `SpanCache` owner now exports a complete report and can atomically import it into a fresh cache. The stateless loader validates the same bytes without opening another database:

```python
from ipfs_datasets_py.logic.autoformal.span_cache import load_source_coordinate_report

payload = cache.export_source_coordinate_report(expected_pin)
loaded = load_source_coordinate_report(payload, expected_report_sha256=expected_pin)
inserted = receiving_cache.enqueue_exported_source_coordinate_report(
    payload, expected_report_sha256=expected_pin)
assert receiving_cache.export_source_coordinate_report(expected_pin) == payload
```

All three APIs accept `max_bytes`, an exact positive integer no greater than 32 MiB. Intake checks that limit before UTF-8 decoding, rejects duplicate keys, nonfinite JSON and excessive nesting, then replays every retained document and span against the separately supplied report commitment. The report commitment is distinct from `sha256(payload)`; a file transport should retain its own byte digest. JSON metadata insertion order is preserved because historical IDs can depend on `str(mapping)`. No coercion from strings or mutable buffers is accepted.

Export requires the original live cache/thread owner and replays the persisted report before returning ordered bytes. Intake uses the existing transaction: fresh spans, one report and bindings commit together; exact retries insert zero; mixed legacy/fresh conflicts and interrupted writes roll back. It does not backfill old rows or change semantic, training or admission flags. Bounds cover transport size, not total replay memory: export first reads the stored report under the existing 32 MiB ceiling. Filesystem publication, path isolation, remote transfer and manifests remain caller responsibilities.

The [portable-report qualification](../../../../../workspace/test-logs/federal-corpus-audits/coordinate-cache-20261020-01/portable-report-01/qualification.json) records **24 cases / 72 phases**: 20 new portable controls plus four existing regressions. The exact candidate bytes were installed separately under source WRITE/CAS. Original native, storage and source READ released; 52 sealed files were rehashed. These fixture results cover Unicode/CRLF slices, fresh-cache reference identity, nested metadata order, retry/no-backfill, malformed inputs, stale pins, resealed bad coordinates/authority, owner guards and transaction rollback. They establish no official source authentication, statutory meaning, training result, native Lean result or publication.

## Remaining production transport

`USCodeParquetRecord.from_row` still strips text before the corpus ingest caller receives it, and default `SpanCache.enqueue` still ignores extra provenance. This profile does not connect raw Parquet ingestion or change the default corpus path. Capture the exact field and physical row identity before cleaning, using the existing parent-field custody owners; decoded-field offsets are not Parquet-file byte offsets or original HTML offsets.

Complete reports can now leave the originating cache through the bounded bytes API below. Exchange still carries only a small reference: callers must transfer the report separately and retain its independent report pin. Automatic file/Hub publication and manifest attachment remain unimplemented. Existing paired Arrow profiles and the closed fenced source manifest are unchanged. Historical normalized-only spans remain unresolved.

The raw-producer audit identifies the next compatibility boundary. `USCodeParquetRecord.text` is stripped and may fall back to a law name or citation; retain the original field and a missing/null/nonstring disposition separately. `_documents` counts eligible documents for resume, while `_parse_document` inventories each document separately. Neither count is a physical Parquet ordinal. Replacing that recipe with a 64-document report changes IDs. Preserve the existing projected-column set, distinguish the separate historical 64-document recipe, bind a selected profile's checkpoint to actual file identity and define duplicate-occurrence refusal explicitly. Reuse `legal_parent_parquet_pages.read_selected_parent_rows` and `legal_parent_text_views.prepare_parent_text_views` for independently pinned physical custody. The current corpus caller polls a remote checkpoint even in enqueue-only/no-upload modes, so a future offline test must avoid that entrypoint or supply an explicit offline boundary.

See the [current handoff](../HANDOFF.md#cache-producer-and-offsets), [owner map](../ARCHITECTURE.md) and original [24-task backlog](../BACKLOG.json), especially LIR-02. The 8D/384D/768D/4096D numerical owners and their qualification gates are unchanged.

## Original coordinate qualification

The [original qualification](../../../../../workspace/test-logs/federal-corpus-audits/source-coordinates-20261020-01/qualification.json) records **31 passed controls / 93 passed phases**, exact private source copies, matched collection/JUnit records and verified original source/native/storage release. The selected cases cover Unicode and UTF-8 coordinates, CRLF and Unicode whitespace, repeated occurrences, filtered empty documents, frozen legacy identities, changed source/metadata/query/release bindings, independently pinned report replay, rehashed selector tampering and finite population limits.

These are fixture contract tests. They do not qualify original Parquet/HTML provenance transport, historical cache repair, learned reconstruction, statutory meaning, or Lean admission. No model, training or native Lean run was performed.
