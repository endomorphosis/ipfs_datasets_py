"""ISO country-code mapping onto legal-scraper regions.

Regions are mutually exclusive for national gazette corpora:

- americas
- europe
- mena
- africa
- asia_pacific

US state and municipal scrapers are separate classes, not country regions.
"""

from __future__ import annotations

from typing import Mapping

REGION_IDS = (
    "americas",
    "europe",
    "mena",
    "africa",
    "asia_pacific",
)

REGION_DISPLAY_NAMES = {
    "americas": "Americas",
    "europe": "Europe",
    "mena": "Middle East and North Africa",
    "africa": "Africa",
    "asia_pacific": "Asia-Pacific",
}

# Middle East and North Africa, including Turkey.
MENA_CODES = frozenset(
    {
        "AE",
        "BH",
        "DZ",
        "EG",
        "IQ",
        "IR",
        "IL",
        "JO",
        "KW",
        "LB",
        "LY",
        "MA",
        "MR",
        "OM",
        "PS",
        "QA",
        "SA",
        "SD",
        "SY",
        "TN",
        "TR",
        "YE",
        "EH",
    }
)

EUROPE_CODES = frozenset(
    {
        "AL",
        "AD",
        "AM",
        "AT",
        "AZ",
        "BA",
        "BE",
        "BG",
        "BY",
        "CH",
        "CY",
        "CZ",
        "DE",
        "DK",
        "EE",
        "ES",
        "EU",
        "FI",
        "FR",
        "GB",
        "GE",
        "GR",
        "HR",
        "HU",
        "IE",
        "IS",
        "IT",
        "LI",
        "LT",
        "LU",
        "LV",
        "MC",
        "MD",
        "ME",
        "MK",
        "MT",
        "NL",
        "NO",
        "PL",
        "PT",
        "RO",
        "RS",
        "RU",
        "SE",
        "SI",
        "SK",
        "SM",
        "UA",
        "VA",
        "XK",
    }
)

AMERICAS_CODES = frozenset(
    {
        "AG",
        "AI",
        "AR",
        "AW",
        "BB",
        "BM",
        "BO",
        "BR",
        "BS",
        "BZ",
        "CA",
        "CL",
        "CO",
        "CR",
        "CU",
        "CW",
        "DM",
        "DO",
        "EC",
        "GD",
        "GT",
        "GY",
        "HN",
        "HT",
        "JM",
        "KN",
        "KY",
        "LC",
        "MX",
        "MS",
        "NI",
        "PA",
        "PE",
        "PR",
        "PY",
        "SR",
        "SV",
        "SX",
        "TC",
        "TT",
        "US",
        "UY",
        "VC",
        "VE",
        "VG",
    }
)

AFRICA_CODES = frozenset(
    {
        "AO",
        "BF",
        "BI",
        "BJ",
        "BW",
        "CD",
        "CF",
        "CG",
        "CI",
        "CM",
        "CV",
        "DJ",
        "ER",
        "ET",
        "GA",
        "GH",
        "GM",
        "GN",
        "GQ",
        "GW",
        "KE",
        "KM",
        "LR",
        "LS",
        "MG",
        "ML",
        "MU",
        "MW",
        "MZ",
        "NA",
        "NE",
        "NG",
        "RW",
        "SC",
        "SL",
        "SN",
        "SO",
        "SS",
        "ST",
        "SZ",
        "TD",
        "TG",
        "TZ",
        "UG",
        "ZA",
        "ZM",
        "ZW",
    }
)

ASIA_PACIFIC_CODES = frozenset(
    {
        "AF",
        "AU",
        "BD",
        "BN",
        "BT",
        "CK",
        "CN",
        "FJ",
        "FM",
        "HK",
        "ID",
        "IN",
        "JP",
        "KG",
        "KH",
        "KI",
        "KR",
        "KZ",
        "LA",
        "LK",
        "MH",
        "MM",
        "MN",
        "MV",
        "MY",
        "NP",
        "NR",
        "NU",
        "NZ",
        "PG",
        "PH",
        "PK",
        "PW",
        "SB",
        "SG",
        "TH",
        "TJ",
        "TL",
        "TM",
        "TO",
        "TV",
        "TW",
        "UZ",
        "VN",
        "VU",
        "WS",
    }
)

_REGION_CODE_SETS: Mapping[str, frozenset[str]] = {
    "americas": AMERICAS_CODES,
    "europe": EUROPE_CODES,
    "mena": MENA_CODES,
    "africa": AFRICA_CODES,
    "asia_pacific": ASIA_PACIFIC_CODES,
}


def _build_country_to_region() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for region_id, codes in _REGION_CODE_SETS.items():
        for code in codes:
            if code in mapping:
                raise ValueError(f"Country {code} assigned to both {mapping[code]} and {region_id}")
            mapping[code] = region_id
    return mapping


COUNTRY_TO_REGION = _build_country_to_region()


def normalize_region_id(value: str) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "america": "americas",
        "latin_america": "americas",
        "north_america": "americas",
        "south_america": "americas",
        "caribbean": "americas",
        "eu": "europe",
        "european_union": "europe",
        "middle_east": "mena",
        "middle_east_and_north_africa": "mena",
        "north_africa": "mena",
        "sub_saharan_africa": "africa",
        "asia": "asia_pacific",
        "asia_pac": "asia_pacific",
        "asiapacific": "asia_pacific",
        "oceania": "asia_pacific",
        "pacific": "asia_pacific",
        "ap": "asia_pacific",
    }
    return aliases.get(text, text)


def region_for_country(country_code: str) -> str:
    code = str(country_code or "").strip().upper()
    if not code:
        raise KeyError("Unknown legal scraper region for country code: ")
    if code not in COUNTRY_TO_REGION:
        raise KeyError(f"Unknown legal scraper region for country code: {country_code}")
    return COUNTRY_TO_REGION[code]


def countries_for_region(region_id: str) -> frozenset[str]:
    normalized = normalize_region_id(region_id)
    if normalized not in _REGION_CODE_SETS:
        raise KeyError(f"Unknown legal scraper region: {region_id}")
    return _REGION_CODE_SETS[normalized]


def known_region_ids() -> tuple[str, ...]:
    return REGION_IDS


__all__ = [
    "AFRICA_CODES",
    "AMERICAS_CODES",
    "ASIA_PACIFIC_CODES",
    "COUNTRY_TO_REGION",
    "EUROPE_CODES",
    "MENA_CODES",
    "REGION_DISPLAY_NAMES",
    "REGION_IDS",
    "countries_for_region",
    "known_region_ids",
    "normalize_region_id",
    "region_for_country",
]
