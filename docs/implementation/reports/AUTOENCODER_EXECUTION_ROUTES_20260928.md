# Separate autoencoder routes and adaptive parallel passes

Inference and training now cross an explicit execution gate in their production
paths. Inference evaluates immutable checkpoint bytes and verifies that the
model state is unchanged. It cannot invoke projection training, publish weights,
open the training registry, or switch a training state directory into inference.
Training uses a separate bounded projection gate and writes private candidates.
Its internal evaluations are part of optimization; they do not authorize an
inference request to train.

The execution gate is distinct from qualification. Cosine/reconstruction,
deterministic source round trip, six native logic syntax checks, disjoint tuning
validation and actual `lake build Legal` remain required. Only the source-locked
numeric theorem gets a Lake admit. An embedding, checkpoint, receipt or database
row does not. The Constitution remains unformalized.

## Local use

From the pinned `external/ipfs_datasets` tree, using existing resource roots:

```bash
PYTHONPATH="$PWD" python scripts/ops/legal_ir/run_incremental_autoencoders.py \
  --execution-mode inference \
  --state-directory /absolute/campaign/inference \
  --input-jsonl /absolute/campaign/spans.jsonl \
  --validation-jsonl /absolute/campaign/validation.jsonl \
  --workers 0 --max-batches 16
```

Inference inputs are local SampleRecord JSONL. It scores the current local
checkpoint and performs the same full pipeline qualification checks. A failed
result remains evidence; it does not secretly start an optimizer. Network input,
weight publication and training-only Arrow/target artifacts are rejected on this
route. Completed passes are sealed against exact checkpoint, source, validation
and receipt hashes; resume checks those bindings and the underlying proof files.
Machine sharding is deterministic. Interrupted unfinished passes require explicit
recovery and cannot masquerade as completed evidence.

Use `--execution-mode training` with a separate state directory to train. This
remains the default for the existing training command. Training still uses the
five configured legal-IR bridges, no external provers, sample memory disabled,
temperature zero and `python_sparse_batch`. The execution gate rejects invalid
routes, conflicting inference flags and unbounded direct training parameters.
No context window, qualification threshold or CUDA backend policy was changed.

## What scales

`--workers 0` now means a stable ceiling of 32 logical lanes, with the physical
dispatch width recomputed from hardware and resources. A fixed lane topology is
necessary for stable span placement and resume identity. Explicit values from
1 through 32 set that logical ceiling. Existing streams must retain their prior
explicit lane count; changed producer sources require a new campaign.

The planner considers CPU affinity, visible ancestor cgroup CPU/memory limits,
available RAM, the configured memory envelope, pending passes, scheduler lane
reservations and process slots. Fleet planning also includes storage headroom
with retained claims fully charged. Load average is reported as context, not
used as a hard quota. Resource estimates are advisory; atomic reservations
remain authoritative. Unknown or insufficient capacity can yield zero, which
defers work without inventing a successful training attempt.

The local supervisor rechecks resources at each cycle. Within its already
reserved CPU/memory envelope, the training runner rechecks before each dispatch.
It never subtracts the parent's reservation twice. With the default 8 GiB group
budget and a 512 MiB coordinator reserve, the current estimate allows at most
seven 1 GiB passes, further limited by actual hardware and queued work.

This scales **independent concurrent passes**, not optimization epochs. The
existing one-epoch/one-line-search job defaults remain; extra metric retries stay
inside `max_training_rounds`. More hardware does not loosen qualification or
turn a structural compiler failure into optimizer success.

## Multiple local campaign workers

The new fleet launcher runs bounded waves of preconfigured distributed workers:

```bash
PYTHONPATH="$PWD" python scripts/ops/legal_ir/run_autoencoder_fleet.py \
  --state-directory /absolute/campaign/fleet \
  --connection-file /private/host-a.json \
  --connection-file /private/host-b.json \
  --max-workers 0 --cycles 1 --plan
```

Remove `--plan` to run the wave. `--cycles 0` explicitly enables continuous
bounded waves. The planner reads the owner policy but does not claim work or
download weights. Each worker gets a private state directory and performs at
most one span attempt per invocation. Existing owner generation, lease,
qualification, sparse publication and complete-weight synchronization rules
remain in force. Worker identities must already exist in the owner policy;
the launcher does not silently add campaign participants.

Training worker planning charges 1 GiB/one CPU slot for outer coordination plus
the existing 8 GiB/one CPU inner training reservation. Synchronization-only
workers charge only the outer allowance. Without an explicit pending-job ceiling,
configured identities remain eligible for synchronization and empty queue polls.
This ensures a worker can receive the final weights after the work queue drains.

Fleet state preserves identity placement and rotates through available workers.
Private identity locks, PID birth checks, bounded logs/timeouts and owned-child
cleanup prevent overlapping attempts or killing unrelated processes on resume.
The owner remains the only writer of its DuckDB registry; workers use scoped
Quack control and independent local candidates. Epochs and gradients are not
silently merged across machines.

## Validation scope

Native inference and training ran concurrently on two synthetic numeric spans
each, using the protected restart12 checkpoint. Both routes selected two passes;
inference did not train, and two private optimizer candidates passed subsequent
qualification, including actual Lake builds. Mock stable-hash embeddings were
used, so this establishes pipeline behavior rather than federal-law model
generalization. Full evidence and resume results are retained in the
[evidence directory](evidence/autoencoder-execution-routes-20260928).

| Native route | Initial wall time | Selected parallel passes | Resume with one-core affinity | New passes on resume |
| --- | ---: | ---: | ---: | ---: |
| Inference | 30.63 s | 2 | 112.79 s, selected width 1 | 0 |
| Training | 48.07 s | 2 | 125.87 s, selected width 1 | 0 |

The two reduced-affinity resumes deliberately shared one CPU. Their wall times
include evidence verification and resource accounting; they are not a training
speed benchmark. The initial runs show overlapping active inference/training
worker processes and sampled CPU progress, not an observation of simultaneous
optimizer kernels. Inference created no training registry or candidate weights.
The original 25,895,338-byte checkpoint retained SHA-256
`1446cb1859ddf4ed40fb5576f6e320eece4cec268a008c5c07bffeaf959cd8dd`.

The two one-sample training jobs' first bridge-on evaluations took 5.168 and
5.431 seconds. Both had one legal-IR target and ran `modal_frame_logic`,
`deontic_norms`, `fol_tdfol`, `cec_dcec` and `external_prover_router`, with
provers false, disk cache disabled, one bridge worker and sample memory false.
Process caches began empty; subsequent in-process evaluations were warm.
Qualification's bridge-off embedding evaluations are not legal-IR timings.
Optimizer training wall time was 6.739 and 6.995 seconds per one-span job,
excluding process startup, qualification and resource accounting.

The readiness suite passed 409 tests; the final integration suite passed 121.
These overlap and are not summed as distinct tests. The fleet launcher has
functional and real Linux
subprocess lifecycle tests; a new live fleet campaign was not launched in this
smoke.

The native run uses captured workspace source hashes. Unrelated concurrent
parser/model edits are not silently bundled into the scoped publication. No
physical multi-host deployment or full-corpus throughput improvement is claimed.
The campaign cap remains 80 GB, historical reservations remain retained, and
the protected checkpoint is never overwritten.
