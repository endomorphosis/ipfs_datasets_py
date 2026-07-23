#!/usr/bin/env python3
"""Scrape the current Portland City Code from https://www.portland.gov/code."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import re
import time
from pathlib import Path
import sys
from typing import Any, Dict, Iterable, List, Tuple
from urllib.parse import urljoin, urlparse


BASE_URL = "https://www.portland.gov/code"
USER_AGENT = "Mozilla/5.0 (compatible; HACC municipal law recovery)"
CODE_URL_RE = re.compile(r"^https://www\.portland\.gov/code/\d+(?:/[A-Za-z0-9]+){0,2}$")
TITLE_RE = re.compile(r"^https://www\.portland\.gov/code/\d+$")
CHAPTER_RE = re.compile(r"^https://www\.portland\.gov/code/\d+/[A-Za-z0-9]+$")
SECTION_RE = re.compile(r"^https://www\.portland\.gov/code/\d+/[A-Za-z0-9]+/[A-Za-z0-9]+$")
WS_RE = re.compile(r"\s+")


def _bootstrap_pythonpath() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    repo_root_str = str(repo_root)
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)


_bootstrap_pythonpath()

from ipfs_datasets_py.utils.cid_utils import cid_for_bytes, cid_for_obj  # noqa: E402


def _session():
    import requests

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def _fetch(url: str, *, timeout: int = 60, attempts: int = 3) -> str:
    last_exc: Exception | None = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            response = _session().get(url, timeout=timeout)
            response.raise_for_status()
            return response.text
        except Exception as exc:
            last_exc = exc
            if attempt >= attempts:
                break
            time.sleep(float(attempt))
    raise RuntimeError(f"Failed to fetch {url}: {last_exc}")


def _clean_url(url: str) -> str:
    parsed = urlparse(urljoin(BASE_URL, url))
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")


def _text(value: Any) -> str:
    return WS_RE.sub(" ", str(value or "")).strip()


def _code_links(html: str, base_url: str, pattern: re.Pattern[str]) -> List[Tuple[str, str]]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    links: List[Tuple[str, str]] = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        href = _clean_url(urljoin(base_url, str(anchor.get("href") or "")))
        if pattern.match(href) and href not in seen:
            seen.add(href)
            links.append((_text(anchor.get_text(" ", strip=True)), href))
    return links


def _discover_urls(*, workers: int = 8) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]], List[Tuple[str, str]], List[Dict[str, str]]]:
    root_html = _fetch(BASE_URL)
    titles = [(label, url) for label, url in _code_links(root_html, BASE_URL, TITLE_RE)]
    chapters: List[Tuple[str, str]] = []
    seen_chapters = set()
    errors: List[Dict[str, str]] = []

    def _links_for(url: str, pattern: re.Pattern[str]) -> List[Tuple[str, str]]:
        return _code_links(_fetch(url), url, pattern)

    with ThreadPoolExecutor(max_workers=max(1, int(workers))) as executor:
        future_map = {executor.submit(_links_for, title_url, CHAPTER_RE): title_url for _title_label, title_url in titles}
        for future in as_completed(future_map):
            title_url = future_map[future]
            try:
                for label, url in future.result():
                    if url not in seen_chapters:
                        seen_chapters.add(url)
                        chapters.append((label, url))
            except Exception as exc:
                errors.append({"url": title_url, "error": f"{type(exc).__name__}: {exc}"})
    chapters.sort(key=lambda item: item[1])

    sections: List[Tuple[str, str]] = []
    seen_sections = set()
    with ThreadPoolExecutor(max_workers=max(1, int(workers))) as executor:
        future_map = {executor.submit(_links_for, chapter_url, SECTION_RE): chapter_url for _chapter_label, chapter_url in chapters}
        for future in as_completed(future_map):
            chapter_url = future_map[future]
            try:
                for label, url in future.result():
                    if url not in seen_sections:
                        seen_sections.add(url)
                        sections.append((label, url))
            except Exception as exc:
                errors.append({"url": chapter_url, "error": f"{type(exc).__name__}: {exc}"})
    sections.sort(key=lambda item: item[1])
    return titles, chapters, sections, errors


def _path_parts(url: str) -> Tuple[str, str, str]:
    parts = [part for part in urlparse(url).path.split("/") if part]
    title = parts[1] if len(parts) > 1 else ""
    chapter = parts[2] if len(parts) > 2 else ""
    section = parts[3] if len(parts) > 3 else ""
    return title, chapter, section


def _extract_page(label: str, url: str) -> Dict[str, Any]:
    from bs4 import BeautifulSoup

    html = _fetch(url)
    soup = BeautifulSoup(html, "html.parser")
    title_tag = soup.find("title")
    page_title = _text(title_tag.get_text(" ", strip=True) if title_tag else label)
    h1 = soup.find("h1")
    heading = _text(h1.get_text(" ", strip=True) if h1 else label)
    article = soup.select_one("article") or soup.select_one(".node__content") or soup.select_one("main")
    text = _text(article.get_text("\n", strip=True) if article else soup.get_text("\n", strip=True))
    title_no, chapter_no, section_no = _path_parts(url)
    document_bytes = html.encode("utf-8")
    text_bytes = text.encode("utf-8")
    document_cid = cid_for_bytes(document_bytes)
    text_cid = cid_for_bytes(text_bytes)
    payload = {
        "url": url,
        "text_cid": text_cid,
        "document_cid": document_cid,
        "source": "portland.gov/code",
    }
    return {
        "ipfs_cid": cid_for_obj(payload),
        "source_cid": document_cid,
        "text_cid": text_cid,
        "document_cid": document_cid,
        "url": url,
        "title": heading or page_title,
        "text": text,
        "html": html,
        "body_mime": "text/html",
        "domain": "portland.gov",
        "place_name": "City of Portland",
        "state_code": "OR",
        "gnis": "2411471",
        "collection": "current-origin",
        "timestamp": "",
        "mime": "text/html",
        "status": 200,
        "source": "portland.gov/code",
        "title_number": title_no,
        "chapter_number": chapter_no,
        "section_number": section_no,
        "label": label,
    }


def _write_parquet(path: Path, rows: List[Dict[str, Any]]) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape current Portland City Code section pages.")
    parser.add_argument("--output-root", default="workspace/municipal_common_crawl_laws/portland_gov_code_current")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--limit", type=int, default=0, help="Optional section limit for smoke tests.")
    parser.add_argument("--include-chapters", action="store_true", help="Also scrape chapter landing pages.")
    parser.add_argument("--include-titles", action="store_true", help="Also scrape title landing pages.")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    output_root = Path(args.output_root).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    titles, chapters, sections, discovery_errors = _discover_urls(workers=max(1, int(args.workers)))
    targets: List[Tuple[str, str]] = []
    if args.include_titles:
        targets.extend(titles)
    if args.include_chapters:
        targets.extend(chapters)
    targets.extend(sections)
    if args.limit and args.limit > 0:
        targets = targets[: int(args.limit)]

    rows: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = list(discovery_errors)
    with ThreadPoolExecutor(max_workers=max(1, int(args.workers))) as executor:
        future_map = {executor.submit(_extract_page, label, url): (label, url) for label, url in targets}
        for future in as_completed(future_map):
            label, url = future_map[future]
            try:
                rows.append(future.result())
            except Exception as exc:
                errors.append({"url": url, "label": label, "error": f"{type(exc).__name__}: {exc}"})

    rows.sort(key=lambda row: (str(row.get("title_number") or ""), str(row.get("chapter_number") or ""), str(row.get("section_number") or ""), str(row.get("url") or "")))
    _write_parquet(output_root / "pages.parquet", rows)
    manifest = {
        "source": BASE_URL,
        "output_root": str(output_root),
        "pages_parquet": str(output_root / "pages.parquet"),
        "title_count": len(titles),
        "chapter_count": len(chapters),
        "section_count": len(sections),
        "target_count": len(targets),
        "row_count": len(rows),
        "error_count": len(errors),
        "errors": errors[:50],
    }
    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    if args.json:
        print(json.dumps(manifest, indent=2, ensure_ascii=False))
    else:
        print(f"Rows: {len(rows)}")
        print(f"Sections discovered: {len(sections)}")
        print(f"Errors: {len(errors)}")
        print(f"Output: {output_root / 'pages.parquet'}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
