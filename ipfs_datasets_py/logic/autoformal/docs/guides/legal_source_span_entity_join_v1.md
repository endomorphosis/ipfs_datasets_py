# Source, span and entity join manifest

The public `ipfs_datasets_py.logic.autoformal.legal_source_span_entity_join_v1`
module connects selected source-package metadata, complete paired-span bundles
and legacy occurrence candidates into one replayable manifest. It preserves
unresolved source correspondence and entity bindings. The entity input in this
first profile is metadata-only; no entity Parquet file or semantic graph is
inferred from its advertised schema or row count.

## Existing owners

The adapter delegates to:

- `legal_source_package_intake_v1`: exact five-file source metadata intake,
  using `legal_primary_graph_manifest` for source manifest validation.
- `legal_paired_manifest_inventory_v1`: explicit pinned paired-v1/v2 selection.
- `legal_paired_payload_intake_v1`: actual complete paired, goal and artifact
  table verification, preserving every physical row and adapter refusal.
- `corpus_legacy_source_join`: independently pinned producer receipts and
  complete stored source sections, retaining every exact occurrence candidate.
- `legal_entity_index_intake`: the existing twelve-field entity schema contract.
  This manifest does not invoke its file iterator or claim its census coverage.

The source metadata adapter retains the exact `manifest.json`,
`release_metadata.json`, `dataset_configs.json`, `dataset_infos.json` and
`README.md` bytes. Companion descriptor discrepancies and advertised-count
differences remain report issues. Validating their transport does not repair
the source release or verify its corpus/graph tables.

## Inputs and public API

`prepare_source_span_entity_join_manifest` takes the exact outer request bytes,
source request and metadata bytes, paired-inventory request and manifest bytes,
entity schema response bytes, an independently expected outer-request SHA-256,
and optional complete legacy-join inputs.

The closed outer request has these fields:

```text
schema = legal-source-span-entity-join-request/v1
source_request_sha256
paired_inventory_request_sha256
paired_bundles = [{manifest_path_in_repo, repository_root}, ...]
legacy_joins = {manifest_path_in_repo: independent_inputs_sha256, ...}
entity = {repository_id, revision, configuration, info_sha256}
```

Paired bundle order must equal the selected metadata manifest order. Each
retained root is an explicit caller input, never a path chosen by an offered
report. Actual table custody is checked by the existing payload owner. The
entity repository is `justicedao/uscode-autoformal-entity-cache`, configuration
`autoformal_uscode`, with an immutable forty-hex revision. The response must
declare the matching dataset/configuration and supported twelve-field schema.
Its commit association is caller-bound acquisition evidence; this operation
performs no remote authentication.

Each optional legacy input contains exactly `expected_population`,
`producer_receipt_bytes`, `expected_producer_receipt_sha256`, `source_sections`
and `expected_source_sections`. `legacy_join_inputs_sha256` commits the complete
ordinary-JSON inputs while replacing receipt bytes by their SHA-256 and size.
The delegated legacy owner validates the actual receipt and section content.
No short revision alias is expanded to the current source head. The stored
Parquet-text coordinate profile is distinct from the current source wrapper,
official HTML and other normalized views.

`source_span_entity_join_manifest_sha256` hashes the complete bounded report.
`validate_source_span_entity_join_manifest` requires an independent report pin
and regenerates all selected metadata, tables and candidate joins from the
original inputs. Rehashing an altered report does not replace this replay.

## Physical identities and dispositions

Physical identity includes repository, immutable revision, table path,
whole-file SHA-256 and row ordinal. Identical derived row bytes in different
files or positions remain distinct physical rows. `row_references` retains
every selected manifest-row reference; `physical_rows` accounts separately for
distinct physical tuples and their reference ordinals. Repeated references to
one physical row must agree on its observed identity and row digest.

Duplicate bytes within one bank are computed once by the legacy candidate
owner, whose input contract requires unique row commitments. The complete
physical population and all references remain in this adapter. Conflicting
independent expectations for duplicate bytes refuse the operation.

Source candidate records preserve source sections, Unicode/UTF8 selectors and
unresolved context. A unique text candidate remains unselected. No candidate
is passed as `source_bindings` to the paired adapter. Current-source release
correspondence stays `unverified_no_independent_crosswalk`; different revision
names alone do not prove incompatible legal editions.

Entity bindings remain `unavailable_semantic_companions_not_supplied` for every
row. Complete entity-file custody and scoped semantic companions require a
future compatible profile. All admission, semantic, proof and training flags
remain false; training and evaluation-gold masks remain strict integer zero.

The current bounds are sixteen selected bundles, 256 selected row references,
a 256 KiB outer request and a 16 MiB complete report, in addition to each
delegated owner's existing byte/node/depth/row limits. Overflow refuses the
operation instead of returning a truncated successful population. Source-owner
freshness is checked around preparation. Owner pins describe selected source
files; full execution provenance belongs to the frozen validation request.

## Qualification

Run new unit tests and the retained-data integration through the existing
`scripts/ops/legal_ir/run_owned_validation.py` owner, with independently frozen
code/input pins, a private attempt, existing scheduler policy and explicit
resource limits. Retained inputs and preparation scripts live at
`artifacts/legal-ir-source-span-entity-join-20261016-01/` in the parent workspace.
Inspect that packet's request, JUnit, replay assertions and durable result
before attributing successful execution to any source generation.

This adapter creates no reviewed statutory interpretation, definition binding,
training target, model improvement, Lean build or proof receipt. Its output is
the source-custody and unresolved-join input to those later stages.

## Explicit coordinate profile v2

The same owner exposes `prepare_source_span_entity_join_manifest_v2` and
`validate_source_span_entity_join_manifest_v2`, with the same argument layout.
The outer request uses `legal-source-span-entity-join-request/v2`; the complete
report uses `legal-source-span-entity-join-manifest/v2` and records the separate
compatibility profile `paired-coordinate-three-cache-join/v1`. The existing
complete-report hash helper applies to either profile. The v1 entrypoints
continue to require the legacy paired-v1/v2 selection.

V2 admits exactly one paired-v3 manifest and 1–64 declared physical rows. Use
the metadata owner's `legal-paired-manifest-inventory-request/v2` request, whose
selected manifest entry additionally requires an independently supplied
`source_coordinate_report_sha256`. That pin is checked against the manifest
declaration before source-package preparation or payload-table I/O. The outer
request still pins the exact paired request, source request and entity metadata
bytes independently. An exact manifest-byte pin, a complete-coordinate-report
pin, its embedded seal and the report artifact's byte digest have distinct roles.

`legacy_joins` must be empty in this first coordinate profile, and the optional
`legacy_join_inputs` must be absent, null or empty. Historical stored-Parquet
candidate recipes are not implicitly applied to a coordinate transport row.
The original legacy join remains available through v1.

The existing payload owner's v2 reader verifies the complete original report
population and every selected occurrence. Its report is embedded unchanged in
`paired_bundles[0].payload_intake`. The complete report appears exactly once,
as `source_coordinates.report_raw_utf8`, an exact UTF8 string. It is not parsed
and reserialized by the join. This preserves nested source-metadata insertion
order even when the outer join is serialized with sorted JSON keys.

Every `row_references` entry additionally retains:

```text
source_provenance_json
source_coordinate_report_sha256
source_coordinate_span_index
coordinate_transport_status = complete_report_occurrence_replayed
```

The original global span index is preserved; it is not renumbered within the
selected rows. Equal text in different original occurrences or physical table
positions remains distinct. `physical_rows` keeps its reference-ordinal mapping
and physical identity recipe; neither population is collapsed by text equality.
The separate coordinate replay count measures this transport observation only.

`selected_occurrence` remains null: it refers to the legacy candidate-selection
claim, not the new explicit coordinate reference. The source-package metadata
report, span report and entity metadata retain their different repository and
revision namespaces. `current_source_release_correspondence` remains
`unverified_no_independent_crosswalk`; entity bindings remain
`unavailable_semantic_companions_not_supplied`. Entity file rows are not decoded
or verified by this profile. All source, semantic, graph, training and Lean
authority flags remain false, and both masks remain strict integer zero.

The coordinate operation detaches bounded original metadata mappings and checks
the offered mappings again at closing. Exact original byte arguments and these
mappings share an 8 MiB aggregate bound, in addition to the delegated owners'
stricter limits. Source-owner pins include the existing source-manifest and
coordinate replay owners. These are selected source observations, not a complete
loaded-code attestation or a historical pin allowlist.

The same manifest and table inode/size/time witnesses are checked around the
existing payload decoder. Roots and files must be unaliased, and files must be
regular single-link leaves. These are ordered custody checks, not an atomic
snapshot of all three repositories. Closing original-input, source and file
checks all run on success and failure; secondary custody failures are attached
to the original exception rather than replacing it. The validator also checks
that its offered report did not change during full original-input replay.

The existing 16 MiB whole-report bound remains in force, including the exact
report string and JSON escaping. Overflow and unavailable, corrupt or changed
bundle files refuse the complete join; this owner does not return a truncated
success or infer a source/entity association. The separately implemented entity
census companion remains a distinct legacy-join profile until explicitly made
compatible. Coordinates alone do not activate entity graphs or semantic review.

Fresh focused qualification passed **128 cases / 384 test phases**: 45 existing
source-package cases use authored metadata through real owners, 48 legacy join
cases substitute orchestration delegates, and 35 new coordinate cases use real
source-package, metadata, payload and coordinate readers over authored local
Arrow fixtures. Four of the coordinate controls execute genuine delegates before
explicit negative closing-custody mutations or failure injection. None supplies
statutory correspondence or legal meaning, and no prior qualification is
relabeled by this port.

The native request binds 51 bounded function selectors; all 128 expanded case
IDs, all three passing phases per case and exact JUnit outcomes were verified
without skips, deselections or expected-failure credit. All 209 conservative
candidate file pins and 233 total request pins matched; the separately measured
imported/compiled candidate closure was 45 files. The existing owner sealed 289
files totaling 3,686,009 bytes, with original native/resource/storage cleanup and
source READ closeout. Actual storage libraries were PyArrow 25.0.1 and NumPy
2.1.3; DuckDB was not imported. Selected package startup remains isolated.

Requests, original source capture, source/import manifests, JUnit, sealed
artifacts and native release receipts are retained under
`workspace/test-logs/federal-corpus-audits/legal-ir-coordinate-three-cache-join-20261020-01/`
(`attempt-join-02` and `final-independent-qualification-v02.json`). The first
attempt passed all 128 pytest cases but remains unqualified because its wrapper
expected one incorrect parameter label. The corrected case list was independently
verified before the fresh run. All 286 failed-attempt files remain preserved;
the existing recovery owner released its unused 128 MiB storage promise.
Product and test bytes were unchanged between attempts. No model, training,
provider/network, entity census scan, graph admission or Lean execution occurred.


## HF wire intake v2 boundary qualification

The existing `prepare_source_package_intake_v2` and `validate_source_package_intake_v2` APIs accept the explicit `REQUEST_SCHEMA_V2` request with `metadata_profile=METADATA_PROFILE_V2` (`hf-default-parquet-envelope/v1`). The other six request fields remain `repository_id`, `revision`, `expected_release_identity`, `expected_graph_population`, `files` and `schema`. Supply independent original request/report hashes and the five exact metadata files; `source_package_intake_sha256` hashes the complete `SCHEMA_V2` report.

This strict v2 profile refuses inconsistent wire declarations. It checks exact file inventory, standard infos, canonical named card regions and logical config roles. Frontmatter delimiters must occupy whole lines; literal triple-hyphen filenames remain valid. Role flags must be plain booleans with the declared role, and the logical default retains its key and ordered features. V1 keeps its original observation/discrepancy semantics.

The explicit wire metadata intake passed 108 authored cases / 324 phases, including all 99 prior cases and nine focused controls; the same five retained HF49 metadata files were reused. Intake reconciles declarations only: it reads no tables and does not measure Arrow bytes, authenticate a remote revision, map source aliases or grant legal/training/gold/graph/Lean authority.

The earlier 99-case result remains historical. The separate 120-case alternate API was not installed when the source comparison detected the concurrent delivery. This generation extends the one existing v2 owner. Reports bind their actual owner source generation; prepare a fresh report instead of relabeling an old source-pinned report. The original v1/v2 source/span/entity joins retain v1 intake. The explicit v3 consumer below selects wire intake v2.

The [closed boundary qualification](../../../../../docs/autoformalization/evidence/legal-ir-hf-wire-intake-boundaries-20261024.json) retains original cleanup receipts. The selected run closed its compute/storage/source custody; the earlier peer zero-worker failure separately retains an unsupported 64 MiB storage reservation. Optional package initializers, source adoption, legal meaning, training/gold and graph/Lean admission remain outside this metadata qualification.

## Explicit HF wire coordinate join v3

Use `prepare_source_span_entity_join_manifest_v3` and
`validate_source_span_entity_join_manifest_v3` with the existing join argument
layout. The closed six-field outer request uses
`legal-source-span-entity-join-request/v3`; its independent source-request hash
binds an explicit `legal-source-package-intake-request/v2` request with
`metadata_profile="hf-default-parquet-envelope/v1"`. The complete report uses
`legal-source-span-entity-join-manifest/v3` and
`source_compatibility_profile="paired-coordinate-hf-wire-three-cache-join/v1"`.
The existing `source_span_entity_join_manifest_sha256` helper hashes this report.

V3 selects genuine `prepare_source_package_intake_v2` and closing
`validate_source_package_intake_v2`; it never falls back to legacy intake.
The opening source report is detached and byte-pinned. Closing checks compare
both source report objects before and after genuine validation, then check
original metadata, owner sources, retained files and the complete returned join.
Secondary custody failures remain attached to the original exception.

One complete paired-v3 bundle, 1–64 physical rows, original coordinate indices
and the complete coordinate report remain governed by the existing payload
owner. The 8 MiB original-input and 16 MiB complete-report bounds are unchanged.
The wire source intake reconciles declarations only; it does not read source
tables, measure Arrow bytes, authenticate a remote revision or map source aliases.
Local authored paired tables are verified by the existing coordinate payload
reader. Entity file verification and semantic bindings are not added.

The [closed v3 qualification](../../../../../docs/autoformalization/evidence/legal-ir-hf-wire-coordinate-join-20261024.json)
passed 123 authored cases / 369 phases: all 48 legacy cases and 75 coordinate
cases, including the original 35 coordinate cases and 40 v3 controls. The same
five retained HF49 metadata files were reused; no HF loader, release producer,
model, training or Lean run was repeated. Optional package initializers and the
whole installed package remain outside this namespace-scoped qualification.

V1/v2 retain their original schemas and legacy intake. Census, eligibility,
crosswalk, graph and native consumers have not adopted join v3; each needs an
explicit compatible profile and its own qualification. Selected occurrence
remains null, current-source correspondence and entity bindings unresolved,
masks strict integer zero and all authority false. Source/edition/meaning review,
training/gold, remote publication and graph/Lean admission remain separate.

The selected `hf-wire-v02` alone supplies this 123-case qualification. The earlier v01 logging failure retains zero case/phase credit and its original 256 MiB retained terminal; a later separately reviewed existing-owner [storage closeout](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-programme-review-20261022-05/hf-config-compatibility-01/wire-join-v01/v01-storage-closeout/independent-result-review-v01.json) released that promise while preserving all three failure logs (5,763 bytes). Administrative recovery does not turn the failed attempt into validation success.


## Downstream wire profile boundary

The qualified wire-coordinate join is `legal-source-span-entity-join-manifest/v3`, with profile
`paired-coordinate-hf-wire-three-cache-join/v1`. Its legacy v1/v2 predecessors
remain separate. The current downstream compatibility is:

| Consumer | Current accepted join contract | Wire-v3 status |
| --- | --- | --- |
| Coordinate entity census v2 | `legal-source-span-entity-join-manifest/v2`, `paired-coordinate-three-cache-join/v1` | Separate explicit integration required |
| Original-input target eligibility v2/v3 | Original join-v2 inputs and authoritative v2 replay | Separate explicit integration required |
| Coordinate graph/corpus routes | Their declared eligibility and original-input ancestry | No automatic adoption from join-v3 qualification |

When selecting that boundary, extend the existing consumer owner with an
explicit request/report contract, preserve old profiles and replay original
join inputs at opening and closeout. Keep source/edition correspondence,
occurrence selection, entity semantics, definition applicability and review
eligibility unresolved until their actual evidence exists. A wire-compatible
report alone cannot enable training/gold or graph/Lean admission.

The [delivery reconciliation](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-programme-review-20261022-05/wire-join-01/peer-delivery-reconciliation-v01.json)
verifies the current 123-case delivery. A concurrently staged ordinary-v3 /
coordinate-v4 alternative was never installed or executed and remains
unselected; its API names are not reserved. Reuse the qualified coordinate-v3
owner instead of porting those temporary drafts.


## Focused public dependency integration (2026-10-24)

The [accepted integration receipt](../../../../../docs/autoformalization/evidence/legal-ir-hf-wire-public-dependency-integration-20261024.json) records three existing cases / nine passed phases: one positive wire-intake case, one positive wire-coordinate join-v3 case and one legacy/profile-separation negative. They use the unchanged five authored metadata fixture files and local authored Arrow only. The complete historical intake 108/324 and join 123/369 cohorts were not repeated or pooled with these cases.

The measured source base was `ad4c1256`; all 44 selected files remain identical at this publication base after the exact two-product/two-test/five-fixture overlays. Public `span_cache.py` remains `e35f5333` and public `validation_pytest.py` remains `cef7fd00`. The historical cache adds only two transport methods with no references in the selected code/test closure; removing them restores the complete public module AST. Those historical receipts contain no per-method call telemetry. Current coordinate producers hash their actual owner files dynamically, so no output-hash parity or transplanted producer commitment is claimed.

The private `dc6ae4f1` pytest plugin is declared qualification orchestration and is not a product/test dependency or a public source port. The namespace profile uses explicit parent containers; optional initializers and whole public-package behavior remain unqualified. The check observed 35 loaded source entries and 28 checked import-compile sources. PyArrow 25.0.1 executed authored fixture work; DuckDB 1.4.3 was imported with zero database connections. Original source/native/resource/storage custody closed with 25 retained files / 281,592 bytes. The early snapshot remains `UNQUALIFIED_OBSERVATION_ONLY`, separate from accepted final gates.

No model, encoder, embedding, law-cache table scan, download or Lean work occurred. This receipt does not requalify the distinct P/private dependency profile. The original failed attempts and original 108/123 scope limits remain intact. Downstream census, original-input eligibility, crosswalk, graph/native adoption and source/meaning/training/gold admission remain separately selected work.

## Release adoption checklist — LIR-02 and LIR-21

The [observed law snapshot `91ca1838`](https://huggingface.co/datasets/justicedao/ipfs_uscode/tree/91ca1838853ac82d7a12dd4ab47d9686f47667f9) advertised the slash-form logical default and `data/**/*.parquet`; programme review observed a viewer config-name refusal. This is a release-adoption issue, not a fresh table/viewer readback supplied by this checklist. A broad glob alone does not establish heterogeneous Arrow schemas.

- **LIR-02 — select and reconcile.** Reuse intake-v2 and wire join-v3 with their separately selected compatible consumers. Preserve logical `publicus-ir-graphrag/v2` and the already implemented wire alias `publicus-ir-graphrag-v2`; do not rename the source profile or reinterpret historical reports.
- **LIR-02 — retain the data contract.** Bind exact immutable revisions and explicit descriptor/file membership. The existing wire profile uses five string columns (`entry_cid`, `legal_id`, `family`, `record_sha256`, `record_json`) with a family discriminator. Require actual table conformance before selecting that profile; metadata reconciliation alone reads no tables and authenticates no remote revision.
- **LIR-21 — qualify adoption and readback.** Use the existing release producer, corpus-release validator and immutable batch publication/readback owners to reconcile card/config/infos, file inventory, actual schemas/counts and viewer loading at the selected immutable revision. Keep physical records, laws, spans, entity-index rows and reviewed assertions as separate populations.
- **LIR-21 — publish coherently.** Optional per-family viewer views require an explicit compatible profile and matching consumer qualification. Select the release pointer only after complete readback; on failure preserve the previous coherent release and candidate/recovery quarantine custody.

Keep the [span snapshot `60501f3e`](https://huggingface.co/datasets/justicedao/uscode-autoformal-span-cache/tree/60501f3e920f6c9050cfc452e0d9fcc2b7c184f3) and [entity snapshot `79d54378`](https://huggingface.co/datasets/justicedao/uscode-autoformal-entity-cache/tree/79d54378c5d6a89ab56e7a27e0f0ba867e800e19) in their own revision namespaces. This checklist adds acceptance work to the existing BACKLOG tasks; it grants no Hub write, native execution, model work, semantic selection or training/gold/graph/Lean authority. Historical metadata and focused integration qualifications retain their original scope.
