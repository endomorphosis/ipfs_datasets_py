# Durable private autoencoder publication preparation

The local owner can now freeze a complete private resume package into its
artifact store and enqueue a Hugging Face publication intent for an explicitly
selected immutable version. After owner restart, the package can be restored
from that intent even when its original directory is unavailable. This closes
the storage handoff between the version registry and the existing offline
release builder. It does not upload a model or qualify a candidate.

Native training validation remains deferred at the user's request. The work
uses storage fixtures and previously captured checkpoint bytes, with no new
optimizer or bridge-evaluation run.

## Owner and package binding

The new [owner adapter](../../../ipfs_datasets_py/duckdb_control/autoencoder_publication.py)
provides `prepare_autoencoder_publication` and
`restore_autoencoder_publication`. Preparation requires a version ID and an
explicit repository ID. It fetches the immutable version and registered
variant, preserving language metadata; it never resolves a mutable branch head
to choose the version. Distinct variants and checkpoints retain distinct
identities. Registry schema and ordinary enqueue APIs are unchanged.

The owner stages every package file, including the outer manifest, before
enqueueing. A bounded canonical envelope binds the owner paths, exact version
and variant records, repository, required private visibility, audited parent,
evaluation descriptors, package closure and publication-plan identity. The
existing outbox's `plan_artifact` points to this envelope. The adapter compares
the observed inventory with the verified manifest, checks expected bytes while
staging, and reopens the complete package before freezing the enqueue payload.

Supplied evaluation JSON is bound by exact bytes and retained as
`supplied_not_revalidated`. Inclusion does not establish held-out performance,
semantic validity, native qualification or admission. The private package may
retain source-like parameter keys and sample memory. Required private
visibility is a constraint for later publication, not a verified remote fact.

## Recovery and exact reopening

A filesystem journal and exclusive local lock bind retries to the original
request, owner, version, variant and envelope. The envelope descriptor is
durable before `EnqueuePublication`. A lost response resolves that exact
operation before retrying. A previously committed operation returns its
historical receipt even if package files subsequently disappear; that response
does not assert current artifact availability.

The [release loader](../../../ipfs_datasets_py/huggingface/autoencoder_release.py)
reopens original package bytes using the expected outer manifest and owner
records. It validates the complete file closure, release identity, configuration,
evaluation hashes, reconstructed publication plan, private profile and existing
approval metadata. Legacy package bytes remain unchanged. Compact v2 packages
also retain exact full float64 checkpoint bytes, logical and metric identities,
all persisted state fields and revision. Sparse/delta checkpoints are not
publication candidates. Historical descriptive source hashes need not equal
today's source hashes and are not treated as runtime attestations.
Closure covers the release files; it does not materialize every external
historical artifact referenced inside version or variant metadata.

Restoration verifies the envelope against its CAS descriptor and actual owner
records, copies each file with expected size and SHA-256, verifies the entire
package, then fsyncs the files and directories before returning a release
handle. It neither claims nor acknowledges the upload event. Pending, leased
and acknowledged events can be inspected without changing their status.

Incomplete builds and restores are retained and rejected on retry; the adapter
does not silently overwrite them. Recovery after durable closure is supported;
automatic repair of every earlier partial-build point is not. A manifest's
presence alone is not a completion receipt. Cross-owner replay and substituted
request options are rejected.

## Cost, limits and next integration

Numeric training access remains local; neither Arrow buffers nor individual
weight reads traverse this publication interface. CAS writes, checkpoint
validation and package hashing occur outside the owner's short database
transactions. A release can be restored from its immutable CAS contents instead
of rebuilding against a newer head or requiring the original worker directory.

This adds repeated full checkpoint reads and temporary package/CAS/restore
space. It belongs at selected-version release boundaries, not in each training
step. The defaults cap checkpoint inputs at 256 MiB, package closure at 512 MiB,
files at 128 and supplied evaluations at 16 of at most 4 MiB each. Bounded
namespace traversal also rejects special files and aliases. Preflight requires
an additional 8 MiB within the requested package allowance for metadata.
These are local format limits, not global disk reservations or RSS limits; the
existing scheduler must budget simultaneous package, staging and restore space.

The next HF consumer must restore this exact envelope, enforce the existing
publication profile, verify the actual destination and private visibility,
obtain the required exact-plan approval, upload through the existing guarded
publisher, reconcile uncertain remote outcomes and acknowledge only a verified
remote receipt. No approval token, remote inventory or successful upload is
fabricated by preparation. Production DuckLake activation and the remote Quack
owner adapter remain separate work.

The [end-to-end plan](../plans/FEDERAL_LAW_END_TO_END_TRAINING_PLAN.md) retains
the source census, reviewed semantic profiles, split provenance, held-out
qualification and Lake evidence as independent gates. Faster storage does not
establish federal-law coverage. The Constitution remains unformalized;
`roundtrip_ok` is not set. Only `lake build <Lib>` can supply a Lean admit.

## Verification

The [focused owner capture](../../../workspace/test-logs/federal-corpus-audits/autoencoder-publication-20260925/publication-r3-receipt.json)
passes 26 [publication checks](../../../tests/unit/duckdb_control/test_autoencoder_publication.py)
in 7.02 seconds pytest / 7.801180 seconds wrapper. They cover explicit non-head versions, separate language variants,
exact legacy and compact restore after owner restart, four classes of CAS
corruption, evaluation substitution, budget preflight, retained incomplete
builds, lost replies and an actual SIGKILL after durable closure but before
enqueue. Four mutation tests reject package changes after verification,
substituted uncommitted plan identities, envelope changes after writing, and
envelope changes between CAS verification and parsing. The earlier focused
failure compared a restored persisted state to an unnormalized mutable fixture;
its oracle was corrected to load the original sealed checkpoint independently,
without relaxing production behavior.

The [loader fixtures](../../../tests/unit/huggingface/test_autoencoder_release_reopen.py)
check metadata, plans, checkpoint identity, exact file closure and bounded
traversal. Together with the existing builder checks, 51 pass; the builder's
golden package hashes remain unchanged. FIFO and symlink entries, excessive
empty directories, long paths and deep paths are rejected before file hashing.
The strong reopening path is also checked with `rglob` disabled. These are
storage results, not legal-IR timings or a learning claim.

The [historical-byte recovery capture](../../../workspace/test-logs/federal-corpus-audits/autoencoder-publication-20260925/historical-recovery/historical-recovery-r1-receipt.json)
passes all 18 checks with network syscalls denied. It imports the exact original
base/candidate version records and language variant into a fresh isolated owner,
packages the existing 1,664,643-byte compact candidate, renames the original
package, restarts the owner and restores the complete eight-file closure from
CAS. All 38 persisted components, revision and full checkpoint reserialization
match. One HF event remains pending, with zero runs or heads created. The repo
name is an explicit fixture placeholder, not an authorized upload destination.
All 7,740 canonical package sources and protected/historical files remained
unchanged. This existing candidate had zero accepted projection epochs; the
recovery exercise adds no learning evidence.

The [combined regression receipt](../../../workspace/test-logs/federal-corpus-audits/autoencoder-publication-20260925/combined-r1-receipt.json)
records **555 tests passed in 162.17 seconds pytest / 164.508304 seconds wrapper**,
across 15 files, including the legal semantic gates and five-case roundtrip
pilot. **The combined capture failed its source-provenance guard.** Four files
changed during execution: `logic/autoformal/__init__.py`,
`logic/autoformal/supervisor_queue.py`, `logic/autoformal/supervisor_todo.py`,
and `logic/deontic/utils/deontic_parser.py`. The publication owner and release
loader, all selected test files, and protected checkpoints/receipts stayed
unchanged. No source-stable aggregate qualification is claimed, and no repeated
validation or another edit-free window was requested.

The earlier historical recovery capture completed with unchanged sources; its
source manifest equals the combined run's starting manifest. Its evidence
therefore remains bound to that earlier revision. None of these fixture times
is a wall time per legal span or per bridge-on evaluation. No new speed figure,
held-out gain, publication, production activation or admission is asserted.
