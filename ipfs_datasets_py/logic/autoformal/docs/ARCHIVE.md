# Archive and migration map

Current development starts at [HANDOFF.md](HANDOFF.md). This page is the map to preserved evidence and retired documentation. The consolidation relocates maintained guides beside their implementation and retires four overlapping append-plan entry points. It does not erase failed attempts, repin old receipts or count archived candidates as current production code.

## Maintained versus historical material

| Material | Treatment |
| --- | --- |
| Module implementation and regression tests | One canonical owner; artifact snapshots/candidates are evidence only. |
| 157 LegalIR guides at the consolidation cutoff | Moved to `docs/guides`, with relative links rewritten and old handbook paths redirected. Original bytes remain in the migration archive. |
| Four overlapping current append plans | Original bytes archived; old paths redirect to the maintained handoff. Legacy bookmarks identify archived sections. |
| Existing 24-task backlog | Preserved as `BACKLOG.json`, including the original whole task records, order and dependencies. The extensive old evidence-root snapshot is archived and indexed, rather than maintained as a second active ledger. |
| Generic autoencoder handbook and unrelated modalities | Remain under repository `docs/autoencoders`; their LegalIR entry points route here. |
| Dated run scripts, frozen source trees, reports and checkpoints | Cataloged with their implementation owner and observed status. Historical evidence paths and pins remain explicit. |
| Unapplied proposals and stale candidates | Retained as unapplied/stale; never silently installed or treated as completed work. |

The [work catalog](work_catalog.json) is the single maintained owner/evidence index. It references the [portable pre-consolidation archive](history/pre-consolidation.zip), its original member paths and hashes, migration provenance and portability limits. That archive preserves original guide, plan and backlog bytes, the earlier broad inventory, and selected context150/gated/journal experimental source files as historical data. Use the catalog and archive to recover original bytes, rather than reading every historical plan into a new agent's context. The existing `docs/autoformalization/evidence/work_inventory.json`, consolidation archive/records and qualification receipts remain immutable broader-survey evidence at their original paths. They are referenced from the work catalog; they are not a second active registry and are not copied into another maintained evidence index.

## Previous handoff chronicle

The former append chronology is preserved byte-for-byte in the [published handoff at `943e85c247cfc31cdb990518c6ae3bfedf210ceb`](https://github.com/endomorphosis/ipfs_datasets_py/blob/943e85c247cfc31cdb990518c6ae3bfedf210ceb/ipfs_datasets_py/logic/autoformal/docs/HANDOFF.md): 201,584 bytes, SHA-256 `b6c41a6ae3c264e24827faf955812374fd677337c8bb9f424fa5ec200402adc9`. The comprehensive-plan review also retains its before-image. The maintained [HANDOFF.md](HANDOFF.md) now gives the current delivery plan; use the old chronicle for dated evidence and original receipt limitations, not as a second active queue. No historical source/meaning contract or qualification is broadened by this navigation change.

## Older planning entry points

The following workspace-relative files retain dated planning or specification prose, including active-language sections and links to older artifact backlogs. Read them as historical evidence and contract provenance; the maintained delivery queue is HANDOFF and the same 24-task BACKLOG. Do not create a second queue from their older pending-work lists. Original source/meaning decisions, acceptance requirements and versioned specifications remain binding until explicitly superseded in their owning contract; a planning redirect does not supply missing decisions.

| Workspace-relative entry | Treatment |
| --- | --- |
| `implementation_plan/docs/legal-ir-autoformalization-roadmap-2026-10-15.md` and `legal-ir-autoformalization-roadmap-2026-10-16.md` | Historical roadmap snapshots; reconcile later observations through the maintained handoff. |
| `implementation_plan/docs/legal-ir-next-implementation-plan-2026-10-16.md` | Retained incremental source/adoption progress and limitations; its artifact-local next plans are subsystem evidence. |
| `implementation_plan/docs/legal-ir-training-review-and-corpus-plan-2026-10-13.md` | Historical model/typed-contract evidence; use current training history for completed-run status. |
| `implementation_plan/docs/legal-ir-span-graph-lean4-implementation-plan-2026-10-13.md` | Historical programme and old backlog links; preserve the original 20–40-provision acceptance criterion in current LIR-05. |
| `implementation_plan/docs/legal-ir-definition-profile-extension-spec-2026-10-15.md` | Versioned historical design/specification; do not infer its missing meaning or source-adoption effect is implemented. |
| `external/ipfs_datasets/docs/autoencoders/legal_ir_uscode_corpus_improvement_plan_20261015.md` | Retained dated model/corpus history; current next-work ordering belongs to this module. |

Existing October17/18 redirect stubs and archived span/graph/Lean plans keep their original targets. Supervisor production, recovery and operations documents describe their subsystem transport and execution contracts; they are not a replacement LegalIR task board. Reusable product changes belong in the external owner map; historical captures, checkpoints and failed attempts retain their original paths and hashes.

## Selected evidence frontiers

Paths below are relative to the enclosing development workspace; some evidence lives outside the Git checkout. They identify local saved records and do not imply public availability.

| Workspace evidence path | What it establishes |
| --- | --- |
| `artifacts/legal-ir-cp128-zero-conditioning-probe-20261019-01/STATUS.md` and `audits/zero384-prefixes-19-39.json` | Actual two-forward zero-conditioning diagnostic; independently audited state/RNG/lifecycle closure. |
| `artifacts/legal-ir-cp128-zero-conditioning-probe-20261019-01/audit/model-variant-reuse-review.json` | Persistent-conditioning implementation reuse and completed context150 result, distinct checkpoint profiles. |
| `artifacts/legal-ir-cp128-zero-conditioning-probe-20261019-01/audit/cache-producer-source-frontier.json` | Existing producer chain, per-document versus historical 64-document ordinal boundary, missing original-offset map. |
| `artifacts/legal-ir-cp128-zero-conditioning-probe-20261019-01/plan-reconciliation/` | Reviewed but unapplied documentation proposals and two source-WRITE wait failures. |
| `artifacts/legal-ir-cp128-conditioning-readiness-20261019-01/` | Saved-score analysis, finite C1 design and reconciliation of both earlier physical budget cohorts. |
| `artifacts/legal-ir-budget-inference-20261019-01/` | Earlier128forward budget cohort and its source-isolation limitations. |
| `artifacts/legal-ir-cp128-budget-pilot-20261019-01/` | Later128forward source-isolated budget cohort on the same two examples. |
| `artifacts/legal-ir-role-source-isolation-20261019-01/` | Fixed role-priority campaign and checkpoint lineage; native checkpoint bytes remain in the corresponding owned workspace attempt. |
| `artifacts/legal-ir-plaintext-definition-use-20261019-01/` | Closed 141-case / 423-phase lookup/use qualification, with earlier failed physical attempts retained separately. |
| `artifacts/legal-ir-parent-use-review-20261019T192000Z/delivery.json` | Installed parent combined-use review and 28-case / 84-phase closure. |
| `artifacts/legal-ir-parent-use-lake-20261019-01/README.md` | Earlier parent preparation failures01–03; preserve their separate unknown closeouts and stale proposal. |
| `external/ipfs_datasets/workspace/test-logs/federal-corpus-audits/legal-parent-use-lake-20261019-01/qualification-summary.json` | Later separate 30-case current-preparation success, installed source/fixture identities and original source/native/storage release. |
| `artifacts/legal-ir-parent-use-native-20261019T193900Z/` | Historical proposal; its parent extension now has an installed canonical successor in `legal_corpus_definition_use_native_v2`. The proposal itself remains unqualified evidence. |
| `external/ipfs_datasets/workspace/test-logs/federal-corpus-audits/autoformal-source-migration-20261019-01/qualification-summary.json` | Canonical source migration: 88 unique controls passed (64 experimental, 19 parent-native, 2 catalog, 3 official); exact receipt identity lives in the single work-catalog evidence record. No original checkpoint replay, convergence or real parent Lean claim. |
| `artifacts/autoencoder-comprehensive-review-20261013/implementation-backlog.json` | Historical source of the original24ordered task records and extensive evidence fields. |
| `external/ipfs_datasets/workspace/test-logs/federal-corpus-audits/owned-validation-runs/` | Original sealed native attempt payloads, immutable checkpoints, logs and release records. Preserve their original commitments. |

The later workspace parent Lake qualification supersedes older handoff notes that preparation was still unqualified. The original installation and fixture-fix receipts are now retained. This does not resolve failed artifact-cohort closeout gaps or supersede the independently closed parent-review qualification. Current source presence and guide text alone would not establish those results.

## Reading limits

Use a precise result descriptor and its closed review when assessing an experiment. Distinguish source-only implementation, prepared input, actual executed case, completed native closure and legal admission. Do not combine physical repetitions into additional distinct examples, equate synthetic custody with genuine human interpretation, or use a stale archive launcher as the next run command.

## Expanded prior consolidation

The immediately preceding consolidation had already moved 106 additional model/legal guides, making 157 maintained guides. This migration preserves their latest actual prose and moves all 157 bodies into the module, with both prior documentation paths redirected. At that consolidation cutoff, the subsequently added experimental profile guide brought the historical total to 158. The current public tree at `943e85c247cfc31cdb990518c6ae3bfedf210ceb` contains 165 maintained Markdown guides; the historical 157-guide migration and its packaging qualifications retain their original scopes. Its `CATALOG.md`, current-state/migration entry points and historical/proposal Markdown are archived and redirected; JSON, patch and compressed evidence remain immutable. The [work catalog](work_catalog.json) indexes that prior evidence and the single portable archive, including context150, gated/journal and parent-native proposal source. Those original sources remain archival evidence with unchanged pins. Six reusable experimental profiles and the parent native extension now have canonical successors; their new focused migration engineering controls are qualified, independently of the original runs. The gated training harness remains archival, and no original checkpoint campaign is replayed by the port.

The historical `scripts/ops/legal_ir/verify_autoformal_documentation.py` validates the earlier 157-guide layout and remains unchanged. It is superseded for current navigation by `python ipfs_datasets_py/logic/autoformal/work_catalog.py --check`. Do not run it as a current-module migration gate or alter its old evidence to make it pass.
