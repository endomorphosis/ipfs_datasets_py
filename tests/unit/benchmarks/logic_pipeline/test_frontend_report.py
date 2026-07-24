"""Executable tests for the spaCy/SyMAI front-end overlap report."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from benchmarks.logic_pipeline import frontend_report, report
from benchmarks.logic_pipeline.contracts import (
    DEFAULT_PROTOCOL_SHA256,
    canonical_json,
)
from benchmarks.logic_pipeline.variants import VARIANT_REGISTRY_SHA256


ROOT = Path(__file__).resolve().parents[4]
ARTIFACT_SHA256 = (
    "86cc7263efe890a80e0ecf3518eaefaad8dfbabb4fb35d544be83905e4c32404"
)


def _redigest(value: dict[str, object]) -> dict[str, object]:
    value["artifact_sha256"] = hashlib.sha256(
        canonical_json(
            {
                key: item
                for key, item in value.items()
                if key != "artifact_sha256"
            }
        ).encode("utf-8")
    ).hexdigest()
    return value


def _measured_observations() -> list[dict[str, object]]:
    """Create a complete synthetic matrix for exercising pure derivation.

    These rows are deliberately passed only to ``derive_frontend_analysis``.
    They are not represented as captured execution evidence and therefore are
    not passed through the measured-report validator, which correctly requires
    a full provenance-bound ``CaseResultRecord`` for every measured cell.
    """

    value = copy.deepcopy(frontend_report.create_capability_preflight_report())
    observations = value["observations"]
    assert isinstance(observations, list)
    for row in observations:
        assert isinstance(row, dict)
        case_id = str(row["case_id"])
        variant_id = str(row["variant_id"])
        expected_class = str(row["expected_class"])
        symai_variant = variant_id in {"A4", "A5", "A7", "A8"}
        symai_call = variant_id == "A5" or (
            symai_variant and case_id.endswith("06")
        )
        row.update(
            {
                "status": "semantically_correct",
                "semantic_signature_sha256": hashlib.sha256(
                    case_id.encode("utf-8")
                ).hexdigest(),
                "normalized_ir_exact_match": True,
                "deterministic_semantic_equivalence": False,
                "semantic_validator_receipt_sha256": None,
                "predicted_class": expected_class,
                "ambiguity_classification_correct": (
                    True if expected_class == "ambiguous" else None
                ),
                "fail_closed_classification_correct": (
                    True
                    if expected_class in {"disproved", "unsupported"}
                    else None
                ),
                "spacy_invoked": variant_id != "A0",
                "symai_invoked": symai_variant,
                "symai_model_calls": int(symai_call),
                "total_wall_time_ms": 10.0 + int(symai_call),
                "model_calls": int(symai_call),
                "missing_reason": None,
            }
        )

    # On one ambiguity case the full-spaCy/no-SyMAI arm regresses from A0,
    # while gated SyMAI recovers the reviewed semantics.  Always-on SyMAI then
    # spends a call without improving on the gated result.
    a1 = next(
        row
        for row in observations
        if row["split"] == "pilot"
        and row["cache_mode"] == "cold"
        and row["variant_id"] == "A1"
        and row["case_id"] == "pilot-p06"
    )
    a1.update(
        {
            "status": "semantically_incorrect",
            "semantic_signature_sha256": hashlib.sha256(
                b"pilot-p06-full-spacy-disagreement"
            ).hexdigest(),
            "normalized_ir_exact_match": False,
            "predicted_class": "unsupported",
            "ambiguity_classification_correct": False,
        }
    )
    return observations


def _analysis_record(
    analysis: dict[str, object],
    collection: str,
    **identity: str,
) -> dict[str, object]:
    rows = analysis[collection]
    assert isinstance(rows, list)
    return next(
        row
        for row in rows
        if isinstance(row, dict)
        and all(row.get(name) == expected for name, expected in identity.items())
    )


def test_checked_in_report_freezes_exact_matrix_marker_and_identities() -> None:
    value = frontend_report.load_frontend_report(
        ROOT / frontend_report.DEFAULT_FRONTEND_REPORT_PATH
    )

    assert frontend_report.HSSLEV0519C80() == (
        "paired spaCy and SyMAI front-end overlap, unique-win, "
        "unnecessary-call, and capability-missingness report"
    )
    assert report.HSSLEV0519C80() == frontend_report.HSSLEV0519C80()
    assert value["evidence"] == frontend_report.HSSLEV0519C80()
    assert value["protocol_sha256"] == DEFAULT_PROTOCOL_SHA256
    assert value["registry_sha256"] == VARIANT_REGISTRY_SHA256
    assert value["artifact_sha256"] == ARTIFACT_SHA256
    assert value["variant_ids"] == ["A0", "A1", "A4", "A5", "A7", "A8"]
    assert value["cache_modes"] == ["cold", "warm"]
    assert value["development_selection"] == {
        "status": "preregistered_full_split",
        "case_ids": value["case_ids_by_split"]["development"],
        "selection_basis": (
            "all reviewed development cases; no outcome-derived case shortlist"
        ),
        "outcomes_inspected": False,
    }

    expected_coordinates = [
        (split, mode, variant, case_id)
        for split in frontend_report.SPLITS
        for mode in frontend_report.CACHE_MODES
        for variant in frontend_report.FRONTEND_VARIANT_IDS
        for case_id in value["case_ids_by_split"][split]
    ]
    actual_coordinates = [
        (
            row["split"],
            row["cache_mode"],
            row["variant_id"],
            row["case_id"],
        )
        for row in value["observations"]
    ]
    assert len(actual_coordinates) == 240
    assert actual_coordinates == expected_coordinates
    assert len(set(actual_coordinates)) == 240
    assert set(value["stratum_by_case"].values()) == {
        "simple_fol",
        "nested_quantifiers",
        "modal_deontic",
        "temporal_rules",
        "epistemic_rules",
        "legal_ir_ambiguity",
        "multi_premise",
        "contradiction",
        "hammer_obligation",
        "invalid_syntax",
    }


def test_each_arm_records_the_exact_frozen_frontend_policy() -> None:
    value = frontend_report.create_capability_preflight_report()
    identities: dict[str, tuple[str, str]] = {}
    for row in value["observations"]:
        identity = (row["spacy_mode"], row["symai_policy"])
        previous = identities.setdefault(row["variant_id"], identity)
        assert previous == identity

    assert identities == {
        "A0": ("current_effective", "off"),
        "A1": ("full_model", "off"),
        "A4": ("full_model", "ambiguity_gated"),
        "A5": ("full_model", "always"),
        "A7": ("regex_legal", "ambiguity_gated"),
        "A8": ("blank_model", "ambiguity_gated"),
    }


def test_capability_missingness_is_retained_as_null_not_scored_zero() -> None:
    value = frontend_report.create_capability_preflight_report()

    assert value["execution_mode"] == "capability_preflight"
    assert value["capabilities"]["spacy_full_model"]["status"] == "unavailable"
    assert value["capabilities"]["symai"]["status"] == "degraded"
    assert value["capabilities"]["llm_router"]["status"] == "degraded"
    for row in value["observations"]:
        assert row["status"] == "unavailable"
        assert row["case_result"] is None
        assert row["semantic_signature_sha256"] is None
        assert row["normalized_ir_exact_match"] is None
        assert row["deterministic_semantic_equivalence"] is None
        assert row["predicted_class"] is None
        assert row["missing_reason"]

    metric = _analysis_record(
        value["analysis"],
        "variant_metrics",
        split="pilot",
        cache_mode="cold",
        variant_id="A4",
    )["metrics"]
    assert metric["scheduled_count"] == 10
    assert metric["measured_count"] == 0
    assert metric["unavailable_count"] == 10
    assert metric["semantic_quality_rate"] is None
    assert metric["latency_ms_p95"] is None

    calls = _analysis_record(
        value["analysis"],
        "symai_unnecessary_calls",
        split="pilot",
        cache_mode="cold",
        variant_id="A4",
    )
    assert calls["symai_model_calls"] == 0
    assert calls["unnecessary_calls"] == 0
    assert calls["unnecessary_call_rate"] is None
    assert calls["unavailable_pair_case_ids"] == value["case_ids_by_split"][
        "pilot"
    ]


def test_measured_derivation_retains_disagreements_unique_wins_and_costs() -> None:
    analysis = frontend_report.derive_frontend_analysis(
        _measured_observations()
    )

    assert analysis["coverage"] == {
        "split_count": 2,
        "case_count": 20,
        "stratum_count": 10,
        "variant_count": 6,
        "cache_mode_count": 2,
        "expected_observation_count": 240,
        "observed_observation_count": 240,
    }
    comparison = _analysis_record(
        analysis,
        "pairwise_comparisons",
        split="pilot",
        cache_mode="cold",
        label="current_route_vs_full_spacy",
    )
    assert comparison["left_only_semantic_win_case_ids"] == ["pilot-p06"]
    assert comparison["right_only_semantic_win_case_ids"] == []
    assert comparison["disagreement_rate"] == 0.1
    assert comparison["disagreements"] == [
        {
            "case_id": "pilot-p06",
            "stratum": "legal_ir_ambiguity",
            "left_semantic_signature_sha256": hashlib.sha256(
                b"pilot-p06"
            ).hexdigest(),
            "right_semantic_signature_sha256": hashlib.sha256(
                b"pilot-p06-full-spacy-disagreement"
            ).hexdigest(),
            "left_semantically_correct": True,
            "right_semantically_correct": False,
        }
    ]

    recovered = _analysis_record(
        analysis,
        "component_unique_wins",
        split="pilot",
        cache_mode="cold",
        comparison="symai_off_vs_ambiguity_gated",
    )
    assert recovered["left_unique_win_case_ids"] == []
    assert recovered["right_unique_win_case_ids"] == ["pilot-p06"]

    regression = _analysis_record(
        analysis,
        "a0_regressions",
        split="pilot",
        cache_mode="cold",
        variant_id="A1",
    )
    assert regression["regression_case_ids"] == ["pilot-p06"]
    assert regression["unique_improvement_case_ids"] == []
    assert regression["regression_rate"] == 0.1

    gated = _analysis_record(
        analysis,
        "symai_unnecessary_calls",
        split="pilot",
        cache_mode="cold",
        variant_id="A4",
    )
    assert gated["symai_model_calls"] == 1
    assert gated["unique_win_calls"] == 1
    assert gated["unnecessary_calls"] == 0
    assert gated["unnecessary_call_rate"] == 0.0
    assert gated["causal_interpretation"] == "descriptive_overlap_only"

    always = _analysis_record(
        analysis,
        "symai_unnecessary_calls",
        split="pilot",
        cache_mode="cold",
        variant_id="A5",
    )
    assert always["symai_model_calls"] == 10
    assert always["unique_win_calls"] == 0
    assert always["unnecessary_calls"] == 10
    assert always["unnecessary_call_rate"] == 1.0
    assert always["causal_interpretation"] == "gate_efficiency_control"


def test_missing_duplicate_reordered_and_tampered_reports_fail_closed() -> None:
    value = copy.deepcopy(frontend_report.create_capability_preflight_report())
    value["observations"].pop()
    with pytest.raises(frontend_report.FrontendReportError, match="incomplete"):
        frontend_report.validate_frontend_report(value)

    value = copy.deepcopy(frontend_report.create_capability_preflight_report())
    value["observations"][-1] = copy.deepcopy(value["observations"][0])
    with pytest.raises(frontend_report.FrontendReportError, match="duplicate"):
        frontend_report.validate_frontend_report(value)

    value = copy.deepcopy(frontend_report.create_capability_preflight_report())
    value["observations"][0], value["observations"][1] = (
        value["observations"][1],
        value["observations"][0],
    )
    with pytest.raises(frontend_report.FrontendReportError, match="canonical order"):
        frontend_report.validate_frontend_report(value)

    value = copy.deepcopy(frontend_report.create_capability_preflight_report())
    value["analysis"]["coverage"]["observed_observation_count"] = 239
    _redigest(value)
    with pytest.raises(frontend_report.FrontendReportError, match="differs"):
        frontend_report.validate_frontend_report(value)

    value = copy.deepcopy(frontend_report.create_capability_preflight_report())
    value["artifact_sha256"] = "f" * 64
    with pytest.raises(frontend_report.FrontendReportError, match="digest"):
        frontend_report.validate_frontend_report(value)


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    (
        ("evidence", "wrong evidence", "evidence marker"),
        ("protocol_sha256", "a" * 64, "protocol identity"),
        ("registry_sha256", "b" * 64, "variant registry identity"),
        ("corpus_manifest_sha256", "c" * 64, "reviewed corpus identity"),
    ),
)
def test_frozen_report_identity_tampering_is_rejected(
    field: str, replacement: str, message: str
) -> None:
    value = copy.deepcopy(frontend_report.create_capability_preflight_report())
    value[field] = replacement
    _redigest(value)
    with pytest.raises(frontend_report.FrontendReportError, match=message):
        frontend_report.validate_frontend_report(value)


def test_loader_rejects_noncanonical_and_duplicate_json(tmp_path: Path) -> None:
    value = frontend_report.create_capability_preflight_report()
    noncanonical = tmp_path / "noncanonical.json"
    noncanonical.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(frontend_report.FrontendReportError, match="canonical"):
        frontend_report.load_frontend_report(noncanonical)

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"schema":"a","schema":"b"}\n', encoding="utf-8")
    with pytest.raises(frontend_report.FrontendReportError, match="strict"):
        frontend_report.load_frontend_report(duplicate)


def test_required_frontend_cli_validates_exact_checked_in_evidence() -> None:
    process = subprocess.run(
        [
            sys.executable,
            "benchmarks/logic_pipeline/report.py",
            "--section",
            "frontend",
            "--validate",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout) == {
        "artifact_sha256": ARTIFACT_SHA256,
        "execution_mode": "capability_preflight",
        "missingness_retained": True,
        "observation_count": 240,
        "section": "frontend",
        "semantic_measurement_count": 0,
        "split_count": 2,
        "status": "valid",
        "stratum_count": 10,
    }
