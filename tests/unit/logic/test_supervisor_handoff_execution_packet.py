"""Pure-function AST extraction qualification; not normal package integration.

The test compiles the actual selected function from the complete canonical
owner bytes. It imports no Datasets package, model, numerical or database code.
OWNER_SOURCE_SHA256 and FUNCTION_SOURCE_SHA256 identify the extraction profile.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping
import unittest

EXTRACTION_PROFILE = "canonical-supervisor-handoff-pure-function-ast/v1"
OWNER = Path(__file__).resolve().parents[3] / "ipfs_datasets_py/logic/autoformal/supervisor_loop.py"
OWNER_BYTES = OWNER.read_bytes()
OWNER_SOURCE_SHA256 = hashlib.sha256(OWNER_BYTES).hexdigest()
OWNER_TEXT = OWNER_BYTES.decode("utf-8")
FUNCTION_NODE = next(node for node in ast.parse(OWNER_TEXT).body
    if isinstance(node, ast.FunctionDef) and node.name == "prepare_handoff_execution_packet_v1")
FUNCTION_SOURCE_SHA256 = hashlib.sha256(ast.get_source_segment(OWNER_TEXT, FUNCTION_NODE).encode()).hexdigest()
NAMESPACE = {"json": json, "Any": Any, "Mapping": Mapping}
exec(compile(ast.Module(body=[FUNCTION_NODE], type_ignores=[]), str(OWNER), "exec"), NAMESPACE)
prepare = NAMESPACE["prepare_handoff_execution_packet_v1"]


class HandoffExecutionPacketTests(unittest.TestCase):
    def fixture(self, alias="LIR-9003"):
        descriptor = {"path": "/retained/code.json", "bytes": 123, "sha256": "a" * 64}
        link = {"task_alias": alias, "task_cid": "existing-task-cid", "goal_alias": "LIR-G090", "goal_cid": "existing-goal-cid"}
        programme = {"schema": "legal-ir-existing-native-programme-links/v1", "historical_plan_root_cid": "existing-plan-cid",
            "historical_repository_tree_id": "existing-tree-cid", "unparented_handoff_and_engineering_task_links": [link]}
        directives = {"LIR-01": {"schema": "legal-ir-existing-task-directive/v1", "next_task": "Reuse selected assets; meaning remains pending"}}
        task = {**link, "plan_cid": "existing-plan-cid", "repository_tree_id": "existing-tree-cid", "revision": 14,
            "dependencies": [{"task_cid": "existing-predecessor", "revision": 7}],
            "attempt_history": {"attempts": 0, "max_attempts": 2, "exhausted": False, "history": []}}
        profile = {"ir_family": "legal_ir", "schema_version": "legal-ir/v1", "decoder_task": "semantic_json",
            "source_dimension": 384, "actual_bottleneck_dimension": 8, "sidecars": ["source_text"],
            "input_token_limit": 512, "output_token_limit": 512}
        envelope = {key: copy.deepcopy(task[key]) for key in
            ("task_alias", "task_cid", "goal_cid", "plan_cid", "repository_tree_id", "revision", "dependencies")}
        envelope.update(directive_ids=["LIR-01"], profile=profile,
            inputs=[{"role": "checkpoint", "use": "provenance", "descriptor": descriptor, "profile": copy.deepcopy(profile)}],
            argv=["python3", "review.py"], cwd="/isolated/worktree", outputs=["evidence/review.json"],
            code_allowlist=[], test_allowlist=["tests/test_review.py"], exclusive_keys=["selected-source-read"],
            budgets={"cpu_threads": 1, "memory_mib": 1024, "storage_bytes": 67108864, "max_children": 4,
                     "max_tokens": 8192, "deadline_seconds": 180, "max_attempts": 1},
            worker={"role": "packet_preparer", "principal": "worker-a"},
            verifier={"role": "independent_acceptance", "principal": "reviewer-b", "argv": ["python3", "verify.py"]})
        return dict(programme_links=programme, current_directives=directives, current_task_metadata=task, execution_envelope=envelope)

    def test_complete_metadata_is_detached_and_never_execution_authority(self):
        request = self.fixture()
        before = copy.deepcopy(request)
        request["current_task_metadata"]["caller_claims_native_admission"] = True
        result = prepare(**request)
        self.assertTrue(result["metadata_complete"], result["metadata_blockers"])
        self.assertEqual(result["metadata_blockers"], [])
        self.assertEqual(len(result["independent_verification_gates"]), 2)
        for key in ("independently_verified", "descriptor_hashes_verified", "native_status_verified", "dispatch_authorized",
                    "rearm_authorized", "native_admission", "workers_started", "task_completion_authority",
                    "goal_completion_authority", "completion_authority", "admitted", "formalized", "training_authorized"):
            self.assertIs(result[key], False)
        self.assertEqual(result["supervision_masks"], {"training": 0, "evaluation_gold": 0})
        retained = result["supplied_metadata"]
        self.assertTrue(retained["current_task_metadata"]["caller_claims_native_admission"])
        retained["execution_envelope"]["profile"]["sidecars"].append("changed")
        self.assertEqual(request["execution_envelope"], before["execution_envelope"])
        self.assertEqual(request["current_task_metadata"]["attempt_history"], before["current_task_metadata"]["attempt_history"])

    def test_all_four_existing_handoff_aliases_and_widths_are_metadata_only(self):
        for alias, width in zip(("LIR-9001", "LIR-9002", "LIR-9003", "LIR-9004"), (8, 384, 768, 4096)):
            with self.subTest(alias=alias, width=width):
                request = self.fixture(alias)
                profile = request["execution_envelope"]["profile"]
                profile["source_dimension"] = width
                request["execution_envelope"]["inputs"][0]["profile"] = copy.deepcopy(profile)
                self.assertTrue(prepare(**request)["metadata_complete"])
        request = self.fixture("LIR-9101")
        self.assertIn("unsupported_handoff_task", prepare(**request)["metadata_blockers"])

    def test_exact_identity_revision_and_dependency_bindings_are_required(self):
        for key in ("task_alias", "task_cid", "goal_cid", "plan_cid", "repository_tree_id", "revision"):
            with self.subTest(key=key):
                request = self.fixture()
                request["execution_envelope"].pop(key)
                self.assertFalse(prepare(**request)["metadata_complete"])
        request = self.fixture()
        request["execution_envelope"]["dependencies"] = []
        self.assertIn("exact_dependency_revisions_required", prepare(**request)["metadata_blockers"])
        request = self.fixture()
        request["current_task_metadata"].pop("revision")
        self.assertIn("current_revision_binding_required", prepare(**request)["metadata_blockers"])

    def test_exhausted_history_requires_original_owner_review_disposition_never_rearm(self):
        request = self.fixture("LIR-9001")
        task = request["current_task_metadata"]
        task["attempt_history"].update(attempts=2, exhausted=True, history=[{"attempt": 2, "status": "failed"}])
        before = copy.deepcopy(task["attempt_history"])
        self.assertIn("exhausted_attempt_original_owner_disposition_required", prepare(**request)["metadata_blockers"])
        task["original_owner_disposition"] = {"task_cid": task["task_cid"], "revision": task["revision"],
            "action": "review_preview_only", "receipt": {"path": "/retained/owner.json", "bytes": 5, "sha256": "b" * 64}}
        self.assertTrue(prepare(**request)["metadata_complete"])
        request["execution_envelope"]["rearm"] = True
        self.assertIn("authority_request_forbidden:rearm", prepare(**request)["metadata_blockers"])
        self.assertEqual(task["attempt_history"], before)

    def test_profile_dimensions_schema_and_decoder_task_cannot_be_relabelled(self):
        for key, value in (("source_dimension", 768), ("schema_version", "legal-ir/v2"), ("decoder_task", "legal_text"),
                           ("actual_bottleneck_dimension", 384), ("sidecars", [])):
            with self.subTest(key=key):
                request = self.fixture()
                request["execution_envelope"]["inputs"][0]["profile"][key] = value
                self.assertIn("input_profile_mismatch:0", prepare(**request)["metadata_blockers"])
        request = self.fixture()
        request["execution_envelope"]["profile"]["source_dimension"] = 786
        self.assertIn("profile_identity_invalid", prepare(**request)["metadata_blockers"])

    def test_target_or_target_derived_context_cannot_be_inference_input(self):
        for role, derived in (("target", False), ("context", True), ("representation", True)):
            with self.subTest(role=role):
                request = self.fixture()
                item = request["execution_envelope"]["inputs"][0]
                item.update(role=role, use="inference", target_derived=derived)
                self.assertIn("target_inference_leak:0", prepare(**request)["metadata_blockers"])

    def test_cross_input_target_content_cannot_be_laundered_by_role_or_path(self):
        for protected_role in ("target", "review", "target_derived_source"):
            for aliased_path in (False, True):
                for reversed_order in (False, True):
                    with self.subTest(role=protected_role, alias=aliased_path, reversed=reversed_order):
                        request = self.fixture()
                        pin = {"path": "/retained/target.json", "bytes": 37, "sha256": "c" * 64}
                        protected = {"role": "source" if protected_role == "target_derived_source" else protected_role,
                            "use": "verification", "descriptor": copy.deepcopy(pin)}
                        if protected_role == "target_derived_source":
                            protected["target_derived"] = True
                        inference = {"role": "source", "use": "inference", "target_derived": False,
                                     "descriptor": copy.deepcopy(pin)}
                        if aliased_path:
                            inference["descriptor"]["path"] = "/renamed/apparently-source.json"
                        pair = [protected, inference]
                        if reversed_order:
                            pair.reverse()
                        request["execution_envelope"]["inputs"].extend(pair)
                        result = prepare(**request)
                        self.assertFalse(result["metadata_complete"])
                        self.assertTrue(any(reason.startswith("cross_input_target_inference_leak:")
                                            for reason in result["metadata_blockers"]))
                        self.assertIs(result["dispatch_authorized"], False)

    def test_distinct_source_and_checkpoint_provenance_remain_preparable(self):
        request = self.fixture()
        request["execution_envelope"]["inputs"].extend([
            {"role": "target", "use": "verification", "descriptor":
                {"path": "/retained/target.json", "bytes": 37, "sha256": "b" * 64}},
            {"role": "source", "use": "inference", "target_derived": False, "descriptor":
                {"path": "/retained/source.json", "bytes": 37, "sha256": "c" * 64}},
        ])
        before = copy.deepcopy(request)
        result = prepare(**request)
        self.assertTrue(result["metadata_complete"], result["metadata_blockers"])
        self.assertEqual(request, before)
        self.assertEqual(result["supplied_metadata"], request)
        self.assertIs(result["descriptor_hashes_verified"], False)

    def test_budgets_and_independent_acceptance_are_explicit(self):
        for value in (0, -1, True, "unbounded", None):
            with self.subTest(value=value):
                request = self.fixture()
                request["execution_envelope"]["budgets"]["max_attempts"] = value
                self.assertIn("finite_positive_budgets_required", prepare(**request)["metadata_blockers"])
        request = self.fixture()
        request["execution_envelope"]["verifier"]["principal"] = "worker-a"
        self.assertIn("independent_verifier_required", prepare(**request)["metadata_blockers"])
        for key in ("inputs", "argv", "cwd", "outputs", "code_allowlist", "test_allowlist", "exclusive_keys", "verifier", "directive_ids"):
            with self.subTest(missing=key):
                request = self.fixture()
                request["execution_envelope"].pop(key)
                self.assertFalse(prepare(**request)["metadata_complete"])

    def test_exact_argv_preserves_repeated_arguments_and_malformed_roles_block(self):
        request = self.fixture()
        request["execution_envelope"]["argv"] = ["python3", "review.py", "--left", "same", "--right", "same"]
        self.assertTrue(prepare(**request)["metadata_complete"])
        request["execution_envelope"]["inputs"][0]["role"] = {"invalid": "role"}
        self.assertIn("input_binding_invalid:0", prepare(**request)["metadata_blockers"])
        request = self.fixture()
        request["execution_envelope"]["task_alias"] = ["LIR-9003"]
        self.assertIn("unsupported_handoff_task", prepare(**request)["metadata_blockers"])

    def test_no_callable_or_nonfinite_metadata_is_invoked_or_accepted(self):
        request = self.fixture()
        request["execution_envelope"]["callable"] = lambda: self.fail("callable invoked")
        with self.assertRaisesRegex(ValueError, "finite JSON data"):
            prepare(**request)
        request = self.fixture()
        request["execution_envelope"]["budgets"]["deadline_seconds"] = float("inf")
        with self.assertRaisesRegex(ValueError, "finite JSON data"):
            prepare(**request)


    def test_control_metadata_only_needs_no_decoder_profile_or_model_assets(self):
        for include_null_profile in (False, True):
            with self.subTest(null_profile=include_null_profile):
                request = self.fixture("LIR-9001")
                envelope = request["execution_envelope"]
                envelope["execution_kind"] = "control_metadata_only"
                envelope.pop("profile")
                if include_null_profile:
                    envelope["profile"] = None
                envelope["inputs"] = [
                    {"role": "code", "use": "verification", "descriptor":
                        {"path": "/retained/controller.py", "bytes": 41, "sha256": "d" * 64}},
                    {"role": "prior_evidence", "use": "provenance", "descriptor":
                        {"path": "/retained/current-task.json", "bytes": 73, "sha256": "e" * 64}},
                ]
                before = copy.deepcopy(request)
                result = prepare(**request)
                self.assertTrue(result["metadata_complete"], result["metadata_blockers"])
                self.assertEqual(result["supplied_metadata"], request)
                self.assertEqual(request, before)
                for key in ("independently_verified", "descriptor_hashes_verified", "native_status_verified",
                            "dispatch_authorized", "rearm_authorized", "native_admission", "workers_started",
                            "task_completion_authority", "goal_completion_authority", "completion_authority",
                            "admitted", "formalized", "training_authorized", "semantic_review_verified"):
                    self.assertIs(result[key], False)
                self.assertEqual(result["supervision_masks"], {"training": 0, "evaluation_gold": 0})

    def test_control_metadata_only_rejects_profiles_model_assets_and_uses(self):
        cases = (
            ("nonnull_profile", "control_metadata_profile_forbidden"),
            ("empty_profile", "control_metadata_profile_forbidden"),
            ("input_null_profile", "control_metadata_input_profile_forbidden:0"),
            ("input_model_profile", "control_metadata_input_profile_forbidden:0"),
            ("representation", "control_metadata_model_asset_forbidden:0"),
            ("checkpoint", "control_metadata_model_asset_forbidden:0"),
            ("inference", "control_metadata_model_use_forbidden:0"),
            ("supervision", "control_metadata_model_use_forbidden:0"),
            ("model_role_alias", "input_binding_invalid:0"),
            ("training_use_alias", "input_binding_invalid:0"),
            ("mixedcase_use_alias", "input_binding_invalid:0"),
            ("malformed_role", "input_binding_invalid:0"),
        )
        for case, blocker in cases:
            with self.subTest(case=case):
                request = self.fixture("LIR-9001")
                envelope = request["execution_envelope"]
                model_profile = envelope.pop("profile")
                envelope["execution_kind"] = "control_metadata_only"
                item = {"role": "code", "use": "verification", "descriptor":
                    {"path": "/retained/controller.py", "bytes": 41, "sha256": "d" * 64}}
                envelope["inputs"] = [item]
                if case == "nonnull_profile":
                    envelope["profile"] = model_profile
                elif case == "empty_profile":
                    envelope["profile"] = {}
                elif case == "input_null_profile":
                    item["profile"] = None
                elif case == "input_model_profile":
                    item["profile"] = model_profile
                elif case in ("representation", "checkpoint"):
                    item["role"] = case
                elif case in ("inference", "supervision"):
                    item.update(use=case, target_derived=False)
                elif case == "model_role_alias":
                    item["role"] = "model_checkpoint"
                elif case == "training_use_alias":
                    item["use"] = "training"
                elif case == "mixedcase_use_alias":
                    item["use"] = "Inference"
                elif case == "malformed_role":
                    item["role"] = {"invalid": "checkpoint"}
                result = prepare(**request)
                self.assertFalse(result["metadata_complete"])
                self.assertIn(blocker, result["metadata_blockers"])
                self.assertIs(result["dispatch_authorized"], False)
                self.assertEqual(result["supervision_masks"], {"training": 0, "evaluation_gold": 0})

    def test_execution_kind_defaults_to_model_and_invalid_kinds_block(self):
        request = self.fixture()
        request["execution_envelope"]["execution_kind"] = "model"
        self.assertTrue(prepare(**request)["metadata_complete"])
        request["execution_envelope"].pop("profile")
        self.assertIn("profile_identity_required", prepare(**request)["metadata_blockers"])
        for kind in ("metadata_only", "control", "", None, True, 7, [], {}, ["model"]):
            with self.subTest(kind=kind):
                request = self.fixture()
                request["execution_envelope"]["execution_kind"] = kind
                result = prepare(**request)
                self.assertFalse(result["metadata_complete"])
                self.assertIn("execution_kind_invalid", result["metadata_blockers"])
                self.assertIs(result["dispatch_authorized"], False)




# These controls extend the same disclosed AST-extraction qualification profile.
_RECONCILIATION_NAMES = {"_handoff_reconciliation_bytes_v2", "_handoff_reconciliation_facts_v2",
                         "prepare_current_handoff_reconciliation_v2", "verify_current_handoff_reconciliation_v2"}
_RECONCILIATION_NODES = [n for n in ast.parse(OWNER_TEXT).body
                         if isinstance(n, ast.FunctionDef) and n.name in _RECONCILIATION_NAMES]
assert len(_RECONCILIATION_NODES) == 4
_RECONCILIATION_NAMESPACE = {"json": json, "hashlib": hashlib, "Any": Any, "Mapping": Mapping}
exec(compile(ast.Module(body=_RECONCILIATION_NODES, type_ignores=[]), str(OWNER), "exec"), _RECONCILIATION_NAMESPACE)
_reconcile = _RECONCILIATION_NAMESPACE["prepare_current_handoff_reconciliation_v2"]
_verify_reconciliation = _RECONCILIATION_NAMESPACE["verify_current_handoff_reconciliation_v2"]
_reconciliation_bytes = _RECONCILIATION_NAMESPACE["_handoff_reconciliation_bytes_v2"]


class CurrentHandoffReconciliationTests(unittest.TestCase):
    """Authored metadata controls, without native-store or provider access."""

    def fixture(self):
        aliases = ["LIR-9001", "LIR-9002", "LIR-9003", "LIR-9004", "LIR-0101", "LIR-0201", "LIR-0202", "LIR-0502"] + ["LIR-X" + str(i).zfill(3) for i in range(56)]
        goals = [{"goal_cid": "goal:" + str(i), "goal_alias": "LIR-G000" if i == 0 else "LIR-G090" if i == 1 else "goal-alias:" + str(i),
                  "parent_goal_cid": "" if i == 0 else "goal:0", "objective_id": "objective:test"} for i in range(34)]
        tasks = []
        for i, alias in enumerate(aliases):
            deps = [] if i == 0 else ["task:" + str(i - 1)]
            if 2 <= i <= 53:
                deps.append("task:" + str(i - 2))
            tasks.append({"task_alias": alias, "task_cid": "task:" + str(i), "goal_cid": "goal:1", "plan_cid": "plan:test",
                          "objective_id": "objective:test", "dependencies": deps, "legacy_parent_task": None,
                          "authored_task": {"title": "authored " + alias}})
        parents, maintained_parents = [], []
        at = 12
        for i in range(1, 25):
            parent = "LIR-" + str(i).zfill(2)
            children = tasks[at:at + (3 if i <= 4 else 2)]
            at += len(children)
            for child in children:
                child["legacy_parent_task"] = parent
            parents.append({"id": parent, "depends_on": [], "subtasks": [c["task_alias"] for c in children],
                            "related_lac_equivalence": "unreviewed_related_scope_only", "related_lac_tasks": ["LAC-authored"]})
            maintained_parents.append({"id": parent, "depends_on": [], "supervisor_execution": {"task_links": [
                {key: c[key] for key in ("task_alias", "task_cid", "goal_cid", "legacy_parent_task")} for c in children]}})
        self.assertEqual(at, 64)
        edges = [{"parent_goal_cid": "goal:0", "child_goal_cid": "goal:" + str(i), "edge_kind": "goal_parent"} for i in range(1, 34)]
        original = {"schema": "legal-ir-native-task-population/v1", "board_namespace": "test-board", "plan_root_cid": "plan:test",
                    "repository_tree_id": "tree:test", "tasks": tasks, "goals": goals, "goal_edges": edges,
                    "plans": [{"plan_cid": "plan:test", "legacy_parent_crosswalk": parents}]}
        current = {key: copy.deepcopy(original[key]) for key in ("board_namespace", "plan_root_cid", "repository_tree_id", "tasks", "goals", "goal_edges")}
        current["schema"] = "legal-ir-current-native-programme-snapshot/v2"
        for row in current["tasks"]:
            row.update(revision=14 if row["task_alias"] == "LIR-9001" else 2, status="blocked")
        receipt = {"task_cid": "task:0", "operation": "database_task_claim_failure", "attempt_number": 2,
                   "automatic_retry_admitted": False, "failure_kind": "administrative_operator_stop_outcome_unknown",
                   "attempt_id": "original-unknown-attempt", "provider_invocation_count": 1}
        digest = hashlib.sha256(_reconciliation_bytes(receipt)[:-1]).hexdigest()
        current["tasks"][0].update(completion_receipt=copy.deepcopy(receipt), retained_execution_outcomes=[{
            "task_cid": "task:0", "task_revision": 13, "completion_receipt": copy.deepcopy(receipt), "sha256": digest}])
        prior = {key: current["tasks"][0][key] for key in ("task_alias", "task_cid", "goal_cid", "plan_cid")}
        prior.update(repository_tree_id="tree:test", revision=13, status="blocked", completion_receipt=copy.deepcopy(receipt),
                     attempt_history={"attempts": 2, "max_attempts": 2, "outcome": "UNKNOWN"})
        programme = {"schema": "legal-ir-existing-native-programme-links/v1", "historical_board_namespace": "test-board",
                     "historical_plan_root_cid": "plan:test", "historical_repository_tree_id": "tree:test",
                     "unparented_handoff_and_engineering_task_links": [{key: c[key] for key in ("task_alias", "task_cid", "goal_cid")} for c in tasks[:12]]}
        return {"original_population": original, "current_snapshot": current,
                "backlog": {"schema": "legal-ir-active-work-items/v1", "supervisor_programme": programme, "tasks": maintained_parents},
                "work_catalog": {"schema": "legal-autoformal-work-catalog/v1", "components": [{"id": "owner-a", "path": "owner.py", "status": "retained", "evidence_ids": ["proof-a"]}], "selected_evidence": [{"id": "proof-a"}]},
                "prior_task_metadata": prior, "producer_principal": "metadata-author", "expected_task_revision": 14}

    def report_and_freeze(self, inputs):
        report = _reconcile(**inputs)
        raw = _reconciliation_bytes(report)
        freeze = {"schema": "legal-ir-handoff-producer-freeze/v2", "report_sha256": hashlib.sha256(raw).hexdigest(),
                  "report_bytes": len(raw), "producer_principal": inputs["producer_principal"], "frozen_before_verification": True}
        return report, freeze

    def test_valid_join_preserves_counts_current_statuses_and_unknown_history(self):
        inputs = self.fixture()
        before = copy.deepcopy(inputs)
        report = _reconcile(**inputs)
        self.assertEqual(report["counts"], {"tasks": 64, "goals": 34, "goal_edges": 33, "dependencies": 115, "parents": 24})
        self.assertEqual(report["prior_provider_outcome"], "UNKNOWN")
        self.assertEqual(report["prior_attempt_history"], {"attempts": 2, "max_attempts": 2, "outcome": "UNKNOWN"})
        self.assertEqual({r["status"] for r in report["current_task_states"]}, {"blocked"})
        self.assertEqual(report["retained_execution_outcomes"], inputs["current_snapshot"]["tasks"][0]["retained_execution_outcomes"])
        self.assertEqual(inputs, before)
        for field in ("native_status_verified", "descriptor_files_authenticated", "old_provider_outcome_resolved",
                      "old_provider_success_claimed", "attempts_rearmed", "attempt_budget_reset", "task_or_goal_status_changed",
                      "completion_authority", "dispatch_authorized", "native_admission", "training_authorized", "formalized"):
            self.assertIs(report[field], False)
        report["reuse_candidates"][0]["evidence_ids"].append("changed")
        self.assertEqual(inputs, before)

    def test_independent_frozen_verification_has_no_native_or_legal_authority(self):
        inputs = self.fixture()
        report, freeze = self.report_and_freeze(inputs)
        before = copy.deepcopy((inputs, report, freeze))
        checked = _verify_reconciliation(report, producer_freeze=freeze, verifier_principal="independent-reviewer", **inputs)
        self.assertIs(checked["valid"], True)
        self.assertEqual(checked["task_scope"]["revision"], 14)
        self.assertEqual(checked["report_sha256"], freeze["report_sha256"])
        self.assertEqual(checked["checked_scope"], "factual_metadata_only")
        for key in ("principals_authenticated", "freeze_chronology_authenticated", "native_status_verified",
                    "old_provider_outcome_resolved", "completion_authority", "native_admission", "training_authorized", "formalized"):
            self.assertIs(checked[key], False)
        self.assertEqual((inputs, report, freeze), before)

    def test_stale_task_and_prior_revisions_are_refused(self):
        for field, value in (("current", 13), ("current", 15), ("current", True), ("prior", 12), ("prior", 14), ("expected", 15)):
            with self.subTest(field=field, value=value):
                x = self.fixture()
                if field == "current": x["current_snapshot"]["tasks"][0]["revision"] = value
                elif field == "prior": x["prior_task_metadata"]["revision"] = value
                else: x["expected_task_revision"] = value
                with self.assertRaises(ValueError): _reconcile(**x)

    def test_missing_or_duplicate_population_rows_and_edges_are_refused(self):
        for key in ("tasks", "goals", "goal_edges"):
            for damage in ("missing", "duplicate"):
                with self.subTest(key=key, damage=damage):
                    x = self.fixture(); rows = x["current_snapshot"][key]
                    if damage == "missing": rows.pop()
                    else: rows[-1] = copy.deepcopy(rows[0])
                    with self.assertRaises(ValueError): _reconcile(**x)

    def test_task_identity_authored_metadata_or_dependency_change_is_refused(self):
        for key in ("task_cid", "goal_cid", "plan_cid", "objective_id", "legacy_parent_task", "authored_task", "dependencies"):
            with self.subTest(key=key):
                x = self.fixture(); row = x["current_snapshot"]["tasks"][-1]
                row[key] = {"changed": True} if key == "authored_task" else [] if key == "dependencies" else "changed"
                with self.assertRaises(ValueError): _reconcile(**x)

    def test_parent_crosswalk_and_lac_equivalence_changes_are_refused(self):
        for damage in ("parent", "dependency", "cid", "lac", "unparented", "current_lac"):
            with self.subTest(damage=damage):
                x = self.fixture(); p = x["backlog"]["tasks"][0]
                if damage == "parent": p["id"] = "LIR-99"
                elif damage == "dependency": p["depends_on"] = ["LIR-02"]
                elif damage == "cid": p["supervisor_execution"]["task_links"][0]["task_cid"] = "wrong"
                elif damage == "lac": x["original_population"]["plans"][0]["legacy_parent_crosswalk"][0]["related_lac_equivalence"] = "completed"
                elif damage == "current_lac": p["related_lac_equivalence"] = "completed"
                else: x["backlog"]["supervisor_programme"]["unparented_handoff_and_engineering_task_links"].pop()
                with self.assertRaises(ValueError): _reconcile(**x)

    def test_spent_budget_unknown_receipt_and_history_are_not_forged_or_erased(self):
        for damage in ("attempt", "retry", "failure", "budget", "outcome", "current_receipt", "missing_history", "history_hash", "history_revision", "history_task", "duplicate_history"):
            with self.subTest(damage=damage):
                x = self.fixture(); prior = x["prior_task_metadata"]; row = x["current_snapshot"]["tasks"][0]
                if damage == "attempt": prior["completion_receipt"]["attempt_number"] = 1
                elif damage == "retry": prior["completion_receipt"]["automatic_retry_admitted"] = True
                elif damage == "failure": prior["completion_receipt"]["failure_kind"] = "provider_succeeded"
                elif damage == "budget": prior["attempt_history"]["max_attempts"] = 3
                elif damage == "outcome": prior["attempt_history"]["outcome"] = "SUCCEEDED"
                elif damage == "current_receipt": row["completion_receipt"]["attempt_id"] = "other"
                elif damage == "missing_history": row["retained_execution_outcomes"] = []
                elif damage == "history_hash": row["retained_execution_outcomes"][0]["sha256"] = "0" * 64
                elif damage == "history_revision": row["retained_execution_outcomes"][0]["task_revision"] = 14
                elif damage == "history_task": row["retained_execution_outcomes"][0]["task_cid"] = "other"
                else: row["retained_execution_outcomes"].append(copy.deepcopy(row["retained_execution_outcomes"][0]))
                with self.assertRaises(ValueError): _reconcile(**x)

    def test_report_changes_cannot_borrow_a_valid_freeze_or_grant_authority(self):
        for damage in ("status", "authority", "unknown", "extra"):
            with self.subTest(damage=damage):
                x = self.fixture(); report, freeze = self.report_and_freeze(x)
                if damage == "status": report["current_task_states"][0]["status"] = "completed"
                elif damage == "authority": report["completion_authority"] = True
                elif damage == "unknown": report["prior_provider_outcome"] = "SUCCEEDED"
                else: report["unreviewed_extra"] = True
                with self.assertRaises(ValueError): _verify_reconciliation(report, producer_freeze=freeze, verifier_principal="reviewer", **x)

    def test_freeze_and_declared_principal_separation_are_required(self):
        for damage in ("hash", "bytes", "producer", "order", "same_principal", "missing_verifier"):
            with self.subTest(damage=damage):
                x = self.fixture(); report, freeze = self.report_and_freeze(x); principal = "reviewer"
                if damage == "hash": freeze["report_sha256"] = "0" * 64
                elif damage == "bytes": freeze["report_bytes"] += 1
                elif damage == "producer": freeze["producer_principal"] = "other"
                elif damage == "order": freeze["frozen_before_verification"] = False
                elif damage == "same_principal": principal = x["producer_principal"]
                else: principal = ""
                with self.assertRaises(ValueError): _verify_reconciliation(report, producer_freeze=freeze, verifier_principal=principal, **x)

    def test_catalog_link_and_finite_json_requirements_are_checked(self):
        for damage in ("missing_evidence", "duplicate_component", "nan"):
            with self.subTest(damage=damage):
                x = self.fixture()
                if damage == "missing_evidence": x["work_catalog"]["selected_evidence"][0]["id"] = "other"
                elif damage == "duplicate_component": x["work_catalog"]["components"] *= 2
                else: x["work_catalog"]["bad_scalar"] = float("nan")
                with self.assertRaises(ValueError): _reconcile(**x)

    def reviewed_fixture(self):
        x = self.fixture()
        allowed = {
            "LIR-0101": {"existing_owners", "objective", "inputs", "acceptance_criteria", "acceptance"},
            "LIR-0201": {"existing_owners", "objective", "inputs", "acceptance_criteria", "acceptance", "title"},
            "LIR-0202": {"existing_owners", "objective", "inputs", "acceptance_criteria", "acceptance"},
            "LIR-0502": {"acceptance_criteria", "acceptance"},
        }
        originals = {r["task_alias"]: r for r in x["original_population"]["tasks"]}
        approvals = []
        for row in x["current_snapshot"]["tasks"]:
            alias = row["task_alias"]
            if alias not in allowed:
                continue
            row["revision"] = 3
            for field in allowed[alias]:
                row["authored_task"][field] = "reviewed field: " + field
            independent_sha = lambda value: hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()
            approvals.append({"task_alias": alias, "task_cid": row["task_cid"], "revision": 3,
                              "original_authored_sha256": independent_sha(originals[alias]["authored_task"]),
                              "current_authored_sha256": independent_sha(row["authored_task"]),
                              "review": {"path": "/retained/authoring-review.json", "bytes": 123, "sha256": "a" * 64}})
        x["reviewed_current_task_amendments"] = approvals
        return x

    def test_exact_four_reviewed_current_authoring_amendments_are_disclosed_without_authority(self):
        x = self.reviewed_fixture()
        before = copy.deepcopy(x)
        report, freeze = self.report_and_freeze(x)
        self.assertEqual(len(report["reviewed_current_authoring_differences"]), 4)
        self.assertEqual({r["task_alias"] for r in report["reviewed_current_authoring_differences"]}, {"LIR-0101", "LIR-0201", "LIR-0202", "LIR-0502"})
        self.assertIs(report["authoring_review_authenticated"], False)
        checked = _verify_reconciliation(report, producer_freeze=freeze, verifier_principal="independent-reviewer", **x)
        self.assertIs(checked["valid"], True)
        self.assertIs(checked["completion_authority"], False)
        self.assertEqual(x, before)

    def test_missing_wrong_extra_or_unreviewed_authoring_approval_is_refused(self):
        for damage in ("missing", "hash", "revision", "cid", "alias", "extra_field", "review", "unreviewed"):
            with self.subTest(damage=damage):
                x = self.reviewed_fixture(); approvals = x["reviewed_current_task_amendments"]
                if damage == "missing": approvals.pop()
                elif damage == "hash": approvals[0]["current_authored_sha256"] = "0" * 64
                elif damage == "revision": approvals[0]["revision"] = 4
                elif damage == "cid": approvals[0]["task_cid"] = "wrong"
                elif damage == "alias": approvals[0]["task_alias"] = "LIR-9001"
                elif damage == "extra_field": x["current_snapshot"]["tasks"][4]["authored_task"]["unreviewed"] = True
                elif damage == "review": approvals[0]["review"]["sha256"] = "b" * 64
                else: x["current_snapshot"]["tasks"][-1]["authored_task"]["unreviewed"] = True
                with self.assertRaises(ValueError): _reconcile(**x)

    def test_goal_parent_cycle_is_refused_even_if_both_inputs_repeat_it(self):
        x = self.fixture()
        for population in (x["original_population"], x["current_snapshot"]):
            population["goals"][1]["parent_goal_cid"] = "goal:2"
            population["goals"][2]["parent_goal_cid"] = "goal:1"
            population["goal_edges"][0]["parent_goal_cid"] = "goal:2"
            population["goal_edges"][1]["parent_goal_cid"] = "goal:1"
        with self.assertRaisesRegex(ValueError, "goal parent cycle"):
            _reconcile(**x)



_CLI_OWNER = OWNER.parents[3] / "scripts/ops/legal_ir/run_autoformal_supervisor.py"
_CLI_BYTES = _CLI_OWNER.read_bytes()
_CLI_TEXT = _CLI_BYTES.decode("utf-8")
_CLI_NODES = [n for n in ast.parse(_CLI_TEXT).body if isinstance(n, ast.FunctionDef)
              and n.name in {"_read_handoff_metadata_v2", "_write_handoff_metadata_v2", "main"}]
assert len(_CLI_NODES) == 3
import os
import sys
_CLI_NAMESPACE = {"os": os, "sys": sys, "json": json, "Path": Path}
exec(compile(ast.Module(body=_CLI_NODES, type_ignores=[]), str(_CLI_OWNER), "exec"), _CLI_NAMESPACE)


def test_handoff_metadata_reader_rejects_duplicate_nonfinite_and_nonobject_json(tmp_path):
    for i, raw in enumerate((b'{"x":1,"x":2}', b'{"x":NaN}', b'[]')):
        source = tmp_path / ("bad-" + str(i) + ".json")
        source.write_bytes(raw)
        with unittest.TestCase().assertRaises(ValueError):
            _CLI_NAMESPACE["_read_handoff_metadata_v2"](source)
    source = tmp_path / "good.json"
    source.write_bytes(b'{"scope":"metadata"}')
    assert _CLI_NAMESPACE["_read_handoff_metadata_v2"](source) == {"scope": "metadata"}


def test_handoff_metadata_outputs_are_exclusive_and_preserve_existing_bytes(tmp_path):
    output = tmp_path / "report.json"
    write = _CLI_NAMESPACE["_write_handoff_metadata_v2"]
    write(output, b'{"valid":false}\n')
    with unittest.TestCase().assertRaises(FileExistsError):
        write(output, b'{"valid":true}\n')
    assert output.read_bytes() == b'{"valid":false}\n'


def test_handoff_metadata_mode_routes_before_native_argument_parsing():
    called = []
    namespace = dict(_CLI_NAMESPACE)
    namespace["handoff_reconciliation_main_v2"] = lambda argv: called.append(argv) or 17
    namespace["parser"] = lambda: (_ for _ in ()).throw(AssertionError("native parser reached"))
    node = next(n for n in ast.parse(_CLI_TEXT).body if isinstance(n, ast.FunctionDef) and n.name == "main")
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(_CLI_OWNER), "exec"), namespace)
    assert namespace["main"](["handoff-reconciliation", "prepare", "--inputs", "metadata.json"]) == 17
    assert called == [["prepare", "--inputs", "metadata.json"]]


if __name__ == "__main__":
    unittest.main()
