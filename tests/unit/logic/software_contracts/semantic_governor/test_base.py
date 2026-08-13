"""Contract vectors for semantic-governor artifact base (SCG-006)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_bytes,
    cid_for_structured,
)
from ipfs_datasets_py.logic.software_contracts.semantic_governor.base import (
    GOVERNOR_ARTIFACT_HEADER_INTERFACE,
    GOVERNOR_ARTIFACT_HEADER_SCHEMA,
    AssumptionKind,
    ArtifactProvenance,
    AuthoritySource,
    ContextSufficiencyState,
    ExecutionMode,
    GeneratorIdentity,
    GovernorArtifactHeader,
    GovernorAssumption,
    GovernorTerminalStatus,
    MODEL_AUTHORITY_FORBIDDEN_KEYS,
    PRIVATE_FIELD_MARKERS,
    SemanticGovernorBaseError,
    context_sufficiency_states,
    governor_terminal_statuses,
    reject_private_and_model_authority,
    verify_header_identity,
)

jsonschema = pytest.importorskip("jsonschema")

SCHEMA_PATH = (
    Path(__file__).resolve().parents[5]
    / "ipfs_datasets_py"
    / "logic"
    / "software_contracts"
    / "semantic_governor"
    / "schemas"
    / "base.schema.json"
)


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _generator(**overrides: object) -> GeneratorIdentity:
    fields = {
        "generator_id": "context_coverage",
        "generator_version": "1.0.0",
        "interface_id": "build_context_coverage_manifest@1",
    }
    fields.update(overrides)
    return GeneratorIdentity(**fields)  # type: ignore[arg-type]


def _provenance(**overrides: object) -> ArtifactProvenance:
    fields = {
        "producer_id": "semantic_governor",
        "producer_version": "1",
        "execution_mode": ExecutionMode.LIVE,
        "authority_source": AuthoritySource.DETERMINISTIC,
        "input_cids": (_cid("input-a"), _cid("input-b")),
        "tool_ids": ("analyzer.v1",),
        "policy_cid": _cid("policy"),
        "notes": None,
    }
    fields.update(overrides)
    return ArtifactProvenance(**fields)  # type: ignore[arg-type]


def _assumption(**overrides: object) -> GovernorAssumption:
    fields = {
        "assumption_id": "capsule_fresh",
        "kind": AssumptionKind.FRESHNESS,
        "statement": "Capsule freshness assessed as fresh for target cone",
        "supporting_cids": (_cid("freshness"),),
    }
    fields.update(overrides)
    return GovernorAssumption(**fields)  # type: ignore[arg-type]


def _header(**overrides: object) -> GovernorArtifactHeader:
    fields = {
        "artifact_kind": "context_coverage_manifest",
        "repository_state_cid": _cid("repo-state"),
        "context_pack_cid": _cid("context-pack"),
        "verification_bundle_cid": _cid("verification-bundle"),
        "generator": _generator(),
        "provenance": _provenance(),
        "terminal_status": GovernorTerminalStatus.COMPLETE,
        "assumptions": (_assumption(),),
        "metadata": {"risk_class": "local_bug"},
    }
    fields.update(overrides)
    return GovernorArtifactHeader(**fields)  # type: ignore[arg-type]


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Closed vocabularies
# ---------------------------------------------------------------------------


def test_context_sufficiency_states_are_exactly_nine() -> None:
    expected = (
        "sufficient",
        "sufficient_with_caveats",
        "expansion_required",
        "frontier_escalation_required",
        "human_review_required",
        "inconclusive",
        "invalid",
        "stale",
        "evaluation_failed",
    )
    assert context_sufficiency_states() == expected
    assert len(ContextSufficiencyState) == 9
    for value in expected:
        assert ContextSufficiencyState(value).value == value


def test_governor_terminal_statuses_are_closed() -> None:
    values = governor_terminal_statuses()
    assert "complete" in values
    assert "simulated" in values
    assert "invalid" in values
    assert len(set(values)) == len(values)
    with pytest.raises(ValueError):
        GovernorTerminalStatus("accepted_by_model")


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


def test_key_order_and_assumption_order_do_not_change_identity() -> None:
    a = _assumption(assumption_id="a_first", statement="first")
    b = _assumption(assumption_id="b_second", statement="second")
    left = _header(assumptions=(b, a), metadata={"z": 1, "a": 2})
    right = _header(assumptions=(a, b), metadata={"a": 2, "z": 1})
    assert left.header_cid == right.header_cid
    assert [item.assumption_id for item in left.assumptions] == ["a_first", "b_second"]


def test_input_cid_order_independent_for_provenance() -> None:
    left = _provenance(input_cids=(_cid("z"), _cid("a")))
    right = _provenance(input_cids=(_cid("a"), _cid("z")))
    assert left.provenance_cid == right.provenance_cid
    assert list(left.input_cids) == sorted(left.input_cids)


def test_round_trip_seals_and_recomputes() -> None:
    header = _header()
    restored = GovernorArtifactHeader.from_dict(header.to_dict())
    assert restored == header
    assert restored.header_cid == header.header_cid
    assert restored.generator.generator_cid == header.generator.generator_cid
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
    with pytest.raises(SemanticGovernorBaseError, match="fields must be exactly"):
        GovernorArtifactHeader.from_dict(payload)


def test_unknown_terminal_status_fails_closed() -> None:
    with pytest.raises(SemanticGovernorBaseError, match="unsupported value"):
        _header(terminal_status="model_accepted")


def test_unknown_sufficiency_state_fails_closed() -> None:
    with pytest.raises(ValueError):
        ContextSufficiencyState("probably_enough")


def test_floats_fail_closed_in_metadata() -> None:
    with pytest.raises(SemanticGovernorBaseError, match="DAG-JSON|float"):
        _header(metadata={"score": 0.5})


def test_forged_header_cid_fails_closed() -> None:
    payload = _header().to_dict()
    payload["header_cid"] = _cid("forged-header")
    with pytest.raises(SemanticGovernorBaseError, match="does not verify"):
        GovernorArtifactHeader.from_dict(payload)


def test_forged_nested_cids_fail_closed() -> None:
    payload = _header().to_dict()
    payload["generator"]["generator_cid"] = _cid("forged-generator")
    with pytest.raises(SemanticGovernorBaseError, match="does not verify"):
        GovernorArtifactHeader.from_dict(payload)

    payload = _header().to_dict()
    payload["provenance"]["provenance_cid"] = _cid("forged-provenance")
    with pytest.raises(SemanticGovernorBaseError, match="does not verify"):
        GovernorArtifactHeader.from_dict(payload)

    payload = _header().to_dict()
    payload["assumptions"][0]["assumption_cid"] = _cid("forged-assumption")
    with pytest.raises(SemanticGovernorBaseError, match="does not verify"):
        GovernorArtifactHeader.from_dict(payload)


def test_invalid_cid_shape_fails_closed() -> None:
    with pytest.raises(SemanticGovernorBaseError, match="valid CID"):
        _header(repository_state_cid="cidv1-sha256-not-a-real-cid")
    with pytest.raises(SemanticGovernorBaseError, match="valid CID"):
        _header(context_pack_cid="not-a-cid")


def test_unsupported_schema_and_interface_fail_closed() -> None:
    payload = _header().to_dict()
    payload["schema"] = "ipfs-datasets.software-contracts.semantic-governor-artifact-header@2"
    with pytest.raises(SemanticGovernorBaseError, match="unsupported"):
        GovernorArtifactHeader.from_dict(payload)

    payload = _header().to_dict()
    payload["interface_id"] = "GovernorArtifactHeader@2"
    with pytest.raises(SemanticGovernorBaseError, match="unsupported"):
        GovernorArtifactHeader.from_dict(payload)


# ---------------------------------------------------------------------------
# Fail-closed: private data and model-written authority
# ---------------------------------------------------------------------------


def test_private_data_fields_fail_closed() -> None:
    assert "raw_source" in PRIVATE_FIELD_MARKERS
    assert "secret" in PRIVATE_FIELD_MARKERS
    with pytest.raises(SemanticGovernorBaseError, match="private data"):
        _header(metadata={"raw_source": "def secret():\n    pass\n"})
    with pytest.raises(SemanticGovernorBaseError, match="private data"):
        _header(metadata={"nested": {"api_key": "sk-test"}})
    with pytest.raises(SemanticGovernorBaseError, match="private data"):
        reject_private_and_model_authority({"password": "x"})


def test_model_written_authority_fails_closed() -> None:
    assert "model_written_authority" in MODEL_AUTHORITY_FORBIDDEN_KEYS
    with pytest.raises(SemanticGovernorBaseError, match="model-written authority"):
        _header(metadata={"model_authority": True})
    with pytest.raises(SemanticGovernorBaseError, match="model-written authority"):
        _header(metadata={"promotion_authority": "llm"})
    with pytest.raises(SemanticGovernorBaseError, match="model-written authority"):
        _provenance(authority_source="model")
    with pytest.raises(SemanticGovernorBaseError, match="model-written authority"):
        _provenance(authority_source="llm")


def test_simulated_provenance_cannot_claim_complete() -> None:
    with pytest.raises(SemanticGovernorBaseError, match="simulated provenance"):
        _header(
            provenance=_provenance(execution_mode=ExecutionMode.SIMULATED),
            terminal_status=GovernorTerminalStatus.COMPLETE,
        )
    sealed = _header(
        provenance=_provenance(execution_mode=ExecutionMode.SIMULATED),
        terminal_status=GovernorTerminalStatus.SIMULATED,
    )
    assert sealed.terminal_status == GovernorTerminalStatus.SIMULATED.value


def test_duplicate_assumptions_fail_closed() -> None:
    a = _assumption(assumption_id="dup")
    b = _assumption(assumption_id="dup", statement="other")
    with pytest.raises(SemanticGovernorBaseError, match="duplicate"):
        _header(assumptions=(a, b))


def test_generator_requires_versioned_interface() -> None:
    with pytest.raises(SemanticGovernorBaseError, match="versioned interface"):
        _generator(interface_id="no_version")


# ---------------------------------------------------------------------------
# JSON Schema packaging
# ---------------------------------------------------------------------------


def test_base_schema_is_valid_draft_2020_12_and_accepts_sealed_header() -> None:
    schema = _load_schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    validator = jsonschema.Draft202012Validator(schema)
    header = _header()
    validator.validate(header.to_dict())
    validator.validate(header.generator.to_dict())
    validator.validate(header.provenance.to_dict())
    validator.validate(header.assumptions[0].to_dict())


def test_base_schema_rejects_unknown_fields_and_floats() -> None:
    schema = _load_schema()
    validator = jsonschema.Draft202012Validator(schema)
    bad = _header().to_dict()
    bad["extra"] = True
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(bad)
    # Floats are excluded by strictValue oneOf (no number type).
    floaty = _header().to_dict()
    floaty["metadata"] = {"score": 1.25}
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(floaty)


def test_base_schema_exposes_closed_enums() -> None:
    schema = _load_schema()
    sufficiency = schema["$defs"]["contextSufficiencyState"]["enum"]
    terminal = schema["$defs"]["governorTerminalStatus"]["enum"]
    assert sufficiency == list(context_sufficiency_states())
    assert terminal == list(governor_terminal_statuses())
    assert schema["$defs"]["governorArtifactHeader"]["properties"]["interface_id"][
        "const"
    ] == GOVERNOR_ARTIFACT_HEADER_INTERFACE
    assert schema["$defs"]["governorArtifactHeader"]["properties"]["schema"][
        "const"
    ] == GOVERNOR_ARTIFACT_HEADER_SCHEMA


def test_schema_file_is_packaged_beside_module() -> None:
    assert SCHEMA_PATH.is_file()
    assert SCHEMA_PATH.name == "base.schema.json"
