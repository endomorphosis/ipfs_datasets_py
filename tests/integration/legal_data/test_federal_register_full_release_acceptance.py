"""Source-attested LCR-071 Federal full-live acceptance tests."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

import scripts.ops.legal_data.run_federal_register_full_release_acceptance as acceptance


def _write_json(root: Path, relpath: Path, payload: dict) -> None:
    target = root / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _live_workspace(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    total = 3
    payloads = {
        acceptance.CANDIDATE_RELPATH: {
            "authorizing_for_publication": False,
            "authorizing_hub_upload": False,
            "candidate": {"kind": "live_official_complete"},
            "fixture_only": False,
            "mode": "live_official",
        },
        acceptance.INVENTORY_RELPATH: {
            "acceptance": {"mode": "live", "official_total": total},
            "fixture_only": False,
        },
        acceptance.FULLTEXT_RELPATH: {
            "authorizing_for_publication": False,
            "compact_recipe": False,
            "classified": total,
            "failed_final": 0,
            "fixture": {"inventory_documents": total},
            "fixture_only": False,
            "full_text_admitted": total,
            "sample_identity": False,
        },
        acceptance.EVALUATION_RELPATH: {
            "fixture_only": False,
            "gold": {"meets_declared_gates": True},
            "status": "passed",
            "vector": {"meets_declared_gates": True},
        },
        acceptance.ADJACENCY_RELPATH: {
            "fixture_only": False,
            "inversion_holds": True,
            "status": "passed",
        },
        acceptance.LIVE_VECTORS_RELPATH: {
            "backend": "sentence_transformers",
            "centroid_bounds_hold": True,
            "fixture_only": False,
            "status": "passed",
            "vector_count": total,
        },
        acceptance.LIVE_GOLD_RELPATH: {
            "fixture_only": False,
            "status": "passed",
        },
    }
    for relpath, payload in payloads.items():
        _write_json(root, relpath, payload)
    return root


def _build(root: Path) -> dict:
    return acceptance.inspect_production_readiness(
        require_live_official=True,
        require_production_candidate=True,
        repository_root=root,
    )


def test_success_binds_exact_canonical_inputs_and_self_digest(tmp_path: Path) -> None:
    root = _live_workspace(tmp_path)
    report = _build(root)
    assert report["schema"] == acceptance.SCHEMA
    assert report["status"] == "passed"
    assert report["mode"] == "live_official"
    assert report["fixture_only"] is False
    assert report["dirty"] is False
    assert report["authorizing_for_publication"] is False
    assert report["authorizing_hub_upload"] is False
    assert set(report["input_file_sha256"]) == {
        path.as_posix() for path in acceptance.INPUT_RELPATHS
    }
    checked = acceptance.check_full_live_acceptance_report(
        report, repository_root=root
    )
    assert checked == {
        "ok": True,
        "report_digest_sha256": report["report_digest_sha256"],
    }


def test_missing_extra_or_stale_input_digest_fails_closed(tmp_path: Path) -> None:
    root = _live_workspace(tmp_path)
    report = _build(root)
    for mutation in ("missing", "extra", "stale"):
        tampered = deepcopy(report)
        if mutation == "missing":
            tampered["input_file_sha256"].pop(acceptance.CANDIDATE_RELPATH.as_posix())
        elif mutation == "extra":
            tampered["input_file_sha256"]["unexpected.json"] = "0" * 64
        else:
            tampered["input_file_sha256"][acceptance.CANDIDATE_RELPATH.as_posix()] = (
                "0" * 64
            )
        tampered["report_digest_sha256"] = acceptance._report_digest(tampered)
        with pytest.raises(acceptance.AcceptanceError, match="input_file_sha256"):
            acceptance.check_full_live_acceptance_report(
                tampered, repository_root=root
            )


def test_raw_byte_change_invalidates_attestation(tmp_path: Path) -> None:
    root = _live_workspace(tmp_path)
    report = _build(root)
    target = root / acceptance.ADJACENCY_RELPATH
    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(acceptance.AcceptanceError, match="input_file_sha256"):
        acceptance.check_full_live_acceptance_report(report, repository_root=root)


def test_self_digest_and_live_flags_are_strict(tmp_path: Path) -> None:
    root = _live_workspace(tmp_path)
    report = _build(root)
    stale = deepcopy(report)
    stale["report_digest_sha256"] = "0" * 64
    with pytest.raises(acceptance.AcceptanceError, match="self digest"):
        acceptance.check_full_live_acceptance_report(stale, repository_root=root)
    for field, value in (
        ("schema", "ipfs_datasets_py/federal-register-full-live-acceptance@1"),
        ("fixture_only", True),
        ("dirty", True),
        ("mode", "inspect"),
        ("authorizing_for_publication", True),
    ):
        tampered = deepcopy(report)
        tampered[field] = value
        tampered["report_digest_sha256"] = acceptance._report_digest(tampered)
        with pytest.raises(acceptance.AcceptanceError, match="non-authorizing @2"):
            acceptance.check_full_live_acceptance_report(
                tampered, repository_root=root
            )


def test_live_alternates_never_replace_canonical_receipts(tmp_path: Path) -> None:
    root = _live_workspace(tmp_path)
    report = _build(root)
    for name in (
        "federal_candidate.live.json",
        "federal_evaluation.live.json",
        "federal_adjacency_reconciliation.live.json",
    ):
        _write_json(
            root,
            Path("docs/reports/legal_corpora_reindex") / name,
            {"fixture_only": True, "status": "failed"},
        )
    assert _build(root) == report


def test_fixture_canonical_candidate_cannot_pass(tmp_path: Path) -> None:
    root = _live_workspace(tmp_path)
    candidate_path = root / acceptance.CANDIDATE_RELPATH
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    candidate["fixture_only"] = True
    _write_json(root, acceptance.CANDIDATE_RELPATH, candidate)
    with pytest.raises(acceptance.AcceptanceError, match="fixture-only"):
        _build(root)


def test_missing_any_canonical_input_fails_closed(tmp_path: Path) -> None:
    root = _live_workspace(tmp_path)
    (root / acceptance.LIVE_GOLD_RELPATH).unlink()
    with pytest.raises(acceptance.AcceptanceError, match="missing or unsafe"):
        _build(root)


def test_blocked_cli_does_not_overwrite_acceptance_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _live_workspace(tmp_path)
    candidate = json.loads(
        (root / acceptance.CANDIDATE_RELPATH).read_text(encoding="utf-8")
    )
    candidate["fixture_only"] = True
    _write_json(root, acceptance.CANDIDATE_RELPATH, candidate)
    evidence = root / acceptance.ACCEPTANCE_RELPATH
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text("sentinel\n", encoding="utf-8")
    monkeypatch.setattr(acceptance, "REPOSITORY_ROOT", root)
    assert acceptance.main(
        ["--full", "--require-live-official", "--require-production-candidate", "--check"]
    ) == 1
    assert evidence.read_text(encoding="utf-8") == "sentinel\n"


def test_successful_cli_writes_checked_at2_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _live_workspace(tmp_path)
    monkeypatch.setattr(acceptance, "REPOSITORY_ROOT", root)
    assert acceptance.main(
        ["--full", "--require-live-official", "--require-production-candidate", "--check"]
    ) == 0
    payload = json.loads(
        (root / acceptance.ACCEPTANCE_RELPATH).read_text(encoding="utf-8")
    )
    assert acceptance.check_full_live_acceptance_report(
        payload, repository_root=root
    )["ok"] is True
