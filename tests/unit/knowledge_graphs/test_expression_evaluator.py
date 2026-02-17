from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import (
    apply_operator,
    call_function,
    evaluate_case_expression,
    evaluate_compiled_expression,
    evaluate_condition,
    evaluate_expression,
)
from ipfs_datasets_py.knowledge_graphs.neo4j_compat.types import Node


def test_apply_operator_comparisons_and_strings():
    assert apply_operator(5, ">", 3) is True
    assert apply_operator(3, ">", 5) is False
    assert apply_operator(5, ">=", 5) is True
    assert apply_operator(5, "=", 5) is True
    assert apply_operator(5, "!=", 6) is True
    assert apply_operator("hello world", "CONTAINS", "world") is True
    assert apply_operator("hello", "STARTS WITH", "he") is True
    assert apply_operator("hello", "ENDS WITH", "lo") is True
    assert apply_operator("x", "IN", ["a", "x"]) is True


def test_evaluate_expression_property_and_functions():
    node = Node(1, labels=["Person"], properties={"age": 30, "name": "Alice"})
    row = {"n": node}

    assert evaluate_expression("n", row) == node
    assert evaluate_expression("n.age", row) == 30
    assert evaluate_expression("toLower(n.name)", row) == "alice"
    assert evaluate_expression("substring(n.name,1,2)", row) == "li"


def test_call_function_unknown_returns_none():
    assert call_function("definitelyNotAFunction", [1, 2, 3]) is None


def test_evaluate_condition_simple_comparisons():
    node = Node(1, labels=["Person"], properties={"age": 30, "min": 20})
    row = {"n": node}
    assert evaluate_condition("n.age > n.min", row) is True
    assert evaluate_condition("n.age < n.min", row) is False


def test_evaluate_case_expression_generic_case():
    node = Node(
        1, labels=["Person"], properties={"age": 30, "min": 20, "flag": "yes", "alt": "no"}
    )
    row = {"n": node}

    # Generic CASE (no TEST:), WHEN uses condition expressions.
    case_expr = "CASE|WHEN:n.age > n.min:THEN:n.flag|ELSE:n.alt|END"
    assert evaluate_case_expression(case_expr, row) == "yes"


def test_evaluate_compiled_expression_property_function_and_op():
    node = Node(1, labels=["Person"], properties={"age": 30, "name": "Alice"})
    binding = {"n": node}

    assert evaluate_compiled_expression({"property": "n.age"}, binding) == 30
    assert (
        evaluate_compiled_expression(
            {"function": "toLower", "args": [{"property": "n.name"}]},
            binding,
        )
        == "alice"
    )
    assert (
        evaluate_compiled_expression(
            {"op": ">", "left": {"property": "n.age"}, "right": 20},
            binding,
        )
        is True
    )


def test_evaluate_compiled_expression_string_literals_with_dots():
    binding = {"n": Node(1, labels=["Person"], properties={"age": 30})}
    assert evaluate_compiled_expression("test@example.com", binding) == "test@example.com"
    assert evaluate_compiled_expression("n.age", binding) == 30
