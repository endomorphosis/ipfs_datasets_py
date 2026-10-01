"""Source-bound contracts for optional extended Intent logic projections.

Syntax validation is recorded separately from semantic fidelity and proof. These
reports cannot grant execution permission or turn an inferred node into evidence.
"""
from __future__ import annotations

import hashlib
import json
import re

SCHEMA = "intent-family-projection/v1"
MAX_REPORT_BYTES = 4 * 1024 * 1024
AUTHORITY = {"authority": "unverified_candidate_only", "proof_authority": False,
             "execution_authority": False, "completion_authority": False,
             "omission_authority": False, "source_semantics_verified": False}


def canonical_bytes(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                     allow_nan=False).encode("utf-8")
    if len(raw) > MAX_REPORT_BYTES:
        raise ValueError("extended Intent projection exceeds its byte bound")
    return raw


def validated_document(document):
    from ..decoder import decode_intent_ir
    from ..schema import validate_intent_ir
    if type(document) is dict:
        document = decode_intent_ir(document)
    return validate_intent_ir(document)


def source_ir_sha256(document):
    from ..canonicalize import canonical_intent_ir_bytes
    return hashlib.sha256(canonical_intent_ir_bytes(validated_document(document))).hexdigest()


def make_projection(document, *, family_id, profile_id=None, status="projected",
                    representation, source_node_ids=(), validation=(), assumptions=(),
                    unsupported=(), semantics="declaration_projection"):
    from ...families.registry import DEFAULT_REGISTRY
    from ...families.namespaces import BASELINE_NAMESPACES, NamespaceKind
    document = validated_document(document)
    if type(family_id) is not str or family_id not in DEFAULT_REGISTRY.families:
        raise ValueError("projection requires a canonical registered logic family")
    if profile_id is not None:
        if type(profile_id) is not str:
            raise ValueError("registered profile ID required")
        BASELINE_NAMESPACES.get(NamespaceKind.PROFILE, profile_id)
    if status not in {"projected", "partial", "unsupported"}:
        raise ValueError("explicit projection disposition required")
    if type(representation) is not dict or not representation:
        raise ValueError("structured projection representation required")
    known = {document.document_id, *(r.statement_id for r in document.statements),
             *(r.action_id for r in document.actions), *(r.edge_id for r in document.control_edges),
             *(r.ref_id for r in document.sources)}
    nodes = list(source_node_ids)
    if len(nodes) > 4096 or any(type(n) is not str or n not in known for n in nodes) or len(set(nodes)) != len(nodes):
        raise ValueError("projection references unknown or duplicate Intent nodes")
    observations = list(validation)
    if len(observations) > 128:
        raise ValueError("projection validation bound exceeded")
    for row in observations:
        if (type(row) is not dict or set(row) != {"validator", "status", "details"}
                or type(row["validator"]) is not str or not row["validator"]
                or row["status"] not in {"passed", "failed", "not_run", "unavailable"}
                or type(row["details"]) is not dict):
            raise ValueError("closed explicit validation observation required")
    losses = list(unsupported)
    if len(losses) > 4096:
        raise ValueError("projection frontier bound exceeded")
    for row in losses:
        if (type(row) is not dict or set(row) != {"node_id", "reason"}
                or type(row["node_id"]) is not str or row["node_id"] not in known
                or type(row["reason"]) is not str or not row["reason"]):
            raise ValueError("source-bound unsupported projection record required")
    if status == "projected" and (losses or any(v["status"] == "failed" for v in observations)):
        raise ValueError("a projected result cannot hide omitted nodes or failed validation")
    premises = list(assumptions)
    if (len(premises) > 256 or any(type(p) is not str or not p or len(p) > 4096 for p in premises)
            or type(semantics) is not str or not semantics or len(semantics) > 256):
        raise ValueError("bounded explicit projection semantics and assumptions required")
    value = {"schema": SCHEMA,
        "projection_id": f"intent-extended/{family_id}/{profile_id or 'default'}/v1",
        "family_id": family_id, "profile_id": profile_id, "status": status,
        "source_ir_sha256": source_ir_sha256(document), "source_node_ids": nodes,
        "representation": representation, "validation": observations, "assumptions": premises,
        "unsupported": losses, "semantics": semantics, **AUTHORITY}
    value = json.loads(canonical_bytes(value))
    value["projection_sha256"] = hashlib.sha256(canonical_bytes(value)).hexdigest()
    return value


def validate_projection(report, document):
    if type(report) is not dict:
        raise ValueError("extended Intent projection report required")
    keys = {"schema", "projection_id", "family_id", "profile_id", "status", "source_ir_sha256",
            "source_node_ids", "representation", "validation", "assumptions", "unsupported",
            "semantics", "projection_sha256", *AUTHORITY}
    if set(report) != keys:
        raise ValueError("extended projection fields differ")
    expected = make_projection(document, **{k: report[k] for k in (
        "family_id", "profile_id", "status", "representation", "source_node_ids", "validation",
        "assumptions", "unsupported", "semantics")})
    if canonical_bytes(report) != canonical_bytes(expected):
        raise ValueError("extended projection source, authority, or digest differs")
    return report


def safe_symbol(value, *, prefix="sym"):
    """Collision-resistant external names; original strings stay in symbol maps."""
    if type(value) is not str or not value or len(value) > 65536:
        raise ValueError("bounded nonempty symbol value required")
    if type(prefix) is not str or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", prefix):
        raise ValueError("safe symbol namespace required")
    return prefix + "_" + hashlib.sha256(value.encode()).hexdigest()


__all__ = ["make_projection", "validate_projection", "validated_document", "source_ir_sha256",
           "safe_symbol", "canonical_bytes", "SCHEMA", "AUTHORITY"]
