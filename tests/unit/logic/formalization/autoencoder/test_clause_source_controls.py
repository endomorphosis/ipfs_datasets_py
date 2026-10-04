"""Source-only control plumbing, without a model, encoder, or reference parser."""
from copy import deepcopy
import hashlib
import inspect
import json

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import clause_source_controls as subject


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def text_digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def vector(index):
    return [float(i == index % 384) for i in range(384)]


def fixture(lengths=(1, 1, 2, 2, 4, 4, 8, 8)):
    rows, contexts = [], {}
    for index, length in enumerate(lengths):
        identity = f"source-{index:03}"
        texts = [f"Clause {index} rôle π {slot}." for slot in range(length)]
        source = "\n\n".join(texts)
        descriptor = dict(source_sha256=text_digest(source), segments=[])
        char = byte = 0
        for slot, text in enumerate(texts):
            embedding = vector(index * 8 + slot)
            descriptor["segments"].append(dict(source_text=text, source_sha256=text_digest(text),
                embedding_sha256=digest(embedding), vector=embedding,
                char_start=char, char_end=char + len(text),
                byte_start=byte, byte_end=byte + len(text.encode())))
            char += len(text) + 2
            byte += len(text.encode()) + 2
        contexts[identity] = descriptor
        # Deliberately unrelated to clause length: this payload must remain opaque.
        rows.append(dict(id=identity, source_text=source, input=vector(200 + index),
            target_ids=[1, 3, 2]))
    return rows, contexts


def assert_strict(actual_rows, actual_contexts):
    subject.context_owner.validate_contexts(actual_rows, actual_contexts)
    for row in actual_rows:
        descriptor = actual_contexts[row["id"]]
        assert row["source_text"] == "\n\n".join(s["source_text"] for s in descriptor["segments"])
        assert descriptor["source_sha256"] == text_digest(row["source_text"])
        for segment in descriptor["segments"]:
            assert row["source_text"][segment["char_start"]:segment["char_end"]] == segment["source_text"]
            assert row["source_text"].encode()[segment["byte_start"]:segment["byte_end"]].decode() == segment["source_text"]


def test_conditioned_is_value_exact_but_has_no_mutable_aliases():
    rows, contexts = fixture()
    actual, context, execution = subject.prepare_control(rows, contexts, "conditioned")
    assert actual == rows and context == contexts
    assert execution["kind"] == execution["control"]["kind"] == "conditioned"
    assert not execution["provenance_breaking"]
    assert execution["original_contexts_sha256"] == execution["actual_contexts_sha256"]
    actual[0]["input"][0] = 12
    actual[0]["target_ids"].append(99)
    context[rows[0]["id"]]["segments"][0]["vector"][0] = 12
    assert rows[0]["input"][0] != 12 and rows[0]["target_ids"] == [1, 3, 2]
    assert contexts[rows[0]["id"]]["segments"][0]["vector"][0] != 12


@pytest.mark.parametrize("kind", subject.KINDS)
def test_all_controls_preserve_inputs_targets_order_and_caller_data(kind):
    rows, contexts = fixture(tuple(x for x in (1, 2, 4, 8) for _ in range(12))
        if kind == "cross_length_shuffle" else (1, 1, 2, 2, 4, 4, 8, 8))
    original = deepcopy((rows, contexts))
    actual, controlled, execution = subject.prepare_control(rows, contexts, kind)
    assert (rows, contexts) == original
    assert [r["id"] for r in actual] == [r["id"] for r in rows]
    assert [r["target_ids"] for r in actual] == [r["target_ids"] for r in rows]
    assert_strict(actual, controlled)
    assert execution["source_only"] and execution["target_payloads_read"] is False
    assert execution["references_accepted"] is False
    assert not any(execution[key] for key in ("admitted", "qualified", "lake_executed"))


def test_within_shuffle_moves_the_complete_source_bundle_with_sorted_source_groups():
    rows, contexts = fixture()
    rows.reverse()
    actual, controlled, execution = subject.prepare_control(rows, contexts, "source_shuffle")
    by_id = {r["id"]: r for r in rows}
    for row in actual:
        donor = execution["source_assignment"][row["id"]]
        assert donor != row["id"]
        assert execution["paragraph_source_assignment"][row["id"]] == donor
        assert row["source_text"] == by_id[donor]["source_text"]
        assert row["input"] == by_id[donor]["input"]
        assert controlled[row["id"]] == contexts[donor]
    expected = {f"source-{i:03}": f"source-{i ^ 1:03}" for i in range(8)}
    assert execution["source_assignment"] == expected


def test_context_only_shuffle_preserves_paragraph_vector_but_binds_donor_context_text():
    rows, contexts = fixture()
    actual, controlled, execution = subject.prepare_control(rows, contexts, "context_only_shuffle")
    by_id = {r["id"]: r for r in rows}
    for row in actual:
        identity = row["id"]
        donor = execution["context_source_assignment"][identity]
        assert row["input"] == by_id[identity]["input"]
        assert row["source_text"] == by_id[donor]["source_text"]
        assert controlled[identity] == contexts[donor]
        assert execution["paragraph_source_assignment"][identity] == identity
        binding = execution["source_bindings"][identity]
        assert binding["paragraph_source_sha256"] == text_digest(by_id[identity]["source_text"])
        assert binding["actual_context_source_sha256"] == text_digest(by_id[donor]["source_text"])
        assert binding["actual_input_sha256"] == digest(by_id[identity]["input"])
        assert binding["effective_context_change"] and not binding["effective_paragraph_change"]
    assert execution["provenance_breaking"]
    assert execution["control"]["kind"] == "context_only_shuffle"


@pytest.mark.parametrize("kind", ["context_reverse", "context_rotate"])
def test_order_controls_rebuild_unicode_offsets_and_keep_original_target_and_paragraph(kind):
    rows, contexts = fixture((1, 2, 4, 8))
    actual, controlled, execution = subject.prepare_control(rows, contexts, kind)
    for original, row in zip(rows, actual):
        identity = original["id"]
        segments = contexts[identity]["segments"]
        indices = list(range(len(segments)))
        order = indices[::-1] if kind == "context_reverse" else indices[1:] + indices[:1]
        assert execution["context_permutation"][identity] == order
        assert row["source_text"] == "\n\n".join(segments[i]["source_text"] for i in order)
        assert [s["vector"] for s in controlled[identity]["segments"]] == [segments[i]["vector"] for i in order]
        assert row["input"] == original["input"] and row["target_ids"] == original["target_ids"]
        assert execution["source_bindings"][identity]["effective_context_change"] == (len(segments) > 1)
    assert_strict(actual, controlled)


def test_cross_length_source_assignment_matches_fixed_48_row_rotation_without_references():
    rows, contexts = fixture(tuple(x for x in (1, 2, 4, 8) for _ in range(12)))
    rows.reverse()
    actual, controlled, execution = subject.prepare_control(rows, contexts, "cross_length_shuffle")
    by_id = {row["id"]: row for row in rows}
    expected = {f"source-{i:03}": f"source-{(i + 12) % 48:03}" for i in range(48)}
    assert execution["source_assignment"] == expected
    assert execution["kind"] == "cross_length_shuffle"
    for row in actual:
        original = by_id[row["id"]]
        assert len(row["source_text"].split("\n\n")) != len(original["source_text"].split("\n\n"))
        assert row["input"] == by_id[expected[row["id"]]]["input"]
    assert_strict(actual, controlled)


@pytest.mark.parametrize("kind", ["source_shuffle", "context_only_shuffle"])
def test_singleton_shuffle_stratum_is_rejected(kind):
    rows, contexts = fixture((1, 1, 2))
    with pytest.raises(ValueError, match="two rows"):
        subject.prepare_control(rows, contexts, kind)


@pytest.mark.parametrize("lengths", [(1, 1, 2, 2, 4, 4, 8, 8), (1,) * 48,
    tuple(x for x in (1, 2, 4, 8) for _ in range(11))])
def test_unbalanced_cross_length_inventory_is_rejected(lengths):
    rows, contexts = fixture(lengths)
    with pytest.raises(ValueError, match="twelve source rows"):
        subject.prepare_control(rows, contexts, "cross_length_shuffle")


def test_equal_paragraph_vectors_are_not_misreported_as_effective_whole_source_shuffle():
    rows, contexts = fixture((1, 1))
    rows[1]["input"] = deepcopy(rows[0]["input"])
    with pytest.raises(ValueError, match="equal-vector"):
        subject.prepare_control(rows, contexts, "source_shuffle")
    # Clause-only perturbation remains meaningful and does not claim a vector change.
    subject.prepare_control(rows, contexts, "context_only_shuffle")


def test_equal_context_text_is_not_misreported_as_effective_shuffle():
    rows, contexts = fixture((1, 1))
    rows[1]["source_text"] = rows[0]["source_text"]
    contexts[rows[1]["id"]] = deepcopy(contexts[rows[0]["id"]])
    with pytest.raises(ValueError, match="duplicate normalized paragraph|equal-text"):
        subject.prepare_control(rows, contexts, "context_only_shuffle")


def test_target_objects_are_not_inspected_or_hashed():
    class Opaque:
        def __deepcopy__(self, memo):
            return self
        def __iter__(self):
            raise AssertionError("target contents read")
        def __len__(self):
            raise AssertionError("target length read")
        def __repr__(self):
            raise AssertionError("target formatted")
    rows, contexts = fixture((1, 1, 2, 2))
    opaque = Opaque()
    for row in rows:
        row["target_ids"] = opaque
    actual, _, execution = subject.prepare_control(rows, contexts, "source_shuffle")
    assert all(row["target_ids"] is opaque for row in actual)
    assert execution["target_payloads_read"] is False
    assert tuple(inspect.signature(subject.prepare_control).parameters) == ("rows", "contexts", "kind")


@pytest.mark.parametrize("change", ["descriptor_source_hash", "segment_embedding", "offset", "missing_context", "extra_context"])
def test_invalid_original_context_binding_fails_before_control(change):
    rows, contexts = fixture((1, 1))
    identity = rows[0]["id"]
    if change == "descriptor_source_hash":
        contexts[identity]["source_sha256"] = "0" * 64
    elif change == "segment_embedding":
        contexts[identity]["segments"][0]["vector"][0] = 0.5
    elif change == "offset":
        contexts[identity]["segments"][0]["byte_end"] -= 1
    elif change == "missing_context":
        contexts.pop(identity)
    else:
        contexts["unrelated"] = deepcopy(contexts[identity])
    with pytest.raises(ValueError):
        subject.prepare_control(rows, contexts, "source_shuffle")


@pytest.mark.parametrize("kind", ["zero_condition", "unknown", None, 1])
def test_unknown_controls_are_not_silently_conditioned(kind):
    rows, contexts = fixture((1, 1))
    with pytest.raises(ValueError, match="unsupported"):
        subject.prepare_control(rows, contexts, kind)


def test_control_source_id_inventory_is_closed():
    rows, contexts = fixture((1, 1))
    rows[1]["id"] = rows[0]["id"]
    with pytest.raises(ValueError, match="unique"):
        subject.prepare_control(rows, contexts, "conditioned")
    rows, contexts = fixture((1, 1))
    rows[0]["reference_count"] = 1
    with pytest.raises(ValueError, match="closed"):
        subject.prepare_control(rows, contexts, "conditioned")
