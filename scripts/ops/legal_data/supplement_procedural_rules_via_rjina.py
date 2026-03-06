#!/usr/bin/env python3
"""Supplement US state procedural rules using r.jina.ai mirrored pages.

This script targets states with no matches in the existing procedural-rules
summary, fetches state legal index pages via r.jina.ai, extracts civil/criminal
procedure links, and writes supplemental records. It can also produce a merged
JSONL for downstream use.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests

from ipfs_datasets_py.processors.legal_scrapers.state_laws_scraper import US_STATES

LINK_RE = re.compile(r"\[(?P<label>[^\]]+)\]\((?P<url>[^)]+)\)")
HTML_LINK_RE = re.compile(r"<a\s+[^>]*href=[\"'](?P<url>[^\"']+)[\"'][^>]*>(?P<label>.*?)</a>", re.IGNORECASE | re.DOTALL)

CIVIL_RE = re.compile(
    r"rules?\s+of\s+civil\s+procedure|civil\s+procedure|code\s+of\s+civil\s+procedure|civil\s+practice|special\s+civil|\bcplr\b|\bccp\b|\bciv\.?\s*p(?:roc)?\b|\br\.?civ\.?\s*p\.?\b",
    re.IGNORECASE,
)
CRIMINAL_RE = re.compile(
    r"rules?\s+of\s+criminal\s+procedure|criminal\s+procedure|code\s+of\s+criminal\s+procedure|criminal\s+practice|\bcrim\.?\s*p(?:roc)?\b|\br\.?crim\.?\s*p\.?\b",
    re.IGNORECASE,
)
FALLBACK_LINK_RE = re.compile(
    r"rule|rules|form|forms|procedure|court|civil|criminal|chapter|article|section|subtitle|part|title",
    re.IGNORECASE,
)


def _same_domain(seed_url: str, target_url: str) -> bool:
    seed_host = (urlparse(seed_url).hostname or "").lower()
    target_host = (urlparse(target_url).hostname or "").lower()
    if not seed_host or not target_host:
        return False
    if seed_host == target_host:
        return True
    return target_host.endswith(f".{seed_host}") or seed_host.endswith(f".{target_host}")


def _page_context_family(seed_url: str, markdown_text: str) -> Optional[str]:
    seed_lower = seed_url.lower()
    text_head = "\n".join(markdown_text.splitlines()[:80]).lower()
    context = f"{seed_lower}\n{text_head}"
    if "district-of-columbia/title-13" in seed_lower:
        return "civil_procedure"
    if "circuit-courts-civil-justice-improvement-rules" in seed_lower:
        return "civil_procedure"
    if "forms-files/civil" in seed_lower or "title: civil" in context:
        return "civil_procedure"
    if "forms-files/criminal" in seed_lower or "title: criminal" in context:
        return "criminal_procedure"
    if "maryland/courts-and-judicial-proceedings/title-6" in seed_lower:
        return "civil_procedure"
    if "louisiana/code-of-civil-procedure" in seed_lower:
        return "civil_procedure"
    # Justia and similar title pages often contain the family signal in page title
    # while individual link labels are generic (e.g., chapter/article names).
    if any(
        token in context
        for token in [
            "civil law and procedure",
            "civil practice",
            "civil actions",
            "civil remedies and procedure",
            "courts and civil procedure",
            "courts and court procedure",
            "proceedings in civil actions",
            "pleading and practice",
            "code of civil procedure",
        ]
    ):
        return "civil_procedure"
    if any(
        token in context
        for token in [
            "criminal procedure",
            "criminal procedures",
            "court procedure -- criminal",
        ]
    ):
        return "criminal_procedure"
    return None


def _justia_slug(state_name: str) -> str:
    slug = state_name.lower().strip().replace("&", "and")
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug


def _rjina_fetch(url: str, timeout: int = 45, retries: int = 4, backoff_s: float = 1.5) -> str:
    direct_archive = "web.archive.org" in url.lower()
    mirror = f"https://r.jina.ai/http://{url.replace('https://', '').replace('http://', '')}"
    last_exc: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            target_url = url if direct_archive else mirror
            resp = requests.get(target_url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code == 429 and attempt < retries:
                time.sleep(backoff_s * attempt)
                continue
            resp.raise_for_status()
            return resp.text
        except Exception as exc:  # pragma: no cover - network dependent
            last_exc = exc
            if attempt < retries:
                time.sleep(backoff_s * attempt)
                continue
            raise
    if last_exc:
        raise last_exc
    raise RuntimeError(f"Failed to fetch mirrored URL: {url}")


def _classify(label: str, url: str) -> Optional[str]:
    text = f"{label}\n{url}"
    civ = CIVIL_RE.search(text) is not None
    cri = CRIMINAL_RE.search(text) is not None
    if civ and cri:
        return "civil_and_criminal_procedure"
    if civ:
        return "civil_procedure"
    if cri:
        return "criminal_procedure"
    return None


def _extract_matches(markdown_text: str, seed_url: str) -> List[Tuple[str, str, str]]:
    out: List[Tuple[str, str, str]] = []
    fallback_family = _page_context_family(seed_url, markdown_text)
    for m in LINK_RE.finditer(markdown_text):
        label = m.group("label").strip()
        raw_url = html.unescape(m.group("url")).strip()
        url = urljoin(seed_url, raw_url)
        if not url.lower().startswith(("http://", "https://")):
            continue
        family = _classify(label, url)
        generic_label = (
            len(label) <= 10
            or label.lower().startswith("image")
            or "click to view" in label.lower()
            or label.strip() in {"More...", "View More"}
        )
        if not family and generic_label:
            start = max(0, m.start() - 220)
            end = min(len(markdown_text), m.end() + 220)
            nearby = markdown_text[start:end]
            family = _classify(nearby, url)
        # Iowa court rules listing often uses image labels for PDF links; infer chapter family.
        if not family and "legis.iowa.gov" in url.lower() and "chapter." in url.lower():
            if ".chapter.1." in url.lower():
                family = "civil_procedure"
            elif ".chapter.2." in url.lower():
                family = "criminal_procedure"
        if not family and fallback_family and (
            url.lower().endswith(".pdf")
            or FALLBACK_LINK_RE.search(f"{label}\n{url}") is not None
        ) and _same_domain(seed_url, url):
            family = fallback_family
        if family:
            out.append((family, label, url))

    if not out and "<a " in markdown_text.lower():
        for m in HTML_LINK_RE.finditer(markdown_text):
            raw_label = re.sub(r"<[^>]+>", " ", m.group("label"))
            label = html.unescape(raw_label).strip()
            raw_url = html.unescape(m.group("url")).strip()
            url = urljoin(seed_url, raw_url)
            if not url.lower().startswith(("http://", "https://")):
                continue
            family = _classify(label, url)
            if not family and fallback_family and (
                url.lower().endswith(".pdf")
                or FALLBACK_LINK_RE.search(f"{label}\n{url}") is not None
            ) and _same_domain(seed_url, url):
                family = fallback_family
            if family:
                out.append((family, label, url))

    return out


def _state_seed_urls(state_code: str, state_name: str) -> List[str]:
    slug = _justia_slug(state_name)
    seeds = [f"https://law.justia.com/codes/{slug}/"]
    if state_code == "IA":
        seeds.extend(
            [
                "https://www.legis.iowa.gov/law/courtRules/courtRulesListings",
                "https://www.legis.iowa.gov/law/courtRules",
            ]
        )
    if state_code == "NJ":
        seeds.append("https://www.njcourts.gov/attorneys/rules-of-court")
    if state_code == "FL":
        seeds.append("https://www.floridabar.org/rules/ctproc/")
    if state_code == "CT":
        seeds.append("https://law.justia.com/codes/connecticut/title-54/")
    if state_code == "GA":
        seeds.append("https://law.justia.com/codes/georgia/title-17/")
    if state_code == "KS":
        seeds.append("https://law.justia.com/codes/kansas/chapter-22/")
    if state_code == "ME":
        seeds.append("https://law.justia.com/codes/maine/title-15/")
    if state_code == "SD":
        seeds.append("https://law.justia.com/codes/south-dakota/title-23a/")
    if state_code == "SC":
        seeds.append("https://law.justia.com/codes/south-carolina/title-17/")
    if state_code == "TN":
        seeds.append("https://law.justia.com/codes/tennessee/title-40/")
    if state_code == "IN":
        seeds.append("https://law.justia.com/codes/indiana/title-34/")
    if state_code == "MT":
        seeds.append("https://law.justia.com/codes/montana/title-25/")
    if state_code == "OK":
        seeds.append("https://law.justia.com/codes/oklahoma/title-12/")
    if state_code == "MS":
        seeds.append("https://law.justia.com/codes/mississippi/title-11/")
    if state_code == "RI":
        seeds.append("https://law.justia.com/codes/rhode-island/title-9/")
    if state_code == "AL":
        seeds.append("https://law.justia.com/codes/alabama/title-6/")
    if state_code == "AR":
        seeds.append("https://law.justia.com/codes/arkansas/title-16/")
    if state_code == "DE":
        seeds.append("https://law.justia.com/codes/delaware/title-10/")
        seeds.append("https://law.justia.com/codes/delaware/title-10/chapter-39/")
    if state_code == "CO":
        seeds.append("https://law.justia.com/codes/colorado/2024/title-13/")
    if state_code == "ID":
        seeds.append("https://law.justia.com/codes/idaho/title-5/")
    if state_code == "LA":
        seeds.append("https://law.justia.com/codes/louisiana/code-of-civil-procedure/")
    if state_code == "MD":
        seeds.append("https://law.justia.com/codes/maryland/courts-and-judicial-proceedings/title-6/")
    if state_code == "UT":
        seeds.extend(
            [
                "https://law.justia.com/codes/utah/title-78b/chapter-3/",
                "https://law.justia.com/codes/utah/title-78b/chapter-3a/",
            ]
        )
    if state_code == "VA":
        seeds.append("https://law.justia.com/codes/virginia/title-8-01/")
    if state_code == "WV":
        seeds.append("https://law.justia.com/codes/west-virginia/chapter-56/")
    if state_code == "KY":
        seeds.append("https://law.justia.com/codes/kentucky/chapter-454/")
    if state_code == "MI":
        seeds.append(
            "https://www.courts.michigan.gov/rules-administrative-orders-and-jury-instructions/current-rules-and-jury-instructions/michigan-court-rules/"
        )
    if state_code == "DC":
        seeds.append("https://law.justia.com/codes/district-of-columbia/title-13/")
        seeds.append("https://law.justia.com/codes/district-of-columbia/title-13/chapter-1/")
    if state_code == "HI":
        seeds.append("https://www.courts.state.hi.us/circuit-courts-civil-justice-improvement-rules")
    if state_code == "OH":
        seeds.extend(
            [
                "https://www.supremecourt.ohio.gov/laws-rules/ohio-rules-of-court/",
                "http://www.supremecourt.ohio.gov/docs/LegalResources/Rules/civil/CivilProcedure.pdf",
                "http://www.supremecourt.ohio.gov/docs/LegalResources/Rules/criminal/CriminalProcedure.pdf",
            ]
        )
    if state_code == "PA":
        seeds.extend(
            [
                "https://www.pacourts.us/courts/supreme-court/committees/rules-committees",
                "https://www.pacourts.us/courts/supreme-court/committees/rules-committees/civil-procedural-rules-committee",
                "https://www.pacourts.us/courts/supreme-court/committees/rules-committees/criminal-procedural-rules-committee",
            ]
        )
    if state_code == "WY":
        seeds.append("https://www.courts.state.wy.us/court-rules/")
    if state_code == "MN":
        seeds.extend(
            [
                "https://www.revisor.mn.gov/court_rules/",
            ]
        )
    if state_code == "MO":
        seeds.extend(
            [
                "https://www.courts.mo.gov/page.jsp?id=46",
                "https://web.archive.org/web/20161115161825/https://www.courts.mo.gov/page.jsp?id=46",
                "https://web.archive.org/web/20161115161825/https://www.courts.mo.gov/page.jsp?id=671",
                "https://web.archive.org/web/20161115161825/https://www.courts.mo.gov/page.jsp?id=674",
                "https://web.archive.org/web/20161115161825/https://www.courts.mo.gov/page.jsp?id=676",
                "https://web.archive.org/web/20161115161825/https://www.courts.mo.gov/page.jsp?id=677",
                "https://web.archive.org/web/20161115161825/https://www.courts.mo.gov/page.jsp?id=679",
            ]
        )
    if state_code == "NM":
        seeds.extend(
            [
                "https://nmcourts.gov/forms-files/civil",
                "https://nmcourts.gov/forms-files/criminal",
                "https://nmcourts.gov/rules-forms-filing/",
            ]
        )
    if state_code == "ND":
        seeds.extend(
            [
                "https://www.ndcourts.gov/legal-resources/rules",
                "https://www.ndcourts.gov/legal-resources/rules/ndrcivp",
                "https://www.ndcourts.gov/legal-resources/rules/ndrcrimp",
            ]
        )
    if state_code == "NH":
        seeds.extend(
            [
                "https://www.courts.nh.gov/self-help/civil",
                "https://www.courts.nh.gov/self-help/criminal",
                "https://www.courts.nh.gov/media/rules-governing-media-court",
            ]
        )
    if state_code == "DC":
        seeds.extend([
            "https://www.dccourts.gov/superior-court/rules",
            "https://www.dccourts.gov/services/civil-matters/rules-civil-procedure",
            "https://www.dccourts.gov/services/criminal-matters/rules-criminal-procedure",
        ])
    return seeds


def _load_no_match_states(summary_path: Path) -> List[str]:
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    states = payload.get("supported_with_no_procedural_matches") or []
    return [str(s).upper() for s in states if str(s).upper() in US_STATES]


def run(
    summary_path: Path,
    output_jsonl: Path,
    merged_output_jsonl: Optional[Path],
    base_jsonl: Optional[Path],
    sleep_s: float,
    target_states: Optional[List[str]],
) -> Dict[str, Any]:
    if target_states:
        targets = sorted({s.upper() for s in target_states if s.upper() in US_STATES})
    else:
        targets = _load_no_match_states(summary_path)
    supplemental: List[Dict[str, Any]] = []
    states_with_hits: Dict[str, int] = {}
    errors: Dict[str, str] = {}

    for state_code in targets:
        state_name = US_STATES[state_code]
        state_hits = 0
        for seed in _state_seed_urls(state_code, state_name):
            try:
                markdown = _rjina_fetch(seed)
            except Exception as exc:
                errors[f"{state_code}:{seed}"] = str(exc)
                continue

            for family, label, url in _extract_matches(markdown, seed):
                supplemental.append(
                    {
                        "jurisdiction_code": state_code,
                        "jurisdiction_name": state_name,
                        "territory": False,
                        "procedure_family": family,
                        "ipfs_cid": None,
                        "name": label,
                        "titleName": None,
                        "chapterName": None,
                        "sectionName": label,
                        "sourceUrl": url,
                        "code_name": "supplemental_procedural_rules_rjina",
                        "text": None,
                        "record": {
                            "source": "r.jina.ai",
                            "seed_url": seed,
                            "label": label,
                            "target_url": url,
                        },
                    }
                )
                state_hits += 1

            time.sleep(max(0.0, sleep_s))

        if state_hits > 0:
            states_with_hits[state_code] = state_hits

    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with output_jsonl.open("w", encoding="utf-8") as handle:
        for row in supplemental:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    merged_count = None
    if merged_output_jsonl and base_jsonl and base_jsonl.exists():
        merged_output_jsonl.parent.mkdir(parents=True, exist_ok=True)
        seen = set()
        merged_rows: List[Dict[str, Any]] = []

        for path in [base_jsonl, output_jsonl]:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    obj = json.loads(line)
                    key = (
                        obj.get("jurisdiction_code"),
                        obj.get("procedure_family"),
                        obj.get("sourceUrl"),
                        obj.get("name"),
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    merged_rows.append(obj)

        with merged_output_jsonl.open("w", encoding="utf-8") as handle:
            for row in merged_rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        merged_count = len(merged_rows)

    return {
        "status": "success",
        "targets": targets,
        "targets_count": len(targets),
        "supplemental_records": len(supplemental),
        "states_with_hits_count": len(states_with_hits),
        "states_with_hits": states_with_hits,
        "errors_count": len(errors),
        "errors_sample": dict(list(errors.items())[:20]),
        "supplemental_output": str(output_jsonl),
        "merged_output": str(merged_output_jsonl) if merged_output_jsonl else None,
        "merged_count": merged_count,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Supplement state procedural rules via r.jina.ai")
    parser.add_argument(
        "--summary-json",
        default=str(Path.home() / ".ipfs_datasets" / "state_laws" / "procedural_rules" / "us_state_procedural_rules_summary.json"),
    )
    parser.add_argument(
        "--base-jsonl",
        default=str(Path.home() / ".ipfs_datasets" / "state_laws" / "procedural_rules" / "us_state_procedural_rules.jsonl"),
    )
    parser.add_argument(
        "--output-jsonl",
        default=str(Path.home() / ".ipfs_datasets" / "state_laws" / "procedural_rules" / "us_state_procedural_rules_supplemental_rjina.jsonl"),
    )
    parser.add_argument(
        "--merged-output-jsonl",
        default=str(Path.home() / ".ipfs_datasets" / "state_laws" / "procedural_rules" / "us_state_procedural_rules_merged_with_rjina.jsonl"),
    )
    parser.add_argument("--sleep-s", type=float, default=0.1)
    parser.add_argument(
        "--states",
        nargs="*",
        default=None,
        help="Optional state code list (e.g. IA NM) to limit supplementation",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run(
        summary_path=Path(args.summary_json).expanduser().resolve(),
        output_jsonl=Path(args.output_jsonl).expanduser().resolve(),
        merged_output_jsonl=Path(args.merged_output_jsonl).expanduser().resolve(),
        base_jsonl=Path(args.base_jsonl).expanduser().resolve(),
        sleep_s=float(args.sleep_s),
        target_states=args.states,
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
