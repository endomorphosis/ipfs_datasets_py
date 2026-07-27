"""Contracts for the source-bound SRT-019 canonical decision.

These tests pin the fail-closed selected/declined receipt shapes used by
the operator handoff validator.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from benchmarks.logic_pipeline.content_addressing import (
    canonical_dag_json_bytes,
    cid_for_bytes,
    cid_for_dag_json,
)
from benchmarks.semantic_roundtrip.canonical_decision import (
    CANONICAL_ARTIFACT_PATHS,
    CANONICAL_DECISION_INTERFACE,
    CANONICAL_DECISION_SCHEMA,
    PARITY_POLICY_INTERFACE,
    PARITY_POLICY_SCHEMA,
    PARITY_REPORT_INTERFACE,
    PARITY_REPORT_SCHEMA,
    REQUESTED_TOOL_IDS,
    CanonicalDecisionValidationError,
    validate_canonical_decision,
    validate_canonical_decision_file,
)


ROOT = Path(__file__).resolve().parents[4]


def _with_cid(value: dict[str, Any], field: str) -> dict[str, Any]:
    result = copy.deepcopy(value)
    result[field] = cid_for_dag_json(result)
    return result


def _write(root: Path, relative: str, content: bytes) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _tool_accounting() -> dict[str, Any]:
    return {
        "requested_tool_ids": list(REQUESTED_TOOL_IDS),
        "scored_tool_ids": ["typed_deontic"],
        "unavailable": [],
        "unscored": [
            {"tool_id": tool_id, "reason": "not selected by measured arm"}
            for tool_id in REQUESTED_TOOL_IDS
            if tool_id != "typed_deontic"
        ],
    }


def _reproduction() -> dict[str, Any]:
    return {
        "commands": [
            {
                "purpose": "composition_report_validation",
                "command": (
                    "PYTHONPATH=. python "
                    "benchmarks/bench_semantic_roundtrip_compositions.py "
                    "--validate-report report.json"
                ),
            },
            {
                "purpose": "canonical_schema_tests",
                "command": (
                    "PYTHONPATH=. python -m pytest "
                    "tests/unit/logic/legal_ir/"
                    "test_canonical_roundtrip_schema.py -q"
                ),
            },
            {
                "purpose": "canonical_parity_tests",
                "command": (
                    "PYTHONPATH=. python -m pytest "
                    "tests/integration/logic/"
                    "test_canonical_semantic_roundtrip.py -q"
                ),
            },
            {
                "purpose": "decision_validation",
                "command": (
                    "PYTHONPATH=. python "
                    "benchmarks/bench_semantic_roundtrip_compositions.py "
                    "--validate-canonical-decision decision.json"
                ),
            },
        ],
        "supervisor_commands": [
            {
                "purpose": "supervisor_plan",
                "command": (
                    "PYTHONPATH=. python "
                    "benchmarks/semantic_roundtrip_scheduler.py plan"
                ),
            },
            {
                "purpose": "supervisor_launch",
                "command": (
                    "PYTHONPATH=. python "
                    "benchmarks/semantic_roundtrip_scheduler.py launch"
                ),
            },
        ],
    }


def _selected_fixture(root: Path) -> dict[str, Any]:
    case_ids = ["case-a", "case-b"]
    uncertainty = {
        "method": "seeded_percentile_case_cluster_bootstrap",
        "confidence_level": 0.95,
        "bootstrap_samples": 10_000,
        "resampling_unit": "case_after_within_case_repeat_aggregation",
        "low": 0.1,
        "high": 0.3,
    }
    composition = _with_cid(
        {
            "selection": {
                "outcome": "selected",
                "winner": {"arm_id": "arm-a"},
                "co_winner_arm_ids": ["arm-a"],
            },
            "statistics": {
                "arm_summaries": {
                    "arm-a": {
                        "aggregate": {
                            "end_to_end": {
                                "mean": 0.2,
                                "uncertainty": uncertainty,
                            }
                        },
                        "per_case": {
                            "case-a": {"losses": {"end_to_end": 0.1}},
                            "case-b": {"losses": {"end_to_end": 0.3}},
                        },
                    }
                }
            },
            "inputs": {"fixture": {"case_ids": case_ids}},
        },
        "report_cid",
    )
    composition_path = _write(
        root,
        CANONICAL_ARTIFACT_PATHS["composition_report"],
        canonical_dag_json_bytes(composition) + b"\n",
    )

    implementation_paths: dict[str, Path] = {}
    for name in ("specification", "ir_schema", "compiler", "decompiler", "roundtrip"):
        implementation_paths[name] = _write(
            root,
            CANONICAL_ARTIFACT_PATHS[name],
            f"{name} fixture\n".encode(),
        )

    policy = _with_cid(
        {
            "interface": PARITY_POLICY_INTERFACE,
            "schema_version": PARITY_POLICY_SCHEMA,
            "metric": "end_to_end_loss",
            "comparison": "canonical_minus_selected",
            "decision_rule": (
                "upper_confidence_bound_lte_noninferiority_margin"
            ),
            "confidence_level": 0.95,
            "bootstrap_method": "seeded_percentile_case_cluster_bootstrap",
            "bootstrap_samples": 10_000,
            "resampling_unit": (
                "case_after_within_case_repeat_aggregation"
            ),
            "noninferiority_margin": 0.03,
            "frozen_from_report_cid": composition["report_cid"],
        },
        "policy_cid",
    )
    policy_path = _write(
        root,
        CANONICAL_ARTIFACT_PATHS["parity_policy"],
        canonical_dag_json_bytes(policy) + b"\n",
    )

    implementation_cids = {
        name: cid_for_bytes(implementation_paths[name].read_bytes())
        for name in ("ir_schema", "compiler", "decompiler", "roundtrip")
    }
    case_results = []
    for case_id, selected_loss in (("case-a", 0.1), ("case-b", 0.3)):
        case_results.append(
            {
                "case_id": case_id,
                "status": "success",
                "canonical_l1_cid": cid_for_bytes(f"{case_id}-l1".encode()),
                "realized_text_cid": cid_for_bytes(f"{case_id}-text".encode()),
                "canonical_l2_cid": cid_for_bytes(f"{case_id}-l2".encode()),
                "end_to_end_loss": selected_loss + 0.01,
                "selected_arm_end_to_end_loss": selected_loss,
                "canonical_minus_selected": 0.01,
                "full_nonempty_coverage": True,
                "polarity_hard_failure": False,
                "source_copy_violation": False,
            }
        )
    configuration_cid = cid_for_bytes(b"configuration")
    parity = _with_cid(
        {
            "interface": PARITY_REPORT_INTERFACE,
            "schema_version": PARITY_REPORT_SCHEMA,
            "status": "complete",
            "composition_report_cid": composition["report_cid"],
            "parity_policy_cid": policy["policy_cid"],
            "selected_arm_id": "arm-a",
            "execution": {
                "case_count": 2,
                "observed_terminal_case_count": 2,
                "missing_case_count": 0,
                "case_results": case_results,
            },
            "comparison": {
                "metric": "end_to_end_loss",
                "direction": "canonical_minus_selected",
                "case_deltas": {"case-a": 0.01, "case-b": 0.01},
                "estimate": 0.01,
                "uncertainty": {
                    "method": "seeded_percentile_case_cluster_bootstrap",
                    "confidence_level": 0.95,
                    "bootstrap_samples": 10_000,
                    "resampling_unit": (
                        "case_after_within_case_repeat_aggregation"
                    ),
                    "low": 0.0,
                    "high": 0.02,
                },
                "noninferiority_margin": 0.03,
                "within_tolerance": True,
            },
            "structural_checks": {
                tool_id: {
                    "applicable": tool_id != "lean",
                    "status": (
                        "passed" if tool_id != "lean" else "not_applicable"
                    ),
                    "reason": (
                        "checked" if tool_id != "lean" else "no Lean obligation"
                    ),
                }
                for tool_id in ("hammer", "cvc5", "lean")
            },
            "lineage": {
                "configuration_cids": [configuration_cid],
                "model_cids": [],
                "implementation_raw_cids": implementation_cids,
            },
        },
        "report_cid",
    )
    parity_path = _write(
        root,
        CANONICAL_ARTIFACT_PATHS["parity_report"],
        canonical_dag_json_bytes(parity) + b"\n",
    )

    paths = {
        "composition_report": composition_path,
        "parity_policy": policy_path,
        "parity_report": parity_path,
        **implementation_paths,
    }
    artifacts = {
        name: {
            "path": CANONICAL_ARTIFACT_PATHS[name],
            "raw_cid": cid_for_bytes(paths[name].read_bytes()),
        }
        for name in CANONICAL_ARTIFACT_PATHS
    }
    decision = _with_cid(
        {
            "interface": CANONICAL_DECISION_INTERFACE,
            "schema_version": CANONICAL_DECISION_SCHEMA,
            "decision": {
                "status": "selected",
                "selected_arm_id": "arm-a",
                "evidence_complete": True,
                "parity_passed": True,
                "reason_codes": [],
            },
            "artifacts": artifacts,
            "selected_composition": {
                "arm_id": "arm-a",
                "selection_basis": "srt014_unique_winner",
                "reconstruction_loss": {
                    "metric": "end_to_end_loss",
                    "aggregation": "per_case_first_macro_mean",
                    "mean": 0.2,
                    "uncertainty": uncertainty,
                },
                "deterministic_stages": [
                    {
                        "stage_id": "compiler",
                        "component": "typed_deontic",
                        "role": "constructor",
                    }
                ],
                "optional_learned_stages": [],
            },
            "parity": {
                "status": "passed",
                "policy_cid": policy["policy_cid"],
                "report_cid": parity["report_cid"],
                "observed_upper_bound": 0.02,
                "noninferiority_margin": 0.03,
                "within_tolerance": True,
            },
            "tool_accounting": _tool_accounting(),
            "lineage": {
                "configuration_cids": [configuration_cid],
                "model_cids": [],
            },
            "reproduction": _reproduction(),
        },
        "decision_cid",
    )
    return decision


def _accept_composition(_value: object) -> dict[str, object]:
    return {"status": "valid"}


def test_selected_decision_recomputes_source_bound_parity(
    tmp_path: Path,
) -> None:
    decision = _selected_fixture(tmp_path)

    result = validate_canonical_decision(
        decision,
        repo_root=tmp_path,
        composition_validator=_accept_composition,
    )

    assert result["status"] == "valid"
    assert result["decision_status"] == "selected"
    assert result["selected_arm_id"] == "arm-a"
    assert result["evidence_complete"] is True
    assert result["parity_passed"] is True

    path = tmp_path / "decision.json"
    path.write_bytes(canonical_dag_json_bytes(decision) + b"\n")
    from_file = validate_canonical_decision_file(
        path,
        repo_root=tmp_path,
        composition_validator=_accept_composition,
    )
    assert from_file["decision_cid"] == decision["decision_cid"]


def test_selected_decision_rejects_parity_margin_drift(
    tmp_path: Path,
) -> None:
    decision = _selected_fixture(tmp_path)
    parity_path = (
        tmp_path / CANONICAL_ARTIFACT_PATHS["parity_report"]
    )
    parity = json.loads(parity_path.read_bytes())
    parity["comparison"]["noninferiority_margin"] = 0.04
    parity.pop("report_cid")
    parity["report_cid"] = cid_for_dag_json(parity)
    parity_path.write_bytes(canonical_dag_json_bytes(parity) + b"\n")
    decision["artifacts"]["parity_report"]["raw_cid"] = cid_for_bytes(
        parity_path.read_bytes()
    )
    decision["parity"]["report_cid"] = parity["report_cid"]
    decision.pop("decision_cid")
    decision["decision_cid"] = cid_for_dag_json(decision)

    with pytest.raises(
        CanonicalDecisionValidationError,
        match="margin differs from the frozen SRT-015 policy",
    ):
        validate_canonical_decision(
            decision,
            repo_root=tmp_path,
            composition_validator=_accept_composition,
        )


def test_selected_decision_rejects_incomplete_srt014_evidence(
    tmp_path: Path,
) -> None:
    decision = _selected_fixture(tmp_path)

    def reject_composition(_value: object) -> dict[str, object]:
        raise ValueError("missing frozen coordinates")

    with pytest.raises(
        CanonicalDecisionValidationError,
        match="composition evidence is invalid: missing frozen coordinates",
    ):
        validate_canonical_decision(
            decision,
            repo_root=tmp_path,
            composition_validator=reject_composition,
        )


def test_nonselectable_srt014_outcome_requires_declined_decision(
    tmp_path: Path,
) -> None:
    composition = _with_cid(
        {
            "selection": {
                "outcome": "no_eligible_composition",
                "winner": None,
                "co_winner_arm_ids": [],
            },
            "statistics": {"arm_summaries": {}},
            "inputs": {"fixture": {"case_ids": ["case-a"]}},
        },
        "report_cid",
    )
    composition_path = _write(
        tmp_path,
        CANONICAL_ARTIFACT_PATHS["composition_report"],
        canonical_dag_json_bytes(composition) + b"\n",
    )
    artifacts: dict[str, object] = {
        name: None for name in CANONICAL_ARTIFACT_PATHS
    }
    artifacts["composition_report"] = {
        "path": CANONICAL_ARTIFACT_PATHS["composition_report"],
        "raw_cid": cid_for_bytes(composition_path.read_bytes()),
    }
    decision = _with_cid(
        {
            "interface": CANONICAL_DECISION_INTERFACE,
            "schema_version": CANONICAL_DECISION_SCHEMA,
            "decision": {
                "status": "declined",
                "selected_arm_id": None,
                "evidence_complete": False,
                "parity_passed": False,
                "reason_codes": ["srt014_no_eligible_composition"],
            },
            "artifacts": artifacts,
            "selected_composition": None,
            "parity": {
                "status": "incomplete",
                "policy_cid": None,
                "report_cid": None,
                "observed_upper_bound": None,
                "noninferiority_margin": None,
                "within_tolerance": False,
            },
            "tool_accounting": _tool_accounting(),
            "lineage": {"configuration_cids": [], "model_cids": []},
            "reproduction": _reproduction(),
        },
        "decision_cid",
    )

    result = validate_canonical_decision(
        decision,
        repo_root=tmp_path,
        composition_validator=_accept_composition,
    )

    assert result["decision_status"] == "declined"
    assert result["evidence_complete"] is False
    assert result["parity_passed"] is False


def test_cli_dispatches_canonical_decision_validator_without_inference(
    tmp_path: Path,
) -> None:
    malformed = tmp_path / "malformed.json"
    malformed.write_bytes(canonical_dag_json_bytes({}) + b"\n")

    completed = subprocess.run(
        [
            sys.executable,
            "benchmarks/bench_semantic_roundtrip_compositions.py",
            "--validate-canonical-decision",
            str(malformed),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 1
    assert completed.stdout == ""
    error = json.loads(completed.stderr)
    assert error["status"] == "invalid"
    assert "fields changed" in error["error"]
