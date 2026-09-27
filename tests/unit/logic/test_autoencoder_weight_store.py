"""Sparse autoencoder weights, consensus ticks, and origin/main sync."""
from pathlib import Path

from ipfs_datasets_py.logic.autoformal.autoencoder_weight_store import (
    consensus_history,
    control_plane_record,
    record_consensus,
    sparse_delta,
    store_sparse_update,
)
from ipfs_datasets_py.logic.autoformal.goal_git_sync import sync_origin_main


def test_sparse_delta_drops_high_frequency_jitter() -> None:
    deltas = sparse_delta(
        {"family_logits.deontic": 1.0, "family_logits.frame": 0.2},
        {"family_logits.deontic": 1.0001, "family_logits.frame": 0.8, "family_logits.noise": 1e-6},
    )
    assert [item["name"] for item in deltas] == ["family_logits.frame"]


def test_weights_and_consensus_live_in_duckdb(tmp_path: Path, monkeypatch) -> None:
    database = tmp_path / "weights.duckdb"
    monkeypatch.setenv("IPFS_DATASETS_WEIGHTS_DB", str(database))
    receipt = store_sparse_update(
        {"family_logits.frame": 0.5},
        path=database,
        improved=False,
    )
    assert receipt["delta_count"] == 1
    assert receipt["uploaded"] is False
    assert receipt["admitted"] is False
    tiny = store_sparse_update(
        {"family_logits.frame": 0.50001},
        path=database,
        improved=True,
    )
    assert tiny["delta_count"] == 0
    assert tiny["uploaded"] is False
    tick = record_consensus(
        {"encoded": 4, "agree": 2, "disagree": 2, "unscored": 1, "agreement_rate": 0.5},
        path=database,
    )
    history = consensus_history(database)
    assert history[-1]["tick_id"] == tick
    assert history[-1]["agreement_rate"] == 0.5
    assert history[-1]["admitted"] is False
    plane = control_plane_record(database)
    assert plane["control_plane"] == "duckdb+quack"
    assert plane["ducklake_activation_held"] == "true"
    assert "quack" in plane["explicit_load_order"]
    assert "ducklake" in plane["explicit_load_order"]


def test_weights_are_readable_over_quack(tmp_path: Path, monkeypatch) -> None:
    import threading

    from ipfs_datasets_py.duckdb_control.span_cache_quack import SupervisorGoalTransportClient, handoff_paths
    from ipfs_datasets_py.logic.autoformal.autoencoder_weight_store import WeightQuackGateway

    database = tmp_path / "weights.duckdb"
    monkeypatch.setenv("IPFS_DATASETS_WEIGHTS_DB", str(database))
    store_sparse_update({"family_logits.frame": 0.4}, path=database, improved=False)
    gateway = WeightQuackGateway(database)
    stop = threading.Event()

    def serve() -> None:
        while not stop.is_set():
            gateway.serve()
            stop.wait(0.01)

    try:
        gateway.start()
        published = gateway.publish()
        thread = threading.Thread(target=serve)
        thread.start()
        _endpoint, token_path = handoff_paths(database)
        token = token_path.read_text(encoding="utf-8").strip()
        with SupervisorGoalTransportClient(published["endpoint"], token) as client:
            reply = client.request(
                "UpsertFailureGoals",
                {"goals": [{"op": "weights"}]},
                "read-weights-1",
                timeout=30,
            )
        cells = {item["name"]: item["value"] for item in reply["cells"]}
        assert cells["family_logits.frame"] == "0.40000000"
        assert reply["control_plane"]["ducklake_activation_held"] == "true"
        assert reply["admitted"] is False
    finally:
        stop.set()
        gateway.close()


def test_goal_sync_pulls_and_merges_without_force(tmp_path: Path) -> None:
    import os
    import subprocess

    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "sync-test",
            "GIT_AUTHOR_EMAIL": "sync-test@example.com",
            "GIT_COMMITTER_NAME": "sync-test",
            "GIT_COMMITTER_EMAIL": "sync-test@example.com",
        }
    )

    def git(repo: Path, *args: str) -> None:
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env=env)

    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
    first = tmp_path / "first"
    subprocess.run(["git", "init", "-b", "main", str(first)], check=True, capture_output=True, env=env)
    compiler = first / "ipfs_datasets_py/logic/legal_ir/canonical_compiler.py"
    compiler.parent.mkdir(parents=True)
    compiler.write_text("def compile():\n    return 1\n", encoding="utf-8")
    git(first, "add", str(compiler))
    git(first, "commit", "-m", "base")
    git(first, "remote", "add", "origin", str(origin))
    git(first, "push", "-u", "origin", "main")
    second = tmp_path / "second"
    subprocess.run(
        ["git", "clone", "--branch", "main", str(origin), str(second)],
        check=True,
        capture_output=True,
        env=env,
    )
    other = second / "ipfs_datasets_py/logic/legal_ir/canonical_compiler.py"
    other.write_text("def compile():\n    return 3\n", encoding="utf-8")
    git(second, "add", str(other))
    git(second, "commit", "-m", "other machine")
    git(second, "push", "origin", "HEAD:main")
    compiler.write_text("def compile():\n    return 2\n", encoding="utf-8")
    git(first, "add", str(compiler))
    git(first, "commit", "-m", "local compiler edit")
    receipt = sync_origin_main(first, push=True)
    assert receipt["conflict"] is True
    assert receipt["pushed"] is False
    assert any(str(path).endswith("canonical_compiler.py") for path in receipt["conflict_paths"])
