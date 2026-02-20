"""
DCEC Parsing System

This module provides core parsing functionality for DCEC expressions.
Ported from DCEC_Library/highLevelParsing.py to pure Python 3.

Classes:
    ParseToken: Represents a parsed DCEC expression as a tree structure

Functions:
    remove_comments: Remove semicolon comments
    functorize_symbols: Convert operators to function names
    replace_synonyms: Handle common spelling variants
    prefix_logical_functions: Convert infix logic to prefix notation
    prefix_emdas: Convert infix arithmetic to prefix notation with PEMDAS
"""

from dataclasses import dataclass, field
from typing import List, Union, Dict, Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class ParseToken:
    """
    Represents a parsed DCEC expression as a tree structure.
    
    Attributes:
        func_name: The function name or operator
        args: List of arguments (strings or nested ParseTokens)
        depth: Cached depth of the tree (calculated lazily)
        width: Cached width of the tree (calculated lazily)
        s_expression: Cached S-expression representation
        f_expression: Cached F-expression representation
    """
    func_name: str
    args: List[Union[str, 'ParseToken']]
    depth: Optional[int] = field(default=None, init=False)
    width: Optional[int] = field(default=None, init=False)
    s_expression: Optional[str] = field(default=None, init=False)
    f_expression: Optional[str] = field(default=None, init=False)
    
    def depth_of(self) -> int:
        """
        Calculate the depth of the parse tree.
        
        Returns:
            int: The maximum depth from this node to any leaf
        """
        if self.depth is not None:
            return self.depth
        
        temp = []
        for arg in self.args:
            if isinstance(arg, ParseToken):
                temp.append(arg)
        
        if len(temp) == 0:
            self.depth = 1
        else:
            self.depth = 1 + max([x.depth_of() for x in temp])
        
        return self.depth
    
    def width_of(self) -> int:
        """
        Calculate the width of the parse tree (number of leaf nodes).
        
        Returns:
            int: The total number of leaf nodes
        """
        if self.width is not None:
            return self.width
        
        temp = 0
        for arg in self.args:
            if isinstance(arg, str):
                temp += 1
            else:
                temp += arg.width_of()
        
        self.width = temp
        return self.width
    
    def create_s_expression(self) -> str:
        """
        Create S-expression representation: (funcName arg1 arg2 ...)
        
        Returns:
            str: The S-expression string
        """
        if self.s_expression is not None:
            return self.s_expression
        
        self.s_expression = "(" + self.func_name + " "
        for arg in self.args:
            if isinstance(arg, str):
                self.s_expression += arg + " "
            else:
                arg.create_s_expression()
                self.s_expression += (arg.s_expression or "") + " "
        
        self.s_expression = self.s_expression.strip()
        self.s_expression += ")"
        
        return self.s_expression
    
    def create_f_expression(self) -> str:
        """
        Create F-expression representation: funcName(arg1, arg2, ...)
        
        Returns:
            str: The F-expression string
        """
        if self.f_expression is not None:
            return self.f_expression
        
        self.f_expression = self.func_name + "("
        for arg in self.args:
            if isinstance(arg, str):
                self.f_expression += arg + ","
            else:
                arg.create_f_expression()
                self.f_expression += (arg.f_expression or "") + ","
        
        self.f_expression = self.f_expression.strip(",")
        self.f_expression += ")"
        
        return self.f_expression
    
    def print_tree(self) -> None:
        """Print the F-expression representation of this token."""
        self.create_s_expression()
        self.create_f_expression()
        print(self.f_expression)
    
    def __str__(self) -> str:
        """String representation uses F-expression format."""
        return self.create_f_expression()
    
    def __repr__(self) -> str:
        """Repr shows both func_name and args."""
        return f"ParseToken(func_name={self.func_name!r}, args={self.args!r})"


def remove_comments(expression: str) -> str:
    """
    Remove semicolon comments from a DCEC expression.
    
    Args:
        expression: The DCEC expression that may contain comments
        
    Returns:
        str: The expression with semicolon comments removed
        
    Examples:
        >>> remove_comments("(and a b) ; this is a comment")
        '(and a b) '
        >>> remove_comments("no comment here")
        'no comment here'
    """
    index = expression.find(";")
    if index != -1:
        expression = expression[:index]
    
    if len(expression) == 0:
        expression = ""
    
    return expression


def functorize_symbols(expression: str) -> str:
    """
    Replace all symbols with the appropriate internal function name.
    
    Some symbols are left untouched as they have multiple interpretations
    in the DCEC syntax. For example, * can represent both multiplication
    and the self operator.
    
    Args:
        expression: The DCEC expression containing symbols
        
    Returns:
        str: The expression with symbols replaced by function names
        
    Examples:
        >>> functorize_symbols("a -> b")
        'a  implies  b'
        >>> functorize_symbols("x + y")
        'x  add  y'
    """
    symbols = ["^", "*", "/", "+", "<->", "->", "-", "&", "|", "~", ">=", "==", "<=", "===", "=", ">", "<"]
    symbol_map = {
        "^": "exponent",
        "*": "*",
        "/": "divide",
        "+": "add",
        "-": "-",
        "&": "&",
        "|": "|",
        "~": "not",
        "->": "implies",
        "<->": "ifAndOnlyIf",
        ">": "greater",
        "<": "less",
        ">=": "greaterOrEqual",
        "<=": "lessOrEqual",
        "=": "equals",
        "==": "equals",
        "===": "tautology",
    }
    
    returner = expression
    for symbol in symbols:
        returner = returner.replace(symbol, " " + symbol_map[symbol] + " ")
    
    returner = returner.replace("( ", "(")
    
    return returner


def replace_synonyms(args: List[Union[str, ParseToken]]) -> None:
    """
    Replace common spelling errors and synonyms in the argument list.
    
    These are common spelling variations that users demand the parser
    takes care of. Modifies the args list in place.
    
    Args:
        args: List of arguments (modified in place)
        
    Examples:
        >>> args = ["forall", "x", "P"]
        >>> replace_synonyms(args)
        >>> args
        ['forAll', 'x', 'P']
    """
    synonym_map = {
        "ifAndOnlyIf": "iff",
        "if": "implies",
        "Time": "Moment",
        "forall": "forAll",
        "Forall": "forAll",
        "ForAll": "forAll",
        "Exists": "exists",
    }
    
    for arg in range(len(args)):
        arg_val = args[arg]
        if isinstance(arg_val, str) and arg_val in synonym_map.keys():
            logger.warning(
                f"Replaced the common misspelling {arg_val} with "
                f"the correct name {synonym_map[arg_val]}"
            )
            args[arg] = synonym_map[arg_val]


def prefix_logical_functions(
    args: List[Union[str, ParseToken]], 
    add_atomics: Dict[str, List[str]]
) -> List[Union[str, ParseToken]]:
    """
    Convert infix logical notation to prefix notation.
    
    Assumes standard logical order of operations and converts infix
    operators to prefix ParseTokens.
    
    Args:
        args: List of arguments in potentially infix notation
        add_atomics: Dictionary to track atomic types for sort inference
        
    Returns:
        List[Union[str, ParseToken]]: Arguments converted to prefix notation
        
    Examples:
        >>> args = ["a", "and", "b"]
        >>> atomics = {}
        >>> result = prefix_logical_functions(args, atomics)
        >>> isinstance(result[0], ParseToken)
        True
    """
    logic_keywords = ["not", "and", "or", "xor", "implies", "iff"]
    
    # Handle unary prefix: ["not", operand] → [ParseToken("not", [operand])]
    if len(args) == 2 and isinstance(args[0], str) and args[0] == "not":
        operand = args[1]
        if isinstance(operand, str) and operand not in logic_keywords:
            if operand in add_atomics:
                add_atomics[operand].append("Boolean")
            else:
                add_atomics[operand] = ["Boolean"]
            return [ParseToken("not", [operand])]

    # Check for infix notation
    if len(args) < 3:
        return args
    
    # Check for infix notation - order of operations only needed in infix
    if args[-2] not in logic_keywords:
        return args
    
    # Warn about ambiguous not statements
    for arg in range(len(args)):
        if (args[arg] == "not" and arg + 2 < len(args) and 
            args[arg + 1] not in logic_keywords):
            logger.warning(
                "Ambiguous not statement. This parser assumes standard order "
                "of logical operations. Please use prefix notation or "
                "parentheses to resolve this ambiguity."
            )
    
    for word in logic_keywords:
        while word in args:
            index = args.index(word)
            
            if word == "not":
                new_token = ParseToken(word, [args[index + 1]])
                # Assign sorts to the atomics used
                arg_val = args[index + 1]
                if isinstance(arg_val, str):
                    if arg_val in add_atomics:
                        add_atomics[arg_val].append("Boolean")
                    else:
                        add_atomics[arg_val] = ["Boolean"]
                # Replace infix notation with tokenized representation
                args = args[:index + 1] + args[index + 2:]
                args[index] = new_token
                break
            
            in1 = index - 1
            in2 = index + 1
            
            # If the thing is actually prefix anyway
            if in1 < 0:
                break
            
            # Tuck the logical expression into a token
            new_token = ParseToken(word, [args[in1], args[in2]])
            
            # Assign sorts to the atomics used
            arg_in1 = args[in1]
            arg_in2 = args[in2]
            
            if isinstance(arg_in1, str):
                if arg_in1 in add_atomics:
                    add_atomics[arg_in1].append("Boolean")
                else:
                    add_atomics[arg_in1] = ["Boolean"]
            
            if isinstance(arg_in2, str):
                if arg_in2 in add_atomics:
                    add_atomics[arg_in2].append("Boolean")
                else:
                    add_atomics[arg_in2] = ["Boolean"]
            
            # Replace the args used in the token with the token
            args = args[:in1] + args[in2:]
            args[in1] = new_token
    
    return args


def prefix_emdas(
    args: List[Union[str, ParseToken]], 
    add_atomics: Dict[str, List[str]]
) -> List[Union[str, ParseToken]]:
    """
    Convert infix arithmetic notation to prefix using PEMDAS order of operations.
    
    Args:
        args: List of arguments in potentially infix notation
        add_atomics: Dictionary to track atomic types for sort inference
        
    Returns:
        List[Union[str, ParseToken]]: Arguments converted to prefix notation
        
    Examples:
        >>> args = ["x", "add", "y"]
        >>> atomics = {}
        >>> result = prefix_emdas(args, atomics)
        >>> isinstance(result[0], ParseToken)
        True
    """
    arithmetic_keywords = ["negate", "exponent", "multiply", "divide", "add", "sub"]
    
    # Handle unary prefix: ["negate", operand] → [ParseToken("negate", [operand])]
    if len(args) == 2 and isinstance(args[0], str) and args[0] == "negate":
        operand = args[1]
        if isinstance(operand, str) and operand not in arithmetic_keywords:
            if operand in add_atomics:
                add_atomics[operand].append("Numeric")
            else:
                add_atomics[operand] = ["Numeric"]
            return [ParseToken("negate", [operand])]

    # Check for infix notation
    if len(args) < 3:
        return args
    
    # Check for infix notation - PEMDAS only needed in infix
    if args[-2] not in arithmetic_keywords:
        return args
    
    for word in arithmetic_keywords:
        while word in args:
            index = args.index(word)
            
            if word == "negate":
                new_token = ParseToken(word, [args[index + 1]])
                # Assign sorts to the atomics used
                arg_val = args[index + 1]
                if isinstance(arg_val, str):
                    if arg_val in add_atomics:
                        add_atomics[arg_val].append("Numeric")
                    else:
                        add_atomics[arg_val] = ["Numeric"]
                # Replace notation with token
                args = args[:index + 1] + args[index + 2:]
                args[index] = new_token
                break
            
            in1 = index - 1
            in2 = index + 1
            
            # If actually prefix already
            if in1 < 0:
                break
            
            # Tuck the arithmetic expression into a token
            new_token = ParseToken(word, [args[in1], args[in2]])
            
            # Assign sorts to the atomics used
            arg_in1 = args[in1]
            arg_in2 = args[in2]
            
            if isinstance(arg_in1, str):
                if arg_in1 in add_atomics:
                    add_atomics[arg_in1].append("Numeric")
                else:
                    add_atomics[arg_in1] = ["Numeric"]
            
            if isinstance(arg_in2, str):
                if arg_in2 in add_atomics:
                    add_atomics[arg_in2].append("Numeric")
                else:
                    add_atomics[arg_in2] = ["Numeric"]
            
            # Replace the args with the token
            args = args[:in1] + args[in2:]
            args[in1] = new_token
    
    return args
