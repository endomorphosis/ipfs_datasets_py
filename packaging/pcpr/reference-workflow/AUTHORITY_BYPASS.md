# PCPR-083 Datasets authority-bypass binding

These files bind DatasetsContextPack@1, LogicProviderProtocol@2, and the
stale ContextPack and protocol-test identities to the Accelerate-owned
authority-bypass proof. Datasets does not remint the pack CID, does not
remint the canonical protocol identity, and does not claim live MCP
stdio or HTTP.

- `cpython312/reference.authority-bypass.binding.json` binds the
  Datasets pack identity to the Accelerate authority-bypass proof. Exact
  commit and tree are bound by the PCPR-083 receipt
  `current_tree_binding`.
- The sidecar records that semantic identities survive the bypass
  demonstration. Stale identities remain rejected. Unaffected
  solver-qualification proofs remain current. The authority-bypass proof
  is owned by Accelerate. Threat-model preparation remains PCPR-090.
- Missing a live Quack-fenced session emits operator-blocking task
  `pcpr-083-operator-live-external-client-authority-bypass`.

Sealed validation PATH is exactly `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin`.
