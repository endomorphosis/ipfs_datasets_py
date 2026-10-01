"""Optional extended projections around the immutable learned Intent codec."""
from __future__ import annotations

import hashlib
import json
import re

from .projection_contracts import canonical_bytes

SCHEMA = "intent-instruction-extended-roundtrip/v1"
CONTEXT_SCHEMA = "intent-instruction-extended-roundtrip/v2"
MAX_ADVISORY_REPORT_BYTES = 262_144


class ProjectionReportBudgetExceeded(ValueError):
    """Optional family data cannot fit the supervisor's bounded advice report."""


def _base_report(base, *, contextual=False):
    report = json.loads(json.dumps(base, allow_nan=False))
    report["schema"] = CONTEXT_SCHEMA if contextual else SCHEMA
    report["base_report_sha256"] = report.pop("report_sha256")
    report["extended_projections"] = None
    report["extension_status"] = "not_applicable"
    if contextual:
        report["projection_request"] = None
    return report


def _finish(report):
    report["report_sha256"] = hashlib.sha256(canonical_bytes(report)).hexdigest()
    return report


def prepare_extended_intent_instruction(instruction, checkpoint_descriptor=None, *, projection_request=None):
    from .roundtrip import prepare_roundtrip_intent_instruction
    from .extended_projections import project_intent_families
    base = prepare_roundtrip_intent_instruction(instruction, checkpoint_descriptor)
    contextual = projection_request is not None and base["status"] == "semantic_candidate_advice"
    report = _base_report(base, contextual=contextual)
    if base["status"] == "semantic_candidate_advice":
        try:
            options = {}
            if contextual:
                from .projection_request import validate_intent_projection_request
                selected = validate_intent_projection_request(projection_request, instruction=instruction,
                    document=base["candidate_intent_ir"], checkpoint_sha256=base["checkpoint_sha256"])
                report["projection_request"] = selected
                options = {"context": selected["context"], "requested_families": selected["requested_families"]}
            report["extended_projections"] = project_intent_families(base["candidate_intent_ir"], **options)
            report["extension_status"] = "projected_with_explicit_frontiers"
            # Match the consumer's ASCII JSON wire size, including the final
            # fixed-width digest. Escaped Unicode can be larger than canonical
            # UTF-8. An oversized extension must not discard valid base inference.
            sized = {**report, "report_sha256": "0" * 64}
            if len(json.dumps(sized, sort_keys=True, separators=(",", ":"),
                              allow_nan=False).encode()) > MAX_ADVISORY_REPORT_BYTES:
                raise ProjectionReportBudgetExceeded("optional projection report exceeds its byte budget")
        except Exception as exc:
            # Ordinary optional projector failures retain the base candidate;
            # cancellation remains visible and original planning remains available.
            report["extended_projections"] = None
            report["extension_status"] = "fail_open_projection_error"
            report["gaps"].append("extended_projection_error_category:" + type(exc).__name__)
    return _finish(report)


def validate_extended_intent_report(report, *, instruction, checkpoint_descriptor=None):
    if type(report) is not dict or report.get("schema") not in {SCHEMA, CONTEXT_SCHEMA}:
        raise ValueError("extended Intent report required")
    contextual = report["schema"] == CONTEXT_SCHEMA
    if report.get("extension_status") == "fail_open_projection_error":
        # A transient optional failure need not recur to keep the independently
        # replayed base inference. The closed failed envelope carries no added
        # formulas or validation claims that could acquire authority.
        from .roundtrip import prepare_roundtrip_intent_instruction
        base = prepare_roundtrip_intent_instruction(instruction, checkpoint_descriptor)
        if base["status"] != "semantic_candidate_advice":
            raise ValueError("failed extension requires independently replayable base advice")
        gaps = report.get("gaps")
        if (type(gaps) is not list or len(gaps) != len(base["gaps"]) + 1
                or type(gaps[-1]) is not str
                or not re.fullmatch(r"extended_projection_error_category:[A-Za-z_][A-Za-z0-9_]{0,127}", gaps[-1])):
            raise ValueError("closed optional projection failure category required")
        expected = _base_report(base, contextual=contextual)
        if contextual and report.get("projection_request") is not None:
            from .projection_request import validate_intent_projection_request
            expected["projection_request"] = validate_intent_projection_request(report["projection_request"],
                instruction=instruction, document=base["candidate_intent_ir"],
                checkpoint_sha256=base["checkpoint_sha256"])
        expected["extension_status"] = "fail_open_projection_error"
        expected["gaps"].append(gaps[-1])
        if canonical_bytes(report) != canonical_bytes(_finish(expected)):
            raise ValueError("failed extension changed its source-bound base candidate")
        return report
    if contextual and report.get("projection_request") is None:
        raise ValueError("contextual Intent report requires its selected request")
    expected = prepare_extended_intent_instruction(instruction, checkpoint_descriptor,
        projection_request=report.get("projection_request") if contextual else None)
    if canonical_bytes(report) != canonical_bytes(expected):
        raise ValueError("extended Intent advice differs from checkpoint/source/projection replay")
    return report
