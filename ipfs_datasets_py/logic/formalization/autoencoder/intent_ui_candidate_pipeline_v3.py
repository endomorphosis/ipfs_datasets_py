"""Post-generation routing for compact and explicitly supplied full documents.

The old compact Intent/UI paths remain unchanged. New routes require complete
source agreement and preserve the original candidate. No parser output enters
inference, no context or token limit grows, and family targets confer no proof.
"""
from copy import deepcopy
import hashlib
from pathlib import Path

from . import intent_ui_candidate_pipeline_v2 as previous

SCHEMA = "intent-ui-candidate-pipeline/v3"
FALSE = previous.FALSE
_IMPORTED_SHA = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _guard():
    previous._guard()
    previous._require(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == _IMPORTED_SHA,
                      "candidate pipeline v3 changed after import")


def _validate(report, source_rows):
    sources = previous._source_rows(source_rows)
    previous._require(type(report) is dict and report.get("domain_id") in {"intent_ir", "ui_ux_ir"},
                      "Intent or UI inference report required")
    previous._require(type(report.get("dimension")) is int and report["dimension"] == 384,
                      "genuine 384-dimensional report required")
    rows = report.get("rows")
    previous._require(type(rows) is list and len(rows) == len(sources), "source/output count mismatch")
    previous._require(len(previous._raw(report)) <= 64 * 1024 * 1024, "bounded inference report required")
    for record in [report, *rows]:
        previous._require(type(record) is dict, "object inference row required")
        previous._require(all(record.get(key, False) is False for key in FALSE), "inference cannot carry proof authority")
    identities = [row.get("id") for row in rows]
    previous._require(all(type(value) is str for value in identities) and len(set(identities)) == len(identities)
                      and set(identities) == set(sources), "source/output identity mismatch")
    for row in rows:
        previous._require(row.get("target_access") is False and row.get("teacher_forcing") is False,
                          "target-free generation evidence required")
        previous._require(row.get("source_sha256") == hashlib.sha256(sources[row["id"]].encode()).hexdigest(),
                          "source/output hash mismatch")
    return sources


def _full_route(report, row, text):
    candidate = row.get("candidate_ir")
    audited = candidate if candidate is not None else row.get("raw_candidate_ir")
    document = type(audited) is dict and audited.get("kind") == "document"
    if report["domain_id"] == "intent_ir":
        return "explicit_intent_document" if document else None
    # The discriminator belongs to original source text, not caller expectations.
    # Unknown/malformed JSON schemas are rejected by the closed source parser.
    return "explicit_ui_document" if document or text.lstrip().startswith("{") else None


def audit_candidates(report, source_rows, *, requested_families=None):
    _guard()
    sources = _validate(report, source_rows)
    result = deepcopy(report)
    # Delegate compact rows once as a batch. This also avoids repeated copying
    # of a possibly large shared report header when many rows use the old path.
    compact_rows = [row for row in result["rows"] if _full_route(report, row, sources[row["id"]]) is None]
    compact_outputs = {}
    if compact_rows:
        compact = {key: value for key, value in report.items() if key != "rows"}
        compact["rows"] = compact_rows
        old = previous.audit_candidates(compact,
            [{"id": row["id"], "source_text": sources[row["id"]]} for row in compact_rows],
            requested_families=requested_families)
        compact_outputs = {row["id"]: row for row in old["rows"]}
    dispositions = {}
    for row in result["rows"]:
        text = sources[row["id"]]
        candidate = row.get("candidate_ir")
        before = previous._raw(candidate)
        route = _full_route(report, row, text)
        if route is None:
            old_row = compact_outputs[row["id"]]
            row.clear()
            row.update(old_row)
            row["candidate_audit"]["pipeline_route"] = "unchanged_compact_v2"
            compact_projection = row["candidate_audit"]["family_projection"]
            if (report["domain_id"] == "ui_ux_ir" and type(compact_projection) is dict
                    and type(compact_projection.get("report")) is dict):
                from . import ui_declared_source_fidelity as ui
                row["candidate_audit"]["missing_context_requirements"] = ui.coverage_requirements(compact_projection["report"])
        else:
            if route == "explicit_ui_document":
                from . import ui_declared_source_fidelity as owner
            else:
                from . import intent_source_coverage_384 as owner
            audited = candidate if candidate is not None else row.get("raw_candidate_ir")
            source_audit = owner.audit_candidate(text, audited)
            status = source_audit["status"]
            if status == "source_agreement" and candidate is None:
                status = "native_generation_rejected"
            projection = None
            ready = False
            requirements = []
            if status == "source_agreement":
                try:
                    prepared = owner.prepare_family_targets(text, candidate, requested_families=requested_families)
                    projection_status = prepared["audit"]["status"] if route == "explicit_ui_document" else "projected_candidate"
                    projection = {"status": projection_status, "report": prepared["report"],
                                  "audit": prepared["audit"], **FALSE}
                    ready = projection_status == "projected_candidate"
                    if not ready:
                        status = "projection_" + projection_status
                    requirements = prepared.get("missing_context_requirements", [])
                except (ValueError, TypeError, KeyError, RecursionError) as error:
                    projection = {"status": "invalid_or_missing_context", "reason": str(error)[:1024],
                                  "candidate": deepcopy(candidate), **FALSE}
                    status = "projection_invalid_or_missing_context"
            row["candidate_audit"] = {"status": status, "source_fidelity": source_audit,
                "family_projection": projection, "projection_executed": projection is not None,
                "source_agreement_required": True, "native_candidate_available": candidate is not None,
                "raw_output_audited_after_native_rejection": candidate is None and "raw_candidate_ir" in row,
                "pipeline_route": route, "missing_context_requirements": requirements,
                "neural_rich_document_generation_verified": False, **FALSE}
            row.update(eligible_for_family_preparation=ready, candidate_rewritten=False,
                       continue_planning=True, **FALSE)
            row["status"] = "unqualified_audited_candidate" if ready else "blocked_candidate_" + status
        previous._require(previous._raw(candidate) == before and previous._raw(row.get("candidate_ir")) == before,
                          "audit rewrote generated candidate")
        status = row["candidate_audit"]["status"]
        dispositions[status] = dispositions.get(status, 0) + 1
    result.update(candidate_audit_schema=SCHEMA, source_contracts_checked=True,
        candidate_audit_dispositions=dispositions, candidate_rewritten=False,
        inference_finished_before_source_audit=True,
        family_preparation_requires_bounded_source_agreement=True,
        training_token_limit_changed=False, neural_rich_document_generation_verified=False,
        candidate_audit_producer_sha256=_IMPORTED_SHA, **FALSE)
    _guard()
    return result


def infer_and_audit(runtime, rows, *, requested_families=None, **inference_options):
    """Finish target-free inference before inspecting any source declaration."""
    _guard()
    previous._require(type(rows) is list and 1 <= len(rows) <= 4096 and all(type(row) is dict
        and set(row) == {"id", "source_text", "embedding"} for row in rows), "closed target-free inference rows required")
    sources = [{key: row[key] for key in ("id", "source_text")} for row in rows]
    previous._source_rows(sources)
    generated = runtime.infer(deepcopy(rows), **inference_options)
    return audit_candidates(generated, sources, requested_families=requested_families)


__all__ = ["SCHEMA", "audit_candidates", "infer_and_audit"]
