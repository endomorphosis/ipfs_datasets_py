"""Lake probe reports lake build Legal errors without admitting."""
from __future__ import annotations

from ipfs_datasets_py.logic.autoformal.lake_probe import (
    lake_check,
    pattern_from_fixture,
    pattern_from_rule,
    probe_census_rules,
    render_fixture,
    render_norm,
)
from ipfs_datasets_py.logic.autoformal.supervisor_loop import run_supervisor_loop


def test_probe_reports_injected_lake_errors_without_admitting() -> None:
    rule = {"modality": "obligation", "actor": "Agency", "action": "make", "object": "records"}
    assert pattern_from_rule(rule)["kind"] == "norm"
    source = render_norm(pattern_from_rule(rule), suffix="0")
    assert "theorem normBoundary0" in source

    def check(_source: str):
        return {
            "lake_ok": False,
            "error": "error: Legal.lean:4:0: unexpected token",
            "log": "error: Legal.lean:4:0: unexpected token\n",
            "admitted": False,
            "formalized": False,
        }

    receipt = probe_census_rules([rule], check=check)
    assert receipt["lake_ok"] is False
    assert "unexpected token" in receipt["error"]
    assert receipt["theorem_count"] == 1
    assert receipt["admitted"] is False
    assert receipt["formalized"] is False


def test_belief_knowledge_and_actorless_prohibition_are_definitional_fixtures() -> None:
    belief = {"modality": "B", "actor": "", "action": "willfully_falsify_material_fact_shall_fin", "object": "willfully_falsify_material_fact"}
    knowledge = {"modality": "K", "actor": "knowingly", "action": "falsify_material_fact_shall_fin_title", "object": "falsify_material_fact_shall"}
    actorless = {"modality": "F", "actor": "", "action": "commit_theft", "object": "commit_theft"}
    frame = {"modality": "Frame", "actor": "", "action": "united_states_code_edition_title_armed", "object": ""}
    assert pattern_from_rule(belief) is None
    assert pattern_from_rule(knowledge) is None
    assert pattern_from_rule(actorless) is None
    assert pattern_from_rule(frame) is None
    patterns = [
        pattern_from_fixture(belief),
        pattern_from_fixture(knowledge),
        pattern_from_fixture(actorless),
        pattern_from_fixture(frame),
    ]
    assert [item["fixture"] for item in patterns] == ["B", "K", "actorless_F", "Frame"]
    assert patterns[3]["modality"] == 6
    assert patterns[0]["bearer"] == "fixture:bearer"
    assert patterns[1]["bearer"] == "knowingly"
    source = "\n".join(render_fixture(pattern, suffix=str(index)) for index, pattern in enumerate(patterns))
    assert " axiom " not in f" {source} "
    assert "sorry" not in source.split()
    assert "admit" not in source.split()
    receipt = lake_check(source, timeout=180)
    assert receipt["lake_ok"] is True
    assert receipt["admitted"] is False
    assert receipt["formalized"] is False


def test_frame_selection_does_not_invent_a_target_probability_floor() -> None:
    from ipfs_datasets_py.logic.modal.codec import target_family_distribution_for_modal_ir
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import ModalIRDocument

    document = ModalIRDocument(document_id="t", source="t", normalized_text="t")
    plain = target_family_distribution_for_modal_ir(document)
    assert "frame" not in plain
    assert abs(sum(plain.values()) - 1.0) < 1e-6


def test_loop_logs_census_spans_and_lake_errors(tmp_path) -> None:
    lines: list[str] = []

    def lake_probe(rules):
        return {
            "lake_ok": False,
            "error": "error: Legal.lean:3:0: unknown identifier",
            "log": "error: Legal.lean:3:0: unknown identifier\n",
            "theorem_count": 1,
            "target": "Legal",
            "admitted": False,
            "formalized": False,
        }

    receipt = run_supervisor_loop(
        lambda: {
            "rows": [
                {
                    "agrees": True,
                    "id": "ok",
                    "source_span_id": "ok",
                    "skipped": False,
                    "text": "Each agency shall make records available.",
                    "decompiled": "Agency must make records available.",
                    "rule": {"modality": "obligation", "actor": "Agency", "action": "make", "object": "records"},
                },
                {
                    "agrees": False,
                    "id": "gap",
                    "source_span_id": "gap",
                    "skipped": False,
                    "reason": "CanonicalErrorCode.UNSUPPORTED_SEMANTICS:penalty",
                    "text": "Whoever shall be imprisoned.",
                    "dropped": ["penalty"],
                },
            ]
        },
        ingest=lambda *a, **k: {"task_count": 1},
        max_rounds=1,
        board_path=tmp_path / "loop.todo.md",
        log=lines.append,
        lake_probe=lake_probe,
    )
    joined = "\n".join(lines)
    assert "CENSUS span id=ok status=agreed" in joined
    assert "CENSUS span id=gap status=gap" in joined
    assert "penalty" in joined
    assert "LAKE round=1 target=Legal" in joined
    assert "unknown identifier" in joined
    assert receipt["lake"]["lake_ok"] is False
    assert receipt["admitted"] is False
    census = (tmp_path / "loop.todo.census.json").read_text(encoding="utf-8")
    assert "unknown identifier" in census
    assert "census_spans" in census
