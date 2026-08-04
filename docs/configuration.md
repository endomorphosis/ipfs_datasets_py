# Configuration Guide

| Field | Value |
| --- | --- |
| Interface | `ConfigurationGuide@1` |
| Task | `IPFSDOC-091` |
| Status | `canonical` (root user entry) |
| Owner | user-docs |
| Source of truth | package env/`ipfs_datasets_cli.py` / routers; detailed [CONFIGURATION_REFERENCE](guides/installation/CONFIGURATION_REFERENCE.md) |
| Last verified | 2026-08-03 |
| Audience | end-user, operator, developer, security reviewer |
| Related | [CONFIGURATION_REFERENCE.md](guides/installation/CONFIGURATION_REFERENCE.md), [CAPABILITY_INSTALLATION.md](guides/installation/CAPABILITY_INSTALLATION.md), [installation.md](installation.md), [SECRETS_AND_CREDENTIALS.md](guides/security/SECRETS_AND_CREDENTIALS.md) |

This page is the **short root route** for configuring `ipfs_datasets_py`: precedence, safe defaults, and environment profiles. The full environment catalog, file inventory, and security consequences live in [CONFIGURATION_REFERENCE](guides/installation/CONFIGURATION_REFERENCE.md). Install extras and native tools: [installation.md](installation.md) and [CAPABILITY_INSTALLATION](guides/installation/CAPABILITY_INSTALLATION.md).

## Precedence model

Subsystems share one rule of thumb: **more specific overrides less specific**, and **runtime/process flags beat files**.

| Layer (highest → lowest) | Examples |
| --- | --- |
| CLI flags | `--host`, `--port`, `--gateway`, `--config` |
| Process environment | `IPFS_DATASETS_*`, `IPFS_HOST`, secrets |
| User / project config files | `~/.ipfs_datasets/cli.json`, copied YAML/`.env` |
| Built-in defaults | e.g. CLI host `127.0.0.1`, port `8899` |

When two env aliases exist, **code-defined order** wins (e.g. HTTP gateway prefers `IPFS_HTTP_GATEWAY` then `IPFS_DATASETS_IPFS_GATEWAY`).

### CLI dashboard / gateway

| Setting | Precedence |
| --- | --- |
| Host / port | CLI → `IPFS_DATASETS_HOST` / `IPFS_DATASETS_PORT` → `~/.ipfs_datasets/cli.json` (or `--config` / `IPFS_DATASETS_CLI_CONFIG`) → defaults |
| IPFS HTTP gateway | `--gateway` → `IPFS_HTTP_GATEWAY` or `IPFS_DATASETS_IPFS_GATEWAY` → config JSON `gateway` → unset |
| Config path | `--config` → `IPFS_DATASETS_CLI_CONFIG` → `~/.ipfs_datasets/cli.json` |

```json
{
  "host": "127.0.0.1",
  "port": "8899",
  "gateway": "https://ipfs.io"
}
```

### Auto-install and hermetic import

| Layer | Role |
| --- | --- |
| Explicit env before import | Wins when set |
| Package defaults | If `IPFS_DATASETS_AUTO_INSTALL` is **unset**, import may set it to `"true"` |
| Minimal / benchmark | `IPFS_DATASETS_PY_MINIMAL_IMPORTS=1` or `IPFS_DATASETS_PY_BENCHMARK=1` force hermetic behavior |

**Security:** default-on auto-install can run `pip` on first feature use. Production and CI should set `IPFS_DATASETS_AUTO_INSTALL=false` (or minimal-import modes) **before** import.

### IPFS backend selection (conceptual)

1. Forced `IPFS_DATASETS_PY_IPFS_BACKEND`
2. Enabled optional providers (`IPFS_DATASETS_PY_ENABLE_IPFS_KIT`, `…_HTTPAPI` + host, `…_ACCELERATE`)
3. Local Kubo CLI (`IPFS_DATASETS_PY_KUBO_CMD`, default `ipfs`)
4. Feature degradation when nothing usable is available → treat IPFS-backed paths as **unavailable** rather than “working offline by magic”

`IPFS_KIT_DISABLE` hard-disables kit bootstrap.

### Theorem-prover resolution

1. Explicit `IPFS_DATASETS_PY_<PROVER>_EXECUTABLE`
2. `PATH` and user-local root (`IPFS_DATASETS_PY_EXTERNAL_PROVER_ROOT`)
3. Lazy installer or org `…_INSTALL_COMMAND` if allowed
4. Unavailable / blocked / failed — **never** “proven”

## Configuration sources

| Source | Typical use | Notes |
| --- | --- | --- |
| `.env` / process environment | Secrets, feature flags, binds | Highest practical deploy control; never commit real secrets |
| `~/.ipfs_datasets/cli.json` | Operator CLI defaults | User-local |
| `config.yaml.example`, `configs.yaml.example`, `sql_configs.yaml.example` | Application YAML sketches | Copy and customize |
| `config/mcp_config.yaml` + `IPFS_DATASETS_CONFIG` | MCP / Docker samples | Deploy wiring, not universal for every subsystem |
| Module TOML / package loaders | Legacy or module-specific | Prefer explicit paths in automation |

```bash
cp .env.example .env
# edit hosts and secrets; never commit .env
```

YAML examples are **templates**, not live credentials. Prefer a secret manager over world-readable `.env` in production.

### Explicit process initialization

```python
from ipfs_datasets_py import initialize, RouterDeps

deps = RouterDeps()
initialize(deps=deps, register_symai_engines=False)
```

Import alone is not a substitute for `initialize()` when shared accelerate/IPFS clients must be process-scoped.

## Environment profiles

### Base / library embed

```bash
export IPFS_DATASETS_AUTO_INSTALL=false
# leave ENABLE_* import flags unset unless required
python -c "import ipfs_datasets_py"
```

No runtime pip; heavy stacks stay off until explicitly installed and imported. Optional features remain **optional** or **unavailable**.

### Capability-enabled host

```bash
pip install -e '.[vectors,file_conversion,theorem-provers,api]'
export IPFS_DATASETS_PY_ENABLE_MCP_IMPORTS=1   # only if MCP import-time surface is required
# optional: export IPFS_DATASETS_PY_IPFS_BACKEND=…
```

Installed extras + system tools enable feature paths. Capability probes still do **not** equal production attestation or proof.

### Offline / air-gapped

```bash
export IPFS_DATASETS_AUTO_INSTALL=0
export IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS=0
export IPFS_DATASETS_AUTO_INSTALL_OFFLINE=1
export IPFS_DATASETS_AUTO_INSTALL_WHEELHOUSE=/path/to/wheels
```

Only pre-provisioned wheels and local prover roots work; missing artifacts surface as **unavailable**.

### Unavailable vs fail-closed trust

| Class | Stance |
| --- | --- |
| Optional media / scrape / vector helpers | Soft-disable or clear **unavailable** status |
| Authz, admissibility, proof, identity integrity | **Fail closed** — never treat as verified or authorized |
| P2P cache without a real shared secret | Prefer disable (`IPFS_DATASETS_PY_CACHE_DISABLE_TASK_P2P`) over weak secrets |

## High-signal environment variables

Truth values are generally `1` / `true` / `yes` / `on` (case-insensitive) unless a subsystem documents otherwise. Full catalog: CONFIGURATION_REFERENCE §3.

| Area | Variables |
| --- | --- |
| Hermetic import | `IPFS_DATASETS_PY_MINIMAL_IMPORTS`, `IPFS_DATASETS_PY_BENCHMARK`, `IPFS_DATASETS_PY_ENABLE_*_IMPORTS` |
| Auto / offline pip | `IPFS_DATASETS_AUTO_INSTALL`, `IPFS_DATASETS_AUTO_INSTALL_OFFLINE`, `IPFS_DATASETS_AUTO_INSTALL_WHEELHOUSE` |
| CLI / gateway | `IPFS_DATASETS_HOST`, `IPFS_DATASETS_PORT`, `IPFS_DATASETS_CLI_CONFIG`, `IPFS_HTTP_GATEWAY` |
| IPFS routers | `IPFS_DATASETS_PY_IPFS_BACKEND`, `IPFS_DATASETS_PY_ENABLE_IPFS_*`, `IPFS_DATASETS_PY_KUBO_CMD`, `IPFS_KIT_DISABLE` |
| Provers | `IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS`, `IPFS_DATASETS_PY_EXTERNAL_PROVER_ROOT`, `IPFS_DATASETS_PY_<PROVER>_EXECUTABLE`, `IPFS_DATASETS_PY_ALLOW_SUDO_FOR_PROVERS` (default deny) |
| Path safety | `IPFS_DATASETS_SAFE_ROOT` |
| Secrets (examples) | `JWT_SECRET_KEY`, `OPENAI_API_KEY` / `IPFS_DATASETS_PY_OPENAI_API_KEY`, `POSTGRES_*`, `IPFS_DATASETS_PY_CACHE_P2P_SHARED_SECRET` |

## Security caveats (preserve in ops)

- **Default-on auto-install** mutates environments — disable in production images.
- **Native prover install** may download/build under a user-local root; keep sudo allow flags off unless deliberately reviewed.
- **Secrets in env and P2P aliases** can fall back to GitHub tokens in some cache paths — prefer dedicated P2P secrets; never log full env dumps.
- **Network binds** (`0.0.0.0`, open IPFS API) expose admin surfaces — prefer localhost + reverse proxy + auth for non-lab use.
- Rolling back code **without** rotating secrets does not undo credential exposure.

Details: [CONFIGURATION_REFERENCE §6](guides/installation/CONFIGURATION_REFERENCE.md), [SECRETS_AND_CREDENTIALS](guides/security/SECRETS_AND_CREDENTIALS.md).

## Operator hygiene

| Goal | Action |
| --- | --- |
| Stop runtime pip | `IPFS_DATASETS_AUTO_INSTALL=false` (and/or minimal imports) |
| Stop native prover downloads | `IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS=0` |
| Clear CLI defaults | Remove `~/.ipfs_datasets/cli.json` |
| Roll back Python env | Recreate the venv; reinstall only needed extras |
| Remove prover tree | Delete external prover root **intentionally** |
| Revoke secrets | Rotate keys/passwords/tokens; update secret store |

## Related deep dives

- Performance tuning: [PERFORMANCE_TUNING_GUIDE](PERFORMANCE_TUNING_GUIDE.md) (when present) / domain guides
- GraphRAG extraction fields: [optimizers/graphrag/CONFIGURATION_REFERENCE](optimizers/graphrag/CONFIGURATION_REFERENCE.md) (domain-specific, not package root config)
- Deployment: [deployment.md](deployment.md), [Docker](deployment/DOCKER_DEPLOYMENT_GUIDE.md)
- Architecture: [DEPENDENCY_AND_INITIALIZATION](architecture/DEPENDENCY_AND_INITIALIZATION.md), [ADR-002](architecture/decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md)

## Next steps

- [Installation guide](installation.md) — base and optional install routes
- [CAPABILITY_INSTALLATION](guides/installation/CAPABILITY_INSTALLATION.md) — extras, natives, offline
- [CONFIGURATION_REFERENCE](guides/installation/CONFIGURATION_REFERENCE.md) — full env and file map
- [User guide](user_guide.md) · [Getting started](getting_started.md)
