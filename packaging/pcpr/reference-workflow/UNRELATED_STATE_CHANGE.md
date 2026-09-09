# PCPR-066 Datasets unrelated-state-change binding

These files bind DatasetsContextPack@1, LogicProviderProtocol@2, and the
documentation-only sidecar to the Accelerate-owned unrelated state
change. Datasets does not remint the pack CID, does not remint the
protocol, and does not claim live reuse.

- `cpython312/reference.unrelated-state-change.binding.json` binds the
  Datasets pack identity to the Accelerate change. Exact commit and
  tree are bound by the PCPR-066 receipt `current_tree_binding`.
- The sidecar is documentation-only. The impacted cone is empty.
  Execution is owned by Accelerate. Eligible reuse remains PCPR-067.
- Missing a live Quack-fenced session emits operator-blocking task
  `pcpr-066-operator-live-unrelated-state-change`.

Sealed validation PATH is exactly `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin`.
