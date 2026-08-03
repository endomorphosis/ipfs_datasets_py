# Completion receipt — IPFSDOC-091

| Field | Value |
| --- | --- |
| Interface | `DocumentationTaskCompletionReceipt@1` |
| Task | `IPFSDOC-091` |
| Title | Refresh root installation and configuration pages |
| Status | `evidence` |
| Owner | user-docs (implementation agent) |
| Goal id | `IPFSDOC-G021` |
| Track | user-docs |
| Bundle | documentation/install-config |
| Parallel lane | user-install-integration |
| Interfaces | `InstallationGuide@1`, `ConfigurationGuide@1` |
| Attempt | 1 |
| Measured at (UTC) | 2026-08-03T18:15:34Z |
| Worktree commit (`HEAD`) | `3d90d03af4acd71c29d337c0fffcf3864639f7f2` |
| Worktree commit tree (`HEAD^{tree}`) | `79db6bad416d7d851aff9c3e7c297625ca379d4d` |
| Supervisor tree_id (packet) | `3d90d03af4acd71c29d337c0fffcf3864639f7f2` |
| Objective revision | `baguqeerazrdt3hotny7sgnnurffntds53vy6jntcs6nck5wth6ncp4gb47qa` |
| Branch | `implementation/ipfsdoc-091-cc473d9dd36e-attempt-1-1785780829` |
| Package version (cited) | `ipfs_datasets_py` **0.2.0** (`requires-python >= 3.12`) |
| Checkpoint dir | `$IPFS_ACCELERATE_AGENT_TASK_CHECKPOINT_DIR` → `…/implementation_checkpoints/ipfsdoc-091-cc473d9dd36e` (empty at start; no prior valid checkpoint reused) |
| Audience | maintainer, agent, daemon validation gate |

## Acceptance restated

Replace Python 3.7/3.9, nonexistent extras, placeholder organizations,
obsolete CUDA advice, and incomplete environment coverage with concise
verified base/capability installation and configuration precedence routes.
Preserve platform/security/offline caveats and link to the detailed
references. Record the validated current tree, command, and result in this
receipt.

## Declared outputs

| Path | Role | Size (bytes, post-write) | Content SHA-256 (at validation) |
| --- | --- | ---: | --- |
| `docs/installation.md` | Root installation guide (`InstallationGuide@1`) | 8592 | `a036c4613d064c893b28b197a7cd81b43aa6092ad6fbc9f432559692ecc9496a` |
| `docs/configuration.md` | Root configuration guide (`ConfigurationGuide@1`) | 9419 | `fd241e129cff4eddfa7727215075b16601c176669b27a64998ce33a907c3b50c` |
| `docs/maintenance/completion_receipts/IPFSDOC-091.md` | This completion receipt | non-empty | evidence artifact (this file); content is the authoritative record |

## Evidence used (read-only)

| Source | Use |
| --- | --- |
| `pyproject.toml` (`name`, `version`, `requires-python >=3.12`) | Python baseline and package identity |
| `docs/guides/installation/CAPABILITY_INSTALLATION.md` (IPFSDOC-063) | Verified extras, natives, offline/unavailable, install recipes |
| `docs/guides/installation/CONFIGURATION_REFERENCE.md` (IPFSDOC-063) | Precedence model, env catalog, security consequences, profiles |
| Prior stale `docs/installation.md` | Replaced: Python 3.7/3.9, `[vector]`/`[graphrag]`/`[webarchive]`, `your-organization`/`yourorga`, torch 1.10 CUDA pins |
| Prior stale `docs/configuration.md` | Replaced: incomplete env list, unverified YAML sketches as sole authority |
| `docs/quickstart/PLATFORM_INSTALL.md` | Platform extras pointer (not rewritten) |
| `docs/guides/security/SECRETS_AND_CREDENTIALS.md` | Link target for secrets hygiene |
| Sibling receipts `IPFSDOC-064`, `IPFSDOC-090` | Receipt shape and validation table pattern |
| Declared dependency IPFSDOC-063 leaf guides | Canonical detailed references (not re-edited) |

Protected plan files under `docs/implementation/plans/IPFS_DATASETS_DOCUMENTATION_REFRESH*` were **not** modified.

## What changed

### `docs/installation.md`

Replaced the obsolete long install page with a concise **InstallationGuide@1** root route:

1. **Metadata** — interface, task, sources, links to CAPABILITY_INSTALLATION / CONFIGURATION_REFERENCE.
2. **Requirements** — **Python 3.12+** only; platform notes; no obsolete CUDA pin recipes.
3. **Base install** — venv + `pip install` / editable from `endomorphosis/ipfs_datasets_py`; VCS-deps skip; requirements files pointer.
4. **Optional capabilities** — real extras (`vectors`, `knowledge_graphs`, `web_archive`, …); explicit invalid-name table; native tools summary.
5. **Profiles** — base / capability / hermetic / offline / **unavailable** degradation.
6. **Console scripts**, Docker caveat (no `yourorga` images), quick validation, short troubleshooting.
7. **Links** to detailed CAPABILITY_INSTALLATION and CONFIGURATION_REFERENCE (not full duplication).

### `docs/configuration.md`

Replaced the thin incomplete config page with a concise **ConfigurationGuide@1** root route:

1. **Precedence** — CLI > env > files > defaults; CLI/gateway table; auto-install/hermetic; IPFS backend; prover resolution.
2. **Sources** — `.env`, CLI JSON, YAML examples as templates, `initialize()`.
3. **Profiles** — base, capability-enabled, offline, unavailable vs fail-closed trust.
4. **High-signal env** table + security caveats (auto-install, provers, secrets, binds).
5. **Operator hygiene** and deep-dive links including CONFIGURATION_REFERENCE and CAPABILITY_INSTALLATION.

### `docs/maintenance/completion_receipts/IPFSDOC-091.md`

This receipt: validated tree identity, command, pass table, acceptance map.

## Validated current tree

```text
HEAD:     3d90d03af4acd71c29d337c0fffcf3864639f7f2
Tree:     79db6bad416d7d851aff9c3e7c297625ca379d4d
Subject:  Merge branch 'implementation/ipfsdoc-083-e80fdd41fa32-attempt-3-1785746753' into agent/ipfs-datasets-documentation-refresh-20260803
Committer date: 2026-08-03 08:48:16 +0000
Branch:   implementation/ipfsdoc-091-cc473d9dd36e-attempt-1-1785780829
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
test -s docs/installation.md && test -s docs/configuration.md && test -s docs/maintenance/completion_receipts/IPFSDOC-091.md && rg -n 'Python 3.12|CAPABILITY_INSTALLATION|CONFIGURATION_REFERENCE|optional|unavailable' docs/installation.md docs/configuration.md
```

**Result:** exit code **0** (all three declared paths non-empty; required tokens present in both root pages).

| Check | Result |
| --- | --- |
| `test -s docs/installation.md` | **pass** (non-empty; 8592 bytes) |
| `test -s docs/configuration.md` | **pass** (non-empty; 9419 bytes) |
| `test -s docs/maintenance/completion_receipts/IPFSDOC-091.md` | **pass** (this file non-empty) |
| `rg` token coverage on both guides | **pass** — all required tokens match |
| Overall gate | **pass** (exit 0) |

### Keyword presence (required tokens)

| Token | Present in `docs/installation.md` | Present in `docs/configuration.md` |
| --- | --- | --- |
| Python 3.12 | yes (requirements: Python 3.12+) | (required on either; install page carries baseline) |
| CAPABILITY_INSTALLATION | yes | yes |
| CONFIGURATION_REFERENCE | yes | yes |
| optional | yes | yes |
| unavailable | yes | yes |

Note: `rg` searches both files as a set; tokens need not each appear in every file as long as the combined pattern matches—the gate matches multiple lines across both files for all five alternation terms.

## Acceptance map

| Acceptance item | Disposition |
| --- | --- |
| Replace Python 3.7/3.9 | Done — Python 3.12+ only; 3.7–3.11 marked unsupported |
| Replace nonexistent extras | Done — real names; invalid `vector`/`graphrag`/`webarchive` table |
| Replace placeholder organizations | Done — `endomorphosis/ipfs_datasets_py`; no `yourorga` install recipes |
| Replace obsolete CUDA advice | Done — no torch 1.10/cu113 pins; point to current vendor builds / `ml` extra |
| Incomplete environment coverage | Done — base/capability/offline/unavailable + hermetic profiles |
| Preserve platform/security/offline caveats | Done — platform notes, auto-install risk, secrets, offline wheelhouse |
| Link detailed references | Done — CAPABILITY_INSTALLATION + CONFIGURATION_REFERENCE |
| Record tree/command/result | Done — this receipt |

## Discrepancies / deferred gates

| Item | Disposition |
| --- | --- |
| PyPI package availability for a given release channel | Root page documents `pip install ipfs-datasets-py` as the published path; source editable install is the verified tree path |
| Full env catalog not duplicated on root pages | Intentional — routes to CONFIGURATION_REFERENCE |
| Docker image names/tags | Deployment-owned; root page refuses placeholder registries without inventing unverified image names |
| IPFSDOC-063 leaf guides not re-edited | Dependency read-only evidence; root pages link to them |

## Non-claims

- These root pages do not re-certify production readiness of optional stacks.
- Probe success ≠ authorization ≠ proof (ADR-002).
- No claim that every example YAML key is consumed by every module.
