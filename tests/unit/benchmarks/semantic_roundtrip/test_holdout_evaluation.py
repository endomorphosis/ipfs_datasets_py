"""Unit tests for PLAT2-060 one-shot blind-holdout evaluation and decision."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.logic_pipeline.content_addressing import cid_for_dag_json
from benchmarks.semantic_roundtrip.holdout_baseline import (
    DECISION_GENERALIZATION_NO_IMPROVEMENT,
    DECISION_IMPROVEMENT_CONFIRMED,
    DECISION_INCOMPLETE,
    DECISION_PROMOTION_DECLINED,
    NONINFERIORITY_MARGIN,
    PRODUCTION_ARM_ID,
)
from benchmarks.semantic_roundtrip.holdout_candidate_freeze import (
    load_candidate_freeze,
    load_holdout_authorization,
)
from benchmarks.semantic_roundtrip.holdout_evaluation import (
    DEFAULT_ACCESS_LEDGER_RELATIVE_PATH,
    DEFAULT_PROMOTION_DECISION_RELATIVE_PATH,
    DEFAULT_REMEASURE_RELATIVE_PATH,
    DEFAULT_RESULTS_DOCS_RELATIVE_PATH,
    EVAL_EVIDENCE_ID,
    EVAL_GOAL_ID,
    EVAL_TASK_ID,
    HOLDOUT_REMEASURE_SCHEMA,
    HoldoutEvaluationError,
    build_access_ledger_export,
    collect_named_residuals,
    decide_holdout_outcome,
    evaluate_selection_gates_on_block,
    grant_single_use_access,
    isolated_namespace,
    materialize_blind_matrix_cases,
    paired_case_cluster_analysis,
    private_record_to_matrix_case,
    render_holdout_results_markdown,
    run_one_shot_blind_evaluation,
    score_cases_for_role,
    split_runtime_and_scorer_views,
    validate_identities_for_access,
    vocabulary_from_gold_ir,
    write_evaluation_artifacts,
)
from benchmarks.semantic_roundtrip.holdout_protocol import (
    AUTHORIZATION_GOAL_ID,
    HOLDOUT_ACCESS_AUDIT_INTERFACE,
    load_frozen_blind_holdout_seal,
    materialize_preregistered_blind_records,
)


ROOT = Path(__file__).resolve().parents[4]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _score_record(
    case_id: str,
    *,
    forward: float = 0.0,
    cycle: float = 0.0,
    end_to_end: float | None = None,
    full_coverage: bool = True,
    source_copy_exclusion: bool = True,
    polarity_preservation: bool = True,
    status: str = "semantic_scored",
) -> dict[str, object]:
    e2e = forward if end_to_end is None else end_to_end
    gates = {
        "full_coverage": full_coverage,
        "source_copy_exclusion": source_copy_exclusion,
        "polarity_preservation": polarity_preservation,
    }
    gates["selection_eligible"] = all(gates.values())
    return {
        "arm_id": PRODUCTION_ARM_ID,
        "case_cid": cid_for_dag_json({"case_id": case_id}),
        "case_id": case_id,
        "evaluation_status": status,
        "evaluation_status_reason": "success" if status == "semantic_scored" else status,
        "facets": {
            "end_to_end": {
                "modality": 1.0,
                "conditions": 1.0 if e2e == 0.0 else 0.5,
                "exceptions": 1.0,
                "temporal": 1.0,
            }
        },
        "gates": gates,
        "losses": {
            "cycle": cycle,
            "end_to_end": e2e,
            "forward": forward,
        },
        "polarity": {"gate_passed": polarity_preservation, "inversion_count": 0},
        "semantic_score_eligible": status == "semantic_scored",
        "source_copy": {
            "copy_risk": not source_copy_exclusion,
            "gate_passed": source_copy_exclusion,
            "shared_8gram_precision": 0.0,
        },
    }


def _block_from_scores(
    scores: dict[str, dict[str, object]],
    *,
    role: str,
    namespace: str,
) -> dict[str, object]:
    cases = []
    for case_id, score in scores.items():
        row = dict(score)
        row["case_id"] = case_id
        row["evaluation_role"] = role
        row["cache_namespace"] = namespace
        cases.append(row)
    return {
        "aggregates": {
            "case_count": len(cases),
            "means": {
                "forward": 0.0,
                "cycle": 0.0,
                "end_to_end": 0.0,
            },
            "semantic_scored_count": len(cases),
        },
        "arm_id": PRODUCTION_ARM_ID,
        "cache_namespace": namespace,
        "cases": cases,
        "evaluation_role": role,
        "population_kind": "blind_holdout",
    }


def _synthetic_scorer_factory(loss_by_case: dict[str, float]):
    def _scorer(case, **_kwargs):
        loss = float(loss_by_case.get(case.case_id, 0.0))
        return _score_record(case.case_id, forward=loss, end_to_end=loss)

    return _scorer


# ---------------------------------------------------------------------------
# Vocabulary / boundary / materialization
# ---------------------------------------------------------------------------


def test_vocabulary_and_matrix_case_from_private_records() -> None:
    records = materialize_preregistered_blind_records()
    assert len(records) == 12
    case = private_record_to_matrix_case(records[0])
    assert case.case_id == records[0].case_id
    vocab = vocabulary_from_gold_ir(dict(records[0].gold_ir))
    assert records[0].gold_ir["rules"][0]["actor"] in vocab.actors


def test_runtime_scorer_boundary_withholds_cross_material() -> None:
    cases = materialize_blind_matrix_cases()
    boundary = split_runtime_and_scorer_views(cases)
    policy = boundary["boundary_policy"]
    assert policy["agents_receive_gold"] is False
    assert policy["runtime_may_receive_source"] is True
    assert policy["scorer_may_receive_gold"] is True
    runtime = boundary["runtime_source_envelopes"]
    scorer = boundary["scorer_gold_bindings"]
    assert len(runtime) == len(scorer) == len(cases)
    assert "gold_ir" not in runtime[0]
    assert "source_text" not in scorer[0]
    assert runtime[0]["source_text"]
    assert scorer[0]["gold_ir"]


def test_isolated_namespaces_differ_for_roles() -> None:
    seal = load_frozen_blind_holdout_seal()
    freeze = load_candidate_freeze()
    base = isolated_namespace(
        "baseline",
        seal_cid=seal.seal_cid,
        freeze_cid=str(freeze["freeze_cid"]),
    )
    cand = isolated_namespace(
        "candidate",
        seal_cid=seal.seal_cid,
        freeze_cid=str(freeze["freeze_cid"]),
    )
    assert base != cand
    assert "baseline" in base
    assert "candidate" in cand


# ---------------------------------------------------------------------------
# Access ledger
# ---------------------------------------------------------------------------


def test_validate_identities_and_single_use_access(tmp_path: Path) -> None:
    freeze = load_candidate_freeze()
    auth = load_holdout_authorization()
    seal = load_frozen_blind_holdout_seal()
    identities = validate_identities_for_access(
        authorization=auth, freeze=freeze, seal=seal
    )
    assert identities["authorization_cid"]
    assert identities["powered"] is True

    ledger_path = tmp_path / "access.jsonl"
    first = grant_single_use_access(
        authorization=auth,
        freeze=freeze,
        seal=seal,
        ledger_path=ledger_path,
        executor_id="test-executor",
    )
    assert first["successful_access"] is True
    assert first["grant_receipt"]["event"] == "access_granted"
    assert first["release_receipt"]["event"] == "manifest_released"
    export = first["export"]
    assert export["path_free"] is True
    assert export["tuning_permitted"] is False
    assert export["interface"] == HOLDOUT_ACCESS_AUDIT_INTERFACE
    assert export["events"] == ["access_granted", "manifest_released"]
    assert "ledger_cid" in export
    # Path-free: no absolute filesystem paths in the public export.
    dumped = json.dumps(export)
    assert str(ledger_path) not in dumped
    assert "/tmp/" not in dumped or "tmp" not in json.dumps(export.get("receipts"))

    with pytest.raises(HoldoutEvaluationError, match="already accessed"):
        grant_single_use_access(
            authorization=auth,
            freeze=freeze,
            seal=seal,
            ledger_path=ledger_path,
            executor_id="test-executor",
        )


def test_access_export_requires_single_grant_and_release() -> None:
    with pytest.raises(HoldoutEvaluationError, match="access_granted"):
        build_access_ledger_export(
            receipts=[],
            identities={
                "access_ledger_authority_cid": cid_for_dag_json({"a": 1}),
                "authorization_cid": cid_for_dag_json({"b": 1}),
                "candidate_freeze_cid": cid_for_dag_json({"c": 1}),
                "seal_cid": cid_for_dag_json({"d": 1}),
                "sealed_private_bundle_cid": cid_for_dag_json({"e": 1}),
            },
            executor_id="x",
            purpose="evaluation",
        )


# ---------------------------------------------------------------------------
# Paired analysis + decision outcomes
# ---------------------------------------------------------------------------


def test_paired_analysis_improvement_when_candidate_strictly_better() -> None:
    baseline = _block_from_scores(
        {
            "c1": _score_record("c1", forward=0.4, end_to_end=0.4),
            "c2": _score_record("c2", forward=0.2, end_to_end=0.2),
        },
        role="baseline",
        namespace="ns-b",
    )
    candidate = _block_from_scores(
        {
            "c1": _score_record("c1", forward=0.0, end_to_end=0.0),
            "c2": _score_record("c2", forward=0.0, end_to_end=0.0),
        },
        role="candidate",
        namespace="ns-c",
    )
    paired = paired_case_cluster_analysis(
        baseline,
        candidate,
        baseline_arm_id="baseline_arm",
        candidate_arm_id="candidate_arm",
        bootstrap_samples=200,
    )
    assert paired["e2e_beats_baseline_ci_high_lt_0"] is True
    assert paired["metrics"]["end_to_end"]["mean_delta"] < 0


def test_decision_outcomes_cover_improvement_generalization_decline_incomplete() -> None:
    gates_pass = {"full_gates_pass": True}
    gates_fail = {"full_gates_pass": False}
    pilots_ok = {"non_regressed": True, "mean_end_to_end": 0.0}
    pilots_bad = {"non_regressed": False, "mean_end_to_end": 0.1}

    improved = decide_holdout_outcome(
        paired={
            "e2e_beats_baseline_ci_high_lt_0": True,
            "e2e_noninferior_ucb_lte_margin": True,
        },
        gates=gates_pass,
        pilot_non_regression=pilots_ok,
        powered=True,
        promotion_eligible=True,
        evidence_complete=True,
        exploratory=False,
    )
    assert improved["decision_outcome"] == DECISION_IMPROVEMENT_CONFIRMED
    assert improved["promotion"] is True
    assert improved["improvement_claim"] is True
    assert improved["production_promotion_authorized"] is True

    general = decide_holdout_outcome(
        paired={
            "e2e_beats_baseline_ci_high_lt_0": False,
            "e2e_noninferior_ucb_lte_margin": True,
        },
        gates=gates_pass,
        pilot_non_regression=pilots_ok,
        powered=True,
        promotion_eligible=True,
        evidence_complete=True,
        exploratory=False,
    )
    assert general["decision_outcome"] == DECISION_GENERALIZATION_NO_IMPROVEMENT
    assert general["promotion"] is False
    assert general["improvement_claim"] is False
    assert general["production_promotion_authorized"] is True

    declined = decide_holdout_outcome(
        paired={
            "e2e_beats_baseline_ci_high_lt_0": False,
            "e2e_noninferior_ucb_lte_margin": False,
        },
        gates=gates_pass,
        pilot_non_regression=pilots_ok,
        powered=True,
        promotion_eligible=True,
        evidence_complete=True,
        exploratory=False,
    )
    assert declined["decision_outcome"] == DECISION_PROMOTION_DECLINED
    assert declined["production_promotion_authorized"] is False

    gate_declined = decide_holdout_outcome(
        paired={
            "e2e_beats_baseline_ci_high_lt_0": True,
            "e2e_noninferior_ucb_lte_margin": True,
        },
        gates=gates_fail,
        pilot_non_regression=pilots_ok,
        powered=True,
        promotion_eligible=True,
        evidence_complete=True,
        exploratory=False,
    )
    assert gate_declined["decision_outcome"] == DECISION_PROMOTION_DECLINED

    pilot_declined = decide_holdout_outcome(
        paired={
            "e2e_beats_baseline_ci_high_lt_0": True,
            "e2e_noninferior_ucb_lte_margin": True,
        },
        gates=gates_pass,
        pilot_non_regression=pilots_bad,
        powered=True,
        promotion_eligible=True,
        evidence_complete=True,
        exploratory=False,
    )
    assert pilot_declined["decision_outcome"] == DECISION_PROMOTION_DECLINED

    incomplete = decide_holdout_outcome(
        paired={
            "e2e_beats_baseline_ci_high_lt_0": True,
            "e2e_noninferior_ucb_lte_margin": True,
        },
        gates=gates_pass,
        pilot_non_regression=pilots_ok,
        powered=False,
        promotion_eligible=False,
        evidence_complete=True,
        exploratory=True,
    )
    assert incomplete["decision_outcome"] == DECISION_INCOMPLETE

    missing = decide_holdout_outcome(
        paired={
            "e2e_beats_baseline_ci_high_lt_0": True,
            "e2e_noninferior_ucb_lte_margin": True,
        },
        gates=gates_pass,
        pilot_non_regression=pilots_ok,
        powered=True,
        promotion_eligible=True,
        evidence_complete=False,
        exploratory=False,
    )
    assert missing["decision_outcome"] == DECISION_INCOMPLETE


def test_noninferiority_margin_matches_frozen_protocol() -> None:
    assert NONINFERIORITY_MARGIN == 0.03


def test_selection_gates_and_named_residuals() -> None:
    block = _block_from_scores(
        {
            "ok": _score_record("ok", forward=0.0),
            "residual": _score_record("residual", forward=0.2, end_to_end=0.25),
            "gate_fail": _score_record(
                "gate_fail",
                forward=0.0,
                full_coverage=False,
            ),
        },
        role="candidate",
        namespace="ns",
    )
    gates = evaluate_selection_gates_on_block(block)
    assert gates["full_gates_pass"] is False
    residuals = collect_named_residuals(block)
    assert any(row["case_id"] == "residual" for row in residuals)
    assert all(row["population"] == "blind_holdout" for row in residuals)
    assert all(
        "newly authored blind population" in str(row["recommended_next_wave"])
        for row in residuals
    )


# ---------------------------------------------------------------------------
# End-to-end evaluation with injected scorer (fast)
# ---------------------------------------------------------------------------


def test_one_shot_evaluation_with_synthetic_scorer_writes_public_artifacts(
    tmp_path: Path,
) -> None:
    freeze = load_candidate_freeze()
    auth = load_holdout_authorization()
    seal = load_frozen_blind_holdout_seal()
    cases = materialize_blind_matrix_cases()
    # Perfect scores on every blind case → baseline==candidate → generalization.
    scorer = _synthetic_scorer_factory({case.case_id: 0.0 for case in cases})
    pilot_scores = {
        "cases": [
            _score_record(case_id, forward=0.0)
            for case_id in (
                "exception_with_window",
                "exec_order_1",
                "corp_policy_1",
                "legal_doc_1",
                "construction_contract",
            )
        ],
        "mean_end_to_end": 0.0,
        "non_regressed": True,
        "per_case": {},
        "required_mean": 0.0,
        "population_kind": "pilot",
    }

    ledger_path = tmp_path / "custodian" / "access.jsonl"
    bundle = run_one_shot_blind_evaluation(
        ROOT,
        freeze=freeze,
        authorization=auth,
        seal=seal,
        blind_cases=cases,
        ledger_path=ledger_path,
        scorer=scorer,
        pilot_non_regression=pilot_scores,
        captured_at_utc="2026-07-28T12:00:00.000+00:00",
    )

    decision = bundle["decision"]
    assert decision["decision_outcome"] == DECISION_GENERALIZATION_NO_IMPROVEMENT
    assert decision["improvement_claim"] is False
    assert decision["production_promotion_authorized"] is True

    remeasure = bundle["remeasure"]
    assert remeasure["interface"] == "EvalRepairMatrixReport@1"
    assert remeasure["schema_version"] == HOLDOUT_REMEASURE_SCHEMA
    assert remeasure["task_id"] == EVAL_TASK_ID
    assert remeasure["goal_id"] == EVAL_GOAL_ID
    assert remeasure["evidence_id"] == EVAL_EVIDENCE_ID
    assert remeasure["access_ledger_cid"] == bundle["access_ledger"]["ledger_cid"]

    promotion = bundle["promotion_decision"]
    assert promotion["decision"]["decision_outcome"] == (
        DECISION_GENERALIZATION_NO_IMPROVEMENT
    )
    assert promotion["post_access_policy"]["retune_against_this_blind_holdout"] is False
    assert (
        promotion["post_access_policy"][
            "seed_new_board_requires_fresh_blind_population"
        ]
        is True
    )

    # Public artifacts must not embed gold or source bodies.
    for payload in (remeasure, promotion, bundle["access_ledger"]):
        dumped = json.dumps(payload)
        assert "runtime_source_envelopes" not in dumped
        assert "scorer_gold_bindings" not in dumped
        assert '"gold_ir"' not in dumped
        assert '"source_text"' not in dumped

    md = bundle["results_markdown"]
    assert EVAL_TASK_ID in md
    assert "generalization_confirmed_no_improvement" in md
    assert "single path-free append-only access grant" in md

    out_dir = tmp_path / "artifacts"
    written = write_evaluation_artifacts(
        bundle,
        repo_root=ROOT,
        access_ledger_path=out_dir / "ledger.json",
        remeasure_path=out_dir / "remeasure.json",
        decision_path=out_dir / "decision.json",
        results_path=out_dir / "results.md",
    )
    for path in written.values():
        assert Path(path).is_file()
    ledger_doc = json.loads(Path(written["access_ledger"]).read_text(encoding="utf-8"))
    assert ledger_doc["single_use"] is True
    assert ledger_doc["path_free"] is True


def test_one_shot_evaluation_improvement_path(tmp_path: Path) -> None:
    freeze = load_candidate_freeze()
    auth = load_holdout_authorization()
    seal = load_frozen_blind_holdout_seal()
    cases = materialize_blind_matrix_cases()[:4]

    call_state = {"n": 0}

    def scorer(case, **_kwargs):
        # First pass over cases is baseline (higher loss); second is candidate.
        call_state["n"] += 1
        # baseline: calls 1..4, candidate: 5..8
        if call_state["n"] <= len(cases):
            return _score_record(case.case_id, forward=0.5, end_to_end=0.5)
        return _score_record(case.case_id, forward=0.0, end_to_end=0.0)

    pilot_scores = {
        "cases": [],
        "mean_end_to_end": 0.0,
        "non_regressed": True,
        "per_case": {},
        "required_mean": 0.0,
        "population_kind": "pilot",
    }
    bundle = run_one_shot_blind_evaluation(
        ROOT,
        freeze=freeze,
        authorization=auth,
        seal=seal,
        blind_cases=cases,
        ledger_path=tmp_path / "ledger.jsonl",
        scorer=scorer,
        pilot_non_regression=pilot_scores,
    )
    assert bundle["decision"]["decision_outcome"] == DECISION_IMPROVEMENT_CONFIRMED
    assert bundle["decision"]["promotion"] is True
    assert bundle["decision"]["improvement_claim"] is True


def test_score_cases_for_role_attaches_namespace_and_strips_private_keys() -> None:
    cases = materialize_blind_matrix_cases()[:1]

    def scorer(case, **_kwargs):
        row = _score_record(case.case_id, forward=0.0)
        row["source_text"] = "SECRET"
        row["gold_ir"] = {"rules": []}
        return row

    block = score_cases_for_role(
        cases,
        role="candidate",
        namespace="plat2-060/candidate/test",
        scorer=scorer,
    )
    assert block["cache_namespace"] == "plat2-060/candidate/test"
    assert "source_text" not in block["cases"][0]
    assert "gold_ir" not in block["cases"][0]


def test_render_markdown_includes_decision_table_and_ledger_cid(
    tmp_path: Path,
) -> None:
    freeze = load_candidate_freeze()
    auth = load_holdout_authorization()
    seal = load_frozen_blind_holdout_seal()
    cases = materialize_blind_matrix_cases()[:2]
    scorer = _synthetic_scorer_factory({case.case_id: 0.0 for case in cases})
    bundle = run_one_shot_blind_evaluation(
        ROOT,
        freeze=freeze,
        authorization=auth,
        seal=seal,
        blind_cases=cases,
        ledger_path=tmp_path / "ledger.jsonl",
        scorer=scorer,
        pilot_non_regression={
            "cases": [],
            "mean_end_to_end": 0.0,
            "non_regressed": True,
            "per_case": {},
            "required_mean": 0.0,
            "population_kind": "pilot",
        },
    )
    text = render_holdout_results_markdown(
        remeasure=bundle["remeasure"],  # type: ignore[arg-type]
        decision=bundle["promotion_decision"],  # type: ignore[arg-type]
        access_ledger=bundle["access_ledger"],  # type: ignore[arg-type]
    )
    assert "Access ledger CID" in text
    assert str(bundle["access_ledger"]["ledger_cid"]) in text
    assert "Decision outcome" in text


def test_default_artifact_relative_paths_match_task_contract() -> None:
    assert DEFAULT_ACCESS_LEDGER_RELATIVE_PATH.as_posix().endswith(
        "plateau2_holdout_access_ledger.json"
    )
    assert DEFAULT_REMEASURE_RELATIVE_PATH.as_posix().endswith(
        "2026-07-28_semantic_roundtrip_holdout_remeasure.json"
    )
    assert DEFAULT_PROMOTION_DECISION_RELATIVE_PATH.as_posix().endswith(
        "2026-07-28_semantic_roundtrip_holdout_promotion_decision.json"
    )
    assert DEFAULT_RESULTS_DOCS_RELATIVE_PATH.as_posix().endswith(
        "semantic_roundtrip_holdout_results.md"
    )
