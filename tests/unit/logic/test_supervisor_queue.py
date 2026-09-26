"""Native queue producer contracts; no providers, downloads or fake completion."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.autoformal.supervisor_queue import (
    RepairQueueError, enqueue_repairs, read_packet, repair_packets, replay_packet,
    repair_outputs, upgrade_ready_outputs,
)


def agreement():
    return {"rows": [
        {"id": "sec1", "source_span_id": "source-1", "text": "The officer shall retain records unless exempt.",
         "reason": "dropped_clause", "dropped": ["unless exempt"], "agrees": False,
         "decompiled": "The officer shall retain records."},
        {"id": "sec2", "source_span_id": "source-2", "text": "The agency shall not disclose records.",
         "reason": "", "agrees": True, "decompiled": "The agency shall not disclose records."},
    ]}


def packets(value=None, **overrides):
    return repair_packets(value or agreement(), **{
        "release_id": "release-v1", "code_identity": "compiler-tree-1",
        "model_identity": "checkpoint-1", **overrides,
    })


def test_absolute_python_rejected_before_queue_or_packet_writes(tmp_path):
    with pytest.raises(RepairQueueError, match="sealed python3 launcher"):
        enqueue_repairs(None, packets(), packet_directory=tmp_path / "packets", python="/usr/bin/python3")
    assert not (tmp_path / "packets").exists()


def test_versioned_baseline_scope_preserves_parent_and_discloses_old_bad_preserves():
    from ipfs_datasets_py.logic.autoformal.extended_repair import baseline_packet, validate_baseline
    from ipfs_datasets_py.logic.autoformal.supervisor_queue import canonical_bytes
    parent = packets()[0]
    before = canonical_bytes(parent["packet"])
    old = [parent["packet"]["row"], *parent["packet"]["preserve_rows"]]
    census = {"rows": [{**row, "id": row["source_span_id"], "agrees": False,
                        "reason": "dropped_clause", "skipped": False} for row in old]}
    item = baseline_packet(parent["packet"], parent["sha256"], census=census,
                           source_span_id=old[1]["source_span_id"], code_identity="new-reviewed-tree")
    assert canonical_bytes(parent["packet"]) == before
    assert item["packet"]["preserve_rows"] == []
    assert item["packet"]["revision"]["other_unresolved_sources"] == [old[0]["source_span_id"]]
    assert item["packet"]["revision"]["parent_task_completed"] is False
    assert "ipfs_datasets_py/logic/legal_ir/canonical_compiler.py" in repair_outputs(item["packet"], item["sha256"])
    assert "ipfs_datasets_py/logic/legal_ir/canonical_decompiler.py" in repair_outputs(item["packet"], item["sha256"])
    item["packet"]["revision"]["parent_task_completed"] = True
    with pytest.raises(ValueError):
        validate_baseline(item["packet"])


def test_versioned_baseline_cannot_seed_from_changed_source_or_claimed_agreement():
    from ipfs_datasets_py.logic.autoformal.extended_repair import baseline_packet
    parent = packets()[0]
    old = [parent["packet"]["row"], *parent["packet"]["preserve_rows"]]
    rows = [{**row, "id": row["source_span_id"], "skipped": False} for row in old]
    with pytest.raises(ValueError, match="reproduced failure"):
        baseline_packet(parent["packet"], parent["sha256"], census={"rows": rows},
                        source_span_id=old[1]["source_span_id"], code_identity="new-tree")
    rows[0]["text"] += " fabricated"
    with pytest.raises(ValueError, match="every parent source"):
        baseline_packet(parent["packet"], parent["sha256"], census={"rows": rows},
                        source_span_id=old[0]["source_span_id"], code_identity="new-tree")


def test_new_versioned_tasks_do_not_reset_or_mutate_parent_task(tmp_path):
    from ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source import DatabaseTaskSource
    from ipfs_datasets_py.logic.autoformal.extended_repair import extension_packet
    from ipfs_datasets_py.logic.legal_ir.extended_contracts import ExtendedLegalIR, PolicyV2
    parent = packets({"rows": [{"id": "policy", "text": "Congress supports retaining records.",
                              "reason": "compiler_abstain", "agrees": False}]})[0]
    item = extension_packet(parent["packet"], parent["sha256"], code_identity="new-tree", family="policy",
                            expected_ir=ExtendedLegalIR((PolicyV2("Congress", "supports", ("retaining records",)),)).to_dict())
    with DatabaseTaskSource(tmp_path / "control.duckdb") as source:
        old_result = enqueue_repairs(source, [parent], packet_directory=tmp_path / "packets")
        old = source.ready_tasks(limit=10).tasks[0]
        inserted = enqueue_repairs(source, [item], packet_directory=tmp_path / "packets")
        assert inserted["task_count"] == 1 and inserted["inserted"] != old_result["inserted"]
        assert source.get(old.task_cid) == old
        assert enqueue_repairs(source, [item], packet_directory=tmp_path / "packets")["task_count"] == 0
        assert source.get(old.task_cid) == old


def test_offline_parent_cid_matches_native_authority_codec():
    import hashlib
    from ipfs_datasets_py.logic.autoformal.extended_repair import _parent_task_cid
    from ipfs_datasets_py.logic.autoformal.supervisor_queue import SCHEMA
    from ipfs_accelerate_py.agent_supervisor.task_sources.control_plane_contracts import content_identity
    for index in range(32):
        digest = hashlib.sha256(str(index).encode()).hexdigest()
        assert _parent_task_cid(digest) == content_identity({"schema": SCHEMA, "packet_sha256": digest})


def test_identity_ignores_order_and_query_but_binds_semantics_and_versions():
    original = packets()[0]
    reverse = agreement()
    reverse["rows"].reverse()
    assert packets(reverse, query="different search")[0]["sha256"] == original["sha256"]
    for key in ("release_id", "code_identity", "model_identity"):
        assert packets(**{key: "changed"})[0]["sha256"] != original["sha256"]
    changed = agreement()
    changed["rows"][0]["text"] += " After ten days."
    assert packets(changed)[0]["sha256"] != original["sha256"]


class FakeTaskSource:
    def __init__(self):
        self.records = {}
        self.materialized = []

    def list_tasks(self, cursor="", limit=100):
        return SimpleNamespace(tasks=list(self.records.values()), next_cursor="")

    def get(self, task_cid):
        return self.records.get(task_cid)

    def materialize(self, payload):
        self.materialized.append(payload)
        for task in payload["tasks"]:
            record = SimpleNamespace(
                task_cid=task["task_cid"],
                task_alias=task["task_id"],
                status=task.get("status") or "ready",
                body=dict(task),
            )
            self.records[task["task_cid"]] = record


@pytest.mark.parametrize("key,value", [
    ("task_cid", "forged"), ("task_id", "forged"), ("status", "completed"),
    ("allowed_edit_paths", ["validators.py"]), ("outputs", []),
    ("validation_commands", []), ("completion_receipt", {"passed": True}),
    ("packet_sha256", "0" * 64), ("packet_path", "/tmp/forged.json"),
    ("board_namespace", "foreign"), ("acceptance_criteria", []),
    ("priority", "P0"), ("estimated_tokens", 10**10),
    ("admitted", True), ("formalized", True),
])
def test_export_metadata_cannot_override_task_authority_before_writes(tmp_path, key, value):
    with pytest.raises(RepairQueueError, match="export metadata"):
        enqueue_repairs(None, packets(), packet_directory=tmp_path / "packets",
                        extra_task_fields={key: value})
    assert not (tmp_path / "packets").exists()


@pytest.mark.parametrize("value", [
    {"jsonl_written": True}, {"wrote_compiler": 0},
    {"huggingface_todo_locator": {"schema": "unknown"}},
    {"huggingface_todo_locator": {"schema": "ipfs_accelerate_py.agent_supervisor.huggingface_todo_locator/v1", "data": "x" * 16384}},
])
def test_export_metadata_is_bounded_versioned_data(tmp_path, value):
    with pytest.raises(RepairQueueError, match="metadata"):
        enqueue_repairs(None, packets(), packet_directory=tmp_path / "packets", extra_task_fields=value)
    assert not (tmp_path / "packets").exists()


def test_export_metadata_is_detached_before_reading_the_queue(tmp_path):
    from ipfs_datasets_py.logic.autoformal.supervisor_todo import LOCATOR_SCHEMA
    extra = {"jsonl_written": False, "huggingface_todo_locator": {"schema": LOCATOR_SCHEMA, "revision": "original"}}
    class MutatingSource(FakeTaskSource):
        def list_tasks(self, **kwargs):
            extra["status"] = "completed"
            extra["huggingface_todo_locator"]["revision"] = "changed"
            return super().list_tasks(**kwargs)
    source = MutatingSource()
    enqueue_repairs(source, packets(), packet_directory=tmp_path / "packets", extra_task_fields=extra)
    task = source.materialized[0]["tasks"][0]
    assert task["status"] == "ready"
    assert task["huggingface_todo_locator"]["revision"] == "original"
    assert task["validation_commands"][0]["argv"][0] == "python3"


def test_canonical_error_codes_use_compiler_abstain_scope():
    from ipfs_datasets_py.logic.autoformal.supervisor_queue import (
        EDIT_SCOPES,
        RepairQueueError,
        approved_edit_scope,
    )

    assert approved_edit_scope("CanonicalErrorCode.UNSUPPORTED_SEMANTICS") == "compiler_abstain"
    assert approved_edit_scope("dropped_clause") == "dropped_clause"
    assert approved_edit_scope("compiler_abstain:detail") == "compiler_abstain"
    assert approved_edit_scope("strict_roundtrip_failed") == "strict_roundtrip_failed"
    with pytest.raises(RepairQueueError, match="no approved"):
        approved_edit_scope("inference_still_failing")
    assert "compiler_abstain" in EDIT_SCOPES


def test_huggingface_locator_is_not_packet_identity(tmp_path):
    from ipfs_datasets_py.logic.autoformal.supervisor_queue import submit_native_discrepancies

    locator = {
        "schema": "ipfs_accelerate_py.agent_supervisor.huggingface_todo_locator/v1",
        "dataset_repo_id": "justicedao/uscode-autoformal-todos",
        "release_id": "release-v1",
        "board_path": "data/autoformal_todo/release-v1/board.md",
        "todos_path": "data/autoformal_todo/release-v1/todos.parquet",
    }
    source = FakeTaskSource()
    original = packets()[0]["sha256"]
    receipt = submit_native_discrepancies(
        source,
        agreement(),
        packet_directory=tmp_path / "packets",
        release_id="release-v1",
        code_identity="compiler-tree-1",
        model_identity="checkpoint-1",
        huggingface_locator=locator,
    )
    again = enqueue_repairs(source, packets(), packet_directory=tmp_path / "packets")
    assert packets()[0]["sha256"] == original
    assert receipt["authority"] == "accelerate-duckdb"
    assert receipt["jsonl_written"] is False
    assert receipt["task_count"] == 1
    assert receipt["huggingface_todo_locator"]["dataset_repo_id"] == "justicedao/uscode-autoformal-todos"
    assert receipt["time_management"]["total_estimated_tokens"] > 0
    assert again["task_count"] == 0
    assert again["existing"]
    body = source.materialized[0]["tasks"][0]
    assert body["huggingface_todo_locator"]["dataset_repo_id"] == "justicedao/uscode-autoformal-todos"
    assert body["estimated_tokens"] > 0


def test_no_inference_failure_disguised_as_compiler_repair():
    value = agreement()
    value["rows"][0]["reason"] = "inference_still_failing"
    with pytest.raises(RepairQueueError, match="scope"):
        packets(value)


def test_empty_or_unversioned_evidence_rejected():
    with pytest.raises(RepairQueueError, match="identities"):
        packets(release_id="")
    value = agreement()
    value["rows"][0]["text"] = ""
    with pytest.raises(RepairQueueError, match="exact source"):
        packets(value)


def test_decompiler_task_scope_preserves_compiler():
    packet = packets()[0]["packet"]
    assert all("canonical_compiler.py" not in path for path in packet["allowed_edit_paths"])
    assert "TypedDeonticCanonicalCompiler" in packet["preserve"]
    assert packet["preserve_rows"][0]["source_span_id"] == "source-2"


def test_replay_needs_every_source_not_an_aggregate_success_flag():
    packet = packets()[0]["packet"]
    assert not replay_packet(packet, census=lambda *args: {"agrees": True, "rows": []})["passed"]
    def census(samples, inference):
        assert inference["captures"][0]["sample_id"] == "source-1"
        return {"rows": [{"id": row["id"], "agrees": True, "skipped": False} for row in samples]}
    result = replay_packet(packet, census=census)
    assert result["passed"] and not result["formalized"] and not result["admitted"]


def test_replay_rejects_skipped_preserved_rows():
    packet = packets()[0]["packet"]
    def census(samples, inference):
        return {"rows": [{"id": row["id"], "agrees": True, "skipped": i == 1}
                         for i, row in enumerate(samples)]}
    assert not replay_packet(packet, census=census)["passed"]


def test_native_duckdb_restart_idempotence_and_sealed_evidence(tmp_path: Path):
    from ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source import DatabaseTaskSource
    items = packets()
    path = tmp_path / "control.duckdb"
    with DatabaseTaskSource(path) as source:
        first = enqueue_repairs(source, items, packet_directory=tmp_path / "packets")
        assert len(first["inserted"]) == 1
        record = source.get(first["inserted"][0])
        assert record.status == "ready"
        assert record.body["packet_sha256"] == items[0]["sha256"]
        assert "validate_autoformal_repair.py" in str(record.validations)
        assert record.validations[0]["argv"][1] == "scripts/ops/legal_ir/validate_autoformal_repair.py"
        assert [dict(row)["path"] for row in record.outputs] == repair_outputs(items[0]["packet"], items[0]["sha256"])
        from ipfs_accelerate_py.agent_supervisor.todo_daemon.database_portal_bridge import DatabasePortalExecutionBridge
        bridge = DatabasePortalExecutionBridge(task_source=source, attempt_root=tmp_path / "attempts",
                                              portal_factory=lambda *args: None)
        attempt = SimpleNamespace(task_cid=record.task_cid, task_alias=record.task_alias,
                                  attempt_id="attempt-test", claim_id="claim-test", attempt_number=1)
        projection = bridge._render_projection(attempt, record)
        assert "- Outputs: ipfs_datasets_py/logic/legal_ir/canonical_decompiler.py," in projection
        assert repair_outputs(items[0]["packet"], items[0]["sha256"])[-1] in projection
        assert "- Validation: python3 scripts/ops/legal_ir/validate_autoformal_repair.py " in projection
    with DatabaseTaskSource(path) as source:
        second = enqueue_repairs(source, items, packet_directory=tmp_path / "packets")
        assert not second["inserted"]
        assert second["existing"][0]["status"] == "ready"
        assert source.snapshot().task_count == 1
    packet_file = tmp_path / "packets" / (items[0]["sha256"] + ".json")
    assert read_packet(packet_file, items[0]["sha256"])["row"]["text"] == agreement()["rows"][0]["text"]
    packet_file.write_bytes(packet_file.read_bytes() + b" ")
    with pytest.raises(RepairQueueError, match="integrity"):
        read_packet(packet_file, items[0]["sha256"])
    with DatabaseTaskSource(path) as source:
        with pytest.raises(RepairQueueError, match="conflicting"):
            enqueue_repairs(source, items, packet_directory=tmp_path / "packets")


def test_explicit_output_migration_keeps_validation_and_is_idempotent(tmp_path):
    from ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source import DatabaseTaskSource
    with DatabaseTaskSource(tmp_path / "control.duckdb") as source:
        result = enqueue_repairs(source, packets(), packet_directory=tmp_path / "packets")
        record = source.get(result["inserted"][0])
        source.materialize({"tasks": [{**dict(record.body), "task_cid": record.task_cid,
                                      "task_id": record.task_alias, "status": "ready",
                                      "validation_commands": [{"argv": list(v["argv"])} for v in record.validations],
                                      "acceptance_criteria": [dict(v["evidence_policy"]) for v in record.acceptance]}]})
        assert not source.get(record.task_cid).outputs
        assert upgrade_ready_outputs(source)["upgraded"] == [record.task_alias]
        fresh = source.get(record.task_cid)
        assert fresh.status == "ready" and fresh.outputs
        assert fresh.validations == record.validations
        assert not upgrade_ready_outputs(source)["upgraded"]


def test_output_migration_refuses_nonvirgin_task(tmp_path):
    from ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source import DatabaseTaskSource
    with DatabaseTaskSource(tmp_path / "control.duckdb") as source:
        result = enqueue_repairs(source, packets(), packet_directory=tmp_path / "packets")
        record = source.get(result["inserted"][0])
        source.materialize({"tasks": [{**dict(record.body), "task_cid": record.task_cid,
                                      "task_id": record.task_alias, "status": "failed"}]})
        with pytest.raises(RepairQueueError, match="never-dispatched"):
            upgrade_ready_outputs(source)
        assert source.get(record.task_cid).status == "failed"


def test_output_scope_cannot_be_broadened():
    item = packets()[0]
    item["packet"]["allowed_edit_paths"].append("ipfs_datasets_py/logic/autoformal/autoencoder_router.py")
    with pytest.raises(RepairQueueError, match="edit scope"):
        repair_outputs(item["packet"], item["sha256"])


def test_model_only_reobservation_keeps_evidence_without_duplicate_task(tmp_path):
    from ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source import DatabaseTaskSource
    with DatabaseTaskSource(tmp_path / "control.duckdb") as source:
        original = enqueue_repairs(source, packets(), packet_directory=tmp_path / "packets")
        record = source.get(original["inserted"][0])
        again = enqueue_repairs(source, packets(model_identity="new-private-checkpoint"),
                                packet_directory=tmp_path / "packets")
        assert not again["inserted"]
        assert again["covered"][0]["task_id"] == record.task_alias
        assert source.get(record.task_cid).revision == record.revision
        assert source.snapshot().task_count == 1
        evidence = again["covered"][0]
        assert read_packet(Path(evidence["packet_path"]), evidence["observation_sha256"])["model_identity"] == "new-private-checkpoint"
        changed = enqueue_repairs(source, packets(code_identity="changed-compiler"),
                                  packet_directory=tmp_path / "packets")
        assert changed["task_count"] == 1


def test_changed_model_captures_are_not_deduplicated(tmp_path):
    from ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source import DatabaseTaskSource
    with DatabaseTaskSource(tmp_path / "control.duckdb") as source:
        enqueue_repairs(source, packets(), packet_directory=tmp_path / "packets")
        changed = agreement()
        changed["rows"][0]["capture"] = {"triples": [{"subject": "rule", "predicate": "unless", "object": "exempt"}]}
        result = enqueue_repairs(source, packets(changed, model_identity="next-model"),
                                 packet_directory=tmp_path / "packets")
        assert result["task_count"] == 1
