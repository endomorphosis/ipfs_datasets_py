"""Contracts for the immutable SRT-014 no-eligible remediation manifest."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.utils.cid_utils import cid_for_dag_json

import benchmarks.semantic_roundtrip.no_eligible_remediation as remediation_module
from benchmarks.semantic_roundtrip.no_eligible_remediation import (
    MANIFEST_INTERFACE,
    MANIFEST_RELATIVE_PATH,
    MANIFEST_SCHEMA_VERSION,
    NoEligibleRemediationError,
    build_no_eligible_remediation_manifest,
    validate_no_eligible_remediation_manifest,
    write_no_eligible_remediation_manifest,
)
from benchmarks.semantic_roundtrip_scheduler import (
    SRT014_REPORT_RELATIVE_PATH,
    evaluate_srt014_downstream_gate,
)


ROOT = Path(__file__).resolve().parents[4]
MANIFEST_PATH = ROOT / MANIFEST_RELATIVE_PATH


@pytest.fixture(scope="module")
def srt014_gate() -> dict[str, object]:
    gate = evaluate_srt014_downstream_gate(ROOT)
    assert gate["status"] == "remediation_required"
    return gate


def _use_gate(
    monkeypatch: pytest.MonkeyPatch,
    gate: dict[str, object],
) -> None:
    monkeypatch.setattr(
        remediation_module,
        "evaluate_srt014_downstream_gate",
        lambda _repo_root: copy.deepcopy(gate),
    )


def test_checked_in_manifest_exactly_regenerates_from_srt014() -> None:
    checked_in = json.loads(MANIFEST_PATH.read_bytes())
    generated = build_no_eligible_remediation_manifest(ROOT)

    assert checked_in == generated
    assert set(checked_in) == {
        "interface",
        "schema_version",
        "status",
        "source",
        "remediation",
        "protocol_immutable",
        "replacement_run_required",
        "srt015_fenced",
        "manifest_cid",
    }
    assert checked_in["interface"] == MANIFEST_INTERFACE
    assert checked_in["schema_version"] == MANIFEST_SCHEMA_VERSION
    cid_payload = dict(checked_in)
    del cid_payload["manifest_cid"]
    assert checked_in["manifest_cid"] == cid_for_dag_json(cid_payload)


def test_manifest_binds_exact_report_and_gate_lineage(
    srt014_gate: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_gate(monkeypatch, srt014_gate)
    manifest = build_no_eligible_remediation_manifest(
        ROOT,
        srt014_gate=srt014_gate,
    )

    assert manifest["source"] == {
        "srt014_report_path": str(SRT014_REPORT_RELATIVE_PATH),
        "srt014_report_cid": srt014_gate["report_cid"],
        "srt014_report_raw_cid": srt014_gate["report_raw_cid"],
        "srt014_gate_cid": srt014_gate["gate_cid"],
    }
    assert manifest["remediation"] == srt014_gate["remediation"]
    assert manifest["remediation"] is not srt014_gate["remediation"]


def test_manifest_retains_complete_failure_evidence(
    srt014_gate: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_gate(monkeypatch, srt014_gate)
    remediation = build_no_eligible_remediation_manifest(ROOT)["remediation"]
    arms = remediation["arms"]

    assert remediation["classification"] == (
        "all_preregistered_arms_failed_selection_eligibility"
    )
    assert remediation["arm_count"] == len(arms) == 30
    assert remediation["eligible_arm_count"] == 0
    assert sum(arm["coordinate_count"] for arm in arms.values()) == 670
    assert remediation["gate_evidence"] == {
        "source_copy_exclusion": {
            "affected_arm_count": 15,
            "affected_arm_ids": remediation["gate_evidence"][
                "source_copy_exclusion"
            ]["affected_arm_ids"],
            "failed_coordinate_count": 271,
        },
        "polarity_preservation": {
            "affected_arm_count": 28,
            "affected_arm_ids": remediation["gate_evidence"][
                "polarity_preservation"
            ]["affected_arm_ids"],
            "failed_coordinate_count": 579,
        },
        "full_coverage": {
            "affected_arm_count": 21,
            "affected_arm_ids": remediation["gate_evidence"][
                "full_coverage"
            ]["affected_arm_ids"],
            "failed_coordinate_count": 350,
        },
    }
    assert remediation["systemic_gate_ids"] == []
    assert remediation["component_local_gate_ids"] == [
        "source_copy_exclusion",
        "polarity_preservation",
        "full_coverage",
    ]
    assert remediation["terminal_failure_reason_counts"] == {
        "empty_l2": 85,
        "invalid_output": 5,
        "post_schedule_capability_unavailable": 260,
    }
    assert remediation["terminal_failure_stage_counts"] == {
        "unspecified_stage": 350
    }
    for arm in arms.values():
        assert set(arm["affected_case_ids_by_gate"]) == {
            "source_copy_exclusion",
            "polarity_preservation",
            "full_coverage",
        }
        assert set(arm["sample_coordinate_keys_by_gate"]) == {
            "source_copy_exclusion",
            "polarity_preservation",
            "full_coverage",
        }
        assert len(arm["failed_gate_ids"]) >= 1


def test_manifest_prescribes_only_a_new_immutable_replacement_run(
    srt014_gate: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_gate(monkeypatch, srt014_gate)
    manifest = build_no_eligible_remediation_manifest(ROOT)
    task_inputs = manifest["remediation"]["recommended_task_inputs"]

    assert manifest["status"] == "frozen_no_eligible"
    assert manifest["protocol_immutable"] is True
    assert manifest["replacement_run_required"] is True
    assert manifest["srt015_fenced"] is True
    assert manifest["remediation"]["frozen_protocol_must_not_change"] is True
    assert manifest["remediation"]["srt015_must_remain_fenced"] is True
    assert task_inputs[-1] == {
        "task_kind": "execute_replacement_full_matrix",
        "protocol_action": "preserve_frozen_protocol",
        "artifact_action": "new_immutable_run_namespace_and_report",
        "requires_all_prior_remediation_receipts": True,
    }
    assert not any(
        "mutate" in str(value).lower()
        for task_input in task_inputs
        for value in task_input.values()
    )


@pytest.mark.parametrize(
    ("path", "value"),
    (
        (("selection_outcome",), "selected"),
        (("launch_authorized",), True),
        (("remediation", "eligible_arm_count"), 1),
        (
            (
                "remediation",
                "arms",
                "typed_deontic__no_guidance__no_repair__not_applicable__deterministic",
                "failed_gate_ids",
            ),
            [],
        ),
    ),
)
def test_builder_rejects_missing_or_contradictory_gate_evidence(
    srt014_gate: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
    path: tuple[str, ...],
    value: object,
) -> None:
    contradictory = copy.deepcopy(srt014_gate)
    target: dict[str, object] = contradictory
    for key in path[:-1]:
        target = target[key]  # type: ignore[assignment]
    target[path[-1]] = value
    _use_gate(monkeypatch, contradictory)

    with pytest.raises(NoEligibleRemediationError):
        build_no_eligible_remediation_manifest(ROOT)


def test_builder_rejects_a_stale_supplied_gate(
    srt014_gate: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_gate(monkeypatch, srt014_gate)
    stale = copy.deepcopy(srt014_gate)
    stale["report_raw_cid"] = (
        "bafkreiaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    )

    with pytest.raises(
        NoEligibleRemediationError,
        match="contradicts repository evidence",
    ):
        build_no_eligible_remediation_manifest(ROOT, srt014_gate=stale)


def test_manifest_validation_rejects_tampering_even_with_a_recomputed_cid(
    srt014_gate: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_gate(monkeypatch, srt014_gate)
    forged = build_no_eligible_remediation_manifest(ROOT)
    forged["remediation"]["recommended_task_inputs"][-1][
        "protocol_action"
    ] = "mutate_srt014"
    cid_payload = dict(forged)
    del cid_payload["manifest_cid"]
    forged["manifest_cid"] = cid_for_dag_json(cid_payload)

    with pytest.raises(
        NoEligibleRemediationError,
        match="contradicts freshly recomputed",
    ):
        validate_no_eligible_remediation_manifest(
            forged,
            repo_root=ROOT,
        )


def test_writer_refuses_to_replace_a_different_frozen_manifest(
    tmp_path: Path,
    srt014_gate: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_gate(monkeypatch, srt014_gate)
    output = tmp_path / "manifest.json"
    written = write_no_eligible_remediation_manifest(
        ROOT,
        output_path=output,
    )
    original = output.read_bytes()
    value = json.loads(original)
    value["status"] = "mutable"
    output.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(NoEligibleRemediationError):
        write_no_eligible_remediation_manifest(
            ROOT,
            output_path=output,
        )
    assert output.read_text(encoding="utf-8") == json.dumps(value)
    assert written == output
