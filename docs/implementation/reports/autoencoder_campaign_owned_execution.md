# Owned execution of prepared autoencoder campaign jobs

Implementation and offline validation, 2026-09-26. This adds the B2 owner entry
from the [dispatch plan](../plans/AUTOENCODER_CAMPAIGN_OWNED_DISPATCH_PLAN.md).
All 486 selected regression cases passed with no failures, errors or skips.
Native checkpoint validation remains deferred. These are synthetic execution
and compatibility results, not a native qualification or speed receipt.

The owner executes the original registered v8 jobs. Their language/variant,
base version, training and validation roles, bridge configuration, shared
targets, optional Arrow feature weights, and sparse-storage policy stay bound
to the sealed request. DuckDB retains ownership of registration and completion.
Parameter reads and accepted updates use the existing local worker path.

```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_campaign_owned_training import (
    execute_prepared_campaign_training,
)

report = execute_prepared_campaign_training(
    registry, prepared["request_artifact"], max_new_batches=1, max_workers=1,
)
```

This call belongs on the registry owner thread. The request must already exist
and must declare sufficient per-worker resources. Invocation limits cannot
exceed its sealed policy. There is no remote execution endpoint in B2; the
typed Quack controller and gateway profile remain B3 work. The existing daemon
controller continues to describe a separate execution path.

## Completion and recovery

The coordinator retains its original receipt verification, patch replay,
compaction and completion methods. Its public entry keeps its existing defaults.
The owned entry adds persistent claim, renewal, completion and failure slots.
Lost mutation responses resolve against the same registry operation. Reopening
only looks up pending intents; it never resends a start or silently adopts an
old lease. An unresolved operation, uncertain child, retained attempt or
unconfirmed resource release requires explicit recovery before further dispatch.

Completed original jobs are independently checked again under an admitted
replay reservation. A completed database row alone is insufficient. A page can
release each verified successful job before claiming the next, allowing serial
pages without holding every prior worker's host allocation. Failed attempts
retain their disk claims and evidence. Their host lease can be released only
after the worker group and owner filesystem work have stopped.

The native child starts through a fixed isolated bootstrap. It installs the
network filter before package imports, pins the canonical workspace tree, and
waits until the owner durably records its process identity. The owner then
releases the original worker. Loss of the owner pipe terminates the isolated
group. Test injection always remains `injected_test`; it cannot establish
supervised native execution.

## Cost and limits

| Mechanism | Benefit | Cost or remaining limit |
|---|---|---|
| Existing shared target artifacts | Workers consume the complete sealed targets without substituting an empty bridge | Hydration and semantic validation still run |
| Accepted sparse patches | Completion transfers and replays accepted changes through the existing owner path | Compaction can still materialize a full checkpoint |
| Existing Arrow weight views | Numeric access stays local to each worker | This change does not convert all embeddings or all model state into zero-copy arrays |
| Persistent operation slots | Lost responses do not cause duplicate training | Journal size and operation limits bound each dispatch page |
| Per-worker resource admission | Parallel jobs account independently for memory, CPU and storage | Full named-root accounting has a startup/completion cost |
| Five-second routine usage checks | Avoids a full disk census on every coordinator poll | Enforcement is cooperative and sampled |
| Geometric output allowances | Avoids one resource-ledger update per small patch | Output allowance can approach twice the measured bytes; it is capacity, not a measurement |
| Original completion replay | Preserves candidate identity and acceptance semantics | Replay remains CPU/I/O work; synchronous owner replay can delay other heartbeats |

The owner refreshes other active leases before synchronous terminal replay.
Wall deadlines are checked around owner operations and while supervising
children; they are not kernel deadlines for uninterruptible Python or filesystem
work. No new filesystem quota, automatic retained-claim cleanup, model promotion,
DuckLake write or Hugging Face publication is performed by this entry.

No legal-IR speed claim follows from these changes. A future native comparison
must report wall time per span and bridge-on evaluation with nonzero target
counts, exact bridge names, prover/cache flags, workers, sample count and source
provenance. Training acceptance remains distinct from formalization. Only
`lake build <Lib>` supplies a Lean admit; the Constitution remains unformalized.

## Captured validation

The [test receipt](evidence/autoencoder_control_plane_plan/campaign-owned-execution-tests-20260926-r1.json)
records 29 owned-execution, 24 durable-coordinator, 35 process-boundary, 101
existing-coordinator, 45 journal, 72 preparation, 169 request-codec and 11
shared-target/sparse/Arrow cases. Native process supervision used test doubles;
the existing spawn-pool fixture ran an injected worker. Neither performed native
checkpoint training. The tests exercised real target codecs, tiny accepted
updates, owner replay/compaction and optional Arrow views.

The [audit](evidence/autoencoder_control_plane_plan/campaign-owned-execution-audit-20260926-r1.json)
passed a 60-second quiet-source gate and unchanged before/after inventories of
7,776 package files and 1,293 dependencies. Test wall time was 283.200 seconds;
the guarded capture took 368.500 seconds. These times measure regression tests,
not legal-IR evaluation. Protected checkpoint and measurement receipts stayed
unchanged. The [resource receipt](evidence/autoencoder_control_plane_plan/campaign-owned-execution-release-20260926-r1.json)
confirms release of reservation `c37e50296f744398ad5b39db56a11825`. Its final
charge was 206,388,260 bytes, including the conservative 200 MB fixture allowance;
that charge is not an observed peak allocation.

The first capture had 485 passes and one failure. A forged native label from an
injected producer reached database completion before the existing replay check
rejected the mismatch. The owned boundary now checks the producer mode before
staging and completion. Public coordinator defaults were preserved. The
[failed test receipt](evidence/autoencoder_control_plane_plan/campaign-owned-execution-failed-tests-20260926-r1.json),
[failed audit](evidence/autoencoder_control_plane_plan/campaign-owned-execution-failed-audit-20260926-r1.json)
and [original source](evidence/autoencoder_control_plane_plan/campaign-owned-execution-failed-source-20260926-r1.py)
remain separate immutable evidence. Its disk claim
`c2773bf889f64efc8fc433c89f2cf03b` remains retained; the repair did not erase or
relabel the failed attempt.
