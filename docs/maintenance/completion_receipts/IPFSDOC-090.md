# Completion receipt — IPFSDOC-090

| Field | Value |
| --- | --- |
| Interface | `DocumentationTaskCompletionReceipt@1` |
| Task | `IPFSDOC-090` |
| Title | Rebuild the architecture documentation hub |
| Status | `evidence` |
| Owner | documentation-governance / navigation (implementation agent) |
| Goal id | `IPFSDOC-G111` |
| Track | navigation |
| Bundle | documentation/navigation |
| Parallel lane | navigation-architecture |
| Attempt | 1 |
| Measured at (UTC) | 2026-08-03T08:21:38Z |
| Worktree commit (`HEAD`) | `2903f921968eb74af1894dd642a849a6d7dcfe4f` |
| Worktree commit tree (`HEAD^{tree}`) | `b417dc0b3f826220e3dbc4d5632583af53712ac1` |
| Supervisor tree_id (packet) | `2903f921968eb74af1894dd642a849a6d7dcfe4f` |
| Objective revision | `baguqeerawcoildemsohedwoevb62z3v4fr42svhoo4jci7o3mg2l2tuxhrsq` |
| Branch | `implementation/ipfsdoc-090-b09c858c8c93-attempt-1-1785745146` |
| Package version (cited) | `ipfs_datasets_py` **0.2.0** (`requires-python >= 3.12`) |
| Checkpoint dir | `$IPFS_ACCELERATE_AGENT_TASK_CHECKPOINT_DIR` → `…/implementation_checkpoints/ipfsdoc-090-b09c858c8c93` (empty at start; no prior valid checkpoint reused) |
| Audience | maintainer, agent, daemon validation gate |

## Acceptance restated

Replace the stale short diagram/index with audience and decision routes across
system, runtime, processing, storage, retrieval, knowledge, logic, MCP,
security/wallet, ADRs, operations and package-local details. Clearly label
current architecture versus proposed plans, implementation evidence,
compatibility and history. Record the validated current tree, command, and
result in this receipt.

## Declared outputs

| Path | Role | Size (bytes, post-write) | Content SHA-256 (at validation) |
| --- | --- | ---: | --- |
| `docs/architecture/README.md` | Architecture documentation hub | 31517 | `d20ddc2fa63d7dd465a95bf124ee2a43aeb2ae17f78288186f20b6457b0769c9` |
| `docs/maintenance/completion_receipts/IPFSDOC-090.md` | This completion receipt | non-empty | evidence artifact (this file); content is the authoritative record |

## Evidence used (read-only)

| Source | Use |
| --- | --- |
| `docs/architecture/` live tree inventory (all domain READMEs + leaves) | Route targets and lifecycle labels |
| `docs/architecture/SYSTEM_CONTEXT.md`, `DOMAIN_MAP.md`, flow/init/integration/entry pages | System model section |
| Domain indexes: `processing/`, `storage/`, `retrieval/`, `knowledge/`, `logic/`, `mcp/`, `runtime/`, `decisions/` | Domain and ADR routes |
| `docs/architecture/WALLET_TRUST_AND_PRIVACY.md` | Security/wallet route |
| `docs/architecture/*_PLAN.md`, `*.objectives.md`, `*.todo.md`, `semantic_roundtrip_canonical_compiler.md` | Proposed / plan labeling |
| Historical pages (github_actions_*, submodule_*, mcp_tools_*, project_structure.md) | Historical section |
| `docs/maintenance/INFORMATION_ARCHITECTURE.md` | Hub contract, lifecycle states, audience model |
| `docs/maintenance/PACKAGE_LOCAL_DOCUMENTATION_MAP.md` | Package-local authority routing |
| `docs/maintenance/SOURCE_AUTHORITY.md` | Authority order restated on hub |
| `docs/guides/operations/*`, `docs/guides/security/*` | Operations / security outbound links |
| Prior `docs/architecture/README.md` (stale short index + ASCII stack) | Replaced content |
| Sibling receipts `IPFSDOC-064`, `IPFSDOC-093` | Receipt shape and validation table pattern |
| `pyproject.toml` name/version | Package identity on receipt |

Protected plan files under `docs/implementation/plans/IPFS_DATASETS_DOCUMENTATION_REFRESH*` were **not** modified.

Declared depends-on (architecture leaf tasks) consulted as sources only; not re-edited:

| Dependency | Use |
| --- | --- |
| IPFSDOC-016 | ADR index + ADR-001…007 surface |
| IPFSDOC-017 | runtime/ agent supervisor + Profile G |
| IPFSDOC-022 | processing/ domain |
| IPFSDOC-026 | storage/ domain |
| IPFSDOC-033 | retrieval/ + knowledge/ domains |
| IPFSDOC-045 | logic/ domain |
| IPFSDOC-053 | mcp/ domain |
| IPFSDOC-061 | WALLET_TRUST_AND_PRIVACY |
| IPFSDOC-062 | related security/ops linkage (read via guides) |

## What changed

### `docs/architecture/README.md`

Replaced the stale short “Contents / Submodule / MCP Tools + three-layer ASCII
diagram + five design principles” index with a full **ArchitectureDocumentationHub@1**:

1. **Metadata table** — interface, task, canonical status, sources, audience.
2. **Lifecycle labels** — Current / Proposed·plan / Evidence / Compatibility / Historical / Template.
3. **Audience routes** — architect, developer, agent, operator, security reviewer, maintainer.
4. **Decision routes** — question → current page + related ADR.
5. **System model** — SYSTEM_CONTEXT, DOMAIN_MAP, END_TO_END_DATA_FLOW, DEPENDENCY_AND_INITIALIZATION, INTEGRATION_BOUNDARIES, RUNTIME_ENTRYPOINTS + simplified topology diagram labeled current-only.
6. **Domain routes** — processing, storage, retrieval, knowledge, logic, mcp, runtime, security/wallet with every current leaf linked.
7. **ADRs** — decisions index, templates, MCP reconciliation, ADR-001…007 accepted.
8. **Operations and package-local** — ops runbooks, PACKAGE_LOCAL map, MCP package ADRs, templates/contribution.
9. **Proposed plans** — all `*_PLAN.md` / boards / SRT design under this tree labeled **not** current architecture.
10. **Compatibility** — processor strangler, MCP shells, lazy extras, submodules, CLI packaging drift.
11. **Historical** — github_actions_*, submodule_*, project_structure, legacy mcp_tools_* catalogs.
12. **Implementation evidence** — maintenance baselines and receipt home.
13. **Full inventory** — every Markdown path under `docs/architecture/` classified.
14. **Validation commands** and explicit non-claims.

### `docs/maintenance/completion_receipts/IPFSDOC-090.md`

This receipt: validated tree identity, command, pass table, acceptance map.

## Validated current tree

```text
HEAD:     2903f921968eb74af1894dd642a849a6d7dcfe4f
Tree:     b417dc0b3f826220e3dbc4d5632583af53712ac1
Subject:  Merge branch 'implementation/ipfsdoc-070-580400b4a5e6-attempt-1-1785744886' into agent/ipfs-datasets-documentation-refresh-20260803
Committer date: 2026-08-03 08:19:05 +0000
Branch:   implementation/ipfsdoc-090-b09c858c8c93-attempt-1-1785745146
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
test -s docs/architecture/README.md && test -s docs/maintenance/completion_receipts/IPFSDOC-090.md && rg -n 'SYSTEM_CONTEXT|DOMAIN_MAP|processing|storage|retrieval|knowledge|logic|mcp|decisions|runtime' docs/architecture/README.md
```

**Result:** exit code **0** (both declared paths non-empty; required tokens present in the hub).

| Check | Result |
| --- | --- |
| `test -s docs/architecture/README.md` | **pass** (non-empty; 31517 bytes) |
| `test -s docs/maintenance/completion_receipts/IPFSDOC-090.md` | **pass** (this file non-empty) |
| `rg` token coverage on hub | **pass** — matching lines cover all required tokens |
| Overall gate | **pass** (exit 0) |

### Keyword presence (required tokens)

| Token | Present in `docs/architecture/README.md` |
| --- | --- |
| SYSTEM_CONTEXT | yes |
| DOMAIN_MAP | yes |
| processing | yes |
| storage | yes |
| retrieval | yes |
| knowledge | yes |
| logic | yes |
| mcp | yes |
| decisions | yes |
| runtime | yes |

### Supplemental spot-check (not the exclusive gate; documents leaf presence)

```bash
test -s docs/architecture/SYSTEM_CONTEXT.md \
  && test -s docs/architecture/DOMAIN_MAP.md \
  && test -s docs/architecture/processing/README.md \
  && test -s docs/architecture/storage/README.md \
  && test -s docs/architecture/retrieval/README.md \
  && test -s docs/architecture/knowledge/README.md \
  && test -s docs/architecture/logic/README.md \
  && test -s docs/architecture/mcp/README.md \
  && test -s docs/architecture/decisions/README.md \
  && test -s docs/architecture/runtime/AGENT_SUPERVISOR_AND_TASKBOARDS.md \
  && test -s docs/architecture/WALLET_TRUST_AND_PRIVACY.md
```

Expected: exit 0 when dependency leaves from depends-on tasks remain in the tree.

## Acceptance criteria map

| Criterion | Evidence |
| --- | --- |
| Audience routes | §3 Audience routes (architect, developer, agent, operator, security, maintainer) |
| Decision routes | §4 Decision routes table |
| System model | §5 SYSTEM_CONTEXT, DOMAIN_MAP, flows, init, integration, entrypoints |
| Runtime | §6.7 runtime/ + RUNTIME_ENTRYPOINTS |
| Processing / storage / retrieval / knowledge / logic / mcp | §6.1–§6.6 full leaf tables |
| Security / wallet | §6.8 WALLET_TRUST_AND_PRIVACY + security guides |
| ADRs | §7 decisions/ index and ADR-001…007 |
| Operations | §8.1 ops runbooks |
| Package-local details | §8.2 PACKAGE_LOCAL map + MCP package ADRs |
| Current vs proposed plans | §2 labels; §9 plans; §13 inventory |
| Implementation evidence | §12 maintenance baselines and receipts |
| Compatibility | §10 strangler, MCP shells, lazy extras, submodules |
| History | §11 historical pages under this tree |
| Validated tree, command, result | This receipt sections above |

## Explicit non-claims

- This receipt is **evidence** for the measured commit/date; it is not evergreen product architecture.
- Hub navigation summaries do not outrank tests, implementation, or accepted ADRs when they disagree.
- No production code, packaging, or protected plan files were changed.
- Daemon commit/merge remains subject to the supervisor validation gate.
- Checkpoint directory was empty; no resumable coordinate was reused.

## Re-run recipe

From repository root of this worktree:

```bash
test -s docs/architecture/README.md && test -s docs/maintenance/completion_receipts/IPFSDOC-090.md && rg -n 'SYSTEM_CONTEXT|DOMAIN_MAP|processing|storage|retrieval|knowledge|logic|mcp|decisions|runtime' docs/architecture/README.md
```
