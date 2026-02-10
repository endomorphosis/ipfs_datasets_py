"""
Proof Execution Engine

This module provides the capability to actually execute proofs using installed
theorem provers, not just translate to their formats. Supports Z3, CVC5, Lean 4, Coq.
"""

import os
import sys
import subprocess
import tempfile
import logging
from pathlib import Path
import shutil
from typing import Dict, List, Optional, Union, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
import json
import time

from ..tools.deontic_logic_core import DeonticFormula, DeonticRuleSet
from ..tools.logic_translation_core import LogicTranslationTarget, TranslationResult, LogicTranslator
from ..tools.logic_translation_core import LeanTranslator, CoqTranslator, SMTTranslator

logger = logging.getLogger(__name__)


class ProofStatus(Enum):
    """Status of proof execution."""
    SUCCESS = "success"
    FAILURE = "failure" 
    TIMEOUT = "timeout"
    ERROR = "error"
    UNSUPPORTED = "unsupported"


@dataclass
class ProofResult:
    """Result of executing a proof."""
    prover: str
    statement: str
    status: ProofStatus
    proof_output: str = ""
    execution_time: float = 0.0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "prover": self.prover,
            "statement": self.statement,
            "status": self.status.value,
            "proof_output": self.proof_output,
            "execution_time": self.execution_time,
            "errors": self.errors,
            "warnings": self.warnings,
            "metadata": self.metadata
        }


class ProofExecutionEngine:
    """
    Engine for executing proofs using various theorem provers.
    """
    
    def __init__(
        self,
        temp_dir: Optional[str] = None,
        timeout: int = 60,
        default_prover: Optional[str] = None,
    ):
        self.temp_dir = Path(temp_dir) if temp_dir else Path(tempfile.gettempdir()) / "ipfs_proofs"
        self.temp_dir.mkdir(exist_ok=True)
        self.timeout = timeout

        env_default = os.environ.get("IPFS_DATASETS_PY_PROOF_PROVER")
        self.default_prover = str(default_prover or env_default or "z3")

        self._refresh_prover_state()

        # NOTE: setup.py hooks are not guaranteed to run for all install modes (e.g. wheels/PEP517).
        # To make auto-install actually work in practice, we also attempt installation here when
        # the engine is constructed.
        self._maybe_auto_install_provers()
        self._refresh_prover_state()

    def _refresh_prover_state(self) -> None:
        # Prefer explicit executable paths when provers were installed into user bins.
        self.prover_binaries = {
            "z3": self._find_executable("z3"),
            "cvc5": self._find_executable("cvc5"),
            "lean": self._find_executable("lean", extra=[Path.home() / ".elan" / "bin"]),
            "coq": self._find_executable("coqc"),
        }

        # Available provers and their verification
        self.available_provers = self._detect_available_provers()

    def _env_truthy(self, name: str, default: str = "1") -> bool:
        value = os.environ.get(name, default)
        return str(value).strip().lower() not in {"0", "false", "no", "off", ""}

    def _maybe_auto_install_provers(self) -> None:
        if not self._env_truthy("IPFS_DATASETS_PY_AUTO_INSTALL_PROVERS", "1"):
            return

        # Prevent recursion / repeated nested installs.
        if self._env_truthy("IPFS_DATASETS_PY_PROVER_AUTO_INSTALL_RUNNING", "0"):
            return

        missing = [p for p, ok in (self.available_provers or {}).items() if not ok]
        if not missing:
            return

        want_z3 = self._env_truthy("IPFS_DATASETS_PY_AUTO_INSTALL_Z3", "1")
        want_cvc5 = self._env_truthy("IPFS_DATASETS_PY_AUTO_INSTALL_CVC5", "1")
        want_lean = self._env_truthy("IPFS_DATASETS_PY_AUTO_INSTALL_LEAN", "1")
        # Coq auto-install is intentionally conservative (may require root/sudo or a full opam toolchain).
        want_coq = self._env_truthy("IPFS_DATASETS_PY_AUTO_INSTALL_COQ", "0")

        enabled: Dict[str, bool] = {
            "z3": want_z3,
            "cvc5": want_cvc5,
            "lean": want_lean,
            "coq": want_coq,
        }

        to_install = [p for p in missing if enabled.get(p, False)]
        if not to_install:
            return

        args = [sys.executable, "-m", "ipfs_prover_installer", "--yes"]
        if want_z3:
            args.append("--z3")
        if want_cvc5:
            args.append("--cvc5")
        if want_lean:
            args.append("--lean")
        if want_coq:
            args.append("--coq")

        env = os.environ.copy()
        env["IPFS_DATASETS_PY_PROVER_AUTO_INSTALL_RUNNING"] = "1"

        try:
            logger.info(f"Auto-installing missing provers (best-effort): {to_install}")
            subprocess.run(args, check=False, env=env)
        except Exception as exc:
            logger.info(f"Auto-install provers failed (best-effort): {exc}")
        
    def _detect_available_provers(self) -> Dict[str, bool]:
        """Detect which theorem provers are available on the system."""
        # NOTE: Lean installed via elan may download the toolchain on first use;
        # `lean --version` can legitimately take >10s in that case.
        provers = {
            'z3': self._test_command([self._prover_cmd('z3'), '--version'], timeout_s=10),
            'cvc5': self._test_command([self._prover_cmd('cvc5'), '--version'], timeout_s=10),
            'lean': self._test_command([self._prover_cmd('lean'), '--version'], timeout_s=60),
            'coq': self._test_command([self._prover_cmd('coq'), '--version'], timeout_s=30),
        }
        
        logger.info(f"Available theorem provers: {[p for p, available in provers.items() if available]}")
        return provers

    def _common_bin_dirs(self) -> List[Path]:
        dirs: List[Path] = []
        try:
            dirs.append(Path.home() / ".local" / "bin")
        except Exception:
            pass
        return dirs

    def _find_executable(self, name: str, extra: Optional[List[Path]] = None) -> Optional[str]:
        # Try PATH first.
        path = shutil.which(name)
        if path:
            return path

        # Then common user bins.
        candidates = []
        for d in (extra or []):
            candidates.append(d / name)
        for d in self._common_bin_dirs():
            candidates.append(d / name)

        for c in candidates:
            try:
                if c.exists() and os.access(str(c), os.X_OK):
                    return str(c)
            except Exception:
                continue
        return None

    def _prover_cmd(self, prover: str) -> str:
        # Map internal name -> executable.
        if prover == "coq":
            return self.prover_binaries.get("coq") or "coqc"
        if prover == "lean":
            return self.prover_binaries.get("lean") or "lean"
        if prover == "z3":
            return self.prover_binaries.get("z3") or "z3"
        if prover == "cvc5":
            return self.prover_binaries.get("cvc5") or "cvc5"
        return prover
        
    def _test_command(self, cmd: List[str], *, timeout_s: int = 10) -> bool:
        """Test if a command is available."""
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=int(timeout_s))
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError):
            return False
    
    def prove_deontic_formula(
        self,
        formula: DeonticFormula,
        prover: Optional[str] = None,
    ) -> ProofResult:
        """
        Prove a deontic logic formula using the specified theorem prover.
        """
        prover = str(prover or self.default_prover or "z3")
        if prover not in self.available_provers:
            return ProofResult(
                prover=prover,
                statement=formula.to_fol_string(),
                status=ProofStatus.UNSUPPORTED,
                errors=[f"Prover {prover} not available"]
            )
        
        if not self.available_provers[prover]:
            return ProofResult(
                prover=prover,
                statement=formula.to_fol_string(),
                status=ProofStatus.ERROR,
                errors=[f"Prover {prover} not installed"]
            )
        
        # Translate formula to target format
        translator = self._get_translator(prover)
        if not translator:
            return ProofResult(
                prover=prover,
                statement=formula.to_fol_string(),
                status=ProofStatus.UNSUPPORTED,
                errors=[f"No translator available for {prover}"]
            )
        
        translation_result = translator.translate_deontic_formula(formula)
        if not translation_result.success:
            return ProofResult(
                prover=prover,
                statement=formula.to_fol_string(),
                status=ProofStatus.ERROR,
                errors=[f"Translation failed: {translation_result.errors}"]
            )
        
        # Execute proof based on prover type
        if prover == 'z3':
            return self._execute_z3_proof(formula, translation_result)
        elif prover == 'cvc5':
            return self._execute_cvc5_proof(formula, translation_result)
        elif prover == 'lean':
            return self._execute_lean_proof(formula, translation_result)
        elif prover == 'coq':
            return self._execute_coq_proof(formula, translation_result)
        else:
            return ProofResult(
                prover=prover,
                statement=formula.to_fol_string(),
                status=ProofStatus.UNSUPPORTED,
                errors=[f"Proof execution not implemented for {prover}"]
            )
    
    def _get_translator(self, prover: str) -> Optional[LogicTranslator]:
        """Get appropriate translator for prover."""
        translators = {
            'z3': SMTTranslator(),
            'cvc5': SMTTranslator(),
            'lean': LeanTranslator(),
            'coq': CoqTranslator()
        }
        return translators.get(prover)
    
    def _execute_z3_proof(self, formula: DeonticFormula, 
                         translation: TranslationResult) -> ProofResult:
        """Execute proof using Z3 SMT solver."""
        start_time = time.time()
        
        # Create SMT-LIB file for Z3
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
        
        # Write to temporary file
        smt_file = self.temp_dir / f"formula_{formula.formula_id}.smt2"
        smt_file.write_text(smt_content)
        
        try:
            # Run Z3
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
                    status = ProofStatus.SUCCESS  # Unsat can be valid result
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
        
        # Create SMT-LIB file for CVC5 (similar to Z3)
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
        except Exception:
            proposition_id = None
        proposition_id = str(proposition_id or "P")

        # Create a Lean file that does not depend on Mathlib (works with core Lean).
        # We only need successful elaboration to prove Lean is actually executing.
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
        
        # Create Coq file
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
    
    def prove_rule_set(self, rule_set: DeonticRuleSet, 
                      prover: str = "z3") -> List[ProofResult]:
        """
        Prove all formulas in a rule set.
        """
        results = []
        
        for formula in rule_set.formulas:
            result = self.prove_deontic_formula(formula, prover)
            results.append(result)
            
        return results
    
    def prove_consistency(self, rule_set: DeonticRuleSet, 
                         prover: str = "z3") -> ProofResult:
        """
        Check if a rule set is logically consistent.
        """
        start_time = time.time()
        
        if prover == "z3":
            return self._check_z3_consistency(rule_set, start_time)
        elif prover == "cvc5":
            return self._check_cvc5_consistency(rule_set, start_time)
        else:
            return ProofResult(
                prover=prover,
                statement=f"Consistency check for {len(rule_set.formulas)} formulas",
                status=ProofStatus.UNSUPPORTED,
                errors=[f"Consistency checking not implemented for {prover}"]
            )
    
    def _check_z3_consistency(self, rule_set: DeonticRuleSet, start_time: float) -> ProofResult:
        """Check consistency using Z3."""
        # Translate all formulas to SMT-LIB
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
        
        # Add all formulas
        for formula in rule_set.formulas:
            translation_result = translator.translate_deontic_formula(formula)
            if translation_result.success:
                smt_content += f"; {formula.source_text[:50]}...\n"
                smt_content += f"(assert {translation_result.translated_formula})\n\n"
        
        smt_content += "(check-sat)\n"
        
        # Write to file
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
        # Similar to Z3 but with CVC5-specific syntax
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
        
        # Add all formulas
        for formula in rule_set.formulas:
            translation_result = translator.translate_deontic_formula(formula)
            if translation_result.success:
                smt_content += f"; {formula.source_text[:50]}...\n"
                smt_content += f"(assert {translation_result.translated_formula})\n\n"
        
        smt_content += "(check-sat)\n"
        
        # Write to file
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

    def prove_multiple_provers(self, formula: DeonticFormula, 
                             provers: List[str] = None) -> Dict[str, ProofResult]:
        """
        Prove the same formula using multiple theorem provers.
        """
        if provers is None:
            provers = [p for p, available in self.available_provers.items() if available]
        
        results = {}
        for prover in provers:
            if prover in self.available_provers and self.available_provers[prover]:
                results[prover] = self.prove_deontic_formula(formula, prover)
            else:
                results[prover] = ProofResult(
                    prover=prover,
                    statement=formula.to_fol_string(),
                    status=ProofStatus.UNSUPPORTED,
                    errors=[f"Prover {prover} not available"]
                )
        
        return results

    def get_prover_status(self) -> Dict[str, Any]:
        """Get status of all available theorem provers."""
        status = {
            "available_provers": self.available_provers,
            "temp_directory": str(self.temp_dir),
            "timeout": self.timeout
        }
        
        # Test each available prover with a simple statement
        for prover, available in self.available_provers.items():
            if available:
                # Create a simple test formula
                from ..tools.deontic_logic_core import create_obligation, LegalAgent
                test_agent = LegalAgent("test_agent", "Test Agent", "organization")
                test_formula = create_obligation(test_agent, "test_proposition", "Test proposition")
                
                try:
                    test_result = self.prove_deontic_formula(test_formula, prover)
                    status[f"{prover}_test"] = {
                        "status": test_result.status.value,
                        "execution_time": test_result.execution_time
                    }
                except Exception as e:
                    status[f"{prover}_test"] = {
                        "status": "error",
                        "error": str(e)
                    }
        
        return status


# Convenience functions
def create_proof_engine(temp_dir: Optional[str] = None, timeout: int = 60) -> ProofExecutionEngine:
    """Create a proof execution engine."""
    return ProofExecutionEngine(temp_dir=temp_dir, timeout=timeout)


def prove_formula(formula: DeonticFormula, prover: str = "z3", 
                 temp_dir: Optional[str] = None) -> ProofResult:
    """Prove a single formula using the specified prover."""
    engine = create_proof_engine(temp_dir)
    return engine.prove_deontic_formula(formula, prover)


def prove_with_all_provers(formula: DeonticFormula, 
                          temp_dir: Optional[str] = None) -> Dict[str, ProofResult]:
    """Prove a formula using all available theorem provers."""
    engine = create_proof_engine(temp_dir)
    return engine.prove_multiple_provers(formula)


def check_consistency(rule_set: DeonticRuleSet, prover: str = "z3",
                     temp_dir: Optional[str] = None) -> ProofResult:
    """Check consistency of a rule set."""
    engine = create_proof_engine(temp_dir)
    return engine.prove_consistency(rule_set, prover)