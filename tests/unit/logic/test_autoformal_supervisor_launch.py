"""Pre-dispatch guards run without opening a queue or calling any provider."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


class NewCaller:
    def compare_and_set_status(self):
        return self._intent.cas_task_status(task_cid="probe", expected_revision=1, new_status="in_progress",
                                            receipt={}, expected_control_receipt=None, evidence_digests=None)


class MatchingRevisionCaller:
    def compare_and_set_status(self):
        return self._intent.cas_task_status(task_cid="probe", expected_revision=1, new_status="in_progress",
                                            receipt={}, evidence_digests=None)


def launcher():
    root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location(
        "autoformal_launch_contract", root / "scripts/ops/legal_ir/run_autoformal_supervisor.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_task_alias_shard_index_matches_daemon_lane_hash():
    module = launcher()
    assert module.task_alias_shard_index("AFTD-" + "ab" * 10, 1) == 0
    first = module.task_alias_shard_index("AFTD-" + "ab" * 10, 4)
    assert module.task_alias_shard_index("AFTD-" + "ab" * 10, 4) == first
    assert 0 <= first < 4
    indexes = {
        module.task_alias_shard_index(f"AFTD-{index:020x}", 3)
        for index in range(30)
    }
    assert indexes == {0, 1, 2}


def test_receipt_argument_mismatch_stops_before_calling_native_transition():
    class Incompatible:
        def cas_task_status(self, *, task_cid, expected_revision, new_status,
                            receipt=None, evidence_digests=None):
            pytest.fail("preflight must not perform a transition")
    with pytest.raises(RuntimeError, match="expected_control_receipt"):
        launcher().require_native_transition_contract(Incompatible, NewCaller)


def test_compatible_signature_checked_without_synthetic_claim():
    class Compatible:
        def cas_task_status(self, *, task_cid, expected_revision, new_status,
                            receipt=None, expected_control_receipt=None,
                            evidence_digests=None):
            pytest.fail("preflight must not perform a transition")
    launcher().require_native_transition_contract(Compatible, NewCaller)


def test_supervise_autoformal_loop_refuses_implement():
    with pytest.raises(ValueError, match="does not claim"):
        launcher().main(
            [
                "--accelerate-root",
                "/tmp/accelerate",
                "--database",
                "/tmp/control.duckdb",
                "--runtime-root",
                "/tmp/runtime",
                "supervise",
                "--once",
                "--implement",
                "--autoformal-loop",
                "--hits",
                "/tmp/hits.json",
            ]
        )


def test_loop_subcommand_is_registered_without_opening_a_queue():
    module = launcher()
    parsed = module.parser().parse_args(
        [
            "--accelerate-root",
            "/tmp/accelerate",
            "--database",
            "/tmp/control.duckdb",
            "--runtime-root",
            "/tmp/runtime",
            "loop",
            "--hits",
            "/tmp/hits.json",
            "--max-rounds",
            "2",
            "--job-template",
            "/tmp/job-v6.json",
            "--model-identity",
            "sha256:loop-census-unbound",
        ]
    )
    assert parsed.command == "loop"
    assert parsed.hits.name == "hits.json"
    assert parsed.recensus is False
    assert parsed.job_template.name == "job-v6.json"
    assert parsed.model_identity == "sha256:loop-census-unbound"


def test_matching_revision_contract_needs_no_keyword_rewriting():
    class Compatible:
        def cas_task_status(self, *, task_cid, expected_revision, new_status, receipt=None, evidence_digests=None):
            pytest.fail("preflight must not perform a transition")
    launcher().require_native_transition_contract(Compatible, MatchingRevisionCaller)


def test_caller_cannot_silently_omit_fencing_fields():
    class UnguardedCaller:
        def compare_and_set_status(self):
            return self._intent.cas_task_status(task_cid="probe", new_status="completed")
    with pytest.raises(RuntimeError, match="omits revision"):
        launcher().require_native_transition_contract(object, UnguardedCaller)


@pytest.mark.parametrize("text,review", [
    ("§§ 1100 to 1100a–3. Omitted", True),
    ("§ 10. Reserved.", True),
    ("§ 10. Repealed", True),
    ("§ 10. Transferred", True),
    ("The officer shall retain omitted records.", False),
])
def test_early_preflight_keeps_native_lifecycle_and_flags_editorial_input(tmp_path, text, review):
    from ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source import DatabaseTaskSource
    from ipfs_datasets_py.logic.autoformal.supervisor_queue import enqueue_repairs, repair_packets, NAMESPACE

    packets = repair_packets({"rows": [{"id": "s1", "text": text, "agrees": False,
                                         "reason": "compiler_abstain:unsupported_norm_type"}]},
                             release_id="release-1", code_identity="compiler-1", model_identity="model-1")
    seen = []

    def probe(repository, commands, *, task_authority):
        assert repository == tmp_path
        assert len(commands) == 1 and "validate_autoformal_repair.py" in commands[0]
        assert task_authority["board_namespace"] == NAMESPACE
        assert task_authority["declared_outputs"][-1].startswith("tests/unit/logic/autoformal_repairs/")
        seen.append(task_authority)
        return {"passed": True, "reason": "test_probe_only"}

    module = launcher()
    with DatabaseTaskSource(tmp_path / "control.duckdb") as source:
        enqueue_repairs(source, packets, packet_directory=tmp_path / "packets")
        before = source.snapshot().to_dict()
        report = module.preflight_next_repair(source, tmp_path, probe=probe)
        assert source.snapshot().to_dict() == before
        assert source.list_tasks().tasks[0].status == "ready"
    assert len(seen) == 1 and not report["tasks_claimed"] and not report["provider_dispatched"]
    assert report["passed"] is not review
    if review:
        with pytest.raises(RuntimeError, match="editorial_heading"):
            module.require_validation_preflight(report)
    else:
        module.require_validation_preflight(report)


def test_native_dependency_rejection_is_not_overridden():
    report = {"eligible": True, "passed": False, "review_flags": [],
              "dependency_preflight": {"passed": False, "reason": "project_dependency_contract_collection_failed",
                  "projects": [{"contract_error_reason": "v2_validation_command_not_declared"}]}}
    with pytest.raises(RuntimeError, match="v2_validation_command_not_declared"):
        launcher().require_validation_preflight(report)


def test_backoff_without_eligible_task_is_not_a_passing_qualification(tmp_path):
    source = SimpleNamespace(snapshot=lambda: SimpleNamespace(revision=82),
                             ready_tasks=lambda **kwargs: SimpleNamespace(tasks=(), revision=82))
    report = launcher().preflight_next_repair(source, tmp_path,
                                            probe=lambda *args, **kwargs: pytest.fail("no eligible task"))
    assert report["passed"] is None and not report["eligible"]


def test_launch_disables_destructive_pool_reuse_before_loading_native_runtime(tmp_path, monkeypatch):
    import os
    module = launcher()
    monkeypatch.setenv("IPFS_ACCELERATE_AGENT_WORKTREE_POOL_ENABLED", "1")
    class ReachedPin(Exception):
        pass
    def pin(_root):
        assert os.environ["IPFS_ACCELERATE_AGENT_WORKTREE_POOL_ENABLED"] == "0"
        raise ReachedPin
    monkeypatch.setattr(module, "pin_accelerate", pin)
    with pytest.raises(ReachedPin):
        module.main(["--accelerate-root", str(tmp_path), "--database", str(tmp_path / "unused.duckdb"),
                     "--runtime-root", str(tmp_path), "status"])


def test_native_dry_run_requires_retention_without_claiming_or_generating_context(tmp_path, capsys):
    import json
    import ipfs_accelerate_py
    from ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source import DatabaseTaskSource
    database = tmp_path / "control.duckdb"
    with DatabaseTaskSource(database) as source:
        before = source.snapshot().to_dict()
    accelerate = Path(ipfs_accelerate_py.__file__).resolve().parent.parent
    result = launcher().main(["--accelerate-root", str(accelerate), "--database", str(database),
                              "--runtime-root", str(tmp_path), "supervise"])
    report = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert result == 0 and report["tasks_claimed"] is False
    assert "--retain-worktree-artifacts" in report["native_arguments"]
    assert "--operator-repair-note" not in report["native_arguments"]
    with DatabaseTaskSource(database, install_schema=False) as source:
        assert source.snapshot().to_dict() == before
    assert not (tmp_path / "repair-context").exists()


def test_live_multi_task_invocation_is_rejected_before_loading_runtime(tmp_path, monkeypatch):
    module = launcher()
    monkeypatch.setattr(module, "pin_accelerate", lambda _: pytest.fail("must reject before dependency loading"))
    with pytest.raises(ValueError, match="live supervise requires --once"):
        module.main(["--accelerate-root", str(tmp_path), "--database", str(tmp_path / "unused.duckdb"),
                     "--runtime-root", str(tmp_path), "supervise", "--implement"])
    assert not (tmp_path / "unused.duckdb").exists()


def test_live_single_task_invocation_can_reach_runtime_loading(tmp_path, monkeypatch):
    module = launcher()
    class ReachedPin(Exception):
        pass
    def pin(_root):
        raise ReachedPin
    monkeypatch.setattr(module, "pin_accelerate", pin)
    with pytest.raises(ReachedPin):
        module.main(["--accelerate-root", str(tmp_path), "--database", str(tmp_path / "unused.duckdb"),
                     "--runtime-root", str(tmp_path), "supervise", "--implement", "--once"])


def selected_queue(tmp_path):
    from ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source import DatabaseTaskSource
    from ipfs_datasets_py.logic.autoformal.supervisor_queue import enqueue_repairs, repair_packets
    packets = repair_packets({"rows": [
        {"id": "first", "text": "The officer shall retain records.", "agrees": False, "reason": "compiler_abstain"},
        {"id": "second", "text": "The clerk shall preserve notices.", "agrees": False, "reason": "compiler_abstain"},
    ]}, release_id="release-1", code_identity="compiler-1", model_identity="model-1")
    with DatabaseTaskSource(tmp_path / "control.duckdb") as source:
        enqueue_repairs(source, packets, packet_directory=tmp_path / "packets")
        tasks = source.ready_tasks(limit=2).tasks
        assert len(tasks) == 2
    return tasks


def test_selected_preflight_uses_native_readiness_without_reordering_queue(tmp_path):
    from ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source import DatabaseTaskSource
    first, target = selected_queue(tmp_path)
    seen = []
    def probe(_repo, _commands, *, task_authority):
        seen.append(task_authority["canonical_task_cid"])
        return {"passed": True}
    module = launcher()
    with DatabaseTaskSource(tmp_path / "control.duckdb", install_schema=False) as source:
        before = source.snapshot().to_dict()
        report = module.preflight_next_repair(source, tmp_path, probe=probe, task_id=target.task_alias)
        assert source.snapshot().to_dict() == before
        assert source.ready_tasks(limit=1).tasks[0].task_cid == first.task_cid
    assert seen == [target.task_cid]
    assert report["requested_task_id"] == target.task_alias
    assert module.native_task_binding(report) == ["--execution-slice-task-cid", target.task_cid]


def test_old_absolute_python_task_fails_before_dependency_probe_or_dispatch(tmp_path):
    from dataclasses import replace
    from ipfs_datasets_py.logic.autoformal.supervisor_queue import RepairQueueError
    _, target = selected_queue(tmp_path)
    command = dict(target.validations[0])
    command["argv"] = ["/usr/bin/python3", *command["argv"][1:]]
    old = replace(target, validations=(command,))
    source = SimpleNamespace(snapshot=lambda: SimpleNamespace(revision=1),
                             ready_tasks=lambda **kwargs: SimpleNamespace(tasks=(old,), revision=1))
    with pytest.raises(RepairQueueError, match="python3 launcher required"):
        launcher().preflight_next_repair(source, tmp_path, task_id=old.task_alias,
            probe=lambda *a, **k: pytest.fail("invalid launcher reached dependency probe"))


def test_task_launcher_is_accepted_by_real_native_runtime_grammar():
    import shlex
    from ipfs_accelerate_py.agent_supervisor.validation.validation_runtime import (
        ValidationRuntimeError, validation_shell_command,
    )
    args = ["scripts/ops/legal_ir/validate_autoformal_repair.py", "--packet", "/tmp/evidence.json", "--sha256", "a" * 64]
    wrapped = validation_shell_command(shlex.join(["python3", *args]))
    assert "_ipfs_accelerate_validation_python" in wrapped[-1]
    with pytest.raises(ValidationRuntimeError, match="sealed python or python3 launcher"):
        validation_shell_command(shlex.join(["/usr/bin/python3", *args]))


def test_status_change_requires_the_stored_control_receipt(tmp_path):
    from ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source import (
        DatabaseTaskSource,
        TaskSourceConflictError,
    )
    task = selected_queue(tmp_path)[0]
    with DatabaseTaskSource(tmp_path / "control.duckdb", install_schema=False) as source:
        source.compare_and_set_status(
            task.task_cid, task.revision, "in_progress", receipt={"operation": "claim"},
        )
        current = source.get(task.task_cid)
        with pytest.raises(TaskSourceConflictError, match="control receipt CAS is stale"):
            source.compare_and_set_status(
                current.task_cid, current.revision, "retrying",
                receipt={"operation": "next"},
                expected_control_receipt={"operation": "other"},
            )
        moved = source.compare_and_set_status(
            current.task_cid, current.revision, "retrying",
            receipt={"operation": "next"},
            expected_control_receipt={"operation": "claim"},
        )
    assert moved.task.status == "retrying"
    with DatabaseTaskSource(tmp_path / "control.duckdb", install_schema=False) as source:
        assert source.get(task.task_cid).status == "retrying"


def test_explicit_in_progress_task_is_preflighted_for_resume(tmp_path):
    from ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source import DatabaseTaskSource
    first, target = selected_queue(tmp_path)
    seen = []

    def probe(_repo, _commands, *, task_authority):
        seen.append(task_authority["canonical_task_cid"])
        return {"passed": True}

    module = launcher()
    with DatabaseTaskSource(tmp_path / "control.duckdb", install_schema=False) as source:
        source.compare_and_set_status(
            target.task_cid, target.revision, "in_progress",
            receipt={"operation": "database_claim"},
        )
        report = module.preflight_next_repair(
            source, tmp_path, probe=probe, task_id=target.task_alias,
        )
        assert source.ready_tasks(limit=1).tasks[0].task_cid == first.task_cid
    assert seen == [target.task_cid]
    assert report["eligible"] is True and report["passed"] is True
    assert report["task_cid"] == target.task_cid
    assert module.native_task_binding(report) == [
        "--execution-slice-task-cid", target.task_cid,
    ]


def test_selected_blocked_task_never_falls_back_to_other_ready_work(tmp_path):
    from ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source import DatabaseTaskSource
    _, target = selected_queue(tmp_path)
    with DatabaseTaskSource(tmp_path / "control.duckdb", install_schema=False) as source:
        source.compare_and_set_status(target.task_cid, target.revision, "blocked",
                                      receipt={"operation": "unit-test-only"})
        before = source.snapshot().to_dict()
        report = launcher().preflight_next_repair(source, tmp_path, task_id=target.task_alias,
                                                  probe=lambda *a, **k: pytest.fail("blocked task probe"))
        assert report["eligible"] is False and report["passed"] is None
        assert source.snapshot().to_dict() == before
        assert source.ready_tasks(limit=1).tasks
    with pytest.raises(ValueError, match="passing eligible"):
        launcher().native_task_binding(report)


def test_missing_selected_task_cannot_probe_or_bind_another_task(tmp_path):
    calls = []
    def ready_tasks(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(tasks=(SimpleNamespace(task_alias="AFTD-" + "a" * 20),), revision=3)
    source = SimpleNamespace(snapshot=lambda: SimpleNamespace(revision=3), ready_tasks=ready_tasks)
    report = launcher().preflight_next_repair(source, tmp_path, task_id="AFTD-" + "b" * 20,
                                             probe=lambda *a, **k: pytest.fail("missing task probe"))
    assert not report["eligible"]
    assert calls == [{"limit": 1000}]  # No assumed completions or blocked-ID overlays.


@pytest.mark.parametrize("task_id", ["", "AFTD-123", "AFTD-" + "A" * 20, "--implement", "AFTD-" + "a" * 20 + ";id"])
def test_task_selection_id_validation(task_id):
    with pytest.raises(ValueError, match="task ID"):
        launcher().validated_task_id(task_id)


@pytest.mark.parametrize("changes", [{"passed": False}, {"eligible": False}, {"task_cid": "--implement"}])
def test_live_native_binding_refuses_unqualified_selection(changes):
    from ipfs_accelerate_py.agent_supervisor.task_sources.control_plane_contracts import content_identity
    report = {"eligible": True, "passed": True, "task_cid": content_identity({"test": "sealed"}), **changes}
    with pytest.raises(ValueError):
        launcher().native_task_binding(report)


def test_selected_dry_run_exposes_slice_without_claiming(tmp_path, capsys):
    import json
    import ipfs_accelerate_py
    from ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source import DatabaseTaskSource
    first, target = selected_queue(tmp_path)
    pin = Path(ipfs_accelerate_py.__file__).resolve().parent.parent
    module = launcher()
    with DatabaseTaskSource(tmp_path / "control.duckdb", install_schema=False) as source:
        before = source.snapshot().to_dict()
    assert module.main(["--accelerate-root", str(pin), "--database", str(tmp_path / "control.duckdb"),
                        "--runtime-root", str(tmp_path), "--task-id", target.task_alias, "supervise"]) == 0
    report = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    argv = report["native_arguments"]
    assert argv[argv.index("--execution-slice-task-id") + 1] == target.task_alias
    assert "--operator-repair-note" not in argv
    with DatabaseTaskSource(tmp_path / "control.duckdb", install_schema=False) as source:
        assert source.snapshot().to_dict() == before
        assert source.ready_tasks(limit=1).tasks[0].task_cid == first.task_cid


def test_claimed_gap_asks_the_router_without_importing_or_finishing(tmp_path):
    import json
    from ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon import parse_args
    from ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon_runner import (
        build_database_implementation_daemon_from_args,
    )
    from ipfs_datasets_py.logic.autoformal.supervisor_queue import NAMESPACE
    from ipfs_datasets_py.logic.autoformal.supervisor_router import provide_claimed_gap, review_holds

    first, target = selected_queue(tmp_path)
    bound = launcher().native_task_binding(
        {"eligible": True, "passed": True, "task_cid": target.task_cid}
    )
    parsed = parse_args([
        "--todo-path", str(tmp_path / "control.duckdb"),
        "--state-dir", str(tmp_path / "state"),
        "--state-prefix", "router-claim",
        "--authority-mode", "embedded",
        "--task-source-kind", "duckdb",
        "--board-namespace", NAMESPACE,
        "--state-store-id", "router-claim",
        "--state-failover-policy", "fail_closed",
        "--max-task-attempts", "3",
        *bound,
    ])
    prompts = []

    def generate(prompt, temperature=0, task_kind="legal"):
        prompts.append((temperature, task_kind, prompt))
        return json.dumps({
            "compiler": "def compile(request):\n    return request\n",
            "parser": "def parse_statute(text):\n    return text\n",
        })

    daemon = build_database_implementation_daemon_from_args(parsed)
    try:
        claim = daemon.claim_next()
        assert claim is not None and claim.task_cid == target.task_cid
        claim = daemon.commit_phase(claim, "context", body={"packet": "sealed"})
        _attempt, result, duplicated = daemon.run_provider(
            claim,
            provider_fn=lambda attempt: provide_claimed_gap(
                attempt, task_source=daemon.task_source, generate=generate,
            ),
        )
        assert duplicated is False
        assert result["router_called"] is True
        assert result["accepted"] is False
        assert result["imported"] is False
        assert result["wrote_compiler"] is False
        assert result["admitted"] is False
        assert result["formalized"] is False
        assert result["proposal_sha256"]
        assert result["proposal_keys"] == ["compiler", "parser"]
        assert prompts and prompts[0][0] == 0 and prompts[0][1] == "legal"
        assert "Do not replace them" in prompts[0][2]
        assert "deontic_parser.py" in prompts[0][2]
        assert "Edit only the existing files" in prompts[0][2]
        assert daemon.task_source.get(first.task_cid).status == "ready"
        assert daemon.task_source.get(target.task_cid).status == "in_progress"
        resumed = daemon.resume_attempt(_attempt.attempt_id)
        assert resumed["resumed"] is False
        assert resumed["reason"] == "router_proposal_not_applied"
        assert resumed["admitted"] is False
        assert resumed["formalized"] is False
        assert resumed["wrote_compiler"] is False
        assert resumed["effect_result"]["status"] == "refused"
        assert resumed["effect_result"]["applied"] is False
        assert resumed["committed_phase"] != "complete"
        assert resumed["requeued"] is True
        assert resumed["task_status"] == "ready"
        ready = daemon.task_source.get(target.task_cid)
        assert ready.status == "ready"
        assert ready.body["completion_receipt"]["operation"] == "router_proposal_not_applied"
        assert ready.body["completion_receipt"]["admitted"] is False
        assert ready.body["completion_receipt"]["formalized"] is False
        assert ready.body["completion_receipt"]["proposal_sha256"] == result["proposal_sha256"]
        again = daemon.claim_next()
        assert again is not None and again.task_cid == target.task_cid
        assert daemon.task_source.get(first.task_cid).status == "ready"
        again = daemon.commit_phase(again, "context", body={"packet": "sealed"})
        _again, repeat, repeat_duplicated = daemon.run_provider(
            again,
            provider_fn=lambda attempt: provide_claimed_gap(
                attempt, task_source=daemon.task_source, generate=generate,
            ),
        )
        assert repeat_duplicated is False
        assert len(prompts) == 1
        assert repeat["router_called"] is False
        assert repeat["reason"] == "proposal_already_recorded"
        assert repeat["proposal_sha256"] == result["proposal_sha256"]
        assert repeat["accepted"] is False
        assert repeat["imported"] is False
        assert repeat["wrote_compiler"] is False
        assert repeat["admitted"] is False
        assert repeat["formalized"] is False
        parked = daemon.resume_attempt(_again.attempt_id)
        assert len(prompts) == 1
        assert parked["resumed"] is False
        assert parked["requeued"] is False
        assert parked["task_status"] == "blocked"
        assert parked["admitted"] is False
        assert parked["formalized"] is False
        assert parked["wrote_compiler"] is False
        held = daemon.task_source.get(target.task_cid)
        assert held.status == "blocked"
        assert held.body["completion_receipt"]["operation"] == "router_proposal_review"
        assert held.body["completion_receipt"]["admitted"] is False
        assert held.body["router_proposal"]["proposal_sha256"] == result["proposal_sha256"]
        assert daemon.claim_next() is None
        assert daemon.task_source.get(first.task_cid).status == "ready"
        holds = review_holds(daemon.task_source)
        assert holds["router_called"] is False
        assert holds["admitted"] is False
        assert holds["formalized"] is False
        assert holds["wrote_compiler"] is False
        assert [item["task_cid"] for item in holds["holds"]] == [target.task_cid]
        assert holds["holds"][0]["proposal_sha256"] == result["proposal_sha256"]
        assert holds["holds"][0]["proposal_keys"] == ["compiler", "parser"]
        assert holds["review_hold_keys"] == {"compiler": 1, "decompiler": 0, "parser": 1}
        assert holds["holds"][0]["applied"] is False
        assert holds["holds"][0]["imported"] is False
        assert not list(tmp_path.rglob("proposed_compiler.py"))
    finally:
        daemon.close()


def test_status_lists_a_parked_router_review_without_reopening_it(tmp_path, capsys):
    import json
    import ipfs_accelerate_py
    from ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source import DatabaseTaskSource

    queued = selected_queue(tmp_path)
    task, other = queued[0], queued[1]
    claim = {
        "operation": "database_claim",
        "claim_id": "claim-status",
        "attempt_id": "attempt-status",
        "lease_id": "lease-status",
        "attempt_number": 1,
        "owner_session_id": "status-test",
        "fencing_token": 1,
        "fence_epoch": 1,
    }
    with DatabaseTaskSource(tmp_path / "control.duckdb", install_schema=False) as source:
        source.compare_and_set_status(task.task_cid, task.revision, "in_progress", claim)
        current = source.get(task.task_cid)
        source.compare_and_set_status(
            current.task_cid, current.revision, "ready",
            {
                "operation": "router_proposal_not_applied",
                "attempt_id": "attempt-status",
                "proposal_keys": ["parser"],
                "proposal_sha256": "abc123",
                "applied": False,
                "wrote_compiler": False,
                "imported": False,
                "admitted": False,
                "formalized": False,
            },
            expected_control_receipt=claim,
        )
        current = source.get(task.task_cid)
        before = source.snapshot().to_dict()
        source.compare_and_set_status(
            current.task_cid, current.revision, "blocked",
            {
                "operation": "router_proposal_review",
                "attempt_id": "attempt-status-2",
                "proposal_sha256": "abc123",
                "applied": False,
                "wrote_compiler": False,
                "imported": False,
                "admitted": False,
                "formalized": False,
            },
            expected_control_receipt=current.body["completion_receipt"],
        )
    accelerate = Path(ipfs_accelerate_py.__file__).resolve().parent.parent
    result = launcher().main([
        "--accelerate-root", str(accelerate),
        "--database", str(tmp_path / "control.duckdb"),
        "--runtime-root", str(tmp_path),
        "status",
    ])
    report = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert result == 0
    assert report["admitted"] is False
    assert report["formalized"] is False
    assert report["router_called"] is False
    assert report["wrote_compiler"] is False
    assert report["review_hold_count"] == 1
    assert report["review_holds"][0]["task_cid"] == task.task_cid
    assert report["review_holds"][0]["proposal_sha256"] == "abc123"
    assert report["review_holds"][0]["proposal_keys"] == ["parser"]
    assert report["review_hold_keys"] == {"compiler": 0, "decompiler": 0, "parser": 1}
    assert report["verified_complete_count"] == 0
    assert report["inconclusive_goal_count"] == 0
    assert report["inconclusive_goals"] == []
    assert report["claim_blocked_reason"] == ""
    assert report["claim_blocked_task_cids"] == []
    assert report["claimable_ready_task_cids"] == [other.task_cid]
    assert report["open_goal_count"] == len(report["open_goals"])
    assert all(item["status"] == "open" and item["admitted"] is False for item in report["open_goals"])
    assert all(task.task_cid not in item["ready_task_cids"] for item in report["open_goals"])
    assert all(item["goal_cid"] for item in report["open_goals"])
    assert report["formalized"] is False
    assert report["review_holds"][0]["applied"] is False
    assert report["review_holds"][0]["source_readable"] is True
    assert report["review_holds"][0]["source_span_id"] in {"first", "second"}
    assert "shall" in report["review_holds"][0]["source_text"]
    assert report["review_holds"][0]["failure_reason"] == "compiler_abstain"
    assert any("deontic_parser.py" in path for path in report["review_holds"][0]["allowed_edit_paths"])
    assert report["review_holds"][0]["replace"]
    assert report["counts"]["blocked"] == 1
    assert report["counts"]["ready"] == 1
    with DatabaseTaskSource(tmp_path / "control.duckdb", install_schema=False) as source:
        assert source.get(task.task_cid).status == "blocked"
        assert source.snapshot().revision >= before["revision"]


def test_native_builder_claims_only_the_preflighted_cid(tmp_path):
    from ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon import parse_args
    from ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon_runner import (
        build_database_implementation_daemon_from_args,
    )
    from ipfs_datasets_py.logic.autoformal.supervisor_queue import NAMESPACE
    first, target = selected_queue(tmp_path)
    bound = launcher().native_task_binding({"eligible": True, "passed": True, "task_cid": target.task_cid})
    parsed = parse_args(["--todo-path", str(tmp_path / "control.duckdb"), "--state-dir", str(tmp_path / "state"),
                         "--state-prefix", "slice-test", "--authority-mode", "embedded",
                         "--task-source-kind", "duckdb", "--board-namespace", NAMESPACE,
                         "--state-store-id", "slice-test", "--state-failover-policy", "fail_closed",
                         "--max-task-attempts", "3", "--implement", *bound])
    def forbidden(*args, **kwargs):
        pytest.fail("claim test cannot dispatch provider/effect/validation")
    daemon = build_database_implementation_daemon_from_args(parsed, provider_fn=forbidden,
                                                           effect_fn=forbidden, validation_fn=forbidden)
    try:
        claim = daemon.claim_next()
        assert claim is not None and claim.task_cid == target.task_cid
        assert daemon.task_source.get(first.task_cid).status == "ready"
        recorded = daemon._require_connection().execute(
            "SELECT COUNT(*) FROM provider_invocations WHERE attempt_id = ?",
            [str(claim.attempt_id)],
        ).fetchone()
        assert int(recorded[0]) == 0
    finally:
        daemon.close()
