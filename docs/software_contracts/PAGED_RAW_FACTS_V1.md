# Explicit paged raw facts, version 1

`semantic_index.paged_fact_scan.scan_chunked_repository_paged_facts` performs
cold committed-content verification and per-file raw fact extraction. It does
**not** reconcile pytest identities across files, resolve the repository graph,
compile capsules, construct a semantic-state bundle, register a control-plane
root, or grant analysis/task completion authority. Its new root schema cannot
be passed to the legacy semantic-state consumer as a completed reconstruction.

The caller supplies an exact `PagedFactProfile`, a separate `FactSpoolBudget`,
an exclusively created `OwnedFactStore` outside the target repository, and the
exact repository/commit/tree/chunk-manifest identity. The default in-memory
scanner, manifests, decoder profiles, and legacy serializers are unchanged.

The profile retains 32 MiB working fact payload, 1 MiB records/index pages,
existing 8 MiB per-file fact envelopes, 4 MiB materialized source files,
128 MiB retained-source ceiling, existing 100,000 per-file record/AST limits,
and the 256 MiB/15-second-CPU analyzer child. The child has bounded pipes and a
20-second default timeout. The default 128 MiB Git decoder and explicitly
admitted 256 MiB Git decoder remain separate contracts.

New explicit structural limits are 256 index entries per page, depth eight,
8 MiB of retained coverage references, and structured-record depth 512. Those
limits refuse unsupported inputs; they do not drop or reclassify facts. Python
RSS is not the same as serialized working payload; actual worker RSS is reported
separately under its kernel address-space limit.

The cumulative spool budget has no defaults. It bounds stored bytes (up to
256 MiB), allocated file count (up to 100,000), raw records (up to 1,000,000),
spool I/O bytes (up to 4 GiB), and work items (up to 10,000,000). These are API
ceilings, not a claim that a particular repository fits or that larger native
runs have been qualified. Writes and verification passes are charged before
use, including existing-CID reads. Failed reservations remain charged. Source
decoding is additionally bound by the separately admitted chunk manifest.

Each file's six raw record groups retain their original extraction order.
Every committed raw path has a coverage entry, including analyzed empty files,
duplicate-blob paths, syntax errors, undecodable content, oversized inputs,
symlinks, and opaque gitlinks. Gitlinks are never followed or locally imported.
Projection artifacts and individual record identities are reverified against
their file/source bindings; index packing, ordering, ranges and counts are
independently checked before publication.

The request binds the exact paging/analysis/decoder budgets and profiles,
committed population, interpreter identity, trusted implementation source tree,
dependency source/data trees, and permitted import origins. Each child independently
recomputes that implementation profile before and after analyzing source bytes.
After complete content and coverage verification, the parent rechecks the source
fence and implementation profile before publishing `raw-coverage.json`.

The store retains an exclusive lifetime flock during production. After it is
closed, `OwnedFactStore.open_published` can reopen an exact request/root read-only
under a shared lifetime flock; the caller then runs `verify_raw_fact_coverage`
to verify all reachable coverage pages. This validates the stored raw output,
not independent re-execution of the analyzer. There is no resumed write mode or
implicit promotion of incomplete spools. A failed invocation leaves bounded
unpublished evidence and a structured refusal with stage, raw-path identity,
completed-entry/blob counts, and charged work; source text is not logged.

Later global assembly and consumer paging must be separately implemented and
qualified before any semantic reconstruction can use these pages. Any eventual
derived-root registration belongs to the existing authenticated DuckDB + Quack
coordination contract, preserving exact source/request bindings. This module
does not create or mutate a live database or control plane.
