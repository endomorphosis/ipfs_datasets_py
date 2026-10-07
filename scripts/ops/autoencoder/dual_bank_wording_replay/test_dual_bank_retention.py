"""Pure dual-bank budget/coverage and numerical-retention contract tests."""
from collections import Counter
from copy import deepcopy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("dual_bank_retention_pure_subject", Path(__file__).with_name("dual_bank_retention.py"))
subject = importlib.util.module_from_spec(spec)
spec.loader.exec_module(subject)


def seal(value, key):
    value[key] = subject.digest({k: v for k, v in value.items() if k != key})
    return value


def fixture():
    rules = [dict(actor="actor" + str(i), action="deliver", object="notice", modality=m,
        conditions=[], exceptions=[], temporal=[]) for m in subject.MODALITIES for i in range(30)]
    banks, census, declarations = {}, {}, {}
    for role in subject.ROLES:
        templates = [role + "-template0", role + "-template1"]
        rows = []
        for slot in (0, 1):
            for rule in rules:
                text = role + " " + str(slot) + " " + subject.rule_sha(rule)
                sha = subject.text_sha(text)
                rows.append(dict(id="clause:" + sha, source_text=text, source_sha256=sha,
                    target=deepcopy(rule), modality=rule["modality"], template=templates[slot],
                    modality_token_id={"O": 3, "P": 4, "F": 5}[rule["modality"]]))
        rows.sort(key=lambda r: r["id"])
        banks[role] = seal(dict(dimension=384, rows=rows, qualified=False, admitted=False, proof_authority=False), "bank_sha256")
        census[role] = [dict(index=i, row_id=r["id"], source_sha256=r["source_sha256"],
            original_rule_sha256=subject.rule_sha(r["target"]), template=r["template"], modality=r["modality"],
            template_slot=templates.index(r["template"])) for i, r in enumerate(rows)]
        declarations[role] = dict(bank_sha256=banks[role]["bank_sha256"], templates=templates)
    orders = {role: [[r["index"] for r in sorted((item for item in census[role]
        if item["modality"] == m and item["template_slot"] == slot),
        key=lambda r: subject.digest([1729, m, slot, r["original_rule_sha256"]]))]
        for m in subject.MODALITIES for slot in (0, 1)] for role in subject.ROLES}
    draws = [dict(step=t, indices={r: [order[t % 30] for order in orders[r]] for r in subject.ROLES},
        original_rule_sha256=[subject.rule_sha(banks["control"]["rows"][order[t % 30]]["target"])
            for order in orders["control"]]) for t in range(170)]
    pairing = seal(dict(schema="balanced-wording-paired-draws/v1", seed=1729, steps=170,
        original_rules_sha256=subject.digest(rules), banks=declarations, census=census, orders=orders,
        draws=draws, qualified=False, admitted=False, proof_authority=False, train_eligible=False), "pairing_sha256")
    return dict(pairing=pairing, banks_by_role=banks, original_rules=rules)


class ScheduleContracts(unittest.TestCase):
    def setUp(self):
        self.inputs = fixture()
        self.schedule = subject.build_schedule(**self.inputs)

    def test_exact170_1020_and_complete180_per_bank_at2_or3_exposures(self):
        proof = subject.validate_schedule(self.schedule)
        self.assertEqual(proof["source_presentations"], 1020)
        self.assertEqual(len(self.schedule["draws"]), 170)
        for role in subject.ROLES:
            counts = self.schedule["per_source_exposures"][role]
            self.assertEqual(len(counts), 180)
            self.assertEqual(sum(counts.values()), 510)
            self.assertEqual(Counter(counts.values()), {3: 150, 2: 30})
        self.assertEqual(set(self.schedule["presentations_per_actual_template"].values()), {255})
        self.assertEqual(self.schedule["presentations_per_modality"], {"O": 340, "P": 340, "F": 340})

    def test_each_adjacent_pair_has_same_original_rules_and_slots_with_real_different_sources(self):
        for i in range(0, 170, 2):
            old, new = self.schedule["draws"][i:i + 2]
            self.assertEqual(old["original_rule_sha256"], new["original_rule_sha256"])
            self.assertEqual(old["template_slots"], new["template_slots"])
            self.assertEqual(old["bank_local_committed_step"], new["bank_local_committed_step"])
            self.assertNotEqual(old["row_ids"], new["row_ids"])
            self.assertNotEqual(old["selected_bank_sha256"], new["selected_bank_sha256"])

    def test_reversed_first_bank_preserves_the_same_coverage_and_budgets(self):
        schedule = subject.build_schedule(**self.inputs, first_bank="balanced")
        self.assertEqual(schedule["draws"][0]["bank_role"], "balanced")
        self.assertEqual(schedule["per_source_exposures"], self.schedule["per_source_exposures"])
        self.assertNotEqual(schedule["schedule_sha256"], self.schedule["schedule_sha256"])

    def test_naive_global_parity_samples_only90_members_and_is_refused(self):
        naive = deepcopy(self.schedule); counts = {r: Counter() for r in subject.ROLES}
        for t, draw in enumerate(naive["draws"]):
            role = draw["bank_role"]
            indices = [order[t % 30] for order in self.inputs["pairing"]["orders"][role]]
            rows = [self.inputs["banks_by_role"][role]["rows"][i] for i in indices]
            draw.update(indices=indices, row_ids=[r["id"] for r in rows], source_sha256=[r["source_sha256"] for r in rows],
                original_rule_sha256=[subject.rule_sha(r["target"]) for r in rows], templates=[r["template"] for r in rows],
                modalities=[r["modality"] for r in rows], target_token_ids=[r["modality_token_id"] for r in rows])
            counts[role].update(draw["row_ids"])
        self.assertEqual({r: len(c) for r, c in counts.items()}, {"control": 90, "balanced": 90})
        naive["per_source_exposures"] = {r: dict(c) for r, c in counts.items()}
        seal(naive, "schedule_sha256")
        with self.assertRaises(ValueError):
            subject.validate_schedule(naive)

    def test_changed_bank_or_source_target_refused(self):
        for kind in ("source", "target", "qualifier", "duplicate", "dimension", "modality_token"):
            inputs = deepcopy(self.inputs); bank = inputs["banks_by_role"]["balanced"]
            if kind == "source":
                bank["rows"][0]["source_text"] += " relabel"
            elif kind == "target":
                bank["rows"][0]["target"]["actor"] = "new actor"
            elif kind == "qualifier":
                bank["rows"][0]["target"]["conditions"] = ["if"]
            elif kind == "duplicate":
                bank["rows"][-1] = deepcopy(bank["rows"][0])
            elif kind == "dimension":
                bank["dimension"] = True
            else:
                bank["rows"][0]["modality_token_id"] = False
            seal(bank, "bank_sha256")
            inputs["pairing"]["banks"]["balanced"]["bank_sha256"] = bank["bank_sha256"]
            seal(inputs["pairing"], "pairing_sha256")
            with self.assertRaises(ValueError):
                subject.build_schedule(**inputs)

    def test_resealed_changed_local_step_source_id_and_budget_refused(self):
        for key, value in (("bank_local_committed_step", 1), ("global_committed_step", False),
            ("selected_bank_sha256", "0" * 64)):
            changed = deepcopy(self.schedule); changed["draws"][0][key] = value; seal(changed, "schedule_sha256")
            with self.assertRaises(ValueError):
                subject.validate_schedule(changed)
        for key, value in (("auxiliary_clause_presentations", 2040), ("source_auxiliary_weight", 0.),
            ("encoder_context_tokens", 8192), ("qualified", True), ("implemented_in_real_trainer", True)):
            changed = deepcopy(self.schedule); changed[key] = value; seal(changed, "schedule_sha256")
            with self.assertRaises(ValueError):
                subject.validate_schedule(changed)


def gate_fixture(schedule):
    expected, baseline, candidate = {}, {}, {}
    for cohort in subject.TRAIN_COHORTS:
        rows = []
        for count in (1, 2, 4, 8):
            for i in range(12):
                text = "\n\n".join(cohort + " " + str(count) + " " + str(i) + " " + str(j) for j in range(count))
                rows.append(dict(id=cohort + str(len(rows)), source_text=text))
        binding = dict(source_rows=rows, source_contexts_sha256=subject.digest(["contexts", cohort]),
            references_sha256=subject.digest(["references", cohort]), codec_sha256=subject.digest(["codec"]))
        source_binding = {k: v for k, v in binding.items() if k != "source_rows"}
        source_binding["source_text_rows_sha256"] = subject.digest(rows)
        expected[cohort] = binding
        formula = dict(rows=48, expected_rules=180, generated_rules=180, valid_generated_rules=180,
            eos_count=48, parsed_documents=48, syntax_valid=48, ordered_exact=48, all_rules_preserved=48,
            whole_rules_missing=0, whole_rules_extra=0, duplicate_rules=0, invalid_rule_count=0,
            invalid_rows=0, unscorable_generation_rows=0, prediction_missing_rows=0, order_mismatch_rows=0)
        panel = dict(complete=True, rows=48, expected_rules=180, source_binding=source_binding,
            model_tensor_sha256=subject.digest(["parent"]), formula_metrics=formula,
            formula_rows=[dict(id=row["id"], counts=dict(formula, rows=1,
                expected_rules=len(row["source_text"].split("\n\n")), generated_rules=len(row["source_text"].split("\n\n")),
                valid_generated_rules=len(row["source_text"].split("\n\n")), eos_count=1, parsed_documents=1,
                syntax_valid=1, ordered_exact=1, all_rules_preserved=1),
                by_facet={f: dict(total=len(row["source_text"].split("\n\n")),
                    correct=len(row["source_text"].split("\n\n"))) for f in subject.FACETS}) for row in rows],
            seven_facets={f: dict(total=180, correct=180) for f in subject.FACETS},
            scalar_by_field={f: dict(reference_sites=180, visited=180, unvisited=0, unavailable=0,
                source_correct=180, source_incorrect=0) for f in subject.FIELDS})
        baseline[cohort] = panel
        candidate[cohort] = deepcopy(panel); candidate[cohort]["model_tensor_sha256"] = subject.digest(["candidate"])
    banks = {r: {f: dict(correct=179 if r == "control" and f == "action" else 180, total=180)
        for f in subject.FIELDS} for r in subject.ROLES}
    return dict(schedule=schedule, expected_bindings=expected, baseline_panels=baseline,
        candidate_panels=candidate, baseline_bank_fields=banks, candidate_bank_fields=deepcopy(banks))


class RetentionGateContracts(unittest.TestCase):
    def setUp(self):
        self.kwargs = gate_fixture(subject.build_schedule(**fixture()))

    def test_complete_retention_can_only_pass_numerical_proposal_gate(self):
        result = subject.retention_gate(**self.kwargs)
        self.assertTrue(result["numerical_retention_passed"])
        self.assertTrue(result["allowed_numerical_continuation"])
        self.assertEqual(result["findings"], [])
        self.assertTrue(all(result[k] is False for k in subject.FALSE))
        self.assertFalse(result["implemented_in_real_trainer"])

    def test_observed_old33_of48_and19_substitutions_fail_retention(self):
        panel = self.kwargs["candidate_panels"]["normative_train48"]
        panel["formula_metrics"].update(ordered_exact=33, all_rules_preserved=33, whole_rules_missing=19, whole_rules_extra=19)
        panel["seven_facets"]["modality"]["correct"] = 161
        for row in panel["formula_rows"][:11] + panel["formula_rows"][12:16]:
            errors = row["counts"]["expected_rules"]
            row["counts"].update(ordered_exact=0, all_rules_preserved=0, whole_rules_missing=errors, whole_rules_extra=errors)
            row["by_facet"]["modality"]["correct"] -= errors
        self.kwargs["candidate_bank_fields"]["control"]["modality"]["correct"] = 170
        result = subject.retention_gate(**self.kwargs)
        self.assertFalse(result["allowed_numerical_continuation"])
        self.assertTrue(any("formula/EOS/omission/order" in s for s in result["findings"]))
        self.assertTrue(any("source bank modality" in s for s in result["findings"]))

    def test_row_cardinality_swap_cannot_hide_behind_correct_global180_count(self):
        panel = self.kwargs["candidate_panels"]["normative_train48"]
        panel["formula_rows"][0]["counts"]["generated_rules"] += 1
        panel["formula_rows"][12]["counts"]["generated_rules"] -= 1
        result = subject.retention_gate(**self.kwargs)
        self.assertFalse(result["allowed_numerical_continuation"])
        self.assertTrue(any("row cardinality" in s for s in result["findings"]))

    def test_dropped_formula_row_or_reordered_reference_position_fails_closed(self):
        for kind in ("missing", "reordered"):
            kwargs = deepcopy(self.kwargs); rows = kwargs["candidate_panels"]["new_balanced_train48"]["formula_rows"]
            if kind == "missing":
                rows.pop()
            else:
                rows[0], rows[1] = rows[1], rows[0]
            self.assertFalse(subject.retention_gate(**kwargs)["allowed_numerical_continuation"])

    def test_source_bank_regression_cannot_hide_behind_perfect_formulas(self):
        self.kwargs["candidate_bank_fields"]["control"]["modality"]["correct"] = 170
        self.assertFalse(subject.retention_gate(**self.kwargs)["allowed_numerical_continuation"])

    def test_missing_denominator_malformed_or_boolean_metric_fails_closed(self):
        for kind in ("missing", "denominator", "boolean", "incomplete", "contradictory"):
            kwargs = deepcopy(self.kwargs); panel = kwargs["candidate_panels"]["original_train48"]
            if kind == "missing":
                panel["seven_facets"].pop("conditions")
            elif kind == "denominator":
                panel["scalar_by_field"]["action"]["reference_sites"] = 179
            elif kind == "boolean":
                panel["formula_metrics"]["invalid_rows"] = False
            elif kind == "incomplete":
                panel["complete"] = False
            else:
                panel["seven_facets"]["conditions"]["correct"] = 179
            result = subject.retention_gate(**kwargs)
            self.assertFalse(result["allowed_numerical_continuation"])
            self.assertTrue(result["findings"])

    def test_eos_invalid_missing_extra_and_order_failures_are_not_dropped(self):
        for key, value in (("eos_count", 47), ("invalid_rows", 1), ("whole_rules_missing", 1),
            ("whole_rules_extra", 1), ("duplicate_rules", 1), ("order_mismatch_rows", 1)):
            kwargs = deepcopy(self.kwargs)
            kwargs["candidate_panels"]["new_balanced_train48"]["formula_metrics"][key] = value
            self.assertFalse(subject.retention_gate(**kwargs)["allowed_numerical_continuation"])

    def test_source_collision_and_changed_reference_or_context_binding_refused(self):
        for kind in ("collision", "reference", "context", "endpoint"):
            kwargs = deepcopy(self.kwargs)
            if kind == "collision":
                kwargs["expected_bindings"]["new_balanced_train48"]["source_rows"][0] = deepcopy(
                    kwargs["expected_bindings"]["normative_train48"]["source_rows"][0])
            elif kind == "reference":
                kwargs["candidate_panels"]["normative_train48"]["source_binding"]["references_sha256"] = "0" * 64
            elif kind == "context":
                kwargs["candidate_panels"]["normative_train48"]["source_binding"]["source_contexts_sha256"] = "0" * 64
            else:
                kwargs["candidate_panels"]["normative_train48"]["model_tensor_sha256"] = "0" * 64
            self.assertFalse(subject.retention_gate(**kwargs)["allowed_numerical_continuation"])

    def test_unvisited_or_unavailable_never_becomes_success_by_reducing_denominator(self):
        for category in ("unvisited", "unavailable"):
            kwargs = deepcopy(self.kwargs); field = kwargs["candidate_panels"]["normative_train48"]["scalar_by_field"]["modality"]
            field.update(visited=179, source_correct=179); field[category] = 1
            result = subject.retention_gate(**kwargs)
            self.assertFalse(result["allowed_numerical_continuation"])
            self.assertTrue(any("unavailable/unvisited" in s for s in result["findings"]))

    def test_v3_or_sealed60_cannot_be_added_or_substituted_as_selector(self):
        for cohort in ("exposed_v3_48", "sealed60"):
            kwargs = deepcopy(self.kwargs)
            for key in ("expected_bindings", "baseline_panels", "candidate_panels"):
                kwargs[key][cohort] = deepcopy(kwargs[key]["original_train48"])
            result = subject.retention_gate(**kwargs)
            self.assertFalse(result["allowed_numerical_continuation"])
            self.assertFalse(result["exposed_v3_used_for_selection"])

    def test_rehashed_forged_schedule_cannot_enable_retention(self):
        kwargs = deepcopy(self.kwargs)
        kwargs["schedule"]["draws"][0]["bank_local_committed_step"] = False
        seal(kwargs["schedule"], "schedule_sha256")
        self.assertFalse(subject.retention_gate(**kwargs)["allowed_numerical_continuation"])


if __name__ == "__main__":
    unittest.main()
