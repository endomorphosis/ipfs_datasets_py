# Shared-target handoff review

Read-only integration review, 2026-09-29. No producer or training process was
started by this review. Source files remain frozen.

## Supported durable path

`prepare_shared_autoencoder_targets.py` creates an immutable target bundle and
`receipt.json`. The existing durable `run_incremental_autoencoders.py` accepts
the receipt's `runner_arguments` (`--shared-targets PATH --target-snapshot-id ID`).
Its `run_cycle` passes them to `make_templates`, which stages the artifact into
the owning registry and includes its descriptor and identity in every job.
Each worker independently checks artifact bytes, full producer/configuration
binding, and the requested sample content, including supplied embeddings.

The new `training_job_fields` receipt object contains `target_snapshot_id` and
`target_snapshot_artifact`. A standalone worker can consume its original file
path. A registry-backed coordinator must first stage the bytes in the owner's
content-addressed artifact store and put that owner's path in each job. The
coordinator independently verifies artifact membership before starting workers;
an arbitrary existing producer path does not satisfy that requirement.

The following uses the actual `AutoencoderRegistry.stage_artifact` and
`artifact_path` APIs, with an already-open owning registry and otherwise valid
ordinary `job_fields`:

```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import TrainingJobSpec

target = receipt["training_job_fields"]["target_snapshot_artifact"]
staged = registry.stage_artifact(target["path"], target["sha256"])
if staged != {"sha256": target["sha256"], "bytes": target["bytes"]}:
    raise ValueError("shared-target artifact changed during owner staging")
owner_target_fields = {
    "target_snapshot_id": receipt["training_job_fields"]["target_snapshot_id"],
    "target_snapshot_artifact": {
        **staged,
        "path": str(registry.artifact_path(staged)),
    },
}
spec = TrainingJobSpec.from_dict({**job_fields, **owner_target_fields})
```

Stage once per owner and reuse these fields for its candidate jobs. The bytes,
hash, size and snapshot identity stay unchanged. Staging does not grant
admission or replace source/configuration/sample validation. The first root
smoke omitted staging and failed before worker execution with `RegistryError:
artifact is missing or unreadable`; its evidence was retained. R2 corrects the
workspace harness to perform this staging step. The durable incremental CLI
already performs it in `make_templates`.

Example preparation, from the canonical repository root, using the unchanged
six training and two tuning rows of this diagnostic (no canary rows):

```bash
/home/barberb/.local/bin/python scripts/ops/legal_ir/prepare_shared_autoencoder_targets.py \
  --input-jsonl workspace/test-logs/federal-corpus-audits/parallel-training-campaign-20260929T042818Z/verified-embeddings-r1/training.jsonl \
  --validation-jsonl workspace/test-logs/federal-corpus-audits/parallel-training-campaign-20260929T042818Z/verified-embeddings-r1/tuning.jsonl \
  --output-directory workspace/test-logs/federal-corpus-audits/shared-target-example-new \
  --max-output-bytes 33554432 --storage-bytes 100000000 \
  --memory-mb 8192 --timeout-seconds 600
```

This is an invocation example, not evidence it ran. An existing output directory
is refused; storage admission remains mandatory. Add `--plan` to inspect the
requested selection/configuration without producing targets or taking a lease.
The bundle cap is a bound, not a guarantee that these rows fit.

After successful preparation, the durable runner can consume its handoff
without any bespoke training implementation:

```python
import json
import subprocess
from pathlib import Path

root = Path("/home/barberb/lift_coding/external/ipfs_datasets")
receipt = json.loads((root / "workspace/test-logs/federal-corpus-audits/shared-target-example-new/receipt.json").read_text())
inputs = root / "workspace/test-logs/federal-corpus-audits/parallel-training-campaign-20260929T042818Z/verified-embeddings-r1"
seed = root / "workspace/test-logs/federal-corpus-audits/parallel-training-campaign-20260929T050700Z/fresh-gte-small-384.state.json"
command = [
    "/home/barberb/.local/bin/python", str(root / "scripts/ops/legal_ir/run_incremental_autoencoders.py"),
    "--state-directory", str(root / "workspace/test-logs/federal-corpus-audits/shared-target-runner-example-new"),
    "--execution-mode", "training", "--checkpoint", str(seed),
    "--input-jsonl", str(inputs / "training.jsonl"),
    "--validation-jsonl", str(inputs / "tuning.jsonl"),
    "--workers", "2", "--parallel-workers", "2",
    "--parallel-qualification-workers", "1", "--fresh-training-workers",
    "--max-batches", "1", "--max-training-rounds", "1", "--polls", "1",
    "--memory-mb", "24576", "--storage-bytes", "600000000",
    "--epochs", "2", "--line-search-attempts", "2", "--max-seconds", "180",
    *receipt["runner_arguments"],
]
# Review resource admission and the exact source/input binding before executing:
# subprocess.run(command, cwd=root, check=True)
```

The durable incremental runner dispatches one training span per job with the
same disjoint tuning set. This differs from the diagnostic sweep's six-row
training batches; these commands are not an equivalent speed comparison.
The local command omits dataset polling/publication and does not download
weights. All target settings remain five bridges, provers false, one IR worker,
metric disk cache zero and sample memory false. Only actual `lake build Legal`
on a supported generated Lean unit establishes its existing admission.

Preparing once does not make targets timeless: changes to sample text/vectors,
producer Python contents, installed dependency identity, ordered bridge names,
prover/worker settings or target timeout cause compatibility refusal. New rows
require a new covering artifact. Warm shared-target timings must include the
separate preparation cost before reporting end-to-end speed. Timeout fallbacks
are reused as timeout observations, not upgraded to conversions or proofs.

## Remaining distributed/fleet gap

`autoencoder_distributed_training.training_config` currently sets
`shared_targets=None` and `target_snapshot_id=None` explicitly.
`run_distributed_autoencoders.py` exposes no shared-target handoff options, and
`run_autoencoder_fleet.py` delegates to that distributed worker. Consequently
those paths do not consume this artifact today. Adding flags alone would be
insufficient: their owner policy must bind the target descriptor/configuration,
each worker must verify a locally staged artifact before claiming work, and
new census rows need an explicit artifact-version transition. This review
does not claim distributed sharing is implemented. Distributed workers also
synchronize/download weight generations, so they are outside this local
no-download validation invocation.

## Scoped publication

`shared-target-owned-diff.json` compares origin/main blobs directly to the
actual six working files, including files untracked by the older live HEAD.
Origin/main at review: `424ba3dda31279e30566a8668d698474375e10f5`.

Owned source changes: `autoencoder_target_preparation.py` (+16/-4),
`autoencoder_training_worker.py` (+18), `autoencoder_native_pool.py` (+3), and
`scripts/ops/legal_ir/prepare_shared_autoencoder_targets.py` (+5).

Owned tests: existing `test_prepare_shared_autoencoder_targets.py` (+4 lines
asserting the direct job-field handoff) and new
`test_parallel_shared_target_preparation.py` (147 lines, 7 test cases covering
mixed full/timeout payload equality, two candidate jobs without regeneration,
and five stale-binding refusals). Existing producer/worker/pool suites were run
unchanged. The two focused commands passed 39 and 238 cases, respectively,
with 27 overlapping preparation-CLI cases: **250 unique cases passed**.
