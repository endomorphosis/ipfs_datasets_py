"""ISO code and catalog-slug crosswalk for JusticeDAO legal query.

The default English-name rule is not used for codes in ``CODE_OVERRIDES``.
``AQ`` and ``ZZ`` are intentionally absent. ``UK`` is not an ISO code; the
slug ``uk`` is resolved before the two-letter rule and echoes ``GB``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Published slug for each code. Overrides beat the English-name rule.
CODE_OVERRIDES: dict[str, str] = {
    "GB": "uk",
    "AE": "uae",
    "CZ": "czechia",
    "KR": "korea",
    "KP": "northkorea",
    "NZ": "newzealand",
    "CD": "drc",
    "CG": "congobrazzaville",
    "CF": "car",
    "CI": "cotedivoire",
    "CV": "caboverde",
    "DO": "dominicanrepublic",
    "SV": "elsalvador",
    "PG": "papuanewguinea",
    "SM": "sanmarino",
    "TT": "trinidad",
    "MK": "northmacedonia",
    "BA": "bosnia",
    "HK": "hongkong",
    "FM": "fsm",
    "VG": "british_virgin_islands",
    "KY": "cayman",
    "AG": "antigua_barbuda",
    "KN": "saint_kitts_nevis",
    "LC": "saint_lucia",
    "VC": "saint_vincent_grenadines",
    "SB": "solomonislands",
    "ST": "saotome",
    "TL": "timorleste",
    "ZA": "southafrica",
    "SA": "saudiarabia",
    "BF": "burkinafaso",
    "CR": "costarica",
    "GQ": "equatorialguinea",
    "GW": "guineabissau",
    "MH": "marshallislands",
    "LK": "srilanka",
    "SZ": "eswatini",
    "SS": "southsudan",
    "NC": "new_caledonia",
    "PR": "puerto_rico",
    "PY": "paraguay",
    "SX": "sint_maarten",
    "TC": "turks_caicos",
    "CK": "cookislands",
    "CW": "curacao",
    "PN": "pitcairn",
    "XK": "kosovo",
    "EU": "eu",
    "PS": "palestine",
    "VA": "vatican",
    "GU": "guam",
    "BN": "brunei",
    "BS": "bahamas",
    "GM": "gambia",
    "MM": "myanmar",
    "TR": "turkey",
    "RU": "russia",
    "VN": "vietnam",
    "LA": "laos",
    "IR": "iran",
    "SY": "syria",
    "TW": "taiwan",
    "BO": "bolivia",
    "VE": "venezuela",
    "TZ": "tanzania",
    "MD": "moldova",
}

# English short names whose default slug rule matches the published repo.
_DEFAULT_NAMES: dict[str, str] = {
    "FR": "France",
    "ES": "Spain",
    "CA": "Canada",
    "BE": "Belgium",
    "ID": "Indonesia",
    "PT": "Portugal",
    "DE": "Germany",
    "NL": "Netherlands",
    "IT": "Italy",
    "JP": "Japan",
    "AU": "Australia",
    "AT": "Austria",
    "BR": "Brazil",
    "CL": "Chile",
    "CN": "China",
    "CO": "Colombia",
    "HR": "Croatia",
    "DK": "Denmark",
    "EG": "Egypt",
    "EE": "Estonia",
    "FI": "Finland",
    "GH": "Ghana",
    "GR": "Greece",
    "IS": "Iceland",
    "HU": "Hungary",
    "IN": "India",
    "IE": "Ireland",
    "IL": "Israel",
    "KE": "Kenya",
    "KW": "Kuwait",
    "LV": "Latvia",
    "LT": "Lithuania",
    "LU": "Luxembourg",
    "MY": "Malaysia",
    "MT": "Malta",
    "MA": "Morocco",
    "NG": "Nigeria",
    "NO": "Norway",
    "PK": "Pakistan",
    "PE": "Peru",
    "PL": "Poland",
    "RO": "Romania",
    "SG": "Singapore",
    "SE": "Sweden",
    "CH": "Switzerland",
    "TH": "Thailand",
    "UA": "Ukraine",
    "UY": "Uruguay",
    "AR": "Argentina",
    "BD": "Bangladesh",
}

# Municipal slug when it is not ``{national}_municipal``.
MUNICIPAL_SLUG: dict[str, str] = {
    "CZ": "czech_municipal",
    "KR": "korea_municipal",
    "NZ": "new_zealand_municipal",
    "ZA": "south_africa_municipal",
    "SA": "saudi_arabia_municipal",
    "PS": "palestine_municipal",
}

# Reviewed endomorphosis/ipfs_*_municipal_laws hubs. A ``*_municipal`` stem
# outside this set is not a catalog, including chile_municipal and
# hungary_municipal. Those names are not world-card configs.
_PUBLISHED_MUNICIPAL_SLUGS = frozenset({
    "andorra_municipal",
    "austria_municipal",
    "belgium_municipal",
    "brazil_municipal",
    "canada_municipal",
    "czech_municipal",
    "estonia_municipal",
    "ethiopia_municipal",
    "indonesia_municipal",
    "jordan_municipal",
    "kenya_municipal",
    "korea_municipal",
    "latvia_municipal",
    "malta_municipal",
    "mauritius_municipal",
    "mozambique_municipal",
    "namibia_municipal",
    "netherlands_municipal",
    "new_zealand_municipal",
    "palestine_municipal",
    "peru_municipal",
    "portugal_municipal",
    "saudi_arabia_municipal",
    "slovenia_municipal",
    "south_africa_municipal",
    "spain_municipal",
    "tanzania_municipal",
    "tunisia_municipal",
    "uganda_municipal",
    "zimbabwe_municipal",
})

_CODE = re.compile(r"^[A-Za-z]{2}(-[A-Za-z0-9]{1,3})?$")

HTML_COUNTRY_NAMES = {
    "canada": "CA",
    "belgium": "BE",
    "indonesia": "ID",
    "portugal": "PT",
    "new zealand": "NZ",
}


def default_slug(english_name: str) -> str:
    """Lowercase and delete spaces, commas, apostrophes, and hyphens.

    Diacritics stay, so ``Curaçao`` becomes ``curaçao``, not ``curacao``.
    """

    kept: list[str] = []
    for char in english_name.casefold():
        if char in " ,'-":
            continue
        kept.append(char)
    return "".join(kept)


def national_slug(code: str) -> str | None:
    folded = code.upper()
    if folded in CODE_OVERRIDES:
        return CODE_OVERRIDES[folded]
    name = _DEFAULT_NAMES.get(folded)
    if name is None:
        return None
    return default_slug(name)


def codes_in_crosswalk() -> frozenset[str]:
    return frozenset(CODE_OVERRIDES) | frozenset(_DEFAULT_NAMES)


def _slug_index() -> dict[str, tuple[str, str]]:
    """Map a catalog slug to ``(iso_code, admin_level)``."""

    index: dict[str, tuple[str, str]] = {}
    for code in codes_in_crosswalk():
        slug = national_slug(code)
        if slug is None:
            continue
        level = "supranational" if code == "EU" else "country"
        index[slug] = (code, level)
    for code, slug in MUNICIPAL_SLUG.items():
        index[slug] = (code, "municipality")
    return index


_SLUG_INDEX = _slug_index()


@dataclass(frozen=True)
class ResolvedJurisdiction:
    echo: str
    code: str
    slug: str | None
    admin_level: str
    municipal_slug: str | None = None


def resolve_jurisdiction(raw: str) -> ResolvedJurisdiction | None:
    """Resolve a code or slug. Unknown inputs, including ``AQ`` and ``ZZ``, return None."""

    token = str(raw or "").strip()
    if not token:
        return None
    lowered = token.casefold()
    if lowered == "uk":
        return ResolvedJurisdiction(echo="GB", code="GB", slug="uk", admin_level="country")
    if lowered in {"eu", "xk"} or _CODE.fullmatch(token):
        return _resolve_code(token.upper())
    return _resolve_slug(lowered)


def _resolve_code(code: str) -> ResolvedJurisdiction | None:
    if "-" in code:
        parent, _, _sub = code.partition("-")
        if national_slug(parent) is None and parent != "US":
            return None
        if parent != "US" and national_slug(parent) is None:
            return None
        if parent == "US" or national_slug(parent) is not None:
            return ResolvedJurisdiction(
                echo=code,
                code=parent,
                slug=None,
                admin_level="adm1",
            )
        return None
    if code == "US":
        return ResolvedJurisdiction(echo="US", code="US", slug=None, admin_level="country")
    slug = national_slug(code)
    if slug is None:
        return None
    level = "supranational" if code == "EU" else "country"
    municipal = MUNICIPAL_SLUG.get(code)
    return ResolvedJurisdiction(
        echo=code,
        code=code,
        slug=slug,
        admin_level=level,
        municipal_slug=municipal,
    )


def _resolve_slug(slug: str) -> ResolvedJurisdiction | None:
    folded = fold_alias(slug)
    found = _SLUG_INDEX.get(folded)
    if found is None:
        if folded in _PUBLISHED_MUNICIPAL_SLUGS and folded.endswith("_municipal"):
            stem = folded[: -len("_municipal")]
            for code in codes_in_crosswalk():
                if national_slug(code) == stem:
                    return ResolvedJurisdiction(
                        echo=code,
                        code=code,
                        slug=stem,
                        admin_level="municipality",
                        municipal_slug=folded,
                    )
        return None
    code, level = found
    national = national_slug(code)
    return ResolvedJurisdiction(
        echo=code,
        code=code,
        slug=national,
        admin_level=level,
        municipal_slug=slug if level == "municipality" else MUNICIPAL_SLUG.get(code),
    )


def fold_alias(slug: str) -> str:
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.coverage import (
        canonical_slug,
    )

    return canonical_slug(slug)


def html_country_code(value: object) -> str | None:
    """Closed map for the five HTML municipal hubs. Unknown strings return None."""

    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"[A-Za-z]{2}", text):
        code = text.upper()
        if code in codes_in_crosswalk():
            return code
        return None
    return HTML_COUNTRY_NAMES.get(text.casefold())



