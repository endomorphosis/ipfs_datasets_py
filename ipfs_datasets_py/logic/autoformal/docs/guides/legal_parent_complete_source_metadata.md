# Complete historical-parent metadata scan

This additive API in `legal_parent_parquet_pages.py` scans every
physical row of one independently pinned historical parent artifact. The
existing preflight and selected-row APIs, supported format, `DEFAULT_LIMITS`
and selected 256 MiB decoded-page ceiling remain unchanged.

```python
scan_parent_source_metadata(
    descriptor,
    *,
    expected_descriptor_sha256,
    expected_preflight_sha256,
    preflight_report,
    output_directory,
    limits,  # Explicit ParentMetadataScanLimits required.
)
```

The function creates a fresh exclusive output directory and returns the complete
manifest only after scanning and final source-byte guards. It does not expose a
lazy iterator whose early abandonment could accidentally claim completeness.
It opens the source once, hashes the complete pinned artifact on entry and exit,
replays its complete preflight, and decodes every dictionary/data page once using
the existing Snappy, RLE, PLAIN, definition/repetition and UTF-8 routines.

The saved historical preflight declares one row group with 60,077 rows, 45 columns
and 423 pages. Their uncompressed bodies total **1,169,575,763 bytes**, exceeding
the selected 256 MiB aggregate budget by 901,140,307 bytes. The text column alone
declares 325,983,482 decoded bytes. These sums describe page work; dictionary
references can expand the logical canonical row input further. They do not
measure resident RAM, timing, legal accuracy or model performance.

`ParentMetadataScanLimits` supplies a separate, lower-only scan profile:

| Limit | Ceiling |
| --- | ---: |
| Physical rows | 65,536 |
| Aggregate decoded page bodies | 2 GiB |
| Aggregate canonical row bytes hashed | 4 GiB |
| Canonical observations retained across active rows | 256 MiB |
| Literal identity observation | 512 UTF-8 bytes |
| Metadata row, including newline | 4 KiB |
| Metadata shard | 4 MiB / 4,096 rows |
| Metadata shards | 128 |
| Supplied preflight JSON | 8 MiB |
| Complete manifest JSON | 2 MiB |
| Metadata package | 384 MiB |

Every limit requires a positive plain integer. Raising a ceiling or using bools
refuses. The original per-file/page/value/dictionary/list and 8 MiB canonical
row bounds still apply. The scan-specific page allowance is passed only inside
the new API; no default or selected API limit is modified. An owned execution
profile and normal resource admission remain prerequisites for an actual whole
scan. The separate profile uses one CPU, 2,048 MiB memory, two child
slots, 1,200 seconds and 512 MiB of durable output. Each run requires its own
admission and qualification record; this guide grants no execution credit.
Canonical retained-byte counters do not bound Python object/allocator overhead
or prove RSS compliance.

Columnar input prevents simply yielding complete rows while retaining one page.
The scanner instead holds one SHA256 context and small bounded source observations
per row in the current row group. Columns are processed in canonical JSON key
order. Opening/closing braces, keys, separators and every scalar/list fragment
are charged before allocation and streamed into the corresponding row hash.
The implementation reuses the existing exact JSON byte-count, scalar decoder
and canonical JSON encoder; it does not invent another escaping convention.

Dictionary-expanded values are charged for every row occurrence, even though
their page is decoded once. Lists retain only continuation counters and hash
fragments, including lists crossing page boundaries; they are never collected
as full-row arrays. Complete source text is decoded only for the active scalar
to compute its exact hash, lengths and normalized key, then discarded. No
collection of full rows or all source texts is retained.

Rows are emitted in contiguous physical order into `metadata/part-000000.jsonl`
and subsequent bounded shards. Each row retains the current selected-source
labels: full `physical_key` and compatible `physical_section_id`,
`full_raw_row_sha256`, exact text hash/UTF-8 bytes/Unicode-codepoint count,
`normalized_content_sha256`, literal CID/title/section observations and statuses,
text disposition, null group/split/inference fields, false authority and integer
zero train/evaluation-gold masks. `raw_row_canonical_bytes` accounts for all
hashed original fields. Uninterpreted raw extras contribute to the full row hash
and are not stored as source metadata.

Missing/null, empty-string and supported nonstring text values remain physical
rows with `missing_text`, `empty_text` or `unsupported_text_type` dispositions.
Nonempty strings, including whitespace, retain `stored_text_available`.
Identity strings longer than the literal limit retain a null literal,
`unsupported_size`, and exact SHA256/UTF-8 length under
`observed_identity_evidence`; they are never truncated. Unsupported identity
types retain a null literal and `unsupported_type`. These are source observations,
not canonical legal identities or eligible training inputs.

Normalized text uses the existing `unicode-whitespace-casefold-v1` recipe:
`sha256(" ".join(text.split()).casefold().encode("utf-8"))`.
Exact original text hashes remain separate. Shared normalized keys do not merge
physical occurrences, authenticate meaning or establish group/split membership.
Malformed UTF-8, unsupported parent profiles, source drift and hard parser,
canonical hashing, resident observation or output-budget failures refuse the
whole scan; partial files remain diagnostics and no successful manifest is
returned.

The final `parent-source-metadata.json` uses schema
`legal-parent-complete-source-metadata/v1`, profile
`historical-parent-complete-source-metadata/v1`, and scope
`declared_parent_artifact_only`. It records the complete parent/preflight/schema
commitments, explicit limits, complete physical coverage, all shard hashes and
half-open ordinal ranges, decoded page witnesses/totals, canonical row-byte
total, metadata byte total and disposition counts. Its `manifest_sha256` seals
canonical bytes excluding that field. `parent_source_metadata_manifest_sha256`
hashes the entire bounded canonical manifest including the seal; hashing alone
does not validate original source bytes or grant admission.

Manifest publication happens after the source context has completed its final
same-FD hash and path guard. Caller descriptor, preflight and limit snapshots
are checked again before publication. The writer fsyncs a private pending
manifest, creates the final name atomically with an exclusive hard link, removes
the pending name and fsyncs the directory. Before-commit failures leave no final
manifest. After a publication error it attempts to remove only its own matching
inode names, preserving foreign replacements. Arbitrary filesystem failures or
uncatchable process termination can prevent cleanup; a final name or seal alone
does not establish successful completion or durable ownership. The actual
returned result and owned validation/durability receipt are required.

`whole_parent_inventoried=true` describes complete physical metadata coverage of
this one parent. `grouping_metadata_complete` remains false: literal historical
identities and normalized text keys require a separate genuine grouping profile.
Excluded, unsupported and alias rows must remain connectors where their keys
are available; missing keys cannot be dropped to force successful partitions.
The different 62,931-row release inventory cannot donate its assignments merely
because it shares a repository commit or legal identifiers. Governing definitions,
entities, exceptions, temporal scope and permitted-context dependencies need
their own closure before scientific holdout or training eligibility. No cache
targets, vectors, model, database, prover, Lean or convergence work runs here.
