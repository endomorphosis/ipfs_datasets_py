"""
LogicVerifierBackendsMixin

Backend method implementations for LogicVerifier, extracted to keep the
main logic_verification.py file under 600 lines.  These methods rely only on
`self.use_symbolic_ai` and `self.fallback_enabled`, both set in
LogicVerifier.__init__.
"""

import logging
from typing import List, Tuple

from .logic_verification_types import (
    ConsistencyCheck,
    EntailmentResult,
    ProofResult,
    ProofStep,
)
from .logic_verification_utils import are_contradictory, parse_proof_steps

# Symbol is imported at module level so the mixin methods can reference it.
# The same conditional import pattern used in logic_verification.py is used
# here to avoid hard-requiring SymbolicAI.
try:
    from symai import Symbol  # type: ignore
    _SYMBOLIC_AI_AVAILABLE = True
except (ImportError, SystemExit):
    _SYMBOLIC_AI_AVAILABLE = False

    class Symbol:  # type: ignore  # noqa: F811
        def __init__(self, value: str, semantic: bool = False):
            self.value = value

        def query(self, prompt: str) -> str:
            return f"Mock response for: {prompt}"


logger = logging.getLogger(__name__)


class LogicVerifierBackendsMixin:
    """Mixin providing SymbolicAI and fallback backend methods for LogicVerifier."""

    # ------------------------------------------------------------------
    # Consistency backends
    # ------------------------------------------------------------------

    def _check_consistency_symbolic(self, formulas: List[str]) -> ConsistencyCheck:
        """Check consistency using SymbolicAI."""
        try:
            combined_formulas = " ∧ ".join(f"({formula})" for formula in formulas)
            symbol = Symbol(combined_formulas, semantic=True)

            consistency_query = symbol.query(
                "Are these logical formulas consistent with each other? "
                "Can they all be true at the same time? "
                "Respond with: consistent, inconsistent, or unknown"
            )

            result_text = getattr(consistency_query, 'value', str(consistency_query)).lower()
            conflicting: List[Tuple[str, str]] = []

            if "consistent" in result_text and "inconsistent" not in result_text:
                is_consistent = True
                confidence = 0.8
                explanation = "SymbolicAI analysis indicates the formulas are consistent"
            elif "inconsistent" in result_text:
                is_consistent = False
                confidence = 0.8
                explanation = "SymbolicAI analysis indicates the formulas are inconsistent"
                conflicting = self._find_conflicting_pairs_symbolic(formulas)
            else:
                if self.fallback_enabled:
                    return self._check_consistency_fallback(formulas)
                is_consistent = False
                confidence = 0.5
                explanation = "SymbolicAI could not determine consistency"

            return ConsistencyCheck(
                is_consistent=is_consistent,
                conflicting_formulas=conflicting if not is_consistent else [],
                confidence=confidence,
                explanation=explanation,
                method_used="symbolic_ai"
            )

        except Exception as e:
            logger.error(f"Error in symbolic consistency check: {e}")
            return self._check_consistency_fallback(formulas)

    def _check_consistency_fallback(self, formulas: List[str]) -> ConsistencyCheck:
        """Fallback consistency checking using basic pattern matching."""
        conflicting_pairs: List[Tuple[str, str]] = []

        for i, formula1 in enumerate(formulas):
            for j, formula2 in enumerate(formulas[i + 1:], i + 1):
                if are_contradictory(formula1, formula2):
                    conflicting_pairs.append((formula1, formula2))

        is_consistent = len(conflicting_pairs) == 0
        confidence = 0.6 if is_consistent else 0.8

        explanation = (
            "Basic pattern matching found no obvious contradictions" if is_consistent else
            f"Found {len(conflicting_pairs)} potential contradictions"
        )

        return ConsistencyCheck(
            is_consistent=is_consistent,
            conflicting_formulas=conflicting_pairs,
            confidence=confidence,
            explanation=explanation,
            method_used="pattern_matching"
        )

    def _find_conflicting_pairs_symbolic(self, formulas: List[str]) -> List[Tuple[str, str]]:
        """Find conflicting pairs using SymbolicAI."""
        conflicting: List[Tuple[str, str]] = []

        for i, formula1 in enumerate(formulas):
            for _j, formula2 in enumerate(formulas[i + 1:], i + 1):
                combined = Symbol(f"({formula1}) ∧ ({formula2})", semantic=True)
                contradiction_query = combined.query(
                    "Can these two logical statements both be true at the same time? "
                    "Respond with: yes, no, or unknown"
                )

                result = getattr(contradiction_query, 'value', str(contradiction_query)).lower()
                if "no" in result:
                    conflicting.append((formula1, formula2))

        return conflicting

    # ------------------------------------------------------------------
    # Entailment backends
    # ------------------------------------------------------------------

    def _check_entailment_symbolic(self, premises: List[str], conclusion: str) -> EntailmentResult:
        """Check entailment using SymbolicAI."""
        try:
            combined_premises = " ∧ ".join(f"({p})" for p in premises)
            entailment_formula = f"({combined_premises}) → ({conclusion})"

            symbol = Symbol(entailment_formula, semantic=True)

            entailment_query = symbol.query(
                "Is this logical implication valid? "
                "Do the premises logically entail the conclusion? "
                "Respond with: yes, no, or unknown"
            )

            result_text = getattr(entailment_query, 'value', str(entailment_query)).lower()

            if "yes" in result_text:
                entails = True
                confidence = 0.8
                explanation = "SymbolicAI analysis confirms the entailment"
            elif "no" in result_text:
                entails = False
                confidence = 0.8
                explanation = "SymbolicAI analysis rejects the entailment"
            else:
                if self.fallback_enabled:
                    return self._check_entailment_fallback(premises, conclusion)
                entails = False
                confidence = 0.5
                explanation = "SymbolicAI could not determine entailment"

            return EntailmentResult(
                entails=entails,
                premises=premises,
                conclusion=conclusion,
                confidence=confidence,
                explanation=explanation
            )

        except Exception as e:
            logger.error(f"Error in symbolic entailment check: {e}")
            return self._check_entailment_fallback(premises, conclusion)

    def _check_entailment_fallback(self, premises: List[str], conclusion: str) -> EntailmentResult:
        """Fallback entailment checking using basic rules."""
        entails = False
        confidence = 0.4
        explanation = "Basic pattern matching used"

        for premise in premises:
            if "→" in premise and conclusion in premise:
                parts = premise.split("→")
                if len(parts) == 2:
                    antecedent = parts[0].strip()
                    consequent = parts[1].strip()

                    if consequent == conclusion and antecedent in premises:
                        entails = True
                        confidence = 0.8
                        explanation = "Modus ponens pattern detected"
                        break

        return EntailmentResult(
            entails=entails,
            premises=premises,
            conclusion=conclusion,
            confidence=confidence,
            explanation=explanation
        )

    # ------------------------------------------------------------------
    # Proof generation backends
    # ------------------------------------------------------------------

    def _generate_proof_symbolic(self, premises: List[str], conclusion: str) -> ProofResult:
        """Generate proof using SymbolicAI."""
        try:
            premises_text = ", ".join(premises)
            proof_prompt = f"Given premises: {premises_text}. Prove: {conclusion}"

            symbol = Symbol(proof_prompt, semantic=True)

            proof_query = symbol.query(
                "Generate a logical proof with step-by-step reasoning. "
                "For each step, provide: step number, formula, and justification. "
                "Format as: Step 1: [formula] (justification)"
            )

            proof_text = getattr(proof_query, 'value', str(proof_query))
            steps = parse_proof_steps(proof_text)

            if not steps and self.fallback_enabled:
                return self._generate_proof_fallback(premises, conclusion)

            is_valid = len(steps) > 0 and steps[-1].formula == conclusion
            confidence = 0.7 if is_valid else 0.3

            return ProofResult(
                is_valid=is_valid,
                conclusion=conclusion,
                steps=steps,
                confidence=confidence,
                method_used="symbolic_ai"
            )

        except Exception as e:
            logger.error(f"Error in symbolic proof generation: {e}")
            return self._generate_proof_fallback(premises, conclusion)

    def _generate_proof_fallback(self, premises: List[str], conclusion: str) -> ProofResult:
        """Generate proof using fallback methods."""
        steps = []

        for i, premise in enumerate(premises):
            steps.append(ProofStep(
                step_number=i + 1,
                formula=premise,
                justification="Given premise",
                rule_applied="premise"
            ))

        for premise in premises:
            if "→" in premise:
                parts = premise.split("→")
                if len(parts) == 2:
                    antecedent = parts[0].strip()
                    consequent = parts[1].strip()

                    if antecedent in premises and consequent == conclusion:
                        steps.append(ProofStep(
                            step_number=len(steps) + 1,
                            formula=conclusion,
                            justification=f"Modus ponens from '{antecedent}' and '{premise}'",
                            rule_applied="modus_ponens",
                            premises=[antecedent, premise]
                        ))

                        return ProofResult(
                            is_valid=True,
                            conclusion=conclusion,
                            steps=steps,
                            confidence=0.8,
                            method_used="fallback_modus_ponens"
                        )

        return ProofResult(
            is_valid=False,
            conclusion=conclusion,
            steps=steps,
            confidence=0.1,
            method_used="fallback_failed",
            errors=["Could not generate proof with available fallback methods"]
        )
