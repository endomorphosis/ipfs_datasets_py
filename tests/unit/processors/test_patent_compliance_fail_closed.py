"""PATLAW-005: fail-closed legal and form verification regressions.

Acceptance
----------
- Every absent/unsupported/skipped/errored case yields ``unknown`` or
  ``review_required``.
- No empty input can produce ``overall_pass=True``.
- Existing supported satisfied/failed behavior remains compatible.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from ipfs_datasets_py.processors.form_requirements_verifier import (
    STATUS_REVIEW_REQUIRED,
    STATUS_SATISFIED,
    STATUS_UNKNOWN,
    STATUS_VIOLATED,
    FormRequirementsVerifier,
    VerificationReport,
)
from ipfs_datasets_py.processors.legal_data.dependency_graph import (
    Dependency,
    DependencyGraph,
    DependencyNode,
    DependencyType,
    NodeType,
)
from ipfs_datasets_py.processors.legal_data.neurosymbolic import (
    STATUS_REVIEW_REQUIRED as NS_REVIEW_REQUIRED,
    STATUS_SATISFIED as NS_SATISFIED,
    STATUS_UNKNOWN as NS_UNKNOWN,
    STATUS_UNSATISFIED as NS_UNSATISFIED,
    NeurosymbolicMatcher,
)
from ipfs_datasets_py.processors.legal_data.requirements_graph import (
    LegalElement,
    LegalRequirementsGraph,
)
from ipfs_datasets_py.processors.protocol import Entity, KnowledgeGraph, Relationship


# ---------------------------------------------------------------------------
# Helpers — form verifier
# ---------------------------------------------------------------------------


def _formula(
    *,
    formula_id: str = "f1",
    field: str = "full_name",
    operator: str = "obligation",
    proposition: str = "fill(full_name)",
) -> SimpleNamespace:
    """Minimal formula stand-in compatible with the verifier."""
    try:
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import (
            DeonticOperator,
        )
        op_map = {
            "obligation": DeonticOperator.OBLIGATION,
            "permission": DeonticOperator.PERMISSION,
            "prohibition": DeonticOperator.PROHIBITION,
        }
        op = op_map.get(operator, DeonticOperator.OBLIGATION)
    except Exception:
        op = SimpleNamespace(name=operator.upper())

    variables = {"field": field} if field is not None else {}
    # formula_id is often a property on real DeonticFormula; expose as attr.
    formula = SimpleNamespace(
        formula_id=formula_id,
        operator=op,
        proposition=proposition,
        agent="filer",
        conditions=[],
        legal_context="form",
        confidence=1.0,
        source_text=proposition,
        variables=variables,
    )
    return formula


def _rule_set(formulas: Optional[List[Any]] = None, *, raise_on_consistency: bool = False) -> SimpleNamespace:
    formulas = list(formulas or [])

    def check_consistency():
        if raise_on_consistency:
            raise RuntimeError("consistency backend unavailable")
        return []

    return SimpleNamespace(
        formulas=formulas,
        rule_set_id="test-form",
        check_consistency=check_consistency,
    )


def _proof_status(name: str):
    from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
    return getattr(ProofStatus, name)


def _proof_result(status_name: str, *, prover: str = "z3", errors: Optional[List[str]] = None):
    return SimpleNamespace(
        status=_proof_status(status_name),
        prover=prover,
        proof_output="",
        errors=list(errors or []),
    )


def _verifier_with_engine(engine: Any) -> FormRequirementsVerifier:
    verifier = FormRequirementsVerifier(prover="z3", timeout=5)
    verifier._engine = engine
    return verifier


# ---------------------------------------------------------------------------
# Helpers — neurosymbolic
# ---------------------------------------------------------------------------


def _empty_kg() -> KnowledgeGraph:
    return KnowledgeGraph(entities=[], relationships=[], source="test")


def _kg_with_support(claim_label: str = "Termination") -> KnowledgeGraph:
    return KnowledgeGraph(
        entities=[
            Entity(id="claim_entity", type="claim", label=claim_label),
            Entity(id="doc_1", type="evidence", label="Notice"),
        ],
        relationships=[
            Relationship(
                id="rel_1",
                source="claim_entity",
                target="doc_1",
                type="supported_by",
            )
        ],
        source="test",
    )


def _dep_graph_with_claim(
    claim_id: str = "claim_1",
    claim_name: str = "Termination",
    claim_type: str = "termination",
    *,
    satisfied_requirement: bool = False,
    requirement_name: str = "Damages Requirement",
) -> DependencyGraph:
    graph = DependencyGraph()
    graph.add_node(
        DependencyNode(
            id=claim_id,
            node_type=NodeType.CLAIM,
            name=claim_name,
            attributes={"claim_type": claim_type},
        )
    )
    graph.add_node(
        DependencyNode(
            id="req_node_1",
            node_type=NodeType.REQUIREMENT,
            name=requirement_name,
            satisfied=satisfied_requirement,
            confidence=0.9 if satisfied_requirement else 0.0,
        )
    )
    graph.add_dependency(
        Dependency(
            id="dep_1",
            source_id="req_node_1",
            target_id=claim_id,
            dependency_type=DependencyType.REQUIRES,
            required=True,
        )
    )
    return graph


def _legal_graph_for(
    claim_type: str = "termination",
    *,
    requirement_name: str = "Damages Requirement",
) -> LegalRequirementsGraph:
    graph = LegalRequirementsGraph()
    graph.add_element(
        LegalElement(
            id="req_1",
            element_type="requirement",
            name=requirement_name,
            description="Requires damages showing",
            citation="Example § 1",
            attributes={"applicable_claim_types": [claim_type]},
        )
    )
    return graph


# ===========================================================================
# FormRequirementsVerifier — empty / absent inputs
# ===========================================================================


class TestFormVerifierEmptyAndAbsent:
    def test_empty_values_and_empty_formulas_never_pass(self):
        verifier = FormRequirementsVerifier()
        # Force lightweight path to avoid prover dependency noise.
        with patch.object(FormRequirementsVerifier, "_get_engine", side_effect=ImportError("no engine")):
            report = verifier.verify({}, _rule_set([]), form_id="empty")

        assert report.overall_pass is False
        assert report.review_required is True
        assert report.results == []
        assert "no_formulas_checked" in report.metadata.get("fail_closed_reasons", [])
        assert report.metadata.get("empty_input") is True

    def test_empty_formulas_with_values_never_pass(self):
        verifier = FormRequirementsVerifier()
        with patch.object(FormRequirementsVerifier, "_get_engine", side_effect=ImportError("no engine")):
            report = verifier.verify({"full_name": "Alice"}, _rule_set([]))

        assert report.overall_pass is False
        assert report.review_required is True
        assert "no_formulas_checked" in report.metadata.get("fail_closed_reasons", [])

    def test_empty_values_with_required_obligation_is_violated_not_pass(self):
        verifier = FormRequirementsVerifier()
        with patch.object(FormRequirementsVerifier, "_get_engine", side_effect=ImportError("no engine")):
            report = verifier.verify({}, _rule_set([_formula(field="full_name")]))

        assert report.overall_pass is False
        assert any(r.status == STATUS_VIOLATED for r in report.results)
        # Empty input also forces review_required under fail-closed aggregation.
        assert report.review_required is True

    def test_none_like_values_coerced_fail_closed(self):
        verifier = FormRequirementsVerifier()
        with patch.object(FormRequirementsVerifier, "_get_engine", side_effect=ImportError("no engine")):
            # type: ignore[arg-type] — adversarial non-dict input
            report = verifier.verify(None, _rule_set([]))  # type: ignore[arg-type]

        assert report.overall_pass is False
        assert report.review_required is True


# ===========================================================================
# FormRequirementsVerifier — unsupported / skipped / timeout / error
# ===========================================================================


class TestFormVerifierNonDefinitiveOutcomes:
    def test_unsupported_proof_yields_unknown_and_blocks_pass(self):
        engine = MagicMock()
        engine.prove_deontic_formula.return_value = _proof_result("UNSUPPORTED")
        verifier = _verifier_with_engine(engine)

        report = verifier.verify(
            {"full_name": "Alice"},
            _rule_set([_formula(field="full_name")]),
        )

        assert len(report.results) == 1
        assert report.results[0].status == STATUS_UNKNOWN
        assert report.overall_pass is False
        assert report.review_required is True

    def test_timeout_yields_unknown_and_blocks_pass(self):
        engine = MagicMock()
        engine.prove_deontic_formula.return_value = _proof_result("TIMEOUT")
        verifier = _verifier_with_engine(engine)

        report = verifier.verify(
            {"full_name": "Alice"},
            _rule_set([_formula(field="full_name")]),
        )

        assert report.results[0].status == STATUS_UNKNOWN
        assert report.overall_pass is False
        assert report.review_required is True

    def test_prover_error_status_yields_review_required(self):
        engine = MagicMock()
        engine.prove_deontic_formula.return_value = _proof_result("ERROR", errors=["backend crash"])
        verifier = _verifier_with_engine(engine)

        report = verifier.verify(
            {"full_name": "Alice"},
            _rule_set([_formula(field="full_name")]),
        )

        assert report.results[0].status == STATUS_REVIEW_REQUIRED
        assert report.overall_pass is False
        assert report.review_required is True

    def test_prover_exception_yields_review_required(self):
        engine = MagicMock()
        engine.prove_deontic_formula.side_effect = RuntimeError("prover exploded")
        verifier = _verifier_with_engine(engine)

        report = verifier.verify(
            {"full_name": "Alice"},
            _rule_set([_formula(field="full_name")]),
        )

        assert report.results[0].status == STATUS_REVIEW_REQUIRED
        assert "prover exploded" in report.results[0].errors[0]
        assert report.overall_pass is False
        assert report.review_required is True

    def test_unbound_obligation_yields_unknown(self):
        """Obligation with no field binding cannot be verified → unknown."""
        verifier = FormRequirementsVerifier()
        unbound = _formula(field="")
        unbound.variables = {}
        with patch.object(FormRequirementsVerifier, "_get_engine", side_effect=ImportError("no engine")):
            report = verifier.verify({"x": "1"}, _rule_set([unbound]))

        assert report.results[0].status == STATUS_UNKNOWN
        assert report.overall_pass is False
        assert report.review_required is True

    def test_conflict_detection_failure_blocks_pass(self):
        engine = MagicMock()
        engine.prove_deontic_formula.return_value = _proof_result("SUCCESS")
        verifier = _verifier_with_engine(engine)

        report = verifier.verify(
            {"full_name": "Alice"},
            _rule_set([_formula(field="full_name")], raise_on_consistency=True),
        )

        assert report.overall_pass is False
        assert report.review_required is True
        assert report.metadata.get("conflict_check_failed") is True
        assert "conflict_detection_failed" in report.metadata.get("fail_closed_reasons", [])

    def test_mixed_satisfied_and_unknown_never_passes(self):
        engine = MagicMock()
        engine.prove_deontic_formula.side_effect = [
            _proof_result("SUCCESS"),
            _proof_result("TIMEOUT"),
        ]
        verifier = _verifier_with_engine(engine)
        formulas = [
            _formula(formula_id="a", field="full_name"),
            _formula(formula_id="b", field="email", proposition="fill(email)"),
        ]
        report = verifier.verify(
            {"full_name": "Alice", "email": "a@b.c"},
            _rule_set(formulas),
        )

        statuses = {r.formula_id: r.status for r in report.results}
        assert statuses["a"] == STATUS_SATISFIED
        assert statuses["b"] == STATUS_UNKNOWN
        assert report.overall_pass is False
        assert report.review_required is True


# ===========================================================================
# FormRequirementsVerifier — supported satisfied / violated (compat)
# ===========================================================================


class TestFormVerifierSupportedOutcomesCompatible:
    def test_all_satisfied_proofs_yield_overall_pass(self):
        engine = MagicMock()
        engine.prove_deontic_formula.return_value = _proof_result("SUCCESS")
        verifier = _verifier_with_engine(engine)

        report = verifier.verify(
            {"full_name": "Alice", "email": "a@b.c"},
            _rule_set([
                _formula(formula_id="a", field="full_name"),
                _formula(formula_id="b", field="email", proposition="fill(email)"),
            ]),
        )

        assert all(r.status == STATUS_SATISFIED for r in report.results)
        assert report.overall_pass is True
        assert report.review_required is False

    def test_explicit_proof_failure_is_violated_not_unknown(self):
        engine = MagicMock()
        engine.prove_deontic_formula.return_value = _proof_result("FAILURE")
        verifier = _verifier_with_engine(engine)

        report = verifier.verify(
            {"full_name": "Alice"},
            _rule_set([_formula(field="full_name")]),
        )

        assert report.results[0].status == STATUS_VIOLATED
        assert report.overall_pass is False

    def test_empty_required_field_inline_violated(self):
        engine = MagicMock()
        # Engine should not be needed for inline violation, but provide it.
        engine.prove_deontic_formula.return_value = _proof_result("SUCCESS")
        verifier = _verifier_with_engine(engine)

        report = verifier.verify(
            {"full_name": ""},
            _rule_set([_formula(field="full_name")]),
        )

        assert report.results[0].status == STATUS_VIOLATED
        assert report.overall_pass is False
        engine.prove_deontic_formula.assert_not_called()

    def test_lightweight_filled_obligations_can_pass(self):
        verifier = FormRequirementsVerifier()
        with patch.object(FormRequirementsVerifier, "_get_engine", side_effect=ImportError("no engine")):
            report = verifier.verify(
                {"full_name": "Alice"},
                _rule_set([_formula(field="full_name")]),
            )

        assert report.results[0].status == STATUS_SATISFIED
        assert report.overall_pass is True
        assert report.metadata["prover"] == "lightweight"

    def test_report_to_dict_includes_review_required(self):
        report = VerificationReport(
            form_id="f",
            source_pdf="",
            timestamp=0.0,
            overall_pass=False,
            review_required=True,
        )
        payload = report.to_dict()
        assert payload["overall_pass"] is False
        assert payload["review_required"] is True


# ===========================================================================
# NeurosymbolicMatcher — empty / absent / unknown
# ===========================================================================


class TestNeurosymbolicFailClosed:
    def test_empty_claims_never_overall_pass(self):
        matcher = NeurosymbolicMatcher()
        result = matcher.match_claims_to_law(
            _empty_kg(),
            DependencyGraph(),
            LegalRequirementsGraph(),
        )

        assert result["total_claims"] == 0
        assert result["overall_pass"] is False
        assert result["review_required"] is True
        assert result["overall_status"] in {NS_UNKNOWN, NS_REVIEW_REQUIRED}
        assert "empty_claims" in result["fail_closed_reasons"]

    def test_absent_requirement_catalog_is_unknown_not_vacuous_pass(self):
        """Regression: no requirements for claim type must not set satisfied=True."""
        matcher = NeurosymbolicMatcher()
        dep = DependencyGraph()
        dep.add_node(
            DependencyNode(
                id="claim_1",
                node_type=NodeType.CLAIM,
                name="Termination",
                attributes={"claim_type": "termination"},
            )
        )
        result = matcher.match_claims_to_law(
            _empty_kg(),
            dep,
            LegalRequirementsGraph(),  # empty catalog
        )

        assert result["total_claims"] == 1
        claim = result["claims"][0]
        assert claim["satisfied"] is False
        assert claim["status"] == NS_UNKNOWN
        assert claim["review_required"] is True
        assert claim["confidence"] == 0.0
        assert result["overall_pass"] is False
        assert result["review_required"] is True
        assert result["overall_status"] in {NS_UNKNOWN, NS_REVIEW_REQUIRED}

    def test_unsatisfied_requirement_is_unsatisfied_not_pass(self):
        matcher = NeurosymbolicMatcher()
        result = matcher.match_claims_to_law(
            _empty_kg(),
            _dep_graph_with_claim(satisfied_requirement=False),
            _legal_graph_for(),
        )

        claim = result["claims"][0]
        # Matched dependency node exists but unsatisfied → unsatisfied (not unknown).
        assert claim["satisfied"] is False
        assert claim["status"] == NS_UNSATISFIED
        assert result["overall_pass"] is False

    def test_incomplete_evidence_without_dependency_match_is_unknown(self):
        matcher = NeurosymbolicMatcher()
        dep = DependencyGraph()
        dep.add_node(
            DependencyNode(
                id="claim_1",
                node_type=NodeType.CLAIM,
                name="Termination",
                attributes={"claim_type": "termination"},
            )
        )
        # Legal requirement exists but no overlapping dependency node and no claim entity.
        result = matcher.match_claims_to_law(
            _empty_kg(),
            dep,
            _legal_graph_for(requirement_name="Totally Unrelated Requirement Name XYZ"),
        )

        claim = result["claims"][0]
        assert claim["satisfied"] is False
        assert claim["status"] == NS_UNKNOWN
        assert claim["review_required"] is True
        assert result["overall_pass"] is False
        assert result["review_required"] is True

    def test_satisfied_claim_with_evidence_can_pass(self):
        matcher = NeurosymbolicMatcher()
        result = matcher.match_claims_to_law(
            _kg_with_support("Termination"),
            _dep_graph_with_claim(satisfied_requirement=True, requirement_name="Damages Requirement"),
            _legal_graph_for(requirement_name="Damages Requirement"),
        )

        claim = result["claims"][0]
        assert claim["satisfied"] is True
        assert claim["status"] == NS_SATISFIED
        assert claim["review_required"] is False
        assert result["overall_pass"] is True
        assert result["review_required"] is False
        assert result["overall_status"] == NS_SATISFIED
        assert result["overall_satisfaction"] == 1.0

    def test_mixed_unknown_claim_blocks_overall_pass(self):
        matcher = NeurosymbolicMatcher()
        dep = DependencyGraph()
        dep.add_node(
            DependencyNode(
                id="claim_ok",
                node_type=NodeType.CLAIM,
                name="Termination",
                attributes={"claim_type": "termination"},
            )
        )
        dep.add_node(
            DependencyNode(
                id="claim_gap",
                node_type=NodeType.CLAIM,
                name="Other",
                attributes={"claim_type": "unknown_type"},
            )
        )
        dep.add_node(
            DependencyNode(
                id="req_node_1",
                node_type=NodeType.REQUIREMENT,
                name="Damages Requirement",
                satisfied=True,
                confidence=0.9,
            )
        )
        dep.add_dependency(
            Dependency(
                id="dep_1",
                source_id="req_node_1",
                target_id="claim_ok",
                dependency_type=DependencyType.REQUIRES,
            )
        )
        legal = _legal_graph_for(claim_type="termination", requirement_name="Damages Requirement")

        result = matcher.match_claims_to_law(_kg_with_support("Termination"), dep, legal)

        assert result["total_claims"] == 2
        assert result["overall_pass"] is False
        assert result["review_required"] is True
        statuses = {c["claim_id"]: c["status"] for c in result["claims"]}
        assert statuses["claim_ok"] == NS_SATISFIED
        assert statuses["claim_gap"] == NS_UNKNOWN


# ===========================================================================
# Cross-cutting invariants
# ===========================================================================


class TestFailClosedInvariants:
    @pytest.mark.parametrize(
        "values,formulas_empty",
        [
            ({}, True),
            ({}, False),
            ({"a": "1"}, True),
        ],
    )
    def test_form_emptyish_inputs_never_pass(self, values, formulas_empty):
        formulas = [] if formulas_empty else [_formula(field="full_name")]
        verifier = FormRequirementsVerifier()
        with patch.object(FormRequirementsVerifier, "_get_engine", side_effect=ImportError("no engine")):
            report = verifier.verify(values, _rule_set(formulas))
        assert report.overall_pass is False

    def test_form_non_definitive_statuses_only_unknown_or_review(self):
        """Unsupported/timeout/error map exclusively to unknown|review_required."""
        cases = [
            ("UNSUPPORTED", STATUS_UNKNOWN),
            ("TIMEOUT", STATUS_UNKNOWN),
            ("ERROR", STATUS_REVIEW_REQUIRED),
        ]
        for status_name, expected in cases:
            engine = MagicMock()
            engine.prove_deontic_formula.return_value = _proof_result(status_name)
            verifier = _verifier_with_engine(engine)
            report = verifier.verify(
                {"full_name": "Alice"},
                _rule_set([_formula(field="full_name")]),
            )
            assert report.results[0].status == expected
            assert report.results[0].status in {STATUS_UNKNOWN, STATUS_REVIEW_REQUIRED}
            assert report.overall_pass is False

    def test_neurosymbolic_overall_pass_implies_no_review_and_all_satisfied(self):
        matcher = NeurosymbolicMatcher()
        result = matcher.match_claims_to_law(
            _kg_with_support("Termination"),
            _dep_graph_with_claim(satisfied_requirement=True),
            _legal_graph_for(),
        )
        if result["overall_pass"]:
            assert result["review_required"] is False
            assert result["overall_status"] == NS_SATISFIED
            assert all(c["satisfied"] and c["status"] == NS_SATISFIED for c in result["claims"])
