# PCPR-081 Datasets generic-MCP-client binding

These files bind DatasetsContextPack@1, LogicProviderProtocol@2, and the
stale ContextPack and protocol-test identities to the Accelerate-owned
generic MCP-client demonstration. Datasets does not remint the pack
CID, does not remint the canonical protocol identity, and does not claim
live MCP stdio or HTTP.

- `cpython312/reference.generic-mcp-client.binding.json` binds the
  Datasets pack identity to the Accelerate generic MCP client. Exact
  commit and tree are bound by the PCPR-081 receipt
  `current_tree_binding`.
- The sidecar records that semantic identities survive the client
  demonstration. Stale identities remain rejected. Unaffected
  solver-qualification proofs remain current. The generic MCP client is
  owned by Accelerate. Cross-client identity parity remains PCPR-082.
- Missing a live Quack-fenced session emits operator-blocking task
  `pcpr-081-operator-live-generic-mcp-client`.

Sealed validation PATH is exactly `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin`.
