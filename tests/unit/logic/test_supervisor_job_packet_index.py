"""Authored metadata controls; no native store, model or runtime integration.

The complete selected canonical function ASTs execute with stdlib-only globals.
These fixtures do not authenticate source bytes, principals or current status.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping
import unittest

OWNER = Path(__file__).resolve().parents[3] / "ipfs_datasets_py/logic/autoformal/supervisor_loop.py"
OWNER_BYTES = OWNER.read_bytes()
OWNER_SOURCE_SHA256 = hashlib.sha256(OWNER_BYTES).hexdigest()
FUNCTIONS = {"_handoff_reconciliation_bytes_v2", "prepare_current_job_packet_index_v1", "verify_current_job_packet_index_v1"}
NODES = [node for node in ast.parse(OWNER_BYTES).body if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS]
if {node.name for node in NODES} != FUNCTIONS:
    raise AssertionError("complete selected canonical packet-index functions required")
NAMESPACE = {"Any": Any, "Mapping": Mapping, "json": json, "hashlib": hashlib}
exec(compile(ast.Module(body=NODES, type_ignores=[]), str(OWNER), "exec"), NAMESPACE)
prepare = NAMESPACE["prepare_current_job_packet_index_v1"]
verify = NAMESPACE["verify_current_job_packet_index_v1"]
wire = NAMESPACE["_handoff_reconciliation_bytes_v2"]


def pin(value, path="/retained/value.json"):
    raw = wire(value)
    return {"path": path, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


class JobPacketIndexTests(unittest.TestCase):
    def fixture(self):
        aliases = ["LIR-9001", "LIR-9002", "LIR-9003", "LIR-9004"] + [f"LIR-{n:04d}" for n in range(100, 160)]
        tasks = []
        for i, alias in enumerate(aliases):
            deps = [] if i == 0 else [{"dependency_task_cid": f"task-{i-1}", "kind": "depends_on"}]
            if 2 <= i < 54:
                deps.append({"dependency_task_cid": f"task-{i-2}", "kind": "depends_on"})
            #9003 is the unmodified handoff frontier, with9002 as its sole dependency.
            if i in (2, 3):
                deps = deps[:1]
            if i in (54, 55):
                deps.append({"dependency_task_cid": "task-0", "kind": "depends_on"})
            output = f"data/{alias}/result.json"
            tasks.append({"task_alias": alias, "task_cid": f"task-{i}", "goal_cid": f"goal-{i%34}",
                "plan_cid": "existing-plan", "revision": 2, "status": "blocked", "dependencies": deps,
                "outputs": [{"path": output}], "body": {"completion": "manual", "authored_task": {"title": alias},
                    "code_edit_allowlist": [], "exclusive_keys": [f"writer:{alias}"], "owned_paths": [f"data/{alias}"]}})
        tasks[0].update(revision=15, status="completed")
        failure = {"task_cid": "task-0", "failure_kind": "administrative_operator_stop_outcome_unknown", "automatic_retry_admitted": False}
        tasks[0]["body"].update(completion_receipt={"old_provider_outcome_resolved": False,
            "provider_success_claimed": False, "old_failure_receipt": failure}, retained_execution_outcomes=[{
                "task_cid": "task-0", "task_revision": 13, "completion_receipt": failure,
                "sha256": hashlib.sha256(wire(failure)[:-1]).hexdigest()}])
        tasks[1].update(revision=4, status="completed")
        scope = {key: (3 if key == "revision" else tasks[1][key]) for key in ("task_alias", "task_cid", "goal_cid", "plan_cid", "revision")}
        flags = {"training_authorized": False, "semantic_review_verified": False, "dispatch_authorized": False,
            "native_admission": False, "formalized": False, "supervision_masks": {"training": 0, "evaluation_gold": 0}}
        purposes = ["source_custody", "control_metadata_analysis", "metadata_validation", "training",
            "inference_8D_384D_768D_4096D", "lean_kernel_and_library_build", "semantic_review",
            "runtime_filesystem_observation", "task_manual_acceptance"]
        report = {"schema": "legal-ir-current-capability-and-purpose-map/v1", "task_scope": scope,
            "producer_principal": "inventory-author", "unavailable_capabilities_remain_explicit_blockers": True,
            "all_capabilities_required_runnable": False, **copy.deepcopy(flags), "capabilities": [
                {"purpose": purpose, "disposition": ("unavailable" if purpose == "semantic_review" else
                    "retained_scope_only" if purpose in {"source_custody", "control_metadata_analysis", "metadata_validation", "task_manual_acceptance"}
                    else "implementation_unbound"),
                 "new_execution_authorized": False, "blockers": ["current execution unadmitted"],
                 "permitted_input_roles": ["source_metadata", "prior_evidence"]} for purpose in purposes]}
        checked = {"schema": "legal-ir-current-capability-purpose-verification/v1", "valid": True,
            "checked_scope": "factual_capability_inventory_only", "task_scope": scope,
            "report_sha256": pin(report)["sha256"], "report_bytes": len(wire(report)),
            "producer_principal": "inventory-author", "verifier_principal": "inventory-reviewer", **copy.deepcopy(flags)}
        tasks[1]["body"]["completion_receipt"] = {"operation": "independent_capability_purpose_inventory_completion_v1",
            "scope": "factual_capability_inventory_only", "reviewed_revision": 3,
            "independent_verification": pin(checked), **copy.deepcopy(flags)}
        snapshot = {"schema": "ipfs_accelerate_py/agent-supervisor/intent-plan-projection@1", "tasks": tasks,
            "goals": [{"goal_cid": f"goal-{i}"} for i in range(34)], "plans": [{"plan_cid": "existing-plan"}],
            "goal_edges": [{"parent_goal_cid": f"goal-{i-1}", "child_goal_cid": f"goal-{i}", "edge_kind": "goal_parent"} for i in range(1, 34)]}
        return {"current_snapshot": snapshot, "capability_report": report, "capability_verification": checked,
            "packet_proposals": [], "producer_principal": "packet-author"}

    def proposal(self, request):
        task = request["current_snapshot"]["tasks"][3]
        source = {"path": "/source/metadata.py", "bytes": 100, "sha256": "a" * 64}
        return {"task_alias": task["task_alias"], "task_cid": task["task_cid"], "revision": task["revision"],
            "dependencies": [{"task_cid": "task-2", "revision": 2, "status": "blocked"}],
            "purpose": "metadata_validation", "execution_kind": "control_metadata_only",
            "argv": ["python3", source["path"], "prepare"], "cwd": "/source", "source_descriptors": [source],
            "entrypoint_source": source, "validation_source": source,
            "validation_argv": ["python3", source["path"], "check"],
            "inputs": [{"role": "source_metadata", "use": "verification", "descriptor": source}],
            "outputs": [task["outputs"][0]["path"]], "code_allowlist": [], "test_allowlist": [],
            "exclusive_keys": task["body"]["exclusive_keys"], "retry_key": "metadata-attempt-only",
            "invalidation_key": "current-task-and-input-commitments", "worker": {"role": "metadata", "principal": "worker"},
            "verifier": {"role": "independent_acceptance", "principal": "reviewer", "source_descriptor": source,
                         "argv": ["python3", source["path"], "verify"]},
            "budgets": {"cpu_threads": 1, "memory_mib": 1024, "storage_bytes": 67108864,
                        "max_children": 1, "max_tokens": 0, "deadline_seconds": 120, "max_attempts": 1}}

    def test_missing_packets_have_complete_index_coverage_and_zero_acceptance(self):
        request = self.fixture(); before = copy.deepcopy(request)
        result = prepare(**request)
        self.assertEqual(len(result["entries"]), 64)
        self.assertEqual(result["counts"]["completed_scope_retained"], 2)
        self.assertEqual(result["counts"]["packet_missing"], 62)
        self.assertTrue(result["full_index_coverage"])
        self.assertEqual(result["capability_dispositions"][6]["disposition"], "unavailable")
        for key in ("productive_runnable_coverage_complete", "task_acceptance_satisfied", "native_admission", "completion_authority"):
            self.assertIs(result[key], False)
        self.assertTrue(all(not row["runnable"] for row in result["entries"]))
        self.assertEqual(request, before)

    def test_complete_metadata_still_preserves_capability_blockers_and_no_dispatch(self):
        request = self.fixture(); request["packet_proposals"] = [self.proposal(request)]
        result = prepare(**request); row = result["entries"][3]
        self.assertTrue(row["metadata_complete"], row["metadata_blockers"])
        self.assertEqual(row["disposition"], "metadata_bound_pending_review")
        self.assertIn("current execution unadmitted", row["execution_blockers"])
        self.assertIn("dependency_not_completed:task-2", row["execution_blockers"])
        self.assertFalse(row["runnable"]); self.assertFalse(result["task_acceptance_satisfied"])
        self.assertEqual(row["dependencies"], request["packet_proposals"][0]["dependencies"])

    def test_required_packet_fields_become_negative_dispositions(self):
        for key in ("argv", "validation_argv", "source_descriptors", "entrypoint_source", "validation_source", "cwd",
                    "inputs", "outputs", "code_allowlist", "test_allowlist", "exclusive_keys", "budgets",
                    "worker", "verifier", "retry_key", "invalidation_key", "dependencies"):
            with self.subTest(field=key):
                request = self.fixture(); proposal = self.proposal(request); proposal.pop(key)
                request["packet_proposals"] = [proposal]
                row = prepare(**request)["entries"][3]
                self.assertEqual(row["disposition"], "packet_metadata_incomplete")
                self.assertFalse(row["metadata_complete"]); self.assertTrue(row["metadata_blockers"])

    def test_model_roles_scope_and_budget_cannot_be_relabelled_metadata(self):
        changes = [("purpose", "training"), ("execution_kind", "model"), ("outputs", ["data/another-task/result.json"]),
                   ("inputs", [{"role": "source_metadata", "use": "inference", "descriptor": {"path": "/x", "bytes": 1, "sha256": "a"*64}}]),
                   ("code_allowlist", ["product.py"])]
        for key, value in changes:
            with self.subTest(field=key):
                request = self.fixture(); proposal = self.proposal(request); proposal[key] = value
                request["packet_proposals"] = [proposal]
                self.assertFalse(prepare(**request)["entries"][3]["metadata_complete"])
        for value in (1, False, -1):
            request = self.fixture(); proposal = self.proposal(request); proposal["budgets"]["max_tokens"] = value
            request["packet_proposals"] = [proposal]
            self.assertFalse(prepare(**request)["entries"][3]["metadata_complete"])

    def test_identity_completed_replay_authority_and_duplicate_proposals_refused(self):
        for change in ("revision", "task_cid", "completed", "authority", "duplicate"):
            with self.subTest(change=change):
                request = self.fixture(); proposal = self.proposal(request)
                if change == "revision": proposal["revision"] = True
                if change == "task_cid": proposal["task_cid"] = "another-task"
                if change == "completed": request["current_snapshot"]["tasks"][3]["status"] = "completed"
                if change == "authority": proposal["dispatch_authorized"] = True
                request["packet_proposals"] = [proposal] * (2 if change == "duplicate" else 1)
                with self.assertRaises(ValueError): prepare(**request)

    def test_accepted_capability_history_and_population_bindings_are_required(self):
        for change in ("verification", "receipt", "history", "population", "dependency", "plan", "cycle"):
            with self.subTest(change=change):
                request = self.fixture(); tasks = request["current_snapshot"]["tasks"]
                if change == "verification": request["capability_verification"]["report_sha256"] = "0" * 64
                if change == "receipt": tasks[1]["revision"] = 3
                if change == "history": tasks[0]["body"]["retained_execution_outcomes"] = []
                if change == "population": tasks.pop()
                if change == "dependency": tasks[2]["dependencies"] = []
                if change == "plan": tasks[-1]["plan_cid"] = "another-plan"
                if change == "cycle": tasks[4]["dependencies"][0]["dependency_task_cid"] = "task-5"
                with self.assertRaises(ValueError): prepare(**request)

    def test_frozen_index_reconstruction_is_distinct_and_acceptance_stays_open(self):
        request = self.fixture(); report = prepare(**request); raw = wire(report)
        freeze = {"schema": "legal-ir-job-packet-index-producer-freeze/v1", "report_sha256": hashlib.sha256(raw).hexdigest(),
            "report_bytes": len(raw), "producer_principal": report["producer_principal"], "frozen_before_verification": True}
        result = verify(report, producer_freeze=freeze, verifier_principal="packet-reviewer", **request)
        self.assertTrue(result["valid"]); self.assertEqual(result["checked_scope"], "factual_job_packet_inventory_only")
        self.assertFalse(result["task_acceptance_satisfied"]); self.assertFalse(result["productive_runnable_coverage_complete"])
        with self.assertRaises(ValueError): verify(report, producer_freeze=freeze, verifier_principal="packet-author", **request)
        for damage in ("report", "freeze"):
            bad_report, bad_freeze = copy.deepcopy(report), copy.deepcopy(freeze)
            if damage == "report": bad_report["entries"][3]["runnable"] = True
            else: bad_freeze["frozen_before_verification"] = False
            with self.assertRaises(ValueError): verify(bad_report, producer_freeze=bad_freeze, verifier_principal="packet-reviewer", **request)


if __name__ == "__main__":
    unittest.main()
