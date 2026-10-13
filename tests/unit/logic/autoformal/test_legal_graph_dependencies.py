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
