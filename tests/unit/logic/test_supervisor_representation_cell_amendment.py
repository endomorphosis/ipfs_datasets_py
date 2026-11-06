"""Authored pure-AST amendment fixtures; no package/native or runtime qualification."""
from __future__ import annotations

import ast
import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping
import unittest
from unittest import mock

EXTRACTION_PROFILE = "canonical-supervisor-representation-amendment-pure-ast/v1"
OWNER = Path(__file__).resolve().parents[3] / "ipfs_datasets_py/logic/autoformal/supervisor_loop.py"
OWNER_BYTES = OWNER.read_bytes()
OWNER_SOURCE_SHA256 = hashlib.sha256(OWNER_BYTES).hexdigest()
OWNER_TEXT = OWNER_BYTES.decode("utf-8")
FUNCTION_NODE = next(node for node in ast.parse(OWNER_TEXT).body
    if isinstance(node, ast.FunctionDef) and node.name == "prepare_representation_cell_amendment_v1")
FUNCTION_SOURCE_SHA256 = hashlib.sha256(ast.get_source_segment(OWNER_TEXT, FUNCTION_NODE).encode()).hexdigest()
NAMESPACE = {"json": json, "hashlib": hashlib, "Any": Any, "Mapping": Mapping}
exec(compile(ast.Module(body=[FUNCTION_NODE], type_ignores=[]), str(OWNER), "exec"), NAMESPACE)
prepare = NAMESPACE["prepare_representation_cell_amendment_v1"]


def commitment(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()


class RepresentationCellAmendmentTests(unittest.TestCase):
    def fixture(self):
        aliases = ["LIR-1901", "LIR-1902", "LIR-1903", "LIR-1904", "LIR-1905"]
        aliases += [f"LIR-X{i:03d}" for i in range(59)]
        tasks = []
        for ordinal, alias in enumerate(aliases, 1):
            deps = ["LIR-1902", "LIR-1903", "LIR-1904"] if alias == "LIR-1905" else ["LIR-1901"]
            inputs = {"roles": ["frozen_predictions", "role_authorized_references"] if alias == "LIR-1905"
                      else ["source", "allowed_context", "verified_model_and_encoder", "self_generated_prefixes"],
                      "required_dependency_results": deps[:], "references": ["retained/producer-guide.md"]}
            task = {"task_alias": alias, "task_id": alias, "task_cid": "task:" + alias,
                "goal_id": "LIR-G119", "goal_cid": "goal:representation", "plan_cid": "plan:retained",
                "objective_id": "objective:uscode", "ordinal": ordinal, "revision": 2, "status": "blocked",
                "title": "Retained task", "objective": "Retained three-width authored contract",
                "depends_on": deps, "dependencies": ["task:" + name for name in deps],
                "legacy_parent_task": "LIR-19", "inputs": inputs, "existing_owners": ["retained/producer-guide.md"],
                "outputs": [{"path": f"data/{alias}/result.json", "materialized": False}],
                "owned_paths": [f"data/{alias}"], "exclusive_keys": ["writer:" + alias],
                "resource_profile": "inference", "resource_stage": "inference", "validation_commands": [],
                "execution_authorized_by_this_file": False, "execution_packet_required": True,
                "gold_or_teacher_admission_granted": False, "completion": "manual",
                "constraints": {"worker_launch_authorized": False, "weight_download_allowed": False},
                "authored_task": {"objective": "Retained three-width authored contract", "depends_on": deps[:],
                    "inputs": copy.deepcopy(inputs)}}
            tasks.append(task)
        # A retained unrelated UNKNOWN receipt/history is never rewritten.
        tasks[-1]["completion_receipt"] = {"outcome": "unknown", "attempt": 2}
        tasks[-1]["attempt_history"] = [{"attempt": 1}, {"attempt": 2}]
        goals = [{"goal_cid": "goal:representation", "goal_alias": "LIR-G119"}]
        goals += [{"goal_cid": f"goal:{i}", "goal_alias": f"LIR-G{i}"} for i in range(33)]
        population = {"schema": "legal-ir-native-task-population/v1",
            "board_namespace": "legal-ir-span-graph-lean-refinement-20261016",
            "repository_tree_id": "tree:retained", "plan_root_cid": "plan:retained",
            "plans": [{"plan_cid": "plan:retained", "revision": 1}],
            "goals": goals, "goal_edges": [{"parent_goal_cid": "goal:representation", "child_goal_cid": f"goal:{i}"} for i in range(33)],
            "tasks": tasks}
        bindings = {t["task_alias"]: {"task_cid": t["task_cid"], "revision": t["revision"],
            "spec_revision": "native-spec:" + t["task_alias"] + ":2", "record_sha256": commitment(t)} for t in tasks}
        profile = {"ir_family": "legal_ir", "source_dimension": 4096, "actual_bottleneck_dimension": 4,
            "schema_version": "retained-legal-span/v1", "decoder_task": "source_span",
            "producer_family": "leanstral", "producer_id": "retained:leanstral-full-causal",
            "producer_revision": "retained:immutable-native-revision", "causal_forward": "full", "pooling": "last",
            "normalization": "l2", "input_token_limit": 512, "output_token_limit": 512,
            "sidecars": ["source_text"], "raw_vector_residual_bypass": False,
            "study_kind": "native_producer_systems", "comparison_widths": [8, 384, 768, 4096]}
        child = copy.deepcopy(tasks[3])
        child.update(task_id="LIR-1906", task_alias="LIR-1906", task_cid="task:new-durable-4096",
            ordinal=65, revision=0, plan_cid="plan:successor", title="Retained 4096D cell",
            objective="Reuse the declared retained source and decoder profile; no new capture is authorized.",
            outputs=[{"path": "data/LIR-1906/result.json", "materialized": False}],
            owned_paths=["data/LIR-1906"], exclusive_keys=["writer:LIR-1906"],
            representation_profile=copy.deepcopy(profile))
        child["authored_task"]["objective"] = child["objective"]
        replacements = {"LIR-1901": copy.deepcopy(tasks[0]), "LIR-1905": copy.deepcopy(tasks[4])}
        replacements["LIR-1901"]["objective"] = "Freeze compatible 8D/384D/768D/Leanstral4096D native-producer systems on identical reviewed source groups, complete targets, permitted context and output budgets; keep a bypass-free single-producer bottleneck study separate."
        replacements["LIR-1905"]["objective"] = "Independently compare frozen complete reviewed outputs, controls and all-enrolled fidelity/coverage/cost across the four admitted native-producer cells; this is not an isolated bottleneck-width ablation."
        comparison = replacements["LIR-1905"]
        comparison["depends_on"].append(child["task_alias"])
        comparison["dependencies"].append(child["task_cid"])
        comparison["inputs"]["required_dependency_results"] = comparison["depends_on"][:]
        for alias, task in replacements.items():
            task["authored_task"]["objective"] = task["objective"]
            if alias == "LIR-1905":
                task["authored_task"]["depends_on"] = task["depends_on"][:]
                task["authored_task"]["inputs"]["required_dependency_results"] = task["depends_on"][:]
        after_bindings = {a: {"spec_revision": "native-after-spec:" + a, "record_sha256": commitment(t)}
                          for a, t in replacements.items()}
        root_keys = ["repository_id", "repository_root_cid", "dirty_worktree_root", "task_source_id", "task_source_revision",
            "policy_root", "intent_ir_root", "legal_ir_root", "security_ir_root", "program_root", "capability_catalog_root",
            "provider_catalog_root", "usage_policy_root", "configuration_root"]
        roots = {k: "root:" + k for k in root_keys}
        roots.update(schema="ipfs_accelerate_py/agent-supervisor/plan-authority-roots@1", contract_version=1,
                     repository_root_cid=population["repository_tree_id"])
        items = []
        for alias in ["LIR-1901", "LIR-1905", "LIR-1906"]:
            add = alias == "LIR-1906"
            target = child["task_cid"] if add else bindings[alias]["task_cid"]
            items.append({"schema": "ipfs_accelerate_py/agent-supervisor/plan-delta-item@1", "contract_version": 1,
                "item_key": "amendment:" + alias, "operation": "add_task" if add else "amend_unstarted_task",
                "target_cid": "" if add else target, "expected_target_lifecycle": "proposed" if add else "blocked",
                "expected_target_spec_revision": "" if add else bindings[alias]["spec_revision"],
                "before_digest": "" if add else bindings[alias]["record_sha256"],
                "after_record_cid": target if add else after_bindings[alias]["spec_revision"],
                "effect_class": "materializable_now", "rationale": "Reviewed metadata-only four-system amendment",
                "provenance": {"review": "evidence:review"}, "preconditions": ["owner:verify-current"],
                "expected_effects": ["add_task" if add else "amend_unstarted_task"], "rollback_refs": [],
                "affected_goal_cids": ["goal:representation"], "affected_task_cids": [target],
                "affected_paths": [], "dependency_impact": [], "conflict_impact": [], "resource_impact": []})
        delta = {"schema": "ipfs_accelerate_py/agent-supervisor/plan-delta@1", "contract_version": 1,
            "base_plan_root": "plan:retained", "base_plan_revision": 1, "request_cid": "request:reviewed-4096",
            "roots": roots, "items": items, "expected_effects": ["add_task", "amend_unstarted_task"],
            "deferred_item_keys": [], "claimed_population_digest": "", "accepted_population_digest": "",
            "scan_receipt_cid": "", "evidence_bundle_cid": "", "admission_receipt_cid": ""}
        request = {"schema": "legal-ir-representation-cell-amendment-request/v1",
            "base_population_sha256": commitment(population), "candidate_plan_root_cid": "plan:successor",
            "child_task": child, "replacement_tasks": replacements, "replacement_spec_bindings": after_bindings,
            "profile": profile, "review": {"reviewer": "reviewer:independent", "scope": "representation_cell_and_comparison_metadata_only",
                "evidence": {"path": "evidence/review.json", "bytes": 128, "sha256": "a" * 64}}, "delta": delta}
        return {"current_population": population, "current_task_bindings": bindings, "amendment_request": request}

    def refresh_population_bindings(self, request):
        for task in request["current_population"]["tasks"]:
            binding = request["current_task_bindings"][task["task_alias"]]
            binding["revision"] = task["revision"]
            binding["record_sha256"] = commitment(task)
        request["amendment_request"]["base_population_sha256"] = commitment(request["current_population"])

    def test_complete_proposal_preserves_all_history_and_grants_nothing(self):
        request = self.fixture()
        before = copy.deepcopy(request)
        with mock.patch("builtins.open", side_effect=AssertionError("unexpected file access")), \
             mock.patch.object(Path, "open", side_effect=AssertionError("unexpected Path access")):
            result = prepare(**request)
        self.assertTrue(result["metadata_complete"])
        self.assertEqual(len(result["candidate_tasks"]), 65)
        changed = {original["task_alias"] for original, candidate in
                   zip(request["current_population"]["tasks"], result["candidate_tasks"]) if original != candidate}
        self.assertEqual(changed, {"LIR-1901", "LIR-1905"})
        for original, candidate in zip(before["current_population"]["tasks"], result["candidate_tasks"]):
            for field in ["task_cid", "task_alias", "ordinal", "revision", "status", "plan_cid"]:
                self.assertEqual(candidate[field], original[field])
        self.assertEqual(result["candidate_tasks"][63], before["current_population"]["tasks"][63])
        self.assertEqual(result["unchanged_goals"], before["current_population"]["goals"])
        self.assertEqual(result["unchanged_goal_edges"], before["current_population"]["goal_edges"])
        for flag in ["native_application_authorized", "native_identity_allocated", "dispatch_authorized",
                     "rearm_authorized", "workers_started", "completion_authority", "training_authorized", "semantic_review_verified"]:
            self.assertIs(result[flag], False)
        self.assertTrue(result["native_plan_revision_store_admission_required"])
        self.assertTrue(result["lineage_aware_watchdog_cutover_pending"])
        self.assertEqual(result["supervision_masks"], {"training": 0, "evaluation_gold": 0})
        result["candidate_tasks"][-1]["inputs"]["roles"].append("changed")
        result["plan_delta_wire"]["items"][0]["provenance"]["changed"] = True
        self.assertEqual(request, before)

    def test_each_partial_or_extra_delta_is_refused(self):
        for index in range(3):
            with self.subTest(removed=index):
                request = self.fixture()
                request["amendment_request"]["delta"]["items"].pop(index)
                with self.assertRaises(ValueError): prepare(**request)
        for name in ["LIR-1901", "LIR-1905"]:
            with self.subTest(removed_replacement=name):
                request = self.fixture()
                del request["amendment_request"]["replacement_tasks"][name]
                with self.assertRaises(ValueError): prepare(**request)
        request = self.fixture()
        request["amendment_request"]["delta"]["items"].append(copy.deepcopy(request["amendment_request"]["delta"]["items"][0]))
        with self.assertRaises(ValueError): prepare(**request)

    def test_existing_identity_scope_and_current_revisions_cannot_change(self):
        for section, key, value in [("current_population", "schema", "other"),
                ("current_population", "board_namespace", "other"),
                ("amendment_request", "base_population_sha256", "0" * 64),
                ("amendment_request", "candidate_plan_root_cid", "plan:retained")]:
            with self.subTest(section=section, key=key):
                request = self.fixture(); request[section][key] = value
                with self.assertRaises(ValueError): prepare(**request)
        for key, value in [("revision", 99), ("spec_revision", "stale-spec"), ("record_sha256", "0" * 64)]:
            with self.subTest(binding=key):
                request = self.fixture(); request["current_task_bindings"]["LIR-1901"][key] = value
                with self.assertRaises(ValueError): prepare(**request)
        request = self.fixture(); request["amendment_request"]["delta"]["base_plan_revision"] = 2
        with self.assertRaises(ValueError): prepare(**request)
        request = self.fixture(); request["current_population"]["tasks"][0]["revision"] = 1
        self.refresh_population_bindings(request)
        request["current_task_bindings"]["LIR-1901"]["revision"] = True
        with self.assertRaises(ValueError): prepare(**request)
        for value in [None, 0, []]:
            with self.subTest(malformed_plan=value):
                request = self.fixture(); request["current_population"]["plans"] = [value]
                with self.assertRaises(ValueError): prepare(**request)

    def test_claimed_running_and_terminal_specifications_are_refused(self):
        for alias, index in [("LIR-1901", 0), ("LIR-1905", 4)]:
            for status in ["claimed", "running", "in_progress", "completed", "failed"]:
                with self.subTest(alias=alias, status=status):
                    request = self.fixture(); request["current_population"]["tasks"][index]["status"] = status
                    self.refresh_population_bindings(request)
                    with self.assertRaises(ValueError): prepare(**request)

    def test_child_identity_parent_ordinal_and_authority_are_strict(self):
        for key, value in [("task_cid", "task:LIR-1904"), ("task_alias", "LIR-1904"),
                ("task_cid", "LIR-1906"), ("goal_cid", "goal:foreign"), ("goal_id", "LIR-G090"),
                ("plan_cid", "plan:retained"), ("ordinal", 44), ("ordinal", True), ("revision", 1),
                ("status", "ready"), ("execution_authorized_by_this_file", True),
                ("gold_or_teacher_admission_granted", True), ("validation_commands", ["run.py"])]:
            with self.subTest(child_field=key):
                request = self.fixture(); request["amendment_request"]["child_task"][key] = value
                with self.assertRaises(ValueError): prepare(**request)

    def test_child_cannot_reuse_another_writer_or_output_scope(self):
        for key, value in [("exclusive_keys", ["writer:LIR-1904"]), ("owned_paths", ["data/LIR-1904"]),
                ("owned_paths", ["../escape"]), ("outputs", [{"path": "data/foreign/result.json", "materialized": False}])]:
            with self.subTest(field=key):
                request = self.fixture(); request["amendment_request"]["child_task"][key] = value
                with self.assertRaises(ValueError): prepare(**request)

    def test_child_meaning_and_authored_authority_metadata_cannot_be_empty_or_contradictory(self):
        for key in ["title", "objective", "existing_owners"]:
            with self.subTest(empty=key):
                request = self.fixture(); child = request["amendment_request"]["child_task"]
                child[key] = [] if key == "existing_owners" else None
                if key == "objective": child["authored_task"][key] = None
                with self.assertRaises(ValueError): prepare(**request)
        for key, value in [("execution_authorized_by_this_file", True), ("gold_or_teacher_admission_granted", True),
                ("resource_stage", "training"), ("completion", "automatic"),
                ("constraints", {"worker_launch_authorized": True})]:
            with self.subTest(contradiction=key):
                request = self.fixture(); request["amendment_request"]["child_task"]["authored_task"][key] = value
                with self.assertRaises(ValueError): prepare(**request)

    def inject_runtime_metadata(self, task, wrappers, key, value):
        node = task
        for wrapper in wrappers:
            node = node.setdefault(wrapper, {})
        node[key] = copy.deepcopy(value)

    def test_new_identity_refuses_runtime_history_on_donor_child_and_copied_metadata(self):
        wrappers = [(), ("authored_task",), ("body",), ("runtime",), ("body", "runtime_state"),
                    ("authored_task", "body", "runtime_metadata"), ("metadata", "task_record")]
        histories = [("completion_receipt", {"status": "unknown", "attempt": 2}),
            ("attempt_history", [{"attempt": 2, "outcome": "unknown"}]),
            ("claim_id", "claim:original"), ("provider_invocations", [{"status": "unknown", "attempt_id": "attempt:2"}]),
            ("settlement_receipt", {"outcome": "unknown"}), ("execution_result", {"accepted": False}),
            ("lease_id", "lease:original")]
        for placement in ["donor", "child", "both"]:
            for wrappers_path in wrappers:
                for key, value in histories:
                    with self.subTest(placement=placement, wrappers=wrappers_path, field=key):
                        request = self.fixture()
                        donor = request["current_population"]["tasks"][3]
                        child = request["amendment_request"]["child_task"]
                        if placement != "child": self.inject_runtime_metadata(donor, wrappers_path, key, value)
                        if placement != "donor": self.inject_runtime_metadata(child, wrappers_path, key, value)
                        self.refresh_population_bindings(request)
                        before = copy.deepcopy(request)
                        with self.assertRaisesRegex(ValueError, "runtime history/evidence"):
                            prepare(**request)
                        self.assertEqual(request, before)

    def test_empty_zero_and_false_runtime_fields_are_not_clean_authoring_metadata(self):
        for key in ["completion_receipt", "attempt_history", "attempt_budget_consumed", "claim_id",
                    "provider_history", "settlement_status", "lease_id", "execution_result"]:
            for empty in [None, {}, [], 0, "", False]:
                for wrappers_path in [(), ("authored_task", "body", "runtime")]:
                    with self.subTest(field=key, value=empty, wrappers=wrappers_path):
                        request = self.fixture()
                        for task in [request["current_population"]["tasks"][3], request["amendment_request"]["child_task"]]:
                            self.inject_runtime_metadata(task, wrappers_path, key, empty)
                        self.refresh_population_bindings(request)
                        before = copy.deepcopy(request)
                        with self.assertRaisesRegex(ValueError, "runtime history/evidence"):
                            prepare(**request)
                        self.assertEqual(request, before)

    def test_declared_budgets_negative_authority_and_input_lineage_are_preserved(self):
        request = self.fixture()
        for task in [request["current_population"]["tasks"][3], request["amendment_request"]["child_task"]]:
            task["max_task_attempts"] = 2
            task["runtime"] = {"max_attempts": 2, "execution_packet_required": True,
                               "worker_launch_authorized": False, "completion_authority": False}
            task["inputs"]["provenance"] = {"checkpoint_history": [{"checkpoint": "retained:donor"}],
                "producer_history": [{"capture": "retained:producer"}],
                "source_note": "Prior attempts, claims and UNKNOWN outcomes remain unqualified."}
            task["authored_task"]["inputs"] = copy.deepcopy(task["inputs"])
        self.refresh_population_bindings(request)
        before = copy.deepcopy(request)
        result = prepare(**request)
        self.assertTrue(result["metadata_complete"])
        self.assertEqual(result["candidate_tasks"][-1]["max_task_attempts"], 2)
        self.assertEqual(result["candidate_tasks"][-1]["runtime"], before["amendment_request"]["child_task"]["runtime"])
        self.assertEqual(result["candidate_tasks"][63]["attempt_history"], [{"attempt": 1}, {"attempt": 2}])
        self.assertEqual(request, before)

    def test_comparison_requires_durable_child_dependency_and_complete_mirrors(self):
        for field in ["dependencies", "depends_on", "inputs", "authored_task", "objective", "status", "task_cid"]:
            with self.subTest(field=field):
                request = self.fixture()
                comparison = request["amendment_request"]["replacement_tasks"]["LIR-1905"]
                if field == "dependencies": comparison[field][-1] = "LIR-1906"
                elif field == "depends_on": comparison[field].pop()
                elif field == "inputs": comparison[field]["required_dependency_results"].pop()
                elif field == "authored_task": comparison[field]["depends_on"].pop()
                elif field == "objective": comparison[field] = "Compare three cells"
                elif field == "status": comparison[field] = "ready"
                else: comparison[field] = "task:changed-existing"
                with self.assertRaises(ValueError): prepare(**request)

    def test_producer_width_context_bottleneck_and_inventory_contracts(self):
        for key, value in [("source_dimension", 786), ("source_dimension", True), ("ir_family", "intent_ir"),
                ("actual_bottleneck_dimension", 0), ("producer_family", "gte"), ("causal_forward", "partial"),
                ("pooling", "mean"), ("normalization", "none"), ("producer_revision", ""),
                ("input_token_limit", 0), ("output_token_limit", True), ("sidecars", "source_text"),
                ("raw_vector_residual_bypass", "false"), ("study_kind", "bottleneck_only"),
                ("comparison_widths", [8, 384, 768])]:
            with self.subTest(profile_field=key):
                request = self.fixture(); request["amendment_request"]["profile"][key] = value
                request["amendment_request"]["child_task"]["representation_profile"][key] = value
                with self.assertRaises(ValueError): prepare(**request)
        request = self.fixture()
        request["amendment_request"]["profile"]["actual_bottleneck_dimension"] = 4096
        request["amendment_request"]["child_task"]["representation_profile"]["actual_bottleneck_dimension"] = 4096
        self.assertTrue(prepare(**request)["metadata_complete"])

    def test_wire_contract_cas_and_changed_replacement_commitments_are_refused(self):
        for index, key, value in [(0, "expected_target_spec_revision", "stale"),
                (0, "after_record_cid", "task:LIR-1901"), (0, "expected_target_lifecycle", "claimed"),
                (0, "before_digest", "a" * 64), (2, "after_record_cid", "native-spec:not-logical-child"),
                (2, "target_cid", "task:LIR-1904"), (1, "affected_task_cids", ["task:unrelated"]),
                (1, "operation", "unblock_task"), (1, "effect_class", "lifecycle_request")]:
            with self.subTest(item=index, field=key):
                request = self.fixture(); request["amendment_request"]["delta"]["items"][index][key] = value
                with self.assertRaises(ValueError): prepare(**request)
        request = self.fixture(); request["amendment_request"]["replacement_spec_bindings"]["LIR-1905"]["record_sha256"] = "0" * 64
        with self.assertRaises(ValueError): prepare(**request)

    def test_closed_metadata_bounds_nonfinite_values_and_review_are_refused(self):
        for target in ["request", "profile", "delta", "roots"]:
            with self.subTest(extra_field=target):
                request = self.fixture()
                objects = {"request": request["amendment_request"], "profile": request["amendment_request"]["profile"],
                    "delta": request["amendment_request"]["delta"], "roots": request["amendment_request"]["delta"]["roots"]}
                objects[target]["unexpected"] = True
                with self.assertRaises(ValueError): prepare(**request)
        for value in [float("nan"), float("inf"), "x" * 16385, object()]:
            with self.subTest(invalid_value=type(value).__name__):
                request = self.fixture(); request["amendment_request"]["review"]["reviewer"] = value
                with self.assertRaises(ValueError): prepare(**request)
        request = self.fixture(); del request["amendment_request"]["review"]["evidence"]
        with self.assertRaises(ValueError): prepare(**request)


if __name__ == "__main__":
    unittest.main(verbosity=2)
