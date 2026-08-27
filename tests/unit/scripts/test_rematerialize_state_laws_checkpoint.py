"""Tests for offline state-law checkpoint rematerialization."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.ir_core import identity
from ipfs_datasets_py.processors.legal_data import state_laws_legacy_v2_adapter
from ipfs_datasets_py.processors.legal_scrapers import state_laws_scraper
from ipfs_datasets_py.retrieval.hf_graphrag import artifacts
from ipfs_datasets_py.retrieval.hf_graphrag.artifacts import file_digest

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "ops"
    / "legal_data"
    / "rematerialize_state_laws_checkpoint.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "rematerialize_state_laws_checkpoint_test_target", _SCRIPT_PATH
)
assert _SPEC is not None and _SPEC.loader is not None
cli = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = cli
_SPEC.loader.exec_module(cli)

VALID_SHORT_LAW = "A licensee shall comply with this section today."


def test_reuses_existing_normalization_quality_and_artifact_helpers() -> None:
    assert cli._write_state_jsonld_files is state_laws_scraper._write_state_jsonld_files
    assert (
        cli._is_scaffold_or_navigation_record
        is state_laws_scraper._is_scaffold_or_navigation_record
    )
    assert cli._legacy_fixture_reasons is state_laws_legacy_v2_adapter._fixture_reasons
    assert cli._legacy_row_source_url is state_laws_legacy_v2_adapter._row_source_url
    assert cli.file_digest is artifacts.file_digest
    assert cli.atomic_staging is artifacts.atomic_staging
    assert cli.cid_v1_from_digest is identity.cid_v1_from_digest


def _statute(
    *,
    text: str,
    section: str = "1-102",
    source_url: str = "https://delcode.delaware.gov/title1/c001/sc01/index.html",
) -> dict[str, object]:
    return {
        "state_code": "DE",
        "state_name": "Delaware",
        "code_name": "Delaware Code",
        "statute_id": f"Delaware Code § {section}",
        "section_number": section,
        "section_name": "Short operative provision",
        "source_url": source_url,
        "full_text": text,
    }


def _write_checkpoint(
    root: Path,
    *,
    statutes: list[object] | None = None,
    **overrides: object,
) -> Path:
    rows = statutes if statutes is not None else [_statute(text=VALID_SHORT_LAW)]
    payload: dict[str, object] = {
        "code_name": "scrape_all",
        "progress": {"codes_completed": 1, "codes_total": 1},
        "stage_label": "scrape_all:complete",
        "state_code": "DE",
        "state_name": "Delaware",
        "statutes": rows,
        "statutes_count": len(rows),
        "updated_at": "2026-08-24T01:02:03+00:00",
    }
    payload.update(overrides)
    path = root / "STATE-DE-partial.json"
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return path


def test_preserves_48_character_law_and_rejects_scaffold_and_placeholder(
    tmp_path: Path,
) -> None:
    assert len(VALID_SHORT_LAW) == 48
    checkpoint = _write_checkpoint(
        tmp_path,
        statutes=[
            _statute(text=VALID_SHORT_LAW),
            _statute(
                text="Section Section-1: Skip navigation Contact us",
                section="Section-1",
            ),
            _statute(text="Placeholder text", section="1-103"),
        ],
    )
    output_root = tmp_path / "materialized"

    result = cli.rematerialize_checkpoint(
        checkpoint_path=checkpoint,
        jurisdiction="DE",
        output_root=output_root,
    )

    assert result["status"] == "materialized"
    assert result["input_rows"] == 3
    assert result["accepted_rows"] == 1
    assert result["rejected_rows"] == 2
    output = Path(result["output_path"])
    assert output.parent.name == "state_laws_jsonld"
    rows = [
        json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == 1
    assert rows[0]["text"] == VALID_SHORT_LAW
    assert rows[0]["legislationJurisdiction"] == "US-DE"

    receipt_path = Path(result["receipt_path"])
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["filtering"]["minimum_text_characters"] == 1
    assert receipt["filtering"]["accepted_rows"] == 1
    assert receipt["filtering"]["rejected_rows"] == 2
    assert receipt["filtering"]["rejection_counts"]["placeholder_text"] == 1
    assert (
        receipt["filtering"]["rejection_counts"]["scaffold_or_navigation_record"] == 1
    )
    assert (
        receipt["source_lineage"]["checkpoint_sha256"]
        == file_digest(checkpoint)[1].hex()
    )
    assert receipt["output_artifact"]["sha256"] == file_digest(output)[1].hex()
    assert receipt["output_artifact"]["row_count"] == 1
    assert receipt["output_artifact"]["family"] == "source_artifact"
    assert receipt["output_artifact"]["metadata"]["physical_query_shard"] is False
    assert (
        receipt["output_artifact"]["content_cid"]
        == receipt["output_artifact"]["cid"]
    )
    assert receipt["network_access"] is False
    assert receipt["authorizing_for_publication"] is False
    assert receipt["authorizing_hub_upload"] is False


@pytest.mark.parametrize(
    ("overrides", "error_match"),
    [
        ({"stage_label": "scrape_all:code_complete"}, "stage_label"),
        ({"state_code": "MD"}, "state_code mismatch"),
        ({"statutes_count": 2}, "statutes_count"),
        (
            {"progress": {"codes_completed": 0, "codes_total": 1}},
            "progress is not closed",
        ),
    ],
)
def test_incomplete_or_mismatched_checkpoint_fails_closed(
    tmp_path: Path,
    overrides: dict[str, object],
    error_match: str,
) -> None:
    checkpoint = _write_checkpoint(tmp_path, **overrides)
    with pytest.raises(cli.CheckpointRematerializationError, match=error_match):
        cli.rematerialize_checkpoint(
            checkpoint_path=checkpoint,
            jurisdiction="DE",
            output_root=tmp_path / "materialized",
        )
    assert not (
        tmp_path / "materialized" / "state_laws_jsonld" / "STATE-DE.jsonld"
    ).exists()


def test_mixed_jurisdiction_row_fails_the_whole_checkpoint(tmp_path: Path) -> None:
    bad = _statute(text=VALID_SHORT_LAW)
    bad["state_code"] = "MD"
    checkpoint = _write_checkpoint(tmp_path, statutes=[bad])

    with pytest.raises(
        cli.CheckpointRematerializationError, match=r"statutes\[0\].state_code"
    ):
        cli.rematerialize_checkpoint(
            checkpoint_path=checkpoint,
            jurisdiction="DE",
            output_root=tmp_path / "materialized",
        )


def test_completed_single_code_checkpoint_rejects_stale_larger_row_snapshot(
    tmp_path: Path,
) -> None:
    checkpoint = _write_checkpoint(
        tmp_path,
        statutes=[
            _statute(text=VALID_SHORT_LAW),
            _statute(text=VALID_SHORT_LAW, section="1-103"),
        ],
        progress={
            "codes_completed": 1,
            "codes_total": 1,
            "latest_code_statutes": 1,
        },
    )

    with pytest.raises(
        cli.CheckpointRematerializationError,
        match="row snapshot does not match the completed single-code result",
    ):
        cli.rematerialize_checkpoint(
            checkpoint_path=checkpoint,
            jurisdiction="DE",
            output_root=tmp_path / "materialized",
        )

    assert not (tmp_path / "materialized").exists()


def test_zero_or_all_rejected_checkpoint_fails_without_artifacts(
    tmp_path: Path,
) -> None:
    zero = _write_checkpoint(tmp_path, statutes=[])
    with pytest.raises(cli.CheckpointRematerializationError, match="zero statutes"):
        cli.rematerialize_checkpoint(
            checkpoint_path=zero,
            jurisdiction="DE",
            output_root=tmp_path / "zero-output",
        )

    rejected = _write_checkpoint(
        tmp_path,
        statutes=[_statute(text="Placeholder text")],
    )
    with pytest.raises(
        cli.CheckpointRematerializationError, match="no structurally valid"
    ):
        cli.rematerialize_checkpoint(
            checkpoint_path=rejected,
            jurisdiction="DE",
            output_root=tmp_path / "rejected-output",
        )
    assert not (tmp_path / "rejected-output").exists()


def test_idempotent_but_refuses_to_overwrite_different_output(tmp_path: Path) -> None:
    checkpoint = _write_checkpoint(tmp_path)
    output_root = tmp_path / "materialized"
    first = cli.rematerialize_checkpoint(
        checkpoint_path=checkpoint,
        jurisdiction="DE",
        output_root=output_root,
    )
    second = cli.rematerialize_checkpoint(
        checkpoint_path=checkpoint,
        jurisdiction="DE",
        output_root=output_root,
    )
    assert second["output_sha256"] == first["output_sha256"]
    assert second["receipt_sha256"] == first["receipt_sha256"]

    output = Path(first["output_path"])
    output.write_text("different\n", encoding="utf-8")
    with pytest.raises(
        cli.CheckpointRematerializationError, match="refusing to overwrite"
    ):
        cli.rematerialize_checkpoint(
            checkpoint_path=checkpoint,
            jurisdiction="DE",
            output_root=output_root,
        )
    assert output.read_text(encoding="utf-8") == "different\n"


def test_malformed_json_and_wrong_filename_fail_closed(tmp_path: Path) -> None:
    malformed = tmp_path / "STATE-DE-partial.json"
    malformed.write_text('{"stage_label":', encoding="utf-8")
    with pytest.raises(cli.CheckpointRematerializationError, match="strict JSON"):
        cli.rematerialize_checkpoint(
            checkpoint_path=malformed,
            jurisdiction="DE",
            output_root=tmp_path / "malformed-output",
        )

    valid = _write_checkpoint(tmp_path)
    renamed = tmp_path / "checkpoint.json"
    valid.rename(renamed)
    with pytest.raises(cli.CheckpointRematerializationError, match="filename mismatch"):
        cli.rematerialize_checkpoint(
            checkpoint_path=renamed,
            jurisdiction="DE",
            output_root=tmp_path / "wrong-name-output",
        )


def test_checkpoint_symlink_is_rejected(tmp_path: Path) -> None:
    real_root = tmp_path / "real"
    real_root.mkdir()
    real = _write_checkpoint(real_root)
    linked_root = tmp_path / "linked"
    linked_root.mkdir()
    link = linked_root / "STATE-DE-partial.json"
    link.symlink_to(real)

    with pytest.raises(cli.CheckpointRematerializationError, match="must not be a symlink"):
        cli.rematerialize_checkpoint(
            checkpoint_path=link,
            jurisdiction="DE",
            output_root=tmp_path / "symlink-output",
        )


def test_cli_is_single_state_and_local_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    checkpoint = _write_checkpoint(tmp_path)
    assert (
        cli.main(
            [
                "--checkpoint",
                str(checkpoint),
                "--state",
                "DE",
                "--output-root",
                str(tmp_path / "materialized"),
                "--json",
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["jurisdiction"] == "DE"
    assert report["network_access"] is False
    assert report["authorizing_for_publication"] is False
    assert report["authorizing_hub_upload"] is False
