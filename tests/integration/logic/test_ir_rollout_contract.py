"""Executable documentation contract for the reviewed IR-family rollout."""

from __future__ import annotations

from pathlib import Path
import re

from ipfs_datasets_py.logic.intent_ir.evaluation.benchmark import (
    INTENT_FORMALIZATION_BENCHMARK_REPORT_SCHEMA_VERSION,
    IntentBenchmarkArm,
)
from ipfs_datasets_py.logic.intent_ir.source_adapters.policy import (
    AllowedUseDecision,
)
from ipfs_datasets_py.logic.intent_ir.source_adapters.snapshot import (
    SKILLCENTER_SNAPSHOT_SCHEMA_VERSION,
)
from ipfs_datasets_py.logic.ir_core.artifacts import (
    IR_ARTIFACT_MANIFEST_SCHEMA_VERSION,
)
from ipfs_datasets_py.logic.ir_core.protocols import (
    BACKEND_CAPABILITIES_SCHEMA_VERSION,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
ARCHITECTURE_PATH = (
    REPO_ROOT / "docs/architecture/IR_FAMILY_REFACTOR_AND_INTENT_IR_PLAN.md"
)
OPERATIONS_PATH = REPO_ROOT / "docs/guides/IR_FAMILY_OPERATIONS.md"
MIGRATION_PATH = (
    REPO_ROOT / "docs/security_verification/SECURITY_IR_MIGRATION.md"
)

EXPECTED_STAGES = ("off", "shadow", "assist", "canary")
EXPECTED_ARMS = (
    "deterministic_only",
    "intent_from_scratch",
    "legal_encoder_transfer",
)
HARD_ZERO_GATES = (
    "false_proof_count",
    "false_completion_count",
    "authority_violation_count",
    "leakage_count",
)


def _read(path: Path) -> str:
    assert path.is_file(), f"required rollout document is missing: {path}"
    return path.read_text(encoding="utf-8")


def _section(document: str, heading: str) -> str:
    pattern = re.compile(
        rf"^##+ {re.escape(heading)}\s*$\n(?P<body>.*?)(?=^##+ |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(document)
    assert match is not None, f"missing section: {heading}"
    return match.group("body")


def _table_rows(section: str) -> tuple[tuple[str, ...], ...]:
    rows: list[tuple[str, ...]] = []
    for line in section.splitlines():
        if not line.startswith("|"):
            continue
        cells = tuple(cell.strip() for cell in line.strip().strip("|").split("|"))
        if not cells or all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        rows.append(cells)
    assert rows, "expected a Markdown table"
    return tuple(rows)


def _unquote(value: str) -> str:
    return value.strip().strip("`").strip("*").strip()


def _squash(value: str) -> str:
    return " ".join(value.split())


def test_required_rollout_documents_exist_and_cross_reference_each_other() -> None:
    architecture = _read(ARCHITECTURE_PATH)
    operations = _read(OPERATIONS_PATH)
    migration = _read(MIGRATION_PATH)

    assert "Interface: `IRFamilyRollout@1`" in operations
    assert "Interface: `SecurityIRMigration@1`" in migration
    assert "docs/guides/IR_FAMILY_OPERATIONS.md" in architecture
    assert "docs/security_verification/SECURITY_IR_MIGRATION.md" in architecture
    assert "IR_FAMILY_REFACTOR_AND_INTENT_IR_PLAN.md" in operations
    assert "SECURITY_IR_MIGRATION.md" in operations
    assert "security_ir_v1_compatibility.md" in migration


def test_rollout_stage_contract_is_ordered_fail_closed_and_candidate_only() -> None:
    architecture = _read(ARCHITECTURE_PATH)
    operations = _read(OPERATIONS_PATH)

    architecture_rows = _table_rows(
        _section(architecture, "Rollout gates")
    )
    operations_rows = _table_rows(_section(operations, "Stage contract"))
    architecture_stages = tuple(
        _unquote(row[0])
        for row in architecture_rows[1:]
        if _unquote(row[0]) in EXPECTED_STAGES
    )
    operations_stages = tuple(
        _unquote(row[0])
        for row in operations_rows[1:]
        if _unquote(row[0]) in EXPECTED_STAGES
    )

    assert architecture_stages == EXPECTED_STAGES
    assert operations_stages == EXPECTED_STAGES
    assert "Default stage: `off`" in operations
    assert "Stages are strictly ordered `off -> shadow -> assist -> canary`" in operations
    assert "There is no automatic transition" in architecture
    assert "Unknown stage values fail to `off`" in operations

    stage_contract = _squash(_section(operations, "Stage contract")).lower()
    assert "canonical ir" in stage_contract
    assert "any proof, trust, license, permission, or execution authority" in stage_contract
    assert "manifest-bounded allowlisted cohort" in stage_contract
    assert "confidence/retrieval as authority" in stage_contract


def test_license_snapshot_solver_and_source_group_gates_fail_closed() -> None:
    operations = _read(OPERATIONS_PATH)

    license_gate = _squash(
        _section(operations, "License and hostile-input gate")
    )
    documented_decisions = {
        decision.value for decision in AllowedUseDecision
    }
    assert documented_decisions <= set(re.findall(r"`([^`]+)`", license_gate))
    assert "human-approved allowlist" in license_gate
    assert "Unknown, absent, contradictory" in license_gate
    assert "no rollout stage executes, imports, or installs" in license_gate

    snapshot_gate = _section(operations, "Snapshot pinning gate")
    assert "SkillCenterSnapshotCache" in snapshot_gate
    assert "SkillCenterSnapshot" in snapshot_gate
    for required_binding in (
        "full immutable dataset revision",
        "exact repository filename",
        "expected size",
        "expected SHA-256",
        "GraphRAG",
        "embedding",
        "checkpoint",
    ):
        assert required_binding in snapshot_gate
    assert "`main`" in snapshot_gate
    assert "stale alias" in snapshot_gate

    solver_gate = _squash(_section(operations, "Solver capability gate"))
    assert "BackendCapabilities" in solver_gate
    assert "side-effect free" in solver_gate
    assert "logic family and `QueryKind`" in solver_gate
    assert "availability probe succeeds" in solver_gate
    assert "Unsupported or unavailable" in solver_gate
    assert "blocks a required proof" in solver_gate
    assert "EvidenceGateResult" in solver_gate
    assert "PolicyDecision" in solver_gate

    split_gate = _section(operations, "Source-group split and retrieval gate")
    for group_key in (
        "primary_source_id",
        "source repository and document",
        "exact content digest and near-duplicate family",
        "generation prompt/model family",
        "source revision/time boundary",
    ):
        assert group_key in split_gate
    assert "never random rows" in split_gate
    assert "All variants of a family remain in one partition" in split_gate
    assert "validate_retrieval_partition_fence" in split_gate
    assert "`leakage_count > 0` and blocks promotion" in split_gate

    # The prose is bound to implemented wire contracts, not new spellings.
    assert SKILLCENTER_SNAPSHOT_SCHEMA_VERSION == "skillcenter-snapshot/v1"
    assert BACKEND_CAPABILITIES_SCHEMA_VERSION == "proof-backend-capabilities/v1"


def test_benchmark_thresholds_are_numeric_paired_and_hard_zero() -> None:
    architecture = _read(ARCHITECTURE_PATH)
    operations = _read(OPERATIONS_PATH)
    benchmark = _section(operations, "Benchmark and promotion thresholds")

    assert INTENT_FORMALIZATION_BENCHMARK_REPORT_SCHEMA_VERSION in benchmark
    documented_arms = tuple(
        value
        for value in re.findall(r"`([^`]+)`", benchmark)
        if value in EXPECTED_ARMS
    )
    assert documented_arms[:3] == EXPECTED_ARMS
    assert tuple(arm.value for arm in IntentBenchmarkArm) == EXPECTED_ARMS

    threshold_rows = {
        _unquote(row[0]): row[1]
        for row in _table_rows(benchmark)[1:]
    }
    assert "`+0.02` absolute" in threshold_rows["material improvement"]
    assert "`0.01` absolute" in threshold_rows["bounded regression"]
    assert "`0.95`" in threshold_rows["bounded regression"]
    assert "`grounding_accuracy == 1.0`" in threshold_rows["structural validity"]
    assert "`round_trip_accuracy == 1.0`" in threshold_rows["structural validity"]
    assert "`semantic_mutation_rate == 0.0`" in threshold_rows["structural validity"]

    for gate in HARD_ZERO_GATES:
        assert f"`{gate} == 0`" in benchmark
        assert f"`{gate} == 0`" in architecture
    assert "The four zero gates are hard gates" in benchmark
    assert "may waive them" in benchmark
    assert "same split, graph, and\nembedding snapshots" in benchmark
    assert "clean rerun with the same pinned inputs" in benchmark


def test_artifact_promotion_requires_immutable_lineage_and_review() -> None:
    architecture = _read(ARCHITECTURE_PATH)
    operations = _read(OPERATIONS_PATH)
    migration = _read(MIGRATION_PATH)

    lifecycle = _squash(_section(operations, "Artifact lifecycle"))
    assert "`runs/<run-id>/`" in lifecycle
    assert "Never write directly to `promoted/`" in lifecycle
    assert "Recompute all digests" in lifecycle
    assert "independent reviewer" in lifecycle
    assert "content-addressed artifact manifest" in lifecycle
    assert "never mutate an existing promoted object" in lifecycle
    for forbidden in ("`latest`", "`-new`", "unmanifested path"):
        assert forbidden in lifecycle
    assert "Do not delete or rewrite failed evidence" in lifecycle

    authority = _squash(_section(migration, "Artifact layout and authority"))
    assert "`authority_selected == false`" in authority
    assert "`authority_decisions_made == 0`" in authority
    assert "is not a review decision" in authority
    assert IR_ARTIFACT_MANIFEST_SCHEMA_VERSION in authority
    assert "independent reviewer and rollback owner" in authority
    assert "only\nmanifested immutable artifacts move to `promoted/`" in architecture


def test_security_deprecation_window_and_removal_gates_are_explicit() -> None:
    migration = _read(MIGRATION_PATH)
    window = _section(migration, "Deprecation window")
    removal = _section(migration, "Removal gates")

    assert re.search(
        r"two\s+consecutive minor releases and 180 days .*whichever ends later",
        window,
        re.DOTALL,
    )
    assert "replacement import" in window
    assert "earliest calendar removal date" in window
    assert "must not change serialization or exit\ncodes" in window
    assert "Absence of telemetry is\nnot evidence of zero use" in window

    assert "30 consecutive days of zero observed use" in removal
    assert "telemetry health demonstrated" in removal
    assert "legacy golden-reader/export" in removal
    assert "rollback rehearsal" in removal
    assert "security reviewer and release owner explicitly approve" in removal
    assert "Serialized legacy v1 artifacts are not deleted" in removal


def test_monitoring_stop_conditions_and_rollback_are_fail_closed() -> None:
    operations = _read(OPERATIONS_PATH)
    migration = _read(MIGRATION_PATH)

    monitoring = _section(operations, "Monitoring and stop conditions")
    for signal in (
        "license-policy counts",
        "retrieval-fence violations",
        "false proofs",
        "false completions",
        "authority violations",
        "backend unavailable",
        "proof-receipt integrity failure",
        "p50/p95 latency",
        "Security legacy/v1 compatibility",
        "attempted source command",
    ):
        assert signal in monitoring
    assert "automatically stop new canary admission" in monitoring
    assert "Missing telemetry is a\nstop condition" in monitoring

    rollback = _section(operations, "Rollback and incident response")
    ordered_actions = (
        "atomically route new work to `off`",
        "stop new advisor/canary admission",
        "revoke the active rollout manifest",
        "quarantine incomplete",
        "preserve logs",
        "verify deterministic-only health",
        "notify the data steward",
        "require a new root-cause record",
    )
    positions = tuple(rollback.index(action) for action in ordered_actions)
    assert positions == tuple(sorted(positions))
    assert "do not delete" in rollback
    assert "fail requests closed" in rollback

    migration_rollback = _section(migration, "Rollback")
    assert "non-destructive" in migration_rollback
    assert "revoke the active cutover/promotion manifest without deleting it" in migration_rollback
    assert "frozen legacy facade" in migration_rollback


def test_human_approval_decisions_are_complete_and_cannot_waive_safety() -> None:
    architecture = _read(ARCHITECTURE_PATH)
    operations = _read(OPERATIONS_PATH)
    migration = _read(MIGRATION_PATH)

    architecture_decisions = _section(
        architecture, "Decisions to approve before the pilot expands"
    )
    operations_decisions = _section(operations, "Decisions requiring human approval")
    joined = "\n".join(
        (architecture_decisions, operations_decisions, _section(migration, "Human approvals"))
    ).lower()

    for decision in (
        "license allowlist",
        "source domain",
        "secret/pii",
        "ontology",
        "formal view",
        "cid/multicodec",
        "solver/backend/version",
        "gold-set",
        "source-group split",
        "benchmark",
        "resource budget",
        "`assist`",
        "`canary`",
        "artifact promotion",
        "incident",
        "legacy shim",
    ):
        assert decision in joined
    assert "may not create, infer, or waive" in architecture_decisions
    assert "without waiving the zero" in architecture_decisions
    assert "may not manufacture an approval" in operations_decisions


def test_documented_preflight_paths_and_commands_are_current() -> None:
    operations = _read(OPERATIONS_PATH)
    preflight = _section(operations, "Preflight")
    documented_tests = re.findall(r"(tests/[A-Za-z0-9_./-]+\.py)", preflight)

    assert documented_tests
    assert "python -m pytest" in preflight
    for relative_path in documented_tests:
        assert (REPO_ROOT / relative_path).is_file(), relative_path
    assert "repository tree" in preflight
    assert "partial or stale test receipt is not a substitute" in preflight
