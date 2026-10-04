# Resource recovery and bounded native SMT qualification

The next persistent candidate is saved at
`.worktrees/proof-resource-admission-20261003`, on branch
`codex/proof-resource-admission-20261003`. Local commit
`7a40a59c80ae68bb64cad4f01622c4bf43c880b8` has parent
`97d9ddc80186ae2666a011c770d5fbb7a6413146` and twelve changed files.
The worktree is clean. A verified incremental Git bundle preserves the commit
with that parent as prerequisite. No merge, push or parent gitlink update was
performed.

The [machine handoff](resource_native_handoff.json) binds the source admissions,
test results, commit, bundle, preservation checks and remaining gates. The
earlier [protocol handoff](protocol_admission_handoff.md) retains its original
source generation and qualification scope.

## Scheduler and memory telemetry: 204 passing cases

The candidate selects the reviewed 90,191-byte scheduler generation
`69f13438f2bbeb33056c50f106aa0e8a7cd86bc092a17cbfc29200365ac5df2e`.
Its change from the earlier frozen scheduler allows explicit construction to
reconfigure an idle pool while refusing ordinary operations from a facade that
still holds old capacities. A stale object can no longer silently restore its
cached limits after another client changes the shared configuration.

The selected cohort reuses 162 existing cases and adds 42 regressions. All
**204 cases passed**, with zero failures or skips. Coverage includes boot/PID
identity, retained live descendants, stale facade operations, state durability,
atomic replacement and rollback, bounded waiting/cancellation, pressure
backoff, visible ancestor memory boundaries, and repaired telemetry cooldown.
The new cases exercise invalid ASCII/NUL bytes, overlong whitespace before
stripping, unreadable ancestor controls, valid counters at the 4,096-byte
boundary, and root/child backoff without releasing live work.

This run admits seventeen project/test files and the earlier pinned external
Python dependency profile. Guarded loaders verify each raw source read and
compile those same bytes. Test modules preload through that guard; assertion
rewriting and plugin/conftest discovery are disabled. There were zero blocked
imports or effects and only the main thread remained at completion. State and
synthetic proc/cgroup fixtures are private to this run. Self-process and kernel
boot identity reads, POSIX locks, fsync and joined test threads are declared
effects. Real GPU/psutil collectors were unnecessary.

The first run had 121 passing and 83 failing cases because the harness supplied
zero optional GPU/unified capacities, which the API correctly rejects. The
failed run and original harness are retained. Clearing those optional settings
fixed the harness; the scheduler and test sources did not change. Four native
cross-process cases and two hammer/portfolio cases were explicitly deselected
and remain separate qualification work.

## Fresh native baseline: 12 passing cases

Pinned Z3 4.15.4 and CVC5 1.3.3 ELF targets each executed one satisfiable and
one contradictory integer arithmetic example. All four logical calls used
three phases: version, verdict, and model or unsat core. The twelve expected
native phase launches completed, and all **12 selected test cases passed**.
Satisfiable models assign the requested integer value; contradictory examples
return the expected named core. Receipt replay and changed-input/relaxed-limit
rejection added no native launches.

Every phase used the pinned `prlimit` helper, a private workspace, explicit
argv, the producer's minimal `C` locale environment, a 128 MiB per-process
address-space limit and sampled process-tree RSS guard, and a 16 MiB file
limit. The five-second logical budget includes
admission and all phases; version discovery is capped at two seconds. The
parent audit permits only the selected helper/ELF targets and bounded arguments,
verifying their bytes immediately before launch. The discovery shell launcher
is recorded but was not executed. All phase workspaces were cleaned, all four
private schedulers drained, and only the main thread remained.

The native cohort admits thirty-six project/test sources, including the earlier
corrected general backend, selected scheduler and unchanged reviewed resource
helper. It exercises arithmetic examples and bounded transport/receipt replay.
It does not qualify source-to-code correspondence, the integer-profile producer,
supervisor operations, all fault/disagreement branches, arbitrary shared-library
execution or repository proof authority. The source-bound verification and
applicability producers still require their own admitted cohorts.

## Proof catalog acquisition and next gates

The draft now includes the missing `codebase_verification_projection.py` and
`codebase_verification_queries.py` helpers and their three authored test modules.
All five were captured as authenticated source snapshots and copied exactly.
The query helper changed independently between audit and acquisition; the
selected `a53b470...` generation is recorded explicitly. Its API compatibility
and database execution remain unqualified. No database was opened in this stage.

The [gap tracker](../../../../../../artifacts/codebase-ir-resource-admission-20261003/gap-status.json)
specifies the next acceptance checks:

1. Qualify Git/file-backed DuckDB repository currentness using private repositories
   and stores: changed tracked/index/untracked bytes, independent worktrees,
   extraction/publication races, ABA generations, restart hydration, transaction
   rollback and cancellation. Pin the actual Git/DuckDB/CID/project origins first.
2. Review the captured catalog helper generation and qualify normalized historical
   discovery with the existing UNKNOWN-evidence fixture. Test key/domain exactness,
   omitted or corrupt rows, monotonic epochs, append cursor invalidation, replay,
   capacity rollback and bounded traversal. Native key/applicability cases remain
   a separate cohort.
3. Qualify source-bound native integer verification, model replay, error and
   disagreement handling, resource pressure and cross-process recovery. Preserve
   operation-specific supervisor policy: integer compilation retains its default;
   revised verification/applicability producers disable supervisor evidence.
4. Add typed serving/routing contracts for IR family, width, decoder task/role,
   checkpoint/codec/tokenizer/encoder generation, token/span profile and vector
   receipt. Historical discovery associations remain historical when serving
   heads advance. Qualify twelve separate store/lake/artifact roots, writer locks
   and cross-cell rejection before creating or promoting the cell stores.
5. Bind actual IntentIR documents/actions/conditions to exact current repository
   heads, units, contracts and domains. Reobserve at effect time and distinguish
   current facts, desired goals, planned post-state and observed post-state.
   Unresolved interpretations and historical conditional evidence grant no
   unconditional planner authority.
6. Qualify explicit locally pinned DuckLake extension loading and outbox delivery,
   then extend source/proof evidence delivery beyond discovery metadata. Reconcile
   selected source/assets with the integration target before accepted manifests,
   merges and reviewed gitlink propagation.

## Model and reconstruction work remains separate

CodebaseIR, SecurityIR, LegalIR and IntentIR still have independent 8D, 384D and
768D cells. Their thirteen inventory documents and twenty-six original inherited
assets match their earlier receipts; all seven completed stages remain intact.
No model was loaded, no embedding regenerated and no training or promotion ran.

Before training the 768D decoder, authenticate the learned 8D/384D donor bodies
and cached embedding/sample associations, then pass held-out 384D reconstruction
and transfer gates. Good training loss alone does not establish reconstruction.
Legal text evaluation must separately report original-byte recovery, generated
surface recovery, LegalIR structure and semantic preservation. Source copying or
retained residual recovery needs its own label. Free-generation evaluation must
withhold the original source so its score measures decoder reconstruction.

Larger token/span profiles and the 768D encoder require aligned input projections
and explicit family decoder contracts. Preserve the old assets as teachers and
comparison baselines, reuse learned decoder bodies, and train new projections
and longer-span capacity progressively. The resource/native results above do
not establish these model tasks.
