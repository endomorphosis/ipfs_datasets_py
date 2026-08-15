"""LPC-052: Typed provider responses with untrusted default authority.

Acceptance:

* Responses carry request id, operation, provider id/version, operation status,
  verdict, evidence kind/authority, boundedness, assumptions, translations,
  sources, artifacts, resources, cache provenance, and error.
* Default evidence authority is untrusted (advisory).
* Operation success never upgrades authority.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.backends.protocol_v2 import (
    LOGIC_PROVIDER_PROTOCOL_VERSION,
    ProtocolOperationV2,
)
from ipfs_datasets_py.logic.backends.provider import (
    LogicProviderFailure,
    LogicProviderFailureCode,
)
from ipfs_datasets_py.logic.backends.response_v2 import (
    CACHE_PROVENANCE_V2_SCHEMA,
    DEFAULT_BOUNDEDNESS,
    DEFAULT_EVIDENCE_AUTHORITY,
    DEFAULT_EVIDENCE_KIND,
    DEFAULT_SEMANTIC_VERDICT,
    PROVIDER_RESPONSE_V2_INTERFACE,
    PROVIDER_RESPONSE_V2_MODULE_VERSION,
    PROVIDER_RESPONSE_V2_SCHEMA,
    REQUIRED_RESPONSE_FIELDS,
    CacheHitKind,
    CacheProvenanceV2,
    ProviderResponseV2,
    ResponseArtifactRef,
    ResponseAuthorityError,
    ResponseSourceRef,
    ResponseTranslationRef,
    ResponseV2Error,
    admit_provider_response_v2,
    default_untrusted_authority,
    response_carries_required_fields,
)
from ipfs_datasets_py.logic.ir_core.axes import (
    LogicBoundedness,
    LogicEvidenceAuthority,
    LogicEvidenceKind,
    LogicOperationStatus,
    LogicSemanticVerdict,
    LogicTranslationPreservation,
)
from ipfs_datasets_py.logic.ir_core.protocols import ResourceUsage


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _resources() -> ResourceUsage:
    return ResourceUsage(
        elapsed_ms=12,
        steps=40,
        peak_memory_bytes=2048,
        output_bytes=256,
    )


def _full_response(**changes: object) -> ProviderResponseV2:
    fields: dict[str, object] = {
        "request_id": "req:lpc-052-1",
        "operation": ProtocolOperationV2.PROVE,
        "provider_id": "provider.z3",
        "provider_version": "4.12.0",
        "operation_status": LogicOperationStatus.SUCCEEDED,
        "verdict": LogicSemanticVerdict.UNKNOWN,
        "evidence_kind": LogicEvidenceKind.CANDIDATE,
        "evidence_authority": LogicEvidenceAuthority.ADVISORY,
        "boundedness": LogicBoundedness.UNKNOWN,
        "assumptions": ("asm:classical", "asm:integer-model"),
        "translations": (
            ResponseTranslationRef(
                translation_id="tr:smtlib2-to-internal",
                content_digest=_digest("translation"),
                preservation=LogicTranslationPreservation.EQUISATISFIABLE,
            ),
        ),
        "sources": (
            ResponseSourceRef(
                document_id="doc:lpc-052",
                source_digest=_digest("source"),
            ),
        ),
        "artifacts": (
            ResponseArtifactRef(
                artifact_id="artifact:witness-1",
                content_digest=_digest("artifact"),
                kind="witness",
            ),
        ),
        "resources": _resources(),
        "cache_provenance": CacheProvenanceV2.miss(reason="cold"),
        "error": None,
        "duration_ms": 12,
    }
    fields.update(changes)
    return ProviderResponseV2(**fields)  # type: ignore[arg-type]


def _note_path() -> Path:
    note_relative = Path(
        "data/agent_supervisor/logic_platform_canonicalization/notes/"
        "provider_responses.md"
    )
    for parent in Path(__file__).resolve().parents:
        candidate = parent / note_relative
        if candidate.is_file():
            return candidate
    return Path(__file__).resolve().parents[5] / note_relative


# ---------------------------------------------------------------------------
# Identities and inventory
# ---------------------------------------------------------------------------


def test_interface_and_schema_identities() -> None:
    assert PROVIDER_RESPONSE_V2_INTERFACE == "LogicProviderResponse@2"
    assert PROVIDER_RESPONSE_V2_SCHEMA == (
        "ipfs_datasets_py/logic-provider-response@2"
    )
    assert PROVIDER_RESPONSE_V2_MODULE_VERSION == "1.0.0"
    assert LOGIC_PROVIDER_PROTOCOL_VERSION == 2
    assert CACHE_PROVENANCE_V2_SCHEMA.endswith("@2")


def test_required_field_inventory_matches_acceptance() -> None:
    expected = {
        "request_id",
        "operation",
        "provider_id",
        "provider_version",
        "operation_status",
        "verdict",
        "evidence_kind",
        "evidence_authority",
        "boundedness",
        "assumptions",
        "translations",
        "sources",
        "artifacts",
        "resources",
        "cache_provenance",
        "error",
    }
    assert set(REQUIRED_RESPONSE_FIELDS) == expected
    assert len(REQUIRED_RESPONSE_FIELDS) == 16


def test_response_carries_every_acceptance_field() -> None:
    response = _full_response()
    payload = response.to_dict()
    for field_name in REQUIRED_RESPONSE_FIELDS:
        assert field_name in payload, f"missing required field {field_name}"
    assert response_carries_required_fields(response)
    assert response_carries_required_fields(payload)

    # Spot-check values for each acceptance field.
    assert response.request_id == "req:lpc-052-1"
    assert response.operation is ProtocolOperationV2.PROVE
    assert response.provider_id == "provider.z3"
    assert response.provider_version == "4.12.0"
    assert response.operation_status is LogicOperationStatus.SUCCEEDED
    assert response.verdict is LogicSemanticVerdict.UNKNOWN
    assert response.evidence_kind is LogicEvidenceKind.CANDIDATE
    assert response.evidence_authority is LogicEvidenceAuthority.ADVISORY
    assert response.boundedness is LogicBoundedness.UNKNOWN
    assert response.assumptions == ("asm:classical", "asm:integer-model")
    assert len(response.translations) == 1
    assert response.translations[0].translation_id == "tr:smtlib2-to-internal"
    assert len(response.sources) == 1
    assert response.sources[0].document_id == "doc:lpc-052"
    assert len(response.artifacts) == 1
    assert response.artifacts[0].artifact_id == "artifact:witness-1"
    assert response.resources.elapsed_ms == 12
    assert response.cache_provenance.hit_kind is CacheHitKind.MISS
    assert response.error is None


# ---------------------------------------------------------------------------
# Untrusted default authority
# ---------------------------------------------------------------------------


def test_default_authority_is_untrusted_advisory() -> None:
    assert DEFAULT_EVIDENCE_AUTHORITY is LogicEvidenceAuthority.ADVISORY
    assert default_untrusted_authority() is LogicEvidenceAuthority.ADVISORY
    assert DEFAULT_SEMANTIC_VERDICT is LogicSemanticVerdict.UNKNOWN
    assert DEFAULT_EVIDENCE_KIND is LogicEvidenceKind.CANDIDATE
    assert DEFAULT_BOUNDEDNESS is LogicBoundedness.UNKNOWN


def test_succeeded_factory_applies_untrusted_defaults() -> None:
    response = ProviderResponseV2.succeeded(
        request_id="req:default-auth",
        operation="check",
        provider_id="provider.cvc5",
        provider_version="1.1.0",
    )
    assert response.operation is ProtocolOperationV2.CHECK
    assert response.operation_status is LogicOperationStatus.SUCCEEDED
    assert response.is_success
    assert response.verdict is LogicSemanticVerdict.UNKNOWN
    assert response.evidence_kind is LogicEvidenceKind.CANDIDATE
    assert response.evidence_authority is LogicEvidenceAuthority.ADVISORY
    assert response.default_authority_applied
    assert not response.is_trusted
    assert response.boundedness is LogicBoundedness.UNKNOWN
    assert response.error is None
    assert response_carries_required_fields(response)


def test_succeeded_unknown_advisory_is_representable_and_not_proof() -> None:
    """LPC-032 counterexample must remain a valid provider response."""

    response = ProviderResponseV2.succeeded(
        request_id="req:succeeded-unknown-advisory",
        operation=ProtocolOperationV2.PROVE,
        provider_id="provider.advisory",
        provider_version="0.1.0",
        verdict=LogicSemanticVerdict.UNKNOWN,
        evidence_kind=LogicEvidenceKind.CANDIDATE,
        evidence_authority=LogicEvidenceAuthority.ADVISORY,
        boundedness=LogicBoundedness.UNKNOWN,
        artifacts=(
            ResponseArtifactRef(
                artifact_id="artifact:candidate",
                content_digest=_digest("candidate"),
                kind="candidate",
            ),
        ),
    )
    assert response.is_success
    assert response.verdict is LogicSemanticVerdict.UNKNOWN
    assert not response.verdict.conclusive
    assert response.evidence_authority is LogicEvidenceAuthority.ADVISORY
    assert not response.is_trusted
    # Success is lifecycle only — not a proof claim.
    assert response.operation_status is LogicOperationStatus.SUCCEEDED
    assert response.verdict is not LogicSemanticVerdict.PROVED


def test_silent_authority_upgrade_fails_closed() -> None:
    response = ProviderResponseV2.succeeded(
        request_id="req:no-upgrade",
        operation="prove",
        provider_id="provider.z3",
        provider_version="4.12.0",
    )
    with pytest.raises(ResponseAuthorityError, match="allow_upgrade"):
        response.with_authority(LogicEvidenceAuthority.AUTHORITATIVE)

    upgraded = response.with_authority(
        LogicEvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        allow_upgrade=True,
    )
    assert upgraded.evidence_authority is (
        LogicEvidenceAuthority.INDEPENDENTLY_CHECKABLE
    )
    assert upgraded.is_trusted
    # Original remains untrusted.
    assert response.default_authority_applied


# ---------------------------------------------------------------------------
# Failure path
# ---------------------------------------------------------------------------


def test_failed_response_requires_error_and_keeps_untrusted_authority() -> None:
    response = ProviderResponseV2.failed(
        request_id="req:fail-1",
        operation=ProtocolOperationV2.VERIFY,
        provider_id="provider.lean",
        provider_version="4.0.0",
        code=LogicProviderFailureCode.TIMED_OUT,
        message="verification budget exhausted",
        retryable=True,
        resources=_resources(),
    )
    assert response.operation_status is LogicOperationStatus.FAILED
    assert not response.is_success
    assert isinstance(response.error, LogicProviderFailure)
    assert response.error.code is LogicProviderFailureCode.TIMED_OUT
    assert response.evidence_authority is LogicEvidenceAuthority.ADVISORY
    assert not response.is_trusted
    assert response_carries_required_fields(response)


def test_succeeded_cannot_carry_error() -> None:
    with pytest.raises(ResponseV2Error, match="cannot carry an error"):
        ProviderResponseV2(
            request_id="req:bad-success",
            operation="prove",
            provider_id="provider.z3",
            provider_version="1.0.0",
            operation_status=LogicOperationStatus.SUCCEEDED,
            error=LogicProviderFailure(
                code=LogicProviderFailureCode.PROVIDER_ERROR,
                message="should not appear on success",
            ),
        )


def test_failed_status_requires_error() -> None:
    with pytest.raises(ResponseV2Error, match="requires an error"):
        ProviderResponseV2(
            request_id="req:bad-fail",
            operation="prove",
            provider_id="provider.z3",
            provider_version="1.0.0",
            operation_status=LogicOperationStatus.FAILED,
            error=None,
        )


# ---------------------------------------------------------------------------
# Cache provenance
# ---------------------------------------------------------------------------


def test_cache_miss_and_hit_provenance() -> None:
    miss = CacheProvenanceV2.miss(reason="cold-start")
    assert miss.hit_kind is CacheHitKind.MISS
    assert not miss.is_hit

    hit = CacheProvenanceV2(
        hit_kind=CacheHitKind.HIT,
        cache_key_digest=_digest("cache-key"),
        entry_digest=_digest("entry"),
        reason="exact-key",
    )
    assert hit.is_hit
    response = _full_response(cache_provenance=hit)
    assert response.cache_provenance.hit_kind is CacheHitKind.HIT
    # Cache hit does not raise authority.
    assert response.evidence_authority is LogicEvidenceAuthority.ADVISORY
    assert not response.is_trusted


def test_cache_hit_without_digests_fails_closed() -> None:
    with pytest.raises(ResponseV2Error, match="cache hit"):
        CacheProvenanceV2(hit_kind=CacheHitKind.HIT)


# ---------------------------------------------------------------------------
# Round-trip and admission
# ---------------------------------------------------------------------------


def test_dict_and_json_round_trip_preserves_inventory() -> None:
    original = _full_response(
        operation=ProtocolOperationV2.TRANSLATE,
        verdict=LogicSemanticVerdict.INCONCLUSIVE,
        translation_preservation=LogicTranslationPreservation.BOUNDED_ABSTRACTION,
    )
    restored = ProviderResponseV2.from_dict(original.to_dict())
    assert restored.to_dict() == original.to_dict()
    assert response_carries_required_fields(restored)

    from_json = ProviderResponseV2.from_json(original.to_json())
    assert from_json.to_dict() == original.to_dict()

    admitted = admit_provider_response_v2(original.to_dict())
    assert admitted.request_id == original.request_id
    assert admitted.operation is ProtocolOperationV2.TRANSLATE
    assert len(admitted.content_digest()) == 64


def test_admit_rejects_protocol_version_one() -> None:
    payload = _full_response().to_dict()
    payload["protocol_version"] = 1
    with pytest.raises(ResponseV2Error, match="protocol_version=2"):
        admit_provider_response_v2(payload)


def test_admit_rejects_unknown_fields() -> None:
    payload = _full_response().to_dict()
    payload["payload"] = {"free_form": True}
    with pytest.raises(Exception, match="unknown"):
        admit_provider_response_v2(payload)


@pytest.mark.parametrize(
    "operation",
    [
        ProtocolOperationV2.CAPABILITY,
        ProtocolOperationV2.TRANSLATE,
        ProtocolOperationV2.PROVE,
        ProtocolOperationV2.CHECK,
        ProtocolOperationV2.RECONSTRUCT,
        ProtocolOperationV2.VERIFY,
        ProtocolOperationV2.ATTEST,
    ],
)
def test_response_supports_every_protocol_v2_operation(
    operation: ProtocolOperationV2,
) -> None:
    response = ProviderResponseV2.succeeded(
        request_id=f"req:op-{operation.value}",
        operation=operation,
        provider_id="provider.example",
        provider_version="1.0.0",
    )
    assert response.operation is operation
    assert response_carries_required_fields(response)


# ---------------------------------------------------------------------------
# Note
# ---------------------------------------------------------------------------


def test_provider_responses_note_documents_inventory_and_defaults() -> None:
    note = _note_path()
    assert note.is_file(), f"missing LPC-052 note at {note}"
    text = note.read_text(encoding="utf-8")
    assert "LPC-052" in text
    assert "LogicProviderResponse@2" in text
    assert "untrusted" in text.lower()
    assert "advisory" in text
    for field_name in REQUIRED_RESPONSE_FIELDS:
        assert field_name in text, f"note missing field {field_name}"
    assert "response_v2" in text
    assert "DEFAULT_EVIDENCE_AUTHORITY" in text
