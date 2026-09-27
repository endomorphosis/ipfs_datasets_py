"""JusticeDAO search pins collapse duplicate Hugging Face repos."""

from __future__ import annotations

from pathlib import Path

from ipfs_datasets_py.processors.legal_data.justicedao_release_registry import (
    build_release_registry,
    selected_releases,
)

_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "justicedao_public_datasets_20260925.txt"
)


def _ids() -> list[str]:
    return [line.strip() for line in _FIXTURE.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_public_justicedao_repos_collapse_to_one_pin_per_source() -> None:
    dataset_ids = _ids()
    releases = build_release_registry(dataset_ids)
    by_repo = {item.hf_repo: item for item in releases}

    assert len(by_repo) == len(dataset_ids)
    assert set(by_repo) == set(dataset_ids)
    assert all(item.authoritative is False for item in releases)
    assert all(item.ducklake_authoritative is False for item in releases)
    assert all(item.research_only is True for item in releases)
    assert not any(item.layout_profile == "unclassified" for item in releases)

    checkpoint = by_repo["justicedao/legal-ir-autoencoder-checkpoints"]
    assert checkpoint.layout_profile == "excluded"
    assert checkpoint.searchable is False

    malta = by_repo["justicedao/ipfs_malta_laws_ir"]
    malta_hyphen = by_repo["justicedao/ipfs_malta_laws-ir"]
    assert malta.selected is True
    assert malta.corpus_id == "country:malta"
    assert malta.primary_key == "entry_cid"
    assert malta_hyphen.selected is False
    assert malta_hyphen.corpus_id == malta.corpus_id
    assert "justicedao/ipfs_malta_laws-ir" in malta.supersedes

    argentina = by_repo["justicedao/ipfs_argentina_laws_ir"]
    assert argentina.selected is True
    assert by_repo["justicedao/ipfs_argentina_laws-ir"].selected is False

    netherlands = by_repo["justicedao/ipfs_netherlands_laws_ir"]
    assert netherlands.selected is True
    assert netherlands.coverage == "snapshot"
    capped = by_repo["justicedao/wetwijzer_netherlands_legal_corpus"]
    assert capped.selected is False
    assert capped.coverage == "capped"
    assert capped.hf_repo in netherlands.supersedes

    register = by_repo["justicedao/federal-register-full-graphrag-v20260810"]
    research = by_repo["justicedao/ipfs_federal_register"]
    assert register.selected is True
    assert register.coverage == "current-bundle"
    assert research.selected is False
    assert research.coverage == "research"
    assert research.hf_repo in register.supersedes

    patent = by_repo["justicedao/patent-legal-ir-graphrag"]
    assert patent.selected is True
    assert by_repo["justicedao/patent-legal-bm25"].selected is False
    assert "justicedao/patent-legal-bm25" in patent.supersedes

    assert by_repo["justicedao/ipfs_state_laws"].corpus_id == "us:state-statutes"
    assert by_repo["justicedao/open-us-law-sparse-graphrag"].corpus_id == "us:open-us-law"
    assert by_repo["justicedao/ipfs_caselaw_access_project"].selected is True
    assert by_repo["justicedao/dedup_ipfs_caselaw_access_project"].selected is False
    embeddings = by_repo["justicedao/Caselaw_Access_Project_embeddings"]
    assert embeddings.text_corpus is False
    assert embeddings.selected is True
    assert embeddings.corpus_id != "us:caselaw"

    court_rules = by_repo["justicedao/ipfs_court_rules"]
    assert court_rules.selected is False
    assert court_rules.layout_profile == "unverified"

    selected = selected_releases(releases)
    assert malta in selected
    assert malta_hyphen not in selected
    assert research not in selected
    assert {item.corpus_id for item in selected if item.corpus_id == "us:federal-register"} == {
        "us:federal-register"
    }
    assert sum(item.corpus_id == "us:federal-register" for item in selected) == 1
    assert sum(item.corpus_id == "country:malta" for item in selected) == 1
