"""Codec and compiler census, plus holdout canary training."""
from ipfs_datasets_py.logic.autoformal.span_agreement import (
    annotate_compiled_batch,
    consensus_summary,
    decide_span,
    encoding_consensus,
    train_until_canary_improves,
)


def test_consensus_requires_round_trip_formula_cosine_and_cross_entropy() -> None:
    from ipfs_datasets_py.logic.autoformal.span_agreement import result_alignment

    duty = {
        "compiled": True,
        "decompiled": "Agency must make records available.",
        "repair": {
            "autoencoder": {
                "decoded_text": "Each agency shall make records available.",
                "formulas": [{"op": "O", "predicate": "record_available"}],
            }
        },
    }
    close_duty = {
        "compiled": True,
        "decompiled": "Agency must keep the record.",
        "repair": {
            "autoencoder": {
                "decoded_text": "The agency shall keep the record.",
                "formulas": [{"op": "O", "predicate": "record"}],
            }
        },
    }
    citation_tail = {
        "compiled": True,
        "decompiled": "Agency must keep the record.",
        "repair": {
            "autoencoder": {
                "decoded_text": "The agency shall keep the record. See 42 U.S.C. § 1983 and 123 F.3d 456.",
                "formulas": [{"op": "O", "predicate": "record"}, {"op": "Frame", "predicate": "usc:us:42:1983"}],
            }
        },
    }
    penalty = {
        "compiled": False,
        "decompiled": "",
        "repair": {"autoencoder": {"decoded_text": "Whoever shall be imprisoned.", "formulas": [{"op": "O", "predicate": "imprison"}]}},
    }
    scrap = {"compiled": False, "decompiled": "", "repair": {"autoencoder": {"decoded_text": "5, 1990, 104 Stat.", "formulas": []}}}
    alignment = result_alignment(duty)
    assert alignment["cosine_similarity"] >= 0.72
    assert alignment["round_trip_cross_entropy_loss"] is not None
    assert alignment["formula_cross_entropy_loss"] is not None
    assert alignment["measurements"] > 1
    assert alignment["cross_entropy_loss"] == (
        alignment["round_trip_cross_entropy_loss"] * 5
        + alignment["formula_cross_entropy_loss"] * (alignment["measurements"] - 5)
    ) / alignment["measurements"]
    assert alignment["cross_entropy_loss"] <= 2.4
    assert alignment["formula_matches"] is True
    assert encoding_consensus(duty) == "agree"
    assert encoding_consensus(close_duty) == "agree"
    assert encoding_consensus(citation_tail) == "disagree"
    assert encoding_consensus(penalty) == "disagree"
    blank = result_alignment(penalty)
    assert blank["cross_entropy_loss"] is None
    assert blank["measurements"] == 0
    assert blank["cosine_similarity"] == 0.0
    summary = consensus_summary([duty, close_duty, citation_tail, penalty, scrap])
    assert summary["encoded"] == 4
    assert summary["agree"] == 2
    assert summary["disagree"] == 2
    assert summary["unscored"] == 1
    assert summary["agreement_rate"] == 0.5
    assert summary["admitted"] is False


def test_agreement_requires_compiler_codec_and_lake() -> None:
    agreed = decide_span(
        {
            "agrees": True,
            "decompiled": "Agency must make records available.",
            "repair": {"autoencoder": {"decoded_text": "Each agency shall make records available.", "cosine_loss": 0.1}},
        },
        lake_ok=True,
    )
    assert agreed["census"]["agree"] is True
    assert agreed["census"]["train"] is False
    assert agreed["census"]["admitted"] is False

    disagreed = decide_span(
        {
            "agrees": False,
            "decompiled": "",
            "reason": "CanonicalErrorCode.UNSUPPORTED_SEMANTICS:penalty",
            "repair": {"autoencoder": {"decoded_text": "Whoever shall be imprisoned.", "cosine_loss": 0.1}},
        },
        lake_ok=True,
    )
    assert disagreed["census"]["agree"] is False
    assert disagreed["census"]["work_kind"] == "compiler_decompiler_edit"
    assert disagreed["census"]["train"] is False


def test_high_loss_or_failed_lake_asks_for_canary_training() -> None:
    high = decide_span(
        {
            "agrees": True,
            "decompiled": "Agency must make records available.",
            "cosine_loss": 0.8,
            "cross_entropy_loss": 0.4,
            "repair": {"autoencoder": {"decoded_text": "Each agency shall make records available."}},
        },
        lake_ok=True,
    )
    assert high["census"]["agree"] is False
    assert high["census"]["train"] is True
    family_below_gate = decide_span(
        {
            "agrees": True,
            "decompiled": "Agency must make records available.",
            "cosine_loss": 0.2,
            "cross_entropy_loss": 0.4,
            "repair": {"autoencoder": {"decoded_text": "Each agency shall make records available."}},
        },
        lake_ok=True,
    )
    assert family_below_gate["census"]["train"] is False
    assert family_below_gate["census"]["cross_entropy_loss"] == 0.4
    reconstruction_above_gate = decide_span(
        {
            "agrees": True,
            "decompiled": "Agency must make records available.",
            "cosine_similarity": 0.9,
            "cross_entropy_loss": 0.4,
            "reconstruction_loss": 0.25,
            "repair": {"autoencoder": {"decoded_text": "Each agency shall make records available."}},
        },
        lake_ok=True,
    )
    assert reconstruction_above_gate["census"]["train"] is True
    view_above_gate = decide_span(
        {
            "agrees": True,
            "decompiled": "Agency must make records available.",
            "cosine_loss": 0.2,
            "view_cross_entropy_loss": 0.06,
            "repair": {"autoencoder": {"decoded_text": "Each agency shall make records available."}},
        },
        lake_ok=True,
    )
    assert view_above_gate["census"]["train"] is False
    compressed_poorly = decide_span(
        {
            "agrees": True,
            "decompiled": "Agency must make records available.",
            "cosine_similarity": 0.9,
            "ir_compression_loss": 0.8,
            "reconstruction_loss": 0.05,
            "repair": {"autoencoder": {"decoded_text": "Each agency shall make records available."}},
        },
        lake_ok=True,
    )
    assert compressed_poorly["census"]["train"] is True
    failed_lake = decide_span(
        {
            "agrees": True,
            "decompiled": "Agency must make records available.",
            "cosine_loss": 0.1,
            "repair": {"autoencoder": {"decoded_text": "Each agency shall make records available."}},
        },
        lake_ok=False,
    )
    assert failed_lake["census"]["train"] is True
    assert failed_lake["census"]["lake_ok"] is False
    assert failed_lake["census"]["admitted"] is False


def test_batch_lake_uses_the_injected_check_and_stops_at_the_cap() -> None:
    calls = {"n": 0}

    def check(_source: str) -> dict:
        calls["n"] += 1
        return {"lake_ok": True, "admitted": False, "formalized": False}

    rows = [
        {
            "agrees": False,
            "decompiled": "",
            "reason": "no_parser_elements",
            "repair": {
                "autoencoder": {
                    "decoded_text": "text",
                    "formulas": [{"op": "O", "predicate": "record", "arguments": ["actor:agency", "scope:record"]}],
                }
            },
        }
        for _ in range(6)
    ]
    annotated = annotate_compiled_batch(rows, lake_check=check, lake_limit=2)
    assert calls["n"] == 2
    assert annotated[0]["census"]["lake_ok"] is True
    assert annotated[2]["census"]["lake_ok"] is None
    assert all(item["census"]["admitted"] is False for item in annotated)


def test_canary_training_stops_when_the_holdout_improves() -> None:
    state = {
        "cosine_similarity": 0.4,
        "cross_entropy_loss": 1.5,
        "fits": 0,
        "rates": [],
        "reconstruction_loss": 0.4,
        "trained_on": [],
    }
    spans = [
        {"source_span_id": f"s{index}", "legal_id": "usc:us:18:1", "text": f"Span text number {index} shall keep the record."}
        for index in range(8)
    ]

    class Model:
        def measure_canary(self, texts: list[str]) -> dict:
            assert texts
            return {
                "cosine_similarity": state["cosine_similarity"],
                "cross_entropy_loss": state["cross_entropy_loss"],
                "reconstruction_loss": state["reconstruction_loss"],
            }

        def fit_train(self, texts: list[str], rate: float) -> None:
            state["fits"] += 1
            state["rates"].append(rate)
            state["trained_on"].extend(texts)
            state["cosine_similarity"] = 0.9
            state["cross_entropy_loss"] = 0.4
            state["reconstruction_loss"] = 0.1

    receipt = train_until_canary_improves(Model(), rounds=3, spans=spans, seed=7)
    assert receipt["trained"] is True
    assert receipt["improved"] is True
    assert receipt["rounds"] == 1
    assert receipt["admitted"] is False
    assert receipt["formalized"] is False
    assert state["fits"] == 1
    assert set(receipt["holdout_ids"]).isdisjoint(receipt["train_ids"])
    assert state["trained_on"]
    assert set(state["trained_on"]).isdisjoint(
        {row["text"] for row in spans if row["source_span_id"] in receipt["holdout_ids"]}
    )


def test_learning_rate_shrinks_when_the_holdout_does_not_improve() -> None:
    from ipfs_datasets_py.logic.autoformal.span_agreement import LearningRateSchedule

    schedule = LearningRateSchedule()
    first = schedule.step(improved=False)
    second = schedule.step(improved=True)
    assert first == 0.175
    assert second == min(0.35, 0.175 * 1.1)
    assert schedule.history[0] == 0.35


def test_seeded_split_is_stable_and_disjoint() -> None:
    from ipfs_datasets_py.logic.autoformal.span_agreement import split_train_holdout

    rows = [{"source_span_id": f"s{index}", "text": f"text {index} " * 5, "legal_id": "usc:us:1:1"} for index in range(10)]
    holdout_a, train_a = split_train_holdout(rows, seed=3)
    holdout_b, train_b = split_train_holdout(rows, seed=3)
    assert [row["source_span_id"] for row in holdout_a] == [row["source_span_id"] for row in holdout_b]
    assert {row["source_span_id"] for row in holdout_a}.isdisjoint({row["source_span_id"] for row in train_a})
    assert len(holdout_a) + len(train_a) == 10


def test_federal_sample_reads_a_cache_without_writing(tmp_path) -> None:
    from ipfs_datasets_py.logic.autoformal.span_agreement import sample_federal_spans
    from ipfs_datasets_py.logic.autoformal.span_cache import SpanCache

    cache = SpanCache(tmp_path / "span-cache.duckdb")
    cache.enqueue(
        [
            {"source_span_id": f"s{index}", "text": f"The agency shall keep record number {index} for the public.", "legal_id": "usc:us:5:552"}
            for index in range(12)
        ]
    )
    cache._db.execute("UPDATE span_cache SET status = 'gap', admitted = FALSE WHERE source_span_id IN ('s0', 's1', 's2', 's3')")
    cache.close()
    first = sample_federal_spans(tmp_path / "span-cache.duckdb", count=5, seed=11)
    second = sample_federal_spans(tmp_path / "span-cache.duckdb", count=5, seed=11)
    other = sample_federal_spans(tmp_path / "span-cache.duckdb", count=5, seed=12)
    assert [row["source_span_id"] for row in first] == [row["source_span_id"] for row in second]
    assert [row["source_span_id"] for row in first] != [row["source_span_id"] for row in other]
    assert all(40 <= len(row["text"]) <= 800 for row in first)
    failed = sample_federal_spans(tmp_path / "span-cache.duckdb", count=8, seed=11, status="gap")
    assert {row["source_span_id"] for row in failed} <= {"s0", "s1", "s2", "s3"}
    assert len(failed) >= 2
    writer = SpanCache(tmp_path / "span-cache.duckdb")
    saved = writer.save_gap_repairs(
        [
            {
                "source_span_id": "s0",
                "repair": {"error": "no actor", "fix": "parse the actor", "admitted": False, "formalized": False},
            }
        ]
    )
    loaded = writer.list_gaps()
    writer.close()
    assert saved == 1
    assert next(row for row in loaded if row["source_span_id"] == "s0")["repair"]["fix"] == "parse the actor"
