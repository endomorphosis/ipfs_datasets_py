"""Property and unit tests for expression algebra (LFP-013).

Covers:

* free / bound variable analysis
* alpha-equivalence and shared semantic identity
* capture-avoiding substitution (never captures free variables)
* alpha-rename under shadowing and nested binders
* adversarial capture terms
* substitution idempotence
* bounded traversal (node and depth limits)
"""

from __future__ import annotations

import itertools

import pytest

from ipfs_datasets_py.logic.syntax_core.algebra import (
    ALGEBRA_MODULE_VERSION,
    DEFAULT_ALGEBRA,
    LOGIC_EXPRESSION_ALGEBRA_INTERFACE,
    AlgebraError,
    AlgebraLimits,
    LogicExpressionAlgebra,
    alpha_equivalent,
    bound_variables,
    free_variables,
    semantic_identity,
    substitute,
    walk_bounded,
)
from ipfs_datasets_py.logic.syntax_core.ast import (
    Binder,
    LogicNode,
    NodeKind,
    mk_and,
    mk_application,
    mk_constant,
    mk_equality,
    mk_exists,
    mk_extension,
    mk_false,
    mk_forall,
    mk_implies,
    mk_let,
    mk_not,
    mk_or,
    mk_predicate,
    mk_true,
    mk_variable,
)
from ipfs_datasets_py.logic.syntax_core.signatures import atomic_sort


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _person():
    return atomic_sort("Person")


def _var(name: str, node_id: str | None = None, sort=None) -> LogicNode:
    return mk_variable(node_id or f"n:v:{name}", name, sort or _person())


def _const(name: str, node_id: str | None = None, sort=None) -> LogicNode:
    return mk_constant(node_id or f"n:c:{name}", name, sort or _person())


def _pred(symbol: str, *args: LogicNode, node_id: str | None = None) -> LogicNode:
    return mk_predicate(node_id or f"n:p:{symbol}", symbol, args)


def _forall(names: list[str], body: LogicNode, node_id: str = "n:all") -> LogicNode:
    binders = tuple(Binder(name=n, sort=_person()) for n in names)
    return mk_forall(node_id, binders, body)


def _exists(names: list[str], body: LogicNode, node_id: str = "n:ex") -> LogicNode:
    binders = tuple(Binder(name=n, sort=_person()) for n in names)
    return mk_exists(node_id, binders, body)


def _assert_fv_property(expr: LogicNode, var: str, term: LogicNode) -> LogicNode:
    """Assert the free-variable law of capture-avoiding substitution."""

    alg = DEFAULT_ALGEBRA
    fv_e = alg.free_variables(expr)
    fv_t = alg.free_variables(term)
    result = alg.substitute(expr, var, term)
    fv_r = alg.free_variables(result)
    if var not in fv_e:
        assert fv_r == fv_e
    else:
        assert fv_r == (fv_e - {var}) | fv_t
    return result


# ---------------------------------------------------------------------------
# Module / interface identity
# ---------------------------------------------------------------------------


def test_module_version_and_interface() -> None:
    assert ALGEBRA_MODULE_VERSION == "1.0.0"
    assert LOGIC_EXPRESSION_ALGEBRA_INTERFACE == "LogicExpressionAlgebra@1"
    assert DEFAULT_ALGEBRA.interface == LOGIC_EXPRESSION_ALGEBRA_INTERFACE
    restored = LogicExpressionAlgebra.from_dict(DEFAULT_ALGEBRA.to_dict())
    assert restored.limits.max_nodes == DEFAULT_ALGEBRA.limits.max_nodes


# ---------------------------------------------------------------------------
# Free / bound variables
# ---------------------------------------------------------------------------


def test_free_and_bound_variables_basic() -> None:
    x = _var("x")
    y = _var("y")
    # ∀x. P(x, y)  — x bound, y free
    formula = _forall(["x"], _pred("P", x, y))
    assert free_variables(formula) == frozenset({"y"})
    assert bound_variables(formula) == frozenset({"x"})
    assert free_variables(x) == frozenset({"x"})
    assert free_variables(_const("alice")) == frozenset()


def test_free_variables_shadowing_and_let() -> None:
    x = _var("x")
    y = _var("y")
    # let x = y in P(x)  — y free, x bound in body
    let_node = mk_let(
        "n:let",
        Binder(name="x", sort=_person()),
        y,
        _pred("P", x),
    )
    assert free_variables(let_node) == frozenset({"y"})
    assert "x" in bound_variables(let_node)

    # Nested: ∀x. ∃x. P(x) — only inner x binds the occurrence
    inner = _exists(["x"], _pred("P", x), node_id="n:inner")
    outer = _forall(["x"], inner, node_id="n:outer")
    assert free_variables(outer) == frozenset()
    assert bound_variables(outer) == frozenset({"x"})


def test_free_variables_nested_binders() -> None:
    x, y, z = _var("x"), _var("y"), _var("z")
    # ∀x. ∃y. P(x, y, z)
    body = _pred("R", x, y, z)
    formula = _forall(["x"], _exists(["y"], body))
    assert free_variables(formula) == frozenset({"z"})
    assert bound_variables(formula) == frozenset({"x", "y"})


# ---------------------------------------------------------------------------
# Alpha-equivalence and semantic identity
# ---------------------------------------------------------------------------


def test_alpha_equivalent_renamed_binders() -> None:
    # ∀x. P(x)  ~  ∀y. P(y)
    left = _forall(["x"], _pred("P", _var("x")), node_id="n:l")
    right = _forall(["y"], _pred("P", _var("y")), node_id="n:r")
    assert alpha_equivalent(left, right)
    assert semantic_identity(left) == semantic_identity(right)

    # ∀x. P(x, y)  !~  ∀y. P(y, y)  (free y vs bound)
    left2 = _forall(["x"], _pred("P", _var("x"), _var("y")), node_id="n:l2")
    right2 = _forall(["y"], _pred("P", _var("y"), _var("y")), node_id="n:r2")
    assert not alpha_equivalent(left2, right2)
    assert semantic_identity(left2) != semantic_identity(right2)


def test_alpha_equivalent_nested_and_shadowing() -> None:
    # ∀x. ∃y. R(x, y)  ~  ∀a. ∃b. R(a, b)
    left = _forall(
        ["x"],
        _exists(["y"], _pred("R", _var("x"), _var("y")), node_id="n:e1"),
        node_id="n:a1",
    )
    right = _forall(
        ["a"],
        _exists(["b"], _pred("R", _var("a"), _var("b")), node_id="n:e2"),
        node_id="n:a2",
    )
    assert alpha_equivalent(left, right)
    assert semantic_identity(left) == semantic_identity(right)

    # Shadowing: ∀x. ∃x. P(x)  ~  ∀y. ∃z. P(z)
    left_s = _forall(
        ["x"],
        _exists(["x"], _pred("P", _var("x")), node_id="n:es"),
        node_id="n:as",
    )
    right_s = _forall(
        ["y"],
        _exists(["z"], _pred("P", _var("z")), node_id="n:es2"),
        node_id="n:as2",
    )
    assert alpha_equivalent(left_s, right_s)
    assert semantic_identity(left_s) == semantic_identity(right_s)


def test_alpha_equivalent_let_and_connectives() -> None:
    left = mk_let(
        "n:l",
        Binder(name="x", sort=_person()),
        _const("alice"),
        _pred("Human", _var("x")),
    )
    right = mk_let(
        "n:r",
        Binder(name="z", sort=_person()),
        _const("alice"),
        _pred("Human", _var("z")),
    )
    assert alpha_equivalent(left, right)
    assert semantic_identity(left) == semantic_identity(right)

    p = _pred("P")
    q = _pred("Q")
    assert alpha_equivalent(mk_and("n:a1", p, q), mk_and("n:a2", p, q))
    assert not alpha_equivalent(mk_and("n:a1", p, q), mk_or("n:o1", p, q))


def test_semantic_identity_ignores_node_ids_and_is_stable() -> None:
    a = _forall(["x"], _pred("P", _var("x")), node_id="n:1")
    b = _forall(["x"], _pred("P", _var("x")), node_id="n:totally-different")
    assert semantic_identity(a) == semantic_identity(b)
    # Deterministic across calls.
    assert semantic_identity(a) == semantic_identity(a)


def test_alpha_rename_binder_preserves_semantic_identity() -> None:
    alg = DEFAULT_ALGEBRA
    original = _forall(["x"], _pred("P", _var("x"), _var("y")))
    renamed = alg.alpha_rename_binder(original, "x", "z")
    assert alpha_equivalent(original, renamed)
    assert semantic_identity(original) == semantic_identity(renamed)
    assert free_variables(renamed) == frozenset({"y"})
    # Capture rejection: renaming binder to free name y would capture.
    with pytest.raises(AlgebraError, match="capture"):
        alg.alpha_rename_binder(original, "x", "y")


def test_alpha_rename_binder_avoids_nested_capture() -> None:
    """∀x. ∃z. P(x) renamed x→z must keep the outer binder visible in P."""

    alg = DEFAULT_ALGEBRA
    # ∀x. ∃z. P(x)  — P mentions the outer binder only
    original = _forall(
        ["x"],
        _exists(["z"], _pred("P", _var("x")), node_id="n:ex"),
        node_id="n:all",
    )
    renamed = alg.alpha_rename_binder(original, "x", "z")
    assert alpha_equivalent(original, renamed)
    assert semantic_identity(original) == semantic_identity(renamed)
    # Outer binder is z; inner must be renamed so P refers to outer.
    assert renamed.binders[0].name == "z"
    inner = renamed.arguments[0]
    assert inner.kind is NodeKind.EXISTS
    assert inner.binders[0].name != "z"
    assert inner.arguments[0].arguments[0].symbol == "z"


# ---------------------------------------------------------------------------
# Capture-avoiding substitution
# ---------------------------------------------------------------------------


def test_substitute_simple_and_idempotent() -> None:
    # P(x)[x := alice] => P(alice)
    expr = _pred("P", _var("x"))
    term = _const("alice")
    result = _assert_fv_property(expr, "x", term)
    assert result.arguments[0].kind is NodeKind.CONSTANT
    assert result.arguments[0].symbol == "alice"

    # Idempotence: substituting a closed term twice is stable under alpha.
    again = substitute(result, "x", term)
    assert alpha_equivalent(result, again)

    # e[x := x] ~ e
    identity = substitute(expr, "x", _var("x"))
    assert alpha_equivalent(expr, identity)


def test_substitute_under_binder_no_capture() -> None:
    # Classic: (∀y. P(x, y))[x := y]  must NOT yield ∀y. P(y, y)
    # Capture-avoiding: ∀y'. P(y, y')  (or similar fresh)
    body = _pred("P", _var("x"), _var("y"))
    expr = _forall(["y"], body)
    term = _var("y")  # free y
    result = _assert_fv_property(expr, "x", term)

    # Free vars: original FV = {x}; after: {y}
    assert free_variables(result) == frozenset({"y"})
    # Must still be a quantifier.
    assert result.kind is NodeKind.FORALL
    binder_name = result.binders[0].name
    # Binder must have been renamed away from y.
    assert binder_name != "y"
    # Body should be P(y, binder_name)
    pred = result.arguments[0]
    assert pred.kind is NodeKind.PREDICATE
    assert pred.arguments[0].symbol == "y"
    assert pred.arguments[1].symbol == binder_name
    # Not alpha-equivalent to the captured form ∀y. P(y, y)
    captured = _forall(["y"], _pred("P", _var("y"), _var("y")))
    assert not alpha_equivalent(result, captured)


def test_substitute_shadowed_variable_unchanged() -> None:
    # (∀x. P(x))[x := alice]  =>  ∀x. P(x)  (x not free)
    expr = _forall(["x"], _pred("P", _var("x")))
    term = _const("alice")
    result = _assert_fv_property(expr, "x", term)
    assert alpha_equivalent(expr, result)


def test_substitute_let_capture_avoidance() -> None:
    # (let y = a in P(x, y))[x := y]  must rename y binder
    expr = mk_let(
        "n:let",
        Binder(name="y", sort=_person()),
        _const("a"),
        _pred("P", _var("x"), _var("y")),
    )
    result = _assert_fv_property(expr, "x", _var("y"))
    assert free_variables(result) == frozenset({"y"})
    assert result.binders[0].name != "y"
    # Bound value is outside binder: still constant a
    assert result.arguments[0].symbol == "a"


def test_substitute_nested_binders_adversarial() -> None:
    # (∀y. ∃z. R(x, y, z))[x := f(y, z)]
    # Both y and z free in replacement — both binders must be renamed.
    x, y, z = _var("x"), _var("y"), _var("z")
    body = _pred("R", x, y, z)
    expr = _forall(["y"], _exists(["z"], body, node_id="n:ex"), node_id="n:all")
    term = mk_application(
        "n:f",
        "f",
        (_var("y"), _var("z")),
        sort=_person(),
    )
    result = _assert_fv_property(expr, "x", term)
    assert free_variables(result) == frozenset({"y", "z"})

    # Walk binders: neither should be y or z if they would capture.
    outer = result
    assert outer.kind is NodeKind.FORALL
    assert outer.binders[0].name not in {"y", "z"}
    inner = outer.arguments[0]
    assert inner.kind is NodeKind.EXISTS
    assert inner.binders[0].name not in {"y", "z"}
    # The application free vars remain free in the whole formula.
    assert "y" in free_variables(result)
    assert "z" in free_variables(result)


def test_substitute_many_simultaneous() -> None:
    alg = DEFAULT_ALGEBRA
    # P(x, y)[x := y, y := x]  simultaneous swap
    expr = _pred("P", _var("x"), _var("y"))
    result = alg.substitute_many(expr, {"x": _var("y"), "y": _var("x")})
    assert result.arguments[0].symbol == "y"
    assert result.arguments[1].symbol == "x"
    assert free_variables(result) == frozenset({"x", "y"})


def test_substitute_rejects_non_term_replacement() -> None:
    with pytest.raises(AlgebraError, match="must be a term"):
        substitute(_pred("P", _var("x")), "x", _pred("Q"))


def test_substitute_connectives_and_equality() -> None:
    x = _var("x")
    t = _const("c")
    formula = mk_implies(
        "n:imp",
        mk_not("n:not", _pred("P", x)),
        mk_or("n:or", _pred("Q", x), mk_equality("n:eq", x, _const("a"))),
    )
    result = _assert_fv_property(formula, "x", t)
    assert free_variables(result) == frozenset()
    # All occurrences replaced.
    for node in walk_bounded(result):
        if node.kind is NodeKind.VARIABLE:
            assert node.symbol != "x"


def test_substitute_extension_children() -> None:
    inner = _pred("P", _var("x"))
    node = mk_extension(
        "n:box",
        family="modal",
        profile="s5",
        features=("modal.box",),
        payload_schema="modal.box/v1",
        payload={"kind": "box", "schema_version": "1"},
        children=(inner,),
    )
    result = _assert_fv_property(node, "x", _const("alice"))
    assert result.extension is not None
    assert result.extension.children[0].arguments[0].symbol == "alice"


# ---------------------------------------------------------------------------
# Property: random-ish combinatorial capture suite
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "binder_names,free_name,term_frees",
    [
        (["y"], "x", ("y",)),
        (["y", "z"], "x", ("y",)),
        (["y"], "x", ("y", "z")),
        (["a"], "x", ("a",)),
    ],
)
def test_property_substitution_never_captures(
    binder_names: list[str],
    free_name: str,
    term_frees: tuple[str, ...],
) -> None:
    """For adversarial binder/term combinations, FV law holds and no capture."""

    # Body mentions free_name and each binder.
    args = [_var(free_name)] + [_var(b) for b in binder_names]
    body = _pred("P", *args)
    expr: LogicNode = body
    for name in reversed(binder_names):
        expr = _forall([name], expr, node_id=f"n:all:{name}")

    # Replacement term mentioning term_frees (application of f if multi).
    if len(term_frees) == 1:
        term: LogicNode = _var(term_frees[0])
    else:
        term = mk_application(
            "n:f",
            "f",
            tuple(_var(n) for n in term_frees),
            sort=_person(),
        )

    result = _assert_fv_property(expr, free_name, term)

    # Capture check: every free var of term is still free in result
    # whenever free_name was free in expr (it is).
    for name in term_frees:
        assert name in free_variables(result), (
            f"free variable {name!r} of replacement was captured: "
            f"FV(result)={set(free_variables(result))}"
        )

    # No binder in the result should equal a free var of the term that was
    # free in the original expression context — more precisely, binders that
    # scope over the substituted occurrence must not be names from FV(term).
    # We check the strong form: FV law already proved; additionally the
    # captured closed form is not alpha-eq to result when term has free vars
    # overlapping binders.
    if set(term_frees) & set(binder_names):
        # Build naive captured form for contrast (same binders, free_name -> term)
        # We only assert result is NOT alpha-eq to substituting without rename
        # into body while keeping binders: ∀binders. P(term_as_if_vars, binders)
        # which would bind term frees.
        naive_args = []
        # Rough naive: replace free_name leaf with first term free var node
        naive_body_args = [_var(term_frees[0])] + [_var(b) for b in binder_names]
        naive: LogicNode = _pred("P", *naive_body_args)
        for name in reversed(binder_names):
            naive = _forall([name], naive, node_id=f"n:naive:{name}")
        # If term was a single var equal to a binder, naive captures.
        if len(term_frees) == 1 and term_frees[0] in binder_names:
            assert not alpha_equivalent(result, naive)


def test_property_alpha_equivalent_share_semantic_identity() -> None:
    """Many alpha-renaming variants share one semantic identity."""

    names = ["x", "y", "z", "u", "v"]
    digests: set[str] = set()
    nodes: list[LogicNode] = []
    for a, b in itertools.permutations(names, 2):
        node = _forall(
            [a],
            _exists([b], _pred("R", _var(a), _var(b), _var("w"))),
            node_id=f"n:{a}:{b}",
        )
        nodes.append(node)
        digests.add(semantic_identity(node))
    assert len(digests) == 1
    for left, right in itertools.combinations(nodes[:5], 2):
        assert alpha_equivalent(left, right)


def test_property_semantic_identity_distinguishes_structure() -> None:
    a = _forall(["x"], _pred("P", _var("x")))
    b = _exists(["x"], _pred("P", _var("x")))
    c = _forall(["x"], _pred("Q", _var("x")))
    d = _forall(["x"], _pred("P", _var("x"), _var("y")))
    identities = {
        semantic_identity(a),
        semantic_identity(b),
        semantic_identity(c),
        semantic_identity(d),
    }
    assert len(identities) == 4


# ---------------------------------------------------------------------------
# Bounded traversal
# ---------------------------------------------------------------------------


def test_walk_and_size_depth() -> None:
    formula = mk_and(
        "n:root",
        _pred("P", _var("x")),
        _forall(["y"], _pred("Q", _var("y"), _var("x"))),
        mk_true(),
        mk_false(),
    )
    alg = DEFAULT_ALGEBRA
    nodes = list(alg.walk(formula))
    assert alg.size(formula) == len(nodes)
    assert alg.depth(formula) >= 2
    assert formula in nodes


def test_traversal_respects_node_limit() -> None:
    # Build a modest tree and force a tiny node budget.
    formula = mk_and(
        "n:root",
        _pred("P", _var("x")),
        _pred("Q", _var("y")),
        _pred("R", _var("z")),
    )
    tight = AlgebraLimits(max_nodes=2, max_depth=64)
    alg = LogicExpressionAlgebra(limits=tight)
    with pytest.raises(AlgebraError, match="node count"):
        alg.size(formula)
    with pytest.raises(AlgebraError, match="node count"):
        list(alg.walk(formula))
    with pytest.raises(AlgebraError, match="node count"):
        alg.free_variables(formula)


def test_traversal_respects_depth_limit() -> None:
    # Deep nest of NOT: depth grows linearly.
    node: LogicNode = _pred("P")
    for index in range(10):
        node = mk_not(f"n:not:{index}", node)
    # Depth is 11 (10 nots + pred). Limit 3 must fail.
    tight = AlgebraLimits(max_nodes=10_000, max_depth=3)
    alg = LogicExpressionAlgebra(limits=tight)
    with pytest.raises(AlgebraError, match="depth"):
        alg.depth(node)
    with pytest.raises(AlgebraError, match="depth"):
        list(alg.walk(node))


def test_limits_reject_unbounded_and_over_ceiling() -> None:
    with pytest.raises(AlgebraError, match="positive"):
        AlgebraLimits(max_nodes=0)
    with pytest.raises(AlgebraError, match="ceiling"):
        AlgebraLimits(max_nodes=10**12)


def test_substitute_and_alpha_under_tight_but_sufficient_limits() -> None:
    limits = AlgebraLimits(max_nodes=10_000, max_depth=64)
    alg = LogicExpressionAlgebra(limits=limits)
    expr = _forall(["y"], _pred("P", _var("x"), _var("y")))
    result = alg.substitute(expr, "x", _var("y"))
    assert "y" in alg.free_variables(result)
    assert alg.alpha_equivalent(
        expr,
        alg.alpha_rename_binder(expr, "y", "z"),
    )


def test_walk_bounded_module_helper() -> None:
    node = _pred("P", _var("x"))
    walked = list(walk_bounded(node))
    assert len(walked) == 2
    with pytest.raises(AlgebraError):
        list(walk_bounded(node, limits=AlgebraLimits(max_nodes=1, max_depth=8)))


# ---------------------------------------------------------------------------
# Nullary / constants / true-false edge cases
# ---------------------------------------------------------------------------


def test_true_false_and_constants_stable_under_subst() -> None:
    assert free_variables(mk_true()) == frozenset()
    assert free_variables(mk_false()) == frozenset()
    assert alpha_equivalent(mk_true("a"), mk_true("b"))
    assert semantic_identity(mk_true("a")) == semantic_identity(mk_true("b"))
    result = substitute(mk_true(), "x", _const("c"))
    assert result.kind is NodeKind.TRUE
    result_c = substitute(_const("alice"), "x", _const("bob"))
    assert result_c.symbol == "alice"


def test_application_free_vars_and_subst() -> None:
    term = mk_application(
        "n:f",
        "father",
        (_var("x"),),
        sort=_person(),
    )
    assert free_variables(term) == frozenset({"x"})
    result = substitute(term, "x", _const("alice"))
    assert free_variables(result) == frozenset()
    assert result.arguments[0].symbol == "alice"
