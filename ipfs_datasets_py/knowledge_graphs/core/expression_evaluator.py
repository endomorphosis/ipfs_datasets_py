"""Expression evaluation helpers for query execution.

This module centralizes evaluation of compiled expressions (from the Cypher
compiler) and legacy string expressions used by the query execution layer.

It is intentionally stateless: all functions operate purely on provided inputs.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from ..exceptions import KnowledgeGraphError

logger = logging.getLogger(__name__)


def apply_operator(left: Any, operator: str, right: Any) -> bool:
    """Apply a comparison/string operator."""
    try:
        operator = operator.upper()

        # Equality operators
        if operator == "=":
            return left == right
        elif operator in ("<>", "!="):
            return left != right

        # Comparison operators
        elif operator == ">":
            return left > right
        elif operator == "<":
            return left < right
        elif operator == ">=":
            return left >= right
        elif operator == "<=":
            return left <= right

        # IN operator - check membership in list
        elif operator == "IN":
            if isinstance(right, list):
                return left in right
            return False

        # String operators
        elif operator == "CONTAINS":
            if isinstance(left, str) and isinstance(right, str):
                return right in left
            return False

        elif operator in ("STARTS", "STARTS WITH"):
            if isinstance(left, str) and isinstance(right, str):
                return left.startswith(right)
            return False

        elif operator in ("ENDS", "ENDS WITH"):
            if isinstance(left, str) and isinstance(right, str):
                return left.endswith(right)
            return False

        logger.warning("Unknown operator: %s", operator)
        return False

    except (TypeError, ValueError, AttributeError) as e:
        logger.debug("Operator %s failed: %s", operator, e)
        return False


def call_function(func_name: str, args: List[Any]) -> Any:
    """Call a built-in function."""
    func_name_lower = func_name.lower()

    # Try function registry first (math, spatial, temporal)
    from ..cypher.functions import FUNCTION_REGISTRY

    if func_name_lower in FUNCTION_REGISTRY:
        try:
            func = FUNCTION_REGISTRY[func_name_lower]
            if len(args) == 1:
                return func(args[0])
            elif len(args) > 1:
                return func(*args)
            return func()
        except KnowledgeGraphError:
            raise
        except (AttributeError, TypeError, ValueError, KeyError, ZeroDivisionError, OverflowError) as e:
            logger.warning("Function %s raised exception: %s", func_name, e)
            return None
        except Exception as e:
            logger.warning("Function %s raised exception: %s", func_name, e)
            return None

    # String functions (existing implementation)
    if func_name_lower == "tolower":
        if args and isinstance(args[0], str):
            return args[0].lower()
        return None

    if func_name_lower == "toupper":
        if args and isinstance(args[0], str):
            return args[0].upper()
        return None

    if func_name_lower == "substring":
        if len(args) >= 2 and isinstance(args[0], str):
            string = args[0]
            start = args[1] if isinstance(args[1], int) else 0
            if len(args) >= 3 and isinstance(args[2], int):
                length = args[2]
                return string[start : start + length]
            return string[start:]
        return None

    if func_name_lower == "trim":
        if args and isinstance(args[0], str):
            return args[0].strip()
        return None

    if func_name_lower == "ltrim":
        if args and isinstance(args[0], str):
            return args[0].lstrip()
        return None

    if func_name_lower == "rtrim":
        if args and isinstance(args[0], str):
            return args[0].rstrip()
        return None

    if func_name_lower == "replace":
        if len(args) >= 3 and isinstance(args[0], str):
            string = args[0]
            search = str(args[1]) if args[1] is not None else ""
            replace = str(args[2]) if args[2] is not None else ""
            return string.replace(search, replace)
        return None

    if func_name_lower == "reverse":
        if args and isinstance(args[0], str):
            return args[0][::-1]
        return None

    if func_name_lower == "size":
        if args:
            if isinstance(args[0], str):
                return len(args[0])
            if isinstance(args[0], (list, tuple)):
                return len(args[0])
        return None

    if func_name_lower == "split":
        if len(args) >= 2 and isinstance(args[0], str):
            string = args[0]
            delimiter = str(args[1]) if args[1] is not None else ","
            return string.split(delimiter)
        return None

    if func_name_lower == "left":
        if len(args) >= 2 and isinstance(args[0], str) and isinstance(args[1], int):
            return args[0][: args[1]]
        return None

    if func_name_lower == "right":
        if len(args) >= 2 and isinstance(args[0], str) and isinstance(args[1], int):
            return args[0][-args[1] :]
        return None

    logger.warning("Unknown function: %s", func_name)
    return None


def evaluate_expression(expr: str, row: Dict[str, Any]) -> Any:
    """Evaluate an expression against a data row."""
    if expr.startswith("CASE|"):
        return evaluate_case_expression(expr, row)

    if "(" in expr and expr.endswith(")"):
        func_match = expr.find("(")
        func_name = expr[:func_match].strip()
        args_str = expr[func_match + 1 : -1].strip()

        if args_str:
            args: List[str] = []
            current_arg = ""
            paren_depth = 0
            for char in args_str:
                if char == "," and paren_depth == 0:
                    args.append(current_arg.strip())
                    current_arg = ""
                    continue
                if char == "(":
                    paren_depth += 1
                elif char == ")":
                    paren_depth -= 1
                current_arg += char
            if current_arg:
                args.append(current_arg.strip())

            eval_args: List[Any] = []
            for arg in args:
                if arg.isdigit():
                    eval_args.append(int(arg))
                elif (arg.startswith("'") and arg.endswith("'")) or (
                    arg.startswith('"') and arg.endswith('"')
                ):
                    eval_args.append(arg[1:-1])
                else:
                    eval_args.append(evaluate_expression(arg, row))
        else:
            eval_args = []

        return call_function(func_name, eval_args)

    if "." in expr:
        var, prop = expr.split(".", 1)
        if var in row:
            val = row[var]
            if hasattr(val, "get"):
                return val.get(prop)
            if hasattr(val, "_properties") and prop in val._properties:
                return val._properties[prop]
    elif expr in row:
        return row[expr]

    return None


def evaluate_case_expression(case_expr: str, row: Dict[str, Any]) -> Any:
    """Evaluate a serialized CASE expression."""
    parts = case_expr.split("|")
    if parts[0] != "CASE" or parts[-1] != "END":
        logger.warning("Invalid CASE expression format: %s", case_expr)
        return None

    test_expr = None
    when_clauses = []
    else_result = None

    i = 1
    while i < len(parts) - 1:
        part = parts[i]
        if part.startswith("TEST:"):
            test_expr = part[5:]
        elif part.startswith("WHEN:"):
            when_parts = part.split(":")
            if len(when_parts) >= 4 and when_parts[2] == "THEN":
                condition = when_parts[1]
                result = ":".join(when_parts[3:])
                when_clauses.append((condition, result))
        elif part.startswith("ELSE:"):
            else_result = part[5:]
        i += 1

    if test_expr:
        test_value = evaluate_expression(test_expr, row)
        for condition, result in when_clauses:
            when_value = evaluate_expression(condition, row)
            if test_value == when_value:
                return evaluate_expression(result, row)
    else:
        for condition, result in when_clauses:
            if evaluate_condition(condition, row):
                return evaluate_expression(result, row)

    if else_result:
        return evaluate_expression(else_result, row)
    return None


def evaluate_condition(condition: str, row: Dict[str, Any]) -> bool:
    """Evaluate a condition expression."""
    for op in [" >= ", " <= ", " <> ", " != ", " = ", " > ", " < "]:
        if op in condition:
            parts = condition.split(op, 1)
            if len(parts) == 2:
                left_val = evaluate_expression(parts[0].strip(), row)
                right_val = evaluate_expression(parts[1].strip(), row)
                return apply_operator(left_val, op.strip(), right_val)

    value = evaluate_expression(condition, row)
    return bool(value)


def evaluate_compiled_expression(expr: Any, binding: Dict[str, Any]) -> Any:
    """Evaluate a compiled expression (dict or string) against a binding."""
    if isinstance(expr, dict):
        if "function" in expr:
            func_name = expr["function"]
            args = expr.get("args", [])
            eval_args = [evaluate_compiled_expression(arg, binding) for arg in args]
            return call_function(func_name, eval_args)

        if "property" in expr:
            prop_path = expr["property"]
            if prop_path in binding:
                return binding[prop_path]
            if "." in prop_path:
                var, prop = prop_path.split(".", 1)
                if var in binding:
                    val = binding[var]
                    if hasattr(val, "get"):
                        return val.get(prop)
                    if hasattr(val, "_properties") and prop in val._properties:
                        return val._properties[prop]
            return None

        if "var" in expr:
            return binding.get(expr["var"])

        if "op" in expr:
            left = evaluate_compiled_expression(expr["left"], binding)
            right = evaluate_compiled_expression(expr["right"], binding)
            return apply_operator(left, expr["op"], right)

    if isinstance(expr, str):
        if expr in binding:
            return evaluate_expression(expr, binding)
        if "." in expr:
            parts = expr.split(".")
            if len(parts) == 2 and parts[0].isidentifier():
                return evaluate_expression(expr, binding)
            return expr
        return expr

    return expr
