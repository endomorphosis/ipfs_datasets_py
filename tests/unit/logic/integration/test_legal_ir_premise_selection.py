"""Contract-aware LegalIR premise ranking is deterministic and source-free."""

from __future__ import annotations

import json

from ipfs_datasets_py.logic.integration.reasoning.hammer import HammerGoal, HammerPremise
from ipfs_datasets_py.logic.integration.reasoning.legal_ir_premise_selection import (
    LEGAL_IR_PREMISE_SELECTION_SCHEMA_VERSION,
    LegalIRPremiseKind,
    LegalIRPremiseSelector,
    rank_legal_ir_premises,
)
from ipfs_datasets_py.logic.integration.reasoning.legal_ir_premises import (
    premises_from_theorem_registry,
)


def _goal(**metadata: object) -> HammerGoal:
    return HammerGoal(
        name="contract-field-goal",
        statement="This statement is deliberately not a ranking feature.",
        metadata={
            "contract_id": "legal-ir-view/deontic/v1",
            "legal_ir_view": "deontic.ir",
            "obligation_family": "deontic_required_fields",
            "required_field": "actor",
            "sample_id": "sample-1",
            **metadata,
        },
    )


def _premise(name: str, **metadata: object) -> HammerPremise:
    return HammerPremise(
        name=name,
        statement=f"formal premise {name}",
        metadata=dict(metadata),
    )


def test_ranks_contract_family_view_and_field_overlap_ahead_of_unrelated_fact() -> None:
    selector = LegalIRPremiseSelector()
    matching = _premise(
        "matching",
        premise_kind="compiler_fact",
        obligation_family="deontic_required_fields",
        legal_ir_view="deontic",  # canonical alias of deontic.ir
        contract_id="legal-ir-view/deontic/v1",
        contract_fields=["actor", "action"],
        sample_id="sample-1",
    )
    unrelated = _premise(
        "unrelated",
        premise_kind="compiler_fact",
        obligation_family="cec_lifecycle_transition",
        legal_ir_view="CEC.native",
        contract_fields=["events"],
        sample_id="other-sample",
    )

    ranked = selector.rank(_goal(), [unrelated, matching])

    assert [item.premise.name for item in ranked] == ["matching", "unrelated"]
    receipt = ranked[0].ranking
    assert receipt.schema_version == LEGAL_IR_PREMISE_SELECTION_SCHEMA_VERSION
    assert receipt.matched_obligation_families == ("deontic_required_fields",)
    assert receipt.matched_contract_fields == ("actor",)
    assert receipt.components["target_view"] > 0
    assert receipt.components["contract_id"] > 0


def test_verified_failure_and_provenance_hash_are_strong_structural_features() -> None:
    provenance_hash = "a" * 64
    goal = _goal(
        verified_failure_reason="preserved_value_mismatch",
        provenance_hash=provenance_hash,
    )
    matching = _premise(
        "failure-repair",
        premise_kind="theorem_template",
        failure_reason="preserved_value_mismatch",
        provenance_hash=provenance_hash,
    )
    other = _premise(
        "generic-template",
        premise_kind="theorem_template",
        failure_reason="missing_required_field",
        provenance_hash="b" * 64,
    )

    ranked = LegalIRPremiseSelector().rank(goal, [other, matching])
    receipt = ranked[0].ranking

    assert ranked[0].premise is matching
    assert receipt.components["verified_failure_reason"] == 2.25
    assert receipt.components["provenance_hash"] == 1.75
    assert receipt.matched_failure_reasons == ("preserved_value_mismatch",)
    # Receipts expose a digest of the identifier, not the provenance identifier.
    assert provenance_hash not in json.dumps(receipt.to_dict())


def test_contract_telemetry_supplies_verified_failure_reasons_and_fields() -> None:
    telemetry = {
        "decompiler_preservation_failures": [
            {
                "field_path": "operator",
                "formula_id": "formula-1",
                "reason": "preserved_value_mismatch",
                "source_value_sha256": "c" * 64,
            }
        ],
        "missing_required_fields": {"decompiler": ["operator"]},
    }
    selector = LegalIRPremiseSelector(contract_telemetry=telemetry)
    matching = _premise(
        "decompiler-repair",
        premise_kind="sample_local_assumption",
        contract_fields=["operator"],
        failure_reason="preserved_value_mismatch",
    )
    generic = _premise("generic", premise_kind="sample_local_assumption")

    ranked = selector.rank(
        _goal(legal_ir_view="modal.decompiler", formula_id="formula-1"),
        [generic, matching],
    )

    assert ranked[0].premise is matching
    assert ranked[0].ranking.components["verified_failure_reason"] == 2.25
    assert "operator" in ranked[0].ranking.matched_contract_fields


def test_verified_leanstral_registry_entry_gets_trust_bonus() -> None:
    common = {
        "theorem_id": "theorem-1",
        "statement": "LegalIR theorem statement",
        "legal_ir_view": "deontic.ir",
        "logic_family": "deontic",
        "evidence_hash": "d" * 64,
    }
    verified = premises_from_theorem_registry(
        {
            "registry_hash": "e" * 64,
            "verified_theorem_ids": ["theorem-1"],
            "theorems": [{**common, "theorem_name": "verified"}],
        }
    )[0]
    unverified = premises_from_theorem_registry(
        {
            "registry_hash": "e" * 64,
            "theorems": [{**common, "theorem_name": "unverified"}],
        }
    )[0]

    ranked = LegalIRPremiseSelector().rank(
        _goal(logic_family="deontic", evidence_hash="d" * 64),
        [unverified, verified],
    )

    assert verified.metadata["premise_kind"] == "verified_leanstral_theorem"
    assert ranked[0].premise is verified
    assert ranked[0].ranking.premise_kind == LegalIRPremiseKind.VERIFIED_LEANSTRAL_THEOREM.value
    assert ranked[0].ranking.components["verified_registry"] == 1.0


def test_copied_source_spans_and_goal_wording_do_not_change_scores() -> None:
    copied = "The agency shall disclose a record unless a statutory exception applies."
    first = HammerPremise(
        name="first",
        statement=copied,
        metadata={
            "premise_kind": "compiler_fact",
            "legal_ir_view": "deontic.ir",
            "source_span": copied,
            "source_text": copied,
        },
    )
    second = HammerPremise(
        name="second",
        statement="opaque compiler proposition",
        metadata={
            "premise_kind": "compiler_fact",
            "legal_ir_view": "deontic.ir",
            "source_span": "completely different copied source",
            "source_text": "different text",
        },
    )
    selector = LegalIRPremiseSelector()

    initial = selector.rank(_goal(source_text=copied), [first, second])
    rewritten = selector.rank(
        HammerGoal(
            statement=copied,
            metadata={**_goal().metadata, "source_text": "other raw source"},
        ),
        [first, second],
    )
    initial_scores = {item.premise.name: item.score for item in initial}
    rewritten_scores = {item.premise.name: item.score for item in rewritten}

    assert initial_scores["first"] == initial_scores["second"]
    assert initial_scores == rewritten_scores
    serialized = json.dumps([item.to_dict() for item in initial], sort_keys=True)
    assert copied not in serialized
    assert "completely different copied source" not in serialized


def test_selection_is_order_independent_and_uses_stable_name_tiebreak() -> None:
    premises = [
        _premise("zeta", premise_kind="theorem_template"),
        _premise("alpha", premise_kind="theorem_template"),
        _premise("middle", premise_kind="theorem_template"),
    ]

    first = rank_legal_ir_premises(_goal(), premises, max_premises=2)
    second = rank_legal_ir_premises(_goal(), list(reversed(premises)), max_premises=2)

    assert [item.name for item in first.selected] == ["alpha", "middle"]
    assert [item.name for item in second.selected] == ["alpha", "middle"]
    assert first.scores == second.scores
    assert first.considered_count == 3
    assert first.max_premises == 2


def test_all_required_premise_kinds_receive_a_deterministic_score() -> None:
    premises = [
        _premise("compiler", premise_kind="compiler_fact"),
        _premise("template", premise_kind="theorem_template"),
        _premise("local", premise_kind="sample_local_assumption"),
        _premise(
            "registry",
            premise_kind="leanstral_theorem",
            verification_status="verified",
        ),
    ]

    ranked = LegalIRPremiseSelector().rank(_goal(), premises)
    kinds = {item.ranking.premise_kind for item in ranked}

    assert kinds == {
        LegalIRPremiseKind.COMPILER_FACT.value,
        LegalIRPremiseKind.THEOREM_TEMPLATE.value,
        LegalIRPremiseKind.SAMPLE_LOCAL_ASSUMPTION.value,
        LegalIRPremiseKind.VERIFIED_LEANSTRAL_THEOREM.value,
    }
    assert all(item.score >= 0 for item in ranked)
