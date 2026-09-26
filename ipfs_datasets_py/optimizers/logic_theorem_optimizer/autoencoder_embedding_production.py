"""Bounded, exact receipts for locally produced pinned GTE-small embeddings.

A receipt binds supplied source bytes, selectors, token inputs, float32 output,
and producer/runtime evidence. It is an integrity record, not cryptographic
attestation that inference occurred, official source authentication, or a proof
of a legal/formal claim. Injected fixtures are permanently diagnostic.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import struct
from typing import Any, Callable, Mapping, Sequence

from .autoencoder_corpus_manifest import (
    CorpusManifestError, EmbeddingProvenance, SourceSampleRecord, SourceSpan,
    _read_verified,
)
from .autoencoder_training_worker import SampleRecord

SCHEMA = "autoencoder-embedding-production-v1"
MODEL_ID = "thenlper/gte-small"
MODEL_REVISION = "17e1f347d17fe144873b1201da91788898c639cd"
DIMENSION = 384
MAX_TOKENS = 512
MAX_RECORDS = 256
MAX_BYTES = 64 * 1024 * 1024
MAX_TEXT_BYTES = 1024 * 1024
STATUSES = ("embedded", "token_limit_exceeded", "missing_input")
_HASH = re.compile(r"[0-9a-f]{64}")
_INPUT_ID = re.compile(r"sha256:[0-9a-f]{64}")
_EXECUTION = {
    "backend": "sentence-transformers", "device": "cpu", "eval_mode": True,
    "gradient_mode": "inference_mode", "pooling": "mean", "normalization": "l2",
    "max_tokens": MAX_TOKENS, "truncation": False,
    "dtype": "float32", "cpu_threads": 1, "seed": 0,
}
_QUALIFICATION = {
    "record_integrity": True,
    "source_authority_authenticated": False,
    "model_revision_authenticated": False,
    "runtime_cryptographically_attested": False,
    "runtime_computation_proven": False,
    "formal_proof_verified": False,
}


class EmbeddingProductionError(ValueError):
    """The bounded producer evidence contract is invalid."""


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=True,
                          allow_nan=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError, OverflowError) as exc:
        raise EmbeddingProductionError("invalid strict JSON value") from exc


def _parse(raw: bytes) -> Any:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise EmbeddingProductionError("duplicate JSON field")
            result[key] = value
        return result

    def invalid(_):
        raise EmbeddingProductionError("nonfinite JSON number")

    try:
        return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)
    except (ValueError, UnicodeError, RecursionError, OverflowError) as exc:
        raise EmbeddingProductionError("invalid receipt JSON") from exc


def _keys(value, expected, name):
    if type(value) is not dict or set(value) != set(expected):
        raise EmbeddingProductionError(f"{name} has unknown or missing fields")
    return dict(value)


def _integer(value, name, minimum=0, maximum=2**31 - 1):
    if type(value) is not int or not minimum <= value <= maximum:
        raise EmbeddingProductionError(f"{name} is outside its integer bound")
    return value


def _digest(value, name):
    if type(value) is not str or not _HASH.fullmatch(value):
        raise EmbeddingProductionError(f"{name} requires a lowercase SHA-256")
    return value


def _text(value, name, maximum=4096):
    try:
        valid = type(value) is str and value.strip() and len(value.encode("utf-8")) <= maximum
    except UnicodeError as exc:
        raise EmbeddingProductionError(f"{name} is not exact UTF-8") from exc
    if not valid:
        raise EmbeddingProductionError(f"{name} requires bounded nonempty text")
    return value


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class EmbeddingInput:
    """An exact source input, without a mock model or placeholder vector."""

    source: SourceSpan
    title: str
    section: str
    text: str
    citation: str

    def __post_init__(self):
        if not isinstance(self.source, SourceSpan):
            raise EmbeddingProductionError("input source must be a SourceSpan")
        try:
            # Revalidate even caller-constructed or replaced frozen instances.
            source = SourceSpan.from_dict(asdict(self.source))
        except (ValueError, TypeError) as exc:
            raise EmbeddingProductionError("invalid input source span") from exc
        if source.normalization != "identity":
            raise EmbeddingProductionError("producer requires identity source normalization")
        if source.artifact.bytes > MAX_BYTES:
            raise EmbeddingProductionError("source artifact exceeds byte bound")
        for name in ("title", "section", "citation"):
            _text(getattr(self, name), name)
        _text(self.text, "input text", MAX_TEXT_BYTES)
        if self.citation != source.citation:
            raise EmbeddingProductionError("input citation differs from source citation")

    def _payload(self):
        return {"source": asdict(self.source), "title": self.title, "section": self.section,
                "text": self.text, "citation": self.citation}

    @property
    def input_id(self):
        return "sha256:" + _sha(_canonical({"schema": "source-embedding-input-v1", **self._payload()}))

    def to_dict(self):
        return {"input_id": self.input_id, **self._payload()}

    @classmethod
    def from_dict(cls, value):
        data = _keys(value, {"input_id", "source", "title", "section", "text", "citation"}, "input")
        identity = data.pop("input_id")
        try:
            data["source"] = SourceSpan.from_dict(data["source"])
            result = cls(**data)
        except (ValueError, TypeError) as exc:
            raise EmbeddingProductionError("invalid source embedding input") from exc
        if type(identity) is not str or not _INPUT_ID.fullmatch(identity) or result.input_id != identity:
            raise EmbeddingProductionError("input identity mismatch")
        return result

    @classmethod
    def from_source_record(cls, record: SourceSampleRecord):
        try:
            record = SourceSampleRecord.from_dict(record.to_dict())
        except (AttributeError, TypeError, ValueError) as exc:
            raise EmbeddingProductionError("invalid source sample record") from exc
        return cls(record.source, record.sample.title, record.sample.section,
                   record.sample.text, record.sample.citation)


def native_execution_profile(*, batch_size: int = 16) -> dict[str, Any]:
    """Return the sole qualified runtime profile; the caller must execute it."""
    _integer(batch_size, "batch_size", 1, 16)
    return {"kind": "native", "batch_size": batch_size, **_EXECUTION}


def _execution(value):
    value = _keys(value, {"kind", "batch_size", *_EXECUTION}, "execution")
    _integer(value["batch_size"], "batch_size", 1, 16)
    if value["kind"] not in ("native", "injected_fixture"):
        raise EmbeddingProductionError("unsupported execution kind")
    for key, expected in _EXECUTION.items():
        if type(value[key]) is not type(expected) or value[key] != expected:
            raise EmbeddingProductionError(f"unqualified execution {key}")
    return value


def _tokens(value, *, maximum=MAX_TOKENS):
    data = _keys(value, {"input_ids", "attention_mask", "token_type_ids"}, "token inputs")
    ids, mask, types = (data[key] for key in ("input_ids", "attention_mask", "token_type_ids"))
    if type(ids) is not list or not 1 <= len(ids) <= maximum:
        raise EmbeddingProductionError("token count exceeds qualified bound")
    if type(mask) is not list or len(mask) != len(ids):
        raise EmbeddingProductionError("attention mask length differs from input IDs")
    for value in ids:
        _integer(value, "token ID")
    for value in mask:
        _integer(value, "attention mask", maximum=1)
    if not any(mask):
        raise EmbeddingProductionError("token inputs have no attended tokens")
    if types is not None:
        if type(types) is not list or len(types) != len(ids):
            raise EmbeddingProductionError("token type mask length differs from input IDs")
        for value in types:
            _integer(value, "token type ID")
    return data


def token_input_digest(tokens: Mapping[str, Any]) -> dict[str, Any]:
    """Bind the full untruncated token inputs for an oversized disposition."""
    data = _tokens(tokens, maximum=MAX_TEXT_BYTES)
    return {"token_count": len(data["input_ids"]), "sha256": _sha(_canonical(data))}


def _encode_vector(vector):
    if type(vector) not in (list, tuple) or len(vector) != DIMENSION:
        raise EmbeddingProductionError("embedding must contain exactly 384 float32 values")
    bits = []
    for value in vector:
        if type(value) is not float or not math.isfinite(value):
            raise EmbeddingProductionError("embedding values must be finite exact float32 values")
        try:
            packed = struct.pack(">f", value)
        except (OverflowError, struct.error) as exc:
            raise EmbeddingProductionError("embedding value exceeds float32") from exc
        if struct.unpack(">f", packed)[0] != value:
            raise EmbeddingProductionError("embedding value is not an exact float32 value")
        bits.append(packed)
    result = {"encoding": "float32-be-hex", "dimension": DIMENSION, "bits": b"".join(bits).hex()}
    _decode_vector(result)
    return result


def _decode_vector(value):
    data = _keys(value, {"encoding", "dimension", "bits"}, "embedding")
    if data["encoding"] != "float32-be-hex" or type(data["dimension"]) is not int or data["dimension"] != DIMENSION:
        raise EmbeddingProductionError("unsupported embedding encoding or dimension")
    bits = data["bits"]
    if type(bits) is not str or not re.fullmatch(r"[0-9a-f]{3072}", bits):
        raise EmbeddingProductionError("invalid float32 embedding bits")
    values = struct.unpack(f">{DIMENSION}f", bytes.fromhex(bits))
    if not all(math.isfinite(item) for item in values):
        raise EmbeddingProductionError("embedding contains nonfinite float32 bits")
    norm = math.sqrt(math.fsum(item * item for item in values))
    if not math.isclose(norm, 1.0, rel_tol=0, abs_tol=1e-5):
        raise EmbeddingProductionError("embedding is not L2 normalized")
    return values


def _assets(value):
    if type(value) is not list or not 1 <= len(value) <= 64:
        raise EmbeddingProductionError("model asset count exceeds bound")
    names, total = [], 0
    for asset in value:
        data = _keys(asset, {"name", "sha256", "bytes"}, "model asset")
        name = _text(data["name"], "model asset name", 512)
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name or str(path) != name:
            raise EmbeddingProductionError("model asset name must be a canonical relative path")
        _digest(data["sha256"], "model asset SHA-256")
        total += _integer(data["bytes"], "model asset bytes", 1, 512 * 1024 * 1024)
        names.append(name)
    if names != sorted(set(names)) or total > 1024 * 1024 * 1024:
        raise EmbeddingProductionError("model asset manifest must be unique, sorted and bounded")
    required = {"config.json", "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json",
                "modules.json", "1_Pooling/config.json", "sentence_bert_config.json", "vocab.txt"}
    if not required <= set(names) or not {"model.safetensors", "pytorch_model.bin"} & set(names):
        raise EmbeddingProductionError("model asset manifest lacks model/tokenizer/pooling evidence")
    return value


def _producer(value):
    data = _keys(value, {"code_sha256", "runtime_versions"}, "producer")
    _digest(data["code_sha256"], "producer code SHA-256")
    versions = _keys(data["runtime_versions"], {"python", "torch", "transformers", "sentence_transformers", "tokenizers"}, "runtime versions")
    for name, version in versions.items():
        _text(version, name + " version", 256)
    return data


def _validate_inputs(inputs):
    if type(inputs) not in (list, tuple) or not 1 <= len(inputs) <= MAX_RECORDS:
        raise EmbeddingProductionError("input count exceeds bounded producer contract")
    checked = []
    for item in inputs:
        if not isinstance(item, EmbeddingInput):
            raise EmbeddingProductionError("inputs must contain EmbeddingInput values")
        checked.append(EmbeddingInput.from_dict(item.to_dict()))
    if len({item.input_id for item in checked}) != len(checked):
        raise EmbeddingProductionError("duplicate input identity")
    selectors = [(item.source.artifact.sha256, item.source.byte_start, item.source.byte_end) for item in checked]
    if len(set(selectors)) != len(selectors):
        raise EmbeddingProductionError("duplicate source selector")
    sources = {}
    for item in checked:
        source = item.source.artifact
        if sources.setdefault(source.sha256, source.bytes) != source.bytes:
            raise EmbeddingProductionError("source digest has inconsistent declared byte sizes")
    if sum(sources.values()) > MAX_BYTES or sum(len(item.text.encode("utf-8")) for item in checked) > MAX_BYTES:
        raise EmbeddingProductionError("aggregate source/input bytes exceed bound")
    return tuple(checked)


def _verify_sources(inputs, rows, resolver):
    if not callable(resolver):
        raise EmbeddingProductionError("source verification requires a resolver")
    cache = {}
    verified = 0
    for item, row in zip(inputs, rows):
        if row["status"] == "missing_input":
            continue
        ref = asdict(item.source.artifact)
        if ref["sha256"] not in cache:
            try:
                raw = _read_verified(resolver(dict(ref)), ref, MAX_BYTES)
                raw.decode("utf-8")
            except (CorpusManifestError, KeyError, OSError, TypeError, ValueError, UnicodeError) as exc:
                raise EmbeddingProductionError("source bytes unavailable or identity mismatch") from exc
            cache[ref["sha256"]] = raw
        raw = cache[ref["sha256"]]
        try:
            selected = raw[item.source.byte_start:item.source.byte_end].decode("utf-8")
        except UnicodeError as exc:
            raise EmbeddingProductionError("source selector is not exact UTF-8") from exc
        if selected != item.text:
            raise EmbeddingProductionError("source selector differs from exact embedding input")
        verified += 1
    return {"source_bytes_verified": sum(map(len, cache.values())),
            "source_inputs_verified": verified, "source_artifacts_verified": len(cache)}


def validate_embedding_inputs(inputs: Sequence[EmbeddingInput], *, resolver: Callable) -> tuple[EmbeddingInput, ...]:
    """Validate bounded exact inputs and source bytes before loading a runtime."""
    checked = _validate_inputs(inputs)
    _verify_sources(checked, [{"status": "pending"} for _ in checked], resolver)
    return checked


@dataclass(frozen=True)
class EmbeddingProductionReceipt:
    """Validated immutable canonical bytes. All consumption rechecks source bytes."""

    _raw: bytes

    def __post_init__(self):
        if type(self._raw) is not bytes or not 1 <= len(self._raw) <= MAX_BYTES:
            raise EmbeddingProductionError("receipt exceeds byte bound")
        data = _keys(_parse(self._raw), {"schema", "model", "execution", "model_assets", "producer",
                                       "inputs", "results", "status_counts", "qualification"}, "receipt")
        if data["schema"] != SCHEMA or _canonical(data) != self._raw:
            raise EmbeddingProductionError("unsupported or noncanonical receipt")
        model = _keys(data["model"], {"model_id", "revision", "dimension"}, "model")
        if model != {"model_id": MODEL_ID, "revision": MODEL_REVISION, "dimension": DIMENSION} or type(model["dimension"]) is not int:
            raise EmbeddingProductionError("model differs from the pinned qualified model")
        _execution(data["execution"])
        _assets(data["model_assets"])
        _producer(data["producer"])
        if type(data["inputs"]) is not list or not 1 <= len(data["inputs"]) <= MAX_RECORDS:
            raise EmbeddingProductionError("input count exceeds bounded producer contract")
        inputs = _validate_inputs([EmbeddingInput.from_dict(item) for item in data["inputs"]])
        rows = data["results"]
        if type(rows) is not list or len(rows) != len(inputs):
            raise EmbeddingProductionError("results must cover every input exactly once")
        counts = dict.fromkeys(STATUSES, 0)
        for item, row in zip(inputs, rows):
            row = _keys(row, {"input_id", "status", "tokens", "vector"}, "result")
            if row["input_id"] != item.input_id or type(row["status"]) is not str or row["status"] not in STATUSES:
                raise EmbeddingProductionError("result input identity or disposition mismatch")
            counts[row["status"]] += 1
            if row["status"] == "embedded":
                _tokens(row["tokens"])
                _decode_vector(row["vector"])
            elif row["status"] == "token_limit_exceeded":
                token_ref = _keys(row["tokens"], {"token_count", "sha256"}, "oversized token evidence")
                _integer(token_ref["token_count"], "oversized token count", MAX_TOKENS + 1, MAX_TEXT_BYTES)
                _digest(token_ref["sha256"], "oversized token SHA-256")
                if row["vector"] is not None:
                    raise EmbeddingProductionError("oversized input must have no vector")
            elif row["tokens"] is not None or row["vector"] is not None:
                raise EmbeddingProductionError("missing input must have no tokens or vector")
        declared = _keys(data["status_counts"], STATUSES, "status counts")
        if any(type(value) is not int or value != counts[key] for key, value in declared.items()):
            raise EmbeddingProductionError("disposition counts do not match complete result coverage")
        qualification = _keys(data["qualification"], _QUALIFICATION, "qualification")
        if any(type(value) is not bool or value is not _QUALIFICATION[key] for key, value in qualification.items()):
            raise EmbeddingProductionError("unsupported qualification claim")

    def to_bytes(self):
        return self._raw

    def to_dict(self):
        return _parse(self._raw)

    @property
    def sha256(self):
        return _sha(self._raw)

    @property
    def inputs(self):
        return tuple(EmbeddingInput.from_dict(item) for item in self.to_dict()["inputs"])

    @property
    def status_counts(self):
        return self.to_dict()["status_counts"]

    @property
    def native_execution_profile(self):
        return self.to_dict()["execution"]["kind"] == "native"

    def verification_summary(self):
        data = self.to_dict()
        return {"schema": SCHEMA, "sha256": self.sha256, "bytes": len(self._raw),
                "input_count": len(data["inputs"]), "status_counts": data["status_counts"],
                "execution_kind": data["execution"]["kind"],
                "native_execution_profile": data["execution"]["kind"] == "native",
                **data["qualification"]}

    def validate_sources(self, resolver):
        # Reparse rather than trust arbitrary dataclass labels or cached fields.
        receipt = EmbeddingProductionReceipt(self._raw)
        return {**receipt.verification_summary(),
                **_verify_sources(receipt.inputs, receipt.to_dict()["results"], resolver)}

    def to_corpus_records(self, *, resolver) -> tuple[SourceSampleRecord, ...]:
        receipt = EmbeddingProductionReceipt(self._raw)
        receipt.validate_sources(resolver)
        return receipt._corpus_records()

    def _corpus_records(self):
        data = self.to_dict()
        if data["execution"]["kind"] != "native":
            raise EmbeddingProductionError("injected fixtures are not eligible for native corpus conversion")
        result = []
        provenance = EmbeddingProvenance(MODEL_ID, MODEL_REVISION, self.sha256)
        for item, row in zip(self.inputs, data["results"]):
            if row["status"] != "embedded":
                continue
            if item.source.source_kind != "us_code" or item.source.language != "en":
                raise EmbeddingProductionError("native corpus conversion requires English us_code inputs")
            sample = SampleRecord(item.title, item.section, item.text, item.citation,
                                  MODEL_ID, _decode_vector(row["vector"]))
            result.append(SourceSampleRecord(item.source, sample, provenance))
        return tuple(result)

    def verify_records(self, records: Sequence[SourceSampleRecord], *, resolver, allow_subset=True):
        receipt = EmbeddingProductionReceipt(self._raw)
        if type(allow_subset) is not bool:
            raise EmbeddingProductionError("allow_subset must be boolean")
        expected = {record.record_id: record for record in receipt._corpus_records()}
        if type(records) not in (list, tuple) or not 1 <= len(records) <= len(expected):
            raise EmbeddingProductionError("supplied record count differs from successful producer rows")
        seen, checked = set(), []
        for supplied in records:
            try:
                supplied = SourceSampleRecord.from_dict(supplied.to_dict())
            except (AttributeError, ValueError, TypeError) as exc:
                raise EmbeddingProductionError("invalid supplied source sample record") from exc
            record = expected.get(supplied.record_id)
            if record is None or _canonical(supplied.to_dict()) != _canonical(record.to_dict()):
                raise EmbeddingProductionError("supplied source/vector/provenance differs from receipt")
            if supplied.record_id in seen:
                raise EmbeddingProductionError("duplicate supplied producer record")
            seen.add(supplied.record_id)
            checked.append(EmbeddingInput.from_source_record(record))
        if not allow_subset and seen != set(expected):
            raise EmbeddingProductionError("supplied records do not cover all successful producer rows")
        sources = _verify_sources(checked, [{"status": "embedded"} for _ in checked], resolver)
        return {**receipt.verification_summary(), "supplied_records_verified": len(checked),
                "source_selectors_verified": True, **sources}

    def save(self, destination, *, resolver):
        self.validate_sources(resolver)
        path = Path(destination)
        with path.open("xb") as stream:
            stream.write(self._raw)
            stream.flush()
            os.fsync(stream.fileno())
        return {"path": str(path.absolute()), "sha256": self.sha256, "bytes": len(self._raw)}


def build_embedding_production_receipt(inputs: Sequence[EmbeddingInput], *, results: Sequence[Mapping[str, Any]],
                                       execution: Mapping[str, Any], model_assets: Sequence[Mapping[str, Any]],
                                       producer: Mapping[str, Any], resolver: Callable) -> EmbeddingProductionReceipt:
    """Build from actual producer outputs and verify exact source bytes immediately.

    ``results`` preserve input order, using raw Python float32-exact vectors for
    successful rows. Oversized rows supply :func:`token_input_digest`; missing
    input dispositions assert only that no vector was produced, not global absence.
    """
    inputs = _validate_inputs(inputs)
    _execution(execution)
    _assets(model_assets)
    _producer(producer)
    if type(results) not in (list, tuple) or len(results) != len(inputs):
        raise EmbeddingProductionError("results must cover every input exactly once")
    rows = []
    for result in results:
        row = _keys(result, {"input_id", "status", "tokens", "vector"}, "producer result")
        if row["status"] == "embedded":
            _tokens(row["tokens"])
            row["vector"] = _encode_vector(row["vector"])
        elif row["status"] == "token_limit_exceeded":
            token_ref = _keys(row["tokens"], {"token_count", "sha256"}, "oversized token evidence")
            _integer(token_ref["token_count"], "oversized token count", MAX_TOKENS + 1, MAX_TEXT_BYTES)
            _digest(token_ref["sha256"], "oversized token SHA-256")
            if row["vector"] is not None:
                raise EmbeddingProductionError("oversized input must have no vector")
        elif row["status"] != "missing_input" or row["tokens"] is not None or row["vector"] is not None:
            raise EmbeddingProductionError("invalid missing input disposition")
        rows.append(row)
    receipt = EmbeddingProductionReceipt(_canonical({
        "schema": SCHEMA, "model": {"model_id": MODEL_ID, "revision": MODEL_REVISION, "dimension": DIMENSION},
        "execution": execution, "model_assets": model_assets, "producer": producer,
        "inputs": [item.to_dict() for item in inputs], "results": rows,
        "status_counts": {status: sum(row["status"] == status for row in rows) for status in STATUSES},
        "qualification": _QUALIFICATION,
    }))
    receipt.validate_sources(resolver)
    return receipt


def load_embedding_production_receipt(path, *, expected_sha256: str, expected_size_bytes: int,
                                      resolver: Callable | None = None) -> EmbeddingProductionReceipt:
    """Load only the expected exact bytes; source verification precedes consumption."""
    _digest(expected_sha256, "receipt SHA-256")
    _integer(expected_size_bytes, "receipt bytes", 1, MAX_BYTES)
    try:
        raw = _read_verified(path, {"sha256": expected_sha256, "bytes": expected_size_bytes}, MAX_BYTES)
    except (CorpusManifestError, OSError, TypeError, ValueError) as exc:
        raise EmbeddingProductionError("receipt byte identity mismatch") from exc
    result = EmbeddingProductionReceipt(raw)
    if resolver is not None:
        result.validate_sources(resolver)
    return result
