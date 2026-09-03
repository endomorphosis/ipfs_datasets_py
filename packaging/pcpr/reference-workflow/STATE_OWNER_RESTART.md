# PCPR-070 Datasets state-owner-restart binding

These files bind DatasetsContextPack@1, LogicProviderProtocol@2, and the
stale ContextPack and protocol-test identities to the Accelerate-owned
authoritative state-owner restart. Datasets does not remint the pack CID,
does not remint the canonical protocol identity, and does not claim live
Quack restart.

- `cpython312/reference.state-owner-restart.binding.json` binds the
  Datasets pack identity to the Accelerate restart. Exact commit and
  tree are bound by the PCPR-070 receipt `current_tree_binding`.
- The sidecar records that semantic identities survive restart. Stale
  identities remain rejected. Unaffected solver-qualification proofs
  remain current. Restart is owned by Accelerate. Recovery remains
  PCPR-071.
- Missing a live Quack-fenced session emits operator-blocking task
  `pcpr-070-operator-live-authoritative-state-owner-restart`.

Sealed validation PATH is exactly `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin`.
