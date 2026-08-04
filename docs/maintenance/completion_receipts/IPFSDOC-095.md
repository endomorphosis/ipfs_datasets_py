# Completion receipt — IPFSDOC-095

| Field | Value |
| --- | --- |
| Interface | `DocumentationTaskCompletionReceipt@1` |
| Task | `IPFSDOC-095` |
| Title | Rebuild root documentation navigation |
| Status | `evidence` |
| Owner | documentation-governance / navigation (implementation agent) |
| Goal id | `IPFSDOC-G111` |
| Track | navigation |
| Bundle | documentation/navigation |
| Parallel lane | navigation-root |
| Interfaces | `DocumentationNavigationRoot@1`, `DocumentationDirectoryOverview@1`, `DocumentationDeepIndex@1` |
| Attempt | 1 |
| Measured at (UTC) | 2026-08-03T18:37:37Z |
| Worktree commit (`HEAD`) | `e06063ce27c0471a13e6656a3c7a14a450077e43` |
| Worktree commit tree (`HEAD^{tree}`) | `6e35d21c0c676f43ada6d9512d000b40ecb7683b` |
| Supervisor tree_id (packet) | `e06063ce27c0471a13e6656a3c7a14a450077e43` |
| Branch | `implementation/ipfsdoc-095-6b6b9de1865b-attempt-1-1785782041` |
| Package version (cited) | `ipfs_datasets_py` **0.2.0** (`requires-python >= 3.12`) |
| Checkpoint dir | `$IPFS_ACCELERATE_AGENT_TASK_CHECKPOINT_DIR` → `…/implementation_checkpoints/ipfsdoc-095-6b6b9de1865b` (empty at start; no prior valid checkpoint reused) |
| Audience | maintainer, agent, daemon validation gate |

## Acceptance restated

Choose one canonical landing flow and make the three existing entry files
consistent pointers rather than competing indexes. Route by audience and task
to every canonical guide/domain, remove stale February/latest/count/completion
claims, distinguish maintained/generated/historical material, and avoid
orphaning deep component docs. Record the validated current tree, command, and
result in this receipt.

## Declared outputs

| Path | Role | Size (bytes, post-write) | Content SHA-256 (at validation) |
| --- | --- | ---: | --- |
| `docs/index.md` | Canonical product landing (`DocumentationNavigationRoot@1`) | 16455 | `f3dab4d9b0cb9dafa8d1711ce79b83651b5cad717c3596dbc3c707c1e86cf7a1` |
| `docs/README.md` | Docs directory overview (`DocumentationDirectoryOverview@1`) | 8312 | `da1faed1b5ae24bb7f1da4632416339f89876622e0a971bbd94d2a55e1c1a4ee` |
| `docs/DOCUMENTATION_INDEX.md` | Deep maintained catalog (`DocumentationDeepIndex@1`) | 18749 | `f81d65add621ccf118bcc1fed4bd01168a1a2f4ae063b75c64406d8a248b186b` |
| `docs/maintenance/completion_receipts/IPFSDOC-095.md` | This completion receipt | non-empty | evidence artifact (this file); content is the authoritative record |

## Evidence used (read-only)

| Source | Use |
| --- | --- |
| Live `docs/` top-level inventory (dirs + root guides) | Landing targets and lifecycle placement |
| `docs/architecture/README.md` (IPFSDOC-090) | Architecture hub contract and domain routes |
| `docs/api/README.md` + `docs/api/domains/*` (IPFSDOC-082) | API domain routes |
| `docs/getting_started.md`, `user_guide.md` (IPFSDOC-092) | Getting Started / user journeys |
| `docs/installation.md`, `configuration.md` (IPFSDOC-091) | Install/config routes |
| `docs/developer_guide.md` + `docs/developer_guides/*` (IPFSDOC-074) | Developers routes |
| `docs/guides/operations/*`, `docs/guides/security/*` | Operations and Security routes |
| `docs/FEATURES.md`, `docs/CHANGELOG.md` (IPFSDOC-064) | Capability matrix and changelog policy |
| `docs/GLOSSARY.md` (IPFSDOC-093) | Vocabulary route |
| `docs/maintenance/INFORMATION_ARCHITECTURE.md` | Audience model, target tree, lifecycle states |
| `docs/maintenance/LEGACY_DISPOSITION.md` | Index triple disposition; product entry spine |
| `docs/maintenance/PACKAGE_LOCAL_DOCUMENTATION_MAP.md` | Package-local component docs (anti-orphan) |
| `docs/maintenance/SOURCE_AUTHORITY.md` | Authority order restated on landing |
| Prior `docs/index.md` | Replaced: phase checkmarks, competing master index, undated architecture essay |
| Prior `docs/README.md` | Replaced: February 2026 “Latest Features,” guide counts, 85% clutter claim |
| Prior `docs/DOCUMENTATION_INDEX.md` | Replaced: incomplete partial list without lifecycle labels |
| Sibling receipts IPFSDOC-064, 074, 090–093 | Receipt shape and dependency evidence |
| `pyproject.toml` name/version/requires-python | Package identity on receipt |

Protected plan files under `docs/implementation/plans/IPFS_DATASETS_DOCUMENTATION_REFRESH*` were **not** modified.

Declared depends-on consulted as sources only (not re-edited):

| Dependency | Use |
| --- | --- |
| IPFSDOC-064 | FEATURES / CHANGELOG capability honesty |
| IPFSDOC-074 | Developer guide landing |
| IPFSDOC-082 | API index + domain pages |
| IPFSDOC-090 | Architecture hub |
| IPFSDOC-091 | Installation / configuration |
| IPFSDOC-092 | Getting started / user guide |
| IPFSDOC-093 | Glossary |
| IPFSDOC-094 | (declared in packet; receipt not present in this worktree — used live tree targets instead) |

## What changed

### Canonical landing flow (one authority)

```text
docs/index.md                 → product entry (audience + task)
docs/DOCUMENTATION_INDEX.md   → deep domain catalog
docs/README.md                → directory roles (maintained / generated / historical)
```

The three files are **consistent pointers**, not three competing full indexes.
Superseded duplicates (`DOCUMENTATION_INDEX_COMPLETE.md`,
`root_DOCUMENTATION_INDEX.md`) are named as non-authoritative.

### `docs/index.md`

Rebuilt as **DocumentationNavigationRoot@1**:

1. Metadata + authority order + lifecycle labels.
2. **Getting Started** shortest path and four canonical tutorials.
3. **By audience** table (user, Developers, architect, operator, Security, agent, maintainer).
4. **Architecture** domain routes to the IPFSDOC-090 hub and leaves.
5. **Developers**, **API**, **Operations**, **Security** sections with current hubs.
6. Task routes for install, data, RAG, PDF, MCP, IPLD, logic, deploy, extend.
7. **Deep component docs** table linking package READMEs (vector_stores, search,
   knowledge_graphs, logic, mcp_server, optimizers, audit, utils).
8. **Historical / generated / plans / evidence** placement.
9. Explicit non-claims (no February/latest/count/completion marketing).

### `docs/README.md`

Rebuilt as **DocumentationDirectoryOverview@1**:

1. States index.md as the only product landing.
2. Landing-flow diagram and role table for the entry triple.
3. **Getting Started**, **Architecture**, **Developers**, **API**, **Operations**,
   **Security** short routes.
4. Full directory map by lifecycle (maintained / generated / historical / plan / evidence).
5. Package-local component links; MkDocs note; maintenance rules.

### `docs/DOCUMENTATION_INDEX.md`

Rebuilt as **DocumentationDeepIndex@1**:

1. Entry triple restated.
2. Catalog sections: Getting Started, Architecture, Developers, API, Operations,
   Security, domain clusters (MCP, processing, IPLD, KG, logic, legal/web).
3. Lifecycle column on major rows.
4. Package-local deep components table (anti-orphan).
5. Historical, generated, plans, evidence, maintenance sections.
6. Update rules + validation command.

### Removed / avoided

- February 2026 “Latest Features” blocks and reorganization percentage claims.
- Undated tool counts, coverage percentages, phase ✅ completion checklists on entry pages.
- Competing “master documentation index” pointers as product authority.

## Validated current tree

```text
HEAD: e06063ce27c0471a13e6656a3c7a14a450077e43
HEAD^{tree}: 6e35d21c0c676f43ada6d9512d000b40ecb7683b
Branch: implementation/ipfsdoc-095-6b6b9de1865b-attempt-1-1785782041
Package: ipfs_datasets_py 0.2.0 (requires-python >= 3.12)
Measured at (UTC): 2026-08-03T18:37:37Z

docs/ top-level directories (inventory):
  analysis api architecture archive archived_stubs auto_generated_stubs
  benchmarks dashboards deployment developer_guides examples guides
  implementation knowledge_graphs logic maintenance migration_docs
  migration_guides modules optimizers performance_snapshots profiling
  quickstart rag_optimizer reorganization reports schemas
  security_verification tdfol tutorials user_guides

Approximate Markdown counts (this worktree, find):
  docs/**/*.md: 1569
  docs/architecture/**/*.md: 72
  docs/api/**/*.md: 9
  ipfs_datasets_py/**/*.md: 387

Entry triple (post-write):
  docs/index.md                 16455 bytes  sha256:f3dab4d9b0cb9dafa8d1711ce79b83651b5cad717c3596dbc3c707c1e86cf7a1
  docs/README.md                 8312 bytes  sha256:da1faed1b5ae24bb7f1da4632416339f89876622e0a971bbd94d2a55e1c1a4ee
  docs/DOCUMENTATION_INDEX.md   18749 bytes  sha256:f81d65add621ccf118bcc1fed4bd01168a1a2f4ae063b75c64406d8a248b186b
```

## Validation command and result

```bash
test -s docs/index.md && test -s docs/README.md && test -s docs/DOCUMENTATION_INDEX.md && \
  test -s docs/maintenance/completion_receipts/IPFSDOC-095.md && \
  rg -n 'Getting Started|Architecture|Developers|API|Operations|Security|Historical' \
  docs/index.md docs/README.md docs/DOCUMENTATION_INDEX.md
```

| Check | Result |
| --- | --- |
| `test -s docs/index.md` | **pass** |
| `test -s docs/README.md` | **pass** |
| `test -s docs/DOCUMENTATION_INDEX.md` | **pass** |
| `test -s docs/maintenance/completion_receipts/IPFSDOC-095.md` | **pass** |
| `rg` keyword set on all three entry files | **pass** (matches in each file for Getting Started, Architecture, Developers, API, Operations, Security, Historical) |
| Stale February/latest/count/✅ markers on entry triple | **pass** (none found) |

## Acceptance map

| Criterion | How met |
| --- | --- |
| One canonical landing flow | `index.md` is product entry; README and deep index point to it |
| Three files consistent pointers | Shared flow + role table in all three; no competing home narratives |
| Audience + task routes | index §3–§9; deep index domain sections |
| Every canonical guide/domain | Architecture domains, API domains, ops, security, tutorials, package READMEs |
| Remove stale February/latest/count/completion | Prior content replaced; scan clean |
| Distinguish maintained/generated/historical | Explicit tables in all three files |
| Avoid orphaning deep component docs | Package README tables + PACKAGE_LOCAL map links |
| Record tree, command, result | This receipt §§ Validated current tree / Validation |

## Explicit non-claims

- This task did **not** move, archive, or delete legacy pages (disposition map only).
- This task did **not** edit protected plan files or non-declared outputs.
- Markdown counts above are worktree inventory facts, not product KPIs.
- MkDocs nav coverage is unchanged; full routing is via the entry triple.

## Checkpoint

| Item | Value |
| --- | --- |
| Checkpoint directory | `$IPFS_ACCELERATE_AGENT_TASK_CHECKPOINT_DIR` (`ipfsdoc-095-6b6b9de1865b`) |
| Prior checkpoint | none (directory empty at start) |
| Written | `checkpoint.env` with task id, HEAD, UTC after validation evidence collection |
