# PCPR-065 Datasets selected-tests-and-proofs binding

These files bind DatasetsContextPack@1, LogicProviderProtocol@2, the
selected protocol and semantic-API tests, and solver-qualification
proofs to the Accelerate-owned selected-tests-and-proofs run. Datasets
does not remint the pack CID, does not remint the protocol, and does
not claim live selected tests.

- `cpython312/reference.selected-tests-and-proofs.binding.json` binds
  the Datasets pack identity to the Accelerate run. Exact commit and
  tree are bound by the PCPR-065 receipt `current_tree_binding`.
- The PatchPlan selection is incomplete, so full validation is required.
- Execution is owned by Accelerate. Unrelated-state-change reuse remains
  PCPR-066.
- Missing a live Quack-fenced session emits operator-blocking task
  `pcpr-065-operator-live-selected-tests-and-proofs`.

Sealed validation PATH is exactly `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin`.
