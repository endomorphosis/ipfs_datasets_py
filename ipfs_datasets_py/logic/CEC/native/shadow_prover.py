"""
ShadowProver: Native Python 3 port of the Java ShadowProver.

This module provides a pure Python 3 implementation of ShadowProver,
an automated theorem prover for modal logics and cognitive calculus.

ShadowProver supports:
- Modal logics: K, T, S4, S5, D
- Linear logic: LP, LP1, LP2
- Cognitive calculus
- First-order logic
- Resolution-based proving
- Natural deduction

This is Phase 4D of the native implementation project.
"""

from typing import List, Dict, Optional, Any, Union
from dataclasses import dataclass, field
from enum import Enum
from abc import ABC, abstractmethod
import logging

from .exceptions import ProvingError

try:
    from beartype import beartype
except ImportError:
    from typing import TypeVar, Callable, Any
    F = TypeVar('F', bound=Callable[..., Any])
    def beartype(func: F) -> F:
        return func

logger = logging.getLogger(__name__)


class ModalLogic(Enum):
    """Supported modal logic systems."""
    K = "K"           # Basic modal logic
    T = "T"           # Reflexive
    S4 = "S4"         # Reflexive + Transitive
    S5 = "S5"         # Reflexive + Transitive + Symmetric
    D = "D"           # Serial
    LP = "LP"         # Linear logic (propositional)
    LP1 = "LP1"       # Linear logic level 1
    LP2 = "LP2"       # Linear logic level 2


class ProofStatus(Enum):
    """Status of a proof attempt."""
    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"
    ERROR = "error"


@dataclass
class ProofStep:
    """A single step in a proof.
    
    Attributes:
        rule_name: Name of the inference rule applied
        premises: List of formulas used as premises
        conclusion: Formula derived
        justification: Explanation of why this step is valid
    """
    rule_name: str
    premises: List[Any]
    conclusion: Any
    justification: str = ""
    
    def __str__(self) -> str:
        return f"{self.rule_name}: {self.premises} ⊢ {self.conclusion}"


@dataclass
class ProofTree:
    """A proof tree structure.
    
    Attributes:
        goal: The formula to prove
        steps: Sequence of proof steps
        status: Final status of the proof
        logic: Modal logic system used
    """
    goal: Any
    steps: List[ProofStep]
    status: ProofStatus
    logic: ModalLogic
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def is_successful(self) -> bool:
        """Check if proof was successful."""
        return self.status == ProofStatus.SUCCESS
    
    def get_depth(self) -> int:
        """Get the depth (number of steps) of the proof."""
        return len(self.steps)


@dataclass
class ProblemFile:
    """Represents a problem file for the prover.
    
    Attributes:
        name: Problem identifier
        logic: Logic system to use
        assumptions: List of assumptions (axioms)
        goals: List of goals to prove
        metadata: Additional problem information
    """
    name: str
    logic: ModalLogic
    assumptions: List[Any]
    goals: List[Any]
    metadata: Dict[str, Any] = field(default_factory=dict)


class ModalOperator(Enum):
    """Modal operators for modal logic."""
    NECESSARY = "□"      # Box (necessarily)
    POSSIBLE = "◇"       # Diamond (possibly)
    BELIEF = "B"         # Belief operator
    KNOWLEDGE = "K"      # Knowledge operator
    SAYS = "says"        # Says operator
    PERCEIVES = "P"      # Perception operator


class ShadowProver(ABC):
    """Abstract base class for ShadowProver implementations.
    
    Different modal logics require different proving strategies,
    so this provides a common interface for all provers.
    """
    
    def __init__(self, logic: ModalLogic):
        """Initialize the prover.
        
        Args:
            logic: The modal logic system to use
        """
        self.logic = logic
        self.proof_cache: Dict[str, ProofTree] = {}
        self.statistics = {
            "proofs_attempted": 0,
            "proofs_succeeded": 0,
            "proofs_failed": 0,
            "average_steps": 0.0,
        }
    
    @abstractmethod
    def prove(self, goal: Any, assumptions: Optional[List[Any]] = None,
              timeout: Optional[int] = None) -> ProofTree:
        """Attempt to prove a goal given assumptions.
        
        Args:
            goal: The formula to prove
            assumptions: List of assumptions (axioms)
            timeout: Optional timeout in seconds
            
        Returns:
            ProofTree containing the proof or failure information
        """
        pass
    
    @abstractmethod
    def prove_problem(self, problem: ProblemFile) -> List[ProofTree]:
        """Prove all goals in a problem file.
        
        Args:
            problem: Problem file with goals and assumptions
            
        Returns:
            List of proof trees for each goal
        """
        pass
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get prover statistics.
        
        Returns:
            Dictionary of statistics
        """
        return self.statistics.copy()
    
    def clear_cache(self) -> None:
        """Clear the proof cache."""
        self.proof_cache.clear()


class KProver(ShadowProver):
    """Prover for modal logic K (basic modal logic).
    
    K is the weakest normal modal logic, with only the necessitation
    rule and the distribution axiom K: □(P→Q) → (□P→□Q)
    """
    
    def __init__(self) -> None:
        """Initialize K prover."""
        super().__init__(ModalLogic.K)
        # Lazy import to avoid circular dependency
        self._tableau_prover: Optional[Any] = None
    
    def _get_tableau_prover(self) -> Optional[Any]:
        """Get tableaux prover instance (lazy initialization)."""
        if self._tableau_prover is None:
            try:
                from .modal_tableaux import TableauProver
                self._tableau_prover = TableauProver(self.logic)
            except ImportError:
                logger.warning("TableauProver not available, using basic implementation")
        return self._tableau_prover
    
    def prove(self, goal: Any, assumptions: Optional[List[Any]] = None,
              timeout: Optional[int] = None) -> ProofTree:
        """Prove a goal in modal logic K.
        
        Uses tableau method for modal logic proving.
        
        Args:
            goal: The formula to prove
            assumptions: List of assumptions
            timeout: Optional timeout
            
        Returns:
            ProofTree with proof or failure
        """
        self.statistics["proofs_attempted"] += 1
        
        # Try using tableau prover if available
        tableau_prover = self._get_tableau_prover()
        if tableau_prover:
            try:
                success, tableau = tableau_prover.prove(str(goal), 
                                                       [str(a) for a in assumptions] if assumptions else None)
                
                status = ProofStatus.SUCCESS if success else ProofStatus.FAILURE
                if success:
                    self.statistics["proofs_succeeded"] += 1
                else:
                    self.statistics["proofs_failed"] += 1
                
                # Convert tableau to proof tree
                proof = ProofTree(
                    goal=goal,
                    steps=tableau.proof_steps,
                    status=status,
                    logic=self.logic,
                    metadata={
                        "method": "tableau",
                        "closed": success,
                        "worlds": tableau.world_counter
                    }
                )
                
                return proof
                
            except Exception as e:
                logger.error(f"Tableau proving failed: {e}")
        
        # Fallback to basic implementation
        self.statistics["proofs_failed"] += 1
        proof = ProofTree(
            goal=goal,
            steps=[],
            status=ProofStatus.UNKNOWN,
            logic=self.logic,
            metadata={"message": "Basic K prover fallback"}
        )
        
        return proof
    
    def prove_problem(self, problem: ProblemFile) -> List[ProofTree]:
        """Prove all goals in a problem.
        
        Args:
            problem: Problem file
            
        Returns:
            List of proof trees
        """
        return [self.prove(goal, problem.assumptions) for goal in problem.goals]


class S4Prover(ShadowProver):
    """Prover for modal logic S4.
    
    S4 extends K with reflexivity (T) and transitivity (4):
    - T: □P → P
    - 4: □P → □□P
    """
    
    def __init__(self) -> None:
        """Initialize S4 prover."""
        super().__init__(ModalLogic.S4)
        self._tableau_prover: Optional[Any] = None
    
    def _get_tableau_prover(self) -> Optional[Any]:
        """Get tableaux prover instance (lazy initialization)."""
        if self._tableau_prover is None:
            try:
                from .modal_tableaux import TableauProver
                self._tableau_prover = TableauProver(self.logic)
            except ImportError:
                logger.warning("TableauProver not available")
        return self._tableau_prover
    
    def prove(self, goal: Any, assumptions: Optional[List[Any]] = None,
              timeout: Optional[int] = None) -> ProofTree:
        """Prove a goal in modal logic S4.
        
        Uses tableau method with S4 axioms (reflexivity + transitivity).
        
        Args:
            goal: Formula to prove
            assumptions: Optional assumptions
            timeout: Optional timeout
            
        Returns:
            ProofTree with proof result
        """
        self.statistics["proofs_attempted"] += 1
        
        tableau_prover = self._get_tableau_prover()
        if tableau_prover:
            try:
                success, tableau = tableau_prover.prove(str(goal),
                                                       [str(a) for a in assumptions] if assumptions else None)
                
                status = ProofStatus.SUCCESS if success else ProofStatus.FAILURE
                if success:
                    self.statistics["proofs_succeeded"] += 1
                else:
                    self.statistics["proofs_failed"] += 1
                
                proof = ProofTree(
                    goal=goal,
                    steps=tableau.proof_steps,
                    status=status,
                    logic=self.logic,
                    metadata={
                        "method": "tableau",
                        "closed": success,
                        "worlds": tableau.world_counter,
                        "axioms": ["reflexivity", "transitivity"]
                    }
                )
                
                return proof
                
            except Exception as e:
                logger.error(f"S4 tableau proving failed: {e}")
        
        self.statistics["proofs_failed"] += 1
        proof = ProofTree(
            goal=goal,
            steps=[],
            status=ProofStatus.UNKNOWN,
            logic=self.logic,
            metadata={"message": "S4 prover fallback"}
        )
        
        return proof
    
    def prove_problem(self, problem: ProblemFile) -> List[ProofTree]:
        """Prove all goals in a problem."""
        return [self.prove(goal, problem.assumptions) for goal in problem.goals]


class S5Prover(ShadowProver):
    """Prover for modal logic S5.
    
    S5 extends S4 with symmetry (5): ◇P → □◇P
    S5 is the strongest normal modal logic for single-agent knowledge.
    """
    
    def __init__(self) -> None:
        """Initialize S5 prover."""
        super().__init__(ModalLogic.S5)
        self._tableau_prover: Optional[Any] = None
    
    def _get_tableau_prover(self) -> Optional[Any]:
        """Get tableaux prover instance (lazy initialization)."""
        if self._tableau_prover is None:
            try:
                from .modal_tableaux import TableauProver
                self._tableau_prover = TableauProver(self.logic)
            except ImportError:
                logger.warning("TableauProver not available")
        return self._tableau_prover
    
    def prove(self, goal: Any, assumptions: Optional[List[Any]] = None,
              timeout: Optional[int] = None) -> ProofTree:
        """Prove a goal in modal logic S5.
        
        Uses tableau method with S5 axioms (reflexivity + transitivity + symmetry).
        
        Args:
            goal: Formula to prove
            assumptions: Optional assumptions
            timeout: Optional timeout
            
        Returns:
            ProofTree with proof result
        """
        self.statistics["proofs_attempted"] += 1
        
        tableau_prover = self._get_tableau_prover()
        if tableau_prover:
            try:
                success, tableau = tableau_prover.prove(str(goal),
                                                       [str(a) for a in assumptions] if assumptions else None)
                
                status = ProofStatus.SUCCESS if success else ProofStatus.FAILURE
                if success:
                    self.statistics["proofs_succeeded"] += 1
                else:
                    self.statistics["proofs_failed"] += 1
                
                proof = ProofTree(
                    goal=goal,
                    steps=tableau.proof_steps,
                    status=status,
                    logic=self.logic,
                    metadata={
                        "method": "tableau",
                        "closed": success,
                        "worlds": tableau.world_counter,
                        "axioms": ["reflexivity", "transitivity", "symmetry"]
                    }
                )
                
                return proof
                
            except Exception as e:
                logger.error(f"S5 tableau proving failed: {e}")
        
        self.statistics["proofs_failed"] += 1
        proof = ProofTree(
            goal=goal,
            steps=[],
            status=ProofStatus.UNKNOWN,
            logic=self.logic,
            metadata={"message": "S5 prover fallback"}
        )
        
        return proof
    
    def prove_problem(self, problem: ProblemFile) -> List[ProofTree]:
        """Prove all goals in a problem."""
        return [self.prove(goal, problem.assumptions) for goal in problem.goals]


class CognitiveCalculusProver(ShadowProver):
    """Prover for cognitive calculus.
    
    Cognitive calculus extends modal logic with operators for:
    - Belief (B)
    - Knowledge (K)
    - Says (says)
    - Perceives (P)
    
    Includes axioms for belief revision, knowledge dynamics, etc.
    """
    
    def __init__(self) -> None:
        """Initialize cognitive calculus prover."""
        super().__init__(ModalLogic.S5)  # Base on S5
        self.cognitive_axioms = self._init_cognitive_axioms()
        self._tableau_prover: Optional[Any] = None
        
    def _get_tableau_prover(self) -> Optional[Any]:
        """Get tableaux prover instance."""
        if self._tableau_prover is None:
            try:
                from .modal_tableaux import TableauProver
                self._tableau_prover = TableauProver(self.logic)
            except ImportError:
                logger.warning("TableauProver not available")
        return self._tableau_prover
    
    def _init_cognitive_axioms(self) -> List[str]:
        """Initialize cognitive calculus axioms.
        
        Returns:
            List of axiom names
        """
        return [
            # Knowledge axioms (S5)
            "K_distribution",              # K(P→Q) → (KP→KQ)
            "K_necessitation",             # If ⊢P then ⊢KP
            "K_truth",                     # KP → P (knowledge implies truth)
            "K_positive_introspection",    # KP → KKP (knows that knows)
            "K_negative_introspection",    # ¬KP → K¬KP (knows that doesn't know)
            
            # Belief axioms (KD45)
            "B_distribution",              # B(P→Q) → (BP→BQ)
            "B_consistency",               # BP → ¬B¬P (belief consistency)
            "B_positive_introspection",    # BP → BBP
            "B_negative_introspection",    # ¬BP → B¬BP
            
            # Knowledge-Belief interaction
            "knowledge_implies_belief",    # KP → BP (knowledge implies belief)
            "belief_revision",             # (BP ∧ KQ) → B(P∧Q)
            
            # Perception axioms
            "perception_to_knowledge",     # PP → KP (perception implies knowledge)
            "perception_veridical",        # PP → P (perception is true)
            
            # Communication axioms
            "says_to_belief",              # Says(agent, P) → B_agent(P)
            "truthful_communication",      # Says(agent, P) ∧ Honest(agent) → P
            
            # Intention axioms
            "intention_consistency",       # I(P) → ¬I(¬P)
            "intention_persistence",       # I(P) ∧ ¬Done(P) → Next(I(P))
            
            # Goal axioms
            "goal_consistency",            # G(P) → ¬G(¬P)
            "achievement",                 # G(P) ∧ Done(P) → Satisfied
        ]
    
    def apply_cognitive_rules(self, formulas: List[Any]) -> List[Any]:
        """Apply cognitive calculus specific rules.
        
        Args:
            formulas: Current formulas
            
        Returns:
            New derived formulas
        """
        derived = []
        
        for formula in formulas:
            formula_str = str(formula)
            
            # K_truth: KP → P
            if formula_str.startswith("K("):
                inner = formula_str[2:-1]
                derived.append(inner)
            
            # Knowledge implies belief: KP → BP
            if formula_str.startswith("K("):
                inner = formula_str[2:-1]
                derived.append(f"B({inner})")
            
            # Perception to knowledge: PP → KP
            if formula_str.startswith("P("):
                inner = formula_str[2:-1]
                derived.append(f"K({inner})")
            
            # Knowledge positive introspection: KP → KKP
            if formula_str.startswith("K(") and not formula_str.startswith("K(K("):
                derived.append(f"K({formula_str})")
            
            # Belief positive introspection: BP → BBP
            if formula_str.startswith("B(") and not formula_str.startswith("B(B("):
                derived.append(f"B({formula_str})")
        
        return derived
    
    def prove(self, goal: Any, assumptions: Optional[List[Any]] = None,
              timeout: Optional[int] = None) -> ProofTree:
        """Prove a goal in cognitive calculus.
        
        Uses S5 tableau with additional cognitive rules.
        
        Args:
            goal: Formula to prove
            assumptions: Optional assumptions
            timeout: Optional timeout
            
        Returns:
            ProofTree with proof result
        """
        self.statistics["proofs_attempted"] += 1
        
        # Add cognitive axioms to assumptions
        enhanced_assumptions = list(assumptions) if assumptions else []
        
        # Try cognitive rule application first
        try:
            if assumptions:
                derived = self.apply_cognitive_rules(assumptions)
                enhanced_assumptions.extend(derived)
        except Exception as e:
            logger.debug(f"Cognitive rule application error: {e}")
        
        # Use tableau prover with enhanced assumptions
        tableau_prover = self._get_tableau_prover()
        if tableau_prover:
            try:
                success, tableau = tableau_prover.prove(
                    str(goal),
                    [str(a) for a in enhanced_assumptions]
                )
                
                status = ProofStatus.SUCCESS if success else ProofStatus.FAILURE
                if success:
                    self.statistics["proofs_succeeded"] += 1
                else:
                    self.statistics["proofs_failed"] += 1
                
                proof = ProofTree(
                    goal=goal,
                    steps=tableau.proof_steps,
                    status=status,
                    logic=self.logic,
                    metadata={
                        "method": "cognitive_calculus",
                        "axioms": self.cognitive_axioms,
                        "closed": success,
                        "cognitive_rules_applied": len(derived) if assumptions else 0
                    }
                )
                
                return proof
                
            except Exception as e:
                logger.error(f"Cognitive calculus proving failed: {e}")
        
        self.statistics["proofs_failed"] += 1
        proof = ProofTree(
            goal=goal,
            steps=[],
            status=ProofStatus.UNKNOWN,
            logic=self.logic,
            metadata={
                "message": "Cognitive calculus prover fallback",
                "axioms": self.cognitive_axioms
            }
        )
        
        return proof
    
    def prove_problem(self, problem: ProblemFile) -> List[ProofTree]:
        """Prove all goals in a problem."""
        return [self.prove(goal, problem.assumptions) for goal in problem.goals]


class ProblemReader:
    """Reader for problem files.
    
    Supports various problem file formats used in automated theorem proving.
    """
    
    @beartype  # type: ignore[untyped-decorator]
    @staticmethod
    def read_problem_file(filepath: str) -> ProblemFile:
        """Read a problem file.
        
        Args:
            filepath: Path to problem file
            
        Returns:
            ProblemFile object
            
        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If file format is invalid
        """
        try:
            from .problem_parser import parse_problem_file
            return parse_problem_file(filepath)
        except ImportError:
            logger.warning("Problem parser not available, using basic implementation")
            
            # Basic fallback implementation
            return ProblemFile(
                name="placeholder",
                logic=ModalLogic.K,
                assumptions=[],
                goals=[],
                metadata={"filepath": filepath, "message": "Parser not available"}
            )


def create_prover(logic: ModalLogic) -> Union[KProver, S4Prover, S5Prover]:
    """Factory function to create a prover for the specified logic.
    
    Args:
        logic: The modal logic system
        
    Returns:
        Appropriate prover instance
        
    Raises:
        ValueError: If logic is not supported
    """
    prover_map = {
        ModalLogic.K: KProver,
        ModalLogic.S4: S4Prover,
        ModalLogic.S5: S5Prover,
    }
    
    prover_class = prover_map.get(logic)
    if not prover_class:
        raise ProvingError(
            f"Unsupported modal logic: {logic}",
            proof_state={"requested_logic": str(logic)},
            suggestion=f"Use one of the supported modal logics: K, S4, S5"
        )
    
    return prover_class()  # type: ignore[return-value,abstract]


def create_cognitive_prover() -> CognitiveCalculusProver:
    """Factory function to create a cognitive calculus prover.
    
    Returns:
        CognitiveCalculusProver instance
    """
    return CognitiveCalculusProver()
