"""The supervisor claims census disagreements while later spans are still compiled."""

from pathlib import Path

from ipfs_datasets_py.logic.autoformal.joint_benchmark import packet_schema_gaps, run_joint_benchmark
from ipfs_datasets_py.logic.autoformal.supervisor_queue import read_packet


def test_supervisor_claims_a_disagreement_while_ingestion_continues(tmp_path: Path):
    spans = [
        {"legal_id": "usc:10:1", "source_span_id": "joint-1", "text": "The officer shall retain records."},
        {"legal_id": "usc:10:2", "source_span_id": "joint-2", "text": "The officer shall retain records until Monday."},
        {"legal_id": "usc:10:3", "source_span_id": "joint-3", "text": "The clerk shall keep the journal."},
    ]
    scores = {"cosine_similarity": 0.2, "cross_entropy_loss": 1.0, "reconstruction_loss": 0.1}
    result = run_joint_benchmark(
        spans,
        database=tmp_path / "control.duckdb",
        packet_directory=tmp_path / "packets",
        scores=scores,
        decode=lambda _text: "5, 1990, 104 Stat.",
        pause_seconds=0.05,
    )
    assert result["enqueued"] == 3
    assert len(result["claimed"]) == 3
    assert result["overlapped"] is True
    assert result["schema_ready"] is True
    assert result["admitted"] is False
    assert result["formalized"] is False
    assert result["wrote_compiler"] is False
    assert result["uploaded"] is False
    assert all(item["schema_gaps"] == [] for item in result["claimed"])
    from ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source import DatabaseTaskSource

    with DatabaseTaskSource(tmp_path / "control.duckdb") as source:
        page = source.list_tasks(status="in_progress", limit=10)
        assert len(page.tasks) == 3
        for record in page.tasks:
            body = record.body
            packet = read_packet(Path(body["packet_path"]), body["packet_sha256"])
            assert packet_schema_gaps(packet) == []
            assert list(record.validations)
            assert record.status == "in_progress"


def test_supervisor_applies_a_router_repair_and_reruns_the_census(tmp_path: Path):
    import json

    spans = [
        {"legal_id": "usc:10:1", "source_span_id": "joint-repair", "text": "The officer shall retain records."},
    ]

    def generate(prompt, temperature=0, task_kind="legal"):
        assert temperature == 0 and task_kind == "legal"
        assert "canonical_decompiler.py" in prompt
        return json.dumps({
            "decompiler": "def decompile(text):\n    return '5, 1990, 104 Stat.'\n",
        })

    result = run_joint_benchmark(
        spans,
        database=tmp_path / "control.duckdb",
        packet_directory=tmp_path / "packets",
        scores={"cosine_similarity": 0.9, "cross_entropy_loss": 1.0, "reconstruction_loss": 0.1},
        decode=lambda _text: "5, 1990, 104 Stat.",
        generate=generate,
        pause_seconds=0.01,
    )
    assert len(result["claimed"]) == 1
    claim = result["claimed"][0]
    assert claim["router_called"] is True
    assert claim["census_rerun"] is True
    assert claim["agrees_with_autoencoder"] is True
    assert claim["wrote_compiler"] is False
    assert claim["admitted"] is False
    assert (tmp_path / "packets" / claim["task_cid"] / "decompiler_repair.py").is_file()
    installed = Path(__file__).resolve().parents[3] / "ipfs_datasets_py/logic/legal_ir/canonical_decompiler.py"
    assert "def decompile(text):" not in installed.read_text(encoding="utf-8")[:400]
