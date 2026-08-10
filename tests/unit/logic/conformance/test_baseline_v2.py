"""Join and seal the Wave-2 logic runtime baseline (LFP2-005).

``LogicRuntimeBaseline@2`` binds the four Wave-2 inventory artifacts and
publishes ``CapabilityLifecycle@1`` maturity rules.

Acceptance (fail-closed):

* Conflicting claims fail closed (schema/revision/source-identity drift,
  lifecycle conflation, multi-owner gaps).
* Each reachable gap has exactly one owner and one evidence obligation.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from ipfs_datasets_py.logic.conformance.baseline_v2 import (
    ARTIFACT_KEYS,
    CAPABILITY_LIFECYCLE_INTERFACE,
    CAPABILITY_LIFECYCLE_SCHEMA,
    DEFAULT_BASELINE_RELATIVE_PATH,
    GOAL_ID,
    LIFECYCLE_STAGES,
    LOGIC_RUNTIME_BASELINE_INTERFACE,
    LOGIC_RUNTIME_BASELINE_SCHEMA,
    MATERIALIZATION_TARGET,
    NON_CONFLATABLE_PAIRS,
    PROGRAM_ID,
    SOURCE_GOAL_ID,
    STAGE_EVIDENCE_OBLIGATIONS,
    TASK_ID,
    BaselineGap,
    BaselineV2Error,
    GapSource,
    assert_stages_not_conflated,
    assert_unique_gap_owners,
    build_capability_lifecycle,
    build_default_baseline_join,
    collect_boundary_gaps,
    collect_claim_gaps,
    collect_graph_work_gaps,
    default_baseline_join_path,
    detect_claim_conflicts,
    ensure_baseline_join_seal,
    is_compact_baseline_join_seal,
    join_baseline_v2,
    load_baseline_join,
    load_claim_artifact,
    render_baseline_join_json,
    to_baseline_join_seal_dict,
    validate_baseline_join,
    validate_capability_lifecycle,
    write_baseline_join,
)
from ipfs_datasets_py.logic.conformance.baseline_v2 import (
    main as baseline_v2_main,
)
from ipfs_datasets_py.logic.conformance.claim_runtime_audit import (
    LOGIC_CLAIM_RUNTIME_AUDIT_INTERFACE,
    LogicClaimRuntimeAuditReport,
    build_default_audit,
)
from ipfs_datasets_py.logic.conformance.claim_runtime_audit import (
    default_baseline_path as claim_baseline_path,
)
from ipfs_datasets_py.logic.conformance.corpus_v2 import (
    LOGIC_CONFORMANCE_CORPUS_INTERFACE,
    default_manifest_path,
)
from ipfs_datasets_py.logic.conformance.raw_boundary_inventory import (
    RAW_LOGIC_BOUNDARY_INVENTORY_INTERFACE,
)
from ipfs_datasets_py.logic.conformance.raw_boundary_inventory import (
    default_baseline_report_path as boundary_baseline_path,
)
from ipfs_datasets_py.logic.conformance.reachable_graph import (
    REACHABLE_CAPABILITY_GRAPH_INTERFACE,
    build_default_graph,
)
from ipfs_datasets_py.logic.conformance.reachable_graph import (
    default_baseline_path as graph_baseline_path,
)

DATASETS_ROOT = Path(__file__).resolve().parents[4]
BASELINE_DIR = (
    DATASETS_ROOT / "docs" / "architecture" / "logic" / "logic_parser_v2_baseline"
)
JOIN_PATH = BASELINE_DIR / "baseline_join.json"
CLAIM_PATH = BASELINE_DIR / "claim_runtime_audit.json"
BOUNDARY_PATH = BASELINE_DIR / "raw_boundary_inventory.json"
GRAPH_PATH = BASELINE_DIR / "reachable_capability_graph.json"
CORPUS_PATH = (
    DATASETS_ROOT / "tests" / "fixtures" / "logic_conformance_v2" / "manifest.json"
)
LOGIC_ROOT = DATASETS_ROOT / "ipfs_datasets_py" / "logic"


# ---------------------------------------------------------------------------
# Path contracts
# ---------------------------------------------------------------------------


def test_baseline_paths_resolve_to_checked_in_artifacts() -> None:
    assert CLAIM_PATH.is_file()
    assert BOUNDARY_PATH.is_file()
    assert GRAPH_PATH.is_file()
    assert CORPUS_PATH.is_file()
    assert claim_baseline_path(datasets_root=DATASETS_ROOT) == CLAIM_PATH
    assert boundary_baseline_path(LOGIC_ROOT) == BOUNDARY_PATH
    assert graph_baseline_path(datasets_root=DATASETS_ROOT) == GRAPH_PATH
    assert default_manifest_path() == CORPUS_PATH
    assert default_baseline_join_path(datasets_root=DATASETS_ROOT) == JOIN_PATH
    assert DEFAULT_BASELINE_RELATIVE_PATH.endswith("baseline_join.json")


# ---------------------------------------------------------------------------
# CapabilityLifecycle@1
# ---------------------------------------------------------------------------


def test_capability_lifecycle_publishes_distinct_maturity_rules() -> None:
    lifecycle = build_capability_lifecycle()
    validate_capability_lifecycle(lifecycle)

    assert lifecycle["interface"] == CAPABILITY_LIFECYCLE_INTERFACE
    assert lifecycle["schema_version"] == CAPABILITY_LIFECYCLE_SCHEMA
    assert lifecycle["stages"] == list(LIFECYCLE_STAGES)
    assert set(lifecycle["stage_evidence_obligations"]) == set(LIFECYCLE_STAGES)
    for stage, obligation in STAGE_EVIDENCE_OBLIGATIONS.items():
        assert lifecycle["stage_evidence_obligations"][stage] == obligation
        assert obligation  # non-empty evidence obligation

    policy = lifecycle["authority_policy"]
    assert policy["authority_is_not_lifecycle"] is True
    assert policy["executable_does_not_imply_kernel_authority"] is True
    assert policy["advisory_never_promotes_to_kernel"] is True

    # Declaration / parse / compile / execute / replay / authority stay distinct.
    for left, right in NON_CONFLATABLE_PAIRS:
        if right == "authority":
            with pytest.raises(BaselineV2Error, match="conflated|authority"):
                assert_stages_not_conflated(left, right)
        else:
            with pytest.raises(BaselineV2Error, match="conflated|conflicting"):
                assert_stages_not_conflated(left, right)

    # Same stage is fine.
    assert_stages_not_conflated("executable", "executable")


def test_capability_lifecycle_rejects_stage_vocabulary_drift() -> None:
    lifecycle = build_capability_lifecycle()
    drifted = copy.deepcopy(lifecycle)
    drifted["stages"] = list(LIFECYCLE_STAGES) + ["almost_executable"]
    with pytest.raises(BaselineV2Error, match="stages vocabulary"):
        validate_capability_lifecycle(drifted)

    missing = copy.deepcopy(lifecycle)
    missing["stage_evidence_obligations"] = dict(missing["stage_evidence_obligations"])
    del missing["stage_evidence_obligations"]["executable"]
    with pytest.raises(BaselineV2Error, match="evidence obligation"):
        validate_capability_lifecycle(missing)


# ---------------------------------------------------------------------------
# Successful join
# ---------------------------------------------------------------------------


def test_join_seals_wave2_baseline_without_drift() -> None:
    before = {
        path: path.read_bytes()
        for path in (CLAIM_PATH, BOUNDARY_PATH, GRAPH_PATH, CORPUS_PATH)
    }

    receipt = join_baseline_v2(datasets_root=DATASETS_ROOT, verify_live=True)
    validate_baseline_join(receipt)

    assert receipt["interface"] == LOGIC_RUNTIME_BASELINE_INTERFACE
    assert receipt["schema_version"] == LOGIC_RUNTIME_BASELINE_SCHEMA
    assert receipt["task_id"] == TASK_ID
    assert receipt["goal_id"] == GOAL_ID
    assert receipt["program_id"] == PROGRAM_ID
    assert set(receipt["artifacts"]) == set(ARTIFACT_KEYS)

    source = receipt["source_identity"]
    assert source["program_id"] == PROGRAM_ID
    assert source["goal_id"] == SOURCE_GOAL_ID
    assert source["consistent"] is True
    assert source["tasks"]["claim_runtime_audit"] == "LFP2-001"
    assert source["tasks"]["raw_boundary_inventory"] == "LFP2-002"
    assert source["tasks"]["reachable_capability_graph"] == "LFP2-003"
    assert source["tasks"]["conformance_corpus"] == "LFP2-004"

    artifacts = receipt["artifacts"]
    assert artifacts["claim_runtime_audit"]["interface"] == (
        LOGIC_CLAIM_RUNTIME_AUDIT_INTERFACE
    )
    assert artifacts["raw_boundary_inventory"]["interface"] == (
        RAW_LOGIC_BOUNDARY_INVENTORY_INTERFACE
    )
    assert artifacts["reachable_capability_graph"]["interface"] == (
        REACHABLE_CAPABILITY_GRAPH_INTERFACE
    )
    assert artifacts["conformance_corpus"]["interface"] == (
        LOGIC_CONFORMANCE_CORPUS_INTERFACE
    )
    for key in ARTIFACT_KEYS:
        assert artifacts[key]["content_digest"]
        assert artifacts[key]["goal_id"] == SOURCE_GOAL_ID

    lifecycle = receipt["capability_lifecycle"]
    assert lifecycle["interface"] == CAPABILITY_LIFECYCLE_INTERFACE
    assert lifecycle["stages"] == list(LIFECYCLE_STAGES)

    gaps = receipt["gaps"]
    assert isinstance(gaps, list)
    assert receipt["gap_summary"]["gap_count"] == len(gaps)
    assert receipt["gap_summary"]["each_gap_has_one_owner"] is True
    assert receipt["gap_summary"]["each_gap_has_evidence_obligation"] is True

    seen_ids: set[str] = set()
    for gap in gaps:
        assert gap["gap_id"]
        assert gap["owner"]
        assert gap["evidence_obligation"]
        assert gap["gap_id"] not in seen_ids
        seen_ids.add(gap["gap_id"])

    acceptance = receipt["acceptance"]
    assert acceptance["conflicting_claims_fail_closed"] is True
    assert acceptance["each_reachable_gap_has_one_owner"] is True
    assert acceptance["each_reachable_gap_has_evidence_obligation"] is True
    assert acceptance["lifecycle_stages_not_conflated"] is True
    assert acceptance["authority_distinct_from_lifecycle"] is True
    assert acceptance["source_identity_consistent"] is True
    assert acceptance["unsupported_cartesian_cells_are_not_work"] is True

    # Join is side-effect free against sealed input artifacts.
    after = {
        path: path.read_bytes()
        for path in (CLAIM_PATH, BOUNDARY_PATH, GRAPH_PATH, CORPUS_PATH)
    }
    assert before == after

    again = join_baseline_v2(datasets_root=DATASETS_ROOT, verify_live=True)
    assert again["content_digest"] == receipt["content_digest"]
    assert again["gap_summary"] == receipt["gap_summary"]


def test_each_reachable_gap_has_one_owner_and_evidence_obligation() -> None:
    receipt = join_baseline_v2(datasets_root=DATASETS_ROOT, verify_live=True)
    owners = {gap["owner"] for gap in receipt["gaps"]}
    assert owners  # at least one owner appears
    # Claim gaps (if any) keep LFP2-001; boundary extension gaps map to LFP2-006.
    for gap in receipt["gaps"]:
        assert gap["owner"].startswith("LFP2-")
        assert gap["evidence_obligation"]
        assert gap["source"] in {
            "claim_audit",
            "raw_boundary",
            "reachable_graph",
            "corpus",
        }

    # Reconstruct collectors and re-assert uniqueness.
    claim = build_default_audit(root=DATASETS_ROOT)
    graph = build_default_graph()
    boundary = json.loads(BOUNDARY_PATH.read_text(encoding="utf-8"))
    collected = (
        collect_claim_gaps(claim)
        + collect_boundary_gaps(boundary)
        + collect_graph_work_gaps(graph)
    )
    assert_unique_gap_owners(collected)


def test_claim_conflict_detection_rejects_duplicate_lifecycle() -> None:
    report = build_default_audit(root=DATASETS_ROOT)
    detect_claim_conflicts(report)  # sealed report is consistent

    if not report.claims:
        pytest.skip("no claims to conflict")
    first = report.claims[0]
    from ipfs_datasets_py.logic.conformance.claim_runtime_audit import (
        ClaimLifecycleStage,
    )

    class _ConflictingReport:
        claims = (
            first,
            type(
                "Row",
                (),
                {
                    "claim_id": first.claim_id,
                    "lifecycle_stage": (
                        ClaimLifecycleStage.EXECUTABLE
                        if first.lifecycle_stage
                        is not ClaimLifecycleStage.EXECUTABLE
                        else ClaimLifecycleStage.DECLARED
                    ),
                    "authority_ceiling": first.authority_ceiling,
                    "authority_bearing": False,
                    "executable_claim": False,
                    "gaps": (),
                    "kind": first.kind,
                    "subject": dict(first.subject),
                },
            )(),
        )

    with pytest.raises(BaselineV2Error, match="conflicting claims"):
        detect_claim_conflicts(_ConflictingReport())  # type: ignore[arg-type]


def test_assert_unique_gap_owners_rejects_multi_owner() -> None:
    gaps = (
        BaselineGap(
            gap_id="gap:demo",
            source=GapSource.CLAIM_AUDIT,
            owner="LFP2-001",
            evidence_obligation="non_mock_runner_execution_receipt",
            subject_id="provider:z3",
            stage="executable",
        ),
        BaselineGap(
            gap_id="gap:demo",
            source=GapSource.CLAIM_AUDIT,
            owner="LFP2-099",
            evidence_obligation="non_mock_runner_execution_receipt",
            subject_id="provider:z3",
            stage="executable",
        ),
    )
    with pytest.raises(BaselineV2Error, match="multiple owners"):
        assert_unique_gap_owners(gaps)


def test_assert_unique_gap_owners_rejects_missing_obligation() -> None:
    with pytest.raises(BaselineV2Error, match="evidence_obligation|owner"):
        BaselineGap(
            gap_id="gap:empty",
            source=GapSource.CORPUS,
            owner="LFP2-004",
            evidence_obligation="",
            subject_id="x",
            stage="declared",
        )


# ---------------------------------------------------------------------------
# Drift rejection
# ---------------------------------------------------------------------------


def test_join_rejects_schema_drift(tmp_path: Path) -> None:
    drifted = tmp_path / "claim_runtime_audit.json"
    payload = json.loads(CLAIM_PATH.read_text(encoding="utf-8"))
    payload["schema_version"] = "logic-claim-runtime-audit-report/v0-drift"
    drifted.write_text(
        json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    with pytest.raises(BaselineV2Error, match="schema drift|load failure"):
        join_baseline_v2(
            claim_path=drifted,
            datasets_root=DATASETS_ROOT,
            verify_live=False,
        )


def test_join_rejects_interface_drift(tmp_path: Path) -> None:
    drifted = tmp_path / "raw_boundary_inventory.json"
    payload = json.loads(BOUNDARY_PATH.read_text(encoding="utf-8"))
    payload["interface"] = "RawLogicBoundaryInventory@0-drift"
    drifted.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with pytest.raises(BaselineV2Error, match="interface drift|load failure"):
        join_baseline_v2(
            boundary_path=drifted,
            datasets_root=DATASETS_ROOT,
            verify_live=False,
        )


def test_join_rejects_source_identity_drift(tmp_path: Path) -> None:
    drifted = tmp_path / "reachable_capability_graph.json"
    payload = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    payload["program_id"] = "ipfs-datasets-logic-family-parser-v1"
    drifted.write_text(
        json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    with pytest.raises(BaselineV2Error, match="source identity|program_id"):
        join_baseline_v2(
            graph_path=drifted,
            datasets_root=DATASETS_ROOT,
            verify_live=False,
        )


def test_join_rejects_task_revision_drift(tmp_path: Path) -> None:
    drifted = tmp_path / "claim_runtime_audit.json"
    payload = json.loads(CLAIM_PATH.read_text(encoding="utf-8"))
    payload["task_id"] = "LFP2-999"
    drifted.write_text(
        json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    with pytest.raises(BaselineV2Error, match="revision drift|task_id"):
        join_baseline_v2(
            claim_path=drifted,
            datasets_root=DATASETS_ROOT,
            verify_live=False,
        )


def test_join_rejects_corpus_schema_drift(tmp_path: Path) -> None:
    drifted = tmp_path / "manifest.json"
    payload = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    payload["schema_version"] = "logic-conformance-corpus/v0-drift"
    drifted.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with pytest.raises(BaselineV2Error, match="schema drift|load failure"):
        join_baseline_v2(
            corpus_path=drifted,
            datasets_root=DATASETS_ROOT,
            verify_live=False,
        )


def test_validate_receipt_rejects_digest_drift() -> None:
    receipt = join_baseline_v2(datasets_root=DATASETS_ROOT, verify_live=False)
    validate_baseline_join(receipt)
    mutated = copy.deepcopy(receipt)
    mutated["content_digest"] = "sha256:" + ("0" * 64)
    with pytest.raises(BaselineV2Error, match="content_digest|digest"):
        validate_baseline_join(mutated)


def test_validate_receipt_rejects_gap_without_owner() -> None:
    receipt = join_baseline_v2(datasets_root=DATASETS_ROOT, verify_live=False)
    mutated = copy.deepcopy(receipt)
    assert mutated["gaps"], "join must surface at least one reachable gap"
    mutated["gaps"] = list(mutated["gaps"])
    first = dict(mutated["gaps"][0])
    first["owner"] = ""
    mutated["gaps"][0] = first
    # Digest no longer matches; either owner or digest check fails closed.
    with pytest.raises(BaselineV2Error):
        validate_baseline_join(mutated)


def test_silent_bypass_boundary_fails_closed() -> None:
    payload = json.loads(BOUNDARY_PATH.read_text(encoding="utf-8"))
    rows = list(payload.get("boundaries") or [])
    rows.append(
        {
            "boundary_id": "raw_string:evil.py#silent",
            "discovery": "curated",
            "disposition": "silent_bypass",
            "executable": True,
            "family_hints": [],
            "gates_crossed": [],
            "kind": "raw_string",
            "notes": "injected silent bypass",
            "path": "evil.py",
            "qualname": "silent",
            "role": "ingress",
            "symbol": "silent",
        }
    )
    payload["boundaries"] = rows
    with pytest.raises(BaselineV2Error, match="silent"):
        collect_boundary_gaps(payload)


# ---------------------------------------------------------------------------
# Sealed artifact + CLI
# ---------------------------------------------------------------------------


def test_write_and_seal_baseline_join(tmp_path: Path) -> None:
    receipt = build_default_baseline_join(
        datasets_root=DATASETS_ROOT, verify_live=True
    )
    full_out = tmp_path / "baseline_join_full.json"
    write_baseline_join(receipt, full_out, compact=False)
    loaded_full = load_baseline_join(full_out)
    assert loaded_full["content_digest"] == receipt["content_digest"]
    assert loaded_full["interface"] == LOGIC_RUNTIME_BASELINE_INTERFACE

    compact_out = tmp_path / "baseline_join_compact.json"
    write_baseline_join(receipt, compact_out, compact=True)
    sealed_bytes = json.loads(compact_out.read_text(encoding="utf-8"))
    assert is_compact_baseline_join_seal(sealed_bytes)
    assert "gaps" not in sealed_bytes
    assert "artifacts" not in sealed_bytes
    loaded_compact = load_baseline_join(
        compact_out, datasets_root=DATASETS_ROOT, verify_live=True
    )
    assert loaded_compact["content_digest"] == receipt["content_digest"]
    assert loaded_compact["gap_summary"] == receipt["gap_summary"]

    rendered = render_baseline_join_json(receipt)
    assert rendered.endswith("\n")
    assert json.loads(rendered)["task_id"] == TASK_ID


def test_sealed_baseline_join_matches_live_materialization(tmp_path: Path) -> None:
    """Materialize, seal, and verify the owned Wave-2 baseline join output."""

    before = JOIN_PATH.read_bytes()
    receipt = join_baseline_v2(datasets_root=DATASETS_ROOT, verify_live=True)
    candidate = tmp_path / "baseline_join.json"
    write_baseline_join(receipt, candidate, compact=True)
    assert candidate.read_bytes() == before

    on_disk = json.loads(candidate.read_text(encoding="utf-8"))
    assert is_compact_baseline_join_seal(on_disk)
    assert on_disk["interface"] == LOGIC_RUNTIME_BASELINE_INTERFACE
    assert on_disk["task_id"] == TASK_ID
    assert on_disk["goal_id"] == GOAL_ID
    assert on_disk["program_id"] == PROGRAM_ID
    assert on_disk["materialization"] == MATERIALIZATION_TARGET
    assert on_disk["capability_lifecycle"]["interface"] == CAPABILITY_LIFECYCLE_INTERFACE
    assert on_disk["acceptance"]["conflicting_claims_fail_closed"] is True
    assert on_disk["acceptance"]["each_reachable_gap_has_one_owner"] is True
    assert on_disk["lifecycle_stages"] == list(LIFECYCLE_STAGES)
    assert "gaps" not in on_disk
    assert "artifacts" not in on_disk

    # Compact seal re-materializes the full owned gap surface.
    live = load_baseline_join(candidate, datasets_root=DATASETS_ROOT)
    assert live["content_digest"] == receipt["content_digest"]
    assert live["gap_summary"] == receipt["gap_summary"]
    assert live["gap_summary"]["each_gap_has_one_owner"] is True
    for gap in live["gaps"]:
        assert gap["owner"]
        assert gap["evidence_obligation"]

    resealed = ensure_baseline_join_seal(candidate, datasets_root=DATASETS_ROOT)
    assert resealed["content_digest"] == receipt["content_digest"]
    assert resealed["gap_summary"] == receipt["gap_summary"]

    checked_in = ensure_baseline_join_seal(JOIN_PATH, datasets_root=DATASETS_ROOT)
    assert checked_in["content_digest"] == receipt["content_digest"]
    assert JOIN_PATH.read_bytes() == before


def test_cli_writes_baseline_join(tmp_path: Path) -> None:
    target = tmp_path / "baseline_join.json"
    exit_code = baseline_v2_main(
        ["--root", str(DATASETS_ROOT), "--output", str(target)]
    )
    assert exit_code == 0
    assert target.is_file()
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["interface"] == LOGIC_RUNTIME_BASELINE_INTERFACE
    assert payload["materialization"] == MATERIALIZATION_TARGET
    assert is_compact_baseline_join_seal(payload)
    validate_baseline_join(payload)


def test_ensure_baseline_join_seal_detects_drift(tmp_path: Path) -> None:
    receipt = join_baseline_v2(datasets_root=DATASETS_ROOT, verify_live=False)
    target = tmp_path / "baseline_join.json"
    write_baseline_join(receipt, target, compact=True)
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["joined_content_digest"] = "sha256:" + ("0" * 64)
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(BaselineV2Error, match="digest|drift"):
        load_baseline_join(
            target, datasets_root=DATASETS_ROOT, verify_live=False
        )
    with pytest.raises(BaselineV2Error, match="digest|drift"):
        ensure_baseline_join_seal(
            target, datasets_root=DATASETS_ROOT, verify_live=False
        )


def test_compact_seal_dict_is_self_validating() -> None:
    with pytest.raises(BaselineV2Error, match="full baseline join receipt"):
        to_baseline_join_seal_dict()

    receipt = join_baseline_v2(datasets_root=DATASETS_ROOT, verify_live=False)
    seal = to_baseline_join_seal_dict(receipt)
    validate_baseline_join(seal)
    assert is_compact_baseline_join_seal(seal)
    assert seal["capability_lifecycle"]["stages"] == list(LIFECYCLE_STAGES)

    with pytest.raises(BaselineV2Error, match="already compact"):
        to_baseline_join_seal_dict(seal)


def test_compact_seal_validation_rejects_missing_or_weakened_bindings() -> None:
    receipt = join_baseline_v2(datasets_root=DATASETS_ROOT, verify_live=False)
    seal = to_baseline_join_seal_dict(receipt)

    weakened: list[dict[str, Any]] = []
    missing_digest = copy.deepcopy(seal)
    missing_digest.pop("joined_content_digest")
    weakened.append(missing_digest)

    malformed_digest = copy.deepcopy(seal)
    malformed_digest["joined_content_digest"] = "sha256:invalid"
    weakened.append(malformed_digest)

    missing_summary = copy.deepcopy(seal)
    missing_summary.pop("gap_summary")
    weakened.append(missing_summary)

    incomplete_summary = copy.deepcopy(seal)
    incomplete_summary["gap_summary"].pop("owner_histogram")
    weakened.append(incomplete_summary)

    false_summary_acceptance = copy.deepcopy(seal)
    false_summary_acceptance["gap_summary"]["each_gap_has_one_owner"] = False
    weakened.append(false_summary_acceptance)

    wrong_histogram = copy.deepcopy(seal)
    wrong_histogram["gap_summary"]["owner_histogram"]["LFP2-001"] += 1
    weakened.append(wrong_histogram)

    wrong_source_task = copy.deepcopy(seal)
    wrong_source_task["source_identity"]["tasks"]["claim_runtime_audit"] = "LFP2-999"
    weakened.append(wrong_source_task)

    wrong_interface = copy.deepcopy(seal)
    wrong_interface["artifact_interfaces"]["claim_runtime_audit"] = "Other@1"
    weakened.append(wrong_interface)

    wrong_root = copy.deepcopy(seal)
    wrong_root["roots"]["datasets_root"] = "/absolute/checkout"
    weakened.append(wrong_root)

    false_acceptance = copy.deepcopy(seal)
    false_acceptance["acceptance"]["unsupported_cartesian_cells_are_not_work"] = False
    weakened.append(false_acceptance)

    for payload in weakened:
        with pytest.raises(BaselineV2Error):
            validate_baseline_join(payload)


def test_compact_writer_rejects_an_already_compact_seal(tmp_path: Path) -> None:
    receipt = join_baseline_v2(datasets_root=DATASETS_ROOT, verify_live=False)
    seal = to_baseline_join_seal_dict(receipt)

    with pytest.raises(BaselineV2Error, match="already compact"):
        write_baseline_join(seal, tmp_path / "nested.json", compact=True)


def test_claim_artifact_live_verification_rejects_resealed_semantic_drift(
    tmp_path: Path,
) -> None:
    payload = build_default_audit(root=DATASETS_ROOT).to_baseline_dict()
    vampire = next(
        claim for claim in payload["claims"] if claim["claim_id"] == "provider:vampire"
    )
    vampire["support"] = "bounded"
    vampire["authority_ceiling"] = "advisory"
    tampered = LogicClaimRuntimeAuditReport.from_dict(payload).to_baseline_dict()
    target = tmp_path / "claim_runtime_audit.json"
    target.write_text(json.dumps(tampered) + "\n", encoding="utf-8")

    with pytest.raises(BaselineV2Error, match="exact live materialization"):
        load_claim_artifact(
            target,
            verify_live=True,
            datasets_root=DATASETS_ROOT,
        )
