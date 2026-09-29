# Distributed feature training: storage retry

The allocated retry passed native training, graceful shutdown, owner/worker
restart, and a later live Hugging Face upload/download check of the exact final
selected checkpoint. Every owned native and transport resource claim was
released without manual reconciliation. The earlier
[report and its storage failure](AUTOENCODER_DISTRIBUTED_FEATURES_20260929.md)
remain unchanged.

The campaign storage cap increased from 87 to **90 GB** through an explicit,
locked migration preserving all 257 existing reservation records and storage
roots. The per-worker maximum remains 50 GB. The fresh migration census left
3.505 GB headroom. Retained claims never expire automatically.
After the retry and transfer, the final census measured
2.627 GB headroom; all 19 new claims owned by this
retry were released, and all 257 pre-migration records remained identical.

| Allocation | Retry |
| --- | ---: |
| Outer worker, each of two | 400 MB |
| Owner | 250 MB |
| Nested training job, each | 250 MB |
| Shared target preparation | 300 MB |
| Frozen-run wrapper | 16 MiB |
| Live Hub transport | 256 MiB storage; 1 GiB RAM |
| Live Hub capsule wrapper | 16 MB storage |

MB and GB above are decimal; MiB and GiB are binary. These are cooperative
admission and polled usage limits, not filesystem quotas. A continuous run
still needs space for retained jobs, sparse patches, evidence and parent copies.

The retry ran the published dataset source `db43d80c` plus the tested
90 GB cap override, under frozen read-only mounts at the canonical workspace
paths. Its source receipt also binds the dependency exports and JevOps snapshot.
No HACC source substitution was used. The resource and lock suites passed
**96 tests**; the retry harness passed **11 checks**.

Two native workers processed two US Code training spans against two disjoint,
repeatedly used tuning spans, with verified local 384-dimensional GTE-small
embeddings. There were **3 native jobs and 9 accepted epochs**;
6 epochs are on the selected ancestry, and the retained stale candidate
was safely retrained from the current generation. Both workers verified the
same generation 3 checkpoint: **5,555,747 bytes**, SHA-256
`429d8667e9593d01f9dba2149e163fdfd05cbe6f6d274bc16ee2b7c1ab5a5d62`.

Owner-checked tuning cosine changed from
0.196116 to 0.795083; reconstruction loss changed from
0.00252708 to 0.00201069.
These are repeated-tuning feature measurements, not held-out qualification or
evidence of reaching a global minimum. Timing bounds establish at least 4.593 seconds of overlap between training calls; this does not prove simultaneous optimizer CPU execution.

The owner and both workers were then restarted from their retained state.
Each worker performed three bounded normal polls, with **zero new training
jobs and zero additional Hub-simulation fetches or bytes**. The training
artifact inventory was unchanged and both full-weight acknowledgments matched.
Both training and resume phases exited cleanly.

The subsequent live Hub check used the same source capsule, mounted read-only
at the canonical paths, with networking explicitly enabled for this authorized
transfer. Runtime/source proofs matched before and after. It published the
complete generation 2 parent as an
unqualified anchor, followed by the selected child's sparse patches and native
feature evidence. Two fresh local consumer stores independently downloaded and
replayed the [exact selected update](https://huggingface.co/datasets/justicedao/uscode-autoformal-span-cache/blob/fb30e3407b9cf210549aea504ff2a150dfff5ae0/autoformal/uscode/feature-pretraining/updates/4874a5d31293fa802ea3d21ea1919678f8a12621e30eefbc72bb7a4fd1aa38c8.json), obtaining the identical
complete checkpoint. Both subsequent weight and evidence resumes fetched zero
bytes. The original native registry was opened read-only and its hash remained
unchanged; no additional training was attributed to transport.

Each fresh weight consumer downloaded 13,687,349 update bytes and
3,800,512 parent bytes. The raw epoch patches total 13,371,213
bytes. Sparse postimages can exceed the complete checkpoint size; this run
does not establish a bandwidth advantage. Exact replay and parent binding were
verified, and periodic full-parent compaction bounds ancestry.

| Timing scope | Wall time |
| --- | ---: |
| Complete frozen native invocation, including preparation and resume | 577.740 s |
| Cold target generation, 4 spans and 4 targets | 16.109 s/span |
| Complete supervised target preparation, 4 spans | 94.449 s |
| Bridge-on tuning evaluate, 2 samples and 2 targets per call | 1.334–2.039 s/call |
| Bridge-on training cache preparation, 1 sample and 1 target per call | 1.785–2.142 s/call |
| Live Hub publication plus two fresh download/replays and resumes | 36.029 s |

All IR measurements use `modal_frame_logic`, `deontic_norms`, `fol_tdfol`,
`cec_dcec`, and `external_prover_router`; provers are false, metric disk cache is
0, requested IR workers are 1, and sample memory is false. Target preparation
is cold. Evaluations reuse explicitly prepared targets, generate zero new
targets and start zero target-generation workers. Target preparation is not a
compiler-only timing, and these scopes are not a speed comparison with the
earlier Constitution or three-gate measurements.

Native training used a clearly labeled local Hub simulation. The subsequent
transfer test used the real Hugging Face dataset. Both were on one physical
host: this establishes the component path and exact transfer/resume behavior,
not deployment on two physical machines. Hosts must still provision matching
source, dependency/runtime fingerprints, verified embeddings, shared targets,
private Quack access and dataset credentials. The existing
[deployment commands](AUTOENCODER_DISTRIBUTED_FEATURES_20260929.md#provisioning-and-commands)
apply with locally admitted storage budgets.

Feature checkpoints remain `qualified=false`, `admitted=false`, and
`formalized=false`. Actual `lake build Legal` remains the admission gate;
this feature retry executed no Lake build and did not promote an inference
model. The Constitution is not formalized. No Mathlib, new pretrained weights,
context expansion or temperature change was introduced.

The [evidence summary](evidence/autoencoder-distributed-features-retry-20260929/summary.json)
binds the compact native, resume, source, test, cap-migration and live-transfer
receipts. Raw weights, private connection files, credentials and the shared
reservation ledger are excluded from this publication.
