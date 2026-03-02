"""Unified contracts for web archiving search and fetch workflows.

These models provide a provider-neutral request/response envelope used by the
new unified web archiving API.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse


class OperationMode(str, Enum):
    """Execution profile for provider selection and fallback behavior."""

    MAX_THROUGHPUT = "max_throughput"
    BALANCED = "balanced"
    MAX_QUALITY = "max_quality"
    LOW_COST = "low_cost"


class ErrorSeverity(str, Enum):
    """Severity classification for unified errors."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


def _is_valid_http_url(value: str) -> bool:
    """Return True when value is an absolute HTTP(S) URL."""
    try:
        parsed = urlparse(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        return False


@dataclass
class UnifiedError:
    """Standardized error envelope across providers."""

    code: str
    message: str
    provider: Optional[str] = None
    retryable: bool = False
    severity: ErrorSeverity = ErrorSeverity.ERROR
    context: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.code:
            raise ValueError("UnifiedError.code must be non-empty")
        if not self.message:
            raise ValueError("UnifiedError.message must be non-empty")


@dataclass
class UnifiedSearchHit:
    """Normalized search hit from any provider."""

    title: str
    url: str
    snippet: str
    source: str
    score: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not _is_valid_http_url(self.url):
            raise ValueError(f"UnifiedSearchHit.url must be http(s): {self.url}")
        if not self.source:
            raise ValueError("UnifiedSearchHit.source must be non-empty")


@dataclass
class UnifiedDocument:
    """Normalized fetched document content from any provider/method."""

    url: str
    title: str = ""
    text: str = ""
    html: str = ""
    content_type: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    extraction_provenance: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not _is_valid_http_url(self.url):
            raise ValueError(f"UnifiedDocument.url must be http(s): {self.url}")


@dataclass
class ExecutionTrace:
    """Provider-attempt trace metadata for observability and debugging."""

    request_id: str
    operation: str
    mode: OperationMode
    providers_attempted: List[str] = field(default_factory=list)
    provider_selected: Optional[str] = None
    fallback_count: int = 0
    total_latency_ms: float = 0.0
    retries: int = 0
    started_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    finished_at: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.request_id:
            raise ValueError("ExecutionTrace.request_id must be non-empty")
        if not self.operation:
            raise ValueError("ExecutionTrace.operation must be non-empty")
        if self.fallback_count < 0:
            raise ValueError("ExecutionTrace.fallback_count cannot be negative")
        if self.total_latency_ms < 0:
            raise ValueError("ExecutionTrace.total_latency_ms cannot be negative")
        if self.retries < 0:
            raise ValueError("ExecutionTrace.retries cannot be negative")


@dataclass
class UnifiedSearchRequest:
    """Provider-neutral search request."""

    query: str
    mode: OperationMode = OperationMode.BALANCED
    max_results: int = 20
    offset: int = 0
    provider_allowlist: Optional[List[str]] = None
    provider_denylist: Optional[List[str]] = None
    timeout_seconds: int = 30
    min_quality: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.query or not self.query.strip():
            raise ValueError("UnifiedSearchRequest.query must be non-empty")
        if self.max_results <= 0:
            raise ValueError("UnifiedSearchRequest.max_results must be > 0")
        if self.offset < 0:
            raise ValueError("UnifiedSearchRequest.offset must be >= 0")
        if self.timeout_seconds <= 0:
            raise ValueError("UnifiedSearchRequest.timeout_seconds must be > 0")
        if not 0.0 <= self.min_quality <= 1.0:
            raise ValueError("UnifiedSearchRequest.min_quality must be in [0.0, 1.0]")

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["mode"] = self.mode.value
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "UnifiedSearchRequest":
        data = dict(payload)
        mode = data.get("mode", OperationMode.BALANCED)
        if isinstance(mode, str):
            data["mode"] = OperationMode(mode)
        return cls(**data)

    @classmethod
    def from_json(cls, payload: str) -> "UnifiedSearchRequest":
        return cls.from_dict(json.loads(payload))


@dataclass
class UnifiedFetchRequest:
    """Provider-neutral fetch/scrape request."""

    url: str
    mode: OperationMode = OperationMode.BALANCED
    timeout_seconds: int = 30
    fallback_enabled: bool = True
    min_quality: float = 0.0
    provider_allowlist: Optional[List[str]] = None
    provider_denylist: Optional[List[str]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not _is_valid_http_url(self.url):
            raise ValueError(f"UnifiedFetchRequest.url must be http(s): {self.url}")
        if self.timeout_seconds <= 0:
            raise ValueError("UnifiedFetchRequest.timeout_seconds must be > 0")
        if not 0.0 <= self.min_quality <= 1.0:
            raise ValueError("UnifiedFetchRequest.min_quality must be in [0.0, 1.0]")

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["mode"] = self.mode.value
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "UnifiedFetchRequest":
        data = dict(payload)
        mode = data.get("mode", OperationMode.BALANCED)
        if isinstance(mode, str):
            data["mode"] = OperationMode(mode)
        return cls(**data)

    @classmethod
    def from_json(cls, payload: str) -> "UnifiedFetchRequest":
        return cls.from_dict(json.loads(payload))


@dataclass
class UnifiedSearchResponse:
    """Provider-neutral search response."""

    query: str
    results: List[UnifiedSearchHit] = field(default_factory=list)
    trace: Optional[ExecutionTrace] = None
    errors: List[UnifiedError] = field(default_factory=list)
    total_results: int = 0
    success: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.total_results < 0:
            raise ValueError("UnifiedSearchResponse.total_results cannot be negative")
        if self.total_results == 0 and self.results:
            self.total_results = len(self.results)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        if self.trace is not None:
            payload["trace"]["mode"] = self.trace.mode.value
        for error in payload["errors"]:
            error["severity"] = ErrorSeverity(error["severity"]).value
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "UnifiedSearchResponse":
        data = dict(payload)
        data["results"] = [UnifiedSearchHit(**item) for item in data.get("results", [])]
        data["errors"] = [
            UnifiedError(
                code=item["code"],
                message=item["message"],
                provider=item.get("provider"),
                retryable=item.get("retryable", False),
                severity=ErrorSeverity(item.get("severity", ErrorSeverity.ERROR.value)),
                context=item.get("context", {}),
            )
            for item in data.get("errors", [])
        ]
        trace_payload = data.get("trace")
        if trace_payload is not None:
            mode = trace_payload.get("mode", OperationMode.BALANCED)
            if isinstance(mode, str):
                trace_payload["mode"] = OperationMode(mode)
            data["trace"] = ExecutionTrace(**trace_payload)
        return cls(**data)

    @classmethod
    def from_json(cls, payload: str) -> "UnifiedSearchResponse":
        return cls.from_dict(json.loads(payload))


@dataclass
class UnifiedFetchResponse:
    """Provider-neutral fetch response."""

    url: str
    document: Optional[UnifiedDocument] = None
    trace: Optional[ExecutionTrace] = None
    errors: List[UnifiedError] = field(default_factory=list)
    success: bool = True
    quality_score: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not _is_valid_http_url(self.url):
            raise ValueError(f"UnifiedFetchResponse.url must be http(s): {self.url}")
        if not 0.0 <= self.quality_score <= 1.0:
            raise ValueError("UnifiedFetchResponse.quality_score must be in [0.0, 1.0]")

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        if self.trace is not None:
            payload["trace"]["mode"] = self.trace.mode.value
        for error in payload["errors"]:
            error["severity"] = ErrorSeverity(error["severity"]).value
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "UnifiedFetchResponse":
        data = dict(payload)
        document_payload = data.get("document")
        if document_payload is not None:
            data["document"] = UnifiedDocument(**document_payload)
        data["errors"] = [
            UnifiedError(
                code=item["code"],
                message=item["message"],
                provider=item.get("provider"),
                retryable=item.get("retryable", False),
                severity=ErrorSeverity(item.get("severity", ErrorSeverity.ERROR.value)),
                context=item.get("context", {}),
            )
            for item in data.get("errors", [])
        ]
        trace_payload = data.get("trace")
        if trace_payload is not None:
            mode = trace_payload.get("mode", OperationMode.BALANCED)
            if isinstance(mode, str):
                trace_payload["mode"] = OperationMode(mode)
            data["trace"] = ExecutionTrace(**trace_payload)
        return cls(**data)

    @classmethod
    def from_json(cls, payload: str) -> "UnifiedFetchResponse":
        return cls.from_dict(json.loads(payload))


__all__ = [
    "OperationMode",
    "ErrorSeverity",
    "UnifiedError",
    "UnifiedSearchHit",
    "UnifiedDocument",
    "ExecutionTrace",
    "UnifiedSearchRequest",
    "UnifiedFetchRequest",
    "UnifiedSearchResponse",
    "UnifiedFetchResponse",
]
