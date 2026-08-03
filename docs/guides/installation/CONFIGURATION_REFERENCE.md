# Configuration Reference

| Field | Value |
| --- | --- |
| Interface | `ConfigurationReference@1` |
| Task | `IPFSDOC-063` |
| Status | `canonical` |
| Owner | user-docs |
| Source of truth | `ipfs_datasets_py/__init__.py`; `ipfs_datasets_cli.py`; `ipfs_datasets_py/auto_installer.py`; `ipfs_datasets_py/ipfs_backend_router.py`; `ipfs_datasets_py/router_deps.py`; `ipfs_datasets_py/logic/external_provers/lazy_installer.py`; `.env.example`; `config.yaml.example`; `configs.yaml.example`; `setup.py` install hooks |
| Last verified | 2026-08-03 |
| Audience | developer, operator, security reviewer |
| Related | [CAPABILITY_INSTALLATION.md](CAPABILITY_INSTALLATION.md), [DEPENDENCY_AND_INITIALIZATION.md](../../architecture/DEPENDENCY_AND_INITIALIZATION.md), [SECRETS_AND_CREDENTIALS.md](../security/SECRETS_AND_CREDENTIALS.md), [ADR-002](../../architecture/decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md) |

## 1. Purpose

This reference documents **how configuration is resolved** for `ipfs_datasets_py`: environment variables (especially the `IPFS_DATASETS*` family), config files, CLI flags, install-time hooks, and the security consequences of each layer. Values and names are taken from current code and packaging—not from obsolete singular extras or placeholder organizations.

For **what to install** (extras, console scripts, native tools), use [CAPABILITY_INSTALLATION.md](CAPABILITY_INSTALLATION.md).

## 2. Precedence model

Different subsystems implement the same general idea: **more specific overrides less specific**, and **runtime/process flags beat files**.

### 2.1 CLI dashboard / gateway defaults

Documented and implemented in `ipfs_datasets_cli.py`:

| Setting | Precedence (highest → lowest) |
| --- | --- |
| Host / port | CLI flags (`--host` / `--port`) → `IPFS_DATASETS_HOST` / `IPFS_DATASETS_PORT` → `~/.ipfs_datasets/cli.json` (or path from `--config` / `IPFS_DATASETS_CLI_CONFIG`) → hardcoded `127.0.0.1` / `8899` |
| IPFS HTTP gateway | Explicit `--gateway` → `IPFS_HTTP_GATEWAY` or `IPFS_DATASETS_IPFS_GATEWAY` → config JSON `gateway` → `None` |
| Config path | `--config` path → `IPFS_DATASETS_CLI_CONFIG` → `~/.ipfs_datasets/cli.json` |

Example CLI config file:

```json
{
  "host": "127.0.0.1",
  "port": "8899",
  "gateway": "https://ipfs.io"
}
```

### 2.2 Package import and auto-install policy

| Layer | Role |
| --- | --- |
| Explicit env at process start | Wins when set before import |
| Package root defaults | If `IPFS_DATASETS_AUTO_INSTALL` is **unset**, import sets it to `"true"`; same pattern for `IPFS_KIT_AUTO_INSTALL_DEPS` |
| Minimal / benchmark modes | `IPFS_DATASETS_PY_MINIMAL_IMPORTS=1` or `IPFS_DATASETS_PY_BENCHMARK=1` force hermetic behavior and disable runtime install regardless of soft defaults |
| Feature call-site | `ensure_module` / router factories may still refuse install under offline/minimal policy |

**Security consequence:** the default-on auto-install favors developer experience. Production and CI **must set** `IPFS_DATASETS_AUTO_INSTALL=false` (or minimal-import modes) before import if surprise `pip` mutation is unacceptable.

### 2.3 IPFS backend selection

Router selection is configuration-driven (see `ipfs_backend_router` and architecture storage docs). Conceptual **precedence**:

1. Explicit `IPFS_DATASETS_PY_IPFS_BACKEND` (force named backend)
2. Enabled optional providers (`IPFS_DATASETS_PY_ENABLE_IPFS_KIT`, `…_HTTPAPI` + `IPFS_HOST`, `…_ENABLE_IPFS_ACCELERATE`)
3. Local Kubo CLI (`IPFS_DATASETS_PY_KUBO_CMD`, default `ipfs`)
4. Feature degradation when nothing usable is available

`IPFS_KIT_DISABLE` hard-disables kit bootstrap. Successful kit auto-install may set enable flags as a side effect—treat that as process mutation.

### 2.4 Config files vs environment

| Source | Typical use | Notes |
| --- | --- | --- |
| `.env` / process environment | Secrets, feature flags, host binding | Highest practical control for deployment; never commit real secrets |
| `~/.ipfs_datasets/cli.json` | Operator CLI defaults | User-local; not package-managed |
| `config.yaml.example` / `configs.yaml.example` / `sql_configs.yaml.example` | Example application YAML | Copy and customize; many runtime modules also accept env overrides |
| TOML under `config/` / package `config.toml` | Legacy/module-specific loaders (`ipfs_datasets_py.config`) | Path search is module-specific—prefer explicit paths in automation |
| `IPFS_DATASETS_CONFIG` (Docker compose samples) | Point containers at `mcp_config.yaml` | Deployment wiring, not universal for all subsystems |
| `DATABASE_PATH`, `POSTGRES_*`, `REDIS_URL` (`.env.example`) | Dashboard / persistence | Credentials are secrets—see §6 |

**General rule:** for a given key, **CLI flag > environment variable > config file > built-in default**, unless a subsystem documents a narrower order. When two env aliases exist, code-defined order wins (e.g. gateway prefers `IPFS_HTTP_GATEWAY` then `IPFS_DATASETS_IPFS_GATEWAY`).

### 2.5 Theorem-prover resolution

1. Explicit `IPFS_DATASETS_PY_<PROVER>_EXECUTABLE`
2. `PATH` and user-local external prover root (`IPFS_DATASETS_PY_EXTERNAL_PROVER_ROOT`)
3. Lazy installer (if allowed) or custom `IPFS_DATASETS_PY_<SOLVER>_INSTALL_COMMAND`
4. Unavailable / blocked / failed phases—not “proven”

Org-managed install commands always take operator responsibility for checksum and version review.

## 3. Environment variable catalog

Names below appear in current code or first-party examples. Truthy values are generally `1` / `true` / `yes` / `on` (case-insensitive) unless noted.

### 3.1 Hermetic import and heavy stacks

| Variable | Default / unset behavior | Effect |
| --- | --- | --- |
| `IPFS_DATASETS_PY_MINIMAL_IMPORTS` | off | Hermetic imports; stub installer; optional stacks stay off |
| `IPFS_DATASETS_PY_BENCHMARK` | off | Same minimal treatment as above |
| `IPFS_DATASETS_PY_ENABLE_MCP_IMPORTS` | off | Allow MCP-related import-time exports |
| `IPFS_DATASETS_PY_ENABLE_FASTAPI_IMPORTS` | off | Allow FastAPI-related import-time exports |
| `IPFS_DATASETS_PY_ENABLE_LLM_IMPORTS` | off | Allow transformers/LLM import-time paths |
| `IPFS_DATASETS_PY_ENABLE_FINANCE_DASHBOARD_IMPORTS` | off | Allow finance dashboard import-time exports |
| `IPFS_DATASETS_PY_WARN_OPTIONAL_IMPORTS` | off | Emit warnings for missing optional deps |
| `IPFS_DATASETS_PY_LOG_DEDUP` | `0` | Deduplicate root logging handlers |
| `IPFS_DATASETS_PY_USE_SYMAI_ENGINE_ROUTER` | off | Best-effort SyMAI engine registration during `initialize()` |

### 3.2 Auto / lazy Python installation

| Variable | Default / unset behavior | Effect |
| --- | --- | --- |
| `IPFS_DATASETS_AUTO_INSTALL` | set to `true` on import if unset | Allow runtime `pip` installs |
| `IPFS_AUTO_INSTALL` | alias | Compatibility alias for auto-install |
| `IPFS_KIT_AUTO_INSTALL_DEPS` | set to `1` on import if unset | Kit-side dependency install policy |
| `IPFS_DATASETS_AUTO_INSTALL_OFFLINE` | off | Offline/wheelhouse pip mode |
| `IPFS_DATASETS_AUTO_INSTALL_WHEELHOUSE` | unset | Local wheel directory |
| `IPFS_DATASETS_PIP_TIMEOUT` | installer default | Pip timeout (bounded 30–3600 s in lazy installer) |
| `IPFS_DATASETS_INSTALL_LOCK_TIMEOUT` | installer default | Cross-worker install lock wait |
| `IPFS_DATASETS_INSTALL_RETRY_SECONDS` | installer default | Cooldown after failed install |
| `IPFS_INSTALL_VERBOSE` | off | Installer diagnostics |
| `IPFS_DATASETS_ENSURE_INSTALLER` | off | May re-check repository installer currency (not the same as feature lazy install) |
| `IPFS_DATASETS_PROJECT_ROOT` / `IPFS_DATASETS_LOCAL_BIN` / `IPFS_DATASETS_LOCAL_DEPS` / `IPFS_DATASETS_NPM_PREFIX` | layout defaults | Local bin/deps layout for bootstrap helpers |
| `IPFS_DATASETS_AUTO_INSTALL_IPFS_KIT` | falls back to general auto-install | On-demand kit bootstrap |
| `IPFS_DATASETS_PY_INCLUDE_VCS_DEPENDENCIES` | on (`1`) | Include kit/accelerate/libp2p VCS deps in `setup.py` install |

### 3.3 Install-time packaging hooks

| Variable | Default | Effect |
| --- | --- | --- |
| `IPFS_DATASETS_PY_AUTO_NLTK_DOWNLOAD` | on | Best-effort NLTK resource download after install/develop |
| `IPFS_DATASETS_PY_NLTK_DOWNLOAD_DIR` | unset | Download target; else first `NLTK_DATA` path |
| `IPFS_DATASETS_PY_NLTK_DOWNLOAD_QUIET` | on | Quiet NLTK downloads |
| `IPFS_DATASETS_PY_AUTO_GROTH16_BUILD` | on | Chmod bundled Groth16 binary or build via Cargo when available |

### 3.4 IPFS, cache, and routers

| Variable | Role |
| --- | --- |
| `IPFS_DATASETS_HOST` / `IPFS_DATASETS_PORT` | CLI/dashboard defaults |
| `IPFS_DATASETS_CLI_CONFIG` | Path to CLI JSON config |
| `IPFS_HTTP_GATEWAY` / `IPFS_DATASETS_IPFS_GATEWAY` | HTTP gateway for content fetch helpers |
| `IPFS_HOST` / `IPFS_API_*` / `IPFS_GATEWAY` (examples) | Daemon/API endpoints in `.env.example` and deploy samples |
| `IPFS_DATASETS_PY_IPFS_BACKEND` | Force backend name |
| `IPFS_DATASETS_PY_ENABLE_IPFS_KIT` | Enable kit backend path |
| `IPFS_DATASETS_PY_ENABLE_IPFS_HTTPAPI` | Enable HTTP API backend |
| `IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE` | Enable accelerate IPFS path |
| `IPFS_DATASETS_PY_KUBO_CMD` | Kubo CLI name/path (default `ipfs`) |
| `IPFS_DATASETS_PY_ROUTER_CACHE` | Cache resolved backends (`0` disables) |
| `IPFS_DATASETS_PY_IPFS_CACHE_DIR` | IPFS-related cache directory |
| `IPFS_KIT_DISABLE` | Hard-disable kit |
| `IPFS_KIT_INTEGRATION` | Integration mode for getter/pinner helpers |
| `IPFS_KIT_MCP_URL` | Kit MCP URL defaulting near localhost:5001 |
| `IPFS_DATASETS_PY_CACHE_P2P_SHARED_SECRET` (+ accelerate aliases) | P2P cache shared secret |
| `CACHE_P2P_SHARED_SECRET` | Additional alias for P2P secret |
| `IPFS_DATASETS_PY_CACHE_DISABLE_TASK_P2P` (+ aliases) | Disable task P2P cache |
| `IPFS_DATASETS_PY_REMOTE_CACHE_NETWORK` / `…_PORT` / `…_BOOTSTRAP` | Remote cache network |
| `IPFS_DATASETS_PY_REMOTE_CACHE_P2P_TASKS` | Opt-in remote P2P task cache |
| `IPFS_DATASETS_PY_TASK_P2P_REMOTE_MULTIADDR` / `…_PEER_ID` (+ accelerate aliases) | Remote peer addressing |
| `IPFS_DATASETS_SAFE_ROOT` | Bound CAR/path operations to a safe root (path-traversal reduction) |
| `IPFS_DATASETS_CONFIG` | Deploy-time path to MCP/config YAML |
| `IPFS_ACCELERATE_ENABLED` | Gate accelerate availability helpers |

### 3.5 Theorem provers and formal methods

| Variable | Role |
| --- | --- |
| `IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS` | Master switch for first-use native install |
| `IPFS_DATASETS_PY_LAZY_INSTALL_<PROVER>` | Per-prover enable/disable |
| `IPFS_DATASETS_PY_AUTO_INSTALL_PROVERS` / `…_ALL_PROVERS` / portfolio lists | Managed preflight install |
| `IPFS_DATASETS_PY_AUTO_INSTALL_PROVER_PORTFOLIOS` | Explicit portfolio list |
| `IPFS_DATASETS_PY_LAZY_INSTALL_STRICT` / `IPFS_DATASETS_PY_PROVER_INSTALL_STRICT` | Raise on installer failure |
| `IPFS_DATASETS_PY_ALLOW_SUDO_FOR_PROVERS` | Allow interactive sudo (**default deny**) |
| `IPFS_DATASETS_PY_EXTERNAL_PROVER_ROOT` | User-local solver tree (default under `~/.local/share/ipfs_datasets_py/theorem-provers`) |
| `IPFS_DATASETS_PY_<PROVER>_EXECUTABLE` | Pin binary path |
| `IPFS_DATASETS_PY_<SOLVER>_INSTALL_COMMAND` | Org-managed install (Apalache, Tamarin, Maude, ProVerif, CVC5, Coq, …) |
| `IPFS_DATASETS_PY_LEAN_TOOLCHAIN` | Reviewed Lean toolchain selection |
| `LEANSTRAL_AUDIT_PROVER_PORTFOLIO` | Worker preflight portfolio override |

Python binding extras remain separate: install `theorem-provers` / `requirements-theorem-provers.txt` for `z3-solver`, `cvc5`, `pysmt`, etc. Native CLIs are **not** pip packages.

### 3.6 Messaging, SMS, and realtime (high sensitivity)

| Variable | Role |
| --- | --- |
| `IPFS_DATASETS_SMS_BRIDGE_DB_PATH` | SMS bridge SQLite path |
| `IPFS_DATASETS_SMS_BRIDGE_ARCHIVE_EXPORT_ROOT` | Archive export root |
| `IPFS_DATASETS_VOICE_MEDIA_ROOT` | Voice media root |
| `IPFS_DATASETS_SMS_TWILIO_AUTO_REPLY_TEXT` | Twilio auto-reply text |
| `IPFS_DATASETS_TWILIO_GATHER_*` | Gather timeouts |
| `IPFS_DATASETS_OPENAI_REALTIME_*` | Realtime model/voice/WS/instructions/token limits |
| `IPFS_DATASETS_PY_OPENAI_API_KEY` | OpenAI API key for realtime path |

### 3.7 Dashboard / example `.env` keys

From `.env.example` (illustrative—verify consumers before relying on every key):

| Variable | Role |
| --- | --- |
| `MCP_DASHBOARD_HOST` / `MCP_DASHBOARD_PORT` | Dashboard bind |
| `JWT_SECRET_KEY` | JWT signing secret |
| `DATABASE_PATH` | Local DB path (`~/.ipfs_datasets/data.db`) |
| `POSTGRES_PASSWORD` / `POSTGRES_URL` | Postgres credentials |
| `REDIS_URL` | Redis |
| `LOG_LEVEL` / `LOG_PATH` | Logging |
| `FAISS_INDEX_PATH` / `QDRANT_HOST` / `QDRANT_PORT` | Vector store endpoints |
| `CUDA_VISIBLE_DEVICES` / `ENABLE_GPU` | GPU selection |
| `ENABLE_AUTH` | Auth gate |
| `OPENAI_API_KEY` | LLM provider |
| `ERROR_REPORTING_ENABLED` / `GITHUB_REPOSITORY` / `GITHUB_TOKEN` / `GH_TOKEN` | Error reporting to GitHub |

### 3.8 Domain and product flags (selected)

| Variable | Role |
| --- | --- |
| `IPFS_DATASETS_PROFILE_G_DB` | Durable Profile G evidence DB path |
| `IPFS_DATASETS_LEGAL_FETCH_CACHE_*` | Legal scraper fetch cache controls |
| `IPFS_DATASETS_CLOUDFLARE_*` | Cloudflare crawl credentials and limits |
| `IPFS_DATASETS_PY_USE_EMBEDDING_ADAPTER` | Embedding adapter path selection |
| `IPFS_DATASETS_AUTO_INSTALL_TEST_DEPS` | Test harness auto-deps (`conftest.py`) |

## 4. Configuration files

### 4.1 `.env`

```bash
cp .env.example .env
# edit secrets and hosts; never commit .env
```

Use process supervisors or secret managers in production instead of long-lived world-readable `.env` files.

### 4.2 CLI config JSON

Path resolution: `--config` → `IPFS_DATASETS_CLI_CONFIG` → `~/.ipfs_datasets/cli.json`.

### 4.3 YAML examples

- `config.yaml.example` — logic/prover oriented defaults (timeouts, cache, rate limits, monitoring)
- `configs.yaml.example` / `sql_configs.yaml.example` — additional service/SQL sketches
- `config/mcp_config.yaml` — MCP-oriented deploy config referenced by Docker compose via `IPFS_DATASETS_CONFIG`

Treat examples as **templates**, not live secrets.

### 4.4 Explicit process initialization

```python
from ipfs_datasets_py import initialize, RouterDeps

deps = RouterDeps()
initialize(deps=deps, register_symai_engines=False)
```

Import is not a substitute for `initialize()` when shared accelerate/IPFS clients must be process-scoped.

## 5. Profiles: base, capability, offline, unavailable

### 5.1 Base / library embed

```bash
export IPFS_DATASETS_AUTO_INSTALL=false
# leave ENABLE_* import flags unset
python -c "import ipfs_datasets_py"
```

Implication: no runtime pip; heavy stacks absent until explicitly installed and imported.

### 5.2 Capability-enabled host

```bash
pip install -e '.[vectors,file_conversion,theorem-provers,api]'
export IPFS_DATASETS_PY_ENABLE_MCP_IMPORTS=1   # only if MCP import-time surface is required
export IPFS_DATASETS_PY_IPFS_BACKEND=…         # if forcing a backend
```

Implication: features that match installed extras and system tools can run; probes still do not equal production attestation.

### 5.3 Offline / air-gapped

```bash
export IPFS_DATASETS_AUTO_INSTALL=0
export IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS=0
export IPFS_DATASETS_AUTO_INSTALL_OFFLINE=1
export IPFS_DATASETS_AUTO_INSTALL_WHEELHOUSE=/media/wheels
```

Implication: only pre-provisioned wheels and local prover roots work; missing artifacts surface as unavailable, not silent success.

### 5.4 Unavailable degradation vs fail-closed trust

| Class | Configuration stance | Runtime stance |
| --- | --- | --- |
| Optional media/scrape/vector helpers | Missing extra/env | Soft-disable, clear unavailable status |
| Authz, admissibility, proof, identity integrity | Missing validator/prover/secret | **Fail closed**—never treat as verified or authorized |
| P2P cache without shared secret | Misconfigured secret chain | Risk of open or broken trust—prefer disable (`…_DISABLE_TASK_P2P`) over weak secrets |

## 6. Security consequences

### 6.1 Default-on auto-install

- **Risk:** process may execute `pip` and mutate the environment on first feature use.
- **Mitigation:** set `IPFS_DATASETS_AUTO_INSTALL=false` before import; use locked images + wheelhouses; prefer explicit extras at build time.

### 6.2 Native prover install and sudo

- **Risk:** downloads and builds under the user-local prover root; optional OPAM/package-manager steps.
- **Mitigation:** keep `IPFS_DATASETS_PY_ALLOW_SUDO_FOR_PROVERS` unset; use managed CLI with reviewed portfolios; pin executables; treat install receipts as **environment evidence only**, not proofs.

### 6.3 Secrets in environment and P2P aliases

Several cache paths accept a chain of secrets, including falling back to `GH_TOKEN` / `GITHUB_TOKEN` when P2P shared secrets are unset. That coupling is convenient for CI but dangerous if tokens are overly privileged.

- Prefer dedicated `IPFS_DATASETS_PY_CACHE_P2P_SHARED_SECRET`.
- Scope GitHub tokens tightly; never log env dumps in CI artifacts.
- Rotate any token that may have been used as a cache shared secret.

### 6.4 JWT, API keys, Twilio, Cloudflare

- `JWT_SECRET_KEY`, `OPENAI_API_KEY`, `IPFS_DATASETS_PY_OPENAI_API_KEY`, Postgres passwords, Cloudflare tokens, and SMS bridge state paths control money, privacy, and account takeover surface.
- Store outside the repository; inject at runtime; restrict filesystem permissions on `DATABASE_PATH` and SMS/voice roots.

### 6.5 Network-facing binds

- `MCP_DASHBOARD_HOST=0.0.0.0` and open IPFS API ports expose administrative surfaces.
- Prefer localhost binds behind reverse proxies with auth (`ENABLE_AUTH`) for non-lab use.

### 6.6 Path safety

- `IPFS_DATASETS_SAFE_ROOT` and careful CAR/path handling reduce path-traversal risk. Do not point safe roots at world-writable shared directories without access control.

### 6.7 Error reporting

- `ERROR_REPORTING_ENABLED` plus `GITHUB_TOKEN` may create issues containing stack traces. Ensure no secrets appear in exception messages before enabling.

## 7. Uninstall, rollback, and config hygiene

| Goal | Action |
| --- | --- |
| Stop runtime pip | `IPFS_DATASETS_AUTO_INSTALL=false` (and/or minimal imports) |
| Stop native prover downloads | `IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS=0` |
| Roll back Python env | Recreate venv; `pip uninstall ipfs_datasets_py` |
| Remove prover tree | Delete `IPFS_DATASETS_PY_EXTERNAL_PROVER_ROOT` contents intentionally |
| Clear CLI defaults | Remove `~/.ipfs_datasets/cli.json` |
| Revoke secrets | Rotate API keys, JWT secret, DB passwords, GitHub tokens; update `.env` / secret store |
| Disable P2P cache | Set `IPFS_DATASETS_PY_CACHE_DISABLE_TASK_P2P=1` (and related aliases) |

Rolling back code **without** rotating secrets does not undo credential exposure.

## 8. Quick operator recipes

### 8.1 Safe CI / benchmark

```bash
export IPFS_DATASETS_PY_MINIMAL_IMPORTS=1
export IPFS_DATASETS_AUTO_INSTALL=0
export IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS=0
export IPFS_DATASETS_PY_LOG_DEDUP=1
```

### 8.2 Dev workstation (convenient)

```bash
# auto-install remains default-on after import
pip install -e '.[vectors,file_conversion,theorem-provers,lazy]'
# optional managed provers:
# ipfs-datasets-install-provers --portfolio legal_ir_generation --yes
```

### 8.3 Production API host

```bash
export IPFS_DATASETS_AUTO_INSTALL=false
export IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS=0
export IPFS_DATASETS_PY_ENABLE_FASTAPI_IMPORTS=1   # only if required
export IPFS_DATASETS_SAFE_ROOT=/var/lib/ipfs_datasets/safe
# inject JWT_SECRET_KEY, DB URLs, and API keys from a secret manager
```

## 9. Related documents

- [CAPABILITY_INSTALLATION.md](CAPABILITY_INSTALLATION.md) — extras, scripts, native tools, probes
- [LAZY_DEPENDENCY_INSTALLATION.md](../LAZY_DEPENDENCY_INSTALLATION.md)
- [lazy_theorem_prover_installation.md](../../security_verification/lazy_theorem_prover_installation.md)
- [SECRETS_AND_CREDENTIALS.md](../security/SECRETS_AND_CREDENTIALS.md)
- [STORAGE_CACHING_AND_BACKENDS.md](../../architecture/storage/STORAGE_CACHING_AND_BACKENDS.md)
- [ADR-002 Lazy Optional Capabilities](../../architecture/decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md)
