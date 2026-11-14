# LegalIR cache census and statutory source preparation

Date: 2026-10-15. This implements a bounded first part of the
[US Code improvement plan](legal_ir_uscode_corpus_improvement_plan_20261015.md).
It extends the existing entity-index intake and prepares source review inputs.
No training targets, accepted legal meanings, graph repairs or Lean proofs are
claimed by this work.

## Implemented contract

`logic/autoformal/legal_entity_index_intake.py` now accepts
`endpoint_details=True` in `census_parquet`, full replay validation and pinned
binding validation. This emits `legal-materialized-entity-index-census/v2` with
four exclusive edge dispositions: missing values, nonempty dangling references,
ambiguous declared node IDs and unique declared endpoints. Separate endpoint
diagnostics retain overlap and repeated physical edges. Ontology metadata does
not count as a graph edge; strings match exactly without label inference.

Default requests preserve the v1 output and digest. Both versions keep every
semantic, training and proof authority flag false. The v2 validator checks its
closed nested schema, matching policy, count types/bounds and authority flags
even when the independently supplied report digest matches. See the
[intake guide](../guides/legal_entity_index_intake_20261013.md).

## Fresh whole-file evidence

The actual bytes of
[entity cache revision `79d54378c5d6a89ab56e7a27e0f0ba867e800e19`](https://huggingface.co/datasets/justicedao/uscode-autoformal-entity-cache/tree/79d54378c5d6a89ab56e7a27e0f0ba867e800e19)
were downloaded and hashed: 11,139,328 bytes, SHA-256
`f5f07379d4ca913cb2d8d98505a4ecb01e4d0658039a2f4ff84fb4fb585e8233`.
The fresh traversal covers its full physical population.

| Observation | Count |
| --- | ---: |
| All records | 1,960,876 |
| Node records | 238,452 |
| Nodes with empty IDs | 119,134 |
| Distinct nonempty node IDs | 119,318 |
| Duplicate nonempty node ID groups | 0 |
| Edge records | 1,722,395 |
| Edges with both endpoints empty | 1,722,395 |
| Nonempty dangling / ambiguous / uniquely resolved edges | 0 / 0 / 0 |
| Category / logical-relation / classification-rule records | 9 / 6 / 14 |
| Repeated raw-row instances beyond first occurrences | 1,722,389 |

These values happen to match retained historical totals, but this report binds
the newer file's bytes. Zero dangling references does not imply linkage: no edge
has a nonempty endpoint. The index cannot supply the intended semantic graph
until exact source identities are recovered. This change diagnoses the defect;
it does not reconstruct missing endpoints or establish the upstream cause.

The first captured-v1 scan and independent DuckDB aggregate had no resource-owner
lease; that limitation and their original records remain retained. The new v2
run acquired the existing scheduler's validation lease under policy
`f07cb14289fcb6275e4497dcc36be0dcf8bfc3dc87531ff7a9537eb85fdcc661`, completed,
and released it. No scheduler or policy was created or replaced.

- **50 focused tests passed** in 1.04 seconds, including all existing intake
  cases and new versioning, missing/dangling, multiplicity, malformed-schema and
  false-authority cases.
- The full v2 scan took **24.123 seconds** inside the child. Projecting out the
  new details and restoring the v1 schema/digest reproduced the entire retained
  v1 report exactly, including source custody and ordered stream identity.
- v2 census digest:
  `ba91ce2b51cbeb4e0852ed896cda9f5a248d5201417c3a09806c94809f1497e8`.
- Sampled direct-child RSS peaked at 94,400 KiB during this isolated scan. This
  is a sampled process observation, not total pipeline cost or a kernel memory
  quota. The earlier combined inspection's process-lifetime peak is separately
  retained and is not a matched performance comparison.
- Existing package sources were loaded through minimal namespaces to avoid
  application initializers. This qualifies the specific offline intake path,
  not ordinary package startup or end-to-end supervisor execution.

## Real source component prepared

The candidate component now uses the actual **officer** definition in
10 USC §101(b)(1), with complete candidate use paragraphs in §7213 and §7214.
The earlier engineering example defined **enlisted member**, so it cannot supply
the officer binding.

The source packet preserves the retained official 2024 §101 page and its 560
blank review guides. Two small official 2024 pages were acquired and processed
through the existing sampler/review owners:

- [2024 §7213](https://www.govinfo.gov/content/pkg/USCODE-2024-title10/html/USCODE-2024-title10-subtitleB-partII-chap723-sec7213.htm): 26 complete blocks.
- [2024 §7214](https://www.govinfo.gov/content/pkg/USCODE-2024-title10/html/USCODE-2024-title10-subtitleB-partII-chap723-sec7214.htm): 41 complete blocks.

All **627 blank guides** are retained, with six focused blank drafts for the
definition, scope, neighboring definitions and two uses. There are **zero actual
reviews, qualified targets, semantic graph assertions or Lean builds**. Whole
pages, notes, controls, exact source hashes and character/UTF-8 selectors remain
available. Independent standard-library verification passed **122 checks**.

Both new operative paragraphs exactly match the historical candidate paragraph
bytes. Their source versions and coordinates remain distinct: the old Parquet
edition was undeclared, and matching text does not establish source lineage or
governing applicability. The packet has 13 actual loaded package-source pins;
12 match published Datasets `234dc97a2fedb864c99add7f0d8e37ba81c785cf`. The local
`legal_statutory_context.py` retains the older inline dependency-slot helper.
The actual local source forest is recorded rather than relabeled as published
main. One failed inspection-driver invocation and its corrected retry are also
retained; the failure changed no implementation owner.

## Retained artifacts and reproduction

Workspace evidence root:
`lift_coding/artifacts/legal-ir-cache-source-qualification-20261015-01/`.

- `entity/`: immutable Parquet, captured old scanner, v1 census, independent
  aggregates, source/hash manifests and honest resource limitations.
- `source/`: exact official and historical sources, blank review bundles,
  source comparisons, loaded-source pins and packet integrity verifier.
- `capabilities/read_only_capability_inventory.json`: 16 source hashes and four
  concrete decoder profiles; metadata presence is separate from actual checkpoint
  loading and inference qualification.
- `validation/attempt-01/`: focused test log, v2 census, full v1 comparison and
  existing-scheduler execution/release receipt.
- `compatibility-manifest.json`: an evidence projection joining these exact
  artifacts and stage statuses. It grants no runtime, review or training authority.
- `entity-recovery-leads.json`: exact retained primary-graph manifests, scoped
  writer/reader history and the next existing-owner replay sequence. All 74
  selected shard paths were located and their sizes checked; their bodies were
  not rehashed in this recovery step. The retained 119,134-node/178,691-edge
  reconstruction remains a distinct population from the broken legacy index.

From the `lift_coding` workspace, inspect source integrity without network access:

```bash
python artifacts/legal-ir-cache-source-qualification-20261015-01/source/verify_source_packet.py
```

To repeat the tests and census, choose a new output path; the retained driver
uses the same existing scheduler and refuses policy drift or unavailable admission:

```bash
python artifacts/legal-ir-cache-source-qualification-20261015-01/validation/run_checks.py --output artifacts/legal-ir-cache-source-qualification-20261015-01/validation/replay-01
```

The driver reserves one CPU slot, 8 GiB and one child slot. It uses a 120-second
phase deadline, sampled direct-child RSS guard and kernel CPU/file-size limits.
It is a bounded audit reproducer, not a general process-tree sandbox or a new
supervisor. It does not run models or solvers. A new run still needs available
native admission; no acceptance threshold is changed by this command.

## Remaining work

1. Recover exact upstream graph records and writer lineage before creating an
   endpoint-preserving corrected entity export. Labels cannot replace missing IDs.
   The recovery lead identifies `select_primary_graph_manifest`,
   `verify_primary_graph_files` and `validate_reconstruction` as the existing
   replay owners. The historical ten-field publisher is a possible loss
   mechanism, not an established identity for the final twelve-field writer.
2. Complete span-cache inventory by producer and source identity. The retained
   span metadata observation is not a full current cache-row or training-target census.
3. Obtain actual independent source/meaning and applicability decisions for the
   proposed component. Blank guides and source equality supply no semantic review.
4. Represent complete approval, quantity, purpose, pronoun and definition scope
   structures, then qualify all-occurrence binding and compatible V2 lowering.
5. Train and evaluate only after representable reviewed targets and fresh
   evaluation groups exist; retain all pending and unsupported material.

The existing 24-task backlog was not rewritten or marked complete. No original
cache or report, learned checkpoint, production service or repository remote was
modified by this phase.
