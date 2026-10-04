"""Source inventories remain byte-exact without pretending to be formal labels."""
import hashlib
import json

import pytest

from ipfs_datasets_py.logic.formalization import text_spans
from ipfs_datasets_py.logic.security_ir.cvefixes import source_spans as spans


def assert_complete(text, rows):
    assert "".join(row["text"] for row in rows) == text
    char, byte = 0, 0
    raw = text.encode("utf-8")
    for row in rows:
        assert row["start_char"] == char and row["start_byte"] == byte
        assert row["end_char"] > char and row["end_byte"] > byte
        assert text[char:row["end_char"]] == row["text"]
        assert raw[byte:row["end_byte"]] == row["text"].encode("utf-8")
        assert row["span_text_sha256"] == hashlib.sha256(row["text"].encode()).hexdigest()
        assert row["raw_body_sha256"] == hashlib.sha256(raw).hexdigest()
        assert row["truncated"] is row["complete_compilation_unit"] is row["source_semantics_verified"] is False
        char, byte = row["end_char"], row["end_byte"]
    assert char == len(text) and byte == len(raw)


@pytest.mark.parametrize("field", sorted(spans.PROSE_FIELDS))
def test_prose_reuses_shared_policy_and_retains_unicode_whitespace_selectors(field):
    text = " \tCafé 漏洞 affects clients.\r\n\nPatch β now!  Retain context?\t "
    rows = spans.build_source_spans(text, field, "baf-source")
    assert_complete(text, rows)
    sentences = [row for row in rows if row["kind"] == "prose_sentence"]
    assert [{key: row[key] for key in sentence} for row, sentence in
            zip(sentences, text_spans.sentence_spans(text))] == text_spans.sentence_spans(text)
    assert len(sentences) == 3
    assert all(row["status"] == "candidate" and row["candidate_eligible"] for row in sentences)
    whitespace = [row for row in rows if row["kind"] == "whitespace"]
    assert len(whitespace) == 4
    assert all(row["status"] == "excluded_whitespace" and not row["candidate_eligible"] for row in whitespace)
    assert rows[1]["end_byte"] > rows[1]["end_char"]


@pytest.mark.parametrize("field", sorted(spans.FIELDS))
def test_empty_and_whitespace_are_lossless_but_never_candidates(field):
    assert spans.build_source_spans("", field, "source") == []
    text = " \t\r\n\n "
    rows = spans.build_source_spans(text, field, "source")
    assert_complete(text, rows)
    assert len(rows) == 1 and rows[0]["kind"] == "whitespace"
    assert rows[0]["status"] == "excluded_whitespace"
    assert rows[0]["candidate_eligible"] is False


@pytest.mark.parametrize("text,status", [
    (" ".join(["word"] * 48), "candidate"),
    (" ".join(["word"] * 49), "oversize"),
    ("x" * 4096, "candidate"),
    ("x" * 4097, "oversize"),
])
def test_candidate_bounds_retain_oversize_prose_without_cutting_it(text, status):
    rows = spans.build_source_spans(text, "commit_message", "source")
    assert_complete(text, rows)
    assert len(rows) == 1 and rows[0]["status"] == status
    assert rows[0]["exceeds_candidate_limit"] == (status == "oversize")
    assert rows[0]["candidate_eligible"] == (status == "candidate")


@pytest.mark.parametrize("field", sorted(spans.CODE_FIELDS))
def test_code_body_stays_whole_even_with_sentence_punctuation_or_oversize(field):
    text = '\n# Café. Preserve this comment!\nvalue = "first. second?"\n' + "x" * 4200
    rows = spans.build_source_spans(text, field, "source")
    assert_complete(text, rows)
    assert len(rows) == 1
    row = rows[0]
    assert row["kind"] == "code_context" and row["status"] == "context_required"
    assert row["requires_file_context"] is row["exceeds_candidate_limit"] is True
    assert row["candidate_eligible"] is False


def test_unified_diff_keeps_file_headers_and_unicode_hunks_separate():
    preamble = "diff --git a/café.py b/café.py\r\n--- a/café.py\r\n+++ b/café.py\r\n"
    first = "@@ -1,2 +1,2 @@ function\r\n keep\r\n-old. text\r\n+new. text\r\n"
    between = "diff --git a/β.py b/β.py\n--- a/β.py\n+++ b/β.py\n"
    second = "@@ -3,0 +4,2 @@\n+one\n+two\n\\ No newline at end of file\n"
    trailing = "final source context\n"
    text = preamble + first + between + second + trailing
    rows = spans.build_source_spans(text, "diff_with_context", "source")
    assert_complete(text, rows)
    assert [row["kind"] for row in rows] == ["diff_context", "diff_hunk", "diff_context", "diff_hunk", "diff_context"]
    assert [row["text"] for row in rows] == [preamble, first, between, second, trailing]
    assert all(row["status"] == "context_required" and row["requires_file_context"] for row in rows)
    assert not any(row["candidate_eligible"] for row in rows)


def test_diff_payload_that_looks_like_file_headers_remains_in_counted_hunk():
    text = "@@ -1 +1 @@\n--- old\n+++ new\n--- a/next\n+++ b/next\n@@ -0,0 +1 @@\n+tail"
    rows = spans.build_source_spans(text, "diff_with_context", "source")
    assert_complete(text, rows)
    assert [row["kind"] for row in rows] == ["diff_hunk", "diff_context", "diff_hunk"]
    assert rows[0]["text"] == "@@ -1 +1 @@\n--- old\n+++ new\n"
    assert rows[1]["text"] == "--- a/next\n+++ b/next\n"


@pytest.mark.parametrize("text", [
    "A sentence. More context.\ninline @@ -1 +1 @@ text\n",
    "@@@ -1,1 +1,1 @@@\ninvalid combined-diff context\n",
    "@@ not a unified range @@\n",
    "@@ -1 +1 @@broken suffix\n",
    "before\u2028@@ -1 +1 @@\n",
])
def test_only_actual_unified_hunk_header_lines_start_hunks(text):
    rows = spans.build_source_spans(text, "diff_with_context", "source")
    assert_complete(text, rows)
    assert len(rows) == 1 and rows[0]["kind"] == "diff_context"


def test_incomplete_hunk_never_claims_compilation_or_discards_context():
    text = "  \n@@ -1,5 +1,5 @@\n-short\n+partial\nraw uninterpreted context\n"
    rows = spans.build_source_spans(text, "diff_with_context", "source")
    assert_complete(text, rows)
    assert [row["kind"] for row in rows] == ["whitespace", "diff_hunk", "diff_context"]
    assert rows[1]["complete_compilation_unit"] is False


def test_ids_are_deterministic_and_bind_parent_body_field_selector_and_localized_index():
    text = "First sentence. Second sentence."
    original = spans.build_source_spans(text, "cve_description", "source-a")
    assert json.dumps(original, sort_keys=True) == json.dumps(spans.build_source_spans(text, "cve_description", "source-a"), sort_keys=True)
    assert len({row["span_id"] for row in original}) == len(original)
    variants = [
        spans.build_source_spans(text, "cve_description", "source-b"),
        spans.build_source_spans(text, "cwe_description", "source-a"),
        spans.build_source_spans(text + " Extra.", "cve_description", "source-a"),
        spans.build_source_spans(text, "cve_description", "source-a", field_index=1),
    ]
    assert all(rows[0]["span_id"] != original[0]["span_id"] for rows in variants)
    assert variants[-1][0]["field_index"] == 1
    assert variants[-1][0]["source_cid"] == "source-a"
    assert variants[-1][0]["start_char"] == 0


def test_profile_is_serializable_replay_metadata_without_ast_or_gold_claims():
    profile = spans.describe_source_span_profile()
    assert profile == json.loads(json.dumps(profile))
    assert profile["prose_policy"] == text_spans.SENTENCE_POLICY
    assert profile["span_schema"] == spans.SCHEMA
    assert profile["complete_compilation_unit_asserted"] is profile["semantic_targets_generated"] is False
    assert set(profile["producer_pins"]) == {spans.__name__, text_spans.__name__}
    assert all(len(value) == 64 for value in profile["producer_pins"].values())


@pytest.mark.parametrize("text,field,source_cid,index", [
    (None, "commit_message", "source", 0), (b"bytes", "commit_message", "source", 0),
    ("text", "other", "source", 0), ("text", None, "source", 0),
    ("text", [], "source", 0), ("text", "commit_message", None, 0),
    ("text", "commit_message", "", 0), ("text", "commit_message", " \t", 0),
    ("text", "cve_description", "source", -1), ("text", "cve_description", "source", True),
    ("text", "cve_description", "source", "1"), ("text", "fixed_code", "source", 1),
    ("text", "cwe_description", "source", 1),
])
def test_invalid_types_fields_and_localized_indexes_fail_explicitly(text, field, source_cid, index):
    with pytest.raises(ValueError):
        spans.build_source_spans(text, field, source_cid, field_index=index)
