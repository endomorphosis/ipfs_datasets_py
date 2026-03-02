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
from typing import Any, Dict, Iterator, List, Optional
from urllib.parse import urljoin

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
DEFAULT_USCODE_DOWNLOAD_RETRIES = 4
DEFAULT_USCODE_YEAR_FALLBACKS = 8
DEFAULT_USHOUSE_RELEASE_MAX_PROBE = 220
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
DOCID_COMMENT_RE = re.compile(r"<!--\s*documentid:[^>]*-->", re.IGNORECASE)
DOCID_SECTION_KEY_RE = re.compile(r"documentid:\s*[0-9A-Za-z]+_([0-9A-Za-z._\-]+)", re.IGNORECASE)
USHOUSE_RELEASE_LINK_RE = re.compile(
    r"releasepoints/us/pl/(?P<congress>\d+)/(?P<release>[A-Za-z0-9]+)/"
    r"htm_usc(?P<title_code>[0-9]{2}[a-z]?)@(?P<tag>[0-9]+-[A-Za-z0-9]+)\\.zip",
    re.IGNORECASE,
)

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

_USHOUSE_DOWNLOAD_LINKS_BY_CODE: Optional[Dict[str, str]] = None
_USHOUSE_RELEASE_CACHE_BY_CONGRESS: Dict[int, str] = {}


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


def _ushouse_download_page_url() -> str:
    return "https://uscode.house.gov/download/download.shtml"


def _ushouse_title_code(title_num: str) -> str:
    value = str(title_num or "").strip()
    if value.isdigit():
        return f"{int(value):02d}"
    return value.lower()


def _year_to_congress(year: int) -> int:
    # 1st Congress started in 1789 and each Congress spans two years.
    return int((int(year) - 1789) // 2 + 1)


def _looks_like_zip_response(response: "requests.Response") -> bool:
    try:
        content_type = str(response.headers.get("content-type") or "").lower()
        if "zip" in content_type:
            return True
        magic = response.raw.read(4)
        return magic == b"PK\x03\x04"
    except Exception:
        return False


def _load_ushouse_download_links(session: "requests.Session") -> Dict[str, str]:
    global _USHOUSE_DOWNLOAD_LINKS_BY_CODE
    if _USHOUSE_DOWNLOAD_LINKS_BY_CODE is not None:
        return dict(_USHOUSE_DOWNLOAD_LINKS_BY_CODE)

    page_url = _ushouse_download_page_url()
    response = session.get(page_url, timeout=40)
    if int(response.status_code) != 200:
        raise RuntimeError(f"Failed to load US House download page: HTTP {response.status_code}")

    text = str(response.text or "")
    matches = list(USHOUSE_RELEASE_LINK_RE.finditer(text))
    if not matches:
        raise RuntimeError("No US House releasepoint links found on download page")

    links: Dict[str, str] = {}
    for match in matches:
        code = str(match.group("title_code") or "").lower()
        rel = str(match.group(0) or "").strip()
        if not code or not rel:
            continue
        if code not in links:
            links[code] = urljoin("https://uscode.house.gov/download/", rel)

    if not links:
        raise RuntimeError("Unable to parse US House title links")

    _USHOUSE_DOWNLOAD_LINKS_BY_CODE = dict(links)
    return dict(links)


def _discover_ushouse_release_for_congress(
    session: "requests.Session",
    congress: int,
    *,
    max_release_probe: int = DEFAULT_USHOUSE_RELEASE_MAX_PROBE,
) -> Optional[str]:
    congress_int = int(congress)
    if congress_int in _USHOUSE_RELEASE_CACHE_BY_CONGRESS:
        return _USHOUSE_RELEASE_CACHE_BY_CONGRESS[congress_int]

    probe_code = "01"
    for release in range(int(max_release_probe), 0, -1):
        release_s = str(int(release))
        url = (
            f"https://uscode.house.gov/download/releasepoints/us/pl/{congress_int}/{release_s}/"
            f"htm_usc{probe_code}@{congress_int}-{release_s}.zip"
        )
        try:
            response = session.get(url, timeout=30, stream=True)
            if int(response.status_code) != 200:
                continue
            if _looks_like_zip_response(response):
                _USHOUSE_RELEASE_CACHE_BY_CONGRESS[congress_int] = release_s
                return release_s
        except Exception:
            continue
    return None


def _ushouse_releasepoint_title_zip_url(*, congress: int, release: str, title_num: str) -> str:
    code = _ushouse_title_code(title_num)
    rel = str(release).strip()
    return (
        f"https://uscode.house.gov/download/releasepoints/us/pl/{int(congress)}/{rel}/"
        f"htm_usc{code}@{int(congress)}-{rel}.zip"
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
    max_attempts: int = DEFAULT_USCODE_DOWNLOAD_RETRIES,
) -> Path:
    url = _govinfo_zip_url(year, title_num)
    out_path = cache_dir / f"USCODE-{int(year)}-title{title_num}.zip"
    return _download_zip_from_url(
        session,
        url=url,
        out_path=out_path,
        force_download=force_download,
        max_attempts=max_attempts,
        not_found_hint=f"title {title_num} year {year}",
    )


def _download_zip_from_url(
    session: "requests.Session",
    *,
    url: str,
    out_path: Path,
    force_download: bool,
    max_attempts: int,
    not_found_hint: str,
) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists() and not force_download:
        if _is_valid_zip_file(out_path):
            return out_path
        try:
            out_path.unlink(missing_ok=True)
        except Exception:
            pass

    last_error: Optional[Exception] = None

    for attempt in range(1, max(1, int(max_attempts)) + 1):
        tmp_path = out_path.with_suffix(out_path.suffix + ".part")
        try:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass

            response = session.get(url, timeout=90, stream=True)
            status_code = int(response.status_code)
            if status_code != 200:
                if status_code == 404:
                    raise RuntimeError(f"Title zip not found (HTTP 404) for {not_found_hint}")
                raise RuntimeError(f"Failed to download title zip: HTTP {status_code} ({url})")

            with tmp_path.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    handle.write(chunk)

            if tmp_path.stat().st_size <= 0:
                raise RuntimeError(f"Downloaded empty zip for {not_found_hint}")

            if not _is_valid_zip_file(tmp_path):
                raise RuntimeError(f"Downloaded invalid zip for {not_found_hint}")

            tmp_path.replace(out_path)
            return out_path
        except Exception as exc:
            last_error = exc if isinstance(exc, Exception) else Exception(str(exc))
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass

            # 404 means this title-year package likely does not exist; fail fast for this year.
            if "HTTP 404" in str(exc):
                break

            if attempt < max(1, int(max_attempts)):
                time.sleep(min(8.0, float(attempt)))

    if last_error is not None:
        raise last_error
    raise RuntimeError(f"Failed to download title zip for {not_found_hint}")


def _download_title_zip_ushouse(
    session: "requests.Session",
    *,
    title_num: str,
    cache_dir: Path,
    force_download: bool,
    max_attempts: int = DEFAULT_USCODE_DOWNLOAD_RETRIES,
    year: Optional[int] = None,
) -> Dict[str, Any]:
    cache_dir.mkdir(parents=True, exist_ok=True)

    source_url: Optional[str] = None
    source_release: Optional[str] = None
    source_congress: Optional[int] = None

    if year is not None:
        congress = _year_to_congress(int(year))
        release = _discover_ushouse_release_for_congress(session, congress)
        if release:
            source_congress = int(congress)
            source_release = str(release)
            source_url = _ushouse_releasepoint_title_zip_url(
                congress=source_congress,
                release=source_release,
                title_num=title_num,
            )

    if not source_url:
        links = _load_ushouse_download_links(session)
        code = _ushouse_title_code(title_num).lower()
        source_url = links.get(code)
        if source_url:
            match = USHOUSE_RELEASE_LINK_RE.search(source_url)
            if match:
                source_congress = int(match.group("congress"))
                source_release = str(match.group("release"))

    if not source_url:
        raise RuntimeError(f"No US House releasepoint source URL found for title {title_num}")

    year_part = str(int(year)) if year is not None else "latest"
    out_name = f"USHOUSE-USCODE-{year_part}-title{title_num}"
    if source_congress is not None and source_release is not None:
        out_name += f"-c{source_congress}-r{source_release}"
    out_path = cache_dir / f"{out_name}.zip"

    zip_path = _download_zip_from_url(
        session,
        url=source_url,
        out_path=out_path,
        force_download=force_download,
        max_attempts=max_attempts,
        not_found_hint=f"US House releasepoint title {title_num}",
    )

    section_url_base = source_url.rsplit("/", 1)[0] if "/" in source_url else source_url
    source_package = f"USHOUSE-USCODE-{source_congress or 'latest'}-{source_release or 'latest'}-title{title_num}"

    return {
        "zip_path": zip_path,
        "source_url": source_url,
        "source_package": source_package,
        "section_url_base": section_url_base,
        "source_congress": source_congress,
        "source_release": source_release,
    }


def _candidate_years_for_title(
    session: "requests.Session",
    *,
    title_num: str,
    year: Optional[int],
    max_year_fallbacks: int,
) -> List[int]:
    """Build candidate package years for a title, newest-first."""
    if year is not None:
        return [int(year)]

    latest = _discover_latest_year(session)
    if latest is None:
        return []

    window = max(1, int(max_year_fallbacks))
    out: List[int] = []
    for y in range(int(latest), MIN_USCODE_YEAR - 1, -1):
        out.append(y)
        if len(out) >= window:
            break
    return out


def _extract_section_number_from_filename(file_name: str) -> str:
    match = re.search(r"-sec([^.]+)\.htm$", file_name, flags=re.IGNORECASE)
    if match:
        return str(match.group(1)).strip()
    return Path(file_name).stem


def _extract_section_heading(text: str, section_number: str, fallback_heading: str) -> str:
    source = _norm_space(str(text or ""))
    sec_raw = str(section_number or "").strip()
    sec_no = re.escape(sec_raw)
    if not source or not sec_no:
        return _norm_space(fallback_heading)[:500]

    def _normalize_ref(value: str) -> str:
        return re.sub(r"\s+", "", str(value or "").replace("–", "-").replace("—", "-").lower())

    sec_norm = _normalize_ref(sec_raw)

    sec_pattern = re.compile(
        rf"Sec\.\s*{sec_no}\s*-\s*(.+?)(?=\s+From\s+the\s+U\.S\.\s+Government\s+Publishing\s+Office|\s+§\s*{sec_no}\.?|\s+Editorial\s+Notes|\s+Statutory\s+Notes|$)",
        re.IGNORECASE,
    )
    sec_match = sec_pattern.search(source)
    if sec_match:
        return _norm_space(sec_match.group(1))[:500]

    secs_pattern = re.compile(
        r"Secs?\.\s*([^\-]{1,140})\s*-\s*(.+?)(?=\s+From\s+the\s+U\.S\.\s+Government\s+Publishing\s+Office|\s+§{1,2}\s|\s+Editorial\s+Notes|\s+Statutory\s+Notes|$)",
        re.IGNORECASE,
    )
    for match in secs_pattern.finditer(source):
        refs = _normalize_ref(match.group(1))
        if sec_norm and sec_norm in refs:
            return _norm_space(match.group(2))[:500]

    section_symbol_pattern = re.compile(
        rf"§\s*{sec_no}\.?\s*(.+?)(?=\s+\([a-zA-Z0-9]{{1,4}}\)\s|\s+\([A-Z][a-z]{{2,9}}\.?\s+\d{{1,2}},\s+\d{{4}}|\s+Editorial\s+Notes|\s+Statutory\s+Notes|$)",
        re.IGNORECASE,
    )
    section_symbol_match = section_symbol_pattern.search(source)
    if section_symbol_match:
        return _norm_space(section_symbol_match.group(1))[:500]

    section_symbols_pattern = re.compile(
        r"§{2}\s*([^\.]{1,140})\.\s*(.+?)(?=\s+Editorial\s+Notes|\s+Statutory\s+Notes|$)",
        re.IGNORECASE,
    )
    for match in section_symbols_pattern.finditer(source):
        refs = _normalize_ref(match.group(1))
        if sec_norm and sec_norm in refs:
            return _norm_space(match.group(2))[:500]

    return _norm_space(fallback_heading)[:500]


def _extract_section_number_and_heading(heading_text: str) -> tuple[str, str]:
    text = _norm_space(heading_text)
    if not text:
        return "", ""

    m = re.match(r"^§+\s*([0-9A-Za-z.\-]+(?:\s+to\s+[0-9A-Za-z.\-]+)?)\.?\s*(.*)$", text, re.IGNORECASE)
    if m:
        section_number = _norm_space(m.group(1)).strip()
        heading = _norm_space(m.group(2)).strip(" .")
        return section_number, heading or text

    m = re.match(r"^(?:Sec\.|SEC\.)\s*([0-9A-Za-z.\-]+)\.?\s*(.*)$", text)
    if m:
        section_number = _norm_space(m.group(1)).strip()
        heading = _norm_space(m.group(2)).strip(" .")
        return section_number, heading or text

    return "", text


def _extract_sections_from_zip(
    zip_path: Path,
    *,
    year: int,
    title_num: str,
    title_name: str,
    include_metadata: bool,
    source_package: Optional[str] = None,
    section_url_base: Optional[str] = None,
) -> List[Dict[str, Any]]:
    def _iter_documentid_chunks(html_text: str) -> Iterator[str]:
        markers = list(DOCID_COMMENT_RE.finditer(html_text))
        for idx, marker in enumerate(markers):
            start = marker.start()
            end = markers[idx + 1].start() if idx + 1 < len(markers) else len(html_text)
            if end > start:
                yield html_text[start:end]

    def _source_url_for_entry(html_name: str) -> str:
        if section_url_base:
            return f"{str(section_url_base).rstrip('/')}/{html_name}"
        return _govinfo_section_url(year, title_num, html_name)

    def _extract_consolidated_sections(html_text: str, html_name: str) -> List[Dict[str, Any]]:
        consolidated: List[Dict[str, Any]] = []
        for chunk in _iter_documentid_chunks(html_text):
            if "section-head" not in chunk:
                continue

            soup = BeautifulSoup(chunk, "html.parser")
            head = soup.find(class_=re.compile(r"\bsection-head\b", re.IGNORECASE))
            if head is None:
                continue

            heading_text = _norm_space(head.get_text(" ", strip=True))
            section_number, heading = _extract_section_number_and_heading(heading_text)
            if not section_number:
                match = DOCID_SECTION_KEY_RE.search(chunk)
                if match:
                    section_number = _norm_space(match.group(1)).strip("._-")
            if not section_number:
                continue

            body_text = _norm_space(soup.get_text(" ", strip=True))
            if not body_text:
                continue

            record: Dict[str, Any] = {
                "section_number": section_number,
                "heading": heading,
                "text": body_text,
                "body_text": body_text,
                "citations": _extract_citations(body_text),
            }
            if include_metadata:
                record.update(
                    {
                        "title_number": title_num,
                        "title_name": title_name,
                        "year": int(year),
                        "package": source_package or f"USCODE-{int(year)}-title{title_num}",
                        "source_url": _source_url_for_entry(html_name),
                    }
                )
            consolidated.append(record)
        return consolidated

    sections: List[Dict[str, Any]] = []
    with zipfile.ZipFile(zip_path) as archive:
        names = sorted(archive.namelist())
        html_entries = [
            name
            for name in names
            if name.lower().endswith((".htm", ".html")) and "-sec" in name.lower()
        ]
        if not html_entries:
            html_entries = [name for name in names if name.lower().endswith((".htm", ".html"))]

        for entry_name in html_entries:
            html_name = Path(entry_name).name
            raw = archive.read(entry_name)
            try:
                html_text = raw.decode("utf-8", errors="ignore")
            except Exception:
                html_text = str(raw)

            if "documentid:" in html_text and "section-head" in html_text and "-sec" not in html_name.lower():
                sections.extend(_extract_consolidated_sections(html_text, html_name))
                continue

            soup = BeautifulSoup(raw, "html.parser")

            text = soup.get_text(" ", strip=True)
            subsection_text = _trim_nonstatutory_tail(text)
            section_number = _extract_section_number_from_filename(html_name)
            heading_node = soup.find(["h1", "h2", "h3", "h4", "title"])
            fallback_heading = heading_node.get_text(" ", strip=True) if heading_node else html_name
            heading = _extract_section_heading(text, section_number, fallback_heading)
            chapter_info = _extract_chapter_info(
                subsection_text,
                title_num=title_num,
                title_name=title_name,
                heading=heading,
            )
            section_body = _extract_section_body(subsection_text, section_number, heading)
            preamble = _extract_preamble(section_body)
            if not preamble:
                preamble = _norm_space(heading)
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
                "subsections": _parse_subsections(section_body),
            }
            record["parser_warnings"] = _validate_subsection_tree(record.get("subsections") or [])
            if include_metadata:
                record.update(
                    {
                        "title_number": title_num,
                        "title_name": title_name,
                        "year": int(year),
                        "package": source_package or f"USCODE-{int(year)}-title{title_num}",
                        "source_url": _source_url_for_entry(html_name),
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
    max_year_fallbacks: int = DEFAULT_USCODE_YEAR_FALLBACKS,
    download_retries: int = DEFAULT_USCODE_DOWNLOAD_RETRIES,
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
        candidate_years = _candidate_years_for_title(
            session,
            title_num=title_num,
            year=year,
            max_year_fallbacks=max_year_fallbacks,
        )
        if not candidate_years:
            raise RuntimeError("Unable to discover an available USCODE package year")

        last_error = None
        tried_years: List[int] = []
        source_attempts: List[Dict[str, Any]] = []
        for selected_year in candidate_years:
            tried_years.append(int(selected_year))
            try:
                zip_path = _download_title_zip(
                    session,
                    year=selected_year,
                    title_num=title_num,
                    cache_dir=cache_root / str(selected_year),
                    force_download=bool(force_download),
                    max_attempts=download_retries,
                )
                sections = _extract_sections_from_zip(
                    zip_path,
                    year=selected_year,
                    title_num=title_num,
                    title_name=title_name,
                    include_metadata=include_metadata,
                    source_package=f"USCODE-{int(selected_year)}-title{title_num}",
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
                    "candidate_years": candidate_years,
                    "tried_years": tried_years,
                    "source_attempts": source_attempts,
                    "sections": sections,
                }
            except Exception as year_exc:
                source_attempts.append(
                    {
                        "source": "govinfo-package-zip",
                        "year": int(selected_year),
                        "status": "error",
                        "error": str(year_exc),
                    }
                )
                last_error = year_exc
                continue

        # Secondary official fallback source: U.S. House releasepoint HTM ZIP.
        try:
            target_year = int(year) if year is not None else int(candidate_years[0])
            ushouse = _download_title_zip_ushouse(
                session,
                title_num=title_num,
                cache_dir=cache_root / "ushouse",
                force_download=bool(force_download),
                max_attempts=download_retries,
                year=target_year,
            )
            us_zip_path = Path(str(ushouse.get("zip_path")))
            sections = _extract_sections_from_zip(
                us_zip_path,
                year=target_year,
                title_num=title_num,
                title_name=title_name,
                include_metadata=include_metadata,
                source_package=str(ushouse.get("source_package") or "USHOUSE-USCODE"),
                section_url_base=str(ushouse.get("section_url_base") or "").strip() or None,
            )

            if not keep_zip_cache:
                try:
                    us_zip_path.unlink(missing_ok=True)
                except Exception:
                    pass

            await anyio.sleep(max(0.0, float(rate_limit_delay)))
            source_attempts.append(
                {
                    "source": "ushouse-releasepoint-htm-zip",
                    "status": "success",
                    "source_url": ushouse.get("source_url"),
                    "source_congress": ushouse.get("source_congress"),
                    "source_release": ushouse.get("source_release"),
                }
            )
            return {
                "title_number": title_num,
                "title_name": title_name,
                "source": "US Code (US House releasepoint HTM ZIP)",
                "source_url": ushouse.get("source_url"),
                "scraped_at": datetime.now().isoformat(),
                "year": target_year,
                "zip_path": str(us_zip_path),
                "candidate_years": candidate_years,
                "tried_years": tried_years,
                "source_attempts": source_attempts,
                "sections": sections,
            }
        except Exception as ushouse_exc:
            source_attempts.append(
                {
                    "source": "ushouse-releasepoint-htm-zip",
                    "status": "error",
                    "error": str(ushouse_exc),
                }
            )
            last_error = RuntimeError(
                f"GovInfo package ZIP attempts failed ({tried_years}); "
                f"US House fallback also failed: {ushouse_exc}"
            )

        raise RuntimeError(
            f"Failed to fetch title {title_num} after trying years {tried_years}: {last_error}"
        )
    except Exception as e:
        logger.error("Failed to fetch title %s: %s", title_num, e)
        return {
            "title_number": title_num,
            "title_name": title_name,
            "source": "US Code",
            "source_url": "https://www.govinfo.gov/",
            "scraped_at": datetime.now().isoformat(),
            "error": str(e),
            "candidate_years": [],
            "tried_years": [],
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
    max_year_fallbacks: int = DEFAULT_USCODE_YEAR_FALLBACKS,
    download_retries: int = DEFAULT_USCODE_DOWNLOAD_RETRIES,
    continue_on_error: bool = True,
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
        failed_titles: List[Dict[str, Any]] = []
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
                max_year_fallbacks=max_year_fallbacks,
                download_retries=download_retries,
            )

            title_error = str(title_data.get("error") or "").strip()
            if title_error:
                failed_titles.append(
                    {
                        "title_number": title_num,
                        "title_name": title_name,
                        "error": title_error,
                        "candidate_years": title_data.get("candidate_years", []),
                        "tried_years": title_data.get("tried_years", []),
                    }
                )
                if not continue_on_error:
                    break
                continue

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
            else:
                failed_titles.append(
                    {
                        "title_number": title_num,
                        "title_name": title_name,
                        "error": "No sections extracted",
                        "candidate_years": title_data.get("candidate_years", []),
                        "tried_years": title_data.get("tried_years", []),
                    }
                )
                if not continue_on_error:
                    break

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
            "titles_requested": selected_titles,
            "titles_requested_count": len(selected_titles),
            "titles_scraped": [str(t.get("title_number")) for t in scraped_titles],
            "titles_count": len(scraped_titles),
            "failed_titles": failed_titles,
            "failed_titles_count": len(failed_titles),
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
            "max_year_fallbacks": int(max_year_fallbacks),
            "download_retries": int(download_retries),
            "continue_on_error": bool(continue_on_error),
            "jsonld_dir": str(output_root / DEFAULT_USCODE_JSONLD_DIRNAME),
            "jsonld_files": jsonld_paths,
        }

        logger.info("Completed US Code scraping: %s sections in %.2fs", sections_count, elapsed_time)

        if not scraped_titles:
            return {
                "status": "error",
                "error": "No US Code titles were successfully scraped",
                "data": scraped_titles,
                "metadata": metadata,
                "output_format": output_format,
                "note": "Comprehensive title-package ingestion from GovInfo USCODE ZIP sources.",
            }

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
