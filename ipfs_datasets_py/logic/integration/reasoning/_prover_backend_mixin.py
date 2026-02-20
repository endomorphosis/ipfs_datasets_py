"""
Prover Backend Mixin

Contains per-prover proof execution and consistency-check methods extracted
from ProofExecutionEngine to keep that module under 500 lines.
"""

import subprocess
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from ..converters.deontic_logic_core import DeonticFormula, DeonticRuleSet
from ..converters.logic_translation_core import TranslationResult
from ..converters.logic_translation_core import SMTTranslator
from .proof_execution_engine_types import ProofStatus, ProofResult

logger = logging.getLogger(__name__)


class ProverBackendMixin:
    """
    Mixin providing per-prover execution and consistency-check methods.

    Expects the host class to provide:
        - self.temp_dir (Path)
        - self.timeout (int)
        - self._prover_cmd(prover: str) -> str
    """

    def _execute_z3_proof(self, formula: DeonticFormula,
                          translation: TranslationResult) -> ProofResult:
        """Execute proof using Z3 SMT solver."""
        start_time = time.time()

        smt_content = f"""
; Deontic logic axioms
(declare-sort Agent 0)
(declare-sort Proposition 0)

; Deontic operators
(declare-fun Obligatory (Agent Proposition) Bool)
(declare-fun Permitted (Agent Proposition) Bool)
(declare-fun Forbidden (Agent Proposition) Bool)

; Consistency axioms
(assert (forall ((a Agent) (p Proposition)) 
    (not (and (Obligatory a p) (Forbidden a p)))))
(assert (forall ((a Agent) (p Proposition))
    (=> (Obligatory a p) (Permitted a p))))

; Formula to prove/check
{translation.translated_formula}

; Check satisfiability
(check-sat)
(get-model)
"""

        smt_file = self.temp_dir / f"formula_{formula.formula_id}.smt2"
        smt_file.write_text(smt_content)

        try:
            result = subprocess.run(
                [self._prover_cmd('z3'), str(smt_file)],
                capture_output=True,
                text=True,
                timeout=self.timeout
            )

            execution_time = time.time() - start_time

            if result.returncode == 0:
                output = result.stdout.strip()
                if "sat" in output.lower():
                    status = ProofStatus.SUCCESS
                elif "unsat" in output.lower():
                    status = ProofStatus.SUCCESS
                else:
                    status = ProofStatus.FAILURE

                return ProofResult(
                    prover="z3",
                    statement=formula.to_fol_string(),
                    status=status,
                    proof_output=output,
                    execution_time=execution_time,
                    metadata={"smt_file": str(smt_file)}
                )
            else:
                return ProofResult(
                    prover="z3",
                    statement=formula.to_fol_string(),
                    status=ProofStatus.ERROR,
                    execution_time=execution_time,
                    errors=[result.stderr]
                )

        except subprocess.TimeoutExpired:
            return ProofResult(
                prover="z3",
                statement=formula.to_fol_string(),
                status=ProofStatus.TIMEOUT,
                execution_time=self.timeout,
                errors=["Execution timeout"]
            )
        except Exception as e:
            return ProofResult(
                prover="z3",
                statement=formula.to_fol_string(),
                status=ProofStatus.ERROR,
                errors=[str(e)]
            )

    def _execute_cvc5_proof(self, formula: DeonticFormula,
                            translation: TranslationResult) -> ProofResult:
        """Execute proof using CVC5 SMT solver."""
        start_time = time.time()

        smt_content = f"""
(set-logic ALL)

; Deontic logic sorts and functions
(declare-sort Agent 0)
(declare-sort Proposition 0)

(declare-fun Obligatory (Agent Proposition) Bool)
(declare-fun Permitted (Agent Proposition) Bool)
(declare-fun Forbidden (Agent Proposition) Bool)

; Deontic logic axioms
(assert (forall ((a Agent) (p Proposition)) 
    (not (and (Obligatory a p) (Forbidden a p)))))
(assert (forall ((a Agent) (p Proposition))
    (=> (Obligatory a p) (Permitted a p))))

; Formula to verify
{translation.translated_formula}

(check-sat)
"""

        smt_file = self.temp_dir / f"formula_{formula.formula_id}_cvc5.smt2"
        smt_file.write_text(smt_content)

        try:
            result = subprocess.run(
                [self._prover_cmd('cvc5'), str(smt_file)],
                capture_output=True,
                text=True,
                timeout=self.timeout
            )

            execution_time = time.time() - start_time

            if result.returncode == 0:
                output = result.stdout.strip()
                status = ProofStatus.SUCCESS if "sat" in output.lower() or "unsat" in output.lower() else ProofStatus.FAILURE

                return ProofResult(
                    prover="cvc5",
                    statement=formula.to_fol_string(),
                    status=status,
                    proof_output=output,
                    execution_time=execution_time,
                    metadata={"smt_file": str(smt_file)}
                )
            else:
                return ProofResult(
                    prover="cvc5",
                    statement=formula.to_fol_string(),
                    status=ProofStatus.ERROR,
                    execution_time=execution_time,
                    errors=[result.stderr]
                )

        except subprocess.TimeoutExpired:
            return ProofResult(
                prover="cvc5",
                statement=formula.to_fol_string(),
                status=ProofStatus.TIMEOUT,
                execution_time=self.timeout,
                errors=["Execution timeout"]
            )
        except Exception as e:
            return ProofResult(
                prover="cvc5",
                statement=formula.to_fol_string(),
                status=ProofStatus.ERROR,
                errors=[str(e)]
            )

    def _execute_lean_proof(self, formula: DeonticFormula,
                            translation: TranslationResult) -> ProofResult:
        """Execute proof using Lean 4."""
        start_time = time.time()

        proposition_id = None
        try:
            proposition_id = (translation.metadata or {}).get("proposition_id")
        except (AttributeError, TypeError, KeyError) as e:
            logger.debug(f"Could not extract proposition_id from metadata: {e}")
            proposition_id = None
        proposition_id = str(proposition_id or "P")

        lean_content = f"""
-- Deontic logic proof smoke (core Lean only)
set_option autoImplicit false

-- Deontic operators
def Obligatory (P : Prop) : Prop := P
def Permitted (P : Prop) : Prop := ¬¬P
def Forbidden (P : Prop) : Prop := ¬P

-- A proposition constant for this run
axiom {proposition_id} : Prop

-- Statement to verify (type-check)
def statement : Prop := {translation.translated_formula}

-- Consistency check
theorem deontic_consistency (P : Prop) : ¬(Obligatory P ∧ Forbidden P) := by
    intro h
    exact h.right h.left

#check statement
#check deontic_consistency
"""

        lean_file = self.temp_dir / f"formula_{formula.formula_id}.lean"
        lean_file.write_text(lean_content)

        try:
            result = subprocess.run(
                [self._prover_cmd('lean'), str(lean_file)],
                capture_output=True,
                text=True,
                timeout=self.timeout
            )

            execution_time = time.time() - start_time

            if result.returncode == 0:
                return ProofResult(
                    prover="lean",
                    statement=formula.to_fol_string(),
                    status=ProofStatus.SUCCESS,
                    proof_output=result.stdout,
                    execution_time=execution_time,
                    metadata={"lean_file": str(lean_file)}
                )
            else:
                return ProofResult(
                    prover="lean",
                    statement=formula.to_fol_string(),
                    status=ProofStatus.ERROR,
                    execution_time=execution_time,
                    errors=[result.stderr],
                    proof_output=result.stdout
                )

        except subprocess.TimeoutExpired:
            return ProofResult(
                prover="lean",
                statement=formula.to_fol_string(),
                status=ProofStatus.TIMEOUT,
                execution_time=self.timeout,
                errors=["Execution timeout"]
            )
        except Exception as e:
            return ProofResult(
                prover="lean",
                statement=formula.to_fol_string(),
                status=ProofStatus.ERROR,
                errors=[str(e)]
            )

    def _execute_coq_proof(self, formula: DeonticFormula,
                           translation: TranslationResult) -> ProofResult:
        """Execute proof using Coq."""
        start_time = time.time()

        coq_content = f"""
(* Deontic Logic Theory *)

Parameter Agent : Type.
Parameter Proposition : Type.

Definition Obligatory (a : Agent) (P : Proposition) : Prop := True.
Definition Permitted (a : Agent) (P : Proposition) : Prop := True.
Definition Forbidden (a : Agent) (P : Proposition) : Prop := False.

(* Consistency axiom *)
Axiom deontic_consistency : forall (a : Agent) (P : Proposition),
  ~(Obligatory a P /\\ Forbidden a P).

(* Statement to verify *)
{translation.translated_formula}

(* Basic theorem *)
Theorem example_consistency : forall (a : Agent) (P : Proposition),
  Obligatory a P -> Permitted a P.
Proof.
  intros a P H.
  exact I.
Qed.
"""

        coq_file = self.temp_dir / f"formula_{formula.formula_id}.v"
        coq_file.write_text(coq_content)

        try:
            result = subprocess.run(
                [self._prover_cmd('coq'), str(coq_file)],
                capture_output=True,
                text=True,
                timeout=self.timeout
            )

            execution_time = time.time() - start_time

            if result.returncode == 0:
                return ProofResult(
                    prover="coq",
                    statement=formula.to_fol_string(),
                    status=ProofStatus.SUCCESS,
                    proof_output=result.stdout,
                    execution_time=execution_time,
                    metadata={"coq_file": str(coq_file)}
                )
            else:
                return ProofResult(
                    prover="coq",
                    statement=formula.to_fol_string(),
                    status=ProofStatus.ERROR,
                    execution_time=execution_time,
                    errors=[result.stderr],
                    proof_output=result.stdout
                )

        except subprocess.TimeoutExpired:
            return ProofResult(
                prover="coq",
                statement=formula.to_fol_string(),
                status=ProofStatus.TIMEOUT,
                execution_time=self.timeout,
                errors=["Execution timeout"]
            )
        except Exception as e:
            return ProofResult(
                prover="coq",
                statement=formula.to_fol_string(),
                status=ProofStatus.ERROR,
                errors=[str(e)]
            )

    def _check_z3_consistency(self, rule_set: DeonticRuleSet, start_time: float) -> ProofResult:
        """Check consistency using Z3."""
        translator = SMTTranslator()

        smt_content = """
; Deontic logic consistency check
(declare-sort Agent 0)
(declare-sort Proposition 0)

(declare-fun Obligatory (Agent Proposition) Bool)
(declare-fun Permitted (Agent Proposition) Bool)
(declare-fun Forbidden (Agent Proposition) Bool)

; Consistency axioms
(assert (forall ((a Agent) (p Proposition)) 
    (not (and (Obligatory a p) (Forbidden a p)))))
(assert (forall ((a Agent) (p Proposition))
    (=> (Obligatory a p) (Permitted a p))))

"""

        for formula in rule_set.formulas:
            translation_result = translator.translate_deontic_formula(formula)
            if translation_result.success:
                smt_content += f"; {formula.source_text[:50]}...\n"
                smt_content += f"(assert {translation_result.translated_formula})\n\n"

        smt_content += "(check-sat)\n"

        smt_file = self.temp_dir / f"consistency_{rule_set.name}.smt2"
        smt_file.write_text(smt_content)

        try:
            result = subprocess.run(
                [self._prover_cmd('z3'), str(smt_file)],
                capture_output=True,
                text=True,
                timeout=self.timeout
            )

            execution_time = time.time() - start_time

            if result.returncode == 0:
                output = result.stdout.strip()
                if "sat" in output.lower():
                    status = ProofStatus.SUCCESS
                    message = "Rule set is consistent (satisfiable)"
                elif "unsat" in output.lower():
                    status = ProofStatus.FAILURE
                    message = "Rule set is inconsistent (unsatisfiable)"
                else:
                    status = ProofStatus.ERROR
                    message = f"Unexpected Z3 output: {output}"

                return ProofResult(
                    prover="z3",
                    statement=f"Consistency of {len(rule_set.formulas)} formulas",
                    status=status,
                    proof_output=f"{message}\n\nZ3 output:\n{output}",
                    execution_time=execution_time,
                    metadata={"smt_file": str(smt_file), "formula_count": len(rule_set.formulas)}
                )
            else:
                return ProofResult(
                    prover="z3",
                    statement=f"Consistency of {len(rule_set.formulas)} formulas",
                    status=ProofStatus.ERROR,
                    execution_time=execution_time,
                    errors=[result.stderr]
                )

        except subprocess.TimeoutExpired:
            return ProofResult(
                prover="z3",
                statement=f"Consistency of {len(rule_set.formulas)} formulas",
                status=ProofStatus.TIMEOUT,
                execution_time=self.timeout,
                errors=["Execution timeout"]
            )
        except Exception as e:
            return ProofResult(
                prover="z3",
                statement=f"Consistency of {len(rule_set.formulas)} formulas",
                status=ProofStatus.ERROR,
                errors=[str(e)]
            )

    def _check_cvc5_consistency(self, rule_set: DeonticRuleSet, start_time: float) -> ProofResult:
        """Check consistency using CVC5."""
        translator = SMTTranslator()

        smt_content = """
(set-logic ALL)

; Deontic logic sorts and functions
(declare-sort Agent 0)
(declare-sort Proposition 0)

(declare-fun Obligatory (Agent Proposition) Bool)
(declare-fun Permitted (Agent Proposition) Bool)
(declare-fun Forbidden (Agent Proposition) Bool)

; Consistency axioms
(assert (forall ((a Agent) (p Proposition)) 
    (not (and (Obligatory a p) (Forbidden a p)))))

"""

        for formula in rule_set.formulas:
            translation_result = translator.translate_deontic_formula(formula)
            if translation_result.success:
                smt_content += f"; {formula.source_text[:50]}...\n"
                smt_content += f"(assert {translation_result.translated_formula})\n\n"

        smt_content += "(check-sat)\n"

        smt_file = self.temp_dir / f"consistency_cvc5_{rule_set.name}.smt2"
        smt_file.write_text(smt_content)

        try:
            result = subprocess.run(
                [self._prover_cmd('cvc5'), str(smt_file)],
                capture_output=True,
                text=True,
                timeout=self.timeout
            )

            execution_time = time.time() - start_time

            if result.returncode == 0:
                output = result.stdout.strip()
                if "sat" in output.lower():
                    status = ProofStatus.SUCCESS
                elif "unsat" in output.lower():
                    status = ProofStatus.FAILURE
                else:
                    status = ProofStatus.ERROR

                return ProofResult(
                    prover="cvc5",
                    statement=f"Consistency of {len(rule_set.formulas)} formulas",
                    status=status,
                    proof_output=output,
                    execution_time=execution_time,
                    metadata={"smt_file": str(smt_file)}
                )
            else:
                return ProofResult(
                    prover="cvc5",
                    statement=f"Consistency of {len(rule_set.formulas)} formulas",
                    status=ProofStatus.ERROR,
                    execution_time=execution_time,
                    errors=[result.stderr]
                )

        except subprocess.TimeoutExpired:
            return ProofResult(
                prover="cvc5",
                statement=f"Consistency of {len(rule_set.formulas)} formulas",
                status=ProofStatus.TIMEOUT,
                execution_time=self.timeout,
                errors=["Execution timeout"]
            )
        except Exception as e:
            return ProofResult(
                prover="cvc5",
                statement=f"Consistency of {len(rule_set.formulas)} formulas",
                status=ProofStatus.ERROR,
                errors=[str(e)]
            )
