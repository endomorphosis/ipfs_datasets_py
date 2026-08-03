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
