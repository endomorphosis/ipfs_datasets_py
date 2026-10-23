"""Geographic and subnational legal-scraper classes."""

from .base import LegalRegion, region_from_id
from .mapping import (
    REGION_DISPLAY_NAMES,
    REGION_IDS,
    countries_for_region,
    known_region_ids,
    normalize_region_id,
    region_for_country,
)

Americas = LegalRegion(
    region_id="americas",
    display_name="Americas",
    aliases=("america", "latin_america", "caribbean"),
)
Europe = LegalRegion(
    region_id="europe",
    display_name="Europe",
    aliases=("eu", "european_union"),
)
MENA = LegalRegion(
    region_id="mena",
    display_name="Middle East and North Africa",
    aliases=("middle_east", "north_africa"),
)
Africa = LegalRegion(
    region_id="africa",
    display_name="Africa",
    aliases=("sub_saharan_africa",),
)
AsiaPacific = LegalRegion(
    region_id="asia_pacific",
    display_name="Asia-Pacific",
    aliases=("asia", "oceania", "pacific"),
)

_REGIONS = {
    "americas": Americas,
    "europe": Europe,
    "mena": MENA,
    "africa": Africa,
    "asia_pacific": AsiaPacific,
}


def get_region(key: str) -> LegalRegion:
    normalized = normalize_region_id(key)
    if normalized in _REGIONS:
        return _REGIONS[normalized]
    return region_from_id(normalized)


def list_regions() -> list[LegalRegion]:
    return [_REGIONS[region_id] for region_id in REGION_IDS]


__all__ = [
    "Africa",
    "Americas",
    "AsiaPacific",
    "Europe",
    "LegalRegion",
    "MENA",
    "REGION_DISPLAY_NAMES",
    "REGION_IDS",
    "countries_for_region",
    "get_region",
    "known_region_ids",
    "list_regions",
    "normalize_region_id",
    "region_for_country",
    "region_from_id",
]
