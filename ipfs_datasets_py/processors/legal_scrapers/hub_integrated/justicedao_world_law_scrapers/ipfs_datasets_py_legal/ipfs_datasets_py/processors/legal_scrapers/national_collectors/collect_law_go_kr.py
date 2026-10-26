#!/usr/bin/env python3
"""Republic of Korea: in-force national 법령 from 국가법령정보센터 (law.go.kr).

Official only (ROK / not DPRK):
  https://www.law.go.kr/          국가법령정보센터 (법제처)
  https://open.law.go.kr/         Open API docs (OC key required; not used)
  https://www.moleg.go.kr/        Ministry of Government Legislation

robots.txt: User-agent:* Allow:/  Sitemap: https://law.go.kr/LSW/sitemap.xml
No OC / Open API key is used or invented. Public HTML:
  GET  /법령/{법령명}                 pretty URL (iframe -> lsiSeq)
  GET  /LSW/lsInfoP.do?lsiSeq=...  instrument chrome + hidden metadata
  POST /LSW/lsScListR.do           현행법령 목록 (법령명 검색)
  POST /LSW/lsInfoR.do             한글 본문 HTML (session cookie from lsInfoP)

On HTTP 429/403 use archive_fallbacks.fetch_with_fallbacks against official
law.go.kr / moleg.go.kr URLs (Common Crawl WARC -> Wayback replay).
Never letter-by-letter Wayback CDX. No WAF bypass, no commercial DBs.
"""
from __future__ import annotations

import json
import logging
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from html import unescape
from typing import Optional
from urllib.parse import quote

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from common import *  # noqa: F401,F403
import archive_fallbacks as af  # noqa: E402

CC = "kr"
COUNTRY = "Republic of Korea"
SOURCE_TYPE = "law_go_kr_html"
LICENSE = (
    "Official ROK legislative texts (헌법·법률·조약·명령·조례 및 규칙) are not "
    "protected by copyright (저작권법 제7조 제1호). Snapshot of 국가법령정보센터 "
    "(법제처, law.go.kr) public HTML. license: other. Not legal advice; "
    "authentic 관보 / law.go.kr text prevails."
)
UA = DEFAULT_UA + " source=https://www.law.go.kr/"
PORTAL = "https://www.law.go.kr/"
OPEN_API = "https://open.law.go.kr/"
MOLEG = "https://www.moleg.go.kr/"
LSW = "https://www.law.go.kr/LSW"
LIST_URL = (
    LSW + "/lsScListR.do?menuId=1&subMenuId=15&tabMenuId=81"
)
INFO_P = LSW + "/lsInfoP.do"
INFO_R = LSW + "/lsInfoR.do"
WARM = INFO_P + "?lsiSeq=61603&chrClsCd=010202&urlMode=lsInfoP&efYd=19880225&ancYnChk=0"
WORKERS = 4
SLEEP = 0.4
LIST_SLEEP = 0.45
OUTMAX = 50
log = logging.getLogger("kr")
_live_blocked = threading.Event()
_warm_lock = threading.Lock()

# 현행법령 검색 queries (법령명 contains). Not CDX letter-bombing.
LIST_QUERIES = ("법", "령", "규칙", "규정", "헌법")
NATIONAL_TYPES = {
    "헌법": "constitution",
    "법률": "statute",
    "대통령령": "decree",
    "총리령": "decree",
    "부령": "decree",
    "국회규칙": "regulation",
    "대법원규칙": "regulation",
    "헌법재판소규칙": "regulation",
    "중앙선거관리위원회규칙": "regulation",
    "감사원규칙": "regulation",
    "규칙": "regulation",
}
SKIP_TYPES = {"조례", "훈령", "예규", "고시", "지침", "자치법규"}
TYPE_IN_TITLE = re.compile(
    r"\[(헌법|법률|대통령령|총리령|부령|국회규칙|대법원규칙|헌법재판소규칙|"
    r"중앙선거관리위원회규칙|감사원규칙|규칙|조례)[^\]]*"
)
WIDE_RE = re.compile(
    r"lsViewWideAll\('(\d+)','(\d+)'[^>]*?title=\"([^\"]+)\"",
    re.S,
)
BL_RE = re.compile(
    r'<span class="bl"><label[^>]*>\s*([^<]+?)\s*</label>',
    re.I,
)
LAWCON_RE = re.compile(
    r'<div class="lawcon"[^>]*>([\s\S]*?)</div>',
    re.I,
)
PGROUP_RE = re.compile(
    r'<div class="pgroup"[^>]*>([\s\S]*?)</div>\s*(?=<a |<div class="pgroup"|<!-- 부칙|$)',
    re.I,
)
JO_NUM_RE = re.compile(r"제\s*(\d+)\s*조(?:의\s*(\d+))?")
ART_SPLIT_KO = re.compile(
    r"(?m)^\s*(제\s*\d+\s*조(?:의\s*\d+)?(?:\s*\([^)]{0,40}\))?)"
)
HIDDEN_RE = re.compile(
    r'<input[^>]+id=["\']([^"\']+)["\'][^>]*value=["\']([^"\']*)["\']',
    re.I,
)
HIDDEN_RE2 = re.compile(
    r'<input[^>]+value=["\']([^"\']*)["\'][^>]*id=["\']([^"\']+)["\']',
    re.I,
)


def setup():
    ensure_dirs(CC)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def pretty_url(name: str) -> str:
    name = (name or "").strip()
    return f"https://www.law.go.kr/법령/{name}"


def info_p_url(seq: str, ef: str = "") -> str:
    u = f"{INFO_P}?lsiSeq={seq}&chrClsCd=010202&urlMode=lsInfoP&ancYnChk=0"
    if ef:
        u += f"&efYd={ef}"
    return u


def dump_jsonl(path: Path, rows: list) -> None:
    atomic_write(path, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def load_jsonl(path: Path) -> list:
    if not path.exists() or path.stat().st_size < 20:
        return []
    out = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def hidden_fields(html: str) -> dict:
    vals = {}
    for m in HIDDEN_RE.finditer(html or ""):
        vals[m.group(1)] = unescape(m.group(2))
    for m in HIDDEN_RE2.finditer(html or ""):
        vals.setdefault(m.group(2), unescape(m.group(1)))
    return vals


def parse_type_title(title: str) -> tuple[str, str, str]:
    raw = unescape(title or "").replace("\xa0", " ")
    name = raw.split("\n", 1)[0].strip()
    name = re.sub(r"^\d+\.\s*", "", name)
    kind = ""
    m = TYPE_IN_TITLE.search(raw)
    if m:
        kind = m.group(1)
    if not kind:
        if "헌법" in name and "법률" not in name:
            kind = "헌법"
        elif name.endswith("법률") or name.endswith("법"):
            kind = "법률"
        elif name.endswith("시행령") or name.endswith("령"):
            kind = "대통령령"
        elif "규칙" in name:
            kind = "규칙"
    anc = ""
    am = re.search(r"제\s*(\d+)\s*호", raw)
    if am:
        anc = am.group(1)
    return name, kind, anc


def parse_list_html(html: str, query: str) -> list[dict]:
    items = []
    seen = set()
    for m in WIDE_RE.finditer(html or ""):
        seq, ef, title = m.group(1), m.group(2), m.group(3)
        if seq in seen:
            continue
        seen.add(seq)
        name, kind, anc = parse_type_title(title)
        if not name:
            continue
        if kind in SKIP_TYPES:
            continue
        items.append({
            "lsiSeq": seq,
            "efYd": ef,
            "name": name,
            "kind": kind or "법령",
            "ancNo": anc,
            "query": query,
            "url": pretty_url(name),
            "info_url": info_p_url(seq, ef),
            "source": "lsScListR",
        })
    return items


def list_post(query: str, pg: int) -> tuple[str, int]:
    if _live_blocked.is_set():
        return "", 0
    data = {
        "q": query,
        "outmax": str(OUTMAX),
        "pg": str(pg),
        "p9": "2,4",
        "p18": "0",
        "p19": "1,3",
        "fsort": "10,41,21,31",
        "section": "",
        "query": query,
    }
    try:
        time.sleep(LIST_SLEEP)
        r = get_session(UA).post(
            LIST_URL, data=data, timeout=(20, 90),
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": LSW + "/lsSc.do?menuId=1&subMenuId=15&tabMenuId=81",
                "Accept": "text/html, */*",
            },
        )
    except Exception as exc:
        log.info("list POST fail q=%s pg=%s: %s", query, pg, exc)
        return "", 0
    if r.status_code in (403, 429) or af.is_challenge(r.text or "", r.status_code):
        _live_blocked.set()
        log.info("live list blocked HTTP %s q=%s", r.status_code, query)
        return "", 0
    if r.status_code != 200 or not r.text:
        log.info("list HTTP %s q=%s pg=%s", r.status_code, query, pg)
        return "", 0
    html = r.text
    m = re.search(r'id="pageSize"[^>]*value="(\d+)"', html)
    pages = int(m.group(1)) if m else 1
    return html, pages


def seed_pretty(name: str, extra: dict) -> Optional[dict]:
    url = pretty_url(name)
    html = live_get(url)
    if not html:
        return None
    m = re.search(r"lsiSeq=(\d+)", html)
    if not m:
        return None
    seq = m.group(1)
    efm = re.search(r"efYd=(\d{8})", html)
    ef = efm.group(1) if efm else extra.get("efYd") or ""
    row = {
        "lsiSeq": seq, "efYd": ef, "name": name,
        "kind": extra.get("kind") or "", "ancNo": extra.get("ancNo") or "",
        "query": "pretty", "url": url, "info_url": info_p_url(seq, ef),
        "source": "pretty_url",
    }
    return row


def live_get(url: str) -> Optional[str]:
    if _live_blocked.is_set():
        return None
    try:
        r = http_get(url, ua=UA, sleep=SLEEP, timeout=(20, 90), retries=2,
                     headers={"Accept": "text/html, */*"})
    except Exception as exc:
        log.info("live GET fail %s: %s", url, exc)
        return None
    if r.status_code in (403, 429) or af.is_challenge(r.text or "", r.status_code):
        _live_blocked.set()
        log.info("live blocked HTTP %s %s", r.status_code, url)
        return None
    if r.status_code != 200 or not r.text:
        return None
    return r.text


def warm_session() -> None:
    s = get_session(UA)
    if getattr(s, "_kr_warm", False):
        return
    with _warm_lock:
        try:
            r = s.get(WARM, timeout=(20, 60), headers={"Accept": "text/html, */*"})
            s._kr_warm = r.status_code == 200
            if r.status_code in (403, 429):
                _live_blocked.set()
        except Exception as exc:
            log.info("warm fail: %s", exc)


def discover_live() -> list[dict]:
    items: list[dict] = []
    seen: dict[str, dict] = {}

    def add(row: dict) -> bool:
        seq = str(row.get("lsiSeq") or "")
        if not seq or seq in seen:
            if seq and row.get("kind") and not seen.get(seq, {}).get("kind"):
                seen[seq]["kind"] = row["kind"]
            return False
        seen[seq] = row
        items.append(row)
        return True

    warm_session()
    for q in LIST_QUERIES:
        if _live_blocked.is_set():
            break
        html, pages = list_post(q, 1)
        rows = parse_list_html(html, q)
        nnew = sum(1 for r in rows if add(r))
        pages = min(max(pages, 1), 180)
        log.info("list q=%s pg=1 new=%s total=%s pages=%s", q, nnew, len(items), pages)
        for pg in range(2, pages + 1):
            if _live_blocked.is_set():
                break
            html, _ = list_post(q, pg)
            rows = parse_list_html(html, q)
            nnew = sum(1 for r in rows if add(r))
            if pg % 10 == 0 or pg == pages or nnew == 0:
                log.info("list q=%s pg=%s/%s new=%s total=%s", q, pg, pages, nnew, len(items))
            if nnew == 0 and pg > 2:
                break
    for name, extra in (
        ("대한민국헌법", {"kind": "헌법", "efYd": "19880225"}),
        ("민법", {"kind": "법률"}),
        ("형법", {"kind": "법률"}),
        ("상법", {"kind": "법률"}),
        ("근로기준법", {"kind": "법률"}),
    ):
        if any(it.get("name") == name for it in items):
            continue
        row = seed_pretty(name, extra)
        if row:
            add(row)
            log.info("pretty seed %s seq=%s", name, row["lsiSeq"])
    return items


def expand_archives(items: list[dict], seen: dict) -> None:
    """ONE Wayback prefix + ONE Common Crawl prefix. Not letter-CDX."""
    log.info("archive expand unique=%s (one CC + one Wayback prefix)", len(items))
    time.sleep(8.0)
    try:
        cc_hits = af.search_common_crawl("www.law.go.kr/법령*", limit=400)
    except Exception as exc:
        log.warning("cc search: %s", exc)
        cc_hits = []
    log.info("common crawl hits=%s", len(cc_hits))
    added = 0
    for rec in cc_hits:
        orig = rec.get("original") or rec.get("url") or ""
        name = pretty_name_from_url(orig)
        if not name:
            continue
        extra = {"source": "common_crawl", "name": name, "url": pretty_url(name),
                 "kind": "", "lsiSeq": "", "efYd": "", "query": "cc",
                 "info_url": orig, "cc_record": {
                     "filename": rec.get("filename"),
                     "offset": rec.get("offset"),
                     "length": rec.get("length"),
                     "timestamp": rec.get("timestamp"),
                     "original": orig,
                 }}
        key = "name:" + name
        if key in seen or any(it.get("name") == name for it in items):
            continue
        items.append(extra)
        seen[key] = extra
        added += 1
    log.info("cc extra new=%s total=%s", added, len(items))
    time.sleep(12.0)
    try:
        recs = af.search_wayback_machine(
            "www.law.go.kr/법령/",
            match_type="prefix",
            limit=600,
            collapse="urlkey",
            filter_status="200",
            extra_filters=["mimetype:text/html"],
        )
    except Exception as exc:
        log.warning("wayback prefix: %s", exc)
        recs = []
    added_wb = 0
    for rec in recs:
        orig = rec.get("original") or ""
        name = pretty_name_from_url(orig)
        if not name:
            continue
        if any(it.get("name") == name for it in items):
            # attach ts onto existing
            for it in items:
                if it.get("name") == name and not it.get("cdx_ts"):
                    it["cdx_ts"] = rec.get("timestamp")
                    it["wayback_url"] = rec.get("wayback_url")
                    break
            continue
        row = {
            "source": "wayback_prefix", "name": name, "url": pretty_url(name),
            "kind": "", "lsiSeq": "", "efYd": "", "query": "wayback",
            "info_url": orig, "cdx_ts": rec.get("timestamp"),
            "wayback_url": rec.get("wayback_url"),
        }
        items.append(row)
        added_wb += 1
    log.info("wayback prefix new=%s hits=%s total=%s", added_wb, len(recs), len(items))


def pretty_name_from_url(url: str) -> Optional[str]:
    if not url:
        return None
    u = unescape(url).split("?")[0]
    m = re.search(r"/법령/([^/#]+)$", u)
    if not m:
        return None
    name = unescape(m.group(1))
    try:
        from urllib.parse import unquote
        name = unquote(name)
    except Exception:
        pass
    name = name.strip()
    if not name or name.lower() in {"index", "main"}:
        return None
    if len(name) > 80:
        return None
    return name


def discover() -> list[dict]:
    dest = ROOT / CC / "raw" / "catalog.jsonl"
    cached = load_jsonl(dest)
    if cached and len(cached) >= 50:
        log.info("resume catalog %s (letter-CDX will not run)", len(cached))
        return cached
    items = discover_live()
    seen = {("seq:" + it["lsiSeq"]) if it.get("lsiSeq") else ("name:" + it.get("name", "")): it
            for it in items}
    if len(items) < 200:
        expand_archives(items, seen)
    # drop 조례 if any slipped through
    items = [it for it in items if (it.get("kind") or "") not in SKIP_TYPES]
    # prefer 헌법, 법률, then decrees
    rank = {"헌법": 0, "법률": 1, "대통령령": 2, "총리령": 3, "부령": 4}
    items.sort(key=lambda x: (rank.get(x.get("kind") or "", 9), x.get("name") or ""))
    dump_jsonl(dest, items)
    log.info("catalog discovered %s", len(items))
    return items


def split_korean_articles(html: str, text: str, law_id: str, source_url: str,
                           date: Optional[str]) -> list[dict]:
    docs = []
    seen = set()
    for chunk in LAWCON_RE.findall(html or ""):
        lab_m = BL_RE.search(chunk)
        if not lab_m:
            # 전문 / chapter text without 제N조
            body = html_to_text(chunk)
            if body and "전문" in body[:12] and len(body) > 40:
                docs.append({
                    "id": f"{law_id}-preamble"[:180],
                    "title": "전문",
                    "text": body,
                    "date_filed": date,
                    "document_number": "전문",
                    "source_url": source_url,
                    "record_type": "article",
                    "article_number": "전문",
                    "law_identifier": law_id,
                    "metadata": {"text_extraction": {"source": "official", "backend": "lawcon_html"}},
                })
            continue
        heading = re.sub(r"\s+", " ", unescape(lab_m.group(1))).strip()
        body = html_to_text(chunk)
        if not body or len(body) < 8:
            continue
        jm = JO_NUM_RE.search(heading)
        if jm:
            num = f"제{jm.group(1)}조" + (f"의{jm.group(2)}" if jm.group(2) else "")
        else:
            num = heading.split("(")[0].strip() or heading[:40]
        aid = re.sub(r"[^a-z0-9가-힣]+", "-", num.lower()).strip("-")
        doc_id = f"{law_id}-{aid}"[:180]
        if doc_id in seen:
            doc_id = f"{doc_id}-{len(docs)+1}"[:180]
        seen.add(doc_id)
        docs.append({
            "id": doc_id,
            "title": heading[:200],
            "text": body,
            "date_filed": date,
            "document_number": num,
            "source_url": source_url,
            "record_type": "article",
            "article_number": num,
            "law_identifier": law_id,
            "metadata": {"text_extraction": {"source": "official", "backend": "lawcon_html"}},
        })
        if len(docs) >= 4000:
            break
    if len(docs) < 2 and text:
        alt = []
        matches = list(ART_SPLIT_KO.finditer(text))
        for i, m in enumerate(matches):
            start = m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            chunk = text[start:end].strip()
            num = re.sub(r"\s+", " ", m.group(1)).strip()
            aid = re.sub(r"[^a-z0-9가-힣]+", "-", num.lower()).strip("-")
            alt.append({
                "id": f"{law_id}-{aid}"[:180],
                "title": chunk.split("\n", 1)[0][:200],
                "text": chunk,
                "date_filed": date,
                "document_number": num,
                "source_url": source_url,
                "record_type": "article",
                "article_number": num,
                "law_identifier": law_id,
                "metadata": {"text_extraction": {"source": "official", "backend": "regex_제N조"}},
            })
            if len(alt) >= 4000:
                break
        if len(alt) > len(docs):
            docs = alt
    return docs


def post_lsinfor(seq: str, ef: str) -> tuple[Optional[str], int]:
    warm_session()
    if _live_blocked.is_set():
        return None, 0
    data = {
        "lsiSeq": seq,
        "chrClsCd": "010202",
        "efYd": ef or "",
        "ancYnChk": "0",
        "efYn": "Y",
        "nwYn": "Y",
    }
    try:
        time.sleep(SLEEP)
        r = get_session(UA).post(
            INFO_R, data=data, timeout=(20, 120),
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": info_p_url(seq, ef),
                "Accept": "text/html, */*",
            },
        )
    except Exception as exc:
        log.info("lsInfoR fail seq=%s: %s", seq, exc)
        return None, 0
    if r.status_code in (403, 429) or af.is_challenge(r.text or "", r.status_code):
        _live_blocked.set()
        log.info("lsInfoR blocked HTTP %s seq=%s", r.status_code, seq)
        return None, r.status_code
    if r.status_code != 200 or not r.text:
        return None, r.status_code
    if "기본정보 조회 실패" in r.text:
        # refresh chrome page then retry once
        live_get(info_p_url(seq, ef))
        try:
            time.sleep(SLEEP)
            r = get_session(UA).post(
                INFO_R, data=data, timeout=(20, 120),
                headers={
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": info_p_url(seq, ef),
                },
            )
        except Exception:
            return None, 0
        if r.status_code != 200 or "기본정보 조회 실패" in (r.text or ""):
            return None, r.status_code
    return r.text, r.status_code


def fetch_body(it: dict) -> tuple[Optional[str], str, dict]:
    """Return (html, method, meta)."""
    seq = str(it.get("lsiSeq") or "")
    ef = str(it.get("efYd") or "")
    name = it.get("name") or ""
    if seq and not _live_blocked.is_set():
        html, status = post_lsinfor(seq, ef)
        if html and ("lawcon" in html or "제1조" in html or "전문" in html):
            return html, "live_lsInfoR", {}
        if status in (403, 429):
            pass
    # resolve seq from pretty URL if missing
    if not seq and name and not _live_blocked.is_set():
        wrap = live_get(pretty_url(name))
        if wrap:
            m = re.search(r"lsiSeq=(\d+)", wrap)
            if m:
                seq = m.group(1)
                it["lsiSeq"] = seq
                efm = re.search(r"efYd=(\d{8})", wrap)
                if efm:
                    ef = efm.group(1)
                    it["efYd"] = ef
                html, status = post_lsinfor(seq, ef)
                if html and ("lawcon" in html or "제1조" in html):
                    return html, "live_pretty_then_lsInfoR", {}
    # 429/403 or empty -> archives of official URLs
    urls = []
    if name:
        urls.append(pretty_url(name))
    if seq:
        urls.append(info_p_url(seq, ef))
    urls.append(it.get("info_url") or it.get("url") or "")
    last_err = ""
    for url in urls:
        if not url:
            continue
        res = af.fetch_with_fallbacks(
            url,
            cc_record=it.get("cc_record"),
            wayback_ts=it.get("cdx_ts"),
            try_archive_is=False,
            try_http=not _live_blocked.is_set(),
            try_cc=bool(it.get("cc_record")),
        )
        if res.get("status") == "success" and (res.get("text") or ""):
            html = res.get("text") or ""
            if "lawcon" in html or "제1조" in html or len(html_to_text(html)) > 200:
                meta = {
                    "archive_backend": res.get("method"),
                    "wayback_url": res.get("wayback_url"),
                    "capture_timestamp": res.get("capture_timestamp"),
                    "archive_url": res.get("archive_url") or res.get("wayback_url"),
                }
                return html, "archive-of-official", meta
        last_err = (res or {}).get("error") or last_err
    return None, last_err or "empty", {}


def ident_for(it: dict, hid: dict) -> str:
    ls_id = (hid.get("lsId") or "").strip()
    seq = (it.get("lsiSeq") or hid.get("lsiSeq") or "").strip()
    if ls_id:
        return f"lsid-{ls_id}"
    if seq:
        return f"lsiseq-{seq}"
    name = it.get("name") or "unknown"
    return "name-" + re.sub(r"\s+", "", name)[:40]


def fetch_one(it: dict, done: set[str]) -> str:
    seq = str(it.get("lsiSeq") or "")
    name = it.get("name") or seq or "unknown"
    # provisional id from catalog
    prov = slug_id(CC, ident_for(it, {}))
    if prov in done:
        return "skip"
    html, method, meta = fetch_body(it)
    if not html or len(html) < 200:
        log_failure(CC, {
            "identifier": seq or name, "source_url": it.get("url") or it.get("info_url"),
            "status": "failed", "reason": method or "empty_html",
        })
        return "fail"
    hid = hidden_fields(html)
    ls_id = hid.get("lsId") or ""
    title = hid.get("lsNm") or name
    seq = hid.get("lsiSeq") or seq
    ef = hid.get("efYd") or it.get("efYd") or ""
    anc_yd = hid.get("ancYd") or ""
    anc_no = hid.get("ancNo") or it.get("ancNo") or ""
    kind = it.get("kind") or ""
    if not kind:
        _, kind, _ = parse_type_title(title)
    ident = ident_for(it, hid)
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    source_url = pretty_url(title) if title else (it.get("url") or info_p_url(seq, ef))
    text = html_to_text(html)
    # drop chrome crumbs
    text = re.sub(r"(조문체계도버튼|본문목록열림|부칙목록열림|조문체계도 팝업으로 이동)", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) < 40:
        log_failure(CC, {
            "identifier": ident, "source_url": source_url,
            "status": "failed", "reason": "empty_text",
        })
        return "fail"
    docs = split_korean_articles(html, text, rid, source_url, iso_date(ef))
    doc_type = NATIONAL_TYPES.get(kind, "statute")
    rec = base_record(
        cc=CC, country=COUNTRY, language="ko", ident=ident,
        title=title, text=text, source_url=source_url, source_type=SOURCE_TYPE,
        license_text=LICENSE, collector="kr-law-go-kr",
        eli=None, date=iso_date(ef) or iso_date(anc_yd),
        official_identifier=title,
        document_type=doc_type, law_status="current", is_current=True,
        documents=docs,
        extra_meta={
            "discovery": {
                "method": it.get("source") or "lsScListR",
                "catalog_identifier": seq or ident,
                "seed_url": LIST_URL,
                "retrieval": method,
                **{k: v for k, v in (meta or {}).items() if v},
            },
            "official_metadata": {
                "lsiSeq": seq,
                "lsId": ls_id,
                "law_name": title,
                "law_kind": kind,
                "promulgation_date": iso_date(anc_yd),
                "enforcement_date": iso_date(ef),
                "promulgation_number": anc_no,
                "chrClsCd": "010202",
            },
            "text_extraction": {
                "source": "archive-of-official" if method.startswith("archive") else "official",
                "backend": f"law_go_kr_{method}",
            },
        },
        extra_fields={
            "canonical_title": title,
            "citation": f"{title} ({kind} {('제'+anc_no+'호') if anc_no else ''})".strip(),
            "publication_date": iso_date(anc_yd),
            "effective_date": iso_date(ef),
            "status_source": "law.go.kr_현행법령_lsScListR",
            "status_confidence": "high" if method.startswith("live") else "medium",
            "languages": ["ko"],
        },
    )
    rec["id"] = rid
    write_instrument(CC, rec)
    done.add(rid)
    return "ok"


def main():
    setup()
    t0 = utcnow()
    # robots: Allow:/ — still polite
    try:
        rb = http_get("https://www.law.go.kr/robots.txt", ua=UA, sleep=0.2, retries=2)
        log.info("robots status=%s body=%s", getattr(rb, "status_code", None), (rb.text or "")[:120])
    except Exception as exc:
        log.info("robots fetch: %s", exc)
    items = discover()
    done = existing_ids(CC)
    ok = skip = fail = 0
    log.info("queue %s already_done=%s workers=%s live_blocked=%s",
             len(items), len(done), WORKERS, _live_blocked.is_set())
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = [ex.submit(fetch_one, it, done) for it in items]
        n = 0
        for fut in as_completed(futs):
            n += 1
            try:
                st = fut.result()
            except Exception as exc:
                st = "fail"
                log_failure(CC, {"status": "failed", "reason": repr(exc)})
            ok += st == "ok"
            skip += st == "skip"
            fail += st == "fail"
            if n % 25 == 0 or n == len(items):
                log.info("progress %s/%s ok=%s skip=%s fail=%s", n, len(items), ok, skip, fail)
                write_summary(
                    CC, country=COUNTRY,
                    source="국가법령정보센터 (법제처, law.go.kr) 현행법령",
                    source_urls=[PORTAL, OPEN_API, MOLEG, LIST_URL, WARM],
                    license_text=LICENSE, discovered=len(items), fetched=ok,
                    skipped=skip, failed=fail, coverage="snapshot",
                    notes="No OC key. Public HTML POST lsInfoR. Archives on 429/403.",
                    last_run=utcnow(),
                )
    n_json = len(list((ROOT / CC / "instruments").glob("*.json"))) if (ROOT / CC / "instruments").exists() else 0
    coverage = "snapshot"
    notes = (
        "ROK (not DPRK) in-force 법령 from 국가법령정보센터 public HTML. "
        "No OC/Open API key used or invented. robots.txt Allow:/. "
        "Catalog via POST lsScListR.do (현행 법령명, q in 법/령/규칙/규정/헌법). "
        "Bodies via POST lsInfoR.do after session warm. "
        "On 429/403: fetch_with_fallbacks of official law.go.kr URLs "
        "(CC WARC -> Wayback replay). One Wayback prefix www.law.go.kr/법령/ "
        "and one Common Crawl 법령* search if live catalog was thin; "
        "no letter-CDX. 조례/훈령/예규/고시 excluded. "
        f"instruments_json={n_json}. Started {t0}."
    )
    write_summary(
        CC, country=COUNTRY,
        source="국가법령정보센터 (법제처, law.go.kr) 현행법령",
        source_urls=[PORTAL, OPEN_API, MOLEG,
                     "https://www.law.go.kr/LSW/lsSc.do?menuId=1&subMenuId=15&tabMenuId=81",
                     INFO_P, INFO_R],
        license_text=LICENSE, discovered=len(items), fetched=ok,
        skipped=skip, failed=fail, coverage=coverage, notes=notes,
        last_run=utcnow(), extra=f"started {t0} live_blocked={_live_blocked.is_set()}",
    )
    (ROOT / CC / "logs" / "DONE").write_text(json.dumps({
        "ok": ok, "skip": skip, "fail": fail, "discovered": len(items),
        "coverage": coverage, "instruments": n_json,
    }, indent=2) + "\n", encoding="utf-8")
    log.info("done ok=%s skip=%s fail=%s instruments=%s", ok, skip, fail, n_json)


if __name__ == "__main__":
    main()
