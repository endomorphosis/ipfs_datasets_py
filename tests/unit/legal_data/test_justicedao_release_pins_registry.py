"""Pin-gated layouts stay unselected until the local pin file says they are readable."""

from __future__ import annotations

from ipfs_datasets_py.processors.legal_data.justicedao_release_pins import (
    pin_readable,
    pin_revision,
)
from ipfs_datasets_py.processors.legal_data.justicedao_release_registry import (
    build_release_registry,
    selected_releases,
)

_AMERICAN_MUNICIPAL_REVISION = "df0c0c405bf59cb948d1269dea29767a4712fb81"


def test_world_pins_stay_unreadable() -> None:
    assert pin_readable("world_national_law") is False
    assert pin_readable("world_municipal_law") is False
    assert pin_readable("justicedao/ipfs_france_laws_norm") is False
    assert pin_revision("world_national_law") is None


def test_american_municipal_norm_pin_is_readable() -> None:
    assert pin_readable("american_municipal_law_norm") is True
    assert pin_revision("american_municipal_law_norm") == _AMERICAN_MUNICIPAL_REVISION
    assert pin_revision("justicedao/american_municipal_law_norm") == _AMERICAN_MUNICIPAL_REVISION
    releases = build_release_registry(
        [
            "justicedao/american_municipal_law_norm",
            "justicedao/american_municipal_law",
            "justicedao/world_national_law",
            "justicedao/world_municipal_law",
        ]
    )
    by_repo = {item.hf_repo: item for item in releases}
    norm = by_repo["justicedao/american_municipal_law_norm"]
    assert norm.selected is True
    assert norm.searchable is True
    assert by_repo["justicedao/american_municipal_law"].selected is False
    assert by_repo["justicedao/world_national_law"].selected is False
    assert by_repo["justicedao/world_municipal_law"].selected is False


def test_april_municipal_and_world_repos_stay_unselected(monkeypatch) -> None:
    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_data.justicedao_release_registry.pin_readable",
        lambda _repo: False,
    )
    releases = build_release_registry(
        [
            "justicedao/american_municipal_law",
            "justicedao/american_municipal_law_norm",
            "justicedao/world_national_law",
            "justicedao/world_municipal_law",
            "justicedao/world_law_scrapers",
            "justicedao/ipfs_spain_municipal_laws_ir",
            "justicedao/ipfs_france_laws_ir",
            "justicedao/ipfs_france_laws_norm",
            "justicedao/ipfs_state_laws_normalized_graphrag",
            "justicedao/ipfs_american_municipal_law_normalized_graphrag",
        ]
    )
    by_repo = {item.hf_repo: item for item in releases}
    april = by_repo["justicedao/american_municipal_law"]
    assert april.selected is False
    assert april.searchable is False
    assert april.layout_profile == "municipal-gnis"
    assert april.corpus_id == "us:municipal"

    norm = by_repo["justicedao/american_municipal_law_norm"]
    assert norm.layout_profile == "legal-record/v1"
    assert norm.corpus_id == "us:municipal-norm"
    assert norm.selected is False

    world = by_repo["justicedao/world_national_law"]
    assert world.layout_profile == "world-law/v1.1.0"
    assert world.corpus_id == "world:national"
    assert world.selected is False

    municipal = by_repo["justicedao/world_municipal_law"]
    assert municipal.corpus_id == "world:municipal"
    assert municipal.selected is False

    scrapers = by_repo["justicedao/world_law_scrapers"]
    assert scrapers.layout_profile == "excluded"
    assert scrapers.selected is False

    spain = by_repo["justicedao/ipfs_spain_municipal_laws_ir"]
    assert spain.instrument_kind == "ordinance"
    assert spain.selected is True
    assert spain.corpus_id == "country:spain_municipal"

    france_ir = by_repo["justicedao/ipfs_france_laws_ir"]
    france_norm = by_repo["justicedao/ipfs_france_laws_norm"]
    assert france_ir.corpus_id == france_norm.corpus_id == "country:france"
    assert france_ir.selected is True
    assert france_ir.instrument_kind == "statute"
    assert france_norm.layout_profile == "legal-record/v1"
    assert france_norm.selected is False

    hold = by_repo["justicedao/ipfs_state_laws_normalized_graphrag"]
    assert hold.layout_profile == "unclassified"
    assert hold.corpus_id == "us:state-statutes-normalized"
    assert hold.selected is False
    municipal_hold = by_repo["justicedao/ipfs_american_municipal_law_normalized_graphrag"]
    assert municipal_hold.selected is False
    assert municipal_hold.corpus_id == "us:municipal-normalized"

    selected = {item.hf_repo for item in selected_releases(releases)}
    assert "justicedao/american_municipal_law" not in selected
    assert "justicedao/world_national_law" not in selected
    assert "justicedao/ipfs_france_laws_ir" in selected
    assert "justicedao/ipfs_france_laws_norm" not in selected


def test_readable_norm_pin_selects_only_that_repo(monkeypatch) -> None:
    def readable(repo: str) -> bool:
        name = repo.split("/", 1)[-1]
        return name == "ipfs_france_laws_norm"

    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_data.justicedao_release_registry.pin_readable",
        readable,
    )
    releases = build_release_registry(
        [
            "justicedao/ipfs_france_laws_ir",
            "justicedao/ipfs_france_laws_norm",
            "justicedao/world_national_law",
        ]
    )
    by_repo = {item.hf_repo: item for item in releases}
    assert by_repo["justicedao/ipfs_france_laws_ir"].selected is True
    assert by_repo["justicedao/ipfs_france_laws_norm"].selected is True
    assert by_repo["justicedao/ipfs_france_laws_norm"].searchable is True
    assert by_repo["justicedao/world_national_law"].selected is False
