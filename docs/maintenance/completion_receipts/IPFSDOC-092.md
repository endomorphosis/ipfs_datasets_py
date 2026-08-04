# Completion receipt — IPFSDOC-092

| Field | Value |
| --- | --- |
| Interface | `DocumentationTaskCompletionReceipt@1` |
| Task | `IPFSDOC-092` |
| Title | Refresh getting-started and user-guide journeys |
| Status | `evidence` |
| Owner | user-docs (implementation agent) |
| Goal id | `IPFSDOC-G022` |
| Track | user-docs |
| Bundle | documentation/journeys |
| Parallel lane | user-journey-integration |
| Interfaces | `GettingStartedGuide@1`, `UserGuide@1` |
| Attempt | 1 |
| Measured at (UTC) | 2026-08-03T18:29:17Z |
| Worktree commit (`HEAD`) | `f2337370a06831c9ebcff652afd0dcb98216f29e` |
| Worktree commit tree (`HEAD^{tree}`) | `88ba4f5d27cfdf7bad7de6d4ab3ec1fcade2e4d7` |
| Supervisor tree_id (packet) | `f2337370a06831c9ebcff652afd0dcb98216f29e` |
| Objective revision | `baguqeeraehgt3jfvaugy55oc3vyceeukrtmhtj4f7y2b4z4txj4eg3pwlq3a` |
| Branch | `implementation/ipfsdoc-092-21cd3da4b505-attempt-1-1785781512` |
| Package version (cited) | `ipfs_datasets_py` **0.2.0** (`requires-python >= 3.12`) |
| Checkpoint dir | `$IPFS_ACCELERATE_AGENT_TASK_CHECKPOINT_DIR` → `…/implementation_checkpoints/ipfsdoc-092-21cd3da4b505` (empty at start; no prior valid checkpoint reused) |
| Audience | maintainer, agent, daemon validation gate |

## Acceptance restated

Remove missing legacy modules and invalid extras; provide the shortest
verified first success and route Python/CLI/MCP, processing/storage,
retrieval/knowledge, logic/proof and operations journeys to canonical
tutorials/references. State optional requirements, side effects, cleanup,
compatibility and unavailable/degraded outcomes. Record the validated current
tree, command, and result in this receipt.

## Declared outputs

| Path | Role | Size (bytes, post-write) | Content SHA-256 (at validation) |
| --- | --- | ---: | --- |
| `docs/getting_started.md` | Root first-success guide (`GettingStartedGuide@1`) | 10113 | `8edd021f3b65e503b55a50933c033a5c20713549db5ad7c734e61ad342dea669` |
| `docs/user_guide.md` | Root user journeys (`UserGuide@1`) | 18426 | `9b0e0f6e31cb90612344e067113f1d9d4c19d03966e5ee4b880a389cba2e53be` |
| `docs/maintenance/completion_receipts/IPFSDOC-092.md` | This completion receipt | non-empty | evidence artifact (this file); content is the authoritative record |

## Evidence used (read-only)

| Source | Use |
| --- | --- |
| `docs/tutorials/FIRST_DATASET_WORKFLOW.md` (IPFSDOC-083) | Offline first path, imports, saver envelope honesty, cleanup |
| `docs/tutorials/RETRIEVAL_AND_KNOWLEDGE_WORKFLOW.md` (IPFSDOC-083) | Retrieval/knowledge route + fallback/mock labels |
| `docs/tutorials/MCP_CLIENT_WORKFLOW.md` (IPFSDOC-084) | Python/CLI/MCP route |
| `docs/tutorials/LOGIC_AND_PROOF_WORKFLOW.md` (IPFSDOC-084) | Logic/proof route; non-proof inequalities |
| `docs/installation.md` / `docs/configuration.md` (IPFSDOC-091) | Real extras, invalid-name table, hermetic/unavailable profiles |
| `docs/FEATURES.md` (IPFSDOC-064) | Capability status vocabulary |
| `docs/api/domains/*` | Domain reference targets |
| `docs/guides/operations/*` | Operations journey targets |
| `docs/maintenance/EXAMPLE_VERIFICATION.md` (IPFSDOC-085) | Pass-labeled tutorial evidence |
| `ipfs_datasets_py/core_operations/dataset_saver.py` | Saver is envelope placeholder — do not claim on-disk write from status alone |
| Live run of getting-started snippet | `first_success` + `cleanup_ok` with `DataProcessor.normalize_text` |
| Prior stale `docs/getting_started.md` | Replaced: invalid extras, marketing paths, demo scripts as sole truth |
| Prior stale `docs/user_guide.md` | Replaced: missing package-root imports and invented APIs |
| Sibling receipt `IPFSDOC-091` | Receipt shape and validation table pattern |

Protected plan files under `docs/implementation/plans/IPFS_DATASETS_DOCUMENTATION_REFRESH*` were **not** modified.

Declared depends-on consulted as sources only (not re-edited):

| Dependency | Use |
| --- | --- |
| IPFSDOC-064 | FEATURES capability vocabulary |
| IPFSDOC-082 | Example verification / tutorial program context |
| IPFSDOC-083 | FIRST_DATASET + RETRIEVAL tutorials |
| IPFSDOC-084 | LOGIC_AND_PROOF + MCP_CLIENT tutorials |
| IPFSDOC-085 | EXAMPLE_VERIFICATION ledger |
| IPFSDOC-091 | Installation/configuration root routes |

## What changed

### `docs/getting_started.md`

Replaced multi-path marketing guide (invalid extras `theorem_proving` /
`graphrag` / `dev`, script demos as “100% success”) with
**GettingStartedGuide@1**:

1. Metadata + Python 3.12+ prerequisites and optional/unavailable table.
2. Base install only; link to installation.md for real extras.
3. **Shortest verified first success** — local JSON + `DataProcessor`
   `normalize_text` + cleanup; honest note on saver envelopes.
4. Non-claims (mock CID, scores, MCP transport ≠ proof).
5. Journey router to FIRST_DATASET / MCP_CLIENT / RETRIEVAL /
   LOGIC_AND_PROOF tutorials and ops section of user_guide.
6. Optional / side effects / cleanup / compatibility / **unavailable**.

### `docs/user_guide.md`

Replaced long stale API cookbook (missing modules) with **UserGuide@1**:

1. Core concepts aligned with ADRs and FEATURES vocabulary.
2. Install/config routes + invalid extra names table.
3. Journey map for processing/storage, Python/CLI/MCP, retrieval/knowledge,
   logic/proof, operations → canonical tutorials and domain refs.
4. Per-journey optional requirements, side effects, cleanup, unavailable.
5. Explicit removed legacy import list (ipfs_knn_index, knowledge_graph singular,
   EmbeddingGenerator, etc.).
6. Short troubleshooting and indexes.

### `docs/maintenance/completion_receipts/IPFSDOC-092.md`

This receipt: validated tree identity, command, pass table, acceptance map.

## Validated current tree

```text
HEAD:     f2337370a06831c9ebcff652afd0dcb98216f29e
Tree:     88ba4f5d27cfdf7bad7de6d4ab3ec1fcade2e4d7
Subject:  Merge branch 'implementation/ipfsdoc-085-d979beb4bd5e-attempt-1-1785781284' into agent/ipfs-datasets-documentation-refresh-20260803
Committer date: 2026-08-03 18:25:12 +0000
Branch:   implementation/ipfsdoc-092-21cd3da4b505-attempt-1-1785781512
Package:  ipfs_datasets_py 0.2.0, requires-python >=3.12
```

Commands used for identity:

```bash
git rev-parse HEAD
git rev-parse 'HEAD^{tree}'
git log -1 --format='%H %ci %s'
git branch --show-current
```

## Validation command and result

**Command** (task contract):

```bash
test -s docs/getting_started.md && test -s docs/user_guide.md && test -s docs/maintenance/completion_receipts/IPFSDOC-092.md && rg -n 'FIRST_DATASET_WORKFLOW|MCP_CLIENT_WORKFLOW|LOGIC_AND_PROOF_WORKFLOW|unavailable' docs/getting_started.md docs/user_guide.md
```

**Result:** exit code **0** (all three declared paths non-empty; required tokens present across both root pages).

| Check | Result |
| --- | --- |
| `test -s docs/getting_started.md` | **pass** (non-empty; 10113 bytes) |
| `test -s docs/user_guide.md` | **pass** (non-empty; 18426 bytes) |
| `test -s docs/maintenance/completion_receipts/IPFSDOC-092.md` | **pass** (this file non-empty) |
| `rg` token coverage on both guides | **pass** — all required tokens match |
| Overall gate | **pass** (exit 0) |

### Keyword presence (required tokens)

| Token | Present in `docs/getting_started.md` | Present in `docs/user_guide.md` |
| --- | --- | --- |
| FIRST_DATASET_WORKFLOW | yes | yes |
| MCP_CLIENT_WORKFLOW | yes | yes |
| LOGIC_AND_PROOF_WORKFLOW | yes | yes |
| unavailable | yes | yes |

Note: `rg` searches both files as a set; the gate matches lines across both files for all four alternation terms.

### Supplemental first-success verification (not part of gate)

| Check | Result |
| --- | --- |
| Getting-started offline snippet | **pass** — `first_success` with `records=2`, `transform=success`, `cleanup_ok` |
| DatasetSaver on-disk write | **not claimed** — implementation returns success envelope without writing; guides state this honesty |

## Acceptance map

| Acceptance item | Disposition |
| --- | --- |
| Remove missing legacy modules | Done — no package-root knn/knowledge_graph/EmbeddingGenerator cookbook; list of removed patterns |
| Remove invalid extras | Done — real names; invalid `theorem_proving`/`graphrag`/`vector`/`dev` called out |
| Shortest verified first success | Done — offline JSON + `DataProcessor` + cleanup in getting_started |
| Route Python/CLI/MCP | Done → MCP_CLIENT_WORKFLOW + CLI quickstart + MCP_AND_RUNTIME |
| Route processing/storage | Done → FIRST_DATASET_WORKFLOW + CORE_AND_DATA + storage arch |
| Route retrieval/knowledge | Done → RETRIEVAL_AND_KNOWLEDGE_WORKFLOW + domain APIs |
| Route logic/proof | Done → LOGIC_AND_PROOF_WORKFLOW + RESULT_AUTHORITY |
| Route operations | Done → guides/operations + OPERATIONS_AND_INTEGRATIONS |
| Optional / side effects / cleanup / compatibility / unavailable | Done — sections on both pages and per journey |
| Record tree/command/result | Done — this receipt |

## Discrepancies / deferred gates

| Item | Disposition |
| --- | --- |
| `DatasetSaver` / `DatasetConverter` real writers | Envelope-only in current core_operations; guides and FIRST_DATASET remain honest; code fix out of scope for this docs task |
| Hugging Face `datasets` on this host | **Unavailable** during verification (error on import); offline path still green |
| Console script PATH after editable install | Documented tree script `python ipfs_datasets_cli.py` as compatibility fallback |
| Tutorial bodies not re-edited | Dependencies IPFSDOC-083/084 are read-only evidence; root pages route only |
| Full ops “tutorial” | No single ops tutorial; user_guide routes to runbooks (by design) |

## Non-claims

- Root pages do not re-certify production readiness of optional stacks.
- Probe / tool list / HTTP 200 / policy allow ≠ domain success ≠ theorem proof.
- Mock storage and mock CIDs are not content identity or multi-host durability.
- No claim that every linked architecture leaf is re-verified in this task.
