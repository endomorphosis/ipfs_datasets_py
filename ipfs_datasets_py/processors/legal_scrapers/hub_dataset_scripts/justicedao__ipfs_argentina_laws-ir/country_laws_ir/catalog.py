"""Catalog of endomorphosis/ipfs_*_laws corpora.

Belgium, Portugal, and Lithuania are incomplete Wayback harvests and are
excluded from indexing. american_municipal_law is out of scope.
"""

from __future__ import annotations

from typing import Any

EXCLUDED_SLUGS = {"belgium", "portugal", "lithuania"}
EXCLUDED_REPOS = {f"endomorphosis/ipfs_{s}_laws" for s in EXCLUDED_SLUGS}

# Hub listing as of 2026-09-03. Refresh via `python -m country_laws_ir catalog --refresh`.
COUNTRIES: list[dict[str, Any]] = [
    {"slug": "argentina", "repo": "endomorphosis/ipfs_argentina_laws", "name": "Argentina", "indexable": True},
    {"slug": "australia", "repo": "endomorphosis/ipfs_australia_laws", "name": "Australia", "indexable": True},
    {"slug": "austria", "repo": "endomorphosis/ipfs_austria_laws", "name": "Austria", "indexable": True},
    {"slug": "bangladesh", "repo": "endomorphosis/ipfs_bangladesh_laws", "name": "Bangladesh", "indexable": True},
    {"slug": "belgium", "repo": "endomorphosis/ipfs_belgium_laws", "name": "Belgium", "indexable": False,
     "skip_reason": "incomplete Wayback harvest (Justel / Moniteur belge archive shard)"},
    {"slug": "brazil", "repo": "endomorphosis/ipfs_brazil_laws", "name": "Brazil", "indexable": True},
    {"slug": "canada", "repo": "endomorphosis/ipfs_canada_laws", "name": "Canada", "indexable": True},
    {"slug": "chile", "repo": "endomorphosis/ipfs_chile_laws", "name": "Chile", "indexable": True},
    {"slug": "china", "repo": "endomorphosis/ipfs_china_laws", "name": "China", "indexable": True},
    {"slug": "colombia", "repo": "endomorphosis/ipfs_colombia_laws", "name": "Colombia", "indexable": True},
    {"slug": "croatia", "repo": "endomorphosis/ipfs_croatia_laws", "name": "Croatia", "indexable": True},
    {"slug": "czechia", "repo": "endomorphosis/ipfs_czechia_laws", "name": "Czechia", "indexable": True},
    {"slug": "denmark", "repo": "endomorphosis/ipfs_denmark_laws", "name": "Denmark", "indexable": True},
    {"slug": "egypt", "repo": "endomorphosis/ipfs_egypt_laws", "name": "Egypt", "indexable": True},
    {"slug": "estonia", "repo": "endomorphosis/ipfs_estonia_laws", "name": "Estonia", "indexable": True},
    {"slug": "eu", "repo": "endomorphosis/ipfs_eu_laws", "name": "European Union", "indexable": True},
    {"slug": "finland", "repo": "endomorphosis/ipfs_finland_laws", "name": "Finland", "indexable": True},
    {"slug": "france", "repo": "endomorphosis/ipfs_france_laws", "name": "France", "indexable": True},
    {"slug": "germany", "repo": "endomorphosis/ipfs_germany_laws", "name": "Germany", "indexable": True},
    {"slug": "greece", "repo": "endomorphosis/ipfs_greece_laws", "name": "Greece", "indexable": True},
    {"slug": "hongkong", "repo": "endomorphosis/ipfs_hongkong_laws", "name": "Hong Kong", "indexable": True},
    {"slug": "hungary", "repo": "endomorphosis/ipfs_hungary_laws", "name": "Hungary", "indexable": True},
    {"slug": "india", "repo": "endomorphosis/ipfs_india_laws", "name": "India", "indexable": True},
    {"slug": "indonesia", "repo": "endomorphosis/ipfs_indonesia_laws", "name": "Indonesia", "indexable": True},
    {"slug": "ireland", "repo": "endomorphosis/ipfs_ireland_laws", "name": "Ireland", "indexable": True},
    {"slug": "israel", "repo": "endomorphosis/ipfs_israel_laws", "name": "Israel", "indexable": True},
    {"slug": "japan", "repo": "endomorphosis/ipfs_japan_laws", "name": "Japan", "indexable": True},
    {"slug": "kenya", "repo": "endomorphosis/ipfs_kenya_laws", "name": "Kenya", "indexable": True},
    {"slug": "korea", "repo": "endomorphosis/ipfs_korea_laws", "name": "Korea (ROK)", "indexable": True},
    {"slug": "kuwait", "repo": "endomorphosis/ipfs_kuwait_laws", "name": "Kuwait", "indexable": True},
    {"slug": "latvia", "repo": "endomorphosis/ipfs_latvia_laws", "name": "Latvia", "indexable": True},
    {"slug": "lithuania", "repo": "endomorphosis/ipfs_lithuania_laws", "name": "Lithuania", "indexable": False,
     "skip_reason": "incomplete Wayback harvest (e-TAR archive shard)"},
    {"slug": "luxembourg", "repo": "endomorphosis/ipfs_luxembourg_laws", "name": "Luxembourg", "indexable": True},
    {"slug": "malaysia", "repo": "endomorphosis/ipfs_malaysia_laws", "name": "Malaysia", "indexable": True},
    {"slug": "malta", "repo": "endomorphosis/ipfs_malta_laws", "name": "Malta", "indexable": True, "pilot": True},
    {"slug": "mexico", "repo": "endomorphosis/ipfs_mexico_laws", "name": "Mexico", "indexable": True},
    {"slug": "netherlands", "repo": "endomorphosis/ipfs_netherlands_laws", "name": "Netherlands", "indexable": True},
    {"slug": "newzealand", "repo": "endomorphosis/ipfs_newzealand_laws", "name": "New Zealand", "indexable": True},
    {"slug": "nigeria", "repo": "endomorphosis/ipfs_nigeria_laws", "name": "Nigeria", "indexable": True},
    {"slug": "norway", "repo": "endomorphosis/ipfs_norway_laws", "name": "Norway", "indexable": True},
    {"slug": "pakistan", "repo": "endomorphosis/ipfs_pakistan_laws", "name": "Pakistan", "indexable": True},
    {"slug": "philippines", "repo": "endomorphosis/ipfs_philippines_laws", "name": "Philippines", "indexable": True},
    {"slug": "poland", "repo": "endomorphosis/ipfs_poland_laws", "name": "Poland", "indexable": True},
    {"slug": "portugal", "repo": "endomorphosis/ipfs_portugal_laws", "name": "Portugal", "indexable": False,
     "skip_reason": "incomplete Wayback harvest (Diário da República archive shard)"},
    {"slug": "qatar", "repo": "endomorphosis/ipfs_qatar_laws", "name": "Qatar", "indexable": True},
    {"slug": "russia", "repo": "endomorphosis/ipfs_russia_laws", "name": "Russia", "indexable": True},
    {"slug": "saudiarabia", "repo": "endomorphosis/ipfs_saudiarabia_laws", "name": "Saudi Arabia", "indexable": True},
    {"slug": "singapore", "repo": "endomorphosis/ipfs_singapore_laws", "name": "Singapore", "indexable": True},
    {"slug": "slovakia", "repo": "endomorphosis/ipfs_slovakia_laws", "name": "Slovakia", "indexable": True},
    {"slug": "southafrica", "repo": "endomorphosis/ipfs_southafrica_laws", "name": "South Africa", "indexable": True},
    {"slug": "spain", "repo": "endomorphosis/ipfs_spain_laws", "name": "Spain", "indexable": True},
    {"slug": "sweden", "repo": "endomorphosis/ipfs_sweden_laws", "name": "Sweden", "indexable": True},
    {"slug": "switzerland", "repo": "endomorphosis/ipfs_switzerland_laws", "name": "Switzerland", "indexable": True},
    {"slug": "taiwan", "repo": "endomorphosis/ipfs_taiwan_laws", "name": "Taiwan", "indexable": True},
    {"slug": "thailand", "repo": "endomorphosis/ipfs_thailand_laws", "name": "Thailand", "indexable": True},
    {"slug": "turkey", "repo": "endomorphosis/ipfs_turkey_laws", "name": "Turkey", "indexable": True},
    {"slug": "uae", "repo": "endomorphosis/ipfs_uae_laws", "name": "United Arab Emirates", "indexable": True},
    {"slug": "uk", "repo": "endomorphosis/ipfs_uk_laws", "name": "United Kingdom", "indexable": True},
    {"slug": "ukraine", "repo": "endomorphosis/ipfs_ukraine_laws", "name": "Ukraine", "indexable": True},
    {"slug": "vietnam", "repo": "endomorphosis/ipfs_vietnam_laws", "name": "Vietnam", "indexable": True},
]


def get_country(source: str) -> dict[str, Any]:
    source = source.strip()
    slug = source
    if "/" in source:
        slug = source.rsplit("/", 1)[-1]
    slug = slug.removeprefix("ipfs_").removesuffix("_laws").removesuffix("-ir")
    for row in COUNTRIES:
        if row["slug"] == slug or row["repo"] == source or row["repo"].endswith("/" + source):
            return dict(row)
    if source.startswith("endomorphosis/ipfs_") and source.endswith("_laws"):
        inferred = source.split("ipfs_", 1)[1].removesuffix("_laws")
        return {
            "slug": inferred,
            "repo": source,
            "name": inferred.replace("_", " ").title(),
            "indexable": inferred not in EXCLUDED_SLUGS,
            "skip_reason": "incomplete Wayback harvest" if inferred in EXCLUDED_SLUGS else None,
        }
    raise KeyError(f"Unknown country-law source: {source}")


def indexable_countries() -> list[dict[str, Any]]:
    return [c for c in COUNTRIES if c.get("indexable")]


def target_repo(slug: str) -> str:
    return f"justicedao/ipfs_{slug}_laws-ir"


def refresh_from_hub() -> list[dict[str, Any]]:
    """Hub listing using the connector token (never printed)."""
    from huggingface_hub import HfApi

    from .auth import configure_hf, load_token

    configure_hf()
    api = HfApi(token=load_token())
    found: list[dict[str, Any]] = []
    for ds in api.list_datasets(author="endomorphosis"):
        ds_id = ds.id
        if not ds_id.startswith("endomorphosis/ipfs_") or not ds_id.endswith("_laws"):
            continue
        slug = ds_id.split("ipfs_", 1)[1].removesuffix("_laws")
        found.append({
            "slug": slug,
            "repo": ds_id,
            "name": slug.replace("_", " ").title(),
            "indexable": slug not in EXCLUDED_SLUGS,
            "skip_reason": (
                "incomplete Wayback harvest" if slug in EXCLUDED_SLUGS else None
            ),
        })
    found.sort(key=lambda r: r["slug"])
    return found
