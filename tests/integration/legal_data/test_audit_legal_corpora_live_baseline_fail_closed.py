"""Hermetic fail-closed matrix for LCR-081. Pytest must not open a network socket."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.ops.legal_data.audit_federal_register_hf_baseline import (
    PINNED_REVISION as FEDERAL_PIN,
)
from scripts.ops.legal_data.audit_legal_corpora_live_baseline import (
    FEDERAL_REPO_ID,
    MODE_LIVE,
    STATE_PINNED_REVISION,
    STATE_REPO_ID,
    LiveBaselineAuditError,
    ScriptedHubTransport,
    build_receipt,
    dataset_resolve_url,
    dataset_revision_url,
    dataset_tree_url,
    datasets_server_url,
    persist_and_verify_receipt,
    require_commit_sha,
    seal_receipt,
    state_partition_path,
    validate_receipt,
)
from tests.unit.scripts.test_audit_legal_corpora_live_baseline import (
    SCRIPT_TOKEN,
    _observe,
    _salvage_roots,
    _state_tree_items,
    build_scripted_responses,
    partition_parquets,
    viewer_parquets,
)


pytestmark = pytest.mark.integration


def _build(
    partition_parquets: dict[str, bytes],
    viewer_parquets: dict[str, bytes],
    tmp_path: Path,
    responses: dict[str, Any] | None = None,
    salvage_roots: list[tuple[str, Path]] | None = None,
) -> dict[str, Any]:
    transport = ScriptedHubTransport(
        responses or build_scripted_responses(partition_parquets, viewer_parquets),
        token=SCRIPT_TOKEN,
    )
    return build_receipt(
        transport=transport,
        token=SCRIPT_TOKEN,
        token_source="test",
        salvage_roots=salvage_roots or _salvage_roots(tmp_path),
        observed_at="2026-08-21T12:00:00.000Z",
        mode=MODE_LIVE,
    )


def test_production_live_mode_rejects_scripted_fixture(
    partition_parquets: dict[str, bytes],
    viewer_parquets: dict[str, bytes],
    tmp_path: Path,
) -> None:
    receipt = _observe(partition_parquets, viewer_parquets, tmp_path)
    with pytest.raises(LiveBaselineAuditError, match="fixture"):
        validate_receipt(
            receipt,
            require_live_hub=True,
            require_local_salvage_inventory=True,
        )


def test_mutable_revision_tokens_never_authorize() -> None:
    for token in ("main", "latest", "HEAD", "", "master"):
        with pytest.raises(LiveBaselineAuditError, match="40-hex|mutable"):
            require_commit_sha(token, "pin")


def test_pagination_next_page_missing_fails(
    partition_parquets: dict[str, bytes],
    viewer_parquets: dict[str, bytes],
    tmp_path: Path,
) -> None:
    responses = build_scripted_responses(partition_parquets, viewer_parquets)
    tree_url = dataset_tree_url(STATE_REPO_ID, STATE_PINNED_REVISION)
    nxt = f"{tree_url}&cursor=truncated-page"
    responses[f"GET {tree_url}"] = {
        "status": 200,
        "headers": {"Link": f'<{nxt}>; rel="next"'},
        "body": json.dumps(_state_tree_items()[:12]),
    }
    with pytest.raises(LiveBaselineAuditError, match="pagination|missing"):
        _build(partition_parquets, viewer_parquets, tmp_path, responses=responses)


def test_missing_dc_and_parquet_read_failures(
    partition_parquets: dict[str, bytes],
    viewer_parquets: dict[str, bytes],
    tmp_path: Path,
) -> None:
    with pytest.raises(LiveBaselineAuditError, match="DC"):
        _observe(partition_parquets, viewer_parquets, tmp_path, include_dc=False)
    responses = build_scripted_responses(partition_parquets, viewer_parquets)
    url = dataset_resolve_url(
        STATE_REPO_ID, STATE_PINNED_REVISION, state_partition_path("OR")
    )
    responses[f"GET {url}"] = {"status": 500, "headers": {}, "body": b"nope"}
    with pytest.raises(LiveBaselineAuditError, match="Parquet"):
        _build(partition_parquets, viewer_parquets, tmp_path, responses=responses)


def test_viewer_config_omission_and_missing_response_hashes(
    partition_parquets: dict[str, bytes],
    viewer_parquets: dict[str, bytes],
    tmp_path: Path,
) -> None:
    responses = build_scripted_responses(partition_parquets, viewer_parquets)
    del responses[f"GET {datasets_server_url('info', FEDERAL_REPO_ID, FEDERAL_PIN)}"]
    with pytest.raises(LiveBaselineAuditError, match="Viewer|scripted Hub missing"):
        _build(partition_parquets, viewer_parquets, tmp_path, responses=responses)
    receipt = _observe(partition_parquets, viewer_parquets, tmp_path)
    receipt["requests"][0]["response_sha256"] = ""
    with pytest.raises(LiveBaselineAuditError, match="response_sha256"):
        validate_receipt(receipt, require_live_hub=False)


def test_salvage_inaccessible_sampled_truncated_and_symlink_escape(
    partition_parquets: dict[str, bytes],
    viewer_parquets: dict[str, bytes],
    tmp_path: Path,
) -> None:
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    blocked.chmod(0o000)
    try:
        with pytest.raises(
            LiveBaselineAuditError, match="empty salvage|inaccessible|all-missing"
        ):
            _build(
                partition_parquets,
                viewer_parquets,
                tmp_path,
                salvage_roots=[("blocked", blocked)],
            )
    finally:
        blocked.chmod(0o755)
    receipt = _observe(partition_parquets, viewer_parquets, tmp_path)
    receipt["local_salvage"]["truncated"] = True
    with pytest.raises(LiveBaselineAuditError, match="sampled or truncated"):
        validate_receipt(receipt, require_live_hub=False)
    receipt = _observe(partition_parquets, viewer_parquets, tmp_path)
    receipt["local_salvage"]["roots"][0]["symlink_escape"] = True
    with pytest.raises(LiveBaselineAuditError, match="symlink escape"):
        validate_receipt(receipt, require_live_hub=False)


def test_on_disk_receipt_required_and_nested_digest_mismatch(
    partition_parquets: dict[str, bytes],
    viewer_parquets: dict[str, bytes],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = _observe(partition_parquets, viewer_parquets, tmp_path)
    missing = tmp_path / "no-receipt.json"
    monkeypatch.setattr(
        "scripts.ops.legal_data.audit_legal_corpora_live_baseline.write_receipt",
        lambda *_a, **_k: missing,
    )
    with pytest.raises(LiveBaselineAuditError, match="absent on-disk receipt"):
        persist_and_verify_receipt(receipt, missing)
    receipt = _observe(partition_parquets, viewer_parquets, tmp_path)
    receipt["digests"]["federal_row_count_sha256"] = "d" * 64
    with pytest.raises(LiveBaselineAuditError, match="row digest mismatch"):
        validate_receipt(receipt, require_live_hub=False)
    receipt = _observe(partition_parquets, viewer_parquets, tmp_path)
    receipt["receipt_sha256"] = "e" * 64
    with pytest.raises(LiveBaselineAuditError, match="root digest mismatch"):
        validate_receipt(receipt, require_live_hub=False)


def test_token_and_path_leakage_denied(
    partition_parquets: dict[str, bytes],
    viewer_parquets: dict[str, bytes],
    tmp_path: Path,
) -> None:
    receipt = _observe(partition_parquets, viewer_parquets, tmp_path)
    receipt["note"] = "hf_" + ("z" * 20)
    with pytest.raises(LiveBaselineAuditError, match="token leakage"):
        seal_receipt(dict(receipt), None)
    receipt = _observe(partition_parquets, viewer_parquets, tmp_path)
    roots = _salvage_roots(tmp_path)
    receipt["note"] = str(roots[1][1])
    with pytest.raises(LiveBaselineAuditError, match="path leakage"):
        seal_receipt(dict(receipt), SCRIPT_TOKEN, salvage_roots=roots)


def test_stale_pin_and_malformed_utc(
    partition_parquets: dict[str, bytes],
    viewer_parquets: dict[str, bytes],
    tmp_path: Path,
) -> None:
    responses = build_scripted_responses(partition_parquets, viewer_parquets)
    url = dataset_revision_url(STATE_REPO_ID, STATE_PINNED_REVISION)
    payload = json.loads(responses[f"GET {url}"]["body"])
    payload["sha"] = "ffffffffffffffffffffffffffffffffffffffff"
    responses[f"GET {url}"] = {"status": 200, "headers": {}, "body": json.dumps(payload)}
    with pytest.raises(LiveBaselineAuditError, match="stale or changed pin"):
        _build(partition_parquets, viewer_parquets, tmp_path, responses=responses)
    receipt = _observe(partition_parquets, viewer_parquets, tmp_path)
    receipt["observed_at"] = "2026-08-21 12:00:00"
    with pytest.raises(LiveBaselineAuditError, match="UTC"):
        validate_receipt(receipt, require_live_hub=False)


def test_successful_scripted_observation_still_cannot_claim_live_hub(
    partition_parquets: dict[str, bytes],
    viewer_parquets: dict[str, bytes],
    tmp_path: Path,
) -> None:
    receipt = _observe(partition_parquets, viewer_parquets, tmp_path)
    result = validate_receipt(
        receipt, require_live_hub=False, require_local_salvage_inventory=True
    )
    assert result["ok"] is True
    assert receipt["live_hub_contacted"] is False
    path = tmp_path / "on_disk.json"
    persist_and_verify_receipt(
        receipt,
        path,
        require_live_hub=False,
        require_local_salvage_inventory=True,
    )
    dumped = path.read_text(encoding="utf-8")
    assert SCRIPT_TOKEN not in dumped
    assert "hf_" not in dumped
    assert "DC" in receipt["state_laws"]["partitions"]
    assert len(receipt["state_laws"]["partitions"]) == 51
