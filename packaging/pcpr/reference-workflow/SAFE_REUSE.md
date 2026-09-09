# PCPR-067 Datasets safe-reuse binding

These files bind DatasetsContextPack@1, LogicProviderProtocol@2, and the
documentation-only sidecar to the Accelerate-owned eligible-reuse
admission. Datasets does not remint the pack CID, does not remint the
protocol, and does not claim live reuse.

- `cpython312/reference.safe-reuse.binding.json` binds the Datasets pack
  identity to the Accelerate reuse admission. Exact commit and tree are
  bound by the PCPR-067 receipt `current_tree_binding`.
- The sidecar remains documentation-only. The impacted cone is empty.
  Execution is owned by Accelerate. A relevant interface change remains
  PCPR-068.
- Missing a live Quack-fenced session emits operator-blocking task
  `pcpr-067-operator-live-safe-reuse`.

Sealed validation PATH is exactly `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin`.
