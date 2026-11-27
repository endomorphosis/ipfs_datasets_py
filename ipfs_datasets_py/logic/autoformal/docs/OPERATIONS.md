# Operations and evidence ownership

## Agent-owner pauses and independent continuations

Use the existing supervisor's metadata command when one agent stops while
other work remains. This does not launch a second supervisor or restart a
worker:

```sh
python scripts/ops/legal_ir/run_autoformal_supervisor.py agent-turn-recovery \
  --inputs frontier.json --output recovery.json
```

For goal-aware recovery, supply `legal-ir-agent-turn-frontier/v2`. In addition
to the original tasks, observations, policy holds and finite parallel width,
it requires:

- `goal_control`: the goal ID, common authority ID, original owner task ID,
  and explicit `intent`/`observed` records. Each record carries the same goal
  and authority, a directive ID, ordered revision and state. Revisions must
  belong to that one authenticated goal-control sequence; unrelated counters
  or an agent's prose are not resume evidence.
- `operation_history`: original `{task, observation}` pairs, including exact
  thread/turn IDs, scopes, spent attempts and outcomes. Persist returned
  entries even when tasks leave the current frontier. Aliases cannot replay
  an existing attempt; live or uncertain owners retain scope and capacity.
- `reconciliation_history`: original `{request, status, result}` records.
  A newer active directive can identify an older saved **pause** and produce
  one `reconcile_saved_goal` request for the existing owner. An outstanding
  request remains outstanding; changing a frontier or resume ID cannot retry
  the same pause cycle. A new cycle must follow the prior closed directive.
- `execution_hold`: explicit `null` or the original run-wide hold's `kind`,
  `reason` and `evidence_refs`. Usage, policy or resource restrictions remain
  effective across resume directives and disjoint tasks.

An explicit pause suppresses new work. Unknown, blocked, completed or
contradictory goal state requires owner reconciliation. Already-active state
needs no resume. Independent tasks can be selected while an older saved pause
is reconciled, but only with their existing authorization, accepted dependencies,
remaining attempts, available capacity and disjoint declared scopes. Preserve
returned policy holds as well as both histories. V1 inputs remain supported for
old turn-only callers, but reject V2 control fields rather than silently ignore
them.

The result is scheduling DATA: `dispatch_authorized`, `retries_authorized`,
`workers_started`, `owner_resume_authorized`, `goal_mutation_authorized`,
`goal_complete` and `admitted` remain false. The existing owner must verify the
expected goal/owner observation before applying a reconciliation request, and
use its existing atomic claims, Source leases and runtime admission before any
selected work. No request authorizes an explicit user pause override, quota
bypass, legal approval or corpus admission. Input and output files must differ;
output creation is exclusive and existing evidence is never overwritten.

### Ingest an observed provider turn

Use the same owner and existing V2 frontier:

```sh
python scripts/ops/legal_ir/run_autoformal_supervisor.py agent-turn-recovery \
  --inputs frontier.json --observation owner-turn.json --output checkpoint.json
```

`owner-turn.json` has exactly these fields, using actual original IDs/error and
saved evidence references:

```json
{
  "schema": "legal-ir-agent-turn-observation/v1",
  "task_id": "existing-task",
  "thread_id": "existing-thread",
  "turn": {"id": "existing-turn", "status": "failed", "error": {"code": "policy_refusal", "message": "Original refusal"}},
  "cleanup_confirmed": false,
  "accepted": false,
  "evidence_refs": []
}
```

The task must already have a charged attempt and a matching current or retained
owner observation. Supported provider states are `inProgress`, `completed`,
`failed` and `interrupted`; absent/ambiguous state is not terminal. Cleanup and
acceptance are never inferred. Keep them false without the existing owner's
independent evidence. Live owners remain exact polling targets. A refusal and its
original evidence stay held across aliases, resume directives and duplicate
delivery; explicit pauses and run-wide usage/resource holds remain effective.

Retain the whole output and pass its `next_frontier` into the next existing
scheduling call. It includes the updated observation, policy holds and both
histories; exact duplicate events preserve spent counters and the next frontier.
Verify `observation_checkpoint.input_frontier_sha256` against the current immutable
frontier before existing atomic claim/admission. Event and next-frontier digests
are also included. This adapter does not authenticate its own provider metadata
or mutate the task/goal store.

Observation mode requires `--output`; the three paths must differ. Output creation
is exclusive, with file and directory fsync and post-sync identity checks before
success. Failure returns code 2, starts no work and may leave a partial output.
Preserve it: existence alone is not a successful commit, and failed output must
not drive a claim or automatic repeat. Existing planning-only stdout mode remains
unchanged when `--observation` is absent. Local software qualification passed 95
tests and 171 subtests; no live provider recovery was performed.

## CLI4 separate original custody and retained failures — 2026-11-15

The audited corrected Source5 operation installed two changed bodies and recaptured three same-byte bodies with fresh identities; its separate readback closed. Separate original A144v02 and H34 cohorts passed independent audits: 144 selected cases in 3.934s and 34 new health cases in 1.413s, each with zero failures/errors/skips. Their original Source R+A, Native-resource, sampled-process and genuine-wait custody closed separately in 168.173s and 168.301s before each initial 420s cutoff.

Each durably released only its own 16MiB: A144's 462 files / 4,697,191 bytes and H34's 1,385 files / 3,469,714 bytes. The first failed A144's 16MiB remains retained; the earlier corrected Source queue timed out at 300s with zero writes and all acquired scopes closed.

CPU1, memory1536MiB, process4, storage16MiB, productive300, ledger60, shared Source60 and initial420 remain unchanged, without retry or deadline renewal. Main15, private immutable@2 SDK/worker, full A owner/driver/template transition and all private-asset/runtime holds remain separate. [Selected source/software evidence](../../../../workspace/test-logs/federal-corpus-audits/legal-ir-native-physical-R-CLI4-selected-software-qualified-20261115-v01/qualification-summary.json).


## G14 two-literal fix and retained setup-failure boundary — 2026-11-15

The existing embedded observation owner referenced two import-scope constants that it had never defined. The intended physical-R CLI4 probe therefore stopped with two setup errors in the legacy parser before reaching the proposed CLI4 call. That failed 16MiB claim stays retained and nondurable; it is not a CLI4 feature reproduction.

The minimal fix adds only the archived-import and read-only-import scope literals already defined by the unchanged driver (289 bytes). All owner function bodies remain identical. Original Source2 adoption and a separate independent readback bind the two current A source files. No new flag, schema, backend, import permission or resource authority is introduced.

A fresh original generic run passed 14 selected software controls in 0.399 seconds: 12 new scope/matching/no-effects/count-guard cases and 2 existing parser/backend-refusal regressions, with zero failures/errors/skips. The 211 declared source pins remained exact; this is not proof of all runtime import origins. Original Source R+A, Native, sampled-process and genuine-wait custody closed in 155.635 seconds before the initial 420-second cutoff. The run durably released its own 16MiB promise after 29 sealed rows plus the seal, 30 files / 142,436 bytes.

These are constructor and literal-validation controls. They do not execute native database observation, qualify the physical-R/namespace port, reproduce CLI4 CALL failures, or grant model, statutory, Lean, corpus, SDK or Source-generation admission. CPU1, memory1536MiB, process4, productive300, shared Source60, initial acceptance420 and ledger60 stay unchanged, with no automatic retry or deadline renewal. Peer sections, 119 owners, 24 task IDs/states and runtime/private-asset holds are preserved. [Exact selected 14 evidence](../../../../workspace/test-logs/federal-corpus-audits/legal-ir-native-owner-import-scope-G14-qualified-20261115-v01/qualification-summary.json).


## R56 original32MiB/work120 with initial420 custody — 2026-11-15

The current release-v3 source-only batch covers the release coordinator, validate_uscode_corpus_release CLI and its maintained owning controls. The opt-in transport/closure path preserves the default domain and legacy request identity, checks the literal packet policy, and validates complete ordered chunk transport and mixed physical closure using reviewed test components. These are software behaviors, not actual US Code, Native Lean, model or corpus admission.

One fresh original run selected 13 functions and passed 56 exact natural cases in 33.61 seconds, with zero failures/errors/skips. The result and execution records and full JUnit classname/name/parameter-ID order were independently joined. The explicit source frontier contains 198 pinned files, checked unchanged; no raw import-origin stream establishes that every runtime import belonged to that frontier. No old 56/155/146 outcome is pooled or transferred.

Original Source R+A, Native, sampled-process and genuine-wait custody closed in 189.529 seconds, before the initial 420-second acceptance cutoff. Its own 32MiB promise was durably released after 61 sealed rows plus the seal, 62 files / 6,572,203 bytes. The existing CPU1, memory1536MiB, process4 and productive 120-second request limits stay unchanged. The reviewed helper uses one shared 60-second Source-admission cutoff inside that initial 420 acceptance clock, without deadline renewal, hard-preemption claims or a new runtime grant.

This publication preserves all current peer sections, 119 owners, 24 task IDs/states, retained failures and private-asset/runtime holds. Source-generation, delegated immutable@2, actual live SDK cleanup, full-import qualification, native Lean and real corpus/model/training/legal validation remain separate gates. [Current 13/56 exact evidence](../../../../workspace/test-logs/federal-corpus-audits/legal-ir-current-release-v3-source-only-R56-qualified-20261115-v01/qualification-summary.json).


## Cleanup146 retained-failure and Source guard boundaries — 2026-11-15

The current immutable-source qualification@1 cleanup changes were adopted in the published worktrees through the original four-target Source operation and a separate audited readback. The new completed-failed-retained profile is cleanup-only: it preserves current-row, process, Native, source, request and original-deadline checks; it grants no passed receipt, repair adoption, retry or storage authority.

Fresh GREEN146 ran all146 exact selected owning controls (40 SDK and106 CLI, including the prior17+54 regressions plus23+52 new cases) in one original generic CLI run:146 clean JUnit records, zero failures/errors/skips,6.09seconds. Source, Native, process and genuine-wait custody closed before the initial420-second acceptance cutoff (178.700seconds). Its own16MiB promise was durably released after680 files/2,551,287bytes. Modeled proof frames inside these software controls do not establish a genuine live SDK cleanup lifecycle.

The earlier RED2 reproduced two expected CALL failures under the previous source bytes; its own16MiB failure claim remains retained and nondurable. The separate previously published71 result remains historical, without pooled or transferred qualification. The four-target Source guard now keeps55 strict fences and captures exactly10 known unselected documentation files under both original Source scopes, then checks them unchanged through the writes and final read. A separate READ records its own fresh interval. This permits unrelated peer prose before admission without authorizing any documentation write by the code actor.

CPU1, memory1536MiB, process4, storage16MiB, productive300 and ledger60 are unchanged; one shared60-second Source-admission cutoff stays inside the initial420-second acceptance deadline without renewal or automatic retry. Existing runtime holds,119 owners,24 task states and physical200/next201/9,800 remaining at generation2of2 are preserved. FullSDK95/SourceGen/raw7, actual SDK timeout cleanup, private delegated immutable@2 SDK/worker/Main and mapped preparation remain separate unqualified gates. No model, legal, Lean, native-corpus or activation gain follows. [Exact146 evidence](../../../../workspace/test-logs/federal-corpus-audits/legal-ir-current-immutable-v1-cleanup146-qualified-20261115-v01/qualification-summary.json).


## Cleanup71 Source scheduling and retained-failure boundaries — 2026-11-14

The four cancelled-retained cleanup sources were installed in the published worktrees through the original Source operation and separate readback. A private current-policy fault in one R owning control was then restored after its refusal/no-write assertions through a separately audited one-target Source operation. The SDK, CLI and strict origin/current-state guards retain their reviewed limits.

Fresh P4 ran exactly17 SDK and54 CLI cleanup owning controls:71 clean JUnit records, zero failures/errors/skips,3.6seconds. The original generic CLI route closed Source, Native and process/wait custody before the initial420-second cutoff (158.901seconds); its own16MiB promise was durably released after322 files/616,444bytes. These are selected software controls with modeled proof frames, not a genuine SDK timeout-cleanup lifecycle or a complete SDK/SourceGen qualification.

Earlier P1/P2 Source-admission refusals ran no CLI tests. P3 reached71 call passes but one teardown error; its failed16MiB claim stays retained. The new shared60-second Source-admission cutoff is inside one initial420-second acceptance deadline, with no renewal. CPU1, memory1536MiB, process4, storage16MiB, productive300 and ledger60 remain unchanged. This is no hard preemption or guaranteed worst-case setup/work envelope.

The old C4 SDK timeout and abnormal owned-holder close remain historical failure evidence: no qualified worker report, actual underlying execution unobserved, and no normal Source@2 closure. Complete95/raw source-role execution, genuine SDK cleanup integration, parent delegation and completed-failure cleanup remain separate gates; the latter private proposals gain no qualification here. Runtime holds,119 owners,24 task states and physical200/next201/9,800 remaining at generation2of2 are preserved. No model, legal, Lean or native-corpus gain follows. [Selected71 exact evidence](../../../../workspace/test-logs/federal-corpus-audits/legal-ir-worktree-cleanup71-qualified-20261114-v01/qualification-summary.json).


## Cold SDK Source getter preserves authenticated import order — 2026-11-14

The SDK public Source helper preserves the authenticated control-root then datasets-root import order. The 303-byte correction keeps its unguarded legacy branch and strict origin guard. The SDK and its additive owning tests were installed through the original two-target Source operation.

The guarded cold-import regression first reproduced the original import refusal. Fresh guarded and legacy regressions now both pass under one original Native request with the unchanged 16MiB bound, closed Source/process/wait custody and durable release of its own promise. The first failed C81 SDK invocation and retained RED evidence remain preserved.

The two isolated child controls exercise real normal imports without entering Source leases. A fresh actual C81 SDK worker validation, raw source-role execution and Source-generation approval remain separate gates. Runtime holds, all119 owners,24 task states, physical200/next201/9,800 remaining and original budgets are preserved. [Selected import-order evidence](../../../../workspace/test-logs/federal-corpus-audits/legal-ir-cold-public-source-order-20261114-v01/qualification-summary.json).


## Immutable-source qualification uses existing owners and bounded separate runs — 2026-11-14

Explicit immutable-source qualification authenticates a sealed control snapshot and Python execution subjects through the SDK and worker. Default repair still requires a changed Python body. Complete plan reconstruction, original source/namespace guards and execution evidence remain strict; a source-only receipt supplies no repair adoption or technical source-generation approval.

The unchanged former RED probe passes. Separately, 36 selected SDK controls pass across four disjoint runs, 65 existing namespace/operational regressions pass, the whole 94-case SourceGen owning file passes, and 20 reviewed-parent metadata controls pass. Each uses its own original Native request and 16MiB bound, with closed Source/process/wait custody and durable release of only its own promise. Inner fixture lifecycle statements remain fictional DATA; the original RED failure, zero-test pregrant refusal, observer-only no-gap stops and pre-CLI Source refusals stay preserved.

Runtime remains held. Genuine cold-worker/raw7 qualification, technical source-generation approval, the 8D/384D/768D/4096D model lineages, statutory meaning and Lean/corpus admission remain separate gates. Preserve peer progress, all119 owners and24 task states, physical200/next201/9,800 remaining, generation2 of2, holds and original budgets. [Selected qualification evidence](../../../../workspace/test-logs/federal-corpus-audits/legal-ir-immutable-source-qualification-20261114-v01/qualification-summary.json).


## Existing namespace and strict unissued-template handling qualified — 2026-11-14

Ordinary V5 validation now carries the existing sealed control namespace through its plan and worker. The operational repair remains intact. Installed Pytest and current SDK source references use the existing SDK file reader where appropriate; health, source-origin, archive and authorization guards remain strict. A fixture ID now stays stable across relocated templates, with an explicit ID-only rejection test. This closes the previously private namespace and unqualified whole-SourceGen engineering gaps at the new SDK-owning source epoch; earlier entries remain historical.

Fresh qualification passes the whole 88-case SourceGen owning suite in 15.079 seconds: 36 functions, 50 complete fixture expansions and 38 light cases. Separately, 65 selected namespace/operational regressions pass in 1.963 seconds. Each original execution closes Source/native/process/genuine-wait custody and releases only its own 16MiB promise durably. Inner process/Source/native/approval statements remain fictional engineering DATA; both failed 87-case attempts, the retained 65-case setup failure and the separate pregrant ledger refusal remain preserved. That refusal ran no tests and created no Native or storage grant. The namespace fixture now uses a separate child root; product behavior and assertions stay strict.

Keep the original resource owners, 16MiB limits, deadlines, holds and expired authority. Actual runtime/source-generation approval and cold-control/raw7 qualification remain open; no active profile is issued. Preserve current peer updates and 119 owners and 24 task states. [Selected qualification evidence](../../../../workspace/test-logs/federal-corpus-audits/legal-ir-sourcegen-whole88-namespace65-20261114-v01/qualification-summary.json).


## Bounded operational generations and terminal scheduling — 2026-11-14

Verified pregrant ledger contention now has explicit SDK/runtime/fleet handling. It remains operational DATA: the default is a visible needs_new_authorization state, while an explicit profile can permit bounded distinct generations within the same fixed epoch and original shared attempt cap. Tickets are spent before invocation; no old request, expiry or budget is renewed. No profile has been issued.

Fresh combined qualification passes 50 executions in 1.347s: 31 new expanded controls, 18 selected existing regressions and one duplicate injected-result check. Original Source/native/process/genuine-wait custody closes and only its 16MiB promise releases durably. Fixture process/Source/native statements remain modeled DATA; the central SDK metadata reader has an explicit classifier-verdict seam. Earlier retained failures and the one stale copied-board test correction are preserved in the selected evidence; existing authorization guards remain strict.

Pre-CLI SourceLeaseTimeout and existing Source-admission75 stay distinct from the verified ledger-busy route. Original clocks, Source/native owners and holds remain; genuine cold-SDK execution and activation are still gated. Preserve peer work and all 119 owners/24 states. [Exact selected evidence](../../../../workspace/test-logs/federal-corpus-audits/legal-ir-operational-ledger-busy-20261114-v01/qualification-summary.json).


## SourceGen source-only installation and ledger-blocked diagnostic — 2026-11-14

Main d01 with the earlier cd647 owning source has a genuine selected LIGHT38 result:38 cases across21 functions pass in0.409s, with zero complete source fixtures. Original Source/native/process/genuine-wait/durability custody closes; all244 execution pins and156 files226078B match independent readback, releasing only its16MiB estimate. This selected engineering qualification stays scoped to its recorded epoch; whole87/raw7 remains unqualified.

The original COMPLETE13A attempt aborts operationally on the inventory rule requiring ordinary owned single-link files. Its one bad entry is the pytest-created SDKcurrent symlink. All760 regular files plus that link,1981225B, are preserved. Ten E bytes in stdout establish no case/error count. No actual run JUnit/result/seal exists; nested fixture XML is fictional DATA. Original Source/native/process/genuine-wait closure is verified, while its failed16MiB remains retained and non-durable.

A one-target Source1 adoption changes only the shared fixture mktemp call to numbered=False. Main d01 retains its original inode/full9; owning93bda preserves all35 test bodies,87cases and49complete expansions. Actual WRITE, separate READ and independent readback establish source installation, with no transferred complete-fixture qualification. The fresh one-case DIAG1 then meets a60s ledger-lock refusal after the finite observer saw a gap. It creates no reservation record, Native grant, productive child, storage promise, test, JUnit/result/seal; its attempt stays empty. Original Source and parent/CLI genuine waits close through the typed no-child alternative. child_reaped and a0b cleanup flags remain false, with no child-cleanup or storage-release credit. This did not reproduce any fixture setup traceback: the installed-Pytest0664 descriptor issue remains a static hypothesis, and no follow-on descriptor fix is implemented. No same-attempt retry or old deadline renewal is authorized by this evidence.

OrdinaryV5 namespace propagation, a genuine immutable-source validation mode and same-epoch whole-owning/cohort aggregation remain actual blockers. Namespace SDKb6b6/worker22e9/owning4e6b and its15new cases are private/static-only; current SDK e8/worker35c stays unchanged. Unchanged health778a must not be invented as a repair edit. Genuine raw6 child imports, original CLI PID/birth/argv/wait provenance, real cold control/candidate paths, trusted closure and source commit/tree evidence still need their own closed originals. The generic16MiB/CPU1/1536MiB/four-child/work300/parent420/Source3/ledger60 route and180s/stable2 one-parent observer do not redefine the future cold SDK route: inner SDK authority360, outer420 and its actual Source waits remain distinct.

Preserve failed/held physical200, next distinct201,9800remaining, generation2/max2, the operator hold, expired repair authorization, all original failures and peer work. No automatic unblocking, productive task status, new runtime/dispatch/completion/hold authority, model-quality or training gain, legal meaning approval, Lean or whole-US-Code release follows. [Exact original evidence](../../../../workspace/test-logs/federal-corpus-audits/legal-ir-scientific-sourcegen-fixture-progress-20261114-v01/qualification-summary.json).


## Exact incoming SDK DATA provenance qualified without runtime activation — 2026-11-14

The canonical repair_candidate_owners SDK e8c2 and productive-owner tests6c52 now have two disjoint genuine original-owned qualification groups: G1v02 passes13 cases/6 functions in1.266s (12 new archival controls plus one selected existing default regression), and G2 passes29 cases/6 functions in2.026s (12 new plus17 selected existing default regressions). All failures, errors and skips are zero. Together these are24 new and18 selected default engineering executions; their local proof/process/Source/native statements inside unit fixtures remain fictional DATA. This is not the whole old suite or a genuine incoming7-role/package source qualification.

Root and independent readback bind both real original parent/CLI waits, Source closure, Native/process closure, current246 execution pins and complete original seals. G1v02 preserves273 files/6506879B and G2 preserves527 files/9381163B; only each successful run's own16MiB promise releases durably. The genuine old7ad missing-API RED1 remains one expected no-fixture AttributeError failure with its four-file3687B16MiB claim retained without durability or release. The earlier G1v01 reaches an original60s ledger-lock refusal before record, Native, child, tests or promise; it receives no test/native/release credit. G1v02 is a separate fresh Root-selected one-shot observed-gap attempt, preserving that refusal and all original deadlines.

The explicit archived-SDK data capability binds exact sealed incoming producer/engine physical references and rechecks the whole policy/control source population and sameNEW reader/engine body compatibility per use. The default current-origin verifier remains strict; receipts, __file__, clocks and current identities are not rewritten, and old7ad qualification is not inherited by newcode. Current native-driver2e9 and imported SDK process-engine e6e3 are distinct roles. SourceGen product Main d01 remains private/pending software proof and genuine incoming qualification; its fixture-storage proposal and future Source2 are separate, still gated work.

The selected-evidence capsule reconstructs selected original buffers and three source-manifest inverses, reusing the installed health/H2 capsule by content-hash reference. It does not archive every fictional SDK fixture body, nest prior capsules or claim the full old suite. Existing peer prose/catalog append order,119 component owners and24 task states retain their own scope. Preserve physical spent200/next distinct201/9800 remaining/generation2-max2 and1GiB proof budget, original16MiB qualification limits, scientific idle384MiB/eight-child/shared300s envelope, operator hold and expired repair authorization. No current service activation, automatic unblocking, task completion, improved decoder/training accuracy, legal approval, Lean or whole-US-Code release follows. [Exact original evidence](../../../../workspace/test-logs/federal-corpus-audits/legal-ir-scientific-SDK42-20261114-v01/qualification-summary.json).


## Qualified historical evidence remains separate from activation — 2026-11-14

The canonical native_executor_health778a and unchanged owning tests c364 complete the genuine full owning-file242-case/65-function qualification in4.535s with zero failures, errors or skips. Independent readback joins the original single parent/CLI waits, both Source READs, closed Native/process custody and release of only that run's16MiB estimate. All238 execution sources match; the original3145 seal rows/3146-file population totals9792978B and is checked twice. These are current engineering unit fixtures, with no current scientific-service or task-dispatch authority.

A separate original operation calls the canonical historical-witness APIs for retained cycle199 and exact old receipt37 identity. Its single5054-byte JSON returns historical_evidence_verified=true for both, authenticates all423 source declarations per use and closes the witness in finally. All declared historical source bodies reconstructed, current executor verification, new historical Native/kernel execution and every runtime/dispatch/completion/activation/hold-removal authority result remain false. Original Source/native/process/genuine-wait/durability custody closes; all251 execution pins and the five-file8127B population match independent readback, releasing only that operation's16MiB estimate. This selected DATA authentication neither recreates all37 original custody chains nor reexecutes the old cycles.

The earlier Source3s prelaunch refusal remains no-owner/no-Native, and the f870 GREEN242v02 result remains240 pass/two legacy role-reason failures with its retained claim. The minimal778a interpreter-order repair keeps ordinary current-interpreter authentication while restricting explicit archived data to five historical project-source slots. The installed CLI68/actual423 qualification remains its ac208 epoch; success is not transferred across source generations. The cold capsule archives selected original buffers and three exact prepared-manifest inverses, not every one of the3146 fixture bodies or all423 historical source bodies. It references the installed prior capsule and does not nest it or recopy the old38MB base.

Current SDK/engine physical import-origin binding remains a real blocker and its private source-generation proposal has no qualification from these results. Current Main-role, coherent profile/config/unissued-template/history and failure-specific physical200 continuation remain separate work. Preserve failed/held physical200, next distinct201,9800 remaining, generation2/max2, the operator hold, expired repair authorization and original budgets. Ordinary qualification stays16MiB/CPU1/1536MiB/four child slots/300s work/420s parent/Source3s admission; scientific idle stays384MiB/eight child slots/shared300s=240work+60cleanup. No service activation, automatic unblocking, productive task completion, improved training/decoder accuracy, legal approval, Lean or whole-US-Code release follows. Latest peer prose/catalog/task states retain their own scope. [Exact original evidence](../../../../workspace/test-logs/federal-corpus-audits/legal-ir-scientific-health242-history199-20261114-v01/qualification-summary.json).


## Scientific prepare CLI is qualified; physical200 handover remains gated — 2026-11-14

The CLI68 and actual423 measurements belong to their recorded ac208 health-source epoch. Canonical health f870 is a later generation and needs its own qualification; no result is transferred to it here.

The existing canonical scientific executor has an isolated prepare-idle-source-replacement CLI (6e4/2da1). Its genuine one-case missing-operation baseline fails with SystemExit 2 and retains16MiB. Source42/733 installs only the owner and owning tests, with separate readback. All68 selected cases across17 functions pass in0.506s:28 new CLI controls plus40 retained API/template controls. Original Source/native/process/genuine-wait/durability custody closes and releases only that run's16MiB promise.

A fresh original operation now runs the CLI against the actual423-source profile. Its single4406-byte JSON result authenticates exactly five replacements, checks all current descriptor bodies, restores the original profile by exact raw inverse and returns source_count423/changed_source_count5. All242 execution pins and423 data-source identities match the independent readback. Original custody closes and releases only its16MiB promise. The earlier v01 SourceLeaseTimeout remains a prelaunch refusal: no original owner Popen, attempt or resource claim; its false Native/wait/reap flags are not relabeled as cleanup success. This is a real metadata comparison, not a JUnit test, Lean kernel result, service cycle or legal formalization.

Counter correction: the earlier spent162/next163 statements describe the retained historical acknowledgment. The current read-only physical inventory reaches200, with37 subsequent closed/proof paths at163–199 and failed/held200; the next distinct position is201 and9800 of10000 remain. Generation2/max2 and all old failures/holds remain. This inventory and its archived path witnesses do not independently reverify full historical custody or the prior13 operations, and grant no continuation/rearm authority. The existing failure-specific200 capacity-continuation contract still needs its own history/witness, current health/Main-role and coherent profile/config/unissued-template qualification.

All coherence/runtime/activation/dispatch/hold-removal/authority results remain false. Preserve the operator hold, expired repair authorization, physical200 history and original budgets. The separate scientific idle route remains384MiB, CPU1/1536MiB/eight child slots and shared300s=240work+60cleanup; the16MiB ordinary qualification route is not a replacement. Productive task templates, model fidelity, independent statutory meaning review and whole-US-Code/Lean release remain open. [Current physical history and original bounds](../../../../workspace/test-logs/federal-corpus-audits/legal-ir-scientific-CLI68-actual423-cycle200-20261114-v01/qualification-summary.json).


## Scientific source preparation is separate from runtime handover — 2026-11-14

The existing scientific executor now has a prepare-only five-source comparison. A genuine one-case baseline fails on the missing API in 0.150 seconds and retains its 16 MiB claim. Original Source 42/733 publishes only the canonical helper and owning tests (1000ca/ba4d); separate readback confirms both postimages and nine unchanged code fences. A fresh original-owner run passes all 40 cases across nine functions in 0.455 seconds: 36 new controls plus four preserved template-policy controls. Source, native compute, process, genuine wait and durability custody close; only its own 16 MiB promise is released. The capsule archives 37 selected proof files and two prepared manifests. The original seal and independent audit verify all 583 GREEN attempt files; their raw file buffers are not all archived in this capsule.

The helper reads the old frozen profile as historical DATA, validates the current proposed profile twice, and accepts exactly the five canonical R source replacements with unchanged paths, row order, four roles and other profile fields. Strict old descriptor types and exact raw inverse checks reject unlisted changes; it writes no config, hold, authorization or runtime state. All activation, dispatch, hold-removal and authority results remain false. These tests use complete fixture profiles; the helper has not been run against the actual 423-source scientific profile. Config/template/history coherence and real scientific runtime qualification stay unresolved.

Continue through the existing owner with an explicit finite source-transition contract and separately qualified current main role, coherent profile/config/unissued-template bindings and original runtime proof. Preserve the scientific operator hold, expired repair authorization, generation 2/max 2/spent 162, all retained failures and original budgets. The idle scientific route remains 384 MiB, CPU 1/1536 MiB/eight child slots and one 300-second clock split into 240 seconds of work and 60 seconds of cleanup. Productive task templates, model fidelity, statutory reviews and whole-US-Code/Lean release remain open. [Qualification and prior publication failure](../../../../workspace/test-logs/federal-corpus-audits/legal-ir-scientific-source-comparison-20261114-v02/qualification-summary.json).


## Supervisor continuation: peer22 closed; scientific source migration remains explicit — 2026-11-14

The existing A214 packet resolves the missing captured canonical-writer dependency. Its actual peer-owned original run passes22 cases across7 functions in0.556s, with all214 source pins checked, original parent wait, Source/native/process closure and durable release of its16MiB promise (six files/47127B). Root reuses this exact ae4d/f414/d57 lineage and launches no duplicate; the separate b767/a01f preparation stays inert. External tool wait for the peer completion job was not observed and is not inferred from absent PIDs. Earlier A212 failures, historical47 on ca6, and pending current ordinary335/transport1/Native1/caller scopes remain separate.

A fresh read-only scientific review identifies exactly five stale canonicalR sources. The inert e2fe profile changes only423-row slots389/392/394/397/402; its inverse restores originalae9 byte for byte. All423 unique current source bodies (38389030B), four role aliases and full-nine identities are preserved in the lossless capsule. This is static source/ABI comparison: no product parser, tests, service restart or activation was run. Existing config0136 still selects oldae9, idle request4a884 still pins the five old sources, and frozen b940 recovery branches reject these replacements. Updating five hashes alone is not a coherent or authorized restart.

The live repair remains policy_wait/repair_authorization_expired; the scientific operator hold remains. Engineering145/145 is healthy idle with zero selectable tasks; diagnostic scientific60/4 counts grant no completion or dispatch authority. Continue LIR-1401/1402 with current owning/adoption bindings and LIR-2201/2202 with an explicit existing-owner source-only transition plus coherent profile/config/unissued-template/runtime proof. Preserve generation2/max2, spent162, max10000 cycles,1GiB proof bound and idle-only execution_templates=[]. The original idle route is384MiB/CPU1/1536MiB/eight child slots/shared300s=240work+60cleanup; the separate Nativev10 profile is not a substitute. Productive task templates and statutory/model/corpus gates remain separately open.

Do not treat no selectable engineering tasks as a hung worker or renew expired authority. Current terminal helpers, finite source migration, actual runtime identity/health and task dispatch require their separate qualifications. [Exact evidence and original routes](../../../../workspace/test-logs/federal-corpus-audits/legal-ir-supervisor-source-migration-frontier-20261114-v02/qualification-summary.json).

## Native source attribution and original lifecycle closeout — 2026-11-14

Canonical 35c/c823 resolves the real directory descriptor for authenticated R packet writes and projects an authenticated selected Pytest call beside the original loader map. Compile/pre-exec alone supplies no call witness. Invalid attribution remains uncredited without clearing the profile hook; missing-body diagnostics retain a bounded count and eight details. Original Source 2/Source 3 WRITE and separately SHA-bound READs preserve 20 fences and both source epochs.

The selected 106 owning cases pass with original 2 MiB durable closure. Fresh v10 closes original Source/Native/process/wait/durability and releases 16 MiB; its 77-file packet and same-thread opaque-handle reader pass. The 85 seal rows plus the seal preserve 86 files / 2,547,864 bytes. Keep MAX 16 MiB, 300 seconds productive / 420 seconds parent, 1 CPU / 1536 MiB memory / 4 child processes and six output trees. V08/v09 failed 16 MiB promises remain retained; budgets and failed results are not reset.

This validates direct original API custody. Separately recorded nested 7ad/557 runtime, terminal compatibility/autonomy, D e25/fef observations and all peer histories retain their own scopes. Preserve 119 owners / 24 task states and the existing supervisor task homes. [Verbatim evidence and exact limits](../../../../workspace/test-logs/federal-corpus-audits/legal-ir-descriptor-relative-native-persistence-20261114-v01/qualification-summary.json).


## Canonical readonly stdin uses the original process lifecycle — 2026-11-11

Canonical R process4434 and lifecycle testsc536 are installed through original42/733 Source1/Source2 and SHA-bound separate READs. Absent input now opens os.devnull in rb mode only around original Popen construction; byte input retains PIPE. Cleanup-owner attachment or ordinary tracking occurs before a potentially failing input close. No external-write, profiling, process, source or resource permission is broadened.

The direct-R/C19 cohort passes36/36 across27 functions, with original16MiB/MAX16MiB,300+420 seconds,CPU1/memory1536/process4 and all six output trees preserved. The7 physical files total17,885bytes including the six-row durability seal; actual Source/Native-compute/process/wait/durability close and that successful reservation releases. The preceding32-pass/4-failure reservation remains retained. Scope distinguishes real readonly/EOF and PIPE subprocesses, an injected failed launch and two modeled postspawn-close cases. The source-retained symlink-output case remains unqualified under the ordinary profile.

The separate immutable A runtime migration remains pending and the D e25/fef watcher keeps its existing binding. No original Native build, complete77-file packet, same-thread opaque-handle consumption or corpus admission follows from this process-only qualification. Use the exact four-file cachetools appendix and newly checked runtime policy/source commitments for the next original derivation and Native operation. Do not force a changed aggregate hash or silently repin old proof. Preserve failed claims, current source identities and the existing LIR-14/LIR-22 task homes. [Exact closeouts, raw files and next gates](../../../../workspace/test-logs/federal-corpus-audits/legal-ir-readonly-native-stdin-20261111-v01/qualification-summary.json).


## Current A3 installation and remaining Native operation — 2026-11-11

Canonical A3 source installation leaves the separate immutable A live-runtime migration pending; the deployed D e25/fef watcher retains its existing runtime binding. Canonical A owner7ad1, worker557c and testsb0ef are installed through original42/733 Source operations and independent original READs. Their selected owning55 cohort passes with the original CPU1/memory1536/process4, 2 MiB reservation and 300/420-second bounds. All original lifecycle and durability checks close; the failed baseline and four dispatched Native-failure promises remain preserved. No timeout, source, I/O or cap permission is broadened.

The completed disk0 probes use paired Source25/work40/Native55 owners and record their own narrower scopes. The collection diagnostic alone uses no:logging; full Native-worker logging stays unchanged. A modeled profiler case explains exception masking without granting profiling permission. A separate unlaunched stdio case observes CPython's O_RDWR devnull open and successful readonly EOF/close. The build-entry diagnostic's tempfile path belongs to its different TMP context and does not identify the earlier Native write target.

Under existing LIR-14/LIR-22, retain the private R4434 repair and explicit 36-case/27-function direct-R scope until separately qualified; keep its real-symlink case open. The cachetools5.5.2 appendix declares exactly four Python files. Any changed R producer requires a fresh aggregate and current policy, followed by the original Native owner and same-thread handle reader under its unchanged 16 MiB/300+420 profile. [Current receipts, cutoffs and next gates](../../../../workspace/test-logs/federal-corpus-audits/legal-ir-native-parent-A3-frontier-20261111-v01/qualification-summary.json).


## Derived fictional inputs are durable; Native activation remains unqualified — 2026-11-11

A separate original SDK operation completed the current-producer derivation, full policy validation and normative reopen, closing original Source, Native, process, genuine-wait and durability custody and releasing its 4 MiB promise under the unchanged 16 MiB maximum. All 245 source pins matched at that execution's cutoff. Its four durable outputs are public DATA f624, policy 065b, lineage 48b3 and observation 8376. The original public 2c8129 bytes, encoded signed normative fields and signatures are unchanged. Only the successor's preparation and expected-preservation fields change; the aggregate digest is 4e8d. This operation invoked no fixture creator, signer, compiler or original Native-parent runner; training and gold masks remain zero.

The separate Native activation has no successful result. Its first attempt failed on a missing attempt-root directory before any Source context; only that operational precondition was repaired. The fresh second invocation refused before Popen, SDK or Native dispatch when the original custody guard found later peer control-source changes: owner 6c5 to 2d23 and owned CLI 269 to 86c8; the maintained accelerator fixture also advanced from c128 to 4365. Its plan, request, empty attempt and original observations are preserved, with no matching Native grant or reservation row and no loader observation. Unlike the first setup failure, the second custody constructor may already have entered Source READs and then closed its ExitStack on exception; no new Source witness or historical global absence is inferred.

A reviewed current ABI and unsigned policy-lineage successor, followed by a distinct fresh operation and genuine original Native parent with capability consumption in the same thread, remain pending at this note's cutoff. Do not relabel the old policy, replay the refused invocation, recreate signers or reset budgets. The completed recovery-deployment section and its natural API0 point observation retain their earlier cutoff. All peer work, task states, original failures and 8D/384D/768D/Leanstral 4096D lineage remain intact. Fictional DATA derivation establishes no statutory meaning, model quality, Lean build or corpus admission. [Exact derived outputs, lineage and preserved refusal scopes](../../../../workspace/test-logs/federal-corpus-audits/legal-ir-current-derived-aggregate-frontier-20261111-v01/qualification-summary.json).


## Historical-cap recovery deployed after 811 owning and 248 watcher checks — 2026-11-11

Two upfront disjoint owning cohorts passed 513 cases across 94 functions and 298 across 37: 811 cases across 131 functions. Three fresh watcher cohorts passed 81/52, 95/37 and 72/15: all 248 cases across 104 functions from the complete 688c owning source. Each of the five original owners closed Source, Native, process, genuine-wait and durability custody and released its separate 16 MiB promise. These are aggregate results across separate executions.

The exact four canonical postimages are now adopted: recovery API c60, watcher c5ca, sampled recovery tests 8ff and unopened controls d20a. Historical positive exact-integer cap values are treated as proof DATA while current ledger, Source, row and Native gates remain strict. The watcher changes only the API pin on peer 240e, preserving automatic completed-profile dispatch, finite producer/SDK pairs and the existing 688c watcher tests. A single original WRITE0 adoption followed a bounded observation of the four original lock inodes inside the same maintenance window; foreign readers, lock priority and deadlines were untouched.

Fresh Source29 capture, configuration, unit publication and loaded-manager readback are complete. The configuration changes only its CLI hash and capture descriptor; existing candidates, triggers, roots, state, policy, current 250 GB cap and service limits are preserved. The original controller closed in 197.369 seconds, restored the existing timer and released only its registered hold. One subsequent natural cycle closed Source READ and reported idle_current_capacity_satisfied with zero readiness, reconciliation or disposition API calls. That observation grants no future admission or new release authority.

Peer storage closeout 372f, composed native384/364, later GTE fitting and lexical rankings, all task states and 8D/384D/768D/Leanstral 4096D lineage retain their separate evidence. Preserve every old failed attempt, UNKNOWN marker, metadata cutoff, the failed A1 4 MiB promise and exact 781248-byte public 2c8129 DATA. The read-only consumer's prelaunch Native AST drift refusal remains a refusal. At this recovery deployment cutoff, distinct derived-input generation and a separate original Native parent with same-thread capability consumption remain pending; these software and operational results establish no statutory meaning, model accuracy or corpus/Lean admission. [Exact qualification, deployment and preserved scopes](../../../../workspace/test-logs/federal-corpus-audits/legal-ir-historical-cap811-current-auto248-20261111-v01/qualification-summary.json).


## Current retention qualification and recovery generation — 2026-11-11

Canonical retention80 request5daf/callerf26a completed with all80 passing and actual2MiB/MAX16 unchanged. Source176, Native, birth-bound processes and genuine wait closed; released/durable row25b9 and all24 files744,793bytes were independently verified. The prior79/1 row4c96 remains retained with its22 original files. Separate repaired-outer35 row399399 released2MiB with clean custody; keep its historical220GB Host scope distinct.

Preserve the peer's authorized250GB cap and current e42/b6d3/09ef API/test/watcher progress, including manual snapshots and completed-run recovery. Original claims, receipts and UNKNOWN92 were not rewritten by migration. Root performed no cap migration or service change. One old embedded migration Host-test reference is unverified; current source pins and deployed captures were checked independently.

The remaining ordinary historical-cap mismatch has a private c60 candidate and26 scoped passing controls; no canonical adoption or claim release follows from those controls. Plan complete disjoint513+298 case cohorts with current peer250 dependencies and exact811 union, all output trees retained and original per-request limits. A complete single-process811 fit is not established. No failed attempt is replayed or released to obtain capacity. The P22 candidate is ineligible after six missing original files; no Root archival or reclaimed-space claim was made. [Exact operational evidence](../../../../workspace/test-logs/federal-corpus-audits/legal-ir-retention80-recovery-integration-20261111-v01/qualification-summary.json).


## Released engineering-fixture reclamation — 2026-11-11

The selected Green46 TMP-only reclamation used original Source42 WRITE and IO733, current released-row/custody checks, a lossless verified PAX archive and a local TMP_ARCHIVE.json before checked removal of25 synthetic fixture files. Archive generation occurred in bounded memory; all new archive/manifest/pointer/outcome files stayed below256KiB. This bounded net-negative filesystem maintenance reclaimed37,449,489bytes during an existing overage. It granted no Native allocation, changed no ledger row or limit, and supplied no runtime qualification by itself. The later103 request still used fresh original admission. Original file inode/ctime values remain historical; restoration does not renew the old durability seal. Preserve outer logs/seals and use the exact retained manifest and pointer. This one selected operation is not permission to relocate active, failed, scientific or current model inputs.


## SDK shutdown repair adopted; full clean-run gate pending — 2026-11-11

The complete497-case/91-function recovery body now passes with zero failures/errors/skips. Its old canonical280/SDK11e outer failed afterward with `validation watchdog did not finish cleanly`; original Source/Native/process custody closed, but the16MiB failed claim and all7,791 files remain. Body success is not whole-run qualification.

The independently qualified private35/19 SDK4df/CLI269 repair is now adopted in the three canonical SDK/owned-runner/owning-test files through original42/733 CAS and separate Source readback. APIa5, recovery testsbe and peer watchera8/v15-ops remain unchanged. The deployed Source29 excludes these three targets; no service, unit, configuration, timer or HOLD action was needed. The repair stops the periodic observer cooperatively while retaining final full durability and quota checks.

A fresh request reached the genuine new269/4df outer, then refused before any test/record/Native grant/child:2MiB admission deficit1,583,227 bytes. Source and Native closure and the new no-grant classifier were verified, with no successful new-outer qualification. Preserve all failures and limits. Complete the repaired-outer35 test and then full497/newouter custody/durability before stage2 recovery API/tests/watch-pin adoption. Keep the peer census fix and require settled runtime/fresh Source29/actual READY for that later change.

The existing recovery root contract also rejects an authentic private working directory with a canonical runner/Source lease; a separately verified manual profile is pending. Do not rewrite original cwd, Source roots or UNKNOWN history to obtain eligibility. Scientific original-parent Native success, genuine statutory reviews and model quality remain open; all24 task states and8D/384D/768D/Leanstral4096D lineage remain intact. [Exact new Source and run evidence](../../../../workspace/test-logs/federal-corpus-audits/legal-ir-staged-SDK-shutdown-repair-20261111-v01/qualification-summary.json).


## Exact namespace and shutdown adoption frontier — 2026-11-11

Canonical accelerator owner6c5/worker42aa/testc128 have closed6 direct and39 original pytest namespace controls. Select the explicit v2 marker only for the exact three canonical normal namespace rows; retain legacy zero/one behavior and normal package/source identity checks. The separate73 native-owner cases and private35 cooperative SDK/CLI cases closed their original custody with durable2MiB release under the unchanged16MiB maximum. None establishes actual scientific Native-parent or outer269 success.

The coherent six-R adoption packet is conditional on actual complete497/91 GREEN, full durability and closed genuine owner/Source/Native/process custody. V04 failed457/40 because the private closure omitted an existing module; v05 corrects both transitive leaves but was refused before execution. Keep the failed16MiB promise and all7,709 files; do not drop cases, shorten inventories, expand budgets or treat preparation as qualification. Finite recovery must retain280/11e and269/4df pairs, preserve all V4 behavior and leave the UNKNOWN92 automatic frontier unchanged.

Peer v15 operations own that namespace. After actual full qualification, freeze the settled base and a genuinely unoccupied successor, refresh all full-identity preimages, use original42/733 write plus separate readback, then the original single3-second Source29 capture and actual READY/config/unit/health receipts. Rollback also needs a fresh capture; restored bytes do not restore inode/time identity. Actual future refs must remain absent until their original producers return.

Exact legacy-empty recovery requires original provenance, not merely an empty path or missing Native fields. The reviewed ac537 timeout proved never-native/no-child and its existing exact-empty API released16MiB once; current Source closed and original UNKNOWN stayed. A stable original-RID marker prevents fresh-output-directory replay. Claims686046,7862 and e689 were refused because original terminals record acquired grants. Do not launder those histories through the empty pre-native opt-in. Administrative projections are not actual postwrite global censuses. [Exact actions and refusal evidence](../../../../workspace/test-logs/federal-corpus-audits/legal-ir-native73-namespace39-shutdown35-progress-20261111-v01/qualification-summary.json).


## Canonical recovery and two direct native-guard controls — 2026-11-11

Recorded Source adoption installed recovery `d7556346…`, tests `dc0da2b6…` and watcher CLI `4bfa498e…`. Fresh original Source29 capture retained 12 files, 17 instruction absences and two owning targets. Publication produced v12 config `8398275b…` and unit `56e6cf8f…`; manager readback confirmed the binding and original CPU, memory, task and timeout limits. Three frozen-row path accesses were corrected to `source_ref.path` after a preserved pre-intent refusal. Historical natural watch output records closed Source, zero readiness/reconciliation/disposition APIs and UNKNOWN92 no-replay. [All selected raw receipts](../../../../workspace/test-logs/federal-corpus-audits/legal-ir-v12-recovery-and-native-guard-progress-20261111-v01/qualification-summary.json)

RneedRED2’s once-only administrative closeout returned normally. Its first independent observer hit the clipped quiet deadline before API entry; the next hit a five-second lock wait before API entry. Both failures remain archived. A fresh read-only observer restored the original 30-second lock allowance inside its unchanged 240-second scope and established the released row without a mutation API. Three further actual readiness checks then supported separate known returned administrative closeouts of 16 MiB each. A shared read-only observer joined all three actual returned receipts to their current released rows, executed one global census and obtained three original storage-release dispositions in 55.986543 seconds. It closed Source and issued no grant. Our four closeouts released 64 MiB while retaining 25 files / 283,544 bytes and all failures.

The v12 rollout maintenance closed in 540.292 seconds, and the later three-claim maintenance in 503.270 seconds, each inside its original 690-second absolute bound. Both restored their own timers, required fresh fleet/held-watchdog health and released only their registered holds. The intervening pre-HOLD refusal preserved a foreign maintenance owner and paused no timer. No budget, task status, global/scientific hold or deadline was renewed. Later foreign maintenance retains its own timer/hold authority; these closure receipts are historical rather than a claim of global current timer activity.

The group census charged 219,996,653,442 bytes against 220,000,000,000: apparent 173,898,447,554 plus outstanding 46,098,205,888. Its 3,346,558-byte headroom was insufficient for the original 16 MiB qualification promise, and a later natural watch recorded pressure again. Admission must be checked afresh. Our attribution covers only the four selected closeouts; peer outcomes remain separate.

Two direct native-guard controls passed under the original Source 25-second wait and resource work/native 40/55-second scopes, with 1 CPU, 1536 MiB and one process slot; all Source/root/phase custody closed. Only original scheduler-state operations were permitted during the body. The full 73-case request had previously run zero tests after pre-admission refusal. Its successor, SDK 35-case qualification and original-parent native execution remain pending. Earlier dated entries below preserve their original generations.


## Current capacity recovery and qualification, 2026-11-11

Original readiness/admin/disposition under824 closed only the own V4 claims75dec and7085: 128 MiB of promises released, ten files preserved, failed tests unchanged. Source and original cleanup clocks closed. The configured UNKNOWN92 claim was not replayed. Saved headroom64,221,027 bytes is an observation, not admission authority.

The first current-port baseline had zero bodies due to actual global capacity refusal. Its fresh successor reproduced V5 rejection; private41 passed with released/durable1MiB custody. The d755/dc0d recovery and4bfa watcher adoption plus recorded v12 Source29/config/unit publication and manager reload are complete with private41 scope and unchanged limits. Our own9cc storage release has separate actual evidence. Later live generations require a fresh comparison. [Recorded adoption and metadata observation](../../../../workspace/test-logs/federal-corpus-audits/legal-ir-ledger-refusal-diagnostics-20261111-v01/readbacks/peer-v5-source-and-v12-binding-readback-v02.json) Old V4/64MiB/12-case publisher gates cannot be relabeled as this private41 result. The runtime29 guards are the 12 captured files plus17 instruction absences. CLI and watch-test owning_targets are captured DATA. The configured CLI own pin still binds exact bytes, while an identical-byte inode or timestamp change alone does not invalidate runtime29. Refresh separate full9 custody observations before relying on their old metadata. [Capacity closeout and private V5 qualification](../../../../workspace/test-logs/federal-corpus-audits/legal-ir-capacity-repair-and-v5-private-qualification-20261111-v01/qualification-summary.json)

## Source-held V4 recovery and recorded v14 binding

The original d755 public readiness call reproduced the selected 1e18 H16 V4 refusal with two closed Source reads and no mutation, scheduler, census or Native grant. Private a5fc/be42 then passed 41 cases in 5.284 seconds with 54 pins and 15 normal private collection origins. Original Source, Native and process custody closed and its 1 MiB promise durably released. The corrected independent reader preserves its earlier metadata-descriptor refusal, validates full9 and gives no raw-compilation or whole-module credit. [Exact qualification and lineage](../../../../workspace/test-logs/federal-corpus-audits/legal-ir-ledger-refusal-diagnostics-20261111-v01/source-held-v4-compatibility-qualification-summary-v01.json)

Recorded original Source WRITE and separate READ adopted a5fc/be42/6de. Fresh Source29 capture, matched v14 config/unit publication and exact manager reload completed with the existing limits and unchanged recovery frontier. The original maintenance closed in 369.560 seconds after restoring its timer, requiring fresh health and releasing its own hold. Runtime29 contains the 12 captured files plus 17 instruction absences. CLI/watch-test owning targets remain DATA, and the CLI own pin checks exact bytes. Three later A-source outer-fence changes do not belong to runtime29. A separate service observation records a natural v14 start after reload and exit 0 without a Root service start. Its service properties do not inspect Source/API journals. Refresh every current selection. [Natural service observation](../../../../workspace/test-logs/federal-corpus-audits/legal-ir-ledger-refusal-diagnostics-20261111-v01/readbacks/source-held-v4-v14-natural-service-observation-v01.json) Preserve UNKNOWN journals and other owners' holds. [Adoption and binding observation](../../../../workspace/test-logs/federal-corpus-audits/legal-ir-ledger-refusal-diagnostics-20261111-v01/readbacks/source-held-v4-source3-and-v14-binding-independent-readback-v01.json)

Our own9cc current-V5 operation released 64 MiB with all 14 files / 220,676 bytes and its original failed baseline preserved. Separate historical API824 closeouts released 32 MiB. Two later d755 closeouts released another 32 MiB and preserved 351 files / 7,408,821 bytes. Their original 20-case and 198-case commands still have one failure each. The earlier d755 census charged 219,977,259,610 bytes, leaving 22,740,390 bytes under the unchanged cap at that cutoff. At that earlier cutoff, a fresh 64 MiB promise would have lacked 44,368,474 bytes. Obtain fresh admission rather than relying on that saved census. [Own64](../../../../workspace/test-logs/federal-corpus-audits/legal-ir-ledger-refusal-diagnostics-20261111-v01/readbacks/own9cc-current-v5-own9cc-independent-saved-readback-v01.json) · [Additional32](../../../../workspace/test-logs/federal-corpus-audits/legal-ir-ledger-refusal-diagnostics-20261111-v01/readbacks/current-d755-V1-additional32MiB-combined-summary-v01.json)

Two subsequent original a5fc operations closed the selected real V4 claims `1e18` and `4002` and verified 64 MiB release each. Each had one readiness, one administrative mutation and one disposition call, an actual postwrite census and closed original Source reads. All 73 files, 55 directories and 44,620 bytes remain unchanged. The original one-case and12-case commands remain failed with one failure each. The second saved census charged 219,886,859,447 bytes and left 113,140,553 bytes under the unchanged 220 GB cap. That point observation is not current admission authority. The original 427.763-second maintenance restored the timer, required fresh health and removed only its own hold. Preserve the unchanged UNKNOWN frontier and obtain fresh admission for any new promise. [Actual128 MiB operational evidence](../../../../workspace/test-logs/federal-corpus-audits/legal-ir-ledger-refusal-diagnostics-20261111-v01/real-source-held-v4-two-original-closeouts-summary-v01.json)

The private diagnostic 47e/a4c whole246 request remains UNRUN and unpublished. Preserve both earlier zero-test capacity refusals, their source reversals and every retained original result. Administrative storage release grants no test success, new compute or admission. Detailed natural-cycle journal review retains its separate evidence requirement.

## Reviewed original-parent runtime gate, 2026-11-11

The 210-case original-parent regression has passing tests/source audit and a failed outer validator: its resource observer remained alive after the unchanged five-second join. Preserve the retained 16 MiB claim and failure result. Make the existing local observer stoppable after proved child cleanup while retaining full final inventory and original resource/time bounds; do not pad test duration or claim runtime acceptance. No blocking thread frame was saved in this attempt.

The last recorded 220 GB Host census left 23,952,214 bytes. Obtain fresh admission for each operation. The sole configured recovery claim's once-only journal has no returned receipt and forbids replay. The own RneedRED2 claim `8806f36e7ef64323b7dd10985ea59cbf` is a separate, genuinely closed six-file/125,686-byte failure. The V5 port is adopted from its private41 qualification. This separate RneedRED2 claim still requires individually selected readiness and administrative closeout with fresh current-source pins. The larger failed 210-case attempt also exceeds the existing 4,096-artifact recovery profile. Do not truncate inventories, delete files, change caps or release another agent's claim. [Original-parent bridge evidence](../../../../workspace/test-logs/federal-corpus-audits/legal-ir-reviewed-native-admitted-parent-20261111-v01/qualification-summary.json)

## Explicit archival profiles and capacity admission

Use the existing `ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_ledger_archival` owner. Its default `SCHEMA` remains `released-reconciliation-archival/v1`, with an 8 MiB ledger bound and 160,000,000,000-byte storage cap. Passing `profile=CURRENT_PROFILE` selects only the known V2 bounds of 16 MiB and 220,000,000,000 bytes. Unknown profiles are refused; caller-selected caps are unavailable. Pointer schema V1 is unchanged. Reader profile selection changes its bounded snapshot size and grants no mutation authority.

Effectful archival still requires genuine current-process/thread Native root and child phase leases, the matching current Host configuration, and exclusive ledger admission before the first intent or snapshot write. The immutable snapshot and intent precede the sole atomic ledger fold. If completion or readback fails after that fold, inspect the original outcome before another attempt. Preserve selected records, unrelated rows, root policy and cap accounting. The new profile grants no automatic cleanup, arbitrary recovery, task completion or cap expansion.

The peak storage default remains 32 MiB and the existing ceiling remains 64 MiB. Precharge includes the original snapshot, projected ledger, two 1 MiB journals and 65,536 bytes. Two full 16 MiB buffers require 35,717,120 bytes and exceed the default. The qualified large private case used a 16,654,331-byte snapshot and 15,612,168-byte projected ledger: the 32 MiB promise was refused before writes, then an independently admitted 64 MiB promise succeeded. Original resource and ledger caps remained unchanged. [46-case qualification](../../../../workspace/test-logs/federal-corpus-audits/legal-ir-ledger-archival-current-profile-20261111-v01/readbacks/focused46-independent-readback-v02.json)

The separate actual-eight check reads the old immutable snapshot and two individually stable live-ledger generations, requiring exact selected rows and schema/roots/cap while allowing unrelated rows to advance. It writes no live ledger and creates no snapshot copy. Its direct normal-import control checks the canonical module and selected function origins; this route emits no per-compile audit inventory. Do not transfer the 46-case suite's compilation counts or treat the read as another test cohort or production archival fold. [Actual eight-record readback](../../../../workspace/test-logs/federal-corpus-audits/legal-ir-ledger-archival-current-profile-20261111-v01/readbacks/actual8-independent-readback-v01.json)

The reviewed native owner now issues an opaque process/thread-local handle after a fresh default native build, persisted-packet readback and closing current-review replay. The reader joins the exact packet and current inputs, refuses forged handles and packet swaps, and detects callable and class-lookup changes. All 71 selected ordinary cases passed in 54.008 seconds. Three actual native cases passed in 58.964 seconds, exercising three offline Lake builds and nine observed native launch requests. Each build checked six modules and 15 conditional preservation obligations with empty axiom reports. Original Source, compute, process and durable 16 MiB custody closed for both cohorts. Both bounded maintenance windows restored their timer and fresh health checks and released their own holds. [Live native qualification](../../../../workspace/test-logs/federal-corpus-audits/legal-ir-reviewed-native-live-success-20261111-v01/qualification-summary.json)

Live native authentication is separate from admitted-parent authentication. The new result retains `original_success_authenticated=False` and `original_admitted_parent_custody_authenticated=False`; all legal/release authorities and training/evaluation masks remain false. The retained-only loader keeps its previous authority limits. The missing-API baseline and earlier zero-test ledger-lock failure retain their failed results and reservations. Saved deduplicated packets preserve exact bytes and cannot recreate a live handle. Next under LIR-14: join the original admitted-parent request, genuine wait, Source/Native closure and durability evidence to the exact native packet before release-native consumption.

The retained-capacity watcher now reports physical ledger bytes, reservation count and remaining metadata capacity under its existing inspection lock. All 12 focused cases passed in 0.341 seconds, including compact/pretty physical sizing, zero row headroom, real lock contention, stage-specific refusals and concurrent ledger mutation. The original validator closed Source, compute, process and durable 64 MiB storage custody. The v11 service binding is installed; its first natural cycle at 06:15:44 UTC closed Source and reported 2,866,172 bytes and 1,483 reservation slots available, with zero readiness, reconciliation or disposition API calls. The timer, fresh fleet/watchdog health and own maintenance-hold release were verified. [Watchdog qualification](../../../../workspace/test-logs/federal-corpus-audits/legal-ir-watchdog-ledger-headroom-20261111-v01/qualification-summary.json)

The earlier 11-pass/one-failure run retains its expected-message mismatch and failed reservation. Its maintenance controller also retains its failed closeout; a separate expired-owner release restored normal operation. The successful successor used fresh evidence and its own bounded window. These operational checks do not establish statutory meaning, model accuracy or corpus admission.

The existing command timeout handler now uses one remaining cleanup cutoff after its existing KILL request. If output capture does not observe EOF, its short diagnostic explicitly retains descendant-cleanup UNKNOWN; a bounded wait addresses only the direct leader. Local pipe closure must not be treated as proof that descendants stopped. Focused12 controlled transport tests qualified the partial-output, UTF-8, prefix/compaction and complete-capture contracts; whole34 and physical escaped-EOF cleanup remain unqualified. See the [existing maintained recovery capsule](../../../../docs/autoformalization/evidence/legal-ir-reviewed-producer-recovery-full225-20261109.json) for separate Source2 and actual UNIT qualification receipts.

Keep the capacity-service observations separate: the 06:01:22 inspection-ledger-lock refusal remains saved; a later natural cycle from 06:17:12 to 06:17:59 exited successfully and was observed at docs-only entry. Neither the earlier maintenance IN_PROGRESS report nor the Native test result is that cycle's completion proof. Existing maintenance still restores the timer, obtains a fresh healthy report and HELD watchdog acknowledgement, then releases only its registered own token under the original fixed deadline. No action budget, scientific hold, task status, repair authority or Source-repin authority is expanded.


## Acquired-then-closed pre-child Source inspection

Use the existing CLI's [`inspect_owned_validation_no_child_native_closed_v1`](../../../../docs/autoformalization/evidence/legal-ir-no-child-native-closed-20261109.json) only after genuinely waiting on the original CLI Popen for its strict new v1 profile. Keep the original Source READ while it verifies the pinned request/producer, empty attempt and exact retained row, then fresh owner, native descendant, exact-request and waiter absence under inspection-only scheduler custody. Its bounded cleanup clock covers cooperative checks and lock waits. A positive result permits Source-custody closeout; `storage_release_authorized` remains false. It acquires no native grant and writes no scheduler, ledger or storage state.

The 67 selected fictional-fixture controls qualify binding and freshness checks on their recorded `178e4ebd…` test generation. A separate [physical real-lock case](../../../../docs/autoformalization/evidence/legal-ir-no-child-native-closed-physical-e2e-20261109.json) passed on test `2b738a97…`: a genuine CLI acquired its native grant, exceeded its original admission deadline while blocked on the private ledger, launched no child, and was genuinely waited on before inspection. The Source-only verdict left private ledger/native state unchanged and the private claim retained; the outer 2 MiB validation claim separately closed durably. This qualifies the direct original-CLI-to-inspector path. The outer metadata wrapper's exception callback and arbitrary historical failures receive no new qualification. Existing pure classification and recovery contracts are unchanged. Preserve the earlier `e68968…` manual closure and retained 2 MiB claim; do not replay it through this profile or infer original-parent custody.

The current V5 acquired-before-child profile uses `inspect_owned_validation_no_child_native_closed_v5`; it is distinct from the V1 profile above and accepts only the original V5 bytes and exact typed pre-child deadline evidence. Only the original Source-held caller may use a positive observation to close its reads. The canonical supervisor first performs its existing genuine engine/Popen wait and verifies the same process, birth, typed complete EOF/result and closing source pins, then binds the explicit V5 inspector. `wait_and_inspect_owned_validation_no_child_native_closed_v5` is available to a caller that still owns its actual original Popen; it genuinely waits and clamps work to the earlier original/parent native deadline. Exhausted deadlines, wrong profiles or uncertain current custody remain UNKNOWN. Neither API creates a grant, renews a budget, releases storage, recovers a claim or authorizes replay.

The closed `owned-validation-request/v6` opt-in keeps admission and productive work at 180 seconds each and the original total at 420 seconds, always clipped by an earlier parent limit. The SDK publishes the first work epoch exactly once after verifying the attached direct child PID/birth and completing fresh accounting; the CLI releases its startup barrier afterward. Reattachment, late opt-in and second publication cannot renew authority. Fresh census and final inventory remain mandatory. The v6 inspector and waiter are `inspect_owned_validation_no_child_native_closed_v6` and `wait_and_inspect_owned_validation_no_child_native_closed_v6`; the explicit classifier is `classify_owned_validation_startup_clock_source_custody_v1`. They retain original request/terminal bytes, genuine wait and current typed custody checks. The acquired-no-child branch supports only SDK-open admission-deadline evidence before child launch with the exact empty attempt and retained row; uncovered post-open frames remain UNKNOWN. Any created/attached child excludes no-child classification even before work publication. Phase observations grant no storage release, Native grant, replay or clock reset. The selected 76-case private software result is not a host-v6 workload qualification; Source publication and current owned bytes are verified. [Exact software audit](../../../../workspace/test-logs/federal-corpus-audits/legal-ir-reviewed-component-cycle-20261110-Ex3yDW/reviewed-mixed-joint-adoption-v01/profiled-retention-integration-v01/independent-startup-clock-small-candidate-software-saved-DATA-v01.json).

The [qualified V5 caller summary](../../../../workspace/test-logs/federal-corpus-audits/owned-daemon-resource-control/retained-capacity-watchdog-v01/census-lock-followthrough-v01/completed-body-finalization-recovery-v01/v5-canonical-consumer-private-v01/coherent-four-file-source-CAS-private-v01/qualified-V5-original-caller-integration-summary-v02-peer-source8.json) separates the retained private R238 provider checks (89 new plus149 legacy in two operations) from canonical A163 caller checks (132 owner cases plus31 engine neighbors). All original Source/Native/process custody closed and each successful 16MiB promise was durably released. Inner caller Source/Native verdicts remain explicitly modeled dependency DATA. Preserve the failed v04 baseline and old B3 UNKNOWN/claim; administrative closure of an exact metadata observer is not an original successful parent/native/storage receipt. The current e25/fef watcher includes the exact finite producer/SDK pair after its separate54/49 qualifications and fresh Source29/configuration/unit publication. Current c239 keeps the complete4300 test prefix and adds separately qualified2 PRIVATE/LOCAL smoke cases. This does not enable A runtime dispatch, enroll candidates, restart productive workers or confer fresh admission; the natural0-API cycle is a point observation.

Reusable implementation belongs in `ipfs_datasets_py.logic.autoformal` or its existing shared numerical/operational owner. Authored regression tests belong in `tests/unit/logic/autoformal`. A run directory may contain frozen inputs and observations; it must not become a second production owner.

Use the [handoff](HANDOFF.md) to choose one bounded next action and the [owner map](ARCHITECTURE.md) to reuse its current API. Inspect existing closed cohorts before creating another training, test or inference request. Stale candidates and failed requests remain evidence, not reusable launch defaults.

Before installing a new profile or public API, refresh this handoff/catalog and the latest selected Git delivery receipts, then check the active owner in the existing task queue. A new qualified delivery may appear while candidates are being prepared; reuse its contract and reconcile overlapping candidates before canonical WRITE. Do not create a second task board.

## Existing execution owners

- Source custody: `optimizers/logic_theorem_optimizer/autoencoder_source_lease.py`, with the original outer lease and its default300-second acquisition wait where required.
- Owned native validation: `scripts/ops/legal_ir/run_owned_validation.py`, with exact request/source pins, finite resource envelope, admitted child/process supervision, complete artifact seals and original release evidence.
- Numerical operations: existing immutable checkpoint/prepared-session owners, with a separately reviewed finite contract. Inference does not authorize training, target-prefix probes, warmup, generation or extra retries.
- Documentation installation: source-WRITE custody plus checked preimages/CAS when shared source/docs are being installed. A wait timeout before acquisition is an unapplied change, not a completed installation.

Do not replace these with artifact-local schedulers or broad process/resource queries. Retain the original failure and closure status. Unknown native/storage release remains unknown until the responsible owner supplies exact evidence; no other task may infer cleanup from a source-lease release alone.

Bind each fresh attempt path in its request. Follow the selected existing launcher's declared directory-creation step with mode `0700` before owner admission.

### Validation capacity refusals

When `owner.open()` raises the original storage-capacity error, the validation
launcher emits one bounded JSON line on stderr with schema
`owned-validation-capacity-refusal/v1`. It carries the captured accounting
aggregates and separate storage-cap and physical-free-space deficits. It reads
no additional inventory or ledger and preserves the original exception and
failure lifecycle. Malformed observations or unavailable stderr do not replace
the failure.

This is the original refusal's observation, not a fresh admission decision.
Use the existing recovery owner to reconcile exact closed technical claims;
retain their original failures and artifacts. A later operation still needs a
fresh purpose-specific resource admission. The diagnostic grants no release,
retry, limit change or task completion.

### Ledger metadata refusals

The original CLI emits a typed lifecycle refusal when serialization exceeds the 16 MiB ledger bound before its first record is written. It binds the original SDK and storage-owner traceback, the exact request and the source generation. After waiting on the original CLI, the parent uses `classify_owned_validation_source_custody` to verify Source closure. Its `storage_release_authorized` field remains false. The focused 22-case result and original generic-refusal baseline are retained in the existing evidence capsule. [Validation and supervisor evidence](../../../../docs/autoformalization/evidence/legal-ir-canonical-v5-parent-source-adoption-20261110.json)

The interrupted v11 direct validation retains ACTIVE reservation `41915d6b255f49ffbed1f8526c0fcb15` at 16 MiB. Its startup-barrier error and original process absence remain attached to that request. The existing storage recovery owners require their supported terminal and custody evidence before reconciliation.

The earlier v10 generation was restored after the initial telemetry maintenance attempt. Its 06:03:29 UTC cycle closed Source with zero readiness, reconciliation or disposition API calls. The existing owner administratively released that expired hold while preserving the failed controller. The qualified v11 telemetry generation and its successful maintenance closeout are recorded in the [watchdog qualification](../../../../workspace/test-logs/federal-corpus-audits/legal-ir-watchdog-ledger-headroom-20261111-v01/qualification-summary.json).


### Typed sampled-validation storage recovery

The later P4 record has a closed 225-case qualification and an unrun 68-case admission failure after a native grant was acquired then released. Its caller required separate manual metadata Source closure, not an original parent Popen receipt. The earlier merged cancellation/timeout and all retained claims remain separate. These observations grant no storage recovery, alias deletion, fallback or blind replay.

The existing optimizer `autoencoder_resource_recovery` owner provides `inspect_sampled_validation_recovery_v1` / `reconcile_sampled_validation_reservation_v1` for the strict supported `sampled-validation-recovery-proof/v1` / original sampled-parent failure profile. Independently pin the original request, stdout/terminal, parent closeout and captured producer. Select genuine parent Popen-verified evidence; do not fabricate a handle or treat closure booleans as execution attestation. Other historical parent formats are unsupported.

An existing absolute cleanup deadline, exact row/root/artifact binding, fresh owner/observed PID and native root/descendant/request/waiter absence, and the final scheduler lock through the one storage write remain required. Readiness checks durable artifacts without census, grant or ledger write. Administrative closeout retains the full promise during censuses and requires independent actual postwrite census/disposition. Neither route releases native resources or establishes arbitrary containment. Preserve failed/ambiguous commits and inspect original state before a new operation.

[Exact source qualification and own32 closeout](../../../../docs/autoformalization/evidence/legal-ir-sampled-validation-recovery-20261109.json): 183 selected cases passed, original validation custody closed, and the separate own32 release preserved 44 files. Own64 remains retained; no generic-group, batch or external fallback was used.

### Nested tools and source custody

The 17-field validation request preserves the legacy `isolated_process_group` profile. Select `sampled_birth_bound_descendants` explicitly for nested native tools that create separate sessions. `ValidationResourceReservation` in the existing optimizer owner retains resource/storage custody; the existing operations launcher supervises execution and reuses the shared `logic/backends/process.py` birth/pidfd tracker. Legal preparation, review and Lean orchestration remain in `logic/autoformal`.

Attach and retain the isolated direct child before releasing its startup barrier. The tracked profile adds observed descendants outside that group to sampled RSS/process counts without counting group members twice, and retains observed identities across session changes and reparenting. This is cooperative ancestry observation, not kernel containment of unobserved escaping processes. The selected scope stays fixed for cleanup; historical group-only receipts gain no broader qualification.

Keep the original outer source READ through CLI exit and confirmation that observed groups/descendants stopped and native compute was released. On failure, use the original `owned-validation-failure-terminal/v1` emitted after the owner's `__exit__`, including its actual reservation, request hash, process observation and cleanup errors. The earlier `failure.json` cannot establish post-exit release. Retained storage and a failed qualification remain distinct from released compute.

After observing the original CLI exit, pass a pre-admission failure to `classify_owned_validation_source_custody` in the same canonical launcher. Supply exact request bytes and their independent SHA256, the original PID/birth and exit code, and `expected_resource_ledger` from the original CLI. Its typed `owned-validation-source-custody-lifecycle/v1` witness can establish the exact native timeout branch with no attempted child or barrier release and no acquired grant. The classifier rechecks the launcher and five ownership/scheduler source pins. Only `source_custody_closed=True` permits this separate no-child READ closeout; `storage_release_authorized` remains false. Null lease/process fields alone do not establish that verdict.

Missing or mismatched terminal evidence, survivors, observation errors or cleanup errors leave source READ held for responsible-owner cleanup. A final custody guard must retain it even if saving or printing diagnostics fails. Source-lease release alone never establishes native or storage release.

The existing `autoencoder_resource_recovery.py` owner exposes `reconcile_empty_unopened_validation_reservation_v1` for one explicitly reviewed historical unopened reserved claim. It requires independently pinned original request/failure/trace/controller evidence, exact source profile, absent original PIDs, an empty durable attempt, two fresh nonpersistent exact-request absence checks, full charged/projected censuses and a final full-ledger CAS. It records one administrative reserved-to-released storage transition while retaining the old abnormal closure and unknown historical native-release status. Existing retained-claim recovery defaults remain strict. A writeahead or postwrite uncertainty requires original-owner readback before another operation; it does not authorize a blind retry.

## Source-custody qualification and retained generations

The [selected evidence summary](../../../../docs/autoformalization/evidence/legal-ir-source-custody-reconciliation-20261021.json) records 492 passed cases and 1476 passed phases across four separate owning cohorts, their exact source identities and independent reviews. Each successful run has its own verified native, storage and source closeout. Referenced workspace receipts remain local retained evidence; this commit does not publish those logs.

The launcher no-child lifecycle classifier and the historical unopened-claim recovery API are distinct contracts. The latter supports the explicitly pinned historical profile only. The separate typed sampled profile above requires its own supported, independently pinned original-parent proof; source READ closeout alone never supplies storage recovery permission.

At its original qualification cutoff, the selected eligibility/cache profile was isolated from the primary cache generation. Integration must preserve both explicit contracts and their owning tests; it does not extend historical qualifications to changed source generations. No model training, statutory meaning approval or Lean execution follows from this engineering delivery. Keep the maintained navigation and packaging resources below.

### LegalIR task source and migration boundary

The [2026-10-23 source and deployment review](../../../../docs/autoformalization/evidence/legal-ir-supervisor-reference-plan-20261023.json) observes all four named LegalIR units active. Their installed selection is explicit `legacy-markdown` / `legacy_markdown`, board `legal-ir-autoencoder-v1`, from the immutable fleet release `abaab51bc0aaea7259cbc2789f1786d5479ff9c6`. This does not configure a typed LegalIR task scope. Inspect that deployed generation when reviewing these workers; current Accelerate source has a different generic gateway boundary.

The existing OS-user native bootstrap creates its protected credential internally. Authenticated status additionally requires an admitted scope: the owner binds 1–512 existing persisted task CIDs to board/plan/tree, or admits its separate federation consumer. A status client need not prelist those CIDs. An empty owner cannot supply that scope; the CLI `ready` projection is not an independent authenticated status read. Reject a missing consumer/scope before server construction, which can already create state directories. For an actual consumer retain the original OS lease, native capability, resource/storage, credential and terminal cleanup gates.

The original `LegacyStateImport@1` strict/default-REJECT board-only preview parsed 140 headings: 135 accepted engineering rows and five rejected conflicting `Goal` rows. Preserve these conflicts and the unchanged source. No runtime history was selected. The maintained 24 `LIR-*` items remain separate from the 135 `LIRAE-*` engineering items. Preview acceptance records provenance; even the existing apply route writes import bookkeeping, not typed task creation or scope admission. Before worker cutover, review the history and namespace/plan/tree mapping, qualify the existing task-creation/admission route, then verify the live scoped population through the original authenticated interface. Preserve attempts, failures and retry limits; imported rows cannot rearm historical tasks.

### Existing native programme and dedicated watchdog

The [current programme/runtime review](../../../../docs/autoformalization/evidence/legal-ir-programme-watchdog-review-20261026.json) reconciles the existing `LIR-G000` programme with the maintained backlog. Its 34 goals, 64 tasks, 33 goal links and 115 dependencies remain the single native hierarchy; the historical population and readback are linked in the [task-catalog guide](guides/legal_ir_supervisor_task_catalog_20261016.md). The backlog crosswalk preserves all original task/goal CIDs and 24 parent mappings. It does not open the native store or authorize claims, retries, dispatch or settlement. Bind current revisions and finite execution packets through the existing native owner before activation; preserve the historical `LIR-9001` frontier as an observation rather than rearming it.

The existing dedicated `ipfs-taskboard-legal-ir-watchdog.service` and `ipfs-taskboard-legal-ir-repair.service` use `~/.config/ipfs-taskboard-watchdog/legal-ir/fleet.json`; they now enrol both `legal-ir-autoencoder-v1` (board id `legal-ir`) and `legal-ir-span-graph-lean-refinement-20261016` (`legal-ir-scientific`). Reuse this loop and preserve the shared fleet. The engineering minute monitor retains bounded lane-restart ownership; the scientific probe performs isolated, bounded read-only SQL against the existing catalogue, with population/namespace/task/goal/plan/dependency checks. It does not construct a native owner or activate an executor. A stopped/unestablished executor and blocked task population remain visible rather than becoming a healthy empty fleet.

The [dual-namespace receipt](../../../../docs/autoformalization/evidence/legal-ir-dual-namespace-watchdog-20261027.json) binds the installed source `9daede14`, release `2b499e94d6c23f14cd72`, configuration, 92 selected focused passes and independent live verification. Both boards use closed `infrastructure-only/v1` policies: poll60s, three-action daily windows, one-hour circuit guards, three-attempt repair caps, watchdog cooldown180s/max-backoff3600s, full common/per-board operator holds and exact board/unit/attempt cancellation. Action history survives symptom changes, healthy flaps and restarts; malformed budget state escalates. Only configured infrastructure faults can enter the existing coding-repair route in the Accelerate engine checkout. Dependency/legal/activation waits, unknown outcomes and denied or exhausted retries cannot trigger native healing, task rearm, budget resets, catalogue repair or scientific dispatch. Missing/stale/mismatched observations remain unknown; observer freshness does not establish fresh catalogue facts after a failed read. An engineering recovery still requires the existing accepted-progress check when runnable work was stalled.

The actual controlled watchdog-main crash recovered in31.36s with both namespace views, task projection, database/WAL state, counters and prior repair job preserved; the repair service remained up. This supplies watchdog infrastructure evidence only. Preserve original failures and source pins, and require a fresh exact-bound observation after repair; a coding-process exit cannot grant native/legal/model/graph/Lean/corpus completion. [PR304](https://github.com/endomorphosis/ipfs_accelerate_py/pull/304) is published but unmerged because its required `documentation-gates` job did not start under GitHub's reported account billing lock. The separate `qualification` checks are not listed as required by current branch protection. The local profile uses the reviewed feature commit; keep public-main and parent-gitlink adoption pending the protected merge, without CI/rule bypass.

Intentional engineering maintenance uses the existing registered `maintenance_hold` owner and its exact engineering-board token. Keep scientific/global holds, task dispositions and repair counters unchanged. The completed 600-second window restored the existing capacity timer and released its registered hold (`ec8aa693`); a cached pre-release paused fleet report then triggered a coding-repair attempt refused by stale authorization (`348c2a65`). Later fleet/watchdog observations were healthy; the recorded three actions, nine total actions and open circuit remain historical evidence.

The selected replacement reserves 450 seconds of quiet and 120 seconds of cleanup within the original absolute 690-second controller deadline. Before releasing its own token, restore the capacity timer, start the **existing** fleet monitor once, require a fresh post-restoration healthy four-lane report with the exact enrolled dependency, and require the held watchdog to acknowledge that fresh healthy observation. If the start joins an older monitor cycle, wait read-only for a normal fresh report; do not start a second cycle or renew the deadline. On timeout, unhealthy status or an unverified hold binding, preserve the registered hold and its explicit recovery disposition. The selected window completed a natural 450-second quiet period and 35.205 seconds of cleanup in 493.247 seconds, within the original 690-second deadline (`faeaf6c9`). It restored the timer, started the existing monitor once, verified the fresh healthy report and held watchdog acknowledgement, then released and archived its exact own token. The budget remained three actions, nine total actions and an open circuit. The measured scope is the existing guarded coding-repair path for an inactive enrolled dependency. Maintenance evidence grants no Native, scientific-dispatch or budget-reset authority.

### Dispatch decisions for existing programme tasks

Use the [whole-corpus hierarchy](BACKLOG.json) and the latest
[handoff](HANDOFF.md#current-execution-priorities-after-artifact-review) together
with the [training history](TRAINING_HISTORY.md). The
[dispatch reconciliation](../../../../docs/autoformalization/evidence/legal-ir-programme-dispatch-reconciliation-20261028.json)
records planning observations and missing interfaces, not native admission or
another task queue. Read newer selected delivery receipts before historical
"next" instructions: completed captures, fits, scoring and artifact ports must
not be scheduled again merely because an older paragraph lists them as pending.

| Existing phase and parent tasks | Parallel work and acceptance fence |
| --- | --- |
| Lineage: LIR-01,03,16 | Reconcile current producer, source, checkpoint, codec and optimizer capabilities; reuse qualified deliveries and preserve original experiment results. |
| Source and review: LIR-02,05,06 | Prepare one complete norm, its governing definition and two distinct physical operative uses; authenticate edition/context and retain unresolved interpretation decisions. |
| Complete IR: LIR-07,09,10 | Check full-span representability, ordered roles, binders, counting, conditions, exceptions, time and lossless codecs before enrolling targets for training. |
| Graphs: LIR-04,08,11 | Preserve occurrence, mention, sense, entity, definition and norm identities; close reviewed edges and dependencies without merging alternatives or treating string matches as meaning. |
| Lean: LIR-12–15 | Reuse the interpretation and preservation owners; bind exact modules, imports, toolchain, premises and axiom policy. An actual pinned build and source-meaning review remain separate gates. |
| Models and cost: LIR-17–20,23 | Reuse retained assets and frozen outputs; select only a missing compatible comparison. Four native producer systems and a bypass-free bottleneck experiment are separate studies. |
| Release and expansion: LIR-21,22,24 | Require immutable readback and complete stage-specific dispositions; expand connected components, then the selected pilot and dependency shards, before claiming whole-manifest coverage. |

Preparation can proceed in parallel while semantic dependencies remain open;
its completion does not satisfy those dependencies. Existing protected claims,
resource owners and finite reviewed packets govern execution. Root retains
adoption, deployment and publication ownership. Keep exact UTF8 restoration
with a retained surface sidecar, canonical rendering and learned source-free
prose reconstruction separate under the existing
[reconstruction contract](HANDOFF.md#reconstruction-contract-for-model-promotion); none is a proxy
for autonomous complete-IR fidelity or statutory meaning.

The four-width plan currently exceeds native task-cell coverage. The selected
64-task population names `LIR-1902`, `LIR-1903` and `LIR-1904` for 8D, 384D and
768D, with `LIR-1905` for comparison; it has no dedicated 4096D cell. Record a
reviewed amendment under existing LIR-19 before dispatching that cell. Preserve
all original IDs/CIDs, revisions, dependencies, claims and failures; allocate
new native identity only through its owner. Reuse the existing Leanstral
captures and decoder profile, explicitly separating causal source width from
a learned legal bottleneck and declaring source-text/residual bypasses.

Keep model and cache identities separated by IR family, width, producer,
schema/version and decoder task. Reuse the existing inventory, ModelManager,
DuckDB/DuckLake and Hub owners and immutable payload references. Registration,
public availability, callable compatibility and measured quality remain
different states; a shared release index cannot make one family's checkpoint
or original optimizer state compatible with another profile.

Known-format decoder imports can opt into `decoder_identity_witness`
(`ir-decoder-identity-witness/v1`) on the import-plan model record. Pin the
original decoder profile inventory, select its existing checkpoint record ID,
and declare the target IR schema version separately from the checkpoint payload
schema. The importer checks the original format/profile/checkpoint identity
chain and exact JSON types through metadata conversion and persisted readback.
The witness stays in the import plan and outcome evidence, allowing existing
ModelManager rows to be verified and reused without adding metadata fields or
changing checkpoint IDs. Existing metadata-only imports keep their contracts.
The known-format inventory currently supports IntentIR and SecurityIR at 384D;
this check does not extend that support or establish numerical, runtime, teacher
or proof qualification.

### Watchdog decisions and deployment compatibility

| Observed state | Existing owner response |
| --- | --- |
| No admitted ready child; completed engineering work | Intentional idle. Keep observing; do not restart lanes to manufacture progress. |
| Source, review, context, dependency or activation block | Report the missing prerequisite against its existing task identity. Generic infrastructure repair cannot rearm or admit it. |
| Runnable work and a policy-allowlisted infrastructure fault | Use the existing bounded infrastructure repair owner, preserving holds, action/attempt limits and cooldowns; require fresh bound evidence and accepted progress after repair. |
| Unknown callback outcome or denied retry | Retain the owner, attempt history and budgets. Only exact outcome evidence through its native owner can settle the uncertainty. |
| Model, compiler or semantic failure | Return diagnostic evidence to the existing scientific task and its review/experiment gate. A service restart cannot establish reconstruction gain or corpus completion. |

The scientific catalogue observer deliberately reports `not_activated` and
`not_established`; it is not an executor-health or native-capability endpoint.
Qualify an extension bound to actual activation epoch, admitted task population,
claim/process births, meaningful progress and terminal receipts before using
the monitor to attest a scientific executor. A fresh observer timestamp alone
does not establish any of those facts.

The active LegalIR profile from [PR304](https://github.com/endomorphosis/ipfs_accelerate_py/pull/304)
uses `recovery_policy.profile="infrastructure-only/v1"`. The separate retained
owner work in [PR306](https://github.com/endomorphosis/ipfs_accelerate_py/pull/306)
uses `recovery_policy.schema="agent-supervisor/owner-retention@1"`; its closed
validator denies other present policies. Their individual qualifications do
not qualify a combined runtime. Reconcile these schemas in the existing
Accelerate watchdog/repair owners before rollout, preserving infrastructure
classification, cumulative budgets, shared-unit cancellation identity,
operator holds, retention denials and fresh-probe/effect-boundary checks.
Do not silently replace the functioning dedicated LegalIR generation or
install another loop. Catalogue recovery must leave scientific blocks intact.

Record publication, filesystem installation, configured runtime generation,
staged observation and admitted executor/current claim separately. A published
branch, installed file or healthy observer supplies no native execution grant.
Keep protected merges and superproject-pointer adoption separate from staging;
retain the previous usable release when either is pending.

### Recovery correction adopted, 2026-10-28

The [existing watchdog record](../../../../docs/autoformalization/evidence/legal-ir-dual-namespace-watchdog-20261027.json) preserves the original activation with 92 cases and 139 engineering cards and separately records Accelerate `d861eacc`. Three separate cohorts passed 110 classification cases (330 phases), 55 cases for the physical quota adapter and retry deadlines (165 phases), and six unchanged original route cases (18 phases). No actual provider, service, native database or model ran in those cohorts. Three generic cooldown expectations also fail on original `9daede14`; broader native-fixture, native-heal and subprocess-smoke attempts remain refused failures outside passing credit. Full generic-suite and live provider-repair qualification are not claimed.

Validated live non-restart backpressure waits without another coding repair, even with positive paused ready counts. Independent runnable work retains finite stall detection through a closed scheduling frame. The worker selects the physical strict-quota adapter/private `-P` receipt pipe. Durable infrastructure retry deadlines survive quick failures, source/route changes, reconciliation, productive continuation and clock-reversed early refusal. Positive cumulative caps, operator holds and exact cancellation remain mandatory. Healthy-state attempts/ensure_attempts are consecutive bookkeeping; their zero values do not replenish the separate durable action window or cumulative repair-job budget.

The reviewed transition changed only fleet/inventory source locations and the two dedicated unit source prefixes, retaining standalone release `2b499e94d6c23f14cd72`. Both units are active/enabled on the clean worktree `/home/barberb/lift_coding/.worktrees/legal-ir-watchdog-recovery-contract-20261028` at `d861eacc`. Fresh post-start observations show 141/141 engineering cards healthy and 64 scientific tasks blocked, cursor 214/generation 19, with LIR-9001 revision 13/attempt 2 still UNKNOWN and automatic retry refused. The retained job hash and engineering budget bytes are unchanged: three cumulative attempts and three daily actions (three total); the scientific durable-budget file remains absent. No other unit, native task or provider operation changed. Independent review binds metadata and process environment, not whole-process imports or live provider execution.

[PR 304](https://github.com/endomorphosis/ipfs_accelerate_py/pull/304) publishes `d861eacc` but remains open/blocked. Its only required check, `documentation-gates` (app 15368), did not start under GitHub's account billing lock; normal merge was refused by base-branch policy. No bypass was used. Public-main and parent Accelerate gitlink adoption remain pending. Retain this active clean worktree until a reviewed successor deployment replaces it; it is the selected checkout of existing Accelerate owners, not a duplicate implementation. Preserve all explicit and old/new cwd holds, failed logs and spent counters.

## Documentation and migration

Maintain this module's README, handoff, architecture, training history, operations and original task backlog in place. Detailed API guides live in `docs/guides`; old handbook paths redirect here. Update one current plan instead of appending the same paragraph to several dated plans. Preserve historical task identities/dependencies and reference a precise new result rather than duplicate a complete run tree.

The single maintained [work catalog](work_catalog.json) records current owners, selected evidence and references to migration provenance. Historical migration records retain original path/hash/size, canonical destination, action and candidate/postimage identity; do not create another active ownership registry or evidence index. Relative guide links are resolved from their original location and rewritten to the canonical guide destination. Original guide and retired-plan bytes are archived before redirect installation. Historical raw/canonical hashes and absolute producer identities in retained receipts are not silently rewritten.

When adapting an existing request, preserve its project source forest **and** its explicit support-data pins. Package lookup tables and distribution METADATA can sit outside the project tree. The [reference-capture follow-up](../../../../docs/autoformalization/evidence/legal-ir-cp128-reference-coverage-observations-20261025.json) records two failed generations with omitted support pins, followed by a separate successful zero-model denied-read probe. Retain the failures, captures and original recovery receipts; a diagnostic success cannot backfill a missing source archive or upgrade the failed numerical pipeline. Reuse completed forwards as explicitly partial evidence and require a named consumer before repeating them.

## Evidence and portability

The [work catalog](work_catalog.json) maps current owners to selected dated observations; [ARCHIVE.md](ARCHIVE.md) explains the preserved historical material. Large reports, checkpoints, source snapshots, raw cache rows and closed native attempts are evidence data; they do not belong in ordinary package imports or an agent's initial context. Preserve original paths where existing pinned manifests depend on them and use catalog descriptors to locate the exact bytes. A local catalog entry is not proof that untracked evidence has been published or will travel in a repository clone.

New evidence should use one explicitly configured evidence root and a versioned manifest referring to canonical implementation owners. Keep paths relative to their declared root where the existing profile supports it. If a historical profile authenticates an absolute producer path, declare that portability limit; relocating the package does not requalify its observations. Do not alter old pins merely to make a relocated path look current.

## Checks for a focused change

Validate candidate Python/JSON/Markdown and relative links without importing numerical/model/native owners. For implementation changes, run only the relevant finite cohort through the existing owner after exact source review; record planned versus actually completed cases/phases and all exclusions. A terminal progress dot is not a qualified case record. Preserve unrun negative branches explicitly.

For parent Lake work, the newer directory-alias fixture is a different transport test from the former interior-file symlink fixture. Enroll its exact current bytes and complete population before another run. A source-only optimization or successful preparation is not a native Lean build or measured speedup.

The work-catalog navigator distinguishes archived prototypes with installed canonical successors from unselected archival material in its summary. Its `--check` mode checks metadata joins as well as named paths and declared APIs. These checks do not import registered owners or qualify experiments.

The earlier `scripts/ops/legal_ir/verify_autoformal_documentation.py` is an unchanged verifier for the superseded documentation layout. Use `python ipfs_datasets_py/logic/autoformal/work_catalog.py --check` for current navigation. Its original manifests, installation records, patches and compressed evidence remain immutable history; do not run the old verifier as the current migration gate.

## Distribution packaging

The canonical module README, catalog/backlog JSON, maintained Markdown guides and
the exact `docs/history/pre-consolidation.zip` archive are declared in both
`setup.py` and `pyproject.toml`, with matching `MANIFEST.in` rules for source
distributions. The narrow patterns preserve this module's navigation resources
without including checkpoint files, runtime workspaces or arbitrary history ZIPs.

The [packaging qualification](../../../../workspace/test-logs/federal-corpus-audits/autoformal-packaging-20261020-01/qualification-summary.json) passed three new packaging controls
and two existing catalog controls. Real setuptools `build_py` copied the selected
package fixture; its source tree was then removed before catalog checking, task
lookup and component lookup. All 168 declared resource files matched, nine decoy
runtime/evidence paths were excluded, and missing installed metadata refused
without a checkout fallback. The tests import the navigator by file and never
execute package initializers or registered numerical owners.

This is a bounded packaging fixture, not a full release wheel/sdist build or an
end-to-end inference qualification. Optional historical evidence links outside the
package still require their separately retained repositories/workspaces. The test
owner recorded source, native and storage release. The regression test is
[`test_autoformal_packaging.py`](../../../../tests/unit/logic/autoformal/test_autoformal_packaging.py).

### Reviewed preservation replay

Use the existing shared-corpus and native reviewed-preservation APIs. Their retained packet binds exact source, output, process, toolchain and receipt bytes. Lake declares all six preservation modules as explicit roots. The qualified obligations preserve the typed representation under their stated premises. The private native build, the 38-case fixture regression and each canonical run retain their own receipts. The source-meaning review, original-success adapter and unified corpus release join remain open. [Reviewed preservation evidence](../../../../docs/autoformalization/evidence/legal-ir-genuine-parent420-retention-integration-20261110.json)
