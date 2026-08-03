# Configuration Guide

| Field | Value |
| --- | --- |
| Interface | `ConfigurationGuide@1` |
| Task | `IPFSDOC-091` |
| Status | `canonical` |
| Owner | user-docs |
| Source of truth | `ipfs_datasets_py/__init__.py`; `ipfs_datasets_cli.py`; `ipfs_datasets_py/auto_installer.py`; `ipfs_datasets_py/ipfs_backend_router.py`; `.env.example`; `config.yaml.example`; `configs.yaml.example`; [CONFIGURATION_REFERENCE.md](guides/installation/CONFIGURATION_REFERENCE.md) |
| Last verified | 2026-08-03 |
| Audience | end-user, operator, developer, security reviewer |
| Related | [CONFIGURATION_REFERENCE.md](guides/installation/CONFIGURATION_REFERENCE.md), [CAPABILITY_INSTALLATION.md](guides/installation/CAPABILITY_INSTALLATION.md), [installation.md](installation.md), [SECRETS_AND_CREDENTIALS.md](guides/security/SECRETS_AND_CREDENTIALS.md) |

This page is the **short configuration precedence route** for `ipfs_datasets_py`. The full environment catalog, subsystem tables, and security analysis live in [CONFIGURATION_REFERENCE.md](guides/installation/CONFIGURATION_REFERENCE.md). What to install for each capability lives in [installation.md](installation.md) and [CAPABILITY_INSTALLATION.md](guides/installation/CAPABILITY_INSTALLATION.md).

## 1. Precedence model

Subsystems share one idea: **more specific overrides less specific**, and **runtime flags beat files**.

### 1.1 General rule

For a given key, unless a subsystem documents a narrower order:

**CLI flag → environment variable → config file → built-in default**

When two env aliases exist, **code-defined order** wins (example: gateway prefers `IPFS_HTTP_GATEWAY`, then `IPFS_DATASETS_IPFS_GATEWAY`).

### 1.2 CLI dashboard / gateway (`ipfs_datasets_cli.py`)

| Setting | Highest → lowest |
| --- | --- |
| Host / port | `--host` / `--port` → `IPFS_DATASETS_HOST` / `IPFS_DATASETS_PORT` → `~/.ipfs_datasets/cli.json` (or `--config` / `IPFS_DATASETS_CLI_CONFIG`) → `127.0.0.1` / `8899` |
| IPFS HTTP gateway | `--gateway` → `IPFS_HTTP_GATEWAY` or `IPFS_DATASETS_IPFS_GATEWAY` → config JSON `gateway` → unset |
| Config path | `--config` → `IPFS_DATASETS_CLI_CONFIG` → `~/.ipfs_datasets/cli.json` |

Example user CLI defaults:

```json
{
  "host": "127.0.0.1",
  "port": "8899",
  "gateway": "https://ipfs.io"
}
```

### 1.3 Import and auto-install policy

| Layer | Role |
| --- | --- |
| Explicit env at process start | Wins when set **before** import |
| Package defaults | If `IPFS_DATASETS_AUTO_INSTALL` is unset, import may set it to `"true"` (developer-friendly default) |
| Minimal / benchmark modes | `IPFS_DATASETS_PY_MINIMAL_IMPORTS=1` or `IPFS_DATASETS_PY_BENCHMARK=1` force hermetic behavior and disable runtime install |
| Feature call-site | `ensure_module` / routers may still refuse install under offline/minimal policy |

**Security:** production and CI **must** set `IPFS_DATASETS_AUTO_INSTALL=false` (or minimal modes) before import if surprise `pip` mutation is unacceptable.

### 1.4 IPFS backend selection (conceptual)

1. Explicit `IPFS_DATASETS_PY_IPFS_BACKEND` (force named backend)
2. Enabled optional providers (`IPFS_DATASETS_PY_ENABLE_IPFS_KIT`, `…_HTTPAPI` + host settings, `…_ENABLE_IPFS_ACCELERATE`)
3. Local Kubo CLI (`IPFS_DATASETS_PY_KUBO_CMD`, default `ipfs`)
4. Feature degradation when nothing usable is available (**unavailable**, not “connected”)

`IPFS_KIT_DISABLE` hard-disables kit bootstrap.

### 1.5 Theorem-prover resolution

1. Explicit `IPFS_DATASETS_PY_<PROVER>_EXECUTABLE`
2. `PATH` and user-local root (`IPFS_DATASETS_PY_EXTERNAL_PROVER_ROOT`)
3. Lazy installer (if allowed) or org `IPFS_DATASETS_PY_<SOLVER>_INSTALL_COMMAND`
4. Phases blocked / failed / **unavailable**—never treat as “proven”

## 2. Configuration sources

| Source | Typical use | Notes |
| --- | --- | --- |
| Process environment / `.env` | Secrets, feature flags, binds | Highest practical deploy control; never commit real secrets |
| `~/.ipfs_datasets/cli.json` | Operator CLI defaults | User-local |
| `.env.example` | Template keys | Copy to `.env`; verify consumers before relying on every key |
| `config.yaml.example`, `configs.yaml.example`, `sql_configs.yaml.example` | Application YAML sketches | Templates only |
| `IPFS_DATASETS_CONFIG` | Deploy pointer (e.g. MCP YAML) | Not universal for every subsystem |
| Module TOML loaders (`ipfs_datasets_py.config`) | Legacy/module-specific | Prefer explicit paths in automation |

```bash
cp .env.example .env
# edit secrets and hosts; never commit .env
```

### 2.1 Explicit process initialization

Import is not a full substitute for shared client setup when accelerate/IPFS clients must be process-scoped:

```python
from ipfs_datasets_py import initialize, RouterDeps

deps = RouterDeps()
initialize(deps=deps, register_symai_engines=False)
```

## 3. High-value environment variables

Names below appear in current code or first-party examples. Truthy values are generally `1` / `true` / `yes` / `on` (case-insensitive) unless noted. Full catalog: [CONFIGURATION_REFERENCE.md](guides/installation/CONFIGURATION_REFERENCE.md).

### 3.1 Hermetic import and heavy stacks

| Variable | Effect when set |
| --- | --- |
| `IPFS_DATASETS_PY_MINIMAL_IMPORTS` | Hermetic imports; optional stacks stay off |
| `IPFS_DATASETS_PY_BENCHMARK` | Same minimal treatment |
| `IPFS_DATASETS_PY_ENABLE_MCP_IMPORTS` | Allow MCP-related import-time exports |
| `IPFS_DATASETS_PY_ENABLE_FASTAPI_IMPORTS` | Allow FastAPI-related import-time exports |
| `IPFS_DATASETS_PY_ENABLE_LLM_IMPORTS` | Allow transformers/LLM import-time paths |
| `IPFS_DATASETS_PY_WARN_OPTIONAL_IMPORTS` | Warn on missing **optional** deps |

### 3.2 Auto / lazy Python installation

| Variable | Role |
| --- | --- |
| `IPFS_DATASETS_AUTO_INSTALL` / `IPFS_AUTO_INSTALL` | Master switch for runtime `pip` |
| `IPFS_DATASETS_AUTO_INSTALL_OFFLINE` | Offline/wheelhouse pip mode |
| `IPFS_DATASETS_AUTO_INSTALL_WHEELHOUSE` | Local wheel directory |
| `IPFS_DATASETS_PIP_TIMEOUT` | Bounded pip timeout |
| `IPFS_DATASETS_PY_INCLUDE_VCS_DEPENDENCIES` | Include kit/accelerate VCS deps at package install |

### 3.3 IPFS, cache, and routers

| Variable | Role |
| --- | --- |
| `IPFS_DATASETS_HOST` / `IPFS_DATASETS_PORT` | CLI/dashboard defaults |
| `IPFS_HTTP_GATEWAY` / `IPFS_DATASETS_IPFS_GATEWAY` | HTTP gateway for content helpers |
| `IPFS_HOST` / related API vars (examples) | Daemon endpoints in `.env.example` |
| `IPFS_DATASETS_PY_IPFS_BACKEND` | Force backend name |
| `IPFS_DATASETS_PY_ENABLE_IPFS_KIT` / `…_HTTPAPI` / `…_ACCELERATE` | Provider enable flags |
| `IPFS_DATASETS_PY_KUBO_CMD` | Kubo CLI name/path |
| `IPFS_KIT_DISABLE` | Hard-disable kit |
| `IPFS_DATASETS_SAFE_ROOT` | Bound path/CAR operations |
| `IPFS_DATASETS_PY_CACHE_P2P_SHARED_SECRET` | Prefer dedicated P2P secret (do not reuse privileged tokens) |

### 3.4 Theorem provers

| Variable | Role |
| --- | --- |
| `IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS` | Master switch for first-use native install |
| `IPFS_DATASETS_PY_LAZY_INSTALL_<PROVER>` | Per-prover override |
| `IPFS_DATASETS_PY_EXTERNAL_PROVER_ROOT` | User-local solver tree |
| `IPFS_DATASETS_PY_<PROVER>_EXECUTABLE` | Pin binary path |
| `IPFS_DATASETS_PY_ALLOW_SUDO_FOR_PROVERS` | Interactive sudo (**default deny**) |

Python bindings remain a packaging concern: install the `theorem-provers` **optional** extra (or `requirements-theorem-provers.txt`). Native CLIs are not PyPI packages.

### 3.5 Secrets and service keys (high sensitivity)

| Variable (examples) | Note |
| --- | --- |
| `JWT_SECRET_KEY` | Dashboard auth signing |
| `OPENAI_API_KEY` / `IPFS_DATASETS_PY_OPENAI_API_KEY` | LLM / realtime paths |
| `POSTGRES_*` / `DATABASE_PATH` | Persistence credentials and local DB path |
| `GITHUB_TOKEN` / `GH_TOKEN` | Error reporting and possible cache-secret fallbacks—scope tightly |
| Twilio / Cloudflare `IPFS_DATASETS_*` keys | Messaging and crawl credentials |

Store secrets outside the repository; inject at runtime. See [SECRETS_AND_CREDENTIALS.md](guides/security/SECRETS_AND_CREDENTIALS.md).

## 4. Profiles: base, capability, offline, unavailable

### 4.1 Base / library embed

```bash
export IPFS_DATASETS_AUTO_INSTALL=false
# leave ENABLE_* import flags unset unless required
python -c "import ipfs_datasets_py"
```

**Implication:** no runtime pip; heavy stacks absent until explicitly installed and imported.

### 4.2 Capability-enabled host

```bash
pip install -e '.[vectors,file_conversion,theorem-provers,api]'
export IPFS_DATASETS_PY_ENABLE_MCP_IMPORTS=1   # only if MCP import-time surface is required
```

**Implication:** features matching installed extras **and** system tools can run; probes still do not equal production attestation.

### 4.3 Offline / air-gapped

```bash
export IPFS_DATASETS_AUTO_INSTALL=0
export IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS=0
export IPFS_DATASETS_AUTO_INSTALL_OFFLINE=1
export IPFS_DATASETS_AUTO_INSTALL_WHEELHOUSE=/media/wheels
```

**Implication:** only pre-provisioned wheels and local prover roots work; missing artifacts surface as **unavailable**, not silent success.

### 4.4 Unavailable degradation vs fail-closed trust

| Class | Configuration stance | Runtime stance |
| --- | --- | --- |
| Optional media / scrape / vector helpers | Missing extra or env | Soft-disable, clear **unavailable** status |
| Authz, admissibility, proof, identity integrity | Missing validator / prover / secret | **Fail closed**—never treat as verified or authorized |
| P2P cache without shared secret | Misconfigured secret chain | Prefer disable (`IPFS_DATASETS_PY_CACHE_DISABLE_TASK_P2P`) over weak secrets |

## 5. Security consequences (preserve in ops)

| Risk | Mitigation |
| --- | --- |
| Default-on auto-install mutates envs | `IPFS_DATASETS_AUTO_INSTALL=false`; bake deps in images |
| Native prover download / optional sudo | Keep sudo allow unset; pin executables; treat install receipts as environment evidence only |
| Secrets in env dumps / P2P token fallbacks | Dedicated P2P secret; rotate leaked tokens; no secrets in CI logs |
| Open binds (`0.0.0.0`, open IPFS API) | Localhost + reverse proxy + auth for non-lab use |
| Path traversal on CAR/fs ops | Set `IPFS_DATASETS_SAFE_ROOT` carefully |
| Error reporting with GitHub tokens | Ensure stack traces cannot contain secrets |

Full write-up: [CONFIGURATION_REFERENCE.md §6](guides/installation/CONFIGURATION_REFERENCE.md).

## 6. Config hygiene and rollback

| Goal | Action |
| --- | --- |
| Stop runtime pip | `IPFS_DATASETS_AUTO_INSTALL=false` and/or minimal imports |
| Stop native prover downloads | `IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS=0` |
| Clear CLI defaults | Remove `~/.ipfs_datasets/cli.json` |
| Revoke secrets | Rotate keys and update the secret store; rolling back code does not undo exposure |
| Disable P2P cache | `IPFS_DATASETS_PY_CACHE_DISABLE_TASK_P2P=1` |

## 7. Quick checks

```bash
# Hermetic import (expect no runtime install)
IPFS_DATASETS_AUTO_INSTALL=false python -c "import ipfs_datasets_py; print('ok')"

# Optional capability probe (after installing the matching extra)
python -c "from ipfs_datasets_py.logic.common.feature_detection import is_module_available as a; print('faiss', a('faiss'))"

# CLI defaults path (when CLI is installed)
ipfs-datasets info defaults
```

Do not use invented import paths or legacy module names as configuration smoke tests. Prefer probes and documented CLI commands against the current tree.

## 8. Next steps

| Need | Go to |
| --- | --- |
| Full env catalog and security detail | [CONFIGURATION_REFERENCE.md](guides/installation/CONFIGURATION_REFERENCE.md) |
| Install extras and native tools | [installation.md](installation.md), [CAPABILITY_INSTALLATION.md](guides/installation/CAPABILITY_INSTALLATION.md) |
| Architecture of routers / init | [DEPENDENCY_AND_INITIALIZATION.md](architecture/DEPENDENCY_AND_INITIALIZATION.md) |
| Secrets handling | [SECRETS_AND_CREDENTIALS.md](guides/security/SECRETS_AND_CREDENTIALS.md) |
| User journeys | [getting_started.md](getting_started.md), [user_guide.md](user_guide.md) |
