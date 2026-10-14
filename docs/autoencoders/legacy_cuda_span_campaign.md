# Legacy CUDA span campaign

This runner collects legacy autoencoder feature observations alongside an
independent source compiler's output. It is an inference campaign, not model
training, learned formula generation, or legal admission. The executable is
[`run_legacy_span_cuda.py`](../../scripts/ops/legal_ir/run_legacy_span_cuda.py).
This page documents its operating contract. The September 30 deployment and
measured evidence are recorded below; current progress belongs to the live
status file and immutable publication receipts.

## What the model observes

The local legacy checkpoint must have SHA-256
`7236de26bd3d7f8414ffa04805f1b6e8a8849f9e0103cec6edb4985b911658be`
and size 398,209,746 bytes. Its default local location is:

```text
/home/barberb/portland-laws.github.io/ipfs_datasets_py/workspace/todo-queues/legal-ir-autoencoder-canonical.state.json
```

The checkpoint has eight-dimensional embedding tables. This diagnostic uses
the historical `mock:stable-sha256` input representation. Those deterministic
vectors are **not verified semantic embeddings**. Their losses cannot establish
legal understanding or satisfy the separate feature-training requirement for
verified semantic embeddings. The constituent legacy training representations
have not all been independently verified. See the
[architecture comparison](legal_architecture_comparison.md) for that lineage
and its limitations.

The learned model returns reconstructed vectors and feature/view scores. It
does not generate legal formulas or reconstructed legal text. Every row keeps:

- Raw-decoder embedding, cosine similarity, and reconstruction loss.
- A separately labeled, target-conditioned safety-projected observation.
- The deterministic source compiler's result and decompiled text.
- Source identity, checkpoint identity, producer provenance, bridge telemetry,
  and execution timings.

The compiler result belongs to the compiler. Empty `autoencoder_text` remains
empty. Vector reconstruction scores remain nested observations; they do not
populate text-reconstruction quality columns. Sample-preparation errors retain
their compiler evidence without claiming that learned inference ran.

There is no optimizer or weight publication in this path. No model weights are
downloaded. Checkpoints are immutable local inputs. No Lake command runs, and
`admitted`, `formalized`, and `semantic_qualified` remain false. Constitution
inputs are explicitly unsupported and must not receive `roundtrip_ok`.

## Recovering the actual source spans

The dataset's `autoformal/uscode/resume-checkpoint.parquet` is a progress ledger.
It has source IDs and hashes, but no source-text column. Its metadata, board,
agent, seal, and summary rows are not legal sentences. The initial metadata
inspection at Hub revision `cce42e5021226c6ec70706bbb69b4c4a2268f2c2` found
443,905 total ledger rows: 443,904 span identities and one metadata row. Those
are intake targets, not a count of successfully processed spans.

[`legacy_span_intake.py`](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/legacy_span_intake.py)
resolves source text as follows:

1. Download only the bounded progress parquet at its resolved immutable Hub
   revision; verify its exact hash and byte count.
2. Read the already-local `justicedao/ipfs_uscode` source parquet at revision
   `5016b86a273ce5e4ffd066c5ae9f5fe494dd417e`. Its expected file hash is
   `4d26df1e3814279e4b4df3af0e454b4f64fc89a81879db926989862b6ad7d8b8`.
3. Regenerate source spans with the existing inventory's citation, release,
   sentence-splitting, and identifier rules. Reproduce the pinned ledger's
   historical calls of 64 valid source documents: sentence ordinals accumulate
   across those documents and restart at the next historical group.
4. Require exact agreement on `source_span_id`, source-text SHA-256, and legal ID.
   Unlisted sentences and conflicting source identities remain unmatched.
5. Transactionally enqueue matched sources and advance the section cursor in
   the owner's DuckDB queue. Replaying a section does not duplicate work.

The original source contains 60,077 section rows. Neither those sections nor
the progress ledger should be treated as an assertion that all federal law is
formalized. The four census bundles present during initial inspection contain
only a small observed subset and cannot replace this full-ledger source join.

The historical 64-document identity groups are independent of current intake
batch size. Resume replays the source prefix's sentence counts before emitting
new rows. The row provenance records
`identity_reconstruction=historical-64-document-ordinal/v1`, historical group
size, group index, and span ordinal. Upgrading an earlier per-section-ordinal
intake resets its section cursor and replays the source while preserving the
queue's completed identities. Multiple original documents can share a legal ID
and source-text hash; each must still match its own source CID and regenerated
span ID. An apparently unmatched legal ID may belong to a later source row.

The queue never imports a remote `sealed`, `roundtrip_ok`, `admitted`, claim, or
completion flag as local authority. Source text is not truncated to reproduce
historical cache behavior. A missing or mismatched source stays visible as a
gap. `intake-coverage.json` reports source hydration within the current temporary
index's lifetime; durable work counters, not this temporary index, establish
campaign progress across restarts.

## Processes and hardware

One owner serializes its DuckDB queue. One persistent CUDA worker loads the
legacy model once; a separate CPU process pool compiles source spans. Workers
do not open the queue file. The owner prefetches at most one additional batch:
its CPU compilation overlaps the current batch's CUDA evaluation. The receipt's
`cpu_cuda_overlap` field records whether that prefetch occurred; it is not a
measurement of GPU utilization. The code uses the canonical
`external/ipfs_datasets` tree and rejects compiler/parser import drift.

The current interface accepts 1–8 compiler workers and batches of 1–32 spans.
`--bridge-workers` independently selects 1–8 target-preparation threads within
the resident model and defaults to 1. A value of 4 is a candidate configuration
to measure after the baseline; it is not an established faster configuration.
Those are requested limits, not evidence that every configuration fits or runs
faster. Host memory, CPU/process slots, storage, and observed CUDA headroom must
be admitted first. The CUDA worker reports actual kernel execution on its
initial evaluated batch and rejects CPU fallback. GPU telemetry does not make
the parser, target preparation, or compiler GPU operations.

The queue uses one DuckDB thread, a 1 GiB memory limit, and at most 128 MiB of
temporary spill space beneath the charged runtime directory. The resident
worker configures a 2 GiB PyTorch CUDA allocator budget and requires 2 GiB of
observed free-device safety headroom. This is a cooperative campaign limit,
not a reservation of the entire GPU or a quota on unrelated CUDA applications.

Complete spans longer than 16,000 characters are retained under
`deferred_input_bounds`; the runner does not shorten them. Each submitted model
batch stays within one MiB of UTF-8 source text. A deferred span is neither
completed inference nor an empty successful result.

Profile wall time per span and per bridge-on evaluation before raising worker
or batch limits. Keep the measured configuration explicit:

| Setting | Value |
| --- | --- |
| Bridge names | `modal_frame_logic`, `deontic_norms`, `fol_tdfol`, `cec_dcec`, `external_prover_router` |
| External prover evaluation | `False` |
| Legal-IR bridge workers per evaluation | `--bridge-workers`, default `1` |
| Threads inside each bridge adapter | `IPFS_DATASETS_LEGAL_IR_ADAPTER_WORKERS=1` |
| Native target timeout | `IPFS_DATASETS_LEGAL_IR_TARGET_TIMEOUT_SECONDS=0`, explicitly disabled |
| Disk metric cache | `IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE=0` |
| Sample memory | Disabled |
| Raw reconstruction objective | `raw_decoder` |
| Temperature | `0` |
| Model updates | None |

`HF_HUB_OFFLINE=0` keeps dataset metadata and publication available while
`TRANSFORMERS_OFFLINE=1` keeps model resolution offline. No model resolver or
weight-download path runs in this campaign. Set both explicitly: the Hub client
can otherwise inherit the Transformers offline setting and silently disable
dataset publication.

The model process persists, so in-process caches can be warm even with disk
caching disabled. Receipts explicitly disclose this distinction. A zero-target
batch or a requested device string alone does not demonstrate bridge-on CUDA
inference. Record requested span count, actual sample count, preparation errors,
target count, kernel evidence, and complete batch wall time.

## Smoke continuous execution and resume

Inspect the CLI without starting work:

```bash
cd /home/barberb/lift_coding/external/ipfs_datasets
PYTHONPATH="$PWD" PYTHONDONTWRITEBYTECODE=1 \
  python3 -B scripts/ops/legal_ir/run_legacy_span_cuda.py --help
```

Choose a new runtime directory beneath the existing resource ledger's admitted
roots. `/CHARGED/legacy-span-cuda` below is a placeholder, not a created or
validated directory. The default checkpoint and source parquet must already
exist and match their required hashes. The example budgets also require actual
admission; they are not a promise of available headroom.

Run a two-batch local smoke first so that the second batch can exercise CPU
prefetch. This fetches dataset progress metadata and the progress parquet; it
does not upload results or fetch weights:

```bash
python3 -B scripts/ops/legal_ir/run_legacy_span_cuda.py \
  --runtime-directory /CHARGED/legacy-span-cuda \
  --scheduler-state /ABSOLUTE/existing-native-scheduler.json \
  --expected-policy-sha256 CURRENT_POLICY_SHA256 \
  --compiler-workers 2 --bridge-workers 1 --batch-size 4 --max-batches 2 \
  --storage-bytes 750000000 --memory-mb 12288 \
  --agent-id legacy-cuda-census
```

Inspect `cuda-ready.json`, `status.json`, resource telemetry, and the batch
receipt. Confirm exact checkpoint and source identity, actual CUDA kernels,
nonzero targets for evaluated samples, retained compiler results, and false
qualification/admission flags. A mock-vector diagnostic smoke is not a
semantic-embedding quality experiment.

After validation, restart with the same runtime directory and agent identity,
omit the batch limit, and enable immutable census publication if desired:

```bash
python3 -B scripts/ops/legal_ir/run_legacy_span_cuda.py \
  --runtime-directory /CHARGED/legacy-span-cuda \
  --scheduler-state /ABSOLUTE/existing-native-scheduler.json \
  --expected-policy-sha256 CURRENT_POLICY_SHA256 \
  --compiler-workers 4 --bridge-workers 1 --batch-size 8 --max-batches 0 \
  --poll-seconds 300 --storage-bytes 750000000 --memory-mb 12288 \
  --agent-id legacy-cuda-census --upload
```

`--max-batches 0` removes the campaign-wide batch limit. There is no overall
campaign deadline. Resource limits, input bounds, provenance checks, and bounded
network requests still apply. The process polls for a changed progress artifact
after draining its current source inventory; newly observed source identities
are enqueued without reopening completed work.

For unattended operation, install a user systemd service around the **outer**
CLI. The internal `--_engine` entry bypasses owner setup and is not a public
launch command. A deployment should set `Restart=on-failure`, an explicit
restart delay, no `RuntimeMaxSec` limit, the canonical working directory, and
the exact admitted runtime/budgets. Use the same unit and runtime on restart;
the owner lock prevents a second campaign owner. A failed provenance check or
insufficient capacity remains a failed/deferred run despite automatic restarts.

The deployed service name and actual command belong in the smoke/deployment
receipt. Once installed, use those exact identities:

```bash
systemctl --user status UNIT_NAME.service
journalctl --user -u UNIT_NAME.service -f
systemctl --user stop UNIT_NAME.service
systemctl --user start UNIT_NAME.service
```

Stopping and restarting is resumable. Work interrupted before a durable receipt
returns to pending. A retained receipt must match its complete queued source,
batch ID, checkpoint, mode, and authority flags before recovery can stage it.
On explicit shutdown, the outer owner uses the existing native, birth-checked
process-group cleanup, including descendants whose leader has already exited.
It sends SIGTERM followed by bounded SIGKILL escalation and reaping when needed.
These existing native cleanup bounds apply only to shutdown; they are not a
deadline on productive campaign execution. A prefetched batch interrupted during shutdown resumes
through the same queue recovery path.
Do not edit the queue or copy an open DuckDB file to resume on another host.

## Publication and interpreting repair work

New batches publish census **v3** under `autoformal/uscode/census-v3/`.
Raw learned decoder vectors, target-conditioned projected vectors, compiler
rules and component outcomes, and source-derived bridge documents have
separate explicit columns. Targets are prepared once and the same objects are
used for both evaluation and artifact capture. A recorded bridge document is
not a learned formula or proof. `logic_target_artifact_count` and
`compiler_rule_count` in live batch metrics report what was actually retained.

Goals remain deferred v2 handoffs. They bind the full source and census hash,
include bounded inline output context, and provide verified retrieval keys for
larger artifacts. Export does not enqueue or execute supervisor tasks. Existing
v2 census bundles remain readable without rewriting their hashes or source
evidence. See [output access and historical indexing](span_exchange_outputs.md)
for dataset configurations, field meanings, and backfill commands that require
no inference or checkpoint download.

The existing exchange outbox stages content-addressed census and deferred goal
parquets plus their manifest before the queue marks a batch completed. Publication
appends immutable artifacts to `justicedao/uscode-autoformal-span-cache` and
retains the successful Hub commit identity. A failed upload remains retryable
without repeating CUDA work. No local supervisor is opened or instructed to
execute a dataset-supplied task.

Use publication-only mode to retry a retained outbox and verified cleanup
without loading the model, preparing new source inputs, or invoking CUDA:

```bash
python3 -B scripts/ops/legal_ir/run_legacy_span_cuda.py \
  --runtime-directory /CHARGED/legacy-span-cuda \
  --scheduler-state /ABSOLUTE/existing-native-scheduler.json \
  --expected-policy-sha256 CURRENT_POLICY_SHA256 \
  --agent-id legacy-cuda-census --publish-only --upload \
  --storage-bytes 750000000 --memory-mb 12288
```

Stop the existing owner first and keep its runtime, checkpoint path, and agent
identity. This mode uses the same resource admission and ownership checks. It
returns a failure status if staged uploads cannot advance; rerunning it retries
the durable outbox without repeating inference. A successful delivery does not
grant authority to the observations or deferred goals.

The campaign shares Hugging Face rate limits with other processes using the
same account or network. HTTP 429 from a publication request records a durable
`publication_retry_after` epoch in the queue and `status.json`. A numeric
`Retry-After` sets the cooldown within 60–3,600 seconds; an absent or unusable
value defaults to 300 seconds. During that window publication attempts
skip Hub requests, including after an owner restart. Retained staged batches
stay local and retryable. Check the recorded deadline before repeatedly
restarting publication-only mode; restarts do not provide additional quota.
An upload attempt, including a completed blob transfer, is not a successful
dataset publication until the immutable commit receipt has been retained.

After publication,
[`legacy_span_publication.py`](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/legacy_span_publication.py)
verifies the manifest, census, and goals at the exact immutable Hub commit,
including remote blob hashes and byte counts. It also verifies that the census
preserves every recorded source observation and the complete raw evaluation.
Only then does it durably journal cleanup and unlink exactly five local files:
the batch JSON receipt, census parquet, goals parquet, manifest, and local
publication receipt. Interrupted cleanup resumes from that journal. The queue
keeps compact source identities for deduplication and the remote publication
evidence; already-processed spans are not trained or inferred again merely
because their local payload copies were evicted.
Payload compaction also retries batches already marked evicted, covering a
crash between artifact cleanup and queue compaction. Unpublished or merely
verified-but-not-evicted batches keep their complete local payloads.

At 75% of the admitted runtime storage allowance, the runner stops taking new
work and reports `waiting_for_verified_publication_storage`. It continues
publication and verified cleanup attempts. Unpublished evidence is retained;
an offline campaign without publication cannot process indefinitely within a
finite allowance. Compare retained bytes per span with that allowance, and
never advance a cursor without durable enqueue or delete pending outbox files
to make the storage counter smaller.

There are two distinct reasons for a deferred goal. A source compiler gap can
suggest a parser/compiler/decompiler repair supported by that source. A missing
learned text output reflects the legacy architecture's absent text decoder.
The existing census format records the latter as `inference_still_failing` with
`learned_text_unavailable`. Successful vector reconstruction does not resolve
that capability gap, and identical capability requests should not be counted
as independent compiler failures or blindly executed as per-span training jobs.

Use the complete retained observations to design the next compiler/decompiler
experiments. A compiled rule, a decoded sentence, a census row, a vector score,
or a syntax check does not replace actual source-locked `lake build <Lib>`
admission. This campaign does not run that admission path.


## September 30 deployment and measured evidence

The installed user service is `legacy-cuda-span-census.service`, from
[the versioned unit](../../configs/autoencoders/legacy-cuda-span-census.service).
It runs one resident legacy CUDA model, four CPU compiler workers, one native
bridge-target worker, and batches of up to 32 spans. Compilation of the next
batch overlaps evaluation of the current batch. Both the campaign deadline and
native target timeout are disabled; the unit uses `RuntimeMaxSec=infinity` and
`Restart=on-failure`. Operator shutdown has bounded cleanup and is resumable.

The runtime is:

```text
/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/federal-corpus-audits/legacy-cuda-campaign-20260930/runtime
```

Inspect `status.json`, `owner.json`, `cuda-ready.json`, and
`resource-status.json`. `status.json` retains the latest compact bridge/timing
observation after uploaded batch files are evicted. The DuckDB owner preserves
publication commits, verified remote hashes, cleanup journals, source identities,
and retry counts. Interrupted work is retried before fresh intake; completed
identities are not run again when the cursor is replayed.

The measured runs used all five bridge names in the configuration table,
provers disabled, disk metric caching disabled, and sample memory disabled.
The initial two-span observation started with an empty native target cache:
8.030 seconds per bridge-on evaluation and 5.399 seconds per span including
CPU compilation and worker dispatch (10.798 seconds for the batch). It observed
158 CUDA kernel events and two real bridge targets.

A subsequent 32-span smoke completed in 60.486 seconds, or 1.890 seconds per
span. The first continuous 32-span batch measured 58.977 seconds for bridge-on
evaluation and 71.886 seconds including compilation/dispatch, or 2.246 seconds
per span. That batch observed 32 bridge targets, 1,936 CUDA kernel events, zero
native timeout fallbacks, and one independent compiler text roundtrip. No Lake
admission was run or granted. CPU/native target preparation dominated these
observations; CUDA device time was only a few milliseconds.

Four target threads were also exercised successfully on two eight-span batches
(18.299 and 12.020 seconds per bridge-on evaluation). These were different
sentences and cache states, so they do not establish a speedup or regression.
The deployed setting remains one target worker. Increasing concurrency needs
a matched-sample measurement and host admission; thread count alone does not
establish throughput.

The intake admits at most 32,768 regenerated candidate spans or 64 MiB of
candidate records per 16-section chunk, within the 12 GiB host reservation.
The source parquet has one 1.17 GB decoded row group, so its explicit metadata
bound is 2 GiB; Arrow still streams bounded section batches. Model input limits
remain 16,000 characters per span and one MiB per model batch. The source's nine
trailing metadata rows with missing CIDs are skipped before validating text;
a valid-CID row with missing text remains an error.

Seven immutable Hub commits had been verified after 98 observations, including
[this census publication](https://huggingface.co/datasets/justicedao/uscode-autoformal-span-cache/commit/54df3d138d8bb594522c8e7fa01e9febb1111674).
The prior 66 observations remained intact across the service startup; a later
controlled reader update preserved 98 completions and requeued interrupted
work. HTTP 429 responses were observed and delivery succeeded after backoff.
These counts are dated smoke evidence, not a live corpus-completion claim.

The focused implementation suite passed 103 tests; the three required compiler
semantic gates and five selected historical pilot tests also passed. Protected
legacy and restart12 checkpoint digests were unchanged. Evidence binds the exact
working-tree producer digest rather than inferring source identity from Git HEAD.
See the [deployment receipt](../implementation/reports/evidence/legacy-cuda-campaign-20260930/deployment.json),
[measurements](../implementation/reports/evidence/legacy-cuda-campaign-20260930/smoke-measurements.json),
and [verified publications](../implementation/reports/evidence/legacy-cuda-campaign-20260930/verified-publications.json).


## Explicit existing scheduler binding and owner-gated engine launch

The outer CLI now requires paired `--scheduler-state` and
`--expected-policy-sha256` identities. It opens only the exact existing native
policy before runtime directory creation, owner locks or ledger access. The
library's `LegacySpanCampaignResources` constructor likewise requires paired
`scheduler_state_path` and `expected_scheduler_policy_sha256` keywords.
The subsequent `DaemonResourceReservation` uses these same scalar identities
and `require_existing_ledger=True`; policy drift before entry refuses before
a new disk claim is written. No process-global facade is installed. Argument
parsing and `--help` remain available without reserving anything, but omitted
or partial bindings cannot launch a real campaign, including publication-only
mode or the hidden engine entry.

The parent attaches the actual isolated engine child, records its PID and birth
in the native disk row, and binds a closed launch envelope to that same row.
It sends public lease/reservation identities, actual parent and child births,
root identities, the exact parsed CLI digest and resource envelope through a
bounded stdin barrier. No lease key is sent. Before opening the cache or
starting CUDA/pools, the engine joins that envelope to its currently live
native parent lease, native disk reservation, root/runtime identities and
actual Linux process relationship. A matching policy hash alone cannot start
an engine. The engine rechecks this custody at work-dispatch boundaries;
the external owner continues monitoring the process group and storage. The
60-second startup barrier bounds owner handoff only; productive inference
still has no campaign-wide deadline. Private controller tests use explicit
fixtures and do not run CUDA, legal inference or Lean admission.

The existing unit file records the historical deployment. Keep it and all
prior attempts unchanged. The reviewed optional successor drop-in is
[legacy-cuda-span-census-existing-policy.conf](../../configs/autoencoders/legacy-cuda-span-census-existing-policy.conf).
It explicitly binds the externally observed 24-field policy `f07cb142…`, with
one compiler worker, one bridge worker, CPU 3, RAM 8192MiB and five child-process
slots. The original runtime, agent identity, paired/guided diagnostic outputs,
publication, `max-batches 0`, temperature 0 and lack of an overall runtime limit
are preserved. This is a deployment candidate, not an assertion that these
budgets or CUDA execution have been admitted. The observed policy permits 16
CPU slots, 16 process slots and 99688MiB host memory, reserves validation CPU 2
and 24922MiB proof headroom. That policy was changed externally; this repair did
not apply the earlier proposed four-to-eight-slot expansion. Its current source
producer and exact digest must be explicitly reconciled and revalidated before
any real deployment. No prior scheduler state is restored, and this client does
not initialize, normalize or reconfigure the current policy.

A 4096MiB host request can pass basic CPU/process arithmetic but still leave no
buffer headroom because legacy batch planning reserves at least 4096MiB for
resident work. The candidate 8192MiB allowance leaves room for those buffers
and also fits the older 9830MiB host budget; the explicitly observed current
policy and actual hardware observations still govern admission. Native
reservations still decide admission. Change worker counts only with matched
wall-time/target-count observations, retaining the bridge/prover/cache fields.

Before adoption, stop the old failing restart loop and verify it has no live
owner or descendants. Preserve the old service definition, runtime, weights,
spans, retry counters, completed batches and budgets. After authenticating the
current external policy and compatible canonical
native producer, explicitly bind the new drop-in and fresh acceptance/source
contexts to that observed policy. Install the drop-in as a separate
`20-existing-native-policy.conf` beneath the user unit's drop-in directory,
then reload systemd and inspect the effective command before deciding whether
the genuinely admitted diagnostic campaign may resume. Do not start the old
deleted source-preparation generation or rewrite its historical receipts.

The October 14 metadata audit found `next_sequence=2` and one acquisition/release
in the shared scheduler, versus a larger earlier retained state file. The old
unpinned native constructor can reset idle state on configuration mismatch.
This explains a plausible reset mechanism, but the audit did not authenticate
which external process replaced/reset the state. No prior scheduler state is
reconstructed from those observations. The repair prevents this client's
implicit configuration path; independently running legacy clients still need
explicit owner review before their own shared-policy migration.


### Fresh bytecode, scoped producer pins and one startup deadline

The v2 launch adds a new empty 0700 bytecode-prefix directory for each engine,
created inside the already admitted runtime. The child receives
`PYTHONPYCACHEPREFIX` pointing to that directory and retains Python `-B`/
`PYTHONDONTWRITEBYTECODE=1`. The verifier checks its actual
`sys.pycache_prefix`, `sys.dont_write_bytecode`, directory identity and continued
emptiness before cache/pool execution and at dispatch boundaries. This prevents
reuse of a previous engine's standard Python bytecode cache. Declared controller,
resource, package and metadata-helper source hashes and loaded producer origins
must match the exact same source tree before the native launch is accepted.
The real CLI still requires the workspace compiler/decompiler/parser tree.
No HACC import aliases, module-cache removal or source retargeting are used.

These pins cover 16 declared source files, not the entire Python environment,
interpreter binary, third-party import hooks or checkpoint authenticity. They
observe current source bytes; they do not independently attest the parent's
already loaded bytecode. The later legacy model's full canonical source snapshot
and checkpoint checks continue to apply. Private metadata/control fixtures can
run in an isolated source tree and grant no semantic or Lean admission.

The same 60-second parent startup deadline starts immediately before Popen.
It is checked after spawn, after the required native child attach/census and
launch binding, before and after each heartbeat/resource check, and before
accepting the engine's exact handoff receipt. The child also bounds its stdin
wait to 60 seconds. A slow full native inventory remains a genuine startup
refusal; no census is skipped and no deadline/context cap is increased.
The owner accepts only a receipt tied to this exact child and launch hash,
checks the deadline again after reading it, and preserves each ready receipt
beside that launch's unique bytecode directory. A stale prior receipt cannot
stand in for the current child. Receipt transport is an engineering observation,
not a model result, proof, independent operational grant or Lake admission.

The earlier idle audit at 10:47 UTC observed the old 19-field policy. At 11:10 UTC,
a read-only observation found the external 24-field `f07cb142…` policy with
`next_sequence=51`; no leases or waiters were then observed. Those timestamps
and local observations do not identify or authorize the external policy change.
Do not reconstitute missing/reset scheduler history from either snapshot.
A later active peer lease remains owned by that peer and must not be stopped,
recovered or reconfigured merely to resume this campaign.


Source, startup and execution failures use the existing native reservation exit
path to retain their full disk claim and failure type instead of asserting
successful artifact durability. Native group cleanup runs even after the engine
leader exits; a live descendant prevents accepting a successful return. After
cleanup, the native owner decides whether its lease can be released. No peer
lease, prior claim, task history or storage cap is modified by that recovery.
Successful and explicitly stopped runs still require native strict finalization
with a stopped process group, durable artifacts and fresh accounting.


### Retained runtime storage headroom

The reviewed successor drop-in reserves 1000000000 bytes for the same retained
runtime. An October 14 read-only footprint observation found 613748056 bytes:
that exceeds the previous 750000000-byte reservation's 75% intake threshold
(562500000 bytes), so the old command can admit a process yet defer all new
intake for verified publication cleanup. The successor's 75% threshold is
750000000 bytes, leaving about 136.25MB before that intake threshold at the
observed footprint. The campaign's hard allowance rises by 250MB; the shared
145000000000-byte cap and all prior full claims remain unchanged. A fresh native
accounting/admission check is required before each real run. This is no promise
of unlimited storage: successful remote hash verification and native cleanup
still govern eviction, and failed/unpublished work remains retained.

The cached source parquet and local legacy checkpoint must retain their exact
required hashes. Runner/source-guard edits are recorded per observation and do
not change the existing campaign identity: checkpoint path, fixed source hash,
diagnostic representation and agent identity are unchanged. A root-owned native
read must verify the actual queue identity before resuming; status JSON and
filesystem hashes alone do not prove that logical database identity or progress.


The successor is an explicitly observed trial and sets `Restart=no`. The original
unit's recovery policy stays unchanged underneath the separate drop-in, and
`max-batches 0` plus the lack of a productive deadline still allow an admitted,
healthy owner to continue. Automatic failure restarts are held because each
failed native attempt retains its full 1GB claim; three uncontrolled retries
would consume most of the approximately 4.12GB headroom in the preceding native
accounting observation. Confirm actual custody, CUDA execution, a completed
batch and publication behavior before deliberately enabling any bounded
recovery policy. Do not release old failed claims to manufacture headroom.
