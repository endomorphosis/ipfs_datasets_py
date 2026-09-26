"""Read-only input-lineage checks leave state reconstruction and recovery intact."""
import os

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder_checkpoint as codec
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import ModalAutoencoderTrainingState


IDENTITY = {"sha256": "1" * 64, "bytes": 1024}


def _fixture(tmp_path):
    base = ModalAutoencoderTrainingState()
    base.feature_embedding_weights["test"] = [0.25, -0.0]
    path, deltas = tmp_path / "state.bin", tmp_path / "state.deltas"
    codec.write_checkpoint_atomic(path, base, metadata={"corpus_input_identity": IDENTITY, "cycle": 0})
    changed = base.copy()
    changed._state_identity_tracker.restore_revision(base.state_revision)
    changed.feature_embedding_weights["test"] = [0.5, -0.0]
    segment = codec.serialize_delta(base, changed, metadata={"cycle": 1, "corpus_input_identity": IDENTITY})
    metadata_only = codec.serialize_delta(changed, changed, metadata={"cycle": 2, "corpus_input_identity": IDENTITY})
    deltas.write_bytes(segment + metadata_only)
    return path, deltas, base, changed, segment, metadata_only


def test_metadata_matches_codec_manifests_without_reconstruction_or_writes(tmp_path, monkeypatch):
    path, deltas, *_ = _fixture(tmp_path)
    raw, delta_raw = path.read_bytes(), deltas.read_bytes()
    full, _, _ = codec._parse_container(raw)
    segments, _, _ = codec.iter_delta_segments(delta_raw)
    expected = (full["metadata"], *(manifest.metadata for manifest, _ in segments))

    def forbidden(*args, **kwargs):
        pytest.fail("metadata preflight must not construct/decode state")

    for name in ("_state_class", "_decode_state_payload", "_state_from_data", "_apply_delta"):
        monkeypatch.setattr(codec, name, forbidden)
    result = codec.read_checkpoint_input_metadata(path, delta_path=deltas)
    assert result == expected
    assert len(result) == 3  # The unchanged metadata-only delta matters too.
    assert path.read_bytes() == raw and deltas.read_bytes() == delta_raw
    result[0]["corpus_input_identity"]["bytes"] = -1
    assert codec.read_checkpoint_input_metadata(path)[0]["corpus_input_identity"] == IDENTITY


@pytest.mark.parametrize("cut", [1, codec._HEADER.size - 1, codec._HEADER.size, -1])
def test_torn_delta_tail_remains_for_normal_recovering_loader(tmp_path, cut):
    path, deltas, base, changed, segment, metadata_only = _fixture(tmp_path)
    prefix = metadata_only[:cut]
    deltas.write_bytes(segment + prefix)
    before = deltas.read_bytes()
    info = codec.read_checkpoint_input_metadata(path, delta_path=deltas)
    assert len(info) == 2
    assert deltas.read_bytes() == before
    loaded = codec.load_checkpoint(path, delta_path=deltas, recover=True)
    assert loaded.recovered_tail_bytes == len(prefix)
    assert loaded.state.to_dict() == changed.to_dict()
    assert deltas.read_bytes() == segment


@pytest.mark.parametrize("location", ["manifest", "payload", "kind", "unsafe_length", "schema"])
def test_complete_bad_delta_is_rejected_without_truncation(tmp_path, location):
    path, deltas, _, _, segment, _ = _fixture(tmp_path)
    bad = bytearray(segment)
    if location == "manifest":
        bad[codec._HEADER.size] ^= 1
    elif location == "payload":
        bad[-1] ^= 1
    elif location in {"kind", "unsafe_length"}:
        header = list(codec._HEADER.unpack_from(bad))
        if location == "kind":
            header[0] = codec.CHECKPOINT_MAGIC
        else:
            header[4] = codec._MAX_PAYLOAD_BYTES + 1
        bad[:codec._HEADER.size] = codec._HEADER.pack(*header)
    else:
        manifest, payload, _ = codec._parse_container(segment)
        manifest["schema_version"] = "unsupported"
        bad = codec._container_bytes(codec.DELTA_MAGIC, manifest, payload)
    deltas.write_bytes(bad)
    with pytest.raises(codec.ModalAutoencoderCheckpointError):
        codec.read_checkpoint_input_metadata(path, delta_path=deltas)
    assert deltas.read_bytes() == bad


@pytest.mark.parametrize("location", ["manifest", "payload", "trailing", "metadata_shape"])
def test_complete_bad_base_is_rejected_without_state_decode(tmp_path, location):
    path, *_ = _fixture(tmp_path)
    bad = bytearray(path.read_bytes())
    if location == "manifest":
        bad[codec._HEADER.size] ^= 1
    elif location == "payload":
        bad[-1] ^= 1
    elif location == "trailing":
        bad.extend(b"suffix")
    else:
        manifest, payload, _ = codec._parse_container(bytes(bad))
        manifest["metadata"] = ["invalid"]
        bad = codec._container_bytes(codec.CHECKPOINT_MAGIC, manifest, payload)
    path.write_bytes(bad)
    with pytest.raises(codec.ModalAutoencoderCheckpointError):
        codec.read_checkpoint_input_metadata(path)
    assert path.read_bytes() == bad


def test_legacy_json_does_not_decode_state_and_complete_deltas_still_bind(tmp_path, monkeypatch):
    path, deltas, base, _, _, _ = _fixture(tmp_path)
    path.write_text(base.to_json())
    before = path.read_bytes()
    monkeypatch.setattr(codec, "_state_from_data", lambda *_args, **_kwargs: pytest.fail("state reconstruction"))
    metadata = codec.read_checkpoint_input_metadata(path, delta_path=deltas)
    assert metadata[0] == {}
    assert metadata[1]["corpus_input_identity"] == IDENTITY
    assert path.read_bytes() == before


def test_legacy_json_reads_only_prefix_without_binary_size_policy(tmp_path, monkeypatch):
    path = tmp_path / "legacy.json"
    path.write_bytes(b" " * 8193 + b'{"large_legacy_field":"' + b"x" * 100_000 + b'"}')
    original = os.fdopen
    reads = []

    class Observed:
        def __init__(self, stream):
            self.stream = stream

        def __getattr__(self, key):
            return getattr(self.stream, key)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def read(self, size):
            data = self.stream.read(size)
            reads.append((size, len(data)))
            return data

    monkeypatch.setattr(codec.os, "fdopen", lambda *args, **kwargs: Observed(original(*args, **kwargs)))
    monkeypatch.setattr(codec, "_MAX_PAYLOAD_BYTES", 1)
    monkeypatch.setattr(codec, "_MAX_MANIFEST_BYTES", 1)
    assert codec.read_checkpoint_input_metadata(path) == ({},)
    assert reads == [(4096, 4096)] * 3


def test_all_complete_metadata_retained_even_when_full_checkpoint_supersedes_delta(tmp_path):
    path, deltas, _, changed, _, _ = _fixture(tmp_path)
    codec.write_checkpoint_atomic(path, changed, metadata={"newer_full": True})
    metadata = codec.read_checkpoint_input_metadata(path, delta_path=deltas)
    assert metadata == ({"newer_full": True}, {"cycle": 1, "corpus_input_identity": IDENTITY},
                        {"cycle": 2, "corpus_input_identity": IDENTITY})


def test_empty_and_absent_delta_log(tmp_path):
    path, deltas, *_ = _fixture(tmp_path)
    expected = codec.read_checkpoint_input_metadata(path)
    deltas.write_bytes(b"")
    assert codec.read_checkpoint_input_metadata(path, delta_path=deltas) == expected
    deltas.unlink()
    assert codec.read_checkpoint_input_metadata(path, delta_path=deltas) == expected


def test_forged_maximum_torn_length_is_not_allocated(tmp_path):
    path, deltas, *_ = _fixture(tmp_path)
    header = codec._HEADER.pack(codec.DELTA_MAGIC, codec.CONTAINER_VERSION, 0, 1,
                                codec._MAX_PAYLOAD_BYTES, b"0" * 32, b"0" * 32)
    deltas.write_bytes(header)
    assert len(codec.read_checkpoint_input_metadata(path, delta_path=deltas)) == 1
    assert deltas.read_bytes() == header


def test_non_regular_source_fails_without_blocking(tmp_path):
    path = tmp_path / "fifo"
    os.mkfifo(path)
    with pytest.raises(codec.CheckpointCorruptionError, match="regular file"):
        codec.read_checkpoint_input_metadata(path)
