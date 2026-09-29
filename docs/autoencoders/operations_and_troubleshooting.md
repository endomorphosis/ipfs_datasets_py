# Operations and troubleshooting

Use this page with [legal training](legal_training.md), the
[native feature quickstart](native_feature_quickstart.md), and
[control-plane synchronization](control_plane_and_sync.md). Operational success,
feature improvement, and modality qualification have separate receipts. A
DuckDB row, published artifact, successful compile, reconstruction metric, or
decompiled sentence does not constitute Lean admission.

The source baseline for these instructions is published commit
`3666ebad19422b8345ebe5432a1c02f26d2eba4c`. A dirty checkout may contain unrelated
work; validate the exact source generation used by a run rather than assuming
that its live files equal `origin/main`.

## Read-only preflight

Start in the canonical source tree. A bare import elsewhere can resolve the
editable HACC installation, which is a different parser/compiler tree.

```bash
cd /home/barberb/lift_coding/external/ipfs_datasets
export PYTHONPATH="$PWD"
export PYTHONDONTWRITEBYTECODE=1
git rev-parse origin/main
git status --short
python3 -B - <<'PY'
from pathlib import Path
import ipfs_datasets_py
from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
print(Path(ipfs_datasets_py.__file__).resolve())
print(require_workspace_logic_tree())
PY
python3 -B scripts/ops/legal_ir/prepare_shared_autoencoder_targets.py --help
python3 -B scripts/ops/legal_ir/run_distributed_autoencoders.py owner --help
python3 -B scripts/ops/legal_ir/run_distributed_autoencoders.py worker --help
```

Do not edit HACC or `hallucinate_app` to make an incorrect import appear aligned.
Keep temperature zero, the existing context limit, and installed local model
weights. The workflow does not require Mathlib or downloading pretrained weights.
Exchanging our explicitly published campaign weights is a separate, authorized
artifact-transfer operation.

For prepared legal rows, the shared-target CLI has a read-only planning mode:

```bash
python3 -B scripts/ops/legal_ir/prepare_shared_autoencoder_targets.py \
  --input-jsonl /LOCAL/training.jsonl \
  --validation-jsonl /LOCAL/tuning.jsonl \
  --output-directory /CHARGED/new-target-preparation \
  --plan
```

`--plan` reads and validates inputs and reports configuration; it does not
reserve resources or produce targets. Actual preparation requires storage,
runtime bounds, and the selected source generation. Use
`--require-complete-targets` for a training handoff that must reject partial,
timed-out, rejected, or missing bridge supervision. Do not replace verified
embeddings with deterministic test vectors to make a production run start.

## Storage accounting

On **2026-09-29 at 23:40 UTC**, the published resource module defined
`MAX_STORAGE_BYTES = 90_000_000_000`, and the existing campaign ledger's
`limit_bytes` independently contained that same value. The observed ledger
had 278 reservation records. These are observations, not a forecast of free
space. The read ledger's SHA-256 was
`ed3d4c004e031da8c326faa5101cc3c82225e5ca13d644d84bddfefb7aaae4c0`.
The distributed CLI's per-role storage bounds remain at most
`50_000_000_000` bytes. Decimal GB and binary GiB differ.

Read the current cap and retained claim inventory without opening the registry
or changing reservations:

```bash
python3 -B - <<'PY'
from collections import Counter
import json
from pathlib import Path

path = Path("workspace/test-logs/federal-corpus-audits/owned-daemon-resource-control/disk-reservations.json")
ledger = json.loads(path.read_bytes())
rows = list(ledger["reservations"].values())
print({"limit_bytes": ledger["limit_bytes"],
       "reservation_count": len(rows),
       "statuses": dict(Counter(row["status"] for row in rows)),
       "outstanding_full_reservations_bytes": sum(row["storage_bytes"] for row in rows
                                                  if row["status"] != "released")})
PY
df -B1 /home/barberb/lift_coding/external/ipfs_datasets
```

This inspection does **not** calculate fresh headroom. Admission performs a
fresh named-root census under the resource ledger lock:

```text
charged bytes = observed apparent bytes + all outstanding full reservations
                + the new requested reservation
```

Filesystem free bytes must also cover outstanding reservations plus the new
request. Existing outputs remain counted after a claim is released; releasing
the reservation does not delete its artifacts. A free disk can still have no
campaign headroom, and a large campaign cap does not guarantee filesystem
capacity.

[`DaemonResourceReservation`](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_resources.py)
also acquires scheduler CPU, memory, and child-process capacity. These are
cooperative admission and polled usage limits, not kernel filesystem quotas.
Allocate for the owner, each outer worker, nested jobs, target preparation,
source capsules, local complete generations, patches, and evidence. Count
retained generations and failed/stale candidates when sizing a long run.

Changing a CLI `--storage-bytes` increases that attempt's request; it does not
migrate the campaign ledger's cap. A cap migration must update the source
policy and matching ledger limit explicitly under the lock while preserving
roots and unrelated reservation records. Reading an older ledger never upgrades
it automatically. Do not expire old claims by age or remove retained evidence
to make a capacity check pass.

For normal closeout, require stopped child process groups, durable artifacts,
successful final accounting, and `status=released`. Check
`attempt_exceeded_reservation`, not just a training-completed flag. The
[documented retry](../implementation/reports/AUTOENCODER_DISTRIBUTED_FEATURES_RETRY_20260929.md)
raised outer workers to 400 MB because a preceding 180 MB allocation was too
small after synchronization and cleanup.

[`reconcile_retained_reservation()`](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_resource_recovery.py)
is an explicit administrative closeout for one dead owner's retained claim.
It requires the exact prior record hash, matching attempt directory identity,
verified durable artifact inventory, absent owner PID, dead recorded child
groups, and no unsupported external charges. It preserves other claims and
outputs. It is not a routine retry or an automatic cleanup daemon.

## Source consistency and frozen runs

The source guards intentionally reject producer changes. Coordinate source
integration outside an active run, then capture a complete chosen generation
and prepare targets against that generation. Do not remove provenance guards,
copy individual files into an active producer, or substitute an old target
snapshot after a parser update.

The existing offline capsule CLI is
[`run_frozen_autoencoder_source.py`](../../scripts/ops/legal_ir/run_frozen_autoencoder_source.py):

```bash
python3 -B scripts/ops/legal_ir/run_frozen_autoencoder_source.py prepare --help
python3 -B scripts/ops/legal_ir/run_frozen_autoencoder_source.py run --help
```

`prepare` captures the current canonical source, optional declared extra Python
files, and source metadata under a bounded reservation. It does not mean
“export the latest remote commit”; select and verify the desired code first.
`run` requires the manifest and its SHA-256, an existing local Docker image,
explicit writable runtime directories, a resource ledger, a temporary
directory, and a timeout. Its implementation mounts the verified source
read-only at the canonical paths and uses `--pull=never`, a read-only container,
and **`--network=none`**.

Consequently this standard frozen runner is suitable for offline native
preparation/training checks; it does not enable the live Hub/remote Quack path.
There is no documented `--network` override in its CLI. The historical live
Hub retry used a separately reviewed transfer harness. Provision a verified
source deployment for online workers rather than inventing flags or silently
disabling the source checks.

## Failure diagnosis

| Symptom | Check and action | Evidence to retain |
| --- | --- | --- |
| `database already has an owner` or DuckDB lock error | Locate the existing owner and use its scoped Quack connection. Do not launch another owner over the same file or copy its live database. | Owner process identity, connection receipt, original error |
| Installed Quack/HTTP artifact unavailable or wrong hash | Match the pinned DuckDB version and existing local extension artifacts. An SSH tunnel cannot repair a codec or extension mismatch. | Extension/version diagnostic; no credentials |
| Worker and owner sources differ | Deploy the same selected source generation and dependencies, including JevOps and target provenance. Restart with the proper connection information; do not relax identity checks. | Source/capsule manifests and source mismatch report |
| Shared targets rejected after a merge | Reprepare against the selected source/runtime and exact input bytes. Keep the rejected bundle as evidence. | Target snapshot identity, preparation receipt, producer fingerprints |
| Embedding manifest invalid or missing | Provision verified local producer artifacts and exact records; check model revision/dimension and record bindings. Do not download replacement pretrained weights or use test vectors. | Embedding manifest/production receipt and mismatch diagnostic |
| `resource_capacity_unavailable` / `CapacityDeferred` | Separate storage accounting from scheduler RAM/CPU/process admission. Adjust admitted parallelism or budgets with a fresh census. | `worker-status.json` with `deferred=true`, resource receipt |
| Attempt exceeds storage after training | Include patches, full replayed parents, evidence, and retained jobs in the allocation. A completed optimizer is not clean closeout. | Final usage and `attempt_exceeded_reservation`; original failure |
| Worker cannot claim after pulling | The owner may have advanced while download/acknowledgment was in progress. Let the normal polling loop synchronize and reuse pending operation IDs. | `pending.json`, control journal, installed/current generation bindings |
| Candidate is stale | Keep the candidate and let the owner requeue from the current parent. Never add its postimages to the new model. | Candidate version, old parent, requeue/owner observation |
| Hub commit conflict or ambiguous response | Use the existing bounded publication retry and verify immutable remote references. Keep the staged artifact identity; do not rename content to force another update. | Manifest, immutable commit reference, transfer receipt |
| Resume downloads unexpectedly | Compare commit/hash/byte references, generation binding, and local `installed.json`; missing or changed parent materialization prevents cache reuse. | Download byte counts, cache-hit indication, full hash check |
| Feature target count is zero | Confirm legal bridge names actually ran and targets were complete. Bridge-off reconstruction timing is not IR timing. | `legal_ir_target_count`, `legal_ir_losses`, bridge telemetry |
| Feature update rejected | Inspect raw reconstruction objective, cosine, cross-entropy, each IR regression guard, and source/parent evidence. Repair inputs or optimizer behavior; do not loosen admission semantics. | Worker epoch reports and independent owner before/after evaluation |
| Native incremental batch rejected | Keep the fitted feature basis, exact contract, source split, and fixed tuning panel. Inspect unknown-atom coverage; a new basis or tuning panel requires a new model lane. | Feature-space digest, tuning digest, per-projection coverage |
| Native parent cannot resume/register | Check parameter shapes, finite values, Adam moments/steps, completed epochs, optimizer settings, and exact registered parent digest. Do not average states or relabel another modality. | State/contract digest and registry parent chain |
| Sparse ancestry/depth limit reached | Use the implemented full-parent compaction path and verified anchor identity. Do not increase recursion limits to hide unbounded history. | Anchor publication and exact materialization receipt |
| Feature run has no Lake receipt | Expected in feature mode: retain all qualification/admission flags false. Formalization requires its separate real Lake and modality checks. | Feature purpose, qualification gaps, optional later proof receipts |

## Metrics and a defensible completion receipt

Measure end-to-end cost by stage rather than inferring speed from one accepted
epoch. Record source/input identities, hardware/resource selection, sample
counts, and whether targets or caches were reused.

| Stage | Record |
| --- | --- |
| Parser/compiler front end | Wall time per span; separate `vocabulary_from_clause` parsing from compiler parsing when profiling the legal duplicate-parse path; compiled and abstained counts |
| Cold legal target preparation | Total wall time, wall time/span, target count, exact bridge names, per-target generation timing, timeout/partial statuses |
| Bridge-on evaluation | Wall time/call, sample count, nonzero target count, `legal_ir_losses`, IR cosine and cross-entropy; whether shared targets replaced generation |
| Modal optimizer | `elapsed_seconds`, `projection_profile`, `stopped_reason`, attempted/accepted epochs, line-search bounds, `legal_ir_view_cross_entropy_delta` in epoch reports |
| Native structural optimizer | Before/after objective and each projection's metrics, attempted/selected epochs, unknown-atom coverage, elapsed time and deadline reason; these are structural features, not semantic embedding quality |
| Arrow mapping | `mapped_numeric_bytes`, `overlay_rows`, materialization counters, private numeric bytes and process memory; the numeric byte estimate excludes Python overhead |
| Sparse persistence/transfer | Patch bytes versus full checkpoint bytes, closure depth, materialization/hash cost, downloaded bytes, cache hits, retained artifact growth |
| Campaign/cleanup | Selected generation and full artifact identity, acknowledged workers, retained stale jobs, child exit codes, final resource status and usage |

For the established legal comparison, list all five bridge names:
`modal_frame_logic`, `deontic_norms`, `fol_tdfol`, `cec_dcec`, and
`external_prover_router`. Record `legal_ir_evaluate_provers=false`,
`legal_ir_parallel_workers=1`, `IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE=0`,
`use_sample_memory=false`, and the exact sample count when those are the chosen
settings. A changed bridge list is a different measurement. Enabling external
provers or changing the numerical backend without a profile does not establish
an optimization. Shared-target evaluation is not cold compilation.

Use repeated tuning only as the optimizer's selection evidence, not a held-out
canary. For legal admission, preserve the actual `lake build <Lib>` result and
the required logic-family/semantic checks. A log mentioning a prover is not a
proof. Never mark a Constitution span `roundtrip_ok` or describe the Constitution
as formalized because a feature or transport test passed.

Before calling an end-to-end smoke complete, independently inspect native
training results, full-weight replay, owner selection, worker acknowledgments,
graceful child exits, and released owned resource claims. A resume smoke should
report new job counts and actual additional download bytes. If native training
used a Hub simulation and a later test used the real Hub, identify both phases
explicitly. Two local workers or two local consumer directories do not prove
deployment on two physical machines.
