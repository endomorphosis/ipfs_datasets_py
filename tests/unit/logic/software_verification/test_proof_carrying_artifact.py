"""Independent proof-carrying artifact verification (LGCVF-090).

Required evidence: independent replay, forged/stale/omission rejection.
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.software_contracts.content import cid_for_structured
from ipfs_datasets_py.logic.software_verification.proof_carrying_artifact import (
    FORBIDDEN_PRODUCER_FLAGS,
    MANDATORY_LINEAGE_KINDS,
    PROOF_CARRYING_ARTIFACT_INTERFACE,
    ArtifactLineage,
    ProofCarryingArtifact,
    ProofCarryingArtifactAuthorityError,
    ProofCarryingDisposition,
    ProofCarryingIssue,
    ProofCarryingRoots,
    verify_proof_carrying_artifact,
)


def _cid(tag: str) -> str:
    return cid_for_structured({"lgcvf-090": tag})


def _lineage(**overrides: str) -> ArtifactLineage:
    refs = {kind: _cid(f"lineage:{kind}") for kind in MANDATORY_LINEAGE_KINDS}
    refs.update(overrides)
    return ArtifactLineage(**{f"{kind}_ref": refs[kind] for kind in MANDATORY_LINEAGE_KINDS})


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
