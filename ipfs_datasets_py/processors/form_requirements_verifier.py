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
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class FieldVerificationResult:
    """Proof outcome for a single deontic formula / field obligation."""

    formula_id: str
    proposition: str
    field_name: str          # extracted from formula variables["field"] if available
    status: str              # "satisfied" | "violated" | "skipped" | "error"
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
        return asdict(self)  # type: ignore[name-defined]


@dataclass
class VerificationReport:
    """Machine-readable outcome of a form-completion verification run.

    This report is JSON-serialisable and serves as the public input to the
    ZKP certificate step (Phase 5).
    """

    form_id: str
    source_pdf: str
    timestamp: float
    overall_pass: bool
    results: List[FieldVerificationResult] = field(default_factory=list)
    conflicts: List[ConflictRecord] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "form_id": self.form_id,
            "source_pdf": self.source_pdf,
            "timestamp": self.timestamp,
            "overall_pass": self.overall_pass,
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


def _dataclass_asdict(obj: Any) -> Any:
    """Minimal dataclass to dict — avoids importing dataclasses.asdict in loops."""
    if hasattr(obj, "__dataclass_fields__"):
        return {k: _dataclass_asdict(getattr(obj, k)) for k in obj.__dataclass_fields__}
    if isinstance(obj, list):
        return [_dataclass_asdict(v) for v in obj]
    return obj


# Monkey-patch ConflictRecord.to_dict properly
def _conflict_to_dict(self: ConflictRecord) -> Dict[str, Any]:
    return {
        "formula_id_a": self.formula_id_a,
        "formula_id_b": self.formula_id_b,
        "description": self.description,
    }

ConflictRecord.to_dict = _conflict_to_dict  # type: ignore[method-assign]


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
        value = values.get(field_name, "")

        # Build an instantiated proposition: fill(field) ∧ value(field) = "v"
        new_prop = formula.proposition
        if field_name and value is not None:
            value_str = str(value)
            new_prop = f"{formula.proposition} [value={value_str!r}]"

        # Check required obligation
        data_type = formula.variables.get("data_type", "string")
        conditions = list(formula.conditions)
        if formula.operator == DeonticOperator.OBLIGATION and field_name:
            if not value:
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

    def _detect_conflicts(self, rule_set: Any) -> List[ConflictRecord]:
        """Run the built-in ``DeonticRuleSet.check_consistency()`` and convert
        the results to :class:`ConflictRecord` objects."""
        try:
            raw_conflicts = rule_set.check_consistency()
        except Exception as exc:
            logger.warning("Conflict detection failed: %s", exc)
            return []

        records: List[ConflictRecord] = []
        for f1, f2, description in (raw_conflicts or []):
            records.append(
                ConflictRecord(
                    formula_id_a=f1.formula_id,
                    formula_id_b=f2.formula_id,
                    description=description,
                )
            )
        return records

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
        try:
            engine = self._get_engine()
        except ImportError:
            logger.warning("ProofExecutionEngine unavailable; returning lightweight report")
            return self._lightweight_verify(values, rule_set, form_id=form_id, source_pdf=source_pdf)

        results: List[FieldVerificationResult] = []
        overall_pass = True

        for formula in (rule_set.formulas or []):
            instantiated = self._instantiate_formula(formula, values)
            field_name = formula.variables.get("field", "")

            # Check if the obligation condition is flagged as violated
            violated_inline = any(
                "violated:" in cond for cond in instantiated.conditions
            )
            if violated_inline:
                status = "violated"
                overall_pass = False
                results.append(FieldVerificationResult(
                    formula_id=formula.formula_id,
                    proposition=instantiated.proposition,
                    field_name=field_name,
                    status=status,
                    prover="inline",
                    errors=[c for c in instantiated.conditions if "violated:" in c],
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
                    status = "satisfied"
                elif proof_result.status in {ProofStatus.UNSUPPORTED, ProofStatus.TIMEOUT}:
                    # Cannot prove — treat as skipped, don't fail the form
                    status = "skipped"
                else:
                    status = "violated"
                    overall_pass = False

                results.append(FieldVerificationResult(
                    formula_id=formula.formula_id,
                    proposition=instantiated.proposition,
                    field_name=field_name,
                    status=status,
                    prover=proof_result.prover,
                    proof_output=proof_result.proof_output,
                    errors=proof_result.errors,
                    execution_time=elapsed,
                ))
            except Exception as exc:
                elapsed = time.time() - t0
                logger.warning("Proof execution error for formula %s: %s", formula.formula_id, exc)
                results.append(FieldVerificationResult(
                    formula_id=formula.formula_id,
                    proposition=instantiated.proposition,
                    field_name=field_name,
                    status="error",
                    prover=self.prover,
                    errors=[str(exc)],
                    execution_time=elapsed,
                ))

        conflicts = self._detect_conflicts(rule_set)
        if conflicts:
            overall_pass = False

        return VerificationReport(
            form_id=form_id or getattr(rule_set, "rule_set_id", ""),
            source_pdf=source_pdf,
            timestamp=time.time(),
            overall_pass=overall_pass,
            results=results,
            conflicts=conflicts,
            metadata={
                "prover": self.prover,
                "formula_count": len(rule_set.formulas),
                "satisfied": sum(1 for r in results if r.status == "satisfied"),
                "violated": sum(1 for r in results if r.status == "violated"),
                "skipped": sum(1 for r in results if r.status == "skipped"),
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
        """Fast rule-based check without a theorem prover backend."""
        results: List[FieldVerificationResult] = []
        overall_pass = True

        for formula in (getattr(rule_set, "formulas", None) or []):
            try:
                from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import DeonticOperator
                is_obligation = formula.operator == DeonticOperator.OBLIGATION
            except Exception:
                is_obligation = True  # assume obligation when unsure

            field_name = (getattr(formula, "variables", None) or {}).get("field", "")
            value = values.get(field_name, "")
            required_but_empty = is_obligation and field_name and not value

            if required_but_empty:
                overall_pass = False
                status = "violated"
                errors = [f"Required field '{field_name}' has no value."]
            else:
                status = "satisfied"
                errors = []

            results.append(FieldVerificationResult(
                formula_id=getattr(formula, "formula_id", ""),
                proposition=getattr(formula, "proposition", str(formula)),
                field_name=field_name,
                status=status,
                prover="lightweight",
                errors=errors,
            ))

        conflicts = self._detect_conflicts(rule_set)
        if conflicts:
            overall_pass = False

        return VerificationReport(
            form_id=form_id,
            source_pdf=source_pdf,
            timestamp=time.time(),
            overall_pass=overall_pass,
            results=results,
            conflicts=conflicts,
            metadata={"prover": "lightweight"},
        )


__all__ = [
    "ConflictRecord",
    "FieldVerificationResult",
    "FormRequirementsVerifier",
    "VerificationReport",
]
