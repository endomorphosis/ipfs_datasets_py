"""Independent semantic fences for richer weak SkillCenter span targets.

All source text in these tests is authored. Public held-out text is deliberately
absent: extraction-rule development may inspect only the public training split.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.intent_ir.formalize import rich_span_targets as targets
from ipfs_datasets_py.logic.intent_ir.formalize import structured_target_bridge as bridge
from ipfs_datasets_py.logic.intent_ir.formalize.roundtrip import intent_ir_to_frame
from ipfs_datasets_py.logic.intent_ir.formalize.skillcenter_spans import (
    export_skillcenter_span_corpus,
)
from ipfs_datasets_py.logic.intent_ir.formalize.skillcenter_training import (
    export_skillcenter_training_corpus, load_skillcenter_training_corpus,
)
from tests.unit.logic.intent_ir.test_skillcenter_training import _fixture


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def _source(tmp_path, documents):
    args = _fixture(tmp_path / "release", records=[
        (name, "MIT", "allow", text) for name, text in documents])
    source = export_skillcenter_training_corpus(
        **args, output=tmp_path / "sources", max_examples=len(documents))
    spans = export_skillcenter_span_corpus(source, output=tmp_path / "spans")
    return spans, load_skillcenter_training_corpus(source), args


def _corpus(tmp_path, documents):
    spans, sources, args = _source(tmp_path, documents)
    return targets.build_skillcenter_rich_span_targets(spans), sources, args


def _frame(modality="intended", action="review", object_="report"):
    return {"actor": "unspecified", "action": action, "object": object_,
            "modality": modality}


@pytest.mark.parametrize("modality", ["intended", "required", "prohibited", "permitted", "recommended"])
def test_conditional_does_not_become_unconditional_modal_or_state_assertion(modality):
    instruction = "If tests pass, the agent must review the report."
    target = {"kind": "conditional", "actions": [_frame(modality)], "condition": "tests pass"}
    native = bridge.build_structured_target_ir(target, instruction)
    native.validate()
    assert len(native.statements) == len(native.actions) == 1
    statement = native.statements[0]
    assert statement.kind.value == "goal"
    assert statement.modality.value == "intended"
    assert statement.normalized_text == instruction
    assert statement.predicate == "" and statement.arguments == ()
    assert statement.grounding.value == "inferred" and statement.confidence == 0.0
    action = native.actions[0]
    assert not action.precondition_ids and not action.effect_ids
    assert not action.verification_ids and not native.control_edges
    assert native.sources[0].content_sha256 == _sha(instruction.encode())
    with pytest.raises(ValueError):
        intent_ir_to_frame(native)
    report = bridge.qualify_structured_target(target, instruction)
    assert report["training_supported"] is False
    assert report["candidate_ast"] == {
        "op": "implies", "antecedent": {"op": "opaque_condition", "text": "tests pass"},
        "consequent": {"op": "modal_action", "frame": _frame(modality)},
    }
    for projection in report["projections"]["projections"]:
        if projection["family_id"] in {"dcec", "tdfol"}:
            assert not projection["representation"]["payload"].get("formulas")
    assert report["code_state_bound"] is report["state_effects_inferred"] is False
    assert report["proof_authority"] is report["execution_authority"] is False
    assert "conditional_modality_relation" in _wire(report).decode()
    bridge.validate_structured_target_report(report, target, instruction)


def test_explicit_sequence_preserves_order_without_observed_effects():
    first, second = _frame(action="review"), _frame(action="update", object_="cache")
    target = {"kind": "sequence", "actions": [first, second], "condition": None}
    native = bridge.build_structured_target_ir(target, "Review report, then update cache.")
    assert [row.verb for row in native.actions] == ["review", "update"]
    assert len(native.control_edges) == 1
    edge = native.control_edges[0]
    assert edge.kind.value == "next"
    assert native.entry_action_ids == (native.actions[0].action_id,)
    assert native.terminal_action_ids == (native.actions[1].action_id,)
    assert all(not row.effect_ids and not row.precondition_ids for row in native.actions)
    with pytest.raises(ValueError):
        intent_ir_to_frame(native)
    assert bridge.qualify_structured_target(target, "Review report, then update cache.")["training_supported"] is False


def test_bridge_report_replay_binds_target_original_instruction_and_nested_projection():
    target = {"kind": "conditional", "actions": [_frame("prohibited")], "condition": "tests fail"}
    instruction = "If tests fail, do not review report."
    report = bridge.qualify_structured_target(target, instruction)
    with pytest.raises(ValueError):
        bridge.validate_structured_target_report(report, target, instruction.replace("fail", "pass"))
    forged = deepcopy(report)
    forged["candidate_ast"]["consequent"]["frame"]["modality"] = "required"
    forged.pop("report_sha256")
    forged["report_sha256"] = _sha(_wire(forged))
    with pytest.raises(ValueError):
        bridge.validate_structured_target_report(forged, target, instruction)


@pytest.mark.parametrize("mutate", [
    lambda row: row.update(extra=True),
    lambda row: row.update(kind="parallel"),
    lambda row: row.update(actions=[]),
    lambda row: row.update(actions=[_frame(), _frame()]),
    lambda row: row.update(condition="tests pass"),
    lambda row: row["actions"][0].update(effects=["cache removed"]),
    lambda row: row["actions"][0].update(modality="asserted"),
])
def test_structured_target_is_closed_and_rejects_silent_semantic_loss(mutate):
    target = {"kind": "action", "actions": [_frame()], "condition": None}
    mutate(target)
    with pytest.raises(ValueError):
        bridge.validate_structured_target(target)


@pytest.mark.parametrize("condition", ["", " ", "tests\x00pass", "tests  pass", "x" * 257,
                                       " ".join(["test"] * 33)])
def test_opaque_condition_requires_bounded_exact_normalization(condition):
    target = {"kind": "conditional", "actions": [_frame()], "condition": condition}
    with pytest.raises(ValueError):
        bridge.validate_structured_target(target)


@pytest.mark.parametrize("text", [
    "Review all reports.", "Review report unless tests fail.",
    "Review report and update cache.", "Review report or update cache.",
    "Do not never delete cache.", "Review report without validation.",
    "The agent reviews report.", "Review its report.",
])
def test_unsupported_scope_cannot_silently_become_a_simple_target(tmp_path, text):
    report, _, _ = _corpus(tmp_path, [("unsafe", text + "\n")])
    assert not report["targets"]
    assert report["omitted"]


@pytest.mark.parametrize("prefix", [
    "# If tests pass\n", "If tests pass:\n\n", "# Examples\n",
    "- If tests pass:\n  - ", "# Every service\n", "> ",
])
def test_parent_markdown_context_cannot_disappear(tmp_path, prefix):
    report, _, _ = _corpus(tmp_path, [("context", prefix + "Review report.\n")])
    assert not report["targets"]


@pytest.mark.parametrize("heading", ["禁止", "Règles", "Never", "Do not", "Allowed"])
def test_unknown_heading_language_or_modality_does_not_become_neutral(tmp_path, heading):
    report, _, _ = _corpus(tmp_path, [("heading", f"# {heading}\nDelete cache.\n")])
    assert not report["targets"]
    assert report["omitted"]


def test_fenced_code_remains_excluded_even_with_imperative_text():
    from ipfs_datasets_py.logic.intent_ir.formalize.skillcenter_spans import _source_spans
    text = "```text\nReview report.\n```\n"
    parent = {"instruction": text, "source_id": "code", "source_sha256": _sha(text.encode()),
              "domain": "devtools", "split": "train"}
    for span in _source_spans(parent):
        target, reason = targets.extract_rich_span_target(span, parent)
        assert target is None and reason


def test_inherited_prohibition_and_explicit_conflict_are_preserved(tmp_path):
    report, _, _ = _corpus(tmp_path, [
        ("prohibition", "# MUST NOT DO\n## Maintenance\nReview report.\n"),
        ("conflict", "# MUST NOT DO\nThe agent may review cache.\n"),
    ])
    assert len(report["targets"]) == 1
    row = report["targets"][0]
    assert row["target"]["kind"] == "action"
    assert row["target"]["actions"][0]["modality"] == "prohibited"
    assert row["target"]["actions"][0]["actor"] == "unspecified"


def test_source_bound_targets_preserve_partition_and_unicode_byte_offsets(tmp_path):
    text = "# Instructions 🧪\r\nReview report.\r\n"
    report, sources, _ = _corpus(tmp_path, [("unicode", text)])
    assert len(report["targets"]) == 1
    row = report["targets"][0]
    parent = sources["samples"][0]
    assert row["split"] == parent["split"]
    assert row["source_id"] == parent["id"]
    provenance = row["provenance"]
    assert provenance["source_sha256"] == _sha(text.encode())
    assert provenance["human_reviewed"] is provenance["gold_source_semantics"] is False
    for selector, fragment in zip(provenance["spans"], provenance["source_fragments"]):
        assert text[selector["start_char"]:selector["end_char"]] == fragment
        assert text.encode()[selector["start_byte"]:selector["end_byte"]].decode() == fragment
    targets.validate_skillcenter_rich_span_targets(report)


@pytest.mark.parametrize("field", ["split", "target", "source", "native", "qualification", "authority"])
def test_rich_report_replay_rejects_forgery_even_after_outer_rehash(tmp_path, field):
    report, _, _ = _corpus(tmp_path, [("forgery", "Review report.\n")])
    forged = deepcopy(report)
    row = forged["targets"][0]
    if field == "split":
        row["split"] = "test" if row["split"] != "test" else "train"
    elif field == "target":
        row["target"]["actions"][0]["modality"] = "prohibited"
    elif field == "source":
        row["provenance"]["source_sha256"] = "0" * 64
    elif field == "native":
        row["native_intent_ir"]["statements"][0]["modality"] = "prohibited"
    elif field == "qualification":
        row["qualification"]["training_supported"] = False
    else:
        forged["semantic_correctness_verified"] = True
    forged.pop("report_sha256", None)
    forged["report_sha256"] = _sha(_wire(forged))
    with pytest.raises(ValueError):
        targets.validate_skillcenter_rich_span_targets(forged)


def test_parent_source_shard_change_breaks_rich_replay(tmp_path):
    report, _, args = _corpus(tmp_path, [("tamper", "Review report.\n")])
    shard = args["release_root"] / args["shards"][0]
    shard.write_bytes(shard.read_bytes() + b"changed")
    with pytest.raises(ValueError):
        targets.validate_skillcenter_rich_span_targets(report)


@pytest.mark.parametrize("bad_instruction", [
    "Review report 123.", "Review report - output.", "Review report _ output.",
])
def test_lexically_unsupported_row_does_not_abort_valid_source_export(tmp_path, bad_instruction):
    report, _, _ = _corpus(tmp_path, [
        ("valid", "Review report.\n"), ("unsupported", bad_instruction + "\n"),
    ])
    assert len(report["targets"]) == 1
    assert report["targets"][0]["target"]["actions"][0]["object"] == "report"
    assert report["omitted"]
    targets.validate_skillcenter_rich_span_targets(report)


def test_native_qualification_failure_is_not_silenced_as_a_source_gap(tmp_path, monkeypatch):
    spans, _, _ = _source(tmp_path, [("valid", "Review report.\n")])
    def broken_qualification(*args, **kwargs):
        raise ValueError("independent native semantic fence failure")
    monkeypatch.setattr(bridge, "qualify_structured_target", broken_qualification)
    with pytest.raises(ValueError, match="native semantic fence failure"):
        targets.build_skillcenter_rich_span_targets(spans)


def test_export_refuses_to_replace_existing_checkpoint_directory(tmp_path):
    destination = tmp_path / "existing"
    destination.mkdir()
    sentinel = destination / "weights.json"
    sentinel.write_bytes(b"unchanged legal initializer")
    with pytest.raises(ValueError, match="fresh"):
        targets.export_skillcenter_rich_span_targets({}, output=destination)
    assert sentinel.read_bytes() == b"unchanged legal initializer"


def test_cross_partition_duplicates_do_not_reassign_source_splits(tmp_path):
    docs = [(f"split{index}", f"Review sharedreport.\n\nInspect object{index}.\n")
            for index in range(36)]
    report, sources, _ = _corpus(tmp_path, docs)
    assignments = {row["id"]: row["split"] for row in sources["samples"]}
    assert len(set(assignments.values())) > 1
    assert report["targets"]
    assert all(row["target"]["actions"][0]["object"] != "sharedreport"
               for row in report["targets"])
    assert all(row["split"] == assignments[row["source_id"]] for row in report["targets"])


def test_rich_conditional_collisions_are_quarantined_before_native_qualification(tmp_path):
    docs = [(f"conditional{index}", f"# Scope {index}\nIf tests pass, delete cache.\n")
            for index in range(36)]
    report, sources, _ = _corpus(tmp_path, docs)
    assert len({row["split"] for row in sources["samples"]}) > 1
    assert not report["targets"]
    assert len(report["quarantined"]) == len(docs)
    assert all(row["reason"] == "cross_partition_instruction_or_semantic_target_collision"
               for row in report["quarantined"])


def test_sequence_and_condition_targets_never_enter_single_clause_training(tmp_path):
    from ipfs_datasets_py.logic.intent_ir.formalize.rich_span_training import (
        build_rich_span_pairs, validate_rich_span_pairs,
    )
    spans, _, _ = _source(tmp_path, [
        ("simple", "Review report.\n"),
        ("sequence", "Read report, then update cache.\n"),
        ("condition", "If tests pass, delete cache.\n"),
        ("case", "Verify CSS custom properties.\n"),
    ])
    descriptor = targets.export_skillcenter_rich_span_targets(spans, output=tmp_path / "rich")
    report = targets.load_skillcenter_rich_span_targets(descriptor)
    assert {row["target"]["kind"] for row in report["targets"]} == {"action", "sequence", "conditional"}
    case = next(row for row in report["targets"] if row["target"]["actions"][0]["object"] == "CSS custom properties")
    assert case["native_intent_ir"]["actions"][0]["object_refs"] == ["CSS custom properties"]
    assert case["qualification"]["training_supported"] is False
    corpus = build_rich_span_pairs(descriptor)
    assert len(corpus["samples"]) == 1
    assert corpus["samples"][0]["frame"]["action"] == "review"
    assert corpus["include_authored"] is False
    validate_rich_span_pairs(corpus)


def test_rich_cli_trains_real_shared_weights_without_changing_source_export(tmp_path, monkeypatch, capsys):
    import importlib.util
    import torch
    from ipfs_datasets_py.logic.intent_ir.formalize.roundtrip import load_intent_roundtrip_checkpoint

    torch.set_num_threads(1)
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "")
    spans, sources, _ = _source(tmp_path, [
        (f"train{index}", f"Review object{index}.\n") for index in range(36)])
    assert {row["split"] for row in sources["samples"]} >= {"train", "validation"}
    target_root = tmp_path / "targets"
    descriptor = targets.export_skillcenter_rich_span_targets(spans, output=target_root)
    source_before = Path(descriptor["path"]).read_bytes()
    cli_path = Path(__file__).resolve().parents[4] / "scripts/training/train_intent_roundtrip.py"
    spec = importlib.util.spec_from_file_location("rich_roundtrip_cli_test", cli_path)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    lexical = tmp_path / "lexical.json"
    lexical.write_text(json.dumps({"keys": ["token:object0", "token:review", "token:unspecified"],
        "weights": [[0.1, 0.2], [0.2, 0.3], [0.3, 0.4]], "embedding_width": 2,
        "source_checkpoint_sha256": "a" * 64}))
    output = tmp_path / "trained"
    assert cli.main([
        "--rich-target-descriptor", str(target_root / "descriptor.json"),
        "--lexical-initializer", str(lexical),
        "--output", str(output), "--epochs", "1", "--max-seconds", "20",
        "--hidden-size", "8", "--embedding-dim", "8",
    ]) == 0
    summary = json.loads(capsys.readouterr().out)
    checkpoint = load_intent_roundtrip_checkpoint(summary["checkpoint"])
    training = checkpoint["backend"]["training"]
    assert training["optimizer_steps"] > 0 and training["native_kernel_calls"] > 0
    assert training["initial_state_sha256"] != training["final_state_sha256"]
    corpus = json.loads((output / "corpus.json").read_bytes())
    receipt = json.loads((output / "training-receipt.json").read_bytes())
    assert corpus["conditional_or_sequence_training"] is False
    assert corpus["include_authored"] is False
    assert receipt["test_used_for_training_or_tuning"] is False
    assert {row["provenance"]["kind"] for row in corpus["samples"]} == {"skillcenter_rich_weak_span"}
    assert Path(descriptor["path"]).read_bytes() == source_before
    assert summary["published"] is False


@pytest.mark.parametrize("split", ["train", "validation", "test"])
@pytest.mark.parametrize("include_authored", [False, True])
@pytest.mark.parametrize("punctuation_spacing", [False, True])
def test_same_partition_normalized_instruction_with_different_targets_is_quarantined(
        monkeypatch, split, include_authored, punctuation_spacing):
    from ipfs_datasets_py.logic.intent_ir.formalize import rich_span_training
    from ipfs_datasets_py.logic.intent_ir.formalize.roundtrip import frame_to_intent_ir
    from ipfs_datasets_py.logic.intent_ir.formalize.roundtrip_corpus import authored_intent_pairs
    from ipfs_datasets_py.logic.intent_ir.formalize.roundtrip_training import build_training_pairs
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_paired_text import _pairs, tokenize

    def admitted(identifier, instruction, frame):
        return {"id": identifier, "span_id": identifier + "-span", "source_id": identifier + "-source",
            "split": split, "instruction": instruction,
            "target": {"kind": "action", "actions": [frame], "condition": None},
            "native_intent_ir": frame_to_intent_ir(frame, instruction=instruction).to_dict(),
            "qualification": {"training_supported": True},
            "provenance": {"source_id": identifier + "-source"}}

    sentinel = admitted("sentinel", "Inspect sentinel.", _frame(action="inspect", object_="sentinel"))
    if include_authored:
        authored = next(row for row in authored_intent_pairs() if row["split"] == split
            and row["frame"]["modality"] == "required"
            and row["instruction"] == "the {actor} must {action} the {object}.".format(**row["frame"]))
        frame = {**authored["frame"], "object": "the " + authored["frame"]["object"]}
        instruction = authored["instruction"].capitalize()
        if punctuation_spacing:
            instruction = instruction[:-1] + " ."
        rows = [admitted("ambiguous", instruction, frame), sentinel]
    else:
        instruction = "Review the report."
        alias = "review  the report ." if punctuation_spacing else "review  the report."
        rows = [admitted("ambiguous-a", instruction, _frame(object_="the report")),
                admitted("ambiguous-b", alias, _frame(object_="report")), sentinel]
    original_rows = deepcopy(rows)
    # The source replay layer is exercised above; isolate the downstream
    # mixture of already admitted targets and optional authored controls.
    monkeypatch.setattr(targets, "load_skillcenter_rich_span_targets", lambda _: {"targets": rows})
    corpus = rich_span_training.build_rich_span_pairs({}, include_authored=include_authored)
    normalized_tokens = tokenize(" ".join(instruction.lower().split()))
    assert not any(tokenize(" ".join(row["instruction"].lower().split())) == normalized_tokens
                   for row in corpus["samples"])
    assert len(corpus["quarantined"]) == 2
    assert {row["split"] for row in corpus["quarantined"]} == {split}
    retained = next(row for row in corpus["samples"] if row["provenance"].get("target_id") == "sentinel")
    assert retained["instruction"] == sentinel["instruction"]
    assert retained["native_intent_ir"] == sentinel["native_intent_ir"]
    assert rows == original_rows
    for partition in ("train", "validation", "test"):
        samples = [row for row in corpus["samples"] if row["split"] == partition]
        if samples:
            assert _pairs(build_training_pairs(samples))


@pytest.mark.parametrize("public_split", ["validation", "test"])
def test_backend_token_equivalence_across_partitions_is_quarantined(monkeypatch, public_split):
    from ipfs_datasets_py.logic.intent_ir.formalize import rich_span_training
    from ipfs_datasets_py.logic.intent_ir.formalize.roundtrip import frame_to_intent_ir
    from ipfs_datasets_py.logic.intent_ir.formalize.roundtrip_corpus import authored_intent_pairs
    from ipfs_datasets_py.logic.intent_ir.formalize.roundtrip_training import _validated_samples, build_training_pairs
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_paired_text import _pairs, tokenize
    authored = next(row for row in authored_intent_pairs()
                    if row["instruction"] == "the agent must read the report.")
    assert authored["split"] == "train"
    instruction = "The agent must read the report ."
    frame = {**authored["frame"], "object": "the report"}
    public = {"id": "token-alias", "span_id": "token-alias-span", "source_id": "token-alias-source",
        "split": public_split, "instruction": instruction,
        "target": {"kind": "action", "actions": [frame], "condition": None},
        "native_intent_ir": frame_to_intent_ir(frame, instruction=instruction).to_dict(),
        "qualification": {"training_supported": True}, "provenance": {"source_id": "token-alias-source"}}
    monkeypatch.setattr(targets, "load_skillcenter_rich_span_targets", lambda _: {"targets": [public]})
    corpus = rich_span_training.build_rich_span_pairs({}, include_authored=True)
    bad_tokens = tokenize(instruction.lower())
    assert not any(tokenize(" ".join(row["instruction"].lower().split())) == bad_tokens
                   for row in corpus["samples"])
    assert len(corpus["quarantined"]) == 2
    assert {row["split"] for row in corpus["quarantined"]} == {"train", public_split}
    _validated_samples(corpus)
    for split in ("train", "validation", "test"):
        assert _pairs(build_training_pairs([row for row in corpus["samples"] if row["split"] == split]))
