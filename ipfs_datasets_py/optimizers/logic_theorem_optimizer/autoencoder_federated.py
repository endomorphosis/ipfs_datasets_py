"""Dependency-light same-base FedAvg candidates for declared numeric parameters.

This module combines local model deltas; it does not interpret legacy sparse
postimage patches, merge optimizer state, publish artifacts, or select a model.
An owner must verify the base checkpoint and its extracted parameter digest,
approve client sample counts, and independently qualify the resulting candidate.
Parameter names form an explicit whitelist, including semantic sparse row keys
when applicable. New keys and layout changes require a new round.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
import math
import re
import struct


ROUND_SCHEMA = "autoencoder-federated-round/v1"
UPDATE_SCHEMA = "autoencoder-federated-update/v1"
CANDIDATE_SCHEMA = "autoencoder-federated-candidate/v1"
ALGORITHM = "same-base-fedavg/v1"
_PARAMETER_DOMAIN = b"autoencoder-federated-parameters\x00v1\x00"
_UPDATE_DOMAIN = b"autoencoder-federated-update\x00v1\x00"
_HASH_CHUNK_COORDINATES = 4096
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_RESERVED = frozenset({
    "optimizer", "optimizer_state", "adam", "exp_avg", "exp_avg_sq", "momentum",
    "metadata", "provenance", "source_provenance", "progress", "schema_version",
    "qualified", "admitted", "formalized", "promotion_performed", "owner_verified",
    "decoded_embeddings", "family_logits", "proof_feedback_version_fingerprint",
    "applied_proof_feedback_ids", "applied_leanstral_guidance_ids", "applied_todo_ids",
})
_FALSE = {"qualified": False, "admitted": False, "formalized": False,
          "owner_verified": False, "promotion_performed": False,
          "publication_performed": False}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _text(value, label):
    _require(type(value) is str and 0 < len(value) <= 512
             and all(ord(character) >= 32 and ord(character) != 127 for character in value),
             label + " must be a bounded nonempty string without control characters")
    return value


def _sha(value, label):
    _require(type(value) is str and _SHA.fullmatch(value) is not None,
             label + " must be a lowercase SHA256 digest")
    return value


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def _digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _hash_metadata(hasher, metadata):
    raw = _raw(metadata)
    hasher.update(struct.pack("<Q", len(raw)))
    hasher.update(raw)


def _hash_values(hasher, values, dtype):
    code = "f" if dtype == "float32" else "d"
    for offset in range(0, len(values), _HASH_CHUNK_COORDINATES):
        chunk = values[offset:offset + _HASH_CHUNK_COORDINATES]
        hasher.update(struct.pack("<" + str(len(chunk)) + code, *chunk))


@dataclass(frozen=True, slots=True)
class ParameterSpec:
    """An owner-declared trainable parameter with a fixed flattened layout."""

    name: str
    shape: tuple[int, ...]
    dtype: str

    def __post_init__(self):
        _text(self.name, "parameter name")
        _require(not (_RESERVED & set(re.split(r"[./:|]", self.name.lower()))),
                 "metadata, sample memories and optimizer state cannot be parameters")
        _require(type(self.shape) in (list, tuple) and len(self.shape) <= 16
                 and all(type(size) is int and 0 < size <= 2**31 - 1 for size in self.shape),
                 "parameter shape requires positive integer dimensions")
        _require(type(self.dtype) is str and self.dtype in {"float32", "float64"},
                 "parameter dtype must be float32 or float64")
        object.__setattr__(self, "shape", tuple(self.shape))

    @property
    def size(self):
        return math.prod(self.shape)

    @property
    def manifest(self):
        return {"name": self.name, "shape": list(self.shape), "dtype": self.dtype}


def _specs(parameters):
    _require(type(parameters) in (list, tuple) and bool(parameters),
             "a nonempty declared parameter layout is required")
    _require(all(type(spec) is ParameterSpec for spec in parameters), "ParameterSpec entries required")
    # Revalidate even frozen objects: an unsafe caller can bypass dataclass setters.
    normalized = tuple(sorted((ParameterSpec(spec.name, spec.shape, spec.dtype)
                               for spec in parameters), key=lambda spec: spec.name))
    _require(len({spec.name for spec in normalized}) == len(normalized), "duplicate parameter name")
    return normalized


def _number(value, dtype, label):
    _require(type(value) in (int, float), label + " requires builtin numeric values, excluding bool")
    try:
        converted = float(value)
        _require(math.isfinite(converted), label + " must be finite")
        if dtype == "float32":
            converted = struct.unpack("<f", struct.pack("<f", converted))[0]
        _require(math.isfinite(converted), label + " overflows " + dtype)
    except (OverflowError, struct.error) as error:
        raise ValueError(label + " overflows " + dtype) from error
    return converted


def _parameters(specs, values):
    _require(type(values) is dict and set(values) == {spec.name for spec in specs},
             "base parameters must match the exact declared parameter names")
    rows = []
    for spec in specs:
        row = values[spec.name]
        _require(type(row) in (list, tuple) and len(row) == spec.size,
                 "base parameter shape differs: " + spec.name)
        rows.append((spec.name, tuple(_number(value, spec.dtype, spec.name) for value in row)))
    return tuple(rows)


def _parameter_digest(specs, rows):
    hasher = hashlib.sha256(_PARAMETER_DOMAIN)
    hasher.update(struct.pack("<Q", len(specs)))
    for spec, (_, values) in zip(specs, rows):
        _hash_metadata(hasher, spec.manifest)
        _hash_values(hasher, values, spec.dtype)
    return hasher.hexdigest()


def parameter_digest(parameter_specs, base_parameters):
    """Commit exact dtype-normalized values, names and shapes, including -0.0.

    Encoding v1 is SHA256 over ``autoencoder-federated-parameters\\0v1\\0``,
    uint64 little-endian parameter count, then each sorted parameter's canonical
    ASCII JSON metadata prefixed by its uint64 byte length, and its flattened
    little-endian IEEE float32/float64 bytes. Shapes imply buffer lengths. Binary
    buffers stream in bounded chunks; numerical weights never serialize to JSON.
    """
    specs = _specs(parameter_specs)
    return _parameter_digest(specs, _parameters(specs, base_parameters))


@dataclass(frozen=True, slots=True)
class ClientSpec:
    """An owner's approved participant, weighting count and local-data identity."""

    client_id: str
    sample_count: int
    local_data_sha256: str

    def __post_init__(self):
        _text(self.client_id, "client_id")
        _require(type(self.sample_count) is int and 0 < self.sample_count <= 2**63 - 1,
                 "sample_count must be a positive bounded owner-approved integer")
        _sha(self.local_data_sha256, "local_data_sha256")

    @property
    def manifest(self):
        return {"client_id": self.client_id, "sample_count": self.sample_count,
                "local_data_sha256": self.local_data_sha256}


@dataclass(frozen=True, slots=True)
class FederatedRound:
    """Immutable exact-base round contract; separate lineages never mix."""

    round_id: str
    model_id: str
    lineage_id: str
    dimension: int
    architecture: str
    runtime_profile: str
    base_sha256: str
    base_parameters_sha256: str
    embedding_producer_sha256: str
    parameters: tuple[ParameterSpec, ...]
    clients: tuple[ClientSpec, ...]
    max_local_steps: int = 1

    def __post_init__(self):
        for name in ("round_id", "model_id", "lineage_id", "architecture", "runtime_profile"):
            _text(getattr(self, name), name)
        _require(type(self.dimension) is int and self.dimension in (8, 384),
                 "Legal federated rounds require dimension 8 or 384")
        for name in ("base_sha256", "base_parameters_sha256", "embedding_producer_sha256"):
            _sha(getattr(self, name), name)
        _require(type(self.max_local_steps) is int and 0 < self.max_local_steps <= 10**9,
                 "max_local_steps must be a positive bounded integer")
        object.__setattr__(self, "parameters", _specs(self.parameters))
        _require(type(self.clients) in (list, tuple) and bool(self.clients)
                 and all(type(client) is ClientSpec for client in self.clients),
                 "a nonempty owner-approved client list is required")
        clients = tuple(sorted((ClientSpec(client.client_id, client.sample_count, client.local_data_sha256)
                                for client in self.clients), key=lambda client: client.client_id))
        _require(len({client.client_id for client in clients}) == len(clients), "duplicate approved client")
        object.__setattr__(self, "clients", clients)

    @property
    def layout_sha256(self):
        return _digest({"schema": "autoencoder-federated-layout/v1",
                        "parameters": [spec.manifest for spec in self.parameters]})

    @property
    def manifest(self):
        return {"schema": ROUND_SCHEMA, "algorithm": ALGORITHM,
                **{name: getattr(self, name) for name in (
                    "round_id", "model_id", "lineage_id", "dimension", "architecture",
                    "runtime_profile", "base_sha256", "base_parameters_sha256",
                    "embedding_producer_sha256", "max_local_steps")},
                "layout_sha256": self.layout_sha256,
                "parameters": [spec.manifest for spec in self.parameters],
                "clients": [client.manifest for client in self.clients],
                "accumulation": "sorted_clients_math_fsum_float64_with_exact_overflow_fallback",
                "optimizer_policy": "client_local_not_aggregated",
                "sparse_omission": "zero_delta_all_approved_clients_denominator", **_FALSE}

    @property
    def round_sha256(self):
        return _digest(self.manifest)


def _round(value):
    _require(type(value) is FederatedRound, "FederatedRound required")
    return FederatedRound(**{name: getattr(value, name) for name in value.__dataclass_fields__})


def _deltas(round_spec, deltas):
    _require(type(deltas) is dict and set(deltas) <= {spec.name for spec in round_spec.parameters},
             "updates cannot introduce undeclared parameter keys")
    rows = []
    for spec in round_spec.parameters:
        if spec.name not in deltas:
            continue
        row = deltas[spec.name]
        if type(row) in (list, tuple):
            _require(len(row) == spec.size, "delta shape differs: " + spec.name)
            coordinates = enumerate(row)
        else:
            _require(type(row) is dict, "delta must be a flat sequence or sparse coordinate dictionary")
            _require(all(type(index) is int and 0 <= index < spec.size for index in row),
                     "sparse delta coordinates must be existing integer coordinates")
            coordinates = sorted(row.items())
        rows.append((spec.name, tuple((index, _number(value, spec.dtype, spec.name + " delta"))
                                      for index, value in coordinates)))
    return tuple(rows)


@dataclass(frozen=True, slots=True)
class ClientUpdate:
    """Owned immutable numeric delta snapshot bound to one approved round."""

    round_sha256: str
    base_sha256: str
    base_parameters_sha256: str
    layout_sha256: str
    client_id: str
    local_data_sha256: str
    local_steps: int
    _delta_rows: tuple[tuple[str, tuple[tuple[int, float], ...]], ...]

    def __post_init__(self):
        for name in ("round_sha256", "base_sha256", "base_parameters_sha256", "layout_sha256",
                     "local_data_sha256"):
            _sha(getattr(self, name), name)
        _text(self.client_id, "client_id")
        _require(type(self.local_steps) is int and 0 < self.local_steps <= 10**9,
                 "local_steps must be a positive bounded integer")
        _require(type(self._delta_rows) in (list, tuple), "numeric delta snapshot required")
        rows = []
        for row in self._delta_rows:
            _require(type(row) in (list, tuple) and len(row) == 2, "named delta row required")
            name, coordinates = row
            _text(name, "delta parameter name")
            _require(type(coordinates) in (list, tuple), "coordinate delta snapshot required")
            owned = []
            for coordinate in coordinates:
                _require(type(coordinate) in (list, tuple) and len(coordinate) == 2,
                         "integer coordinate and numeric delta required")
                index, value = coordinate
                _require(type(index) is int and 0 <= index <= 2**64 - 1,
                         "nonnegative uint64 coordinate required")
                owned.append((index, _number(value, "float64", "delta")))
            _require(len({index for index, _ in owned}) == len(owned), "duplicate delta coordinate")
            rows.append((name, tuple(sorted(owned))))
        _require(len({name for name, _ in rows}) == len(rows), "duplicate delta parameter")
        object.__setattr__(self, "_delta_rows", tuple(sorted(rows)))

    @property
    def deltas(self):
        return {name: dict(coordinates) for name, coordinates in self._delta_rows}

    @property
    def manifest(self):
        return {"schema": UPDATE_SCHEMA, **{name: getattr(self, name) for name in (
            "round_sha256", "base_sha256", "base_parameters_sha256", "layout_sha256",
            "client_id", "local_data_sha256", "local_steps")},
            "deltas": [{"name": name, "coordinates": [[index, value.hex()]
                         for index, value in coordinates]} for name, coordinates in self._delta_rows], **_FALSE}

    @property
    def update_sha256(self):
        """Stream v1 update identity without JSON serialization of deltas.

        Hash the update domain, one length-prefixed canonical metadata envelope,
        uint64 row count, then each sorted row's length-prefixed name metadata,
        uint64 coordinate count, and repeated little-endian uint64 index/IEEE
        float64 pairs. Values already obey the round's declared dtype. The
        layout commitment binds that dtype; transport floats use lossless float64.
        """
        hasher = hashlib.sha256(_UPDATE_DOMAIN)
        _hash_metadata(hasher, {"schema": UPDATE_SCHEMA, **{name: getattr(self, name) for name in (
            "round_sha256", "base_sha256", "base_parameters_sha256", "layout_sha256",
            "client_id", "local_data_sha256", "local_steps")}, **_FALSE})
        hasher.update(struct.pack("<Q", len(self._delta_rows)))
        for name, coordinates in self._delta_rows:
            _hash_metadata(hasher, {"name": name})
            hasher.update(struct.pack("<Q", len(coordinates)))
            for offset in range(0, len(coordinates), _HASH_CHUNK_COORDINATES):
                chunk = coordinates[offset:offset + _HASH_CHUNK_COORDINATES]
                hasher.update(struct.pack("<" + "Qd" * len(chunk),
                                          *(value for coordinate in chunk for value in coordinate)))
        return hasher.hexdigest()


def make_client_update(round_spec, client_id, deltas, *, local_steps, local_data_sha256):
    """Snapshot local deltas; counts come from the owner round, never the update."""
    round_spec = _round(round_spec)
    client = next((client for client in round_spec.clients if client.client_id == client_id), None)
    _require(client is not None, "client is not approved for this round")
    _require(local_data_sha256 == client.local_data_sha256, "client local-data identity differs")
    _require(type(local_steps) is int and 0 < local_steps <= round_spec.max_local_steps,
             "local_steps exceeds the round's positive local-step bound")
    return ClientUpdate(round_spec.round_sha256, round_spec.base_sha256,
                        round_spec.base_parameters_sha256, round_spec.layout_sha256,
                        client.client_id, client.local_data_sha256, local_steps, _deltas(round_spec, deltas))


def _weighted_coordinate(base, contributions, total, dtype, label):
    if not any(delta != 0.0 for delta, _ in contributions):
        return base
    try:
        result = math.fsum([base, *(delta * (count / total) for delta, count in contributions)])
    except OverflowError:
        # fsum can overflow its intermediate expansion although opposing finite
        # terms cancel. Fall back only for that rare case, avoiding scaled loss.
        exact = Fraction(base) + sum((Fraction(delta) * Fraction(count, total)
                                     for delta, count in contributions), Fraction())
        try:
            result = float(exact)
        except OverflowError as error:
            raise ValueError(label + " aggregate overflows " + dtype) from error
    return _number(result, dtype, label + " aggregate")


@dataclass(frozen=True, slots=True)
class AggregateCandidate:
    """A fresh parameter candidate with provenance and no promotion authority."""

    _parameter_rows: tuple[tuple[str, tuple[float, ...]], ...]
    _provenance_json: bytes
    candidate_sha256: str

    def __post_init__(self):
        rows, raw = _candidate_parts(self._parameter_rows, self._provenance_json, self.candidate_sha256)
        object.__setattr__(self, "_parameter_rows", rows)
        object.__setattr__(self, "_provenance_json", raw)

    @property
    def parameters(self):
        return {name: list(values) for name, values in self._parameter_rows}

    @property
    def provenance(self):
        return json.loads(self._provenance_json)


def _candidate_parts(rows, raw, candidate_sha256):
    _require(type(raw) is bytes, "candidate provenance requires immutable canonical JSON bytes")
    try:
        provenance = json.loads(raw)
    except (ValueError, UnicodeError) as error:
        raise ValueError("invalid candidate provenance") from error
    fields = {"schema", "algorithm", "round_sha256", "round", "parent_checkpoint_sha256",
              "parent_parameters_sha256", "parameters_sha256", "total_sample_count", "updates", *_FALSE}
    _require(type(provenance) is dict and set(provenance) == fields
             and provenance["schema"] == CANDIDATE_SCHEMA and provenance["algorithm"] == ALGORITHM
             and all(provenance[key] is False for key in _FALSE),
             "closed unqualified federated candidate provenance required")
    _require(raw == _raw(provenance) and _sha(candidate_sha256, "candidate_sha256") == _digest(provenance),
             "candidate provenance bytes or digest differs")
    manifest = provenance["round"]
    _require(type(manifest) is dict and type(manifest.get("parameters")) is list
             and type(manifest.get("clients")) is list, "candidate requires a closed round manifest")
    try:
        round_spec = FederatedRound(**{name: manifest[name] for name in (
            "round_id", "model_id", "lineage_id", "dimension", "architecture", "runtime_profile",
            "base_sha256", "base_parameters_sha256", "embedding_producer_sha256", "max_local_steps")},
            parameters=[ParameterSpec(**spec) for spec in manifest["parameters"]],
            clients=[ClientSpec(**client) for client in manifest["clients"]])
    except (KeyError, TypeError) as error:
        raise ValueError("candidate round fields differ") from error
    _require(_raw(manifest) == _raw(round_spec.manifest)
             and provenance["round_sha256"] == round_spec.round_sha256
             and provenance["parent_checkpoint_sha256"] == round_spec.base_sha256
             and provenance["parent_parameters_sha256"] == round_spec.base_parameters_sha256,
             "candidate parent or round binding differs")
    _require(type(provenance["total_sample_count"]) is int
             and provenance["total_sample_count"] == sum(client.sample_count for client in round_spec.clients),
             "candidate approved sample total differs")
    evidence = provenance["updates"]
    _require(type(evidence) is list and len(evidence) == len(round_spec.clients),
             "candidate requires evidence from every approved client")
    for item, client in zip(evidence, round_spec.clients):
        _require(type(item) is dict and set(item) == {"client_id", "sample_count", "local_data_sha256",
                                                    "local_steps", "update_sha256"}
                 and item["client_id"] == client.client_id
                 and type(item["sample_count"]) is int and item["sample_count"] == client.sample_count
                 and item["local_data_sha256"] == client.local_data_sha256
                 and type(item["local_steps"]) is int and 0 < item["local_steps"] <= round_spec.max_local_steps,
                 "candidate client evidence differs from the approved round")
        _sha(item["update_sha256"], "update_sha256")
    _require(type(rows) in (list, tuple), "candidate numeric snapshot required")
    _require(all(type(row) in (list, tuple) and len(row) == 2 for row in rows),
             "candidate requires named parameter rows")
    _require(len({row[0] for row in rows}) == len(rows), "duplicate candidate parameter")
    owned = _parameters(round_spec.parameters, dict(rows))
    _require(provenance["parameters_sha256"] == _parameter_digest(round_spec.parameters, owned),
             "candidate parameter commitment differs from its numeric snapshot")
    return owned, raw


def aggregate_round(round_spec, base_parameters, updates):
    """Combine every approved client's same-base deltas into a fresh candidate.

    All approved clients must submit exactly one update (an empty delta is valid).
    The caller supplies parameters extracted from an independently verified base
    checkpoint. Their numeric commitment is checked here; artifact verification
    and owner evaluation are separate responsibilities.
    """
    round_spec = _round(round_spec)
    base_rows = _parameters(round_spec.parameters, base_parameters)
    _require(_parameter_digest(round_spec.parameters, base_rows) == round_spec.base_parameters_sha256,
             "base parameter commitment differs from the round")
    _require(type(updates) in (list, tuple), "a complete client update sequence is required")
    verified = {}
    for update in updates:
        _require(type(update) is ClientUpdate, "ClientUpdate required")
        _require(update.client_id not in verified, "duplicate client update")
        _require(update.round_sha256 == round_spec.round_sha256
                 and update.base_sha256 == round_spec.base_sha256
                 and update.base_parameters_sha256 == round_spec.base_parameters_sha256
                 and update.layout_sha256 == round_spec.layout_sha256,
                 "update belongs to another round, base or parameter layout")
        # Frozen snapshots are revalidated at the aggregation boundary. The
        # equality also rejects duplicate/reordered coordinate encodings that
        # a direct dataclass constructor or unsafe object mutation could inject.
        expected = make_client_update(round_spec, update.client_id, update.deltas,
            local_steps=update.local_steps, local_data_sha256=update.local_data_sha256)
        _require(update == expected and update.update_sha256 == expected.update_sha256,
                 "client update has a noncanonical or mutated numeric snapshot")
        verified[update.client_id] = expected
    _require(set(verified) == {client.client_id for client in round_spec.clients},
             "exactly one update from every approved client is required")
    total = sum(client.sample_count for client in round_spec.clients)
    client_deltas = [(client, verified[client.client_id].deltas) for client in round_spec.clients]
    aggregate = []
    for spec, (_, base_values) in zip(round_spec.parameters, base_rows):
        per_client = [(client.sample_count, deltas.get(spec.name, {})) for client, deltas in client_deltas]
        values = tuple(_weighted_coordinate(value,
            [(coordinates.get(index, 0.0), count) for count, coordinates in per_client],
            total, spec.dtype, spec.name) for index, value in enumerate(base_values))
        aggregate.append((spec.name, values))
    aggregate = tuple(aggregate)
    provenance = {"schema": CANDIDATE_SCHEMA, "algorithm": ALGORITHM,
                  "round_sha256": round_spec.round_sha256, "round": round_spec.manifest,
                  "parent_checkpoint_sha256": round_spec.base_sha256,
                  "parent_parameters_sha256": round_spec.base_parameters_sha256,
                  "parameters_sha256": _parameter_digest(round_spec.parameters, aggregate),
                  "total_sample_count": total,
                  "updates": [{"client_id": client.client_id, "sample_count": client.sample_count,
                               "local_data_sha256": client.local_data_sha256,
                               "local_steps": verified[client.client_id].local_steps,
                               "update_sha256": verified[client.client_id].update_sha256}
                              for client in round_spec.clients], **_FALSE}
    return AggregateCandidate(aggregate, _raw(provenance), _digest(provenance))


__all__ = ["ParameterSpec", "ClientSpec", "FederatedRound", "ClientUpdate",
           "AggregateCandidate", "parameter_digest", "make_client_update", "aggregate_round"]
