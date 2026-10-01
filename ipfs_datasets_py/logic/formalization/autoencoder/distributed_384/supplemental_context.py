"""Separate, source-bound interpretation evidence for unchanged native models.

The native v7 owner still receives exactly its published source-input contract.
Additional interpretations belong to the candidate gate and never replace a
native declaration or become learned checkpoint output.
"""
from copy import deepcopy

from .contracts import digest, raw, require
from .projection_context_contract import bind_context, validate_context

KEY = "supplemental_interpretations"
KINDS = {"concurrency", "protocol", "refinement"}


def canonical_interpretations(rows):
    """Validate the envelope; each emitter validates its interpretation schema."""
    require(type(rows) is list and len(rows) <= len(KINDS),
            "bounded supplemental interpretation list required")
    require(len(raw(rows)) <= 1024 * 1024, "supplemental interpretations exceed byte bound")
    seen = set()
    for row in rows:
        require(type(row) is dict and set(row) == {"kind", "interpretation"}
                and type(row["kind"]) is str and row["kind"] in KINDS
                and row["kind"] not in seen and type(row["interpretation"]) is dict,
                "closed unique supplemental interpretation kind required")
        seen.add(row["kind"])
        identity = row["interpretation"].get("native_document_sha256")
        require(type(identity) is str and len(identity) == 64
                and all(c in "0123456789abcdef" for c in identity),
                "exact native document digest required for supplemental interpretation")
    return deepcopy(rows)


def split_context(domain, candidate, source_text, context):
    """Keep the original context identity while deriving native-owner inputs."""
    if context is None:
        return None, []
    inputs = validate_context(context, domain, candidate, source_text)
    if KEY not in inputs:
        return context, []
    require(domain == "security_ir", "supplemental interpretations require SecurityIR")
    rows = canonical_interpretations(inputs.pop(KEY))
    return bind_context(domain, candidate, source_text, inputs), rows


def validate_native_bindings(rows, report):
    """Every supplied interpretation must match an active, unchanged view."""
    rows = canonical_interpretations(rows)
    require(not rows or report["domain_id"] == "security_ir",
            "supplemental interpretations require SecurityIR")
    result = {}
    for row in rows:
        identifier = "security_ir/supplemental/" + row["kind"] + "/v2"
        projections = [p for p in report["projections"] if p["projection_id"] == identifier]
        require(len(projections) == 1, "supplemental interpretation has no active native projection")
        document = projections[0].get("payload", {}).get("native_document")
        require(type(document) is dict and digest(document) == row["interpretation"]["native_document_sha256"],
                "supplemental interpretation native document differs")
        result[identifier] = row["interpretation"]
    return result
