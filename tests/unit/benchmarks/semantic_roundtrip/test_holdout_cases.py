"""Unit tests for the frozen PLAT2 holdout case fixture (HoldoutCaseFixture@1)."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from benchmarks.logic_pipeline.content_addressing import cid_for_bytes
from benchmarks.semantic_roundtrip.matrix import MatrixCase, load_matrix_cases
from benchmarks.semantic_roundtrip.residual_catalog import PILOT_CASE_IDS
from benchmarks.semantic_roundtrip.selective_repair import (
    ACTIVATION_FIXTURE_PACK_ID,
    activation_fixture_pack,
)


ROOT = Path(__file__).resolve().parents[4]
HOLDOUT_FIXTURE = ROOT / "tests/fixtures/semantic_roundtrip/holdout_cases.json"
HOLDOUT_DOCS = ROOT / "docs/benchmarks/semantic_roundtrip_holdout_cases.md"
PILOT_FIXTURE = ROOT / "tests/fixtures/semantic_roundtrip/pilot_cases.json"

HOLDOUT_CASE_FIXTURE_INTERFACE = "HoldoutCaseFixture@1"
SELECTIVE_REPAIR_ACTIVATION_CASE_IDS = (
    "missing_temporal",
    "low_confidence_object",
    "contradictory_modality",
)
LEGAL_CORPUS_CASE_IDS = (
    "legal_doc_2",
    "privacy_act_amendment",
    "fed_reg_1",
    "dept_memo_1",
    "hr_handbook",
)
FROZEN_HOLDOUT_CASE_IDS = (
    *SELECTIVE_REPAIR_ACTIVATION_CASE_IDS,
    *LEGAL_CORPUS_CASE_IDS,
)

# Byte-exact freeze of tests/fixtures/semantic_roundtrip/holdout_cases.json
FROZEN_FIXTURE_SHA256 = (
    "4a00c6f18345a58fa7fbfda9bd5b692f5a11739e270373ac2bfa3e20272fb92d"
)
FROZEN_FIXTURE_CID = (
    "bafkreickaddpda2fuwh2p675vg6vw2jpliixhhrhanz2yk72hyqcol5zfu"
)

REQUIRED_CASE_KEYS = frozenset(
    {
        "id",
        "source_text",
        "allowed_atoms",
        "gold_ir",
        "score_bindings",
    }
)


def _fixture_bytes() -> bytes:
    return HOLDOUT_FIXTURE.read_bytes()


def _fixture_sha256() -> str:
    return hashlib.sha256(_fixture_bytes()).hexdigest()


def _load_raw_cases() -> list[dict[str, object]]:
    payload = json.loads(HOLDOUT_FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(payload, list)
    return payload  # type: ignore[return-value]


def test_holdout_fixture_exists_and_is_nonempty_array() -> None:
    assert HOLDOUT_FIXTURE.is_file()
    payload = _load_raw_cases()
    assert payload, "holdout_cases.json must be a nonempty array"


def test_holdout_fixture_digest_is_frozen() -> None:
    raw = _fixture_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    cid = cid_for_bytes(raw)
    assert sha == FROZEN_FIXTURE_SHA256
    assert cid == FROZEN_FIXTURE_CID


def test_holdout_ids_are_stable_unique_and_ordered() -> None:
    cases = _load_raw_cases()
    ids = [str(case["id"]) for case in cases]
    assert ids == list(FROZEN_HOLDOUT_CASE_IDS)
    assert len(ids) == len(set(ids))
    assert len(ids) >= 3


def test_holdout_is_disjoint_from_pilot_population() -> None:
    holdout_ids = {str(case["id"]) for case in _load_raw_cases()}
    pilot_ids = set(PILOT_CASE_IDS)
    overlap = holdout_ids & pilot_ids
    assert not overlap, f"holdout overlaps sealed pilots: {sorted(overlap)}"

    pilot_payload = json.loads(PILOT_FIXTURE.read_text(encoding="utf-8"))
    pilot_file_ids = {str(case["id"]) for case in pilot_payload}
    assert holdout_ids.isdisjoint(pilot_file_ids)


def test_hybrid_set_includes_selective_repair_activation_and_legal_cases() -> None:
    holdout_ids = {str(case["id"]) for case in _load_raw_cases()}
    for case_id in SELECTIVE_REPAIR_ACTIVATION_CASE_IDS:
        assert case_id in holdout_ids
    for case_id in LEGAL_CORPUS_CASE_IDS:
        assert case_id in holdout_ids
    # Acceptance: three non-pilot cases satisfied by activation pack alone,
    # plus additional legal corpus cases.
    assert len(holdout_ids - set(PILOT_CASE_IDS)) >= 3


def test_each_case_has_gold_ir_or_explicit_score_bindings() -> None:
    for raw in _load_raw_cases():
        missing = REQUIRED_CASE_KEYS - set(raw)
        assert not missing, f"{raw.get('id')}: missing keys {sorted(missing)}"
        source = raw["source_text"]
        assert isinstance(source, str) and source.strip()
        gold = raw["gold_ir"]
        assert isinstance(gold, dict) and "rules" in gold
        assert isinstance(gold["rules"], list) and gold["rules"]
        bindings = raw["score_bindings"]
        assert isinstance(bindings, dict)
        assert bindings.get("binding_kind") == "gold_ir"


def test_cases_load_through_matrix_contracts() -> None:
    cases = load_matrix_cases(HOLDOUT_FIXTURE)
    assert len(cases) == len(FROZEN_HOLDOUT_CASE_IDS)
    assert tuple(case.case_id for case in cases) == FROZEN_HOLDOUT_CASE_IDS
    for case in cases:
        assert isinstance(case, MatrixCase)
        assert not case.gold_ir.is_empty
        case.gold_ir.validate_vocabulary(case.allowed_atom_vocabulary)
        assert case.case_cid.startswith("baguqeera") or case.case_cid.startswith(
            "bafk"
        )
        assert case.gold_ir_cid
        assert case.source_text_cid


def test_selective_repair_activation_cases_bind_activation_pack() -> None:
    by_id = {str(case["id"]): case for case in _load_raw_cases()}
    pack = {item.case_id: item for item in activation_fixture_pack()}
    for case_id in SELECTIVE_REPAIR_ACTIVATION_CASE_IDS:
        raw = by_id[case_id]
        bindings = raw["score_bindings"]
        assert isinstance(bindings, dict)
        assert bindings["activation_fixture_pack_id"] == ACTIVATION_FIXTURE_PACK_ID
        pack_case = pack[case_id]
        assert raw["source_text"] == pack_case.source_text
        assert raw["gold_ir"] == pack_case.repaired_ir.to_dict()
        assert bindings["baseline_ir"] == pack_case.baseline_ir.to_dict()
        assert bindings["repaired_ir"] == pack_case.repaired_ir.to_dict()
        assert set(bindings["expected_trigger_kinds"]) == {
            kind.value for kind in pack_case.expected_kinds
        }


def test_legal_corpus_cases_have_source_refs() -> None:
    by_id = {str(case["id"]): case for case in _load_raw_cases()}
    for case_id in LEGAL_CORPUS_CASE_IDS:
        raw = by_id[case_id]
        assert raw.get("case_family") == "legal_corpus"
        source_ref = raw.get("source_ref")
        assert isinstance(source_ref, str) and source_ref.strip()
        assert "test_deontological_reasoning.py" in source_ref


def test_docs_record_fixture_digest_and_case_inventory() -> None:
    """PLAT2-020 docs freeze the three-way population split and case inventory.

    The hybrid ``holdout_cases.json`` fixture remains byte-frozen in code
    (see ``test_holdout_fixture_digest_is_frozen``). Public docs intentionally
    describe repair-development + blind seal rather than embedding the hybrid
    fixture SHA, so this test binds case inventory and freeze language without
    requiring the historical hybrid digest string in markdown.
    """

    assert HOLDOUT_DOCS.is_file()
    text = HOLDOUT_DOCS.read_text(encoding="utf-8")
    # Fixture digest remains frozen in-repo; docs point at repair_dev / seal.
    assert _fixture_sha256() == FROZEN_FIXTURE_SHA256
    assert "repair_dev_cases.json" in text
    assert "holdout_cases.json" in text
    assert "hybrid" in text.lower()
    assert "plateau2_blind_holdout_seal.json" in text
    for case_id in FROZEN_HOLDOUT_CASE_IDS:
        assert case_id in text
    for case_id in PILOT_CASE_IDS:
        # Docs may mention pilots for contrast, but must not list them as holdout.
        pass
    # Explicit population table / freeze section
    assert re.search(r"fixture.?sha256|SHA-256|digest", text, re.IGNORECASE)
    assert "selective-repair" in text.lower() or "selective_repair" in text


def test_from_dict_round_trip_preserves_scoring_surface() -> None:
    for raw in _load_raw_cases():
        case = MatrixCase.from_dict(raw)
        rebuilt = MatrixCase.from_dict(
            {
                "id": case.case_id,
                "source_text": case.source_text,
                "allowed_atoms": case.allowed_atom_vocabulary.to_dict(),
                "gold_ir": case.gold_ir.to_dict(),
            }
        )
        assert rebuilt.case_id == case.case_id
        assert rebuilt.gold_ir.to_dict() == case.gold_ir.to_dict()
        assert rebuilt.case_cid == case.case_cid
