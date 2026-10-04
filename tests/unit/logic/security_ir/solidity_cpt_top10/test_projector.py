"""Conformance tests for Solidity CPT structural projection."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from ipfs_datasets_py.logic.security_ir.solidity_cpt_top10.projector import (
    DiagnosticCode,
    ExtractionMethod,
    FactKind,
    ProjectionError,
    ProjectorConfig,
    SolidityGraphProjector,
    StructuralFact,
    SuppliedEvidenceFact,
    UnitKind,
    canonical_source_row_cid,
    project_solidity_row,
)
from ipfs_datasets_py.logic.security_ir.solidity_cpt_top10.source_snapshot import (
    adapt_solidity_cpt_row,
)
from ipfs_datasets_py.logic.security_ir.solidity_cpt_top10.vocabulary import (
    SolidityAuthorityType,
)


SOURCE = """\
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;
import "./Ownable.sol";

contract Vault is Ownable {
    uint256 public balance;
    event Deposited(address indexed who, uint256 amount);
    error Insufficient();

    modifier onlyPositive(uint256 x) {
        require(x > 0);
        _;
    }

    function deposit() external payable onlyOwner {
        require(msg.sender != address(0));
        balance += msg.value;
        emit Deposited(msg.sender, msg.value);
    }

    function withdraw(uint256 amount) external onlyOwner {
        if (amount > balance) revert Insufficient();
        balance -= amount;
        (bool ok, ) = msg.sender.call{value: amount}("");
        require(ok);
    }
}
"""


def _row(text: str = SOURCE) -> dict[str, object]:
    return {
        "text": text,
        "source": "etherscan",
        "address": "0x" + "1" * 40,
        "name": "Vault",
        "compiler": "v0.8.24",
        "license": "MIT",
        "path": "contracts/Vault.sol",
        "n_chars": len(text),
    }


def _adapted(text: str = SOURCE, *, row_index: int = 7):
    return adapt_solidity_cpt_row(_row(text), row_index=row_index)


def _codes(result) -> set[DiagnosticCode]:
    return {item.code for item in result.diagnostics}


def test_projection_is_deterministic_and_provenance_bound() -> None:
    adapted = _adapted()
    projector = SolidityGraphProjector()
    first = projector.project_adapted(adapted)
    second = projector.project_adapted(adapted)

    assert first == second
    assert first.projection_id == second.projection_id
    assert first.to_dict() == second.to_dict()
    assert first.source_cid == canonical_source_row_cid(adapted.row)
    assert first.supported is True
    assert first.language == "solidity"
    assert first.path == "contracts/Vault.sol"
    assert "source_body" not in first.to_dict()
    assert "text" not in first.to_dict()

    for unit in first.code_units:
        assert unit.source_cids == (first.source_cid,)
        assert unit.config_cid == first.config_cid
        assert unit.language == "solidity"
        assert unit.payload["grants_execution_authority"] is False
        assert "source_code" not in unit.payload
        assert "body" not in unit.payload
        assert "text" not in unit.payload

    with pytest.raises(TypeError):
        first.code_units[0].payload["name"] = "changed"  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        first.path = "changed.sol"  # type: ignore[misc]


def test_observed_syntax_covers_declarations_and_effects() -> None:
    result = project_solidity_row(_adapted().row, _adapted().source_body)

    kinds = {item.unit_kind for item in result.code_units}
    assert UnitKind.SOURCE_UNIT.value in kinds
    assert UnitKind.CONTRACT.value in kinds
    assert UnitKind.FUNCTION.value in kinds
    assert UnitKind.MODIFIER.value in kinds
    assert UnitKind.VARIABLE.value in kinds
    assert UnitKind.EVENT.value in kinds
    assert UnitKind.ERROR.value in kinds
    assert UnitKind.CALL_SITE.value in kinds

    observed = result.facts_by_authority(
        SolidityAuthorityType.OBSERVED_SYNTAX
    )
    assert observed
    assert all(
        item.extraction_method is ExtractionMethod.DETERMINISTIC_SYNTAX
        and item.authority_type is SolidityAuthorityType.OBSERVED_SYNTAX
        and item.confidence == 1.0
        and item.to_dict()["authority"] == "non_authoritative"
        and item.to_dict()["grants_execution_authority"] is False
        for item in observed
    )
    predicates = {item.predicate for item in observed}
    assert any(item.startswith("declares:contract:") for item in predicates)
    assert any(item.startswith("inherits:") for item in predicates)
    assert any(item.startswith("imports:") for item in predicates)
    assert any(item.startswith("has_license:") for item in predicates)
    assert any(item.startswith("has_compiler:") for item in predicates)
    assert any(item.startswith("guards:") for item in predicates)
    assert any(item.startswith("calls:") for item in predicates)
    assert any(item.startswith("may_effect:") for item in predicates)


def test_inferred_candidates_are_separate_authority_type() -> None:
    result = project_solidity_row(_adapted().row, _adapted().source_body)
    inferred = result.facts_by_authority(
        SolidityAuthorityType.INFERRED_CANDIDATE
    )

    assert inferred
    assert all(
        item.authority_type is SolidityAuthorityType.INFERRED_CANDIDATE
        and item.extraction_method is ExtractionMethod.HEURISTIC_INFERENCE
        and item.kind is FactKind.SECURITY_CONCEPT
        and item.predicate.startswith("candidate_for:")
        for item in inferred
    )
    # Must remain distinct from observed syntax facts.
    observed_ids = {
        item.cid
        for item in result.facts_by_authority(
            SolidityAuthorityType.OBSERVED_SYNTAX
        )
    }
    assert observed_ids.isdisjoint({item.cid for item in inferred})


def test_reviewed_and_verified_facts_require_supply_and_stay_separate() -> None:
    adapted = _adapted()
    projector = SolidityGraphProjector()
    base = projector.project_adapted(adapted)
    unit_cid = next(
        item.cid
        for item in base.code_units
        if item.unit_kind == UnitKind.FUNCTION.value
    )

    with pytest.raises(ProjectionError, match="review_id"):
        SuppliedEvidenceFact(
            kind=FactKind.MITIGATION,
            predicate="enforce_access_control",
            authority_type=SolidityAuthorityType.REVIEWED_CLAIM,
            code_unit_cid=unit_cid,
        )
    with pytest.raises(ProjectionError, match="verification_id"):
        SuppliedEvidenceFact(
            kind=FactKind.PROOF_OBLIGATION,
            predicate="no_unauthorized_withdraw",
            authority_type=SolidityAuthorityType.VERIFIED_RESULT,
            code_unit_cid=unit_cid,
        )

    reviewed = SuppliedEvidenceFact(
        kind=FactKind.MITIGATION,
        predicate="enforce_access_control",
        authority_type=SolidityAuthorityType.REVIEWED_CLAIM,
        code_unit_cid=unit_cid,
        review_id="review:fixture-1",
    )
    verified = SuppliedEvidenceFact(
        kind=FactKind.PROOF_OBLIGATION,
        predicate="no_unauthorized_withdraw",
        authority_type=SolidityAuthorityType.VERIFIED_RESULT,
        code_unit_cid=unit_cid,
        verification_id="verify:fixture-1",
    )
    result = projector.project_adapted(
        adapted, supplied_facts=(reviewed, verified)
    )

    reviewed_facts = result.facts_by_authority(
        SolidityAuthorityType.REVIEWED_CLAIM
    )
    verified_facts = result.facts_by_authority(
        SolidityAuthorityType.VERIFIED_RESULT
    )
    assert len(reviewed_facts) == 1
    assert len(verified_facts) == 1
    assert reviewed_facts[0].review_id == "review:fixture-1"
    assert verified_facts[0].verification_id == "verify:fixture-1"
    assert reviewed_facts[0].authority_type is not (
        verified_facts[0].authority_type
    )
    # Projector never invents reviewed/verified without supply.
    assert not base.facts_by_authority(SolidityAuthorityType.REVIEWED_CLAIM)
    assert not base.facts_by_authority(SolidityAuthorityType.VERIFIED_RESULT)


def test_quality_score_never_becomes_security_label() -> None:
    adapted = _adapted()
    result = project_solidity_row(
        adapted.row,
        adapted.source_body,
        quality_score=0.95,
    )

    assert result.quality_score == 0.95
    assert result.quality_is_security_label is False
    assert DiagnosticCode.QUALITY_NOT_SECURITY in _codes(result)
    with pytest.raises(ProjectionError, match="security label"):
        from ipfs_datasets_py.logic.security_ir.solidity_cpt_top10.projector import (
            ProjectionResult,
        )

        ProjectionResult(
            source_cid=result.source_cid,
            config_cid=result.config_cid,
            language="solidity",
            path=result.path,
            parse_status=result.parse_status,
            code_units=result.code_units,
            structural_facts=result.structural_facts,
            diagnostics=(),
            quality_score=0.1,
            quality_is_security_label=True,
        )


def test_body_digest_mismatch_fails_closed() -> None:
    adapted = _adapted()
    with pytest.raises(ProjectionError, match="digest"):
        project_solidity_row(adapted.row, "contract Other {}")


def test_config_bounds_are_identity_affecting() -> None:
    adapted = _adapted()
    a = SolidityGraphProjector(ProjectorConfig(max_excerpt_chars=64))
    b = SolidityGraphProjector(ProjectorConfig(max_excerpt_chars=128))
    assert a.config_cid != b.config_cid
    first = a.project_adapted(adapted)
    second = b.project_adapted(adapted)
    assert first.config_cid != second.config_cid
    assert first.projection_id != second.projection_id


def test_disable_inferred_candidates() -> None:
    adapted = _adapted()
    result = SolidityGraphProjector(
        ProjectorConfig(emit_inferred_candidates=False)
    ).project_adapted(adapted)
    assert not result.facts_by_authority(
        SolidityAuthorityType.INFERRED_CANDIDATE
    )
