# IPFSDOC-091 Completion Receipt

| Field | Value |
| --- | --- |
| Task | `IPFSDOC-091` |
| Title | Refresh root installation and configuration pages |
| Status | `evidence` |
| Owner | user-docs |
| Goal id | `IPFSDOC-G021` |
| Depends on | `IPFSDOC-063` |
| Last verified | 2026-08-03 |
| Measured at (UTC) | 2026-08-03T08:18:12Z |
| Tree id / commit | `402099fc1059c745849418b045086b1398c6320d` |
| Branch | `implementation/ipfsdoc-091-cc473d9dd36e-attempt-1-1785744852` |
| Workspace | supervisor worktree for artifact completion (shard 3) |

## Declared outputs

| Path | Role |
| --- | --- |
| `docs/installation.md` | Root installation guide (`InstallationGuide@1`) |
| `docs/configuration.md` | Root configuration guide (`ConfigurationGuide@1`) |
| `docs/maintenance/completion_receipts/IPFSDOC-091.md` | This receipt |

## What changed

Replaced stale root pages that claimed Python 3.7/3.9, nonexistent extras (`vector`, `graphrag`, `webarchive`), placeholder organizations (`your-organization`, `yourorga/…`), obsolete CUDA pin recipes, and incomplete environment coverage.

New pages provide concise, source-grounded routes for:

- **Base install** (Python 3.12+, `endomorphosis/ipfs_datasets_py`, `scripts/setup/install.py --quick`, editable `pip install -e .`)
- **Optional capability extras** with real packaging names and explicit invalid-name redirects
- **Configuration precedence** (CLI → env → file → default) and profile recipes (base / capability / offline / unavailable)
- **Platform, security, and offline caveats** preserved with pointers to detailed leaves:
  - [CAPABILITY_INSTALLATION.md](../../guides/installation/CAPABILITY_INSTALLATION.md)
  - [CONFIGURATION_REFERENCE.md](../../guides/installation/CONFIGURATION_REFERENCE.md)

## Source authority used

| Source | Facts taken |
| --- | --- |
| `pyproject.toml` / `setup.py` | `requires-python >=3.12`, distribution name, optional-dependencies / extras, console scripts |
| `scripts/setup/install.py` | Canonical project installer (`--quick`) |
| `docker/Dockerfile` | Local Docker build (Python 3.12-slim); no placeholder public image |
| `docs/guides/installation/CAPABILITY_INSTALLATION.md` | Extra names, invalid aliases, native tools, offline/auto-install policy |
| `docs/guides/installation/CONFIGURATION_REFERENCE.md` | Precedence tables, env catalog, security consequences, profiles |
| `.env.example`, `config.yaml.example`, `configs.yaml.example` | Config file templates that exist in-tree |
| `ipfs_datasets_cli.py` / package init (via leaf guide citations) | CLI and auto-install precedence |

## Validation

### Command

```bash
test -s docs/installation.md && test -s docs/configuration.md && test -s docs/maintenance/completion_receipts/IPFSDOC-091.md && rg -n 'Python 3.12|CAPABILITY_INSTALLATION|CONFIGURATION_REFERENCE|optional|unavailable' docs/installation.md docs/configuration.md
```

### Result

- **Exit code:** `0`
- **Outcome:** **PASS**
- **Validated tree:** `402099fc1059c745849418b045086b1398c6320d`

Command stdout (file non-empty checks + focused `rg` hits):

```text
docs/installation.md:9:| Source of truth | `pyproject.toml`; `setup.py`; `requirements.txt`; `scripts/setup/install.py`; `docker/Dockerfile`; [CAPABILITY_INSTALLATION.md](guides/installation/CAPABILITY_INSTALLATION.md) |
docs/installation.md:12:| Related | [CAPABILITY_INSTALLATION.md](guides/installation/CAPABILITY_INSTALLATION.md), [CONFIGURATION_REFERENCE.md](guides/installation/CONFIGURATION_REFERENCE.md), [configuration.md](configuration.md), [PLATFORM_INSTALL.md](quickstart/PLATFORM_INSTALL.md) |
docs/installation.md:14:This page is the **short install route** for `ipfs_datasets_py`. Full extra tables, console scripts, native tools, lazy install policy, and capability probes live in [CAPABILITY_INSTALLATION.md](guides/installation/CAPABILITY_INSTALLATION.md). Configuration precedence and security consequences live in [configuration.md](configuration.md) and [CONFIGURATION_REFERENCE.md](guides/installation/CONFIGURATION_REFERENCE.md).
docs/installation.md:20:| **Python** | **Python 3.12+** (`requires-python = ">=3.12"` in `pyproject.toml`; `python_requires='>=3.12'` in `setup.py`) |
docs/installation.md:23:| Disk / network | Base install needs network or a prepared wheelhouse; optional theorem provers, OCR models, and Playwright browsers need extra disk when provisioned |
docs/installation.md:27:Base install is **not** every capability. Optional extras, system binaries, and native provers are separate layers; missing ones surface as **optional** / **unavailable**, not as silent success.
docs/installation.md:54:Editable install resolves `ipfs_kit_py` / `ipfs_accelerate_py` from vendored checkouts when present, otherwise from GitHub `main` (see `setup.py`). Constrained builds can skip VCS optional deps:
docs/installation.md:84:Install only the extras you need. Prefer the **declared** names below. Full matrix, platform markers, and recipes: [CAPABILITY_INSTALLATION.md](guides/installation/CAPABILITY_INSTALLATION.md).
docs/installation.md:118:Python wheels do not replace host tools. Missing tools leave related features **unavailable**.
docs/installation.md:143:- Platform notes: [PLATFORM_INSTALL.md](quickstart/PLATFORM_INSTALL.md) and [CAPABILITY_INSTALLATION.md](guides/installation/CAPABILITY_INSTALLATION.md).
docs/installation.md:147:On import, if unset, `IPFS_DATASETS_AUTO_INSTALL` defaults toward allowing runtime `pip` for missing optional modules. That favors developer machines and is **unsafe** for immutable images without an explicit policy.
docs/installation.md:164:Without a wheelhouse and without preinstalled binaries, optional features report **unavailable**—not proven, authorized, or healthy.
docs/installation.md:178:There is no verified public `yourorga/…` image in this tree. Build from the repository Dockerfile (`Dockerfile` → `docker/Dockerfile`, Python 3.12 base):
docs/installation.md:187:Container images still need the same optional extras and system tools for full capabilities. Prefer `IPFS_DATASETS_AUTO_INSTALL=false` in production images and bake dependencies at build time.
docs/installation.md:213:| `ImportError` for optional stack | Install the matching **extra** (§3); probe with `is_module_available` |
docs/installation.md:223:| Full extras, scripts, probes, offline matrix | [CAPABILITY_INSTALLATION.md](guides/installation/CAPABILITY_INSTALLATION.md) |
docs/installation.md:224:| Env vars, precedence, secrets | [configuration.md](configuration.md), [CONFIGURATION_REFERENCE.md](guides/installation/CONFIGURATION_REFERENCE.md) |
docs/configuration.md:9:| Source of truth | `ipfs_datasets_py/__init__.py`; `ipfs_datasets_cli.py`; `ipfs_datasets_py/auto_installer.py`; `ipfs_datasets_py/ipfs_backend_router.py`; `.env.example`; `config.yaml.example`; `configs.yaml.example`; [CONFIGURATION_REFERENCE.md](guides/installation/CONFIGURATION_REFERENCE.md) |
docs/configuration.md:12:| Related | [CONFIGURATION_REFERENCE.md](guides/installation/CONFIGURATION_REFERENCE.md), [CAPABILITY_INSTALLATION.md](guides/installation/CAPABILITY_INSTALLATION.md), [installation.md](installation.md), [SECRETS_AND_CREDENTIALS.md](guides/security/SECRETS_AND_CREDENTIALS.md) |
docs/configuration.md:14:This page is the **short configuration precedence route** for `ipfs_datasets_py`. The full environment catalog, subsystem tables, and security analysis live in [CONFIGURATION_REFERENCE.md](guides/installation/CONFIGURATION_REFERENCE.md). What to install for each capability lives in [installation.md](installation.md) and [CAPABILITY_INSTALLATION.md](guides/installation/CAPABILITY_INSTALLATION.md).
docs/configuration.md:60:2. Enabled optional providers (`IPFS_DATASETS_PY_ENABLE_IPFS_KIT`, `…_HTTPAPI` + host settings, `…_ENABLE_IPFS_ACCELERATE`)
docs/configuration.md:62:4. Feature degradation when nothing usable is available (**unavailable**, not “connected”)
docs/configuration.md:71:4. Phases blocked / failed / **unavailable**—never treat as “proven”
docs/configuration.md:102:Names below appear in current code or first-party examples. Truthy values are generally `1` / `true` / `yes` / `on` (case-insensitive) unless noted. Full catalog: [CONFIGURATION_REFERENCE.md](guides/installation/CONFIGURATION_REFERENCE.md).
docs/configuration.md:108:| `IPFS_DATASETS_PY_MINIMAL_IMPORTS` | Hermetic imports; optional stacks stay off |
docs/configuration.md:113:| `IPFS_DATASETS_PY_WARN_OPTIONAL_IMPORTS` | Warn on missing **optional** deps |
docs/configuration.md:149:Python bindings remain a packaging concern: install the `theorem-provers` **optional** extra (or `requirements-theorem-provers.txt`). Native CLIs are not PyPI packages.
docs/configuration.md:163:## 4. Profiles: base, capability, offline, unavailable
docs/configuration.md:193:**Implication:** only pre-provisioned wheels and local prover roots work; missing artifacts surface as **unavailable**, not silent success.
docs/configuration.md:199:| Optional media / scrape / vector helpers | Missing extra or env | Soft-disable, clear **unavailable** status |
docs/configuration.md:208:| Native prover download / optional sudo | Keep sudo allow unset; pin executables; treat install receipts as environment evidence only |
docs/configuration.md:214:Full write-up: [CONFIGURATION_REFERENCE.md §6](guides/installation/CONFIGURATION_REFERENCE.md).
docs/configuration.md:245:| Full env catalog and security detail | [CONFIGURATION_REFERENCE.md](guides/installation/CONFIGURATION_REFERENCE.md) |
docs/configuration.md:246:| Install extras and native tools | [installation.md](installation.md), [CAPABILITY_INSTALLATION.md](guides/installation/CAPABILITY_INSTALLATION.md) |
```

### Stale-token scan (supplemental)

Scan for obsolete claims (`Python 3.7`, `Python 3.9`, `your-organization`, `yourorga`, singular extras, `torch==1.10`, `faiss-gpu`) on the two root pages. Matches below are intentional **negative** documentation (what not to use / what was obsolete), not install recipes:

```text
docs/installation.md:25:**Not supported as the package baseline:** Python 3.7–3.11. Older docs that claim Python 3.7+ or 3.9+ are obsolete.
docs/installation.md:114:| Placeholder orgs (`your-organization`, `yourorga/…`) | `endomorphosis/ipfs_datasets_py` (or your real fork) |
docs/installation.md:139:Do **not** follow obsolete pin recipes (for example `torch==1.10.*+cu113` or blanket `faiss-gpu` one-liners from old docs). Current packaging:
docs/installation.md:178:There is no verified public `yourorga/…` image in this tree. Build from the repository Dockerfile (`Dockerfile` → `docker/Dockerfile`, Python 3.12 base):
```

### Required token coverage

The validation `rg` pattern hits both root pages for: `Python 3.12`, `CAPABILITY_INSTALLATION`, `CONFIGURATION_REFERENCE`, `optional`, `unavailable`.

## Explicit non-claims

- No live PyPI publish or network install was performed as part of this documentation task.
- No claim that every optional extra installs cleanly on every OS without platform markers.
- Docker image tags other than local builds from this repository are not asserted as published.
- GPU/CUDA wheel selection is intentionally deferred to current vendor indexes and the `ml` / platform docs—obsolete version pins were removed, not replaced with another frozen CUDA recipe.
- Getting-started / user-guide journey refresh remains `IPFSDOC-092`.
