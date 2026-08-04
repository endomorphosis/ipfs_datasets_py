# Secrets and credentials guide

| Field | Value |
| --- | --- |
| Interface | `SecretsCredentialGuide@1` |
| Task | `IPFSDOC-060` |
| Status | `canonical` |
| Owner | security; operators; mcp-server; optimizers.security |
| Source of truth | `ipfs_datasets_py/mcp_server/secrets_vault.py`; `ipfs_datasets_py/mcp_server/did_key_manager.py`; `ipfs_datasets_py/mcp_server/fastapi_service.py`; `ipfs_datasets_py/mcp_server/server.py` (`_sanitize_error_context`); `ipfs_datasets_py/optimizers/security/secrets_manager.py`; `ipfs_datasets_py/optimizers/security/authentication.py`; `ipfs_datasets_py/processors/legal_data/email_auth.py`; env-gated modules under `messaging/`, `wallet/`, `caching/`, `error_reporting/`; [THREAT_MODEL.md](THREAT_MODEL.md) |
| Last verified | 2026-08-03 |
| Audience | operator, developer, security reviewer, agent |
| Related | [THREAT_MODEL.md](THREAT_MODEL.md), [security_governance.md](security_governance.md), [audit_logging.md](audit_logging.md), MCP [POLICY_AND_AUTHORIZATION.md](../../architecture/mcp/POLICY_AND_AUTHORIZATION.md) |
| Review cadence | when env var names, vault formats, or auth modules change |

> **Hard rules**
>
> 1. **Never put real secrets** in documentation, tests committed to git, issue
>    bodies, screenshots, or example commands with live values.
> 2. Prefer **environment variables**, platform secret stores, or encrypted
>    vaults over plaintext config files in the repository.
> 3. **Redact** credentials in logs, error reports, MCP public views, and
>    telemetry.
> 4. Plan **rotation** and **revocation** before production use.
> 5. Development defaults are **not** production credentials.

---

## 1. Purpose

This guide is the **operator and developer contract** for how
`ipfs_datasets_py` expects credentials to be supplied, stored, redacted,
rotated, revoked, and recovered. It pairs with the system
[THREAT_MODEL.md](THREAT_MODEL.md) (trust boundaries and residual risks).

It inventories **names and channels** of secrets only—**placeholder values**
appear as `<REDACTED>`, `$ENV_NAME`, or documentation fakes such as
`sk-example-not-real`.

---

## 2. Definitions

| Term | Meaning |
| --- | --- |
| **Secret** | High-entropy value that grants access or decrypts data (API keys, tokens, private keys, vault master material) |
| **Credential** | Broader identity material: secrets plus usernames, DIDs, client IDs, non-secret config that becomes sensitive in combination |
| **Injection** | Making a secret available to a process (usually via environment) without embedding it in source |
| **Redaction** | Replacing secret or PII material with placeholders before log/export |
| **Rotation** | Replacing a secret with a new one on a schedule or after exposure, while invalidating the old value |
| **Revocation** | Immediate invalidation at the issuer or local blacklist/revlist without waiting for expiry |
| **Residual risk** | Risk remaining after current controls |

---

## 3. Trust model for credentials

```text
  Platform secret store / human operator
            │
            │  inject (CI secrets, k8s, systemd EnvironmentFile)
            ▼
  Process environment  ◄──── optional SecretsVault.load_into_env()
            │
            ├── FastAPI SECRET_KEY / JWT
            ├── Provider clients (OpenAI, HF, Brave, Discord, Twilio, …)
            ├── GitHub error reporting
            ├── P2P / distributed cache shared secrets
            └── Wallet / messaging bridges
            │
            ▼
  In-memory use only for request lifetime
            │
            ├── Logs / errors ──► redact (never echo raw secret)
            ├── MCP tool results ──► public/redacted views where implemented
            └── Disk vaults ──► encrypted at rest (vault / SecretsManager)
```

| Boundary | Rule |
| --- | --- |
| **Untrusted** | Client-supplied “please use this key” in tool args unless explicitly designed and authorized |
| **Trusted-for-code** | Package code paths that read env/vault |
| **Not trusted-for-leak-prevention alone** | Application logs, third-party model APIs, crash dumps—require redaction and retention policy |
| **External issuer of truth** | Cloud IAM, GitHub, Twilio, etc. for revoke/rotate |

---

## 4. Storage mechanisms (current tree)

### 4.1 Environment variables (primary)

Most modules resolve credentials with `os.environ` / `os.getenv` at runtime.
**Preferred production pattern:**

```bash
# Example only — values are fake placeholders
export SECRET_KEY='<REDACTED-production-secret-key>'
export OPENAI_API_KEY='sk-example-not-real'
```

Do **not** commit `.env` files containing real secrets. If local `.env` files
are used, keep them outside git (ignore rules) and use a secrets manager when
possible.

### 4.2 MCP Secrets Vault (`SecretsVault`)

| Item | Detail |
| --- | --- |
| **Module** | `ipfs_datasets_py.mcp_server.secrets_vault` |
| **Default path** | `~/.ipfs_datasets/secrets_vault.json` |
| **Override** | `IPFS_DATASETS_SECRETS_VAULT_FILE` |
| **Crypto** | AES-256-GCM; key derived via HKDF-SHA256 from Ed25519 seed managed by `DIDKeyManager` |
| **Ops** | `set` / `get` named secrets; `load_into_env()` injects into process environment |
| **Requirements** | `cryptography`; UCAN/DID extras for key derivation path |

**Security notes:**

- Vault file confidentiality depends on **filesystem permissions** and
  protection of the DID private key material.
- Changing HKDF salt/info strings **invalidates** existing ciphertexts (see
  module constants).
- Loading into `os.environ` expands process-local exposure (child processes may
  inherit)—prefer short-lived processes and avoid dumping environ.

### 4.3 Optimizers `SecretsManager`

| Item | Detail |
| --- | --- |
| **Module** | `ipfs_datasets_py.optimizers.security.secrets_manager` |
| **Crypto** | Fernet (symmetric) with key derivation helpers |
| **Features** | Categories, access levels, **expiry** (default 90 days), **rotation/versioning** metadata, audit hooks, path validation |
| **Use** | Application-level secret records (API keys, DB passwords, tokens) when optimizers security stack is in use |

Treat the Fernet master key as a **root secret**: store it in the platform
secret store, not in the same JSON file unencrypted.

### 4.4 Authentication tokens (optimizers)

| Item | Detail |
| --- | --- |
| **Module** | `ipfs_datasets_py.optimizers.security.authentication` |
| **Types** | JWT access/refresh, API keys (`MIN_API_KEY_LENGTH = 32`), bcrypt password hashes |
| **Revocation** | In-memory `TokenBlacklist` (production should use shared store) |
| **Defaults** | Access TTL ~30 minutes; refresh ~7 days (configurable) |

### 4.5 Platform and CI secret stores

| Store | Typical use |
| --- | --- |
| GitHub Actions secrets | `GITHUB_TOKEN` / `GH_TOKEN`, deploy keys—never echo in workflow logs |
| Kubernetes / Docker secrets | Mount as env or files with mode `0400`/`0600` |
| systemd `EnvironmentFile` | MCP service units (`ipfs-datasets-mcp.service`) |
| Cloud KMS / Vault (external) | Recommended for production master keys |

Auto-healing workflows must **not** receive organization secrets beyond least
privilege ([auto_healing_security.md](auto_healing_security.md)).

### 4.6 Domain-specific helpers

| Domain | Module / pattern | Notes |
| --- | --- | --- |
| Legal email / Gmail | `processors/legal_data/email_auth.py` | OAuth/app password resolution; vault prefix helpers; **prompt** only when interactive |
| Wallet APIs | `wallet/api.py` | Magic login secret, SMTP, ops health shared secret, provider bearer tokens via env |
| Messaging / SMS | `messaging/sms_bridge.py` | Twilio auth tokens, provider bearers, OpenAI realtime—env only |
| Error reporting | `error_reporting/` | `GITHUB_TOKEN` / `GH_TOKEN` for issue creation; sanitize payloads |
| P2P cache | `caching/task_p2p_cache.py`, `distributed_cache.py` | Shared secret env chain; avoid relying on GH token as sole secret |

---

## 5. Credential inventory (names only)

> **No real values.** Operators map these names to platform secrets.

### 5.1 Core HTTP / MCP service

| Name | Role | Production guidance |
| --- | --- | --- |
| `SECRET_KEY` | FastAPI / service signing & security dependency | **Required** in production; fatal if missing when production checks run |
| `JWT_SECRET_KEY` | Enterprise API JWT signing | Set explicitly; **do not** use documented dev defaults |
| `ENVIRONMENT` | `development` vs production behavior | Set `production` (or equivalent) only with real secrets |
| `MCP_CORS_ORIGINS` | CORS allowlist | Restrict; empty/default is not “open internet safe” |
| `MCP_ALLOWED_HOSTS` | Host header allowlist | Restrict to real hostnames |
| `MCPPP_MAX_BODY_BYTES` | Request body cap | Keep bounded to reduce DoS |
| `MCPPP_EXEC_TIMEOUT_S` | Tool execution timeout | Prevent runaway tools |
| `MCPPP_ALLOW_UNSIGNED_DELEGATIONS` | UCAN unsigned mode | **Must be unset/false** in production |
| `IPFS_POLICY_STORE_PATH` | Optional policy store | Protect file ACLs |
| `MCP_DELEGATION_STORE_PATH` | Optional UCAN delegation state | Protect file ACLs |
| `IPFS_DATASETS_SECRETS_VAULT_FILE` | Vault path override | Restrict permissions |

### 5.2 Model and neurosymbolic providers

| Name | Role |
| --- | --- |
| `OPENAI_API_KEY` | OpenAI-compatible APIs |
| `ANTHROPIC_API_KEY` | Anthropic (development tools config default env name) |
| `NEUROSYMBOLIC_ENGINE_API_KEY` | SyMAI neurosymbolic engine |
| `IPFS_DATASETS_PY_SYMAI_NEUROSYMBOLIC_API_KEY` | Alternate SyMAI key env |
| `SYMBOLICAI_API_KEY` | SymbolicAI enable/key (logic config) |
| Hugging Face tokens (e.g. hub token env names used by HF client) | Model/dataset hub auth—set via standard HF env practices |

### 5.3 Collaboration and CI

| Name | Role |
| --- | --- |
| `GITHUB_TOKEN` / `GH_TOKEN` | Error reporting, cache helpers, automation—**least privilege**, short-lived when possible |
| `DISCORD_TOKEN` | Discord dashboard/CLI |

### 5.4 Messaging, wallet, and notifications

| Name | Role |
| --- | --- |
| `IPFS_DATASETS_SMS_TWILIO_AUTH_TOKEN` | SMS Twilio auth |
| `IPFS_DATASETS_CALL_TWILIO_AUTH_TOKEN` | Voice Twilio auth |
| `IPFS_DATASETS_SMS_PROVIDER_BEARER_TOKEN` | SMS provider bearer |
| `IPFS_DATASETS_CALL_PROVIDER_BEARER_TOKEN` | Call provider bearer |
| `IPFS_DATASETS_SMS_INBOUND_FORWARD_BEARER_TOKEN` | Inbound forward auth |
| `IPFS_DATASETS_EMAIL_PROVIDER_BEARER_TOKEN` | Email provider |
| `IPFS_DATASETS_EMAIL_SMTP_PASSWORD` / `WALLET_DEAD_DROP_SMTP_PASSWORD` | SMTP passwords |
| `WALLET_MAGIC_LOGIN_SECRET` | Wallet magic-login HMAC/secret material |
| `WALLET_OPS_HEALTH_SHARED_SECRET` | Ops health endpoint shared secret |
| `WALLET_FILECOIN_PIN_BEARER_TOKEN` | Filecoin pin bearer |
| Provider-specific `*_BEARER_TOKEN` patterns in wallet API | Per-integration bearer tokens |

### 5.5 Cache and distributed trust material

| Name | Role |
| --- | --- |
| `IPFS_DATASETS_PY_CACHE_P2P_SHARED_SECRET` | Preferred P2P/distributed cache shared secret |
| `IPFS_ACCELERATE_PY_CACHE_P2P_SHARED_SECRET` | Accelerate-aligned alias |
| `CACHE_P2P_SHARED_SECRET` | Generic alias |
| Fallback to `GH_TOKEN` / `GITHUB_TOKEN` | **Residual risk**—prefer dedicated cache secrets so CI tokens are not dual-purposed |

### 5.6 Prover / ZKP paths (not always “secrets,” still sensitive)

| Name | Role |
| --- | --- |
| `IPFS_DATASETS_GROTH16_BINARY` / `GROTH16_BINARY` | Binary path integrity matters |
| `IPFS_DATASETS_EVENT_DAG_GROTH16_ARTIFACTS` / `GROTH16_BACKEND_ARTIFACTS_ROOT` | Artifact roots—protect proving keys |

Treat proving keys and DID private seeds as **secrets** even when paths are not.

### 5.7 Categories in `SecretsManager`

When using optimizers secrets storage, classify records:

| Category | Examples |
| --- | --- |
| `API_KEY` | Provider keys |
| `TOKEN` | Bearer/JWT refresh material at rest |
| `CREDENTIALS` | Username+password pairs |
| `ENCRYPTION_KEY` | Fernet/AES master keys |
| `DATABASE` | DB DSNs with passwords |
| `CERTIFICATE` | PEM material |
| `OTHER` | Explicitly documented exceptions |

---

## 6. Injection and configuration precedence

Typical resolution order (module-specific; always check the owning module):

1. **Explicit function/CLI argument** (avoid for secrets in shared shells—prefer env).
2. **Process environment**.
3. **Vault load into environment** (`SecretsVault.load_into_env`).
4. **Encrypted secrets manager record**.
5. **Interactive prompt** (legal email helpers only when enabled).
6. **Unsafe development default** (must not ship to production).

**Hermetic / minimal import flags** may avoid loading heavy stacks; they do not
remove the need to protect secrets already in the environment.

---

## 7. Redaction and safe logging

### 7.1 MCP server error context

`IPFSDatasetsMCPServer._sanitize_error_context` replaces values whose **keys**
match sensitive substrings:

`key`, `token`, `password`, `secret`, `auth`, `credential`, `api_key`,
`apikey`, `access_token`, `private`, `passwd`

with `"<REDACTED>"`, and collapses large collections to type/length summaries
before external error reporting.

**Residual risk:** secrets embedded in **non-matching keys** or free-text
strings may still leak—never put tokens in generic fields like `notes` or
`query`.

### 7.2 Authorization and proof public views

- Logic admissibility MCP tools return **redacted** authorization views (no
  prompts, raw arguments, or secrets).
- Proof query audit receipts support redacted forms
  ([PROOF_ATTESTATION_AND_ZKP.md](../../architecture/logic/PROOF_ATTESTATION_AND_ZKP.md)).
- Hammer publishable receipt views expose redacted dictionaries when
  `publishable=True`.

### 7.3 Wallet and PII-adjacent content

Wallet analysis APIs apply `_redact_text` patterns and default
`redacted_derived_only` output policies for GraphRAG/vector profiles. This is
**PII reduction**, not a complete credential scanner—still avoid storing API
keys inside wallet documents.

### 7.4 Operator checklist for redaction

| Do | Do not |
| --- | --- |
| Log secret **names** and “present/absent” booleans | Log secret **values** |
| Use `<REDACTED>` in docs and tickets | Paste CI secret dumps into issues |
| Prefer correlation IDs over raw params in OTel | Attach full tool kwargs to traces |
| Review MCP tool returns before enabling debug | Enable verbose debug in multi-tenant prod |

---

## 8. Rotation

### 8.1 Cadence recommendations

| Class | Suggested rotation | Notes |
| --- | --- | --- |
| Platform root (`SECRET_KEY`, JWT signing) | 90 days or on personnel change | Forces session invalidation—coordinate downtime |
| Cloud API keys (OpenAI, HF, …) | 90 days or provider policy | Dual-key overlap when provider supports |
| Twilio / Discord / SMTP | 90 days or on suspicion | Update all bridges simultaneously |
| P2P cache shared secret | 90 days | Flush cache peers after rotate |
| UCAN/DID key material | On compromise or annual | Revoke delegations signed by old key |
| `SecretsManager` records | Honor `DEFAULT_SECRET_EXPIRY_DAYS` (90) | Rotate before expiry errors |
| GitHub Actions tokens | Prefer ephemeral `GITHUB_TOKEN` | Fine-scoped PATs if required |

### 8.2 Rotation procedure (generic)

1. **Generate** new secret in issuer console or `openssl rand -base64 32`.
2. **Install** new value in platform secret store / vault **alongside** old if dual-read supported.
3. **Deploy** config reload or rolling restart.
4. **Verify** health and one authenticated path.
5. **Revoke** old secret at issuer.
6. **Record** rotation in operator change log (no secret values).
7. **Flush** dependent caches and blacklists as needed.

### 8.3 Code-supported rotation aids

- `SecretsManager`: versioning/expiry fields and rotation helpers (see module).
- JWT: short access TTL + refresh; blacklist old tokens on logout/compromise.
- UCAN: issue new delegations; revoke old CIDs via `RevocationList`.
- Vault: `set` overwrites ciphertext for a name; protect DID seed during re-key.

---

## 9. Revocation

| Material | How to revoke | Local follow-up |
| --- | --- | --- |
| Cloud API key | Provider console revoke | Remove from env/vault; restart |
| JWT / API key (optimizers) | `TokenBlacklist.add` / shared store | Reduce TTL config |
| UCAN delegation | `RevocationList.revoke` / `revoke_chain`; persist file | Flush authz decision cache |
| Proof / attestation | Corpus revocation snapshot | Fail release gates |
| GitHub PAT | GitHub UI revoke | Rotate Actions secrets |
| Discord/Twilio | Developer portal revoke | Update bridge env |
| Vault master / DID seed | Treat as root compromise—re-key vault, re-encrypt secrets | Audit all secrets that were decryptable |

**Revocation without rotation** is incomplete if attackers already copied the
secret—always rotate after revoke when reuse is possible.

---

## 10. Detection

| Signal | Possible cause | Action |
| --- | --- | --- |
| Auth failures after deploy | Wrong/missing `SECRET_KEY` | Fix injection; do not disable auth |
| Provider 401 from model tools | Rotated key not updated | Sync env/vault |
| Unexpected GitHub issue bots | Leaked `GITHUB_TOKEN` | Revoke token; tighten scopes |
| Cache peer auth failures | Shared secret mismatch post-rotate | Align secrets; rolling restart |
| Secrets in CI logs | Echo or debug print | Purge logs if possible; rotate; fix workflow |
| Vault decrypt errors | Wrong DID seed or corrupt file | Restore from backup; re-key |

Use secret scanning (gitleaks, provider scanning, GitHub push protection) as
**external** controls—the package does not replace them.

---

## 11. Recovery after exposure

1. **Contain** — disable public endpoints; revoke provider credentials.
2. **Rotate** — all secrets in the same blast radius (often: signing keys + API keys + cache secrets).
3. **Invalidate** — sessions, UCAN chains, token blacklists, decision caches.
4. **Audit** — policy audit log, Event DAG, cloud provider access logs for the window.
5. **Eradicate** — remove secrets from git history if committed (filter-repo / support process); treat history as hostile until rewritten and force-protected.
6. **Recover** — redeploy clean config; verify redaction still enabled.
7. **Lessons** — update runbooks; add CI checks; see planned audit/incident guide.

Cross-check threat recovery playbooks in [THREAT_MODEL.md](THREAT_MODEL.md) §7.

---

## 12. Safe examples (fake values only)

### 12.1 Production-oriented env file **template**

```bash
# secrets.env.template — copy to a gitignored location; fill via secret store
# All values below are FAKE documentation placeholders.

SECRET_KEY=replace-with-long-random-string
JWT_SECRET_KEY=replace-with-different-long-random-string
ENVIRONMENT=production

# OPENAI_API_KEY=sk-example-not-real
# GITHUB_TOKEN=ghp_example_not_real
# IPFS_DATASETS_PY_CACHE_P2P_SHARED_SECRET=replace-with-dedicated-cache-secret

MCPPP_ALLOW_UNSIGNED_DELEGATIONS=
MCP_CORS_ORIGINS=https://docs.example.invalid
MCP_ALLOWED_HOSTS=api.example.invalid
```

### 12.2 Vault usage pattern

```python
# Documentation pattern only — do not hardcode real secrets in source.
from ipfs_datasets_py.mcp_server.secrets_vault import SecretsVault

vault = SecretsVault()
# vault.set("OPENAI_API_KEY", "<REDACTED>")  # value from operator prompt / CI
assert vault.get("OPENAI_API_KEY") is not None  # presence check in real ops tests
# vault.load_into_env()  # optional; understand child-process inheritance
```

### 12.3 Checking presence without leaking

```python
import os

def secret_status(name: str) -> dict:
    value = os.environ.get(name)
    return {
        "name": name,
        "present": bool(value),
        "length": len(value) if value else 0,
        # never return value
    }
```

---

## 13. Testing without real secrets

| Practice | Guidance |
| --- | --- |
| Unit tests | Use fixtures, fakes, and ephemeral random strings generated in-process |
| CI | Inject secrets only via CI secret store; mask values; never print |
| Integration | Prefer record/replay or sandbox keys with hard spend limits |
| Docs and snapshots | Only `<REDACTED>` or clearly fake patterns |
| Permission of vault files in tests | Use temp directories; delete after |

If a test requires a live key, mark it optional/skipped when unset—**do not**
embed a personal key to make CI green.

---

## 14. Ownership

| Concern | Owner |
| --- | --- |
| This guide | security track / documentation |
| FastAPI `SECRET_KEY` production guard | mcp-server maintainers |
| `SecretsVault` / DID keys | mcp-server |
| `SecretsManager` / JWT helpers | optimizers.security |
| Provider account lifecycle | operators / service owners |
| UCAN revocation lists | mcp-security |
| Wallet/messaging credentials | wallet / messaging owners |
| CI secret scanning policy | repository administrators |

---

## 15. Residual risks (credentials-specific)

| ID | Risk | Control gap | Mitigation |
| --- | --- | --- | --- |
| C1 | Key-name redaction misses free-text secrets | Pattern list on keys only | Never place secrets in free-text fields; DLP |
| C2 | In-memory token blacklist not shared across workers | Process-local | Shared Redis/DB blacklist in multi-worker prod |
| C3 | Dev JWT default string in enterprise API path | Dangerous if copied | Force env in production; fail closed |
| C4 | Vault unlocked by stolen DID seed | Single root of trust | OS key perms; optional hardware; re-key plan |
| C5 | `load_into_env` inherits to children | Environ exposure | Prefer explicit reads; scrub env |
| C6 | GH token dual-used as P2P cache secret | Coupling blast radius | Dedicated `*_CACHE_P2P_SHARED_SECRET` |
| C7 | Secrets committed historically | Git forever | Scanner + history rewrite + rotate |

---

## 16. Related documents

| Document | Role |
| --- | --- |
| [THREAT_MODEL.md](THREAT_MODEL.md) | Full trust boundaries and surface threats |
| [security_governance.md](security_governance.md) | Governance feature narrative (key rotation mentions) |
| [auto_healing_security.md](auto_healing_security.md) | CI token least privilege |
| [audit_logging.md](audit_logging.md) | Audit trails (no secret values) |
| Architecture MCP policy / authz leaves | Delegation and capability revoke semantics |

---

## 17. Validation

```bash
test -s docs/guides/security/THREAT_MODEL.md && test -s docs/guides/security/SECRETS_AND_CREDENTIALS.md && rg -n 'trust|untrusted|residual|secret|redact|rotation|revoke' docs/guides/security/THREAT_MODEL.md docs/guides/security/SECRETS_AND_CREDENTIALS.md
```

Confirm this file still contains **no live secret material** before merge
(manual review + optional secret scanner).

---

## 18. Document history

| Date | Change |
| --- | --- |
| 2026-08-03 | Initial canonical secrets and credentials guide for `IPFSDOC-060` / `SecretsCredentialGuide@1` |
