"""
CEC Prove Tool - Theorem proving for DCEC formulas.

This tool provides theorem proving capabilities for DCEC formulas using
multiple prover backends with automatic selection.
"""

from typing import Dict, Any, Optional, List
import logging

logger = logging.getLogger(__name__)


def prove_dcec(
    goal: str,
    axioms: Optional[List[str]] = None,
    strategy: str = "auto",
    timeout: int = 30
) -> Dict[str, Any]:
    """
    Prove a DCEC theorem.
    
    Args:
        goal: Goal formula to prove
        axioms: Optional list of axiom formulas
        strategy: Proving strategy (auto/z3/vampire/e_prover)
        timeout: Timeout in seconds
    
    Returns:
        Dictionary with:
        - proved: Whether goal was proved
        - prover_used: Which prover was used
        - proof_steps: Number of proof steps
        - execution_time: Time taken in seconds
    
    Example:
        >>> result = prove_dcec("P(x) -> P(x)", strategy="auto")
        >>> print(result['proved'])
        True
    """
    try:
        from ipfs_datasets_py.logic.CEC.provers import ProverManager, ProverStrategy
        from ipfs_datasets_py.logic.CEC.native import parse_dcec_string
        
        # Parse goal
        goal_formula = parse_dcec_string(goal)
        
        # Parse axioms if provided
        axiom_formulas = []
        if axioms:
            for axiom in axioms:
                axiom_formulas.append(parse_dcec_string(axiom))
        
        # Get strategy enum
        if strategy == "auto":
            prover_strategy = ProverStrategy.AUTO
        elif strategy == "z3":
            prover_strategy = ProverStrategy.Z3
        elif strategy == "vampire":
            prover_strategy = ProverStrategy.VAMPIRE
        elif strategy == "e_prover":
            prover_strategy = ProverStrategy.E_PROVER
        else:
            prover_strategy = ProverStrategy.AUTO
        
        # Prove
        manager = ProverManager()
        result = manager.prove(
            formula=goal_formula,
            axioms=axiom_formulas,
            strategy=prover_strategy,
            timeout=timeout
        )
        
        return {
            "proved": result.success,
            "prover_used": result.prover_name,
            "proof_steps": result.steps,
            "execution_time": result.time_taken,
            "success": True
        }
    
    except Exception as e:
        logger.error(f"Error in prove_dcec: {e}")
        return {
            "proved": False,
            "prover_used": None,
            "proof_steps": 0,
            "execution_time": 0.0,
            "success": False,
            "error": str(e)
        }


def check_theorem(
    formula: str,
    axioms: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Check if a formula is a theorem (tautology).
    
    Args:
        formula: Formula to check
        axioms: Optional axioms to assume
    
    Returns:
        Dictionary with:
        - is_theorem: Whether formula is a theorem
        - counterexample: Counterexample if not a theorem
    
    Example:
        >>> result = check_theorem("P(x) | ~P(x)")
        >>> print(result['is_theorem'])
        True
    """
    try:
        from ipfs_datasets_py.logic.CEC.provers import ProverManager
        from ipfs_datasets_py.logic.CEC.native import parse_dcec_string
        
        formula_obj = parse_dcec_string(formula)
        
        axiom_objs = []
        if axioms:
            axiom_objs = [parse_dcec_string(a) for a in axioms]
        
        manager = ProverManager()
        result = manager.prove(formula_obj, axiom_objs)
        
        return {
            "is_theorem": result.success,
            "counterexample": result.counterexample if hasattr(result, 'counterexample') else None,
            "success": True
        }
    
    except Exception as e:
        logger.error(f"Error in check_theorem: {e}")
        return {
            "is_theorem": False,
            "counterexample": None,
            "success": False,
            "error": str(e)
        }


def get_proof_tree(
    goal: str,
    axioms: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Get proof tree for a theorem.
    
    Args:
        goal: Goal to prove
        axioms: Optional axioms
    
    Returns:
        Dictionary with:
        - tree: Proof tree structure
        - depth: Tree depth
        - nodes: Number of nodes
    
    Example:
        >>> result = get_proof_tree("P(x) -> P(x)")
        >>> print(result['depth'])
        2
    """
    try:
        from ipfs_datasets_py.logic.CEC.native import TheoremProver, parse_dcec_string
        
        goal_formula = parse_dcec_string(goal)
        
        axiom_formulas = []
        if axioms:
            axiom_formulas = [parse_dcec_string(a) for a in axioms]
        
        prover = TheoremProver()
        result = prover.prove(goal_formula, axiom_formulas)
        
        if result.success and result.proof_tree:
            return {
                "tree": result.proof_tree.to_dict(),
                "depth": result.proof_tree.depth,
                "nodes": result.proof_tree.node_count,
                "success": True
            }
        else:
            return {
                "tree": None,
                "depth": 0,
                "nodes": 0,
                "success": False,
                "error": "Proof failed or no tree available"
            }
    
    except Exception as e:
        logger.error(f"Error in get_proof_tree: {e}")
        return {
            "tree": None,
            "depth": 0,
            "nodes": 0,
            "success": False,
            "error": str(e)
        }


# Tool metadata for MCP server
TOOLS = {
    "prove_dcec": {
        "function": prove_dcec,
        "description": "Prove a DCEC theorem",
        "parameters": {
            "goal": {
                "type": "string",
                "description": "Goal formula to prove",
                "required": True
            },
            "axioms": {
                "type": "array",
                "description": "List of axiom formulas",
                "required": False
            },
            "strategy": {
                "type": "string",
                "description": "Proving strategy (auto/z3/vampire/e_prover)",
                "required": False,
                "default": "auto"
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds",
                "required": False,
                "default": 30
            }
        }
    },
    "check_theorem": {
        "function": check_theorem,
        "description": "Check if formula is a theorem",
        "parameters": {
            "formula": {
                "type": "string",
                "description": "Formula to check",
                "required": True
            },
            "axioms": {
                "type": "array",
                "description": "Optional axioms",
                "required": False
            }
        }
    },
    "get_proof_tree": {
        "function": get_proof_tree,
        "description": "Get proof tree structure",
        "parameters": {
            "goal": {
                "type": "string",
                "description": "Goal to prove",
                "required": True
            },
            "axioms": {
                "type": "array",
                "description": "Optional axioms",
                "required": False
            }
        }
    }
}
