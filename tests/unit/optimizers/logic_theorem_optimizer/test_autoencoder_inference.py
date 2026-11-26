"""Immutable inference and resume tests; no model training, Lake or network."""
from concurrent.futures import Future
from dataclasses import asdict
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_inference as inference
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_candidate_qualification as qualification
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import SampleRecord
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    AdaptiveModalAutoencoder, ModalAutoencoderTrainingState,
)


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _sample(section):
    return asdict(SampleRecord.from_dict({"title": "inference-fixture", "section": str(section),
        "text": f"The officer shall retain record {section}."}))


class ImmediateExecutor:
    sizes = []

    def __init__(self, max_workers):
        self.sizes.append(max_workers)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def submit(self, function, *args):
        future = Future()
        try:
            future.set_result(function(*args))
        except BaseException as exc:
            future.set_exception(exc)
        return future


@pytest.fixture
def context(tmp_path, monkeypatch):
    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_text(ModalAutoencoderTrainingState().to_json() + "\n")
    inputs, validation = tmp_path / "samples.jsonl", tmp_path / "validation.jsonl"
    inputs.write_text("".join(json.dumps(_sample(index)) + "\n" for index in range(3)))
    validation.write_text(json.dumps(_sample("validation")) + "\n")
    def records(path):
        rows = [json.loads(line) for line in Path(path).read_text().splitlines()]
        return [{"record_id": inference.inc._sha(row), "sample": row} for row in rows]
    cli = SimpleNamespace(_pin=lambda: {"test_producer": "fixed"},
                          orchestration_hashes=lambda: {"test_orchestration": "fixed"},
                          local_records=records, _sha=_sha,
                          _write=lambda path, value: inference.inc._write(Path(path), value),
                          PINNED=tmp_path / "protected.json", PINNED_SHA="0" * 64)
    config = {"execution_mode": "inference", "input_jsonl": str(inputs),
              "validation_jsonl": str(validation), "checkpoint": str(checkpoint),
              "state_directory": str(tmp_path / "state"), "cycle_receipt": str(tmp_path / "cycle.json"),
              "lake_timeout_seconds": 1, "workers": 4, "max_parallel_workers": 4,
              "max_batches": 8, "memory_mb": 8192}
    def structural_failure(*args, **kwargs):
        return {"compiler": {"compiler_status": "test_fixture_abstain"},
                **{name: {"passed": False, "rows": [], "reason": "isolated_test_structure", "admitted": False}
                   for name in ("semantic_gate", "family_syntax_gate", "lake_gate")}}
    monkeypatch.setattr(qualification, "_structural_gates", structural_failure)
    ImmediateExecutor.sizes = []
    return config, cli


def _run(context, **kwargs):
    config, cli = context
    capacity = lambda **limits: {"workers": min(limits["max_workers"], limits["pending_count"])}
    return inference.run_inference_cycle(config, cli, executor_factory=ImmediateExecutor,
                                         capacity_callback=kwargs.pop("capacity_callback", capacity), **kwargs)


def _first_pass(context):
    config, cli = context
    checkpoint = Path(config["checkpoint"])
    candidate = {"path": str(checkpoint), "sha256": _sha(checkpoint), "bytes": checkpoint.stat().st_size}
    sample = cli.local_records(config["input_jsonl"])[0]["sample"]
    heldout = [row["sample"] for row in cli.local_records(config["validation_jsonl"])]
    return (candidate, "inference-" + candidate["sha256"], sample, heldout,
            Path(config["state_directory"]) / "direct-pass", 1)


def test_inference_calls_neither_training_registry_nor_hub_and_keeps_weights(context, monkeypatch):
    from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
    from ipfs_datasets_py.huggingface import autoencoder_incremental as publication
    from ipfs_datasets_py.huggingface import autoencoder_span_attempts as attempts
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_qualified_training as training
    def forbidden(*args, **kwargs):
        pytest.fail("inference entered a mutating training/control/publication boundary")
    monkeypatch.setattr(AdaptiveModalAutoencoder, "train_generalizable_projection", forbidden)
    monkeypatch.setattr(AutoencoderRegistry, "__init__", forbidden)
    monkeypatch.setattr(worker, "execute_training_job", forbidden)
    monkeypatch.setattr(training, "run_qualified_incremental_training", forbidden)
    monkeypatch.setattr(publication, "publish_sparse_update", forbidden)
    monkeypatch.setattr(publication, "enqueue_sparse_update", forbidden)
    monkeypatch.setattr(attempts, "publish_span_attempt", forbidden)
    before = Path(context[0]["checkpoint"]).read_bytes()
    result = _run(context)
    assert Path(context[0]["checkpoint"]).read_bytes() == before
    assert result["execution_path"] == "inference" and result["training_executed"] is False
    assert result["training"] is None and result["weight_publications"] == []
    assert result["admitted"] is result["formalized"] is result["promotion_performed"] is False
    assert result["dispatched_pass_count"] == 3 and result["pending_pass_count"] == 0
    assert all(row["qualified"] is False for row in result["inference"])
    assert not list(Path(context[0]["state_directory"]).rglob("*.duckdb"))


@pytest.mark.parametrize("update", [
    {"execution_mode": "training"}, {"execution_mode": "automatic"},
    {"input_jsonl": None}, {"validation_jsonl": None},
    {"repository_id": "test/data"}, {"publish_repository": "test/data"},
    {"arrow_feature_weights": "weights.arrow"}, {"shared_targets": "targets.arrow"},
])
def test_invalid_route_or_training_inputs_rejected_before_loading(context, update):
    config, cli = context
    config.update(update)
    cli._pin = lambda: pytest.fail("invalid route loaded producers")
    with pytest.raises(ValueError):
        _run(context)
    assert not Path(config["state_directory"]).exists()


def test_completed_pass_reuse_verifies_evidence_without_requalifying(context, monkeypatch):
    args = _first_pass(context)
    first = inference._pass(*args)
    receipt_before = Path(first["receipt"]).read_bytes()
    monkeypatch.setattr(qualification, "qualify_candidate", lambda *a, **k: pytest.fail("completed pass reran"))
    assert inference._pass(*args) == first
    assert Path(first["receipt"]).read_bytes() == receipt_before


def test_modified_receipt_fails_unchanged_seal(context):
    args = _first_pass(context)
    first = inference._pass(*args)
    path = Path(first["receipt"])
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="retained inference evidence changed"):
        inference._pass(*args)


@pytest.mark.parametrize("corruption", ["route", "gate", "row_source", "metrics"])
def test_resealed_tampering_cannot_cross_route_or_qualification_gates(context, corruption):
    args = _first_pass(context)
    first = inference._pass(*args)
    path = Path(first["receipt"])
    receipt = json.loads(path.read_bytes())
    if corruption == "route":
        receipt["training_executed"] = True
    elif corruption == "gate":
        receipt["execution_gate_applied"] = False
    elif corruption == "row_source":
        row = receipt["rows"][0]
        row["source"]["text"] = "Another source sentence."
        row["source_sha256"] = hashlib.sha256(row["source"]["text"].encode()).hexdigest()
    else:
        receipt["qualified"] = True
        for row in receipt["rows"]:
            row["qualified"] = True
            for gate in ("metric_gate", "semantic_gate", "family_syntax_gate", "lake_gate"):
                row[gate]["passed"] = True
            row["metric_gate"].update(embedding_cosine_similarity=.1, reconstruction_loss=.9)
        for name, gate in receipt["gate_results"].items():
            gate["passed"] = True
            receipt[name] = gate
    raw = json.dumps(receipt).encode()
    path.write_bytes(raw)
    inference.inc._write(path.with_name("inference-seal.json"),
                         {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})
    with pytest.raises(ValueError):
        inference._pass(*args)


def test_unfinished_pass_keeps_partial_artifacts_and_requires_recovery(context):
    args = _first_pass(context)
    directory = args[4]
    directory.mkdir(parents=True)
    marker = directory / "interrupted.txt"
    marker.write_text("not qualification evidence")
    with pytest.raises(ValueError, match="explicit recovery"):
        inference._pass(*args)
    assert marker.read_text() == "not qualification evidence"
    assert not (directory / "inference-seal.json").exists()


@pytest.mark.parametrize("change", ["checkpoint", "sources", "validation", "timeout"])
def test_resume_rejects_changed_semantic_binding(context, change):
    _run(context)
    config, cli = context
    if change == "checkpoint":
        with Path(config["checkpoint"]).open("a") as stream:
            stream.write(" ")
    elif change == "sources":
        cli.orchestration_hashes = lambda: {"test_orchestration": "changed"}
    elif change == "validation":
        Path(config["validation_jsonl"]).write_text(json.dumps(_sample("other-validation")) + "\n")
    else:
        config["lake_timeout_seconds"] = 2
    with pytest.raises(ValueError, match="new state required"):
        _run(context)


def test_zero_capacity_defers_then_resume_changes_hardware_without_changing_pass_identity(context, monkeypatch):
    config, cli = context
    zero = _run(context, capacity_callback=lambda **limits: {"workers": 0})
    assert zero["dispatched_pass_count"] == 0 and zero["pending_pass_count"] == 3
    assert not (Path(config["state_directory"]) / "inference/passes").exists()
    binding_path = Path(config["state_directory"]) / "inference/binding.json"
    binding = binding_path.read_bytes()
    config.update(max_batches=1, workers=1, max_parallel_workers=1)
    first = _run(context)
    assert first["dispatched_pass_count"] == 1 and first["pending_pass_count"] == 2
    saved = first["inference"][0]
    config.update(max_batches=8, workers=32, max_parallel_workers=3, memory_mb=16384)
    second = _run(context)
    assert second["dispatched_pass_count"] == 2 and second["pending_pass_count"] == 0
    assert saved in second["inference"] and binding_path.read_bytes() == binding
    assert ImmediateExecutor.sizes == [1, 2]
    monkeypatch.setattr(qualification, "qualify_candidate", lambda *a, **k: pytest.fail("resume requalified"))
    config.update(workers=2, max_parallel_workers=2)
    last = _run(context)
    assert last["dispatched_pass_count"] == 0 and last["pending_pass_count"] == 0
    assert sorted(last["inference"], key=lambda r: r["receipt"]) == sorted(second["inference"], key=lambda r: r["receipt"])


def test_capacity_is_rechecked_between_waves_without_changing_samples(context):
    calls = []
    def capacity(**limits):
        calls.append(limits)
        return {"workers": 1 if len(calls) == 1 else limits["pending_count"]}
    result = _run(context, capacity_callback=capacity)
    assert [call["pending_count"] for call in calls] == [3, 2]
    assert ImmediateExecutor.sizes == [1, 2]
    assert result["dispatched_pass_count"] == 3 and len(result["inference"]) == 3


def test_machine_shards_cover_inputs_once_independent_of_worker_capacity(context):
    config, cli = context
    observed = []
    def check(candidate, version, sample, heldout, directory, timeout):
        observed.append((config["shard_index"], sample["section"]))
        return {"qualified": False, "admitted": False}
    config.update(shard_count=2, workers=1, max_parallel_workers=1)
    for shard in range(2):
        config["shard_index"] = shard
        _run(context, pass_function=check)
        config.update(workers=8, max_parallel_workers=8)
    assert sorted(section for _, section in observed) == ["0", "1", "2"]
    for shard, section in observed:
        assert int(inference.inc._sha(_sample(section)), 16) % 2 == shard


def test_cli_dispatches_inference_before_training_registry_and_rejects_unknown_mode(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[4] / "scripts/ops/legal_ir/run_incremental_autoencoders.py"
    name = "_test_inference_route_cli"
    spec = importlib.util.spec_from_file_location(name, path)
    cli = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, cli)
    spec.loader.exec_module(cli)
    marker = object()
    calls = []
    def route(config, namespace):
        calls.append((config, namespace))
        return marker
    monkeypatch.setattr(inference, "run_inference_cycle", route)
    monkeypatch.setattr(cli, "_pin", lambda **kwargs: pytest.fail("training producer path entered"))
    config = {"execution_mode": "inference", "state_directory": str(tmp_path / "state")}
    assert cli.run_cycle(config) is marker
    assert calls[0][0] is config
    with pytest.raises(ValueError):
        cli.run_cycle({"execution_mode": "unknown"})


def test_inference_nested_callback_receives_complete_reserved_cpu_envelope(context):
    config, _ = context
    config.update(max_parallel_workers=7, reserved_cpu_slots=8, reserved_child_process_slots=23)
    seen = []
    def capacity(**limits):
        seen.append(limits)
        return {"workers": min(limits["max_workers"], limits["pending_count"])}
    _run(context, capacity_callback=capacity)
    assert seen and all(call["cpu_budget"] == 8 for call in seen)


def test_reviewed_inference_cli_without_parent_runtime_refuses_before_effects(tmp_path, monkeypatch):
    """The normal opt-in must reject an unconfigured caller before any loader."""
    path = Path(__file__).resolve().parents[4] / "scripts/ops/legal_ir/run_incremental_autoencoders.py"
    name = "_test_reviewed_inference_unconfigured_normal_cli"
    spec = importlib.util.spec_from_file_location(name, path)
    cli = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, cli)
    spec.loader.exec_module(cli)
    state = tmp_path / "original-owner-attempt"
    state.mkdir(mode=0o700)
    marker = state / "retained-original-marker.txt"
    marker.write_bytes(b"unconfigured CLI must preserve existing bytes")
    request = tmp_path / "reviewed-evaluation-request.json"
    request.write_bytes(b"{}\n")
    request_sha256 = _sha(request)
    def forbidden(*args, **kwargs):
        pytest.fail("unconfigured reviewed inference crossed legacy/model/policy boundary")
    monkeypatch.setattr(cli, "run_cycle", forbidden)
    monkeypatch.setattr(cli, "_pin", forbidden)
    monkeypatch.setattr(inference, "run_inference_cycle", forbidden)
    original_read = Path.read_bytes
    def guarded_read(selected):
        if selected == request:
            pytest.fail("unconfigured reviewed inference read its packet")
        return original_read(selected)
    monkeypatch.setattr(Path, "read_bytes", guarded_read)
    with pytest.raises(ValueError, match="runtime"):
        cli.main(["--execution-mode", "inference", "--state-directory", str(state),
            "--reviewed-evaluation-request", str(request),
            "--reviewed-evaluation-sha256", request_sha256], reviewed_parent_runtime=None)
    assert marker.read_bytes() == b"unconfigured CLI must preserve existing bytes"
    assert sorted(p.name for p in state.iterdir()) == [marker.name]


@pytest.fixture
def reviewed_physical_owner(tmp_path, monkeypatch):
    """One real original Host owner using only a strict test-private scheduler.

    The outer qualification owns the productive host envelope. This fixture
    exercises the same original native/file APIs on small private state; it
    never substitutes a lease, patches admission, or creates a global grant.
    """
    import os
    import time
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as host
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as native
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import existing_resource_scheduler as existing
    root = tmp_path / "private-owned-root"
    root.mkdir(mode=0o700)
    attempt = root / "original-attempt"
    attempt.mkdir(mode=0o700)
    # Explicit qualification-only allowance; the ordinary fixture keeps its
    # original profile. The enclosing admitted request must reserve this too.
    memory_profile = os.environ.get("IPFS_DATASETS_TEST_REVIEWED_MEMORY_PROFILE", "1536")
    if memory_profile not in ("1536", "3072", "8192", "12288"):
        raise ValueError("unsupported reviewed physical memory profile")
    memory_mb = int(memory_profile)
    work_seconds = 600 if memory_profile == "12288" else 180 if memory_profile == "8192" else 120
    scheduler = native.GlobalResourceScheduler(native.ResourceSchedulerConfig(
        total_cpu_slots=1, total_memory_mb=memory_mb, total_child_process_slots=1,
        lane_reservations={}, state_path=tmp_path / "private-native.json", auto_renew_leases=False,
        proof_safety_enabled=True))
    initial = json.loads(scheduler.state_path.read_bytes())
    policy_sha = existing.policy_sha256(initial["config"])
    assert initial["leases"] == {} and initial["waiters"] == {}
    # Any accidental child default acquisition is observable in this SAME
    # private file. The real Host constructor still uses strict explicit pins.
    monkeypatch.setenv("IPFS_DATASETS_RESOURCE_SCHEDULER_PATH", str(scheduler.state_path))
    ledger = tmp_path / "private-disk.json"
    ledger.write_bytes(json.dumps({"schema": host.SCHEMA, "roots": [host._root_identity(root)],
        "limit_bytes": host.MAX_STORAGE_BYTES, "reservations": {}}, sort_keys=True).encode())
    owner = host.DaemonResourceReservation(ledger, roots=[root], storage_bytes=8 * 1024**2,
        memory_mb=memory_mb, cpu_slots=1, child_process_slots=1, timeout_seconds=work_seconds,
        ledger_lock_timeout_seconds=3, scheduler_state_path=scheduler.state_path,
        expected_scheduler_policy_sha256=policy_sha, require_existing_ledger=True)
    previous = native.resource_operation_deadline()
    work = min(time.monotonic() + work_seconds, previous.work_deadline_monotonic if previous else float("inf"))
    cleanup = min(work + 5, previous.native_deadline_monotonic if previous else float("inf"))
    facts = SimpleNamespace(owner=owner, root=root, attempt=attempt, ledger=ledger,
        scheduler=scheduler, initial=initial, policy_sha=policy_sha, deadline=work, host=host)
    with native.resource_admission_deadline(work_deadline_monotonic=work, native_deadline_monotonic=cleanup):
        with owner:  # The ONLY reservation/native entry in this fixture.
            owner.check_usage(attempt_directory=attempt)
            entered = json.loads(scheduler.state_path.read_bytes())
            assert len(entered["leases"]) == 1 and entered["waiters"] == {}
            assert entered["next_sequence"] == initial["next_sequence"] + 1
            lease = next(iter(entered["leases"].values()))
            assert lease["owner_pid"] == os.getpid() and not lease.get("parent_lease_id")
            assert set(json.loads(ledger.read_bytes())["reservations"]) == {owner.reservation_id}
            facts.lease_id = owner._lease.lease_id
            facts.entered_sequence = entered["next_sequence"]
            yield facts
    ended = json.loads(scheduler.state_path.read_bytes())
    assert ended["config"] == initial["config"] and ended["leases"] == {} and ended["waiters"] == {}
    assert ended["next_sequence"] == facts.entered_sequence  # No child entry or second root.
    assert owner.to_dict()["cleanup_error"] is None
    retained_row = json.loads(ledger.read_bytes())["reservations"][owner.reservation_id]
    assert retained_row["status"] in ("retained", "released")
    if retained_row["status"] == "retained":
        assert retained_row["artifacts_durable_asserted"] is False and attempt.is_dir()


def _reviewed_physical_cli(monkeypatch):
    path = Path(__file__).resolve().parents[4] / "scripts/ops/legal_ir/run_incremental_autoencoders.py"
    name = "_test_reviewed_physical_original_parent_cli"
    spec = importlib.util.spec_from_file_location(name, path)
    cli = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, cli)
    spec.loader.exec_module(cli)
    return cli


def _reviewed_physical_packet(facts, *, rich_fixture=None, admission_version="v2", operation="heldout_evaluation", runtime_profile=None, generation_policy=None, source_fixture=None, digest_omitted=False):
    """Independent physical source facts, signed heldout policy, real HF pair.

    Models are constructed only when a test calls this INSIDE its original
    admitted owner. No row canonical_ir is used to construct source contexts.
    The byte transport is the existing v2 format, with content-addressed leaves
    so identical signed bytes always identify one ordinary physical file.
    """
    from copy import deepcopy
    from tests.unit.optimizers.logic_theorem_optimizer import test_autoencoder_training_worker as model_fixtures
    from tests.unit.optimizers.logic_theorem_optimizer import test_legal_ir_evaluation_artifacts as evaluation_fixtures
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consumer_binding as consumer
    assert admission_version in {"v2", "v3"}
    assert admission_version == "v3" or operation == "heldout_evaluation"
    assert runtime_profile is None or (admission_version == "v3" and runtime_profile in {"builtin-llama-bfloat16/v1", "builtin-qwen2-bfloat16/v1"})
    assert generation_policy is None or runtime_profile is not None
    assert source_fixture is None or (rich_fixture is None and admission_version == "v3" and runtime_profile is not None)
    assert type(digest_omitted) is bool
    if digest_omitted:
        assert rich_fixture is None and source_fixture is None and admission_version == "v3"
        assert runtime_profile == "builtin-qwen2-bfloat16/v1" and generation_policy is not None
        assert generation_policy["schema"] == worker.REVIEWED_DIGEST_OMITTED_GENERATION_POLICY_SCHEMA
    actual_pretrained = source_fixture is not None or bool(getattr(rich_fixture, "actual_pretrained", False))
    calls = {"source": 0, "asset": 0, "admission": 0}
    assets = facts.root / "independent-local-assets"
    assets.mkdir(mode=0o700)
    if rich_fixture is None and source_fixture is None:
        if admission_version == "v3":
            consumer_helper, mixed_helper, admission, current, rows, consumer_options, _ = (
                evaluation_fixtures._producer_public_mixed_case(operation=operation))
            helper = mixed_helper.fixture
        else:
            consumer_helper, helper, admission, current, rows, consumer_options, _ = evaluation_fixtures._producer_public_heldout_case()
        def query_admission():
            return consumer_helper.reviewed_public_admission_inputs(helper, admission, current)
        declaration = current["declaration"]
        contexts = {"profile": "reviewed-source-selection-context/v2",
            "selection_context": {"schema": "caller-known-interpretation-selection/v1",
                "interpretation_id": declaration["interpretation_id"], "selection_mode": "identifier_only"},
            "rows": [{"id": "reviewed:" + unit["unit_id"], "unit_id": unit["unit_id"],
                "governing_context": deepcopy(declaration["governing_context"]),
                "source_binding": {"source_version_cid": unit["source_version"]["record_cid"],
                    "occurrence_cid": unit["occurrence"]["record_cid"], "document_revision": unit["document_revision"]}}
                for unit in declaration["units"]]}
    else:
        selected_fixture = rich_fixture if rich_fixture is not None else source_fixture
        helper, current = None, selected_fixture.query_case
        rows, consumer_options, contexts = selected_fixture.rows, selected_fixture.options, selected_fixture.contexts
        query_admission = selected_fixture.runtime.current_admission_provider

    def fresh_admission():
        calls["admission"] += 1
        return deepcopy(query_admission())

    if source_fixture is not None:
        fixture = source_fixture.model
    elif rich_fixture is None and runtime_profile is not None:
        fixture = _reviewed_physical_fixture_assets(facts, assets, "causal_lm", max_sequence_tokens=8192 if digest_omitted else 4096,
            local_model_profile=runtime_profile, **({"profiled_generation": True} if generation_policy is not None else {}),
            **({"digest_omitted": True} if digest_omitted else {}))
    else:
        fixture = (model_fixtures._reviewed_local_loader_hf_fixture(assets, admission_provider=fresh_admission,
                       max_sequence_tokens=4096 if admission_version == "v3" else 2048)
                   if rich_fixture is None else rich_fixture.model)
    assert [item["id"] for item in contexts["rows"]] == [row["id"] for row in rows]
    leaves = assets / "admission-and-data"
    leaves.mkdir(mode=0o700)
    def put(raw):
        digest = hashlib.sha256(raw).hexdigest()
        path = leaves / (digest + ".artifact")
        if not path.exists():
            with path.open("xb") as stream:
                stream.write(raw)
        assert path.read_bytes() == raw and path.stat().st_nlink == 1
        return {"path": str(path), "sha256": digest, "bytes": len(raw)}
    def put_json(value):
        return put(worker._json_bytes(value))

    def admission_artifact(captured_admission):
        byte_leaves = []

        def skeleton(value, path):
            if type(value) is bytes:
                byte_leaves.append({"path": path, "kind": "artifact_bytes", "artifact": put(value)} if value else
                    {"path": path, "kind": "empty_bytes", "bytes": 0, "sha256": hashlib.sha256(b"").hexdigest()})
                return None
            if type(value) is dict:
                return {key: skeleton(item, path + [key]) for key, item in sorted(value.items())}
            if type(value) is list:
                return [skeleton(item, path + [index]) for index, item in enumerate(value)]
            return value

        digest = consumer.reviewed_admission_inputs_sha256(captured_admission)
        transport = {"schema": "reviewed-cycle-admission-input-transport/v2",
            "skeleton": skeleton(captured_admission, []), "byte_leaves": byte_leaves,
            "admission_inputs_sha256": digest}
        return {"admission_inputs_sha256": digest, "admission_transport_artifact": put_json(transport)}

    fixed_lifecycle = inference._reviewed_evaluation_lifecycle_source_sha256(rich_context=rich_fixture is not None)
    source_options = ({"admission_profile": worker.REVIEWED_MIXED_ADMISSION_PROFILE}
                      if admission_version == "v3" else {})
    fixed_decoder = worker._reviewed_decoder_source_pins(**source_options)
    memory_trace = {"last_time": 0.0, "last_rss": 0, "last_policy": None}
    def observe_memory(event):
        if not actual_pretrained or facts.owner._child is None:
            return
        import time
        now = time.monotonic()
        if event != "asset_policy" and now-memory_trace["last_time"] < .1:
            return
        usage = facts.host._group_usage(facts.owner._child)
        rss = usage.get("rss_bytes", 0)
        if event == "asset_policy" or now-memory_trace["last_time"] >= .25 or abs(rss-memory_trace["last_rss"]) >= 16*1024**2:
            with (facts.root / "actual-pretrained-parent-memory.jsonl").open("a") as stream:
                stream.write(json.dumps({"event": event, "monotonic": now, "child_usage": usage,
                    "parent_memory": worker._memory_observation(),
                    "outer_owner": facts.host._process(facts.host._process(facts.owner._owner_pid)["parent_pid"]),
                    "last_policy_schema": memory_trace["last_policy"],
                    "callback_counts": dict(calls), "model_or_budget_changed": False}) + "\n")
                stream.flush()
            memory_trace.update(last_time=now, last_rss=rss)
    def source_guard():
        # Raw fixed source identities; never nest a Source lease beneath the
        # original qualification's live READ while a writer may be queued.
        calls["source"] += 1
        for path, sha in fixed_lifecycle.items():
            assert _sha(path) == sha, "original lifecycle Source changed: " + path
        assert worker._reviewed_decoder_source_pins(**source_options) == fixed_decoder
        observe_memory("source_guard")
    def asset_policy(policy):
        calls["asset"] += 1
        assert policy["training_requested"] is False
        for name in ("downloads_requested", "resource_grant_requested"):
            assert policy.get(name, False) is False
        memory_trace["last_policy"] = policy.get("schema")
        observe_memory("asset_policy")
    payload = {"schema": "reviewed-source-evaluation-request/v1", "request_id": "fictional-physical-heldout-three",
        "operation": "heldout_evaluation", "heldout_evaluation_purpose": consumer.REVIEWED_HELDOUT_PURPOSE,
        "allow_fictional_fixture": True,
        "assets": {name: asdict(fixture.options[name]) for name in ("recipe_artifact", "model_config_artifact",
            "tokenizer_artifact", "license_artifact", "model_checkpoint", "optimizer_checkpoint")},
        "backend_identity": deepcopy(fixture.options["expected_backend_identity"]),
        "source_sha256": fixed_decoder, "lifecycle_source_sha256": fixed_lifecycle,
        **admission_artifact(fresh_admission()), "source_contexts_artifact": put_json(contexts), "rows_artifact": put_json(rows),
        "split_manifest_artifact": put_json(consumer_options["split_manifest"]),
        "exposure_artifact": put_json(consumer_options["exposure_records"]),
        "compiler_commit": "fictional:local-physical-inference-compiler",
        "checkpoint_declarations": {"encoder": {"id": "fictional:encoder-declaration-only", "sha256": "1" * 64},
            "decoder": {"id": fixture.options["expected_backend_identity"]["backend_id"],
                "sha256": fixture.options["model_checkpoint"].sha256}},
        "max_source_tokens": 2048, "max_output_tokens": 3, "max_model_bytes": 64 * 1024**2,
        "attempt_directory": str(facts.attempt), "output_directory": str(facts.attempt / "outputs")}
    if admission_version == "v3":
        payload.update(schema="reviewed-source-evaluation-request/v3",
            admission_profile=worker.REVIEWED_MIXED_ADMISSION_PROFILE,
            request_id="fictional-physical-mixed-source-only-" + operation, operation=operation,
            heldout_evaluation_purpose=consumer.REVIEWED_HELDOUT_PURPOSE if operation == "heldout_evaluation" else None,
            max_source_tokens=4096)
    context_callbacks = {}
    if rich_fixture is not None:
        training = rich_fixture.provider()
        mixed = admission_version == "v3"
        payload.update(schema="reviewed-source-evaluation-request/v4" if mixed else "reviewed-source-evaluation-request/v2",
            request_id="fictional-physical-heldout-rich-TRAIN-three",
            heldout_evaluation_purpose=(consumer.REVIEWED_V3_HELDOUT_CONTEXT_PURPOSE if mixed
                                        else consumer.REVIEWED_HELDOUT_CONTEXT_PURPOSE), max_source_tokens=4096,
            training_context={"profile": (consumer.REVIEWED_V3_HELDOUT_CONTEXT_PROFILE if mixed
                                          else consumer.REVIEWED_HELDOUT_CONTEXT_PROFILE),
                "context_inputs_sha256": rich_fixture.context_digest(training),
                **admission_artifact(training["admission_inputs"]), "rows_artifact": put_json(training["training_rows"]),
                "exposure_artifact": put_json(training["exposure_records"]),
                "retrieval_rows_artifact": put_json(training["retrieval_rows"])})
        context_callbacks = {"current_training_admission_provider": lambda: rich_fixture.provider()["admission_inputs"],
                             "context_policy_guard": rich_fixture.options["context_policy_guard"]}

    if runtime_profile is not None:
        payload.update(schema="reviewed-source-evaluation-request/v6" if rich_fixture is not None else "reviewed-source-evaluation-request/v5",
                       runtime_profile=runtime_profile)
    if generation_policy is not None:
        qwen2 = runtime_profile == "builtin-qwen2-bfloat16/v1"
        payload.update(schema=("reviewed-source-evaluation-request/v10" if rich_fixture is not None else "reviewed-source-evaluation-request/v9") if qwen2
            else ("reviewed-source-evaluation-request/v8" if rich_fixture is not None else "reviewed-source-evaluation-request/v7"), generation_policy=deepcopy(generation_policy))
        if qwen2 and rich_fixture is not None:
            payload["training_context"]["context_budget_profile"] = generation_policy["context_budget_profile"]
    if digest_omitted:
        payload["schema"] = inference.REVIEWED_DIGEST_OMITTED_EVALUATION_REQUEST_SCHEMA
    def write_request():
        return put_json(payload)

    return SimpleNamespace(payload=payload, write_request=write_request, source_guard=source_guard,
        asset_policy=asset_policy, fresh_admission=fresh_admission, calls=calls, fixture=fixture, context_callbacks=context_callbacks,
        helper=helper, current=current, worker=worker, original_assets=({name: Path(item["path"]).read_bytes()
            for name, item in payload["assets"].items()} if not actual_pretrained else {}))


def _reviewed_physical_run(cli, facts, packet, *, source_guard=None, asset_policy=None, admission_provider=None,
                           context_callbacks=None, typed_structure_profile=None):
    request = packet.write_request()
    # Asset preparation is complete and its real child has exited. Return free
    # setup heap pages before launching the unchanged inference child; do not
    # retain allocator slack inside the original combined-RSS envelope.
    import gc, ctypes, time
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
    before = worker._memory_observation()
    collected = gc.collect(2)
    trim_supported, trim_result = False, None
    if sys.platform == "linux":
        libc = ctypes.CDLL(None)
        if hasattr(libc, "malloc_trim"):
            trim_supported = True
            libc.malloc_trim.argtypes = [ctypes.c_size_t]
            libc.malloc_trim.restype = ctypes.c_int
            trim_result = libc.malloc_trim(0)
    (facts.root / ("parent-heap-before-cli-" + str(time.monotonic_ns()) + ".json")).write_bytes(worker._json_bytes(dict(
        before=before, after=worker._memory_observation(), unreachable_objects_collected=collected,
        allocator_trim_supported=trim_supported, allocator_trim_result=trim_result,
        model_tokens_or_resource_limits_changed=False)))
    runtime = inference.ReviewedInferenceParentRuntime(facts.owner,
        source_guard or packet.source_guard, asset_policy or packet.asset_policy,
        admission_provider or packet.fresh_admission, facts.deadline,
        typed_structure_profile=typed_structure_profile,
        **(packet.context_callbacks if context_callbacks is None else context_callbacks))
    try:
        return cli.main(["--execution-mode", "inference", "--state-directory", str(facts.attempt),
            "--reviewed-evaluation-request", request["path"], "--reviewed-evaluation-sha256", request["sha256"]],
            reviewed_parent_runtime=runtime)
    except BaseException as original_error:
        def actual_child_log_diagnostic():
            import os, stat, base64
            path = facts.attempt / "reviewed-worker.log"
            limit = 64 * 1024
            before = path.lstat()
            assert path.resolve(strict=True) == path and path.parent.resolve(strict=True) == facts.attempt
            assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_uid == os.getuid()
            fields = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_uid", "st_gid", "st_size", "st_mtime_ns", "st_ctime_ns")
            full9 = lambda value: {key: str(getattr(value, key)) for key in fields}
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            try:
                assert full9(before) == full9(os.fstat(fd))
                offset = max(0, before.st_size - limit)
                assert os.lseek(fd, offset, os.SEEK_SET) == offset
                tail = bytearray()
                while len(tail) < limit:
                    piece = os.read(fd, limit - len(tail))
                    if not piece: break
                    tail.extend(piece)
                assert full9(before) == full9(os.fstat(fd)) == full9(path.lstat())
            finally:
                os.close(fd)
            assert len(tail) == before.st_size - offset
            return {"schema": "actual-owned-reviewed-child-failure-log-tail/v1", "path": str(path),
                "full9": full9(before), "actual_file_bytes": before.st_size, "tail_start_offset": offset,
                "retained_tail_bytes": len(tail), "truncated": offset != 0,
                "sha256": hashlib.sha256(tail).hexdigest(),
                "sha256_scope": "retained_tail_only" if offset else "whole_file",
                "tail_base64": base64.b64encode(tail).decode("ascii"),
                "tail_utf8_backslashreplace": bytes(tail).decode("utf-8", errors="backslashreplace"),
                "primary_error_replaced": False}
        try:
            original_error.add_note("ACTUAL_REVIEWED_CHILD_FAILURE_LOG=" + json.dumps(actual_child_log_diagnostic(), sort_keys=True, ensure_ascii=True))
        except BaseException as diagnostic_error:
            original_error.add_note("ACTUAL_REVIEWED_CHILD_FAILURE_LOG_UNAVAILABLE=" + type(diagnostic_error).__name__ + ": " + str(diagnostic_error)[:2048])
        raise



def _reviewed_physical_tokenizer_only(facts, artifacts, preparation_complete):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
    class TokenizerOnly:
        @property
        def tokenizer(self):
            assert preparation_complete()
            assert facts.owner._child is not None
            assert facts.host._group_usage(facts.owner._child)["live_processes"] == 0
            from tokenizers import Tokenizer
            from transformers import PreTrainedTokenizerFast
            native = Tokenizer.from_file(artifacts["tokenizer_artifact"].path)
            recipe = json.loads(Path(artifacts["recipe_artifact"].path).read_bytes())
            options = recipe["tokenizer"]
            frontend = PreTrainedTokenizerFast(tokenizer_object=native,
                bos_token=options["bos_token"], eos_token=options["eos_token"],
                unk_token=options["unk_token"], pad_token=options["pad_token"],
                model_max_length=options["model_max_length"],
                clean_up_tokenization_spaces=options["clean_up_tokenization_spaces"])
            return worker.ReviewedPretrainedTokenizer(frontend, bos_token_id=frontend.bos_token_id, eos_token_id=frontend.eos_token_id,
                vocab_size=native.get_vocab_size(with_added_tokens=True))
    return TokenizerOnly()


def _reviewed_physical_fixture_assets(facts, directory, architecture="encoder_decoder", **options):
    """Build unchanged real HF assets in a genuinely waited short-lived child.

    The physical-test parent retains descriptors, not a second model/optimizer.
    The original outer Host envelope covers this child; no new scheduler/native
    grant or larger budget is requested. Its fresh canonical compiled buffers
    are observed, not cryptographically attested. Tokenizer loading stays lazy
    until the original inference child has exited and expected inputs are checked.
    """
    import os
    import subprocess
    import time
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
    assert facts.owner.to_dict()["status"] == "active"
    assert set(options) <= {"admission_provider", "max_sequence_tokens", "fixed_json_schema_subwords",
                            "fixed_typed_schema_subwords", "ranked_context_snapshot", "ranked_context_snapshot_artifact", "local_model_profile", "profiled_generation", "digest_omitted"}
    configuration = {key: value for key, value in options.items() if key != "admission_provider"}
    root = Path(__file__).resolve().parents[4]
    def existing_package_binding():
        # Top-level spec lookup is metadata only: do not import a model in the
        # parent, install packages, or inherit the parent's whole search path.
        import importlib.util
        origins, roots = {}, {}
        for name in ("transformers", "torch"):
            spec = importlib.util.find_spec(name)
            assert spec is not None and type(spec.origin) is str, "existing package origin required: " + name
            origin = Path(spec.origin)
            assert origin.is_absolute() and origin.is_file(), "existing package file required: " + name
            origin = origin.resolve(strict=True)
            assert origin.name == "__init__.py" and origin.parent.name == name, "ordinary package required: " + name
            locations = spec.submodule_search_locations
            assert locations is not None and len(locations) == 1 and Path(locations[0]).resolve(strict=True) == origin.parent, "package location differs: " + name
            package_root = origin.parent.parent
            assert any(type(item) is str and item and Path(item).is_absolute()
                and Path(item).resolve(strict=False) == package_root for item in sys.path), "package root is not already visible to parent: " + name
            origins[name], roots[name] = str(origin), str(package_root)
        assert roots["torch"] == roots["transformers"], "Torch and Transformers must use the same existing package root"
        return {"schema": "physical-fixture-existing-package-binding/v1", "package_root": roots["transformers"], "package_origins": origins}
    package_binding = existing_package_binding()
    script = r"""import sys,json,hashlib,importlib.machinery,importlib.util
from pathlib import Path
from dataclasses import asdict
root=Path(sys.argv[1]);sys.path.insert(0,str(root));sys.dont_write_bytecode=True
binding=json.loads(sys.argv[5])
assert type(binding) is dict and set(binding)=={"schema","package_root","package_origins"}
assert binding["schema"]=="physical-fixture-existing-package-binding/v1"
assert type(binding["package_root"]) is str
package_root=Path(binding["package_root"])
assert package_root.is_absolute() and package_root.resolve(strict=True)==package_root and package_root.is_dir()
assert type(binding["package_origins"]) is dict and set(binding["package_origins"])=={"transformers","torch"}
sys.path.insert(1,str(package_root))
for name in ("transformers","torch"):
 expected=binding["package_origins"][name]
 assert type(expected) is str
 origin=Path(expected)
 assert origin.is_absolute() and origin.resolve(strict=True)==origin and origin.parent.parent==package_root
 spec=importlib.util.find_spec(name)
 assert spec is not None and type(spec.origin) is str and Path(spec.origin).resolve(strict=True)==origin, "child package origin differs: "+name
 assert spec.submodule_search_locations is not None and len(spec.submodule_search_locations)==1 and Path(spec.submodule_search_locations[0]).resolve(strict=True)==origin.parent, "child package location differs: "+name
assert sys.flags.isolated==1
compiled={};original=importlib.machinery.SourceFileLoader.get_code
def code(loader,name):
 p=Path(loader.path).resolve()
 if p.is_relative_to(root):
  raw=p.read_bytes();compiled[str(p)]=hashlib.sha256(raw).hexdigest();return loader.source_to_code(raw,str(p))
 return original(loader,name)
importlib.machinery.SourceFileLoader.get_code=code
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_training_worker import _reviewed_local_loader_hf_fixture
configuration=json.loads(sys.argv[4]);ranked_snapshot=None
actual_snapshot=configuration.pop("ranked_context_snapshot_artifact",None)
if actual_snapshot is not None:
 from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_inference import _qualified_actual_GTE_ranked_snapshot
 ranked_snapshot=_qualified_actual_GTE_ranked_snapshot(actual_snapshot)
elif configuration.pop("ranked_context_snapshot",False):
 from tests.unit.optimizers.logic_theorem_optimizer.test_legal_ir_evaluation_artifacts import _ranked_mixed_context_join
 captured=[]
 _ranked_mixed_context_join("healthy",capture=captured.append)
 assert len(captured)==1
 ranked_snapshot=captured[0]
profiled=configuration.pop("profiled_generation",False)
assert type(profiled) is bool
digest_omitted=configuration.pop("digest_omitted",False)
assert type(digest_omitted) is bool
if digest_omitted:
 assert profiled and sys.argv[3]=="causal_lm"
 assert configuration=={"max_sequence_tokens":8192,"local_model_profile":"builtin-qwen2-bfloat16/v1"}
 from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_training_worker import _digest_omitted_Qwen_local_fixture
 fixture=_digest_omitted_Qwen_local_fixture(Path(sys.argv[2]))
elif profiled:
 from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_training_worker import _reviewed_chatml_local_asset_fixture
 fixture=_reviewed_chatml_local_asset_fixture(Path(sys.argv[2]),sys.argv[3],**configuration)
else:
 fixture=_reviewed_local_loader_hf_fixture(Path(sys.argv[2]),sys.argv[3],**configuration)
keys=('recipe_artifact','model_config_artifact','tokenizer_artifact','license_artifact','model_checkpoint','optimizer_checkpoint')
result={'assets':{k:asdict(fixture.options[k]) for k in keys},'backend_identity':fixture.options['expected_backend_identity'],'compiled_sources':compiled,'existing_package_binding':binding,'isolated_mode':sys.flags.isolated}
if ranked_snapshot is not None:result["ranked_context_snapshot"]=ranked_snapshot
assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in compiled.items())
print(json.dumps(result,sort_keys=True))
"""
    command = [sys.executable, "-I", "-B", "-c", script, str(root), str(directory), architecture,
               json.dumps(configuration, sort_keys=True), json.dumps(package_binding, sort_keys=True)]
    child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    try:
        stdout, stderr = child.communicate(timeout=max(.001, facts.deadline - time.monotonic()))
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
    assert child.returncode == 0, stderr
    result = json.loads(stdout)
    assert result["existing_package_binding"] == package_binding and result["isolated_mode"] == 1
    for path, digest in result["compiled_sources"].items():
        assert Path(path).is_relative_to(root) and _sha(path) == digest
    artifacts = {key: worker.CheckpointArtifact.from_dict(value) for key, value in result["assets"].items()}
    for artifact in artifacts.values():
        assert Path(artifact.path).is_relative_to(directory) and _sha(artifact.path) == artifact.sha256
        assert Path(artifact.path).stat().st_size == artifact.bytes
    # No model, optimizer or torch import is needed in the physical parent.
    tokenizer_only = _reviewed_physical_tokenizer_only(facts, artifacts, lambda: child.poll() == 0)
    receipt = {"schema": "physical-fixture-asset-preparation/v1", "pid": child.pid,
        "genuine_communicate_completed": True, "returncode": child.returncode,
        "parent_model_or_optimizer_retained": False, "new_resource_grant": False,
        "cryptographic_execution_attestation": False, **result}
    path = directory / "fixture-preparation.json"
    path.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
    return SimpleNamespace(backend=tokenizer_only, preparation_receipt=receipt,
        options={**artifacts, "expected_backend_identity": result["backend_identity"]})

def _reviewed_physical_rich_packet(facts, monkeypatch, **options):
    from tests.unit.optimizers.logic_theorem_optimizer import test_legal_ir_evaluation_artifacts as evaluation_fixtures
    directory = facts.root / "signed-rich-fixture"
    directory.mkdir(mode=0o700)
    fixture = evaluation_fixtures._reviewed_torch_rich_hparam_fixture(
        directory, monkeypatch, heldout=True,
        physical_model_factory=lambda path, architecture, **kwargs:
            _reviewed_physical_fixture_assets(facts, path, architecture, **kwargs), **options)
    return _reviewed_physical_packet(facts, rich_fixture=fixture), fixture


def _reviewed_physical_assert_stopped(facts):
    assert facts.owner._child is not None
    assert facts.host._group_usage(facts.owner._child)["live_processes"] == 0
    state = json.loads(facts.scheduler.state_path.read_bytes())
    assert state["next_sequence"] == facts.entered_sequence and state["waiters"] == {}
    assert set(json.loads(facts.ledger.read_bytes())["reservations"]) == {facts.owner.reservation_id}


def _reviewed_physical_fsync_tree(root):
    import os
    import stat
    for path in sorted(root.rglob("*")):
        value = path.lstat()
        assert stat.S_ISDIR(value.st_mode) or stat.S_ISREG(value.st_mode) and value.st_nlink == 1
        if stat.S_ISREG(value.st_mode):
            with path.open("rb") as stream:
                os.fsync(stream.fileno())
    for path in sorted([root, *(p for p in root.rglob("*") if p.is_dir())], key=lambda p: len(p.parts), reverse=True):
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _assert_reviewed_output_artifacts(output, *receipts):
    expected = {name: {"path": str(output / (name + ".json")),
        "sha256": _sha(output / (name + ".json")), "bytes": (output / (name + ".json")).stat().st_size}
        for name in ("evaluation", "loader", "generation")}
    for receipt in receipts:
        assert receipt["output_artifacts"] == expected
    return expected


@pytest.mark.parametrize("admission_version,operation", [("v2", "heldout_evaluation"),
    ("v3", "heldout_evaluation"), ("v3", "hparam_selection")])
def test_reviewed_inference_normal_cli_physical_original_owner_reaches_real_heldout_t5(
        reviewed_physical_owner, monkeypatch, capsys, admission_version, operation):
    facts = reviewed_physical_owner
    cli = _reviewed_physical_cli(monkeypatch)
    packet = _reviewed_physical_packet(facts, admission_version=admission_version, operation=operation)
    assert _reviewed_physical_run(cli, facts, packet) == 0
    report = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert report["parent_FINISH_acknowledged"] is report["original_child_waited"] is True
    assert report["parent_current_admission_rechecked_after_wait"] is True
    assert report["schema"] == "reviewed-source-evaluation-parent/v1" and report["completed"] is True
    assert report["original_owner_reservation_id"] == facts.owner.reservation_id
    assert report["resource_release_performed"] is False and facts.owner.to_dict()["status"] == "active"
    assert report["original_child_identity"] == facts.owner._child
    assert report["parent_callbacks"]["original_deadline_monotonic"] == facts.deadline
    assert report["parent_callbacks"]["owner_identity"]["pid"] == facts.owner._owner_pid
    assert report["parent_callbacks"]["finished"] is report["parent_callbacks"]["closed"] is True
    assert report["parent_callbacks"]["operations"]["FINISH"] == 1
    assert all(report["parent_callbacks"]["operations"][name] > 0 for name in ("GUARD", "ASSET", "ADMISSION"))
    assert all(report["parent_callbacks"][name] is False for name in (
        "resource_authority_granted", "storage_release_authorized", "reservation_entered_or_released"))
    assert all(packet.calls[name] > 0 for name in packet.calls)
    output = facts.attempt / "outputs"
    cycle = json.loads((output / "cycle.json").read_bytes())
    assert report["parent_output_artifacts_rechecked_after_wait"] is True
    _assert_reviewed_output_artifacts(output, cycle, report)
    assert json.loads((output / "parent-cycle.json").read_bytes()) == report
    assert report["parent_receipt"] == str(output / "parent-cycle.json")
    assert report["child_cycle_artifact"] == {"path": str(output / "cycle.json"),
        "sha256": _sha(output / "cycle.json"), "bytes": (output / "cycle.json").stat().st_size}
    evaluation = json.loads((output / "evaluation.json").read_bytes())
    generation = json.loads((output / "generation.json").read_bytes())
    loader = json.loads((output / "loader.json").read_bytes())
    assert cycle["completed"] is True and cycle["input_count"] == 3 and cycle["training"] is None
    assert cycle["training_executed"] is False and cycle["weight_publications"] == []
    assert all(cycle[name] is False for name in ("admitted", "model_quality_qualified", "legal_meaning_verified",
        "proof_authority", "convergence_proved", "corpus_admitted"))
    metric = evaluation["metrics"]["complete_norm_payload"]
    assert metric["denominator"] == metric["outcome_counts"]["abstained"] == 3
    assert metric["metric_numerators"]["full_nine_payload_exact"] == 0
    evaluated = evaluation["compiler_artifact"]["reviewed_source_span_producer_evaluation"]
    assert evaluated["producer_callback_count"] == 1 and evaluated["producer_exception_type"] is None
    assert all(evaluated[name] is False for name in ("producer_authenticity_verified",
        "loaded_checkpoint_identity_verified", "native_proof_verified", "source_fidelity_proved",
        "semantic_equivalence_proved", "corpus_admitted", "token_budget_enforced"))
    assert loader["matched_pair"] is loader["checkpoint_restored"] is True
    if admission_version == "v3":
        assert loader["schema"] == "reviewed-local-decoder-runtime-load/v2"
        assert loader["admission_profile"] == generation["admission_profile"] == packet.worker.REVIEWED_MIXED_ADMISSION_PROFILE
        assert evaluated["admission_before"]["schema"] == evaluated["admission_after"]["schema"] == "reviewed-source-span-consumer-binding/v3"
        assert evaluated["admission_before"]["operation"] == evaluated["admission_after"]["operation"] == operation
        assert report["inference"]["profile"] == "reviewed-source-evaluation-request/v3"
    else:
        assert loader["schema"] == "reviewed-local-decoder-runtime-load/v1"
        assert "admission_profile" not in loader and "admission_profile" not in generation
    assert generation["last_call"]["entry_pair_match"] is generation["last_call"]["exit_pair_match"] is True
    assert generation["last_call"]["input_receipt"]["target_access_performed"] is False
    assert all(item["outcome"] == "abstained" and item["candidate"] is None
        and item["generated_token_ids"] == [257, 0] for item in generation["last_call"]["raw_generation_outputs"])
    _reviewed_physical_assert_stopped(facts)
    assert set(json.loads(facts.scheduler.state_path.read_bytes())["leases"]) == {facts.lease_id}
    for name, item in packet.payload["assets"].items():
        assert Path(item["path"]).read_bytes() == packet.original_assets[name]
    _reviewed_physical_fsync_tree(facts.root)
    released = facts.owner.finalize(facts.attempt, artifacts_durable=True)
    assert released["status"] == "released" and released["record"]["artifacts_durable_asserted"] is True


def test_reviewed_inference_normal_cli_physical_original_owner_reaches_rich_heldout_t5(
        reviewed_physical_owner, monkeypatch, capsys):
    from ipfs_datasets_py.logic.autoformal import training_cycle_inputs as inputs
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_structured_retrieval as structured
    facts = reviewed_physical_owner
    cli = _reviewed_physical_cli(monkeypatch)
    packet, fixture = _reviewed_physical_rich_packet(facts, monkeypatch, shared_revision=True)
    context = packet.payload["training_context"]
    assert context["admission_inputs_sha256"] != packet.payload["admission_inputs_sha256"]
    assert _reviewed_physical_run(cli, facts, packet) == 0
    report = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert report["original_owner_reservation_id"] == facts.owner.reservation_id
    assert report["parent_FINISH_acknowledged"] is report["original_child_waited"] is True
    assert report["parent_current_admission_rechecked_after_wait"] is True
    assert report["parent_current_training_admission_rechecked_after_wait"] is True
    assert report["parent_context_policy_rechecked_after_wait"] is True
    assert report["current_training_admission_sha256"] == context["admission_inputs_sha256"]
    assert report["current_admission_sha256"] == packet.payload["admission_inputs_sha256"]
    assert report["context_inputs_sha256"] == context["context_inputs_sha256"]
    operations = report["parent_callbacks"]["operations"]
    assert operations["CONTEXT"] == fixture.checks["context_policy"] - 1 > 0
    assert operations["TRAIN_ADMISSION"] > 0 and operations["ADMISSION"] > 0 and operations["FINISH"] == 1
    assert report["training_executed"] is False and report["weight_publications"] == []
    assert report["resource_release_performed"] is False and facts.owner.to_dict()["status"] == "active"
    output = facts.attempt / "outputs"
    assert json.loads((output / "parent-cycle.json").read_bytes()) == report
    assert report["parent_output_artifacts_rechecked_after_wait"] is True
    _assert_reviewed_output_artifacts(output, json.loads((output / "cycle.json").read_bytes()), report)
    evaluation = json.loads((output / "evaluation.json").read_bytes())
    generation = json.loads((output / "generation.json").read_bytes())
    loader = json.loads((output / "loader.json").read_bytes())
    assert loader["checkpoint_restored"] is loader["matched_pair"] is True
    scores = evaluation["metrics"]["complete_norm_payload"]
    assert scores["denominator"] == scores["outcome_counts"]["abstained"] == 3
    assert scores["metric_numerators"]["full_nine_payload_exact"] == 0
    evaluated = evaluation["compiler_artifact"]["reviewed_source_span_producer_evaluation"]
    assert evaluated["configuration"]["profile"] == "reviewed-source-span-producer-heldout-rich-TRAIN/v1"
    assert evaluated["heldout_evaluation"]["training_example_ids"] == sorted(row["id"] for row in fixture.training_rows)
    assert evaluated["configuration"]["rich_training_context"]["retrieved_example_ids"] == [fixture.definition["id"]]
    assert evaluated["producer_callback_count"] == 1 and evaluated["producer_exception_type"] is None
    assert generation["context"]["heldout_context_supported"] is True
    call = generation["last_call"]
    assert call["entry_pair_match"] is call["exit_pair_match"] is True
    assert call["input_receipt"]["target_access_performed"] is False
    assert all(item["outcome"] == "abstained" and item["candidate"] is None
               and item["generated_token_ids"] == [257, 0] for item in call["raw_generation_outputs"])

    def digest(value):
        return hashlib.sha256(inputs._reviewed_wire(value)).hexdigest()

    training = fixture.provider()
    offered = structured.consume_reviewed_contexts_v2(**training, consumer=lambda payload: payload,
        expected_query_rows_sha256=digest(training["query_rows"]),
        expected_retrieval_rows_sha256=digest(training["retrieval_rows"]))
    source_arguments = []
    for source, row in zip(training["query_rows"], offered["rows"], strict=True):
        example, = row["examples"]
        assert example["canonical_ir"] == fixture.definition["canonical_ir"]
        assert example["source_link"] == fixture.definition["canonical_ir"]["source_binding"]
        source_arguments.append({**source, "context": {"permitted": [],
            "retrieved": [{"id": fixture.definition["id"], "content": example}]}})
    expected_records = inputs.prepare_reviewed_decoder_context_generation_inputs(source_arguments,
        source_contexts=fixture.contexts, expected_source_contexts_sha256=digest(fixture.contexts),
        expected_context_records_sha256=digest([{key: row[key] for key in ("id", "context")} for row in source_arguments]),
        tokenizer=fixture.model.backend.tokenizer, max_source_tokens=4096)
    assert call["source_arguments_sha256"] == digest(source_arguments)
    assert call["source_records_sha256"] == digest(expected_records["records"])
    assert call["input_receipt"] == expected_records["receipt"]
    for name, item in packet.payload["assets"].items():
        assert Path(item["path"]).read_bytes() == packet.original_assets[name]
    _reviewed_physical_assert_stopped(facts)
    _reviewed_physical_fsync_tree(facts.root)
    released = facts.owner.finalize(facts.attempt, artifacts_durable=True)
    assert released["status"] == "released" and released["record"]["artifacts_durable_asserted"] is True


def test_reviewed_inference_rich_heldout_context_policy_denial_preserves_original_error(
        reviewed_physical_owner, monkeypatch):
    facts = reviewed_physical_owner
    cli = _reviewed_physical_cli(monkeypatch)
    packet, fixture = _reviewed_physical_rich_packet(facts, monkeypatch)
    denial = PermissionError("original parent denied the separately reviewed TRAIN context")
    fixture.state["policy_error"] = denial
    with pytest.raises(PermissionError) as caught:
        _reviewed_physical_run(cli, facts, packet)
    assert caught.value is denial and fixture.checks["context_policy"] == 1
    assert not (facts.attempt / "outputs").exists()
    _reviewed_physical_assert_stopped(facts)


def test_reviewed_inference_rich_heldout_rechecks_train_admission_after_child_wait(reviewed_physical_owner, monkeypatch):
    facts = reviewed_physical_owner
    cli = _reviewed_physical_cli(monkeypatch)
    packet, fixture = _reviewed_physical_rich_packet(facts, monkeypatch)
    original_provider = packet.context_callbacks["current_training_admission_provider"]
    output = facts.attempt / "outputs"

    def current_training_admission():
        if (output / "cycle.json").exists():
            fixture.state["revoked"] = True
        return original_provider()

    packet.context_callbacks["current_training_admission_provider"] = current_training_admission
    with pytest.raises(ValueError, match="TRAIN admission changed after child completion"):
        _reviewed_physical_run(cli, facts, packet)
    assert fixture.state["revoked"] is True and fixture.state["query_revoked"] is False
    assert json.loads((output / "cycle.json").read_bytes())["completed"] is True
    assert not (output / "parent-cycle.json").exists()
    _reviewed_physical_assert_stopped(facts)


def test_reviewed_inference_rich_heldout_rechecks_exact_context_policy_after_child_wait(
        reviewed_physical_owner, monkeypatch):
    from copy import deepcopy
    facts = reviewed_physical_owner
    cli = _reviewed_physical_cli(monkeypatch)
    packet, _ = _reviewed_physical_rich_packet(facts, monkeypatch)
    original_policy = packet.context_callbacks["context_policy_guard"]
    output = facts.attempt / "outputs"
    last_approved = None
    denial = PermissionError("original context use revoked before parent publication")

    def context_policy(policy):
        nonlocal last_approved
        if (output / "cycle.json").exists():
            assert policy == last_approved
            _reviewed_physical_assert_stopped(facts)
            raise denial
        last_approved = deepcopy(policy)
        original_policy(policy)
        policy.clear()  # A callback cannot rewrite the acknowledged request kept by the parent.

    packet.context_callbacks["context_policy_guard"] = context_policy
    with pytest.raises(PermissionError) as caught:
        _reviewed_physical_run(cli, facts, packet)
    assert caught.value is denial
    assert json.loads((output / "cycle.json").read_bytes())["completed"] is True
    assert not (output / "parent-cycle.json").exists()
    _reviewed_physical_assert_stopped(facts)


@pytest.mark.parametrize("damage, diagnostic", [
    ("heldout_transport", "pinned local admission transport differs"),
    ("nested_reference", "heldout reference identity in rich producer context"),
])
def test_reviewed_inference_rich_heldout_refuses_changed_transport_or_leaked_reference(
        reviewed_physical_owner, monkeypatch, damage, diagnostic):
    facts = reviewed_physical_owner
    cli = _reviewed_physical_cli(monkeypatch)
    packet, fixture = _reviewed_physical_rich_packet(facts, monkeypatch, nested_query_identity=damage == "nested_reference")
    if damage == "heldout_transport":
        packet.payload["training_context"]["admission_transport_artifact"] = packet.payload["admission_transport_artifact"]
    with pytest.raises((RuntimeError, EOFError), match="child failed|callback endpoint closed"):
        _reviewed_physical_run(cli, facts, packet)
    assert diagnostic in (facts.attempt / "reviewed-worker.log").read_text()
    assert fixture.checks["context_policy"] == 0 and not (facts.attempt / "outputs").exists()
    if damage == "heldout_transport":
        assert packet.calls["asset"] == 0
    _reviewed_physical_assert_stopped(facts)


@pytest.mark.parametrize("admission_version", ["v2", "v3"])
def test_reviewed_inference_original_parent_asset_denial_precedes_missing_model_and_is_preserved(
        reviewed_physical_owner, monkeypatch, admission_version):
    facts = reviewed_physical_owner
    cli = _reviewed_physical_cli(monkeypatch)
    packet = _reviewed_physical_packet(facts, admission_version=admission_version)
    packet.payload["assets"]["model_checkpoint"]["path"] = str(facts.root / "never-created-model.pt")
    denial = PermissionError("original parent independently denied model asset")
    seen = []
    def deny(policy):
        seen.append(policy)
        raise denial
    with pytest.raises(PermissionError) as caught:
        _reviewed_physical_run(cli, facts, packet, asset_policy=deny)
    assert caught.value is denial and len(seen) == 1
    assert not (facts.root / "never-created-model.pt").exists()
    assert not (facts.attempt / "outputs").exists()
    _reviewed_physical_assert_stopped(facts)
    assert facts.owner.to_dict()["status"] == "active"  # Context exit retains; no release here.


@pytest.mark.parametrize("admission_version", ["v2", "v3"])
def test_reviewed_inference_late_new_parent_admission_mapping_refuses_completed_child(
        reviewed_physical_owner, monkeypatch, admission_version):
    facts = reviewed_physical_owner
    cli = _reviewed_physical_cli(monkeypatch)
    packet = _reviewed_physical_packet(facts, admission_version=admission_version)
    changed = []
    def fresh_after_output():
        if (facts.attempt / "outputs" / "cycle.json").exists() and not changed:
            packet.current["registry"]["keys"][0]["revoked_at_utc"] = packet.helper.EVALUATED
            packet.current["registry"]["revocation_generation"] += 1
            packet.helper.reviewed_resign_v2(packet.current)
            changed.append(True)
        return packet.fresh_admission()  # Always a NEW mapping, never mutate an older snapshot.
    with pytest.raises(ValueError, match="admission changed after child completion"):
        _reviewed_physical_run(cli, facts, packet, admission_provider=fresh_after_output)
    assert changed == [True]
    assert json.loads((facts.attempt / "outputs" / "cycle.json").read_bytes())["completed"] is True
    assert not (facts.attempt / "outputs" / "parent-cycle.json").exists()
    assert sorted(p.name for p in (facts.attempt / "outputs").iterdir()) == [
        "cycle.json", "evaluation.json", "generation.json", "loader.json"]
    _reviewed_physical_assert_stopped(facts)


@pytest.mark.parametrize("name", ["evaluation", "loader", "generation", "cycle"])
@pytest.mark.parametrize("admission_version", ["v2", "v3"])
def test_reviewed_inference_rechecks_exact_output_bytes_after_final_parent_callback(
        reviewed_physical_owner, monkeypatch, name, admission_version):
    facts = reviewed_physical_owner
    cli = _reviewed_physical_cli(monkeypatch)
    packet = _reviewed_physical_packet(facts, admission_version=admission_version)
    output = facts.attempt / "outputs"
    changed = []
    def mutate_after_output():
        if (output / "cycle.json").exists() and not changed:
            path = output / (name + ".json")
            original = path.read_bytes()
            # Valid JSON, same length: a size-only check cannot detect this.
            replacement = original[:2] + (b"x" if original[2:3] != b"x" else b"y") + original[3:]
            assert json.loads(original) != json.loads(replacement) and len(original) == len(replacement)
            path.write_bytes(replacement)
            changed.append({"path": str(path), "before": hashlib.sha256(original).hexdigest(),
                            "after": _sha(path), "bytes": len(original)})
        return packet.fresh_admission()
    with pytest.raises(ValueError, match="artifact changed"):
        _reviewed_physical_run(cli, facts, packet, admission_provider=mutate_after_output)
    assert len(changed) == 1 and changed[0]["before"] != changed[0]["after"]
    assert not (output / "parent-cycle.json").exists()
    assert sorted(p.name for p in output.iterdir()) == [
        "cycle.json", "evaluation.json", "generation.json", "loader.json"]
    _reviewed_physical_assert_stopped(facts)
    assert facts.owner.to_dict()["status"] == "active"


def test_reviewed_inference_original_private_native_cancellation_stops_before_asset_ack(reviewed_physical_owner, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_campaign_process as processes
    facts = reviewed_physical_owner
    cli = _reviewed_physical_cli(monkeypatch)
    packet = _reviewed_physical_packet(facts)
    cancelled = []
    def cancel_original(policy):
        packet.asset_policy(policy)
        assert facts.owner._lease.lease_id == facts.lease_id
        cancelled.append(facts.owner._lease.release())  # Only THIS real private original grant.
    with pytest.raises(processes.CampaignProcessError, match="custody cancelled|native root lease identity differs"):
        _reviewed_physical_run(cli, facts, packet, asset_policy=cancel_original)
    assert cancelled == [True] and facts.owner.cancelled is True
    assert not (facts.attempt / "outputs").exists()
    _reviewed_physical_assert_stopped(facts)


@pytest.mark.parametrize("extra", [
    ["--execution-mode", "training"], ["--input-jsonl", "forbidden-training.jsonl"],
    ["--validation-jsonl", "forbidden-validation.jsonl"], ["--repository-id", "forbidden:remote"],
    ["--publish-repository", "justicedao/uscode-autoformal-span-cache"], ["--feature-input-manifest", "forbidden-features.json"],
])
def test_reviewed_inference_normal_cli_refuses_mixed_legacy_or_remote_before_packet(reviewed_physical_owner, monkeypatch, extra):
    facts = reviewed_physical_owner
    cli = _reviewed_physical_cli(monkeypatch)
    request = facts.root / "unread-request.json"
    request.write_bytes(b"{}\n")
    digest = _sha(request)
    def forbidden(*args, **kwargs):
        pytest.fail("mixed reviewed CLI crossed packet/model/policy boundary")
    runtime = inference.ReviewedInferenceParentRuntime(facts.owner, forbidden, forbidden, forbidden, facts.deadline)
    original_read = Path.read_bytes
    def read(path):
        if path == request:
            forbidden()
        return original_read(path)
    monkeypatch.setattr(Path, "read_bytes", read)
    with pytest.raises(ValueError, match="exclusive"):
        cli.main(["--execution-mode", "inference", "--state-directory", str(facts.attempt),
            "--reviewed-evaluation-request", str(request), "--reviewed-evaluation-sha256", digest, *extra],
            reviewed_parent_runtime=runtime)
    assert facts.owner._child is None and not (facts.attempt / "reviewed-worker.log").exists()


@pytest.mark.parametrize("damage", ["extra_field", "training_operation", "output_escape",
    "legacy_with_context", "rich_selection", "rich_same_admission", "rich_missing_callback"])
def test_reviewed_inference_closed_data_packet_refuses_before_original_popen(reviewed_physical_owner, monkeypatch, damage):
    facts = reviewed_physical_owner
    cli = _reviewed_physical_cli(monkeypatch)
    # No HF fixture is needed to prove parser refusal before process/model work.
    # Structurally typed descriptors are DATA only, never model permissions.
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consumer_binding as consumer
    artifact = {"path": str(facts.root / "unread-asset"), "sha256": "1" * 64, "bytes": 1}
    value = {"schema": "reviewed-source-evaluation-request/v1", "request_id": "malformed-data-only",
        "operation": "hparam_selection", "heldout_evaluation_purpose": None, "allow_fictional_fixture": True,
        "assets": {name: dict(artifact) for name in ("recipe_artifact", "model_config_artifact", "tokenizer_artifact",
            "license_artifact", "model_checkpoint", "optimizer_checkpoint")}, "backend_identity": {},
        "source_sha256": worker._reviewed_decoder_source_pins(),
        "lifecycle_source_sha256": inference._reviewed_evaluation_lifecycle_source_sha256(),
        "admission_inputs_sha256": "2" * 64, **{name: dict(artifact) for name in ("admission_transport_artifact",
            "source_contexts_artifact", "rows_artifact", "split_manifest_artifact", "exposure_artifact")},
        "compiler_commit": "fictional:invalid-data", "checkpoint_declarations": {},
        "max_source_tokens": 2048, "max_output_tokens": 3, "max_model_bytes": 1024,
        "attempt_directory": str(facts.attempt), "output_directory": str(facts.attempt / "outputs")}
    if damage == "extra_field":
        value["serialized_owner_grant"] = {"approved": True}
    elif damage == "training_operation":
        value["operation"] = "train"
    elif damage == "output_escape":
        value["output_directory"] = str(facts.root / "outside-original-attempt")
    else:
        value["training_context"] = {"profile": consumer.REVIEWED_HELDOUT_CONTEXT_PROFILE,
            "admission_inputs_sha256": value["admission_inputs_sha256"] if damage == "rich_same_admission" else "3" * 64,
            "context_inputs_sha256": "4" * 64,
            **{name: dict(artifact) for name in ("admission_transport_artifact", "rows_artifact",
                "exposure_artifact", "retrieval_rows_artifact")}}
        if damage != "legacy_with_context":
            value.update(schema="reviewed-source-evaluation-request/v2",
                heldout_evaluation_purpose=consumer.REVIEWED_HELDOUT_CONTEXT_PURPOSE,
                lifecycle_source_sha256=inference._reviewed_evaluation_lifecycle_source_sha256(rich_context=True))
            if damage != "rich_selection":
                value["operation"] = "heldout_evaluation"
    path = facts.root / "malformed-request.json"
    path.write_bytes(worker._json_bytes(value))
    def forbidden(*args, **kwargs):
        pytest.fail("malformed DATA crossed policy/model boundary")
    lifecycle = dict(value["lifecycle_source_sha256"])
    decoder_sources = dict(value["source_sha256"])
    def raw_source_guard():
        assert all(_sha(path) == digest for path, digest in lifecycle.items())
        assert worker._reviewed_decoder_source_pins() == decoder_sources
    runtime = inference.ReviewedInferenceParentRuntime(facts.owner, raw_source_guard, forbidden, forbidden, facts.deadline)
    with pytest.raises(ValueError, match="closed reviewed|direct child|explicit frozen|independently committed|both live"):
        cli.main(["--execution-mode", "inference", "--state-directory", str(facts.attempt),
            "--reviewed-evaluation-request", str(path), "--reviewed-evaluation-sha256", _sha(path)],
            reviewed_parent_runtime=runtime)
    assert facts.owner._child is None and not (facts.attempt / "reviewed-worker.log").exists()



@pytest.mark.parametrize("profile", ["source-only", "rich-TRAIN", "source-only-v3"])
def test_reviewed_inference_supervisor_adapter_runs_normal_cli_and_preserves_native_task(
        reviewed_physical_owner, monkeypatch, profile):
    from copy import deepcopy
    import stat
    from ipfs_datasets_py.logic.autoformal import supervisor_dispatch as dispatch
    facts = reviewed_physical_owner
    rich = profile == "rich-TRAIN"
    packet = (_reviewed_physical_rich_packet(facts, monkeypatch)[0] if rich else
              _reviewed_physical_packet(facts, admission_version="v3" if profile == "source-only-v3" else "v2"))
    request = packet.write_request()
    task = {"task_id": packet.payload["request_id"], "work_kind": "reviewed_source_evaluation",
        "goal_id": "fictional:existing-goal", "subgoal_id": "fictional:existing-subgoal",
        "cid": "fictional:existing-native-task-cid", "revision": 7, "status": "running",
        "history": [{"revision": 6, "status": "ready"}, {"revision": 7, "status": "running"}]}
    original_task = deepcopy(task)
    bound = dispatch.bind_reviewed_evaluation_task(task, request)
    assert task == original_task
    assert bound["reviewed_evaluation"]["request_schema"] == packet.payload["schema"]
    bound_snapshot = deepcopy(bound)
    runtime = inference.ReviewedInferenceParentRuntime(facts.owner, packet.source_guard,
        packet.asset_policy, packet.fresh_admission, facts.deadline, **packet.context_callbacks)
    result = dispatch.execute_reviewed_evaluation_task(bound, reviewed_parent_runtime=runtime)
    assert bound == bound_snapshot and task == original_task

    assert result["task_id"] == packet.payload["request_id"] and result["request_sha256"] == request["sha256"]
    assert result["schema"] == "supervisor-reviewed-source-evaluation-result/v1"
    assert result["original_child_waited"] is True
    assert all(result[name] is False for name in ("training_executed", "task_status_changed",
        "task_completion_authority", "resource_release_performed", "admitted"))
    output = Path(packet.payload["output_directory"])
    def reference(path):
        observed = path.lstat()
        assert stat.S_ISREG(observed.st_mode) and observed.st_nlink == 1
        raw = path.read_bytes()
        return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
    parent_path, child_path = output / "parent-cycle.json", output / "cycle.json"
    assert result["parent_receipt"] == reference(parent_path)
    assert result["cycle_receipt"] == reference(child_path)
    parent = json.loads(parent_path.read_bytes())
    child = json.loads(child_path.read_bytes())
    assert parent["parent_output_artifacts_rechecked_after_wait"] is True
    assert result["output_artifacts"] == _assert_reviewed_output_artifacts(output, parent, child)
    assert parent["child_cycle_artifact"] == result["cycle_receipt"]
    assert parent["request_sha256"] == child["request_sha256"] == request["sha256"]
    assert parent["completed"] is child["completed"] is True
    assert parent["original_child_identity"] == facts.owner._child
    assert parent["parent_FINISH_acknowledged"] is parent["parent_current_admission_rechecked_after_wait"] is True
    assert parent.get("parent_current_training_admission_rechecked_after_wait", False) is rich
    assert parent.get("parent_context_policy_rechecked_after_wait", False) is rich
    assert parent["parent_callbacks"]["finished"] is parent["parent_callbacks"]["closed"] is True
    assert parent["parent_callbacks"]["original_deadline_monotonic"] == facts.deadline
    assert parent["original_owner_reservation_id"] == facts.owner.reservation_id
    child_references = {}
    for name in ("evaluation", "loader", "generation"):
        path = output / (name + ".json")
        assert parent["inference"][name] == child["inference"][name] == str(path)
        child_references[name] = reference(path)
    evaluation = json.loads((output / "evaluation.json").read_bytes())
    scores = evaluation["metrics"]["complete_norm_payload"]
    assert scores["denominator"] == scores["outcome_counts"]["abstained"] == 3
    assert scores["metric_numerators"]["full_nine_payload_exact"] == 0
    _reviewed_physical_assert_stopped(facts)
    assert facts.owner.to_dict()["status"] == "active"
    native = json.loads(facts.scheduler.state_path.read_bytes())
    assert set(native["leases"]) == {facts.lease_id} and native["waiters"] == {}
    ledger = json.loads(facts.ledger.read_bytes())
    assert set(ledger["reservations"]) == {facts.owner.reservation_id}
    assert ledger["reservations"][facts.owner.reservation_id]["status"] == "active"
    assert ledger["reservations"][facts.owner.reservation_id]["artifacts_durable_asserted"] is False
    for name, item in packet.payload["assets"].items():
        assert Path(item["path"]).read_bytes() == packet.original_assets[name]
    _reviewed_physical_fsync_tree(facts.root)
    released = facts.owner.finalize(facts.attempt, artifacts_durable=True)
    assert released["status"] == "released" and released["record"]["artifacts_durable_asserted"] is True
    assert result["parent_receipt"] == reference(parent_path) and result["cycle_receipt"] == reference(child_path)
    assert all(value == reference(output / (name + ".json")) for name, value in child_references.items())
    assert bound == bound_snapshot and task == original_task


@pytest.mark.parametrize("name", ["generation", "cycle", "parent-cycle", "parent-float-bytes"])
def test_reviewed_supervisor_rechecks_output_and_receipt_bytes_after_final_source_callback(
        reviewed_physical_owner, monkeypatch, name):
    from ipfs_datasets_py.logic.autoformal import supervisor_dispatch as dispatch
    facts = reviewed_physical_owner
    packet = _reviewed_physical_packet(facts)
    request = packet.write_request()
    task = {"task_id": packet.payload["request_id"], "work_kind": "reviewed_source_evaluation",
            "status": "running", "revision": 7}
    bound = dispatch.bind_reviewed_evaluation_task(task, request)
    snapshot = json.dumps(bound, sort_keys=True)
    output = facts.attempt / "outputs"
    completed_guards, changed = [], []
    def mutate_at_final_source_check():
        packet.source_guard()
        if (output / "parent-cycle.json").exists():
            completed_guards.append(True)
            if len(completed_guards) == 1 and name == "parent-float-bytes":
                path = output / "parent-cycle.json"
                value = json.loads(path.read_bytes())
                value["output_artifacts"]["generation"]["bytes"] = float(value["output_artifacts"]["generation"]["bytes"])
                path.write_bytes(packet.worker._json_bytes(value))
                changed.append(path)
            # First guard precedes reading receipts, second follows them.
            if len(completed_guards) == 2 and name != "parent-float-bytes":
                path = output / (name + ".json")
                original = path.read_bytes()
                replacement = original[:2] + b"x" + original[3:]
                assert json.loads(original) != json.loads(replacement) and len(original) == len(replacement)
                path.write_bytes(replacement)
                changed.append(path)
    runtime = inference.ReviewedInferenceParentRuntime(facts.owner, mutate_at_final_source_check,
        packet.asset_policy, packet.fresh_admission, facts.deadline)
    with pytest.raises(ValueError, match="base_checkpoint.bytes" if name == "parent-float-bytes" else "artifact changed"):
        dispatch.execute_reviewed_evaluation_task(bound, reviewed_parent_runtime=runtime)
    assert len(changed) == 1 and len(completed_guards) == 2
    assert json.dumps(bound, sort_keys=True) == snapshot and task["status"] == "running"
    assert (output / "parent-cycle.json").exists() and (output / "cycle.json").exists()
    _reviewed_physical_assert_stopped(facts)
    assert facts.owner.to_dict()["status"] == "active"


@pytest.mark.parametrize("damage", ["missing_map", "missing_output", "extra_output", "extra_descriptor_field",
    "redirected_path", "redirected_inference", "extra_inference", "oversized", "wrong_size", "wrong_hash",
    "zero_bytes", "boolean_bytes", "float_bytes", "symlink", "hardlink"])
def test_reviewed_output_artifacts_require_closed_bounded_exact_original_paths(tmp_path, damage):
    output = tmp_path / "outputs"
    output.mkdir()
    references = {}
    for name in ("evaluation", "loader", "generation"):
        path = output / (name + ".json")
        path.write_bytes(b'{"fixture":"fictional"}')
        references[name] = {"path": str(path), "sha256": _sha(path), "bytes": path.stat().st_size}
    request = {"schema": "reviewed-source-evaluation-request/v1", "output_directory": str(output)}
    cycle = {"output_artifacts": references, "inference": {"profile": request["schema"],
        **{name: value["path"] for name, value in references.items()}}}
    inference._check_reviewed_evaluation_outputs(cycle, request)
    if damage == "missing_map":
        del cycle["output_artifacts"]
    elif damage == "missing_output":
        del references["evaluation"]
    elif damage == "extra_output":
        references["unselected"] = dict(references["evaluation"])
    elif damage == "extra_descriptor_field":
        references["evaluation"]["authority"] = True
    elif damage in ("redirected_path", "symlink", "hardlink"):
        other = tmp_path / "identical.json"
        other.write_bytes((output / "evaluation.json").read_bytes())
        if damage == "redirected_path":
            references["evaluation"]["path"] = str(other)
        else:
            path = output / "evaluation.json"
            path.unlink()
            if damage == "symlink":
                path.symlink_to(other)
            else:
                import os
                os.link(other, path)
    elif damage == "redirected_inference":
        cycle["inference"]["evaluation"] = str(tmp_path / "other.json")
    elif damage == "extra_inference":
        cycle["inference"]["unselected"] = str(output / "evaluation.json")
    elif damage == "oversized":
        references["evaluation"]["bytes"] = inference.REVIEWED_EVALUATION_OUTPUT_LIMIT + 1
    elif damage == "wrong_size":
        references["evaluation"]["bytes"] += 1
    elif damage == "wrong_hash":
        references["evaluation"]["sha256"] = "0" * 64
    elif damage == "zero_bytes":
        references["evaluation"]["bytes"] = 0
    elif damage == "boolean_bytes":
        references["evaluation"]["bytes"] = True
    elif damage == "float_bytes":
        references["evaluation"]["bytes"] = float(references["evaluation"]["bytes"])
    with pytest.raises(ValueError):
        inference._check_reviewed_evaluation_outputs(cycle, request)


# Explicit source-only admission V3 DATA uses the same original-parent route.
def _reviewed_mixed_request_data(tmp_path):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consumer_binding as consumer
    attempt = tmp_path / "original-attempt"
    attempt.mkdir()
    artifact = {"path": str(tmp_path / "unread-artifact"), "sha256": "1" * 64, "bytes": 1}
    value = {"schema": "reviewed-source-evaluation-request/v3", "request_id": "fictional:mixed-source-only-data",
        "admission_profile": worker.REVIEWED_MIXED_ADMISSION_PROFILE,
        "operation": "heldout_evaluation", "heldout_evaluation_purpose": consumer.REVIEWED_HELDOUT_PURPOSE,
        "allow_fictional_fixture": True,
        "assets": {name: dict(artifact) for name in ("recipe_artifact", "model_config_artifact", "tokenizer_artifact",
            "license_artifact", "model_checkpoint", "optimizer_checkpoint")}, "backend_identity": {},
        "source_sha256": worker._reviewed_decoder_source_pins(admission_profile=worker.REVIEWED_MIXED_ADMISSION_PROFILE),
        "lifecycle_source_sha256": inference._reviewed_evaluation_lifecycle_source_sha256(),
        "admission_inputs_sha256": "2" * 64, **{name: dict(artifact) for name in ("admission_transport_artifact",
            "source_contexts_artifact", "rows_artifact", "split_manifest_artifact", "exposure_artifact")},
        "compiler_commit": "fictional:data-only", "checkpoint_declarations": {},
        "max_source_tokens": 4096, "max_output_tokens": 3, "max_model_bytes": 1024,
        "attempt_directory": str(attempt), "output_directory": str(attempt / "outputs")}
    def write_request():
        path = tmp_path / "request.json"
        path.write_bytes(worker._json_bytes(value))
        return {"path": str(path), "sha256": _sha(path), "bytes": path.stat().st_size}
    return worker, consumer, value, write_request


@pytest.mark.parametrize("operation", ["hparam_selection", "heldout_evaluation"])
def test_reviewed_inference_mixed_v3_request_authenticates_data_without_model_or_effects(tmp_path, monkeypatch, operation):
    import builtins
    worker, _consumer, value, write_request = _reviewed_mixed_request_data(tmp_path)
    value["operation"] = operation
    if operation == "hparam_selection":
        value["heldout_evaluation_purpose"] = None
    original_import = builtins.__import__
    def no_model_import(name, *args, **kwargs):
        if name.split(".", 1)[0] in {"torch", "transformers", "tokenizers"}:
            pytest.fail("reviewed request DATA imported a model package")
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", no_model_import)
    reference = write_request()
    loaded_reference, raw, request = inference._read_reviewed_evaluation_request(reference)
    assert asdict(loaded_reference) == reference and worker._parse_json(raw) == request == value
    assert "training_context" not in request
    assert not Path(value["output_directory"]).exists()
    assert not (tmp_path / "unread-artifact").exists()


@pytest.mark.parametrize("damage", ["missing-profile", "wrong-profile", "unhashable-profile", "rich-context",
    "legacy-v1-profile", "legacy-v2-profile", "v2-admission-pins", "lifecycle-pin", "rich-purpose", "training-operation"])
def test_reviewed_inference_mixed_v3_request_refuses_domain_and_context_swaps_before_execution(tmp_path, monkeypatch, damage):
    import builtins
    worker, consumer, value, write_request = _reviewed_mixed_request_data(tmp_path)
    if damage == "missing-profile": value.pop("admission_profile")
    elif damage == "wrong-profile": value["admission_profile"] = "complete-reviewed-norm-admission/v2"
    elif damage == "unhashable-profile": value["admission_profile"] = []
    elif damage == "rich-context": value["training_context"] = {}
    elif damage == "legacy-v1-profile": value["schema"] = "reviewed-source-evaluation-request/v1"
    elif damage == "legacy-v2-profile":
        value.update(schema="reviewed-source-evaluation-request/v2", training_context={})
    elif damage == "v2-admission-pins": value["source_sha256"] = worker._reviewed_decoder_source_pins()
    elif damage == "lifecycle-pin": value["lifecycle_source_sha256"][str(Path(inference.__file__).resolve())] = "0" * 64
    elif damage == "rich-purpose": value["heldout_evaluation_purpose"] = consumer.REVIEWED_V3_HELDOUT_CONTEXT_PURPOSE
    elif damage == "training-operation": value["operation"] = "training"
    else: raise AssertionError(damage)
    original_import = builtins.__import__
    def no_model_import(name, *args, **kwargs):
        if name.split(".", 1)[0] in {"torch", "transformers", "tokenizers"}:
            pytest.fail("malformed V3 DATA reached a model import")
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", no_model_import)
    with pytest.raises(ValueError):
        inference._read_reviewed_evaluation_request(write_request())
    assert not Path(value["output_directory"]).exists()
    assert not (tmp_path / "unread-artifact").exists()


def test_reviewed_inference_mixed_v3_request_cannot_relabel_signed_v2_admission_before_model_load(
        reviewed_physical_owner, monkeypatch):
    facts = reviewed_physical_owner
    packet = _reviewed_physical_packet(facts)
    packet.payload.update(schema="reviewed-source-evaluation-request/v3",
        admission_profile=packet.worker.REVIEWED_MIXED_ADMISSION_PROFILE,
        source_sha256=packet.worker._reviewed_decoder_source_pins(
            admission_profile=packet.worker.REVIEWED_MIXED_ADMISSION_PROFILE))
    cli = _reviewed_physical_cli(monkeypatch)
    with pytest.raises((EOFError, RuntimeError),
            match="reviewed (child callback endpoint closed|evaluation child failed with exit 1)"):
        _reviewed_physical_run(cli, facts, packet)
    child_log = (facts.attempt / "reviewed-worker.log").read_text()
    assert "SourceSpanConsumerBindingError: reviewed admission replay failed: explicit complete reviewed declaration and provenance required" in child_log
    assert packet.calls["asset"] == 0
    assert not (facts.attempt / "outputs").exists()
    _reviewed_physical_assert_stopped(facts)
    assert facts.owner.to_dict()["status"] == "active"


def _reviewed_mixed_rich_request_data(tmp_path):
    worker, consumer, value, write_request = _reviewed_mixed_request_data(tmp_path)
    artifact = value["rows_artifact"]
    value.update(schema="reviewed-source-evaluation-request/v4",
        request_id="fictional:mixed-rich-data",
        heldout_evaluation_purpose=consumer.REVIEWED_V3_HELDOUT_CONTEXT_PURPOSE,
        lifecycle_source_sha256=inference._reviewed_evaluation_lifecycle_source_sha256(rich_context=True),
        training_context={"profile": consumer.REVIEWED_V3_HELDOUT_CONTEXT_PROFILE,
            "admission_inputs_sha256": "3" * 64, "context_inputs_sha256": "4" * 64,
            **{name: dict(artifact) for name in ("admission_transport_artifact", "rows_artifact",
                "exposure_artifact", "retrieval_rows_artifact")}})
    return worker, consumer, value, write_request


@pytest.mark.parametrize("damage", [None, "v2-purpose", "v2-context", "source-only-purpose", "missing-profile",
    "missing-context", "hparam", "same-admission", "unknown-context-field", "v2-schema", "v3-schema"])
def test_reviewed_inference_mixed_rich_v4_request_data_domains(tmp_path, monkeypatch, damage):
    import builtins
    worker, consumer, value, write_request = _reviewed_mixed_rich_request_data(tmp_path)
    if damage == "v2-purpose": value["heldout_evaluation_purpose"] = consumer.REVIEWED_HELDOUT_CONTEXT_PURPOSE
    elif damage == "v2-context": value["training_context"]["profile"] = consumer.REVIEWED_HELDOUT_CONTEXT_PROFILE
    elif damage == "source-only-purpose": value["heldout_evaluation_purpose"] = consumer.REVIEWED_HELDOUT_PURPOSE
    elif damage == "missing-profile": value.pop("admission_profile")
    elif damage == "missing-context": value.pop("training_context")
    elif damage == "hparam": value["operation"] = "hparam_selection"
    elif damage == "same-admission": value["training_context"]["admission_inputs_sha256"] = value["admission_inputs_sha256"]
    elif damage == "unknown-context-field": value["training_context"]["reference_target"] = {}
    elif damage == "v2-schema": value["schema"] = "reviewed-source-evaluation-request/v2"
    elif damage == "v3-schema": value["schema"] = "reviewed-source-evaluation-request/v3"
    elif damage is not None: raise AssertionError(damage)
    original_import = builtins.__import__
    def no_model_import(name, *args, **kwargs):
        if name.split(".", 1)[0] in {"torch", "transformers", "tokenizers"}:
            pytest.fail("mixed rich request DATA reached a model import")
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", no_model_import)
    reference = write_request()
    if damage is None:
        loaded, raw, request = inference._read_reviewed_evaluation_request(reference)
        assert asdict(loaded) == reference and worker._parse_json(raw) == request == value
    else:
        with pytest.raises(ValueError):
            inference._read_reviewed_evaluation_request(reference)
    assert not Path(value["output_directory"]).exists()
    assert not (tmp_path / "unread-artifact").exists()



def _qualified_actual_GTE_ranked_snapshot(reference):
    """Read only pinned DATA from an already closed original qualification."""
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_joint_retrieval as joint
    def load(ref):
        assert type(ref) is dict and set(ref)=={"path","bytes","sha256"}
        path=Path(ref["path"]);raw=path.read_bytes()
        assert path.is_file() and not path.is_symlink() and len(raw)==ref["bytes"] and hashlib.sha256(raw).hexdigest()==ref["sha256"], "qualified input bytes differ"
        return json.loads(raw)
    bundle=load(reference)
    assert bundle["schema"]=="qualified-actual-GTE-ranked-CLI-test-input/v1" and bundle["mode"]=="joint"
    qualification=load(bundle["qualification"])
    method=next(row for row in qualification["actual_methods"] if row["mode"]=="joint")
    assert method["receipt"]==bundle["producer_receipt"], "producer differs from qualified original"
    owner=next(row for row in qualification["original_owners"] if row["name"]=="legal-shorttag-joint-v03")
    assert owner["closeout"]==bundle["original_closeout"]
    close=load(bundle["original_closeout"]);custody=close["original_owner_custody"]
    assert close["source_closed"] and custody["returncode"]==0 and not custody["errors"]
    assert all(custody[key] for key in ("original_native_compute_closed","original_source_exit_lifecycle_closed","all_observed_identities_gone","storage_released_and_durable"))
    request=load(bundle["original_request"])
    assert bundle["original_request"]["sha256"]==close["request_sha256"]==owner["request_sha256"]
    report=load(bundle["producer_receipt"]);checkpoint=load(bundle["projection_checkpoint"])
    base=Path(bundle["producer_receipt"]["path"]).parent
    assert Path(bundle["projection_checkpoint"]["path"])==base/"actual-GTE-reviewed-joint-checkpoint.json"
    assert Path(bundle["encoder_operation"]["path"])==base/"actual-GTE-reviewed-joint-run.json"
    assert base.is_relative_to(Path(request["attempt_directory"]))
    operation=load(bundle["encoder_operation"]);independent=load(bundle["independent_readback"])
    assert independent["source_closed"] and independent["native_root_phase_closed"]
    assert independent["all_dispatched_record_and_receipt_commitments_match"] and independent["actual_GTE_bank_vectors_and_inputs_identical"]
    assert operation["actual_encoder_executed"] and operation["actual_masked_projection_update_executed"]
    arm=report["arms"]["joint"];sha=joint.checkpoint_digest(checkpoint)
    assert sha==method["projection_checkpoint_sha256"]==arm["ranking_provenance"]["checkpoint_sha256"], "canonical projection identity differs"
    assert operation["checkpoint"]["sha256"]==bundle["projection_checkpoint"]["sha256"], "serialized checkpoint identity differs"
    assert operation["checkpoint"]["path"]==bundle["projection_checkpoint"]["path"]
    assert arm["actual_forwards"]==3 and report["common_queries"]==3
    return dict(projection_checkpoint=checkpoint,producer_artifact=arm["producer"],ranking_provenance=arm["ranking_provenance"],
        actual_GTE_lineage=dict(bundle=reference,original_request_sha256=close["request_sha256"],producer_receipt=bundle["producer_receipt"],
            encoder_operation=bundle["encoder_operation"],projection_checkpoint=bundle["projection_checkpoint"],
            original_qualification=bundle["qualification"],original_custody_closed=True,encoder_reexecuted=False,
            statutory_or_quality_authority=False))


@pytest.fixture
def qualified_actual_GTE_ranked_input():
    import os
    raw=os.environ.get("IPFS_DATASETS_TEST_QUALIFIED_GTE_RANKED_INPUT")
    if raw is None:pytest.skip("explicit admitted qualified GTE input descriptor required; no encoder replay")
    reference=json.loads(raw)
    _qualified_actual_GTE_ranked_snapshot(reference)
    return reference


@pytest.mark.parametrize("damage",["producer-pin","checkpoint-pin","qualification-link"])
def test_reviewed_inference_actual_GTE_ranked_input_refuses_changed_provenance(tmp_path,qualified_actual_GTE_ranked_input,damage):
    from copy import deepcopy
    original=qualified_actual_GTE_ranked_input;bundle=json.loads(Path(original["path"]).read_bytes());bundle=deepcopy(bundle)
    if damage=="producer-pin":bundle["producer_receipt"]["sha256"]="0"*64
    elif damage=="checkpoint-pin":bundle["projection_checkpoint"]["sha256"]="0"*64
    else:bundle["original_closeout"]["sha256"]="0"*64
    raw=json.dumps(bundle,sort_keys=True,separators=(",",":")).encode();path=tmp_path/"damaged-bundle.json";path.write_bytes(raw)
    with pytest.raises(AssertionError):_qualified_actual_GTE_ranked_snapshot(dict(path=str(path),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest()))


def _reviewed_physical_mixed_rich_packet(facts, *, shared_context=False, context_transport="shared_json_v1", actual_GTE_bundle=None, runtime_profile=None, generation_policy=None, qualified_pretrained_pair=None):
    actual_pretrained = qualified_pretrained_pair is not None
    qwen2 = runtime_profile == "builtin-qwen2-bfloat16/v1"
    from copy import deepcopy
    from tests.unit.optimizers.logic_theorem_optimizer import test_legal_ir_evaluation_artifacts as evaluation
    from tests.unit.optimizers.logic_theorem_optimizer import test_autoencoder_training_worker as models
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consumer_binding as consumer
    _helper, options, _populations, _replays, components = evaluation._rich_v3_heldout_case()
    directory = facts.root / "signed-mixed-rich-fixture"
    directory.mkdir(mode=0o700)
    if actual_pretrained:
        assert qwen2 and shared_context and context_transport == "shared_json_v2" and actual_GTE_bundle is not None
        pair = qualified_pretrained_pair.pair
        assert pair["runtime_profile"] == runtime_profile and pair["pretrained_declaration"] and not pair["training_performed"]
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
        artifacts = {key: worker.CheckpointArtifact.from_dict(value) for key, value in pair["artifacts"].items()}
        snapshot = _qualified_actual_GTE_ranked_snapshot(actual_GTE_bundle)
        model = SimpleNamespace(backend=_reviewed_physical_tokenizer_only(facts, artifacts, lambda: True),
            options={**artifacts, "expected_backend_identity": pair["expected_backend_identity"]},
            preparation_receipt={"ranked_context_snapshot": snapshot, "upstream_import_and_restoration_closed": True,
                "current_preparation_child_created": False, "parent_model_or_optimizer_retained": False})
    else:
        model = _reviewed_physical_fixture_assets(facts, directory, "causal_lm" if runtime_profile else "encoder_decoder",
            max_sequence_tokens=8192 if generation_policy is not None else 4096,
            fixed_json_schema_subwords=True, fixed_typed_schema_subwords=True,
            **({"profiled_generation": True} if generation_policy is not None else {}),
            **({"local_model_profile": runtime_profile} if runtime_profile else {}),
            **({"ranked_context_snapshot_artifact": actual_GTE_bundle} if actual_GTE_bundle is not None
               else {"ranked_context_snapshot": True} if shared_context else {}))
    if shared_context:
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_structured_retrieval as structured
        snapshot = model.preparation_receipt["ranked_context_snapshot"]
        ranked = snapshot["producer_artifact"]["compiler_artifact"]["reviewed_source_span_producer_evaluation"]
        training = options["reviewed_training_context"]
        assert [row["id"] for row in ranked["producer_arguments"]] == [row["id"] for row in options["rows"]]
        for row, offered, query in zip(training["retrieval_rows"], ranked["producer_arguments"], options["rows"], strict=True):
            assert offered["id"] == query["id"] and offered["source_text"] == query["source_text"]
            examples = offered["context"]["retrieved"]
            assert len(examples) == 3 and {item["id"] for item in examples} == {item["id"] for item in _populations["train"]}
            for item in examples:
                original = next(unit for unit in _populations["train"] if unit["id"] == item["id"])
                assert item["content"]["canonical_ir"] == original["canonical_ir"]
                assert item["content"]["source_text"] == original["source_text"]
            row["retrieved_ids"] = [item["id"] for item in examples]
        payload = structured._consume_reviewed_contexts(**training,
            expected_query_rows_sha256=evaluation._producer_digest(training["query_rows"]),
            expected_retrieval_rows_sha256=evaluation._producer_digest(training["retrieval_rows"]),
            consumer=lambda value: value,
            heldout_evaluation=options["binding"].receipt()["heldout_evaluation"], _admission_version="v3")
        options["retrieved_examples"] = {row["id"]: [{"id": item["id"], "content": item}
            for item in row["examples"]] for row in payload["rows"]}
        assert options["retrieved_examples"] == {row["id"]:row["context"]["retrieved"] for row in ranked["producer_arguments"]}
    declaration = components["holdout"]["declaration"]
    contexts = {"profile": "reviewed-source-selection-context/v2",
        "selection_context": {"schema": "caller-known-interpretation-selection/v1",
            "interpretation_id": declaration["interpretation_id"], "selection_mode": "identifier_only"},
        "rows": [{"id": "reviewed:" + unit["unit_id"], "unit_id": unit["unit_id"],
            "governing_context": deepcopy(declaration["governing_context"]),
            "source_binding": {"source_version_cid": unit["source_version"]["record_cid"],
                "occurrence_cid": unit["occurrence"]["record_cid"], "document_revision": unit["document_revision"]}}
            for unit in declaration["units"]]}
    def provider():
        return {key: item if key == "binding" else deepcopy(item)
                for key, item in options["reviewed_training_context"].items()}
    def context_digest(value):
        digest = evaluation._producer_digest
        return digest({"schema": "reviewed-decoder-rich-context-inputs/v1",
            "profile": consumer.REVIEWED_V3_HELDOUT_CONTEXT_PROFILE,
            "binding_receipt_sha256": digest(value["binding"].receipt()),
            **{name + "_sha256": digest(value[name]) for name in
                ("training_rows", "split_manifest", "exposure_records", "query_rows", "retrieval_rows")},
            "admission_inputs_sha256": consumer.reviewed_admission_inputs_sha256(value["admission_inputs"])})
    fixture = SimpleNamespace(query_case=None, rows=options["rows"], options=options, contexts=contexts,
        runtime=SimpleNamespace(current_admission_provider=lambda: deepcopy(options["admission_inputs"])),
        model=model, provider=provider, context_digest=context_digest, actual_pretrained=actual_pretrained)
    packet = _reviewed_physical_packet(facts, rich_fixture=fixture, admission_version="v3",
        runtime_profile=runtime_profile, generation_policy=generation_policy)
    if generation_policy is not None:
        packet.payload["max_output_tokens"] = 3500
    if actual_pretrained:
        packet.payload.update(max_model_bytes=pair["max_model_bytes"], max_source_tokens=8192)
        assert packet.original_assets == {}
    if shared_context:
        packet.payload["training_context"]["transport"] = context_transport
        provenance = model.preparation_receipt["ranked_context_snapshot"]["ranking_provenance"]
        packet.payload["checkpoint_declarations"]["encoder"] = {
            "id": "fictional:actual-reviewed-joint-projection", "sha256": provenance["checkpoint_sha256"]}
        original_policy = packet.context_callbacks["context_policy_guard"]
        def shared_policy(policy):
            assert policy["schema"] == ("reviewed-decoder-rich-context-use-policy/v3" if qwen2 else "reviewed-decoder-rich-context-use-policy/v2")
            if qwen2:
                assert policy["context_budget_profile"] == generation_policy["context_budget_profile"]
            assert policy["context_transport"] == context_transport
            assert policy["shared_context_schema"] == ("reviewed-lossless-shared-context/v2"
                if context_transport == "shared_json_v2" else "reviewed-lossless-shared-context/v1")
            assert policy["max_expanded_context_bytes"] == 262144
            assert policy["max_context_bytes"] == 16384 and policy["max_context_tokens"] == (8192 if qwen2 else 4096)
            return original_policy(policy)
        packet.context_callbacks["context_policy_guard"] = shared_policy
    return packet, fixture


def _run_reviewed_inference_mixed_rich_v4_physical_original_owner(reviewed_physical_owner, monkeypatch, capsys, mode, shared_context, *, context_transport="shared_json_v1", actual_GTE_bundle=None, runtime_profile=None, generation_policy=None, qualified_pretrained_pair=None, typed_structure_profile=None):
    actual_pretrained = qualified_pretrained_pair is not None
    qwen2 = runtime_profile == "builtin-qwen2-bfloat16/v1"
    from copy import deepcopy
    from ipfs_datasets_py.logic.autoformal import training_cycle_inputs as inputs
    from tests.unit.optimizers.logic_theorem_optimizer import test_legal_ir_evaluation_artifacts as evaluation
    facts = reviewed_physical_owner
    cli = _reviewed_physical_cli(monkeypatch)
    packet, fixture = _reviewed_physical_mixed_rich_packet(facts, shared_context=shared_context, context_transport=context_transport,
        actual_GTE_bundle=actual_GTE_bundle, runtime_profile=runtime_profile, generation_policy=generation_policy,
        qualified_pretrained_pair=qualified_pretrained_pair)
    output = facts.attempt / "outputs"
    assert packet.payload["schema"] == ("reviewed-source-evaluation-request/v10" if qwen2 else "reviewed-source-evaluation-request/v8" if generation_policy is not None
        else "reviewed-source-evaluation-request/v6" if runtime_profile else "reviewed-source-evaluation-request/v4")
    assert packet.payload["training_context"]["admission_inputs_sha256"] != packet.payload["admission_inputs_sha256"]
    if mode == "policy-denied":
        denial = PermissionError("original parent denied mixed rich TRAIN context")
        def deny(policy):
            assert policy["context_profile"] == packet.payload["training_context"]["profile"]
            raise denial
        packet.context_callbacks["context_policy_guard"] = deny
        with pytest.raises(PermissionError) as caught:
            _reviewed_physical_run(cli, facts, packet)
        assert caught.value is denial and not output.exists()
    elif mode == "train-revoked-after-wait":
        original = packet.context_callbacks["current_training_admission_provider"]
        revoked = []
        def current_training():
            value = original()
            if (output / "cycle.json").exists():
                value["registry"]["keys"][0]["revoked_at_utc"] = "2026-01-01T00:00:00Z"
                revoked.append(True)
            return value
        packet.context_callbacks["current_training_admission_provider"] = current_training
        with pytest.raises(ValueError, match="TRAIN admission changed after child completion"):
            _reviewed_physical_run(cli, facts, packet)
        assert revoked and json.loads((output / "cycle.json").read_bytes())["completed"] is True
        assert not (output / "parent-cycle.json").exists()
    elif mode == "query-revoked-after-wait":
        revoked = []
        def current_query():
            value = packet.fresh_admission()
            if (output / "cycle.json").exists():
                value["registry"]["keys"][0]["revoked_at_utc"] = "2026-01-01T00:00:00Z"
                revoked.append(True)
            return value
        with pytest.raises(ValueError, match="original parent admission changed after child completion"):
            _reviewed_physical_run(cli, facts, packet, admission_provider=current_query)
        assert revoked and json.loads((output / "cycle.json").read_bytes())["completed"] is True
        assert not (output / "parent-cycle.json").exists()
    else:
        assert _reviewed_physical_run(cli, facts, packet,
            **({} if typed_structure_profile is None else {"typed_structure_profile":typed_structure_profile})) == 0
        report = json.loads(capsys.readouterr().out.splitlines()[-1])
        assert report["original_owner_reservation_id"] == facts.owner.reservation_id
        for key in ("parent_FINISH_acknowledged", "original_child_waited", "parent_current_admission_rechecked_after_wait",
                    "parent_current_training_admission_rechecked_after_wait", "parent_context_policy_rechecked_after_wait",
                    "parent_output_artifacts_rechecked_after_wait"):
            assert report[key] is True
        assert report["context_inputs_sha256"] == packet.payload["training_context"]["context_inputs_sha256"]
        assert report["training_executed"] is False and report["weight_publications"] == []
        assert report["resource_release_performed"] is False
        cycle = json.loads((output / "cycle.json").read_bytes())
        _assert_reviewed_output_artifacts(output, cycle, report)
        evaluated = json.loads((output / "evaluation.json").read_bytes())
        typed_audit = None
        if typed_structure_profile is not None:
            from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_semantic_metrics as structural
            _reviewed_physical_assert_stopped(facts)
            assert report["schema"] == "reviewed-source-evaluation-parent/v2"
            assert report["typed_structure_profile"] == typed_structure_profile
            assert report["parent_typed_structure_audit_after_wait"] and report["parent_current_admission_rechecked_after_audit"]
            descriptor=report["typed_structure_audit_artifact"];path=Path(descriptor["path"])
            assert descriptor == {"path":str(path),"bytes":path.stat().st_size,"sha256":_sha(path)}
            typed_audit=json.loads(path.read_bytes())
            assert typed_audit["request_sha256"] == cycle["request_sha256"]
            assert typed_audit["original_output_artifacts"] == cycle["output_artifacts"]
            assert typed_audit["report"]["denominator"] == typed_audit["report"]["canonical_reference_count"] == 3
            payload=evaluated["compiler_artifact"]["reviewed_source_span_producer_evaluation"]
            assert typed_audit["report"] == structural.evaluate_complete_norm_typed_structure([
                dict(case_id=r["id"],reference=r["canonical_ir"],candidate=o["candidate"],outcome=o["outcome"])
                for r,o in zip(fixture.rows,payload["producer_outputs"],strict=True)])
            assert not any(typed_audit[k]for k in ("native_proof_verified","legal_meaning_verified","current_admission_authority_granted","model_reexecuted"))
            _assert_reviewed_output_artifacts(output,cycle,report)
        else:
            assert report["schema"] == "reviewed-source-evaluation-parent/v1"
            assert "typed_structure_audit_artifact" not in report

        metrics = evaluated["metrics"]["complete_norm_payload"]
        assert metrics["denominator"] == 3
        if not actual_pretrained: assert metrics["outcome_counts"]["abstained"] == 3
        loader = json.loads((output / "loader.json").read_bytes())
        assert loader["checkpoint_restored"] is loader["matched_pair"] is True
        if runtime_profile is not None:
            assert loader["runtime_profile"] == runtime_profile and loader["dtype"] == "bfloat16"
            assert loader["deterministic_buffer_dtype"] == "float32"
        generation = json.loads((output / "generation.json").read_bytes())
        assert generation["context"]["heldout_context_supported"] is True
        if generation_policy is not None:
            assert generation["schema"] == ("reviewed-decoder-source-producer-observation/v4" if qwen2 else "reviewed-decoder-source-producer-observation/v3")
            commitment = generation["input_commitment"]
            assert commitment["generation_policy"] == generation_policy
            if qwen2:
                assert commitment["runtime_profile"] == runtime_profile
            assert generation["input_profile_id"] == ("reviewed-decoder-qwen2-profiled-producer/v1:" if qwen2 else "reviewed-decoder-profiled-producer/v1:") + evaluation._producer_digest(commitment)
        if actual_GTE_bundle is not None:
            snapshot = fixture.model.preparation_receipt["ranked_context_snapshot"]
            assert snapshot["actual_GTE_lineage"]["bundle"] == actual_GTE_bundle
            assert snapshot["actual_GTE_lineage"]["original_custody_closed"] is True
            assert snapshot["actual_GTE_lineage"]["encoder_reexecuted"] is False
            assert snapshot["ranking_provenance"]["checkpoint_sha256"] == packet.payload["checkpoint_declarations"]["encoder"]["sha256"]
        call = generation["last_call"]
        assert call["entry_pair_match"] is call["exit_pair_match"] is True
        if actual_pretrained:
            assert len(call["raw_generation_outputs"]) == 3
            assert all(len(row["generated_token_ids"]) >= 2 and row["generated_token_ids"][0] == 151643 for row in call["raw_generation_outputs"])
        else:
            assert all(row["outcome"] == "abstained" and row["generated_token_ids"] == ([0, 2] if qwen2 else [1, 2] if generation_policy is not None else [257, 0])
                       for row in call["raw_generation_outputs"])
        source_arguments = [{"id": row["id"], "source_text": row["source_text"], "context": {"permitted": [],
            "retrieved": deepcopy(fixture.options["retrieved_examples"][row["id"]])}} for row in fixture.rows]
        digest = evaluation._producer_digest
        expected = inputs.prepare_reviewed_decoder_context_generation_inputs(source_arguments,
            source_contexts=fixture.contexts, expected_source_contexts_sha256=digest(fixture.contexts),
            expected_context_records_sha256=digest([{key: row[key] for key in ("id", "context")} for row in source_arguments]),
            tokenizer=fixture.model.backend.tokenizer, max_source_tokens=8192 if actual_pretrained else 4096,
            **({"context_budget_profile": generation_policy["context_budget_profile"]} if qwen2 else {}),
            **({"context_transport": context_transport} if shared_context else {}))
        if shared_context:
            assert expected["receipt"]["context_transport"] == context_transport
            ranking = fixture.model.preparation_receipt["ranked_context_snapshot"]
            encoder = evaluated["compiler_artifact"]["reviewed_source_span_producer_evaluation"]["configuration"]["checkpoint_declarations"]["encoder"]
            assert encoder["sha256"] == ranking["ranking_provenance"]["checkpoint_sha256"]
            assert generation["input_commitment"]["context_transport"] == context_transport
            assert all(3 <= len(item["source_token_ids"]) <= (8192 if actual_pretrained else 4096) for item in expected["records"])
            for record, original in zip(expected["records"], source_arguments, strict=True):
                encoded = json.loads(record["source_wire"])
                unpack = (inputs.unpack_reviewed_context_json_v2 if context_transport == "shared_json_v2"
                          else inputs.unpack_reviewed_context_json_v1)
                assert unpack(encoded["context"]) == original["context"]
                assert len(original["context"]["retrieved"]) == 3
        assert call["source_arguments_sha256"] == digest(source_arguments)
        assert call["source_records_sha256"] == digest(expected["records"])
        assert call["input_receipt"] == expected["receipt"]
        if generation_policy is not None:
            from tests.unit.optimizers.logic_theorem_optimizer import test_autoencoder_training_worker as models
            frontend = fixture.model.backend.tokenizer.tokenizer
            capacity = []
            for record, reference in zip(expected["records"], fixture.rows, strict=True):
                assert record["id"] == reference["id"]
                framed = models._reviewed_chatml_native_test_frame(frontend, record["source_wire"],
                    public_layouts=qwen2 and generation_policy["conditioning_profile"] == "qwen2-chatml-field-layouts/v1")
                assert len(framed) + packet.payload["max_output_tokens"] - 1 <= (32768 if actual_pretrained else 8192)
                # Reference tokenization happens only here, after the genuine
                # child exit. These bytes never enter its generation inputs.
                target_wire = inputs._reviewed_wire(reference["canonical_ir"]).decode("utf-8")
                target_ids = frontend.backend_tokenizer.encode(target_wire, add_special_tokens=False).ids
                assert frontend.backend_tokenizer.decode(target_ids, skip_special_tokens=False) == target_wire
                assert len(target_ids) + 2 <= packet.payload["max_output_tokens"]
                capacity.append({"id": record["id"], "source_tokens": len(record["source_token_ids"]),
                    "full_reference_target_tokens": len(target_ids) + 2,
                    "full_reference_target_sha256": hashlib.sha256(target_wire.encode()).hexdigest(),
                    "native_chatml_frame_tokens": len(framed), "full_output_ceiling": packet.payload["max_output_tokens"],
                    "reserved_positions": len(framed) + packet.payload["max_output_tokens"] - 1})
            (facts.root / "profiled-rich-capacity.json").write_text(json.dumps({"schema": "profiled-rich-fixture-capacity/v1",
                "rows": capacity, "model_positions": 32768 if actual_pretrained else 8192, "source_budget": 8192 if actual_pretrained else 4096, "context_budget": 8192 if qwen2 else 4096,
                "all_three_complete_TRAIN_examples_preserved": True, "actual_pretrained_tokenizer": actual_pretrained}, indent=2) + "\n")
        if actual_pretrained:
            (facts.root / "actual-pretrained-rich-source-records.json").write_bytes(inputs._reviewed_wire(expected["records"]))
            (facts.root / "actual-pretrained-rich-CLI-result.json").write_text(json.dumps({
                "schema": "actual-pretrained-rich-parent-CLI-observation/v1", "prepared_pair": qualified_pretrained_pair.bundle["prepared_pair"],
                "actual_GTE_lineage": fixture.model.preparation_receipt["ranked_context_snapshot"]["actual_GTE_lineage"],
                "runtime_profile": runtime_profile, "generation_policy": generation_policy, "outputs": call["raw_generation_outputs"],
                "metrics": evaluated["metrics"], "all_three_complete_TRAIN_examples_per_query": True,
                **({} if typed_audit is None else {"original_parent_typed_structure_audit_artifact":report["typed_structure_audit_artifact"],
                    "original_parent_typed_structure_audit_report":typed_audit["report"]}),
                "parent_FINISH_wait_query_TRAIN_policy_output_checks": True, "paired_state_restored": True,
                "actual_parameters_imported": qualified_pretrained_pair.pair["parameters_imported"], "training_performed": False,
                "legal_meaning_verified": False, "fair_A_to_F_comparison": False}, indent=2) + "\n")
    for name, artifact in packet.payload["assets"].items():
        if actual_pretrained:
            digest = hashlib.sha256()
            with Path(artifact["path"]).open("rb") as stream:
                while chunk := stream.read(1024**2): digest.update(chunk)
            assert digest.hexdigest() == artifact["sha256"]
        else:
            assert Path(artifact["path"]).read_bytes() == packet.original_assets[name]
    _reviewed_physical_assert_stopped(facts)
    _reviewed_physical_fsync_tree(facts.root)
    result = facts.owner.finalize(facts.attempt, artifacts_durable=True)
    assert result["status"] == "released"


@pytest.mark.parametrize("shared_context", [False, True])
@pytest.mark.parametrize("mode", ["healthy", "train-revoked-after-wait", "policy-denied"])
def test_reviewed_inference_mixed_rich_v4_physical_original_owner(reviewed_physical_owner, monkeypatch, capsys, mode, shared_context):
    _run_reviewed_inference_mixed_rich_v4_physical_original_owner(
        reviewed_physical_owner, monkeypatch, capsys, mode, shared_context)


@pytest.mark.parametrize("mode", ["healthy", "train-revoked-after-wait", "policy-denied"])
def test_reviewed_inference_shorttag_v2_physical_original_owner(reviewed_physical_owner, monkeypatch, capsys, mode):
    _run_reviewed_inference_mixed_rich_v4_physical_original_owner(
        reviewed_physical_owner, monkeypatch, capsys, mode, True, context_transport="shared_json_v2")


@pytest.mark.parametrize("damage",[None,"unknown-transport","plain-as-opt-in","v2-domain","extra-field"])
def test_reviewed_inference_shared_rich_transport_request_data(tmp_path,monkeypatch,damage):
    import builtins
    worker,consumer,value,write_request=_reviewed_mixed_rich_request_data(tmp_path)
    value["training_context"]["transport"]="shared_json_v1"
    if damage=="unknown-transport":value["training_context"]["transport"]="unknown"
    elif damage=="plain-as-opt-in":value["training_context"]["transport"]="plain_json_v1"
    elif damage=="v2-domain":
        value["schema"]="reviewed-source-evaluation-request/v2"
        value.pop("admission_profile")
        value["heldout_evaluation_purpose"]=consumer.REVIEWED_HELDOUT_CONTEXT_PURPOSE
        value["training_context"]["profile"]=consumer.REVIEWED_HELDOUT_CONTEXT_PROFILE
    elif damage=="extra-field":value["training_context"]["authorize_expansion"]=True
    original_import=builtins.__import__
    def no_model_import(name,*args,**kwargs):
        if name.split(".",1)[0] in {"torch","transformers","tokenizers"}:pytest.fail("shared request DATA imported model")
        return original_import(name,*args,**kwargs)
    monkeypatch.setattr(builtins,"__import__",no_model_import)
    reference=write_request()
    if damage is None:
        loaded,raw,request=inference._read_reviewed_evaluation_request(reference)
        assert asdict(loaded)==reference and request==value==worker._parse_json(raw)
    else:
        with pytest.raises(ValueError):inference._read_reviewed_evaluation_request(reference)
    assert not Path(value["output_directory"]).exists()


@pytest.mark.parametrize("damage",[None,"transport-downgrade","schema-downgrade","expanded-budget","wire-budget","token-budget","codec-schema","implicit-upgrade"])
def test_reviewed_inference_shared_context_policy_binds_request_and_budgets(damage):
    from ipfs_datasets_py.logic.autoformal import training_cycle_inputs as inputs
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
    context={"transport":"shared_json_v1"}
    policy={"schema":"reviewed-decoder-rich-context-use-policy/v2","context_transport":"shared_json_v1",
        "shared_context_schema":inputs.REVIEWED_SHARED_CONTEXT_JSON_SCHEMA,
        "max_expanded_context_bytes":inputs.REVIEWED_SHARED_CONTEXT_MAX_EXPANDED_BYTES,
        "max_context_bytes":worker.REVIEWED_GENERATION_CONTEXT_MAX_BYTES,
        "max_context_tokens":worker.REVIEWED_GENERATION_CONTEXT_MAX_TOKENS}
    if damage=="transport-downgrade":policy["context_transport"]="plain_json_v1"
    elif damage=="schema-downgrade":policy["schema"]="reviewed-decoder-rich-context-use-policy/v1"
    elif damage=="expanded-budget":policy["max_expanded_context_bytes"]+=1
    elif damage=="wire-budget":policy["max_context_bytes"]+=1
    elif damage=="token-budget":policy["max_context_tokens"]+=1
    elif damage=="codec-schema":policy["shared_context_schema"]="unknown"
    elif damage=="implicit-upgrade":context={}
    if damage is None:
        assert inference._check_reviewed_context_transport_policy(context,policy) is None
        assert inference._check_reviewed_context_transport_policy({}, {"schema":"reviewed-decoder-rich-context-use-policy/v1"}) is None
    else:
        with pytest.raises(ValueError):inference._check_reviewed_context_transport_policy(context,policy)


@pytest.mark.parametrize("damage",[None,"v1-codec","v1-transport","boolean-budget","expanded-budget","implicit-upgrade"])
def test_reviewed_inference_shorttag_request_and_policy_keep_explicit_version_and_limits(tmp_path,damage):
    from ipfs_datasets_py.logic.autoformal import training_cycle_inputs as inputs
    worker,consumer,value,write_request=_reviewed_mixed_rich_request_data(tmp_path)
    value["training_context"]["transport"]="shared_json_v2"
    _,_,loaded=inference._read_reviewed_evaluation_request(write_request())
    assert loaded["training_context"]["transport"]=="shared_json_v2"
    context={"transport":"shared_json_v2"}
    policy={"schema":"reviewed-decoder-rich-context-use-policy/v2","context_transport":"shared_json_v2",
        "shared_context_schema":inputs.REVIEWED_SHARED_CONTEXT_JSON_SCHEMA_V2,
        "max_expanded_context_bytes":inputs.REVIEWED_SHARED_CONTEXT_MAX_EXPANDED_BYTES,
        "max_context_bytes":worker.REVIEWED_GENERATION_CONTEXT_MAX_BYTES,
        "max_context_tokens":worker.REVIEWED_GENERATION_CONTEXT_MAX_TOKENS}
    if damage=="v1-codec":policy["shared_context_schema"]=inputs.REVIEWED_SHARED_CONTEXT_JSON_SCHEMA
    elif damage=="v1-transport":policy["context_transport"]="shared_json_v1"
    elif damage=="boolean-budget":policy["max_context_tokens"]=True
    elif damage=="expanded-budget":policy["max_expanded_context_bytes"]+=1
    elif damage=="implicit-upgrade":context={}
    if damage is None:assert inference._check_reviewed_context_transport_policy(context,policy) is None
    else:
        with pytest.raises(ValueError):inference._check_reviewed_context_transport_policy(context,policy)


def test_reviewed_inference_actual_GTE_ranked_context_physical_original_owner(reviewed_physical_owner, monkeypatch, capsys, qualified_actual_GTE_ranked_input):
    _run_reviewed_inference_mixed_rich_v4_physical_original_owner(reviewed_physical_owner, monkeypatch, capsys,
        "healthy", True, context_transport="shared_json_v2", actual_GTE_bundle=qualified_actual_GTE_ranked_input)


@pytest.mark.parametrize("rich", [False, True])
@pytest.mark.parametrize("damage", [None, "missing", "unknown", "legacy-profile", "boolean", "old-schema", "domain-swap"])
def test_reviewed_inference_BF16_request_data_is_explicit_and_closed(tmp_path, monkeypatch, rich, damage):
    import builtins
    worker, consumer, value, write_request = (_reviewed_mixed_rich_request_data(tmp_path) if rich else _reviewed_mixed_request_data(tmp_path))
    value.update(schema="reviewed-source-evaluation-request/v6" if rich else "reviewed-source-evaluation-request/v5",
                 runtime_profile="builtin-llama-bfloat16/v1")
    if rich:
        value["training_context"]["transport"] = "shared_json_v2"
    if damage == "missing":
        value.pop("runtime_profile")
    elif damage == "unknown":
        value["runtime_profile"] = "unapproved:runtime"
    elif damage == "legacy-profile":
        value["runtime_profile"] = "builtin-t5-gpt2-float32/v1"
    elif damage == "boolean":
        value["runtime_profile"] = True
    elif damage == "old-schema":
        value["schema"] = "reviewed-source-evaluation-request/v4" if rich else "reviewed-source-evaluation-request/v3"
    elif damage == "domain-swap":
        value["admission_profile"] = "complete-reviewed-norm-admission/v2"
    original_import = builtins.__import__
    def no_model_import(name, *args, **kwargs):
        if name.split(".", 1)[0] in {"torch", "transformers", "tokenizers"}:
            pytest.fail("BF16 request DATA imported a model package")
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", no_model_import)
    if damage is None:
        reference, raw, loaded = inference._read_reviewed_evaluation_request(write_request())
        assert loaded == value and loaded["runtime_profile"] == "builtin-llama-bfloat16/v1"
    else:
        with pytest.raises(ValueError):
            inference._read_reviewed_evaluation_request(write_request())
    assert not Path(value["output_directory"]).exists()


def test_reviewed_inference_BF16_source_only_physical_original_owner(reviewed_physical_owner, monkeypatch, capsys):
    from ipfs_datasets_py.logic.autoformal import training_cycle_inputs as inputs
    facts = reviewed_physical_owner
    packet = _reviewed_physical_packet(facts, admission_version="v3", runtime_profile="builtin-llama-bfloat16/v1")
    cli = _reviewed_physical_cli(monkeypatch)
    assert packet.payload["schema"] == "reviewed-source-evaluation-request/v5"
    assert _reviewed_physical_run(cli, facts, packet) == 0
    report = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert report["original_owner_reservation_id"] == facts.owner.reservation_id
    assert all(report[key] for key in ("parent_FINISH_acknowledged", "original_child_waited", "parent_current_admission_rechecked_after_wait", "parent_output_artifacts_rechecked_after_wait"))
    assert not report["training_executed"] and report["weight_publications"] == [] and not report["resource_release_performed"]
    output = facts.attempt / "outputs"
    cycle = json.loads((output / "cycle.json").read_bytes())
    _assert_reviewed_output_artifacts(output, cycle, report)
    loader = json.loads((output / "loader.json").read_bytes())
    assert loader["runtime_profile"] == "builtin-llama-bfloat16/v1" and loader["dtype"] == "bfloat16"
    assert loader["checkpoint_restored"] and loader["matched_pair"] and loader["deterministic_buffer_dtype"] == "float32"
    evaluated = json.loads((output / "evaluation.json").read_bytes())
    assert evaluated["metrics"]["complete_norm_payload"]["denominator"] == evaluated["metrics"]["complete_norm_payload"]["outcome_counts"]["abstained"] == 3
    payload = evaluated["compiler_artifact"]["reviewed_source_span_producer_evaluation"]
    generation = json.loads((output / "generation.json").read_bytes())["last_call"]
    assert generation["completed"] and generation["entry_pair_match"] and generation["exit_pair_match"]
    assert all(row["generated_token_ids"] == [257, 0] and row["outcome"] == "abstained" for row in generation["raw_generation_outputs"])
    contexts = json.loads(Path(packet.payload["source_contexts_artifact"]["path"]).read_bytes())
    digest = lambda value: hashlib.sha256(inputs._reviewed_wire(value)).hexdigest()
    prepared = inputs.prepare_reviewed_decoder_generation_inputs(payload["producer_arguments"], source_contexts=contexts,
        expected_source_contexts_sha256=digest(contexts), tokenizer=packet.fixture.backend.tokenizer, max_source_tokens=4096)
    assert generation["source_records_sha256"] == digest(prepared["records"]) and generation["input_receipt"] == prepared["receipt"]
    for name, artifact in packet.payload["assets"].items():
        assert Path(artifact["path"]).read_bytes() == packet.original_assets[name]
    _reviewed_physical_assert_stopped(facts)
    _reviewed_physical_fsync_tree(facts.root)
    assert facts.owner.finalize(facts.attempt, artifacts_durable=True)["status"] == "released"


@pytest.mark.parametrize("mode", ["healthy", "train-revoked-after-wait", "policy-denied"])
def test_reviewed_inference_BF16_rich_physical_original_owner(reviewed_physical_owner, monkeypatch, capsys, mode):
    _run_reviewed_inference_mixed_rich_v4_physical_original_owner(reviewed_physical_owner, monkeypatch, capsys,
        mode, True, context_transport="shared_json_v2", runtime_profile="builtin-llama-bfloat16/v1")



def _reviewed_profiled_request_data(tmp_path,rich=False):
    worker,consumer,value,write=(_reviewed_mixed_rich_request_data(tmp_path) if rich else _reviewed_mixed_request_data(tmp_path))
    value.update(schema='reviewed-source-evaluation-request/v8' if rich else 'reviewed-source-evaluation-request/v7',runtime_profile='builtin-llama-bfloat16/v1',
        generation_policy={'schema':'reviewed-decoder-generation-policy/v1','generation_profile':'builtin-llama-dynamic-kv/v1',
            'conditioning_profile':'chatml-complete-legal-ir/v1','max_generation_seconds':1.0})
    if rich:value['training_context']['transport']='shared_json_v2'
    return worker,consumer,value,write


@pytest.mark.parametrize('rich',[False,True])
@pytest.mark.parametrize('damage',[None,'missing','generation','conditioning','budget_missing','zero','bool','overflow','extra','downgrade','runtime','domain'])
def test_reviewed_inference_profiled_generation_request_is_closed_data(tmp_path,monkeypatch,rich,damage):
    import builtins
    worker,consumer,value,write=_reviewed_profiled_request_data(tmp_path,rich)
    if damage=='missing':value.pop('generation_policy')
    elif damage=='generation':value['generation_policy']['generation_profile']='unknown'
    elif damage=='conditioning':value['generation_policy']['conditioning_profile']=[]
    elif damage=='budget_missing':value['generation_policy'].pop('max_generation_seconds')
    elif damage=='zero':value['generation_policy']['max_generation_seconds']=0
    elif damage=='bool':value['generation_policy']['max_generation_seconds']=True
    elif damage=='overflow':value['generation_policy']['max_generation_seconds']=10**1000
    elif damage=='extra':value['generation_policy']['target_json']='forbidden'
    elif damage=='downgrade':value['schema']='reviewed-source-evaluation-request/v6' if rich else 'reviewed-source-evaluation-request/v5'
    elif damage=='runtime':value['runtime_profile']='builtin-t5-gpt2-float32/v1'
    elif damage=='domain':value['admission_profile']='complete-reviewed-norm-admission/v2'
    original=builtins.__import__
    def no_native(name,*args,**kwargs):
        if name.split('.',1)[0] in ('torch','transformers','tokenizers'):pytest.fail('request DATA imported native code')
        return original(name,*args,**kwargs)
    monkeypatch.setattr(builtins,'__import__',no_native)
    if damage is None:
        _,_,loaded=inference._read_reviewed_evaluation_request(write());assert loaded==value
    else:
        with pytest.raises(ValueError):inference._read_reviewed_evaluation_request(write())
    assert not Path(value['output_directory']).exists()


def _reviewed_profiled_parent_policy_data(tmp_path,kind):
    worker,consumer,request,_=_reviewed_profiled_request_data(tmp_path)
    context={'fixture':'independently supplied source context'};path=tmp_path/'contexts.json';path.write_bytes(worker._json_bytes(context))
    request['source_contexts_artifact']={'path':str(path),'sha256':_sha(path),'bytes':path.stat().st_size}
    if kind=='load':
        policy={'schema':'reviewed-local-decoder-load-policy/v2','backend_identity':request['backend_identity'],
            'assets':[request['assets'][k] for k in ('recipe_artifact','model_config_artifact','tokenizer_artifact','license_artifact','model_checkpoint','optimizer_checkpoint')],
            'producer_pins':request['source_sha256'],'admission_inputs_sha256':request['admission_inputs_sha256'],
            'max_model_bytes':request['max_model_bytes'],'device':'cpu','dtype':'bfloat16','load_requested':True,'restore_requested':True,
            'training_requested':False,'downloads_requested':False,'resource_grant_requested':False,
            'runtime_profile':request['runtime_profile'],'admission_profile':request['admission_profile']}
    else:
        policy={'schema':'reviewed-decoder-source-producer-policy/v3','backend_identity':request['backend_identity'],
            'assets':[request['assets'][k] for k in ('recipe_artifact','model_config_artifact','tokenizer_artifact','license_artifact')],
            'model_checkpoint':request['assets']['model_checkpoint'],'optimizer_checkpoint':request['assets']['optimizer_checkpoint'],
            'source_contexts_sha256':worker._digest(worker._json_bytes(context)),'admission_inputs_sha256':request['admission_inputs_sha256'],
            'max_source_tokens':request['max_source_tokens'],'max_output_tokens':request['max_output_tokens'],'operation':request['operation'],
            'training_requested':False,'restore_requested':False,'admission_profile':request['admission_profile'],
            'generation_policy':json.loads(worker._json_bytes(request['generation_policy']))}
    return worker,request,policy


@pytest.mark.parametrize('kind',['load','producer'])
@pytest.mark.parametrize('damage',[None,'schema','policy','limit','extra','backend'])
def test_reviewed_inference_profiled_generation_original_parent_policy_matches_request(tmp_path,kind,damage):
    worker,request,policy=_reviewed_profiled_parent_policy_data(tmp_path,kind)
    if damage=='schema':policy['schema']='reviewed-decoder-source-producer-policy/v2'
    elif damage=='policy':
        if kind=='load':policy['runtime_profile']='unknown'
        else:policy['generation_policy']['max_generation_seconds']=2.0
    elif damage=='limit':policy['max_model_bytes' if kind=='load' else 'max_output_tokens']+=1
    elif damage=='extra':policy['decoder_input_ids']=[1]
    elif damage=='backend':policy['backend_identity']={'unbound':True}
    if damage is None:assert inference._check_reviewed_generation_policy(request,policy) is None
    else:
        with pytest.raises(ValueError):inference._check_reviewed_generation_policy(request,policy)


@pytest.mark.parametrize('damage',[None,'generation','profile_id','schema'])
def test_reviewed_inference_profiled_generation_output_commitment_checked_after_bytes(tmp_path,damage):
    worker,request,policy=_reviewed_profiled_parent_policy_data(tmp_path,'producer');output=Path(request['output_directory']);output.mkdir()
    commitment={**policy,'source_sha256':request['source_sha256'],'fixture':'opaque evaluator joins stay separate'}
    generation={'schema':'reviewed-decoder-source-producer-observation/v3','input_commitment':commitment,
        'input_profile_id':'reviewed-decoder-profiled-producer/v1:'+worker._digest(worker._json_bytes(commitment))}
    if damage=='generation':generation['input_commitment']['generation_policy']['max_generation_seconds']=2.0
    elif damage=='profile_id':generation['input_profile_id']='reviewed-decoder-profiled-producer/v1:'+'f'*64
    elif damage=='schema':generation['schema']='reviewed-decoder-source-producer-observation/v2'
    descriptors={};paths={}
    for name,value in (('evaluation',{}),('loader',{}),('generation',generation)):
        path=output/(name+'.json');path.write_bytes(worker._json_bytes(value));paths[name]=str(path);descriptors[name]={'path':str(path),'sha256':_sha(path),'bytes':path.stat().st_size}
    cycle={'output_artifacts':descriptors,'inference':{'profile':request['schema'],**paths}}
    if damage is None:inference._check_reviewed_evaluation_outputs(cycle,request)
    else:
        with pytest.raises(ValueError):inference._check_reviewed_evaluation_outputs(cycle,request)



def _run_reviewed_inference_profiled_generation_physical_original_owner(
        reviewed_physical_owner, monkeypatch, capsys, mode, *, runtime_profile):
    facts = reviewed_physical_owner
    qwen2 = runtime_profile == "builtin-qwen2-bfloat16/v1"
    assert runtime_profile in {"builtin-llama-bfloat16/v1", "builtin-qwen2-bfloat16/v1"}
    policy = {"schema": "reviewed-decoder-generation-policy/v1",
        "generation_profile": "builtin-llama-dynamic-kv/v1",
        "conditioning_profile": "chatml-complete-legal-ir/v1", "max_generation_seconds": 30.0}
    if qwen2:
        policy.update(schema="reviewed-decoder-generation-policy/v2",
            generation_profile="builtin-qwen2-dynamic-kv/v1",
            conditioning_profile="qwen2-chatml-complete-legal-ir/v1",
            context_budget_profile="qwen2-full-context-8192/v1")
    packet = _reviewed_physical_packet(facts, admission_version="v3",
        runtime_profile=runtime_profile, generation_policy=policy)
    assert packet.payload["schema"] == ("reviewed-source-evaluation-request/v9" if qwen2 else "reviewed-source-evaluation-request/v7")
    cli = _reviewed_physical_cli(monkeypatch)
    output = facts.attempt / "outputs"
    if mode == "policy-denied":
        denial = PermissionError("original parent denied profiled generation")
        def deny(value):
            packet.asset_policy(value)
            if value["schema"] == ("reviewed-decoder-source-producer-policy/v4" if qwen2 else "reviewed-decoder-source-producer-policy/v3"):
                raise denial
        with pytest.raises(PermissionError) as caught:
            _reviewed_physical_run(cli, facts, packet, asset_policy=deny)
        assert caught.value is denial and not output.exists()
    elif mode == "query-revoked-after-wait":
        revoked = []
        def current():
            value = packet.fresh_admission()
            if (output / "cycle.json").exists():
                value["registry"]["keys"][0]["revoked_at_utc"] = "2026-01-01T00:00:00Z"
                revoked.append(True)
            return value
        with pytest.raises(ValueError, match="original parent admission changed after child completion"):
            _reviewed_physical_run(cli, facts, packet, admission_provider=current)
        assert revoked and json.loads((output / "cycle.json").read_bytes())["completed"] is True
        assert not (output / "parent-cycle.json").exists()
    else:
        from ipfs_datasets_py.logic.autoformal import training_cycle_inputs as inputs
        assert _reviewed_physical_run(cli, facts, packet) == 0
        report = json.loads(capsys.readouterr().out.splitlines()[-1])
        assert report["original_owner_reservation_id"] == facts.owner.reservation_id
        assert all(report[key] for key in ("parent_FINISH_acknowledged", "original_child_waited",
            "parent_current_admission_rechecked_after_wait", "parent_output_artifacts_rechecked_after_wait"))
        assert not report["training_executed"] and report["weight_publications"] == []
        assert not report["resource_release_performed"]
        cycle = json.loads((output / "cycle.json").read_bytes())
        _assert_reviewed_output_artifacts(output, cycle, report)
        loader = json.loads((output / "loader.json").read_bytes())
        assert loader["runtime_profile"] == runtime_profile and loader["dtype"] == "bfloat16"
        assert loader["checkpoint_restored"] and loader["matched_pair"]
        observation = json.loads((output / "generation.json").read_bytes())
        assert observation["schema"] == ("reviewed-decoder-source-producer-observation/v4" if qwen2 else "reviewed-decoder-source-producer-observation/v3")
        commitment = observation["input_commitment"]
        assert commitment["generation_policy"] == policy
        digest = lambda value: hashlib.sha256(inputs._reviewed_wire(value)).hexdigest()
        assert observation["input_profile_id"] == ("reviewed-decoder-qwen2-profiled-producer/v1:" if qwen2 else "reviewed-decoder-profiled-producer/v1:") + digest(commitment)
        generation = observation["last_call"]
        assert generation["completed"] and generation["entry_pair_match"] and generation["exit_pair_match"]
        assert all(row["generated_token_ids"] == ([0, 2] if qwen2 else [1, 2]) and row["outcome"] == "abstained"
            for row in generation["raw_generation_outputs"])
        evaluated = json.loads((output / "evaluation.json").read_bytes())
        metrics = evaluated["metrics"]["complete_norm_payload"]
        assert metrics["denominator"] == metrics["outcome_counts"]["abstained"] == 3
        payload = evaluated["compiler_artifact"]["reviewed_source_span_producer_evaluation"]
        contexts = json.loads(Path(packet.payload["source_contexts_artifact"]["path"]).read_bytes())
        prepared = inputs.prepare_reviewed_decoder_generation_inputs(payload["producer_arguments"],
            source_contexts=contexts, expected_source_contexts_sha256=digest(contexts),
            tokenizer=packet.fixture.backend.tokenizer, max_source_tokens=4096)
        assert generation["source_records_sha256"] == digest(prepared["records"])
        assert generation["input_receipt"] == prepared["receipt"]
    assert packet.fixture.preparation_receipt["genuine_communicate_completed"] is True
    assert packet.fixture.preparation_receipt["parent_model_or_optimizer_retained"] is False
    for name, artifact in packet.payload["assets"].items():
        assert Path(artifact["path"]).read_bytes() == packet.original_assets[name]
    _reviewed_physical_assert_stopped(facts)
    _reviewed_physical_fsync_tree(facts.root)
    assert facts.owner.finalize(facts.attempt, artifacts_durable=True)["status"] == "released"


@pytest.mark.parametrize("mode", ["healthy", "policy-denied", "query-revoked-after-wait"])
def test_reviewed_inference_profiled_generation_physical_original_owner(
        reviewed_physical_owner, monkeypatch, capsys, mode):
    _run_reviewed_inference_profiled_generation_physical_original_owner(
        reviewed_physical_owner, monkeypatch, capsys, mode,
        runtime_profile="builtin-llama-bfloat16/v1")


@pytest.mark.parametrize("mode", ["healthy", "policy-denied", "query-revoked-after-wait"])
def test_reviewed_inference_Qwen2_generation_physical_original_owner(
        reviewed_physical_owner, monkeypatch, capsys, mode):
    _run_reviewed_inference_profiled_generation_physical_original_owner(
        reviewed_physical_owner, monkeypatch, capsys, mode,
        runtime_profile="builtin-qwen2-bfloat16/v1")



@pytest.mark.parametrize("mode", ["healthy", "train-revoked-after-wait", "query-revoked-after-wait", "policy-denied"])
def test_reviewed_inference_profiled_generation_rich_physical_original_owner(
        reviewed_physical_owner, monkeypatch, capsys, mode):
    policy = {"schema": "reviewed-decoder-generation-policy/v1",
        "generation_profile": "builtin-llama-dynamic-kv/v1",
        "conditioning_profile": "chatml-complete-legal-ir/v1", "max_generation_seconds": 30.0}
    _run_reviewed_inference_mixed_rich_v4_physical_original_owner(reviewed_physical_owner, monkeypatch, capsys,
        mode, True, context_transport="shared_json_v2", runtime_profile="builtin-llama-bfloat16/v1",
        generation_policy=policy)



@pytest.mark.parametrize("mode", ["healthy", "train-revoked-after-wait", "query-revoked-after-wait", "policy-denied"])
def test_reviewed_inference_Qwen2_rich_generation_physical_original_owner(
        reviewed_physical_owner, monkeypatch, capsys, mode):
    policy = {"schema": "reviewed-decoder-generation-policy/v2",
        "generation_profile": "builtin-qwen2-dynamic-kv/v1",
        "conditioning_profile": "qwen2-chatml-complete-legal-ir/v1",
        "context_budget_profile": "qwen2-full-context-8192/v1", "max_generation_seconds": 30.0}
    _run_reviewed_inference_mixed_rich_v4_physical_original_owner(reviewed_physical_owner, monkeypatch, capsys,
        mode, True, context_transport="shared_json_v2", runtime_profile="builtin-qwen2-bfloat16/v1",
        generation_policy=policy)


def _qualified_actual_pretrained_pair_input(reference):
    """Authenticate already closed import evidence; never load a model here."""
    def load(value):
        assert type(value) is dict and set(value) == {"path", "bytes", "sha256"}
        path = Path(value["path"])
        assert path.is_file() and not path.is_symlink() and path.stat().st_nlink == 1
        digest, total = hashlib.sha256(), 0
        with path.open("rb") as stream:
            while chunk := stream.read(1024**2):
                digest.update(chunk); total += len(chunk)
        assert total == value["bytes"] and digest.hexdigest() == value["sha256"]
        return path
    bundle = json.loads(load(reference).read_bytes())
    assert bundle["schema"] in {"qualified-actual-pretrained-pair-CLI-test-input/v1", "qualified-actual-pretrained-pair-CLI-test-input/v2"}
    qwen2 = bundle["schema"] == "qualified-actual-pretrained-pair-CLI-test-input/v2"
    if qwen2:
        assert set(bundle) == {"schema", "prepared_pair", "pair_closeout", "pair_request", "independent_restoration", "restoration_closeout", "restoration_request", "capacity_preflight"}
    pair = json.loads(load(bundle["prepared_pair"]).read_bytes())
    close = json.loads(load(bundle["pair_closeout"]).read_bytes())
    request = json.loads(load(bundle["pair_request"]).read_bytes())
    custody = close["original_owner_custody"]
    assert close["request_sha256"] == bundle["pair_request"]["sha256"]
    assert close["source_closed"] and custody["returncode"] == 0 and not custody["errors"] and not custody["source_drift"]
    assert all(custody[k] for k in ("genuine_wait_completed", "original_native_compute_closed",
        "original_source_exit_lifecycle_closed", "all_observed_identities_gone", "storage_released_and_durable"))
    assert Path(bundle["prepared_pair"]["path"]) == Path(request["attempt_directory"]) / "exports/prepared-pair.json"
    if qwen2:
        assert pair["schema"] == "actual-pinned-Qwen25-pretrained-checkpoint-pair/v1"
        assert pair["repository"] == "Qwen/Qwen2.5-0.5B-Instruct" and pair["revision"] == "7ae557604adf67be50417f59c2c2f167def9a775"
        assert pair["all_stored_parameters_bit_equal"] and pair["parameters_imported"] == 494032768
        assert pair["pretrained_declaration"] and pair["fresh_Adam_state_empty"] and pair["optimizer_steps"] == 0
        assert not pair["model_forward_executed"] and not pair["training_performed"]
        assert pair["original_weight_artifact"]["sha256"] == "fdf756fa7fcbe7404d5c60e26bff1a0c8b8aa1f72ced49e7dd0210fe288fb7fe"
        restored = json.loads(load(bundle["independent_restoration"]).read_bytes())
        rc = json.loads(load(bundle["restoration_closeout"]).read_bytes());rq = json.loads(load(bundle["restoration_request"]).read_bytes());rv = rc["original_owner_custody"]
        assert rc["request_sha256"] == bundle["restoration_request"]["sha256"] and rc["source_closed"] and rv["returncode"] == 0 and not rv["errors"] and not rv["source_drift"]
        assert all(rv[k] for k in ("genuine_wait_completed", "original_native_compute_closed", "original_source_exit_lifecycle_closed", "all_observed_identities_gone", "storage_released_and_durable"))
        assert Path(bundle["independent_restoration"]["path"]) == Path(rq["attempt_directory"]) / "exports/independent-restoration.json"
        assert restored["prepared_pair"] == bundle["prepared_pair"] and restored["independent_parameters_compared"] == 494032768
        assert restored["loader_receipt"]["matched_pair"] and restored["loader_receipt"]["checkpoint_restored"] and restored["canonical_configuration_bytes_equal"]
        assert not restored["model_forward_executed"] and not restored["training_performed"]
    else:
        assert pair["repository"] == "HuggingFaceTB/SmolLM2-135M-Instruct"
        assert pair["revision"] == "12fd25f77366fa6b3b4b768ec3050bf629380bac"
        assert pair["all_stored_parameters_bit_equal"] and pair["parameters_imported"] == 134515008
        assert pair["pretrained_declaration"] and pair["fresh_Adam_state_empty"] and pair["optimizer_steps"] == 0
        assert not pair["model_forward_executed"] and not pair["training_performed"]
        assert pair["original_weight_artifact"]["sha256"] == "5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c"
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
    mixed_pins = worker._reviewed_decoder_source_pins(admission_profile=worker.REVIEWED_MIXED_ADMISSION_PROFILE)
    # Admission is explicitly bound by the new reviewed request. Preserve the
    # import's original v2 technical pin; never relabel it as a v3 review.
    assert all(pair["expected_source_sha256"][key] == mixed_pins[key]
        for key in ("worker", "inputs", "consumer", "splits"))
    if qwen2: assert pair["expected_source_sha256"] == mixed_pins
    for value in pair["artifacts"].values(): load(value)
    for key in (("capacity_preflight",) if qwen2 else ("source_records", "frame_capacity", "capacity_preflight")): load(bundle[key])
    return SimpleNamespace(bundle=bundle, pair=pair, mixed_source_pins=mixed_pins)


@pytest.fixture
def qualified_actual_pretrained_pair_input():
    import os
    raw = os.environ.get("IPFS_DATASETS_TEST_QUALIFIED_PRETRAINED_PAIR_INPUT")
    if raw is None:
        pytest.skip("explicit admitted qualified pretrained pair descriptor required; no download or model preparation")
    return _qualified_actual_pretrained_pair_input(json.loads(raw))


def test_reviewed_inference_actual_pretrained_profiled_source_physical_original_owner(
        reviewed_physical_owner, monkeypatch, capsys, qualified_actual_pretrained_pair_input):
    _run_reviewed_inference_actual_pretrained_profiled_source_physical_original_owner(
        reviewed_physical_owner, monkeypatch, capsys, qualified_actual_pretrained_pair_input)


def _run_reviewed_inference_actual_pretrained_profiled_source_physical_original_owner(
        reviewed_physical_owner, monkeypatch, capsys, qualified_actual_pretrained_pair_input,
        *, generation_seconds=20.0, conditioning_profile=None, typed_structure_profile=None):
    from copy import deepcopy
    from tests.unit.optimizers.logic_theorem_optimizer import test_legal_ir_evaluation_artifacts as evaluation
    from ipfs_datasets_py.logic.autoformal import training_cycle_inputs as inputs
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
    facts = reviewed_physical_owner
    evidence = qualified_actual_pretrained_pair_input
    pair, bundle = evidence.pair, evidence.bundle
    qwen2 = pair["runtime_profile"] == "builtin-qwen2-bfloat16/v1"
    _, options, populations, replays, components = evaluation._rich_v3_heldout_case()
    from dataclasses import replace
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_eval_splits as splits
    original_manifest = splits.LegalIRSplitManifest.from_mapping(options["split_manifest"])
    query_ids = {row["id"] for row in populations["holdout"]}
    assert len(query_ids) == 3 and all(original_manifest.assignments[row_id] == "holdout" for row_id in query_ids)
    standalone_manifest = replace(original_manifest,
        examples=tuple(row for row in original_manifest.examples if row.sample_id in query_ids),
        assignments={row_id: original_manifest.assignments[row_id] for row_id in query_ids},
        metadata={**original_manifest.metadata, "source_only_projection_of": original_manifest.digest})
    assert {row.sample_id for row in standalone_manifest.examples} == query_ids
    assert all(standalone_manifest.assignments[row_id] == original_manifest.assignments[row_id] for row_id in query_ids)
    options = dict(options, split_manifest=standalone_manifest.to_dict())
    (facts.root / "standalone-heldout-manifest-projection.json").write_text(json.dumps({
        "original_manifest": original_manifest.to_dict(), "source_only_manifest": standalone_manifest.to_dict(),
        "all_three_query_units_preserved": True, "assignments_changed": False,
        "TRAIN_rows_offered_to_source_only_decoder": False}, indent=2) + "\n")
    declaration = components["holdout"]["declaration"]
    contexts = {"profile": "reviewed-source-selection-context/v2",
        "selection_context": {"schema": "caller-known-interpretation-selection/v1",
            "interpretation_id": declaration["interpretation_id"], "selection_mode": "identifier_only"},
        "rows": [{"id": "reviewed:" + unit["unit_id"], "unit_id": unit["unit_id"],
            "governing_context": deepcopy(declaration["governing_context"]),
            "source_binding": {"source_version_cid": unit["source_version"]["record_cid"],
                "occurrence_cid": unit["occurrence"]["record_cid"], "document_revision": unit["document_revision"]}}
            for unit in declaration["units"]]}
    model = SimpleNamespace(options={**{k: worker.CheckpointArtifact.from_dict(v) for k,v in pair["artifacts"].items()},
        "expected_backend_identity": pair["expected_backend_identity"]})
    source_fixture = SimpleNamespace(query_case=components["holdout"], rows=populations["holdout"], options=options,
        contexts=contexts, runtime=SimpleNamespace(current_admission_provider=lambda: deepcopy(replays["holdout"])), model=model)
    policy = {"schema": "reviewed-decoder-generation-policy/v1", "generation_profile": "builtin-llama-dynamic-kv/v1",
        "conditioning_profile": "chatml-complete-legal-ir/v1", "max_generation_seconds": generation_seconds}
    if qwen2:
        policy.update(schema="reviewed-decoder-generation-policy/v2", generation_profile="builtin-qwen2-dynamic-kv/v1",
            conditioning_profile="qwen2-chatml-complete-legal-ir/v1", context_budget_profile="qwen2-full-context-8192/v1")
    if conditioning_profile is not None:
        assert qwen2 and conditioning_profile == worker.REVIEWED_QWEN2_FIELD_LAYOUTS_PROFILE
        policy["conditioning_profile"] = conditioning_profile
    packet = _reviewed_physical_packet(facts, admission_version="v3", runtime_profile=pair["runtime_profile"],
        generation_policy=policy, source_fixture=source_fixture)
    packet.payload.update(max_output_tokens=3500, max_model_bytes=pair["max_model_bytes"],
        max_source_tokens=8192 if qwen2 else 4096,
        request_id="actual-pretrained-fixed-fictional-three-source-only" +
            ("-120s" if generation_seconds == 120.0 else "") +
            ("-field-layouts" if conditioning_profile is not None else ""))
    assert packet.payload["schema"] == ("reviewed-source-evaluation-request/v9" if qwen2 else "reviewed-source-evaluation-request/v7")
    assert packet.payload["source_sha256"] == evidence.mixed_source_pins
    assert packet.original_assets == {}  # No model-checkpoint bytes retained in parent.
    if qwen2:
        from tokenizers import Tokenizer
        native = Tokenizer.from_file(pair["artifacts"]["tokenizer_artifact"]["path"])
        records = []
        for row, context in zip(source_fixture.rows, contexts["rows"], strict=True):
            wire = inputs._reviewed_wire({"profile": inputs.REVIEWED_DECODER_SOURCE_PROFILE,
                "source_text": row["source_text"], "governing_context": context["governing_context"],
                "source_binding": context["source_binding"], "selection_context": contexts["selection_context"]}).decode()
            records.append({"id": row["id"], "unit_id": context["unit_id"], "source_wire": wire,
                "source_token_ids": [151643, *native.encode(wire, add_special_tokens=False).ids, 151645]})
        path = facts.root / "actual-Qwen-source-records.json";path.write_bytes(inputs._reviewed_wire(records))
        bundle = {**bundle, "source_records": {"path": str(path), "bytes": path.stat().st_size, "sha256": _sha(path)}}
    else:
        records = json.loads(Path(bundle["source_records"]["path"]).read_bytes())
    assert len(records) == len(source_fixture.rows) == 3
    for record, row, context in zip(records, source_fixture.rows, contexts["rows"], strict=True):
        wire = inputs._reviewed_wire({"profile": inputs.REVIEWED_DECODER_SOURCE_PROFILE,
            "source_text": row["source_text"], "governing_context": context["governing_context"],
            "source_binding": context["source_binding"], "selection_context": contexts["selection_context"]}).decode()
        assert record["id"] == row["id"] and record["source_wire"] == wire
    cli = _reviewed_physical_cli(monkeypatch)
    assert _reviewed_physical_run(cli, facts, packet,
        **({} if typed_structure_profile is None else {"typed_structure_profile":typed_structure_profile})) == 0
    report = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert report["original_owner_reservation_id"] == facts.owner.reservation_id
    assert all(report[k] for k in ("parent_FINISH_acknowledged", "original_child_waited",
        "parent_current_admission_rechecked_after_wait", "parent_output_artifacts_rechecked_after_wait"))
    assert not report["training_executed"] and report["weight_publications"] == []
    assert not report["resource_release_performed"]
    output = facts.attempt / "outputs"
    cycle = json.loads((output / "cycle.json").read_bytes())
    _assert_reviewed_output_artifacts(output, cycle, report)
    typed_audit = None
    if typed_structure_profile is not None:
        assert report["schema"] == "reviewed-source-evaluation-parent/v2"
        assert report["typed_structure_profile"] == typed_structure_profile
        assert report["parent_typed_structure_audit_after_wait"] and report["parent_current_admission_rechecked_after_audit"]
        descriptor = report["typed_structure_audit_artifact"];path=Path(descriptor["path"])
        assert descriptor == {"path":str(path), "bytes":path.stat().st_size, "sha256":_sha(path)}
        typed_audit=json.loads(path.read_bytes())
        assert typed_audit["request_sha256"] == cycle["request_sha256"]
        assert typed_audit["original_output_artifacts"] == cycle["output_artifacts"]
        assert typed_audit["report"]["denominator"] == typed_audit["report"]["canonical_reference_count"] == 3
        assert sum(typed_audit["report"]["counts"].values()) == 3
        assert not any(typed_audit[k] for k in ("native_proof_verified","legal_meaning_verified","current_admission_authority_granted","model_reexecuted"))
    else:
        assert report["schema"] == "reviewed-source-evaluation-parent/v1"
        assert "typed_structure_audit_artifact" not in report
    loader = json.loads((output / "loader.json").read_bytes())
    assert loader["checkpoint_restored"] and loader["matched_pair"] and loader["optimizer_steps"] == 0
    assert loader["dtype"] == "bfloat16" and loader["runtime_profile"] == pair["runtime_profile"]
    generation = json.loads((output / "generation.json").read_bytes())
    assert generation["schema"] == ("reviewed-decoder-source-producer-observation/v4" if qwen2 else "reviewed-decoder-source-producer-observation/v3")
    assert generation["input_commitment"]["generation_policy"] == policy
    assert generation["input_profile_id"] == ("reviewed-decoder-qwen2-profiled-producer/v1:" if qwen2 else "reviewed-decoder-profiled-producer/v1:") + evaluation._producer_digest(generation["input_commitment"])
    call = generation["last_call"]
    assert call["completed"] and call["entry_pair_match"] and call["exit_pair_match"]
    assert call["source_records_sha256"] == evaluation._producer_digest(records)
    assert [row["id"] for row in call["raw_generation_outputs"]] == [row["id"] for row in records]
    assert len(call["raw_generation_outputs"]) == 3
    # Independent tokenizer checks occur only after the actual child exited.
    _reviewed_physical_assert_stopped(facts)
    from tokenizers import Tokenizer
    native = Tokenizer.from_file(pair["artifacts"]["tokenizer_artifact"]["path"])
    if qwen2:
        from transformers import PreTrainedTokenizerFast
        from tests.unit.optimizers.logic_theorem_optimizer import test_autoencoder_training_worker as models
        recipe = json.loads(Path(pair["artifacts"]["recipe_artifact"]["path"]).read_bytes())
        frontend = PreTrainedTokenizerFast(tokenizer_object=Tokenizer.from_file(pair["artifacts"]["tokenizer_artifact"]["path"]), **recipe["tokenizer"])
        frames = {"rows": []}
        for record in records:
            ids = models._reviewed_chatml_native_test_frame(frontend, record["source_wire"],
                public_layouts=policy["conditioning_profile"] == worker.REVIEWED_QWEN2_FIELD_LAYOUTS_PROFILE)
            frames["rows"].append({"id": record["id"], "complete_frame_token_ids": ids,
                "complete_frame_text": native.decode(ids, skip_special_tokens=False)})
        path = facts.root / "actual-Qwen-source-capacity.json";path.write_bytes(inputs._reviewed_wire(frames))
        bundle["frame_capacity"] = {"path": str(path), "bytes": path.stat().st_size, "sha256": _sha(path)}
    else:
        frames = json.loads(Path(bundle["frame_capacity"]["path"]).read_bytes())
    for record, frame in zip(records, frames["rows"], strict=True):
        assert record["id"] == frame["id"]
        assert [151643 if qwen2 else 1, *native.encode(record["source_wire"], add_special_tokens=False).ids, 151645 if qwen2 else 2] == record["source_token_ids"]
        assert native.decode(record["source_token_ids"][1:-1], skip_special_tokens=False) == record["source_wire"]
        assert native.encode(frame["complete_frame_text"], add_special_tokens=False).ids == frame["complete_frame_token_ids"]
        assert len(frame["complete_frame_token_ids"]) + 3500 - 1 <= (32768 if qwen2 else 4096)
    evaluated = json.loads((output / "evaluation.json").read_bytes())
    assert evaluated["metrics"]["complete_norm_payload"]["denominator"] == 3
    if typed_audit is not None:
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_semantic_metrics as metrics
        payload=evaluated["compiler_artifact"]["reviewed_source_span_producer_evaluation"]
        assert typed_audit["report"] == metrics.evaluate_complete_norm_typed_structure([
            dict(case_id=r["id"], reference=r["canonical_ir"], candidate=o["candidate"], outcome=o["outcome"])
            for r,o in zip(source_fixture.rows,payload["producer_outputs"],strict=True)])
        _assert_reviewed_output_artifacts(output, cycle, report)

    (facts.root / "actual-pretrained-CLI-result.json").write_text(json.dumps({
        "schema": "actual-pretrained-reviewed-parent-CLI-observation/v1", "prepared_pair": bundle["prepared_pair"],
        "pair_closeout": bundle["pair_closeout"], "fixed_population_records": bundle["source_records"],
        "runtime_profile": pair["runtime_profile"], "generation_policy": policy,
        "outputs": call["raw_generation_outputs"], "metrics": evaluated["metrics"],
        **({} if typed_audit is None else {"original_parent_typed_structure_audit_artifact":report["typed_structure_audit_artifact"],
            "original_parent_typed_structure_audit_report":typed_audit["report"]}),
        "emitted_prefixes_DATA_only": [{"id": row["id"],
            "text": native.decode(row["generated_token_ids"][1:], skip_special_tokens=False),
            "not_a_candidate": True} for row in call["raw_generation_outputs"]],
        "parent_FINISH_wait_review_and_output_checks": True, "paired_state_restored": True,
        "actual_parameters_imported": pair["parameters_imported"], "training_performed": False,
        "legal_meaning_verified": False, "fair_A_to_F_comparison": False}, indent=2) + "\n")
    for descriptor in packet.payload["assets"].values():
        digest = hashlib.sha256()
        with Path(descriptor["path"]).open("rb") as stream:
            while chunk := stream.read(1024**2): digest.update(chunk)
        assert digest.hexdigest() == descriptor["sha256"]
    _reviewed_physical_fsync_tree(facts.root)
    assert facts.owner.finalize(facts.attempt, artifacts_durable=True)["status"] == "released"



@pytest.mark.parametrize("damage", ["pair-pin", "closeout-open", "request-join"])
def test_reviewed_inference_actual_pretrained_pair_input_refuses_changed_evidence(
        tmp_path, qualified_actual_pretrained_pair_input, damage):
    from copy import deepcopy
    original = qualified_actual_pretrained_pair_input
    bundle = deepcopy(original.bundle)
    if damage == "pair-pin":
        bundle["prepared_pair"]["sha256"] = "0" * 64
    else:
        close = json.loads(Path(bundle["pair_closeout"]["path"]).read_bytes())
        if damage == "closeout-open": close["original_owner_custody"]["storage_released_and_durable"] = False
        else: close["request_sha256"] = "0" * 64
        raw = json.dumps(close, sort_keys=True, separators=(",", ":")).encode()
        path = tmp_path / "changed-closeout.json"
        path.write_bytes(raw)
        bundle["pair_closeout"] = {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    raw = json.dumps(bundle, sort_keys=True, separators=(",", ":")).encode()
    path = tmp_path / "changed-bundle.json"
    path.write_bytes(raw)
    with pytest.raises(AssertionError):
        _qualified_actual_pretrained_pair_input({"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})


def test_reviewed_inference_actual_Qwen25_source_physical_original_owner(
        reviewed_physical_owner, monkeypatch, capsys, qualified_actual_pretrained_pair_input):
    assert qualified_actual_pretrained_pair_input.pair["runtime_profile"] == "builtin-qwen2-bfloat16/v1"
    _run_reviewed_inference_actual_pretrained_profiled_source_physical_original_owner(
        reviewed_physical_owner, monkeypatch, capsys, qualified_actual_pretrained_pair_input)


def test_reviewed_inference_actual_Qwen25_source_120s_physical_original_owner(
        reviewed_physical_owner, monkeypatch, capsys, qualified_actual_pretrained_pair_input):
    """Budget sensitivity on all three fixed queries; no quality assertion."""
    import os
    assert os.environ.get("IPFS_DATASETS_TEST_REVIEWED_MEMORY_PROFILE") == "12288"
    assert qualified_actual_pretrained_pair_input.pair["runtime_profile"] == "builtin-qwen2-bfloat16/v1"
    _run_reviewed_inference_actual_pretrained_profiled_source_physical_original_owner(
        reviewed_physical_owner, monkeypatch, capsys, qualified_actual_pretrained_pair_input,
        generation_seconds=120.0)


def test_reviewed_inference_actual_Qwen25_source_layout_120s_physical_original_owner(
        reviewed_physical_owner, monkeypatch, capsys, qualified_actual_pretrained_pair_input):
    import os
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
    assert os.environ.get("IPFS_DATASETS_TEST_REVIEWED_MEMORY_PROFILE") == "12288"
    assert qualified_actual_pretrained_pair_input.pair["runtime_profile"] == "builtin-qwen2-bfloat16/v1"
    _run_reviewed_inference_actual_pretrained_profiled_source_physical_original_owner(
        reviewed_physical_owner, monkeypatch, capsys, qualified_actual_pretrained_pair_input,
        generation_seconds=120.0, conditioning_profile=worker.REVIEWED_QWEN2_FIELD_LAYOUTS_PROFILE)


@pytest.mark.parametrize("damage", ["pair-pin", "closeout-open", "request-join", "restored-pin", "restored-open"])
def test_reviewed_inference_actual_Qwen25_pair_input_refuses_changed_evidence(
        tmp_path, qualified_actual_pretrained_pair_input, damage):
    from copy import deepcopy
    original = qualified_actual_pretrained_pair_input
    bundle = deepcopy(original.bundle)
    if damage in ("pair-pin", "restored-pin"):
        bundle["prepared_pair" if damage == "pair-pin" else "independent_restoration"]["sha256"] = "0" * 64
    else:
        key = "restoration_closeout" if damage == "restored-open" else "pair_closeout"
        close = json.loads(Path(bundle[key]["path"]).read_bytes())
        if damage in ("closeout-open", "restored-open"):
            close["original_owner_custody"]["storage_released_and_durable"] = False
        else:
            close["request_sha256"] = "0" * 64
        raw = json.dumps(close, sort_keys=True, separators=(",", ":")).encode()
        path = tmp_path / "changed-Qwen-closeout.json";path.write_bytes(raw)
        bundle[key] = {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    raw = json.dumps(bundle, sort_keys=True, separators=(",", ":")).encode()
    path = tmp_path / "changed-Qwen-bundle.json";path.write_bytes(raw)
    with pytest.raises(AssertionError):
        _qualified_actual_pretrained_pair_input({"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})


def test_reviewed_inference_actual_Qwen25_rich_packet_is_descriptor_only(
        reviewed_physical_owner, monkeypatch, qualified_actual_pretrained_pair_input, qualified_actual_GTE_ranked_input):
    import builtins
    from tests.unit.optimizers.logic_theorem_optimizer import test_autoencoder_training_worker as numerical
    facts = reviewed_physical_owner
    original = builtins.__import__
    def no_vendor_model(name, *args, **kwargs):
        if name.split(".", 1)[0] in ("torch", "transformers", "tokenizers"):
            pytest.fail("descriptor-only rich packet imported a vendor model/tokenizer")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", no_vendor_model)
    packet, fixture = _reviewed_physical_mixed_rich_packet(facts, shared_context=True, context_transport="shared_json_v2",
        actual_GTE_bundle=qualified_actual_GTE_ranked_input, runtime_profile="builtin-qwen2-bfloat16/v1",
        generation_policy=numerical._reviewed_Qwen2_generation_policy(),
        qualified_pretrained_pair=qualified_actual_pretrained_pair_input)
    assert packet.payload["schema"] == "reviewed-source-evaluation-request/v10"
    assert packet.payload["max_source_tokens"] == 8192 and packet.payload["max_output_tokens"] == 3500
    assert packet.payload["max_model_bytes"] == 2*1024**3 and packet.original_assets == {}
    assert facts.owner._child is None and fixture.actual_pretrained
    receipt = fixture.model.preparation_receipt
    assert receipt["upstream_import_and_restoration_closed"] and not receipt["current_preparation_child_created"]
    assert not receipt["parent_model_or_optimizer_retained"]
    snapshot = receipt["ranked_context_snapshot"]
    assert snapshot["actual_GTE_lineage"]["original_custody_closed"] and not snapshot["actual_GTE_lineage"]["encoder_reexecuted"]
    assert packet.payload["checkpoint_declarations"]["encoder"]["sha256"] == snapshot["ranking_provenance"]["checkpoint_sha256"]
    assert all(len(row) == 3 for row in fixture.options["retrieved_examples"].values())
    _reviewed_physical_fsync_tree(facts.root)
    assert facts.owner.finalize(facts.attempt, artifacts_durable=True)["status"] == "released"


def test_reviewed_inference_actual_Qwen25_rich_physical_original_owner(
        reviewed_physical_owner, monkeypatch, capsys, qualified_actual_pretrained_pair_input,
        qualified_actual_GTE_ranked_input):
    assert qualified_actual_pretrained_pair_input.pair["runtime_profile"] == "builtin-qwen2-bfloat16/v1"
    policy = {"schema": "reviewed-decoder-generation-policy/v2", "generation_profile": "builtin-qwen2-dynamic-kv/v1",
        "conditioning_profile": "qwen2-chatml-complete-legal-ir/v1", "context_budget_profile": "qwen2-full-context-8192/v1",
        "max_generation_seconds": 20.0}
    _run_reviewed_inference_mixed_rich_v4_physical_original_owner(reviewed_physical_owner, monkeypatch, capsys,
        "healthy", True, context_transport="shared_json_v2", actual_GTE_bundle=qualified_actual_GTE_ranked_input,
        runtime_profile="builtin-qwen2-bfloat16/v1", generation_policy=policy,
        qualified_pretrained_pair=qualified_actual_pretrained_pair_input)


def _reviewed_Qwen2_request_data(tmp_path,rich=False):
    worker,consumer,value,write=_reviewed_profiled_request_data(tmp_path,rich)
    from tests.unit.optimizers.logic_theorem_optimizer import test_autoencoder_training_worker as numerical
    value.update(schema="reviewed-source-evaluation-request/v10"if rich else"reviewed-source-evaluation-request/v9",
        runtime_profile="builtin-qwen2-bfloat16/v1",generation_policy=numerical._reviewed_Qwen2_generation_policy(),
        max_model_bytes=1024**3,max_source_tokens=8192)
    if rich:value["training_context"]["context_budget_profile"]="qwen2-full-context-8192/v1"
    return worker,consumer,value,write


@pytest.mark.parametrize("rich",[False,True])
@pytest.mark.parametrize("damage",[None,"runtime","policy_version","context_budget","state_bound","downgrade","domain","extra","missing_context","training_budget","legacy_large_bound","training_context_type"])
def test_reviewed_inference_Qwen2_request_is_explicit_closed_data(tmp_path,monkeypatch,rich,damage):
    import builtins
    worker,consumer,value,write=_reviewed_Qwen2_request_data(tmp_path,rich)
    if damage=="runtime":value["runtime_profile"]="builtin-llama-bfloat16/v1"
    elif damage=="policy_version":value["generation_policy"]={"schema":"reviewed-decoder-generation-policy/v1","generation_profile":"builtin-llama-dynamic-kv/v1","conditioning_profile":"chatml-complete-legal-ir/v1","max_generation_seconds":1.0}
    elif damage=="context_budget":value["generation_policy"]["context_budget_profile"]="unknown"
    elif damage=="state_bound":value["max_model_bytes"]=2*1024**3+1
    elif damage=="downgrade":value["schema"]="reviewed-source-evaluation-request/v8"if rich else"reviewed-source-evaluation-request/v7"
    elif damage=="domain":value["admission_profile"]="complete-reviewed-norm-admission/v2"
    elif damage=="extra":value["generation_policy"]["target_json"]="forbidden"
    elif damage=="missing_context":value["generation_policy"].pop("context_budget_profile")
    elif damage=="legacy_large_bound":
        value["schema"]="reviewed-source-evaluation-request/v8"if rich else"reviewed-source-evaluation-request/v7"
        value["runtime_profile"]="builtin-llama-bfloat16/v1"
        value["generation_policy"]={"schema":"reviewed-decoder-generation-policy/v1","generation_profile":"builtin-llama-dynamic-kv/v1","conditioning_profile":"chatml-complete-legal-ir/v1","max_generation_seconds":1.0}
        if rich:value["training_context"].pop("context_budget_profile")
    elif damage=="training_context_type":
        if rich:value["training_context"]=[]
        else:value["generation_policy"]["context_budget_profile"]=False
    elif damage=="training_budget":
        if rich:value["training_context"]["context_budget_profile"]="unknown"
        else:value["max_model_bytes"]=True
    original=builtins.__import__
    def no_native(name,*a,**k):
        if name.split(".",1)[0]in("torch","transformers","tokenizers"):pytest.fail("request DATA imported native code")
        return original(name,*a,**k)
    monkeypatch.setattr(builtins,"__import__",no_native)
    if damage is None:
        _,_,loaded=inference._read_reviewed_evaluation_request(write());assert loaded==value
    else:
        with pytest.raises(ValueError):inference._read_reviewed_evaluation_request(write())
    assert not Path(value["output_directory"]).exists()


def _reviewed_Qwen2_parent_policy_data(tmp_path,kind):
    worker,request,policy=_reviewed_profiled_parent_policy_data(tmp_path,kind)
    from tests.unit.optimizers.logic_theorem_optimizer import test_autoencoder_training_worker as numerical
    request.update(schema="reviewed-source-evaluation-request/v9",runtime_profile="builtin-qwen2-bfloat16/v1",
        generation_policy=numerical._reviewed_Qwen2_generation_policy(),max_model_bytes=1024**3)
    if kind=="load":policy.update(runtime_profile=request["runtime_profile"],max_model_bytes=request["max_model_bytes"])
    else:policy.update(schema="reviewed-decoder-source-producer-policy/v4",runtime_profile=request["runtime_profile"],generation_policy=json.loads(worker._json_bytes(request["generation_policy"])))
    return worker,request,policy


@pytest.mark.parametrize("kind",["load","producer"])
@pytest.mark.parametrize("damage",[None,"schema","runtime","context","limit","extra"])
def test_reviewed_inference_Qwen2_parent_policy_matches_original_request(tmp_path,kind,damage):
    worker,request,policy=_reviewed_Qwen2_parent_policy_data(tmp_path,kind)
    if damage=="schema":policy["schema"]="unknown"
    elif damage=="runtime":policy["runtime_profile"]="builtin-llama-bfloat16/v1"
    elif damage=="context":
        if kind=="producer":policy["generation_policy"]["context_budget_profile"]="unknown"
        else:policy["dtype"]="float32"
    elif damage=="limit":policy["max_model_bytes"if kind=="load"else"max_source_tokens"]+=1
    elif damage=="extra":policy["target_json"]="forbidden"
    if damage is None:inference._check_reviewed_generation_policy(request,policy)
    else:
        with pytest.raises(ValueError):inference._check_reviewed_generation_policy(request,policy)


@pytest.mark.parametrize("damage",[None,"budget","schema","missing","downgrade","policy_type","context_type"])
def test_reviewed_inference_Qwen2_context_transport_matches_explicit_budget(damage):
    from ipfs_datasets_py.logic.autoformal import training_cycle_inputs as inputs
    context=dict(transport="shared_json_v2",context_budget_profile="qwen2-full-context-8192/v1")
    policy=dict(schema="reviewed-decoder-rich-context-use-policy/v3",context_transport="shared_json_v2",
        max_expanded_context_bytes=inputs.REVIEWED_SHARED_CONTEXT_MAX_EXPANDED_BYTES,
        shared_context_schema=inputs.REVIEWED_SHARED_CONTEXT_JSON_SCHEMA_V2,
        max_context_bytes=16384,max_context_tokens=8192,context_budget_profile=context["context_budget_profile"])
    if damage=="budget":policy["max_context_tokens"]=4096
    elif damage=="schema":policy["schema"]="reviewed-decoder-rich-context-use-policy/v2"
    elif damage=="missing":policy.pop("context_budget_profile")
    elif damage=="downgrade":context.pop("context_budget_profile")
    elif damage=="policy_type":policy=[]
    elif damage=="context_type":context=[]
    if damage is None:inference._check_reviewed_context_transport_policy(context,policy)
    else:
        with pytest.raises(ValueError):inference._check_reviewed_context_transport_policy(context,policy)


@pytest.mark.parametrize("damage",[None,"policy","profile","schema","runtime"])
def test_reviewed_inference_Qwen2_output_commitment_checked_after_bytes(tmp_path,damage):
    worker,request,policy=_reviewed_Qwen2_parent_policy_data(tmp_path,"producer")
    output=tmp_path/"outputs";output.mkdir();request["output_directory"]=str(output)
    commitment={**policy,"source_sha256":request["source_sha256"],"exposure_sha256":"a"*64,"supplied_context_supported":"empty_permitted_and_retrieved_only"}
    if damage=="policy":commitment["generation_policy"]["max_generation_seconds"]=2.0
    elif damage=="runtime":commitment["runtime_profile"]="builtin-llama-bfloat16/v1"
    generation=dict(schema="reviewed-decoder-source-producer-observation/v4",input_commitment=commitment,
        input_profile_id="reviewed-decoder-qwen2-profiled-producer/v1:"+worker._digest(worker._json_bytes(commitment)))
    if damage=="profile":generation["input_profile_id"]="reviewed-decoder-qwen2-profiled-producer/v1:"+"0"*64
    elif damage=="schema":generation["schema"]="reviewed-decoder-source-producer-observation/v3"
    paths={};descriptors={}
    for name,value in(("evaluation",{}),("loader",{}),("generation",generation)):
        path=output/(name+".json");path.write_bytes(worker._json_bytes(value));paths[name]=str(path);descriptors[name]=dict(path=str(path),bytes=path.stat().st_size,sha256=_sha(path))
    cycle=dict(output_artifacts=descriptors,inference=dict(profile=request["schema"],**paths))
    if damage is None:inference._check_reviewed_evaluation_outputs(cycle,request)
    else:
        with pytest.raises(ValueError):inference._check_reviewed_evaluation_outputs(cycle,request)


@pytest.mark.parametrize("rich", [False, True])
@pytest.mark.parametrize("damage", [None, "schema", "target"])
def test_reviewed_inference_Qwen2_public_layout_request_is_closed_data(tmp_path, monkeypatch, rich, damage):
    import builtins
    worker, consumer, value, write = _reviewed_Qwen2_request_data(tmp_path, rich)
    value["generation_policy"]["conditioning_profile"] = "qwen2-chatml-field-layouts/v1"
    if damage == "schema": value["generation_policy"]["field_layouts"] = "caller-chosen"
    elif damage == "target": value["generation_policy"]["target_json"] = {"answer": "forbidden"}
    original = builtins.__import__
    def no_native(name, *args, **kwargs):
        if name.split(".", 1)[0] in ("torch", "transformers", "tokenizers"):
            pytest.fail("closed request DATA imported a native runtime")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", no_native)
    if damage is None:
        assert inference._read_reviewed_evaluation_request(write())[2] == value
    else:
        with pytest.raises(ValueError): inference._read_reviewed_evaluation_request(write())
    assert not Path(value["output_directory"]).exists()


@pytest.mark.parametrize("profile", [None, "canonical-typed-expression-wire/v1", False, 1, {}, "unknown"])
def test_reviewed_inference_parent_typed_audit_runtime_is_trusted_closed_data(profile):
    callbacks = [lambda: None, lambda _: None, lambda: {}]
    if profile is None or type(profile) is str and profile == "canonical-typed-expression-wire/v1":
        runtime = inference.ReviewedInferenceParentRuntime(object(), *callbacks, 1.0, typed_structure_profile=profile)
        assert runtime.typed_structure_profile == profile
    else:
        with pytest.raises(ValueError, match="typed-structure profile"):
            inference.ReviewedInferenceParentRuntime(object(), *callbacks, 1.0, typed_structure_profile=profile)


@pytest.mark.parametrize("rich", [False, True])
def test_reviewed_inference_parent_typed_audit_cannot_be_enabled_by_packet(tmp_path, rich):
    worker, consumer, value, write = _reviewed_Qwen2_request_data(tmp_path, rich)
    value["typed_structure_profile"] = "canonical-typed-expression-wire/v1"
    with pytest.raises(ValueError, match="closed reviewed"):
        inference._read_reviewed_evaluation_request(write())
    assert not Path(value["output_directory"]).exists()


@pytest.fixture(scope="module")
def parent_typed_audit_seed():
    from tests.unit.optimizers.logic_theorem_optimizer import test_legal_ir_evaluation_artifacts as evaluation
    _, options, populations, _, _ = evaluation._rich_v3_heldout_case()
    rows = populations["holdout"]
    artifact = evaluation._producer_evaluate(options, lambda _: evaluation._producer_exact_outputs(rows)).to_dict()
    return rows, artifact


@pytest.mark.parametrize("damage", [None, "rows", "source", "outcome", "metrics", "checkpoint", "batch_error", "unbound_error"])
def test_reviewed_inference_parent_typed_audit_binds_complete_original_artifacts(tmp_path, parent_typed_audit_seed, damage):
    from copy import deepcopy
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
    rows, evaluation = deepcopy(parent_typed_audit_seed)
    payload = evaluation["compiler_artifact"]["reviewed_source_span_producer_evaluation"]
    generation = {"last_call": {"completed": True, "raw_generation_outputs": deepcopy(payload["producer_outputs"])}}
    checkpoints = deepcopy(payload["configuration"]["checkpoint_declarations"])
    if damage in ("batch_error", "unbound_error"):
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_semantic_metrics as metrics
        for row in payload["producer_outputs"]: row.update(candidate=None, outcome="error")
        payload["producer_exception_type"] = "RuntimeError"
        exact = metrics.evaluate_complete_norm_payloads([dict(case_id=r["id"], reference=r["canonical_ir"],
            candidate=o["candidate"], outcome=o["outcome"]) for r,o in zip(rows,payload["producer_outputs"],strict=True)])
        payload["comparison"] = exact;evaluation["metrics"]["complete_norm_payload"] = deepcopy(exact)
        generation["last_call"].update(completed=False, raw_generation_outputs=None, exception_type=("RuntimeError" if damage=="batch_error" else "ValueError"),
            entry_pair_match=True, exit_pair_match=True, closeout_exception_type=None)
    if damage == "rows": rows[0]["source_text"] += " altered"
    elif damage == "source": payload["producer_arguments"][0]["source_text"] += " altered"
    elif damage == "outcome": generation["last_call"]["raw_generation_outputs"][0]["outcome"] = "incomplete"
    elif damage == "metrics": evaluation["metrics"]["complete_norm_payload"]["metric_numerators"]["full_nine_payload_exact"] = 999
    elif damage == "checkpoint": checkpoints["decoder"]["sha256"] = "0" * 64
    def save(name, value):
        path = tmp_path / (name + ".json");path.write_bytes(worker._json_bytes(value))
        return {"path": str(path), "bytes": path.stat().st_size, "sha256": _sha(path)}
    artifacts = {"evaluation": save("evaluation", evaluation), "generation": save("generation", generation), "loader": save("loader", {})}
    request = {"rows_artifact": save("rows", rows), "checkpoint_declarations": checkpoints}
    cycle = {"output_artifacts": artifacts};cycle_ref = worker.CheckpointArtifact.from_dict(save("cycle", cycle))
    if damage not in (None, "batch_error"):
        with pytest.raises(ValueError, match="parent typed-structure"):
            inference._build_parent_typed_structure_audit(cycle, request, cycle_ref, "a" * 64, {})
    else:
        report = inference._build_parent_typed_structure_audit(cycle, request, cycle_ref, "a" * 64, {})
        assert report["report"]["denominator"] == 3
        assert report["report"]["counts"] == ({"canonical_formula":0,"invalid_complete":0,"not_checked":3} if damage=="batch_error" else {"canonical_formula":3,"invalid_complete":0,"not_checked":0})
        if damage=="batch_error":assert report["generation_join_scope"]=="recorded_batch_exception_without_raw_generation_rows"
        assert report["native_proof_verified"] is report["legal_meaning_verified"] is report["current_admission_authority_granted"] is False
        assert report["original_output_artifacts"] == artifacts
    assert not (tmp_path / "typed-structure-audit.json").exists()


@pytest.mark.parametrize("rich,mode", [(False,"healthy"),(True,"healthy"),(False,"query-revoked"),
                                      (True,"train-revoked"),(False,"output-tampered")])
def test_reviewed_inference_parent_typed_audit_original_owner(reviewed_physical_owner, monkeypatch, capsys, rich, mode):
    from copy import deepcopy
    facts = reviewed_physical_owner
    if rich:
        packet, fixture = _reviewed_physical_mixed_rich_packet(facts, shared_context=True, context_transport="shared_json_v2")
    else:
        packet = _reviewed_physical_packet(facts, admission_version="v3")
    cli = _reviewed_physical_cli(monkeypatch);seen = [];state = {"revoked": False}
    original = inference._build_parent_typed_structure_audit
    def observe(*args, **kwargs):
        _reviewed_physical_assert_stopped(facts)
        seen.append(True);report = original(*args, **kwargs)
        if mode in ("query-revoked", "train-revoked"): state["revoked"] = True
        elif mode == "output-tampered":
            path = facts.attempt / "outputs/evaluation.json";path.write_bytes(path.read_bytes() + b" ")
        return report
    monkeypatch.setattr(inference, "_build_parent_typed_structure_audit", observe)
    def query():
        value = packet.fresh_admission()
        if state["revoked"] and mode == "query-revoked": value["at_time_utc"] = "2026-01-01T00:00:00Z"
        return value
    context = dict(packet.context_callbacks)
    if rich:
        fresh = context["current_training_admission_provider"]
        def train():
            value = deepcopy(fresh())
            if state["revoked"] and mode == "train-revoked": value["at_time_utc"] = "2026-01-01T00:00:00Z"
            return value
        context["current_training_admission_provider"] = train
    def run():
        return _reviewed_physical_run(cli, facts, packet, admission_provider=query,
            context_callbacks=context, typed_structure_profile="canonical-typed-expression-wire/v1")
    output = facts.attempt / "outputs"
    if mode == "healthy":
        assert run() == 0
        report = json.loads(capsys.readouterr().out.splitlines()[-1])
        assert report["schema"] == "reviewed-source-evaluation-parent/v2"
        assert report["parent_typed_structure_audit_after_wait"] and report["parent_current_admission_rechecked_after_audit"]
        descriptor = report["typed_structure_audit_artifact"];path = Path(descriptor["path"])
        assert descriptor == {"path": str(path), "bytes": path.stat().st_size, "sha256": _sha(path)}
        audit = json.loads(path.read_bytes());assert audit["report"]["denominator"] == audit["report"]["canonical_reference_count"] == 3
        assert audit["report"]["counts"] == {"canonical_formula": 0, "invalid_complete": 0, "not_checked": 3}
        assert not audit["native_proof_verified"] and not audit["legal_meaning_verified"]
        cycle = json.loads((output / "cycle.json").read_bytes());_assert_reviewed_output_artifacts(output, cycle, report)
        assert audit["original_output_artifacts"] == cycle["output_artifacts"]
        assert audit["request_sha256"] == cycle["request_sha256"]
    else:
        with pytest.raises((ValueError, packet.worker.TrainingJobValidationError)):
            run()
        assert not (output / "parent-cycle.json").exists() and not (output / "typed-structure-audit.json").exists()
    assert seen == [True]
    _reviewed_physical_assert_stopped(facts);_reviewed_physical_fsync_tree(facts.root)
    assert facts.owner.finalize(facts.attempt, artifacts_durable=True)["status"] == "released"


def test_reviewed_inference_actual_Qwen25_source_layout_typed_audit_physical_original_owner(
        reviewed_physical_owner, monkeypatch, capsys, qualified_actual_pretrained_pair_input):
    import os
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
    assert os.environ.get("IPFS_DATASETS_TEST_REVIEWED_MEMORY_PROFILE") == "12288"
    assert qualified_actual_pretrained_pair_input.pair["runtime_profile"] == "builtin-qwen2-bfloat16/v1"
    _run_reviewed_inference_actual_pretrained_profiled_source_physical_original_owner(
        reviewed_physical_owner, monkeypatch, capsys, qualified_actual_pretrained_pair_input,
        conditioning_profile=worker.REVIEWED_QWEN2_FIELD_LAYOUTS_PROFILE,
        typed_structure_profile="canonical-typed-expression-wire/v1")


def test_reviewed_inference_actual_Qwen25_rich_layout_typed_audit_physical_original_owner(
        reviewed_physical_owner, monkeypatch, capsys, qualified_actual_pretrained_pair_input,
        qualified_actual_GTE_ranked_input):
    import os
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
    assert os.environ.get("IPFS_DATASETS_TEST_REVIEWED_MEMORY_PROFILE") == "12288"
    assert qualified_actual_pretrained_pair_input.pair["runtime_profile"] == "builtin-qwen2-bfloat16/v1"
    policy={"schema":"reviewed-decoder-generation-policy/v2","generation_profile":"builtin-qwen2-dynamic-kv/v1",
        "conditioning_profile":worker.REVIEWED_QWEN2_FIELD_LAYOUTS_PROFILE,"context_budget_profile":"qwen2-full-context-8192/v1",
        "max_generation_seconds":20.0}
    _run_reviewed_inference_mixed_rich_v4_physical_original_owner(reviewed_physical_owner,monkeypatch,capsys,
        "healthy",True,context_transport="shared_json_v2",actual_GTE_bundle=qualified_actual_GTE_ranked_input,
        runtime_profile="builtin-qwen2-bfloat16/v1",generation_policy=policy,
        qualified_pretrained_pair=qualified_actual_pretrained_pair_input,
        typed_structure_profile="canonical-typed-expression-wire/v1")


@pytest.mark.parametrize('profile', [None, 'unreviewed-complete-norm-candidate-syntax/v2',
    'unreviewed-complete-norm-candidate-syntax/v3', False, 1, {}, 'unknown'])
def test_reviewed_parent_candidate_audit_trusted_runtime_closed_profile(profile):
    callbacks = [lambda: None, lambda _: None, lambda: {}]
    if profile is None or type(profile) is str and profile.endswith(('/v2', '/v3')):
        runtime = inference.ReviewedInferenceParentRuntime(object(), *callbacks, 1.0, candidate_syntax_profile=profile)
        assert runtime.candidate_syntax_profile == profile
    else:
        with pytest.raises(ValueError, match='candidate-syntax profile'):
            inference.ReviewedInferenceParentRuntime(object(), *callbacks, 1.0, candidate_syntax_profile=profile)


@pytest.mark.parametrize('rich', [False, True])
def test_reviewed_parent_candidate_audit_not_enabled_by_packet(tmp_path, rich):
    _, _, value, write = _reviewed_Qwen2_request_data(tmp_path, rich)
    value['candidate_syntax_profile'] = 'unreviewed-complete-norm-candidate-syntax/v3'
    with pytest.raises(ValueError, match='closed reviewed'):
        inference._read_reviewed_evaluation_request(write())
    assert not Path(value['output_directory']).exists()


@pytest.fixture(scope='module')
def parent_candidate_audit_seed():
    from copy import deepcopy
    from tests.unit.optimizers.logic_theorem_optimizer import test_legal_ir_evaluation_artifacts as bridge
    options, rows, known, _ = bridge._candidate_audit_fixture()
    evaluation = bridge._producer_evaluate(options, lambda _: bridge._producer_exact_outputs(rows)).to_dict()
    # Only declaration-derived known facts, not copied reference target fields.
    contexts = dict(profile='reviewed-source-selection-context/v2',
        selection_context=deepcopy(known[rows[0]['id']]['known_selection_context']),
        rows=[dict(id=r['id'], unit_id=r['unit_id'],
            source_binding=deepcopy(known[r['id']]['known_source_binding']),
            governing_context=deepcopy(known[r['id']]['known_governing_context'])) for r in rows])
    return rows, evaluation, contexts


@pytest.mark.parametrize('damage', [None, 'missing-contexts', 'source-fact', 'selection', 'order',
    'unit-id', 'extra', 'metrics', 'output-join', 'checkpoint', 'context-bytes', 'batch-error'])
def test_reviewed_parent_candidate_audit_binds_independent_original_artifacts(tmp_path, parent_candidate_audit_seed, damage):
    from copy import deepcopy
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_semantic_metrics as metrics
    rows, evaluation, contexts = deepcopy(parent_candidate_audit_seed)
    payload = evaluation['compiler_artifact']['reviewed_source_span_producer_evaluation']
    generation = {'last_call': {'completed': True, 'raw_generation_outputs': deepcopy(payload['producer_outputs'])}}
    checkpoints = deepcopy(payload['configuration']['checkpoint_declarations'])
    if damage == 'source-fact': contexts['rows'][0]['source_binding']['document_revision'] = 'fixture:different'
    elif damage == 'selection': contexts['selection_context']['interpretation_id'] = 'fixture:different'
    elif damage == 'order': contexts['rows'].reverse()
    elif damage == 'unit-id': contexts['rows'][0]['unit_id'] = 'fixture:different'
    elif damage == 'extra': contexts['reference_target'] = rows[0]['canonical_ir']
    elif damage == 'metrics': evaluation['metrics']['complete_norm_payload']['denominator'] = 999
    elif damage == 'output-join': generation['last_call']['raw_generation_outputs'][0]['outcome'] = 'incomplete'
    elif damage == 'checkpoint': checkpoints['decoder']['sha256'] = '0' * 64
    elif damage == 'batch-error':
        for output in payload['producer_outputs']: output.update(candidate=None, outcome='error')
        payload['producer_exception_type'] = 'RuntimeError'
        exact = metrics.evaluate_complete_norm_payloads([dict(case_id=r['id'], reference=r['canonical_ir'],
            candidate=o['candidate'], outcome=o['outcome']) for r, o in zip(rows, payload['producer_outputs'], strict=True)])
        payload['comparison'] = exact; evaluation['metrics']['complete_norm_payload'] = deepcopy(exact)
        generation['last_call'].update(completed=False, raw_generation_outputs=None, exception_type='RuntimeError',
            entry_pair_match=True, exit_pair_match=True, closeout_exception_type=None)
    def save(name, value):
        path = tmp_path / (name + '.json');path.write_bytes(worker._json_bytes(value))
        return dict(path=str(path), bytes=path.stat().st_size, sha256=_sha(path))
    artifacts = {name: save(name, value) for name, value in [('evaluation', evaluation), ('generation', generation), ('loader', {})]}
    request = dict(rows_artifact=save('rows', rows), checkpoint_declarations=checkpoints,
        source_contexts_artifact=save('contexts', contexts))
    cycle = dict(output_artifacts=artifacts);cycle_ref = worker.CheckpointArtifact.from_dict(save('cycle', cycle))
    if damage == 'missing-contexts': request.pop('source_contexts_artifact')
    elif damage == 'context-bytes': Path(request['source_contexts_artifact']['path']).write_text('{}\n')
    profile = 'unreviewed-complete-norm-candidate-syntax/v3'
    if damage not in (None, 'batch-error'):
        with pytest.raises(ValueError):
            inference._build_parent_candidate_syntax_audit(cycle, request, cycle_ref, 'a' * 64, {}, profile)
    else:
        report = inference._build_parent_candidate_syntax_audit(cycle, request, cycle_ref, 'a' * 64, {}, profile)
        assert report['profile'] == profile and report['report']['denominator'] == 3
        assert report['report']['counts']['not_checked' if damage == 'batch-error' else 'syntax_validated_unreviewed'] == 3
        assert report['source_contexts_artifact'] == request['source_contexts_artifact']
        assert report['original_output_artifacts'] == artifacts
        assert report['original_child_artifacts_modified'] is report['model_reexecuted'] is False
        assert report['native_proof_verified'] is report['legal_meaning_verified'] is report['current_admission_authority_granted'] is False
    assert not (tmp_path / 'candidate-syntax-audit.json').exists()


@pytest.mark.parametrize('typed,candidate', [(None, None), (None, 'unreviewed-complete-norm-candidate-syntax/v2'),
    ('canonical-typed-expression-wire/v1', None), ('canonical-typed-expression-wire/v1', 'unreviewed-complete-norm-candidate-syntax/v3')])
def test_reviewed_parent_candidate_audit_cli_forwards_trusted_opt_ins_only(monkeypatch, typed, candidate):
    cli = _reviewed_physical_cli(monkeypatch);marker = object();calls = []
    runtime = inference.ReviewedInferenceParentRuntime(object(), lambda: None, lambda _: None, lambda: {}, 1.0,
        typed_structure_profile=typed, candidate_syntax_profile=candidate)
    def route(*args, **kwargs): calls.append(kwargs);return marker
    monkeypatch.setattr(inference, 'run_reviewed_source_inference_cycle', route)
    assert cli.supervised_cycle({'reviewed_evaluation_request': {}}, reviewed_parent_runtime=runtime) is marker
    assert calls[0].get('typed_structure_profile') == typed
    assert calls[0].get('candidate_syntax_profile') == candidate
    assert ('candidate_syntax_profile' in calls[0]) is (candidate is not None)


def test_reviewed_parent_candidate_audit_source_pins_are_canonical_metadata_only():
    pins = inference._parent_candidate_syntax_source_pins()
    root = Path(inference.__file__).resolve().parents[3]
    assert 0 < len(pins) <= 256
    assert any(path.endswith('/legal_norm_content_adjudication_v1.py') for path in pins)
    assert any(path.endswith('/native_family_lean_emitters.py') for path in pins)
    for path, digest in pins.items():
        assert Path(path).resolve().is_relative_to(root)
        assert _sha(path) == digest


@pytest.mark.parametrize('charged,limit,sizes,accepted', [(100,120,[12,12],False),
    (100,124,[12,12],True), (121,120,[],False)])
def test_reviewed_parent_candidate_audit_quota_retains_prior_charges(charged, limit, sizes, accepted):
    usage = dict(total_attempt_charged_bytes=charged, attempt_limit_bytes=limit, attempt_live_bytes=1)
    wires = [b'x' * n for n in sizes]
    if accepted: inference._check_parent_audit_storage(usage, wires)
    else:
        with pytest.raises(ValueError, match='storage promise'):
            inference._check_parent_audit_storage(usage, wires)


def test_reviewed_parent_candidate_audit_keeps_individual_output_bound(monkeypatch):
    monkeypatch.setattr(inference, 'REVIEWED_EVALUATION_OUTPUT_LIMIT', 8)
    with pytest.raises(ValueError, match='output bound'):
        inference._check_parent_audit_storage(dict(total_attempt_charged_bytes=0, attempt_limit_bytes=100), [b'x' * 9])


@pytest.mark.parametrize('candidate', [False, True])
def test_reviewed_parent_candidate_audit_final_input_check_after_late_context_write(tmp_path, candidate):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
    def save(name, value):
        path = tmp_path / (name + '.json');path.write_bytes(worker._json_bytes(value))
        return dict(path=str(path), bytes=path.stat().st_size, sha256=_sha(path))
    request = dict(rows_artifact=save('rows', []), source_contexts_artifact=save('contexts', {'declared': True}))
    reference = worker.CheckpointArtifact.from_dict(save('request', request))
    # Simulate a last caller callback overwriting independent known facts.
    Path(request['source_contexts_artifact']['path']).write_text('{}\n')
    if candidate:
        with pytest.raises(ValueError):
            inference._check_parent_audit_inputs(request, reference, candidate=True)
    else:
        inference._check_parent_audit_inputs(request, reference, candidate=False)


# Explicit source-conditioned Qwen budgets are request DATA.  These controls use
# the existing closed request fixtures; they do not load a model or authorize it.
@pytest.mark.parametrize("transport", ["shared_json_v2", "shared_json_v3"])
@pytest.mark.parametrize("budget", [8192, 16384])
def test_reviewed_inference_Qwen2_explicit_context_profile_request(tmp_path, monkeypatch, transport, budget):
    import builtins
    worker, consumer, value, write = _reviewed_Qwen2_request_data(tmp_path, rich=True)
    profile = f"qwen2-full-context-{budget}/v1"
    value["generation_policy"]["context_budget_profile"] = profile
    value["training_context"].update(transport=transport, context_budget_profile=profile)
    original = builtins.__import__
    def no_native(name, *args, **kwargs):
        if name.split(".", 1)[0] in {"torch", "transformers", "tokenizers"}:
            pytest.fail("frontend request DATA imported a native model")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", no_native)
    reference = write()
    loaded, raw, request = inference._read_reviewed_evaluation_request(reference)
    assert asdict(loaded) == reference and request == value == worker._parse_json(raw)
    assert request["training_context"]["profile"] == consumer.REVIEWED_V3_HELDOUT_CONTEXT_PROFILE
    assert not Path(value["output_directory"]).exists()


@pytest.mark.parametrize("damage", ["request-profile-mismatch", "generation-profile-mismatch", "unknown-profile",
    "boolean-profile", "aggregate-profile", "v1-transport", "uncommitted-target", "missing-budget"])
def test_reviewed_inference_Qwen2_expanded_request_still_binds_closed_context(tmp_path, damage):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_structured_retrieval as structured
    _, consumer, value, write = _reviewed_Qwen2_request_data(tmp_path, rich=True)
    value["generation_policy"]["context_budget_profile"] = "qwen2-full-context-16384/v1"
    value["training_context"].update(transport="shared_json_v3", context_budget_profile="qwen2-full-context-16384/v1")
    if damage == "request-profile-mismatch": value["training_context"]["context_budget_profile"] = "qwen2-full-context-8192/v1"
    elif damage == "generation-profile-mismatch": value["generation_policy"]["context_budget_profile"] = "qwen2-full-context-8192/v1"
    elif damage == "unknown-profile": value["training_context"]["context_budget_profile"] = "qwen2-full-context-16384/v2"
    elif damage == "boolean-profile": value["training_context"]["context_budget_profile"] = True
    elif damage == "aggregate-profile": value["training_context"]["profile"] = structured.AGGREGATE_CONTEXT_V4_PROFILE
    elif damage == "v1-transport": value["training_context"]["transport"] = "shared_json_v1"
    elif damage == "uncommitted-target": value["training_context"]["target_json"] = {"shall": "leak"}
    else: value["training_context"].pop("context_budget_profile")
    with pytest.raises(ValueError): inference._read_reviewed_evaluation_request(write())
    assert not Path(value["output_directory"]).exists()


def _reviewed_frontend_selected_shared_policy(budget, transport):
    from ipfs_datasets_py.logic.autoformal import training_cycle_inputs as inputs
    context = {"transport": transport}
    policy = {"schema": "reviewed-decoder-rich-context-use-policy/v2", "context_transport": transport,
        "shared_context_schema": inputs.REVIEWED_SHARED_CONTEXT_JSON_SCHEMA_V3 if transport == "shared_json_v3" else inputs.REVIEWED_SHARED_CONTEXT_JSON_SCHEMA_V2,
        "max_expanded_context_bytes": inputs.REVIEWED_SHARED_CONTEXT_MAX_EXPANDED_BYTES,
        "max_context_bytes": 16384, "max_context_tokens": budget}
    if budget != 4096:
        context["context_budget_profile"] = policy["context_budget_profile"] = f"qwen2-full-context-{budget}/v1"
        policy["schema"] = "reviewed-decoder-rich-context-use-policy/v3"
    return context, policy


@pytest.mark.parametrize("budget,transport", [(4096, "shared_json_v3"), (8192, "shared_json_v2"),
    (8192, "shared_json_v3"), (16384, "shared_json_v2"), (16384, "shared_json_v3")])
def test_reviewed_inference_selected_shared_context_policy_keeps_numeric_and_codec_identity(budget, transport):
    context, policy = _reviewed_frontend_selected_shared_policy(budget, transport)
    assert inference._check_reviewed_context_transport_policy(context, policy) is None
    assert policy["max_context_tokens"] == budget and policy["max_context_bytes"] == 16384


@pytest.mark.parametrize("damage", ["old-codec", "transport-mismatch", "old-token-cap", "boolean-token-cap",
    "expanded-byte-cap", "wire-byte-cap", "profile-mismatch", "unknown-request-profile", "schema-downgrade", "implicit-profile"])
def test_reviewed_inference_expanded_shared_policy_refuses_mismatched_commitments(damage):
    from ipfs_datasets_py.logic.autoformal import training_cycle_inputs as inputs
    context, policy = _reviewed_frontend_selected_shared_policy(16384, "shared_json_v3")
    if damage == "old-codec": policy["shared_context_schema"] = inputs.REVIEWED_SHARED_CONTEXT_JSON_SCHEMA_V2
    elif damage == "transport-mismatch": policy["context_transport"] = "shared_json_v2"
    elif damage == "old-token-cap": policy["max_context_tokens"] = 8192
    elif damage == "boolean-token-cap": policy["max_context_tokens"] = True
    elif damage == "expanded-byte-cap": policy["max_expanded_context_bytes"] += 1
    elif damage == "wire-byte-cap": policy["max_context_bytes"] += 1
    elif damage == "profile-mismatch": policy["context_budget_profile"] = "qwen2-full-context-8192/v1"
    elif damage == "unknown-request-profile": context["context_budget_profile"] = "qwen2-full-context-16384/v2"
    elif damage == "schema-downgrade": policy["schema"] = "reviewed-decoder-rich-context-use-policy/v2"
    else: context.pop("context_budget_profile")
    with pytest.raises(ValueError): inference._check_reviewed_context_transport_policy(context, policy)


@pytest.mark.parametrize("kind", ["load", "producer"])
@pytest.mark.parametrize("budget", [8192, 16384])
def test_reviewed_inference_Qwen2_current_parent_policy_preserves_explicit_generation_profile(tmp_path, kind, budget):
    worker, request, policy = _reviewed_Qwen2_parent_policy_data(tmp_path, kind)
    request["generation_policy"]["context_budget_profile"] = f"qwen2-full-context-{budget}/v1"
    if kind == "producer": policy["generation_policy"] = json.loads(worker._json_bytes(request["generation_policy"]))
    assert inference._check_reviewed_generation_policy(request, policy) is None
    if kind == "producer":
        policy["generation_policy"]["context_budget_profile"] = f"qwen2-full-context-{16384 if budget == 8192 else 8192}/v1"
        with pytest.raises(ValueError): inference._check_reviewed_generation_policy(request, policy)


@pytest.mark.parametrize("damage", [None, "legacy-domain", "aggregate-profile"])
def test_reviewed_inference_generic_v3_transport_remains_single_component_request(tmp_path, damage):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_structured_retrieval as structured
    _, consumer, value, write = _reviewed_mixed_rich_request_data(tmp_path)
    value["training_context"]["transport"] = "shared_json_v3"
    if damage == "legacy-domain":
        value["schema"] = "reviewed-source-evaluation-request/v2"
        value.pop("admission_profile")
        value["heldout_evaluation_purpose"] = consumer.REVIEWED_HELDOUT_CONTEXT_PURPOSE
        value["training_context"]["profile"] = consumer.REVIEWED_HELDOUT_CONTEXT_PROFILE
    elif damage == "aggregate-profile": value["training_context"]["profile"] = structured.AGGREGATE_CONTEXT_V4_PROFILE
    if damage is None:
        _, _, request = inference._read_reviewed_evaluation_request(write())
        assert request == value and "context_budget_profile" not in request["training_context"]
    else:
        with pytest.raises(ValueError): inference._read_reviewed_evaluation_request(write())
    assert not Path(value["output_directory"]).exists()


# Explicit v11 software controls. Metadata-only cases do not establish a real
# local-vendor pair; the physical case uses the existing tiny fictional assets.
def _reviewed_v11_tuple(worker, request):
    request.update(schema=inference.REVIEWED_DIGEST_OMITTED_EVALUATION_REQUEST_SCHEMA,
        runtime_profile="builtin-qwen2-bfloat16/v1")
    request["generation_policy"].update(schema=worker.REVIEWED_DIGEST_OMITTED_GENERATION_POLICY_SCHEMA,
        conditioning_profile=worker.REVIEWED_DIGEST_OMITTED_CHATML_PROFILE,
        target_codec=worker.REVIEWED_DIGEST_OMITTED_TARGET_CODEC)
    request["backend_identity"] = {"backend_id": "torch-digest-omitted-reviewed-decoder/v1:" + "a" * 64,
        "implementation_sha256": request["source_sha256"]["worker"],
        "checkpoint_format": "torch-weights-only-digest-omitted-reviewed-state-pair/v1",
        "target_codec": worker.REVIEWED_DIGEST_OMITTED_TARGET_CODEC,
        "source_conditioned": True, "pretrained": False}


def _reviewed_v11_request_data(tmp_path):
    worker, consumer, value, write = _reviewed_Qwen2_request_data(tmp_path)
    _reviewed_v11_tuple(worker, value)
    return worker, consumer, value, write


@pytest.mark.parametrize("damage", [None, "old_request", "old_policy", "old_prompt", "old_codec", "old_pair",
    "old_backend", "implementation", "runtime", "rich_context", "target", "extra", "source_cap", "output_cap"])
def test_reviewed_inference_v11_request_tuple_is_explicit_before_assets(tmp_path, monkeypatch, damage):
    import builtins
    worker, _, value, write = _reviewed_v11_request_data(tmp_path)
    # The largest existing metadata capacities stay available; actual backend
    # position and complete-context checks remain authoritative at runtime.
    value.update(max_source_tokens=65536, max_output_tokens=65536, max_model_bytes=2 * 1024**3)
    if damage == "old_request": value["schema"] = "reviewed-source-evaluation-request/v9"
    elif damage == "old_policy": value["generation_policy"]["schema"] = "reviewed-decoder-generation-policy/v2"
    elif damage == "old_prompt": value["generation_policy"]["conditioning_profile"] = "qwen2-chatml-complete-legal-ir/v1"
    elif damage == "old_codec": value["generation_policy"]["target_codec"] = "complete-reviewed-norm-json/v2"
    elif damage == "old_pair": value["backend_identity"]["checkpoint_format"] = "torch-weights-only-reviewed-state-pair/v1"
    elif damage == "old_backend": value["backend_identity"]["backend_id"] = "torch-reviewed-decoder/v1:" + "a" * 64
    elif damage == "implementation": value["backend_identity"]["implementation_sha256"] = "b" * 64
    elif damage == "runtime": value["runtime_profile"] = "builtin-llama-bfloat16/v1"
    elif damage == "rich_context": value["training_context"] = {}
    elif damage == "target": value["target_json"] = {"hidden": "not an input"}
    elif damage == "extra": value["generation_policy"]["repair"] = True
    elif damage == "source_cap": value["max_source_tokens"] = 65537
    elif damage == "output_cap": value["max_output_tokens"] = 65537
    ref = write()
    original_import = builtins.__import__
    def no_assets(name, *args, **kwargs):
        if name.split(".")[0] in {"torch", "transformers", "tokenizers"}:
            raise AssertionError("request DATA validation imported a model runtime")
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", no_assets)
    if damage is None:
        assert inference._read_reviewed_evaluation_request(ref)[2] == value
    else:
        with pytest.raises((ValueError, worker.TrainingJobValidationError)):
            inference._read_reviewed_evaluation_request(ref)
    assert not Path(value["assets"]["model_checkpoint"]["path"]).exists()


@pytest.mark.parametrize("version", range(1, 11))
def test_reviewed_inference_old_versions_refuse_new_codec_identity(tmp_path, version):
    worker, _, value, write = _reviewed_v11_request_data(tmp_path)
    value["schema"] = "reviewed-source-evaluation-request/v" + str(version)
    if version < 7: value.pop("generation_policy")
    else:
        from tests.unit.optimizers.logic_theorem_optimizer import test_autoencoder_training_worker as numerical
        value["generation_policy"] = numerical._reviewed_Qwen2_generation_policy() if version >= 9 else {
            "schema": "reviewed-decoder-generation-policy/v1", "generation_profile": "builtin-llama-dynamic-kv/v1",
            "conditioning_profile": "chatml-complete-legal-ir/v1", "max_generation_seconds": 1.0}
    if version < 5: value.pop("runtime_profile")
    elif version < 9: value["runtime_profile"] = "builtin-llama-bfloat16/v1"
    if version < 3: value.pop("admission_profile")
    if version in {2, 4, 6, 8, 10}: value["training_context"] = {}
    with pytest.raises((ValueError, worker.TrainingJobValidationError)):
        inference._read_reviewed_evaluation_request(write())


def _reviewed_v11_parent_policy_data(tmp_path, kind):
    worker, request, policy = _reviewed_Qwen2_parent_policy_data(tmp_path, kind)
    _reviewed_v11_tuple(worker, request)
    policy["backend_identity"] = json.loads(worker._json_bytes(request["backend_identity"]))
    if kind == "load":
        policy.update(schema="reviewed-local-digest-omitted-decoder-load-policy/v1",
            target_codec=worker.REVIEWED_DIGEST_OMITTED_TARGET_CODEC)
    else:
        policy.update(schema="reviewed-decoder-digest-omitted-source-producer-policy/v1",
            generation_policy=json.loads(worker._json_bytes(request["generation_policy"])),
            output_derivation={"schema": "reviewed-digest-omitted-output-assembly/v1",
                "target_codec": worker.REVIEWED_DIGEST_OMITTED_TARGET_CODEC,
                "only_computed_field": "typed_expression.content_digest", "other_default_filling": False})
    return worker, request, policy


@pytest.mark.parametrize("kind", ["load", "producer"])
@pytest.mark.parametrize("damage", [None, "schema", "identity", "source", "asset", "extra", "objective"])
def test_reviewed_inference_v11_parent_callback_exact_objective_and_scope(tmp_path, kind, damage):
    worker, request, policy = _reviewed_v11_parent_policy_data(tmp_path, kind)
    if damage == "schema": policy["schema"] = "reviewed-local-decoder-load-policy/v2" if kind == "load" else "reviewed-decoder-source-producer-policy/v4"
    elif damage == "identity": policy["backend_identity"]["checkpoint_format"] = "torch-weights-only-reviewed-state-pair/v1"
    elif damage == "source":
        if kind == "load": policy["producer_pins"] = {**policy["producer_pins"], "worker": "b" * 64}
        else: policy["source_contexts_sha256"] = "b" * 64
    elif damage == "asset": policy["assets"][0] = {**policy["assets"][0], "sha256": "b" * 64}
    elif damage == "extra": policy["hidden_target"] = {}
    elif damage == "objective":
        if kind == "load": policy["target_codec"] = "complete-reviewed-norm-json/v2"
        else: policy["output_derivation"]["other_default_filling"] = True
    if damage is None:
        inference._check_reviewed_generation_policy(request, policy)
    else:
        with pytest.raises(ValueError): inference._check_reviewed_generation_policy(request, policy)


@pytest.mark.parametrize("kind", ["load", "producer"])
def test_reviewed_inference_old_callback_cannot_admit_digest_omitted_policy(tmp_path, kind):
    worker, request, policy = _reviewed_Qwen2_parent_policy_data(tmp_path, kind)
    request["generation_policy"].update(schema=worker.REVIEWED_DIGEST_OMITTED_GENERATION_POLICY_SCHEMA,
        conditioning_profile=worker.REVIEWED_DIGEST_OMITTED_CHATML_PROFILE, target_codec=worker.REVIEWED_DIGEST_OMITTED_TARGET_CODEC)
    if kind == "producer": policy["generation_policy"] = json.loads(worker._json_bytes(request["generation_policy"]))
    with pytest.raises(ValueError, match="explicit v11"):
        inference._check_reviewed_generation_policy(request, policy)


def _reviewed_v11_bind_saved_source_control(worker, inputs, request, generation, offered, *, reference_target):
    """Build the fictional source commitments independently of the saved outputs."""
    call = generation["last_call"]
    receipt = call["input_receipt"]
    tokenizer = receipt["tokenizer_contract"]
    profile = "reviewed-source-selection-context/v2"
    selection = {"schema": "caller-known-interpretation-selection/v1",
        "interpretation_id": "fixture:interpretation", "selection_mode": "identifier_only"}
    governing = {"jurisdiction": "fixture:jurisdiction", "instrument_id": "fixture:instrument",
        "governing_edition": "fixture:edition", "legal_as_of_utc": "2025-01-01T00:00:00Z",
        "valid_from_utc": "2025-01-01T00:00:00Z", "valid_until_utc": None}
    rows, arguments, records, row_commitments = [], [], [], []
    for identity, unit in offered:
        binding = {"source_version_cid": "fixture:version", "occurrence_cid": unit,
            "document_revision": "fixture:revision"}
        rows.append({"id": identity, "unit_id": unit, "governing_context": governing,
            "source_binding": binding})
        source_text = f"Fictional saved-output control for {unit}."
        arguments.append({"id": identity, "source_text": source_text,
            "context": {"permitted": [], "retrieved": []}})
        wire = inputs._reviewed_wire({"profile": profile, "source_text": source_text,
            "governing_context": governing, "source_binding": binding, "selection_context": selection})
        tokens = [tokenizer["bos_token_id"], *wire, tokenizer["eos_token_id"]]
        records.append({"id": identity, "unit_id": unit, "source_wire": wire.decode("utf-8"),
            "source_token_ids": tokens})
        row_commitments.append({"id": identity, "unit_id": unit,
            "source_text_sha256": worker._digest(source_text.encode("utf-8")),
            "source_wire_sha256": worker._digest(wire),
            "source_token_ids_sha256": worker._digest(inputs._reviewed_wire(tokens))})

    references = [{"id": argument["id"], "source_text": argument["source_text"],
        "canonical_ir": reference_target} for argument in arguments]
    references_raw = worker._json_bytes(references)
    reference_path = Path(request["source_contexts_artifact"]["path"]).with_name("selected-rows.json")
    reference_path.write_bytes(references_raw)
    request["rows_artifact"] = {"path": str(reference_path), "bytes": len(references_raw),
        "sha256": worker._digest(references_raw)}
    contexts = {"profile": profile, "selection_context": selection, "rows": rows}
    contexts_raw = inputs._reviewed_wire(contexts)
    path = Path(request["source_contexts_artifact"]["path"])
    path.write_bytes(contexts_raw)
    contexts_sha = worker._digest(contexts_raw)
    request["source_contexts_artifact"] = {"path": str(path), "bytes": len(contexts_raw), "sha256": contexts_sha}
    commitment = generation["input_commitment"]
    commitment["source_contexts_sha256"] = contexts_sha
    generation["input_profile_id"] = "reviewed-decoder-digest-omitted-producer/v1:" + worker._digest(inputs._reviewed_wire(commitment))
    call["source_arguments_sha256"] = worker._digest(inputs._reviewed_wire(arguments))
    call["source_records_sha256"] = worker._digest(inputs._reviewed_wire(records))
    receipt.update(schema="reviewed-decoder-generation-input-receipt/v1",
        profile="source-only-reviewed-decoder-generation-inputs/v1",
        source_profile=profile, record_count=len(offered), source_contexts_sha256=contexts_sha,
        source_arguments_sha256=call["source_arguments_sha256"],
        selection_context_sha256=worker._digest(inputs._reviewed_wire(selection)),
        prepared_records_sha256=call["source_records_sha256"], row_commitments=row_commitments,
        max_source_tokens=request["max_source_tokens"], supplied_examples="empty_only",
        **dict.fromkeys(("semantic_selection_supported", "source_facts_authenticated",
            "current_admission_replayed", "backend_execution_authorized", "target_access_performed",
            "training_stage_access_performed", "proof_authority", "corpus_admitted"), False))


def _reviewed_v11_saved_evaluation(worker, inputs, request, generation):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_semantic_metrics as metrics

    rows = json.loads(Path(request["rows_artifact"]["path"]).read_bytes())
    arguments = [{"id": row["id"], "source_text": row["source_text"],
        "context": {"permitted": [], "retrieved": []}} for row in rows]
    outputs = generation["last_call"]["producer_outputs"]
    output_by_id = {item["id"]: item for item in outputs}
    # For malformed generation controls, the saved report is still only
    # a bookkeeping fixture. The terminal checks must refuse those first.
    cases = []
    for row in rows:
        result = output_by_id.get(row["id"], {"candidate": None, "outcome": "incomplete"})
        cases.append({"case_id": row["id"], "reference": row["canonical_ir"],
            "candidate": result["candidate"], "outcome": result["outcome"]})
    comparison = metrics.evaluate_complete_norm_payloads(cases)
    payload = {"configuration": {"checkpoint_declarations": request["checkpoint_declarations"]},
        "reference_population": rows, "producer_arguments": arguments, "producer_outputs": outputs,
        "declared_compiler_identity": request["compiler_commit"], "comparison": comparison}
    return {"schema_version": "legal-ir-evaluation-artifact-v1",
        "compiler_artifact": {"reviewed_source_span_producer_evaluation": payload},
        "metrics": {"complete_norm_payload": comparison},
        "metadata": {"source_generation_observation": generation,
            "source_generation_input_commitment_sha256": worker._digest(inputs._reviewed_wire(generation["input_commitment"]))}}


def _reviewed_v11_saved_control(tmp_path, disposition, *, model_vocab_padding=0, model_eos=None):
    from tests.unit.optimizers.logic_theorem_optimizer import test_autoencoder_training_worker as numerical
    worker, request, policy = _reviewed_v11_parent_policy_data(tmp_path, "producer")
    inputs, codec, target = numerical._digest_omitted_small_generation_target()
    full_text = inputs.encode_reviewed_decoder_digest_omitted_target(target, target_codec=codec)
    body = list(full_text.encode("utf-8"))
    request["max_output_tokens"] = policy["max_output_tokens"] = len(body) + 3
    bos, eos, vocab = 256, 257, 258
    config = tmp_path / "model-config.json"
    config.write_bytes(worker._json_bytes({
        "model_type": "qwen2",
        "vocab_size": vocab + model_vocab_padding,
        "bos_token_id": bos,
        "eos_token_id": eos if model_eos is None else model_eos,
    }))
    request["assets"]["model_config_artifact"] = {
        "path": str(config), "bytes": config.stat().st_size, "sha256": _sha(config),
    }
    policy["assets"] = [request["assets"][name] for name in (
        "recipe_artifact", "model_config_artifact", "tokenizer_artifact", "license_artifact",
    )]
    outcomes = {
        "complete": ("complete", [bos, *body, eos], full_text, None),
        "abstained": ("abstained", [bos, eos], None, "empty_output"),
        "incomplete": ("incomplete", [bos], None, "generation_time_limit_without_eos"),
        "output_limit": ("incomplete", [bos] + [3] * (request["max_output_tokens"] - 1),
            None, "output_limit_without_eos"),
        "unexpected_bos": ("invalid", [bos, 3, bos], None, "unexpected_bos_in_output"),
        "invalid_no_text": ("invalid", [bos, 0xC3, eos], None, "invalid_output_transport"),
        "invalid_text": ("invalid", [bos, ord("{"), eos], "{", "invalid_complete_norm_json"),
        "invalid_empty_text": ("invalid", [bos, 3, eos], "", "invalid_complete_norm_json"),
    }
    outcome, tokens, text, reason = outcomes[disposition]
    candidate = target if outcome == "complete" else None
    raw = {"id": "fixture:source-only-row", "unit_id": "fixture:unit", "outcome": outcome,
        "candidate": candidate, "generated_token_ids": tokens, "generated_text": text, "reason": reason}
    proof = {"id": raw["id"], "raw_model_text_sha256": None if text is None else worker._digest(text.encode("utf-8")),
        "assembled_full_target_sha256": worker._digest(inputs._reviewed_wire(target)) if outcome == "complete" else None,
        "outcome": outcome, "computed_field": "typed_expression.content_digest", "other_fields_repaired": False}
    exposure = {"fixture": "independent original source-only exposure"}
    path = tmp_path / "exposure.json"; path.write_bytes(worker._json_bytes(exposure))
    request["exposure_artifact"] = {"path": str(path), "bytes": path.stat().st_size, "sha256": _sha(path)}
    commitment = {**policy, "source_sha256": request["source_sha256"],
        "exposure_sha256": worker._digest(inputs._reviewed_wire(exposure)),
        "supplied_context_supported": "empty_permitted_and_retrieved_only"}
    # Fictional saved tokenizer DATA only. No tokenizer is loaded or called.
    pipeline = b"Fictional UTF-8 byte-domain control"
    tokenizer = {"schema": "reviewed-decoder-tokenizer-contract/v2",
        "bos_token_id": bos, "eos_token_id": eos, "vocab_size": vocab,
        "pipeline_kind": "fictional_fixed_byte", "pipeline_sha256": worker._digest(pipeline),
        "pipeline_bytes": len(pipeline)}
    generation = {"schema": "reviewed-decoder-digest-omitted-source-producer-observation/v1",
        "input_commitment": commitment,
        "last_call": {"completed": True, "entry_pair_match": True, "exit_pair_match": True,
            "exception_type": None, "input_receipt": {"tokenizer_contract": tokenizer},
            "raw_generation_outputs": [raw],
            "producer_outputs": [{key: raw[key] for key in ("id", "outcome", "candidate")}],
            "output_derivation": [proof]}}
    _reviewed_v11_bind_saved_source_control(worker, inputs, request, generation, [(raw["id"], raw["unit_id"])],
        reference_target=target)
    request.setdefault("compiler_commit", "fixture:compiler")
    request["checkpoint_declarations"] = {
        "encoder": {"id": "fixture:encoder", "sha256": "a" * 64},
        "decoder": {"id": request["backend_identity"]["backend_id"], "sha256": request["assets"]["model_checkpoint"]["sha256"]},
    }
    loader = {"schema": "reviewed-local-digest-omitted-decoder-runtime-load/v1", "target_codec": codec,
        "expected_backend_identity": request["backend_identity"], "loaded_backend_identity": request["backend_identity"],
        "producer_pins": request["source_sha256"], "artifacts": [request["assets"][key] for key in
            ("recipe_artifact", "model_config_artifact", "tokenizer_artifact", "license_artifact", "model_checkpoint", "optimizer_checkpoint")],
        "runtime_profile": request["runtime_profile"], "device": "cpu", "dtype": "bfloat16", "optimizer_steps": 0,
        **{key: True for key in ("checkpoint_restored", "matched_pair", "load_performed", "restore_performed")},
        **{key: False for key in ("training_performed", "downloads_performed", "resource_granted", "automatic_old_source_checkpoint_migration",
            "old_objective_checkpoint_migration_performed", "license_bytes_are_permission", "pretrained_quality_verified", "legal_meaning_verified",
            "proof_authority", "convergence_proved", "corpus_admitted")}}
    output = tmp_path / "outputs"; output.mkdir(); request["output_directory"] = str(output)
    def write():
        paths, descriptors = {}, {}
        evaluation = _reviewed_v11_saved_evaluation(worker, inputs, request, generation)
        for name, value in (("evaluation", evaluation), ("loader", loader), ("generation", generation)):
            path = output / (name + ".json"); path.write_bytes(worker._json_bytes(value))
            paths[name] = str(path); descriptors[name] = {"path": str(path), "bytes": path.stat().st_size, "sha256": _sha(path)}
        return {"output_artifacts": descriptors, "inference": {"profile": request["schema"], **paths}}
    return worker, inputs, request, generation, loader, write


@pytest.mark.parametrize("disposition", ["abstained", "incomplete", "invalid_no_text", "invalid_text", "complete"])
def test_reviewed_inference_v11_saved_raw_assembled_dispositions_preserved(tmp_path, disposition):
    worker, _, request, generation, _, write = _reviewed_v11_saved_control(tmp_path, disposition)
    # Controlled token IDs are bookkeeping fixtures, not an assertion that the
    # tokenizer produced them. The original-owner test covers actual generation.
    original = worker._json_bytes(generation)
    cycle = write(); before = {name: Path(ref["path"]).read_bytes() for name, ref in cycle["output_artifacts"].items()}
    inference._check_reviewed_evaluation_outputs(cycle, request)
    assert worker._json_bytes(generation) == original
    assert all(Path(cycle["output_artifacts"][name]["path"]).read_bytes() == raw for name, raw in before.items())
    proof = generation["last_call"]["output_derivation"][0]
    assert (proof["raw_model_text_sha256"] is None) == (generation["last_call"]["raw_generation_outputs"][0]["generated_text"] is None)
    assert (proof["assembled_full_target_sha256"] is not None) == (disposition == "complete")


@pytest.mark.parametrize("damage", ["raw_hash", "null_as_empty", "candidate_rewrite", "supplied_digest", "derivation", "population",
    "tokens", "profile", "observation", "loader_schema", "loader_pair", "loader_authority", "source", "exposure", "commitment_extra"])
def test_reviewed_inference_v11_saved_output_refuses_raw_derivation_or_scope_changes(tmp_path, damage):
    worker, inputs, request, generation, loader, write = _reviewed_v11_saved_control(tmp_path, "complete" if damage in {"candidate_rewrite", "supplied_digest"} else "incomplete")
    raw = generation["last_call"]["raw_generation_outputs"][0]
    output = generation["last_call"]["producer_outputs"][0]
    proof = generation["last_call"]["output_derivation"][0]
    if damage == "raw_hash": proof["raw_model_text_sha256"] = "b" * 64
    elif damage == "null_as_empty": proof["raw_model_text_sha256"] = worker._digest(b"")
    elif damage == "candidate_rewrite":
        changed = json.loads(inputs._reviewed_wire(raw["candidate"]))
        changed["typed_expression"]["expression_id"] += ":changed"
        raw["candidate"] = output["candidate"] = changed
        proof["assembled_full_target_sha256"] = worker._digest(inputs._reviewed_wire(changed))
    elif damage == "supplied_digest":
        body = json.loads(raw["generated_text"])
        body["typed_expression"]["content_digest"] = raw["candidate"]["typed_expression"]["content_digest"]
        raw["generated_text"] = inputs._reviewed_wire(body).decode("utf-8")
        proof["raw_model_text_sha256"] = worker._digest(raw["generated_text"].encode("utf-8"))
    elif damage == "derivation": proof["other_fields_repaired"] = True
    elif damage == "population": generation["last_call"]["producer_outputs"] = []
    elif damage == "tokens": raw["generated_token_ids"] = [True]
    elif damage == "profile": generation["input_profile_id"] = "reviewed-decoder-digest-omitted-producer/v1:" + "b" * 64
    elif damage == "observation": generation["schema"] = "reviewed-decoder-source-producer-observation/v4"
    elif damage == "loader_schema": loader["schema"] = "reviewed-local-decoder-runtime-load/v3"
    elif damage == "loader_pair": loader["matched_pair"] = False
    elif damage == "loader_authority": loader["proof_authority"] = True
    elif damage == "source": generation["input_commitment"]["source_sha256"] = {**request["source_sha256"], "worker": "b" * 64}
    elif damage == "exposure": generation["input_commitment"]["exposure_sha256"] = "b" * 64
    elif damage == "commitment_extra": generation["input_commitment"]["hidden_target"] = {"forbidden": True}
    if damage in {"source", "exposure", "commitment_extra"}:
        generation["input_profile_id"] = "reviewed-decoder-digest-omitted-producer/v1:" + worker._digest(inputs._reviewed_wire(generation["input_commitment"]))
    with pytest.raises((ValueError, worker.TrainingJobValidationError)):
        inference._check_reviewed_evaluation_outputs(write(), request)


@pytest.mark.parametrize(("disposition", "damage"), [
    pytest.param("output_limit", None, id="real-token-exhaustion"),
    pytest.param("unexpected_bos", None, id="real-unexpected-bos"),
    pytest.param("invalid_empty_text", None, id="empty-decoded-body"),
    pytest.param("complete", "missing-eos", id="complete-without-eos"),
    pytest.param("complete", "early-eos", id="complete-with-early-eos"),
    pytest.param("complete", "wrong-bos", id="complete-with-wrong-bos"),
    pytest.param("complete", "outside-vocab", id="complete-outside-vocab"),
    pytest.param("abstained", "false-abstention", id="false-abstention"),
    pytest.param("incomplete", "incomplete-with-eos", id="false-incomplete-with-eos"),
    pytest.param("incomplete", "false-token-budget", id="false-token-budget"),
    pytest.param("complete", "valid-body-called-invalid", id="valid-body-called-invalid"),
    pytest.param("complete", "missing-tokenizer-receipt", id="missing-tokenizer-receipt"),
    pytest.param("complete", "model-eos", id="receipt-eos-disagrees-with-pinned-config"),
    pytest.param("complete", "padded-vocab", id="padded-model-vocab"),
])
def test_reviewed_inference_v11_saved_terminal_evidence_matches_disposition(tmp_path, disposition, damage):
    worker, _, request, generation, _, write = _reviewed_v11_saved_control(
        tmp_path, disposition, model_vocab_padding=4096 if damage == "padded-vocab" else 0,
        model_eos=255 if damage == "model-eos" else None,
    )
    call = generation["last_call"]
    raw = call["raw_generation_outputs"][0]
    output = call["producer_outputs"][0]
    proof = call["output_derivation"][0]
    tokenizer = call["input_receipt"]["tokenizer_contract"]
    bos, eos, vocab = (tokenizer[key] for key in ("bos_token_id", "eos_token_id", "vocab_size"))
    tokens = raw["generated_token_ids"]
    if damage == "missing-eos" or damage == "false-abstention":
        tokens[-1] = 3
    elif damage == "early-eos":
        tokens.insert(1, eos)
    elif damage == "wrong-bos":
        tokens[0] = 3
    elif damage == "outside-vocab":
        tokens[1] = vocab
    elif damage == "incomplete-with-eos":
        tokens.append(eos)
    elif damage == "false-token-budget":
        raw["reason"] = "output_limit_without_eos"
        raw["generated_token_ids"] = [bos, 3]
    elif damage == "valid-body-called-invalid":
        raw.update(outcome="invalid", candidate=None, reason="invalid_complete_norm_json")
        output.update(outcome="invalid", candidate=None)
        proof.update(outcome="invalid", assembled_full_target_sha256=None)
    elif damage == "missing-tokenizer-receipt":
        del call["input_receipt"]

    cycle = write()
    original = worker._json_bytes(generation)
    if damage is None or damage == "padded-vocab":
        inference._check_reviewed_evaluation_outputs(cycle, request)
    elif damage == "model-eos":
        with pytest.raises(ValueError, match="request-pinned model configuration"):
            inference._check_reviewed_evaluation_outputs(cycle, request)
    else:
        with pytest.raises(ValueError):
            inference._check_reviewed_evaluation_outputs(cycle, request)
    assert worker._json_bytes(generation) == original
    assert all(_sha(Path(ref["path"])) == ref["sha256"] for ref in cycle["output_artifacts"].values())


def test_reviewed_inference_v11_source_only_physical_original_owner(reviewed_physical_owner, monkeypatch, capsys):
    """Tiny fictional real-owner dispatch/cleanup, not vendor or quality proof."""
    facts = reviewed_physical_owner
    from tests.unit.optimizers.logic_theorem_optimizer import test_autoencoder_training_worker as numerical
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
    policy = numerical._reviewed_Qwen2_generation_policy()
    policy.update(schema=worker.REVIEWED_DIGEST_OMITTED_GENERATION_POLICY_SCHEMA,
        conditioning_profile=worker.REVIEWED_DIGEST_OMITTED_CHATML_PROFILE, target_codec=worker.REVIEWED_DIGEST_OMITTED_TARGET_CODEC)
    packet = _reviewed_physical_packet(facts, admission_version="v3", runtime_profile="builtin-qwen2-bfloat16/v1",
        generation_policy=policy, digest_omitted=True)
    assert packet.payload["schema"] == inference.REVIEWED_DIGEST_OMITTED_EVALUATION_REQUEST_SCHEMA
    cli = _reviewed_physical_cli(monkeypatch)
    assert _reviewed_physical_run(cli, facts, packet) == 0
    report = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert report["original_owner_reservation_id"] == facts.owner.reservation_id
    assert all(report[key] for key in ("parent_FINISH_acknowledged", "original_child_waited", "parent_current_admission_rechecked_after_wait", "parent_output_artifacts_rechecked_after_wait"))
    assert not report["training_executed"] and report["weight_publications"] == [] and not report["resource_release_performed"]
    output = facts.attempt / "outputs"
    cycle = json.loads((output / "cycle.json").read_bytes()); _assert_reviewed_output_artifacts(output, cycle, report)
    loader = json.loads((output / "loader.json").read_bytes())
    assert loader["schema"] == "reviewed-local-digest-omitted-decoder-runtime-load/v1" and loader["target_codec"] == worker.REVIEWED_DIGEST_OMITTED_TARGET_CODEC
    assert loader["optimizer_steps"] == 0 and loader["matched_pair"] and loader["checkpoint_restored"]
    observed = json.loads((output / "generation.json").read_bytes())
    assert observed["schema"] == "reviewed-decoder-digest-omitted-source-producer-observation/v1"
    call = observed["last_call"]
    assert call["completed"] and call["entry_pair_match"] and call["exit_pair_match"]
    assert len(call["raw_generation_outputs"]) == len(call["output_derivation"]) == 3
    for raw, derived in zip(call["raw_generation_outputs"], call["output_derivation"], strict=True):
        assert raw["outcome"] == "abstained" and raw["candidate"] is None and raw["generated_text"] is None
        assert raw["generated_token_ids"] == [packet.fixture.backend.tokenizer.bos_token_id, packet.fixture.backend.tokenizer.eos_token_id]
        assert derived["raw_model_text_sha256"] is None and derived["assembled_full_target_sha256"] is None
        assert derived["other_fields_repaired"] is False
    evaluated = json.loads((output / "evaluation.json").read_bytes())
    assert evaluated["metrics"]["complete_norm_payload"]["denominator"] == evaluated["metrics"]["complete_norm_payload"]["outcome_counts"]["abstained"] == 3
    for name, artifact in packet.payload["assets"].items():
        assert Path(artifact["path"]).read_bytes() == packet.original_assets[name]
    _reviewed_physical_assert_stopped(facts); _reviewed_physical_fsync_tree(facts.root)
    assert facts.owner.finalize(facts.attempt, artifacts_durable=True)["status"] == "released"



def _reviewed_v11_three_source_coverage_control(tmp_path):
    worker, inputs, request, generation, loader, write = _reviewed_v11_saved_control(tmp_path, "incomplete")
    call = generation["last_call"]
    offered = [("fixture:source-row:" + str(index), "fixture:unit:" + str(index)) for index in range(3)]
    for name in ("raw_generation_outputs", "producer_outputs", "output_derivation"):
        original = call[name][0]
        call[name] = [json.loads(worker._json_bytes(original)) for _ in offered]
        for row, (identity, unit) in zip(call[name], offered, strict=True):
            row["id"] = identity
            if name == "raw_generation_outputs": row["unit_id"] = unit
    reference = json.loads(Path(request["rows_artifact"]["path"]).read_bytes())[0]["canonical_ir"]
    _reviewed_v11_bind_saved_source_control(worker, inputs, request, generation, offered, reference_target=reference)
    return worker, request, generation, write, offered


@pytest.mark.parametrize("damage", [None, "drop_middle", "only_one", "coordinated_reverse", "renamed_id", "renamed_unit"])
def test_reviewed_inference_v11_outputs_cover_ordered_source_population(tmp_path, monkeypatch, damage):
    worker, request, generation, write, expected = _reviewed_v11_three_source_coverage_control(tmp_path)
    call = generation["last_call"]
    names = ("raw_generation_outputs", "producer_outputs", "output_derivation")
    if damage == "drop_middle":
        for name in names: del call[name][1]
    elif damage == "only_one":
        for name in names: del call[name][1:]
    elif damage == "coordinated_reverse":
        for name in names: call[name].reverse()
    elif damage == "renamed_id":
        for name in names: call[name][1]["id"] += ":renamed"
    elif damage == "renamed_unit": call["raw_generation_outputs"][1]["unit_id"] += ":renamed"
    observed = []
    original_reader = worker._reviewed_decoder_artifact
    def observe(reference, *args, **kwargs):
        if reference.path == request["source_contexts_artifact"]["path"]: observed.append(reference.path)
        return original_reader(reference, *args, **kwargs)
    monkeypatch.setattr(worker, "_reviewed_decoder_artifact", observe)
    original_generation = worker._json_bytes(generation)
    original_context = Path(request["source_contexts_artifact"]["path"]).read_bytes()
    if damage is None:
        inference._check_digest_omitted_generation_outputs(generation, request)
        assert [(row["id"], row["unit_id"]) for row in call["raw_generation_outputs"]] == expected
        # Also check the existing saved-byte/commitment path, without repair.
        inference._check_reviewed_evaluation_outputs(write(), request)
    else:
        with pytest.raises(ValueError, match="ordered source context"):
            inference._check_digest_omitted_generation_outputs(generation, request)
    assert observed and worker._json_bytes(generation) == original_generation
    assert Path(request["source_contexts_artifact"]["path"]).read_bytes() == original_context



@pytest.mark.parametrize("mode", ["default-user-first", "default-active-subset", "default-user-only", "explicit-user-first", "explicit-repeat"])
def test_reviewed_inference_default_child_dependency_order_uses_active_known_roots(tmp_path, monkeypatch, mode):
    """Controlled site metadata; exercise the actual maintained guard unchanged.

    These are empty owned directories, not installed package/runtime claims.
    The physical original-owner case separately checks the real environment.
    """
    import site
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_campaign_process_worker as bootstrap
    primary = [str(tmp_path / name) for name in ("interpreter-site-a", "interpreter-site-b", "known-but-inactive-site")]
    user = str(tmp_path / "user-site")
    unrelated = str(tmp_path / "unrelated-active-root")
    for directory in [*primary, user, unrelated]: Path(directory).mkdir()
    prefix = str(Path(sys.executable).parent.parent)
    original_path = list(sys.path)
    with monkeypatch.context() as context:
        # Input metadata only: never patch _require, either maintained helper,
        # the original owner, or the normal qualification/bootstrap protocol.
        context.setattr(site, "getsitepackages", lambda *, prefixes: list(primary))
        context.setattr(site, "getusersitepackages", lambda: user)
        active = [user, primary[1], primary[0]]
        if mode == "default-active-subset": active = [unrelated, user, primary[1]]
        elif mode == "default-user-only": active = [user]
        context.setattr(sys, "path", active)
        if mode.startswith("default-"):
            result = bootstrap._reviewed_dependency_paths(prefix)
            expected = ((user, primary[1]) if mode == "default-active-subset" else
                (user,) if mode == "default-user-only" else (user, primary[1], primary[0]))
            assert result == expected
            assert primary[2] not in result and all(value in active for value in result)
            assert unrelated not in result and sys.path == active
        elif mode == "explicit-user-first":
            supplied = [user, primary[0], primary[1]]
            assert bootstrap._reviewed_dependency_paths(prefix, supplied) == tuple(supplied)
            assert sys.path == active
        else:
            supplied = [primary[0], primary[1], user, user]
            with pytest.raises(RuntimeError, match="unknown or repeated"):
                bootstrap._reviewed_dependency_paths(prefix, supplied)
            assert sys.path == active
    assert sys.path == original_path



@pytest.mark.parametrize("mode", ["present", "absent", "empty", "override-refused"])
def test_reviewed_inference_child_environment_preserves_only_existing_original_userbase(tmp_path, monkeypatch, mode):
    """Environment DATA only; the original isolated child guard stays strict."""
    import os
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_invocation_contracts as contracts
    private_home = str(tmp_path / "private-home")
    original_userbase = str(tmp_path / "original-userbase")
    monkeypatch.setenv("HOME", private_home)
    monkeypatch.delenv("PYTHONUSERBASE", raising=False)
    if mode != "absent": monkeypatch.setenv("PYTHONUSERBASE", "" if mode == "empty" else original_userbase)
    # Unrelated ambient settings are not a new environment grant.
    monkeypatch.setenv("REVIEWED_UNRELATED_ENVIRONMENT", "must-not-propagate")
    monkeypatch.setenv("HF_TOKEN", "fictional-not-a-credential")
    before = dict(os.environ)
    if mode == "override-refused":
        with pytest.raises(contracts.DaemonInvocationError, match="unsupported execution environment override"):
            contracts.execution_environment({"PYTHONUSERBASE": str(tmp_path / "not-the-parent-userbase")})
    else:
        environment = contracts.execution_environment()
        assert environment["HOME"] == private_home
        if mode == "absent": assert "PYTHONUSERBASE" not in environment
        else: assert environment["PYTHONUSERBASE"] == ("" if mode == "empty" else original_userbase)
        assert "REVIEWED_UNRELATED_ENVIRONMENT" not in environment and "HF_TOKEN" not in environment
        assert environment["HF_HUB_OFFLINE"] == environment["TRANSFORMERS_OFFLINE"] == "1"
        assert not Path(private_home).exists() and not Path(original_userbase).exists()
    assert dict(os.environ) == before


@pytest.mark.parametrize("damage", [None, "empty", "checkpoint", "references", "context", "output",
    "observation", "commitment", "scores", "compiler"])
def test_reviewed_inference_v11_evaluation_scores_the_verified_generation(tmp_path, damage):
    worker, _, request, _, _, save = _reviewed_v11_saved_control(tmp_path, "complete")
    cycle = save()
    evaluation_path = Path(cycle["output_artifacts"]["evaluation"]["path"])
    evaluation = json.loads(evaluation_path.read_bytes())
    payload = evaluation["compiler_artifact"]["reviewed_source_span_producer_evaluation"]
    if damage == "empty":
        evaluation = {}
    elif damage == "checkpoint":
        payload["configuration"]["checkpoint_declarations"]["decoder"]["sha256"] = "f" * 64
    elif damage == "references":
        payload["reference_population"][0]["source_text"] += " changed"
    elif damage == "context":
        payload["producer_arguments"][0]["context"]["retrieved"].append("different example")
    elif damage == "output":
        payload["producer_outputs"][0].update(candidate=None, outcome="abstained")
    elif damage == "observation":
        evaluation["metadata"]["source_generation_observation"]["last_call"]["completed"] = False
    elif damage == "commitment":
        evaluation["metadata"]["source_generation_input_commitment_sha256"] = "e" * 64
    elif damage == "scores":
        for score in (payload["comparison"], evaluation["metrics"]["complete_norm_payload"]):
            score["denominator"] += 1
    elif damage == "compiler":
        payload["declared_compiler_identity"] = "fixture:another-compiler"
    raw = worker._json_bytes(evaluation)
    evaluation_path.write_bytes(raw)
    cycle["output_artifacts"]["evaluation"].update(bytes=len(raw), sha256=_sha(evaluation_path))
    fixed = {name: Path(cycle["output_artifacts"][name]["path"]).read_bytes()
        for name in ("generation", "loader")}
    if damage is None:
        inference._check_reviewed_evaluation_outputs(cycle, request)
    else:
        with pytest.raises(ValueError, match="v11 evaluation|parent typed-structure"):
            inference._check_reviewed_evaluation_outputs(cycle, request)
    assert evaluation_path.read_bytes() == raw
    for name, before in fixed.items():
        assert Path(cycle["output_artifacts"][name]["path"]).read_bytes() == before
