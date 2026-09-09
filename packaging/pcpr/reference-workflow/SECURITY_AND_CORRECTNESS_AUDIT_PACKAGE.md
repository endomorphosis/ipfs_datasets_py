# PCPR-092 Datasets security and correctness audit-package binding

These files bind DatasetsContextPack@1, LogicProviderProtocol@2, and the
stale ContextPack and protocol-test identities to the Accelerate-owned
security and correctness audit package. Datasets does not remint the
pack CID, does not remint the canonical protocol identity, and does not
claim live Supervisor.run.

- `cpython312/reference.security-and-correctness-audit-package.binding.json`
  binds the Datasets pack identity to the Accelerate audit package.
  Exact commit and tree are bound by the PCPR-092 receipt
  `current_tree_binding`.
- The sidecar records that semantic identities survive the audit
  package. Stale identities remain rejected. Unaffected
  solver-qualification proofs remain current. The audit package is
  owned by Accelerate. Status is external_audit_ready, never
  externally_audited. Closed release remains PCPR-093/094.
- Missing a live Quack-fenced session emits operator-blocking task
  `pcpr-092-operator-live-audit-package`.

Sealed validation PATH is exactly `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin`.
