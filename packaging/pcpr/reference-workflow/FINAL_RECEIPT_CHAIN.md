# PCPR-072 Datasets final-receipt-chain binding

These files bind DatasetsContextPack@1, LogicProviderProtocol@2, and the
stale ContextPack and protocol-test identities to the Accelerate-owned
final proof-carrying receipt chain. Datasets does not remint the pack
CID, does not remint the canonical protocol identity, and does not claim
live Quack chain emission.

- `cpython312/reference.final-receipt-chain.binding.json` binds the
  Datasets pack identity to the Accelerate chain. Exact commit and
  tree are bound by the PCPR-072 receipt `current_tree_binding`.
- The sidecar records that semantic identities survive the chain. Stale
  identities remain rejected. Unaffected solver-qualification proofs
  remain current. The chain is owned by Accelerate. External-client
  demonstration remains PCPR-080.
- Missing a live Quack-fenced session emits operator-blocking task
  `pcpr-072-operator-live-final-receipt-chain`.

Sealed validation PATH is exactly `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin`.
