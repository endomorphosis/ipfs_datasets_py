# Selected historical-parent source inventory

`legal_parent_source_inventory_v1` prepares source-only metadata for an explicitly
declared selection of physical rows in a historical parent Parquet artifact.
It replays the unchanged public parent parser against the original file before
projecting metadata. A selection of 13 rows in the 60,077-row historical
`uscode_parquet/laws.parquet` remains a 13-row selection.

The public functions are:

```python
prepare_selected_parent_source_inventory_v1(
    descriptor,
    row_report,
    *,
    expected_descriptor_sha256,
    expected_row_report_sha256,
    preflight_report,
    expected_preflight_sha256,
    row_ordinals,
    expected_row_sha256s,
)

validate_selected_parent_source_inventory_v1(
    report,
    descriptor,
    row_report,
    *,
    expected_report_sha256,
    expected_descriptor_sha256,
    expected_row_report_sha256,
    preflight_report,
    expected_preflight_sha256,
    row_ordinals,
    expected_row_sha256s,
)

selected_parent_source_inventory_sha256(report)
```

Supply expected hashes and the complete ordered ordinal/hash lists from the
source intake boundary. The hash helper only hashes bounded canonical metadata;
original-bound validation reconstructs the entire report, including all flags,
nulls and integer masks. Rehashing a modified report cannot qualify a changed
source, selector, partition, permission or authority claim.

Preparation captures bounded, detached plain JSON originals, verifies their full
canonical hashes, and calls
`legal_parent_parquet_pages.validate_selected_parent_rows`. That existing public
owner reopens the complete parent under its guarded descriptor, hashes the
artifact, regenerates the preflight and selected rows, and checks every expected
full raw-row hash. The new owner then checks that neither the caller's originals
nor the delegated snapshots changed. No alternative Parquet parser, text search,
code parser, model or database runs.

The report uses schema `legal-parent-selected-source-inventory/v1`, profile
`historical-parent-selected-source-metadata/v1`, and scope
`declared_physical_selection_only`. It retains the complete parent descriptor,
its independent SHA256, the full preflight/row report SHA256 values, the ordered
selection and its canonical commitment, complete source-schema metadata, and
separate declared-parent/selected/replayed row counts.

Each selected physical row remains present. Its identity binds the full literal
repository and revision, parent path, artifact SHA256 and byte count, and absolute
Parquet row index. `physical_section_id` is `sha256:` followed by the SHA256 of
that key's compact sorted UTF-8 JSON with `ensure_ascii=False`. It matches the
preceding physical source-section projection. `full_raw_row_sha256` covers every
field of the verified original row, including all 45 fields in the real parent;
source metadata does not replace the complete raw-row evidence.

The projected `text` field contains only the exact UTF-8 SHA256, UTF-8 byte count
and Unicode-codepoint count. Complete source text and uninterpreted raw-row extra
values are not retained in this inventory. Literal `ipfs_cid`, `title_number`
and `section_number` observations are retained as strings or null, with explicit
`observed_string`, `missing` or `unsupported_type` statuses. These observations
do not infer a canonical legal identity, applicable edition or producer origin.

Text dispositions preserve the complete selected denominator:

| Original text value | Disposition | Text metadata |
| --- | --- | --- |
| Nonempty string, including whitespace | `stored_text_available` | Exact hash and lengths |
| Empty string | `empty_text` | Empty-byte SHA256 and zero lengths |
| Missing field or null | `missing_text` | Null |
| Other supported parent value type | `unsupported_text_type` | Null |

`normalized_content_sha256` uses the existing
`unicode-whitespace-casefold-v1` recipe:
`sha256(" ".join(text.split()).casefold().encode("utf-8"))`.
The recipe is spelled out here to avoid importing optimizer or model modules
just to normalize source metadata. The exact raw text hash remains separate.
Equal normalized hashes do not establish legal or source equivalence and do not
merge physical occurrences or create group/split assignments.

This API accepts no cache/candidate report, formal target, catalog, entity graph,
vector, checkpoint, tokenizer or model identity. Historical candidate links can
later reference the inventory SHA256 and physical section IDs in a separate
companion. Original-occurrence decisions, source/current-release crosswalk,
access and chronology evidence, source-derived catalogs and encoder receipts
remain separate inputs to their existing owners.

Every row and the overall report retain `group_id=null`, `split=null`,
`inference_view=null`, false authority flags, and plain integer zero training and
evaluation-gold masks. The selected-source codec does not present itself as
`USCodeSourceInventory` or `SourcePartitions`. It constructs no release, model,
retrieval-admission or training identities and does not authorize producer,
trainer, evaluation or Lean execution.

The selected profile keeps the existing 32-row maximum and the unchanged parent
owner's file/page/row/decoded-byte limits. Input JSON is bounded before canonical
serialization by 16 levels, 262,144 visited nodes, 65,536 members per collection,
8 MiB per UTF-8 string, and 64 MiB per complete input. Parent ordinals must be
plain integers, distinct and sorted. Output metadata is capped at 2 MiB and is
detached from caller-owned collections. Limits are finite input/output contracts,
not an operating-system memory quota or transient-write attestation.

A full historical-parent inventory remains separate work. It must account for
all 60,077 physical ordinals, exclusions, aliases and grouping connectors before
whole-parent partition claims. Scale through a bounded metadata iterator in the
existing page owner, retaining source hashes and discarding resident text, rather
than thousands of independent full-file selected-row replays. Existing physical
document/text grouping still requires governing-definition and context dependency
closure before scientific holdout or training qualification. Source equivalence,
legal meaning, model convergence and Lean admission require their own evidence.
