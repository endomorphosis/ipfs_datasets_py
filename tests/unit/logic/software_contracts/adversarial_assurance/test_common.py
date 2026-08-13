"""Contract vectors for adversarial-assurance common headers (AAE-007)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_bytes,
    cid_for_structured,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.common import (
    ASSURANCE_ARTIFACT_HEADER_INTERFACE,
    ASSURANCE_ARTIFACT_HEADER_SCHEMA,
    ArtifactProvenance,
    AssuranceArtifactHeader,
    AssuranceBaseError,
    AssuranceTerminalStatus,
    AuthoritySource,
    ExecutionMode,
    GeneratorIdentity,
    HOST_FALLBACK_MARKERS,
    MODEL_AUTHORITY_FORBIDDEN_KEYS,
    PRIVATE_FIELD_MARKERS,
    VersionBinding,
    assurance_terminal_statuses,
    authority_sources,
    execution_modes,
    reject_private_model_authority_and_host_fallbacks,
    verify_header_identity,
)


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _generator(**overrides: object) -> GeneratorIdentity:
    fields = {
        "generator_id": "mutation_campaign",
        "generator_version": "1.0.0",
        "interface_id": "generate_mutation_candidates@1",
    }
    fields.update(overrides)
    return GeneratorIdentity(**fields)  # type: ignore[arg-type]


def _versions(**overrides: object) -> VersionBinding:
    fields = {
        "operator_id": "control_flow_invert",
        "operator_version": "1",
        "campaign_policy_id": "default_campaign",
        "campaign_policy_version": "1.0.0",
        "generator": _generator(),
    }
    fields.update(overrides)
    return VersionBinding(**fields)  # type: ignore[arg-type]


def _provenance(**overrides: object) -> ArtifactProvenance:
    fields = {
        "producer_id": "adversarial_assurance",
        "producer_version": "1",
        "execution_mode": ExecutionMode.LIVE,
        "authority_source": AuthoritySource.DETERMINISTIC,
        "input_cids": (_cid("input-a"), _cid("input-b")),
        "tool_ids": ("mutator.v1",),
        "policy_cid": _cid("policy"),
        "notes": None,
    }
    fields.update(overrides)
    return ArtifactProvenance(**fields)  # type: ignore[arg-type]


def _header(**overrides: object) -> AssuranceArtifactHeader:
    fields = {
        "artifact_kind": "mutation_campaign_plan",
        "repository_id": "repository:sha256:test-repo-identity",
        "repository_state_cid": _cid("repo-state"),
        "target_symbol_ids": ("mod.fn", "mod.Other"),
        "target_artifact_cids": (_cid("artifact-a"),),
        "capsule_cids": (_cid("capsule-a"),),
        "proof_unit_cids": (_cid("proof-unit-a"),),
        "environment_cid": _cid("environment"),
        "dependency_lock_cid": _cid("dependency-lock"),
        "versions": _versions(),
        "provenance": _provenance(),
        "terminal_status": AssuranceTerminalStatus.COMPLETE,
        "receipt_cids": (_cid("receipt-a"),),
        "proof_cids": (_cid("proof-a"),),
        "metadata": {"risk_class": "local_bug"},
    }
    fields.update(overrides)
    return AssuranceArtifactHeader(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Closed vocabularies
# ---------------------------------------------------------------------------


def test_assurance_terminal_statuses_are_closed() -> None:
    expected = (
        "complete",
        "rejected",
        "invalid",
        "stale",
        "inconclusive",
        "evaluation_failed",
        "human_review_required",
        "unavailable",
        "cancelled",
        "simulated",
    )
    assert assurance_terminal_statuses() == expected
    assert len(AssuranceTerminalStatus) == 10
    for value in expected:
        assert AssuranceTerminalStatus(value).value == value
    with pytest.raises(ValueError):
        AssuranceTerminalStatus("accepted_by_model")


def test_execution_modes_and_authority_sources_are_closed() -> None:
    assert execution_modes() == ("live", "simulated", "replay")
    assert authority_sources() == (
        "deterministic",
        "observed",
        "human",
        "policy",
        "receipt",
        "schema",
    )
    with pytest.raises(ValueError):
        ExecutionMode("guessed")
    with pytest.raises(ValueError):
        AuthoritySource("llm")


# ---------------------------------------------------------------------------
# Required field bindings
# ---------------------------------------------------------------------------


def test_header_binds_all_required_identity_fields() -> None:
    header = _header()
    payload = header.to_dict()
    required = {
        "repository_id",
        "repository_state_cid",
        "target_symbol_ids",
        "target_artifact_cids",
        "capsule_cids",
        "proof_unit_cids",
        "environment_cid",
        "dependency_lock_cid",
        "versions",
        "terminal_status",
        "provenance",
        "header_cid",
        "receipt_cids",
        "proof_cids",
        "schema",
        "interface_id",
        "artifact_kind",
        "metadata",
    }
    assert required.issubset(payload.keys())
    assert payload["interface_id"] == ASSURANCE_ARTIFACT_HEADER_INTERFACE
    assert payload["schema"] == ASSURANCE_ARTIFACT_HEADER_SCHEMA
    assert payload["versions"]["operator_version"] == "1"
    assert payload["versions"]["campaign_policy_version"] == "1.0.0"
    assert payload["versions"]["generator"]["generator_version"] == "1.0.0"
    assert payload["provenance"]["authority_source"] == "deterministic"
    assert payload["header_cid"] == header.header_cid


def test_missing_required_field_fails_closed() -> None:
    payload = _header().to_dict()
    del payload["environment_cid"]
    with pytest.raises(AssuranceBaseError, match="fields must be exactly"):
        AssuranceArtifactHeader.from_dict(payload)

    payload = _header().to_dict()
    del payload["dependency_lock_cid"]
    with pytest.raises(AssuranceBaseError, match="fields must be exactly"):
        AssuranceArtifactHeader.from_dict(payload)

    payload = _header().to_dict()
    del payload["repository_id"]
    with pytest.raises(AssuranceBaseError, match="fields must be exactly"):
        AssuranceArtifactHeader.from_dict(payload)


# ---------------------------------------------------------------------------
# Deterministic identity
# ---------------------------------------------------------------------------


def test_identical_inputs_yield_identical_cids() -> None:
    first = _header()
    second = _header()
    assert first.header_cid == second.header_cid
    assert first.to_dict() == second.to_dict()
    assert verify_header_identity(first) == first.header_cid
    assert verify_header_identity(first.to_dict()) == first.header_cid


def test_list_and_metadata_order_do_not_change_identity() -> None:
    left = _header(
        target_symbol_ids=("z_sym", "a_sym"),
        capsule_cids=(_cid("c2"), _cid("c1")),
        metadata={"z": 1, "a": 2},
    )
    right = _header(
        target_symbol_ids=("a_sym", "z_sym"),
        capsule_cids=(_cid("c1"), _cid("c2")),
        metadata={"a": 2, "z": 1},
    )
    assert left.header_cid == right.header_cid
    assert list(left.target_symbol_ids) == sorted(left.target_symbol_ids)
    assert list(left.capsule_cids) == sorted(left.capsule_cids)


def test_input_cid_order_independent_for_provenance() -> None:
    left = _provenance(input_cids=(_cid("z"), _cid("a")))
    right = _provenance(input_cids=(_cid("a"), _cid("z")))
    assert left.provenance_cid == right.provenance_cid
    assert list(left.input_cids) == sorted(left.input_cids)


def test_round_trip_seals_and_recomputes() -> None:
    header = _header()
    restored = AssuranceArtifactHeader.from_dict(header.to_dict())
    assert restored == header
    assert restored.header_cid == header.header_cid
    assert restored.versions.version_binding_cid == header.versions.version_binding_cid
    assert (
        restored.versions.generator.generator_cid
        == header.versions.generator.generator_cid
    )
    assert restored.provenance.provenance_cid == header.provenance.provenance_cid


def test_identity_payload_matches_content_profile() -> None:
    header = _header()
    assert cid_for_structured(header.identity_payload()) == header.header_cid


# ---------------------------------------------------------------------------
# Fail-closed: unknown fields / statuses / floats / forged CIDs
# ---------------------------------------------------------------------------


def test_unknown_header_fields_fail_closed() -> None:
    payload = _header().to_dict()
    payload["extra"] = "nope"
    with pytest.raises(AssuranceBaseError, match="fields must be exactly"):
        AssuranceArtifactHeader.from_dict(payload)


def test_unknown_nested_fields_fail_closed() -> None:
    payload = _header().to_dict()
    payload["provenance"]["extra"] = True
    with pytest.raises(AssuranceBaseError, match="fields must be exactly"):
        AssuranceArtifactHeader.from_dict(payload)

    payload = _header().to_dict()
    payload["versions"]["extra"] = True
    with pytest.raises(AssuranceBaseError, match="fields must be exactly"):
        AssuranceArtifactHeader.from_dict(payload)

    payload = _header().to_dict()
    payload["versions"]["generator"]["extra"] = True
    with pytest.raises(AssuranceBaseError, match="fields must be exactly"):
        AssuranceArtifactHeader.from_dict(payload)


def test_unknown_terminal_status_fails_closed() -> None:
    with pytest.raises(AssuranceBaseError, match="unsupported value"):
        _header(terminal_status="model_accepted")


def test_floats_fail_closed_in_metadata() -> None:
    with pytest.raises(AssuranceBaseError, match="DAG-JSON|float"):
        _header(metadata={"score": 0.5})


def test_host_objects_fail_closed_in_metadata() -> None:
    with pytest.raises(AssuranceBaseError, match="DAG-JSON|host"):
        _header(metadata={"path": Path("/tmp/secret")})
    with pytest.raises(AssuranceBaseError, match="DAG-JSON|host"):
        _header(metadata={"payload": b"bytes-not-allowed"})


def test_host_fallback_fields_fail_closed() -> None:
    assert "host_fallback" in HOST_FALLBACK_MARKERS
    assert "local_path" in HOST_FALLBACK_MARKERS
    with pytest.raises(AssuranceBaseError, match="host fallback"):
        _header(metadata={"host_fallback": "/var/tmp"})
    with pytest.raises(AssuranceBaseError, match="host fallback"):
        _header(metadata={"nested": {"local_path": "./x"}})
    with pytest.raises(AssuranceBaseError, match="host fallback"):
        reject_private_model_authority_and_host_fallbacks({"cwd": "/home/user"})


def test_forged_header_cid_fails_closed() -> None:
    payload = _header().to_dict()
    payload["header_cid"] = _cid("forged-header")
    with pytest.raises(AssuranceBaseError, match="identity mismatch"):
        AssuranceArtifactHeader.from_dict(payload)


def test_forged_nested_cids_fail_closed() -> None:
    payload = _header().to_dict()
    payload["versions"]["generator"]["generator_cid"] = _cid("forged-generator")
    with pytest.raises(AssuranceBaseError, match="identity mismatch"):
        AssuranceArtifactHeader.from_dict(payload)

    payload = _header().to_dict()
    payload["versions"]["version_binding_cid"] = _cid("forged-versions")
    with pytest.raises(AssuranceBaseError, match="identity mismatch"):
        AssuranceArtifactHeader.from_dict(payload)

    payload = _header().to_dict()
    payload["provenance"]["provenance_cid"] = _cid("forged-provenance")
    with pytest.raises(AssuranceBaseError, match="identity mismatch"):
        AssuranceArtifactHeader.from_dict(payload)


def test_invalid_cid_shape_fails_closed() -> None:
    with pytest.raises(AssuranceBaseError, match="valid CID"):
        _header(repository_state_cid="cidv1-sha256-not-a-real-cid")
    with pytest.raises(AssuranceBaseError, match="valid CID"):
        _header(environment_cid="not-a-cid")
    with pytest.raises(AssuranceBaseError, match="valid CID"):
        _header(dependency_lock_cid="still-not-a-cid")


def test_unsupported_schema_and_interface_fail_closed() -> None:
    payload = _header().to_dict()
    payload["schema"] = (
        "ipfs-datasets.software-contracts.adversarial-assurance-artifact-header@2"
    )
    with pytest.raises(AssuranceBaseError, match="unsupported"):
        AssuranceArtifactHeader.from_dict(payload)

    payload = _header().to_dict()
    payload["interface_id"] = "AssuranceArtifactHeader@2"
    with pytest.raises(AssuranceBaseError, match="unsupported"):
        AssuranceArtifactHeader.from_dict(payload)


# ---------------------------------------------------------------------------
# Fail-closed: private data and model-written authority
# ---------------------------------------------------------------------------


def test_private_data_fields_fail_closed() -> None:
    assert "raw_source" in PRIVATE_FIELD_MARKERS
    assert "secret" in PRIVATE_FIELD_MARKERS
    with pytest.raises(AssuranceBaseError, match="private data"):
        _header(metadata={"raw_source": "def secret():\n    pass\n"})
    with pytest.raises(AssuranceBaseError, match="private data"):
        _header(metadata={"nested": {"api_key": "sk-test"}})
    with pytest.raises(AssuranceBaseError, match="private data"):
        reject_private_model_authority_and_host_fallbacks({"password": "x"})


def test_model_written_authority_fails_closed() -> None:
    assert "model_written_authority" in MODEL_AUTHORITY_FORBIDDEN_KEYS
    with pytest.raises(AssuranceBaseError, match="model-written authority"):
        _header(metadata={"model_authority": True})
    with pytest.raises(AssuranceBaseError, match="model-written authority"):
        _header(metadata={"promotion_authority": "llm"})
    with pytest.raises(AssuranceBaseError, match="model-written authority"):
        _provenance(authority_source="model")
    with pytest.raises(AssuranceBaseError, match="model-written authority"):
        _provenance(authority_source="llm")


def test_simulated_provenance_cannot_claim_complete() -> None:
    with pytest.raises(AssuranceBaseError, match="simulated provenance"):
        _header(
            provenance=_provenance(execution_mode=ExecutionMode.SIMULATED),
            terminal_status=AssuranceTerminalStatus.COMPLETE,
        )
    sealed = _header(
        provenance=_provenance(execution_mode=ExecutionMode.SIMULATED),
        terminal_status=AssuranceTerminalStatus.SIMULATED,
    )
    assert sealed.terminal_status == AssuranceTerminalStatus.SIMULATED.value


def test_duplicate_list_entries_fail_closed() -> None:
    with pytest.raises(AssuranceBaseError, match="duplicate"):
        _header(target_symbol_ids=("same", "same"))
    with pytest.raises(AssuranceBaseError, match="duplicate"):
        _header(capsule_cids=(_cid("x"), _cid("x")))
    with pytest.raises(AssuranceBaseError, match="duplicate"):
        _provenance(input_cids=(_cid("d"), _cid("d")))


def test_generator_requires_versioned_interface() -> None:
    with pytest.raises(AssuranceBaseError, match="versioned interface"):
        _generator(interface_id="no_version")


def test_empty_repository_id_and_kind_fail_closed() -> None:
    with pytest.raises(AssuranceBaseError, match="nonempty string"):
        _header(repository_id="")
    with pytest.raises(AssuranceBaseError, match="nonempty string|snake-case"):
        _header(artifact_kind="")
    with pytest.raises(AssuranceBaseError, match="snake-case|kind"):
        _header(artifact_kind="NotValid")


def test_verify_header_identity_rejects_non_header() -> None:
    with pytest.raises(AssuranceBaseError, match="header must be"):
        verify_header_identity("not-a-header")  # type: ignore[arg-type]


def test_empty_target_and_reference_lists_are_admitted() -> None:
    header = _header(
        target_symbol_ids=(),
        target_artifact_cids=(),
        capsule_cids=(),
        proof_unit_cids=(),
        receipt_cids=(),
        proof_cids=(),
    )
    restored = AssuranceArtifactHeader.from_dict(header.to_dict())
    assert restored.header_cid == header.header_cid
    assert restored.target_symbol_ids == ()
    assert restored.receipt_cids == ()
