"""Integration tests for the fail-closed external DQP release verifier (DQK-057).

Acceptance:

* CLI accepts ``--receipt``, ``--accelerate-root`` and ``--json`` and emits
  ``ipfs_accelerate_py/agent-supervisor/duckdb-quack-release-verification@1``
* Markdown and process status cannot satisfy the gate
* Missing canonical receipt query or machine-readable identity fails closed
* A stale, mismatched, expired, unsigned, or unaccepted cutover receipt is
  rejected
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping

import pytest

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts/validation/validate_accelerate_duckdb_quack_release.py"


def _load_verifier() -> ModuleType:
    """Load the verifier module by path (no package __init__ required)."""

    spec = importlib.util.spec_from_file_location(
        "validate_accelerate_duckdb_quack_release",
        SCRIPT,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


verifier = _load_verifier()
FIXED_NOW = datetime(2026, 8, 9, 12, 0, 0, tzinfo=timezone.utc)
FUTURE = (FIXED_NOW + timedelta(hours=6)).isoformat().replace("+00:00", "Z")
PAST = (FIXED_NOW - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
SCHEMA_CHECKSUM = "sha256:" + ("c0" * 32)
QUACK_PROFILE = "profile:quack-1.5.5-loopback"
STORE_GENERATION = "generation:dqp-039-1"


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


@pytest.fixture()
def accelerate_repo(tmp_path: Path) -> Path:
    root = tmp_path / "accelerate"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.name", "DQK-057 Test")
    _git(root, "config", "user.email", "dqk057@example.invalid")
    (root / "README.md").write_text("accelerate fixture\n", encoding="utf-8")
    _git(root, "add", "--", "README.md")
    _git(root, "commit", "-m", "fixture accelerator release")
    return root


def _commit_tree(accelerate_repo: Path) -> tuple[str, str]:
    commit = _git(accelerate_repo, "rev-parse", "HEAD").lower()
    tree = _git(accelerate_repo, "rev-parse", "HEAD^{tree}").lower()
    return commit, tree


def _write_receipt(path: Path, envelope: Mapping[str, Any]) -> Path:
    path.write_text(
        json.dumps(envelope, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    return path


def _valid_envelope(accelerate_repo: Path, **kwargs: Any) -> dict[str, Any]:
    commit, tree = _commit_tree(accelerate_repo)
    return verifier.build_signed_gate_input(
        accelerator_commit=commit,
        accelerator_tree=tree,
        schema_checksum=SCHEMA_CHECKSUM,
        store_generation=STORE_GENERATION,
        quack_profile=QUACK_PROFILE,
        expires_at=kwargs.pop("expires_at", FUTURE),
        **kwargs,
    )


def _run_cli(
    *args: str, check: bool = False
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=check,
    )


# ---------------------------------------------------------------------------
# Module surface / self-check
# ---------------------------------------------------------------------------


def test_script_is_materialized_and_executable_contract() -> None:
    assert SCRIPT.is_file()
    assert verifier.VERIFICATION_SCHEMA == (
        "ipfs_accelerate_py/agent-supervisor/duckdb-quack-release-verification@1"
    )
    assert verifier.RELEASE_INTERFACE == "DuckDBControlPlaneReleaseReceipt@1"
    assert verifier.CUTOVER_INTERFACE == "DatabaseCutoverReceipt@1"


def test_cli_check_mode_loads_without_receipt() -> None:
    result = _run_cli("--check", "--json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["schema"] == verifier.VERIFICATION_SCHEMA
    assert payload["check"] == "ok"
    assert payload["accepted"] is False


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_cli_accepts_receipt_accelerate_root_and_json(
    tmp_path: Path, accelerate_repo: Path
) -> None:
    envelope = _valid_envelope(accelerate_repo)
    receipt = _write_receipt(tmp_path / "release.json", envelope)
    result = _run_cli(
        "--receipt",
        str(receipt),
        "--accelerate-root",
        str(accelerate_repo),
        "--json",
        "--now",
        FIXED_NOW.isoformat(),
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    commit, tree = _commit_tree(accelerate_repo)
    assert payload == {
        "schema": verifier.VERIFICATION_SCHEMA,
        "accepted": True,
        "accelerator_commit": commit,
        "accelerator_tree": tree,
        "release_receipt_cid": envelope["release_receipt"]["identity_id"],
        "cutover_receipt_cid": envelope["cutover_receipt"]["identity_id"],
        "store_generation": STORE_GENERATION,
        "schema_checksum": SCHEMA_CHECKSUM,
        "quack_profile": QUACK_PROFILE,
        "decision_cid": envelope["decision_cid"],
        "expires_at": FUTURE,
    }
    # Gate CAS field contracts.
    assert payload["schema_checksum"].startswith("sha256:")
    assert len(payload["accelerator_commit"]) == 40
    assert len(payload["accelerator_tree"]) == 40
    for field in (
        "release_receipt_cid",
        "cutover_receipt_cid",
        "store_generation",
        "quack_profile",
        "decision_cid",
        "expires_at",
    ):
        assert isinstance(payload[field], str) and payload[field].strip()


def test_verify_api_matches_cli(
    tmp_path: Path, accelerate_repo: Path
) -> None:
    envelope = _valid_envelope(accelerate_repo)
    receipt = _write_receipt(tmp_path / "release.json", envelope)
    via_api = verifier.verify_receipt_file(
        receipt,
        accelerate_root=accelerate_repo,
        now=FIXED_NOW,
    )
    result = _run_cli(
        "--receipt",
        str(receipt),
        "--accelerate-root",
        str(accelerate_repo),
        "--json",
        "--now",
        FIXED_NOW.isoformat(),
    )
    assert result.returncode == 0
    assert json.loads(result.stdout) == via_api


# ---------------------------------------------------------------------------
# Markdown / process status cannot satisfy the gate
# ---------------------------------------------------------------------------


def test_markdown_board_is_rejected(tmp_path: Path, accelerate_repo: Path) -> None:
    board = tmp_path / "board.md"
    board.write_text(
        "# DQP board\n\n## DQP-039\n\n- Status: completed\n",
        encoding="utf-8",
    )
    result = _run_cli(
        "--receipt",
        str(board),
        "--accelerate-root",
        str(accelerate_repo),
        "--json",
    )
    assert result.returncode != 0
    assert "markdown" in (result.stderr + result.stdout).lower()


def test_process_status_json_is_rejected(
    tmp_path: Path, accelerate_repo: Path
) -> None:
    status = {
        "program_id": "agent-supervisor-duckdb-quack-control-plane-v1",
        "master_pid": 1234,
        "master_alive": True,
        "release_status": "completed",
        "lanes": [],
        "completed_count": 39,
        "task_count": 39,
    }
    path = _write_receipt(tmp_path / "status.json", status)
    result = _run_cli(
        "--receipt",
        str(path),
        "--accelerate-root",
        str(accelerate_repo),
        "--json",
    )
    assert result.returncode != 0
    combined = (result.stderr + result.stdout).lower()
    assert "process status" in combined or "schema is unsupported" in combined


def test_task_status_kind_is_rejected(
    tmp_path: Path, accelerate_repo: Path
) -> None:
    payload = {
        "kind": "task_status",
        "task_id": "DQP-039",
        "status": "completed",
    }
    path = _write_receipt(tmp_path / "task-status.json", payload)
    result = _run_cli(
        "--receipt",
        str(path),
        "--accelerate-root",
        str(accelerate_repo),
        "--json",
    )
    assert result.returncode != 0


# ---------------------------------------------------------------------------
# Missing canonical query / identity fails closed
# ---------------------------------------------------------------------------


def test_missing_canonical_receipt_query_fails_closed(
    tmp_path: Path, accelerate_repo: Path
) -> None:
    envelope = _valid_envelope(accelerate_repo)
    envelope.pop("canonical_receipt_query")
    envelope["signature"] = verifier.compute_signature(envelope)
    path = _write_receipt(tmp_path / "no-query.json", envelope)
    result = _run_cli(
        "--receipt",
        str(path),
        "--accelerate-root",
        str(accelerate_repo),
        "--json",
        "--now",
        FIXED_NOW.isoformat(),
    )
    assert result.returncode != 0
    assert "canonical_receipt_query" in (result.stderr + result.stdout)


def test_tampered_release_identity_fails_closed(
    tmp_path: Path, accelerate_repo: Path
) -> None:
    envelope = _valid_envelope(accelerate_repo)
    envelope["release_receipt"]["identity_id"] = "sha256:" + ("ff" * 32)
    envelope["canonical_receipt_query"]["release_receipt_cid"] = envelope[
        "release_receipt"
    ]["identity_id"]
    # Recompute decision + signature after tamper.
    body = {
        key: value
        for key, value in envelope.items()
        if key not in {"signature", "decision_cid"}
    }
    envelope["decision_cid"] = verifier.content_identity(
        body, domain=verifier.SIGNATURE_DOMAIN
    )
    envelope["signature"] = verifier.compute_signature(envelope)
    path = _write_receipt(tmp_path / "bad-identity.json", envelope)
    result = _run_cli(
        "--receipt",
        str(path),
        "--accelerate-root",
        str(accelerate_repo),
        "--json",
        "--now",
        FIXED_NOW.isoformat(),
    )
    assert result.returncode != 0
    assert "identity" in (result.stderr + result.stdout).lower()


def test_missing_receipt_flag_fails_closed(accelerate_repo: Path) -> None:
    result = _run_cli("--accelerate-root", str(accelerate_repo), "--json")
    assert result.returncode != 0
    assert "receipt" in (result.stderr + result.stdout).lower()


# ---------------------------------------------------------------------------
# Stale / mismatched / expired / unsigned / unaccepted cutover
# ---------------------------------------------------------------------------


def test_stale_accelerator_commit_is_rejected(
    tmp_path: Path, accelerate_repo: Path
) -> None:
    commit, tree = _commit_tree(accelerate_repo)
    envelope = verifier.build_signed_gate_input(
        accelerator_commit="a" * 40,
        accelerator_tree=tree,
        schema_checksum=SCHEMA_CHECKSUM,
        store_generation=STORE_GENERATION,
        quack_profile=QUACK_PROFILE,
        expires_at=FUTURE,
        release_overrides={"git_identity": f"git:{'a' * 40}"},
    )
    path = _write_receipt(tmp_path / "stale-commit.json", envelope)
    result = _run_cli(
        "--receipt",
        str(path),
        "--accelerate-root",
        str(accelerate_repo),
        "--json",
        "--now",
        FIXED_NOW.isoformat(),
    )
    assert result.returncode != 0
    assert "accelerator_commit" in (result.stderr + result.stdout)
    del commit


def test_mismatched_schema_checksum_is_rejected(
    tmp_path: Path, accelerate_repo: Path
) -> None:
    envelope = _valid_envelope(
        accelerate_repo,
        cutover_overrides={
            "binding": {"schema_checksum": "sha256:" + ("dd" * 32)},
        },
    )
    # Rebuild cutover signature/identity after binding override.
    cut = dict(envelope["cutover_receipt"])
    cut.pop("signature", None)
    cut.pop("identity_id", None)
    cut["signature"] = verifier.cutover_signature_for(cut)
    cut = verifier.attach_identity(cut)
    envelope["cutover_receipt"] = cut
    envelope["canonical_receipt_query"]["cutover_receipt_cid"] = cut["identity_id"]
    body = {
        key: value
        for key, value in envelope.items()
        if key not in {"signature", "decision_cid"}
    }
    envelope["decision_cid"] = verifier.content_identity(
        body, domain=verifier.SIGNATURE_DOMAIN
    )
    envelope["signature"] = verifier.compute_signature(envelope)
    path = _write_receipt(tmp_path / "mismatch.json", envelope)
    result = _run_cli(
        "--receipt",
        str(path),
        "--accelerate-root",
        str(accelerate_repo),
        "--json",
        "--now",
        FIXED_NOW.isoformat(),
    )
    assert result.returncode != 0
    assert "mismatch" in (result.stderr + result.stdout).lower()


def test_expired_cutover_receipt_is_rejected(
    tmp_path: Path, accelerate_repo: Path
) -> None:
    envelope = _valid_envelope(
        accelerate_repo,
        expires_at=FUTURE,
        cutover_overrides={"expires_at": PAST},
    )
    cut = dict(envelope["cutover_receipt"])
    cut["expires_at"] = PAST
    cut.pop("signature", None)
    cut.pop("identity_id", None)
    cut["signature"] = verifier.cutover_signature_for(cut)
    cut = verifier.attach_identity(cut)
    envelope["cutover_receipt"] = cut
    envelope["canonical_receipt_query"]["cutover_receipt_cid"] = cut["identity_id"]
    body = {
        key: value
        for key, value in envelope.items()
        if key not in {"signature", "decision_cid"}
    }
    envelope["decision_cid"] = verifier.content_identity(
        body, domain=verifier.SIGNATURE_DOMAIN
    )
    envelope["signature"] = verifier.compute_signature(envelope)
    path = _write_receipt(tmp_path / "expired-cutover.json", envelope)
    result = _run_cli(
        "--receipt",
        str(path),
        "--accelerate-root",
        str(accelerate_repo),
        "--json",
        "--now",
        FIXED_NOW.isoformat(),
    )
    assert result.returncode != 0
    assert "expired" in (result.stderr + result.stdout).lower()


def test_expired_envelope_is_rejected(
    tmp_path: Path, accelerate_repo: Path
) -> None:
    envelope = _valid_envelope(accelerate_repo, expires_at=PAST)
    path = _write_receipt(tmp_path / "expired-envelope.json", envelope)
    result = _run_cli(
        "--receipt",
        str(path),
        "--accelerate-root",
        str(accelerate_repo),
        "--json",
        "--now",
        FIXED_NOW.isoformat(),
    )
    assert result.returncode != 0
    assert "expired" in (result.stderr + result.stdout).lower()


def test_unsigned_cutover_receipt_is_rejected(
    tmp_path: Path, accelerate_repo: Path
) -> None:
    envelope = _valid_envelope(accelerate_repo)
    cut = dict(envelope["cutover_receipt"])
    cut.pop("signature", None)
    cut.pop("identity_id", None)
    cut = verifier.attach_identity(cut)
    envelope["cutover_receipt"] = cut
    envelope["canonical_receipt_query"]["cutover_receipt_cid"] = cut["identity_id"]
    body = {
        key: value
        for key, value in envelope.items()
        if key not in {"signature", "decision_cid"}
    }
    envelope["decision_cid"] = verifier.content_identity(
        body, domain=verifier.SIGNATURE_DOMAIN
    )
    envelope["signature"] = verifier.compute_signature(envelope)
    path = _write_receipt(tmp_path / "unsigned-cutover.json", envelope)
    result = _run_cli(
        "--receipt",
        str(path),
        "--accelerate-root",
        str(accelerate_repo),
        "--json",
        "--now",
        FIXED_NOW.isoformat(),
    )
    assert result.returncode != 0
    assert "unsigned" in (result.stderr + result.stdout).lower()


def test_unsigned_envelope_is_rejected(
    tmp_path: Path, accelerate_repo: Path
) -> None:
    envelope = _valid_envelope(accelerate_repo)
    envelope.pop("signature")
    path = _write_receipt(tmp_path / "unsigned-envelope.json", envelope)
    result = _run_cli(
        "--receipt",
        str(path),
        "--accelerate-root",
        str(accelerate_repo),
        "--json",
        "--now",
        FIXED_NOW.isoformat(),
    )
    assert result.returncode != 0
    assert "unsigned" in (result.stderr + result.stdout).lower()


def test_unaccepted_cutover_receipt_is_rejected(
    tmp_path: Path, accelerate_repo: Path
) -> None:
    envelope = _valid_envelope(
        accelerate_repo,
        cutover_overrides={
            "verdict": "held",
            "promoted": False,
            "accepted": False,
        },
    )
    cut = dict(envelope["cutover_receipt"])
    cut["verdict"] = "held"
    cut["promoted"] = False
    cut["accepted"] = False
    cut.pop("signature", None)
    cut.pop("identity_id", None)
    cut["signature"] = verifier.cutover_signature_for(cut)
    cut = verifier.attach_identity(cut)
    envelope["cutover_receipt"] = cut
    envelope["canonical_receipt_query"]["cutover_receipt_cid"] = cut["identity_id"]
    body = {
        key: value
        for key, value in envelope.items()
        if key not in {"signature", "decision_cid"}
    }
    envelope["decision_cid"] = verifier.content_identity(
        body, domain=verifier.SIGNATURE_DOMAIN
    )
    envelope["signature"] = verifier.compute_signature(envelope)
    path = _write_receipt(tmp_path / "unaccepted-cutover.json", envelope)
    result = _run_cli(
        "--receipt",
        str(path),
        "--accelerate-root",
        str(accelerate_repo),
        "--json",
        "--now",
        FIXED_NOW.isoformat(),
    )
    assert result.returncode != 0
    assert "unaccepted" in (result.stderr + result.stdout).lower()


def test_unaccepted_release_receipt_is_rejected(
    tmp_path: Path, accelerate_repo: Path
) -> None:
    envelope = _valid_envelope(
        accelerate_repo,
        release_overrides={"verdict": "fail", "passed": False},
    )
    release = dict(envelope["release_receipt"])
    release["verdict"] = "fail"
    release["passed"] = False
    release.pop("identity_id", None)
    release = verifier.attach_identity(release)
    envelope["release_receipt"] = release
    envelope["canonical_receipt_query"]["release_receipt_cid"] = release[
        "identity_id"
    ]
    body = {
        key: value
        for key, value in envelope.items()
        if key not in {"signature", "decision_cid"}
    }
    envelope["decision_cid"] = verifier.content_identity(
        body, domain=verifier.SIGNATURE_DOMAIN
    )
    envelope["signature"] = verifier.compute_signature(envelope)
    path = _write_receipt(tmp_path / "unaccepted-release.json", envelope)
    result = _run_cli(
        "--receipt",
        str(path),
        "--accelerate-root",
        str(accelerate_repo),
        "--json",
        "--now",
        FIXED_NOW.isoformat(),
    )
    assert result.returncode != 0


def test_invalid_envelope_signature_is_rejected(
    tmp_path: Path, accelerate_repo: Path
) -> None:
    envelope = _valid_envelope(accelerate_repo)
    envelope["signature"] = "sha256:" + ("00" * 32)
    path = _write_receipt(tmp_path / "bad-sig.json", envelope)
    result = _run_cli(
        "--receipt",
        str(path),
        "--accelerate-root",
        str(accelerate_repo),
        "--json",
        "--now",
        FIXED_NOW.isoformat(),
    )
    assert result.returncode != 0
    assert "signature" in (result.stderr + result.stdout).lower()


def test_symlink_receipt_is_rejected(
    tmp_path: Path, accelerate_repo: Path
) -> None:
    envelope = _valid_envelope(accelerate_repo)
    real = _write_receipt(tmp_path / "real.json", envelope)
    link = tmp_path / "link.json"
    link.symlink_to(real)
    result = _run_cli(
        "--receipt",
        str(link),
        "--accelerate-root",
        str(accelerate_repo),
        "--json",
        "--now",
        FIXED_NOW.isoformat(),
    )
    assert result.returncode != 0
    assert "symlink" in (result.stderr + result.stdout).lower()
