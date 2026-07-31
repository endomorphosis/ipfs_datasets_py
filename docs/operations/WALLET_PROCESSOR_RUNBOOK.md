# Wallet Processor Operations Runbook

Operational guide for multi-chain wallet processors under
`ipfs_datasets_py.processors.wallets` (WALPROC-G640).

This runbook covers **processor ingest/export** observability, bounds, and
recovery. For the 211-AI data-wallet API and World ID production health checks,
see `docs/runbooks/WALLET_OPERATIONS_RUNBOOK.md` in the outer repository.

## Scope

| Surface | Module | Notes |
| --- | --- | --- |
| Structured metrics | `processors.wallets.metrics.WalletProcessorMetrics` | Payload-free counters |
| Run receipts | `processors.wallets.metrics.IngestRunReceipt` | No addresses/payloads/secrets |
| Streaming ingest | `processors.wallets.pipeline.WalletLedgerProcessor` | Sink-before-CAS |
| Checkpoints | `processors.wallets.checkpoints` | Hash-anchored CAS |
| Finality / reorg | `processors.wallets.finality` | Shallow rewind / deep fail-closed |
| Fixture benchmark | `benchmarks/wallet_processors/run.py --fixture-only` | Offline only |

Importing wallet processor modules performs **no network I/O**.

## Operational bounds

All runs must be **explicitly finite** before any provider call:

* `OperationContext.limits`: `max_pages`, `max_items`, `max_requests`, deadlines
* Finite wallet scope or ledger `[start_position, end_position]`
* Token-bucket rate limits and retry/circuit-breaker policies on transports
* Response byte, decompression, and raw-payload custody ceilings
* Cooperative cancellation and wall-clock deadlines

Default resource budgets for offline gates live in
`ResourceBudget.fixture_default()`. Operator production budgets must be declared
explicitly.

### Performance budget policy

**Do not set performance budgets from live provider latency alone.**

1. Run the fixture benchmark and record records/sec + peak memory.
2. Combine fixture results with capacity planning (page size, concurrency,
   retention) and SLO policy.
3. Treat live latency as a separate diagnostic signal, never as the sole budget
   source.

```bash
python ipfs_datasets_py/benchmarks/wallet_processors/run.py --fixture-only
```

## Metrics catalog

`WalletProcessorMetrics` / `IngestRunReceipt` expose:

| Field group | Contents | Privacy rule |
| --- | --- | --- |
| Calls | `provider_calls` | No endpoints; optional `endpoint:<digest>` labels only |
| Retries / throttles | `retries`, `throttles` | Counts only |
| Bytes | `bytes_in`, `bytes_out` | Sizes only; never bodies |
| Records | seen / normalized / accepted / duplicate / exported | Counts only |
| Errors | provider, normalization, checkpoint, sink, export, other | Category buckets |
| Checkpoint | `checkpoint_age_seconds`, opaque `last_checkpoint_revision` | No scope strings with addresses |
| Head lag | `head_lag_units` + unit name (`blocks` / `slots` / `ledgers`) | Numeric delta only |
| Reorg | `reorg_rewinds`, `shallow_reorgs`, `deep_reorgs` | Depth units, not hashes |
| Finality | distribution over `Finality` enum | Enum values only |
| Throughput | `records_per_second`, `export_records_per_second`, wall time | Derived |
| Memory | `peak_memory_bytes` | Optional process peak |

Receipts **must not** contain wallet addresses, raw payloads, API keys, memos,
calldata, or authorization material. Use `IngestRunReceipt.assert_payload_free()`
in tests and CI.

### Example instrumentation sketch

```python
from ipfs_datasets_py.processors.wallets.metrics import (
    IngestRunReceipt,
    MetricErrorCategory,
    ResourceBudget,
    new_run_metrics,
)

metrics = new_run_metrics(
    chain_namespace="eip155",
    network="ethereum-mainnet",
    provider="alchemy-http",
)
metrics.record_provider_call()
metrics.record_bytes(inbound=2048)
metrics.record_records(seen=50, normalized=50, accepted=48, duplicate=2)
metrics.observe_checkpoint(age_seconds=12.5, revision="rev-abc123")
metrics.observe_head_lag(units=3, unit_name="blocks")

receipt = IngestRunReceipt.from_metrics(
    metrics,
    status="complete",
    chain_namespace="eip155",
    network="ethereum-mainnet",
    provider="alchemy-http",
    budget=ResourceBudget.fixture_default(),
)
receipt.assert_payload_free()
```

## Live smoke controls

Live provider smoke is **disabled by default**.

Enable only when **both** conditions hold:

1. Explicit endpoint allowlist (fingerprinted via `endpoint_fingerprint(url)`).
2. Explicit operator `network_approval_id`.

CLI gate:

```bash
# Refused (missing approval)
python ipfs_datasets_py/benchmarks/wallet_processors/run.py --live-smoke

# Policy accepted (still performs no budget derivation from live latency)
python ipfs_datasets_py/benchmarks/wallet_processors/run.py --live-smoke \
  --approve-endpoint 'https://rpc.example.test/v1' \
  --network-approval-id ops-approval-2026-07-29
```

`LiveSmokePolicy` raises if `APPROVED` is set without fingerprints and approval
id. Fixture-only CI must never depend on live smoke.

## Recovery procedures

### 1. Crash mid-run

**Symptoms:** process exit before `PipelineRunReceipt` / `IngestRunReceipt`;
partial sink pages may exist without a checkpoint advance.

**Invariants:**

* Durable checkpoint advances **only after** successful sink commit
  (sink-before-CAS).
* Partial / cancelled / failed runs must **not** advance the checkpoint.

**Recovery:**

1. Inspect the last durable checkpoint revision and hash anchor.
2. Confirm sink commit receipt (if any) does not claim a later revision.
3. Resume with the same `CheckpointIdentity` (chain, network, genesis, provider,
   scope, schema major, normalizer version).
4. Re-run the bounded request; the processor re-reads from the hash-anchored
   position. Duplicates are filtered at the sink.
5. Emit a metrics receipt with `status=partial` or `failed` for the aborted run;
   do not invent a successful receipt.

### 2. Checkpoint CAS failure

**Symptoms:** `CheckpointError` on compare-and-set; concurrent writer or stale
expected revision.

**Recovery:**

1. Reload the current checkpoint; verify identity still matches.
2. If another worker advanced the same scope, stop dual-writers and reconcile.
3. If the local expected revision is stale after a crash-replay, rebuild the
   expected state from the store and retry once with the fresh base revision.
4. If CAS keeps losing, fail closed for operator review; do not force-overwrite
   without audit.
5. Record `MetricErrorCategory.CHECKPOINT` and checkpoint age after recovery.

### 3. Reorganization (shallow)

**Symptoms:** provider tip diverges within the configured safety window;
`reorg_rewinds` increments; orphan/tombstone corrections emitted.

**Recovery:**

1. Locate common ancestor within the safety depth.
2. Apply orphan/tombstone projections for displaced records.
3. Rewind the checkpoint to the common ancestor anchor.
4. Resume forward ingest; record `record_reorg_rewind(shallow=True)`.
5. Re-export only if consumers require corrected finality.

### 4. Reorganization (deep)

**Symptoms:** divergence exceeds safety window; `ReorgReviewRequired` /
`deep_reorgs` signal.

**Recovery:**

1. **Stop automatic rewind.** Deep reorgs fail closed.
2. Preserve checkpoint, sink state, and provider tip observations for audit.
3. Operator decides: manual rewind depth, full rescan of affected range, or
   quarantine export consumers.
4. After repair, resume with an explicit bounded request and a new run receipt.
5. Do not collapse finality to a boolean; keep `Finality` enum transitions.

### 5. Provider mismatch

**Symptoms:** resume identity differs in provider name, genesis, schema major,
or normalizer version; checkpoint key does not match.

**Recovery:**

1. Treat as a **new scan identity** — never reuse another provider’s checkpoint.
2. If intentional migration (provider cutover), document dual-run window:
   finish old provider to a stable anchor, start new provider from a verified
   hash position, compare fixture/conformance outputs.
3. Reject silent provider swaps in config; surface `InvalidRequestError` /
   checkpoint incompatibility.
4. Metrics labels may include provider name only (no secrets or resolved URLs).

### 6. Transport throttle / circuit open

**Symptoms:** elevated `throttles` / `retries`; `CircuitOpenError`.

**Recovery:**

1. Back off; respect `Retry-After` within policy caps.
2. Reduce concurrent requests per endpoint fingerprint.
3. Confirm rate-limit policy is not fighting upstream quotas.
4. If circuit stays open past SLO, fail the bounded run with a partial receipt
   rather than spinning.

### 7. Resource limit / deadline

**Symptoms:** `ResourceLimitError` or `DeadlineExceededError`.

**Recovery:**

1. Narrow the ledger range or lower page size.
2. Raise limits only with documented capacity justification (not from a single
   live latency sample).
3. Checkpoint should remain at last successful commit; resume later.

## Health checks (offline)

```bash
# Unit metrics coverage
python -m pytest -q ipfs_datasets_py/tests/unit/processors/wallets/test_metrics.py

# Fixture benchmark (records/sec + peak memory)
python ipfs_datasets_py/benchmarks/wallet_processors/run.py --fixture-only

# Pipeline / checkpoint / reorg unit suites (shared kernel)
python -m pytest -q \
  ipfs_datasets_py/tests/unit/processors/wallets/test_pipeline.py \
  ipfs_datasets_py/tests/unit/processors/wallets/test_checkpoints.py \
  ipfs_datasets_py/tests/unit/processors/wallets/test_reorgs.py
```

## Alerting suggestions

| Signal | Warning | Critical |
| --- | --- | --- |
| Checkpoint age | > 2× expected batch interval | > 10× or unbounded growth |
| Head lag | Sustained lag above operator SLO | Lag growing while calls succeed |
| Deep reorgs | Any | Immediate page + freeze auto-export |
| CAS failures | > 1% of commits | Burst suggesting dual-writers |
| Provider error rate | > 5% of calls | Circuit open with backlog |
| Budget breach (fixture CI) | `budget_ok=false` on report | Regression vs fixture baseline |

Never page on raw payload content. Prefer counters, ages, and category rates.

## Privacy and logging

* Log allowlists only: request id, chain namespace, network, provider name,
  endpoint fingerprint, status, counters, error categories.
* Forbidden: addresses, private keys, API keys, authorization headers, memos,
  calldata, full provider JSON bodies.
* Use `security.safe_exception_text` and `endpoint_fingerprint` for error paths.

## Related documents

* Migration plan §14 Performance and operability (planning docs; operator-protected)
* `docs/security/WALLET_PROCESSOR_THREAT_MODEL.md` (when present)
* Outer-repo cutover: `docs/runbooks/WALLET_PROCESSOR_CUTOVER.md` (release track)
* Outer-repo wallet API ops: `docs/runbooks/WALLET_OPERATIONS_RUNBOOK.md`
