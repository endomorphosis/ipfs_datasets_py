"""Synthetic bridge content/geometry checks; no model inference or training."""
from copy import deepcopy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import subprocess
import sys
import unittest


_PATH = Path(__file__).resolve().parents[5] / "ipfs_datasets_py/logic/formalization/autoencoder/gte_bridge_pairs.py"
_SPEC = importlib.util.spec_from_file_location("gte_bridge_pairs_under_test", _PATH)
subject = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(subject)


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def row(name="a", **changes):
    # Different directions avoid the auditor's global vector identity grouping.
    angle = (sum(map(ord, name)) % 300) / 100.0
    result = {
        "id": name, "domain_id": "legal_ir", "document_id": "doc:" + name,
        "group_id": "group:" + name, "split": "train", "source_text": "Source " + name,
        "embedding": [math.cos(angle), math.sin(angle)] + [0.0] * 382,
        "reference_target": {"native_reference": name}, "target_origin": "authored",
        "source_language": "en", "evaluation_role": "development",
    }
    result.update(changes)
    return result


def audit(rows):
    return subject._AUDIT.audit_transfer_rows(
        rows, vector_space_id="synthetic-declared-gte-small-384/v1",
    )


def tasks(rows, report=None):
    return subject._CORPUS.prepare_embedding_tasks(rows, report or audit(rows))


def receipt(task, **changes):
    angle = int(hashlib.sha256(task["id"].encode()).hexdigest()[:12], 16) / (16 ** 12)
    result = {
        "schema": subject._CORPUS.RECEIPT_SCHEMA, "id": task["id"],
        "source_sha256": task["source_sha256"], "profile_id": subject.PROFILE_ID,
        "dimension": 768, "embedding": [math.cos(angle), math.sin(angle)] + [0.0] * 766,
        "token_count_including_special_tokens": 17, "token_input_sha256": "a" * 64,
        "truncated": False, "normalized": True, "asset_manifest_sha256": "b" * 64,
    }
    result.update(changes)
    return result


def prepare(rows, receipts=None, **kwargs):
    report = audit(rows)
    manifest = tasks(rows, report)
    supplied = [receipt(task) for task in manifest["tasks"]] if receipts is None else receipts
    return subject.prepare_bridge_pairs(rows, report, manifest, supplied, **kwargs)


class BridgePairContractTests(unittest.TestCase):
    def test_ready_pairs_preserve_exact_source_metadata_and_vector_payloads(self):
        rows = [row("a"), row("b", split="validation", source_language="fr")]
        manifest = tasks(rows)
        receipts = [receipt(task) for task in manifest["tasks"]]
        report = subject.prepare_bridge_pairs(rows, audit(rows), manifest, receipts)
        self.assertEqual(report["schema"], subject.SCHEMA)
        self.assertEqual(report["status"], "ready")
        self.assertEqual(report["split_counts"], {"train": 1, "validation": 1})
        self.assertEqual(report["reference_supervision_split_counts"], {"train": 1, "validation": 1})
        self.assertEqual(report["pairs_sha256"], hashlib.sha256(raw(report["pairs"])).hexdigest())
        by_id = {original["id"]: original for original in rows}
        by_task = {task["id"]: task for task in manifest["tasks"]}
        by_receipt = {item["id"]: item for item in receipts}
        for pair in report["pairs"]:
            original = by_id[pair["source_id"]]
            task = by_task[pair["task_id"]]
            for field in ("domain_id", "document_id", "group_id", "split", "target_origin",
                          "source_language", "evaluation_role"):
                self.assertEqual(pair[field], original[field])
            for field in ("row_sha256", "component_sha256", "reference_target_sha256"):
                self.assertEqual(pair[field], task["metadata"][field])
            self.assertEqual(pair["source_sha256"], task["source_sha256"])
            self.assertEqual(pair["source_embedding_384"], original["embedding"])
            self.assertEqual(pair["student_embedding_768"], by_receipt[pair["task_id"]]["embedding"])
            self.assertEqual(pair["student_receipt_sha256"],
                             hashlib.sha256(raw(by_receipt[pair["task_id"]])).hexdigest())
            self.assertEqual(pair["student_profile_id"], subject.PROFILE_ID)
            self.assertEqual(pair["asset_manifest_sha256"], "b" * 64)
            self.assertTrue(pair["reference_supervision_eligible"])
        self.assertEqual(report["counts"]["pairs"], 2)
        self.assertEqual(sum(report["terminal_row_counts"].values()), len(rows))

    def test_returned_content_excludes_raw_text_reference_ir_and_execution_claims(self):
        rows = [row(source_text="SOURCE_TEXT_SECRET", reference_target={"secret": "IR_ONLY_SECRET"})]
        result = prepare(rows)
        encoded = json.dumps(result)
        self.assertNotIn("SOURCE_TEXT_SECRET", encoded)
        self.assertNotIn("IR_ONLY_SECRET", encoded)
        self.assertNotIn('"reference_target":', encoded)
        self.assertEqual(result["neural_input_fields"], ["student_embedding_768"])
        self.assertEqual(result["alignment_target_fields"], ["source_embedding_384"])
        for field in ("split_memberships_changed", "reference_targets_exported", "source_text_exported",
                      "target_semantics_verified", "source_vectors_producer_verified",
                      "student_vectors_producer_verified", "student_model_numerics_verified",
                      "tokenization_producer_verified", "teacher_qualified", "training_performed",
                      "training_authorized", "proof_authority"):
            self.assertIs(result[field], False)

    def test_inputs_unchanged_and_outputs_independent_of_order(self):
        rows = [row("a"), row("b", split="validation")]
        report, manifest = audit(rows), tasks(rows)
        receipts = [receipt(task) for task in manifest["tasks"]]
        before = deepcopy((rows, report, manifest, receipts))
        first = subject.prepare_bridge_pairs(rows, report, manifest, receipts)
        second = subject.prepare_bridge_pairs(iter(reversed(rows)), report, manifest, reversed(receipts))
        self.assertEqual(first, second)
        self.assertEqual((rows, report, manifest, receipts), before)
        rows[0]["embedding"][0] = 999
        receipts[0]["embedding"][0] = 999
        manifest["tasks"][0]["metadata"]["source_id"] = "changed"
        self.assertNotIn(999, first["pairs"][0]["source_embedding_384"])
        self.assertNotIn(999, first["pairs"][0]["student_embedding_768"])

    def test_no_receipts_is_unavailable_and_does_not_fabricate_vectors(self):
        rows = [row("a"), row("b", split="validation")]
        result = prepare(rows, [])
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["pairs"], [])
        self.assertEqual(result["counts"]["missing_eligible_pair_receipts"], 2)
        self.assertEqual(result["counts"]["eligible_pair_tasks"], 2)
        self.assertEqual(result["terminal_row_counts"]["missing_768_receipt"], 2)
        self.assertEqual(result["unavailable_reasons"], ["missing_768_receipts"])
        self.assertEqual(set(result["missing_receipt_ids"]),
                         set(result["missing_eligible_pair_receipt_ids"]))

    def test_partial_coverage_keeps_only_declared_receipt_pairs(self):
        rows = [row("a"), row("b", split="validation")]
        manifest = tasks(rows)
        result = prepare(rows, [receipt(manifest["tasks"][0])])
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["counts"]["pairs"], 1)
        self.assertEqual(result["counts"]["missing_eligible_pair_receipts"], 1)
        self.assertEqual(result["pairs"][0]["task_id"], manifest["tasks"][0]["id"])
        self.assertEqual(result["excluded_rows"][0]["reasons"], ["missing_768_receipt"])

    def test_domain_selection_is_separate_from_quarantine_and_global_missing_receipts(self):
        rows = [row("a"), row("b", domain_id="security_ir")]
        manifest = tasks(rows)
        legal = next(task for task in manifest["tasks"] if task["metadata"]["domain_id"] == "legal_ir")
        result = prepare(rows, [receipt(legal)])
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["counts"]["source_tasks"], 2)
        self.assertEqual(result["counts"]["other_domain_tasks"], 1)
        self.assertEqual(result["counts"]["missing_receipts"], 1)
        self.assertEqual(result["counts"]["missing_eligible_pair_receipts"], 0)
        self.assertEqual(result["terminal_row_counts"]["outside_domain"], 1)
        self.assertEqual(result["terminal_row_counts"]["quarantined"], 0)
        self.assertEqual(result["excluded_rows"][0]["reasons"], ["domain_filtered"])
        security = prepare(rows, domain_id="security_ir")
        self.assertEqual(security["pairs"][0]["domain_id"], "security_ir")

    def test_test_canary_and_sealed_rows_never_supply_pairs(self):
        rows = [row("a"), row("b", split="test", evaluation_role="sealed"),
                row("c", split="canary"), row("d", split="test")]
        result = prepare(rows)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["counts"]["pairs"], 1)
        self.assertEqual(result["counts"]["selected_domain_non_development_tasks"], 3)
        self.assertEqual(result["terminal_row_counts"]["outside_development_splits"], 3)
        self.assertEqual({item["split"] for item in result["excluded_rows"]}, {"test", "canary"})

    def test_new_student_cross_split_vector_collision_is_quarantined(self):
        rows = [row("a"), row("b", split="validation")]
        manifest = tasks(rows)
        receipts = [receipt(task, embedding=[1.0] + [0.0] * 767) for task in manifest["tasks"]]
        result = prepare(rows, receipts)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["pairs"], [])
        self.assertEqual(result["counts"]["archive_quarantined_rows"], 0)
        self.assertEqual(result["counts"]["student_geometry_quarantined_rows"], 2)
        self.assertEqual(result["terminal_row_counts"]["student_quarantined"], 2)
        self.assertEqual(result["exclusion_reason_counts"]["student_geometry:cross_split_connected_component"], 2)
        self.assertEqual(result["student_geometry_inventory_sha256"],
                         result["student_geometry_audit"]["inventory_sha256"])
        self.assertEqual(result["student_geometry_audit"]["profile"]["dimension"], 768)
        self.assertEqual({item["split"] for item in result["excluded_rows"]}, {"train", "validation"})
        self.assertIn("student_geometry_quarantine", result["unavailable_reasons"])

    def test_new_student_same_split_conflicting_reference_collision_is_quarantined(self):
        rows = [row("a"), row("b")]
        manifest = tasks(rows)
        receipts = [receipt(task, embedding=[1.0] + [0.0] * 767) for task in manifest["tasks"]]
        result = prepare(rows, receipts)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["counts"]["reference_supervision_pairs"], 0)
        self.assertEqual(result["exclusion_reason_counts"]["student_geometry:contradictory_reference_targets"], 2)
        self.assertEqual(result["terminal_row_counts"]["student_quarantined"], 2)

    def test_student_numeric_int_float_and_signed_zero_identity_is_exact(self):
        rows = [row("a"), row("b", split="validation")]
        manifest = tasks(rows)
        receipts = [receipt(manifest["tasks"][0], embedding=[1] + [0] * 767),
                    receipt(manifest["tasks"][1], embedding=[1.0, -0.0] + [0.0] * 766)]
        result = prepare(rows, receipts)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["terminal_row_counts"]["student_quarantined"], 2)
        self.assertEqual(len({item["numeric_vector_sha256"] for item in
                              result["student_geometry_audit"]["rows"]}), 1)

    def test_student_collision_quarantine_propagates_through_document_components(self):
        rows = [row("a"), row("b", document_id="doc:a"), row("c", split="validation")]
        manifest = tasks(rows)
        receipts = [receipt(task, embedding=[1.0] + [0.0] * 767)
                    if task["metadata"]["source_id"] in ("a", "c") else receipt(task)
                    for task in manifest["tasks"]]
        result = prepare(rows, receipts)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["terminal_row_counts"]["student_quarantined"], 3)
        self.assertEqual(result["exclusion_reason_counts"]["student_geometry:cross_split_connected_component"], 3)

    def test_same_split_student_duplicates_with_same_reference_have_one_pair(self):
        rows = [row("a", reference_target={"reference": "same"}),
                row("b", reference_target={"reference": "same"})]
        manifest = tasks(rows)
        receipts = [receipt(task, embedding=[1.0] + [0.0] * 767) for task in manifest["tasks"]]
        result = prepare(rows, receipts)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["counts"]["pairs"], 1)
        self.assertEqual(result["terminal_row_counts"]["student_deduplicated"], 1)
        self.assertEqual(result["counts"]["student_geometry_deduplicated_rows"], 1)

    def test_student_collision_with_other_domain_is_globally_accounted(self):
        rows = [row("a"), row("b", domain_id="security_ir", split="validation")]
        manifest = tasks(rows)
        receipts = [receipt(task, embedding=[1.0] + [0.0] * 767) for task in manifest["tasks"]]
        result = prepare(rows, receipts)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["terminal_row_counts"]["student_quarantined"], 2)
        self.assertEqual(result["counts"]["other_domain_tasks"], 1)
        self.assertEqual(result["counts"]["student_geometry_quarantined_rows"], 2)

    def test_cross_split_components_preserve_whole_archive_quarantine(self):
        rows = [row("a"), row("b", split="test", group_id="group:a"), row("c")]
        result = prepare(rows)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["counts"]["archive_quarantined_rows"], 2)
        self.assertEqual(result["counts"]["source_task_rejected_rows"], 2)
        self.assertEqual(result["terminal_row_counts"]["quarantined"], 2)
        self.assertEqual(result["pairs"][0]["source_id"], "c")
        self.assertEqual(result["exclusion_reason_counts"]["cross_split_connected_component"], 2)
        self.assertEqual(sum(result["terminal_row_counts"].values()), 3)

    def test_deduplicated_sources_are_excluded_and_do_not_add_pairs(self):
        rows = [row("a", source_text="same", reference_target={"target": "same"}),
                row("b", source_text="same", reference_target={"target": "same"})]
        result = prepare(rows)
        self.assertEqual(result["counts"]["pairs"], 1)
        self.assertEqual(result["terminal_row_counts"]["deduplicated"], 1)
        self.assertEqual(result["counts"]["archive_deduplicated_rows"], 1)

    def test_invalid_archive_rows_remain_accounted_without_bridge_inputs(self):
        rows = [row("a"), row("b", embedding=[True] + [0.0] * 383), None]
        result = prepare(rows)
        self.assertEqual(result["counts"]["archive_rows"], 3)
        self.assertEqual(result["counts"]["pairs"], 1)
        self.assertEqual(result["terminal_row_counts"]["quarantined"], 2)
        self.assertEqual(len(result["excluded_rows"]), 2)

    def test_missing_384_vector_is_excluded_without_creating_or_normalizing_it(self):
        rows = [row("a"), row("b", embedding=None)]
        result = prepare(rows)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["terminal_row_counts"]["missing_384_input"], 1)
        self.assertEqual(result["counts"]["eligible_pair_tasks"], 1)
        self.assertEqual(result["counts"]["selected_domain_development_tasks"], 2)
        self.assertEqual(result["counts"]["bound_receipts"], 2)
        self.assertEqual(result["excluded_rows"][0]["reasons"], ["missing_384_input"])

    def test_non_unit_384_vector_is_excluded_instead_of_renormalized(self):
        rows = [row("a"), row("b", embedding=[2.0] + [0.0] * 383)]
        result = prepare(rows)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["terminal_row_counts"]["non_unit_384_input"], 1)
        self.assertEqual(result["excluded_rows"][0]["reasons"], ["source_embedding_not_unit_normalized"])
        self.assertEqual(rows[1]["embedding"][0], 2.0)

    def test_384_norm_tolerance_and_overflow_boundary(self):
        for norm, allowed in ((1.0 + 0.999e-4, True), (1.0 + 1.001e-4, False),
                              (0.0, False), (1e308, False)):
            with self.subTest(norm=norm):
                result = prepare([row(embedding=[norm] + [0.0] * 383)])
                self.assertEqual(result["counts"]["pairs"], int(allowed))
                self.assertEqual(result["status"], "ready" if allowed else "unavailable")

    def test_all_missing_384_inputs_and_missing_receipts_are_both_accounted(self):
        result = prepare([row(embedding=None)], [])
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["unavailable_reasons"], ["missing_384_inputs"])
        self.assertEqual(result["counts"]["missing_receipts"], 1)
        self.assertEqual(result["counts"]["missing_eligible_pair_receipts"], 0)
        self.assertEqual(result["excluded_rows"][0]["reasons"], ["missing_384_input", "missing_768_receipt"])

    def test_teacher_predictions_and_unlabeled_vectors_do_not_count_as_references(self):
        rows = [row("a", target_origin="teacher_prediction"),
                row("b", target_origin="unlabeled", reference_target=None),
                row("c", target_origin="compiler_weak", split="validation"),
                row("d", target_origin="independently_checked", split="validation")]
        result = prepare(rows)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["counts"]["pairs"], 4)
        self.assertEqual(result["counts"]["teacher_prediction_pairs"], 1)
        self.assertEqual(result["counts"]["unlabeled_pairs"], 1)
        self.assertEqual(result["counts"]["reference_supervision_pairs"], 2)
        self.assertEqual(result["reference_supervision_split_counts"], {"train": 0, "validation": 2})
        for pair in result["pairs"]:
            if pair["target_origin"] in ("teacher_prediction", "unlabeled"):
                self.assertIs(pair["reference_supervision_eligible"], False)

    def test_empty_or_absent_selected_domain_is_explicitly_unavailable(self):
        for rows in ([], [row(domain_id="security_ir")], [row(split="test")]):
            result = prepare(rows)
            self.assertEqual(result["status"], "unavailable")
            self.assertEqual(result["pairs"], [])
            self.assertEqual(result["unavailable_reasons"], ["no_selected_domain_development_tasks"])

    def test_stale_complete_audit_or_row_subset_superset_is_rejected(self):
        rows = [row("a"), row("b", split="validation")]
        report, manifest = audit(rows), tasks(rows)
        for changed in (rows[:1], rows + [row("c")],
                        [row("a", group_id="changed"), rows[1]],
                        [row("a", source_text="changed"), rows[1]],
                        [row("a", reference_target={"changed": True}), rows[1]]):
            with self.subTest(changed=changed):
                with self.assertRaisesRegex(ValueError, "complete rows"):
                    subject.prepare_bridge_pairs(changed, report, manifest, [])

    def test_modified_task_manifest_fields_counts_flags_scope_or_content_rejected(self):
        rows = [row()]
        report, manifest = audit(rows), tasks(rows)
        changes = (
            lambda value: value.update(task_count=100),
            lambda value: value.update(embeddings_generated=True),
            lambda value: value.update(unexpected="field"),
            lambda value: value.update(tasks_sha256="0" * 64),
            lambda value: value["tasks"][0]["metadata"].update(split="validation"),
            lambda value: value["tasks"][0].update(source_text="changed"),
        )
        for change in changes:
            modified = deepcopy(manifest)
            change(modified)
            with self.assertRaisesRegex(ValueError, "tasks_manifest"):
                subject.prepare_bridge_pairs(rows, report, modified, [])
        for invalid in (None, [], {"bad": float("nan")}):
            with self.assertRaises(ValueError):
                subject.prepare_bridge_pairs(rows, report, invalid, [])

    def test_invalid_or_inconsistent_receipt_declared_vectors_are_rejected(self):
        rows = [row()]
        manifest = tasks(rows)
        task = manifest["tasks"][0]
        changes = (
            {"source_sha256": "c" * 64}, {"profile_id": "different-profile"},
            {"dimension": 384}, {"embedding": [1.0] + [0.0] * 383},
            {"embedding": [2.0] + [0.0] * 767},
            {"embedding": [True] + [0.0] * 767},
            {"embedding": [float("nan")] + [0.0] * 767},
            {"truncated": True}, {"normalized": False},
            {"token_count_including_special_tokens": 8193},
            {"asset_manifest_sha256": "bad"}, {"unexpected": True},
        )
        for change in changes:
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    prepare(rows, [receipt(task, **change)])

    def test_invalid_receipt_on_filtered_domain_is_still_rejected(self):
        rows = [row("a"), row("b", domain_id="security_ir")]
        manifest = tasks(rows)
        receipts = [receipt(task, normalized=False if task["metadata"]["domain_id"] == "security_ir" else True)
                    for task in manifest["tasks"]]
        with self.assertRaises(ValueError):
            prepare(rows, receipts)

    def test_duplicate_unknown_and_mixed_asset_receipts_are_rejected(self):
        rows = [row("a"), row("b")]
        manifest = tasks(rows)
        receipts = [receipt(task) for task in manifest["tasks"]]
        for supplied in ([receipts[0], receipts[0]],
                         [receipt(manifest["tasks"][0], id="unexpected")],
                         [receipts[0], receipt(manifest["tasks"][1], asset_manifest_sha256="c" * 64)]):
            with self.assertRaises(ValueError):
                prepare(rows, supplied)

    def test_invalid_parameters_and_unbounded_inputs_are_rejected(self):
        rows = [row("a"), row("b")]
        report, manifest = audit(rows), tasks(rows)
        for limit in (True, 0, -1, 1.5, 100001):
            with self.assertRaises(ValueError):
                subject.prepare_bridge_pairs(rows, report, manifest, [], max_rows=limit)
        with self.assertRaises(ValueError):
            subject.prepare_bridge_pairs(rows, report, manifest, [], max_rows=1)
        for domain in (None, "invalid", [], True):
            with self.assertRaises(ValueError):
                subject.prepare_bridge_pairs(rows, report, manifest, [], domain_id=domain)
        for invalid in (None, "rows", b"rows", {}):
            with self.assertRaises(ValueError):
                subject.prepare_bridge_pairs(invalid, report, manifest, [])
            with self.assertRaises(ValueError):
                subject.prepare_bridge_pairs(rows, report, manifest, invalid)

    def test_import_does_not_load_torch_transformers_or_package_initializers(self):
        code = (
            "import importlib.util, sys; "
            "spec = importlib.util.spec_from_file_location('isolated_bridge', sys.argv[1]); "
            "module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); "
            "assert 'torch' not in sys.modules; assert 'transformers' not in sys.modules; "
            "assert 'ipfs_datasets_py' not in sys.modules"
        )
        completed = subprocess.run([sys.executable, "-I", "-c", code, str(_PATH)],
                                   check=False, capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
