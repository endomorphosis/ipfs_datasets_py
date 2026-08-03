"""Bounded Python facade for wallet ingest, export, resume, and status.

:class:`WalletProcessorAPI` is the integration-owner surface for wallet-centric
and finite ledger-range scans.  CLI and MCP adapters are thin wrappers over the
same typed requests and sanitized receipts.

Design constraints (WALPROC-G610 / CRYPTOIR-G600):

* Typed request/result objects are shared by Python, CLI, and MCP.
* Every scan requires finite range/item/byte/time/retry bounds.
* Provider URLs and secret values from untrusted MCP callers are only accepted
  when they match an explicit allowlist (see :class:`TrustPolicy`).
* Default export mode is finalized; provisional and raw modes are explicit.
* No signing or broadcast verbs exist on this surface.
* Status/receipts never include wallet record payloads or secret material.
* CRYPTOIR-G600 cutover: consumers cannot bypass policy via ``approved=true``;
  signing/broadcast remains disabled here and is only available through
  :class:`~ipfs_datasets_py.processors.wallets.guard.service.GuardService`
  after exact-candidate admissibility capability consumption.  Read-only
  lookup and ingest remain usable without custody authority.

Importing this module performs no network I/O and does not load chain extras.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any
from urllib.parse import urlsplit

from .errors import (
    ExportError,
    InvalidRequestError,
    UnsupportedCapabilityError,
    WalletProcessorError,
)
from .export import (
    ExportFormat,
    ExportReceipt,
    WalletDatasetExporter,
    load_export_manifest,
    verify_manifest,
)
from .models import (
    ChainRef,
    ExportManifest,
    ExportPartition,
    ExportStatus,
    Finality,
    Provenance,
    RawPayloadPolicy,
)
from .pipeline import (
    IngestMode,
    PipelineRunReceipt,
    RunStatus,
    WalletLedgerProcessor,
    assert_finite_scope,
)
from .protocols import (
    BoundedRequest,
    Capabilities,
    Capability,
    OperationContext,
    RequestLimits,
)
from .registry import (
    WalletProcessorRegistry,
    default_registry,
)
from .security import SecretReference, endpoint_fingerprint


API_RECEIPT_SCHEMA_VERSION = "wallet-api-receipt-v1"
API_STATUS_SCHEMA_VERSION = "wallet-api-status-v1"
DEFAULT_MAX_TIME_SECONDS = 300
DEFAULT_MAX_RETRIES = 3
_SECRET_KEY_RE = re.compile(
    r"(secret|password|token|api[_-]?key|authorization|private|seed|mnemonic|signing)",
    re.IGNORECASE,
)
_FORBIDDEN_VERBS = frozenset(
    {
        "sign",
        "broadcast",
        "submit",
        "approve_payload",
        "sign_transaction",
        "broadcast_transaction",
        "send",
        "send_raw_transaction",
        "transfer",
        "approve",
    }
)
# Compatibility escape hatches rejected at the read-only API boundary.
_FORBIDDEN_ESCAPE_OPTIONS = frozenset(
    {
        "approved",
        "approve",
        "is_approved",
        "caller_approved",
        "force_allow",
        "skip_guard",
        "bypass_guard",
        "bypass_policy",
        "private_key",
        "signing_key",
        "seed",
        "mnemonic",
    }
)


# ---------------------------------------------------------------------------
# Enums / bounds
# ---------------------------------------------------------------------------


class ExportMode(StrEnum):
    """Export finality mode.  Default for all surfaces is :attr:`FINALIZED`."""

    FINALIZED = "finalized"
    PROVISIONAL = "provisional"
    RAW = "raw"


class TrustLevel(StrEnum):
    """Caller trust level used by MCP/CLI adapters when applying allowlists."""

    TRUSTED = "trusted"
    UNTRUSTED = "untrusted"


class JobPhase(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _required_str(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError(f"{name} must be a non-empty string")
    return value.strip()


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InvalidRequestError(f"{name} must be a positive integer")
    return value


def _non_negative_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvalidRequestError(f"{name} must be a non-negative integer")
    return value


def _positive_float(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) <= 0:
        raise InvalidRequestError(f"{name} must be a positive number")
    return float(value)


@dataclass(frozen=True, slots=True)
class ScanBounds:
    """Hard finite ceilings applied to every ingest/export scan.

    All dimensions are required and finite.  Callers cannot request unbounded
    range, item, page, byte, time, or retry budgets through this facade.
    """

    max_items: int = 1_000
    max_pages: int = 100
    max_requests: int = 100
    max_response_bytes: int = 16 * 1024 * 1024
    max_time_seconds: float = DEFAULT_MAX_TIME_SECONDS
    max_retries: int = DEFAULT_MAX_RETRIES

    def __post_init__(self) -> None:
        _positive_int(self.max_items, "max_items")
        _positive_int(self.max_pages, "max_pages")
        _positive_int(self.max_requests, "max_requests")
        _positive_int(self.max_response_bytes, "max_response_bytes")
        _positive_float(self.max_time_seconds, "max_time_seconds")
        _non_negative_int(self.max_retries, "max_retries")

    def to_request_limits(self) -> RequestLimits:
        return RequestLimits(
            max_items=self.max_items,
            max_pages=self.max_pages,
            max_requests=self.max_requests,
            max_response_bytes=self.max_response_bytes,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_items": self.max_items,
            "max_pages": self.max_pages,
            "max_requests": self.max_requests,
            "max_response_bytes": self.max_response_bytes,
            "max_time_seconds": self.max_time_seconds,
            "max_retries": self.max_retries,
        }


@dataclass(frozen=True, slots=True)
class TrustPolicy:
    """Allowlists for untrusted MCP/CLI callers.

    Trusted callers may supply provider endpoints and secret references freely
    (still subject to endpoint safety elsewhere).  Untrusted callers may only
    use hosts and secret-reference prefixes listed here.
    """

    allowed_provider_hosts: frozenset[str] = field(default_factory=frozenset)
    allowed_secret_prefixes: frozenset[str] = field(default_factory=frozenset)
    allow_http: bool = False

    def __post_init__(self) -> None:
        hosts = frozenset(h.rstrip(".").lower() for h in self.allowed_provider_hosts)
        prefixes = frozenset(p for p in self.allowed_secret_prefixes if p)
        object.__setattr__(self, "allowed_provider_hosts", hosts)
        object.__setattr__(self, "allowed_secret_prefixes", prefixes)

    def assert_provider_url(self, url: str | None, *, trust: TrustLevel) -> None:
        if url is None:
            return
        url = _required_str(url, "provider_url")
        if trust is TrustLevel.TRUSTED:
            return
        try:
            parsed = urlsplit(url)
        except ValueError as exc:
            raise InvalidRequestError("provider_url is invalid") from exc
        scheme = (parsed.scheme or "").lower()
        if scheme not in ({"https", "http"} if self.allow_http else {"https"}):
            raise InvalidRequestError(
                f"untrusted callers may not supply provider_url "
                f"({endpoint_fingerprint(url)})"
            )
        host = (parsed.hostname or "").rstrip(".").lower()
        if not host or host not in self.allowed_provider_hosts:
            raise InvalidRequestError(
                "provider_url host is not on the untrusted MCP allowlist "
                f"({endpoint_fingerprint(url)})"
            )

    def assert_secret_reference(
        self, reference: str | None, *, trust: TrustLevel
    ) -> None:
        if reference is None:
            return
        reference = _required_str(reference, "secret_reference")
        # Validate shape without retaining the value in errors.
        try:
            SecretReference(reference)
        except InvalidRequestError:
            raise InvalidRequestError(
                "secret_reference must use an explicit resolver URI"
            ) from None
        if trust is TrustLevel.TRUSTED:
            return
        if not any(reference.startswith(prefix) for prefix in self.allowed_secret_prefixes):
            raise InvalidRequestError(
                "secret_reference is not on the untrusted MCP allowlist"
            )

    def assert_no_inline_secrets(self, payload: Mapping[str, Any]) -> None:
        """Reject request fields that look like inline secret material."""

        for key, value in payload.items():
            if _SECRET_KEY_RE.search(str(key)) and key not in {
                "secret_reference",
                "secret_references",
            }:
                if isinstance(value, str) and value.strip():
                    raise InvalidRequestError(
                        f"inline secret field {key!r} is forbidden; "
                        "use an opaque secret_reference"
                    )
            if isinstance(value, Mapping):
                self.assert_no_inline_secrets(value)


# ---------------------------------------------------------------------------
# Typed requests
# ---------------------------------------------------------------------------


def _parse_chain(chain: ChainRef | Mapping[str, Any]) -> ChainRef:
    if isinstance(chain, ChainRef):
        return chain
    if not isinstance(chain, Mapping):
        raise InvalidRequestError("chain must be a ChainRef or mapping")
    namespace = chain.get("namespace") or chain.get("chain_namespace")
    return ChainRef(
        namespace=_required_str(namespace, "chain.namespace"),
        network=_required_str(chain.get("network"), "chain.network"),
        chain_id=_required_str(chain.get("chain_id"), "chain.chain_id"),
        genesis_hash=_required_str(chain.get("genesis_hash"), "chain.genesis_hash"),
    )


def _parse_bounds(bounds: ScanBounds | Mapping[str, Any] | None) -> ScanBounds:
    if bounds is None:
        return ScanBounds()
    if isinstance(bounds, ScanBounds):
        return bounds
    if not isinstance(bounds, Mapping):
        raise InvalidRequestError("bounds must be a ScanBounds or mapping")
    return ScanBounds(
        max_items=int(bounds.get("max_items", 1_000)),
        max_pages=int(bounds.get("max_pages", 100)),
        max_requests=int(bounds.get("max_requests", 100)),
        max_response_bytes=int(bounds.get("max_response_bytes", 16 * 1024 * 1024)),
        max_time_seconds=float(bounds.get("max_time_seconds", DEFAULT_MAX_TIME_SECONDS)),
        max_retries=int(bounds.get("max_retries", DEFAULT_MAX_RETRIES)),
    )


def _parse_export_mode(mode: ExportMode | str | None) -> ExportMode:
    if mode is None:
        return ExportMode.FINALIZED
    if isinstance(mode, ExportMode):
        return mode
    try:
        return ExportMode(str(mode).strip().lower())
    except ValueError as exc:
        raise InvalidRequestError(
            f"export_mode must be one of {[m.value for m in ExportMode]}"
        ) from exc


def _parse_formats(
    formats: Sequence[ExportFormat | str] | None,
) -> tuple[ExportFormat, ...]:
    if not formats:
        return (ExportFormat.JSONL,)
    out: list[ExportFormat] = []
    for fmt in formats:
        out.append(fmt if isinstance(fmt, ExportFormat) else ExportFormat(str(fmt)))
    return tuple(out)


@dataclass(frozen=True, slots=True)
class WalletIngestRequest:
    """Typed wallet-centric ingest request with mandatory finite bounds."""

    scope: str
    chain: ChainRef
    bounds: ScanBounds = field(default_factory=ScanBounds)
    family: str | None = None
    request_id: str | None = None
    cursor: str | None = None
    provider_url: str | None = None
    secret_reference: str | None = None
    export_formats: tuple[ExportFormat, ...] = ()
    export_dir: str | None = None
    store_raw_payloads: bool = False
    safety_depth: int = 0
    options: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "scope", _required_str(self.scope, "scope"))
        if not isinstance(self.chain, ChainRef):
            object.__setattr__(self, "chain", _parse_chain(self.chain))
        if not isinstance(self.bounds, ScanBounds):
            object.__setattr__(self, "bounds", _parse_bounds(self.bounds))
        if self.family is not None:
            object.__setattr__(self, "family", _required_str(self.family, "family"))
        if self.cursor == "":
            raise InvalidRequestError("cursor must be non-empty when provided")
        _non_negative_int(self.safety_depth, "safety_depth")
        object.__setattr__(self, "export_formats", tuple(self.export_formats))
        object.__setattr__(self, "options", MappingProxyType(dict(self.options)))


@dataclass(frozen=True, slots=True)
class LedgerRangeIngestRequest:
    """Typed finite ledger-range ingest request."""

    scope: str
    chain: ChainRef
    start_position: int
    end_position: int
    bounds: ScanBounds = field(default_factory=ScanBounds)
    family: str | None = None
    request_id: str | None = None
    cursor: str | None = None
    provider_url: str | None = None
    secret_reference: str | None = None
    export_formats: tuple[ExportFormat, ...] = ()
    export_dir: str | None = None
    store_raw_payloads: bool = False
    safety_depth: int = 0
    options: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "scope", _required_str(self.scope, "scope"))
        if not isinstance(self.chain, ChainRef):
            object.__setattr__(self, "chain", _parse_chain(self.chain))
        if not isinstance(self.bounds, ScanBounds):
            object.__setattr__(self, "bounds", _parse_bounds(self.bounds))
        _non_negative_int(self.start_position, "start_position")
        _non_negative_int(self.end_position, "end_position")
        if self.start_position > self.end_position:
            raise InvalidRequestError(
                "start_position must not be greater than end_position"
            )
        if self.family is not None:
            object.__setattr__(self, "family", _required_str(self.family, "family"))
        if self.cursor == "":
            raise InvalidRequestError("cursor must be non-empty when provided")
        _non_negative_int(self.safety_depth, "safety_depth")
        object.__setattr__(self, "export_formats", tuple(self.export_formats))
        object.__setattr__(self, "options", MappingProxyType(dict(self.options)))


@dataclass(frozen=True, slots=True)
class WalletExportRequest:
    """Typed dataset export request.  Default mode is finalized."""

    scope: str
    chain: ChainRef
    output_dir: str
    bounds: ScanBounds = field(default_factory=ScanBounds)
    request_id: str | None = None
    records: tuple[object, ...] = ()
    formats: tuple[ExportFormat, ...] = (ExportFormat.JSONL,)
    mode: ExportMode = ExportMode.FINALIZED
    raw_payload_policy: RawPayloadPolicy = RawPayloadPolicy.OMITTED
    processor_version: str = "wallet-api@1.0.0"
    normalized_schema_major: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "scope", _required_str(self.scope, "scope"))
        if not isinstance(self.chain, ChainRef):
            object.__setattr__(self, "chain", _parse_chain(self.chain))
        object.__setattr__(
            self, "output_dir", _required_str(self.output_dir, "output_dir")
        )
        if not isinstance(self.bounds, ScanBounds):
            object.__setattr__(self, "bounds", _parse_bounds(self.bounds))
        object.__setattr__(self, "records", tuple(self.records))
        object.__setattr__(self, "formats", _parse_formats(self.formats))
        object.__setattr__(self, "mode", _parse_export_mode(self.mode))
        if not isinstance(self.raw_payload_policy, RawPayloadPolicy):
            object.__setattr__(
                self,
                "raw_payload_policy",
                RawPayloadPolicy(str(self.raw_payload_policy)),
            )
        if self.mode is ExportMode.RAW and self.raw_payload_policy is RawPayloadPolicy.OMITTED:
            raise InvalidRequestError(
                "raw export mode requires an explicit raw_payload_policy "
                "other than 'omitted'"
            )
        if self.mode is not ExportMode.RAW and self.raw_payload_policy is not (
            RawPayloadPolicy.OMITTED
        ):
            # Non-raw modes may still reference payloads, but the mode must be
            # set explicitly when raw policy is non-omitted.
            if self.mode is ExportMode.FINALIZED:
                raise InvalidRequestError(
                    "non-omitted raw_payload_policy requires export_mode "
                    "'provisional' or 'raw'"
                )
        _positive_int(self.normalized_schema_major, "normalized_schema_major")
        if len(self.records) > self.bounds.max_items:
            raise InvalidRequestError(
                f"export record count {len(self.records)} exceeds "
                f"bounds.max_items {self.bounds.max_items}"
            )


@dataclass(frozen=True, slots=True)
class ResumeRequest:
    """Resume a previously started job by id (status + checkpoint identity)."""

    job_id: str
    bounds: ScanBounds = field(default_factory=ScanBounds)
    request_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "job_id", _required_str(self.job_id, "job_id"))
        if not isinstance(self.bounds, ScanBounds):
            object.__setattr__(self, "bounds", _parse_bounds(self.bounds))


@dataclass(frozen=True, slots=True)
class StatusRequest:
    job_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "job_id", _required_str(self.job_id, "job_id"))


@dataclass(frozen=True, slots=True)
class CapabilitiesRequest:
    family: str | None = None
    network: str | None = None

    def __post_init__(self) -> None:
        if self.family is not None:
            object.__setattr__(self, "family", _required_str(self.family, "family"))
        if self.network is not None:
            object.__setattr__(
                self, "network", _required_str(self.network, "network")
            )


@dataclass(frozen=True, slots=True)
class VerifyManifestRequest:
    """Verify an export manifest path or in-memory mapping."""

    path: str | None = None
    manifest: Mapping[str, Any] | ExportManifest | None = None

    def __post_init__(self) -> None:
        if self.path is None and self.manifest is None:
            raise InvalidRequestError("verify_manifest requires path or manifest")
        if self.path is not None:
            object.__setattr__(self, "path", _required_str(self.path, "path"))


# ---------------------------------------------------------------------------
# Typed results (sanitized)
# ---------------------------------------------------------------------------


def _sanitize_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    """Drop secret-like keys and large nested payloads from receipts."""

    out: dict[str, Any] = {}
    for key, item in value.items():
        key_s = str(key)
        if _SECRET_KEY_RE.search(key_s):
            out[key_s] = "<redacted>"
            continue
        if key_s in {
            "records",
            "payload",
            "payloads",
            "wallet_payload",
            "raw",
            "raw_payloads",
            "calldata",
            "memo",
            "instruction",
            "instructions",
            "seed",
            "private_key",
        }:
            out[key_s] = "<omitted>"
            continue
        if isinstance(item, Mapping):
            out[key_s] = _sanitize_mapping(item)
        elif isinstance(item, (list, tuple)):
            # Keep scalar lists; omit nested record-like structures.
            if item and isinstance(item[0], Mapping):
                out[key_s] = f"<omitted {len(item)} items>"
            else:
                out[key_s] = list(item)
        else:
            out[key_s] = item
    return out


@dataclass(frozen=True, slots=True)
class StatusReceipt:
    """Sanitized job status; never includes wallet payloads or secrets."""

    job_id: str
    phase: JobPhase
    mode: str | None
    scope_fingerprint: str
    chain_namespace: str | None
    chain_network: str | None
    bounds: Mapping[str, Any]
    pages_processed: int = 0
    records_accepted: int = 0
    records_duplicate: int = 0
    checkpoint_advanced: bool = False
    export_receipt_id: str | None = None
    export_mode: str | None = None
    warnings: tuple[str, ...] = ()
    error: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    schema_version: str = field(default=API_STATUS_SCHEMA_VERSION, init=False)

    def to_dict(self) -> dict[str, Any]:
        return _sanitize_mapping(
            {
                "schema_version": self.schema_version,
                "job_id": self.job_id,
                "phase": self.phase.value,
                "mode": self.mode,
                "scope_fingerprint": self.scope_fingerprint,
                "chain_namespace": self.chain_namespace,
                "chain_network": self.chain_network,
                "bounds": dict(self.bounds),
                "pages_processed": self.pages_processed,
                "records_accepted": self.records_accepted,
                "records_duplicate": self.records_duplicate,
                "checkpoint_advanced": self.checkpoint_advanced,
                "export_receipt_id": self.export_receipt_id,
                "export_mode": self.export_mode,
                "warnings": list(self.warnings),
                "error": self.error,
                "created_at": self.created_at,
                "updated_at": self.updated_at,
            }
        )


@dataclass(frozen=True, slots=True)
class IngestResult:
    """Sanitized ingest result shared by Python/CLI/MCP."""

    job_id: str
    status: str
    mode: str
    scope_fingerprint: str
    pages_processed: int
    records_accepted: int
    records_duplicate: int
    checkpoint_advanced: bool
    bounds: Mapping[str, Any]
    export_receipt_id: str | None = None
    warnings: tuple[str, ...] = ()
    error: str | None = None
    schema_version: str = field(default=API_RECEIPT_SCHEMA_VERSION, init=False)

    def to_dict(self) -> dict[str, Any]:
        return _sanitize_mapping(
            {
                "schema_version": self.schema_version,
                "job_id": self.job_id,
                "status": self.status,
                "mode": self.mode,
                "scope_fingerprint": self.scope_fingerprint,
                "pages_processed": self.pages_processed,
                "records_accepted": self.records_accepted,
                "records_duplicate": self.records_duplicate,
                "checkpoint_advanced": self.checkpoint_advanced,
                "bounds": dict(self.bounds),
                "export_receipt_id": self.export_receipt_id,
                "warnings": list(self.warnings),
                "error": self.error,
            }
        )


@dataclass(frozen=True, slots=True)
class ExportResult:
    """Sanitized export result.  Default mode is finalized."""

    job_id: str
    status: str
    mode: str
    scope_fingerprint: str
    output_dir: str
    formats: tuple[str, ...]
    receipt_id: str | None
    manifest_id: str | None
    record_count: int
    partial: bool
    bounds: Mapping[str, Any]
    warnings: tuple[str, ...] = ()
    schema_version: str = field(default=API_RECEIPT_SCHEMA_VERSION, init=False)

    def to_dict(self) -> dict[str, Any]:
        return _sanitize_mapping(
            {
                "schema_version": self.schema_version,
                "job_id": self.job_id,
                "status": self.status,
                "mode": self.mode,
                "scope_fingerprint": self.scope_fingerprint,
                "output_dir": self.output_dir,
                "formats": list(self.formats),
                "receipt_id": self.receipt_id,
                "manifest_id": self.manifest_id,
                "record_count": self.record_count,
                "partial": self.partial,
                "bounds": dict(self.bounds),
                "warnings": list(self.warnings),
            }
        )


@dataclass(frozen=True, slots=True)
class CapabilitiesResult:
    families: tuple[dict[str, Any], ...]
    selected: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "families": list(self.families),
            "selected": self.selected,
            "supports_sign": False,
            "supports_broadcast": False,
        }


@dataclass(frozen=True, slots=True)
class VerifyManifestResult:
    ok: bool
    path: str | None
    manifest_id: str | None
    record_count: int | None
    status: str | None
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "path": self.path,
            "manifest_id": self.manifest_id,
            "record_count": self.record_count,
            "status": self.status,
            "errors": list(self.errors),
        }


# ---------------------------------------------------------------------------
# Internal job bookkeeping
# ---------------------------------------------------------------------------


def scope_fingerprint(scope: str) -> str:
    """Stable non-reversible label for receipts (no raw address leakage)."""

    digest = hashlib.sha256(scope.encode("utf-8", errors="replace")).hexdigest()[:16]
    return f"scope:{digest}"


@dataclass
class _JobRecord:
    job_id: str
    phase: JobPhase
    mode: str | None
    scope: str
    chain: ChainRef | None
    bounds: ScanBounds
    pages_processed: int = 0
    records_accepted: int = 0
    records_duplicate: int = 0
    checkpoint_advanced: bool = False
    export_receipt_id: str | None = None
    export_mode: str | None = None
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    resume_request: WalletIngestRequest | LedgerRangeIngestRequest | None = None
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)

    def to_status(self) -> StatusReceipt:
        return StatusReceipt(
            job_id=self.job_id,
            phase=self.phase,
            mode=self.mode,
            scope_fingerprint=scope_fingerprint(self.scope),
            chain_namespace=self.chain.namespace if self.chain else None,
            chain_network=self.chain.network if self.chain else None,
            bounds=self.bounds.to_dict(),
            pages_processed=self.pages_processed,
            records_accepted=self.records_accepted,
            records_duplicate=self.records_duplicate,
            checkpoint_advanced=self.checkpoint_advanced,
            export_receipt_id=self.export_receipt_id,
            export_mode=self.export_mode,
            warnings=tuple(self.warnings),
            error=self.error,
            created_at=self.created_at.isoformat(),
            updated_at=self.updated_at.isoformat(),
        )


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


class WalletProcessorAPI:
    """Bounded Python facade for wallet and ledger ingest/export surfaces.

    Parameters
    ----------
    registry:
        Lazy family registry; defaults to the process-wide registry.
    processor:
        Optional prebuilt :class:`WalletLedgerProcessor` used for ingest
        (tests inject fixture providers without loading chain extras).
    trust_policy:
        Host/secret allowlists applied when ``trust`` is untrusted.
    trust:
        Default trust level for this API instance (MCP tools force untrusted).
    """

    # Explicit denylist of custody/signing verbs — never implemented.
    FORBIDDEN_OPERATIONS = _FORBIDDEN_VERBS

    def __init__(
        self,
        *,
        registry: WalletProcessorRegistry | None = None,
        processor: WalletLedgerProcessor | None = None,
        trust_policy: TrustPolicy | None = None,
        trust: TrustLevel = TrustLevel.TRUSTED,
        clock: Any | None = None,
    ) -> None:
        self._registry = registry if registry is not None else default_registry()
        self._processor = processor
        self._trust_policy = trust_policy or TrustPolicy()
        self._trust = trust if isinstance(trust, TrustLevel) else TrustLevel(str(trust))
        self._clock = clock or _utc_now
        self._jobs: dict[str, _JobRecord] = {}

    # -- discovery ------------------------------------------------------------

    def list_families(self) -> CapabilitiesResult:
        """List registered families without loading chain extras."""

        families: list[dict[str, Any]] = []
        for name in self._registry.list_families():
            try:
                caps = self._registry.capabilities_for(name)
            except Exception:
                caps = None
            entry: dict[str, Any] = {"family": name}
            if caps is not None:
                entry.update(
                    {
                        "provider": caps.provider,
                        "chain_namespaces": sorted(caps.chain_namespaces),
                        "features": sorted(f.value for f in caps.features),
                        "metadata": _sanitize_mapping(dict(caps.metadata)),
                    }
                )
            entry["supports_sign"] = False
            entry["supports_broadcast"] = False
            families.append(entry)
        return CapabilitiesResult(families=tuple(families))

    def capabilities(
        self, request: CapabilitiesRequest | None = None
    ) -> CapabilitiesResult:
        """Return declared capabilities; never loads optional chain SDKs."""

        request = request or CapabilitiesRequest()
        listing = self.list_families()
        if request.family is None and request.network is None:
            return listing
        selected: dict[str, Any] | None = None
        if request.family is not None:
            for fam in listing.families:
                if fam.get("family") == request.family:
                    selected = dict(fam)
                    break
            if selected is None:
                # Fall back to registry capabilities_for (raises Unknown*).
                caps = self._registry.capabilities_for(request.family)
                selected = {
                    "family": request.family,
                    "provider": caps.provider,
                    "chain_namespaces": sorted(caps.chain_namespaces),
                    "features": sorted(f.value for f in caps.features),
                    "metadata": _sanitize_mapping(dict(caps.metadata)),
                    "supports_sign": False,
                    "supports_broadcast": False,
                }
        elif request.network is not None:
            # Prefer static catalogue match without constructing processors.
            for fam in listing.families:
                meta = fam.get("metadata") or {}
                networks = meta.get("networks") or []
                if request.network in networks or request.network == meta.get(
                    "default_network"
                ):
                    selected = dict(fam)
                    break
            if selected is None:
                raise InvalidRequestError(
                    f"no family declared for network {request.network!r}"
                )
        return CapabilitiesResult(families=listing.families, selected=selected)

    # -- ingest ---------------------------------------------------------------

    async def wallet_ingest(self, request: WalletIngestRequest) -> IngestResult:
        """Run a bounded wallet-centric ingest."""

        self._assert_not_forbidden_options(request.options)
        self._apply_trust_guards(
            provider_url=request.provider_url,
            secret_reference=request.secret_reference,
            options=request.options,
        )
        processor = self._require_processor(request.chain)
        context = self._build_context(request.request_id, request.bounds)
        bounded = BoundedRequest(
            scope=request.scope,
            context=context,
            cursor=request.cursor,
            options=dict(request.options),
        )
        assert_finite_scope(bounded, mode=IngestMode.WALLET)
        job = self._new_job(
            mode=IngestMode.WALLET.value,
            scope=request.scope,
            chain=request.chain,
            bounds=request.bounds,
            resume_request=request,
        )
        return await self._run_ingest(
            job,
            processor.ingest_wallet(
                bounded,
                export_formats=request.export_formats,
                export_dir=request.export_dir,
                store_raw_payloads=request.store_raw_payloads,
                safety_depth=request.safety_depth,
            ),
        )

    async def ledger_ingest(self, request: LedgerRangeIngestRequest) -> IngestResult:
        """Run a bounded finite ledger-range ingest."""

        self._assert_not_forbidden_options(request.options)
        self._apply_trust_guards(
            provider_url=request.provider_url,
            secret_reference=request.secret_reference,
            options=request.options,
        )
        processor = self._require_processor(request.chain)
        context = self._build_context(request.request_id, request.bounds)
        bounded = BoundedRequest(
            scope=request.scope,
            context=context,
            cursor=request.cursor,
            start_position=request.start_position,
            end_position=request.end_position,
            options=dict(request.options),
        )
        assert_finite_scope(bounded, mode=IngestMode.LEDGER_RANGE)
        job = self._new_job(
            mode=IngestMode.LEDGER_RANGE.value,
            scope=request.scope,
            chain=request.chain,
            bounds=request.bounds,
            resume_request=request,
        )
        return await self._run_ingest(
            job,
            processor.ingest_ledger(
                bounded,
                export_formats=request.export_formats,
                export_dir=request.export_dir,
                store_raw_payloads=request.store_raw_payloads,
                safety_depth=request.safety_depth,
            ),
        )

    async def resume(self, request: ResumeRequest) -> IngestResult:
        """Resume a prior job using its stored typed request (if resumable)."""

        job = self._jobs.get(request.job_id)
        if job is None:
            raise InvalidRequestError(f"unknown job_id {request.job_id!r}")
        if job.resume_request is None:
            raise InvalidRequestError(
                f"job {request.job_id!r} is not resumable (no stored request)"
            )
        if job.phase in {JobPhase.RUNNING}:
            raise InvalidRequestError(f"job {request.job_id!r} is already running")
        stored = job.resume_request
        # Rebuild with updated bounds if provided.
        if isinstance(stored, WalletIngestRequest):
            resumed = WalletIngestRequest(
                scope=stored.scope,
                chain=stored.chain,
                bounds=request.bounds,
                family=stored.family,
                request_id=request.request_id or stored.request_id,
                cursor=stored.cursor,
                provider_url=stored.provider_url,
                secret_reference=stored.secret_reference,
                export_formats=stored.export_formats,
                export_dir=stored.export_dir,
                store_raw_payloads=stored.store_raw_payloads,
                safety_depth=stored.safety_depth,
                options=dict(stored.options),
            )
            # Reuse job_id
            result = await self.wallet_ingest(resumed)
        else:
            resumed = LedgerRangeIngestRequest(
                scope=stored.scope,
                chain=stored.chain,
                start_position=stored.start_position,
                end_position=stored.end_position,
                bounds=request.bounds,
                family=stored.family,
                request_id=request.request_id or stored.request_id,
                cursor=stored.cursor,
                provider_url=stored.provider_url,
                secret_reference=stored.secret_reference,
                export_formats=stored.export_formats,
                export_dir=stored.export_dir,
                store_raw_payloads=stored.store_raw_payloads,
                safety_depth=stored.safety_depth,
                options=dict(stored.options),
            )
            result = await self.ledger_ingest(resumed)
        # Point status of original job_id at the new outcome for continuity.
        if result.job_id != request.job_id and request.job_id in self._jobs:
            new_job = self._jobs.get(result.job_id)
            if new_job is not None:
                self._jobs[request.job_id] = new_job
                new_job.job_id = request.job_id
                return IngestResult(
                    job_id=request.job_id,
                    status=result.status,
                    mode=result.mode,
                    scope_fingerprint=result.scope_fingerprint,
                    pages_processed=result.pages_processed,
                    records_accepted=result.records_accepted,
                    records_duplicate=result.records_duplicate,
                    checkpoint_advanced=result.checkpoint_advanced,
                    bounds=result.bounds,
                    export_receipt_id=result.export_receipt_id,
                    warnings=result.warnings,
                    error=result.error,
                )
        return result

    def status(self, request: StatusRequest) -> StatusReceipt:
        job = self._jobs.get(request.job_id)
        if job is None:
            raise InvalidRequestError(f"unknown job_id {request.job_id!r}")
        return job.to_status()

    # -- export ---------------------------------------------------------------

    async def wallet_export(self, request: WalletExportRequest) -> ExportResult:
        """Export records with default finalized mode (provisional/raw explicit)."""

        mode = request.mode
        context = self._build_context(request.request_id, request.bounds)
        export_status = (
            ExportStatus.COMPLETE
            if mode is ExportMode.FINALIZED
            else ExportStatus.PARTIAL
        )
        # RAW mode remains partial until an operator explicitly finalizes.
        raw_policy = request.raw_payload_policy
        if mode is ExportMode.RAW and raw_policy is RawPayloadPolicy.OMITTED:
            raise InvalidRequestError(
                "raw export mode requires explicit raw_payload_policy"
            )
        exporter = WalletDatasetExporter(
            chain=request.chain,
            output_dir=request.output_dir,
            formats=request.formats,
            processor_version=request.processor_version,
            normalized_schema_major=request.normalized_schema_major,
            raw_payload_policy=raw_policy,
            provider="wallet-processor-api",
            provider_kind="api",
            clock=self._clock,
        )
        job = self._new_job(
            mode="export",
            scope=request.scope,
            chain=request.chain,
            bounds=request.bounds,
        )
        job.export_mode = mode.value
        job.phase = JobPhase.RUNNING
        job.updated_at = self._clock()
        try:
            receipt: ExportReceipt = await exporter.export_records(
                request.records,
                context=context,
                scope=request.scope,
                status=export_status,
            )
            job.phase = (
                JobPhase.COMPLETE
                if receipt.status is ExportStatus.COMPLETE and not receipt.partial
                else JobPhase.PARTIAL
            )
            job.records_accepted = receipt.manifest.record_count
            job.export_receipt_id = receipt.receipt_id
            job.updated_at = self._clock()
            return ExportResult(
                job_id=job.job_id,
                status=receipt.status.value,
                mode=mode.value,
                scope_fingerprint=scope_fingerprint(request.scope),
                output_dir=receipt.output_dir,
                formats=receipt.formats,
                receipt_id=receipt.receipt_id,
                manifest_id=receipt.manifest.manifest_id,
                record_count=receipt.manifest.record_count,
                partial=receipt.partial,
                bounds=request.bounds.to_dict(),
                warnings=receipt.warnings,
            )
        except Exception as exc:
            job.phase = JobPhase.FAILED
            job.error = type(exc).__name__
            job.updated_at = self._clock()
            raise

    def verify_manifest(self, request: VerifyManifestRequest) -> VerifyManifestResult:
        """Verify export manifest accounting without leaking payloads."""

        errors: list[str] = []
        path = request.path
        manifest_obj: ExportManifest | None = None
        manifest_id: str | None = None
        record_count: int | None = None
        status: str | None = None
        try:
            if isinstance(request.manifest, ExportManifest):
                manifest_obj = request.manifest
                verify_manifest(manifest_obj)
                manifest_id = manifest_obj.manifest_id
                record_count = manifest_obj.record_count
                status = manifest_obj.status.value
            elif request.manifest is not None:
                # Lightweight accounting checks on dict payloads.
                payload = dict(request.manifest)
                manifest_id = (
                    str(payload["manifest_id"])
                    if payload.get("manifest_id") is not None
                    else None
                )
                record_count = (
                    int(payload["record_count"])
                    if payload.get("record_count") is not None
                    else None
                )
                status = (
                    str(payload["status"]) if payload.get("status") is not None else None
                )
                partitions = payload.get("partitions") or []
                if record_count is not None and isinstance(partitions, list):
                    part_sum = sum(int(p.get("record_count", 0)) for p in partitions)
                    if part_sum != record_count:
                        errors.append("partition record counts must equal record_count")
                warnings = payload.get("warnings") or []
                warning_count = payload.get("warning_count")
                if warning_count is not None and int(warning_count) != len(warnings):
                    errors.append("warning_count must equal the number of warnings")
                finality = payload.get("finality_counts") or {}
                if record_count is not None and isinstance(finality, Mapping):
                    if sum(int(v) for v in finality.values()) != record_count:
                        errors.append("finality counts must equal record_count")
            if path is not None:
                loaded = load_export_manifest(path)
                if request.manifest is None:
                    # Recursive check on loaded mapping.
                    nested = self.verify_manifest(
                        VerifyManifestRequest(manifest=loaded)
                    )
                    return VerifyManifestResult(
                        ok=nested.ok,
                        path=path,
                        manifest_id=nested.manifest_id,
                        record_count=nested.record_count,
                        status=nested.status,
                        errors=nested.errors,
                    )
        except (ExportError, InvalidRequestError, ValueError, OSError, TypeError) as exc:
            errors.append(type(exc).__name__)
        return VerifyManifestResult(
            ok=not errors,
            path=path,
            manifest_id=manifest_id,
            record_count=record_count,
            status=status,
            errors=tuple(errors),
        )

    # -- internal helpers -----------------------------------------------------

    def _require_processor(self, chain: ChainRef) -> WalletLedgerProcessor:
        if self._processor is None:
            raise UnsupportedCapabilityError(
                "WalletProcessorAPI has no injected WalletLedgerProcessor; "
                "construct the API with processor=... or use registry-built "
                "chain processors outside this facade"
            )
        if self._processor.chain.identity_dict() != chain.identity_dict():
            raise InvalidRequestError(
                "injected processor chain does not match request chain"
            )
        return self._processor

    def _build_context(
        self, request_id: str | None, bounds: ScanBounds
    ) -> OperationContext:
        rid = request_id or f"wallet-api-{uuid.uuid4().hex[:12]}"
        # OperationContext.check_active uses wall-clock time unless a custom
        # ``now`` is threaded through every call site.  Deadlines must therefore
        # be anchored to wall time so finite max_time_seconds is enforceable
        # even when the facade clock is frozen for deterministic receipts.
        wall = datetime.now(timezone.utc)
        clock_now = self._clock()
        if not isinstance(clock_now, datetime):
            raise InvalidRequestError("clock must return a datetime")
        if clock_now.tzinfo is None or clock_now.utcoffset() is None:
            clock_now = clock_now.replace(tzinfo=timezone.utc)
        anchor = wall if clock_now <= wall else clock_now
        deadline = anchor + timedelta(seconds=bounds.max_time_seconds)
        return OperationContext(
            request_id=rid,
            limits=bounds.to_request_limits(),
            deadline=deadline,
        )

    def _new_job(
        self,
        *,
        mode: str | None,
        scope: str,
        chain: ChainRef | None,
        bounds: ScanBounds,
        resume_request: WalletIngestRequest | LedgerRangeIngestRequest | None = None,
    ) -> _JobRecord:
        job_id = f"job-{uuid.uuid4().hex[:16]}"
        job = _JobRecord(
            job_id=job_id,
            phase=JobPhase.PENDING,
            mode=mode,
            scope=scope,
            chain=chain,
            bounds=bounds,
            resume_request=resume_request,
            created_at=self._clock(),
            updated_at=self._clock(),
        )
        self._jobs[job_id] = job
        return job

    async def _run_ingest(self, job: _JobRecord, coro: Any) -> IngestResult:
        job.phase = JobPhase.RUNNING
        job.updated_at = self._clock()
        try:
            receipt: PipelineRunReceipt = await coro
            job.pages_processed = receipt.pages_processed
            job.records_accepted = receipt.records_accepted
            job.records_duplicate = receipt.records_duplicate
            job.checkpoint_advanced = receipt.checkpoint_advanced
            job.warnings = list(receipt.warnings)
            if receipt.export_receipt is not None:
                job.export_receipt_id = receipt.export_receipt.receipt_id
            if receipt.status is RunStatus.COMPLETE:
                job.phase = JobPhase.COMPLETE
            elif receipt.status is RunStatus.CANCELLED:
                job.phase = JobPhase.CANCELLED
            elif receipt.status is RunStatus.FAILED:
                job.phase = JobPhase.FAILED
            else:
                job.phase = JobPhase.PARTIAL
            job.updated_at = self._clock()
            return IngestResult(
                job_id=job.job_id,
                status=receipt.status.value,
                mode=receipt.mode.value,
                scope_fingerprint=scope_fingerprint(receipt.scope),
                pages_processed=receipt.pages_processed,
                records_accepted=receipt.records_accepted,
                records_duplicate=receipt.records_duplicate,
                checkpoint_advanced=receipt.checkpoint_advanced,
                bounds=job.bounds.to_dict(),
                export_receipt_id=job.export_receipt_id,
                warnings=tuple(receipt.warnings),
            )
        except Exception as exc:
            job.phase = JobPhase.FAILED
            job.error = type(exc).__name__
            job.updated_at = self._clock()
            raise

    def _apply_trust_guards(
        self,
        *,
        provider_url: str | None,
        secret_reference: str | None,
        options: Mapping[str, object],
    ) -> None:
        self._trust_policy.assert_provider_url(provider_url, trust=self._trust)
        self._trust_policy.assert_secret_reference(
            secret_reference, trust=self._trust
        )
        # Also scan options for untrusted provider_url / secrets.
        if isinstance(options, Mapping):
            opt_url = options.get("provider_url")
            if isinstance(opt_url, str):
                self._trust_policy.assert_provider_url(opt_url, trust=self._trust)
            opt_secret = options.get("secret_reference") or options.get("api_key")
            if isinstance(opt_secret, str) and options.get("secret_reference"):
                self._trust_policy.assert_secret_reference(
                    opt_secret, trust=self._trust
                )
            elif isinstance(opt_secret, str) and self._trust is TrustLevel.UNTRUSTED:
                raise InvalidRequestError(
                    "inline secret field 'api_key' is forbidden; "
                    "use an opaque secret_reference"
                )
            self._trust_policy.assert_no_inline_secrets(
                {k: v for k, v in options.items() if not isinstance(v, (bytes, bytearray))}
            )

    def _assert_not_forbidden_options(self, options: Mapping[str, object]) -> None:
        for key in options:
            lowered = str(key).strip().lower()
            if (
                lowered in self.FORBIDDEN_OPERATIONS
                or lowered in _FORBIDDEN_ESCAPE_OPTIONS
                or lowered.startswith("sign_")
            ):
                raise UnsupportedCapabilityError(
                    f"operation {key!r} is not supported: "
                    "wallet processors never sign or broadcast and reject "
                    "approved=true compatibility escape hatches "
                    "(migrate to GuardService capability consumption)"
                )

    def guard_service(self) -> Any:
        """Return the process GuardService for preflight / gated signing.

        Read-only wallet operations do not require this.  Signing and broadcast
        must use the guard service with a consumed admissibility capability.
        """

        from .guard.service import get_default_guard_service

        return get_default_guard_service()

    def __getattr__(self, name: str) -> Any:
        if (
            name in self.FORBIDDEN_OPERATIONS
            or name.startswith("sign_")
            or name in _FORBIDDEN_ESCAPE_OPTIONS
        ):
            raise UnsupportedCapabilityError(
                f"{name!r} is not supported: wallet processors never sign or "
                "broadcast; use GuardService with a consumed "
                "AdmissibilityCapability (no approved=true escape hatch)"
            )
        raise AttributeError(
            f"{type(self).__name__!r} object has no attribute {name!r}"
        )


# ---------------------------------------------------------------------------
# Module-level convenience (AST symbols: wallet_ingest, wallet_export)
# ---------------------------------------------------------------------------

_DEFAULT_API: WalletProcessorAPI | None = None


def get_default_api() -> WalletProcessorAPI:
    global _DEFAULT_API
    if _DEFAULT_API is None:
        _DEFAULT_API = WalletProcessorAPI()
    return _DEFAULT_API


def reset_default_api() -> None:
    global _DEFAULT_API
    _DEFAULT_API = None


async def wallet_ingest(
    request: WalletIngestRequest | Mapping[str, Any],
    *,
    api: WalletProcessorAPI | None = None,
) -> IngestResult:
    """Module-level wallet ingest entrypoint (AST: ``wallet_ingest``)."""

    facade = api or get_default_api()
    if not isinstance(request, WalletIngestRequest):
        request = WalletIngestRequest(
            scope=_required_str(request.get("scope"), "scope"),
            chain=_parse_chain(request["chain"]),
            bounds=_parse_bounds(request.get("bounds")),
            family=request.get("family"),
            request_id=request.get("request_id"),
            cursor=request.get("cursor"),
            provider_url=request.get("provider_url"),
            secret_reference=request.get("secret_reference"),
            export_formats=_parse_formats(request.get("export_formats")),
            export_dir=request.get("export_dir"),
            store_raw_payloads=bool(request.get("store_raw_payloads", False)),
            safety_depth=int(request.get("safety_depth", 0)),
            options=dict(request.get("options") or {}),
        )
    return await facade.wallet_ingest(request)


async def wallet_export(
    request: WalletExportRequest | Mapping[str, Any],
    *,
    api: WalletProcessorAPI | None = None,
) -> ExportResult:
    """Module-level wallet export entrypoint (AST: ``wallet_export``)."""

    facade = api or get_default_api()
    if not isinstance(request, WalletExportRequest):
        mode = _parse_export_mode(request.get("mode") or request.get("export_mode"))
        raw_policy_raw = request.get("raw_payload_policy", RawPayloadPolicy.OMITTED)
        raw_policy = (
            raw_policy_raw
            if isinstance(raw_policy_raw, RawPayloadPolicy)
            else RawPayloadPolicy(str(raw_policy_raw))
        )
        request = WalletExportRequest(
            scope=_required_str(request.get("scope"), "scope"),
            chain=_parse_chain(request["chain"]),
            output_dir=_required_str(request.get("output_dir"), "output_dir"),
            bounds=_parse_bounds(request.get("bounds")),
            request_id=request.get("request_id"),
            records=tuple(request.get("records") or ()),
            formats=_parse_formats(request.get("formats")),
            mode=mode,
            raw_payload_policy=raw_policy,
            processor_version=str(
                request.get("processor_version") or "wallet-api@1.0.0"
            ),
            normalized_schema_major=int(
                request.get("normalized_schema_major") or 1
            ),
        )
    return await facade.wallet_export(request)


__all__ = [
    "API_RECEIPT_SCHEMA_VERSION",
    "API_STATUS_SCHEMA_VERSION",
    "CapabilitiesRequest",
    "CapabilitiesResult",
    "ExportMode",
    "ExportResult",
    "IngestResult",
    "JobPhase",
    "LedgerRangeIngestRequest",
    "ResumeRequest",
    "ScanBounds",
    "StatusReceipt",
    "StatusRequest",
    "TrustLevel",
    "TrustPolicy",
    "VerifyManifestRequest",
    "VerifyManifestResult",
    "WalletExportRequest",
    "WalletIngestRequest",
    "WalletProcessorAPI",
    "get_default_api",
    "reset_default_api",
    "scope_fingerprint",
    "wallet_export",
    "wallet_ingest",
]
