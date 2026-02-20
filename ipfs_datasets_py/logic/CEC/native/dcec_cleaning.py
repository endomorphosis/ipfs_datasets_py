"""
DCEC Expression Cleaning Utilities

This module provides utilities for cleaning and normalizing DCEC expressions.
Ported from DCEC_Library/cleaning.py to pure Python 3.

Functions:
    strip_whitespace: Normalize whitespace and commas in expressions
    strip_comments: Remove # comments from expressions
    consolidate_parens: Remove redundant parentheses
    check_parens: Validate balanced parentheses
    get_matching_close_paren: Find matching closing parenthesis
    tuck_functions: Transform function notation B(args) to (B args)
"""

from typing import Optional
import logging
import re

logger = logging.getLogger(__name__)


def strip_whitespace(expression: str) -> str:
    """
    Strip unnecessary whitespace from a DCEC expression.
    
    Normalizes whitespace and transforms all argument separators (spaces and commas)
    into comma-separated format. Also handles special bracket notation.
    
    Args:
        expression: The DCEC expression to clean
        
    Returns:
        str: The expression with normalized whitespace
        
    Examples:
        >>> strip_whitespace("  ( a  b  c )  ")
        '(a,b,c)'
        >>> strip_whitespace("func( arg1 , arg2 )")
        'func(arg1,arg2)'
    """
    # Strip the whitespace around the expression
    temp = expression.strip()
    
    # Brackets have special notation, they are bracket-ish
    temp = temp.replace("[", " [")
    temp = temp.replace("]", "] ")
    
    # Treat commas and spaces identically
    temp = temp.replace(",", " ")
    
    # Strip whitespace iteratively until no more changes
    while True:
        length_pre = len(temp)
        temp = temp.replace("  ", " ")
        temp = temp.replace("( ", "(")
        temp = temp.replace(" )", ")")
        length_post = len(temp)
        if length_pre == length_post:
            break
    
    # Find any touching parens, they should have a space between them
    temp = temp.replace(")(", ") (")
    
    # Convert spaces to commas for consistency
    temp = temp.replace(" ", ",")
    
    return temp


def strip_comments(expression: str) -> str:
    """
    Remove # comments from a DCEC expression.
    
    Args:
        expression: The DCEC expression that may contain comments
        
    Returns:
        str: The expression with comments removed
        
    Examples:
        >>> strip_comments("(and a b) # this is a comment")
        '(and a b) '
        >>> strip_comments("no comment here")
        'no comment here'
    """
    place = expression.find("#")
    if place == -1:
        return expression
    else:
        return expression[:place]


def consolidate_parens(expression: str) -> str:
    """
    Remove superfluous parentheses from an expression.
    
    Returns a string identical to the input except all redundant parentheses are
    removed. Will also put parens around the outside of the expression if it
    does not already have them. Will not detect a paren mismatch error.
    
    Args:
        expression: The DCEC expression to clean
        
    Returns:
        str: The expression with redundant parentheses removed
        
    Examples:
        >>> consolidate_parens("((a))")
        '(a)'
        >>> consolidate_parens("((and a b))")
        '(and a b)'
    """
    temp = "(" + expression + ")"
    # List of indexes to delete
    delete_list = []
    # Location of first paren
    first_paren_a = 0
    
    # Looks through entire expression
    while first_paren_a < len(temp):
        # Find every occurrence of a "(("
        first_paren_a = temp.find("((", first_paren_a)
        first_paren_b = first_paren_a + 1
        if first_paren_a == -1:
            break
        
        # Get the matching close parens
        second_paren_a = get_matching_close_paren(temp, first_paren_a)
        second_paren_b = get_matching_close_paren(temp, first_paren_b)
        
        # If both the open parens and the close parens match, one set is unnecessary
        if second_paren_a is not None and second_paren_b is not None:
            if second_paren_a == second_paren_b + 1:
                delete_list.append(first_paren_a)
                delete_list.append(second_paren_a)
        
        first_paren_a += 1
    
    # Make the string to return
    returner = ""
    for x in range(len(temp)):
        if x in delete_list:
            continue
        returner += temp[x]
    
    # Additional pass: remove redundant single-atom parens like (a) → a
    # but only inside a multi-element expression (i.e., when the result has spaces).
    # This avoids stripping the outermost wrapper from a lone atomic like "(a)".
    if ' ' in returner:
        _inner_atom_re = re.compile(r'(?<![A-Za-z0-9_])\(([A-Za-z_][A-Za-z0-9_]*)\)(?![A-Za-z0-9_])')
        prev = None
        while prev != returner:
            prev = returner
            returner = _inner_atom_re.sub(r'\1', returner)

    return returner


def check_parens(expression: str) -> bool:
    """
    Check if an expression has balanced parentheses.
    
    Returns True if there are an equal number of left and right parentheses,
    and False if there are not.
    
    Args:
        expression: The DCEC expression to check
        
    Returns:
        bool: True if parentheses are balanced, False otherwise
        
    Examples:
        >>> check_parens("(and a b)")
        True
        >>> check_parens("(and a b")
        False
        >>> check_parens("and a b)")
        False
    """
    return expression.count("(") == expression.count(")")


def get_matching_close_paren(input_str: str, open_paren_index: int = 0) -> Optional[int]:
    """
    Find the index of the matching closing parenthesis.
    
    Args:
        input_str: The string to search in
        open_paren_index: The index of the opening parenthesis
        
    Returns:
        Optional[int]: The index of the matching close paren, or False if not found
        
    Examples:
        >>> get_matching_close_paren("(a (b c) d)", 0)
        10
        >>> get_matching_close_paren("(a (b c) d)", 3)
        7
    """
    paren_counter = 1
    current_index = open_paren_index
    
    if current_index == -1:
        return None
    
    while paren_counter > 0:
        close_index = input_str.find(")", current_index + 1)
        open_index = input_str.find("(", current_index + 1)
        
        if (open_index < close_index or close_index == -1) and open_index != -1:
            current_index = open_index
            paren_counter += 1
        elif (close_index < open_index or open_index == -1) and close_index != -1:
            current_index = close_index
            paren_counter -= 1
        else:
            return None
    
    return current_index


def tuck_functions(expression: str) -> str:
    """
    Transform function calls from B(args) to (B args) notation.
    
    This makes it easier to keep tokens on the same level by converting
    F-expression notation to S-expression notation.
    
    Args:
        expression: The DCEC expression with function calls
        
    Returns:
        str: The expression with function calls transformed
        
    Examples:
        >>> tuck_functions("B(a,b)")
        '(B,a,b)'
        >>> tuck_functions("not(P)")
        '(not,(P))'
    """
    first_paren = 0
    new_index = 0
    adder = ""
    temp = ""
    
    # Find the parentheses
    while first_paren < len(expression):
        first_paren = expression.find("(", first_paren)
        if first_paren == -1:
            break
        
        if not (expression[first_paren - 1] in [",", " ", "(", ")"]):
            func_start = first_paren - 1
            while func_start >= 0:
                if expression[func_start] == "," or expression[func_start] == "(":
                    func_start += 1
                    break
                func_start -= 1
            
            if func_start == -1:
                func_start = 0
            
            funcname = expression[func_start:first_paren]
            
            if funcname in ["not", "negate"]:
                adder = expression[new_index:func_start] + "(" + funcname + ",("
                close_paren_place = get_matching_close_paren(
                    expression, func_start + len(funcname)
                )
                if close_paren_place is not None:
                    expression = (
                        expression[:func_start]
                        + expression[func_start:close_paren_place]
                        + "))"
                        + expression[close_paren_place + 1:]
                    )
                temp += adder
                new_index += len(adder) - 2
            else:
                adder = expression[new_index:func_start] + "(" + funcname + ","
                temp += adder
                new_index += len(adder) - 1
        
        first_paren += 1
    
    returner = temp + expression[new_index:]
    returner = returner.replace("``", "`")
    returner = returner.replace(",,", ",")
    returner = returner.replace("`", " ")
    
    return returner


def clean_dcec_expression(text: str) -> str:
    """Normalize a DCEC/DCEC-like expression string.

    This is a convenience wrapper used by higher-level APIs/tests.
    It applies the standard cleaning steps in a predictable order.
    """
    text = strip_comments(text)
    text = strip_whitespace(text)
    text = consolidate_parens(text)
    return text
