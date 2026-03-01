from __future__ import annotations

import json
from pathlib import Path

from ipfs_datasets_py.processors.legal_data.reasoner.v2_cli import main, run_v2_cli


def test_run_v2_cli_single_sentence() -> None:
    payload = run_v2_cli(
        sentences=["Controller shall report breach within 24 hours."],
        jurisdiction="us/federal",
        enable_optimizer=True,
        enable_kg=True,
        enable_prover=True,
        prover_backend_id="mock_smt",
    )

    assert payload["summary"]["total"] == 1
    assert payload["summary"]["ok"] == 1
    assert payload["summary"]["error"] == 0
    assert payload["results"][0]["status"] == "ok"


def test_main_supports_jsonl_input_and_output(tmp_path: Path) -> None:
    input_jsonl = tmp_path / "sentences.jsonl"
    output_json = tmp_path / "out" / "v2_run.json"

    rows = [
        {"sentence": "Agency may inspect records if complaint filed."},
        {"sentence": "Vendor shall not disclose personal data."},
    ]
    input_jsonl.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")

    code = main(
        [
            "--input-jsonl",
            str(input_jsonl),
            "--output-json",
            str(output_json),
            "--pretty",
        ]
    )

    assert code == 0
    assert output_json.exists()
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["summary"]["total"] == 2
    assert payload["summary"]["ok"] == 2


def test_main_supports_committed_fixture_jsonl(tmp_path: Path) -> None:
    fixture_jsonl = Path(__file__).parent / "fixtures" / "hybrid_v2_cli_batch_sentences.jsonl"
    output_json = tmp_path / "v2_fixture_out.json"

    code = main(
        [
            "--input-jsonl",
            str(fixture_jsonl),
            "--sentence-field",
            "sentence",
            "--output-json",
            str(output_json),
        ]
    )

    assert code == 0
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["summary"]["total"] == 4
    assert payload["summary"]["ok"] == 4
