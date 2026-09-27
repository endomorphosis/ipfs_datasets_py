# Native concurrent smoke R3: retained setup refusal

R3 selected and claimed the real smoke task, then stopped in native implementation
setup. Its non-ephemeral setting conflicted with the default worktree root. The
native guard refused dispatch; provider invocations and effect claims remained
zero. The task settled as blocked and its claim was released. Neither training
nor conversion ran. A placeholder validation field says passed=true alongside
attempted=false and reason=not_run; this is not validation evidence.

The outer attempt took 74.339 seconds; native supervisor execution took 28.452
seconds. All owned descendants exited. The 150 MB reservation
`c258894ac4f44b09bc550265d9cc838d` remains retained with 93 files totaling
49,188,906 bytes. The exact refusal appears in retained Portal JSONL lines 2–3;
the [diagnostic](evidence/concurrent-autoformal-supervisor-r3-20260927/setup-refusal.json)
records unchanged source hashes and confirms absence of both lanes.

R4 explicitly sets `--worktree-root` to the newly created private repository,
while keeping `--no-ephemeral-worktree`. The factory forwards both arguments,
and the native guards explicitly permit equality of worktree root and repository
root. The driver requires this repository to be a canonical, nonsymlink child
of its owned runtime. Pooling remains disabled. This uses the supported direct
fixture path and retains artifacts without changing the native guard or callbacks.
It does not point the native worker at a shared checkout.

The [R4 manifest](evidence/concurrent-autoformal-supervisor-r3-20260927/r4-preparation-manifest.json)
records the corrected driver and unchanged training/conversion configuration.
The 150 MB, 8 GiB, two CPU, and 600-second bounds remain. R4 has not executed
at this commit. The [evidence manifest](evidence/concurrent-autoformal-supervisor-r3-20260927/manifest.json)
binds the retained observations. No legal-IR timing, optimizer update, or
concurrency result exists for R3. No law is admitted or formalized; no
Constitution span was processed.
