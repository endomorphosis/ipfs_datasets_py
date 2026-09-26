"""Mapped sample compatibility; synthetic codec declarations are not inference."""
from __future__ import annotations

from collections.abc import Sequence
import copy
import hashlib
import json
import struct

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_arrow_inputs as arrow
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_production as production
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_corpus_manifest import SourceArtifact, SourceSpan
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_samples
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder as autoencoder


@pytest.fixture
def mapped_fixture(tmp_path):
    """Exercise serialized native-profile claims, without claiming real inference."""
    text = "The agency shall retain the public record."
    raw = text.encode()
    path = tmp_path / "source.txt"
    path.write_bytes(raw)
    span = SourceSpan(SourceArtifact(hashlib.sha256(raw).hexdigest(), len(raw)), "us_code",
                      "adapter-fixture", "fixture-1", "en", "5 USC 1", 0, len(raw))
    item = production.EmbeddingInput(span, "5", "1", text, span.citation)
    resolver = lambda _: path
    values = list(struct.unpack("<384f", struct.pack("<384f", 0.6, 0.8, -0.0, 2**-149, *([0.0] * 380))))
    assets = [{"name": name, "sha256": hashlib.sha256(name.encode()).hexdigest(), "bytes": 1}
              for name in sorted(("config.json", "tokenizer.json", "tokenizer_config.json", "vocab.txt",
                                  "special_tokens_map.json", "modules.json", "sentence_bert_config.json",
                                  "1_Pooling/config.json", "model.safetensors"))]
    fixture = production.build_embedding_production_receipt(
        [item], results=[{"input_id": item.input_id, "status": "embedded",
                          "tokens": {"input_ids": [101, 2000, 102], "attention_mask": [1, 1, 1],
                                     "token_type_ids": [0, 0, 0]}, "vector": values}],
        execution={**production.native_execution_profile(), "kind": "injected_fixture"}, model_assets=assets,
        producer={"code_sha256": "a" * 64, "runtime_versions": {
            name: "fixture" for name in ("python", "torch", "transformers", "sentence_transformers", "tokenizers")}},
        resolver=resolver)
    declared = fixture.to_dict()
    declared["execution"]["kind"] = "native"
    receipt = production.EmbeddingProductionReceipt(json.dumps(
        declared, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode())
    assert receipt.verification_summary()["runtime_computation_proven"] is False
    records = receipt.to_corpus_records(resolver=resolver)
    artifact = arrow.write_embedding_inputs_ipc(
        records, tmp_path / "inputs.arrow", production=receipt, resolver=resolver)
    mapping = arrow.load_embedding_inputs_ipc(
        artifact["path"], expected_sha256=artifact["sha256"], expected_size_bytes=artifact["bytes"],
        production=receipt, records=records, resolver=resolver)
    try:
        yield mapping, records[0], values
    finally:
        mapping.close()


def _sample(record, vector):
    return legal_samples.build_us_code_sample(
        title=record.sample.title, section=record.sample.section, text=record.sample.text,
        citation=record.sample.citation, embedding_model=record.sample.embedding_model,
        embedding_vector=vector)


def _float_bits(values):
    return b"".join(struct.pack(">d", value) for value in values)


def test_builder_retains_exact_mapped_vector_and_explicit_serialization_matches(mapped_fixture):
    mapping, record, values = mapped_fixture
    vector = mapping.row(record.record_id)
    sample = _sample(record, vector)
    ordinary = _sample(record, values)
    assert type(vector) is arrow.MappedEmbeddingVector
    assert isinstance(vector, Sequence)
    assert sample.embedding_vector is vector
    assert type(ordinary.embedding_vector) is list
    assert ordinary.embedding_vector is not values
    assert all(type(value) is float for value in vector)
    assert _float_bits(vector) == _float_bits(values)
    assert sample.to_json() == ordinary.to_json()
    assert "-0.0" in sample.to_json()
    assert autoencoder._embedding_vector_hash(vector) == autoencoder._embedding_vector_hash(values)
    assert autoencoder._sample_content_cache_id(sample) == autoencoder._sample_content_cache_id(ordinary)
    assert _float_bits(sample.to_dict()["embedding_vector"]) == _float_bits(values)


def test_ordinary_sequence_inputs_still_get_independent_lists(mapped_fixture):
    _, record, values = mapped_fixture

    class OrdinarySequence(Sequence):
        def __len__(self):
            return len(values)

        def __getitem__(self, index):
            return values[index]

    for candidate in (values, tuple(values), OrdinarySequence()):
        sample = _sample(record, candidate)
        assert type(sample.embedding_vector) is list
        assert sample.embedding_vector is not candidate
        assert _float_bits(sample.embedding_vector) == _float_bits(values)
    copied = _sample(record, values)
    values[0] = 0.0
    assert copied.embedding_vector[0] != values[0]


def test_mapped_readonly_and_closed_lifetime_are_enforced(mapped_fixture):
    mapping, record, _ = mapped_fixture
    vector = mapping.row(record.record_id)
    sample = _sample(record, vector)
    with pytest.raises(TypeError):
        vector[0] = 2.0
    with pytest.raises(AttributeError):
        vector.append(2.0)
    array = vector.readonly_array()
    assert str(array.dtype) == "float32"
    assert array.flags.writeable is False
    with pytest.raises(ValueError):
        array[0] = 2.0
    del array
    mapping.close()
    for operation in (lambda: len(vector), lambda: vector[0], lambda: list(vector), sample.validate, sample.to_dict):
        with pytest.raises(arrow.ArrowInputError, match="closed"):
            operation()


def test_python_math_evaluation_and_update_match_without_target_copy(mapped_fixture, monkeypatch):
    mapping, record, values = mapped_fixture
    vector = mapping.row(record.record_id)
    mapped_sample, ordinary_sample = _sample(record, vector), _sample(record, values)
    mapped_model = autoencoder.AdaptiveModalAutoencoder(compute_device="python")
    ordinary_model = autoencoder.AdaptiveModalAutoencoder(compute_device="python")
    decoded = [0.25] * len(values)
    assert autoencoder.cosine_similarity(vector, decoded) == autoencoder.cosine_similarity(values, decoded)
    assert autoencoder.mse_loss(vector, decoded) == autoencoder.mse_loss(values, decoded)
    assert _float_bits(mapped_model._initial_embedding_projection(vector)) == _float_bits(
        ordinary_model._initial_embedding_projection(values))
    assert _float_bits(mapped_model._embedding_training_error(vector, decoded)) == _float_bits(
        ordinary_model._embedding_training_error(values, decoded))
    seen = []
    original_metrics = mapped_model._embedding_metrics

    def capture(targets, predictions):
        seen.extend(targets)
        return original_metrics(targets, predictions)

    monkeypatch.setattr(mapped_model, "_embedding_metrics", capture)
    assert mapped_model.evaluate([mapped_sample]).to_dict() == ordinary_model.evaluate([ordinary_sample]).to_dict()
    assert len(seen) == 1 and seen[0] is vector
    mapped_model._nudge_decoded_embedding(mapped_sample, learning_rate=0.2)
    ordinary_model._nudge_decoded_embedding(ordinary_sample, learning_rate=0.2)
    assert json.dumps(mapped_model.state.to_dict(), sort_keys=True) == json.dumps(
        ordinary_model.state.to_dict(), sort_keys=True)
    assert type(mapped_model.state.decoded_embeddings[mapped_sample.sample_id]) is not arrow.MappedEmbeddingVector


def test_baseline_encode_keeps_its_explicit_copy(mapped_fixture):
    mapping, record, values = mapped_fixture
    vector = mapping.row(record.record_id)
    encoded = autoencoder.ModalAutoencoderBaseline().encode(_sample(record, vector))
    assert type(encoded["embedding"]) is list
    assert encoded["embedding"] is not vector
    assert _float_bits(encoded["embedding"]) == _float_bits(values)


@pytest.mark.parametrize("indices", [slice(None), slice(None, None, -1), slice(1, 9, 2), slice(0, 0)])
def test_deepcopy_detaches_exact_values_and_preserves_repeated_view_aliases(mapped_fixture, indices):
    mapping, record, values = mapped_fixture
    vector = mapping.row(record.record_id)[indices]
    before = mapping.statistics
    cloned = copy.deepcopy({"first": vector, "nested": [vector]})
    detached = cloned["first"]
    assert type(detached) is list
    assert detached is cloned["nested"][0]
    assert _float_bits(detached) == _float_bits(values[indices])
    assert mapping.statistics["scalar_accesses"] - before["scalar_accesses"] == len(detached)
    assert mapping.statistics["array_exports"] == before["array_exports"]
    mapping.close()
    assert _float_bits(detached) == _float_bits(values[indices])
    detached.append(7.0)
    assert cloned["nested"][0][-1] == 7.0


def test_deepcopied_sample_survives_mapping_close_and_preserves_graph_aliases(mapped_fixture):
    mapping, record, values = mapped_fixture
    vector = mapping.row(record.record_id)
    source = _sample(record, vector)
    expected = _sample(record, values)
    detached, alias, copied_vector = copy.deepcopy([source, source, vector])
    assert detached is alias
    assert detached is not source
    assert detached.embedding_vector is copied_vector
    assert type(copied_vector) is list
    mapping.close()
    detached.validate()
    assert detached.to_json() == expected.to_json()
    assert _float_bits(copied_vector) == _float_bits(values)
    assert autoencoder._sample_content_cache_id(detached) == autoencoder._sample_content_cache_id(expected)
    with pytest.raises(arrow.ArrowInputError, match="closed"):
        source.to_dict()


def test_separate_deepcopies_do_not_share_mutable_detached_rows(mapped_fixture):
    mapping, record, values = mapped_fixture
    vector = mapping.row(record.record_id)
    first, second = copy.deepcopy(vector), copy.deepcopy(vector)
    first[0] = -11.0
    assert _float_bits(second) == _float_bits(values)
    assert _float_bits(vector) == _float_bits(values)


def test_deepcopy_of_closed_vector_fails_without_publishing_memo(mapped_fixture):
    mapping, record, _ = mapped_fixture
    vector = mapping.row(record.record_id)
    mapping.close()
    memo = {}
    with pytest.raises(arrow.ArrowInputError, match="closed"):
        copy.deepcopy(vector, memo)
    assert id(vector) not in memo


@pytest.mark.parametrize("close_after_index", [0, 383])
def test_interrupted_deepcopy_does_not_publish_a_partial_or_closed_row(
        mapped_fixture, monkeypatch, close_after_index):
    mapping, record, _ = mapped_fixture
    vector = mapping.row(record.record_id)
    original = arrow.MappedEmbeddingVector.__getitem__

    def close_during_read(self, index):
        value = original(self, index)
        if index == close_after_index:
            mapping.close()
        return value

    monkeypatch.setattr(arrow.MappedEmbeddingVector, "__getitem__", close_during_read)
    memo = {}
    with pytest.raises(arrow.ArrowInputError, match="closed"):
        copy.deepcopy(vector, memo)
    assert id(vector) not in memo


def test_mapped_sequences_preserve_existing_torch_float64_backend(mapped_fixture):
    pytest.importorskip("torch")
    mapping, record, values = mapped_fixture
    vector = mapping.row(record.record_id)
    model = autoencoder.AdaptiveModalAutoencoder(compute_device="cpu")
    assert model.compute_backend == "torch_cpu"
    current = [0.25] * len(values)
    assert model._embedding_metrics([vector], [current]) == model._embedding_metrics([values], [current])
    assert _float_bits(model._vector_difference(vector, current)) == _float_bits(
        model._vector_difference(values, current))
    assert _float_bits(model._blend_toward(current, vector, step=0.2)) == _float_bits(
        model._blend_toward(current, values, step=0.2))
