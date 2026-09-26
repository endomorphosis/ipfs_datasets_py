# Lossless target bundles and selective hydration

Implementation milestone, 2026-09-25, continuing
[shared targets, sparse updates and Arrow weights](autoencoder_shared_targets_sparse_arrow.md)
and the [federal-law plan](../plans/FEDERAL_LAW_END_TO_END_TRAINING_PLAN.md).

Follow-up: [sparse checkpoint persistence and bounded compaction](autoencoder_sparse_checkpoint_persistence.md)
implements the next persistence slice. The target-bundle measurements below
retain their original full-checkpoint scope.

## Change and authority

`legal_ir_target_bundle.py` adds a single immutable artifact containing a shared
configuration/sample manifest and independently compressed complete targets.
Targets use the exact tagged JSON encoding of the existing snapshot codec.
Content hashes identify shards; identical complete payloads reuse their bytes.
Zlib compresses repeated strings within each payload. This is not a generic
structural-subtree store or cross-bundle manifest deduplication.

The owner stages the bundle through the existing content-addressed artifact
interface. Job descriptors and their version rules are unchanged. No additional
DuckDB connections, writable catalogs or database schema migrations are needed.
This does not activate production Quack routing, DuckLake materialization or
Hugging Face publication.

The loader hashes the entire bounded file and validates its manifest, then
decompresses and hydrates only requested targets. Metadata properties read the
manifest without repeatedly parsing the complete graphs. Selected shards must
pass compressed and expanded hashes, exact byte bounds, typed decoding, sample
identity, document text, status and configuration checks. Full target semantics
are validated on use; an unrequested record's inventory status is not a claim
that its semantic payload was decoded by this worker.

Full graph fields, timestamps, rejection information and rich grammar inputs
remain intact. JSON snapshots remain supported and remain the preparation
default. Workers detect the artifact format from its bytes, not its extension.
The bundle's versioned manifest identity differs from the legacy snapshot ID;
complete target identities are preserved.

## Streaming and bounds

`prepare_training_targets(..., artifact_format="bundle")` feeds targets directly
to the writer, with at most the configured worker count of pending generation
results. It bypasses both metric and multiview target caches, and checks source
provenance before generation and again before publishing. Exclusive publication
occurs only after the producer finishes successfully. Failures remove private
scratch files and release the preparation lock. The worker closes its read-only
artifact handle on success and failure.

Worker artifacts are capped at 256 MiB, manifests at 16 MiB and each expanded
target shard at 64 MiB. Expansion rejects truncated streams, trailing streams
and output beyond the declared size. Paths reject symlinks, parent traversal
and nonregular files; descriptor-bound checks reject changes during reads.
The writer temporarily holds a shard spool and the final artifact, so allow
roughly twice the bounded artifact size for its file storage, plus the ordinary
source, checkpoint, WAL, candidate and receipt reservations.

This bounds the rich-target backlog and expanded reads. It does not make every
part of corpus preparation constant-memory: source records, parsed samples,
embeddings, statuses, generation intervals and the manifest still scale with
sample count. Serialization constructs one encoded target before checking its
size; the producer's original object graph is not bounded by the serialized
limit. Workers still retain their selected train/validation union in memory.
Use bounded jobs and, for an entire corpus, an index of multiple bounded
bundles. That corpus index remains future work.

## Qualification

The [native comparison receipt](evidence/autoencoder_control_plane_plan/target-bundles-20260925.json)
passed. Complete-job median wall time fell from **10.2816 seconds with shared
JSON to 8.0392 seconds with shared bundles**, a 21.8% reduction. Relative to
fresh targets in the same comparison, complete-job wall time fell 46.3%.
These are two observations per mode on a small in-sample workload, not a
full-corpus or held-out speed/quality claim.

| Mode | Observations | Complete job | Per training span | Initial bridge-on evaluate | Evaluate / span | Target loading |
|---|---:|---:|---:|---:|---:|---:|
| Fresh targets | 2 | 14.9776 s median | 4.9925 s | 10.6501 s median | 3.5500 s | Targets generated during evaluation |
| Shared JSON | 2 | 10.2816 s median | 3.4272 s | 1.8163 s median | 0.6054 s | 3.3806 s median |
| Shared bundle | 2 | 8.0392 s median | 2.6797 s | 1.8340 s median | 0.6113 s | 1.3371 s median |
| Shared bundle + sparse capture/replay | 1 | 10.4069 s | 3.4690 s | 1.8267 s | 0.6089 s | 1.3073 s |

Each before/after evaluation contained three targets. Preparation and shared
worker inventories were exactly three `ready` entries, with no timeout
fallback. All seven jobs accepted one optimizer epoch and produced identical
complete candidate bytes. Complete before/after evaluation dictionaries matched
across the shared formats; all numeric evaluations matched fresh-target jobs.
No target fields, bridges, grammar rejections or precision were removed.

Bridge evaluation excludes target loading and shows no improvement between the
two shared formats. Target loading, including source/configuration verification,
fell 60.4%. Bundle open/hash/manifest validation took a median 0.0241 seconds,
and requested target hydration took 0.5661 seconds. The corresponding JSON
figures were 1.1952 and 0.4061 seconds: JSON's first stage also eagerly validates
every target, so the hydration-stage number alone is not a comparable complete
loading measurement. Other loading time includes provenance and metadata work.

One-time native bundle preparation took **13.5825 seconds**, including 11.0758
seconds generating targets (3.6919 seconds/span), 0.6887 seconds validating and
encoding them, and 0.1004 seconds compressing them. Preparation is excluded from
reuse-job timings. The JSON reference required a further 3.1994 seconds to load
the bundle, hydrate its exact targets, and build/save legacy JSON. That transcode
is a qualification cost, not a required production stage or a fair standalone
serializer comparison. Amortize preparation over repeated compatible jobs;
do not substitute the reused-target evaluate time for a cold-run time.

The identical-content JSON artifact was **20,525,293 bytes**; the bundle was
**2,218,551 bytes**, an 89.2% reduction. Its manifest was 1,093,203 bytes and its
compressed target payloads were 1,125,332 bytes, representing 19,432,903 expanded
bytes. All three native targets were distinct: **zero whole-target duplicates**
were removed. The observed reduction came from lossless compression. Exact
whole-target deduplication is separately covered by tests.

The subset check decoded precisely one shard and 12,085,200 expanded bytes for
the backup sentence, while the manifest accounted for all three samples. Full
target hashes matched the JSON reference, including timestamps and graph data.
Before-training median process PSS was 796,701 KiB for JSON and 707,632.5 KiB for
bundles; after-training PSS was 953,781.5 versus 926,060.5 KiB. These are two
single-worker observations, not peak-RSS bounds or a parallel-memory guarantee.

The sparse run produced a 2,395-byte segment, replayed to the identical
25,895,897-byte candidate, and survived owner restart. Full candidate anchors
are still written and staged; sparse capture/replay adds time in this path.
The pinned checkpoint, source hashes and branch head were unchanged. Temporary
benchmark artifacts were removed after the receipt was assembled.

The combined focused regression selection passed **330 tests in 34.17 seconds**,
including 46 new codec cases, preparation/worker integration, sparse replay,
Arrow compatibility, source identities, Constitution restrictions and the
mandatory semantic gates. This is not the entire repository test suite.

The comparison streams one bundle from the three public gates, then derives
the JSON reference from those exact targets. It separately checks complete
encoded-target SHA-256 values, document hashes, statuses and configuration.
A fresh-process subset check requests one of three samples and asserts exactly
one decompressed shard. Training compares full shared-target evaluations,
numeric fresh-target evaluations, candidate bytes and accepted epochs.

The native recipe retains all five bridges in order: `modal_frame_logic`,
`deontic_norms`, `fol_tdfol`, `cec_dcec`, `external_prover_router`; provers false;
metric disk cache 0; one training process and one bridge worker; sample memory
false; CPU `python_sparse_batch`; CUDA disabled; BLAS/OpenMP threads 1;
temperature 0; one epoch, one update family, one line-search attempt, and
max seconds 180. Three train samples equal three validation samples: **in-sample**.
Fresh jobs construct targets in fresh processes; shared jobs reuse sealed
targets. OS cache warmth is uncontrolled. Shared results are not cold target
generation timings.

## Next implementation costs

Keep the opt-in bundle path available for bounded jobs; retain JSON compatibility.
The projection update itself still took about 0.066 seconds, so this measurement
does not justify a CUDA backend change. The remaining costs include target
evaluation, source verification, full model startup/serialization and sparse
replay against a full recovery anchor. Qualify sparse-only versions with periodic
full compaction and nonblocking owner staging before expecting smaller patches
to reduce total checkpoint I/O.

At corpus scale, add the verified source/sample/split manifests and a leased
index of bounded bundles before distributing batches. The 1.09 MB common
configuration is now about half this small artifact: cross-bundle manifest
sharing or compression is a measured storage opportunity, but not a reason to
weaken source verification. Arrow feature weights remain opt-in under their
previous qualification; this comparison does not claim a new Arrow speedup.

To reproduce from the pinned source tree, choose a new output path:

```bash
PYTHONPATH="$PWD" python3 scripts/ops/legal_ir/benchmark_target_bundle_training.py --pairs 2 --output /tmp/target-bundle-benchmark-new.json
```

Only actual `lake build <Lib>` is a Lean admit. These storage and training
changes do not formalize the Constitution or permit `roundtrip_ok` on any of
its spans. No full Constitution campaign or publication is part of this slice.
