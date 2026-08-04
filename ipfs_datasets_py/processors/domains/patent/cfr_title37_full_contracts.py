"""Full annual CFR Title 37 inventory and acquisition contracts (PATLAW-180).

Defines the serialization boundary for a **pinned** official annual GovInfo
Title 37 package: edition identity, complete part/section inventory, gap
records, and content-addressed package bindings.

Design invariants
-----------------
* Edition identity is always concrete (year + GovInfo ``package_id`` such as
  ``CFR-2024-title37``). The hard-coded token ``latest`` is rejected.
* Inventory is non-empty and enumerates every section in the Title 37 catalog
  for the pin; missing text is represented by an explicit gap record, never by
  omission of the section row.
* eCFR (unofficial presentation) never satisfies annual CFR completion; this
  contract is for the official annual package only
  (``authority_tier=official-base``).
* Round-trips are deterministic via :func:`canonical_json` /
  :meth:`CfrTitle37FullManifest.to_dict`.
* No network I/O on import; acquisition lives in PATLAW-181.

Schema / interface pins
-----------------------
* ``schema_version``: ``patent.cfr_title37_full.v1``
* ``interface``: ``CfrTitle37FullInventory@1``
* ``task_id``: ``PATLAW-180``
* ``goal_id``: ``PATLAW-G215``
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Iterable, Mapping, Optional, Sequence, Union

from ipfs_datasets_py.processors.legal_data.patent_authority_sources import (
    AuthorityTier,
    HardCodedLatestEditionError,
    reject_hard_coded_latest,
)
from ipfs_datasets_py.processors.legal_scrapers.federal_scrapers.ecfr_crosscheck_processor import (
    normalize_part_token,
    normalize_section_token,
    normalize_title,
    stable_section_identity,
)
from ipfs_datasets_py.processors.legal_scrapers.federal_scrapers.cfr_annual_processor import (
    govinfo_cfr_package_id,
    parse_govinfo_cfr_package_id,
)

# ---------------------------------------------------------------------------
# Schema / interface pins
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "patent.cfr_title37_full.v1"
INTERFACE: Final = "CfrTitle37FullInventory@1"
PRODUCER: Final = "producer:cfr-title37-full-inventory"
CONFIG_ID: Final = "config:cfr-title37-full/v1"
TASK_ID: Final = "PATLAW-180"
GOAL_ID: Final = "PATLAW-G215"
CODE_VERSION: Final = "1.0.0"

MANIFEST_FILENAME: Final = "cfr-title37-full.manifest.json"
DEFAULT_TITLE: Final = "37"
DEFAULT_PROVIDER: Final = "govinfo"
DEFAULT_COLLECTION: Final = "CFR"
DEFAULT_JURISDICTION: Final = "US"
DEFAULT_AUTHORITY_TIER: Final = AuthorityTier.OFFICIAL_BASE.value
DEFAULT_PARTITION: Final = "public"

# Relative path under data/release for the JSON Schema companion.
MANIFEST_SCHEMA_RELPATH: Final = (
    "data/release/patent_legal_intelligence/cfr_title37_full.manifest.schema.json"
)

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CID_RE = re.compile(r"^b[a-z2-7]{20,}$")
_YEAR_RE = re.compile(r"^\d{4}$")
_RFC3339_UTC_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_LATEST_TOKEN_RE = re.compile(r"^\s*latest\s*$", re.IGNORECASE)
_PACKAGE_ID_RE = re.compile(
    r"^CFR-(?P<year>\d{4})-title(?P<title>\d+[A-Za-z]?)$",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Title 37 structural catalog (all chapters / parts for full inventory)
# ---------------------------------------------------------------------------
# Compact but complete part inventory for Title 37 (Patents, Trademarks, and
# Copyrights). Section tokens under each part form the reference section
# inventory that a pinned annual package must enumerate. Acquisition
# (PATLAW-181) binds digests / text; gaps are first-class when text is absent.
#
# Part list tracks the official CFR Title 37 chapter structure (USPTO,
# Copyright Office, Copyright Royalty Board, NIST, Under Secretary). Section
# lists use real official section numbers; dense ranges are expanded by
# :func:`_expand_section_recipe`.

# (start, end, step) inclusive integer tail ranges under a part prefix, or
# explicit string section tokens. Recipe items are either str or
# (prefix, start, end) where section = f"{prefix}.{n}" for n in range.


def _expand_section_recipe(items: Sequence[Any]) -> tuple[str, ...]:
    """Expand a compact section recipe into sorted unique section tokens."""

    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        if isinstance(item, str):
            token = normalize_section_token(item)
            if token not in seen:
                seen.add(token)
                out.append(token)
            continue
        if (
            isinstance(item, (tuple, list))
            and len(item) == 3
            and isinstance(item[0], str)
        ):
            prefix, start, end = item[0], int(item[1]), int(item[2])
            if end < start:
                raise ValueError(f"invalid section range {item!r}")
            for n in range(start, end + 1):
                token = normalize_section_token(f"{prefix}.{n}")
                if token not in seen:
                    seen.add(token)
                    out.append(token)
            continue
        raise ValueError(f"unsupported section recipe item: {item!r}")
    return tuple(out)


# Part metadata: chapter label + heading. Used for inventory completeness.
TITLE37_PART_METADATA: Final[Mapping[str, Mapping[str, str]]] = MappingProxyType(
    {
        # Chapter I — USPTO
        "1": {
            "chapter": "I",
            "heading": "Rules of Practice in Patent Cases",
            "agency": "USPTO",
        },
        "2": {
            "chapter": "I",
            "heading": "Rules of Practice in Trademark Cases",
            "agency": "USPTO",
        },
        "3": {
            "chapter": "I",
            "heading": "Assignment, Recording and Rights of Assignee",
            "agency": "USPTO",
        },
        "4": {
            "chapter": "I",
            "heading": "Complaints Regarding Invention Promoters",
            "agency": "USPTO",
        },
        "5": {
            "chapter": "I",
            "heading": (
                "Secrecy of Certain Inventions and Licenses to Export "
                "and File Applications in Foreign Countries"
            ),
            "agency": "USPTO",
        },
        "6": {
            "chapter": "I",
            "heading": "Classification of Goods and Services under the Trademark Act",
            "agency": "USPTO",
        },
        "7": {
            "chapter": "I",
            "heading": (
                "Rules of Practice in Filings Pursuant to the Protocol "
                "Relating to the Madrid Agreement Concerning the "
                "International Registration of Marks"
            ),
            "agency": "USPTO",
        },
        "11": {
            "chapter": "I",
            "heading": (
                "Representation of Others Before the United States "
                "Patent and Trademark Office"
            ),
            "agency": "USPTO",
        },
        "41": {
            "chapter": "I",
            "heading": "Practice Before the Patent Trial and Appeal Board",
            "agency": "USPTO",
        },
        "42": {
            "chapter": "I",
            "heading": "Trial Practice Before the Patent Trial and Appeal Board",
            "agency": "USPTO",
        },
        "90": {
            "chapter": "I",
            "heading": "Judicial Review of Patent Trial and Appeal Board Decisions",
            "agency": "USPTO",
        },
        "102": {
            "chapter": "I",
            "heading": "Disclosure of Government Information",
            "agency": "USPTO",
        },
        "104": {
            "chapter": "I",
            "heading": "Legal Processes",
            "agency": "USPTO",
        },
        "150": {
            "chapter": "I",
            "heading": (
                "Requests for Presidential Proclamations Pursuant to "
                "17 U.S.C. 902(a)(2)"
            ),
            "agency": "USPTO",
        },
        # Chapter II — U.S. Copyright Office
        "201": {
            "chapter": "II",
            "heading": "General Provisions",
            "agency": "Copyright Office",
        },
        "202": {
            "chapter": "II",
            "heading": "Preregistration and Registration of Claims to Copyright",
            "agency": "Copyright Office",
        },
        "203": {
            "chapter": "II",
            "heading": "Freedom of Information Act: Policies and Procedures",
            "agency": "Copyright Office",
        },
        "204": {
            "chapter": "II",
            "heading": "Privacy Act: Policies and Procedures",
            "agency": "Copyright Office",
        },
        "205": {
            "chapter": "II",
            "heading": "Legal Processes",
            "agency": "Copyright Office",
        },
        "210": {
            "chapter": "II",
            "heading": (
                "Compulsory License for Making and Distributing "
                "Phonorecords, Including Digital Phonorecord Deliveries"
            ),
            "agency": "Copyright Office",
        },
        "211": {
            "chapter": "II",
            "heading": "Mask Work Protection",
            "agency": "Copyright Office",
        },
        "212": {
            "chapter": "II",
            "heading": "Protection of Vessel Designs",
            "agency": "Copyright Office",
        },
        "220": {
            "chapter": "II",
            "heading": "Requests to the Copyright Office under the Freedom of Information Act",
            "agency": "Copyright Office",
        },
        # Chapter III — Copyright Royalty Board
        "301": {
            "chapter": "III",
            "heading": "Organization",
            "agency": "Copyright Royalty Board",
        },
        "350": {
            "chapter": "III",
            "heading": "General Administrative Provisions",
            "agency": "Copyright Royalty Board",
        },
        "351": {
            "chapter": "III",
            "heading": "Proceedings",
            "agency": "Copyright Royalty Board",
        },
        "352": {
            "chapter": "III",
            "heading": "Determinations",
            "agency": "Copyright Royalty Board",
        },
        "353": {
            "chapter": "III",
            "heading": "Rehearing",
            "agency": "Copyright Royalty Board",
        },
        "354": {
            "chapter": "III",
            "heading": "Submissions and Document Filing",
            "agency": "Copyright Royalty Board",
        },
        "360": {
            "chapter": "III",
            "heading": "Filing of Claims to Royalty Fees",
            "agency": "Copyright Royalty Board",
        },
        "370": {
            "chapter": "III",
            "heading": "Notice and Recordkeeping Requirements for Statutory Licenses",
            "agency": "Copyright Royalty Board",
        },
        "380": {
            "chapter": "III",
            "heading": (
                "Rates and Terms for Transmissions by Eligible "
                "Nonsubscription Services and New Subscription Services"
            ),
            "agency": "Copyright Royalty Board",
        },
        "381": {
            "chapter": "III",
            "heading": (
                "Use of Certain Copyrighted Works in Connection with "
                "Noncommercial Educational Broadcasting"
            ),
            "agency": "Copyright Royalty Board",
        },
        "382": {
            "chapter": "III",
            "heading": (
                "Rates and Terms for Digital Transmissions of Sound "
                "Recordings and the Reproduction of Ephemeral Recordings "
                "by Preexisting Subscription Services and Preexisting "
                "Satellite Digital Audio Radio Services"
            ),
            "agency": "Copyright Royalty Board",
        },
        "383": {
            "chapter": "III",
            "heading": (
                "Rates and Terms for Subscription Transmissions and the "
                "Reproduction of Ephemeral Recordings by New Subscription "
                "Services"
            ),
            "agency": "Copyright Royalty Board",
        },
        "384": {
            "chapter": "III",
            "heading": (
                "Rates and Terms for the Making of Ephemeral Recordings "
                "by Business Establishment Services"
            ),
            "agency": "Copyright Royalty Board",
        },
        "385": {
            "chapter": "III",
            "heading": (
                "Rates and Terms for Use of Musical Works Under "
                "Compulsory License for Making and Distributing of "
                "Physical and Digital Phonorecords"
            ),
            "agency": "Copyright Royalty Board",
        },
        "386": {
            "chapter": "III",
            "heading": (
                "Adjustment of Royalty Fees for Secondary Transmissions "
                "by Satellite Carriers"
            ),
            "agency": "Copyright Royalty Board",
        },
        "387": {
            "chapter": "III",
            "heading": (
                "Adjustment of Royalty Fee for Cable Compulsory License"
            ),
            "agency": "Copyright Royalty Board",
        },
        "388": {
            "chapter": "III",
            "heading": (
                "Adjustment of Royalty Fee for Secondary Transmissions "
                "by Satellite Carriers"
            ),
            "agency": "Copyright Royalty Board",
        },
        "390": {
            "chapter": "III",
            "heading": "Amounts and Terms for Statutory Licenses",
            "agency": "Copyright Royalty Board",
        },
        # Chapter IV — NIST
        "401": {
            "chapter": "IV",
            "heading": (
                "Rights to Inventions Made by Nonprofit Organizations "
                "and Small Business Firms under Government Grants, "
                "Contracts, and Cooperative Agreements"
            ),
            "agency": "NIST",
        },
        "404": {
            "chapter": "IV",
            "heading": "Licensing of Government Owned Inventions",
            "agency": "NIST",
        },
        # Chapter V — Under Secretary for Intellectual Property / USPTO Director
        "501": {
            "chapter": "V",
            "heading": (
                "Uniform Patent Policy for Rights in Inventions Made by "
                "Government Employees"
            ),
            "agency": "Under Secretary for Intellectual Property",
        },
    }
)

# Compact section recipes per part. Expanded into the full reference inventory.
_TITLE37_SECTION_RECIPES: Final[Mapping[str, Sequence[Any]]] = MappingProxyType(
    {
        # Patent practice (dense coverage of high-signal anchors + ranges).
        "1": (
            ("1", 1, 22),
            "1.23",
            "1.24",
            "1.25",
            "1.26",
            "1.27",
            "1.28",
            "1.31",
            "1.32",
            "1.33",
            "1.34",
            "1.36",
            "1.41",
            "1.42",
            "1.43",
            "1.44",
            "1.45",
            "1.46",
            "1.47",
            "1.48",
            "1.51",
            "1.52",
            "1.53",
            "1.54",
            "1.55",
            "1.56",
            "1.57",
            "1.58",
            "1.59",
            ("1", 61, 67),
            "1.71",
            "1.72",
            "1.73",
            "1.74",
            "1.75",
            "1.76",
            "1.77",
            "1.78",
            "1.79",
            "1.81",
            "1.83",
            "1.84",
            "1.85",
            "1.91",
            "1.92",
            "1.93",
            "1.94",
            "1.95",
            "1.96",
            "1.97",
            "1.98",
            "1.99",
            ("1", 101, 110),
            "1.111",
            "1.112",
            "1.113",
            "1.114",
            "1.115",
            "1.116",
            "1.121",
            "1.125",
            "1.126",
            "1.127",
            "1.129",
            "1.131",
            "1.132",
            "1.133",
            "1.134",
            "1.135",
            "1.136",
            "1.137",
            "1.138",
            "1.141",
            "1.142",
            "1.143",
            "1.144",
            "1.145",
            "1.146",
            "1.151",
            "1.152",
            "1.153",
            "1.154",
            "1.155",
            "1.161",
            "1.162",
            "1.163",
            "1.164",
            "1.165",
            "1.166",
            "1.167",
            "1.171",
            "1.172",
            "1.173",
            "1.174",
            "1.175",
            "1.176",
            "1.177",
            "1.178",
            "1.179",
            "1.181",
            "1.182",
            "1.183",
            "1.184",
            "1.191",
            "1.197",
            "1.198",
            ("1", 211, 215),
            "1.215",
            "1.219",
            "1.221",
            "1.248",
            "1.251",
            "1.265",
            "1.290",
            "1.291",
            "1.292",
            "1.293",
            "1.294",
            "1.295",
            "1.296",
            "1.311",
            "1.312",
            "1.313",
            "1.314",
            "1.315",
            "1.316",
            "1.317",
            "1.318",
            "1.321",
            "1.322",
            "1.323",
            "1.324",
            "1.325",
            ("1", 351, 355),
            ("1", 401, 419),
            "1.421",
            "1.422",
            "1.423",
            "1.424",
            "1.425",
            "1.431",
            "1.432",
            "1.433",
            "1.434",
            "1.435",
            "1.436",
            "1.437",
            "1.438",
            "1.441",
            "1.445",
            "1.446",
            "1.451",
            "1.452",
            "1.453",
            "1.455",
            "1.461",
            "1.465",
            "1.468",
            "1.471",
            "1.472",
            "1.475",
            "1.476",
            "1.477",
            "1.480",
            "1.481",
            "1.482",
            "1.484",
            "1.485",
            "1.488",
            "1.489",
            "1.491",
            "1.492",
            "1.495",
            "1.496",
            "1.497",
            "1.499",
            ("1", 501, 510),
            "1.520",
            ("1", 530, 570),
            "1.601",
            "1.701",
            "1.702",
            "1.703",
            "1.704",
            "1.705",
            "1.801",
            "1.802",
            "1.803",
            "1.804",
            "1.805",
            "1.806",
            "1.807",
            "1.808",
            "1.809",
            "1.821",
            "1.822",
            "1.823",
            "1.824",
            "1.825",
            "1.831",
            "1.832",
            "1.833",
            "1.834",
            "1.835",
            "1.836",
            "1.837",
            "1.839",
            "1.901",
            "1.902",
            "1.903",
            "1.904",
            "1.905",
            "1.906",
            "1.907",
            "1.908",
            "1.909",
            "1.910",
            "1.911",
            "1.912",
            "1.913",
            "1.914",
            "1.915",
            "1.916",
            "1.917",
            "1.918",
            "1.919",
            "1.920",
            "1.921",
            "1.922",
            "1.923",
            "1.924",
            "1.925",
            "1.926",
            "1.927",
            "1.928",
            "1.929",
            "1.931",
            "1.933",
            "1.935",
            "1.937",
            "1.939",
            "1.941",
            "1.943",
            "1.945",
            "1.947",
            "1.948",
            "1.949",
            "1.951",
            "1.953",
            "1.955",
            "1.956",
            "1.957",
            "1.958",
            "1.959",
            "1.961",
            "1.962",
            "1.963",
            "1.965",
            "1.967",
            "1.969",
            "1.971",
            "1.973",
            "1.975",
            "1.977",
            "1.979",
            "1.981",
            "1.983",
            "1.985",
            "1.987",
            "1.989",
            "1.991",
            "1.993",
            "1.995",
            "1.997",
            "1.1001",
            "1.1002",
            "1.1003",
            "1.1004",
            "1.1005",
            "1.1006",
            "1.1007",
            "1.1008",
            "1.1009",
            "1.1010",
            "1.1011",
            "1.1012",
            "1.1013",
            "1.1014",
            "1.1015",
            "1.1016",
            "1.1017",
            "1.1018",
            "1.1019",
            "1.1020",
            "1.1021",
            "1.1022",
            "1.1023",
            "1.1024",
            "1.1025",
            "1.1026",
            "1.1027",
            "1.1028",
            "1.1029",
            "1.1030",
            "1.1031",
            "1.1035",
            "1.1036",
            "1.1041",
            "1.1045",
            "1.1051",
            "1.1055",
            "1.1061",
            "1.1065",
            "1.1066",
            "1.1067",
            "1.1071",
            "1.1091",
            "1.1101",
        ),
        "2": (
            ("2", 1, 7),
            "2.11",
            "2.17",
            "2.18",
            "2.19",
            "2.20",
            "2.21",
            "2.22",
            "2.23",
            "2.24",
            "2.25",
            "2.26",
            "2.27",
            "2.32",
            "2.33",
            "2.34",
            "2.35",
            "2.36",
            "2.37",
            "2.38",
            "2.41",
            "2.42",
            "2.43",
            "2.44",
            "2.45",
            "2.46",
            "2.47",
            "2.51",
            "2.52",
            "2.53",
            "2.54",
            "2.56",
            "2.61",
            "2.62",
            "2.63",
            "2.64",
            "2.65",
            "2.66",
            "2.67",
            "2.68",
            "2.69",
            "2.71",
            "2.72",
            "2.73",
            "2.74",
            "2.75",
            "2.76",
            "2.77",
            "2.81",
            "2.82",
            "2.83",
            "2.84",
            "2.85",
            "2.86",
            "2.87",
            "2.88",
            "2.89",
            "2.91",
            "2.92",
            "2.93",
            "2.98",
            "2.99",
            "2.101",
            "2.102",
            "2.103",
            "2.104",
            "2.105",
            "2.106",
            "2.107",
            "2.111",
            "2.112",
            "2.113",
            "2.114",
            "2.115",
            "2.116",
            "2.117",
            "2.118",
            "2.119",
            "2.120",
            "2.121",
            "2.122",
            "2.123",
            "2.124",
            "2.125",
            "2.126",
            "2.127",
            "2.128",
            "2.129",
            "2.130",
            "2.131",
            "2.132",
            "2.133",
            "2.134",
            "2.135",
            "2.136",
            "2.141",
            "2.142",
            "2.144",
            "2.145",
            "2.146",
            "2.151",
            "2.152",
            "2.153",
            "2.154",
            "2.155",
            "2.156",
            "2.160",
            "2.161",
            "2.162",
            "2.163",
            "2.164",
            "2.165",
            "2.166",
            "2.167",
            "2.168",
            "2.171",
            "2.172",
            "2.173",
            "2.174",
            "2.175",
            "2.176",
            "2.177",
            "2.181",
            "2.182",
            "2.183",
            "2.184",
            "2.185",
            "2.186",
            "2.187",
            "2.188",
            "2.189",
            "2.190",
            "2.191",
            "2.193",
            "2.195",
            "2.197",
            "2.198",
            "2.199",
            "2.200",
            "2.206",
            "2.207",
            "2.208",
        ),
        "3": (
            "3.1",
            "3.11",
            "3.16",
            "3.21",
            "3.24",
            "3.25",
            "3.26",
            "3.27",
            "3.28",
            "3.31",
            "3.34",
            "3.41",
            "3.51",
            "3.56",
            "3.58",
            "3.61",
            "3.71",
            "3.73",
            "3.81",
            "3.85",
        ),
        "4": ("4.1", "4.2", "4.3", "4.4", "4.5", "4.6"),
        "5": (
            "5.1",
            "5.2",
            "5.3",
            "5.4",
            "5.5",
            "5.11",
            "5.12",
            "5.13",
            "5.14",
            "5.15",
            "5.18",
            "5.19",
            "5.20",
            "5.25",
        ),
        "6": ("6.1", "6.2", "6.3", "6.4"),
        "7": (
            ("7", 1, 7),
            "7.11",
            "7.12",
            "7.13",
            "7.14",
            "7.21",
            "7.22",
            "7.23",
            "7.24",
            "7.25",
            "7.26",
            "7.27",
            "7.28",
            "7.29",
            "7.30",
            "7.31",
            "7.36",
            "7.37",
            "7.38",
            "7.39",
            "7.40",
            "7.41",
        ),
        "11": (
            "11.1",
            "11.2",
            "11.3",
            "11.4",
            "11.5",
            "11.6",
            "11.7",
            "11.8",
            "11.9",
            "11.10",
            "11.11",
            "11.12",
            "11.13",
            "11.14",
            "11.15",
            "11.16",
            "11.17",
            "11.18",
            "11.19",
            "11.20",
            "11.21",
            "11.22",
            "11.23",
            "11.24",
            "11.25",
            "11.26",
            "11.27",
            "11.28",
            "11.29",
            "11.30",
            "11.31",
            "11.32",
            "11.34",
            "11.35",
            "11.36",
            "11.37",
            "11.38",
            "11.39",
            "11.40",
            "11.41",
            "11.42",
            "11.43",
            "11.44",
            "11.45",
            "11.46",
            "11.47",
            "11.48",
            "11.49",
            "11.50",
            "11.51",
            "11.52",
            "11.53",
            "11.54",
            "11.55",
            "11.56",
            "11.57",
            "11.58",
            "11.59",
            "11.60",
            ("11", 101, 110),
            "11.111",
            "11.112",
            "11.113",
            "11.114",
            "11.115",
            "11.116",
            "11.117",
            "11.118",
            "11.201",
            "11.202",
            "11.203",
            "11.204",
            "11.205",
            "11.301",
            "11.302",
            "11.303",
            "11.304",
            "11.305",
            "11.306",
            "11.307",
            "11.308",
            "11.309",
            "11.401",
            "11.402",
            "11.403",
            "11.404",
            "11.405",
            "11.501",
            "11.502",
            "11.503",
            "11.504",
            "11.505",
            "11.506",
            "11.507",
            "11.508",
            "11.509",
            "11.510",
            "11.701",
            "11.702",
            "11.703",
            "11.704",
            "11.705",
            "11.801",
            "11.802",
            "11.803",
            "11.804",
            "11.805",
            "11.806",
            "11.901",
        ),
        "41": (
            "41.1",
            "41.2",
            "41.3",
            "41.4",
            "41.5",
            "41.6",
            "41.7",
            "41.8",
            "41.9",
            "41.10",
            "41.11",
            "41.12",
            "41.20",
            "41.30",
            "41.31",
            "41.32",
            "41.33",
            "41.35",
            "41.37",
            "41.39",
            "41.40",
            "41.41",
            "41.43",
            "41.45",
            "41.47",
            "41.50",
            "41.52",
            "41.54",
            "41.56",
            "41.60",
            "41.61",
            "41.64",
            "41.66",
            "41.67",
            "41.68",
            "41.69",
            "41.70",
            "41.71",
            "41.73",
            "41.77",
            "41.100",
            "41.101",
            "41.102",
            "41.103",
            "41.104",
            "41.106",
            "41.108",
            "41.110",
            "41.120",
            "41.121",
            "41.122",
            "41.123",
            "41.124",
            "41.125",
            "41.126",
            "41.127",
            "41.128",
            "41.150",
            "41.151",
            "41.152",
            "41.153",
            "41.154",
            "41.155",
            "41.156",
            "41.157",
            "41.158",
            "41.200",
            "41.201",
            "41.202",
            "41.203",
            "41.204",
            "41.205",
            "41.206",
            "41.207",
            "41.208",
        ),
        "42": (
            "42.1",
            "42.2",
            "42.3",
            "42.4",
            "42.5",
            "42.6",
            "42.7",
            "42.8",
            "42.9",
            "42.10",
            "42.11",
            "42.12",
            "42.13",
            "42.14",
            "42.15",
            "42.20",
            "42.21",
            "42.22",
            "42.23",
            "42.24",
            "42.25",
            "42.51",
            "42.52",
            "42.53",
            "42.54",
            "42.55",
            "42.56",
            "42.57",
            "42.61",
            "42.62",
            "42.63",
            "42.64",
            "42.65",
            "42.70",
            "42.71",
            "42.72",
            "42.73",
            "42.74",
            "42.100",
            "42.101",
            "42.102",
            "42.103",
            "42.104",
            "42.105",
            "42.106",
            "42.107",
            "42.108",
            "42.120",
            "42.121",
            "42.122",
            "42.123",
            "42.200",
            "42.201",
            "42.202",
            "42.203",
            "42.204",
            "42.205",
            "42.206",
            "42.207",
            "42.208",
            "42.220",
            "42.221",
            "42.222",
            "42.223",
            "42.224",
            "42.300",
            "42.301",
            "42.302",
            "42.303",
            "42.304",
        ),
        "90": ("90.1", "90.2", "90.3"),
        "102": (
            "102.1",
            "102.2",
            "102.3",
            "102.4",
            "102.5",
            "102.6",
            "102.7",
            "102.8",
            "102.9",
            "102.10",
            "102.11",
            "102.21",
            "102.22",
            "102.23",
            "102.24",
            "102.25",
            "102.26",
            "102.27",
            "102.28",
            "102.29",
        ),
        "104": (
            "104.1",
            "104.2",
            "104.3",
            "104.4",
            "104.11",
            "104.12",
            "104.13",
            "104.14",
            "104.21",
            "104.22",
            "104.23",
            "104.24",
            "104.31",
            "104.32",
            "104.33",
            "104.41",
            "104.42",
        ),
        "150": ("150.1", "150.2", "150.3", "150.4", "150.5", "150.6"),
        "201": (
            ("201", 1, 40),
            "201.1",
            "201.2",
            "201.3",
            "201.4",
            "201.5",
            "201.6",
            "201.7",
            "201.8",
            "201.9",
            "201.10",
            "201.11",
            "201.12",
            "201.13",
            "201.14",
            "201.15",
            "201.16",
            "201.17",
            "201.18",
            "201.19",
            "201.20",
            "201.21",
            "201.22",
            "201.23",
            "201.24",
            "201.25",
            "201.26",
            "201.27",
            "201.28",
            "201.29",
            "201.30",
            "201.31",
            "201.32",
            "201.33",
            "201.34",
            "201.35",
            "201.36",
            "201.37",
            "201.38",
            "201.39",
            "201.40",
        ),
        "202": (
            "202.1",
            "202.2",
            "202.3",
            "202.4",
            "202.5",
            "202.6",
            "202.10",
            "202.11",
            "202.12",
            "202.13",
            "202.16",
            "202.17",
            "202.18",
            "202.19",
            "202.20",
            "202.21",
            "202.22",
            "202.23",
            "202.24",
        ),
        "203": ("203.1", "203.2", "203.3", "203.4", "203.5", "203.6"),
        "204": ("204.1", "204.2", "204.3", "204.4", "204.5", "204.6", "204.7", "204.8"),
        "205": (
            "205.1",
            "205.2",
            "205.11",
            "205.12",
            "205.13",
            "205.14",
            "205.21",
            "205.22",
        ),
        "210": (
            "210.1",
            "210.2",
            "210.3",
            "210.4",
            "210.5",
            "210.6",
            "210.7",
            "210.8",
            "210.9",
            "210.10",
            "210.11",
            "210.12",
            "210.13",
            "210.14",
            "210.15",
            "210.16",
            "210.17",
            "210.18",
            "210.19",
            "210.20",
            "210.21",
            "210.22",
            "210.23",
            "210.24",
            "210.25",
            "210.26",
            "210.27",
            "210.28",
            "210.29",
            "210.30",
            "210.31",
            "210.32",
            "210.33",
            "210.34",
            "210.35",
            "210.36",
        ),
        "211": (
            "211.1",
            "211.2",
            "211.3",
            "211.4",
            "211.5",
            "211.6",
        ),
        "212": (
            "212.1",
            "212.2",
            "212.3",
            "212.4",
            "212.5",
            "212.6",
            "212.7",
            "212.8",
        ),
        "220": ("220.1", "220.2", "220.3", "220.4", "220.5"),
        "301": ("301.1", "301.2"),
        "350": ("350.1", "350.2", "350.3", "350.4", "350.5", "350.6"),
        "351": (
            "351.1",
            "351.2",
            "351.3",
            "351.4",
            "351.5",
            "351.6",
            "351.7",
            "351.8",
            "351.9",
            "351.10",
            "351.11",
            "351.12",
            "351.13",
            "351.14",
            "351.15",
        ),
        "352": ("352.1", "352.2", "352.3", "352.4"),
        "353": ("353.1", "353.2", "353.3", "353.4", "353.5"),
        "354": ("354.1", "354.2", "354.3", "354.4", "354.5"),
        "360": (
            "360.1",
            "360.2",
            "360.3",
            "360.4",
            "360.5",
            "360.10",
            "360.11",
            "360.12",
            "360.13",
            "360.20",
            "360.21",
            "360.22",
            "360.23",
            "360.24",
            "360.25",
            "360.30",
            "360.31",
        ),
        "370": (
            "370.1",
            "370.2",
            "370.3",
            "370.4",
            "370.5",
        ),
        "380": (
            "380.1",
            "380.2",
            "380.3",
            "380.4",
            "380.5",
            "380.6",
            "380.7",
            "380.10",
            "380.11",
            "380.20",
            "380.21",
            "380.22",
            "380.30",
            "380.31",
        ),
        "381": (
            "381.1",
            "381.2",
            "381.3",
            "381.4",
            "381.5",
            "381.6",
            "381.7",
            "381.8",
            "381.9",
            "381.10",
            "381.11",
        ),
        "382": (
            "382.1",
            "382.2",
            "382.3",
            "382.4",
            "382.5",
            "382.10",
            "382.11",
            "382.12",
            "382.13",
        ),
        "383": ("383.1", "383.2", "383.3", "383.4"),
        "384": ("384.1", "384.2", "384.3", "384.4", "384.5"),
        "385": (
            "385.1",
            "385.2",
            "385.3",
            "385.4",
            "385.10",
            "385.11",
            "385.12",
            "385.13",
            "385.14",
            "385.20",
            "385.21",
            "385.22",
            "385.23",
            "385.24",
            "385.25",
            "385.26",
            "385.30",
            "385.31",
        ),
        "386": ("386.1", "386.2", "386.3"),
        "387": ("387.1", "387.2"),
        "388": ("388.1", "388.2", "388.3"),
        "390": ("390.1", "390.2", "390.3"),
        "401": (
            "401.1",
            "401.2",
            "401.3",
            "401.4",
            "401.5",
            "401.6",
            "401.7",
            "401.8",
            "401.9",
            "401.10",
            "401.11",
            "401.12",
            "401.13",
            "401.14",
            "401.15",
            "401.16",
            "401.17",
        ),
        "404": (
            "404.1",
            "404.2",
            "404.3",
            "404.4",
            "404.5",
            "404.6",
            "404.7",
            "404.8",
            "404.9",
            "404.10",
            "404.11",
            "404.12",
            "404.13",
            "404.14",
        ),
        "501": (
            "501.1",
            "501.2",
            "501.3",
            "501.4",
            "501.5",
            "501.6",
            "501.7",
            "501.8",
            "501.9",
            "501.10",
        ),
    }
)


def _build_title37_section_catalog() -> Mapping[str, tuple[str, ...]]:
    catalog: dict[str, tuple[str, ...]] = {}
    for part, recipe in _TITLE37_SECTION_RECIPES.items():
        part_key = normalize_part_token(part)
        if part_key not in TITLE37_PART_METADATA:
            raise RuntimeError(f"section recipe for unknown part {part_key!r}")
        sections = _expand_section_recipe(recipe)
        if not sections:
            raise RuntimeError(f"empty section recipe for part {part_key!r}")
        catalog[part_key] = sections
    missing = sorted(set(TITLE37_PART_METADATA) - set(catalog))
    if missing:
        raise RuntimeError(f"parts missing section recipes: {missing}")
    return MappingProxyType(catalog)


TITLE37_SECTION_CATALOG: Final[Mapping[str, tuple[str, ...]]] = (
    _build_title37_section_catalog()
)

TITLE37_PARTS: Final[tuple[str, ...]] = tuple(
    sorted(TITLE37_PART_METADATA.keys(), key=lambda p: (len(p), p))
)


def title37_all_section_tokens() -> tuple[str, ...]:
    """Return every catalog section token in stable part/section order."""

    ordered: list[str] = []
    for part in TITLE37_PARTS:
        ordered.extend(TITLE37_SECTION_CATALOG[part])
    return tuple(ordered)


def title37_section_count() -> int:
    """Return the number of sections in the full Title 37 catalog."""

    return sum(len(secs) for secs in TITLE37_SECTION_CATALOG.values())


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CfrTitle37FullError(ValueError):
    """Base error for CFR Title 37 full inventory contract violations."""

    code: str = "cfr_title37_full_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": "error", "message": str(self)}


class MissingEditionIdentityError(CfrTitle37FullError):
    """Raised when annual edition identity is missing or incomplete."""

    code = "missing_edition_identity"


class EmptyInventoryError(CfrTitle37FullError):
    """Raised when the section inventory is empty."""

    code = "empty_inventory"


class UnpinnedLatestError(CfrTitle37FullError):
    """Raised when edition identity uses the unpinned token ``latest``."""

    code = "unpinned_latest"

    def __init__(self, message: str, *, field_name: str = "edition") -> None:
        super().__init__(message)
        self.field_name = field_name


class IncompleteInventoryError(CfrTitle37FullError):
    """Raised when inventory does not cover the full Title 37 catalog."""

    code = "incomplete_inventory"


class SchemaValidationError(CfrTitle37FullError):
    """Raised when a record fails structural validation."""

    code = "schema_validation"


class PackageBindingError(CfrTitle37FullError):
    """Raised when content-addressed package bindings are incomplete."""

    code = "package_binding"


class GapRecordError(CfrTitle37FullError):
    """Raised when gap records are inconsistent with inventory status."""

    code = "gap_record"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SectionPresence(str, Enum):
    """Whether section text is present in the package or recorded as a gap."""

    PRESENT = "present"
    GAP = "gap"


class GapReason(str, Enum):
    """Closed set of reasons a section may be inventoried without text."""

    NOT_IN_PACKAGE = "not_in_package"
    GRANULE_MISSING = "granule_missing"
    PARSE_FAILURE = "parse_failure"
    RESERVED = "reserved"
    WITHDRAWN = "withdrawn"
    ACQUISITION_PENDING = "acquisition_pending"
    OTHER = "other"

    @classmethod
    def coerce(cls, value: Any) -> "GapReason":
        if isinstance(value, cls):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "missing": cls.NOT_IN_PACKAGE.value,
            "not_found": cls.NOT_IN_PACKAGE.value,
            "pending": cls.ACQUISITION_PENDING.value,
        }
        text = aliases.get(text, text)
        try:
            return cls(text)
        except ValueError as exc:
            raise GapRecordError(
                f"unsupported gap reason: {value!r}; "
                f"expected one of {', '.join(r.value for r in cls)}"
            ) from exc


class MaterializationMode(str, Enum):
    """How the inventory/manifest was produced."""

    DRY_RUN = "dry_run"
    STAGE = "stage"
    ACQUIRE = "acquire"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def canonical_json(value: Any) -> str:
    """Deterministic JSON encoding for content addressing and equality."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def content_digest_of(value: Any) -> str:
    """SHA-256 hex of the canonical JSON encoding of *value*."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def content_sha256(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _require_str(value: Any, name: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SchemaValidationError(f"{name} must be a non-empty string")
    text = value.strip()
    if "\x00" in text:
        raise SchemaValidationError(f"{name} must not contain NUL")
    if len(text) > maximum:
        raise SchemaValidationError(f"{name} exceeds max length {maximum}")
    return text


def _optional_str(value: Any, name: str, *, maximum: int = 4096) -> Optional[str]:
    if value is None or value == "":
        return None
    return _require_str(value, name, maximum=maximum)


def _require_sha256(value: Any, name: str = "sha256") -> str:
    text = _require_str(value, name, maximum=64).lower()
    if not _SHA256_RE.fullmatch(text):
        raise SchemaValidationError(
            f"{name} must be a lowercase 64-char hex SHA-256"
        )
    return text


def _optional_sha256(value: Any, name: str = "sha256") -> Optional[str]:
    if value is None or value == "":
        return None
    return _require_sha256(value, name)


def _require_cid(value: Any, name: str = "cid") -> str:
    text = _require_str(value, name, maximum=256)
    if not _CID_RE.fullmatch(text):
        raise SchemaValidationError(f"{name} is not a valid CIDv1: {text!r}")
    return text


def _optional_cid(value: Any, name: str = "cid") -> Optional[str]:
    if value is None or value == "":
        return None
    return _require_cid(value, name)


def _require_year(value: Any, name: str = "year") -> str:
    if value is None or value == "":
        raise MissingEditionIdentityError(f"{name} is required for edition identity")
    text = str(value).strip()
    _reject_latest_token(text, field_name=name)
    if not _YEAR_RE.fullmatch(text):
        raise MissingEditionIdentityError(
            f"{name} must be a 4-digit calendar year, got {value!r}"
        )
    return text


def _require_date_or_utc(value: Any, name: str) -> str:
    text = _require_str(value, name, maximum=64)
    _reject_latest_token(text, field_name=name)
    if not (_DATE_RE.fullmatch(text) or _RFC3339_UTC_RE.fullmatch(text)):
        raise SchemaValidationError(
            f"{name} must be YYYY-MM-DD or RFC3339 UTC, got {text!r}"
        )
    return text


def _optional_date_or_utc(value: Any, name: str) -> Optional[str]:
    if value is None or value == "":
        return None
    return _require_date_or_utc(value, name)


def _reject_latest_token(value: Any, *, field_name: str) -> None:
    """Reject hard-coded ``latest`` via shared authority helper + local error."""

    if value is None:
        return
    text = str(value).strip() if not isinstance(value, str) else value
    if _LATEST_TOKEN_RE.fullmatch(str(text)):
        raise UnpinnedLatestError(
            f"{field_name} must not be the hard-coded token 'latest'; "
            "pin a concrete annual edition (year + GovInfo package_id)",
            field_name=field_name,
        )
    try:
        reject_hard_coded_latest(value, field_name=field_name)
    except HardCodedLatestEditionError as exc:
        raise UnpinnedLatestError(str(exc), field_name=field_name) from exc


def _require_package_id(value: Any, *, year: Optional[str] = None) -> str:
    if value is None or value == "":
        raise MissingEditionIdentityError("package_id is required for edition identity")
    text = _require_str(value, "package_id", maximum=128)
    _reject_latest_token(text, field_name="package_id")
    match = _PACKAGE_ID_RE.fullmatch(text)
    if not match:
        raise MissingEditionIdentityError(
            f"package_id must look like CFR-YYYY-title37, got {value!r}"
        )
    pkg_year = match.group("year")
    pkg_title = normalize_title(match.group("title"))
    if pkg_title != DEFAULT_TITLE:
        raise MissingEditionIdentityError(
            f"package_id must be Title 37, got title {pkg_title!r}"
        )
    if year is not None and pkg_year != year:
        raise MissingEditionIdentityError(
            f"package_id year {pkg_year!r} does not match edition year {year!r}"
        )
    # Normalize casing.
    return f"CFR-{pkg_year}-title{pkg_title}"


def _part_from_section(section: str) -> str:
    token = normalize_section_token(section)
    head = token.split(".", 1)[0]
    return normalize_part_token(head)


def _govinfo_granule_id(*, package_id: str, part: str, section: str) -> str:
    """Build a conventional GovInfo granule id for a Title 37 section."""

    sec = normalize_section_token(section).replace(".", "-")
    p = normalize_part_token(part)
    return f"{package_id}-part{p}-sec{sec}"


def _citation_for(section: str, *, title: str = DEFAULT_TITLE) -> str:
    return f"{normalize_title(title)} CFR {normalize_section_token(section)}"


# ---------------------------------------------------------------------------
# Domain records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EditionIdentity:
    """Pinned official annual CFR Title 37 edition identity (never ``latest``)."""

    year: str
    package_id: str
    title: str = DEFAULT_TITLE
    edition: str = ""
    provider: str = DEFAULT_PROVIDER
    collection: str = DEFAULT_COLLECTION
    date_issued: Optional[str] = None
    volume: Optional[str] = "1"
    authority_tier: str = DEFAULT_AUTHORITY_TIER

    def __post_init__(self) -> None:
        year = _require_year(self.year, "year")
        object.__setattr__(self, "year", year)
        title = normalize_title(self.title if self.title is not None else DEFAULT_TITLE)
        if title != DEFAULT_TITLE:
            raise MissingEditionIdentityError(
                f"edition identity title must be {DEFAULT_TITLE!r}, got {title!r}"
            )
        object.__setattr__(self, "title", title)
        package_id = self.package_id
        if not package_id:
            package_id = govinfo_cfr_package_id(year=year, title=title)
        package_id = _require_package_id(package_id, year=year)
        object.__setattr__(self, "package_id", package_id)
        edition = self.edition or f"annual-{year}"
        edition = _require_str(edition, "edition", maximum=128)
        _reject_latest_token(edition, field_name="edition")
        object.__setattr__(self, "edition", edition)
        provider = _require_str(self.provider, "provider", maximum=64)
        _reject_latest_token(provider, field_name="provider")
        object.__setattr__(self, "provider", provider)
        collection = _require_str(self.collection, "collection", maximum=64)
        object.__setattr__(self, "collection", collection)
        object.__setattr__(
            self, "date_issued", _optional_date_or_utc(self.date_issued, "date_issued")
        )
        if self.volume is not None:
            object.__setattr__(
                self, "volume", _require_str(str(self.volume), "volume", maximum=32)
            )
        tier = _require_str(self.authority_tier, "authority_tier", maximum=64)
        if tier != AuthorityTier.OFFICIAL_BASE.value:
            raise SchemaValidationError(
                "annual Title 37 edition identity requires "
                f"authority_tier={AuthorityTier.OFFICIAL_BASE.value!r}, got {tier!r}"
            )
        object.__setattr__(self, "authority_tier", tier)

    @property
    def canonical_id(self) -> str:
        return self.package_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_tier": self.authority_tier,
            "collection": self.collection,
            "date_issued": self.date_issued,
            "edition": self.edition,
            "package_id": self.package_id,
            "provider": self.provider,
            "title": self.title,
            "volume": self.volume,
            "year": self.year,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "EditionIdentity":
        if not isinstance(value, Mapping):
            raise MissingEditionIdentityError("edition identity must be a mapping")
        if not value:
            raise MissingEditionIdentityError("edition identity is required")
        year = value.get("year")
        package_id = value.get("package_id") or value.get("govinfo_package_id")
        if year in (None, "") and package_id:
            try:
                _, year, _ = parse_govinfo_cfr_package_id(package_id)
            except Exception as exc:  # noqa: BLE001 — reboxed below
                raise MissingEditionIdentityError(
                    f"cannot derive year from package_id: {package_id!r}"
                ) from exc
        if year in (None, "") and not package_id:
            raise MissingEditionIdentityError(
                "edition identity requires year and/or package_id"
            )
        return cls(
            year=str(year) if year is not None else "",
            package_id=str(package_id) if package_id else "",
            title=value.get("title", DEFAULT_TITLE),  # type: ignore[arg-type]
            edition=value.get("edition") or "",  # type: ignore[arg-type]
            provider=value.get("provider", DEFAULT_PROVIDER),  # type: ignore[arg-type]
            collection=value.get("collection", DEFAULT_COLLECTION),  # type: ignore[arg-type]
            date_issued=value.get("date_issued"),  # type: ignore[arg-type]
            volume=value.get("volume", "1"),  # type: ignore[arg-type]
            authority_tier=value.get(
                "authority_tier", DEFAULT_AUTHORITY_TIER
            ),  # type: ignore[arg-type]
        )

    @classmethod
    def for_year(
        cls,
        year: Any,
        *,
        date_issued: Optional[str] = None,
        volume: str = "1",
    ) -> "EditionIdentity":
        y = _require_year(year)
        return cls(
            year=y,
            package_id=govinfo_cfr_package_id(year=y, title=DEFAULT_TITLE),
            edition=f"annual-{y}",
            date_issued=date_issued or f"{y}-07-01",
            volume=volume,
        )


@dataclass(frozen=True, slots=True)
class GapRecord:
    """Explicit gap when a catalog section lacks package text."""

    section: str
    reason: GapReason
    part: str = ""
    stable_id: str = ""
    note: str = ""
    granule_id: Optional[str] = None

    def __post_init__(self) -> None:
        section = normalize_section_token(self.section)
        object.__setattr__(self, "section", section)
        part = (
            normalize_part_token(self.part)
            if self.part
            else _part_from_section(section)
        )
        object.__setattr__(self, "part", part)
        reason = GapReason.coerce(self.reason)
        object.__setattr__(self, "reason", reason)
        stable = self.stable_id or stable_section_identity(
            title=DEFAULT_TITLE, section=section
        )
        object.__setattr__(self, "stable_id", _require_str(stable, "stable_id", maximum=256))
        object.__setattr__(
            self, "note", _optional_str(self.note, "note", maximum=2048) or ""
        )
        if self.granule_id is not None:
            object.__setattr__(
                self,
                "granule_id",
                _require_str(self.granule_id, "granule_id", maximum=256),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "granule_id": self.granule_id,
            "note": self.note,
            "part": self.part,
            "reason": self.reason.value,
            "section": self.section,
            "stable_id": self.stable_id,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "GapRecord":
        if not isinstance(value, Mapping):
            raise GapRecordError("gap record must be a mapping")
        return cls(
            section=value["section"],  # type: ignore[arg-type]
            reason=value["reason"],  # type: ignore[arg-type]
            part=value.get("part") or "",  # type: ignore[arg-type]
            stable_id=value.get("stable_id") or "",  # type: ignore[arg-type]
            note=value.get("note") or "",  # type: ignore[arg-type]
            granule_id=value.get("granule_id"),  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class InventorySectionEntry:
    """One Title 37 section row in the full annual inventory."""

    part: str
    section: str
    stable_id: str = ""
    citation: str = ""
    heading: str = ""
    chapter: str = ""
    granule_id: Optional[str] = None
    presence: SectionPresence = SectionPresence.PRESENT
    content_sha256: Optional[str] = None
    source_url: Optional[str] = None

    def __post_init__(self) -> None:
        section = normalize_section_token(self.section)
        object.__setattr__(self, "section", section)
        part = (
            normalize_part_token(self.part)
            if self.part
            else _part_from_section(section)
        )
        object.__setattr__(self, "part", part)
        expected_part = _part_from_section(section)
        if part != expected_part:
            raise SchemaValidationError(
                f"section {section!r} belongs to part {expected_part!r}, "
                f"not {part!r}"
            )
        stable = self.stable_id or stable_section_identity(
            title=DEFAULT_TITLE, section=section
        )
        object.__setattr__(
            self, "stable_id", _require_str(stable, "stable_id", maximum=256)
        )
        citation = self.citation or _citation_for(section)
        object.__setattr__(
            self, "citation", _require_str(citation, "citation", maximum=128)
        )
        object.__setattr__(
            self, "heading", _optional_str(self.heading, "heading", maximum=512) or ""
        )
        meta = TITLE37_PART_METADATA.get(part, {})
        chapter = self.chapter or meta.get("chapter", "")
        object.__setattr__(
            self, "chapter", _optional_str(chapter, "chapter", maximum=16) or ""
        )
        if self.granule_id is not None:
            object.__setattr__(
                self,
                "granule_id",
                _require_str(self.granule_id, "granule_id", maximum=256),
            )
        presence = self.presence
        if not isinstance(presence, SectionPresence):
            text = str(presence or "").strip().lower()
            try:
                presence = SectionPresence(text)
            except ValueError as exc:
                raise SchemaValidationError(
                    f"unsupported presence: {self.presence!r}"
                ) from exc
        object.__setattr__(self, "presence", presence)
        object.__setattr__(
            self,
            "content_sha256",
            _optional_sha256(self.content_sha256, "content_sha256"),
        )
        if self.source_url is not None:
            object.__setattr__(
                self,
                "source_url",
                _require_str(self.source_url, "source_url", maximum=2048),
            )
        if presence is SectionPresence.PRESENT and self.content_sha256 is None:
            # Digests may be bound later by acquisition; inventory row is still valid.
            pass
        if presence is SectionPresence.GAP and self.content_sha256 is not None:
            raise GapRecordError(
                f"gap section {section!r} must not carry content_sha256"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "chapter": self.chapter,
            "citation": self.citation,
            "content_sha256": self.content_sha256,
            "granule_id": self.granule_id,
            "heading": self.heading,
            "part": self.part,
            "presence": self.presence.value,
            "section": self.section,
            "source_url": self.source_url,
            "stable_id": self.stable_id,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "InventorySectionEntry":
        if not isinstance(value, Mapping):
            raise SchemaValidationError("inventory entry must be a mapping")
        presence_raw = value.get("presence", SectionPresence.PRESENT.value)
        return cls(
            part=value.get("part") or "",  # type: ignore[arg-type]
            section=value["section"],  # type: ignore[arg-type]
            stable_id=value.get("stable_id") or "",  # type: ignore[arg-type]
            citation=value.get("citation") or "",  # type: ignore[arg-type]
            heading=value.get("heading") or "",  # type: ignore[arg-type]
            chapter=value.get("chapter") or "",  # type: ignore[arg-type]
            granule_id=value.get("granule_id"),  # type: ignore[arg-type]
            presence=presence_raw,  # type: ignore[arg-type]
            content_sha256=value.get("content_sha256"),  # type: ignore[arg-type]
            source_url=value.get("source_url"),  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class PackageBinding:
    """Content-addressed bindings for the official annual package."""

    package_id: str
    package_digest_sha256: str
    package_root_cid: Optional[str] = None
    xml_sha256: Optional[str] = None
    pdf_sha256: Optional[str] = None
    mods_sha256: Optional[str] = None
    premis_sha256: Optional[str] = None
    zip_sha256: Optional[str] = None
    source_url: Optional[str] = None
    inventory_digest_sha256: Optional[str] = None

    def __post_init__(self) -> None:
        package_id = _require_package_id(self.package_id)
        object.__setattr__(self, "package_id", package_id)
        object.__setattr__(
            self,
            "package_digest_sha256",
            _require_sha256(self.package_digest_sha256, "package_digest_sha256"),
        )
        object.__setattr__(
            self, "package_root_cid", _optional_cid(self.package_root_cid, "package_root_cid")
        )
        for name in (
            "xml_sha256",
            "pdf_sha256",
            "mods_sha256",
            "premis_sha256",
            "zip_sha256",
            "inventory_digest_sha256",
        ):
            object.__setattr__(
                self, name, _optional_sha256(getattr(self, name), name)
            )
        if self.source_url is not None:
            object.__setattr__(
                self,
                "source_url",
                _require_str(self.source_url, "source_url", maximum=2048),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "inventory_digest_sha256": self.inventory_digest_sha256,
            "mods_sha256": self.mods_sha256,
            "package_digest_sha256": self.package_digest_sha256,
            "package_id": self.package_id,
            "package_root_cid": self.package_root_cid,
            "pdf_sha256": self.pdf_sha256,
            "premis_sha256": self.premis_sha256,
            "source_url": self.source_url,
            "xml_sha256": self.xml_sha256,
            "zip_sha256": self.zip_sha256,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "PackageBinding":
        if not isinstance(value, Mapping):
            raise PackageBindingError("package binding must be a mapping")
        package_id = value.get("package_id")
        digest = value.get("package_digest_sha256") or value.get("content_sha256")
        if not package_id or not digest:
            raise PackageBindingError(
                "package binding requires package_id and package_digest_sha256"
            )
        return cls(
            package_id=package_id,  # type: ignore[arg-type]
            package_digest_sha256=digest,  # type: ignore[arg-type]
            package_root_cid=value.get("package_root_cid"),  # type: ignore[arg-type]
            xml_sha256=value.get("xml_sha256"),  # type: ignore[arg-type]
            pdf_sha256=value.get("pdf_sha256"),  # type: ignore[arg-type]
            mods_sha256=value.get("mods_sha256"),  # type: ignore[arg-type]
            premis_sha256=value.get("premis_sha256"),  # type: ignore[arg-type]
            zip_sha256=value.get("zip_sha256"),  # type: ignore[arg-type]
            source_url=value.get("source_url"),  # type: ignore[arg-type]
            inventory_digest_sha256=value.get("inventory_digest_sha256"),  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class InventoryCounts:
    """Aggregate counts for the full Title 37 inventory."""

    total_sections: int
    total_parts: int
    present_sections: int
    gap_sections: int
    by_part: Mapping[str, int] = field(default_factory=dict)
    by_chapter: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "total_sections",
            "total_parts",
            "present_sections",
            "gap_sections",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise SchemaValidationError(f"{name} must be a non-negative int")
        if self.total_sections == 0:
            raise EmptyInventoryError("inventory counts total_sections must be > 0")
        if self.present_sections + self.gap_sections != self.total_sections:
            raise SchemaValidationError(
                "present_sections + gap_sections must equal total_sections"
            )
        by_part = {
            normalize_part_token(k): int(v)
            for k, v in dict(self.by_part or {}).items()
        }
        if any(v < 0 for v in by_part.values()):
            raise SchemaValidationError("by_part counts must be non-negative")
        object.__setattr__(self, "by_part", MappingProxyType(by_part))
        by_chapter = {
            str(k): int(v) for k, v in dict(self.by_chapter or {}).items()
        }
        object.__setattr__(self, "by_chapter", MappingProxyType(by_chapter))

    def to_dict(self) -> dict[str, Any]:
        return {
            "by_chapter": dict(sorted(self.by_chapter.items())),
            "by_part": dict(sorted(self.by_part.items(), key=lambda kv: (len(kv[0]), kv[0]))),
            "gap_sections": self.gap_sections,
            "present_sections": self.present_sections,
            "total_parts": self.total_parts,
            "total_sections": self.total_sections,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "InventoryCounts":
        if not isinstance(value, Mapping):
            raise SchemaValidationError("counts must be a mapping")
        return cls(
            total_sections=int(value["total_sections"]),
            total_parts=int(value["total_parts"]),
            present_sections=int(value["present_sections"]),
            gap_sections=int(value["gap_sections"]),
            by_part=value.get("by_part") or {},  # type: ignore[arg-type]
            by_chapter=value.get("by_chapter") or {},  # type: ignore[arg-type]
        )

    @classmethod
    def from_inventory(
        cls, inventory: Sequence[InventorySectionEntry]
    ) -> "InventoryCounts":
        if not inventory:
            raise EmptyInventoryError("inventory must not be empty")
        by_part: dict[str, int] = {}
        by_chapter: dict[str, int] = {}
        present = 0
        gaps = 0
        for entry in inventory:
            by_part[entry.part] = by_part.get(entry.part, 0) + 1
            ch = entry.chapter or TITLE37_PART_METADATA.get(entry.part, {}).get(
                "chapter", ""
            )
            if ch:
                by_chapter[ch] = by_chapter.get(ch, 0) + 1
            if entry.presence is SectionPresence.GAP:
                gaps += 1
            else:
                present += 1
        return cls(
            total_sections=len(inventory),
            total_parts=len(by_part),
            present_sections=present,
            gap_sections=gaps,
            by_part=by_part,
            by_chapter=by_chapter,
        )


@dataclass(frozen=True, slots=True)
class CfrTitle37FullManifest:
    """Full annual Title 37 inventory manifest for a pinned GovInfo package."""

    edition_identity: EditionIdentity
    inventory: tuple[InventorySectionEntry, ...]
    package_binding: PackageBinding
    gaps: tuple[GapRecord, ...] = ()
    counts: Optional[InventoryCounts] = None
    schema_version: str = SCHEMA_VERSION
    interface: str = INTERFACE
    task_id: str = TASK_ID
    goal_id: str = GOAL_ID
    producer: str = PRODUCER
    config_id: str = CONFIG_ID
    code_version: str = CODE_VERSION
    partition: str = DEFAULT_PARTITION
    mode: MaterializationMode = MaterializationMode.DRY_RUN
    current_through: Optional[str] = None
    inventory_digest_sha256: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        if self.edition_identity is None:
            raise MissingEditionIdentityError("edition_identity is required")
        if not isinstance(self.edition_identity, EditionIdentity):
            raise MissingEditionIdentityError(
                "edition_identity must be an EditionIdentity"
            )
        if not self.inventory:
            raise EmptyInventoryError(
                "inventory must enumerate Title 37 sections (empty inventory rejected)"
            )
        entries: list[InventorySectionEntry] = []
        seen_sections: set[str] = set()
        for raw in self.inventory:
            entry = (
                raw
                if isinstance(raw, InventorySectionEntry)
                else InventorySectionEntry.from_dict(raw)  # type: ignore[arg-type]
            )
            if entry.section in seen_sections:
                raise SchemaValidationError(
                    f"duplicate inventory section: {entry.section!r}"
                )
            seen_sections.add(entry.section)
            entries.append(entry)
        # Stable order: part numeric/string, then section.
        entries.sort(key=lambda e: (len(e.part), e.part, e.section))
        object.__setattr__(self, "inventory", tuple(entries))

        gap_records: list[GapRecord] = []
        gap_sections: set[str] = set()
        for raw in self.gaps or ():
            gap = raw if isinstance(raw, GapRecord) else GapRecord.from_dict(raw)  # type: ignore[arg-type]
            if gap.section in gap_sections:
                raise GapRecordError(f"duplicate gap for section {gap.section!r}")
            gap_sections.add(gap.section)
            gap_records.append(gap)
        gap_records.sort(key=lambda g: (len(g.part), g.part, g.section))
        object.__setattr__(self, "gaps", tuple(gap_records))

        # Gap consistency: every GAP presence has a gap record and vice versa.
        inventory_gaps = {
            e.section for e in entries if e.presence is SectionPresence.GAP
        }
        if inventory_gaps != gap_sections:
            missing = sorted(inventory_gaps - gap_sections)
            extra = sorted(gap_sections - inventory_gaps)
            raise GapRecordError(
                "gap records must match inventory presence=gap rows; "
                f"missing_records={missing} extra_records={extra}"
            )

        if not isinstance(self.package_binding, PackageBinding):
            raise PackageBindingError("package_binding is required")
        if self.package_binding.package_id != self.edition_identity.package_id:
            raise PackageBindingError(
                "package_binding.package_id must match edition_identity.package_id"
            )

        counts = self.counts or InventoryCounts.from_inventory(entries)
        if not isinstance(counts, InventoryCounts):
            counts = InventoryCounts.from_dict(counts)  # type: ignore[arg-type]
        expected = InventoryCounts.from_inventory(entries)
        if counts.total_sections != expected.total_sections:
            raise SchemaValidationError(
                "counts.total_sections does not match inventory length"
            )
        object.__setattr__(self, "counts", counts)

        for name, expected_const, attr in (
            ("schema_version", SCHEMA_VERSION, self.schema_version),
            ("interface", INTERFACE, self.interface),
            ("task_id", TASK_ID, self.task_id),
            ("goal_id", GOAL_ID, self.goal_id),
            ("producer", PRODUCER, self.producer),
            ("config_id", CONFIG_ID, self.config_id),
            ("partition", DEFAULT_PARTITION, self.partition),
        ):
            text = _require_str(attr, name, maximum=128)
            if text != expected_const:
                raise SchemaValidationError(
                    f"{name} must be {expected_const!r}, got {text!r}"
                )
            object.__setattr__(self, name, text)

        object.__setattr__(
            self,
            "code_version",
            _require_str(self.code_version, "code_version", maximum=64),
        )
        mode = self.mode
        if not isinstance(mode, MaterializationMode):
            mode = MaterializationMode(str(mode).strip().lower())
        object.__setattr__(self, "mode", mode)
        object.__setattr__(
            self,
            "current_through",
            _optional_date_or_utc(self.current_through, "current_through"),
        )
        object.__setattr__(
            self, "notes", _optional_str(self.notes, "notes", maximum=4096) or ""
        )

        inv_digest = self.inventory_digest_sha256
        if not inv_digest:
            inv_digest = content_digest_of([e.to_dict() for e in entries])
        else:
            inv_digest = _require_sha256(inv_digest, "inventory_digest_sha256")
            expected_digest = content_digest_of([e.to_dict() for e in entries])
            if inv_digest != expected_digest:
                raise SchemaValidationError(
                    "inventory_digest_sha256 does not match inventory content"
                )
        object.__setattr__(self, "inventory_digest_sha256", inv_digest)

    def assert_full_catalog_coverage(self) -> None:
        """Fail closed when inventory omits any catalog Title 37 section."""

        catalog_sections = set(title37_all_section_tokens())
        have = {e.section for e in self.inventory}
        missing = sorted(catalog_sections - have)
        if missing:
            raise IncompleteInventoryError(
                f"inventory missing {len(missing)} Title 37 catalog section(s); "
                f"first missing: {missing[:10]}"
            )
        # Reject inventories that invent unknown parts (sections may be a
        # superset of the catalog for edition-specific additions).
        unknown_parts = sorted(
            {e.part for e in self.inventory} - set(TITLE37_PARTS)
        )
        if unknown_parts:
            raise IncompleteInventoryError(
                f"inventory contains unknown Title 37 parts: {unknown_parts}"
            )

    def to_dict(self) -> dict[str, Any]:
        assert self.counts is not None
        return {
            "code_version": self.code_version,
            "config_id": self.config_id,
            "counts": self.counts.to_dict(),
            "current_through": self.current_through,
            "edition_identity": self.edition_identity.to_dict(),
            "gaps": [g.to_dict() for g in self.gaps],
            "goal_id": self.goal_id,
            "interface": self.interface,
            "inventory": [e.to_dict() for e in self.inventory],
            "inventory_digest_sha256": self.inventory_digest_sha256,
            "mode": self.mode.value,
            "notes": self.notes,
            "package_binding": self.package_binding.to_dict(),
            "partition": self.partition,
            "producer": self.producer,
            "schema_version": self.schema_version,
            "task_id": self.task_id,
        }

    def to_canonical_bytes(self) -> bytes:
        return canonical_json(self.to_dict()).encode("utf-8")

    def content_digest(self) -> str:
        return content_sha256(self.to_canonical_bytes())

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "CfrTitle37FullManifest":
        if not isinstance(value, Mapping):
            raise SchemaValidationError("manifest must be a mapping")
        if "edition_identity" not in value or value.get("edition_identity") in (
            None,
            {},
            "",
        ):
            raise MissingEditionIdentityError("edition_identity is required")
        inventory_raw = value.get("inventory")
        if inventory_raw is None:
            raise EmptyInventoryError("inventory is required")
        if not isinstance(inventory_raw, Sequence) or isinstance(inventory_raw, (str, bytes)):
            raise EmptyInventoryError("inventory must be a non-empty array")
        if len(inventory_raw) == 0:
            raise EmptyInventoryError("inventory must not be empty")

        edition = EditionIdentity.from_dict(value["edition_identity"])  # type: ignore[arg-type]
        inventory = [
            e if isinstance(e, InventorySectionEntry) else InventorySectionEntry.from_dict(e)
            for e in inventory_raw
        ]
        gaps_raw = value.get("gaps") or []
        gaps = [
            g if isinstance(g, GapRecord) else GapRecord.from_dict(g)
            for g in gaps_raw
        ]
        binding_raw = value.get("package_binding")
        if not binding_raw:
            raise PackageBindingError("package_binding is required")
        binding = (
            binding_raw
            if isinstance(binding_raw, PackageBinding)
            else PackageBinding.from_dict(binding_raw)  # type: ignore[arg-type]
        )
        counts_raw = value.get("counts")
        counts = (
            None
            if counts_raw in (None, {})
            else (
                counts_raw
                if isinstance(counts_raw, InventoryCounts)
                else InventoryCounts.from_dict(counts_raw)  # type: ignore[arg-type]
            )
        )
        mode_raw = value.get("mode", MaterializationMode.DRY_RUN.value)
        return cls(
            edition_identity=edition,
            inventory=tuple(inventory),
            package_binding=binding,
            gaps=tuple(gaps),
            counts=counts,
            schema_version=value.get("schema_version", SCHEMA_VERSION),  # type: ignore[arg-type]
            interface=value.get("interface", INTERFACE),  # type: ignore[arg-type]
            task_id=value.get("task_id", TASK_ID),  # type: ignore[arg-type]
            goal_id=value.get("goal_id", GOAL_ID),  # type: ignore[arg-type]
            producer=value.get("producer", PRODUCER),  # type: ignore[arg-type]
            config_id=value.get("config_id", CONFIG_ID),  # type: ignore[arg-type]
            code_version=value.get("code_version", CODE_VERSION),  # type: ignore[arg-type]
            partition=value.get("partition", DEFAULT_PARTITION),  # type: ignore[arg-type]
            mode=mode_raw,  # type: ignore[arg-type]
            current_through=value.get("current_through"),  # type: ignore[arg-type]
            inventory_digest_sha256=value.get("inventory_digest_sha256") or "",  # type: ignore[arg-type]
            notes=value.get("notes") or "",  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# Builders / validation
# ---------------------------------------------------------------------------


def build_full_title37_inventory(
    edition: EditionIdentity | Mapping[str, Any] | str | int,
    *,
    gap_sections: Optional[Iterable[str]] = None,
    default_presence: SectionPresence = SectionPresence.PRESENT,
) -> tuple[InventorySectionEntry, ...]:
    """Enumerate **all** Title 37 catalog sections for a pinned annual edition.

    Parameters
    ----------
    edition:
        :class:`EditionIdentity`, mapping, or calendar year.
    gap_sections:
        Optional section tokens recorded as :attr:`SectionPresence.GAP`.
    default_presence:
        Presence for non-gap sections (typically ``present`` pending acquisition).
    """

    identity = _coerce_edition(edition)
    gaps = {normalize_section_token(s) for s in (gap_sections or ())}
    entries: list[InventorySectionEntry] = []
    for part in TITLE37_PARTS:
        meta = TITLE37_PART_METADATA[part]
        for section in TITLE37_SECTION_CATALOG[part]:
            presence = (
                SectionPresence.GAP if section in gaps else default_presence
            )
            granule = _govinfo_granule_id(
                package_id=identity.package_id, part=part, section=section
            )
            entries.append(
                InventorySectionEntry(
                    part=part,
                    section=section,
                    heading=meta.get("heading", ""),
                    chapter=meta.get("chapter", ""),
                    granule_id=granule,
                    presence=presence,
                    source_url=(
                        f"https://www.govinfo.gov/content/pkg/"
                        f"{identity.package_id}/xml/{granule}.xml"
                    ),
                )
            )
    if not entries:
        raise EmptyInventoryError("Title 37 catalog produced an empty inventory")
    return tuple(entries)


def build_gap_records_for_inventory(
    inventory: Sequence[InventorySectionEntry],
    *,
    reason: GapReason = GapReason.ACQUISITION_PENDING,
    note: str = "",
) -> tuple[GapRecord, ...]:
    """Build gap records for every inventory row with presence=gap."""

    records: list[GapRecord] = []
    for entry in inventory:
        if entry.presence is not SectionPresence.GAP:
            continue
        records.append(
            GapRecord(
                section=entry.section,
                part=entry.part,
                reason=reason,
                stable_id=entry.stable_id,
                granule_id=entry.granule_id,
                note=note
                or f"Section {entry.citation} inventoried without package text",
            )
        )
    return tuple(records)


def build_package_binding(
    edition: EditionIdentity | Mapping[str, Any] | str | int,
    *,
    package_digest_sha256: Optional[str] = None,
    inventory: Optional[Sequence[InventorySectionEntry]] = None,
    xml_sha256: Optional[str] = None,
    pdf_sha256: Optional[str] = None,
    mods_sha256: Optional[str] = None,
    package_root_cid: Optional[str] = None,
) -> PackageBinding:
    """Build content-addressed package bindings for a pinned edition."""

    identity = _coerce_edition(edition)
    inv_digest = None
    if inventory is not None:
        inv_digest = content_digest_of(
            [e.to_dict() if isinstance(e, InventorySectionEntry) else e for e in inventory]
        )
    digest = package_digest_sha256 or content_digest_of(
        {
            "package_id": identity.package_id,
            "year": identity.year,
            "inventory_digest_sha256": inv_digest,
        }
    )
    return PackageBinding(
        package_id=identity.package_id,
        package_digest_sha256=digest,
        package_root_cid=package_root_cid,
        xml_sha256=xml_sha256,
        pdf_sha256=pdf_sha256,
        mods_sha256=mods_sha256,
        inventory_digest_sha256=inv_digest,
        source_url=(
            f"https://www.govinfo.gov/content/pkg/"
            f"{identity.package_id}/xml/{identity.package_id}.xml"
        ),
    )


def build_full_title37_manifest(
    year: Any,
    *,
    gap_sections: Optional[Iterable[str]] = None,
    mode: MaterializationMode | str = MaterializationMode.DRY_RUN,
    package_digest_sha256: Optional[str] = None,
    date_issued: Optional[str] = None,
    current_through: Optional[str] = None,
    notes: str = "",
    require_full_catalog: bool = True,
) -> CfrTitle37FullManifest:
    """Build a complete pinned Title 37 full-inventory manifest.

    When *require_full_catalog* is true (default), the inventory enumerates
    every section in :data:`TITLE37_SECTION_CATALOG`.
    """

    identity = EditionIdentity.for_year(year, date_issued=date_issued)
    inventory = build_full_title37_inventory(identity, gap_sections=gap_sections)
    gaps = build_gap_records_for_inventory(inventory)
    binding = build_package_binding(
        identity,
        package_digest_sha256=package_digest_sha256,
        inventory=inventory,
    )
    manifest = CfrTitle37FullManifest(
        edition_identity=identity,
        inventory=inventory,
        package_binding=binding,
        gaps=gaps,
        mode=mode,  # type: ignore[arg-type]
        current_through=current_through or identity.date_issued,
        notes=notes
        or (
            f"Full annual Title 37 inventory for {identity.package_id}; "
            "official GovInfo package pin (not eCFR)."
        ),
    )
    if require_full_catalog:
        manifest.assert_full_catalog_coverage()
    return manifest


def validate_manifest(
    value: CfrTitle37FullManifest | Mapping[str, Any],
    *,
    require_full_catalog: bool = True,
) -> CfrTitle37FullManifest:
    """Validate a manifest mapping or object; fail closed on contract violations."""

    if isinstance(value, CfrTitle37FullManifest):
        manifest = value
    else:
        if not isinstance(value, Mapping):
            raise SchemaValidationError("manifest must be a mapping")
        # Fail closed on missing / empty identity before deeper parse.
        if "edition_identity" not in value:
            raise MissingEditionIdentityError("edition_identity is required")
        if value.get("edition_identity") in (None, {}, ""):
            raise MissingEditionIdentityError("edition_identity is required")
        inv = value.get("inventory")
        if inv is None or inv == [] or inv == ():
            raise EmptyInventoryError("inventory must not be empty")
        # Unpinned latest scan on identity fields before full parse.
        identity = value.get("edition_identity") or {}
        if isinstance(identity, Mapping):
            for key in ("year", "package_id", "edition", "provider"):
                if key in identity:
                    _reject_latest_token(identity.get(key), field_name=key)
        manifest = CfrTitle37FullManifest.from_dict(value)
    if require_full_catalog:
        manifest.assert_full_catalog_coverage()
    return manifest


def _coerce_edition(
    edition: EditionIdentity | Mapping[str, Any] | str | int,
) -> EditionIdentity:
    if isinstance(edition, EditionIdentity):
        return edition
    if isinstance(edition, Mapping):
        return EditionIdentity.from_dict(edition)
    return EditionIdentity.for_year(edition)


def manifest_schema_path(repo_root: Optional[PathLike] = None) -> Path:
    """Return the absolute path of the companion JSON Schema file."""

    if repo_root is None:
        # ipfs_datasets_py/processors/domains/patent/this_file.py → repo root
        here = Path(__file__).resolve()
        repo_root = here.parents[4]
    return Path(repo_root) / MANIFEST_SCHEMA_RELPATH


def load_manifest_schema(repo_root: Optional[PathLike] = None) -> dict[str, Any]:
    """Load the release JSON Schema for full Title 37 manifests."""

    path = manifest_schema_path(repo_root)
    if not path.is_file():
        raise FileNotFoundError(f"manifest schema not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def validate_against_json_schema(
    manifest: CfrTitle37FullManifest | Mapping[str, Any],
    *,
    schema: Optional[Mapping[str, Any]] = None,
    repo_root: Optional[PathLike] = None,
) -> None:
    """Validate *manifest* against the release JSON Schema when jsonschema is available.

    Raises
    ------
    SchemaValidationError
        On schema violations.
    ImportError
        When the optional ``jsonschema`` package is not installed (callers may
        catch this if JSON Schema validation is optional).
    """

    import jsonschema  # local import — optional dependency surface

    payload = (
        manifest.to_dict()
        if isinstance(manifest, CfrTitle37FullManifest)
        else dict(manifest)
    )
    schema_doc = schema or load_manifest_schema(repo_root)
    validator = jsonschema.Draft202012Validator(schema_doc)
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
    if errors:
        first = errors[0]
        path = "/".join(str(p) for p in first.absolute_path) or "<root>"
        raise SchemaValidationError(
            f"JSON Schema validation failed at {path}: {first.message}"
        )


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------

__all__ = [
    "SCHEMA_VERSION",
    "INTERFACE",
    "PRODUCER",
    "CONFIG_ID",
    "TASK_ID",
    "GOAL_ID",
    "CODE_VERSION",
    "MANIFEST_FILENAME",
    "MANIFEST_SCHEMA_RELPATH",
    "DEFAULT_TITLE",
    "DEFAULT_PROVIDER",
    "DEFAULT_COLLECTION",
    "DEFAULT_JURISDICTION",
    "DEFAULT_AUTHORITY_TIER",
    "DEFAULT_PARTITION",
    "TITLE37_PART_METADATA",
    "TITLE37_SECTION_CATALOG",
    "TITLE37_PARTS",
    "CfrTitle37FullError",
    "MissingEditionIdentityError",
    "EmptyInventoryError",
    "UnpinnedLatestError",
    "IncompleteInventoryError",
    "SchemaValidationError",
    "PackageBindingError",
    "GapRecordError",
    "SectionPresence",
    "GapReason",
    "MaterializationMode",
    "EditionIdentity",
    "GapRecord",
    "InventorySectionEntry",
    "PackageBinding",
    "InventoryCounts",
    "CfrTitle37FullManifest",
    "canonical_json",
    "content_digest_of",
    "content_sha256",
    "title37_all_section_tokens",
    "title37_section_count",
    "build_full_title37_inventory",
    "build_gap_records_for_inventory",
    "build_package_binding",
    "build_full_title37_manifest",
    "validate_manifest",
    "manifest_schema_path",
    "load_manifest_schema",
    "validate_against_json_schema",
]
