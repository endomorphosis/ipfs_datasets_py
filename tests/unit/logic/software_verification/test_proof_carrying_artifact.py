"""Independent proof-carrying artifact verification (LGCVF-090).

Required evidence: independent replay, forged/stale/omission rejection.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from ipfs_datasets_py.logic.ir_core.identity import canonical_identity
from ipfs_datasets_py.logic.software_verification.proof_carrying_artifact import (
    FORBIDDEN_PRODUCER_FLAGS,
    MANDATORY_LINEAGE_KINDS,
    OPTIONAL_LINEAGE_KINDS,
    PROOF_CARRYING_ARTIFACT_INTERFACE,
    ArtifactLineage,
    ProofCarryingArtifact,
    ProofCarryingArtifactAuthorityError,
    ProofCarryingArtifactError,
    ProofCarryingDisposition,
    ProofCarryingIssue,
    ProofCarryingRoots,
    rebuild_compact_checks,
    require_verified_artifact,
    verify_proof_carrying_artifact,
)


def _cid(tag: str) -> str:
    return canonical_identity(
        {"lgcvf-090": tag},
        domain="lgcvf-090-fixture",
        schema_version="v1",
    ).cid


def _lineage(**overrides: str) -> ArtifactLineage:
    refs = {kind: _cid(f"lineage:{kind}") for kind in MANDATORY_LINEAGE_KINDS}
    refs.update(overrides)
    return ArtifactLineage(**{f"{kind}_ref": refs[kind] for kind in MANDATORY_LINEAGE_KINDS})


def _lineage_with_extra(extra_refs: dict[str, str] | None = None, **overrides: str) -> ArtifactLineage:
    refs = {kind: _cid(f"lineage:{kind}") for kind in MANDATORY_LINEAGE_KINDS}
    refs.update(overrides)
    return ArtifactLineage(
        **{f"{kind}_ref": refs[kind] for kind in MANDATORY_LINEAGE_KINDS},
        extra_refs=extra_refs or {},
    )


def _roots(**overrides: str) -> ProofCarryingRoots:
    values = {
        "repository_id": "repository:fixture",
        "tree_id": _cid("tree:current"),
        "semantic_state_root": _cid("semantic-root:current"),
        "contract_root": _cid("contract-root:current"),
    }
    values.update(overrides)
    return ProofCarryingRoots(**values)


def test_build_round_trip_reconstructs_and_validates() -> None:
    lineage = _lineage()
    roots = _roots()
    artifact = ProofCarryingArtifact.build(lineage=lineage, roots=roots)
    assert artifact.artifact_cid == artifact.reconstructed_cid
    assert artifact.to_dict()["interface"] == PROOF_CARRYING_ARTIFACT_INTERFACE
    restored = ProofCarryingArtifact.from_dict(artifact.to_dict())
    assert restored.artifact_cid == artifact.artifact_cid
    verification = verify_proof_carrying_artifact(
        restored, expected_roots=roots, expected_lineage=lineage
    )
    assert verification.valid
    assert verification.disposition is ProofCarryingDisposition.VALIDATED
    assert verification.checks["content_identity_reconstructed"] is True
    assert verification.checks["compact_checks_reconstructed"] is True
    assert verification.checks["mandatory_lineage_present"] is True
    assert verification.to_dict()["completion_authority"] is False
    assert verification.to_dict()["production_authorized"] is False


def test_independent_replay_rebuilds_compact_checks() -> None:
    artifact = ProofCarryingArtifact.build(lineage=_lineage(), roots=_roots())
    verification = verify_proof_carrying_artifact(artifact.to_dict())
    assert verification.valid
    assert verification.replay_receipt_cid
    assert verification.replay_receipt_cid != artifact.artifact_cid
    second = verify_proof_carrying_artifact(artifact)
    assert second.replay_receipt_cid == verification.replay_receipt_cid
    rebuilt = rebuild_compact_checks(artifact.lineage, artifact.roots)
    assert dict(artifact.compact_checks) == rebuilt


def test_forged_artifact_cid_is_rejected() -> None:
    artifact = ProofCarryingArtifact.build(lineage=_lineage(), roots=_roots())
    forged = artifact.to_dict()
    forged["artifact_cid"] = _cid("forged-artifact")
    assert forged["artifact_cid"] != artifact.artifact_cid
    verification = verify_proof_carrying_artifact(forged)
    assert not verification.valid
    assert ProofCarryingIssue.FORGED_CID.value in verification.issues
    assert verification.checks["content_identity_reconstructed"] is False


def test_stale_roots_are_rejected() -> None:
    current = _roots()
    artifact = ProofCarryingArtifact.build(lineage=_lineage(), roots=current)
    stale = _roots(tree_id=_cid("tree:stale"))
    verification = verify_proof_carrying_artifact(artifact, expected_roots=stale)
    assert not verification.valid
    assert ProofCarryingIssue.STALE_ROOT.value in verification.issues
    assert verification.checks["roots_current"] is False


def test_missing_mandatory_lineage_is_rejected() -> None:
    payload = ProofCarryingArtifact.build(lineage=_lineage(), roots=_roots()).to_dict()
    payload["lineage"]["semantic_ref"] = ""
    verification = verify_proof_carrying_artifact(payload)
    assert not verification.valid
    assert ProofCarryingIssue.MISSING_MANDATORY_EVIDENCE.value in verification.issues


@pytest.mark.parametrize("flag", sorted(FORBIDDEN_PRODUCER_FLAGS))
def test_producer_flags_are_rejected(flag: str) -> None:
    with pytest.raises(ProofCarryingArtifactAuthorityError):
        ProofCarryingArtifact.build(
            lineage=_lineage(),
            roots=_roots(),
            metadata={flag: True},
        )
    payload = ProofCarryingArtifact.build(lineage=_lineage(), roots=_roots()).to_dict()
    payload["metadata"] = {flag: True}
    verification = verify_proof_carrying_artifact(payload)
    assert not verification.valid
    assert ProofCarryingIssue.PRODUCER_FLAG.value in verification.issues


def test_omitted_compact_check_is_rejected() -> None:
    artifact = ProofCarryingArtifact.build(lineage=_lineage(), roots=_roots())
    payload = artifact.to_dict()
    payload["compact_checks"]["lineage"] = _cid("forged-lineage-check")
    verification = verify_proof_carrying_artifact(payload)
    assert not verification.valid
    assert ProofCarryingIssue.COMPACT_CHECK_MISMATCH.value in verification.issues


def test_expected_lineage_mismatch_is_rejected() -> None:
    artifact = ProofCarryingArtifact.build(lineage=_lineage(), roots=_roots())
    other = _lineage(proof=_cid("lineage:proof:other"))
    verification = verify_proof_carrying_artifact(artifact, expected_lineage=other)
    assert not verification.valid
    assert ProofCarryingIssue.LINEAGE_MISMATCH.value in verification.issues


def test_mandatory_lineage_kinds_match_acceptance() -> None:
    assert MANDATORY_LINEAGE_KINDS == (
        "semantic",
        "contract",
        "abstract",
        "proof",
        "test",
        "static",
        "security",
        "policy",
        "authority",
    )
    artifact = ProofCarryingArtifact.build(lineage=_lineage(), roots=_roots())
    present = set(artifact.lineage.as_mapping())
    assert set(MANDATORY_LINEAGE_KINDS) <= present


def test_optional_lineage_kinds_round_trip_as_extra_refs() -> None:
    extra = {kind: _cid(f"extra:{kind}") for kind in OPTIONAL_LINEAGE_KINDS}
    lineage = _lineage_with_extra(extra)
    artifact = ProofCarryingArtifact.build(lineage=lineage, roots=_roots())
    restored = ProofCarryingArtifact.from_dict(artifact.to_dict())
    assert dict(restored.lineage.extra_refs) == extra
    result = verify_proof_carrying_artifact(
        restored, expected_roots=_roots(), expected_lineage=lineage
    )
    assert result.valid
    assert set(OPTIONAL_LINEAGE_KINDS) <= set(restored.lineage.as_mapping())


def test_extra_refs_cannot_override_mandatory_kinds() -> None:
    with pytest.raises(ProofCarryingArtifactError, match="cannot override"):
        ArtifactLineage(
            **{f"{kind}_ref": _cid(f"lineage:{kind}") for kind in MANDATORY_LINEAGE_KINDS},
            extra_refs={"semantic": _cid("override-semantic")},
        )


def test_artifact_is_immutable() -> None:
    artifact = ProofCarryingArtifact.build(lineage=_lineage(), roots=_roots())
    with pytest.raises(FrozenInstanceError):
        artifact.artifact_cid = _cid("mutated")  # type: ignore[misc]


def test_top_level_producer_flag_is_rejected() -> None:
    payload = ProofCarryingArtifact.build(lineage=_lineage(), roots=_roots()).to_dict()
    payload["passed"] = True
    verification = verify_proof_carrying_artifact(payload)
    assert not verification.valid
    assert ProofCarryingIssue.PRODUCER_FLAG.value in verification.issues
    assert verification.disposition is ProofCarryingDisposition.REJECTED


def test_nested_producer_flag_in_compact_checks_is_rejected() -> None:
    payload = ProofCarryingArtifact.build(lineage=_lineage(), roots=_roots()).to_dict()
    payload["compact_checks"]["verified"] = _cid("smuggled-flag")
    verification = verify_proof_carrying_artifact(payload)
    assert not verification.valid
    assert ProofCarryingIssue.PRODUCER_FLAG.value in verification.issues


def test_producer_flag_on_extra_refs_is_rejected() -> None:
    with pytest.raises(ProofCarryingArtifactAuthorityError):
        _lineage_with_extra({"passed": _cid("extra-passed")})


def test_omitted_compact_checks_are_rebuilt() -> None:
    artifact = ProofCarryingArtifact.build(lineage=_lineage(), roots=_roots())
    payload = artifact.to_dict()
    del payload["compact_checks"]
    verification = verify_proof_carrying_artifact(payload)
    assert verification.valid
    restored = ProofCarryingArtifact.from_dict(payload)
    assert dict(restored.compact_checks) == rebuild_compact_checks(
        restored.lineage, restored.roots
    )


@pytest.mark.parametrize("kind", MANDATORY_LINEAGE_KINDS)
def test_omitted_lineage_kind_is_missing_evidence(kind: str) -> None:
    payload = ProofCarryingArtifact.build(lineage=_lineage(), roots=_roots()).to_dict()
    del payload["lineage"][f"{kind}_ref"]
    verification = verify_proof_carrying_artifact(payload)
    assert not verification.valid
    assert ProofCarryingIssue.MISSING_MANDATORY_EVIDENCE.value in verification.issues


def test_omitted_lineage_mapping_is_missing_evidence() -> None:
    payload = ProofCarryingArtifact.build(lineage=_lineage(), roots=_roots()).to_dict()
    del payload["lineage"]
    verification = verify_proof_carrying_artifact(payload)
    assert not verification.valid
    assert ProofCarryingIssue.MISSING_MANDATORY_EVIDENCE.value in verification.issues


def test_omitted_roots_are_missing_evidence() -> None:
    payload = ProofCarryingArtifact.build(lineage=_lineage(), roots=_roots()).to_dict()
    del payload["roots"]
    verification = verify_proof_carrying_artifact(payload)
    assert not verification.valid
    assert ProofCarryingIssue.MISSING_MANDATORY_EVIDENCE.value in verification.issues


@pytest.mark.parametrize("field", ["tree_id", "semantic_state_root", "contract_root"])
def test_stale_individual_roots_are_rejected(field: str) -> None:
    current = _roots()
    artifact = ProofCarryingArtifact.build(lineage=_lineage(), roots=current)
    stale = _roots(**{field: _cid(f"stale-{field}")})
    verification = verify_proof_carrying_artifact(artifact, expected_roots=stale)
    assert not verification.valid
    assert ProofCarryingIssue.STALE_ROOT.value in verification.issues
    assert verification.checks["content_identity_reconstructed"] is True


def test_malformed_lineage_cid_is_rejected() -> None:
    payload = ProofCarryingArtifact.build(lineage=_lineage(), roots=_roots()).to_dict()
    payload["lineage"]["proof_ref"] = "not-a-cid"
    verification = verify_proof_carrying_artifact(payload)
    assert not verification.valid
    assert ProofCarryingIssue.MALFORMED_CID.value in verification.issues


def test_forged_compact_roots_check_is_rejected() -> None:
    artifact = ProofCarryingArtifact.build(lineage=_lineage(), roots=_roots())
    payload = artifact.to_dict()
    payload["compact_checks"]["roots"] = _cid("forged-roots-check")
    verification = verify_proof_carrying_artifact(payload)
    assert not verification.valid
    assert ProofCarryingIssue.COMPACT_CHECK_MISMATCH.value in verification.issues


def test_require_verified_artifact_returns_validated_result() -> None:
    artifact = ProofCarryingArtifact.build(lineage=_lineage(), roots=_roots())
    result = require_verified_artifact(artifact, expected_roots=_roots(), expected_lineage=_lineage())
    assert result.valid
    assert result.replay_receipt_cid


def test_require_verified_artifact_fails_closed_on_stale_root() -> None:
    artifact = ProofCarryingArtifact.build(lineage=_lineage(), roots=_roots())
    with pytest.raises(ProofCarryingArtifactError, match="independent verification"):
        require_verified_artifact(
            artifact,
            expected_roots=_roots(semantic_state_root=_cid("stale-semantic")),
        )


def test_verification_result_does_not_treat_producer_passed_as_authority() -> None:
    artifact = ProofCarryingArtifact.build(lineage=_lineage(), roots=_roots())
    result = verify_proof_carrying_artifact(artifact)
    encoded = result.to_dict()
    assert "passed" not in encoded
    assert encoded["valid"] is True
    assert "passed" not in encoded["checks"]
    assert encoded["completion_authority"] is False
    assert encoded["production_authorized"] is False


def test_from_dict_without_artifact_cid_reconstructs_identity() -> None:
    artifact = ProofCarryingArtifact.build(lineage=_lineage(), roots=_roots())
    payload = artifact.to_dict()
    del payload["artifact_cid"]
    restored = ProofCarryingArtifact.from_dict(payload)
    assert restored.artifact_cid == artifact.artifact_cid
    assert verify_proof_carrying_artifact(restored).valid


def test_construction_rejects_metadata_producer_flag() -> None:
    with pytest.raises(ProofCarryingArtifactAuthorityError, match="producer flags"):
        ProofCarryingArtifact.build(
            lineage=_lineage(),
            roots=_roots(),
            metadata={"producer_pass": True},
        )


def test_expected_roots_mapping_round_trip() -> None:
    roots = _roots()
    artifact = ProofCarryingArtifact.build(lineage=_lineage(), roots=roots)
    verification = verify_proof_carrying_artifact(artifact, expected_roots=roots.to_dict())
    assert verification.valid
    stale = roots.to_dict()
    stale["tree_id"] = _cid("tree:mapping-stale")
    rejected = verify_proof_carrying_artifact(artifact, expected_roots=stale)
    assert ProofCarryingIssue.STALE_ROOT.value in rejected.issues
