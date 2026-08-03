# Operations and integrations API domain reference

| Field | Value |
| --- | --- |
| Interface | `OperationsAPIReference@1` |
| Task | `IPFSDOC-081` |
| Status | `canonical` |
| Owner | api-reference / operations-integrations |
| Source of truth | `ipfs_datasets_py/audit/` (+ package-root `audit.py` shim); `ipfs_datasets_py/wallet/`; `ipfs_datasets_py/workflow_automation/`; `ipfs_datasets_py/config.py` and `ipfs_datasets_py/config/`; `ipfs_datasets_py/security.py`; `ipfs_datasets_py/monitoring.py` / `monitoring_engine.py`; cross-package integration points (`mcp_server` tools, `optimizers/integrations`, package routers); architecture [WALLET_TRUST_AND_PRIVACY.md](../../architecture/WALLET_TRUST_AND_PRIVACY.md), MCP observability leaf, [DOMAIN_MAP.md](../../architecture/DOMAIN_MAP.md) § trust/ops |
| Last verified | 2026-08-03 |
| Audience | developer, agent, operator, security reviewer |
| Related | [MCP_AND_RUNTIME.md](MCP_AND_RUNTIME.md), [KNOWLEDGE_LOGIC_AND_PROOF.md](KNOWLEDGE_LOGIC_AND_PROOF.md), [CORE_AND_DATA.md](CORE_AND_DATA.md), [guides/security/](../../guides/security/) |
| Review cadence | after audit handlers, wallet UCAN/crypto, workflow engines, or config surface changes |

## 1. Purpose

This page maps **callable** audit, wallet, workflow, config, monitoring,
security, and integration surfaces with provenance:

1. **Audit** — logger, handlers, compliance reporters, intrusion / adaptive
   security.
2. **Wallet** — `DataWalletService`, grants/invocations, storage backends,
   proofs, UCAN profile helpers.
3. **Workflow automation** — workflow definitions and background task manager
   (including **mock** implementations).
4. **Config** — package TOML config loaders (dual path).
5. **Cross-cutting ops** — monitoring and security managers.
6. **Integrations** — how ops surfaces attach to MCP and external systems.

Importability is **not** public stability. Simulated proofs, mock workflow
services, and minimal `audit.py` stubs must not be presented as production
authority.

## 2. Authority legend

| Tag | Meaning |
| --- | --- |
| **Stability: public** | Preferred external contract |
| **Stability: reviewed** | Exported and tested; AST is authority |
| **Stability: compatibility** | Alias, dual path, or stub |
| **Stability: internal** | Implementation detail |
| **Optional** | ES, syslog, S3, Filecoin, WorldID, real ZK |
| **Side effects** | Filesystem, network, encrypted blob I/O, alerts |

**Hard inequalities (wallet / audit):**

- encrypted **bytes at rest** ≠ plaintext record content
- **UCAN grant / invocation** authorizes actions; CID / proof receipt / audit
  row do **not**
- `is_simulated=True` proofs ≠ production ZK soundness
- mock workflow / mock task manager ≠ production scheduler completion
- audit log presence ≠ compliance certification

---

## 3. Audit

### 3.1 Canonical package (`ipfs_datasets_py.audit`)

| Field | Value |
| --- | --- |
| **Canonical import** | `from ipfs_datasets_py.audit import AuditLogger, AuditEvent, AuditLevel, AuditCategory, …` |
| **Source** | `ipfs_datasets_py/audit/__init__.py` and leaf modules |
| **Stability** | reviewed for `__all__` |
| **Optional** | Elasticsearch, syslog facilities, alerting sinks |
| **Side effects** | handler I/O (files, network, alerts) |

#### Package `__all__`

```python
from ipfs_datasets_py.audit import (
    # Core
    AuditLogger, AuditEvent, AuditLevel, AuditCategory, AuditHandler,
    # Handlers
    FileAuditHandler, JSONAuditHandler, SyslogAuditHandler,
    ElasticsearchAuditHandler, AlertingAuditHandler,
    # Compliance
    ComplianceReport, ComplianceStandard,
    GDPRComplianceReporter, HIPAAComplianceReporter, SOC2ComplianceReporter,
    # Intrusion / adaptive
    IntrusionDetection, AnomalyDetector, SecurityAlertManager,
    AdaptiveSecurityManager, ResponseAction, ResponseRule,
    SecurityResponse, RuleCondition,
)
```

### 3.2 AuditLogger signatures (AST)

```python
def get_audit_logger() -> AuditLogger

class AuditLogger:
    @classmethod
    def get_instance(cls) -> AuditLogger
    def __init__(self) -> None
    def add_handler(self, handler: AuditHandler) -> None
    def remove_handler(self, handler_name: str) -> None
    def set_context(
        self, user=None, session_id=None, client_ip=None, application=None
    ) -> None
    def clear_context(self) -> None
    def log(
        self,
        level: AuditLevel,
        category: AuditCategory,
        action: str,
        user: Optional[str] = None,
        resource_id: Optional[str] = None,
        resource_type: Optional[str] = None,
        status: str = "success",
        details: Optional[Dict[str, Any]] = None,
        client_ip: Optional[str] = None,
        session_id: Optional[str] = None,
        **kwargs,
    ) -> Optional[str]
    # Level helpers: debug, info, notice, warning, error, critical, emergency
    # Category helpers: auth, authz, data_access, data_modify, system,
    #                   security, compliance
    def add_event_listener(self, listener, category=None) -> None
    def remove_event_listener(self, listener, category=None) -> None
    def events(self) ...
    def configure(self, config) -> None
    def reset(self) -> None

class AuditEvent:
    def to_dict(self) -> Dict[str, Any]
    def to_json(self, pretty: bool = ...) -> str
    @classmethod
    def from_dict / from_json / from_security_audit_entry(...)
    def to_security_audit_entry(self) ...
```

```python
logger = get_audit_logger()
logger.add_handler(FileAuditHandler(name="file", file_path="/var/log/ipfs_datasets_audit.log"))
logger.log(
    AuditLevel.INFO,
    AuditCategory.DATA_ACCESS,  # enum member per module
    action="dataset.load",
    resource_id="cid:…",
    status="success",
)
```

### 3.3 Handlers (AST construction notes)

| Handler | Key constructor params | Side effects |
| --- | --- | --- |
| `FileAuditHandler` | `file_path`, rotate size/count, compression | **writes** log files |
| `JSONAuditHandler` | `file_path` / `file_obj`, pretty, rotate | JSON file I/O |
| `SyslogAuditHandler` | `facility`, `identity` | OS syslog |
| `ElasticsearchAuditHandler` | `hosts`, credentials, bulk settings | **network** to ES (**optional**) |
| `AlertingAuditHandler` | `alert_handlers`, rate limits, rules | invokes alert callbacks |

### 3.4 Compliance, intrusion, adaptive security

| Group | Types | Role | Authority |
| --- | --- | --- | --- |
| Compliance | `*ComplianceReporter`, `ComplianceReport`, `ComplianceStandard` | Map audit events to control frameworks | **Reports**, not legal certification |
| Intrusion | `IntrusionDetection`, `AnomalyDetector`, `SecurityAlertManager` | Detect/alert on patterns | Signals ≠ policy allow |
| Adaptive | `AdaptiveSecurityManager`, `ResponseRule`, `ResponseAction` | Automated responses | May **mutate** process policy state — treat as side-effecting |

Additional modules under `audit/` (provenance integration, visualization,
enhanced security) are available by path; prefer `__all__` exports for stable
imports.

### 3.5 Package-root `audit.py` (compatibility stub)

| Field | Value |
| --- | --- |
| **Path** | `ipfs_datasets_py/audit.py` |
| **Stability** | **compatibility** minimal stub (`AuditLogger.log_event` dict helper) |
| **Do not use** | as production audit authority |

**Canonical:** `ipfs_datasets_py.audit` package. The root module exists to
resolve import errors and is **not** feature-complete.

MCP audit tools: `mcp_server/tools/audit_tools/` — thin wrappers; see
[MCP_AND_RUNTIME.md](MCP_AND_RUNTIME.md).

---

## 4. Wallet

### 4.1 Package overview

| Field | Value |
| --- | --- |
| **Canonical import** | `from ipfs_datasets_py.wallet import DataWalletService, …` |
| **Source** | `ipfs_datasets_py/wallet/` (`service.py` control plane) |
| **Stability** | public / reviewed for `__all__` |
| **Optional** | IPFS/S3/Filecoin stores, WorldID bindings, non-simulated proofs |
| **Side effects** | encrypted storage I/O; key wrap; audit chain append; network for remote stores |

Architecture: [WALLET_TRUST_AND_PRIVACY.md](../../architecture/WALLET_TRUST_AND_PRIVACY.md).

```text
wallet/
  service.py     # DataWalletService
  crypto.py      # AES-256-GCM envelope
  storage.py     # Local / IPFS / S3 / Filecoin / Replicated
  ucan.py        # grants, invocations, profile fixtures
  multisig.py    # threshold approval
  proofs.py      # ProofBackend registry (simulated + deterministic)
  privacy.py     # DP helpers
  analytics.py   # consent / aggregates
  models.py      # Wallet, Grant, ProofReceipt, …
  audit.py       # per-wallet hash-chain events
  repository.py  # snapshots / ledgers
  api.py, cli.py # HTTP-shaped / CLI
```

**Alias:** `WalletService = DataWalletService` (same class).

### 4.2 Core types (package exports)

Representative `__all__` groups:

| Group | Symbols |
| --- | --- |
| Service | `DataWalletService`, `WalletService` |
| Models | `Wallet`, `DataRecord`, `Grant`, `GrantReceipt`, `WalletInvocation`, `ProofReceipt`, `AccessRequest`, `ApprovalRequest`, `AnalyticsConsent`, `WorldIdBinding`, … |
| Storage | `LocalEncryptedBlobStore`, `IPFSEncryptedBlobStore`, `S3EncryptedBlobStore`, `FilecoinEncryptedBlobStore`, `ReplicatedEncryptedBlobStore`, `create_encrypted_blob_store`, configs |
| Proofs | `ProofBackend`, `ProofBackendRegistry`, `SimulatedProofBackend`, `DeterministicLocation*ProofBackend` |
| UCAN helpers | `wallet_ucan_profile`, `invocation_to_ucan_profile_payload`, `validate_ucan_profile_payload`, conformance fixture helpers, profile ID constants |
| Errors | `DataWalletError`, `AccessDeniedError`, `GrantError`, `DecryptionError`, `ApprovalRequiredError`, `MissingRecordError` |
| Other | `LocalWalletRepository`, `AnalyticsPrivacyPolicy`, `operation_requires_approval` |

### 4.3 DataWalletService — primary signatures (AST)

Construction:

```python
class DataWalletService:
    def __init__(self, storage_dir: ...) -> None
```

#### Lifecycle and governance

```python
def create_wallet(
    self,
    owner_did: str,
    device_did: Optional[str] = None,
    controller_dids: Optional[List[str]] = None,
    governance_policy: Optional[Dict[str, Any]] = None,
) -> Wallet

def get_wallet(self, wallet_id: str) -> ...
def add_controller / remove_controller(self, wallet_id, ...)
def add_device / revoke_device(self, wallet_id, ...)
def set_recovery_policy / recover_controller(self, wallet_id, ...)
def request_approval / approve_approval(self, wallet_id, ...)
def request_access / list_access_requests / approve_access_request /
    reject_access_request / revoke_access_request(...)
```

#### Records and grants

```python
def add_document(self, wallet_id, path, ...) -> ...
def add_location(self, wallet_id, ...) -> ...
def add_record(self, wallet_id, ...) -> ...
def update_record_metadata / delete_record(self, wallet_id, record_id, ...)

def create_grant(
    self,
    wallet_id: str,
    issuer_did: str,
    audience_did: str,
    resources: List[str],
    abilities: List[str],
    caveats: Optional[Dict[str, Any]] = None,
    expires_at: Optional[str] = None,
    approval_id: Optional[str] = None,
    issuer_secret: Optional[bytes] = None,
    audience_secret: Optional[bytes] = None,
    parent_grant_id: Optional[str] = None,
) -> Grant

def issue_invocation(
    self,
    wallet_id: str,
    grant_id: str,
    actor_did: str,
    resource: str,
    ability: str,
    actor_secret: Optional[bytes] = None,
    caveats: Optional[Dict[str, Any]] = None,
    expires_at: Optional[str] = None,
) -> WalletInvocation

def verify_invocation(self, wallet_id, invocation, ...) -> ...
def revoke_grant(self, wallet_id, grant_id, ...) -> ...
def emergency_revoke(self, wallet_id, ...) -> ...
def list_grant_receipts(self, wallet_id, ...) -> ...
```

#### Decrypt and analysis (capability-gated)

```python
def decrypt_record(
    self,
    wallet_id: str,
    record_id: str,
    actor_did: str,
    grant_id: Optional[str] = None,
    actor_secret: Optional[bytes] = None,
    invocation_caveats: Optional[Dict[str, Any]] = None,
) -> bytes

def decrypt_record_with_invocation(self, wallet_id, record_id, ...) -> bytes
def rotate_record_key(self, wallet_id, record_id, ...) -> ...

# Redacted / privacy-preserving analysis helpers (selected)
def analyze_record_summary(...)
def analyze_document_with_redaction(...)
def create_document_vector_profile(...)
def create_redacted_graphrag(self, wallet_id, record_ids, ...)
def extract_document_text_with_redaction(...)
```

#### Location / document proofs

```python
def create_coarse_location_claim(...)
def create_location_region_proof(...)
def create_location_distance_proof(...)
def create_document_profile_proof(...)
```

**Result authority:** inspect proof backend / `is_simulated` flags. Deterministic
location backends are **integration plumbing**; `SimulatedProofBackend` is
**dev/test only**.

#### Analytics, export, storage health

```python
def create_analytics_consent / revoke_analytics_consent(...)
def create_analytics_template / list_analytics_templates / retire_...(…)
def create_analytics_contribution / verify_analytics_contribution(...)
def run_aggregate_count / run_aggregate_count_by_fields(...)

def get_wallet_manifest / get_wallet_manifest_canonical(...)
def export_wallet_snapshot / import_wallet_snapshot(...)
def create_export_bundle / verify_export_bundle / import_export_bundle(...)
def create_export_bundle_with_invocation(...)
def get_audit_log(self, wallet_id) -> ...
def verify_record_storage / verify_wallet_storage(...)
def repair_record_storage / repair_wallet_storage(...)
def set_principal_secret(self, did, secret) -> None  # side effect: secret material
```

WorldID bindings, recovery bundles, missing-person dead drops, and service
plans are additional control-plane methods on the same class (see AST of
`service.py` for full inventory). **Never put real secrets, DEKs, or WorldID
nullifiers in documentation examples.**

### 4.4 UCAN profile helpers

```python
from ipfs_datasets_py.wallet import (
    wallet_ucan_profile,
    wallet_ucan_external_adapter_profile,
    invocation_to_ucan_profile_payload,
    validate_ucan_profile_payload,
    wallet_ucan_conformance_fixture,
    validate_wallet_ucan_conformance_fixture,
    # constants: WALLET_UCAN_PROFILE_ID, WALLET_UCAN_TOKEN_PREFIX, …
)
```

Source: `wallet/ucan.py`. Grants/invocations assert caveats and resources;
profile payloads adapt to external UCAN stacks without granting extra power.

### 4.5 Multisig

```python
from ipfs_datasets_py.wallet import operation_requires_approval
```

When governance threshold &gt; 1, sensitive operations require approval —
**do not soft-skip** in integrations.

### 4.6 MCP wallet tools

Thin wrappers under `mcp_server/tools/wallet_tools/` call `DataWalletService`.
MCP listing ≠ grant issuance. Policy pipeline stages are separate from wallet
UCAN checks ([MCP_AND_RUNTIME.md](MCP_AND_RUNTIME.md) §9).

---

## 5. Workflow automation

| Field | Value |
| --- | --- |
| **Canonical import** | `from ipfs_datasets_py.workflow_automation import …` |
| **Source** | `workflow_automation/__init__.py`, `enhanced_workflows.py`, `background_task_engine.py` |
| **Stability** | reviewed for exports; **default service is mock-oriented** |
| **Side effects** | in-memory task/workflow state for mock engine; real backends if substituted |

### 5.1 Package exports

```python
from ipfs_datasets_py.workflow_automation import (
    TaskStatus,
    TaskType,
    MockBackgroundTask,
    MockTaskManager,
    WorkflowStatus,
    StepStatus,
    WorkflowStep,
    WorkflowDefinition,
    MockWorkflowService,
    get_default_workflow_service,
)
```

Package docstring: MCP-agnostic workflow logic reusable by CLI, MCP, and
other integrations.

### 5.2 MockTaskManager (AST)

```python
class MockTaskManager:
    def __init__(self) -> None
    async def create_task(self, task_type: str, **kwargs) -> str
    async def get_task(self, task_id: str) -> ...
    async def list_tasks(self) -> ...
    async def cancel_task(self, task_id: str) -> ...
    async def cleanup_completed_tasks(self, max_age_hours: float = ...) -> ...
    async def get_stats(self) -> ...
    async def get_task_status(self, task_id: str) -> ...
    async def update_task(self, task_id: str, ...) -> ...
    async def get_queue_stats(self) -> ...
```

`MockBackgroundTask` supports `add_log`, `update_progress`, `complete`, `fail`,
`cancel`, `to_dict`.

### 5.3 MockWorkflowService (AST)

```python
class MockWorkflowService:
    def __init__(self) -> None
    async def create_workflow(self, definition: Dict[str, Any]) -> Dict[str, Any]
    async def execute_workflow(
        self, workflow_id: str, execution_params: Optional[Dict] = None
    ) -> Dict[str, Any]
    async def get_workflow_status(self, workflow_id: str) -> Dict[str, Any]
    async def list_workflows(self, status_filter=None) -> Dict[str, Any]

def get_default_workflow_service() -> MockWorkflowService
```

Supporting types: `WorkflowDefinition`, `WorkflowStep`, `WorkflowStatus`,
`StepStatus` enums.

**Result authority:** mock completion is **not** production job orchestration
success. MCP `background_task_tools` and enhanced tools may wrap these types —
check tool implementation for real vs mock backend.

Related modules: `background_task_tools.py`, `enhanced_background_task_tools.py`,
`cli.py` in the same package.

---

## 6. Config

### 6.1 Dual surface (compatibility)

Two equivalent config loaders exist:

| Path | Import | Stability |
| --- | --- | --- |
| Package module | `from ipfs_datasets_py.config import config` → `config/config.py` | reviewed package path |
| Root module | `from ipfs_datasets_py.config import config` via `config.py` at package root | **compatibility dual** — same class shape |

```python
# Preferred: package
from ipfs_datasets_py.config import config  # config/__init__.py re-exports

# Class methods (AST)
class config:
    def __init__(self, collection=None, meta=None)
    def overrideToml(self, base, overrides) -> ...
    def findConfig(self) -> ...
    def loadConfig(self, configPath, overrides=None) -> ...
    def requireConfig(self, opts=None) -> ...
```

**Side effects:** reads TOML from search paths / temp dirs as implemented;
does not start services by itself.

**Templates:** `config/config.toml`, `config template.toml`, repo-root
`config.yaml.example`, `configs.yaml.example`, `sql_configs.yaml.example`.

### 6.2 MCP-local configs

`ipfs_datasets_py.mcp_server.Configs` / `load_config_from_yaml` — server pathing
only ([MCP_AND_RUNTIME.md](MCP_AND_RUNTIME.md) §11).

### 6.3 Logic / optimizer configs

Domain-specific config modules (`logic.config`, optimizer configs) stay in
those domains. Do not treat global TOML loader as IR schema authority.

---

## 7. Monitoring and security (cross-cutting)

### 7.1 Monitoring

| Field | Value |
| --- | --- |
| **Canonical import** | `from ipfs_datasets_py.monitoring import …` (module `monitoring.py`) |
| **Source** | `ipfs_datasets_py/monitoring.py`, `monitoring_engine.py` |
| **Stability** | reviewed helpers |
| **Side effects** | metrics registries, timed operations |

Selected surfaces (AST):

```python
class MonitoringSystem: ...
class MetricsRegistry: ...
class MonitoringConfig / MetricsConfig / LoggerConfig: ...

def get_logger(name: Optional[str] = None) -> logging.Logger
def get_metrics_registry() -> MetricsRegistry
def configure_monitoring(config: Optional[MonitoringConfig] = None) -> MonitoringSystem
def monitor_context(**kwargs) ...
def timed_operation(name, metrics_registry, labels=None) ...
def timed(func=None, *, metric_name=None, registry=None, include_args=False) ...
```

**Authority:** metrics and health exports ≠ authorization or compliance proof.
MCP Prometheus/OTel modules are additional attach points under `mcp_server/`.

### 7.2 Security manager

| Field | Value |
| --- | --- |
| **Canonical import** | `from ipfs_datasets_py.security import SecurityManager, SecurityConfig, initialize_security, …` |
| **Source** | `ipfs_datasets_py/security.py` |
| **Stability** | reviewed large module; import carefully in constrained environments |
| **Side effects** | encryption, policy evaluation, lineage/provenance tracking when used |

Key types: `SecurityConfig`, `UserCredentials`, `EncryptionKey`,
`ResourcePolicy`, `DataLineage`, `DataProvenance`, `AuditLogEntry`,
`SecurityManager`, `initialize_security(config=None) -> SecurityManager`.

This package-root security module is **distinct** from `logic.security` /
`logic.security_ir` (formal IR) and from wallet crypto. Prefer the domain that
owns the concern.

---

## 8. Integration surfaces

### 8.1 MCP as integration bus

| Integration | Mechanism | Notes |
| --- | --- | --- |
| Audit tools | `mcp_server/tools/audit_tools/` | wrap audit package |
| Wallet tools | `mcp_server/tools/wallet_tools/` | wrap `DataWalletService` |
| Background / workflow tools | `background_task_tools`, MCP++ workflow tools | may use mock engines |
| Admin / monitoring / rate limit | corresponding `*_tools` dirs | ops control plane |
| ipfs_kit MCP | `register_ipfs_kit_tools(url)` | **optional** remote |

Thin wrappers must not re-implement domain authority.

### 8.2 Optimizer external integrations

| Field | Value |
| --- | --- |
| **Path** | `ipfs_datasets_py/optimizers/integrations/` |
| **Modules** | e.g. `duckdb_storage`, `elasticsearch_indexer`, `kafka_ontology_stream`, `neo4j_loader` |
| **Stability** | **optional** external systems |
| **Side effects** | network / DB writes |

### 8.3 Knowledge / logic bridges

- `logic.integrations` — GraphRAG / UnixFS adapters (outside core theorem tree)
- `logic.bridge` — optimizer/prover/KG bridges
- Wallet `create_redacted_graphrag` — privacy-preserving graph path

### 8.4 Package routers (lazy)

Root package and modules such as `llm_router`, `embedding_router`,
`multimodal_router`, `voice_router` provide lazy integration entrypoints.
Treat missing optional providers as **availability** failures, not API
absence (ADR-002 lazy capabilities).

### 8.5 Workflow DAG helpers (package getattr)

Software-engineering MCP tools may expose `create_workflow_dag` /
speculative planners via package `__getattr__` paths — **optional** and
distinct from `workflow_automation.MockWorkflowService`.

---

## 9. Canonical import cheat sheet

| Intent | Canonical import | Stability | Authority notes |
| --- | --- | --- | --- |
| Production audit log | `audit.AuditLogger` / `get_audit_logger` | reviewed | handlers define durability |
| Audit handlers | `audit.FileAuditHandler`, … | reviewed / optional ES | I/O side effects |
| Compliance reporters | `audit.GDPRComplianceReporter`, … | reviewed | report ≠ certification |
| Avoid stub | ~~`ipfs_datasets_py.audit` module file~~ | compatibility stub | use package |
| Wallet control plane | `wallet.DataWalletService` | public | grants authorize |
| Wallet UCAN helpers | `wallet.wallet_ucan_profile`, … | reviewed | profile ≠ grant |
| Simulated proofs | `wallet.SimulatedProofBackend` | reviewed | **non-production ZK** |
| Workflows (default) | `workflow_automation.get_default_workflow_service` | reviewed mock | mock ≠ prod |
| Background tasks | `workflow_automation.MockTaskManager` | reviewed mock | same |
| App TOML config | `ipfs_datasets_py.config.config` | reviewed dual-path | load only |
| MCP server config | `mcp_server.Configs` | reviewed | server-local |
| Metrics | `monitoring.configure_monitoring` | reviewed | ≠ authz |
| App security mgr | `security.initialize_security` | reviewed | ≠ logic IR |

---

## 10. Side-effect and optional summary

| Surface | Side effects | Optional |
| --- | --- | --- |
| Audit handlers | files, syslog, ES, alerts | ES credentials |
| Wallet service | encrypted FS/object I/O, secrets | IPFS/S3/Filecoin |
| Wallet proofs | CPU; optional network | real ZK backends |
| Multisig approvals | blocks ops until threshold | governance policy |
| Mock workflows | in-memory only | — |
| Config load | read TOML paths | custom paths |
| Monitoring | registry mutation | Prometheus exporters |
| Security manager | crypto / policy state | key material |
| Optimizer integrations | external DB/stream I/O | each backend |

---

## 11. Discrepancies and deferred items

| Item | Disposition |
| --- | --- |
| Root `audit.py` vs `audit/` package | Prefer package; stub labeled compatibility |
| Dual `config.py` / `config/config.py` | Same API shape; package import preferred |
| Mock workflow default | Explicit mock authority — production schedulers elsewhere (MCP++ / supervisor) |
| Exhaustive `DataWalletService` method table | Primary AST groups listed; full list in `service.py` (~6k lines) |
| Security.py vs logic.security_ir | Different domains; do not conflate |
| Wallet MCP tool names | Discover live under `wallet_tools/`; not duplicated as SoT here |

---

## 12. Validation evidence for this page

- Audit package `__all__` and `AuditLogger` / handler ASTs (2026-08-03).
- Wallet package exports and `DataWalletService` method signatures from AST.
- Workflow automation `__all__` and mock service/manager ASTs.
- Config dual path and monitoring/security entrypoints from module ASTs.
- Cross-linked to wallet architecture (IPFSDOC-061), MCP observability, and
  sibling API domain pages (IPFSDOC-080/081).
