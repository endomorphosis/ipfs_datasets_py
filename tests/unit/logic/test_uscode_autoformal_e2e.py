"""Subprocess end-to-end: CLI ingest, DuckDB native queue, Hugging Face, schedule."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


DATASETS_ROOT = Path(__file__).resolve().parents[3]
ACCEL_ROOT = DATASETS_ROOT.parent / "ipfs_accelerate"
RUNNER = DATASETS_ROOT / "scripts/ops/legal_ir/run_uscode_on_sparse_graphrag.py"
CONSTITUTION = DATASETS_ROOT / "scripts/ops/legal_ir/run_constitution_on_state.py"


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ACCEL_ROOT), str(DATASETS_ROOT), env.get("PYTHONPATH", "")]
    )
    env["IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI"] = "0"
    return env


def _run(args: list[str], *, cwd: Path, script: Path = RUNNER) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=cwd,
        env=_env(),
        check=False,
        capture_output=True,
        text=True,
    )


def test_subprocess_cli_hits_duckdb_huggingface_and_schedule(tmp_path: Path) -> None:
    if not (ACCEL_ROOT / "ipfs_accelerate_py").is_dir():
        pytest.skip("outer ipfs_accelerate checkout is missing")
    hits = tmp_path / "hits.json"
    hits.write_text(
        json.dumps(
            [
                {
                    "entry_cid": "bafkreiabc",
                    "legal_id": "usc:us:5:552",
                    "title": "5",
                    "section": "552",
                    "text": "Whoever knowingly and willfully falsifies a material fact shall be fined under this title.",
                }
            ]
        ),
        encoding="utf-8",
    )
    result = _run(
        [
            "--hits",
            str(hits),
            "--query",
            "agency records",
            "--release-id",
            "e2e-duckdb-v1",
            "--board",
            str(tmp_path / "board.md"),
            "--huggingface-package",
            str(tmp_path / "hf"),
            "--pointer",
            str(tmp_path / "pointer.json"),
            "--schedule-queue",
            str(tmp_path / "queue.json"),
            "--database",
            str(tmp_path / "control.duckdb"),
            "--runtime-root",
            str(tmp_path / "runtime"),
            "--code-identity",
            "compiler-tree-e2e",
            "--model-identity",
            "checkpoint-e2e",
            "--max-tokens",
            "50000",
        ],
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    assert "jsonl_written=false" in result.stdout
    assert "wrote_compiler=False" in result.stdout
    assert "native_inserted=1" in result.stdout
    assert (tmp_path / "board.md").is_file()
    assert "## AFTD-" in (tmp_path / "board.md").read_text(encoding="utf-8")
    assert (tmp_path / "hf" / "todos.parquet").is_file()
    assert (tmp_path / "pointer.json").is_file()
    assert (tmp_path / "control.duckdb").is_file()
    assert (tmp_path / "queue.json").is_file()
    assert list((tmp_path / "runtime" / "packets").glob("*.json"))
    assert not list(tmp_path.rglob("*.jsonl"))


def test_subprocess_cli_graphrag_root_exits_clean(tmp_path: Path) -> None:
    import importlib.util

    remote = DATASETS_ROOT / "tests/unit/retrieval/hf_graphrag/test_remote_search.py"
    spec = importlib.util.spec_from_file_location("hf_graphrag_e2e_fixture", remote)
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    release = tmp_path / "release"
    release.mkdir()
    fixture.build_mini_release(release)
    result = _run(
        [
            "--query",
            "foia agency",
            "--graphrag-root",
            str(release),
            "--graphrag-repo-id",
            fixture.REPO_ID,
            "--graphrag-revision",
            fixture.PINNED_REVISION,
            "--graphrag-cache",
            str(tmp_path / "cache"),
            "--board",
            str(tmp_path / "board.md"),
            "--huggingface-package",
            str(tmp_path / "hf"),
            "--pointer",
            str(tmp_path / "pointer.json"),
            "--skip-upload",
        ],
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    assert "jsonl_written=false" in result.stdout
    assert not list(tmp_path.rglob("*.jsonl"))


def test_subprocess_constitution_packages_and_schedules(tmp_path: Path) -> None:
    source = tmp_path / "constitution.txt"
    source.write_text(
        "Article I\n"
        "Whoever knowingly and willfully falsifies a material fact shall be fined under this title.\n"
    )
    result = _run(
        [
            "--compiler-only",
            "--constitution",
            str(source),
            "--output",
            str(tmp_path / "receipt.json"),
            "--huggingface-package",
            str(tmp_path / "hf"),
            "--pointer",
            str(tmp_path / "pointer.json"),
            "--board",
            str(tmp_path / "constitution.todo.md"),
            "--schedule-queue",
            str(tmp_path / "queue.json"),
            "--max-tokens",
            "50000",
        ],
        cwd=tmp_path,
        script=CONSTITUTION,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    assert "jsonl_written=false" in result.stdout
    receipt = json.loads((tmp_path / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["formalized"] is False
    assert receipt["jsonl_written"] is False
    assert receipt["supervisor"]["task_count"] >= 1
    assert (tmp_path / "constitution.todo.md").is_file()
    assert "## AFTD-" in (tmp_path / "constitution.todo.md").read_text(encoding="utf-8")
    assert (tmp_path / "hf" / "todos.parquet").is_file()
    assert (tmp_path / "pointer.json").is_file()
    assert (tmp_path / "queue.json").is_file()
    assert not list(tmp_path.rglob("*.jsonl"))


def test_subprocess_graphrag_then_schedule_when_pointer_exists(tmp_path: Path) -> None:
    import importlib.util

    remote = DATASETS_ROOT / "tests/unit/retrieval/hf_graphrag/test_remote_search.py"
    spec = importlib.util.spec_from_file_location("hf_graphrag_schedule_e2e_fixture", remote)
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    release = tmp_path / "release"
    release.mkdir()
    fixture.build_mini_release(release)
    result = _run(
        [
            "--query",
            "foia agency",
            "--graphrag-root",
            str(release),
            "--graphrag-repo-id",
            fixture.REPO_ID,
            "--graphrag-revision",
            fixture.PINNED_REVISION,
            "--graphrag-cache",
            str(tmp_path / "cache"),
            "--release-id",
            "e2e-graphrag-schedule-v1",
            "--board",
            str(tmp_path / "board.md"),
            "--huggingface-package",
            str(tmp_path / "hf"),
            "--pointer",
            str(tmp_path / "pointer.json"),
        ],
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    assert "jsonl_written=false" in result.stdout
    assert not list(tmp_path.rglob("*.jsonl"))
    pointer = tmp_path / "pointer.json"
    if not pointer.is_file():
        return
    scheduler = DATASETS_ROOT / "scripts/ops/legal_ir/schedule_uscode_autoformal_todos.py"
    scheduled = subprocess.run(
        [
            sys.executable,
            str(scheduler),
            "--accelerate-root",
            str(ACCEL_ROOT),
            "--pointer",
            str(pointer),
            "--repo-root",
            str(tmp_path),
            "--board",
            str(tmp_path / "scheduled.md"),
            "--queue",
            str(tmp_path / "queue.json"),
            "--package-root",
            str(tmp_path / "hf"),
            "--max-tokens",
            "50000",
        ],
        cwd=tmp_path,
        env=_env(),
        check=False,
        capture_output=True,
        text=True,
    )
    assert scheduled.returncode == 0, scheduled.stdout + "\n" + scheduled.stderr
    assert (tmp_path / "queue.json").is_file()
    assert (tmp_path / "scheduled.md").is_file()


def test_subprocess_supervisor_loop_converts_errors_to_todos_and_goals(tmp_path: Path) -> None:
    hits = tmp_path / "hits.json"
    hits.write_text(
        json.dumps(
            [
                {
                    "entry_cid": "cid-0",
                    "legal_id": "usc:us:5:552",
                    "title": "5",
                    "section": "552",
                    "text": "Each agency shall make records available.",
                },
                {
                    "entry_cid": "cid-1",
                    "legal_id": "usc:us:18:1001",
                    "title": "18",
                    "section": "1001",
                    "text": "Whoever knowingly and willfully falsifies a material fact shall be fined under this title.",
                },
                {
                    "entry_cid": "cid-2",
                    "legal_id": "usc:us:18:1001",
                    "title": "18",
                    "section": "1001",
                    "text": "Whoever makes a false statement in any matter within the jurisdiction of the executive branch shall be imprisoned.",
                },
            ]
        ),
        encoding="utf-8",
    )
    board = tmp_path / "loop.todo.md"
    result = _run(
        [
            "--hits",
            str(hits),
            "--query",
            "false statements",
            "--release-id",
            "loop-e2e-v1",
            "--max-rounds",
            "3",
            "--board",
            str(board),
            "--skip-upload",
        ],
        cwd=tmp_path,
        script=DATASETS_ROOT / "scripts/ops/legal_ir/run_autoformal_supervisor_loop.py",
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    summary = json.loads(result.stdout.strip().splitlines()[-1])
    assert summary["admitted"] is False
    assert summary["formalized"] is False
    assert summary["jsonl_written"] is False
    assert summary["wrote_compiler"] is False
    assert int(summary.get("compiled_count") or 0) >= 1
    assert int(summary.get("remaining_count") or 0) >= 1
    assert "CENSUS round=" in result.stdout
    assert "CENSUS span id=" in result.stdout
    assert "LAKE round=" in result.stdout
    assert "PROGRESS round=" in result.stdout
    assert Path(summary.get("census_path") or "").is_file()
    assert Path(summary.get("progress_log_path") or "").is_file()
    assert summary.get("progress", {}).get("compiled_count") == summary["compiled_count"]
    assert summary["todo_count"] >= 1
    assert summary["stop_reason"] in {
        "no_new_errors",
        "no_outstanding_todos",
        "max_rounds",
        "goals_resolved",
    }
    markdown = board.read_text(encoding="utf-8")
    assert "## AFTD-" in markdown
    assert "- Preserve:" in markdown
    assert "- Replace:" in markdown
    assert "- Formalized: false" in markdown
    assert "proposed_compiler" not in markdown.casefold()
    assert not list(tmp_path.rglob("*.jsonl"))
    if "## AFTD-G" in markdown:
        assert "- Kind:" in markdown
        assert "- Resolves:" in markdown


def test_subprocess_supervisor_loop_ingests_duckdb_goal_tree(tmp_path: Path) -> None:
    if not (ACCEL_ROOT / "ipfs_accelerate_py").is_dir():
        pytest.skip("outer ipfs_accelerate checkout is missing")
    hits = tmp_path / "hits.json"
    hits.write_text(
        json.dumps(
            [
                {
                    "legal_id": "usc:us:18:1001",
                    "title": "18",
                    "section": "1001",
                    "text": "Whoever knowingly and willfully falsifies a material fact shall be fined under this title.",
                },
                {
                    "legal_id": "usc:us:18:1519",
                    "title": "18",
                    "section": "1519",
                    "text": "Whoever makes a false statement in any matter within the jurisdiction of the executive branch shall be imprisoned.",
                },
            ]
        ),
        encoding="utf-8",
    )
    result = _run(
        [
            "--hits",
            str(hits),
            "--query",
            "false statements",
            "--release-id",
            "loop-duckdb-v1",
            "--max-rounds",
            "2",
            "--board",
            str(tmp_path / "loop.todo.md"),
            "--accelerate-root",
            str(ACCEL_ROOT),
            "--database",
            str(tmp_path / "control.duckdb"),
            "--huggingface-package",
            str(tmp_path / "hf"),
            "--pointer",
            str(tmp_path / "pointer.json"),
            "--schedule-queue",
            str(tmp_path / "queue.json"),
            "--max-tokens",
            "50000",
        ],
        cwd=tmp_path,
        script=DATASETS_ROOT / "scripts/ops/legal_ir/run_autoformal_supervisor_loop.py",
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    summary = json.loads(result.stdout.strip().splitlines()[-1])
    assert summary["todo_count"] >= 1
    assert summary["jsonl_written"] is False
    assert int(summary.get("native_task_count") or 0) >= 1
    assert int(summary.get("native_goal_count") or 0) >= 1
    assert (tmp_path / "control.duckdb").is_file()
    assert (tmp_path / "loop.todo.md").is_file()
    population = tmp_path / "loop.todo.population.json"
    assert population.is_file()
    payload = json.loads(population.read_text(encoding="utf-8"))
    assert payload["population"]["tasks"]
    assert payload["population"]["goals"]
    assert payload["jsonl_written"] is False
    assert (tmp_path / "hf" / "todos.parquet").is_file()
    assert (tmp_path / "pointer.json").is_file()
    assert (tmp_path / "queue.json").is_file()
    assert summary.get("scheduled_task_ids")
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "from ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source import DatabaseTaskSource\n"
            f"src = DatabaseTaskSource(r'{tmp_path / 'control.duckdb'}', install_schema=False)\n"
            "page = src.list_tasks(limit=20)\n"
            "print(len(page.tasks))\n"
            "print(page.tasks[0].goal_cid if page.tasks else '')\n"
            "print(page.tasks[0].plan_cid if page.tasks else '')\n"
            "src.close()\n",
        ],
        cwd=tmp_path,
        env=_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert probe.returncode == 0, probe.stdout + "\n" + probe.stderr
    count, goal_cid, plan_cid = probe.stdout.strip().splitlines()[-3:]
    assert int(count) >= 1
    assert goal_cid.startswith("goal:")
    assert plan_cid.startswith("plan:")
    resume = _run(
        [
            "--hits",
            str(hits),
            "--query",
            "false statements",
            "--release-id",
            "loop-duckdb-v1",
            "--max-rounds",
            "1",
            "--board",
            str(tmp_path / "loop.todo.md"),
            "--skip-upload",
            "--accelerate-root",
            str(ACCEL_ROOT),
            "--database",
            str(tmp_path / "control.duckdb"),
            "--population-in",
            str(population),
            "--population-out",
            str(tmp_path / "loop.todo.population.json"),
        ],
        cwd=tmp_path,
        script=DATASETS_ROOT / "scripts/ops/legal_ir/run_autoformal_supervisor_loop.py",
    )
    assert resume.returncode == 0, resume.stdout + "\n" + resume.stderr
    resumed = json.loads(resume.stdout.strip().splitlines()[-1])
    assert resumed["stop_reason"] in {"no_new_errors", "goals_resolved", "max_rounds"}
    assert resumed["jsonl_written"] is False
    recensus = _run(
        [
            "--recensus",
            "--population-in",
            str(population),
            "--population-out",
            str(tmp_path / "loop.todo.population.json"),
            "--board",
            str(tmp_path / "loop.todo.md"),
            "--skip-upload",
            "--max-rounds",
            "1",
            "--release-id",
            "loop-duckdb-v1",
            "--accelerate-root",
            str(ACCEL_ROOT),
            "--database",
            str(tmp_path / "control.duckdb"),
        ],
        cwd=tmp_path,
        script=DATASETS_ROOT / "scripts/ops/legal_ir/run_autoformal_supervisor_loop.py",
    )
    assert recensus.returncode == 0, recensus.stdout + "\n" + recensus.stderr
    recensed = json.loads(recensus.stdout.strip().splitlines()[-1])
    assert recensed["jsonl_written"] is False
    assert recensed["wrote_compiler"] is False
    assert recensed["admitted"] is False
    progress = tmp_path / "loop.todo.progress.log"
    assert progress.is_file()
    logged = progress.read_text(encoding="utf-8")
    assert "PROGRESS round=" in logged
    assert "remaining=" in logged


def test_subprocess_supervise_graphrag_query_logs_progress(tmp_path: Path) -> None:
    import importlib.util

    if not (ACCEL_ROOT / "ipfs_accelerate_py").is_dir():
        pytest.skip("outer ipfs_accelerate checkout is missing")
    remote = DATASETS_ROOT / "tests/unit/retrieval/hf_graphrag/test_remote_search.py"
    spec = importlib.util.spec_from_file_location("hf_graphrag_supervise_fixture", remote)
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    release = tmp_path / "release"
    release.mkdir()
    fixture.build_mini_release(release)
    result = subprocess.run(
        [
            sys.executable,
            str(DATASETS_ROOT / "scripts/ops/legal_ir/run_autoformal_supervisor.py"),
            "--accelerate-root",
            str(ACCEL_ROOT),
            "--database",
            str(tmp_path / "control.duckdb"),
            "--runtime-root",
            str(tmp_path / "runtime"),
            "supervise",
            "--once",
            "--query",
            "foia agency",
            "--graphrag-root",
            str(release),
            "--graphrag-repo-id",
            fixture.REPO_ID,
            "--graphrag-revision",
            fixture.PINNED_REVISION,
            "--graphrag-cache",
            str(tmp_path / "cache"),
            "--max-rounds",
            "2",
            "--board",
            str(tmp_path / "runtime" / "loop.todo.md"),
        ],
        cwd=tmp_path,
        env=_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    assert "PROGRESS round=" in result.stdout
    assert "compiled=" in result.stdout
    summary = json.loads(result.stdout.strip().splitlines()[-1])
    assert summary["tasks_claimed"] is False
    assert summary["jsonl_written"] is False
    progress = tmp_path / "runtime" / "loop.todo.progress.log"
    assert progress.is_file()
    assert "PROGRESS stop=" in progress.read_text(encoding="utf-8")


def test_subprocess_supervise_autoformal_loop_runs_and_recensus(tmp_path: Path) -> None:
    if not (ACCEL_ROOT / "ipfs_accelerate_py").is_dir():
        pytest.skip("outer ipfs_accelerate checkout is missing")
    hits = tmp_path / "hits.json"
    hits.write_text(
        json.dumps(
            [
                {
                    "legal_id": "usc:us:18:1001",
                    "title": "18",
                    "section": "1001",
                    "text": "Whoever knowingly and willfully falsifies a material fact shall be fined under this title.",
                }
            ]
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            str(DATASETS_ROOT / "scripts/ops/legal_ir/run_autoformal_supervisor.py"),
            "--accelerate-root",
            str(ACCEL_ROOT),
            "--database",
            str(tmp_path / "control.duckdb"),
            "--runtime-root",
            str(tmp_path / "runtime"),
            "supervise",
            "--once",
            "--hits",
            str(hits),
            "--release-id",
            "supervise-loop-v1",
            "--max-rounds",
            "2",
            "--board",
            str(tmp_path / "runtime" / "loop.todo.md"),
        ],
        cwd=tmp_path,
        env=_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    summary = json.loads(result.stdout.strip().splitlines()[-1])
    assert summary["tasks_claimed"] is False
    assert summary["jsonl_written"] is False
    assert "PROGRESS round=" in result.stdout
    assert "remaining=" in result.stdout
    assert summary["recensus"]["command"] == "supervise-autoformal-recensus"
    assert summary["recensus"]["tasks_claimed"] is False
    assert int(summary.get("native_task_count") or 0) >= 1
    assert Path(summary["population_path"]).is_file()


def test_subprocess_native_supervisor_loop_command(tmp_path: Path) -> None:
    if not (ACCEL_ROOT / "ipfs_accelerate_py").is_dir():
        pytest.skip("outer ipfs_accelerate checkout is missing")
    hits = tmp_path / "hits.json"
    hits.write_text(
        json.dumps(
            [
                {
                    "legal_id": "usc:us:5:552",
                    "title": "5",
                    "section": "552",
                    "text": "Each agency shall make records available.",
                },
                {
                    "legal_id": "usc:us:18:1001",
                    "title": "18",
                    "section": "1001",
                    "text": "Whoever knowingly and willfully falsifies a material fact shall be fined under this title.",
                },
                {
                    "legal_id": "usc:us:18:1519",
                    "title": "18",
                    "section": "1519",
                    "text": "Whoever makes a false statement in any matter within the jurisdiction of the executive branch shall be imprisoned.",
                },
            ]
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            str(DATASETS_ROOT / "scripts/ops/legal_ir/run_autoformal_supervisor.py"),
            "--accelerate-root",
            str(ACCEL_ROOT),
            "--database",
            str(tmp_path / "control.duckdb"),
            "--runtime-root",
            str(tmp_path / "runtime"),
            "loop",
            "--hits",
            str(hits),
            "--query",
            "false statements",
            "--release-id",
            "native-loop-v1",
            "--max-rounds",
            "2",
            "--board",
            str(tmp_path / "runtime" / "loop.todo.md"),
        ],
        cwd=tmp_path,
        env=_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    summary = json.loads(result.stdout.strip().splitlines()[-1])
    assert summary["command"] == "loop"
    assert summary["jsonl_written"] is False
    assert summary["wrote_compiler"] is False
    assert summary["admitted"] is False
    assert int(summary.get("native_task_count") or 0) >= 1
    assert int(summary.get("native_goal_count") or 0) >= 1
    assert Path(summary["population_path"]).is_file()
    assert Path(summary["board_path"]).is_file()
    assert "## AFTD-G" in Path(summary["board_path"]).read_text(encoding="utf-8") or "## AFTD-" in Path(summary["board_path"]).read_text(encoding="utf-8")
    census = Path(summary.get("census_path") or Path(summary["board_path"]).with_name(Path(summary["board_path"]).stem + ".census.json"))
    assert census.is_file()
    counts = json.loads(census.read_text(encoding="utf-8"))
    assert int(counts.get("compiled_count") or 0) >= 1
    assert int(counts.get("remaining_count") or 0) >= 1
    assert counts["admitted"] is False
    assert "CENSUS round=" in result.stdout
    assert int(summary.get("compiled_count") or 0) >= 1
    assert summary.get("progress", {}).get("rounds")
