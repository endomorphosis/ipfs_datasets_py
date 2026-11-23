# Candidate Legal corpus graph exchange

## Release-v3 graph transport source-only 56 qualification — 2026-11-15

Select the V3 replay explicitly with `python -B scripts/ops/legal_ir/validate_uscode_corpus_release.py validate-closure --request PATH --request-sha256 SHA --profile reviewed-norm-v3-physical-three-cache-replay/v1`. The default remains `reviewed-norm-v2-local-replay/v1`.

The V3 controls replay a complete fictional signed three-cache component (an 83-file fixture) and reconstruct its bounded four-chunk packet transport. Complete typed records and literal policy are checked; incomplete/reordered/aliased transport is refused. This fixture demonstrates software replay behavior, without actual Native Lean or real US Code release admission.

The current release-v3 source-only batch covers the release coordinator, validate_uscode_corpus_release CLI and its maintained owning controls. The opt-in transport/closure path preserves the default domain and legacy request identity, checks the literal packet policy, and validates complete ordered chunk transport and mixed physical closure using reviewed test components. These are software behaviors, not actual US Code, Native Lean, model or corpus admission.

One fresh original run selected 13 functions and passed 56 exact natural cases in 33.61 seconds, with zero failures/errors/skips. The result and execution records and full JUnit classname/name/parameter-ID order were independently joined. The explicit source frontier contains 198 pinned files, checked unchanged; no raw import-origin stream establishes that every runtime import belonged to that frontier. No old 56/155/146 outcome is pooled or transferred.

Original Source R+A, Native, sampled-process and genuine-wait custody closed in 189.529 seconds, before the initial 420-second acceptance cutoff. Its own 32MiB promise was durably released after 61 sealed rows plus the seal, 62 files / 6,572,203 bytes. The existing CPU1, memory1536MiB, process4 and productive 120-second request limits stay unchanged. The reviewed helper uses one shared 60-second Source-admission cutoff inside that initial 420 acceptance clock, without deadline renewal, hard-preemption claims or a new runtime grant.

This publication preserves all current peer sections, 119 owners, 24 task IDs/states, retained failures and private-asset/runtime holds. Source-generation, delegated immutable@2, actual live SDK cleanup, full-import qualification, native Lean and real corpus/model/training/legal validation remain separate gates. [Current 13/56 exact evidence](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-current-release-v3-source-only-R56-qualified-20261115-v01/qualification-summary.json).


This additive v1 profile exports and validates a bounded local candidate graph.
It preserves complete sealed node/edge records and explicit graph endpoints.
It is a graph interchange format, not a complete statutory or Lean corpus
release. Validation establishes local record/file integrity; it does not
authenticate source provenance, review legal interpretation, resolve external
references, run a model, compile Lean, or publish to Hugging Face.

The source, qualification and graph contracts remain separate. Use
`corpus_source` to bind exact raw/extracted identities and extracted-view
coordinates. Use the current review/interpretation owners to qualify meaning.
A graph node's content/source/interpretation CIDs are preserved references:
their presence alone does not authenticate the referenced records.
Losslessness applies to graph envelopes. Source records, producer-specific
formal payloads and review receipts addressed by those CIDs remain external;
retain the companion candidate records when exchanging those payloads.

## Format and supported profile

The API owners are `logic/autoformal/corpus_graph.py` and
`logic/autoformal/corpus_graph_exchange.py` under `ipfs_datasets_py/`.

| File | Content |
| --- | --- |
| `snapshot.json` | Exact canonical DAG-JSON sealed `legal-corpus-candidate-graph/v1` snapshot |
| `nodes.parquet` | Readable node projections plus each complete canonical node record |
| `edges.parquet` | Readable endpoint/relation/ordinal projections plus each complete canonical edge record |
| `manifest.json` | Sealed `legal-corpus-graph-bundle/v1` manifest binding all three files by SHA256, size and row count |

The manifest records `snapshot_cid`, `node_count`, `edge_count` and
`format_profile=candidate-graph-parquet-with-canonical-records/v1`. Its own
external SHA256 is supplied by the caller and is not a self-included field.
The manifest and snapshot retain `view=candidate`, `admitted=false`,
`formalized=false` and `source_semantics_verified=false`; the bundle also
records `external_references_verified=false`.

V1 requires every edge endpoint in the same snapshot. External imports are
unsupported. It validates the current node/relation profile, ordered role
positions, duplicate records and mutually exclusive interpretation boundaries.
Repeated role arguments remain distinct through their explicit ordinals.
It does not infer scope, merge equivalent terms, complete missing graph
relationships or substitute omitted records. Unsupported or malformed inputs
fail rather than being skipped.
Source-only snapshots are permitted. This phase does not project the varying
cached `typed-deontic-rule/v1` payloads into a unified typed rule/definition
schema or automatically promote them into semantic assertion nodes.

The common record envelope currently bounds canonical snapshots to 1 MiB,
25,000 JSON nodes and depth20. Graph limits are 4,096 nodes and8,192 edges;
the aggregate record bound may be reached earlier. Partitioning larger corpora
requires a separately specified profile and explicit dependency accounting.
Parquet exchange requires the optional `pyarrow` dependency. Missing dependencies
produce an explicit failure; no network installation or model loading occurs.

## Python API

```python
from ipfs_datasets_py.logic.autoformal.corpus_graph_exchange import (
    load_graph_bundle,
    write_graph_bundle,
)

manifest = write_graph_bundle(sealed_snapshot, output_directory)
loaded = load_graph_bundle(
    output_directory,
    expected_manifest_sha256=independently_expected_manifest_sha256,
)
assert loaded["snapshot"]["record_cid"] == sealed_snapshot["record_cid"]
```

The writer requires a new output directory and refuses overwrite. Keep incomplete
failed attempts distinct from a successfully validated bundle. The loader checks
the exact manifest, payload files, projections, row counts and reconstructed
snapshot; it returns `{"manifest": ..., "snapshot": ...}`. Neither API promotes
candidate assertions or verifies separately referenced semantic/source evidence.

## Command line

Use an installed package or an explicitly qualified package path. There are no
runtime `sys.path` modifications. These commands perform local file operations:

```bash
IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 python -m scripts.ops.legal_ir.validate_uscode_corpus_release export \
  --snapshot /absolute/path/snapshot.json \
  --snapshot-sha256 EXPECTED_SNAPSHOT_SHA256 \
  --output /absolute/path/new-bundle

IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 python -m scripts.ops.legal_ir.validate_uscode_corpus_release validate \
  --bundle /absolute/path/new-bundle \
  --manifest-sha256 EXPECTED_MANIFEST_SHA256
```

Direct script execution is also supported when public package imports are
qualified by the environment:

```bash
IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=/absolute/path/ipfs_datasets_py_checkout \
  python /absolute/path/ipfs_datasets_py_checkout/scripts/ops/legal_ir/validate_uscode_corpus_release.py \
  validate --bundle /absolute/path/new-bundle --manifest-sha256 EXPECTED_MANIFEST_SHA256
```

Replace uppercase placeholders with digests from the source-intake or release
custody boundary. Hashing arbitrary local input and passing that same hash proves
only its local identity; it does not establish source authenticity.

Export verifies an independently expected snapshot SHA256 before parsing and
graph validation. It reads a bounded regular file without following final or
parent-component symlinks, writes the new bundle, then performs a complete
readback with the computed manifest digest. Validation requires the expected
manifest SHA256 and performs the same bundle integrity checks. This snapshot
path profile requires directory descriptors and `O_NOFOLLOW` support.

Each invocation writes one JSON receipt to stdout. Successful validation/export
returns exit0 with `snapshot_cid`, `manifest_cid`, `manifest_sha256`, `node_count`
and `edge_count`. Errors return nonzero with `status=error`, an error type and
message. `--help` returns a JSON usage receipt. All receipts explicitly retain
false admission/formalization, source-authenticity, semantic and proof flags.
They qualify only the candidate graph v1 local-integrity profile.

## Extension boundary

This exchange does not replace the existing span cache, entity-cache inventory,
definition/norm composition, review recorder or Lake owners. It supplies an
additive reconstructable candidate graph view. A future coherent corpus release
must separately bind exact span/entity dataset revisions, reviewed semantic
artifacts, resolved definition dependencies, generated Lean modules, toolchain
and actual compilation/theorem receipts. No such release is claimed by v1.

## Read-only selected release-component replay

The separate `reviewed-norm-v2-local-replay/v1` profile is available through the existing coordinator's `validate_uscode_release_closure_v1(request_raw, expected_request_sha256=...)` API and CLI:

```bash
python -m scripts.ops.legal_ir.validate_uscode_corpus_release validate-closure \
  --request /absolute/path/closure.request --request-sha256 EXPECTED_REQUEST_SHA256
```

Requests use the existing `legal_corpus_definition_use_lake_v2.encode_parent_replay_value_v1` / `decode_parent_replay_value_v1` bounded plain-value-and-bytes codec. The request is at most 8 MiB, with at most 64 exact byte-bound artifacts of at most 1,000,000 bytes each. Supply independently retained request and complete component pins, all law/span/entity revision declarations, exact unit/artifact populations and complete original replay inputs. Reuse the existing owners; do not create an importer or replace an unsupported profile with another version.

Validation replays current reviewed norm V2 admission, its graph and dependency closure, Lean preservation preparation, HF packaging and strict source/span/entity join V3. The selected package identity and all five metadata bodies must agree. A Hub commit is not the producer source revision. Local byte equality authenticates neither remote acquisition nor legal meaning. Existing `export`, `validate` and general-help contracts remain unchanged; `validate-closure --help` returns its separate usage receipt.

The existing HF producer supplies the compatible metadata directly:

```python
from ipfs_datasets_py.processors.legal_data.uscode_hf_release import build_uscode_hf_release
candidate = build_uscode_hf_release(
    family_rows, legacy_files=legacy_files, dry_run=True,
    source_revision=producer_source_commit,
    metadata_profile="hf-default-parquet-envelope/v1",
)
```

This explicit profile measures actual local Parquet schema, rows and Arrow bytes. Its manifest, release metadata and configuration declaration match the standard single-alias infos and exact card frontmatter before existing descriptor/root sealing. Preserve logical `publicus-ir-graphrag/v2` and wire alias `publicus-ir-graphrag-v2`. Legacy/recovery files remain retained but their streaming configurations are unadvertised in this profile. Omitting the option keeps the original default bytes. Do not substitute compressed artifact bytes for Arrow bytes or a producer source commit for a Hub commit.

A successful JSON receipt means the supplied local replay completed; `closure_complete` and `release_ready` remain false. The packaging compatibility blocker is removed only after genuine package validation and matching selected-intake profile. Independent source correspondence, original admitted-native parent custody and immutable remote Hub readback remain blockers. The fictional positive fixture has no original native receipt/packet; that optional positive path remains unqualified. Metadata-only intake does not itself measure physical Arrow bytes, authenticate remote acquisition or admit meaning.

The four source/test changes have 103 private owning controls (producer58 and closure45), 33 actual software CLI children, 208 unchanged observed canonical dependencies, and an independent original-vs-new default comparison of all23 artifact bytes. Canonical pytest and actual Native counts remain zero. [Qualification and exact source scope](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-programme-review-20261022-05/coherent-release-closure-v01/producer-wire-profile-v01/private-wire-profile-qualification-summary-v01.json); [Source installation](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-programme-review-20261022-05/coherent-release-closure-v01/producer-wire-profile-v01/source-adoption-actual-v02.json). Earlier45-case and canonical-help observations retain their separate provenance.

## Reviewed physical law/span/entity successor

Select the closed v2 request explicitly; omitting `--profile` retains v1:

```bash
python -m scripts.ops.legal_ir.validate_uscode_corpus_release validate-closure \
  --profile reviewed-norm-v2-physical-three-cache-replay/v1 \
  --request /absolute/path/physical-closure.request --request-sha256 EXPECTED_REQUEST_SHA256
```

The existing coordinator API is `validate_uscode_release_closure_v2(request_raw, expected_request_sha256=...)`. Use request schema `legal-uscode-release-closure-request/v2` and the profile above. The existing8MiB request/64-artifact/1,000,000-byte artifact bounds remain. Add `physical_inputs` with exact absolute `law_path`/`entity_path`, component roles `reviewed_crosswalk`/`entity_parquet`, and the independently expected `reviewed_crosswalk` pin. Files must equal the exact supplied artifacts and remain the same byte/stat generation throughout replay.

The canonical crosswalk uses `legal-reviewed-physical-source-crosswalk/v1` and `identity-text-complete-reviewed-graph/v1`. It declares all three revision namespaces, selected package-bound legacy law file/rows and coordinate report, complete entity file/projection, ordered reviewed unit selections, every physical paired row and every physical entity row. Each unit's existing reviewed declaration must reference the exact crosswalk bytes/version as a dependency before review. Supply its original evidence body and current dependency observation; its own bytes are not independent process evidence.

The law text is captured by the existing raw-row owner, before cleaning or fallback. Identity extraction/normalization is the supported profile; a different extraction needs an explicit compatible owner rather than guessed offsets. Reviewed source versions, full occurrences, document revisions and Unicode coordinates remain distinct from Hub commits and producer source revisions. Sentence rows may cover one reviewed unit together; uncovered nonwhitespace clauses refuse. Entity rows bind explicit stable semantic selectors, then resolve unambiguously to all actual reviewed graph records/companions. The projection exhausts both node and edge populations. Matching labels, legal IDs or legacy admission booleans do not establish that binding.

Successful v2 replay sets `local_source_cache_entity_bindings_verified` and `independent_reviewed_crosswalk_verified` for the complete declared selected component. It removes only the local crosswalk blocker. Original-native custody, optional retained-native positive evidence and immutable remote Hub readback remain separate; release/proof/corpus flags stay false. This profile measures selected physical rows, not whole corpus coverage.

The114-case private qualification covers wholeCLI65 plus49 affected reviewed-admission cases, with63 unrelated helperV1 cases deselected. Two separately saved normalcanonical invocations also replayed the full fictional3unit/4span/39entity/18node/21edge component. These are no statutory/model/native results. [Qualification](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-programme-review-20261022-05/coherent-release-closure-v01/reviewed-physical-crosswalk-v01/private-physical-crosswalk-qualification-summary-v02.json); [canonical observations](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-programme-review-20261022-05/coherent-release-closure-v01/reviewed-physical-crosswalk-v01/canonical-readonly-CLI-v01/observation.json). The earlier v1/wire qualifications above retain their original generations.

The finite current V5 recovery producer/SDK pair `7ce92270` / `860d25af` has a separate selected software qualification: 45 distinct cases in 13 whole functions across API 15/4, watcher 9/3 and retained 21/6 originals, each with its own closed custody and durable 16 MiB release. This retains the captured 217-source epoch and adds no graph, Native-parent, statutory, model, training, Lean or corpus-release qualification to any graph or corpus replay. Live OLD recovery/watcher `1508` / `27049` and configuration `0b7c` remain unchanged. The later private DATA36 original remains failed at 35 passes/one fixture failure; its reviewed fixture-only correction has no qualified rerun. The Main `7d3` → `a4a4` test-only postclose transition is authenticated separately, while corrected DATA53 remains private and unrun; neither transfers the original 45-case qualification. [Selected recovery software evidence](../../../../../docs/autoformalization/evidence/legal-ir-current-v5-supervisor-source4-selected-evidence-20261115.json). The accompanying [portable ZIP](../../../../../docs/autoformalization/evidence/legal-ir-current-v5-supervisor-source4-selected-evidence-20261115.zip) transports those records and separately labeled UNRUN53 preparations; it grants no new qualification and does not recreate original inode identities.

## Full-release CLI selects strict wire metadata — 2026-11-15

The existing `scripts/ops/legal_data/build_uscode_full_hf_release.py` now
selects the existing `hf-default-parquet-envelope/v1` packaging profile by
default. Staged release metadata lists exact files and records measured
Parquet schema, row counts and Arrow bytes. Unselected files in the staging
directory remain untouched and cannot enter the manifest through a broad
glob. `--legacy-metadata-profile` explicitly retains the old CLI behavior;
the underlying producer API keeps its existing default.

The old CLI reproduced a strict-intake failure after successful real local
staging. The corrected default and explicit legacy route pass both owning
tests, using real tiny Parquet files and the existing staging/intake owners.
Only upstream family generation is modeled. All229 source pins stayed exact;
the original156-second run closed Source, Native and process custody and
durably released its own32MiB reservation. This is local packaging evidence,
with no Hub upload, model execution, statutory review or corpus admission.
Public law/span/entity compatibility findings remain separate from this fix.

[Closed two-case qualification](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-mixed-renderer-preservation-20261111-v01/release-v3-candidate-v02/current-main-qualification-20261114-v01/HF_full_release_cli_current2-small-v01/cohort-closeout.json).

## Current V3 three-cache integration and typed JSON correction — 2026-11-14

The integration checkout now extends the existing release coordinator and CLI
with the explicit V3 law/span/entity path. Complete admission and graph
artifacts use the existing norm correspondence JSON profile, retaining the
1,000,000-byte artifact and 8 MiB request ceilings and all downstream semantic
and independent-pin validation. Generic graph records and V1/V2 keep their
existing decoder limits. The shared review fixture now inventories one exact
artifact per identity while preserving every legal unit and cross-reference;
conflicting bytes under one identity refuse before manifest replacement.

A fresh canonical-source run passed **56 cases in 13 functions**: 54 release
cases and two shared-fixture controls. It covers a complete three-unit
fictional physical replay, damaged legal JSON, complete 83-file packet
transport, selected V1/V2 behavior and direct/module CLI paths. Source, native
resource, process, genuine wait and storage custody closed; this successful
run released only its own 32 MiB promise. The earlier missing-API, temporary
factory, duplicate-reference and generic-depth failures remain preserved.
A larger legacy batch hit its original 120-second deadline and grants no
whole-batch credit. Use the retained smaller cohorts and the existing
`--owned-ordinary-temp-factory` option for remaining checks.

At that run’s cutoff, the release owning file declared 152 cases; **98 remained
unqualified on its captured source**. The prior 35-case transport result overlaps this run
and must not be added to it. No actual Lean build, original Native-parent
authentication, immutable Hub readback, statutory review, model fitting or
corpus release is established. V3 remains an explicit local replay path.
[Closed qualification](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-mixed-renderer-preservation-20261111-v01/release-v3-candidate-v02/current-main-qualification-20261114-v01/current-canonical-release-v3-physical56-qualified-and-closed.json).

## Shared law-row replay and release regression checks — 2026-11-15

The existing physical fixture represents two source rows carrying three legal
units. It retains complete original bytes, exact character and UTF-8 offsets,
all span overlaps and one graph source-version node per identity. Signing binds
the original shared row before admission; source/IR artifact identities stay
distinct for each unit. The prior three-row default remains available.

The shared-row run passed six checks: three new cases, the retained three-row
positive and two shared-artifact controls. The five invalid-path cases also
passed after their owning test gained exact-leaf cleanup following its original
CLI assertions. Original and working snapshots plus ordinary observation
evidence remain; the C19 plugin, SDK and CLI were not changed for this fix.
Both runs closed all original custody and released their own 32 MiB promises.
The old symlink teardown error and earlier timed-out runs remain preserved.

All 98 cases in the previously unqualified regression selection now have
passing results across 19 closed originals. The latest nine sequential runs
cover the final 46. Independent raw-JUnit accounting joins those 98 with the
earlier 54 release cases and three new shared-row cases: all 155 declared
release case IDs and 39 functions are covered. Helper cases and overlapping
runs are not added twice. Every scope retains its exact source epoch; this is
not one unified current-source run or verification of statutory meaning.
Actual corpus Native-parent integration, immutable Hub readback, real legal
review and a complete statutory Lean corpus remain open.

[Shared-row closeout](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-mixed-renderer-preservation-20261111-v01/release-v3-candidate-v02/current-main-qualification-20261114-v01/shared_lawrow6-shared-v01/cohort-closeout.json). [Physical5 closeout](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-mixed-renderer-preservation-20261111-v01/release-v3-candidate-v02/current-main-qualification-20261114-v01/legacy_CLI_paths5-physical-current5-green-v01/cohort-closeout.json). [Complete98 closeout](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-mixed-renderer-preservation-20261111-v01/release-v3-candidate-v02/current-main-qualification-20261114-v01/remaining-release98-complete-19closed-v01.json). [Independent155 accounting](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-mixed-renderer-preservation-20261111-v01/release-v3-candidate-v02/current-main-qualification-20261114-v01/independent-final-remaining98-and-release155-captured-epoch-coverage-audit-v01.json).

The existing V3 bridge's `validate_uscode_release_closure_v3(..., original_parent_handle=handle)` path now has an actual same-process, same-thread positive: genuine original 22410 consumed the authentic A capability and authenticated the original 83-file Native receipt through the existing D coordinator for the same signed physical component. The legacy 77-file loader refused the genuine V3 capability. Three Native commands, eight compiled modules, 15 empty-axiom observations and full original custody/output/storage closeout are retained. This is one fictional three-unit local engineering replay; D closure, release, statutory/legal, remote, source-kernel and training flags remain false with two blockers. The c970/493/7d3 ordinary 28-case version-forwarding qualification, fresh D1 v08, prior 58-case failure-close and 63-case observer scopes are separate; the earlier v06 D failure remains preserved. Root explicitly cleared the optional observer binding only after independent whole-caller/D review, restored baseline config ab496 and retained registries edaf and 3ec5. Monitoring grants no handle, cleanup, retry, signal, restart or completion authority and enrolls no next job. [Exact bridge evidence](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-mixed-renderer-preservation-20261111-v01/release-v3-candidate-v02/current-main-qualification-20261114-v01/original-parent-v3-bridge-progress-selected-evidence-v07-local-engineering-A-to-D-complete.json).
