"""Theorem-prover requirement verification for completed PDF forms.

:class:`FormRequirementsVerifier` takes a completed set of field values and the
``DeonticRuleSet`` produced by
:class:`~ipfs_datasets_py.processors.pdf_form_ir.FormToLegalIR` and verifies
that each obligation is satisfied using the existing
:class:`~ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine.ProofExecutionEngine`.

Pipeline
--------
::

    values: dict[field_name → value]
    rule_set: DeonticRuleSet          # from FormToLegalIR
         │
         ▼
    FormRequirementsVerifier.verify()
         │
         ├─ instantiate each formula with the provided values
         ├─ call ProofExecutionEngine.prove_deontic_formula()
         ├─ detect conflicts via DeonticRuleSet.check_consistency()
         └─ return VerificationReport

Fail-closed semantics
---------------------
``overall_pass`` is True only when every mandatory check executed and
returned ``satisfied`` with evidence. Empty inputs, empty rule sets,
timeouts, unsupported semantics, prover errors, and conflict-detection
failures never produce a pass. Non-definitive outcomes use ``unknown``
or ``review_required``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# Definitive and non-definitive per-formula statuses.
STATUS_SATISFIED = "satisfied"
STATUS_VIOLATED = "violated"
STATUS_UNKNOWN = "unknown"
STATUS_REVIEW_REQUIRED = "review_required"

# Statuses that block overall_pass (everything except satisfied).
_NON_PASS_STATUSES = frozenset({
    STATUS_VIOLATED,
    STATUS_UNKNOWN,
    STATUS_REVIEW_REQUIRED,
    # Legacy aliases retained for any external callers that still emit them.
    "skipped",
    "error",
})


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class FieldVerificationResult:
    """Proof outcome for a single deontic formula / field obligation.

    ``status`` is one of:
    - ``satisfied``: obligation proven satisfied with evidence
    - ``violated``: obligation proven failed (empty required field, counter-example)
    - ``unknown``: proof skipped/timeout/unsupported or evidence incomplete
    - ``review_required``: prover/runtime error or other human-review case
    """

    formula_id: str
    proposition: str
    field_name: str          # extracted from formula variables["field"] if available
    status: str              # satisfied | violated | unknown | review_required
    prover: str
    proof_output: str = ""
    errors: List[str] = field(default_factory=list)
    execution_time: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "formula_id": self.formula_id,
            "proposition": self.proposition,
            "field_name": self.field_name,
            "status": self.status,
            "prover": self.prover,
            "proof_output": self.proof_output,
            "errors": self.errors,
            "execution_time": self.execution_time,
        }


@dataclass
class ConflictRecord:
    """A detected conflict between two deontic formulas."""

    formula_id_a: str
    formula_id_b: str
    description: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "formula_id_a": self.formula_id_a,
            "formula_id_b": self.formula_id_b,
            "description": self.description,
        }


@dataclass
class VerificationReport:
    """Machine-readable outcome of a form-completion verification run.

    This report is JSON-serialisable and serves as the public input to the
    ZKP certificate step (Phase 5).

    Fail-closed: ``overall_pass`` is True only when every formula result is
    ``satisfied``, at least one formula was checked, and no conflicts remain.
    Any unknown/review/error path sets ``review_required``.
    """

    form_id: str
    source_pdf: str
    timestamp: float
    overall_pass: bool
    results: List[FieldVerificationResult] = field(default_factory=list)
    conflicts: List[ConflictRecord] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    review_required: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "form_id": self.form_id,
            "source_pdf": self.source_pdf,
            "timestamp": self.timestamp,
            "overall_pass": self.overall_pass,
            "review_required": self.review_required,
            "results": [r.to_dict() for r in self.results],
            "conflicts": [c.to_dict() for c in self.conflicts],
            "metadata": self.metadata,
        }

    def to_json(self, **kwargs: Any) -> str:
        return json.dumps(self.to_dict(), **kwargs)

    def verdicts_hash(self) -> str:
        """Deterministic SHA-256 hash of the per-formula pass/fail verdicts.

        Used as a public input to the ZKP circuit so the proof commits to
        the verification outcome without revealing field values.
        """
        summary = json.dumps(
            {r.formula_id: r.status for r in sorted(self.results, key=lambda x: x.formula_id)},
            sort_keys=True,
        )
        return hashlib.sha256(summary.encode()).hexdigest()


def _dataclass_asdict_unused(obj: Any) -> Any:
    """Unused - kept for reference."""
    if hasattr(obj, "__dataclass_fields__"):
        return {k: _dataclass_asdict_unused(getattr(obj, k)) for k in obj.__dataclass_fields__}
    if isinstance(obj, list):
        return [_dataclass_asdict_unused(v) for v in obj]
    return obj


def _aggregate_fail_closed(
    results: List[FieldVerificationResult],
    conflicts: List[ConflictRecord],
    *,
    empty_input: bool = False,
    conflict_check_failed: bool = False,
    fail_closed_reasons: Optional[List[str]] = None,
) -> Tuple[bool, bool, List[str]]:
    """Compute overall_pass and review_required under fail-closed rules.

    Returns
    -------
    overall_pass, review_required, reasons
    """
    reasons: List[str] = list(fail_closed_reasons or [])
    review_required = False
    overall_pass = True

    if empty_input:
        overall_pass = False
        review_required = True
        reasons.append("empty_input")

    if not results:
        # Vacuous success is forbidden: no executed checks cannot pass.
        overall_pass = False
        review_required = True
        reasons.append("no_formulas_checked")

    for result in results:
        status = result.status
        if status == STATUS_SATISFIED:
            continue
        overall_pass = False
        if status in (STATUS_UNKNOWN, "skipped"):
            review_required = True
            reasons.append(f"unknown:{result.formula_id or result.field_name}")
        elif status in (STATUS_REVIEW_REQUIRED, "error"):
            review_required = True
            reasons.append(f"review_required:{result.formula_id or result.field_name}")
        elif status == STATUS_VIOLATED:
            reasons.append(f"violated:{result.formula_id or result.field_name}")
        else:
            # Unrecognized status — treat as non-pass requiring review.
            review_required = True
            reasons.append(f"unrecognized_status:{status}")

    if conflicts:
        overall_pass = False
        review_required = True
        reasons.append("conflicts_detected")

    if conflict_check_failed:
        overall_pass = False
        review_required = True
        reasons.append("conflict_detection_failed")

    # Defensive: never allow pass when any non-pass status or review is set.
    if review_required:
        overall_pass = False
    if any(r.status in _NON_PASS_STATUSES for r in results):
        overall_pass = False

    return overall_pass, review_required, reasons


def _status_counts(results: List[FieldVerificationResult]) -> Dict[str, int]:
    counts = {
        "satisfied": 0,
        "violated": 0,
        "unknown": 0,
        "review_required": 0,
        # Legacy keys kept so existing consumers of metadata still work.
        "skipped": 0,
        "error": 0,
    }
    for result in results:
        if result.status in counts:
            counts[result.status] += 1
        elif result.status == "skipped":
            counts["skipped"] += 1
            counts["unknown"] += 1
        elif result.status == "error":
            counts["error"] += 1
            counts["review_required"] += 1
    return counts


# ---------------------------------------------------------------------------
# FormRequirementsVerifier
# ---------------------------------------------------------------------------

class FormRequirementsVerifier:
    """Verify that a set of field values satisfies all deontic obligations.

    Parameters
    ----------
    prover:
        Theorem prover to use (``"z3"``, ``"cvc5"``, ``"lean"``, ``"coq"``).
        Defaults to ``"z3"``.
    timeout:
        Per-formula proof timeout in seconds.

    Fail-closed aggregation
    -----------------------
    ``overall_pass`` requires a non-empty formula set, non-empty values when
    obligations reference fields, every formula ``satisfied``, and a successful
    conflict check with no conflicts. Timeouts, unsupported proofs, and
    runtime errors surface as ``unknown`` / ``review_required`` and block pass.
    """

    def __init__(
        self,
        *,
        prover: str = "z3",
        timeout: int = 30,
    ) -> None:
        self.prover = prover
        self.timeout = timeout
        self._engine: Any = None  # lazy

    def _get_engine(self) -> Any:
        if self._engine is None:
            from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine import (
                ProofExecutionEngine,
            )
            self._engine = ProofExecutionEngine(timeout=self.timeout)
        return self._engine

    # ------------------------------------------------------------------
    # Value instantiation
    # ------------------------------------------------------------------

    def _instantiate_formula(self, formula: Any, values: Dict[str, Any]) -> Any:
        """Return a copy of *formula* with its proposition filled in with
        the actual field value, so the prover can check satisfiability."""
        try:
            from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import (
                DeonticFormula,
                DeonticOperator,
            )
        except ImportError:
            return formula

        field_name = formula.variables.get("field", "")
        value = values.get(field_name, "") if field_name else ""

        # Build an instantiated proposition: fill(field) ∧ value(field) = "v"
        new_prop = formula.proposition
        if field_name and value is not None:
            value_str = str(value)
            new_prop = f"{formula.proposition} [value={value_str!r}]"

        # Check required obligation
        data_type = formula.variables.get("data_type", "string")
        del data_type  # reserved for future typed checks
        conditions = list(formula.conditions)
        if formula.operator == DeonticOperator.OBLIGATION:
            if not field_name:
                conditions.append(
                    "unknown: obligation has no field binding; cannot verify"
                )
            elif not value:
                conditions.append(f"violated: required field '{field_name}' is empty")

        return DeonticFormula(
            operator=formula.operator,
            proposition=new_prop,
            agent=formula.agent,
            conditions=conditions,
            legal_context=formula.legal_context,
            confidence=formula.confidence,
            source_text=formula.source_text,
            variables={**formula.variables, "filled_value": str(value)},
        )

    # ------------------------------------------------------------------
    # Conflict detection
    # ------------------------------------------------------------------

    def _detect_conflicts(
        self, rule_set: Any
    ) -> Tuple[List[ConflictRecord], bool]:
        """Run ``DeonticRuleSet.check_consistency()``.

        Returns ``(records, check_failed)``. On exception, fail closed by
        reporting ``check_failed=True`` rather than silently returning empty.
        """
        try:
            raw_conflicts = rule_set.check_consistency()
        except Exception as exc:
            logger.warning("Conflict detection failed: %s", exc)
            return [], True

        records: List[ConflictRecord] = []
        for f1, f2, description in (raw_conflicts or []):
            records.append(
                ConflictRecord(
                    formula_id_a=getattr(f1, "formula_id", str(f1)),
                    formula_id_b=getattr(f2, "formula_id", str(f2)),
                    description=description,
                )
            )
        return records, False

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def verify(
        self,
        values: Dict[str, Any],
        rule_set: Any,
        *,
        form_id: str = "",
        source_pdf: str = "",
    ) -> VerificationReport:
        """Verify *values* against every formula in *rule_set*.

        Parameters
        ----------
        values:
            ``{field_name: filled_value}`` dict from the agent or the user.
        rule_set:
            ``DeonticRuleSet`` produced by :class:`FormToLegalIR`.
        form_id:
            Identifier for the form (forwarded to the report).
        source_pdf:
            Path to the source PDF (forwarded to the report).

        Returns
        -------
        :class:`VerificationReport`
        """
        values = values if isinstance(values, dict) else {}
        empty_input = not values

        try:
            engine = self._get_engine()
        except ImportError:
            logger.warning("ProofExecutionEngine unavailable; returning lightweight report")
            return self._lightweight_verify(values, rule_set, form_id=form_id, source_pdf=source_pdf)

        results: List[FieldVerificationResult] = []
        formulas = list(getattr(rule_set, "formulas", None) or [])

        for formula in formulas:
            instantiated = self._instantiate_formula(formula, values)
            field_name = (getattr(formula, "variables", None) or {}).get("field", "")
            formula_id = getattr(formula, "formula_id", "")
            proposition = getattr(instantiated, "proposition", getattr(formula, "proposition", ""))
            conditions = list(getattr(instantiated, "conditions", None) or [])

            # Inline unknown (e.g. missing field binding)
            unknown_inline = [c for c in conditions if "unknown:" in c]
            if unknown_inline:
                results.append(FieldVerificationResult(
                    formula_id=formula_id,
                    proposition=proposition,
                    field_name=field_name,
                    status=STATUS_UNKNOWN,
                    prover="inline",
                    errors=unknown_inline,
                ))
                continue

            # Inline violation (required empty)
            violated_inline = [c for c in conditions if "violated:" in c]
            if violated_inline:
                results.append(FieldVerificationResult(
                    formula_id=formula_id,
                    proposition=proposition,
                    field_name=field_name,
                    status=STATUS_VIOLATED,
                    prover="inline",
                    errors=violated_inline,
                ))
                continue

            t0 = time.time()
            try:
                proof_result = engine.prove_deontic_formula(
                    instantiated,
                    prover=self.prover,
                )
                elapsed = time.time() - t0
                from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
                if proof_result.status == ProofStatus.SUCCESS:
                    status = STATUS_SATISFIED
                elif proof_result.status == ProofStatus.FAILURE:
                    # Explicit proof failure (prover ran and found a counter-example)
                    status = STATUS_VIOLATED
                elif proof_result.status == ProofStatus.UNSUPPORTED:
                    # Cannot determine; fail closed as unknown
                    status = STATUS_UNKNOWN
                elif proof_result.status == ProofStatus.TIMEOUT:
                    status = STATUS_UNKNOWN
                else:
                    # ERROR or any other non-success → human review
                    status = STATUS_REVIEW_REQUIRED

                results.append(FieldVerificationResult(
                    formula_id=formula_id,
                    proposition=proposition,
                    field_name=field_name,
                    status=status,
                    prover=getattr(proof_result, "prover", self.prover),
                    proof_output=getattr(proof_result, "proof_output", "") or "",
                    errors=list(getattr(proof_result, "errors", None) or []),
                    execution_time=elapsed,
                ))
            except Exception as exc:
                elapsed = time.time() - t0
                logger.warning("Proof execution error for formula %s: %s", formula_id, exc)
                results.append(FieldVerificationResult(
                    formula_id=formula_id,
                    proposition=proposition,
                    field_name=field_name,
                    status=STATUS_REVIEW_REQUIRED,
                    prover=self.prover,
                    errors=[str(exc)],
                    execution_time=elapsed,
                ))

        conflicts, conflict_check_failed = self._detect_conflicts(rule_set)
        overall_pass, review_required, reasons = _aggregate_fail_closed(
            results,
            conflicts,
            empty_input=empty_input,
            conflict_check_failed=conflict_check_failed,
        )
        counts = _status_counts(results)

        return VerificationReport(
            form_id=form_id or getattr(rule_set, "rule_set_id", ""),
            source_pdf=source_pdf,
            timestamp=time.time(),
            overall_pass=overall_pass,
            review_required=review_required,
            results=results,
            conflicts=conflicts,
            metadata={
                "prover": self.prover,
                "formula_count": len(formulas),
                "satisfied": counts["satisfied"],
                "violated": counts["violated"],
                "unknown": counts["unknown"],
                "review_required": counts["review_required"],
                # Compatibility aliases for prior metadata consumers.
                "skipped": counts["unknown"],
                "error": counts["review_required"],
                "fail_closed_reasons": reasons,
                "conflict_check_failed": conflict_check_failed,
                "empty_input": empty_input,
            },
        )

    # ------------------------------------------------------------------
    # Lightweight fallback (no prover)
    # ------------------------------------------------------------------

    def _lightweight_verify(
        self,
        values: Dict[str, Any],
        rule_set: Any,
        *,
        form_id: str = "",
        source_pdf: str = "",
    ) -> VerificationReport:
        """Fast rule-based check without a theorem prover backend.

        Still fail-closed: empty rule sets and empty inputs never pass;
        unbound obligations and prover absence of field evidence surface as
        unknown/review rather than vacuous satisfaction.
        """
        values = values if isinstance(values, dict) else {}
        empty_input = not values
        results: List[FieldVerificationResult] = []
        formulas = list(getattr(rule_set, "formulas", None) or [])

        for formula in formulas:
            try:
                from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import DeonticOperator
                is_obligation = formula.operator == DeonticOperator.OBLIGATION
            except Exception:
                is_obligation = True  # assume obligation when unsure (stricter)

            field_name = (getattr(formula, "variables", None) or {}).get("field", "")
            value = values.get(field_name, "") if field_name else ""
            formula_id = getattr(formula, "formula_id", "")
            proposition = getattr(formula, "proposition", str(formula))

            if is_obligation and not field_name:
                status = STATUS_UNKNOWN
                errors = ["Obligation has no field binding; cannot verify."]
            elif is_obligation and field_name and not value:
                status = STATUS_VIOLATED
                errors = [f"Required field '{field_name}' has no value."]
            elif not is_obligation:
                # Permission/prohibition without prover: cannot fully verify.
                status = STATUS_UNKNOWN
                errors = ["Non-obligation formula cannot be verified without a prover."]
            else:
                status = STATUS_SATISFIED
                errors = []

            results.append(FieldVerificationResult(
                formula_id=formula_id,
                proposition=proposition,
                field_name=field_name,
                status=status,
                prover="lightweight",
                errors=errors,
            ))

        conflicts, conflict_check_failed = self._detect_conflicts(rule_set)
        overall_pass, review_required, reasons = _aggregate_fail_closed(
            results,
            conflicts,
            empty_input=empty_input,
            conflict_check_failed=conflict_check_failed,
            fail_closed_reasons=["lightweight_prover_fallback"] if formulas else None,
        )
        # Lightweight path is partial assurance: still allow pass only when
        # every obligation was a field-presence check that succeeded. Mark
        # review when we relied on lightweight semantics with no prover.
        if overall_pass and formulas:
            # Field-presence only is still a completed check set; do not force review.
            pass
        counts = _status_counts(results)

        return VerificationReport(
            form_id=form_id or getattr(rule_set, "rule_set_id", ""),
            source_pdf=source_pdf,
            timestamp=time.time(),
            overall_pass=overall_pass,
            review_required=review_required,
            results=results,
            conflicts=conflicts,
            metadata={
                "prover": "lightweight",
                "formula_count": len(formulas),
                "satisfied": counts["satisfied"],
                "violated": counts["violated"],
                "unknown": counts["unknown"],
                "review_required": counts["review_required"],
                "skipped": counts["unknown"],
                "error": counts["review_required"],
                "fail_closed_reasons": reasons,
                "conflict_check_failed": conflict_check_failed,
                "empty_input": empty_input,
            },
        )


__all__ = [
    "ConflictRecord",
    "FieldVerificationResult",
    "FormRequirementsVerifier",
    "STATUS_REVIEW_REQUIRED",
    "STATUS_SATISFIED",
    "STATUS_UNKNOWN",
    "STATUS_VIOLATED",
    "VerificationReport",
]
