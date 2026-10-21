# Original-bound entity census companion

`logic/autoformal/legal_source_span_entity_census_v1.py` attaches an
independently pinned, previously completed entity-index v2 census to the
existing source/span/entity join. It preserves that join unchanged and uses
the existing public owners for both checks:

1. `legal_entity_index_intake.validate_census_bindings` verifies the retained
   census seal, complete population and endpoint diagnostics, then rehashes the
   original file and checks its Parquet schema, footer and resource bounds.
   It does **not** decode the entity rows again.
2. `legal_source_span_entity_join_v1.validate_source_span_entity_join_manifest`
   regenerates the complete selected join from its original inputs.

The entity repository, immutable revision, configuration, declared population
and twelve-field schema must agree across the two results. The order above
rejects malformed census evidence before expensive join replay. These are
ordered custody observations, not an atomic snapshot across all files.

## API and exact inputs

```python
prepare_source_span_entity_census_v1(
    request_raw, join_report, census_raw, entity_path,
    *, expected_request_sha256, join_originals,
)
source_span_entity_census_sha256(report)
validate_source_span_entity_census_v1(
    report, request_raw, join_report, census_raw, entity_path,
    *, expected_report_sha256, expected_request_sha256, join_originals,
)
```

The request is duplicate-free UTF-8 JSON with exactly these keys:

```text
schema = legal-source-span-entity-census-request/v1
join_report_sha256
census_raw_sha256
census_sha256
entity = {
  repository_id, revision, configuration, file_sha256, file_bytes, rows
}
census_limits = {
  max_rows, batch_size, max_file_bytes, max_decoded_bytes,
  max_row_group_bytes, max_batch_bytes, max_row_bytes, max_scratch_bytes
}
```

The repository is `justicedao/uscode-autoformal-entity-cache`; configuration is
`autoformal_uscode`; revision is an explicit lowercase forty-hex identity.
These are caller-supplied acquisition identities, not authenticated remote
history. All eight census limits must exactly match the original census and
remain within the existing intake owner's bounds. They cannot be silently
widened for replay. `endpoint_details=True` is mandatory; a v1 census is not a
substitute for the detailed v2 evidence.

`join_originals` is a closed mapping of the unchanged join owner's inputs:

```text
request_raw
source_request_raw
source_metadata_bytes
paired_inventory_request_raw
paired_manifest_bytes
entity_info_raw
expected_request_sha256
legacy_join_inputs
```

The two metadata mappings contain exact original bytes. `legacy_join_inputs`
is the original mapping or `None`, not a reconstructed report projection. Each
provided legacy entry retains its complete expected population, receipt bytes
or unavailable `None`, independent receipt pin, source sections and independent
section expectations. Its exact fields and source commitments remain the
existing join owner's responsibility.

`entity_path` must be the original absolute physical path recorded in the
census. The public binding validator compares the entire reconstructed source
descriptor. Copying a file does not authorize rewriting the historical census
path and resealing it. A relocated evidence package needs a separately designed
custody contract; this adapter does not silently relax the existing one.

## Hashes and retention

Keep these three different identities distinct:

| Identity | Recipe |
| --- | --- |
| `census_raw_sha256` | SHA-256 of the exact original JSON file bytes, including formatting. |
| `census_sha256` | Existing census owner's SHA-256 of compact, sorted, non-ASCII-escaped UTF-8 JSON with only the self-seal field `census_sha256` omitted. |
| `source_span_entity_census_sha256(report)` | SHA-256 of the complete bounded canonical companion report; no report field is omitted. |

The join has its own existing canonical report identity. An independently
supplied request pin binds these identities; reading a census's self-seal and
presenting it as an independent pin is insufficient provenance.

The companion retains the exact census UTF-8 bytes and its complete parsed
report, including missing endpoints, duplicate physical rows, legacy boolean
observations and all negative dispositions. It retains the full replayed join
unchanged. The nested join's historical `verified_file_rows=0` still describes
that metadata-only join; the separate companion describes the additional
physical-file evidence rather than rewriting its predecessor.

`join_originals_sha256` is an input-custody commitment. Raw original byte
arguments and metadata byte values are represented by their SHA-256 and byte
length. Legacy ordinary arguments are canonically encoded and committed the
same way, with receipt bytes committed separately. The resulting identity
mapping is canonically encoded and hashed. This commitment does not replace
the original join's independent request, receipt and source pins.

## Coverage and custody limits

`prior_entity_census_rows` is the historical complete decoded population from
the independently pinned census. `fresh_entity_rows_decoded=0` describes this
adapter's actual work. Fresh verification covers file bytes, schema and footer;
`fresh_entity_row_replay_performed` remains false. Original rows remain in the
immutable entity file. The adapter does not select entity rows, reconstruct
edges, verify current source-table rows or infer section coverage.

Each selected paired reference retains its order, physical identity and raw
row identity. `entity_semantic_binding` remains `null`, with reason
`semantic_companions_not_supplied`; the aggregate semantic binding count also
remains `null`. A missing binding is not a measured zero-error result. All
semantic, training, evaluation, graph and proof authority flags remain false;
training and evaluation masks remain zero. Labels, IDs and legacy admitted or
formalized flags cannot establish scoped definitions or governing use.

Original join arguments are detached before delegated calls. On success and
failure, closing checks inspect the offered originals, offered join report and
selected owner source hashes. The outer validator also checks the offered
companion report after replay. All closing checks are attempted; secondary
custody failures are attached as exception notes without replacing the first
operational exception. These fences do not claim arbitrary concurrent-writer
or complete loaded-byte attestation. The producer-pin scope is explicitly the
selected source files; `loaded_byte_identity_verified` remains false.

Bounds are 128 KiB for the request, 1 MiB for raw census JSON, 16 MiB for the
original join report, 64 MiB aggregate original argument bytes and 32 MiB for
the companion. The original-argument bound excludes the separately checked
Parquet file. The entity owner's limits govern that file and its footer.
Over-limit evidence is rejected rather than truncated or sampled.

This API creates no scheduler, reservation or controller. Qualification must
use the existing resource and source-lease owners. A real retained fixture can
prepare and replay the companion without network, new scans, models, training,
semantic reviews or Lean execution. Self-resealed report-tampering cases require
full original replay and should be explicitly budgeted; fixed-pin mismatches
can be tested before that work. Negative unit fault injections must remain
separate from actual retained-evidence qualification.

## Additive coordinate v2 companion

Qualification status: **PASSED — original census-04, independently accepted**.
The original controller completed 41 cases and 123 setup/call/teardown phases
with zero skips: 37 new coordinate-companion cases and four ported entity-owner
regressions. The prior 141-case qualification remains separate and was not rerun.
The new companion fixture prepares one tiny 16-row detailed census in module
setup; companion preparation and replay perform zero entity-row rescans.
The exact candidate has 230 source files and the native request pins 256
sources; the original normal granted-native owner proved compute/storage
cleanup and closed source READ. The c758 runner result is scoped to this
normal path; this census run does not qualify broader lifecycle59, and no fallback ran.
See the retained `qualification-summary.json` in the census phase and
`docs/autoformalization/evidence/legal-ir-coordinate-entity-census-20261021.json`.
This transport/custody result does not establish statutory meaning, reviewed
entity bindings, model accuracy or Lean admission. Installation/publication
are separate actions. The original v1 definitions, request schema and legacy
join dispatch remain unchanged; v1 rejects coordinate-v2 requests and joins,
and explicit v2 APIs reject v1 profiles.

```python
prepare_source_span_entity_census_v2(
    request_raw, join_report, census_raw, entity_path,
    *, expected_request_sha256, join_originals,
)
source_span_entity_census_join_originals_sha256(join_originals)
source_span_entity_census_sha256(report)
validate_source_span_entity_census_v2(
    report, request_raw, join_report, census_raw, entity_path,
    *, expected_report_sha256, expected_request_sha256, join_originals,
)
```

The v2 request is duplicate-free UTF-8 JSON with exactly eight top-level keys:

```text
schema = legal-source-span-entity-census-request/v2
join_report_sha256
census_raw_sha256
census_sha256
entity = {
  repository_id, revision, configuration, file_sha256, file_bytes, rows
}
census_limits = {
  max_rows, batch_size, max_file_bytes, max_decoded_bytes,
  max_row_group_bytes, max_batch_bytes, max_row_bytes, max_scratch_bytes
}
join_originals_sha256
source_coordinate_report_sha256
```

The report schema is `legal-source-span-entity-census/v2`, with
`source_compatibility_profile=paired-coordinate-entity-census/v1`. The same
complete-report hash function serves both companion versions.
`expected_request_sha256` must independently pin the exact request bytes.
The canonical full join pin, exact prior-census raw pin, prior-census self-seal,
original-input commitment and coordinate-report pin remain separate identities.
A supplied self-seal or a digest recomputed from an untrusted report is not
independent retained evidence.

The originals helper commits the same closed eight-field original-argument
mapping described above. Four raw byte arguments are limited to 256 KiB each;
each metadata mapping has 1–16 entries with nonempty UTF-8 names of at most
512 bytes. Their exact byte values and lengths are committed. The aggregate
original-byte limit is **8 MiB** for this coordinate profile; the original
v1 limit remains unchanged. `legacy_join_inputs` must be `None` or an empty
ordinary mapping. The helper also checks the original request bytes against
their independently supplied request pin. The helper creates an identity;
callers must retain that identity independently before relying on it in a
later request or replay. It grants no source or semantic authority.

V2 calls the existing public
`legal_source_span_entity_join_v1.validate_source_span_entity_join_manifest_v2`
against all captured originals. A copied join report or a wrapper success flag
does not substitute for this genuine regeneration. The selected join must have
exactly one complete coordinate bundle with **1–64** ordered physical paired
rows and references. The upstream join and payload owners retain their stricter
input checks. Partial populations, reordered references and mixed legacy
occurrence inputs cannot be silently accepted.

The companion retains the complete regenerated join unchanged. Its complete
raw coordinate report is retained once inside that join, with its raw-byte
identity and independently pinned canonical coordinate identity. Each companion
reference adds `source_provenance_json`, `source_coordinate_report_sha256` and
`source_coordinate_span_index`; these must exactly match the corresponding
payload reference. A global coordinate index of `1` can belong to physical
paired row `0`. Neither that global index nor a companion reference ordinal
should be substituted for a physical table-row ordinal. Identical text at
distinct coordinates remains distinct evidence. Exact occurrence transport
does not verify a current statutory edition or select an entity meaning.

The original detailed entity census and original absolute `entity_path` remain
mandatory. A prior 1,960,876-row retained census may be reused at that original
path with its independently retained pins and unchanged limits; this is not a
new census. Reuse preserves every recorded endpoint defect, duplicate and
legacy boolean observation. It does not repair empty endpoints or attach
entity rows to the selected spans. A tiny authored test census must declare its
own actual population consistently across the genuine join and census; it
cannot be presented as that historical population.

Preparation first calls the genuine entity binding validator with
`endpoint_details=True`, then genuinely replays the coordinate join. On every
exit after entering this custody operation, the closing checks attempt another
entity binding validation, inspect paired-file witnesses, compare both offered
and detached originals with the independent commitment, check offered and
captured join identities, and inspect selected producer source hashes. The
outer validator also fences the offered companion report. An opening entity
binding failure still receives the closing entity check; paired-file closing
checks apply once the selected bundle context has been captured. All applicable
checks are attempted, and secondary failures are attached to a primary failure
instead of replacing it.

Opening and closing entity bindings rehash the original entity file and check
its schema, footer and bounds without decoding entity rows. The final paired
check reuses the existing join owner's physical-file witnesses: retained paths,
regular-file and link constraints, device/inode, mode, size and modification/
change timestamps. It detects drift after the genuine join validator returns.
It is a fresh metadata observation, **not a second payload hash or payload-row
replay**. These ordered opening and closing observations do not provide an
atomic snapshot, arbitrary concurrent-writer protection or loaded-byte
attestation. The report keeps those limits explicit.

A successful preparation therefore makes two genuine entity binding calls and
one genuine public join-v2 validation. Preparing and then publicly validating
the companion repeats preparation, giving four entity bindings and two public
join validations. These are API behavior requirements, not a claim that any
qualification run has completed. `fresh_entity_rows_decoded` remains `0`,
`fresh_entity_row_replay_performed` remains false, and the nested join's
metadata-only entity `verified_file_rows=0` is preserved.

`coordinate_occurrence_replayed_rows` counts selected references transported
with exact coordinates. `prior_entity_census_rows` counts the separate retained
historical population. Neither count measures semantic fidelity.
`entity_semantic_binding` and its aggregate count remain `null`, all authority
flags remain false, and every training/evaluation mask remains integer zero.
No graph admission, governing-definition resolution, semantic review,
training/gold eligibility, model execution or Lean admission follows from this
companion. New qualification receipts must be appended only after the original
resource/source owners close and the actual outcomes have been reviewed.
