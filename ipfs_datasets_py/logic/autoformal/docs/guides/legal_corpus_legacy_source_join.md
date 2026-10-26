# Legacy source occurrence candidates

`corpus_legacy_source_join` connects an explicitly supplied paired-row population
to complete, pinned legacy Parquet source sections. It preserves every exact
stored-text match, including overlaps. It selects no occurrence. A unique match
does not attest which occurrence the original producer used.

The in-memory API performs no downloads, Parquet reads, models or legal review:

```python
from ipfs_datasets_py.logic.autoformal.corpus_legacy_source_join import (
    build_legacy_source_join,
    validate_legacy_source_join,
)

ledger = build_legacy_source_join(
    paired_row_bytes,
    expected_population=independently_expected_population,
    producer_receipt_bytes=complete_original_producer_receipt,
    expected_producer_receipt_sha256=independently_expected_receipt_sha256,
    source_sections=verified_complete_stored_sections,
    expected_source_sections=independently_expected_source_sections,
)
```

Expected paired rows have exactly `row_sha256`, `source_span_id`, `text_sha256`
and `source_revision`. Expected source sections have exactly `repository_id`,
`revision`, `path_in_repo`, `artifact_sha256`, `artifact_bytes`, `release_id`,
`parquet_row_index`, `entry_cid`, `legal_id` and `text_sha256`; supplied source
sections add their complete `text`. Order, membership and hashes must agree.
The supported source is `justicedao/ipfs_uscode` at a complete immutable revision,
with path `uscode_parquet/laws.parquet`.

Before calling this API, the intake owner must verify the complete source file
against its externally expected digest and read the declared physical rows.
The ledger does not authenticate a caller's Parquet reference by inspecting
strings or accepting a digest declaration. It checks the supplied full section
text against its expected digest. The exact paired receipt pointer and its
source/parent descriptors constrain the physical row; a historical ordinal is
never used as a character offset or as evidence of a unique occurrence.

Each candidate reuses `corpus_source` records for the retained text/plain bytes
with an identity normalization profile. The larger Parquet artifact is retained
as a separate provenance reference. Edition is explicitly
`not_declared_in_source_artifact`, with no inferred historical year. Source
occurrences have exact Unicode-codepoint and UTF8 half-open selectors. These
are distinct from the HTML-derived normalized-view selectors required by
`legal_semantic_graph` and `EntityCache.build_proposed_graphs`.

The ledger retains `unique_exact_candidate`, `ambiguous_exact_candidates`,
`no_exact_occurrence`, `source_section_unavailable`,
`producer_source_unavailable` and `producer_parent_mismatch` dispositions.
Context remains `required_unresolved`. Empty source inventories and explicitly
unavailable producer receipts preserve the paired denominator. Every candidate
has a context declaration with open governing dependencies. All selection,
original-occurrence attestation, authority, admission, formalization and proof
flags remain false/null.

The complete ledger has the common 1 MiB record limit. Input populations are
bounded to 64 paired rows and 64 source sections; source text has a 128 KiB
per-section and 512 KiB aggregate limit. All exact matches must fit the per-row
256 and total 512 occurrence bounds. The original producer receipt has a
separate 32 MiB parsing limit; it is retained by digest, size and exact pointer,
without enlarging the common record limit. Overflow refuses the whole operation
without silently dropping candidates or source context.

`validate_legacy_source_join` requires the original paired bytes and all the same
independent input arguments; it recomputes the full ledger. Resealing an altered
selection, occurrence, context or provenance does not pass validation.

The existing recovery owner, `recover_legal_uscode_source_context.py`, remains
responsible for legacy source recovery. The existing
[proposed graph bridge](legal_corpus_proposed_graph_adapter.md) consumes genuine
HTML-derived selectors separately. A later view-to-view correspondence needs
its own checked evidence; neither text equality nor these candidate IDs grants
that equivalence.
