"""Exact vector-aware enacted-body proof for Arkansas Act 373, section 11."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
    StateLawMultiFetchAcquisitionLedger,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
    arkansas_act373 as act373,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.arkansas import (
    ArkansasScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.arkansas_lexis import (
    ARKANSAS_DELEGATED_INVENTORY_SHA256,
    CURRENT_VARIANT_RESOLVER_PARSER_NAME,
    load_exact_retained_inventory,
    reconcile_current_statute_variants,
    resolve_act373_enacted_body,
)

_EVIDENCE_ROOT = Path(
    os.environ.get("ARKANSAS_ACT373_TEST_EVIDENCE_ROOT")
    or "/home/barberb/.ipfs_datasets/state_laws/"
    "legal-corpora-reindex-20260829-ar-act373-proof-Zyxt13"
)
_INVENTORY_PATH = Path(
    os.environ.get("ARKANSAS_EXACT_CURRENT_TEST_INVENTORY")
    or "/home/barberb/.ipfs_datasets/state_laws/"
    "legal-corpora-reindex-20260824/arkansas-delegated-inventory-v6/"
    "arkansas-lexis-toc.json"
)
_REPORT_PATH = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "reports"
    / "legal_corpora_reindex"
    / "arkansas_act373_act926_temporal_audit_v1.md"
)


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _require_evidence() -> None:
    if not _INVENTORY_PATH.is_file():
        pytest.skip("exact retained Arkansas inventory is not installed")
    if not (_EVIDENCE_ROOT / "AR" / "fetches").is_dir():
        pytest.skip("exact retained Arkansas Act 373 proof is not installed")


def _ledger() -> StateLawMultiFetchAcquisitionLedger:
    return StateLawMultiFetchAcquisitionLedger(
        _EVIDENCE_ROOT,
        jurisdiction="AR",
        parser_name=CURRENT_VARIANT_RESOLVER_PARSER_NAME,
        retained_replay_only=True,
    )


def _proof_inputs(ledger: StateLawMultiFetchAcquisitionLedger):
    keys = tuple(act373.ACT373_TEMPORAL_SOURCE_INPUT_CONTRACT)
    retained = ledger.replay_retained_parser_inputs(
        requests=tuple(
            (
                act373.ACT373_TEMPORAL_SOURCE_INPUT_CONTRACT[key][0],
                {
                    "method": "GET",
                    "url": act373.ACT373_TEMPORAL_SOURCE_INPUT_CONTRACT[key][0],
                },
            )
            for key in keys
        )
    )
    return dict(zip(keys, retained, strict=True))


def _object(digest: str) -> bytes:
    return (_EVIDENCE_ROOT / "AR" / "objects" / f"{digest}.bin").read_bytes()


def _snapshot() -> dict[str, object]:
    return act373.extract_act373_geometry_snapshot(_object(act373.ACT373_SHA256))


def _report_table() -> dict[str, str]:
    rows: dict[str, str] = {}
    for raw_line in _REPORT_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != 2:
            continue
        field, value = cells
        if field in {"Field", "---"} or set(field) == {"-"}:
            continue
        rows[field] = value.strip("`")
    return rows


def test_act373_text_constant_has_an_independent_digest() -> None:
    assert len(act373.ACT373_CURRENT_TEXT.encode("utf-8")) == 530
    assert (
        hashlib.sha256(act373.ACT373_CURRENT_TEXT.encode("utf-8")).hexdigest()
        == act373.ACT373_CURRENT_TEXT_SHA256
    )
    assert "which reflects" not in act373.ACT373_CURRENT_TEXT
    assert "costs of providing service to each class" not in (
        act373.ACT373_CURRENT_TEXT
    )
    assert "consistent with" in act373.ACT373_CURRENT_TEXT
    assert "last approved cost-of-service study" in act373.ACT373_CURRENT_TEXT

    report = _report_table()
    assert report["temporal_status"] == "partial_source_closure"
    assert report["temporal_authorizing_for_materialization"] == "false"
    assert report["temporal_publication_authorized"] == "false"
    assert report["temporal_rows_closed"] == "1"
    assert report["temporal_closed_citations"] == act373.ACT373_SECTION_NUMBER
    assert report["temporal_unresolved_citations"] == (
        "19-42-201, 27-14-802, 27-14-803, 5-64-308"
    )
    assert report["act373_disposition"] == "selected_current_source_body"
    assert report["act373_delegated_urn_selected"] == "false"
    assert report["act373_source_sha256"] == act373.ACT373_SHA256
    assert report["act373_current_text_sha256"] == (act373.ACT373_CURRENT_TEXT_SHA256)
    assert report["act373_geometry_sha256"] == act373.ACT373_GEOMETRY_SHA256
    assert report["act373_pagination_sha256"] == (act373.ACT373_PAGINATION_SHA256)
    assert report["act373_amendment_instruction_sha256"] == (
        act373.ACT373_AMENDMENT_INSTRUCTION_SHA256
    )
    assert report["act373_markup_geometry_sha256"] == (
        act373.ACT373_MARKUP_GEOMETRY_SHA256
    )
    assert report["act373_effective_date_geometry_sha256"] == (
        act373.ACT373_EFFECTIVE_DATE_GEOMETRY_SHA256
    )
    assert report["act373_mark_projection_sha256"] == (
        act373.ACT373_MARK_PROJECTION_SHA256
    )
    assert report["temporal_preflight_selected_current_source_body"] == "1"
    assert report["temporal_preflight_unresolved"] == "4"
    assert report["temporal_act926_certification_locator"] == "unidentified"
    assert report["temporal_act926_occurrence_encoded"] == "false"
    assert report["temporal_act926_nonoccurrence_encoded"] == "false"
    assert report["temporal_full_state_live_to_retained_run"].startswith("not launched")


def test_act373_rejects_unpinned_source_bytes_before_pdf_parsing() -> None:
    with pytest.raises(ValueError, match="SHA-256 drifted"):
        act373.validate_act373_enacted_section(b"x" * act373.ACT373_BYTE_SIZE)


def test_act373_exact_pdf_derives_only_the_coordinate_bound_current_body() -> None:
    _require_evidence()
    result = act373.validate_act373_enacted_section(_object(act373.ACT373_SHA256))

    assert result.section_number == "23-4-909"
    assert result.full_text == act373.ACT373_CURRENT_TEXT
    assert result.full_text_sha256 == act373.ACT373_CURRENT_TEXT_SHA256
    assert result.effective_date == "2025-03-20"
    assert result.page_count == 63
    assert result.printed_pages == (6, 7, 62, 63)
    assert result.geometry_sha256 == act373.ACT373_GEOMETRY_SHA256
    assert result.pagination_sha256 == act373.ACT373_PAGINATION_SHA256
    assert result.amendment_instruction_sha256 == (
        act373.ACT373_AMENDMENT_INSTRUCTION_SHA256
    )
    assert result.markup_geometry_sha256 == (act373.ACT373_MARKUP_GEOMETRY_SHA256)
    assert result.effective_date_geometry_sha256 == (
        act373.ACT373_EFFECTIVE_DATE_GEOMETRY_SHA256
    )
    assert result.mark_projection_sha256 == (act373.ACT373_MARK_PROJECTION_SHA256)
    assert (result.inserted_word_count, result.deleted_word_count) == (41, 9)


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (
            lambda value: value.__setitem__("page_count", 62),
            "pagination projection drifted",
        ),
        (
            lambda value: value["amendment_instruction"][0]["rect"].__setitem__(
                0, 122.421
            ),
            "amendment instruction drifted",
        ),
        (
            lambda value: value["section_rules"][0]["rect"].__setitem__(1, 681.941),
            "markup geometry drifted",
        ),
        (
            lambda value: value["effective_words"][0]["rect"].__setitem__(1, 364.929),
            "effective-date geometry drifted",
        ),
    ),
)
def test_act373_independent_coordinate_seals_reject_adversarial_drift(
    mutation,
    message: str,
) -> None:
    _require_evidence()
    snapshot = copy.deepcopy(_snapshot())
    mutation(snapshot)
    with pytest.raises(ValueError, match=message):
        act373.derive_act373_enacted_section_from_snapshot(snapshot)


def _rebind_mutated_geometry_seals(
    monkeypatch: pytest.MonkeyPatch,
    snapshot: dict[str, object],
) -> None:
    monkeypatch.setattr(
        act373,
        "ACT373_MARKUP_GEOMETRY_SHA256",
        _canonical_sha256(
            {key: snapshot[key] for key in ("body_words", "section_rules")}
        ),
    )
    monkeypatch.setattr(
        act373,
        "ACT373_GEOMETRY_SHA256",
        _canonical_sha256(snapshot),
    )


def test_act373_underline_moved_to_strike_position_is_not_admitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _require_evidence()
    snapshot = copy.deepcopy(_snapshot())
    consistent_rule = next(
        rule
        for rule in snapshot["section_rules"]
        if rule["page_index"] == 6 and rule["rect"][0] == 459.55
    )
    consistent_rule["rect"][1:4:2] = [101.9, 102.38]
    _rebind_mutated_geometry_seals(monkeypatch, snapshot)

    with pytest.raises(ValueError, match="strike/underline projection drifted"):
        act373.derive_act373_enacted_section_from_snapshot(snapshot)


def test_act373_resulting_text_seal_rejects_reclassified_markup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _require_evidence()
    snapshot = copy.deepcopy(_snapshot())
    consistent_rule = next(
        rule
        for rule in snapshot["section_rules"]
        if rule["page_index"] == 6 and rule["rect"][0] == 459.55
    )
    consistent_rule["rect"][1:4:2] = [101.9, 102.38]
    _rebind_mutated_geometry_seals(monkeypatch, snapshot)
    marked = act373._classify_section_words(snapshot)
    monkeypatch.setattr(
        act373,
        "ACT373_MARK_PROJECTION_SHA256",
        _canonical_sha256(marked),
    )

    with pytest.raises(ValueError, match="resulting enacted text drifted"):
        act373.derive_act373_enacted_section_from_snapshot(snapshot)


def test_act373_temporal_chain_is_exact_and_rejects_each_later_session_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _require_evidence()
    bodies = {
        "change_table_2025": _object(act373.ACT373_2025_CHANGE_TABLE_SHA256),
        "current_session_contract": _object(
            act373.ARKANSAS_CURRENT_SESSION_CONTRACT_SHA256
        ),
        "change_table_2026f": _object(act373.ACT373_2026F_CHANGE_TABLE_SHA256),
        "change_table_2026s1": _object(act373.ACT373_2026S1_CHANGE_TABLE_SHA256),
    }
    chronology = act373.validate_act373_temporal_chain(**bodies)
    assert chronology.later_sessions == ("2025/2026F", "2025/2026S1")
    assert chronology.fiscal_2026_title_23_rows == (("23-86-119(a)(1)", "147", "SB7"),)
    assert chronology.extraordinary_2026_title_23_terminal == (
        "No amended code for this section."
    )

    changed_2025 = bodies["change_table_2025"].replace(
        b">23-4-909</div>",
        b">23-4-908</div>",
    )
    assert len(changed_2025) == len(bodies["change_table_2025"])
    monkeypatch.setattr(
        act373,
        "ACT373_2025_CHANGE_TABLE_SHA256",
        hashlib.sha256(changed_2025).hexdigest(),
    )
    with pytest.raises(ValueError, match="row is not unique"):
        act373.validate_act373_temporal_chain(
            **{**bodies, "change_table_2025": changed_2025}
        )
    monkeypatch.setattr(
        act373,
        "ACT373_2025_CHANGE_TABLE_SHA256",
        hashlib.sha256(bodies["change_table_2025"]).hexdigest(),
    )

    changed_sessions = bodies["current_session_contract"].replace(
        b'2025/2026S1">',
        b'2025/2026S2">',
    )
    assert len(changed_sessions) == len(bodies["current_session_contract"])
    monkeypatch.setattr(
        act373,
        "ARKANSAS_CURRENT_SESSION_CONTRACT_SHA256",
        hashlib.sha256(changed_sessions).hexdigest(),
    )
    with pytest.raises(ValueError, match="session frontier drifted"):
        act373.validate_act373_temporal_chain(
            **{**bodies, "current_session_contract": changed_sessions}
        )
    monkeypatch.setattr(
        act373,
        "ARKANSAS_CURRENT_SESSION_CONTRACT_SHA256",
        hashlib.sha256(bodies["current_session_contract"]).hexdigest(),
    )

    changed_2026f = bodies["change_table_2026f"].replace(
        b">23-86-119(a)(1)</div>",
        b">23-86-119(a)(2)</div>",
    )
    assert len(changed_2026f) == len(bodies["change_table_2026f"])
    monkeypatch.setattr(
        act373,
        "ACT373_2026F_CHANGE_TABLE_SHA256",
        hashlib.sha256(changed_2026f).hexdigest(),
    )
    with pytest.raises(ValueError, match="2026F title 23 amendment frontier"):
        act373.validate_act373_temporal_chain(
            **{**bodies, "change_table_2026f": changed_2026f}
        )
    monkeypatch.setattr(
        act373,
        "ACT373_2026F_CHANGE_TABLE_SHA256",
        hashlib.sha256(bodies["change_table_2026f"]).hexdigest(),
    )

    changed_2026s1 = bodies["change_table_2026s1"].replace(
        b"No amended code for this section.",
        b"XX amended code for this section.",
    )
    assert len(changed_2026s1) == len(bodies["change_table_2026s1"])
    monkeypatch.setattr(
        act373,
        "ACT373_2026S1_CHANGE_TABLE_SHA256",
        hashlib.sha256(changed_2026s1).hexdigest(),
    )
    with pytest.raises(ValueError, match="2026S1 title 23 terminal"):
        act373.validate_act373_temporal_chain(
            **{**bodies, "change_table_2026s1": changed_2026s1}
        )


def test_act373_resolution_selects_source_body_and_no_delegated_urn() -> None:
    _require_evidence()
    inventory, inventory_sha256 = load_exact_retained_inventory(_INVENTORY_PATH)
    assert inventory_sha256 == ARKANSAS_DELEGATED_INVENTORY_SHA256
    resolution = resolve_act373_enacted_body(
        inventory.nodes,
        inventory_sha256=inventory_sha256,
        retained_inputs=_proof_inputs(_ledger()),
    )
    assert resolution.evidence_verified
    decisions = reconcile_current_statute_variants(
        inventory.nodes,
        observed_at=inventory.observed_at,
        source_bound_resolutions=(resolution,),
    )
    decision = next(item for item in decisions if item.section_number == "23-4-909")
    assert decision.disposition == "selected_current_source_body"
    assert decision.candidate_node_ids == (
        "AAXAABAAFAAJAAK",
        "AAXAABAAFAAJAAL",
    )
    assert not hasattr(decision, "selected_node_id")
    assert decision.full_text_sha256 == act373.ACT373_CURRENT_TEXT_SHA256


def test_act373_retained_preflight_closes_one_row_with_zero_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _require_evidence()
    inventory, inventory_sha256 = load_exact_retained_inventory(_INVENTORY_PATH)
    ledger = _ledger()
    before = (
        len(list((_EVIDENCE_ROOT / "AR" / "fetches").glob("*.json"))),
        len(list((_EVIDENCE_ROOT / "AR" / "objects").glob("*.bin"))),
    )
    scraper = ArkansasScraper("AR", "Arkansas")
    scraper.attach_arkansas_current_variant_resolution_ledger(ledger)

    async def _network_forbidden(*_args, **_kwargs):
        raise AssertionError("Act 373 preflight must remain zero-network")

    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _network_forbidden,
    )
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _network_forbidden,
    )
    result = asyncio.run(
        scraper._resolve_exact_current_variant_frontier(
            nodes=inventory.nodes,
            observed_at=inventory.observed_at,
            inventory_sha256=inventory_sha256,
        )
    )

    assert result["current_counts"] == {
        "selected_current_locator": 127,
        "no_current_locator": 1,
        "unresolved": 4,
    }
    assert result["original_conflict_counts"] == {
        "selected_current_locator": 33,
        "no_current_locator": 0,
        "unresolved": 4,
    }
    assert result["selected_current_source_body_count"] == 1
    assert result["unresolved_section_numbers"] == [
        "19-42-201",
        "27-14-802",
        "27-14-803",
        "5-64-308",
    ]
    assert result["decision_sha256"] == (
        "3d75e491f3052a8decb129d8f4af27675cdbb24edaad27d6d96d674f9eb81e94"
    )
    assert result["act373"]["disposition"] == ("selected_current_source_body")
    assert result["act373"]["network_requested_pages"] == 0
    assert result["authorizing_for_materialization"] is False
    after = (
        len(list((_EVIDENCE_ROOT / "AR" / "fetches").glob("*.json"))),
        len(list((_EVIDENCE_ROOT / "AR" / "objects").glob("*.bin"))),
    )
    assert after == before == (70, 70)
