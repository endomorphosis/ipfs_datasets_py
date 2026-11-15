"""Exact declared populations, reverse direction, cycles and missing custody."""
from copy import deepcopy

import pytest

from ipfs_datasets_py.logic.autoformal import legal_graph_dependencies as subject


def artifact(key, **pins):
    declared = {kind: [] for kind in subject.PIN_KINDS}
    declared.update({kind: [{"key": f"{kind}:{key}", "sha256": value}] for kind, value in pins.items()})
    return {"artifact_id": key, "artifact_sha256": "a" * 64, "dependency_pins": declared}


def edge(dependent, dependency):
    return {"dependent_id": dependent, "dependency_id": dependency}


def manifest(rows, edges=()):
    return subject.build_dependency_manifest(rows, list(edges), expected_artifact_ids=[r["artifact_id"] for r in rows])


def observations(value):
    pins = {kind: {} for kind in subject.PIN_KINDS}
    for row in value["artifacts"]:
        for kind in subject.PIN_KINDS:
            pins[kind].update({p["key"]: p["sha256"] for p in row["dependency_pins"][kind]})
    return {"expected_manifest_sha256": value["manifest_sha256"],
            "observed_artifact_sha256s": {r["artifact_id"]: r["artifact_sha256"] for r in value["artifacts"]},
            "observed_pins": pins}


def test_changed_definition_invalidates_only_reverse_reachable_descendants():
    value = manifest([artifact("definition", definition="b" * 64), artifact("rule"),
                      artifact("doctrine"), artifact("independent")],
                     [edge("rule", "definition"), edge("doctrine", "rule")])
    current = observations(value)
    current["observed_pins"]["definition"]["definition:definition"] = "c" * 64
    result = subject.invalidate_dependencies(value, **current)
    assert result["stale_artifact_ids"] == ["definition", "rule", "doctrine"]
    assert result["reusable_under_declared_dependencies"] == ["independent"]
    assert result["seed_artifact_ids"] == ["definition"]
    assert result["propagation_witnesses"] == [edge("rule", "definition"), edge("doctrine", "rule")]
    assert result["global_consistency_verified"] is False


@pytest.mark.parametrize("kind", subject.PIN_KINDS)
def test_each_declared_pin_kind_and_revision_is_compared_exactly(kind):
    value = manifest([artifact("source", **{kind: "b" * 64}), artifact("child")], [edge("child", "source")])
    current = observations(value)
    current["observed_pins"][kind][f"{kind}:source"] = "c" * 64
    result = subject.invalidate_dependencies(value, **current)
    assert result["stale_artifact_ids"] == ["source", "child"]
    assert result["seed_reasons"]["source"] == [{"code": "dependency_pin_changed", "kind": kind, "key": f"{kind}:source"}]


def test_cycle_and_self_loop_are_inventory_items_and_do_not_truncate_propagation():
    value = manifest([artifact("a"), artifact("b"), artifact("c"), artifact("self"), artifact("safe")],
                     [edge("b", "a"), edge("a", "b"), edge("c", "b"), edge("self", "self")])
    assert value["cycles"] == [["a", "b"], ["self"]]
    current = observations(value)
    current["observed_artifact_sha256s"]["a"] = "d" * 64
    result = subject.invalidate_dependencies(value, **current)
    assert result["stale_artifact_ids"] == ["a", "b", "c"]
    assert result["reusable_under_declared_dependencies"] == ["self", "safe"]


def test_missing_target_and_pin_propagate_without_claiming_closure():
    value = manifest([artifact("rule", context=None), artifact("doctrine")],
                     [edge("rule", "missing-source"), edge("doctrine", "rule")])
    result = subject.invalidate_dependencies(value, **observations(value))
    assert result["stale_artifact_ids"] == ["rule", "doctrine"]
    assert result["missing_dependencies"] == [edge("rule", "missing-source")]
    assert result["legal_dependency_inventory_exhaustive"] is False
    assert result["population_complete"] is True
    assert result["coverage_scope"] == "exact_declared_artifacts_pins_and_edges_only"


def test_absent_observed_pin_and_explicit_missing_artifact_prevent_reuse():
    value = manifest([artifact("rule", source="b" * 64), artifact("other")])
    current = observations(value)
    current["observed_pins"]["source"].clear()
    current["observed_artifact_sha256s"]["other"] = None
    result = subject.invalidate_dependencies(value, **current)
    assert result["stale_artifact_ids"] == ["rule", "other"]
    assert result["reusable_under_declared_dependencies"] == []


def test_observation_population_and_extra_keys_cannot_hide_changed_artifacts():
    value = manifest([artifact("rule"), artifact("other")])
    current = observations(value)
    current["observed_artifact_sha256s"].pop("other")
    with pytest.raises(subject.GraphDependencyError, match="every artifact"):
        subject.invalidate_dependencies(value, **current)
    current = observations(value)
    current["observed_pins"]["source"]["typo"] = "b" * 64
    with pytest.raises(subject.GraphDependencyError, match="observed pin keys"):
        subject.invalidate_dependencies(value, **current)


def test_manifest_omission_reordering_duplicate_or_foreign_dependent_fails():
    rows = [artifact("a"), artifact("b")]
    with pytest.raises(subject.GraphDependencyError, match="population differs"):
        subject.build_dependency_manifest(list(reversed(rows)), [], expected_artifact_ids=["a", "b"])
    with pytest.raises(subject.GraphDependencyError):
        subject.build_dependency_manifest(rows[:1], [], expected_artifact_ids=["a", "b"])
    with pytest.raises(subject.GraphDependencyError, match="duplicate expected"):
        subject.build_dependency_manifest([rows[0], rows[0]], [], expected_artifact_ids=["a", "a"])
    with pytest.raises(subject.GraphDependencyError, match="dependent is omitted"):
        manifest(rows, [edge("omitted", "a")])


def test_resealed_manifest_and_invalidation_tampering_are_rejected():
    value = manifest([artifact("a"), artifact("b")], [edge("b", "a")])
    bad = deepcopy(value)
    bad["reverse_index"]["a"] = []
    bad["manifest_sha256"] = subject._digest({k: v for k, v in bad.items() if k != "manifest_sha256"})
    with pytest.raises(subject.GraphDependencyError, match="independently expected identity"):
        subject.validate_dependency_manifest(bad, expected_manifest_sha256=value["manifest_sha256"])
    current = observations(value)
    current["observed_artifact_sha256s"]["a"] = "c" * 64
    result = subject.invalidate_dependencies(value, **current)
    result["stale_artifact_ids"] = ["a"]
    result["invalidation_sha256"] = subject._digest({k: v for k, v in result.items() if k != "invalidation_sha256"})
    with pytest.raises(subject.GraphDependencyError, match="exact regeneration"):
        subject.validate_invalidation(result, value, **current)


def test_large_linear_frontier_uses_no_recursive_or_hop_cutoff():
    rows = [artifact(str(index)) for index in range(1200)]
    value = manifest(rows, [edge(str(index), str(index - 1)) for index in range(1, len(rows))])
    current = observations(value)
    current["observed_artifact_sha256s"]["0"] = None
    result = subject.invalidate_dependencies(value, **current)
    assert len(result["stale_artifact_ids"]) == len(rows)
    assert not result["reusable_under_declared_dependencies"]


def test_dropped_and_resealed_artifacts_cannot_retarget_manifest_consumption():
    original = manifest([artifact("source"), artifact("rule"), artifact("doctrine")],
                        [edge("rule", "source"), edge("doctrine", "rule")])
    dropped = manifest([artifact("source"), artifact("rule")], [edge("rule", "source")])
    current = observations(dropped)
    current["expected_manifest_sha256"] = original["manifest_sha256"]
    with pytest.raises(subject.GraphDependencyError, match="independently expected identity"):
        subject.invalidate_dependencies(dropped, **current)


def test_bad_bounds_pin_shape_and_boolean_hash_refuse_before_partial_result(monkeypatch):
    value = artifact("a")
    value["dependency_pins"].pop("model")
    with pytest.raises(subject.GraphDependencyError, match="seven"):
        manifest([value])
    value = artifact("a", model=True)
    with pytest.raises(subject.GraphDependencyError, match="SHA256"):
        manifest([value])
    monkeypatch.setattr(subject, "MAX_ARTIFACTS", 1)
    with pytest.raises(subject.GraphDependencyError, match="bounded artifact"):
        manifest([artifact("a"), artifact("b")])


def test_returned_observations_are_detached_and_unchanged_artifacts_are_only_conditionally_reusable():
    value = manifest([artifact("a", policy="b" * 64)])
    current = observations(value)
    result = subject.invalidate_dependencies(value, **current)
    current["observed_pins"]["policy"]["policy:a"] = "c" * 64
    assert result["observed_pins"]["policy"]["policy:a"] == "b" * 64
    assert result["reusable_under_declared_dependencies"] == ["a"]
    assert all(result[key] is False for key in subject._FALSE)


def component_dependency_case_v2(*, declared=None):
    """Reuse the graph owner's complete fictional component/import fixture."""
    from tests.unit.logic.autoformal import test_corpus_graph as graph_fixture
    case = graph_fixture.component_case_v2()
    arguments = dict(expected_composition_cid=case["graph"]["record_cid"], expected_components=case["pins"])
    value = subject.build_component_dependency_manifest_v2(case["graph"],
        declared_dependencies=[] if declared is None else declared, **arguments)
    return case, value, dict(expected_manifest_sha256=value["manifest_sha256"], **arguments)


def test_component_dependency_v2_keeps_every_competing_import_and_existing_reverse_direction():
    case, value, arguments = component_dependency_case_v2()
    assert [row["artifact_id"] for row in value["dependency_manifest"]["artifacts"]] == [
        row["component_id"] for row in case["pins"]]
    assert [row["import_cid"] for row in value["import_dependencies"]] == [row["record_cid"] for row in case["imports"]]
    assert value["dependency_manifest"]["edges"] == [edge("component-0", "component-1"),
        edge("component-0", "component-2"), edge("component-1", "component-2")]
    current = observations(value["dependency_manifest"])
    current.pop("expected_manifest_sha256")
    result = subject.invalidate_component_dependencies_v2(value, case["graph"], **arguments, **current)
    assert result["invalidation"]["stale_artifact_ids"] == []
    assert result["disposition"] == "unchanged_declared_dependencies_only"
    assert result["review_state_evaluation_performed"] is False
    assert all(result[key] is False for key in subject._FALSE)
    assert subject.validate_component_invalidation_v2(result, value, case["graph"], **arguments, **current) == result


@pytest.mark.parametrize("changed", ["snapshot", "revoked_review", "unavailable_component"])
def test_component_dependency_v2_changed_or_revoked_inputs_invalidate_all_users_without_selecting_a_definition(changed):
    case, value, arguments = component_dependency_case_v2()
    current = observations(value["dependency_manifest"])
    current.pop("expected_manifest_sha256")
    if changed == "snapshot": current["observed_pins"]["source"]["component-2:snapshot"] = "b" * 64
    elif changed == "revoked_review": current["observed_pins"]["context"]["component-2:review-inputs"] = "c" * 64
    else: current["observed_artifact_sha256s"]["component-2"] = None
    result = subject.invalidate_component_dependencies_v2(value, case["graph"], **arguments, **current)
    assert result["invalidation"]["seed_artifact_ids"] == ["component-2"]
    assert result["invalidation"]["stale_artifact_ids"] == ["component-0", "component-1", "component-2"]
    assert result["import_dependencies"] == value["import_dependencies"]
    assert case["graph"]["components"][1]["review_inputs"]["state"] == "revoked"


def test_component_dependency_v2_missing_declared_dependency_and_cycle_remain_explicit_without_hop_cutoff():
    declared = [edge("component-2", "missing-current-context"), edge("component-2", "component-0")]
    case, value, arguments = component_dependency_case_v2(declared=declared)
    assert value["declared_dependencies"] == declared
    current = observations(value["dependency_manifest"])
    current.pop("expected_manifest_sha256")
    result = subject.invalidate_component_dependencies_v2(value, case["graph"], **arguments, **current)
    assert result["invalidation"]["missing_dependencies"] == [declared[0]]
    assert result["invalidation"]["cycles"] == [["component-0", "component-1", "component-2"]]
    assert result["invalidation"]["stale_artifact_ids"] == ["component-0", "component-1", "component-2"]
    assert result["disposition"] == "declared_dependencies_missing"


@pytest.mark.parametrize("damage", ["drop_import", "drop_competing", "review_pin", "reverse_index", "authority"])
def test_component_dependency_v2_resealed_foreign_or_incomplete_manifest_cannot_replace_independent_pin(damage):
    case, value, arguments = component_dependency_case_v2()
    bad = deepcopy(value)
    if damage == "drop_import": bad["import_dependencies"].pop()
    elif damage == "drop_competing": bad["dependency_manifest"]["edges"].pop(1)
    elif damage == "review_pin": bad["component_pins"][0]["review_sha256"] = "b" * 64
    elif damage == "reverse_index": bad["dependency_manifest"]["reverse_index"]["component-2"] = []
    else: bad["admitted"] = True
    bad["manifest_sha256"] = subject._digest({key: item for key, item in bad.items() if key != "manifest_sha256"})
    with pytest.raises(subject.GraphDependencyError, match="independent identity"):
        subject.validate_component_dependency_manifest_v2(bad, case["graph"], **arguments)
    changed_arguments = dict(arguments, expected_manifest_sha256=bad["manifest_sha256"])
    with pytest.raises(subject.GraphDependencyError, match="exact regeneration"):
        subject.validate_component_dependency_manifest_v2(bad, case["graph"], **changed_arguments)


@pytest.mark.parametrize("damage", ["foreign_observation", "omit_observation", "foreign_pin", "unbound_pin"])
def test_component_dependency_v2_observation_contract_remains_complete_and_closed(damage):
    case, value, arguments = component_dependency_case_v2()
    current = observations(value["dependency_manifest"])
    current.pop("expected_manifest_sha256")
    if damage == "foreign_observation": current["observed_artifact_sha256s"]["foreign"] = "a" * 64
    elif damage == "omit_observation": current["observed_artifact_sha256s"].pop("component-2")
    elif damage == "foreign_pin": current["observed_pins"]["definition"]["foreign"] = "b" * 64
    else: current["observed_pins"]["context"].pop("component-2:review-inputs")
    if damage == "unbound_pin":
        result = subject.invalidate_component_dependencies_v2(value, case["graph"], **arguments, **current)
        assert result["invalidation"]["stale_artifact_ids"] == ["component-0", "component-1", "component-2"]
    else:
        with pytest.raises(subject.GraphDependencyError):
            subject.invalidate_component_dependencies_v2(value, case["graph"], **arguments, **current)


@pytest.mark.parametrize("damage", ["duplicate", "foreign_dependent", "artifact_bound", "edge_bound"])
def test_component_dependency_v2_bounds_and_declared_population_never_filter(damage, monkeypatch):
    from tests.unit.logic.autoformal import test_corpus_graph as graph_fixture
    case = graph_fixture.component_case_v2()
    declared = [edge("component-0", "missing")]
    if damage == "duplicate": declared.append(dict(declared[0]))
    elif damage == "foreign_dependent": declared[0]["dependent_id"] = "omitted"
    elif damage == "artifact_bound": monkeypatch.setattr(subject, "MAX_ARTIFACTS", 2)
    else: monkeypatch.setattr(subject, "MAX_EDGES", 2)
    with pytest.raises(subject.GraphDependencyError):
        subject.build_component_dependency_manifest_v2(case["graph"], declared_dependencies=declared,
            expected_composition_cid=case["graph"]["record_cid"], expected_components=case["pins"])
