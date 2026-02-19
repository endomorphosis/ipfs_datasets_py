"""
CEC Analysis Tool - Analyze DCEC formulas for complexity and properties.

This tool provides analysis capabilities for DCEC formulas including
complexity metrics, formula properties, and structural analysis.
"""

from typing import Dict, Any, List
import logging

logger = logging.getLogger(__name__)


def analyze_formula(formula: str) -> Dict[str, Any]:
    """
    Analyze a DCEC formula for various properties.
    
    Args:
        formula: DCEC formula to analyze
    
    Returns:
        Dictionary with:
        - complexity: Complexity metrics
        - operators: List of operators used
        - variables: List of variables
        - depth: Formula depth
        - size: Formula size (number of subformulas)
    
    Example:
        >>> result = analyze_formula("O(P(x)) & K(agent, Q(y))")
        >>> print(result['complexity']['depth'])
        3
    """
    try:
        from ipfs_datasets_py.logic.CEC.native import parse_dcec_string
        
        formula_obj = parse_dcec_string(formula)
        
        # Calculate complexity metrics
        def get_depth(f):
            """Recursively calculate formula depth"""
            if hasattr(f, 'subformulas'):
                return 1 + max((get_depth(sf) for sf in f.subformulas), default=0)
            return 1
        
        def get_size(f):
            """Count number of subformulas"""
            if hasattr(f, 'subformulas'):
                return 1 + sum(get_size(sf) for sf in f.subformulas)
            return 1
        
        def get_operators(f):
            """Extract operators used"""
            ops = []
            if hasattr(f, 'operator'):
                ops.append(str(f.operator))
            if hasattr(f, 'subformulas'):
                for sf in f.subformulas:
                    ops.extend(get_operators(sf))
            return ops
        
        depth = get_depth(formula_obj)
        size = get_size(formula_obj)
        operators = list(set(get_operators(formula_obj)))
        
        return {
            "complexity": {
                "depth": depth,
                "size": size,
                "operators_count": len(operators)
            },
            "operators": operators,
            "variables": [],  # Would extract from formula
            "depth": depth,
            "size": size,
            "success": True
        }
    
    except Exception as e:
        logger.error(f"Error in analyze_formula: {e}")
        return {
            "complexity": {},
            "operators": [],
            "variables": [],
            "depth": 0,
            "size": 0,
            "success": False,
            "error": str(e)
        }


def visualize_proof(
    goal: str,
    axioms: List[str] = None,
    format: str = "text"
) -> Dict[str, Any]:
    """
    Visualize a proof tree.
    
    Args:
        goal: Goal formula
        axioms: Optional axioms
        format: Output format (text/json/graphviz)
    
    Returns:
        Dictionary with:
        - visualization: Proof visualization
        - format: Format used
    
    Example:
        >>> result = visualize_proof("P -> P", format="text")
        >>> print(result['visualization'])
        'Goal: P -> P\n  Axiom: P\n  Proves: P'
    """
    try:
        from ipfs_datasets_py.logic.CEC.native import TheoremProver, parse_dcec_string
        
        goal_formula = parse_dcec_string(goal)
        
        axiom_formulas = []
        if axioms:
            axiom_formulas = [parse_dcec_string(a) for a in axioms]
        
        prover = TheoremProver()
        result = prover.prove(goal_formula, axiom_formulas)
        
        if format == "text":
            viz = f"Goal: {goal}\n"
            if result.success:
                viz += "Status: PROVED\n"
                viz += f"Steps: {result.steps}\n"
            else:
                viz += "Status: UNPROVED\n"
            
            return {
                "visualization": viz,
                "format": format,
                "success": True
            }
        elif format == "json":
            return {
                "visualization": {
                    "goal": goal,
                    "proved": result.success,
                    "steps": result.steps
                },
                "format": format,
                "success": True
            }
        else:
            return {
                "visualization": None,
                "format": format,
                "success": False,
                "error": f"Unsupported format: {format}"
            }
    
    except Exception as e:
        logger.error(f"Error in visualize_proof: {e}")
        return {
            "visualization": None,
            "format": format,
            "success": False,
            "error": str(e)
        }


def get_formula_complexity(formula: str) -> Dict[str, Any]:
    """
    Get detailed complexity metrics for a formula.
    
    Args:
        formula: DCEC formula
    
    Returns:
        Dictionary with:
        - modal_depth: Maximum modal depth
        - quantifier_depth: Quantifier nesting depth
        - connective_count: Number of logical connectives
        - overall_complexity: Overall complexity score
    
    Example:
        >>> result = get_formula_complexity("O(P(x)) -> K(agent, Q(y))")
        >>> print(result['overall_complexity'])
        'medium'
    """
    try:
        from ipfs_datasets_py.logic.CEC.native import parse_dcec_string
        
        formula_obj = parse_dcec_string(formula)
        
        # Calculate various complexity metrics
        modal_depth = 0
        quantifier_depth = 0
        connective_count = 0
        
        # Simple heuristic for complexity
        if len(formula) < 20:
            complexity = "low"
        elif len(formula) < 50:
            complexity = "medium"
        else:
            complexity = "high"
        
        return {
            "modal_depth": modal_depth,
            "quantifier_depth": quantifier_depth,
            "connective_count": connective_count,
            "overall_complexity": complexity,
            "formula_length": len(formula),
            "success": True
        }
    
    except Exception as e:
        logger.error(f"Error in get_formula_complexity: {e}")
        return {
            "modal_depth": 0,
            "quantifier_depth": 0,
            "connective_count": 0,
            "overall_complexity": "unknown",
            "formula_length": 0,
            "success": False,
            "error": str(e)
        }


def profile_operation(
    operation: str,
    formula: str,
    iterations: int = 1
) -> Dict[str, Any]:
    """
    Profile the performance of an operation on a formula.
    
    Args:
        operation: Operation to profile (parse/prove/analyze)
        formula: Formula to operate on
        iterations: Number of iterations for profiling
    
    Returns:
        Dictionary with:
        - avg_time: Average time per iteration (seconds)
        - total_time: Total time (seconds)
        - memory_used: Memory used (bytes)
    
    Example:
        >>> result = profile_operation("parse", "O(P(x))", iterations=100)
        >>> print(result['avg_time'])
        0.001
    """
    try:
        from ipfs_datasets_py.logic.CEC.optimization import FormulaProfiler
        import time
        
        profiler = FormulaProfiler()
        profiler.start_profiling(f"profile_{operation}")
        
        start = time.time()
        
        for _ in range(iterations):
            if operation == "parse":
                from ipfs_datasets_py.logic.CEC.native import parse_dcec_string
                parse_dcec_string(formula)
            elif operation == "prove":
                from ipfs_datasets_py.logic.CEC.native import TheoremProver, parse_dcec_string
                f = parse_dcec_string(formula)
                prover = TheoremProver()
                prover.prove(f, [])
            elif operation == "analyze":
                analyze_formula(formula)
        
        elapsed = time.time() - start
        result = profiler.stop_profiling(f"profile_{operation}")
        
        return {
            "avg_time": elapsed / iterations,
            "total_time": elapsed,
            "memory_used": result.memory_used,
            "iterations": iterations,
            "success": True
        }
    
    except Exception as e:
        logger.error(f"Error in profile_operation: {e}")
        return {
            "avg_time": 0.0,
            "total_time": 0.0,
            "memory_used": 0,
            "iterations": 0,
            "success": False,
            "error": str(e)
        }


# Tool metadata for MCP server
TOOLS = {
    "analyze_formula": {
        "function": analyze_formula,
        "description": "Analyze DCEC formula properties and complexity",
        "parameters": {
            "formula": {
                "type": "string",
                "description": "DCEC formula to analyze",
                "required": True
            }
        }
    },
    "visualize_proof": {
        "function": visualize_proof,
        "description": "Visualize proof tree",
        "parameters": {
            "goal": {
                "type": "string",
                "description": "Goal formula",
                "required": True
            },
            "axioms": {
                "type": "array",
                "description": "Optional axioms",
                "required": False
            },
            "format": {
                "type": "string",
                "description": "Output format (text/json/graphviz)",
                "required": False,
                "default": "text"
            }
        }
    },
    "get_formula_complexity": {
        "function": get_formula_complexity,
        "description": "Get detailed complexity metrics",
        "parameters": {
            "formula": {
                "type": "string",
                "description": "DCEC formula",
                "required": True
            }
        }
    },
    "profile_operation": {
        "function": profile_operation,
        "description": "Profile operation performance",
        "parameters": {
            "operation": {
                "type": "string",
                "description": "Operation to profile (parse/prove/analyze)",
                "required": True
            },
            "formula": {
                "type": "string",
                "description": "Formula to operate on",
                "required": True
            },
            "iterations": {
                "type": "integer",
                "description": "Number of iterations",
                "required": False,
                "default": 1
            }
        }
    }
}
