"""Source integrity and ambiguity tests; no semantic-gold assertions."""
from copy import deepcopy
import gzip
import importlib.util
import json
from pathlib import Path

import pytest

MODULE = Path(__file__).parents[3] / "scripts/ops/legal_ir/recover_legal_uscode_source_context.py"
spec = importlib.util.spec_from_file_location("recover_uscode_source", MODULE)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def observation(text="The agency shall file."):
    return {"source_span_id": "span-a", "source_text": text,
            "source_text_sha256": m.sha256(text.encode()), "legal_ids": ["usc:us:5:1"],
            "prior_diagnostic_triage": {"categories": ["operative_clause_candidate"]},
            "producer_reports": [{"repository": "justicedao/uscode-autoformal-span-cache",
                                  "revision": "abc", "path_in_repo": "reports/r.json.gz", "sha256": "r"}]}


def section(text="Title. The agency shall file. Notes.", row=15, lid="usc:us:5:1"):
    return {"text": text, "legal_id": lid, "parquet_row_index": row, "ipfs_cid": "cid-a",
            "raw_text_ref": {"path": "exact.txt", "sha256": m.sha256(text.encode())}}


def report_row(obs=None):
    o = obs or observation()
    return {"source_span_id": o["source_span_id"], "text": o["source_text"],
            "source_sha256": o["source_text_sha256"], "legal_id": "usc:us:5:1",
            "source_section_offset": 15, "entry_cid": "cid-a",
            "source_parent": {"sha256": m.SOURCE_SHA256, "revision": m.SOURCE_REVISION}}


def packet():
    o = observation()
    producer = dict(o["producer_reports"][0], source_span_id=o["source_span_id"], source_text=o["source_text"])
    producer.update(source_report_revision=producer.pop("revision"),
                    source_report_path_in_repo=producer.pop("path_in_repo"),
                    source_report_sha256=producer.pop("sha256"))
    return {"groups": [{"source_text": o["source_text"], "source_text_sha256": o["source_text_sha256"],
                        "gold_target": None, "training_qualified": False,
                        "source_observations": [{"source_span_id": o["source_span_id"],
                                                 "legal_ids": o["legal_ids"], "gold_target": None,
                                                 "training_qualified": False,
                                                 "occurrences": [{"producer_record": producer}]}]}]}


def test_exact_offsets_keep_unicode_bytes_distinct():
    result = m.exact_ranges("§ α shall.", "shall")
    assert result == [{"char_start": 4, "char_end": 9, "utf8_byte_start": 6, "utf8_byte_end": 11}]


def test_exact_offsets_keep_overlapping_occurrences():
    assert [x["char_start"] for x in m.exact_ranges("aaaa", "aa")] == [0, 1, 2]


def test_exact_offsets_do_not_normalize():
    assert not m.exact_ranges("agency  shall", "agency shall")


def test_empty_span_rejected():
    with pytest.raises(ValueError, match="empty"):
        m.exact_ranges("anything", "")


def test_unique_context_retains_unqualified_status():
    value = m.recover_observation(observation(), [section()], {})
    assert value["source_occurrence_status"] == "unique_exact_occurrence"
    assert value["selected_occurrence"]["char_start"] == 7
    assert value["producer_links"][0]["status"] == "unattested_local_report_missing"
    assert value["legal_meaning_reference"] is None
    assert value["training_qualified"] is False
    assert value["source_authority_authenticated"] is False
    assert value["original_producer_occurrence_attested"] is False


def test_repeated_text_fails_closed_despite_verified_report():
    o = observation("L.")
    value = m.recover_observation(o, [section("Pub. L. 1. Pub. L. 2.")], {"r": [report_row(o)]})
    assert value["source_occurrence_status"] == "ambiguous_exact_occurrences"
    assert value["occurrence_count"] == 2 and value["selected_occurrence"] is None
    assert value["producer_links"][0]["status"] == "producer_parent_link_verified"


def test_duplicate_legal_ids_preserve_both_physical_rows():
    value = m.recover_observation(observation(), [section(), section(row=16)], {})
    assert [x["parquet_row_index"] for x in value["exact_occurrences"]] == [15, 16]
    assert value["selected_occurrence"] is None


def test_wrong_parent_legal_id_not_matched():
    value = m.recover_observation(observation(), [section(lid="usc:us:5:2")], {})
    assert value["source_occurrence_status"] == "missing"


def test_report_section_offset_is_row_index_not_character_offset():
    value = m.recover_observation(observation(), [section()], {"r": [report_row()]})
    assert value["selected_occurrence"]["char_start"] == 7
    assert value["producer_links"][0]["parquet_row_index"] == 15
    assert value["producer_links"][0]["status"] == "producer_parent_link_verified"


@pytest.mark.parametrize("field,value", [("entry_cid", "wrong"), ("source_sha256", "wrong"),
                                         ("source_section_offset", 7), ("text", "different")])
def test_report_mismatch_blocks_selection(field, value):
    row = report_row(); row[field] = value
    result = m.recover_observation(observation(), [section()], {"r": [row]})
    assert result["source_occurrence_status"] == "producer_parent_link_mismatch"
    assert result["selected_occurrence"] is None


def test_report_parent_revision_mismatch_blocks_selection():
    row = report_row(); row["source_parent"]["revision"] = "newer"
    result = m.recover_observation(observation(), [section()], {"r": [row]})
    assert result["source_context_integrity"] == "unresolved"


def test_missing_observation_in_cached_report_is_unattested():
    result = m.recover_observation(observation(), [section()], {"r": []})
    assert result["producer_links"][0]["status"] == "unattested_observation_missing_from_report"


def test_packet_hash_mismatch_rejected():
    p = packet(); p["groups"][0]["source_text"] += " changed"
    with pytest.raises(ValueError, match="source hash"):
        m.packet_observations(p)


def test_packet_qualified_target_rejected():
    p = packet(); p["groups"][0]["source_observations"][0]["gold_target"] = {"rule": 1}
    with pytest.raises(ValueError, match="qualified observation"):
        m.packet_observations(p)


def test_packet_duplicate_observation_rejected():
    p = packet(); p["groups"].append(deepcopy(p["groups"][0]))
    with pytest.raises(ValueError, match="duplicate"):
        m.packet_observations(p)


def test_packet_inconsistent_producer_text_rejected():
    p = packet(); p["groups"][0]["source_observations"][0]["occurrences"][0]["producer_record"]["source_text"] = "bad"
    with pytest.raises(ValueError, match="producer occurrence"):
        m.packet_observations(p)


def test_cached_report_content_hash_checked(tmp_path):
    o = observation(); path = tmp_path / "snapshots/abc/reports/r.json.gz"
    path.parent.mkdir(parents=True); path.write_bytes(gzip.compress(json.dumps({"rows": []}).encode()))
    with pytest.raises(ValueError, match="hash mismatch"):
        m.load_cached_reports([o], tmp_path)
    o["producer_reports"][0]["sha256"] = m.sha256(path.read_bytes())
    reports, refs = m.load_cached_reports([o], tmp_path)
    assert len(reports) == 1 and refs[0]["locally_available"] is True


def test_report_path_traversal_rejected(tmp_path):
    o = observation(); o["producer_reports"][0]["path_in_repo"] = "../wrong"
    with pytest.raises(ValueError, match="repository path"):
        m.load_cached_reports([o], tmp_path)


def test_existing_output_directory_refused_before_reading_inputs(tmp_path):
    with pytest.raises(ValueError, match="new directory"):
        m.run(Path("missing"), Path("missing"), tmp_path, tmp_path)


def test_json_writer_cannot_overwrite(tmp_path):
    path = tmp_path / "frozen.json"
    m.write_json(path, {"old": True})
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        m.write_json(path, {"old": False})
    assert path.read_bytes() == before
