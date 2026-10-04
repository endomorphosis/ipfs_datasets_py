"""Synthetic contract checks; no tokenizer, encoder, weights, or training."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest


_PATH = Path(__file__).resolve().parents[5] / "ipfs_datasets_py/logic/formalization/autoencoder/gte_multilingual_corpus.py"
_SPEC = importlib.util.spec_from_file_location("gte_multilingual_corpus_under_test", _PATH)
subject = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(subject)


def row(name="a", **changes):
    result = {
        "id": name, "domain_id": "legal_ir", "document_id": "doc:" + name,
        "group_id": "group:" + name, "split": "train", "source_text": "Source " + name,
        "embedding": [float(sum(map(ord, name))), 1.0] + [0.0] * 382,
        "reference_target": {"native_reference": name}, "target_origin": "authored",
        "source_language": "en", "evaluation_role": "development",
    }
    result.update(changes)
    return result


def audit(rows):
    return subject._AUDIT.audit_transfer_rows(
        rows, vector_space_id="synthetic-declared-gte-small-384/v1",
    )


def prepare(rows):
    return subject.prepare_embedding_tasks(rows, audit(rows))


def receipt(task, **changes):
    result = {
        "schema": subject.RECEIPT_SCHEMA, "id": task["id"],
        "source_sha256": task["source_sha256"], "profile_id": subject.PROFILE_ID,
        "dimension": 768, "embedding": [1.0] + [0.0] * 767,
        "token_count_including_special_tokens": 17, "token_input_sha256": "a" * 64,
        "truncated": False, "normalized": True, "asset_manifest_sha256": "b" * 64,
    }
    result.update(changes)
    return result


class MultilingualTaskPreparationTests(unittest.TestCase):
    def test_prepares_source_only_without_reference_or_384_vector_payload(self):
        original = row(reference_target={"native_reference": "target-only SECRET"})
        manifest = prepare([original])
        self.assertEqual(manifest["task_count"], 1)
        self.assertEqual(manifest["input_row_count"], 1)
        self.assertEqual(manifest["status"], "ready")
        task = manifest["tasks"][0]
        self.assertEqual(task["source_text"], original["source_text"])
        self.assertEqual(task["source_sha256"], hashlib.sha256(original["source_text"].encode()).hexdigest())
        self.assertEqual(task["metadata"]["source_id"], original["id"])
        self.assertEqual(task["metadata"]["reference_target_sha256"],
                         audit([original])["rows"][0]["reference_target_sha256"])
        self.assertNotIn("target-only SECRET", json.dumps(manifest))
        self.assertNotIn('"embedding":', json.dumps(manifest))
        self.assertNotIn('"reference_target":', json.dumps(manifest))
        self.assertEqual(manifest["neural_input_fields"], ["source_text"])
        for field in ("embeddings_generated", "split_memberships_changed",
                      "reference_targets_exported", "target_semantics_verified",
                      "vectors_producer_verified"):
            self.assertIs(manifest[field], False)

    def test_manifest_is_order_independent_and_inputs_unmodified(self):
        rows = [row("a"), row("b", split="validation")]
        before = deepcopy(rows)
        first = prepare(rows)
        self.assertEqual(first, prepare(list(reversed(rows))))
        self.assertEqual(rows, before)

    def test_preserves_all_split_origin_group_and_language_declarations(self):
        rows = [row("a", split="test", evaluation_role="sealed", source_language="fr",
                    target_origin="independently_checked", document_id="statute:17",
                    group_id="statute-family:8")]
        metadata = prepare(rows)["tasks"][0]["metadata"]
        for field in ("domain_id", "document_id", "group_id", "split", "target_origin",
                      "source_language", "evaluation_role"):
            self.assertEqual(metadata[field], rows[0][field])

    def test_unlabeled_and_missing_384_embeddings_remain_source_tasks(self):
        rows = [row("a", embedding=None),
                row("b", embedding=None, reference_target=None, target_origin="unlabeled")]
        manifest = prepare(rows)
        self.assertEqual(manifest["task_count"], 2)
        self.assertIsNone(next(t for t in manifest["tasks"] if t["metadata"]["source_id"] == "b")
                          ["metadata"]["reference_target_sha256"])

    def test_teacher_predictions_stay_declared_metadata(self):
        manifest = prepare([row(target_origin="teacher_prediction")])
        self.assertEqual(manifest["tasks"][0]["metadata"]["target_origin"], "teacher_prediction")

    def test_cross_split_components_are_excluded_without_repartition(self):
        rows = [row("a"), row("b", split="test", group_id="group:a")]
        manifest = prepare(rows)
        self.assertEqual(manifest["task_count"], 0)
        self.assertEqual(manifest["rejected_row_count"], 2)
        self.assertEqual(manifest["rejection_reason_counts"]["cross_split_connected_component"], 2)
        self.assertEqual({r["split"] for r in manifest["rejected_rows"]}, {"train", "test"})

    def test_duplicate_source_has_one_task_and_one_accounted_rejection(self):
        rows = [row("a", source_text="same", reference_target={"target": "same"}),
                row("b", source_text="same", reference_target={"target": "same"})]
        manifest = prepare(rows)
        self.assertEqual(manifest["task_count"], 1)
        self.assertEqual(manifest["rejected_row_count"], 1)
        self.assertEqual(manifest["rejected_rows"][0]["reasons"], ["deduplicated"])
        self.assertEqual(manifest["rejected_rows"][0]["duplicate_of"], "a")

    def test_missing_sources_and_invalid_rows_are_accounted(self):
        rows = [row("a", source_text=None), row("b", source_text="  "), None]
        manifest = prepare(rows)
        self.assertEqual(manifest["task_count"], 0)
        self.assertEqual(manifest["input_row_count"], 3)
        self.assertEqual(manifest["rejected_row_count"], 3)
        self.assertEqual(manifest["rejection_reason_counts"]["missing_source"], 3)

    def test_nonfinite_and_cyclic_rows_are_audited_and_rejected(self):
        cyclic = row("c")
        cyclic["reference_target"]["cycle"] = cyclic
        rows = [row("a", embedding=[float("nan")] + [0.0] * 383), cyclic]
        manifest = prepare(rows)
        self.assertEqual(manifest["task_count"], 0)
        self.assertEqual(manifest["rejected_row_count"], 2)

    def test_task_identifiers_are_scoped_by_domain(self):
        left = prepare([row("same")])["tasks"][0]
        right = prepare([row("same", domain_id="security_ir")])["tasks"][0]
        self.assertNotEqual(left["id"], right["id"])
        self.assertTrue(left["id"].startswith("gte768:legal_ir:"))
        self.assertTrue(right["id"].startswith("gte768:security_ir:"))

    def test_existing_global_duplicate_id_quarantine_is_preserved(self):
        rows = [row("same"), row("same", domain_id="security_ir", source_text="Different")]
        manifest = prepare(rows)
        self.assertEqual(manifest["task_count"], 0)
        self.assertEqual(manifest["rejection_reason_counts"]["duplicate_id"], 2)

    def test_stale_source_target_vector_and_metadata_audits_rejected(self):
        rows = [row()]
        original_audit = audit(rows)
        for field, changed in (("source_text", "changed"), ("reference_target", {"changed": True}),
                               ("embedding", [1.0] + [0.0] * 383), ("group_id", "different")):
            with self.subTest(field=field):
                altered = deepcopy(rows)
                altered[0][field] = changed
                with self.assertRaises(ValueError):
                    subject.prepare_embedding_tasks(altered, original_audit)

    def test_subset_and_superset_of_audit_are_rejected(self):
        rows = [row("a"), row("b")]
        report = audit(rows)
        for altered in (rows[:1], rows + [row("c")]):
            with self.assertRaises(ValueError):
                subject.prepare_embedding_tasks(altered, report)

    def test_modified_audit_counts_flags_and_rows_are_rejected(self):
        rows = [row()]
        for change in (lambda r: r.update(input_row_count=9),
                       lambda r: r.update(vectors_producer_verified=True),
                       lambda r: r["rows"][0].update(quarantined=True)):
            altered = audit(rows)
            change(altered)
            with self.assertRaises(ValueError):
                subject.prepare_embedding_tasks(rows, altered)

    def test_wrong_dimension_schema_nonfinite_or_missing_profile_rejected(self):
        for altered in (None, {}, {"schema": "wrong"}, {"profile": {"dimension": 768}},
                        {"bad": float("nan")}):
            with self.assertRaises(ValueError):
                subject.prepare_embedding_tasks([row()], altered)

    def test_max_rows_and_invalid_iterables_rejected(self):
        rows = [row("a"), row("b")]
        with self.assertRaises(ValueError):
            subject.prepare_embedding_tasks(rows, audit(rows), max_rows=1)
        for value in (True, 0, 1.5):
            with self.assertRaises(ValueError):
                subject.prepare_embedding_tasks([], audit([]), max_rows=value)
        for value in ("rows", b"rows", {}, None):
            with self.assertRaises(ValueError):
                subject.prepare_embedding_tasks(value, audit([]))

    def test_empty_corpus_has_complete_empty_task_binding(self):
        manifest = prepare([])
        self.assertEqual(manifest["task_count"], 0)
        self.assertEqual(manifest["input_row_count"], 0)
        result = subject.bind_embedding_receipts(manifest, [])
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["accepted_count"], 0)


class MultilingualReceiptBindingTests(unittest.TestCase):
    def setUp(self):
        self.manifest = prepare([row("a"), row("b", split="validation")])
        self.tasks = self.manifest["tasks"]
        self.receipts = [receipt(t) for t in self.tasks]

    def test_complete_binding_preserves_tasks_and_uses_only_new_768_vectors(self):
        before = deepcopy((self.manifest, self.receipts))
        result = subject.bind_embedding_receipts(self.manifest, self.receipts)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["accepted_count"], 2)
        self.assertEqual(result["rejected_count"], 0)
        self.assertEqual(result["missing_receipt_ids"], [])
        self.assertEqual(result["tasks_sha256"], self.manifest["tasks_sha256"])
        self.assertEqual(result["corpus_inventory_sha256"], self.manifest["corpus_inventory_sha256"])
        for bound, task in zip(result["bound_rows"], self.tasks):
            self.assertEqual(bound["metadata"], task["metadata"])
            self.assertEqual(bound["source_text"], task["source_text"])
            self.assertEqual(len(bound["embedding"]), 768)
            self.assertEqual(bound["embedding_receipt"]["asset_manifest_sha256"], "b" * 64)
        self.assertEqual((self.manifest, self.receipts), before)
        self.assertNotIn('"reference_target":', json.dumps(result))
        for field in ("split_memberships_changed", "reference_targets_exported",
                      "target_semantics_verified", "vectors_producer_verified",
                      "tokenization_producer_verified"):
            self.assertIs(result[field], False)

    def test_direct_task_list_and_order_independence(self):
        first = subject.bind_embedding_receipts(self.tasks, self.receipts)
        second = subject.bind_embedding_receipts(reversed(self.tasks), reversed(self.receipts))
        self.assertEqual(first, second)
        self.assertIsNone(first["corpus_inventory_sha256"])

    def test_missing_coverage_explicitly_incomplete(self):
        result = subject.bind_embedding_receipts(self.manifest, self.receipts[:1])
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["accepted_count"], 1)
        self.assertEqual(result["rejected_count"], 1)
        self.assertEqual(result["missing_receipt_ids"], [self.tasks[1]["id"]])

    def test_no_receipts_retains_all_missing_task_ids(self):
        result = subject.bind_embedding_receipts(self.manifest, [])
        self.assertEqual(result["missing_receipt_ids"], sorted(t["id"] for t in self.tasks))
        self.assertEqual(result["accepted_count"], 0)
        self.assertIsNone(result["asset_manifest_sha256"])

    def test_receipt_wrong_source_profile_and_dimension_rejected(self):
        for field, value in (("source_sha256", "c" * 64), ("profile_id", "gte-small"),
                             ("schema", "unknown"), ("dimension", 384), ("dimension", True)):
            with self.subTest(field=field, value=value):
                with self.assertRaises(ValueError):
                    subject.bind_embedding_receipts(self.manifest, [receipt(self.tasks[0], **{field: value})])

    def test_duplicate_and_unexpected_receipt_ids_rejected(self):
        for data in ([self.receipts[0], self.receipts[0]],
                     [receipt(self.tasks[0], id="unexpected")]):
            with self.assertRaises(ValueError):
                subject.bind_embedding_receipts(self.manifest, data)

    def test_receipt_closed_schema_missing_and_extra_fields_rejected(self):
        for field in subject._RECEIPT_FIELDS:
            altered = deepcopy(self.receipts[0])
            del altered[field]
            with self.subTest(missing=field), self.assertRaises(ValueError):
                subject.bind_embedding_receipts(self.manifest, [altered])
        altered = deepcopy(self.receipts[0])
        altered["reference_target"] = {"must_not_enter": True}
        with self.assertRaises(ValueError):
            subject.bind_embedding_receipts(self.manifest, [altered])

    def test_nonfinite_boolean_string_wrong_width_and_overflow_vectors_rejected(self):
        vectors = [[1.0] * 384, [True] + [0.0] * 767, ["1"] + [0.0] * 767,
                   [float("nan")] + [0.0] * 767, [float("inf")] + [0.0] * 767,
                   [10 ** 400] + [0.0] * 767, tuple([1.0] + [0.0] * 767)]
        for vector in vectors:
            with self.subTest(kind=type(vector), first=type(vector[0])):
                with self.assertRaises(ValueError):
                    subject.bind_embedding_receipts(self.manifest,
                                                    [receipt(self.tasks[0], embedding=vector)])

    def test_unit_normalization_required(self):
        for value in (0.0, 0.5, 1.0002):
            with self.assertRaises(ValueError):
                subject.bind_embedding_receipts(self.manifest,
                                                [receipt(self.tasks[0], embedding=[value] + [0.0] * 767)])
        result = subject.bind_embedding_receipts(self.manifest,
                                                 [receipt(self.tasks[0], embedding=[1.00009] + [0.0] * 767)])
        self.assertEqual(result["accepted_count"], 1)

    def test_token_count_includes_specials_and_requires_bounded_integer(self):
        for count in (0, -1, 8193, True, 17.0, "17"):
            with self.subTest(count=count), self.assertRaises(ValueError):
                subject.bind_embedding_receipts(self.manifest,
                                                [receipt(self.tasks[0], token_count_including_special_tokens=count)])
        for count in (1, 8192):
            result = subject.bind_embedding_receipts(self.manifest,
                                                     [receipt(self.tasks[0], token_count_including_special_tokens=count)])
            self.assertEqual(result["accepted_count"], 1)

    def test_truncation_and_normalization_flags_are_exact_booleans(self):
        for field, value in (("truncated", True), ("truncated", 0), ("truncated", None),
                             ("normalized", False), ("normalized", 1), ("normalized", "true")):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                subject.bind_embedding_receipts(self.manifest, [receipt(self.tasks[0], **{field: value})])

    def test_receipt_hashes_require_canonical_lowercase_sha256(self):
        for field in ("token_input_sha256", "asset_manifest_sha256"):
            for value in ("", "A" * 64, "g" * 64, "a" * 63, None):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    subject.bind_embedding_receipts(self.manifest, [receipt(self.tasks[0], **{field: value})])

    def test_mixed_asset_manifest_receipts_rejected(self):
        mixed = [self.receipts[0], receipt(self.tasks[1], asset_manifest_sha256="c" * 64)]
        with self.assertRaises(ValueError):
            subject.bind_embedding_receipts(self.manifest, mixed)

    def test_corrupted_manifest_profile_count_or_content_rejected(self):
        for mutate in (lambda m: m.update(profile_id="wrong"),
                       lambda m: m.update(task_count=3),
                       lambda m: m.update(task_count=True),
                       lambda m: m.update(tasks_sha256="d" * 64),
                       lambda m: m["tasks"][0].update(source_text="changed")):
            manifest = deepcopy(self.manifest)
            mutate(manifest)
            with self.assertRaises(ValueError):
                subject.bind_embedding_receipts(manifest, self.receipts)

    def test_direct_task_source_id_and_metadata_bindings_rejected_when_changed(self):
        for mutate in (lambda t: t.update(source_text="changed"),
                       lambda t: t.update(source_sha256="d" * 64),
                       lambda t: t.update(id="unexpected"),
                       lambda t: t["metadata"].update(domain_id="unknown"),
                       lambda t: t["metadata"].update(split="future"),
                       lambda t: t["metadata"].update(evaluation_role="sealed"),
                       lambda t: t["metadata"].update(row_sha256=None),
                       lambda t: t["metadata"].update(reference_target_sha256=None),
                       lambda t: t["metadata"].update(extra="forbidden")):
            tasks = deepcopy(self.tasks)
            mutate(tasks[0])
            with self.assertRaises(ValueError):
                subject.bind_embedding_receipts(tasks, self.receipts)

    def test_duplicate_tasks_are_rejected(self):
        with self.assertRaises(ValueError):
            subject.bind_embedding_receipts([self.tasks[0], self.tasks[0]], [self.receipts[0]])

    def test_receipt_and_task_iterables_must_be_sequences_not_objects(self):
        for value in (None, "items", b"items", {}):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    subject.bind_embedding_receipts(self.manifest, value)
                with self.assertRaises(ValueError):
                    subject.bind_embedding_receipts(value, [])

    def test_binding_does_not_share_mutable_payloads_with_callers(self):
        result = subject.bind_embedding_receipts(self.manifest, self.receipts)
        self.tasks[0]["metadata"]["group_id"] = "changed"
        self.receipts[0]["embedding"][0] = 0.0
        self.assertNotEqual(result["bound_rows"][0]["metadata"]["group_id"], "changed")
        self.assertEqual(result["bound_rows"][0]["embedding"][0], 1.0)


if __name__ == "__main__":
    unittest.main()
