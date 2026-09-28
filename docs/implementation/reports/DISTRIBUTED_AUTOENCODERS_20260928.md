# Distributed span training and complete-weight synchronization

Follow-up: [80 GB cap, completed publication/convergence and restart validation](DISTRIBUTED_AUTOENCODERS_80GB_20260928.md).
The status below records the earlier 75 GB run.

Status: the combined focused suite passed 148 tests; the final downloader suite
passed 34 tests, including one subsequently added regression. A two-worker native exercise verified complete
seed downloads, simultaneous training and actual qualification, then stopped at
the unchanged 75 GB storage cap before publication and generation synchronization
completed. Deployment across physical hosts has not been demonstrated. This is
not a production-readiness or corpus-formalization claim.

## What runs where

`scripts/ops/legal_ir/run_distributed_autoencoders.py` runs one campaign owner
and independent workers. The owner exclusively opens the shared DuckDB weight
registry and publishes one scoped Quack endpoint for each configured worker.
Workers have their own local registries, training directories, checkpoints and
resource ledgers; they do not concurrently open the owner's DuckDB file.

The control vocabulary is limited to reading campaign/assignment state,
acknowledging exact complete weights, claiming and renewing a span assignment,
and submitting an immutable report reference. Quack carries bounded control
records. Hugging Face carries immutable weights, evidence, census and goals.
The implementation uses the existing Quack prototype; it does not add a
public database endpoint or claim new DuckLake production qualification.

The owner maintains a canonical campaign generation. Every generation binds
an immutable version ID, the SHA-256 and size of the **complete checkpoint**,
and a portable artifact reference. A worker reconstructs the entire checkpoint
and hashes its bytes before acknowledging that generation. Acknowledgement is
required before a new claim. A local `current.json` pointer changes only after
the complete bytes are verified; older generations remain available. Recovering
a still-live older assignment verifies its private snapshot without moving the
canonical local pointer backward. Synchronization happens at polling/batch
boundaries; an offline or busy worker is not claimed to be instantly current.

Workers can train different spans concurrently against the same generation.
Their updates remain separate candidates. The owner downloads and independently
qualifies a successful candidate before a compare-and-swap generation advance.
A sibling trained against an older generation cannot silently overwrite or
merge into the new weights: its source work is requeued for the new generation.
This provides parallel candidate work with serial canonical selection, not
synchronous gradient averaging or a merge of every worker's sparse patch.

## Source revisions and resume

The owner accepts bounded local JSONL and optionally polls
`justicedao/uscode-autoformal-span-cache` for immutable census exchanges.
Use explicit span IDs when a legal provision can change:

```json
{"source_span_id":"usc:5:example:clause-a","sample":{"title":"5","section":"example","text":"Full source text goes here."}}
```

This is an input-shape example, not a statute or successful formalization.
Changing source text retains the supplied span ID but produces a distinct
revision. Bare `SampleRecord` JSON is also accepted; its identity is based on
content. Prior observations are retained as immutable audit artifacts, while
repeated observations of an unchanged revision do not themselves cause another
training job.

Feed discovery pins each listing and download to an immutable Hub commit.
Bounded pages, pending downloads and verified inbox bundles survive restart.
The owner acknowledges a feed bundle after durable source-work registration.
Acknowledgement means intake completed, not training or legal admission.

Worker commands are journaled before transmission and reuse their operation
IDs after a lost reply. Span leases include worker, attempt, fence and owner
generation. Heartbeats renew the exact lease. Stale reports cannot acquire
authority after reassignment. Pending reports remain reserved for owner
verification; a verifier failure does not silently complete the source work.

Local training resumes at completed qualified attempts, not within an optimizer
step. Interrupted native attempts may require explicit recovery or a new
fenced worker attempt. Retain the state directories and artifacts used by the
original command when restarting.

## Weight and evidence transfer

Only explicitly selected campaign artifacts are downloaded. This authorization
does not enable pretrained-model downloads or Lean toolchain installation.

| Artifact | Transfer and authority |
| --- | --- |
| Initial full seed | One immutable `autoformal/uscode/autoencoders/anchors/<sha>.state.json`; transport baseline only, unqualified. |
| Ordinary successful update | Sparse manifest and complete sparse dependency closure, exact qualification receipt, Lean source/log and pinned project metadata. |
| Prior generation | Reconstructed recursively from its portable sparse reference and earlier anchor. Each complete reconstructed parent must exactly equal the next update's anchor SHA and byte count. |
| Periodic full snapshot | Explicit bounded compaction of an exact checkpoint; not falsely labeled a sparse transfer. |
| Span attempt | Exact source/revision, candidate and base generation, qualification disposition and repair evidence, including failed attempts. |
| Census and goals | Existing immutable exchange format; dataset handoff does not mean submission to a live supervisor. |

Downloads are pinned to 40-character Hub commits and verified by expected
SHA-256 and sizes. Verified local files are reused after interruption. Before
fetching a parent, workers search their installed generations and the owner
checks its existing artifact store. The exact full hash is rechecked; a corrupt
local parent fails rather than silently falling back. Portable ancestry is
validated even when the parent is already local. Recursive
portable references reject cycles and allow at most eight sparse generations;
the runner compacts the parent before extending a chain beyond that bound.
Within each sparse bundle, the existing sparse-checkpoint depth and replay
limits also apply. A generation download never promotes a model or makes it
locally qualified.

The owner and workers compare their pinned source identities before work and
publication. Changing compiler/parser/qualification/orchestration sources,
worker set, validation set or campaign policy requires an explicit new campaign.
Do not edit the HACC checkout or `hallucinate_app` to make those identities match.

## Qualification is unchanged

Successful candidates must pass every existing gate on the assigned training
source and disjoint tuning-validation sources:

- Embedding round-trip cosine at least `0.72` and reconstruction loss at most
  `0.20`, checked per row with sample memory disabled.
- Deterministic source compiler/decompiler semantic round-trip checks.
- Actual syntax parsing for FOL, deontic FOL, temporal FOL, deontic temporal FOL,
  deontic cognitive event calculus, and frame logic.
- Source-locked `lake build Legal`, using the installed pinned Lean toolchain.

The autoencoder produces embedding reconstructions; it does not decode source
text or Lean programs in this pipeline. Logic-family exports are explicitly
qualified syntax projections, not automatic proof of cross-family semantic
equivalence. The Lake admit concerns only the generated source-locked numeric
theorem. It does not admit a whole statute, an autoencoder, a checkpoint, a
bridge target, an NCA cell or a DuckDB row. No Mathlib is imported.

The validation set participates in repeated candidate selection and therefore
is tuning validation, not an independent generalization canary. Temperature
remains zero. The Constitution remains unformalized; its spans must not be
marked `roundtrip_ok`.

## Start an owner

Use the identical reviewed checkout layout on each host, including the sibling
`JevOps/jevops/statement_lock.py`. The compiler, parser and decompiler must resolve
from this `external/ipfs_datasets` tree. The installed native DuckDB/Quack
extension and pinned Lean toolchain must already be present. The owner and
training workers need existing authorized Hub credentials for the campaign
dataset; keep those credentials out of command logs and publication artifacts.

From `external/ipfs_datasets`, adapt the paths below to an existing resource
ledger whose roots include the state directory:

```bash
PYTHONPATH="$PWD" python scripts/ops/legal_ir/run_distributed_autoencoders.py owner \
  --state-directory /absolute/campaign/owner \
  --resource-ledger /absolute/campaign/resources.json \
  --campaign-id federal-en-example \
  --worker-id host-a --worker-id host-b \
  --input-jsonl /absolute/campaign/source-spans.jsonl \
  --validation-jsonl /absolute/campaign/tuning-validation.jsonl \
  --repository-id justicedao/uscode-autoformal-span-cache \
  --serve-seconds 0
```

The optional `--checkpoint` defaults to the protected restart12 checkpoint.
The script checks its pinned hash and does not overwrite it. The initial
command uploads that exact seed as an unqualified transport baseline.
`--repository-id` enables incremental census intake; omit it for a bounded local
source test. The source feed covers published census exchanges, not a guarantee
that every federal provision is already present in the dataset.

The owner writes `connections/<worker-id>.json` and a private
`connections/<worker-id>.token`. Give each worker only its own files. The token
file must retain mode `0600`. Connection details and tokens change when the
owner restarts; transfer the refreshed worker-specific files before reconnecting.

## Start workers locally or through SSH

For a worker on the owner's host:

```bash
PYTHONPATH="$PWD" python scripts/ops/legal_ir/run_distributed_autoencoders.py worker \
  --state-directory /absolute/campaign/host-a \
  --resource-ledger /absolute/campaign/resources.json \
  --connection-file /absolute/campaign/owner/connections/host-a.json \
  --polls 0 --max-jobs 0
```

For a remote worker, privately transfer its JSON connection descriptor and token.
Read the port from its `quack:127.0.0.1:<owner-port>` endpoint; do not expose that
listener publicly. On the worker host, establish an authenticated SSH forward:

```bash
ssh -N -L 127.0.0.1:19001:127.0.0.1:<owner-port> <owner-ssh-host>
```

In another terminal on that worker, use the matching reviewed checkout and a
host-local resource ledger:

```bash
PYTHONPATH="$PWD" python scripts/ops/legal_ir/run_distributed_autoencoders.py worker \
  --state-directory /absolute/campaign/host-b \
  --resource-ledger /absolute/campaign/host-b-resources.json \
  --connection-file /private/host-b.json \
  --token-file /private/host-b.token \
  --endpoint quack:127.0.0.1:19001 \
  --polls 0 --max-jobs 0
```

These commands describe deployment; they are not evidence that a remote host
has been deployed or tested. `--sync-only` downloads/verifies and acknowledges
weights without claiming work. For bounded smoke runs use finite `--polls`,
`--max-jobs`, `--serve-seconds`, and the existing training/time/storage limits.

## Observe progress and practical limits

The owner writes `status.json` and immutable iteration observations. Compare
`weights.artifact` and `acknowledged_current_workers`; an acknowledgement is a
worker's report of local full-byte verification, not remote attestation. Worker
`weights/current.json`, per-generation `installed.json`, `worker-status.json`,
control journals and per-attempt receipts retain the corresponding identities.
Qualified weights and all span dispositions remain distinct evidence types.

Multiple workers increase concurrent source processing, but a slow candidate
may need retraining when another worker advances the canonical generation.
The present design does not average or merge sibling deltas. Source changes
append revisions; they do not erase historical source or result evidence.
Invalid evidence fails closed and remains for investigation. Network failures
retain local artifacts and pending control/publication state.

This runner does not automatically deploy workers, authenticate previously
unknown machines, install dependencies, or cover unseen corpus spans. It also
does not turn the operational dataset into an entirely autoformalized US Code
or Constitution. Any corpus-level completion claim requires a complete pinned
source census and measured gate results for that census.

## Available validation

The downloader/publication unit tests use explicit transport fixtures and fake
Hub responses; they do not claim native model or Lake execution. The final recursive
download suite passed 34 tests, including a fresh-machine reconstruction from
two sparse bundles and one seed, zero-download resume, hash mismatch, invalid
paths, malformed checkpoint data, cycle/depth rejection and bounded retry.
The combined focused suite passed **148 tests in 38.54 seconds**, including native
Quack control and failure/recovery tests. The integration smoke uploaded the
25,895,338-byte pinned seed in Hub commit
`16ee0931888173934ad1863cc6058d6a48723fcb`. Both workers downloaded and verified
SHA-256 `1446cb1859ddf4ed40fb5576f6e320eece4cec268a008c5c07bffeaf959cd8dd`
and acknowledged generation 1 before claiming different spans. Their native
training processes overlapped on this host.

The synthetic 20-day minimum-duration fixture passed metric, canonical semantic,
six-family syntax, actual Lake and disjoint tuning-validation gates. The real
5 USC 8410 source passed the metric gate but failed semantic, syntax and Lake
gates. These are workspace-scoped results using mock stable embeddings; they
are neither pretrained semantic quality nor federal-corpus completion evidence.

The shared resource ledger stopped the run when observed bytes plus retained
reservations reached the unchanged 75 GB cap. A read-only audit identified five
exact, dead-process reservations from this task totaling 3.39 GB as candidates
for an explicitly approved release. Their 174.2 MB of artifacts would remain
preserved and charged; ambiguous and historical claims would remain untouched. No new canonical generation or
complete publish/download convergence is claimed from this interrupted run.
Its artifacts and failed-run reservations remain intact pending explicit
reconciliation. Startup defects found during this exercise were fixed: private
token creation uses Python's supported file API, and both coordinators wait up
to 60 seconds for the existing resource-ledger lock, within its established
bound. Capacity and qualification gates were not relaxed.

The checked-in native evidence comes from the pinned workspace, whose semantic
compiler/parser files contain concurrent edits relative to origin/main. This
change publishes the reviewed distributed runner and its tests, not a blanket
merge of those unrelated edits. A campaign rejects workers whose actual source
hashes differ. Start any deployment from identical reviewed source on every
machine; these workspace results are not represented as a clean-main benchmark.

### Observed per-span timing (interrupted native run)

| Training source | One accepted projection epoch | First bridge-on evaluation | Native qualification |
| --- | ---: | ---: | ---: |
| Synthetic 20-day minimum | 5.987 s | 4.445 s | 6.732 s |
| Real 5 USC 8410 | 9.620 s | 5.353 s | 7.949 s |

Each optimizer used one training sample and reported one legal-IR target. All
five bridges ran: `modal_frame_logic`, `deontic_norms`, `fol_tdfol`, `cec_dcec`,
and `external_prover_router`. Provers were disabled; metric disk cache was `0`;
`legal_ir_parallel_workers=1`; sample memory was disabled. Processes began cold,
but later phases reused in-process targets. These wall times are phase-specific,
not end-to-end span completion times or a comparison to the earlier three-span
measurement. Native process observation windows overlapped for 2.357 seconds;
exact simultaneous projection execution was not measured.

The local-parent reuse optimization was added after the interrupted native run
and is covered separately by focused transport tests; its live transfer savings
are not claimed as measured native results.
