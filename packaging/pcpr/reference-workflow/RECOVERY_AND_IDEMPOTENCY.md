# PCPR-071 Datasets recovery-and-idempotency binding

These files bind DatasetsContextPack@1, LogicProviderProtocol@2, and the
stale ContextPack and protocol-test identities to the Accelerate-owned
recovery and idempotency demonstration. Datasets does not remint the pack
CID, does not remint the canonical protocol identity, and does not claim
live Quack recovery.

- `cpython312/reference.recovery-and-idempotency.binding.json` binds the
  Datasets pack identity to the Accelerate recovery. Exact commit and
  tree are bound by the PCPR-071 receipt `current_tree_binding`.
- The sidecar records that semantic identities survive recovery. Stale
  identities remain rejected. Unaffected solver-qualification proofs
  remain current. Recovery is owned by Accelerate. The final receipt
  chain remains PCPR-072.
- Missing a live Quack-fenced session emits operator-blocking task
  `pcpr-071-operator-live-recovery-and-idempotency`.

Sealed validation PATH is exactly `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin`.
