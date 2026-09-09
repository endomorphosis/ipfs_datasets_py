# PCPR-091 Datasets trusted-computing-base binding

These files bind DatasetsContextPack@1, LogicProviderProtocol@2, and the
stale ContextPack and protocol-test identities to the Accelerate-owned
trusted-computing-base inventory. Datasets does not remint the pack CID,
does not remint the canonical protocol identity, and does not claim live
Supervisor.run.

- `cpython312/reference.trusted-computing-base.binding.json` binds the
  Datasets pack identity to the Accelerate TCB inventory. Exact commit
  and tree are bound by the PCPR-091 receipt `current_tree_binding`.
- The sidecar records that semantic identities survive the TCB
  inventory. Stale identities remain rejected. Unaffected
  solver-qualification proofs remain current. The TCB inventory is
  owned by Accelerate. Audit package remains PCPR-092.
- Missing a live Quack-fenced session emits operator-blocking task
  `pcpr-091-operator-live-tcb-inventory`.

Sealed validation PATH is exactly `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin`.
