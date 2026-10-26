"""List ordinance entries on shared municipal platforms.

Spanish sedelectronica.es towns expose ordenanzas on one shared board id.
The page is a table of document links plus a Wicket "Mostrar más" control.
Italian Saturnweb's first page is the act-type menu, not the documents.
Neither function downloads the ordinance file.
"""

from __future__ import annotations

import http.cookiejar
import json
import re
from html import unescape
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from ipfs_datasets_py.processors.legal_scrapers.municipal.code_links import (
    USER_AGENT,
    host_of,
    load_done_qids,
)

# Same board category on every sedelectronica host: Ordenanzas y reglamentos.
SEDE_BOARD_ID = "97521486-f59b-11de-b600-00237da12c6a"
SATURN_HOME = "https://www.servizipubblicaamministrazione.it/servizi/saturnweb/Home.aspx?CE={ce}"
SATURN_NOTICES = (
    "https://www.servizipubblicaamministrazione.it/servizi/saturnweb/"
    "Pubblicazioni.aspx?RicCro=1&CE={ce}"
)

Fetch = Callable[..., tuple[int, str]]

_MORE_RE = re.compile(
    r"wicketAjaxGet\('([^']+)'[\s\S]{0,400}?Mostrar m[aá]s",
    re.I,
)
_OPTION_RE = re.compile(
    r'<option[^>]*value="(-?\d+)"[^>]*>(.*?)</option>',
    re.I | re.S,
)
_CELL_FIELDS = {
    "class_foldercode": "expediente",
    "class_foldername": "procedure",
    "class_boardcategory": "category",
    "class_description": "description",
    "class_datefrom": "published",
}


def _markup(text: str) -> str:
    """Return Wicket ajax fragments, leaving a normal HTML page intact.

    Sede pages include CDATA inside scripts. Treating every CDATA block as
    the document drops the ordenanza table.
    """
    body = text or ""
    if "<ajax-response" not in body:
        return body
    parts = re.findall(r"<!\[CDATA\[(.*?)\]\]>", body, flags=re.S)
    return "\n".join(parts) if parts else body


def sede_board_url(host: str) -> str:
    text = (host or "").lower().split(":")[0]
    if text.startswith("www."):
        text = text[4:]
    return f"https://{text}/board/{SEDE_BOARD_ID}/"


def sede_more_path(html: str) -> str:
    match = _MORE_RE.search(_markup(html))
    return match.group(1) if match else ""


class _BoardParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[dict[str, str]] = []
        self._skip = 0
        self._row: dict[str, str] | None = None
        self._cell = ""
        self._cell_text: list[str] = []
        self._capture = False
        self._anchor_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self._skip += 1
            return
        if self._skip:
            return
        values = {key.lower(): value or "" for key, value in attrs}
        if tag == "tr":
            self._row = {
                "url": "",
                "title": "",
                "label": "",
                "expediente": "",
                "procedure": "",
                "category": "",
                "description": "",
                "published": "",
            }
            return
        if self._row is None:
            return
        if tag == "td":
            classes = values.get("class", "").split()
            self._cell = classes[0].lower() if classes else ""
            self._cell_text = []
        elif tag == "a" and "preview-document" in values.get("href", ""):
            self._row["url"] = values.get("href", "")
            self._row["title"] = re.sub(r"\s+", " ", values.get("title", "")).strip()
            self._capture = True
            self._anchor_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
            return
        if self._skip or self._row is None:
            return
        if tag == "a" and self._capture:
            self._row["label"] = re.sub(r"\s+", " ", "".join(self._anchor_text)).strip()
            self._capture = False
        elif tag == "td" and self._cell:
            text = re.sub(r"\s+", " ", "".join(self._cell_text)).strip()
            field = _CELL_FIELDS.get(self._cell)
            if field and text:
                self._row[field] = text
            self._cell = ""
        elif tag == "tr":
            if self._row.get("url"):
                if not self._row["title"]:
                    self._row["title"] = self._row["label"]
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._capture:
            self._anchor_text.append(data)
        if self._cell:
            self._cell_text.append(data)


def parse_sede_documents(html: str, page_url: str) -> list[dict[str, str]]:
    parser = _BoardParser()
    try:
        parser.feed(_markup(html))
        parser.close()
    except Exception:
        return []
    documents: list[dict[str, str]] = []
    for row in parser.rows:
        absolute = urllib.parse.urljoin(page_url, row["url"])
        item = dict(row)
        item["url"] = absolute
        documents.append(item)
    return documents


def parse_saturnweb_types(html: str) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    for value, raw in _OPTION_RE.findall(html or ""):
        if value in ("-1", "") or value in seen:
            continue
        name = re.sub(r"<[^>]+>", " ", raw)
        name = re.sub(r"\s+", " ", unescape(name)).strip()
        if not name:
            continue
        seen.add(value)
        found.append({"id": value, "name": name})
    return found


class _NoticeParser(HTMLParser):
    """One row of the Saturnweb chronological albo."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[dict[str, str]] = []
        self._in_row = False
        self._cell = -1
        self._cells: list[str] = []
        self._text: list[str] = []
        self._pub = ""
        self._href = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value or "" for key, value in attrs}
        if tag == "tr":
            self._in_row = True
            self._cell = -1
            self._cells = []
            self._pub = ""
            self._href = ""
            return
        if not self._in_row:
            return
        if tag == "td":
            self._cell += 1
            self._text = []
            self._cells.append("")
        elif tag == "br" and self._cell >= 0:
            self._text.append(" ")
        elif tag == "a":
            href = values.get("href", "")
            match = re.search(r"[?&]Pub=(\d+)", href, re.I)
            if match:
                self._pub = match.group(1)
                self._href = href

    def handle_data(self, data: str) -> None:
        if self._in_row and self._cell >= 0:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self._in_row and self._cell >= 0:
            self._cells[self._cell] = re.sub(r"\s+", " ", "".join(self._text)).strip()
        elif tag == "tr" and self._in_row:
            if self._pub and len(self._cells) >= 3:
                self.rows.append(
                    {
                        "pub": self._pub,
                        "href": self._href,
                        "number_cell": self._cells[0],
                        "date_cell": self._cells[1],
                        "act": self._cells[2],
                        "requester": self._cells[3] if len(self._cells) > 3 else "",
                    }
                )
            self._in_row = False


def parse_saturn_notices(html: str, page_url: str) -> list[dict[str, str]]:
    parser = _NoticeParser()
    try:
        parser.feed(html or "")
        parser.close()
    except Exception:
        return []
    notices: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in parser.rows:
        pub = row["pub"]
        if pub in seen:
            continue
        seen.add(pub)
        numbers = re.findall(r"\d+", row["number_cell"])
        dates = re.findall(r"\d{2}/\d{2}/\d{4}", row["date_cell"])
        act = row["act"]
        subject = ""
        match = re.search(r"Oggetto:\s*(.*)$", act, re.I)
        if match:
            subject = match.group(1).strip()
        notices.append(
            {
                "pub": pub,
                "url": urllib.parse.urljoin(page_url, row["href"]),
                "number": numbers[0] if numbers else "",
                "year": numbers[1] if len(numbers) > 1 else "",
                "published_from": dates[0] if dates else "",
                "published_until": dates[1] if len(dates) > 1 else "",
                "act": act,
                "subject": subject,
                "requester": row["requester"],
            }
        )
    return notices


def query_param(url: str, name: str) -> str:
    try:
        query = urllib.parse.urlparse(url).query
    except ValueError:
        return ""
    wanted = name.lower()
    for part in query.split("&"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        if key.lower() == wanted:
            return urllib.parse.unquote(value)
    return ""


def sede_targets(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    targets: list[dict[str, str]] = []
    for row in rows:
        host = ""
        for link in row.get("code_links") or []:
            if link.get("vendor") != "sedelectronica":
                continue
            host = str(link.get("host") or host_of(str(link.get("url") or "")))
            if host:
                break
        if not host:
            continue
        targets.append({"qid": str(row.get("qid") or ""), "name": str(row.get("name") or ""), "host": host})
    return targets


def saturn_targets(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    targets: list[dict[str, str]] = []
    for row in rows:
        ce = ""
        for link in row.get("code_links") or []:
            if link.get("vendor") != "saturnweb":
                continue
            ce = query_param(str(link.get("url") or ""), "ce")
            if ce:
                break
        if not ce:
            continue
        targets.append({"qid": str(row.get("qid") or ""), "name": str(row.get("name") or ""), "ce": ce})
    return targets


def list_sede_board(host: str, fetch: Fetch, *, max_pages: int = 4) -> dict[str, Any]:
    """Collect ordenanza rows. max_pages includes the first page."""
    board = sede_board_url(host)
    documents: list[dict[str, str]] = []
    seen: set[str] = set()
    status = 0
    error = ""
    pages = 0
    more = ""
    try:
        status, html = fetch(board, ajax=False)
        pages = 1
        if status >= 400 or not html:
            error = f"HTTP {status}"
        else:
            _add_documents(documents, seen, parse_sede_documents(html, board))
            more = sede_more_path(html)
            while more and pages < max_pages:
                status, fragment = fetch(urllib.parse.urljoin(board, more), ajax=True)
                pages += 1
                if status >= 400 or not fragment:
                    error = f"HTTP {status}"
                    more = ""
                    break
                added = _add_documents(documents, seen, parse_sede_documents(fragment, board))
                more = sede_more_path(fragment) if added else ""
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    return {
        "host": urllib.parse.urlparse(board).netloc,
        "board_url": board,
        "ok": bool(status) and status < 400 and not error.startswith("HTTP"),
        "status": status,
        "error": error,
        "pages": pages,
        "more_remaining": bool(more),
        "documents": documents,
    }


def list_saturn_types(ce: str, fetch: Fetch) -> dict[str, Any]:
    url = SATURN_HOME.format(ce=urllib.parse.quote(ce))
    status = 0
    error = ""
    types: list[dict[str, str]] = []
    try:
        status, html = fetch(url, ajax=False)
        if status >= 400 or not html:
            error = f"HTTP {status}"
        else:
            types = parse_saturnweb_types(html)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    return {
        "ce": ce,
        "url": url,
        "ok": bool(status) and status < 400 and not error.startswith("HTTP"),
        "status": status,
        "error": error,
        "act_types": types,
    }


def list_saturn_notices(ce: str, fetch: Fetch) -> dict[str, Any]:
    """Current albo notices. The chronological page is one list, not a search."""
    url = SATURN_NOTICES.format(ce=urllib.parse.quote(ce))
    status = 0
    error = ""
    notices: list[dict[str, str]] = []
    try:
        status, html = fetch(url, ajax=False)
        if status >= 400 or not html:
            error = f"HTTP {status}"
        else:
            notices = parse_saturn_notices(html, url)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    return {
        "ce": ce,
        "url": url,
        "ok": bool(status) and status < 400 and not error.startswith("HTTP"),
        "status": status,
        "error": error,
        "notices": notices,
    }


def _add_documents(
    documents: list[dict[str, str]],
    seen: set[str],
    found: Sequence[Mapping[str, str]],
) -> int:
    added = 0
    for item in found:
        url = str(item.get("url") or "")
        if not url or url in seen:
            continue
        seen.add(url)
        documents.append(dict(item))
        added += 1
    return added


def _http_get(opener: urllib.request.OpenerDirector, url: str, headers: Mapping[str, str]) -> tuple[int, str]:
    request = urllib.request.Request(url, headers=dict(headers))
    try:
        with opener.open(request, timeout=20) as response:
            raw = response.read(800_000)
            charset = response.headers.get_content_charset() or "utf-8"
            return int(response.status), raw.decode(charset, errors="replace")
    except urllib.error.HTTPError as exc:
        return int(exc.code), ""


def _scan(
    targets: Sequence[Mapping[str, str]],
    dest: Path,
    worker: Callable[[Mapping[str, str]], dict[str, Any]],
    *,
    workers: int,
    label: str,
) -> dict[str, Any]:
    done = load_done_qids(dest)
    pending = [dict(row) for row in targets if str(row.get("qid") or "") not in done]
    pending.sort(key=lambda row: str(row.get("qid") or ""))
    dest.parent.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    ok = 0
    with_rows = 0
    total = len(pending)
    print(f"{label} pending {total} already {len(done)}", flush=True)
    with dest.open("a", encoding="utf-8") as handle:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = [pool.submit(worker, row) for row in pending]
            for index, future in enumerate(as_completed(futures), start=1):
                record = future.result()
                line = json.dumps(record, ensure_ascii=False) + "\n"
                filled = bool(record.get("documents") or record.get("act_types") or record.get("notices"))
                with lock:
                    handle.write(line)
                    if index % 25 == 0:
                        handle.flush()
                    if record.get("ok"):
                        ok += 1
                    if filled:
                        with_rows += 1
                if index % 50 == 0 or index == total:
                    print(f"{label} {index}/{total} ok={ok} listed={with_rows}", flush=True)
    return {
        "label": label,
        "pending": total,
        "fetched_ok": ok,
        "with_rows": with_rows,
        "path": str(dest),
    }


def scan_sede_boards(
    rows: Sequence[Mapping[str, Any]],
    dest: Path,
    *,
    workers: int = 4,
    delay: float = 0.15,
    max_pages: int = 4,
    limit: int | None = None,
) -> dict[str, Any]:
    targets = sede_targets(rows)
    if limit is not None:
        targets = targets[:limit]

    def worker(target: Mapping[str, str]) -> dict[str, Any]:
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        board = sede_board_url(str(target.get("host") or ""))

        def fetch(url: str, *, ajax: bool = False) -> tuple[int, str]:
            headers = {"User-Agent": USER_AGENT, "Accept": "text/html"}
            if ajax:
                headers["Wicket-Ajax"] = "true"
                headers["Accept"] = "text/xml"
                headers["Referer"] = board
                headers["Wicket-Ajax-BaseURL"] = f"board/{SEDE_BOARD_ID}/"
            return _http_get(opener, url, headers)

        record = list_sede_board(str(target.get("host") or ""), fetch, max_pages=max_pages)
        record["qid"] = target.get("qid")
        record["name"] = target.get("name")
        record["country_code"] = "ES"
        if delay:
            time.sleep(delay)
        return record

    summary = _scan(targets, dest, worker, workers=workers, label="sede")
    summary["targets"] = len(targets)
    return summary


def scan_saturn_types(
    rows: Sequence[Mapping[str, Any]],
    dest: Path,
    *,
    workers: int = 2,
    delay: float = 0.3,
    limit: int | None = None,
) -> dict[str, Any]:
    targets = saturn_targets(rows)
    if limit is not None:
        targets = targets[:limit]

    def worker(target: Mapping[str, str]) -> dict[str, Any]:
        opener = urllib.request.build_opener()

        def fetch(url: str, *, ajax: bool = False) -> tuple[int, str]:
            del ajax
            return _http_get(opener, url, {"User-Agent": USER_AGENT, "Accept": "text/html"})

        record = list_saturn_types(str(target.get("ce") or ""), fetch)
        record["qid"] = target.get("qid")
        record["name"] = target.get("name")
        record["country_code"] = "IT"
        if delay:
            time.sleep(delay)
        return record

    # One host serves every comune, so stay at two concurrent sessions.
    summary = _scan(targets, dest, worker, workers=min(2, max(1, workers)), label="saturn")
    summary["targets"] = len(targets)
    return summary


def _sede_worker(target: Mapping[str, str], *, delay: float, max_pages: int) -> dict[str, Any]:
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    board = sede_board_url(str(target.get("host") or ""))

    def fetch(url: str, *, ajax: bool = False) -> tuple[int, str]:
        headers = {"User-Agent": USER_AGENT, "Accept": "text/html"}
        if ajax:
            headers["Wicket-Ajax"] = "true"
            headers["Accept"] = "text/xml"
            headers["Referer"] = board
            headers["Wicket-Ajax-BaseURL"] = f"board/{SEDE_BOARD_ID}/"
        return _http_get(opener, url, headers)

    record = list_sede_board(str(target.get("host") or ""), fetch, max_pages=max_pages)
    record["qid"] = target.get("qid")
    record["name"] = target.get("name")
    record["country_code"] = "ES"
    if delay:
        time.sleep(delay)
    return record


def scan_saturn_notices(
    rows: Sequence[Mapping[str, Any]],
    dest: Path,
    *,
    workers: int = 2,
    delay: float = 0.3,
    limit: int | None = None,
) -> dict[str, Any]:
    targets = saturn_targets(rows)
    if limit is not None:
        targets = targets[:limit]

    def worker(target: Mapping[str, str]) -> dict[str, Any]:
        opener = urllib.request.build_opener()

        def fetch(url: str, *, ajax: bool = False) -> tuple[int, str]:
            del ajax
            return _http_get(opener, url, {"User-Agent": USER_AGENT, "Accept": "text/html"})

        record = list_saturn_notices(str(target.get("ce") or ""), fetch)
        record["qid"] = target.get("qid")
        record["name"] = target.get("name")
        record["country_code"] = "IT"
        if delay:
            time.sleep(delay)
        return record

    summary = _scan(targets, dest, worker, workers=min(2, max(1, workers)), label="saturn-notices")
    summary["targets"] = len(targets)
    return summary


def refresh_sede_incomplete(
    path: Path,
    *,
    workers: int = 4,
    delay: float = 0.15,
    max_pages: int = 12,
) -> dict[str, Any]:
    """Refetch towns that failed or still had another board page.

    A failed retry keeps the previous row when that row had loaded.
    """
    if not path.is_file():
        return {"path": str(path), "pending": 0}
    stored: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                stored.append(json.loads(line))
    pending = [
        index
        for index, row in enumerate(stored)
        if not row.get("ok") or row.get("more_remaining")
    ]
    print(f"sede-retry pending {len(pending)}", flush=True)
    replaced = 0
    kept = 0

    def worker(index: int) -> tuple[int, dict[str, Any], bool]:
        previous = stored[index]
        record = _sede_worker(previous, delay=delay, max_pages=max_pages)
        if not record.get("ok") and previous.get("ok"):
            kept_row = dict(previous)
            kept_row["refresh_error"] = record.get("error") or f"HTTP {record.get('status')}"
            return index, kept_row, False
        return index, record, True

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(worker, index) for index in pending]
        done = 0
        total = len(pending)
        for future in as_completed(futures):
            index, record, changed = future.result()
            stored[index] = record
            done += 1
            if changed:
                replaced += 1
            else:
                kept += 1
            if done % 25 == 0 or done == total:
                print(f"sede-retry {done}/{total} replaced={replaced} kept={kept}", flush=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in stored:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    temporary.replace(path)
    summary = summarize_listed(path)
    summary["replaced"] = replaced
    summary["kept_previous"] = kept
    return summary


def summarize_listed(path: Path) -> dict[str, Any]:
    rows = 0
    ok = 0
    with_rows = 0
    documents = 0
    types = 0
    notices = 0
    more = 0
    procedures: Counter[str] = Counter()
    if not path.is_file():
        return {"path": str(path), "rows": 0}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            rows += 1
            if row.get("ok"):
                ok += 1
            docs = row.get("documents") or []
            acts = row.get("act_types") or []
            posted = row.get("notices") or []
            if docs or acts or posted:
                with_rows += 1
            documents += len(docs)
            types += len(acts)
            notices += len(posted)
            if row.get("more_remaining"):
                more += 1
            for doc in docs:
                name = str(doc.get("procedure") or "")
                if name:
                    procedures[name] += 1
    return {
        "path": str(path),
        "rows": rows,
        "ok": ok,
        "with_rows": with_rows,
        "documents": documents,
        "act_types": types,
        "notices": notices,
        "more_remaining": more,
        "procedures": dict(procedures.most_common(12)),
    }
