# PCPR-062 Datasets ContextPack storage binding

These files bind DatasetsContextPack@1 to the Kit-owned hermetic
current root. Datasets does not remint the pack CID, does not store
bytes, and does not publish a current root.

- `cpython312/reference.context-pack.root.binding.json` binds the
  Datasets pack identity to Kit current-root CID
  `bafkreihjdjarrlr24sperlq3zl4hjrksbol4b5saxquie3wpyi6xwsobwi`.
  Exact commit and tree are bound by the PCPR-062 receipt
  `current_tree_binding`.
- Durable storage is owned by Kit. Deterministic execution remains
  PCPR-063.
- Missing a live Quack-fenced session emits operator-blocking task
  `pcpr-062-operator-live-context-pack-root`.

Sealed validation PATH is exactly `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin`.
