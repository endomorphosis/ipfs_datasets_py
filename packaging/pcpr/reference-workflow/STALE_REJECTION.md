# PCPR-069 Datasets stale-rejection binding

These files bind DatasetsContextPack@1, LogicProviderProtocol@2, and the
stale ContextPack and protocol-test identities to the Accelerate-owned
stale rejection and PlanDelta. Datasets does not remint the pack CID,
does not remint the canonical protocol identity, and does not claim live
PlanDelta admission.

- `cpython312/reference.stale-rejection.binding.json` binds the Datasets
  pack identity to the Accelerate stale rejection. Exact commit and tree
  are bound by the PCPR-069 receipt `current_tree_binding`.
- The sidecar records stale identities. Unaffected solver-qualification
  proofs remain current. Execution is owned by Accelerate. Restart
  recovery remains PCPR-070.
- Missing a live Quack-fenced session emits operator-blocking task
  `pcpr-069-operator-live-stale-rejection-and-plan-delta`.

Sealed validation PATH is exactly `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin`.
