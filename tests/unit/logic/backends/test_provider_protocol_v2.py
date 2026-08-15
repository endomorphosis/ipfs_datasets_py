"""LPC-050: LogicProviderProtocol@2 operation-specific typed requests.

Acceptance:

* Typed requests exist for capability, translation, prove/check, reconstruct,
  verify, and attest.
* Executable operations require positive finite bounds.
* Free-form v1-style payloads cannot be admitted as @2.
"""

from __future__ import annotations

import hashlib
from typing import Any

import pytest

from ipfs_datasets_py.logic.backends.protocol_v2 import (
    EXECUTABLE_OPERATIONS,
    LOGIC_PROVIDER_PROTOCOL_V2_INTERFACE,
    LOGIC_PROVIDER_PROTOCOL_VERSION,
    PROTOCOL_V2_OPERATIONS,
    ArbitraryPayloadProtocolError,
    AttestRequestV2,
    CapabilityRequestV2,
    LogicProviderProtocolV2,
    MissingExecutableBoundsError,
    ProveCheckMode,
    ProveCheckRequestV2,
    ProtocolOperationV2,
    ProtocolV2AdmissionError,
    ProtocolV2Error,
    ProviderProtocolEnvelopeV2,
    ReconstructRequestV2,
    TranslationRequestV2,
    VerifyRequestV2,
    admit_provider_request_v2,
    is_executable_operation,
    require_executable_bounds,
    v1_operation_for,
)
from ipfs_datasets_py.logic.backends.provider import LogicProviderOperation
from ipfs_datasets_py.logic.backends.requests_v2 import (
    BackendRequestV2,
    MissingBoundsError,
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
    request_id: str = "req:protocol-v2-1",
    bounds: RequestBounds | None = None,
) -> BackendRequestV2:
    bounds = bounds or _bounds()
    return BackendRequestV2(
        request_id=request_id,
        obligation_id="obl:protocol-v2-1",
        obligation_digest=_digest("obligation"),
        document_id="doc:protocol-v2",
        source_digest=_digest("source"),
        expression_id="expr:protocol-v2",
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


# ---------------------------------------------------------------------------
# Identities and closed vocabularies
# ---------------------------------------------------------------------------


def test_protocol_v2_interface_identity() -> None:
    assert LOGIC_PROVIDER_PROTOCOL_V2_INTERFACE == "LogicProviderProtocol@2"
    assert LOGIC_PROVIDER_PROTOCOL_VERSION == 2
    assert PROTOCOL_V2_OPERATIONS == frozenset(
        {
            "capability",
            "translate",
            "prove",
            "check",
            "reconstruct",
            "verify",
            "attest",
        }
    )
    assert EXECUTABLE_OPERATIONS == frozenset(
        {
            "translate",
            "prove",
            "check",
            "reconstruct",
            "verify",
            "attest",
        }
    )
    assert "capability" not in EXECUTABLE_OPERATIONS


def test_typed_request_classes_exist_for_every_operation_family() -> None:
    families = {
        "capability": CapabilityRequestV2,
        "translation": TranslationRequestV2,
        "prove_check": ProveCheckRequestV2,
        "reconstruct": ReconstructRequestV2,
        "verify": VerifyRequestV2,
        "attest": AttestRequestV2,
    }
    assert set(families) == {
        "capability",
        "translation",
        "prove_check",
        "reconstruct",
        "verify",
        "attest",
    }
    for cls in families.values():
        assert cls.interface == LOGIC_PROVIDER_PROTOCOL_V2_INTERFACE


def test_logic_provider_protocol_v2_is_runtime_checkable() -> None:
    assert issubclass(LogicProviderProtocolV2, object)


# ---------------------------------------------------------------------------
# Capability (non-executable)
# ---------------------------------------------------------------------------


def test_capability_request_does_not_require_bounds() -> None:
    request = CapabilityRequestV2(
        request_id="req:cap-1",
        provider_id="z3",
        feature_query=("smt", "qf_lra"),
        include_versions=True,
    )
    assert request.operation is ProtocolOperationV2.CAPABILITY
    assert request.bounds is None
    assert request.backend_request is None
    assert not is_executable_operation(request.operation)
    restored = CapabilityRequestV2.from_dict(request.to_dict())
    assert restored.to_dict() == request.to_dict()


def test_capability_rejects_free_form_payload_metadata() -> None:
    with pytest.raises(ArbitraryPayloadProtocolError, match="free-form"):
        CapabilityRequestV2(
            request_id="req:cap-bad",
            metadata={"payload": {"logic_family": "smt"}},
        )


# ---------------------------------------------------------------------------
# Executable ops require positive finite bounds
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("factory", "kwargs"),
    [
        (
            TranslationRequestV2,
            {
                "source_encoding": "smtlib2",
                "target_encoding": "tptp",
            },
        ),
        (
            ProveCheckRequestV2,
            {"mode": ProveCheckMode.PROVE, "statement": "prove P"},
        ),
        (
            ProveCheckRequestV2,
            {"mode": ProveCheckMode.CHECK, "statement": "check P"},
        ),
        (
            ReconstructRequestV2,
            {"candidate_digest": _digest("candidate")},
        ),
        (
            VerifyRequestV2,
            {"evidence_digest": _digest("evidence")},
        ),
        (
            AttestRequestV2,
            {"statement_digest": _digest("statement")},
        ),
    ],
)
def test_executable_requests_require_positive_finite_bounds(
    factory: type[Any], kwargs: dict[str, Any]
) -> None:
    backend = _backend_request()
    bounds = _bounds()
    request = factory(
        request_id=f"req:{factory.__name__}",
        bounds=bounds,
        backend_request=backend,
        **kwargs,
    )
    assert is_executable_operation(request.operation)
    assert isinstance(request.bounds, RequestBounds)
    assert request.bounds.timeout_ms > 0
    assert request.bounds.max_steps > 0
    assert request.bounds.max_memory_bytes > 0
    assert request.bounds.max_output_bytes > 0
    enforced = require_executable_bounds(request)
    assert enforced.to_dict() == bounds.to_dict()
    restored = factory.from_dict(request.to_dict())
    assert restored.operation is request.operation
    assert restored.bounds is not None
    assert restored.bounds.to_dict() == bounds.to_dict()


@pytest.mark.parametrize(
    ("factory", "kwargs"),
    [
        (
            TranslationRequestV2,
            {
                "source_encoding": "smtlib2",
                "target_encoding": "tptp",
            },
        ),
        (ProveCheckRequestV2, {"mode": "prove"}),
        (ReconstructRequestV2, {"candidate_digest": _digest("c")}),
        (VerifyRequestV2, {"evidence_digest": _digest("e")}),
        (AttestRequestV2, {"statement_digest": _digest("s")}),
    ],
)
def test_executable_requests_reject_missing_bounds(
    factory: type[Any], kwargs: dict[str, Any]
) -> None:
    with pytest.raises(
        (MissingExecutableBoundsError, MissingBoundsError),
        match="bounds",
    ):
        factory(
            request_id=f"req:missing-bounds:{factory.__name__}",
            bounds=None,  # type: ignore[arg-type]
            backend_request=_backend_request(),
            **kwargs,
        )


@pytest.mark.parametrize(
    "bad_bounds",
    [
        {"timeout_ms": 0, "max_steps": 1, "max_memory_bytes": 1, "max_output_bytes": 1},
        {
            "timeout_ms": -1,
            "max_steps": 1,
            "max_memory_bytes": 1,
            "max_output_bytes": 1,
        },
        {"timeout_ms": 1, "max_steps": 1, "max_memory_bytes": 1},  # incomplete
    ],
)
def test_executable_requests_reject_non_positive_or_incomplete_bounds(
    bad_bounds: dict[str, Any],
) -> None:
    with pytest.raises(
        (MissingExecutableBoundsError, MissingBoundsError, ProtocolV2Error)
    ):
        TranslationRequestV2(
            request_id="req:bad-bounds",
            bounds=bad_bounds,
            backend_request=_backend_request(),
            source_encoding="smtlib2",
            target_encoding="tptp",
        )


def test_executable_from_dict_rejects_missing_bounds_field() -> None:
    backend = _backend_request()
    payload = {
        "request_id": "req:no-bounds-field",
        "operation": "translate",
        "backend_request": backend.to_dict(),
        "source_encoding": "smtlib2",
        "target_encoding": "tptp",
    }
    with pytest.raises(MissingExecutableBoundsError, match="bounds"):
        TranslationRequestV2.from_dict(payload)


def test_prove_and_check_share_typed_request_family() -> None:
    backend = _backend_request()
    prove = ProveCheckRequestV2(
        request_id="req:prove",
        bounds=_bounds(),
        backend_request=backend,
        mode=ProveCheckMode.PROVE,
        statement="prove P",
    )
    check = ProveCheckRequestV2(
        request_id="req:check",
        bounds=_bounds(),
        backend_request=backend,
        mode=ProveCheckMode.CHECK,
        statement="check P",
    )
    assert prove.operation is ProtocolOperationV2.PROVE
    assert check.operation is ProtocolOperationV2.CHECK
    assert prove.mode is ProveCheckMode.PROVE
    assert check.mode is ProveCheckMode.CHECK


def test_operation_bounds_cannot_exceed_backend_request_bounds() -> None:
    backend = _backend_request(bounds=_bounds(timeout_ms=1_000))
    with pytest.raises(ProtocolV2AdmissionError, match="cannot exceed"):
        ProveCheckRequestV2(
            request_id="req:loose-bounds",
            bounds=_bounds(timeout_ms=60_000),
            backend_request=backend,
            mode="prove",
        )


# ---------------------------------------------------------------------------
# Admission / envelope
# ---------------------------------------------------------------------------


def test_admit_provider_request_v2_discriminates_operations() -> None:
    backend = _backend_request()
    cases = [
        CapabilityRequestV2(request_id="req:a", provider_id="z3"),
        TranslationRequestV2(
            request_id="req:b",
            bounds=_bounds(),
            backend_request=backend,
            source_encoding="smtlib2",
            target_encoding="tptp",
        ),
        ProveCheckRequestV2(
            request_id="req:c",
            bounds=_bounds(),
            backend_request=backend,
            mode="check",
        ),
        ReconstructRequestV2(
            request_id="req:d",
            bounds=_bounds(),
            backend_request=backend,
            candidate_digest=_digest("cand"),
        ),
        VerifyRequestV2(
            request_id="req:e",
            bounds=_bounds(),
            backend_request=backend,
            evidence_digest=_digest("ev"),
        ),
        AttestRequestV2(
            request_id="req:f",
            bounds=_bounds(),
            backend_request=backend,
            statement_digest=_digest("st"),
        ),
    ]
    for original in cases:
        admitted = admit_provider_request_v2(original.to_dict())
        assert type(admitted) is type(original)
        assert admitted.operation is original.operation


def test_envelope_round_trip() -> None:
    request = CapabilityRequestV2(request_id="req:env", provider_id="lean")
    envelope = ProviderProtocolEnvelopeV2(request=request)
    assert envelope.operation is ProtocolOperationV2.CAPABILITY
    assert not envelope.executable
    restored = ProviderProtocolEnvelopeV2.from_dict(envelope.to_dict())
    assert restored.request.to_dict() == request.to_dict()


def test_admit_rejects_v1_generic_payload_envelope() -> None:
    with pytest.raises(ArbitraryPayloadProtocolError, match="LogicProvider@1"):
        admit_provider_request_v2(
            {
                "schema_version": "ipfs_datasets_py/logic-provider-request@1",
                "protocol_version": 1,
                "operation": "prove",
                "payload": {"formula": "P"},
                "request_id": "req:v1",
            }
        )


def test_admit_rejects_free_form_payload_key() -> None:
    with pytest.raises(ArbitraryPayloadProtocolError, match="free-form"):
        admit_provider_request_v2(
            {
                "operation": "capability",
                "request_id": "req:payload",
                "payload": {"anything": True},
            }
        )


def test_admit_rejects_unknown_operation() -> None:
    with pytest.raises(ProtocolV2Error, match="operation"):
        admit_provider_request_v2(
            {
                "operation": "optimize",
                "request_id": "req:unknown-op",
            }
        )


def test_require_executable_bounds_rejects_capability() -> None:
    request = CapabilityRequestV2(request_id="req:cap-bounds")
    with pytest.raises(ProtocolV2Error, match="not executable"):
        require_executable_bounds(request)


def test_v1_operation_mapping_covers_protocol_v2_ops() -> None:
    assert v1_operation_for("capability") is LogicProviderOperation.CAPABILITY
    assert v1_operation_for("translate") is LogicProviderOperation.TRANSLATE
    assert v1_operation_for("prove") is LogicProviderOperation.PROVE
    assert v1_operation_for("check") is LogicProviderOperation.PROVE
    assert v1_operation_for("reconstruct") is LogicProviderOperation.RECONSTRUCT
    assert v1_operation_for("verify") is LogicProviderOperation.VERIFY
    assert v1_operation_for("attest") is LogicProviderOperation.ATTEST


def test_protocol_operation_executable_flags() -> None:
    assert ProtocolOperationV2.CAPABILITY.executable is False
    assert ProtocolOperationV2.PROVE.executable is True
    assert ProtocolOperationV2.CHECK.executable is True
    assert ProtocolOperationV2.PROVE.prove_check_family is True
    assert ProtocolOperationV2.TRANSLATE.prove_check_family is False
