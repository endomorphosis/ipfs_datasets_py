"""Bounded source-coordinate preparation tests; no model execution or fitting."""
from copy import deepcopy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import subprocess
import sys
import unittest


_PATH = Path(__file__).resolve().parents[5] / "ipfs_datasets_py/logic/formalization/autoencoder/gte_alignment_contract.py"
_SPEC = importlib.util.spec_from_file_location("gte_alignment_contract_under_test", _PATH)
subject = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(subject)


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(raw(value)).hexdigest()


def row(name, **changes):
    angle = int(hashlib.sha256(name.encode()).hexdigest()[:12], 16) / (16 ** 12)
    result = {
        "id": name, "domain_id": "legal_ir", "document_id": "doc:" + name,
        "group_id": "group:" + name, "split": "train", "source_text": "Source " + name,
        "embedding": [math.cos(angle), math.sin(angle)] + [0.0] * 382,
        "reference_target": {"native_reference": name}, "target_origin": "authored",
        "source_language": "en", "evaluation_role": "development",
    }
    result.update(changes)
    return result


def receipt(task):
    angle = int(hashlib.sha256(task["id"].encode()).hexdigest()[:12], 16) / (16 ** 12)
    return {
        "schema": subject._BRIDGE._CORPUS.RECEIPT_SCHEMA, "id": task["id"],
        "source_sha256": task["source_sha256"], "profile_id": subject._BRIDGE.PROFILE_ID,
        "dimension": 768, "embedding": [math.cos(angle), math.sin(angle)] + [0.0] * 766,
        "token_count_including_special_tokens": 17, "token_input_sha256": "a" * 64,
        "truncated": False, "normalized": True, "asset_manifest_sha256": "b" * 64,
    }


def pairs(rows=None, receipts=True):
    rows = rows if rows is not None else [row("train-a"), row("train-b"), row("validation", split="validation")]
    audit = subject._AUDIT.audit_transfer_rows(rows, vector_space_id="synthetic-declared-gte-small-384/v1")
    tasks = subject._BRIDGE._CORPUS.prepare_embedding_tasks(rows, audit)
    supplied = [receipt(task) for task in tasks["tasks"]] if receipts else []
    return subject._BRIDGE.prepare_bridge_pairs(rows, audit, tasks, supplied)


def resign_pairs(manifest):
    manifest["pairs_sha256"] = digest(manifest["pairs"])
    return manifest


def resign_plan(plan):
    plan["train_rows_sha256"] = digest(plan["train_rows"])
    plan["validation_rows_sha256"] = digest(plan["validation_rows"])
    plan["pairs_sha256"] = digest(sorted(plan["train_rows"] + plan["validation_rows"], key=lambda item: item["task_id"]))
    plan["plan_sha256"] = digest({key: value for key, value in plan.items() if key != "plan_sha256"})
    return plan


class AlignmentPreparationTests(unittest.TestCase):
    def test_ready_plan_separates_fitting_and_validation_and_keeps_pins(self):
        manifest = pairs()
        plan = subject.prepare_alignment_plan(manifest)
        self.assertEqual(plan["schema"], subject.SCHEMA)
        self.assertEqual(plan["status"], "ready")
        self.assertIs(plan["fit_ready"], True)
        self.assertEqual(plan["selection_policy"], "development_validation_mse")
        self.assertEqual(plan["regularization_candidates"], [.001, .01, .1])
        self.assertEqual(len(plan["train_rows"]), 2)
        self.assertEqual(len(plan["validation_rows"]), 1)
        self.assertEqual(plan["counts"]["selected_fit_rows"], 2)
        self.assertEqual(plan["counts"]["selected_validation_rows"], 1)
        self.assertEqual(plan["pairs_manifest_sha256"], digest(manifest))
        for key in subject._PIN_FIELDS:
            self.assertEqual(plan[key], manifest[key])
        self.assertEqual(plan["plan_sha256"], digest({key: value for key, value in plan.items() if key != "plan_sha256"}))
        self.assertEqual(subject.inspect_alignment_plan(plan)["plan_sha256"], plan["plan_sha256"])

    def test_inputs_unchanged_and_copied_vectors_are_independent(self):
        manifest = pairs()
        before = deepcopy(manifest)
        plan = subject.prepare_alignment_plan(manifest)
        self.assertEqual(manifest, before)
        plan["train_rows"][0]["source_embedding_384"][0] = 999
        plan["train_rows"][0]["student_embedding_768"][0] = 999
        self.assertEqual(manifest, before)

    def test_no_text_targets_teacher_gates_or_execution_claims(self):
        manifest = pairs([row("train-a", source_text="SECRET_ONE", reference_target={"secret": "TARGET_SECRET"}),
                          row("train-b"), row("validation", split="validation")])
        plan = subject.prepare_alignment_plan(manifest)
        encoded = json.dumps(plan)
        self.assertNotIn("SECRET_ONE", encoded)
        self.assertNotIn("TARGET_SECRET", encoded)
        self.assertNotIn('"reference_target":', encoded)
        for key in subject._FALSE_FIELDS | {"teacher_qualification_required", "donor_checkpoint_required", "producer_authenticity_verified"}:
            self.assertIs(plan[key], False)

    def test_teacher_predictions_and_unlabeled_vectors_can_align_without_becoming_references(self):
        manifest = pairs([row("train-a", target_origin="teacher_prediction"),
                          row("train-b", target_origin="unlabeled", reference_target=None),
                          row("validation", split="validation")])
        plan = subject.prepare_alignment_plan(manifest)
        self.assertTrue(plan["fit_ready"])
        self.assertEqual(plan["counts"]["teacher_prediction_pairs"], 1)
        self.assertEqual(plan["counts"]["unlabeled_pairs"], 1)
        self.assertEqual(plan["counts"]["reference_supervision_pairs"], 1)
        self.assertTrue(all(not item["reference_supervision_eligible"] for item in plan["train_rows"]))

    def test_no_real_receipts_returns_structured_unavailable_plan(self):
        manifest = pairs(receipts=False)
        plan = subject.prepare_alignment_plan(manifest)
        self.assertEqual(plan["status"], "unavailable")
        self.assertFalse(plan["fit_ready"])
        self.assertEqual(plan["train_rows"], [])
        self.assertEqual(plan["validation_rows"], [])
        self.assertEqual(plan["counts"]["selected_fit_rows"], 0)
        self.assertEqual(plan["counts"]["selected_validation_rows"], 0)
        self.assertEqual(plan["counts"]["missing_eligible_pair_receipts"], 3)
        self.assertIn("missing_768_receipts", plan["unavailable_reasons"])
        self.assertIsNone(plan["asset_manifest_sha256"])

    def test_multiple_candidates_need_validation_and_fixed_candidate_does_not(self):
        manifest = pairs([row("train-a"), row("train-b")])
        unavailable = subject.prepare_alignment_plan(manifest)
        self.assertFalse(unavailable["fit_ready"])
        self.assertIn("validation_pairs_required_for_candidate_selection", unavailable["unavailable_reasons"])
        self.assertEqual(unavailable["counts"]["selected_fit_rows"], 0)
        fixed = subject.prepare_alignment_plan(manifest, regularization_candidates=(.01,))
        self.assertTrue(fixed["fit_ready"])
        self.assertEqual(fixed["selection_policy"], "fixed_candidate_no_validation")
        self.assertEqual(fixed["counts"]["selected_fit_rows"], 2)

    def test_unavailable_grid_retains_declared_validation_selection_policy(self):
        for manifest in (pairs(receipts=False), pairs([row("train-a"), row("train-b")])):
            plan = subject.prepare_alignment_plan(manifest)
            self.assertEqual(plan["regularization_candidates"], [.001, .01, .1])
            self.assertFalse(plan["fit_ready"])
            self.assertEqual(plan["selection_policy"], "development_validation_mse")
            self.assertIn("validation_pairs_required_for_candidate_selection", plan["unavailable_reasons"])
            self.assertEqual(plan["counts"]["selected_fit_rows"], 0)
            self.assertEqual(subject.inspect_alignment_plan(plan)["selection_policy"], "development_validation_mse")
            # A resigned unavailable plan still cannot invent a fixed candidate
            # policy while retaining a grid with multiple candidates.
            plan["selection_policy"] = "fixed_candidate_no_validation"
            resign_plan(plan)
            with self.assertRaisesRegex(ValueError, "selection policy mismatch"):
                subject.inspect_alignment_plan(plan)

    def test_one_train_pair_is_insufficient_even_with_validation(self):
        plan = subject.prepare_alignment_plan(pairs([row("train-a"), row("validation", split="validation")]))
        self.assertFalse(plan["fit_ready"])
        self.assertIn("at_least_two_distinct_training_pairs_required", plan["unavailable_reasons"])

    def test_existing_quarantine_test_and_canary_are_not_reintroduced(self):
        rows = [row("train-a"), row("train-b"), row("validation", split="validation"),
                row("heldout", split="test", evaluation_role="sealed"),
                row("canary", split="canary"),
                row("leak-one", source_text="Shared source"),
                row("leak-two", source_text="Shared source", split="validation")]
        manifest = pairs(rows)
        plan = subject.prepare_alignment_plan(manifest)
        self.assertTrue(plan["fit_ready"])
        self.assertEqual(plan["counts"]["available_pairs"], 3)
        self.assertEqual(plan["counts"]["excluded_rows"], 4)
        self.assertEqual(plan["counts"]["archive_quarantined_rows"], 2)
        self.assertEqual({item["source_id"] for item in plan["train_rows"] + plan["validation_rows"]},
                         {"train-a", "train-b", "validation"})
        self.assertEqual(plan["excluded_rows_sha256"], digest(manifest["excluded_rows"]))

    def test_repeated_document_inside_training_split_is_permitted(self):
        manifest = pairs([row("train-a", document_id="document-one"),
                          row("train-b", document_id="document-one"),
                          row("validation", split="validation")])
        self.assertTrue(subject.prepare_alignment_plan(manifest)["fit_ready"])

    def test_partial_receipt_coverage_can_use_sufficient_pairs_without_fabricating_missing(self):
        rows = [row("train-a"), row("train-b"), row("validation", split="validation"), row("missing")]
        audit = subject._AUDIT.audit_transfer_rows(rows, vector_space_id="synthetic-declared-gte-small-384/v1")
        tasks = subject._BRIDGE._CORPUS.prepare_embedding_tasks(rows, audit)
        supplied = [receipt(task) for task in tasks["tasks"] if task["metadata"]["source_id"] != "missing"]
        manifest = subject._BRIDGE.prepare_bridge_pairs(rows, audit, tasks, supplied)
        self.assertEqual(manifest["status"], "partial")
        plan = subject.prepare_alignment_plan(manifest)
        self.assertTrue(plan["fit_ready"])
        self.assertEqual(plan["counts"]["available_pairs"], 3)
        self.assertEqual(plan["counts"]["missing_eligible_pair_receipts"], 1)

    def test_bounds_reject_rather_than_truncate_or_resplit(self):
        manifest = pairs()
        with self.assertRaisesRegex(ValueError, "train pairs exceed"):
            subject.prepare_alignment_plan(manifest, max_train_pairs=1)
        for key in ("max_train_pairs", "max_validation_pairs"):
            for value in (0, -1, True, 1.5, 4097, 100000):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    subject.prepare_alignment_plan(manifest, **{key: value})

    def test_candidate_grid_is_bounded_finite_positive_distinct_and_increasing(self):
        for grid in ((), [], (.1, .01), (.01, .01), (True,), (0,), (-1,), (1e-9,), (1e7,),
                     (float("nan"),), (float("inf"),), (10 ** 400,), "0.01", {"a": 1},
                     [1e-8 * (index + 1) for index in range(17)]):
            with self.subTest(grid=grid), self.assertRaises(ValueError):
                subject.prepare_alignment_plan(pairs(), regularization_candidates=grid)
        plan = subject.prepare_alignment_plan(pairs(), regularization_candidates=(1e-8, 1e6))
        self.assertEqual(plan["regularization_candidates"], [1e-8, 1e6])


class AlignmentManifestAdmissionTests(unittest.TestCase):
    def test_closed_top_schema_rejects_missing_extra_and_wrong_schema(self):
        for mutate in (lambda item: item.update({"extra": 1}), lambda item: item.pop("counts"),
                       lambda item: item.update({"schema": "other/v1"})):
            manifest = pairs()
            mutate(manifest)
            with self.assertRaises(ValueError):
                subject.prepare_alignment_plan(manifest)

    def test_pair_digest_is_verified_before_row_admission(self):
        manifest = pairs()
        manifest["pairs"][0]["source_embedding_384"][0] += .001
        with self.assertRaisesRegex(ValueError, "pairs digest mismatch"):
            subject.prepare_alignment_plan(manifest)

    def test_all_pair_payloads_are_closed_and_source_only(self):
        for change in ({"extra": "unbound"}, {"source_text": "secret"}, {"reference_target": {"a": 1}}):
            manifest = pairs()
            manifest["pairs"][0].update(change)
            resign_pairs(manifest)
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "pair has invalid fields"):
                subject.prepare_alignment_plan(manifest)

    def test_wrong_shapes_nonfinite_booleans_and_nonunit_vectors_are_rejected(self):
        invalid_vectors = ([0.0] * 384, [1.0] + [0.0] * 382,
                           [True] + [0.0] * 383, [float("nan")] + [0.0] * 383,
                           [float("inf")] + [0.0] * 383, [10 ** 400] + [0] * 383)
        for vector in invalid_vectors:
            manifest = pairs()
            manifest["pairs"][0]["source_embedding_384"] = vector
            if all(not isinstance(item, float) or math.isfinite(item) for item in vector):
                resign_pairs(manifest)
            with self.subTest(first=repr(vector[0])), self.assertRaises(ValueError):
                subject.prepare_alignment_plan(manifest)

    def test_source_profile_asset_and_receipt_hashes_are_bound(self):
        changes = ({"source_vector_space_id": "wrong"}, {"student_profile_id": "wrong"},
                   {"asset_manifest_sha256": "c" * 64}, {"student_receipt_sha256": "X" * 64},
                   {"source_sha256": "c" * 64}, {"row_sha256": None},
                   {"component_sha256": "short"}, {"student_component_sha256": "c" * 64})
        for change in changes:
            manifest = pairs()
            manifest["pairs"][0].update(change)
            resign_pairs(manifest)
            with self.subTest(change=change), self.assertRaises(ValueError):
                subject.prepare_alignment_plan(manifest)

    def test_student_vector_is_bound_to_complete_geometry_audit(self):
        manifest = pairs()
        manifest["pairs"][0]["student_embedding_768"] = [1.0] + [0.0] * 767
        resign_pairs(manifest)
        with self.assertRaisesRegex(ValueError, "student vector/reference geometry binding"):
            subject.prepare_alignment_plan(manifest)

    def test_geometry_inventory_and_component_digests_are_verified(self):
        for component in (False, True):
            manifest = pairs()
            if component:
                manifest["student_geometry_audit"]["components"][0]["row_ids"] = ["wrong"]
            else:
                manifest["student_geometry_inventory_sha256"] = "c" * 64
            with self.subTest(component=component), self.assertRaises(ValueError):
                subject.prepare_alignment_plan(manifest)

    def test_resigned_geometry_cannot_put_shared_document_in_separate_split_components(self):
        manifest = pairs()
        train = next(item for item in manifest["pairs"] if item["split"] == "train")
        validation = next(item for item in manifest["pairs"] if item["split"] == "validation")
        validation["document_id"] = train["document_id"]
        geometry = manifest["student_geometry_audit"]
        validation_geometry = next(item for item in geometry["rows"] if item["id"] == validation["source_id"])
        validation_geometry["document_id"] = train["document_id"]
        # Rebind every changed declaration while intentionally leaving the two
        # connected sources in their old separate components.
        for component in geometry["components"]:
            members = [item for item in geometry["rows"] if item["component_sha256"] == component["component_sha256"]]
            component_hash = digest(sorted(({field: item[field] for field in subject._BINDING_FIELDS}
                                            for item in members), key=raw))
            for item in members:
                item["component_sha256"] = component_hash
            component["component_sha256"] = component_hash
        by_id = {item["id"]: item for item in geometry["rows"]}
        for pair in manifest["pairs"]:
            pair["student_component_sha256"] = by_id[pair["source_id"]]["component_sha256"]
        geometry["inventory_sha256"] = digest({"profile": geometry["profile"], "rows": geometry["rows"]})
        manifest["student_geometry_inventory_sha256"] = geometry["inventory_sha256"]
        resign_pairs(manifest)
        with self.assertRaisesRegex(ValueError, "connected-component identities disagree"):
            subject.prepare_alignment_plan(manifest)

    def test_false_claims_and_reference_supervision_cannot_be_promoted(self):
        for field in subject._FALSE_FIELDS:
            manifest = pairs()
            manifest[field] = True
            with self.subTest(field=field), self.assertRaises(ValueError):
                subject.prepare_alignment_plan(manifest)
        manifest = pairs([row("train-a", target_origin="teacher_prediction"), row("train-b"), row("validation", split="validation")])
        manifest["pairs"][0]["reference_supervision_eligible"] = True
        resign_pairs(manifest)
        with self.assertRaisesRegex(ValueError, "reference-supervision flag"):
            subject.prepare_alignment_plan(manifest)

    def test_geometry_claims_are_false_and_eligibility_is_recomputed(self):
        for field in ("typed_target_validated", "source_semantics_verified", "vectors_producer_verified",
                      "normalization_verified", "split_memberships_changed", "sealed_memberships_inferred"):
            manifest = pairs()
            manifest["student_geometry_audit"][field] = True
            with self.subTest(field=field), self.assertRaises(ValueError):
                subject.prepare_alignment_plan(manifest)
        manifest = pairs()
        geometry = manifest["student_geometry_audit"]
        geometry["rows"][0]["eligibility"]["sealed_evaluation_reference"] = True
        geometry["inventory_sha256"] = digest({"profile": geometry["profile"], "rows": geometry["rows"]})
        manifest["student_geometry_inventory_sha256"] = geometry["inventory_sha256"]
        with self.assertRaisesRegex(ValueError, "eligibility claim mismatch"):
            subject.prepare_alignment_plan(manifest)

    def test_counts_status_and_exclusion_membership_are_consistent(self):
        changes = (("counts", "pairs", 99), ("counts", "bound_receipts", 2),
                   ("counts", "source_tasks", 2), ("split_counts", "train", 99),
                   ("reference_supervision_split_counts", "train", 99),
                   ("terminal_row_counts", "paired", 99),
                   ("counts", "archive_teacher_prediction_rows", 1),
                   ("counts", "selected_domain_archive_rows", 1))
        for section, field, value in changes:
            manifest = pairs()
            manifest[section][field] = value
            with self.subTest(section=section, field=field), self.assertRaises(ValueError):
                subject.prepare_alignment_plan(manifest)
        manifest = pairs(receipts=False)
        manifest["missing_eligible_pair_receipt_ids"] = []
        with self.assertRaisesRegex(ValueError, "missing receipt membership"):
            subject.prepare_alignment_plan(manifest)
        manifest = pairs()
        manifest["status"] = "partial"
        with self.assertRaisesRegex(ValueError, "coverage status mismatch"):
            subject.prepare_alignment_plan(manifest)

    def test_allows_no_schema_subclasses_or_cyclic_json(self):
        class DictSubclass(dict):
            pass
        with self.assertRaises(ValueError):
            subject.prepare_alignment_plan(DictSubclass(pairs()))
        manifest = pairs()
        manifest["pairs"][0]["source_embedding_384"][0] = manifest
        with self.assertRaisesRegex(ValueError, "finite acyclic JSON"):
            subject.prepare_alignment_plan(manifest)


class SerializedAlignmentPlanTests(unittest.TestCase):
    def test_plan_tampering_and_unknown_fields_are_rejected(self):
        for change in ({"extra": True}, {"teacher_qualified": True}, {"fit_ready": False},
                       {"selection_policy": "test_selection"}, {"source_dimension": 768},
                       {"input_alignment_direction": "source_384_to_student_768"}):
            plan = subject.prepare_alignment_plan(pairs())
            plan.update(change)
            if "extra" not in change:
                resign_plan(plan)
            with self.subTest(change=change), self.assertRaises(ValueError):
                subject.inspect_alignment_plan(plan)

    def test_resigned_plan_cannot_move_validation_into_fitting(self):
        plan = subject.prepare_alignment_plan(pairs())
        plan["train_rows"].append(plan["validation_rows"].pop())
        resign_plan(plan)
        with self.assertRaisesRegex(ValueError, "changed original split memberships"):
            subject.inspect_alignment_plan(plan)

    def test_cross_split_document_group_component_or_exact_source_identity_is_rejected(self):
        for field in ("document_id", "group_id", "component_sha256", "student_component_sha256",
                      "source_id", "source_sha256", "row_sha256"):
            plan = subject.prepare_alignment_plan(pairs())
            plan["validation_rows"][0][field] = plan["train_rows"][0][field]
            resign_plan(plan)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "alignment identity"):
                subject.inspect_alignment_plan(plan)

    def test_exact_numeric_vector_identity_includes_int_float_signed_zero(self):
        for field, width in (("source_embedding_384", 384), ("student_embedding_768", 768)):
            plan = subject.prepare_alignment_plan(pairs())
            plan["train_rows"][0][field] = [1] + [0] * (width - 1)
            plan["validation_rows"][0][field] = [1.0, -0.0] + [0.0] * (width - 2)
            resign_plan(plan)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "alignment identity"):
                subject.inspect_alignment_plan(plan)

    def test_malformed_task_identifier_rejects_before_sorting(self):
        plan = subject.prepare_alignment_plan(pairs())
        plan["train_rows"][0]["task_id"] = 17
        plan["train_rows_sha256"] = digest(plan["train_rows"])
        plan["plan_sha256"] = digest({key: value for key, value in plan.items() if key != "plan_sha256"})
        with self.assertRaisesRegex(ValueError, "task identifiers are invalid"):
            subject.inspect_alignment_plan(plan)

    def test_stdlib_import_and_zero_receipt_preparation_do_not_load_models(self):
        code = """
import importlib.abc, importlib.util, sys
class RejectModels(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'torch','transformers','numpy','safetensors'}:
            raise AssertionError('unexpected numerical import: '+fullname)
sys.meta_path.insert(0, RejectModels())
spec=importlib.util.spec_from_file_location('alignment_contract', sys.argv[1])
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
rows=[]
audit=module._AUDIT.audit_transfer_rows(rows, vector_space_id='synthetic/v1')
tasks=module._BRIDGE._CORPUS.prepare_embedding_tasks(rows,audit)
pairs=module._BRIDGE.prepare_bridge_pairs(rows,audit,tasks,[])
plan=module.prepare_alignment_plan(pairs)
assert not plan['fit_ready'] and not plan['train_rows']
assert module.inspect_alignment_plan(plan)['status']=='unavailable'
"""
        result = subprocess.run([sys.executable, "-c", code, str(_PATH)], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
