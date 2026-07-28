"""Unit tests for PLAT2-025 experiment contract and repair-dev baseline freeze."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from benchmarks.logic_pipeline.content_addressing import cid_for_dag_json
from benchmarks.semantic_roundtrip.holdout_baseline import (
    AGGREGATION_ORDER,
    BASELINE_POPULATIONS,
    BOOTSTRAP_METHOD,
    BOOTSTRAP_SAMPLES,
    CONFIDENCE_LEVEL,
    DEFAULT_BASELINE_REPORT_RELATIVE_PATH,
    EVALUATION_STATUSES,
    EVAL_REPAIR_MATRIX_REPORT_INTERFACE,
    EVAL_REPAIR_MATRIX_REPORT_SCHEMA,
    EVAL_STATUS_RUNTIME_FAILED,
    EVAL_STATUS_SEMANTIC_SCORED,
    EXPERIMENT_TASK_ID,
    HoldoutBaselineError,
    NONINFERIORITY_MARGIN,
    PACKET_TOKEN_BUDGET,
    PLATEAU2_EXPERIMENT_CONTRACT_INTERFACE,
    PLATEAU2_EXPERIMENT_CONTRACT_SCHEMA,
    POST_PLAT_BASELINE_E2E_MEAN,
    PRODUCTION_ARM_ID,
    SELECTION_GATE_IDS,
    assert_blind_seal_unopened,
    bootstrap_definition,
    build_experiment_contract,
    build_repair_dev_baseline_report,
    capture_environment_toolchain,
    capture_git_tree_binding,
    failure_taxonomy_definition,
    load_population_and_residual_cids,
    load_repair_dev_baseline_report,
    metric_facet_definitions,
    mint_new_experiment_identity,
    noninferiority_and_promotion_rules,
    packet_token_budget_definition,
    parse_experiment_contract,
    parse_repair_dev_baseline_report,
    run_deterministic_baseline,
    score_deterministic_case,
    write_repair_dev_baseline_report,
)
from benchmarks.semantic_roundtrip.holdout_protocol import (
    BLIND_SEAL_RELATIVE_PATH,
    load_frozen_blind_holdout_seal,
)
from benchmarks.semantic_roundtrip.matrix import load_matrix_cases
from benchmarks.semantic_roundtrip.residual_catalog import (
    HOLDOUT_BASELINE_REPORT_CID,
    PILOT_CASE_IDS,
    PILOT_CASES_RELATIVE_PATH,
    POPULATION_KIND_AUTHORIZED_BLIND_EVALUATION,
    POPULATION_KIND_PILOT,
    POPULATION_KIND_REPAIR_DEVELOPMENT,
    REPAIR_DEV_CASES_RELATIVE_PATH,
)


ROOT = Path(__file__).resolve().parents[4]
BASELINE_PATH = ROOT / DEFAULT_BASELINE_REPORT_RELATIVE_PATH
BASELINE_DOCS = ROOT / "docs/benchmarks/semantic_roundtrip_plateau2_baseline.md"


# ---------------------------------------------------------------------------
# Frozen protocol constants
# ---------------------------------------------------------------------------


def test_interfaces_and_core_constants_are_frozen() -> None:
    assert PLATEAU2_EXPERIMENT_CONTRACT_INTERFACE == "Plateau2ExperimentContract@1"
    assert (
        PLATEAU2_EXPERIMENT_CONTRACT_SCHEMA
        == "ipfs-datasets.semantic-roundtrip-plateau2-experiment-contract.v1"
    )
    assert EVAL_REPAIR_MATRIX_REPORT_INTERFACE == "EvalRepairMatrixReport@1"
    assert (
        EVAL_REPAIR_MATRIX_REPORT_SCHEMA
        == "ipfs-datasets.semantic-roundtrip-plateau2-repair-dev-baseline.v1"
    )
    assert PRODUCTION_ARM_ID == (
        "typed_deontic__no_guidance__no_repair__not_applicable__deterministic"
    )
    assert POST_PLAT_BASELINE_E2E_MEAN == 0.0
    assert POST_PLAT_BASELINE_E2E_MEAN == 0.0
    assert HOLDOUT_BASELINE_REPORT_CID.startswith("baguqeera")
    assert AGGREGATION_ORDER == "per_case_first_macro_mean"
    assert BOOTSTRAP_METHOD == "seeded_percentile_case_cluster_bootstrap"
    assert BOOTSTRAP_SAMPLES == 10_000
    assert CONFIDENCE_LEVEL == 0.95
    assert NONINFERIORITY_MARGIN == 0.03
    assert PACKET_TOKEN_BUDGET == 8_192
    assert tuple(BASELINE_POPULATIONS) == (
        POPULATION_KIND_PILOT,
        POPULATION_KIND_REPAIR_DEVELOPMENT,
    )
    assert set(SELECTION_GATE_IDS) == {
        "full_coverage",
        "source_copy_exclusion",
        "polarity_preservation",
    }
    assert EVALUATION_STATUSES == {
        "semantic_scored",
        "not_measured",
        "runtime_failed",
        "unsupported",
    }


def test_metric_bootstrap_budget_and_taxonomy_helpers() -> None:
    metrics = metric_facet_definitions()
    assert metrics["primary_promotion_metric"] == "end_to_end_loss"
    assert metrics["aggregation_order"] == AGGREGATION_ORDER
    assert set(metrics["facet_names"]) == {
        "modality",
        "conditions",
        "exceptions",
        "temporal",
    }

    bootstrap = bootstrap_definition()
    assert bootstrap["bootstrap_samples"] == BOOTSTRAP_SAMPLES
    assert bootstrap["confidence_level"] == CONFIDENCE_LEVEL
    assert bootstrap["bootstrap_unit"] == "case_cluster"

    rules = noninferiority_and_promotion_rules()
    assert rules["noninferiority_margin"] == NONINFERIORITY_MARGIN
    assert rules["underpowered_cannot_promote"] is True
    assert rules["promotion_requires_full_gates"] is True

    budget = packet_token_budget_definition()
    assert budget["max_tokens"] == PACKET_TOKEN_BUDGET
    assert budget["omitted_handle_coverage_required"] is True

    taxonomy = failure_taxonomy_definition()
    assert set(taxonomy["evaluation_statuses"]) == EVALUATION_STATUSES
    assert taxonomy["non_semantic_excluded_from_score_aggregates"] is True


# ---------------------------------------------------------------------------
# Source tree / populations / blind seal
# ---------------------------------------------------------------------------


def test_capture_git_tree_and_environment() -> None:
    tree = capture_git_tree_binding(ROOT)
    assert len(tree["commit"]) == 40
    assert len(tree["tree"]) == 40
    assert int(tree["gitlink_count"]) >= 1
    assert tree["gitlinks_cid"].startswith("baguqeera")
    assert tree["tree_binding_cid"].startswith("baguqeera")
    # Benchmark-bounded inventory includes top-level ipfs_accelerate_py.
    paths = {item["path"] for item in tree["gitlinks"]}  # type: ignore[union-attr]
    assert "ipfs_accelerate_py" in paths

    env = capture_environment_toolchain()
    assert "python_version" in env
    assert env["constructor_identity"] == "TypedDeonticCanonicalConstructor@1"
    assert env["realizer_identity"] == "CanonicalDeterministicRealizer@1"


def test_population_and_residual_cids_bind_pilot_and_repair_dev() -> None:
    bindings = load_population_and_residual_cids(ROOT)
    pilot = bindings["pilot"]
    repair = bindings["repair_development"]
    assert pilot["population_kind"] == POPULATION_KIND_PILOT
    assert tuple(pilot["case_ids"]) == PILOT_CASE_IDS
    assert pilot["manifest_cid"].startswith("baguqeera")
    assert pilot["residual_catalog_cid"].startswith("baguqeera")
    assert repair["population_kind"] == POPULATION_KIND_REPAIR_DEVELOPMENT
    assert repair["population_cid"].startswith("baguqeera")
    assert repair["residual_catalog_cid"].startswith("baguqeera")
    assert repair["tree_cid"].startswith("baguqeera")
    assert set(pilot["case_ids"]).isdisjoint(set(repair["case_ids"]))
    seal = load_frozen_blind_holdout_seal(repository_root=ROOT)
    assert bindings["blind_holdout_seal_cid"] == seal.seal_cid


def test_blind_seal_remains_unopened_with_zero_receipts() -> None:
    status = assert_blind_seal_unopened(ROOT)
    assert status["blind_seal_unopened"] is True
    assert status["access_receipt_count"] == 0
    assert status["status"] == "sealed_unopened"
    assert status["private_content_absent_from_public_seal"] is True
    seal_path = ROOT / BLIND_SEAL_RELATIVE_PATH
    raw = json.loads(seal_path.read_text(encoding="utf-8"))
    for forbidden in (
        "case_ids",
        "source_text",
        "gold_ir",
        "labels",
        "per_case_digests",
        "semantic_hints",
    ):
        assert forbidden not in raw


# ---------------------------------------------------------------------------
# Experiment contract
# ---------------------------------------------------------------------------


def test_build_and_parse_experiment_contract() -> None:
    contract = build_experiment_contract(ROOT)
    parsed = parse_experiment_contract(contract)
    assert parsed["interface"] == PLATEAU2_EXPERIMENT_CONTRACT_INTERFACE
    assert parsed["schema_version"] == PLATEAU2_EXPERIMENT_CONTRACT_SCHEMA
    assert parsed["task_id"] == EXPERIMENT_TASK_ID
    assert parsed["arm_config"]["arm_id"] == PRODUCTION_ARM_ID
    assert parsed["arm_config"]["post_plat_baseline_e2e_mean"] == 0.0
    assert parsed["bootstrap"]["bootstrap_method"] == BOOTSTRAP_METHOD
    assert parsed["decision_rules"]["noninferiority_margin"] == NONINFERIORITY_MARGIN
    assert parsed["packet_token_budget"]["max_tokens"] == PACKET_TOKEN_BUDGET
    assert parsed["metrics"]["aggregation_order"] == AGGREGATION_ORDER
    assert parsed["blind_holdout"]["access_receipt_count"] == 0
    assert parsed["protocol_change_policy"]["mutable_after_freeze"] is False
    assert "autoencoder" in parsed["capability_policy"]
    assert parsed["capability_policy"]["leanstral"]["semantic_authority"] is False
    assert parsed["capability_policy"]["hammer"]["semantic_authority"] is False
    assert parsed["source_tree"]["commit"]
    assert parsed["source_tree"]["gitlinks_cid"]
    assert parsed["populations"]["repair_development"]["residual_catalog_cid"]
    # CID round-trip stability.
    identity = {
        key: value
        for key, value in contract.items()
        if key
        not in {
            "contract_cid",
            "contract_cid_codec",
            "contract_cid_scope",
            "experiment_id",
        }
    }
    assert contract["contract_cid"] == cid_for_dag_json(identity)


def test_experiment_contract_rejects_tampered_margin() -> None:
    contract = build_experiment_contract(ROOT)
    tampered = copy.deepcopy(contract)
    tampered["decision_rules"]["noninferiority_margin"] = 0.5
    # Rebind CID so only the semantic check fails.
    identity = {
        key: value
        for key, value in tampered.items()
        if key
        not in {
            "contract_cid",
            "contract_cid_codec",
            "contract_cid_scope",
            "experiment_id",
        }
    }
    tampered["contract_cid"] = cid_for_dag_json(identity)
    with pytest.raises(HoldoutBaselineError, match="noninferiority_margin"):
        parse_experiment_contract(tampered)


def test_mint_new_experiment_identity_retires_previous() -> None:
    contract = build_experiment_contract(ROOT)
    successor = mint_new_experiment_identity(
        contract, reason="protocol_bootstrap_seed_change"
    )
    assert successor["experiment_id"] != contract["experiment_id"]
    assert successor["experiment_revision"] == contract["experiment_revision"] + 1
    assert successor["previous_experiment_id"] == contract["experiment_id"]
    assert successor["retirement"]["retired"] is True
    assert "invalid" in successor["retired_receipts_policy"]


# ---------------------------------------------------------------------------
# Deterministic scoring
# ---------------------------------------------------------------------------


def test_score_deterministic_case_on_pilot_control() -> None:
    cases = load_matrix_cases(ROOT / PILOT_CASES_RELATIVE_PATH)
    by_id = {case.case_id: case for case in cases}
    case = by_id["exec_order_1"]
    record = score_deterministic_case(case)
    assert record["case_id"] == "exec_order_1"
    assert record["arm_id"] == PRODUCTION_ARM_ID
    assert record["evaluation_status"] == EVAL_STATUS_SEMANTIC_SCORED
    assert record["semantic_score_eligible"] is True
    assert record["losses"]["forward"] == pytest.approx(0.0)
    assert record["losses"]["cycle"] == pytest.approx(0.0)
    assert record["losses"]["end_to_end"] == pytest.approx(0.0)
    assert record["gates"]["full_coverage"] is True
    assert record["gates"]["polarity_preservation"] is True
    assert set(record["facets"]["end_to_end"]) == {
        "modality",
        "conditions",
        "exceptions",
        "temporal",
    }


def test_run_deterministic_baseline_rejects_blind_population() -> None:
    with pytest.raises(HoldoutBaselineError, match="rejects population"):
        run_deterministic_baseline(
            ROOT,
            populations=(POPULATION_KIND_AUTHORIZED_BLIND_EVALUATION,),
        )


def test_build_baseline_report_from_injected_population_results() -> None:
    """Avoid multi-minute live re-score: inject a minimal synthetic score block."""

    def _case(
        case_id: str,
        *,
        e2e: float = 0.0,
        source_copy: bool = True,
    ) -> dict[str, object]:
        return {
            "arm_id": PRODUCTION_ARM_ID,
            "case_cid": f"cid-{case_id}",
            "case_id": case_id,
            "evaluation_status": EVAL_STATUS_SEMANTIC_SCORED,
            "evaluation_status_reason": "success",
            "facets": {
                "cycle": {
                    "modality": 1.0,
                    "conditions": 1.0,
                    "exceptions": 1.0,
                    "temporal": 1.0,
                },
                "end_to_end": {
                    "modality": 1.0,
                    "conditions": 1.0,
                    "exceptions": 1.0,
                    "temporal": 1.0,
                },
                "forward": {
                    "modality": 1.0,
                    "conditions": 1.0,
                    "exceptions": 1.0,
                    "temporal": 1.0,
                },
            },
            "gates": {
                "full_coverage": True,
                "polarity_preservation": True,
                "selection_eligible": source_copy,
                "source_copy_exclusion": source_copy,
            },
            "losses": {
                "cycle": 0.0,
                "end_to_end": e2e,
                "forward": e2e,
            },
            "polarity": {"gate_passed": True, "inversion_count": 0},
            "semantic_score_eligible": True,
            "source_copy": {
                "copy_risk": not source_copy,
                "gate_passed": source_copy,
                "shared_8gram_precision": 0.0,
            },
        }

    pilot_cases = [_case(case_id) for case_id in PILOT_CASE_IDS]
    repair_ids = [
        case.case_id
        for case in load_matrix_cases(ROOT / REPAIR_DEV_CASES_RELATIVE_PATH)
    ]
    repair_cases = [
        _case(case_id, e2e=0.1 if index % 2 else 0.0)
        for index, case_id in enumerate(repair_ids)
    ]
    # One runtime-failed synthetic row to exercise taxonomy.
    repair_cases.append(
        {
            "arm_id": PRODUCTION_ARM_ID,
            "case_cid": "cid-failed",
            "case_id": "synthetic_runtime_failed",
            "detail": "injected",
            "evaluation_status": EVAL_STATUS_RUNTIME_FAILED,
            "evaluation_status_reason": "constructor_failed",
            "facets": None,
            "gates": {
                "full_coverage": False,
                "polarity_preservation": False,
                "selection_eligible": False,
                "source_copy_exclusion": False,
            },
            "losses": {"cycle": 1.0, "end_to_end": 1.0, "forward": 1.0},
            "polarity": None,
            "semantic_score_eligible": False,
            "source_copy": None,
        }
    )

    def _block(cases: list[dict[str, object]], kind: str) -> dict[str, object]:
        scored = [c for c in cases if c["semantic_score_eligible"]]
        return {
            "aggregates": {
                "aggregation": AGGREGATION_ORDER,
                "case_count": len(cases),
                "gate_pass_counts": {
                    "full_coverage": sum(
                        1 for c in cases if c["gates"]["full_coverage"]  # type: ignore[index]
                    ),
                    "polarity_preservation": sum(
                        1
                        for c in cases
                        if c["gates"]["polarity_preservation"]  # type: ignore[index]
                    ),
                    "selection_eligible": sum(
                        1
                        for c in cases
                        if c["gates"]["selection_eligible"]  # type: ignore[index]
                    ),
                    "source_copy_exclusion": sum(
                        1
                        for c in cases
                        if c["gates"]["source_copy_exclusion"]  # type: ignore[index]
                    ),
                },
                "means": {
                    "cycle": 0.0,
                    "end_to_end": sum(
                        float(c["losses"]["end_to_end"])  # type: ignore[index]
                        for c in scored
                    )
                    / max(len(scored), 1),
                    "forward": sum(
                        float(c["losses"]["forward"])  # type: ignore[index]
                        for c in scored
                    )
                    / max(len(scored), 1),
                },
                "scored_case_count": len(scored),
                "status_counts": {
                    "not_measured": 0,
                    "runtime_failed": sum(
                        1
                        for c in cases
                        if c["evaluation_status"] == EVAL_STATUS_RUNTIME_FAILED
                    ),
                    "semantic_scored": len(scored),
                    "unsupported": 0,
                },
            },
            "cases": cases,
            "failure_clusters": {
                "evaluation_runtime_failed": [
                    c["case_id"]
                    for c in cases
                    if c["evaluation_status"] == EVAL_STATUS_RUNTIME_FAILED
                ],
                "loss_end_to_end_nonzero": [
                    c["case_id"]
                    for c in scored
                    if float(c["losses"]["end_to_end"]) > 0.0  # type: ignore[index]
                ],
            },
            "population_kind": kind,
        }

    population_results = {
        POPULATION_KIND_PILOT: _block(pilot_cases, POPULATION_KIND_PILOT),
        POPULATION_KIND_REPAIR_DEVELOPMENT: _block(
            repair_cases, POPULATION_KIND_REPAIR_DEVELOPMENT
        ),
    }
    contract = build_experiment_contract(ROOT)
    report = build_repair_dev_baseline_report(
        ROOT,
        contract=contract,
        population_results=population_results,
        run_scoring=False,
    )
    parse_repair_dev_baseline_report(report)
    assert report["interface"] == EVAL_REPAIR_MATRIX_REPORT_INTERFACE
    assert report["experiment_id"] == contract["experiment_id"]
    assert report["contract_cid"] == contract["contract_cid"]
    assert report["blind_holdout"]["access_receipt_count"] == 0
    assert set(report["populations"]) == set(BASELINE_POPULATIONS)
    assert "blind_holdout" not in report["populations"]
    assert report["promotion_gates_snapshot"]["pilot_non_regressed"] is True

    # Write / reload round-trip.
    # (tmp path)
    # Use write helper with injected report.
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as tmp:
        out = Path(tmp) / "repair_dev_baseline.json"
        written = write_repair_dev_baseline_report(out, report=report, repo_root=ROOT)
        reloaded = json.loads(out.read_text(encoding="utf-8"))
        assert reloaded == written
        parse_repair_dev_baseline_report(reloaded)


def test_build_baseline_report_rejects_blind_population_results() -> None:
    contract = build_experiment_contract(ROOT)
    with pytest.raises(HoldoutBaselineError, match="rejects population"):
        build_repair_dev_baseline_report(
            ROOT,
            contract=contract,
            population_results={
                POPULATION_KIND_AUTHORIZED_BLIND_EVALUATION: {
                    "cases": [],
                    "aggregates": {},
                    "failure_clusters": {},
                    "population_kind": POPULATION_KIND_AUTHORIZED_BLIND_EVALUATION,
                }
            },
            run_scoring=False,
        )


# ---------------------------------------------------------------------------
# Checked-in freeze artifacts
# ---------------------------------------------------------------------------


def test_checked_in_baseline_report_parses_and_scopes_populations() -> None:
    assert BASELINE_PATH.is_file(), (
        "repair_dev_baseline.json must be written by PLAT2-025"
    )
    report = load_repair_dev_baseline_report(BASELINE_PATH, repo_root=ROOT)
    assert report["interface"] == EVAL_REPAIR_MATRIX_REPORT_INTERFACE
    assert report["arm_id"] == PRODUCTION_ARM_ID
    assert report["task_id"] == EXPERIMENT_TASK_ID
    assert report["blind_holdout"]["blind_seal_unopened"] is True
    assert report["blind_holdout"]["access_receipt_count"] == 0
    assert set(report["populations"]) == {
        POPULATION_KIND_PILOT,
        POPULATION_KIND_REPAIR_DEVELOPMENT,
    }

    pilot = report["populations"][POPULATION_KIND_PILOT]
    repair = report["populations"][POPULATION_KIND_REPAIR_DEVELOPMENT]
    pilot_ids = [item["case_id"] for item in pilot["cases"]]  # type: ignore[index]
    repair_ids = [item["case_id"] for item in repair["cases"]]  # type: ignore[index]
    assert pilot_ids == list(PILOT_CASE_IDS)
    assert set(pilot_ids).isdisjoint(set(repair_ids))
    assert pilot["aggregates"]["means"]["end_to_end"] == pytest.approx(0.0)
    assert report["promotion_gates_snapshot"]["pilot_non_regressed"] is True

    for kind, block in (
        (POPULATION_KIND_PILOT, pilot),
        (POPULATION_KIND_REPAIR_DEVELOPMENT, repair),
    ):
        for case in block["cases"]:  # type: ignore[index]
            assert case["evaluation_status"] in EVALUATION_STATUSES
            assert set(case["losses"]) == {"forward", "cycle", "end_to_end"}
            assert "gates" in case
            assert "full_coverage" in case["gates"]
            assert "source_copy_exclusion" in case["gates"]
            assert "polarity_preservation" in case["gates"]
            if case["evaluation_status"] == EVAL_STATUS_SEMANTIC_SCORED:
                assert case["facets"] is not None
                assert "end_to_end" in case["facets"]
        assert isinstance(block["failure_clusters"], dict)

    # Contract bindings are present and parseable from the report lineage.
    assert report["contract_cid"].startswith("baguqeera")
    assert report["experiment_id"].startswith("baguqeera")


def test_baseline_docs_exist_and_mention_contract_freeze() -> None:
    assert BASELINE_DOCS.is_file()
    text = BASELINE_DOCS.read_text(encoding="utf-8")
    for needle in (
        "Plateau2ExperimentContract@1",
        "EvalRepairMatrixReport@1",
        "noninferiority",
        "packet token",
        "paired",
        "bootstrap",
        "blind",
        "repair-development",
        "PLAT2-025",
        "semantic_scored",
        "not_measured",
        "runtime_failed",
        "unsupported",
    ):
        assert needle.lower() in text.lower(), f"docs missing {needle!r}"
