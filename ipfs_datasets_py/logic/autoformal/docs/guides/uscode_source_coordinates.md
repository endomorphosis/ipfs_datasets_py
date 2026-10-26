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

## Retained 2024 official-source pilot cohort

The [retained-official pilot evidence](../../../../../docs/autoformalization/evidence/legal-ir-retained-official-pilot-20261024.json) records a separately identified local cohort for the complete retained 2024 Title 10 §§101, 7213 and 7214 source documents. DATA1 replayed the exact retained HTML and existing normalized views, then wrote three Parquet rows with eight UTF-8 fields and a report of **1,649 uncompiled source-coordinate spans**. The raw HTML stays separately pinned; the Parquet text field contains the normalized view. DATA1 used Arrow 25.0.1 and NumPy 2.1.3. Its four data checks passed under the existing native owner. The earlier failed DATA1 generation and its separate storage reconciliation retain their original failed status.

The local cohort is bound to actual Git commit `79f6f5538747095de6512dcc071e92b025570017`, rather than a claimed Hugging Face revision. DATA2 used the genuine `legal_parent_parquet_pages` reader and `legal_parent_text_views` owner to reread all three physical rows, verified all eight fields against the pre-Arrow rows, and replayed the complete source-coordinate report with the same hash. Its four data checks passed without Arrow/NumPy decoding, a Git subprocess, pytest or model execution. Both successful runs have original native/storage release and final controller source-READ closeout receipts; these are two distinct data observations, not a new test-phase total.

Existing `usc:us:10:101`, `usc:us:10:7213` and `usc:us:10:7214` legal IDs remain display/source identifiers. The query is `retained-official-pilot:2024:10:101,7213,7214:v1` and the release is `retained-official-pilot/2024-title10/v1`. Their new physical cohort, row/field witnesses and source-span identities must remain distinct from legacy cache records. Offsets refer to decoded normalized-text characters and UTF-8 bytes; they supply neither encoded-HTML offsets nor Parquet-file byte mappings. The descriptor includes the actual local repository path: moving the files requires a new descriptor and replay, while the original descriptor and evidence remain unchanged.

This cohort creates no entity annotations, semantic review or legacy cache repair. Legacy rows retain `producer_lineage_unavailable` and null Hugging Face physical joins. Source authenticity, governing edition, context, complete meaning, definition applicability and the existing interpretation alternatives remain pending; training/evaluation masks stay zero and graph/Lean authority stays false. No source sampler, reviewer template, encoder, training run or Lean build was regenerated. Reuse these physical witnesses for the next source-bound review instead of repeating the source capture.

### Retained source units and exact physical selectors

The [retained-unit crosswalk evidence](../../../../../docs/autoformalization/evidence/legal-ir-retained-pilot-source-crosswalk-20261024.json) reuses the existing three-row cohort and all 1,649 inventory spans. Existing public owners replayed three retained source versions and four original source-occurrence records, enumerated every literal candidate, and selected the sole exact match for each retained unit. Four bounded data checks passed with original native/storage release and final controller source-READ closeout; no source sampler, cohort capture or reviewer template was regenerated.

These half-open ranges address the decoded `text` field of the named physical row. Character positions count Unicode code points; byte positions count its UTF-8 encoding.

| Retained unit label | Section / physical row | Character range | UTF-8 byte range |
| --- | --- | --- | --- |
| Title-scope candidate | §101 / 0 | [6425, 6527) | [6447, 6551) |
| Officer-definition candidate | §101 / 0 | [6528, 6591) | [6552, 6615) |
| Officer-use candidate | §7213 / 1 | [431, 624) | [432, 625) |
| Officer-use candidate | §7214 / 2 | [407, 570) | [408, 571) |

Each selected unit lies inside one inventory span. The two §101 units share a containing span, so four unit selectors link to three spans; none is identical to its entire containing span. Preserve the full overlap population and each original USC ID, source-version/unit/occurrence CID, context reference, blank-guide reference and unanswered review question. The selected labels do not resolve their source roles, governing definition, meaning or applicability. Coordinates establish no encoded-HTML or Parquet-file byte mapping, registered occurrence alias, historical Hugging Face join, entity annotation, semantic graph edge or Lean admission; training/evaluation masks remain zero. This data worker observed ten ordinary project origins, twelve checked compile buffers and four initializer bypasses, with multiformats 0.3.1 from the trusted installed runtime; Arrow and NumPy remained absent. These runtime observations do not attest whole third-party binaries or qualify a model/profile.
