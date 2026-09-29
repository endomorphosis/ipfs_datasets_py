# Shared feature training across machines

The shared-owner distributed runner has an explicit `feature_pretraining`
purpose. It combines the verified local feature optimizer with the existing
DuckDB owner, scoped Quack assignments, durable progress, and immutable Hugging
Face exchange. The separate formalization purpose retains its semantic,
logic-family, reconstruction, and actual `lake build Legal` qualification.

Feature checkpoints always remain `qualified=false`, `admitted=false`, and
`formalized=false`. Learning from compiler-derived IR supervision does not
formalize the source law. The Constitution is not formalized. No Mathlib,
embedding model downloads, larger context window, or temperature change is
part of this workflow.

## Work and weight synchronization

One owner opens the shared DuckDB registry. Independent workers use scoped
Quack clients through loopback or an explicitly configured private SSH tunnel.
Workers have their own local training registry and numerical state; they never
open the owner's database over a shared filesystem. This is the existing
DuckDB/Quack control path; it does not add a DuckLake dependency to training.

Every worker downloads or replays the advertised complete generation and
verifies its full byte hash before acknowledging it or claiming work. A span
claim binds the exact source revision, campaign policy, code identity, parent
weights, lease and fencing token. Interrupted claims and ambiguous network
replies reuse durable operation IDs. The owner persists the corpus progress.

Workers train bounded raw-decoder feature jobs with disjoint repeated tuning
samples, the five fixed IR bridges, sample memory off, provers off, metric disk
cache off and one IR worker. They upload content-addressed sparse updates and
feature evidence to the authorized dataset under
`autoformal/uscode/feature-pretraining/`. Full seeds and periodic parent
compaction use the existing explicitly unqualified anchor transport. Ordinary
updates transfer sparse patches and evidence, with exact parent identities.

Before selecting a candidate, the owner reconstructs its complete weights,
checks assignment and producer bindings, and independently evaluates the raw
feature objective and IR regression guards on its verified tuning inputs.
Canonical selection uses a compare-and-swap against the previous generation.
It does not promote an inference model or grant legal qualification.

Concurrent candidates are branches from their assigned parent. Once one is
accepted, stale work is retained and requeued against the current generation.
Sparse postimages are never added together or silently applied to a different
parent. This trades some repeated training for a directly checked sequence of
improving feature checkpoints. It is not synchronous distributed gradient
averaging and does not establish convergence to a global optimum.

At their polling interval, all workers pull the current generation. Machines
can temporarily differ while training or transferring; the owner's
`acknowledged_current_workers` records which have verified the exact current
complete artifact. A disconnected worker catches up when it reconnects.

## Provisioning and commands

Use the same canonical source generation and dependencies on every host,
including the sibling `JevOps/jevops/statement_lock.py` used by the source
identity check. Both hosts need the exact DuckDB version and its existing
hash-pinned local `quack` and `httpfs` extension artifacts; this runner does not
install them. The initial parent must be a compatible full checkpoint in the
autoencoder's canonical serialization, so exact no-update comparisons work.
Shared target provenance also binds the existing Python, platform/kernel and
installed-distribution fingerprint. Hosts with a different fingerprint fail
closed; this change does not make targets portable across arbitrary runtimes.
Provision each host with the verified embedding manifest, its referenced
embedding-production receipt and source artifacts, the exact training/tuning
JSONL files, and the shared target bundle. Paths may be local to each host;
the campaign binds portable content identities. Every host independently
verifies the embedding provenance and target bytes. No pretrained model is
downloaded. The tuning role is repeated optimizer selection, not an independent
canary. Corpus changes require a newly verified immutable campaign policy.
Prepare targets with `scripts/ops/legal_ir/prepare_shared_autoencoder_targets.py`
after provisioning the chosen published source generation. The native smoke
bundles below belong to their captured source generation; they cannot be reused
after pulling different parser/compiler source.

Hugging Face automatically exchanges weights and result evidence. This first
feature campaign path does not poll arbitrary new span rows into training:
those rows need verified embeddings and targets before joining a new campaign.

Run one owner, replacing the example paths, snapshot identity and budgets with
the exact prepared inputs and locally admitted resources:

```bash
python scripts/ops/legal_ir/run_distributed_autoencoders.py owner \
  --training-purpose feature_pretraining \
  --campaign-id uscode-features-v1 \
  --worker-id machine-a --worker-id machine-b \
  --checkpoint /LOCAL/compatible-feature-parent.state.json \
  --input-jsonl /LOCAL/training.jsonl \
  --validation-jsonl /LOCAL/tuning.jsonl \
  --feature-input-manifest /LOCAL/feature-inputs.json \
  --shared-targets /LOCAL/targets.bundle \
  --target-snapshot-id sha256:EXACT_PREPARED_TARGET_SNAPSHOT \
  --target-timeout-seconds 60 \
  --state-directory /CHARGED/owner \
  --resource-ledger /LOCAL/disk-reservations.json \
  --epochs 3 --line-search-attempts 2 \
  --projection-optimizer-mode productive_adaptive \
  --projection-momentum 0.25 \
  --projection-candidate-update-order decoded_embedding_structural \
  --serve-seconds 0 --sync-interval 30
```

The owner writes one connection JSON and private token for each named worker
under `owner/connections/`. Provision only the worker's own token through your
existing private channel; keep its mode `0600`. On another host, establish the
explicit authenticated SSH forward to the advertised loopback endpoint:
`ssh -N -L 127.0.0.1:LOCAL_PORT:127.0.0.1:OWNER_PORT OWNER_HOST`, taking
`OWNER_PORT` from that worker's connection JSON. Pass the local endpoint as
`quack:127.0.0.1:LOCAL_PORT` using `--endpoint`. The Quack endpoint itself is not a
public network service. The owner and workers need existing Hugging Face
credentials authorized to append artifacts to the dataset. Tokens are not
stored in reports or uploaded evidence.

Run the corresponding worker with its own state directory and resource ledger:

```bash
python scripts/ops/legal_ir/run_distributed_autoencoders.py worker \
  --training-purpose feature_pretraining \
  --connection-file /PRIVATE/machine-a.json \
  --token-file /PRIVATE/machine-a.token \
  --endpoint quack:127.0.0.1:LOCAL_PORT \
  --feature-training-jsonl /LOCAL/training.jsonl \
  --feature-validation-jsonl /LOCAL/tuning.jsonl \
  --feature-input-manifest /LOCAL/feature-inputs.json \
  --shared-targets /LOCAL/targets.bundle \
  --target-snapshot-id sha256:EXACT_PREPARED_TARGET_SNAPSHOT \
  --target-timeout-seconds 60 \
  --state-directory /CHARGED/machine-a \
  --resource-ledger /LOCAL/disk-reservations.json \
  --polls 0 --max-jobs 0 --sync-interval 30
```

The same commands and state directories resume a campaign. Use one worker
identity/state directory per concurrent worker process, including additional
workers on the same host. Admission remains bounded by each host's existing
resource scheduler and durable storage ledger. A `--sync-only` feature worker
needs the connection and token but no training inputs; it downloads/replays and
acknowledges complete weights without training. After owner restart, refresh
the connection/tunnel for the newly created transient endpoint.

Observe owner `status.json`, worker `worker-status.json`, immutable job result
receipts and the feature namespace in the dataset. Retained stale/failed
candidates remain evidence; they are not successful laws or canonical weights.
Only a verified current-generation acknowledgment means a machine has the
same complete selected weights.

## Validation

The scoped suites passed **306 tests**, including the native two-client Quack
transport test, existing qualified/local-feature regressions, feature exchange,
source and generation binding, retry recovery and stale-work handling.
The same **306 tests passed in 84.93 seconds**, with no skips, on a verified
partial export of `origin/main` (`61733095`) plus the nine scoped code/test
changes. Imported source paths and file hashes were checked before and after;
the live Git HEAD and ordinary index were preserved. The validation reservation
was released. Test harness setup failures remain in the local audit trail.

The live Hugging Face exchange smoke published an already recorded native
feature candidate, then reconstructed it independently into two fresh local
stores. Both produced the exact full checkpoint SHA
`04e916bc3fc9eb32a6836794e53b50b7230083300349415c350c67faff347a2b`
(3,231,074 bytes); both resumed with **zero bytes and zero fetches**. The original
training registry was read-only and its hash remained unchanged. No new
training or formalization was attributed to this transport test.

The [immutable feature update](https://huggingface.co/datasets/justicedao/uscode-autoformal-span-cache/blob/614c0472f163c74ef01defe8ecf1f224f26b5545/autoformal/uscode/feature-pretraining/updates/060135a0c0c559845b243236d330754d3d8b45f36174443f6c53b3dd6134ce26.json)
references three native epoch patches totaling 13,371,382 bytes, plus evidence.
Each fresh store transferred 13,687,357 update bytes and a 1,558-byte seed.
The two first download/replay calls took 5.175 and 3.598 seconds; the complete
publication/download/resume test took 24.317 seconds. This is transfer evidence,
not a bridge evaluation speed measurement or a two-physical-machine test.

Those early epoch postimages are larger than the final full checkpoint, so
sparse transport is not a bandwidth improvement for this example. Periodic
full parent compaction bounds ancestry; later optimization could also squash
overlapping postimages while preserving exact replay and epoch evidence.
No bandwidth or convergence benefit is inferred from the word "sparse."

The separate native training smokes used two worker processes with an explicitly
simulated Hub transport inside a frozen canonical source environment. Both
processed two training spans against two disjoint, repeatedly used tuning spans.
The first smoke completed three one-epoch jobs, safely retrained one stale
candidate, advanced to generation 3, and released every resource claim. Both
workers verified the same 5,555,794-byte complete weights. Its complete frozen
invocation took 382.083 seconds.

The second smoke used three epochs per job: nine accepted epochs, including
three from the retained stale proposal, and six on the selected ancestry. Both
workers verified generation 3 with full SHA
`9f2081934cbb35c530e068ff90dcce90a26c43dbfa7aef8aadb29930e3c79bb1`
(5,554,896 bytes). Independently checked tuning raw cosine rose from 0.196116
through 0.653217 to 0.796117; reconstruction loss fell from 0.00252708 to
0.00201148. These are repeated-tuning feature results, not held-out qualification.
The complete invocation took 422.824 seconds.

After its final acknowledgment, the second worker exceeded the smoke's
180,000,000-byte reservation with 194,051,423 retained bytes and stopped at the
storage guard. The initial collector correctly failed the resource closeout.
The harness's earlier completion flag covers training/synchronization only;
it is not evidence of clean shutdown. Administrative closeout preserves that
failure and all retained artifacts. Use a budget that covers retained jobs,
patches, evidence and downloaded ancestors for continuous operation.

Both smokes demonstrated independent native workers and stale-parent recovery.
Their process lifetimes overlapped; conservative timing envelopes do not prove
overlapping optimizer calls or CPU execution. Neither establishes execution on
two physical hosts. The end-to-end native runs used captured live source, whose
parser/compiler differs from the newer `origin/main` base. Publication retains
those upstream improvements; isolated source compatibility tests are a separate
check, not a native training run on that publication tree.

| Timing scope | First smoke | Three-epoch smoke |
| --- | ---: | ---: |
| Cold target generation, seconds/span, 4 spans | 16.219 | 15.475 |
| Complete supervised target preparation, seconds, 4 spans | 90.048 | 90.962 |
| Bridge-on evaluate, seconds/call, 2 samples and 2 targets | 1.369–2.047 | 1.318–1.961 |

Every row uses `modal_frame_logic`, `deontic_norms`, `fol_tdfol`, `cec_dcec`, and
`external_prover_router`; provers are false, metric disk cache is 0, requested
IR workers are 1, and sample memory is false. Target preparation is cold with
no process metric cache. Evaluations reuse the explicitly prepared targets:
they generate zero targets and start zero target-generation workers. These
different timing scopes do not establish a speedup over the earlier three-gate
or Constitution measurements. Target generation time is not compiler-only time.

The [evidence summary](evidence/autoencoder-distributed-features-20260929/summary.json)
links the separate native, live Hub, source-test and manual-closeout receipts.
The [source test receipt](evidence/autoencoder-distributed-features-20260929/tests-publication-source.json)
records the exact source hashes intended for publication.
