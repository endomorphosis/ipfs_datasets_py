# PCPR-064 Datasets bounded PatchPlan binding

These files bind DatasetsContextPack@1 and LogicProviderProtocol@2 to
the Accelerate-owned bounded PatchPlan. Datasets does not remint the
pack CID, does not remint the protocol, and does not add a protocol
operation.

- `cpython312/reference.bounded-patch.binding.json` binds the Datasets
  pack identity to the Accelerate PatchPlan. Exact commit and tree are
  bound by the PCPR-064 receipt `current_tree_binding`.
- The hermetic protocol mutation is the additive
  LogicProviderProtocolBoundedPatchPlan@1 surface on protocol_v2.py.
- Execution is owned by Accelerate. Selected tests remain PCPR-065.
- Missing a live Quack-fenced session emits operator-blocking task
  `pcpr-064-operator-live-bounded-patch`.

Sealed validation PATH is exactly `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin`.
