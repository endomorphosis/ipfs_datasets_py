"""Numerical and isolation checks; synthetic examples imply no statutory accuracy."""
from copy import deepcopy
import json

import pytest
import torch

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_formula as span
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_dimensions as dims
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_mixed_replay as mixed
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consistency as runtime


def rows_and_pairs(prefix="fit"):
    rows, pairs = [], []
    def row(identifier, actor, domain, index, front=False):
        cue, modality = (("must", "O"), ("may", "P"), ("must not", "F"))[index % 3]
        condition = "inspectors arrive" if index % 2 else ""
        core = f"{actor} {cue} retain books"
        text = ((f"When {condition}, {core}" if condition else "Under this rule, " + core) if front
                else core + (f" when {condition}" if condition else "")) + "."
        atoms = {"actor": actor, "action": "retain", "object": "books", "conditions": condition,
                 "exceptions": "", "temporal": ""}
        return {"id": identifier, "source_text": text, "domain": domain, "trigger_supervised": domain == "new",
            "trigger_span": [text.index(cue), text.index(cue) + len(cue)] if domain == "new" else None,
            "canonical_ir": {"rules": [{"modality": modality, **{k: ([v] if v else []) if k in span.codec_module.QUALIFIERS else v
                                                                    for k, v in atoms.items()}}]},
            "facet_spans": {k: [text.index(v), text.index(v) + len(v)] if v else None for k, v in atoms.items()}}
    for domain, count in (("earlier", 7), ("new", 7)):
        rows.extend(row(f"{prefix}-{domain}-{i}", f"{prefix} {domain} Office {i}", domain, i) for i in range(count))
    for i in range(7):
        ids = [f"{prefix}-pair-{i}-{side}" for side in range(2)]
        rows.extend(row(identifier, f"{prefix} paired Office {i}", "new", i, bool(side)) for side, identifier in enumerate(ids))
        pairs.append(ids)
    return rows, pairs


@pytest.fixture(scope="module", autouse=True)
def threads():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


@pytest.fixture(scope="module")
def parent():
    rows, _ = rows_and_pairs("parent")
    plain = [{k: r[k] for k in ("id", "source_text", "canonical_ir")} for r in rows]
    cp = span.build_checkpoint(plain, latent_dimension=0, latent_enabled=False,
        hidden_size=8, embedding_dim=4, projection_width=4, batch_size=12)
    cp = span.train_decoder(cp, plain, max_steps=1, max_seconds=30)["checkpoint"]
    cp = dims.build_checkpoint(cp, plain, latent_dimension=0, batch_size=12)
    cp = dims.train_decoder(cp, plain, max_steps=1, max_seconds=30)["checkpoint"]
    return {enabled: mixed.train_decoder(mixed.build_checkpoint(cp, rows, trigger_enabled=enabled), rows,
              max_steps=1, max_seconds=30)["checkpoint"] for enabled in (False, True)}


def checkpoint(parent, objective="consistency", enabled=True):
    rows, pairs = rows_and_pairs()
    return runtime.build_checkpoint(parent[enabled], rows, [], pairs, objective=objective, seed=1729)


@pytest.mark.parametrize("enabled", [False, True])
def test_initial_inference_equals_trained_parent_and_owns_snapshot(parent, enabled):
    cp = checkpoint(parent, enabled=enabled)
    decoder = runtime.ConsistencyDecoder(cp)
    texts = [r["source_text"] for r in rows_and_pairs()[0][-6:]]
    expected = mixed.MixedReplayDecoder(parent[enabled]).decode_formal_logic(texts)["rows"]
    assert decoder.decode_formal_logic(texts)["rows"] == expected
    assert cp["model_state"] == parent[enabled]["model_state"]
    assert cp["optimizer_state"]["parameters"] == {}
    cp["model_state"] = {}
    owned = decoder.checkpoint
    owned["model_state"] = {}
    assert decoder.decode_formal_logic(texts)["rows"] == expected
    with torch.no_grad():
        next(decoder.model.parameters()).add_(1)
    with pytest.raises(ValueError, match="model state changed"):
        decoder.decode_formal_logic(texts)


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("objective", ["ce", "consistency"])
def test_resume_reproduces_losses_moments_and_pair_order(parent, enabled, objective):
    cp = checkpoint(parent, objective, enabled)
    rows, pairs = rows_and_pairs()
    full = runtime.train_decoder(cp, rows, [], pairs, max_steps=5, max_seconds=30)
    first = runtime.train_decoder(cp, rows, [], pairs, max_steps=2, max_seconds=30)
    resumed = runtime.train_decoder(first["checkpoint"], rows, [], pairs, max_steps=3, max_seconds=30)
    for key in ("model_state", "optimizer_state", "progress"):
        assert full["checkpoint"][key] == resumed["checkpoint"][key]
    for key in ("batch_losses", "batch_loss_components", "batch_exposures"):
        assert full["report"][key] == first["report"][key] + resumed["report"][key]
    assert runtime.optimizer_steps(resumed["checkpoint"]) == 5
    for part in full["report"]["batch_loss_components"]:
        assert part["total"] == pytest.approx(part["base_ce"] + (.25 if objective == "consistency" else 0) * part["consistency_js"], abs=1e-6)
    if not enabled:
        assert all(v == 0 for v in full["report"]["auxiliary_gradient_norm_max"].values())
        assert all(full["checkpoint"]["model_state"][k] == cp["model_state"][k] for k in cp["model_state"] if k.startswith(mixed._EXTRA))


def test_objectives_share_batches_and_ce_matches_frozen_base(parent):
    rows, pairs = rows_and_pairs()
    ce_cp, js_cp = checkpoint(parent, "ce"), checkpoint(parent, "consistency")
    ce_result = runtime.train_decoder(ce_cp, rows, [], pairs, max_steps=2, max_seconds=30)
    js_result = runtime.train_decoder(js_cp, rows, [], pairs, max_steps=2, max_seconds=30)
    assert ce_result["report"]["batch_exposures"] == js_result["report"]["batch_exposures"]
    parsed, _ = mixed._splits(rows, [])
    by_id = {r["id"]: r for r in parsed}
    batch = [by_id[i] for i in ce_result["report"]["batch_exposures"][0]["ids"]]
    _, model, _ = runtime._restore(ce_cp)
    actual, parts = runtime._loss(torch, model, batch, ce_cp["model_config"], "ce")
    expected, _ = mixed._loss(torch, model, batch, ce_cp["model_config"])
    assert torch.equal(actual, expected)
    assert parts["weighted_consistency"].item() == 0


def test_role_projection_aligns_permutations_and_keeps_gradients():
    rows, pairs = rows_and_pairs()
    records, _ = mixed._splits(rows, [])
    records = {r["id"]: r for r in records}
    a, b = (records[i] for i in pairs[1])
    def logits(record, favored):
        roles = runtime._role_buckets(torch, record)
        sizes = torch.bincount(roles, minlength=8)
        weights = torch.arange(1., 9.)
        weights[favored] += 9
        # Allocate a fixed amount of probability per role, independent of its token count.
        return (weights[roles] / sizes[roles]).log().requires_grad_()
    x, y = logits(a, 0), logits(b, 0)
    p, q = runtime._project(torch, x, a), runtime._project(torch, y, b)
    assert torch.allclose(p, q, atol=1e-7)
    assert abs(runtime._js(torch, p, q).item()) < 1e-7
    y = logits(b, 1)
    loss = runtime._js(torch, p, runtime._project(torch, y, b))
    assert loss.item() > 0
    loss.backward()
    assert x.grad is not None and torch.isfinite(x.grad).all() and x.grad.abs().sum() > 0
    assert y.grad is not None and torch.isfinite(y.grad).all() and y.grad.abs().sum() > 0


def test_absent_endpoints_do_not_enter_consistency():
    rows, pairs = rows_and_pairs()
    records, _ = mixed._splits(rows, [])
    by_id = {r["id"]: r for r in records}
    pair = [by_id[i] for i in pairs[0]]
    length = max(len(r["tokens"]) for r in pair)
    output = {"modality": torch.zeros(2, 3), "presence": torch.zeros(2, 4, 2),
              "start": torch.zeros(2, 6, length), "end": torch.zeros(2, 6, length)}
    loss, parts = runtime._consistency_loss(torch, output, pair, [(0, 1)])
    changed = {k: v.clone() for k, v in output.items()}
    changed["start"][0, 3:, 0] = 50
    changed["end"][1, 3:, -1] = 50
    actual, _ = runtime._consistency_loss(torch, changed, pair, [(0, 1)])
    assert torch.equal(loss, actual)
    changed["presence"][1, 2, 1] = 50
    actual, changed_parts = runtime._consistency_loss(torch, changed, pair, [(0, 1)])
    assert actual > loss and changed_parts["js_presence"] > parts["js_presence"]


def test_semantic_mismatch_duplicate_and_cross_domain_pairs_rejected(parent):
    rows, pairs = rows_and_pairs()
    bad = deepcopy(rows)
    bad[-1]["canonical_ir"]["rules"][0]["modality"] = "P"
    with pytest.raises(ValueError, match="canonical meanings"):
        runtime.build_checkpoint(parent[True], bad, [], pairs, objective="ce", seed=1729)
    with pytest.raises(ValueError, match="unique"):
        runtime.build_checkpoint(parent[True], rows, [], [pairs[0]] + pairs, objective="ce", seed=1729)
    bad_pairs = deepcopy(pairs)
    bad_pairs[0][0] = rows[0]["id"]
    with pytest.raises(ValueError, match="annotated new"):
        runtime.build_checkpoint(parent[True], rows, [], bad_pairs, objective="ce", seed=1729)


def test_save_load_pins_moments_progress_and_manifests(parent, tmp_path):
    rows, pairs = rows_and_pairs()
    cp = runtime.train_decoder(checkpoint(parent), rows, [], pairs, max_steps=1, max_seconds=30)["checkpoint"]
    ref = runtime.save_checkpoint(cp, tmp_path / "checkpoint.json")
    assert runtime.load_checkpoint(ref["path"], expected_sha256=ref["sha256"]) == cp
    with pytest.raises(FileExistsError):
        runtime.save_checkpoint(cp, ref["path"])
    with pytest.raises(ValueError, match="hash differs"):
        runtime.load_checkpoint(ref["path"], expected_sha256="0" * 64)
    for key, mutate in (("progress", lambda v: v["pools"]["pairs"].update(row_cursor=0)),
                        ("training_config", lambda v: v.update(consistency_weight=.5)),
                        ("model_config", lambda v: v.update(trigger_enabled=False))):
        bad = deepcopy(cp)
        mutate(bad[key])
        with pytest.raises(ValueError):
            runtime.validate_checkpoint(bad)
    bad = deepcopy(cp)
    next(iter(bad["optimizer_state"]["parameters"].values()))["step"] = 0
    with pytest.raises(ValueError, match="step differs"):
        runtime.validate_checkpoint(bad)
    with pytest.raises(ValueError, match="manifest"):
        runtime.train_decoder(cp, rows, [], list(reversed(pairs)), max_steps=1)
    with pytest.raises(ValueError, match="budget"):
        runtime.train_decoder(cp, rows, [], pairs, max_steps=800)
