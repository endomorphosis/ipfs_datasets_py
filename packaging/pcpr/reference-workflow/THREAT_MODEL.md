# PCPR-090 Datasets threat-model binding

These files bind DatasetsContextPack@1, LogicProviderProtocol@2, and the
stale ContextPack and protocol-test identities to the Accelerate-owned
threat model. Datasets does not remint the pack CID, does not remint
the canonical protocol identity, and does not claim live Supervisor.run.

- `cpython312/reference.threat-model.binding.json` binds the Datasets
  pack identity to the Accelerate threat model. Exact commit and tree
  are bound by the PCPR-090 receipt `current_tree_binding`.
- The sidecar records that semantic identities survive the threat model.
  Stale identities remain rejected. Unaffected solver-qualification
  proofs remain current. The threat model is owned by Accelerate.
  Trusted-computing-base inventory remains PCPR-091.
- Missing a live Quack-fenced session emits operator-blocking task
  `pcpr-090-operator-live-threat-model`.

Sealed validation PATH is exactly `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin`.
