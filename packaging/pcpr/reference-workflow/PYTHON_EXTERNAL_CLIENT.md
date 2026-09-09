# PCPR-080 Datasets Python-external-client binding

These files bind DatasetsContextPack@1, LogicProviderProtocol@2, and the
stale ContextPack and protocol-test identities to the Accelerate-owned
Python external-client demonstration. Datasets does not remint the pack
CID, does not remint the canonical protocol identity, and does not claim
live Supervisor.run.

- `cpython312/reference.python-external-client.binding.json` binds the
  Datasets pack identity to the Accelerate Python client. Exact commit
  and tree are bound by the PCPR-080 receipt `current_tree_binding`.
- The sidecar records that semantic identities survive the client
  demonstration. Stale identities remain rejected. Unaffected
  solver-qualification proofs remain current. The Python client is
  owned by Accelerate. Generic MCP-client demonstration remains
  PCPR-081.
- Missing a live Quack-fenced session emits operator-blocking task
  `pcpr-080-operator-live-python-external-client`.

Sealed validation PATH is exactly `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin`.
