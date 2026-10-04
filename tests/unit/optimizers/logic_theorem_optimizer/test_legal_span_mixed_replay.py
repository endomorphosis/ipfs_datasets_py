"""Synthetic numerical checks only; none establish accuracy on statutes."""
from copy import deepcopy
import hashlib
import json

import pytest
import torch

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_formula as span
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_dimensions as dims
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_grounding as grounded
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_mixed_replay as mixed


def examples(counts=(7, 11), prefix="fit"):
    rows = []
    for domain, count in zip(mixed.DOMAINS, counts):
        for index in range(count):
            actor = f"{prefix} {domain} Office {index}"
            cue, modality = (("must", "O"), ("may", "P"), ("must not", "F"))[index % 3]
            text = f"{actor} {cue} retain books"
            condition = " when inspected" if domain == "new" and index % 2 else ""
            text += condition + "."
            starts = {word: text.index(word) for word in ("retain", "books")}
            rows.append({"id": f"{prefix}-{domain}-{index}", "domain": domain,
                "trigger_supervised": domain == "new", "source_text": text,
                "canonical_ir": {"rules": [{"actor": actor, "modality": modality,
                    "action": "retain", "object": "books", "conditions": [condition.strip()] if condition else [],
                    "exceptions": [], "temporal": []}]},
                "facet_spans": {"actor": [0, len(actor)], "action": [starts["retain"], starts["retain"] + 6],
                    "object": [starts["books"], starts["books"] + 5], "conditions":
                    [text.index("when"), len(text) - 1] if condition else None, "exceptions": None, "temporal": None},
                "trigger_span": [len(actor) + 1, len(actor) + 1 + len(cue)] if domain == "new" else None})
    return rows


def plain(rows):
    return [{key: row[key] for key in ("id", "source_text", "canonical_ir")} for row in rows]


@pytest.fixture(scope="module", autouse=True)
def threads():
    before = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(before)


@pytest.fixture(scope="module")
def parent():
    data = plain(examples())
    base = span.build_checkpoint(data, latent_dimension=0, latent_enabled=False,
        hidden_size=8, embedding_dim=4, projection_width=4, batch_size=12)
    first = span.train_decoder(base, data, max_steps=2, max_seconds=30)["checkpoint"]
    child = dims.build_checkpoint(first, data, latent_dimension=0, batch_size=12)
    return dims.train_decoder(child, data, max_steps=2, max_seconds=30)["checkpoint"]


def checkpoint(parent, enabled=True):
    return mixed.build_checkpoint(parent, examples(), trigger_enabled=enabled)


@pytest.mark.parametrize("enabled", [False, True])
def test_initial_logits_match_frozen_grounded_and_source_parent(parent, enabled):
    cp = checkpoint(parent, enabled)
    fresh = mixed.MixedReplayDecoder(cp)
    original = dims.DimensionalSpanDecoder(parent)
    records, _ = mixed._splits(examples(), [])
    with torch.no_grad():
        a = fresh.model(*span._batch(torch, records))
        b = original.model(*span._batch(torch, records))
    assert all(torch.equal(a[key], value) for key, value in b.items())
    assert mixed._model is grounded._model
    assert mixed._source_state(cp["model_state"]) == parent["model_state"]
    assert mixed.initial_source_model_digest(cp) == span.checkpoint_digest(parent["model_state"])
    assert mixed.initial_model_digest(cp) == span.checkpoint_digest(cp["model_state"])
    assert cp["optimizer_state"]["parameters"] == {}
    texts = [row["source_text"] for row in examples()[:4]]
    expected = original.decode_formal_logic(texts)["rows"]
    actual = fresh.decode_formal_logic(texts)["rows"]
    for first, second in zip(expected, actual):
        assert {k: v for k, v in second.items() if k != "grounding_diagnostics"} == first


@pytest.mark.parametrize("enabled", [False, True])
def test_resume_preserves_independent_pool_wraps_adam_losses_and_exposures(parent, enabled):
    cp = checkpoint(parent, enabled)
    full = mixed.train_decoder(cp, examples(), max_steps=8, max_seconds=30)
    first = mixed.train_decoder(cp, examples(), max_steps=3, max_seconds=30)
    second = mixed.train_decoder(first["checkpoint"], examples(), max_steps=5, max_seconds=30)
    for key in ("model_state", "optimizer_state", "progress"):
        assert full["checkpoint"][key] == second["checkpoint"][key]
    for key in ("batch_losses", "batch_loss_components", "batch_exposures"):
        assert full["report"][key] == first["report"][key] + second["report"][key]
    progress = full["checkpoint"]["progress"]
    assert (progress["pools"]["earlier"]["epochs_completed"], progress["pools"]["earlier"]["row_cursor"]) == (6, 6)
    assert (progress["pools"]["new"]["epochs_completed"], progress["pools"]["new"]["row_cursor"]) == (4, 4)
    assert full["report"]["domain_exposures"] == {"earlier": 48, "new": 48}
    assert mixed.optimizer_steps(second["checkpoint"]) == 8
    assert all(len(ids) == 6 for row in full["report"]["batch_exposures"] for ids in row["ids_by_domain"].values())


def test_control_matches_explicit_balanced_original_semantics_and_adam(parent):
    cp = checkpoint(parent, False)
    records, _ = mixed._splits(examples(), [])
    pools = {domain: [row for row in records if row["domain"] == domain] for domain in mixed.DOMAINS}
    baseline = span._model(torch, deepcopy(cp["config"]))
    baseline.load_state_dict({key: torch.tensor(value) for key, value in parent["model_state"].items()})
    optimizer = torch.optim.Adam(baseline.parameters(), lr=.001, foreach=False)
    progress, losses = deepcopy(cp["progress"]), []
    for _ in range(4):
        indices, progress = mixed.next_batch_indices(progress, cp["training_domain_counts"], cp["config"]["seed"])
        batch = [pools[domain][i] for domain in mixed.DOMAINS for i in indices[domain]]
        output = baseline(*span._batch(torch, batch))
        # One shared forward, then original seven-facet loss per domain. Optional
        # facet presence differs across the two deliberately heterogeneous pools.
        domain_losses = []
        for domain in mixed.DOMAINS:
            positions = [i for i, row in enumerate(batch) if row["domain"] == domain]
            selected = {key: value[positions] for key, value in output.items()}
            domain_losses.append(span._loss(torch, lambda *_: selected, [batch[i] for i in positions]))
        loss = sum(domain_losses) / 2
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(list(baseline.parameters()), 5, error_if_nonfinite=True)
        optimizer.step()
        losses.append(float(loss.detach()))
    expected_weights, expected_moments = span._pack(baseline, optimizer)
    result = mixed.train_decoder(cp, examples(), max_steps=4, max_seconds=30)
    actual = result["checkpoint"]
    assert mixed._source_state(actual["model_state"]) == expected_weights
    assert mixed._source_state(actual["optimizer_state"]["parameters"]) == expected_moments["parameters"]
    assert result["report"]["batch_losses"] == losses
    assert all(value == 0. for value in result["report"]["auxiliary_gradient_norm_max"].values())
    for name in cp["model_state"]:
        if name.startswith(mixed._EXTRA):
            assert actual["model_state"][name] == cp["model_state"][name]
            assert not torch.count_nonzero(torch.tensor(actual["optimizer_state"]["parameters"][name]["exp_avg"]))


def test_loss_uses_only_supervised_new_trigger_labels(parent):
    cp = checkpoint(parent)
    decoder = mixed.MixedReplayDecoder(cp)
    records, _ = mixed._splits(examples(), [])
    loss, parts = mixed._loss(torch, decoder.model, records, cp["config"])
    output = decoder.model(*span._batch(torch, records))
    indices = [i for i, row in enumerate(records) if row["trigger_supervised"]]
    targets = torch.tensor([records[i]["trigger_span"] for i in indices])
    ce = torch.nn.functional.cross_entropy
    expected = (ce(output["trigger_boundary"][indices, 0], targets[:, 0]) +
                ce(output["trigger_boundary"][indices, 1], targets[:, 1])) * .5
    assert torch.equal(parts["trigger"], expected)
    assert torch.equal(parts["semantic"], (parts["semantic_earlier"] + parts["semantic_new"]) / 2)
    assert torch.equal(parts["actor"], (parts["actor_earlier"] + parts["actor_new"]) / 2)
    assert torch.equal(loss, parts["semantic"] + .25 * parts["trigger"] + .25 * parts["actor"])
    assert all(row["trigger_span"] is None for row in records if row["domain"] == "earlier")
    trained = mixed.train_decoder(cp, examples(), max_steps=3, max_seconds=30)
    assert all(value > 0 for value in trained["report"]["auxiliary_gradient_norm_max"].values())
    for batch in trained["report"]["batch_loss_components"]:
        assert batch["domain_rows"] == {"earlier": 6, "new": 6}
        assert batch["supervised_trigger_rows"] == batch["trigger_loss_rows"] == 6


def test_tuning_is_separate_by_domain_and_does_not_change_fit(parent):
    tuning = examples((3, 5), "tune")
    cp = mixed.build_checkpoint(parent, examples(), tuning)
    result = mixed.train_decoder(cp, examples(), tuning, max_steps=2, max_seconds=30)
    plain = mixed.train_decoder(checkpoint(parent), examples(), max_steps=2, max_seconds=30)
    for key in ("model_state", "optimizer_state", "progress"):
        assert result["checkpoint"][key] == plain["checkpoint"][key]
    reports = result["report"]["tuning_by_domain"]
    assert [reports[domain]["rows_evaluated"] for domain in mixed.DOMAINS] == [3, 5]
    assert all(row["complete"] and row["used_for_fit_or_selection"] is False for row in reports.values())


def test_inference_snapshot_owns_values_no_deepcopy_per_source_and_checks_mutations(parent, monkeypatch):
    fitted = mixed.train_decoder(checkpoint(parent), examples(), max_steps=2, max_seconds=30)["checkpoint"]
    decoder = mixed.MixedReplayDecoder(fitted)
    text = ["A new agency may inspect records."]
    expected = decoder.decode_formal_logic(text)
    fitted["config"]["trigger_enabled"] = False
    returned = decoder.checkpoint
    returned["config"]["trigger_enabled"] = False
    with pytest.raises(TypeError):
        decoder._inference_config["config"]["trigger_enabled"] = False
    with monkeypatch.context() as patch:
        patch.setattr(mixed.copy, "deepcopy", lambda *_: (_ for _ in ()).throw(AssertionError("inference copied checkpoint")))
        assert decoder.decode_formal_logic(text) == expected
    with torch.no_grad():
        decoder.model.trigger_modality.bias.add_(1)
    with pytest.raises(ValueError, match="model state changed"):
        decoder.decode_formal_logic(text)


def test_changed_snapshot_and_changed_state_during_inference_are_rejected(parent):
    decoder = mixed.MixedReplayDecoder(checkpoint(parent))
    decoder._inference_view._checkpoint = {"config": {"trigger_enabled": False, "latent_enabled": False}}
    with pytest.raises(ValueError, match="snapshot changed"):
        decoder.decode_formal_logic(["An office may retain files."])
    decoder = mixed.MixedReplayDecoder(checkpoint(parent))
    def mutate(module, inputs, output):
        with torch.no_grad():
            module.trigger_modality.bias.add_(1)
    handle = decoder.model.register_forward_hook(mutate)
    with pytest.raises(ValueError, match="model state changed"):
        decoder.decode_formal_logic(["An office may retain files."])
    handle.remove()


@pytest.mark.parametrize("mutate,match", [
    (lambda r: r.update(trigger_span=[0, 3]), "masked"),
    (lambda r: r.update(trigger_supervised=True), "masked"),
    (lambda r: r.update(domain="other"), "domain"),
    (lambda r: r.update(trigger_supervised=0), "boolean"),
    (lambda r: r.update(target_hint="may"), "closed"),
    (lambda r: r["facet_spans"].update(actor=r["facet_spans"]["action"]), "differs"),
])
def test_earlier_annotations_are_checked_in_control(parent, mutate, match):
    rows = examples()
    mutate(rows[0])
    with pytest.raises(ValueError, match=match):
        mixed.build_checkpoint(parent, rows, trigger_enabled=False)


@pytest.mark.parametrize("mutate,match", [
    (lambda r: r.update(trigger_span=None), "annotated"),
    (lambda r: r.update(trigger_supervised=False), "annotated"),
    (lambda r: r.update(trigger_span=r["facet_spans"]["actor"]), "overlaps"),
    (lambda r: r["trigger_span"].__setitem__(0, 1), "align"),
])
def test_new_annotations_are_required_and_exact(parent, mutate, match):
    rows = examples()
    mutate(rows[7])
    with pytest.raises(ValueError, match=match):
        mixed.build_checkpoint(parent, rows)


@pytest.mark.parametrize("mutate,match", [
    (lambda cp: cp.update(qualified=True), "authority"),
    (lambda cp: cp.update(initial_source_model_sha256="a" * 64), "weight boundary"),
    (lambda cp: cp["model_state"]["actor_boundary.bias"].__setitem__(0, .1), "zero-update"),
    (lambda cp: cp["progress"].update(optimizer_steps=True), "progress"),
    (lambda cp: cp["progress"]["pools"]["earlier"].update(row_cursor=1), "cursor"),
    (lambda cp: cp["progress"]["pools"]["new"]["shuffle_order"].reverse(), "shuffle"),
    (lambda cp: cp["progress"]["pools"]["new"]["shuffle_order"].__setitem__(0, True), "shuffle"),
    (lambda cp: cp["implementation"].update(mixed_replay_sha256="a" * 64), "source drift"),
    (lambda cp: cp["config"].update(trigger_enabled=1), "boolean"),
    (lambda cp: cp["config"].update(batch_size=6), "exactly 12"),
    (lambda cp: cp["training_domain_counts"].update(earlier=8), "domain counts"),
])
def test_checkpoint_corruption_rejected(parent, mutate, match):
    cp = checkpoint(parent)
    mutate(cp)
    with pytest.raises(ValueError, match=match):
        mixed.validate_checkpoint(cp)


def test_coordinates_support_repeated_names_without_string_search(parent):
    rows = examples()
    text = "May Trust must retain books when May Trust is audited."
    rows[0] = {"id": "repeated-actor", "source_text": text, "domain": "earlier",
        "trigger_span": None, "trigger_supervised": False,
        "canonical_ir": {"rules": [{"actor": "May Trust", "modality": "O", "action": "retain",
            "object": "books", "conditions": ["when May Trust is audited"], "exceptions": [], "temporal": []}]},
        "facet_spans": {"actor": [0, 9], "action": [15, 21], "object": [22, 27],
                        "conditions": [28, 53], "exceptions": None, "temporal": None}}
    records, _ = mixed._splits(rows, [])
    assert records[0]["labels"]["spans"][0] == (0, 1)
    assert records[0]["trigger_span"] is None
    mixed.validate_checkpoint(mixed.build_checkpoint(parent, rows))
    rows[0]["facet_spans"]["actor"] = [33, 42]
    with pytest.raises(ValueError, match="overlap"):
        mixed._splits(rows, [])


def test_noop_bounds_manifest_swaps_and_no_inference_target_parameters(parent):
    cp = checkpoint(parent)
    assert mixed.train_decoder(cp, examples(), max_steps=0, max_seconds=0)["checkpoint"] == cp
    rows = examples()
    rows[0]["id"] = "changed"
    with pytest.raises(ValueError, match="manifests differ"):
        mixed.train_decoder(cp, rows, max_steps=1)
    with pytest.raises(ValueError, match="overlap"):
        mixed.build_checkpoint(parent, examples(), examples())
    with pytest.raises(ValueError, match="at least six"):
        mixed.build_checkpoint(parent, examples((5, 8)))
    with pytest.raises(ValueError, match="0..800"):
        mixed.train_decoder(cp, examples(), max_steps=801)
    decoder = mixed.MixedReplayDecoder(cp)
    with pytest.raises(TypeError):
        decoder.decode_formal_logic(["Source only."], trigger_span=[0, 6])
    with pytest.raises(ValueError, match="ablation"):
        decoder.decode_formal_logic(["Source only."], trigger_ablation="repair")


def test_hash_storage_roundtrip_exclusive_and_duplicate_json_rejection(parent, tmp_path):
    cp = mixed.train_decoder(checkpoint(parent), examples(), max_steps=2, max_seconds=30)["checkpoint"]
    path = tmp_path / "checkpoint.json"
    receipt = mixed.save_checkpoint(cp, path)
    assert mixed.load_checkpoint(path, expected_sha256=receipt["sha256"]) == cp
    with pytest.raises(FileExistsError):
        mixed.save_checkpoint(cp, path)
    raw = '{"schema":"bad",' + json.dumps(cp)[1:]
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(raw)
    with pytest.raises(ValueError, match="duplicate"):
        mixed.load_checkpoint(duplicate, expected_sha256=hashlib.sha256(raw.encode()).hexdigest())
    with pytest.raises(ValueError, match="hash differs"):
        mixed.load_checkpoint(path, expected_sha256="0" * 64)
