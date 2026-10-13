"""Exact span-to-section observations, with source and review obligations open.

A unique declared section citation is a candidate, not a source occurrence.
This bridge never expands short revisions, normalizes legal IDs, selects the
first match, interprets paired formal outputs, or supplies missing context.
Existing SpanCache intake owns typed source-bound graph construction. Primary
graph lookup and independent per-record source mappings remain separate inputs.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import re

from . import legal_span_cache_intake as intake
from ...processors.legal_data.uscode_release_schema import validate_legal_id

SCHEMA = "legal-span-section-observation-bridge/v1"
POLICY_SCHEMA = "legal-span-section-source-mapping-policy/v1"
FLAT_PROFILE = "span_export_fields/v1"
EVIDENCE_PROFILE = "uscode-autoformal-span-evidence/v1"
FLAT_PROFILES = (FLAT_PROFILE, EVIDENCE_PROFILE)
PAIRED_PROFILES = ("uscode-paired-span-census/v1", "uscode-paired-span-census/v2")
PROFILES = [*FLAT_PROFILES, *PAIRED_PROFILES]
MAX_ROWS = 128
_REV = re.compile(r"[0-9a-f]{40}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_MAPPING_KEYS = {"record_sha256", "source_span_id", "source_sha256", "legal_id",
    "primary_revision", "source_revision", "document_revision", "document_view_id",
    "section_entry_cid", "source_package_entry_cid"}
AUTHORITY = dict.fromkeys(("admitted", "formalized", "source_semantics_verified",
    "source_package_content_identity_verified", "primary_source_correspondence_verified", "context_closure_verified", "legal_review_verified",
    "global_consistency_verified", "proof_authority", "training_qualified",
    "complete_section_coverage_verified", "legacy_admission_flags_used"), False)


class SpanSectionBridgeError(ValueError):
    """An independent bridge pin, supported policy, or finite bound differs."""


def _need(ok, message):
    if not ok:
        raise SpanSectionBridgeError(message)


def _wire(value):
    return intake._wire(value)


def _digest(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def _sha(value):
    _need(type(value) is str and _SHA.fullmatch(value), "exact bridge SHA256 required")


def _full_revision(value):
    return type(value) is str and _REV.fullmatch(value) is not None


def _policy(policy):
    _need(type(policy) is dict and set(policy) == {"schema", "identity_profiles", "legal_id_profile",
        "revision_profile", "coordinate_profile", "record_mappings"}, "closed bridge mapping policy required")
    _need(policy["schema"] == POLICY_SCHEMA and policy["identity_profiles"] == PROFILES
        and policy["legal_id_profile"] == "literal_declared_usc_legal_id/v1"
        and policy["revision_profile"] == "exact_full_git_source_revision/v1"
        and policy["coordinate_profile"] == "independently_pinned_legal_view_occurrence/v2",
        "unsupported identity/revision/coordinate policy profile")
    mappings = policy["record_mappings"]
    _need(type(mappings) is list and len(mappings) <= MAX_ROWS, "bounded per-record source mappings required")
    seen = set()
    for mapping in mappings:
        _need(type(mapping) is dict and set(mapping) == _MAPPING_KEYS, "closed per-record source mapping required")
        for key in ("record_sha256", "source_sha256"):
            _sha(mapping[key])
        _need(mapping["record_sha256"] not in seen, "duplicate source mapping record pin")
        seen.add(mapping["record_sha256"])
        for key in ("primary_revision", "source_revision", "document_revision"):
            _need(_full_revision(mapping[key]), "complete literal git revisions required; aliases are unsupported")
        _need(mapping["document_revision"] == mapping["source_revision"], "document/source revision equality required by this profile")
        for key in ("source_span_id", "legal_id", "document_view_id", "section_entry_cid", "source_package_entry_cid"):
            _need(type(mapping[key]) is str and 0 < len(mapping[key].encode()) <= 2048 and mapping[key].strip(),
                  "bounded explicit source mapping identity required")
        _need(validate_legal_id(mapping["legal_id"]) == mapping["legal_id"], "literal legal identity required")
    return deepcopy(policy)


def identity_policy_sha256(policy):
    """Hash the complete versioned independently declared source-mapping policy."""
    return _digest(_policy(policy))


def _identity(row):
    issues = []
    version = row.get("schema_version")
    if version in PAIRED_PROFILES:
        profile, source = version, row.get("source")
        if type(source) is not dict:
            source = {}
            issues.append({"code": "missing_paired_source_object"})
        fields = {"source_span_id": source.get("span_id"), "source_text": source.get("text"),
                  "source_sha256": source.get("text_sha256"), "legal_id": source.get("legal_id"),
                  "declared_revision": source.get("revision")}
        issues.append({"code": "paired_formal_transport_unsupported"})
    elif version is None or version == EVIDENCE_PROFILE:
        profile = FLAT_PROFILE if version is None else EVIDENCE_PROFILE
        fields = {key: row.get(key) for key in ("source_span_id", "source_text", "source_sha256", "legal_id")}
        fields["declared_revision"] = row.get("source_revision")
        for alias, canonical in (("id", "source_span_id"), ("text", "source_text"), ("revision", "source_revision")):
            if alias in row and row[alias] != row.get(canonical):
                issues.append({"code": "conflicting_or_unsupported_identity_alias", "field": alias})
    else:
        return {"profile": "unsupported", "declared_schema_version": version}, [{"code": "unsupported_span_identity_profile"}]
    for key in ("source_span_id", "source_text"):
        if type(fields[key]) is not str or not fields[key].strip():
            issues.append({"code": "missing_exact_" + key})
    text = fields["source_text"]
    if type(text) is not str or fields["source_sha256"] != hashlib.sha256(text.encode()).hexdigest():
        issues.append({"code": "source_text_sha256_mismatch"})
    try:
        _need(type(fields["legal_id"]) is str and validate_legal_id(fields["legal_id"]) == fields["legal_id"],
              "literal legal ID required")
    except (TypeError, ValueError):
        issues.append({"code": "missing_or_unsupported_literal_legal_id"})
    fields["revision_status"] = "full_source_revision_declared" if _full_revision(fields["declared_revision"]) else "unsupported_or_missing_full_source_revision"
    if not _full_revision(fields["declared_revision"]):
        issues.append({"code": "unsupported_or_missing_full_source_revision"})
    return {"profile": profile, **fields}, issues


def reconcile_span_sections(rows, *, cache_identity, expected_row_sha256s, expected_record_sha256s,
        section_index, expected_section_index_sha256, identity_policy, expected_identity_policy_sha256,
        source_bindings, expected_source_bindings_sha256, start_ordinal=0):
    """Preserve every row and independently assess section/source prerequisites.

    ``section_index`` is the guarded public PrimarySectionIndex owner. A pinned
    full per-record mapping is an explicit association, not proof that package
    contents equal the official document. Review/context closure remains open.
    """
    from .legal_primary_section_index import PrimarySectionIndex

    _need(type(section_index) is PrimarySectionIndex, "guarded PrimarySectionIndex owner required")
    _sha(expected_section_index_sha256); _sha(expected_identity_policy_sha256)
    section_index.guard()
    _need(section_index.index_sha256 == expected_section_index_sha256, "independent section index pin differs")
    policy = _policy(identity_policy)
    _need(_digest(policy) == expected_identity_policy_sha256, "independent identity policy pin differs")
    observed = intake.prepare_span_cache_intake(rows, cache_identity=cache_identity,
        expected_row_sha256s=expected_row_sha256s, expected_record_sha256s=expected_record_sha256s,
        source_bindings=source_bindings, expected_source_bindings_sha256=expected_source_bindings_sha256,
        start_ordinal=start_ordinal)
    mappings = {row["record_sha256"]: row for row in policy["record_mappings"]}
    _need(set(mappings) <= set(expected_record_sha256s), "source mapping addresses a foreign record population")
    primary = deepcopy(section_index.primary_identity)
    result_rows = []
    for original in observed["rows"]:
        identity, issues = _identity(original["raw_row"])
        raw_row = original["raw_row"]
        if "repository_id" in raw_row and raw_row["repository_id"] != cache_identity["repository"]:
            issues.append({"code": "cache_repository_identity_mismatch"})
        if identity["profile"] == EVIDENCE_PROFILE:
            if raw_row.get("record_kind") != "span":
                issues.append({"code": "unsupported_evidence_record_kind"})
            if raw_row.get("dataset_id") != primary["repository"]:
                issues.append({"code": "primary_dataset_identity_mismatch"})
        lookup = candidate = None
        if not any(row["code"] == "missing_or_unsupported_literal_legal_id" for row in issues) and identity.get("legal_id") is not None:
            lookup = section_index.lookup_sections(identity["legal_id"])
            _need(lookup["legal_id"] == identity["legal_id"] and lookup["index_sha256"] == expected_section_index_sha256
                  and _wire(lookup["primary_identity"]) == _wire(primary), "guarded section lookup identity differs")
            sections = lookup["sections"]
            _need(type(sections) is list and all(row["legal_id"] == identity["legal_id"] for row in sections), "literal section lookup population differs")
            if len(sections) == 1:
                candidate = deepcopy(sections[0])
                if candidate.get("issues"):
                    issues.append({"code": "candidate_section_has_unresolved_issues"})
            else:
                issues.append({"code": "section_candidate_missing" if not sections else "section_candidate_ambiguous", "count": len(sections)})
            if lookup.get("issues"):
                issues.append({"code": "section_lookup_has_unresolved_issues"})
        mapping = mappings.get(original["record_sha256"])
        if mapping is None:
            issues.append({"code": "missing_independent_per_record_source_mapping"})
        else:
            expected = {"source_span_id": identity.get("source_span_id"), "source_sha256": identity.get("source_sha256"),
                        "legal_id": identity.get("legal_id"), "source_revision": identity.get("declared_revision"),
                        "primary_revision": primary["revision"]}
            if any(mapping[key] != value for key, value in expected.items()) or mapping["source_revision"] != primary["source_revision"]:
                issues.append({"code": "independent_source_mapping_identity_or_revision_mismatch"})
            if candidate is None or mapping["section_entry_cid"] != candidate["entry_cid"]:
                issues.append({"code": "independent_section_entry_binding_mismatch"})
            packages = [] if candidate is None else candidate["source_packages"]
            if sum(package["entry_cid"] == mapping["source_package_entry_cid"] for package in packages) != 1:
                issues.append({"code": "independent_source_package_binding_missing_or_ambiguous"})
            source = original["source_binding"]
            if source is None or source["document_revision"] != mapping["document_revision"] or source["view_id"] != mapping["document_view_id"]:
                issues.append({"code": "independent_exact_document_occurrence_binding_missing_or_mismatched"})
        if original["graph"] is None:
            issues.append({"code": "existing_span_intake_graph_prerequisites_unresolved"})
        graph = deepcopy(original["graph"]) if not issues and identity["profile"] in FLAT_PROFILES else None
        result_rows.append({"row_ordinal": original["row_ordinal"], "raw_row": original["raw_row"],
            "raw_row_sha256": original["raw_row_sha256"], "record_sha256": original["record_sha256"],
            "source_identity": identity, "section_lookup": lookup, "candidate_section": candidate,
            "primary_binding": deepcopy(mapping), "primary_binding_status": "bound_source_mapping_observation" if graph else "unresolved",
            "original_span_intake": original, "graph_request": original["graph_request"], "graph_proposal": graph,
            "obligations": {"section_identity": "unique_declared_candidate_only" if candidate else "unresolved",
                "revision": identity.get("revision_status", "unsupported"),
                "coordinates": "exact_independent_source_occurrence" if graph else "unresolved",
                "source_package_content": "not_verified_by_section_identity_or_mapping",
                "primary_source_correspondence": "open_requires_independent_primary_payload_to_official_source_correspondence_evidence",
                "context": "open_requires_source_bound_context_packet_and_dependency_inventory",
                "review": "not_assessed_requires_legal_graph_review",
                "legal_graph_review_api": "ipfs_datasets_py.logic.autoformal.legal_graph_review.build_review_subject"},
            "issues": issues, "disposition": "source_bound_unreviewed_graph_proposal" if graph else "unresolved",
            "authority": dict(AUTHORITY)})
    section_index.guard()
    _need(section_index.index_sha256 == expected_section_index_sha256 and _wire(section_index.primary_identity) == _wire(primary),
          "section index moved during bridge batch")
    report = {"schema": SCHEMA, "cache_identity": observed["cache_identity"], "start_ordinal": start_ordinal,
        "row_count": len(result_rows), "rows": result_rows, "primary_identity": primary,
        "section_index_sha256": expected_section_index_sha256, "identity_policy": policy,
        "identity_policy_sha256": expected_identity_policy_sha256, "span_intake_sha256": observed["intake_sha256"],
        "source_bindings_sha256": observed["source_bindings_sha256"],
        "expected_row_sha256s": observed["expected_row_sha256s"], "expected_record_sha256s": observed["expected_record_sha256s"],
        "disposition_counts": dict(Counter(row["disposition"] for row in result_rows)),
        "population_complete": True, "coverage_scope": "exact_independently_pinned_supplied_span_rows_only",
        "authority": dict(AUTHORITY)}
    report["bridge_sha256"] = _digest(report)
    return deepcopy(report)


def validate_span_section_bridge(report, rows, **trusted_inputs):
    expected = reconcile_span_sections(rows, **trusted_inputs)
    _need(_wire(report) == _wire(expected), "span section bridge differs from independent complete replay")
    return expected


__all__ = ["SpanSectionBridgeError", "identity_policy_sha256", "reconcile_span_sections", "validate_span_section_bridge"]
