# SQL persistence and optional dependency diagnosis

The paired Docker replay preserved the complete AST catalog but **did not reproduce
the large host timing improvement** from column-list insertion. The SQL candidate
and its production patch remain unapplied. This evidence supports a deployment
dependency investigation, not a completed Source384 qualification or benchmark score.

## Exact retained catalog replay

The read-only exporter binds the successful `full-context-04` native receipt to
the actual `codebase_control.heads` row and unchanged database bytes. It retains
31 canonical AST projections from 220 permitted files, with exact row counts and
digests for all 13 catalog tables. Both insertion methods rebuild through the native
owner, use a fresh database, verify every table, close the database, and verify a
cold native canonical reopen. The source/database/model owners are not modified.

The proposed insertion hook keeps the existing 128-row and 256-KiB parameter-byte
target, lazy row consumption, oversized singleton behavior, nine fact families,
validation, transaction boundaries and rollback. It changes only the SQL parameter
layout from repeated VALUES tuples to one list per column with UNNEST. Its method
and connection wrappers are restored even on failure.

| Single ordered pair | Host VALUES | Host UNNEST | Docker VALUES | Docker UNNEST |
| --- | ---: | ---: | ---: | ---: |
| apply_batch seconds | 4.664 | 2.135 | 41.391 | 39.863 |
| summed execute seconds | 3.399 | 0.946 | 40.269 | 38.692 |
| complete diagnostic seconds | 8.828 | 6.133 | 45.106 | 43.646 |

The two layouts make the same 1,132 calls and bind the same 870,877 scalar values;
the candidate reduces parameter objects from 870,877 to 10,816. Execute timing
includes Python parameter binding and native execution, excluding fetching and
telemetry preparation. Inclusive insertion-family timings include the telemetry
overhead. These are single ordered component comparisons, not general speed claims.

Both environments used the exact same DuckDB 1.5.5 extension (SHA-256 beginning
`60ba1803`), one database thread and a 512-MB connection limit. The Docker resource
profile was five CPUs and 12 GiB. Its receipts record zero cgroup CPU throttling,
roughly equal execute CPU/wall time, and substantially greater system CPU time.
The Docker SQL pair completed and its container was removed. The pair did not run
Source384 context preparation, model inference, task code, a provider, training or
the official verifier. Full preparation's 90-second deadline was never increased.

## Runtime and dependency isolation

An isolated standalone Python 3.12.12 installation, using existing host dependency
paths and the same DuckDB binary, retained fast host behavior: VALUES/UNNEST
apply_batch took 4.278/2.122 seconds. The standalone build selected by host uv is
dated February 12, 2026; Docker's pinned uv selected a December 17, 2025 build.
This is not a byte-identical interpreter comparison and does not independently
exclude libc, namespace or other dependency differences. Binary hashes, paths,
settings and resource counters are retained. The installation used `--no-bin`;
an initial download was interrupted before linking a versioned executable. The
first import preflight lacked the host system dateutil path and failed; adding
the existing host dist-packages paths resolved it without installing dependencies.

DuckDB's exact v1.5.5 scalar conversion checks pandas NaT and NA before built-in
scalar types. Its optional import cache retries unsuccessful loads. Primary source
URLs and source hashes are retained in `runtime-diagnosis/diagnosis.json`; upstream
source files are not redistributed here. A controlled finder probe counted 130
pandas import attempts for 64 integers or strings, versus two for 64 nulls. That
probe demonstrates the retry mechanism and does not measure genuine missing-module
filesystem cost.

The subsequent dependency experiment uses four fresh isolated `-I -S` processes
with genuine private filesystem dependency roots and untouched standard import
finders. Both roots expose the same DuckDB, NumPy, dateutil and six dependencies;
only the available arm also exposes real pandas and its metadata. Each process
checks all 2,048 rows / 36,864 mixed scalar values, using sixteen 128-row queries.
Two available runs took 0.021514 and 0.021684 seconds in execute; two absent runs
took 0.999193 and 0.995784 seconds. Row parity passed in all four. This establishes
a large causal effect for missing pandas in the bounded host fixture. It does not
yet measure a corrected Docker deployment or prove that this accounts for every
second of the full pipeline. No allocator causality is claimed.

## Controls and retained attempts

The final replay harness passed 12 controls, the Docker wrapper passed eight
mocked boundary controls, and the external candidate passed ten small SQL controls.
These cover digest and producer refusal, exact table/cold parity, original cursor
and exception identity, cleanup restoration, stale/foreign native head refusal,
Unicode/NULL/DOUBLE values, source values remaining SQL parameters, chunk limits,
lazy consumption and rollback. These are separate suites; repeated historical
attempts are not added to their distinct control counts.

Earlier successful control generations and both diagnostic setup failures remain
visible. The initial exporter omitted the native head envelope's schema field;
the real export refused it, and final tiny-05 sources corrected the exact schema
before either pair. `replay/control-generations.json` maps retained sources to XML.
The earliest tiny-01 replay source was not separately recovered and is historical
only. The first isolated dependency attempt omitted package metadata; its actual
refusal is retained separately from the successful metadata-complete runs.

## Reproduction and package limits

`corpus-reproduction.json` binds the 9,412,206-byte retained corpus and its source
receipt/database, exact producer hashes, row digests and export/replay limits. The
task AST corpus, databases, model weights, interpreter binaries and dependency
symlink roots are excluded. Reproduction requires the retained public-source
database and native receipt; hashes cannot recreate unavailable artifacts. The
small generated dependency fixture is included with its hash.

`manifest.json` closes the scripts, source generations, raw logs/XML, receipts,
reviews, comparison data and reproduction metadata. No production SQL code is
changed by this package. The next deployment dependency fix and fresh full Docker
qualification require their own evidence.
