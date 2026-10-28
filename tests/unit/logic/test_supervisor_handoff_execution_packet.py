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



# Authored inventory controls extend the disclosed pure-function AST profile.
# CLI controls below substitute only the extracted pure owner at its import
# boundary; separate actual canonical-namespace execution remains mandatory.
_CAPABILITY_NAMES = {"_handoff_reconciliation_bytes_v2", "prepare_current_capability_and_purpose_map_v1",
                     "verify_current_capability_and_purpose_map_v1"}
_CAPABILITY_NODES = [node for node in ast.parse(OWNER_TEXT).body
    if isinstance(node, ast.FunctionDef) and node.name in _CAPABILITY_NAMES]
assert len(_CAPABILITY_NODES) == 3
_CAPABILITY_NAMESPACE = {"json": json, "hashlib": hashlib, "Any": Any, "Mapping": Mapping}
exec(compile(ast.Module(body=_CAPABILITY_NODES, type_ignores=[]), str(OWNER), "exec"), _CAPABILITY_NAMESPACE)
_capability_prepare = _CAPABILITY_NAMESPACE["prepare_current_capability_and_purpose_map_v1"]
_capability_verify = _CAPABILITY_NAMESPACE["verify_current_capability_and_purpose_map_v1"]


class CapabilityPurposeInventoryTests(unittest.TestCase):
    """Supplied metadata fixtures; no actual native or scientific capabilities."""

    def fixture(self):
        roots = {"datasets_metadata": "/fixture/datasets", "native_control": "/fixture/accelerate", "runtime_resources": "/fixture/runtime"}
        files = {
            "source_lease": "autoencoder_source_lease.py", "resource_scheduler": "resource_scheduler.py",
            "existing_scheduler": "existing_resource_scheduler.py", "daemon_owner": "autoencoder_daemon_resources.py",
            "parented_owner": "parented_phase_resources.py", "validation_owner": "validation_run_resources.py",
            "runtime_observer": "autoencoder_owned_runtime.py", "pipeline_scheduler": "pipeline_stage_scheduler.py",
            "training_preparer": "autoencoder_campaign_owned_training.py", "training_executor": "autoencoder_campaign_owned_execution.py",
            "inference_route": "autoencoder_inference.py", "inference4096": "legal_span_4096_device_inference.py"}
        sources = {key: {"path": roots["runtime_resources"] + "/ipfs_datasets_py/optimizers/logic_theorem_optimizer/" + leaf,
                         "bytes": 123, "sha256": "a" * 64} for key, leaf in files.items()}
        for key, root, relative in (
            ("validation_cli", "runtime_resources", "scripts/ops/legal_ir/run_owned_validation.py"),
            ("lean_backend", "runtime_resources", "ipfs_datasets_py/logic/backends/kernel/lean.py"),
            ("native_task_source", "native_control", "ipfs_accelerate_py/agent_supervisor/task_sources/database_task_source.py"),
            ("native_intent_owner", "native_control", "ipfs_accelerate_py/agent_supervisor/task_sources/intent_repository.py"),
            ("pure_packet_preparer", "datasets_metadata", "ipfs_datasets_py/logic/autoformal/supervisor_loop.py"),
            ("canonical_metadata_cli", "datasets_metadata", "scripts/ops/legal_ir/run_autoformal_supervisor.py")):
            sources[key] = {"path": roots[root] + "/" + relative, "bytes": 123, "sha256": "a" * 64}
        criteria = ["Unavailable capabilities remain explicit blockers.",
            "Validation replay cannot authorize training; semantic_review is a proposed reviewer stage until its capability adapter is bound."]
        aliases = ["LIR-9001", "LIR-9002"] + ["LIR-X" + str(i) for i in range(62)]
        tasks = []
        for index, alias in enumerate(aliases):
            dependencies = [] if index == 0 else [{"dependency_task_cid": "task:" + str(index - 1), "kind": "depends_on"}]
            if 2 <= index <= 53:
                dependencies.append({"dependency_task_cid": "task:" + str(index - 2), "kind": "depends_on"})
            tasks.append({"task_alias": alias, "task_cid": "task:" + str(index), "goal_cid": "goal:1", "plan_cid": "plan:test",
                "revision": 2, "status": "blocked", "spec_cid": "spec:" + str(index), "dependencies": dependencies,
                "body": {"completion": "manual", "authored_task": {"task_id": alias}}, "outputs": [], "acceptance": [], "validations": []})
        baseline = {"schema": "ipfs_accelerate_py/agent-supervisor/intent-plan-projection@1", "projection_cid": "projection:old",
            "tasks": tasks, "goals": [{"goal_cid": "goal:" + str(i)} for i in range(34)],
            "goal_edges": [{"parent_goal_cid": "goal:0", "child_goal_cid": "goal:" + str(i)} for i in range(1, 34)],
            "plans": [{"plan_cid": "plan:test"}], "objectives": []}
        old_failure = {"task_cid": "task:0", "attempt_number": 2, "outcome": "UNKNOWN"}
        values = {
            "completion_result": {"schema": "legal-ir-native-independent-factual-completion-result/v2", "task_cid": "task:0",
                "completed_revision": 15, "evidence_digest": "evidence:accepted", "all_other63_tasks_unchanged": True, "native_DAG_unchanged": True},
            "independent_verification": {"schema": "legal-ir-current-handoff-verification/v2", "valid": True,
                "task_scope": {"task_cid": "task:0", "revision": 14}, "checked_scope": "factual_metadata_only", "old_provider_outcome_resolved": False},
            "independent_owner_closeout": {"schema": "f18-original-owner-control-closeout/v1", "returncode": 0,
                "request_unchanged": True, "source_pins_unchanged": True,
                "source_READ_retained_through_owner_exit_and_closing_source_check": True,
                "custody": {"source_custody_closed": True, "original_storage_status": "released"}},
            "completion_terminal": {"schema": "legal-ir-original-native-control-terminal/v1", "completed": True, "child_returncode": 0,
                "source_READ_closed": True, "original_native_compute_closed": True, "storage_status": "released", "cleanup_errors": []}}
        evidence = {}
        for key, value in values.items():
            raw = (json.dumps(value, sort_keys=True) + "\n").encode()
            evidence[key] = {"descriptor": {"path": "/retained/" + key + ".json", "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()},
                             "json_text": raw.decode()}
        receipt = {"schema": "legal-ir-native-independent-factual-completion/v2", "task_cid": "task:0", "reviewed_revision": 14,
            "operation": "independent_factual_metadata_completion_v2", "evidence_digest": "evidence:accepted",
            "prior_provider_outcome": "UNKNOWN", "old_provider_outcome_resolved": False, "provider_success_claimed": False,
            "old_failure_receipt": old_failure, "independent_verification": evidence["independent_verification"]["descriptor"],
            "independent_closed_owner_receipt": evidence["independent_owner_closeout"]["descriptor"]}
        tasks[0].update(revision=15, status="completed")
        tasks[0]["body"].update(completion_receipt=receipt, retained_execution_outcomes=[{"task_cid": "task:0", "task_revision": 13,
            "completion_receipt": old_failure, "sha256": hashlib.sha256(_reconciliation_bytes(old_failure)[:-1]).hexdigest()}])
        tasks[1]["acceptance"] = [{"criterion": criterion, "ordinal": i, "evidence_policy": {"criterion": criterion}}
                                  for i, criterion in enumerate(criteria)]
        current = copy.deepcopy(baseline);selected = current["tasks"][1];selected.update(revision=3, spec_cid="spec:amended")
        outputs = {"report": roots["runtime_resources"] + "/workspace/test-logs/evidence/outputs/LIR-9002/capability-and-purpose-map-current-v1.json"}
        outputs.update(freeze=outputs["report"][:-5] + ".freeze.json", verification=outputs["report"][:-5] + ".verification.json")
        relative = {key: value[len(roots["runtime_resources"]) + 1:] for key, value in outputs.items()}
        verifier_argv = ["/fixture/python", "-B", sources["canonical_metadata_cli"]["path"], "capability-purpose", "verify",
            "--inputs", "/fixture/inputs.json", "--report", outputs["report"], "--freeze", outputs["freeze"],
            "--verifier-principal", "independent-reviewer", "--output", "/fixture/verification.json"]
        selected["body"]["control_capability_purpose_inventory_v1"] = {"schema": "legal-ir-native-capability-purpose-contract/v1",
            "execution_kind": "control_metadata_only", "provider_execution_allowed": False, "new_provider_attempt_allowed": False,
            "replacement_evidence_kind": "legal_ir_capability_purpose_inventory_independent_v1", "history_copied_from_other_tasks": False,
            "output_paths": relative, "publication_root": roots["runtime_resources"], "verification_argv": verifier_argv,
            "prior_outputs": [], "prior_validations": [], "prior_owned_paths": None}
        selected["body"].update(validation=[verifier_argv], validation_commands=[{"argv":verifier_argv}])
        selected["outputs"] = [{"path": value} for value in relative.values()]
        for row in selected["acceptance"]:
            row["evidence_policy"].update(evidence_kind="legal_ir_capability_purpose_inventory_independent_v1",
                independent_post_freeze_validation_required=True, scope="factual_capability_inventory_only")
        specs = [
            ("source_custody", ["source_lease"], ["source_metadata"]),
            ("control_metadata_analysis", ["existing_scheduler", "daemon_owner", "parented_owner", "native_task_source", "native_intent_owner"], ["source_metadata", "prior_evidence"]),
            ("metadata_validation", ["validation_owner", "validation_cli"], ["source_metadata", "prior_evidence"]),
            ("training", ["training_preparer", "training_executor", "pipeline_scheduler"], ["source_text", "permitted_context", "reviewed_training_target"]),
            ("inference_8D_384D_768D_4096D", ["inference_route", "inference4096"], ["source_text", "permitted_context", "representation", "checkpoint"]),
            ("lean_kernel_and_library_build", ["lean_backend", "resource_scheduler"], ["candidate_formalization", "source_metadata"]),
            ("semantic_review", [], ["source_text", "permitted_context", "candidate_formalization"]),
            ("runtime_filesystem_observation", ["runtime_observer"], ["source_metadata"]),
            ("task_manual_acceptance", ["native_task_source", "native_intent_owner"], ["source_metadata", "prior_evidence"])]
        rows = [{"purpose": purpose, "owners": owners, "owner_sources": [sources[key] for key in owners],
            "disposition": "unavailable" if purpose == "semantic_review" else "implementation_unbound",
            "blockers": ["No new operation-specific native admission or authorized reviewer adapter."], "evidence_ids": [],
            "permitted_input_roles": roles, "new_execution_authorized": False} for purpose, owners, roles in specs]
        for row in rows:
            if row["purpose"] in {"source_custody", "control_metadata_analysis", "metadata_validation", "task_manual_acceptance"}:
                row.update(disposition="retained_scope_only", evidence_ids=["completion_terminal", "independent_owner_closeout"])
        inventory = {"schema": "legal-ir-capability-purpose-inputs/v1", "repository_roots": roots, "source_descriptors": sources,
            "capabilities": rows, "dependency_evidence": evidence, "runtime_outputs": outputs,
            "input_role_policy": {"target_as_inference_input": False, "review_as_inference_input": False,
                "target_derived_context_as_inference_input": False, "evaluation_reference_requires_output_freeze": True,
                "training_requires_distinct_native_owner": True, "semantic_review_requires_authorized_adapter": True},
            "input_roots": {"source_metadata": sorted(roots.values()), "model_source": [], "context": [], "targets": [], "evaluation_reference": []}}
        return {"original_snapshot": baseline, "current_snapshot": current, "inventory": inventory,
                "producer_principal": "inventory-author", "expected_task_revision": 3}

    def freeze(self, request):
        report = _capability_prepare(**request);raw = _reconciliation_bytes(report)
        return report, {"schema": "legal-ir-capability-purpose-producer-freeze/v1", "report_sha256": hashlib.sha256(raw).hexdigest(),
            "report_bytes": len(raw), "producer_principal": report["producer_principal"], "frozen_before_verification": True}

    def test_unavailable_capabilities_are_valid_inventory_and_never_execution_authority(self):
        request = self.fixture();before = copy.deepcopy(request);report, freeze = self.freeze(request)
        self.assertEqual(report["counts"], {"tasks":64,"goals":34,"goal_edges":33,"dependencies":115,"purposes":9})
        self.assertFalse(report["all_capabilities_required_runnable"])
        self.assertTrue(report["unavailable_capabilities_remain_explicit_blockers"])
        self.assertEqual(request, before)
        checked = _capability_verify(report, producer_freeze=freeze, verifier_principal="independent-reviewer", **request)
        self.assertTrue(checked["valid"])
        for key in ("native_admission", "completion_authority", "training_authorized", "semantic_review_verified", "descriptor_files_authenticated"):
            self.assertIs(report[key], False);self.assertIs(checked[key], False)
        self.assertEqual(checked["supervision_masks"], {"training":0,"evaluation_gold":0})

    def test_stale_dependency_revision_status_receipt_and_evidence_are_refused(self):
        for mutation in ("revision", "status", "receipt", "verification", "terminal", "evidence_hash", "history"):
            with self.subTest(mutation=mutation):
                request=self.fixture();row=request["current_snapshot"]["tasks"][0]
                if mutation=="revision":row["revision"]=14
                elif mutation=="status":row["status"]="blocked"
                elif mutation=="receipt":row["body"]["completion_receipt"]["old_provider_outcome_resolved"]=True
                elif mutation=="history":row["body"]["retained_execution_outcomes"]=[]
                else:
                    evidence=request["inventory"]["dependency_evidence"]
                    if mutation=="evidence_hash":evidence["completion_result"]["descriptor"]["sha256"]="f"*64
                    else:
                        key="independent_verification" if mutation=="verification" else "completion_terminal"
                        value=json.loads(evidence[key]["json_text"]);value["valid" if mutation=="verification" else "source_READ_closed"]=False
                        raw=(json.dumps(value,sort_keys=True)+"\n").encode();evidence[key]["json_text"]=raw.decode()
                        evidence[key]["descriptor"].update(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
                if mutation in {"revision", "status", "receipt", "history"}:
                    # Preserve the between-snapshot join to exercise the
                    # dependency acceptance checks themselves.
                    request["original_snapshot"]["tasks"][0]=copy.deepcopy(row)
                with self.assertRaises(ValueError):_capability_prepare(**request)

    def test_native_generated_ids_do_not_require_guessed_pre_CAS_cids(self):
        request=self.fixture();expected=_capability_prepare(**request)
        request["current_snapshot"]["projection_cid"]="actual-native-projection"
        request["current_snapshot"]["tasks"][1]["spec_cid"]="actual-native-specification"
        self.assertEqual(_capability_prepare(**request),expected)
        self.assertEqual(expected["current_snapshot_commitment_omits_native_generated_ids"],
                         ["projection_cid","tasks[LIR-9002].spec_cid"])

    def test_exact_native_identity_population_criteria_and_other_rows_are_preserved(self):
        for mutation in ("task", "revision", "dependency", "other_row", "count", "goal", "criterion", "authored", "history_copy"):
            with self.subTest(mutation=mutation):
                request=self.fixture();current=request["current_snapshot"];row=current["tasks"][1]
                if mutation=="task":row["task_cid"]="other-task"
                elif mutation=="revision":row["revision"]=4
                elif mutation=="dependency":row["dependencies"][0]["dependency_task_cid"]="task:2"
                elif mutation=="other_row":current["tasks"][3]["status"]="completed"
                elif mutation=="count":current["tasks"].pop()
                elif mutation=="goal":current["goals"].pop()
                elif mutation=="criterion":row["acceptance"][0]["criterion"]="Every capability is runnable."
                elif mutation=="authored":row["body"]["authored_task"]["task_id"]="LIR-9001"
                else:row["body"]["attempt_history"]={"attempts":2,"outcome":"UNKNOWN"}
                with self.assertRaises(ValueError):_capability_prepare(**request)

    def test_source_owners_roles_and_purposes_cannot_be_mismatched(self):
        for mutation in ("source_hash", "source_path", "owner", "role", "duplicate_purpose"):
            with self.subTest(mutation=mutation):
                request=self.fixture();data=request["inventory"];row=data["capabilities"][2]
                if mutation=="source_hash":row["owner_sources"][0]=dict(row["owner_sources"][0],sha256="b"*64)
                elif mutation=="source_path":data["source_descriptors"]["validation_owner"]["path"]="/fixture/runtime/other.py"
                elif mutation=="owner":row["owners"]=["training_executor"]
                elif mutation=="role":row["permitted_input_roles"].append("target")
                else:data["capabilities"][-1]=copy.deepcopy(data["capabilities"][0])
                with self.assertRaises(ValueError):_capability_prepare(**request)

    def test_validation_receipts_cannot_qualify_training_inference_lean_or_runtime(self):
        for purpose in ("training", "inference_8D_384D_768D_4096D", "lean_kernel_and_library_build", "runtime_filesystem_observation"):
            with self.subTest(purpose=purpose):
                request=self.fixture();row=next(r for r in request["inventory"]["capabilities"] if r["purpose"]==purpose)
                row.update(disposition="retained_scope_only",evidence_ids=["independent_owner_closeout"])
                with self.assertRaises(ValueError):_capability_prepare(**request)
        for field in ("qualified", "new_execution_authorized"):
            request=self.fixture();request["inventory"]["capabilities"][0][field]=True
            with self.assertRaises(ValueError):_capability_prepare(**request)

    def test_unbound_semantic_review_requires_an_explicit_unavailable_disposition(self):
        for mutation in ("available", "adapter", "empty_blocker"):
            with self.subTest(mutation=mutation):
                request=self.fixture();row=next(r for r in request["inventory"]["capabilities"] if r["purpose"]=="semantic_review")
                if mutation=="available":row.update(disposition="retained_scope_only",evidence_ids=["completion_terminal"])
                elif mutation=="adapter":row["owners"]=["validation_owner"]
                else:row["blockers"]=[]
                with self.assertRaises(ValueError):_capability_prepare(**request)

    def test_target_review_and_reference_roles_do_not_become_inference_permissions(self):
        for field in ("target_as_inference_input", "review_as_inference_input", "target_derived_context_as_inference_input"):
            request=self.fixture();request["inventory"]["input_role_policy"][field]=True
            with self.assertRaises(ValueError):_capability_prepare(**request)
        request=self.fixture();request["inventory"]["input_roots"]["targets"]=["/fixture/answers"]
        with self.assertRaises(ValueError):_capability_prepare(**request)

    def test_report_freeze_mutation_and_same_principal_cannot_borrow_acceptance(self):
        request=self.fixture();report,freeze=self.freeze(request)
        for mutation in ("report", "freeze", "principal"):
            with self.subTest(mutation=mutation):
                candidate=copy.deepcopy(report);seal=copy.deepcopy(freeze);principal="independent-reviewer"
                if mutation=="report":candidate["capabilities"][0]["new_execution_authorized"]=True
                elif mutation=="freeze":seal["report_sha256"]="f"*64
                else:principal=request["producer_principal"]
                with self.assertRaises(ValueError):_capability_verify(candidate,producer_freeze=seal,verifier_principal=principal,**request)

    def test_traversal_duplicate_dependency_keys_and_nonfinite_inputs_are_refused(self):
        for mutation in ("source_traversal", "root_traversal", "output_traversal", "duplicate_key", "nonfinite"):
            with self.subTest(mutation=mutation):
                request=self.fixture();data=request["inventory"]
                if mutation=="source_traversal":data["source_descriptors"]["source_lease"]["path"]="/fixture/runtime/../outside.py"
                elif mutation=="root_traversal":data["repository_roots"]["datasets_metadata"]="/fixture/../outside"
                elif mutation=="output_traversal":data["runtime_outputs"]["report"]="/fixture/runtime/workspace/test-logs/../outside.json"
                elif mutation=="nonfinite":data["capabilities"][0]["blockers"]=[float("nan")]
                else:
                    item=data["dependency_evidence"]["completion_result"];raw=b'{"schema":"one","schema":"two"}'
                    item.update(json_text=raw.decode());item["descriptor"].update(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
                with self.assertRaises(ValueError):_capability_prepare(**request)


def _capability_cli_fixture_namespace():
    import argparse
    import builtins
    from types import SimpleNamespace
    selected = {"_read_handoff_metadata_v2", "_write_handoff_metadata_v2", "capability_purpose_main_v1", "main"}
    nodes = [node for node in ast.parse(_CLI_TEXT).body if isinstance(node, ast.FunctionDef) and node.name in selected]
    assert len(nodes) == 4
    real_import = builtins.__import__
    owner = SimpleNamespace(**{key: _CAPABILITY_NAMESPACE[key] for key in _CAPABILITY_NAMES})
    def fixture_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "ipfs_datasets_py.logic.autoformal.supervisor_loop":
            return owner
        return real_import(name, globals, locals, fromlist, level)
    namespace = {"__builtins__": dict(vars(builtins), __import__=fixture_import), "argparse":argparse,
        "os":os,"sys":SimpleNamespace(path=[],argv=[]),"json":json,"Path":Path,"hashlib":hashlib,"ROOT":OWNER.parents[3]}
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(_CLI_OWNER),"exec"),namespace)
    return namespace


def test_capability_metadata_routes_before_native_parser():
    namespace=_capability_cli_fixture_namespace();calls=[]
    namespace["capability_purpose_main_v1"]=lambda argv:calls.append(argv) or 23
    namespace["parser"]=lambda:(_ for _ in ()).throw(AssertionError("native parser reached"))
    assert namespace["main"](["capability-purpose","prepare","--inputs","metadata.json"])==23
    assert calls==[["prepare","--inputs","metadata.json"]]


def test_capability_metadata_cli_refuses_duplicate_json_and_traversal(tmp_path):
    namespace=_capability_cli_fixture_namespace();run=namespace["capability_purpose_main_v1"]
    source=tmp_path/"inputs.json";output=tmp_path/"report.json";freeze=tmp_path/"freeze.json"
    source.write_bytes(b'{"inventory":{},"inventory":{}}')
    call=["prepare","--inputs",str(source),"--output",str(output),"--freeze-out",str(freeze)]
    assert run(call)==2 and not output.exists() and not freeze.exists()
    call[2]=str(tmp_path/".."/"outside.json")
    assert run(call)==2 and not output.exists()


def test_capability_metadata_cli_roundtrip_freeze_and_output_preservation(tmp_path):
    namespace=_capability_cli_fixture_namespace();run=namespace["capability_purpose_main_v1"]
    request=CapabilityPurposeInventoryTests().fixture();source=tmp_path/"inputs.json";source.write_bytes(_reconciliation_bytes(request))
    report=tmp_path/"report.json";freeze=tmp_path/"freeze.json";verification=tmp_path/"verification.json"
    prepare_call=["prepare","--inputs",str(source),"--output",str(report),"--freeze-out",str(freeze)]
    assert run(prepare_call)==0
    before=report.read_bytes();assert run(prepare_call)==2 and report.read_bytes()==before
    verify_call=["verify","--inputs",str(source),"--report",str(report),"--freeze",str(freeze),
                 "--verifier-principal","independent-reviewer","--output",str(verification)]
    assert run(verify_call)==0 and json.loads(verification.read_bytes())["valid"] is True
    assert run(verify_call)==2
    verification.unlink();report.write_bytes(before+b" ")
    assert run(verify_call)==2 and not verification.exists()


if __name__ == "__main__":
    unittest.main()
