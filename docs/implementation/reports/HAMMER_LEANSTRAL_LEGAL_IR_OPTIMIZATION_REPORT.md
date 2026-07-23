# Hammer/Leanstral LegalIR Optimization Report

Task: PORTAL-LIR-HAMMER-072

This report defines the production promotion contract for the evidence-driven
LegalIR optimizer rollout. Promotion is based on persisted benchmark, smoke,
hparam, canary, and production evidence. It is not based on operator judgment,
live process state, or generated patch counts without validation.

## Artifacts

- `benchmarks/bench_legal_ir_optimizer_pipeline.py` publishes matched cold/warm
  baseline and candidate evidence for the full CUDA/Hammer/Leanstral/Codex
  optimizer pipeline.
- `scripts/ops/legal_ir/hammer_leanstral_rollout_gate.py` gates individual
  Hammer/Leanstral summaries and the staged promotion manifest.
- `scripts/ops/legal_ir/run_hammer_leanstral_smoke.sh` verifies the integrated
  CUDA, Hammer, Leanstral, and Codex smoke path before longer runs.
- `scripts/ops/legal_ir/run_hammer_leanstral_hparam.sh` runs the fixed sequence:
  short smoke, one-hour resource-aware hparam search, eight-hour canary, and
  twenty-four-hour production.

## Benchmark Contract

The benchmark report publishes a matched cold/warm baseline and requires cold
and warm cache runs for every measured parallelism profile. It records
throughput, phase p50/p95, projection training latency, trainer duty cycle,
proof and reconstruction throughput, Leanstral batch efficiency,
CPU/GPU/memory/swap telemetry, queue lag, accepted Codex patches per hour,
transient failures, and hard quality metrics.

The deterministic dry-run path is schema-complete and demonstrates a selected
balanced profile with at least 40 percent lower projection p95 than the fixed
baseline while preserving quality and resource guardrails.

## Promotion Gates

The staged gate fails closed unless the manifest contains the exact stage
sequence:

- `short_smoke`: 10 minutes
- `one_hour_hparam`: 60 minutes
- `eight_hour_canary`: 8 hours
- `twenty_four_hour_production`: 24 hours

Every stage must provide complete promotion lineage, trusted-feedback delivery
to the autoencoder, full required Hammer coverage by LegalIR family, durable
rollback evidence, healthy queue telemetry, successful managed-process cleanup,
and no hard semantic, provenance, anti-copy, Hammer proof, Lean reconstruction,
process lifecycle, or queue-lag regression.

The final production stage must also prove:

- at least 40 percent lower projection p95,
- at least 20 percent better task-to-accepted-patch rate,
- at least 25 percent lower state-to-merged-patch lag.

## Lineage

Each staged snapshot records a rollout id, stage name, fixed baseline digest,
input digest, output digest, promotion revision, and producing tool. The gate
normalizes digest references as `sha256:<hex>` and rejects missing, malformed,
or stage-mismatched lineage before promotion.

## Validation

Primary validation commands:

```bash
/home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/optimizers/logic_theorem_optimizer/test_evidence_driven_rollout.py tests/unit/optimizers/logic_theorem_optimizer/test_parallel_pipeline_rollout_gate.py tests/unit/optimizers/logic_theorem_optimizer/test_hammer_rollout_gates.py -q
/home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python benchmarks/bench_legal_ir_optimizer_pipeline.py --dry-run
PYTHONPATH=/home/barberb/portland-laws.github.io/ipfs_accelerate_py:. /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -c "from pathlib import Path; from ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon import parse_task_file; tasks=parse_task_file(Path('docs/LEGAL_IR_HAMMER_LEANSTRAL_AGENT_TODOS.md')); ids={task.task_id for task in tasks}; assert len(tasks)>=72; assert all(task.acceptance and task.validation and task.outputs for task in tasks); assert all(dep in ids for task in tasks for dep in task.depends_on); print('parsed', len(tasks), 'tasks')"
```
