"""Verified fixed-layout federation of raw Legal modal core checkpoints.

The legacy 8D and current 384D state classes retain separate runtime identities.
This adapter freezes the semantic row index, sample memories and proof metadata;
only declared reusable numeric heads become FedAvg parameters. Published Legal
package envelopes and attached formula heads are unsupported. Local data must
use the owner's predeclared rows; layout expansion requires a new base round.

Heavy numerical/codec dependencies load only when a checkpoint is opened. The
established checkpoint codec still performs its own full serialization and
identity checks. This adapter is not a replacement for its verification.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import importlib
import inspect
import json
import math
import os
from pathlib import Path
import stat
import struct
import tempfile
import zlib

from . import autoencoder_federated as federation


SCHEMA = "legal-modal-federated-adapter/v1"
_VERSIONS = {"legacy_v1": (8, "legacy_hub_v1"), "current_v2": (384, "current_legal_v2")}
_DEFAULT_MAX_BYTES = 512 * 1024 * 1024
_NORMALIZATION = "established-modal-reload-defaults-and-compatible-architecture/v1"
_FALSE = {"qualified": False, "admitted": False, "formalized": False,
          "promotion_performed": False, "publication_performed": False}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def _digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _tree_digest(value):
    """Stream a typed semantic commitment without numeric JSON serialization."""
    hasher = hashlib.sha256(b"legal-modal-federated-tree\x00v1\x00")
    def visit(item):
        if item is None:
            hasher.update(b"n")
        elif type(item) is bool:
            hasher.update(b"t" if item else b"f")
        elif type(item) in (int, float):
            try:
                number = float(item)
            except OverflowError as error:
                raise ValueError("state numbers must fit finite float64") from error
            _require(math.isfinite(number) and (type(item) is float or item == number),
                     "state numbers must be losslessly representable finite float64")
            hasher.update(b"d" + struct.pack("<d", number))
        elif type(item) is str:
            encoded = item.encode("utf-8")
            hasher.update(b"s" + struct.pack("<Q", len(encoded)))
            hasher.update(encoded)
        elif type(item) is list:
            hasher.update(b"l" + struct.pack("<Q", len(item)))
            for nested in item:
                visit(nested)
        elif type(item) is dict:
            _require(all(type(key) is str for key in item), "state keys must be exact strings")
            hasher.update(b"m" + struct.pack("<Q", len(item)))
            for key in sorted(item):
                visit(key)
                visit(item[key])
        else:
            raise ValueError("state contains unsupported or executable values")
    visit(value)
    return hasher.hexdigest()


def _modules(runtime_version):
    _require(type(runtime_version) is str and runtime_version in _VERSIONS,
             "runtime_version must be legacy_v1 or current_v2")
    namespace = importlib.import_module(__package__ + ".autoencoder_lineages." + runtime_version)
    codec = importlib.import_module(__package__ + ".modal_autoencoder_checkpoint")
    current = importlib.import_module(__package__ + ".modal_autoencoder")
    optimizer = importlib.import_module(__package__ + ".modal_autoencoder_adaptive_optimizer")
    implementation = importlib.import_module(namespace.TrainingState.__module__)
    dimension, lineage_id = _VERSIONS[runtime_version]
    _require(namespace.DIMENSION == dimension and namespace.LINEAGE_ID == lineage_id,
             "selected runtime lineage or dimension differs")
    return namespace, codec, current, optimizer, implementation


def _source_profile(runtime_version):
    namespace, codec, current, optimizer, implementation = _modules(runtime_version)
    contract = importlib.import_module(__package__ + ".autoencoder_lineages._contract")
    if runtime_version == "legacy_v1":
        contract.verify_snapshot(Path(namespace.__file__).parent / "_snapshot")
    sources = {}
    for label, module in (("adapter", importlib.import_module(__name__)), ("federation", federation),
                          ("namespace", namespace), ("state", implementation), ("codec", codec),
                          ("contract", contract), ("field_inventory", current), ("head_whitelist", optimizer)):
        source = Path(inspect.getfile(module)).resolve(strict=True)
        sources[label] = hashlib.sha256(source.read_bytes()).hexdigest()
    return {"scope": "listed_adapter_state_runtime_codec_and_verified_legacy_snapshot",
            "files": sources}


def _read_stable(path, max_bytes):
    _require(type(max_bytes) is int and 0 < max_bytes <= 8 * 1024 * 1024 * 1024,
             "max_bytes must be a positive bounded integer")
    source = Path(path)
    _require(not source.is_symlink(), "checkpoint cannot be a symlink")
    source = source.resolve(strict=True)
    with source.open("rb") as stream:
        before = os.fstat(stream.fileno())
        _require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= max_bytes,
                 "checkpoint must be a bounded nonempty regular file")
        raw = stream.read(max_bytes + 1)
        after = os.fstat(stream.fileno())
    identity = lambda entry: (entry.st_dev, entry.st_ino, entry.st_size, entry.st_mtime_ns, entry.st_ctime_ns)
    _require(identity(before) == identity(after) and len(raw) == before.st_size,
             "checkpoint changed during reading")
    return source, raw


def _read_verified(path, expected_sha256, max_bytes):
    federation._sha(expected_sha256, "expected_sha256")
    source, raw = _read_stable(path, max_bytes)
    _require(hashlib.sha256(raw).hexdigest() == expected_sha256, "checkpoint SHA256 mismatch")
    return source, raw


def _parse_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "duplicate checkpoint JSON key")
            result[key] = value
        return result
    def invalid(_):
        raise ValueError("nonfinite checkpoint JSON")
    try:
        return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("invalid checkpoint JSON") from error


def _numeric(value):
    _require(type(value) in (int, float), "weight leaves must be builtin numbers, excluding bool")
    try:
        converted = float(value)
    except OverflowError as error:
        raise ValueError("weights must fit finite float64") from error
    _require(math.isfinite(converted) and (type(value) is float or value == converted),
             "weights must be losslessly representable finite float64")


def _plain_component(value):
    # Recursive tracking containers subclass dict/list. Bypass overridden
    # iterators while copying their actual stored values into builtin containers.
    if isinstance(value, dict):
        return {key: _plain_component(item) for key, item in dict.items(value)}
    if isinstance(value, list):
        return [_plain_component(item) for item in list.__iter__(value)]
    return value


def _state_data(state, runtime_version):
    namespace, _, current, _, _ = _modules(runtime_version)
    _require(type(state) is namespace.TrainingState, "state belongs to another modal runtime class")
    _require(set(state.__dict__) <= set(state.__dataclass_fields__),
             "modal state contains unknown attributes or attached formula data")
    normalized = state.to_dict()
    for name in current.MODAL_AUTOENCODER_STATE_COMPONENT_FIELDS:
        raw_value = _plain_component(getattr(state, name))
        _require(_tree_digest(raw_value) == _tree_digest(normalized[name]),
                 "modal state serialization would discard or alter component: " + name)
    return normalized


def _mapping(value, depth):
    _require(type(value) is dict and all(type(key) is str for key in value),
             "semantic rows require string-keyed mappings")
    for nested in value.values():
        if depth == 1:
            _numeric(nested)
        else:
            _mapping(nested, depth - 1)


def _validate_raw(data, runtime_version):
    namespace, _, current, _, implementation = _modules(runtime_version)
    _require(type(data) is dict, "raw modal checkpoint must contain a state object")
    allowed = current.MODAL_AUTOENCODER_STATE_SERIALIZED_FIELDS
    _require(set(data) <= allowed,
             "unsupported package, attached formula head or unknown modal state fields")
    for name, value in data.items():
        if name == "decoded_embeddings" or name.endswith("_embedding_weights"):
            _require(type(value) is dict and all(type(key) is str for key in value),
                     "embedding weights require string-keyed vector mappings")
            for vector in value.values():
                _require(type(vector) is list and len(vector) == namespace.DIMENSION,
                         "embedding row width differs from selected lineage")
                for number in vector:
                    _numeric(number)
        elif name in {"schema_version", "proof_auxiliary_head_schema_version", "architecture_version",
                      "proof_feedback_version_fingerprint"}:
            _require(type(value) is str, "modal schema and proof metadata must be strings")
        elif name.startswith("applied_"):
            _require(type(value) is list and all(type(item) is str for item in value),
                     "applied history must be a string array")
        elif name == "proof_auxiliary_head_logits":
            _mapping(value, 3)
        else:
            _mapping(value, 1 if name == "legal_ir_view_logits" else 2)
    if "schema_version" in data:
        _require(data["schema_version"] == implementation.MODAL_AUTOENCODER_STATE_SCHEMA_VERSION,
                 "modal checkpoint state schema differs")
    if "architecture_version" in data:
        _require(data["architecture_version"] in implementation.MODAL_AUTOENCODER_COMPATIBLE_ARCHITECTURE_VERSIONS,
                 "unsupported modal architecture")
    if "proof_auxiliary_head_schema_version" in data:
        _require(data["proof_auxiliary_head_schema_version"] == implementation.PROOF_AUXILIARY_HEAD_SCHEMA_VERSION,
                 "proof auxiliary schema differs")


def _decompressed_chunks(compressed, maximum):
    """Bound allocations and output while consuming exactly one zlib stream."""
    decoder, produced = zlib.decompressobj(), 0
    block = 65536
    for offset in range(0, len(compressed), block):
        pending = memoryview(compressed)[offset:offset + block]
        while pending:
            try:
                output = decoder.decompress(pending, block)
            except zlib.error as error:
                raise ValueError("invalid compressed modal numeric payload") from error
            produced += len(output)
            _require(produced <= maximum, "modal decompressed payload exceeds declared bounds")
            _require(not decoder.unused_data, "modal payload has trailing compressed bytes or streams")
            pending = decoder.unconsumed_tail
            if output:
                yield output
    # Drain any bounded buffered output without flush(), whose length argument
    # is an initial allocation size rather than an output limit.
    while True:
        try:
            output = decoder.decompress(b"", block)
        except zlib.error as error:
            raise ValueError("invalid compressed modal numeric payload") from error
        produced += len(output)
        _require(produced <= maximum, "modal decompressed payload exceeds declared bounds")
        if not output:
            break
        yield output
    _require(decoder.eof and not decoder.unused_data, "modal compressed stream is incomplete or has trailing bytes")


def _validate_binary_index(compressed, manifest, runtime_version, codec):
    """Close the original codec index before it can coerce or discard rows."""
    namespace, _, current, _, _ = _modules(runtime_version)
    count, table_count = manifest["numeric_value_count"], manifest["table_count"]
    _require(type(count) is int and 0 <= count <= codec._MAX_TABLE_VALUES
             and type(table_count) is int and 0 <= table_count <= len(current.MODAL_AUTOENCODER_STATE_COMPONENT_FIELDS),
             "modal manifest declares invalid numeric table counts")
    dtype = manifest["float_precision"]
    _, width, digits = codec._FLOAT_FORMATS[dtype]
    maximum = codec._INDEX_LENGTH.size + codec._MAX_INDEX_BYTES + count * width
    chunks, prefix = iter(_decompressed_chunks(compressed, maximum)), bytearray()
    while len(prefix) < codec._INDEX_LENGTH.size:
        try:
            prefix.extend(next(chunks))
        except StopIteration as error:
            raise ValueError("modal numeric index prefix is truncated") from error
    index_length = codec._INDEX_LENGTH.unpack_from(prefix)[0]
    _require(0 < index_length <= codec._MAX_INDEX_BYTES, "modal numeric index length exceeds bounds")
    numeric_start = codec._INDEX_LENGTH.size + index_length
    expected_size = numeric_start + count * width
    while len(prefix) < numeric_start:
        try:
            prefix.extend(next(chunks))
        except StopIteration as error:
            raise ValueError("modal numeric index is truncated") from error
    index_raw = bytes(memoryview(prefix)[codec._INDEX_LENGTH.size:numeric_start])
    index = _parse_json(index_raw)
    _require(type(index) is dict and set(index) == {"component_digests", "metadata", "schema_version", "tables"}
             and index["schema_version"] == codec.MODAL_AUTOENCODER_TABLE_SCHEMA_VERSION
             and _raw(index) == index_raw, "unknown or noncanonical modal numeric index fields")
    metadata, tables, digests = index["metadata"], index["tables"], index["component_digests"]
    _validate_raw(metadata, runtime_version)
    _require(all(not codec._numeric_shape(value) or codec._numeric_shape(value) == "empty_mapping"
                 for value in metadata.values()), "modal index metadata contains unindexed numeric state")
    _require(type(digests) is dict and set(digests) == set(current.MODAL_AUTOENCODER_STATE_COMPONENT_FIELDS),
             "modal component digest inventory differs")
    for value in digests.values():
        federation._sha(value, "component digest")
    _require(type(tables) is list and len(tables) == table_count
             and all(type(table) is dict for table in tables), "modal numeric table inventory differs")
    common = {"byte_length", "byte_offset", "dtype", "encoding", "field", "precision_digits", "value_count"}
    extras = {"keyed_scalars": {"keys"}, "keyed_vectors": {"keys", "row_lengths"},
              "path_scalars": {"paths", "empty_paths"}}
    fields, position, values_seen = [], 0, 0
    for table in tables:
        encoding, field = table.get("encoding"), table.get("field")
        _require(type(encoding) is str and encoding in extras and set(table) == common | extras[encoding],
                 "unknown or unused modal table descriptor fields")
        _require(type(field) is str and field in current.MODAL_AUTOENCODER_STATE_COMPONENT_FIELDS
                 and field not in metadata and field not in fields, "duplicate or unknown modal numeric table field")
        fields.append(field)
        number, length, offset = table["value_count"], table["byte_length"], table["byte_offset"]
        _require(type(number) is int and 0 <= number <= codec._MAX_TABLE_VALUES
                 and type(length) is int and length == number * width
                 and type(offset) is int and offset == position
                 and table["dtype"] == dtype and type(table["precision_digits"]) is int
                 and table["precision_digits"] == digits,
                 "modal numeric table dtype, lengths or contiguous offsets differ")
        position += length
        values_seen += number
        if encoding in {"keyed_scalars", "keyed_vectors"}:
            keys = table["keys"]
            _require(type(keys) is list and all(type(key) is str for key in keys)
                     and keys == sorted(set(keys)), "modal semantic table keys must be sorted unique strings")
            if encoding == "keyed_scalars":
                _require(field == "legal_ir_view_logits" and len(keys) == number,
                         "modal scalar semantic table shape differs")
            else:
                lengths = table["row_lengths"]
                _require(field == "decoded_embeddings" or field.endswith("_embedding_weights"),
                         "modal vector table uses a nonvector state component")
                _require(type(lengths) is list and len(lengths) == len(keys)
                         and all(type(size) is int and size == namespace.DIMENSION for size in lengths)
                         and sum(lengths) == number, "modal vector semantic row widths differ")
        else:
            _require(field != "decoded_embeddings" and not field.endswith("_embedding_weights")
                     and field != "legal_ir_view_logits", "modal scalar paths use a different component shape")
            paths, empty = table["paths"], table["empty_paths"]
            depth = 3 if field == "proof_auxiliary_head_logits" else 2
            def qualified_paths(rows, numeric):
                _require(type(rows) is list and all(type(path) is list and bool(path)
                         and all(type(key) is str for key in path)
                         and (len(path) == depth if numeric else len(path) < depth) for path in rows),
                         "modal semantic numeric or empty path shape differs")
                typed = [tuple(path) for path in rows]
                _require(typed == sorted(set(typed)), "modal semantic paths must be sorted and unique")
                return typed
            numeric_paths, empty_paths = qualified_paths(paths, True), qualified_paths(empty, False)
            _require(len(numeric_paths) == number, "modal scalar path count differs")
            terminals = sorted(numeric_paths + empty_paths)
            _require(all(following[:len(previous)] != previous
                         for previous, following in zip(terminals, terminals[1:])),
                     "modal semantic numeric and empty paths overlap")
    _require(fields == sorted(fields) and values_seen == count and position == count * width,
             "modal numeric table ordering or declared totals differ")
    produced = len(prefix)
    # Retain only the strict index while validating the remaining numeric frame.
    del prefix, index_raw, index, tables, metadata, digests
    for chunk in chunks:
        produced += len(chunk)
        _require(produced <= expected_size, "modal numeric payload has unconsumed bytes")
    _require(produced == expected_size, "modal numeric payload length differs from its complete index")


def _decode(raw, runtime_version):
    namespace, codec, current, _, _ = _modules(runtime_version)
    capture = {}
    class Factory:
        @staticmethod
        def from_dict(data):
            _validate_raw(data, runtime_version)
            state = namespace.TrainingState.from_dict(data)
            normalized = state.to_dict()
            for name, value in data.items():
                if name != "architecture_version":
                    _require(_tree_digest(value) == _tree_digest(normalized[name]),
                             "modal reload would discard or alter present field: " + name)
            capture["normalization"] = {"policy": _NORMALIZATION,
                "missing_fields": sorted(current.MODAL_AUTOENCODER_STATE_SERIALIZED_FIELDS - set(data)),
                "raw_architecture": data.get("architecture_version"),
                "loaded_architecture": normalized["architecture_version"]}
            return state
    if raw.startswith(codec.CHECKPOINT_MAGIC):
        _manifest, compressed, _ = codec._parse_container(raw, expected_magic=codec.CHECKPOINT_MAGIC)
        length = codec._HEADER.unpack_from(raw)[3]
        strict_manifest = _parse_json(raw[codec._HEADER.size:codec._HEADER.size + length])
        _require(type(strict_manifest) is dict, "binary checkpoint manifest must be an object")
        parsed_manifest = codec.CheckpointManifest.from_dict(strict_manifest)
        _require(_raw(strict_manifest) == _raw(parsed_manifest.to_dict()),
                 "unknown or malformed binary checkpoint manifest fields")
        _validate_binary_index(compressed, strict_manifest, runtime_version, codec)
        def head_free(value):
            if type(value) is dict:
                _require(not {"formula_checkpoint", "joint_formula_checkpoint", "_joint_formula_checkpoint",
                              "formula_head"} & set(value), "attached formula heads require a separate requalification branch")
                _require(value.get("formula_head_attached", False) is False,
                         "attached formula heads require a separate requalification branch")
                for child in value.values():
                    head_free(child)
            elif type(value) is list:
                for child in value:
                    head_free(child)
        head_free(parsed_manifest.metadata)
        loaded = codec.deserialize_checkpoint(raw, state_factory=Factory)
        state, format_name, dtype = loaded.state, "compact", loaded.manifest.float_precision
        metric_lineage = loaded.manifest.metric_lineage
        metadata_sha = _tree_digest(loaded.manifest.metadata)
    elif raw.lstrip().startswith(b"{"):
        state = Factory.from_dict(_parse_json(raw))
        format_name, dtype, metric_lineage, metadata_sha = "json", "float64", None, _tree_digest({})
    else:
        raise ValueError("only complete modal JSON or LIRMAECP checkpoints are supported")
    _require(dtype in {"float32", "float64"}, "unsupported modal numeric precision")
    # Revalidate the normalized complete envelope independently of from_dict.
    normalized = state.to_dict()
    _validate_raw(normalized, runtime_version)
    _require(set(normalized) == current.MODAL_AUTOENCODER_STATE_SERIALIZED_FIELDS,
             "normalized modal state field inventory differs")
    return state, normalized, {"format": format_name, "dtype": dtype,
        "metric_lineage": metric_lineage, "normalization": capture["normalization"],
        "checkpoint_metadata_sha256": metadata_sha,
        "checkpoint_metadata_policy": "replace_with_federation_receipt_not_client_training_history"}, (
            loaded.manifest if format_name == "compact" else None)


@dataclass(frozen=True, slots=True)
class _ComponentLayout:
    name: str
    kind: str
    rows: tuple[tuple[tuple[str, ...], int], ...]
    empty_paths: tuple[tuple[str, ...], ...]

    @property
    def size(self):
        return sum(length for _, length in self.rows)


def _layout(data, components, dtype, dimension):
    layouts, specs, parameters = [], [], {}
    for name in components:
        table = data[name]
        rows, values, empty_paths = [], [], []
        if name.endswith("_embedding_weights"):
            kind = "keyed_vectors"
            for key in sorted(table):
                rows.append(((key,), dimension))
                values.extend(table[key])
        else:
            kind = "path_scalars"
            def scan(mapping, path=()):
                for key in sorted(mapping):
                    child, child_path = mapping[key], path + (key,)
                    if type(child) is dict:
                        if child:
                            scan(child, child_path)
                        else:
                            empty_paths.append(child_path)
                    else:
                        rows.append((child_path, 1))
                        values.append(child)
            scan(table)
        layouts.append(_ComponentLayout(name, kind, tuple(rows), tuple(empty_paths)))
        if values:
            specs.append(federation.ParameterSpec(name, (len(values),), dtype))
            parameters[name] = values
    _require(bool(specs), "checkpoint has no reusable trainable parameters in selected components")
    return tuple(layouts), tuple(specs), parameters


def _layout_digest(layouts, dtype):
    hasher = hashlib.sha256(b"legal-modal-federated-semantic-index\x00v1\x00")
    hasher.update(struct.pack("<Q", len(layouts)))
    for layout in layouts:
        def metadata(value):
            raw = _raw(value)
            hasher.update(struct.pack("<Q", len(raw)))
            hasher.update(raw)
        metadata({"component": layout.name, "kind": layout.kind, "dtype": dtype,
                  "rows": len(layout.rows), "empty_paths": len(layout.empty_paths)})
        for path, width in layout.rows:
            metadata({"path": list(path), "width": width})
        for path in layout.empty_paths:
            metadata({"empty_path": list(path)})
    return hasher.hexdigest()


def _frozen_digest(data, components):
    return _tree_digest({name: value for name, value in data.items() if name not in components})


@dataclass(frozen=True, slots=True)
class ModalCheckpoint:
    """A verified base artifact and owned fixed-layout numeric snapshot."""

    path: str
    base_sha256: str
    runtime_version: str
    dimension: int
    lineage_id: str
    architecture: str
    runtime_profile: str
    base_parameters_sha256: str
    _parameter_specs: tuple[federation.ParameterSpec, ...]
    _parameter_rows: tuple[tuple[str, tuple[float, ...]], ...]
    _components: tuple[str, ...]
    _layouts: tuple[_ComponentLayout, ...]
    _binding_json: bytes
    _max_bytes: int

    @property
    def parameter_specs(self):
        return self._parameter_specs

    @property
    def parameters(self):
        return {name: list(values) for name, values in self._parameter_rows}

    @property
    def binding(self):
        return json.loads(self._binding_json)

    @property
    def semantic_index(self):
        return [{"component": layout.name, "kind": layout.kind,
                 "rows": [{"path": list(path), "width": width} for path, width in layout.rows],
                 "empty_paths": [list(path) for path in layout.empty_paths]} for layout in self._layouts]

    def _verified_base(self):
        binding = self.binding
        _require(_source_profile(self.runtime_version) == binding["source_profile"],
                 "modal adapter or codec source profile changed")
        _, raw = _read_verified(self.path, self.base_sha256, self._max_bytes)
        state, data, info, _ = _decode(raw, self.runtime_version)
        _require(info == binding["checkpoint_policy"], "modal base decoding policy changed")
        params = self._extract(data)
        _require(federation.parameter_digest(self.parameter_specs, params) == self.base_parameters_sha256,
                 "modal extracted base parameter commitment differs")
        _require(self.parameters == params, "modal owned base snapshot differs")
        return state

    def _extract(self, data):
        _validate_raw(data, self.runtime_version)
        _require(data["architecture_version"] == self.architecture, "modal architecture changed")
        binding = self.binding
        layouts, specs, params = _layout(data, self._components, binding["checkpoint_policy"]["dtype"], self.dimension)
        _require(layouts == self._layouts and specs == self.parameter_specs
                 and _layout_digest(layouts, binding["checkpoint_policy"]["dtype"]) == binding["semantic_layout_sha256"],
                 "modal semantic keys, rows or tensor layout changed; start a new owner round")
        _require(_frozen_digest(data, self._components) == binding["frozen_state_sha256"],
                 "client changed frozen sample memories, proof metadata or excluded state")
        return params

    def fresh_state(self):
        """Load a fresh exact-lineage state, rechecking artifact and source bytes."""
        return self._verified_base()

    def fresh_model(self, **model_options):
        _require(set(model_options) <= {"compute_device"}, "only compute_device may override the bound runtime")
        namespace, _, _, _, _ = _modules(self.runtime_version)
        return namespace.Autoencoder(state=self.fresh_state(), **model_options)

    def validate_round(self, round_spec):
        round_spec = federation._round(round_spec)
        self._verified_base()
        _require(round_spec.base_sha256 == self.base_sha256
                 and round_spec.base_parameters_sha256 == self.base_parameters_sha256
                 and round_spec.dimension == self.dimension and round_spec.lineage_id == self.lineage_id
                 and round_spec.architecture == self.architecture and round_spec.runtime_profile == self.runtime_profile
                 and round_spec.parameters == tuple(sorted(self.parameter_specs, key=lambda spec: spec.name)),
                 "federated round differs from the authenticated modal base/runtime/layout")
        return round_spec

    def make_round(self, round_id, clients, *, embedding_producer_sha256, max_local_steps=1, model_id="legal_ir"):
        self._verified_base()
        return federation.FederatedRound(round_id=round_id, model_id=model_id, lineage_id=self.lineage_id,
            dimension=self.dimension, architecture=self.architecture, runtime_profile=self.runtime_profile,
            base_sha256=self.base_sha256, base_parameters_sha256=self.base_parameters_sha256,
            embedding_producer_sha256=embedding_producer_sha256, parameters=self.parameter_specs,
            clients=clients, max_local_steps=max_local_steps)

    def extract_parameters(self, state):
        _require(_source_profile(self.runtime_version) == self.binding["source_profile"],
                 "modal adapter or codec source profile changed")
        return self._extract(_state_data(state, self.runtime_version))

    def make_update_from_state(self, round_spec, client_id, state, *, local_steps, local_data_sha256):
        round_spec = self.validate_round(round_spec)
        params = self.extract_parameters(state)
        base = self.parameters
        deltas = {}
        for name, values in params.items():
            coordinates = {}
            for index, value in enumerate(values):
                previous = base[name][index]
                if struct.pack("<d", value) != struct.pack("<d", previous):
                    _require(value != previous,
                             "signed-zero-only changes cannot be represented by an additive delta")
                    coordinates[index] = value - previous
            deltas[name] = coordinates
        return federation.make_client_update(round_spec, client_id, deltas,
            local_steps=local_steps, local_data_sha256=local_data_sha256)

    def make_update(self, round_spec, client_id, trained_path, *, expected_sha256, local_steps, local_data_sha256):
        _, raw = _read_verified(trained_path, expected_sha256, self._max_bytes)
        state, _, info, _ = _decode(raw, self.runtime_version)
        _require(info["dtype"] == self.binding["checkpoint_policy"]["dtype"], "client checkpoint precision changed")
        return self.make_update_from_state(round_spec, client_id, state,
            local_steps=local_steps, local_data_sha256=local_data_sha256)

    def materialize(self, round_spec, candidate, path):
        """Write/reuse an immutable full binary candidate; never qualify or promote."""
        round_spec = self.validate_round(round_spec)
        _require(type(candidate) is federation.AggregateCandidate, "AggregateCandidate required")
        candidate = replace(candidate)  # Closed provenance and numeric commitment validation.
        _require(candidate.provenance["round_sha256"] == round_spec.round_sha256,
                 "aggregate candidate belongs to another modal round")
        state = self.fresh_state()
        params = candidate.parameters
        for layout in self._layouts:
            if not layout.size:
                continue
            table, values, position = getattr(state, layout.name), params[layout.name], 0
            for row_path, width in layout.rows:
                if layout.kind == "keyed_vectors":
                    table[row_path[0]] = values[position:position + width]
                else:
                    cursor = table
                    for key in row_path[:-1]:
                        cursor = cursor[key]
                    cursor[row_path[-1]] = values[position]
                position += width
        _require(federation.parameter_digest(self.parameter_specs, self.extract_parameters(state))
                 == candidate.provenance["parameters_sha256"], "materialized modal parameter commitment differs")
        _, codec, _, _, _ = _modules(self.runtime_version)
        policy = self.binding["checkpoint_policy"]
        metadata = self._materialization_metadata(candidate)
        raw = codec.serialize_checkpoint(state, float_precision=policy["dtype"],
            metric_lineage=policy["metric_lineage"], metadata=metadata, revision=0)
        # Validate the established codec's output with the same strict factory.
        restored, _, _, _ = _decode(raw, self.runtime_version)
        _require(federation.parameter_digest(self.parameter_specs, self.extract_parameters(restored))
                 == candidate.provenance["parameters_sha256"], "binary modal roundtrip changed parameters")
        _require(len(raw) <= self._max_bytes, "binary modal candidate exceeds max_bytes")
        destination = _write_immutable(path, raw)
        return {"path": str(destination), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
                "format": "modal-autoencoder-checkpoint-v1", "state_revision": 0,
                "parameters_sha256": candidate.provenance["parameters_sha256"],
                "candidate_sha256": candidate.candidate_sha256, "adapter_binding": self.binding,
                "formula_head_attached": False, "optimizer_history_persisted": False, **_FALSE}

    def _materialization_metadata(self, candidate):
        return {"schema": SCHEMA, "candidate_sha256": candidate.candidate_sha256,
                    "base_checkpoint_sha256": self.base_sha256, "runtime_profile": self.runtime_profile,
                    "semantic_layout_sha256": self.binding["semantic_layout_sha256"],
                    "inherited_proof_metadata_is_new_evidence": False,
                    "formula_head_attached": False, "optimizer_history_persisted": False, **_FALSE}

    def verify_materialization(self, round_spec, candidate, staged_path):
        """Verify staged binary bytes contain this exact aggregate and frozen base.

        Returning True certifies complete materialization only. The registry
        verifies the staged artifact hash separately; objective qualification,
        admission and generation selection remain separate owner actions.
        """
        round_spec = self.validate_round(round_spec)
        _require(type(candidate) is federation.AggregateCandidate, "AggregateCandidate required")
        candidate = replace(candidate)
        _require(candidate.provenance["round_sha256"] == round_spec.round_sha256,
                 "aggregate candidate belongs to another modal round")
        _, raw = _read_stable(staged_path, self._max_bytes)
        _, codec, _, _, _ = _modules(self.runtime_version)
        _require(raw.startswith(codec.CHECKPOINT_MAGIC), "aggregate materialization must use the complete binary modal codec")
        state, _, info, manifest = _decode(raw, self.runtime_version)
        policy = self.binding["checkpoint_policy"]
        _require(manifest.revision == 0 and info["dtype"] == policy["dtype"]
                 and _tree_digest(info["metric_lineage"]) == _tree_digest(policy["metric_lineage"])
                 and manifest.metadata == self._materialization_metadata(candidate),
                 "aggregate checkpoint revision, precision or owner metadata differs")
        _require(federation.parameter_digest(self.parameter_specs, self.extract_parameters(state))
                 == candidate.provenance["parameters_sha256"], "staged modal parameters differ from aggregate")
        return True


def _write_immutable(path, raw):
    destination = Path(path).absolute()
    _require(not destination.is_symlink(), "candidate destination cannot be a symlink")
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".federated-modal-", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, destination)
        except FileExistsError:
            _, existing = _read_verified(destination, hashlib.sha256(raw).hexdigest(), len(raw))
            _require(existing == raw, "immutable modal candidate differs")
        directory_fd = os.open(destination.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        os.unlink(temporary)
    return destination


def load_modal_checkpoint(path, *, expected_sha256, runtime_version, trainable_components=None,
                          max_bytes=_DEFAULT_MAX_BYTES):
    """Verify a complete modal artifact and bind its fixed trainable semantic index.

    Missing known legacy fields and compatible architecture migration follow the
    established loader and are explicitly recorded. All present fields must
    survive reload; unknown fields, duplicate keys, lossy proof normalization,
    package envelopes and sidecars are rejected before they can be discarded.
    """
    namespace, _, _, optimizer, _ = _modules(runtime_version)
    source_profile = _source_profile(runtime_version)
    source, raw = _read_verified(path, expected_sha256, max_bytes)
    state, data, policy, _ = _decode(raw, runtime_version)
    if trainable_components is None:
        components = tuple(sorted(optimizer.MOMENTUM_COMPONENTS))
    else:
        _require(type(trainable_components) in (list, tuple) and bool(trainable_components)
                 and all(type(name) is str for name in trainable_components),
                 "trainable_components must be a nonempty declared string sequence")
        _require(len(set(trainable_components)) == len(trainable_components)
                 and set(trainable_components) <= optimizer.MOMENTUM_COMPONENTS,
                 "only distinct reusable numeric heads may be federated")
        components = tuple(sorted(trainable_components))
    layouts, specs, params = _layout(data, components, policy["dtype"], namespace.DIMENSION)
    semantic_sha = _layout_digest(layouts, policy["dtype"])
    profile_sha = _digest({"source_profile": source_profile, "semantic_layout_sha256": semantic_sha,
                           "runtime_version": runtime_version, "lineage_id": namespace.LINEAGE_ID,
                           "dimension": namespace.DIMENSION, "checkpoint_policy": policy})
    profile = SCHEMA + "/" + profile_sha
    parameter_sha = federation.parameter_digest(specs, params)
    binding = {"schema": SCHEMA, "base_checkpoint_sha256": expected_sha256,
               "base_checkpoint_bytes": len(raw), "runtime_version": runtime_version,
               "lineage_id": namespace.LINEAGE_ID, "dimension": namespace.DIMENSION,
               "architecture": data["architecture_version"], "runtime_profile": profile,
               "source_profile": source_profile, "checkpoint_policy": policy,
               "trainable_components": list(components), "semantic_layout_sha256": semantic_sha,
               "parameters_sha256": parameter_sha, "frozen_state_sha256": _frozen_digest(data, components),
               "inherited_proof_metadata_is_new_evidence": False,
               "formula_head_attached": False, "optimizer_history_persisted": False, **_FALSE}
    _require(_source_profile(runtime_version) == source_profile, "modal sources changed while loading")
    return ModalCheckpoint(str(source), expected_sha256, runtime_version, namespace.DIMENSION,
        namespace.LINEAGE_ID, data["architecture_version"], profile, parameter_sha,
        specs, tuple((name, tuple(values)) for name, values in sorted(params.items())),
        components, layouts, _raw(binding), max_bytes)


__all__ = ["ModalCheckpoint", "load_modal_checkpoint"]
