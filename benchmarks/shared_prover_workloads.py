"""Pure bounded propositional fixtures for native shared-prover benchmarks.

Builders perform actual modal-parser/pretty-printer replay, preserving complete
native AST records. They never execute a solver, acquire resources, or claim a
checked proof. Fixture preparation is separate from solver execution timing.
The outer task adapter admits at most 1 MiB of serialized target data; the
checked datasets route also limits text, AST size and depth independently.
"""
from __future__ import annotations

import itertools
import json
import random

WORKLOAD_SCHEMA = "shared-prover-workloads@1"
MAX_TARGET_BYTES = 1024 * 1024
MAX_AST_NODES = 4096
MAX_AST_DEPTH = 64
MAX_TEXT_BYTES = 65536
TSEITIN_SEED_BASE = 1729


def _integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{label} must be an exact integer in [{low}, {high}]")


def _balanced(operator, terms):
    if len(terms) == 1:
        return terms[0]
    middle = len(terms) // 2
    return f"({_balanced(operator, terms[:middle])} {operator} {_balanced(operator, terms[middle:])})"


def _shape(node):
    children = [_shape(child) for child in node["arguments"]]
    return 1 + sum(size for size, _ in children), 1 + max((depth for _, depth in children), default=0)


def _target(request_id, source_construct, text, solver_names):
    from ipfs_datasets_py.logic.parsers import modal

    if type(request_id) is not str or not request_id or len(request_id.encode()) > 1024:
        raise ValueError("bounded nonempty request_id required")
    if (type(solver_names) not in (tuple, list) or not 1 <= len(solver_names) <= 2
            or any(type(name) is not str or name not in ("z3", "cvc5") for name in solver_names)
            or len(set(solver_names)) != len(solver_names)):
        raise ValueError("one or two distinct native SMT solver names required")
    if len(text.encode()) > MAX_TEXT_BYTES:
        raise ValueError("fixture text exceeds checked routing bound")
    parsed = modal.parse_modal(text, modal.profile_k())
    if not parsed.ok or parsed.diagnostics:
        raise ValueError("fixture failed native propositional parsing")
    replay = modal.parse_modal(parsed.printed, modal.profile_k())
    if not replay.ok or replay.diagnostics or replay.printed != parsed.printed:
        raise ValueError("fixture failed exact native parser replay")
    native_ast = replay.root.to_dict()
    size, depth = _shape(native_ast)
    if size > MAX_AST_NODES or depth > MAX_AST_DEPTH:
        raise ValueError("fixture AST exceeds checked routing bounds")
    result = {"request_id": request_id, "source_construct": source_construct,
        "logic_family": "propositional", "ast_format": "shared_logic",
        "printed": parsed.printed, "native_ast": native_ast, "solver_names": list(solver_names)}
    if len(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()) > MAX_TARGET_BYTES:
        raise ValueError("serialized fixture exceeds the 1 MiB task bound")
    return result


def pigeonhole_target(request_id, pigeons=10, holes=9, solver_names=("z3", "cvc5")):
    """Each pigeon occupies a hole; no hole can contain two pigeons.

    ``p{i}h{j}`` means pigeon i occupies hole j. One positive disjunction per
    pigeon forces occupancy; one negative pair per hole/pigeon-pair prevents
    sharing. This is unsatisfiable exactly when pigeons > holes. For the SAT
    control pigeons <= holes, the diagonal assignment is an explicit witness.
    There is no added at-most-one-hole constraint or symmetry-breaking clause.
    """
    _integer(pigeons, 1, 11, "pigeons")
    _integer(holes, 1, 10, "holes")
    clauses = [_balanced("or", [f"p{i}h{j}" for j in range(holes)]) for i in range(pigeons)]
    clauses.extend(f"(not p{i}h{k} or not p{j}h{k})"
                   for k in range(holes) for i in range(pigeons) for j in range(i + 1, pigeons))
    return _target(request_id, f"benchmark:pigeonhole-cnf@1:pigeons={pigeons}:holes={holes}",
                   _balanced("and", clauses), solver_names)


def _tseitin_graph(vertices):
    """A connected simple cubic graph: cycle plus a disjoint perfect matching."""
    _integer(vertices, 4, 64, "vertices")
    if vertices % 2:
        raise ValueError("Tseitin vertices must be even")
    cycle = {tuple(sorted((i, (i + 1) % vertices))) for i in range(vertices)}
    rng = random.Random(TSEITIN_SEED_BASE + vertices)
    for _ in range(1000):
        order = list(range(vertices))
        rng.shuffle(order)
        matching = {tuple(sorted(order[i:i + 2])) for i in range(0, vertices, 2)}
        if not cycle & matching:
            edges = tuple(sorted(cycle | matching))
            return edges, (1,) + (0,) * (vertices - 1)
    raise ValueError("bounded deterministic matching search failed")


def tseitin_target(request_id, vertices=64, solver_names=("z3", "cvc5")):
    """Odd-charge Tseitin contradiction, expanded into exact three-literal CNF.

    Each shared edge has one Boolean variable. Its endpoint constraints XOR
    their incident edge values to the vertex charge. Exactly vertex zero has
    charge one. Summing all constraints modulo two counts each edge twice, so
    the left side is zero and the right side one: the conjunction is UNSAT.
    Four clauses per cubic vertex forbid precisely the wrong-parity assignments.
    The fixed generator seed is 1729 + vertices; no runtime randomness or
    model/proof cache affects construction or the expected truth domain.
    """
    edges, charges = _tseitin_graph(vertices)
    incident = [[] for _ in range(vertices)]
    for edge_index, (left, right) in enumerate(edges):
        incident[left].append(f"e{edge_index}")
        incident[right].append(f"e{edge_index}")
    clauses = []
    for variables, charge in zip(incident, charges):
        for values in itertools.product((0, 1), repeat=3):
            if sum(values) % 2 != charge:
                clauses.append(_balanced("or", [f"not {name}" if value else name
                                                 for name, value in zip(variables, values)]))
    return _target(request_id, f"benchmark:tseitin-cnf@1:vertices={vertices}:seed={TSEITIN_SEED_BASE + vertices}",
                   _balanced("and", clauses), solver_names)


__all__ = ["WORKLOAD_SCHEMA", "pigeonhole_target", "tseitin_target"]
