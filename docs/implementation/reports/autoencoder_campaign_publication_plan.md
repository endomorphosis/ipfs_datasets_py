# Offline campaign publication and restore plan

Implementation complete, 2026-09-26; the current tree is unqualified. The new
selected-page builder, detached verifier, owner capture and restore path passed
all 150 focused tests plus the guarded archived-page probe on the recorded
source. Independent closeout failed its two current-tree checks after external
edits; its other 41 checks passed. The failed closeout, first failed test capture
and second source-guard abort remain historical evidence. Archived restore
preserved exact bytes; no publication intent or upload occurred. See the
[implementation report](autoencoder_campaign_packages.md) for the current
boundary and validation status. Restoration preserves evidence and bytes; it
does not create an executable training campaign.

The [batch-generation report](autoencoder_campaign_batches.md) establishes
deterministic jobs and restart behavior over archived source inputs. It does
not establish a complete publication closure. This proposal extends that work
using the [control-plane plan](../plans/AUTOENCODER_DUCKDB_DUCKLAKE_TRAINING_PLAN.md)
and [federal-law plan](../plans/FEDERAL_LAW_END_TO_END_TRAINING_PLAN.md).

## Existing interfaces and their limits

| Existing interface | Reuse | Boundary to preserve |
|---|---|---|
| `AutoencoderRegistry.artifact_path`, `verify_artifact`, `stage_artifact` | Bare `{sha256, bytes}` references and CAS paths `<artifact_root>/<sha[:2]>/<sha>` | A descriptor or registry row is not authority to train or a proof of source authenticity. |
| `build_private_resume_release`, `load_private_resume_release`, `verify_release_package` in [`huggingface/autoencoder_release.py`](../../../ipfs_datasets_py/huggingface/autoencoder_release.py) | Exact checkpoint bytes, deterministic manifests, safe paths and strong offline reopening | Existing private model packages support full legacy JSON and canonical full float64 compact checkpoints. Deltas and sparse manifests require explicit verified materialization and registration first. The bounded loader allows 128 files and 512 MiB; its namespace walker allows 256 entries. |
| `prepare_autoencoder_publication`, `restore_autoencoder_publication` in [`duckdb_control/autoencoder_publication.py`](../../../ipfs_datasets_py/duckdb_control/autoencoder_publication.py) | Owner-bound journals, streamed CAS copies, exclusive restore destinations and fsync | Preparation enqueues an outbox intent; restore reads that same owner's envelope. Neither is a portable campaign importer. The proposed builder must not call preparation merely to obtain local files. |
| `registered_corpus_job_inputs`, `registered_checkpoint_inputs` | Registered variant/job/source bindings and bounded checkpoint dependency inventory | Corpus verification applies to the exact job. Checkpoint inventory does not reconstruct weights or establish semantic replay. |
| `inventory_checkpoint`, `resolve_checkpoint` | Exact sparse parent/patch closure; separate optional state replay | Inventory explicitly reports no constructed weights or verified semantic replay. Replay recomputes patch transitions and final state; it is not model evaluation or legal formalization. |
| Campaign plan, inventory, partition, receipt-set and projection codecs | Ordered roles, exact roots, selected closure and immutable identities | Public loaders and normal worker/owner verification retain their existing checks. A package introduces no alternative source-selection pipeline. |
| `build_uscode_hf_release`, `stage_uscode_hf_release`, `validate_uscode_hf_release` | Existing corpus/Parquet descriptors and dataset layout conventions | These are distinct from campaign jobs. Their retrieval admission terminology must not be presented as Lean admission. Remote upload is not supported by the local staging API. |

The model release format should remain unchanged. Its safe streaming and
canonical-identity conventions are useful, but increasing its limits or adding
campaign fields would change an already qualified contract. A new campaign
schema should have its own limits and tests. No DuckDB schema change, live
Quack connection or DuckLake write is needed for the first implementation.

## Two distinct coverage scopes

`selected_campaign_page` means that every dependency required to inspect the
declared generation page and its jobs is present. Include the original template
job as well as generated jobs: a later page can depend on template source files
that are absent from its own selected records. Include full selected receipt
leaves, but authorize and validate source bytes only for the exact job records.
Unrelated records in the same leaf do not expand the job's source-read authority.

The shared inventory and receipt-set metadata describe a larger denominator.
They do not contain every source payload. A selected-page package must report
which upstream payload families are outside its scope; it must not claim that
all references mentioned in those metadata files were physically packaged.
Aliases, embedding failures, unattempted inputs, protected splits and deferred
successful inputs remain in the original coverage accounting.

`sealed_source_campaign` is a future, stronger scope. It also requires the
original release manifest, all declared corpus shards and other release
artifacts, every producer leaf, and the exact source payload closure needed by
those receipts. It must reverify those current bytes, rather than infer their
availability from the inventory's recorded build-time checks. The full source
closure can exceed a selected-page budget and should use bounded package parts
and a versioned collection manifest. It still does not imply complete federal
law coverage, official-source authentication, usable embeddings for every input
or semantic formalization.

V8 currently requires the qualified English `us_code` frontend. Additional
languages and a Constitution frontend require their own source and validation
contracts; changing a package label cannot provide that support.

## Implemented first format and dependency closure

The new module
[`autoencoder_campaign_release.py`](../../../ipfs_datasets_py/huggingface/autoencoder_campaign_release.py)
provides `build_campaign_package`, `verify_campaign_package` and
`restore_campaign_package`. The separate
[`build_registered_campaign_package`](../../../ipfs_datasets_py/duckdb_control/autoencoder_campaign_publication.py)
wrapper captures the selected owner records without writing registry tables or
enqueueing publication. The caller supplies selected generation/plan references
and, on reopen, the exact expected package-manifest digest. A supplied digest
binds content; it does not authenticate its issuer. Focused guarded tests and
the archived-page transport probe passed on captured source. The independent
closeout failed current-tree provenance, so those results do not qualify the
current tree.

Keep the original artifact bytes under package-relative
`blobs/<sha[:2]>/<sha>` paths. Use a closed canonical manifest whose fields bind
schema version, coverage scope, original generation/plan references, immutable
variant/version records, ordered job references, typed dependency references,
coverage, limits and qualification flags. Derive the package identity from that
manifest; do not put a self-referential digest inside its own hash input.

The typed traversal must include:

1. The generation artifact, sealed plan, every listed job specification and
   the recipe's original template job. Verify recipe, ordinal, job/run IDs and
   exact plan-to-job bindings rather than trusting a supplied flat file list.
2. The shared source inventory, source partitions and receipt-set root; every
   job's corpus manifest and produced-record projection; the exact selected
   original leaves and source files for both generated and template jobs.
3. Exact target snapshots and optional Arrow feature-weight artifacts. V8
   embedding vectors remain inline in the existing job and manifest bytes.
4. Registered base-version records and their complete checkpoint parent/patch
   closure. Parent versions must remain in the same variant. Deduplicate by
   digest and reject inconsistent sizes, cycles or unsupported schemas.

The first implementation should target queued jobs and their base checkpoints,
which matches the archived batch probe. Historical candidate/completion export
is a subsequent extension: it must bind `get_run_completion` history, worker
receipts, candidate versions, accepted patches and any compaction evidence.
Packaging declarations alone cannot recreate that history or establish exact
candidate replay. Running and failed attempts must never become queued or
completed through restoration.

The new format caps the package control manifest at 4 MiB, with 4,096 blobs,
256 MiB per blob and 512 MiB aggregate payload bytes. Retain stricter limits
from each underlying codec. Bound directory count, relative-path depth and
path bytes independently, including empty directories. The implemented
namespace caps are 257 directories, 4,354 entries including the control file,
three relative path components and 128 UTF-8 path bytes. Callers may tighten
these limits. These are new-package caps, not changes to existing model-release limits or promises about process
memory. A valid generation artifact may be much larger than 4 MiB; it is a
payload blob, not the package control manifest. Reject overflow before copying
the next artifact; never omit records or repack batch boundaries to fit.

Reserve space for package files, temporary files, optional CAS staging and the
restore copy separately. Use streaming hashes and copies. Content deduplication
reduces retained duplicates; it does not remove hash, serialization or copy
cost. The first builder need not CAS-stage the whole package or enqueue any
publication intent.

## Restore and portable paths

Existing jobs, campaign plans and daemon input snapshots bind absolute owner
paths. Preserve those bytes and identities unchanged. On restore, original
paths are historical data, never locations to open or write.

The package verifier should use a descriptor resolver restricted to the exact
package inventory. Load the existing metadata codecs through that resolver,
compare the original job's ordered samples, roles, roots and configuration,
and authorize both roles before selected source/leaf reads. The new
[`detached adapter`](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_campaign_detached_inputs.py)
uses original job bytes and descriptor-only resolution. It preserves historical
`expected_source_sha256` declarations while explicitly deferring current
execution-source compatibility. It enforces the current canonical workspace
tree pin and a bounded validator drift guard. The guarded qualification capture
must separately establish whole-package source stability.

Verify the complete bounded namespace and every file hash before copying into
a fresh, exclusive destination. Reject missing or extra files, unsafe relative
paths, symlinks and special files. Rehash source and destination at the defined
boundaries, fsync files/directories, then reopen the restored package using its
expected digest. A failed or interrupted destination is retained and cannot be silently
overwritten or adopted by a retry. Failure after manifest publication or during
the owner wrapper's final record recapture can leave a structurally valid
historical package; the failed operation returns no success or current owner
authority. Boundary checks do not make arbitrary concurrent filesystem changes
atomic.

The first restore constructs no model weights, runs no inference or optimizer,
and needs no network. It verifies sparse framing and dependency inventory;
`checkpoint_semantic_replay_verified` stays false. Exact state replay, if later
added, must be an explicitly bounded separate phase with its own result. Preserve
targets and Arrow bytes, but report their runtime membership and compatibility
as deferred until dedicated validators actually run. A template target bundle
must not be assumed to cover every newly generated sample.

Restoration writes package files only. It does not import DuckDB tables,
register runs, restore leases, invoke `CompleteRun`, move checkpoint heads,
acknowledge outbox events or authorize training. A future executable import
requires an explicit locator-rebinding recipe, new job/plan identities linked
to the original package digest, parent-before-child registration and ordinary
owner/worker validation. That is separate from exact artifact restoration.

## Sequence, tests and opportunity cost

The closed selected-page control format, typed closure walker, streamed builder
and independent reopen/restore path are now implemented. Existing generation, plan,
job and checkpoint codecs remain unchanged. The new tests use small injected
vectors and checkpoint fixtures and forbid model evaluation and training.
The first guarded run collected and executed all 150 cases, with 149 passes and
one failure. The test contract covers:

- Repeat packaging produces the same identity; shared blobs occur once.
- A package moved to a different directory verifies without touching original
  absolute paths and cannot be passed off as an executable restored job.
- Missing template-only inputs, sparse ancestors, selected sources, targets or
  Arrow weights fail; conflicting sizes, reordered roles and foreign variants
  fail even when their replacement bytes are individually well formed.
- Exact budget boundaries, unsafe paths, extra directories, copy-time mutation
  and interrupted destinations fail without expanding authority or scope.
- All registry runs, leases, checkpoint heads and outbox records remain
  unchanged. No model call, publication enqueue, credentials read or network
  request occurs.
- Selected-page coverage distinguishes omitted upstream payloads. A future
  full-source package rejects an omitted declared shard or producer leaf.

The failed compact-ancestor case detected corrupt checkpoint bytes but exposed
`CheckpointCorruptionError` instead of the public package-input error. Its
[test receipt](../../../workspace/test-logs/federal-corpus-audits/campaign-package-20260926/capture-r1/tests/tests-receipt.json)
records passing test-phase source, dependency and protected-artifact guards.
The [failed aggregate receipt](../../../workspace/test-logs/federal-corpus-audits/campaign-package-20260926/capture-r1/audit-receipt.json),
original source snapshot and retained 900 MB resource claim remain unchanged.
The archived-page probe did not run. The narrow domain-error correction was
submitted to a new guarded test capture; it does not reclassify the failed attempt.

The [second attempt](../../../workspace/test-logs/federal-corpus-audits/campaign-package-tests-retry-20260926/capture-r1/audit-receipt.json)
aborted after 10.827527 seconds because the whole-producer guard detected
external edits to four canonical logic files and a new `lake_probe.py`.
It started no test child and produced no second pytest result. Its separate
50 MB claim remains retained alongside the earlier failure evidence.

The [final test capture](../../../workspace/test-logs/federal-corpus-audits/campaign-package-tests-final-20260926/capture-r1/tests/tests-receipt.json)
passed all 150 cases, with no errors or skips, in 194.233477 seconds. Its
[audit](../../../workspace/test-logs/federal-corpus-audits/campaign-package-tests-final-20260926/capture-r1/audit-receipt.json)
passed all 7,767-source, 920-dependency and protected-artifact guards, and the
50 MB test reservation and 30 MB fixture charge were
[released](../../../workspace/test-logs/federal-corpus-audits/campaign-package-tests-final-20260926/capture-r1/resource-release.json).
The separately guarded archived-page probe also passed on that same captured
source. Subsequent independent closeout failed current-tree provenance.

The [archived probe](../../../workspace/test-logs/federal-corpus-audits/campaign-package-restore-final-20260926/capture-r1/probe/package-report.json)
passed all 16 checks over 47 unique records and three jobs. It produced 66
unique payload blobs containing 95,455,368 bytes, plus a 13,114-byte manifest,
and restored the complete 95,468,482-byte package unchanged with original owner
paths unavailable. All eight registry tables remained unchanged. Page
preparation took 14.616086 seconds, package build including verification
68.802200 seconds, and restore including both verification passes 68.131718
seconds. These are single-operation diagnostics, not a training or legal-IR
speed comparison. The [implementation report](autoencoder_campaign_packages.md)
records full phase boundaries, lifetime RSS and coverage limits.

The probe used a separate 250 MB reservation, replacing the 305 MB proposal.
After closing its fixture owner and successfully verifying the package build
and exact parity, the harness retired only its own 66 fresh CAS duplicates.
This is harness lifecycle management, not public API behavior: the owner wrapper
remains read-only with respect to registry and CAS. The probe retained original descriptors, exact parity receipts, the
private database and all eight table snapshots, and complete package and restore
copies. Earlier failed artifacts and claims remain untouched. This retention
design fits the 50 GB global limit without reducing selected scope or weakening
whole-producer guards. Its [audit](../../../workspace/test-logs/federal-corpus-audits/campaign-package-restore-final-20260926/capture-r1/audit-receipt.json)
passed the same 7,767-source/920-dependency guards as the test capture, and its
[reservation and lease were released](../../../workspace/test-logs/federal-corpus-audits/campaign-package-restore-final-20260926/capture-r1/resource-release.json)
with 202,211,150 owned and charged bytes. All 17 prior retained claims remained
unchanged.

The [independent closeout](evidence/autoencoder_control_plane_plan/campaign-package-closeout-20260926-r1.json)
failed with 41 of 43 checks passing. All eight recorded source/dependency
snapshots agreed; artifact, exact restore, owner-state and resource checks
passed. External edits after the captures changed the package's
`logic/autoformal/supervisor_loop.py` and dependency
`scripts/ops/legal_ir/run_autoformal_supervisor.py`, and added
`huggingface/autoformal_span_cache.py` and `logic/autoformal/span_cache.py`.
The two current-tree equality checks therefore failed. The failed receipt is
retained unchanged; no rerun or relaxed source criteria followed. The recorded
test and restore results remain historical evidence, without combined
qualification of the current tree.

Historical completion packaging, full-source collection packaging and a
reviewable remote publication plan follow after that contract is stable.

The separate [root-reuse capture](autoencoder_campaign_root_reuse.md) qualified
preparation of the same primed three-job page at a 66.324950-second control median
and 15.117741-second reuse median, with two observations per mode. That result
covers current-code preparation of 47 unique stored records. It is neither a
package transport measurement nor compiler-per-span or bridge-on evaluation
timing. The earlier [batch probe](autoencoder_campaign_batches.md) remains
separate historical evidence.

The first package verifier independently validates each job and adds hashing,
copying and reopening. It introduces no cross-job decoded-root cache. Measure
those phases and their memory costs before considering reuse in this different
verification context. Exact descriptors, both-role authorization, current-byte
checks and final drift detection remain mandatory; no persistent trust cache
is proposed.

Packaging and profiling serve different near-term needs. Packaging makes the
existing bounded work portable as verifiable evidence. Metadata amortization
can reduce its preparation cost, but does not supply missing targets, embeddings
or legal semantics. Both are useful before increasing campaign width or worker
count. Neither requires changing acceptance criteria, context limits,
temperature, parser trees or projection backend.

All package reports and cards must preserve the relevant false/deferred
qualification flags: no inferred source authority, global holdout verification,
full federal-corpus completeness, training admission, publication or
formalization. A source row, target, decompiled sentence, model score or package
receipt is not an admit. The Constitution remains unformalized; only
`lake build <Lib>` counts as a Lean admit.
