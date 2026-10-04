# Backend pipe-worker correction and integration handoff

The isolated backend candidate now rejects successful native exits when an
output reader fails or a reader/input writer remains alive. The earlier copy
could return `ok=True` with incomplete pipe ownership or capture. The
[corrected source](../../../../../../artifacts/codebase-ir-backend-lifecycle-qualification-20261002/candidate/v2/ipfs_datasets_py/logic/backends/process.py)
passes 99 focused tests. A
[seven-file release patch](../../../../../../artifacts/codebase-ir-backend-lifecycle-qualification-20261002/release-payload.patch)
applies cleanly to the explicitly pinned local datasets baseline, using a
temporary Git index. The active worktree, index and refs were not changed by
that check.

The [machine handoff](backend_lifecycle_qualification.json) binds the candidate,
tests, runtime observations, patch and preserved assets. This advances the
[backend transition](backend_profile_transition.json) with a tested correction;
full installed-owner closure, fresh native integer checks, proof-index/Intent
qualification and release integration remain pending. All model cells keep
their prior state.

## Measured behavior

| Source/cohort | Passed | Failed | Skipped | Interpretation |
| --- | ---: | ---: | ---: | --- |
| Original candidate, existing lifecycle tests | 76 | 0 | 0 | Existing tests missed the pipe failures |
| Original candidate, first seven regressions | 3 | 4 | 0 | Four false-success cases reproduced |
| Corrected candidate, first combined cohort | 83 | 0 | 0 | Initial correction verified |
| Original candidate, extended 23 regressions | 4 | 19 | 0 | Failure reporting, control propagation and worker-completion gaps reproduced |
| Corrected candidate, extended combined cohort | 99 | 0 | 0 | 76 existing plus 23 regression cases pass |

The final [corrected run](../../../../../../artifacts/codebase-ir-backend-lifecycle-qualification-20261002/runs/extended-all-v2-02/result.json)
records 69 authored native launches and only `MainThread` at completion. The
[baseline regression run](../../../../../../artifacts/codebase-ir-backend-lifecycle-qualification-20261002/runs/extended-regression-v1-02/result.json)
retains the nineteen expected failures. Test fixtures release controlled
stalls, reap their native children, join host/worker threads and check that
owned pipe descriptors close without changing the parent FD targets.

Coverage includes failed writer startup, genuinely full stdin pipes under
timeout/cancellation, stdout/stderr read faults, stdin write/flush faults,
stdout/stderr/stdin close faults, original-instance worker control exceptions,
surviving reader/writer rejection, empty live-reader captures and genuine
BrokenPipe compatibility. Controlled pipe faults wrap actual authored native
process pipes; they are not solver executions.

Two intermediate extended runs stopped before collection because the tightened
harness misidentified a built-in pytest plugin class. Those exit-3 logs remain
saved. The corrected harness distinguishes modules from plugin classes; these
startup errors are separate from backend failures and passing runs.

## Scope of the correction

Candidate V1 is 68,367 bytes, SHA256
`9035ba1982cf5fbd0db40ec994a3829902d9f4a25cc7aeb0c0ae2705f233cbf5`.
Candidate V2 is 69,941 bytes, SHA256
`fe75b7e8a38bea59c53a73e2ea062fc6109fb867832d3c342624db27412c8c5e`.
V2 records reader and non-BrokenPipe writer errors, joins/checks all pipe
workers, refuses success through the existing failure flag, and omits captures
from live readers. Control exceptions propagate as their original instances
after attempted cleanup. Public signatures, public fields, schemas and
translation mathematics remain unchanged.

The generic `resource_limit` reason for these results denotes failed pipe
ownership/capture; it is not evidence of measured RAM exhaustion. The existing
integer checker rejects errors/resource failures before parsing stdout, so
partial captures cannot create terminal conditional evidence through that
path. Fresh native proof-profile qualification remains required to admit the
new backend identity.

Per-worker joins do not establish one end-to-end deadline. The owner refuses
success for live workers and avoids closing buffered pipes held by them; it
does not guarantee reclaiming every stalled worker. Sampling descendants/RSS,
retained-output limits and post-execution workspace accounting retain the
limits documented in the earlier transition.

## Bind the actual test environment

The copied package slice contains the exact root initializer, router
dependencies, logic initializer and process owner. The backend directory
remains a namespace. The IPFS backend router is copied for the root's presence
check and is not imported. Tests bind the copied process location and SHA256;
the final harness checks package/test receipts before and after execution.
These endpoint matches are not continuous or atomic executed-byte attestation.

The parent uses `/usr/bin/python3.12 -I -S -B`, explicit installed dependency
roots, pytest 9.1.1, no conftest/cache provider, disabled plugin autoload,
cleared explicit `PYTEST_PLUGINS`, and recorded plugin origin checks. Existing
tests invoke the real Python executable for children with ordinary reviewed
system startup. The profile retains four system `.pth` files, the system
customization/Apport hook and selected helper receipts. Child launches use
fresh private workspace homes and exclude `PYTHONPATH`/`PYTHONUSERBASE`.
Parent isolation must not be read as child `-S` isolation.

Interpreter, `prlimit`, selected startup files and observed package/dependency
origins are bound to receipts. The module inventory is observational; it does
not attest all transitive Python/native libraries or child activity. No
installed-package changes, solver/model execution, database operation or
training was performed.

The original seven-case regression source and earlier harness versions remain
retained under `inputs`. Earlier run records retain their original paths and
hashes; the handoff maps superseded source paths to the exact retained bytes.
The original runs' `unchanged_during_run` label means their implemented
before/after checks. Final runs use the precise endpoint label.

## Integrate the complete tested payload

The patch check uses explicit baseline
`8de37ba8d216cd21a5d7134292de01d9e12c9a56`, a dated local `origin/main` object.
This is not a claim about the latest GitHub state. The release payload is:

1. Replace `logic/backends/process.py` with the complete corrected owner,
   including the earlier local resource/descendant controls missing from Git.
2. Update the existing lifecycle test with its retained RSS cases.
3. Add the existing exception-cleanup, descendant-session, file-limit and
   parallel-limit tests unchanged from the acquired copies.
4. Add the extended pipe-worker test at
   `tests/unit/logic/backends/test_process_pipe_workers.py`.

These are seven repository files. Four unchanged initializer/presence owners
match the explicit baseline and remain pinned prerequisites. A temporary
`GIT_INDEX_FILE` held `read-tree` state for the baseline; `git apply --cached
--check` succeeded there. No live index or ref was used for a patch mutation.
This proves scoped patch applicability, not installed candidate import or
release qualification.

Acquire the payload in an isolated Git candidate, verify the prerequisite
owner bytes and exact test origins, then complete the selected BT00/BT01
dependency/acquisition gates. Rebase to a newer target only with fresh source
comparisons and checks justified by its changes. Carry these lifecycle results
as BT02 evidence, retaining BT03 aggregate budget and BT04 fresh native integer
qualification requirements. BT05 proof-index/Intent applicability and BT07
accepted manifest/parent gitlink integration remain separate.

## Preserve the model work

The preservation audit rechecks all 26 original checkpoint/vector/descriptor
assets, all thirteen inventory documents and the prior 481, seventeen and
thirty-file verification sets. They match their existing receipts. None was
rewritten or loaded into a model. The original rejected release manifest and
the earlier unqualified candidate manifest remain unchanged.

Legal, Security, Intent and Codebase retain independent 8D/384D/768D paths,
decoders, token/span profiles, registries, DuckDB/DuckLake stores and Hub
destinations. The backend correction changes future checker/cache identities;
it does not reset model training or alter cached embeddings. Old proof records
remain historical with their original bindings, while any admitted new
conditional evidence requires fresh current-source/native checks. Decoder
distillation and Legal text reconstruction keep their independent evaluation
and promotion gates.
