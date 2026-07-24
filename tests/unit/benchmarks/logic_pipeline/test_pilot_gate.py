"""Production contract tests for the pilot-completion shortlist gate."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from benchmarks.logic_pipeline import pilot_gate, report
from benchmarks.logic_pipeline.contracts import (
    CacheMode,
    CacheScope,
    DEFAULT_PROTOCOL,
    DEFAULT_PROTOCOL_SHA256,
    Split,
    canonical_json,
)
from benchmarks.logic_pipeline.variants import (
    ALL_VARIANT_IDS,
    VARIANT_REGISTRY,
    VARIANT_REGISTRY_SHA256,
)


ROOT = Path(__file__).resolve().parents[4]


def _sha256_json(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _redigest(value: dict[str, object]) -> dict[str, object]:
    value["artifact_sha256"] = _sha256_json(
        {
            key: item
            for key, item in value.items()
            if key != "artifact_sha256"
        }
    )
    return value


@pytest.fixture(scope="module")
def canonical_report() -> dict[str, object]:
    """Load and source-revalidate the canonical artifact once per test run."""

    return pilot_gate.load_pilot_gate_report(repository_root=ROOT)


def test_marker_proxy_and_canonical_artifact_identity(
    canonical_report: dict[str, object],
) -> None:
    marker = (
        "complete pilot outcome ledger, capability diagnosis, "
        "and deeply frozen nonbaseline shortlist"
    )

    assert pilot_gate.HSSLEV0801D68() == marker
    assert report.HSSLEV0801D68() == marker
    assert canonical_report["evidence"] == marker
    assert canonical_report["schema"] == pilot_gate.PILOT_GATE_SCHEMA
    assert canonical_report["run_id"] == pilot_gate.PILOT_GATE_RUN_ID
    assert pilot_gate.PILOT_SHORTLIST_SCHEMA == pilot_gate.PILOT_GATE_SCHEMA
    assert (
        pilot_gate.DEFAULT_PILOT_SHORTLIST_PATH
        == pilot_gate.DEFAULT_PILOT_GATE_PATH
    )


def test_ledger_has_exact_coordinates_order_and_observation_kinds(
    canonical_report: dict[str, object],
) -> None:
    ledger = canonical_report["outcome_ledger"]
    normalization = canonical_report["normalization"]
    assert isinstance(ledger, list)
    assert isinstance(normalization, dict)

    expected_coordinates = [
        (variant_id, cache_mode, case_id)
        for variant_id in ALL_VARIANT_IDS
        for cache_mode in pilot_gate.CACHE_MODES
        for case_id in pilot_gate.PILOT_CASE_IDS
    ]
    actual_coordinates = [
        (row["variant_id"], row["cache_mode"], row["case_id"])
        for row in ledger
    ]
    assert len(ledger) == 280
    assert actual_coordinates == expected_coordinates
    assert len(set(actual_coordinates)) == 280
    assert normalization == {
        "variant_ids": list(ALL_VARIANT_IDS),
        "candidate_variant_ids": list(
            pilot_gate.NONBASELINE_CANDIDATE_IDS
        ),
        "cache_modes": ["cold", "warm"],
        "pilot_case_ids": list(pilot_gate.PILOT_CASE_IDS),
        "proof_eligible_case_ids": [
            "pilot-p01",
            "pilot-p02",
            "pilot-p03",
            "pilot-p04",
            "pilot-p07",
            "pilot-p08",
            "pilot-p09",
        ],
        "proof_excluded_case_ids": [
            "pilot-p05",
            "pilot-p06",
            "pilot-p10",
        ],
        "overlap_variant_ids": ["A4", "A7", "A8"],
        "expected_cell_count": 280,
        "observed_cell_count": 280,
        "observation_kind_counts": {
            "frontend_only": 78,
            "proof_only": 112,
            "frontend_and_proof": 42,
            "excluded_nonproof": 48,
        },
        "canonical_order": ["variant_id", "cache_mode", "case_id"],
    }

    actual_kind_counts = {
        kind: sum(row["observation_kind"] == kind for row in ledger)
        for kind in (
            "frontend_only",
            "proof_only",
            "frontend_and_proof",
            "excluded_nonproof",
        )
    }
    assert actual_kind_counts == normalization["observation_kind_counts"]
    assert {row["schema"] for row in ledger} == {
        pilot_gate.PILOT_OUTCOME_CELL_SCHEMA
    }


def test_proof_exclusions_are_explicit_for_p05_p06_and_p10(
    canonical_report: dict[str, object],
) -> None:
    ledger = canonical_report["outcome_ledger"]
    assert isinstance(ledger, list)
    excluded_cases = {"pilot-p05", "pilot-p06", "pilot-p10"}
    proof_variants = {
        "A2",
        "A3",
        "A4",
        "A6",
        "A7",
        "A8",
        "A9",
        "A10",
        "A11",
        "A12",
        "S1",
    }
    overlap_variants = set(pilot_gate.OVERLAP_VARIANT_IDS)

    excluded_rows = [
        row
        for row in ledger
        if row["variant_id"] in proof_variants
        and row["case_id"] in excluded_cases
    ]
    assert len(excluded_rows) == 66
    for row in excluded_rows:
        assert row["proof_scope"] == "excluded_nonproof"
        assert not any(
            source["source"] == "proof"
            for source in row["source_observations"]
        )
        assert row["kernel_verified"] is None
        if row["variant_id"] in overlap_variants:
            assert row["observation_kind"] == "frontend_only"
        else:
            assert row["observation_kind"] == "excluded_nonproof"
            assert row["evidence_status"] == "excluded_nonproof"
            assert row["efficacy_observed"] is False
            assert row["missing_reasons"] == [
                "case is outside the frozen proof-eligible scope; no proof "
                "efficacy observation was synthesized"
            ]


def test_invalid_control_has_zero_false_positives_and_null_efficacy(
    canonical_report: dict[str, object],
) -> None:
    ledger = canonical_report["outcome_ledger"]
    safety = canonical_report["safety"]
    assert isinstance(ledger, list)
    invalid_rows = [row for row in ledger if row["invalid_control"] is True]

    assert len(invalid_rows) == 28
    assert {row["case_id"] for row in invalid_rows} == {"pilot-p10"}
    assert all(
        row["invalid_control_kernel_false_positive"] is None
        for row in invalid_rows
    )
    assert all(row["efficacy_observed"] is False for row in invalid_rows)
    assert safety == {
        "invalid_control_case_ids": ["pilot-p10"],
        "invalid_control_cell_count": 28,
        "observed_invalid_control_cell_count": 0,
        "kernel_verified_invalid_control_false_positive_count": 0,
        "kernel_verified_invalid_control_false_positive_rate": None,
        "threshold": 0,
        "fatal_safety_incident": False,
        "efficacy_observation_count": 0,
        "infrastructure_failure_count": 0,
        "absence_is_not_negative_efficacy": True,
    }


def test_source_bindings_and_deep_freeze_are_content_addressed(
    canonical_report: dict[str, object],
) -> None:
    bindings = canonical_report["source_bindings"]
    deep_freeze = canonical_report["deep_freeze"]
    assert isinstance(bindings, list)
    assert isinstance(deep_freeze, dict)

    assert [(item["kind"], item["path"]) for item in bindings] == [
        ("frontend_overlap_report", pilot_gate.FRONTEND_SOURCE_PATH.as_posix()),
        ("proof_overlap_report", pilot_gate.PROOF_SOURCE_PATH.as_posix()),
        ("frozen_a0_manifest", pilot_gate.BASELINE_SOURCE_PATH.as_posix()),
    ]
    for binding in bindings:
        source_path = ROOT / str(binding["path"])
        assert binding["content_sha256"] == hashlib.sha256(
            source_path.read_bytes()
        ).hexdigest()
        source = json.loads(source_path.read_text(encoding="utf-8"))
        semantic_sha256 = source.get("artifact_sha256") or _sha256_json(source)
        assert binding["semantic_sha256"] == semantic_sha256
        assert binding["schema"] == source["schema"]

    assert deep_freeze["schema"] == pilot_gate.PILOT_FREEZE_SCHEMA
    assert deep_freeze["frozen"] is True
    assert deep_freeze["tuning_permitted"] is False
    assert deep_freeze["protocol"] == {
        "sha256": DEFAULT_PROTOCOL_SHA256,
        "snapshot": DEFAULT_PROTOCOL.to_dict(),
    }
    registry = deep_freeze["registry"]
    assert registry["sha256"] == VARIANT_REGISTRY_SHA256
    assert [
        item["variant_id"] for item in registry["variant_configurations"]
    ] == list(ALL_VARIANT_IDS)
    for item in registry["variant_configurations"]:
        variant = VARIANT_REGISTRY[item["variant_id"]]
        assert item["configuration_sha256"] == variant.digest
        assert item["configuration"] == variant.to_dict()

    assert deep_freeze["source_semantic_bindings"] == [
        {
            "kind": item["kind"],
            "path": item["path"],
            "semantic_sha256": item["semantic_sha256"],
        }
        for item in bindings
    ]
    assert deep_freeze["selection_basis"] == {
        "allowed_splits": ["pilot", "development"],
        "holdout_outcomes_permitted": False,
        "post_freeze_reranking_permitted": False,
        "arbitrary_ranking_or_truncation_permitted": False,
    }
    for key in (
        "prompts",
        "cache_policy",
        "resource_policy",
        "policies",
        "model_identities",
        "thresholds",
    ):
        assert deep_freeze[key]["frozen"] is True
        assert len(deep_freeze[key]["sha256"]) == 64
    assert deep_freeze["prompts"]["observed_model_call_count"] == 0
    assert deep_freeze["prompts"]["materialized_prompt_sha256s"] == []
    assert deep_freeze["prompts"]["contracts_sha256"] == _sha256_json(
        deep_freeze["prompts"]["contracts"]
    )
    assert deep_freeze["cache_policy"]["cold_warm_results_separate"] is True
    assert deep_freeze["cache_policy"]["cross_variant_reuse_forbidden"] is True
    assert deep_freeze["cache_policy"]["namespace_dimensions"] == [
        "run_id",
        "protocol_sha256",
        "variant_id",
        "split",
        "cache_mode",
    ]
    expected_reserved_namespaces = [
        CacheScope(
            pilot_gate.PILOT_GATE_RUN_ID,
            DEFAULT_PROTOCOL_SHA256,
            variant_id,
            split,
            cache_mode,
        ).namespace
        for split in (Split.PILOT, Split.DEVELOPMENT)
        for variant_id in ALL_VARIANT_IDS
        for cache_mode in (CacheMode.COLD, CacheMode.WARM)
    ]
    assert len(expected_reserved_namespaces) == 56
    assert (
        deep_freeze["cache_policy"]["reserved_unopened_namespaces"]
        == expected_reserved_namespaces
    )
    assert len(set(expected_reserved_namespaces)) == 56
    assert deep_freeze["cache_policy"][
        "execution_claimed_for_reserved_namespaces"
    ] is False
    assert deep_freeze["resource_policy"][
        "model_and_kernel_lanes_distinct"
    ] is True
    assert deep_freeze["resource_policy"]["execution_claimed"] is False
    assert deep_freeze["resource_policy"]["resource_lanes"] == [
        "cpu",
        "model",
        "solver",
        "kernel",
        "validation",
    ]
    assert deep_freeze["thresholds"]["values"] == (
        DEFAULT_PROTOCOL.thresholds.to_dict()
    )
    for key in ("prompts", "cache_policy", "resource_policy"):
        body = dict(deep_freeze[key])
        body.pop("frozen")
        digest = body.pop("sha256")
        assert digest == _sha256_json(body)
    assert deep_freeze["policies"]["sha256"] == _sha256_json(
        deep_freeze["policies"]["values"]
    )
    model_identity_body = dict(deep_freeze["model_identities"])
    model_identity_body.pop("frozen")
    model_identity_digest = model_identity_body.pop("sha256")
    assert model_identity_digest == _sha256_json(model_identity_body)
    assert deep_freeze["thresholds"]["sha256"] == _sha256_json(
        deep_freeze["thresholds"]["values"]
    )

    freeze_body = {
        "protocol_sha256": deep_freeze["protocol"]["sha256"],
        "registry_sha256": deep_freeze["registry"]["sha256"],
        "variant_configuration_sha256s": [
            item["configuration_sha256"]
            for item in registry["variant_configurations"]
        ],
        "prompt_sha256": deep_freeze["prompts"]["sha256"],
        "cache_policy_sha256": deep_freeze["cache_policy"]["sha256"],
        "resource_policy_sha256": deep_freeze["resource_policy"]["sha256"],
        "policy_sha256": deep_freeze["policies"]["sha256"],
        "model_identity_sha256": deep_freeze["model_identities"]["sha256"],
        "threshold_sha256": deep_freeze["thresholds"]["sha256"],
        "sources": deep_freeze["source_semantic_bindings"],
    }
    assert deep_freeze["freeze_sha256"] == _sha256_json(freeze_body)


def test_dispositions_empty_shortlist_incomplete_decision_and_closed_holdout(
    canonical_report: dict[str, object],
) -> None:
    dispositions = canonical_report["variant_dispositions"]
    assert isinstance(dispositions, list)
    assert [item["variant_id"] for item in dispositions] == list(
        pilot_gate.NONBASELINE_CANDIDATE_IDS
    )
    assert len(dispositions) == 12
    assert all(item["pilot_cell_count"] == 20 for item in dispositions)
    assert all(
        item["pilot_efficacy_observation_count"] == 0
        and item["development_efficacy_observation_count"] == 0
        and item["selection_eligible"] is False
        and item["disposition"] == "not_selected"
        and item["efficacy_rates"]
        == {
            "kernel_verified_rate": None,
            "semantic_success_rate": None,
            "paired_delta_vs_a0": None,
        }
        for item in dispositions
    )
    assert all(
        item["reasons"][:2]
        == [
            "no_pilot_efficacy_observed",
            "no_development_efficacy_observed",
        ]
        for item in dispositions
    )

    assert canonical_report["shortlist"] == {
        "status": "incomplete",
        "frozen": True,
        "freeze_kind": "empty_due_to_unavailable_evidence",
        "candidate_max": 4,
        "selected_variant_ids": [],
        "selected_count": 0,
        "nonbaseline_only": True,
        "diagnostic_arms_excluded": ["S1"],
        "baseline_arms_excluded": ["A0"],
        "selection_splits": ["pilot", "development"],
        "ranking_applied": False,
        "truncation_applied": False,
        "reason": (
            "capability-preflight evidence contains no observed efficacy; "
            "no arm may be ranked or selected"
        ),
    }
    assert canonical_report["decision"] == {
        "status": "incomplete",
        "structurally_valid": True,
        "pilot_protocol_status": "capability_preflight_complete",
        "efficacy_status": "unavailable",
        "shortlist_status": "frozen_empty",
        "holdout_authorized": False,
        "production_promotion_authorized": False,
        "reason": (
            "pilot and development source matrices are structurally "
            "validated, but required efficacy was unavailable"
        ),
    }
    assert canonical_report["holdout"] == {
        "status": "unopened",
        "authorized": False,
        "outcomes_inspected": False,
        "access_log_ids": [],
        "selection_used_holdout": False,
        "tuning_after_access": False,
        "reason": "an incomplete empty shortlist cannot authorize holdout access",
    }


def _mutate_redigested_report(
    value: dict[str, object], case: str
) -> dict[str, object]:
    ledger = value["outcome_ledger"]
    shortlist = value["shortlist"]
    assert isinstance(ledger, list)
    assert isinstance(shortlist, dict)
    if case == "ledger removal":
        ledger.pop()
    elif case == "ledger reorder":
        ledger[0], ledger[1] = ledger[1], ledger[0]
    elif case == "candidate injection":
        shortlist["selected_variant_ids"] = ["A1"]
        shortlist["selected_count"] = 1
    elif case == "S1 injection":
        shortlist["selected_variant_ids"] = ["S1"]
        shortlist["selected_count"] = 1
    elif case == "shortlist overflow":
        shortlist["selected_variant_ids"] = ["A1", "A2", "A3", "A4", "A5"]
        shortlist["selected_count"] = 5
    elif case == "source binding edit":
        value["source_bindings"][0]["semantic_sha256"] = "0" * 64
    elif case == "deep-freeze edit":
        value["deep_freeze"]["thresholds"]["frozen"] = False
    elif case == "holdout edit":
        value["holdout"]["authorized"] = True
    elif case == "safety edit":
        value["safety"][
            "kernel_verified_invalid_control_false_positive_count"
        ] = 1
    else:  # pragma: no cover - parametrization is intentionally exhaustive.
        raise AssertionError(f"unknown tamper case: {case}")
    return _redigest(value)


@pytest.mark.parametrize(
    "case",
    [
        "ledger removal",
        "ledger reorder",
        "candidate injection",
        "S1 injection",
        "shortlist overflow",
        "source binding edit",
        "deep-freeze edit",
        "holdout edit",
        "safety edit",
    ],
)
def test_strict_recomputation_rejects_redigested_tampering(
    canonical_report: dict[str, object],
    case: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Reuse the already source-revalidated canonical derivation.  This keeps
    # the tamper matrix fast while preserving the validator's exact
    # recomputation-and-comparison boundary.
    expected = copy.deepcopy(canonical_report)
    monkeypatch.setattr(
        pilot_gate,
        "_derive_report",
        lambda _root: copy.deepcopy(expected),
    )
    forged = _mutate_redigested_report(copy.deepcopy(canonical_report), case)

    with pytest.raises(
        pilot_gate.PilotGateError,
        match="differs from recomputed allowlisted source evidence",
    ):
        pilot_gate.validate_pilot_gate_report(forged, repository_root=ROOT)


def test_validator_rejects_digest_and_top_level_contract_tampering(
    canonical_report: dict[str, object],
) -> None:
    forged = copy.deepcopy(canonical_report)
    forged["artifact_sha256"] = "f" * 64
    with pytest.raises(pilot_gate.PilotGateError, match="artifact digest"):
        pilot_gate.validate_pilot_gate_report(forged, repository_root=ROOT)

    forged = copy.deepcopy(canonical_report)
    forged["invented"] = True
    with pytest.raises(pilot_gate.PilotGateError, match="keys changed"):
        pilot_gate.validate_pilot_gate_report(forged, repository_root=ROOT)


def test_loader_accepts_canonical_and_rejects_duplicate_or_noncanonical_json(
    canonical_report: dict[str, object],
    tmp_path: Path,
) -> None:
    canonical = tmp_path / "canonical.json"
    canonical.write_text(
        canonical_json(canonical_report) + "\n", encoding="utf-8"
    )
    assert pilot_gate.load_pilot_gate_report(
        canonical, repository_root=ROOT
    ) == canonical_report

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(
        '{"schema":"first","schema":"second"}\n', encoding="utf-8"
    )
    with pytest.raises(pilot_gate.PilotGateError, match="strict JSON"):
        pilot_gate.load_pilot_gate_report(duplicate, repository_root=ROOT)

    noncanonical = tmp_path / "noncanonical.json"
    noncanonical.write_text(
        json.dumps(canonical_report, indent=2) + "\n", encoding="utf-8"
    )
    with pytest.raises(pilot_gate.PilotGateError, match="canonical JSON"):
        pilot_gate.load_pilot_gate_report(noncanonical, repository_root=ROOT)


def test_writer_is_canonical_atomic_and_refuses_overwrite(
    canonical_report: dict[str, object],
    tmp_path: Path,
) -> None:
    destination = tmp_path / "nested" / "pilot.json"
    assert pilot_gate.write_pilot_gate_report(
        canonical_report,
        destination,
        repository_root=ROOT,
    ) == destination
    assert destination.read_text(encoding="utf-8") == (
        canonical_json(canonical_report) + "\n"
    )

    with pytest.raises(pilot_gate.PilotGateError, match="refusing to overwrite"):
        pilot_gate.write_pilot_gate_report(
            canonical_report,
            destination,
            repository_root=ROOT,
        )

    assert pilot_gate.write_pilot_shortlist_report(
        canonical_report,
        destination,
        repository_root=ROOT,
        overwrite=True,
    ) == destination


def test_source_path_resolution_is_strictly_allowlisted() -> None:
    assert pilot_gate.ALLOWED_SOURCE_PATHS == frozenset(
        {
            pilot_gate.FRONTEND_SOURCE_PATH.as_posix(),
            pilot_gate.PROOF_SOURCE_PATH.as_posix(),
            pilot_gate.BASELINE_SOURCE_PATH.as_posix(),
        }
    )
    for relative_path in pilot_gate.ALLOWED_SOURCE_PATHS:
        resolved = pilot_gate._resolve_allowlisted_source(ROOT, relative_path)
        assert resolved == (ROOT / relative_path).resolve()
        assert resolved.is_file()

    for forbidden in (
        "../frontend-overlap-v1.json",
        "/tmp/frontend-overlap-v1.json",
        pilot_gate.FRONTEND_SOURCE_PATH.as_posix() + ".bak",
        ".",
    ):
        with pytest.raises(
            pilot_gate.PilotGateError, match="not allowlisted"
        ):
            pilot_gate._resolve_allowlisted_source(ROOT, forbidden)


def test_performance_snapshot_matches_the_canonical_gate(
    canonical_report: dict[str, object],
) -> None:
    snapshot = json.loads(
        (
            ROOT
            / "docs/performance_snapshots/2026-07-24_pilot_shortlist.json"
        ).read_text(encoding="utf-8")
    )["results"]
    normalization = canonical_report["normalization"]
    safety = canonical_report["safety"]
    shortlist = canonical_report["shortlist"]
    decision = canonical_report["decision"]
    deep_freeze = canonical_report["deep_freeze"]

    assert snapshot["artifact"] == {
        "path": pilot_gate.DEFAULT_PILOT_GATE_PATH.as_posix(),
        "sha256": canonical_report["artifact_sha256"],
        "decision": decision["status"],
        "structurally_valid": decision["structurally_valid"],
    }
    assert snapshot["scope"] == {
        "variant_count": len(normalization["variant_ids"]),
        "pilot_case_count": len(normalization["pilot_case_ids"]),
        "cache_mode_count": len(normalization["cache_modes"]),
        "expected_outcome_cells": normalization["expected_cell_count"],
        "retained_outcome_cells": normalization["observed_cell_count"],
        "observation_kind_counts": normalization["observation_kind_counts"],
        "proof_excluded_case_ids": normalization[
            "proof_excluded_case_ids"
        ],
        "selection_splits": shortlist["selection_splits"],
        "holdout_outcomes_used": canonical_report["holdout"][
            "selection_used_holdout"
        ],
    }
    safety_fields = (
        "invalid_control_case_ids",
        "invalid_control_cell_count",
        "observed_invalid_control_cell_count",
        "kernel_verified_invalid_control_false_positive_count",
        "kernel_verified_invalid_control_false_positive_rate",
        "fatal_safety_incident",
        "infrastructure_failure_count",
        "efficacy_observation_count",
    )
    assert snapshot["safety"] == {
        field: safety[field] for field in safety_fields
    }
    assert snapshot["freeze"] == {
        "sha256": deep_freeze["freeze_sha256"],
        "protocol_sha256": deep_freeze["protocol"]["sha256"],
        "variant_registry_sha256": deep_freeze["registry"]["sha256"],
        "prompts_sha256": deep_freeze["prompts"]["sha256"],
        "policies_sha256": deep_freeze["policies"]["sha256"],
        "model_identities_sha256": deep_freeze["model_identities"]["sha256"],
        "cache_policy_sha256": deep_freeze["cache_policy"]["sha256"],
        "resource_policy_sha256": deep_freeze["resource_policy"]["sha256"],
        "thresholds_sha256": deep_freeze["thresholds"]["sha256"],
        "tuning_permitted": deep_freeze["tuning_permitted"],
    }


def _run_report_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "benchmarks/logic_pipeline/report.py",
            *arguments,
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_pilot_gate_cli_emits_the_exact_stable_summary(
    canonical_report: dict[str, object],
) -> None:
    process = _run_report_cli("--gate", "pilot-shortlist")

    assert process.returncode == 0, process.stderr
    assert process.stderr == ""
    assert json.loads(process.stdout) == {
        "section": "pilot-shortlist",
        "status": "incomplete",
        "structurally_valid": True,
        "artifact_sha256": canonical_report["artifact_sha256"],
        "outcome_cell_count": 280,
        "pilot_case_count": 10,
        "variant_count": 14,
        "efficacy_observation_count": 0,
        "kernel_verified_invalid_control_false_positive_count": 0,
        "kernel_verified_invalid_control_false_positive_rate": None,
        "selected_variant_ids": [],
        "shortlist_frozen": True,
        "holdout_authorized": False,
        "missingness_retained": True,
    }


@pytest.mark.parametrize(
    ("section", "expected_count_key", "expected_count"),
    [
        ("frontend", "observation_count", 240),
        ("proof", "observation_count", 154),
    ],
)
def test_legacy_report_validation_clis_remain_accepted(
    section: str,
    expected_count_key: str,
    expected_count: int,
) -> None:
    process = _run_report_cli("--section", section, "--validate")

    assert process.returncode == 0, process.stderr
    summary = json.loads(process.stdout)
    assert summary["section"] == section
    assert summary["status"] == "valid"
    assert summary[expected_count_key] == expected_count


def _measured_gate_sources(
    *,
    frontier: list[str] | None = None,
    candidate_ids: list[str] | None = None,
    missing_cost: bool = False,
    invalid_control_verified: bool = False,
) -> dict[str, dict[str, object]]:
    run_id = "measured-pilot-test"
    candidates = candidate_ids or ["A1", "A2"]
    selected = frontier if frontier is not None else ["A1"]
    baseline_receipt = hashlib.sha256(b"case-A0").hexdigest()
    candidate_receipts = {
        candidate_id: hashlib.sha256(
            f"case-{candidate_id}".encode()
        ).hexdigest()
        for candidate_id in candidates
    }

    frontend = {
        "schema": "frontend-test.v1",
        "run_id": run_id,
        "execution_mode": "measured",
        "protocol_sha256": DEFAULT_PROTOCOL_SHA256,
        "registry_sha256": VARIANT_REGISTRY_SHA256,
        "observations": [
            {
                "status": "semantically_correct",
                "source_receipt_sha256": baseline_receipt,
            }
        ],
        "analysis": {
            "coverage": {
                "expected_observation_count": 240,
                "observed_observation_count": 240,
            },
            "variant_metrics": [
                {
                    "metrics": {
                        "semantic_quality_rate": 0.9,
                        "latency_ms_p95": 10.0,
                        "model_calls": 1,
                        "symai_model_calls": 1,
                    }
                }
            ],
        },
        "artifact_sha256": hashlib.sha256(b"frontend-test").hexdigest(),
    }
    proof = {
        "schema": "proof-test.v1",
        "run_id": run_id,
        "execution_mode": "measured",
        "protocol_sha256": DEFAULT_PROTOCOL_SHA256,
        "registry_sha256": VARIANT_REGISTRY_SHA256,
        "observations": [
            {
                "status": "verified",
                "source_receipt_sha256": candidate_receipts[candidates[0]],
            }
        ],
        "analysis": {
            "coverage": {
                "expected_observation_count": 154,
                "observed_observation_count": 154,
            },
            "primary_metrics": [
                {
                    "kernel_verified_rate": 0.8,
                    "mean_wall_time_ms": 12.0,
                    "model_calls": 1,
                }
            ],
        },
        "artifact_sha256": hashlib.sha256(b"proof-test").hexdigest(),
    }
    cost = {
        "model_calls": 2,
        "solver_processes": None if missing_cost else 1,
        "accelerator_minutes": 0.25,
        "retries": 0,
        "operational_components": 2,
    }
    efficiency = {
        "schema": "efficiency-test.v1",
        "execution_mode": "measured",
        "protocol_sha256": DEFAULT_PROTOCOL_SHA256,
        "observations": [
            {
                "invalid_control": True,
                "case_result_sha256": baseline_receipt,
                "case_result": {
                    "status": (
                        "verified"
                        if invalid_control_verified
                        else "rejected"
                    ),
                    "kernel_receipt_sha256": (
                        hashlib.sha256(
                            b"invalid-kernel-receipt"
                        ).hexdigest()
                        if invalid_control_verified
                        else None
                    ),
                },
            },
            *[
                {
                    "invalid_control": False,
                    "case_result_sha256": receipt,
                    "case_result": {
                        "status": "verified",
                        "kernel_receipt_sha256": hashlib.sha256(
                            f"kernel-{candidate_id}".encode()
                        ).hexdigest(),
                    },
                }
                for candidate_id, receipt in candidate_receipts.items()
            ],
        ],
        "analysis": {
            "measured": True,
            "case_count": 20,
            "run_id": run_id,
            "pareto_points": [
                {
                    "variant_id": candidate_id,
                    "eligible": not missing_cost,
                    "kernel_verified_rate": 0.8,
                    "costs": dict(cost),
                    "unnecessary_call_rate": 0.1,
                    "failed_attempts": 0,
                }
                for candidate_id in candidates
            ],
        },
        "artifact_sha256": hashlib.sha256(b"efficiency-test").hexdigest(),
    }
    statistics_report = {
        "schema": "statistics-test.v1",
        "protocol_sha256": DEFAULT_PROTOCOL_SHA256,
        "analyses": [
            {"split": "pilot", "measured_count": 10, "missing_count": 0},
            {
                "split": "development",
                "measured_count": 10,
                "missing_count": 0,
            },
        ],
        "requests": [
            {
                "observations": [
                    {
                        "run_id": run_id,
                        "baseline_result_sha256": baseline_receipt,
                        "candidate_result_sha256": candidate_receipts[
                            candidate_id
                        ],
                    }
                ]
            }
            for candidate_id in candidates
        ],
        "pareto": {
            "frontier_candidate_ids": selected,
            "candidates": [
                {
                    "candidate_id": candidate_id,
                    "eligible": True,
                    "on_frontier": candidate_id in selected,
                    "dominated_by": (
                        [] if candidate_id in selected else [selected[0]]
                    ),
                    "metrics": {
                        "quality": 0.8,
                        "latency": 12.0,
                        "resource": 2.0,
                        "routing": 0.1,
                        "complexity": 2.0,
                    },
                    "analysis_sha256s": [
                        hashlib.sha256(
                            f"analysis-{candidate_id}".encode()
                        ).hexdigest()
                    ],
                    "case_result_sha256s": [
                        baseline_receipt,
                        candidate_receipts[candidate_id],
                    ],
                    "safety_feasible": True,
                }
                for candidate_id in candidates
            ],
        },
        "artifact_sha256": hashlib.sha256(b"statistics-test").hexdigest(),
    }
    return {
        "frontend": frontend,
        "proof": proof,
        "efficiency": efficiency,
        "statistics": statistics_report,
    }


def _measured_gate_inputs(
    sources: dict[str, dict[str, object]],
) -> tuple[dict[str, object], dict[str, object]]:
    bindings = {
        kind: source["artifact_sha256"] for kind, source in sources.items()
    }
    freeze_inputs = {
        "prompts": {"prompt_sha256s": ["1" * 64]},
        "policies": {"policy": "frozen"},
        "model_identities": {"model": "pinned-model@revision"},
        "cache_policy": {"cold_warm_separate": True},
        "resource_policy": {"lanes": ["model", "kernel"]},
        "thresholds": DEFAULT_PROTOCOL.thresholds.to_dict(),
    }
    return bindings, freeze_inputs


def _build_synthetic_measured_gate(
    monkeypatch: pytest.MonkeyPatch,
    sources: dict[str, dict[str, object]],
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    monkeypatch.setattr(
        pilot_gate,
        "_measured_source_reports",
        lambda *_args: copy.deepcopy(sources),
    )
    bindings, freeze_inputs = _measured_gate_inputs(sources)
    value = pilot_gate.build_measured_pilot_gate_report(
        sources["frontend"],
        sources["proof"],
        sources["efficiency"],
        sources["statistics"],
        source_bindings=bindings,
        freeze_inputs=freeze_inputs,
    )
    return value, bindings, freeze_inputs


def test_measured_gate_authorizes_exact_nondominated_frontier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = _measured_gate_sources(frontier=["A1"])
    value, bindings, freeze_inputs = _build_synthetic_measured_gate(
        monkeypatch, sources
    )

    assert pilot_gate.HSSLEV1159F06() == report.HSSLEV1159F06()
    assert value["evidence"] == pilot_gate.HSSLEV1159F06()
    assert value["schema"] == pilot_gate.MEASURED_PILOT_GATE_SCHEMA
    assert value["completeness"]["complete"] is True
    assert value["shortlist"]["frontier_variant_ids"] == ["A1"]
    assert value["shortlist"]["selected_variant_ids"] == ["A1"]
    assert value["shortlist"]["ranking_applied"] is False
    assert value["shortlist"]["truncation_applied"] is False
    assert value["holdout"]["authorized"] is True
    assert len(value["holdout"]["authorization_sha256"]) == 64
    assert value["decision"]["status"] == "complete"
    assert value["decision"]["production_promotion_authorized"] is False
    assert [
        row["variant_id"]
        for row in value["deep_freeze"]["registry"][
            "selected_configurations"
        ]
    ] == ["A1"]
    assert pilot_gate.validate_measured_pilot_gate_report(
        value,
        sources["frontend"],
        sources["proof"],
        sources["efficiency"],
        sources["statistics"],
        source_bindings=bindings,
        freeze_inputs=freeze_inputs,
    ) == value


def test_measured_gate_retains_null_cost_as_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, _, _ = _build_synthetic_measured_gate(
        monkeypatch, _measured_gate_sources(missing_cost=True)
    )

    assert value["decision"]["status"] == "incomplete"
    assert value["holdout"]["authorized"] is False
    assert value["shortlist"]["selected_variant_ids"] == []
    assert any(
        reason.startswith("efficiency_metric_missing:A1:")
        for reason in value["shortlist"]["reasons"]
    )
    assert value["candidate_evidence"][0]["efficiency"]["costs"][
        "solver_processes"
    ] is None


def test_measured_gate_invalid_control_forces_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, _, _ = _build_synthetic_measured_gate(
        monkeypatch,
        _measured_gate_sources(invalid_control_verified=True),
    )

    assert value["safety"][
        "kernel_verified_invalid_control_false_positive_count"
    ] == 1
    assert value["safety"]["fatal_safety_incident"] is True
    assert value["decision"]["status"] == "rejected"
    assert value["shortlist"]["selected_variant_ids"] == []
    assert value["holdout"]["authorized"] is False


def test_measured_gate_cannot_treat_absent_invalid_controls_as_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = _measured_gate_sources()
    sources["efficiency"]["observations"] = [
        row
        for row in sources["efficiency"]["observations"]
        if row["invalid_control"] is not True
    ]
    value, _, _ = _build_synthetic_measured_gate(monkeypatch, sources)

    assert value["safety"]["observed_invalid_control_count"] == 0
    assert value["safety"][
        "kernel_verified_invalid_control_false_positive_rate"
    ] is None
    assert value["completeness"]["complete"] is False
    assert "invalid_control_safety_evidence_missing" in value["shortlist"][
        "reasons"
    ]
    assert value["decision"]["status"] == "incomplete"
    assert value["holdout"]["authorized"] is False


def test_measured_gate_never_truncates_an_oversized_frontier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frontier = ["A1", "A2", "A3", "A4", "A5"]
    value, _, _ = _build_synthetic_measured_gate(
        monkeypatch,
        _measured_gate_sources(
            frontier=frontier,
            candidate_ids=frontier,
        ),
    )

    assert value["shortlist"]["frontier_variant_ids"] == frontier
    assert value["shortlist"]["selected_variant_ids"] == []
    assert value["shortlist"]["truncation_applied"] is False
    assert "nondominated_frontier_exceeds_shortlist_max" in value[
        "shortlist"
    ]["reasons"]
    assert value["holdout"]["authorized"] is False


def test_measured_gate_requires_exact_source_and_freeze_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = _measured_gate_sources()
    monkeypatch.setattr(
        pilot_gate,
        "_measured_source_reports",
        lambda *_args: copy.deepcopy(sources),
    )
    bindings, freeze_inputs = _measured_gate_inputs(sources)
    bindings["statistics"] = "0" * 64
    with pytest.raises(pilot_gate.PilotGateError, match="statistics source"):
        pilot_gate.build_measured_pilot_gate_report(
            sources["frontend"],
            sources["proof"],
            sources["efficiency"],
            sources["statistics"],
            source_bindings=bindings,
            freeze_inputs=freeze_inputs,
        )

    bindings, freeze_inputs = _measured_gate_inputs(sources)
    freeze_inputs["thresholds"] = {"shortlist_candidate_max": 99}
    with pytest.raises(pilot_gate.PilotGateError, match="thresholds differ"):
        pilot_gate.build_measured_pilot_gate_report(
            sources["frontend"],
            sources["proof"],
            sources["efficiency"],
            sources["statistics"],
            source_bindings=bindings,
            freeze_inputs=freeze_inputs,
        )


def test_measured_gate_rejects_cross_run_statistics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = _measured_gate_sources()
    sources["statistics"]["requests"][0]["observations"][0][
        "run_id"
    ] = "different-run"
    monkeypatch.setattr(
        pilot_gate,
        "_measured_source_reports",
        lambda *_args: copy.deepcopy(sources),
    )
    bindings, freeze_inputs = _measured_gate_inputs(sources)

    with pytest.raises(pilot_gate.PilotGateError, match="statistics observations"):
        pilot_gate.build_measured_pilot_gate_report(
            sources["frontend"],
            sources["proof"],
            sources["efficiency"],
            sources["statistics"],
            source_bindings=bindings,
            freeze_inputs=freeze_inputs,
        )
