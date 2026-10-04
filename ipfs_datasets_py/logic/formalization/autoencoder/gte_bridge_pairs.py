"""Prepare an exact-source 768-to-384 embedding bridge without loading models.

The complete 384D archive audit and source-only task manifest are recomputed
before declared 768D receipts are bound. Only existing development train and
validation memberships may supply pairs. Content bindings and vector geometry
do not establish encoder execution, reference semantics, or teacher quality.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import importlib.util
import json
import math
from pathlib import Path


SCHEMA = "gte-bridge-pairs/v1"
UNIT_NORM_TOLERANCE = 1e-4
_MAX_ROWS = 100000
_DEVELOPMENT_SPLITS = ("train", "validation")
_TERMINAL_STATUSES = (
    "quarantined", "deduplicated", "student_quarantined", "student_deduplicated",
    "outside_domain", "outside_development_splits",
    "missing_384_input", "non_unit_384_input", "missing_768_receipt", "paired",
)


def _load_corpus_module():
    path = Path(__file__).with_name("gte_multilingual_corpus.py")
    spec = importlib.util.spec_from_file_location("_gte_bridge_multilingual_corpus", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the multilingual corpus contract")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_CORPUS = _load_corpus_module()
_AUDIT = _CORPUS._AUDIT
PROFILE_ID = _CORPUS.PROFILE_ID


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _excluded(binding, status, reasons, task_id=None):
    return {
        "source_id": binding["id"], "task_id": task_id,
        "domain_id": binding["domain_id"], "split": binding["split"],
        "row_sha256": binding["row_sha256"],
        "source_sha256": binding["source_sha256"],
        "component_sha256": binding["component_sha256"],
        "status": status, "reasons": sorted(set(reasons)),
    }


def prepare_bridge_pairs(rows_384, corpus_audit, tasks_manifest, receipts_768,
                         *, domain_id="legal_ir", max_rows=4096):
    """Bind normalized 384D archive vectors to same-source 768D receipts.

    ``ready`` describes complete pair coverage for the selected domain's
    retained development train/validation tasks, not training authorization.
    ``partial`` has usable declared pairs and incomplete selected coverage;
    ``unavailable`` has no pairs. Quarantined, duplicate, other-domain and
    test/canary rows stay explicitly accounted without rewriting any split.

    Receipts for any task in the complete manifest may be supplied, but all are
    validated before domain selection. Unknown, duplicate or inconsistent
    receipts raise ``ValueError``. Missing receipts never trigger a fallback.
    Teacher predictions can supply vector-alignment pairs; they cannot count
    as reference supervision. Neither source text nor target payloads appear
    in the returned neural inputs. A second complete geometry audit detects
    new 768D vector collisions before pairs are admitted. Its quarantine and
    deduplication decisions supplement the original 384D audit; no old
    quarantine is cleared and no source or split is rewritten.
    """
    if (isinstance(max_rows, bool) or not isinstance(max_rows, int)
            or not 1 <= max_rows <= _MAX_ROWS):
        raise ValueError("max_rows must be an integer between 1 and 100000")
    if not isinstance(domain_id, str) or domain_id not in _AUDIT.DOMAINS:
        raise ValueError("domain_id must be a supported logic IR domain")
    rows = _CORPUS._bounded_rows(rows_384, max_rows, label="rows_384")
    recomputed_tasks = _CORPUS.prepare_embedding_tasks(rows, corpus_audit, max_rows=max_rows)
    if (not isinstance(tasks_manifest, dict) or not _AUDIT._json_value(tasks_manifest)
            or _raw(tasks_manifest) != _raw(recomputed_tasks)):
        raise ValueError("tasks_manifest does not exactly match the complete audited rows")
    receipts = _CORPUS._bounded_rows(receipts_768, max_rows, label="receipts_768")
    bound = _CORPUS.bind_embedding_receipts(recomputed_tasks, receipts)

    tasks = recomputed_tasks["tasks"]
    tasks_by_row = {task["metadata"]["row_sha256"]: task for task in tasks}
    bound_by_id = {item["id"]: item for item in bound["bound_rows"]}
    originals = {}
    for row in rows:
        if isinstance(row, dict):
            row_sha256 = _AUDIT._json_digest(row)
            if row_sha256 is not None:
                originals[row_sha256] = row
    student_rows = []
    for row in rows:
        if not isinstance(row, dict):
            student_rows.append(row)
            continue
        task = tasks_by_row.get(_AUDIT._json_digest(row))
        receipt_row = bound_by_id.get(task["id"]) if task else None
        # Replace only the coordinate payload. The auditor receives the same
        # source, reference, grouping and split declarations as the archive.
        student_rows.append({**row, "embedding": receipt_row["embedding"] if receipt_row else None})
    student_audit = _AUDIT.audit_transfer_rows(
        student_rows, dimension=768, vector_space_id=PROFILE_ID, max_rows=max_rows,
    )
    student_by_id = {item["id"]: item for item in student_audit["rows"]}
    selected_tasks = [task for task in tasks if task["metadata"]["domain_id"] == domain_id]
    development_tasks = [task for task in selected_tasks
                         if task["metadata"]["split"] in _DEVELOPMENT_SPLITS
                         and task["metadata"]["evaluation_role"] == "development"]
    pairs = []
    excluded_rows = []
    terminal_counts = Counter({name: 0 for name in _TERMINAL_STATUSES})
    exclusion_reasons = Counter()
    eligible_ids = []
    missing_pair_ids = []

    for binding in corpus_audit["rows"]:
        task = tasks_by_row.get(binding["row_sha256"])
        task_id = task["id"] if task else None
        status = None
        reasons = []
        if binding["quarantined"]:
            status = "quarantined"
            reasons = list(binding["quarantine_reasons"])
            if binding["deduplicated"]:
                reasons.append("deduplicated")
        elif binding["deduplicated"]:
            status, reasons = "deduplicated", ["deduplicated"]
        elif student_by_id[binding["id"]]["quarantined"]:
            status = "student_quarantined"
            reasons = ["student_geometry:" + reason for reason in
                       student_by_id[binding["id"]]["quarantine_reasons"]]
        elif student_by_id[binding["id"]]["deduplicated"]:
            status, reasons = "student_deduplicated", ["student_geometry:deduplicated"]
        elif binding["domain_id"] != domain_id:
            status, reasons = "outside_domain", ["domain_filtered"]
        elif (binding["split"] not in _DEVELOPMENT_SPLITS
              or binding["evaluation_role"] != "development"):
            status, reasons = "outside_development_splits", ["not_development_train_or_validation"]
        else:
            if task is None:
                # A fully recomputed audit cannot retain a valid source without
                # its exact task; fail closed if helper contracts ever disagree.
                raise ValueError("retained development row has no exact source task")
            original = originals.get(binding["row_sha256"])
            if original is None:
                raise ValueError("audited development row has no exact archive binding")
            vector, vector_error = _AUDIT._vector(original["embedding"], 384)
            if vector_error:
                raise ValueError("retained development row has an invalid 384D vector")
            if vector is None:
                status, reasons = "missing_384_input", ["missing_384_input"]
            else:
                norm = math.hypot(*vector)
                if not math.isfinite(norm) or abs(norm - 1.0) > UNIT_NORM_TOLERANCE:
                    status, reasons = "non_unit_384_input", ["source_embedding_not_unit_normalized"]
            if status is None:
                eligible_ids.append(task_id)
                receipt_row = bound_by_id.get(task_id)
                if receipt_row is None:
                    status, reasons = "missing_768_receipt", ["missing_768_receipt"]
                    missing_pair_ids.append(task_id)
                else:
                    metadata = task["metadata"]
                    receipt = receipt_row["embedding_receipt"]
                    pairs.append({
                        "task_id": task_id, "source_id": metadata["source_id"],
                        "source_sha256": task["source_sha256"],
                        "student_component_sha256": student_by_id[binding["id"]]["component_sha256"],
                        **{field: metadata[field] for field in (
                            "domain_id", "document_id", "group_id", "split",
                            "source_language", "evaluation_role", "row_sha256",
                            "component_sha256", "reference_target_sha256", "target_origin",
                        )},
                        "reference_supervision_eligible": binding["has_reference_target"],
                        "source_embedding_384": list(original["embedding"]),
                        "student_embedding_768": list(receipt_row["embedding"]),
                        "source_vector_space_id": corpus_audit["profile"]["vector_space_id"],
                        "student_profile_id": PROFILE_ID,
                        "student_receipt_sha256": receipt["receipt_sha256"],
                        "asset_manifest_sha256": receipt["asset_manifest_sha256"],
                    })
                    status = "paired"
            elif task_id not in bound_by_id:
                reasons.append("missing_768_receipt")
        terminal_counts[status] += 1
        if status != "paired":
            excluded_rows.append(_excluded(binding, status, reasons, task_id))
            exclusion_reasons.update(reasons)

    pairs.sort(key=lambda item: item["task_id"])
    excluded_rows.sort(key=_raw)
    coverage_complete = len(pairs) == len(development_tasks)
    status = "ready" if pairs and coverage_complete else "partial" if pairs else "unavailable"
    unavailable_reasons = []
    if not pairs:
        if not development_tasks:
            unavailable_reasons.append("no_selected_domain_development_tasks")
        if terminal_counts["student_quarantined"]:
            unavailable_reasons.append("student_geometry_quarantine")
        if terminal_counts["student_deduplicated"]:
            unavailable_reasons.append("student_geometry_deduplication")
        if terminal_counts["missing_384_input"]:
            unavailable_reasons.append("missing_384_inputs")
        if terminal_counts["non_unit_384_input"]:
            unavailable_reasons.append("non_unit_384_inputs")
        if missing_pair_ids:
            unavailable_reasons.append("missing_768_receipts")
    origin_counts = Counter(pair["target_origin"] for pair in pairs)
    split_counts = {split: sum(pair["split"] == split for pair in pairs)
                    for split in _DEVELOPMENT_SPLITS}
    reference_split_counts = {split: sum(pair["split"] == split
                                        and pair["reference_supervision_eligible"] for pair in pairs)
                              for split in _DEVELOPMENT_SPLITS}
    return {
        "schema": SCHEMA, "status": status, "domain_id": domain_id,
        "source_dimension": 384, "student_dimension": 768,
        "source_vector_space_id": corpus_audit["profile"]["vector_space_id"],
        "student_profile_id": PROFILE_ID,
        "corpus_inventory_sha256": corpus_audit["inventory_sha256"],
        "student_geometry_inventory_sha256": student_audit["inventory_sha256"],
        "student_geometry_audit": student_audit,
        "tasks_sha256": recomputed_tasks["tasks_sha256"],
        "tasks_manifest_sha256": _digest(recomputed_tasks),
        "embedding_binding_sha256": bound["binding_sha256"],
        "asset_manifest_sha256": bound["asset_manifest_sha256"],
        "pairs_sha256": _digest(pairs), "pairs": pairs,
        "split_counts": split_counts,
        "reference_supervision_split_counts": reference_split_counts,
        "pair_target_origin_counts": {origin: origin_counts[origin] for origin in _AUDIT.TARGET_ORIGINS},
        "counts": {
            "archive_rows": len(rows),
            "archive_quarantined_rows": corpus_audit["quarantined_row_count"],
            "archive_deduplicated_rows": corpus_audit["deduplicated_row_count"],
            "archive_teacher_prediction_rows": corpus_audit["target_origin_counts"]["teacher_prediction"],
            "student_geometry_quarantined_rows": student_audit["quarantined_row_count"],
            "student_geometry_deduplicated_rows": student_audit["deduplicated_row_count"],
            "source_tasks": len(tasks),
            "source_task_rejected_rows": recomputed_tasks["rejected_row_count"],
            "selected_domain_archive_rows": corpus_audit["domain_counts"][domain_id],
            "selected_domain_tasks": len(selected_tasks),
            "other_domain_tasks": len(tasks) - len(selected_tasks),
            "selected_domain_development_tasks": len(development_tasks),
            "selected_domain_non_development_tasks": len(selected_tasks) - len(development_tasks),
            "eligible_pair_tasks": len(eligible_ids),
            "supplied_receipts": len(receipts),
            "bound_receipts": bound["accepted_count"],
            "missing_receipts": len(bound["missing_receipt_ids"]),
            "missing_eligible_pair_receipts": len(missing_pair_ids),
            "pairs": len(pairs),
            "reference_supervision_pairs": sum(reference_split_counts.values()),
            "teacher_prediction_pairs": origin_counts["teacher_prediction"],
            "unlabeled_pairs": origin_counts["unlabeled"],
        },
        "terminal_row_counts": dict(terminal_counts),
        "excluded_rows": excluded_rows,
        "exclusion_reason_counts": dict(sorted(exclusion_reasons.items())),
        "missing_receipt_ids": bound["missing_receipt_ids"],
        "missing_eligible_pair_receipt_ids": sorted(missing_pair_ids),
        "unavailable_reasons": unavailable_reasons,
        "coverage_scope": "selected_domain_retained_development_train_validation_tasks",
        "neural_input_fields": ["student_embedding_768"],
        "alignment_target_fields": ["source_embedding_384"],
        "unit_norm_tolerance": UNIT_NORM_TOLERANCE,
        "split_memberships_changed": False, "reference_targets_exported": False,
        "source_text_exported": False, "target_semantics_verified": False,
        "source_vectors_producer_verified": False,
        "student_vectors_producer_verified": False,
        "student_model_numerics_verified": False,
        "tokenization_producer_verified": False,
        "teacher_qualified": False, "training_performed": False,
        "training_authorized": False, "proof_authority": False,
    }
