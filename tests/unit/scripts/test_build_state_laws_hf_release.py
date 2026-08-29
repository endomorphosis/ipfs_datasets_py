"""Unit tests for the exact-51 state-law release candidate assembler (LCR-039)."""

from __future__ import annotations

import copy
import io
import json
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import scripts.ops.legal_data.build_state_laws_hf_release as cli
from ipfs_datasets_py.processors.legal_data.state_laws_completeness import (
    CANONICAL_JURISDICTION_ORDER,
    EXPECTED_JURISDICTION_COUNT,
)
from ipfs_datasets_py.processors.legal_data.state_laws_hf_release import (
    DEFAULT_DATASET_REPO_ID,
    PREVIOUS_PUBLIC_PIN,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    DEFAULT_EMBEDDING_MODEL_ID,
    DEFAULT_EMBEDDING_MODEL_REVISION,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
REPORT_PATH = REPO_ROOT / "docs" / "reports" / "legal_corpora_reindex" / "release_candidate.json"
E2E_PATH = REPO_ROOT / "docs" / "reports" / "legal_corpora_reindex" / "local_e2e.json"


def test_cli_identity_and_help() -> None:
    assert cli.TASK_ID == "LCR-039"
    assert cli.GOAL_ID == "LCR-G070"
    parser = cli.build_parser()
    assert parser.prog == "build_state_laws_hf_release.py"
    assert cli.main(["--help"]) == 0


def test_hub_upload_forbidden() -> None:
    assert cli.main(["--hub-upload"]) == 1
    assert cli.main(["--no-fixture-only"]) == 1


def test_check_and_write_modes_are_mutually_exclusive() -> None:
    assert cli.main(["--check", "--write"]) == 2


def test_exact_51_family_rows_cover_canonical_set() -> None:
    rows = cli.exact_51_family_rows()
    codes = [str(row["jurisdiction"]).upper() for row in rows["corpus"]]
    assert codes == list(CANONICAL_JURISDICTION_ORDER)
    assert len(codes) == EXPECTED_JURISDICTION_COUNT
    assert codes[-1] == "DC"
    assert "PR" not in codes
    assert len(rows["bm25_documents"]) == EXPECTED_JURISDICTION_COUNT
    assert len(rows["vectors"]) == EXPECTED_JURISDICTION_COUNT
    assert len(rows["graph_nodes"]) == EXPECTED_JURISDICTION_COUNT
    assert len(rows["source_receipts"]) == EXPECTED_JURISDICTION_COUNT


def test_assemble_candidate_does_not_authorize_publication() -> None:
    payload = cli.assemble_candidate(repo_root=REPO_ROOT)
    cli.check_candidate_report(payload)
    assert payload["authorizing_for_publication"] is False
    assert payload["hub_upload"] is False
    assert payload["dataset_repo_id"] == DEFAULT_DATASET_REPO_ID
    assert payload["model_id"] == DEFAULT_EMBEDDING_MODEL_ID
    assert payload["model_revision"] == DEFAULT_EMBEDDING_MODEL_REVISION
    assert payload["previous_public_pin"] == PREVIOUS_PUBLIC_PIN
    assert payload["rollback_target"] == PREVIOUS_PUBLIC_PIN
    assert payload["jurisdiction_count"] == EXPECTED_JURISDICTION_COUNT
    assert payload["validation"]["valid"] is True
    assert payload["multipart_plan"]["transactional_staging_ready"] is True


def test_committed_report_exists_and_matches_gate() -> None:
    assert E2E_PATH.is_file()
    assert REPORT_PATH.is_file()
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    cli.check_candidate_report(payload)
    assert payload["task_id"] == "LCR-039"
    assert payload["jurisdiction_count"] == EXPECTED_JURISDICTION_COUNT


def test_cli_check_validates_frozen_report() -> None:
    assert cli.main(["--check"]) == 0


def test_literal_cli_check_uses_repository_scripts_namespace() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/ops/legal_data/build_state_laws_hf_release.py",
            "--check",
        ],
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    assert "state_laws_release_candidate: PASS" in completed.stdout


def _git(tmp_path: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(tmp_path), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_acceptance_then_candidate_write_allows_only_controlled_evidence_outputs(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "LCR Test")
    _git(tmp_path, "config", "user.email", "lcr@example.invalid")
    source = tmp_path / "source.py"
    baseline = tmp_path / "docs" / "baseline.json"
    acceptance = tmp_path / "docs" / "acceptance.json"
    candidate = tmp_path / "docs" / "candidate.json"
    baseline.parent.mkdir(parents=True)
    source.write_text("SOURCE = 1\n", encoding="utf-8")
    for path in (baseline, acceptance, candidate):
        path.write_text("{}\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "clean production source")
    revision = _git(tmp_path, "rev-parse", "HEAD")

    # A freshly reobserved LCR-081 receipt is a controlled evidence output,
    # not executable source drift. Acceptance is then written from one clean
    # premeasurement, and candidate sealing permits exactly those two paths.
    cli.write_json_report({"fresh": True}, baseline)
    cli.require_only_expected_dirty_paths(
        repo_root=tmp_path,
        source_revision=revision,
        allowed_paths=(baseline,),
    )
    cli.write_json_report({"accepted": True}, acceptance)
    cli.require_only_expected_dirty_paths(
        repo_root=tmp_path,
        source_revision=revision,
        allowed_paths=(baseline, acceptance),
    )
    cli.write_json_report({"candidate": True}, candidate)

    source.write_text("SOURCE = 2\n", encoding="utf-8")
    with pytest.raises(cli.CandidateError, match="source drift"):
        cli.require_only_expected_dirty_paths(
            repo_root=tmp_path,
            source_revision=revision,
            allowed_paths=(baseline, acceptance, candidate),
        )


def test_source_control_false_does_not_claim_clean_and_rename_keeps_both_paths(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "LCR Test")
    _git(tmp_path, "config", "user.email", "lcr@example.invalid")
    source = tmp_path / "source.py"
    allowed = tmp_path / "docs" / "acceptance.json"
    allowed.parent.mkdir(parents=True)
    source.write_text("SOURCE = 1\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "clean source")
    revision = _git(tmp_path, "rev-parse", "HEAD")

    binding = cli.source_control_binding(
        repo_root=tmp_path,
        source_revision=revision,
        require_clean=False,
    )
    assert binding["clean_at_seal"] is False

    _git(tmp_path, "mv", "source.py", "docs/acceptance.json")
    with pytest.raises(cli.CandidateError, match="source drift|rename/copy"):
        cli.require_only_expected_dirty_paths(
            repo_root=tmp_path,
            source_revision=revision,
            allowed_paths=(allowed,),
        )


def test_source_control_rejects_rename_between_allowed_reports(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "LCR Test")
    _git(tmp_path, "config", "user.email", "lcr@example.invalid")
    acceptance = tmp_path / "docs" / "acceptance.json"
    candidate = tmp_path / "docs" / "candidate.json"
    acceptance.parent.mkdir(parents=True)
    acceptance.write_text("{}\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "clean source")
    revision = _git(tmp_path, "rev-parse", "HEAD")

    _git(tmp_path, "mv", "docs/acceptance.json", "docs/candidate.json")
    with pytest.raises(cli.CandidateError, match="rename/copy"):
        cli.require_only_expected_dirty_paths(
            repo_root=tmp_path,
            source_revision=revision,
            allowed_paths=(acceptance, candidate),
        )


def test_source_control_rejects_dirty_report_executable_mode(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "LCR Test")
    _git(tmp_path, "config", "user.email", "lcr@example.invalid")
    report = tmp_path / "docs" / "acceptance.json"
    report.parent.mkdir(parents=True)
    report.write_text("{}\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "clean source")
    revision = _git(tmp_path, "rev-parse", "HEAD")

    report.chmod(0o755)
    with pytest.raises(cli.CandidateError, match="non-executable regular file"):
        cli.require_only_expected_dirty_paths(
            repo_root=tmp_path,
            source_revision=revision,
            allowed_paths=(report,),
        )


@pytest.mark.parametrize("require_clean_source", [False, True])
def test_collect_production_evidence_honors_clean_source_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    require_clean_source: bool,
) -> None:
    baseline = tmp_path / cli.DEFAULT_LIVE_BASELINE_RELPATH
    baseline.parent.mkdir(parents=True)
    baseline.write_text("{}\n", encoding="utf-8")
    observed: dict[str, bool] = {}

    class _ObservedSourceBinding(RuntimeError):
        pass

    def _observe_source_binding(**kwargs):
        observed["require_clean"] = kwargs["require_clean"]
        raise _ObservedSourceBinding

    monkeypatch.setattr(cli, "source_control_binding", _observe_source_binding)
    with pytest.raises(_ObservedSourceBinding):
        cli.collect_production_evidence(
            input_map_path=tmp_path / "input-map.json",
            rights_receipt_path=tmp_path / "rights.json",
            production_output_root=tmp_path / "release",
            live_baseline_path=baseline,
            source_revision="a" * 40,
            repo_root=tmp_path,
            require_clean_source=require_clean_source,
        )

    assert observed == {"require_clean": require_clean_source}


def test_report_only_remeasurement_requires_exact_prior_clean_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "LCR Test")
    _git(tmp_path, "config", "user.email", "lcr@example.invalid")
    baseline = tmp_path / cli.DEFAULT_LIVE_BASELINE_RELPATH
    acceptance = tmp_path / cli.PRODUCTION_ACCEPTANCE_RELPATH
    candidate = tmp_path / cli.DEFAULT_REPORT_RELPATH
    for path in (baseline, acceptance, candidate):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "clean source seal")
    revision = _git(tmp_path, "rev-parse", "HEAD")
    tree = _git(tmp_path, "rev-parse", f"{revision}^{{tree}}")
    sealed = {
        "clean_at_seal": True,
        "excluded_evidence_paths": [
            cli.DEFAULT_LIVE_BASELINE_RELPATH.as_posix(),
            cli.PRODUCTION_ACCEPTANCE_RELPATH.as_posix(),
            cli.DEFAULT_REPORT_RELPATH.as_posix(),
        ],
        "revision": revision,
        "tree": tree,
    }
    acceptance.write_text('{"sealed":true}\n', encoding="utf-8")

    class _ReachedEvidenceVerification(RuntimeError):
        pass

    monkeypatch.setattr(
        cli,
        "_validated_live_baseline",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            _ReachedEvidenceVerification()
        ),
    )
    common = {
        "input_map_path": tmp_path / "input-map.json",
        "rights_receipt_path": tmp_path / "rights.json",
        "production_output_root": tmp_path / "release",
        "live_baseline_path": baseline,
        "source_revision": revision,
        "repo_root": tmp_path,
    }
    with pytest.raises(_ReachedEvidenceVerification):
        cli.collect_production_evidence(
            **common,
            require_clean_source=False,
            sealed_source_control=sealed,
        )
    with pytest.raises(cli.CandidateError, match="exact prior clean source binding"):
        cli.collect_production_evidence(
            **common,
            require_clean_source=False,
            sealed_source_control=None,
        )
    forged = dict(sealed)
    forged["tree"] = "0" * 40
    with pytest.raises(cli.CandidateError, match="exact prior clean source binding"):
        cli.collect_production_evidence(
            **common,
            require_clean_source=False,
            sealed_source_control=forged,
        )
    with pytest.raises(cli.CandidateError, match="source drift"):
        cli.collect_production_evidence(
            **common,
            require_clean_source=True,
        )


def test_source_control_rejects_untracked_extra(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "LCR Test")
    _git(tmp_path, "config", "user.email", "lcr@example.invalid")
    tracked = tmp_path / "tracked.py"
    tracked.write_text("SOURCE = 1\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "clean source")
    revision = _git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "untracked.py").write_text("UNTRUSTED = 1\n", encoding="utf-8")
    with pytest.raises(cli.CandidateError, match="source drift"):
        cli.require_only_expected_dirty_paths(
            repo_root=tmp_path,
            source_revision=revision,
            allowed_paths=(),
        )


def test_source_control_rejects_unmerged_state(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "LCR Test")
    _git(tmp_path, "config", "user.email", "lcr@example.invalid")
    source = tmp_path / "source.py"
    source.write_text("SOURCE = 1\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "base")
    base_branch = _git(tmp_path, "branch", "--show-current")
    _git(tmp_path, "checkout", "-b", "other")
    source.write_text("SOURCE = 2\n", encoding="utf-8")
    _git(tmp_path, "commit", "-am", "other change")
    _git(tmp_path, "checkout", base_branch)
    source.write_text("SOURCE = 3\n", encoding="utf-8")
    _git(tmp_path, "commit", "-am", "main change")
    revision = _git(tmp_path, "rev-parse", "HEAD")
    merge = subprocess.run(
        ["git", "-C", str(tmp_path), "merge", "other"],
        capture_output=True,
        check=False,
        text=True,
    )
    assert merge.returncode != 0
    with pytest.raises(cli.CandidateError, match="unmerged"):
        cli.require_only_expected_dirty_paths(
            repo_root=tmp_path,
            source_revision=revision,
            allowed_paths=(source,),
        )


def test_source_revision_accepts_clean_report_only_descendant(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "LCR Test")
    _git(tmp_path, "config", "user.email", "lcr@example.invalid")
    source = tmp_path / "source.py"
    report = tmp_path / cli.PRODUCTION_ACCEPTANCE_RELPATH
    report.parent.mkdir(parents=True)
    source.write_text("SOURCE = 1\n", encoding="utf-8")
    report.write_text("{}\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "source revision")
    revision = _git(tmp_path, "rev-parse", "HEAD")
    report.write_text('{"sealed":true}\n', encoding="utf-8")
    _git(tmp_path, "commit", "-am", "seal report")

    cli.require_only_expected_dirty_paths(
        repo_root=tmp_path,
        source_revision=revision,
        allowed_paths=(report,),
    )


@pytest.mark.parametrize("mutation", ["source", "report_mode"])
def test_source_revision_rejects_unsafe_descendant(
    tmp_path: Path, mutation: str
) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "LCR Test")
    _git(tmp_path, "config", "user.email", "lcr@example.invalid")
    source = tmp_path / "source.py"
    report = tmp_path / cli.PRODUCTION_ACCEPTANCE_RELPATH
    report.parent.mkdir(parents=True)
    source.write_text("SOURCE = 1\n", encoding="utf-8")
    report.write_text("{}\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "source revision")
    revision = _git(tmp_path, "rev-parse", "HEAD")
    if mutation == "source":
        source.write_text("SOURCE = 2\n", encoding="utf-8")
    else:
        report.chmod(0o755)
    _git(tmp_path, "commit", "-am", "unsafe descendant")

    with pytest.raises(cli.CandidateError, match="non-report drift|changed mode"):
        cli.require_only_expected_dirty_paths(
            repo_root=tmp_path,
            source_revision=revision,
            allowed_paths=(report,),
        )


def test_nofollow_open_rejects_parent_directory_replacement(
    tmp_path: Path,
) -> None:
    live = tmp_path / "live"
    other = tmp_path / "other"
    live.mkdir()
    other.mkdir()
    (live / "evidence.json").write_text("A", encoding="utf-8")
    (other / "evidence.json").write_text("B", encoding="utf-8")

    with (
        pytest.raises(cli.CandidateError, match="path was replaced"),
        cli._open_regular_file_nofollow(
            live / "evidence.json", label="race probe"
        ) as handle,
    ):
        assert handle.read() == b"A"
        live.rename(tmp_path / "old")
        other.rename(live)


def test_production_local_is_explicit_and_never_a_hub_mode() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(["--production-local", "--no-fixture-only"])
    assert args.production_local is True
    assert args.fixture_only is False
    assert cli.main(["--production-local", "--no-fixture-only", "--hub-upload"]) == 1


def _corpus_closure_surfaces() -> tuple[
    dict[str, dict[str, object]],
    dict[str, dict[str, object]],
    dict[str, object],
]:
    selected: dict[str, dict[str, object]] = {}
    produced: dict[str, dict[str, object]] = {}
    keys: list[str] = []
    for code in CANONICAL_JURISDICTION_ORDER:
        key = f"sha256:{cli.digest_payload({'jurisdiction': code})}"
        row = {
            "acquisition_receipt_id": f"receipt-{code}",
            "entry_cid": key,
            "jurisdiction": code,
        }
        receipt = {"jurisdiction": code, "receipt_id": f"receipt-{code}"}
        shard = {
            "first_key": key,
            "last_key": key,
            "relative_path": f"data/corpus/jurisdiction/{code}/part.parquet",
            "row_count": 1,
            "sha256": "a" * 64,
        }
        selected[code] = {
            "adapter_dispositions": {
                "admitted": 1,
                "quarantined": 0,
                "rejected": 0,
            },
            "entry_cids": [key],
            "rows": [row],
            "source_receipt": receipt,
        }
        produced[code] = {
            "corpus_shards": [shard],
            "entry_cids": [key],
            "rows": [dict(row)],
            "source_receipt": dict(receipt),
            "source_receipt_digest_sha256": cli.digest_payload(receipt),
            "source_receipt_path": f"receipts/{code}.json",
            "source_receipt_sha256": "b" * 64,
        }
        keys.append(key)
    manifest: dict[str, object] = {
        "counts": {"corpus_documents": 51},
        "key_parity": {
            "parent_entry_cid_count": 51,
            "parent_entry_cids_sha256": cli.digest_payload(
                {"parent_entry_cids": sorted(keys)}
            ),
        },
    }
    return selected, produced, manifest


@pytest.mark.parametrize("mutation", ["swapped", "mislabeled", "redistributed"])
def test_exact_corpus_closure_rejects_same_total_state_drift(mutation: str) -> None:
    selected, produced, manifest = _corpus_closure_surfaces()
    first, second = CANONICAL_JURISDICTION_ORDER[:2]
    if mutation == "swapped":
        produced[first]["rows"], produced[second]["rows"] = (
            produced[second]["rows"], produced[first]["rows"]
        )
        produced[first]["entry_cids"], produced[second]["entry_cids"] = (
            produced[second]["entry_cids"], produced[first]["entry_cids"]
        )
    elif mutation == "mislabeled":
        produced[first]["rows"][0]["jurisdiction"] = second  # type: ignore[index]
    else:
        produced[first]["rows"] = [
            *produced[first]["rows"],  # type: ignore[misc]
            *produced[second]["rows"],  # type: ignore[misc]
        ]
        produced[first]["entry_cids"] = [
            *produced[first]["entry_cids"],  # type: ignore[misc]
            *produced[second]["entry_cids"],  # type: ignore[misc]
        ]
        produced[second]["rows"] = []
        produced[second]["entry_cids"] = []
    with pytest.raises(cli.CandidateError, match="release corpus differs"):
        cli._bind_exact_corpus_closure(selected, produced, manifest=manifest)


def test_exact_corpus_closure_rejects_output_input_source_receipt_digest() -> None:
    selected, produced, manifest = _corpus_closure_surfaces()
    first = CANONICAL_JURISDICTION_ORDER[0]
    produced[first]["source_receipt_digest_sha256"] = "0" * 64
    with pytest.raises(cli.CandidateError, match="source-receipt digest mismatched"):
        cli._bind_exact_corpus_closure(selected, produced, manifest=manifest)


@pytest.mark.parametrize(
    "filename",
    [
        "input-map.json",
        "rights-receipt.json",
        "live-baseline.json",
        "run-seal.json",
        "release-manifest.json",
        "embedded-source-receipt.json",
        "acceptance.json",
        "candidate.json",
        "STATE-AL.jsonld",
    ],
)
def test_every_production_json_surface_rejects_duplicate_keys(
    tmp_path: Path, filename: str
) -> None:
    path = tmp_path / filename
    path.write_text('{"outer":{"identity":1,"identity":2}}', encoding="utf-8")
    with pytest.raises(cli.CandidateError, match="duplicate key"):
        cli.load_json_value(path, label=filename)


def test_bound_json_snapshot_hashes_and_parses_one_captured_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "bound.json"
    path.write_text('{"identity":"path-bytes"}', encoding="utf-8")
    captured = b'{"identity":"captured"}'
    swapped = b'{"identity":"swapped","identity":"last-wins"}'
    calls = 0

    def alternating_read(_path: Path, *, label: str) -> bytes:
        nonlocal calls
        del label
        calls += 1
        return captured if calls == 1 else swapped

    monkeypatch.setattr(cli, "read_regular_file_bytes", alternating_read)
    payload, serialized, digest = cli.load_bound_json_mapping_snapshot(
        path,
        expected_sha256=cli.hashlib.sha256(captured).hexdigest(),
        label="race-bound JSON",
    )
    assert calls == 1
    assert serialized == captured
    assert payload == {"identity": "captured"}
    assert digest == cli.hashlib.sha256(captured).hexdigest()


def test_json_lines_duplicate_scan_uses_the_adapter_snapshot() -> None:
    with pytest.raises(cli.CandidateError, match="duplicate key"):
        cli.load_json_lines_mappings_bytes(
            b'{"entry":1}\n{"nested":{"key":1,"key":2}}\n',
            label="canonical JSON-LD",
        )


def test_adapter_rows_come_from_one_digest_bound_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "STATE-AK.jsonld"
    path.write_text('{"entry":"path"}\n', encoding="utf-8")
    captured = b'{"entry":"captured-1"}\n{"entry":"captured-2"}\n'
    swapped = b'{"entry":"swapped","entry":"last-wins"}\n'
    digest = cli.hashlib.sha256(captured).hexdigest()
    binding = SimpleNamespace(
        canonical_jsonld_path=path,
        canonical_jsonld_sha256=digest,
    )
    adapter = SimpleNamespace(
        input_path=path,
        source_receipt=SimpleNamespace(input_sha256=digest),
    )
    calls = 0

    def alternating_read(_path: Path, *, label: str) -> bytes:
        nonlocal calls
        del label
        calls += 1
        return captured if calls == 1 else swapped

    monkeypatch.setattr(cli, "read_regular_file_bytes", alternating_read)
    rows = list(
        cli._strict_adapter_snapshot_rows(
            adapter=adapter, binding=binding, code="AK"
        )
    )
    assert calls == 1
    assert rows == [{"entry": "captured-1"}, {"entry": "captured-2"}]


def test_addressed_ledger_parses_verified_bytes_without_reopening(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "ledger.json"
    path.write_text('{"source":"swapped"}', encoding="utf-8")
    captured = b'{"source":"captured"}'
    digest = cli.hashlib.sha256(captured).hexdigest()
    monkeypatch.setattr(
        cli,
        "_address_matches_file",
        lambda *_args, **_kwargs: (captured, digest),
    )
    monkeypatch.setattr(
        cli,
        "load_json_mapping",
        lambda *_args, **_kwargs: pytest.fail("addressed ledger was reopened"),
    )
    payload, observed = cli._load_addressed_json_mapping(
        path,
        {"byte_size": len(captured), "sha256": digest},
        label="request ledger",
    )
    assert payload == {"source": "captured"}
    assert observed == digest


def test_closure_input_parses_its_digest_named_snapshot_without_reopening(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    closure_dir = tmp_path / "frontiers" / "closure-inputs"
    closure_dir.mkdir(parents=True)
    frontier = {"complete": True, "frontier_digest_sha256": "f" * 64}
    closure = {
        "canonical_output_binding": {"canonical_row_count": 1},
        "completion_receipt": {
            "disposition": {"admitted": 1},
            "frontier": frontier,
            "index_keys": ["one"],
            "jurisdiction": "AK",
        },
        "replayed_frontier": frontier,
    }
    serialized = cli.canonical_json_bytes(closure)
    digest = cli.hashlib.sha256(serialized).hexdigest()
    path = closure_dir / f"{digest}.json"
    path.write_bytes(serialized)
    monkeypatch.setattr(
        cli,
        "load_json_mapping",
        lambda *_args, **_kwargs: pytest.fail("closure input was reopened"),
    )
    selected_path, selected = cli._closure_input_for_raw_receipt(
        jurisdiction_root=tmp_path,
        raw_receipt={
            "canonical_row_count": 1,
            "disposition": {"admitted": 1},
            "frontier": frontier,
            "index_keys": ["one"],
        },
        code="AK",
    )
    assert selected_path == path
    assert selected == closure


def test_closure_input_binds_exact_live_or_replay_catalog_evidence(
    tmp_path: Path,
) -> None:
    closure_dir = tmp_path / "frontiers" / "closure-inputs"
    closure_dir.mkdir(parents=True)
    frontier = {"complete": True, "frontier_digest_sha256": "f" * 64}

    def catalog_evidence(*, retained_replay: bool, receipt: str) -> dict[str, object]:
        observation = {
            "body_sha256": "b" * 64,
            "observation_digest": "d" * 64,
            "retained_parser_inputs": [{"receipt_sha256": receipt}],
            "retained_replay": retained_replay,
        }
        return {
            "catalog_key_count": 1,
            "first_observation": observation,
            "replay_observation": observation,
        }

    closure_paths: dict[str, Path] = {}
    catalogs = {
        "live": catalog_evidence(retained_replay=False, receipt="a" * 64),
        "replay": catalog_evidence(retained_replay=True, receipt="c" * 64),
    }
    for name, catalog in catalogs.items():
        closure = {
            "canonical_output_binding": {"canonical_row_count": 1},
            "completion_receipt": {
                "disposition": {"admitted": 1},
                "frontier": frontier,
                "index_keys": ["one"],
                "jurisdiction": "IA",
                "source_catalog_evidence": catalog,
            },
            "replayed_frontier": frontier,
        }
        serialized = cli.canonical_json_bytes(closure)
        digest = cli.hashlib.sha256(serialized).hexdigest()
        closure_paths[name] = closure_dir / f"{digest}.json"
        closure_paths[name].write_bytes(serialized)

    selected_path, selected = cli._closure_input_for_raw_receipt(
        jurisdiction_root=tmp_path,
        raw_receipt={
            "canonical_row_count": 1,
            "disposition": {"admitted": 1},
            "frontier": frontier,
            "index_keys": ["one"],
            "source_catalog_evidence": catalogs["replay"],
        },
        code="IA",
    )

    assert selected_path == closure_paths["replay"]
    assert selected["completion_receipt"]["source_catalog_evidence"] == catalogs[
        "replay"
    ]


def test_verifier_phase_bound_seed_uses_one_live_selector_and_rejects_competing_plan(
    tmp_path: Path,
) -> None:
    closure_dir = tmp_path / "frontiers" / "closure-inputs"
    closure_dir.mkdir(parents=True)
    first_receipt = "a" * 64
    replay_receipt = "b" * 64
    closure = {
        "completion_receipt": {
            "jurisdiction": "IA",
            "source_catalog_evidence": {
                "first_observation": {
                    "retained_parser_inputs": [
                        {"receipt_sha256": first_receipt}
                    ],
                    "retained_replay": False,
                },
                "replay_observation": {
                    "retained_parser_inputs": [
                        {"receipt_sha256": replay_receipt}
                    ],
                    "retained_replay": False,
                },
            },
        }
    }
    serialized = cli.canonical_json_bytes(closure)
    selector = closure_dir / f"{cli.hashlib.sha256(serialized).hexdigest()}.json"
    selector.write_bytes(serialized)

    class PhaseScraper:
        def attach_state_law_acquisition_ledger(self, ledger: object) -> None:
            self.ledger = ledger

        def _bound_shared_official_frontier_replay_plan(
            self, *, phase: str
        ) -> list[dict[str, str]]:
            return [
                {
                    "receipt_sha256": (
                        first_receipt if phase == "first" else replay_receipt
                    )
                }
            ]

    ledger = SimpleNamespace(
        closure_inputs_dir=closure_dir,
        resolve_frontier_closure_projection_path=lambda path: path,
        _load_frontier_closure_projection=lambda path: json.loads(
            path.read_text(encoding="utf-8")
        ),
    )
    receipt_ids, selected = cli._verifier_phase_bound_seed_selection(
        scraper=PhaseScraper(),
        ledger=ledger,
        code="IA",
    )

    assert receipt_ids == (first_receipt, replay_receipt)
    assert selected == selector
    destination_root = tmp_path / "destination"
    (destination_root / "IA").mkdir(parents=True)
    linked = cli._hardlink_verifier_phase_selector(
        source=selector,
        destination_root=destination_root,
        code="IA",
    )
    assert linked.read_bytes() == serialized
    assert linked.stat().st_ino == selector.stat().st_ino

    class CompetingPlanScraper(PhaseScraper):
        def _bound_shared_official_frontier_replay_plan(
            self, *, phase: str
        ) -> list[dict[str, str]]:
            del phase
            raise RuntimeError(
                "shared official frontier has multiple distinct live replay plans"
            )

    with pytest.raises(cli.CandidateError, match="multiple distinct live replay plans"):
        cli._verifier_phase_bound_seed_selection(
            scraper=CompetingPlanScraper(),
            ledger=ledger,
            code="IA",
        )


def test_release_artifact_snapshot_rejects_path_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release_root = tmp_path / "release"
    artifact = release_root / "data" / "artifact.bin"
    artifact.parent.mkdir(parents=True)
    original_bytes = b"descriptor-bound"
    artifact.write_bytes(original_bytes)
    manifest = {
        "artifacts": [
            {
                "family": "graph",
                "relative_path": "data/artifact.bin",
                "row_count": 1,
                "sha256": cli.hashlib.sha256(original_bytes).hexdigest(),
                "size_bytes": len(original_bytes),
            }
        ]
    }
    original_hash = cli._open_handle_sha256

    def swap_after_hash(handle: object) -> str:
        digest = original_hash(handle)  # type: ignore[arg-type]
        replacement = release_root / "replacement.bin"
        replacement.write_bytes(b"swapped-artifact")
        replacement.replace(artifact)
        return digest

    monkeypatch.setattr(cli, "_open_handle_sha256", swap_after_hash)
    with pytest.raises(cli.CandidateError, match="changed while|pathname was replaced"):
        cli._snapshot_release_artifacts(
            SimpleNamespace(output_root=release_root), manifest
        )


def _remote_baseline_projection(*, al_rows: int = 1) -> dict[str, object]:
    partitions = {
        code: {
            "content_sha256": f"{position + 1:064x}",
            "num_rows": al_rows if code == "AL" else 1,
        }
        for position, code in enumerate(CANONICAL_JURISDICTION_ORDER)
    }
    return {
        "authenticated_identity": {
            "authenticated": True,
            "name": "principal",
            "token_present": True,
            "token_source": "ignored-local-source",
            "type": "user",
            "whoami_response_sha256": "a" * 64,
        },
        "federal_register": {"revision": "b" * 40, "parquet": {"num_rows": 1}},
        "pins": {"federal_register": "b" * 40, "state_laws": "c" * 40},
        "requests": [
            {
                "byte_length": 1,
                "endpoint": "https://huggingface.co/api/whoami-v2",
                "response_sha256": "a" * 64,
            }
        ],
        "state_laws": {
            "partitions": partitions,
            "revision": "c" * 40,
        },
    }


def _attach_baseline_identity_observations(
    receipt: dict[str, object],
) -> None:
    state = receipt["state_laws"]
    assert isinstance(state, dict)
    partitions = state["partitions"]
    assert isinstance(partitions, dict)
    for code, partition in partitions.items():
        assert isinstance(code, str) and isinstance(partition, dict)
        row_count = int(partition["num_rows"])
        identities = [f"urn:test:{code}:one"] * row_count
        partition["partition_body_observation"] = {
            "jurisdiction": code,
            "noncomparable_recovery_manifest_count": 0,
            "noncomparable_recovery_manifest_multiset_sha256": cli.digest_payload([]),
            "noncomparable_recovery_manifest_row_digests": [],
            "observed_row_count": row_count,
            "schema_version": cli.BASELINE_SOURCE_IDENTITY_CLOSURE_SCHEMA,
            "source_identities": identities,
            "source_identity_count": row_count,
            "source_identity_multiset_sha256": cli.digest_payload(identities),
        }


def test_live_baseline_replay_is_mandatory_stable_and_byte_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = _remote_baseline_projection()
    stored_state = stored["state_laws"]
    assert isinstance(stored_state, dict)
    stored_state["partitions"] = dict(
        sorted(stored_state["partitions"].items())  # type: ignore[union-attr]
    )
    calls = {"observe": 0, "validate": 0}

    def observe(**kwargs: object) -> dict[str, object]:
        calls["observe"] += 1
        assert callable(kwargs.get("state_partition_body_observer_factory"))
        replay = copy.deepcopy(stored)
        _attach_baseline_identity_observations(replay)
        replay["observed_at"] = f"2026-08-28T02:00:0{calls['observe']}Z"
        replay[cli.live_baseline_audit.RECEIPT_SELF_DIGEST_FIELD] = (
            f"{calls['observe']:064x}"
        )
        return replay

    def validate(*_args: object, **_kwargs: object) -> dict[str, bool]:
        calls["validate"] += 1
        return {"ok": True}

    monkeypatch.setattr(cli.live_baseline_audit, "observe_with_live_hub", observe)
    monkeypatch.setattr(cli.live_baseline_audit, "validate_receipt", validate)
    first = cli._verifier_owned_live_baseline_replay(stored)
    second = cli._verifier_owned_live_baseline_replay(stored)
    assert calls == {"observe": 2, "validate": 2}
    assert first == second
    assert first[0]["verifier_owned_live_reobservation"] is True

    forged = _remote_baseline_projection(al_rows=2)
    with pytest.raises(cli.CandidateError, match="differs.*live Hub bytes/counts"):
        cli._verifier_owned_live_baseline_replay(forged)


def test_offline_self_consistent_baseline_cannot_skip_live_primitive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"observe": 0}

    def unavailable(**_kwargs: object) -> dict[str, object]:
        calls["observe"] += 1
        raise cli.live_baseline_audit.LiveBaselineAuditError("network blocked")

    monkeypatch.setattr(
        cli.live_baseline_audit, "observe_with_live_hub", unavailable
    )
    with pytest.raises(cli.CandidateError, match="live Hub replay failed"):
        cli._verifier_owned_live_baseline_replay(_remote_baseline_projection())
    assert calls["observe"] == 1


def _reconcile_source_identities(
    baseline: dict[str, int],
    acquired: dict[str, int],
    *,
    placeholders: int = 0,
) -> dict[str, object]:
    return cli._reconcile_baseline_source_identities(
        jurisdiction="AL",
        baseline_counter=baseline,
        acquired_counter=acquired,
        baseline_row_count=sum(baseline.values()) + placeholders,
        acquired_row_count=sum(acquired.values()),
        noncomparable_recovery_manifest_count=placeholders,
        noncomparable_recovery_manifest_multiset_sha256=cli.digest_payload(
            ["a" * 64] * placeholders
        ),
        duplicate_count=0,
        excluded_count=0,
        quarantined_count=0,
    )


@pytest.mark.parametrize(
    ("baseline", "acquired"),
    [
        ({"urn:a": 1, "urn:b": 1}, {"urn:a": 1, "urn:c": 1}),
        ({"urn:a": 1, "urn:b": 1}, {"urn:a": 1, "urn:c": 1, "urn:d": 1}),
        ({"urn:a": 2}, {"urn:a": 1, "urn:b": 1}),
    ],
)
def test_baseline_source_identity_removal_fails_even_when_counts_are_padded(
    baseline: dict[str, int], acquired: dict[str, int]
) -> None:
    with pytest.raises(cli.CandidateError, match="removes.*source-identity"):
        _reconcile_source_identities(baseline, acquired)


def test_source_identity_multiset_digest_is_order_independent_and_growth_is_typed() -> None:
    first = {"urn:b": 1, "urn:a": 2}
    second = {"urn:a": 2, "urn:b": 1}
    assert cli._source_identity_multiset_digest(first) == (
        cli._source_identity_multiset_digest(second)
    )
    exact = _reconcile_source_identities({"urn:a": 1}, {"urn:a": 1})
    assert exact["disposition"] == "exact_match"
    growth = _reconcile_source_identities(
        {"urn:a": 1}, {"urn:a": 1, "urn:b": 1}
    )
    assert growth["disposition"] == "current_official_growth"
    assert growth["added_source_identity_count"] == 1


def test_authenticated_recovery_manifest_is_the_only_typed_raw_underfill() -> None:
    comparison = _reconcile_source_identities(
        {"urn:a": 1}, {"urn:a": 1}, placeholders=1
    )
    assert comparison["delta_from_baseline"] == -1
    assert comparison["explained_delta_count"] == 1
    assert comparison["baseline_noncomparable_recovery_manifest_disposition"] == (
        "authenticated_baseline_recovery_manifest"
    )


def _baseline_parquet_bytes(rows: list[dict[str, object]]) -> bytes:
    buffer = io.BytesIO()
    pq.write_table(pa.Table.from_pylist(rows), buffer)
    return buffer.getvalue()


def test_live_baseline_partition_observer_runs_only_after_lfs_verification() -> None:
    audit = cli.live_baseline_audit
    body = _baseline_parquet_bytes([{"n": 1}, {"n": 2}])
    path = audit.state_partition_path("AL")
    url = audit.dataset_resolve_url(
        audit.STATE_REPO_ID,
        audit.STATE_PINNED_REVISION,
        path,
    )
    responses = {f"GET {url}": {"status": 200, "body": body}}
    transport = audit.ScriptedHubTransport(responses)

    default = audit.fetch_parquet_content(
        transport,
        transport.token,
        audit.STATE_REPO_ID,
        audit.STATE_PINNED_REVISION,
        path,
    )
    assert "partition_body_observation" not in default

    calls: list[bytes] = []

    def observer(serialized: bytes) -> dict[str, object]:
        calls.append(serialized)
        return {"observed": True}

    observed = audit.fetch_parquet_content(
        transport,
        transport.token,
        audit.STATE_REPO_ID,
        audit.STATE_PINNED_REVISION,
        path,
        expected_lfs_sha256=cli.hashlib.sha256(body).hexdigest(),
        partition_body_observer=observer,
    )
    assert calls == [body]
    assert observed["partition_body_observation"] == {"observed": True}

    calls.clear()
    with pytest.raises(audit.LiveBaselineAuditError, match="content hash mismatch"):
        audit.fetch_parquet_content(
            transport,
            transport.token,
            audit.STATE_REPO_ID,
            audit.STATE_PINNED_REVISION,
            path,
            expected_lfs_sha256="0" * 64,
            partition_body_observer=observer,
        )
    assert calls == []


def _recovery_manifest_row(code: str = "AL") -> dict[str, object]:
    parquet_name = f"STATE-{code}.parquet"
    manifest_dir = f"/sensitive/recovery/{code}"
    promotion_dir = f"{manifest_dir}/canonical_promotion"
    candidate_url = f"https://official.invalid/{code}/candidate"
    row: dict[str, object] = {
        key: None for key in cli._RECOVERY_MANIFEST_ROW_KEYS
    }
    row.update(
        {
            "archived_count": 0,
            "archived_source_urls": [],
            "candidate_count": 1,
            "candidate_urls": [candidate_url],
            "cid_field": "ipfs_cid",
            "citation_text": f"{code} recovery",
            "corpus_key": "state_laws",
            "generated_at": "2026-08-28T00:00:00Z",
            "hf_dataset_id": "justicedao/ipfs_state_laws",
            "manifest_directory": manifest_dir,
            "manifest_path": f"{manifest_dir}/recovery_manifest.json",
            "normalized_citation": f"{code} recovery",
            "preferred_parquet_names": [
                parquet_name,
                "state_laws_all_states.parquet",
            ],
            "primary_candidate_score": 1,
            "primary_candidate_source": "citation_url_hint",
            "primary_candidate_source_type": "current",
            "primary_candidate_title": f"{code} candidate",
            "primary_candidate_url": candidate_url,
            "promotion_json_path": f"{promotion_dir}/promotion_rows.json",
            "promotion_output_dir": promotion_dir,
            "promotion_parquet_path": f"{promotion_dir}/promotion_rows.parquet",
            "search_query": f"{code} code",
            "source_type": "legal_source_recovery_manifest",
            "state_code": code,
            "state_field": "state_code",
            "target_local_parquet_path": (
                f"/sensitive/work/state_laws_parquet_cid/{parquet_name}"
            ),
            "target_parquet_file": parquet_name,
            "target_parquet_path": f"state_laws_parquet_cid/{parquet_name}",
        }
    )
    return row


def test_baseline_partition_observer_binds_multiplicity_and_recovery_manifests() -> None:
    identity = "urn:state:al:statute:one"
    first = {key: None for key in cli._RECOVERY_MANIFEST_ROW_KEYS}
    first.update(
        {
            "state_code": "AL",
            "source_id": identity,
            "jsonld": json.dumps({"@id": identity}),
            "text": "first",
        }
    )
    variant = dict(first)
    variant["text"] = "variant"
    body = _baseline_parquet_bytes(
        [
            first,
            variant,
            _recovery_manifest_row(),
        ]
    )
    observed = cli._baseline_source_identity_observer_factory("AL")(body)
    assert observed["source_identities"] == [identity, identity]
    assert observed["source_identity_count"] == 2
    assert observed["noncomparable_recovery_manifest_count"] == 1
    assert observed["observed_row_count"] == 3
    serialized = json.dumps(observed, sort_keys=True)
    assert "/sensitive/" not in serialized


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_type", "unknown"),
        ("state_code", "AK"),
        ("target_parquet_path", "state_laws_parquet_cid/STATE-AK.parquet"),
        ("candidate_count", 2),
        ("text", "not a recovery-only row"),
        ("source_url", "https://official.invalid/law"),
    ],
)
def test_recovery_manifest_classification_is_narrow(
    field: str, value: object
) -> None:
    row = _recovery_manifest_row()
    row[field] = value
    with pytest.raises(
        cli.CandidateError,
        match="substantive baseline row|conflicting jurisdiction",
    ):
        cli._baseline_source_identity_observer_factory("AL")(
            _baseline_parquet_bytes([row])
        )


@pytest.mark.parametrize(
    "row",
    [
        {
            "state_code": "AL",
            "source_id": None,
            "jsonld": None,
            "text": "substantive",
        },
        {
            "state_code": "AL",
            "source_id": "urn:one",
            "jsonld": '{"@id":"urn:one","@id":"urn:two"}',
            "text": "substantive",
        },
        {
            "state_code": "AL",
            "source_id": "urn:one",
            "jsonld": '{"@id":"urn:two"}',
            "text": "substantive",
        },
    ],
)
def test_baseline_partition_observer_rejects_nonempty_missing_or_ambiguous_identity(
    row: dict[str, object]
) -> None:
    with pytest.raises(cli.CandidateError, match="baseline row|JSON-LD"):
        cli._baseline_source_identity_observer_factory("AL")(
            _baseline_parquet_bytes([row])
        )


def _production_evidence(
    *, sealed_at: datetime | None = None
) -> dict[str, object]:
    seal_time = sealed_at or datetime.now(UTC) - timedelta(seconds=1)
    observation_time = (seal_time - timedelta(minutes=2)).isoformat().replace(
        "+00:00", "Z"
    )
    run_seal_time = (seal_time - timedelta(minutes=1)).isoformat().replace(
        "+00:00", "Z"
    )
    baseline_time = (seal_time - timedelta(minutes=3)).isoformat().replace(
        "+00:00", "Z"
    )
    jurisdictions = []
    official_replay = []
    partitions = []
    reconciliation = []
    per_jurisdiction = []
    source_versions = []
    runner_identity = f"refresh@sha256:{'7' * 64}"
    for position, code in enumerate(CANONICAL_JURISDICTION_ORDER):
        digest = f"{position + 1:064x}"
        jurisdictions.append(
            {
                "canonical_jsonld_path": f"evidence/STATE-{code}.jsonld",
                "canonical_jsonld_sha256": digest,
                "canonical_row_count": 1,
                "content_hashes_digest_sha256": "1" * 64,
                "discovered": 1,
                "duplicates": 0,
                "excluded": 0,
                "failed_final": 0,
                "fetched": 1,
                "frontier_closed": True,
                "jurisdiction": code,
                "normalized_source_receipt_path": f"evidence/{code}.json",
                "normalized_source_receipt_sha256": "2" * 64,
                "observation_time": observation_time,
                "official_source_url": f"https://official.invalid/{code}",
                "quarantined": 0,
                "receipt_id": f"receipt-{code}",
                "release_point": f"release-{code}",
                "release_source_receipt_digest_sha256": "3" * 64,
                "release_source_receipt_path": f"receipts/{code}.json",
                "release_source_receipt_sha256": "4" * 64,
                "run_seal_created_at": run_seal_time,
                "run_seal_path": f"evidence/{code}.seal.json",
                "run_seal_sha256": "5" * 64,
                "source_software_version": f"scraper-{code}",
            }
        )
        partitions.append(
            {
                "content_sha256": "6" * 64,
                "footer_sha256": "7" * 64,
                "jurisdiction": code,
                "noncomparable_recovery_manifest_count": 0,
                "noncomparable_recovery_manifest_multiset_sha256": cli.digest_payload([]),
                "num_rows": 1,
                "path": f"STATE-{code}.parquet",
                "source_identity_count": 1,
                "source_identity_multiset_sha256": cli.digest_payload(
                    [f"urn:test:{code}:one"]
                ),
            }
        )
        reconciliation.append(
            {
                "acquired_row_count": 1,
                "acquired_source_identity_count": 1,
                "acquired_source_identity_multiset_sha256": cli.digest_payload(
                    [f"urn:test:{code}:one"]
                ),
                "added_source_identity_count": 0,
                "added_source_identity_multiset_sha256": cli.digest_payload([]),
                "baseline_noncomparable_recovery_manifest_count": 0,
                "baseline_noncomparable_recovery_manifest_disposition": (
                    "authenticated_baseline_recovery_manifest"
                ),
                "baseline_noncomparable_recovery_manifest_multiset_sha256": cli.digest_payload([]),
                "baseline_row_count": 1,
                "baseline_source_identity_count": 1,
                "baseline_source_identity_multiset_sha256": cli.digest_payload(
                    [f"urn:test:{code}:one"]
                ),
                "delta_from_baseline": 0,
                "disposition": "exact_match",
                "duplicate_count": 0,
                "excluded_count": 0,
                "explained_delta_count": 0,
                "jurisdiction": code,
                "quarantined_count": 0,
                "removed_source_identity_count": 0,
                "removed_source_identity_multiset_sha256": cli.digest_payload([]),
            }
        )
        shard = {
            "first_key": digest,
            "last_key": digest,
            "relative_path": f"data/corpus/jurisdiction/{code}/part.parquet",
            "row_count": 1,
            "sha256": "8" * 64,
        }
        per_jurisdiction.append(
            {
                "adapter_dispositions": {
                    "admitted": 1,
                    "quarantined": 0,
                    "rejected": 0,
                },
                "admitted_row_count": 1,
                "input_corpus_rows_digest_sha256": "9" * 64,
                "input_entry_cids_digest_sha256": "a" * 64,
                "jurisdiction": code,
                "release_corpus_rows_digest_sha256": "9" * 64,
                "release_corpus_shards": [shard],
                "release_corpus_shards_digest_sha256": cli.digest_payload([shard]),
                "release_entry_cids_digest_sha256": "a" * 64,
            }
        )
        source_versions.append(
            {
                "jurisdiction": code,
                "source_software_version": f"scraper-{code}",
            }
        )
        official_replay.append(
            {
                "acquisition_path_ids": [f"official-{code.lower()}"],
                "canonical_row_count": 1,
                "content_body_hashes_digest_sha256": "1" * 64,
                "corpus_entry_cids_digest_sha256": "a" * 64,
                "corpus_rows_digest_sha256": "9" * 64,
                "jurisdiction": code,
                "official_source_url": f"https://official.invalid/{code}",
                "request_ledger_sha256": "2" * 64,
                "response_ledger_sha256": "3" * 64,
                "response_projection_digest_sha256": "4" * 64,
                "runner_identity_binding": {
                    "runner_end_identity": runner_identity,
                    "runner_start_identity": runner_identity,
                    "source_software_version": f"scraper-{code}",
                },
                "selected_evidence": {
                    "canonical_jsonld_sha256": digest,
                    "closure_input_sha256": "1" * 64,
                    "legacy_receipt_sha256": "2" * 64,
                    "normalized_source_receipt_sha256": "2" * 64,
                    "run_seal_canonical_jsonld_sha256": digest,
                    "run_seal_normalized_source_receipt_sha256": "2" * 64,
                    "run_seal_sha256": "5" * 64,
                    "selected_corpus_rows_digest_sha256": "9" * 64,
                    "selected_entry_cids_digest_sha256": "a" * 64,
                },
                "source_software_version": f"scraper-{code}",
                "start_urls": [f"https://official.invalid/{code}"],
                "terminal_projection_digest_sha256": "5" * 64,
            }
        )
    artifact = {
        "family": "corpus",
        "relative_path": "data/corpus/part.parquet",
        "row_count": 51,
        "sha256": "b" * 64,
        "size_bytes": 1,
    }
    source_digest = "c" * 64
    return {
        "authenticated_live_baseline": {
            "live_replay_request_count": 100,
            "observed_at": baseline_time,
            "partitions": partitions,
            "partitions_digest_sha256": cli.digest_payload(partitions),
            "path": cli.DEFAULT_LIVE_BASELINE_RELPATH.as_posix(),
            "receipt_digest_sha256": "d" * 64,
            "remote_projection_digest_sha256": "e" * 64,
            "sha256": "f" * 64,
            "source_identity_closure_digest_sha256": cli.digest_payload(
                [
                    {
                        "jurisdiction": item["jurisdiction"],
                        "noncomparable_recovery_manifest_count": item[
                            "noncomparable_recovery_manifest_count"
                        ],
                        "noncomparable_recovery_manifest_multiset_sha256": item[
                            "noncomparable_recovery_manifest_multiset_sha256"
                        ],
                        "source_identity_count": item["source_identity_count"],
                        "source_identity_multiset_sha256": item[
                            "source_identity_multiset_sha256"
                        ],
                    }
                    for item in partitions
                ]
            ),
            "source_identity_closure_schema": (
                cli.BASELINE_SOURCE_IDENTITY_CLOSURE_SCHEMA
            ),
            "state_revision": "1" * 40,
            "verifier_owned_live_reobservation": True,
        },
        "baseline_reconciliation": reconciliation,
        "input_map": {
            "path": "evidence/input-map.json",
            "schema_version": "state-laws-production-input-map/v2",
            "sha256": "1" * 64,
        },
        "jurisdictions": jurisdictions,
        "official_frontier_reobservation": {
            "copied_file_count": 0,
            "derivation_reverified_with_current_code": True,
            "hardlinked_file_count": 102,
            "jurisdiction_count": 51,
            "jurisdictions": official_replay,
            "jurisdictions_digest_sha256": cli.digest_payload(official_replay),
            "network_io_performed": False,
            "origin_reauthentication_performed": False,
            "provenance_trust_root": "verified-retained-acquisition-bytes",
            "retained_replay_completed": True,
            "schema_version": "state-laws-verifier-retained-replay/v1",
            "verifier_owned": True,
        },
        "production_release": {
            "artifact_count": 1,
            "artifact_descriptors_digest_sha256": cli.digest_payload([artifact]),
            "artifacts": [artifact],
            "counts": [{"name": "corpus_documents", "value": 51}],
            "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
            "key_parity": {
                "chunk_cid_count": 51,
                "chunk_cids_exact": True,
                "chunk_cids_sha256": "2" * 64,
                "document_chunk_mapping_exact": True,
                "document_chunk_mapping_sha256": "3" * 64,
                "exact": True,
                "parent_entry_cid_count": 51,
                "parent_entry_cids_sha256": "4" * 64,
            },
            "manifest_digest": "a" * 64,
            "manifest_file_sha256": "b" * 64,
            "manifest_path": "release/manifest.json",
            "manifest_size_bytes": 1,
            "output_root": "release",
            "release_point": "production-release",
            "source_revision": "d" * 40,
        },
        "rights_receipt": {
            "catalog_digest_sha256": "5" * 64,
            "path": "evidence/rights.json",
            "receipt_digest_sha256": "c" * 64,
            "sha256": "6" * 64,
            "status": "passed",
        },
        "source_bundle": {
            "current_source_software_versions": source_versions,
            "current_source_software_versions_digest_sha256": cli.digest_payload(
                source_versions
            ),
            "refresh_runner_source_software_version": runner_identity,
        },
        "source_control": {
            "clean_at_seal": True,
            "excluded_evidence_paths": [
                cli.DEFAULT_LIVE_BASELINE_RELPATH.as_posix(),
                "docs/reports/legal_corpora_reindex/full_scrape_acceptance.json",
                "docs/reports/legal_corpora_reindex/release_candidate.json",
            ],
            "revision": "d" * 40,
            "tree": "8" * 40,
        },
        "source_receipts_digest_sha256": source_digest,
        "union": {
            "deduped_corpus_rows_digest_sha256": "9" * 64,
            "deduped_entry_cids_digest_sha256": "4" * 64,
            "deduped_union_count": 51,
            "duplicate_row_count": 0,
            "input_source_receipts_digest_sha256": source_digest,
            "per_jurisdiction": per_jurisdiction,
            "release_source_receipts_digest_sha256": source_digest,
            "shard_sum_before_dedup": 51,
        },
    }


def _production_candidate(tmp_path: Path) -> dict[str, object]:
    # Production mutation inventory is intentionally Git-tracked and has no
    # non-Git fallback.  This synthetic evidence root has an explicit empty
    # tracked-Python scope unless an individual regression stages sources.
    _git(tmp_path, "init", "--quiet")
    sealed_at = datetime.now(UTC) - timedelta(seconds=1)
    sealed_at_text = sealed_at.isoformat().replace("+00:00", "Z")
    evidence = _production_evidence(sealed_at=sealed_at)
    evidence_digest = cli.digest_payload(evidence)
    for relative in (
        "evidence/input-map.json",
        "evidence/rights.json",
        cli.DEFAULT_LIVE_BASELINE_RELPATH,
    ):
        evidence_file = tmp_path / relative
        evidence_file.parent.mkdir(parents=True, exist_ok=True)
        evidence_file.write_text("{}\n", encoding="utf-8")
    (tmp_path / "release").mkdir()
    schema_path = tmp_path / "data/legal/state_laws_full_scrape_acceptance.schema.json"
    schema_path.parent.mkdir(parents=True, exist_ok=True)
    schema_path.write_bytes(
        (REPO_ROOT / "data/legal/state_laws_full_scrape_acceptance.schema.json").read_bytes()
    )
    mutation_schema_path = (
        tmp_path / cli.mutation_path_audit.SCHEMA_RELPATH
    )
    mutation_schema_path.parent.mkdir(parents=True, exist_ok=True)
    mutation_schema_path.write_bytes(
        (
            REPO_ROOT
            / cli.mutation_path_audit.SCHEMA_RELPATH
        ).read_bytes()
    )
    measured_mutations = cli.mutation_path_audit.inventory_mutation_paths(
        repository_root=tmp_path
    )
    mutation_report_path = (
        tmp_path / cli.PRODUCTION_MUTATION_AUDIT_RELPATH
    )
    mutation_report_path.parent.mkdir(parents=True, exist_ok=True)
    mutation_report_path.write_text(
        cli.mutation_path_audit._canonical_report_text(measured_mutations),
        encoding="utf-8",
    )
    mutation_audit = cli._production_mutation_audit_binding(
        repo_root=tmp_path
    )
    acceptance_path = tmp_path / cli.PRODUCTION_ACCEPTANCE_RELPATH
    acceptance_path.parent.mkdir(parents=True, exist_ok=True)
    acceptance_document: dict[str, object] = {
        "authorizing_for_publication": False,
        "authorizing_hub_upload": False,
        "candidate_requirement": {
            "candidate_path": cli.DEFAULT_REPORT_RELPATH.as_posix(),
            "candidate_schema": cli.PRODUCTION_REPORT_SCHEMA,
            "manifest_digest": evidence["production_release"]["manifest_digest"],
            "production_evidence_digest_sha256": evidence_digest,
        },
        "evidence": evidence,
        "freshness_max_age_seconds": 2592000,
        "goal_id": cli.PRODUCTION_GOAL_ID,
        "hub_mutation_performed": False,
        "jurisdiction_codes": list(CANONICAL_JURISDICTION_ORDER),
        "jurisdiction_count": 51,
        "local_only": False,
        "mode": "live_official",
        "network_io_performed": True,
        "producer": "audit_state_laws_full_scrape_acceptance.py",
        "production_evidence_digest_sha256": evidence_digest,
        "production_generation_local_only": True,
        "program_id": cli.PROGRAM_ID,
        "read_only_live_verification": True,
        "report_digest_sha256": "0" * 64,
        "schema": cli.PRODUCTION_ACCEPTANCE_SCHEMA,
        "sealed_at": sealed_at_text,
        "status": "passed",
        "task_id": cli.PRODUCTION_TASK_ID,
    }
    acceptance_document["report_digest_sha256"] = cli._digest_for_report(
        acceptance_document
    )
    acceptance_path.write_text(
        json.dumps(acceptance_document, sort_keys=True), encoding="utf-8"
    )
    payload: dict[str, object] = {
        "acceptance": {
            "byte_descriptor_complete": True,
            "contains_exact_51": True,
            "full_scrape_acceptance_path": cli.PRODUCTION_ACCEPTANCE_RELPATH.as_posix(),
            "full_scrape_acceptance_report_digest_sha256": acceptance_document[
                "report_digest_sha256"
            ],
            "full_scrape_acceptance_sealed_at": sealed_at_text,
            "full_scrape_acceptance_sha256": cli.file_sha256(acceptance_path),
            "live_official": True,
            "no_hub_mutation": True,
            "production_evidence_digest_sha256": evidence_digest,
            "required_semantic_families": True,
        },
        "authorizing_for_publication": False,
        "authorizing_for_release": False,
        "board_namespace": cli.BOARD_NAMESPACE,
        "bundle": "state-full-live-acceptance-hardening",
        "candidate": {
            "acceptance_schema": cli.PRODUCTION_ACCEPTANCE_SCHEMA,
            "kind": cli.PRODUCTION_KIND,
        },
        "code_version": "2",
        "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
        "families": list(cli.REQUIRED_FAMILIES),
        "fixture_only": False,
        "goal_id": cli.PRODUCTION_GOAL_ID,
        "hub_upload": False,
        "hub_mutation_performed": False,
        "inputs": {
            "input_map_path": evidence["input_map"]["path"],
            "input_map_sha256": evidence["input_map"]["sha256"],
            "live_baseline_path": evidence["authenticated_live_baseline"]["path"],
            "live_baseline_sha256": evidence["authenticated_live_baseline"]["sha256"],
            "source_rights_receipt_path": evidence["rights_receipt"]["path"],
            "source_rights_receipt_sha256": evidence["rights_receipt"]["sha256"],
        },
        "jurisdiction_codes": list(CANONICAL_JURISDICTION_ORDER),
        "jurisdiction_count": 51,
        "local_only": False,
        "manifest_digest": "a" * 64,
        "manifest_file_sha256": "b" * 64,
        "model_id": DEFAULT_EMBEDDING_MODEL_ID,
        "model_revision": DEFAULT_EMBEDDING_MODEL_REVISION,
        "mutation_audit": mutation_audit,
        "network_io_performed": True,
        "producer": cli.PRODUCER,
        "production_generation_local_only": True,
        "production_evidence": evidence,
        "production_evidence_digest_sha256": evidence_digest,
        "program_id": cli.PROGRAM_ID,
        "publication_binding": None,
        "proves_software_contract_only": False,
        "read_only_live_verification": True,
        "release_profile": cli.RELEASE_PROFILE,
        "report_digest_sha256": "0" * 64,
        "schema": cli.PRODUCTION_REPORT_SCHEMA,
        "schema_version": cli.PRODUCTION_SCHEMA_VERSION,
        "sealed_at": sealed_at_text,
        "source_revision": "d" * 40,
        "source_rights_catalog_digest": evidence["rights_receipt"][
            "catalog_digest_sha256"
        ],
        "source_rights_receipt_digest": "c" * 64,
        "status": "passed",
        "task_id": cli.PRODUCTION_TASK_ID,
        "validation": {
            "artifact_count": 1,
            "descriptor_bytes_verified": True,
            "local_release_verified": True,
            "valid": True,
        },
    }
    payload["report_digest_sha256"] = cli._digest_for_report(payload)
    return payload


def _main_publication_candidate(
    staging: dict[str, object],
) -> tuple[dict[str, object], str]:
    candidate = copy.deepcopy(staging)
    staging_digest = cli.production_candidate_staging_digest(candidate)
    candidate["publication_binding"] = {
        "plan_digest": "1" * 64,
        "policy_proof_digest": "2" * 64,
        "release_manifest_digest": candidate["manifest_digest"],
        "staging_candidate_digest": staging_digest,
    }
    candidate["report_digest_sha256"] = cli._digest_for_report(candidate)
    return candidate, staging_digest


def test_production_candidate_publication_binding_has_distinct_a_b_chain(
    tmp_path: Path,
) -> None:
    staging = _production_candidate(tmp_path)
    assert staging["publication_binding"] is None
    assert cli.check_production_candidate_publication_binding(
        staging,
        phase="state_staging",
    ) is None
    with pytest.raises(cli.CandidateError, match="state_main requires"):
        cli.check_production_candidate_publication_binding(
            staging,
            phase="state_main",
        )

    main, staging_digest = _main_publication_candidate(staging)
    binding = cli.check_production_candidate_publication_binding(
        main,
        phase="state_main",
    )
    assert binding is not None
    assert binding["staging_candidate_digest"] == staging_digest
    assert main["report_digest_sha256"] != staging_digest
    assert cli.production_candidate_staging_digest(main) == staging_digest
    cli.check_production_candidate_report(
        main,
        repo_root=tmp_path,
        remeasure_production_evidence=False,
    )


def test_production_mutation_binding_consumes_one_paired_source_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _production_candidate(tmp_path)
    paired = cli.mutation_path_audit.validate_frozen_mutation_capture(
        repository_root=tmp_path
    )
    calls = {"paired": 0}

    def _paired(**_kwargs: object) -> object:
        calls["paired"] += 1
        return paired

    def _forbid_split(*_args: object, **_kwargs: object) -> object:
        pytest.fail("authority binding used a split inventory/projection API")

    monkeypatch.setattr(
        cli.mutation_path_audit,
        "validate_frozen_mutation_capture",
        _paired,
    )
    monkeypatch.setattr(
        cli.mutation_path_audit,
        "validate_frozen_mutation_inventory",
        _forbid_split,
    )
    monkeypatch.setattr(
        cli.mutation_path_audit,
        "mutation_source_projection",
        _forbid_split,
    )

    binding = cli._production_mutation_audit_binding(repo_root=tmp_path)

    assert calls == {"paired": 1}
    assert binding["inventory_digest_sha256"] == cli.digest_payload(
        paired.report
    )
    assert binding["source_file_count"] == len(paired.source_projection)
    assert binding["source_projection_digest_sha256"] == cli.digest_payload(
        paired.source_projection
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("staging_candidate_digest", "3" * 64, "differs from A"),
        ("release_manifest_digest", "4" * 64, "release manifest differs"),
        ("plan_digest", "not-a-digest", "lowercase SHA-256"),
    ],
)
def test_production_candidate_publication_binding_rejects_chain_tampering(
    tmp_path: Path,
    field: str,
    value: str,
    message: str,
) -> None:
    main, _ = _main_publication_candidate(_production_candidate(tmp_path))
    binding = main["publication_binding"]
    assert isinstance(binding, dict)
    binding[field] = value
    main["report_digest_sha256"] = cli._digest_for_report(main)
    with pytest.raises(cli.CandidateError, match=message):
        cli.check_production_candidate_publication_binding(
            main,
            phase="state_main",
        )


def test_production_candidate_publication_binding_rejects_at1_main_bypass() -> None:
    with pytest.raises(cli.CandidateError, match="@2"):
        cli.check_production_candidate_publication_binding(
            {
                "schema": cli.REPORT_SCHEMA,
                "publication_binding": {
                    "plan_digest": "1" * 64,
                    "policy_proof_digest": "2" * 64,
                    "release_manifest_digest": "3" * 64,
                    "staging_candidate_digest": "4" * 64,
                },
            },
            phase="state_main",
        )


def test_candidate_baseline_anchor_survives_fresh_live_replay_runtime() -> None:
    checked_at = datetime.now(UTC)
    sealed_at = checked_at - timedelta(minutes=1)
    evidence = _production_evidence(sealed_at=sealed_at)
    baseline = evidence["authenticated_live_baseline"]
    assert isinstance(baseline, dict)

    baseline["observed_at"] = (checked_at - timedelta(hours=2)).isoformat()
    cli._validate_candidate_evidence_chronology(
        evidence,
        sealed_at=sealed_at,
        checked_at=checked_at,
    )

    baseline["observed_at"] = (checked_at - timedelta(days=31)).isoformat()
    with pytest.raises(cli.CandidateError, match="live baseline is stale"):
        cli._validate_candidate_evidence_chronology(
            evidence,
            sealed_at=sealed_at,
            checked_at=checked_at,
        )


def test_retained_replay_comparison_is_repeatable_but_semantic_exact() -> None:
    first = _production_evidence()["official_frontier_reobservation"]
    second = copy.deepcopy(first)
    selected = second["jurisdictions"][0]["selected_evidence"]  # type: ignore[index]
    selected["legacy_receipt_sha256"] = "0" * 64
    selected["closure_input_sha256"] = "1" * 64
    selected["run_seal_sha256"] = "2" * 64
    assert cli._retained_replay_comparison_projection(
        first  # type: ignore[arg-type]
    ) == cli._retained_replay_comparison_projection(second)  # type: ignore[arg-type]

    second["jurisdictions"][0]["terminal_projection_digest_sha256"] = "3" * 64  # type: ignore[index]
    assert cli._retained_replay_comparison_projection(
        first  # type: ignore[arg-type]
    ) != cli._retained_replay_comparison_projection(second)  # type: ignore[arg-type]


def _retained_replay_subprocess_result(*, status: str = "success") -> dict[str, object]:
    inventory = {
        "candidate_count": 0,
        "complete": True,
        "closure_projection_missing_jurisdictions": [],
        "gap_jurisdictions": [],
        "jurisdiction_count": 51,
        "jurisdictions": {
            code: {
                "candidate_count": 0,
                "closure_projection_producer_present": True,
                "complete": True,
            }
            for code in CANONICAL_JURISDICTION_ORDER
        },
        "publication_evidence_complete": True,
        "schema_version": "state-laws-registered-transport-bypass-inventory-v1",
    }
    expected = list(CANONICAL_JURISDICTION_ORDER)
    return {
        "acquisition_evidence": {
            "aggregate_closed_count": 51,
            "authorizing_for_publication": True,
            "evidence_gap_states": [],
            "retained_replay_only": True,
            "strict": True,
            "transport_bypass_inventory": inventory,
        },
        "build": {"missing_jsonld_states": []},
        "build_gap_states": [],
        "plan": {
            "incremental_state_publish": False,
            "merge_hf_existing": False,
            "publish_to_hf": False,
            "requested_state_count": 51,
            "requested_states": expected,
            "retained_replay_only": True,
            "scrape": True,
            "skipped_completed_count": 0,
            "skipped_completed_states": [],
            "startup_stale_sync": False,
            "state_count": 51,
            "states": expected,
            "strict_acquisition_evidence": True,
            "transport_bypass_inventory": inventory,
        },
        "scrape_gap_states": [],
        "status": status,
    }


def test_retained_replay_subprocess_requires_strict_exact_success() -> None:
    result = _retained_replay_subprocess_result()
    assert cli._parse_retained_replay_result(json.dumps(result)) == result

    result["status"] = "partial_success"
    with pytest.raises(cli.CandidateError, match="exact success"):
        cli._parse_retained_replay_result(json.dumps(result))
    with pytest.raises(cli.CandidateError, match="duplicate key"):
        cli._parse_retained_replay_result('{"status":"success","status":"success"}')


def test_retained_replay_rejects_duplicate_keys_in_raw_fetch_receipt(
    tmp_path: Path,
) -> None:
    fetch = tmp_path / "fetch.json"
    fetch.write_text(
        '{"schema_version":"one","transport_receipt":{"status":200,"status":201}}',
        encoding="utf-8",
    )
    with pytest.raises(cli.CandidateError, match="duplicate key"):
        cli._strict_retained_fetch_evidence_hashes(
            [SimpleNamespace(evidence_path=fetch)], jurisdiction="AK"
        )


def test_retained_replay_subprocess_kills_live_spam_at_combined_bound(
    tmp_path: Path,
) -> None:
    spammer = (
        "import sys\n"
        "chunk=b'x'*65536\n"
        "while True:\n"
        " sys.stderr.buffer.write(chunk)\n"
        " sys.stderr.buffer.flush()\n"
    )
    with pytest.raises(cli.CandidateError, match="output exceeded"):
        cli._run_bounded_retained_replay_subprocess(
            [sys.executable, "-I", "-c", spammer],
            cwd=tmp_path,
            environment={},
            timeout_seconds=10,
            output_limit_bytes=4096,
        )


def test_retained_replay_subprocess_kills_descendant_after_leader_exit(
    tmp_path: Path,
) -> None:
    pid_path = tmp_path / "descendant.pid"
    leader = (
        "import pathlib,subprocess,sys\n"
        "child=subprocess.Popen([sys.executable,'-I','-c',"
        "'import time;time.sleep(60)'])\n"
        f"pathlib.Path({str(pid_path)!r}).write_text(str(child.pid))\n"
    )
    child_pid: int | None = None
    try:
        with pytest.raises(cli.CandidateError, match="timed out"):
            cli._run_bounded_retained_replay_subprocess(
                [sys.executable, "-I", "-c", leader],
                cwd=tmp_path,
                environment={},
                timeout_seconds=0.5,
                output_limit_bytes=4096,
            )
        child_pid = int(pid_path.read_text(encoding="utf-8"))
        child_proc = Path(f"/proc/{child_pid}")

        def _descendant_is_live() -> bool:
            if not child_proc.exists():
                return False
            try:
                return child_proc.joinpath("stat").read_text().split()[2] != "Z"
            except (FileNotFoundError, IndexError):
                return False

        deadline = time.monotonic() + 5
        while _descendant_is_live() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not _descendant_is_live()
    finally:
        if child_pid is not None and Path(f"/proc/{child_pid}").exists():
            os.kill(child_pid, signal.SIGKILL)


def test_retained_replay_subprocess_returns_bounded_diagnostics(
    tmp_path: Path,
) -> None:
    returncode, stdout, stderr_tail = (
        cli._run_bounded_retained_replay_subprocess(
            [
                sys.executable,
                "-I",
                "-c",
                "import sys;sys.stdout.write('{}');sys.stderr.write('diagnostic')",
            ],
            cwd=tmp_path,
            environment={},
            timeout_seconds=10,
            output_limit_bytes=4096,
        )
    )
    assert returncode == 0
    assert stdout == b"{}"
    assert stderr_tail == "diagnostic"


@pytest.mark.parametrize(
    "mutation",
    ["manifest", "evidence", "mutation_audit", "rights_catalog", "extra"],
)
def test_production_candidate_rejects_mutated_bindings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    payload = _production_candidate(tmp_path)
    measured = copy.deepcopy(payload["production_evidence"])
    monkeypatch.setattr(
        cli,
        "collect_production_evidence",
        lambda **_kwargs: copy.deepcopy(measured),
    )
    cli.check_production_candidate_report(payload, repo_root=tmp_path)
    if mutation == "manifest":
        payload["manifest_digest"] = "0" * 64
    elif mutation == "evidence":
        payload["production_evidence_digest_sha256"] = "0" * 64
    elif mutation == "mutation_audit":
        payload["mutation_audit"]["inventory_digest_sha256"] = "0" * 64  # type: ignore[index]
        payload["report_digest_sha256"] = cli._digest_for_report(payload)
    elif mutation == "rights_catalog":
        payload["source_rights_catalog_digest"] = "0" * 64
        payload["report_digest_sha256"] = cli._digest_for_report(payload)
    else:
        payload["caller_authority"] = True
    with pytest.raises(cli.CandidateError):
        cli.check_production_candidate_report(payload, repo_root=tmp_path)


@pytest.mark.parametrize(
    "mutation",
    [
        "dataset_repo_id",
        "families",
        "inputs",
        "producer",
        "release_profile",
        "sealed_at",
        "board_namespace",
        "bundle",
        "code_version",
        "acceptance_extra",
        "validation_extra",
        "evidence_extra",
    ],
)
def test_production_candidate_rejects_self_digested_claim_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    payload = _production_candidate(tmp_path)
    measured = copy.deepcopy(payload["production_evidence"])
    monkeypatch.setattr(
        cli,
        "collect_production_evidence",
        lambda **_kwargs: copy.deepcopy(measured),
    )
    if mutation == "dataset_repo_id":
        payload["dataset_repo_id"] = "attacker/other"
    elif mutation == "families":
        payload["families"] = ["corpus"]
    elif mutation == "inputs":
        payload["inputs"]["input_map_sha256"] = "0" * 64  # type: ignore[index]
    elif mutation == "producer":
        payload["producer"] = "caller.py"
    elif mutation == "release_profile":
        payload["release_profile"] = "other"
    elif mutation == "sealed_at":
        payload["sealed_at"] = "2026-08-28T02:00:01Z"
    elif mutation == "board_namespace":
        payload["board_namespace"] = "other"
    elif mutation == "bundle":
        payload["bundle"] = "other"
    elif mutation == "code_version":
        payload["code_version"] = "999"
    elif mutation == "acceptance_extra":
        payload["acceptance"]["caller_claim"] = True  # type: ignore[index]
    elif mutation == "validation_extra":
        payload["validation"]["caller_claim"] = True  # type: ignore[index]
    else:
        payload["production_evidence"]["caller_claim"] = True  # type: ignore[index]
        payload["production_evidence_digest_sha256"] = cli.digest_payload(
            payload["production_evidence"]
        )
        payload["acceptance"]["production_evidence_digest_sha256"] = payload[  # type: ignore[index]
            "production_evidence_digest_sha256"
        ]
    payload["report_digest_sha256"] = cli._digest_for_report(payload)
    with pytest.raises(cli.CandidateError):
        cli.check_production_candidate_report(payload, repo_root=tmp_path)


def test_production_candidate_check_mandatorily_remeasures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = _production_candidate(tmp_path)
    measured = copy.deepcopy(payload["production_evidence"])
    calls = {"collect": 0}

    captured: dict[str, object] = {}

    def collect(**kwargs: object) -> object:
        calls["collect"] += 1
        captured.update(kwargs)
        return copy.deepcopy(measured)

    monkeypatch.setattr(cli, "collect_production_evidence", collect)
    cli.check_production_candidate_report(payload, repo_root=tmp_path)
    assert calls == {"collect": 1}
    assert captured["input_map_path"] == tmp_path / "evidence/input-map.json"
    assert captured["rights_receipt_path"] == tmp_path / "evidence/rights.json"
    assert captured["production_output_root"] == tmp_path / "release"
    assert captured["live_baseline_path"] == (
        tmp_path / cli.DEFAULT_LIVE_BASELINE_RELPATH
    )


@pytest.mark.parametrize("surface", ["acceptance", "mutation_audit"])
def test_production_candidate_final_evidence_bookend_rejects_byte_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    surface: str,
) -> None:
    payload = _production_candidate(tmp_path)
    measured = copy.deepcopy(payload["production_evidence"])
    target = (
        tmp_path / cli.PRODUCTION_ACCEPTANCE_RELPATH
        if surface == "acceptance"
        else tmp_path / cli.PRODUCTION_MUTATION_AUDIT_RELPATH
    )

    def collect(**_kwargs: object) -> object:
        target.write_bytes(target.read_bytes() + b"\n")
        return copy.deepcopy(measured)

    monkeypatch.setattr(cli, "collect_production_evidence", collect)
    with pytest.raises(cli.CandidateError, match=surface.replace("_", ".*")):
        cli.check_production_candidate_report(payload, repo_root=tmp_path)


def test_production_candidate_rejects_stale_jurisdiction_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = _production_candidate(tmp_path)
    evidence = payload["production_evidence"]
    assert isinstance(evidence, dict)
    for item in evidence["jurisdictions"]:
        item["observation_time"] = "2025-01-01T00:00:00Z"
        item["run_seal_created_at"] = "2025-01-02T00:00:00Z"
    evidence_digest = cli.digest_payload(evidence)
    payload["production_evidence_digest_sha256"] = evidence_digest
    payload["acceptance"]["production_evidence_digest_sha256"] = evidence_digest

    acceptance_path = tmp_path / cli.PRODUCTION_ACCEPTANCE_RELPATH
    acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
    acceptance["evidence"] = copy.deepcopy(evidence)
    acceptance["production_evidence_digest_sha256"] = evidence_digest
    acceptance["candidate_requirement"][
        "production_evidence_digest_sha256"
    ] = evidence_digest
    acceptance["report_digest_sha256"] = cli._digest_for_report(acceptance)
    acceptance_path.write_text(json.dumps(acceptance, sort_keys=True), encoding="utf-8")
    payload["acceptance"]["full_scrape_acceptance_report_digest_sha256"] = acceptance[
        "report_digest_sha256"
    ]
    payload["acceptance"]["full_scrape_acceptance_sha256"] = cli.file_sha256(
        acceptance_path
    )
    payload["report_digest_sha256"] = cli._digest_for_report(payload)
    monkeypatch.setattr(
        cli,
        "collect_production_evidence",
        lambda **_kwargs: copy.deepcopy(evidence),
    )
    with pytest.raises(cli.CandidateError, match="stale"):
        cli.check_production_candidate_report(payload, repo_root=tmp_path)


@pytest.mark.parametrize("mutation", ["noncanonical", "symlink"])
def test_production_candidate_requires_nofollow_canonical_acceptance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    payload = _production_candidate(tmp_path)
    canonical = tmp_path / cli.PRODUCTION_ACCEPTANCE_RELPATH
    if mutation == "noncanonical":
        other = tmp_path / "docs/other-acceptance.json"
        other.parent.mkdir(parents=True, exist_ok=True)
        other.write_bytes(canonical.read_bytes())
        payload["acceptance"]["full_scrape_acceptance_path"] = (  # type: ignore[index]
            "docs/other-acceptance.json"
        )
        payload["report_digest_sha256"] = cli._digest_for_report(payload)
        message = "canonical full-scrape acceptance"
    else:
        outside = tmp_path / "outside-acceptance.json"
        outside.write_bytes(canonical.read_bytes())
        canonical.unlink()
        canonical.symlink_to(outside)
        message = "symlink|unsafe"
    monkeypatch.setattr(
        cli,
        "collect_production_evidence",
        lambda **_kwargs: copy.deepcopy(payload["production_evidence"]),
    )
    with pytest.raises(cli.CandidateError, match=message):
        cli.check_production_candidate_report(payload, repo_root=tmp_path)


def test_acceptance_candidate_requirement_must_name_canonical_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = _production_candidate(tmp_path)
    acceptance_path = tmp_path / cli.PRODUCTION_ACCEPTANCE_RELPATH
    acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
    acceptance["candidate_requirement"]["candidate_path"] = "docs/other.json"
    acceptance["report_digest_sha256"] = cli._digest_for_report(acceptance)
    acceptance_path.write_text(json.dumps(acceptance, sort_keys=True), encoding="utf-8")
    payload["acceptance"]["full_scrape_acceptance_report_digest_sha256"] = (  # type: ignore[index]
        acceptance["report_digest_sha256"]
    )
    payload["acceptance"]["full_scrape_acceptance_sha256"] = cli.file_sha256(  # type: ignore[index]
        acceptance_path
    )
    payload["report_digest_sha256"] = cli._digest_for_report(payload)
    monkeypatch.setattr(
        cli,
        "collect_production_evidence",
        lambda **_kwargs: copy.deepcopy(payload["production_evidence"]),
    )
    with pytest.raises(cli.CandidateError, match="candidate requirement drifted"):
        cli.check_production_candidate_report(payload, repo_root=tmp_path)
