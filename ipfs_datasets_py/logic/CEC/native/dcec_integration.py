"""
DCEC String to Formula Integration

This module provides the complete pipeline for converting string expressions
to DCEC Formula objects, integrating all parsing, cleaning, and type checking
components.

Functions:
    parse_expression_to_token: Convert string to ParseToken tree
    token_to_formula: Convert ParseToken to Formula object
    parse_dcec_string: Complete pipeline from string to Formula
"""

from typing import Optional, Dict, List, Union, Tuple
import logging
from .dcec_core import (
    Formula, AtomicFormula, ConnectiveFormula, QuantifiedFormula,
    DeonticFormula, CognitiveFormula, TemporalFormula,
    LogicalConnective, DeonticOperator, CognitiveOperator, TemporalOperator,
    Term, VariableTerm, FunctionTerm, Variable, Sort, Function, Predicate
)
from .dcec_cleaning import (
    strip_whitespace, strip_comments, consolidate_parens,
    check_parens, tuck_functions
)
from .dcec_parsing import (
    ParseToken, remove_comments, functorize_symbols,
    replace_synonyms, prefix_logical_functions, prefix_emdas
)
from .dcec_prototypes import DCECPrototypeNamespace

logger = logging.getLogger(__name__)


def _make_agent_term(agent_str: str, variables: Dict[str, Variable]) -> Term:
    """Create a Variable or Function term for an agent string."""
    if isinstance(agent_str, str) and agent_str[0].islower():
        if agent_str not in variables:
            variables[agent_str] = Variable(agent_str, Sort("Agent"))
        return VariableTerm(variables[agent_str])
    # Constant (e.g. "Agent", "agent")
    func = Function(str(agent_str), [], Sort("Agent"))
    return FunctionTerm(func, [])


class DCECParsingError(Exception):
    """Exception raised for errors during DCEC parsing."""
    pass


def parse_expression_to_token(
    expression: str,
    namespace: Optional[DCECPrototypeNamespace] = None
) -> Optional[ParseToken]:
    """
    Parse a DCEC expression string into a ParseToken tree.
    
    This performs the complete parsing pipeline:
    1. Remove comments
    2. Clean whitespace
    3. Functorize symbols
    4. Convert to prefix notation
    5. Build token tree
    
    Args:
        expression: The DCEC expression as a string
        namespace: Optional namespace for type checking
        
    Returns:
        Optional[ParseToken]: The root token, or None if parsing fails
        
    Raises:
        DCECParsingError: If the expression is malformed
        
    Examples:
        >>> expr = "a -> b"
        >>> token = parse_expression_to_token(expr)
        >>> token.func_name
        'implies'
    """
    if not expression or not expression.strip():
        logger.error("Empty expression provided")
        return None
    
    # Step 1: Remove comments
    expr = remove_comments(expression)
    expr = strip_comments(expr)
    
    # Special-case: top-level "not X" prefix notation.
    # Recursively parse the operand then wrap in a ParseToken("not", [operand]).
    # This must be done BEFORE strip_whitespace because that converts "not a" → "not,a".
    import re as _re
    _raw = expression.strip() if expression else ""
    _not_match = _re.match(r'^not\s+(.+)$', _raw, _re.DOTALL)
    if _not_match:
        sub_expr = _not_match.group(1).strip()
        sub_token = parse_expression_to_token(sub_expr, namespace)
        if sub_token is not None:
            return ParseToken("not", [sub_token])

    # Step 2: Clean whitespace and validate
    expr = strip_whitespace(expr)
    
    if not check_parens(expr):
        raise DCECParsingError(f"Unbalanced parentheses in: {expr}")
    
    # Step 3: Consolidate redundant parens
    expr = consolidate_parens(expr)
    
    # Step 4: Functorize symbols (convert operators to function names)
    expr = functorize_symbols(expr)
    
    # Step 5: Transform function notation
    expr = tuck_functions(expr)
    
    # Step 6: Split into arguments
    expr = strip_whitespace(expr)
    args = expr.split(",")
    
    # Step 7: Replace synonyms
    replace_synonyms(args)
    
    # Step 8: Track atomics for type inference
    add_atomics: Dict[str, List[str]] = {}
    
    # Step 9: Convert infix to prefix (logical operations)
    args = prefix_logical_functions(args, add_atomics)
    
    # Step 10: Convert infix to prefix (arithmetic operations)
    args = prefix_emdas(args, add_atomics)
    
    # Step 11: Build token tree from result
    if len(args) == 1 and isinstance(args[0], ParseToken):
        return args[0]
    elif len(args) > 1:
        # Multiple args at top level, wrap in implicit "and"
        logger.warning(f"Multiple top-level args, wrapping in 'and': {args}")
        return ParseToken("and", args)
    elif len(args) == 1:
        # Single atomic
        return ParseToken("atomic", [args[0]])
    
    return None


def token_to_formula(
    token: ParseToken,
    namespace: Optional[DCECPrototypeNamespace] = None,
    variables: Optional[Dict[str, Variable]] = None
) -> Optional[Formula]:
    """
    Convert a ParseToken tree to a Formula object.
    
    Args:
        token: The ParseToken to convert
        namespace: Optional namespace for type checking
        variables: Dict of known variables
        
    Returns:
        Optional[Formula]: The Formula object, or None if conversion fails
        
    Examples:
        >>> token = ParseToken("and", ["a", "b"])
        >>> formula = token_to_formula(token)
        >>> formula.operator
        LogicalConnective.AND
    """
    if variables is None:
        variables = {}
    
    # Strip leading/trailing parens from function name (parser artifacts)
    func_name = token.func_name.strip("()").lower()
    
    # Special case: "atomic" tokens wrap a single predicate name in parens.
    # e.g. ParseToken("atomic", ["(a)"]) → AtomicFormula(Predicate("a", []), [])
    if func_name == "atomic":
        pred_strs = [a.strip("()") for a in token.args if isinstance(a, str)]
        if pred_strs:
            predicate = Predicate(pred_strs[0], [])
            return AtomicFormula(predicate, [])
        return None
    
    # Logical connectives
    if func_name == "and":
        if len(token.args) == 2:
            # Check for embedded NOT: and(["not", "x"]) is really NOT(x)
            first_raw = token.args[0] if isinstance(token.args[0], str) else ""
            first_clean = first_raw.strip("()").lower()
            if first_clean == "not":
                inner = _arg_to_formula(token.args[1], namespace, variables)
                if inner:
                    return ConnectiveFormula(LogicalConnective.NOT, [inner])
        if len(token.args) >= 2:
            formulas = [_arg_to_formula(arg, namespace, variables) for arg in token.args]
            formulas = [f for f in formulas if f is not None]
            if len(formulas) >= 2:
                return ConnectiveFormula(LogicalConnective.AND, formulas)
    
    elif func_name == "or":
        if len(token.args) >= 2:
            formulas = [_arg_to_formula(arg, namespace, variables) for arg in token.args]
            formulas = [f for f in formulas if f is not None]
            if len(formulas) >= 2:
                return ConnectiveFormula(LogicalConnective.OR, formulas)
    
    elif func_name == "not":
        if len(token.args) == 1:
            formula = _arg_to_formula(token.args[0], namespace, variables)
            if formula:
                return ConnectiveFormula(LogicalConnective.NOT, [formula])
    
    elif func_name == "implies":
        if len(token.args) == 2:
            left = _arg_to_formula(token.args[0], namespace, variables)
            right = _arg_to_formula(token.args[1], namespace, variables)
            if left and right:
                return ConnectiveFormula(LogicalConnective.IMPLIES, [left, right])
    
    elif func_name in ["iff", "ifandonlyif"]:
        if len(token.args) == 2:
            left = _arg_to_formula(token.args[0], namespace, variables)
            right = _arg_to_formula(token.args[1], namespace, variables)
            if left and right:
                return ConnectiveFormula(LogicalConnective.BICONDITIONAL, [left, right])
    
    # Deontic operators
    elif func_name == "o":  # Obligation
        if len(token.args) >= 2:
            # O(agent, moment, formula) or O(agent, moment, condition, formula)
            formula_arg = token.args[-1]
            formula = _arg_to_formula(formula_arg, namespace, variables)
            if formula:
                return DeonticFormula(DeonticOperator.OBLIGATORY, formula)
    
    elif func_name == "p":  # Permission
        if len(token.args) >= 1:
            formula = _arg_to_formula(token.args[-1], namespace, variables)
            if formula:
                return DeonticFormula(DeonticOperator.PERMISSIBLE, formula)
    
    elif func_name == "f":  # Forbidden
        if len(token.args) >= 1:
            formula = _arg_to_formula(token.args[-1], namespace, variables)
            if formula:
                return DeonticFormula(DeonticOperator.FORBIDDEN, formula)
    
    # Cognitive operators
    elif func_name == "b":  # Belief
        if len(token.args) >= 1:
            agent_str = token.args[0] if len(token.args) >= 2 else "agent"
            agent_term = _make_agent_term(str(agent_str), variables)
            formula = _arg_to_formula(token.args[-1], namespace, variables)
            agent_arg = token.args[0]
            agent_term = FunctionTerm(Function(str(agent_arg), [], Sort("agent")), [])
            if formula:
                return CognitiveFormula(CognitiveOperator.BELIEF, agent_term, formula)
    
    elif func_name == "k":  # Knowledge
        if len(token.args) >= 1:
            agent_str = token.args[0] if len(token.args) >= 2 else "agent"
            agent_term = _make_agent_term(str(agent_str), variables)
            formula = _arg_to_formula(token.args[-1], namespace, variables)
            agent_arg = token.args[0]
            agent_term = FunctionTerm(Function(str(agent_arg), [], Sort("agent")), [])
            if formula:
                return CognitiveFormula(CognitiveOperator.KNOWLEDGE, agent_term, formula)
    
    elif func_name == "i":  # Intention
        if len(token.args) >= 1:
            agent_str = token.args[0] if len(token.args) >= 2 else "agent"
            agent_term = _make_agent_term(str(agent_str), variables)
            formula = _arg_to_formula(token.args[-1], namespace, variables)
            agent_arg = token.args[0]
            agent_term = FunctionTerm(Function(str(agent_arg), [], Sort("agent")), [])
            if formula:
                return CognitiveFormula(CognitiveOperator.INTENTION, agent_term, formula)
    
    # Temporal operators
    elif func_name in ["always", "box", "□"]:
        if len(token.args) >= 1:
            formula = _arg_to_formula(token.args[0], namespace, variables)
            if formula:
                return TemporalFormula(TemporalOperator.ALWAYS, formula)
    
    elif func_name in ["eventually", "diamond", "◊"]:
        if len(token.args) >= 1:
            formula = _arg_to_formula(token.args[0], namespace, variables)
            if formula:
                return TemporalFormula(TemporalOperator.EVENTUALLY, formula)
    
    elif func_name in ["next", "x"]:
        if len(token.args) >= 1:
            formula = _arg_to_formula(token.args[0], namespace, variables)
            if formula:
                return TemporalFormula(TemporalOperator.NEXT, formula)
    
    # Atomic formula (predicate)
    else:
        # Try to create as atomic formula
        terms = []
        for arg in token.args:
            if isinstance(arg, str):
                # Simple variable or constant
                if arg[0].islower():
                    # Variable
                    if arg not in variables:
                        variables[arg] = Variable(arg, Sort("Object"))
                    terms.append(VariableTerm(variables[arg]))
                else:
                    # Constant (treated as 0-ary function)
                    func = Function(arg, [], Sort("Object"))
                    terms.append(FunctionTerm(func, []))
            elif isinstance(arg, ParseToken):
                # Nested token - recursively convert
                nested = token_to_formula(arg, namespace, variables)
                if nested:
                    # Convert formula to term (simplified)
                    logger.warning(f"Nested formula as term not fully supported: {arg}")
        
        # Create predicate with arity matching actual terms
        arg_sorts = [Sort("Object")] * len(terms)
        predicate = Predicate(token.func_name, arg_sorts)
        return AtomicFormula(predicate, terms)
    
    logger.warning(f"Could not convert token to formula: {token.func_name}")
    return None


def _arg_to_formula(
    arg: Union[str, ParseToken],
    namespace: Optional[DCECPrototypeNamespace],
    variables: Dict[str, Variable]
) -> Optional[Formula]:
    """Helper to convert an argument to a formula."""
    if isinstance(arg, ParseToken):
        return token_to_formula(arg, namespace, variables)
    elif isinstance(arg, str):
        # Strip parser-added outer parentheses
        clean_arg = arg.strip("()")
        if not clean_arg:
            return None
        # Atomic predicate (0-ary)
        predicate = Predicate(clean_arg, [])
        return AtomicFormula(predicate, [])
    return None


def parse_dcec_string(
    expression: str,
    namespace: Optional[DCECPrototypeNamespace] = None
) -> Optional[Formula]:
    """
    Complete pipeline: Parse a DCEC string expression into a Formula object.
    
    This is the main entry point for string-to-formula conversion.
    
    Args:
        expression: The DCEC expression as a string
        namespace: Optional namespace for type checking
        
    Returns:
        Optional[Formula]: The parsed Formula, or None if parsing fails
        
    Raises:
        DCECParsingError: If the expression is malformed
        
    Examples:
        >>> formula = parse_dcec_string("a -> b")
        >>> isinstance(formula, ConnectiveFormula)
        True
        >>> formula.operator
        LogicalConnective.IMPLIES
    """
    try:
        # Pre-process: convert "not X" prefix notation to "not(X)" if not already
        import re as _re
        # Normalize: "not X" (not followed by paren) -> "not(X)"
        expression = _re.sub(r'\bnot\s+(?!\()(\w+)', r'not(\1)', expression)
        
        # Step 1: Parse to token
        token = parse_expression_to_token(expression, namespace)
        if token is None:
            return None
        
        # Step 2: Convert token to formula
        formula = token_to_formula(token, namespace)
        return formula
        
    except Exception as e:
        logger.error(f"Error parsing DCEC string: {e}")
        raise DCECParsingError(f"Failed to parse '{expression}': {e}")


def validate_formula(
    formula: Formula,
    namespace: Optional[DCECPrototypeNamespace] = None
) -> Tuple[bool, List[str]]:
    """
    Validate a formula for type correctness and well-formedness.
    
    Args:
        formula: The formula to validate
        namespace: Optional namespace for type checking
        
    Returns:
        Tuple[bool, List[str]]: (is_valid, list_of_errors)
    """
    errors = []
    
    # Type-specific validation
    if isinstance(formula, ConnectiveFormula):
        if formula.connective == LogicalConnective.NOT:
            if len(formula.formulas) != 1:
                errors.append("NOT should have exactly 1 operand")
        elif formula.connective in [LogicalConnective.IMPLIES, LogicalConnective.BICONDITIONAL]:
            if len(formula.formulas) != 2:
                errors.append(f"{formula.connective} requires exactly 2 operands")
        elif formula.connective in [LogicalConnective.AND, LogicalConnective.OR]:
            if len(formula.formulas) < 2:
                errors.append(f"{formula.connective} requires at least 2 operands")
        
        # Validate all sub-formulas recursively
        for sub_formula in formula.formulas:
            valid, sub_errors = validate_formula(sub_formula, namespace)
            errors.extend(sub_errors)
    
    return (len(errors) == 0, errors)
