"""Versioned local declaration chains using fixed regenerated pagewise parents.

This additive owner never injects arbitrary row inventories or changes the old
public v1 reconciliation profile. Verified physical parent bytes still do not
attest a historical invocation, original span occurrence or governing meaning.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import re

from . import legal_producer_lineage as legacy

SCHEMA = "legal-producer-page-lineage-observations/v2"
PARENT_PROFILE = "pagewise_v2"
INPUT_SCHEMA = "legal-producer-qualified-page-parent-population/v1"
MAX_PARENT_INPUT_BYTES = 32 * 1024 * 1024
_FIELDS = {"descriptor_sha256", "preflight_report", "expected_preflight_sha256",
           "row_report", "expected_row_report_sha256"}
_SHA = re.compile(r"[0-9a-f]{64}\Z")


class ProducerPageLineageError(ValueError):
    """An independently expected complete page-parent population differs."""


def _need(ok, message):
    if not ok:
        raise ProducerPageLineageError(message)


def _wire(value, maximum=legacy.MAX_REPORT_BYTES):
    return legacy._wire(value, maximum)


def _sha(value):
    _need(type(value) is str and _SHA.fullmatch(value), "independent lowercase page-lineage SHA256 required")


def _inputs(values):
    _need(type(values) is list and len(values) <= legacy.MAX_PARENT_FILES, "bounded complete page-parent population required")
    # Enforce aggregate bytes before retaining a second nested population.
    raw = _wire(values, MAX_PARENT_INPUT_BYTES)
    seen = set()
    for value in values:
        _need(type(value) is dict and set(value) == _FIELDS, "closed qualified page-parent input required")
        for key in ("descriptor_sha256", "expected_preflight_sha256", "expected_row_report_sha256"):
            _sha(value[key])
        _need(value["descriptor_sha256"] not in seen, "duplicate page-parent descriptor identity")
        seen.add(value["descriptor_sha256"])
        for key in ("preflight_report", "row_report"):
            _need(type(value[key]) is dict, "complete pinned page-parent report object required")
    return hashlib.sha256(raw).hexdigest()


def parent_page_inputs_sha256(parent_page_inputs):
    """Hash every closed input including the FULL reports and internal seals."""
    return _inputs(parent_page_inputs)


def producer_page_lineage_report_sha256(report):
    """Hash the entire v2 report, including page_lineage_sha256."""
    return hashlib.sha256(_wire(report)).hexdigest()


def reconcile_producer_page_lineage(provenance_reports, *, expected_provenance_report_sha256s,
        expected_record_sha256s, witness_manifest, expected_witness_manifest_sha256,
        parent_page_inputs, expected_parent_page_inputs_sha256):
    """Regenerate complete declaration chains through the fixed pagewise owner.

    The common internal owner selects its fixed page validator from this closed
    profile; callers cannot supply a loader or select easier columns/records.
    Independent manifest/request hashes remain the original custody inputs.
    """
    _sha(expected_parent_page_inputs_sha256)
    actual = _inputs(parent_page_inputs)
    _need(actual == expected_parent_page_inputs_sha256, "independent complete page-parent population pin differs")
    inputs = deepcopy(parent_page_inputs)
    result = legacy._reconcile_producer_lineage(provenance_reports,
        expected_provenance_report_sha256s=expected_provenance_report_sha256s,
        expected_record_sha256s=expected_record_sha256s,
        witness_manifest=witness_manifest,
        expected_witness_manifest_sha256=expected_witness_manifest_sha256,
        parent_profile=PARENT_PROFILE, parent_page_inputs=inputs,
        expected_parent_page_inputs_sha256=expected_parent_page_inputs_sha256)
    _need(result.get("schema") == legacy.SCHEMA and "lineage_sha256" in result,
          "fixed common lineage result profile differs")
    _need(type(result.get("authority")) is dict and all(value is False for value in result["authority"].values())
          and type(result.get("rows")) is list
          and all(type(row.get("authority")) is dict and all(value is False for value in row["authority"].values()) for row in result["rows"]),
          "page lineage cannot upgrade semantic or execution authority")
    result = deepcopy(result)
    result.pop("lineage_sha256")
    result["schema"] = SCHEMA
    result["parent_profile"] = PARENT_PROFILE
    result["parent_page_input_population"] = {"schema": INPUT_SCHEMA,
        "expected_parent_page_inputs_sha256": expected_parent_page_inputs_sha256,
        "inputs": inputs, "qualification_scope": "fixed_owner_regenerated_complete_requested_physical_parent_rows_only"}
    result["historical_v1_report_reinterpreted"] = False
    result["page_lineage_sha256"] = hashlib.sha256(_wire(result)).hexdigest()
    return result


def validate_producer_page_lineage(report, provenance_reports, *, expected_report_sha256, **trusted_inputs):
    _sha(expected_report_sha256)
    _need(producer_page_lineage_report_sha256(report) == expected_report_sha256,
          "independent full v2 page-lineage report pin differs")
    expected = reconcile_producer_page_lineage(provenance_reports, **trusted_inputs)
    _need(_wire(report) == _wire(expected), "v2 page-lineage report differs from fixed full independent regeneration")
    return {"valid": True, "row_count": expected["row_count"], "parent_profile": PARENT_PROFILE,
        "legal_semantic_acceptance": False, "historical_invocation_verified": False}


__all__ = ["ProducerPageLineageError", "parent_page_inputs_sha256", "producer_page_lineage_report_sha256",
           "reconcile_producer_page_lineage", "validate_producer_page_lineage"]
