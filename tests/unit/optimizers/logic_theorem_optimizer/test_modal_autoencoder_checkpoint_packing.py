"""Independent old numeric packing oracle; synthetic codec fixtures only.

The encoder and leaf helpers below are frozen from the archived pre-edit codec.
Tests never read that workspace archive at runtime. The existing frozen public
serializer bodies are rebound to this old helper namespace, so expected bytes
cannot silently follow a changed production payload encoder.
"""
from __future__ import annotations

from collections import UserDict
import hashlib
import math
import struct
import zlib

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder_checkpoint as codec
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    ModalAutoencoderTrainingState, MODAL_AUTOENCODER_STATE_COMPONENT_FIELDS,
)
from tests.unit.optimizers.logic_theorem_optimizer.test_modal_autoencoder_checkpoint_baseline import (
    _REFERENCE_SOURCE as _FROZEN_SERIALIZERS, copied, fixture, mutate,
)

_ORIGINAL_CODEC_SHA256 = "eead66d108709e6868f7c112ee8df5580b4cd38a756e997f276b775d7dacd021"
_FROZEN_HELPERS_SHA256 = "a3e7b16665426e1460f9a9cb6f2260bb303488c7385ffbf96ef9f4d3ae9af196"
# Verbatim function bodies; do not regenerate from the candidate implementation.
_FROZEN_HELPERS = r'''def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")

def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()

def _canonical_copy(value: Any) -> Any:
    """Copy supported JSON data while rejecting executable/custom values."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("checkpoint numeric values must be finite")
        return value
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_copy(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_canonical_copy(item) for item in value]
    raise TypeError(f"unsupported checkpoint value: {type(value).__name__}")

def _quantized_copy(value: Any, precision: str) -> Any:
    if isinstance(value, float):
        return quantize_float(value, precision)
    if isinstance(value, Mapping):
        return {str(key): _quantized_copy(item, precision) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_quantized_copy(item, precision) for item in value]
    return _canonical_copy(value)

def quantize_float(value: float, precision: str = "float64") -> float:
    """Return the exact value represented by the declared storage precision."""

    try:
        fmt, _width, _digits = _FLOAT_FORMATS[precision]
    except KeyError as exc:
        raise ValueError(f"unsupported float precision: {precision!r}") from exc
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("checkpoint numeric values must be finite")
    try:
        return struct.unpack(fmt, struct.pack(fmt, number))[0]
    except OverflowError as exc:
        raise ValueError(f"value {number!r} cannot be represented as {precision}") from exc

def _numeric_shape(value: Any) -> str:
    if not isinstance(value, Mapping):
        return ""
    if not value:
        return "empty_mapping"
    values = list(value.values())
    if all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in values):
        return "keyed_scalars"
    if all(
        isinstance(item, Sequence)
        and not isinstance(item, (str, bytes, bytearray))
        and all(
            isinstance(number, (int, float)) and not isinstance(number, bool) for number in item
        )
        for item in values
    ):
        return "keyed_vectors"
    if all(isinstance(item, Mapping) for item in values):
        leaves = list(_mapping_numeric_leaves(value))
        if leaves or all(not item for item in values):
            return "path_scalars"
    return ""

def _mapping_numeric_leaves(
    value: Mapping[str, Any],
    prefix: Tuple[str, ...] = (),
) -> Iterable[Tuple[Tuple[str, ...], float]]:
    for raw_key, item in sorted(value.items(), key=lambda pair: str(pair[0])):
        path = (*prefix, str(raw_key))
        if isinstance(item, Mapping):
            yield from _mapping_numeric_leaves(item, path)
        elif isinstance(item, (int, float)) and not isinstance(item, bool):
            yield path, float(item)
        else:
            raise TypeError(f"non-numeric table leaf at {'.'.join(path)}")

def _mapping_empty_paths(
    value: Mapping[str, Any],
    prefix: Tuple[str, ...] = (),
) -> Iterable[Tuple[str, ...]]:
    for raw_key, item in sorted(value.items(), key=lambda pair: str(pair[0])):
        path = (*prefix, str(raw_key))
        if isinstance(item, Mapping):
            if item:
                yield from _mapping_empty_paths(item, path)
            else:
                yield path

def _encode_state_payload(
    state_data: Mapping[str, Any],
    *,
    precision: str,
    component_digests: Mapping[str, str],
    include_components: Optional[Sequence[str]] = None,
) -> tuple[bytes, List[Dict[str, Any]]]:
    fmt, width, digits = _FLOAT_FORMATS.get(precision, (None, None, None))
    if fmt is None:
        raise ValueError(f"unsupported float precision: {precision!r}")
    selected = None if include_components is None else set(include_components)
    metadata: Dict[str, Any] = {}
    tables: List[Dict[str, Any]] = []
    numeric = bytearray()

    for name, raw_value in sorted(state_data.items()):
        if selected is not None and name not in selected:
            continue
        value = _canonical_copy(raw_value)
        shape = _numeric_shape(value)
        if not shape or shape == "empty_mapping":
            metadata[name] = value
            continue

        descriptor: Dict[str, Any] = {
            "byte_length": 0,
            "byte_offset": len(numeric),
            "dtype": precision,
            "encoding": shape,
            "field": name,
            "precision_digits": digits,
            "value_count": 0,
        }
        values: List[float]
        if shape == "keyed_scalars":
            descriptor["keys"] = [str(key) for key in sorted(value)]
            values = [float(value[key]) for key in sorted(value)]
        elif shape == "keyed_vectors":
            keys = [str(key) for key in sorted(value)]
            rows = [value[key] for key in sorted(value)]
            descriptor["keys"] = keys
            descriptor["row_lengths"] = [len(row) for row in rows]
            values = [float(number) for row in rows for number in row]
        else:
            leaves = list(_mapping_numeric_leaves(value))
            descriptor["paths"] = [list(path) for path, _number in leaves]
            descriptor["empty_paths"] = [list(path) for path in _mapping_empty_paths(value)]
            values = [number for _path, number in leaves]

        packed = bytearray()
        for number in values:
            quantized = quantize_float(number, precision)
            packed.extend(struct.pack(fmt, quantized))
        descriptor["value_count"] = len(values)
        descriptor["byte_length"] = len(packed)
        numeric.extend(packed)
        tables.append(descriptor)

    index = {
        "component_digests": dict(sorted(component_digests.items())),
        "metadata": metadata,
        "schema_version": MODAL_AUTOENCODER_TABLE_SCHEMA_VERSION,
        "tables": tables,
    }
    index_bytes = _json_bytes(index)
    if len(index_bytes) > _MAX_INDEX_BYTES:
        raise ValueError("checkpoint table index exceeds safety limit")
    raw_payload = _INDEX_LENGTH.pack(len(index_bytes)) + index_bytes + bytes(numeric)
    return zlib.compress(raw_payload, level=9), tables

def _state_data(state: Any) -> Dict[str, Any]:
    if isinstance(state, Mapping):
        return _canonical_copy(state)
    # Packed tensor state deliberately writes the rollout-compatible legacy
    # map envelope.  This keeps existing readers operational while migration
    # code can immediately re-pack the decoded object.
    checkpoint_dict = getattr(state, "to_checkpoint_dict", None)
    if callable(checkpoint_dict):
        value = checkpoint_dict()
        if not isinstance(value, Mapping):
            raise TypeError("state.to_checkpoint_dict() must return a mapping")
        return _canonical_copy(value)
    to_dict = getattr(state, "to_dict", None)
    if not callable(to_dict):
        raise TypeError(f"unsupported checkpoint state: {type(state).__name__}")
    value = to_dict()
    if not isinstance(value, Mapping):
        raise TypeError("state.to_dict() must return a mapping")
    return _canonical_copy(value)

@dataclass(frozen=True)
class CheckpointManifest:
    """Validated public metadata for one full checkpoint or delta."""

    schema_version: str
    kind: str
    state_schema_version: str
    state_digest: str
    revision: int
    metric_lineage_digest: str
    metric_lineage: Any
    float_precision: str
    payload_checksum: str
    checkpoint_id: str
    base_state_digest: str = ""
    base_revision: int = -1
    changed_components: Tuple[str, ...] = ()
    table_count: int = 0
    numeric_value_count: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CheckpointManifest":
        schema = str(value.get("schema_version") or "")
        if schema not in (
            MODAL_AUTOENCODER_CHECKPOINT_SCHEMA_VERSION,
            MODAL_AUTOENCODER_DELTA_SCHEMA_VERSION,
        ):
            raise UnsupportedCheckpointError(f"unsupported checkpoint schema: {schema!r}")
        precision = str(value.get("float_precision") or "")
        if precision not in _FLOAT_FORMATS:
            raise UnsupportedCheckpointError(f"unsupported float precision: {precision!r}")
        return cls(
            schema_version=schema,
            kind=str(value.get("kind") or ""),
            state_schema_version=str(value.get("state_schema_version") or ""),
            state_digest=str(value.get("state_digest") or ""),
            revision=int(value.get("revision", -1)),
            metric_lineage_digest=str(value.get("metric_lineage_digest") or ""),
            metric_lineage=_canonical_copy(value.get("metric_lineage")),
            float_precision=precision,
            payload_checksum=str(value.get("payload_checksum") or ""),
            checkpoint_id=str(value.get("checkpoint_id") or ""),
            base_state_digest=str(value.get("base_state_digest") or ""),
            base_revision=int(value.get("base_revision", -1)),
            changed_components=tuple(str(item) for item in value.get("changed_components", [])),
            table_count=int(value.get("table_count", 0)),
            numeric_value_count=int(value.get("numeric_value_count", 0)),
            metadata=_canonical_copy(value.get("metadata") or {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "checkpoint_id": self.checkpoint_id,
            "compression": "zlib",
            "float_precision": self.float_precision,
            "kind": self.kind,
            "metadata": _canonical_copy(self.metadata),
            "metric_lineage_digest": self.metric_lineage_digest,
            "metric_lineage": _canonical_copy(self.metric_lineage),
            "numeric_value_count": self.numeric_value_count,
            "payload_checksum": self.payload_checksum,
            "revision": self.revision,
            "schema_version": self.schema_version,
            "state_digest": self.state_digest,
            "state_schema_version": self.state_schema_version,
            "table_count": self.table_count,
            "table_schema_version": MODAL_AUTOENCODER_TABLE_SCHEMA_VERSION,
        }
        if self.kind == "delta":
            result.update(
                {
                    "base_revision": self.base_revision,
                    "base_state_digest": self.base_state_digest,
                    "changed_components": list(self.changed_components),
                }
            )
        return result

def _container_bytes(magic: bytes, manifest: Mapping[str, Any], payload: bytes) -> bytes:
    manifest_bytes = _json_bytes(manifest)
    if len(manifest_bytes) > _MAX_MANIFEST_BYTES or len(payload) > _MAX_PAYLOAD_BYTES:
        raise ValueError("checkpoint container exceeds safety limit")
    header = _HEADER.pack(
        magic,
        CONTAINER_VERSION,
        0,
        len(manifest_bytes),
        len(payload),
        hashlib.sha256(manifest_bytes).digest(),
        hashlib.sha256(payload).digest(),
    )
    return header + manifest_bytes + payload
'''


def old_functions():
    assert hashlib.sha256(_FROZEN_HELPERS.encode()).hexdigest() == _FROZEN_HELPERS_SHA256
    namespace = vars(codec).copy()
    namespace["_FLOAT_FORMATS"] = {"float32": ("<f", 4, 7), "float64": ("<d", 8, 15)}
    exec(compile(_FROZEN_HELPERS, "<frozen-pre-packing-helpers>", "exec"), namespace)
    exec(compile(_FROZEN_SERIALIZERS, "<frozen-pre-baseline-serializers>", "exec"), namespace)
    return namespace


def _outcome(function, *args, **kwargs):
    try:
        return ("returned", function(*args, **kwargs))
    except (TypeError, ValueError, OverflowError, struct.error, RecursionError) as exc:
        return ("raised", type(exc), str(exc))


def _payload_options(data, precision, selected=None):
    return {"precision": precision,
            "component_digests": {name: hashlib.sha256(name.encode()).hexdigest() for name in data},
            "include_components": selected}


def _unpack_payload(payload):
    raw = zlib.decompress(payload)
    length = struct.unpack_from(">I", raw)[0]
    return codec.json.loads(raw[4:4 + length]), raw[4 + length:]


def test_old_oracle_is_independent_of_candidate_encoder_and_leaf_helpers(monkeypatch):
    state = fixture()
    def forbidden(*args, **kwargs):
        raise AssertionError("frozen oracle called a candidate helper")
    for name in ("_encode_state_payload", "quantize_float", "_quantized_copy", "_canonical_copy",
                 "_numeric_shape", "_mapping_numeric_leaves", "_mapping_empty_paths", "_state_data",
                 "_json_bytes", "_sha256", "_container_bytes"):
        monkeypatch.setattr(codec, name, forbidden)
    reference = old_functions()
    encoded = reference["serialize_checkpoint"](state)
    assert encoded.startswith(codec.CHECKPOINT_MAGIC)
    data = {"weights": {"original": [-0.0, 1.0]}}
    payload, _ = reference["_encode_state_payload"](data, **_payload_options(data, "float32"))
    assert _unpack_payload(payload)[1] == struct.pack("<ff", -0.0, 1.0)


@pytest.mark.parametrize("precision", ["float32", "float64"])
def test_full_all38_components_match_independent_old_wire_bytes(precision):
    state = fixture()
    reference = old_functions()
    options = {"float_precision": precision,
               "metric_lineage": {"schema": "packing-fixture-v1", "zero": -0.0},
               "metadata": {"fixture": True, "order": ["second", "first"], "unicode": "é/法"},
               "revision": state.state_revision + 3}
    expected = reference["serialize_checkpoint"](state, **options)
    snapshot = codec.serialize_checkpoint_snapshot(state, **options)
    assert snapshot.payload == expected == codec.serialize_checkpoint(state, **options)
    loaded = codec.deserialize_checkpoint(expected)
    assert len(loaded.state.state_identity_record().component_digests) == 38
    assert snapshot.baseline.state_digest == loaded.manifest.state_digest
    assert snapshot.baseline.revision == loaded.state.state_revision


@pytest.mark.parametrize("precision", ["float32", "float64"])
@pytest.mark.parametrize("component", MODAL_AUTOENCODER_STATE_COMPONENT_FIELDS)
def test_each_component_legacy_and_baseline_delta_match_independent_old_encoder(component, precision):
    base = fixture()
    current = copied(base)
    mutate(current, component)
    reference = old_functions()
    options = {"float_precision": precision, "metric_lineage": {"fixture": "packing"},
               "metadata": {"component": component}}
    expected = reference["serialize_delta"](base, current, **options)
    token = codec.checkpoint_baseline(base, float_precision=precision, metric_lineage=options["metric_lineage"])
    legacy = codec.serialize_delta_snapshot(base, current, **options)
    baseline = codec.serialize_delta_from_baseline(token, current, **options)
    assert legacy.payload == baseline.payload == expected == codec.serialize_delta(base, current, **options)
    assert baseline.baseline == legacy.baseline
    assert baseline.baseline.component_digests == codec.checkpoint_baseline(
        current, float_precision=precision, metric_lineage=options["metric_lineage"]).component_digests


def _shape_case(kind):
    numbers = [-0.0, 0.0, -1.0, 1.0 / 3.0, 1 + 2**-24,
               math.nextafter(1 + 2**-24, math.inf), 2**-149, 2**-150, -(2**-150)]
    if kind == "keyed-scalars":
        return {"values": {"z": numbers[0], "a": numbers[3], "integer": 7}}
    if kind == "ragged-vectors":
        return {"values": {"z": [], "a": numbers, "single": [-0.0]}, "empty": {}}
    if kind == "nested-empty-paths":
        return {"values": {"a": {"empty": {}, "child": {"deep-empty": {}, "number": -0.0}}, "z": {}}}
    if kind == "only-nested-empties":
        return {"values": {"a": {}, "z": {}}, "deeper": {"outer": {"empty": {}}}}
    if kind == "metadata-mixed":
        return {"metadata": {"boolean": True, "none": None, "text": "text", "list": ["a", "a"]}}
    if kind == "unicode-controls-surrogate":
        return {"values": {"é/法": numbers, "tab\tline\n": [-0.0], "\ud800": [1.0]},
                "metadata": ["\udfff", "quote\"slash\\", "é", "é"]}
    if kind == "string-key-collision":
        return {"values": UserDict({1: [2.0], "1": [-0.0], "01": [0.125]})}
    if kind == "float64-extremes":
        return {"values": {"row": [float.fromhex("0x1.fffffffffffffp+1023"), 5e-324, -5e-324]}}
    raise AssertionError(kind)


@pytest.mark.parametrize("precision", ["float32", "float64"])
@pytest.mark.parametrize("kind", ["keyed-scalars", "ragged-vectors", "nested-empty-paths", "only-nested-empties",
                                  "metadata-mixed", "unicode-controls-surrogate", "string-key-collision", "float64-extremes"])
def test_direct_encoder_shapes_and_errors_match_independent_reference(kind, precision):
    data = _shape_case(kind)
    options = _payload_options(data, precision)
    expected = _outcome(old_functions()["_encode_state_payload"], data, **options)
    actual = _outcome(codec._encode_state_payload, data, **options)
    assert actual == expected
    if expected[0] == "returned":
        payload, tables = actual[1]
        index, numeric = _unpack_payload(payload)
        assert index["tables"] == tables
        assert len(numeric) == sum(table["byte_length"] for table in tables)
        if kind == "nested-empty-paths":
            assert tables[0]["empty_paths"] == [["a", "child", "deep-empty"], ["a", "empty"], ["z"]]
            assert numeric == struct.pack("<f" if precision == "float32" else "<d", -0.0)


@pytest.mark.parametrize("precision", ["float32", "float64"])
@pytest.mark.parametrize("count", [0, 1, 4095, 4096, 4097, 8193])
def test_numeric_rows_across_proposed_chunk_boundaries_have_identical_wire_bytes(precision, count):
    values = [(-0.0 if index % 17 == 0 else (index - 4000) / 16) for index in range(count)]
    data = {"values": {"first-empty": [], "row": values, "last": [0.125]}}
    options = _payload_options(data, precision)
    expected = old_functions()["_encode_state_payload"](data, **options)
    assert codec._encode_state_payload(data, **options) == expected
    index, raw = _unpack_payload(expected[0])
    # Assert typed bytes separately; float equality alone loses signed zero.
    ordered = [0.125, *values]  # sorted row names: first-empty, last, row.
    fmt = "<f" if precision == "float32" else "<d"
    assert raw == b"".join(struct.pack(fmt, value) for value in ordered)
    assert index["tables"][0]["row_lengths"] == [0, 1, count]


@pytest.mark.parametrize("precision", ["float32", "float64"])
@pytest.mark.parametrize("kind", ["nan", "positive-infinity", "negative-infinity", "huge-integer", "object", "mixed-nested-leaf"])
def test_direct_encoder_retains_exception_type_and_message(kind, precision):
    value = {"nan": float("nan"), "positive-infinity": float("inf"), "negative-infinity": -float("inf"),
             "huge-integer": 2**2000, "object": object(), "mixed-nested-leaf": {"outer": {"number": 1, "bad": None}}}[kind]
    data = {"bad": {"value": value}}
    options = _payload_options(data, precision)
    expected = _outcome(old_functions()["_encode_state_payload"], data, **options)
    assert expected[0] == "raised"
    assert _outcome(codec._encode_state_payload, data, **options) == expected


@pytest.mark.parametrize("prefix_length", [0, 4095, 4096])
@pytest.mark.parametrize("nonfinite_first", [False, True])
def test_multiple_invalid_values_preserve_first_scalar_error_across_chunks(prefix_length, nonfinite_first):
    class InfiniteInt(int):
        def __float__(self):
            return math.inf

    # Unlike an ordinary nonfinite float, this supported int subclass passes
    # canonical-copy validation. The original encoder detects nonfiniteness
    # only after scalar conversion, in the same loop as float32 overflow.
    invalid = [InfiniteInt(1), 1e40] if nonfinite_first else [1e40, InfiniteInt(1)]
    data = {"values": {"row": [0.125] * prefix_length + invalid}}
    options = _payload_options(data, "float32")
    expected = _outcome(old_functions()["_encode_state_payload"], data, **options)
    message = ("checkpoint numeric values must be finite" if nonfinite_first
               else "value 1e+40 cannot be represented as float32")
    assert expected == ("raised", ValueError, message)
    assert _outcome(codec._encode_state_payload, data, **options) == expected


@pytest.mark.parametrize("precision", ["float32", "float64", "float16", None, []])
def test_precision_validation_and_unselected_invalid_component_keep_legacy_order(precision):
    data = {"selected": {"row": [-0.0, 0.125]}, "unselected": object()}
    options = _payload_options(data, precision, selected=["selected", "selected"])
    reference = old_functions()["_encode_state_payload"]
    assert _outcome(codec._encode_state_payload, data, **options) == _outcome(reference, data, **options)


@pytest.mark.parametrize("precision", ["float32", "float64"])
@pytest.mark.parametrize("case", ["ragged-nested-unicode", "surrogate-key", "float32-boundaries", "float64-extremes", "nonfinite"])
def test_public_full_and_delta_edge_acceptance_bytes_and_errors_remain_exact(precision, case):
    base = fixture()
    current = copied(base)
    if case == "ragged-nested-unicode":
        current.feature_embedding_weights = {"é/法": [-0.0, 0.125], "empty": [], "line\n": [1.0]}
        current.proof_auxiliary_head_logits = {"obligation_family": {"__global__": {"number": -0.0}, "empty": {}}}
        current.applied_todo_ids[:] = ["é", "duplicate", "duplicate", "line\n"]
    elif case == "surrogate-key":
        current.feature_embedding_weights["\ud800"] = [-0.0]
    elif case == "float32-boundaries":
        current.feature_embedding_weights["boundary"] = [1 + 2**-24, math.nextafter(1 + 2**-24, math.inf),
                                                          2**-150, -(2**-150), 2**-149, float.fromhex("0x1.fffffep+127")]
    elif case == "float64-extremes":
        current.feature_embedding_weights["boundary"] = [float.fromhex("0x1.fffffffffffffp+1023"), 5e-324, -5e-324]
    else:
        current.feature_embedding_weights["bad"] = [float("nan")]
    reference = old_functions()
    options = {"float_precision": precision, "metadata": {"fixture": case}}
    full = _outcome(reference["serialize_checkpoint"], current, **options)
    if case in {"ragged-nested-unicode", "float32-boundaries"} or (case == "float64-extremes" and precision == "float64"):
        assert full[0] == "returned"
    assert _outcome(codec.serialize_checkpoint, current, **options) == full
    delta = _outcome(reference["serialize_delta"], base, current, **options)
    assert _outcome(codec.serialize_delta, base, current, **options) == delta
    baseline = codec.checkpoint_baseline(base, float_precision=precision)
    def baseline_bytes():
        return codec.serialize_delta_from_baseline(baseline, current, **options).payload
    assert _outcome(baseline_bytes) == delta


@pytest.mark.parametrize("precision", ["float32", "float64"])
def test_writer_full_and_baseline_delta_use_exact_independent_old_bytes(tmp_path, precision):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.async_artifact_writer import AsyncArtifactWriter
    state = fixture()
    reference = old_functions()
    writer = AsyncArtifactWriter(tmp_path / "spool", autostart=False)
    try:
        full = writer.snapshot_state_checkpoint(state, cycle=0, float_precision=precision)
        assert full.payload == reference["serialize_checkpoint"](
            state, float_precision=precision, metadata={"cycle": 0}, revision=state.state_revision)
        current = copied(state)
        current.feature_embedding_weights["a"] = [-0.0, 0.125, 1.0 / 3]
        delta = writer.snapshot_state_checkpoint(current, cycle=1, full=False,
            base_baseline=full.checkpoint_baseline, float_precision=precision)
        assert delta.payload == reference["serialize_delta"](state, current,
            float_precision=precision, metadata={"cycle": 1}, base_revision=state.state_revision,
            revision=current.state_revision)
    finally:
        writer.close(cancel_pending=True)
