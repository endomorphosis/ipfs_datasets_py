"""Snapshot hydrate stays local and refuses Hub authorization."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ops.legal_data.hydrate_remaining_states_from_snapshot import (
    REFUSAL,
    hydrate_state,
    main,
)


def test_hydrate_state_copies_statutes_without_authorization(tmp_path: Path) -> None:
    source = tmp_path / "snap" / "AR"
    source.mkdir(parents=True)
    (source / "statutes.jsonl").write_text(
        json.dumps({"state_code": "AR", "full_text": "body", "section_number": "1"})
        + "\n",
        encoding="utf-8",
    )
    receipt = hydrate_state(
        state_code="AR",
        source=tmp_path / "snap",
        output_root=tmp_path / "out",
    )
    dest = tmp_path / "out" / "staging-ar-snapshot-hydrate" / "statutes.jsonl"
    assert dest.is_file()
    assert receipt["authorizing_for_publication"] is False
    assert receipt["authorizing_hub_upload"] is False
    assert receipt["current_bundle"] is False
    assert receipt["statute_count"] == 1
    assert "official_source_receipt" in receipt["hub_authorization_refused"]


def test_main_refuses_authorizing_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "hydrate_remaining_states_from_snapshot.py",
            "--authorizing-for-publication",
        ],
    )
    with pytest.raises(SystemExit) as raised:
        main()
    assert "REFUSING Hub authorization" in str(raised.value)
    assert "closed_frontier" in REFUSAL
