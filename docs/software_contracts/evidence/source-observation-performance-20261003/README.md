# Source observation performance evidence (2026-10-03)

A retained Bottle canary timed out in repeated native source observation. The
read-only cProfile diagnostic found 4,652 dependency edges and repeated complete
graph identity traversals. The old 4,096-entry pure CID caches repeatedly evicted
the working set: manifest loading accounted for 24.75 of the 27.85 profiled
seconds, with approximately 29,000 encoding misses.

The sole production optimization raises each fixed pure encoding/validation
cache capacity to **8,192 entries**. Neither source bodies nor graph values are
cached. Fresh body hashing, live codec/encoder registration guards, native CAS,
active AST lookup, source capture and published-head checks remain intact. The
same source/head observation with the production change passed in **13.62
seconds** under the unchanged 90-second deadline and native admission. The
13.77-second diagnostic override run is separately labeled and is not used as
production qualification. These are instrumented component measurements; no
full benchmark or general scaling claim follows, and larger working sets still
evict at the fixed bound.

The original source database was opened read-only. The native store constructor
unconditionally attempts CREATE DDL, so the diagnostic initializes the exact
store without a connection and attaches the existing read-only connection before
constructing the native catalog. The observation and all lookup implementations
are unchanged. The initial constructor refusal is retained.

The first final-production attempt was refused before observation because its
native host defaults differed from concurrently active shared scheduler capacity.
The retained read-only follow-up audit found no remaining leases or waiters and
recorded stored 4 CPU / 9,830MiB versus requested 16 CPU / 99,688MiB. The other actor was
not identified. No shared state file or policy was edited; a separate normal
admission retry passed. That refusal is not a performance sample.

**64 tests passed in 5.94 seconds**: exact identity vectors, CAS corruption and
body mutation controls, registry replacement and miss/hit races, thread parity,
real bounded eviction, and the new repeated 5,000-item graph working-set control.
The original 4,096-capacity owner/test source and the final tested source are
retained separately. Earlier evidence packages were not rewritten.

`manifest.json` is a closed inventory of all other package files. The retained
JSON receipts, human-readable cProfile tables and test XML are the evidence;
`profile-observe.py` is the final diagnostic reproducer. Its later-added metadata
fields are absent from earlier receipts. No binary profiler data, checkpoint
weights, source databases, credentials or unrelated session messages are
included. See [the source-unit guide](../../CODEBASE_SOURCE_UNITS_384.md) for the
consumer boundary and source-unit limitations.
