"""Flag-first worldwide query. Unpublished jurisdictions do not fall back to US Code."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.processors.legal_data.query_legal_records import (
    LegalQueryDisabled,
    LegalQueryInputError,
    query_legal_records,
)

_WORLD_SHA = "53a38d3ea51402640141bf1f1126d669c1277e46"


def _opened(calls: list[str]):
    def opener(repo: str) -> tuple[dict[str, object], ...]:
        calls.append(repo)
        return ({"entry_cid": "cid-1", "text": "body", "provenance": {}},)

    return opener


def test_flag_off_raises_before_resolution(monkeypatch) -> None:
    monkeypatch.delenv("LEGAL_QUERY_NORMALIZED", raising=False)
    calls: list[str] = []
    for jurisdiction in ("AQ", "ZZ", "US", "FR"):
        with pytest.raises(LegalQueryDisabled):
            query_legal_records(
                jurisdiction=jurisdiction,
                text_query="",
                corpus_opener=_opened(calls),
            )
    assert calls == []


def test_flag_on_unknown_codes_are_empty(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "1")
    calls: list[str] = []
    for jurisdiction in ("AQ", "ZZ"):
        result = query_legal_records(
            jurisdiction=jurisdiction,
            text_query="",
            citation="",
            corpus_opener=_opened(calls),
        )
        assert result.schema_version == "legal-query/v1"
        assert result.record_schema == "legal-record/v1"
        assert result.jurisdiction == jurisdiction
        assert result.coverage == "not_published"
        assert result.records == ()
        assert result.source_repo is None
        assert not hasattr(result, "error")
    assert calls == []


def test_us_statute_without_admin_level_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "1")
    calls: list[str] = []
    with pytest.raises(LegalQueryInputError) as raised:
        query_legal_records(
            jurisdiction="US",
            text_query="title 18",
            instrument_type="statute",
            corpus_opener=_opened(calls),
        )
    assert raised.value.code == "admin_level_required"
    assert calls == []


def test_uk_and_cw_name_the_catalog_slug(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "1")
    uk = query_legal_records(jurisdiction="uk", text_query="theft")
    gb = query_legal_records(jurisdiction="GB", text_query="theft")
    assert uk.jurisdiction == gb.jurisdiction == "GB"
    assert uk.source_repo == gb.source_repo == "justicedao/ipfs_uk_laws_ir"
    assert uk.coverage == "snapshot"
    cw = query_legal_records(jurisdiction="CW", text_query="tax")
    assert cw.jurisdiction == "CW"
    assert cw.source_repo == "justicedao/ipfs_curacao_laws_ir"


def test_stale_france_does_not_open_world_until_the_pin_is_readable(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "1")
    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_data.query_legal_records.pin_readable",
        lambda _repo: False,
    )
    calls: list[str] = []
    closed = query_legal_records(
        jurisdiction="FR",
        text_query="code civil",
        gap_status="stale",
        corpus_opener=_opened(calls),
    )
    assert closed.coverage == "not_published"
    assert closed.records == ()
    assert closed.source_repo is None
    assert calls == []

    stale = query_legal_records(
        jurisdiction="france",
        text_query="code civil",
        gap_status="stale",
        allow_stale=True,
        corpus_opener=_opened(calls),
    )
    assert stale.jurisdiction == "FR"
    assert stale.coverage == "stale_pin"
    assert stale.source_repo == "justicedao/ipfs_france_laws_ir"
    assert calls == ["justicedao/ipfs_france_laws_ir"]


def test_readable_world_pin_returns_partial_with_revision(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "1")

    def readable(repo: str) -> bool:
        return repo.split("/", 1)[-1] == "world_national_law"

    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_data.query_legal_records.pin_readable",
        readable,
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_data.query_legal_records.pin_revision",
        lambda repo: _WORLD_SHA if repo.endswith("world_national_law") else None,
    )
    calls: list[str] = []
    result = query_legal_records(
        jurisdiction="FR",
        text_query="code civil",
        gap_status="stale",
        corpus_opener=_opened(calls),
    )
    assert result.coverage == "partial"
    assert result.source_repo == "justicedao/world_national_law"
    assert result.source_revision == _WORLD_SHA
    assert calls == ["justicedao/world_national_law"]
    assert result.records[0]["provenance"]["fallback_from"] == "stale"
    current = query_legal_records(
        jurisdiction="FR",
        text_query="code civil",
        gap_status="current",
        corpus_opener=_opened(calls),
    )
    assert current.coverage == "current"
    assert current.source_repo == "justicedao/ipfs_france_laws_ir"
    assert calls[-1] == "justicedao/ipfs_france_laws_ir"


def test_admin_level_repo_is_not_replaced_by_instrument(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "1")
    federal = query_legal_records(
        jurisdiction="US",
        text_query="title 18",
        admin_level="us-federal",
        instrument_type="register",
    )
    assert federal.source_repo == "justicedao/ipfs_uscode"
    assert federal.coverage == "current"
    state = query_legal_records(
        jurisdiction="US",
        text_query="penal",
        admin_level="us-state",
        instrument_type="case",
    )
    assert state.source_repo == "justicedao/ipfs_state_laws"
    assert state.coverage == "current"
    patent_state = query_legal_records(
        jurisdiction="US",
        text_query="claim",
        admin_level="us-federal",
        instrument_type="patent",
    )
    assert patent_state.source_repo == "justicedao/ipfs_uscode"


def test_instrument_without_admin_level_selects_its_repo(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "1")
    register = query_legal_records(
        jurisdiction="US",
        text_query="notice",
        instrument_type="register",
    )
    assert register.source_repo == "justicedao/federal-register-full-graphrag-v20260810"
    assert register.coverage == "current"
    case = query_legal_records(
        jurisdiction="US",
        text_query="brown",
        instrument_type="case",
    )
    assert case.source_repo == "justicedao/ipfs_caselaw_access_project"
    assert case.coverage == "snapshot"
    patent = query_legal_records(
        jurisdiction="US",
        text_query="claim",
        instrument_type="patent",
    )
    assert patent.source_repo == "justicedao/patent-legal-ir-graphrag"
    assert patent.coverage == "current"


def test_query_id_is_stable_for_the_same_request(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "1")
    first = query_legal_records(jurisdiction="FR", text_query="code", citation="art 1")
    second = query_legal_records(jurisdiction="FR", text_query="code", citation="art 1")
    changed = query_legal_records(jurisdiction="FR", text_query="code", citation="art 2")
    assert first.query_id == second.query_id
    assert len(first.query_id) == 64
    assert changed.query_id != first.query_id


def test_missing_municipal_slug_does_not_invent_a_repo(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "1")
    closed = query_legal_records(
        jurisdiction="CL",
        text_query="ordenanza",
        admin_level="municipality",
    )
    assert closed.coverage == "not_published"
    assert closed.source_repo is None
    named = query_legal_records(jurisdiction="chile_municipal", text_query="ordenanza")
    assert named.coverage == "not_published"
    assert named.source_repo is None
    hungary = query_legal_records(jurisdiction="hungary_municipal", text_query="rendelet")
    assert hungary.source_repo is None
    spain = query_legal_records(jurisdiction="spain_municipal", text_query="ordenanza")
    assert spain.jurisdiction == "ES"
    assert spain.source_repo == "justicedao/ipfs_spain_municipal_laws_ir"


_MATCH = "a" * 40
_OTHER = "b" * 40


def test_alias_sha_selects_one_spelling(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "1")
    alias_only = query_legal_records(
        jurisdiction="PG",
        text_query="land",
        alias_revisions={
            "papua_new_guinea": (_MATCH, _MATCH),
            "papuanewguinea": (_OTHER, _MATCH),
        },
    )
    assert alias_only.jurisdiction == "PG"
    assert alias_only.source_repo == "justicedao/ipfs_papua_new_guinea_laws_ir"
    neither = query_legal_records(
        jurisdiction="papua_new_guinea",
        text_query="land",
        alias_revisions={
            "papua_new_guinea": (_OTHER, _MATCH),
            "papuanewguinea": (_MATCH, _OTHER),
        },
    )
    assert neither.jurisdiction == "PG"
    assert neither.source_repo == "justicedao/ipfs_papuanewguinea_laws_ir"
    both = query_legal_records(
        jurisdiction="papua_new_guinea",
        text_query="land",
        alias_revisions={
            "papua_new_guinea": (_MATCH, _MATCH),
            "papuanewguinea": (_MATCH, _MATCH),
        },
    )
    assert both.source_repo == "justicedao/ipfs_papuanewguinea_laws_ir"
    unset = query_legal_records(jurisdiction="PG", text_query="land")
    assert unset.source_repo == "justicedao/ipfs_papuanewguinea_laws_ir"
