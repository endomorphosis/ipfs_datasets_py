"""Independent source replay and real shared-training checks for Intent spans."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.intent_ir.formalize import span_training as sut
from ipfs_datasets_py.logic.intent_ir.formalize.roundtrip import intent_ir_to_frame
from ipfs_datasets_py.logic.intent_ir.formalize.skillcenter_training import (
    export_skillcenter_training_corpus, load_skillcenter_training_corpus,
)
from tests.unit.logic.intent_ir.test_skillcenter_training import _fixture


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _source(tmp_path, documents):
    args = _fixture(tmp_path / "release", records=[
        (name, "MIT", "allow", text) for name, text in documents])
    descriptor = export_skillcenter_training_corpus(**args, output=tmp_path / "sources", max_examples=len(documents))
    return descriptor, load_skillcenter_training_corpus(descriptor), args


def _corpus(tmp_path, documents):
    from ipfs_datasets_py.logic.intent_ir.formalize.skillcenter_spans import export_skillcenter_span_corpus
    descriptor, sources, args = _source(tmp_path, documents)
    spans = export_skillcenter_span_corpus(source_descriptor=descriptor, output=tmp_path / "spans")
    return sut.build_skillcenter_span_pairs(spans), sources, args


def _cli(filename):
    path = Path(__file__).resolve().parents[4] / "scripts/training" / filename
    spec = importlib.util.spec_from_file_location("span_cli_" + filename.replace(".", "_"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_multisentence_and_wrapped_clauses_have_exact_parent_provenance(tmp_path):
    text = "# Instructions\nRead report. Update\ncache.\n"
    report, sources, _ = _corpus(tmp_path, [("wrapped", text)])
    assert {row["instruction"] for row in report["samples"]} == {"read report.", "update cache."}
    parent = sources["samples"][0]
    for pair in report["samples"]:
        provenance = pair["provenance"]
        assert pair["split"] == parent["split"]
        assert provenance["source_id"] == parent["id"]
        assert provenance["source_identity"] == parent["source_identity"]
        assert provenance["source_sha256"] == _sha(text.encode())
        assert provenance["source_sha256"] != _sha(pair["instruction"].encode())
        assert provenance["adapter_input_sha256"] == _sha(provenance["adapter_input"].encode())
        assert provenance["source_fragments"] == [text[s["start_char"]:s["end_char"]]
                                                   for s in provenance["spans"]]
        for selector, fragment in zip(provenance["spans"], provenance["source_fragments"]):
            assert text.encode()[selector["start_byte"]:selector["end_byte"]].decode() == fragment
        assert intent_ir_to_frame(pair["native_intent_ir"]) == pair["frame"]
        native_source = pair["native_intent_ir"]["sources"][0]
        assert native_source["content_sha256"] == _sha(pair["instruction"].encode())
        assert provenance["human_reviewed"] is provenance["gold_source_semantics"] is False
        assert pair["native_projection_summary"]
    assert report["gold_formal_target_count"] == report["human_reviewed_pair_count"] == 0
    assert report["semantic_correctness_verified"] is report["qualified"] is report["admitted"] is False
    assert report["provider_calls"] == 0 and report["source_content_executed"] is False
    sut.validate_skillcenter_span_pairs(report)


def test_heading_prohibition_survives_sentence_expansion_and_descendant_heading(tmp_path):
    report, _, _ = _corpus(tmp_path, [("prohibition",
        "# MUST NOT DO\n## Maintenance\nDelete cache. Remove report.\n")])
    assert len(report["samples"]) == 2
    for pair in report["samples"]:
        assert pair["frame"]["modality"] == "prohibited"
        assert pair["instruction"].startswith("must not do: ")
        assert pair["canonical_text"].startswith("unspecified must not ")
        assert [h["text"].strip() for h in pair["provenance"]["heading_context"]] == [
            "# MUST NOT DO", "## Maintenance"]


def test_setext_heading_keeps_prohibition_and_original_source_selector(tmp_path):
    text = "MUST NOT DO\n-----------\nDelete cache.\n"
    report, _, _ = _corpus(tmp_path, [("setext", text)])
    assert len(report["samples"]) == 1
    pair = report["samples"][0]
    assert pair["frame"]["modality"] == "prohibited"
    assert pair["instruction"] == "must not do: delete cache."
    assert pair["provenance"]["source_fragments"][0] == "MUST NOT DO\n-----------\n"
    assert pair["provenance"]["adapter_input"].startswith("## MUST NOT DO\n")


@pytest.mark.parametrize("prefix", [
    "# If tests pass\n", "If tests pass:\n", "# Examples\n",
    "If tests pass:\n\n", "If tests pass:\n\n```text\nstatus output\n```\n\n",
])
def test_conditional_and_example_context_cannot_become_unconditional_training(tmp_path, prefix):
    report, _, _ = _corpus(tmp_path, [("context", prefix + "Delete cache.\n")])
    assert report["samples"] == []
    assert report["omitted"]


def test_conflicting_explicit_and_inherited_modalities_are_omitted(tmp_path):
    report, _, _ = _corpus(tmp_path, [("conflict", "# MUST NOT DO\nThe agent may delete cache.\n")])
    assert report["samples"] == []
    assert any("conflicting_explicit_modalities" in row.get("adapter_reasons", [])
               for row in report["omitted"])


def test_long_object_and_token_dense_object_do_not_abort_other_spans(tmp_path):
    # The hyphenated object is under the 160-character/12-word frame limits,
    # but its serialized IR exceeds the frozen decoder's generation budget.
    text = "Read report.\n\nRead " + "x" * 161 + ".\n\nRead " + "-".join(["x"] * 65) + ".\n"
    report, _, _ = _corpus(tmp_path, [("bounds", text)])
    assert [row["instruction"] for row in report["samples"]] == ["read report."]
    assert report["counts"]["omission_reasons"]["outside_bounded_clause_target"] == 1
    assert report["counts"]["omission_reasons"]["outside_shared_codec_target_bounds"] == 1


@pytest.mark.parametrize("field", ["split", "frame", "source_sha256", "span", "gold", "pin"])
def test_exact_replay_rejects_changed_labels_offsets_and_authority_even_after_rehash(tmp_path, field):
    report, _, _ = _corpus(tmp_path, [("replay", "Read report.\n")])
    forged = deepcopy(report)
    pair = forged["samples"][0]
    if field == "split":
        pair["split"] = "test" if pair["split"] != "test" else "train"
    elif field == "frame":
        pair["frame"]["modality"] = "prohibited"
    elif field == "source_sha256":
        pair["provenance"]["source_sha256"] = "0" * 64
    elif field == "span":
        pair["provenance"]["spans"][-1]["start_byte"] += 1
    elif field == "gold":
        forged["gold_formal_target_count"] = 1
    else:
        forged["producer_sha256"][next(iter(forged["producer_sha256"]))] = "0" * 64
    forged.pop("report_sha256")
    forged["report_sha256"] = _sha(sut._wire(forged))
    with pytest.raises(ValueError, match="source replay"):
        sut.validate_skillcenter_span_pairs(forged)


def test_source_shard_tamper_invalidates_pair_replay(tmp_path):
    report, _, args = _corpus(tmp_path, [("source", "Read report.\n")])
    shard = args["release_root"] / args["shards"][0]
    shard.write_bytes(shard.read_bytes() + b"tampered")
    with pytest.raises(ValueError):
        sut.validate_skillcenter_span_pairs(report)


def test_shared_sentences_are_excluded_without_reassigning_parent_splits(tmp_path):
    documents = [(f"collision{index}", f"Read sharedreport.\n\nInspect object{index}.\n")
                 for index in range(36)]
    report, sources, _ = _corpus(tmp_path, documents)
    assignments = {row["id"]: row["split"] for row in sources["samples"]}
    assert len(set(assignments.values())) > 1
    assert not any(row["instruction"] == "read sharedreport." for row in report["samples"])
    assert report["samples"]
    assert all(row["split"] == assignments[row["provenance"]["source_id"]] for row in report["samples"])
    assert report["quarantined"] or any(row["reason"] == "cross_partition_duplicate"
                                        for row in report["omitted"])


def test_authored_controls_are_explicitly_opt_in_and_reported_separately(tmp_path):
    report, _, _ = _corpus(tmp_path, [("optional", "Inspect localcatalog.\n")])
    assert report["include_authored"] is False
    assert report["counts"]["by_source"]["authored_development_control"] == {}
    mixed = sut.build_skillcenter_span_pairs(report["span_corpus_descriptor"], include_authored=True)
    assert mixed["include_authored"] is True
    assert sum(mixed["counts"]["by_source"]["authored_development_control"].values()) == 720
    assert mixed["counts"]["pairs"] == 721
    sut.validate_skillcenter_span_pairs(mixed)


def test_cli_exports_then_trains_real_shared_weights_from_pinned_spans(tmp_path, monkeypatch, capsys):
    import torch
    from ipfs_datasets_py.logic.intent_ir.formalize.roundtrip import load_intent_roundtrip_checkpoint
    torch.set_num_threads(1)
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "")
    source_descriptor, sources, _ = _source(tmp_path, [
        (f"smoke{index}", f"Inspect object{index}.\n") for index in range(36)])
    assert {row["split"] for row in sources["samples"]} >= {"train", "validation"}
    source_path = tmp_path / "source-descriptor.json"
    source_path.write_text(json.dumps(source_descriptor))
    span_root = tmp_path / "span-export"
    build_cli = _cli("build_intent_span_corpus.py")
    assert build_cli.main(["--source-corpus-descriptor", str(source_path), "--output", str(span_root)]) == 0
    build_summary = json.loads(capsys.readouterr().out)
    assert build_summary["pair_counts"]["pairs"] == 36
    inventory_descriptor = span_root / "descriptor.json"
    before = inventory_descriptor.read_bytes()
    lexical = tmp_path / "lexical.json"
    lexical.write_text(json.dumps({"keys": ["token:inspect", "token:object0", "token:unspecified"],
        "weights": [[0.1, 0.2], [0.2, 0.3], [0.3, 0.4]], "embedding_width": 2,
        "source_checkpoint_sha256": "a" * 64}))
    lexical_before = lexical.read_bytes()
    output = tmp_path / "trained"
    assert _cli("train_intent_roundtrip.py").main([
        "--span-corpus-descriptor", str(inventory_descriptor), "--lexical-initializer", str(lexical),
        "--output", str(output), "--epochs", "1", "--max-seconds", "20",
        "--hidden-size", "8", "--embedding-dim", "8"]) == 0
    summary = json.loads(capsys.readouterr().out)
    loaded = load_intent_roundtrip_checkpoint(summary["checkpoint"])
    training = loaded["backend"]["training"]
    assert training["optimizer_steps"] > 0 and training["native_kernel_calls"] > 0
    assert training["initial_state_sha256"] != training["final_state_sha256"]
    assert training["lexical_lineage"]["parent_modified"] is False
    assert training["lexical_lineage"]["frozen"] is True
    assert training["lexical_lineage"]["matched_tokens"] > 0
    receipt = json.loads((output / "training-receipt.json").read_bytes())
    corpus = json.loads((output / "corpus.json").read_bytes())
    assert receipt["supervision"] == corpus["supervision"]
    assert corpus["include_authored"] is False
    assert {row["provenance"]["kind"] for row in corpus["samples"]} == {"skillcenter_weak_span"}
    assert receipt["test_used_for_training_or_tuning"] is False
    assert inventory_descriptor.read_bytes() == before and lexical.read_bytes() == lexical_before
    for split in ("train", "validation", "test"):
        evaluation = json.loads((output / f"evaluation-{split}.json").read_bytes())
        assert evaluation["teacher_forcing"] is evaluation["inference_target_access"] is False
        assert evaluation["metrics"]["count"] == sum(row["split"] == split for row in corpus["samples"])
    assert summary["published"] is False


def test_build_cli_refuses_existing_destination_before_mutation(tmp_path):
    destination = tmp_path / "existing"
    destination.mkdir()
    sentinel = destination / "weights.json"
    sentinel.write_bytes(b"preserve legal weights")
    with pytest.raises(ValueError, match="fresh"):
        _cli("build_intent_span_corpus.py").main([
            "--source-corpus-descriptor", str(tmp_path / "absent.json"), "--output", str(destination)])
    assert sentinel.read_bytes() == b"preserve legal weights"
