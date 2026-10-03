# Bounded header-model checker

The explicit native-leased-bounded-header-checker@1 adapter reuses the existing datasets process runner and requires a native parent resource lease. It enforces a shared deadline across admission, a bounded cached version probe and each query, passes the exact SMT text, bounds accepted combined output, and refuses late, truncated, cancelled, resource-exhausted or unclean results.

The profile requires Linux procfs and prlimit. RLIMIT_AS and CPU limits are per process; sampled process-tree RSS can overshoot. Owned process groups are terminated on timeout/cancellation; escaping groups are not sandboxed. Cleanup can extend return latency, and late results are rejected. It grants no source, mutation or completion authority. Existing optional solver behavior remains unchanged unless this adapter is selected.

All38 controls passed against the actual checkout:34 authored adapter controls and4 real subprocess controls, including installed Z3, resource-limit observations, output flooding and timeout cleanup. Tests use authored native lease supervision and do not qualify host-default resource admission. No checkpoint/provider/benchmark run is part of this package.
