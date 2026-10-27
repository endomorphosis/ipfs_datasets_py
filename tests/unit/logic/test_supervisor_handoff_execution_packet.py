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



if __name__ == "__main__":
    unittest.main()
