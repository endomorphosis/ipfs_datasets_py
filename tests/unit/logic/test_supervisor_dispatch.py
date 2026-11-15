"""Loop todos declare train and compiler/decompiler edit work without admitting."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.autoformal.supervisor_dispatch import (
    TRAINING_ENTRYPOINT,
    TRAINING_JOB_SCHEMA,
    TRAINING_NAMESPACE,
    WORK_KIND_EDIT,
    WORK_KIND_REVIEW,
    WORK_KIND_TRAIN,
    attach_dispatch,
    classify_work,
    dispatch_counts,
)
from ipfs_datasets_py.logic.autoformal.supervisor_loop import run_supervisor_loop, spawn_goal_tree, supervisor_population
from ipfs_datasets_py.logic.autoformal.supervisor_queue import EDIT_SCOPES, NAMESPACE as REPAIR_NAMESPACE
from ipfs_datasets_py.logic.autoformal.supervisor_todo import discrepancy_tasks, render_supervisor_board, validate_supervisor_board


def _row(span_id: str, *, reason: str, text: str = "Each agency shall make records available.", legal_id: str = "usc:us:5:552") -> dict:
    return {
        "agrees": False,
        "id": span_id,
        "legal_id": legal_id,
        "reason": reason,
        "skipped": False,
        "source_span_id": span_id,
        "text": text,
    }


def _v6_template(path: Path) -> Path:
    path.write_text(json.dumps({"schema_version": TRAINING_JOB_SCHEMA}), encoding="utf-8")
    return path


def test_classify_work_maps_failure_modes_to_train_and_edit() -> None:
    assert classify_work("no_parser_elements") == (WORK_KIND_EDIT,)
    assert classify_work("compiler_abstain:recipient") == (WORK_KIND_EDIT,)
    assert classify_work("CanonicalErrorCode.UNSUPPORTED_SEMANTICS") == (WORK_KIND_EDIT,)
    assert classify_work("strict_roundtrip_failed") == (WORK_KIND_EDIT,)
    assert classify_work("inference_still_failing") == (WORK_KIND_TRAIN,)
    assert classify_work("capture_not_in_decompilation") == (WORK_KIND_EDIT, WORK_KIND_TRAIN)
    assert classify_work("loop_error") == ()


def test_parser_gap_declares_edit_scope_without_training() -> None:
    tasks = discrepancy_tasks({"rows": [_row("s1", reason="no_parser_elements"), _row("s2", reason="no_parser_elements")]})
    tree = spawn_goal_tree(tasks)
    assert {task["work_kind"] for task in tree["tasks"]} == {WORK_KIND_EDIT}
    for task in tree["tasks"]:
        assert task["allowed_edit_paths"] == list(EDIT_SCOPES["no_parser_elements"])
        assert task["predicted_files"] == task["allowed_edit_paths"]
        assert task["conflict_policy"] == "serialize overlapping compiler/decompiler edits"
        assert task.get("training_job") in (None, {}, []) or "training_job" not in task
        assert task["admitted"] is False
        assert task["formalized"] is False
        assert task["wrote_compiler"] is False
        assert task["dispatch_status"] == "awaiting_sealed_packet"
        assert task["review_only"] is True
    markdown = render_supervisor_board(tree["tasks"], goals=tree["goals"])
    validate_supervisor_board(markdown)
    assert "- Work kind: compiler_decompiler_edit" in markdown


def test_inference_failure_declares_training_without_compiler_paths() -> None:
    tasks = discrepancy_tasks({"rows": [_row("inf", reason="inference_still_failing", text="")]})
    tree = spawn_goal_tree(tasks)
    assert len(tree["tasks"]) == 1
    task = tree["tasks"][0]
    assert task["work_kind"] == WORK_KIND_TRAIN
    assert task["allowed_edit_paths"] == []
    assert task["board_namespace"] == TRAINING_NAMESPACE
    assert task["training_job"]["entrypoint"] == TRAINING_ENTRYPOINT
    assert task["training_job"]["bound"] is False
    assert task["review_only"] is True
    assert task["conflict_policy"] == "do not write compiler or decompiler patches from this task"
    assert task["admitted"] is False
    assert task["formalized"] is False


def test_capture_gap_spawns_edit_and_train_under_one_subgoal() -> None:
    tasks = discrepancy_tasks(
        {
            "rows": [
                _row("cap-1", reason="capture_not_in_decompilation"),
                _row("cap-2", reason="capture_not_in_decompilation"),
            ]
        }
    )
    tree = spawn_goal_tree(tasks)
    kinds = [task["work_kind"] for task in tree["tasks"]]
    assert kinds.count(WORK_KIND_EDIT) == 2
    assert kinds.count(WORK_KIND_TRAIN) == 2
    by_span: dict[str, set[str]] = {}
    for task in tree["tasks"]:
        by_span.setdefault(str(task["source_span_id"]), set()).add(str(task["goal_cid"]))
        by_span[str(task["source_span_id"])].add(str(task["work_kind"]))
    assert all(WORK_KIND_EDIT in kinds and WORK_KIND_TRAIN in kinds for kinds in by_span.values())
    for span, values in by_span.items():
        goal_cids = [item for item in values if item.startswith("goal:")]
        assert len(goal_cids) == 1
    counts = dispatch_counts(tree["tasks"])
    assert counts["edit"] == 2
    assert counts["train"] == 2
    assert counts["sealed_packets"] == 0


def test_sealed_edit_packet_matches_repair_namespace(tmp_path: Path) -> None:
    agreement = {"rows": [_row("art-1", reason="compiler_abstain:recipient")]}
    tasks = discrepancy_tasks(agreement, release_id="rel-1")
    tree = spawn_goal_tree(
        tasks,
        release_id="rel-1",
        dispatch={
            "agreement": agreement,
            "packet_directory": tmp_path / "packets",
            "code_identity": "compiler-tree-1",
            "model_identity": "checkpoint-1",
        },
    )
    assert len(tree["tasks"]) == 1
    task = tree["tasks"][0]
    assert task["work_kind"] == WORK_KIND_EDIT
    assert task["board_namespace"] == REPAIR_NAMESPACE
    assert task["dispatch_status"] == "sealed_edit"
    assert task["review_only"] is False
    assert Path(task["packet_path"]).is_file()
    assert len(task["packet_sha256"]) == 64
    argv = task["validation_commands"][0]["argv"]
    assert argv[0] == "python3"
    assert argv[1] == "scripts/ops/legal_ir/validate_autoformal_repair.py"
    assert "--packet" in argv
    assert task["packet_sha256"] in argv
    assert task["allowed_edit_paths"] == list(EDIT_SCOPES["compiler_abstain"])
    assert task["admitted"] is False
    assert task["wrote_compiler"] is False


def test_bound_training_job_uses_frozen_v6_cycle(tmp_path: Path) -> None:
    template = _v6_template(tmp_path / "job.json")
    tasks = discrepancy_tasks({"rows": [_row("inf", reason="inference_still_failing", text="")]})
    tree = spawn_goal_tree(
        tasks,
        dispatch={
            "job_template": template,
            "accelerate_root": tmp_path / "accelerate",
            "database": tmp_path / "control.duckdb",
            "runtime_root": tmp_path / "runtime",
        },
    )
    task = tree["tasks"][0]
    assert task["work_kind"] == WORK_KIND_TRAIN
    assert task["review_only"] is False
    assert task["training_job"]["bound"] is True
    assert task["training_job"]["job_schema"] == TRAINING_JOB_SCHEMA
    argv = task["validation_commands"][0]["argv"]
    assert argv[:2] == ["python3", TRAINING_ENTRYPOINT]
    assert "--job-template" in argv
    assert str(template.resolve()) in argv
    assert task["production_promotion"] is False
    assert task["admitted"] is False
    assert task["formalized"] is False


def test_invalid_job_template_is_refused(tmp_path: Path) -> None:
    bad = tmp_path / "job.json"
    bad.write_text(json.dumps({"schema_version": "autoencoder-training-job-v5"}), encoding="utf-8")
    tasks = discrepancy_tasks({"rows": [_row("inf", reason="inference_still_failing", text="")]})
    with pytest.raises(Exception, match="autoencoder-training-job-v6"):
        spawn_goal_tree(tasks, dispatch={"job_template": bad})


def test_loop_population_carries_dispatch_into_duckdb(tmp_path: Path) -> None:
    from ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source import DatabaseTaskSource
    from ipfs_datasets_py.logic.autoformal.supervisor_loop import ingest_population
    import duckdb
    from ipfs_accelerate_py.agent_supervisor.task_sources.control_plane_schema import (
        DATASETS_AUTHORITATIVE_OPERATIONAL_PROFILE_ID,
        install_datasets_authoritative_operational_schema,
        verify_datasets_authoritative_operational_schema,
    )

    # Small persisted fixture: choose file blocks before the original owner
    # installs its schema; its connection policy and all assertions stay intact.
    database = tmp_path / "control.duckdb"
    assert not database.exists()
    with duckdb.connect(str(database), config={"default_block_size": "16384", "threads": "1"}) as seed:
        seed.execute("CHECKPOINT")
        size = seed.execute("PRAGMA database_size")
        sizes = dict(zip((column[0] for column in size.description), size.fetchone(), strict=True))
        assert sizes["block_size"] == 16384

    # Dispatch persistence uses the existing datasets-authoritative operational
    # schema; semantic/AST/proof truth stays in the datasets owner.
    install_datasets_authoritative_operational_schema(database)
    profile = verify_datasets_authoritative_operational_schema(database)
    assert profile["valid"] is True
    assert profile["profile_id"] == DATASETS_AUTHORITATIVE_OPERATIONAL_PROFILE_ID
    assert profile["forbidden_relations"] == []
    assert profile["forbidden_contracts"] == []

    agreement = {
        "rows": [
            _row("s1", reason="no_parser_elements"),
            _row("s2", reason="inference_still_failing", text=""),
        ]
    }
    template = _v6_template(tmp_path / "job.json")
    tasks = discrepancy_tasks(agreement, release_id="rel-1")
    tree = spawn_goal_tree(
        tasks,
        release_id="rel-1",
        dispatch={
            "agreement": agreement,
            "packet_directory": tmp_path / "packets",
            "code_identity": "compiler-tree-1",
            "model_identity": "checkpoint-1",
            "job_template": template,
            "accelerate_root": tmp_path / "accelerate",
            "database": tmp_path / "control.duckdb",
            "runtime_root": tmp_path / "runtime",
        },
    )
    kinds = {task["work_kind"] for task in tree["tasks"]}
    assert kinds == {WORK_KIND_EDIT, WORK_KIND_TRAIN}
    with DatabaseTaskSource(tmp_path / "control.duckdb") as source:
        receipt = ingest_population(source, supervisor_population(tree))
        assert receipt["jsonl_written"] is False
        assert receipt["wrote_compiler"] is False
        assert receipt["admitted"] is False
        records = source.list_tasks(limit=10).tasks
        bodies = [record.body for record in records]
        assert any(body.get("work_kind") == WORK_KIND_EDIT and body.get("packet_sha256") for body in bodies)
        assert any(body.get("work_kind") == WORK_KIND_TRAIN and (body.get("training_job") or {}).get("bound") for body in bodies)
        assert all(body.get("admitted") is False for body in bodies)
        assert all(body.get("formalized") is False for body in bodies)
        assert all(body.get("wrote_compiler") is False for body in bodies)

    assert database.is_file()
    with DatabaseTaskSource(database, install_schema=False) as reopened:
        persisted = reopened.list_tasks(limit=10).tasks
        assert [(record.task_cid, dict(record.body)) for record in persisted] == [
            (record.task_cid, dict(record.body)) for record in records]



def test_supervisor_loop_stamps_train_and_edit_on_population(tmp_path: Path) -> None:
    template = _v6_template(tmp_path / "job.json")

    def autoformal():
        return {
            "rows": [
                _row("s1", reason="no_parser_elements"),
                _row("inf", reason="inference_still_failing", text=""),
            ]
        }

    receipt = run_supervisor_loop(
        autoformal,
        ingest=lambda *a, **k: {"task_count": 2},
        max_rounds=1,
        dispatch={
            "packet_directory": tmp_path / "packets",
            "code_identity": "compiler-tree-1",
            "model_identity": "checkpoint-1",
            "job_template": template,
            "accelerate_root": tmp_path / "accelerate",
            "database": tmp_path / "control.duckdb",
            "runtime_root": tmp_path / "runtime",
        },
    )
    tasks = receipt["population"]["tasks"]
    kinds = {task["work_kind"] for task in tasks}
    assert kinds == {WORK_KIND_EDIT, WORK_KIND_TRAIN}
    edit = next(task for task in tasks if task["work_kind"] == WORK_KIND_EDIT)
    train = next(task for task in tasks if task["work_kind"] == WORK_KIND_TRAIN)
    assert edit["dispatch_status"] == "sealed_edit"
    assert edit["packet_sha256"]
    assert train["training_job"]["bound"] is True
    assert receipt["admitted"] is False
    assert receipt["wrote_compiler"] is False
    assert receipt["jsonl_written"] is False


def test_review_todos_stay_off_the_compiler() -> None:
    tasks = discrepancy_tasks({"rows": [_row("loop", reason="loop_error", text="census exploded")]})
    tree = spawn_goal_tree(tasks)
    task = tree["tasks"][0]
    assert task["work_kind"] == WORK_KIND_REVIEW
    assert task["review_only"] is True
    assert "compiler/decompiler" in task["conflict_policy"] or "do not write compiler" in task["conflict_policy"]
    assert not task.get("packet_sha256")
    assert not task.get("training_job")


def _reviewed_dispatch_metadata_case(tmp_path, monkeypatch):
    """Isolated DATA-binding fixture; no model or native owner is exercised."""
    from copy import deepcopy
    from ipfs_datasets_py.logic.autoformal import supervisor_dispatch as dispatch
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_inference as inference
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
    reference = worker.CheckpointArtifact(str(tmp_path / "reviewed-request.json"), "1" * 64, 2)
    offered = {"path": reference.path, "sha256": reference.sha256, "bytes": reference.bytes}
    task = {"task_id": "LIR-existing-review", "task_cid": "fixture:original-task-cid", "revision": 19,
        "spec_cid": "fixture:original-spec", "goal_cid": "fixture:original-goal", "status": "blocked",
        "claims": [], "attempt": 2, "max_attempts": 2, "depends_on": ["fixture:original-dependency"],
        "work_kind": dispatch.WORK_KIND_REVIEWED_EVALUATION, "operator_hold": True,
        "historical_provider_outcome": "UNKNOWN", "admitted": False, "formalized": False}
    request = {"schema": "reviewed-source-evaluation-request/v1", "request_id": task["task_id"],
               "operation": "heldout_evaluation"}
    observed = []
    def read_request(value):
        observed.append(deepcopy(value))
        assert value == offered
        return reference, b"{}", deepcopy(request)
    monkeypatch.setattr(inference, "_read_reviewed_evaluation_request", read_request)
    return dispatch, inference, worker, task, request, reference, offered, observed


def test_reviewed_evaluation_dispatch_unconfigured_runtime_refuses_before_packet_or_effects(monkeypatch):
    from ipfs_datasets_py.logic.autoformal import supervisor_dispatch as dispatch
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_inference as inference
    def forbidden(*args, **kwargs):
        pytest.fail("unconfigured reviewed dispatch accessed packet or effect owner")
    monkeypatch.setattr(inference, "_read_reviewed_evaluation_request", forbidden)
    with pytest.raises(dispatch.SupervisorDispatchError, match="runtime"):
        dispatch.execute_reviewed_evaluation_task({"task_id": "existing", "reviewed_evaluation": {}},
                                                 reviewed_parent_runtime=None)


def test_reviewed_evaluation_binding_preserves_existing_native_identity_history_and_hold(tmp_path, monkeypatch):
    from copy import deepcopy
    dispatch, _, _, task, _, _, offered, observed = _reviewed_dispatch_metadata_case(tmp_path, monkeypatch)
    before = deepcopy(task)
    bound = dispatch.bind_reviewed_evaluation_task(task, offered)
    assert task == before and bound is not task
    assert set(bound) == set(before) | {"reviewed_evaluation"}
    assert {key: bound[key] for key in before} == before
    binding = bound["reviewed_evaluation"]
    assert binding["schema"] == dispatch.REVIEWED_EVALUATION_BINDING_SCHEMA
    assert binding["entrypoint"] == "scripts/ops/legal_ir/run_incremental_autoencoders.py"
    assert binding["request_artifact"] == offered and binding["requires_live_parent_runtime"] is True
    assert binding["operation"] == "heldout_evaluation"
    assert observed == [offered]
    # Binding the same bytes is idempotent metadata, never another attempt.
    assert dispatch.bind_reviewed_evaluation_task(bound, offered) == bound
    assert bound["attempt"] == 2 and bound["max_attempts"] == 2 and bound["operator_hold"] is True
    assert bound["status"] == "blocked" and bound["historical_provider_outcome"] == "UNKNOWN"


@pytest.mark.parametrize("damage", ["missing_work_kind", "training_work_kind", "missing_id", "blank_id"])
def test_reviewed_evaluation_binding_requires_explicit_existing_work_kind_before_packet(tmp_path, monkeypatch, damage):
    dispatch, inference, _, task, _, _, offered, _ = _reviewed_dispatch_metadata_case(tmp_path, monkeypatch)
    if damage == "missing_work_kind":
        del task["work_kind"]
    elif damage == "training_work_kind":
        task["work_kind"] = dispatch.WORK_KIND_TRAIN
    elif damage == "missing_id":
        del task["task_id"]
    else:
        task["task_id"] = " "
    def forbidden(*args, **kwargs):
        pytest.fail("invalid task metadata reached request reader")
    monkeypatch.setattr(inference, "_read_reviewed_evaluation_request", forbidden)
    with pytest.raises(dispatch.SupervisorDispatchError, match="existing task ID"):
        dispatch.bind_reviewed_evaluation_task(task, offered)


def test_reviewed_evaluation_binding_refuses_request_for_another_native_task(tmp_path, monkeypatch):
    from copy import deepcopy
    dispatch, _, _, task, request, _, offered, _ = _reviewed_dispatch_metadata_case(tmp_path, monkeypatch)
    before = deepcopy(task)
    request["request_id"] = "different-existing-task"
    with pytest.raises(dispatch.SupervisorDispatchError, match="existing native task ID"):
        dispatch.bind_reviewed_evaluation_task(task, offered)
    assert task == before


def test_reviewed_evaluation_binding_never_implicitly_rebinds_or_rearms(tmp_path, monkeypatch):
    from copy import deepcopy
    dispatch, inference, worker, task, request, _, offered, _ = _reviewed_dispatch_metadata_case(tmp_path, monkeypatch)
    bound = dispatch.bind_reviewed_evaluation_task(task, offered)
    before = deepcopy(bound)
    replacement = worker.CheckpointArtifact(str(tmp_path / "new-review.json"), "2" * 64, 2)
    new_descriptor = {"path": replacement.path, "sha256": replacement.sha256, "bytes": replacement.bytes}
    monkeypatch.setattr(inference, "_read_reviewed_evaluation_request",
                        lambda value: (replacement, b"{}", deepcopy(request)))
    with pytest.raises(dispatch.SupervisorDispatchError, match="no implicit rebind or retry"):
        dispatch.bind_reviewed_evaluation_task(bound, new_descriptor)
    assert bound == before and bound["status"] == "blocked" and bound["attempt"] == 2


@pytest.mark.parametrize("field,value", [
    ("entrypoint", "untrusted/alternate-evaluator.py"),
    ("request_schema", "untrusted-schema/v1"),
    ("operation", "training"),
    ("requires_live_parent_runtime", False),
])
def test_reviewed_evaluation_execute_refuses_corrupt_binding_before_fixed_import(tmp_path, monkeypatch, field, value):
    import time
    from copy import deepcopy
    dispatch, inference, _, task, _, _, offered, _ = _reviewed_dispatch_metadata_case(tmp_path, monkeypatch)
    bound = dispatch.bind_reviewed_evaluation_task(task, offered)
    bound["reviewed_evaluation"][field] = value
    before = deepcopy(bound)
    guarded = []
    # The negative metadata boundary must refuse before consulting this unused
    # object as an owner. It supplies no fake execution or native qualification.
    runtime = inference.ReviewedInferenceParentRuntime(object(), lambda: guarded.append(True),
        lambda policy: pytest.fail("binding refusal reached asset policy"),
        lambda: pytest.fail("binding refusal reached admission provider"), time.monotonic() + 60)
    with pytest.raises(dispatch.SupervisorDispatchError, match="no implicit rebind or retry|binding changed"):
        dispatch.execute_reviewed_evaluation_task(bound, reviewed_parent_runtime=runtime)
    assert guarded and bound == before
    assert not (tmp_path / "outputs").exists()


def test_reviewed_evaluation_optin_preserves_strict_frozen_v6_training_default(tmp_path):
    from ipfs_datasets_py.logic.autoformal import supervisor_dispatch as dispatch
    assert dispatch.TRAINING_JOB_SCHEMA == "autoencoder-training-job-v6"
    assert dispatch.classify_work("inference_still_failing") == (dispatch.WORK_KIND_TRAIN,)
    legacy = _v6_template(tmp_path / "legacy-v6.json")
    assert dispatch.bind_job_template(legacy)["schema_version"] == dispatch.TRAINING_JOB_SCHEMA
    unsupported = tmp_path / "reviewed-training-v9.json"
    unsupported.write_text(json.dumps({"schema_version": "autoencoder-training-job-v9-reviewed-legal-ir"}))
    with pytest.raises(dispatch.SupervisorDispatchError, match="autoencoder-training-job-v6"):
        dispatch.bind_job_template(unsupported)


@pytest.fixture(scope='module')
def reviewed_supervisor_audit_seed():
    from tests.unit.optimizers.logic_theorem_optimizer import test_autoencoder_inference as helper
    return helper.parent_candidate_audit_seed.__wrapped__()


def _supervisor_audit_metadata(tmp_path, seed, *, typed=False, candidate=None):
    from copy import deepcopy
    from types import SimpleNamespace
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_inference as inference
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
    rows, evaluation, contexts = deepcopy(seed)
    def save(name, value):
        path = tmp_path / (name + '.json');raw=worker._json_bytes(value);path.write_bytes(raw)
        return dict(path=str(path), bytes=len(raw), sha256=worker._digest(raw))
    payload = evaluation['compiler_artifact']['reviewed_source_span_producer_evaluation']
    generation = dict(last_call=dict(completed=True, raw_generation_outputs=deepcopy(payload['producer_outputs'])))
    child = dict(output_artifacts={name:save(name,value) for name,value in [('evaluation',evaluation),('generation',generation),('loader',{})]})
    child_ref=worker.CheckpointArtifact.from_dict(save('cycle',child))
    request=dict(output_directory=str(tmp_path),rows_artifact=save('rows',rows),source_contexts_artifact=save('contexts',contexts),
        checkpoint_declarations=deepcopy(payload['configuration']['checkpoint_declarations']))
    request_ref=worker.CheckpointArtifact.from_dict(save('request',request))
    runtime=inference.ReviewedInferenceParentRuntime(SimpleNamespace(reservation_id='fictional:unused'),lambda:None,lambda _:None,lambda:{},1.0,
        typed_structure_profile='canonical-typed-expression-wire/v1' if typed else None,candidate_syntax_profile=candidate)
    parent=dict(schema=('reviewed-source-evaluation-parent/v3' if candidate else 'reviewed-source-evaluation-parent/v2' if typed else 'reviewed-source-evaluation-parent/v1'))
    if typed:
        pins=inference._parent_typed_structure_source_pins()
        audit=inference._build_parent_typed_structure_audit(child,request,child_ref,request_ref.sha256,pins)
        parent.update(typed_structure_profile=runtime.typed_structure_profile,typed_structure_audit_artifact=save('typed-structure-audit',audit),
            parent_typed_structure_audit_after_wait=True,parent_current_admission_rechecked_after_audit=True)
    if candidate:
        pins=inference._parent_candidate_syntax_source_pins()
        audit=inference._build_parent_candidate_syntax_audit(child,request,child_ref,request_ref.sha256,pins,candidate)
        parent.update(candidate_syntax_profile=candidate,candidate_syntax_audit_artifact=save('candidate-syntax-audit',audit),
            parent_candidate_syntax_audit_after_wait=True,parent_current_admission_rechecked_after_candidate_audit=True)
    # This fixture describes DATA only. It neither claims nor exercises an
    # original execution, resource grant, actual child wait or task transition.
    return inference,worker,parent,child,request,request_ref,child_ref,runtime,save


@pytest.mark.parametrize('typed,candidate', [(False,None),(True,None),
    (False,'unreviewed-complete-norm-candidate-syntax/v2'),(False,'unreviewed-complete-norm-candidate-syntax/v3'),
    (True,'unreviewed-complete-norm-candidate-syntax/v3')])
def test_reviewed_supervisor_audit_metadata_matches_trusted_opt_ins(tmp_path,reviewed_supervisor_audit_seed,typed,candidate):
    from ipfs_datasets_py.logic.autoformal import supervisor_dispatch as dispatch
    _,_,parent,child,request,reference,child_ref,runtime,_=_supervisor_audit_metadata(tmp_path,reviewed_supervisor_audit_seed,typed=typed,candidate=candidate)
    state=dispatch._validate_reviewed_parent_audits(parent,child,request,reference.sha256,child_ref,runtime)
    assert set(state['artifacts'])==({'typed_structure'} if typed else set())|({'candidate_syntax'} if candidate else set())
    assert set(state['source_pins'])==set(state['artifacts'])
    dispatch._reauthenticate_reviewed_parent_audits(state,request,reference,runtime)


@pytest.mark.parametrize('damage',['schema','profile','flag','path','report','request','implementation','extra'])
def test_reviewed_supervisor_audit_rejects_resealed_or_unrequested_sidecars(tmp_path,reviewed_supervisor_audit_seed,damage):
    from pathlib import Path
    from ipfs_datasets_py.logic.autoformal import supervisor_dispatch as dispatch
    inf,worker,parent,child,request,reference,child_ref,runtime,save=_supervisor_audit_metadata(tmp_path,reviewed_supervisor_audit_seed,candidate='unreviewed-complete-norm-candidate-syntax/v3')
    if damage=='schema':parent['schema']='reviewed-source-evaluation-parent/v1'
    elif damage=='profile':parent['candidate_syntax_profile']='unreviewed-complete-norm-candidate-syntax/v2'
    elif damage=='flag':parent['parent_candidate_syntax_audit_after_wait']=False
    elif damage=='extra':parent['typed_structure_profile']='canonical-typed-expression-wire/v1'
    else:
        d=parent['candidate_syntax_audit_artifact'];audit=json.loads(Path(d['path']).read_bytes())
        if damage=='path':parent['candidate_syntax_audit_artifact']=save('unexpected-audit',audit)
        else:
            if damage=='report':audit['report']['counts']['syntax_validated_unreviewed']=999
            elif damage=='request':audit['request_sha256']='0'*64
            else:audit['implementation_sha256']={}
            parent['candidate_syntax_audit_artifact']=save('candidate-syntax-audit',audit)
    with pytest.raises(ValueError):dispatch._validate_reviewed_parent_audits(parent,child,request,reference.sha256,child_ref,runtime)


@pytest.mark.parametrize('damage',['sidecar','context','source'])
def test_reviewed_supervisor_audit_reauth_after_last_caller_callback(tmp_path,reviewed_supervisor_audit_seed,monkeypatch,damage):
    from ipfs_datasets_py.logic.autoformal import supervisor_dispatch as dispatch
    inf,worker,parent,child,request,reference,child_ref,runtime,_=_supervisor_audit_metadata(tmp_path,reviewed_supervisor_audit_seed,candidate='unreviewed-complete-norm-candidate-syntax/v3')
    state=dispatch._validate_reviewed_parent_audits(parent,child,request,reference.sha256,child_ref,runtime)
    if damage=='sidecar':Path(parent['candidate_syntax_audit_artifact']['path']).write_text('{}\n')
    elif damage=='context':Path(request['source_contexts_artifact']['path']).write_text('{}\n')
    else:monkeypatch.setattr(inf,'_parent_candidate_syntax_source_pins',lambda:{})
    with pytest.raises(ValueError):dispatch._reauthenticate_reviewed_parent_audits(state,request,reference,runtime)


def _simulated_reviewed_dispatch(tmp_path, seed, monkeypatch, *, typed=False, candidate=None):
    """Exercise adapter control flow using simulated receipts, never Native."""
    from copy import deepcopy
    import hashlib
    import builtins
    from ipfs_datasets_py.logic.autoformal import supervisor_dispatch as dispatch
    inf,worker,parent,child,request,_,_,runtime,save=_supervisor_audit_metadata(tmp_path,seed,typed=typed,candidate=candidate)
    root=Path(dispatch.__file__).resolve().parents[3];cli=root/dispatch.REVIEWED_EVALUATION_ENTRYPOINT
    request.update(schema='reviewed-source-evaluation-request/v1',request_id='fixture:simulated-dispatch',operation='heldout_evaluation',
        attempt_directory=str(tmp_path),lifecycle_source_sha256={str(cli):hashlib.sha256(cli.read_bytes()).hexdigest()})
    reference=worker.CheckpointArtifact.from_dict(save('request',request))
    false_claims=('training_executed','admitted','model_quality_qualified','legal_meaning_verified','proof_authority','convergence_proved','corpus_admitted')
    child.update(schema='reviewed-source-evaluation-cycle/v1',request_sha256=reference.sha256,completed=True,execution_path='inference',
        inference={'profile':request['schema'],**{n:str(tmp_path/(n+'.json')) for n in ('evaluation','loader','generation')}},
        **dict.fromkeys(false_claims,False))
    child_ref=worker.CheckpointArtifact.from_dict(save('cycle',child))
    parent.update(child, schema=parent['schema'],child_cycle_artifact=dict(path=child_ref.path,bytes=child_ref.bytes,sha256=child_ref.sha256),
        parent_receipt=str(tmp_path/'parent-cycle.json'),receipt=str(tmp_path/'cycle.json'),parent_callbacks=dict(finished=True,closed=True,child_identity={'fixture':'not-a-real-child'}),
        original_child_identity={'fixture':'not-a-real-child'},original_child_waited=True,parent_FINISH_acknowledged=True,
        parent_current_admission_rechecked_after_wait=True,parent_output_artifacts_rechecked_after_wait=True,
        resource_release_performed=False,original_owner_reservation_id=runtime.owner.reservation_id)
    if typed:
        parent['typed_structure_audit_artifact']=save('typed-structure-audit',inf._build_parent_typed_structure_audit(child,request,child_ref,reference.sha256,inf._parent_typed_structure_source_pins()))
    if candidate:
        parent['candidate_syntax_audit_artifact']=save('candidate-syntax-audit',inf._build_parent_candidate_syntax_audit(child,request,child_ref,reference.sha256,inf._parent_candidate_syntax_source_pins(),candidate))
    save('parent-cycle',parent)
    monkeypatch.setattr(inf,'_read_reviewed_evaluation_request',lambda _: (reference,b'fixture-only',deepcopy(request)))
    def simulated_cli_import(code, namespace):
        builtins.exec(code,namespace)
        namespace['main']=lambda *_a,**_k:0 # No process, model, owner or real wait is exercised.
    monkeypatch.setattr(dispatch,'exec',simulated_cli_import,raising=False)
    task=dict(task_id=request['request_id'],work_kind=dispatch.WORK_KIND_REVIEWED_EVALUATION,revision=9,status='blocked',operator_hold=True,
        attempt=2,max_attempts=2,historical_provider_outcome='UNKNOWN',claims=[])
    descriptor=dict(path=reference.path,bytes=reference.bytes,sha256=reference.sha256)
    bound=dispatch.bind_reviewed_evaluation_task(task,descriptor)
    return dispatch,bound,runtime,parent,request


@pytest.mark.parametrize('typed,candidate',[(False,None),(True,None),(False,'unreviewed-complete-norm-candidate-syntax/v3'),(True,'unreviewed-complete-norm-candidate-syntax/v3')])
def test_reviewed_supervisor_audit_simulated_adapter_flow_preserves_task_authority(tmp_path,reviewed_supervisor_audit_seed,monkeypatch,typed,candidate):
    from copy import deepcopy
    dispatch,task,runtime,parent,_=_simulated_reviewed_dispatch(tmp_path,reviewed_supervisor_audit_seed,monkeypatch,typed=typed,candidate=candidate)
    before=deepcopy(task);result=dispatch.execute_reviewed_evaluation_task(task,reviewed_parent_runtime=runtime)
    assert task==before
    assert result['schema']==('supervisor-reviewed-source-evaluation-result/v2' if typed or candidate else 'supervisor-reviewed-source-evaluation-result/v1')
    assert all(result[k] is False for k in ('training_executed','task_status_changed','task_completion_authority','resource_release_performed','admitted'))
    if typed or candidate:
        assert result['parent_schema']==parent['schema'] and result['parent_audits_recomputed'] is True
        assert result['audit_artifacts']


@pytest.mark.parametrize('damage',['sidecar','context'])
def test_reviewed_supervisor_audit_simulated_adapter_catches_final_callback_write(tmp_path,reviewed_supervisor_audit_seed,monkeypatch,damage):
    from dataclasses import replace
    dispatch,task,runtime,parent,request=_simulated_reviewed_dispatch(tmp_path,reviewed_supervisor_audit_seed,monkeypatch,candidate='unreviewed-complete-norm-candidate-syntax/v3')
    original=dispatch._validate_reviewed_parent_audits;phase={}
    def validated(*args,**kwargs):
        state=original(*args,**kwargs);phase['after_audit']=True;return state
    monkeypatch.setattr(dispatch,'_validate_reviewed_parent_audits',validated)
    def last_callback():
        if phase.get('after_audit'):
            target=parent['candidate_syntax_audit_artifact'] if damage=='sidecar' else request['source_contexts_artifact']
            Path(target['path']).write_text('{}\n')
    runtime=replace(runtime,source_guard=last_callback)
    with pytest.raises(ValueError):dispatch.execute_reviewed_evaluation_task(task,reviewed_parent_runtime=runtime)
