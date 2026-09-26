# Selected campaign packages and offline restore

Implementation is complete, but the current tree is unqualified. All 150 focused
offline tests and the guarded archived-page package/restore probe passed on the
recorded source on 2026-09-26. Independent closeout then failed its two
current-tree checks after external edits; its other 41 checks passed. The
captured results, failed closeout and two earlier failed attempts remain
separate historical evidence. Recorded times are diagnostic operation
measurements, not a speed comparison or training result. No publication
occurred, and native training validation remains deferred.

The implementation extends the
[publication and restore plan](autoencoder_campaign_publication_plan.md). It
makes one selected generation page portable as evidence while preserving the
original job, plan and checkpoint bytes. It does not import an executable
campaign into a new owner.

## Entry points and immutable format

[`autoencoder_campaign_release.py`](../../../ipfs_datasets_py/huggingface/autoencoder_campaign_release.py)
provides three local APIs:

- `build_campaign_package(generation_artifact, plan_artifact, destination, *, variant_record, version_records, run_records, artifact_resolver, limits)` validates the typed closure and writes a fresh package.
- `verify_campaign_package(root, *, expected_manifest_sha256, limits)` independently reopens that exact package through package-local blob descriptors.
- `restore_campaign_package(root, destination, *, expected_manifest_sha256, limits)` copies into a fresh destination and reopens it with the same expected manifest digest.

`limits` defaults to `CampaignPackageLimits()`. A matching digest binds content;
it does not authenticate the party supplying that digest.

The canonical `campaign-package.json` uses
`autoencoder-selected-campaign-package-v1` and the scope
`selected_campaign_page`. Its closed fields bind the original generation and
plan descriptors, captured variant/version/run records, derived typed artifact
roles, coverage, limits and qualification flags. Original artifacts occupy
`blobs/<sha256[:2]>/<sha256>` once per distinct digest. The package identity is
`sha256:<manifest digest>`; the manifest does not contain its own identity.

The format permits at most 4 MiB of control JSON, 4,096 blobs, 256 MiB per blob
and 512 MiB of unique payload bytes. The control file is additional to the
payload budget. Namespace caps separately cover 257 directories, 4,354 entries,
three relative path components and 128 UTF-8 bytes per relative path. Empty
directories count. Each existing codec retains its stricter limits; caller
limits can only tighten the package ceilings. Overflow rejects the operation
without truncating a page or repacking batches.

All three APIs return an evidence report with the local package path, manifest
descriptor and package identity, unique blob/payload/package byte counts,
coverage, limits and explicit qualification. No success report is returned
until the final validation boundaries pass.

## Typed dependency reconstruction

The new
[`inspect_campaign_inputs`](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_campaign_package_inputs.py)
walks generation, recipe, template and generated-job bindings rather than
trusting a flat list of files. It reconstructs the frozen source census and all
input dispositions, ordered training batches and fixed validation selection,
canonical lowest-entry-CID aliases, recipe/job identities and sealed plan
bindings. A later page includes its original template even when that template
uses source files absent from the selected generated jobs.

The
[`detached job adapter`](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_campaign_detached_inputs.py)
reads original v8 bytes without replacing their historical absolute paths.
Only the bare-descriptor resolver provides file locations. Existing inventory,
partition, receipt-set, projection and corpus-manifest codecs validate both
training and validation roles before selected source or receipt reads. Selected
source bytes, leaf vectors, ordered samples and dataset/split identities remain
bound to the original job. Unselected source records inside a shared receipt
leaf do not expand read authority.

The adapter preserves each historical `expected_source_sha256` declaration. It
does not attest that those historical producer files match the current worker.
`execution_source_manifest_verified` remains false. The current canonical logic
tree pin and bounded validator drift checks still apply. A whole-package source
claim requires the separate guarded capture, not this narrower runtime check.

The dependency inventory includes original template and generated jobs, all
three campaign roots, corpus manifests and projections, selected full receipt
leaves and sources, optional target and Arrow feature-weight bytes, and the
registered base-version ancestry. Version records must remain in one variant,
match their content identities and include every parent before its child.
Unrelated versions and cycles are rejected; ancestry is bounded at 256 records.

Physical sparse checkpoint inventory uses the existing manifest/patch framing
validator. Sparse roots also bind their parent artifact and base-version ID to
the registered parent record. A declared materialized checkpoint is not invented
as an existing blob. Full compact checkpoint ancestors are checked through the
existing container/manifest framing without constructing weights; actual v8
bases retain the existing JSON/sparse input contract. Checkpoint semantic replay
is deferred. Targets and Arrow artifacts retain exact bytes while runtime
membership and compatibility remain unverified.

The larger shared roots remain coverage metadata. A selected-page package does
not include every upstream release shard, producer leaf or unselected source
payload mentioned in them. Full source-campaign transport requires a separate
bounded collection contract. This implementation neither expands the English
`us_code` frontend nor formalizes the Constitution.

## Owner capture and file safety

[`build_registered_campaign_package`](../../../ipfs_datasets_py/duckdb_control/autoencoder_campaign_publication.py)
captures the current owner's immutable bindings and supplies an owner-restricted
CAS resolver. Generated runs must be fresh queued records with zero attempts
and fences, and no lease or result. The original template may already be running,
failed or completed; its exact captured row remains historical metadata. Its
candidate/result references are not exported as completion history.

The wrapper rechecks original owner records and all resolved current artifact
bytes before returning. It does not register versions or runs, claim leases,
move heads, enqueue an outbox intent or invoke publication. Successful transport
alone does not authorize any of those actions.

Initial package enumeration bounds names and `stat` metadata without reading
selected payloads. The typed walk authorizes the selected closure before generic
hash/copy passes. Missing or extra files and directories, aliases, special files,
conflicting descriptor sizes and unreferenced blobs fail. Transport hashing and copy opens reject
symlink components; their final regular-file opens are nonblocking. Existing
typed codecs retain their own bounded current-byte checks. Streaming copies
use exclusive creation, declared byte limits, hashes and before/after descriptor
and pathname checks. Files and directories are fsynced, and the control manifest
is written after blob copying.

Restore first validates the complete source package and rejects a destination
inside it. It preserves every original artifact and manifest byte and reopens
the copy through its expected digest. Restored locators are package-local;
historical absolute paths remain data and are never opened for restoration.

Failed or interrupted destinations are retained and cannot be overwritten or
adopted by a retry. A failure after manifest publication, or during the owner
wrapper's final record comparison, can leave a structurally valid historical
package. The failed operation returns no success or current owner authority.
Checks at operation boundaries do not make arbitrary concurrent filesystem
changes atomic.

## Captured tests and restore passed; current-tree closeout failed

Focused new tests cover detached role authorization, exact typed generation and
ancestry bindings, coherent alias/descriptor forgeries, later pages with
template-only dependencies, optional stored artifacts, and unchanged owner
state. Transport tests cover repeated deterministic builds, content
deduplication, deletion of original source paths before reopen/restore, exact
byte/count limits, unsafe or extraneous namespaces, malformed and coherently
resealed control files, interrupted copies and source/destination mutations.
They forbid native model/deserializer/replay and network operations as
appropriate to their fixture phase.

The first guarded run executed all 150 focused cases: 149 passed and one failed,
with no errors or skips. Its
[test receipt](../../../workspace/test-logs/federal-corpus-audits/campaign-package-20260926/capture-r1/tests/tests-receipt.json)
records 196.972950 seconds for the test child and passing source, dependency,
harness, input and protected-artifact guards. The failing compact-ancestor case
correctly detected a payload checksum mismatch, but its
`CheckpointCorruptionError` escaped the public package-input error boundary.
The correction catches the checkpoint domain error at compact framing
validation and converts it to `CampaignPackageInputError`; arbitrary runtime
interruptions remain distinct.

The [failed aggregate receipt](../../../workspace/test-logs/federal-corpus-audits/campaign-package-20260926/capture-r1/audit-receipt.json),
original source snapshot and retained 900 MB resource claim remain historical
failure evidence. The archived-page probe did not run, and the failed parent
receipt does not establish final whole-capture guards or resource release.

The [second attempt](../../../workspace/test-logs/federal-corpus-audits/campaign-package-tests-retry-20260926/capture-r1/audit-receipt.json)
aborted after 10.827527 seconds when the whole-producer guard detected external
canonical-source changes: edits to four logic files and a new `lake_probe.py`.
No test child started and no collection or second pytest result occurred. Its
50 MB claim and failed receipt remain retained; neither failed attempt is
reclassified by subsequent work.

The [final test receipt](../../../workspace/test-logs/federal-corpus-audits/campaign-package-tests-final-20260926/capture-r1/tests/tests-receipt.json)
records all 150 cases passing, with zero errors or skips, in 194.233477 seconds.
The [test audit](../../../workspace/test-logs/federal-corpus-audits/campaign-package-tests-final-20260926/capture-r1/audit-receipt.json)
took 279.225447 seconds including its 61-second source-stability preflight.
All 7,767 producer sources, 920 dependencies, frozen harness inputs and protected
artifacts passed their guards. The separate 50 MB reservation and 30 MB fixture
charge were [released](../../../workspace/test-logs/federal-corpus-audits/campaign-package-tests-final-20260926/capture-r1/resource-release.json),
with no retained successful test fixtures. These results qualify the focused
offline test contract separately from the archived-page probe.

The [archived-page probe](../../../workspace/test-logs/federal-corpus-audits/campaign-package-restore-final-20260926/capture-r1/probe/package-report.json)
passed all 16 checks. It preserved the exact archived vectors, source bytes,
configuration, role order and all 62,839 input dispositions. Its selected page
contains 40 training and seven fixed validation records in three jobs with
16/16/8 training records and seven validation records each: 47 unique records
and 61 occurrences. It used the synthetic three-byte empty JSON checkpoint,
without model construction, embedding inference, checkpoint replay or training.

The package has 66 unique blobs containing 95,455,368 payload bytes, plus a
13,114-byte control manifest, for 95,468,482 total bytes. Its identity is
`sha256:cd46522bd0b65b85e8065c0b8f86f4e73c32b5317dceeb9f2f0ecfd5bb32872b`.
Restore preserved every manifest and blob byte with the original owner paths
unavailable and without constructing a registry. All eight owner tables,
queued jobs and checkpoint head were unchanged by packaging.

| Probe phase | Wall seconds |
|---|---:|
| Fixture setup | 0.379236 |
| Prepare three-job page | 14.616086 |
| Registered package build, including verification | 68.802200 |
| Retire verified fresh scratch CAS duplicates | 1.685789 |
| Restore, including source and destination verification | 68.131718 |

These single-operation timings include all in-function validation and copying;
extra harness comparisons and guards are outside the phase timers. The
[probe audit](../../../workspace/test-logs/federal-corpus-audits/campaign-package-restore-final-20260926/capture-r1/audit-receipt.json)
took 242.045236 seconds including its 61-second source-stability preflight.
Lifetime process high-water RSS was 739,557,376 bytes across setup, preparation,
packaging and restore. This is neither PSS nor a per-phase memory measurement.
There is no cold-cache, memory-improvement or legal-IR speed claim.

The probe used a 250 MB reservation, replacing the earlier 305 MB design.
After closing its fixture owner and successfully verifying package bytes and
parity, the harness retired exactly its 66 fresh CAS duplicates. It retained
original descriptors and parity receipts, the private database and all eight
table snapshots, and complete package and restored bytes. This is solely
harness lifecycle management; public APIs do not retire CAS files, and the
owner wrapper remains read-only with respect to the registry and CAS.
The [probe reservation and lease were released](../../../workspace/test-logs/federal-corpus-audits/campaign-package-restore-final-20260926/capture-r1/resource-release.json)
with 202,211,150 owned and charged bytes. All 17 prior retained claims stayed
unchanged, including both failed package attempts. Full 7,767-source and
920-dependency guards matched the successful test capture.

The [independent closeout](evidence/autoencoder_control_plane_plan/campaign-package-closeout-20260926-r1.json)
ran once and failed: 41 of 43 checks passed. All eight recorded source and
dependency snapshots agreed, and the independent artifact, exact restore,
owner-state and resource checks passed. The two failing checks were
`eight_full_source_and_dependency_snapshots_equal_current` and
`whole_source_dependency_harness_current_at_close`. External edits after the
captures changed `logic/autoformal/supervisor_loop.py` and the dependency
`scripts/ops/legal_ir/run_autoformal_supervisor.py`, and added
`huggingface/autoformal_span_cache.py` and `logic/autoformal/span_cache.py` under
the package tree. The captured source therefore no longer matched the current
source/dependency inventory.

The failed 294,716-byte closeout receipt remains unchanged, with SHA-256
`d7534b4e6da8dd8d56ae4aed7f97ccd15c3ef2bec8ef99ba364e64e8f8e0bde0`.
It does not qualify the current tree or turn the two passing historical captures
into a combined qualification. No rerun was performed, and the checks were not
relaxed. The prior
[preparation speed comparison](autoencoder_campaign_root_reuse.md) does not
measure this package path, which adds independent validation and copying.

No package claim implies native training quality, parallel throughput, source
authentication, global holdout verification, complete federal-law coverage,
publication or formalization. `checkpoint_semantic_replay_verified`,
`execution_source_manifest_verified`, `completion_history_exported`,
`full_source_payload_closure`, `execution_authorized` and `admitted` remain
false. Only `lake build <Lib>` counts as a Lean admit. The Constitution remains
unformalized.
