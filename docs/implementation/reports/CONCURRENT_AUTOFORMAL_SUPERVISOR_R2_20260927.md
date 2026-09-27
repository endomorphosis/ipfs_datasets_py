# Native concurrent smoke R2: retained CLI failure

R2 stopped before native daemon construction and before either training or
conversion lane ran. Published supervisor 07804 rejected the harness flag
`--retain-worktree-artifacts`. The native argument parser returned 2; the guarded
child returned 1. No optimizer update, legal-IR target, evaluate timing,
conversion result, or concurrency measurement exists for this attempt.

The outer attempt took 48.186 seconds. All owned descendants were stopped and
reaped, and the compute lease was released. The 150 MB reservation
`4ea25ddadcb54fa1a797b01e469476cc` remains retained. After database closure,
60 files totaling 29,906,744 bytes remain; the earlier 1,005,930-byte live sample
was not the final artifact size. Source provenance checks passed.

R3 removes only the unsupported unused flag. The private fixture still uses
`--no-ephemeral-worktree` for retention. The 150 MB/8GiB/two-CPU/600-second bounds,
canonical logic pins, explicit published dependency, training parameters, and
success conditions are unchanged. The [preparation manifest](evidence/concurrent-autoformal-supervisor-r2-20260927/r3-preparation-manifest.json)
and exact corrected driver are retained with the failed attempt's receipts.

R3 has not run at this commit. The [evidence manifest](evidence/concurrent-autoformal-supervisor-r2-20260927/manifest.json)
binds the receipts and observations. This CLI failure supplies no legal
formalization or Lean-admission evidence. No Constitution span was processed.
