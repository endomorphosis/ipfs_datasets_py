"""Semantic fixture inventories and small native SAT/UNSAT controls."""
from collections import Counter
import itertools
import json
import math
import shutil

import pytest

from benchmarks import shared_prover_workloads as workloads
from ipfs_datasets_py.logic.hammers import semantic_routing as routing
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as resources
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources


def clauses(target):
    root = target["native_ast"]
    return root["arguments"] if root["kind"] == "and" else [root]


def literals(clause):
    nodes = clause["arguments"] if clause["kind"] == "or" else [clause]
    result = []
    for node in nodes:
        positive = node["kind"] != "not"
        predicate = node if positive else node["arguments"][0]
        assert predicate["kind"] == "predicate" and not predicate["arguments"]
        result.append((predicate["symbol"], positive))
    return result


def evaluate(target, assignment):
    return all(any(assignment[name] == positive for name, positive in literals(clause))
               for clause in clauses(target))


def test_pigeonhole_has_every_and_only_declared_occupancy_and_exclusion_constraint():
    pigeons, holes = 4, 3
    target = workloads.pigeonhole_target("inventory", pigeons, holes)
    observed = [literals(clause) for clause in clauses(target)]
    assert len(observed) == pigeons + holes * math.comb(pigeons, 2)
    positive, negative = observed[:pigeons], observed[pigeons:]
    for pigeon, clause in enumerate(positive):
        assert set(clause) == {(f"p{pigeon}h{hole}", True) for hole in range(holes)}
    pairs = set()
    for clause in negative:
        assert len(clause) == 2 and all(not sign for _, sign in clause)
        decoded = [tuple(map(int, name[1:].split("h"))) for name, _ in clause]
        (left, hole), (right, same_hole) = decoded
        assert 0 <= left < right < pigeons and 0 <= hole == same_hole < holes
        pairs.add((left, right, hole))
    assert len(pairs) == len(negative)


def test_pigeonhole_small_truth_table_and_diagonal_sat_witness():
    unsat = workloads.pigeonhole_target("finite-unsat", 3, 2)
    names = [f"p{i}h{j}" for i in range(3) for j in range(2)]
    assert not any(evaluate(unsat, dict(zip(names, values))) for values in itertools.product((False, True), repeat=6))
    sat = workloads.pigeonhole_target("finite-sat", 3, 3)
    assert evaluate(sat, {f"p{i}h{j}": i == j for i in range(3) for j in range(3)})


@pytest.mark.parametrize("vertices", [4, 48, 64])
def test_tseitin_constraints_retain_odd_charge_and_shared_edge_incidence(vertices):
    target = workloads.tseitin_target("parity-inventory", vertices)
    edges, charges = workloads._tseitin_graph(vertices)
    assert len(edges) == len(set(edges)) == 3 * vertices // 2
    assert sum(charges) == 1 and charges[0] == 1
    assert all(0 <= left < right < vertices for left, right in edges)
    degrees = Counter(vertex for edge in edges for vertex in edge)
    assert degrees == {vertex: 3 for vertex in range(vertices)}
    assert all(tuple(sorted((vertex, (vertex + 1) % vertices))) in edges for vertex in range(vertices))
    observed = [literals(clause) for clause in clauses(target)]
    assert len(observed) == 4 * vertices
    occurrences = Counter(name for clause in observed for name, _ in clause)
    assert occurrences == {f"e{edge}": 8 for edge in range(len(edges))}
    for vertex, charge in enumerate(charges):
        names = [f"e{index}" for index, edge in enumerate(edges) if vertex in edge]
        local = observed[vertex * 4:(vertex + 1) * 4]
        assert all(len(clause) == 3 and {name for name, _ in clause} == set(names) for clause in local)
        for values in itertools.product((False, True), repeat=3):
            assignment = dict(zip(names, values))
            admitted = all(any(assignment[name] == sign for name, sign in clause) for clause in local)
            assert admitted is (sum(values) % 2 == charge)


def test_small_tseitin_formula_is_unsat_by_complete_boolean_enumeration():
    target = workloads.tseitin_target("parity-truth-table", 4)
    names = [f"e{index}" for index in range(6)]
    assert not any(evaluate(target, dict(zip(names, values))) for values in itertools.product((False, True), repeat=6))


@pytest.mark.parametrize("builder", [workloads.pigeonhole_target, workloads.tseitin_target])
def test_default_fixture_is_reproducible_exact_native_replay_and_bounded(builder):
    target = builder("replay-fixture")
    assert target == builder("replay-fixture")
    parsed = routing.modal.parse_modal(target["printed"], routing.modal.profile_k())
    assert parsed.ok and not parsed.diagnostics and parsed.root.to_dict() == target["native_ast"]
    assert len(target["printed"].encode()) <= workloads.MAX_TEXT_BYTES
    assert len(json.dumps(target, sort_keys=True, separators=(",", ":")).encode()) <= workloads.MAX_TARGET_BYTES
    nodes, depth = workloads._shape(target["native_ast"])
    assert nodes <= routing.MAX_AST_NODES and depth <= routing.MAX_DEPTH
    attempts, receipt = routing.prepare_family_portfolio(**target)
    assert len(attempts) == 2
    assert all(row["operation"] == "check_satisfiability" for row in receipt["routes"])
    assert receipt["qualified"] is False and receipt["source_semantics_verified"] is False


@pytest.mark.parametrize("builder,arguments", [
    (workloads.pigeonhole_target, {"pigeons": True}),
    (workloads.pigeonhole_target, {"pigeons": 12}),
    (workloads.pigeonhole_target, {"holes": 0}),
    (workloads.pigeonhole_target, {"holes": 11}),
    (workloads.pigeonhole_target, {"holes": 3.0}),
    (workloads.tseitin_target, {"vertices": 3}),
    (workloads.tseitin_target, {"vertices": 63}),
    (workloads.tseitin_target, {"vertices": 66}),
    (workloads.tseitin_target, {"vertices": True}),
])
def test_unbounded_or_ambiguous_dimensions_fail_before_parsing(builder, arguments, monkeypatch):
    monkeypatch.setattr(routing.modal, "parse_modal", lambda *a, **k: pytest.fail("invalid dimensions parsed"))
    with pytest.raises(ValueError):
        builder("invalid-fixture", **arguments)


@pytest.mark.parametrize("request_id,solvers", [("", ("z3",)), ("x" * 1025, ("z3",)),
    (True, ("z3",)), ("bad", ()), ("bad", ("z3", "z3")), ("bad", ("vampire",)),
    ("bad", "z3"), ("bad", (True,))])
def test_request_and_solver_names_are_closed(request_id, solvers):
    with pytest.raises(ValueError):
        workloads.pigeonhole_target(request_id, 2, 1, solver_names=solvers)


@pytest.mark.skipif(not shutil.which("z3") or not shutil.which("cvc5"), reason="native Z3/CVC5 unavailable")
@pytest.mark.parametrize("builder,arguments,expected", [
    (workloads.pigeonhole_target, {"pigeons": 3, "holes": 3}, "sat"),
    (workloads.tseitin_target, {"vertices": 48}, "unsat"),
])
def test_native_small_control_matches_exact_fixture_truth_domain(tmp_path, builder, arguments, expected):
    target = builder("native-control", **arguments)
    _, receipt = routing.prepare_family_portfolio(**target)
    owner = resources.GlobalResourceScheduler(resources.ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path / "native-control.json", proof_resource_sampler=lambda: ProofHostResources(8, 8192, 8192),
        lane_reservations={}, auto_renew_leases=False, proof_backoff_seconds=.02, poll_interval_seconds=.005))
    policy = routing.policy.PortfolioPolicy(
        hammer_policy=routing.models.HammerPolicy(allowed_solvers=["z3", "cvc5"], timeout_seconds=4),
        solver_budgets={solver: routing.policy.SolverBudget(timeout_seconds=4, cpu_seconds=2, memory_mb=256)
                        for solver in ("z3", "cvc5")}, max_parallel_processes=1, cancel_on_first_conclusive=False)
    with owner.acquire("orchestration", cpu_slots=1, memory_mb=512, child_process_slots=1, timeout=0) as parent:
        result = routing.run_family_portfolio(expected_routing=receipt, run_policy=policy,
            parent_lease=parent, resource_wait_timeout_seconds=2, **target)
        assert not result.denied and not result.cancelled_attempt_ids
        assert len(result.attempts) == 2
        assert all(row.verdict.value == expected and row.solver_version for row in result.attempts)
        assert owner.snapshot()["active_root_lease_count"] == owner.snapshot()["active_lease_count"] == 1
    assert owner.snapshot()["active_lease_count"] == owner.snapshot()["waiting_request_count"] == 0
