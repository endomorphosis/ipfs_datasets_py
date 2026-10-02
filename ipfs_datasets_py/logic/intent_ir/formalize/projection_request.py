"""Inert, explicitly selected context for a particular learned Intent candidate.

Hashes bind inputs, not truth or authorization. A request supplies modeling
premises only; it cannot replace the decoded IR or the original instruction.
"""
from __future__ import annotations

import hashlib
import json
import re

from .projection_contracts import canonical_bytes, source_ir_sha256

SCHEMA = "intent-projection-request/v1"
MAX_REQUEST_BYTES = 65_536
_FIELDS = {"schema", "instruction_sha256", "source_ir_sha256", "checkpoint_sha256",
           "context", "requested_families", "request_sha256"}


def validate_projection_request_shape(request):
    """Validate transportable data without inference, imports chosen by data, or tools."""
    from .extended_projections import DEFAULT_FAMILIES, ADDITIONAL_REQUIREMENTS
    if type(request) is not dict or set(request) != _FIELDS or request["schema"] != SCHEMA:
        raise ValueError("closed Intent projection request required")
    if len(canonical_bytes(request)) > MAX_REQUEST_BYTES:
        raise ValueError("Intent projection request exceeds its byte bound")
    for name in ("instruction_sha256", "source_ir_sha256", "checkpoint_sha256", "request_sha256"):
        if type(request[name]) is not str or not re.fullmatch(r"[0-9a-f]{64}", request[name]):
            raise ValueError("exact Intent projection request digests required")
    context = request["context"]
    if (type(context) is not dict or set(context) - {"modal", "state", "structural"}
            or any(type(value) is not dict for value in context.values())):
        raise ValueError("closed Intent projection context namespaces required")
    families = request["requested_families"]
    if families is not None and (type(families) is not list or not 1 <= len(families) <= 24
            or any(type(value) is not str or value not in {*DEFAULT_FAMILIES, *ADDITIONAL_REQUIREMENTS}
                   for value in families) or len(set(families)) != len(families)):
        raise ValueError("unique registered extension family selection required")
    payload = {key: value for key, value in request.items() if key != "request_sha256"}
    if hashlib.sha256(canonical_bytes(payload)).hexdigest() != request["request_sha256"]:
        raise ValueError("Intent projection request digest differs")
    return json.loads(canonical_bytes(request))


def validate_intent_projection_request(request, *, instruction, document, checkpoint_sha256):
    request = validate_projection_request_shape(request)
    if (type(instruction) is not str or not instruction.strip()
            or request["instruction_sha256"] != hashlib.sha256(instruction.encode()).hexdigest()
            or request["source_ir_sha256"] != source_ir_sha256(document)
            or request["checkpoint_sha256"] != checkpoint_sha256):
        raise ValueError("Intent projection request does not bind the exact instruction, candidate, and checkpoint")
    return request


def make_intent_projection_request(instruction, document, *, checkpoint_sha256,
                                   context=None, requested_families=None):
    if type(instruction) is not str or not instruction.strip():
        raise ValueError("exact nonempty instruction required")
    payload = {"schema": SCHEMA, "instruction_sha256": hashlib.sha256(instruction.encode()).hexdigest(),
        "source_ir_sha256": source_ir_sha256(document), "checkpoint_sha256": checkpoint_sha256,
        "context": {} if context is None else context, "requested_families": requested_families}
    payload["request_sha256"] = hashlib.sha256(canonical_bytes(payload)).hexdigest()
    return validate_projection_request_shape(payload)


__all__ = ["make_intent_projection_request", "validate_intent_projection_request",
           "validate_projection_request_shape", "MAX_REQUEST_BYTES"]
