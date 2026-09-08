"""PCCE-060 frozen benchmark specification and leakage-boundary tests."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from ipfs_datasets_py.proof_context.benchmarks import specification as spec

DATASETS_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = DATASETS_ROOT / "benchmarks/proof_context/corpus_manifest.json"


def _manifest() -> dict[str, object]:
    value = spec.strict_json_loads(MANIFEST_PATH.read_bytes())
    assert isinstance(value, dict)
    return value


def _fixture_cid(label: str) -> str:
    return spec.structured_cid({"fixture": label})


def _task_control() -> dict[str, object]:
    return {
        "schema": spec.TASK_CONTROL_SCHEMA,
        "task_id": "typed-historical-001",
        "corpus_manifest_cid": _fixture_cid("manifest"),
        "repository_class": "typed_structured",
        "source_pin_id": "python-attrs-attrs-25.3.0",
        "task_kind": "historical_replay",
        "base_commit": "1" * 40,
        "base_tree": "2" * 40,
        "visible_projection_cid": _fixture_cid("visible"),
        "sealed_evaluator_root_cid": _fixture_cid("sealed"),
        "objective": "Repair the visible behavior without hidden evaluator access.",
        "owned_paths": ["src/attr/_make.py"],
        "routine_localized": True,
        "risk_class": "routine",
        "seed": 60060,
        "eligible_configurations": ["A", "B", "C", "D"],
    }


def _raw_result() -> dict[str, object]:
    metrics = {definition["name"]: 0 for definition in spec.metric_catalog()}
    return {
        "schema": spec.RAW_RESULT_SCHEMA,
        "run_key": "fixture/typed-historical-001/A/attempt-1",
        "corpus_manifest_cid": _fixture_cid("manifest"),
        "task_record_cid": _fixture_cid("task"),
        "visible_projection_cid": _fixture_cid("visible"),
        "configuration_id": "A",
        "configuration_cid": _fixture_cid("configuration-A"),
        "repository_state_cid": _fixture_cid("repository-state"),
        "environment_cid": _fixture_cid("environment"),
        "provider_id": "unavailable-fixture",
        "model_id": "unavailable-fixture",
        "model_revision": "unavailable-fixture",
        "seed": 60060,
        "attempt": 1,
        "provenance": "live",
        "terminal_status": "unavailable",
        "metrics": metrics,
        "missingness": {},
        "evidence_cids": [_fixture_cid("attempt")],
    }


def _thresholds(manifest: dict[str, object]) -> dict[str, object]:
    return {
        "schema": spec.THRESHOLD_SET_SCHEMA,
        "benchmark_id": spec.BENCHMARK_ID,
        "corpus_manifest_cid": spec.corpus_manifest_cid(manifest),
        "schema_catalog_cid": spec.catalog_cids()["schema_catalog_cid"],
        "frozen_at": manifest["frozen_at"],
        "freeze_state": "pre-execution-preregistered",
        "results_observed_before_freeze": False,
        **spec.threshold_policy(),
    }


def test_import_is_data_only_and_public_catalogs_are_stable() -> None:
    reloaded = importlib.reload(spec)
    assert reloaded.BENCHMARK_ID == "pcce-external-generalization-v0.1"
    assert not any(
        name.startswith(("run_benchmark", "execute_benchmark", "fetch_corpus"))
        for name in reloaded.__all__
    )
    assert reloaded.catalog_cids() == reloaded.catalog_cids()
    assert reloaded.schema_catalog()["identity_profile"] == ("software-contract-cid-profile-v1")


def test_strict_json_rejects_duplicate_float_and_nonfinite_values() -> None:
    with pytest.raises(spec.BenchmarkSpecificationError, match="duplicate"):
        spec.strict_json_loads('{"a":1,"a":2}')
    with pytest.raises(spec.BenchmarkSpecificationError, match="floating-point"):
        spec.strict_json_loads('{"a":1.5}')
    with pytest.raises(spec.BenchmarkSpecificationError, match="non-finite"):
        spec.strict_json_loads('{"a":NaN}')
    with pytest.raises(spec.BenchmarkSpecificationError):
        spec.structured_cid({"not_admitted": 1.25})


def test_manifest_binds_the_integrated_pcce056_no_go() -> None:
    manifest = _manifest()
    admitted = spec.validate_corpus_manifest(manifest)
    assert admitted == manifest
    gate = manifest["runtime_gate"]
    assert isinstance(gate, dict)
    assert gate["binding_state"] == "final-content-addressed"
    assert gate["qualification_sha256"] == (
        "378f733b31feee32c39552c775d8e774f0cee9381920c00f14649dcfdafb1ef7"
    )
    assert gate["qualification_cid"] == (
        "bafkreibxr5ztwmp65yzmhfksy525rz3u6dhosoazedaa6fdetxh5v6y664"
    )
    assert gate["live_execution_eligible"] is False
    assert gate["qualification_status"] == "no-go"

    draft = dict(manifest)
    draft["runtime_gate"] = dict(gate)
    draft["runtime_gate"]["binding_state"] = "draft-uncommitted"
    with pytest.raises(spec.BenchmarkSpecificationError, match="not final"):
        spec.validate_corpus_manifest(draft)


def test_manifest_binds_all_catalogs_and_leakage_controls() -> None:
    manifest = _manifest()
    assert manifest["catalog_bindings"] == spec.catalog_cids()
    assert manifest["corpus_requirements"] == spec.corpus_requirements()
    assert manifest["isolation_policy"] == spec.isolation_policy()
    assert manifest["materialization_policy"] == spec.materialization_policy()
    assert manifest["downstream_bindings"] == spec.downstream_bindings()
    policy = manifest["materialization_policy"]
    assert policy["hugging_face_dataset_allowed"] is False
    assert policy["mutable_revision_allowed"] is False
    assert policy["repin_after_results_allowed"] is False
    isolation = manifest["isolation_policy"]
    assert isolation["historical_replay"]["descendant_objects"] == "absent"
    assert isolation["aggregation"]["answer_bytes_visible"] is False
    assert isolation["execution"]["provider_conversation_reuse_across_arms"] is False


def test_exact_public_repository_pins_and_probe_evidence() -> None:
    pins = _manifest()["source_pins"]
    assert isinstance(pins, list)
    observed = [
        (
            pin["repository_class"],
            pin["repository"],
            pin["commit"],
            pin["tree"],
            pin["archive"]["sha256"],
            pin["archive"]["size"],
            pin["license"]["spdx"],
            pin["license"]["sha256"],
        )
        for pin in pins
    ]
    assert observed == [
        (
            "typed_structured",
            "python-attrs/attrs",
            "3dca08ce5bbe673d7df25f44f3dda92505d1043d",
            "2f143c350d12dc394f3320a2d4e259dda86874d7",
            "61aae3bc10caff0a26598c38bcfa1270ae3d67914a8e4b89e8074f5a0323c568",
            812534,
            "MIT",
            "882115c95dfc2af1eeb6714f8ec6d5cbcabf667caff8729f42420da63f714e9f",
        ),
        (
            "dynamic_plugins",
            "pytest-dev/pluggy",
            "fd08ab5f811a9b2fa9124ae8cbbd393221151e2c",
            "d3aac17eab19c9e8f6f6358ad2dcaec02d734020",
            "d5f397694a7b520e09127a384369d94004acd8bef1810bcb184d0cf7567e506f",
            64481,
            "MIT",
            "d6b65e6c213a5d0b577911d34d6e5949b9f59d76c238c5071a2f3fc16cfb2606",
        ),
        (
            "mature_python",
            "django/django",
            "a3b1107a4955bdd994908efb4c6e1d03c281e69f",
            "0d45857fbbe288b56ddd4d8e124a1657421f9c48",
            "600a460db656899969c7dd4b1c70ce268eada7c49fa0b57e942da79030faa7af",
            10551627,
            "BSD-3-Clause",
            "b846415d1b514e9c1dff14a22deb906d794bc546ca6129f950a18cd091e2a669",
        ),
    ]
    assert {pin["availability_probe"]["observed_at"] for pin in pins} == {"2026-08-24T17:07:45Z"}
    assert all(pin["authority"] == "commit-tree-and-exact-archive-bytes" for pin in pins)
    assert all(pin["availability_probe"]["archive_http_status"] == 200 for pin in pins)


def test_corpus_population_is_balanced_and_preregistered() -> None:
    requirements = spec.corpus_requirements()
    assert requirements["repository_classes"] == list(spec.REPOSITORY_CLASSES)
    assert requirements["task_kinds"] == list(spec.TASK_KINDS)
    assert requirements["minimum_tasks_per_kind_per_class"] == 1
    assert requirements["minimum_total_tasks"] == 12
    assert requirements["default_eligible_configurations"] == ["A", "B", "C", "D"]
    assert "no-result-informed" in requirements["eligibility_rule"]


def test_configurations_are_exact_and_differ_only_by_the_whitelist() -> None:
    configurations = spec.validate_configuration_catalog(spec.configuration_catalog())
    by_id = {item["configuration_id"]: item for item in configurations}
    assert spec.configuration_diff(by_id["A"], by_id["B"]) == ["context_method"]
    assert by_id["A"]["model_policy"] == by_id["B"]["model_policy"]
    assert by_id["A"]["verification_policy"] == "full-runtime-verification@1"
    assert by_id["B"]["verification_policy"] == "full-runtime-verification@1"
    assert by_id["C"]["routing_enabled"] is True
    assert by_id["C"]["incremental_verification_enabled"] is True
    assert by_id["D"]["sufficiency_enabled"] is True
    assert by_id["D"]["context_expansion_enabled"] is True
    assert by_id["D"]["assurance_enabled"] is True
    assert by_id["D"]["incremental_seal_enabled"] is True
    assert by_id["D"]["human_escalation_enabled"] is True
    assert all(item["hidden_full_scoring"] is True for item in configurations)

    tampered = spec.configuration_catalog()
    tampered[1]["routing_enabled"] = True
    with pytest.raises(spec.BenchmarkSpecificationError, match="differs"):
        spec.validate_configuration_catalog(tampered)


def test_metric_catalog_is_complete_across_all_six_categories() -> None:
    metrics = spec.validate_metric_catalog(spec.metric_catalog())
    matrix = spec.metric_completeness_matrix()
    assert tuple(matrix) == spec.METRIC_CATEGORIES
    assert all(matrix[category] for category in spec.METRIC_CATEGORIES)
    assert sum(len(names) for names in matrix.values()) == len(metrics)
    required = {
        "context_reduction_bp",
        "correct_accepted_patch_rate_bp",
        "routine_frontier_escalation_rate_bp",
        "controlled_selected_test_false_negative_count",
        "stale_capsule_accepted_count",
        "stale_proof_accepted_count",
        "simulated_success_accepted_count",
        "critical_mutant_accepted_count",
        "negative_review_autonomous_accept_count",
        "total_cost_reduction_bp",
        "failed_attempt_cost_micros",
    }
    assert required.issubset({metric["name"] for metric in metrics})


def test_threshold_interface_preregisters_every_board_gate() -> None:
    manifest = _manifest()
    thresholds = _thresholds(manifest)
    admitted = spec.validate_threshold_set(
        thresholds,
        expected_manifest_cid=thresholds["corpus_manifest_cid"],
        expected_schema_catalog_cid=thresholds["schema_catalog_cid"],
    )
    assert admitted == thresholds
    primary = thresholds["primary_comparisons"]
    assert primary["context_reduction"]["minimum_bp"] == 5000
    assert primary["context_reduction"]["target_bp"] == 6000
    assert primary["total_cost_reduction"]["minimum_bp"] == 3000
    assert primary["total_cost_reduction"]["target_bp"] == 5000
    assert primary["accepted_patch_noninferiority"]["margin_bp"] == 500
    assert primary["routine_frontier_escalation"]["maximum_bp"] == 2500
    assert primary["routine_frontier_escalation"]["target_bp"] == 2000
    assert thresholds["analysis"]["bootstrap_samples"] == 10000
    assert thresholds["analysis"]["confidence_bp"] == 9500
    assert set(thresholds["zero_tolerance"].values()) == {0}

    tampered = _thresholds(manifest)
    tampered["primary_comparisons"]["context_reduction"]["minimum_bp"] = 4999
    with pytest.raises(spec.BenchmarkSpecificationError, match="changed"):
        spec.validate_threshold_set(
            tampered,
            expected_manifest_cid=thresholds["corpus_manifest_cid"],
            expected_schema_catalog_cid=thresholds["schema_catalog_cid"],
        )


def test_agent_projection_strips_hidden_evaluator_identity() -> None:
    control = _task_control()
    agent_view = spec.project_task_agent_view(control)
    assert agent_view["schema"] == spec.TASK_AGENT_VIEW_SCHEMA
    assert "sealed_evaluator_root_cid" not in agent_view
    assert "expected_patch" not in agent_view
    assert spec.validate_task_agent_view(agent_view) == agent_view

    escaped = _task_control()
    escaped["owned_paths"] = ["../hidden/answer.patch"]
    with pytest.raises(spec.BenchmarkSpecificationError, match="safe relative"):
        spec.validate_task_control(escaped)

    leaked = dict(agent_view)
    leaked["expected_patch"] = "do not expose"
    with pytest.raises(spec.BenchmarkSpecificationError, match="unknown fields"):
        spec.validate_task_agent_view(leaked)


def test_raw_results_require_complete_metrics_and_explicit_missingness() -> None:
    result = _raw_result()
    assert spec.validate_raw_result(result) == result

    nullable = _raw_result()
    nullable["metrics"]["human_cost_micros"] = None
    nullable["missingness"] = {"human_cost_micros": "no-observed-human-invoice"}
    assert spec.validate_raw_result(nullable) == nullable

    missing_reason = _raw_result()
    missing_reason["metrics"]["human_cost_micros"] = None
    with pytest.raises(spec.BenchmarkSpecificationError, match="missingness"):
        spec.validate_raw_result(missing_reason)

    incomplete = _raw_result()
    del incomplete["metrics"]["provider_call_count"]
    with pytest.raises(spec.BenchmarkSpecificationError, match="incomplete"):
        spec.validate_raw_result(incomplete)

    invalid_status = _raw_result()
    invalid_status["terminal_status"] = "passed_anyway"
    with pytest.raises(spec.BenchmarkSpecificationError, match="terminal"):
        spec.validate_raw_result(invalid_status)


def test_replay_and_simulation_are_typed_but_cannot_satisfy_live_policy() -> None:
    assert set(spec.PROVENANCE_CLASSES) == {"live", "replayed", "simulated"}
    evidence = spec.threshold_policy()["evidence_policy"]
    assert evidence["replay_counts_as_live"] is False
    assert evidence["simulation_counts_as_live"] is False
    assert evidence["estimated_cost_can_pass"] is False
    assert evidence["missing_live_provider"] == "unavailable-no-go"
