"""Prepare a bounded, split-preserving affine-alignment plan without models.

Content hashes bind declarations. A caller must independently recompute the
bridge manifest from its pinned archive, audit, tasks and receipts before
fitting. This contract does not authenticate producers or qualify teachers.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import importlib.util
import json
import math
from pathlib import Path


SCHEMA = "gte-affine-alignment-plan/v1"
_MAX_ROWS = 100000
_MAX_FIT_ROWS = 4096
_MAX_CANDIDATES = 16


def _load_bridge():
    path = Path(__file__).with_name("gte_bridge_pairs.py")
    spec = importlib.util.spec_from_file_location("_gte_alignment_bridge_pairs", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the bridge-pair contract")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_BRIDGE = _load_bridge()
_AUDIT = _BRIDGE._AUDIT
_SPLITS = ("train", "validation")
_FALSE_FIELDS = frozenset((
    "split_memberships_changed", "reference_targets_exported", "source_text_exported",
    "target_semantics_verified", "source_vectors_producer_verified",
    "student_vectors_producer_verified", "student_model_numerics_verified",
    "tokenization_producer_verified", "teacher_qualified", "training_performed",
    "training_authorized", "proof_authority",
))
_PAIR_FIELDS = frozenset((
    "task_id", "source_id", "source_sha256", "student_component_sha256", "domain_id",
    "document_id", "group_id", "split", "source_language", "evaluation_role",
    "row_sha256", "component_sha256", "reference_target_sha256", "target_origin",
    "reference_supervision_eligible", "source_embedding_384", "student_embedding_768",
    "source_vector_space_id", "student_profile_id", "student_receipt_sha256",
    "asset_manifest_sha256",
))
_COUNT_FIELDS = frozenset((
    "archive_rows", "archive_quarantined_rows", "archive_deduplicated_rows",
    "archive_teacher_prediction_rows", "student_geometry_quarantined_rows",
    "student_geometry_deduplicated_rows", "source_tasks", "source_task_rejected_rows",
    "selected_domain_archive_rows", "selected_domain_tasks", "other_domain_tasks",
    "selected_domain_development_tasks", "selected_domain_non_development_tasks",
    "eligible_pair_tasks", "supplied_receipts", "bound_receipts", "missing_receipts",
    "missing_eligible_pair_receipts", "pairs", "reference_supervision_pairs",
    "teacher_prediction_pairs", "unlabeled_pairs",
))
_BRIDGE_FIELDS = frozenset((
    "schema", "status", "domain_id", "source_dimension", "student_dimension",
    "source_vector_space_id", "student_profile_id", "corpus_inventory_sha256",
    "student_geometry_inventory_sha256", "student_geometry_audit", "tasks_sha256",
    "tasks_manifest_sha256", "embedding_binding_sha256", "asset_manifest_sha256",
    "pairs_sha256", "pairs", "split_counts", "reference_supervision_split_counts",
    "pair_target_origin_counts", "counts", "terminal_row_counts", "excluded_rows",
    "exclusion_reason_counts", "missing_receipt_ids", "missing_eligible_pair_receipt_ids",
    "unavailable_reasons", "coverage_scope", "neural_input_fields",
    "alignment_target_fields", "unit_norm_tolerance",
)) | _FALSE_FIELDS
_BINDING_FIELDS = frozenset((
    "id", "domain_id", "document_id", "group_id", "split", "evaluation_role",
    "source_language", "target_origin", "row_sha256", "source_sha256",
    "normalized_source_sha256", "numeric_vector_sha256", "reference_target_sha256",
    "declared_profile_sha256", "has_embedding", "has_reference_target",
))
_AUDIT_ROW_FIELDS = _BINDING_FIELDS | frozenset((
    "component_sha256", "quarantined", "quarantine_reasons", "deduplicated",
    "duplicate_of", "ineligible_reasons", "eligibility",
))
_AUDIT_FIELDS = frozenset((
    "schema", "profile", "declared_profile_sha256", "inventory_sha256", "hash_scope",
    "typed_target_validated", "source_semantics_verified", "vectors_producer_verified",
    "normalization_verified", "split_memberships_changed", "sealed_memberships_inferred",
    "source_normalization", "numeric_vector_identity", "input_row_count", "component_count",
    "quarantined_row_count", "deduplicated_row_count", "duplicate_ids", "split_counts",
    "domain_counts", "target_origin_counts", "sealed_counts", "usable_counts",
    "quarantine_reason_counts", "normalization_stats", "rows", "components",
))
_EXCLUDED_FIELDS = frozenset((
    "source_id", "task_id", "domain_id", "split", "row_sha256", "source_sha256",
    "component_sha256", "status", "reasons",
))
_PIN_FIELDS = frozenset((
    "corpus_inventory_sha256", "student_geometry_inventory_sha256", "tasks_sha256",
    "tasks_manifest_sha256", "embedding_binding_sha256", "pairs_sha256",
))
_PLAN_FIELDS = frozenset((
    "schema", "status", "fit_ready", "domain_id", "source_dimension", "student_dimension",
    "source_vector_space_id", "student_profile_id", "pairs_manifest_sha256", "pairs_sha256",
    "corpus_inventory_sha256", "student_geometry_inventory_sha256", "tasks_sha256",
    "tasks_manifest_sha256", "embedding_binding_sha256", "asset_manifest_sha256",
    "regularization_candidates", "selection_policy", "max_train_pairs", "max_validation_pairs",
    "train_rows", "validation_rows", "train_rows_sha256", "validation_rows_sha256",
    "excluded_rows_sha256", "original_split_counts", "counts", "unavailable_reasons",
    "input_alignment_direction", "neural_input_fields", "alignment_target_fields",
    "unit_norm_tolerance", "hash_scope", "teacher_qualification_required",
    "donor_checkpoint_required", "producer_authenticity_verified", "plan_sha256",
)) | _FALSE_FIELDS
_PLAN_COUNT_FIELDS = frozenset((
    "archive_rows", "excluded_rows", "available_pairs", "train_pairs", "validation_pairs",
    "missing_eligible_pair_receipts", "archive_quarantined_rows", "archive_deduplicated_rows",
    "student_geometry_quarantined_rows", "student_geometry_deduplicated_rows",
    "reference_supervision_pairs", "teacher_prediction_pairs", "unlabeled_pairs",
    "regularization_candidates", "selected_fit_rows", "selected_validation_rows",
))


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _sha(value):
    return (type(value) is str and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def _text(value):
    return type(value) is str and bool(value.strip()) and _AUDIT._json_value(value)


def _int(value, maximum=_MAX_ROWS):
    return type(value) is int and 0 <= value <= maximum


def _counts(value, fields, label):
    _require(type(value) is dict and set(value) == fields
             and all(_int(item) for item in value.values()), label + " has invalid fields or counts")


def _strings(value, label, *, allow_empty=True):
    _require(type(value) is list and len(value) <= _MAX_ROWS
             and all(_text(item) for item in value), label + " must be a bounded string array")
    _require(value == sorted(set(value)), label + " must be sorted and unique")
    if not allow_empty:
        _require(bool(value), label + " must not be empty")


def _bounded_list(value, maximum, label):
    _require(type(value) is list and len(value) <= maximum,
             label + " must be an array within its row bound")


def _limits(max_train_pairs, max_validation_pairs):
    for name, value in (("max_train_pairs", max_train_pairs),
                        ("max_validation_pairs", max_validation_pairs)):
        _require(type(value) is int and 1 <= value <= _MAX_FIT_ROWS,
                 name + " must be an integer between 1 and 4096")


def _candidates(value):
    _require(type(value) in (tuple, list) and 1 <= len(value) <= _MAX_CANDIDATES,
             "regularization_candidates must contain between 1 and 16 values")
    result = []
    for item in value:
        _require(type(item) in (int, float), "regularization candidates must be finite positive numbers")
        try:
            number = float(item)
        except (ValueError, OverflowError):
            raise ValueError("regularization candidates must be finite positive numbers") from None
        _require(math.isfinite(number) and 1e-8 <= number <= 1e6,
                 "regularization candidates must lie between 1e-8 and 1e6")
        result.append(number)
    _require(result == sorted(set(result)), "regularization candidates must be increasing and distinct")
    return result


def _vector(value, width):
    _require(type(value) is list and len(value) == width, "alignment vector has wrong width")
    numbers = []
    for item in value:
        _require(type(item) in (int, float), "alignment vectors must be finite numeric arrays")
        try:
            number = float(item)
        except (OverflowError, ValueError):
            raise ValueError("alignment vectors must be finite numeric arrays") from None
        _require(math.isfinite(number), "alignment vectors must be finite numeric arrays")
        numbers.append(number)
    _require(abs(math.hypot(*numbers) - 1.0) <= _BRIDGE.UNIT_NORM_TOLERANCE,
             "alignment vectors must be unit normalized")
    return _AUDIT._numeric_vector_digest(value)


def _pair_rows(pairs, *, domain_id, source_profile, student_profile, asset_hash,
               max_train_pairs, max_validation_pairs, geometry_by_id=None):
    _bounded_list(pairs, min(_MAX_ROWS, max_train_pairs + max_validation_pairs), "pairs")
    split_counts = Counter()
    seen = {name: {} for name in ("task_id", "source_id", "row_sha256", "source_sha256",
                                  "document_id", "group_id", "component_sha256",
                                  "student_component_sha256", "source_vector", "student_vector",
                                  "normalized_source")}
    rows = {split: [] for split in _SPLITS}
    for pair in pairs:
        _require(type(pair) is dict and set(pair) == _PAIR_FIELDS, "pair has invalid fields")
        for field in ("task_id", "source_id", "document_id", "group_id", "source_language"):
            _require(_text(pair[field]), "pair has invalid " + field)
        _require(pair["domain_id"] == domain_id and pair["split"] in _SPLITS
                 and pair["evaluation_role"] == "development", "pair is outside development alignment scope")
        _require(pair["source_vector_space_id"] == source_profile
                 and pair["student_profile_id"] == student_profile,
                 "pair profile does not match manifest")
        for field in ("source_sha256", "student_component_sha256", "row_sha256", "component_sha256",
                      "student_receipt_sha256", "asset_manifest_sha256"):
            _require(_sha(pair[field]), "pair has invalid " + field)
        _require(pair["asset_manifest_sha256"] == asset_hash, "pair asset manifest does not match")
        origin = pair["target_origin"]
        _require(origin in _AUDIT.TARGET_ORIGINS, "pair has invalid target origin")
        target_hash = pair["reference_target_sha256"]
        _require((target_hash is None and origin == "unlabeled")
                 or (_sha(target_hash) and origin != "unlabeled"), "pair target binding is inconsistent")
        _require(type(pair["reference_supervision_eligible"]) is bool
                 and pair["reference_supervision_eligible"] == (origin not in ("teacher_prediction", "unlabeled")),
                 "pair reference-supervision flag is inconsistent")
        identities = {field: pair[field] for field in seen if field in pair}
        identities["source_vector"] = _vector(pair["source_embedding_384"], 384)
        identities["student_vector"] = _vector(pair["student_embedding_768"], 768)
        if geometry_by_id is not None:
            geometry = geometry_by_id.get(pair["source_id"])
            _require(geometry is not None and not geometry["quarantined"] and not geometry["deduplicated"],
                     "pair is missing or excluded by the student geometry audit")
            for field in ("domain_id", "document_id", "group_id", "split", "source_language",
                          "evaluation_role", "source_sha256", "reference_target_sha256", "target_origin"):
                _require(pair[field] == geometry[field], "pair disagrees with student geometry binding: " + field)
            _require(pair["student_component_sha256"] == geometry["component_sha256"]
                     and identities["student_vector"] == geometry["numeric_vector_sha256"]
                     and pair["reference_supervision_eligible"] == geometry["has_reference_target"],
                     "pair disagrees with student vector/reference geometry binding")
            identities["normalized_source"] = geometry["normalized_source_sha256"]
        split = pair["split"]
        for name, identity in identities.items():
            if identity is None:
                continue
            previous = seen[name].get(identity)
            # Repeated document/group/components within one split are legitimate;
            # exact rows, source and vectors must already have been deduplicated.
            unique = name in ("task_id", "source_id", "row_sha256", "source_sha256",
                              "source_vector", "student_vector")
            _require(previous is None or (previous == split and not unique),
                     "duplicate or cross-split alignment identity: " + name)
            seen[name][identity] = split
        split_counts[split] += 1
        bound = max_train_pairs if split == "train" else max_validation_pairs
        _require(split_counts[split] <= bound, split + " pairs exceed configured row bound")
        rows[split].append(pair)
    _require([pair["task_id"] for pair in pairs] == sorted(pair["task_id"] for pair in pairs),
             "pairs must retain canonical task order")
    return rows


def _geometry(manifest):
    audit = manifest["student_geometry_audit"]
    _require(type(audit) is dict and set(audit) == _AUDIT_FIELDS and audit["schema"] == _AUDIT.SCHEMA,
             "student geometry audit has invalid schema or fields")
    count = manifest["counts"]["archive_rows"]
    _bounded_list(audit["rows"], count, "student geometry rows")
    _bounded_list(audit["components"], count, "student geometry components")
    _require(len(audit["rows"]) == count and audit["input_row_count"] == count,
             "student geometry archive count does not match")
    for field in ("input_row_count", "component_count", "quarantined_row_count", "deduplicated_row_count"):
        _require(_int(audit[field]) and audit[field] <= count, "invalid student geometry count")
    expected_profile = {"dimension": 768, "vector_space_id": _BRIDGE.PROFILE_ID,
                        "identity_status": "declared_not_producer_verified"}
    _require(audit["profile"] == expected_profile
             and audit["declared_profile_sha256"] == _digest(expected_profile), "student geometry profile mismatch")
    _require(audit["inventory_sha256"] == manifest["student_geometry_inventory_sha256"]
             and audit["inventory_sha256"] == _digest({"profile": audit["profile"], "rows": audit["rows"]}),
             "student geometry inventory digest mismatch")
    for field in ("typed_target_validated", "source_semantics_verified", "vectors_producer_verified",
                  "normalization_verified", "split_memberships_changed", "sealed_memberships_inferred"):
        _require(audit[field] is False, "student geometry contains an unsupported evidence claim")
    _require(audit["hash_scope"] == "declared_content_identity_not_authenticity_or_semantic_evidence"
             and audit["source_normalization"] == "NFKC_casefold_whitespace_collapse_for_grouping_only"
             and audit["numeric_vector_identity"] == "exact_integer_or_float_ratio_signed_zero_equal",
             "student geometry identity policy mismatch")
    by_id = {}
    groups = defaultdict(list)
    connected_components = _AUDIT._Components(count)
    identity_members = {}
    for index, row in enumerate(audit["rows"]):
        _require(type(row) is dict and set(row) == _AUDIT_ROW_FIELDS, "student geometry row has invalid fields")
        for field in ("id", "document_id", "group_id", "source_language", "duplicate_of"):
            _require(row[field] is None or _text(row[field]), "invalid student geometry identity field")
        for field, allowed in (("domain_id", _AUDIT.DOMAINS), ("split", _AUDIT.SPLITS),
                               ("target_origin", _AUDIT.TARGET_ORIGINS),
                               ("evaluation_role", ("development", "sealed"))):
            _require(row[field] is None or row[field] in allowed, "invalid student geometry membership field")
        for field in ("quarantined", "deduplicated", "has_embedding", "has_reference_target"):
            _require(type(row[field]) is bool, "student geometry row flag is invalid")
        for field in ("component_sha256", "declared_profile_sha256"):
            _require(_sha(row[field]), "student geometry row hash is invalid")
        _require(row["declared_profile_sha256"] == audit["declared_profile_sha256"],
                 "student geometry row profile hash mismatch")
        _strings(row["quarantine_reasons"], "geometry quarantine reasons")
        _require(row["quarantined"] == bool(row["quarantine_reasons"]), "geometry quarantine flag mismatch")
        _require(type(row["ineligible_reasons"]) is list
                 and all(_text(reason) for reason in row["ineligible_reasons"]), "invalid geometry ineligible reasons")
        eligibility = row["eligibility"]
        _require(type(eligibility) is dict and set(eligibility) == {
            "fitting_reference", "selection_reference", "sealed_evaluation_reference", "development_evaluation_reference"
        } and all(type(flag) is bool for flag in eligibility.values()), "invalid geometry eligibility")
        for field in ("row_sha256", "source_sha256", "normalized_source_sha256", "numeric_vector_sha256",
                      "reference_target_sha256"):
            _require(row[field] is None or _sha(row[field]), "invalid geometry content hash")
        _require(row["has_embedding"] == (row["numeric_vector_sha256"] is not None)
                 and row["has_reference_target"] == (row["reference_target_sha256"] is not None
                     and row["target_origin"] not in ("teacher_prediction", "unlabeled")),
                 "student geometry vector/reference flag mismatch")
        expected_ineligible = []
        if not row["has_embedding"]:
            expected_ineligible.append("missing_embedding")
        if not row["has_reference_target"]:
            expected_ineligible.append("missing_reference_supervision")
        _require(row["ineligible_reasons"] == expected_ineligible, "geometry ineligible reasons mismatch")
        complete = (not row["quarantined"] and not row["deduplicated"]
                    and row["has_embedding"] and row["has_reference_target"])
        expected_eligibility = {
            "fitting_reference": complete and row["split"] == "train" and row["evaluation_role"] == "development",
            "selection_reference": complete and row["split"] == "validation" and row["evaluation_role"] == "development",
            "sealed_evaluation_reference": complete and row["split"] in ("test", "canary") and row["evaluation_role"] == "sealed",
            "development_evaluation_reference": complete and row["split"] in ("test", "canary") and row["evaluation_role"] == "development",
        }
        _require(eligibility == expected_eligibility, "student geometry eligibility claim mismatch")
        if not row["quarantined"]:
            _require(_text(row["id"]) and row["id"] not in by_id, "retained geometry source identifier is not unique")
            by_id[row["id"]] = row
        groups[row["component_sha256"]].append(row)
        identities = [(field, row[field]) for field in (
            "id", "source_sha256", "normalized_source_sha256", "numeric_vector_sha256"
        ) if row[field] is not None]
        if row["domain_id"] is not None:
            identities += [(field, row["domain_id"], row[field]) for field in ("document_id", "group_id")
                           if row[field] is not None]
        for identity in identities:
            previous = identity_members.get(identity)
            if previous is not None:
                connected_components.join(previous, index)
            else:
                identity_members[identity] = index
    _require(audit["quarantined_row_count"] == sum(row["quarantined"] for row in audit["rows"])
             and audit["deduplicated_row_count"] == sum(row["deduplicated"] for row in audit["rows"]),
             "student geometry quarantine or duplicate count mismatch")
    _require(audit["component_count"] == len(audit["components"]) == len(groups), "student geometry component count mismatch")
    recomputed_members = defaultdict(list)
    for index, row in enumerate(audit["rows"]):
        recomputed_members[connected_components.find(index)].append(row)
    _require(len(recomputed_members) == len(groups)
             and all(len({row["component_sha256"] for row in members}) == 1
                     and len(groups[members[0]["component_sha256"]]) == len(members)
                     for members in recomputed_members.values()),
             "student geometry connected-component identities disagree with its audit")
    for field, source_field, memberships in (("split_counts", "split", _AUDIT.SPLITS),
                                            ("domain_counts", "domain_id", _AUDIT.DOMAINS),
                                            ("target_origin_counts", "target_origin", _AUDIT.TARGET_ORIGINS)):
        counter = Counter(row[source_field] for row in audit["rows"])
        _counts(audit[field], frozenset(memberships), "student geometry " + field)
        _require(audit[field] == {item: counter[item] for item in memberships}, "student geometry membership counts mismatch")
    component_ids = set()
    for component in audit["components"]:
        _require(type(component) is dict and set(component) == {
            "component_sha256", "row_ids", "row_count", "splits", "quarantine_reasons", "entire_component_quarantined"
        }, "student geometry component has invalid fields")
        key = component["component_sha256"]
        _require(key in groups and key not in component_ids, "student geometry component binding missing or duplicate")
        component_ids.add(key)
        members = groups[key]
        bindings = sorted(({field: row[field] for field in _BINDING_FIELDS} for row in members), key=_raw)
        _require(key == _digest(bindings) and component["row_count"] == len(members), "student geometry component digest mismatch")
        _require(component["row_ids"] == sorted(row["id"] for row in members if row["id"] is not None)
                 and component["splits"] == sorted({row["split"] for row in members} - {None}),
                 "student geometry component membership mismatch")
        reasons = sorted({reason for row in members for reason in row["quarantine_reasons"]})
        _require(component["quarantine_reasons"] == reasons
                 and type(component["entire_component_quarantined"]) is bool
                 and component["entire_component_quarantined"] == any(
                     reason in reasons for reason in ("cross_split_connected_component", "contradictory_reference_targets")),
                 "student geometry component quarantine mismatch")
        if len(component["splits"]) > 1:
            _require(all(row["quarantined"] for row in members)
                     and component["entire_component_quarantined"], "cross-split geometry component was retained")
    return by_id


def _validate_manifest(manifest, max_train_pairs, max_validation_pairs):
    _require(type(manifest) is dict and set(manifest) == _BRIDGE_FIELDS
             and manifest["schema"] == _BRIDGE.SCHEMA, "bridge pairs manifest has invalid schema or fields")
    _counts(manifest["counts"], _COUNT_FIELDS, "bridge counts")
    counts = manifest["counts"]
    _bounded_list(manifest["pairs"], min(_MAX_ROWS, max_train_pairs + max_validation_pairs), "pairs")
    _bounded_list(manifest["excluded_rows"], counts["archive_rows"], "excluded rows")
    _require(len(manifest["pairs"]) == counts["pairs"]
             and len(manifest["excluded_rows"]) + counts["pairs"] == counts["archive_rows"],
             "bridge pair and archive counts do not match")
    for row in manifest["pairs"]:
        _require(type(row) is dict and set(row) == _PAIR_FIELDS, "pair has invalid fields")
        for field, width in (("source_embedding_384", 384), ("student_embedding_768", 768)):
            _require(type(row[field]) is list and len(row[field]) == width, "alignment vector has wrong width")
    geometry = manifest["student_geometry_audit"]
    _require(type(geometry) is dict and set(geometry) == _AUDIT_FIELDS,
             "student geometry audit has invalid schema or fields")
    _bounded_list(geometry["rows"], counts["archive_rows"], "student geometry rows")
    _bounded_list(geometry["components"], counts["archive_rows"], "student geometry components")
    _require(_AUDIT._json_value(manifest), "bridge pairs manifest must be finite acyclic JSON")
    _require(manifest["source_dimension"] == 384 and type(manifest["source_dimension"]) is int
             and manifest["student_dimension"] == 768 and type(manifest["student_dimension"]) is int,
             "bridge dimensions must be 768 to 384")
    _require(manifest["domain_id"] in _AUDIT.DOMAINS and _text(manifest["source_vector_space_id"])
             and manifest["student_profile_id"] == _BRIDGE.PROFILE_ID, "bridge profile or domain mismatch")
    for field in _PIN_FIELDS:
        _require(_sha(manifest[field]), "invalid bridge " + field)
    asset = manifest["asset_manifest_sha256"]
    _require(asset is None or _sha(asset), "invalid bridge asset binding")
    _require(not counts["pairs"] or _sha(asset), "paired rows require an asset binding")
    _require(manifest["pairs_sha256"] == _digest(manifest["pairs"]), "bridge pairs digest mismatch")
    for field in _FALSE_FIELDS:
        _require(manifest[field] is False, "bridge contains an unsupported evidence claim: " + field)
    _require(manifest["unit_norm_tolerance"] == _BRIDGE.UNIT_NORM_TOLERANCE
             and type(manifest["unit_norm_tolerance"]) is float
             and manifest["coverage_scope"] == "selected_domain_retained_development_train_validation_tasks"
             and manifest["neural_input_fields"] == ["student_embedding_768"]
             and manifest["alignment_target_fields"] == ["source_embedding_384"], "bridge input or scope policy mismatch")
    geometry_by_id = _geometry(manifest)
    rows = _pair_rows(manifest["pairs"], domain_id=manifest["domain_id"],
                      source_profile=manifest["source_vector_space_id"], student_profile=manifest["student_profile_id"],
                      asset_hash=asset, max_train_pairs=max_train_pairs,
                      max_validation_pairs=max_validation_pairs, geometry_by_id=geometry_by_id)
    expected_splits = {split: len(rows[split]) for split in _SPLITS}
    _require(manifest["split_counts"] == expected_splits, "bridge split counts mismatch")
    expected_refs = {split: sum(row["reference_supervision_eligible"] for row in rows[split]) for split in _SPLITS}
    origins = Counter(row["target_origin"] for row in manifest["pairs"])
    _require(manifest["reference_supervision_split_counts"] == expected_refs
             and manifest["pair_target_origin_counts"] == {origin: origins[origin] for origin in _AUDIT.TARGET_ORIGINS},
             "bridge target-origin or reference counts mismatch")
    _require(counts["reference_supervision_pairs"] == sum(expected_refs.values())
             and counts["teacher_prediction_pairs"] == origins["teacher_prediction"]
             and counts["unlabeled_pairs"] == origins["unlabeled"], "bridge pair supervision counts mismatch")
    _counts(manifest["terminal_row_counts"], frozenset(_BRIDGE._TERMINAL_STATUSES), "terminal row counts")
    terminal = Counter()
    reasons = Counter()
    missing = []
    quarantined_duplicates = 0
    pair_source_ids = {row["source_id"] for row in manifest["pairs"]}
    for excluded in manifest["excluded_rows"]:
        _require(type(excluded) is dict and set(excluded) == _EXCLUDED_FIELDS,
                 "excluded row has invalid fields")
        _require(excluded["status"] in _BRIDGE._TERMINAL_STATUSES
                 and excluded["status"] != "paired", "excluded row has invalid terminal status")
        for field in ("source_id", "task_id"):
            _require(excluded[field] is None or _text(excluded[field]), "excluded row has invalid identifier")
        _require(excluded["domain_id"] is None or excluded["domain_id"] in _AUDIT.DOMAINS,
                 "excluded row has invalid domain")
        _require(excluded["split"] is None or excluded["split"] in _AUDIT.SPLITS,
                 "excluded row has invalid split")
        _require(excluded["source_id"] not in pair_source_ids,
                 "an excluded archive identifier was reintroduced into alignment")
        _require(_sha(excluded["component_sha256"])
                 and (excluded["row_sha256"] is None or _sha(excluded["row_sha256"]))
                 and (excluded["source_sha256"] is None or _sha(excluded["source_sha256"])),
                 "excluded row has invalid content bindings")
        _strings(excluded["reasons"], "excluded reasons", allow_empty=False)
        terminal[excluded["status"]] += 1
        reasons.update(excluded["reasons"])
        if excluded["status"] == "quarantined" and "deduplicated" in excluded["reasons"]:
            quarantined_duplicates += 1
        if excluded["status"] == "missing_768_receipt":
            _require(_text(excluded["task_id"]), "missing receipt exclusion requires a task identifier")
            missing.append(excluded["task_id"])
    terminal["paired"] = counts["pairs"]
    _require(manifest["terminal_row_counts"] == {name: terminal[name] for name in _BRIDGE._TERMINAL_STATUSES}
             and manifest["exclusion_reason_counts"] == dict(sorted(reasons.items())), "bridge exclusion counts mismatch")
    _require(counts["archive_quarantined_rows"] == terminal["quarantined"]
             and counts["archive_deduplicated_rows"] == terminal["deduplicated"] + quarantined_duplicates
             and counts["archive_teacher_prediction_rows"] == manifest["student_geometry_audit"]["target_origin_counts"]["teacher_prediction"]
             and counts["selected_domain_archive_rows"] == manifest["student_geometry_audit"]["domain_counts"][manifest["domain_id"]],
             "bridge archive quarantine, domain or origin counts mismatch")
    for field in ("missing_receipt_ids", "missing_eligible_pair_receipt_ids"):
        _strings(manifest[field], field)
    _require(manifest["missing_eligible_pair_receipt_ids"] == sorted(missing)
             and set(missing) <= set(manifest["missing_receipt_ids"]), "bridge missing receipt membership mismatch")
    _require(counts["missing_receipts"] == len(manifest["missing_receipt_ids"])
             and counts["missing_eligible_pair_receipts"] == len(missing)
             and counts["eligible_pair_tasks"] == counts["pairs"] + len(missing)
             and counts["eligible_pair_tasks"] <= counts["selected_domain_development_tasks"],
             "bridge eligible receipt counts mismatch")
    _require(counts["source_tasks"] + counts["source_task_rejected_rows"] == counts["archive_rows"]
             and counts["selected_domain_tasks"] + counts["other_domain_tasks"] == counts["source_tasks"]
             and counts["selected_domain_development_tasks"] + counts["selected_domain_non_development_tasks"] == counts["selected_domain_tasks"]
             and counts["bound_receipts"] == counts["supplied_receipts"]
             and counts["bound_receipts"] + counts["missing_receipts"] == counts["source_tasks"],
             "bridge task and receipt coverage counts mismatch")
    for field, audit_field in (("student_geometry_quarantined_rows", "quarantined_row_count"),
                              ("student_geometry_deduplicated_rows", "deduplicated_row_count")):
        _require(counts[field] == manifest["student_geometry_audit"][audit_field], "bridge geometry counts mismatch")
    expected_status = ("ready" if counts["pairs"] and counts["pairs"] == counts["selected_domain_development_tasks"]
                       else "partial" if counts["pairs"] else "unavailable")
    _require(manifest["status"] == expected_status, "bridge coverage status mismatch")
    expected_reasons = []
    if not counts["pairs"]:
        if not counts["selected_domain_development_tasks"]:
            expected_reasons.append("no_selected_domain_development_tasks")
        for field, reason in (("student_quarantined", "student_geometry_quarantine"),
                              ("student_deduplicated", "student_geometry_deduplication"),
                              ("missing_384_input", "missing_384_inputs"),
                              ("non_unit_384_input", "non_unit_384_inputs")):
            if terminal[field]:
                expected_reasons.append(reason)
        if missing:
            expected_reasons.append("missing_768_receipts")
    _require(manifest["unavailable_reasons"] == expected_reasons, "bridge unavailable reasons mismatch")
    return rows


def _readiness(train_count, validation_count, candidates):
    reasons = []
    if train_count < 2:
        reasons.append("at_least_two_distinct_training_pairs_required")
    if len(candidates) > 1 and not validation_count:
        reasons.append("validation_pairs_required_for_candidate_selection")
    policy = ("development_validation_mse" if validation_count or len(candidates) > 1
              else "fixed_candidate_no_validation")
    return not reasons, reasons, policy


def prepare_alignment_plan(pairs_manifest, *, regularization_candidates=(.001, .01, .1),
                           max_train_pairs=4096, max_validation_pairs=4096):
    """Prepare training-only fitting and separate development validation rows.

    No row is resplit, truncated or silently admitted from an excluded component.
    Multiple ridge candidates require validation. An explicitly fixed candidate
    permits train-only fitting. At least two distinct training pairs are required.
    Teacher-prediction and unlabeled rows may align vectors without becoming
    reference supervision; teacher semantic qualification is irrelevant here.
    """
    _limits(max_train_pairs, max_validation_pairs)
    candidates = _candidates(regularization_candidates)
    rows = _validate_manifest(pairs_manifest, max_train_pairs, max_validation_pairs)
    # Copy only after every bound, shape, content and membership check succeeds.
    copied = {split: [{**row, "source_embedding_384": list(row["source_embedding_384"]),
                      "student_embedding_768": list(row["student_embedding_768"])} for row in rows[split]]
              for split in _SPLITS}
    ready, reasons, policy = _readiness(len(rows["train"]), len(rows["validation"]), candidates)
    if not pairs_manifest["pairs"]:
        reasons = list(dict.fromkeys(pairs_manifest["unavailable_reasons"] + reasons))
    original_counts = pairs_manifest["counts"]
    counts = {field: original_counts[field] for field in (
        "archive_rows", "missing_eligible_pair_receipts", "archive_quarantined_rows",
        "archive_deduplicated_rows", "student_geometry_quarantined_rows",
        "student_geometry_deduplicated_rows", "reference_supervision_pairs",
        "teacher_prediction_pairs", "unlabeled_pairs",
    )}
    counts.update({"excluded_rows": len(pairs_manifest["excluded_rows"]),
                   "available_pairs": len(pairs_manifest["pairs"]),
                   "train_pairs": len(rows["train"]), "validation_pairs": len(rows["validation"]),
                   "regularization_candidates": len(candidates),
                   "selected_fit_rows": len(rows["train"]) if ready else 0,
                   "selected_validation_rows": len(rows["validation"]) if ready else 0})
    plan = {"schema": SCHEMA, "status": "ready" if ready else "unavailable", "fit_ready": ready,
            "domain_id": pairs_manifest["domain_id"], "source_dimension": 384, "student_dimension": 768,
            "source_vector_space_id": pairs_manifest["source_vector_space_id"],
            "student_profile_id": pairs_manifest["student_profile_id"],
            "pairs_manifest_sha256": _digest(pairs_manifest),
            **{field: pairs_manifest[field] for field in _PIN_FIELDS},
            "asset_manifest_sha256": pairs_manifest["asset_manifest_sha256"],
            "regularization_candidates": candidates, "selection_policy": policy,
            "max_train_pairs": max_train_pairs, "max_validation_pairs": max_validation_pairs,
            "train_rows": copied["train"], "validation_rows": copied["validation"],
            "train_rows_sha256": _digest(copied["train"]),
            "validation_rows_sha256": _digest(copied["validation"]),
            "excluded_rows_sha256": _digest(pairs_manifest["excluded_rows"]),
            "original_split_counts": dict(pairs_manifest["split_counts"]), "counts": counts,
            "unavailable_reasons": reasons, "input_alignment_direction": "student_768_to_source_384",
            "neural_input_fields": ["student_embedding_768"],
            "alignment_target_fields": ["source_embedding_384"],
            "unit_norm_tolerance": _BRIDGE.UNIT_NORM_TOLERANCE,
            "hash_scope": "declared_content_identity_not_authenticity_or_semantic_evidence",
            "teacher_qualification_required": False, "donor_checkpoint_required": False,
            "producer_authenticity_verified": False,
            **{field: False for field in _FALSE_FIELDS}}
    plan["plan_sha256"] = _digest(plan)
    inspect_alignment_plan(plan)
    return plan


def inspect_alignment_plan(plan):
    """Validate a serialized plan's content; do not authenticate its provenance."""
    _require(type(plan) is dict and set(plan) == _PLAN_FIELDS and plan["schema"] == SCHEMA,
             "alignment plan has invalid schema or fields")
    _limits(plan["max_train_pairs"], plan["max_validation_pairs"])
    _bounded_list(plan["train_rows"], plan["max_train_pairs"], "training rows")
    _bounded_list(plan["validation_rows"], plan["max_validation_pairs"], "validation rows")
    _counts(plan["counts"], _PLAN_COUNT_FIELDS, "alignment plan counts")
    for row in plan["train_rows"] + plan["validation_rows"]:
        _require(type(row) is dict and set(row) == _PAIR_FIELDS, "alignment plan row fields are invalid")
        for field, width in (("source_embedding_384", 384), ("student_embedding_768", 768)):
            _require(type(row[field]) is list and len(row[field]) == width, "alignment vector has wrong width")
    _require(_AUDIT._json_value(plan), "alignment plan must be finite acyclic JSON")
    candidates = _candidates(plan["regularization_candidates"])
    _require(plan["source_dimension"] == 384 and type(plan["source_dimension"]) is int
             and plan["student_dimension"] == 768 and type(plan["student_dimension"]) is int
             and plan["domain_id"] in _AUDIT.DOMAINS and _text(plan["source_vector_space_id"])
             and plan["student_profile_id"] == _BRIDGE.PROFILE_ID, "alignment plan profile mismatch")
    for field in _PIN_FIELDS | {"pairs_manifest_sha256", "train_rows_sha256", "validation_rows_sha256",
                               "excluded_rows_sha256", "plan_sha256"}:
        _require(_sha(plan[field]), "invalid alignment plan " + field)
    _require(plan["asset_manifest_sha256"] is None or _sha(plan["asset_manifest_sha256"]),
             "invalid alignment plan asset manifest binding")
    _require(plan["plan_sha256"] == _digest({field: value for field, value in plan.items() if field != "plan_sha256"}),
             "alignment plan digest mismatch")
    _require(plan["train_rows_sha256"] == _digest(plan["train_rows"])
             and plan["validation_rows_sha256"] == _digest(plan["validation_rows"]), "alignment plan row digest mismatch")
    all_rows = plan["train_rows"] + plan["validation_rows"]
    _require(all(type(row) is dict and set(row) == _PAIR_FIELDS and _text(row["task_id"]) for row in all_rows),
             "alignment plan row fields or task identifiers are invalid")
    combined = sorted(all_rows, key=lambda row: row["task_id"])
    _require(plan["pairs_sha256"] == _digest(combined), "alignment plan original pairs binding mismatch")
    rows = _pair_rows(combined, domain_id=plan["domain_id"], source_profile=plan["source_vector_space_id"],
                      student_profile=plan["student_profile_id"], asset_hash=plan["asset_manifest_sha256"],
                      max_train_pairs=plan["max_train_pairs"], max_validation_pairs=plan["max_validation_pairs"])
    _require(rows["train"] == plan["train_rows"] and rows["validation"] == plan["validation_rows"],
             "alignment plan changed original split memberships or ordering")
    ready, reasons, policy = _readiness(len(rows["train"]), len(rows["validation"]), candidates)
    _require(type(plan["fit_ready"]) is bool and plan["fit_ready"] == ready
             and plan["status"] == ("ready" if ready else "unavailable")
             and plan["selection_policy"] == policy, "alignment plan readiness or selection policy mismatch")
    _require(type(plan["unavailable_reasons"]) is list
             and len(plan["unavailable_reasons"]) <= 32
             and all(_text(reason) for reason in plan["unavailable_reasons"])
             and all(reason in plan["unavailable_reasons"] for reason in reasons)
             and (not ready or not plan["unavailable_reasons"]), "alignment plan unavailable reasons mismatch")
    counts = plan["counts"]
    origins = Counter(row["target_origin"] for row in combined)
    _require(counts["available_pairs"] == len(combined)
             and counts["train_pairs"] == len(rows["train"])
             and counts["validation_pairs"] == len(rows["validation"])
             and counts["selected_fit_rows"] == (len(rows["train"]) if ready else 0)
             and counts["selected_validation_rows"] == (len(rows["validation"]) if ready else 0)
             and counts["regularization_candidates"] == len(candidates)
             and counts["archive_rows"] == counts["excluded_rows"] + len(combined)
             and counts["reference_supervision_pairs"] == sum(row["reference_supervision_eligible"] for row in combined)
             and counts["teacher_prediction_pairs"] == origins["teacher_prediction"]
             and counts["unlabeled_pairs"] == origins["unlabeled"], "alignment plan counts mismatch")
    _require(plan["original_split_counts"] == {split: len(rows[split]) for split in _SPLITS},
             "alignment plan original split counts mismatch")
    for field in _FALSE_FIELDS | {"teacher_qualification_required", "donor_checkpoint_required", "producer_authenticity_verified"}:
        _require(plan[field] is False, "alignment plan contains an unsupported evidence claim")
    _require(plan["unit_norm_tolerance"] == _BRIDGE.UNIT_NORM_TOLERANCE
             and type(plan["unit_norm_tolerance"]) is float
             and plan["input_alignment_direction"] == "student_768_to_source_384"
             and plan["neural_input_fields"] == ["student_embedding_768"]
             and plan["alignment_target_fields"] == ["source_embedding_384"]
             and plan["hash_scope"] == "declared_content_identity_not_authenticity_or_semantic_evidence",
             "alignment plan input, direction or evidence policy mismatch")
    return {"schema": SCHEMA, "status": plan["status"], "fit_ready": ready,
            "plan_sha256": plan["plan_sha256"], "train_pairs": len(rows["train"]),
            "validation_pairs": len(rows["validation"]), "selection_policy": policy,
            "producer_authenticity_verified": False}
