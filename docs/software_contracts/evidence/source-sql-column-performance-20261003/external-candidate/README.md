# External column-list insert experiment

This directory contains an experimental replacement for `DuckDBASTStore._insert_rows`; no production file is modified. The candidate transposes each existing chunk into column lists and uses a fixed-width `INSERT ... SELECT unnest(?), ...` statement. It keeps the native 128-row and 256 KiB parameter-byte target, including the existing oversized-singleton behavior. Source-derived values remain parameters. The owning transaction, validation, schema, indexes, deadlines and row order are unchanged.

Replay integration is temporary and must restore the original method:

```python
from vector_candidate import insert_rows_unnest

original = DuckDBASTStore._insert_rows
try:
    DuckDBASTStore._insert_rows = insert_rows_unnest
    # Run the separately authorized replay against a fresh native database.
finally:
    DuckDBASTStore._insert_rows = original
```

The hook accepts only the native placeholder-only `VALUES` layout. Its list parameters have equal lengths by construction; DuckDB's unequal-list NULL padding is not used. It preserves native streaming behavior, including consuming the next row before flushing a full previous chunk. The existing owner still validates complete projections before publication.

`check_and_measure.py` runs synthetic 18-column row parity and boundary/rollback controls with DuckDB 1.5.5, one thread and a 512 MB memory setting. The paired timings use fresh in-memory databases, 128 and 1024 rows, three alternating-order pairs, and exclude setup, commit and parity-query time. Both methods receive identical rows. Raw wall/CPU timings, native execute timings, parameter counts, source hashes and control logs are retained per run. These tiny measurements do not establish durable corpus or container performance.

The first run is retained under `tiny-01` with nine controls. `tiny-02` adds a tenth control for all-NULL columns and DOUBLE values; its receipt pins the final test script. No 31-projection replay, Docker comparison, production optimization, training, or model inference is authorized by these results alone.
