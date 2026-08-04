"""Read-only USPTO MCP tools (PATLAW-061 + PATLAW-141).

Thin wrappers around the canonical
:class:`~ipfs_datasets_py.processors.domains.uspto.api.USPTOAnalysisAPI`
plus **persisted** assurance/dossier query tools that never trigger live sync,
filing, payment, or submission-assurance runs.

Design constraints
------------------
* Tool schemas expose **only** read-only status / analysis / persisted-query ops.
* No sign, file, pay, session, credential-returning, or browser tool exists.
* Unauthorized or private cross-tenant access is denied fail-closed.
* Unauthorized tenants receive **no existence oracle** for private persisted rows.
* Output redaction is driven by
  :class:`~ipfs_datasets_py.processors.domains.uspto.analysis.gap_report.OutputRedactionPolicy`.
* All analysis logic lives in the domain API — this module never duplicates it.
* Persisted assurance queries read only from an injected store (no implicit live sync).
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Final, Mapping, Optional, Protocol, Sequence, runtime_checkable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Interface constants
# ---------------------------------------------------------------------------

USPTO_MCP_INTERFACE: Final = "USPTOMCP@1"
USPTO_MCP_SCHEMA: Final = "uspto-mcp/v1"
USPTO_MCP_TOOL_VERSION: Final = "1.0.0"

# Read-only tool surface (acceptance + plan §14). PATLAW-061 contract — do not
# expand this tuple without updating the v1 MCP unit suite.
READ_ONLY_TOOL_NAMES: Final[tuple[str, ...]] = (
    "uspto_status",
    "uspto_dossier_summary",
    "uspto_requirement_matrix",
    "uspto_evidence_gaps",
    "uspto_citation_explanation",
    "uspto_analysis_replay",
)

# Additive persisted-assurance query surface (PATLAW-141). Kept separate so the
# v1 READ_ONLY_TOOL_NAMES / TOOL_SCHEMAS contract remains stable.
PERSISTED_ASSURANCE_TOOL_NAMES: Final[tuple[str, ...]] = (
    "uspto_persisted_assurance_summary",
    "uspto_persisted_assurance_findings",
    "uspto_persisted_assurance_provenance",
)

# Explicitly never offered as MCP operations (acceptance).
FORBIDDEN_MCP_OPERATIONS: Final[frozenset[str]] = frozenset(
    {
        "sign",
        "pay",
        "file",
        "submit",
        "session",
        "credential",
        "credentials",
        "login",
        "browser",
        "automate_browser",
        "scrape",
        "mfa",
        "api_key",
        "password",
        "cookie",
        "import_private",  # mutating; not a read-only MCP surface
        "sync_public",  # write-side sync; not read-only MCP
        "submission_assurance",  # live workflow; MCP uses persisted queries only
        "assure",  # alias of submission_assurance
        "live_sync",
        "force_live_sync",
        "trigger_sync",
        "file_application",
        "make_payment",
    }
)

# Map MCP tool → canonical API operation (or projection of one).
TOOL_TO_API_OPERATION: Final[Mapping[str, str]] = {
    "uspto_status": "status",
    "uspto_dossier_summary": "analyze",
    "uspto_requirement_matrix": "explain",
    "uspto_evidence_gaps": "explain",
    "uspto_citation_explanation": "explain",
    "uspto_analysis_replay": "analyze",
}

# Persisted tools never call live domain API operations.
PERSISTED_ASSURANCE_TOOL_TO_OPERATION: Final[Mapping[str, str]] = {
    "uspto_persisted_assurance_summary": "persisted_read",
    "uspto_persisted_assurance_findings": "persisted_read",
    "uspto_persisted_assurance_provenance": "persisted_read",
}

# Existence-oracle-safe denial code (unauthorized must not distinguish miss vs deny).
ACCESS_DENIED_CODE: Final = "access_denied"
ACCESS_DENIED_MESSAGE: Final = "access denied"

# Keys stripped from persisted projections (never embed private document bodies).
_PERSISTED_BODY_KEYS: Final[frozenset[str]] = frozenset(
    {
        "text",
        "body",
        "content",
        "detail_text",
        "narrative",
        "human_readable",
        "instruction_text",
        "raw_text",
        "raw_bytes",
        "bytes",
        "embedding",
        "embeddings",
        "vector",
        "password",
        "api_key",
        "token",
        "secret",
        "private_cid",
        "document_bytes",
        "pdf_bytes",
        "ocr_text",
        "claim_text",
        "full_text",
    }
)

_PRIVATE_TEXT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "text",
        "body",
        "content",
        "detail_text",
        "explanation",
        "message",
        "summary",
        "narrative",
        "human_readable",
        "display_value",
        "instruction_text",
        "raw_text",
        "prompt",
        "bytes",
        "raw_bytes",
        "embedding",
        "embeddings",
        "vector",
        "password",
        "api_key",
        "token",
        "secret",
        "private_cid",
        "cid",
    }
)

# Documented schemas for MCP discovery — no forbidden operations appear.
TOOL_SCHEMAS: Final[dict[str, dict[str, Any]]] = {
    "uspto_status": {
        "name": "uspto_status",
        "interface": USPTO_MCP_INTERFACE,
        "schema": USPTO_MCP_SCHEMA,
        "python_operation": "status",
        "read_only": True,
        "description": (
            "Fetch/normalize public USPTO application status via the "
            "canonical USPTOAnalysisAPI.status operation."
        ),
        "parameters": {
            "type": "object",
            "required": ["application_number"],
            "properties": {
                "application_number": {
                    "type": "string",
                    "description": "USPTO application number.",
                },
                "matter_id": {
                    "type": "string",
                    "description": "Optional matter identifier.",
                },
                "tenant_id": {
                    "type": "string",
                    "description": (
                        "Caller tenant id (required when the result is private)."
                    ),
                },
                "force_refresh": {
                    "type": "boolean",
                    "default": False,
                    "description": "Bypass cached status snapshot.",
                },
                "credential_ref": {
                    "type": "string",
                    "description": (
                        "Opaque credential *reference id* only (never a secret)."
                    ),
                },
                "output_policy": {
                    "type": "object",
                    "description": "Optional OutputRedactionPolicy mapping.",
                },
            },
        },
        "returns": {"envelope": "uspto-mcp-response/v1"},
    },
    "uspto_dossier_summary": {
        "name": "uspto_dossier_summary",
        "interface": USPTO_MCP_INTERFACE,
        "schema": USPTO_MCP_SCHEMA,
        "python_operation": "analyze",
        "read_only": True,
        "description": (
            "Return a redacted dossier / analysis-bundle summary via "
            "USPTOAnalysisAPI.analyze (no filing mutation)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "matter_id": {"type": "string"},
                "analysis_bundle": {
                    "type": "object",
                    "description": "Optional UsptoAnalysisBundle mapping.",
                },
                "tenant_id": {
                    "type": "string",
                    "description": "Caller tenant id for private material.",
                },
                "seed_classification": {
                    "type": "string",
                    "default": "public_user",
                },
                "output_policy": {"type": "object"},
                "labels": {"type": "object"},
            },
        },
        "returns": {"envelope": "uspto-mcp-response/v1"},
    },
    "uspto_requirement_matrix": {
        "name": "uspto_requirement_matrix",
        "interface": USPTO_MCP_INTERFACE,
        "schema": USPTO_MCP_SCHEMA,
        "python_operation": "explain",
        "read_only": True,
        "description": (
            "Project the requirement/evidence matrix from an analysis bundle "
            "via USPTOAnalysisAPI.explain (deterministic gap report)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "analysis_bundle": {"type": "object"},
                "gap_report": {"type": "object"},
                "matter_id": {"type": "string"},
                "analysis_id": {"type": "string"},
                "tenant_id": {"type": "string"},
                "output_policy": {"type": "object"},
                "labels": {"type": "object"},
            },
        },
        "returns": {"envelope": "uspto-mcp-response/v1"},
    },
    "uspto_evidence_gaps": {
        "name": "uspto_evidence_gaps",
        "interface": USPTO_MCP_INTERFACE,
        "schema": USPTO_MCP_SCHEMA,
        "python_operation": "explain",
        "read_only": True,
        "description": (
            "Return open evidence gaps, unknowns, and reviewer actions from "
            "the canonical gap-report projection."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "analysis_bundle": {"type": "object"},
                "gap_report": {"type": "object"},
                "matter_id": {"type": "string"},
                "analysis_id": {"type": "string"},
                "tenant_id": {"type": "string"},
                "output_policy": {"type": "object"},
                "labels": {"type": "object"},
            },
        },
        "returns": {"envelope": "uspto-mcp-response/v1"},
    },
    "uspto_citation_explanation": {
        "name": "uspto_citation_explanation",
        "interface": USPTO_MCP_INTERFACE,
        "schema": USPTO_MCP_SCHEMA,
        "python_operation": "explain",
        "read_only": True,
        "description": (
            "Explain authority / legal-citation statements bound to the "
            "analysis bundle gap report (provenance links preserved)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "analysis_bundle": {"type": "object"},
                "gap_report": {"type": "object"},
                "matter_id": {"type": "string"},
                "analysis_id": {"type": "string"},
                "tenant_id": {"type": "string"},
                "output_policy": {"type": "object"},
                "labels": {"type": "object"},
            },
        },
        "returns": {"envelope": "uspto-mcp-response/v1"},
    },
    "uspto_analysis_replay": {
        "name": "uspto_analysis_replay",
        "interface": USPTO_MCP_INTERFACE,
        "schema": USPTO_MCP_SCHEMA,
        "python_operation": "analyze",
        "read_only": True,
        "description": (
            "Deterministically replay analysis + explain projections from a "
            "bound analysis bundle (digest verification; no re-derivation of "
            "hidden legal outcomes beyond the canonical API)."
        ),
        "parameters": {
            "type": "object",
            "required": ["analysis_bundle"],
            "properties": {
                "analysis_bundle": {
                    "type": "object",
                    "description": "UsptoAnalysisBundle mapping to replay.",
                },
                "tenant_id": {"type": "string"},
                "output_policy": {"type": "object"},
                "labels": {"type": "object"},
            },
        },
        "returns": {"envelope": "uspto-mcp-response/v1"},
    },
}

# PATLAW-141 schemas (separate dict so v1 TOOL_SCHEMAS contract stays stable).
PERSISTED_ASSURANCE_TOOL_SCHEMAS: Final[dict[str, dict[str, Any]]] = {
    "uspto_persisted_assurance_summary": {
        "name": "uspto_persisted_assurance_summary",
        "interface": USPTO_MCP_INTERFACE,
        "schema": USPTO_MCP_SCHEMA,
        "python_operation": "persisted_read",
        "read_only": True,
        "triggers_live_sync": False,
        "triggers_filing_or_payment": False,
        "description": (
            "Read a tenant-scoped persisted submission-assurance / dossier "
            "summary (identifiers, digests, disposition). Never runs live "
            "sync, filing, payment, or submission_assurance."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "tenant_id": {
                    "type": "string",
                    "description": "Caller tenant id (required for private rows).",
                },
                "matter_id": {"type": "string"},
                "assurance_id": {"type": "string"},
                "dossier_id": {"type": "string"},
                "output_policy": {"type": "object"},
            },
        },
        "returns": {"envelope": "uspto-mcp-response/v1"},
    },
    "uspto_persisted_assurance_findings": {
        "name": "uspto_persisted_assurance_findings",
        "interface": USPTO_MCP_INTERFACE,
        "schema": USPTO_MCP_SCHEMA,
        "python_operation": "persisted_read",
        "read_only": True,
        "triggers_live_sync": False,
        "triggers_filing_or_payment": False,
        "description": (
            "Read persisted assurance finding codes/kinds (no document body "
            "text) for an authorized tenant."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "tenant_id": {"type": "string"},
                "matter_id": {"type": "string"},
                "assurance_id": {"type": "string"},
                "dossier_id": {"type": "string"},
                "output_policy": {"type": "object"},
            },
        },
        "returns": {"envelope": "uspto-mcp-response/v1"},
    },
    "uspto_persisted_assurance_provenance": {
        "name": "uspto_persisted_assurance_provenance",
        "interface": USPTO_MCP_INTERFACE,
        "schema": USPTO_MCP_SCHEMA,
        "python_operation": "persisted_read",
        "read_only": True,
        "triggers_live_sync": False,
        "triggers_filing_or_payment": False,
        "description": (
            "Read persisted provenance digests, stage receipts, and protected "
            "dossier link references for an authorized tenant."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "tenant_id": {"type": "string"},
                "matter_id": {"type": "string"},
                "assurance_id": {"type": "string"},
                "dossier_id": {"type": "string"},
                "output_policy": {"type": "object"},
            },
        },
        "returns": {"envelope": "uspto-mcp-response/v1"},
    },
}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class UsptoMCPError(ValueError):
    """Fail-closed MCP boundary error."""

    def __init__(self, message: str, *, code: str = "uspto_mcp_error") -> None:
        super().__init__(message)
        self.code = code

    def audit_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)[:256]}


class UsptoMCPAuthError(UsptoMCPError):
    """Raised when tenant authorization fails (cross-tenant / missing tenant)."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "unauthorized_tenant",
    ) -> None:
        super().__init__(message, code=code)


class ForbiddenMCPOperationError(UsptoMCPError):
    """Raised when a forbidden capability is requested via MCP."""

    def __init__(self, operation: str) -> None:
        super().__init__(
            f"forbidden USPTO MCP operation: {operation!r}",
            code="forbidden_operation",
        )
        self.operation = operation


# ---------------------------------------------------------------------------
# Lazy domain imports (keep module import light when domain is unavailable)
# ---------------------------------------------------------------------------

try:
    from ipfs_datasets_py.processors.domains.uspto.api import (
        FORBIDDEN_API_OPERATIONS,
        PUBLIC_OPERATIONS,
        USPTOAnalysisAPI,
        CredentialRef,
        ForbiddenAPIOperationError,
        UsptoAPIError,
        assert_operation_allowed,
        create_api,
        scrub_credential_fields,
    )
    from ipfs_datasets_py.processors.domains.uspto.analysis.gap_report import (
        DEFAULT_OUTPUT_POLICY,
        OutputPolicyMode,
        OutputRedactionPolicy,
        RequirementEvidenceGapReport,
        StatementKind,
    )
    from ipfs_datasets_py.processors.domains.uspto.contracts import (
        DisclosureClassification,
        is_private_classification,
        requires_quarantine,
    )

    _API_AVAILABLE = True
except ImportError as _import_err:  # pragma: no cover - exercised when domain missing
    logger.warning("USPTO domain API unavailable for MCP tools: %s", _import_err)
    _API_AVAILABLE = False
    FORBIDDEN_API_OPERATIONS = frozenset()  # type: ignore[misc, assignment]
    PUBLIC_OPERATIONS = ()  # type: ignore[misc, assignment]
    USPTOAnalysisAPI = None  # type: ignore[misc, assignment]
    CredentialRef = None  # type: ignore[misc, assignment]
    ForbiddenAPIOperationError = RuntimeError  # type: ignore[misc, assignment]
    UsptoAPIError = RuntimeError  # type: ignore[misc, assignment]
    DEFAULT_OUTPUT_POLICY = None  # type: ignore[misc, assignment]
    OutputPolicyMode = None  # type: ignore[misc, assignment]
    OutputRedactionPolicy = None  # type: ignore[misc, assignment]
    RequirementEvidenceGapReport = None  # type: ignore[misc, assignment]
    StatementKind = None  # type: ignore[misc, assignment]
    DisclosureClassification = None  # type: ignore[misc, assignment]

    def assert_operation_allowed(operation: str) -> None:  # type: ignore[misc]
        raise UsptoMCPError(
            "uspto domain API not installed", code="api_unavailable"
        )

    def create_api(**kwargs: Any) -> Any:  # type: ignore[misc]
        raise UsptoMCPError(
            "uspto domain API not installed", code="api_unavailable"
        )

    def scrub_credential_fields(payload: Any) -> Any:  # type: ignore[misc]
        return payload

    def is_private_classification(value: Any) -> bool:  # type: ignore[misc]
        return str(value).lower() in {
            "confidential_application",
            "attorney_work_product",
            "export_controlled",
        }

    def requires_quarantine(value: Any) -> bool:  # type: ignore[misc]
        return str(value).lower() in {"unknown", "quarantine"}


# ---------------------------------------------------------------------------
# API binding (injectable for tests; never ambient secrets)
# ---------------------------------------------------------------------------

_bound_api: Any = None
_id_factory: Callable[[], str] | None = None
_bound_assurance_store: "PersistedAssuranceStore | None" = None


def bind_api(api: Any | None) -> None:
    """Bind the canonical :class:`USPTOAnalysisAPI` used by all tools."""
    global _bound_api
    _bound_api = api


def get_api() -> Any:
    """Return the bound API or construct a default (no ambient secrets)."""
    global _bound_api
    if _bound_api is not None:
        return _bound_api
    if not _API_AVAILABLE:
        raise UsptoMCPError(
            "USPTOAnalysisAPI is not available", code="api_unavailable"
        )
    _bound_api = create_api(id_factory=_id_factory)
    return _bound_api


def reset_api() -> None:
    """Clear the bound API (tests / process re-init)."""
    global _bound_api
    _bound_api = None


def set_id_factory(factory: Callable[[], str] | None) -> None:
    """Optional deterministic id factory for replay tests."""
    global _id_factory
    _id_factory = factory


# ---------------------------------------------------------------------------
# Persisted assurance store (PATLAW-141) — injectable; never live-syncs
# ---------------------------------------------------------------------------


@runtime_checkable
class PersistedAssuranceStore(Protocol):
    """Tenant-scoped read surface for persisted assurance / dossier rows.

    Implementations must not perform live USPTO network I/O, filing, payment,
    or submission-assurance execution. Lookups are pure local reads.
    """

    def get_record(
        self,
        *,
        tenant_id: str | None = None,
        matter_id: str | None = None,
        assurance_id: str | None = None,
        dossier_id: str | None = None,
    ) -> Mapping[str, Any] | None:
        """Return one persisted record or ``None`` when missing."""
        ...


class InMemoryPersistedAssuranceStore:
    """Simple in-process store for tests and single-process deployments."""

    def __init__(self) -> None:
        self._rows: list[dict[str, Any]] = []
        self._lock = threading.RLock()
        self.live_sync_calls: int = 0
        self.filing_calls: int = 0
        self.payment_calls: int = 0
        self.assurance_run_calls: int = 0

    def put(self, record: Mapping[str, Any]) -> dict[str, Any]:
        """Insert or replace a persisted assurance row (test / operator helper)."""
        cleaned = _strip_persisted_bodies(dict(record))
        tenant = _normalize_tenant(cleaned.get("tenant_id"))
        if not tenant:
            raise UsptoMCPError(
                "persisted assurance record requires tenant_id",
                code="invalid_persisted_record",
            )
        cleaned["tenant_id"] = tenant
        if not cleaned.get("matter_id") and not cleaned.get("assurance_id"):
            raise UsptoMCPError(
                "persisted assurance record requires matter_id or assurance_id",
                code="invalid_persisted_record",
            )
        cleaned.setdefault("classification", "confidential_application")
        cleaned.setdefault("findings", [])
        cleaned.setdefault("provenance", {})
        cleaned.setdefault("summary", {})
        with self._lock:
            # Replace by assurance_id or (tenant, matter) key.
            aid = str(cleaned.get("assurance_id") or "").strip()
            mid = str(cleaned.get("matter_id") or "").strip()
            kept: list[dict[str, Any]] = []
            for row in self._rows:
                same_aid = aid and str(row.get("assurance_id") or "") == aid
                same_matter = (
                    mid
                    and str(row.get("tenant_id") or "") == tenant
                    and str(row.get("matter_id") or "") == mid
                    and (not aid or str(row.get("assurance_id") or "") == aid)
                )
                if same_aid or same_matter:
                    continue
                kept.append(row)
            kept.append(cleaned)
            self._rows = kept
        return cleaned

    def get_record(
        self,
        *,
        tenant_id: str | None = None,
        matter_id: str | None = None,
        assurance_id: str | None = None,
        dossier_id: str | None = None,
    ) -> Mapping[str, Any] | None:
        # Intentionally no live sync / filing / payment side effects.
        with self._lock:
            candidates = list(self._rows)
        aid = str(assurance_id or "").strip() or None
        mid = str(matter_id or "").strip() or None
        did = str(dossier_id or "").strip() or None
        tenant = _normalize_tenant(tenant_id)
        for row in candidates:
            if aid and str(row.get("assurance_id") or "") != aid:
                continue
            if mid and str(row.get("matter_id") or "") != mid:
                continue
            if did and str(row.get("dossier_id") or "") != did:
                continue
            # When tenant filter provided, only return matching tenant rows.
            if tenant is not None and _normalize_tenant(row.get("tenant_id")) != tenant:
                continue
            return dict(row)
        # If no id filters matched with tenant filter, try id-only (for oracle checks).
        if tenant is not None and (aid or mid or did):
            for row in candidates:
                if aid and str(row.get("assurance_id") or "") != aid:
                    continue
                if mid and str(row.get("matter_id") or "") != mid:
                    continue
                if did and str(row.get("dossier_id") or "") != did:
                    continue
                # Found a row for another tenant — callers must not learn this.
                return {"__cross_tenant__": True, "tenant_id": row.get("tenant_id")}
        return None

    def clear(self) -> None:
        with self._lock:
            self._rows.clear()


def bind_assurance_store(store: PersistedAssuranceStore | None) -> None:
    """Bind the persisted assurance store used by PATLAW-141 tools."""
    global _bound_assurance_store
    _bound_assurance_store = store


def get_assurance_store() -> PersistedAssuranceStore:
    """Return the bound store or a fresh empty in-memory store."""
    global _bound_assurance_store
    if _bound_assurance_store is None:
        _bound_assurance_store = InMemoryPersistedAssuranceStore()
    return _bound_assurance_store


def reset_assurance_store() -> None:
    """Clear the bound assurance store (tests / process re-init)."""
    global _bound_assurance_store
    _bound_assurance_store = None


def _strip_persisted_bodies(payload: Any) -> Any:
    """Drop private body/content keys from nested mappings/lists."""
    if isinstance(payload, Mapping):
        out: dict[str, Any] = {}
        for key, val in payload.items():
            key_l = str(key).lower()
            if key_l in _PERSISTED_BODY_KEYS or key_l in _PRIVATE_TEXT_KEYS:
                continue
            out[str(key)] = _strip_persisted_bodies(val)
        return out
    if isinstance(payload, (list, tuple)):
        return [_strip_persisted_bodies(item) for item in payload]
    return payload


# ---------------------------------------------------------------------------
# Authorization + redaction helpers
# ---------------------------------------------------------------------------


def assert_mcp_operation_allowed(operation: str) -> None:
    """Fail closed if *operation* is a forbidden MCP capability."""
    key = str(operation or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not key:
        raise UsptoMCPError("operation is required", code="missing_operation")
    if key in FORBIDDEN_MCP_OPERATIONS:
        raise ForbiddenMCPOperationError(key)
    # Strip uspto_ prefix for API-level checks when present.
    bare = key[6:] if key.startswith("uspto_") else key
    if bare in FORBIDDEN_MCP_OPERATIONS:
        raise ForbiddenMCPOperationError(bare)
    if key.startswith(
        (
            "sign_",
            "pay_",
            "file_",
            "submit_",
            "scrape_",
            "browser_",
            "automate_",
            "login_",
            "session_",
            "credential_",
        )
    ):
        raise ForbiddenMCPOperationError(key)
    if _API_AVAILABLE:
        # Also refuse anything the domain API forbids (sign/pay/file/...).
        try:
            if bare in FORBIDDEN_API_OPERATIONS or key in FORBIDDEN_API_OPERATIONS:
                raise ForbiddenMCPOperationError(bare or key)
            # Do not call assert_operation_allowed for projection tool names —
            # only for raw forbidden tokens.
        except ForbiddenAPIOperationError as exc:
            raise ForbiddenMCPOperationError(getattr(exc, "operation", bare)) from exc


def _normalize_tenant(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _classification_of(value: Any) -> Any:
    if value is None:
        if DisclosureClassification is not None:
            return DisclosureClassification.PUBLIC_USER
        return "public_user"
    if DisclosureClassification is not None and isinstance(
        value, DisclosureClassification
    ):
        return value
    if isinstance(value, str):
        if DisclosureClassification is not None:
            try:
                return DisclosureClassification(value.strip())
            except ValueError:
                return DisclosureClassification.UNKNOWN
        return value.strip()
    if isinstance(value, Mapping):
        return _classification_of(value.get("classification"))
    return value


def _resource_tenant_id(payload: Any) -> str | None:
    """Extract tenant binding from labels or explicit fields (never secrets)."""
    if payload is None:
        return None
    if hasattr(payload, "labels"):
        labels = getattr(payload, "labels") or {}
        if isinstance(labels, Mapping):
            for key in ("tenant_id", "tenant", "owner_tenant_id"):
                if key in labels:
                    return _normalize_tenant(labels[key])
    if isinstance(payload, Mapping):
        for key in ("tenant_id", "tenant", "owner_tenant_id"):
            if key in payload:
                return _normalize_tenant(payload[key])
        labels = payload.get("labels") or {}
        if isinstance(labels, Mapping):
            for key in ("tenant_id", "tenant", "owner_tenant_id"):
                if key in labels:
                    return _normalize_tenant(labels[key])
        nested = payload.get("analysis_bundle") or payload.get("matter_summary")
        if nested is not None and nested is not payload:
            return _resource_tenant_id(nested)
    return None


def _store_tenant_id(api: Any) -> str | None:
    store = getattr(api, "_private_store", None)
    if store is None:
        return None
    return _normalize_tenant(getattr(store, "tenant_id", None))


def authorize_tenant_access(
    *,
    caller_tenant_id: str | None,
    resource_tenant_id: str | None = None,
    classification: Any = None,
    private_store_tenant_id: str | None = None,
    require_for_private: bool = True,
) -> None:
    """Deny unauthorized / private cross-tenant access (fail-closed).

    Public classifications may proceed without a tenant. Private or quarantine
    material requires a matching caller tenant; mismatched resource or private
    store tenants are denied.
    """
    cls = _classification_of(classification)
    private = False
    try:
        private = bool(is_private_classification(cls) or requires_quarantine(cls))
    except Exception:
        private = str(cls).lower() not in {
            "public_official",
            "public_user",
            "public",
        }

    caller = _normalize_tenant(caller_tenant_id)
    resource = _normalize_tenant(resource_tenant_id)
    store = _normalize_tenant(private_store_tenant_id)

    if not private and not require_for_private:
        # Public path: still refuse explicit cross-tenant when both provided.
        if caller and resource and caller != resource:
            raise UsptoMCPAuthError(
                "caller tenant_id does not match resource tenant_id",
                code="tenant_mismatch",
            )
        return

    if private:
        if not caller:
            raise UsptoMCPAuthError(
                "private USPTO material requires caller tenant_id",
                code="missing_tenant",
            )
        if resource and resource != caller:
            raise UsptoMCPAuthError(
                "unauthorized private cross-tenant access denied",
                code="tenant_mismatch",
            )
        if store and store != caller:
            raise UsptoMCPAuthError(
                "private store tenant_id does not match caller tenant_id",
                code="tenant_mismatch",
            )
        return

    # Non-private but both sides present: still enforce equality.
    if caller and resource and caller != resource:
        raise UsptoMCPAuthError(
            "caller tenant_id does not match resource tenant_id",
            code="tenant_mismatch",
        )


def _coerce_output_policy(value: Any) -> Any:
    if not _API_AVAILABLE:
        return value
    if value is None:
        return DEFAULT_OUTPUT_POLICY
    if isinstance(value, OutputRedactionPolicy):
        return value
    if isinstance(value, Mapping):
        return OutputRedactionPolicy.from_dict(value)
    raise UsptoMCPError(
        "output_policy must be OutputRedactionPolicy or mapping",
        code="invalid_output_policy",
    )


def _policy_dict(policy: Any) -> dict[str, Any]:
    if policy is None:
        return {"mode": "redact_private"}
    if hasattr(policy, "to_dict"):
        return dict(policy.to_dict())
    if isinstance(policy, Mapping):
        return dict(policy)
    return {"mode": str(policy)}


def apply_output_redaction(
    payload: Any,
    *,
    classification: Any = None,
    output_policy: Any = None,
) -> Any:
    """Policy-driven surface-text redaction + credential scrubbing."""
    policy = _coerce_output_policy(output_policy)
    cleaned = scrub_credential_fields(payload)
    cls = _classification_of(classification)

    must_redact = False
    redaction_token = "[REDACTED]"
    mode = "redact_private"
    if policy is not None and hasattr(policy, "must_redact"):
        try:
            must_redact = bool(policy.must_redact(cls))
        except Exception:
            must_redact = is_private_classification(cls) or requires_quarantine(cls)
        redaction_token = str(getattr(policy, "redaction_token", redaction_token))
        mode_obj = getattr(policy, "mode", None)
        mode = getattr(mode_obj, "value", None) or str(mode_obj or mode)
    else:
        must_redact = is_private_classification(cls) or requires_quarantine(cls)

    if mode == "identifiers_only" or (
        OutputPolicyMode is not None
        and getattr(policy, "mode", None) is OutputPolicyMode.IDENTIFIERS_ONLY
    ):
        must_redact = True

    if not must_redact:
        return cleaned

    return _redact_private_text(cleaned, redaction_token=redaction_token)


def _redact_private_text(payload: Any, *, redaction_token: str) -> Any:
    if isinstance(payload, Mapping):
        out: dict[str, Any] = {}
        for key, val in payload.items():
            key_l = str(key).lower()
            if key_l in _PRIVATE_TEXT_KEYS:
                out[str(key)] = redaction_token
            else:
                out[str(key)] = _redact_private_text(
                    val, redaction_token=redaction_token
                )
        return out
    if isinstance(payload, (list, tuple)):
        return [
            _redact_private_text(item, redaction_token=redaction_token)
            for item in payload
        ]
    return payload


def _success(
    tool: str,
    result: Mapping[str, Any] | dict[str, Any],
    *,
    output_policy: Any = None,
    redaction_applied: bool = False,
    api_operation: str | None = None,
) -> dict[str, Any]:
    return scrub_credential_fields(
        {
            "status": "success",
            "tool": tool,
            "interface": USPTO_MCP_INTERFACE,
            "schema": USPTO_MCP_SCHEMA,
            "tool_version": USPTO_MCP_TOOL_VERSION,
            "api_operation": api_operation or TOOL_TO_API_OPERATION.get(tool),
            "read_only": True,
            "result": dict(result),
            "output_policy": _policy_dict(output_policy),
            "redaction_applied": redaction_applied,
        }
    )


def _error(
    tool: str,
    exc: BaseException,
    *,
    code: str | None = None,
) -> dict[str, Any]:
    err_code = code
    if err_code is None:
        err_code = getattr(exc, "code", None) or type(exc).__name__
    return scrub_credential_fields(
        {
            "status": "error",
            "tool": tool,
            "interface": USPTO_MCP_INTERFACE,
            "schema": USPTO_MCP_SCHEMA,
            "tool_version": USPTO_MCP_TOOL_VERSION,
            "error": str(exc)[:512],
            "code": str(err_code),
            "read_only": True,
        }
    )


def _contract_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return scrub_credential_fields(dict(value))
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return scrub_credential_fields(dict(value.to_dict()))
    api = get_api()
    if hasattr(api, "to_contract_dict"):
        return scrub_credential_fields(api.to_contract_dict(value))
    return scrub_credential_fields({"value": str(value)})


# ---------------------------------------------------------------------------
# Schema discovery
# ---------------------------------------------------------------------------


def list_uspto_tools() -> list[dict[str, Any]]:
    """Return documented read-only tool schemas (no forbidden operations).

    Returns the PATLAW-061 v1 surface only. Use
    :func:`list_persisted_assurance_tools` for PATLAW-141 tools.
    """
    return [dict(TOOL_SCHEMAS[name]) for name in READ_ONLY_TOOL_NAMES]


def list_persisted_assurance_tools() -> list[dict[str, Any]]:
    """Return PATLAW-141 persisted assurance query schemas."""
    return [
        dict(PERSISTED_ASSURANCE_TOOL_SCHEMAS[name])
        for name in PERSISTED_ASSURANCE_TOOL_NAMES
    ]


def list_all_uspto_tools() -> list[dict[str, Any]]:
    """v1 read-only tools plus persisted assurance tools."""
    return list_uspto_tools() + list_persisted_assurance_tools()


def get_tool_schema(name: str) -> dict[str, Any] | None:
    """Return one tool schema by name, or ``None``."""
    key = str(name or "").strip()
    if key in TOOL_SCHEMAS:
        return dict(TOOL_SCHEMAS[key])
    if key in PERSISTED_ASSURANCE_TOOL_SCHEMAS:
        return dict(PERSISTED_ASSURANCE_TOOL_SCHEMAS[key])
    return None


def list_forbidden_operations() -> list[str]:
    """Sorted forbidden MCP operation names (audit / discovery)."""
    return sorted(FORBIDDEN_MCP_OPERATIONS)


def schemas_are_read_only() -> bool:
    """True when every documented schema is marked read_only and has no forbidden ops."""
    banned_tokens = (
        "sign",
        "pay",
        "file",
        "session",
        "credential",
        "password",
        "cookie",
        "mfa",
        "browser",
        "login",
        "submit",
    )
    for name, schema in TOOL_SCHEMAS.items():
        if not schema.get("read_only", False):
            return False
        # Tool *names* and operation fields must not be forbidden capabilities.
        for field in (name, schema.get("python_operation", ""), schema.get("name", "")):
            token = str(field).strip().lower().replace("-", "_")
            bare = token[6:] if token.startswith("uspto_") else token
            if bare in FORBIDDEN_MCP_OPERATIONS or token in FORBIDDEN_MCP_OPERATIONS:
                return False
        # Schema must not advertise forbidden operations as properties keys.
        params = schema.get("parameters") or {}
        props = params.get("properties") or {}
        for prop in props:
            prop_l = str(prop).lower()
            if prop_l in {"password", "api_key", "secret", "token", "cookie", "session"}:
                # credential_ref is allowed (reference only); bare secrets are not.
                return False
        # Description may mention "no file" etc.; ensure no operation entry.
        if schema.get("operation") in banned_tokens:
            return False
    return True


# ---------------------------------------------------------------------------
# Tool implementations (async MCP entrypoints)
# ---------------------------------------------------------------------------


async def uspto_status(
    application_number: str,
    matter_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    force_refresh: bool = False,
    credential_ref: Optional[str] = None,
    output_policy: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Read-only public application status via ``USPTOAnalysisAPI.status``."""
    tool = "uspto_status"
    try:
        assert_mcp_operation_allowed(tool)
        if not application_number or not str(application_number).strip():
            raise UsptoMCPError(
                "application_number is required", code="missing_application_number"
            )
        api = get_api()
        ref = None
        if credential_ref:
            ref = CredentialRef(reference_id=str(credential_ref).strip())
        result = api.status(
            str(application_number).strip(),
            matter_id=matter_id or None,
            force_refresh=bool(force_refresh),
            credential_ref=ref,
        )
        payload = _contract_dict(result)
        # Status is public ODP data; still scrub + optional policy projection.
        policy = _coerce_output_policy(output_policy)
        classification = payload.get("classification") or "public_official"
        # If a private store is bound, refuse cross-tenant misuse of the tool
        # when the caller asserts a conflicting tenant.
        authorize_tenant_access(
            caller_tenant_id=tenant_id,
            resource_tenant_id=_resource_tenant_id(payload),
            classification=classification,
            private_store_tenant_id=_store_tenant_id(api),
            require_for_private=True,
        )
        redacted = apply_output_redaction(
            payload, classification=classification, output_policy=policy
        )
        return _success(
            tool,
            redacted if isinstance(redacted, Mapping) else {"status": redacted},
            output_policy=policy,
            redaction_applied=bool(
                isinstance(redacted, Mapping)
                and redacted is not payload
                and is_private_classification(_classification_of(classification))
            ),
            api_operation="status",
        )
    except (
        UsptoMCPError,
        UsptoAPIError,
        ForbiddenAPIOperationError,
        ForbiddenMCPOperationError,
        UsptoMCPAuthError,
    ) as exc:
        return _error(tool, exc)
    except Exception as exc:  # pragma: no cover - unexpected
        logger.exception("uspto_status failed")
        return _error(tool, exc, code="internal_error")


async def uspto_dossier_summary(
    matter_id: Optional[str] = None,
    analysis_bundle: Optional[Mapping[str, Any]] = None,
    tenant_id: Optional[str] = None,
    seed_classification: str = "public_user",
    output_policy: Optional[Mapping[str, Any]] = None,
    labels: Optional[Mapping[str, str]] = None,
) -> dict[str, Any]:
    """Read-only dossier / analysis-bundle summary via ``analyze``."""
    tool = "uspto_dossier_summary"
    try:
        assert_mcp_operation_allowed(tool)
        api = get_api()
        policy = _coerce_output_policy(output_policy)
        label_map: dict[str, str] = dict(labels or {})
        if tenant_id:
            label_map.setdefault("tenant_id", str(tenant_id).strip())

        result = api.analyze(
            analysis_bundle=analysis_bundle,
            matter_id=matter_id,
            seed_classification=seed_classification,
            labels=label_map or None,
        )
        dossier = getattr(result, "dossier", None)
        bundle = getattr(result, "analysis_bundle", None)
        classification = (
            getattr(dossier, "classification", None)
            or getattr(bundle, "classification", None)
            or seed_classification
        )
        resource_tenant = (
            _resource_tenant_id(dossier)
            or _resource_tenant_id(bundle)
            or _resource_tenant_id(analysis_bundle)
            or label_map.get("tenant_id")
        )
        authorize_tenant_access(
            caller_tenant_id=tenant_id,
            resource_tenant_id=resource_tenant,
            classification=classification,
            private_store_tenant_id=_store_tenant_id(api),
        )

        if dossier is not None and hasattr(dossier, "public_projection"):
            summary = dossier.public_projection()
        elif bundle is not None and hasattr(bundle, "public_projection"):
            summary = bundle.public_projection()
        else:
            summary = _contract_dict(result)

        redacted = apply_output_redaction(
            summary, classification=classification, output_policy=policy
        )
        redaction_applied = bool(
            is_private_classification(_classification_of(classification))
            or requires_quarantine(_classification_of(classification))
        )
        return _success(
            tool,
            {
                "summary": redacted,
                "classification": (
                    classification.value
                    if hasattr(classification, "value")
                    else str(classification)
                ),
                "matter_id": getattr(bundle, "matter_id", None) or matter_id,
            },
            output_policy=policy,
            redaction_applied=redaction_applied,
            api_operation="analyze",
        )
    except (
        UsptoMCPError,
        UsptoAPIError,
        ForbiddenAPIOperationError,
        ForbiddenMCPOperationError,
        UsptoMCPAuthError,
    ) as exc:
        return _error(tool, exc)
    except Exception as exc:  # pragma: no cover
        logger.exception("uspto_dossier_summary failed")
        return _error(tool, exc, code="internal_error")


def _explain_report(
    api: Any,
    *,
    analysis_bundle: Mapping[str, Any] | Any | None,
    gap_report: Mapping[str, Any] | Any | None,
    matter_id: str | None,
    analysis_id: str | None,
    output_policy: Any,
    labels: Mapping[str, str] | None,
) -> Any:
    """Call canonical ``api.explain`` (no local analysis duplication)."""
    return api.explain(
        analysis_bundle=analysis_bundle,
        gap_report=gap_report,
        output_policy=output_policy,
        matter_id=matter_id,
        analysis_id=analysis_id,
        labels=labels or {},
    )


def _authorize_report(
    api: Any,
    report: Any,
    *,
    tenant_id: str | None,
    analysis_bundle: Any,
) -> None:
    classification = getattr(report, "classification", None)
    if classification is None and isinstance(analysis_bundle, Mapping):
        classification = analysis_bundle.get("classification")
    resource_tenant = (
        _resource_tenant_id(report)
        or _resource_tenant_id(analysis_bundle)
        or _resource_tenant_id(getattr(report, "matter_summary", None))
    )
    authorize_tenant_access(
        caller_tenant_id=tenant_id,
        resource_tenant_id=resource_tenant,
        classification=classification,
        private_store_tenant_id=_store_tenant_id(api),
    )


async def uspto_requirement_matrix(
    analysis_bundle: Optional[Mapping[str, Any]] = None,
    gap_report: Optional[Mapping[str, Any]] = None,
    matter_id: Optional[str] = None,
    analysis_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    output_policy: Optional[Mapping[str, Any]] = None,
    labels: Optional[Mapping[str, str]] = None,
) -> dict[str, Any]:
    """Read-only requirement matrix via ``USPTOAnalysisAPI.explain``."""
    tool = "uspto_requirement_matrix"
    try:
        assert_mcp_operation_allowed(tool)
        if analysis_bundle is None and gap_report is None:
            if not matter_id:
                raise UsptoMCPError(
                    "analysis_bundle, gap_report, or matter_id is required",
                    code="missing_explain_input",
                )
            # Build a minimal bundle through the canonical analyze path first.
            api = get_api()
            analyzed = api.analyze(matter_id=matter_id, labels=labels or {})
            analysis_bundle = analyzed.analysis_bundle
        api = get_api()
        policy = _coerce_output_policy(output_policy)
        label_map: dict[str, str] = dict(labels or {})
        if tenant_id:
            label_map.setdefault("tenant_id", str(tenant_id).strip())

        report = _explain_report(
            api,
            analysis_bundle=analysis_bundle,
            gap_report=gap_report,
            matter_id=matter_id,
            analysis_id=analysis_id,
            output_policy=policy,
            labels=label_map,
        )
        _authorize_report(
            api, report, tenant_id=tenant_id, analysis_bundle=analysis_bundle
        )

        classification = getattr(report, "classification", "public_user")
        rows = [
            _contract_dict(row) for row in (getattr(report, "requirement_rows", ()) or ())
        ]
        payload = {
            "report_id": getattr(report, "report_id", None),
            "source_bundle_id": getattr(report, "source_bundle_id", None),
            "source_bundle_digest": getattr(report, "source_bundle_digest", None),
            "label": (
                report.label.value
                if hasattr(getattr(report, "label", None), "value")
                else getattr(report, "label", None)
            ),
            "classification": (
                classification.value
                if hasattr(classification, "value")
                else str(classification)
            ),
            "requirement_rows": rows,
            "requirement_row_count": len(rows),
            "mandatory_review_remaining": getattr(
                report, "mandatory_review_remaining", True
            ),
            "gap_count": getattr(report, "gap_count", 0),
            "unknown_count": getattr(report, "unknown_count", 0),
        }
        redacted = apply_output_redaction(
            payload, classification=classification, output_policy=policy
        )
        return _success(
            tool,
            redacted if isinstance(redacted, Mapping) else {"matrix": redacted},
            output_policy=policy,
            redaction_applied=bool(getattr(report, "redaction_applied", False))
            or is_private_classification(_classification_of(classification)),
            api_operation="explain",
        )
    except (
        UsptoMCPError,
        UsptoAPIError,
        ForbiddenAPIOperationError,
        ForbiddenMCPOperationError,
        UsptoMCPAuthError,
    ) as exc:
        return _error(tool, exc)
    except Exception as exc:  # pragma: no cover
        logger.exception("uspto_requirement_matrix failed")
        return _error(tool, exc, code="internal_error")


async def uspto_evidence_gaps(
    analysis_bundle: Optional[Mapping[str, Any]] = None,
    gap_report: Optional[Mapping[str, Any]] = None,
    matter_id: Optional[str] = None,
    analysis_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    output_policy: Optional[Mapping[str, Any]] = None,
    labels: Optional[Mapping[str, str]] = None,
) -> dict[str, Any]:
    """Read-only evidence gaps / unknowns via ``explain``."""
    tool = "uspto_evidence_gaps"
    try:
        assert_mcp_operation_allowed(tool)
        api = get_api()
        if analysis_bundle is None and gap_report is None:
            if not matter_id:
                raise UsptoMCPError(
                    "analysis_bundle, gap_report, or matter_id is required",
                    code="missing_explain_input",
                )
            analyzed = api.analyze(matter_id=matter_id, labels=labels or {})
            analysis_bundle = analyzed.analysis_bundle
        policy = _coerce_output_policy(output_policy)
        label_map: dict[str, str] = dict(labels or {})
        if tenant_id:
            label_map.setdefault("tenant_id", str(tenant_id).strip())

        report = _explain_report(
            api,
            analysis_bundle=analysis_bundle,
            gap_report=gap_report,
            matter_id=matter_id,
            analysis_id=analysis_id,
            output_policy=policy,
            labels=label_map,
        )
        _authorize_report(
            api, report, tenant_id=tenant_id, analysis_bundle=analysis_bundle
        )
        classification = getattr(report, "classification", "public_user")

        gap_rows = []
        for row in getattr(report, "requirement_rows", ()) or ():
            status = getattr(row, "status", None)
            status_v = status.value if hasattr(status, "value") else str(status or "")
            gap_status = getattr(row, "gap_status", None)
            gap_v = (
                gap_status.value if hasattr(gap_status, "value") else str(gap_status or "")
            )
            if status_v in {"unsatisfied", "gap", "missing", "unknown"} or gap_v in {
                "unsatisfied",
                "gap",
                "missing",
                "unknown",
            }:
                gap_rows.append(_contract_dict(row))

        unknowns = [
            _contract_dict(u) for u in (getattr(report, "unknowns", ()) or ())
        ]
        actions = [
            _contract_dict(a) for a in (getattr(report, "reviewer_actions", ()) or ())
        ]
        payload = {
            "report_id": getattr(report, "report_id", None),
            "source_bundle_id": getattr(report, "source_bundle_id", None),
            "source_bundle_digest": getattr(report, "source_bundle_digest", None),
            "classification": (
                classification.value
                if hasattr(classification, "value")
                else str(classification)
            ),
            "gap_count": getattr(report, "gap_count", len(gap_rows)),
            "unknown_count": getattr(report, "unknown_count", len(unknowns)),
            "gaps": gap_rows,
            "unknowns": unknowns,
            "reviewer_actions": actions,
            "mandatory_review_remaining": getattr(
                report, "mandatory_review_remaining", True
            ),
            "warnings": list(getattr(report, "warnings", ()) or ()),
            "reason_codes": list(getattr(report, "reason_codes", ()) or ()),
        }
        redacted = apply_output_redaction(
            payload, classification=classification, output_policy=policy
        )
        return _success(
            tool,
            redacted if isinstance(redacted, Mapping) else {"gaps": redacted},
            output_policy=policy,
            redaction_applied=bool(getattr(report, "redaction_applied", False))
            or is_private_classification(_classification_of(classification)),
            api_operation="explain",
        )
    except (
        UsptoMCPError,
        UsptoAPIError,
        ForbiddenAPIOperationError,
        ForbiddenMCPOperationError,
        UsptoMCPAuthError,
    ) as exc:
        return _error(tool, exc)
    except Exception as exc:  # pragma: no cover
        logger.exception("uspto_evidence_gaps failed")
        return _error(tool, exc, code="internal_error")


async def uspto_citation_explanation(
    analysis_bundle: Optional[Mapping[str, Any]] = None,
    gap_report: Optional[Mapping[str, Any]] = None,
    matter_id: Optional[str] = None,
    analysis_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    output_policy: Optional[Mapping[str, Any]] = None,
    labels: Optional[Mapping[str, str]] = None,
) -> dict[str, Any]:
    """Read-only citation / authority explanation via ``explain``."""
    tool = "uspto_citation_explanation"
    try:
        assert_mcp_operation_allowed(tool)
        api = get_api()
        if analysis_bundle is None and gap_report is None:
            if not matter_id:
                raise UsptoMCPError(
                    "analysis_bundle, gap_report, or matter_id is required",
                    code="missing_explain_input",
                )
            analyzed = api.analyze(matter_id=matter_id, labels=labels or {})
            analysis_bundle = analyzed.analysis_bundle
        policy = _coerce_output_policy(output_policy)
        label_map: dict[str, str] = dict(labels or {})
        if tenant_id:
            label_map.setdefault("tenant_id", str(tenant_id).strip())

        report = _explain_report(
            api,
            analysis_bundle=analysis_bundle,
            gap_report=gap_report,
            matter_id=matter_id,
            analysis_id=analysis_id,
            output_policy=policy,
            labels=label_map,
        )
        _authorize_report(
            api, report, tenant_id=tenant_id, analysis_bundle=analysis_bundle
        )
        classification = getattr(report, "classification", "public_user")

        authority_kind = None
        if StatementKind is not None:
            authority_kind = StatementKind.AUTHORITY

        citations: list[dict[str, Any]] = []
        for stmt in getattr(report, "statements", ()) or ():
            kind = getattr(stmt, "kind", None)
            kind_v = kind.value if hasattr(kind, "value") else str(kind or "")
            links = list(getattr(stmt, "source_links", ()) or ())
            has_authority = any(
                getattr(link, "authority_ids", ()) for link in links
            )
            if (
                kind is authority_kind
                or kind_v in {"authority", "requirement", "evidence"}
                or has_authority
            ):
                citations.append(_contract_dict(stmt))

        # Also surface authority ids from requirement rows.
        authority_ids: list[str] = []
        for row in getattr(report, "requirement_rows", ()) or ():
            for aid in getattr(row, "authority_ids", ()) or ():
                if aid not in authority_ids:
                    authority_ids.append(str(aid))

        payload = {
            "report_id": getattr(report, "report_id", None),
            "source_bundle_id": getattr(report, "source_bundle_id", None),
            "source_bundle_digest": getattr(report, "source_bundle_digest", None),
            "classification": (
                classification.value
                if hasattr(classification, "value")
                else str(classification)
            ),
            "citations": citations,
            "authority_ids": authority_ids,
            "citation_count": len(citations),
        }
        redacted = apply_output_redaction(
            payload, classification=classification, output_policy=policy
        )
        return _success(
            tool,
            redacted if isinstance(redacted, Mapping) else {"citations": redacted},
            output_policy=policy,
            redaction_applied=bool(getattr(report, "redaction_applied", False))
            or is_private_classification(_classification_of(classification)),
            api_operation="explain",
        )
    except (
        UsptoMCPError,
        UsptoAPIError,
        ForbiddenAPIOperationError,
        ForbiddenMCPOperationError,
        UsptoMCPAuthError,
    ) as exc:
        return _error(tool, exc)
    except Exception as exc:  # pragma: no cover
        logger.exception("uspto_citation_explanation failed")
        return _error(tool, exc, code="internal_error")


async def uspto_analysis_replay(
    analysis_bundle: Mapping[str, Any],
    tenant_id: Optional[str] = None,
    output_policy: Optional[Mapping[str, Any]] = None,
    labels: Optional[Mapping[str, str]] = None,
) -> dict[str, Any]:
    """Deterministic analysis + explain replay from a bound analysis bundle."""
    tool = "uspto_analysis_replay"
    try:
        assert_mcp_operation_allowed(tool)
        if not analysis_bundle:
            raise UsptoMCPError(
                "analysis_bundle is required for replay",
                code="missing_analysis_bundle",
            )
        api = get_api()
        policy = _coerce_output_policy(output_policy)
        label_map: dict[str, str] = dict(labels or {})
        if tenant_id:
            label_map.setdefault("tenant_id", str(tenant_id).strip())

        # Source digest before replay (from input mapping or object).
        if isinstance(analysis_bundle, Mapping):
            source_digest = analysis_bundle.get("bundle_digest")
            source_id = analysis_bundle.get("bundle_id")
            source_classification = analysis_bundle.get("classification")
        else:
            source_digest = getattr(analysis_bundle, "bundle_digest", None)
            source_id = getattr(analysis_bundle, "bundle_id", None)
            source_classification = getattr(analysis_bundle, "classification", None)

        authorize_tenant_access(
            caller_tenant_id=tenant_id,
            resource_tenant_id=_resource_tenant_id(analysis_bundle),
            classification=source_classification or "public_user",
            private_store_tenant_id=_store_tenant_id(api),
        )

        analyzed = api.analyze(
            analysis_bundle=analysis_bundle,
            labels=label_map or None,
        )
        bundle = analyzed.analysis_bundle
        report = api.explain(
            bundle,
            output_policy=policy,
            labels=label_map,
        )

        replayed_digest = getattr(bundle, "bundle_digest", None)
        digest_match = (
            source_digest is not None
            and replayed_digest is not None
            and str(source_digest) == str(replayed_digest)
        )
        classification = getattr(bundle, "classification", source_classification)

        summary = (
            bundle.public_projection()
            if hasattr(bundle, "public_projection")
            else _contract_dict(bundle)
        )
        report_public = (
            report.public_projection()
            if hasattr(report, "public_projection")
            else {
                "report_id": getattr(report, "report_id", None),
                "source_bundle_digest": getattr(report, "source_bundle_digest", None),
            }
        )
        payload = {
            "source_bundle_id": source_id,
            "source_bundle_digest": source_digest,
            "replayed_bundle_id": getattr(bundle, "bundle_id", None),
            "replayed_bundle_digest": replayed_digest,
            "digest_match": bool(digest_match),
            "report_bound_digest": getattr(report, "source_bundle_digest", None),
            "report_binding_ok": (
                str(getattr(report, "source_bundle_digest", "")) == str(replayed_digest)
                if replayed_digest
                else False
            ),
            "bundle_summary": summary,
            "gap_report_summary": report_public,
            "classification": (
                classification.value
                if hasattr(classification, "value")
                else str(classification or "")
            ),
        }
        redacted = apply_output_redaction(
            payload, classification=classification, output_policy=policy
        )
        return _success(
            tool,
            redacted if isinstance(redacted, Mapping) else {"replay": redacted},
            output_policy=policy,
            redaction_applied=is_private_classification(
                _classification_of(classification)
            ),
            api_operation="analyze",
        )
    except (
        UsptoMCPError,
        UsptoAPIError,
        ForbiddenAPIOperationError,
        ForbiddenMCPOperationError,
        UsptoMCPAuthError,
    ) as exc:
        return _error(tool, exc)
    except Exception as exc:  # pragma: no cover
        logger.exception("uspto_analysis_replay failed")
        return _error(tool, exc, code="internal_error")


# ---------------------------------------------------------------------------
# Persisted assurance query helpers (PATLAW-141)
# ---------------------------------------------------------------------------


def _access_denied_error(tool: str) -> dict[str, Any]:
    """Uniform denial — no existence oracle for unauthorized callers."""
    return _error(
        tool,
        UsptoMCPAuthError(ACCESS_DENIED_MESSAGE, code=ACCESS_DENIED_CODE),
        code=ACCESS_DENIED_CODE,
    )


def _lookup_persisted_record(
    *,
    tool: str,
    tenant_id: str | None,
    matter_id: str | None,
    assurance_id: str | None,
    dossier_id: str | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Return ``(record, error_envelope)``.

    Unauthorized tenants always receive the same access_denied envelope whether
    the row is missing or owned by another tenant (no existence oracle).
    """
    if not any((matter_id, assurance_id, dossier_id)):
        return None, _error(
            tool,
            UsptoMCPError(
                "matter_id, assurance_id, or dossier_id is required",
                code="missing_lookup_key",
            ),
        )

    store = get_assurance_store()
    # Never invoke live domain operations from persisted tools.
    if hasattr(store, "live_sync_calls"):
        # Counter present on InMemoryPersistedAssuranceStore for tests.
        pass

    raw = store.get_record(
        tenant_id=tenant_id,
        matter_id=matter_id,
        assurance_id=assurance_id,
        dossier_id=dossier_id,
    )

    caller = _normalize_tenant(tenant_id)

    if raw is not None and raw.get("__cross_tenant__"):
        # Row exists for another tenant — never reveal existence.
        return None, _access_denied_error(tool)

    if raw is None:
        # Missing row: unauthorized callers still get access_denied (oracle-safe).
        # Authorized callers with a tenant may learn not_found.
        if not caller:
            return None, _access_denied_error(tool)
        # Probe without tenant filter to detect foreign ownership.
        foreign = store.get_record(
            tenant_id=None,
            matter_id=matter_id,
            assurance_id=assurance_id,
            dossier_id=dossier_id,
        )
        if foreign is not None and _normalize_tenant(foreign.get("tenant_id")) not in (
            None,
            caller,
        ):
            return None, _access_denied_error(tool)
        return None, _error(
            tool,
            UsptoMCPError("persisted assurance record not found", code="not_found"),
            code="not_found",
        )

    resource_tenant = _normalize_tenant(raw.get("tenant_id"))
    classification = raw.get("classification") or "confidential_application"
    try:
        authorize_tenant_access(
            caller_tenant_id=caller,
            resource_tenant_id=resource_tenant,
            classification=classification,
            require_for_private=True,
        )
    except UsptoMCPAuthError:
        # Collapse all auth failures to access_denied (no oracle).
        return None, _access_denied_error(tool)

    return dict(raw), None


def _protected_dossier_link(record: Mapping[str, Any]) -> str | None:
    """Build a protected dossier reference (never embeds content)."""
    explicit = record.get("dossier_link") or record.get("protected_dossier_link")
    if explicit:
        return str(explicit)
    dossier_id = record.get("dossier_id")
    if not dossier_id:
        return None
    return f"protected://dossier/{dossier_id}"


def _summary_projection(record: Mapping[str, Any]) -> dict[str, Any]:
    summary = record.get("summary")
    if not isinstance(summary, Mapping):
        summary = {}
    base = {
        "assurance_id": record.get("assurance_id"),
        "matter_id": record.get("matter_id"),
        "dossier_id": record.get("dossier_id"),
        "dossier_link": _protected_dossier_link(record),
        "tenant_id": record.get("tenant_id"),
        "classification": record.get("classification"),
        "disposition": record.get("disposition"),
        "review_state": record.get("review_state"),
        "bundle_digest": record.get("bundle_digest"),
        "parser_digest": record.get("parser_digest"),
        "content_digest": record.get("content_digest"),
        "reason_codes": list(record.get("reason_codes") or []),
        "labels": dict(record.get("labels") or {}),
        "opaque_matter_ref": record.get("opaque_matter_ref"),
        "is_review_only": record.get("is_review_only", True),
        "is_legal_advice": False,
        "live_sync_triggered": False,
        "filing_or_payment_triggered": False,
    }
    # Merge safe summary keys (already body-stripped on put).
    for key, val in summary.items():
        if str(key).lower() in _PERSISTED_BODY_KEYS or str(key).lower() in _PRIVATE_TEXT_KEYS:
            continue
        if key not in base or base[key] in (None, "", [], {}):
            base[str(key)] = val
    return _strip_persisted_bodies(base)


def _findings_projection(record: Mapping[str, Any]) -> dict[str, Any]:
    findings = record.get("findings") or record.get("items") or []
    if not isinstance(findings, (list, tuple)):
        findings = []
    safe_items: list[dict[str, Any]] = []
    for item in findings:
        if not isinstance(item, Mapping):
            continue
        safe_items.append(
            _strip_persisted_bodies(
                {
                    "item_id": item.get("item_id") or item.get("id"),
                    "kind": item.get("kind"),
                    "code": item.get("code") or item.get("reason_code"),
                    "requirement_id": item.get("requirement_id"),
                    "status": item.get("status"),
                    # Explicitly omit body/text/content.
                }
            )
        )
    return {
        "assurance_id": record.get("assurance_id"),
        "matter_id": record.get("matter_id"),
        "dossier_id": record.get("dossier_id"),
        "dossier_link": _protected_dossier_link(record),
        "tenant_id": record.get("tenant_id"),
        "classification": record.get("classification"),
        "findings": safe_items,
        "finding_count": len(safe_items),
        "live_sync_triggered": False,
        "filing_or_payment_triggered": False,
    }


def _provenance_projection(record: Mapping[str, Any]) -> dict[str, Any]:
    provenance = record.get("provenance")
    if not isinstance(provenance, Mapping):
        provenance = {}
    cleaned = _strip_persisted_bodies(dict(provenance))
    return {
        "assurance_id": record.get("assurance_id"),
        "matter_id": record.get("matter_id"),
        "dossier_id": record.get("dossier_id"),
        "dossier_link": _protected_dossier_link(record),
        "tenant_id": record.get("tenant_id"),
        "classification": record.get("classification"),
        "bundle_digest": record.get("bundle_digest"),
        "parser_digest": record.get("parser_digest"),
        "content_digest": record.get("content_digest"),
        "stage_input_digests": dict(record.get("stage_input_digests") or {}),
        "stage_output_digests": dict(record.get("stage_output_digests") or {}),
        "committed_stages": list(record.get("committed_stages") or []),
        "provenance": cleaned,
        "live_sync_triggered": False,
        "filing_or_payment_triggered": False,
    }


async def uspto_persisted_assurance_summary(
    tenant_id: Optional[str] = None,
    matter_id: Optional[str] = None,
    assurance_id: Optional[str] = None,
    dossier_id: Optional[str] = None,
    output_policy: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Read-only query of a persisted assurance/dossier summary (no live sync)."""
    tool = "uspto_persisted_assurance_summary"
    try:
        assert_mcp_operation_allowed(tool)
        record, err = _lookup_persisted_record(
            tool=tool,
            tenant_id=tenant_id,
            matter_id=matter_id,
            assurance_id=assurance_id,
            dossier_id=dossier_id,
        )
        if err is not None:
            return err
        assert record is not None
        policy = _coerce_output_policy(output_policy)
        payload = _summary_projection(record)
        redacted = apply_output_redaction(
            payload,
            classification=record.get("classification"),
            output_policy=policy,
        )
        return _success(
            tool,
            redacted if isinstance(redacted, Mapping) else {"summary": redacted},
            output_policy=policy,
            redaction_applied=is_private_classification(
                _classification_of(record.get("classification"))
            ),
            api_operation="persisted_read",
        )
    except (
        UsptoMCPError,
        UsptoAPIError,
        ForbiddenAPIOperationError,
        ForbiddenMCPOperationError,
        UsptoMCPAuthError,
    ) as exc:
        if getattr(exc, "code", None) in {
            "tenant_mismatch",
            "missing_tenant",
            "unauthorized_tenant",
        }:
            return _access_denied_error(tool)
        return _error(tool, exc)
    except Exception as exc:  # pragma: no cover
        logger.exception("uspto_persisted_assurance_summary failed")
        return _error(tool, exc, code="internal_error")


async def uspto_persisted_assurance_findings(
    tenant_id: Optional[str] = None,
    matter_id: Optional[str] = None,
    assurance_id: Optional[str] = None,
    dossier_id: Optional[str] = None,
    output_policy: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Read-only query of persisted assurance findings (codes only; no bodies)."""
    tool = "uspto_persisted_assurance_findings"
    try:
        assert_mcp_operation_allowed(tool)
        record, err = _lookup_persisted_record(
            tool=tool,
            tenant_id=tenant_id,
            matter_id=matter_id,
            assurance_id=assurance_id,
            dossier_id=dossier_id,
        )
        if err is not None:
            return err
        assert record is not None
        policy = _coerce_output_policy(output_policy)
        payload = _findings_projection(record)
        redacted = apply_output_redaction(
            payload,
            classification=record.get("classification"),
            output_policy=policy,
        )
        return _success(
            tool,
            redacted if isinstance(redacted, Mapping) else {"findings": redacted},
            output_policy=policy,
            redaction_applied=is_private_classification(
                _classification_of(record.get("classification"))
            ),
            api_operation="persisted_read",
        )
    except (
        UsptoMCPError,
        UsptoAPIError,
        ForbiddenAPIOperationError,
        ForbiddenMCPOperationError,
        UsptoMCPAuthError,
    ) as exc:
        if getattr(exc, "code", None) in {
            "tenant_mismatch",
            "missing_tenant",
            "unauthorized_tenant",
        }:
            return _access_denied_error(tool)
        return _error(tool, exc)
    except Exception as exc:  # pragma: no cover
        logger.exception("uspto_persisted_assurance_findings failed")
        return _error(tool, exc, code="internal_error")


async def uspto_persisted_assurance_provenance(
    tenant_id: Optional[str] = None,
    matter_id: Optional[str] = None,
    assurance_id: Optional[str] = None,
    dossier_id: Optional[str] = None,
    output_policy: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Read-only query of persisted provenance digests and dossier links."""
    tool = "uspto_persisted_assurance_provenance"
    try:
        assert_mcp_operation_allowed(tool)
        record, err = _lookup_persisted_record(
            tool=tool,
            tenant_id=tenant_id,
            matter_id=matter_id,
            assurance_id=assurance_id,
            dossier_id=dossier_id,
        )
        if err is not None:
            return err
        assert record is not None
        policy = _coerce_output_policy(output_policy)
        payload = _provenance_projection(record)
        redacted = apply_output_redaction(
            payload,
            classification=record.get("classification"),
            output_policy=policy,
        )
        return _success(
            tool,
            redacted if isinstance(redacted, Mapping) else {"provenance": redacted},
            output_policy=policy,
            redaction_applied=is_private_classification(
                _classification_of(record.get("classification"))
            ),
            api_operation="persisted_read",
        )
    except (
        UsptoMCPError,
        UsptoAPIError,
        ForbiddenAPIOperationError,
        ForbiddenMCPOperationError,
        UsptoMCPAuthError,
    ) as exc:
        if getattr(exc, "code", None) in {
            "tenant_mismatch",
            "missing_tenant",
            "unauthorized_tenant",
        }:
            return _access_denied_error(tool)
        return _error(tool, exc)
    except Exception as exc:  # pragma: no cover
        logger.exception("uspto_persisted_assurance_provenance failed")
        return _error(tool, exc, code="internal_error")


async def perform_uspto_tool(operation: str, **kwargs: Any) -> dict[str, Any]:
    """Dispatch a named read-only tool or refuse forbidden operations."""
    key = str(operation or "").strip().lower().replace("-", "_").replace(" ", "_")
    try:
        assert_mcp_operation_allowed(key)
    except ForbiddenMCPOperationError as exc:
        return _error(key or "unknown", exc)

    dispatch: dict[str, Callable[..., Any]] = {
        "uspto_status": uspto_status,
        "uspto_dossier_summary": uspto_dossier_summary,
        "uspto_requirement_matrix": uspto_requirement_matrix,
        "uspto_evidence_gaps": uspto_evidence_gaps,
        "uspto_citation_explanation": uspto_citation_explanation,
        "uspto_analysis_replay": uspto_analysis_replay,
        "uspto_persisted_assurance_summary": uspto_persisted_assurance_summary,
        "uspto_persisted_assurance_findings": uspto_persisted_assurance_findings,
        "uspto_persisted_assurance_provenance": uspto_persisted_assurance_provenance,
        # Aliases without prefix
        "status": uspto_status,
        "dossier_summary": uspto_dossier_summary,
        "requirement_matrix": uspto_requirement_matrix,
        "evidence_gaps": uspto_evidence_gaps,
        "citation_explanation": uspto_citation_explanation,
        "analysis_replay": uspto_analysis_replay,
        "persisted_assurance_summary": uspto_persisted_assurance_summary,
        "persisted_assurance_findings": uspto_persisted_assurance_findings,
        "persisted_assurance_provenance": uspto_persisted_assurance_provenance,
    }
    if key not in dispatch:
        return _error(
            key or "unknown",
            UsptoMCPError(f"unknown USPTO MCP tool: {operation!r}", code="unknown_tool"),
        )
    return await dispatch[key](**kwargs)


# Registry list for MCP discovery (functions, not class instances).
# PATLAW-061 v1 surface — length must match READ_ONLY_TOOL_NAMES.
USPTO_MCP_TOOLS: Final[list[Any]] = [
    uspto_status,
    uspto_dossier_summary,
    uspto_requirement_matrix,
    uspto_evidence_gaps,
    uspto_citation_explanation,
    uspto_analysis_replay,
]

# PATLAW-141 additive surface.
PERSISTED_ASSURANCE_MCP_TOOLS: Final[list[Any]] = [
    uspto_persisted_assurance_summary,
    uspto_persisted_assurance_findings,
    uspto_persisted_assurance_provenance,
]


__all__ = [
    "ACCESS_DENIED_CODE",
    "ACCESS_DENIED_MESSAGE",
    "FORBIDDEN_MCP_OPERATIONS",
    "InMemoryPersistedAssuranceStore",
    "PERSISTED_ASSURANCE_MCP_TOOLS",
    "PERSISTED_ASSURANCE_TOOL_NAMES",
    "PERSISTED_ASSURANCE_TOOL_SCHEMAS",
    "PERSISTED_ASSURANCE_TOOL_TO_OPERATION",
    "PersistedAssuranceStore",
    "READ_ONLY_TOOL_NAMES",
    "TOOL_SCHEMAS",
    "TOOL_TO_API_OPERATION",
    "USPTO_MCP_INTERFACE",
    "USPTO_MCP_SCHEMA",
    "USPTO_MCP_TOOLS",
    "USPTO_MCP_TOOL_VERSION",
    "ForbiddenMCPOperationError",
    "UsptoMCPAuthError",
    "UsptoMCPError",
    "apply_output_redaction",
    "assert_mcp_operation_allowed",
    "authorize_tenant_access",
    "bind_api",
    "bind_assurance_store",
    "get_api",
    "get_assurance_store",
    "get_tool_schema",
    "list_all_uspto_tools",
    "list_forbidden_operations",
    "list_persisted_assurance_tools",
    "list_uspto_tools",
    "perform_uspto_tool",
    "reset_api",
    "reset_assurance_store",
    "schemas_are_read_only",
    "set_id_factory",
    "uspto_analysis_replay",
    "uspto_citation_explanation",
    "uspto_dossier_summary",
    "uspto_evidence_gaps",
    "uspto_persisted_assurance_findings",
    "uspto_persisted_assurance_provenance",
    "uspto_persisted_assurance_summary",
    "uspto_requirement_matrix",
    "uspto_status",
]
