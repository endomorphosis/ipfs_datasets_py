# PCPR-063 Datasets deterministic-first route binding

These files bind DatasetsContextPack@1 to the Accelerate-owned
deterministic-first route. Datasets does not remint the pack CID, does
not execute the route, and does not produce a bounded patch.

- `cpython312/reference.deterministic-first-route.binding.json` binds
  the Datasets pack identity to the Accelerate route. Exact commit and
  tree are bound by the PCPR-063 receipt `current_tree_binding`.
- Execution is owned by Accelerate. Bounded patch remains PCPR-064.
  Selected tests remain PCPR-065.
- Missing a live Quack-fenced session emits operator-blocking task
  `pcpr-063-operator-live-deterministic-route`.

Sealed validation PATH is exactly `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin`.
