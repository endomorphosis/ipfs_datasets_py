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

## Current full-corpus execution contract

The maintained goal is the entire pinned US Code population. The initial reviewed component and20–40 connected provisions are gates on expansion. Continue using the34-goal/64-task native hierarchy above and the original24 records in [BACKLOG.json](../BACKLOG.json). Its `supervisor_programme` metadata and per-record `supervisor_execution` crosswalk preserve the historical aliases/CIDs without opening the native database, importing again, changing live status or granting dispatch. The12 handoff/engineering tasks without a24-item parent remain separately linked at the programme level.

The original `LIR-9001`-only frontier is an import-time observation. Reconcile current task revisions, completed work and exhausted attempts before preparing `9001`→`9004`; no guide or JSON crosswalk rearms a historical task. The current `current_programme_directive` in the primary maintained backlog takes precedence over superseded experimental suggestions, but all changes to existing native records use the native revision/CAS route. Preserve original dependencies and apply conditional parallel frontiers only after their actual gates. Reuse completed `LIR-1601` work rather than scheduling it again.

The supervisor must receive a reviewed execution packet for each selected task:

| Packet field | Required binding |
| --- | --- |
| Identity | Existing task CID/revision, goal/plan CIDs, original dependency revisions and selected repository tree. |
| Inputs | Exact source/cache/model/codec/code commitments, edition/coordinate namespaces, complete context and explicit input roles; no target-derived inference context. |
| Execution | Exact argv/cwd, selected supported job template/provider, output paths, code/test allowlists and exclusive keys. |
| Limits | Existing source/native/storage owners, finite CPU/memory/storage/process/update/token/deadline/retry envelope and retained failure/cleanup policy. |
| Acceptance | Independent verifier and role; distinct engineering/source/meaning/representation/graph/Lake/proof/release claims. Missing commands or legal decisions block the relevant stage. |
| Adoption | Supported task authority plus authenticated namespace/plan/tree/task-scope admission and exact persisted readback. Intake and JSON presence are insufficient. |

Keep existing Grok lane routing and the repair dispatcher's configured model choice. Legacy135-task engineering completion is not34-goal/64-task admission or full-USCode completion. Preserve their separate namespaces and original histories.

Partition expansion by exact occurrence and closed dependency component. Use a stable partition identity binding source revision/edition, physical membership, stage, IR/schema/task/profile and dependency versions. Every requested span receives a durable disposition; account for editorial exclusions, missing context, unsupported constructs, ambiguity and failure. Retain complete typed AST/source witnesses beyond compact term/entity indexes. A source/definition/review/model/toolchain change invalidates affected descendants, and a new competing definition reopens relevant negative lookups.

Only the declared reviewed/admitted subset enters a coherent formal-corpus release. Full-corpus closure remains false while operative meanings, governing-definition applications, complete targets, graph dependencies or required complete-library Lake/preservation evidence remain unresolved. Release manifests bind all three immutable dataset revisions, graph/source maps, model/profile identities, review and proof receipts and the toolchain. Native goal settlement must independently bind this policy to exact revisions; neither a work-count dashboard nor the watchdog supplies it.

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
