"""Binary artifacts for owner-bound federated deltas, without weight JSON.

The artifact bytes are exactly the v1 update commitment stream. Consequently
the SHA256 of the complete file equals ``ClientUpdate.update_sha256``. Small
length-prefixed metadata describes the round and rows; coordinates and deltas
use little-endian uint64/float64 pairs. The bound layout preserves float32
semantics where applicable. This module performs no network or database I/O.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import tempfile

from .autoencoder_federated import ClientUpdate, FederatedRound, UPDATE_SCHEMA, make_client_update


MAGIC = b"autoencoder-federated-update\x00v1\x00"
_U64 = struct.Struct("<Q")
_PAIR = struct.Struct("<Qd")
_CHUNK = 4096
_MAX_METADATA = 16_384
_FLAGS = {"qualified": False, "admitted": False, "formalized": False,
          "owner_verified": False, "promotion_performed": False,
          "publication_performed": False}
_HEADER_FIELDS = ("round_sha256", "base_sha256", "base_parameters_sha256",
                  "layout_sha256", "client_id", "local_data_sha256", "local_steps")


def _header(update):
    return {"schema": UPDATE_SCHEMA,
            **{name: getattr(update, name) for name in _HEADER_FIELDS}, **_FLAGS}


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def _raw_cid(sha256):
    # CIDv1, raw codec, sha2-256 multihash, base32 without padding. This
    # addresses one complete binary artifact, not a UnixFS chunked DAG.
    encoded = base64.b32encode(b"\x01\x55\x12\x20" + bytes.fromhex(sha256))
    return "b" + encoded.decode("ascii").lower().rstrip("=")


def _validate(round_spec, update):
    if type(round_spec) is not FederatedRound or type(update) is not ClientUpdate:
        raise ValueError("a federated round and client update are required")
    expected = make_client_update(round_spec, update.client_id, update.deltas,
        local_steps=update.local_steps, local_data_sha256=update.local_data_sha256)
    if update != expected or update.update_sha256 != expected.update_sha256:
        raise ValueError("client update differs from the approved round")
    return expected


def _chunks(update):
    yield MAGIC
    raw = _raw(_header(update))
    yield _U64.pack(len(raw))
    yield raw
    yield _U64.pack(len(update._delta_rows))
    for name, coordinates in update._delta_rows:
        raw = _raw({"name": name})
        yield _U64.pack(len(raw))
        yield raw
        yield _U64.pack(len(coordinates))
        for offset in range(0, len(coordinates), _CHUNK):
            chunk = coordinates[offset:offset + _CHUNK]
            yield struct.pack("<" + "Qd" * len(chunk),
                              *(item for pair in chunk for item in pair))


def write_client_update(path, round_spec, update, *, max_bytes=512 * 1024 * 1024):
    """Publish a fresh fsynced artifact; existing destination files are rejected.

    Validation precedes any file creation. Failures before publication leave
    no destination. The result contains SHA256, byte count, update identity and
    a CIDv1 using the explicit raw/sha2-256 profile,
    suitable for an existing artifact store or a small MCP++ control message.
    """
    update = _validate(round_spec, update)
    if type(max_bytes) is not int or max_bytes < 1:
        raise ValueError("max_bytes must be a positive integer")
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    digest, count = hashlib.sha256(), 0
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent,
                                         prefix=".federated-update-", delete=False) as stream:
            temporary = Path(stream.name)
            for block in _chunks(update):
                count += len(block)
                if count > max_bytes:
                    raise ValueError("federated update exceeds the artifact byte limit")
                stream.write(block)
                digest.update(block)
            stream.flush()
            os.fsync(stream.fileno())
        sha256 = digest.hexdigest()
        if sha256 != update.update_sha256:
            raise ValueError("binary update encoding differs from its numeric commitment")
        os.link(temporary, destination)
        directory = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return {"sha256": sha256, "bytes": count, "update_sha256": sha256,
                "cidv1": _raw_cid(sha256)}
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _pairs(values):
    result = {}
    for key, value in values:
        if key in result:
            raise ValueError("duplicate metadata key")
        result[key] = value
    return result


def read_client_update(path, round_spec, *, expected_sha256, expected_cidv1=None,
                       max_bytes=512 * 1024 * 1024):
    """Read and validate an artifact against a trusted round and byte digest.

    Lengths and coordinate counts are checked before allocating rows. Parsing
    and hashing use the same open stream. A supplied digest proves byte identity;
    trusted worker authentication and round approval remain owner responsibilities.
    """
    if (type(round_spec) is not FederatedRound or type(expected_sha256) is not str
            or len(expected_sha256) != 64
            or any(character not in "0123456789abcdef" for character in expected_sha256)):
        raise ValueError("a federated round and lowercase SHA256 are required")
    if expected_cidv1 is not None and (type(expected_cidv1) is not str
                                     or expected_cidv1 != _raw_cid(expected_sha256)):
        raise ValueError("CIDv1 must match the raw/sha2-256 artifact profile")
    round_spec = FederatedRound(**{
        name: getattr(round_spec, name) for name in round_spec.__dataclass_fields__})
    if type(max_bytes) is not int or max_bytes < 1:
        raise ValueError("max_bytes must be a positive integer")
    digest, consumed = hashlib.sha256(), 0
    with Path(path).open("rb") as stream:
        size = os.fstat(stream.fileno()).st_size
        if size < len(MAGIC) + 16 or size > max_bytes:
            raise ValueError("federated update file exceeds the permitted byte limits")

        def read(count):
            nonlocal consumed
            if count > size - consumed:
                raise ValueError("truncated federated update")
            block = stream.read(count)
            if len(block) != count:
                raise ValueError("truncated federated update")
            consumed += count
            digest.update(block)
            return block

        def integer():
            return _U64.unpack(read(8))[0]

        def metadata():
            count = integer()
            if count > _MAX_METADATA:
                raise ValueError("federated metadata exceeds the byte limit")
            raw = read(count)
            try:
                value = json.loads(raw, object_pairs_hook=_pairs,
                    parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite metadata")))
            except (UnicodeError, json.JSONDecodeError) as error:
                raise ValueError("invalid federated metadata") from error
            if type(value) is not dict or _raw(value) != raw:
                raise ValueError("federated metadata must use canonical JSON")
            return value

        if read(len(MAGIC)) != MAGIC:
            raise ValueError("unsupported federated update artifact")
        header = metadata()
        if set(header) != {"schema", *_HEADER_FIELDS, *_FLAGS}:
            raise ValueError("closed federated update metadata required")
        empty = make_client_update(round_spec, header["client_id"], {},
            local_steps=header["local_steps"], local_data_sha256=header["local_data_sha256"])
        if _raw(header) != _raw(_header(empty)):
            raise ValueError("update metadata differs from the approved round")
        specs = {spec.name: spec for spec in round_spec.parameters}
        row_count = integer()
        if row_count > len(specs):
            raise ValueError("update contains undeclared parameter rows")
        deltas, previous_name = {}, None
        for _ in range(row_count):
            row = metadata()
            if set(row) != {"name"} or type(row["name"]) is not str or row["name"] not in specs:
                raise ValueError("update contains an undeclared parameter")
            name = row["name"]
            if previous_name is not None and name <= previous_name:
                raise ValueError("update row names must be unique and sorted")
            previous_name = name
            count = integer()
            if count > specs[name].size or count * _PAIR.size > size - consumed:
                raise ValueError("update coordinate count exceeds its layout or byte limit")
            coordinates, previous_index = {}, -1
            for offset in range(0, count, _CHUNK):
                block = read(min(_CHUNK, count - offset) * _PAIR.size)
                for index, value in _PAIR.iter_unpack(block):
                    if index <= previous_index or index >= specs[name].size or not math.isfinite(value):
                        raise ValueError("update coordinates must be sorted, unique, finite and in range")
                    previous_index = index
                    coordinates[index] = value
            deltas[name] = coordinates
        if consumed != size or stream.read(1):
            raise ValueError("trailing federated update bytes")
    if digest.hexdigest() != expected_sha256:
        raise ValueError("federated update byte digest differs")
    update = make_client_update(round_spec, header["client_id"], deltas,
        local_steps=header["local_steps"], local_data_sha256=header["local_data_sha256"])
    if update.update_sha256 != expected_sha256:
        raise ValueError("update values differ from their typed numeric commitment")
    return update


__all__ = ["MAGIC", "read_client_update", "write_client_update"]
