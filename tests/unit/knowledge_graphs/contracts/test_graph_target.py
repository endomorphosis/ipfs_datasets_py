"""
KGP-003: Executable GraphTarget + identity contract regressions.

These tests reify the normative shapes from
``docs/architecture/knowledge_graphs_service_contract.md`` and the
compatibility ADR so the control plane cannot drift without breaking CI.

They intentionally define pure-Python validators here (allowed edit surface)
until later tasks promote types into ``ipfs_datasets_py.knowledge_graphs.contracts``.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SERVICE_CONTRACT = REPO_ROOT / "docs/architecture/knowledge_graphs_service_contract.md"
COMPAT_ADR = REPO_ROOT / "docs/architecture/knowledge_graphs_compatibility.md"

CONTRACT_VERSION = "kg-service-contract/v1"
SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9_-]{0,62}[a-z0-9])?$")
REVISION_RE = re.compile(r"^[a-zA-Z0-9._:-]{1,128}$")
STORAGE_PROFILES = frozenset({"parquet", "ipfs_ipld", "ipfs_kit", "hybrid"})

LEGACY_REQUIRED = {
    "graph_engine": "adapt",
    "extraction_knowledge_graph": "adapt",
    "data_transformation_ipld_graph": "adapt",
    "search_graph_data_sharded_car": "adopt",
    "knowledge_graph_manager": "deprecate",
}


class GraphTargetError(ValueError):
    """Invalid GraphTarget; ``code`` matches service-contract TARGET_* codes."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class GraphTarget:
    """Canonical graph address (kg-service-contract/v1)."""

    tenant: str
    graph_id: str
    branch: Optional[str] = None
    revision: Optional[str] = None
    storage_profile: Optional[str] = None

    def __post_init__(self) -> None:
        _validate_target_fields(
            self.tenant,
            self.graph_id,
            self.branch,
            self.revision,
            self.storage_profile,
        )

    @property
    def uri(self) -> str:
        return target_to_uri(self)

    def to_json_dict(self) -> Dict[str, Any]:
        return {
            "tenant": self.tenant,
            "graph_id": self.graph_id,
            "branch": self.branch,
            "revision": self.revision,
            "storage_profile": self.storage_profile,
            "uri": self.uri,
        }

    @classmethod
    def from_uri(
        cls,
        uri: str,
        *,
        storage_profile: Optional[str] = None,
    ) -> "GraphTarget":
        return parse_graph_target_uri(uri, storage_profile=storage_profile)


def _validate_slug(value: str, *, field: str, code_empty: str) -> str:
    if value is None or not str(value).strip():
        raise GraphTargetError(code_empty, f"{field} must be non-empty")
    cleaned = str(value).strip()
    if cleaned != value:
        # Reject untrimmed input so callers normalize explicitly.
        raise GraphTargetError("TARGET_BAD_SLUG", f"{field} must not have surrounding whitespace")
    if not SLUG_RE.fullmatch(cleaned):
        raise GraphTargetError("TARGET_BAD_SLUG", f"{field} failed slug validation: {value!r}")
    return cleaned


def _validate_target_fields(
    tenant: str,
    graph_id: str,
    branch: Optional[str],
    revision: Optional[str],
    storage_profile: Optional[str],
) -> None:
    _validate_slug(tenant, field="tenant", code_empty="TARGET_EMPTY_TENANT")
    _validate_slug(graph_id, field="graph_id", code_empty="TARGET_EMPTY_GRAPH")
    if branch is not None:
        _validate_slug(branch, field="branch", code_empty="TARGET_BAD_SLUG")
    if revision is not None:
        if not revision or not REVISION_RE.fullmatch(revision):
            raise GraphTargetError("TARGET_BAD_URI", f"invalid revision id: {revision!r}")
    if branch is not None and revision is not None:
        raise GraphTargetError(
            "TARGET_BRANCH_AND_REVISION",
            "branch and revision are mutually exclusive on GraphTarget",
        )
    if storage_profile is not None and storage_profile not in STORAGE_PROFILES:
        raise GraphTargetError(
            "TARGET_BAD_PROFILE",
            f"storage_profile must be one of {sorted(STORAGE_PROFILES)} or null",
        )


def target_to_uri(target: GraphTarget) -> str:
    base = f"kg://{target.tenant}/{target.graph_id}"
    if target.revision is not None:
        return f"{base}/revisions/{target.revision}"
    if target.branch is not None:
        return f"{base}/branches/{target.branch}"
    return base


_URI_BRANCH = re.compile(
    r"^kg://(?P<tenant>[^/]+)/(?P<graph_id>[^/]+)/branches/(?P<branch>[^/]+)$"
)
_URI_REV = re.compile(
    r"^kg://(?P<tenant>[^/]+)/(?P<graph_id>[^/]+)/revisions/(?P<revision>[^/]+)$"
)
_URI_BASE = re.compile(r"^kg://(?P<tenant>[^/]+)/(?P<graph_id>[^/]+)$")


def parse_graph_target_uri(
    uri: str,
    *,
    storage_profile: Optional[str] = None,
) -> GraphTarget:
    if not isinstance(uri, str) or not uri:
        raise GraphTargetError("TARGET_BAD_URI", "uri must be a non-empty string")
    if not uri.startswith("kg://"):
        raise GraphTargetError("TARGET_BAD_URI", f"uri must use kg:// scheme: {uri!r}")
    for pattern, kind in (
        (_URI_BRANCH, "branch"),
        (_URI_REV, "revision"),
        (_URI_BASE, "base"),
    ):
        match = pattern.fullmatch(uri)
        if match:
            groups = match.groupdict()
            return GraphTarget(
                tenant=groups["tenant"],
                graph_id=groups["graph_id"],
                branch=groups.get("branch"),
                revision=groups.get("revision"),
                storage_profile=storage_profile,
            )
    raise GraphTargetError("TARGET_BAD_URI", f"uri does not match kg:// grammar: {uri!r}")


def require_open_selector(target: GraphTarget) -> None:
    """open/query require branch or revision (service contract §4.1)."""
    if target.branch is None and target.revision is None:
        raise GraphTargetError(
            "TARGET_AMBIGUOUS",
            "operation requires branch or revision",
        )


# ---------------------------------------------------------------------------
# Lifecycle request/result shapes (identity + operation binding)
# ---------------------------------------------------------------------------

LIFECYCLE_OPERATIONS = frozenset(
    {
        "create",
        "list",
        "describe",
        "open",
        "branch",
        "delete",
        "write",
        "query",
        "begin_tx",
        "commit_tx",
        "rollback_tx",
    }
)


@dataclass(frozen=True)
class LifecycleRequest:
    operation: str
    target: GraphTarget
    contract_version: str = CONTRACT_VERSION
    idempotency_key: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    budgets: Optional[Dict[str, Any]] = None
    auth: Optional[Dict[str, Any]] = None
    request_id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.contract_version != CONTRACT_VERSION:
            raise ValueError(f"unsupported contract_version: {self.contract_version}")
        if self.operation not in LIFECYCLE_OPERATIONS:
            raise ValueError(f"unknown operation: {self.operation}")
        if self.operation in {"write", "create", "commit_tx"} and not self.idempotency_key:
            raise ValueError(f"idempotency_key required for {self.operation}")
        if self.operation in {"open", "query", "write", "begin_tx"}:
            if self.operation == "write" or self.operation == "begin_tx":
                if self.target.branch is None:
                    raise GraphTargetError(
                        "TARGET_AMBIGUOUS",
                        "write/begin_tx require a branch",
                    )
            else:
                require_open_selector(self.target)

    def to_json_dict(self) -> Dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "operation": self.operation,
            "target": self.target.to_json_dict(),
            "idempotency_key": self.idempotency_key,
            "params": self.params or {},
            "budgets": self.budgets,
            "auth": self.auth,
            "request_id": self.request_id,
        }


@dataclass(frozen=True)
class TypedError:
    code: str
    message: str
    retryable: bool
    details: Dict[str, Any]
    cause_code: Optional[str] = None

    def to_json_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "details": self.details,
            "cause_code": self.cause_code,
        }


TYPED_ERROR_CODES = frozenset(
    {
        "INVALID_REQUEST",
        "INVALID_TARGET",
        "NOT_FOUND",
        "ALREADY_EXISTS",
        "CONFLICT",
        "FENCED",
        "UNAUTHORIZED",
        "FORBIDDEN",
        "BUDGET_EXCEEDED",
        "QUERY_PARSE",
        "QUERY_EXECUTION",
        "STORAGE",
        "INTEGRITY",
        "NOT_IMPLEMENTED",
        "INTERNAL",
    }
)


@dataclass(frozen=True)
class LifecycleResult:
    status: str
    operation: str
    target: Optional[GraphTarget]
    result: Optional[Dict[str, Any]] = None
    error: Optional[TypedError] = None
    warnings: tuple = ()
    request_id: Optional[str] = None
    authorization_receipt_ref: Optional[str] = None
    contract_version: str = CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.status not in {"success", "error"}:
            raise ValueError("status must be success|error")
        if self.status == "error" and self.error is None:
            raise ValueError("error result requires TypedError")
        if self.status == "success" and self.error is not None:
            raise ValueError("success result must not include error")
        if self.error is not None and self.error.code not in TYPED_ERROR_CODES:
            raise ValueError(f"unknown error code: {self.error.code}")

    def to_json_dict(self) -> Dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "status": self.status,
            "operation": self.operation,
            "target": self.target.to_json_dict() if self.target else None,
            "result": self.result,
            "error": self.error.to_json_dict() if self.error else None,
            "warnings": list(self.warnings),
            "request_id": self.request_id,
            "authorization_receipt_ref": self.authorization_receipt_ref,
        }


# ---------------------------------------------------------------------------
# ADR document assertions
# ---------------------------------------------------------------------------


def _read(path: Path) -> str:
    assert path.is_file(), f"missing ADR: {path}"
    return path.read_text(encoding="utf-8")


def test_service_contract_adr_exists_and_defines_core_sections() -> None:
    text = _read(SERVICE_CONTRACT)
    required = [
        "GraphTarget",
        "one-service rule",
        "LifecycleRequest",
        "LifecycleResult",
        "TypedError",
        "QueryResultEnvelope",
        "kg-service-contract/v1",
        "kg://",
        "JSON-safe",
        "OSR-1",
        "storage_profile",
    ]
    missing = [item for item in required if item not in text]
    assert not missing, f"service contract missing sections: {missing}"


def test_compatibility_adr_maps_five_legacies() -> None:
    text = _read(COMPAT_ADR)
    for token in (
        "GraphEngine",
        "KnowledgeGraph",
        "IPLD",
        "ShardedCAR",
        "GraphData",
        "KnowledgeGraphManager",
        "adopt",
        "adapt",
        "deprecate",
        "one-service",
        "T0",
        "T1",
        "T2",
        "T3",
        "kg-compatibility/v1",
    ):
        assert token in text, f"compatibility ADR missing {token!r}"

    # Machine-readable map block
    start = text.index("{")
    # Find the JSON policy block by policy_version marker
    marker = '"policy_version": "kg-compatibility/v1"'
    assert marker in text
    json_start = text.rfind("```json", 0, text.index(marker))
    json_fence = text.index("```", text.index(marker))
    block = text[text.index("{", json_start) : json_fence]
    policy = json.loads(block)
    assert policy["one_service_rule"] is True
    assert policy["canonical_service"] == "GraphService"
    assert policy["canonical_target"] == "GraphTarget"
    legacy_map = policy["legacy_map"]
    for key, disposition in LEGACY_REQUIRED.items():
        assert key in legacy_map, f"missing legacy key {key}"
        assert legacy_map[key]["disposition"] == disposition
        assert legacy_map[key]["tier"] in {"T0", "T1", "T2", "T3"}


def test_graph_target_construction_and_uri_roundtrip() -> None:
    head = GraphTarget(tenant="acme", graph_id="skills", branch="main")
    assert head.uri == "kg://acme/skills/branches/main"
    assert GraphTarget.from_uri(head.uri) == head

    snap = GraphTarget(
        tenant="acme",
        graph_id="skills",
        revision="bafyreib2example000000000000000000000001",
        storage_profile="hybrid",
    )
    assert "/revisions/" in snap.uri
    assert GraphTarget.from_uri(snap.uri, storage_profile="hybrid") == snap

    bare = GraphTarget(tenant="t1", graph_id="g1")
    assert bare.uri == "kg://t1/g1"
    assert GraphTarget.from_uri(bare.uri) == bare


def test_graph_target_json_is_stable_and_serializable() -> None:
    target = GraphTarget(
        tenant="acme",
        graph_id="skills",
        branch="main",
        storage_profile="parquet",
    )
    payload = target.to_json_dict()
    encoded = json.dumps(payload, allow_nan=False, sort_keys=True)
    decoded = json.loads(encoded)
    assert decoded["tenant"] == "acme"
    assert decoded["uri"] == "kg://acme/skills/branches/main"
    assert decoded["revision"] is None


@pytest.mark.parametrize(
    "kwargs,code",
    [
        ({"tenant": "", "graph_id": "g"}, "TARGET_EMPTY_TENANT"),
        ({"tenant": "t", "graph_id": ""}, "TARGET_EMPTY_GRAPH"),
        ({"tenant": "ACME", "graph_id": "g"}, "TARGET_BAD_SLUG"),
        ({"tenant": "t", "graph_id": "has space"}, "TARGET_BAD_SLUG"),
        ({"tenant": "t", "graph_id": "g", "branch": "Main"}, "TARGET_BAD_SLUG"),
        (
            {
                "tenant": "t",
                "graph_id": "g",
                "branch": "main",
                "revision": "bafyreib2example000000000000000000000001",
            },
            "TARGET_BRANCH_AND_REVISION",
        ),
        (
            {"tenant": "t", "graph_id": "g", "storage_profile": "mongo"},
            "TARGET_BAD_PROFILE",
        ),
        ({"tenant": " t", "graph_id": "g"}, "TARGET_BAD_SLUG"),
    ],
)
def test_graph_target_rejects_invalid_fields(kwargs: Mapping[str, Any], code: str) -> None:
    with pytest.raises(GraphTargetError) as excinfo:
        GraphTarget(**kwargs)  # type: ignore[arg-type]
    assert excinfo.value.code == code


@pytest.mark.parametrize(
    "uri",
    [
        "https://acme/skills",
        "kg:/acme/skills",
        "kg://acme/skills/branches/main/revisions/abc",
        "kg://",
        "",
    ],
)
def test_graph_target_rejects_bad_uris(uri: str) -> None:
    with pytest.raises(GraphTargetError) as excinfo:
        GraphTarget.from_uri(uri)
    assert excinfo.value.code == "TARGET_BAD_URI"


def test_open_and_query_require_branch_or_revision() -> None:
    bare = GraphTarget(tenant="t", graph_id="g")
    with pytest.raises(GraphTargetError) as excinfo:
        require_open_selector(bare)
    assert excinfo.value.code == "TARGET_AMBIGUOUS"

    with pytest.raises(GraphTargetError):
        LifecycleRequest(operation="query", target=bare)

    ok = GraphTarget(tenant="t", graph_id="g", branch="main")
    req = LifecycleRequest(
        operation="query",
        target=ok,
        params={"language": "cypher", "text": "RETURN 1"},
    )
    assert req.to_json_dict()["contract_version"] == CONTRACT_VERSION
    json.dumps(req.to_json_dict(), allow_nan=False)


def test_write_requires_branch_and_idempotency_key() -> None:
    with pytest.raises(ValueError, match="idempotency_key"):
        LifecycleRequest(
            operation="write",
            target=GraphTarget(tenant="t", graph_id="g", branch="main"),
        )
    with pytest.raises(GraphTargetError) as excinfo:
        LifecycleRequest(
            operation="write",
            target=GraphTarget(
                tenant="t",
                graph_id="g",
                revision="bafyreib2example000000000000000000000001",
            ),
            idempotency_key="idem-1",
        )
    assert excinfo.value.code == "TARGET_AMBIGUOUS"


def test_lifecycle_result_success_and_error_envelopes() -> None:
    target = GraphTarget(tenant="t", graph_id="g", branch="main")
    success = LifecycleResult(
        status="success",
        operation="create",
        target=target,
        result={
            "graph_id": "g",
            "uri": target.uri,
            "branch": "main",
            "revision": "rev0",
            "storage_profile": "parquet",
        },
    )
    payload = success.to_json_dict()
    json.dumps(payload, allow_nan=False)
    assert payload["status"] == "success"
    assert payload["error"] is None

    err = LifecycleResult(
        status="error",
        operation="open",
        target=None,
        error=TypedError(
            code="NOT_FOUND",
            message="graph not found",
            retryable=False,
            details={"tenant": "t", "graph_id": "missing"},
        ),
    )
    err_payload = err.to_json_dict()
    json.dumps(err_payload, allow_nan=False)
    assert err_payload["error"]["code"] == "NOT_FOUND"
    assert err_payload["error"]["retryable"] is False


def test_typed_error_catalog_is_closed() -> None:
    # Service contract §6.2 catalog must stay in lockstep with the ADR text.
    text = _read(SERVICE_CONTRACT)
    for code in sorted(TYPED_ERROR_CODES):
        assert f"`{code}`" in text or code in text, f"error code {code} missing from ADR"


def test_one_service_rule_documented_in_both_adrs() -> None:
    service = _read(SERVICE_CONTRACT)
    compat = _read(COMPAT_ADR)
    for doc in (service, compat):
        assert "GraphService" in doc
        assert "one-service" in doc.lower() or "One-service" in doc or "one service" in doc.lower()
    assert "OSR-3" in service
    assert "KnowledgeGraphManager" in compat
    assert "Deprecate" in compat or "deprecate" in compat


def test_slug_allows_single_char_and_max_length() -> None:
    GraphTarget(tenant="a", graph_id="b", branch="c")
    long_id = "a" * 64
    GraphTarget(tenant=long_id, graph_id=long_id)
    with pytest.raises(GraphTargetError):
        GraphTarget(tenant="a" * 65, graph_id="g")


def test_lifecycle_request_rejects_unknown_operation() -> None:
    with pytest.raises(ValueError, match="unknown operation"):
        LifecycleRequest(
            operation="explode",
            target=GraphTarget(tenant="t", graph_id="g", branch="main"),
        )


def test_graph_target_not_ambient_empty() -> None:
    """Production contract: no ambient empty graph identity (OSR-3 / OSR-6)."""
    # A zero-arg or default empty target must not be constructible.
    with pytest.raises(TypeError):
        GraphTarget()  # type: ignore[call-arg]
    with pytest.raises(GraphTargetError):
        GraphTarget(tenant="default", graph_id="")
