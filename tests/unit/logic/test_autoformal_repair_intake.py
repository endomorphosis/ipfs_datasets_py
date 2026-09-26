"""Intake review preserves failures and evidence while unblocking safe dispatch."""
from __future__ import annotations

from pathlib import Path

import pytest

from ipfs_datasets_py.logic.autoformal.repair_intake import route_intake_reviews, review_flags
from ipfs_datasets_py.logic.autoformal.supervisor_queue import RepairQueueError, enqueue_repairs, repair_packets
from ipfs_datasets_py.logic.autoformal.feedback_cycle import FeedbackCycleError, next_phase, queue_observation


def packets(*texts):
    return repair_packets({"rows": [{"id": f"s{i}", "text": text, "agrees": False,
                                    "reason": "compiler_abstain:unsupported_norm_type"}
                                   for i, text in enumerate(texts)]}, release_id="release-1",
                          code_identity="code-1", model_identity="model-1")


def queue(tmp_path, *texts):
    from ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source import DatabaseTaskSource
    source = DatabaseTaskSource(tmp_path / "control.duckdb")
    enqueue_repairs(source, packets(*texts), packet_directory=tmp_path / "packets")
    return source


def test_read_only_plan_does_not_change_status_or_claim(tmp_path):
    with queue(tmp_path, "§ 10. Omitted", "The officer shall retain omitted records.") as source:
        before = source.snapshot().to_dict()
        result = route_intake_reviews(source)
        assert result["review_required"] == 1
        assert result["transitions"][0]["applied"] is False
        assert source.snapshot().to_dict() == before
        assert result["repairs_completed"] == 0 and result["tasks_claimed"] is False


@pytest.mark.parametrize("status", ["ready", "retrying"])
def test_native_review_transition_preserves_packet_and_leaves_normative_task_eligible(tmp_path, status):
    with queue(tmp_path, "§ 10. Omitted", "The officer shall retain records.") as source:
        editorial = next(task for task in source.list_tasks().tasks if "Omitted" in Path(task.body["packet_path"]).read_text())
        if status == "retrying":
            source.compare_and_set_status(editorial.task_cid, editorial.revision, status,
                                           receipt={"reason": "previous_dependency_failure", "provider_dispatched": False})
            editorial = source.get(editorial.task_cid)
        packet_path = Path(editorial.body["packet_path"])
        sealed = packet_path.read_bytes()
        result = route_intake_reviews(source, apply=True)
        assert result["review_required"] == 1 and result["transitions"][0]["applied"] is True
        reviewed = source.get(editorial.task_cid)
        assert reviewed.status == "blocked"
        assert reviewed.validations == editorial.validations and reviewed.outputs == editorial.outputs
        assert packet_path.read_bytes() == sealed
        receipt = reviewed.body["completion_receipt"]  # Native name; not a completion assertion.
        assert receipt["operation"] == "autoformal_intake_review_required"
        assert receipt["source_classification"] == "unreviewed"
        assert receipt["counts_as_repair"] is receipt["counts_as_validation"] is False
        assert receipt["admitted"] is receipt["formalized"] is False
        eligible = source.ready_tasks()
        assert len(eligible.tasks) == 1 and eligible.tasks[0].task_cid != editorial.task_cid
        assert next_phase(queue_observation(source), "input", None) == "supervise"
        before = source.snapshot().to_dict()
        assert route_intake_reviews(source, apply=True)["review_required"] == 0
        assert source.snapshot().to_dict() == before
    with queue_reopen(tmp_path) as source:
        assert source.get(editorial.task_cid).status == "blocked"
        assert route_intake_reviews(source, apply=True)["review_required"] == 0


def queue_reopen(tmp_path):
    from ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source import DatabaseTaskSource
    return DatabaseTaskSource(tmp_path / "control.duckdb", install_schema=False)


def test_only_review_tasks_does_not_mean_completed_queue(tmp_path):
    with queue(tmp_path, "§ 10. Reserved.") as source:
        route_intake_reviews(source, apply=True)
        with pytest.raises(FeedbackCycleError, match="unresolved"):
            next_phase(queue_observation(source), "input", None)


def test_corrupt_inventory_refuses_entire_intake_plan_before_mutation(tmp_path):
    with queue(tmp_path, "§ 10. Omitted", "The officer shall retain records.") as source:
        task = source.list_tasks().tasks[-1]
        packet = Path(task.body["packet_path"])
        packet.write_bytes(packet.read_bytes() + b" ")
        before = source.snapshot().to_dict()
        with pytest.raises(RepairQueueError, match="integrity"):
            route_intake_reviews(source, apply=True)
        assert source.snapshot().to_dict() == before


def test_active_task_is_never_reclassified(tmp_path):
    with queue(tmp_path, "§ 10. Transferred") as source:
        task = source.list_tasks().tasks[0]
        source.compare_and_set_status(task.task_cid, task.revision, "in_progress", receipt={"owner": "native-test"})
        before = source.snapshot().to_dict()
        assert route_intake_reviews(source, apply=True)["review_required"] == 0
        assert source.snapshot().to_dict() == before


def test_claim_race_fails_cas_and_does_not_park_claimed_task(tmp_path, monkeypatch):
    from ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source import TaskSourceConflictError
    with queue(tmp_path, "§ 10. Repealed") as source:
        task = source.list_tasks().tasks[0]
        native = source.compare_and_set_status
        def race(key, revision, status, receipt=None):
            native(key, revision, "in_progress", receipt={"owner": "another-native-owner"})
            return native(key, revision, status, receipt=receipt)
        monkeypatch.setattr(source, "compare_and_set_status", race)
        with pytest.raises(TaskSourceConflictError):
            route_intake_reviews(source, apply=True)
        assert source.get(task.task_cid).status == "in_progress"


def test_preserved_editorial_heading_cannot_be_hidden_in_a_repair_packet():
    assert review_flags({"row": {"text": "The officer shall retain records."},
                         "preserve_rows": [{"text": "§ 10. Omitted"}]})
    assert not review_flags({"row": {"text": "§ 10. Omitted information shall be supplied."}})


def test_reobserving_blocked_source_does_not_reopen_or_duplicate_it(tmp_path):
    with queue(tmp_path, "§ 10. Omitted") as source:
        route_intake_reviews(source, apply=True)
        before = source.snapshot().to_dict()
        result = enqueue_repairs(source, packets("§ 10. Omitted"), packet_directory=tmp_path / "packets")
        assert not result["inserted"] and result["existing"][0]["status"] == "blocked"
        assert source.snapshot().to_dict() == before


@pytest.mark.parametrize("text", [
    "A brown tree snake constitutes nonmailable matter under .",
    "Except as provided in , this subchapter shall apply.",
    "The agreements were approved pursuant to .",
    "The exemption as defined in ; shall apply.",
    "The amount of payments shall be governed by .",
    "The programs authorized by the Example Act [ et seq.] shall apply.",
    "The term ‘Council’ means the Example Council established in .",
    "The term ‘agency’ has the meaning given the term ‘bureau’ in .",
])
def test_missing_reference_is_review_not_an_invented_citation(text):
    assert review_flags({"row": {"text": text}}) == ["dangling_reference_requires_source_hydration"]


@pytest.mark.parametrize("text", [
    "A brown tree snake constitutes nonmailable matter under section 1716.",
    "Except as provided in subsection (b), this subchapter shall apply.",
    "The officer shall retain records under seal.",
    "The programs authorized by the Example Act [42 U.S.C. 100 et seq.] shall apply.",
    "The term ‘Council’ means the Example Council established in section 10.",
    "The term ‘agency’ has the meaning given the term ‘bureau’ in section 10.",
    "The marker shall be 8 in. long.",
])
def test_present_reference_is_not_flagged_as_dangling(text):
    assert not review_flags({"row": {"text": text}})


def test_missing_reference_in_preserved_row_is_also_a_review_alarm():
    assert review_flags({"row": {"text": "The officer shall retain records."},
                         "preserve_rows": [{"text": "Except as provided in , disclosure is prohibited."}]})


@pytest.mark.parametrize("text", [
    "[§§ 370 to 372. Repealed. , Nov. 5, 1990 , ]",
    "[§ 20. Reserved.]",
])
def test_bracketed_editorial_metadata_requires_review(text):
    assert review_flags({"row": {"text": text}}) == ["editorial_heading_requires_source_classification"]


def test_reference_to_a_repealed_section_is_not_an_editorial_only_heading():
    assert not review_flags({"row": {"text": "The officer shall keep a copy of [§ 20. Repealed.]."}})
