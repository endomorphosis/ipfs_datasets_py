"""Verified modal checkpoint extraction, federation and binary materialization."""
from dataclasses import replace
import hashlib
import importlib
import json
from pathlib import Path
import zlib

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_federated_modal as modal
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_federated import ClientSpec, aggregate_round
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder_checkpoint as codec


def namespace(version):
    return importlib.import_module("ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages." + version)


def state_fixture(version):
    ns = namespace(version)
    return ns.TrainingState(
        feature_embedding_weights={"beta": [2.0] * ns.DIMENSION, "alpha": [1.0] * ns.DIMENSION},
        feature_family_logits={"beta": {"deontic": 2.0}, "alpha": {"deontic": 1.0}, "empty": {}},
        legal_ir_view_logits={"deontic": -0.0},
        decoded_embeddings={"private-memory": [0.5] * ns.DIMENSION},
        family_logits={"private-memory": {"deontic": 0.75}},
        proof_auxiliary_head_logits={"obligation_family": {"__global__": {"mandatory": 0.75}}},
        proof_feedback_version_fingerprint="base-proof-policy", applied_proof_feedback_ids=["proof-a"],
        applied_leanstral_guidance_ids=["guidance-a"], applied_todo_ids=["todo-a"])


def write_raw(tmp_path, raw, *, version="current_v2", name="base", components=None):
    path = tmp_path / name
    path.write_bytes(raw)
    return modal.load_modal_checkpoint(path, expected_sha256=hashlib.sha256(raw).hexdigest(),
        runtime_version=version, trainable_components=components)


def adapter_fixture(tmp_path, version="current_v2", *, binary=False, dtype="float64", components=None):
    state = state_fixture(version)
    raw = codec.serialize_checkpoint(state, float_precision=dtype, metric_lineage={"fixture": "base/v1"}) if binary else (state.to_json() + "\n").encode()
    return write_raw(tmp_path, raw, version=version, components=components)


def round_fixture(adapter):
    return adapter.make_round("round-1", [ClientSpec("a", 1, "a" * 64), ClientSpec("b", 3, "b" * 64)],
        embedding_producer_sha256="c" * 64, max_local_steps=3)


def candidate_fixture(adapter):
    round_spec = round_fixture(adapter)
    first, second = adapter.fresh_state(), adapter.fresh_state()
    first.feature_embedding_weights["alpha"][0] += 4.0
    second.feature_embedding_weights["alpha"][0] -= 2.0
    updates = [adapter.make_update_from_state(round_spec, "a", first, local_steps=1, local_data_sha256="a" * 64),
               adapter.make_update_from_state(round_spec, "b", second, local_steps=2, local_data_sha256="b" * 64)]
    return round_spec, aggregate_round(round_spec, adapter.parameters, updates)


@pytest.mark.parametrize("version", ["legacy_v1", "current_v2"])
@pytest.mark.parametrize("binary,dtype", [(False, "float64"), (True, "float64"), (True, "float32")])
def test_actual_lineage_state_class_compact_parameters_and_semantic_index(tmp_path, version, binary, dtype):
    adapter = adapter_fixture(tmp_path, version, binary=binary, dtype=dtype)
    ns = namespace(version)
    assert type(adapter.fresh_state()) is ns.TrainingState
    assert adapter.dimension == ns.DIMENSION and adapter.lineage_id == ns.LINEAGE_ID
    assert len(adapter.parameter_specs) == 3
    assert all(spec.dtype == dtype for spec in adapter.parameter_specs)
    assert "decoded_embeddings" not in adapter.parameters and "proof_auxiliary_head_logits" not in adapter.parameters
    table = next(item for item in adapter.semantic_index if item["component"] == "feature_embedding_weights")
    assert table["rows"] == [{"path": ["alpha"], "width": ns.DIMENSION}, {"path": ["beta"], "width": ns.DIMENSION}]
    assert adapter.parameters["feature_embedding_weights"] == [1.0] * ns.DIMENSION + [2.0] * ns.DIMENSION
    assert "rows" not in adapter.binding and "semantic_layout_sha256" in adapter.binding
    assert adapter.fresh_model(compute_device="python")._joint_formula_checkpoint is None


@pytest.mark.parametrize("version", ["legacy_v1", "current_v2"])
@pytest.mark.parametrize("binary", [False, True])
def test_full_aggregate_materializes_verified_binary_and_preserves_exact_base_excluded_state(tmp_path, version, binary):
    adapter = adapter_fixture(tmp_path, version, binary=binary)
    original = adapter.fresh_state().to_dict()
    round_spec, candidate = candidate_fixture(adapter)
    receipt = adapter.materialize(round_spec, candidate, tmp_path / "aggregate.bin")
    assert receipt["formula_head_attached"] is False and receipt["optimizer_history_persisted"] is False
    assert receipt["state_revision"] == 0 and receipt["qualified"] is False and receipt["admitted"] is False
    assert adapter.verify_materialization(round_spec, candidate, receipt["path"]) is True
    raw = Path(receipt["path"]).read_bytes()
    assert raw.startswith(codec.CHECKPOINT_MAGIC) and hashlib.sha256(raw).hexdigest() == receipt["sha256"]
    loaded = codec.deserialize_checkpoint(raw, state_factory=namespace(version).TrainingState)
    assert loaded.manifest.revision == 0
    assert loaded.state.feature_embedding_weights["alpha"][0] == 0.5
    for name in ("decoded_embeddings", "family_logits", "proof_auxiliary_head_logits",
                 "proof_feedback_version_fingerprint", "applied_proof_feedback_ids", "applied_todo_ids"):
        assert loaded.state.to_dict()[name] == original[name]
    assert adapter.materialize(round_spec, candidate, receipt["path"]) == receipt
    assert adapter.fresh_state().to_dict() == original


def test_documented_legacy_missing_fields_and_architecture_migration_are_bound(tmp_path):
    data = state_fixture("legacy_v1").to_dict()
    for name in ("schema_version", "architecture_version", "proof_auxiliary_head_schema_version",
                 "proof_auxiliary_head_logits", "proof_feedback_version_fingerprint", "applied_proof_feedback_ids",
                 "applied_leanstral_guidance_ids"):
        data.pop(name)
    adapter = write_raw(tmp_path, json.dumps(data).encode(), version="legacy_v1")
    normalization = adapter.binding["checkpoint_policy"]["normalization"]
    assert "schema_version" in normalization["missing_fields"] and normalization["raw_architecture"] is None
    assert normalization["loaded_architecture"] == adapter.architecture
    data["architecture_version"] = "legacy_dense_v1"
    migrated = write_raw(tmp_path, json.dumps(data).encode(), version="legacy_v1", name="legacy-labelled")
    assert migrated.binding["checkpoint_policy"]["normalization"]["raw_architecture"] == "legacy_dense_v1"
    assert migrated.runtime_profile != adapter.runtime_profile


@pytest.mark.parametrize("field", ["unknown", "optimizer_state", "formula_checkpoint", "core_state", "progress"])
@pytest.mark.parametrize("binary", [False, True])
def test_unknown_fields_and_package_or_formula_envelopes_rejected_before_from_dict_discards_them(tmp_path, field, binary):
    data = state_fixture("current_v2").to_dict()
    data[field] = {"weight": [1.0]}
    raw = codec.serialize_checkpoint(data) if binary else json.dumps(data).encode()
    with pytest.raises(ValueError, match="unsupported package|unknown"):
        write_raw(tmp_path, raw)


def test_json_duplicates_nonfinite_and_type_coercions_are_rejected(tmp_path):
    for raw in (b'{"feature_embedding_weights":{},"feature_embedding_weights":{}}',
                b'{"feature_embedding_weights":{"row":[NaN]}}'):
        with pytest.raises(ValueError, match="duplicate|nonfinite"):
            write_raw(tmp_path, raw)
    data = state_fixture("current_v2").to_dict()
    data["feature_embedding_weights"]["alpha"][0] = True
    with pytest.raises(ValueError, match="excluding bool"):
        write_raw(tmp_path, json.dumps(data).encode())
    data["feature_embedding_weights"]["alpha"][0] = 2**60 + 1
    with pytest.raises(ValueError, match="losslessly"):
        write_raw(tmp_path, json.dumps(data).encode())


@pytest.mark.parametrize("mutation", ["inactive_proof", "too_many_ids", "numeric_strings", "proof_schema"])
def test_lossy_present_field_reload_and_schema_changes_are_rejected(tmp_path, mutation):
    data = state_fixture("current_v2").to_dict()
    if mutation == "inactive_proof":
        data["proof_feedback_version_fingerprint"] = ""
    elif mutation == "too_many_ids":
        data["applied_proof_feedback_ids"] = [str(index) for index in range(4097)]
    elif mutation == "numeric_strings":
        data["feature_embedding_weights"]["alpha"][0] = "1.0"
    else:
        data["proof_auxiliary_head_schema_version"] = "unsupported"
    with pytest.raises(ValueError, match="discard|excluding bool|schema"):
        write_raw(tmp_path, json.dumps(data).encode())


@pytest.mark.parametrize("mutation", ["new_row", "delete_row", "new_label", "empty_row", "shape", "architecture"])
def test_client_semantic_key_shape_and_architecture_drift_is_rejected(tmp_path, mutation):
    adapter = adapter_fixture(tmp_path)
    state = adapter.fresh_state()
    if mutation == "new_row":
        state.feature_embedding_weights["new"] = [0.0] * 384
    elif mutation == "delete_row":
        del state.feature_embedding_weights["alpha"]
    elif mutation == "new_label":
        state.feature_family_logits["alpha"]["new"] = 0.0
    elif mutation == "empty_row":
        state.feature_family_logits["empty"]["new"] = 0.0
    elif mutation == "shape":
        state.feature_embedding_weights["alpha"].pop()
    else:
        state.architecture_version = "legacy_dense_v1"
    with pytest.raises(ValueError, match="layout changed|width|architecture"):
        adapter.extract_parameters(state)


@pytest.mark.parametrize("mutation", ["sample_memory", "sample_logits", "proof", "proof_fingerprint", "history", "unknown_attribute"])
def test_excluded_state_changes_never_propagate_from_client(tmp_path, mutation):
    adapter = adapter_fixture(tmp_path)
    state = adapter.fresh_state()
    if mutation == "sample_memory":
        state.decoded_embeddings["private-memory"][0] += 1
    elif mutation == "sample_logits":
        state.family_logits["private-memory"]["deontic"] += 1
    elif mutation == "proof":
        state.proof_auxiliary_head_logits["obligation_family"]["__global__"]["mandatory"] += 1
    elif mutation == "proof_fingerprint":
        state.proof_feedback_version_fingerprint = "different"
    elif mutation == "history":
        state.applied_todo_ids.append("client-only")
    else:
        state.formula_checkpoint = {}
    with pytest.raises(ValueError, match="frozen|discard|unknown"):
        adapter.extract_parameters(state)


def test_in_memory_inactive_proof_mutation_cannot_hide_behind_to_dict_normalization(tmp_path):
    state = state_fixture("current_v2")
    state.proof_feedback_version_fingerprint = ""
    state.proof_auxiliary_head_logits = {}
    adapter = write_raw(tmp_path, state.to_json().encode())
    modified = adapter.fresh_state()
    modified.proof_auxiliary_head_logits["obligation_family"] = {"__global__": {"mandatory": 1.0}}
    with pytest.raises(ValueError, match="serialization would discard"):
        adapter.extract_parameters(modified)


def test_selected_subset_freezes_other_trainable_heads_and_rejects_proof_or_memory_selection(tmp_path):
    adapter = adapter_fixture(tmp_path, components=["feature_embedding_weights"])
    assert len(adapter.parameter_specs) == 1
    state = adapter.fresh_state()
    state.feature_family_logits["alpha"]["deontic"] += 1
    with pytest.raises(ValueError, match="excluded state"):
        adapter.extract_parameters(state)
    for components in (["decoded_embeddings"], ["proof_auxiliary_head_logits"],
                       ["feature_embedding_weights", "feature_embedding_weights"]):
        with pytest.raises(ValueError, match="distinct reusable"):
            adapter_fixture(tmp_path, components=components)


def test_client_checkpoint_deltas_use_correct_factory_hash_and_precision(tmp_path):
    adapter = adapter_fixture(tmp_path, "legacy_v1", binary=True)
    round_spec = round_fixture(adapter)
    state = adapter.fresh_state()
    state.feature_embedding_weights["alpha"][0] += 2
    raw = codec.serialize_checkpoint(state)
    path = tmp_path / "trained.bin"
    path.write_bytes(raw)
    item = adapter.make_update(round_spec, "a", path, expected_sha256=hashlib.sha256(raw).hexdigest(),
        local_steps=1, local_data_sha256="a" * 64)
    assert item.deltas["feature_embedding_weights"] == {0: 2.0}
    with pytest.raises(ValueError, match="SHA256"):
        adapter.make_update(round_spec, "a", path, expected_sha256="0" * 64,
            local_steps=1, local_data_sha256="a" * 64)
    raw32 = codec.serialize_checkpoint(state, float_precision="float32")
    path.write_bytes(raw32)
    with pytest.raises(ValueError, match="precision"):
        adapter.make_update(round_spec, "a", path, expected_sha256=hashlib.sha256(raw32).hexdigest(),
            local_steps=1, local_data_sha256="a" * 64)


def test_runtime_class_width_base_and_round_bindings_are_checked(tmp_path):
    adapter = adapter_fixture(tmp_path)
    with pytest.raises(ValueError, match="another modal runtime"):
        adapter.extract_parameters(state_fixture("legacy_v1"))
    with pytest.raises(ValueError, match="width"):
        write_raw(tmp_path, state_fixture("legacy_v1").to_json().encode(), name="wrong-width")
    round_spec = round_fixture(adapter)
    for changed in (replace(round_spec, runtime_profile="foreign/v1"), replace(round_spec, base_sha256="0" * 64)):
        with pytest.raises(ValueError, match="round differs"):
            adapter.validate_round(changed)
    Path(adapter.path).write_bytes(b"altered base")
    with pytest.raises(ValueError, match="SHA256"):
        adapter.fresh_state()


def test_parameter_snapshots_semantic_index_and_binding_are_fresh_without_mutable_aliases(tmp_path):
    adapter = adapter_fixture(tmp_path)
    adapter.parameters["feature_embedding_weights"][0] = 100
    adapter.semantic_index[0]["component"] = "unknown"
    adapter.binding["checkpoint_policy"]["dtype"] = "float32"
    assert adapter.parameters["feature_embedding_weights"][0] == 1.0
    assert adapter.binding["checkpoint_policy"]["dtype"] == "float64"


@pytest.mark.parametrize("mutation", ["wrong_weights", "wrong_metadata", "wrong_revision", "wrong_precision", "json"])
def test_independent_materialization_verifier_rejects_weight_and_policy_mismatch(tmp_path, mutation):
    adapter = adapter_fixture(tmp_path)
    round_spec, candidate = candidate_fixture(adapter)
    receipt = adapter.materialize(round_spec, candidate, tmp_path / "aggregate.bin")
    loaded = codec.deserialize_checkpoint(Path(receipt["path"]).read_bytes())
    state, metadata, revision, dtype = loaded.state, loaded.manifest.metadata, 0, "float64"
    if mutation == "wrong_weights":
        state.feature_embedding_weights["alpha"][0] += 1
    elif mutation == "wrong_metadata":
        metadata["candidate_sha256"] = "0" * 64
    elif mutation == "wrong_revision":
        revision = 1
    elif mutation == "wrong_precision":
        dtype = "float32"
    raw = state.to_json().encode() if mutation == "json" else codec.serialize_checkpoint(
        state, metadata=metadata, revision=revision, float_precision=dtype)
    path = tmp_path / "wrong.bin"
    path.write_bytes(raw)
    with pytest.raises(ValueError, match="parameters differ|metadata differs|complete binary"):
        adapter.verify_materialization(round_spec, candidate, path)


def test_binary_manifest_unknown_duplicate_and_attached_head_metadata_rejected(tmp_path):
    raw = codec.serialize_checkpoint(state_fixture("current_v2"))
    manifest, payload, _ = codec._parse_container(raw)
    for change in ({"unknown": True}, {"revision": "0"}, {"metadata": {"formula_checkpoint": {}}}):
        changed = {**manifest, **change}
        malformed = codec._container_bytes(codec.CHECKPOINT_MAGIC, changed, payload)
        with pytest.raises(ValueError, match="manifest fields|formula heads"):
            write_raw(tmp_path, malformed)
    encoded = codec._json_bytes(manifest)
    duplicate = b'{"revision":0,' + encoded[1:]
    framed = codec._HEADER.pack(codec.CHECKPOINT_MAGIC, codec.CONTAINER_VERSION, 0, len(duplicate), len(payload),
                               hashlib.sha256(duplicate).digest(), hashlib.sha256(payload).digest()) + duplicate + payload
    with pytest.raises(ValueError, match="duplicate"):
        write_raw(tmp_path, framed)


def test_source_profile_and_immutable_output_conflicts_fail_closed(tmp_path, monkeypatch):
    adapter = adapter_fixture(tmp_path)
    round_spec, candidate = candidate_fixture(adapter)
    output = tmp_path / "occupied.bin"
    output.write_bytes(b"existing unrelated artifact")
    with pytest.raises(ValueError, match="SHA256"):
        adapter.materialize(round_spec, candidate, output)
    assert output.read_bytes() == b"existing unrelated artifact"
    original = modal._source_profile
    monkeypatch.setattr(modal, "_source_profile", lambda version: {**original(version), "changed": True})
    with pytest.raises(ValueError, match="source profile changed"):
        adapter.validate_round(round_spec)


def test_empty_reusable_state_invalid_selection_limits_and_symlinks_are_rejected(tmp_path):
    raw = namespace("current_v2").TrainingState().to_json().encode()
    with pytest.raises(ValueError, match="no reusable trainable"):
        write_raw(tmp_path, raw)
    path = tmp_path / "nonempty"
    raw = state_fixture("current_v2").to_json().encode()
    path.write_bytes(raw)
    sha = hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError, match="bounded nonempty"):
        modal.load_modal_checkpoint(path, expected_sha256=sha, runtime_version="current_v2", max_bytes=1)
    alias = tmp_path / "alias"
    alias.symlink_to(path)
    with pytest.raises(ValueError, match="symlink"):
        modal.load_modal_checkpoint(alias, expected_sha256=sha, runtime_version="current_v2")


def test_sign_only_parameter_change_is_rejected_rather_than_discarded_in_additive_codec(tmp_path):
    adapter = adapter_fixture(tmp_path)
    state = adapter.fresh_state()
    state.legal_ir_view_logits["deontic"] = 0.0
    with pytest.raises(ValueError, match="signed-zero-only"):
        adapter.make_update_from_state(round_fixture(adapter), "a", state, local_steps=1, local_data_sha256="a" * 64)


def binary_parts(raw):
    manifest, compressed, _ = codec._parse_container(raw)
    payload = zlib.decompress(compressed)
    index_size = codec._INDEX_LENGTH.unpack_from(payload)[0]
    end = codec._INDEX_LENGTH.size + index_size
    return manifest, json.loads(payload[codec._INDEX_LENGTH.size:end]), payload[end:]


def reframe_binary(manifest, index, numeric, *, index_raw=None, compressed_tail=b""):
    encoded = codec._json_bytes(index) if index_raw is None else index_raw
    compressed = zlib.compress(codec._INDEX_LENGTH.pack(len(encoded)) + encoded + numeric) + compressed_tail
    manifest = {**manifest, "payload_checksum": hashlib.sha256(compressed).hexdigest(),
                "table_count": len(index["tables"]),
                "numeric_value_count": sum(table["value_count"] for table in index["tables"])}
    return codec._container_bytes(codec.CHECKPOINT_MAGIC, manifest, compressed)


@pytest.mark.parametrize("version", ["legacy_v1", "current_v2"])
def test_duplicate_binary_vector_rows_cannot_discard_authenticated_numeric_values(tmp_path, version):
    ns = namespace(version)
    raw = codec.serialize_checkpoint(ns.TrainingState(feature_embedding_weights={"f": [2.0] * ns.DIMENSION}))
    manifest, index, numeric = binary_parts(raw)
    table = index["tables"][0]
    table.update(keys=["f", "f"], row_lengths=[ns.DIMENSION, ns.DIMENSION],
                 value_count=2 * ns.DIMENSION, byte_length=16 * ns.DIMENSION)
    numeric = b"".join(codec.struct.pack("<d", 1.0) for _ in range(ns.DIMENSION)) + numeric
    malformed = reframe_binary(manifest, index, numeric)
    # Establish the original codec's normalization trap without changing it.
    assert codec.deserialize_checkpoint(malformed, state_factory=ns.TrainingState).state.feature_embedding_weights["f"] == [2.0] * ns.DIMENSION
    with pytest.raises(ValueError, match="sorted unique"):
        write_raw(tmp_path, malformed, version=version)


def test_duplicate_binary_scalar_keys_cannot_discard_authenticated_numeric_values(tmp_path):
    state = namespace("current_v2").TrainingState(
        feature_embedding_weights={"f": [2.0] * 384}, legal_ir_view_logits={"deontic": 0.5})
    manifest, index, numeric = binary_parts(codec.serialize_checkpoint(state))
    table = index["tables"][-1]
    assert table["encoding"] == "keyed_scalars"
    start = table["byte_offset"]
    table.update(keys=["deontic", "deontic"], value_count=2, byte_length=16)
    numeric = numeric[:start] + codec.struct.pack("<d", 1.0) + numeric[start:]
    malformed = reframe_binary(manifest, index, numeric)
    assert codec.deserialize_checkpoint(malformed).state.legal_ir_view_logits["deontic"] == 0.5
    with pytest.raises(ValueError, match="sorted unique"):
        write_raw(tmp_path, malformed)


@pytest.mark.parametrize("change", ["extra_index", "extra_descriptor", "unused_keys", "dtype",
    "digits", "bool_length", "string_length", "reorder_tables", "reorder_rows", "coerced_key",
    "duplicate_empty", "overlap_empty", "duplicate_path", "wrong_path_depth"])
def test_binary_index_and_descriptor_schema_semantic_paths_and_precision_are_closed(tmp_path, change):
    manifest, index, numeric = binary_parts(codec.serialize_checkpoint(state_fixture("current_v2")))
    vector = next(table for table in index["tables"] if table["field"] == "feature_embedding_weights")
    paths = next(table for table in index["tables"] if table["field"] == "feature_family_logits")
    if change == "extra_index":
        index["unknown"] = {}
    elif change == "extra_descriptor":
        vector["unknown"] = []
    elif change == "unused_keys":
        paths["keys"] = ["ignored"]
    elif change == "dtype":
        vector["dtype"] = "float32"
    elif change == "digits":
        vector["precision_digits"] = 7
    elif change == "bool_length":
        vector["row_lengths"][0] = True
    elif change == "string_length":
        vector["row_lengths"][0] = "384"
    elif change == "reorder_tables":
        index["tables"].reverse()
    elif change == "reorder_rows":
        vector["keys"].reverse()
    elif change == "coerced_key":
        vector["keys"][0] = 1
    elif change == "duplicate_empty":
        paths["empty_paths"].append(paths["empty_paths"][0])
    elif change == "overlap_empty":
        paths["empty_paths"] = [["alpha"], ["empty"]]
    elif change == "duplicate_path":
        paths["paths"][1] = paths["paths"][0]
    else:
        paths["paths"][0].append("ignored-level")
    with pytest.raises(ValueError, match="index fields|descriptor fields|dtype|widths|offsets|keys|paths|shape"):
        write_raw(tmp_path, reframe_binary(manifest, index, numeric))


def test_binary_index_duplicate_json_keys_and_trailing_compression_or_numeric_bytes_are_rejected(tmp_path):
    manifest, index, numeric = binary_parts(codec.serialize_checkpoint(state_fixture("current_v2")))
    encoded = codec._json_bytes(index)
    duplicate = b'{"metadata":{},' + encoded[1:]
    with pytest.raises(ValueError, match="duplicate"):
        write_raw(tmp_path, reframe_binary(manifest, index, numeric, index_raw=duplicate))
    for tail in (b"unconsumed", zlib.compress(b"second-stream")):
        with pytest.raises(ValueError, match="trailing compressed"):
            write_raw(tmp_path, reframe_binary(manifest, index, numeric, compressed_tail=tail))
    with pytest.raises(ValueError, match="unconsumed|length differs"):
        write_raw(tmp_path, reframe_binary(manifest, index, numeric + b"unindexed"))


def test_decompression_bounds_and_truncated_streams_fail_before_original_codec_decode(tmp_path, monkeypatch):
    raw = codec.serialize_checkpoint(state_fixture("current_v2"))
    manifest, index, numeric = binary_parts(raw)
    def original_decode_not_allowed(*args, **kwargs):
        pytest.fail("unsafe compressed index reached the original allocating decoder")
    monkeypatch.setattr(codec, "deserialize_checkpoint", original_decode_not_allowed)
    # The tiny bound is a codec resource test override, not a production change.
    monkeypatch.setattr(codec, "_MAX_INDEX_BYTES", 32)
    with pytest.raises(ValueError, match="bounds"):
        write_raw(tmp_path, raw)
    compressed = zlib.compress(codec._INDEX_LENGTH.pack(5) + b"{}")[:-1]
    manifest["payload_checksum"] = hashlib.sha256(compressed).hexdigest()
    truncated = codec._container_bytes(codec.CHECKPOINT_MAGIC, manifest, compressed)
    with pytest.raises(ValueError, match="truncated|incomplete"):
        write_raw(tmp_path, truncated)
