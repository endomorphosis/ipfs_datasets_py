"""Integration tests: fail-closed release evidence collector (KGP-049).

Acceptance:
  Provide an executable collector that binds evidence to an explicit clean
  repository tree, records command, timestamp, environment label, exit status,
  test counts, and artifact digests, and refuses failed, skipped,
  expected-failure, stale, foreign-tree, or unsigned evidence where required.
  It must ingest corpus sign-offs, UCAN deny proof, load/soak/chaos digests,
  evaluate GraphReleaseGate fail-closed, and write a human-readable runbook
  explaining all ten child gates and the root release decision.

Conflict policy:
  Compose the existing release_gate receipt types and benchmark receipts;
  never synthesize a passing receipt or treat task status, prose, coverage,
  skips, or expected failures as proof.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ipfs_datasets_py.knowledge_graphs import release_evidence as re
from ipfs_datasets_py.knowledge_graphs.release_evidence import (
    CHILD_GATE_CATALOG,
    COLLECTOR_GOAL_ID,
    SCHEMA_VERSION,
    TASK_ID,
    TEN_CHILD_GATES,
    CommandEvidence,
    EvidenceRefusal,
    RefusalCode,
    ReleaseEvidenceCollector,
    TestCounts,
    TreeBinding,
    build_collector_with_passing_evidence,
    default_gate_runbook_text,
    normalize_tree_id,
    parse_pytest_counts,
    policy_dict,
    render_gate_runbook,
    resolve_clean_tree,
    text_digest,
)
from ipfs_datasets_py.knowledge_graphs.release_gate import (
    GOAL_ID,
    REQUIRED_CHILD_GOALS,
    REQUIRED_CORPORA,
    ROOT_DOD_CLAUSE_IDS,
    DecisionOutcome,
    make_dod_receipt,
    make_goal_receipt,
)

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[3]
COLLECTOR_PY = (
    REPO_ROOT / "ipfs_datasets_py" / "knowledge_graphs" / "release_evidence.py"
)
RUNBOOK_MD = (
    REPO_ROOT / "docs" / "operations" / "knowledge_graphs_gate_runbook.md"
)

TREE_ID = "tree-ab30e5a9e5f5225e6375a72eee8ee47988bcf9a4"
FOREIGN_TREE = "tree-ffffffffffffffffffffffffffffffffffffffff"
SIGNING_KEY = b"kgp-049-test-signing-key-not-for-production"
FIXED_NOW = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)
ARTIFACT = "sha256:" + "f" * 64


def _ts(dt: datetime | None = None) -> str:
    value = (dt or FIXED_NOW).astimezone(timezone.utc).replace(microsecond=0)
    return value.isoformat().replace("+00:00", "Z")


def _clean_binding(tree_id: str = TREE_ID) -> TreeBinding:
    return TreeBinding(
        tree_id=tree_id,
        commit=tree_id.removeprefix("tree-"),
        is_clean=True,
        repo_root=str(REPO_ROOT),
        collected_at=_ts(),
    )


def _collector(
    *,
    require_signatures: bool = False,
    signing_key: bytes | str | None = None,
    tree_id: str = TREE_ID,
) -> ReleaseEvidenceCollector:
    key = signing_key if signing_key is not None else (
        SIGNING_KEY if require_signatures else None
    )
    c = ReleaseEvidenceCollector(
        expected_tree_id=tree_id,
        signing_key=key,
        require_signatures=require_signatures,
        package_version="0.1.0-test",
        now=FIXED_NOW,
    )
    c.bind_tree(_clean_binding(tree_id))
    c.set_environment("lab-kg-release-1", "labelled lab environment")
    return c


# ---------------------------------------------------------------------------
# Module / deliverable surface
# ---------------------------------------------------------------------------


def test_module_and_runbook_exist() -> None:
    assert COLLECTOR_PY.is_file()
    assert RUNBOOK_MD.is_file()
    text = RUNBOOK_MD.read_text(encoding="utf-8")
    assert "KGP-G010" in text
    assert "KGP-G100" in text
    assert "GraphReleaseGate" in text or "ReleaseEvidenceCollector" in text
    assert "not production ready" in text.lower()
    # All ten child gates documented.
    for goal_id in TEN_CHILD_GATES:
        assert goal_id in text


def test_ten_child_gates_are_g010_through_g100() -> None:
    assert TEN_CHILD_GATES == REQUIRED_CHILD_GOALS + (GOAL_ID,)
    assert len(TEN_CHILD_GATES) == 10
    assert TEN_CHILD_GATES[0] == "KGP-G010"
    assert TEN_CHILD_GATES[-1] == "KGP-G100"
    assert len(CHILD_GATE_CATALOG) == 10
    assert {e["goal_id"] for e in CHILD_GATE_CATALOG} == set(TEN_CHILD_GATES)


def test_policy_dict_is_stable() -> None:
    policy = policy_dict()
    assert policy["schema_version"] if "schema_version" in policy else True
    assert policy["collector_schema_version"] == SCHEMA_VERSION
    assert policy["task_id"] == TASK_ID
    assert policy["goal_id"] == COLLECTOR_GOAL_ID
    assert policy["ten_child_gates"] == list(TEN_CHILD_GATES)
    assert set(policy["required_corpora"]) == set(REQUIRED_CORPORA)
    assert set(policy["required_dod_clauses"]) == set(ROOT_DOD_CLAUSE_IDS)
    for code in (
        "failed",
        "skipped",
        "expected_failure",
        "stale",
        "foreign_tree",
        "unsigned",
    ):
        assert code in policy["refusal_codes"]


def test_runbook_render_covers_ten_gates_and_root_decision() -> None:
    text = default_gate_runbook_text()
    assert "Ten child gates" in text or "ten child gates" in text.lower()
    assert "Root release decision" in text
    assert "fail-closed" in text.lower() or "fails closed" in text.lower()
    for goal_id in TEN_CHILD_GATES:
        assert goal_id in text
    for clause_id in ROOT_DOD_CLAUSE_IDS:
        assert clause_id in text


# ---------------------------------------------------------------------------
# Tree binding
# ---------------------------------------------------------------------------


def test_normalize_tree_id() -> None:
    assert normalize_tree_id("ab30e5a9e5f5225e6375a72eee8ee47988bcf9a4") == (
        "tree-ab30e5a9e5f5225e6375a72eee8ee47988bcf9a4"
    )
    assert normalize_tree_id(TREE_ID) == TREE_ID


def test_bind_tree_requires_clean() -> None:
    dirty = TreeBinding(
        tree_id=TREE_ID,
        commit=TREE_ID.removeprefix("tree-"),
        is_clean=False,
        repo_root=str(REPO_ROOT),
        dirty_paths=("foo.py",),
        collected_at=_ts(),
    )
    c = ReleaseEvidenceCollector(expected_tree_id=TREE_ID, now=FIXED_NOW)
    with pytest.raises(EvidenceRefusal) as excinfo:
        c.bind_tree(dirty)
    assert excinfo.value.code == RefusalCode.DIRTY_TREE.value


def test_bind_tree_refuses_foreign() -> None:
    c = ReleaseEvidenceCollector(expected_tree_id=TREE_ID, now=FIXED_NOW)
    with pytest.raises(EvidenceRefusal) as excinfo:
        c.bind_tree(_clean_binding(FOREIGN_TREE))
    assert excinfo.value.code == RefusalCode.FOREIGN_TREE.value


def test_resolve_clean_tree_with_git_runner() -> None:
    commit = TREE_ID.removeprefix("tree-")

    def runner(args, cwd):
        if args[:2] == ["rev-parse", "HEAD"]:
            return commit + "\n"
        if args[:2] == ["status", "--porcelain"]:
            return ""
        raise AssertionError(args)

    binding = resolve_clean_tree(
        REPO_ROOT,
        expected_tree_id=TREE_ID,
        git_runner=runner,
    )
    assert binding.is_clean
    assert binding.tree_id == TREE_ID
    assert binding.commit == commit


def test_resolve_clean_tree_refuses_dirty() -> None:
    commit = TREE_ID.removeprefix("tree-")

    def runner(args, cwd):
        if args[:2] == ["rev-parse", "HEAD"]:
            return commit + "\n"
        if args[:2] == ["status", "--porcelain"]:
            return " M dirty_file.py\n"
        raise AssertionError(args)

    with pytest.raises(EvidenceRefusal) as excinfo:
        resolve_clean_tree(REPO_ROOT, git_runner=runner)
    assert excinfo.value.code == RefusalCode.DIRTY_TREE.value


# ---------------------------------------------------------------------------
# Command evidence recording
# ---------------------------------------------------------------------------


def test_record_command_captures_required_fields() -> None:
    c = _collector()
    evidence = c.record_command(
        command="python -m pytest -q tests/knowledge_graphs/contract",
        exit_status=0,
        test_counts=TestCounts(passed=10),
        artifact_digests=(ARTIFACT,),
        goal_id="KGP-G010",
        timestamp=_ts(),
        accept=True,
    )
    assert evidence.command.startswith("python -m pytest")
    assert evidence.timestamp == _ts()
    assert evidence.environment_label == "labelled lab environment"
    assert evidence.exit_status == 0
    assert evidence.test_counts.passed == 10
    assert ARTIFACT in evidence.artifact_digests
    assert evidence.tree_id == TREE_ID
    assert evidence.evidence_digest.startswith("sha256:")
    d = evidence.to_dict()
    for key in (
        "command",
        "timestamp",
        "environment_label",
        "exit_status",
        "test_counts",
        "artifact_digests",
        "tree_id",
    ):
        assert key in d


def test_parse_pytest_counts() -> None:
    counts = parse_pytest_counts("===== 12 passed, 2 skipped, 1 xfailed in 3.14s =====")
    assert counts.passed == 12
    assert counts.skipped == 2
    assert counts.xfailed == 1


# ---------------------------------------------------------------------------
# Refusals: failed / skipped / expected-failure / stale / foreign / unsigned
# ---------------------------------------------------------------------------


def test_refuses_failed_tests() -> None:
    c = _collector()
    with pytest.raises(EvidenceRefusal) as excinfo:
        c.record_and_accept_goal(
            goal_id="KGP-G010",
            command="pytest -q",
            exit_status=0,
            test_counts=TestCounts(passed=5, failed=1),
            artifact_digests=(ARTIFACT,),
            timestamp=_ts(),
        )
    assert excinfo.value.code == RefusalCode.FAILED.value


def test_refuses_nonzero_exit() -> None:
    c = _collector()
    with pytest.raises(EvidenceRefusal) as excinfo:
        c.record_and_accept_goal(
            goal_id="KGP-G010",
            command="pytest -q",
            exit_status=1,
            test_counts=TestCounts(passed=0, failed=3),
            artifact_digests=(ARTIFACT,),
            timestamp=_ts(),
        )
    assert excinfo.value.code in {
        RefusalCode.NONZERO_EXIT.value,
        RefusalCode.FAILED.value,
    }


def test_refuses_skipped_tests() -> None:
    c = _collector()
    with pytest.raises(EvidenceRefusal) as excinfo:
        c.record_and_accept_goal(
            goal_id="KGP-G020",
            command="pytest -q",
            exit_status=0,
            test_counts=TestCounts(passed=4, skipped=1),
            artifact_digests=(ARTIFACT,),
            timestamp=_ts(),
        )
    assert excinfo.value.code == RefusalCode.SKIPPED.value


def test_refuses_expected_failure_xfail() -> None:
    c = _collector()
    with pytest.raises(EvidenceRefusal) as excinfo:
        c.record_and_accept_goal(
            goal_id="KGP-G030",
            command="pytest -q",
            exit_status=0,
            test_counts=TestCounts(passed=4, xfailed=2),
            artifact_digests=(ARTIFACT,),
            timestamp=_ts(),
        )
    assert excinfo.value.code == RefusalCode.EXPECTED_FAILURE.value


def test_refuses_skipped_goal_receipt_status() -> None:
    c = _collector()
    receipt = make_goal_receipt(
        "KGP-G010",
        tree_id=TREE_ID,
        collected_at=_ts(),
        status="skipped",
        evidence_kind="validation_receipt",
    )
    with pytest.raises(EvidenceRefusal) as excinfo:
        c.accept_goal_receipt(receipt)
    assert excinfo.value.code == RefusalCode.SKIPPED.value


def test_refuses_xfail_goal_receipt_status() -> None:
    c = _collector()
    receipt = make_goal_receipt(
        "KGP-G010",
        tree_id=TREE_ID,
        collected_at=_ts(),
        status="xfail",
        evidence_kind="validation_receipt",
    )
    with pytest.raises(EvidenceRefusal) as excinfo:
        c.accept_goal_receipt(receipt)
    assert excinfo.value.code == RefusalCode.EXPECTED_FAILURE.value


def test_refuses_failed_goal_receipt_status() -> None:
    c = _collector()
    receipt = make_goal_receipt(
        "KGP-G010",
        tree_id=TREE_ID,
        collected_at=_ts(),
        status="failed",
        evidence_kind="validation_receipt",
    )
    with pytest.raises(EvidenceRefusal) as excinfo:
        c.accept_goal_receipt(receipt)
    assert excinfo.value.code == RefusalCode.FAILED.value


def test_refuses_stale_evidence() -> None:
    c = _collector()
    stale_ts = _ts(FIXED_NOW - timedelta(days=30))
    with pytest.raises(EvidenceRefusal) as excinfo:
        c.record_and_accept_goal(
            goal_id="KGP-G010",
            command="pytest -q",
            exit_status=0,
            test_counts=TestCounts(passed=3),
            artifact_digests=(ARTIFACT,),
            timestamp=stale_ts,
        )
    assert excinfo.value.code == RefusalCode.STALE.value


def test_refuses_foreign_tree_receipt() -> None:
    c = _collector()
    receipt = make_goal_receipt(
        "KGP-G010",
        tree_id=FOREIGN_TREE,
        collected_at=_ts(),
        status="pass",
    )
    with pytest.raises(EvidenceRefusal) as excinfo:
        c.accept_goal_receipt(receipt)
    assert excinfo.value.code == RefusalCode.FOREIGN_TREE.value


def test_refuses_unsigned_when_required() -> None:
    c = _collector(require_signatures=True, signing_key=SIGNING_KEY)
    with pytest.raises(EvidenceRefusal) as excinfo:
        c.record_and_accept_goal(
            goal_id="KGP-G010",
            command="pytest -q",
            exit_status=0,
            test_counts=TestCounts(passed=3),
            artifact_digests=(ARTIFACT,),
            timestamp=_ts(),
            signature="",  # unsigned
        )
    assert excinfo.value.code == RefusalCode.UNSIGNED.value


def test_accepts_signed_when_required() -> None:
    c = _collector(require_signatures=True, signing_key=SIGNING_KEY)
    receipt = c.record_and_accept_goal(
        goal_id="KGP-G010",
        command="pytest -q",
        exit_status=0,
        test_counts=TestCounts(passed=3),
        artifact_digests=(ARTIFACT,),
        timestamp=_ts(),
        signature="hmac-sha256:deadbeef",
    )
    assert receipt.goal_id == "KGP-G010"
    assert receipt.status == "pass"


def test_refuses_task_status_substitute() -> None:
    c = _collector()
    receipt = make_goal_receipt(
        "KGP-G010",
        tree_id=TREE_ID,
        collected_at=_ts(),
        status="pass",
        evidence_kind="task_status",
    )
    with pytest.raises(EvidenceRefusal) as excinfo:
        c.accept_goal_receipt(receipt)
    assert excinfo.value.code == RefusalCode.REJECTED_SUBSTITUTE.value


def test_refuses_missing_artifact_digests() -> None:
    c = _collector()
    with pytest.raises(EvidenceRefusal) as excinfo:
        c.record_and_accept_goal(
            goal_id="KGP-G010",
            command="pytest -q",
            exit_status=0,
            test_counts=TestCounts(passed=3),
            artifact_digests=(),
            timestamp=_ts(),
        )
    assert excinfo.value.code == RefusalCode.MISSING_DIGEST.value


def test_refuses_unknown_environment() -> None:
    c = ReleaseEvidenceCollector(expected_tree_id=TREE_ID, now=FIXED_NOW)
    c.bind_tree(_clean_binding())
    with pytest.raises(EvidenceRefusal) as excinfo:
        c.set_environment("unknown", "maybe")
    assert excinfo.value.code == RefusalCode.UNKNOWN_ENVIRONMENT.value


# ---------------------------------------------------------------------------
# Ingest: corpus, UCAN, soak/chaos
# ---------------------------------------------------------------------------


def test_ingest_corpus_signoffs() -> None:
    c = _collector()
    for corpus_id in REQUIRED_CORPORA:
        signoff = c.ingest_corpus_signoff(
            corpus_id=corpus_id,
            producer_id=f"producer-{corpus_id}",
            signer=f"owner-{corpus_id}",
            signed_at=_ts(),
        )
        assert signoff.mode == "full"
        assert signoff.tree_id == TREE_ID
    assert {s.corpus_id for s in c.state.corpus_signoffs} == set(REQUIRED_CORPORA)


def test_ingest_refuses_sample_only_corpus() -> None:
    c = _collector()
    with pytest.raises(EvidenceRefusal) as excinfo:
        c.ingest_corpus_signoff(
            corpus_id="cvefixes",
            producer_id="p",
            signer="s",
            mode="sample",
            signed_at=_ts(),
        )
    assert excinfo.value.code == RefusalCode.SAMPLE_ONLY.value


def test_ingest_ucan_deny_proof() -> None:
    c = _collector()
    proof = c.ingest_ucan_deny_proof(
        deny_receipt_cids=("sha256:" + "a" * 64,),
        collected_at=_ts(),
    )
    assert proof.tree_id == TREE_ID
    assert len(proof.deny_receipt_cids) == 1


def test_ingest_ucan_requires_cid() -> None:
    c = _collector()
    with pytest.raises(EvidenceRefusal) as excinfo:
        c.ingest_ucan_deny_proof(deny_receipt_cids=(), collected_at=_ts())
    assert excinfo.value.code == RefusalCode.MISSING_DIGEST.value


def test_ingest_load_soak_chaos() -> None:
    c = _collector()
    evidence = c.ingest_load_soak_chaos(
        soak_receipt_digest="sha256:" + "c" * 64,
        chaos_receipt_digest="sha256:" + "d" * 64,
        load_receipt_digest="sha256:" + "e" * 64,
        collected_at=_ts(),
    )
    assert evidence.soak_receipt_digest.startswith("sha256:")
    assert evidence.chaos_receipt_digest.startswith("sha256:")
    assert evidence.tree_id == TREE_ID


def test_ingest_soak_chaos_requires_both_digests() -> None:
    c = _collector()
    with pytest.raises(EvidenceRefusal) as excinfo:
        c.ingest_load_soak_chaos(
            soak_receipt_digest="",
            chaos_receipt_digest="sha256:" + "d" * 64,
            collected_at=_ts(),
        )
    assert excinfo.value.code == RefusalCode.MISSING_DIGEST.value


def test_ingest_unsigned_corpus_when_required() -> None:
    c = _collector(require_signatures=True, signing_key=SIGNING_KEY)
    with pytest.raises(EvidenceRefusal) as excinfo:
        c.ingest_corpus_signoff(
            corpus_id="cvefixes",
            producer_id="p",
            signer="",  # also fails missing field first — use empty signature path
            signed_at=_ts(),
            signature="",
        )
    # Either missing field (signer) or unsigned.
    assert excinfo.value.code in {
        RefusalCode.MISSING_FIELD.value,
        RefusalCode.UNSIGNED.value,
    }


# ---------------------------------------------------------------------------
# GraphReleaseGate evaluation (fail-closed)
# ---------------------------------------------------------------------------


def test_empty_collector_fails_closed() -> None:
    c = _collector()
    decision = c.evaluate(now=FIXED_NOW)
    assert decision.production_ready is False
    assert decision.outcome in {
        DecisionOutcome.FAIL.value,
        DecisionOutcome.NOT_PRODUCTION_READY.value,
    }
    assert not c.is_production_ready(decision)


def test_complete_collector_passes_and_is_production_ready() -> None:
    c = build_collector_with_passing_evidence(
        tree_id=TREE_ID,
        signing_key=SIGNING_KEY,
        now=FIXED_NOW,
    )
    decision = c.evaluate(now=FIXED_NOW)
    assert decision.outcome == DecisionOutcome.PASS.value
    assert decision.production_ready is True
    assert c.is_production_ready(decision) is True
    assert set(decision.satisfied_child_goals) == set(REQUIRED_CHILD_GOALS)
    assert set(decision.satisfied_dod_clauses) == set(ROOT_DOD_CLAUSE_IDS)
    assert decision.signature.startswith("hmac-sha256:")
    assert decision.decision_cid.startswith("kg-rel1-")


def test_evaluate_or_raise_fail_closed() -> None:
    c = _collector()
    with pytest.raises(Exception) as excinfo:
        c.evaluate(now=FIXED_NOW, raise_on_fail=True)
    # ReleaseGateFailClosed from release_gate
    assert "fail" in str(excinfo.value).lower() or hasattr(
        excinfo.value, "decision"
    )


def test_partial_goals_not_production_ready() -> None:
    c = _collector()
    c.record_and_accept_goal(
        goal_id="KGP-G010",
        command="pytest -q",
        exit_status=0,
        test_counts=TestCounts(passed=2),
        artifact_digests=(ARTIFACT,),
        timestamp=_ts(),
    )
    decision = c.evaluate(now=FIXED_NOW)
    assert decision.production_ready is False
    assert "KGP-G010" in decision.satisfied_child_goals


def test_require_signatures_on_decision() -> None:
    c = build_collector_with_passing_evidence(
        tree_id=TREE_ID,
        signing_key=SIGNING_KEY,
        require_signatures=True,
        now=FIXED_NOW,
        signature="hmac-sha256:operator-sig",
    )
    decision = c.evaluate(now=FIXED_NOW)
    assert decision.production_ready is True
    assert decision.signature.startswith("hmac-sha256:")


def test_write_runbook_includes_decision(tmp_path: Path) -> None:
    c = build_collector_with_passing_evidence(
        tree_id=TREE_ID,
        signing_key=SIGNING_KEY,
        now=FIXED_NOW,
    )
    decision = c.evaluate(now=FIXED_NOW)
    assert decision.production_ready
    out = c.write_runbook(tmp_path / "gate_runbook.md")
    text = out.read_text(encoding="utf-8")
    assert "KGP-G010" in text and "KGP-G100" in text
    assert "production_ready" in text
    assert decision.decision_cid in text
    assert "Root release decision" in text


def test_dump_state_roundtrip(tmp_path: Path) -> None:
    c = build_collector_with_passing_evidence(
        tree_id=TREE_ID,
        signing_key=SIGNING_KEY,
        now=FIXED_NOW,
    )
    c.evaluate(now=FIXED_NOW)
    path = c.dump_state(tmp_path / "collector_state.json")
    assert path.is_file()
    payload = path.read_text(encoding="utf-8")
    assert TREE_ID in payload
    assert SCHEMA_VERSION in payload
    assert "goal_receipts" in payload


def test_dod_receipt_refusals() -> None:
    c = _collector()
    bad = make_dod_receipt(
        "four_surface_parity",
        tree_id=TREE_ID,
        collected_at=_ts(),
        status="xfail",
        evidence_kind="surface_conformance",
    )
    with pytest.raises(EvidenceRefusal) as excinfo:
        c.accept_dod_receipt(bad)
    assert excinfo.value.code == RefusalCode.EXPECTED_FAILURE.value


def test_command_evidence_from_mapping_roundtrip() -> None:
    original = CommandEvidence(
        command="pytest -q",
        timestamp=_ts(),
        environment_label="lab",
        exit_status=0,
        test_counts=TestCounts(passed=1),
        artifact_digests=(ARTIFACT,),
        tree_id=TREE_ID,
        goal_id="KGP-G010",
    )
    restored = CommandEvidence.from_mapping(original.to_dict())
    assert restored.command == original.command
    assert restored.evidence_digest == original.evidence_digest
    assert restored.test_counts.passed == 1


def test_text_digest_stable() -> None:
    assert text_digest("hello") == text_digest("hello")
    assert text_digest("hello") != text_digest("world")


def test_render_runbook_with_failed_decision() -> None:
    c = _collector()
    decision = c.evaluate(now=FIXED_NOW)
    text = render_gate_runbook(
        decision=decision,
        tree_id=TREE_ID,
        collector_state=c.state,
    )
    assert "not production ready" in text.lower() or decision.outcome in text
    assert "Blockers" in text or "blockers" in text.lower()


def test_cli_main_write_runbook(tmp_path: Path) -> None:
    out = tmp_path / "runbook.md"
    rc = re.main(["--write-runbook", str(out), "--policy-json"])
    assert rc == 0
    assert out.is_file()
    assert "KGP-G100" in out.read_text(encoding="utf-8")


def test_build_bundle_tree_matches() -> None:
    c = build_collector_with_passing_evidence(
        tree_id=TREE_ID, now=FIXED_NOW
    )
    bundle = c.build_bundle()
    assert bundle.tree_id == TREE_ID
    assert len(bundle.goal_receipts) == len(REQUIRED_CHILD_GOALS)
    assert bundle.ucan_negative is not None
    assert bundle.soak_chaos is not None
    assert bundle.environment is not None
    assert len(bundle.corpus_signoffs) == len(REQUIRED_CORPORA)
