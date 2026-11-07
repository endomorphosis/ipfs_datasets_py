"""Hub code pins and promoted collectors, read on 2026-11-07.

Near-reformat collector updates (collect_is, collect_sn) were copied into
national_collectors and were not given a new query route. Substantive
collector updates were copied the same way and also keep their existing
routes. Belgium, Portugal, Lithuania, and Ghana stay off the national
query catalog.
"""

from __future__ import annotations

import sys

from ipfs_datasets_py.processors.legal_scrapers.hub_integrated import (
    JUSTICEDAO_WORLD_LAW_SCRAPERS_SHA,
    LEGAL_SCRAPERS_SHA,
    WORLD_LAW_PIPELINE_SHA,
)
from ipfs_datasets_py.processors.legal_scrapers.national_collectors import (
    get_national_collector,
)


def test_hub_pins_match_the_tips_read_on_20261107() -> None:
    assert LEGAL_SCRAPERS_SHA == "752ba7c010802563d6a0d277592d4f92a812c83e"
    assert WORLD_LAW_PIPELINE_SHA == "26004b9f79637373bd8dc0dffb7dbc36aa09c595"
    assert JUSTICEDAO_WORLD_LAW_SCRAPERS_SHA == "6b0cef28733436be7a0ea554ab30dcd81834a64e"


def test_promoted_collectors_resolve_without_replacing_statute_routes() -> None:
    assert get_national_collector("fr").module == "collect_legi"
    assert get_national_collector("de").module == "collect_gii"
    assert get_national_collector("es").module == "collect_boe"
    assert get_national_collector("it").module == "collect_it"
    try:
        get_national_collector("us")
    except KeyError:
        pass
    else:
        raise AssertionError("us must stay unresolved; US routes are in-tree")
    france = get_national_collector("collect_fr_dila")
    germany = get_national_collector("collect_de_rii")
    assert france.filename == "collect_fr_dila.py"
    assert germany.filename == "collect_de_rii.py"
    assert france.iso == "fr"
    assert germany.iso == "de"
    for key, filename in (
        ("collect_additions", "collect_additions.py"),
        ("collect_es_seue", "collect_es_seue.py"),
        ("collect_it_dait", "collect_it_dait.py"),
        ("collect_lu_sparql", "collect_lu_sparql.py"),
        ("collect_ua_zip", "collect_ua_zip.py"),
        ("collect_us_local", "collect_us_local.py"),
        ("collect_jo_gazette", "collect_jo_gazette.py"),
        ("collect_hu_njt", "collect_hu_njt.py"),
        ("collect_dk_nstar", "collect_dk_nstar.py"),
    ):
        spec = get_national_collector(key)
        assert spec.filename == filename
        assert spec.module == key


def test_importing_hub_integrated_does_not_import_collectors() -> None:
    import ipfs_datasets_py.processors.legal_scrapers.hub_integrated as hub

    assert hub.LEGAL_SCRAPERS_SHA == LEGAL_SCRAPERS_SHA
    imported = set(sys.modules)
    assert not any(name.endswith("collect_de_rii") or name.endswith("collect_fr_dila") for name in imported)
    assert not any("caselaw.de_rii" in name or "caselaw.fr_dila" in name for name in imported)


def test_promoted_modules_do_not_use_workspace_roots() -> None:
    import importlib

    from ipfs_datasets_py.processors.legal_scrapers.national_collectors.collect_de_rii import _CASELAW
    from ipfs_datasets_py.processors.legal_scrapers.national_collectors.collect_fr_dila import guard

    assert "/workspace" not in str(_CASELAW)
    assert guard.__defaults__[2] is None
    for key in (
        "collect_additions",
        "collect_es_seue",
        "collect_it_dait",
        "collect_lu_sparql",
        "collect_ua_zip",
        "collect_us_local",
        "collect_jo_gazette",
        "collect_hu_njt",
        "collect_dk_nstar",
    ):
        module = importlib.import_module(
            "ipfs_datasets_py.processors.legal_scrapers.national_collectors." + key
        )
        assert module.vendored_path().is_file()
