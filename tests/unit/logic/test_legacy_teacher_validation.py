"""The teacher benchmark must preserve source excerpts and separate evidence."""
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def runner():
    path = Path(__file__).resolve().parents[3] / "scripts/ops/legal_ir/validate_legacy_linguistic_teacher.py"
    spec = importlib.util.spec_from_file_location("legacy_teacher_validation_tests", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_real_sentence_sampling_keeps_exact_offsets_and_excludes_history(runner):
    text = ("Section heading.  The agency shall retain records for at least 20 days. "
            "Editorial Notes The agency shall disclose records in the historical version.")
    rows = list(runner._sentence_candidates(text))
    assert len(rows) == 1
    start, end, sentence = rows[0]
    assert sentence == text[start:end] == "The agency shall retain records for at least 20 days."
    assert start > 0


def test_sampling_skips_long_and_unterminated_spans_without_truncating(runner):
    assert list(runner._sentence_candidates("The agency shall retain " + "records " * 80 + ".")) == []
    assert list(runner._sentence_candidates("The agency shall retain records until a future date")) == []
    assert list(runner._sentence_candidates("This chapter may be cited as the Public Records Act.")) == []


def test_local_parquet_sampling_is_repeatable_and_records_source_hash(runner, tmp_path):
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    path = tmp_path / "laws.parquet"
    row = dict(title_number="5", section_number="10", source_url="https://example.invalid/5/10",
               text="Heading. The agency shall retain records for at least 20 days.")
    pq.write_table(pa.Table.from_pylist([row]), path)
    first, metadata = runner._real_cases(path, 1)
    assert runner._real_cases(path, 1) == (first, metadata)
    assert first[0]["text"] == row["text"][first[0]["section_start_char"]:first[0]["section_end_char"]]
    assert first[0]["independently_reviewed_gold"] is False
    assert metadata["sha256"] == runner._sha(path)
    assert metadata["downloaded"] is False


def test_reference_comparison_never_qualifies_equal_or_different_ir(runner):
    reference = {"rules": [{"modality": "F", "actor": "the_agency", "action": "disclose", "object": "records"}]}
    same = runner._reference_comparison(reference, reference)
    assert same["surface_normalized_exact"] is True
    assert same["complete_semantic_equivalence_check"] is False
    assert same["reference_independently_reviewed_this_run"] is False
    assert runner._reference_comparison(reference, {"rules": []})["surface_normalized_exact"] is False
    assert runner.FALSE_AUTHORITY["admitted"] is False
    assert runner.FALSE_AUTHORITY["roundtrip_ok"] is False


def test_existing_panel_and_reference_fixtures_are_loaded_without_duplicate_text(runner):
    panel = runner.REPO / "tests/fixtures/logic/legacy_teacher_panel.json"
    cases = runner._fixture_cases(panel)
    assert len(cases) >= 45
    assert len({" ".join(row["text"].split()) for row in cases}) == len(cases)
    assert any("constitution" in row["id"] for row in cases)
    assert any(row.get("reference_gold_ir") for row in cases)
    assert any("uscode" in row["source_kind"] for row in cases)


def test_large_ir_retained_once_and_summary_binds_full_artifact(runner, tmp_path):
    ir = {"formulas": [{"operator": {"family": "deontic", "symbol": "O"}}]}
    result = dict(long_span_ir_rows=[dict(case_id="x", historical_modal_ir=ir, exact=True,
                                         historical_modal_ir_sha256=runner._payload_sha(ir),
                                         preserved_modal_ir_sha256=runner._payload_sha(ir))],
                  admitted=False)
    path = tmp_path / "full.json"
    runner._write(path, result)
    original_bytes = path.read_bytes()
    summary = runner._compact_daemon_summary(result, path)
    assert "historical_modal_ir" not in summary["long_span_ir_rows"][0]
    assert summary["long_span_ir_rows"][0]["exact"] is True
    assert summary["full_evidence_artifact"]["sha256"] == runner._sha(path)
    assert path.read_bytes() == original_bytes
    assert result["long_span_ir_rows"][0]["historical_modal_ir"] == ir
