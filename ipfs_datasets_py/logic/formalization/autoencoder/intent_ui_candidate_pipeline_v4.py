"""Additive post-generation routing for explicit compound UI logic candidates.

All prior routes are delegated in one v3 batch. The compound route preserves
source and prediction, requires exact agreement, and prepares inert family
artifacts only. It does not add a runtime target kind, train, widen context or
turn a raw output rejected by the native decoder into an accepted prediction.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from . import intent_ui_candidate_pipeline_v3 as previous

SCHEMA = "intent-ui-candidate-pipeline/v4"
FALSE = {**previous.FALSE, "training_executed": False, "strict_training_allowed": False,
         "eligible_for_training": False}
_IMPORTED_SHA = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
require, raw = previous.previous._require, previous.previous._raw


def _guard():
    previous._guard()
    require(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == _IMPORTED_SHA,
            "candidate pipeline v4 changed after import")


def _compound(domain, row, text):
    if domain != "ui_ux_ir":
        return False
    candidate = row.get("candidate_ir")
    candidate = candidate if candidate is not None else row.get("raw_candidate_ir")
    if type(candidate) is dict and candidate.get("kind") == "ui_declared_logic":
        return True
    # This routing parse runs only after inference. It grants no source agreement;
    # the new owner must still validate the entire original source and candidate.
    if not text.lstrip().startswith("{"):
        return False
    from . import ui_declared_source_fidelity as source_json
    try:
        value = json.loads(text, object_pairs_hook=source_json._unique, parse_constant=source_json._constant)
    except (ValueError, TypeError, RecursionError):
        return False
    return type(value) is dict and value.get("schema") == "ui-declared-logic-source/v1"


def audit_candidates(report, source_rows, *, requested_families=None):
    _guard()
    sources = previous._validate(report, source_rows)
    for record in [report, *report["rows"]]:
        require(all(record.get(flag, False) is False for flag in FALSE),
                "inference cannot carry training or proof authority")
    result = deepcopy(report)
    routes = {row["id"]: _compound(report["domain_id"], row, sources[row["id"]]) for row in result["rows"]}
    old_rows = [row for row in result["rows"] if not routes[row["id"]]]
    old_results = {}
    if old_rows:
        delegated = {key: value for key, value in report.items() if key != "rows"}
        delegated["rows"] = old_rows
        old = previous.audit_candidates(delegated,
            [{"id": row["id"], "source_text": sources[row["id"]]} for row in old_rows],
            requested_families=requested_families)
        old_results = {row["id"]: row for row in old["rows"]}
    dispositions = {}
    for row in result["rows"]:
        identity = row["id"]
        candidate = row.get("candidate_ir")
        candidate_before = raw(candidate)
        raw_before = raw(row.get("raw_candidate_ir"))
        if not routes[identity]:
            delegated = old_results[identity]
            row.clear()
            row.update(delegated)
        else:
            from . import ui_declared_logic_source as owner
            audited = candidate if candidate is not None else row.get("raw_candidate_ir")
            source_audit = owner.audit_candidate(sources[identity], audited)
            status = source_audit["status"]
            if status == "source_agreement" and candidate is None:
                status = "native_generation_rejected"
            projection, ready = None, False
            if status == "source_agreement":
                try:
                    prepared = owner.prepare_family_targets(sources[identity], candidate,
                                                            requested_families=requested_families)
                    ready = prepared["audit"]["status"] == "projected_candidate"
                    projection = {"status": prepared["audit"]["status"], "report": prepared["report"],
                                  "audit": prepared["audit"], **FALSE}
                    if not ready:
                        status = "projection_" + prepared["audit"]["status"]
                except (ValueError, TypeError, KeyError, RecursionError) as error:
                    projection = {"status": "invalid_or_missing_context", "reason": str(error)[:1024],
                                  "candidate": deepcopy(candidate), **FALSE}
                    status = "projection_invalid_or_missing_context"
            row["candidate_audit"] = {"status": status, "source_fidelity": source_audit,
                "family_projection": projection, "projection_executed": projection is not None,
                "source_agreement_required": True, "native_candidate_available": candidate is not None,
                "raw_output_audited_after_native_rejection": candidate is None and "raw_candidate_ir" in row,
                "pipeline_route": "explicit_compound_UI_logic", "current_learned_decoder_compatible": False,
                "family_preparation_is_training_eligibility": False,
                "neural_rich_document_generation_verified": False, **FALSE}
            row.update(eligible_for_family_preparation=ready, candidate_rewritten=False,
                current_learned_decoder_compatible=False, training_token_limit_changed=False,
                continue_planning=True, **FALSE)
            row["status"] = "unqualified_audited_candidate" if ready else "blocked_candidate_" + status
        require(raw(row.get("candidate_ir")) == candidate_before and raw(row.get("raw_candidate_ir")) == raw_before,
                "pipeline changed original or rejected raw candidate")
        status = row["candidate_audit"]["status"]
        dispositions[status] = dispositions.get(status, 0) + 1
    result.update(candidate_audit_schema=SCHEMA, source_contracts_checked=True,
        candidate_audit_dispositions=dispositions, candidate_rewritten=False,
        inference_finished_before_source_audit=True, family_preparation_requires_bounded_source_agreement=True,
        family_preparation_is_training_eligibility=False, training_token_limit_changed=False,
        neural_rich_document_generation_verified=False, candidate_audit_producer_sha256=_IMPORTED_SHA, **FALSE)
    _guard()
    return result


def infer_and_audit(runtime, rows, *, requested_families=None, **inference_options):
    """Call an unchanged runtime first, then audit its unmodified output."""
    _guard()
    require(type(rows) is list and 1 <= len(rows) <= 4096 and all(type(row) is dict
        and set(row) == {"id", "source_text", "embedding"} for row in rows), "closed target-free inference rows required")
    sources = [{key: row[key] for key in ("id", "source_text")} for row in rows]
    previous.previous._source_rows(sources)
    generated = runtime.infer(deepcopy(rows), **inference_options)
    return audit_candidates(generated, sources, requested_families=requested_families)


__all__ = ["SCHEMA", "audit_candidates", "infer_and_audit"]
