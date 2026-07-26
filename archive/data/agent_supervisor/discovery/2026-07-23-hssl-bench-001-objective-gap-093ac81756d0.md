# HSSL-BENCH-001 Objective Protocol Packet Receipt

Date: 2026-07-24
Task id: HSSL-BENCH-001
Goal ids: HSSL-G011, HSSL-G012
Goal titles: Prove isolated worktree and state-root safety; Inventory runtime capabilities and identities
Objective heap: `docs/implementation/plans/hammer_symai_spacy_leanstral_benchmark_objectives.md`
Source finding: `/home/barberb/.local/share/ipfs_accelerate_py/benchmarks/hssl-20260723T235556Z/discovery/2026-07-23-hssl-bench-001-objective-gap-093ac81756d0.md`
Source fingerprint: `093ac81756d07889182d0a9638b157ae073686ce`
Objective markers: `HSSLEV0118D14`, `HSSLEV0125F83`
Todo vector key: `d362d4eeaf0a21e9`
Merge key: `3e0b8e4942c0352f`
Merge family: `goal_packet/benchmark_protocol/benchmarks/e434c88200e1`
Goal packet role: `packet_aggregate`
Covered sibling tasks: `HSSL-BENCH-004`, `HSSL-BENCH-005`
Work scope: `goal_subgoal_packet_aggregate; vector_ast_bundle`

## Finding Reconciliation

The aggregate source scan found neither executable evidence marker for the
HSSL-G011/HSSL-G012 protocol packet. The objective heap already split the gap
at the correct boundary: one work item proves that benchmark preparation
cannot damage an active checkout, and one inventories every optional runtime
before an arm is eligible. Both contracts share a dependency-free preflight
module and are implemented together without broadening into the corpus,
adapter, or robustness packets.

`benchmarks.logic_pipeline.capabilities.HSSLEV0118D14` and
`benchmarks.logic_pipeline.capabilities.HSSLEV0125F83` are now literal Python
function symbols bound to executable contracts. The objective heap records
their implementation evidence while both goal statuses remain active for
supervisor reconciliation.

## Worktree and State-root Safety Evidence

- `prepare_isolated_worktree` resolves a caller-selected base to its full
  commit before creating any run directory, then uses only
  `git worktree add --detach` with that immutable commit.
- Resolved run, worktree, active-checkout, and Git-common-directory boundaries
  are checked in both directions. Traversal, symlink escape, overlap, and an
  existing worktree target fail before Git preparation and are never cleaned,
  reset, or overwritten.
- Cache, corpus, objective-bundle, receipt, result, state, log, and worktree
  locations remain beneath one run-specific `RunPaths.run_root`; different run
  ids have disjoint state.
- Active HEAD, symbolic branch, and complete tracked/untracked porcelain status
  are captured before and after worktree creation. A change prevents receipt
  emission.
- `WorktreeSafetyReceipt` is immutable and strict. Its canonical JSON and
  SHA-256 bind the source and pinned worktree commits, detached status,
  `auto_merge=false`, active-checkout identity, state root, and every submodule
  gitlink read from the pinned tree. Preparation writes it exclusively as
  `receipts/worktree-safety.json`.
- The implementation contains no active-checkout clean, reset, stash, switch,
  checkout, merge, branch-creation, promotion, or automatic worktree-removal
  path.

## Runtime Capability and Identity Evidence

- `CapabilityInventory` requires exactly one record for each preregistered
  family: spaCy pipeline, SyMAI configuration, llm_router provider, Hammer
  solvers, Leanstral service/model, Lean/Lake toolchain, cache backend, and
  resource scheduler.
- Every `CapabilityRecord` is exactly `available`, `degraded`, or `unavailable`
  and carries nonempty provenance. Partial configuration, an explicit
  fallback, a missing probe, or a probe exception remains visible instead of
  disappearing from the inventory.
- Identity payloads are canonical JSON, deeply immutable, recursively
  secret-redacted, and bound with Python/platform/source identity into a
  canonical inventory digest. Executable probes use bounded argv-only version
  commands; model inference, optional-backend import, auto-install, and service
  startup are outside the preflight.
- Cache and scheduler identities are protocol-bound to the selected run's
  cache/state paths. An explicit production or cross-run path fails the
  inventory contract.
- `require_capabilities` accepts only the exact requested records in the fully
  available state. It rejects degraded and unavailable components rather than
  selecting another effective provider, parser, model, solver, or benchmark
  arm.

## Implementation Evidence

- `benchmarks/logic_pipeline/capabilities.py` contains both versioned schemas,
  evidence markers, strict records, canonical serialization/digests, safe
  probing, exact capability gating, isolation validation, detached worktree
  preparation, submodule capture, and exclusive receipt persistence.
- `benchmarks/logic_pipeline/__init__.py` exposes the stable public preflight
  API without performing a probe or filesystem/process operation during
  import.
- `benchmarks/logic_pipeline/README.md` documents the normative worktree and
  capability preflight alongside the frozen benchmark protocol.
- `tests/integration/benchmarks/logic_pipeline/test_worktree_isolation.py`
  exercises real disposable Git repositories with deliberately dirty tracked
  and untracked operator work, older pinned commits, detached isolated commits,
  no ref advancement or merge, two run roots, hostile paths, existing output,
  invalid revisions, and a spaced-path submodule whose pinned gitlink differs
  from the active checkout.
- `tests/unit/benchmarks/logic_pipeline/test_capabilities.py` exercises exact
  inventory completeness, all statuses, fallback identity, probe isolation,
  strict parsing, deep immutability, canonical digests, secret removal,
  fail-closed eligibility, and cache/scheduler scoping.

## Backlog Alignment

No child goal is needed. HSSL-G011 and HSSL-G012 are already the packet's two
bounded work items and the shared module is their intentional overlap. The
high-confidence bundle work order propagates successful HSSL-BENCH-001
validation to HSSL-BENCH-004 and HSSL-BENCH-005. The lower-confidence
cross-bundle HSSLEV02*/HSSLEV07* candidates are unrelated and were not claimed.
Generated todo, bundle, and vector status were not edited manually.

## Validation

Commands:

```text
python -m pytest tests/integration/benchmarks/logic_pipeline/test_worktree_isolation.py -q
python -m pytest tests/unit/benchmarks/logic_pipeline/test_capabilities.py -q
python -m pytest tests/unit/benchmarks/logic_pipeline/test_package.py tests/unit/benchmarks/logic_pipeline/test_contracts.py tests/unit/benchmarks/logic_pipeline/test_capabilities.py -q
python -m compileall -q benchmarks/logic_pipeline tests/unit/benchmarks/logic_pipeline tests/integration/benchmarks/logic_pipeline
git diff --check
```

Results on 2026-07-24: passed (`16 passed`; `21 passed`; `70 passed`; compile
and diff checks passed).
