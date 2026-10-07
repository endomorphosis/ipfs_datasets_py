# Local US Code source-occurrence census

`scripts/ops/legal_ir/census_uscode_sources.py` inventories the original immutable
progress Parquet and source Parquet without downloading, running a model,
training, importing completion authority, or opening any existing live catalog.
It uses `legacy_span_intake.iter_joined_section_batches(include_candidates=True)`.
The iterator's default matched-only behavior is unchanged.

Every regenerated candidate is persisted, including unlisted sources, source
hash/citation mismatches and conflicting or invalid ledger identities. Canonical
occurrence keys include the source repository/revision/artifact, physical section
offset, CID, source hash and historical ordinal. Duplicate ledger records remain
separately counted; identical text or citations do not collapse source occurrences.
The historical groups of 64 valid documents remain independent of runtime batch
size. Original section bytes remain in the pinned source; the census hashes the
historical extractor's normalized sentence bytes and stores no duplicate text.

The controller is the sole DuckDB writer, protected by a local exclusive lock.
It commits occurrence rows, cumulative counts and the next-section cursor in
one transaction. Resume rehashes inputs, checks revisions, code and tokenizer
pins, then replays historical prefix ordinals. Changes to runtime section batch
size are allowed; changes to generation pins are refused. Original input ledger
indexes are TEMP and rebuilt, so the durable database avoids copying them.

Required dependencies are `duckdb` and `pyarrow`. `tokenizers` is optional only
when a local tokenizer JSON, exact hash, producer ID and immutable revision are
explicitly configured. No tokenizer is downloaded. Truncated tokenizer profiles
are refused; complete configured token counts include actual special tokens and
disable padding. Without that configuration, token counts and cohorts stay null.
UTF-8 bytes and Unicode character lengths are measured independently.

Run from the pinned source checkout, replacing the local paths and exact hashes:

```bash
python scripts/ops/legal_ir/census_uscode_sources.py \
  --progress-parquet /LOCAL/resume-checkpoint.parquet \
  --progress-sha256 7707c001d650876717651a38e442d1522c5bdab6c792539414973922af1c1d03 \
  --progress-revision 765176c6db79ba65c1697c21dead43666350b730 \
  --source-parquet /LOCAL/laws.parquet \
  --source-sha256 4d26df1e3814279e4b4df3af0e454b4f64fc89a81879db926989862b6ad7d8b8 \
  --output-directory /OWNED/source-census-generation \
  --section-batch-size 1 --max-batches 16 \
  --memory-mb 1024 --storage-max-bytes 134217728 \
  --max-row-group-bytes 2147483648
```

The first real run refused a later sixteen-section batch at its configured
span/byte limit. A one-section resume completed the bounded diagnostic window.
Larger batches need measured fit; a single oversized section needs an explicit
disposition or a separately reviewed streaming interface, never silent clipping.

Resume the same command/output directory after removing `--max-batches`; changing
`--section-batch-size` is safe. A complete run produces `census.duckdb`, pinned
`manifest.json`, `report.json`, and a small `census-disposition-counts.parquet`.
Reports distinguish partial pending source scans from complete unresolved joins;
they include exact occurrence/ledger counts, conflicts, length cohorts, counts
above 32,768 characters and 1,048,576 UTF-8 bytes, and ten largest identity-only
examples. No output grants admission, formalization, inference completion or
training qualification. Full Parquet inventories require `--export-full-parquet`
and additional admitted space.

The default budget is 128 MiB of output, one DuckDB thread, 1,024 MB DuckDB memory,
an 8 MB checkpoint threshold and up to one quarter of the output cap for temporary
spill (32 MB at the default). The controller checks its output footprint after
initialization, each committed batch and each export. An exceeded bound stops
continuation while preserving the durable cursor; an external resource guardian
must enforce the admitted process-group budget during individual operations.

The real source has one row group whose full uncompressed footer estimate is
1,170,039,502 bytes; the six selected intake columns account for 330,347,299 bytes.
The explicit 2 GiB row-group metadata bound admits that original file, while Arrow
reads projected batches. These footer sizes are not resident-memory measurements.
Start with a bounded smoke and measure actual peak memory, storage and committed
rows before proceeding; a complete 128 MiB fit is not established by unit tests.

Focused controls cover complete accounting, unlisted/mismatched/conflicting and
invalid identities, Unicode/overflow lengths, optional genuine tokenizer counts,
transaction interruption, pinned resume, multiple runtime batch sizes across a
64-document boundary, exclusive writing, foreign database refusal and preservation
of the original intake interface.
