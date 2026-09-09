# PCPR-082 Datasets objective-identity-parity binding

These files bind DatasetsContextPack@1, LogicProviderProtocol@2, and the
stale ContextPack and protocol-test identities to the Accelerate-owned
objective-identity-parity demonstration. Datasets does not remint the pack
CID, does not remint the canonical protocol identity, and does not claim
live MCP stdio or HTTP.

- `cpython312/reference.objective-identity-parity.binding.json` binds the
  Datasets pack identity to the Accelerate objective identity parity. Exact
  commit and tree are bound by the PCPR-082 receipt
  `current_tree_binding`.
- The sidecar records that semantic identities survive the client
  demonstration. Stale identities remain rejected. Unaffected
  solver-qualification proofs remain current. The objective identity parity is
  owned by Accelerate. Authority-bypass proof remains PCPR-083.
- Missing a live Quack-fenced session emits operator-blocking task
  `pcpr-082-operator-live-cross-client-objective-identity-parity`.

Sealed validation PATH is exactly `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin`.
