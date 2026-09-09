# PCPR-096 Datasets next-bounded-pilot binding

These files bind DatasetsContextPack@1, LogicProviderProtocol@2, and the
stale ContextPack and protocol-test identities to the Accelerate-owned
next-bounded-pilot recommendation. Datasets does not remint the pack CID,
does not remint the canonical protocol identity, and does not claim live
Supervisor.run.

- `cpython312/reference.next-bounded-pilot.binding.json` binds the
  Datasets pack identity to the Accelerate next-bounded-pilot recommendation.
  Exact commit and tree are bound by the PCPR-096 receipt `current_tree_binding`.
- The sidecar records that semantic identities survive the next bounded
  pilot recommendation. Stale identities remain rejected. Unaffected
  solver-qualification proofs remain current. The recommendation is owned
  by Accelerate. The recommended pilot is synthetic, not customer-facing,
  and is not created. This binding does not create a successor campaign.
- Missing a live Quack-fenced session emits operator-blocking task
  `pcpr-096-operator-live-next-bounded-pilot`.

Sealed validation PATH is exactly `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin`.
