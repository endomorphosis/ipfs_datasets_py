"""Unit tests for the secret-safe public counterexample boundary (FVT-002 / FVT-G007).

Covers CounterexampleEnvelope@2 and PublicCounterexampleBoundary@1:

* unknown fields and forged identities fail closed;
* hidden_witness, token, credential, raw source, stdout, and private channels
  never appear publicly;
* raw artifacts are referenced only by private digest/retention metadata;
* projections preserve kind, property, source-map, tool, assumptions, bounds,
  and authority.
"""

from __future__ import annotations

import json
import sys
from typing import Any

import pytest
from ipfs_datasets_py.logic.software_verification.counterexamples.contracts import (
    COUNTEREXAMPLE_ENVELOPE_INTERFACE,
    COUNTEREXAMPLE_ENVELOPE_SCHEMA,
    DEFAULT_DROP_RETENTION_POLICY,
    DEFAULT_PRIVATE_RETENTION_POLICY,
    PRIVATE_ARTIFACT_REFERENCE_SCHEMA,
    PUBLIC_COUNTEREXAMPLE_BOUNDARY_INTERFACE,
    CounterexampleAuthority,
    CounterexampleBoundaryError,
    CounterexampleEnvelope,
    PrivateArtifactReference,
    PublicCounterexampleBoundary,
    project_public_counterexample,
)
from ipfs_datasets_py.logic.verification_api import (
    LogicVerificationAPI,
    VerificationAuthority,
    VerificationStatus,
    get_verification_api,
)


def _leaky_smt_witness(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "model",
        "model": {
            "lease_owner": "worker-a",
            "epoch": 4,
            "hidden_witness": "DO-NOT-PUBLISH-SECRET",
            "credential": "super-secret-credential",
            "note": "Authorization: Bearer abcdefghijklmnopqrstuvwxyz012345",
        },
        "stdout": "unbounded solver transcript with secrets",
        "source_excerpt": "def secrets(): pass",
        "source_code": "complete repository source",
        "raw_output": "solver dump " * 200,
        "violated_property": "obligation:exclusive-lease",
        "assumption_ids": ["assumption:token-order", "assumption:single-owner"],
        "finite_bounds": {"timeout_ms": 500, "max_steps": 32},
        "provider_id": "provider:z3",
        "tool_id": "solver.z3",
        "source_ref_ids": ["source:lease.py"],
        "span_ids": ["span:lease-claim"],
        "ast_scope_id": "symbol:claim_lease",
        "tree_id": "tree:repo@1",
        "summary": "lease owner conflict",
    }
    payload.update(overrides)
    return payload


def test_interfaces_and_schema_constants() -> None:
    assert COUNTEREXAMPLE_ENVELOPE_INTERFACE == "CounterexampleEnvelope@2"
    assert PUBLIC_COUNTEREXAMPLE_BOUNDARY_INTERFACE == "PublicCounterexampleBoundary@1"
    assert COUNTEREXAMPLE_ENVELOPE_SCHEMA.endswith("@2")
    assert PRIVATE_ARTIFACT_REFERENCE_SCHEMA.endswith("@1")


def test_projection_fails_closed_without_supervisor_normalizer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module_name = (
        "ipfs_accelerate_py.agent_supervisor.proof.formal_counterexamples"
    )
    monkeypatch.setitem(sys.modules, module_name, None)

    with pytest.raises(
        CounterexampleBoundaryError,
        match="supervisor counterexample normalizer is unavailable",
    ):
        project_public_counterexample({"model": {"x": 1}})


def test_public_projection_strips_private_channels_and_tokens() -> None:
    envelope = project_public_counterexample(_leaky_smt_witness())
    public = envelope.to_public_dict()
    encoded = json.dumps(public, sort_keys=True).lower()
    witness = json.dumps(envelope.to_witness_dict(), sort_keys=True).lower()

    for surface in (encoded, witness, envelope.to_json().lower()):
        assert "do-not-publish-secret" not in surface
        assert "super-secret-credential" not in surface
        assert "abcdefghijklmnopqrstuvwxyz012345" not in surface
        assert "hidden_witness" not in surface
        assert "credential" not in surface
        assert "stdout" not in surface
        assert "source_excerpt" not in surface
        assert "source_code" not in surface
        assert "raw_output" not in surface
        assert "complete repository source" not in surface

    assert public["contains_private_material"] is False
    assert public["contains_raw_prover_output"] is False
    assert public["contains_source"] is False
    assert public["schema"] == COUNTEREXAMPLE_ENVELOPE_SCHEMA
    assert public["interface"] == COUNTEREXAMPLE_ENVELOPE_INTERFACE
    assert public["boundary"] == PUBLIC_COUNTEREXAMPLE_BOUNDARY_INTERFACE
    assert "raw" not in public


def test_projections_preserve_kind_property_source_map_tool_assumptions_bounds_authority() -> None:
    envelope = project_public_counterexample(_leaky_smt_witness())

    assert envelope.kind == "smt_model"
    assert envelope.violated_property == "obligation:exclusive-lease"
    assert envelope.property_class == "finite_constraint"
    assert envelope.authority is CounterexampleAuthority.SATISFIABILITY

    assert "assumption:token-order" in envelope.assumptions
    assert "assumption:single-owner" in envelope.assumptions
    assert envelope.bounds.get("timeout_ms") == 500
    assert envelope.bounds.get("max_steps") == 32

    assert envelope.source_map["ast_scope_ids"] == ["symbol:claim_lease"]
    assert envelope.source_map["source_ref_ids"] == ["source:lease.py"]
    assert envelope.source_map["span_ids"] == ["span:lease-claim"]
    assert envelope.source_map["tree_ids"] == ["tree:repo@1"]

    assert envelope.tool["tool_id"] == "solver.z3"
    assert "provider:z3" in envelope.tool["provider_ids"] or envelope.tool_id
    assert envelope.payload["assignments"]["lease_owner"] == "worker-a"
    assert envelope.payload["assignments"]["epoch"] == 4
    # Compatibility model projection is public assignments only.
    assert envelope.model["lease_owner"] == "worker-a"
    assert "hidden_witness" not in envelope.model


def test_private_artifacts_are_digest_and_retention_only() -> None:
    boundary = PublicCounterexampleBoundary(
        private_store={
            "stdout": {
                "digest": "sha256:" + "ab" * 32,
                "retention_policy_id": DEFAULT_PRIVATE_RETENTION_POLICY,
                "byte_size": 4096,
                "media_type": "text/plain",
            }
        }
    )
    envelope = boundary.project(_leaky_smt_witness())
    by_channel = {item.channel: item for item in envelope.private_artifacts}

    # Public taxonomy uses channel classes, never raw secret key names.
    assert "secret_material" in by_channel
    assert "provider_transcript" in by_channel
    assert "source_blob" in by_channel or "provider_artifact" in by_channel
    assert "hidden_witness" not in by_channel
    assert "credential" not in by_channel
    assert "stdout" not in by_channel

    dropped = by_channel["secret_material"]
    assert dropped.retained is False
    assert dropped.retention_policy_id == DEFAULT_DROP_RETENTION_POLICY
    assert dropped.digest.startswith("sha256:")
    assert dropped.to_dict()["schema"] == PRIVATE_ARTIFACT_REFERENCE_SCHEMA
    assert "DO-NOT" not in json.dumps(dropped.to_dict())

    retained = by_channel["provider_transcript"]
    assert retained.retained is True
    assert retained.digest == "sha256:" + "ab" * 32
    assert retained.retention_policy_id == DEFAULT_PRIVATE_RETENTION_POLICY
    assert retained.byte_size == 4096
    # No raw payload keys on the public reference.
    assert set(retained.to_dict()) <= {
        "schema",
        "channel",
        "digest",
        "retention_policy_id",
        "retained",
        "byte_size",
        "media_type",
    }


def test_unknown_fields_fail_closed_on_decode() -> None:
    envelope = project_public_counterexample(
        {"model": {"x": 1}, "violated_property": "p"}
    )
    forged = envelope.to_dict()
    forged["unexpected_channel"] = "leak"
    with pytest.raises(CounterexampleBoundaryError, match="unknown fields"):
        CounterexampleEnvelope.from_dict(forged)


def test_forged_identities_fail_closed() -> None:
    envelope = project_public_counterexample(
        {"model": {"x": 1}, "violated_property": "p"}
    )
    forged_id = envelope.to_dict()
    forged_id["counterexample_id"] = "forged-identity"
    with pytest.raises(CounterexampleBoundaryError, match="identity"):
        CounterexampleEnvelope.from_dict(forged_id)

    forged_content = envelope.to_dict()
    forged_content["content_id"] = "sha256:" + "00" * 32
    with pytest.raises(CounterexampleBoundaryError, match="identity"):
        CounterexampleEnvelope.from_dict(forged_content)

    claims_private = envelope.to_dict()
    claims_private["contains_private_material"] = True
    with pytest.raises(CounterexampleBoundaryError, match="contains_private_material"):
        CounterexampleEnvelope.from_dict(claims_private)


def test_round_trip_decode_preserves_public_envelope() -> None:
    original = project_public_counterexample(_leaky_smt_witness())
    decoded = CounterexampleEnvelope.from_dict(original.to_dict())
    assert decoded.counterexample_id == original.counterexample_id
    assert decoded.content_id == original.content_id
    assert decoded.to_dict() == original.to_dict()
    assert PublicCounterexampleBoundary().decode(original.to_dict()) == decoded


def test_secrets_do_not_affect_semantic_identity() -> None:
    first = project_public_counterexample(_leaky_smt_witness())
    # Same public model fields; only private channels / token values change.
    second = project_public_counterexample(
        _leaky_smt_witness(
            model={
                "lease_owner": "worker-a",
                "epoch": 4,
                "hidden_witness": "A-DIFFERENT-SECRET",
                "credential": "ANOTHER-CREDENTIAL",
                "note": "Authorization: Bearer totally-different-token-value-9999",
            }
        )
    )
    assert first.counterexample_id == second.counterexample_id
    assert first.semantic_id == second.semantic_id


def test_verification_api_explain_counterexample_uses_public_boundary() -> None:
    api = get_verification_api(reset=True)
    response = api.explain_counterexample(
        _leaky_smt_witness(),
        request_id="req:boundary",
    )
    encoded = json.dumps(response.to_dict(), sort_keys=True).lower()

    assert response.status is VerificationStatus.SUCCEEDED
    # Operation ceiling stays bounded; kind-derived authority is on the envelope.
    assert response.authority is VerificationAuthority.BOUNDED
    assert response.result["authority"] == "satisfiability"
    assert response.request_id == "req:boundary"
    assert response.property_id == "obligation:exclusive-lease"
    assert "raw" not in response.result
    assert response.result["schema"] == COUNTEREXAMPLE_ENVELOPE_SCHEMA
    assert response.result["boundary"] == PUBLIC_COUNTEREXAMPLE_BOUNDARY_INTERFACE
    assert response.result["kind"] == "smt_model"
    assert response.result["model"]["lease_owner"] == "worker-a"
    assert "assumption:token-order" in response.assumptions
    assert response.bounds.get("timeout_ms") == 500
    assert len(response.witnesses) == 1
    assert "raw" not in response.witnesses[0]
    assert "do-not-publish-secret" not in encoded
    assert "hidden_witness" not in encoded
    assert "stdout" not in encoded
    assert "source_code" not in encoded
    assert "abcdefghijklmnopqrstuvwxyz012345" not in encoded


def test_verification_api_rejects_unprojectable_witness() -> None:
    api = LogicVerificationAPI()
    response = api.explain_counterexample(object())
    assert response.status is VerificationStatus.INVALID
    assert response.authority is VerificationAuthority.NONE
    assert response.diagnostics


def test_private_artifact_unknown_fields_fail_closed() -> None:
    with pytest.raises(CounterexampleBoundaryError, match="unknown fields"):
        PrivateArtifactReference.from_dict(
            {
                "channel": "stdout",
                "digest": "sha256:" + "cd" * 32,
                "payload": "never",
            }
        )


def test_module_level_explain_helper_matches_boundary() -> None:
    from ipfs_datasets_py.logic.software_verification.counterexamples.contracts import (
        explain_counterexample_envelope,
    )

    via_helper = explain_counterexample_envelope(_leaky_smt_witness())
    via_project = project_public_counterexample(_leaky_smt_witness())
    assert via_helper.counterexample_id == via_project.counterexample_id
    assert via_helper.to_dict() == via_project.to_dict()


def _public_codec_fixture() -> dict[str, Any]:
    return CounterexampleEnvelope(
        counterexample_id="counterexample:fixture", kind="model",
        property_class="safety", violated_property="property:exclusive",
        summary="bounded fictional witness",
    ).to_dict()


@pytest.mark.parametrize("retained", ["false", "true", 0, 1, 0.0, 1.0, None])
def test_private_retention_decode_rejects_coercion(retained: Any) -> None:
    with pytest.raises(CounterexampleBoundaryError, match="boolean"):
        PrivateArtifactReference.from_dict({
            "channel": "provider_transcript", "digest": "sha256:" + "ab" * 32,
            "retention_policy_id": DEFAULT_PRIVATE_RETENTION_POLICY,
            "retained": retained,
        })


@pytest.mark.parametrize("artifact", [None, "discard-me", 1, False, []])
def test_envelope_decode_never_discards_malformed_artifacts(artifact: Any) -> None:
    value = _public_codec_fixture()
    value["private_artifacts"] = [artifact]
    with pytest.raises(CounterexampleBoundaryError, match="every private artifact"):
        CounterexampleEnvelope.from_dict(value)


@pytest.mark.parametrize("truncated", ["false", "true", 0, 1, None])
def test_truncation_decode_rejects_coercion(truncated: Any) -> None:
    value = _public_codec_fixture()
    value.update(truncated=truncated, content_id="")
    with pytest.raises(CounterexampleBoundaryError, match="boolean"):
        CounterexampleEnvelope.from_dict(value)


@pytest.mark.parametrize("field,value", [
    ("property_id", "property:other"), ("tool_id", "provider:other"),
    ("finite_bounds", {"steps": 10}), ("model", {"different": 1}),
    ("assumption_ids", ["assumption:other"]),
])
def test_compatibility_aliases_cannot_disagree(field: str, value: Any) -> None:
    raw = _public_codec_fixture()
    raw[field] = value
    with pytest.raises(CounterexampleBoundaryError, match="alias"):
        CounterexampleEnvelope.from_dict(raw)


@pytest.mark.parametrize("field,value", [
    ("interface", "CounterexampleEnvelope@999"), ("boundary", "another-boundary"),
    ("envelope_version", True), ("envelope_version", 1.0), ("redacted", 1),
    ("contains_source", 0), ("contains_private_material", 0.0),
])
def test_decode_rejects_false_profile_or_denial_flags(field: str, value: Any) -> None:
    raw = _public_codec_fixture()
    raw[field] = value
    with pytest.raises(CounterexampleBoundaryError):
        CounterexampleEnvelope.from_dict(raw)


@pytest.mark.parametrize("field", ["contains_source", "contains_private_material",
    "contains_raw_prover_output", "retained", "redacted", "truncated", "minimized"])
def test_denial_flag_names_cannot_hide_private_payload(field: str) -> None:
    with pytest.raises(CounterexampleBoundaryError, match="boolean"):
        CounterexampleEnvelope(
            counterexample_id="counterexample:fictional", kind="model",
            property_class="safety", violated_property="property:one", summary="fictional",
            payload={field: "source_text must not escape through a flag"},
        )


def test_typed_source_map_and_redaction_helpers_use_current_wire() -> None:
    from ipfs_datasets_py.logic.software_verification.counterexamples.contracts import (
        SourceMapRef, RedactionReport, ConfidentialityDisposition,
    )
    source = SourceMapRef(source_ref_ids=("source:b", "source:a"), span_ids=("span:one",))
    assert SourceMapRef.from_dict(source.to_dict()) == source
    report = RedactionReport(dropped_fields=2, redacted_values=3)
    assert report.disposition is ConfidentialityDisposition.PUBLIC_REDACTED
    assert RedactionReport.from_dict(report.to_dict()) == report
    envelope = CounterexampleEnvelope(
        counterexample_id="counterexample:fictional", kind="model", property_class="safety",
        violated_property="property:one", summary="fictional", source_map=source.to_dict(),
        redaction=report.to_dict(),
    )
    assert envelope.schema == COUNTEREXAMPLE_ENVELOPE_SCHEMA
    assert PublicCounterexampleBoundary().validate(envelope).to_dict() == envelope.to_dict()


@pytest.mark.parametrize("value", [True, 1.0, "1", -1, None])
def test_typed_redaction_counts_never_coerce(value: Any) -> None:
    from ipfs_datasets_py.logic.software_verification.counterexamples.contracts import RedactionReport
    with pytest.raises(CounterexampleBoundaryError):
        RedactionReport.from_dict({"dropped_fields": value})


@pytest.mark.parametrize("raw", [
    {"source_ref_ids": "source:one"}, {"source_ref_ids": [True]},
    {"source_ref_ids": ["x" * 257]}, {"source_text": "private bytes"},
    {"source_ref_ids": ["/home/example/private.py"]},
    {"source_ref_ids": ["C:\\private\\file.py"]},
])
def test_typed_source_map_rejects_unknown_or_lossy_values(raw: Any) -> None:
    from ipfs_datasets_py.logic.software_verification.counterexamples.contracts import SourceMapRef
    with pytest.raises(CounterexampleBoundaryError):
        SourceMapRef.from_dict(raw)


def test_batch_projection_retains_distinct_provenance_without_union(monkeypatch: pytest.MonkeyPatch) -> None:
    first = CounterexampleEnvelope.from_dict(_public_codec_fixture())
    second = CounterexampleEnvelope(
        counterexample_id=first.counterexample_id, kind=first.kind,
        property_class=first.property_class, violated_property=first.violated_property,
        summary=first.summary, assumptions=("assumption:another",),
        source_map={"source_ref_ids": ["source:another"]}, bounds={"steps": 2},
    )
    boundary = PublicCounterexampleBoundary()
    monkeypatch.setattr(boundary, "project", lambda item, **kwargs: item)
    projected = boundary.project_many([first, first, second])
    assert projected == (first, second)
    assert projected[0].assumptions == ()
    assert projected[1].assumptions == ("assumption:another",)
    assert len({x.content_id for x in projected}) == 2


def test_real_batch_projection_reuses_canonical_normalizer() -> None:
    boundary = PublicCounterexampleBoundary()
    witnesses = [_leaky_smt_witness(), _leaky_smt_witness()]
    projected = boundary.project_many(witnesses)
    assert len(projected) == 1
    assert projected[0].to_dict() == boundary.project(witnesses[0]).to_dict()


def test_batch_projection_bound_counts_duplicates(monkeypatch: pytest.MonkeyPatch) -> None:
    envelope = CounterexampleEnvelope.from_dict(_public_codec_fixture())
    boundary = PublicCounterexampleBoundary()
    monkeypatch.setattr(boundary, "project", lambda item, **kwargs: item)
    with pytest.raises(CounterexampleBoundaryError, match="max_items"):
        boundary.project_many([envelope, envelope], max_items=1)


def test_validate_rejects_variant_wire_and_forged_digest() -> None:
    raw = _public_codec_fixture()
    raw["schema"] = "counterexample-envelope/v2"
    with pytest.raises(CounterexampleBoundaryError, match="schema"):
        PublicCounterexampleBoundary().validate(raw)
    raw = _public_codec_fixture()
    raw["content_id"] = "sha256:" + "00" * 32
    with pytest.raises(CounterexampleBoundaryError, match="identity"):
        PublicCounterexampleBoundary().validate(raw)


def test_api_compatibility_keywords_preserve_bounded_authority_and_witness() -> None:
    witness = _leaky_smt_witness()
    snapshot = json.dumps(witness, sort_keys=True)
    result = LogicVerificationAPI().explain_counterexample(
        witness, property_id="obligation:exclusive-lease", tool_id="solver.z3", authority="bounded"
    )
    assert result.status is VerificationStatus.SUCCEEDED
    assert result.authority is VerificationAuthority.BOUNDED
    assert result.property_id == "obligation:exclusive-lease"
    assert result.provider_id == "solver.z3"
    assert json.dumps(witness, sort_keys=True) == snapshot


@pytest.mark.parametrize("kwargs", [
    {"property_id": "property:conflicting"}, {"tool_id": "solver:conflicting"},
    {"authority": "theorem"}, {"authority": "attestation"}, {"authority": True},
    {"property_id": True}, {"tool_id": ""},
])
def test_api_compatibility_keywords_cannot_rebind_or_elevate(kwargs: Any) -> None:
    result = LogicVerificationAPI().explain_counterexample(_leaky_smt_witness(), **kwargs)
    assert result.status is VerificationStatus.INVALID
    assert result.authority is VerificationAuthority.NONE
    assert not result.result
