# Retained ordinal diagnosis

`scripts/ops/legal_ir/diagnose_uscode_identity.py` provides a bounded,
metadata-only hypothesis test after an independently accepted stopped source
generation. It takes explicit absolute database, manifest, report, archive and
accepted-review paths, each with a required SHA-256 pin, and a fresh output path.
It never reads the original source Parquet, source text, vectors or model bodies.

The shared nonblocking stopped-writer lock, no-WAL state, exact review bindings,
generation/profile/code pins, cursor and accounting must pass. Duplicate or
conflicting archive IDs refuse. Every retained historical span ID is rebuilt
from its exact stored citation/CID/legal/title/section/hash and historical ordinal
before **any** per-document hypothesis is hashed. The second pass changes only
the ordinal to `source_section_span_ordinal` and joins unresolved archive rows on
the full candidate ID plus exact SHA-256 and legal ID.

The outputs are `report.json` and `candidates.parquet`, published together by
atomic no-replace directory rename. Candidate rows contain identity/context
metadata, preserve the original generated ID and physical occurrence ID, and
record retained-subset multiplicity. No aliases, training records or embedding
reuse approvals are created. Singletons are not globally unique across the full
source; outside-target identities remain unavailable. Zero and partial results
leave unresolved archive counts visible. Original producer recipe, gold,
semantic fidelity, teacher and proof qualification stay false.

Defaults and hard ceilings are 65,536 retained rows, 500,000 archive rows,
256 MB DuckDB memory, one thread, no spill, 128 MiB per input, 32 examples,
2 MiB report and 8 MiB total output. Candidate writes are bounded before each
write. Staged files are checked for exact membership, regular canonical paths
and byte ceilings before bounded SHA-256 rereads. Input drift, overflow, foreign destinations and interrupted staging
refuse without publishing results or modifying the old database. Resource
admission and independent result review belong to the supervising guardian;
the DuckDB setting does not cap the whole Python process.

The report records elapsed time from call entry through report creation, with
final custody fences and publication excluded. `RUSAGE_SELF.ru_maxrss` is the
process-lifetime high-water observed then; Linux reports KiB, also converted to
bytes. This is neither a phase nor a process-group peak.

All API names become CLI flags by replacing underscores with hyphens. Required
pins use `--expected-database-sha256`, `--expected-manifest-sha256`,
`--expected-report-sha256`, `--expected-progress-sha256` and
`--expected-accepted-review-sha256`. Neither diagnostic candidates nor the
available historical compiler digest authenticate an original ingest launch.
