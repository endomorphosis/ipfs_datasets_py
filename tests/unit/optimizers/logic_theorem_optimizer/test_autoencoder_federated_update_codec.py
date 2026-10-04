"""Binary delta artifacts enforce byte, round, dtype and resource identity."""

from dataclasses import replace
import base64
import hashlib
import json
import math
import struct

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_federated import (
    ClientSpec, FederatedRound, ParameterSpec, make_client_update, parameter_digest,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_federated_update_codec import (
    MAGIC, read_client_update, write_client_update,
)


def setup(dtype="float64", size=8):
    parameters = (ParameterSpec("projection.weight", (size,), dtype),)
    base = {"projection.weight": [0.0] * size}
    round_spec = FederatedRound("round", "model", "legacy_hub_v1", 8, "test",
        "profile", "a" * 64, parameter_digest(parameters, base), "e" * 64,
        parameters, (ClientSpec("worker", 10, "d" * 64),))
    return round_spec, make_client_update(round_spec, "worker",
        {"projection.weight": {0: -0.0, size - 1: 1.5}},
        local_steps=1, local_data_sha256="d" * 64)


@pytest.mark.parametrize("dtype", ["float32", "float64"])
@pytest.mark.parametrize("size", [8, 8201])
def test_artifact_digest_is_update_commitment_and_cid_addresses_exact_bytes(tmp_path, dtype, size):
    round_spec, update = setup(dtype, size)
    path = tmp_path / "update.bin"
    receipt = write_client_update(path, round_spec, update)
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == receipt["sha256"] == update.update_sha256
    assert receipt["bytes"] == len(raw)
    cid = receipt["cidv1"]
    decoded = base64.b32decode(cid[1:].upper() + "=" * ((-len(cid[1:])) % 8))
    assert decoded[:4] == b"\x01\x55\x12\x20"
    assert decoded[4:].hex() == receipt["sha256"]
    recovered = read_client_update(path, round_spec, expected_sha256=receipt["sha256"],
                                   expected_cidv1=cid)
    assert recovered == update
    assert math.copysign(1.0, recovered.deltas["projection.weight"][0]) == -1.0


def test_dense_rows_span_binary_chunks_and_contain_no_json_numbers(tmp_path):
    round_spec, _ = setup(size=8201)
    update = make_client_update(round_spec, "worker",
        {"projection.weight": [float(index) for index in range(8201)]},
        local_steps=1, local_data_sha256="d" * 64)
    path = tmp_path / "dense.bin"
    receipt = write_client_update(path, round_spec, update)
    raw = path.read_bytes()
    assert b'"deltas"' not in raw and b'"coordinates"' not in raw
    assert b'"values"' not in raw and b'"values_le_hex"' not in raw
    assert read_client_update(path, round_spec, expected_sha256=receipt["sha256"]) == update


def test_empty_update_roundtrips(tmp_path):
    round_spec, _ = setup()
    update = make_client_update(round_spec, "worker", {}, local_steps=1,
                                local_data_sha256="d" * 64)
    path = tmp_path / "empty.bin"
    receipt = write_client_update(path, round_spec, update)
    assert read_client_update(path, round_spec, expected_sha256=receipt["sha256"]) == update


def test_writer_rejects_foreign_round_before_file_creation(tmp_path):
    round_spec, update = setup()
    path = tmp_path / "absent" / "update.bin"
    with pytest.raises(ValueError, match="approved round"):
        write_client_update(path, replace(round_spec, round_id="other"), update)
    assert not path.parent.exists()


def test_exclusive_writer_preserves_existing_artifact(tmp_path):
    round_spec, update = setup()
    path = tmp_path / "update.bin"
    write_client_update(path, round_spec, update)
    previous = path.read_bytes()
    with pytest.raises(FileExistsError):
        write_client_update(path, round_spec, update)
    assert path.read_bytes() == previous
    assert not list(tmp_path.glob(".federated-update-*"))


def test_writer_byte_limit_does_not_publish_partial_file(tmp_path):
    round_spec, update = setup()
    path = tmp_path / "update.bin"
    with pytest.raises(ValueError, match="byte limit"):
        write_client_update(path, round_spec, update, max_bytes=32)
    assert not path.exists()
    assert not list(tmp_path.glob(".federated-update-*"))


@pytest.mark.parametrize("mutation", ["digest", "truncated", "trailing", "magic", "row_count", "coordinate_count", "index", "nan"])
def test_corrupt_frames_or_byte_digest_are_rejected(tmp_path, mutation):
    round_spec, update = setup()
    path = tmp_path / "update.bin"
    receipt = write_client_update(path, round_spec, update)
    raw = bytearray(path.read_bytes())
    header_size = struct.unpack_from("<Q", raw, len(MAGIC))[0]
    row_count_offset = len(MAGIC) + 8 + header_size
    name_size = struct.unpack_from("<Q", raw, row_count_offset + 8)[0]
    coordinates_offset = row_count_offset + 8 + 8 + name_size
    if mutation == "truncated":
        del raw[-1:]
    elif mutation == "trailing":
        raw += b"extra"
    elif mutation == "magic":
        raw[0] ^= 1
    elif mutation == "row_count":
        struct.pack_into("<Q", raw, row_count_offset, 2**64 - 1)
    elif mutation == "coordinate_count":
        struct.pack_into("<Q", raw, coordinates_offset, 2**64 - 1)
    elif mutation == "index":
        struct.pack_into("<Q", raw, coordinates_offset + 8, 8)
    elif mutation == "nan":
        struct.pack_into("<d", raw, coordinates_offset + 16, float("nan"))
    path.write_bytes(raw)
    expected = receipt["sha256"] if mutation == "digest" else hashlib.sha256(raw).hexdigest()
    if mutation == "digest":
        expected = "0" * 64
    with pytest.raises(ValueError):
        read_client_update(path, round_spec, expected_sha256=expected)


def test_reader_rejects_foreign_round_or_cid_profile(tmp_path):
    round_spec, update = setup()
    path = tmp_path / "update.bin"
    receipt = write_client_update(path, round_spec, update)
    with pytest.raises(ValueError, match="approved round"):
        read_client_update(path, replace(round_spec, embedding_producer_sha256="f" * 64),
                           expected_sha256=receipt["sha256"])
    with pytest.raises(ValueError, match="CIDv1"):
        read_client_update(path, round_spec, expected_sha256=receipt["sha256"],
                           expected_cidv1="bafy-other-profile")


def test_float32_artifact_rejects_nonrepresentable_binary_values(tmp_path):
    round_spec, update = setup(dtype="float32")
    path = tmp_path / "update.bin"
    write_client_update(path, round_spec, update)
    raw = bytearray(path.read_bytes())
    struct.pack_into("<d", raw, len(raw) - 8, 1.500000000000001)
    path.write_bytes(raw)
    with pytest.raises(ValueError, match="typed numeric commitment"):
        read_client_update(path, round_spec, expected_sha256=hashlib.sha256(raw).hexdigest())


def test_duplicate_or_noncanonical_metadata_is_rejected(tmp_path):
    round_spec, update = setup()
    path = tmp_path / "update.bin"
    write_client_update(path, round_spec, update)
    raw = path.read_bytes()
    length = struct.unpack_from("<Q", raw, len(MAGIC))[0]
    old = raw[len(MAGIC) + 8:len(MAGIC) + 8 + length]
    header = json.loads(old)
    for malformed in (b'{"schema":"duplicate",' + old[1:],
                      json.dumps(header, indent=2).encode()):
        corrupt = MAGIC + struct.pack("<Q", len(malformed)) + malformed + raw[len(MAGIC) + 8 + length:]
        path.write_bytes(corrupt)
        with pytest.raises(ValueError):
            read_client_update(path, round_spec, expected_sha256=hashlib.sha256(corrupt).hexdigest())


@pytest.mark.parametrize("limit", [True, 0, -1, 8])
def test_reader_enforces_byte_bound(tmp_path, limit):
    round_spec, update = setup()
    path = tmp_path / "update.bin"
    receipt = write_client_update(path, round_spec, update)
    with pytest.raises(ValueError):
        read_client_update(path, round_spec, expected_sha256=receipt["sha256"], max_bytes=limit)
