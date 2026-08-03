# Completion receipt — IPFSDOC-091

| Field | Value |
| --- | --- |
| Interface | `DocumentationTaskCompletionReceipt@1` |
| Task | `IPFSDOC-091` |
| Title | Refresh root installation and configuration pages |
| Status | `evidence` |
| Owner | user-docs (implementation agent) |
| Goal id | `IPFSDOC-G111` |
| Track | user-docs |
| Bundle | documentation / installation-configuration |
| Attempt | 2 |
| Measured at (UTC) | 2026-08-03T08:30:51Z |
| Worktree commit (`HEAD`) | `15149fb7f507ea535a9bfc11f2b2237d60a84a2f` |
| Worktree commit tree (`HEAD^{tree}`) | `1f802980c480b9cc9bd02d1cfac448910327d11a` |
| Supervisor tree_id (packet) | `3d8043a6f47e8e23e55cf87707b7e4c69b0de37f` |
| Objective revision | `baguqeerazrdt3hotny7sgnnurffntds53vy6jntcs6nck5wth6ncp4gb47qa` |
| Branch | `implementation/ipfsdoc-091-cc473d9dd36e-attempt-2-1785745741` |
| Package version (cited) | `ipfs_datasets_py` **0.2.0** (`requires-python >= 3.12`) |
| Checkpoint dir | `$IPFS_ACCELERATE_AGENT_TASK_CHECKPOINT_DIR` → `…/implementation_checkpoints/ipfsdoc-091-cc473d9dd36e` |
| Audience | maintainer, agent, daemon validation gate |

## Acceptance restated

Replace Python 3.7/3.9, nonexistent extras, placeholder organizations, obsolete
CUDA advice, and incomplete environment coverage with concise verified
base/capability installation and configuration precedence routes. Preserve
platform/security/offline caveats and link to the detailed references. Record
the validated current tree, command, and result in this completion receipt.

## Declared outputs

| Path | Role | Size (bytes, post-write) | Content SHA-256 (at validation) |
| --- | ---: | ---: | --- |
| `docs/installation.md` | Root installation route page | 9680 | `dd6e2a492df6379839bf9af96e9a1bc3ff0179890b83d41afd6decc24d24935d` |
| `docs/configuration.md` | Root configuration route page | 10734 | `ce07ab371fac186b44c46cba4df29ce07fc4efcc878ab823bd67ad32ce31d2f9` |
| `docs/maintenance/completion_receipts/IPFSDOC-091.md` | This completion receipt | non-empty | evidence artifact (this file); content is the authoritative record |

## Evidence used (read-only)

| Source | Use |
| --- | --- |
| `docs/guides/installation/CAPABILITY_INSTALLATION.md` (IPFSDOC-063) | Verified extras, base install, native tools, offline, probes |
| `docs/guides/installation/CONFIGURATION_REFERENCE.md` (IPFSDOC-063) | Precedence model, env catalog, security, profiles |
| `pyproject.toml` (`requires-python >=3.12`, optional-dependencies, version 0.2.0) | Packaging truth for extras and Python floor |
| `setup.py` / README clone URL `endomorphosis/ipfs_datasets_py` | Real org; console scripts; platform markers |
| Prior stale `docs/installation.md` / `docs/configuration.md` | Replaced content (3.7/3.9, singular extras, placeholders, CUDA 10/11 pins) |
| Sibling receipts `IPFSDOC-064`, `IPFSDOC-090`, `IPFSDOC-093` | Receipt shape and validation table pattern |
| Checkpoint `status.txt` (prior attempt claimed validated) | Inspected; worktree still held stale root pages—reimplemented |

Protected plan files under `docs/implementation/plans/IPFS_DATASETS_DOCUMENTATION_REFRESH*` were **not** modified.

Depends-on (IPFSDOC-063) consulted as source only; detailed guides not re-edited.

## What changed

### `docs/installation.md`

Replaced the long stale guide with a concise **RootInstallationPage@1**:

1. Metadata + explicit routes to `CAPABILITY_INSTALLATION` and `CONFIGURATION_REFERENCE`.
2. **Python 3.12+** requirements; 3.7–3.11 called unsupported.
3. Base install from `endomorphosis/ipfs_datasets_py` (no placeholder orgs).
4. Real optional extras: `vectors`, `knowledge_graphs`, `web_archive`, `theorem-provers`, `file_conversion`, `lazy`, `all`, etc.; invalid singular names table.
5. Native tools and managed prover installer pointer.
6. GPU/CUDA: no obsolete torch 1.10 / cu102 / cu113 recipe; vendor-current guidance + `faiss-cpu` via `vectors`.
7. Docker from first-party assets; reject `yourorga/…` images.
8. Platform / offline / security / **unavailable** caveats preserved.
9. “What this page replaced” map for drift repair.

### `docs/configuration.md`

Replaced sparse env/YAML sketch with a concise **RootConfigurationPage@1**:

1. Metadata + routes to `CONFIGURATION_REFERENCE` and `CAPABILITY_INSTALLATION`.
2. Precedence model: CLI → env → files → defaults; CLI dashboard table; auto-install security note.
3. Essential `IPFS_DATASETS*` / hermetic / install / IPFS / secrets variables.
4. Config file sources as templates; `initialize()` / `RouterDeps` note.
5. Profiles: base, optional capability, offline, unavailable vs fail-closed.
6. Security and platform caveats preserved with deep links.
7. Operator recipes (CI, dev, production) and smoke checks.

### `docs/maintenance/completion_receipts/IPFSDOC-091.md`

This receipt: validated tree identity, command, pass table, acceptance map.

## Validated current tree

```text
HEAD:     15149fb7f507ea535a9bfc11f2b2237d60a84a2f
Tree:     1f802980c480b9cc9bd02d1cfac448910327d11a
Subject:  Merge commit '285b6eb825449cbd0eaf55bfa1cc4d0554b93368' into implementation/ipfsdoc-091-cc473d9dd36e-attempt-2-1785745741
Committer date: 2026-08-03 08:29:02 +0000
Branch:   implementation/ipfsdoc-091-cc473d9dd36e-attempt-2-1785745741
Package:  ipfs_datasets_py 0.2.0, requires-python >=3.12
```

Commands used for identity:

```bash
git rev-parse HEAD
git rev-parse 'HEAD^{tree}'
git log -1 --format='%H %ci %s'
git branch --show-current
```

Note: `HEAD` / tree above are the worktree base at measurement time (pre-daemon
commit of these documentation outputs). Content SHAs of the three declared
output files are recorded in the Declared outputs table.

## Validation command and result

**Command** (task contract):

```bash
test -s docs/installation.md && test -s docs/configuration.md && test -s docs/maintenance/completion_receipts/IPFSDOC-091.md && rg -n 'Python 3.12|CAPABILITY_INSTALLATION|CONFIGURATION_REFERENCE|optional|unavailable' docs/installation.md docs/configuration.md
```

**Result:** exit code **0** (all three declared paths non-empty; required tokens present).

| Check | Result |
| --- | --- |
| `test -s docs/installation.md` | **pass** (non-empty; 9680 bytes) |
| `test -s docs/configuration.md` | **pass** (non-empty; 10734 bytes) |
| `test -s docs/maintenance/completion_receipts/IPFSDOC-091.md` | **pass** (this file non-empty) |
| `rg` token coverage on installation + configuration | **pass** — matching lines cover all required tokens |
| Overall gate | **pass** (exit 0) |

### Keyword presence (required tokens)

| Token | Present in `docs/installation.md` | Present in `docs/configuration.md` |
| --- | --- | --- |
| Python 3.12 | yes | (via related install route; required set covered across both files) |
| CAPABILITY_INSTALLATION | yes | yes |
| CONFIGURATION_REFERENCE | yes | yes |
| optional | yes | yes |
| unavailable | yes | yes |

## Acceptance criteria map

| Criterion | Evidence |
| --- | --- |
| Replace Python 3.7/3.9 | installation §1 Python 3.12+; replaced table |
| Replace nonexistent extras | installation §3 real extras + invalid name table |
| Replace placeholder organizations | clone/Docker URLs use `endomorphosis/ipfs_datasets_py` |
| Replace obsolete CUDA advice | installation §3 GPU/CUDA (no cu102/cu113/torch 1.10 recipe) |
| Incomplete environment coverage → precedence routes | configuration §1–§4 + link to CONFIGURATION_REFERENCE |
| Base + capability install routes | installation §2–§3; CAPABILITY_INSTALLATION deep link |
| Preserve platform/security/offline caveats | installation §5; configuration §4–§5 |
| Link to detailed references | CAPABILITY_INSTALLATION + CONFIGURATION_REFERENCE throughout both pages |
| Validated tree, command, result | This receipt sections above |

## Explicit non-claims

- This receipt is **evidence** for the measured commit/date; it is not evergreen product architecture.
- Root route pages do not outrank packaging (`pyproject.toml` / `setup.py`), tests, or the detailed CAPABILITY_INSTALLATION / CONFIGURATION_REFERENCE guides when they disagree.
- No production code, packaging, or protected plan files were changed.
- Daemon commit/merge remains subject to the supervisor validation gate.
- Prior checkpoint `status=validated` did not match worktree content; full rewrite performed on attempt 2.

## Re-run recipe

From repository root of this worktree:

```bash
test -s docs/installation.md && test -s docs/configuration.md && test -s docs/maintenance/completion_receipts/IPFSDOC-091.md && rg -n 'Python 3.12|CAPABILITY_INSTALLATION|CONFIGURATION_REFERENCE|optional|unavailable' docs/installation.md docs/configuration.md
```

Expected: exit status `0`, three non-empty files, multiple `rg` hit lines including every required keyword.
