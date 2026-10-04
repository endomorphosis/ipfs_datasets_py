"""Learned copying, training isolation, exact resumption, and bounded schema tests."""
import copy
import hashlib
import importlib
import json

import pytest

torch = pytest.importorskip("torch")
span = importlib.import_module("ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_span_formula")


def examples(dimension=0):
    result = []
    for index, (marker, modality) in enumerate((("shall", "O"), ("may", "P"), ("shall not", "F"))):
        for qualifier in (False, True):
            text = "The agency " + marker + " disclose records" + (" unless exempt" if qualifier else "") + "."
            row = {"id": str(index) + str(qualifier), "source_text": text,
                   "canonical_ir": {"rules": [{"modality": modality, "actor": "agency", "action": "disclose",
                     "object": "records", "conditions": [], "exceptions": ["exempt"] if qualifier else [], "temporal": []}]}}
            if dimension:
                row["latent"] = [float(i == index) for i in range(dimension)]
            result.append(row)
    return result


@pytest.fixture(scope="module", autouse=True)
def threads():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


def initial(dimension=0, **options):
    return span.build_checkpoint(examples(dimension), latent_dimension=dimension,
        batch_size=3, hidden_size=16, embedding_dim=8, projection_width=8, seed=23, **options)


def test_exact_unicode_offsets_and_unseen_bytes_need_no_vocabulary():
    text = "The Łódź committee shall disclose résumé Ω-17."
    tokens = span.tokenize_source(text)
    assert all(text[token["start"]:token["end"]] == token["text"] for token in tokens)
    assert next(token for token in tokens if token["text"] == "Łódź")["byte_ids"] == [v + 1 for v in "łódź".encode()]
    assert next(token for token in tokens if token["text"] == "Ω")["byte_ids"] == [v + 1 for v in "ω".encode()]
    assert all(1 <= value <= 256 for token in tokens for value in token["byte_ids"])


@pytest.mark.parametrize("dimension", [0, 384])
def test_real_parameter_updates_and_exact_optimizer_resumption(dimension):
    checkpoint = initial(dimension)
    before = copy.deepcopy(checkpoint)
    whole = span.train_decoder(checkpoint, examples(dimension), max_steps=6)
    first = span.train_decoder(checkpoint, examples(dimension), max_steps=3)
    resumed = span.train_decoder(first["checkpoint"], examples(dimension), max_steps=3)
    assert checkpoint == before
    assert whole["report"]["optimizer_steps"] == 6
    names = whole["report"]["changed_parameter_names"]
    assert "byte_embedding.weight" in names and "encoder.weight_ih_l0_reverse" in names
    assert "start.weight" in names and "end.weight" in names and "presence.weight" in names
    if dimension:
        assert "latent_up.weight" in names and "latent_down.weight" in names
    for field in ("model_state", "optimizer_state", "progress"):
        assert whole["checkpoint"][field] == resumed["checkpoint"][field]
    span.validate_checkpoint(whole["checkpoint"])


def test_disabled_context_has_identical_initial_weights_and_zero_context_updates():
    enabled = initial(384)
    disabled = initial(384, latent_enabled=False)
    assert enabled["model_state"] == disabled["model_state"]
    result = span.train_decoder(disabled, examples(384), max_steps=4)
    assert not any(name.startswith("latent_") for name in result["report"]["changed_parameter_names"])
    decoder = span.SpanLegalFormulaDecoder(result["checkpoint"])
    texts = [row["source_text"] for row in examples(384)]
    vectors = [row["latent"] for row in examples(384)]
    normal = decoder.decode_formal_logic(texts, vectors)
    zero = decoder.decode_formal_logic(texts, vectors, latent_ablation="zero")
    assert [row["canonical_ir"] for row in normal["rows"]] == [row["canonical_ir"] for row in zero["rows"]]
    assert all(row["latent_sha256"] == span.checkpoint_digest([0.] * 384) for row in zero["rows"])


def test_context_feature_scaling_changes_relative_pointer_probabilities():
    checkpoint = initial(384)
    _, model, _ = span._restore(checkpoint)
    records, _, _ = span._records(examples(384), 384)
    inputs = list(span._batch(torch, records[:1]))
    inputs[-1] = torch.zeros((1, 384))
    other_inputs = [*inputs[:-1], torch.ones((1, 384))]
    with torch.no_grad():
        initial_plain = model(*inputs, enabled=False)
        initial_context = model(*other_inputs)
        assert all(torch.equal(initial_plain[key], initial_context[key]) for key in initial_plain)
        # Simulate nonzero learned context parameters without relying on fitted
        # labels. This catches additive-only conditioning, whose constant token
        # shifts cancel exactly from the pointer probability distributions.
        model.latent_down.weight.fill_(.002)
        model.latent_down.bias.zero_()
        channels = torch.linspace(-.8, .8, model.latent_up.out_features)
        model.latent_up.weight.copy_(channels[:, None].expand_as(model.latent_up.weight))
        model.latent_up.bias.zero_()
        without_context = model(*inputs)
        with_context = model(*other_inputs)
        for key in ("start", "end"):
            probability_a = torch.softmax(without_context[key], dim=-1)
            probability_b = torch.softmax(with_context[key], dim=-1)
            assert float((probability_a - probability_b).abs().max()) > 1e-5
        disabled_a = model(*inputs, enabled=False)
        disabled_b = model(*other_inputs, enabled=False)
        assert all(torch.equal(disabled_a[key], disabled_b[key]) for key in disabled_a)


def _force_heads(decoder, *, overlap=False):
    """Controlled learned-head outputs test copying; this is not production extraction."""
    def fixed(byte_ids, byte_lengths, lengths, latent, *, enabled=True):
        length = int(lengths[0])
        start, end = torch.full((1, 6, length), -9.), torch.full((1, 6, length), -9.)
        # The Łódź committee shall disclose résumé Ω - 17 .
        for field, left, right in ((0, 1, 2), (1, 4, 4), (2, 5, 8), (3, 0, 0), (4, 0, 0), (5, 0, 0)):
            if overlap and field == 1:
                left, right = 1, 1
            start[0, field, left] = 9.
            end[0, field, right] = 9.
        return {"modality": torch.tensor([[8., -8., -8.]]),
                "presence": torch.tensor([[[-9., 9.], [9., -9.], [9., -9.], [9., -9.]]]),
                "start": start, "end": end}
    decoder.model.forward = fixed


def test_copy_output_exact_offsets_oov_unicode_and_no_target_access(monkeypatch):
    decoder = span.SpanLegalFormulaDecoder(initial())
    _force_heads(decoder)
    def forbidden(*args, **kwargs):
        raise AssertionError("inference touched target supervision or training")
    monkeypatch.setattr(span, "_labels", forbidden)
    monkeypatch.setattr(span, "train_decoder", forbidden)
    text = "The Łódź committee shall disclose résumé Ω-17."
    output = decoder.decode_formal_logic([text])
    row = output["rows"][0]
    assert row["status"] == "decoded"
    rule = row["canonical_ir"]["rules"][0]
    assert rule["actor"] == "Łódź committee" and rule["object"] == "résumé Ω-17"
    assert row["source_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    for field in ("actor", "action", "object"):
        diagnostic = row["span_diagnostics"]["facets"][field]
        assert text[diagnostic["char_start"]:diagnostic["char_end"]] == rule[field]
    assert not row["target_access"] and not row["teacher_forcing"]
    assert all(output[key] is False for key in span.FALSE)
    assert row["formal_outputs"][0]["payload"] == rule


def test_overlapping_copied_facets_abstain_with_explicit_diagnostics():
    decoder = span.SpanLegalFormulaDecoder(initial())
    _force_heads(decoder, overlap=True)
    row = decoder.decode_formal_logic(["The Łódź committee shall disclose résumé Ω-17."])["rows"][0]
    assert row["status"] == "abstained" and row["reason"] == "copied_spans_overlap"
    assert row["canonical_ir"] is None and not row["formal_outputs"]


@pytest.mark.parametrize("mutation,reason", [
    (lambda row: row["canonical_ir"]["rules"][0].update(exceptions=["exempt", "waived"]), "at most one"),
    (lambda row: row["canonical_ir"]["rules"][0].update(actor="municipality"), "not an exact"),
    (lambda row: row.update(source_text="The agency agency shall disclose records."), "ambiguous"),
    (lambda row: row["canonical_ir"]["rules"][0].update(action="agency"), "overlap"),
])
def test_unexpressible_training_targets_fail_closed_and_audit_reports(mutation, reason):
    rows = examples()[:1]
    mutation(rows[0])
    audit = span.audit_examples(rows)
    assert not audit["all_supported"] and reason in audit["rejected_rows"][0]["reason"]
    with pytest.raises(ValueError, match=reason):
        span.build_checkpoint(rows)


def test_long_texts_abstain_without_truncation_and_nonfinite_latents_reject():
    decoder = span.SpanLegalFormulaDecoder(initial())
    texts = ["x " * 257, "x" * 16385, "ø" * 1025]
    output = decoder.decode_formal_logic(texts)
    assert all(row["reason"] == "source_too_long" and row["canonical_ir"] is None for row in output["rows"])
    latent_decoder = span.SpanLegalFormulaDecoder(initial(384))
    for vector in ([0.] * 383, [float("nan")] * 384, [True] * 384):
        with pytest.raises(ValueError):
            latent_decoder.decode_formal_logic(["valid source"], [vector])


def test_no_examples_persisted_and_checkpoint_integrity(tmp_path):
    checkpoint = span.train_decoder(initial(), examples(), max_steps=2)["checkpoint"]
    encoded = json.dumps(checkpoint)
    assert "The agency" not in encoded and "canonical_ir" not in encoded
    path = tmp_path / "span.json"
    receipt = span.save_checkpoint(checkpoint, path)
    assert span.load_checkpoint(path, expected_sha256=receipt["sha256"]) == checkpoint
    with pytest.raises(FileExistsError):
        span.save_checkpoint(checkpoint, path)
    with pytest.raises(ValueError, match="hash differs"):
        span.load_checkpoint(path, expected_sha256="0" * 64)
    changed = examples()
    changed[0]["id"] = "different"
    with pytest.raises(ValueError, match="manifests differ"):
        span.train_decoder(checkpoint, changed, max_steps=1)
    broken = copy.deepcopy(checkpoint)
    broken["optimizer_state"]["parameters"]["start.bias"]["exp_avg_sq"][0] = -1
    with pytest.raises(ValueError):
        span.validate_checkpoint(broken)
    broken = copy.deepcopy(checkpoint)
    broken["progress"]["optimizer_steps"] += 1
    with pytest.raises(ValueError, match="step/cursor"):
        span.validate_checkpoint(broken)


def test_empty_object_is_expressible_and_zero_budget_executes_no_updates():
    row = examples()[0]
    row["canonical_ir"]["rules"][0]["object"] = ""
    checkpoint = span.build_checkpoint([row])
    result = span.train_decoder(checkpoint, [row], max_steps=0)
    assert result["checkpoint"]["model_state"] == checkpoint["model_state"]
    assert result["report"]["optimizer_steps"] == 0
    assert not result["report"]["training_executed"]


def test_trained_heads_reconstruct_modality_and_exception_minimal_pairs():
    rows = examples()
    checkpoint = span.build_checkpoint(rows, batch_size=6, hidden_size=16, embedding_dim=8,
                                       seed=23, learning_rate=.01)
    trained = span.train_decoder(checkpoint, rows, max_steps=150, max_seconds=60)
    outputs = span.SpanLegalFormulaDecoder(trained["checkpoint"]).decode_formal_logic(
        [row["source_text"] for row in rows])
    assert trained["report"]["optimizer_steps"] == 150
    assert [row["canonical_ir"] for row in outputs["rows"]] == [row["canonical_ir"] for row in rows]
    # This is a training-only numeric sanity check, not a generalization estimate.
    assert trained["report"]["batch_losses"][-1] < trained["report"]["batch_losses"][0]
