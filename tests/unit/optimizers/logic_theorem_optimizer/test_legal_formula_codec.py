"""The learned decoder's tokens are lossless; grammar is not qualification."""
import copy
import json
import pytest
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_formula_codec as codec


def example(identifier="one", *, actor="Company A", modality="O", object="backup report",
            conditions=None, exceptions=None, temporal=None, source=None):
    return {"id": identifier,
            "source_text": source or "Company A shall submit backup report within 10 days unless emergency.",
            "canonical_ir": {"rules": [{"modality": modality, "actor": actor, "action": "submit", "object": object,
                "conditions": conditions or [], "exceptions": exceptions or [], "temporal": temporal or []}]}}


@pytest.fixture
def examples():
    return [example(exceptions=["emergency"], temporal=["within 10 days"]),
            example("two", actor="agency", modality="F", object="records",
                    source="The agency shall not submit records."),
            example("three", actor="officer", modality="P", object="file",
                    temporal=["for at least 20 days"], source="The officer may submit file for at least 20 days.")]


def test_actual_full_ir_roundtrip_preserves_all_seven_facets(examples):
    fitted = codec.fit_codec(examples)
    codec.validate_codec(fitted)
    for row in examples:
        ids = codec.encode_target(fitted, row["canonical_ir"])
        assert ids[0] == 1 and ids[-1] == 2 and len(ids) <= 64
        assert codec.decode_target(fitted, ids) == row["canonical_ir"]
        for index, token in enumerate(ids):
            assert token in codec.allowed_token_ids(fitted, ids[:index])
        assert codec.allowed_token_ids(fitted, ids) == []
    assert fitted["source_vocabulary"][:2] == ["<pad>", "<unk>"]
    assert fitted["target_vocabulary"][:3] == ["<pad>", "<bos>", "<eos>"]


def test_vocabularies_are_deterministic_and_survive_json(examples):
    a = codec.fit_codec(examples)
    assert a == codec.fit_codec(list(reversed(examples)))
    reloaded = json.loads(json.dumps(a, ensure_ascii=False))
    codec.validate_codec(reloaded)
    assert codec.encode_target(a, examples[0]["canonical_ir"]) == codec.encode_target(reloaded, examples[0]["canonical_ir"])


def test_source_ids_retain_content_and_negation_without_parser(examples):
    fitted = codec.fit_codec(examples)
    positive = codec.encode_source(fitted, "The agency shall submit records.")
    negative = codec.encode_source(fitted, "The agency shall not submit records.")
    assert positive != negative
    assert positive == codec.encode_source(fitted, "THE AGENCY SHALL SUBMIT RECORDS.")
    assert all(token > 1 for token in positive)


def test_identifiers_are_exact_not_historical_hash_buckets():
    rows = [example("a", actor="actor1"), example("b", actor="actor3")]
    fitted = codec.fit_codec(rows)
    left, right = [codec.encode_target(fitted, row["canonical_ir"]) for row in rows]
    assert left != right
    assert codec.decode_target(fitted, left)["rules"][0]["actor"] == "actor1"
    assert codec.decode_target(fitted, right)["rules"][0]["actor"] == "actor3"


def test_scope_quantity_and_kind_are_distinct_exact_atoms():
    rows = [example("within", temporal=["within 10 days"]),
            example("minimum", temporal=["for at least 20 days"]),
            example("other", temporal=["within 20 days"])]
    fitted = codec.fit_codec(rows)
    encoded = [codec.encode_target(fitted, row["canonical_ir"]) for row in rows]
    assert len({tuple(ids) for ids in encoded}) == 3
    for row, ids in zip(rows, encoded):
        assert codec.decode_target(fitted, ids) == row["canonical_ir"]


def test_typed_atoms_cannot_collide_with_markers_or_other_fields():
    rows = [example(object="<bos>", actor="conditions"), example("two", object="conditions", actor="<bos>")]
    fitted = codec.fit_codec(rows)
    for row in rows:
        ids = codec.encode_target(fitted, row["canonical_ir"])
        assert ids.count(codec.TARGET_BOS) == 1
        assert codec.decode_target(fitted, ids) == row["canonical_ir"]
    first, second = [codec.encode_target(fitted, row["canonical_ir"]) for row in rows]
    malformed = list(first)
    malformed[4] = second[8]
    with pytest.raises(codec.CodecError, match="another field"):
        codec.decode_target(fitted, malformed)


def test_unknown_source_and_target_never_extend_training_vocab(examples):
    fitted = codec.fit_codec(examples)
    before = copy.deepcopy(fitted)
    with pytest.raises(codec.CodecError, match="out-of-vocabulary"):
        codec.encode_source(fitted, "A neverseenactor submits records.")
    changed = copy.deepcopy(examples[0]["canonical_ir"])
    changed["rules"][0]["actor"] = "unseen agency"
    with pytest.raises(codec.CodecError, match="out-of-vocabulary"):
        codec.encode_target(fitted, changed)
    assert fitted == before


@pytest.mark.parametrize("ids", [[], [2], [1, 2], [0], [True], [-1], [999999]])
def test_empty_invalid_and_incomplete_sequences_never_decode(examples, ids):
    with pytest.raises(codec.CodecError):
        codec.decode_target(codec.fit_codec(examples), ids)


def test_eos_never_appears_before_all_fields_and_cannot_be_padded(examples):
    fitted = codec.fit_codec(examples)
    ids = codec.encode_target(fitted, examples[0]["canonical_ir"])
    for index in range(len(ids) - 1):
        assert codec.TARGET_EOS not in codec.allowed_token_ids(fitted, ids[:index])
    with pytest.raises(codec.CodecError, match="incomplete"):
        codec.decode_target(fitted, ids[:-1])
    with pytest.raises(codec.CodecError, match="after EOS"):
        codec.decode_target(fitted, ids + [0])


@pytest.mark.parametrize("values", [["emergency", "emergency"], ["z", "a"], [""], [1], ["a", "b", "c", "d", "e"]])
def test_lossy_or_unbounded_qualifiers_rejected_not_normalized(values):
    row = example(exceptions=values)
    before = copy.deepcopy(row)
    with pytest.raises(codec.CodecError):
        codec.fit_codec([row])
    assert row == before


def test_qualifier_limit_and_lexical_order_enforced_during_generation():
    row = example(conditions=["a", "b", "c", "d"])
    fitted = codec.fit_codec([row])
    ids = codec.encode_target(fitted, row["canonical_ir"])
    decoded_tokens = [fitted["target_vocabulary"][token] for token in ids]
    first = decoded_tokens.index('["atom","conditions","a"]')
    assert ids[first] not in codec.allowed_token_ids(fitted, ids[:first + 1])
    next_ids = codec.allowed_token_ids(fitted, ids[:first + 4])
    assert [fitted["target_vocabulary"][token] for token in next_ids] == ['["end","conditions"]']
    with pytest.raises(codec.CodecError, match="sorted unique"):
        codec.decode_target(fitted, ids[:first + 1] + [ids[first]] + ids[first + 1:])


@pytest.mark.parametrize("update", [lambda ir: ir.update(extra=True),
    lambda ir: ir["rules"].append(copy.deepcopy(ir["rules"][0])),
    lambda ir: ir["rules"][0].update(proved=True), lambda ir: ir["rules"][0].pop("exceptions"),
    lambda ir: ir["rules"][0].update(modality="obligation")])
def test_extra_information_is_rejected_not_dropped(update):
    row = example()
    update(row["canonical_ir"])
    with pytest.raises(codec.CodecError):
        codec.fit_codec([row])


def test_pgir_placeholder_validation_is_reused():
    with pytest.raises(codec.CodecError, match="grammar rejected"):
        codec.fit_codec([example(actor="source_text")])


def test_source_limit_never_truncates():
    fitted = codec.fit_codec([example(source="agency " * 64)])
    assert len(codec.encode_source(fitted, "agency " * 64)) == 64
    with pytest.raises(codec.CodecError, match="64 tokens"):
        codec.encode_source(fitted, "agency " * 65)
    with pytest.raises(codec.CodecError, match="64 tokens"):
        codec.fit_codec([example(source="agency " * 65)])


def test_target_prefix_limit_is_hard(examples):
    with pytest.raises(codec.CodecError, match="64 token"):
        codec.allowed_token_ids(codec.fit_codec(examples), [1] * 65)


@pytest.mark.parametrize("change", [lambda x: x.update(schema="other"), lambda x: x.update(extra=True),
    lambda x: x["policy"].update(max_source_tokens=65), lambda x: x["policy"].update(max_source_tokens=64.0),
    lambda x: x["target_vocabulary"].__setitem__(1, "<changed>"),
    lambda x: x["source_vocabulary"].append(x["source_vocabulary"][-1]),
    lambda x: x.update(target_vocabulary=["x"] * 4097)])
def test_codec_tampering_is_rejected_even_after_cached_validation(examples, change):
    fitted = codec.fit_codec(examples)
    codec.validate_codec(fitted)
    change(fitted)
    with pytest.raises(codec.CodecError):
        codec.validate_codec(fitted)


def test_vocab_and_example_limits():
    with pytest.raises(codec.CodecError, match="4096 training examples"):
        codec.fit_codec([example()] * 4097)
    rows = [example(str(i), actor=f"actor{i}", source=" ".join(f"word{i}_{j}" for j in range(64))) for i in range(65)]
    with pytest.raises(codec.CodecError, match="vocabulary exceeds 4096"):
        codec.fit_codec(rows)
