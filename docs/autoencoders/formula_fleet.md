# Formula decoder workers and checkpoint exchange

`run_formula_fleet.py` runs independent resumed training branches for
`legal_ir:source_conditioned_formula_v1` and the Intent, Security and UI/UX
`native_formula_v1` runtimes. Workers use scoped Quack commands to claim and
renew jobs. One owner opens DuckDB, validates their results, reruns the actual
decoded-output Lake schema gate, and records immutable model versions.

This profile is separate from the existing modal feature-training fleet. It
does not change its checkpoints, qualification policy, production service or
schema. No formula branch is automatically promoted to an inference head.
Native inputs remain compiler-prepared structures; legal inputs are source
text. Structural schema builds do not establish source semantics, full family
backend validity, or legal admission. The known legal exception-loss failure
remains unqualified.

## Prepare an explicit plan

First train/register a base candidate using the existing
[native training CLI](native_formula_training.md) or the learned legal runtime
interface. Each job names its exact registered parent; fresh model creation is
kept outside the resumed-worker path. The plan format is:

```json
{
  "schema": "autoencoder-formula-fleet/v1",
  "jobs": [{
    "job_id": "ui-branch-a",
    "domain": "ui_ux_ir",
    "runtime_version": "native_formula_v1",
    "parent_version_id": "sha256:<64 lowercase hex digits>",
    "corpus": "/absolute/path/corpus.json",
    "corpus_sha256": "<sha256 of exact corpus file bytes>",
    "epochs": 2,
    "max_seconds": 60,
    "lake_timeout_seconds": 30
  }]
}
```

Use the native corpus format `training_targets`, `tuning_targets`,
`projection_ids`; legal uses exactly `train`, `tuning`. Resume preserves the
parent's corpus manifests, vocabulary, dimensions, optimizer settings and
source identities. Changing the corpus is not an incremental resume under this
bounded fixed-vocabulary version. Keep held-out data outside these arrays.

Run from the canonical checkout in a fresh process:

```bash
PYTHONPATH="$PWD" python3 scripts/ops/autoencoder/run_formula_fleet.py run \
  --plan-file /absolute/path/plan.json \
  --registry /absolute/path/control.duckdb \
  --artifact-root /absolute/path/artifacts \
  --state-directory /absolute/path/fleet-state \
  --resource-ledger /absolute/path/existing-disk-reservations.json \
  --max-workers 4 --memory-budget-mb 8192 --plan-only
```

Remove `--plan-only` to execute. The registry, artifacts and state directory must
be under roots already declared by the resource ledger. The planner observes
hardware/cgroup capacity, host scheduler availability, storage headroom and the
caller ceiling. Actual resource reservations remain authoritative. Each worker
reserves 2 GiB, two CPU slots and three process slots, uses one Torch CPU thread,
and has its own storage allowance (default 750 MB). The owner reserves an
additional 1 GiB, one CPU slot and two process slots. CUDA and model downloads
are disabled in worker processes.

Jobs have a training deadline plus a separate bounded allowance for every Lake
check. CPU/RAM/disk policing is cooperative, not a kernel quota. The owner keeps
monitoring all live workers; it drains the wave before expensive owner replay
or upload, renews queued leases and then accepts branches serially. An overrun,
source change, changed input, failed schema build or corrupt sparse replay
prevents completion. Failed storage claims are retained for explicit recovery,
following the existing resource ledger policy.

## Resume and inspect

Rerun the identical plan against the same owner database. Completed jobs return
`already_completed` after verifying their registered candidate and do not train
again. Different job IDs create independent branches. Job identity also binds
the parent, corpus, settings and orchestration sources. A previous live owned
process prevents a restart from spawning a duplicate. Owner restarts fence old
leases; incomplete attempts receive fresh directories and preserve diagnostics.

Under `state/attempts/`, inspect `result.json`, `schema.json`, `worker.json`,
`owner-schema.json`, `owner-receipt.json`, both generated Lean project trees and
the `exchange/` manifest. `last-run.json` records progress. The worker's private
`token` file is a credential: it is never included in reports or upload bundles.
Only the owner can complete a job; workers cannot invoke generic `CompleteRun`
through this profile. The control-completion version is a receipt artifact;
`candidate_version_id` is the actual loadable model version.

## Exchange exact branches between machines

The [formula exchange codec](formula_checkpoint_exchange.md) supports full
anchors and parent-bound sparse postimages. It preserves latest weights,
selected weights, optimizer moments, cursor, model vocabulary and the complete
training report. Dense updates can be almost as large as full checkpoints;
inspect `payload_bytes` and `full_result_bytes`. This is exact state transport,
not distributed gradient averaging or evidence of faster convergence.

`formula_checkpoint_exchange.py` exposes four operations through one domain/
runtime interface. Every operation requires an explicit owner registry,
artifact root and fresh `--receipt` file:

| Command | Additional arguments | Effect |
| --- | --- | --- |
| `anchor` | `--version-id ID --output DIRECTORY` | Stage a full verified registered candidate |
| `publish` | `--manifest FILE [--parent-version ID] [--upload]` | Validate locally; upload only with the flag |
| `receive` | `--reference FILE --kind anchor\|update --output DIRECTORY [--parent-version ID] --allow-weight-download` | Fetch only the exact commit-pinned bundle; updates need the full local parent |
| `register` | `--manifest FILE --output DIRECTORY [--parent-version ID]` | Record the replayed candidate without promotion |

Also provide `--domain` and `--runtime-version` on each command. For an anchor
whose checkpoint has a numerical parent, import/register that exact ancestry
first and pass the matching `--parent-version` when registering. Loading a full
anchor itself does not require downloading its parent chain. The receiver never
chases chains automatically or substitutes a different checkpoint.

Successful `publish --upload` returns a `formula_reference` containing the exact
Hub commit, paths, sizes, hashes and runtime binding. Transfer this reference to
the receiver; mutable `main` is not a checkpoint identity. The dataset is
`justicedao/uscode-autoformal-span-cache`, under the separate
`autoformal/uscode/formula-training/` namespace. `run ... --upload` publishes
completed branch updates; retry verifies that the retained bundle exactly
matches the completed registered candidate before republishing.

The Quack gateway currently listens on loopback. The tested fleet runs local
processes. Another machine can receive/register the same immutable branch and
run its own owner/workers; this does not automatically elect a shared head,
average independently trained branches, periodically poll the Hub, or expose a
production network listener. Those coordination policies remain separate work.
No successful exchange, registry row or schema build changes qualification.

## Census integration

Use `capture_learned_formula_observations` for source-only legal outputs and
pass its retained receipt into the production paired/census exporters. See
[paired census](paired_span_census.md) and
[versioned output columns](span_exchange_outputs.md). Keep raw AST agreement
separate from the restricted canonical-core comparison. Metadata-only
differences do not manufacture semantic repair tasks; lost exceptions and
deadlines remain discrepancies with full observation evidence.
