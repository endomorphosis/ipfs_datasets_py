# PCPR-095 Datasets residual-gap-report binding

These files bind DatasetsContextPack@1, LogicProviderProtocol@2, and the
stale ContextPack and protocol-test identities to the Accelerate-owned
residual-gap report receipt. Datasets does not remint the pack CID, does not
remint the canonical protocol identity, and does not claim live
Supervisor.run.

- `cpython312/reference.residual-gap-report.binding.json` binds the
  Datasets pack identity to the Accelerate residual-gap report. Exact commit and
  tree are bound by the PCPR-095 receipt `current_tree_binding`.
- The sidecar records that semantic identities survive the residual-gap report.
  Stale identities remain rejected. Unaffected solver-qualification
  proofs remain current. The residual-gap report is owned by Accelerate. Next
  bounded-pilot recommendation remains PCPR-096. Residual reporting does not
  create a successor campaign.
- Missing a live Quack-fenced session emits operator-blocking task
  `pcpr-095-operator-live-residual-gap-report`.

Sealed validation PATH is exactly `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin`.
