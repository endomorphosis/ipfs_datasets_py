"""Lossless, sealed training targets. These artifacts never establish admission.

The metric disk cache and bridge ``to_dict`` summaries are deliberately not
used here. Safe tagged JSON preserves the complete document and approved rich
fields; loading never imports a class named by untrusted bytes.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
import hashlib
import json
import math
import os
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from ipfs_datasets_py.logic.bridge.multiview import LegalIRTrainingTarget
from ipfs_datasets_py.logic.bridge.types import LegalIRDocument, LogicIRView
from .legal_ir_grammar_decoder import LegalIRGrammarValidation, LegalIRGrammarRejection

SCHEMA_VERSION = "legal-ir-target-snapshot-v1"
DEFAULT_MAX_BYTES = 256 * 1024 * 1024
STATUSES = frozenset({"ready", "unsupported", "timeout", "unavailable", "failed"})


class TargetSnapshotError(ValueError):
    """Malformed, incomplete, incompatible or modified target artifact."""


def _json(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise TargetSnapshotError("unsupported JSON payload") from exc


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _digest(value: Any) -> str:
    return _sha(_json(value))


def _hash(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _parse(raw: bytes) -> Any:
    def pairs(items):
        # JSON supplies string keys. Constructing in C preserves their order;
        # a smaller dictionary proves at least one decoded key was repeated.
        result = dict(items)
        if len(result) != len(items):
            raise TargetSnapshotError("duplicate JSON key")
        return result
    def invalid(value):
        raise TargetSnapshotError(f"nonfinite JSON number: {value}")
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
    except (ValueError, UnicodeDecodeError, RecursionError) as exc:
        raise TargetSnapshotError("invalid snapshot JSON") from exc


class RichLegalIRTarget:
    """Explicit attribute-compatible rich target, with no implicit object codec.

    Values may include the whitelisted grammar dataclasses and full document.
    Arbitrary objects/callables are rejected by serialization. ``to_dict`` keeps
    candidate and grammar inputs visible to the current evaluator.
    """
    def __init__(self, values: Mapping[str, Any]):
        if not isinstance(values, Mapping) or any(not isinstance(k, str) or k.startswith("_") or k in {"to_dict"} for k in values):
            raise TargetSnapshotError("invalid rich target fields")
        object.__setattr__(self, "_values", dict(values))

    def __getattr__(self, name: str) -> Any:
        try:
            return self._values[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def to_dict(self) -> dict[str, Any]:
        return dict(self._values)


def _types() -> dict[str, type]:
    # Importing these two explicit fallback classes is safe; names in a file
    # never select a module. Ordinary summary-cache objects are rejected below.
    from .modal_autoencoder import _CachedLegalIRDocument, _CachedLegalIRTrainingTarget
    return {cls.__name__: cls for cls in (
        LegalIRTrainingTarget, LegalIRDocument, LogicIRView,
        LegalIRGrammarValidation, LegalIRGrammarRejection,
        _CachedLegalIRDocument, _CachedLegalIRTrainingTarget,
    )}


def _encode(value: Any, depth: int = 0) -> Any:
    if depth > 100:
        raise TargetSnapshotError("target nesting limit exceeded")
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise TargetSnapshotError("nonfinite target number")
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(k, str) for k in value):
            raise TargetSnapshotError("target mapping keys must be strings")
        return {"type": "mapping", "items": [[k, _encode(v, depth + 1)] for k, v in value.items()]}
    if type(value) in (list, tuple):
        return {"type": type(value).__name__, "items": [_encode(v, depth + 1) for v in value]}
    if type(value) is RichLegalIRTarget:
        return {"type": "rich_target", "fields": _encode(value.to_dict(), depth + 1)}
    allowed = _types()
    name = type(value).__name__
    if name not in allowed or type(value) is not allowed[name]:
        raise TargetSnapshotError(f"unsupported target object type: {name}")
    return {"type": name, "fields": _encode({f.name: getattr(value, f.name) for f in fields(value)}, depth + 1)}


def _decode(value: Any, depth: int = 0) -> Any:
    if depth > 100:
        raise TargetSnapshotError("target nesting limit exceeded")
    if value is None or type(value) in (str, bool, int, float):
        if type(value) is float and not math.isfinite(value):
            raise TargetSnapshotError("nonfinite target number")
        return value
    if not isinstance(value, dict) or not isinstance(value.get("type"), str):
        raise TargetSnapshotError("invalid tagged value")
    kind = value["type"]
    if kind in {"mapping", "list", "tuple"}:
        if set(value) != {"type", "items"} or not isinstance(value["items"], list):
            raise TargetSnapshotError("invalid collection encoding")
        child_depth = depth + 1
        if kind != "mapping":
            result = []
            for item in value["items"]:
                # Primitive leaves dominate large targets. Preserve their exact
                # types and depth/finite checks without another recursive call.
                if child_depth > 100:
                    raise TargetSnapshotError("target nesting limit exceeded")
                item_type = type(item)
                if item is None or item_type in (str, bool, int):
                    result.append(item)
                elif item_type is float:
                    if not math.isfinite(item):
                        raise TargetSnapshotError("nonfinite target number")
                    result.append(item)
                else:
                    result.append(_decode(item, child_depth))
            return tuple(result) if kind == "tuple" else result
        result = {}
        for pair in value["items"]:
            if not isinstance(pair, list) or len(pair) != 2 or not isinstance(pair[0], str) or pair[0] in result:
                raise TargetSnapshotError("invalid or duplicate mapping key")
            if child_depth > 100:
                raise TargetSnapshotError("target nesting limit exceeded")
            item = pair[1]
            item_type = type(item)
            if item is None or item_type in (str, bool, int):
                result[pair[0]] = item
            elif item_type is float:
                if not math.isfinite(item):
                    raise TargetSnapshotError("nonfinite target number")
                result[pair[0]] = item
            else:
                result[pair[0]] = _decode(item, child_depth)
        return result
    if set(value) != {"type", "fields"}:
        raise TargetSnapshotError("invalid object encoding")
    data = _decode(value["fields"], depth + 1)
    if not isinstance(data, dict):
        raise TargetSnapshotError("object fields must be a mapping")
    if kind == "rich_target":
        return RichLegalIRTarget(data)
    cls = _types().get(kind)
    if cls is None or set(data) != {f.name for f in fields(cls)}:
        raise TargetSnapshotError("unknown object or field schema")
    try:
        return cls(**data)
    except (ValueError, TypeError) as exc:
        raise TargetSnapshotError("invalid object fields") from exc


@dataclass(frozen=True)
class TargetSnapshotConfig:
    bridge_names: tuple[str, ...]
    evaluate_provers: bool
    parallel_workers: int
    code_sha256: Mapping[str, str]
    dependency_provenance: Mapping[str, Any] | None = None
    target_timeout_seconds: float = 15.0

    def __post_init__(self):
        names = tuple(self.bridge_names)
        if not names or any(not isinstance(n, str) or not n.strip() for n in names) or len(set(names)) != len(names):
            raise TargetSnapshotError("bridge names must be ordered, nonempty and unique")
        if type(self.evaluate_provers) is not bool or type(self.parallel_workers) is not int or self.parallel_workers < 1:
            raise TargetSnapshotError("invalid prover/worker configuration")
        if type(self.target_timeout_seconds) not in (float, int) or not math.isfinite(self.target_timeout_seconds) or self.target_timeout_seconds <= 0:
            raise TargetSnapshotError("invalid timeout")
        if not isinstance(self.code_sha256, Mapping) or not self.code_sha256 or any(not isinstance(k, str) or not k or not _hash(v) for k, v in self.code_sha256.items()):
            raise TargetSnapshotError("code provenance requires content SHA-256 values")
        deps = self.dependency_provenance or {}
        if not isinstance(deps, Mapping):
            raise TargetSnapshotError("dependency provenance must be an object")
        _json(deps)
        object.__setattr__(self, "bridge_names", names)
        object.__setattr__(self, "code_sha256", MappingProxyType(dict(self.code_sha256)))
        object.__setattr__(self, "dependency_provenance", _parse(_json(deps)))

    def to_dict(self) -> dict[str, Any]:
        return {"bridge_names": list(self.bridge_names), "evaluate_provers": self.evaluate_provers,
                "parallel_workers": self.parallel_workers, "code_sha256": dict(self.code_sha256),
                "dependency_provenance": self.dependency_provenance, "target_timeout_seconds": self.target_timeout_seconds}

    @classmethod
    def from_dict(cls, value: Any) -> "TargetSnapshotConfig":
        if not isinstance(value, dict) or set(value) != {f.name for f in fields(cls)}:
            raise TargetSnapshotError("invalid target config schema")
        return cls(**value)


def _sample_payload(sample: Any) -> tuple[str, str]:
    from .legal_samples import LegalSample
    if type(sample) is not LegalSample:
        raise TargetSnapshotError("only qualified LegalSample objects are supported")
    sample.validate()
    # No rounding: json's finite float representation roundtrips IEEE float64.
    return sample.sample_id, _digest(_encode(sample.to_dict()))


def _target_status(target: Any) -> str:
    losses = getattr(target, "losses", {})
    document = getattr(target, "document", None)
    if type(target).__name__ == "_CachedLegalIRTrainingTarget":
        if type(target) is not _types()["_CachedLegalIRTrainingTarget"] or type(document) is not _types()["_CachedLegalIRDocument"]:
            raise TargetSnapshotError("invalid fallback type")
        if target.accepted is not False or not (str(document.canonical_hash()).startswith(("timeout:", "timeout-fallback:")) or "legal_ir_target_timeout_loss" in losses):
            raise TargetSnapshotError("lossy ordinary metric-cache target is not a full target")
        return "timeout"
    if type(target) not in (LegalIRTrainingTarget, RichLegalIRTarget):
        raise TargetSnapshotError("target must be a qualified training or rich target")
    if document is not None and type(document) is not LegalIRDocument:
        raise TargetSnapshotError("full LegalIRDocument required")
    if type(target) is LegalIRTrainingTarget and document is None:
        raise TargetSnapshotError("full LegalIRDocument required")
    return "ready"


def _validate_target(target: Any, sample_id: str, config: TargetSnapshotConfig, status: str):
    actual_status = _target_status(target)
    if actual_status == "timeout" and status != "timeout":
        raise TargetSnapshotError("timeout target status mismatch")
    names = getattr(target, "bridge_names", None)
    if names is not None and tuple(names) != config.bridge_names:
        raise TargetSnapshotError("target bridge order/config mismatch")
    document = getattr(target, "document", None)
    if document is not None and document.document_id != sample_id:
        raise TargetSnapshotError("target document/sample identity mismatch")
    if type(document) is LegalIRDocument:
        if any(not isinstance(getattr(document, name), str) for name in
               ("document_id", "source_text", "normalized_text", "source", "version")):
            raise TargetSnapshotError("invalid document text fields")
        if document.citation is not None and not isinstance(document.citation, str):
            raise TargetSnapshotError("invalid document citation")
        if not isinstance(document.views, Mapping) or any(
            not isinstance(k, str) or type(v) is not LogicIRView for k, v in document.views.items()
        ):
            raise TargetSnapshotError("invalid full document views")
        for view in document.views.values():
            if not isinstance(view.payload, Mapping) or not isinstance(view.metadata, Mapping):
                raise TargetSnapshotError("invalid full view payload")
        try:
            document.canonical_hash()
        except (TypeError, ValueError, AttributeError) as exc:
            raise TargetSnapshotError("invalid full document payload") from exc
    if hasattr(target, "accepted") and type(target.accepted) is not bool:
        raise TargetSnapshotError("accepted must be a boolean")
    for name in ("losses", "view_distribution"):
        numbers = getattr(target, name, {})
        if not isinstance(numbers, Mapping) or any(not isinstance(k, str) or type(v) not in (int, float) or not math.isfinite(v) for k, v in numbers.items()):
            raise TargetSnapshotError("invalid numeric target mapping")


@dataclass(frozen=True)
class TargetSnapshot:
    _raw: bytes

    def __post_init__(self):
        if type(self._raw) is not bytes:
            raise TargetSnapshotError("snapshot storage must be immutable bytes")
        _verified(self._raw)

    @property
    def snapshot_id(self) -> str:
        return _parse(self._raw)["snapshot_id"]

    @property
    def sha256(self) -> str:
        return _sha(self._raw)

    @property
    def config(self) -> TargetSnapshotConfig:
        return TargetSnapshotConfig.from_dict(_parse(self._raw)["config"])

    @property
    def sample_count(self) -> int:
        return len(_parse(self._raw)["records"])

    @property
    def statuses(self) -> dict[str, str]:
        return {r["sample_id"]: r["status"] for r in _parse(self._raw)["records"]}

    def to_bytes(self) -> bytes:
        return self._raw

    def save(self, path: str | Path) -> dict[str, Any]:
        destination = Path(path)
        with destination.open("xb") as handle:
            handle.write(self._raw)
            handle.flush()
            os.fsync(handle.fileno())
        descriptor = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return {"path": str(destination.resolve()), "sha256": self.sha256, "bytes": len(self._raw), "snapshot_id": self.snapshot_id}

    def targets_for(self, samples: Sequence[Any], *, config: TargetSnapshotConfig) -> dict[str, Any]:
        # Construction validated immutable bytes. Avoid hydrating the entire
        # snapshot again when this worker asks for just one manifested slice.
        data = _parse(self._raw)
        if _json(data["config"]) != _json(config.to_dict()):
            raise TargetSnapshotError("target configuration/provenance mismatch")
        records = {r["sample_id"]: r for r in data["records"]}
        result = {}
        for sample in samples:
            sample_id, digest = _sample_payload(sample)
            if sample_id in result:
                raise TargetSnapshotError("duplicate requested sample")
            row = records.get(sample_id)
            if row is None or row["sample_sha256"] != digest:
                raise TargetSnapshotError("missing or changed sample payload")
            if row["target"] is None:
                raise TargetSnapshotError(f"sample has no injectable target: {row['status']}")
            target = _decode(row["target"])
            document = getattr(target, "document", None)
            if type(document) is LegalIRDocument and document.source_text != sample.text:
                raise TargetSnapshotError("target document/source text mismatch")
            result[sample_id] = target
        return result


def _verified(raw: bytes) -> dict[str, Any]:
    data = _parse(raw)
    if not isinstance(data, dict) or set(data) != {"schema_version", "config", "records", "snapshot_id"} or data["schema_version"] != SCHEMA_VERSION:
        raise TargetSnapshotError("snapshot schema mismatch")
    config = TargetSnapshotConfig.from_dict(data["config"])
    body = {k: v for k, v in data.items() if k != "snapshot_id"}
    if data["snapshot_id"] != "sha256:" + _digest(body):
        raise TargetSnapshotError("snapshot identity mismatch")
    if not isinstance(data["records"], list) or not data["records"]:
        raise TargetSnapshotError("snapshot must contain records")
    seen = set()
    for row in data["records"]:
        if not isinstance(row, dict) or set(row) != {"sample_id", "sample_sha256", "status", "target", "target_sha256"}:
            raise TargetSnapshotError("invalid target record schema")
        if not isinstance(row["sample_id"], str) or not row["sample_id"] or row["sample_id"] in seen or not _hash(row["sample_sha256"]):
            raise TargetSnapshotError("invalid/duplicate sample identity")
        seen.add(row["sample_id"])
        if not isinstance(row["status"], str) or row["status"] not in STATUSES or row["target_sha256"] != _digest(row["target"]):
            raise TargetSnapshotError("target status or payload hash mismatch")
        if row["target"] is None:
            if row["status"] == "ready":
                raise TargetSnapshotError("ready target is missing")
        else:
            _validate_target(_decode(row["target"]), row["sample_id"], config, row["status"])
    return data


def build_target_snapshot(samples: Sequence[Any], targets: Mapping[str, Any], *, config: TargetSnapshotConfig,
                          statuses: Mapping[str, str] | None = None) -> TargetSnapshot:
    identities = [_sample_payload(sample) for sample in samples]
    ids = [sample_id for sample_id, _ in identities]
    if not ids or len(set(ids)) != len(ids) or set(targets) != set(ids):
        raise TargetSnapshotError("targets must cover unique sample membership exactly")
    if statuses is not None and set(statuses) != set(ids):
        raise TargetSnapshotError("status membership mismatch")
    records = []
    for sample_id, digest in identities:
        target = targets[sample_id]
        status = statuses[sample_id] if statuses is not None else _target_status(target)
        if target is None and statuses is None:
            raise TargetSnapshotError("missing target requires explicit failure status")
        encoded = None if target is None else _encode(target)
        records.append({"sample_id": sample_id, "sample_sha256": digest, "status": status,
                        "target": encoded, "target_sha256": _digest(encoded)})
    body = {"schema_version": SCHEMA_VERSION, "config": config.to_dict(), "records": records}
    raw = _json({**body, "snapshot_id": "sha256:" + _digest(body)})
    snapshot = TargetSnapshot(raw)
    # Failure inventory may deliberately contain records without an injectable
    # target, but full document records must still bind the requested text.
    for sample in samples:
        document = getattr(targets[sample.sample_id], "document", None)
        if type(document) is LegalIRDocument and document.source_text != sample.text:
            raise TargetSnapshotError("target document/source text mismatch")
    return snapshot


def load_target_snapshot(path: str | Path, *, expected_sha256: str, samples: Sequence[Any] | None = None,
                         config: TargetSnapshotConfig | None = None, max_bytes: int = DEFAULT_MAX_BYTES) -> TargetSnapshot:
    if not _hash(expected_sha256) or type(max_bytes) is not int or max_bytes < 1:
        raise TargetSnapshotError("expected digest and positive byte bound required")
    with Path(path).open("rb") as handle:
        raw = handle.read(max_bytes + 1)
    if len(raw) > max_bytes or _sha(raw) != expected_sha256:
        raise TargetSnapshotError("snapshot byte bound or external digest mismatch")
    snapshot = TargetSnapshot(raw)
    if config is not None and _json(snapshot.config.to_dict()) != _json(config.to_dict()):
        raise TargetSnapshotError("target configuration/provenance mismatch")
    if samples is not None:
        snapshot.targets_for(samples, config=config or snapshot.config)
    return snapshot
