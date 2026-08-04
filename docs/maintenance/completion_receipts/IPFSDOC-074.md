# Completion receipt — IPFSDOC-074

| Field | Value |
| --- | --- |
| Interface | `DocumentationTaskCompletionReceipt@1` |
| Task | `IPFSDOC-074` |
| Title | Refresh the root developer guide |
| Status | `evidence` |
| Owner | developer-docs (implementation agent) |
| Goal id | `IPFSDOC-G080` |
| Track | developer-docs |
| Bundle | documentation/developers |
| Parallel lane | developer-integration |
| Attempt | 1 |
| Measured at (UTC) | 2026-08-03T08:31:58Z |
| Worktree commit (`HEAD`) | `17f790ba0ee33e303fd58af81be6c4d4edf7c51e` |
| Worktree commit tree (`HEAD^{tree}`) | `0b2c68d61f021108f10e139920c69ad857055177` |
| Supervisor tree_id (packet) | `17f790ba0ee33e303fd58af81be6c4d4edf7c51e` |
| Objective revision | `baguqeera7k7guenyfkrbwa67wedgcufgn24cemgwebvia6o2kz5ymiimn3na` |
| Branch | `implementation/ipfsdoc-074-fabe6a11b82a-attempt-1-1785745814` |
| Package version (cited) | `ipfs_datasets_py` **0.2.0** (`requires-python >= 3.12`) |
| Measurement Python | `Python 3.12.3` |
| Checkpoint dir | `$IPFS_ACCELERATE_AGENT_TASK_CHECKPOINT_DIR` → `…/implementation_checkpoints/ipfsdoc-074-fabe6a11b82a` (empty at start; no prior valid checkpoint reused) |
| Audience | maintainer, agent, daemon validation gate |

## Acceptance restated

Replace removed requirements/scripts/modules and stale setup instructions with a
concise current contributor entry routing to repository, architecture, recipe,
testing, agent, contributing, security, and documentation guides. Validate all
introduced paths and commands; do not duplicate detailed leaf content. Record
the validated current tree, command, and result in this receipt.

## Declared outputs

| Path | Role | Size (bytes, post-write) | Content SHA-256 (at validation) |
| --- | --- | ---: | --- |
| `docs/developer_guide.md` | Canonical contributor landing / routing entry | 11301 | `8fd6bcaebd7843be5aab55080f650b315644642b96d2db069accd8a6c95657d8` |
| `docs/maintenance/completion_receipts/IPFSDOC-074.md` | This completion receipt | non-empty | evidence artifact (this file); content is the authoritative record |

## Evidence used (read-only)

| Source | Use |
| --- | --- |
| Prior `docs/developer_guide.md` (stale feature list + removed scripts) | Content replaced |
| `docs/maintenance/DRIFT_AND_CLAIM_MATRIX.md` CLAIM-import-014/015, CLAIM-cmd-002…006/009 | Stale command/import inventory to retire |
| `pyproject.toml` (`requires-python`, version, extras including `test`) | Prerequisites and install commands |
| `docs/developer_guides/REPOSITORY_MAP.md` (IPFSDOC-070) | Repository route |
| `docs/developer_guides/EXTENSION_RECIPES.md` (IPFSDOC-071) | Recipe route |
| `docs/developer_guides/TESTING_AND_EVIDENCE.md` (IPFSDOC-072) | Testing route |
| `docs/developer_guides/FOR_AGENTS.md` (+ TROUBLESHOOTING, HANDOFF_CHECKLIST) (IPFSDOC-073) | Agent route |
| `docs/developer_guides/DOCUMENTATION_CONTRIBUTING.md` | Documentation contribution route |
| `docs/architecture/README.md` (IPFSDOC-090) | Architecture hub route |
| `docs/architecture/RUNTIME_ENTRYPOINTS.md` | MCP/module entry confirmation |
| `docs/guides/security/README.md`, `THREAT_MODEL.md`, `SECRETS_AND_CREDENTIALS.md` | Security routes |
| `docs/architecture/WALLET_TRUST_AND_PRIVACY.md` | Wallet/trust security route |
| Root `CONTRIBUTING.md` | Contributing process route |
| Sibling receipts `IPFSDOC-090`, `IPFSDOC-093` | Receipt shape |
| Live filesystem checks for removed root scripts | Confirmed gone: `comprehensive_mcp_test.py`, `systematic_validation.py`, `start_fastapi.py`, root `install.py` |

Protected plan files under `docs/implementation/plans/IPFS_DATASETS_DOCUMENTATION_REFRESH*` were **not** modified.

Declared depends-on consulted as sources only (not re-edited):

| Dependency | Artifact |
| --- | --- |
| IPFSDOC-070 | `docs/developer_guides/REPOSITORY_MAP.md` |
| IPFSDOC-071 | `docs/developer_guides/EXTENSION_RECIPES.md` |
| IPFSDOC-072 | `docs/developer_guides/TESTING_AND_EVIDENCE.md` |
| IPFSDOC-073 | `docs/developer_guides/FOR_AGENTS.md` (+ companions) |

## What changed

### `docs/developer_guide.md`

Replaced the stale “project overview + removed root scripts + feature marketing
+ FastAPI route map + partial CLAUDE remnant” page with **DeveloperGuide@1**:

1. **Metadata table** — interface, task, canonical status, sources, audience.
2. **Purpose / non-purpose** — landing and routing only; no leaf duplication.
3. **Prerequisites** — **Python 3.12+**, package identity 0.2.0, optional stacks.
4. **Minimal setup** — `pip install -e ".[test]"`, import smoke, nearest pytest
   pointer, MCP module entry; explicit table of **removed** root commands.
5. **Routing table** — repository (`REPOSITORY_MAP`), architecture hub, recipes
   (`EXTENSION_RECIPES`), testing (`TESTING_AND_EVIDENCE`), agents (`FOR_AGENTS`),
   contributing, security, documentation contributing, plus short exploration order.
6. **Ground rules summary** — pointers to ADRs and leaves only.
7. **Explicit non-claims** and maintainer validation recipe.

### `docs/maintenance/completion_receipts/IPFSDOC-074.md`

This receipt: validated tree identity, path/command checks, acceptance map.

## Validated current tree

```text
HEAD:     17f790ba0ee33e303fd58af81be6c4d4edf7c51e
Tree:     0b2c68d61f021108f10e139920c69ad857055177
Subject:  Merge branch 'implementation/ipfsdoc-073-590e67a48a31-attempt-1-1785745505' into agent/ipfs-datasets-documentation-refresh-20260803
Committer date: 2026-08-03 08:30:13 +0000
Branch:   implementation/ipfsdoc-074-fabe6a11b82a-attempt-1-1785745814
Package:  ipfs_datasets_py 0.2.0, requires-python >=3.12
Python:   Python 3.12.3
```

Commands used for identity:

```bash
date -u +%Y-%m-%dT%H:%M:%SZ
git rev-parse HEAD
git rev-parse 'HEAD^{tree}'
git log -1 --format='%H %ci %s'
git branch --show-current
python3 --version
```

## Introduced path validation

All link targets introduced or required by the refreshed guide were checked
`test -s` (non-empty) at measurement time. Result: **all pass**.

| Path | Result |
| --- | --- |
| `docs/developer_guides/REPOSITORY_MAP.md` | pass |
| `docs/developer_guides/EXTENSION_RECIPES.md` | pass |
| `docs/developer_guides/TESTING_AND_EVIDENCE.md` | pass |
| `docs/developer_guides/FOR_AGENTS.md` | pass |
| `docs/developer_guides/TROUBLESHOOTING.md` | pass |
| `docs/developer_guides/HANDOFF_CHECKLIST.md` | pass |
| `docs/developer_guides/DOCUMENTATION_CONTRIBUTING.md` | pass |
| `docs/developer_guides/CREATING_TOOLS.md` | pass |
| `docs/architecture/README.md` | pass |
| `docs/architecture/DOMAIN_MAP.md` | pass |
| `docs/architecture/INTEGRATION_BOUNDARIES.md` | pass |
| `docs/architecture/RUNTIME_ENTRYPOINTS.md` | pass |
| `docs/architecture/DEPENDENCY_AND_INITIALIZATION.md` | pass |
| `docs/architecture/WALLET_TRUST_AND_PRIVACY.md` | pass |
| `docs/architecture/decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md` | pass |
| `docs/architecture/decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md` | pass |
| `docs/maintenance/SOURCE_AUTHORITY.md` | pass |
| `docs/maintenance/INFORMATION_ARCHITECTURE.md` | pass |
| `docs/maintenance/VALIDATION_RUNBOOK.md` | pass |
| `docs/guides/security/README.md` | pass |
| `docs/guides/security/THREAT_MODEL.md` | pass |
| `docs/guides/security/SECRETS_AND_CREDENTIALS.md` | pass |
| `docs/installation.md` | pass |
| `docs/GLOSSARY.md` | pass |
| `CONTRIBUTING.md` | pass |
| `pyproject.toml` | pass |
| `scripts/setup/install.py` | pass |
| `ipfs_datasets_py/mcp_server/__main__.py` | pass |

## Introduced command validation

| Command / claim | Result |
| --- | --- |
| `python3 --version` → Python 3.12.3 | **pass** |
| `requires-python = ">=3.12"` and `test` extra in `pyproject.toml` | **pass** |
| `python -c "import ipfs_datasets_py; …"` → version `0.2.0` | **pass** (package importable in this worktree) |
| `python -m ipfs_datasets_py.mcp_server --help` exposes `--stdio` / `--http` | **pass** |
| Stale root scripts absent: `comprehensive_mcp_test.py`, `systematic_validation.py`, `start_fastapi.py`, root `install.py` | **pass** (confirmed missing; not recommended in new guide) |
| Full `pip install -e ".[test]"` re-execution | **not re-run** as a long install gate; packaging surface verified from `pyproject.toml` + import smoke. Documented as the preferred install pattern. |
| Full `pytest` suite | **not claimed** — deferred to proportional selection in `TESTING_AND_EVIDENCE.md` |

## Validation command and result

**Command** (task contract):

```bash
test -s docs/developer_guide.md && test -s docs/maintenance/completion_receipts/IPFSDOC-074.md && rg -n 'Python 3.12|REPOSITORY_MAP|EXTENSION_RECIPES|TESTING_AND_EVIDENCE|FOR_AGENTS' docs/developer_guide.md
```

**Result:** exit code **0** (both declared paths non-empty; required tokens present).

| Check | Result |
| --- | --- |
| `test -s docs/developer_guide.md` | **pass** (non-empty; 11301 bytes) |
| `test -s docs/maintenance/completion_receipts/IPFSDOC-074.md` | **pass** (this file non-empty) |
| `rg` token coverage on developer guide | **pass** — matching lines cover all required tokens |
| Overall gate | **pass** (exit 0) |

### Keyword presence (required tokens)

| Token | Present in `docs/developer_guide.md` |
| --- | --- |
| Python 3.12 | yes |
| REPOSITORY_MAP | yes |
| EXTENSION_RECIPES | yes |
| TESTING_AND_EVIDENCE | yes |
| FOR_AGENTS | yes |

## Acceptance criteria map

| Criterion | Evidence |
| --- | --- |
| Replace removed requirements/scripts/modules and stale setup | Stale command table; no root `comprehensive_mcp_test` / `start_fastapi` / root `install.py`; no guaranteed `ipfs_kit` in-tree import |
| Concise current contributor entry | Sections 1–3: purpose, prerequisites, minimal setup only |
| Route to repository, architecture, recipe, testing, agent, contributing, security, documentation | Routing table §4 with all eight destinations |
| Validate all introduced paths and commands | Path table + command table above |
| Do not duplicate detailed leaf content | Explicit non-purpose + non-claims; ground rules are one-liners with links |
| Record validated current tree, command, and result | This receipt |

## Explicit non-claims

- This receipt is **evidence** for the measured commit/date; it is not evergreen product architecture.
- The developer guide does not outrank tests, packaging, ADRs, or leaf guides.
- No production code, packaging, or protected plan files were changed.
- Daemon commit/merge remains subject to the supervisor validation gate.
- Full editable reinstall and full-suite pytest were not execution gates for this documentation task.

## Re-run recipe

From repository root of this worktree:

```bash
test -s docs/developer_guide.md && test -s docs/maintenance/completion_receipts/IPFSDOC-074.md && rg -n 'Python 3.12|REPOSITORY_MAP|EXTENSION_RECIPES|TESTING_AND_EVIDENCE|FOR_AGENTS' docs/developer_guide.md
```

Expected: exit status `0`, non-empty files, multiple `rg` hit lines including every required keyword.
