"""Synthetic numerical checks; these tests do not establish legal accuracy."""
from copy import deepcopy
import hashlib
import json

import pytest
import torch

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_formula as span
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_dimensions as dims
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_grounding as grounded


def examples():
    result = []
    for i, (actor, modality, cue, action, obj) in enumerate((
        ("Lark Authority", "O", "must", "retain", "books"),
        ("Wren", "P", "may", "publish", "records"),
        ("Finch Office", "F", "must not", "destroy", "files"),
    )):
        text = f"{actor} {cue} {action} {obj}."
        facets = {"actor": [0, len(actor)], "action": [text.index(action), text.index(action) + len(action)],
                  "object": [text.index(obj), text.index(obj) + len(obj)],
                  "conditions": None, "exceptions": None, "temporal": None}
        result.append({"id": f"synthetic-{i}", "source_text": text,
            "canonical_ir": {"rules": [{"actor": actor, "modality": modality, "action": action,
                "object": obj, "conditions": [], "exceptions": [], "temporal": []}]},
            "trigger_span": [len(actor) + 1, len(actor) + 1 + len(cue)], "facet_spans": facets})
    return result


def plain(rows=None):
    return [{key: row[key] for key in ("id", "source_text", "canonical_ir")} for row in (rows or examples())]


@pytest.fixture(scope="module", autouse=True)
def threads():
    original = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(original)


@pytest.fixture(scope="module")
def parent():
    data = plain()
    base = span.build_checkpoint(data, latent_dimension=0, latent_enabled=False,
        hidden_size=8, embedding_dim=4, projection_width=4, batch_size=2)
    original = span.train_decoder(base, data, max_steps=2, max_seconds=30)["checkpoint"]
    child = dims.build_checkpoint(original, data, latent_dimension=0, batch_size=2)
    return dims.train_decoder(child, data, max_steps=2, max_seconds=30)["checkpoint"]


def checkpoint(parent, enabled=True):
    return grounded.build_checkpoint(parent, examples(), trigger_enabled=enabled, batch_size=2)


@pytest.mark.parametrize("enabled", [False, True])
def test_initialization_copies_parent_and_all_source_logits(parent, enabled):
    before = grounded.checkpoint_digest(parent)
    cp = checkpoint(parent, enabled)
    grounded.validate_checkpoint(cp)
    original = dims.DimensionalSpanDecoder(parent)
    new = grounded.GroundedSpanDecoder(cp)
    records, _ = grounded._splits(examples(), [])
    with torch.no_grad():
        a = original.model(*span._batch(torch, records))
        b = new.model(*span._batch(torch, records))
    assert all(torch.equal(a[key], b[key]) for key in a)
    assert grounded._source_state(cp["model_state"]) == parent["model_state"]
    assert grounded.initial_source_model_digest(cp) == grounded.checkpoint_digest(parent["model_state"])
    for name in ("trigger_modality.weight", "trigger_modality.bias", "actor_boundary.weight", "actor_boundary.bias"):
        assert torch.count_nonzero(torch.tensor(cp["model_state"][name])) == 0
    assert grounded.checkpoint_digest(parent) == before


def test_disabled_training_is_exact_original_source_continuation(parent):
    cp = checkpoint(parent, False)
    data = plain()
    original = span.build_checkpoint(data, latent_dimension=0, latent_enabled=False,
        hidden_size=8, embedding_dim=4, projection_width=4, batch_size=2, learning_rate=.001)
    original["model_state"] = deepcopy(parent["model_state"])
    expected = span.train_decoder(original, data, max_steps=4, max_seconds=30)["checkpoint"]
    result = grounded.train_decoder(cp, examples(), max_steps=4, max_seconds=30)
    assert grounded._source_state(result["checkpoint"]["model_state"]) == expected["model_state"]
    assert grounded._source_state(result["checkpoint"]["optimizer_state"]["parameters"]) == expected["optimizer_state"]["parameters"]
    assert result["checkpoint"]["progress"] == expected["progress"]
    assert all(value == 0. for value in result["report"]["auxiliary_gradient_norm_max"].values())
    for key in cp["model_state"]:
        if key.startswith(grounded._EXTRA):
            assert result["checkpoint"]["model_state"][key] == cp["model_state"][key]


@pytest.mark.parametrize("enabled", [False, True])
def test_split_resumption_matches_weights_moments_and_losses(parent, enabled):
    cp = checkpoint(parent, enabled)
    full = grounded.train_decoder(cp, examples(), max_steps=4, max_seconds=30)
    first = grounded.train_decoder(cp, examples(), max_steps=2, max_seconds=30)
    second = grounded.train_decoder(first["checkpoint"], examples(), max_steps=2, max_seconds=30)
    for key in ("model_state", "optimizer_state", "progress"):
        assert full["checkpoint"][key] == second["checkpoint"][key]
    assert full["report"]["batch_losses"] == first["report"]["batch_losses"] + second["report"]["batch_losses"]
    assert grounded.optimizer_steps(second["checkpoint"]) == 4
    grounded.validate_checkpoint(second["checkpoint"])


def test_new_heads_learn_and_attention_changes_modality_without_runtime_labels(parent):
    cp = checkpoint(parent)
    fitted = grounded.train_decoder(cp, examples(), max_steps=3, max_seconds=30)
    assert all(value > 0 for value in fitted["report"]["auxiliary_gradient_norm_max"].values())
    for name in ("trigger_boundary.weight", "trigger_modality.weight", "actor_boundary.weight"):
        assert fitted["checkpoint"]["model_state"][name] != cp["model_state"][name]
    decoder = grounded.GroundedSpanDecoder(fitted["checkpoint"])
    records, _ = grounded._splits(examples(), [])
    args = span._batch(torch, records)
    with torch.no_grad():
        enabled = decoder.model(*args)
        disabled = decoder.model(*args, enabled=False)
        assert not torch.equal(enabled["modality"], disabled["modality"])
        assert not torch.equal(enabled["start"][:, 0], disabled["start"][:, 0])
        assert torch.equal(enabled["presence"], disabled["presence"])
        assert torch.equal(enabled["start"][:, 1:], disabled["start"][:, 1:])
        decoder.model.trigger_boundary.weight.mul_(-10)
        changed = decoder.model(*args)
        assert not torch.equal(enabled["trigger_attention"], changed["trigger_attention"])
        assert not torch.equal(enabled["modality"], changed["modality"])


def test_attention_masks_padding_and_reports_bounded_source_offsets(parent):
    decoder = grounded.GroundedSpanDecoder(checkpoint(parent))
    records, _ = grounded._splits(examples(), [])
    with torch.no_grad():
        output = decoder.model(*span._batch(torch, records))
    assert torch.allclose(output["trigger_attention"].sum(1), torch.ones(3))
    for i, row in enumerate(records):
        assert not torch.count_nonzero(output["trigger_attention"][i, len(row["tokens"]):])
    texts = [row["source_text"] for row in examples()]
    result = decoder.decode_formal_logic(texts)
    for text, row in zip(texts, result["rows"]):
        detail = row["grounding_diagnostics"]
        cue = detail["trigger"]
        assert text[cue["char_start"]:cue["char_end"]] == cue["text"]
        assert detail["trigger_residual_enabled"] is True
        assert row["target_access"] is row["teacher_forcing"] is False
    assert all(row["grounding_diagnostics"]["trigger_residual_enabled"] is False
               for row in decoder.decode_formal_logic(texts, trigger_ablation="disabled")["rows"])


def test_roundtrip_inference_owns_checkpoint_and_rejects_live_model_mutation(parent, tmp_path):
    fitted = grounded.train_decoder(checkpoint(parent), examples(), max_steps=2, max_seconds=30)["checkpoint"]
    receipt = grounded.save_checkpoint(fitted, tmp_path / "grounded.json")
    restored = grounded.load_checkpoint(receipt["path"], expected_sha256=receipt["sha256"])
    decoder = grounded.GroundedSpanDecoder(restored)
    text = ["A new agency may inspect records."]
    expected = decoder.decode_formal_logic(text)
    assert expected == grounded.GroundedSpanDecoder(fitted).decode_formal_logic(text)
    restored["config"]["trigger_enabled"] = False
    returned = decoder.checkpoint
    returned["config"]["trigger_enabled"] = False
    assert decoder.decode_formal_logic(text) == expected
    with torch.no_grad():
        decoder.model.trigger_modality.bias.add_(1)
    with pytest.raises(ValueError, match="model state changed"):
        decoder.decode_formal_logic(text)


@pytest.mark.parametrize("mutation,match", [
    (lambda row: row["trigger_span"].__setitem__(0, 1), "align"),
    (lambda row: row.update(trigger_span=row["facet_spans"]["actor"]), "overlaps"),
    (lambda row: row["facet_spans"].update(actor=row["facet_spans"]["action"]), "differs"),
    (lambda row: row["facet_spans"].update(conditions=[0, 4]), "absent"),
    (lambda row: row.update(trigger_span=[True, 6]), "invalid"),
    (lambda row: row.update(target_hint="must"), "closed"),
])
def test_annotation_alignment_is_checked_even_in_control(parent, mutation, match):
    rows = examples()
    mutation(rows[0])
    with pytest.raises(ValueError, match=match):
        grounded.build_checkpoint(parent, rows, trigger_enabled=False)


@pytest.mark.parametrize("mutation,match", [
    (lambda cp: cp.update(qualified=True), "authority"),
    (lambda cp: cp.update(initial_source_model_sha256="a" * 64), "weight boundary"),
    (lambda cp: cp["model_state"]["actor_boundary.bias"].__setitem__(0, .1), "zero-update"),
    (lambda cp: cp["progress"].update(row_cursor=True), "progress"),
    (lambda cp: cp["implementation"].update(grounding_sha256="a" * 64), "source drift"),
    (lambda cp: cp["config"].update(trigger_enabled=1), "boolean"),
    (lambda cp: cp["config"].update(trigger_loss_weight=float("nan")), "JSON compliant|weights"),
])
def test_corrupt_checkpoint_is_rejected(parent, mutation, match):
    cp = checkpoint(parent)
    mutation(cp)
    with pytest.raises(ValueError, match=match):
        grounded.validate_checkpoint(cp)


def test_noop_resume_data_swaps_and_target_free_signature(parent):
    cp = checkpoint(parent)
    result = grounded.train_decoder(cp, examples(), max_steps=0, max_seconds=0)
    assert result["checkpoint"] == cp
    rows = examples()
    rows[0]["trigger_span"][1] -= 1
    with pytest.raises(ValueError, match="manifests differ"):
        grounded.train_decoder(cp, rows, max_steps=1)
    decoder = grounded.GroundedSpanDecoder(cp)
    with pytest.raises(TypeError):
        decoder.decode_formal_logic(["Source only."], trigger_span=[0, 6])
    with pytest.raises(ValueError, match="ablation"):
        decoder.decode_formal_logic(["Source only."], trigger_ablation="repair")


def test_explicit_coordinates_support_repeated_actors_and_modal_words_in_names(parent):
    text = "May Trust must retain books when May Trust is audited."
    row = {"id": "repeated-actor", "source_text": text,
        "canonical_ir": {"rules": [{"actor": "May Trust", "modality": "O", "action": "retain",
            "object": "books", "conditions": ["when May Trust is audited"], "exceptions": [], "temporal": []}]},
        "trigger_span": [10, 14],
        "facet_spans": {"actor": [0, 9], "action": [15, 21], "object": [22, 27],
                        "conditions": [28, 53], "exceptions": None, "temporal": None}}
    # Legacy substring resolution cannot choose either actor occurrence.
    with pytest.raises(ValueError, match="ambiguous"):
        span._records(plain([row]), 0)
    records, _ = grounded._splits([row], [])
    assert records[0]["labels"]["spans"][0] == (0, 1)
    assert records[0]["trigger_span"] == (2, 2)
    grounded.validate_checkpoint(grounded.build_checkpoint(parent, [row]))
    wrong = deepcopy(row)
    wrong["facet_spans"]["actor"] = [33, 42]
    with pytest.raises(ValueError, match="overlap"):
        grounded._splits([wrong], [])


def test_train_tuning_overlap_and_untrained_or_context_parent_rejected(parent):
    with pytest.raises(ValueError, match="overlap"):
        grounded.build_checkpoint(parent, examples(), examples())
    original = span.build_checkpoint(plain(), latent_dimension=0, hidden_size=8, embedding_dim=4, projection_width=4)
    with pytest.raises(ValueError, match="closed grounding|closed dimensional"):
        grounded.build_checkpoint(original, examples())


def test_hash_storage_is_exclusive_and_rejects_duplicate_keys(parent, tmp_path):
    cp = checkpoint(parent)
    path = tmp_path / "checkpoint.json"
    receipt = grounded.save_checkpoint(cp, path)
    with pytest.raises(FileExistsError):
        grounded.save_checkpoint(cp, path)
    raw = '{"schema":"bad",' + json.dumps(cp)[1:]
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(raw)
    with pytest.raises(ValueError, match="duplicate"):
        grounded.load_checkpoint(duplicate, expected_sha256=hashlib.sha256(raw.encode()).hexdigest())
    with pytest.raises(ValueError, match="hash differs"):
        grounded.load_checkpoint(receipt["path"], expected_sha256="0" * 64)
