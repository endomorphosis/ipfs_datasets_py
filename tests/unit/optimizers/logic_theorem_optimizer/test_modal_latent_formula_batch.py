"""Batched recurrent generation retains independent grammar and abstention."""
import pytest

torch = pytest.importorskip("torch")
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as learning
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula_inference as optimized


@pytest.fixture(autouse=True)
def allocated_cpu():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


def samples(dimension):
    binding = {"domain": "legal_ir", "lineage_id": "legacy_hub_v1" if dimension == 8 else "current_legal_v2",
               "dimension": dimension, "runtime_profile": "test_authored_raw_core/v1", "core_sha256": "a" * 64}
    rows = []
    for identifier, sign in (("obligation", 1.), ("prohibition", -1.)):
        latent = [sign] + [0.] * (dimension - 1)
        rows.append({"id": identifier, "source_text": identifier + " authored source.", "latent": latent,
                     "embedding": [.6 * value for value in latent], "canonical_ir": {"rules": [{
                         "modality": "O" if sign > 0 else "F", "actor": "agency", "action": "disclose",
                         "object": "records", "conditions": [], "exceptions": [], "temporal": []}]}})
    return binding, rows


def trained_checkpoint(dimension, rows, *, epochs=1):
    binding, _ = samples(dimension)
    checkpoint = learning.build_checkpoint(binding, rows, [], learning_rate=.03, batch_size=2,
                                           hidden_size=16, token_embedding_dim=8, projection_width=4)
    return learning.train(checkpoint, rows, [], epochs=epochs, max_seconds=60)["checkpoint"]


def inputs(rows):
    return [{key: row[key] for key in ("id", "source_text", "latent")} for row in rows]


@pytest.mark.parametrize("dimension", [8, 384])
def test_real_batched_recurrence_matches_singleton_tokens_and_formulas(dimension, monkeypatch):
    _, rows = samples(dimension)
    decoder = optimized.BatchedLatentFormulaDecoder(trained_checkpoint(dimension, rows, epochs=100))
    batch = [dict(inputs(rows)[index % 2], id=str(index)) for index in range(32)]
    original_decoder = learning.LatentFormulaDecoder(decoder.checkpoint)
    singleton = [original_decoder._decode(row, learning.PROJECTION_ID) for row in batch]
    recurrent_sizes, grammar_calls = [], []
    original_step, original_allowed = decoder.model.next_logits, learning.codec_module.allowed_token_ids
    def step(tokens, hidden):
        recurrent_sizes.append(tokens.shape[0])
        return original_step(tokens, hidden)
    def allowed(codec, prefix):
        grammar_calls.append(tuple(prefix))
        return original_allowed(codec, prefix)
    monkeypatch.setattr(decoder.model, "next_logits", step)
    monkeypatch.setattr(learning.codec_module, "allowed_token_ids", allowed)
    result = decoder.infer(batch)
    assert result["decoded_count"] == len(batch)
    assert recurrent_sizes == [len(batch)] * (len(result["rows"][0]["generated_token_ids"]) - 1)
    assert len(grammar_calls) == len(set(grammar_calls))
    for single, batched in zip(singleton, result["rows"]):
        # Float32 matrix operations may round differently with a batch. The
        # confidence margin must agree numerically; all decisions and tokens
        # must agree exactly, including both latent-conditioned modalities.
        assert batched.pop("minimum_decision_logit_margin") == pytest.approx(
            single.pop("minimum_decision_logit_margin"), rel=1e-5, abs=1e-6)
        assert batched == single


def scripted_decoder(dimension, monkeypatch):
    _, rows = samples(dimension)
    rows[1]["canonical_ir"]["rules"][0].update(conditions=["valid_request"], exceptions=["sealed"], temporal=["promptly"])
    checkpoint = trained_checkpoint(dimension, rows)
    decoder = optimized.BatchedLatentFormulaDecoder(checkpoint)
    targets = [learning.codec_module.encode_target(decoder.codec, row["canonical_ir"]) for row in rows]
    sequences = [targets[0], targets[1], targets[0], targets[0], targets[0], targets[0]]
    faults, batches = {}, []
    def project(latents):
        values = latents.clone()
        for slot, index in enumerate(latents[:, 0].tolist()):
            if faults.get(int(index)) == "projection":
                values[slot, 1] = float("inf")
        return values
    def start(projected):
        hidden = torch.stack([projected[:, 0], torch.zeros_like(projected[:, 0])], dim=1).unsqueeze(0)
        for slot, index in enumerate(projected[:, 0].tolist()):
            if faults.get(int(index)) == "condition":
                hidden[0, slot, 1] = float("nan")
        return hidden
    def step(tokens, hidden):
        batches.append(tokens.shape[0])
        logits = torch.full((tokens.shape[0], 1, len(decoder.codec["target_vocabulary"])), -10.)
        updated = hidden.clone()
        for slot in range(tokens.shape[0]):
            index, position = (int(value) for value in hidden[0, slot])
            sequence = sequences[index]
            assert int(tokens[slot, 0]) == sequence[position]
            wanted = sequence[position + 1]
            logits[slot, 0, wanted] = 10.
            fault = faults.get(index)
            if position == 1:
                if fault == "scores":
                    logits[slot, 0, wanted] = float("nan")
                elif fault in {"tie", "small_margin", "clear_margin"}:
                    logits[slot, 0, :] = 0.
                    logits[slot, 0, wanted] = {"tie": 0., "small_margin": 5e-8, "clear_margin": 2e-7}[fault]
            updated[0, slot, 1] += 1
        return logits, updated
    monkeypatch.setattr(decoder.model, "project", project)
    monkeypatch.setattr(decoder.model, "start", start)
    monkeypatch.setattr(decoder.model, "next_logits", step)
    batch = [{"id": str(index), "source_text": "Authored input " + str(index),
              "latent": [float(index)] + [0.] * (dimension - 1)} for index in range(len(sequences))]
    return decoder, batch, sequences, faults, batches


@pytest.mark.parametrize("dimension", [8, 384])
def test_mixed_lengths_and_abstentions_remove_rows_without_reordering(dimension, monkeypatch):
    decoder, batch, sequences, faults, batches = scripted_decoder(dimension, monkeypatch)
    faults.update({2: "tie", 3: "condition", 4: "projection", 5: "scores"})
    batch = [dict(row, id=str(index)) for index, row in enumerate(batch * 3)]
    expected = [decoder._decode(row, learning.PROJECTION_ID) for row in batch]
    batches.clear()
    result = decoder.infer(batch)
    assert result["rows"] == expected
    assert result["status"] == "partial" and result["decoded_count"] == 6
    assert result["rows"][0]["generated_token_ids"] == sequences[0]
    assert result["rows"][1]["generated_token_ids"] == sequences[1]
    assert [row["reason"] for row in result["rows"]] == [None, None, "ambiguous_decoder_scores",
        "nonfinite_decoder_condition", "nonfinite_learned_projection", "nonfinite_decoder_scores"] * 3
    assert batches[:2] == [12, 12] and 6 in batches and batches[-1] == 3
    assert len(batches) == len(sequences[1]) - 1


@pytest.mark.parametrize("fault,decoded", [("tie", False), ("small_margin", False), ("clear_margin", True)])
def test_stable_ties_and_existing_margin_threshold_are_applied_per_row(fault, decoded, monkeypatch):
    decoder, batch, _, faults, _ = scripted_decoder(8, monkeypatch)
    faults[0] = fault
    batch = [dict(row, id=str(index)) for index, row in enumerate(batch[:2] * 9)]
    result = decoder.infer(batch)
    assert (result["rows"][0]["status"] == "decoded") is decoded
    assert result["rows"][1]["status"] == "decoded"
    if decoded:
        assert result["rows"][0]["minimum_decision_logit_margin"] == pytest.approx(2e-7)
    else:
        assert result["rows"][0]["reason"] == "ambiguous_decoder_scores"
        assert len(result["rows"][0]["generated_token_ids"]) == 2


def test_post_batch_integrity_check_detects_data_write_during_recurrent_step(monkeypatch):
    decoder, batch, _, _, _ = scripted_decoder(8, monkeypatch)
    batch = [dict(row, id=str(index)) for index, row in enumerate(batch * 3)]
    original = decoder.model.next_logits
    def mutate(tokens, hidden):
        result = original(tokens, hidden)
        decoder.model.output.bias.data.add_(.25)
        return result
    monkeypatch.setattr(decoder.model, "next_logits", mutate)
    with pytest.raises(ValueError, match="cached decoder weights differ"):
        decoder.infer(batch)


def test_original_checkpoint_pins_and_digest_are_preserved_and_optimizer_source_is_guarded(monkeypatch):
    _, rows = samples(8)
    checkpoint = trained_checkpoint(8, rows)
    original = learning.LatentFormulaDecoder(checkpoint)
    decoder = optimized.BatchedLatentFormulaDecoder(checkpoint)
    assert decoder.checkpoint == original.checkpoint == checkpoint
    assert decoder.checkpoint_sha256 == original.checkpoint_sha256 == learning.checkpoint_digest(checkpoint)
    assert decoder.inference_implementation["checkpoint_conversion_performed"] is False
    assert decoder.project([rows[0]["latent"]]) == original.project([rows[0]["latent"]])
    monkeypatch.setattr(optimized, "_source_sha256", lambda: "0" * 64)
    with pytest.raises(ValueError, match="batched latent decoder implementation changed since import"):
        decoder.infer(inputs(rows))


def test_unsupported_projection_and_invalid_inputs_retain_original_fail_closed_policy():
    _, rows = samples(8)
    decoder = optimized.BatchedLatentFormulaDecoder(trained_checkpoint(8, rows))
    result = decoder.infer(inputs(rows), projection_id="dcec")
    assert all(row["reason"] == "unsupported_formula_projection" for row in result["rows"])
    invalid = inputs(rows)
    invalid[0]["canonical_ir"] = {}
    with pytest.raises(ValueError, match="closed latent row"):
        decoder.infer(invalid)
    with pytest.raises(ValueError, match="one to 128"):
        decoder.infer([])


@pytest.mark.parametrize("count", [1, 8, 16])
def test_small_batches_use_original_scalar_decoder_without_batched_overhead(count, monkeypatch):
    _, rows = samples(8)
    checkpoint = trained_checkpoint(8, rows, epochs=5)
    decoder = optimized.BatchedLatentFormulaDecoder(checkpoint)
    original = learning.LatentFormulaDecoder(checkpoint)
    batch = [dict(inputs(rows)[index % 2], id=str(index)) for index in range(count)]
    expected = original.infer(batch)
    def forbidden(*args):
        raise AssertionError("small batch used the slower batched GRU path")
    monkeypatch.setattr(decoder, "_decode_batch", forbidden)
    result = decoder.infer(batch)
    evidence = result.pop("inference_implementation")
    assert evidence["execution"] == "scalar"
    assert result == expected


@pytest.mark.parametrize("count", [2, 4, 8, 16])
@pytest.mark.parametrize("dimension", [8, 384])
def test_cached_scalar_generation_matches_exact_original_formulas_and_margins(count, dimension):
    _, rows = samples(dimension)
    checkpoint = trained_checkpoint(dimension, rows, epochs=100)
    decoder = optimized.BatchedLatentFormulaDecoder(checkpoint)
    original = learning.LatentFormulaDecoder(checkpoint)
    batch = [dict(inputs(rows)[index % 2], id=str(index)) for index in range(count)]
    expected = original.infer(batch)
    result = decoder.infer(batch)
    evidence = result.pop("inference_implementation")
    assert evidence["execution"] == "scalar"
    assert evidence["confidence_margin_parity"] == "float32_numerical_not_bitwise"
    assert result["decoded_count"] == count
    assert result == expected


@pytest.mark.parametrize("dimension", [8, 384])
def test_scalar_requests_share_grammar_choices_without_changing_original_decisions(dimension, monkeypatch):
    _, rows = samples(dimension)
    checkpoint = trained_checkpoint(dimension, rows, epochs=100)
    decoder = optimized.BatchedLatentFormulaDecoder(checkpoint)
    original = learning.LatentFormulaDecoder(checkpoint)
    batch = [dict(inputs(rows)[index % 2], id=str(index)) for index in range(8)]
    expected = original.infer(batch)
    calls = []
    allowed = learning.codec_module.allowed_token_ids
    def count_allowed(codec, prefix):
        calls.append(tuple(prefix))
        return allowed(codec, prefix)
    monkeypatch.setattr(learning.codec_module, "allowed_token_ids", count_allowed)
    result = decoder.infer(batch)
    result.pop("inference_implementation")
    assert result == expected
    assert len(calls) == len(set(calls))
    decoder.infer(batch)
    assert len(calls) == 2 * len(set(calls)), "grammar cache must not persist across requests"


@pytest.mark.parametrize("dimension", [8, 384])
@pytest.mark.parametrize("count", [1, 8, 32])
def test_combined_projection_is_reused_by_decode_between_two_complete_guards(dimension, count, monkeypatch):
    _, rows = samples(dimension)
    decoder = optimized.BatchedLatentFormulaDecoder(trained_checkpoint(dimension, rows, epochs=30))
    batch = [dict(inputs(rows)[index % 2], id=str(index)) for index in range(count)]
    expected_report = decoder.infer(batch)
    expected_vectors = decoder.project([row["latent"] for row in batch])
    project_sizes, checks = [], []
    project, check = decoder.model.project, decoder._check
    def count_project(latents):
        project_sizes.append(latents.shape[0])
        return project(latents)
    def count_check():
        checks.append(True)
        return check()
    monkeypatch.setattr(decoder.model, "project", count_project)
    monkeypatch.setattr(decoder, "_check", count_check)
    result, vectors = decoder.infer_with_projection(batch)
    assert result == expected_report
    assert torch.allclose(torch.tensor(vectors), torch.tensor(expected_vectors), rtol=1e-6, atol=1e-6)
    assert project_sizes == ([1] * count if count <= 16 else [count])
    assert len(checks) == 2


@pytest.mark.parametrize("count", [1, 8, 32])
@pytest.mark.parametrize("stage", ["project", "next_logits"])
def test_combined_operation_detects_data_write_during_either_stage(count, stage, monkeypatch):
    _, rows = samples(8)
    decoder = optimized.BatchedLatentFormulaDecoder(trained_checkpoint(8, rows, epochs=30))
    batch = [dict(inputs(rows)[index % 2], id=str(index)) for index in range(count)]
    original = getattr(decoder.model, stage)
    def mutate(*args):
        result = original(*args)
        decoder.model.output.bias.data.add_(.25)
        return result
    monkeypatch.setattr(decoder.model, stage, mutate)
    with pytest.raises(ValueError, match="cached decoder weights differ"):
        decoder.infer_with_projection(batch)


@pytest.mark.parametrize("count", [1, 8, 32])
def test_combined_projection_rejects_nonfinite_vectors_even_for_unsupported_formulas(count, monkeypatch):
    _, rows = samples(8)
    decoder = optimized.BatchedLatentFormulaDecoder(trained_checkpoint(8, rows))
    batch = [dict(inputs(rows)[index % 2], id=str(index)) for index in range(count)]
    def nonfinite(latents):
        return torch.full_like(latents, float("nan"))
    monkeypatch.setattr(decoder.model, "project", nonfinite)
    with pytest.raises(ValueError, match="nonfinite learned projection"):
        decoder.infer_with_projection(batch, projection_id="unsupported")


def test_combined_operation_detects_original_source_change_during_projection(monkeypatch):
    _, rows = samples(8)
    decoder = optimized.BatchedLatentFormulaDecoder(trained_checkpoint(8, rows))
    project = decoder.model.project
    def mutate(latents):
        result = project(latents)
        monkeypatch.setattr(learning, "_pins", lambda: {"changed": True})
        return result
    monkeypatch.setattr(decoder.model, "project", mutate)
    with pytest.raises(ValueError, match="latent formula implementation changed since import"):
        decoder.infer_with_projection(inputs(rows))


def test_cached_scalar_grammar_retains_independent_mixed_length_abstentions(monkeypatch):
    decoder, batch, _, faults, _ = scripted_decoder(8, monkeypatch)
    faults.update({2: "tie", 3: "condition", 4: "projection", 5: "scores"})
    expected = [decoder._decode(row, learning.PROJECTION_ID) for row in batch]
    result = decoder.infer(batch)
    assert result["inference_implementation"]["execution"] == "scalar"
    assert result["rows"] == expected
    assert result["decoded_count"] == 2


@pytest.mark.parametrize("fault", ["tie", "small_margin", "clear_margin"])
@pytest.mark.parametrize("count", [1, 2, 8])
def test_combined_scalar_decode_retains_exact_margin_threshold(fault, count, monkeypatch):
    decoder, batch, _, faults, _ = scripted_decoder(8, monkeypatch)
    faults[0] = fault
    batch = [dict(batch[index % 2], id=str(index)) for index in range(count)]
    expected = [decoder._decode(row, learning.PROJECTION_ID) for row in batch]
    result, _ = decoder.infer_with_projection(batch)
    assert result["inference_implementation"]["execution"] == "scalar"
    assert result["rows"] == expected


@pytest.mark.parametrize("count", [8, 32])
def test_completed_rules_are_validated_once_per_request_and_owned_by_each_row(count, monkeypatch):
    decoder, rows, _, _, _ = scripted_decoder(8, monkeypatch)
    batch = [dict(rows[index % 2], id=str(index)) for index in range(count)]
    expected = [decoder._decode(row, learning.PROJECTION_ID) for row in batch]
    calls = []
    decode = learning.codec_module.decode_target
    def count_decode(codec, prefix):
        calls.append(tuple(prefix))
        return decode(codec, prefix)
    monkeypatch.setattr(learning.codec_module, "decode_target", count_decode)
    result = decoder.infer(batch)
    assert result["rows"] == expected
    assert len(calls) == len(set(calls)) == 2
    for row in result["rows"]:
        assert row["formal_outputs"][0]["payload"] is row["canonical_ir"]["rules"][0]
    result["rows"][0]["canonical_ir"]["rules"][0]["actor"] = "caller edit"
    assert result["rows"][2]["canonical_ir"]["rules"][0]["actor"] != "caller edit"
    repeated = decoder.infer(batch)
    assert repeated["rows"] == expected
    assert len(calls) == 4, "completed-rule cache must not persist across requests"


@pytest.mark.parametrize("value", [True, 1.0])
def test_completed_rule_cache_revalidates_nested_codec_numeric_type_changes(value, monkeypatch):
    decoder, _, sequences, _, _ = scripted_decoder(8, monkeypatch)
    cache = {}
    assert decoder._decoded({}, sequences[0], None, cache)["status"] == "decoded"
    decoder._codec["policy"]["rule_count"] = value
    with pytest.raises(ValueError) as expected:
        learning.codec_module.decode_target(decoder._codec, sequences[0])
    result = decoder._decoded({}, sequences[0], None, cache)
    assert result["reason"] == "generated_ir_rejected"
    assert result["detail"] == str(expected.value)


@pytest.mark.parametrize("field, replacement", [
    ("source_vocabulary", tuple), ("target_vocabulary", tuple),
    ("source_vocabulary", type("VocabularySubclass", (list,), {})),
    ("target_vocabulary", type("TargetSubclass", (list,), {})),
    ("policy", type("PolicySubclass", (dict,), {})),
    (None, type("CodecSubclass", (dict,), {})),
])
def test_completed_rule_cache_retains_original_exact_codec_container_types(field, replacement, monkeypatch):
    decoder, _, sequences, _, _ = scripted_decoder(8, monkeypatch)
    cache = {}
    assert decoder._decoded({}, sequences[0], None, cache)["status"] == "decoded"
    digest = learning.checkpoint_digest(decoder._codec)
    if field is None:
        decoder._codec = replacement(decoder._codec)
    else:
        decoder._codec[field] = replacement(decoder._codec[field])
    assert learning.checkpoint_digest(decoder._codec) == digest
    with pytest.raises(ValueError) as expected:
        learning.codec_module.decode_target(decoder._codec, sequences[0])
    result = decoder._decoded({}, sequences[0], None, cache)
    assert result["reason"] == "generated_ir_rejected"
    assert result["detail"] == str(expected.value)


@pytest.mark.parametrize("replacement", [float, type("IntegerSubclass", (int,), {})])
def test_completed_rule_cache_retains_exact_integer_prefix_types(replacement, monkeypatch):
    decoder, _, sequences, _, _ = scripted_decoder(8, monkeypatch)
    cache = {}
    assert decoder._decoded({}, sequences[0], None, cache)["status"] == "decoded"
    changed = [replacement(token) for token in sequences[0]]
    assert tuple(changed) == tuple(sequences[0])
    with pytest.raises(ValueError) as expected:
        learning.codec_module.decode_target(decoder._codec, changed)
    result = decoder._decoded({}, changed, None, cache)
    assert result["reason"] == "generated_ir_rejected"
    assert result["detail"] == str(expected.value)


def test_completed_rule_cache_observes_replaced_validator(monkeypatch):
    decoder, _, sequences, _, _ = scripted_decoder(8, monkeypatch)
    cache = {}
    assert decoder._decoded({}, sequences[0], None, cache)["status"] == "decoded"
    def reject(codec, prefix):
        raise ValueError("new validator rejected generated rule")
    monkeypatch.setattr(learning.codec_module, "decode_target", reject)
    result = decoder._decoded({}, sequences[0], None, cache)
    assert result["reason"] == "generated_ir_rejected"
    assert result["detail"] == "new validator rejected generated rule"


@pytest.mark.parametrize("count", [1, 32])
@pytest.mark.parametrize("fail", [False, True])
def test_numerical_stages_use_inference_mode_and_restore_caller_state(count, fail, monkeypatch):
    decoder, rows, _, _, _ = scripted_decoder(8, monkeypatch)
    batch = [dict(rows[index % 2], id=str(index)) for index in range(count)]
    project, step = decoder.model.project, decoder.model.next_logits
    stages = []
    def projected(latents):
        assert torch.is_inference_mode_enabled()
        stages.append("projection")
        return project(latents)
    def recurrent(tokens, hidden):
        assert torch.is_inference_mode_enabled()
        stages.append("recurrence")
        if fail:
            raise RuntimeError("authored recurrence failure")
        return step(tokens, hidden)
    monkeypatch.setattr(decoder.model, "project", projected)
    monkeypatch.setattr(decoder.model, "next_logits", recurrent)
    with torch.enable_grad():
        assert not torch.is_inference_mode_enabled()
        if fail:
            with pytest.raises(RuntimeError, match="authored recurrence failure"):
                decoder.infer_with_projection(batch)
        else:
            assert decoder.infer_with_projection(batch)[0]["decoded_count"] == count
        assert not torch.is_inference_mode_enabled()
        assert torch.is_grad_enabled()
    assert set(stages) == {"projection", "recurrence"}
