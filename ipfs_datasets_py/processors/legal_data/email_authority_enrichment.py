from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from mediator.mediator import Mediator


_TOPIC_QUERY_HINTS: Dict[str, List[str]] = {
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
}

_TOPIC_PRIORITY = {
    "hcv_orientation": 6,
    "cortez_case": 5,
    "fraud_household": 4,
    "additional_information": 3,
    "annual_certification": 2,
    "clackamas_process": 1,
}

_DEFAULT_STATE_ARCHIVE_DOMAINS = [
    "hud.gov",
    "oregon.public.law",
    "oregonlegislature.gov",
    "oregonlaws.org",
    "clackamas.us",
]

_BASE_SEED_AUTHORITIES: List[Dict[str, str]] = [
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
        "rationale": "State housing-authority powers and governance context for Clackamas County housing authority conduct.",
    },
]

_TOPIC_CASE_SEEDS: Dict[str, List[Dict[str, str]]] = {
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
}


def _load_email_timeline_handoff(path: str | Path) -> Dict[str, Any]:
    payload = json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _topic_summary_items(email_timeline_handoff: Dict[str, Any]) -> List[tuple[str, Dict[str, Any]]]:
    packet = (
        email_timeline_handoff.get("claim_support_temporal_handoff")
        if isinstance(email_timeline_handoff.get("claim_support_temporal_handoff"), dict)
        else {}
    )
    summary = packet.get("topic_summary") if isinstance(packet.get("topic_summary"), dict) else {}
    items: List[tuple[str, Dict[str, Any]]] = []
    for topic, value in summary.items():
        if not isinstance(value, dict):
            continue
        items.append((str(topic), dict(value)))
    items.sort(
        key=lambda item: (
            int(_TOPIC_PRIORITY.get(str(item[0]), 0)),
            int(item[1].get("count") or 0),
        ),
        reverse=True,
    )
    return items


def _collect_participants(email_timeline_handoff: Dict[str, Any], *, limit: int = 8) -> List[str]:
    canonical_facts = (
        list(email_timeline_handoff.get("canonical_facts") or [])
        if isinstance(email_timeline_handoff, dict)
        else []
    )
    participants: List[str] = []
    seen = set()
    for fact in canonical_facts:
        if not isinstance(fact, dict):
            continue
        for value in fact.get("participants") or []:
            text = str(value or "").strip().lower()
            if not text or text in seen:
                continue
            seen.add(text)
            participants.append(text)
            if len(participants) >= limit:
                return participants
    return participants


def build_email_authority_query_plan(
    email_timeline_handoff: Dict[str, Any],
    *,
    jurisdiction_label: str = "Oregon",
    max_topics: int = 5,
) -> List[Dict[str, Any]]:
    claim_type = str(email_timeline_handoff.get("claim_type") or "").strip() or "retaliation"
    claim_element_id = str(email_timeline_handoff.get("claim_element_id") or "").strip() or "causation"
    participants = _collect_participants(email_timeline_handoff)
    has_clackamas = any("clackamas.us" in item for item in participants)
    organization_terms = [
        "Clackamas County Housing Authority" if has_clackamas else "",
        "Clackamas County" if has_clackamas else "",
        "HACC" if has_clackamas else "",
    ]
    plan: List[Dict[str, Any]] = []
    seen_queries = set()

    def _append(topic: str, query: str, *, rationale: str, authority_families: Optional[List[str]] = None) -> None:
        text = " ".join(part for part in [query] if str(part or "").strip()).strip()
        if not text:
            return
        key = text.lower()
        if key in seen_queries:
            return
        seen_queries.add(key)
        plan.append(
            {
                "topic": topic,
                "query": text,
                "claim_type": claim_type,
                "claim_element_id": claim_element_id,
                "jurisdiction_label": jurisdiction_label,
                "authority_families": authority_families or ["statute", "regulation", "case_law", "agency_guidance"],
                "rationale": rationale,
            }
        )

    base_parts = [jurisdiction_label, claim_type, claim_element_id] + [term for term in organization_terms if term]
    _append(
        "overview",
        " ".join(base_parts + ["housing authority", "state law", "case law"]),
        rationale="Broad state and case-law sweep anchored to the email-derived claim posture.",
    )

    selected_topics = _topic_summary_items(email_timeline_handoff)[:max_topics]
    topic_hints_map = {
        topic: _TOPIC_QUERY_HINTS.get(topic, [topic.replace("_", " ")])[:3]
        for topic, _ in selected_topics
    }

    for hint_index in range(3):
        for topic, payload in selected_topics:
            topic_hints = topic_hints_map.get(topic) or []
            if hint_index >= len(topic_hints):
                continue
            hint = topic_hints[hint_index]
            _append(
                topic,
                " ".join(
                    part for part in [jurisdiction_label, *organization_terms, claim_type, hint] if str(part or "").strip()
                ),
                rationale=f"Topic-driven authority search for {topic} with {int(payload.get('count') or 0)} email events.",
            )

    if has_clackamas:
        _append(
            "clackamas_process",
            f"{jurisdiction_label} Clackamas County housing authority grievance hearing administrative plan reasonable accommodation",
            rationale="County- and housing-authority-specific process law/guidance sweep.",
            authority_families=["regulation", "administrative_rule", "agency_guidance", "case_law"],
        )

    return plan


def build_seed_authority_catalog(email_timeline_handoff: Dict[str, Any]) -> List[Dict[str, str]]:
    topics = {topic for topic, _ in _topic_summary_items(email_timeline_handoff)}
    seed_catalog: List[Dict[str, str]] = []
    seen = set()
    for item in _BASE_SEED_AUTHORITIES:
        topic = str(item.get("topic") or "")
        if topic and topic not in topics and topic not in {"reasonable_accommodation", "clackamas_process"}:
            continue
        key = str(item.get("citation") or item.get("source_url") or "")
        if key in seen:
            continue
        seen.add(key)
        seed_catalog.append(dict(item))

    if "hcv_orientation" in topics or "cortez_case" in topics:
        topics.add("reasonable_accommodation")

    for topic in sorted(topics):
        for item in _TOPIC_CASE_SEEDS.get(topic, []):
            key = str(item.get("citation") or item.get("source_url") or "")
            if key in seen:
                continue
            seen.add(key)
            seed_catalog.append(dict(item))

    return seed_catalog


def _build_seed_authority_summary(seed_authorities: List[Dict[str, str]]) -> Dict[str, Any]:
    by_type: Dict[str, int] = {}
    by_topic: Dict[str, List[Dict[str, str]]] = {}
    for item in seed_authorities:
        authority_type = str(item.get("authority_type") or "unknown").strip()
        topic = str(item.get("topic") or "general").strip()
        by_type[authority_type] = by_type.get(authority_type, 0) + 1
        by_topic.setdefault(topic, []).append(item)
    return {
        "authority_type_counts": by_type,
        "topic_authority_counts": {topic: len(items) for topic, items in by_topic.items()},
        "topic_authorities": by_topic,
    }


def enrich_email_timeline_authorities(
    email_timeline_handoff_path: str | Path,
    *,
    output_dir: Optional[str | Path] = None,
    jurisdiction: str = "or",
    jurisdiction_label: str = "Oregon",
    max_queries: int = 8,
    search_state_archives: bool = True,
) -> Dict[str, Any]:
    source_path = Path(email_timeline_handoff_path).expanduser().resolve()
    email_timeline_handoff = _load_email_timeline_handoff(source_path)
    mediator = Mediator(backends=[])
    query_plan = build_email_authority_query_plan(
        email_timeline_handoff,
        jurisdiction_label=jurisdiction_label,
    )[:max_queries]

    query_results: List[Dict[str, Any]] = []
    total_counts = {"statutes": 0, "regulations": 0, "case_law": 0, "web_archives": 0, "state_web_archives": 0}
    for item in query_plan:
        results = mediator.search_legal_authorities(
            item["query"],
            claim_type=item.get("claim_type"),
            jurisdiction=jurisdiction,
            search_all=True,
            authority_families=item.get("authority_families"),
        )
        state_archive_results: List[Dict[str, Any]] = []
        if search_state_archives:
            for domain in _DEFAULT_STATE_ARCHIVE_DOMAINS:
                try:
                    matches = mediator.legal_authority_search.search_web_archives(
                        domain,
                        query=item["query"],
                        max_results=3,
                    )
                except Exception:
                    matches = []
                if matches:
                    state_archive_results.extend(
                        [{"domain": domain, **match} for match in matches if isinstance(match, dict)]
                    )
        counts = {
            "statutes": len(results.get("statutes") or []),
            "regulations": len(results.get("regulations") or []),
            "case_law": len(results.get("case_law") or []),
            "web_archives": len(results.get("web_archives") or []),
            "state_web_archives": len(state_archive_results),
        }
        for key, value in counts.items():
            total_counts[key] += int(value or 0)
        query_results.append(
            {
                **item,
                "result_counts": counts,
                "results": results,
                "state_web_archives": state_archive_results,
            }
        )

    seed_authorities = build_seed_authority_catalog(email_timeline_handoff)
    seed_summary = _build_seed_authority_summary(seed_authorities)
    for item in query_results:
        topic = str(item.get("topic") or "")
        item["seed_matches"] = [
            authority for authority in seed_authorities if str(authority.get("topic") or "") in {topic, "reasonable_accommodation"}
        ][:6]
    payload = {
        "status": "success",
        "email_timeline_handoff_path": str(source_path),
        "claim_type": email_timeline_handoff.get("claim_type"),
        "claim_element_id": email_timeline_handoff.get("claim_element_id"),
        "query_plan": query_plan,
        "query_results": query_results,
        "seed_authorities": seed_authorities,
        "seed_authority_summary": seed_summary,
        "recommended_authorities": seed_authorities[:8],
        "summary": {
            "query_count": len(query_results),
            "total_counts": total_counts,
            "queries_with_hits": sum(
                1
                for item in query_results
                if sum(int(item.get("result_counts", {}).get(key) or 0) for key in total_counts.keys()) > 0
            ),
            "seed_authority_count": len(seed_authorities),
        },
    }

    destination_dir = Path(output_dir).expanduser().resolve() if output_dir else source_path.parent / "authority_enrichment"
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / "email_authority_enrichment.json"
    destination.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    markdown_path = destination_dir / "email_authority_enrichment.md"
    lines = [
        "# Email Authority Enrichment",
        "",
        f"- Claim type: {payload.get('claim_type') or 'unknown'}",
        f"- Claim element: {payload.get('claim_element_id') or 'unknown'}",
        f"- Live query count: {payload['summary']['query_count']}",
        f"- Live queries with hits: {payload['summary']['queries_with_hits']}",
        f"- Seed authority count: {payload['summary']['seed_authority_count']}",
        "",
        "## Recommended Authorities",
    ]
    for item in payload["recommended_authorities"]:
        lines.append(
            f"- {item.get('citation')}: {item.get('title')} ({item.get('authority_type')})"
        )
        lines.append(f"  {item.get('source_url')}")
        lines.append(f"  {item.get('rationale')}")
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    payload["output_path"] = str(destination)
    payload["markdown_output_path"] = str(markdown_path)
    return payload


__all__ = [
    "build_email_authority_query_plan",
    "build_seed_authority_catalog",
    "enrich_email_timeline_authorities",
]
