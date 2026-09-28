# Incremental parallel autoencoder streams

The operator CLI has since gained mandatory qualification and bounded retry
handling; see [qualification gates](QUALIFIED_PARALLEL_AUTOENCODERS_20260928.md).
The optimizer-only behavior and native results below describe the earlier
version and are not retroactively qualified.

The new operator entry point is
[`run_incremental_autoencoders.py`](../../../scripts/ops/legal_ir/run_incremental_autoencoders.py).
It connects verified Hugging Face census exchanges to the existing native
autoencoder workers, private checkpoint versions, and sparse checkpoint replay.
It runs bounded cycles and can repeat them periodically. No daemon installation
or unbounded production campaign is performed by the qualification below.

## Execution and ownership

Each machine runs one coordinator and several spawned workers. Only the
coordinator writes its local databases. Workers receive immutable job inputs,
load a private model, and return candidate artifacts for the existing owner
verification. DuckDB stores model versions and run receipts in `control.duckdb`,
incremental batches and private stream heads in `progress/progress.duckdb`,
and remote discovery/acknowledgements in `feed.duckdb`. These remain separate
databases because the existing registry seals its catalog schema.

Every input has a stable content identity. The same census span appearing in a
new exchange does not automatically retrain the same template. Different text
creates a new input. Hash assignment selects a machine shard and then a local
model stream. Each stream trains its batches sequentially; different streams
run concurrently. An accepted candidate supplies that stream's next parent.
A rejected optimizer step consumes the batch while retaining its previous
weights. This never promotes a registry branch or merges different workers'
weights. Different language/model variants can coexist through the library API
or separate operator state directories.

The core API is
`run_incremental_training(registry, templates, state_directory=..., lane_count=2, ...)`
in
[`autoencoder_incremental_training.py`](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_incremental_training.py).
It accepts existing immutable `TrainingJobSpec` templates, including verified
corpus/embedding inputs, shared targets, sparse checkpoint dependencies and
optional Arrow weights. The CLI emits one-span templates so new source arrivals
do not change old batch boundaries. Larger prebuilt batches can use the API.

## Resume and periodic input updates

Completed registry work is reconciled with progress after a lost response.
Checkpoint advancement and pending-queue removal commit atomically in the
progress database. On restart only each stream's latest checkpoint is replayed;
completed corpus history is not reserialized or scanned on every dispatch page.
The pending queue and total/completed counters are durable and indexed.

Resume occurs at completed batch boundaries. An uncertain running or failed
attempt blocks its stream for explicit recovery. The runner does not infer that
a timeout means the old computation never ran. Other streams can continue.
Changing the initial checkpoint, code or training policy under an existing
variant is rejected; use a new stream for a deliberate new experiment. Changing
the machine shard count/index or local stream count also requires a new stream.

[`span_cache_feed.py`](../../../ipfs_datasets_py/logic/autoformal/span_cache_feed.py)
resolves Hub HEAD to a full immutable commit and incrementally pages through
exchange manifests. Pending listings and downloads retain that original commit
if HEAD advances. It fetches only the manifest, census and goals files; their
bound hashes, schemas and byte limits are checked before intake. Weights and
the dataset's large resume checkpoint are excluded. Repeated ready inputs
remain available until the training runner has durably queued them. The runner
then acknowledges that bundle. A crash before acknowledgement repeats intake
without adding another batch. Original observations remain in retained exchange
files; input records retain source provenance and false admission flags.
Empty source text receives a durable skipped disposition.

Each poll processes a bounded tree page and bounded bundles. Network errors
remain retryable while previously verified inputs can still be consumed.
`--sync-interval` is the delay *after* a bounded training cycle, not a deadline
for receiving remote updates during an optimizer step. No imported goal is
executed or enqueued into a supervisor by this runner.

## Running

Run from the pinned `external/ipfs_datasets` checkout with the existing local
checkpoint. One bounded cycle:

```sh
python3 scripts/ops/legal_ir/run_incremental_autoencoders.py \
  --state-directory workspace/test-logs/autoencoders/uscode-node-0 \
  --repository-id justicedao/uscode-autoformal-span-cache \
  --workers 2 --max-batches 4
```

Repeat that command to resume. For recurring updates add
`--polls 0 --sync-interval 300`; Ctrl-C stops the isolated process group and
preserves uncertain work for recovery. For a bounded scheduler invocation use
`--polls 1`, the default, and rerun it periodically. There is an exclusive local
runner lock to prevent two owners using the same state directory.

On two machines use the same source/code/checkpoint/training configuration and
`--shard-count 2`, with `--shard-index 0` on one and `--shard-index 1` on the other.
Each needs its own state directory and local checkpoint. This is static work
partitioning, not a global lease service: operators must assign each shard index
once. Changing fleet size requires a new partitioned stream or a separately
reviewed migration. Cross-host assignment is tested with fixtures; the native
qualification uses two processes on this host, not two physical machines.

Local incrementally appended JSONL input is also supported through
`--input-jsonl samples.jsonl`. Each line is a `SampleRecord`, for example:

```json
{"title":"gate","section":"prohibit","text":"The agency shall not disclose records."}
```

The CLI uses training observations with no independent validation partition and
marks `heldout_canary=false`. For held-out work, use existing corpus-bound job
templates with explicit split provenance through the library API. The CLI does
not turn census agreement into a supervised success label.

Optional local `--shared-targets PATH --target-snapshot-id ID` reuses a verified
target artifact covering the selected records. `--arrow-feature-weights PATH`
supplies existing baseline-bound Arrow IPC weights. Target membership and
producer identity are verified by the original worker. Baseline Arrow views
are dropped after the stream changes its parent so stale weights cannot
replace accepted updates. Subsequent training uses the existing sparse chain;
this is not whole-model zero-copy training.

## Resources and opportunity cost

The CLI reuses `DaemonResourceReservation`, the host CPU/RAM scheduler and the
75 GB campaign ledger. It admits the entire coordinator/worker group, observes
group RSS and disk usage, and terminates the group at the configured cycle
deadline. Admission and usage checks are cooperative, not kernel quotas.
The default group allowance is 8 GiB and two CPU slots; each worker's native
thread count is one. Concurrent workers still retain private mutable state.
Optional Arrow views can share read-only numeric pages, not every Python object.

`--storage-bytes` is the allowance for the **whole retained stream directory**,
not just the next sparse update. It defaults to 1 GB and is bounded to 50 GB;
increase it explicitly as history grows, subject to the unchanged 75 GB shared
cap. The ledger conservatively charges reservations in addition to observed
bytes. No retained claims are cleared automatically. Successful cycles release
their reservation after workers have stopped and artifacts are durable; failed
cycles retain their evidence and disk claim. Resource-root inventories and
checkpoint verification have real startup cost, so larger bounded dispatch
pages amortize this overhead better than repeated one-row process launches.

The runner uses the existing registry/control architecture. It does not start a
new Quack listener or bypass an existing owner, and it does not introduce direct
multi-process writes to a shared database file. Existing DuckLake/HF publication
consumers can consume registry outputs through their established qualified
paths; this runner does not automatically publish or promote trained weights.
The current transfer is dataset work/evidence, not asynchronous gradient merging.
Independent models may diverge and each needs separate held-out evaluation
before any release decision.

The concurrency choice is consistent with
[DuckDB's documented ownership model](https://duckdb.org/docs/current/connect/concurrency).
Exact revisions and selective files use
[the Hub download API](https://huggingface.co/docs/huggingface_hub/guides/download).

## Qualification and limits

Receipts are under
`workspace/test-logs/federal-corpus-audits/incremental-autoencoders-20260928`.
The separate live feed probe retrieved 3 census records / 555,878 bytes from
Hub commit `e537edd812e6fb714647fbaef2134df7606cd3d2`; replay required zero
additional downloaded bytes. Native training, resumed execution and final
combined test results are recorded in the accompanying verification receipt.

Publication scope is the new feed, incremental coordinator, operator script,
their tests and these receipts. The native measurements use the canonical
workspace source hashes in the receipts. Concurrent parser, canonical compiler,
canonical decompiler and formula-builder edits differ from GitHub main and are
preserved outside this publication. An additional audit of that work passed
five sunset-repair tests, but the wider formula/parser audit reported 285 passes
and 30 failures. Those failures are retained in
[the source audit](evidence/incremental-autoencoders-20260928/source-regressions.xml);
the passing 372-test result is the bounded parallel-runner qualification, not a
claim that every test in the workspace passes. Native timings do not attest to
an identical source tree on another machine or at the published Git commit.

The [native verification](evidence/incremental-autoencoders-20260928/verification.json)
passed: the first cycle dispatched two distinct workers with overlapping live
CPU observations; restarting dispatched the remaining batch from a prior
accepted private checkpoint. A further periodic cycle dispatched zero jobs.
Completed totals were 2, 3, 3, with pending totals 1, 0, 0. All three optimizer
steps were accepted. Source and orchestration hashes stayed fixed during the
qualified cycles, and the protected restart12 checkpoint stayed unchanged.
All three resource reservations were released. The native smoke used ordinary
private weights with sparse checkpoint persistence; optional Arrow/shared-target
continuation was covered by tests, not enabled in this native measurement.

| Measurement | Result |
|---|---:|
| Native worker wall time per one-span job | 7.710–8.921 seconds |
| Initial bridge-on evaluate per span | 5.204–6.180 seconds |
| Warm line-search bridge-on evaluate per span | 0.183–0.223 seconds |
| First two-worker cycle, including admission and verification | 34.619 seconds / 2 spans = 17.310 seconds per span |
| Resumed one-worker cycle | 35.612 seconds / 1 span |
| Replay cycle, no new training | 19.889 seconds |
| Peak observed first-cycle group RSS | 2,386,743,296 bytes (sampled, not continuous peak) |
| Regression tests | 372 passed in 47.42 seconds |

This makes the opportunity cost visible: process admission, named-root disk
accounting, immutable checkpoint staging and replay dominate these tiny dispatch
pages. Two worker processes overlap, but this test does not establish a speedup
against an equivalent serial campaign. The receipt records exact initial and
warm line-search bridge evaluation times for each of the three real census
spans (7 USC 2006d, 16 USC 6809, 5 USC 8410), each with one legal-IR target.
The optimizer profiler calls the initial phase `before_holdout_evaluation`; here
it is explicitly in-sample because validation_sample_count is zero.

An earlier diagnostic poll produced no input because the inherited offline
mode also disabled the Hub reader. The operator now enables network access only
in the dataset-owning coordinator; spawned workers retain their existing offline
environment. That empty diagnostic is retained outside the qualified final
stream and is not counted as a training success or timing result.

Five bridge names remain `modal_frame_logic`, `deontic_norms`, `fol_tdfol`,
`cec_dcec`, `external_prover_router`; provers are off, bridge worker count is 1,
metric disk cache is 0, sample memory is off, and temperature remains 0.
Native worker receipts distinguish cold initial evaluation from later warm
in-process line-search evaluation and report nonzero target counts. No comparison
to the earlier different three-sentence measurement establishes a speedup.

Optimizer acceptance, checkpoint replay, database completion and census rows
are not admissions. Only `lake build <Lib>` can admit Lean through the existing
path. No Lake build is invoked by this training runner, and the Constitution
remains unformalized. Compiler/decompiler/parser acceptance is unchanged.
