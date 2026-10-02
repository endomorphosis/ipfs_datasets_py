# Live scan-policy observation

`codebase_scan_policy_live.verify_policy_current` joins an immutable scan-policy
receipt to a current source head without publishing a new head or artifact.
It replays the frozen policy, checks exact external ignore configuration and
bytes and the complete repository `.gitignore` population, invokes the native
source observer, then repeats the scope check. Changed inactive comments also
invalidate the exact scope receipt. Active external ignore patterns remain
outside the selected policy.

The existing metadata capture helper is reused with a pure content-hash sink.
This lets a read detect changed ambient bytes without writing them into the CAS.
Historical receipt loading separately checks the stored artifact bodies. Source,
model, training and proof authority remain with their existing owners.

The function acquires a native datasets root or child lease, propagates combined
cancellation, and checks its deadline between phases. Individual Git metadata
queries retain the frozen ten-second process bound. Receipt reconstruction and
metadata queries can finish before an expired overall deadline is noticed;
this is cooperative phase-boundary enforcement, not a kernel wall-time limit.

The accelerate benchmark's opt-in `--semantic-manifest` route uses this check
when reconstructing the semantic manifest and observing planning roots. Its
integration tests cover complete inventory, declaration versus checked evidence,
mutated descriptors, stale source, changed ignore scope, read-only artifact
access, and cancellation after lease acquisition. A later filesystem change
still requires a new observation; the function does not lock the repository.
