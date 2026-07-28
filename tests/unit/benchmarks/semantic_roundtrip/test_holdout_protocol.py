"""Unit tests for PLAT2-020 holdout population freeze and custody protocol."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.logic_pipeline.content_addressing import cid_for_dag_json
from benchmarks.semantic_roundtrip.holdout_protocol import (
    AUTHORIZATION_GOAL_ID,
    BLIND_HOLDOUT_SEAL_SCHEMA,
    BLIND_SEAL_RELATIVE_PATH,
    FROZEN_BLIND_CASE_COUNT,
    FROZEN_BLIND_STRATA_COUNTS,
    HOLDOUT_ACCESS_AUDIT_INTERFACE,
    HoldoutAccessAuthorization,
    HoldoutProtocolError,
    NEAR_DUPLICATE_JACCARD_THRESHOLD,
    POPULATION_KIND_BLIND_HOLDOUT,
    POPULATION_KIND_PILOT,
    POPULATION_KIND_REPAIR_DEVELOPMENT,
    POPULATION_MANIFEST_SCHEMA,
    PrivateBlindCaseRecord,
    REPAIR_DEV_CASES_RELATIVE_PATH,
    REPOSITORY_ROOT,
    SEMANTIC_ROUNDTRIP_HOLDOUT_SEAL_INTERFACE,
    SEMANTIC_ROUNDTRIP_POPULATION_MANIFEST_INTERFACE,
    AppendOnlyAccessLedger,
    SampleSizeJustification,
    assert_promotion_sample_size_gate,
    build_blind_holdout_seal,
    build_frozen_blind_holdout_seal,
    freeze_all_populations_with_private_blind,
    freeze_visible_populations,
    load_frozen_blind_holdout_seal,
    load_pilot_manifest,
    load_population_case_views,
    load_raw_case_dicts,
    load_repair_development_manifest,
    materialize_preregistered_blind_records,
    normalize_source_text,
    reject_post_access_tuning,
    release_blind_manifest,
    request_blind_access,
    required_case_count_for_precision,
    source_similarity,
    validate_cross_split_leakage,
    validate_custodian_store_path,
    validate_prompt_example_isolation,
)
from benchmarks.semantic_roundtrip.matrix import load_matrix_cases
from benchmarks.semantic_roundtrip.residual_catalog import PILOT_CASE_IDS


ROOT = REPOSITORY_ROOT
REPAIR_DEV_FIXTURE = ROOT / REPAIR_DEV_CASES_RELATIVE_PATH
BLIND_SEAL_PATH = ROOT / BLIND_SEAL_RELATIVE_PATH
HOLDOUT_DOCS = ROOT / "docs/benchmarks/semantic_roundtrip_holdout_cases.md"

SELECTIVE_REPAIR_ACTIVATION_CASE_IDS = (
    "missing_temporal",
    "low_confidence_object",
    "contradictory_modality",
)


# ---------------------------------------------------------------------------
# Fixtures and freezes
# ---------------------------------------------------------------------------


def test_repair_dev_fixture_exists_with_selective_repair_and_gold() -> None:
    assert REPAIR_DEV_FIXTURE.is_file()
    raw = load_raw_case_dicts(REPAIR_DEV_FIXTURE)
    ids = [str(case["id"]) for case in raw]
    assert len(ids) == len(set(ids))
    assert len(ids) >= 3
    for activation_id in SELECTIVE_REPAIR_ACTIVATION_CASE_IDS:
        assert activation_id in ids
    for case in raw:
        assert case.get("source_text")
        assert case.get("gold_ir")
        gold = case["gold_ir"]
        assert isinstance(gold, dict)
        assert isinstance(gold.get("rules"), list) and gold["rules"]
        assert case.get("score_bindings", {}).get("binding_kind") == "gold_ir"
    # Matrix load exposes source/gold for diagnosis.
    matrix = load_matrix_cases(REPAIR_DEV_FIXTURE)
    assert {case.case_id for case in matrix} == set(ids)
    assert all(not case.gold_ir.is_empty for case in matrix)


def test_pilot_and_repair_dev_manifests_are_disjoint_and_frozen() -> None:
    pilot = load_pilot_manifest()
    repair = load_repair_development_manifest()
    assert pilot.interface == SEMANTIC_ROUNDTRIP_POPULATION_MANIFEST_INTERFACE
    assert repair.interface == SEMANTIC_ROUNDTRIP_POPULATION_MANIFEST_INTERFACE
    assert pilot.schema == POPULATION_MANIFEST_SCHEMA
    assert pilot.population_kind == POPULATION_KIND_PILOT
    assert repair.population_kind == POPULATION_KIND_REPAIR_DEVELOPMENT
    assert tuple(pilot.case_ids) == PILOT_CASE_IDS
    assert set(pilot.case_ids).isdisjoint(set(repair.case_ids))
    assert pilot.fixture_sha256
    assert repair.fixture_sha256
    # Round-trip.
    assert (
        type(pilot).from_dict(pilot.to_dict()).manifest_cid == pilot.manifest_cid
    )
    assert (
        type(repair).from_dict(repair.to_dict()).manifest_cid
        == repair.manifest_cid
    )


def test_freeze_visible_populations_rejects_no_leakage() -> None:
    manifests = freeze_visible_populations()
    assert set(manifests) == {
        POPULATION_KIND_PILOT,
        POPULATION_KIND_REPAIR_DEVELOPMENT,
    }


def test_public_blind_seal_is_frozen_without_private_content() -> None:
    assert BLIND_SEAL_PATH.is_file()
    raw = json.loads(BLIND_SEAL_PATH.read_text(encoding="utf-8"))
    seal = load_frozen_blind_holdout_seal()
    rebuilt = build_frozen_blind_holdout_seal()
    assert seal.seal_cid == rebuilt.seal_cid
    assert seal.interface == SEMANTIC_ROUNDTRIP_HOLDOUT_SEAL_INTERFACE
    assert seal.schema == BLIND_HOLDOUT_SEAL_SCHEMA
    assert seal.case_count == FROZEN_BLIND_CASE_COUNT
    assert dict(seal.strata_counts) == dict(FROZEN_BLIND_STRATA_COUNTS)
    assert set(seal.aggregate_commitments) == {
        "ordered_source_manifest_cid",
        "ordered_gold_manifest_cid",
        "ordered_provenance_manifest_cid",
    }
    # No per-case digests / sources / gold / labels / hints.
    forbidden = {
        "case_ids",
        "cases",
        "source_text",
        "gold_ir",
        "labels",
        "per_case_digests",
        "source_sha256s",
        "semantic_hints",
        "score_bindings",
    }
    assert forbidden.isdisjoint(set(raw))
    text = BLIND_SEAL_PATH.read_text(encoding="utf-8")
    for token in (
        "missing_temporal",
        "The controller must delete",
        "gold_ir",
        "source_text",
        "blind_t1_retention_window",
    ):
        assert token not in text
    from benchmarks.semantic_roundtrip.holdout_protocol import BlindHoldoutSeal

    restored = BlindHoldoutSeal.from_dict(seal.to_dict())
    assert restored.seal_cid == seal.seal_cid


def test_seal_from_dict_rejects_forbidden_public_fields() -> None:
    from benchmarks.semantic_roundtrip.holdout_protocol import BlindHoldoutSeal

    seal = build_frozen_blind_holdout_seal()
    payload = seal.to_dict()
    payload["case_ids"] = ["blind_t1_retention_window"]
    with pytest.raises(HoldoutProtocolError, match="must not expose"):
        BlindHoldoutSeal.from_dict(payload)


# ---------------------------------------------------------------------------
# Sample size / power
# ---------------------------------------------------------------------------


def test_precision_justification_marks_underpowered_as_exploratory() -> None:
    required = required_case_count_for_precision()
    assert required == 10
    under = SampleSizeJustification.build(
        actual_case_count=3,
        strata_counts={"complexity_tier_1": 3},
        notes="synthetic underpowered exploratory population",
    )
    assert under.powered is False
    assert under.exploratory is True
    assert under.promotion_eligible is False
    with pytest.raises(HoldoutProtocolError, match="underpowered|exploratory"):
        # Build a mini seal and assert promotion gate.
        records = materialize_preregistered_blind_records()[:3]
        # Force strata on first three which are tier_1.
        seal = build_blind_holdout_seal(
            records,
            notes="underpowered exploratory seal for tests",
        )
        assert seal.sample_size_justification.exploratory is True
        assert_promotion_sample_size_gate(seal)


def test_powered_frozen_seal_passes_promotion_sample_size_gate() -> None:
    seal = load_frozen_blind_holdout_seal()
    assert seal.sample_size_justification.powered is True
    assert seal.sample_size_justification.promotion_eligible is True
    assert_promotion_sample_size_gate(seal)


def test_repair_development_is_explicitly_exploratory_for_promotion() -> None:
    repair = load_repair_development_manifest()
    # 8 cases < required 10 under the preregistered precision formula.
    assert repair.case_count < required_case_count_for_precision()
    assert repair.sample_size_justification.exploratory is True
    assert repair.sample_size_justification.promotion_eligible is False


# ---------------------------------------------------------------------------
# Leakage checks
# ---------------------------------------------------------------------------


def test_cross_split_and_prompt_leakage_checks_pass_for_preregistered() -> None:
    records = materialize_preregistered_blind_records()
    result = freeze_all_populations_with_private_blind(
        records,
        prompt_examples={
            "pilot_style": (
                "Company A shall submit backup report within 10 days unless "
                "emergency."
            ),
            "repair_style": (
                "The controller must delete the records after 30 days."
            ),
        },
    )
    assert result["blind_holdout_seal"].case_count == FROZEN_BLIND_CASE_COUNT
    assert len(result["prompt_example_sha256s"]) == 2


def test_exact_source_leakage_is_rejected() -> None:
    pilot = load_population_case_views(
        ROOT / "tests/fixtures/semantic_roundtrip/pilot_cases.json",
        population_kind=POPULATION_KIND_PILOT,
    )
    repair = load_population_case_views(
        REPAIR_DEV_FIXTURE,
        population_kind=POPULATION_KIND_REPAIR_DEVELOPMENT,
    )
    leaked = PrivateBlindCaseRecord(
        case_id="leaked_exact",
        source_text=pilot[0].source_text,
        gold_ir={"rules": [
            {
                "modality": "O",
                "actor": "a",
                "action": "b",
                "object": "c",
                "conditions": [],
                "exceptions": [],
                "temporal": [],
            }
        ]},
        source_ref="custodian://leaked/exact",
        stratum="complexity_tier_1",
        provenance={"prompt_exposure": "none"},
    )
    with pytest.raises(HoldoutProtocolError, match="exact source"):
        validate_cross_split_leakage(
            {
                POPULATION_KIND_PILOT: pilot,
                POPULATION_KIND_REPAIR_DEVELOPMENT: repair,
                POPULATION_KIND_BLIND_HOLDOUT: (leaked.as_view(),),
            }
        )


def test_normalized_and_near_duplicate_leakage_are_rejected() -> None:
    pilot = load_population_case_views(
        ROOT / "tests/fixtures/semantic_roundtrip/pilot_cases.json",
        population_kind=POPULATION_KIND_PILOT,
    )
    base = pilot[0].source_text
    # Punctuation/case only → normalized duplicate.
    normalized_dup = PrivateBlindCaseRecord(
        case_id="leaked_normalized",
        source_text=base.upper().replace(".", "!!!"),
        gold_ir={"rules": [
            {
                "modality": "O",
                "actor": "a",
                "action": "b",
                "object": "c",
                "conditions": [],
                "exceptions": [],
                "temporal": [],
            }
        ]},
        source_ref="custodian://leaked/normalized",
        stratum="complexity_tier_1",
        provenance={"prompt_exposure": "none"},
    )
    assert normalize_source_text(normalized_dup.source_text) == normalize_source_text(
        base
    )
    with pytest.raises(HoldoutProtocolError, match="normalized source"):
        validate_cross_split_leakage(
            {
                POPULATION_KIND_PILOT: (pilot[0],),
                POPULATION_KIND_BLIND_HOLDOUT: (normalized_dup.as_view(),),
            }
        )

    # Near-duplicate: share most shingles with a long pilot source.
    long_pilot = max(pilot, key=lambda view: len(view.source_text))
    tokens = normalize_source_text(long_pilot.source_text).split()
    # Keep almost all tokens, swap one rare tail token.
    near_tokens = list(tokens)
    if len(near_tokens) > 3:
        near_tokens[-1] = "zzzxuniquezz"
    near_text = " ".join(near_tokens)
    similarity = source_similarity(long_pilot.source_text, near_text)
    assert similarity >= NEAR_DUPLICATE_JACCARD_THRESHOLD
    near_dup = PrivateBlindCaseRecord(
        case_id="leaked_near",
        source_text=near_text,
        gold_ir={"rules": [
            {
                "modality": "O",
                "actor": "a",
                "action": "b",
                "object": "c",
                "conditions": [],
                "exceptions": [],
                "temporal": [],
            }
        ]},
        source_ref="custodian://leaked/near",
        stratum="complexity_tier_1",
        provenance={"prompt_exposure": "none"},
    )
    with pytest.raises(HoldoutProtocolError, match="near-duplicate"):
        validate_cross_split_leakage(
            {
                POPULATION_KIND_PILOT: (long_pilot,),
                POPULATION_KIND_BLIND_HOLDOUT: (near_dup.as_view(),),
            }
        )


def test_provenance_and_prompt_example_leakage_are_rejected() -> None:
    repair = load_population_case_views(
        REPAIR_DEV_FIXTURE,
        population_kind=POPULATION_KIND_REPAIR_DEVELOPMENT,
    )
    shared_ref = repair[0].source_ref
    blind = PrivateBlindCaseRecord(
        case_id="leaked_ref",
        source_text="Completely unique blind wording about orbital debris liability bonds.",
        gold_ir={"rules": [
            {
                "modality": "O",
                "actor": "operators",
                "action": "post",
                "object": "debris_bonds",
                "conditions": [],
                "exceptions": [],
                "temporal": [],
            }
        ]},
        source_ref=shared_ref,
        stratum="complexity_tier_1",
        provenance={"prompt_exposure": "none"},
    )
    with pytest.raises(HoldoutProtocolError, match="provenance"):
        validate_cross_split_leakage(
            {
                POPULATION_KIND_REPAIR_DEVELOPMENT: (repair[0],),
                POPULATION_KIND_BLIND_HOLDOUT: (blind.as_view(),),
            }
        )

    records = materialize_preregistered_blind_records()
    with pytest.raises(HoldoutProtocolError, match="prompt example|near-copy|exposed"):
        validate_prompt_example_isolation(
            tuple(record.as_view() for record in records),
            {"copied": records[0].source_text},
        )


# ---------------------------------------------------------------------------
# Custodian path boundary
# ---------------------------------------------------------------------------


def test_custodian_store_must_live_outside_worktree(tmp_path: Path) -> None:
    worktree = tmp_path / "agent-worktree"
    worktree.mkdir()
    inside = worktree / "private" / "blind.json"
    inside.parent.mkdir(parents=True)
    inside.write_text("{}", encoding="utf-8")
    with pytest.raises(HoldoutProtocolError, match="outside|worktree"):
        validate_custodian_store_path(inside, worktree_path=worktree)

    outside = tmp_path / "custodian-store" / "blind.bundle"
    outside.parent.mkdir()
    outside.write_bytes(b"\x00secret")
    resolved = validate_custodian_store_path(outside, worktree_path=worktree)
    assert resolved == outside.resolve()


# ---------------------------------------------------------------------------
# Access ledger
# ---------------------------------------------------------------------------


def _authorization_for(seal) -> HoldoutAccessAuthorization:
    return HoldoutAccessAuthorization.build(
        seal=seal,
        candidate_freeze_cid=cid_for_dag_json(
            {"candidate": "plat2-055-synthetic-freeze"}
        ),
    )


def test_access_ledger_rejects_before_authorization_and_repeated_access(
    tmp_path: Path,
) -> None:
    seal = build_frozen_blind_holdout_seal()
    ledger_path = tmp_path / "custodian" / "access.jsonl"
    ledger = AppendOnlyAccessLedger(ledger_path, seal=seal)

    rejected = request_blind_access(
        ledger,
        authorization=None,
        executor_id="executor-test",
    )
    assert rejected.event == "unauthorized_access_rejected"
    assert rejected.interface == HOLDOUT_ACCESS_AUDIT_INTERFACE

    auth = _authorization_for(seal)
    grant = request_blind_access(
        ledger,
        authorization=auth,
        executor_id="executor-test",
    )
    assert grant.event == "access_granted"
    assert grant.authorization_goal_id == AUTHORIZATION_GOAL_ID

    released = release_blind_manifest(
        ledger,
        authorization=auth,
        executor_id="executor-test",
    )
    assert released.event == "manifest_released"

    repeated = request_blind_access(
        ledger,
        authorization=auth,
        executor_id="executor-test",
    )
    assert repeated.event == "repeated_access_rejected"

    tuning = reject_post_access_tuning(
        ledger,
        executor_id="executor-test",
        attempted_change="threshold_tweak",
    )
    assert tuning.event == "post_access_tuning_rejected"

    receipts = ledger.read_receipts()
    assert [item.event for item in receipts] == [
        "unauthorized_access_rejected",
        "access_granted",
        "manifest_released",
        "repeated_access_rejected",
        "post_access_tuning_rejected",
    ]
    # Chain integrity.
    assert receipts[0].previous_receipt_cid is None
    for index in range(1, len(receipts)):
        assert receipts[index].previous_receipt_cid == receipts[index - 1].receipt_cid


def test_access_grant_without_plat2_055_goal_is_rejected(tmp_path: Path) -> None:
    seal = build_frozen_blind_holdout_seal()
    ledger = AppendOnlyAccessLedger(tmp_path / "ledger.jsonl", seal=seal)
    # Build a structurally valid-looking but wrong-goal authorization via raw dict.
    with pytest.raises(HoldoutProtocolError, match="PLAT2-055|goal_id"):
        HoldoutAccessAuthorization(
            goal_id="PLAT2-000",
            authorization_cid=cid_for_dag_json({"bad": True}),
            seal_cid=seal.seal_cid,
            candidate_freeze_cid=cid_for_dag_json({"c": 1}),
            complete=True,
            holdout_authorized=True,
            outcomes_inspected=False,
            tuning_permitted=False,
        )


def test_post_access_tuning_without_prior_access_fails(tmp_path: Path) -> None:
    seal = build_frozen_blind_holdout_seal()
    ledger = AppendOnlyAccessLedger(tmp_path / "ledger.jsonl", seal=seal)
    with pytest.raises(HoldoutProtocolError, match="prior successful access"):
        reject_post_access_tuning(
            ledger,
            executor_id="executor-test",
            attempted_change="prompt_edit",
        )


# ---------------------------------------------------------------------------
# Docs
# ---------------------------------------------------------------------------


def test_holdout_docs_describe_three_population_custody_model() -> None:
    assert HOLDOUT_DOCS.is_file()
    text = HOLDOUT_DOCS.read_text(encoding="utf-8")
    for token in (
        "PLAT2-020",
        "repair_development",
        "blind_holdout",
        "pilot",
        "plateau2_blind_holdout_seal.json",
        "repair_dev_cases.json",
        "PLAT2-055",
        "append-only",
        "exploratory",
        "promotion",
        "aggregate",
    ):
        assert token in text, f"docs missing {token!r}"
    # Must not claim that private blind sources live in the repo fixture.
    assert "custodian" in text.lower()
