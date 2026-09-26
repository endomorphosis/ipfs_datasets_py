"""Real mapped-buffer and tracked-state parity for the private legacy slice."""

from __future__ import annotations

import copy
import hashlib
import os
import struct
import threading

import numpy as np
import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    AdaptiveModalAutoencoder,
    ModalAutoencoderTrainingState,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_arrow_weights import (
    ArrowWeightError,
    MappedFeatureEmbeddingWeights,
    build_feature_embedding_weights_ipc,
    load_feature_embedding_weights_ipc,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_state_transaction import (
    StateTransactionConflictError,
)


BASE_SHA = "a" * 64
ROWS = {"raw source-like feature key!": [-0.0, 0.12345678901234568], "empty": [], "é/last": [2.0]}


def _load(path, descriptor, **overrides):
    return load_feature_embedding_weights_ipc(path, **{
        "expected_sha256": descriptor["sha256"],
        "expected_size_bytes": descriptor["size_bytes"],
        "expected_base_checkpoint_sha256": BASE_SHA,
        **overrides,
    })


@pytest.fixture
def mapped(tmp_path):
    path = tmp_path / "features.arrow"
    descriptor = build_feature_embedding_weights_ipc(ROWS, path, base_checkpoint_sha256=BASE_SHA, batch_rows=1)
    result = _load(path, descriptor)
    yield result
    result.close()


def test_deterministic_private_codec_preserves_keys_order_and_exact_float_bits(tmp_path):
    descriptors = []
    for name in ("first.arrow", "second.arrow"):
        descriptors.append(build_feature_embedding_weights_ipc(
            ROWS, tmp_path / name, base_checkpoint_sha256=BASE_SHA, batch_rows=1,
        ))
    assert descriptors[0] == descriptors[1]
    assert (tmp_path / "first.arrow").read_bytes() == (tmp_path / "second.arrow").read_bytes()
    assert descriptors[0]["scalar_count"] == 3
    assert descriptors[0]["row_count"] == 3
    mapped = _load(tmp_path / "first.arrow", descriptors[0])
    try:
        mapped.verify_source_rows(ROWS)
        assert list(mapped) == list(ROWS)
        assert np.signbit(mapped.readonly_row_array(next(iter(ROWS)))[0])
        assert mapped.readonly_row_array("empty").shape == (0,)
        assert mapped.statistics["overlay_rows"] == 0
        assert mapped.statistics["mapped_numeric_bytes"] == 24
        assert mapped.statistics["row_materializations"] == 0
    finally:
        mapped.close()


def test_unchanged_rows_share_readonly_mapped_buffers(mapped):
    key = next(iter(ROWS))
    first = mapped.readonly_row_array(key)
    second = mapped.readonly_row_array(key)
    assert np.shares_memory(first, second)
    assert not first.flags.writeable
    with pytest.raises(ValueError):
        first[0] = 8.0
    with pytest.raises(ValueError):
        first.setflags(write=True)
    assert list(mapped[key]) == ROWS[key]
    assert len(mapped[key]) == 2
    assert mapped.statistics["row_materializations"] == 0


@pytest.mark.parametrize("change", ["values", "zero_sign", "order", "missing"])
def test_source_reconciliation_rejects_changed_values_signed_zero_or_membership(mapped, change):
    rows = copy.deepcopy(ROWS)
    if change == "values":
        rows[next(iter(rows))][1] += 0.00001
    elif change == "zero_sign":
        rows[next(iter(rows))][0] = 0.0
    elif change == "order":
        rows = dict(reversed(list(rows.items())))
    else:
        rows.pop("empty")
    with pytest.raises(ArrowWeightError, match="source feature"):
        mapped.verify_source_rows(rows)


@pytest.mark.parametrize("change", ["sha", "size", "base", "bytes"])
def test_loader_checks_exact_artifact_and_checkpoint_binding(tmp_path, change):
    path = tmp_path / "features.arrow"
    descriptor = build_feature_embedding_weights_ipc(ROWS, path, base_checkpoint_sha256=BASE_SHA)
    overrides = {}
    if change == "sha":
        overrides["expected_sha256"] = "b" * 64
    elif change == "size":
        overrides["expected_size_bytes"] = descriptor["size_bytes"] + 1
    elif change == "base":
        overrides["expected_base_checkpoint_sha256"] = "b" * 64
    else:
        raw = bytearray(path.read_bytes())
        raw[len(raw) // 2] ^= 1
        path.write_bytes(raw)
    with pytest.raises(ArrowWeightError):
        _load(path, descriptor, **overrides)


def test_codec_refuses_overwrite_and_cleans_incomplete_artifact(tmp_path):
    path = tmp_path / "features.arrow"
    path.write_bytes(b"protected")
    with pytest.raises(FileExistsError):
        build_feature_embedding_weights_ipc(ROWS, path, base_checkpoint_sha256=BASE_SHA)
    assert path.read_bytes() == b"protected"
    bad = tmp_path / "bad.arrow"
    with pytest.raises(ArrowWeightError, match="finite"):
        build_feature_embedding_weights_ipc({"bad": [float("nan")]}, bad, base_checkpoint_sha256=BASE_SHA)
    assert not bad.exists()
    assert list(tmp_path.iterdir()) == [path]


def test_empty_mapping_is_a_valid_lossless_artifact(tmp_path):
    path = tmp_path / "empty.arrow"
    descriptor = build_feature_embedding_weights_ipc({}, path, base_checkpoint_sha256=BASE_SHA)
    mapped = _load(path, descriptor)
    try:
        assert dict(mapped) == {}
        assert mapped.statistics["mapped_numeric_bytes"] == 0
        mapped.verify_source_rows({})
    finally:
        mapped.close()


def test_legacy_string_key_and_float_normalization_match_from_dict(tmp_path):
    rows = {1: [1], "1": [2], 2: ["3.25"]}
    path = tmp_path / "normalized.arrow"
    descriptor = build_feature_embedding_weights_ipc(rows, path, base_checkpoint_sha256=BASE_SHA)
    mapped = _load(path, descriptor)
    try:
        legacy = ModalAutoencoderTrainingState.from_dict({"feature_embedding_weights": rows})
        arrow = ModalAutoencoderTrainingState.from_dict(
            {"feature_embedding_weights": rows}, feature_embedding_weights_override=mapped,
        )
        assert list(mapped) == ["1", "2"]
        assert arrow.state_identity_record() == legacy.state_identity_record()
        assert arrow.to_json() == legacy.to_json()
    finally:
        mapped.close()


def test_compressed_ipc_cannot_claim_mapped_numeric_buffers(tmp_path, monkeypatch):
    import pyarrow as pa
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_arrow_weights import _schema

    if not pa.Codec.is_available("lz4"):
        pytest.skip("test compression codec is unavailable")
    schema = _schema(pa, base_sha256=BASE_SHA, row_count=1, scalar_count=256)
    path = tmp_path / "compressed.arrow"
    with pa.ipc.new_file(path, schema, options=pa.ipc.IpcWriteOptions(compression="lz4")) as writer:
        writer.write_batch(pa.record_batch([
            pa.array(["row"], type=pa.string()),
            pa.array([[1.0] * 256], type=pa.list_(pa.float64())),
        ], schema=schema))
    raw = path.read_bytes()
    def decoder_must_not_run(*args, **kwargs):
        raise AssertionError("compressed batch reached Arrow decoding")
    monkeypatch.setattr(pa.ipc, "open_file", decoder_must_not_run)
    with pytest.raises(ArrowWeightError, match="not a mapped file buffer"):
        load_feature_embedding_weights_ipc(
            path, expected_sha256=hashlib.sha256(raw).hexdigest(),
            expected_size_bytes=len(raw), expected_base_checkpoint_sha256=BASE_SHA,
        )


def test_normal_state_constructor_binds_tracking_without_copying_or_revising(mapped):
    original = ModalAutoencoderTrainingState(feature_embedding_weights=ROWS)
    data = {"feature_embedding_weights": ROWS}
    first = ModalAutoencoderTrainingState.from_dict(data, feature_embedding_weights_override=mapped)
    second = ModalAutoencoderTrainingState.from_dict(data, feature_embedding_weights_override=mapped)
    assert type(first.feature_embedding_weights) is MappedFeatureEmbeddingWeights
    assert first.state_revision == second.state_revision == original.state_revision == 0
    assert first.state_identity_record() == original.state_identity_record()
    assert first.to_json() == original.to_json()
    key = next(iter(ROWS))
    assert np.shares_memory(
        first.feature_embedding_weights.readonly_row_array(key),
        second.feature_embedding_weights.readonly_row_array(key),
    )
    first.feature_embedding_weights[key][0] = 3.0
    assert second.feature_embedding_weights[key][0] == 0.0
    assert np.signbit(second.feature_embedding_weights[key][0])
    assert first.state_revision == 1
    assert second.state_revision == 0
    assert first.feature_embedding_weights.statistics["overlay_rows"] == 1
    assert second.feature_embedding_weights.statistics["overlay_rows"] == 0


def test_from_dict_override_rejects_mismatched_source_rows(mapped):
    with pytest.raises(ArrowWeightError):
        ModalAutoencoderTrainingState.from_dict(
            {"feature_embedding_weights": {"different": [1.0]}},
            feature_embedding_weights_override=mapped,
        )


def test_from_dict_override_rejects_equal_bits_with_nonfloat_overlay_type(mapped):
    mapped["é/last"][0] = 2
    assert type(mapped["é/last"][0]) is int
    with pytest.raises(ArrowWeightError, match="float-normalized"):
        ModalAutoencoderTrainingState.from_dict(
            {"feature_embedding_weights": ROWS}, feature_embedding_weights_override=mapped,
        )


def test_transaction_rollback_and_replay_match_legacy_state_and_release_trial_rows(mapped):
    data = {"feature_embedding_weights": ROWS}
    legacy = ModalAutoencoderTrainingState.from_dict(data)
    arrow = ModalAutoencoderTrainingState.from_dict(data, feature_embedding_weights_override=mapped)
    before = arrow.state_identity_record()
    key = next(iter(ROWS))
    patches = []
    for state in (legacy, arrow):
        transaction = state.transaction(label="trial").begin()
        state.feature_embedding_weights[key][:] = [9.0, -0.0]
        state.feature_embedding_weights["inserted"] = [5.0, 6.0]
        del state.feature_embedding_weights["é/last"]
        patches.append(transaction.capture_patch())
        transaction.rollback()
    assert patches[0] == patches[1]
    assert arrow.state_identity_record() == before
    assert arrow.to_json() == legacy.to_json()
    assert list(arrow.feature_embedding_weights) == list(legacy.feature_embedding_weights)
    assert arrow.feature_embedding_weights.statistics["overlay_rows"] == 0
    for state, patch in zip((legacy, arrow), patches):
        with state.transaction(label="replay") as transaction:
            transaction.apply_patch(patch)
    assert arrow.to_json() == legacy.to_json()
    assert arrow.state_identity_record() == legacy.state_identity_record()
    assert arrow.feature_embedding_weights.statistics["overlay_rows"] == 2
    assert mapped.readonly_row_array(key).tobytes() == np.asarray(ROWS[key], dtype=np.float64).tobytes()


def test_touched_row_deepcopy_has_no_mapping_or_tracking_owner(mapped):
    row = copy.deepcopy(mapped[next(iter(ROWS))])
    assert type(row) is list
    mapped.close()
    assert row == ROWS[next(iter(ROWS))]
    assert np.signbit(row[0])
    assert mapped.statistics["closed"] is True
    with pytest.raises(ArrowWeightError, match="closed"):
        mapped[next(iter(ROWS))]


def test_row_mutation_methods_and_revision_counts_match_existing_lists(mapped):
    legacy = ModalAutoencoderTrainingState(feature_embedding_weights=ROWS)
    arrow = ModalAutoencoderTrainingState(feature_embedding_weights=mapped)
    key = next(iter(ROWS))
    operations = [
        lambda row: row.__setitem__(0, 1),
        lambda row: row.append(3.0),
        lambda row: row.extend([4.0, 5.0]),
        lambda row: row.insert(1, 2.0),
        lambda row: row.__setitem__(slice(1, 3), [7.0]),
        lambda row: row.pop(),
        lambda row: row.remove(3.0),
        lambda row: row.reverse(),
        lambda row: row.sort(),
        lambda row: row.__iadd__([8.0]),
        lambda row: row.__imul__(2),
        lambda row: row.__delitem__(slice(1, 3)),
        lambda row: row.clear(),
    ]
    for operation in operations:
        operation(legacy.feature_embedding_weights[key])
        operation(arrow.feature_embedding_weights[key])
        assert arrow.state_revision == legacy.state_revision
        assert arrow.state_identity_record() == legacy.state_identity_record()
        assert arrow.to_json() == legacy.to_json()


def test_map_mutations_and_deleted_key_reinsertion_match_legacy_order(mapped):
    legacy = ModalAutoencoderTrainingState(feature_embedding_weights=ROWS)
    arrow = ModalAutoencoderTrainingState(feature_embedding_weights=mapped)
    operations = [
        lambda rows: rows.update({"new": [1.0], "empty": [2.0]}),
        lambda rows: rows.pop(next(iter(ROWS))),
        lambda rows: rows.setdefault(next(iter(ROWS)), [3.0]),
        lambda rows: rows.popitem(),
        lambda rows: rows.setdefault("another", []),
        lambda rows: rows.clear(),
    ]
    for operation in operations:
        operation(legacy.feature_embedding_weights)
        operation(arrow.feature_embedding_weights)
        assert list(arrow.feature_embedding_weights) == list(legacy.feature_embedding_weights)
        assert arrow.state_revision == legacy.state_revision
        assert arrow.state_identity_record() == legacy.state_identity_record()


def test_concurrent_mutation_is_rejected_before_numeric_state_changes(mapped):
    state = ModalAutoencoderTrainingState(feature_embedding_weights=mapped)
    transaction = state.transaction(label="owner").begin()
    errors = []
    key = next(iter(ROWS))

    def other_writer():
        try:
            state.feature_embedding_weights[key][0] = 99.0
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=other_writer)
    thread.start()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert len(errors) == 1 and isinstance(errors[0], StateTransactionConflictError)
    assert list(state.feature_embedding_weights[key]) == ROWS[key]
    assert state.state_revision == 0
    transaction.rollback()


def test_real_feature_reads_and_cpu_projection_updates_preserve_numeric_results(tmp_path):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample

    sample = build_us_code_sample(title="1", section="1", text="The agency shall retain records.")
    template = AdaptiveModalAutoencoder(compute_device="cpu")
    feature_keys = template._feature_keys_for(sample)
    rows = {key: [0.01 * (index + 1) for index in range(8)] for key in feature_keys}
    path = tmp_path / "features.arrow"
    descriptor = build_feature_embedding_weights_ipc(rows, path, base_checkpoint_sha256=BASE_SHA)
    mapped = _load(path, descriptor)
    try:
        legacy = AdaptiveModalAutoencoder(
            state=ModalAutoencoderTrainingState(feature_embedding_weights=rows), compute_device="cpu",
        )
        arrow = AdaptiveModalAutoencoder(
            state=ModalAutoencoderTrainingState(feature_embedding_weights=mapped), compute_device="cpu",
        )
        assert arrow._feature_embedding_adjustment(sample, dimensions=8) == legacy._feature_embedding_adjustment(sample, dimensions=8)
        assert arrow.state.feature_embedding_weights.statistics["mapped_row_reads"] > 0
        assert arrow.state.feature_embedding_weights.statistics["row_materializations"] == 0
        results = [model._apply_projection_update_batch(
            [sample], update_targets=("decoded_embedding",), learning_rate=0.01,
            l2_regularization=0.0, update_backend="python_sparse_batch",
        ) for model in (legacy, arrow)]
        assert results[0] == results[1]
        assert arrow.state.to_json() == legacy.state.to_json()
        assert arrow.state.state_identity_record() == legacy.state.state_identity_record()
        assert arrow.state.feature_embedding_weights.statistics["overlay_rows"] > 0
    finally:
        mapped.close()


def test_boundary_identity_is_stable_across_private_overlay_updates(tmp_path):
    path = tmp_path / "features.arrow"
    descriptor = build_feature_embedding_weights_ipc(ROWS, path, base_checkpoint_sha256=BASE_SHA)
    mapped = _load(path, descriptor)
    try:
        expected = {"artifact_sha256": descriptor["sha256"], "artifact_bytes": descriptor["size_bytes"],
                    "artifact_unchanged": True}
        assert mapped.verify_unchanged() == expected
        state = ModalAutoencoderTrainingState(feature_embedding_weights=mapped)
        state.feature_embedding_weights[next(iter(ROWS))][0] = 7.0
        state.feature_embedding_weights["new"] = [9.0]
        assert state.feature_embedding_weights.verify_unchanged() == expected
        assert mapped.verify_unchanged() == expected
        assert hashlib.sha256(path.read_bytes()).hexdigest() == descriptor["sha256"]
    finally:
        mapped.close()


@pytest.mark.parametrize("change", ["mutate", "replace", "unlink", "parent_alias"])
def test_boundary_rejects_persistent_bytes_or_path_identity_change(tmp_path, change):
    directory = tmp_path / "original"
    path = directory / "features.arrow"
    descriptor = build_feature_embedding_weights_ipc(ROWS, path, base_checkpoint_sha256=BASE_SHA)
    mapped = _load(path, descriptor)
    try:
        if change == "mutate":
            raw = path.read_bytes()
            offset = raw.index(struct.pack("<d", ROWS[next(iter(ROWS))][1]))
            with path.open("r+b") as stream:
                stream.seek(offset)
                stream.write(struct.pack("<d", 0.5))
        elif change == "replace":
            replacement = directory / "replacement.arrow"
            replacement.write_bytes(path.read_bytes())
            os.replace(replacement, path)
        elif change == "unlink":
            path.unlink()
        else:
            moved = tmp_path / "moved"
            directory.rename(moved)
            directory.symlink_to(moved, target_is_directory=True)
        with pytest.raises(ArrowWeightError, match="changed|available"):
            mapped.verify_unchanged()
    finally:
        mapped.close()


@pytest.mark.parametrize("kind", ["file_alias", "parent_alias", "directory", "fifo"])
def test_loader_rejects_aliases_and_nonregular_files(tmp_path, kind):
    real = tmp_path / "real"
    path = real / "features.arrow"
    descriptor = build_feature_embedding_weights_ipc(ROWS, path, base_checkpoint_sha256=BASE_SHA)
    if kind == "file_alias":
        alias = tmp_path / "alias.arrow"
        alias.symlink_to(path)
    elif kind == "parent_alias":
        alias = tmp_path / "alias"
        alias.symlink_to(real, target_is_directory=True)
        alias /= path.name
    elif kind == "directory":
        alias = real
    else:
        alias = tmp_path / "pipe"
        os.mkfifo(alias)
    with pytest.raises(ArrowWeightError, match="symlink|regular"):
        _load(alias, descriptor)


def test_relative_path_is_captured_once_without_changing_existing_api(tmp_path, monkeypatch):
    descriptor = build_feature_embedding_weights_ipc(ROWS, tmp_path / "features.arrow",
                                                    base_checkpoint_sha256=BASE_SHA)
    monkeypatch.chdir(tmp_path)
    mapped = _load("features.arrow", descriptor)
    try:
        monkeypatch.chdir(tmp_path.parent)
        assert mapped.verify_unchanged()["artifact_unchanged"] is True
        mapped.verify_source_rows(ROWS)
    finally:
        mapped.close()


@pytest.mark.parametrize("replacement", [False, True])
def test_post_open_verification_rejects_changes_and_releases_fd(tmp_path, monkeypatch, replacement):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder_arrow_weights as codec
    path = tmp_path / "features.arrow"
    descriptor = build_feature_embedding_weights_ipc(ROWS, path, base_checkpoint_sha256=BASE_SHA)
    original_preflight, original_open = codec._preflight, os.open
    opened = []

    def record_open(*args, **kwargs):
        fd = original_open(*args, **kwargs)
        opened.append(fd)
        return fd

    def change_after_hash(buffer):
        result = original_preflight(buffer)
        if replacement:
            changed = tmp_path / "changed.arrow"
            changed.write_bytes(path.read_bytes())
            os.replace(changed, path)
        else:
            raw = path.read_bytes()
            offset = raw.index(struct.pack("<d", ROWS[next(iter(ROWS))][1]))
            with path.open("r+b") as stream:
                stream.seek(offset)
                stream.write(struct.pack("<d", 0.5))
        return result

    monkeypatch.setattr(codec.os, "open", record_open)
    monkeypatch.setattr(codec, "_preflight", change_after_hash)
    with pytest.raises(ArrowWeightError, match="changed"):
        _load(path, descriptor)
    assert len(opened) == 1
    with pytest.raises(OSError):
        os.fstat(opened[0])


def test_close_releases_fd_but_exported_readonly_array_and_detached_values_survive(tmp_path):
    path = tmp_path / "features.arrow"
    descriptor = build_feature_embedding_weights_ipc(ROWS, path, base_checkpoint_sha256=BASE_SHA)
    mapped = _load(path, descriptor)
    state = ModalAutoencoderTrainingState(feature_embedding_weights=mapped)
    exported = state.feature_embedding_weights.readonly_row_array(next(iter(ROWS)))
    detached = copy.deepcopy(state.feature_embedding_weights)
    fd = mapped._base.fd
    before = mapped.statistics
    mapped.close()
    mapped.close()
    with pytest.raises(OSError):
        os.fstat(fd)
    assert mapped._base.mapped is mapped._base.reader is mapped._base.file_buffer is None
    assert mapped._base.values == mapped._base.offsets == []
    assert exported.tobytes() == np.asarray(ROWS[next(iter(ROWS))], dtype=np.float64).tobytes()
    assert not exported.flags.writeable
    with pytest.raises(ValueError):
        exported.setflags(write=True)
    assert np.signbit(detached[next(iter(ROWS))][0])
    assert mapped.statistics == {**before, "closed": True}
    with pytest.raises(ArrowWeightError, match="closed"):
        state.feature_embedding_weights.verify_unchanged()
    with pytest.raises(ArrowWeightError, match="closed"):
        state.feature_embedding_weights[next(iter(ROWS))]


@pytest.mark.parametrize("size", [True, 1.0, 0, -1, 512 * 1024 * 1024 + 1])
def test_loader_rejects_invalid_or_oversized_descriptor_before_open(tmp_path, monkeypatch, size):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder_arrow_weights as codec
    def must_not_open(*args, **kwargs):
        raise AssertionError("invalid descriptor reached file opening")
    monkeypatch.setattr(codec.os, "open", must_not_open)
    with pytest.raises(ArrowWeightError, match="byte bound"):
        _load(tmp_path / "absent.arrow", {"sha256": BASE_SHA, "size_bytes": size})


@pytest.mark.parametrize("field", ["batch_rows", "scalar_count", "buffer_size", "body_size"])
def test_forged_large_lengths_rejected_before_arrow_decoder(tmp_path, monkeypatch, field):
    import pyarrow as pa
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder_arrow_weights as codec
    path = tmp_path / "features.arrow"
    build_feature_embedding_weights_ipc(ROWS, path, base_checkpoint_sha256=BASE_SHA)
    raw = bytearray(path.read_bytes())
    footer_start = len(raw) - 10 - struct.unpack_from("<I", raw, len(raw) - 10)[0]
    footer = codec._FlatBuffer(memoryview(raw)[footer_start:len(raw) - 10])
    blocks, _ = footer.vector(footer.root, 3, 24)
    offset = footer.number("<q", blocks)
    metadata_size = footer.number("<i", blocks + 8)
    message = codec._FlatBuffer(memoryview(raw)[offset + 8:offset + metadata_size])
    batch = message.indirect(message.field(message.root, 2))
    if field == "batch_rows":
        target = offset + 8 + message.field(batch, 0)
    elif field == "scalar_count":
        nodes, _ = message.vector(batch, 1, 16)
        target = offset + 8 + nodes + 32
    elif field == "buffer_size":
        buffers, _ = message.vector(batch, 2, 16)
        target = offset + 8 + buffers + 16 * 6 + 8
    else:
        target = footer_start + blocks + 16
    struct.pack_into("<q", raw, target, 1 << 60)
    path.write_bytes(raw)
    def decoder_must_not_run(*args, **kwargs):
        raise AssertionError("forged size reached Arrow decoding")
    monkeypatch.setattr(pa.ipc, "open_file", decoder_must_not_run)
    with pytest.raises(ArrowWeightError, match="bounds|length|exceed"):
        _load(path, {"sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)})
