# Persistent recovery after the restart

The restart removed `/tmp/ir-lifecycle-integration-20261002`. Its Git
administrative index, branch and the completed artifact receipts survived.
The seven staged changes were recovered from that index into:

`/home/barberb/lift_coding/.worktrees/backend-pipe-lifecycle-20261002`

The existing branch `codex/backend-pipe-lifecycle-20261002` now contains
local commit **`826d94979180dd36cf6b2867aae0b2a077b2838f`**, with parent
`8de37ba8d216cd21a5d7134292de01d9e12c9a56`. Its worktree is clean. The commit
contains exactly the two modified and five added backend/test files from the
reviewed payload. Four package prerequisites remain unchanged. No other
worktree was repaired, pruned, reset or modified by this recovery.

All **99 focused lifecycle tests passed again**, with zero failures or skips,
from the persistent repository paths after the restart. The harness is an
unchanged copy of the preceding qualified harness with a new admission,
source locators and run directory. All thirteen admitted sources, nine
reviewed child-startup sources and the Python/`prlimit` executable receipts
matched. The parent observed 69 authored subprocess launches and only
`MainThread` at completion. The same bounded Linux/endpoint/child-startup
qualification limits apply; no native solver or model was executed.

The [machine handoff](restart_recovery_handoff.json) binds this recovery,
test result, commit and preservation checks. A verified incremental
[Git bundle](../../../../../../artifacts/codebase-ir-lifecycle-restart-recovery-20261002/backend-lifecycle.bundle)
also preserves the commit; it requires the baseline commit named above.
The older [Git handoff](git_candidate_handoff.md) remains unchanged as a dated
record of the previously uncommitted temporary worktree.

## Publication state

This is a local commit; no merge, push or parent gitlink update occurred.
Locally observed `origin/main` was
`4cfe89de936696cdae8c0435e5526bc49c99d86d`. The eleven scoped
payload/prerequisite paths retain their baseline bytes or baseline absence
there, so the backend changes have not appeared in that local ref. No fresh
GitHub state was fetched. The released integer checker still uses the separate
Codebase process fork and does not inherit this general-backend correction.

## Resume proof acquisition from recorded source versions

The new [proof-source observations](../../../../../../artifacts/codebase-ir-lifecycle-restart-recovery-20261002/proof-source-followup.json)
retain eighteen previously missing/differing owner snapshots and five
additional helper/dependency snapshots. These are static inputs, outside the
lifecycle run's admitted sources; they are not an accepted proof route.

A separate [frozen partial source selection](../../../../../../artifacts/codebase-ir-lifecycle-restart-recovery-20261002/frozen-proof-source-selection.json)
now pins twenty-seven source files and their static import inventory. It
selects the committed corrected backend, the later resource-safety variant,
the recorded proof foundations and additional import ancestors. Five
qualification slices identify protocol, reboot/memory telemetry, native
transport and indexed-currentness cohorts. Resolving their complete
dependency and test-source selection remains the first gate. This partial
selection has not been imported or executed as a proof route. Its general
process backend was exercised only by the focused lifecycle cohort.

Compared with the preceding observations, the verifier (`F007`), applicability
owner (`F061`) and scheduler (`F020`) changed. A later preflight also observes
the resource-safety owner (`F100`) differing from its original declaration.
Review frozen source cohorts and their tests rather than importing changing
live owners into a candidate. Keep each observation's timestamp and hashes.

The revised verification/applicability path additionally requires
`codebase_smt_execution.py`, `codebase_smt_protocol.py`,
`codebase_smt_compat.py`, `parsers/smtlib.py` and `syntax_core/contracts.py`.
Acquiring the old seventeen foundations alone cannot establish that expanded
dependency selection. Finish the dependency/import-origin inventory, select
reviewed versions, and issue a new candidate manifest before runtime proof
qualification.

Supervisor policy is operation-specific: the integer profile's typed pipeline
defaults to supervisor evidence enabled, while the revised `@2` historical
verification/applicability producers explicitly disable it. Record both
profiles and qualify their behavior separately. Do not generalize one setting
to the entire route or silently substitute a supervisor-free profile.

## Restored release locators and model preservation

Another workflow restored the release checkout under
`.worktrees/ir-release-datasets-20261002`. Six historical release files have
their exact original bytes at that persistent locator. This recovery only
read those files. An explicit root-override file lets the read-only release
auditor use that locator while preserving the original manifest.

The [relocated preflight](../../../../../../artifacts/codebase-ir-lifecycle-restart-recovery-20261002/relocated-release-preflight.json)
still rejects the original release: **264 of 270 declarations match**, with
`F007`, `F015`, `F020`, `F061`, `F062`, `F100` differing. It reports all twelve
inventory cells and twenty-eight asset associations matching. No manifest
was repinned to turn the audit into success.

The original twenty-six checkpoint/vector/descriptor assets, thirteen
inventory documents and the preceding 481/17/30/82/62 receipt sets remain
preserved. CodebaseIR, SecurityIR, LegalIR and IntentIR still have independent
8D/384D/768D decoder, token/span, inventory, storage and Hub plans. Original
donor embeddings and decoder weights remain available for the planned
distillation. This recovery does not train, generate embeddings, create
databases or promote a model.
