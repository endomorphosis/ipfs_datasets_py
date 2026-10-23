"""Country coverage manifest for the world municipal-law program.

Mirrors the ``national_collectors/catalog.py`` pattern: one entry per
country with its registry, portal, lane status, and HF dataset. This is the
fleet's single source of truth for "which countries, what state" — worker
bots and the coordinator read it instead of hand-maintaining lists.

Statuses: planned → probe → pilot → gated → full → published.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional

# Each entry: key, iso, country, registry, portal, status, hf_dataset, notes.
COUNTRIES: List[Dict[str, Any]] = [
    {
        "key": "nl",
        "iso": "NL",
        "country": "Netherlands",
        "registry": "CBS gemeentecode (4-digit)",
        "portal": "CVDR (lokaleregelgeving.overheid.nl) via SRU 1.2",
        "status": "gated",
        "hf_dataset": None,
        "notes": "Pilot validated (44 regelingen, 736 rows, 5 gemeenten). "
        "Full harvest gated on KOOP servicedesk enquiry (robots Disallow: /).",
    },
    {
        "key": "pt",
        "iso": "PT",
        "country": "Portugal",
        "registry": "CAOP 2025 / DICOFRE concelho code (4-digit)",
        "portal": "Diário da República Eletrónico (diariodarepublica.pt)",
        "status": "published",
        "hf_dataset": "endomorphosis/ipfs_portugal_municipal_laws",
        "notes": "305/308 municípios, 11,081 acts, 329,910 rows. "
        "Regulamento + classified Aviso channels; 20th column 'tipo'.",
    },
    {
        "key": "es",
        "iso": "ES",
        "country": "Spain",
        "registry": "INE municipio code (5-digit)",
        "portal": "~50 provincial BOPs (BOCM/BORM/BOPB patterns mapped)",
        "status": "pilot",
        "hf_dataset": None,
        "notes": "Pilot validated (6 acts, 163 rows: Madrid, Alcalá de Henares, "
        "Murcia). Barcelona gated on Diputació enquiry; full ~800-1100 "
        "single-thread hours estimated.",
    },
    {
        "key": "pl",
        "iso": "PL",
        "country": "Poland",
        "registry": "GUS TERYT (TERC/SIMC/ULIC)",
        "portal": "16 voivodeship journals (Dziennik Urzędowy Województwa)",
        "status": "probe",
        "hf_dataset": None,
        "notes": "VM egress to both sampled journals blocked (IP-reputation); "
        "live-browser route viable (Gdańsk probe: 132 council acts/2025, "
        "~5-8 min per gmina-year). Bounded pilot next.",
    },
    {
        "key": "kr",
        "iso": "KR",
        "country": "South Korea",
        "registry": "NLIC MST ids",
        "portal": "NLIC Open API (law.go.kr, target=ordin)",
        "status": "gated",
        "hf_dataset": None,
        "notes": "Gated on Benjamin's one-time OC signup at open.law.go.kr "
        "(non-delegable). 243 ordinance-issuing governments.",
    },
    {
        "key": "br",
        "iso": "BR",
        "country": "Brazil",
        "registry": "IBGE municipality codes",
        "portal": "LeisMunicipais (surveyed)",
        "status": "planned",
        "hf_dataset": None,
        "notes": "Robots/ToS posture to confirm before bulk.",
    },
    {
        "key": "id",
        "iso": "ID",
        "country": "Indonesia",
        "registry": "BPS codes (surveyed)",
        "portal": "TBD",
        "status": "planned",
        "hf_dataset": None,
        "notes": "In rollout order after BR.",
    },
    {
        "key": "be",
        "iso": "BE",
        "country": "Belgium (Flanders)",
        "registry": "NIS/INS codes (surveyed)",
        "portal": "TBD",
        "status": "planned",
        "hf_dataset": None,
        "notes": "Flanders first per rollout plan.",
    },
    {
        "key": "za",
        "iso": "ZA",
        "country": "South Africa",
        "registry": "MDB codes (surveyed)",
        "portal": "OpenByLaws AKN ingest (surveyed)",
        "status": "planned",
        "hf_dataset": None,
        "notes": "Near-term candidate from source survey.",
    },
    {
        "key": "ca",
        "iso": "CA",
        "country": "Canada",
        "registry": "SCGC codes (surveyed)",
        "portal": "~3,700 vendor templates (surveyed)",
        "status": "planned",
        "hf_dataset": None,
        "notes": "Near-term candidate from source survey.",
    },
    {
        "key": "se",
        "iso": "SE",
        "country": "Sweden",
        "registry": "SCB kommunkod (surveyed)",
        "portal": "TBD",
        "status": "planned",
        "hf_dataset": None,
        "notes": "290 municipalities; near-term candidate.",
    },
    {
        "key": "nz",
        "iso": "NZ",
        "country": "New Zealand",
        "registry": "Stats NZ (surveyed)",
        "portal": "TBD",
        "status": "planned",
        "hf_dataset": None,
        "notes": "78 local authorities; near-term candidate.",
    },
]


def get_country(iso: str) -> Dict[str, Any]:
    """Return the manifest entry for an ISO-2 country code."""
    key = (iso or "").strip().upper()
    for entry in COUNTRIES:
        if entry["iso"] == key:
            return entry
    raise KeyError(f"no municipal-law manifest entry for {iso!r}")


def iter_countries(status: Optional[str] = None) -> Iterator[Dict[str, Any]]:
    """Iterate manifest entries, optionally filtered by status."""
    for entry in COUNTRIES:
        if status is None or entry["status"] == status:
            yield entry


def set_status(iso: str, status: str) -> Dict[str, Any]:
    """Update a country's lane status in the in-memory manifest.

    NOTE: this mutates the in-process list only. Persisting manifest changes
    (e.g. pilot → full) is the coordinator's job at campaign boundaries.
    """
    entry = get_country(iso)
    entry["status"] = status
    return entry
