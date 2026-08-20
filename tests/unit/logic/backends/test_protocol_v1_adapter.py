"""LPC-051: v1 generic payloads cannot bypass BackendRequest@2.

Acceptance:

* v1 payloads are parsed into an operation type, rejected, or retained as
  advisory;
* free-form v1 payloads cannot mint or bypass BackendRequest@2;
* new writes use LogicProviderProtocol@2 / BackendRequest@2.
"""

from __future__ import annotations

import hashlib
from typing import Any

import pytest

from ipfs_datasets_py.logic.backends.protocol_v1_adapter import (
    ADVISORY_V1_RETENTION_SCHEMA,
    PROTOCOL_V1_ADAPTER_INTERFACE,
    PROTOCOL_V1_ADAPTER_VERSION,
    AdvisoryV1Retention,
    V1AdapterDisposition,
    V1AdapterError,
    V1BypassBackendRequestError,
    adapt_v1_provider_request,
    admit_new_provider_write,
    classify_v1_operation,
    elevate_v1_to_v2,
    is_executable_v1_elevation,
    parse_v1_provider_envelope,
    reject_v1_backend_request_bypass,
    retain_v1_as_advisory,
)
from ipfs_datasets_py.logic.backends.protocol_v2 import (
    LOGIC_PROVIDER_PROTOCOL_V2_INTERFACE,
    ArbitraryPayloadProtocolError,
    CapabilityRequestV2,
    ProveCheckRequestV2,
    ProtocolOperationV2,
    admit_provider_request_v2,
)
from ipfs_datasets_py.logic.backends.provider import (
    LOGIC_PROVIDER_PROTOCOL_VERSION as LOGIC_PROVIDER_V1_PROTOCOL_VERSION,
    LOGIC_PROVIDER_REQUEST_SCHEMA,
    LogicProviderOperation,
    LogicProviderRequest,
)
from ipfs_datasets_py.logic.backends.requests_v2 import (
    BACKEND_REQUEST_V2_INTERFACE,
    BackendRequestV2,
    RequestAuthorityCeiling,
    RequestBounds,
)
from ipfs_datasets_py.logic.families.namespaces import (
    encoding_id,
    evidence_id,
    family_id,
    notation_id,
    profile_id,
    property_id,
    view_id,
)


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _bounds(
    *,
    timeout_ms: int = 5_000,
    max_steps: int = 10_000,
    max_memory_bytes: int = 64 * 1024 * 1024,
    max_output_bytes: int = 256 * 1024,
) -> RequestBounds:
    return RequestBounds(
        timeout_ms=timeout_ms,
        max_steps=max_steps,
        max_memory_bytes=max_memory_bytes,
        max_output_bytes=max_output_bytes,
    )


def _backend_request(
    *,
    request_id: str = "req:v1-adapter-1",
    bounds: RequestBounds | None = None,
) -> BackendRequestV2:
    bounds = bounds or _bounds()
    return BackendRequestV2(
        request_id=request_id,
        obligation_id="obl:v1-adapter-1",
        obligation_digest=_digest("obligation"),
        document_id="doc:v1-adapter",
        source_digest=_digest("source"),
        expression_id="expr:v1-adapter",
        expression_digest=_digest("expression"),
        family=family_id("propositional"),
        profile=profile_id("classical"),
        property=property_id("validity"),
        view=view_id("source"),
        notation=notation_id("canonical_text"),
        encoding=encoding_id("smtlib2"),
        evidence_kind=evidence_id("model"),
        bounds=bounds,
        authority_ceiling=RequestAuthorityCeiling.SATISFIABILITY,
    )


def _v1_request(
    operation: str,
    payload: dict[str, Any] | None = None,
    *,
    request_id: str = "req:v1-1",
) -> LogicProviderRequest:
    return LogicProviderRequest(
        operation=operation,
        payload=payload or {},
        request_id=request_id,
    )


# ---------------------------------------------------------------------------
# Identities
# ---------------------------------------------------------------------------


def test_adapter_interface_identity() -> None:
    assert PROTOCOL_V1_ADAPTER_INTERFACE == "LogicProviderProtocolV1Adapter@1"
    assert PROTOCOL_V1_ADAPTER_VERSION == "1.0.0"
    assert ADVISORY_V1_RETENTION_SCHEMA.endswith("@1")


# ---------------------------------------------------------------------------
# Parse into operation type
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("v1_op", "expected"),
    [
        ("capability", ProtocolOperationV2.CAPABILITY),
        ("translate", ProtocolOperationV2.TRANSLATE),
        ("prove", ProtocolOperationV2.PROVE),
        ("reconstruct", ProtocolOperationV2.RECONSTRUCT),
        ("verify", ProtocolOperationV2.VERIFY),
        ("attest", ProtocolOperationV2.ATTEST),
        ("check", ProtocolOperationV2.CHECK),
    ],
)
def test_classify_v1_operation_names(
    v1_op: str, expected: ProtocolOperationV2
) -> None:
    assert classify_v1_operation(v1_op) is expected


@pytest.mark.parametrize(
    "operation",
    ["capability", "translate", "prove", "reconstruct", "verify", "attest"],
)
def test_classify_v1_envelope_parses_operation(operation: str) -> None:
    envelope = _v1_request(operation, {"formula": "P"})
    assert classify_v1_operation(envelope) is classify_v1_operation(operation)
    parsed = parse_v1_provider_envelope(envelope.to_dict())
    assert parsed.operation is LogicProviderOperation(operation)
    assert parsed.schema_version == LOGIC_PROVIDER_REQUEST_SCHEMA
    assert parsed.protocol_version == LOGIC_PROVIDER_V1_PROTOCOL_VERSION


def test_parse_v1_from_json_round_trip() -> None:
    original = _v1_request("prove", {"statement": "P"})
    restored = parse_v1_provider_envelope(original.to_json())
    assert restored.to_dict() == original.to_dict()


# ---------------------------------------------------------------------------
# Rejected disposition
# ---------------------------------------------------------------------------


def test_unknown_operation_is_rejected() -> None:
    result = adapt_v1_provider_request(
        {
            "schema_version": LOGIC_PROVIDER_REQUEST_SCHEMA,
            "protocol_version": 1,
            "request_id": "req:unknown",
            "operation": "optimize",
            "payload": {},
        }
    )
    assert result.disposition is V1AdapterDisposition.REJECTED
    assert result.request_v2 is None
    assert result.advisory is None
    assert result.executable is False
    assert "operation" in result.reason.lower() or "unknown" in result.reason.lower()


def test_malformed_envelope_is_rejected() -> None:
    result = adapt_v1_provider_request("not-json-and-not-an-operation")
    assert result.disposition is V1AdapterDisposition.REJECTED
    assert result.request_v2 is None


def test_free_form_payload_cannot_mint_backend_request() -> None:
    result = adapt_v1_provider_request(
        _v1_request(
            "prove",
            {
                "backend_request": {
                    "request_id": "req:forged",
                    "family": "propositional",
                },
                "statement": "P",
            },
        )
    )
    assert result.disposition is V1AdapterDisposition.REJECTED
    assert result.backend_request is None
    assert "BackendRequest@2" in result.reason or "bypass" in result.reason.lower()


@pytest.mark.parametrize(
    "bypass_key",
    [
        "backend_request",
        "backend_request_v2",
        "BackendRequest@2",
        "obligation",
        "domain_slice",
        "slice",
    ],
)
def test_bypass_payload_keys_are_rejected(bypass_key: str) -> None:
    with pytest.raises(V1BypassBackendRequestError):
        reject_v1_backend_request_bypass(
            _v1_request("prove", {bypass_key: {"forged": True}})
        )
    result = adapt_v1_provider_request(
        _v1_request("prove", {bypass_key: {"forged": True}})
    )
    assert result.disposition is V1AdapterDisposition.REJECTED


def test_v2_body_is_not_dual_read_as_v1() -> None:
    result = adapt_v1_provider_request(
        {
            "schema_version": "ipfs_datasets_py/logic-provider-capability-request@2",
            "protocol_version": 2,
            "interface": LOGIC_PROVIDER_PROTOCOL_V2_INTERFACE,
            "request_id": "req:already-v2",
            "operation": "capability",
            "provider_id": "z3",
        }
    )
    assert result.disposition is V1AdapterDisposition.REJECTED


# ---------------------------------------------------------------------------
# Advisory disposition (no BackendRequest@2 bypass)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("operation", "payload"),
    [
        ("translate", {"source_encoding": "smtlib2", "target_encoding": "tptp"}),
        ("prove", {"statement": "P"}),
        ("reconstruct", {"candidate_digest": _digest("cand")}),
        ("verify", {"evidence_digest": _digest("ev")}),
        ("attest", {"statement_digest": _digest("st")}),
    ],
)
def test_executable_v1_without_backend_request_is_advisory(
    operation: str, payload: dict[str, Any]
) -> None:
    result = adapt_v1_provider_request(_v1_request(operation, payload))
    assert result.disposition is V1AdapterDisposition.ADVISORY
    assert result.operation is classify_v1_operation(operation)
    assert result.request_v2 is None
    assert result.advisory is not None
    assert result.advisory.executable is False
    assert result.advisory.backend_request is None
    assert result.advisory.authority_ceiling == "advisory"
    assert result.executable is False
    assert result.backend_request is None
    assert BACKEND_REQUEST_V2_INTERFACE in result.reason or "advisory" in result.reason


def test_retain_v1_as_advisory_never_executable() -> None:
    advisory = retain_v1_as_advisory(_v1_request("prove", {"statement": "P"}))
    assert isinstance(advisory, AdvisoryV1Retention)
    assert advisory.operation is ProtocolOperationV2.PROVE
    assert advisory.executable is False
    assert advisory.backend_request is None
    assert advisory.to_dict()["backend_request"] is None
    assert advisory.to_dict()["executable"] is False


def test_advisory_cannot_be_admitted_as_executable_v2() -> None:
    result = adapt_v1_provider_request(_v1_request("prove", {"statement": "P"}))
    assert result.advisory is not None
    with pytest.raises(ArbitraryPayloadProtocolError):
        admit_provider_request_v2(result.advisory.to_dict())


# ---------------------------------------------------------------------------
# Parsed disposition (elevation with external BackendRequest@2)
# ---------------------------------------------------------------------------


def test_capability_elevates_without_backend_request() -> None:
    result = adapt_v1_provider_request(
        _v1_request(
            "capability",
            {"provider_id": "z3", "feature_query": ["smt"], "include_versions": True},
        )
    )
    assert result.disposition is V1AdapterDisposition.PARSED
    assert result.operation is ProtocolOperationV2.CAPABILITY
    assert isinstance(result.request_v2, CapabilityRequestV2)
    assert result.request_v2.provider_id == "z3"
    assert result.request_v2.feature_query == ("smt",)
    assert result.executable is False
    assert result.backend_request is None
    assert is_executable_v1_elevation(result) is False


def test_prove_elevates_with_external_backend_request() -> None:
    backend = _backend_request()
    result = adapt_v1_provider_request(
        _v1_request("prove", {"statement": "prove P", "mode": "prove"}),
        backend_request=backend,
    )
    assert result.disposition is V1AdapterDisposition.PARSED
    assert result.operation is ProtocolOperationV2.PROVE
    assert isinstance(result.request_v2, ProveCheckRequestV2)
    assert result.request_v2.statement == "prove P"
    assert result.executable is True
    assert result.backend_request is not None
    assert result.backend_request.request_id == backend.request_id
    assert is_executable_v1_elevation(result) is True


def test_check_mode_elevates_to_check_operation() -> None:
    backend = _backend_request()
    elevated = elevate_v1_to_v2(
        _v1_request("prove", {"statement": "check P", "mode": "check"}),
        backend_request=backend,
    )
    assert isinstance(elevated, ProveCheckRequestV2)
    assert elevated.operation is ProtocolOperationV2.CHECK


def test_translate_elevates_with_encodings_and_backend_request() -> None:
    backend = _backend_request()
    result = adapt_v1_provider_request(
        _v1_request(
            "translate",
            {"source_encoding": "smtlib2", "target_encoding": "tptp"},
        ),
        backend_request=backend,
        bounds=_bounds(timeout_ms=1_000),
    )
    assert result.disposition is V1AdapterDisposition.PARSED
    assert result.operation is ProtocolOperationV2.TRANSLATE
    assert result.request_v2 is not None
    assert result.request_v2.source_encoding == "smtlib2"  # type: ignore[attr-defined]
    assert result.request_v2.target_encoding == "tptp"  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("operation", "payload"),
    [
        ("reconstruct", {"candidate_digest": _digest("cand")}),
        ("verify", {"evidence_digest": _digest("ev")}),
        ("attest", {"statement_digest": _digest("st")}),
    ],
)
def test_digest_ops_elevate_with_backend_request(
    operation: str, payload: dict[str, Any]
) -> None:
    result = adapt_v1_provider_request(
        _v1_request(operation, payload),
        backend_request=_backend_request(),
    )
    assert result.disposition is V1AdapterDisposition.PARSED
    assert result.operation is classify_v1_operation(operation)
    assert result.executable is True
    assert result.backend_request is not None


def test_elevation_bounds_cannot_exceed_backend_request() -> None:
    backend = _backend_request(bounds=_bounds(timeout_ms=1_000))
    result = adapt_v1_provider_request(
        _v1_request("prove", {"statement": "P"}),
        backend_request=backend,
        bounds=_bounds(timeout_ms=60_000),
    )
    assert result.disposition is V1AdapterDisposition.REJECTED
    assert "bounds" in result.reason.lower() or "exceed" in result.reason.lower()


def test_elevate_v1_to_v2_raises_on_advisory() -> None:
    with pytest.raises(V1AdapterError, match="advisory"):
        elevate_v1_to_v2(_v1_request("prove", {"statement": "P"}))


def test_incomplete_typed_fields_stay_advisory_even_with_backend_request() -> None:
    # translate without encodings cannot elevate.
    result = adapt_v1_provider_request(
        _v1_request("translate", {}),
        backend_request=_backend_request(),
    )
    assert result.disposition is V1AdapterDisposition.ADVISORY
    assert result.operation is ProtocolOperationV2.TRANSLATE


# ---------------------------------------------------------------------------
# New writes use v2
# ---------------------------------------------------------------------------


def test_admit_new_provider_write_accepts_v2() -> None:
    request = CapabilityRequestV2(request_id="req:new-write", provider_id="lean")
    admitted = admit_new_provider_write(request)
    assert isinstance(admitted, CapabilityRequestV2)
    admitted_dict = admit_new_provider_write(request.to_dict())
    assert admitted_dict.operation is ProtocolOperationV2.CAPABILITY


def test_admit_new_provider_write_rejects_v1() -> None:
    with pytest.raises(ArbitraryPayloadProtocolError, match="LogicProviderProtocol@2"):
        admit_new_provider_write(
            {
                "schema_version": LOGIC_PROVIDER_REQUEST_SCHEMA,
                "protocol_version": 1,
                "request_id": "req:legacy-write",
                "operation": "prove",
                "payload": {"formula": "P"},
            }
        )


def test_admit_provider_request_v2_still_rejects_v1_bypass() -> None:
    """LPC-050 invariant: pure @2 admission never silently accepts v1."""

    with pytest.raises(ArbitraryPayloadProtocolError, match="LogicProvider@1"):
        admit_provider_request_v2(
            {
                "schema_version": LOGIC_PROVIDER_REQUEST_SCHEMA,
                "protocol_version": 1,
                "operation": "prove",
                "payload": {"formula": "P"},
                "request_id": "req:v1-bypass",
            }
        )


def test_elevated_request_round_trips_through_v2_admission() -> None:
    elevated = elevate_v1_to_v2(
        _v1_request("prove", {"statement": "P"}),
        backend_request=_backend_request(),
    )
    readmitted = admit_provider_request_v2(elevated.to_dict())
    assert readmitted.operation is ProtocolOperationV2.PROVE
    assert readmitted.backend_request is not None


def test_new_write_executable_requires_backend_request_v2() -> None:
    backend = _backend_request()
    request = ProveCheckRequestV2(
        request_id="req:new-exec",
        bounds=_bounds(),
        backend_request=backend,
        mode="prove",
        statement="P",
    )
    admitted = admit_new_provider_write(request.to_dict())
    assert admitted.backend_request is not None
    assert admitted.backend_request.interface == BACKEND_REQUEST_V2_INTERFACE
