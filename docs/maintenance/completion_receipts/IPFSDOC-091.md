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
| Attempt | 3 |
| Measured at (UTC) | 2026-08-03T08:43:20Z |
| Worktree commit (`HEAD`) | `e5beb77fbba11b99384027428e319282074a6236` |
| Worktree commit tree (`HEAD^{tree}`) | `fa5e11a96c0c5be6ba48ff0dab19786431d7c883` |
| Supervisor tree_id (packet) | `1d7d7ff8a36085a941467c7e2467ae43ec510795` |
| Objective revision | `baguqeerazrdt3hotny7sgnnurffntds53vy6jntcs6nck5wth6ncp4gb47qa` |
| Branch | `implementation/ipfsdoc-091-cc473d9dd36e-attempt-3-1785746543` |
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
| `pyproject.toml` (`requires-python >=3.12`, optional-dependencies, version 0.2.0) | Packaging truth for Python floor and pyproject extras |
| `setup.py` extras_require (includes `web_archive`, platform markers) | Full extra inventory including setup-only keys |
| README / clone URL `endomorphosis/ipfs_datasets_py` | Real org; no placeholders |
| Prior attempt-2 root pages + receipt | Re-verified against current tree; content accepted; receipt refreshed |
| Sibling receipts `IPFSDOC-064`, `IPFSDOC-090`, `IPFSDOC-093` | Receipt shape and validation table pattern |
| Checkpoint `status.txt` (attempt 2 claimed validated on older tree) | Inspected; tree identity advanced—re-recorded on attempt 3 |

Protected plan files under `docs/implementation/plans/IPFS_DATASETS_DOCUMENTATION_REFRESH*` were **not** modified.

Depends-on (IPFSDOC-063) consulted as source only; detailed guides not re-edited.

## What changed

### `docs/installation.md`

Concise **RootInstallationPage@1** (retained and re-verified on attempt 3):

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

Concise **RootConfigurationPage@1** (retained and re-verified on attempt 3):

1. Metadata + routes to `CONFIGURATION_REFERENCE` and `CAPABILITY_INSTALLATION`.
2. Precedence model: CLI → env → files → defaults; CLI dashboard table; auto-install security note.
3. Essential `IPFS_DATASETS*` / hermetic / install / IPFS / secrets variables.
4. Config file sources as templates; `initialize()` / `RouterDeps` note.
5. Profiles: base, optional capability, offline, unavailable vs fail-closed.
6. Security and platform caveats preserved with deep links.
7. Operator recipes (CI, dev, production) and smoke checks.

### `docs/maintenance/completion_receipts/IPFSDOC-091.md`

This receipt: attempt **3** tree identity, validation command, pass table, acceptance map (goal **IPFSDOC-G021**).

## Validated current tree

```text
HEAD:     e5beb77fbba11b99384027428e319282074a6236
Tree:     fa5e11a96c0c5be6ba48ff0dab19786431d7c883
Subject:  Merge commit '0115b99a760df754d6d26d7bf51411f659933fc8' into implementation/ipfsdoc-083-e80fdd41fa32-attempt-2-1785746061
Committer date: 2026-08-03 08:34:22 +0000
Branch:   implementation/ipfsdoc-091-cc473d9dd36e-attempt-3-1785746543
Package:  ipfs_datasets_py 0.2.0, requires-python >=3.12
Packet tree_id (supervisor): 1d7d7ff8a36085a941467c7e2467ae43ec510795
```

Commands used for identity:

```bash
git rev-parse HEAD
git rev-parse 'HEAD^{tree}'
git log -1 --format='%H %ci %s'
git branch --show-current
```

Note: `HEAD` / tree above are the worktree base at measurement time (pre-daemon
commit of these documentation outputs). Content SHAs of the declared route pages
are recorded in the Declared outputs table. Supervisor `tree_id` is recorded for
packet correlation; worktree `HEAD^{tree}` is the measured git object.

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
| Python 3.12 | yes | (install route linked; required set covered across both files) |
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
- Attempt-2 checkpoint (`status=validated`, tree `1f802980…`) was for a prior worktree base; attempt 3 re-verified content and re-recorded identity for the current worktree.

## Re-run recipe

From repository root of this worktree:

```bash
test -s docs/installation.md && test -s docs/configuration.md && test -s docs/maintenance/completion_receipts/IPFSDOC-091.md && rg -n 'Python 3.12|CAPABILITY_INSTALLATION|CONFIGURATION_REFERENCE|optional|unavailable' docs/installation.md docs/configuration.md
```

Expected: exit status `0`, three non-empty files, multiple `rg` hit lines including every required keyword.
