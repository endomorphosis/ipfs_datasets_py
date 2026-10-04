"""Historical strict target codec for diagnostic throughput comparison only.

Execute these definitions with the canonical codec globals. Artifact identity,
source/configuration qualification, and training behavior are separate checks.
"""
from __future__ import annotations

# Source: ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_ir_target_snapshot.py
# Original source SHA-256: 7d0a014c4856826aafbe972534456af72e5b69c737662f8ce93a3e8e1d647c9b

def _parse(raw: bytes) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise TargetSnapshotError("duplicate JSON key")
            result[key] = value
        return result
    def invalid(value):
        raise TargetSnapshotError(f"nonfinite JSON number: {value}")
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
    except (ValueError, UnicodeDecodeError, RecursionError) as exc:
        raise TargetSnapshotError("invalid snapshot JSON") from exc


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
        if kind != "mapping":
            result = [_decode(v, depth + 1) for v in value["items"]]
            return tuple(result) if kind == "tuple" else result
        result = {}
        for pair in value["items"]:
            if not isinstance(pair, list) or len(pair) != 2 or not isinstance(pair[0], str) or pair[0] in result:
                raise TargetSnapshotError("invalid or duplicate mapping key")
            result[pair[0]] = _decode(pair[1], depth + 1)
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
