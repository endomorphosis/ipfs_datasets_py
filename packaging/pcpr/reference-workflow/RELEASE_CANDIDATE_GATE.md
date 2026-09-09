# PCPR-093 Datasets release-candidate-gate binding

These files bind DatasetsContextPack@1, LogicProviderProtocol@2, and the
stale ContextPack and protocol-test identities to the Accelerate-owned
release-candidate gate. Datasets does not remint the pack CID, does not
remint the canonical protocol identity, and does not claim live
Supervisor.run.

- `cpython312/reference.release-candidate-gate.binding.json` binds the
  Datasets pack identity to the Accelerate gate run. Exact commit and
  tree are bound by the PCPR-093 receipt `current_tree_binding`.
- The sidecar records that semantic identities survive the gate run.
  Stale identities remain rejected. Unaffected solver-qualification
  proofs remain current. The gate run is owned by Accelerate. Closed
  release remains PCPR-094.
- Missing a live Quack-fenced session emits operator-blocking task
  `pcpr-093-operator-live-release-candidate-gate`.

Sealed validation PATH is exactly `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin`.
