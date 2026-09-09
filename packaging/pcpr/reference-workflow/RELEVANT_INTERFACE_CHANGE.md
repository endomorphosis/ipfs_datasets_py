# PCPR-068 Datasets relevant-interface-change binding

These files bind DatasetsContextPack@1, LogicProviderProtocol@2, and the
relevant successor operation to the Accelerate-owned relevant interface
change. Datasets does not remint the pack CID, does not remint the
canonical protocol identity, and does not claim live reuse.

- `cpython312/reference.relevant-interface-change.binding.json` binds the
  Datasets pack identity to the Accelerate change. Exact commit and
  tree are bound by the PCPR-068 receipt `current_tree_binding`.
- The sidecar adds protocol operation `impact`. The impacted cone is
  nonempty. Execution is owned by Accelerate. Stale rejection remains
  PCPR-069.
- Missing a live Quack-fenced session emits operator-blocking task
  `pcpr-068-operator-live-relevant-interface-change`.

Sealed validation PATH is exactly `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin`.
