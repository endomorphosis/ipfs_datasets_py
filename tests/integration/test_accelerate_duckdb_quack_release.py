"""Integration tests for the fail-closed DQP release verifier (DQK-057)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = (
    REPO_ROOT / "scripts/validation/validate_accelerate_duckdb_quack_release.py"
)


def _prefer_sealed_accelerate_checkout() -> None:
    """Bind the sealed validator's accelerator checkout in nested worktrees.

    The sealed task-validation Python hardcodes ``accelerate_root`` to the
    superproject's ``ipfs_accelerate_py`` checkout. Nested implementation
    worktrees also place their own submodule on ``sys.path`` via pytest
    ``pythonpath``, so collection would otherwise resolve
    ``validation_runtime`` from a foreign path and fail closed before any
    test body runs. Prefer the non-local sealed checkout when both are
    visible; no-op when already running from the superproject.
    """

    local_accelerate = (REPO_ROOT / "ipfs_accelerate_py").resolve()
    accelerate_paths: list[Path] = []
    for entry in sys.path:
        try:
            path = Path(entry).resolve()
        except OSError:
            continue
        runtime = (
            path
            / "ipfs_accelerate_py"
            / "agent_supervisor"
            / "validation_runtime.py"
        )
        if runtime.is_file() and path not in accelerate_paths:
            accelerate_paths.append(path)
    if not accelerate_paths:
        return
    preferred = next(
        (path for path in accelerate_paths if path != local_accelerate),
        accelerate_paths[0],
    )
    if preferred == local_accelerate:
        return

    rebuilt: list[str] = [str(preferred)]
    for entry in sys.path:
        try:
            path = Path(entry).resolve()
        except OSError:
            rebuilt.append(entry)
            continue
        if path in {local_accelerate, preferred}:
            continue
        rebuilt.append(entry)
    sys.path[:] = rebuilt
    for name in list(sys.modules):
        if name == "ipfs_accelerate_py" or name.startswith("ipfs_accelerate_py."):
            del sys.modules[name]


_prefer_sealed_accelerate_checkout()


def _load_verifier() -> ModuleType:
    """Load the verifier script without requiring a package __init__."""

    spec = importlib.util.spec_from_file_location(
        "validate_accelerate_duckdb_quack_release",
        VERIFIER_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


verifier = _load_verifier()


def _git(repository: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repository,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return result.stdout.strip()


@pytest.fixture()
def accelerate_root(tmp_path: Path) -> Path:
    root = tmp_path / "accelerate"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.name", "DQK-057 Test")
    _git(root, "config", "user.email", "dqk-057@example.invalid")
    (root / "README.md").write_text("accelerator fixture\n", encoding="utf-8")
    _git(root, "add", "--", ".")
    _git(root, "commit", "-m", "seed accelerator")
    return root


@pytest.fixture()
def accelerate_identity(accelerate_root: Path) -> tuple[str, str]:
    commit = _git(accelerate_root, "rev-parse", "HEAD").lower()
    tree = _git(accelerate_root, "rev-parse", "HEAD^{tree}").lower()
    return commit, tree


def _fresh_window() -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    return now - timedelta(minutes=5), now + timedelta(hours=2)


def _valid_receipt(
    commit: str,
    tree: str,
    *,
    issued_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> dict[str, Any]:
    issued, expires = _fresh_window()
    if issued_at is not None:
        issued = issued_at
    if expires_at is not None:
        expires = expires_at
    return verifier.build_release_receipt(
        accelerator_commit=commit,
        accelerator_tree=tree,
        store_generation="generation:dqk-057-test",
        schema_checksum="sha256:" + "11" * 32,
        quack_profile="quack-profile:1.5.5-loopback",
        decision_cid="decision:dqk-057-test",
        issued_at=issued,
        expires_at=expires,
    )


def _write_receipt(path: Path, payload: dict[str, Any]) -> Path:
    path.write_text(verifier.canonical_json(payload) + "\n", encoding="utf-8")
    return path


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VERIFIER_PATH), *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_module_exports_expected_schemas() -> None:
    assert (
        verifier.VERIFICATION_SCHEMA
        == "ipfs_accelerate_py/agent-supervisor/duckdb-quack-release-verification@1"
    )
    assert verifier.RELEASE_RECEIPT_INTERFACE == "DuckDBControlPlaneReleaseReceipt@1"
    assert verifier.CUTOVER_RECEIPT_INTERFACE == "DatabaseCutoverReceipt@1"
    assert verifier.PROGRAM_ID == "agent-supervisor-duckdb-quack-control-plane-v1"


def test_check_mode_succeeds() -> None:
    result = _run_cli("--check", "--json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["verification_schema"] == verifier.VERIFICATION_SCHEMA


def test_cli_accepts_receipt_accelerate_root_and_json(
    accelerate_root: Path,
    accelerate_identity: tuple[str, str],
    tmp_path: Path,
) -> None:
    commit, tree = accelerate_identity
    receipt_path = _write_receipt(tmp_path / "release.json", _valid_receipt(commit, tree))
    result = _run_cli(
        "--receipt",
        str(receipt_path),
        "--accelerate-root",
        str(accelerate_root),
        "--json",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["schema"] == verifier.VERIFICATION_SCHEMA
    assert payload["accepted"] is True
    assert payload["accelerator_commit"] == commit
    assert payload["accelerator_tree"] == tree
    assert payload["release_receipt_cid"].startswith("sha256:")
    assert payload["cutover_receipt_cid"].startswith("sha256:")
    assert payload["store_generation"] == "generation:dqk-057-test"
    assert payload["schema_checksum"] == "sha256:" + "11" * 32
    assert payload["quack_profile"] == "quack-profile:1.5.5-loopback"
    assert payload["decision_cid"] == "decision:dqk-057-test"
    assert payload["expires_at"]


def test_library_verify_returns_gate_object(
    accelerate_root: Path,
    accelerate_identity: tuple[str, str],
) -> None:
    commit, tree = accelerate_identity
    receipt = _valid_receipt(commit, tree)
    verification = verifier.verify_release_receipt(
        receipt, accelerate_root=accelerate_root
    )
    assert verification["schema"] == verifier.VERIFICATION_SCHEMA
    assert verification["accepted"] is True
    assert verification["accelerator_commit"] == commit
    assert verification["cutover_receipt_cid"] == receipt["cutover"]["receipt_cid"]


def test_markdown_cannot_satisfy_the_gate(
    accelerate_root: Path,
    tmp_path: Path,
) -> None:
    markdown = tmp_path / "board.md"
    markdown.write_text(
        "# Agent Supervisor\n\n## DQP-039\n\n- Status: completed\n",
        encoding="utf-8",
    )
    result = _run_cli(
        "--receipt",
        str(markdown),
        "--accelerate-root",
        str(accelerate_root),
        "--json",
    )
    assert result.returncode != 0
    assert "Markdown" in result.stderr or "markdown" in result.stderr.lower()


def test_process_status_cannot_satisfy_the_gate(
    accelerate_root: Path,
    tmp_path: Path,
) -> None:
    status = {
        "program_id": verifier.PROGRAM_ID,
        "master_alive": True,
        "master_pid": 1234,
        "release_status": "completed",
        "release_task_id": "DQP-039",
        "completed_count": 39,
        "task_count": 40,
        "board_path": "/tmp/board.md",
        "stale_or_unbound_lanes": [],
    }
    path = _write_receipt(tmp_path / "status.json", status)
    result = _run_cli(
        "--receipt",
        str(path),
        "--accelerate-root",
        str(accelerate_root),
        "--json",
    )
    assert result.returncode != 0
    assert "process status" in result.stderr.lower() or "schema" in result.stderr.lower()


def test_missing_canonical_query_fails_closed(
    accelerate_root: Path,
    accelerate_identity: tuple[str, str],
    tmp_path: Path,
) -> None:
    commit, tree = accelerate_identity
    receipt = _valid_receipt(commit, tree)
    del receipt["canonical_query"]
    # Re-seal without the query so the test isolates the query requirement.
    receipt.pop("signature", None)
    receipt.pop("receipt_cid", None)
    receipt = verifier.seal_receipt(receipt)
    path = _write_receipt(tmp_path / "no-query.json", receipt)
    result = _run_cli(
        "--receipt",
        str(path),
        "--accelerate-root",
        str(accelerate_root),
        "--json",
    )
    assert result.returncode != 0
    assert "canonical" in result.stderr.lower()


def test_missing_machine_readable_identity_fails_closed(
    accelerate_root: Path,
    accelerate_identity: tuple[str, str],
    tmp_path: Path,
) -> None:
    commit, tree = accelerate_identity
    receipt = _valid_receipt(commit, tree)
    # Break the content-bound receipt identity.
    receipt["receipt_cid"] = "not-a-digest"
    path = _write_receipt(tmp_path / "bad-identity.json", receipt)
    result = _run_cli(
        "--receipt",
        str(path),
        "--accelerate-root",
        str(accelerate_root),
        "--json",
    )
    assert result.returncode != 0
    assert result.stderr.strip()


def test_missing_canonical_query_result_identity_fails_closed(
    accelerate_root: Path,
    accelerate_identity: tuple[str, str],
    tmp_path: Path,
) -> None:
    commit, tree = accelerate_identity
    receipt = _valid_receipt(commit, tree)
    query = dict(receipt["canonical_query"])
    del query["result_identity"]
    receipt["canonical_query"] = query
    receipt.pop("signature", None)
    receipt.pop("receipt_cid", None)
    receipt = verifier.seal_receipt(receipt)
    path = _write_receipt(tmp_path / "no-result-identity.json", receipt)
    result = _run_cli(
        "--receipt",
        str(path),
        "--accelerate-root",
        str(accelerate_root),
        "--json",
    )
    assert result.returncode != 0
    assert (
        "identity" in result.stderr.lower()
        or "canonical" in result.stderr.lower()
        or "result" in result.stderr.lower()
    )


def test_stale_accelerator_commit_is_rejected(
    accelerate_root: Path,
    accelerate_identity: tuple[str, str],
    tmp_path: Path,
) -> None:
    commit, tree = accelerate_identity
    stale_commit = "f" * 40
    assert stale_commit != commit
    receipt = _valid_receipt(stale_commit, tree)
    path = _write_receipt(tmp_path / "stale.json", receipt)
    result = _run_cli(
        "--receipt",
        str(path),
        "--accelerate-root",
        str(accelerate_root),
        "--json",
    )
    assert result.returncode != 0
    assert "stale" in result.stderr.lower() or "commit" in result.stderr.lower()


def test_mismatched_accelerator_tree_is_rejected(
    accelerate_root: Path,
    accelerate_identity: tuple[str, str],
    tmp_path: Path,
) -> None:
    commit, tree = accelerate_identity
    mismatched_tree = "e" * 40
    assert mismatched_tree != tree
    receipt = _valid_receipt(commit, mismatched_tree)
    path = _write_receipt(tmp_path / "mismatch.json", receipt)
    result = _run_cli(
        "--receipt",
        str(path),
        "--accelerate-root",
        str(accelerate_root),
        "--json",
    )
    assert result.returncode != 0
    assert "tree" in result.stderr.lower() or "stale" in result.stderr.lower()


def test_expired_receipt_is_rejected(
    accelerate_root: Path,
    accelerate_identity: tuple[str, str],
    tmp_path: Path,
) -> None:
    commit, tree = accelerate_identity
    issued = datetime(2020, 1, 1, tzinfo=timezone.utc)
    expires = datetime(2020, 1, 2, tzinfo=timezone.utc)
    receipt = _valid_receipt(commit, tree, issued_at=issued, expires_at=expires)
    path = _write_receipt(tmp_path / "expired.json", receipt)
    result = _run_cli(
        "--receipt",
        str(path),
        "--accelerate-root",
        str(accelerate_root),
        "--json",
    )
    assert result.returncode != 0
    assert "expired" in result.stderr.lower()


def test_unsigned_receipt_is_rejected(
    accelerate_root: Path,
    accelerate_identity: tuple[str, str],
    tmp_path: Path,
) -> None:
    commit, tree = accelerate_identity
    receipt = _valid_receipt(commit, tree)
    receipt["signature"] = "sha256:" + "0" * 64
    path = _write_receipt(tmp_path / "unsigned.json", receipt)
    result = _run_cli(
        "--receipt",
        str(path),
        "--accelerate-root",
        str(accelerate_root),
        "--json",
    )
    assert result.returncode != 0
    assert "signature" in result.stderr.lower() or "unsigned" in result.stderr.lower()


def test_missing_signature_is_rejected(
    accelerate_root: Path,
    accelerate_identity: tuple[str, str],
    tmp_path: Path,
) -> None:
    commit, tree = accelerate_identity
    receipt = _valid_receipt(commit, tree)
    del receipt["signature"]
    path = _write_receipt(tmp_path / "no-sig.json", receipt)
    result = _run_cli(
        "--receipt",
        str(path),
        "--accelerate-root",
        str(accelerate_root),
        "--json",
    )
    assert result.returncode != 0


def test_unsigned_cutover_is_rejected(
    accelerate_root: Path,
    accelerate_identity: tuple[str, str],
    tmp_path: Path,
) -> None:
    """Acceptance: an unsigned cutover receipt fails closed."""

    commit, tree = accelerate_identity
    issued, expires = _fresh_window()
    cutover = verifier.build_cutover_receipt(
        accelerator_commit=commit,
        accelerator_tree=tree,
        store_generation="generation:dqk-057-test",
        schema_checksum="sha256:" + "11" * 32,
        quack_profile="quack-profile:1.5.5-loopback",
        decision_cid="decision:cutover-unsigned",
        issued_at=issued,
        expires_at=expires,
    )
    del cutover["signature"]
    receipt = verifier.build_release_receipt(
        accelerator_commit=commit,
        accelerator_tree=tree,
        store_generation="generation:dqk-057-test",
        schema_checksum="sha256:" + "11" * 32,
        quack_profile="quack-profile:1.5.5-loopback",
        decision_cid="decision:dqk-057-test",
        issued_at=issued,
        expires_at=expires,
        cutover=cutover,
    )
    path = _write_receipt(tmp_path / "unsigned-cutover.json", receipt)
    result = _run_cli(
        "--receipt",
        str(path),
        "--accelerate-root",
        str(accelerate_root),
        "--json",
    )
    assert result.returncode != 0
    assert (
        "unsigned" in result.stderr.lower()
        or "signature" in result.stderr.lower()
        or "cutover" in result.stderr.lower()
    )


def test_expired_cutover_is_rejected(
    accelerate_root: Path,
    accelerate_identity: tuple[str, str],
    tmp_path: Path,
) -> None:
    """Acceptance: an expired cutover receipt fails closed even if release is live."""

    commit, tree = accelerate_identity
    issued, expires = _fresh_window()
    cutover = verifier.build_cutover_receipt(
        accelerator_commit=commit,
        accelerator_tree=tree,
        store_generation="generation:dqk-057-test",
        schema_checksum="sha256:" + "11" * 32,
        quack_profile="quack-profile:1.5.5-loopback",
        decision_cid="decision:cutover-expired",
        issued_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        expires_at=datetime(2020, 1, 2, tzinfo=timezone.utc),
    )
    receipt = verifier.build_release_receipt(
        accelerator_commit=commit,
        accelerator_tree=tree,
        store_generation="generation:dqk-057-test",
        schema_checksum="sha256:" + "11" * 32,
        quack_profile="quack-profile:1.5.5-loopback",
        decision_cid="decision:dqk-057-test",
        issued_at=issued,
        expires_at=expires,
        cutover=cutover,
    )
    path = _write_receipt(tmp_path / "expired-cutover.json", receipt)
    result = _run_cli(
        "--receipt",
        str(path),
        "--accelerate-root",
        str(accelerate_root),
        "--json",
    )
    assert result.returncode != 0
    assert "expired" in result.stderr.lower() or "cutover" in result.stderr.lower()


def test_cutover_issued_after_expires_is_rejected(
    accelerate_root: Path,
    accelerate_identity: tuple[str, str],
    tmp_path: Path,
) -> None:
    """Cutover issued_at after expires_at fails closed (parity with release)."""

    commit, tree = accelerate_identity
    issued, expires = _fresh_window()
    cutover = verifier.build_cutover_receipt(
        accelerator_commit=commit,
        accelerator_tree=tree,
        store_generation="generation:dqk-057-test",
        schema_checksum="sha256:" + "11" * 32,
        quack_profile="quack-profile:1.5.5-loopback",
        decision_cid="decision:cutover-ordering",
        issued_at=expires + timedelta(hours=1),
        expires_at=expires,
    )
    receipt = verifier.build_release_receipt(
        accelerator_commit=commit,
        accelerator_tree=tree,
        store_generation="generation:dqk-057-test",
        schema_checksum="sha256:" + "11" * 32,
        quack_profile="quack-profile:1.5.5-loopback",
        decision_cid="decision:dqk-057-test",
        issued_at=issued,
        expires_at=expires,
        cutover=cutover,
    )
    path = _write_receipt(tmp_path / "cutover-ordering.json", receipt)
    result = _run_cli(
        "--receipt",
        str(path),
        "--accelerate-root",
        str(accelerate_root),
        "--json",
    )
    assert result.returncode != 0
    assert (
        "issued_at" in result.stderr.lower()
        or "expires" in result.stderr.lower()
        or "cutover" in result.stderr.lower()
    )


def test_verification_object_exposes_gate_cas_fields(
    accelerate_root: Path,
    accelerate_identity: tuple[str, str],
    tmp_path: Path,
) -> None:
    """Success emission must include every string field the gate CAS binds."""

    commit, tree = accelerate_identity
    receipt = _valid_receipt(commit, tree)
    path = _write_receipt(tmp_path / "gate-fields.json", receipt)
    result = _run_cli(
        "--receipt",
        str(path),
        "--accelerate-root",
        str(accelerate_root),
        "--json",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    required = (
        "accelerator_commit",
        "accelerator_tree",
        "release_receipt_cid",
        "cutover_receipt_cid",
        "store_generation",
        "schema_checksum",
        "quack_profile",
        "decision_cid",
        "expires_at",
    )
    assert payload["schema"] == verifier.VERIFICATION_SCHEMA
    assert payload["accepted"] is True
    for field in required:
        assert isinstance(payload.get(field), str) and payload[field].strip()


def test_unaccepted_cutover_is_rejected(
    accelerate_root: Path,
    accelerate_identity: tuple[str, str],
    tmp_path: Path,
) -> None:
    commit, tree = accelerate_identity
    issued, expires = _fresh_window()
    cutover = verifier.build_cutover_receipt(
        accelerator_commit=commit,
        accelerator_tree=tree,
        store_generation="generation:dqk-057-test",
        schema_checksum="sha256:" + "11" * 32,
        quack_profile="quack-profile:1.5.5-loopback",
        decision_cid="decision:cutover-reject",
        issued_at=issued,
        expires_at=expires,
        accepted=False,
        decision="rejected",
    )
    # Seal after forcing unaccepted decision.
    cutover["accepted"] = False
    cutover["decision"] = "rejected"
    cutover.pop("signature", None)
    cutover.pop("receipt_cid", None)
    cutover = verifier.seal_receipt(cutover)

    receipt = verifier.build_release_receipt(
        accelerator_commit=commit,
        accelerator_tree=tree,
        store_generation="generation:dqk-057-test",
        schema_checksum="sha256:" + "11" * 32,
        quack_profile="quack-profile:1.5.5-loopback",
        decision_cid="decision:dqk-057-test",
        issued_at=issued,
        expires_at=expires,
        cutover=cutover,
    )
    path = _write_receipt(tmp_path / "unaccepted.json", receipt)
    result = _run_cli(
        "--receipt",
        str(path),
        "--accelerate-root",
        str(accelerate_root),
        "--json",
    )
    assert result.returncode != 0
    assert (
        "unaccepted" in result.stderr.lower()
        or "accepted" in result.stderr.lower()
        or "decision" in result.stderr.lower()
    )


def test_mismatched_cutover_join_is_rejected(
    accelerate_root: Path,
    accelerate_identity: tuple[str, str],
    tmp_path: Path,
) -> None:
    commit, tree = accelerate_identity
    issued, expires = _fresh_window()
    cutover = verifier.build_cutover_receipt(
        accelerator_commit=commit,
        accelerator_tree=tree,
        store_generation="generation:other",
        schema_checksum="sha256:" + "22" * 32,
        quack_profile="quack-profile:other",
        decision_cid="decision:cutover-other",
        issued_at=issued,
        expires_at=expires,
    )
    receipt = verifier.build_release_receipt(
        accelerator_commit=commit,
        accelerator_tree=tree,
        store_generation="generation:dqk-057-test",
        schema_checksum="sha256:" + "11" * 32,
        quack_profile="quack-profile:1.5.5-loopback",
        decision_cid="decision:dqk-057-test",
        issued_at=issued,
        expires_at=expires,
        cutover=cutover,
    )
    path = _write_receipt(tmp_path / "join-mismatch.json", receipt)
    result = _run_cli(
        "--receipt",
        str(path),
        "--accelerate-root",
        str(accelerate_root),
        "--json",
    )
    assert result.returncode != 0
    assert "mismatch" in result.stderr.lower()


def test_cutover_receipt_cid_must_match_joined_body(
    accelerate_root: Path,
    accelerate_identity: tuple[str, str],
    tmp_path: Path,
) -> None:
    commit, tree = accelerate_identity
    receipt = _valid_receipt(commit, tree)
    receipt["cutover_receipt_cid"] = "sha256:" + "ab" * 32
    receipt.pop("signature", None)
    receipt.pop("receipt_cid", None)
    receipt = verifier.seal_receipt(receipt)
    path = _write_receipt(tmp_path / "cid-mismatch.json", receipt)
    result = _run_cli(
        "--receipt",
        str(path),
        "--accelerate-root",
        str(accelerate_root),
        "--json",
    )
    assert result.returncode != 0
    assert "cutover" in result.stderr.lower()


def test_missing_receipt_argument_fails() -> None:
    result = _run_cli("--json")
    assert result.returncode != 0


def test_missing_accelerate_root_fails(tmp_path: Path) -> None:
    path = _write_receipt(tmp_path / "r.json", {"schema": "x"})
    result = _run_cli("--receipt", str(path), "--json")
    assert result.returncode != 0


def test_tampered_query_identity_fails_closed(
    accelerate_root: Path,
    accelerate_identity: tuple[str, str],
    tmp_path: Path,
) -> None:
    """query_identity must recompute from the canonical query body."""

    commit, tree = accelerate_identity
    receipt = _valid_receipt(commit, tree)
    query = dict(receipt["canonical_query"])
    query["query_identity"] = "sha256:" + ("00" * 32)
    receipt["canonical_query"] = query
    # Re-seal after tamper so the signature is valid but the identity is not.
    del receipt["signature"]
    del receipt["receipt_cid"]
    receipt = verifier.seal_receipt(receipt)
    path = _write_receipt(tmp_path / "bad-query-identity.json", receipt)
    result = _run_cli(
        "--receipt",
        str(path),
        "--accelerate-root",
        str(accelerate_root),
        "--json",
    )
    assert result.returncode != 0
    combined = (result.stderr + result.stdout).lower()
    assert "query_identity" in combined


def test_tampered_result_identity_fails_closed(
    accelerate_root: Path,
    accelerate_identity: tuple[str, str],
    tmp_path: Path,
) -> None:
    """result_identity must recompute from the receipt material."""

    commit, tree = accelerate_identity
    receipt = _valid_receipt(commit, tree)
    query = dict(receipt["canonical_query"])
    query["result_identity"] = "sha256:" + ("11" * 32)
    receipt["canonical_query"] = query
    del receipt["signature"]
    del receipt["receipt_cid"]
    receipt = verifier.seal_receipt(receipt)
    path = _write_receipt(tmp_path / "bad-result-identity.json", receipt)
    result = _run_cli(
        "--receipt",
        str(path),
        "--accelerate-root",
        str(accelerate_root),
        "--json",
    )
    assert result.returncode != 0
    combined = (result.stderr + result.stdout).lower()
    assert "result_identity" in combined


def test_unsupported_release_keys_fail_closed(
    accelerate_root: Path,
    accelerate_identity: tuple[str, str],
    tmp_path: Path,
) -> None:
    """Closed key sets reject free-form status smuggled into the release body."""

    commit, tree = accelerate_identity
    receipt = _valid_receipt(commit, tree)
    receipt["master_alive"] = True
    receipt["release_status"] = "completed"
    del receipt["signature"]
    del receipt["receipt_cid"]
    receipt = verifier.seal_receipt(receipt)
    path = _write_receipt(tmp_path / "extra-keys.json", receipt)
    result = _run_cli(
        "--receipt",
        str(path),
        "--accelerate-root",
        str(accelerate_root),
        "--json",
    )
    assert result.returncode != 0
    combined = (result.stderr + result.stdout).lower()
    assert (
        "unsupported" in combined
        or "process status" in combined
        or "cannot satisfy" in combined
    )


def test_verification_object_uses_closed_key_set(
    accelerate_root: Path,
    accelerate_identity: tuple[str, str],
) -> None:
    """Gate CAS object must expose exactly the accepted typed fields."""

    commit, tree = accelerate_identity
    receipt = _valid_receipt(commit, tree)
    verification = verifier.verify_release_receipt(
        receipt, accelerate_root=accelerate_root
    )
    assert set(verification) == verifier._VERIFICATION_KEYS
    assert verification["schema"] == verifier.VERIFICATION_SCHEMA
    assert verification["accepted"] is True


def test_string_true_accepted_flag_fails_closed(
    accelerate_root: Path,
    accelerate_identity: tuple[str, str],
    tmp_path: Path,
) -> None:
    """String ``\"true\"`` must not satisfy the boolean accepted decision flag."""

    commit, tree = accelerate_identity
    receipt = _valid_receipt(commit, tree)
    receipt["accepted"] = "true"
    del receipt["signature"]
    del receipt["receipt_cid"]
    receipt = verifier.seal_receipt(receipt)
    path = _write_receipt(tmp_path / "string-true-accepted.json", receipt)
    result = _run_cli(
        "--receipt",
        str(path),
        "--accelerate-root",
        str(accelerate_root),
        "--json",
    )
    assert result.returncode != 0
    combined = (result.stderr + result.stdout).lower()
    assert "accepted" in combined or "boolean" in combined


def test_numeric_accepted_flag_fails_closed(
    accelerate_root: Path,
    accelerate_identity: tuple[str, str],
    tmp_path: Path,
) -> None:
    """Integer ``1`` must not satisfy the boolean accepted decision flag."""

    commit, tree = accelerate_identity
    receipt = _valid_receipt(commit, tree)
    receipt["accepted"] = 1
    del receipt["signature"]
    del receipt["receipt_cid"]
    receipt = verifier.seal_receipt(receipt)
    path = _write_receipt(tmp_path / "numeric-accepted.json", receipt)
    result = _run_cli(
        "--receipt",
        str(path),
        "--accelerate-root",
        str(accelerate_root),
        "--json",
    )
    assert result.returncode != 0
    combined = (result.stderr + result.stdout).lower()
    assert "accepted" in combined or "boolean" in combined or "numeric" in combined


def test_duplicate_decision_cid_between_release_and_cutover_fails(
    accelerate_root: Path,
    accelerate_identity: tuple[str, str],
    tmp_path: Path,
) -> None:
    """Joined release and cutover must carry distinct decision CIDs."""

    commit, tree = accelerate_identity
    issued, expires = _fresh_window()
    cutover = verifier.build_cutover_receipt(
        accelerator_commit=commit,
        accelerator_tree=tree,
        store_generation="generation:dqk-057-test",
        schema_checksum="sha256:" + "11" * 32,
        quack_profile="quack-profile:1.5.5-loopback",
        decision_cid="decision:shared",
        issued_at=issued,
        expires_at=expires,
    )
    receipt = verifier.build_release_receipt(
        accelerator_commit=commit,
        accelerator_tree=tree,
        store_generation="generation:dqk-057-test",
        schema_checksum="sha256:" + "11" * 32,
        quack_profile="quack-profile:1.5.5-loopback",
        decision_cid="decision:shared",
        issued_at=issued,
        expires_at=expires,
        cutover=cutover,
    )
    path = _write_receipt(tmp_path / "duplicate-decision.json", receipt)
    result = _run_cli(
        "--receipt",
        str(path),
        "--accelerate-root",
        str(accelerate_root),
        "--json",
    )
    assert result.returncode != 0
    combined = (result.stderr + result.stdout).lower()
    assert "decision_cid" in combined or "distinct" in combined


def test_cutover_expiry_outliving_release_fails(
    accelerate_root: Path,
    accelerate_identity: tuple[str, str],
    tmp_path: Path,
) -> None:
    """Nested cutover expiry must not outlive the terminal release expiry."""

    commit, tree = accelerate_identity
    now = datetime.now(timezone.utc)
    issued = now - timedelta(minutes=5)
    release_expires = now + timedelta(hours=1)
    cutover_expires = now + timedelta(hours=3)
    cutover = verifier.build_cutover_receipt(
        accelerator_commit=commit,
        accelerator_tree=tree,
        store_generation="generation:dqk-057-test",
        schema_checksum="sha256:" + "11" * 32,
        quack_profile="quack-profile:1.5.5-loopback",
        decision_cid="decision:dqk-057-test:cutover",
        issued_at=issued,
        expires_at=cutover_expires,
    )
    receipt = verifier.build_release_receipt(
        accelerator_commit=commit,
        accelerator_tree=tree,
        store_generation="generation:dqk-057-test",
        schema_checksum="sha256:" + "11" * 32,
        quack_profile="quack-profile:1.5.5-loopback",
        decision_cid="decision:dqk-057-test",
        issued_at=issued,
        expires_at=release_expires,
        cutover=cutover,
    )
    path = _write_receipt(tmp_path / "cutover-outlives.json", receipt)
    result = _run_cli(
        "--receipt",
        str(path),
        "--accelerate-root",
        str(accelerate_root),
        "--json",
    )
    assert result.returncode != 0
    combined = (result.stderr + result.stdout).lower()
    assert "expir" in combined or "outlive" in combined


def test_future_issued_at_fails_closed(
    accelerate_root: Path,
    accelerate_identity: tuple[str, str],
    tmp_path: Path,
) -> None:
    """Authority issued far in the future is rejected beyond clock skew."""

    commit, tree = accelerate_identity
    now = datetime.now(timezone.utc)
    issued = now + timedelta(hours=6)
    expires = now + timedelta(hours=12)
    receipt = _valid_receipt(commit, tree, issued_at=issued, expires_at=expires)
    path = _write_receipt(tmp_path / "future-issued.json", receipt)
    result = _run_cli(
        "--receipt",
        str(path),
        "--accelerate-root",
        str(accelerate_root),
        "--json",
    )
    assert result.returncode != 0
    combined = (result.stderr + result.stdout).lower()
    assert "future" in combined or "issued_at" in combined or "skew" in combined

