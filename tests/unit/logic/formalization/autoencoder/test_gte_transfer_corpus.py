"""Preparation-only synthetic audits; no encoder, trained weights or IR claims."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import unittest


_PATH = Path(__file__).resolve().parents[5] / "ipfs_datasets_py/logic/formalization/autoencoder/gte_transfer_corpus.py"
_SPEC = importlib.util.spec_from_file_location("gte_transfer_corpus_under_test", _PATH)
subject = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(subject)


def row(name, *, split="train", **changes):
    number = sum(map(ord, name))
    result = dict(id=name, domain_id="legal_ir", document_id="document:" + name,
                  group_id="group:" + name, split=split, source_text="Source " + name,
                  embedding=[float(number), 1.0], reference_target={"rule": name},
                  target_origin="authored", source_language="en",
                  evaluation_role="development")
    result.update(changes)
    return result


def audit(rows, **kwargs):
    return subject.audit_transfer_rows(rows, dimension=2,
                                       vector_space_id="synthetic-profile/v1", **kwargs)


def by_id(report):
    return {item["id"]: item for item in report["rows"]}


class TransferCorpusAuditTests(unittest.TestCase):
    def test_default_384_dimension_and_declared_profile_only(self):
        data = row("default", embedding=[1.0] + [0.0] * 383)
        report = subject.audit_transfer_rows([data], vector_space_id="declared-gte-small/v1")
        self.assertEqual(report["profile"]["dimension"], 384)
        self.assertEqual(report["usable_counts"]["fitting_reference_rows"], 1)
        self.assertEqual(report["normalization_stats"]["within_unit_norm_tolerance_rows"], 1)
        for key in ("typed_target_validated", "source_semantics_verified",
                    "vectors_producer_verified", "normalization_verified",
                    "split_memberships_changed", "sealed_memberships_inferred"):
            self.assertIs(report[key], False)

    def test_audit_is_order_independent_nonmutating_and_payload_free(self):
        rows = [row("a"), row("b", split="validation")]
        before = deepcopy(rows)
        report = audit(rows)
        self.assertEqual(report, audit(reversed(rows)))
        self.assertEqual(rows, before)
        serialized = json.dumps(report, allow_nan=False)
        self.assertNotIn("Source a", serialized)
        self.assertNotIn('"reference_target":', serialized)
        self.assertNotIn('"embedding":', serialized)
        self.assertEqual(report["usable_counts"]["fitting_reference_rows"], 1)
        self.assertEqual(report["usable_counts"]["selection_reference_rows"], 1)

    def test_leakage_and_dedup_reports_are_order_independent(self):
        rows = [row("a", source_text="duplicate", reference_target={"rule": "same"}),
                row("b", source_text="duplicate", reference_target={"rule": "same"}),
                row("c", split="test", group_id="group:b", evaluation_role="sealed")]
        self.assertEqual(audit(rows), audit([rows[2], rows[0], rows[1]]))

    def test_profile_changes_content_binding(self):
        rows = [row("a")]
        first = audit(rows)
        second = subject.audit_transfer_rows(rows, dimension=2, vector_space_id="other/v1")
        self.assertNotEqual(first["declared_profile_sha256"], second["declared_profile_sha256"])
        self.assertNotEqual(first["inventory_sha256"], second["inventory_sha256"])
        self.assertEqual(first["rows"][0]["source_sha256"], second["rows"][0]["source_sha256"])

    def test_numeric_identity_deduplicates_int_float_and_signed_zero(self):
        rows = [row("a", embedding=[1, -0.0], reference_target={"rule": "same"}),
                row("b", embedding=[1.0, 0], reference_target={"rule": "same"})]
        report = audit(rows)
        self.assertEqual(report["quarantined_row_count"], 0)
        self.assertEqual(report["deduplicated_row_count"], 1)
        self.assertEqual(report["usable_counts"]["fitting_reference_rows"], 1)
        self.assertEqual(by_id(report)["b"]["duplicate_of"], "a")
        self.assertEqual(by_id(report)["a"]["numeric_vector_sha256"], by_id(report)["b"]["numeric_vector_sha256"])

    def test_exact_source_dedup_prefers_complete_reference(self):
        incomplete = row("a", source_text="Same source", embedding=None,
                         reference_target=None, target_origin="unlabeled")
        complete = row("z", source_text="Same source")
        report = audit([incomplete, complete])
        self.assertEqual(by_id(report)["a"]["duplicate_of"], "z")
        self.assertEqual(report["usable_counts"]["fitting_reference_rows"], 1)

    def test_numeric_hash_does_not_round_distinct_large_integers(self):
        report = audit([row("a", embedding=[2 ** 53, 0]),
                        row("b", embedding=[2 ** 53 + 1, 0])])
        self.assertNotEqual(by_id(report)["a"]["numeric_vector_sha256"],
                            by_id(report)["b"]["numeric_vector_sha256"])
        self.assertEqual(report["deduplicated_row_count"], 0)
        self.assertEqual(report["quarantined_row_count"], 0)

    def test_connected_transitive_leak_quarantines_whole_component(self):
        rows = [row("a", group_id="common"),
                row("b", group_id="common", document_id="linked-doc"),
                row("c", split="test", document_id="linked-doc", evaluation_role="sealed")]
        report = audit(rows)
        self.assertEqual(report["component_count"], 1)
        self.assertEqual(report["quarantined_row_count"], 3)
        self.assertEqual(report["usable_counts"]["fitting_reference_rows"], 0)
        self.assertTrue(report["components"][0]["entire_component_quarantined"])
        self.assertEqual(by_id(report)["c"]["split"], "test")
        self.assertEqual(report["quarantine_reason_counts"]["cross_split_connected_component"], 3)

    def test_global_source_overlap_crosses_domain_boundary(self):
        rows = [row("a", source_text="Shared input"),
                row("b", split="test", source_text="Shared input", domain_id="intent_ir",
                    evaluation_role="sealed")]
        report = audit(rows)
        self.assertEqual(report["quarantined_row_count"], 2)
        self.assertNotIn("contradictory_reference_targets", report["quarantine_reason_counts"])

    def test_global_numeric_vector_overlap_crosses_domain_boundary(self):
        report = audit([row("a", embedding=[1, 0]),
                        row("b", split="validation", embedding=[1.0, -0.0], domain_id="intent_ir")])
        self.assertEqual(report["quarantined_row_count"], 2)

    def test_group_and_document_names_are_domain_scoped(self):
        report = audit([row("a", group_id="same", document_id="same"),
                        row("b", split="test", group_id="same", document_id="same",
                            domain_id="intent_ir", evaluation_role="sealed")])
        self.assertEqual(report["quarantined_row_count"], 0)
        self.assertEqual(report["component_count"], 2)

    def test_normalized_source_groups_but_does_not_deduplicate(self):
        rows = [row("a", source_text="Ａgency\n MUST save."),
                row("b", source_text="agency must  save.")]
        report = audit(rows)
        self.assertEqual(report["component_count"], 1)
        self.assertEqual(report["deduplicated_row_count"], 0)
        rows[1]["split"] = "validation"
        self.assertEqual(audit(rows)["quarantined_row_count"], 2)

    def test_reference_conflict_propagates_to_linked_nonconflicting_row(self):
        rows = [row("a", source_text="same", group_id="related"),
                row("b", source_text="same", reference_target={"different": True}),
                row("c", group_id="related")]
        report = audit(rows)
        self.assertEqual(report["quarantined_row_count"], 3)
        self.assertEqual(report["quarantine_reason_counts"]["contradictory_reference_targets"], 3)

    def test_numeric_vector_reference_conflict_is_detected(self):
        report = audit([row("a", embedding=[1, 0]), row("b", embedding=[1.0, -0.0])])
        self.assertEqual(report["quarantine_reason_counts"]["contradictory_reference_targets"], 2)

    def test_teacher_predictions_never_become_reference_supervision(self):
        rows = [row("a", target_origin="teacher_prediction"),
                row("b", source_text="Source a", target_origin="independently_checked")]
        report = audit(rows)
        self.assertEqual(report["quarantined_row_count"], 0)
        self.assertEqual(report["target_origin_counts"]["teacher_prediction"], 1)
        self.assertEqual(report["usable_counts"]["fitting_reference_rows"], 1)
        self.assertFalse(by_id(report)["a"]["eligibility"]["fitting_reference"])

    def test_unlabeled_missing_vectors_are_retained_ineligible(self):
        rows = [row("a", embedding=None),
                row("b", reference_target=None, target_origin="unlabeled")]
        report = audit(rows)
        self.assertEqual(report["quarantined_row_count"], 0)
        self.assertEqual(report["usable_counts"]["retained_rows"], 2)
        self.assertEqual(report["usable_counts"]["missing_embedding_rows"], 1)
        self.assertEqual(report["usable_counts"]["unlabeled_rows"], 1)
        self.assertEqual(report["usable_counts"]["fitting_reference_rows"], 0)

    def test_evaluation_roles_are_explicit_and_never_exported_to_fitting(self):
        rows = [row("a", split="test", evaluation_role="sealed"),
                row("b", split="canary", evaluation_role="development"),
                row("c", split="test", evaluation_role="development")]
        report = audit(rows)
        self.assertEqual(report["usable_counts"]["sealed_evaluation_reference_rows"], 1)
        self.assertEqual(report["usable_counts"]["development_evaluation_reference_rows"], 2)
        self.assertEqual(report["sealed_counts"]["test"], 1)
        self.assertEqual(report["sealed_counts"]["canary"], 0)
        self.assertEqual(report["usable_counts"]["fitting_reference_rows"], 0)
        self.assertEqual(report["usable_counts"]["selection_reference_rows"], 0)

    def test_sealed_train_or_validation_is_rejected(self):
        report = audit([row("a", evaluation_role="sealed"),
                        row("b", split="validation", evaluation_role="sealed")])
        self.assertEqual(report["quarantined_row_count"], 2)
        self.assertEqual(report["quarantine_reason_counts"]["sealed_fitting_or_selection_split"], 2)

    def test_missing_evaluation_role_does_not_infer_sealed(self):
        data = row("a", split="test")
        del data["evaluation_role"]
        report = audit([data])
        self.assertIsNone(report["rows"][0]["evaluation_role"])
        self.assertEqual(report["sealed_counts"]["test"], 0)
        self.assertEqual(report["quarantined_row_count"], 1)

    def test_duplicate_ids_reject_both_rows(self):
        report = audit([row("same"), row("same", source_text="Different", embedding=[-1, 2])])
        self.assertEqual(report["duplicate_ids"], ["same"])
        self.assertEqual(report["quarantine_reason_counts"]["duplicate_id"], 2)
        self.assertEqual(report["usable_counts"]["fitting_reference_rows"], 0)

    def test_closed_record_and_declared_fields_rejected(self):
        cases = [None, row("unknown", extra=True), row("domain", domain_id="other"),
                 row("language", source_language=" "), row("target", target_origin="unlabeled"),
                 row("missing", reference_target=None), row("split", split="tuning")]
        missing = row("missing-role")
        del missing["evaluation_role"]
        cases.append(missing)
        report = audit(cases)
        self.assertEqual(report["quarantined_row_count"], len(cases))
        self.assertEqual(report["usable_counts"]["fitting_reference_rows"], 0)

    def test_numeric_vectors_reject_bool_nan_inf_width_and_coercion(self):
        vectors = [[True, 0], [float("nan"), 0], [float("inf"), 0], [1],
                   ["1", 0], (1, 0), [10 ** 400, 0]]
        report = audit([row(str(index), embedding=vector) for index, vector in enumerate(vectors)])
        self.assertEqual(report["quarantined_row_count"], len(vectors))
        self.assertEqual(report["normalization_stats"]["finite_numeric_vector_rows"], 0)
        json.dumps(report, allow_nan=False)

    def test_norm_overflow_stays_json_finite_without_normalization_claim(self):
        report = audit([row("a", embedding=[1.7e308, 1.7e308])])
        stats = report["normalization_stats"]
        self.assertEqual(stats["finite_numeric_vector_rows"], 1)
        self.assertEqual(stats["norm_overflow_rows"], 1)
        self.assertIsNone(stats["max_l2_norm"])
        self.assertEqual(report["quarantined_row_count"], 0)
        json.dumps(report, allow_nan=False)

    def test_targets_reject_nonjson_cycles_and_nonfinite_values(self):
        cyclic = {}
        cyclic["self"] = cyclic
        targets = [cyclic, {"x": float("nan")}, {1: "non-string key"}, {"x": (1, 2)}]
        report = audit([row(str(index), reference_target=target) for index, target in enumerate(targets)])
        self.assertEqual(report["quarantined_row_count"], len(targets))
        self.assertEqual(report["quarantine_reason_counts"]["reference_target_not_finite_json"], len(targets))
        json.dumps(report, allow_nan=False)

    def test_invalid_row_still_connects_valid_cross_split_peer(self):
        rows = [row("a", source_text="same", extra=True),
                row("b", split="test", source_text="same", evaluation_role="sealed")]
        report = audit(rows)
        self.assertEqual(report["quarantine_reason_counts"]["cross_split_connected_component"], 2)
        self.assertFalse(by_id(report)["b"]["eligibility"]["sealed_evaluation_reference"])

    def test_parameter_and_bounded_iterable_failures(self):
        for dimension in (True, 0, -1, 1.5, 65537):
            with self.subTest(dimension=dimension), self.assertRaises(ValueError):
                subject.audit_transfer_rows([], dimension=dimension, vector_space_id="profile")
        for profile in ("", " ", " profile", "profile\n", None, "bad\x00profile"):
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                subject.audit_transfer_rows([], vector_space_id=profile)
        for limit in (True, 0, -1, 1.2):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                audit([], max_rows=limit)
        for rows in (None, "text", b"text", {}):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                audit(rows)
        self.assertEqual(audit([row("a")], max_rows=1)["input_row_count"], 1)
        with self.assertRaisesRegex(ValueError, "exceeds max_rows"):
            audit(iter([row("a"), row("b")]), max_rows=1)

    def test_empty_report_has_complete_zero_inventory(self):
        report = audit([])
        self.assertEqual(report["input_row_count"], 0)
        self.assertEqual(report["usable_counts"]["fitting_reference_rows"], 0)
        self.assertEqual(report["sealed_counts"]["test"], 0)
        self.assertEqual(report["normalization_stats"]["finite_norm_rows"], 0)
        self.assertEqual(report["rows"], [])


if __name__ == "__main__":
    unittest.main()
