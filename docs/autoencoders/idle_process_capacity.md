# Expanding native process capacity without resetting history

The fenced ingestion pool needs at least `2 + 3 * workers` process slots.
The current four-slot policy cannot fit a spawned worker. Increasing the
worker request alone does not change that policy or its qualification gates.

Use `scripts/ops/legal_ir/plan_span_ingest_capacity.py` to prepare an explicit
administrative change. Supply the existing state, its exact policy digest and
the proposed process capacity:

```sh
python3 -B scripts/ops/legal_ir/plan_span_ingest_capacity.py \
  --scheduler-state /tmp/ipfs-datasets-resource-scheduler-1000.json \
  --expected-policy-sha256 <current-policy-sha256> --process-slots 8
```

The default only reads native metadata. `--apply` additionally requires no
leases, waiters or active pressure recovery/backoff state, known PID headroom and
healthy current native proof telemetry. It changes only
`total_child_process_slots` under the native thread/sibling-file lock with
atomic, fsynced persistence. It retains the sequence, metrics, historical
refusals, opaque extension fields and every other policy field. It does not
recover owners, clear waiters, reset history, raise CPU/memory/storage caps or
change proof thresholds. A busy scheduler refuses application. An expired, well-formed backoff record
is preserved; a malformed deadline refuses.

Coordinate the change with scheduler clients: old facades and runtime specs
deliberately refuse after the policy digest changes. Close them and explicitly
bind fresh facades/specs to the reported successor digest. Revalidate the
owning acceptance/source bindings; do not rewrite retained historical
receipts. The capacity tool does not update those bindings or restart services.
Regular work still obtains native reservations and passes all existing
hardware pressure, storage, source, logic-family and Lake gates.

The helper reports observed PID availability and current pressure. These are
observations, not kernel quotas or guarantees that future work will be
admitted. Eight slots fit a planning floor of two spawned workers only if the
separate CPU/RAM budget also permits it; actual Lake descendants can still
exceed the floor and cause refusal. This command loads no model, performs no
inference or training and confers no Lean or source-span admission.

The Python administrative API is `expand_idle_process_capacity` in
`optimizers/logic_theorem_optimizer/existing_resource_scheduler.py`; its
`apply=False` default is the same read-only plan.
