"""Bounded, dependency-free preparation audit for a future GTE transfer corpus.

This module does not load an encoder, validate native IRs, or establish a
producer's authenticity. Hashes bind declared JSON content only. The report
contains bindings and counts, never source text, targets, or vector payloads.
Established split and evaluation-role declarations are never rewritten.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import math
import unicodedata


SCHEMA = "gte-transfer-corpus-audit/v1"
DOMAINS = ("legal_ir", "intent_ir", "security_ir", "ui_ux_ir")
SPLITS = ("train", "validation", "test", "canary")
TARGET_ORIGINS = (
    "authored", "compiler_weak", "teacher_prediction",
    "independently_checked", "unlabeled",
)
ROW_FIELDS = frozenset((
    "id", "domain_id", "document_id", "group_id", "split", "source_text",
    "embedding", "reference_target", "target_origin", "source_language",
    "evaluation_role",
))
UNIT_NORM_TOLERANCE = 1e-4


def _json_value(value, ancestors=None, depth=0):
    """Accept finite JSON values; reject cycles, coercions and excessive depth."""
    if depth > 128:
        return False
    if value is None or isinstance(value, bool):
        return True
    if isinstance(value, str):
        try:
            value.encode("utf-8")
            return True
        except UnicodeError:
            return False
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if not isinstance(value, (dict, list)):
        return False
    ancestors = set() if ancestors is None else ancestors
    if id(value) in ancestors:
        return False
    ancestors.add(id(value))
    try:
        if isinstance(value, dict):
            return all(isinstance(key, str) and _json_value(key)
                       and _json_value(item, ancestors, depth + 1)
                       for key, item in value.items())
        return all(_json_value(item, ancestors, depth + 1) for item in value)
    finally:
        ancestors.remove(id(value))


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _json_digest(value):
    if not _json_value(value):
        return None
    try:
        return _digest(value)
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        return None


def _text(value):
    return isinstance(value, str) and bool(value.strip()) and _json_value(value)


def _source_digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _vector(value, dimension):
    if value is None:
        return None, None
    if not isinstance(value, list):
        return None, "embedding_not_array"
    if len(value) != dimension:
        return None, "embedding_wrong_width"
    result = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            return None, "embedding_not_finite_numeric"
        try:
            number = float(item)
        except (ValueError, OverflowError):
            return None, "embedding_not_finite_numeric"
        if not math.isfinite(number):
            return None, "embedding_not_finite_numeric"
        result.append(0.0 if number == 0 else number)
    return result, None


def _numeric_vector_digest(value):
    """Bind exact numeric values without rounding large integers through float."""
    ratios = [item.as_integer_ratio() if isinstance(item, float) else (item, 1)
              for item in value]
    return _digest(ratios)


def _inspect(row, dimension, profile_sha256):
    data = row if isinstance(row, dict) else {}
    reasons = set()
    if not isinstance(row, dict):
        reasons.add("row_not_object")
    else:
        reasons.update("missing_field:" + field for field in ROW_FIELDS - data.keys())
        if any(not isinstance(field, str) for field in data):
            reasons.add("row_key_not_string")
        reasons.update("unknown_field:" + field for field in data.keys() - ROW_FIELDS
                       if isinstance(field, str))
    row_sha256 = _json_digest(row)
    if row_sha256 is None:
        reasons.add("row_not_finite_json")
    for field in ("id", "document_id", "group_id", "source_language", "source_text"):
        if not _text(data.get(field)):
            reasons.add("invalid_field:" + field)
    for field, allowed in (("domain_id", DOMAINS), ("split", SPLITS),
                           ("target_origin", TARGET_ORIGINS),
                           ("evaluation_role", ("development", "sealed"))):
        if not isinstance(data.get(field), str) or data.get(field) not in allowed:
            reasons.add("invalid_field:" + field)
    split = data.get("split") if data.get("split") in SPLITS else None
    role = data.get("evaluation_role")
    if split in ("train", "validation") and role == "sealed":
        reasons.add("sealed_fitting_or_selection_split")
    target = data.get("reference_target")
    origin = data.get("target_origin")
    target_sha256 = None if target is None else _json_digest(target)
    if target is not None and target_sha256 is None:
        reasons.add("reference_target_not_finite_json")
    if (target is None) != (origin == "unlabeled"):
        reasons.add("target_origin_label_mismatch")
    vector, vector_error = _vector(data.get("embedding"), dimension)
    if vector_error:
        reasons.add(vector_error)
    source = data.get("source_text")
    source_sha256 = _source_digest(source) if _text(source) else None
    normalized_sha256 = None
    if source_sha256:
        normalized = " ".join(unicodedata.normalize("NFKC", source).casefold().split())
        normalized_sha256 = _source_digest(normalized)
    domain = data.get("domain_id") if data.get("domain_id") in DOMAINS else None
    vector_sha256 = _numeric_vector_digest(data["embedding"]) if vector is not None else None
    binding = {
        "id": data.get("id") if _text(data.get("id")) else None,
        "domain_id": domain,
        "document_id": data.get("document_id") if _text(data.get("document_id")) else None,
        "group_id": data.get("group_id") if _text(data.get("group_id")) else None,
        "split": split,
        "evaluation_role": role if role in ("development", "sealed") else None,
        "source_language": data.get("source_language") if _text(data.get("source_language")) else None,
        "target_origin": origin if origin in TARGET_ORIGINS else None,
        "row_sha256": row_sha256,
        "source_sha256": source_sha256,
        "normalized_source_sha256": normalized_sha256,
        "numeric_vector_sha256": vector_sha256,
        "reference_target_sha256": target_sha256,
        "declared_profile_sha256": profile_sha256,
        "has_embedding": vector is not None,
        "has_reference_target": target_sha256 is not None and origin not in ("teacher_prediction", "unlabeled"),
    }
    norm = math.hypot(*vector) if vector is not None else None
    return {"binding": binding, "reasons": reasons,
            "norm": norm, "identities": [], "dedupe_identities": []}


class _Components:
    def __init__(self, count):
        self.parent = list(range(count))

    def find(self, index):
        while index != self.parent[index]:
            self.parent[index] = self.parent[self.parent[index]]
            index = self.parent[index]
        return index

    def join(self, left, right):
        left, right = self.find(left), self.find(right)
        if left != right:
            self.parent[max(left, right)] = min(left, right)


def audit_transfer_rows(rows, *, dimension=384, vector_space_id, max_rows=100000):
    """Audit closed canonical rows without exporting supervision or changing splits.

    ``vector_space_id`` and ``dimension`` are declarations, not verified producer
    receipts. Sources are grouped globally using exact and NFKC/casefold/space
    hashes. Numeric vector identity also spans domains; document and group labels
    are scoped to a domain. Every member of a connected cross-split or conflicting
    reference component is quarantined. Same-domain exact/vector duplicates have
    one deterministic representative; normalized-text matches only group rows.

    Invalid rows are reported as quarantined. Invalid audit parameters, an invalid
    iterable, or more than ``max_rows`` records raise ``ValueError``. Missing
    embeddings and unlabeled targets are allowed but ineligible for supervised
    use. Teacher predictions are counted separately from reference supervision.
    Test/canary rows, including exposed development rows, never qualify fitting or
    selection. Explicit sealed declarations are retained and never inferred.
    """
    if isinstance(dimension, bool) or not isinstance(dimension, int) or not 1 <= dimension <= 65536:
        raise ValueError("dimension must be an integer between 1 and 65536")
    if (not _text(vector_space_id) or vector_space_id != vector_space_id.strip()
            or len(vector_space_id) > 512
            or any(unicodedata.category(char).startswith("C") for char in vector_space_id)):
        raise ValueError("vector_space_id must be a nonempty, trimmed declared profile identity")
    if isinstance(max_rows, bool) or not isinstance(max_rows, int) or max_rows < 1:
        raise ValueError("max_rows must be a positive integer")
    if isinstance(rows, (str, bytes, dict)):
        raise ValueError("rows must be an iterable of canonical row objects")
    try:
        iterator = iter(rows)
    except TypeError as error:
        raise ValueError("rows must be an iterable of canonical row objects") from error
    profile = {"dimension": dimension, "vector_space_id": vector_space_id,
               "identity_status": "declared_not_producer_verified"}
    profile_sha256 = _digest(profile)
    inspected = []
    for row in iterator:
        if len(inspected) == max_rows:
            raise ValueError("transfer corpus exceeds max_rows; audit was not completed")
        inspected.append(_inspect(row, dimension, profile_sha256))

    components = _Components(len(inspected))
    dedupes = _Components(len(inspected))
    identities = {}
    duplicate_identity = {}
    ids = defaultdict(list)
    reference_groups = defaultdict(lambda: defaultdict(list))
    for index, record in enumerate(inspected):
        binding = record["binding"]
        domain = binding["domain_id"]
        if binding["id"] is not None:
            ids[binding["id"]].append(index)
        scoped = []
        if domain:
            for field in ("document_id", "group_id"):
                if binding[field] is not None:
                    scoped.append((field, domain, binding[field]))
        global_keys = [(field, binding[field]) for field in (
            "source_sha256", "normalized_source_sha256", "numeric_vector_sha256")
            if binding[field] is not None]
        record["identities"] = scoped + global_keys
        for key in record["identities"]:
            if key in identities:
                components.join(index, identities[key])
            else:
                identities[key] = index
        if domain:
            for field in ("source_sha256", "numeric_vector_sha256"):
                if binding[field] is None:
                    continue
                key = (domain, field, binding[field])
                record["dedupe_identities"].append(key)
                if key in duplicate_identity:
                    dedupes.join(index, duplicate_identity[key])
                else:
                    duplicate_identity[key] = index
                if binding["has_reference_target"]:
                    reference_groups[key][binding["reference_target_sha256"]].append(index)
    duplicate_ids = sorted(row_id for row_id, members in ids.items() if len(members) > 1)
    for row_id in duplicate_ids:
        for index in ids[row_id]:
            inspected[index]["reasons"].add("duplicate_id")
            components.join(ids[row_id][0], index)

    members_by_component = defaultdict(list)
    for index in range(len(inspected)):
        members_by_component[components.find(index)].append(index)
    component_reasons = defaultdict(set)
    for root, members in members_by_component.items():
        splits = {inspected[index]["binding"]["split"] for index in members} - {None}
        if len(splits) > 1:
            component_reasons[root].add("cross_split_connected_component")
    for groups in reference_groups.values():
        if len(groups) > 1:
            for members in groups.values():
                for index in members:
                    component_reasons[components.find(index)].add("contradictory_reference_targets")
    for index, record in enumerate(inspected):
        record["reasons"].update(component_reasons[components.find(index)])

    duplicate_of = {}
    duplicate_groups = defaultdict(list)
    for index in range(len(inspected)):
        duplicate_groups[dedupes.find(index)].append(index)
    origin_rank = {"independently_checked": 0, "authored": 1, "compiler_weak": 2,
                   "teacher_prediction": 3, "unlabeled": 4}

    def representative_rank(index):
        binding = inspected[index]["binding"]
        return (bool(inspected[index]["reasons"]),
                not (binding["has_embedding"] and binding["has_reference_target"]),
                not binding["has_reference_target"], not binding["has_embedding"],
                origin_rank.get(binding["target_origin"], 5),
                binding["id"] or "", binding["row_sha256"] or "")

    for members in duplicate_groups.values():
        representative = min(members, key=representative_rank)
        for index in members:
            if index != representative:
                duplicate_of[index] = inspected[representative]["binding"]["id"]

    component_reports = []
    for root, members in members_by_component.items():
        bindings = sorted((inspected[index]["binding"] for index in members), key=_raw)
        component_sha256 = _digest(bindings)
        reasons = sorted({reason for index in members for reason in inspected[index]["reasons"]})
        component_reports.append({
            "component_sha256": component_sha256,
            "row_ids": sorted(binding["id"] for binding in bindings if binding["id"] is not None),
            "row_count": len(members),
            "splits": sorted({binding["split"] for binding in bindings} - {None}),
            "quarantine_reasons": reasons,
            "entire_component_quarantined": bool(component_reasons[root]),
        })
        for index in members:
            inspected[index]["component_sha256"] = component_sha256

    row_reports = []
    split_counts = Counter()
    domain_counts = Counter()
    origin_counts = Counter()
    sealed_counts = Counter()
    reason_counts = Counter()
    usable = Counter({name: 0 for name in (
        "retained_rows", "complete_reference_rows", "embedding_rows", "reference_rows",
        "missing_embedding_rows", "unlabeled_rows", "teacher_prediction_rows",
        "fitting_reference_rows", "selection_reference_rows",
        "sealed_evaluation_reference_rows", "development_evaluation_reference_rows",
    )})
    finite_norms = []
    norm_overflow_count = 0
    for index, record in enumerate(inspected):
        binding = record["binding"]
        split, role = binding["split"], binding["evaluation_role"]
        if split:
            split_counts[split] += 1
        if binding["domain_id"]:
            domain_counts[binding["domain_id"]] += 1
        if binding["target_origin"]:
            origin_counts[binding["target_origin"]] += 1
        if role == "sealed":
            sealed_counts[split or "invalid_split"] += 1
        norm = record["norm"]
        if norm is not None:
            if math.isfinite(norm):
                finite_norms.append(norm)
            else:
                norm_overflow_count += 1
        reasons = sorted(record["reasons"])
        reason_counts.update(reasons)
        retained = not reasons and index not in duplicate_of
        complete = retained and binding["has_embedding"] and binding["has_reference_target"]
        eligible = {
            "fitting_reference": complete and split == "train" and role == "development",
            "selection_reference": complete and split == "validation" and role == "development",
            "sealed_evaluation_reference": complete and split in ("test", "canary") and role == "sealed",
            "development_evaluation_reference": complete and split in ("test", "canary") and role == "development",
        }
        usable["retained_rows"] += retained
        usable["complete_reference_rows"] += complete
        usable["embedding_rows"] += retained and binding["has_embedding"]
        usable["reference_rows"] += retained and binding["has_reference_target"]
        usable["missing_embedding_rows"] += retained and not binding["has_embedding"]
        usable["unlabeled_rows"] += retained and binding["target_origin"] == "unlabeled"
        usable["teacher_prediction_rows"] += retained and binding["target_origin"] == "teacher_prediction"
        for name, value in eligible.items():
            usable[name + "_rows"] += value
        ineligible = []
        if not binding["has_embedding"]:
            ineligible.append("missing_embedding")
        if not binding["has_reference_target"]:
            ineligible.append("missing_reference_supervision")
        row_reports.append({**binding, "component_sha256": record["component_sha256"],
                            "quarantined": bool(reasons), "quarantine_reasons": reasons,
                            "deduplicated": index in duplicate_of,
                            "duplicate_of": duplicate_of.get(index),
                            "ineligible_reasons": ineligible, "eligibility": eligible})
    finite_norms.sort()
    row_reports.sort(key=_raw)
    component_reports.sort(key=lambda item: item["component_sha256"])
    return {
        "schema": SCHEMA, "profile": profile, "declared_profile_sha256": profile_sha256,
        "inventory_sha256": _digest({"profile": profile, "rows": row_reports}),
        "hash_scope": "declared_content_identity_not_authenticity_or_semantic_evidence",
        "typed_target_validated": False, "source_semantics_verified": False,
        "vectors_producer_verified": False, "normalization_verified": False,
        "split_memberships_changed": False, "sealed_memberships_inferred": False,
        "source_normalization": "NFKC_casefold_whitespace_collapse_for_grouping_only",
        "numeric_vector_identity": "exact_integer_or_float_ratio_signed_zero_equal",
        "input_row_count": len(inspected), "component_count": len(component_reports),
        "quarantined_row_count": sum(bool(record["reasons"]) for record in inspected),
        "deduplicated_row_count": len(duplicate_of), "duplicate_ids": duplicate_ids,
        "split_counts": {split: split_counts[split] for split in SPLITS},
        "domain_counts": {domain: domain_counts[domain] for domain in DOMAINS},
        "target_origin_counts": {origin: origin_counts[origin] for origin in TARGET_ORIGINS},
        "sealed_counts": {split: sealed_counts[split] for split in (*SPLITS, "invalid_split")},
        "usable_counts": dict(sorted(usable.items())),
        "quarantine_reason_counts": dict(sorted(reason_counts.items())),
        "normalization_stats": {
            "finite_numeric_vector_rows": len(finite_norms) + norm_overflow_count,
            "finite_norm_rows": len(finite_norms), "norm_overflow_rows": norm_overflow_count,
            "min_l2_norm": finite_norms[0] if finite_norms else None,
            "max_l2_norm": finite_norms[-1] if finite_norms else None,
            "unit_norm_tolerance": UNIT_NORM_TOLERANCE,
            "within_unit_norm_tolerance_rows": sum(abs(norm - 1.0) <= UNIT_NORM_TOLERANCE for norm in finite_norms),
        },
        "rows": row_reports, "components": component_reports,
    }
