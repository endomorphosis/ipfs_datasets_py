# LegalIR supervisor task catalog

Date: October 16, 2026.

The legal autoformalization plan is now stored through the native `ipfs_accelerate_py` supervisor APIs. Its first delivery target is one reviewed statutory definition, one complete norm using it and a second genuine use, represented consistently in the span cache, scoped entity graph and a Lake-built Lean4 library.

The catalog contains one objective, 34 goals, 64 tasks, 33 parent-goal links and 115 task dependencies. It preserves the original 24 LIR parent mappings. Native readback checks each goal's parent and metadata and each task's dependencies, outputs, acceptance criteria and complete authoring metadata. A separate process reopened the catalog without changing its event watermark or projection identity.

The [native intake receipt](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-supervisor-plan-20261016/catalog-02/readback.json) records the exact population and source request. The store is `workspace/test-logs/federal-corpus-audits/legal-ir-supervisor-plan-20261016/catalog-02/control.duckdb`. It is a dedicated planning catalog, separate from the older autoformal repair queue; no existing live task status was overwritten.

## Documentation and source inputs

Read the [LegalIR corpus improvement plan](../../../../../docs/autoencoders/legal_ir_uscode_corpus_improvement_plan_20261015.md), [API map](../../../../../docs/autoencoders/api_map.md), [training guide](../../../../../docs/autoencoders/legal_training.md), [control plane guide](../../../../../docs/autoencoders/control_plane_and_sync.md) and [shared Lake guide](legal_corpus_shared_lake.md).

In the enclosing `lift_coding` workspace, the current execution documents are:

- `implementation_plan/docs/legal-ir-autoformalization-roadmap-2026-10-16.md`.
- `implementation_plan/docs/legal-ir-next-implementation-plan-2026-10-16.md`.
- `implementation_plan/docs/legal-ir-supervisor-operations-2026-10-16.md`.

The intake freezes their exact bytes as context snapshots. The authoring plan is retained under `artifacts/legal-ir-supervisor-start-20261016-01/staging/authoring/` in that workspace. Its `tasks.json` is an authoring manifest, not the native population schema. The reviewed adapter is `artifacts/legal-ir-supervisor-task-intake-20261016-03/intake.py`; its immutable request records all input and producer digests.

The three corpus inputs have separate roles:

| Dataset | Role |
| --- | --- |
| `justicedao/ipfs_uscode` | Versioned source text, lexical/vector indexes and structural graph |
| `justicedao/uscode-autoformal-span-cache` | Source-bound compiler/autoencoder observations, disagreements, evidence and deferred goals |
| `justicedao/uscode-autoformal-entity-cache` | Entity/term/definition projections with lossless semantic companions |

Their immutable revisions, editions, physical occurrences and selected configurations must be reconciled before treating a historical span as part of a newer source release. Source packaging status, candidate agreement and graph rows do not establish formalized law.

## Goals and parallel tasks

Root `LIR-G000` has seven workstreams, 24 parent-aligned subgoals and two separate handoff/engineering subgoals. The complete task and goal lists are retained in the native [population export](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-supervisor-plan-20261016/catalog-02/population.json).

| Workstream | Goal | Representative tasks and handoff |
| --- | --- | --- |
| Source identity and runtime ownership | `LIR-G010` | `LIR-0101/0102`, `0201/0202`, `0301/0302`; exact assets, source/context, compatibility and eligibility |
| Reviewed statutory supervision | `LIR-G020` | `LIR-0501/0502`, `0601/0602`; complete component, frozen exposure policy and actual review decisions |
| Typed meaning and composition | `LIR-G030` | `LIR-0701/0702`, `1001/1002`; supported operators and complete ordered interpretations |
| Scoped semantic graphs | `LIR-G040` | `LIR-0401/0402`, `0801/0802`, `0901/0902`, `1101/1102`; endpoints, every-use definition binding and graph closure |
| Lean corpus and invalidation | `LIR-G050` | `LIR-1201/1202`, `1301/1302`, `1401/1402`, `1501/1502`; shared semantics, actual Lake and changed-dependency controls |
| Decoder and representation improvement | `LIR-G060` | `LIR-1701`–`1703`, `1801/1802`, `1901`–`1905`, `2001/2002`, `2201/2202`; reviewed training, dimension/retrieval controls and feedback |
| Release, costs and expansion | `LIR-G070` | `LIR-2101/2102`, `2301/2302`, `2401`–`2403`; coherent readback, measured cost and connected expansion |
| Native handoff | `LIR-G090` | `LIR-9001`–`9004`; reconcile existing work, bind capabilities, review task packets and qualify dispatch |
| Matched engineering experiment | `LIR-G091` | `LIR-9101`–`9108`; separate conditions-ranking experiment with its own qualification |

The initial native frontier is **`LIR-9001` only**. The other 63 tasks are phase-blocked; original authoring statuses remain preserved separately. Intake does not complete the reconciliation, activate a configured board or launch workers.

Conditional parallel frontiers include `0201/0301/1601` after compatible baseline/handoff work, `9102/9103` after the E1 design, and `1902/1903/1904` after the representation contract. Use the full recorded dependencies. Graph and Lean engineering can proceed alongside reviewed-target preparation where their exact input gates permit it. Do not remove parent dependencies to increase concurrency.

## Native intake and recovery

The existing `logic.autoformal.supervisor_loop.ingest_population()` forwards the reviewed population to `DatabaseTaskSource.materialize()`. The adapter uses the supervisor's own identity primitive and preserves explicit parent CIDs and `goal_parent` edges, CID-resolved task dependencies, mapping-shaped outputs and separate acceptance entries. It does not use the generic taskboard converter that drops hierarchy/output metadata.

The `prepare` operation freezes inputs. `apply` refuses an existing catalog generation. `verify` performs readback without materialization and should run through the existing native control owner. An uncertain or partial import requires reconciliation; do not repeat an upsert blindly, reset attempts or overwrite statuses. Apply later changes through native revision/CAS owners.

The finite import used the existing F07 scheduler/storage owners with a 64 MiB disk envelope. Connections were closed, outputs synced and the native ancestry released. The earlier import-origin failure stopped before opening a database and remains recorded in the enclosing workspace. The successful attempt selects the intended Accelerator tree and keeps the canonical Datasets compiler/parser/decompiler guard.

## Execution packets and acceptance

Before activation, bind every task's current revision/dependencies, source and input hashes, input roles, exact commands and cwd, output paths, code/test allowlists, exclusive file/writer keys, resource budgets, deadline, verifier and independent acceptance role. All 64 original validation lists remain empty pending those packets; acceptance prose must not become an executable command or automatic completion.

Use isolated worktrees and private worker state. Serialize canonical source merges, database writes, checkpoint selection and publication. One owning process writes each native DuckDB file; other machines use qualified transports and immutable artifacts. Preserve model-specific sparse reductions. Arrow's existing legacy feature-weight mapping is not a generic formula/768D/4096D zero-copy path. See the control plane guide for actual supported codecs.

Training, retrieval and evaluation consumers must enforce the same source/review/target/split/exposure contract before consuming a population. Preserve unknown/disputed/unsupported labels and failures in coverage counts. Compiler labels and authored fixtures retain their disclosed supervision roles. The 8D linguistic teacher, source-conditioned formula heads and wider genuine-representation models remain separate lineages.

Use the canonical `external/ipfs_datasets` logic tree, temperature zero, fixed encoder context, no downloaded weights and no Mathlib. Preserve archived checkpoints and foreign edits; do not synchronize HACC or `hallucinate_app` by editing them.

Only actual **`lake build <Lib>`** of the selected complete generated library supplies Lean admission evidence. Direct compilation, syntax, decompilation, cosine/loss, solver output, NCA cells, database flags and Hub publication are separate observations. Lake checks emitted statements and dependencies; legal meaning/applicability needs its own review. The Constitution remains unformalized and receives no `roundtrip_ok`.

Release only after exact readback across source/span/entity/model/Lean manifests. Keep prior coherent releases and all unresolved populations. A physical two-host restart/update/reconstruction test is required before claiming cross-machine training qualification; importing this catalog does not supply it.

## Pure handoff execution-packet preparation

`supervisor_loop.prepare_handoff_execution_packet_v1` is the existing hierarchy owner's metadata-only preparation API for `LIR-9001`, `9002`, `9003` and `9004`. It does not replace native intake, task-contract identity, scope admission or execution routing.

Supply four keyword mappings: `programme_links` from the maintained programme crosswalk; reviewed `current_directives`; selected `current_task_metadata`; and the requested `execution_envelope`. Current metadata is supplied context, never authenticated merely because a field or Boolean says so. The helper copies JSON data and opens no descriptor, store or model; it creates no CID and invokes no command.

The envelope retains exact alias/task/goal/plan/tree/revision/dependency bindings; declared model family/schema/decoder task/source width/bottleneck/sidecars and context limits; role/use-bound immutable input descriptors; argv/cwd/output paths; code/test/exclusive scopes; finite positive resource/retry budgets; and distinct worker/verifier identities. Repeated argv arguments retain their order. Known target, review or target-derived content cannot become inference input through another path or a false derivation flag. A combined file needs a separately supported projection/selector contract; this preview supplies no such exemption. Separate learned reconstruction and retained-source restoration contracts keep their own information-access qualifications.

The result schema is `legal-ir-supervisor-handoff-execution-packet-preview/v1`. `metadata_complete` and `metadata_blockers` describe supplied syntax/consistency only. `independent_verification_gates` still require original-owner current revision/dependency/scope verification and independent byte/profile/permission/acceptance verification. Every authority flag stays false and both supervision masks stay zero, even for complete metadata or a supplied exhausted-attempt disposition. Historical attempts are not rearmed and native task/goal state is not changed.

The [owning tests](../../../../../tests/unit/logic/test_supervisor_handoff_execution_packet.py) are disclosed authored metadata fixtures. The [retained qualification](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-programme-review-20261022-05/comprehensive-plan-review-v01/supervisor-handoff-v01/execution-packet-preflight-v01/validation-01/attempt/exports/unit-results.json) executes the actual selected-function AST under the original finite native/source owners: 11 methods, 44 subcases and 59 function entries, with no skips or effect-fence refusals. This is not default module/package integration, authenticated native admission, a statutory/decoder experiment or legal/training/gold approval. Never substitute the preview or these tests for the final native verifier.

### Explicit control-metadata mode

For factual work reconciliation, capability inventories and review/dispatch preparation that use no autoencoder, set `execution_envelope.execution_kind` to `control_metadata_only`. Its model `profile` must be absent or JSON null. Every input must use `verification` or `provenance`; `representation`/`checkpoint` roles and any per-input `profile` field are forbidden. All identity, current-revision, dependency, disposition, command, scope, budget and independent-verifier checks still apply. Omitted execution kind defaults to `model`, with the original decoder/schema/width/bottleneck/sidecar/context checks. Unknown kinds block preparation. This explicit mode supplies no authentication of caller roles, descriptor contents or actual command effects; final native verification remains mandatory.

The [separate follow-up qualification](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-programme-review-20261022-05/comprehensive-plan-review-v01/supervisor-handoff-v01/execution-packet-preflight-v01/native-handoff-followup-v01/independent-result-review-v01.json) passed 14 methods / 67 subcases and prepared four actual previews from retained LIR-9001–9004 snapshot metadata. These remain incomplete: no operation commands/cwd, budgets, principals, verifier, reviewed directive mapping, complete attempt histories or exhausted-attempt disposition were invented. Snapshot revisions are 13 for LIR-9001 and 2 for LIR-9002–9004; these observations do not establish current native status. Retained LIR-9001 spent its budget of two attempts and has UNKNOWN provider outcome. Its old factual reconciliation output is reused as prior evidence, never as a provider-success receipt; the old revision-11 command is not a revision-13 launch default. Preserve original-owner amendment/rearm ordering (the retained recovery review identifies exact revision 14), all failures and the existing dependency frontier. Do not query a remote provider with a local native attempt/invocation ID or infer outcome from another status read.

## Current job packet inventory preparation

`supervisor_loop.prepare_current_job_packet_index_v1` and
`verify_current_job_packet_index_v1` extend the existing metadata owner for
`LIR-9003`. Seven authored stdlib controls passed under the original bounded validation
owner, with source, child, native-capacity and storage custody closed. This
qualifies the selected pure function ASTs; whole-package integration and native
task admission remain separate. Supply the complete current 64-task native
projection, the accepted `LIR-9002` capability report and its separate verifier
result, explicit packet proposals and a producer principal. The report joins
completed9002 revision4 to its revision3 verification commitment and preserves
completed9001 revision15 with its unresolved historical provider outcome.

Every existing task receives a revision/dependency/record commitment and an
explicit disposition. Missing packets remain `packet_missing`; completed scopes
remain retained. Supplied metadata needs source-bound operation, validation and
verifier argv, exact native output/exclusive keys, role-bound inputs, finite
resources, distinct acceptance principal and retry/invalidation keys. The first
profile supports model-free control metadata with zero model tokens and no code
edits. Scientific purposes retain their unavailable or unbound capability facts.
The preparer opens no descriptor, database or provider and does not execute argv.

`full_index_coverage` includes negative dispositions. It does **not** mean all
productive tasks have reviewed executable packets. Both preparation and frozen
independent reconstruction explicitly return
`productive_runnable_coverage_complete=false`, `task_acceptance_satisfied=false`
and no completion, admission or dispatch authority. A metadata inventory cannot
complete `LIR-9003` or activate productive work. Existing native task owners must
separately bind current source/input bytes, purpose grants, review and lifecycle
before any task becomes runnable. Caller principal strings and supplied source
hashes remain unauthenticated by this pure API.


### Concrete metadata CLI

The existing `scripts/ops/legal_ir/run_autoformal_supervisor.py` adds the early
`job-packet-index prepare|verify` route before repair/native-store setup. This
source addition awaits cold normal-package qualification. It calls the existing
pure owner directly; it does not claim a task or launch a supervisor.

A frozen `legal-ir-job-packet-index-cli-inputs/v1` object supplies exactly
`canonical_owner`, `inputs` (current_snapshot, capability_report and
capability_verification file descriptors), `reuse_audit`,
`primary_snapshot_root`, `packet_proposals`, `producer_principal` and
`expected_task_revision`, plus its schema. Use the single existing completed
engineering reuse capsule. The CLI checks its four packet/receipt pairs,
13 source and11 evidence snapshots, matches the13 current PRIMARY owners and
joins49 current child CID/revision records through22 parent contexts. Historical
W-only generation differences stay context. Captured sources are read as data;
the four completed materializers are never rerun or given native bindings.

The first concrete profile requires a metadata-complete9003 self packet;
9004 may retain its pending metadata qualification packet. Both remain subject
to current dependency acceptance. Shared prior-evidence descriptors bind the
three external metadata files and reuse capsule once. The inputs file's own
hash belongs only in the original outer request, avoiding a self-reference.
Actual commands, principals, output ownership and declared file bytes must
match the self packet. All-negative inventories remain pure API previews.

Run `job-packet-index prepare --inputs <absolute-inputs> --output <index>
--freeze-out <freeze>` under the existing original source/native/storage owner.
After that producer closes, a distinct original verifier runs
`job-packet-index verify --inputs <same-inputs> --report <index> --freeze <freeze>
--verifier-principal <distinct-principal> --output <verification>`. Every path
is absolute; output files are created exclusively. Bind exact argv to the
self packet rather than substituting these documentation placeholders.

Descriptor checks and reuse counts are emitted separately in CLI evidence.
The canonical report and verifier retain their existing false admission,
completion, runnable-coverage and task-acceptance flags. Actual independent
review, current original task authority and purpose-specific admission remain
required before unblocking. No scientific/model/Lean or whole-corpus acceptance
follows from this metadata route.


The CLI reconstructs the shared review context from actual retained files and
current primary source bytes, and requires that exact context in the LIR-9003
self proposal. Its producer freeze therefore covers the four retained packets
and receipts, 13 source comparisons, 11 evidence snapshots, 49 current child
bindings and seven explicit implementation scope gaps. The independent verifier
reconstructs these facts again. Historical private-worktree comparisons remain
context only; this metadata route grants no code or task admission.
