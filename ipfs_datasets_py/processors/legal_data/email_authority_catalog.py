"""Reusable catalog defaults and override helpers for email authority enrichment."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping


DEFAULT_EMAIL_AUTHORITY_ENRICHMENT_CATALOG: dict[str, Any] = {
    "topic_query_hints": {
        "fraud_household": [
            "24 CFR 982.551 24 CFR 982.552 informal hearing",
            "public housing fraud allegation informal hearing",
            "voucher termination family obligations",
        ],
        "additional_information": [
            "public housing authority documentation request grievance process",
            "voucher file documentation request case law",
        ],
        "annual_certification": [
            "annual certification recertification housing choice voucher",
            "24 CFR 982.516 recertification case law",
        ],
        "cortez_case": [
            "housing voucher denial reasonable accommodation case law",
            "fair housing reasonable accommodation denial public housing authority",
        ],
        "hcv_orientation": [
            "24 CFR 982.555 informal review reasonable accommodation voucher",
            "42 USC 3604(f)(3)(B) reasonable accommodation housing authority",
            "housing choice voucher orientation reasonable accommodation informal review",
        ],
    },
    "topic_priority": {
        "hcv_orientation": 6,
        "cortez_case": 5,
        "fraud_household": 4,
        "additional_information": 3,
        "annual_certification": 2,
        "clackamas_process": 1,
    },
    "default_state_archive_domains": [
        "hud.gov",
        "oregon.public.law",
        "oregonlegislature.gov",
        "oregonlaws.org",
        "clackamas.us",
    ],
    "base_seed_authorities": [
        {
            "authority_type": "statute",
            "title": "Fair Housing Act reasonable accommodations",
            "citation": "42 U.S.C. § 3604(f)(3)(B)",
            "source_url": "https://uscode.house.gov/view.xhtml?edition=prelim&num=0&req=granuleid%3AUSC-prelim-title42-section3604%28c%29",
            "topic": "reasonable_accommodation",
            "rationale": "Federal housing-discrimination anchor for accommodation requests tied to voucher administration or dwelling access.",
        },
        {
            "authority_type": "regulation",
            "title": "Family obligations under the Housing Choice Voucher program",
            "citation": "24 C.F.R. § 982.551",
            "source_url": "https://www.ecfr.gov/current/title-24/subtitle-B/chapter-IX/part-982/subpart-L/section-982.551",
            "topic": "fraud_household",
            "rationale": "Core HCV family-obligation rule for allegations tied to household composition or reporting duties.",
        },
        {
            "authority_type": "regulation",
            "title": "Denial or termination of assistance",
            "citation": "24 C.F.R. § 982.552",
            "source_url": "https://www.ecfr.gov/current/title-24/subtitle-B/chapter-IX/part-982/subpart-L/section-982.552",
            "topic": "fraud_household",
            "rationale": "Termination and denial rule commonly implicated by fraud-allegation and voucher-loss disputes.",
        },
        {
            "authority_type": "regulation",
            "title": "Informal review and hearing for participants",
            "citation": "24 C.F.R. § 982.555",
            "source_url": "https://www.ecfr.gov/current/title-24/subtitle-B/chapter-IX/part-982/subpart-L/section-982.555",
            "topic": "hcv_orientation",
            "rationale": "Primary HCV hearing/review regulation for termination, denial, and challenge process issues.",
        },
        {
            "authority_type": "guidance",
            "title": "HUD Housing Choice Voucher Program Guidebook",
            "citation": "HUD HCV Guidebook",
            "source_url": "https://www.hud.gov/helping-americans/housing-choice-vouchers-guidebook",
            "topic": "hcv_orientation",
            "rationale": "Current HUD program guidance, including chapters on informal hearings, reviews, fair housing, and terminations.",
        },
        {
            "authority_type": "guidance",
            "title": "HUD/DOJ Joint Statement on Reasonable Accommodations under the Fair Housing Act",
            "citation": "HUD/DOJ Joint Statement (May 17, 2004)",
            "source_url": "https://www.hud.gov/sites/documents/JOINTSTATEMENT.PDF",
            "topic": "reasonable_accommodation",
            "rationale": "Federal guidance on accommodation duties that often accompanies FHA reasonable-accommodation claims.",
        },
        {
            "authority_type": "state_statute",
            "title": "Oregon disability discrimination in real property transactions",
            "citation": "ORS 659A.145",
            "source_url": "https://oregon.public.law/statutes/ors_659a.145",
            "topic": "reasonable_accommodation",
            "rationale": "Oregon housing-discrimination statute with an accommodation clause for rules, policies, practices, or services.",
        },
        {
            "authority_type": "state_statute",
            "title": "Oregon Housing Authorities Law",
            "citation": "ORS Chapter 456",
            "source_url": "https://www.oregonlegislature.gov/bills_laws/ors/ors456.html",
            "topic": "clackamas_process",
            "rationale": "State housing-authority powers and governance context for housing authority conduct.",
        },
    ],
    "topic_case_seeds": {
        "reasonable_accommodation": [
            {
                "authority_type": "case_law",
                "title": "Giebeler v. M & B Associates",
                "citation": "343 F.3d 1143 (9th Cir. 2003)",
                "source_url": "https://law.justia.com/cases/federal/appellate-courts/F3/343/1143/636375/",
                "topic": "reasonable_accommodation",
                "rationale": "Ninth Circuit authority on FHA reasonable accommodations and policy adjustments for disabled tenants.",
            }
        ],
        "hcv_orientation": [
            {
                "authority_type": "case_law",
                "title": "Basham v. Freda",
                "citation": "805 F. Supp. 930 (M.D. Fla. 1992)",
                "source_url": "https://law.justia.com/cases/federal/district-courts/FSupp/805/930/2593123/",
                "topic": "hcv_orientation",
                "rationale": "Section 8 termination/hearing case discussing due-process requirements for voucher termination decisions.",
            },
            {
                "authority_type": "case_law",
                "title": "Hayward v. Brown",
                "citation": "No. 8:15-cv-03381 (D. Md. 2016)",
                "source_url": "https://law.justia.com/cases/federal/district-courts/maryland/mddce/8%3A2015cv03381/333339/24/",
                "topic": "hcv_orientation",
                "rationale": "Voucher hearing case collecting due-process authorities and HUD hearing-regulation history.",
            },
        ],
    },
}


def _deep_update(base: dict[str, Any], updates: Mapping[str, Any]) -> dict[str, Any]:
    for key, value in updates.items():
        if isinstance(value, Mapping) and isinstance(base.get(key), dict):
            _deep_update(base[key], value)
        else:
            base[key] = value
    return base


def merge_email_authority_enrichment_catalog(override: Mapping[str, Any] | None = None) -> dict[str, Any]:
    catalog = deepcopy(DEFAULT_EMAIL_AUTHORITY_ENRICHMENT_CATALOG)
    if override:
        _deep_update(catalog, override)
    return catalog


def load_email_authority_enrichment_catalog(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("email authority enrichment catalog override must be a JSON object")
    return merge_email_authority_enrichment_catalog(payload)


__all__ = [
    "DEFAULT_EMAIL_AUTHORITY_ENRICHMENT_CATALOG",
    "load_email_authority_enrichment_catalog",
    "merge_email_authority_enrichment_catalog",
]
