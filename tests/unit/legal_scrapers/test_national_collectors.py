"""Hub-vendored national collectors are importable from legal_scrapers."""

from __future__ import annotations

from ipfs_datasets_py.processors.legal_scrapers.national_collectors import (
    COLLECTORS_DIR,
    collector_for_hf_dataset,
    get_national_collector,
    hf_dataset_coverage,
    list_national_collectors,
    load_collector_module,
)


def test_vendored_collectors_cover_official_gazettes() -> None:
    collectors = list_national_collectors()
    assert len(collectors) >= 100
    assert (COLLECTORS_DIR / "collect_at.py").is_file()
    assert (COLLECTORS_DIR / "collect_gii.py").is_file()
    austria = get_national_collector("at")
    assert austria.filename == "collect_at.py"
    assert austria.iso == "at"


def test_hf_datasets_bind_collectors_and_ir_packager() -> None:
    germany = collector_for_hf_dataset("justicedao/ipfs_germany_laws_ir")
    assert "collect_gii" in germany
    assert any(name.endswith("country_laws_ir") for name in germany)
    uk = collector_for_hf_dataset("endomorphosis/ipfs_uk_laws")
    assert "collect_legislation_gov_uk" in uk
    coverage = hf_dataset_coverage()
    assert coverage["bound_hf_datasets"] >= 150
    assert coverage["vendored_collectors"] >= 100


def test_load_collector_does_not_run_main() -> None:
    module = load_collector_module("at")
    assert getattr(module, "CC", None) == "at"
    assert callable(getattr(module, "discover", None))


def test_municipal_hub_scrapers_import() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.municipal_law_database_scrapers.hub import (
        AMLEGAL_PUBLISHER,
        scrape_amlegal_rows,
    )

    assert AMLEGAL_PUBLISHER
    assert callable(scrape_amlegal_rows)


def test_country_laws_ir_package_imports() -> None:
    from ipfs_datasets_py.processors.legal_scrapers import country_laws_ir

    assert country_laws_ir.SCHEMA_VERSION.startswith("country-laws-ir")
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.catalog import (
        get_country,
    )

    germany = get_country("germany")
    assert germany["repo"] == "endomorphosis/ipfs_germany_laws"
