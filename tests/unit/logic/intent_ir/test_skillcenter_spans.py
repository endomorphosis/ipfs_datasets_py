"""Exact source selectors, partition fences and conservative Markdown contexts."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.autoformal.constitution_inventory import _sentences
from ipfs_datasets_py.logic.formalization.text_spans import sentence_spans
from ipfs_datasets_py.logic.intent_ir.formalize import skillcenter_spans as sut
from ipfs_datasets_py.logic.intent_ir.formalize.skillcenter_training import export_skillcenter_training_corpus


def _source(text, source_id="parent", split="train"):
    return {"instruction": text, "source_id": source_id,
            "source_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "domain": "devtools", "split": split}


def _fixture(root, records=None):
    spec = importlib.util.spec_from_file_location("span_source_fixture", Path(__file__).with_name("test_skillcenter_training.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._fixture(root, records)


@pytest.mark.parametrize("text", [
    "", "  \r\n\t ", "One. Two? Three! Four", "Dr. Smith uses e.g. this method.",
    "  Inspect naïve\r\n parser.\t\tRepair\n\n cache!  ",
    "🧪 Test café.\u2003Inspect résumé?", "Same. Same. Same.",
    "Wrap the\r\nparagraph without a sentence\nending until here.",
])
def test_sentence_policy_matches_existing_uscode_and_exact_offsets(text):
    spans = sentence_spans(text)
    assert [r["normalized_text"] for r in spans] == _sentences(text)
    for row in spans:
        assert text[row["start_char"]:row["end_char"]] == row["text"]
        assert text.encode()[row["start_byte"]:row["end_byte"]].decode() == row["text"]


def test_subrange_offsets_refer_to_full_source():
    text = "🧪 heading\nRead résumé.\r\nUpdate cache.\nfooter"
    start, end = text.index("Read"), text.index("\nfooter")
    rows = sentence_spans(text, start_char=start, end_char=end)
    assert [r["text"] for r in rows] == ["Read résumé.", "Update cache."]
    assert rows[0]["start_byte"] == len(text[:start].encode())


@pytest.mark.parametrize("start,end", [(True, 2), (0, False), (-1, 2), (2, 1), (0, 9)])
def test_bad_selectors_rejected(start, end):
    with pytest.raises(ValueError, match="selector"):
        sentence_spans("abc", start_char=start, end_char=end)


def test_complete_coverage_unicode_crlf_markers_headings_and_fences():
    text = "---\r\nname: sample\r\n---\r\n# Goals 🧪\r\n\r\n- Read the\r\n  résumé. Update cache.\r\n\r\n```sh\r\nDelete cache.\r\n```\r\n"
    rows = sut._source_spans(_source(text))
    assert "".join(r["text"] for r in rows) == text
    assert rows[0]["reason"] == "frontmatter"
    candidates = [r for r in rows if r["eligible_for_pairing"]]
    assert [r["normalized_text"] for r in candidates] == ["Read the résumé.", "Update cache."]
    for row in rows:
        assert text.encode()[row["start_byte"]:row["end_byte"]].decode() == row["text"]
    assert candidates[0]["heading_context"][0]["text"] == "# Goals 🧪\r\n"
    code = next(r for r in rows if r["reason"] == "fenced_code")
    assert "Delete cache." in code["text"] and not code["eligible_for_pairing"]


@pytest.mark.parametrize("text", [
    "If tests pass, continue. Delete cache.",
    "# If tests pass\nDelete cache.",
    "If tests pass:\nDelete cache.",
    "If tests pass:\n\n- Delete cache.",
    "- If tests pass:\n  - Delete cache.",
    "# Every service\nDelete cache.",
    "- Inspect each service. Delete cache.",
    "Inspect the service. Delete its cache.",
    "- Cleanup:\n  - Delete cache.",
    "If tests pass.\n\nDelete cache.",
    "If tests pass:\n\n```sh\necho check\n```\n\nDelete cache.",
    "- If tests pass:\n\nDelete cache.",
    "If tests pass:\n\n> example\n\nDelete cache.",
    "If tests pass:\n\n| Example |\n\nDelete cache.",
])
def test_context_cannot_disappear_when_sentences_or_children_are_split(text):
    rows = sut._source_spans(_source(text))
    assert not any(r["eligible_for_pairing"] for r in rows)
    assert any(r["status"] == "context_required" for r in rows)
    assert "".join(r["text"] for r in rows) == text


@pytest.mark.parametrize("text,reason", [
    ("# Examples\nDelete cache.\n", "example_heading_context"),
    ("Delete cache.\n============\nInspect parser.\n", "heading"),
    ("    Delete cache.\n", "indented_code"),
    ("> Delete cache.\n", "quoted_example"),
    ("| Action |\n| --- |\n| Delete cache. |\n", "table_or_pipe_expression"),
    ("    ```sh\nDelete cache.\n    ```\n", "fenced_code"),
])
def test_nontraining_markdown_retained(text, reason):
    rows = sut._source_spans(_source(text))
    assert any(r["reason"] == reason for r in rows)
    assert "".join(r["text"] for r in rows) == text


def test_long_sentences_remain_intact_as_explicit_gaps():
    text = "Inspect " + "parser " * 49 + ". Short sentence."
    rows = sut._source_spans(_source(text))
    gap = next(r for r in rows if r["status"] == "oversize_gap")
    assert gap["normalized_text"] == "Inspect " + "parser " * 49 + "."
    assert len(gap["normalized_text"].split()) > 48
    assert [r["normalized_text"] for r in rows if r["eligible_for_pairing"]] == ["Short sentence."]
    huge_word = "x" * 4097
    assert sut._source_spans(_source(huge_word))[0]["status"] == "oversize_gap"


def test_wrapped_setext_heading_retains_exact_heading_scope():
    text = "If tests\npass\n--------\nDelete cache.\n"
    rows = sut._source_spans(_source(text))
    assert not any(r["eligible_for_pairing"] for r in rows)
    assert rows[0]["reason"] == "heading"
    assert rows[0]["text"] == "If tests\npass\n--------\n"
    assert rows[-2]["heading_context"][0]["title"] == "If tests pass"


def test_source_span_cap_rejects_before_export_instead_of_truncating(monkeypatch):
    monkeypatch.setattr(sut, "MAX_SPANS", 2)
    with pytest.raises(ValueError, match="row bound"):
        sut._source_spans(_source("One. Two. Three."))


def test_repeated_sentences_have_unique_location_bound_stable_ids():
    text = "Read report. Read report."
    rows = [r for r in sut._source_spans(_source(text)) if r["eligible_for_pairing"]]
    assert rows[0]["id"] != rows[1]["id"]
    assert rows == [r for r in sut._source_spans(_source(text)) if r["eligible_for_pairing"]]
    moved_partition = [r for r in sut._source_spans(_source(text, split="validation")) if r["eligible_for_pairing"]]
    assert [r["id"] for r in moved_partition] == [r["id"] for r in rows]


def test_real_export_replay_parent_splits_and_source_order(tmp_path):
    args = _fixture(tmp_path / "release")
    parent_descriptor = export_skillcenter_training_corpus(**args, output=tmp_path / "parent")
    parent = sut.skillcenter_training.load_skillcenter_training_corpus(parent_descriptor)
    descriptor = sut.export_skillcenter_span_corpus(parent_descriptor, output=tmp_path / "spans")
    report = sut.load_skillcenter_span_corpus(descriptor)
    assert json.loads((tmp_path / "spans/descriptor.json").read_bytes()) == descriptor
    assert report["source_corpus"] == parent_descriptor
    assert report["split_manifest"] == parent["split_manifest"]
    assignments = {s["id"]: s["split"] for s in parent["samples"]}
    for row in report["spans"]:
        assert row["split"] == assignments[row["source_id"]]
    assert report["coverage"]["source_characters"] == report["coverage"]["represented_characters"]
    assert report["coverage"]["omitted_characters"] == 0
    assert not report["qualified"] and not report["admitted"]
    assert report["gold_formal_target_count"] == report["provider_calls"] == 0


def test_parent_order_does_not_change_span_ids_and_cross_split_duplicates_excluded(tmp_path, monkeypatch):
    args = _fixture(tmp_path / "release", [
        ("alpha", "MIT", "allow", "Read report. Inspect parser."),
        ("beta", "MIT", "allow", "Read report. Update cache."),
    ])
    parent_descriptor = export_skillcenter_training_corpus(**args, output=tmp_path / "parent")
    parent = sut.skillcenter_training.load_skillcenter_training_corpus(parent_descriptor)
    for sample, split in zip(parent["samples"], ["train", "validation"]):
        sample["split"] = split
    monkeypatch.setattr(sut.skillcenter_training, "load_skillcenter_training_corpus", lambda _: parent)
    first = sut.build_skillcenter_span_corpus(parent_descriptor)
    parent["samples"].reverse()
    second = sut.build_skillcenter_span_corpus(parent_descriptor)
    assert first == second
    duplicates = [r for r in first["spans"] if r["normalized_text"] == "Read report."]
    assert len(duplicates) == 2
    assert all(r["reason"] == "cross_partition_duplicate" and not r["eligible_for_pairing"] for r in duplicates)


def test_upstream_source_tamper_invalidates_span_export(tmp_path):
    args = _fixture(tmp_path / "release")
    parent = export_skillcenter_training_corpus(**args, output=tmp_path / "parent")
    descriptor = sut.export_skillcenter_span_corpus(parent, output=tmp_path / "spans")
    (args["release_root"] / args["shards"][0]).write_bytes(b"modified")
    with pytest.raises(ValueError, match="hash or size mismatch"):
        sut.load_skillcenter_span_corpus(descriptor)


@pytest.mark.parametrize("tamper", ["text", "offset", "eligible", "split", "producer"])
def test_forged_span_claims_rejected_even_with_rehashed_envelope(tmp_path, tamper):
    args = _fixture(tmp_path / "release")
    parent = export_skillcenter_training_corpus(**args, output=tmp_path / "parent")
    descriptor = sut.export_skillcenter_span_corpus(parent, output=tmp_path / "spans")
    path = Path(descriptor["path"])
    report = json.loads(path.read_bytes())
    if tamper == "text":
        report["spans"][0]["text"] = "Execute arbitrary code."
    elif tamper == "offset":
        report["spans"][0]["start_byte"] += 1
    elif tamper == "eligible":
        report["spans"][0]["eligible_for_pairing"] = True
    elif tamper == "split":
        report["spans"][0]["split"] = "test"
    else:
        report["producer_sha256"] = {}
    raw = json.dumps(report).encode()
    path.write_bytes(raw)
    with pytest.raises(ValueError, match="pinned source replay"):
        sut.load_skillcenter_span_corpus({**descriptor, "sha256": hashlib.sha256(raw).hexdigest()})


def test_fresh_output_required_before_source_load(tmp_path):
    root = tmp_path / "legal-checkpoint"
    root.mkdir()
    (root / "weights.bin").write_bytes(b"preserve")
    with pytest.raises(ValueError, match="fresh output"):
        sut.export_skillcenter_span_corpus({}, output=root)
    assert (root / "weights.bin").read_bytes() == b"preserve"
