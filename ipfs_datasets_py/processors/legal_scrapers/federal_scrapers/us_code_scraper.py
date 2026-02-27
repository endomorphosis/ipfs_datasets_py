"""US Code scraper for building federal statutory law datasets.

This module downloads and parses title packages from GovInfo package endpoints,
producing section-level records suitable for full U.S. Code ingestion.
"""

import json
import logging
import re
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import anyio

try:
    import requests
    from bs4 import BeautifulSoup

    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

logger = logging.getLogger(__name__)

DEFAULT_USCODE_CACHE_DIR = Path.home() / ".ipfs_datasets" / "us_code" / "cache"
DEFAULT_USCODE_INDEX_DIR = Path.home() / ".ipfs_datasets" / "us_code"
DEFAULT_USCODE_INDEX_PATH = DEFAULT_USCODE_INDEX_DIR / "uscode_index_latest.jsonl"
DEFAULT_USCODE_JSONLD_DIRNAME = "uscode_jsonld"
MIN_USCODE_YEAR = 1994
USER_AGENT = "ipfs-datasets-uscode-scraper/2.0"
SUBSEC_TOKEN_RE = re.compile(r"\(([0-9]+|[A-Za-z]{1,6})\)")
ROMAN_LOWER_RE = re.compile(r"^[ivxlcdm]+$")
ROMAN_UPPER_RE = re.compile(r"^[IVXLCDM]+$")
COMMON_ROMAN_LOWER = {
    "i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii", "xiii", "xiv", "xv"
}
COMMON_ROMAN_UPPER = {token.upper() for token in COMMON_ROMAN_LOWER}
CHAPTER_RE = re.compile(r"\b(CHAPTER\s+[A-Z0-9\-]+)\s*[\-—]\s*(.+?)(?=\s+Sec\.|\s+§|$)", re.IGNORECASE)
SUBCHAPTER_RE = re.compile(r"\b(SUBCHAPTER\s+[A-Z0-9\-]+)\s*[\-—]\s*(.+?)(?=\s+Sec\.|\s+§|$)", re.IGNORECASE)
PART_RE = re.compile(r"\b(PART\s+[A-Z0-9\-]+)\s*[\-—]\s*(.+?)(?=\s+Sec\.|\s+§|$)", re.IGNORECASE)
PUBLIC_LAW_CITATION_RE = re.compile(r"Pub\.?\s*L\.?\s*(?:No\.?\s*)?\d+\s*[–—−‑-]\s*\d+", re.IGNORECASE)
PUBLIC_LAW_LONGFORM_RE = re.compile(r"Public\s+Law\s+(?:No\.?\s*)?\d+\s*[–—−‑-]\s*\d+", re.IGNORECASE)
PUBLIC_LAW_CONGRESS_RE = re.compile(r"Public\s+Law\s+\d+\s*,\s*[A-Za-z][A-Za-z\-\s]{1,80}\s+Congress", re.IGNORECASE)
STAT_CITATION_RE = re.compile(r"\b\d+\s+Stat\.?\s+\d+\b", re.IGNORECASE)
USC_CITATION_RE = re.compile(r"\b\d+\s+U\.?\s*S\.?\s*C\.?\s*(?:§+\s*|sec(?:tion)?\.?\s*)?\d[\w\-\.()]*", re.IGNORECASE)
TITLE_SECTION_CITATION_RE = re.compile(r"\bsection\s+[\w\-.()]+\s+of\s+Title\s+\d+\b", re.IGNORECASE)
THIS_TITLE_SECTION_CITATION_RE = re.compile(r"\bsection\s+[\w\-.(),\sand]+\s+of\s+this\s+title\b", re.IGNORECASE)
THIS_CHAPTER_SECTION_CITATION_RE = re.compile(r"\bsection\s+[\w\-.(),\sand]+\s+of\s+this\s+chapter\b", re.IGNORECASE)
ACT_CITATION_RE = re.compile(r"\bAct\s+[A-Z][a-z]{2,9}\.?\s+\d{1,2},\s+\d{4}\b", re.IGNORECASE)
CHAPTER_STAT_CITATION_RE = re.compile(r"\bch\.?\s*\d+[A-Za-z\-]*,\s*\d+\s+Stat\.?\s+\d+\b", re.IGNORECASE)

# US Code titles mapping
US_CODE_TITLES = {
    "1": "General Provisions",
    "2": "The Congress",
    "3": "The President",
    "4": "Flag and Seal, Seat of Government, and the States",
    "5": "Government Organization and Employees",
    "6": "Domestic Security",
    "7": "Agriculture",
    "8": "Aliens and Nationality",
    "9": "Arbitration",
    "10": "Armed Forces",
    "11": "Bankruptcy",
    "12": "Banks and Banking",
    "13": "Census",
    "14": "Coast Guard",
    "15": "Commerce and Trade",
    "16": "Conservation",
    "17": "Copyrights",
    "18": "Crimes and Criminal Procedure",
    "19": "Customs Duties",
    "20": "Education",
    "21": "Food and Drugs",
    "22": "Foreign Relations and Intercourse",
    "23": "Highways",
    "24": "Hospitals and Asylums",
    "25": "Indians",
    "26": "Internal Revenue Code",
    "27": "Intoxicating Liquors",
    "28": "Judiciary and Judicial Procedure",
    "29": "Labor",
    "30": "Mineral Lands and Mining",
    "31": "Money and Finance",
    "32": "National Guard",
    "33": "Navigation and Navigable Waters",
    "34": "Crime Control and Law Enforcement",
    "35": "Patents",
    "36": "Patriotic and National Observances, Ceremonies, and Organizations",
    "37": "Pay and Allowances of the Uniformed Services",
    "38": "Veterans' Benefits",
    "39": "Postal Service",
    "40": "Public Buildings, Property, and Works",
    "41": "Public Contracts",
    "42": "The Public Health and Welfare",
    "43": "Public Lands",
    "44": "Public Printing and Documents",
    "45": "Railroads",
    "46": "Shipping",
    "47": "Telecommunications",
    "48": "Territories and Insular Possessions",
    "49": "Transportation",
    "50": "War and National Defense",
    "51": "National and Commercial Space Programs",
    "52": "Voting and Elections",
    "54": "National Park Service and Related Programs",
}


def _title_sort_key(title: str) -> int:
    try:
        return int(str(title))
    except Exception:
        return 10**9


def _normalize_titles(titles: Optional[List[str]]) -> List[str]:
    if titles is None or "all" in [str(t).lower() for t in titles]:
        return sorted(list(US_CODE_TITLES.keys()), key=_title_sort_key)
    out: List[str] = []
    for value in titles:
        key = str(value).strip()
        if key in US_CODE_TITLES:
            out.append(key)
    return sorted(list(dict.fromkeys(out)), key=_title_sort_key)


def _make_session() -> "requests.Session":
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "application/zip, text/html, application/xhtml+xml;q=0.9, */*;q=0.8",
        }
    )
    return session


def _govinfo_zip_url(year: int, title_num: str) -> str:
    return (
        f"https://www.govinfo.gov/content/pkg/USCODE-{int(year)}-title{title_num}/"
        f"zip/USCODE-{int(year)}-title{title_num}.zip"
    )


def _govinfo_section_url(year: int, title_num: str, html_name: str) -> str:
    return (
        f"https://www.govinfo.gov/content/pkg/USCODE-{int(year)}-title{title_num}/"
        f"html/{html_name}"
    )


def _discover_latest_year(session: "requests.Session") -> Optional[int]:
    current_year = datetime.now().year
    for year in range(current_year, MIN_USCODE_YEAR - 1, -1):
        probe = _govinfo_zip_url(year, "1")
        try:
            response = session.get(probe, timeout=25, stream=True)
            if int(response.status_code) != 200:
                continue
            content_type = str(response.headers.get("content-type") or "").lower()
            if "zip" not in content_type:
                continue
            chunk = response.raw.read(4)
            if chunk == b"PK\x03\x04":
                return year
        except Exception:
            continue
    return None


def _is_valid_zip_file(path: Path) -> bool:
    if not path.exists() or path.stat().st_size <= 0:
        return False
    try:
        with zipfile.ZipFile(path) as archive:
            if archive.testzip() is not None:
                return False
        return True
    except Exception:
        return False


def _download_title_zip(
    session: "requests.Session",
    *,
    year: int,
    title_num: str,
    cache_dir: Path,
    force_download: bool,
) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    out_path = cache_dir / f"USCODE-{int(year)}-title{title_num}.zip"
    if out_path.exists() and not force_download:
        if _is_valid_zip_file(out_path):
            return out_path
        try:
            out_path.unlink(missing_ok=True)
        except Exception:
            pass

    url = _govinfo_zip_url(year, title_num)
    response = session.get(url, timeout=60, stream=True)
    if int(response.status_code) != 200:
        raise RuntimeError(f"Failed to download title zip: HTTP {response.status_code} ({url})")

    tmp_path = out_path.with_suffix(out_path.suffix + ".part")
    try:
        tmp_path.unlink(missing_ok=True)
    except Exception:
        pass

    with tmp_path.open("wb") as handle:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if not chunk:
                continue
            handle.write(chunk)

    if tmp_path.stat().st_size <= 0:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise RuntimeError(f"Downloaded empty zip for title {title_num} year {year}")

    if not _is_valid_zip_file(tmp_path):
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise RuntimeError(f"Downloaded invalid zip for title {title_num} year {year}")

    tmp_path.replace(out_path)

    return out_path


def _extract_section_number_from_filename(file_name: str) -> str:
    match = re.search(r"-sec([^.]+)\.htm$", file_name, flags=re.IGNORECASE)
    if match:
        return str(match.group(1)).strip()
    return Path(file_name).stem


def _extract_sections_from_zip(
    zip_path: Path,
    *,
    year: int,
    title_num: str,
    title_name: str,
    include_metadata: bool,
) -> List[Dict[str, Any]]:
    sections: List[Dict[str, Any]] = []
    with zipfile.ZipFile(zip_path) as archive:
        names = sorted(archive.namelist())
        html_entries = [
            name
            for name in names
            if "/html/" in name and name.lower().endswith(".htm") and "-sec" in name.lower()
        ]

        for entry_name in html_entries:
            html_name = Path(entry_name).name
            raw = archive.read(entry_name)
            soup = BeautifulSoup(raw, "html.parser")

            heading_node = soup.find(["h1", "h2", "h3", "h4", "title"])
            heading = heading_node.get_text(" ", strip=True) if heading_node else html_name
            text = soup.get_text(" ", strip=True)
            subsection_text = _trim_nonstatutory_tail(text)
            section_number = _extract_section_number_from_filename(html_name)
            chapter_info = _extract_chapter_info(
                subsection_text,
                title_num=title_num,
                title_name=title_name,
                heading=heading,
            )
            section_body = _extract_section_body(subsection_text, section_number, heading)
            preamble = _extract_preamble(section_body)
            citations = _extract_citations(text, subsection_text)
            legislative_history = _extract_legislative_history(text, subsection_text)

            record: Dict[str, Any] = {
                "section_number": section_number,
                "heading": heading[:500],
                "text": text,
                "chapter": chapter_info,
                "preamble": preamble,
                "citations": citations,
                "legislative_history": legislative_history,
                "subsections": _parse_subsections(subsection_text),
            }
            record["parser_warnings"] = _validate_subsection_tree(record.get("subsections") or [])
            if include_metadata:
                record.update(
                    {
                        "title_number": title_num,
                        "title_name": title_name,
                        "year": int(year),
                        "package": f"USCODE-{int(year)}-title{title_num}",
                        "source_url": _govinfo_section_url(year, title_num, html_name),
                    }
                )
            sections.append(record)

    return sections


def _write_index_jsonl(sections: List[Dict[str, Any]], *, index_path: Path) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with index_path.open("w", encoding="utf-8") as handle:
        for item in sections:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")


def _load_index_jsonl(index_path: Path) -> List[Dict[str, Any]]:
    if not index_path.exists():
        return []
    out: List[Dict[str, Any]] = []
    with index_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if isinstance(obj, dict):
                out.append(obj)
    return out


def _norm_space(text: str) -> str:
    text = str(text or "")
    text = text.replace("\u00a0", " ")
    text = text.replace("\ufeff", "")
    text = text.replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _classify_subsec_kind(token: str, prev_kind: Optional[str]) -> str:
    if token.isdigit():
        return "numeric"

    if token.islower():
        if token in COMMON_ROMAN_LOWER and prev_kind in {"alpha_upper", "roman_lower", "roman_upper"}:
            return "roman_lower"
        if len(token) > 1 and ROMAN_LOWER_RE.match(token):
            return "roman_lower"
        return "alpha_lower"

    if token.isupper():
        if token in COMMON_ROMAN_UPPER and prev_kind in {"roman_lower", "roman_upper"}:
            return "roman_upper"
        if len(token) > 1 and ROMAN_UPPER_RE.match(token):
            return "roman_upper"
        return "alpha_upper"

    return "other"


def _subsec_level(kind: str) -> int:
    order = {
        "numeric": 1,
        "alpha_lower": 2,
        "alpha_upper": 3,
        "roman_lower": 4,
        "roman_upper": 5,
        "other": 6,
    }
    return int(order.get(kind, 6))


def _subsec_rank_map(first_kind: str) -> Dict[str, int]:
    sequence = [
        "numeric",
        "alpha_lower",
        "alpha_upper",
        "roman_lower",
        "roman_upper",
        "other",
    ]
    if first_kind in sequence:
        idx = sequence.index(first_kind)
        sequence = sequence[idx:] + sequence[:idx]
    return {kind: rank + 1 for rank, kind in enumerate(sequence)}


def _find_subsec_markers(text: str) -> List[tuple[int, int, str]]:
    markers: List[tuple[int, int, str]] = []
    for match in SUBSEC_TOKEN_RE.finditer(text):
        start = match.start()
        end = match.end()
        token = match.group(1)

        if len(token) > 6:
            continue
        if token.isdigit() and len(token) > 3:
            continue
        if token.isalpha():
            if not (token.islower() or token.isupper()):
                continue
            if len(token) > 1:
                if token.islower() and not ROMAN_LOWER_RE.match(token):
                    continue
                if token.isupper() and not ROMAN_UPPER_RE.match(token):
                    continue

        prev_ch = text[start - 1] if start > 0 else ""
        next_ch = text[end] if end < len(text) else ""

        valid_left = (start == 0) or prev_ch.isspace() or prev_ch in ";:.(["
        valid_right = (end == len(text)) or next_ch.isspace() or next_ch in "(),;:.]"
        if not (valid_left and valid_right):
            continue

        markers.append((start, end, token))
    return markers


def _parse_subsections(text: str) -> List[Dict[str, Any]]:
    text = _norm_space(text)
    markers = _find_subsec_markers(text)
    if not markers:
        return []

    items: List[Dict[str, Any]] = []
    prev_kind: Optional[str] = None
    for idx, (start, end, token) in enumerate(markers):
        next_start = markers[idx + 1][0] if idx + 1 < len(markers) else len(text)
        body = _norm_space(text[end:next_start])
        kind = _classify_subsec_kind(token, prev_kind)
        prev_kind = kind
        items.append(
            {
                "start": start,
                "end": end,
                "label": f"({token})",
                "token": token,
                "kind": kind,
                "text": body,
                "subsections": [],
            }
        )

    rank_map = _subsec_rank_map(str(items[0].get("kind") or "numeric"))
    for item in items:
        item["level"] = int(rank_map.get(str(item.get("kind") or "other"), _subsec_level("other")))

    roots: List[Dict[str, Any]] = []
    stack: List[Dict[str, Any]] = []
    prev_item: Optional[Dict[str, Any]] = None
    prev_node: Optional[Dict[str, Any]] = None

    def _is_chained(current: Dict[str, Any], previous: Optional[Dict[str, Any]]) -> bool:
        if previous is None:
            return False
        gap = text[int(previous["end"]):int(current["start"])]
        return gap.strip() == ""

    for item in items:
        level = int(item["level"])
        chained = _is_chained(item, prev_item)

        if chained and prev_node is not None:
            parent_subsections = prev_node.get("subsections", [])
        else:
            while stack and int(stack[-1]["level"]) >= level:
                stack.pop()
            parent_subsections = roots if not stack else stack[-1]["subsections"]

        existing_node: Optional[Dict[str, Any]] = None
        for sibling in reversed(parent_subsections):
            if sibling.get("label") == item["label"]:
                existing_node = sibling
                break

        if existing_node is None:
            node = {
                "label": item["label"],
                "token": item["token"],
                "kind": item["kind"],
                "text": item["text"],
                "subsections": [],
            }
            parent_subsections.append(node)
        else:
            node = existing_node
            new_text = item["text"]
            old_text = _norm_space(str(node.get("text", "")))
            if new_text:
                if not old_text:
                    node["text"] = new_text
                elif new_text not in old_text:
                    node["text"] = f"{old_text} {new_text}".strip()

        if not chained:
            stack.append({"level": level, "subsections": node["subsections"]})
        prev_item = item
        prev_node = node

    return roots


def _trim_nonstatutory_tail(text: str) -> str:
    text = _norm_space(text)
    if not text:
        return text

    cut_markers = [
        "Editorial Notes",
        "Statutory Notes and Related Subsidiaries",
        "Amendments",
        "References in Text",
    ]

    lower_text = text.lower()
    cut_at: Optional[int] = None
    for marker in cut_markers:
        idx = lower_text.find(marker.lower())
        if idx > 0:
            cut_at = idx if cut_at is None else min(cut_at, idx)

    if cut_at is None:
        return text
    return _norm_space(text[:cut_at])


def _dedupe_keep_order(items: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for item in items:
        value = _norm_space(item)
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _extract_chapter_info(
    text: str,
    *,
    title_num: str,
    title_name: str,
    heading: str,
) -> Dict[str, Any]:
    source = str(text or "")

    for pattern in (CHAPTER_RE, SUBCHAPTER_RE, PART_RE):
        match = pattern.search(source)
        if match:
            chapter_label = _norm_space(match.group(1)).upper()
            chapter_name = _norm_space(match.group(2))
            if chapter_name:
                return {
                    "chapter_label": chapter_label,
                    "chapter_name": chapter_name,
                    "chapter_inferred": False,
                }

    heading_text = _norm_space(heading)
    heading_match = re.search(r"\b(CHAPTER\s+[A-Z0-9\-]+)\b", heading_text, flags=re.IGNORECASE)
    if heading_match:
        return {
            "chapter_label": _norm_space(heading_match.group(1)).upper(),
            "chapter_name": heading_text,
            "chapter_inferred": True,
        }

    return {
        "chapter_label": f"TITLE {str(title_num).strip()}",
        "chapter_name": _norm_space(title_name),
        "chapter_inferred": True,
    }


def _extract_section_body(text: str, section_number: str, heading: str) -> str:
    core = _trim_nonstatutory_tail(text)
    section_patterns = [
        rf"§\s*{re.escape(section_number)}\.?\s*",
        rf"Sec\.\s*{re.escape(section_number)}\s*-\s*",
    ]

    body = core
    for pattern in section_patterns:
        match = re.search(pattern, core, flags=re.IGNORECASE)
        if match:
            body = core[match.end():]
            break

    heading_clean = _norm_space(heading)
    if heading_clean and body.lower().startswith(heading_clean.lower()):
        body = body[len(heading_clean):].lstrip(" -:;,.\t")

    return _norm_space(body)


def _extract_preamble(section_body: str) -> str:
    text = _norm_space(section_body)
    if not text:
        return ""

    markers = _find_subsec_markers(text)
    if markers and int(markers[0][0]) > 0:
        return _norm_space(text[: int(markers[0][0])])

    sentence_match = re.match(r"(.{1,500}?[\.;:])(\s|$)", text)
    if sentence_match:
        return _norm_space(sentence_match.group(1))
    return _norm_space(text[:500])


def _extract_citations(text: str, core_text: str = "") -> Dict[str, List[str]]:
    base = str(text or "")
    core = str(core_text or "") or base
    public_laws = _dedupe_keep_order(
        PUBLIC_LAW_CITATION_RE.findall(base)
        + PUBLIC_LAW_LONGFORM_RE.findall(base)
        + PUBLIC_LAW_CONGRESS_RE.findall(base)
    )
    statutes_at_large = _dedupe_keep_order(STAT_CITATION_RE.findall(base))
    usc_citations = _dedupe_keep_order(
        USC_CITATION_RE.findall(core)
        + TITLE_SECTION_CITATION_RE.findall(core)
        + THIS_TITLE_SECTION_CITATION_RE.findall(core)
        + THIS_CHAPTER_SECTION_CITATION_RE.findall(core)
    )
    usc_citations = [
        item
        for item in usc_citations
        if "united states code" not in item.lower()
        and "u.s.c. title" not in item.lower()
    ]
    session_laws = _dedupe_keep_order(ACT_CITATION_RE.findall(base) + CHAPTER_STAT_CITATION_RE.findall(base))
    if not public_laws:
        public_laws = _dedupe_keep_order(session_laws + statutes_at_large)
    return {
        "public_laws": public_laws,
        "statutes_at_large": statutes_at_large,
        "usc_citations": usc_citations,
        "session_laws": session_laws,
    }


def _extract_legislative_history(full_text: str, core_text: str) -> Dict[str, Any]:
    enactment_blocks: List[str] = []
    for match in re.finditer(r"\(([^)]{3,1800})\)", core_text):
        block = _norm_space(match.group(1))
        if not block:
            continue
        if re.search(r"(Pub\.?\s*L\.?|\b\d+\s+Stat\.?\s+\d+\b|\bch\.\s*\d+)", block, flags=re.IGNORECASE):
            enactment_blocks.append(block)

    nonparen_pattern = re.compile(
        r"([^.;]{0,160}(?:Pub\.?\s*L\.?\s*\d+[–-]\d+|\b\d+\s+Stat\.?\s+\d+\b|Act\s+[A-Z][a-z]{2,9}\.?\s+\d{1,2},\s+\d{4})[^.;]{0,260}[.;]?)",
        re.IGNORECASE,
    )
    for match in nonparen_pattern.finditer(str(core_text or "")):
        block = _norm_space(match.group(1))
        if block:
            enactment_blocks.append(block)

    editorial_excerpt = ""
    editorial_idx = str(full_text or "").find("Editorial Notes")
    if editorial_idx >= 0:
        editorial_excerpt = _norm_space(str(full_text or "")[editorial_idx: editorial_idx + 3000])

    amendment_mentions = []
    if editorial_excerpt:
        amendment_mentions = _dedupe_keep_order(
            PUBLIC_LAW_CITATION_RE.findall(editorial_excerpt)
            + PUBLIC_LAW_LONGFORM_RE.findall(editorial_excerpt)
            + PUBLIC_LAW_CONGRESS_RE.findall(editorial_excerpt)
        )

    return {
        "enactment_citation_blocks": _dedupe_keep_order(enactment_blocks),
        "amendment_public_laws": amendment_mentions,
        "editorial_notes_excerpt": editorial_excerpt,
    }


def _validate_subsection_tree(nodes: List[Dict[str, Any]], *, max_depth: int = 6) -> List[str]:
    issues: List[str] = []

    def walk(siblings: List[Dict[str, Any]], depth: int, path: str) -> None:
        if depth > max_depth:
            issues.append(f"depth>{max_depth} at {path or 'root'}")

        seen_labels: Dict[str, int] = {}
        for index, node in enumerate(siblings, start=1):
            label = str(node.get("label", ""))
            kind = str(node.get("kind", ""))
            text = _norm_space(str(node.get("text", "")))
            children = node.get("subsections", [])

            if label:
                seen_labels[label] = seen_labels.get(label, 0) + 1
                if seen_labels[label] > 1:
                    issues.append(f"duplicate sibling label {label} at {path or 'root'}")

            if not text and not children:
                issues.append(f"empty leaf node {label or '#'+str(index)} at {path or 'root'}")

            if kind not in {"numeric", "alpha_lower", "alpha_upper", "roman_lower", "roman_upper", "other"}:
                issues.append(f"unknown kind {kind} for {label or '#'+str(index)}")

            child_path = f"{path}/{label}" if path else label
            if isinstance(children, list) and children:
                walk(children, depth + 1, child_path)

    walk(nodes, depth=1, path="")
    return sorted(set(issues))


def _build_section_jsonld(section: Dict[str, Any]) -> Dict[str, Any]:
    title_number = str(section.get("title_number") or "")
    section_number = str(section.get("section_number") or "")
    year_value = section.get("year")
    source_url = str(section.get("source_url") or "")
    title_name = str(section.get("title_name") or "")
    heading = str(section.get("heading") or "")
    text = str(section.get("text") or "")
    chapter = section.get("chapter") or {}
    preamble = str(section.get("preamble") or "")
    citations = section.get("citations") or {}
    legislative_history = section.get("legislative_history") or {}
    subsections = section.get("subsections") or []
    parser_warnings = section.get("parser_warnings") or []

    return {
        "@context": {
            "@vocab": "https://schema.org/",
            "usc": "https://uscode.house.gov/",
            "titleNumber": "usc:titleNumber",
            "sectionNumber": "usc:sectionNumber",
            "sourceUrl": "usc:sourceUrl",
        },
        "@type": "Legislation",
        "@id": f"urn:uscode:title:{title_number}:section:{section_number}:year:{year_value}",
        "name": heading or f"Title {title_number} Section {section_number}",
        "isPartOf": {
            "@type": "CreativeWork",
            "name": f"United States Code Title {title_number}",
            "identifier": f"USC-{title_number}",
        },
        "legislationType": "statute",
        "titleNumber": title_number,
        "titleName": title_name,
        "sectionNumber": section_number,
        "dateModified": str(year_value) if year_value is not None else None,
        "sourceUrl": source_url,
        "chapter": chapter,
        "preamble": preamble,
        "citations": citations,
        "legislativeHistory": legislative_history,
        "text": text,
        "subsections": subsections,
        "parser_warnings": parser_warnings,
    }


def _write_title_jsonld(
    *,
    title_number: str,
    year: Optional[int],
    sections: List[Dict[str, Any]],
    output_root: Path,
) -> Path:
    jsonld_dir = output_root / DEFAULT_USCODE_JSONLD_DIRNAME
    jsonld_dir.mkdir(parents=True, exist_ok=True)
    year_part = str(year) if year is not None else "unknown"
    out_path = jsonld_dir / f"USCODE-{year_part}-title{title_number}.jsonld"

    with out_path.open("w", encoding="utf-8") as handle:
        for section in sections:
            record = _build_section_jsonld(section)
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return out_path


def _resolve_output_dir(output_dir: Optional[str] = None) -> Path:
    if output_dir:
        return Path(output_dir).expanduser().resolve()
    return DEFAULT_USCODE_INDEX_DIR


async def fetch_us_code_title(
    title_num: str,
    title_name: str,
    include_metadata: bool = True,
    rate_limit_delay: float = 1.0,
    year: Optional[int] = None,
    cache_dir: Optional[Path] = None,
    force_download: bool = False,
    keep_zip_cache: bool = False,
) -> Dict[str, Any]:
    """Fetch a US Code title from GovInfo package ZIP content.
    
    Args:
        title_num: Title number (e.g., "18")
        title_name: Title name (e.g., "Crimes and Criminal Procedure")
        include_metadata: Include metadata like effective dates
        rate_limit_delay: Delay between requests
        
    Returns:
        Dict with title data and sections
    """
    if not REQUESTS_AVAILABLE:
        return {
            "title_number": title_num,
            "title_name": title_name,
            "source": "US Code",
            "source_url": "https://www.govinfo.gov/",
            "scraped_at": datetime.now().isoformat(),
            "error": "Required libraries unavailable: install requests and beautifulsoup4",
            "sections": [],
        }

    cache_root = Path(cache_dir) if cache_dir is not None else DEFAULT_USCODE_CACHE_DIR
    try:
        session = _make_session()
        selected_year = int(year) if year is not None else _discover_latest_year(session)
        if selected_year is None:
            raise RuntimeError("Unable to discover an available USCODE package year")

        zip_path = _download_title_zip(
            session,
            year=selected_year,
            title_num=title_num,
            cache_dir=cache_root / str(selected_year),
            force_download=bool(force_download),
        )
        sections = _extract_sections_from_zip(
            zip_path,
            year=selected_year,
            title_num=title_num,
            title_name=title_name,
            include_metadata=include_metadata,
        )

        if not keep_zip_cache:
            try:
                zip_path.unlink(missing_ok=True)
            except Exception:
                pass

        await anyio.sleep(max(0.0, float(rate_limit_delay)))
        return {
            "title_number": title_num,
            "title_name": title_name,
            "source": "US Code (GovInfo package ZIP)",
            "source_url": _govinfo_zip_url(selected_year, title_num),
            "scraped_at": datetime.now().isoformat(),
            "year": selected_year,
            "zip_path": str(zip_path),
            "sections": sections,
        }
    except Exception as e:
        logger.error("Failed to fetch title %s: %s", title_num, e)
        return {
            "title_number": title_num,
            "title_name": title_name,
            "source": "US Code",
            "source_url": "https://www.govinfo.gov/",
            "scraped_at": datetime.now().isoformat(),
            "error": str(e),
            "sections": [],
        }


async def search_us_code(
    query: str,
    titles: Optional[List[str]] = None,
    max_results: int = 100,
    limit: Optional[int] = None,  # Alias for max_results
    index_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Search US Code for sections matching a query.
    
    Args:
        query: Search query string
        titles: Optional list of title numbers to search within
        max_results: Maximum number of results to return
        limit: Alias for max_results (for compatibility)
        
    Returns:
        Dict with search results
    """
    if limit is not None:
        max_results = limit

    try:
        query_text = str(query or "").strip().lower()
        if not query_text:
            return {
                "status": "error",
                "error": "Query must be non-empty",
                "results": [],
            }

        title_filter = set(_normalize_titles(titles)) if titles else None
        resolved_index_path = Path(index_path).expanduser().resolve() if index_path else DEFAULT_USCODE_INDEX_PATH
        rows = _load_index_jsonl(resolved_index_path)
        if not rows:
            return {
                "status": "error",
                "error": "No local US Code index found. Run scrape_us_code() first.",
                "results": [],
            }

        results: List[Dict[str, Any]] = []
        for row in rows:
            title_num = str(row.get("title_number") or "").strip()
            if title_filter and title_num not in title_filter:
                continue

            heading = str(row.get("heading") or "")
            text = str(row.get("text") or "")
            haystack = f"{heading}\n{text}".lower()
            if query_text not in haystack:
                continue

            idx = haystack.find(query_text)
            lo = max(0, idx - 200)
            hi = min(len(text), lo + 500)
            snippet = text[lo:hi].strip() if text else heading[:500]

            results.append(
                {
                    "title_number": title_num,
                    "title_name": row.get("title_name"),
                    "section_number": row.get("section_number"),
                    "title": f"Title {title_num} § {row.get('section_number')}",
                    "snippet": snippet,
                    "url": row.get("source_url", ""),
                    "year": row.get("year"),
                }
            )
            if len(results) >= int(max_results):
                break

        return {
            "status": "success",
            "query": query,
            "results": results,
            "count": len(results),
            "index_path": str(resolved_index_path),
        }
    except Exception as e:
        logger.error("US Code search failed: %s", e)
        return {
            "status": "error",
            "error": str(e),
            "results": [],
        }


async def get_us_code_titles() -> Dict[str, Any]:
    """Get list of all US Code titles.
    
    Returns:
        Dict containing:
            - status: "success" or "error"
            - titles: Dictionary mapping title numbers to names
            - count: Number of titles
            - error: Error message (if failed)
    """
    try:
        return {
            "status": "success",
            "titles": US_CODE_TITLES,
            "count": len(US_CODE_TITLES),
            "source": "US Code - GovInfo package titles"
        }
    except Exception as e:
        logger.error(f"Failed to get US Code titles: {e}")
        return {
            "status": "error",
            "error": str(e),
            "titles": {},
            "count": 0
        }


async def scrape_us_code(
    titles: Optional[List[str]] = None,
    output_format: str = "json",
    include_metadata: bool = True,
    rate_limit_delay: float = 1.0,
    max_sections: Optional[int] = None,
    year: Optional[int] = None,
    cache_dir: Optional[str] = None,
    force_download: bool = False,
    output_dir: Optional[str] = None,
    keep_zip_cache: bool = False,
) -> Dict[str, Any]:
    """Scrape US Code sections and build a structured dataset.
    
    Args:
        titles: List of title numbers to scrape (e.g., ["1", "15", "18"]). 
                If None or ["all"], scrapes all titles.
        output_format: Output format - "json" or "parquet"
        include_metadata: Include section metadata (effective dates, amendments, etc.)
        rate_limit_delay: Delay between requests in seconds (default 1.0)
        max_sections: Maximum number of sections to scrape (for testing/limiting)
    
    Returns:
        Dict containing:
            - status: "success" or "error"
            - data: Scraped US Code sections
            - metadata: Scraping metadata (titles, count, timing)
            - output_format: Format of the data
            - error: Error message (if failed)
    """
    try:
        selected_titles = _normalize_titles(titles)
        if not selected_titles:
            return {
                "status": "error",
                "error": "No valid titles specified",
                "data": [],
                "metadata": {},
            }

        logger.info("Starting US Code scraping for titles: %s", selected_titles)
        start_time = time.time()

        if not REQUESTS_AVAILABLE:
            return {
                "status": "error",
                "error": "Required libraries unavailable: install requests and beautifulsoup4",
                "data": [],
                "metadata": {},
            }

        output_root = _resolve_output_dir(output_dir)
        output_root.mkdir(parents=True, exist_ok=True)
        cache_root = Path(cache_dir).expanduser().resolve() if cache_dir else (output_root / "cache")
        index_path = output_root / "uscode_index_latest.jsonl"
        jsonld_paths: List[str] = []
        scraped_titles: List[Dict[str, Any]] = []
        sections_count = 0

        for title_num in selected_titles:
            if max_sections and sections_count >= max_sections:
                logger.info("Reached max_sections limit of %s", max_sections)
                break

            title_name = US_CODE_TITLES[title_num]
            logger.info("Scraping Title %s: %s", title_num, title_name)

            title_data = await fetch_us_code_title(
                title_num,
                title_name,
                include_metadata=include_metadata,
                rate_limit_delay=rate_limit_delay,
                year=year,
                cache_dir=cache_root,
                force_download=force_download,
                keep_zip_cache=keep_zip_cache,
            )

            sections = list(title_data.get("sections") or []) if isinstance(title_data, dict) else []
            if max_sections is not None and sections:
                remaining = int(max_sections) - int(sections_count)
                if remaining <= 0:
                    sections = []
                elif len(sections) > remaining:
                    sections = sections[:remaining]
                    title_data["sections"] = sections

            if sections:
                jsonld_path = _write_title_jsonld(
                    title_number=title_num,
                    year=title_data.get("year"),
                    sections=sections,
                    output_root=output_root,
                )
                title_data["jsonld_path"] = str(jsonld_path)
                jsonld_paths.append(str(jsonld_path))
                scraped_titles.append(title_data)
                sections_count += len(sections)

        elapsed_time = time.time() - start_time

        flat_sections: List[Dict[str, Any]] = []
        for title_blob in scraped_titles:
            title_num = str(title_blob.get("title_number") or "")
            title_name = str(title_blob.get("title_name") or US_CODE_TITLES.get(title_num, ""))
            year_value = title_blob.get("year")
            for section in title_blob.get("sections") or []:
                if not isinstance(section, dict):
                    continue
                row = dict(section)
                row.setdefault("title_number", title_num)
                row.setdefault("title_name", title_name)
                row.setdefault("year", year_value)
                flat_sections.append(row)

        _write_index_jsonl(flat_sections, index_path=index_path)

        effective_year = None
        if scraped_titles:
            effective_year = scraped_titles[0].get("year")

        metadata = {
            "titles_scraped": selected_titles,
            "titles_count": len(scraped_titles),
            "sections_count": sections_count,
            "elapsed_time_seconds": elapsed_time,
            "scraped_at": datetime.now().isoformat(),
            "source": "GovInfo USCODE package ZIP",
            "rate_limit_delay": rate_limit_delay,
            "include_metadata": include_metadata,
            "year": effective_year,
            "cache_dir": str(cache_root),
            "index_path": str(index_path),
            "output_dir": str(output_root),
            "force_download": bool(force_download),
            "keep_zip_cache": bool(keep_zip_cache),
            "jsonld_dir": str(output_root / DEFAULT_USCODE_JSONLD_DIRNAME),
            "jsonld_files": jsonld_paths,
        }

        logger.info("Completed US Code scraping: %s sections in %.2fs", sections_count, elapsed_time)

        return {
            "status": "success",
            "data": scraped_titles,
            "metadata": metadata,
            "output_format": output_format,
            "note": "Comprehensive title-package ingestion from GovInfo USCODE ZIP sources."
        }

    except Exception as e:
        logger.error("US Code scraping failed: %s", e)
        return {
            "status": "error",
            "error": str(e),
            "data": [],
            "metadata": {},
        }


__all__ = [
    "get_us_code_titles",
    "scrape_us_code",
    "search_us_code",
    "fetch_us_code_title",
]
