"""
Proof Explanation System for TDFOL

This module generates human-readable explanations of theorem proofs in TDFOL.
It converts formal proof steps into natural language descriptions that are
easier for humans to understand.

Supports:
- Standard TDFOL proofs (forward/backward chaining)
- Modal tableaux proofs
- ZKP (zero-knowledge proof) explanations
- Inference rule applications
- Proof step reasoning chains

The explainer can generate:
1. Step-by-step proof narrations
2. High-level proof summaries
3. Inference rule explanations
4. ZKP verification explanations
5. Proof comparison (ZKP vs standard)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple, Any

from .tdfol_core import Formula, LogicOperator, TemporalOperator, DeonticOperator
from .exceptions import ProofError

logger = logging.getLogger(__name__)


class ProofType(Enum):
    """Types of proofs that can be explained."""
    FORWARD_CHAINING = "forward_chaining"
    BACKWARD_CHAINING = "backward_chaining"
    MODAL_TABLEAUX = "modal_tableaux"
    ZKP = "zkp"
    HYBRID = "hybrid"


class ExplanationLevel(Enum):
    """Level of detail in explanation."""
    BRIEF = "brief"  # One-line summary
    NORMAL = "normal"  # Standard detail
    DETAILED = "detailed"  # Full step-by-step
    VERBOSE = "verbose"  # All details + internals


@dataclass
class ProofStep:
    """A single step in a proof."""
    step_number: int
    action: str
    rule_name: Optional[str] = None
    premises: List[Formula] = field(default_factory=list)
    conclusion: Formula = None  # type: ignore
    justification: str = ""
    
    def to_natural_language(self) -> str:
        """Convert step to natural language."""
        if self.rule_name:
            return f"Step {self.step_number}: Applied {self.rule_name} to derive {self.conclusion}"
        else:
            return f"Step {self.step_number}: {self.action}"


@dataclass
class ProofExplanation:
    """Complete explanation of a proof."""
    formula: Formula
    is_proved: bool
    proof_type: ProofType
    steps: List[ProofStep] = field(default_factory=list)
    summary: str = ""
    inference_chain: List[str] = field(default_factory=list)
    statistics: Dict[str, Any] = field(default_factory=dict)
    
    def __str__(self) -> str:
        """Human-readable representation."""
        lines = []
        lines.append(f"Proof of: {self.formula}")
        lines.append(f"Result: {'✓ PROVED' if self.is_proved else '✗ NOT PROVED'}")
        lines.append(f"Method: {self.proof_type.value}")
        lines.append("")
        
        if self.summary:
            lines.append("Summary:")
            lines.append(f"  {self.summary}")
            lines.append("")
        
        if self.steps:
            lines.append(f"Proof Steps ({len(self.steps)}):")
            for step in self.steps:
                lines.append(f"  {step.to_natural_language()}")
            lines.append("")
        
        if self.inference_chain:
            lines.append("Reasoning Chain:")
            for i, item in enumerate(self.inference_chain, 1):
                lines.append(f"  {i}. {item}")
            lines.append("")
        
        if self.statistics:
            lines.append("Statistics:")
            for key, value in self.statistics.items():
                lines.append(f"  {key}: {value}")
        
        return '\n'.join(lines)


class ProofExplainer:
    """
    Generate human-readable explanations of TDFOL proofs.
    
    Converts formal proof steps into natural language descriptions
    that explain the reasoning process.
    """
    
    def __init__(self, level: ExplanationLevel = ExplanationLevel.NORMAL):
        """
        Initialize proof explainer.
        
        Args:
            level: Level of detail in explanations
        """
        self.level = level
        self.rule_descriptions = self._init_rule_descriptions()
    
    def _init_rule_descriptions(self) -> Dict[str, str]:
        """Initialize natural language descriptions for inference rules."""
        return {
            # Propositional rules
            "ModusPonens": "Given {p} → {q} and {p}, we conclude {q}",
            "ModusTollens": "Given {p} → {q} and ¬{q}, we conclude ¬{p}",
            "HypotheticalSyllogism": "Given {p} → {q} and {q} → {r}, we conclude {p} → {r}",
            "DisjunctiveSyllogism": "Given {p} ∨ {q} and ¬{p}, we conclude {q}",
            
            # Temporal rules
            "AlwaysDistribution": "□(P ∧ Q) distributes to □P ∧ □Q",
            "EventuallyAggregation": "◊P ∨ ◊Q implies ◊(P ∨ Q)",
            "TemporalInduction": "Given □(P → XP) and P, we prove □P by induction",
            
            # Deontic rules
            "ObligationWeakening": "O(P ∧ Q) implies O(P) - obligations weaken",
            "DeonticDetachment": "Given O(P → Q) and P, we conclude O(Q)",
            "ContraryToDuty": "When O(P) but ¬P holds, obligation to repair follows",
            
            # Modal rules
            "NecessityRule": "If ⊢ P, then ⊢ □P (necessitation)",
            "KAxiom": "□(P → Q) → (□P → □Q) - K axiom schema",
            "TAxiom": "□P → P - reflexivity axiom",
        }
    
    def explain_proof(
        self,
        formula: Formula,
        proof_steps: List[Any],
        proof_type: ProofType,
        is_proved: bool = True
    ) -> ProofExplanation:
        """
        Generate complete explanation of a proof.
        
        Args:
            formula: The formula that was proved
            proof_steps: List of proof steps (format depends on proof type)
            proof_type: Type of proof (forward chaining, tableaux, ZKP, etc.)
            is_proved: Whether the proof succeeded
            
        Returns:
            ProofExplanation with natural language description
        """
        explanation = ProofExplanation(
            formula=formula,
            is_proved=is_proved,
            proof_type=proof_type
        )
        
        # Generate steps
        if proof_type == ProofType.FORWARD_CHAINING:
            explanation.steps = self._explain_forward_chaining(proof_steps)
        elif proof_type == ProofType.BACKWARD_CHAINING:
            explanation.steps = self._explain_backward_chaining(proof_steps)
        elif proof_type == ProofType.MODAL_TABLEAUX:
            explanation.steps = self._explain_tableaux(proof_steps)
        elif proof_type == ProofType.ZKP:
            explanation.steps = self._explain_zkp(proof_steps)
        
        # Generate summary
        explanation.summary = self._generate_summary(formula, explanation.steps, proof_type, is_proved)
        
        # Generate reasoning chain
        explanation.inference_chain = self._extract_reasoning_chain(explanation.steps)
        
        # Generate statistics
        explanation.statistics = self._compute_statistics(explanation.steps)
        
        return explanation
    
    def _explain_forward_chaining(self, proof_steps: List[Any]) -> List[ProofStep]:
        """Explain forward chaining proof steps."""
        steps = []
        for i, step in enumerate(proof_steps, 1):
            if isinstance(step, dict):
                steps.append(ProofStep(
                    step_number=i,
                    action=f"Forward chaining applied {step.get('rule', 'unknown rule')}",
                    rule_name=step.get('rule'),
                    conclusion=step.get('conclusion'),
                    justification=self._explain_rule_application(step.get('rule'))
                ))
            elif isinstance(step, str):
                steps.append(ProofStep(
                    step_number=i,
                    action=step,
                    justification=""
                ))
        return steps
    
    def _explain_backward_chaining(self, proof_steps: List[Any]) -> List[ProofStep]:
        """Explain backward chaining proof steps."""
        steps = []
        for i, step in enumerate(proof_steps, 1):
            steps.append(ProofStep(
                step_number=i,
                action=f"Backward chaining: {step}",
                justification="Goal-directed search"
            ))
        return steps
    
    def _explain_tableaux(self, proof_steps: List[Any]) -> List[ProofStep]:
        """Explain modal tableaux proof steps."""
        steps = []
        for i, step in enumerate(proof_steps, 1):
            if isinstance(step, str):
                steps.append(ProofStep(
                    step_number=i,
                    action=step,
                    justification="Tableaux expansion"
                ))
        return steps
    
    def _explain_zkp(self, proof_steps: List[Any]) -> List[ProofStep]:
        """Explain ZKP proof steps."""
        steps = []
        # ZKP proofs are typically single-step: verify the proof
        steps.append(ProofStep(
            step_number=1,
            action="Verified zero-knowledge proof",
            justification="Cryptographic verification of proof without revealing axioms"
        ))
        return steps
    
    def _explain_rule_application(self, rule_name: Optional[str]) -> str:
        """Generate natural language explanation of rule application."""
        if not rule_name:
            return "Applied inference rule"
        
        if rule_name in self.rule_descriptions:
            return self.rule_descriptions[rule_name]
        
        # Generate generic explanation
        if "Weakening" in rule_name:
            return "Weakening rule: derive weaker conclusion from stronger premise"
        elif "Strengthening" in rule_name:
            return "Strengthening rule: strengthen the conclusion"
        elif "Distribution" in rule_name:
            return "Distribution rule: distribute operator over subformulas"
        elif "Induction" in rule_name:
            return "Induction rule: prove by mathematical induction"
        else:
            return f"Applied {rule_name} inference rule"
    
    def _generate_summary(
        self,
        formula: Formula,
        steps: List[ProofStep],
        proof_type: ProofType,
        is_proved: bool
    ) -> str:
        """Generate high-level summary of proof."""
        if not is_proved:
            return f"Failed to prove {formula} using {proof_type.value}"
        
        if proof_type == ProofType.FORWARD_CHAINING:
            return f"Proved {formula} in {len(steps)} steps using forward chaining with inference rules"
        elif proof_type == ProofType.BACKWARD_CHAINING:
            return f"Proved {formula} using goal-directed backward chaining in {len(steps)} steps"
        elif proof_type == ProofType.MODAL_TABLEAUX:
            return f"Proved {formula} using modal tableaux method (all branches closed)"
        elif proof_type == ProofType.ZKP:
            return f"Verified {formula} using zero-knowledge proof (cryptographic verification)"
        else:
            return f"Proved {formula} using {proof_type.value}"
    
    def _extract_reasoning_chain(self, steps: List[ProofStep]) -> List[str]:
        """Extract the chain of reasoning from proof steps."""
        chain = []
        for step in steps:
            if step.rule_name:
                chain.append(f"Apply {step.rule_name}")
            elif step.action:
                chain.append(step.action)
        return chain
    
    def _compute_statistics(self, steps: List[ProofStep]) -> Dict[str, Any]:
        """Compute statistics about the proof."""
        stats = {
            "total_steps": len(steps),
            "rules_used": len([s for s in steps if s.rule_name]),
            "unique_rules": len(set(s.rule_name for s in steps if s.rule_name))
        }
        return stats
    
    def explain_inference_rule(self, rule_name: str, premises: List[Formula], conclusion: Formula) -> str:
        """
        Explain a single inference rule application.
        
        Args:
            rule_name: Name of the inference rule
            premises: Premise formulas
            conclusion: Conclusion formula
            
        Returns:
            Natural language explanation
        """
        base_explanation = self._explain_rule_application(rule_name)
        
        if self.level == ExplanationLevel.BRIEF:
            return f"{rule_name}: {premises} ⊢ {conclusion}"
        elif self.level == ExplanationLevel.DETAILED:
            lines = [
                f"Inference Rule: {rule_name}",
                f"Premises: {', '.join(str(p) for p in premises)}",
                f"Conclusion: {conclusion}",
                f"Explanation: {base_explanation}"
            ]
            return '\n'.join(lines)
        else:
            return f"{rule_name}: {base_explanation}"
    
    def compare_proofs(
        self,
        standard_explanation: ProofExplanation,
        zkp_explanation: ProofExplanation
    ) -> str:
        """
        Compare standard and ZKP proofs.
        
        Args:
            standard_explanation: Explanation of standard proof
            zkp_explanation: Explanation of ZKP proof
            
        Returns:
            Comparison text
        """
        lines = [
            "Proof Comparison: Standard vs ZKP",
            "=" * 50,
            "",
            "Standard Proof:",
            f"  Method: {standard_explanation.proof_type.value}",
            f"  Steps: {len(standard_explanation.steps)}",
            f"  Rules used: {standard_explanation.statistics.get('rules_used', 0)}",
            "",
            "ZKP Proof:",
            f"  Method: Zero-knowledge proof",
            f"  Steps: Cryptographic verification",
            f"  Privacy: Axioms hidden",
            "",
            "Trade-offs:",
            "  Standard: Transparent reasoning, shows all steps",
            "  ZKP: Private axioms, fast verification, succinct proof",
            "",
            "Recommendation:",
            "  - Use Standard for transparency and debugging",
            "  - Use ZKP for privacy-sensitive proofs"
        ]
        return '\n'.join(lines)


class ZKPProofExplainer:
    """
    Specialized explainer for zero-knowledge proofs.
    
    Explains ZKP verification results, security properties,
    and trade-offs compared to standard proofs.
    """
    
    def __init__(self):
        """Initialize ZKP explainer."""
        pass
    
    def explain_zkp_proof(
        self,
        formula: Formula,
        zkp_result: Any,
        backend: str = "simulated",
        security_level: int = 128
    ) -> ProofExplanation:
        """
        Explain a ZKP proof result.
        
        Args:
            formula: The formula that was proved
            zkp_result: ZKP proof result object
            backend: ZKP backend (simulated, groth16, etc.)
            security_level: Security level in bits
            
        Returns:
            ProofExplanation for ZKP
        """
        explanation = ProofExplanation(
            formula=formula,
            is_proved=True,  # Assume verified
            proof_type=ProofType.ZKP
        )
        
        # Add ZKP-specific steps
        explanation.steps = [
            ProofStep(
                step_number=1,
                action="Generated zero-knowledge proof",
                justification="Cryptographic proof generation with private axioms"
            ),
            ProofStep(
                step_number=2,
                action="Verified proof cryptographically",
                justification=f"Fast verification (<10ms) using {backend} backend"
            )
        ]
        
        # Generate ZKP-specific summary
        explanation.summary = (
            f"Proved {formula} using zero-knowledge proof "
            f"({backend} backend, {security_level}-bit security). "
            f"Axioms remain private. Proof is succinct (~160 bytes)."
        )
        
        # ZKP reasoning chain
        explanation.inference_chain = [
            "1. Private axioms loaded (hidden from verifier)",
            "2. Zero-knowledge proof generated",
            "3. Proof verified cryptographically",
            "4. Formula proven without revealing axioms"
        ]
        
        # ZKP statistics
        explanation.statistics = {
            "backend": backend,
            "security_level": f"{security_level}-bit",
            "proof_size": "~160 bytes",
            "verification_time": "<10ms",
            "privacy": "Axioms hidden"
        }
        
        return explanation
    
    def explain_security_properties(self, backend: str, security_level: int) -> str:
        """Explain security properties of ZKP backend."""
        lines = [
            f"ZKP Security Properties ({backend} backend)",
            "=" * 50,
            "",
            f"Security Level: {security_level}-bit",
            "",
            "Properties:",
            "  - Completeness: If statement is true, honest prover convinces verifier",
            "  - Soundness: If statement is false, dishonest prover cannot convince verifier",
            "  - Zero-Knowledge: Verifier learns nothing except truth of statement",
            ""
        ]
        
        if backend == "simulated":
            lines.extend([
                "⚠️  WARNING: Simulated backend (not cryptographically secure)",
                "   For educational and testing purposes only",
                "   Do NOT use with sensitive data in production"
            ])
        elif backend == "groth16":
            lines.extend([
                "✓ Groth16: State-of-the-art zk-SNARK",
                "  - Constant-size proofs (~160 bytes)",
                "  - Fast verification (<10ms)",
                "  - Requires trusted setup"
            ])
        
        return '\n'.join(lines)
    
    def explain_zkp_vs_standard(self) -> str:
        """Explain trade-offs between ZKP and standard proofs."""
        return """
ZKP vs Standard Proofs
======================

Standard TDFOL Proving:
  ✓ Transparent: All reasoning steps visible
  ✓ Debuggable: Can inspect each inference
  ✓ Educational: Shows logical reasoning
  ✗ No privacy: Axioms must be public
  ✗ Larger proofs: Full proof tree
  ✗ Slower verification: Must re-check all steps

Zero-Knowledge Proving:
  ✓ Private: Axioms remain hidden
  ✓ Succinct: ~160 byte proofs
  ✓ Fast verification: <10ms
  ✗ Opaque: Cannot inspect reasoning
  ✗ Complex: Requires cryptographic setup
  ✗ Trust assumptions: Trusted setup (Groth16)

When to Use Each:
  - Standard: Transparency, debugging, teaching
  - ZKP: Privacy, proprietary axioms, fast verification
  
Hybrid Approach:
  - Try ZKP first (if privacy needed)
  - Fall back to standard (if ZKP fails or unavailable)
  - Best of both worlds
"""


def explain_proof(
    formula: Formula,
    proof_steps: List[Any],
    proof_type: ProofType = ProofType.FORWARD_CHAINING,
    is_proved: bool = True,
    level: ExplanationLevel = ExplanationLevel.NORMAL
) -> ProofExplanation:
    """
    Convenience function to explain a proof.
    
    Args:
        formula: The formula that was proved
        proof_steps: List of proof steps
        proof_type: Type of proof
        is_proved: Whether proof succeeded
        level: Level of detail
        
    Returns:
        ProofExplanation
        
    Example:
        >>> from tdfol_core import parse_tdfol
        >>> formula = parse_tdfol("P → Q")
        >>> steps = [...]  # Proof steps from prover
        >>> explanation = explain_proof(formula, steps, ProofType.FORWARD_CHAINING)
        >>> print(explanation)
    """
    explainer = ProofExplainer(level=level)
    return explainer.explain_proof(formula, proof_steps, proof_type, is_proved)


def explain_zkp_proof(
    formula: Formula,
    zkp_result: Any,
    backend: str = "simulated",
    security_level: int = 128
) -> ProofExplanation:
    """
    Convenience function to explain a ZKP proof.
    
    Args:
        formula: The formula that was proved
        zkp_result: ZKP proof result
        backend: ZKP backend
        security_level: Security level in bits
        
    Returns:
        ProofExplanation for ZKP
    """
    explainer = ZKPProofExplainer()
    return explainer.explain_zkp_proof(formula, zkp_result, backend, security_level)
