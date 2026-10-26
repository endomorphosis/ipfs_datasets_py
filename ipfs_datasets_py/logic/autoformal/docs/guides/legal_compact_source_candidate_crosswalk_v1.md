# Physical cache references and original-bound source candidates

`legal_compact_source_candidate_crosswalk_v1` connects every selected paired-cache
physical reference to the candidates produced by the existing legacy source join.
It makes source linkage inspectable without selecting a historical character
occurrence. Even a unique exact match remains an unselected candidate.

The adapter performs delegated local I/O: the existing cache intake owner rereads
the exact retained manifests and Parquet tables and revalidates the original-bound
source/context inventory. The legacy join receives exact derived paired-row JSON,
the complete original producer receipt bytes, independently expected ordered row
commitments, and complete stored source sections. The legacy owner resolves the
receipt pointer and physical parent, then enumerates every literal occurrence.
This adapter introduces no text matcher, source revision aliasing, or source-parent
reconstruction. Historical reconstruction disclosures remain in producer records.

```python
report = prepare_source_candidate_crosswalk_v1(
    request_raw,
    expected_request_sha256=request_sha256,
    cache_originals=cache_originals,
    legacy_join_inputs=legacy_join_inputs,
)
digest = source_candidate_crosswalk_sha256(report)
validate_source_candidate_crosswalk_v1(
    report, request_raw,
    expected_report_sha256=digest,
    expected_request_sha256=request_sha256,
    cache_originals=cache_originals,
    legacy_join_inputs=legacy_join_inputs,
)
```

`cache_originals` contains exactly the existing cache owner's complete arguments:
`cache_request_raw`, `cache_bindings_raw`, `expected_cache_request_sha256`,
`expected_cache_bindings_sha256`, `manifest_bytes`, `repository_root`,
`inventory_report`, and `inventory_originals`. The adapter accepts no saved cache
report. It regenerates that report and compares its whole-report digest with the
independent request commitment. As in the underlying owner, file witnesses are
local custody observations; copying identical bytes into a different physical
fixture generally creates a different cache report.

After that replay, the adapter retains exact manifest bytes, the bounded original
inventory report, immutable inventory raw-byte/pin arguments, and the existing
inventory owner's complete partition custody snapshot. It checks them again
after candidate computation, alongside the committed legacy inputs and source
files. Receipt byte strings remain immutable input values.

The duplicate-free JSON request has exactly this structure:

```json
{
  "schema": "legal-compact-source-candidate-crosswalk-request/v1",
  "cache_intake_sha256": "<independently expected fresh cache report SHA256>",
  "legacy_joins": [
    {
      "manifest_path_in_repo": "<selected manifest path>",
      "inputs_sha256": "<independently expected legacy input commitment>"
    }
  ]
}
```

The joins must cover the exact selected manifest order, including unavailable
joins. `legacy_join_inputs` maps exactly those paths to a complete legacy-input
mapping or `None`; unavailable joins use `inputs_sha256: null`. A complete mapping
contains `expected_population`, `producer_receipt_bytes`,
`expected_producer_receipt_sha256`, `source_sections`, and
`expected_source_sections`. Its commitment uses the existing public
`legal_source_span_entity_join_v1.legacy_join_inputs_sha256` recipe: receipt bytes
are committed by SHA256 and length rather than embedded in metadata JSON. Missing
receipts require both receipt arguments null. Missing source sections use empty
ordered source/expected lists. Mismatched bytes or declarations are errors rather
than missing evidence.

`expected_population` is the full physical-slot population for its manifest, in
row ordinal order, including duplicate raw rows and unavailable cache slots. Each
pin has exactly `row_sha256`, `source_span_id`, `text_sha256`, and `source_revision`.
Verified derived bytes must match that physical slot's pin. Identical raw rows
with identical pins may share delegated candidate computation because the legacy
owner requires unique row commitments. Every cache reference is restored in the
output; row hashes never replace `physical_record_id` or `reference_id`.

The report preserves every selected slot, its physical and manifest identities,
expected/observed cache row hashes, cache status, source disposition, unchanged
legacy candidate record, and candidate occurrence IDs. Each bundle retains its
source-only legacy ledger, including full source-parent revision/artifact/row,
producer receipt linkage, complete section text and both Unicode-character and
UTF8-byte selectors. An historical span ordinal remains historical metadata,
never a character selector. Coverage reports candidate references and distinct
occurrences separately. Missing, corrupt or unsupported cache bundles retain
their slots with `cache_record_unavailable`; absent joins use
`source_join_unavailable`. Receipt/source absence keeps the existing owner's
explicit unresolved dispositions.

Bounds are checked before delegated candidate enumeration: 128KiB request,
four manifests, 64 physical rows per bundle, 128 rows total, 64 source sections
per bundle, 32MiB per original receipt, 4MiB join metadata, 4096 candidate
references, and 16MiB whole report. Existing owners retain their additional
source-text, occurrence, decoding, and JSON bounds. Exceeding a bound refuses the
operation; candidates are never truncated. Original receipts stay input bytes
and are not copied into reports. The crosswalk excludes the full cache payload,
so retained formal outputs and vectors do not become source context.

`validate_source_candidate_crosswalk_v1` checks the independent whole-report pin
and regenerates the complete report from all original inputs. Resealing an edited
candidate list, physical identity, selected occurrence, authority flag, or training
mask cannot establish agreement with those originals.

Every `selected_occurrence` and inference view remains null. All authority flags
are false and training/evaluation masks are integer zero. The authored inventory
occurrences remain a separate population: this stage creates no SourcePartitions,
independent access/chronology decisions, current-release crosswalk, reviewed
definition graph, training rows, model execution, Lean proof, or convergence claim.
Those are separate next steps after candidate correspondence review.
