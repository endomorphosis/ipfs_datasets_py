"""Sealed span cache skips compiles and unseals dependents when terms change."""
from __future__ import annotations

from pathlib import Path

from ipfs_datasets_py.huggingface.autoformal_span_cache import build_span_cache_package, flush_span_cache
from ipfs_datasets_py.logic.autoformal.span_cache import SpanCache, terms_from_rule
from ipfs_datasets_py.logic.autoformal.supervisor_loop import recensus_open_todos


def _rule() -> dict:
    return {"modality": "obligation", "actor": "Agency", "action": "make", "object": "records"}


def _agreed(span_id: str = "s1") -> dict:
    return {
        "agrees": True,
        "decompiled": "Agency must make records available.",
        "id": span_id,
        "legal_id": "usc:us:5:552",
        "reason": "",
        "rule": _rule(),
        "skipped": False,
        "source_span_id": span_id,
        "text": "Each agency shall make records available.",
    }


def _gap(span_id: str = "g1") -> dict:
    return {
        "agrees": False,
        "id": span_id,
        "legal_id": "usc:us:18:1001",
        "reason": "CanonicalErrorCode.UNSUPPORTED_SEMANTICS:penalty",
        "skipped": False,
        "source_span_id": span_id,
        "text": "Whoever shall be imprisoned.",
    }


def test_resume_parquet_carries_board_seals_and_agent(tmp_path: Path) -> None:
    cache = SpanCache(tmp_path / "cache.duckdb")
    cache.save_checkpoint(documents=12, parquet="/data/laws.parquet")
    cache.register_agent("agent-a", dataset_id="justicedao/ipfs_uscode", role="compile")
    cache.enqueue(
        [
            {"source_span_id": "s1", "text": "Each agency shall make records available.", "legal_id": "usc:us:5:552"},
            {"source_span_id": "s2", "text": "Whoever shall be imprisoned.", "legal_id": "usc:us:18:1001"},
        ]
    )
    cache.claim_batch("agent-a", limit=1)
    cache.apply_census(
        {"rows": [_agreed("s1")]},
        path_hashes={"ipfs_datasets_py/logic/deontic/utils/deontic_parser.py": "aaa"},
        code_identity="sha256:test",
    )
    path = tmp_path / "resume-checkpoint.parquet"
    written = cache.write_resume_parquet(path)
    assert path.suffix == ".parquet"
    assert written["jsonl_written"] is False
    assert not (tmp_path / "resume-checkpoint.json").exists()
    summary = cache.resume_summary(path)
    assert summary["documents"] == 12
    assert summary["kinds"].get("meta") == 1
    assert summary["kinds"].get("agent") == 1
    assert summary["kinds"].get("board", 0) >= 1
    assert summary["kinds"].get("seal", 0) >= 1
    assert summary["kinds"].get("span") == 2
    assert summary["admitted"] is False
    other = SpanCache(tmp_path / "other.duckdb")
    other.register_agent("agent-b", dataset_id="justicedao/ipfs_uscode", role="compile")
    other.enqueue(
        [{"source_span_id": "s9", "text": "The clerk shall keep a journal.", "legal_id": "usc:us:1:1"}]
    )
    assert other.claim_batch("agent-b", limit=5)[0]["source_span_id"] == "s9"
    assert other.release_stale_claims("agent-a") == 0
    assert other.release_stale_claims("agent-b") == 1
    other.close()
    cache.close()


def test_checkpoint_resumes_after_the_last_committed_document(tmp_path: Path) -> None:
    cache = SpanCache(tmp_path / "cache.duckdb")
    cache.save_checkpoint(documents=4608, parquet="/data/laws.parquet")
    point = cache.checkpoint()
    assert point["documents"] == 4608
    assert point["parquet"] == "/data/laws.parquet"
    assert point["admitted"] is False
    cache.enqueue(
        [{"source_span_id": "s1", "text": "Each agency shall make records available.", "legal_id": "usc:us:5:552"}]
    )
    claimed = cache.claim_batch("control-plane", limit=1)
    assert claimed[0]["source_span_id"] == "s1"
    assert cache.release_stale_claims() == 1
    assert cache.pending(limit=5)[0]["source_span_id"] == "s1"
    cache.close()


def test_claim_batch_is_exclusive_until_completed(tmp_path: Path) -> None:
    cache = SpanCache(tmp_path / "cache.duckdb")
    cache.enqueue(
        [
            {"source_span_id": "s1", "text": "Each agency shall make records available.", "legal_id": "usc:us:5:552"},
            {"source_span_id": "s2", "text": "Whoever shall be imprisoned.", "legal_id": "usc:us:18:1001"},
        ]
    )
    first = cache.claim_batch("control-plane", limit=10)
    assert {item["source_span_id"] for item in first} == {"s1", "s2"}
    assert cache.claim_batch("control-plane", limit=10) == []
    done = cache.complete_claimed(
        [
            {
                "agrees": True,
                "decompiled": "Agency must make records available.",
                "legal_id": "usc:us:5:552",
                "rule": {"modality": "obligation", "actor": "Agency", "action": "make", "object": "records"},
                "source_span_id": "s1",
                "text": "Each agency shall make records available.",
            },
            {
                "agrees": False,
                "decompiled": "",
                "legal_id": "usc:us:18:1001",
                "reason": "no_parser_elements",
                "source_span_id": "s2",
                "text": "Whoever shall be imprisoned.",
            },
        ],
        code_identity="sha256:test",
        path_hashes={"ipfs_datasets_py/logic/deontic/utils/deontic_parser.py": "aaa"},
    )
    assert done["sealed"] == 1
    assert done["gaps"] == 1
    assert done["admitted"] is False
    assert cache.skip_compile("s1", source_text="Each agency shall make records available.") is not None
    cache.close()


def test_terms_from_rule_name_actor_action_object() -> None:
    terms = terms_from_rule(_rule(), decompiled="Agency must make records available.")
    kinds = {item["kind"] for item in terms}
    assert {"modality", "actor", "action", "object", "decompiled"} <= kinds


def test_seal_skips_compile_and_unseals_when_parser_hash_changes(tmp_path: Path) -> None:
    cache = SpanCache(tmp_path / "cache.duckdb")
    parser = "ipfs_datasets_py/logic/deontic/utils/deontic_parser.py"
    hashes = {parser: "aaa"}
    first = cache.apply_census({"rows": [_agreed(), _gap()]}, path_hashes=hashes)
    assert first["sealed"] == 1
    assert first["gaps"] == 1
    assert first["admitted"] is False
    cached = cache.skip_compile("s1", source_text="Each agency shall make records available.")
    assert cached is not None
    assert cached["skipped_compile"] is True
    assert cached["agrees"] is True
    changed = cache.unseal_changed({parser: "bbb"})
    assert changed["unsealed"] == 1
    assert "s1" in changed["unsealed_ids"]
    assert cache.skip_compile("s1", source_text="Each agency shall make records available.") is None
    cache.close()


def test_process_pending_skips_sealed_and_compiles_unsealed(tmp_path: Path) -> None:
    cache = SpanCache(tmp_path / "cache.duckdb")
    parser = "ipfs_datasets_py/logic/deontic/utils/deontic_parser.py"
    cache.apply_census({"rows": [_agreed("s1")]}, path_hashes={parser: "aaa"})
    cache.enqueue([{"source_span_id": "s2", "text": "The clerk shall keep a journal.", "legal_id": "usc:us:1:1"}])
    calls = []

    def compile_one(text: str):
        calls.append(text)
        return {
            "compiler_status": "compiled",
            "decompiled": "Clerk must keep a journal.",
            "reason": "",
            "rule": {"modality": "obligation", "actor": "Clerk", "action": "keep", "object": "journal"},
        }

    receipt = cache.process_pending(compile_one, path_hashes={parser: "aaa"})
    assert receipt["processed"] == 1
    assert len(calls) == 1
    assert cache.stats()["sealed"] == 2
    cache.close()


def test_loop_uses_sealed_cache_on_recensus(tmp_path: Path) -> None:
    cache = SpanCache(tmp_path / "cache.duckdb")
    cache.apply_census(
        {"rows": [_agreed()]},
        path_hashes={"ipfs_datasets_py/logic/deontic/utils/deontic_parser.py": "aaa"},
    )
    compile_calls = {"n": 0}

    def compile_one(text: str):
        compile_calls["n"] += 1
        return {"compiler_status": "abstain", "reason": "penalty", "decompiled": ""}

    prior = {
        "population": {
            "tasks": [
                {
                    "source_span_id": "s1",
                    "source_text": "Each agency shall make records available.",
                    "legal_id": "usc:us:5:552",
                },
                {
                    "source_span_id": "g1",
                    "source_text": "Whoever shall be imprisoned.",
                    "legal_id": "usc:us:18:1001",
                },
            ]
        }
    }
    tick = recensus_open_todos(prior, compile_one, span_cache=cache)
    assert compile_calls["n"] == 1
    by_id = {row["source_span_id"]: row for row in tick["agreement"]["rows"]}
    assert by_id["s1"]["agrees"] is True
    assert by_id["s1"].get("skipped_compile") is True
    assert by_id["g1"]["agrees"] is False
    cache.close()


def test_supervisor_loop_emits_cache_progress(tmp_path: Path) -> None:
    from ipfs_datasets_py.logic.autoformal.supervisor_loop import run_supervisor_loop

    cache = SpanCache(tmp_path / "cache.duckdb")
    lines: list[str] = []
    receipt = run_supervisor_loop(
        lambda: {"rows": [_agreed(), _gap()]},
        ingest=lambda *a, **k: {"task_count": 1},
        max_rounds=1,
        board_path=tmp_path / "loop.todo.md",
        log=lines.append,
        span_cache=cache,
        path_hashes={"ipfs_datasets_py/logic/deontic/utils/deontic_parser.py": "aaa"},
        code_identity="sha256:test",
    )
    joined = "\n".join(lines)
    assert "CACHE round=1" in joined
    assert "STATUTE legal_id=" in joined
    assert "TERM kind=" in joined
    assert receipt["span_cache"]["sealed_total"] == 1
    assert receipt["admitted"] is False
    cache.close()


def test_flush_writes_parquet_not_jsonl(tmp_path: Path) -> None:
    cache = SpanCache(tmp_path / "cache.duckdb")
    cache.apply_census(
        {"rows": [_agreed()]},
        path_hashes={"ipfs_datasets_py/logic/deontic/utils/deontic_parser.py": "aaa"},
    )
    package = build_span_cache_package(cache.sealed_rows(), tmp_path / "pkg")
    assert package["jsonl_written"] is False
    assert package["row_count"] == 1
    assert (tmp_path / "pkg" / "sealed-spans.parquet").is_file()
    assert not list((tmp_path / "pkg").glob("*.jsonl"))
    flushed = flush_span_cache(cache.sealed_rows(), tmp_path / "pkg2", dry_run=True)
    assert flushed["dry_run"] is True
    assert flushed["uploaded"] is False
    assert flushed["remote_write_contacted"] is False
    cache.close()
