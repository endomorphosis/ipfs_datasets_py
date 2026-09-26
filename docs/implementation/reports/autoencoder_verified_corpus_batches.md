# Verified corpus batches and checkpoint input preparation

Implementation milestone, 2026-09-25, continuing
[sparse checkpoint persistence](autoencoder_sparse_checkpoint_persistence.md)
and the [federal-law training plan](../plans/FEDERAL_LAW_END_TO_END_TRAINING_PLAN.md).

## Input provenance

The opt-in v4 training job binds a bounded corpus manifest and its exact source
artifact closure. The existing DuckDB owner stages those artifacts, checks
their paths and bytes, and verifies the ordered job membership before dispatch.
Each worker independently performs the same source and membership checks before
loading weights. Completion binds the worker receipt to the owner's checked
summary. Workers still never open the control database.

The manifest records source kind, release, document, language, citation, exact
UTF-8 byte selectors and an explicit text normalization policy. Source-aware
record IDs bind these fields, the complete training row and supplied embedding
provenance. Dataset and split identities are separate content hashes. Changing
source bytes, record payloads, embeddings or split order changes the applicable
identity. Missing, extra, reordered or substituted job records fail validation.

`diagnostic` mode permits explicitly labeled mock embeddings and in-sample
evaluation. `corpus` mode requires supplied external embeddings and an immutable
model revision/artifact descriptor, and rejects the source/document/content
overlap it can detect within the batch. These are content-bound provenance
claims, not authentication of the publisher or evidence that a particular model
actually produced the supplied vector. Batch disjointness does not establish
independence from previous training runs or global held-out qualification.

The source-aware contract is a sidecar around the existing `SampleRecord` and
`legacy_us_code` training adapter. It does not replace that adapter. Corpus mode
supports English U.S. Code inputs; Constitution corpus training is rejected
until its source-aware frontend is qualified. Diagnostic metadata can identify
Constitution sources explicitly, but any diagnostic training still uses the
legacy U.S. Code adapter and is not a qualified Constitution frontend.
Complete source acquisition, legal identity reconciliation, ordered
embedding-chunk joins and enumeration of every compiler child remain unfinished.

Explicit v1/v2/v3 job encodings retain their canonical identities, and
schema-less JSON still means v2. Jobs without a corpus manifest report
`legacy_unverified`. The new `dataset_and_split_identity_verified` field is
specific to these inputs; other caller labels are not thereby verified.
Registry schemas, version records and head-promotion policies are unchanged.

The qualified batch limits are 4,096 records, 256 source artifacts, a 64 MiB
manifest, 256 MiB per source and 1 GiB of source bytes in total. Embeddings are
limited to 65,536 dimensions per row and one million dimensions per manifest.
Source validation reads one whole source at a time; these limits are not a
peak-memory guarantee. The conservative split check also rejects two splits
that share a source container, even when their byte selectors differ. It is
not yet a splitter for a whole release stored in one file.

To submit a verified batch, build `SourceSampleRecord` values with exact source
descriptors/selectors and the existing `SampleRecord` payloads, then call
`build_corpus_manifest()` with ordered training and validation record IDs.
`manifest.save(..., resolver=...)` verifies source bytes before exclusive output.
Stage the manifest and its exact sources with the registry, set
`schema_version="autoencoder-training-job-v4"`, `corpus_manifest_artifact`,
`corpus_source_artifacts`, and the manifest's dataset/split IDs in the job.
Shared targets, sparse capture, optional Arrow feature weights and the existing
owner dispatch API remain composable with this input contract. The
[native benchmark](../../../scripts/ops/legal_ir/benchmark_verified_corpus_training.py)
provides an executable diagnostic example.

## Avoiding repeated reconstruction

Job preparation previously reconstructed the whole checkpoint chain just to
obtain dependency descriptors. The new bounded inventory verifies artifact
hashes, sizes, schemas and reference structure without constructing weight
containers. It explicitly reports that semantic replay has not been performed.
The worker still reconstructs its base; the owner still independently replays
accepted updates and checks exact candidate bytes before version registration.

This removes a redundant preparation cost. It does not eliminate sparse-base
replay during training, full-state hashing, synchronous owner verification or
compaction. Arrow remains opt-in and limited to its previously qualified feature
table; this milestone makes no broader zero-copy or Arrow speed claim.

## Qualification

The [native receipt](evidence/autoencoder_control_plane_plan/verified-corpus-training-20260925.json)
passed. It compares the former input helper with inventory preparation on the
protected 25.9 MB checkpoint and a real accepted sparse child. Each number below
is the median of three alternating observations in one owner; OS cache warmth
was uncontrolled. Both paths returned identical dependency closures.

| Input checkpoint | Previous reconstruction | New inventory | Preparation time saved |
|---|---:|---:|---:|
| Full restart12 | 1.5548 s | 0.2901 s | 81.3% |
| Accepted one-patch child | 2.6903 s | 0.2433 s | 91.0% |

These savings apply only to input-descriptor preparation, not the entire job.
Inventory still parses legacy JSON into ordinary Python data and checks file
bytes. It does not validate nested model semantics or declared sparse result
bytes; those checks remain in worker/owner reconstruction.

The native training comparison used the same three gate sentences, shared
complete targets and sparse output for both modes. The only input-contract
difference was legacy v3 labels versus a verified v4 diagnostic manifest.
The rows below are medians of two alternating observations per mode.

| Input mode | Dispatch through completion | Input/job preparation | Combined job | Combined / span | Initial bridge-on evaluate | Evaluate / span |
|---|---:|---:|---:|---:|---:|---:|
| Legacy, labels unverified | 10.0218 s | 0.2562 s | 10.2781 s | 3.4260 s | 1.8556 s | 0.6185 s |
| Verified diagnostic manifest | 9.7049 s | 0.2839 s | 9.9888 s | 3.3296 s | 1.7368 s | 0.5789 s |

The small difference between these training rows is run variation, not evidence
that extra provenance checks accelerate evaluation. Worker source/manifest
verification itself took a median **0.002544 seconds** for three records, a
165-byte source and a 2,839-byte manifest. It also runs separately in the owner;
that owner's check was included in dispatch time but not separately profiled.
These small-input costs cannot be extrapolated to full release files.

Complete before/after evaluation dictionaries, logical state identities,
accepted epoch counts and materialized candidate bytes matched. Each candidate
reconstructed 25,895,897 bytes with SHA-256
`23fa2a50725fa5afe3f96da9ae84ea686df5fb49262aa1b6614321023a91799c`.
All six jobs accepted one epoch and retained **three legal-IR targets** before
and after training. All target statuses were `ready`.

The owner was closed and reopened before two verified jobs resumed in parallel
from the stored sparse child. They produced identical candidates. Dispatch
through durable completion took **16.3132 seconds** for six total training spans
(2.7189 seconds/span); including input/job preparation took 16.9045 seconds.
Their initial bridge-on evaluates took 1.7903 and 1.7050 seconds. Sparse-base
reconstruction still took 2.5287 and 2.4843 seconds in the workers. These are
concurrent independent candidate branches, not merged updates or a distributed
optimizer step. Runs, source bytes and the manifest survived another owner
reopen; branch heads stayed unchanged.

Measurement settings:

- Bridge order: `modal_frame_logic`, `deontic_norms`, `fol_tdfol`, `cec_dcec`,
  `external_prover_router`; provers false; bridge workers one.
- Metric disk cache 0, sample memory false. Training processes were fresh, but
  complete bundle targets were explicitly reused. This is **not cold target
  generation**. OS file-cache warmth was uncontrolled.
- Three identical train/validation gate rows per job, explicitly diagnostic
  and in-sample. Paired jobs used one training worker; resumed jobs used two.
- `python_sparse_batch`, CUDA disabled, BLAS/OpenMP threads one, temperature 0,
  one epoch, one update family, one line-search attempt, 180-second limit.

One-time target preparation was measured separately at **13.8513 seconds**,
including 11.3347 seconds of fresh target generation (3.7782 seconds/span).
Initial evaluation timings use the existing profile event
`before_holdout_evaluation`; despite that event name, this fixture is in-sample.
Target loading, preparation and initial registry staging are excluded from the
evaluation column. Input/job preparation includes inventory, job staging and run
creation. The full benchmark took 87.0719 seconds. Scratch retained 39,762,892
bytes before cleanup; this is not a peak-space measurement or quota mechanism.

Validation: **238 focused tests passed** after the final codec/integration
changes; **44 semantic and Constitution guard tests passed** separately.
Thirteen archived v2/v3 job specifications retained their exact serialized
contents and canonical hashes. The native receipt confirms unchanged package
sources and unchanged pinned checkpoint bytes. Scratch was removed. Corpus-mode
guards were tested with synthetic unit fixtures; no real-corpus held-out canary,
full Constitution evaluate, HF upload or production DuckLake activation ran.

## Remaining implementation order

1. Build an index over bounded manifests for one selected, checksummed U.S. Code
   release. Reconcile canonical legal IDs, recovery rows and source completeness;
   join embeddings to exact ordered source chunks. Add the Constitution frontend
   and enumerate all compiler children before enabling its corpus training mode.
2. Freeze splits across the whole campaign, including legal-document and release
   lineage. Prepare reusable target bundles for those manifests, retaining every
   unsupported, missing or failed target as an explicit disposition.
3. Qualify a reviewed held-out canary before increasing training concurrency.
   Add aggregate storage/RAM reservations and lease-safe nonblocking owner work.
   Measure Arrow benefits on weight families the optimizer actually updates.
4. Complete the existing Quack/DuckLake production adapter and restart/restore
   qualification. Package selected full materializations and source/IR/proof
   manifests through the existing Hugging Face path once destination and release
   selection are concrete. This milestone performs no upload or activation.

The opportunity cost is deliberate: source verification adds small bounded work
to each job and retains source artifacts, while preventing expensive training
against untraceable or mislabeled batches. Reusing complete targets and avoiding
redundant reconstruction address measured costs first. Broad numeric-store
rewrites and additional GPU backends remain unjustified by the measured small
projection cost.

No Constitution span is marked `roundtrip_ok`; the Constitution is not
formalized. No checkpoint, manifest, training result or database row is a Lean
admit. Only an actual `lake build <Lib>` can supply that evidence.
