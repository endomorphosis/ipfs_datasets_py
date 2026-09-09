# PCPR-094 Datasets promotion-or-non-promotion binding

These files bind DatasetsContextPack@1, LogicProviderProtocol@2, and the
stale ContextPack and protocol-test identities to the Accelerate-owned
promotion or non-promotion receipt. Datasets does not remint the pack CID, does not
remint the canonical protocol identity, and does not claim live
Supervisor.run.

- `cpython312/reference.promotion-or-non-promotion.binding.json` binds the
  Datasets pack identity to the Accelerate promotion decision. Exact commit and
  tree are bound by the PCPR-094 receipt `current_tree_binding`.
- The sidecar records that semantic identities survive the promotion decision.
  Stale identities remain rejected. Unaffected solver-qualification
  proofs remain current. The promotion decision is owned by Accelerate. Closed
  release remains PCPR-094.
- Missing a live Quack-fenced session emits operator-blocking task
  `pcpr-094-operator-live-promotion`.

Sealed validation PATH is exactly `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin`.
