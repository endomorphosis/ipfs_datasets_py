"""Focused contracts for semantic round-trip dynamic scheduling."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import benchmarks.bench_semantic_roundtrip_compositions as composition_report
import benchmarks.semantic_roundtrip_scheduler as scheduler_module
from benchmarks.semantic_roundtrip_scheduler import (
    CANONICAL_DESIGN_GATE_ARTIFACT_RELATIVE_PATH,
    CANONICAL_DESIGN_GATE_ARTIFACT_VALIDATION_SCHEMA,
    CANONICAL_DESIGN_GATE_SCHEMA,
    DEFAULT_CONFIG_PATH,
    NO_ELIGIBLE_REMEDIATION_MANIFEST_INTERFACE,
    NO_ELIGIBLE_REMEDIATION_MANIFEST_GATE_SCHEMA,
    NO_ELIGIBLE_REMEDIATION_MANIFEST_RELATIVE_PATH,
    NO_ELIGIBLE_REMEDIATION_MANIFEST_SCHEMA,
    REPLACEMENT_REPORT_RELATIVE_PATH,
    REPLACEMENT_SELECTION_GATE_SCHEMA,
    SRT014_DOWNSTREAM_GATE_SCHEMA,
    SRT014_REPORT_RELATIVE_PATH,
    SchedulerPreparationError,
    build_bundle_supervisor_command,
    build_taskboard_bundle_index,
    evaluate_canonical_design_gate,
    evaluate_canonical_design_gate_artifact,
    evaluate_no_eligible_remediation_manifest_gate,
    evaluate_replacement_selection_gate,
    evaluate_srt014_downstream_gate,
    load_scheduler_config,
    probe_provider_capacity,
    validate_taskboard_for_dynamic_scheduler,
)
from ipfs_datasets_py.utils.cid_utils import (
    cid_for_bytes,
    cid_for_dag_json,
    validate_cid,
)
from ipfs_accelerate_py.agent_supervisor.artifact_store import (
    read_bundle_index_artifact,
)
from ipfs_accelerate_py.agent_supervisor.resource_scheduler import (
    HostResourceSnapshot,
    LaneResourceRequirements,
    PROOF_RESOURCE_CLASSES,
    ResourcePolicy,
    ResourceScheduler,
)
from ipfs_accelerate_py.agent_supervisor.objective_graph import (
    build_bundle_task_payloads,
)
from ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon import (
    parse_task_file,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
TASKBOARD = (
    REPO_ROOT
    / "docs"
    / "implementation"
    / "plans"
    / "semantic_roundtrip_compiler.taskboard.todo.md"
)


def test_current_board_compiles_to_one_queryable_bundle_per_task(
    tmp_path: Path,
) -> None:
    config = load_scheduler_config(DEFAULT_CONFIG_PATH)
    index_path = tmp_path / "bundles" / "index.json"

    expected = build_taskboard_bundle_index(
        repo_root=REPO_ROOT,
        taskboard_path=TASKBOARD,
        bundle_index_path=index_path,
        task_prefix=config["task_prefix"],
        provider_id=config["provider"]["provider_id"],
    )
    stored = read_bundle_index_artifact(index_path)

    assert len(expected["bundles"]) == 27
    assert len(stored["bundles"]) == 27
    assert expected["source_todo_raw_cid"] == cid_for_bytes(TASKBOARD.read_bytes())
    assert (
        validate_cid(expected["source_todo_raw_cid"], codecs=("raw",))
        == expected["source_todo_raw_cid"]
    )
    assert index_path.with_suffix(".duckdb").is_file()
    assert all(
        bundle["shard_path"]
        == "docs/implementation/plans/semantic_roundtrip_compiler.taskboard.todo.md"
        for bundle in stored["bundles"].values()
    )

    model_tasks = [
        task
        for bundle in stored["bundles"].values()
        for task in bundle["tasks"]
        if task["resource_class"] == "llm-proof-draft"
    ]
    assert model_tasks
    assert all(task["resource_stage"] == "inference" for task in model_tasks)
    assert all(task["provider_id"] == "leanstral-local" for task in model_tasks)
    assert all(task["requires_provider"] is True for task in model_tasks)
    tasks_by_id = {
        task["task_id"]: task
        for bundle in stored["bundles"].values()
        for task in bundle["tasks"]
    }
    assert tasks_by_id["SRT-002"]["dependency_task_cids"] == [
        tasks_by_id["SRT-001"]["canonical_task_cid"]
    ]
    assert tasks_by_id["SRT-003"]["dependency_task_cids"] == [
        tasks_by_id["SRT-002"]["canonical_task_cid"]
    ]
    assert stored["task_dependency_graph"]["edges"]
    assert stored["srt014_downstream_gate"]["status"] == "pending"
    assert stored["srt014_downstream_gate"]["launch_authorized"] is False
    assert stored["replacement_selection_gate"]["status"] == "pending"
    assert stored["canonical_design_gate"]["launch_authorized"] is False
    for task_id in ("SRT-015", "SRT-016", "SRT-017", "SRT-018", "SRT-019"):
        assert tasks_by_id[task_id]["is_schedulable"] is True
        assert "preflight_blocked" not in tasks_by_id[task_id]
    for task_id in ("SRT-021", "SRT-022", "SRT-023", "SRT-024", "SRT-025", "SRT-026", "SRT-027"):
        assert tasks_by_id[task_id]["is_schedulable"] is True
        assert "preflight_blocked" not in tasks_by_id[task_id]
    assert tasks_by_id["SRT-015"]["implementation_timeout_seconds"] == 7200
    assert isinstance(
        tasks_by_id["SRT-015"]["implementation_timeout_seconds"],
        int,
    )
    assert tasks_by_id["SRT-026"]["implementation_timeout_seconds"] == 14400


def _write_gate_report(
    repo_root: Path,
    relative_path: Path = SRT014_REPORT_RELATIVE_PATH,
) -> Path:
    path = repo_root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    deterministic_ids = [f"arm-{index:02d}" for index in range(4)]
    model_ids = [f"arm-{index:02d}" for index in range(4, 30)]
    deterministic_records = []
    model_records = []
    for index, arm_id in enumerate([*deterministic_ids, *model_ids]):
        record = {
            "coordinate_key": f"case-{index % 5}:0:{arm_id}",
            "case_id": f"case-{index % 5}",
            "repeat_index": 0,
            "arm_id": arm_id,
            "status": "failed",
            "failure": {
                "code": "empty_l2" if index % 2 else "blank_t1",
                "stage": "realization" if index % 2 else "construction",
            },
            "gates": {
                "source_copy_exclusion": index % 3 != 0,
                "polarity_preservation": index % 3 != 1,
                "full_coverage": False,
                "selection_eligible": False,
            },
        }
        (
            deterministic_records
            if arm_id in deterministic_ids
            else model_records
        ).append(record)
    path.write_text(
        json.dumps(
            {
                "report_cid": "bafyreifakereport",
                "preregistration": {
                    "deterministic_cell_ids": deterministic_ids,
                    "model_backed_cell_ids": model_ids,
                },
                "execution": {
                    "deterministic": {"records": deterministic_records},
                    "model_backed": {"records": model_records},
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _test_gate_receipt(payload: dict[str, object]) -> dict[str, object]:
    receipt = dict(payload)
    receipt["gate_cid"] = cid_for_dag_json(receipt)
    receipt["gate_cid_codec"] = "dag-json"
    receipt["gate_cid_scope"] = "payload_without_gate_cid_fields"
    return receipt


def _valid_remediation_manifest_gate(
    original_gate: dict[str, object],
) -> dict[str, object]:
    return _test_gate_receipt({
        "schema": NO_ELIGIBLE_REMEDIATION_MANIFEST_GATE_SCHEMA,
        "status": "valid",
        "valid": True,
        "report_path": str(SRT014_REPORT_RELATIVE_PATH),
        "srt014_gate_cid": original_gate["gate_cid"],
        "srt014_report_cid": original_gate.get("report_cid"),
        "srt014_report_raw_cid": original_gate.get("report_raw_cid"),
        "manifest_path": str(
            NO_ELIGIBLE_REMEDIATION_MANIFEST_RELATIVE_PATH
        ),
        "manifest_cid": cid_for_dag_json({"kind": "remediation-manifest"}),
        "manifest_raw_cid": cid_for_bytes(b"remediation-manifest"),
        "reason_codes": ["no_eligible_remediation_manifest_valid"],
    })


def _repo_bound_canonical_gate_receipts() -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    original = _test_gate_receipt({
        "schema": SRT014_DOWNSTREAM_GATE_SCHEMA,
        "status": "remediation_required",
        "launch_authorized": False,
        "report_path": str(SRT014_REPORT_RELATIVE_PATH),
        "report_cid": cid_for_dag_json({"report": "original"}),
        "report_raw_cid": cid_for_bytes(b"original-report"),
        "selection_outcome": "no_eligible_composition",
        "selection_basis": None,
        "selectable_arm_ids": [],
        "implementation_representative_arm_id": None,
        "tie_bound": 30,
        "reason_codes": ["srt014_no_eligible_composition"],
        "remediation": {"arm_count": 30, "eligible_arm_count": 0},
    })
    manifest = _valid_remediation_manifest_gate(original)
    replacement = _test_gate_receipt({
        "schema": REPLACEMENT_SELECTION_GATE_SCHEMA,
        "status": "authorized",
        "launch_authorized": True,
        "report_path": str(REPLACEMENT_REPORT_RELATIVE_PATH),
        "report_cid": cid_for_dag_json({"report": "replacement"}),
        "report_raw_cid": cid_for_bytes(b"replacement-report"),
        "report_role": "replacement_full_matrix",
        "selection_outcome": "selected",
        "selection_basis": "replacement_unique_winner",
        "selectable_arm_ids": ["arm-03"],
        "implementation_representative_arm_id": "arm-03",
        "tie_bound": 30,
        "reason_codes": ["replacement_unique_full_coverage_winner"],
        "remediation": None,
    })
    return original, manifest, replacement


def _resign_gate(
    receipt: dict[str, object],
    **updates: object,
) -> dict[str, object]:
    payload = {
        key: value
        for key, value in receipt.items()
        if key not in {"gate_cid", "gate_cid_codec", "gate_cid_scope"}
    }
    payload.update(updates)
    return _test_gate_receipt(payload)


def _patch_repo_bound_canonical_gate_receipts(
    monkeypatch: pytest.MonkeyPatch,
    original: dict[str, object],
    manifest: dict[str, object],
    replacement: dict[str, object],
) -> None:
    monkeypatch.setattr(
        scheduler_module,
        "evaluate_srt014_downstream_gate",
        lambda _repo_root: dict(original),
    )
    monkeypatch.setattr(
        scheduler_module,
        "_evaluate_no_eligible_remediation_manifest_gate",
        lambda _repo_root, **_kwargs: dict(manifest),
    )
    monkeypatch.setattr(
        scheduler_module,
        "evaluate_replacement_selection_gate",
        lambda _repo_root: dict(replacement),
    )


def _write_remediation_manifest(
    repo_root: Path,
    original_gate: dict[str, object],
) -> tuple[Path, dict[str, object]]:
    payload: dict[str, object] = {
        "interface": NO_ELIGIBLE_REMEDIATION_MANIFEST_INTERFACE,
        "schema_version": NO_ELIGIBLE_REMEDIATION_MANIFEST_SCHEMA,
        "status": "frozen_no_eligible",
        "source": {
            "srt014_report_path": str(SRT014_REPORT_RELATIVE_PATH),
            "srt014_report_cid": original_gate["report_cid"],
            "srt014_report_raw_cid": original_gate["report_raw_cid"],
            "srt014_gate_cid": original_gate["gate_cid"],
        },
        "remediation": original_gate["remediation"],
        "protocol_immutable": True,
        "replacement_run_required": True,
        "srt015_fenced": True,
    }
    payload["manifest_cid"] = cid_for_dag_json(payload)
    path = repo_root / NO_ELIGIBLE_REMEDIATION_MANIFEST_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path, payload


@pytest.mark.parametrize(
    ("validated", "status", "authorized", "representative"),
    (
        (
            {
                "status": "valid",
                "report_cid": "bafyreifakereport",
                "selection_outcome": "selected",
                "winner_arm_id": "arm-07",
                "co_winner_arm_ids": ["arm-07"],
                "bounded_tie": False,
            },
            "authorized",
            True,
            "arm-07",
        ),
        (
            {
                "status": "valid",
                "report_cid": "bafyreifakereport",
                "selection_outcome": "exact_tie",
                "winner_arm_id": None,
                "co_winner_arm_ids": ["arm-19", "arm-03"],
                "bounded_tie": True,
            },
            "authorized",
            True,
            "arm-03",
        ),
        (
            {
                "status": "valid",
                "report_cid": "bafyreifakereport",
                "selection_outcome": "no_eligible_composition",
                "winner_arm_id": None,
                "co_winner_arm_ids": [],
                "bounded_tie": False,
            },
            "remediation_required",
            False,
            None,
        ),
    ),
)
def test_srt014_gate_handles_every_valid_selection_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    validated: dict[str, object],
    status: str,
    authorized: bool,
    representative: str | None,
) -> None:
    _write_gate_report(tmp_path)
    fixture = (
        tmp_path / "tests/fixtures/semantic_roundtrip/pilot_cases.json"
    )
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_text("[]\n", encoding="utf-8")
    monkeypatch.setattr(
        composition_report,
        "validate_composition_report",
        lambda *_args, **_kwargs: validated,
    )

    gate = evaluate_srt014_downstream_gate(tmp_path)

    assert gate["status"] == status
    assert gate["launch_authorized"] is authorized
    assert gate["implementation_representative_arm_id"] == representative
    assert validate_cid(gate["gate_cid"], codecs=("dag-json",)) == gate["gate_cid"]
    if validated["selection_outcome"] == "exact_tie":
        assert gate["selection_basis"] == "srt015_bounded_tie_policy"
        assert gate["tie_bound"] == 30
    if validated["selection_outcome"] == "no_eligible_composition":
        remediation = gate["remediation"]
        assert remediation["classification"] == (
            "all_preregistered_arms_failed_selection_eligibility"
        )
        assert remediation["arm_count"] == 30
        assert remediation["eligible_arm_count"] == 0
        assert remediation["systemic_gate_ids"] == ["full_coverage"]
        assert remediation["terminal_failure_reason_counts"] == {
            "blank_t1": 15,
            "empty_l2": 15,
        }
        assert remediation["srt015_must_remain_fenced"] is True
        assert remediation["frozen_protocol_must_not_change"] is True
        assert remediation["recommended_task_inputs"][-1] == {
            "task_kind": "execute_replacement_full_matrix",
            "protocol_action": "preserve_frozen_protocol",
            "artifact_action": "new_immutable_run_namespace_and_report",
            "requires_all_prior_remediation_receipts": True,
        }


def test_invalid_or_unbounded_srt014_evidence_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_gate_report(tmp_path)
    monkeypatch.setattr(
        composition_report,
        "validate_composition_report",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ValueError("forged co-winner set")
        ),
    )

    gate = evaluate_srt014_downstream_gate(tmp_path)

    assert gate["status"] == "invalid"
    assert gate["launch_authorized"] is False
    assert gate["selectable_arm_ids"] == []
    assert "srt014_report_validation_failed" in gate["reason_codes"]


def test_authorized_gate_keeps_srt015_and_descendants_schedulable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_scheduler_config(DEFAULT_CONFIG_PATH)
    original_gate = _test_gate_receipt({
        "schema": SRT014_DOWNSTREAM_GATE_SCHEMA,
        "status": "remediation_required",
        "launch_authorized": False,
        "reason_codes": ["srt014_no_eligible_composition"],
    })
    manifest_gate = _valid_remediation_manifest_gate(original_gate)
    replacement_gate = _test_gate_receipt({
        "schema": REPLACEMENT_SELECTION_GATE_SCHEMA,
        "status": "authorized",
        "launch_authorized": True,
        "selection_outcome": "selected",
        "selection_basis": "replacement_unique_winner",
        "selectable_arm_ids": ["arm-03"],
        "implementation_representative_arm_id": "arm-03",
        "reason_codes": ["replacement_unique_full_coverage_winner"],
    })
    canonical_gate = scheduler_module._compose_canonical_design_gate(
        srt014_gate=original_gate,
        remediation_manifest_gate=manifest_gate,
        replacement_gate=replacement_gate,
    )
    monkeypatch.setattr(
        scheduler_module,
        "evaluate_srt014_downstream_gate",
        lambda _repo_root: original_gate,
    )
    monkeypatch.setattr(
        scheduler_module,
        "evaluate_replacement_selection_gate",
        lambda _repo_root: replacement_gate,
    )
    monkeypatch.setattr(
        scheduler_module,
        "_evaluate_no_eligible_remediation_manifest_gate",
        lambda _repo_root, **_kwargs: manifest_gate,
    )

    index = build_taskboard_bundle_index(
        repo_root=REPO_ROOT,
        taskboard_path=TASKBOARD,
        bundle_index_path=tmp_path / "bundles" / "index.json",
        task_prefix=config["task_prefix"],
        provider_id=config["provider"]["provider_id"],
    )
    tasks_by_id = {
        task["task_id"]: task
        for bundle in index["bundles"].values()
        for task in bundle["tasks"]
    }

    for task_id in ("SRT-015", "SRT-016", "SRT-017", "SRT-018", "SRT-019"):
        assert tasks_by_id[task_id]["is_schedulable"] is True
        assert "preflight_blocked" not in tasks_by_id[task_id]
        assert (
            tasks_by_id[task_id]["canonical_design_gate_cid"]
            == canonical_gate["gate_cid"]
        )


def test_completed_srt014_only_makes_replacement_gate_task_claimable(
    tmp_path: Path,
) -> None:
    board = tmp_path / "gate.todo.md"
    board.write_text(
        """# Gate board

## SRT-014 Completed benchmark

- Status: completed
- Completion: manual
- Priority: P0
- Track: benchmark
- Depends on:
- Outputs: docs/performance_snapshots/2026-07-26_semantic_roundtrip_composition_pilot.json
- Validation: true
- Board namespace: gate-test
- Bundle: gate/benchmark
- Parallel lane: benchmark
- Resource class: cpu-small
- Predicted files: docs/performance_snapshots/2026-07-26_semantic_roundtrip_composition_pilot.json
- Acceptance: terminal measurement

## SRT-027 Replacement gate

- Status: todo
- Completion: manual
- Priority: P0
- Track: benchmark
- Depends on: SRT-014
- Outputs: replacement-gate.json
- Validation: PYTHONPATH=. python benchmarks/semantic_roundtrip_scheduler.py gate --repo-root . --require-authorized
- Board namespace: gate-test
- Bundle: gate/replacement
- Parallel lane: replacement-gate
- Resource class: cpu-small
- Predicted files: replacement-gate.json
- Acceptance: fail closed unless replacement evidence authorizes

## SRT-015 Canonical design

- Status: todo
- Completion: manual
- Priority: P0
- Track: compiler
- Depends on: SRT-027
- Outputs: canonical.txt
- Validation: test -f canonical.txt
- Board namespace: gate-test
- Bundle: gate/design
- Parallel lane: design
- Resource class: cpu-small
- Predicted files: canonical.txt
- Acceptance: consume only selectable evidence
""",
        encoding="utf-8",
    )
    index_path = tmp_path / "bundles" / "index.json"

    index = build_taskboard_bundle_index(
        repo_root=tmp_path,
        taskboard_path=board,
        bundle_index_path=index_path,
    )
    payloads = build_bundle_task_payloads(index_path)
    tasks = {
        task["task_id"]: task
        for bundle in index["bundles"].values()
        for task in bundle["tasks"]
    }

    assert index["srt014_downstream_gate"]["status"] == "pending"
    assert tasks["SRT-014"]["status"] == "completed"
    assert tasks["SRT-015"]["is_schedulable"] is True
    assert any(
        "SRT-027" in payload["execution_slice_task_ids"]
        and payload["claimable"]
        for payload in payloads
    )
    assert not any(
        "SRT-015" in payload["execution_slice_task_ids"]
        and payload["claimable"]
        for payload in payloads
    )


@pytest.mark.parametrize(
    ("replacement_status", "expected_status"),
    (
        ("pending", "replacement_pending"),
        ("invalid", "replacement_invalid"),
        (
            "replacement_remediation_required",
            "replacement_remediation_required",
        ),
    ),
)
def test_replacement_missing_invalid_or_no_eligible_cannot_authorize_srt015(
    tmp_path: Path,
    replacement_status: str,
    expected_status: str,
) -> None:
    original = _test_gate_receipt({
        "schema": SRT014_DOWNSTREAM_GATE_SCHEMA,
        "status": "remediation_required",
        "launch_authorized": False,
        "report_cid": "bafyrei-original-report",
        "selection_outcome": "no_eligible_composition",
        "reason_codes": ["srt014_no_eligible_composition"],
        "remediation": {"arm_count": 30},
    })
    replacement = _test_gate_receipt({
        "schema": REPLACEMENT_SELECTION_GATE_SCHEMA,
        "status": replacement_status,
        "launch_authorized": False,
        "report_cid": None,
        "selection_outcome": (
            "no_eligible_composition"
            if replacement_status == "replacement_remediation_required"
            else None
        ),
        "reason_codes": [f"replacement_{replacement_status}"],
        "remediation": (
            {"arm_count": 30}
            if replacement_status == "replacement_remediation_required"
            else None
        ),
    })

    gate = scheduler_module._compose_canonical_design_gate(
        srt014_gate=original,
        remediation_manifest_gate=_valid_remediation_manifest_gate(original),
        replacement_gate=replacement,
    )

    assert gate["status"] == expected_status
    assert gate["launch_authorized"] is False
    assert gate["selectable_arm_ids"] == []
    assert gate["implementation_representative_arm_id"] is None


@pytest.mark.parametrize(
    ("outcome", "basis"),
    (
        ("selected", "replacement_unique_winner"),
        ("exact_tie", "replacement_bounded_tie_policy"),
    ),
)
def test_only_selectable_replacement_evidence_authorizes_srt015(
    tmp_path: Path,
    outcome: str,
    basis: str,
) -> None:
    original = _test_gate_receipt({
        "schema": SRT014_DOWNSTREAM_GATE_SCHEMA,
        "status": "remediation_required",
        "launch_authorized": False,
        "report_cid": "bafyrei-original-report",
        "selection_outcome": "no_eligible_composition",
        "reason_codes": ["srt014_no_eligible_composition"],
    })
    replacement = _test_gate_receipt({
        "schema": REPLACEMENT_SELECTION_GATE_SCHEMA,
        "status": "authorized",
        "launch_authorized": True,
        "report_cid": "bafyrei-replacement-report",
        "selection_outcome": outcome,
        "selection_basis": basis,
        "selectable_arm_ids": ["arm-03", "arm-19"],
        "implementation_representative_arm_id": "arm-03",
        "reason_codes": ["replacement_full_coverage_selection"],
    })

    gate = scheduler_module._compose_canonical_design_gate(
        srt014_gate=original,
        remediation_manifest_gate=_valid_remediation_manifest_gate(original),
        replacement_gate=replacement,
    )

    assert gate["status"] == "authorized"
    assert gate["launch_authorized"] is True
    assert gate["selection_basis"] == basis
    assert gate["selectable_arm_ids"] == ["arm-03", "arm-19"]
    assert gate["implementation_representative_arm_id"] == "arm-03"


def test_remediation_manifest_is_exactly_cid_and_lineage_bound(
    tmp_path: Path,
) -> None:
    original = _test_gate_receipt({
        "schema": SRT014_DOWNSTREAM_GATE_SCHEMA,
        "status": "remediation_required",
        "launch_authorized": False,
        "report_cid": cid_for_dag_json({"kind": "original-report"}),
        "report_raw_cid": cid_for_bytes(b"original-report"),
        "selection_outcome": "no_eligible_composition",
        "reason_codes": ["srt014_no_eligible_composition"],
        "remediation": {
            "arm_count": 30,
            "eligible_arm_count": 0,
            "systemic_gate_ids": ["full_coverage"],
        },
    })

    missing = scheduler_module._evaluate_no_eligible_remediation_manifest_gate(
        tmp_path,
        srt014_gate=original,
    )
    assert missing["status"] == "pending"
    assert missing["valid"] is False

    path, payload = _write_remediation_manifest(tmp_path, original)
    valid = scheduler_module._evaluate_no_eligible_remediation_manifest_gate(
        tmp_path,
        srt014_gate=original,
    )
    assert valid["status"] == "valid"
    assert valid["valid"] is True
    assert valid["manifest_cid"] == payload["manifest_cid"]
    assert valid["manifest_raw_cid"] == cid_for_bytes(path.read_bytes())

    forged = dict(payload)
    forged["source"] = {
        **dict(payload["source"]),
        "srt014_report_raw_cid": cid_for_bytes(b"forged-report"),
    }
    forged_without_cid = dict(forged)
    del forged_without_cid["manifest_cid"]
    forged["manifest_cid"] = cid_for_dag_json(forged_without_cid)
    path.write_text(
        json.dumps(forged, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    invalid = scheduler_module._evaluate_no_eligible_remediation_manifest_gate(
        tmp_path,
        srt014_gate=original,
    )
    assert invalid["status"] == "invalid"
    assert invalid["valid"] is False
    assert "no_eligible_remediation_manifest_invalid" in invalid["reason_codes"]


def test_manifest_gate_rejects_cached_original_that_differs_from_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original, _manifest, _replacement = (
        _repo_bound_canonical_gate_receipts()
    )
    monkeypatch.setattr(
        scheduler_module,
        "evaluate_srt014_downstream_gate",
        lambda _repo_root: dict(original),
    )
    contradictory = _resign_gate(
        original,
        launch_authorized=True,
        selection_outcome="selected",
    )

    denied = evaluate_no_eligible_remediation_manifest_gate(
        tmp_path,
        srt014_gate=contradictory,
    )

    assert denied["status"] == "invalid"
    assert denied["valid"] is False
    assert denied["reason_codes"] == [
        "supplied_srt014_receipt_does_not_match_repo_evidence"
    ]
    assert denied["srt014_gate_cid"] == original["gate_cid"]


def test_selected_replacement_cannot_bypass_missing_or_invalid_manifest(
    tmp_path: Path,
) -> None:
    original = _test_gate_receipt({
        "schema": SRT014_DOWNSTREAM_GATE_SCHEMA,
        "status": "remediation_required",
        "launch_authorized": False,
        "report_cid": "bafyrei-original-report",
        "selection_outcome": "no_eligible_composition",
        "reason_codes": ["srt014_no_eligible_composition"],
    })
    replacement = _test_gate_receipt({
        "schema": REPLACEMENT_SELECTION_GATE_SCHEMA,
        "status": "authorized",
        "launch_authorized": True,
        "report_cid": "bafyrei-replacement-report",
        "selection_outcome": "selected",
        "selection_basis": "replacement_unique_winner",
        "selectable_arm_ids": ["arm-03"],
        "implementation_representative_arm_id": "arm-03",
        "reason_codes": ["replacement_full_coverage_selection"],
    })

    for manifest, expected_status in (
        (
            _test_gate_receipt({
                "schema": NO_ELIGIBLE_REMEDIATION_MANIFEST_GATE_SCHEMA,
                "status": "pending",
                "valid": False,
                "reason_codes": ["no_eligible_remediation_manifest_missing"],
            }),
            "remediation_manifest_pending",
        ),
        (
            _test_gate_receipt({
                "schema": NO_ELIGIBLE_REMEDIATION_MANIFEST_GATE_SCHEMA,
                "status": "invalid",
                "valid": False,
                "reason_codes": ["no_eligible_remediation_manifest_invalid"],
            }),
            "remediation_manifest_invalid",
        ),
    ):
        gate = scheduler_module._compose_canonical_design_gate(
            srt014_gate=original,
            remediation_manifest_gate=manifest,
            replacement_gate=replacement,
        )
        assert gate["status"] == expected_status
        assert gate["launch_authorized"] is False
        assert gate["selectable_arm_ids"] == []


def test_cross_original_manifest_receipt_cannot_authorize(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original, manifest, replacement = _repo_bound_canonical_gate_receipts()
    _patch_repo_bound_canonical_gate_receipts(
        monkeypatch,
        original,
        manifest,
        replacement,
    )
    exact = evaluate_canonical_design_gate(
        tmp_path,
        srt014_gate=original,
        remediation_manifest_gate=manifest,
        replacement_gate=replacement,
    )
    assert exact["status"] == "authorized"
    assert exact["launch_authorized"] is True

    cross_original = _resign_gate(
        manifest,
        srt014_gate_cid=cid_for_dag_json({"gate": "another-original"}),
        srt014_report_cid=cid_for_dag_json(
            {"report": "another-original"}
        ),
        srt014_report_raw_cid=cid_for_bytes(b"another-original"),
    )
    denied = evaluate_canonical_design_gate(
        tmp_path,
        srt014_gate=original,
        remediation_manifest_gate=cross_original,
        replacement_gate=replacement,
    )

    assert denied["status"] == "remediation_manifest_invalid"
    assert denied["launch_authorized"] is False
    assert denied["selectable_arm_ids"] == []
    assert denied["reason_codes"] == [
        (
            "supplied_remediation_manifest_receipt_"
            "does_not_match_repo_evidence"
        )
    ]


@pytest.mark.parametrize(
    "contradiction",
    (
        {"launch_authorized": True},
        {
            "selection_outcome": "selected",
            "selection_basis": "srt014_unique_winner",
            "selectable_arm_ids": ["arm-03"],
            "implementation_representative_arm_id": "arm-03",
        },
    ),
)
def test_contradictory_original_receipt_cannot_authorize(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    contradiction: dict[str, object],
) -> None:
    original, manifest, replacement = _repo_bound_canonical_gate_receipts()
    _patch_repo_bound_canonical_gate_receipts(
        monkeypatch,
        original,
        manifest,
        replacement,
    )
    contradictory = _resign_gate(original, **contradiction)

    denied = evaluate_canonical_design_gate(
        tmp_path,
        srt014_gate=contradictory,
        remediation_manifest_gate=manifest,
        replacement_gate=replacement,
    )

    assert denied["status"] == (
        "original_evidence_invalid_or_not_no_eligible"
    )
    assert denied["launch_authorized"] is False
    assert denied["selectable_arm_ids"] == []
    assert denied["reason_codes"] == [
        "supplied_original_receipt_does_not_match_repo_evidence"
    ]


@pytest.mark.parametrize(
    "forgery",
    (
        {
            "report_cid": "not-a-cid",
            "report_raw_cid": "also-not-a-cid",
        },
        {
            "selection_outcome": "selected",
            "selection_basis": "replacement_unique_winner",
            "selectable_arm_ids": [],
            "implementation_representative_arm_id": None,
        },
        {
            "selection_outcome": "no_eligible_composition",
            "selection_basis": "replacement_unique_winner",
            "selectable_arm_ids": ["unknown-arm"],
            "implementation_representative_arm_id": "different-arm",
        },
    ),
)
def test_forged_authorized_replacement_receipt_cannot_authorize(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    forgery: dict[str, object],
) -> None:
    original, manifest, replacement = _repo_bound_canonical_gate_receipts()
    _patch_repo_bound_canonical_gate_receipts(
        monkeypatch,
        original,
        manifest,
        replacement,
    )
    forged = _resign_gate(replacement, **forgery)

    denied = evaluate_canonical_design_gate(
        tmp_path,
        srt014_gate=original,
        remediation_manifest_gate=manifest,
        replacement_gate=forged,
    )

    assert denied["status"] == "replacement_invalid"
    assert denied["launch_authorized"] is False
    assert denied["selectable_arm_ids"] == []
    assert denied["implementation_representative_arm_id"] is None
    assert denied["reason_codes"] == [
        "supplied_replacement_receipt_does_not_match_repo_evidence"
    ]


def test_canonical_gate_artifact_must_exactly_match_recomputed_receipt(
    tmp_path: Path,
) -> None:
    expected = _test_gate_receipt({
        "schema": CANONICAL_DESIGN_GATE_SCHEMA,
        "status": "authorized",
        "launch_authorized": True,
        "srt014_gate_cid": cid_for_dag_json({"kind": "original-gate"}),
        "remediation_manifest_cid": cid_for_dag_json(
            {"kind": "remediation-manifest"}
        ),
        "replacement_gate_cid": cid_for_dag_json(
            {"kind": "replacement-gate"}
        ),
        "selectable_arm_ids": ["arm-03"],
        "implementation_representative_arm_id": "arm-03",
        "reason_codes": [
            "replacement_report_independently_authorizes_selection"
        ],
    })

    missing = scheduler_module._evaluate_canonical_design_gate_artifact(
        tmp_path,
        canonical_gate=expected,
    )
    assert missing["status"] == "pending"
    assert missing["valid"] is False

    path = tmp_path / CANONICAL_DESIGN_GATE_ARTIFACT_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(expected, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    valid = scheduler_module._evaluate_canonical_design_gate_artifact(
        tmp_path,
        canonical_gate=expected,
    )
    assert valid["schema"] == (
        CANONICAL_DESIGN_GATE_ARTIFACT_VALIDATION_SCHEMA
    )
    assert valid["status"] == "valid"
    assert valid["valid"] is True
    assert valid["artifact_raw_cid"] == cid_for_bytes(path.read_bytes())

    forged = {**expected, "launch_authorized": False}
    path.write_text(
        json.dumps(forged, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    invalid = scheduler_module._evaluate_canonical_design_gate_artifact(
        tmp_path,
        canonical_gate=expected,
    )
    assert invalid["status"] == "invalid"
    assert invalid["valid"] is False
    assert "canonical_design_gate_artifact_invalid" in (
        invalid["reason_codes"]
    )


def test_canonical_gate_artifact_rejects_forged_cached_expected_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original, manifest, replacement = _repo_bound_canonical_gate_receipts()
    expected = scheduler_module._compose_canonical_design_gate(
        srt014_gate=original,
        remediation_manifest_gate=manifest,
        replacement_gate=replacement,
    )
    forged = _resign_gate(
        expected,
        selectable_arm_ids=["forged-arm"],
        implementation_representative_arm_id="forged-arm",
    )
    path = tmp_path / CANONICAL_DESIGN_GATE_ARTIFACT_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(forged, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        scheduler_module,
        "evaluate_canonical_design_gate",
        lambda _repo_root: expected,
    )

    denied = evaluate_canonical_design_gate_artifact(
        tmp_path,
        canonical_gate=forged,
    )

    assert denied["status"] == "invalid"
    assert denied["valid"] is False
    assert denied["canonical_design_gate_cid"] == expected["gate_cid"]
    assert denied["reason_codes"] == [
        (
            "supplied_canonical_design_gate_receipt_"
            "does_not_match_repo_evidence"
        )
    ]


@pytest.mark.parametrize(("valid", "expected_returncode"), ((True, 0), (False, 1)))
def test_manifest_gate_cli_requires_valid_manifest(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    valid: bool,
    expected_returncode: int,
) -> None:
    monkeypatch.setattr(
        scheduler_module,
        "evaluate_no_eligible_remediation_manifest_gate",
        lambda _repo_root: {"status": "valid" if valid else "invalid", "valid": valid},
    )

    returncode = scheduler_module.main(
        ["manifest-gate", "--repo-root", str(REPO_ROOT)]
    )

    assert returncode == expected_returncode
    capsys.readouterr()


@pytest.mark.parametrize(
    ("artifact_valid", "expected_returncode"),
    ((True, 0), (False, 1)),
)
def test_gate_cli_requires_exact_artifact_when_requested(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    artifact_valid: bool,
    expected_returncode: int,
) -> None:
    canonical = _test_gate_receipt({
        "schema": CANONICAL_DESIGN_GATE_SCHEMA,
        "status": "authorized",
        "launch_authorized": True,
        "reason_codes": ["replacement_authorized"],
    })
    monkeypatch.setattr(
        scheduler_module,
        "evaluate_canonical_design_gate",
        lambda _repo_root: canonical,
    )
    monkeypatch.setattr(
        scheduler_module,
        "_evaluate_canonical_design_gate_artifact",
        lambda _repo_root, **_kwargs: {
            "status": "valid" if artifact_valid else "invalid",
            "valid": artifact_valid,
        },
    )

    returncode = scheduler_module.main(
        [
            "gate",
            "--repo-root",
            str(REPO_ROOT),
            "--require-authorized",
            "--validate-artifact",
            str(CANONICAL_DESIGN_GATE_ARTIFACT_RELATIVE_PATH),
        ]
    )

    assert returncode == expected_returncode
    capsys.readouterr()


def test_replacement_gate_uses_replacement_report_and_basis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_gate_report(tmp_path, REPLACEMENT_REPORT_RELATIVE_PATH)
    monkeypatch.setattr(
        composition_report,
        "validate_composition_report",
        lambda *_args, **_kwargs: {
            "status": "valid",
            "report_cid": "bafyreifakereport",
            "selection_outcome": "selected",
            "winner_arm_id": "arm-07",
            "co_winner_arm_ids": ["arm-07"],
            "bounded_tie": False,
        },
    )

    gate = evaluate_replacement_selection_gate(tmp_path)

    assert gate["status"] == "authorized"
    assert gate["launch_authorized"] is True
    assert gate["report_path"] == str(REPLACEMENT_REPORT_RELATIVE_PATH)
    assert gate["selection_basis"] == "replacement_unique_winner"
    assert gate["implementation_representative_arm_id"] == "arm-07"


def test_no_eligible_makes_only_remediation_manifest_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dependencies = {
        "SRT-014": (),
        "SRT-021": ("SRT-014",),
        "SRT-022": ("SRT-021",),
        "SRT-023": ("SRT-021",),
        "SRT-024": ("SRT-021",),
        "SRT-025": ("SRT-022", "SRT-023", "SRT-024"),
        "SRT-026": ("SRT-025",),
        "SRT-027": ("SRT-026",),
        "SRT-015": ("SRT-027",),
        "SRT-016": ("SRT-015",),
    }
    sections = ["# No-eligible remediation board"]
    for task_id, depends_on in dependencies.items():
        status = "completed" if task_id == "SRT-014" else "todo"
        sections.append(
            f"""## {task_id} Test task

- Status: {status}
- Completion: manual
- Priority: P0
- Track: benchmark
- Depends on: {", ".join(depends_on)}
- Outputs: {task_id.lower()}.json
- Validation: true
- Board namespace: gate-test
- Bundle: gate/{task_id.lower()}
- Parallel lane: {task_id.lower()}
- Resource class: cpu-small
- Predicted files: {task_id.lower()}.json
- Acceptance: bounded test task
"""
        )
    board = tmp_path / "remediation.todo.md"
    board.write_text("\n".join(sections), encoding="utf-8")
    original_gate = _test_gate_receipt({
        "schema": SRT014_DOWNSTREAM_GATE_SCHEMA,
        "status": "remediation_required",
        "launch_authorized": False,
        "reason_codes": ["srt014_no_eligible_composition"],
    })
    replacement_gate = _test_gate_receipt({
        "schema": REPLACEMENT_SELECTION_GATE_SCHEMA,
        "status": "pending",
        "launch_authorized": False,
        "reason_codes": ["replacement_report_missing"],
    })
    monkeypatch.setattr(
        scheduler_module,
        "evaluate_srt014_downstream_gate",
        lambda _repo_root: original_gate,
    )
    monkeypatch.setattr(
        scheduler_module,
        "evaluate_replacement_selection_gate",
        lambda _repo_root: replacement_gate,
    )
    index_path = tmp_path / "bundles" / "index.json"

    index = build_taskboard_bundle_index(
        repo_root=tmp_path,
        taskboard_path=board,
        bundle_index_path=index_path,
    )
    payloads = build_bundle_task_payloads(index_path)
    tasks = {
        task["task_id"]: task
        for bundle in index["bundles"].values()
        for task in bundle["tasks"]
    }
    claimable = {
        task_id
        for payload in payloads
        if payload["claimable"]
        for task_id in payload["execution_slice_task_ids"]
    }

    assert claimable == {"SRT-021"}
    assert tasks["SRT-014"]["status"] == "completed"
    assert tasks["SRT-014"]["is_schedulable"] is False
    assert tasks["SRT-015"]["is_schedulable"] is True
    assert tasks["SRT-016"]["is_schedulable"] is True
    assert "preflight_blocked" not in tasks["SRT-015"]
    assert "preflight_blocked" not in tasks["SRT-016"]


@pytest.mark.parametrize(
    "receipt",
    (
        {"status": "failed"},
        {"outcome": "no_eligible_composition"},
    ),
)
def test_srt015_automatically_unblocks_only_after_successful_srt027_receipt(
    tmp_path: Path,
    receipt: dict[str, str],
) -> None:
    board = tmp_path / "automatic-unblock.todo.md"
    board.write_text(
        """# Automatic gate unblock board

## SRT-027 Replacement selection gate

- Status: todo
- Completion: manual
- Priority: P0
- Track: benchmark
- Depends on:
- Outputs: replacement-gate.json
- Validation: PYTHONPATH=. python benchmarks/semantic_roundtrip_scheduler.py gate --repo-root . --require-authorized
- Board namespace: gate-test
- Bundle: gate/replacement
- Parallel lane: replacement-gate
- Resource class: cpu-small
- Predicted files: replacement-gate.json
- Acceptance: complete only for authorized replacement evidence

## SRT-015 Canonical design

- Status: todo
- Completion: manual
- Priority: P0
- Track: compiler
- Depends on: SRT-027
- Outputs: canonical.txt
- Validation: test -f canonical.txt
- Board namespace: gate-test
- Bundle: gate/design
- Parallel lane: design
- Resource class: cpu-small
- Predicted files: canonical.txt
- Acceptance: consume only authorized evidence
""",
        encoding="utf-8",
    )
    index_path = tmp_path / "bundles" / "index.json"
    index = build_taskboard_bundle_index(
        repo_root=tmp_path,
        taskboard_path=board,
        bundle_index_path=index_path,
    )
    index_bytes = index_path.read_bytes()
    tasks = {
        task["task_id"]: task
        for bundle in index["bundles"].values()
        for task in bundle["tasks"]
    }
    gate_cid = tasks["SRT-027"]["canonical_task_cid"]

    initial = build_bundle_task_payloads(index_path)
    assert tasks["SRT-015"]["is_schedulable"] is True
    assert any(
        payload["claimable"]
        and payload["execution_slice_task_ids"] == ["SRT-027"]
        for payload in initial
    )
    assert not any(
        payload["claimable"]
        and "SRT-015" in payload["execution_slice_task_ids"]
        for payload in initial
    )

    failed = build_bundle_task_payloads(
        index_path,
        merge_receipts=[
            {"canonical_task_cid": gate_cid, **receipt},
        ],
    )
    assert not any(
        payload["claimable"]
        and "SRT-015" in payload["execution_slice_task_ids"]
        for payload in failed
    )

    succeeded = build_bundle_task_payloads(
        index_path,
        merge_receipts=[
            {"canonical_task_cid": gate_cid, "status": "succeeded"},
        ],
    )
    assert any(
        payload["claimable"]
        and payload["execution_slice_task_ids"] == ["SRT-015"]
        for payload in succeeded
    )
    assert index_path.read_bytes() == index_bytes


def test_dependency_schedule_admits_the_second_wave_after_srt_002_and_srt_020(
    tmp_path: Path,
) -> None:
    config = load_scheduler_config(DEFAULT_CONFIG_PATH)
    index_path = tmp_path / "bundles" / "index.json"
    build_taskboard_bundle_index(
        repo_root=REPO_ROOT,
        taskboard_path=TASKBOARD,
        bundle_index_path=index_path,
        task_prefix=config["task_prefix"],
        provider_id=config["provider"]["provider_id"],
    )

    payloads = build_bundle_task_payloads(index_path)
    claimable_task_ids = {
        task_id
        for payload in payloads
        if payload["claimable"]
        for task_id in payload["execution_slice_task_ids"]
    }
    by_task_id = {
        task["task_id"]: (payload, task)
        for payload in payloads
        for task in payload["tasks"]
    }

    assert claimable_task_ids == {"SRT-003", "SRT-004", "SRT-005", "SRT-006"}
    assert by_task_id["SRT-002"][1]["status"] == "completed"
    assert by_task_id["SRT-020"][1]["status"] == "completed"
    assert by_task_id["SRT-002"][1]["claimable"] is False
    assert by_task_id["SRT-020"][1]["claimable"] is False
    assert by_task_id["SRT-003"][1]["blocking_task_cids"] == []
    assert by_task_id["SRT-007"][1]["claimable"] is False
    assert set(by_task_id["SRT-007"][1]["blocking_task_cids"]) == {
        by_task_id[task_id][1]["canonical_task_cid"]
        for task_id in ("SRT-003", "SRT-004", "SRT-005", "SRT-006")
    }


def test_custom_resource_class_is_rejected_before_index_write(
    tmp_path: Path,
) -> None:
    board = tmp_path / "invalid.todo.md"
    board.write_text(
        """# Board

## SRT-999 Invalid resource

- Status: todo
- Completion: manual
- Priority: P0
- Track: benchmark
- Depends on:
- Outputs: result.txt
- Validation: test -f result.txt
- Board namespace: test
- Bundle: test/invalid
- Parallel lane: invalid
- Resource class: model-leanstral-one-slot
- Predicted files: result.txt
- Acceptance: rejected
""",
        encoding="utf-8",
    )

    tasks = parse_task_file(board, "## SRT-")
    with pytest.raises(SchedulerPreparationError, match="unsupported resource class"):
        validate_taskboard_for_dynamic_scheduler(tasks)


@pytest.mark.parametrize("timeout", ("invalid", "0", "-1"))
def test_implementation_timeout_must_be_a_positive_integer(
    tmp_path: Path,
    timeout: str,
) -> None:
    board = tmp_path / "invalid-timeout.todo.md"
    board.write_text(
        f"""# Board

## SRT-999 Invalid timeout

- Status: todo
- Completion: manual
- Priority: P0
- Track: benchmark
- Depends on:
- Outputs: result.txt
- Validation: test -f result.txt
- Board namespace: test
- Bundle: test/invalid-timeout
- Parallel lane: invalid-timeout
- Resource class: cpu-small
- Implementation timeout seconds: {timeout}
- Predicted files: result.txt
- Acceptance: rejected
""",
        encoding="utf-8",
    )

    tasks = parse_task_file(board, "## SRT-")
    with pytest.raises(
        SchedulerPreparationError,
        match="implementation_timeout_seconds must be a positive integer",
    ):
        validate_taskboard_for_dynamic_scheduler(tasks)


def test_provider_probe_binds_exact_model_and_one_slot() -> None:
    config = load_scheduler_config(DEFAULT_CONFIG_PATH)["provider"]

    def fake_http_json(url: str, _timeout: float):
        if url.endswith("/health"):
            return {"status": "ok"}, 2
        if url.endswith("/slots"):
            return [{"id": 0, "is_processing": False}], 2
        if url.endswith("/props"):
            return {
                "total_slots": 1,
                "model_alias": config["model_id"],
                "build_info": "test-build",
                "default_generation_settings": {"n_ctx": 8192},
            }, 3
        return {
            "data": [
                {
                    "id": config["model_id"],
                    "capabilities": ["completion"],
                    "meta": {"n_ctx": 8192},
                }
            ]
        }, 3

    payload = probe_provider_capacity(config, http_json=fake_http_json)
    provider = payload["providers"]["leanstral-local"]

    assert payload["probe_errors"] == []
    assert provider["healthy"] is True
    assert provider["max_concurrency"] == 1
    assert provider["active_requests"] == 0
    assert provider["available_concurrency"] == 1
    assert provider["observed_slot_count"] == 1
    assert provider["slot_ids"] == [0]
    assert provider["model_ids"] == [config["model_id"]]
    assert provider["reported_total_slots"] == 1
    assert provider["context_window_tokens"] == 8192
    assert (
        validate_cid(payload["provider_capacity_cid"], codecs=("dag-json",))
        == payload["provider_capacity_cid"]
    )


def test_provider_probe_fails_closed_on_model_identity_mismatch() -> None:
    config = load_scheduler_config(DEFAULT_CONFIG_PATH)["provider"]

    def fake_http_json(url: str, _timeout: float):
        if url.endswith("/health"):
            return {"status": "ok"}, 1
        if url.endswith("/slots"):
            return [{"id": 0, "is_processing": False}], 1
        if url.endswith("/props"):
            return {
                "total_slots": 1,
                "model_alias": "different/model",
                "default_generation_settings": {"n_ctx": 8192},
            }, 1
        return {"data": [{"id": "different/model"}]}, 1

    payload = probe_provider_capacity(config, http_json=fake_http_json)
    provider = payload["providers"]["leanstral-local"]

    assert provider["healthy"] is False
    assert "configured_model_not_served" in payload["probe_errors"]
    assert "props_model_alias_mismatch" in payload["probe_errors"]
    assert provider["max_concurrency"] == 1


def test_provider_probe_observes_busy_llama_cpp_slot() -> None:
    config = load_scheduler_config(DEFAULT_CONFIG_PATH)["provider"]
    observed_timeouts: list[float] = []

    def fake_http_json(url: str, timeout: float):
        observed_timeouts.append(timeout)
        if url.endswith("/health"):
            return {"status": "ok"}, 1
        if url.endswith("/slots"):
            return [{"id": 0, "is_processing": True, "id_task": 17}], 4
        if url.endswith("/props"):
            return {
                "total_slots": 1,
                "model_alias": config["model_id"],
                "default_generation_settings": {"n_ctx": 8192},
            }, 2
        return {"data": [{"id": config["model_id"]}]}, 2

    payload = probe_provider_capacity(config, http_json=fake_http_json)
    provider = payload["providers"]["leanstral-local"]

    assert payload["probe_errors"] == []
    assert provider["healthy"] is True
    assert provider["active_requests"] == 1
    assert provider["available_concurrency"] == 0
    assert provider["observed_slot_count"] == 1
    assert observed_timeouts == [5.0, 5.0, 5.0, 5.0]


def test_provider_probe_reserves_capacity_when_slots_are_unavailable() -> None:
    config = load_scheduler_config(DEFAULT_CONFIG_PATH)["provider"]

    def fake_http_json(url: str, _timeout: float):
        if url.endswith("/health"):
            return {"status": "ok"}, 1
        if url.endswith("/slots"):
            raise TimeoutError("bounded slots timeout")
        if url.endswith("/props"):
            return {
                "total_slots": 1,
                "model_alias": config["model_id"],
                "default_generation_settings": {"n_ctx": 8192},
            }, 1
        return {"data": [{"id": config["model_id"]}]}, 1

    payload = probe_provider_capacity(config, http_json=fake_http_json)
    provider = payload["providers"]["leanstral-local"]

    assert provider["healthy"] is False
    assert provider["active_requests"] == 1
    assert provider["available_concurrency"] == 0
    assert provider["observed_slot_count"] == -1
    assert any(
        error.startswith("slots_probe:TimeoutError:")
        for error in payload["probe_errors"]
    )


@pytest.mark.parametrize(
    "slots",
    (
        [{"id": 0}],
        [{"id": 0, "is_processing": "false"}],
        [],
    ),
)
def test_provider_probe_rejects_ambiguous_slot_occupancy(
    slots: object,
) -> None:
    config = load_scheduler_config(DEFAULT_CONFIG_PATH)["provider"]

    def fake_http_json(url: str, _timeout: float):
        if url.endswith("/health"):
            return {"status": "ok"}, 1
        if url.endswith("/slots"):
            return slots, 1
        if url.endswith("/props"):
            return {
                "total_slots": 1,
                "model_alias": config["model_id"],
                "default_generation_settings": {"n_ctx": 8192},
            }, 1
        return {"data": [{"id": config["model_id"]}]}, 1

    payload = probe_provider_capacity(config, http_json=fake_http_json)
    provider = payload["providers"]["leanstral-local"]

    assert provider["healthy"] is False
    assert provider["active_requests"] == 1
    assert provider["available_concurrency"] == 0
    assert any(
        error.startswith("slots_probe:SchedulerPreparationError:")
        for error in payload["probe_errors"]
    )


def test_resource_scheduler_admits_only_one_leanstral_lane() -> None:
    # The provider reservation layer must independently enforce the physical
    # slot. DynamicBundleScheduler adds an earlier adaptive inference-stage
    # ceiling from the same telemetry, which may report ``stage_concurrency``
    # before this provider-specific fallback is reached.
    scheduler = ResourceScheduler(ResourcePolicy(max_lanes=4))
    host = HostResourceSnapshot(
        observed_at_ms=1,
        cpu_percent=10,
        memory_percent=10,
        disk_percent=10,
        memory_available_bytes=8_000_000_000,
        disk_available_bytes=8_000_000_000,
        active_workers=0,
        worker_limit=4,
        available_worker_capacity=4,
        capabilities=("cpu",),
        resource_classes=PROOF_RESOURCE_CLASSES,
    )
    lanes = [
        LaneResourceRequirements(
            lane_id=f"model-{index}",
            stage="inference",
            resource_class="llm-proof-draft",
            provider_id="leanstral-local",
            requires_provider=True,
        )
        for index in (1, 2)
    ]

    schedule = scheduler.schedule(
        lanes,
        host=host,
        providers={
            "leanstral-local": {
                "healthy": True,
                "max_concurrency": 1,
                "active_requests": 0,
            }
        },
    )

    assert schedule.admitted_lane_ids == ("model-1",)
    assert schedule.decisions[0].admitted is True
    assert schedule.decisions[1].admitted is False
    assert "provider_concurrency" in schedule.decisions[1].reasons


def test_adaptive_inference_stage_uses_same_one_slot_ceiling() -> None:
    scheduler = ResourceScheduler(
        ResourcePolicy(max_lanes=4, adaptive_enabled=True)
    )
    host = HostResourceSnapshot(
        observed_at_ms=1,
        cpu_percent=10,
        memory_percent=10,
        disk_percent=10,
        memory_available_bytes=8_000_000_000,
        disk_available_bytes=8_000_000_000,
        active_workers=0,
        worker_limit=4,
        available_worker_capacity=4,
        capabilities=("cpu",),
        resource_classes=PROOF_RESOURCE_CLASSES,
    )
    lanes = [
        LaneResourceRequirements(
            lane_id=f"adaptive-model-{index}",
            stage="inference",
            resource_class="llm-proof-draft",
            provider_id="leanstral-local",
            requires_provider=True,
        )
        for index in (1, 2)
    ]

    schedule = scheduler.schedule(
        lanes,
        host=host,
        providers={
            "leanstral-local": {
                "healthy": True,
                "max_concurrency": 1,
                "active_requests": 0,
            }
        },
    )

    assert schedule.admitted_lane_ids == ("adaptive-model-1",)
    assert {
        "stage_concurrency",
        "provider_concurrency",
    } & set(schedule.decisions[1].reasons)


def test_launch_command_uses_dynamic_scheduler_without_unsafe_once(
    tmp_path: Path,
) -> None:
    config = load_scheduler_config(DEFAULT_CONFIG_PATH)
    preparation = {
        "repo_root": str(REPO_ROOT),
        "runtime_root": str(tmp_path),
        "bundle_index_path": str(tmp_path / "bundles" / "index.json"),
        "provider_capacity_path": str(tmp_path / "provider_capacity.json"),
    }

    command = build_bundle_supervisor_command(
        preparation,
        config,
        implement=True,
        max_lanes=4,
        start=True,
    )

    assert command[1:3] == [
        "-m",
        "ipfs_accelerate_py.agent_supervisor.bundle_supervisor",
    ]
    assert "--start" in command
    assert "--implement" in command
    assert "--provider-capacity-path" in command
    assert command[command.index("--max-lanes") + 1] == "4"
    assert command[command.index("--task-prefix") + 1] == "## SRT-"
    assert "--once" not in command
