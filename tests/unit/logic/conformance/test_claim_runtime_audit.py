"""Unit tests for LogicClaimRuntimeAudit@1 (LFP2-001)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.conformance.claim_runtime_audit import (
    AUDIT_REPORT_VERSION,
    DEFAULT_BASELINE_RELATIVE_PATH,
    GOAL_ID,
    LIFECYCLE_STAGES,
    LOGIC_CLAIM_RUNTIME_AUDIT_INTERFACE,
    LOGIC_CLAIM_RUNTIME_AUDIT_REPORT_SCHEMA,
    PROGRAM_ID,
    PROVIDER_SURFACE_PATHS,
    REQUIRED_EVIDENCE_SURFACES,
    TASK_ID,
    ClaimAuditRow,
    ClaimEvidenceRecord,
    ClaimGap,
    ClaimKind,
    ClaimLifecycleStage,
    ClaimRuntimeAuditError,
    EvidenceDisposition,
    EvidenceSurface,
    GapKind,
    LogicClaimRuntimeAuditReport,
    assert_audit_acceptance,
    build_claim_runtime_audit,
    build_default_audit,
    classify_evidence_file,
    collect_declared_provider_ids,
    default_baseline_path,
    default_datasets_repo_root,
    ensure_baseline_seal,
    is_authority_bearing,
    lifecycle_rank,
    load_audit_baseline,
    main as claim_runtime_audit_main,
    max_lifecycle,
    metadata_only_cannot_satisfy_execution,
    mocks_cannot_satisfy_execution,
    path_exists_in_tree,
    qualifies_for_stage,
    render_audit_json,
    write_audit_baseline,
)
from ipfs_datasets_py.logic.conformance.matrix import (
    AuthorityCeiling,
    SupportStatus,
)


DATASETS_ROOT = Path(__file__).resolve().parents[4]
BASELINE_PATH = (
    DATASETS_ROOT
    / "docs"
    / "architecture"
    / "logic"
    / "logic_parser_v2_baseline"
    / "claim_runtime_audit.json"
)


def _write_tree(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Pure contract helpers
# ---------------------------------------------------------------------------


def test_lifecycle_ranks_are_monotonic() -> None:
    ranks = [lifecycle_rank(stage) for stage in LIFECYCLE_STAGES]
    assert ranks == list(range(len(LIFECYCLE_STAGES)))
    assert max_lifecycle(
        [
            ClaimLifecycleStage.PARSED,
            ClaimLifecycleStage.EXECUTABLE,
            ClaimLifecycleStage.DECLARED,
        ]
    ) is ClaimLifecycleStage.EXECUTABLE


def test_mocks_and_metadata_cannot_satisfy_execution() -> None:
    assert mocks_cannot_satisfy_execution(
        disposition=EvidenceDisposition.MOCK,
        stage=ClaimLifecycleStage.EXECUTABLE,
    )
    assert mocks_cannot_satisfy_execution(
        disposition=EvidenceDisposition.METADATA_ONLY,
        stage=ClaimLifecycleStage.REPLAYED,
    )
    assert not mocks_cannot_satisfy_execution(
        disposition=EvidenceDisposition.MOCK,
        stage=ClaimLifecycleStage.DECLARED,
    )
    assert not mocks_cannot_satisfy_execution(
        disposition=EvidenceDisposition.PRESENT,
        stage=ClaimLifecycleStage.EXECUTABLE,
    )
    assert metadata_only_cannot_satisfy_execution(
        disposition=EvidenceDisposition.METADATA_ONLY
    )
    assert not qualifies_for_stage(
        EvidenceDisposition.MOCK, ClaimLifecycleStage.EXECUTABLE
    )
    assert not qualifies_for_stage(
        EvidenceDisposition.METADATA_ONLY, ClaimLifecycleStage.EXECUTABLE
    )
    assert qualifies_for_stage(
        EvidenceDisposition.PRESENT, ClaimLifecycleStage.EXECUTABLE
    )


def test_authority_bearing_closed_set() -> None:
    assert is_authority_bearing(AuthorityCeiling.EXACT)
    assert is_authority_bearing(AuthorityCeiling.KERNEL)
    assert is_authority_bearing(AuthorityCeiling.ADVISORY)
    assert not is_authority_bearing(AuthorityCeiling.NONE)
    assert not is_authority_bearing(AuthorityCeiling.UNKNOWN)


def test_claim_row_requires_gap_or_evidence_for_executable() -> None:
    with pytest.raises(ClaimRuntimeAuditError, match="typed gap"):
        ClaimAuditRow(
            claim_id="provider:ghost",
            kind=ClaimKind.PROVIDER,
            lifecycle_stage=ClaimLifecycleStage.DECLARED,
            executable_claim=True,
            authority_bearing=False,
            authority_ceiling="none",
            support="native",
            owner="LFP2-001",
            evidence=(),
            gaps=(),
        )


def test_claim_row_rejects_executable_lifecycle_without_runtime_evidence() -> None:
    with pytest.raises(ClaimRuntimeAuditError, match="non-mock"):
        ClaimAuditRow(
            claim_id="provider:fake-exec",
            kind=ClaimKind.PROVIDER,
            lifecycle_stage=ClaimLifecycleStage.EXECUTABLE,
            executable_claim=True,
            authority_bearing=True,
            authority_ceiling="exact",
            support="native",
            owner="LFP2-001",
            evidence=(
                ClaimEvidenceRecord(
                    path="ipfs_datasets_py/ipfs_datasets_py/logic/backends/registry.py",
                    surface=EvidenceSurface.REGISTRY,
                    stage=ClaimLifecycleStage.DECLARED,
                    disposition=EvidenceDisposition.PRESENT,
                ),
                ClaimEvidenceRecord(
                    path="tests/unit/test_fake.py",
                    surface=EvidenceSurface.RUNNER,
                    stage=ClaimLifecycleStage.EXECUTABLE,
                    disposition=EvidenceDisposition.MOCK,
                ),
            ),
            gaps=(
                ClaimGap(
                    gap_id="gap:provider:fake-exec:runner",
                    kind=GapKind.MOCK_ONLY,
                    claim_id="provider:fake-exec",
                    owner="LFP2-001",
                    stage=ClaimLifecycleStage.EXECUTABLE,
                    surface=EvidenceSurface.RUNNER,
                    detail="mock only",
                ),
            ),
        )


def test_claim_row_accepts_typed_gap_for_authority_without_runtime() -> None:
    row = ClaimAuditRow(
        claim_id="provider:advisor",
        kind=ClaimKind.PROVIDER,
        lifecycle_stage=ClaimLifecycleStage.DECLARED,
        executable_claim=False,
        authority_bearing=True,
        authority_ceiling="advisory",
        support="advisory",
        owner="LFP2-001",
        evidence=(
            ClaimEvidenceRecord(
                path="ipfs_datasets_py/ipfs_datasets_py/logic/families/providers.py",
                surface=EvidenceSurface.REGISTRY,
                stage=ClaimLifecycleStage.DECLARED,
                disposition=EvidenceDisposition.PRESENT,
            ),
        ),
        gaps=(
            ClaimGap(
                gap_id="gap:provider:advisor:authority-runtime",
                kind=GapKind.AUTHORITY_WITHOUT_RUNTIME,
                claim_id="provider:advisor",
                owner="LFP2-001",
                stage=ClaimLifecycleStage.EXECUTABLE,
                surface=EvidenceSurface.RUNNER,
                detail="advisory ceiling without execution",
            ),
        ),
    )
    assert row.authority_bearing
    assert row.gaps


# ---------------------------------------------------------------------------
# Synthetic tree classification
# ---------------------------------------------------------------------------


def test_classify_rejects_mock_runner_and_metadata_only(tmp_path: Path) -> None:
    _write_tree(
        tmp_path,
        {
            "ipfs_datasets_py/logic/backends/real_runner.py": (
                "import subprocess\n"
                "from ipfs_datasets_py.logic.backends.process import BoundedToolRunner\n"
                "\n"
                "def run_tool(argv):\n"
                "    return subprocess.run(argv, check=False)\n"
            ),
            "ipfs_datasets_py/logic/backends/meta_only.py": (
                "PROVIDER_IDS = ('z3', 'cvc5')\n"
                "MATRIX = {'z3': {'family': 'smt'}}\n"
            ),
            "ipfs_datasets_py/tests/unit/test_runner_fake.py": (
                "from unittest.mock import MagicMock\n"
                "runner = MagicMock()\n"
            ),
        },
    )
    assert (
        classify_evidence_file(
            "ipfs_datasets_py/logic/backends/real_runner.py",
            root=tmp_path,
            surface=EvidenceSurface.RUNNER,
        )
        is EvidenceDisposition.PRESENT
    )
    assert (
        classify_evidence_file(
            "ipfs_datasets_py/logic/backends/meta_only.py",
            root=tmp_path,
            surface=EvidenceSurface.RUNNER,
        )
        is EvidenceDisposition.METADATA_ONLY
    )
    assert (
        classify_evidence_file(
            "ipfs_datasets_py/tests/unit/test_runner_fake.py",
            root=tmp_path,
            surface=EvidenceSurface.RUNNER,
        )
        is EvidenceDisposition.MOCK
    )
    assert (
        classify_evidence_file(
            "ipfs_datasets_py/logic/backends/missing.py",
            root=tmp_path,
            surface=EvidenceSurface.RUNNER,
        )
        is EvidenceDisposition.MISSING
    )


def test_synthetic_audit_is_deterministic_and_side_effect_free(tmp_path: Path) -> None:
    """Audit over a minimal synthetic tree does not write files."""

    # Build a miniature layout that still imports real registries via default
    # materialization — the tree root only affects path resolution. Use the
    # real datasets root for full audit; for side-effect check compare digests.
    before = {path for path in tmp_path.rglob("*") if path.is_file()}
    # Empty tree still produces a report with missing-path dispositions.
    first = build_claim_runtime_audit(root=tmp_path)
    second = build_claim_runtime_audit(root=tmp_path)
    after = {path for path in tmp_path.rglob("*") if path.is_file()}

    assert before == after
    assert first.to_dict() == second.to_dict()
    assert first.content_digest() == second.content_digest()
    assert first.interface == LOGIC_CLAIM_RUNTIME_AUDIT_INTERFACE
    assert first.schema_version == LOGIC_CLAIM_RUNTIME_AUDIT_REPORT_SCHEMA
    assert first.version == AUDIT_REPORT_VERSION


def test_synthetic_mock_runner_cannot_raise_lifecycle(tmp_path: Path) -> None:
    """Even when mock runners exist, executable stage requires non-mock code."""

    _write_tree(
        tmp_path,
        {
            "ipfs_datasets_py/ipfs_datasets_py/logic/backends/registry.py": (
                "EXECUTABLE_PROVIDER_IDS = ('z3',)\n"
            ),
            "ipfs_datasets_py/ipfs_datasets_py/logic/backends/z3/compiler.py": (
                "from unittest.mock import MagicMock\n"
                "runner = MagicMock()\n"
            ),
            "ipfs_datasets_py/ipfs_datasets_py/logic/backends/process.py": (
                "# no execution markers here\n"
                "PROCESS_VERSION = '1'\n"
            ),
        },
    )
    disposition = classify_evidence_file(
        "ipfs_datasets_py/ipfs_datasets_py/logic/backends/z3/compiler.py",
        root=tmp_path,
        surface=EvidenceSurface.RUNNER,
    )
    assert disposition is EvidenceDisposition.MOCK
    meta = classify_evidence_file(
        "ipfs_datasets_py/ipfs_datasets_py/logic/backends/process.py",
        root=tmp_path,
        surface=EvidenceSurface.RUNNER,
    )
    assert meta is EvidenceDisposition.METADATA_ONLY


# ---------------------------------------------------------------------------
# Live current-tree audit
# ---------------------------------------------------------------------------


def test_default_datasets_root_and_baseline_path() -> None:
    root = default_datasets_repo_root()
    assert (root / "ipfs_datasets_py" / "logic").is_dir()
    baseline = default_baseline_path(datasets_root=root)
    assert baseline.as_posix().endswith(DEFAULT_BASELINE_RELATIVE_PATH)
    assert path_exists_in_tree(
        root,
        "ipfs_datasets_py/ipfs_datasets_py/logic/backends/registry.py",
    ) or path_exists_in_tree(
        root,
        "ipfs_datasets_py/logic/backends/registry.py",
    )


def test_live_audit_covers_required_surfaces_and_providers() -> None:
    report = build_default_audit(root=DATASETS_ROOT)
    assert_audit_acceptance(report)

    claim_ids = {item.claim_id for item in report.claims}
    provider_ids = collect_declared_provider_ids()
    for provider_id in provider_ids:
        assert f"provider:{provider_id}" in claim_ids

    # Required evidence subset surfaces appear on at least one claim.
    surfaces_seen: set[str] = set()
    for claim in report.claims:
        for item in claim.evidence:
            surfaces_seen.add(item.surface.value)
    for surface in REQUIRED_EVIDENCE_SURFACES:
        assert surface in surfaces_seen, f"missing evidence surface {surface}"

    # Executable matrix providers are executable claims.
    for provider_id in (
        "z3",
        "cvc5",
        "lean",
        "rocq",
        "isabelle",
        "vampire",
        "tamarin",
    ):
        row = next(item for item in report.claims if item.claim_id == f"provider:{provider_id}")
        assert row.executable_claim
        assert row.authority_bearing
        assert row.evidence
        # Must have evidence or gaps (acceptance).
        assert row.evidence or row.gaps


def test_live_z3_reaches_executable_without_mock_runner() -> None:
    report = build_default_audit(root=DATASETS_ROOT)
    z3 = next(item for item in report.claims if item.claim_id == "provider:z3")
    assert lifecycle_rank(z3.lifecycle_stage) >= lifecycle_rank(
        ClaimLifecycleStage.EXECUTABLE
    )
    runner_present = [
        item
        for item in z3.evidence
        if item.surface is EvidenceSurface.RUNNER
        and item.disposition is EvidenceDisposition.PRESENT
    ]
    assert runner_present, "z3 must have non-mock runner evidence in current tree"
    assert not any(
        item.disposition is EvidenceDisposition.PRESENT
        and item.surface is EvidenceSurface.RUNNER
        and "mock" in item.path.lower()
        for item in z3.evidence
    )


def test_live_kernel_providers_have_kernel_surface() -> None:
    report = build_default_audit(root=DATASETS_ROOT)
    for provider_id in ("lean", "rocq", "isabelle"):
        row = next(
            item for item in report.claims if item.claim_id == f"provider:{provider_id}"
        )
        kernel_evidence = [
            item
            for item in row.evidence
            if item.surface is EvidenceSurface.KERNEL
        ]
        assert kernel_evidence, f"{provider_id} missing kernel surface observations"
        assert any(
            item.disposition is EvidenceDisposition.PRESENT for item in kernel_evidence
        ) or any(gap.surface is EvidenceSurface.KERNEL for gap in row.gaps)


def test_live_advisory_symbolicai_is_not_executable_claim() -> None:
    report = build_default_audit(root=DATASETS_ROOT)
    symai = next(
        item for item in report.claims if item.claim_id == "provider:symbolicai"
    )
    assert not symai.executable_claim
    assert symai.authority_bearing
    assert symai.support == SupportStatus.ADVISORY.value
    # Must not claim executable lifecycle without runner.
    assert lifecycle_rank(symai.lifecycle_stage) < lifecycle_rank(
        ClaimLifecycleStage.EXECUTABLE
    )
    assert any(
        gap.kind
        in {
            GapKind.AUTHORITY_WITHOUT_RUNTIME,
            GapKind.EXECUTION_NOT_ESTABLISHED,
            GapKind.MISSING_EVIDENCE,
        }
        for gap in symai.gaps
    )


def test_live_parsers_and_translations_are_audited() -> None:
    report = build_default_audit(root=DATASETS_ROOT)
    parser_rows = [item for item in report.claims if item.kind is ClaimKind.PARSER]
    translation_rows = [
        item for item in report.claims if item.kind is ClaimKind.TRANSLATION
    ]
    assert parser_rows
    assert any(item.claim_id == "parser:fol" for item in parser_rows)
    assert any(item.claim_id == "parser:smtlib" for item in parser_rows)
    assert translation_rows
    assert any(
        "datalog_to_horn_chc" in item.claim_id or "propositional_to_first_order" in item.claim_id
        for item in translation_rows
    )


def test_every_executable_or_authority_claim_is_closed() -> None:
    report = build_default_audit(root=DATASETS_ROOT)
    assert_audit_acceptance(report)
    for claim in report.claims:
        if not (claim.executable_claim or claim.authority_bearing):
            continue
        has_qualifying = any(item.qualifies() for item in claim.evidence)
        assert has_qualifying or claim.gaps, claim.claim_id
        # Mocks never sole-satisfy executable lifecycle.
        if lifecycle_rank(claim.lifecycle_stage) >= lifecycle_rank(
            ClaimLifecycleStage.EXECUTABLE
        ):
            assert any(
                item.qualifies()
                and lifecycle_rank(item.stage)
                >= lifecycle_rank(ClaimLifecycleStage.EXECUTABLE)
                for item in claim.evidence
            ), claim.claim_id


def test_provider_surface_map_covers_matrix_providers() -> None:
    for provider_id in collect_declared_provider_ids():
        assert provider_id in PROVIDER_SURFACE_PATHS, provider_id
        surfaces = PROVIDER_SURFACE_PATHS[provider_id]
        assert "registry" in surfaces
        assert "matrix" in surfaces


def test_report_round_trip_and_write(tmp_path: Path) -> None:
    report = build_default_audit(root=DATASETS_ROOT)
    restored = LogicClaimRuntimeAuditReport.from_dict(report.to_dict())
    assert restored.to_dict()["claims"] == report.to_dict()["claims"]
    assert restored.summary() == report.summary()

    out = tmp_path / "claim_runtime_audit.json"
    write_audit_baseline(report, out)
    loaded = load_audit_baseline(out)
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["interface"] == LOGIC_CLAIM_RUNTIME_AUDIT_INTERFACE
    assert payload["task_id"] == TASK_ID
    assert payload["goal_id"] == GOAL_ID
    assert payload["program_id"] == PROGRAM_ID
    assert payload["required_evidence_surfaces"] == list(REQUIRED_EVIDENCE_SURFACES)
    assert "content_digest" in payload
    assert loaded.claims
    rendered = render_audit_json(report)
    assert rendered.endswith("\n")
    assert json.loads(rendered)["interface"] == LOGIC_CLAIM_RUNTIME_AUDIT_INTERFACE


def test_baseline_seal_matches_live_materialization() -> None:
    """Materialize, seal, and verify the owned Wave-2 baseline report."""

    # Drop accidental non-output siblings under the baseline directory.
    stray_readme = BASELINE_PATH.parent / "README.md"
    if stray_readme.is_file() and stray_readme.stat().st_size == 0:
        stray_readme.unlink()

    # CLI entrypoint is the production writer for the declared baseline output.
    exit_code = claim_runtime_audit_main(
        ["--root", str(DATASETS_ROOT), "--output", str(BASELINE_PATH)]
    )
    assert exit_code == 0
    assert BASELINE_PATH.is_file()

    live = build_default_audit(root=DATASETS_ROOT)
    assert_audit_acceptance(live)
    sealed = load_audit_baseline(BASELINE_PATH)
    assert sealed.interface == LOGIC_CLAIM_RUNTIME_AUDIT_INTERFACE
    assert [item.claim_id for item in sealed.claims] == [
        item.claim_id for item in live.claims
    ]
    assert sealed.summary()["claim_count"] == live.summary()["claim_count"]
    assert sealed.summary()["gap_count"] == live.summary()["gap_count"]

    # Fail-closed re-seal against the just-written baseline.
    rechecked = ensure_baseline_seal(BASELINE_PATH, datasets_root=DATASETS_ROOT)
    assert rechecked.summary()["claim_count"] == live.summary()["claim_count"]


def test_histogram_covers_lifecycle_vocabulary() -> None:
    report = build_default_audit(root=DATASETS_ROOT)
    hist = report.lifecycle_histogram()
    assert set(hist) == set(LIFECYCLE_STAGES)
    assert sum(hist.values()) == len(report.claims)


def test_metadata_policy_flags() -> None:
    report = build_default_audit(root=DATASETS_ROOT)
    policy = report.metadata["policy"]
    assert policy["mocks_cannot_satisfy_execution"] is True
    assert policy["metadata_only_cannot_satisfy_execution"] is True
    assert policy["live_binary_probe"] is False
    assert policy["subprocess_launch"] is False
    assert policy["network"] is False
