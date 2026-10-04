"""Require bounded source agreement before Intent/UI family preparation.

This additive API leaves source-pinned runtimes/checkpoints unchanged. Candidate
generation finishes before a parser or projection owner sees the source. Neither
agreement with a bounded grammar nor a projected artifact grants qualification.
UI declarations use v3 graph projections only after bounded source agreement.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

SCHEMA = "intent-ui-candidate-pipeline/v2"
FALSE = dict(admitted=False, qualified=False, formalized=False, proof_authority=False,
    source_semantics_verified=False, roundtrip_ok=False, execution_authority=False,
    completion_authority=False, claim_proved=False, production_promotion_performed=False,
    lake_executed=False)
_IMPORTED_SHA = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _require(value, reason):
    if not value:
        raise ValueError(reason)


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _guard():
    _require(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == _IMPORTED_SHA,
             "candidate pipeline changed after import")


def _source_rows(rows):
    _require(type(rows) is list and 1 <= len(rows) <= 4096, "bounded nonempty source rows required")
    sources = {}
    for row in rows:
        _require(type(row) is dict and set(row) == {"id", "source_text"}, "closed source audit row required")
        identity, text = row["id"], row["source_text"]
        _require(type(identity) is str and 0 < len(identity) <= 256 and identity not in sources,
                 "bounded unique source identity required")
        _require(type(text) is str and text.strip() and len(text.encode()) <= 65536, "bounded source text required")
        sources[identity] = text
    return sources


def audit_candidates(report, source_rows, *, requested_families=None):
    """Preserve predictions and attach post-generation diagnostics, never repair.

Disagreement or unsupported source syntax blocks family preparation in both
domains. UI source agreement is limited to its explicit component grammar.
An invalid row remains in the denominator and does not suppress valid siblings.
"""
    _guard()
    from . import intent_candidate_fidelity as intent
    from . import intent_source_contract_384 as intent_projection
    from . import ui_source_contract_384_v3 as ui
    from . import ui_candidate_fidelity as ui_fidelity

    sources = _source_rows(source_rows)
    _require(type(report) is dict and report.get("domain_id") in {"intent_ir", "ui_ux_ir"},
             "Intent or UI inference report required")
    _require(report.get("dimension") == 384 and type(report.get("dimension")) is int,
             "genuine 384-dimensional report required")
    rows = report.get("rows")
    _require(type(rows) is list and len(rows) == len(sources), "source/output count mismatch")
    _require(len(_raw(report)) <= 64 * 1024 * 1024, "bounded inference report required")
    for record in [report, *rows]:
        _require(type(record) is dict, "object inference row required")
        _require(all(record.get(key, False) is False for key in FALSE), "inference cannot carry proof authority")
    identities = [row.get("id") for row in rows]
    _require(all(type(value) is str for value in identities) and len(set(identities)) == len(identities)
             and set(identities) == set(sources), "source/output identity mismatch")
    for row in rows:
        _require(row.get("target_access") is False and row.get("teacher_forcing") is False,
                 "target-free generation evidence required")
        _require(row.get("source_sha256") == hashlib.sha256(sources[row["id"]].encode()).hexdigest(),
                 "source/output hash mismatch")
    result = deepcopy(report)
    dispositions = {}
    for row in result["rows"]:
        text = sources[row["id"]]
        candidate = row.get("candidate_ir")
        before = _raw(candidate)
        audit_candidate = candidate if candidate is not None else row.get("raw_candidate_ir")
        if report["domain_id"] == "intent_ir":
            source_audit = intent.audit_intent_candidate(text, audit_candidate)
            status = source_audit["status"]
            if status == "source_agreement" and candidate is None:
                status = "native_generation_rejected"
            projection = None
            ready = False
            if status == "source_agreement":
                projection = intent_projection.qualify_source_candidate(text, candidate,
                    requested_families=requested_families)
                ready = projection["status"] == "projected_candidate"
                if not ready:
                    status = "projection_" + projection["status"]
            checked = {"status": status, "source_fidelity": source_audit,
                "family_projection": projection, "projection_executed": projection is not None,
                "source_agreement_required": True,
                "native_candidate_available": candidate is not None,
                "raw_output_audited_after_native_rejection": candidate is None and "raw_candidate_ir" in row, **FALSE}
            row["eligible_for_family_preparation"] = ready
        else:
            source_audit = ui_fidelity.audit_ui_candidate(text, audit_candidate)
            status = source_audit["status"]
            if status == "source_agreement" and candidate is None:
                status = "native_generation_rejected"
            projection = None
            ready = False
            if status == "source_agreement":
                projection = ui.qualify_source_candidate(text, candidate,
                    requested_families=requested_families)
                ready = projection["status"] == "projected_candidate"
                if not ready:
                    status = "projection_" + projection["status"]
            checked = {"status": status, "source_fidelity": source_audit,
                "family_projection": projection, "projection_executed": projection is not None,
                "source_agreement_required": True,
                "native_candidate_available": candidate is not None,
                "raw_output_audited_after_native_rejection": candidate is None and "raw_candidate_ir" in row, **FALSE}
            row["eligible_for_family_preparation"] = ready
        _require(_raw(candidate) == before, "audit rewrote generated candidate")
        dispositions[status] = dispositions.get(status, 0) + 1
        row.update(candidate_audit=checked, candidate_rewritten=False, continue_planning=True, **FALSE)
        row["status"] = "unqualified_audited_candidate" if ready else "blocked_candidate_" + status
    result.update(candidate_audit_schema=SCHEMA, source_contracts_checked=True,
        candidate_audit_dispositions=dispositions, candidate_rewritten=False,
        inference_finished_before_source_audit=True,
        family_preparation_requires_bounded_source_agreement=True,
        candidate_audit_producer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), **FALSE)
    _guard()
    return result


def infer_and_audit(runtime, rows, *, requested_families=None, **inference_options):
    """Use a loaded 384D runtime; no targets or parser outputs enter inference."""
    _guard()
    _require(type(rows) is list and 1 <= len(rows) <= 4096 and all(type(row) is dict
        and set(row) == {"id", "source_text", "embedding"} for row in rows), "closed target-free inference rows required")
    sources = [{key: row[key] for key in ("id", "source_text")} for row in rows]
    _source_rows(sources)
    # Copy protects caller data from inference-only ablations that rotate inputs.
    generated = runtime.infer(deepcopy(rows), **inference_options)
    return audit_candidates(generated, sources, requested_families=requested_families)


__all__ = ["SCHEMA", "audit_candidates", "infer_and_audit"]
