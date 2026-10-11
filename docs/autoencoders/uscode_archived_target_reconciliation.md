# Archived US Code target reconciliation

`scripts/ops/legal_ir/reconcile_uscode_archive.py` provides an additive local
`uscode-archived-target-reconciliation/v1` generation. It reconciles every archived
span ID against the pinned original source, including conflicting, invalid and
source/hash/citation-mismatched identities. It uses the separately bounded
section/span pager and leaves the earlier all-occurrence census unchanged.

The persisted `target_occurrences` table retains every physical source occurrence
whose ID appears in an archived span row. Duplicate source text, citations or
archive rows do not collapse physical occurrences. Counts of ledger physical
rows, distinct archived IDs, matched occurrences and outside-target observations
remain separate.

Outside-target candidates have durable counts, UTF-8/Unicode length totals and
cohorts, ordered rolling SHA-256 digests and at most the configured identity-only
examples. Their complete identities are not stored. A completed source scan is
therefore **not a complete all-source occurrence inventory**. Outside-target
observations are not classified as missing work, new text or duplicate records.
Original bytes remain in the pinned source artifact; hashes cover the historical
whitespace-normalized extraction. No source text, embedding or model is replaced.

The ordered digests hash each complete canonical occurrence descriptor, including
its archive join disposition and provenance. They are stable across page sizes
and stop/resume within the pinned source-plus-archive generation; they are not
archive-independent raw-source digests. No page size, timestamp or batch counter
enters the descriptor.

Source rows with real CIDs and blank raw text retain the historical citation
fallback and its ordinal consumption. These candidates explicitly carry
`source_text_origin=legacy_citation_fallback` and `raw_source_text_present=False`.
Their counts are separate; their identity match grants no statutory-text,
training, semantic or proof authority. Null-CID metadata consumes no historical
document ordinal.

One exclusive controller commits target rows, aggregate accounting, digests and
the first uncommitted `(next_section,next_span)` cursor in one transaction. Resume
replays prefix sentence counts, preserving the original groups of 64 valid source
documents independently of page sizes. Source/input/code/paging/profile and seed
pins are immutable; changing page bounds creates a new generation. Runtime page
count, memory and output-storage limits can change after separate admission.

An optional old `--seed-census-directory` must contain a stopped, WAL-free census,
its manifest and matching report. The controller holds a shared old writer lock,
authenticates all old files, verifies original input/code/tokenizer bindings,
reconstructs every old physical occurrence in source order and compares exact
stored bindings. Only then does one transaction import archived targets, account
for all old outside-target candidates with new counts/digests, and advance the seed cursor. Interrupted
or refused imports retain a zero cursor and cannot double-count the prefix.
Old files remain read-only. Seed reuse is verified work reuse; complete source
replay without a seed remains available as a separately attributable generation.

Dependencies are `duckdb` and `pyarrow`; this command performs no download,
tokenization, model inference, training, admission, publication or formal proof.
Example using the existing authenticated inputs and old generation:

```bash
python scripts/ops/legal_ir/reconcile_uscode_archive.py \
  --progress-parquet /LOCAL/resume-checkpoint.parquet \
  --progress-sha256 7707c001d650876717651a38e442d1522c5bdab6c792539414973922af1c1d03 \
  --progress-revision 765176c6db79ba65c1697c21dead43666350b730 \
  --source-parquet /LOCAL/laws.parquet \
  --source-sha256 4d26df1e3814279e4b4df3af0e454b4f64fc89a81879db926989862b6ad7d8b8 \
  --output-directory /OWNED/archive-reconciliation-generation \
  --seed-census-directory /LOCAL/old-source-census/results \
  --max-page-spans 1024 --max-page-bytes 4194304 --max-pages 64 \
  --memory-mb 768 --storage-max-bytes 134217728
```

Seed input paths must equal the old manifest's authenticated paths; relocating
inputs is a new lineage rather than silently rewriting an old manifest. A single
candidate exceeding the page limit or a source section exceeding its complete
byte bound is refused without advancing that cursor. Such a source remains
pending and needs a reviewed larger profile or section streaming interface.

Default output consists of `reconciliation.duckdb`, pinned `manifest.json`,
`report.json` and a writer lock. No all-occurrence export is produced. One DuckDB
thread, bounded spill, explicit memory/storage settings and an external owned
resource guardian control each real run. Output size is checked after commits;
these are cooperative bounds rather than a kernel quota. The report includes
the kernel `getrusage(RUSAGE_SELF).ru_maxrss` with platform units and converted
bytes, explicitly a process-lifetime high-water mark rather than an isolated
phase or process-group peak. Full corpus fit is not established by unit controls.
