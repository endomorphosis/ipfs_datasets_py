"""Unit tests for PLAT2-055 candidate freeze, attribution, and authorization."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from benchmarks.logic_pipeline.content_addressing import cid_for_dag_json
from benchmarks.semantic_roundtrip.holdout_baseline import (
    NONINFERIORITY_MARGIN,
    POST_PLAT_BASELINE_E2E_MEAN,
    PRODUCTION_ARM_ID,
    SELECTION_GATE_IDS,
    load_repair_dev_baseline_report,
    score_deterministic_case,
)
from benchmarks.semantic_roundtrip.holdout_candidate_freeze import (
    DEFAULT_AUTHORIZATION_RELATIVE_PATH,
    DEFAULT_FREEZE_RELATIVE_PATH,
    FREEZE_EVIDENCE_ID,
    FREEZE_GOAL_ID,
    FREEZE_TASK_ID,
    HoldoutCandidateFreezeError,
    INVALIDATING_CHANGE_CLASSES,
    PLATEAU2_CANDIDATE_FREEZE_INTERFACE,
    PLATEAU2_CANDIDATE_FREEZE_SCHEMA,
    SEMANTIC_ROUNDTRIP_HOLDOUT_AUTHORIZATION_INTERFACE,
    SEMANTIC_ROUNDTRIP_HOLDOUT_AUTHORIZATION_SCHEMA,
    assert_authorization_still_valid,
    authorization_from_freeze,
    build_candidate_freeze,
    build_freeze_and_authorization_bundle,
    build_holdout_authorization,
    collect_freeze_bindings,
    compute_attribution_evidence,
    evaluate_selection_gates,
    load_candidate_freeze,
    load_edit_wave_manifest,
    load_edit_wave_receipts,
    load_holdout_authorization,
    parse_candidate_freeze,
    parse_holdout_authorization,
    replay_all_isolated_edit_waves,
    replay_isolated_edit_wave,
    score_cumulative_candidate,
    score_population_block,
    write_candidate_freeze,
    write_holdout_authorization,
)
from benchmarks.semantic_roundtrip.holdout_protocol import (
    AUTHORIZATION_GOAL_ID,
    HoldoutAccessAuthorization,
    POPULATION_KIND_PILOT,
    POPULATION_KIND_REPAIR_DEVELOPMENT,
    load_frozen_blind_holdout_seal,
)
from benchmarks.semantic_roundtrip.matrix import load_matrix_cases
from benchmarks.semantic_roundtrip.residual_catalog import (
    PILOT_CASES_RELATIVE_PATH,
    REPAIR_DEV_CASES_RELATIVE_PATH,
)


ROOT = Path(__file__).resolve().parents[4]
FREEZE_PATH = ROOT / DEFAULT_FREEZE_RELATIVE_PATH
AUTH_PATH = ROOT / DEFAULT_AUTHORIZATION_RELATIVE_PATH
FREEZE_DOCS = (
    ROOT / "docs/benchmarks/semantic_roundtrip_plateau2_candidate_freeze.md"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _synthetic_case_record(
    case_id: str,
    *,
    forward: float = 0.0,
    cycle: float = 0.0,
    end_to_end: float | None = None,
    full_coverage: bool = True,
    source_copy_exclusion: bool = True,
    polarity_preservation: bool = True,
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
        "evaluation_status": "semantic_scored",
        "evaluation_status_reason": "success",
        "facets": None,
        "gates": gates,
        "losses": {
            "cycle": cycle,
            "end_to_end": e2e,
            "forward": forward,
        },
        "polarity": {"gate_passed": polarity_preservation, "inversion_count": 0},
        "semantic_score_eligible": True,
        "source_copy": {
            "copy_risk": not source_copy_exclusion,
            "gate_passed": source_copy_exclusion,
            "shared_8gram_precision": 0.0 if source_copy_exclusion else 1.0,
        },
    }


def _population_results_from_baseline_plus_clears() -> dict[str, dict[str, object]]:
    """Build cumulative scores: pilot like baseline; repair-dev residuals cleared."""

    baseline = load_repair_dev_baseline_report(repo_root=ROOT)
    pilot_cases = []
    for row in baseline["populations"]["pilot"]["cases"]:  # type: ignore[index]
        case = dict(row)  # type: ignore[arg-type]
        pilot_cases.append(case)
    repair_cases = []
    for row in baseline["populations"]["repair_development"]["cases"]:  # type: ignore[index]
        case = dict(row)  # type: ignore[arg-type]
        # Cumulative candidate clears residual losses on repair-dev (as PLAT2-050).
        case["losses"] = {
            "cycle": float(case["losses"]["cycle"]),  # type: ignore[index]
            "end_to_end": 0.0,
            "forward": 0.0,
        }
        gates = dict(case["gates"])  # type: ignore[arg-type]
        gates["selection_eligible"] = all(
            gates.get(name) is True
            for name in (
                "full_coverage",
                "source_copy_exclusion",
                "polarity_preservation",
            )
        )
        case["gates"] = gates
        case["evaluation_status"] = "semantic_scored"
        case["semantic_score_eligible"] = True
        repair_cases.append(case)

    pilot_block = score_population_block(
        POPULATION_KIND_PILOT, case_records=pilot_cases
    )
    repair_block = score_population_block(
        POPULATION_KIND_REPAIR_DEVELOPMENT, case_records=repair_cases
    )
    return {
        POPULATION_KIND_PILOT: pilot_block,
        POPULATION_KIND_REPAIR_DEVELOPMENT: repair_block,
    }


def _build_test_freeze(**kwargs: object) -> dict[str, object]:
    population_results = kwargs.pop(
        "population_results", _population_results_from_baseline_plus_clears()
    )
    return build_candidate_freeze(
        ROOT,
        population_results=population_results,  # type: ignore[arg-type]
        run_scoring=False,
        **kwargs,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Interfaces and constants
# ---------------------------------------------------------------------------


def test_interfaces_and_task_constants_are_frozen() -> None:
    assert PLATEAU2_CANDIDATE_FREEZE_INTERFACE == "Plateau2CandidateFreeze@1"
    assert (
        PLATEAU2_CANDIDATE_FREEZE_SCHEMA
        == "ipfs-datasets.semantic-roundtrip-plateau2-candidate-freeze.v1"
    )
    assert (
        SEMANTIC_ROUNDTRIP_HOLDOUT_AUTHORIZATION_INTERFACE
        == "SemanticRoundtripHoldoutAuthorization@1"
    )
    assert (
        SEMANTIC_ROUNDTRIP_HOLDOUT_AUTHORIZATION_SCHEMA
        == "ipfs-datasets.semantic-roundtrip-plateau2-holdout-authorization.v1"
    )
    assert FREEZE_TASK_ID == "PLAT2-055"
    assert FREEZE_GOAL_ID == "PLAT2-G055"
    assert FREEZE_EVIDENCE_ID == "PLAT2EV055FREEZE"
    assert AUTHORIZATION_GOAL_ID == "PLAT2-055"
    assert "compiler_or_realizer_code" in INVALIDATING_CHANGE_CLASSES
    assert "population_or_seal_cid" in INVALIDATING_CHANGE_CLASSES


# ---------------------------------------------------------------------------
# Edit-wave receipts and isolated replay
# ---------------------------------------------------------------------------


def test_edit_wave_manifest_and_receipts_are_terminal_without_blind() -> None:
    manifest = load_edit_wave_manifest(repo_root=ROOT)
    assert manifest["population_kind"] == POPULATION_KIND_REPAIR_DEVELOPMENT
    assert manifest["blind_data_accessed"] is False
    assert list(manifest["optional_runtimes_promoted"]) == []
    receipts = load_edit_wave_receipts(repo_root=ROOT)
    assert len(receipts) == len(manifest["case_ids"])  # type: ignore[arg-type]
    assert {r["case_id"] for r in receipts} == set(manifest["case_ids"])  # type: ignore[arg-type]
    for receipt in receipts:
        assert receipt["implementable"] is True
        assert receipt["doctrine"]["blind_data_accessed"] is False  # type: ignore[index]
        assert list(receipt["optional_runtimes_promoted"]) == []


def test_isolated_wave_replay_reports_marginals_and_resources() -> None:
    receipts = load_edit_wave_receipts(repo_root=ROOT)
    waves = replay_all_isolated_edit_waves(receipts)
    assert len(waves) == len(receipts)
    for wave in waves:
        assert wave["ablation_kind"] == "isolated_edit_wave"
        assert wave["populations_in_scope"] == [
            POPULATION_KIND_PILOT,
            POPULATION_KIND_REPAIR_DEVELOPMENT,
        ]
        deltas = wave["marginal_deltas"]
        assert isinstance(deltas, dict)
        assert deltas["forward"] < 0.0  # type: ignore[index]
        assert wave["first_pass_repair_success"] is True
        assert wave["eventual_repair_success"] is True
        assert wave["accepted_patch_regression"] is False
        assert "packet_token_count" in wave["context_tokens"]  # type: ignore[operator]
        assert wave["provider_calls"]["total_provider_calls"] == 0  # type: ignore[index]
        assert wave["cost"]["total_cost"] == 0.0  # type: ignore[index]
        coverage = wave["structural_gate_coverage"]
        assert coverage["semantic_authority"] is False  # type: ignore[index]
        assert coverage["may_substitute_for_e2e"] is False  # type: ignore[index]
        assert coverage["coverage_count"] >= 1  # type: ignore[index]


def test_isolated_wave_marks_regression_when_pilot_worsens() -> None:
    receipt = dict(load_edit_wave_receipts(repo_root=ROOT)[0])
    post = dict(receipt["post_scores"])  # type: ignore[arg-type]
    post["mean_pilot_forward_loss"] = 0.05
    receipt["post_scores"] = post
    wave = replay_isolated_edit_wave(receipt)
    assert wave["accepted_patch_regression"] is True
    assert wave["marginal_deltas"]["mean_pilot_forward"] == pytest.approx(0.05)  # type: ignore[index]


# ---------------------------------------------------------------------------
# Attribution + selection
# ---------------------------------------------------------------------------


def test_attribution_includes_cumulative_deltas_and_interactions() -> None:
    receipts = load_edit_wave_receipts(repo_root=ROOT)
    isolated = replay_all_isolated_edit_waves(receipts)
    cumulative = score_cumulative_candidate(
        repo_root=ROOT,
        population_results=_population_results_from_baseline_plus_clears(),
        run_scoring=False,
    )
    baseline = load_repair_dev_baseline_report(repo_root=ROOT)
    attribution = compute_attribution_evidence(
        isolated_waves=isolated,
        cumulative=cumulative,
        baseline_report=baseline,
    )
    assert attribution["blind_data_used"] is False
    assert attribution["repair_success"]["eventual_success_count"] == len(isolated)  # type: ignore[index]
    assert attribution["accepted_patch_regressions"]["has_regression"] is False  # type: ignore[index]
    assert "per_case_repair_development_forward" in attribution["cumulative_deltas"]  # type: ignore[operator]
    assert isinstance(attribution["interactions"], list)
    assert attribution["context_tokens"]["sum_packet_token_count"] > 0  # type: ignore[index]
    assert attribution["provider_calls"]["sum_total_provider_calls"] == 0  # type: ignore[index]
    assert attribution["structural_gate_coverage"]["semantic_authority"] is False  # type: ignore[index]
    # Repair-dev mean e2e should improve vs baseline.
    assert (
        attribution["cumulative_deltas"]["mean_repair_development_end_to_end"]  # type: ignore[index]
        < 0.0
    )


def test_selection_selects_one_candidate_when_gates_pass() -> None:
    freeze = _build_test_freeze()
    selection = freeze["selection"]
    assert selection["candidate_selected"] is True  # type: ignore[index]
    assert selection["candidates_selected_count"] == 1  # type: ignore[index]
    assert selection["evidence_complete"] is True  # type: ignore[index]
    assert selection["required_gates_pass"] is True  # type: ignore[index]
    assert selection["pilot_non_regressed"] is True  # type: ignore[index]
    assert selection["rules_ref"]["source"] == "PLAT2-025"  # type: ignore[index]
    assert set(selection["rules_ref"]["selection_gate_ids"]) == set(  # type: ignore[index]
        SELECTION_GATE_IDS
    )
    assert selection["rules_ref"]["noninferiority_margin"] == NONINFERIORITY_MARGIN  # type: ignore[index]
    assert freeze["candidate_selected"] is True
    assert freeze["candidates_selected_count"] == 1
    assert freeze["candidate"]["status"] == "frozen"  # type: ignore[index]
    assert freeze["candidate"]["arm_id"] == PRODUCTION_ARM_ID  # type: ignore[index]


def test_selection_rejects_when_pilot_mean_regresses() -> None:
    results = _population_results_from_baseline_plus_clears()
    pilot_cases = list(results[POPULATION_KIND_PILOT]["cases"])  # type: ignore[arg-type]
    # Worsen one pilot e2e so mean leaves 0.0.
    bad = dict(pilot_cases[0])  # type: ignore[arg-type]
    bad["losses"] = {"cycle": 0.0, "end_to_end": 0.2, "forward": 0.2}
    pilot_cases[0] = bad
    results[POPULATION_KIND_PILOT] = score_population_block(
        POPULATION_KIND_PILOT, case_records=pilot_cases
    )
    freeze = _build_test_freeze(population_results=results)
    assert freeze["candidate_selected"] is False
    assert freeze["candidates_selected_count"] == 0
    assert freeze["candidate"] is None
    assert "pilot_mean_e2e_regressed" in freeze["selection"]["reasons"]  # type: ignore[index]


def test_selection_rejects_new_pilot_gate_failure() -> None:
    results = _population_results_from_baseline_plus_clears()
    pilot_cases = list(results[POPULATION_KIND_PILOT]["cases"])  # type: ignore[arg-type]
    # Force a new polarity failure on a pilot that previously passed polarity.
    for index, row in enumerate(pilot_cases):
        case = dict(row)  # type: ignore[arg-type]
        gates = dict(case["gates"])  # type: ignore[arg-type]
        if gates.get("polarity_preservation") is True:
            gates["polarity_preservation"] = False
            gates["selection_eligible"] = False
            case["gates"] = gates
            pilot_cases[index] = case
            break
    results[POPULATION_KIND_PILOT] = score_population_block(
        POPULATION_KIND_PILOT, case_records=pilot_cases
    )
    freeze = _build_test_freeze(population_results=results)
    assert freeze["candidate_selected"] is False
    assert "new_pilot_gate_failures" in freeze["selection"]["reasons"]  # type: ignore[index]


def test_selection_rejects_when_no_repair_improvement() -> None:
    baseline = load_repair_dev_baseline_report(repo_root=ROOT)
    pilot_block = score_population_block(
        POPULATION_KIND_PILOT,
        case_records=list(baseline["populations"]["pilot"]["cases"]),  # type: ignore[index]
    )
    repair_block = score_population_block(
        POPULATION_KIND_REPAIR_DEVELOPMENT,
        case_records=list(
            baseline["populations"]["repair_development"]["cases"]  # type: ignore[index]
        ),
    )
    # Empty receipts → no improvement evidence.
    freeze = build_candidate_freeze(
        ROOT,
        receipts=(),
        population_results={
            POPULATION_KIND_PILOT: pilot_block,
            POPULATION_KIND_REPAIR_DEVELOPMENT: repair_block,
        },
        run_scoring=False,
    )
    assert freeze["candidate_selected"] is False
    assert freeze["candidates_selected_count"] == 0


# ---------------------------------------------------------------------------
# Freeze bindings and validation
# ---------------------------------------------------------------------------


def test_freeze_bindings_cover_required_identities() -> None:
    bindings = collect_freeze_bindings(repo_root=ROOT)
    assert bindings["baseline"]["arm_id"] == PRODUCTION_ARM_ID  # type: ignore[index]
    assert bindings["baseline"]["post_plat_baseline_e2e_mean"] == (  # type: ignore[index]
        POST_PLAT_BASELINE_E2E_MEAN
    )
    assert str(bindings["blind_holdout_seal_cid"]).startswith("baguqeera")
    assert bindings["compiler_realizer"]["constructor_identity"]  # type: ignore[index]
    assert bindings["compiler_realizer"]["realizer_identity"]  # type: ignore[index]
    assert "commit" in bindings["candidate_source_tree"]  # type: ignore[operator]
    assert "gitlinks_cid" in bindings["candidate_source_tree"]  # type: ignore[operator]
    assert bindings["metrics"]["primary_promotion_metric"] == "end_to_end_loss"  # type: ignore[index]
    assert bindings["bootstrap"]["bootstrap_samples"] == 10_000  # type: ignore[index]
    assert bindings["decision_rules"]["noninferiority_margin"] == (  # type: ignore[index]
        NONINFERIORITY_MARGIN
    )
    assert bindings["thresholds"]["pilot_mean_e2e_required"] == 0.0  # type: ignore[index]
    assert bindings["populations"]["pilot"]["manifest_cid"]  # type: ignore[index]
    assert bindings["populations"]["repair_development"]["residual_catalog_cid"]  # type: ignore[index]
    assert bindings["intervention_registry_cid"]
    assert bindings["packet_context_metrics_cid"]
    assert bindings["edit_wave_manifest_cid"]
    assert bindings["tests"]["validation_commands"]  # type: ignore[index]
    assert "environment_toolchain" in bindings
    assert "provider_model_toolchain_identities" in bindings


def test_build_and_parse_candidate_freeze_round_trip() -> None:
    freeze = _build_test_freeze()
    parsed = parse_candidate_freeze(freeze)
    assert parsed["freeze_cid"] == freeze["freeze_cid"]
    assert parsed["interface"] == PLATEAU2_CANDIDATE_FREEZE_INTERFACE
    assert parsed["attribution"]["blind_data_used"] is False  # type: ignore[index]
    assert parsed["blind_holdout"]["access_receipt_count"] == 0  # type: ignore[index]
    assert parsed["invalidation_policy"]["retune_against_this_blind_holdout"] is False  # type: ignore[index]
    assert parsed["invalidation_policy"]["mutable_after_freeze"] is False  # type: ignore[index]
    # Tamper CID.
    bad = copy.deepcopy(freeze)
    bad["title"] = "tampered"
    with pytest.raises(HoldoutCandidateFreezeError, match="freeze_cid"):
        parse_candidate_freeze(bad)


def test_freeze_rejects_blind_data_flag() -> None:
    freeze = _build_test_freeze()
    freeze["cumulative_candidate_scores"]["blind_data_used"] = True  # type: ignore[index]
    # Recompute CID so we hit the semantic check rather than CID mismatch alone.
    identity = {
        key: value
        for key, value in freeze.items()
        if key not in {"freeze_cid", "freeze_cid_codec", "freeze_cid_scope"}
    }
    freeze["freeze_cid"] = cid_for_dag_json(identity)
    with pytest.raises(HoldoutCandidateFreezeError, match="blind"):
        parse_candidate_freeze(freeze)


def test_write_and_load_freeze(tmp_path: Path) -> None:
    freeze = _build_test_freeze()
    out = tmp_path / "plateau2_candidate_freeze.json"
    written = write_candidate_freeze(out, freeze=freeze, repo_root=ROOT)
    assert out.is_file()
    loaded = load_candidate_freeze(out, repo_root=ROOT)
    assert loaded["freeze_cid"] == written["freeze_cid"]


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


def test_authorization_emitted_only_for_selected_candidate() -> None:
    freeze = _build_test_freeze()
    auth = build_holdout_authorization(freeze, repo_root=ROOT)
    assert auth is not None
    parsed = parse_holdout_authorization(auth)
    assert parsed["goal_id"] == AUTHORIZATION_GOAL_ID
    assert parsed["holdout_authorized"] is True
    assert parsed["complete"] is True
    assert parsed["outcomes_inspected"] is False
    assert parsed["tuning_permitted"] is False
    assert parsed["candidate_freeze_cid"] == freeze["freeze_cid"]
    seal = load_frozen_blind_holdout_seal(repository_root=ROOT)
    assert parsed["seal_cid"] == seal.seal_cid
    # Protocol authorization must validate under HoldoutAccessAuthorization.
    protocol = HoldoutAccessAuthorization(
        goal_id=AUTHORIZATION_GOAL_ID,
        authorization_cid=str(parsed["authorization_cid"]),
        seal_cid=str(parsed["seal_cid"]),
        candidate_freeze_cid=str(parsed["candidate_freeze_cid"]),
        complete=True,
        holdout_authorized=True,
        outcomes_inspected=False,
        tuning_permitted=False,
    )
    assert protocol.authorization_cid == parsed["authorization_cid"]


def test_authorization_not_emitted_without_candidate() -> None:
    results = _population_results_from_baseline_plus_clears()
    pilot_cases = list(results[POPULATION_KIND_PILOT]["cases"])  # type: ignore[arg-type]
    bad = dict(pilot_cases[0])  # type: ignore[arg-type]
    bad["losses"] = {"cycle": 0.0, "end_to_end": 0.5, "forward": 0.5}
    pilot_cases[0] = bad
    results[POPULATION_KIND_PILOT] = score_population_block(
        POPULATION_KIND_PILOT, case_records=pilot_cases
    )
    freeze = _build_test_freeze(population_results=results)
    assert freeze["candidate_selected"] is False
    assert build_holdout_authorization(freeze, repo_root=ROOT) is None


def test_authorization_from_freeze_matches_protocol_builder() -> None:
    freeze = _build_test_freeze()
    auth = authorization_from_freeze(freeze, repo_root=ROOT)
    seal = load_frozen_blind_holdout_seal(repository_root=ROOT)
    expected = HoldoutAccessAuthorization.build(
        seal=seal,
        candidate_freeze_cid=str(freeze["freeze_cid"]),
    )
    assert auth.authorization_cid == expected.authorization_cid
    assert auth.candidate_freeze_cid == freeze["freeze_cid"]


def test_post_authorization_change_invalidates() -> None:
    freeze = _build_test_freeze()
    auth = build_holdout_authorization(freeze, repo_root=ROOT)
    assert auth is not None
    assert_authorization_still_valid(auth, freeze=freeze)
    with pytest.raises(HoldoutCandidateFreezeError, match="invalidated"):
        assert_authorization_still_valid(
            auth,
            freeze=freeze,
            code_config_prompt_threshold_population_changed=True,
        )


def test_write_authorization(tmp_path: Path) -> None:
    freeze = _build_test_freeze()
    out = tmp_path / "plateau2_holdout_authorization.json"
    written = write_holdout_authorization(out, freeze=freeze, repo_root=ROOT)
    assert written is not None
    assert out.is_file()
    loaded = load_holdout_authorization(out, repo_root=ROOT)
    assert loaded["authorization_artifact_cid"] == written["authorization_artifact_cid"]


def test_bundle_helper_emits_both() -> None:
    bundle = build_freeze_and_authorization_bundle(
        ROOT,
        run_scoring=False,
        population_results=_population_results_from_baseline_plus_clears(),
    )
    assert bundle["authorization_emitted"] is True
    assert bundle["freeze"]["candidate_selected"] is True  # type: ignore[index]
    assert bundle["authorization"] is not None


# ---------------------------------------------------------------------------
# Sealed workspace artifacts
# ---------------------------------------------------------------------------


def test_workspace_freeze_artifact_is_valid_when_present() -> None:
    if not FREEZE_PATH.is_file():
        pytest.skip("workspace freeze artifact not generated yet")
    freeze = load_candidate_freeze(FREEZE_PATH, repo_root=ROOT)
    assert freeze["task_id"] == FREEZE_TASK_ID
    assert freeze["attribution"]["blind_data_used"] is False  # type: ignore[index]
    assert freeze["blind_holdout"]["blind_seal_unopened"] is True  # type: ignore[index]
    assert freeze["candidates_selected_count"] in (0, 1)
    if freeze["candidate_selected"]:
        assert freeze["candidate"]["status"] == "frozen"  # type: ignore[index]
        assert AUTH_PATH.is_file()
        auth = load_holdout_authorization(AUTH_PATH, repo_root=ROOT)
        assert auth["candidate_freeze_cid"] == freeze["freeze_cid"]
        assert auth["holdout_authorized"] is True
        assert auth["tuning_permitted"] is False
        # Usable with protocol access ledger builder.
        protocol = authorization_from_freeze(freeze, repo_root=ROOT)
        assert protocol.goal_id == AUTHORIZATION_GOAL_ID
    else:
        # Zero-candidate freezes must not mint authorization.
        if AUTH_PATH.is_file():
            with pytest.raises(HoldoutCandidateFreezeError):
                # If a file exists without a candidate, it must fail validation
                # or be absent; either way authorization must not claim success.
                auth = json.loads(AUTH_PATH.read_text(encoding="utf-8"))
                if auth.get("holdout_authorized") is True:
                    parse_holdout_authorization(auth)
                    raise HoldoutCandidateFreezeError(
                        "authorization must not exist without a candidate"
                    )


def test_docs_describe_freeze_authorization_and_invalidation() -> None:
    assert FREEZE_DOCS.is_file()
    text = FREEZE_DOCS.read_text(encoding="utf-8")
    for token in (
        "PLAT2-055",
        "Plateau2CandidateFreeze@1",
        "SemanticRoundtripHoldoutAuthorization@1",
        "attribution",
        "zero or one",
        "PLAT2-025",
        "authorization",
        "fresh blind",
        "invalidat",
        "blind",
        "repair-development",
        "pilot",
    ):
        assert token.lower() in text.lower(), f"missing docs token: {token}"


# ---------------------------------------------------------------------------
# Live scoring smoke (optional; keeps production path honest)
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_live_cumulative_scoring_on_visible_populations_only() -> None:
    """Optional live re-score; not required for the default unit suite."""

    pilot_cases = load_matrix_cases(ROOT / PILOT_CASES_RELATIVE_PATH)
    sample = score_deterministic_case(pilot_cases[0])
    assert sample["evaluation_status"] == "semantic_scored"
    assert "losses" in sample
    # Ensure repair-dev loader does not pull blind fixtures.
    repair = load_matrix_cases(ROOT / REPAIR_DEV_CASES_RELATIVE_PATH)
    assert all(case.case_id for case in repair)
    # score_cumulative_candidate with injected empty results must reject blind.
    with pytest.raises(HoldoutCandidateFreezeError):
        score_population_block("blind_holdout", repo_root=ROOT)


def test_evaluate_selection_gates_zero_candidate_without_receipts() -> None:
    baseline = load_repair_dev_baseline_report(repo_root=ROOT)
    cumulative = score_cumulative_candidate(
        repo_root=ROOT,
        population_results=_population_results_from_baseline_plus_clears(),
        run_scoring=False,
    )
    attribution = compute_attribution_evidence(
        isolated_waves=[],
        cumulative=cumulative,
        baseline_report=baseline,
    )
    decision = evaluate_selection_gates(
        attribution=attribution,
        cumulative=cumulative,
        baseline_report=baseline,
        receipts=[],
        blind_status={
            "access_receipt_count": 0,
            "blind_seal_unopened": True,
            "status": "sealed_unopened",
        },
    )
    assert decision["candidate_selected"] is False
    assert decision["candidates_selected_count"] == 0
    assert decision["evidence_complete"] is False
