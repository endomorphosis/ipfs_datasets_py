"""Gap replay trains on compile success, not cross-entropy or cosine."""
import hashlib
from pathlib import Path

from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span
from ipfs_datasets_py.logic.autoformal.gap_compile_replay import (
    CompileReplayMemory,
    FailureClassLedger,
    codec_reconstruct,
    compile_miss,
    failure_class,
    replay_gaps,
    replay_until_compiled,
    submit_compiler_failure_goals,
    upsert_failure_goals_through_quack,
)
from ipfs_datasets_py.logic.autoformal.span_cache import SpanCache


def test_compile_replay_is_separate_from_embedding_losses() -> None:
    source = Path(
        "/home/barberb/lift_coding/external/ipfs_datasets/ipfs_datasets_py/logic/autoformal/gap_compile_replay.py"
    ).read_text(encoding="utf-8")
    assert "cross_entropy_loss(" not in source
    assert "cosine_loss(" not in source
    assert "cosine_similarity(" not in source
    assert compile_miss(True) == 0.0
    assert compile_miss(False) == 1.0


def test_replay_scores_reconstructed_text_against_the_compiler(tmp_path: Path) -> None:
    cache = SpanCache(tmp_path / "spans.duckdb")
    cache.enqueue(
        [
            {"source_span_id": "gap-1", "text": "Whoever shall be imprisoned.", "legal_id": "usc:us:18:1001"},
            {"source_span_id": "gap-2", "text": "Each agency shall make records available.", "legal_id": "usc:us:5:552"},
        ]
    )
    cache._db.execute("UPDATE span_cache SET status = 'gap', reason = 'no_parser_elements'")
    gaps = cache.list_gaps(limit=10)
    assert [row["source_span_id"] for row in gaps] == ["gap-1", "gap-2"]

    def reconstruct(text: str) -> str:
        if "imprisoned" in text:
            return "Each agency shall make records available."
        return text

    def compile_one(text: str) -> dict:
        if text == "Each agency shall make records available.":
            return {"compiler_status": "compiled", "decompiled": "Agency must make records available."}
        return {"compiler_status": "abstain", "decompiled": "", "reason": "no_parser_elements"}

    memory = CompileReplayMemory()
    seen: list[bool] = []
    report = replay_gaps(
        gaps,
        reconstruct,
        compile_one,
        observe=lambda row: (seen.append(row["compiled"]), memory.observe(row)),
    )
    assert report["replayed"] == 2
    assert report["compiled"] == 2
    assert report["loss"] == 0.0
    assert report["objective"] == "compile_replay"
    assert report["admitted"] is False
    assert report["wrote_compiler"] is False
    assert seen == [True, True]
    assert memory.receipt()["compiled"] == 2
    assert memory.receipt()["admitted"] is False
    assert memory.accepted["gap-1"] == "Each agency shall make records available."
    cache.close()


def test_real_compiler_failed_span_passes_after_replay() -> None:
    def compile_one(text: str) -> dict:
        return compile_span(AutoformalSession(), text, "gap-" + str(abs(hash(text))))

    span = {
        "legal_id": "usc:us:18:1001",
        "source_span_id": "gap-penalty",
        "text": "Whoever shall be imprisoned.",
    }
    memory = CompileReplayMemory()
    first = replay_until_compiled(span, [], compile_one, memory)
    assert first["compiled"] is False
    assert first["loss"] == 1.0
    assert "penalty" in str(compile_one(span["text"]).get("reason") or "")

    second = replay_until_compiled(
        span,
        ["A person shall not commit theft."],
        compile_one,
        memory,
    )
    assert second["compiled"] is True
    assert second["decompiled"] == "Person must not commit theft."
    assert second["admitted"] is False

    third = replay_until_compiled(span, [], compile_one, memory)
    assert third["compiled"] is True
    assert third["output_text"] == "A person shall not commit theft."
    assert memory.receipt()["compiled"] >= 2


def test_class_goal_collects_citations_from_later_spans() -> None:
    ledger = FailureClassLedger()
    base = {
        "compiled": False,
        "compiler_reason": "CanonicalErrorCode.UNSUPPORTED_SEMANTICS:cross_references",
        "legal_id": "usc:us:42:1983",
        "output_text": "See the section.",
        "repair": {"citations": [], "fix": "Resolve the cross-reference.", "diagnostic": "CanonicalErrorCode.UNSUPPORTED_SEMANTICS:cross_references"},
    }
    ledger.observe({**base, "source_span_id": "a"})
    ledger.observe(
        {
            **base,
            "source_span_id": "b",
            "repair": {"citations": ["usc:us:42:1983", "123-f3d-456"], "fix": "Resolve the cross-reference."},
        }
    )
    goal = ledger.public_goals()[0]
    assert goal["citations"] == ["usc:us:42:1983", "123-f3d-456"]
    assert "123-f3d-456" in goal["repair"]["fix"]
    assert goal["member_count"] == 2


def test_repair_report_keeps_codec_compiler_and_edit_symbols() -> None:
    from ipfs_datasets_py.logic.autoformal.repair_report import repair_report

    report = repair_report(
        compiler={
            "compiler_status": "abstain",
            "decompiled": "",
            "fields": ["penalty"],
            "reason": "CanonicalErrorCode.UNSUPPORTED_SEMANTICS:penalty",
        },
        autoencoder={
            "decoded_text": "Whoever shall be imprisoned.",
            "formulas": [{"op": "O", "predicate": "imprison", "arguments": ["scope:imprison"]}],
            "structural": "obligation",
        },
    )
    assert report["diagnostic"] == "CanonicalErrorCode.UNSUPPORTED_SEMANTICS:penalty"
    assert "penalty" in report["error"].lower()
    assert "canonical_compiler.py" in " ".join(report["edit_paths"])
    assert report["symbols"]
    assert report["autoencoder"]["formulas"][0]["lake"] == "unrendered"
    assert report["lake"]["refuses"] == ["axiom", "sorry", "admit"]
    frame_report = repair_report(
        compiler={"compiler_status": "abstain", "reason": "no_parser_elements", "fields": ["no_parser_elements"], "decompiled": ""},
        autoencoder={
            "decoded_text": "United States Code",
            "formulas": [{"op": "Frame", "predicate": "united_states_code_edition_title_armed", "arguments": []}],
        },
    )
    assert frame_report["autoencoder"]["formulas"][0]["lake"] == "fixture"
    assert frame_report["autoencoder"]["formulas"][0]["lake_code"] == 6
    cited = repair_report(
        compiler={
            "compiler_status": "abstain",
            "decompiled": "",
            "fields": ["cross_references"],
            "reason": "CanonicalErrorCode.UNSUPPORTED_SEMANTICS:cross_references",
        },
        autoencoder={
            "citations": ["usc:us:42:1983", "123-f3d-456"],
            "decoded_text": "See 42 U.S.C. § 1983 and 123 F.3d 456.",
            "formulas": [],
        },
    )
    assert cited["citations"] == ["usc:us:42:1983", "123-f3d-456"]
    assert "usc:us:42:1983" in cited["fix"]
    assert "123-f3d-456" in cited["fix"]
    assert report["admitted"] is False
    assert report["formalized"] is False
    assert report["wrote_compiler"] is False


def test_gap_row_stores_the_repair_capsule(tmp_path: Path) -> None:
    from ipfs_datasets_py.logic.autoformal.repair_report import repair_report

    report = repair_report(
        compiler={"compiler_status": "abstain", "reason": "no_parser_elements", "fields": ["no_parser_elements"], "decompiled": ""},
        autoencoder={"decoded_text": "L.", "formulas": [], "structural": ""},
    )
    cache = SpanCache(tmp_path / "span-cache.duckdb")
    cache.enqueue([{"source_span_id": "gap-1", "text": "L.", "legal_id": "usc:us:10:1"}])
    cache.apply_census(
        {
            "rows": [
                {
                    "agrees": False,
                    "decompiled": "",
                    "legal_id": "usc:us:10:1",
                    "reason": "no_parser_elements",
                    "repair": report,
                    "source_span_id": "gap-1",
                    "text": "L.",
                }
            ]
        }
    )
    gaps = cache.list_gaps()
    cache.close()
    assert gaps[0]["reason"] == "no_parser_elements"
    assert "actor and action" in gaps[0]["repair"]["fix"]
    assert gaps[0]["repair"]["admitted"] is False


def test_codec_output_that_fails_the_compiler_is_one_class_goal() -> None:
    source = "Whoever shall be imprisoned."
    reconstructed = codec_reconstruct(source)
    assert reconstructed == source
    seen: list[str] = []

    def compile_one(text: str) -> dict:
        seen.append(text)
        return {
            "compiler_status": "abstain",
            "decompiled": "",
            "reason": "CanonicalErrorCode.UNSUPPORTED_SEMANTICS:penalty",
        }

    ledger = FailureClassLedger()
    report = replay_gaps(
        [{"source_span_id": "pen-1", "legal_id": "usc:us:18:1001", "text": source}],
        codec_reconstruct,
        compile_one,
        goals=ledger,
    )
    assert seen == [reconstructed]
    assert report["compiled"] == 0
    assert report["failure_classes"] == 1
    assert report["admitted"] is False
    assert report["wrote_compiler"] is False
    goal = report["failure_goals"][0]
    assert goal["failure_class"] == "CanonicalErrorCode.UNSUPPORTED_SEMANTICS:penalty"
    assert goal["example_outputs"] == [reconstructed]


def test_compiler_failures_become_one_goal_per_class(tmp_path: Path) -> None:
    assert failure_class("CanonicalErrorCode.UNSUPPORTED_SEMANTICS:penalty prose") == (
        "CanonicalErrorCode.UNSUPPORTED_SEMANTICS:penalty"
    )
    assert failure_class("CanonicalErrorCode.UNSUPPORTED_SEMANTICS:penalty") == (
        "CanonicalErrorCode.UNSUPPORTED_SEMANTICS:penalty"
    )
    spans = [
        {"source_span_id": "p1", "text": "Whoever shall be imprisoned.", "legal_id": "usc:us:18:1001"},
        {"source_span_id": "p2", "text": "The agency shall imprison the person.", "legal_id": "usc:us:18:1001"},
        {"source_span_id": "x1", "text": "See section 1001.", "legal_id": "usc:us:18:1001"},
        {"source_span_id": "ok", "text": "Each agency shall make records available.", "legal_id": "usc:us:5:552"},
        {"source_span_id": "empty", "text": "no output", "legal_id": "usc:us:18:1001"},
    ]

    def reconstruct(text: str) -> str:
        if text == "no output":
            return ""
        if text.startswith("See"):
            return "See section 1001 of this title."
        return text

    def compile_one(text: str) -> dict:
        if "records available" in text:
            return {"compiler_status": "compiled", "decompiled": "Agency must make records available.", "reason": ""}
        if text.startswith("See"):
            return {
                "compiler_status": "abstain",
                "decompiled": "",
                "reason": "CanonicalErrorCode.UNSUPPORTED_SEMANTICS:cross_references extra",
            }
        if text:
            return {
                "compiler_status": "abstain",
                "decompiled": "",
                "reason": "CanonicalErrorCode.UNSUPPORTED_SEMANTICS:penalty prose",
            }
        return {"compiler_status": "abstain", "decompiled": "", "reason": "empty"}

    ledger = FailureClassLedger()
    report = replay_gaps(spans, reconstruct, compile_one, goals=ledger)
    assert report["failure_classes"] == 2
    assert report["compiled"] == 1
    assert report["admitted"] is False
    assert report["wrote_compiler"] is False
    replay_gaps(spans, reconstruct, compile_one, goals=ledger)
    assert ledger.class_count() == 2
    assert ledger.duplicate_observations >= 2
    classes = {row["failure_class"] for row in ledger.public_goals()}
    assert classes == {
        "CanonicalErrorCode.UNSUPPORTED_SEMANTICS:penalty",
        "CanonicalErrorCode.UNSUPPORTED_SEMANTICS:cross_references",
    }
    penalty = next(row for row in ledger.public_goals() if row["failure_class"].endswith(":penalty"))
    assert penalty["member_count"] == 2
    assert set(penalty["example_span_ids"]) == {"p1", "p2"}
    assert submit_compiler_failure_goals(FailureClassLedger(), None)["ingested"] is False

    from ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source import DatabaseTaskSource

    with DatabaseTaskSource(tmp_path / "supervisor.duckdb") as source:
        first = submit_compiler_failure_goals(ledger, source)
        second = submit_compiler_failure_goals(ledger, source)
        tasks = source.list_tasks(limit=10).tasks
        assert first["ingested"] is True
        assert first["admitted"] is False
        assert first["formalized"] is False
        assert first["wrote_compiler"] is False
        assert first["classes"] == 2
        assert second["goal_count"] == first["goal_count"]
        assert len(tasks) == 2
        assert {str(task.body.get("failure_class") or "") for task in tasks} == classes
        assert all(task.body.get("work_kind") == "compiler_decompiler_edit" for task in tasks)
        assert all(task.body.get("edit_scope") == "compiler_abstain" for task in tasks)
        assert all(task.body.get("admitted") is False for task in tasks)
        assert all(task.body.get("formalized") is False for task in tasks)
        assert all(task.body.get("wrote_compiler") is False for task in tasks)
        assert source.snapshot().to_dict()["goal_count"] == 3
        seen_goals = set()
        for task in tasks:
            goal = source.intent.get_goal(task.goal_cid)
            assert goal is not None
            assert goal["status"] == "open"
            assert goal["body"]["failure_class"] in classes
            assert goal["body"]["admitted"] is False
            assert goal["body"]["formalized"] is False
            seen_goals.add(goal["goal_cid"])
        assert len(seen_goals) == 2


def test_failure_class_goals_upsert_through_quack_owner(tmp_path: Path) -> None:
    ledger = FailureClassLedger()
    ledger.observe(
        {
            "compiled": False,
            "compiler_reason": "CanonicalErrorCode.UNSUPPORTED_SEMANTICS:penalty prose",
            "legal_id": "usc:us:18:1001",
            "output_text": "Whoever shall be imprisoned.",
            "source_span_id": "pen-1",
        }
    )
    ledger.observe(
        {
            "compiled": False,
            "compiler_reason": "CanonicalErrorCode.UNSUPPORTED_SEMANTICS:penalty",
            "legal_id": "usc:us:18:1001",
            "output_text": "The agency shall imprison the person.",
            "source_span_id": "pen-2",
        }
    )
    database = tmp_path / "supervisor-control.duckdb"
    first = upsert_failure_goals_through_quack(ledger, database)
    second = upsert_failure_goals_through_quack(ledger, database)
    assert first["ingested"] is True
    assert first["admitted"] is False
    assert first["formalized"] is False
    assert first["wrote_compiler"] is False
    assert first["transport"] == "quack"
    assert str(first["listen_uri"]).startswith("quack:127.0.0.1:")
    assert first["ducklake_activation_held"] is True
    assert first["production_mutation_enabled"] is False
    assert first["classes"] == 1
    assert first["goal_rows"] == second["goal_rows"]
    assert first["open_goal_rows"] >= 1
    assert second["goal_count"] == first["goal_count"]


def test_real_compiler_penalty_class_is_one_goal() -> None:
    def compile_one(text: str) -> dict:
        span_id = "gap-" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        return compile_span(AutoformalSession(), text, span_id)

    spans = [
        {"source_span_id": "pen-1", "legal_id": "usc:us:18:1001", "text": "Whoever shall be imprisoned."},
        {"source_span_id": "pen-2", "legal_id": "usc:us:18:1001", "text": "The agency shall imprison the person."},
        {"source_span_id": "ok-1", "legal_id": "usc:us:5:552", "text": "Each agency shall make records available."},
    ]
    ledger = FailureClassLedger()
    report = replay_gaps(spans, lambda text: text, compile_one, goals=ledger)
    assert report["admitted"] is False
    assert report["wrote_compiler"] is False
    assert report["compiled"] >= 1
    penalty = [row for row in ledger.public_goals() if "penalty" in row["failure_class"]]
    assert len(penalty) == 1
    assert penalty[0]["member_count"] == 2
    assert set(penalty[0]["example_span_ids"]) == {"pen-1", "pen-2"}
    assert "ok-1" not in penalty[0]["example_span_ids"]
