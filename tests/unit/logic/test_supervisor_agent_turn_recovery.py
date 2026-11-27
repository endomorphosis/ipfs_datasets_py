"""Adversarial contracts for metadata-only agent-turn recovery."""
from __future__ import annotations

from contextlib import ExitStack, redirect_stderr, redirect_stdout
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import urllib.request

from ipfs_datasets_py.logic.autoformal import supervisor_loop
from ipfs_datasets_py.logic.autoformal.supervisor_loop import plan_agent_turn_recovery_v1


def task(task_id, *, operation=None, dependencies=(), keys=(), ready=True,
         authorized=True, used=0, limit=2):
    return {
        "task_id": task_id, "operation_key": operation or "operation:" + task_id,
        "depends_on": list(dependencies), "exclusive_keys": list(keys),
        "ready": ready, "authorized": authorized,
        "attempts_used": used, "max_attempts": limit,
    }


def observation(task_id, *, status="failed", error=None, cleanup=True,
                accepted=False, thread=None, turn=None):
    return {
        "task_id": task_id, "thread_id": thread or "original-thread:" + task_id,
        "turn_id": turn or "original-turn:" + task_id, "status": status,
        "error": deepcopy(error), "cleanup_confirmed": cleanup, "accepted": accepted,
        "evidence_refs": [{"path": "evidence/" + task_id + ".json", "sha256": "a" * 64}],
    }


def frontier(tasks, observations=(), *, holds=(), width=2):
    return {
        "schema": "legal-ir-agent-turn-frontier/v1", "frontier_id": "frontier:original",
        "max_parallel": width, "tasks": list(tasks), "observations": list(observations),
        "policy_holds": deepcopy(list(holds)),
    }


def decision(result, task_id):
    return next(row for row in result["task_decisions"] if row["task_id"] == task_id)


POLICY_ERROR = {
    "code": "policy_refusal", "type": "safety_refusal",
    "message": "Original provider refusal; preserve this text verbatim.",
    "details": {"request_id": "provider-request:original", "evidence": ["original"]},
}


class AgentTurnRecoveryTests(unittest.TestCase):
    def assert_metadata_only(self, result):
        for key in ("dispatch_authorized", "retries_authorized", "attempt_budgets_reset",
                    "workers_started", "goal_complete", "admitted"):
            self.assertIs(result[key], False, key)
        self.assertIs(result["requires_existing_atomic_claim_and_admission"], True)

    def test_policy_refusal_preserves_original_evidence_and_selects_independent_work(self):
        stopped = observation("refused", error=POLICY_ERROR)
        snapshot = frontier([
            task("refused", keys=["source:refused"], used=1),
            task("dependent", dependencies=["refused"]),
            task("independent", keys=["source:independent"]),
        ], [stopped])
        result = plan_agent_turn_recovery_v1(snapshot)
        self.assertEqual(result["status"], "continue_independent")
        self.assertEqual(result["selected_task_ids"], ["independent"])
        self.assertEqual(result["poll_targets"], [])
        self.assertEqual(result["policy_holds"], [{
            "operation_key": "operation:refused", "task_id": "refused",
            "thread_id": stopped["thread_id"], "turn_id": stopped["turn_id"],
            "error": POLICY_ERROR, "evidence_refs": stopped["evidence_refs"],
        }])
        self.assertIn("policy_refusal_requires_review", decision(result, "refused")["reasons"])
        self.assertEqual(decision(result, "dependent")["unaccepted_dependencies"], ["refused"])
        self.assert_metadata_only(result)

    def test_explicit_structured_policy_codes_and_types_are_terminal(self):
        for selector in ("code", "type"):
            for value in ("policy_refusal", "content_filter", "safety_refusal"):
                with self.subTest(selector=selector, value=value):
                    error = {selector: value, "message": "original refusal"}
                    result = plan_agent_turn_recovery_v1(frontier(
                        [task("stopped")], [observation("stopped", error=error)]))
                    self.assertEqual(result["selected_task_ids"], [])
                    self.assertEqual(result["policy_holds"][0]["error"], error)

    def test_explicit_policy_stop_is_retained_for_every_terminal_status(self):
        for status in ("failed", "interrupted", "completed"):
            with self.subTest(status=status):
                result = plan_agent_turn_recovery_v1(frontier(
                    [task("stopped"), task("renamed", operation="operation:stopped")],
                    [observation("stopped", status=status, error=POLICY_ERROR)]))
                self.assertEqual(len(result["policy_holds"]), 1)
                self.assertEqual(result["policy_holds"][0]["error"], POLICY_ERROR)
                self.assertEqual(result["selected_task_ids"], [])
                self.assertIn("policy_refusal_requires_review", decision(result, "renamed")["reasons"])

    def test_policy_error_keeps_live_or_unknown_original_owner_polled(self):
        for status in ("inProgress", "observation_unavailable"):
            with self.subTest(status=status):
                original = observation("original", status=status, error=POLICY_ERROR, cleanup=False)
                result = plan_agent_turn_recovery_v1(frontier([
                    task("original", keys=["shared"], used=1),
                    task("alias", operation="operation:original"),
                    task("overlap", keys=["shared"]), task("independent"),
                ], [original], width=2))
                self.assertEqual(result["selected_task_ids"], ["independent"])
                self.assertEqual(result["poll_targets"], [{key: original[key] for key in
                                 ("task_id", "thread_id", "turn_id", "status")}])
                self.assertEqual(result["policy_holds"][0]["error"], POLICY_ERROR)
                self.assertIn("policy_refusal_requires_review", decision(result, "alias")["reasons"])
                self.assertIn("exclusive_scope_held", decision(result, "overlap")["reasons"])

    def test_renaming_task_does_not_retry_held_operation(self):
        first = plan_agent_turn_recovery_v1(frontier(
            [task("original")], [observation("original", error=POLICY_ERROR)]))
        second = plan_agent_turn_recovery_v1(frontier([
            task("renamed", operation="operation:original"), task("disjoint"),
        ], holds=first["policy_holds"]))
        self.assertEqual(second["selected_task_ids"], ["disjoint"])
        self.assertEqual(second["policy_holds"], first["policy_holds"])
        self.assertIn("policy_refusal_requires_review", decision(second, "renamed")["reasons"])

    def test_retained_policy_hold_survives_without_current_observation(self):
        first = plan_agent_turn_recovery_v1(frontier(
            [task("original")], [observation("original", error=POLICY_ERROR)]))
        result = plan_agent_turn_recovery_v1(frontier(
            [task("original")], holds=first["policy_holds"]))
        self.assertEqual(result["status"], "review_required")
        self.assertEqual(result["selected_task_ids"], [])
        self.assertEqual(result["policy_holds"], first["policy_holds"])

    def test_later_accepted_completion_cannot_bypass_prior_policy_hold(self):
        first = plan_agent_turn_recovery_v1(frontier(
            [task("original")], [observation("original", error=POLICY_ERROR)]))
        result = plan_agent_turn_recovery_v1(frontier([
            task("renamed", operation="operation:original", used=1),
            task("dependent", dependencies=["renamed"]), task("independent"),
        ], [observation("renamed", status="completed", accepted=True, turn="later-turn")],
            holds=first["policy_holds"]))
        self.assertEqual(result["selected_task_ids"], ["independent"])
        self.assertIn("policy_refusal_requires_review", decision(result, "renamed")["reasons"])
        self.assertIn("dependencies_not_accepted", decision(result, "dependent")["reasons"])
        self.assertEqual(result["policy_holds"], first["policy_holds"])

    def test_repeated_observation_does_not_duplicate_original_policy_hold(self):
        snapshot = frontier([task("stopped")], [observation("stopped", error=POLICY_ERROR)])
        first = plan_agent_turn_recovery_v1(snapshot)
        snapshot["policy_holds"] = first["policy_holds"]
        result = plan_agent_turn_recovery_v1(snapshot)
        self.assertEqual(result["policy_holds"], first["policy_holds"])
        self.assertEqual(len(result["policy_holds"]), 1)

    def test_live_turn_is_polled_by_original_ids_and_never_restarted(self):
        live = observation("live", status="inProgress", cleanup=False,
                           thread="thread:keep-exact", turn="turn:keep-exact")
        result = plan_agent_turn_recovery_v1(frontier(
            [task("live", keys=["scope:live"], used=1), task("other")], [live], width=2))
        self.assertEqual(result["poll_targets"], [{key: live[key] for key in
                         ("task_id", "thread_id", "turn_id", "status")}])
        self.assertEqual(result["selected_task_ids"], ["other"])
        self.assertIn("poll_existing_owner", decision(result, "live")["reasons"])
        self.assert_metadata_only(result)

    def test_unavailable_observation_polls_original_owner_and_keeps_scope(self):
        unknown = observation("unknown", status="observation_unavailable", cleanup=False)
        result = plan_agent_turn_recovery_v1(frontier([
            task("unknown", keys=["scope:shared"], used=1),
            task("overlap", keys=["scope:shared"]), task("independent"),
        ], [unknown], width=2))
        self.assertEqual(result["poll_targets"][0]["thread_id"], unknown["thread_id"])
        self.assertEqual(result["poll_targets"][0]["turn_id"], unknown["turn_id"])
        self.assertEqual(result["selected_task_ids"], ["independent"])
        self.assertIn("exclusive_scope_held", decision(result, "overlap")["reasons"])

    def test_live_status_keeps_scope_even_if_cleanup_flag_claims_true(self):
        result = plan_agent_turn_recovery_v1(frontier([
            task("live", keys=["shared"]), task("overlap", keys=["shared"]),
        ], [observation("live", status="inProgress", cleanup=True)]))
        self.assertEqual(result["selected_task_ids"], [])
        self.assertEqual(len(result["poll_targets"]), 1)
        self.assertIn("exclusive_scope_held", decision(result, "overlap")["reasons"])

    def test_terminal_owner_keeps_shared_scope_until_explicit_cleanup(self):
        result = plan_agent_turn_recovery_v1(frontier([
            task("failed", keys=["shared"]), task("overlap", keys=["shared"]),
            task("disjoint", keys=["other"]),
        ], [observation("failed", cleanup=False)], width=2))
        self.assertEqual(result["selected_task_ids"], ["disjoint"])
        self.assertIn("exclusive_scope_held", decision(result, "overlap")["reasons"])
        self.assertEqual(result["poll_targets"], [])

    def test_unclean_terminal_owner_also_consumes_parallel_capacity(self):
        for status in ("failed", "interrupted", "completed"):
            with self.subTest(status=status):
                result = plan_agent_turn_recovery_v1(frontier([
                    task("original", keys=["original-scope"]), task("independent", keys=["other"]),
                ], [observation("original", status=status, cleanup=False)], width=1))
                self.assertEqual(result["selected_task_ids"], [])
                self.assertIn("parallel_capacity_full", decision(result, "independent")["reasons"])

    def test_confirmed_cleanup_releases_scope_for_different_operation(self):
        result = plan_agent_turn_recovery_v1(frontier([
            task("failed", keys=["shared"], used=1), task("next", keys=["shared"]),
        ], [observation("failed", cleanup=True)], width=1))
        self.assertEqual(result["selected_task_ids"], ["next"])
        self.assertIn("terminal_attempt_preserved", decision(result, "failed")["reasons"])

    def test_parallel_width_includes_live_and_unavailable_owners(self):
        result = plan_agent_turn_recovery_v1(frontier([
            task("live"), task("unknown"), task("first"), task("second"),
        ], [observation("live", status="inProgress", cleanup=False),
            observation("unknown", status="observation_unavailable", cleanup=False)], width=3))
        self.assertEqual(len(result["poll_targets"]), 2)
        self.assertEqual(result["selected_task_ids"], ["first"])
        self.assertIn("parallel_capacity_full", decision(result, "second")["reasons"])

    def test_parallel_selection_has_disjoint_keys_and_unique_operations(self):
        tasks = [task("one", operation="same-operation", keys=["shared"]),
                 task("overlap", keys=["shared"]),
                 task("alias", operation="same-operation", keys=["unrelated"]),
                 task("two", keys=["other"]), task("three", keys=["last"])]
        result = plan_agent_turn_recovery_v1(frontier(tasks, width=2))
        self.assertEqual(result["selected_task_ids"], ["one", "two"])
        self.assertIn("exclusive_scope_held", decision(result, "overlap")["reasons"])
        self.assertIn("operation_already_selected", decision(result, "alias")["reasons"])
        self.assertIn("parallel_capacity_full", decision(result, "three")["reasons"])
        chosen = [row for row in tasks if row["task_id"] in result["selected_task_ids"]]
        self.assertFalse(set(chosen[0]["exclusive_keys"]) & set(chosen[1]["exclusive_keys"]))

    def test_unready_unauthorized_and_exhausted_tasks_are_never_selected(self):
        result = plan_agent_turn_recovery_v1(frontier([
            task("unready", ready=False), task("unauthorized", authorized=False),
            task("exhausted", used=2, limit=2), task("available"),
        ], width=4))
        self.assertEqual(result["selected_task_ids"], ["available"])
        for task_id, reason in (("unready", "not_ready"), ("unauthorized", "not_authorized"),
                                ("exhausted", "attempt_budget_exhausted")):
            self.assertIn(reason, decision(result, task_id)["reasons"])

    def test_spent_attempt_without_observation_requires_reconciliation(self):
        result = plan_agent_turn_recovery_v1(frontier([
            task("unreconciled", used=1, limit=5), task("fresh"),
        ]))
        self.assertEqual(result["selected_task_ids"], ["fresh"])
        self.assertFalse(decision(result, "unreconciled")["selected"])
        self.assertEqual(result["preserved_snapshot"]["tasks"][0]["attempts_used"], 1)
        self.assertIs(result["retries_authorized"], False)

    def test_terminal_attempts_are_preserved_despite_remaining_budget(self):
        for status in ("failed", "interrupted", "completed"):
            with self.subTest(status=status):
                result = plan_agent_turn_recovery_v1(frontier([
                    task("original", used=1, limit=10),
                    task("renamed", operation="operation:original"),
                ], [observation("original", status=status)]))
                self.assertEqual(result["selected_task_ids"], [])
                self.assertIn("terminal_attempt_preserved", decision(result, "original")["reasons"])
                self.assertIn("operation_has_existing_attempt", decision(result, "renamed")["reasons"])

    def test_only_accepted_completed_closed_owner_unlocks_dependency(self):
        result = plan_agent_turn_recovery_v1(frontier([
            task("complete", used=1), task("dependent", dependencies=["complete"]),
        ], [observation("complete", status="completed", accepted=True)]))
        self.assertEqual(result["selected_task_ids"], ["dependent"])
        self.assertIn("completed", decision(result, "complete")["reasons"])
        self.assert_metadata_only(result)

    def test_unaccepted_completed_turn_does_not_unlock_dependencies(self):
        result = plan_agent_turn_recovery_v1(frontier([
            task("complete"), task("dependent", dependencies=["complete"]),
        ], [observation("complete", status="completed", accepted=False)]))
        self.assertEqual(result["selected_task_ids"], [])
        self.assertIn("dependencies_not_accepted", decision(result, "dependent")["reasons"])
        self.assertIs(result["goal_complete"], False)

    def test_acceptance_requires_completed_closed_error_free_owner(self):
        invalid = [observation("original", status="failed", accepted=True),
                   observation("original", status="interrupted", accepted=True),
                   observation("original", status="inProgress", accepted=True),
                   observation("original", status="completed", cleanup=False, accepted=True),
                   observation("original", status="completed", accepted=True, error={"code": "runtime_error"}),
                   observation("original", status="completed", accepted=True, error=POLICY_ERROR)]
        for item in invalid:
            with self.subTest(observation=item), self.assertRaises(ValueError):
                plan_agent_turn_recovery_v1(frontier([task("original")], [item]))

    def test_generic_runtime_error_mentioning_policy_is_not_a_refusal(self):
        error = {"code": "runtime_error", "type": "worker_error",
                 "message": "Policy cache failed while parsing content_filter configuration; retry not attempted."}
        result = plan_agent_turn_recovery_v1(frontier(
            [task("original"), task("independent")], [observation("original", error=error)]))
        self.assertEqual(result["policy_holds"], [])
        self.assertEqual(result["selected_task_ids"], ["independent"])
        self.assertEqual(result["preserved_snapshot"]["observations"][0]["error"], error)

    def test_snapshot_and_attempt_budgets_are_unchanged_and_detached(self):
        snapshot = frontier([task("stopped", used=1, limit=7), task("fresh", limit=9)],
                            [observation("stopped", error=POLICY_ERROR)])
        before = deepcopy(snapshot)
        expected_sha = hashlib.sha256(json.dumps(before, sort_keys=True, separators=(",", ":"),
                                                allow_nan=False).encode()).hexdigest()
        result = plan_agent_turn_recovery_v1(snapshot)
        self.assertEqual(snapshot, before)
        self.assertEqual(result["preserved_snapshot"], before)
        self.assertEqual(result["snapshot_sha256"], expected_sha)
        snapshot["tasks"][0]["max_attempts"] = 1000
        snapshot["observations"][0]["error"]["details"]["evidence"].append("changed")
        self.assertEqual(result["preserved_snapshot"], before)
        self.assertEqual(result["policy_holds"][0]["error"], POLICY_ERROR)
        result["preserved_snapshot"]["tasks"][1]["attempts_used"] = 1000
        self.assertEqual(snapshot["tasks"][1]["attempts_used"], 0)
        self.assert_metadata_only(result)

    def test_unknown_dependencies_and_cycles_fail_closed(self):
        for tasks in ([task("unknown", dependencies=["not-in-frontier"])],
                      [task("self", dependencies=["self"])],
                      [task("one", dependencies=["two"]), task("two", dependencies=["one"])]):
            with self.subTest(tasks=tasks):
                result = plan_agent_turn_recovery_v1(frontier(tasks))
                self.assertEqual(result["selected_task_ids"], [])
                self.assertTrue(all("dependencies_not_accepted" in row["reasons"]
                                    for row in result["task_decisions"]))

    def test_malformed_frontier_fields_fail_closed(self):
        original = frontier([task("one")])
        changes = [("schema", "unknown/v1"), ("frontier_id", ""), ("max_parallel", True),
                   ("max_parallel", 0), ("max_parallel", 65), ("tasks", {}),
                   ("observations", {}), ("policy_holds", None)]
        for key, value in changes:
            snapshot = deepcopy(original)
            snapshot[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                plan_agent_turn_recovery_v1(snapshot)

    def test_malformed_task_fields_fail_closed(self):
        changes = [("task_id", "\x00bad"), ("operation_key", ""), ("depends_on", "one"),
                   ("depends_on", ["one", "one"]), ("exclusive_keys", ["same", "same"]),
                   ("ready", 1), ("authorized", None), ("attempts_used", True),
                   ("attempts_used", -1), ("max_attempts", False), ("max_attempts", 0)]
        for key, value in changes:
            item = task("one")
            item[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                plan_agent_turn_recovery_v1(frontier([item]))

    def test_malformed_observation_fields_fail_closed(self):
        changes = [("task_id", "unknown-task"), ("thread_id", ""), ("turn_id", None),
                   ("status", "running"), ("status", []), ("error", "policy_refusal"),
                   ("cleanup_confirmed", "yes"), ("accepted", 1), ("evidence_refs", "not-a-list")]
        for key, value in changes:
            item = observation("one")
            item[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                plan_agent_turn_recovery_v1(frontier([task("one")], [item]))
        item = observation("one")
        del item["error"]
        with self.assertRaises(ValueError):
            plan_agent_turn_recovery_v1(frontier([task("one")], [item]))

    def test_duplicate_task_observation_and_job_identities_fail_closed(self):
        snapshots = [frontier([task("one"), task("one")]),
                     frontier([task("one")], [observation("one"), observation("one")]),
                     frontier([task("one"), task("two")], [
                         observation("one", thread="same-thread", turn="same-turn"),
                         observation("two", thread="same-thread", turn="same-turn")])]
        for snapshot in snapshots:
            with self.subTest(snapshot=snapshot), self.assertRaises(ValueError):
                plan_agent_turn_recovery_v1(snapshot)

    def test_malformed_or_duplicate_retained_policy_holds_fail_closed(self):
        valid = {"operation_key": "operation:one", "task_id": "one", "thread_id": "thread:one",
                 "turn_id": "turn:one", "error": deepcopy(POLICY_ERROR), "evidence_refs": []}
        invalid = [{**valid, "operation_key": ""}, {**valid, "turn_id": None},
                   {**valid, "error": "refused"}, {**valid, "evidence_refs": "not-a-list"},
                   {**valid, "error": {"code": []}}]
        for item in invalid:
            with self.subTest(hold=item), self.assertRaises(ValueError):
                plan_agent_turn_recovery_v1(frontier([task("one")], holds=[item]))
        with self.assertRaises(ValueError):
            plan_agent_turn_recovery_v1(frontier([task("one")], holds=[valid, deepcopy(valid)]))

    def test_malformed_known_error_selectors_fail_closed(self):
        for key in ("code", "type", "message"):
            for value in ([], {}, 1, True):
                error = {key: value}
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    plan_agent_turn_recovery_v1(frontier(
                        [task("one")], [observation("one", error=error)]))

    def test_nonfinite_nonjson_and_oversized_metadata_fail_closed(self):
        for value in (float("nan"), float("inf"), {"not-json"}, object(), "x" * (4 * 1024 * 1024)):
            snapshot = frontier([task("one")])
            snapshot["evidence"] = value
            with self.subTest(value_type=type(value).__name__), self.assertRaises(ValueError):
                plan_agent_turn_recovery_v1(snapshot)


class AgentTurnRecoveryCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(supervisor_loop.__file__).resolve().parents[3]
        path = root / "scripts/ops/legal_ir/run_autoformal_supervisor.py"
        spec = importlib.util.spec_from_file_location("agent_turn_recovery_cli_test", path)
        if spec is None or spec.loader is None:
            raise AssertionError("canonical supervisor CLI cannot be loaded")
        cls.cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.cli)

    def invoke(self, argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with ExitStack() as stack:
            guards = [stack.enter_context(patch.object(subprocess, name,
                      side_effect=AssertionError("runtime process call: " + name)))
                      for name in ("Popen", "run", "call", "check_call", "check_output")]
            guards.append(stack.enter_context(patch.object(socket, "create_connection",
                          side_effect=AssertionError("network call"))))
            guards.append(stack.enter_context(patch.object(urllib.request, "urlopen",
                          side_effect=AssertionError("provider call"))))
            guards.append(stack.enter_context(patch.object(supervisor_loop, "submit_discrepancies",
                          side_effect=AssertionError("task mutation"))))
            guards.append(stack.enter_context(patch.object(self.cli, "parser",
                          side_effect=AssertionError("native CLI dispatch"))))
            stack.enter_context(redirect_stdout(stdout))
            stack.enter_context(redirect_stderr(stderr))
            code = self.cli.main(argv)
            for guard in guards:
                guard.assert_not_called()
        return code, stdout.getvalue(), stderr.getvalue()

    def write_input(self, root, snapshot=None):
        path = root / "frontier.json"
        path.write_text(json.dumps(snapshot if snapshot is not None else frontier([task("independent")])) + "\n")
        return path

    def test_main_writes_json_metadata_without_task_or_runtime_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.write_input(root)
            before = source.read_bytes()
            output = root / "plan.json"
            code, stdout, stderr = self.invoke(["agent-turn-recovery", "--inputs", str(source),
                                                "--output", str(output)])
            result = json.loads(output.read_bytes())
            self.assertEqual((code, stdout, stderr), (0, "", ""))
            self.assertEqual(result["schema"], "legal-ir-agent-turn-recovery/v1")
            self.assertEqual(result["selected_task_ids"], ["independent"])
            self.assertIs(result["workers_started"], False)
            self.assertIs(result["dispatch_authorized"], False)
            self.assertEqual(source.read_bytes(), before)

    def test_main_emits_json_to_stdout_when_no_output_requested(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.write_input(Path(directory))
            code, stdout, stderr = self.invoke(["agent-turn-recovery", "--inputs", str(source)])
            self.assertEqual((code, stderr), (0, ""))
            self.assertEqual(json.loads(stdout)["selected_task_ids"], ["independent"])

    def test_existing_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.write_input(root)
            output = root / "plan.json"
            original = b"original evidence must survive\n"
            output.write_bytes(original)
            code, stdout, stderr = self.invoke(["agent-turn-recovery", "--inputs", str(source),
                                                "--output", str(output)])
            self.assertEqual((code, stdout), (2, ""))
            self.assertEqual(output.read_bytes(), original)
            self.assertEqual(json.loads(stderr)["schema"], "legal-ir-agent-turn-recovery-error/v1")

    def test_same_input_output_is_rejected_without_changing_input(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.write_input(Path(directory))
            original = source.read_bytes()
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stopped:
                self.cli.main(["agent-turn-recovery", "--inputs", str(source), "--output", str(source)])
            self.assertEqual(stopped.exception.code, 2)
            self.assertEqual(source.read_bytes(), original)

    def test_duplicate_json_keys_fail_closed_without_creating_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "frontier.json"
            source.write_text('{"schema":"legal-ir-agent-turn-frontier/v1","schema":"other"}')
            output = root / "plan.json"
            code, stdout, stderr = self.invoke(["agent-turn-recovery", "--inputs", str(source),
                                                "--output", str(output)])
            self.assertEqual((code, stdout), (2, ""))
            self.assertFalse(output.exists())
            self.assertIn("duplicate", json.loads(stderr)["error"])

    def test_invalid_frontier_reports_json_error_without_creating_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.write_input(root, {"schema": "unknown-frontier/v1"})
            output = root / "plan.json"
            code, stdout, stderr = self.invoke(["agent-turn-recovery", "--inputs", str(source),
                                                "--output", str(output)])
            error = json.loads(stderr)
            self.assertEqual((code, stdout), (2, ""))
            self.assertFalse(output.exists())
            self.assertIs(error["workers_started"], False)
            self.assertIs(error["retries_authorized"], False)

    def test_symlink_input_and_output_are_rejected_without_touching_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.write_input(root)
            original = source.read_bytes()
            input_link = root / "input-link.json"
            input_link.symlink_to(source)
            output = root / "plan.json"
            code, stdout, stderr = self.invoke(["agent-turn-recovery", "--inputs", str(input_link),
                                                "--output", str(output)])
            self.assertEqual((code, stdout), (2, ""))
            self.assertTrue(json.loads(stderr)["error"])
            self.assertFalse(output.exists())
            target = root / "existing.json"
            target.write_bytes(b"retained output evidence")
            output.symlink_to(target)
            code, stdout, stderr = self.invoke(["agent-turn-recovery", "--inputs", str(source),
                                                "--output", str(output)])
            self.assertEqual((code, stdout), (2, ""))
            self.assertTrue(json.loads(stderr)["error"])
            self.assertEqual(target.read_bytes(), b"retained output evidence")
            self.assertEqual(source.read_bytes(), original)


from ipfs_datasets_py.logic.autoformal.supervisor_loop import plan_agent_turn_recovery_v2


def paused_owner_frontier(tasks=None, observations=None, *, width=2):
    """Explicit caller-supplied controls for a previously paused saved owner."""
    snapshot = frontier(
        tasks if tasks is not None else [
            task("owner", keys=["scope:owner"], used=1),
            task("independent", keys=["scope:independent"]),
        ],
        observations if observations is not None else [observation("owner")],
        width=width,
    )
    snapshot.update({
        "schema": "legal-ir-agent-turn-frontier/v2",
        "goal_control": {
            "goal_id": "goal:fixture", "authority_id": "authority:fixture", "owner_task_id": "owner",
            "intent": {"goal_id": "goal:fixture", "authority_id": "authority:fixture",
                       "directive_id": "directive:active", "revision": 2, "state": "active"},
            "observed": {"goal_id": "goal:fixture", "authority_id": "authority:fixture",
                         "directive_id": "directive:paused", "revision": 1, "state": "paused"},
        },
        "execution_hold": None, "operation_history": [], "reconciliation_history": [],
    })
    return snapshot


class PausedOwnerRecoveryV2Tests(unittest.TestCase):
    def assert_metadata_only(self, result):
        for key in ("dispatch_authorized", "retries_authorized", "attempt_budgets_reset",
                    "workers_started", "goal_complete", "admitted",
                    "goal_mutation_authorized", "owner_resume_authorized"):
            self.assertIs(result[key], False, key)
        self.assertIs(result["requires_existing_atomic_claim_and_admission"], True)

    def test_newer_active_intent_selects_authorized_disjoint_work_and_one_reconciliation(self):
        snapshot = paused_owner_frontier([
            task("owner", keys=["scope:owner"], used=1),
            task("first", keys=["scope:shared"]),
            task("overlap", keys=["scope:shared"]),
            task("second", keys=["scope:second"]),
            task("unauthorized", authorized=False),
            task("exhausted", used=2, limit=2),
            task("dependent", dependencies=["owner"]),
        ])
        before = deepcopy(snapshot)
        result = plan_agent_turn_recovery_v2(snapshot)
        self.assertEqual(result["schema"], "legal-ir-agent-turn-recovery/v2")
        self.assertEqual(result["selected_task_ids"], ["first", "second"])
        self.assertEqual(result["poll_targets"], [])
        self.assertIsNone(result["goal_block"])
        self.assertEqual(result["reconciliation_reason"], "reconcile_saved_goal")
        self.assertEqual(len(result["owner_reconciliation_requests"]), 1)
        request = result["owner_reconciliation_requests"][0]
        self.assertEqual(request["action"], "reconcile_saved_goal")
        self.assertEqual(request["goal_id"], "goal:fixture")
        self.assertEqual(request["directive_id"], "directive:active")
        self.assertEqual(request["directive_revision"], 2)
        self.assertEqual(request["desired_state"], "active")
        self.assertEqual(request["expected_owner"], {
            key: before["observations"][0][key]
            for key in ("task_id", "thread_id", "turn_id")
        })
        self.assertEqual(request["expected_goal_observation"], before["goal_control"]["observed"])
        key = {name: request[name] for name in
               ("goal_id", "authority_id", "action", "directive_id", "directive_revision")}
        raw_key = (json.dumps(key, sort_keys=True, separators=(",", ":"),
                              ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
        self.assertEqual(request["request_id"], hashlib.sha256(raw_key).hexdigest())
        self.assertEqual(result["reconciliation_history"], [
            {"request": request, "status": "requested", "result": None}
        ])
        self.assertIn("exclusive_scope_held", decision(result, "overlap")["reasons"])
        self.assertIn("not_authorized", decision(result, "unauthorized")["reasons"])
        self.assertIn("attempt_budget_exhausted", decision(result, "exhausted")["reasons"])
        self.assertIn("dependencies_not_accepted", decision(result, "dependent")["reasons"])
        self.assertEqual(snapshot, before)
        self.assertEqual(result["preserved_snapshot"], before)
        raw = (json.dumps(before, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
        self.assertEqual(result["snapshot_sha256"], hashlib.sha256(raw).hexdigest())
        self.assert_metadata_only(result)

    def test_explicit_pause_blocks_selection_and_owner_reconciliation(self):
        snapshot = paused_owner_frontier()
        snapshot["goal_control"]["intent"]["state"] = "paused"
        result = plan_agent_turn_recovery_v2(snapshot)
        self.assertEqual(result["status"], "goal_paused")
        self.assertEqual(result["goal_block"], "explicit_goal_pause")
        self.assertEqual(result["selected_task_ids"], [])
        self.assertEqual(result["owner_reconciliation_requests"], [])
        self.assertEqual(result["preserved_snapshot"], snapshot)
        self.assertIs(result["preserved_snapshot"]["tasks"][1]["authorized"], True)
        self.assert_metadata_only(result)

    def test_global_execution_hold_preserves_evidence_and_blocks_reconciliation(self):
        snapshot = paused_owner_frontier()
        snapshot["execution_hold"] = {
            "kind": "operator_hold", "reason": "Waiting for an existing review.",
            "evidence_refs": [{"path": "evidence/hold.json", "sha256": "b" * 64}],
        }
        result = plan_agent_turn_recovery_v2(snapshot)
        self.assertEqual(result["status"], "execution_hold")
        self.assertEqual(result["selected_task_ids"], [])
        self.assertEqual(result["owner_reconciliation_requests"], [])
        self.assertEqual(result["execution_hold"], snapshot["execution_hold"])
        self.assertEqual(result["preserved_snapshot"], snapshot)
        self.assert_metadata_only(result)

    def test_same_revision_paused_observation_cannot_be_overridden_by_active_state(self):
        for state in ("paused", "blocked"):
            with self.subTest(state=state):
                snapshot = paused_owner_frontier()
                intent = snapshot["goal_control"]["intent"]
                snapshot["goal_control"]["observed"].update(
                    revision=intent["revision"], directive_id=intent["directive_id"], state=state)
                result = plan_agent_turn_recovery_v2(snapshot)
                self.assertEqual(result["goal_block"], "goal_control_conflict" if state == "paused"
                                 else "blocked_goal_requires_owner_review")
                self.assertEqual(result["selected_task_ids"], [])
                self.assertEqual(result["owner_reconciliation_requests"], [])

    def test_newer_unknown_or_completed_goal_observation_requires_review(self):
        for state, revision, reason in (
                ("active", 3, "newer_goal_control_exists"),
                ("unknown", 1, "goal_state_unknown"),
                ("completed", 1, "completed_goal_requires_owner_review")):
            with self.subTest(state=state, revision=revision):
                snapshot = paused_owner_frontier()
                snapshot["goal_control"]["observed"].update(state=state, revision=revision)
                result = plan_agent_turn_recovery_v2(snapshot)
                self.assertEqual(result["goal_block"], reason)
                self.assertEqual(result["selected_task_ids"], [])
                self.assertEqual(result["owner_reconciliation_requests"], [])

    def test_wrong_goal_or_equal_revision_different_directive_rejected(self):
        for field in ("intent", "observed"):
            with self.subTest(field=field):
                snapshot = paused_owner_frontier()
                snapshot["goal_control"][field]["goal_id"] = "goal:other"
                with self.assertRaises(ValueError):
                    plan_agent_turn_recovery_v2(snapshot)
        snapshot = paused_owner_frontier()
        snapshot["goal_control"]["observed"]["revision"] = 2
        with self.assertRaises(ValueError):
            plan_agent_turn_recovery_v2(snapshot)

    def test_missing_or_mismatched_control_authority_rejected(self):
        for field in ("intent", "observed"):
            for replacement in (None, "", "authority:other"):
                with self.subTest(field=field, replacement=replacement):
                    snapshot = paused_owner_frontier()
                    if replacement is None:
                        del snapshot["goal_control"][field]["authority_id"]
                    else:
                        snapshot["goal_control"][field]["authority_id"] = replacement
                    with self.assertRaises(ValueError):
                        plan_agent_turn_recovery_v2(snapshot)

    def test_live_or_unknown_owner_is_polled_exactly_and_keeps_scopes_and_capacity(self):
        for status in ("inProgress", "observation_unavailable"):
            with self.subTest(status=status):
                original = observation("owner", status=status, cleanup=False,
                                       thread="thread:original", turn="turn:original")
                snapshot = paused_owner_frontier([
                    task("owner", keys=["scope:held"], used=1),
                    task("overlap", keys=["scope:held"]), task("first"), task("second"),
                ], [original])
                result = plan_agent_turn_recovery_v2(snapshot)
                self.assertEqual(result["poll_targets"], [{
                    key: original[key] for key in ("task_id", "thread_id", "turn_id", "status")
                }])
                self.assertEqual(result["selected_task_ids"], ["first"])
                self.assertEqual(result["occupied_slots"], 1)
                self.assertIn("exclusive_scope_held", decision(result, "overlap")["reasons"])
                self.assertIn("parallel_capacity_full", decision(result, "second")["reasons"])
                self.assertEqual(result["reconciliation_reason"], "poll_existing_owner")
                self.assertEqual(result["owner_reconciliation_requests"], [])
                self.assert_metadata_only(result)

    def test_owner_polling_continues_under_explicit_pause_or_global_hold(self):
        for blocker in ("pause", "hold"):
            with self.subTest(blocker=blocker):
                original = observation("owner", status="observation_unavailable", cleanup=False)
                snapshot = paused_owner_frontier(observations=[original])
                if blocker == "pause":
                    snapshot["goal_control"]["intent"]["state"] = "paused"
                else:
                    snapshot["execution_hold"] = {
                        "kind": "operator_hold", "reason": "Existing review.", "evidence_refs": []}
                result = plan_agent_turn_recovery_v2(snapshot)
                self.assertEqual(result["selected_task_ids"], [])
                self.assertEqual(result["poll_targets"], [{
                    key: original[key] for key in ("task_id", "thread_id", "turn_id", "status")
                }])
                self.assertEqual(result["owner_reconciliation_requests"], [])

    def test_unclean_terminal_owner_reserves_capacity_without_reconciliation(self):
        for status in ("failed", "interrupted", "completed"):
            with self.subTest(status=status):
                snapshot = paused_owner_frontier(
                    observations=[observation("owner", status=status, cleanup=False)], width=1)
                result = plan_agent_turn_recovery_v2(snapshot)
                self.assertEqual(result["selected_task_ids"], [])
                self.assertEqual(result["owner_reconciliation_requests"], [])
                self.assertEqual(result["reconciliation_reason"], "owner_cleanup_required")
                self.assertEqual(result["cleanup_required"], ["owner"])
                self.assertEqual(result["occupied_slots"], 1)
                self.assertIn("parallel_capacity_full", decision(result, "independent")["reasons"])

    def test_owner_error_requires_review_while_disjoint_work_can_continue(self):
        for error in ({"code": "transport_error", "message": "Original failure."}, POLICY_ERROR):
            with self.subTest(error=error):
                snapshot = paused_owner_frontier(observations=[observation("owner", error=error)])
                result = plan_agent_turn_recovery_v2(snapshot)
                self.assertEqual(result["selected_task_ids"], ["independent"])
                self.assertEqual(result["owner_reconciliation_requests"], [])
                self.assertEqual(result["reconciliation_reason"], "owner_error_requires_review")
                self.assertEqual(result["operation_history"][0]["observation"]["error"], error)

    def test_retained_attempt_survives_omission_and_blocks_renamed_operation(self):
        for status in ("failed", "completed", "observation_unavailable"):
            with self.subTest(status=status):
                original = observation("old", status=status, cleanup=status != "observation_unavailable",
                                       accepted=status == "completed",
                                       thread="thread:old", turn="turn:old")
                first = plan_agent_turn_recovery_v2(paused_owner_frontier([
                    task("owner", used=1), task("old", keys=["scope:old"], used=2, limit=3),
                ], [observation("owner"), original]))
                snapshot = paused_owner_frontier([
                    task("owner", used=1),
                    task("renamed", operation="operation:old", used=0, limit=50),
                    task("overlap", keys=["scope:old"]), task("independent"),
                ], width=3)
                snapshot["operation_history"] = deepcopy(first["operation_history"])
                snapshot["reconciliation_history"] = deepcopy(first["reconciliation_history"])
                result = plan_agent_turn_recovery_v2(snapshot)
                self.assertNotIn("renamed", result["selected_task_ids"])
                self.assertIn("operation_has_existing_attempt", decision(result, "renamed")["reasons"])
                retained = next(entry for entry in result["operation_history"]
                                if entry["task"]["operation_key"] == "operation:old")
                self.assertEqual(retained, {"task": first["operation_history"][1]["task"],
                                            "observation": original})
                self.assertEqual(retained["task"]["attempts_used"], 2)
                self.assertEqual(retained["task"]["max_attempts"], 3)
                self.assertIn("independent", result["selected_task_ids"])
                if status == "observation_unavailable":
                    self.assertEqual(result["poll_targets"], [{
                        key: original[key] for key in ("task_id", "thread_id", "turn_id", "status")
                    }])
                    self.assertIn("exclusive_scope_held", decision(result, "overlap")["reasons"])
                self.assert_metadata_only(result)

    def test_retained_policy_refusal_cannot_be_erased_by_omitting_original_task(self):
        original = observation("old", error=POLICY_ERROR)
        first = plan_agent_turn_recovery_v2(paused_owner_frontier([
            task("owner", used=1), task("old", used=1),
        ], [observation("owner"), original]))
        snapshot = paused_owner_frontier([
            task("owner", used=1), task("renamed", operation="operation:old"), task("independent"),
        ])
        snapshot["operation_history"] = deepcopy(first["operation_history"])
        snapshot["reconciliation_history"] = deepcopy(first["reconciliation_history"])
        result = plan_agent_turn_recovery_v2(snapshot)
        self.assertEqual(result["selected_task_ids"], ["independent"])
        self.assertIn("policy_refusal_requires_review", decision(result, "renamed")["reasons"])
        self.assertEqual(result["policy_holds"][0]["error"], POLICY_ERROR)
        self.assertEqual(result["policy_holds"][0]["thread_id"], original["thread_id"])

    def test_retained_live_owner_can_be_omitted_but_keeps_exact_poll_and_capacity(self):
        original = observation("owner", status="inProgress", cleanup=False)
        first = plan_agent_turn_recovery_v2(paused_owner_frontier(
            [task("owner", keys=["scope:owner"], used=1)], [original], width=1))
        snapshot = paused_owner_frontier([
            task("overlap", keys=["scope:owner"]), task("independent"),
        ], [], width=1)
        snapshot["operation_history"] = deepcopy(first["operation_history"])
        snapshot["reconciliation_history"] = deepcopy(first["reconciliation_history"])
        result = plan_agent_turn_recovery_v2(snapshot)
        self.assertEqual(result["selected_task_ids"], [])
        self.assertEqual(result["poll_targets"], [{
            key: original[key] for key in ("task_id", "thread_id", "turn_id", "status")
        }])
        self.assertEqual(result["occupied_slots"], 1)
        self.assertEqual(result["owner_reconciliation_requests"], [])
        self.assertIn("parallel_capacity_full", decision(result, "independent")["reasons"])

    def test_retained_spent_budgets_scopes_and_owner_ids_cannot_be_rewritten(self):
        original_snapshot = paused_owner_frontier([
            task("owner", keys=["scope:owner"], used=2, limit=3), task("independent"),
        ])
        first = plan_agent_turn_recovery_v2(original_snapshot)
        mutations = (
            ("task", "attempts_used", 1), ("task", "max_attempts", 50),
            ("task", "operation_key", "operation:replacement"),
            ("task", "exclusive_keys", ["scope:replacement"]),
            ("observation", "thread_id", "thread:replacement"),
            ("observation", "turn_id", "turn:replacement"),
            ("observation", "status", "completed"),
            ("observation", "error", {"code": "replacement_error"}),
        )
        for kind, field, value in mutations:
            with self.subTest(kind=kind, field=field):
                snapshot = deepcopy(original_snapshot)
                snapshot["operation_history"] = deepcopy(first["operation_history"])
                snapshot["reconciliation_history"] = deepcopy(first["reconciliation_history"])
                target = snapshot["tasks"][0] if kind == "task" else snapshot["observations"][0]
                target[field] = value
                with self.assertRaises(ValueError):
                    plan_agent_turn_recovery_v2(snapshot)

    def test_reconciliation_request_never_reissues_across_frontiers_and_all_outcomes(self):
        first = plan_agent_turn_recovery_v2(paused_owner_frontier())
        original_request = first["owner_reconciliation_requests"][0]
        for status in ("requested", "completed", "failed", "unknown"):
            with self.subTest(status=status):
                snapshot = paused_owner_frontier()
                snapshot["frontier_id"] = "frontier:later:" + status
                snapshot["operation_history"] = deepcopy(first["operation_history"])
                entry = {"request": deepcopy(original_request), "status": status,
                         "result": None if status == "requested" else {"receipt": "receipt:" + status}}
                snapshot["reconciliation_history"] = [entry]
                before = deepcopy(snapshot)
                result = plan_agent_turn_recovery_v2(snapshot)
                self.assertEqual(result["selected_task_ids"], ["independent"])
                self.assertEqual(result["owner_reconciliation_requests"], [])
                self.assertEqual(result["reconciliation_reason"],
                                 "existing_reconciliation_pending" if status in ("requested", "unknown")
                                 else "pause_cycle_already_reconciled")
                self.assertEqual(result["pending_owner_reconciliation_ids"],
                                 [original_request["request_id"]] if status in ("requested", "unknown") else [])
                self.assertEqual(result["reconciliation_history"], [entry])
                self.assertEqual(snapshot, before)
                self.assert_metadata_only(result)

    def test_duplicate_or_changed_reconciliation_identity_rejected(self):
        first = plan_agent_turn_recovery_v2(paused_owner_frontier())
        for change in ("duplicate", "request_id", "goal_id", "directive_revision"):
            with self.subTest(change=change):
                snapshot = paused_owner_frontier()
                snapshot["reconciliation_history"] = deepcopy(first["reconciliation_history"])
                if change == "duplicate":
                    snapshot["reconciliation_history"] *= 2
                else:
                    snapshot["reconciliation_history"][0]["request"][change] = (
                        3 if change == "directive_revision" else "changed:identity")
                with self.assertRaises(ValueError):
                    plan_agent_turn_recovery_v2(snapshot)

    def test_missing_explicit_controls_histories_or_owner_observation_rejected(self):
        for field in ("goal_control", "execution_hold", "operation_history", "reconciliation_history"):
            with self.subTest(field=field):
                snapshot = paused_owner_frontier()
                del snapshot[field]
                with self.assertRaises(ValueError):
                    plan_agent_turn_recovery_v2(snapshot)
        for field in ("intent", "observed", "owner_task_id", "authority_id"):
            with self.subTest(control_field=field):
                snapshot = paused_owner_frontier()
                del snapshot["goal_control"][field]
                with self.assertRaises(ValueError):
                    plan_agent_turn_recovery_v2(snapshot)
        snapshot = paused_owner_frontier(observations=[])
        with self.assertRaises(ValueError):
            plan_agent_turn_recovery_v2(snapshot)

    def test_v1_rejects_v2_controls_instead_of_ignoring_them(self):
        v2 = paused_owner_frontier()
        for field in ("goal_control", "execution_hold", "operation_history", "reconciliation_history"):
            with self.subTest(field=field):
                snapshot = frontier([task("independent")])
                snapshot[field] = deepcopy(v2[field])
                with self.assertRaises(ValueError):
                    plan_agent_turn_recovery_v1(snapshot)
        with self.assertRaises(ValueError):
            plan_agent_turn_recovery_v1(v2)

    def test_older_blocked_goal_is_barrier_and_already_active_goal_never_reconciles(self):
        for state in ("blocked", "active"):
            with self.subTest(state=state):
                snapshot = paused_owner_frontier()
                snapshot["goal_control"]["observed"]["state"] = state
                result = plan_agent_turn_recovery_v2(snapshot)
                self.assertEqual(result["owner_reconciliation_requests"], [])
                if state == "blocked":
                    self.assertEqual(result["goal_block"], "blocked_goal_requires_owner_review")
                    self.assertEqual(result["selected_task_ids"], [])
                else:
                    self.assertIsNone(result["goal_block"])
                    self.assertIsNone(result["reconciliation_reason"])
                    self.assertEqual(result["selected_task_ids"], ["independent"])

    def test_directive_ordering_domain_is_immutable_across_controls_and_history(self):
        first = plan_agent_turn_recovery_v2(paused_owner_frontier())
        for change in ("same_id_new_revision", "same_revision_new_id", "intent_rollback",
                       "historical_pause_id_new_revision", "authority_domain_changed"):
            with self.subTest(change=change):
                snapshot = paused_owner_frontier()
                snapshot["reconciliation_history"] = deepcopy(first["reconciliation_history"])
                if change == "same_id_new_revision":
                    snapshot["goal_control"]["intent"]["revision"] = 3
                elif change == "same_revision_new_id":
                    snapshot["goal_control"]["intent"]["directive_id"] = "directive:replacement"
                elif change == "intent_rollback":
                    snapshot["goal_control"]["intent"].update(revision=1, directive_id="directive:paused")
                elif change == "historical_pause_id_new_revision":
                    snapshot["reconciliation_history"][0]["request"]["expected_goal_observation"]["revision"] = 0
                else:
                    snapshot["goal_control"]["authority_id"] = "authority:other"
                    for field in ("intent", "observed"):
                        snapshot["goal_control"][field]["authority_id"] = "authority:other"
                with self.assertRaises(ValueError):
                    plan_agent_turn_recovery_v2(snapshot)
        snapshot = paused_owner_frontier()
        snapshot["goal_control"]["observed"]["directive_id"] = "directive:active"
        with self.assertRaises(ValueError):
            plan_agent_turn_recovery_v2(snapshot)

    def test_new_resume_directive_cannot_reissue_same_pause_cycle_for_any_outcome(self):
        first = plan_agent_turn_recovery_v2(paused_owner_frontier())
        old_id = first["owner_reconciliation_requests"][0]["request_id"]
        for status in ("requested", "unknown", "completed", "failed"):
            with self.subTest(status=status):
                snapshot = paused_owner_frontier()
                snapshot["frontier_id"] = "frontier:replacement:" + status
                snapshot["goal_control"]["intent"].update(revision=3, directive_id="directive:active:new")
                snapshot["operation_history"] = deepcopy(first["operation_history"])
                snapshot["reconciliation_history"] = deepcopy(first["reconciliation_history"])
                snapshot["reconciliation_history"][0].update(
                    status=status, result=None if status == "requested" else {"receipt": "receipt:" + status})
                result = plan_agent_turn_recovery_v2(snapshot)
                self.assertEqual(result["selected_task_ids"], ["independent"])
                self.assertEqual(result["owner_reconciliation_requests"], [])
                self.assertEqual(result["reconciliation_history"], snapshot["reconciliation_history"])
                self.assertEqual(result["reconciliation_reason"],
                                 "existing_reconciliation_pending" if status in ("requested", "unknown")
                                 else "pause_cycle_already_reconciled")
                self.assertEqual(result["pending_owner_reconciliation_ids"],
                                 [old_id] if status in ("requested", "unknown") else [])

    def test_new_pause_cycle_waits_for_old_reconciliation_to_close(self):
        first = plan_agent_turn_recovery_v2(paused_owner_frontier())
        old_id = first["owner_reconciliation_requests"][0]["request_id"]
        for status in ("requested", "unknown", "completed", "failed"):
            with self.subTest(status=status):
                snapshot = paused_owner_frontier()
                snapshot["goal_control"]["observed"].update(
                    revision=3, directive_id="directive:paused:new")
                snapshot["goal_control"]["intent"].update(
                    revision=4, directive_id="directive:active:new")
                snapshot["operation_history"] = deepcopy(first["operation_history"])
                snapshot["reconciliation_history"] = deepcopy(first["reconciliation_history"])
                snapshot["reconciliation_history"][0].update(
                    status=status, result=None if status == "requested" else {"receipt": "receipt:" + status})
                result = plan_agent_turn_recovery_v2(snapshot)
                self.assertEqual(result["selected_task_ids"], ["independent"])
                if status in ("requested", "unknown"):
                    self.assertEqual(result["owner_reconciliation_requests"], [])
                    self.assertEqual(result["pending_owner_reconciliation_ids"], [old_id])
                    self.assertEqual(result["reconciliation_reason"], "existing_reconciliation_pending")
                else:
                    self.assertEqual(len(result["owner_reconciliation_requests"]), 1)
                    request = result["owner_reconciliation_requests"][0]
                    self.assertNotEqual(request["request_id"], old_id)
                    self.assertEqual(request["directive_revision"], 4)
                    self.assertEqual(request["expected_goal_observation"], snapshot["goal_control"]["observed"])
                    self.assertEqual(result["pending_owner_reconciliation_ids"], [request["request_id"]])
                    self.assertEqual(result["reconciliation_history"][0], snapshot["reconciliation_history"][0])

    def test_historical_live_policy_refusal_survives_later_clean_completion(self):
        for status in ("inProgress", "observation_unavailable"):
            with self.subTest(status=status):
                original = observation("old", status=status, error=POLICY_ERROR, cleanup=False)
                tasks = [task("owner", used=1), task("old", used=1),
                         task("renamed", operation="operation:old"), task("independent")]
                first = plan_agent_turn_recovery_v2(paused_owner_frontier(
                    tasks, [observation("owner"), original], width=3))
                closed = observation("old", status="completed", accepted=True,
                                     thread=original["thread_id"], turn=original["turn_id"])
                snapshot = paused_owner_frontier(tasks, [observation("owner"), closed], width=3)
                snapshot["operation_history"] = deepcopy(first["operation_history"])
                snapshot["reconciliation_history"] = deepcopy(first["reconciliation_history"])
                result = plan_agent_turn_recovery_v2(snapshot)
                self.assertEqual(result["selected_task_ids"], ["independent"])
                self.assertEqual(result["policy_holds"], first["policy_holds"])
                self.assertEqual(result["policy_holds"][0]["error"], POLICY_ERROR)
                self.assertIn("policy_refusal_requires_review", decision(result, "old")["reasons"])
                self.assertIn("policy_refusal_requires_review", decision(result, "renamed")["reasons"])
                later = paused_owner_frontier([
                    task("owner", used=1), task("alias", operation="operation:old"), task("independent"),
                ])
                later["operation_history"] = deepcopy(result["operation_history"])
                later["reconciliation_history"] = deepcopy(result["reconciliation_history"])
                later["policy_holds"] = deepcopy(result["policy_holds"])
                third = plan_agent_turn_recovery_v2(later)
                self.assertEqual(third["selected_task_ids"], ["independent"])
                self.assertEqual(third["policy_holds"], first["policy_holds"])
                self.assertIn("policy_refusal_requires_review", decision(third, "alias")["reasons"])

    def test_higher_spent_count_with_retained_observation_is_preserved_and_never_reset(self):
        first = plan_agent_turn_recovery_v2(paused_owner_frontier([
            task("owner", used=1, limit=3), task("independent"),
        ]))
        snapshot = paused_owner_frontier([
            task("owner", used=3, limit=3), task("independent"),
        ], [])
        snapshot["operation_history"] = deepcopy(first["operation_history"])
        snapshot["reconciliation_history"] = deepcopy(first["reconciliation_history"])
        result = plan_agent_turn_recovery_v2(snapshot)
        self.assertEqual(result["selected_task_ids"], ["independent"])
        saved = next(entry for entry in result["operation_history"]
                     if entry["task"]["task_id"] == "owner")
        self.assertEqual(saved["task"]["attempts_used"], 3)
        self.assertEqual(saved["task"]["max_attempts"], 3)
        self.assertEqual(saved["observation"], first["operation_history"][0]["observation"])
        self.assertIn("attempt_budget_exhausted", decision(result, "owner")["reasons"])
        self.assert_metadata_only(result)
        snapshot["operation_history"] = deepcopy(result["operation_history"])
        snapshot["tasks"][0]["attempts_used"] = 2
        with self.assertRaises(ValueError):
            plan_agent_turn_recovery_v2(snapshot)

    def test_saved_pause_cannot_roll_back_or_precede_closed_reconciliation(self):
        for prior_pause, prior_resume, newer_pause in ((3, 4, 1), (1, 4, 3)):
            with self.subTest(prior_pause=prior_pause, newer_pause=newer_pause):
                original = paused_owner_frontier()
                original['goal_control']['observed'].update(revision=prior_pause, directive_id='pause:old')
                original['goal_control']['intent'].update(revision=prior_resume, directive_id='run:old')
                prior = plan_agent_turn_recovery_v2(original)
                snapshot = paused_owner_frontier()
                snapshot['goal_control']['observed'].update(revision=newer_pause, directive_id='pause:older')
                snapshot['goal_control']['intent'].update(revision=5, directive_id='run:new')
                snapshot['reconciliation_history'] = deepcopy(prior['reconciliation_history'])
                snapshot['reconciliation_history'][0]['status'] = 'completed'
                snapshot['reconciliation_history'][0]['result'] = {'goal_update_confirmed': True}
                with self.assertRaises(ValueError):
                    plan_agent_turn_recovery_v2(snapshot)


class GoalAwareRecoveryCliTests(unittest.TestCase):
    setUpClass = classmethod(AgentTurnRecoveryCliTests.setUpClass.__func__)
    invoke = AgentTurnRecoveryCliTests.invoke
    write_input = AgentTurnRecoveryCliTests.write_input

    def test_cli_routes_v2_to_goal_aware_planner(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.write_input(Path(directory), paused_owner_frontier())
            code, stdout, stderr = self.invoke(['agent-turn-recovery', '--inputs', str(source)])
            self.assertEqual((code, stderr), (0, ''))
            result = json.loads(stdout)
            self.assertEqual(result['schema'], 'legal-ir-agent-turn-recovery/v2')
            self.assertEqual(result['selected_task_ids'], ['independent'])
            self.assertEqual(len(result['owner_reconciliation_requests']), 1)
            self.assertFalse(result['goal_mutation_authorized'])

    def test_cli_preserves_explicit_goal_pause(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = paused_owner_frontier()
            snapshot['goal_control']['intent']['state'] = 'paused'
            source = self.write_input(Path(directory), snapshot)
            code, stdout, stderr = self.invoke(['agent-turn-recovery', '--inputs', str(source)])
            self.assertEqual((code, stderr), (0, ''))
            result = json.loads(stdout)
            self.assertEqual(result['status'], 'goal_paused')
            self.assertEqual(result['selected_task_ids'], [])
            self.assertEqual(result['owner_reconciliation_requests'], [])


if __name__ == "__main__":
    unittest.main()


class AgentTurnObservationCheckpointTests(unittest.TestCase):
    def snapshot(self):
        result = paused_owner_frontier(observations=[
            observation('owner', status='inProgress', cleanup=False)])
        result['goal_control']['observed'] = deepcopy(result['goal_control']['intent'])
        return result

    def event(self, *, cleanup=True):
        return {
            'schema': 'legal-ir-agent-turn-observation/v1', 'task_id': 'owner',
            'thread_id': 'original-thread:owner',
            'turn': {'id': 'original-turn:owner', 'status': 'failed',
                     'error': {'message': 'This content was flagged for possible cybersecurity risk.',
                               'details': {'original': ['preserved']}}},
            'cleanup_confirmed': cleanup, 'accepted': False,
            'evidence_refs': [{'path': 'saved/owner-turn.json', 'sha256': 'b' * 64}],
        }

    def prepare(self, snapshot=None, event=None):
        result = supervisor_loop.prepare_agent_turn_recovery_checkpoint_v1(
            self.snapshot() if snapshot is None else snapshot,
            self.event() if event is None else event)
        for key in ('dispatch_authorized', 'retries_authorized', 'attempt_budgets_reset',
                    'workers_started', 'owner_resume_authorized', 'goal_mutation_authorized',
                    'goal_complete', 'admitted'):
            self.assertIs(result[key], False, key)
        self.assertIs(result['requires_durable_checkpoint_before_claim'], True)
        return result

    def test_actual_refusal_holds_aliases_and_dependents_but_not_independent_work(self):
        snapshot = self.snapshot()
        snapshot['tasks'] += [task('alias', operation='operation:owner'),
                              task('dependent', dependencies=['owner']),
                              task('unauthorized', authorized=False)]
        result = self.prepare(snapshot)
        self.assertEqual(result['selected_task_ids'], ['independent'])
        self.assertEqual(result['policy_holds'][0]['error'], self.event()['turn']['error'])
        self.assertEqual(result['policy_holds'][0]['evidence_refs'], self.event()['evidence_refs'])
        self.assertIn('policy_refusal_requires_review', decision(result, 'alias')['reasons'])
        self.assertEqual(decision(result, 'dependent')['unaccepted_dependencies'], ['owner'])

    def test_checkpoint_preserves_inputs_and_binds_exact_json(self):
        snapshot, event = self.snapshot(), self.event()
        originals = deepcopy((snapshot, event))
        result = self.prepare(snapshot, event)
        self.assertEqual((snapshot, event), originals)
        checkpoint = result['observation_checkpoint']
        self.assertEqual(checkpoint['event'], event)
        for key, value in [('input_frontier_sha256', snapshot), ('event_sha256', event),
                           ('next_frontier_sha256', result['next_frontier'])]:
            self.assertEqual(checkpoint[key], hashlib.sha256(
                supervisor_loop._handoff_reconciliation_bytes_v2(value)).hexdigest())

    def test_duplicate_delivery_preserves_counters_holds_and_next_frontier(self):
        first = self.prepare()
        second = self.prepare(first['next_frontier'])
        self.assertEqual(first['next_frontier'], second['next_frontier'])
        self.assertEqual(len(second['policy_holds']), 1)
        self.assertEqual(second['owner_reconciliation_requests'], [])
        self.assertEqual(second['next_frontier']['tasks'][0]['attempts_used'], 1)

    def test_digest_binds_consumed_snapshot_despite_later_caller_mutation(self):
        snapshot = self.snapshot()
        serializer = supervisor_loop._handoff_reconciliation_bytes_v2
        original = serializer(snapshot)
        def mutate_after_serialization(value):
            raw = serializer(value)
            if value is snapshot: snapshot['frontier_id'] = 'caller-mutated-after-read'
            return raw
        with patch.object(supervisor_loop, '_handoff_reconciliation_bytes_v2',
                          side_effect=mutate_after_serialization):
            result = self.prepare(snapshot)
        self.assertEqual(result['observation_checkpoint']['input_frontier_sha256'],
                         hashlib.sha256(original).hexdigest())
        self.assertEqual(result['next_frontier']['frontier_id'], 'frontier:original')

    def test_refusal_evidence_cannot_be_rewritten_into_unreplayable_checkpoint(self):
        first = self.prepare(); event = self.event()
        event['evidence_refs'] = [{'path': 'replacement.json', 'sha256': 'c' * 64}]
        with self.assertRaisesRegex(ValueError, 'evidence cannot be rewritten'):
            self.prepare(first['next_frontier'], event)

    def test_wrong_task_thread_or_turn_refused(self):
        for field in ('task_id', 'thread_id', 'turn'):
            event = self.event()
            if field == 'turn': event['turn']['id'] = 'replacement-turn'
            else: event[field] = 'replacement-owner'
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.prepare(event=event)

    def test_missing_or_unavailable_provider_turn_refused(self):
        for value in (None, {}, {'id': 'original-turn:owner',
                                 'status': 'observation_unavailable', 'error': None}):
            event = self.event(); event['turn'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.prepare(event=event)

    def test_existing_attempt_must_remain_charged(self):
        snapshot = self.snapshot(); snapshot['tasks'][0]['attempts_used'] = 0
        with self.assertRaisesRegex(ValueError, 'charged'):
            self.prepare(snapshot)

    def test_terminal_status_does_not_infer_cleanup(self):
        snapshot = self.snapshot()
        snapshot['tasks'].append(task('overlap', keys=['scope:owner']))
        result = self.prepare(snapshot, self.event(cleanup=False))
        self.assertEqual(result['cleanup_required'], ['owner'])
        self.assertEqual(result['occupied_slots'], 1)
        self.assertEqual(result['selected_task_ids'], ['independent'])
        self.assertIn('exclusive_scope_held', decision(result, 'overlap')['reasons'])

    def test_live_owner_keeps_original_poll_target(self):
        event = self.event(cleanup=False)
        event['turn'].update(status='inProgress', error=None)
        result = self.prepare(event=event)
        self.assertEqual(result['poll_targets'], [{
            'task_id': 'owner', 'thread_id': event['thread_id'],
            'turn_id': event['turn']['id'], 'status': 'inProgress'}])

    def test_live_owner_cannot_claim_cleanup_or_acceptance(self):
        for field in ('cleanup_confirmed', 'accepted'):
            event = self.event(cleanup=False)
            event['turn'].update(status='inProgress', error=None); event[field] = True
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.prepare(event=event)

    def test_refusal_cannot_be_accepted(self):
        event = self.event(); event['accepted'] = True
        with self.assertRaises(ValueError): self.prepare(event=event)

    def test_terminal_error_or_status_cannot_be_rewritten(self):
        first = self.prepare()
        for change in ('error', 'status'):
            event = self.event()
            if change == 'error': event['turn']['error'] = None
            else: event['turn']['status'] = 'completed'
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.prepare(first['next_frontier'], event)

    def test_later_cleanup_evidence_preserves_refusal_and_spent_attempt(self):
        first = self.prepare(event=self.event(cleanup=False))
        second = self.prepare(first['next_frontier'])
        self.assertEqual(second['cleanup_required'], [])
        self.assertEqual(second['policy_holds'], first['policy_holds'])
        self.assertEqual(second['next_frontier']['tasks'][0]['attempts_used'], 1)

    def test_explicit_pause_and_runwide_hold_block_independent_selection(self):
        for mode in ('pause', 'hold'):
            snapshot = self.snapshot()
            if mode == 'pause': snapshot['goal_control']['intent']['state'] = 'paused'
            else: snapshot['execution_hold'] = {
                'kind': 'usage_limit', 'reason': 'original restriction', 'evidence_refs': []}
            result = self.prepare(snapshot)
            with self.subTest(mode=mode):
                self.assertEqual(result['selected_task_ids'], [])
                self.assertEqual(len(result['policy_holds']), 1)

    def test_original_omitted_from_frontier_is_recovered_only_from_retained_history(self):
        first = self.prepare()
        snapshot = deepcopy(first['next_frontier'])
        snapshot['tasks'] = [row for row in snapshot['tasks'] if row['task_id'] != 'owner']
        snapshot['observations'] = []
        snapshot['tasks'].append(task('renamed', operation='operation:owner'))
        result = self.prepare(snapshot)
        self.assertEqual(result['policy_holds'], first['policy_holds'])
        self.assertIn('policy_refusal_requires_review', decision(result, 'renamed')['reasons'])

    def test_completed_provider_turn_alone_is_not_task_acceptance(self):
        event = self.event(); event['turn'].update(status='completed', error=None)
        snapshot = self.snapshot(); snapshot['tasks'].append(task('dependent', dependencies=['owner']))
        result = self.prepare(snapshot, event)
        self.assertEqual(decision(result, 'dependent')['unaccepted_dependencies'], ['owner'])

    def test_malformed_event_is_rejected(self):
        for change in ('extra', 'schema', 'cleanup_confirmed', 'evidence_refs'):
            event = self.event()
            event[change] = {'extra': True} if change == 'extra' else 'invalid'
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.prepare(event=event)

    def test_observation_ingestion_is_metadata_only(self):
        snapshot, event = self.snapshot(), self.event()
        with ExitStack() as stack:
            guards = [stack.enter_context(patch.object(Path, name,
                      side_effect=AssertionError('filesystem access'))) for name in ('open', 'read_bytes')]
            guards += [stack.enter_context(patch.object(subprocess, name,
                       side_effect=AssertionError('process call'))) for name in ('Popen', 'run')]
            guards.append(stack.enter_context(patch.object(socket, 'create_connection',
                          side_effect=AssertionError('network call'))))
            self.prepare(snapshot, event)
            for guard in guards: guard.assert_not_called()


class AgentTurnObservationCheckpointCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        AgentTurnRecoveryCliTests.setUpClass()
        cls.cli = AgentTurnRecoveryCliTests.cli

    invoke = AgentTurnRecoveryCliTests.invoke

    def inputs(self, root):
        fixture = AgentTurnObservationCheckpointTests()
        source, event = root/'frontier.json', root/'turn.json'
        source.write_text(json.dumps(fixture.snapshot()))
        event.write_text(json.dumps(fixture.event()))
        return source, event, root/'checkpoint.json'

    def argv(self, source, event, output):
        return ['agent-turn-recovery', '--inputs', str(source), '--observation', str(event),
                '--output', str(output)]

    def test_cli_ingests_refusal_and_syncs_checkpoint_and_directory(self):
        import os
        with tempfile.TemporaryDirectory() as directory:
            source, event, output = self.inputs(Path(directory))
            original = (source.read_bytes(), event.read_bytes())
            with patch.object(self.cli.os, 'fsync', wraps=os.fsync) as synced:
                code, stdout, stderr = self.invoke(self.argv(source, event, output))
            self.assertEqual((code, stdout, stderr), (0, '', ''))
            self.assertEqual(synced.call_count, 2)
            result = json.loads(output.read_bytes())
            self.assertEqual(result['selected_task_ids'], ['independent'])
            self.assertEqual(len(result['next_frontier']['policy_holds']), 1)
            self.assertEqual((source.read_bytes(), event.read_bytes()), original)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)

    def test_observation_mode_requires_output_before_any_input_read(self):
        with patch.object(self.cli, '_read_handoff_metadata_v2') as read:
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stopped:
                self.cli.main(['agent-turn-recovery', '--inputs', 'frontier.json',
                               '--observation', 'turn.json'])
        self.assertEqual(stopped.exception.code, 2); read.assert_not_called()

    def test_existing_checkpoint_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            source, event, output = self.inputs(Path(directory)); output.write_bytes(b'original evidence')
            code, stdout, stderr = self.invoke(self.argv(source, event, output))
            self.assertEqual((code, stdout), (2, ''))
            self.assertEqual(output.read_bytes(), b'original evidence')
            self.assertIs(json.loads(stderr)['workers_started'], False)

    def test_output_cannot_alias_event_input(self):
        with tempfile.TemporaryDirectory() as directory:
            source, event, output = self.inputs(Path(directory)); original = event.read_bytes()
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                self.cli.main(self.argv(source, event, event))
            self.assertEqual(event.read_bytes(), original)

    def test_bad_owner_event_creates_no_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            source, event, output = self.inputs(Path(directory))
            data = json.loads(event.read_bytes()); data['turn']['id'] = 'wrong-turn'
            event.write_text(json.dumps(data))
            code, stdout, stderr = self.invoke(self.argv(source, event, output))
            self.assertEqual((code, stdout), (2, '')); self.assertFalse(output.exists())

    def test_file_or_directory_sync_failure_preserves_partial_and_refuses_success(self):
        for failure in (1, 2):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                source, event, output = self.inputs(Path(directory))
                calls = 0
                def fail_at(fd):
                    nonlocal calls
                    calls += 1
                    if calls == failure: raise OSError('injected checkpoint sync failure')
                with patch.object(self.cli.os, 'fsync', side_effect=fail_at):
                    code, stdout, stderr = self.invoke(self.argv(source, event, output))
                self.assertEqual((code, stdout), (2, '')); self.assertTrue(output.exists())
                self.assertIn('injected checkpoint sync failure', json.loads(stderr)['error'])
                self.assertEqual(len(json.loads(output.read_bytes())['policy_holds']), 1)

    def test_symlink_observation_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source, event, output = self.inputs(Path(directory)); link = event.with_name('turn-link.json')
            link.symlink_to(event)
            code, stdout, stderr = self.invoke(self.argv(source, link, output))
            self.assertEqual((code, stdout), (2, '')); self.assertFalse(output.exists())

    def test_symlink_output_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source, event, output = self.inputs(root)
            target = root/'real'; target.mkdir(); link = root/'link'; link.symlink_to(target, target_is_directory=True)
            code, stdout, stderr = self.invoke(self.argv(source, event, link/'checkpoint.json'))
            self.assertEqual((code, stdout), (2, '')); self.assertEqual(list(target.iterdir()), [])

    def test_replacement_during_directory_sync_cannot_acknowledge_checkpoint(self):
        import os
        for replace_parent in (False, True):
            with self.subTest(replace_parent=replace_parent), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); parent = root/'output'; parent.mkdir()
                source, event, unused = self.inputs(root); output = parent/'checkpoint.json'
                original_sync = os.fsync; calls = 0
                def replace_at_sync(fd):
                    nonlocal calls
                    calls += 1
                    original_sync(fd)
                    if calls == 2:
                        if replace_parent:
                            parent.rename(root/'retained-output'); parent.mkdir()
                        else:
                            output.rename(parent/'retained-checkpoint.json')
                        output.write_bytes(b'replacement must not be acknowledged')
                with patch.object(self.cli.os, 'fsync', side_effect=replace_at_sync):
                    code, stdout, stderr = self.invoke(self.argv(source, event, output))
                self.assertEqual((code, stdout), (2, ''))
                self.assertIn('changed during directory sync', json.loads(stderr)['error'])
