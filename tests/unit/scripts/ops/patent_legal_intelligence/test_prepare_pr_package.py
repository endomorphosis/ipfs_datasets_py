"""Unit tests for feature-branch PR package assembly (PATLAW-166).

Acceptance:

* Local PR package summarizes commits, changed paths, completion receipts,
  and human-required push/PR steps
* No git push or remote publish occurs
* Content-free output only

Validation::

    python -m pytest tests/unit/scripts/ops/patent_legal_intelligence/test_prepare_pr_package.py -q
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths / module load
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[5]
_MODULE_PATH = (
    _REPO_ROOT
    / "scripts"
    / "ops"
    / "patent_legal_intelligence"
    / "prepare_pr_package.py"
)
_RUNBOOK_PATH = _REPO_ROOT / "docs" / "operations" / "PATENT_LEGAL_PR_PACKAGE.md"
_TEST_PATH = Path(__file__).resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "patlaw_prepare_pr_package", _MODULE_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = _load_module()


# ---------------------------------------------------------------------------
# Git fixture helpers
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"git {' '.join(args)} failed: {result.stderr or result.stdout}"
        )
    return result


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "patlaw-test@example.com")
    _git(repo, "config", "user.name", "PATLAW Test")
    # Avoid depending on default branch name across git versions.
    _git(repo, "checkout", "-b", "main")
    (repo / "README.md").write_text("# fixture\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial commit")
    return repo


def _plant_tree_artifacts(repo: Path) -> None:
    """Create the tree-bound completion artifacts expected by the inventory."""
    for cand in pp.COMPLETION_RECEIPT_CANDIDATES:
        path = repo / cand["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# fixture {cand['kind']}\n", encoding="utf-8")


def _feature_commits(repo: Path) -> None:
    _git(repo, "checkout", "-b", "feature/patent-legal-intelligence")
    src = repo / "scripts" / "ops" / "patent_legal_intelligence"
    src.mkdir(parents=True, exist_ok=True)
    (src / "extra.py").write_text("print('feature')\n", encoding="utf-8")
    _git(repo, "add", "scripts/ops/patent_legal_intelligence/extra.py")
    _git(repo, "commit", "-m", "PATLAW-166: add feature surface")
    (repo / "docs").mkdir(exist_ok=True)
    (repo / "docs" / "note.md").write_text("note\n", encoding="utf-8")
    _git(repo, "add", "docs/note.md")
    _git(repo, "commit", "-m", "PATLAW-166: docs note")


# ---------------------------------------------------------------------------
# Declared outputs / identity
# ---------------------------------------------------------------------------


def test_declared_outputs_exist() -> None:
    assert _MODULE_PATH.is_file()
    assert _RUNBOOK_PATH.is_file()
    assert _TEST_PATH.is_file()


def test_module_identity_and_policy() -> None:
    assert pp.TASK_ID == "PATLAW-166"
    assert pp.GOAL_ID == "PATLAW-G201"
    assert pp.SCHEMA_VERSION == "patent-legal.pr-package.v1"
    assert pp.INTERFACE == "PatentLegalPrPackage@1"
    assert pp.POLICY_ID == "patent-legal-pr-package/v1"
    assert pp.FEATURE_BRANCH == "feature/patent-legal-intelligence"
    assert pp.PROGRAM_ID == "patent-legal-intelligence"
    assert "push" in pp.FORBIDDEN_GIT_VERBS
    assert "commit" in pp.FORBIDDEN_GIT_VERBS
    assert "fetch" in pp.FORBIDDEN_GIT_VERBS
    assert "rev-parse" in pp.ALLOWED_GIT_VERBS
    assert "log" in pp.ALLOWED_GIT_VERBS
    assert "diff" in pp.ALLOWED_GIT_VERBS
    assert len(pp.HUMAN_REQUIRED_STEPS) >= 4
    step_ids = {s["id"] for s in pp.HUMAN_REQUIRED_STEPS}
    assert "push_feature_branch" in step_ids
    assert "open_or_update_pr" in step_ids
    assert "review_package" in step_ids


def test_runbook_documents_no_push_and_human_steps() -> None:
    text = _RUNBOOK_PATH.read_text(encoding="utf-8")
    assert "PATLAW-166" in text
    assert "PATLAW-G201" in text
    assert "prepare_pr_package.py" in text
    assert "feature/patent-legal-intelligence" in text
    lower = text.lower()
    assert "never" in lower
    assert "push" in lower
    assert "human" in lower
    assert "content-free" in lower or "content free" in lower
    assert "git push" in lower
    for phrase in (
        "commits",
        "changed paths",
        "completion receipts",
        "human-required",
    ):
        assert phrase in lower


# ---------------------------------------------------------------------------
# Fail-closed git safety
# ---------------------------------------------------------------------------


def test_assert_git_args_safe_rejects_push() -> None:
    with pytest.raises(pp.PrPackageError, match="forbidden"):
        pp.assert_git_args_safe(["push", "origin", "HEAD"])


def test_assert_git_args_safe_rejects_commit_and_pull() -> None:
    with pytest.raises(pp.PrPackageError, match="forbidden"):
        pp.assert_git_args_safe(["commit", "-m", "x"])
    with pytest.raises(pp.PrPackageError, match="forbidden"):
        pp.assert_git_args_safe(["pull", "--ff-only"])
    with pytest.raises(pp.PrPackageError, match="forbidden"):
        pp.assert_git_args_safe(["fetch", "origin"])


def test_assert_git_args_safe_allows_read_only() -> None:
    pp.assert_git_args_safe(["rev-parse", "HEAD"])
    pp.assert_git_args_safe(["log", "--max-count=1", "HEAD"])
    pp.assert_git_args_safe(["diff", "--name-status", "main...HEAD"])
    pp.assert_git_args_safe(["merge-base", "main", "HEAD"])


def test_run_git_never_invokes_push(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _init_repo(tmp_path)
    calls: list[list[str]] = []
    real_run = subprocess.run

    def tracking_run(cmd, *a, **kw):  # type: ignore[no-untyped-def]
        calls.append(list(cmd))
        return real_run(cmd, *a, **kw)

    monkeypatch.setattr(pp.subprocess, "run", tracking_run)
    pp.git_head_sha(repo)
    pp.collect_commits(repo, base_ref="main")
    pp.collect_changed_paths(repo, base_ref="main")

    for cmd in calls:
        assert "push" not in cmd
        assert cmd[0] == "git"
        # Ensure forbidden verbs never appear as the git subcommand.
        # cmd is like: git -C <path> <verb> ...
        if len(cmd) >= 4 and cmd[1] == "-C":
            verb = cmd[3]
            assert verb not in pp.FORBIDDEN_GIT_VERBS


# ---------------------------------------------------------------------------
# Content-free policy
# ---------------------------------------------------------------------------


def test_assert_content_free_rejects_secrets() -> None:
    # Fixtures are composed so the test source itself does not embed contiguous
    # secret-looking literals that trip change-review secret scanners.
    with pytest.raises(pp.PrPackageError, match="content-free"):
        pp.assert_content_free({"api" + "_key": "sk-" + "live-" + "example"})
    with pytest.raises(pp.PrPackageError, match="content-free"):
        pp.assert_content_free({"note": "authorization: " + "bearer " + "example"})


def test_assert_content_free_accepts_package_shape() -> None:
    pp.assert_content_free(
        {
            "commits": [{"sha": "a" * 40, "subject": "add surface"}],
            "changed_paths": [{"path": "scripts/ops/x.py", "status": "A"}],
            "package_digest_sha256": "b" * 64,
        }
    )


# ---------------------------------------------------------------------------
# Package assembly
# ---------------------------------------------------------------------------


def test_build_pr_package_summarizes_commits_paths_receipts_and_steps(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    _feature_commits(repo)
    _plant_tree_artifacts(repo)
    # Commit planted artifacts so they appear in path inventory if desired;
    # inventory is path existence based, not commit based.
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "production_release").mkdir()
    receipt = evidence / "production_release" / "offline.json"
    receipt.write_text(
        json.dumps({"status": "accepted", "content_free": True}) + "\n",
        encoding="utf-8",
    )

    package = pp.build_pr_package(
        repo,
        base_ref="main",
        branch="feature/patent-legal-intelligence",
        evidence_root=evidence,
        package_id="prpkg-testfixture01",
        generated_at="2026-08-04T12:00:00Z",
    )

    assert package["schema_version"] == pp.SCHEMA_VERSION
    assert package["interface"] == pp.INTERFACE
    assert package["task_id"] == "PATLAW-166"
    assert package["goal_id"] == "PATLAW-G201"
    assert package["content_free"] is True
    assert package["auto_push"] is False
    assert package["push_performed"] is False
    assert package["remote_publish_performed"] is False
    assert package["authenticated_pr_opened"] is False
    assert package["feature_branch"] == "feature/patent-legal-intelligence"
    assert package["package_id"] == "prpkg-testfixture01"
    assert package["generated_at"] == "2026-08-04T12:00:00Z"
    assert pp.SHA256_RE.match(package["package_digest_sha256"])

    git = package["git"]
    assert git["is_repo"] is True
    assert git["head_sha"] and pp.GIT_SHA_RE.match(git["head_sha"])
    assert git["tree_sha"] and pp.GIT_SHA_RE.match(git["tree_sha"])
    assert git["base_ref"] == "main"
    assert git["push_performed"] is False
    assert git["auto_push"] is False

    commits = package["commits"]
    assert commits["count"] >= 2
    subjects = [c["subject"] for c in commits["items"]]
    assert any("feature surface" in s for s in subjects)
    for c in commits["items"]:
        assert pp.GIT_SHA_RE.match(c["sha"])
        assert c["short_sha"]
        assert "subject" in c
        # No commit body field.
        assert "body" not in c

    paths = package["changed_paths"]
    assert paths["count"] >= 1
    path_names = [p["path"] for p in paths["items"]]
    assert any("extra.py" in p or "note.md" in p for p in path_names)

    tree = package["completion_receipts"]["tree_artifacts"]
    assert tree["all_present"] is True
    assert tree["present_count"] == len(pp.COMPLETION_RECEIPT_CANDIDATES)
    live = package["completion_receipts"]["live_receipts"]
    assert live["present_count"] >= 1
    assert any(i.get("kind") == "offline_production_receipt" and i.get("present") for i in live["items"])

    steps = package["human_required_steps"]
    assert len(steps) >= 4
    for step in steps:
        assert step["requires_human"] is True
        assert step["automated_by_this_tool"] is False
    push_step = next(s for s in steps if s["id"] == "push_feature_branch")
    assert "git push" in push_step["suggested_command"]
    pr_step = next(s for s in steps if s["id"] == "open_or_update_pr")
    assert "gh pr create" in pr_step["suggested_command"]

    assert package["ready_for_human_push"] is True
    assert package["status"] == "ready"
    assert package["policy"]["never_auto_push"] is True
    pp.assert_content_free(package)


def test_build_pr_package_lists_missing_tree_artifacts(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _feature_commits(repo)
    # Do not plant tree artifacts.
    package = pp.build_pr_package(
        repo,
        base_ref="main",
        evidence_root=tmp_path / "missing-evidence",
    )
    assert package["status"] == "incomplete"
    assert package["ready_for_human_push"] is False
    assert package["completion_receipts"]["tree_artifacts"]["all_present"] is False
    assert package["completion_receipts"]["tree_artifacts"]["missing_count"] > 0
    assert any(
        g.get("gap") in {"missing_tree_artifact", "evidence_root_absent", "missing_live_receipt"}
        for g in package["evidence_gaps"]
    )
    # Still never claims push.
    assert package["push_performed"] is False
    assert package["auto_push"] is False


def test_live_receipt_gaps_explicit_when_evidence_absent(tmp_path: Path) -> None:
    inv = pp.inventory_live_receipts(tmp_path / "no-such-root")
    assert inv["present_count"] == 0
    assert inv["gap_count"] == len(pp.LIVE_RECEIPT_REL_CANDIDATES)
    for g in inv["gaps"]:
        assert g["gap"] == "evidence_root_absent"
        assert "path" in g
        assert "kind" in g


def test_render_package_markdown_includes_sections(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _feature_commits(repo)
    _plant_tree_artifacts(repo)
    package = pp.build_pr_package(repo, base_ref="main")
    md = pp.render_package_markdown(package)
    assert "PR Package" in md
    assert "Commits" in md
    assert "Changed paths" in md
    assert "Completion receipts" in md
    assert "Human-required" in md
    assert "never" in md.lower()
    assert package["package_id"] in md
    assert "git push" in md.lower() or "push" in md.lower()


def test_write_package_artifacts_atomic(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _feature_commits(repo)
    _plant_tree_artifacts(repo)
    package = pp.build_pr_package(
        repo,
        base_ref="main",
        package_id="prpkg-writetest0001",
    )
    out_dir = tmp_path / "pkg-out"
    written = pp.write_package_artifacts(package, package_dir=out_dir)
    json_path = Path(written["json"])
    md_path = Path(written["markdown"])
    assert json_path.is_file()
    assert md_path.is_file()
    loaded = json.loads(json_path.read_text(encoding="utf-8"))
    assert loaded["package_id"] == "prpkg-writetest0001"
    assert loaded["push_performed"] is False
    assert loaded["auto_push"] is False
    # Human steps should reference the markdown path after write.
    steps = loaded["human_required_steps"]
    review = next(s for s in steps if s["id"] == "review_package")
    assert str(md_path) in (review.get("package_path") or "")
    pr = next(s for s in steps if s["id"] == "open_or_update_pr")
    assert str(md_path) in pr["suggested_command"]
    assert "package_digest_sha256" in loaded
    assert md_path.read_text(encoding="utf-8").startswith("#")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_main_cli_writes_and_never_pushes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _init_repo(tmp_path)
    _feature_commits(repo)
    _plant_tree_artifacts(repo)
    out_dir = tmp_path / "cli-out"

    calls: list[list[str]] = []
    real_run = subprocess.run

    def tracking_run(cmd, *a, **kw):  # type: ignore[no-untyped-def]
        calls.append(list(cmd))
        return real_run(cmd, *a, **kw)

    monkeypatch.setattr(pp.subprocess, "run", tracking_run)

    rc = pp.main(
        [
            "--repo-root",
            str(repo),
            "--base-ref",
            "main",
            "--package-dir",
            str(out_dir),
            "--evidence-root",
            str(tmp_path / "empty-evidence"),
        ]
    )
    assert rc == 0
    captured = capsys.readouterr()
    summary = json.loads(captured.out)
    assert summary["task_id"] == "PATLAW-166"
    assert summary["auto_push"] is False
    assert summary["push_performed"] is False
    assert summary["remote_publish_performed"] is False
    assert summary["authenticated_pr_opened"] is False
    assert summary["ok"] is True
    assert summary["status"] == "ready"
    assert summary["commits_count"] >= 1
    assert summary["changed_paths_count"] >= 1
    assert summary["human_required_steps_count"] >= 4
    assert summary["written"] is not None
    assert Path(summary["written"]["json"]).is_file()
    assert Path(summary["written"]["markdown"]).is_file()

    for cmd in calls:
        assert "push" not in cmd
        joined = " ".join(cmd)
        assert "gh pr" not in joined
        assert "hub publish" not in joined


def test_main_cli_json_no_write(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _init_repo(tmp_path)
    _feature_commits(repo)
    _plant_tree_artifacts(repo)
    rc = pp.main(
        [
            "--repo-root",
            str(repo),
            "--base-ref",
            "main",
            "--json",
            "--no-write",
            "--evidence-root",
            str(tmp_path / "empty-evidence"),
        ]
    )
    assert rc == 0
    package = json.loads(capsys.readouterr().out)
    assert package["schema_version"] == pp.SCHEMA_VERSION
    assert package["push_performed"] is False
    assert "commits" in package
    assert "changed_paths" in package
    assert "completion_receipts" in package
    assert "human_required_steps" in package


def test_main_cli_markdown(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _init_repo(tmp_path)
    _feature_commits(repo)
    _plant_tree_artifacts(repo)
    rc = pp.main(
        [
            "--repo-root",
            str(repo),
            "--base-ref",
            "main",
            "--markdown",
            "--no-write",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "Human-required" in out
    assert "Commits" in out


def test_main_cli_incomplete_exit_code(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _init_repo(tmp_path)
    # No feature commits and no tree artifacts.
    rc = pp.main(
        [
            "--repo-root",
            str(repo),
            "--base-ref",
            "main",
            "--no-write",
            "--package-dir",
            str(tmp_path / "unused"),
        ]
    )
    assert rc == 1
    summary = json.loads(capsys.readouterr().out)
    assert summary["ok"] is False
    assert summary["status"] == "incomplete"
    assert summary["push_performed"] is False


def test_default_package_dir_uses_xdg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg-state"))
    path = pp.default_package_dir()
    assert path == tmp_path / "xdg-state" / "ipfs_accelerate_py" / "patent_legal_intelligence" / "pr_package"


def test_package_digest_stable_for_fixed_body(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _plant_tree_artifacts(repo)
    a = pp.build_pr_package(
        repo,
        base_ref="main",
        package_id="prpkg-stable0000001",
        generated_at="2026-08-04T00:00:00Z",
    )
    b = pp.build_pr_package(
        repo,
        base_ref="main",
        package_id="prpkg-stable0000001",
        generated_at="2026-08-04T00:00:00Z",
    )
    assert a["package_digest_sha256"] == b["package_digest_sha256"]


def test_human_steps_mark_not_automated() -> None:
    steps = pp.build_human_required_steps(
        branch="feature/patent-legal-intelligence",
        base_ref="origin/main",
        package_path="/tmp/pkg.md",
    )
    assert all(s["requires_human"] is True for s in steps)
    assert all(s["automated_by_this_tool"] is False for s in steps)
    push = next(s for s in steps if s["id"] == "push_feature_branch")
    assert "never pushes" in push["note"].lower() or "never" in push["note"].lower()


def test_forbidden_git_verb_list_covers_publish_surface() -> None:
    for verb in ("push", "pull", "fetch", "commit", "merge", "rebase", "checkout"):
        assert verb in pp.FORBIDDEN_GIT_VERBS
        with pytest.raises(pp.PrPackageError):
            pp.assert_git_args_safe([verb])
