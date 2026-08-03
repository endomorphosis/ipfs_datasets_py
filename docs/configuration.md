# Configuration

| Field | Value |
| --- | --- |
| Interface | `RootConfigurationPage@1` |
| Task | `IPFSDOC-091` |
| Status | `canonical` (route page) |
| Owner | user-docs |
| Source of truth | `ipfs_datasets_py/__init__.py`; `ipfs_datasets_cli.py`; `.env.example`; [CONFIGURATION_REFERENCE.md](guides/installation/CONFIGURATION_REFERENCE.md) |
| Last verified | 2026-08-03 |
| Audience | end-user, operator, developer, security reviewer |
| Related | [installation.md](installation.md), [CAPABILITY_INSTALLATION.md](guides/installation/CAPABILITY_INSTALLATION.md), [SECRETS_AND_CREDENTIALS.md](guides/security/SECRETS_AND_CREDENTIALS.md) |

This page is the **short configuration route** for `ipfs_datasets_py`. The full environment catalog, security consequences, and operator profiles live in:

→ **[Configuration Reference](guides/installation/CONFIGURATION_REFERENCE.md)** (`CONFIGURATION_REFERENCE`)

What to install (base vs optional extras, native tools, offline) lives in:

→ **[installation.md](installation.md)** and **[CAPABILITY_INSTALLATION.md](guides/installation/CAPABILITY_INSTALLATION.md)** (`CAPABILITY_INSTALLATION`)

---

## 1. Precedence model

Different subsystems share one idea: **more specific overrides less specific**, and **runtime/process flags beat files**.

| Layer (highest → lowest) | Examples |
| --- | --- |
| CLI flags | `ipfs-datasets --host` / `--port` / `--gateway` / `--config` |
| Process environment | `IPFS_DATASETS_*`, `IPFS_DATASETS_PY_*`, secret keys |
| Config files | `~/.ipfs_datasets/cli.json`, copied YAML examples, module TOML |
| Built-in defaults | Hardcoded host/port, soft auto-install defaults on import |

### CLI / dashboard

| Setting | Precedence |
| --- | --- |
| Host / port | CLI → `IPFS_DATASETS_HOST` / `IPFS_DATASETS_PORT` → `~/.ipfs_datasets/cli.json` (or `IPFS_DATASETS_CLI_CONFIG` / `--config`) → `127.0.0.1` / `8899` |
| IPFS HTTP gateway | `--gateway` → `IPFS_HTTP_GATEWAY` or `IPFS_DATASETS_IPFS_GATEWAY` → config JSON → none |
| Config path | `--config` → `IPFS_DATASETS_CLI_CONFIG` → `~/.ipfs_datasets/cli.json` |

### Import and auto-install policy

| Control | Effect |
| --- | --- |
| `IPFS_DATASETS_AUTO_INSTALL` | If **unset**, import sets it to `"true"` (runtime `pip` allowed) |
| `IPFS_DATASETS_PY_MINIMAL_IMPORTS=1` or `IPFS_DATASETS_PY_BENCHMARK=1` | Hermetic: no runtime install; optional stacks stay off |
| `IPFS_DATASETS_AUTO_INSTALL=false` | Production/CI: no surprise environment mutation |

**Security:** default-on auto-install favors developers. Production **must** set `IPFS_DATASETS_AUTO_INSTALL=false` (or minimal-import modes) **before** import if surprise `pip` is unacceptable.

### IPFS backend selection (conceptual)

1. Explicit `IPFS_DATASETS_PY_IPFS_BACKEND`
2. Enabled optional providers (kit / HTTP API / accelerate flags + host endpoints)
3. Local Kubo CLI (`IPFS_DATASETS_PY_KUBO_CMD`, default `ipfs`)
4. Feature degradation when nothing usable is available (**unavailable**, not “verified”)

### Theorem provers

1. `IPFS_DATASETS_PY_<PROVER>_EXECUTABLE`
2. `PATH` and `IPFS_DATASETS_PY_EXTERNAL_PROVER_ROOT`
3. Lazy installer (if allowed) or org `…_INSTALL_COMMAND`
4. Unavailable / blocked / failed — never treated as proven

Full tables: [CONFIGURATION_REFERENCE.md](guides/installation/CONFIGURATION_REFERENCE.md).

---

## 2. Essential environment variables

Names appear in current code or first-party examples. Truthy values are generally `1` / `true` / `yes` / `on` (case-insensitive).

### Hermetic import

| Variable | Role |
| --- | --- |
| `IPFS_DATASETS_PY_MINIMAL_IMPORTS` | Hermetic imports; optional stacks off |
| `IPFS_DATASETS_PY_BENCHMARK` | Same minimal treatment |
| `IPFS_DATASETS_PY_ENABLE_MCP_IMPORTS` | Opt-in MCP import-time surface |
| `IPFS_DATASETS_PY_ENABLE_FASTAPI_IMPORTS` | Opt-in FastAPI import-time surface |
| `IPFS_DATASETS_PY_ENABLE_LLM_IMPORTS` | Opt-in transformers/LLM import paths |

### Auto / lazy install

| Variable | Role |
| --- | --- |
| `IPFS_DATASETS_AUTO_INSTALL` / `IPFS_AUTO_INSTALL` | Runtime pip master switch |
| `IPFS_DATASETS_AUTO_INSTALL_OFFLINE` | Offline/wheelhouse pip mode |
| `IPFS_DATASETS_AUTO_INSTALL_WHEELHOUSE` | Local `--find-links` directory |
| `IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS` | First-use native prover install |
| `IPFS_DATASETS_PY_ALLOW_SUDO_FOR_PROVERS` | Interactive sudo (**default deny**) |

### IPFS / cache / safety

| Variable | Role |
| --- | --- |
| `IPFS_DATASETS_HOST` / `IPFS_DATASETS_PORT` | CLI/dashboard bind defaults |
| `IPFS_HTTP_GATEWAY` / `IPFS_DATASETS_IPFS_GATEWAY` | Content fetch gateway |
| `IPFS_HOST` / related API vars (examples) | Daemon endpoints |
| `IPFS_DATASETS_PY_IPFS_BACKEND` | Force backend name |
| `IPFS_DATASETS_SAFE_ROOT` | Bound CAR/path operations (path-traversal reduction) |
| `IPFS_DATASETS_PY_CACHE_P2P_SHARED_SECRET` | Prefer dedicated P2P secret (not `GH_TOKEN`) |

### Secrets (never commit)

| Variable | Role |
| --- | --- |
| `JWT_SECRET_KEY` | JWT signing |
| `OPENAI_API_KEY` / `IPFS_DATASETS_PY_OPENAI_API_KEY` | LLM / realtime paths |
| `POSTGRES_PASSWORD` / `POSTGRES_URL` / `REDIS_URL` | Persistence |
| `GITHUB_TOKEN` / `GH_TOKEN` | Error reporting / CI only when intentionally scoped |

Copy templates carefully:

```bash
cp .env.example .env
# edit secrets; never commit .env
```

---

## 3. Configuration files

| Source | Typical use |
| --- | --- |
| `.env` / process environment | Secrets, feature flags, host binding |
| `~/.ipfs_datasets/cli.json` | Operator CLI defaults (user-local) |
| `config.yaml.example` / `configs.yaml.example` / `sql_configs.yaml.example` | Application YAML **templates**—copy and customize |
| `config/mcp_config.yaml` | MCP-oriented deploy config (`IPFS_DATASETS_CONFIG` in Docker samples) |
| TOML under `config/` / module loaders | Legacy/module-specific; prefer explicit paths in automation |

Example CLI JSON:

```json
{
  "host": "127.0.0.1",
  "port": "8899",
  "gateway": "https://ipfs.io"
}
```

YAML examples are **not** live secrets and are not a complete substitute for the `IPFS_DATASETS*` env family.

### Process initialization

```python
from ipfs_datasets_py import initialize, RouterDeps

deps = RouterDeps()
initialize(deps=deps, register_symai_engines=False)
```

Import alone is not a substitute for `initialize()` when shared accelerate/IPFS clients must be process-scoped.

---

## 4. Profiles: base, capability, offline, unavailable

### Base / library embed

```bash
export IPFS_DATASETS_AUTO_INSTALL=false
# leave ENABLE_* import flags unset
python -c "import ipfs_datasets_py"
```

No runtime pip; optional features remain **unavailable** until extras and tools are installed.

### Capability-enabled host

```bash
pip install -e '.[vectors,file_conversion,theorem-provers,api]'
export IPFS_DATASETS_PY_ENABLE_MCP_IMPORTS=1   # only if MCP import-time surface is required
```

Install matching **optional** extras and system tools first ([installation.md](installation.md)).

### Offline / air-gapped

```bash
export IPFS_DATASETS_AUTO_INSTALL=0
export IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS=0
export IPFS_DATASETS_AUTO_INSTALL_OFFLINE=1
export IPFS_DATASETS_AUTO_INSTALL_WHEELHOUSE=/media/wheels
```

Only pre-provisioned wheels and local prover roots work; missing artifacts surface as **unavailable**.

### Unavailable vs fail-closed

| Class | Stance |
| --- | --- |
| Optional media / scrape / vector helpers | Soft-disable; clear unavailable status |
| Authz, admissibility, proof, identity integrity | **Fail closed**—never treat as verified or authorized |
| P2P cache without a real shared secret | Prefer disable (`IPFS_DATASETS_PY_CACHE_DISABLE_TASK_P2P`) over weak secrets |

---

## 5. Security and platform caveats (preserve)

| Topic | Guidance |
| --- | --- |
| Default-on auto-install | Disable in production/CI; bake extras into images |
| Native provers / sudo | No implicit sudo; pin executables; install receipts are environment evidence only |
| Network binds | Prefer localhost + reverse proxy + auth; avoid open `0.0.0.0` admin surfaces without protection |
| Path safety | Set `IPFS_DATASETS_SAFE_ROOT`; avoid world-writable shared roots |
| Error reporting | `ERROR_REPORTING_ENABLED` + GitHub tokens may leak stack traces—scrub secrets first |
| Platform GPU | `CUDA_VISIBLE_DEVICES` / `ENABLE_GPU` select devices; they do not install CUDA (see [installation.md](installation.md) GPU section) |

Full security section: [CONFIGURATION_REFERENCE.md](guides/installation/CONFIGURATION_REFERENCE.md) §6 · [SECRETS_AND_CREDENTIALS.md](guides/security/SECRETS_AND_CREDENTIALS.md).

---

## 6. Operator quick recipes

### Safe CI / benchmark

```bash
export IPFS_DATASETS_PY_MINIMAL_IMPORTS=1
export IPFS_DATASETS_AUTO_INSTALL=0
export IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS=0
export IPFS_DATASETS_PY_LOG_DEDUP=1
```

### Dev workstation

```bash
# auto-install remains default-on after import unless you override
pip install -e '.[vectors,file_conversion,theorem-provers,lazy]'
```

### Production API host

```bash
export IPFS_DATASETS_AUTO_INSTALL=false
export IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS=0
export IPFS_DATASETS_SAFE_ROOT=/var/lib/ipfs_datasets/safe
# inject JWT_SECRET_KEY, DB URLs, API keys from a secret manager
```

### Smoke checks

```bash
# IPFS API (when a local daemon is expected)
curl -s -X POST http://127.0.0.1:5001/api/v0/version

# Package import under hermetic policy
IPFS_DATASETS_AUTO_INSTALL=false python -c "import ipfs_datasets_py; print('ok')"
```

---

## 7. What this page replaced

| Stale content | Current guidance |
| --- | --- |
| Sparse env lists without precedence | Precedence model + `IPFS_DATASETS*` family |
| Incomplete coverage of auto-install / provers / offline | Profiles for base, optional capability, offline, unavailable |
| Placeholder secrets-as-docs | Templates + secrets guidance; no invented orgs |
| One-off YAML as the only story | Env > file > default; YAML examples as templates |

---

## 8. Next steps

| Goal | Go to |
| --- | --- |
| Full env catalog and security detail | [CONFIGURATION_REFERENCE.md](guides/installation/CONFIGURATION_REFERENCE.md) |
| Install base / optional extras / native tools | [installation.md](installation.md) · [CAPABILITY_INSTALLATION.md](guides/installation/CAPABILITY_INSTALLATION.md) |
| Performance tuning | [guides/performance_optimization.md](guides/performance_optimization.md) (when present) |
| Security governance | [guides/security/](guides/security/) |
| Architecture init / routers | [DEPENDENCY_AND_INITIALIZATION.md](architecture/DEPENDENCY_AND_INITIALIZATION.md) |
| Deployment samples | [guides/deployment/](guides/deployment/), `docker/` |
