"""Family projection, Lake fingerprint, and supervisor goals stay unadmitted."""

from ipfs_datasets_py.logic.autoformal.family_supervision import (
    FAMILY_NAMES,
    demote_failed_lake,
    goals_for_family_disagreement,
    project_span_families,
)


def _covered():
    return {
        "grammar_rejections": False,
        "legal_ir_target_count": 1,
        "ok": True,
        "view_distribution": {"cec": 1.0, "deontic": 1.0, "frame_logic": 1.0, "tdfol": 1.0},
    }


def test_a_duty_uses_deontic_logic_and_not_every_family():
    projection = project_span_families("The officer shall retain records.", "officer-records")
    assert projection["admitted"] is False
    assert projection["formalized"] is False
    assert projection["compiler_status"] == "compiled"
    assert projection["available_families"] == list(FAMILY_NAMES)
    assert projection["selected_families"] == ["deontic"]
    assert projection["missing_families"] == []
    assert projection["families"]["deontic"]["present"] is True
    assert set(projection["families"]) == {"deontic"}
    assert projection["stitch"]["open_slots"] == []


def test_autoencoder_family_gap_becomes_a_supervisor_goal_and_is_not_imported():
    report = goals_for_family_disagreement(
        [{"id": "officer-records", "source_span_id": "officer-records", "text": "The officer shall retain records."}],
        autoencoder={
            "grammar_rejections": False,
            "legal_ir_target_count": 1,
            "ok": False,
            "view_distribution": {"cec": 1.0, "frame_logic": 1.0, "tdfol": 1.0},
        },
        lake_check=lambda _source: {"admitted": False, "formalized": False, "lake_ok": True, "error": ""},
    )
    assert report["router_called"] is False
    assert report["wrote_compiler"] is False
    assert report["admitted"] is False
    assert report["formalized"] is False
    assert report["task_count"] == 1
    assert report["goal_count"] >= 1
    assert report["agreement"]["rows"][0]["reason"] == "capture_not_in_decompilation"
    assert report["agreement"]["rows"][0]["agrees"] is False


def test_agreement_and_a_successful_lake_build_do_not_open_a_goal():
    report = goals_for_family_disagreement(
        [{"id": "officer-records", "source_span_id": "officer-records", "text": "The officer shall retain records."}],
        autoencoder=_covered(),
        lake_check=lambda source: {
            "admitted": False,
            "error": "",
            "formalized": False,
            "lake_ok": "theorem normBoundary0" in source and "sorry" not in source,
        },
    )
    assert report["task_count"] == 0
    assert report["goal_count"] == 0
    assert report["agreement"]["agrees"] is True
    assert report["agreement"]["projections"][0]["lake"]["lake_ok"] is True
    assert report["admitted"] is False
    assert report["formalized"] is False
    assert report["wrote_compiler"] is False


def test_a_temporal_duty_is_tdfol_and_an_abstention_keeps_a_stitch_fixture():
    from ipfs_datasets_py.logic.autoformal.family_supervision import lake_build_projection, stitch_symbol

    temporal = project_span_families(
        "The officer shall retain records until Monday.",
        "officer-until",
    )
    assert temporal["compiler_status"] == "compiled"
    assert temporal["selected_families"] == ["tdfol"]
    assert "deontic" not in temporal["families"]
    assert temporal["families"]["tdfol"]["present"] is True
    assert temporal["stitch"]["open_slots"] == []
    assert temporal["admitted"] is False

    held = project_span_families(
        "The officer shall retain records before the hearing.",
        "officer-before",
    )
    assert held["compiler_status"] != "compiled"
    assert held["selected_families"] == ["tdfol", "frame_logic"]
    assert held["stitch"]["open_slots"] == ["actor", "action"]
    assert held["families"]["tdfol"]["present"] is True
    assert held["admitted"] is False

    fragment = project_span_families("5, 1990, 104 Stat.", "stat-scrap")
    assert fragment["compiler_status"] != "compiled"
    assert fragment["selected_families"] == ["frame_logic"]
    assert fragment["stitch"]["open_slots"] == ["actor", "action"]
    assert stitch_symbol("stat-scrap", "actor") in fragment["stitch"]["joins"]
    assert stitch_symbol("stat-scrap", "action") in fragment["stitch"]["joins"]
    assert fragment["families"]["frame_logic"]["present"] is True
    assert fragment["admitted"] is False
    assert fragment["formalized"] is False
    lake = lake_build_projection(fragment)
    assert lake["theorem_count"] == 1
    assert lake["lake_ok"] is True
    assert lake["admitted"] is False
    assert lake["formalized"] is False


def test_a_roundtrip_is_demoted_only_when_the_autoencoder_rejects_it():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[3] / "scripts/ops/legal_ir/run_uscode_formal_logic.py"
    spec = importlib.util.spec_from_file_location("run_uscode_formal_logic", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    covered = {
        "rules": [{"modality": "O", "actor": "officer", "action": "retain", "object": "records"}],
        "strict_status": "roundtrip_ok",
        "source_span_id": "officer-records",
    }
    assert module.note_autoencoder_gaps(
        [covered],
        {"ok": False, "legal_ir_target_count": 1, "view_distribution": {"deontic": 1.0}, "grammar_rejections": False},
    ) == []
    assert covered["strict_status"] == "roundtrip_ok"
    rejected = dict(covered)
    fresh = module.note_autoencoder_gaps(
        [rejected],
        {"ok": False, "legal_ir_target_count": 1, "view_distribution": {"deontic": 1.0}, "grammar_rejections": True},
    )
    assert fresh == [rejected]
    assert rejected["strict_status"] == "gap"
    assert rejected["strict_reason"] == "capture_not_in_decompilation"
    assert rejected["admitted"] is False
    assert rejected["formalized"] is False


def test_holdout_scores_and_compiler_replication_use_the_supervisor_schemas():
    from ipfs_datasets_py.logic.autoformal.family_supervision import (
        TRAINING_BRIDGE_NAMES,
        census_autoencoder_span,
        supervisor_repair_goals,
    )
    from ipfs_datasets_py.logic.autoformal.span_agreement import threshold_at_round

    text = "The officer shall retain records."
    passing = census_autoencoder_span(
        text,
        "officer-records",
        text,
        {"cosine_similarity": 0.9, "cross_entropy_loss": 1.0, "reconstruction_loss": 0.1},
        round_index=0,
    )
    assert passing["agrees"] is True
    assert passing["capture"]["replicated"] is True
    assert passing["capture"]["training_families"] == list(FAMILY_NAMES)
    assert passing["capture"]["training_bridges"] == list(TRAINING_BRIDGE_NAMES)
    assert threshold_at_round(8)["cosine_similarity"] > threshold_at_round(0)["cosine_similarity"]

    short = census_autoencoder_span(
        text,
        "officer-records",
        text,
        {"cosine_similarity": 0.2, "cross_entropy_loss": 1.0, "reconstruction_loss": 0.1},
        round_index=0,
    )
    assert short["agrees"] is False
    assert short["reason"] == "inference_still_failing"
    assert "cosine_similarity" in short["capture"]["below_threshold"]
    assert short["capture"]["threshold"]["cosine_similarity"] == 0.40

    mismatched = census_autoencoder_span(
        text,
        "officer-records",
        "5, 1990, 104 Stat.",
        {"cosine_similarity": 0.9, "cross_entropy_loss": 1.0, "reconstruction_loss": 0.1},
        round_index=0,
    )
    assert mismatched["reason"] == "strict_roundtrip_failed"
    goals = supervisor_repair_goals([short, mismatched])
    assert goals["repair_schema"] == "uscode-autoformal-repair-packet/v1"
    assert goals["training_schema"] == "uscode-autoformal-training-job/v1"
    assert goals["wrote_compiler"] is False
    assert goals["admitted"] is False
    assert len(goals["repair_packets"]) == 1
    packet = goals["repair_packets"][0]["packet"]
    assert packet["schema"] == "uscode-autoformal-repair-packet/v1"
    assert any(path.endswith("canonical_decompiler.py") for path in packet["allowed_edit_paths"])
    assert any(path.endswith("canonical_compiler.py") for path in packet["allowed_edit_paths"])
    assert packet["row"]["capture"]["holdout_scores"]["cosine_similarity"] == 0.9
    assert packet["row"]["capture"]["training_families"] == list(FAMILY_NAMES)
    assert goals["training_goals"]
    assert goals["training_goals"][0]["capture"]["below_threshold"] == ["cosine_similarity"]
    assert goals["training_goals"][0]["work_kind"] == "autoencoder_training"


def test_a_failed_lake_build_opens_a_gap_and_a_missing_lake_does_not():
    span = {"rules": [{"modality": "O", "actor": "officer", "action": "retain"}], "strict_status": "roundtrip_ok"}
    failed = demote_failed_lake([span], {"lake_ok": False, "error": "build_failed", "admitted": False, "formalized": False})
    assert failed[0]["strict_status"] == "gap"
    assert failed[0]["strict_reason"] == "strict_roundtrip_failed"
    assert failed[0]["admitted"] is False
    untouched = {"rules": [{"modality": "O"}], "strict_status": "roundtrip_ok"}
    assert demote_failed_lake([untouched], {"lake_ok": False, "error": "lake_not_on_path"}) == []
    assert untouched["strict_status"] == "roundtrip_ok"
