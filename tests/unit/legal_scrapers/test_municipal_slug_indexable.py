"""Municipal hubs stay indexable when the national slug is excluded."""

from __future__ import annotations

from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.catalog import (
    EXCLUDED_SLUGS,
    get_country,
    target_repo,
)


def test_municipal_slugs_are_not_stripped_before_the_exclusion_check(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("COUNTRY_LAWS_IR_ROOT", str(tmp_path))
    assert "belgium" in EXCLUDED_SLUGS
    assert "belgium_municipal" not in EXCLUDED_SLUGS
    for slug in (
        "belgium_municipal",
        "portugal_municipal",
        "lithuania_municipal",
        "ghana_municipal",
    ):
        row = get_country(f"endomorphosis/ipfs_{slug}_laws")
        assert row["slug"] == slug
        assert row["indexable"] is True
    assert get_country("endomorphosis/ipfs_belgium_laws")["indexable"] is False
    assert target_repo("austria_municipal") == "justicedao/ipfs_austria_municipal_laws_ir"
