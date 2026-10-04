"""Source replay and non-lossy extraction for richer weak IntentIR labels."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.intent_ir.formalize import rich_span_targets as sut
from ipfs_datasets_py.logic.intent_ir.formalize import skillcenter_spans
from ipfs_datasets_py.logic.intent_ir.formalize.skillcenter_training import export_skillcenter_training_corpus
from tests.unit.logic.intent_ir.test_skillcenter_training import _fixture


def _source(text, identifier="parent", split="train"):
    return {"instruction": text, "source_id": identifier, "split": split, "domain": "devtools",
            "source_sha256": hashlib.sha256(text.encode()).hexdigest()}


def _extract(text):
    parent = _source(text)
    return [sut.extract_rich_span_target(span, parent) for span in skillcenter_spans._source_spans(parent)]


def _descriptor(tmp_path, documents):
    args = _fixture(tmp_path / "release", records=[(name, "MIT", "allow", text) for name, text in documents])
    sources = export_skillcenter_training_corpus(**args, output=tmp_path / "sources", max_examples=len(documents))
    return skillcenter_spans.export_skillcenter_span_corpus(sources, output=tmp_path / "spans"), args


@pytest.mark.parametrize("text,verb", [
    ("Do not generate long background analysis.", "generate"),
    ("Do not reuse the full system report template.", "reuse"),
    ("Confirm correct selector scope.", "confirm"),
    ("Review content-agnostic design principles.", "review"),
    ("Use a narrow answer format for skill-specific questions.", "use"),
])
def test_train_audited_verbs_preserve_complete_objects_and_missing_actor(text, verb):
    candidates = [row for row, _ in _extract(text) if row]
    assert len(candidates) == 1
    target = candidates[0]["target"]
    assert target["kind"] == "action" and target["condition"] is None
    assert target["actions"][0]["action"] == verb
    assert target["actions"][0]["actor"] == "unspecified"
    assert target["actions"][0]["modality"] == ("prohibited" if text.startswith("Do not") else "intended")
    assert candidates[0]["instruction"] == text


@pytest.mark.parametrize("text,kind", [
    ("If checks fail, report problem.", "conditional"),
    ("If tests pass, delete cache.", "conditional"),
    ("First read report then update cache.", "sequence"),
    ("Read report, then update cache.", "sequence"),
    ("- If checks fail, report problem.\n", "conditional"),
])
def test_complete_explicit_structured_clauses_are_candidates_with_original_scope(text, kind):
    candidates = [row for row, _ in _extract(text) if row]
    assert len(candidates) == 1
    target = candidates[0]["target"]
    assert target["kind"] == kind
    if kind == "conditional":
        assert target["condition"] in {"checks fail", "tests pass"}
        assert len(target["actions"]) == 1
    else:
        assert target["condition"] is None
        assert [row["action"] for row in target["actions"]] == ["read", "update"]


@pytest.mark.parametrize("text", [
    "If checks fail, report problem. Delete cache.",
    "# When checks fail\nRead report then update cache.",
    "Before publishing:\n\nRead report then update cache.",
    "- When checks fail:\n  - Read report then update cache.",
    "If checks fail, report problem and suggest fix.",
    "Must read report then update cache.",
    "The agent must read report then update cache.",
    "Read report then update cache then delete fixture.",
    "# Examples\nIf checks fail, report problem.",
    "# Never do\nDelete cache.",
    "If checks do not fail, delete cache.",
    "If tests passe, delete cache.",
    "Read report without approval.",
    "Report only errors.",
    "Search results come from public search engines.",
    "May be blocked by anti-scraping measures.",
])
def test_ambiguous_or_external_scope_does_not_become_a_target(text):
    assert not [row for row, _ in _extract(text) if row]


def test_nested_heading_force_applies_to_complete_sequence_and_keeps_source_selectors():
    text = "# MUST NOT DO\n## Maintenance\nRead report then update cache.\n"
    rows = [row for row, _ in _extract(text) if row]
    assert len(rows) == 1
    row = rows[0]
    assert [action["modality"] for action in row["target"]["actions"]] == ["prohibited", "prohibited"]
    assert row["instruction"].startswith("must not do: ")
    assert row["provenance"]["source_fragments"] == ["# MUST NOT DO\n", "## Maintenance\n", "Read report then update cache."]
    for selector, fragment in zip(row["provenance"]["spans"], row["provenance"]["source_fragments"]):
        assert text[selector["start_char"]:selector["end_char"]] == fragment
        assert text.encode()[selector["start_byte"]:selector["end_byte"]].decode() == fragment


def test_conflicting_heading_and_explicit_modalities_are_rejected():
    assert not [row for row, _ in _extract("# MUST NOT DO\nThe agent may delete cache.") if row]
    assert not [row for row, _ in _extract("# Required\n## Prohibited\nDelete cache.") if row]


def test_untranslated_heading_cannot_lose_prohibition_but_emoji_is_not_a_language():
    rows = _extract("# 禁止\nDelete cache.\n")
    assert not [row for row, _ in rows if row]
    assert "unsupported_heading_language" in [reason for _, reason in rows]
    rows = [row for row, _ in _extract("# Maintenance 🛠️\nDelete cache.\n") if row]
    assert len(rows) == 1 and rows[0]["target"]["actions"][0]["modality"] == "intended"


def test_real_bridge_keeps_conditions_and_case_out_of_single_frame_training(tmp_path):
    descriptor, _ = _descriptor(tmp_path, [
        ("single", "Generate background analysis.\n"),
        ("case", "Verify CSS custom property fallbacks.\n"),
        ("condition", "If checks fail, report problem.\n"),
        ("sequence", "Read report then update cache.\n"),
    ])
    report = sut.build_skillcenter_rich_span_targets(descriptor)
    assert report["counts"]["by_kind"] == {"action": 2, "conditional": 1, "sequence": 1}
    assert report["counts"]["training_supported"] == 1
    for row in report["targets"]:
        supported = row["qualification"]["training_supported"]
        assert supported == (row["instruction"] == "Generate background analysis.")
        assert row["qualification"]["family_statuses"]
        assert all(family["family_id"] for family in row["qualification"]["family_statuses"])
        assert row["native_intent_ir"]["sources"][0]["content_sha256"] == hashlib.sha256(row["instruction"].encode()).hexdigest()
        if row["target"]["kind"] == "conditional":
            assert row["native_intent_ir"]["actions"][0]["precondition_ids"] == []
            assert row["native_intent_ir"]["statements"][0]["predicate"] == ""
        if "CSS" in row["instruction"]:
            assert row["target"]["actions"][0]["object"] == "CSS custom property fallbacks"
            assert row["native_intent_ir"]["actions"][0]["object_refs"] == ["CSS custom property fallbacks"]
    assert len(report["targets"]) + len(report["omitted"]) + len(report["quarantined"]) == report["counts"]["source_spans"]
    assert report["semantic_correctness_verified"] is report["proof_authority"] is report["training_executed"] is False
    sut.validate_skillcenter_rich_span_targets(report)


def test_native_slot_bounds_are_explicit_gaps_without_aborting_other_targets(tmp_path):
    descriptor, _ = _descriptor(tmp_path, [
        ("bounds", "Generate background analysis.\n\nUse protocol 3.\n"),
    ])
    report = sut.build_skillcenter_rich_span_targets(descriptor)
    assert [row["instruction"] for row in report["targets"]] == ["Generate background analysis."]
    assert report["counts"]["omission_reasons"]["outside_native_structured_target_bounds"] == 1
    assert len(report["targets"]) + len(report["omitted"]) == report["counts"]["source_spans"]
    sut.validate_skillcenter_rich_span_targets(report)


def test_qualification_semantic_errors_are_not_swallowed_as_source_omissions(tmp_path, monkeypatch):
    from ipfs_datasets_py.logic.intent_ir.formalize import structured_target_bridge
    descriptor, _ = _descriptor(tmp_path, [("semantic", "If checks fail, report problem.\n")])

    def regression(*args, **kwargs):
        raise ValueError("conditional projection leaked unconditional authority")

    monkeypatch.setattr(structured_target_bridge, "qualify_structured_target", regression)
    with pytest.raises(ValueError, match="leaked unconditional authority"):
        sut.build_skillcenter_rich_span_targets(descriptor)


@pytest.mark.parametrize("field", ["split", "target", "selector", "pin", "authority"])
def test_replay_rejects_rehashed_forged_labels_source_selectors_and_authority(tmp_path, field):
    descriptor, _ = _descriptor(tmp_path, [("source", "Generate background analysis.\n")])
    report = sut.build_skillcenter_rich_span_targets(descriptor)
    forged = deepcopy(report)
    row = forged["targets"][0]
    if field == "split":
        row["split"] = "test" if row["split"] != "test" else "train"
    elif field == "target":
        row["target"]["actions"][0]["modality"] = "prohibited"
    elif field == "selector":
        row["provenance"]["spans"][-1]["start_byte"] += 1
    elif field == "pin":
        forged["producer_sha256"][next(iter(forged["producer_sha256"]))] = "0" * 64
    else:
        row["qualification"]["training_supported"] = False
        forged["proof_authority"] = True
    forged.pop("report_sha256")
    forged["report_sha256"] = hashlib.sha256(sut._wire(forged)).hexdigest()
    with pytest.raises(ValueError, match="source replay"):
        sut.validate_skillcenter_rich_span_targets(forged)


def test_export_load_cli_and_source_tamper(tmp_path, capsys):
    descriptor, args = _descriptor(tmp_path, [("source", "Generate background analysis.\n")])
    source_path = tmp_path / "span-descriptor.json"
    source_path.write_text(json.dumps(descriptor))
    path = Path(__file__).resolve().parents[4] / "scripts/training/build_intent_rich_span_targets.py"
    spec = importlib.util.spec_from_file_location("rich_span_cli", path)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    output = tmp_path / "rich"
    assert cli.main(["--span-corpus-descriptor", str(source_path), "--output", str(output)]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["published"] is False and summary["counts"]["targets"] == 1
    exported = json.loads((output / "descriptor.json").read_bytes())
    assert exported == summary["rich_targets"]
    assert Path(exported["path"]).name == "targets.json"
    assert sut.load_skillcenter_rich_span_targets(exported)["counts"]["targets"] == 1
    before = (output / "targets.json").read_bytes()
    with pytest.raises(ValueError, match="fresh"):
        cli.main(["--span-corpus-descriptor", str(tmp_path / "missing"), "--output", str(output)])
    assert (output / "targets.json").read_bytes() == before
    shard = args["release_root"] / args["shards"][0]
    shard.write_bytes(shard.read_bytes() + b"changed")
    with pytest.raises(ValueError):
        sut.load_skillcenter_rich_span_targets(exported)
