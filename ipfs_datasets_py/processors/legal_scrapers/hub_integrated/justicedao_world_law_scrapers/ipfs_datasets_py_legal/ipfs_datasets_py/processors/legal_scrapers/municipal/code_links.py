"""Find statute and ordinance links on municipal homepages.

The seed stores each place's official website. In France, Germany, Italy,
and Spain that website is almost always the place's own domain, so the code
text is a linked page rather than a shared host like Municode. This module
fetches a homepage and keeps links whose text or path names a local code.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Mapping, Sequence

USER_AGENT = (
    "JusticeDAO-MunicipalSeed/1.0 "
    "(+https://huggingface.co/datasets/endomorphosis/american_municipal_law)"
)

# Path or anchor fragments that name a local code, regulation, or notice board.
CODE_KEYWORDS: dict[str, tuple[str, ...]] = {
    # Phrases, not the bare words. "règlement" also matches dérèglement and
    # réglementation, and a bare "arrêté" matches prefectural orders.
    "FR": (
        "actes administratifs",
        "actes-administratifs",
        "actes reglementaires",
        "recueil des actes",
        "arretes municipaux",
        "arrete municipal",
        "arretes du maire",
        "arrete du maire",
        "deliberation",
        "reglement municipal",
        "reglements municipaux",
        "reglement interieur",
    ),
    "DE": (
        "satzung",
        "ortsrecht",
        "hauptsatzung",
        "bekanntmachung",
        "amtsblatt",
    ),
    "IT": (
        "statuto",
        "regolamento",
        "albo pretorio",
        "albo-pretorio",
        "albopretorio",
    ),
    "ES": (
        "ordenanza",
        "ordenances",
        "reglamento",
        "normativa municipal",
        "sede electronica",
    ),
}

# Longer suffixes first so halleyegov.it wins over halley.it.
_VENDOR_PAIRS: tuple[tuple[str, str], ...] = (
    ("trasparenza-valutazione-merito.it", "trasparenza"),
    ("servizipubblicaamministrazione.it", "saturnweb"),
    ("albotelematico.tn.it", "albotelematico"),
    ("verwaltungsportal.de", "verwaltungsportal"),
    ("sedelectronica.es", "sedelectronica"),
    ("tinnvision.cloud", "tinnvision"),
    ("hypersicapp.net", "hypersic"),
    ("soluzionipa.it", "soluzionipa"),
    ("halleyegov.it", "halley"),
    ("halleyweb.com", "halley"),
    ("parsec326.it", "parsec"),
    ("dgegovpa.it", "dgegovpa"),
    ("studiok.it", "studiok"),
    ("apkappa.it", "apkappa"),
    ("wittich.de", "wittich"),
    ("seu-e.cat", "seu-e"),
    ("halley.it", "halley"),
    ("urbi.it", "urbi"),
    ("webdelib.", "webdelib"),
)
VENDOR_HOSTS: tuple[tuple[str, str], ...] = tuple(
    sorted(_VENDOR_PAIRS, key=lambda item: len(item[0]), reverse=True)
)


def vendor_for_host(host: str) -> str:
    text = (host or "").lower()
    if text.startswith("www."):
        text = text[4:]
    for suffix, vendor in VENDOR_HOSTS:
        if text == suffix or text.endswith("." + suffix) or suffix in text:
            return vendor
    if text.startswith("sede.") or text.startswith("sedeelectronica."):
        return "sede"
    if text.startswith("albo.") or text.startswith("albopretorio.") or ".albo" in text:
        return "albo"
    return ""


FORCED_QIDS: dict[str, tuple[str, ...]] = {
    "FR": ("Q90", "Q456", "Q23482", "Q7880", "Q33959", "Q12191", "Q1735", "Q1479", "Q648"),
    "DE": ("Q64", "Q1055", "Q1726", "Q365", "Q1794", "Q1022", "Q1718", "Q2079"),
    "IT": ("Q220", "Q490", "Q2634", "Q495", "Q2656", "Q1449", "Q1891", "Q2044"),
    "ES": ("Q2807", "Q1492", "Q8818", "Q8717", "Q10305", "Q8851", "Q8692"),
}


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    stripped = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", stripped).lower()


def host_of(url: str) -> str:
    try:
        netloc = urllib.parse.urlparse(url).netloc.lower()
    except ValueError:
        return ""
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href = ""
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = ""
        for key, value in attrs:
            if key.lower() == "href" and value:
                href = value.strip()
                break
        self._href = href
        self._parts = []

    def handle_data(self, data: str) -> None:
        if self._href:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self._href:
            return
        text = re.sub(r"\s+", " ", "".join(self._parts)).strip()
        self.links.append((self._href, text))
        self._href = ""
        self._parts = []


def _keywords(country_code: str) -> tuple[str, ...]:
    return tuple(_fold(word) for word in CODE_KEYWORDS.get(country_code, ()))


def matches_code_keyword(country_code: str, url: str, text: str) -> bool:
    keywords = _keywords(country_code)
    if not keywords:
        return False
    folded = _fold(f"{url} {text}")
    return any(keyword in folded for keyword in keywords)


def code_links_from_html(html: str, page_url: str, country_code: str) -> list[dict[str, str]]:
    if not _keywords(country_code) or not html:
        return []
    parser = _LinkParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return []
    page_host = host_of(page_url)
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    for href, text in parser.links:
        lowered = href.lower()
        if lowered.startswith(("mailto:", "javascript:", "tel:", "#")):
            continue
        absolute = urllib.parse.urljoin(page_url, href)
        if not matches_code_keyword(country_code, absolute, text):
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        link_host = host_of(absolute)
        found.append(
            {
                "url": absolute,
                "text": text[:180],
                "host": link_host,
                "same_host": str(link_host == page_host).lower(),
                "vendor": vendor_for_host(link_host),
            }
        )
    return found


def _fetch(url: str, *, timeout: float = 8.0) -> tuple[int, str, str]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        final = response.geturl()
        raw = response.read(500_000)
        charset = response.headers.get_content_charset() or "utf-8"
        return int(response.status), final, raw.decode(charset, errors="replace")


def load_country_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def select_sample(rows: Sequence[Mapping[str, Any]], country_code: str, *, limit: int) -> list[dict[str, Any]]:
    forced = set(FORCED_QIDS.get(country_code, ()))
    chosen: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        qid = str(row.get("qid") or "")
        if qid in forced and row.get("source_urls") and qid not in seen:
            chosen.append(dict(row))
            seen.add(qid)
    rest = [
        row
        for row in rows
        if str(row.get("qid") or "") not in seen and row.get("source_urls")
    ]
    rest.sort(key=lambda row: str(row.get("qid") or ""))
    for row in rest:
        if len(chosen) >= limit:
            break
        digest = hashlib.sha1(str(row.get("qid") or "").encode()).hexdigest()
        if int(digest[:2], 16) % 17 == 0:
            chosen.append(dict(row))
    return chosen[:limit]


def _record_for(row: Mapping[str, Any], country_code: str) -> dict[str, Any]:
    homepage = str((row.get("source_urls") or [""])[0])
    record: dict[str, Any] = {
        "qid": row.get("qid"),
        "name": row.get("name"),
        "country_code": country_code,
        "homepage": homepage,
        "ok": False,
        "status": 0,
        "final_url": "",
        "error": "",
        "code_links": [],
    }
    try:
        status, final_url, html = _fetch(homepage)
        record["ok"] = True
        record["status"] = status
        record["final_url"] = final_url
        record["code_links"] = code_links_from_html(html, final_url or homepage, country_code)
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
    return record


def refresh_stored_links(path: Path) -> dict[str, Any]:
    """Relabel vendors on a code-host file. French rows are re-filtered.

    Germany, Italy, and Spain keep every stored link: the anchor text was
    truncated to 180 characters, so a second keyword pass could drop a real
    match. France uses phrase keywords that the first sample did not.
    """
    if not path.is_file():
        return {"path": str(path), "rows": 0, "links_before": 0, "links_after": 0, "vendor_places": {}}
    rewritten: list[dict[str, Any]] = []
    links_before = 0
    links_after = 0
    vendor_places: Counter[str] = Counter()
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            country = str(row.get("country_code") or "")
            refilter = country == "FR"
            kept: list[dict[str, Any]] = []
            for link in row.get("code_links") or []:
                links_before += 1
                url = str(link.get("url") or "")
                text = str(link.get("text") or "")
                if refilter and not matches_code_keyword(country, url, text):
                    continue
                updated = dict(link)
                host = str(updated.get("host") or host_of(url))
                updated["host"] = host
                updated["vendor"] = vendor_for_host(host)
                kept.append(updated)
            links_after += len(kept)
            names = {str(link.get("vendor")) for link in kept if link.get("vendor")}
            vendor_places.update(names)
            row["code_links"] = kept
            rewritten.append(row)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rewritten:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    temporary.replace(path)
    return {
        "path": str(path),
        "rows": len(rewritten),
        "links_before": links_before,
        "links_after": links_after,
        "vendor_places": dict(vendor_places.most_common()),
    }


def load_done_qids(path: Path) -> set[str]:
    done: set[str] = set()
    if not path.is_file():
        return done
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            qid = str(row.get("qid") or "")
            if qid:
                done.add(qid)
    return done


def scan_homepages(
    rows: Sequence[Mapping[str, Any]],
    country_code: str,
    dest: Path,
    *,
    workers: int = 6,
    delay: float = 0.15,
    limit: int | None = None,
) -> dict[str, Any]:
    """Fetch every remaining homepage and append one JSON line per place."""
    done = load_done_qids(dest)
    pending = [
        row
        for row in rows
        if row.get("source_urls") and str(row.get("qid") or "") not in done
    ]
    pending.sort(key=lambda row: str(row.get("qid") or ""))
    if limit is not None:
        pending = pending[:limit]
    dest.parent.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    counters = {"ok": 0, "with_links": 0, "vendors": Counter()}
    total = len(pending)
    print(f"{country_code} pending {total} already {len(done)}", flush=True)

    def _one(row: Mapping[str, Any]) -> dict[str, Any]:
        record = _record_for(row, country_code)
        if delay:
            time.sleep(delay)
        return record

    with dest.open("a", encoding="utf-8") as handle:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = [pool.submit(_one, row) for row in pending]
            for index, future in enumerate(as_completed(futures), start=1):
                record = future.result()
                line = json.dumps(record, ensure_ascii=False) + "\n"
                vendors = {link.get("vendor") for link in record["code_links"] if link.get("vendor")}
                with lock:
                    handle.write(line)
                    if index % 25 == 0:
                        handle.flush()
                    if record["ok"]:
                        counters["ok"] += 1
                    if record["code_links"]:
                        counters["with_links"] += 1
                    counters["vendors"].update(vendors)
                if index % 100 == 0 or index == total:
                    print(
                        f"{country_code} {index}/{total} ok={counters['ok']} links={counters['with_links']}",
                        flush=True,
                    )
    return {
        "country_code": country_code,
        "pending": total,
        "fetched_ok": counters["ok"],
        "with_code_links": counters["with_links"],
        "vendors": dict(counters["vendors"]),
        "path": str(dest),
    }


def discover_country(
    rows: Sequence[Mapping[str, Any]],
    country_code: str,
    *,
    limit: int = 36,
    delay: float = 0.4,
) -> list[dict[str, Any]]:
    sample = select_sample(rows, country_code, limit=limit)
    results: list[dict[str, Any]] = []
    for index, row in enumerate(sample, start=1):
        homepage = str((row.get("source_urls") or [""])[0])
        record: dict[str, Any] = {
            "qid": row.get("qid"),
            "name": row.get("name"),
            "country_code": country_code,
            "homepage": homepage,
            "ok": False,
            "status": 0,
            "final_url": "",
            "error": "",
            "code_links": [],
        }
        try:
            status, final_url, html = _fetch(homepage)
            record["ok"] = True
            record["status"] = status
            record["final_url"] = final_url
            record["code_links"] = code_links_from_html(html, final_url or homepage, country_code)
        except Exception as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"
        results.append(record)
        print(
            f"{country_code} {index}/{len(sample)} {row.get('name')} links={len(record['code_links'])}",
            flush=True,
        )
        time.sleep(delay)
    return results


def summarize_discoveries(results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    hosts: Counter[str] = Counter()
    same = 0
    other = 0
    ok = 0
    with_links = 0
    for row in results:
        if row.get("ok"):
            ok += 1
        links = row.get("code_links") or []
        if links:
            with_links += 1
        for link in links:
            host = str(link.get("host") or "")
            if host:
                hosts[host] += 1
            if link.get("same_host") == "true":
                same += 1
            else:
                other += 1
    return {
        "fetched_ok": ok,
        "rows": len(results),
        "with_code_links": with_links,
        "same_host_links": same,
        "other_host_links": other,
        "link_hosts": dict(hosts.most_common(30)),
    }
