"""Shared bounded Boolean structure for explicit unary definitions.

Source selection and interpretation remain with each caller profile. Importing
this helper loads no native formula, model, compiler or source extraction owner.
"""

from __future__ import annotations


def build_boolean_expression(
    value,
    *,
    atom_builder,
    require,
    max_depth=12,
    max_nodes=128,
    max_operands=16,
):
    """Preserve caller atom/not/all/any order and the legacy left association."""
    from ..TDFOL import tdfol_core as t

    for offered, ceiling in (
        (max_depth, 12),
        (max_nodes, 128),
        (max_operands, 16),
    ):
        require(
            type(offered) is int and 0 < offered <= ceiling,
            "positive lowered definition expression bounds required",
        )
    count = 0

    def closed(node, keys, label):
        require(
            type(node) is dict and set(node) == set(keys),
            "closed " + label + " required",
        )

    def expression(node, depth=0):
        nonlocal count
        count += 1
        require(
            depth <= max_depth and count <= max_nodes and type(node) is dict,
            "bounded typed definition expression required",
        )
        op = node.get("op")
        if op == "atom":
            closed(node, ("op", "span"), "definition atom")
            return atom_builder(node["span"])
        if op == "not":
            closed(node, ("op", "operand"), "definition negation")
            return t.UnaryFormula(
                t.LogicOperator.NOT, expression(node["operand"], depth + 1)
            )
        require(
            op in ("all", "any"),
            "unsupported definition expression; no modalities, quantifier erasure or temporal reification",
        )
        closed(node, ("op", "operands"), "definition Boolean expression")
        require(
            type(node["operands"]) is list
            and 2 <= len(node["operands"]) <= max_operands,
            "bounded nontrivial Boolean operands required",
        )
        operands = [expression(child, depth + 1) for child in node["operands"]]
        result = operands[0]
        for operand in operands[1:]:
            result = t.BinaryFormula(
                t.LogicOperator.AND if op == "all" else t.LogicOperator.OR,
                result,
                operand,
            )
        return result

    return expression(value)


__all__ = ["build_boolean_expression"]
