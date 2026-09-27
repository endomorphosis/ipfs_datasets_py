# Native concurrent smoke R4: sealed-launcher handoff failure

R4 passed the private-worktree setup guard, then stopped before training or
conversion. Its installed-dependency metadata probe failed to start with
`FileNotFoundError` / `dependency_probe_process_unavailable`. The empty missing
and incompatible requirement arrays are not evidence that dependencies passed:
the probe never executed. No installation was attempted.

Inspection found a concrete subprocess handoff defect. The published runtime
creates sealed Python/Ruff executables addressed through `/proc/self/fd/...`
and returns their exact descriptors in `launcher_receipt.inherited_fds`.
The dependency probe's `Popen` call did not pass those descriptors, so normal
subprocess descriptor closure made its executable path unavailable. The native
launcher's self-test and actual validation command have the same omission.
The local Python interpreter exists; choosing another interpreter does not
repair the missing handoff.

The planned correction forwards only the receipt-owned descriptors through all
three first-hop calls, retaining normal closure of unrelated descriptors and
the launcher context lifetime. It does not alter validation profiles, accepted
control-plane descriptor handling, admission rules, or automatic provisioning.
Focused real-subprocess regression results and publication provenance will be
recorded separately before the next native attempt.

R4 took 62.155 seconds overall. All owned descendants exited. Its 150 MB claim
`ace678f9047a4f399de1c05893cd33ae` remains retained with 94 files totaling
48,420,477 bytes. The task remained in progress with a deferred dependency
preflight; provider dispatch and attempt consumption were false. No lane,
optimizer, bridge-evaluate, or concurrency result exists for this attempt.

The [evidence manifest](evidence/concurrent-autoformal-supervisor-r4-20260927/manifest.json)
binds the exact audit, supervisor receipt, Portal events, and final observation.
No law is admitted or formalized by this failure; no Constitution span was
processed. Lake remains the sole source of Lean-admission evidence.
