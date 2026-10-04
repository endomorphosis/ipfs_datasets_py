# Xaman Native-Vault Rekey State Fuzzing

Task: `PORTAL-CXTP-167`

This evidence binds the public Android/iOS rekey order and TypeScript call
sites to the pinned Xaman source manifest. It exhaustively enumerates failure
locations for a single vault and a bounded two-vault batch: recovery snapshot
write, primary purge, replacement write, and recovery cleanup. The batch model
matches the public ordering: all recovery snapshots, then per-vault
purge/replacement pairs, then recovery cleanup. Z3 and CVC5 independently
check the corresponding single-vault state predicates.

Generate the report from a separately pinned source checkout:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/build_xaman_native_vault_state_fuzz.py \
  --source-root /path/to/pinned/xaman-app
```

## Results

The bounded model preserves recoverability for every enumerated phase/index
case. It produces two runtime test obligations:

1. A replacement-write failure after primary deletion leaves old-key recovery.
2. A recovery-cleanup failure after replacement leaves a new-key primary and
   old-key recovery while the operation must report failure.

The public bridge and TypeScript wrapper have error paths, and the public
passcode flow attempts a rollback after a rejected batch rekey. Those source
facts do not prove native storage durability, exception behavior, recovery
accessibility, or caller remediation on a device.

The dual-access cleanup witness is not a vulnerability finding. It is a
source-bounded counterexample to the stronger, unproved assumption that any
failed rekey automatically retires the old key. `PORTAL-CXTP-163` must inject
both failure types on Android and iOS under the reviewed verifier-only gate,
including first- and later-vault batch positions.
