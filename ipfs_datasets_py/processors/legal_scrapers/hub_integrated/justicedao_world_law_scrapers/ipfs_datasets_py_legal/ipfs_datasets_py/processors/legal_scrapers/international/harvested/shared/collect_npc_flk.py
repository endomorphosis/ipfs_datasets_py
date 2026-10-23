#!/usr/bin/env python3
"""China (PRC): in-force national 法律 from official NPC / State Council sources.

Primary intended source is the NPC National Database of Laws and Regulations
(https://flk.npc.gov.cn/). That host's robots.txt is Disallow: / for all
user-agents (explicitly forbidding automated collection), so this collector
does not crawl flk.npc.gov.cn or wb.flk.npc.gov.cn.

Live sources actually used:
  - NPC 现行有效法律目录 PDF (npc.gov.cn)
  - NPC 权威发布 HTML (npc.gov.cn/npc/c2/c12435/)
  - gov.cn pages when a catalog title is missing from 权威发布
  - Wayback CDX of official npc.gov.cn / gov.cn URLs only as last resort
    (labeled archive-of-official)

Do not use pkulaw, lawinfochina, Westlaw China, China Law Translate, etc.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
from archive_fallbacks import (
    fetch_common_crawl_warc,
    get_wayback_content,
    search_common_crawl,
    search_wayback_machine,
)

CC = "cn"
COUNTRY = "China"
SOURCE_TYPE = "npc_qwfb"
LICENSE = (
    "Research snapshot of official PRC publications. Copyright in official "
    "documents is governed by PRC law (including Copyright Law Art. 5 on laws, "
    "regulations, state-organ documents and official translations) and the "
    "NPC / gov.cn terms of use. This snapshot does not claim CC0. license: other. "
    "Not legal advice; the official gazette / NPC text prevails."
)
UA = DEFAULT_UA + " source=http://www.npc.gov.cn/"
WORKERS = 3
SLEEP = 0.5
NPC_ROOT = "http://www.npc.gov.cn"
QWFB_INDEX = "http://www.npc.gov.cn/npc/c2/c12435/index.html"
CATALOG_PDF_URL = "http://www.npc.gov.cn/c2/c30834/202608/P020260818381779930212.pdf"
CONSTITUTION_SEEDS = [
    "https://www.gov.cn/guoqing/2018-03/22/content_5276318.htm",
    "https://www.gov.cn/zhengce/2014-03/21/content_2643049.htm",
    "http://www.npc.gov.cn/npc/c2/c12435/",
]
CDX_PREFIXES = [
    {"url": "http://www.npc.gov.cn/npc/c2/c12435/", "limit": 300, "match_type": "prefix"},
    {"url": "http://www.npc.gov.cn/", "limit": 300, "match_type": "prefix", "from_date": "19980101", "to_date": "20101231"},
    {"url": "http://www.npc.gov.cn/", "limit": 300, "match_type": "prefix", "from_date": "20110101", "to_date": "20181231"},
    {"url": "https://www.gov.cn/zhengce/", "limit": 400, "match_type": "prefix"},
    {"url": "https://www.gov.cn/gongbao/", "limit": 350, "match_type": "prefix"},
    {"url": "http://www.gov.cn/flfg/", "limit": 500, "match_type": "prefix"},
    {"url": "https://www.gov.cn/flfg/", "limit": 300, "match_type": "prefix"},
    {"url": "http://www.npc.gov.cn/wxzl/", "limit": 300, "match_type": "prefix"},
    {"url": "http://www.npc.gov.cn/wxzl/gongbao/", "limit": 700, "match_type": "prefix"},
    {"url": "http://www.npc.gov.cn/wxzl/wxzl/", "limit": 400, "match_type": "prefix"},
    {"url": "http://www.gov.cn/banshi/", "limit": 400, "match_type": "prefix"},
    {"url": "https://www.gov.cn/xinwen/", "limit": 400, "match_type": "prefix", "from_date": "20160101", "to_date": "20181231"},
    {"url": "https://www.gov.cn/xinwen/", "limit": 400, "match_type": "prefix", "from_date": "20190101", "to_date": "20221231"},
    {"url": "https://www.gov.cn/zhengce/", "limit": 400, "match_type": "prefix", "from_date": "20160101", "to_date": "20221231"},
    {"url": "http://www.gov.cn/zhengce/", "limit": 250, "match_type": "prefix"},
]
ASSET_RE = re.compile(
    r"\.(?:css|js|gif|png|jpg|jpeg|svg|woff2?|ico|map|mp4|mp3|woff)(?:$|\?)", re.I
)
LAW_PATH_RE = re.compile(
    r"(?:/c12435/|/c30834/|/kgfb/|/zhengce/|/gongbao/|/guoqing/"
    r"|/xinwen/|/wxzl/|/npc/|/banshi/|/flfg/|/content_\d|/t20\d{6}_)",
    re.I,
)
SKIP_URL_RE = re.compile(
    r"(?:flk\.npc\.gov\.cn|/index(?:_\d+)?\.html?(?:$|\?)|/robots\.txt"
    r"|/search|/css/|/js/|/images/|/pic/)",
    re.I,
)
_archive_lock = threading.Lock()
_cc_empty = 0
_cc_disabled = False


def search_cc_cached(url: str, limit: int = 6) -> list:
    global _cc_empty, _cc_disabled
    if _cc_disabled:
        return []
    try:
        hits = search_common_crawl(url, limit=limit)
    except Exception as exc:
        log.info("cc search fail %s: %s", url, exc)
        hits = []
    if hits:
        _cc_empty = 0
        return hits
    _cc_empty += 1
    if _cc_empty >= 12:
        _cc_disabled = True
        log.info("disabling Common Crawl after %s empty searches", _cc_empty)
    return []

SKIP_TITLE_RE = re.compile(
    r"(草案|审议结果|修改意见|修改情况|的说明|工作报告|任免名单|决定任免|"
    r"决定免职|主席团|会议日程|摘登|答记者问|解读|公告〔|任命名单|"
    r"代表资格|会议闭幕|新闻发布|宣传周)"
)
ART_RE = re.compile(
    r"(?:(?<=\n)|^)[ 　]*"
    r"(第[一二三四五六七八九十百千万零〇两0-9]+条(?:之[一二三四五六七八九十百0-9]+)?)"
)
ZH_HEADERS = {
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.3",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
}
log = logging.getLogger("cn")


def setup():
    ensure_dirs(CC)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def decode_cn(resp):
    if resp is None or not getattr(resp, "content", None):
        return resp
    ctype = (resp.headers.get("content-type") or "").lower()
    if "pdf" in ctype or resp.content.startswith(b"%PDF"):
        return resp
    try:
        resp.content.decode("utf-8")
        resp.encoding = "utf-8"
    except UnicodeDecodeError:
        resp.encoding = resp.apparent_encoding or "gb18030"
    return resp


def npc_get(url: str, **kw):
    headers = dict(ZH_HEADERS)
    headers.update(kw.pop("headers", {}) or {})
    resp = http_get(url, ua=UA, sleep=kw.pop("sleep", SLEEP), headers=headers, **kw)
    return decode_cn(resp)


def norm_title(s: str) -> str:
    s = (s or "").strip()
    s = html_to_text(s) if "<" in s else s
    s = s.replace("\u3000", "").replace(" ", "").replace("\n", "")
    s = s.replace("《", "").replace("》", "").replace("〈", "").replace("〉", "")
    s = s.replace("(", "（").replace(")", "）")
    s = re.sub(r"（\d{4}年.*$", "", s)
    s = re.sub(r"（截至.*$", "", s)
    return s.strip("，,;；、.．")


def title_key(s: str) -> str:
    return hashlib.sha256(norm_title(s).encode("utf-8")).hexdigest()[:16]


def parse_zh_date(text: str) -> Optional[str]:
    if not text:
        return None
    m = re.search(r"(20\d{2}|19\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日", text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.search(r"(20\d{2}|19\d{2})[-/.](\d{1,2})[-/.](\d{1,2})", text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return iso_date(text)


def split_articles_zh(text: str, law_id: str, source_url: str, date: Optional[str] = None) -> list[dict]:
    if not text or len(text) < 40:
        return []
    text = re.sub(r"[ \t\u00a0\u2000-\u200b\u3000]+", " ", text)
    text = re.sub(
        r"(第[一二三四五六七八九十百千万零〇两0-9]+条(?:之[一二三四五六七八九十百0-9]+)?)",
        r"\n\1",
        text,
    )
    matches = list(ART_RE.finditer(text))
    if len(matches) < 2:
        return []
    docs = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk = text[start:end].strip()
        num = re.sub(r"\s+", "", m.group(1))
        aid = hashlib.sha256(num.encode("utf-8")).hexdigest()[:10]
        heading = re.sub(r"\s+", " ", chunk.split("\n", 1)[0])[:200]
        docs.append({
            "id": f"{law_id}-{aid}"[:180],
            "title": heading,
            "text": chunk,
            "date_filed": date,
            "document_number": num,
            "source_url": source_url,
            "record_type": "article",
            "article_number": num,
            "law_identifier": law_id,
            "metadata": {"text_extraction": {"source": "official", "backend": "collector", "article_scheme": "zh-tiao"}},
        })
        if len(docs) >= 4000:
            break
    return docs


def check_flk_robots() -> dict:
    url = "https://flk.npc.gov.cn/robots.txt"
    info = {"url": url, "allowed": False, "reason": "not_fetched"}
    try:
        r = http_get(url, ua=UA, sleep=0.3, retries=2, timeout=(15, 30), allow_empty=True)
        body = r.text if r.status_code == 200 else ""
        info["http_status"] = r.status_code
        info["body_excerpt"] = body[:500]
        if re.search(r"(?im)^user-agent:\s*\*\s*$", body) and re.search(r"(?im)^disallow:\s*/\s*$", body):
            info["allowed"] = False
            info["reason"] = "robots_disallow_all"
        else:
            info["allowed"] = True
            info["reason"] = "robots_not_fully_disallowed"
    except Exception as exc:
        info["reason"] = f"fetch_error:{exc!r}"
        info["allowed"] = False
    (ROOT / CC / "raw" / "flk_robots.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    log.info("flk robots allowed=%s reason=%s", info["allowed"], info["reason"])
    return info


def download_catalog_pdf() -> Path:
    dest = ROOT / CC / "raw" / "xxyxflml_301_20260815.pdf"
    if dest.exists() and dest.stat().st_size > 10000:
        return dest
    r = npc_get(CATALOG_PDF_URL, timeout=(20, 60), retries=4)
    if r.status_code != 200 or not r.content.startswith(b"%PDF"):
        raise RuntimeError(f"catalog pdf failed HTTP {r.status_code}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(r.content)
    return dest


def parse_catalog(pdf_path: Path) -> list[dict]:
    txt_path = ROOT / CC / "raw" / "xxyxflml_301_20260815.txt"
    raw = subprocess.check_output(["pdftotext", str(pdf_path), "-"], text=True, encoding="utf-8", errors="replace")
    atomic_write(txt_path, raw)
    text = raw.replace("\u3000", " ").replace("．", ".")
    text = text.replace("\x0c", "\n")
    text = re.sub(r"\n\s*\d{1,2}\s*\n", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n+", " ", text)
    text = re.sub(r" +", " ", text)
    dept_re = re.compile(r"(宪法相关法|民法商法|行政法|经济法|社会法|刑法|诉讼与非诉讼程序法)（\s*(\d+)\s*件）")
    departments = {m.group(1): int(m.group(2)) for m in dept_re.finditer(text)}
    items: list[dict] = []
    # Constitution block
    items.append({
        "title": "中华人民共和国宪法",
        "department": "宪法",
        "catalog_note": "1982年，含1988/1993/1999/2004/2018年修正案",
        "document_type": "constitution",
        "source": "npc_catalog_pdf",
        "catalog_url": CATALOG_PDF_URL,
    })
    parts = dept_re.split(text)
    # parts: preamble, name, count, body, name, count, body...
    i = 1
    while i + 2 < len(parts):
        dept = parts[i]
        body = parts[i + 2]
        i += 3
        chunks = re.split(
            r"(?=\d+\.\s*(?:中华人民共和国|中国人民解放军|全国人民代表大会))",
            body,
        )
        for ch in chunks:
            ch = ch.strip()
            m = re.match(r"(\d+)\.\s*(.*)$", ch, re.S)
            if not m:
                continue
            body_s = re.sub(r"\s+", "", m.group(2))
            tm = re.match(r"(.+?)（(\d{4}.*)$", body_s)
            if tm:
                title = tm.group(1)
                note = "（" + tm.group(2)
                if "）" in note:
                    note = note[: note.find("）") + 1]
            else:
                title = re.sub(r"（\d+件）.*", "", body_s)
                note = ""
            title = title.strip()
            if len(title) < 4:
                continue
            if title.startswith("附件"):
                continue
            dtype = "statute"
            if title.endswith("条例") or title.endswith("规定") or title.endswith("办法"):
                dtype = "regulation"
            elif "决定" in title or "决议" in title:
                dtype = "decree"
            items.append({
                "title": title,
                "department": dept,
                "catalog_note": note,
                "document_type": dtype,
                "source": "npc_catalog_pdf",
                "catalog_url": CATALOG_PDF_URL,
                "catalog_number": int(m.group(1)),
            })
    # dedup by norm title, keep first
    seen = set()
    out = []
    for it in items:
        k = norm_title(it["title"])
        if not k or k in seen:
            continue
        seen.add(k)
        it["norm"] = k
        out.append(it)
    meta = {
        "advertised_count": 301,
        "parsed_count": len(out),
        "departments_advertised": departments,
        "catalog_url": CATALOG_PDF_URL,
        "cutoff": "2026-08-15",
    }
    atomic_write(
        ROOT / CC / "raw" / "catalog_meta.json",
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
    )
    atomic_write(
        ROOT / CC / "raw" / "catalog_titles.json",
        json.dumps(out, ensure_ascii=False, indent=2) + "\n",
    )
    log.info("catalog parsed %s titles (advertised 301) depts=%s", len(out), departments)
    return out


def listing_items_from_html(html: str, page_url: str) -> list[dict]:
    items = []
    for m in re.finditer(
        r'<li>\s*<a href="([^"]+)"[^>]*>(.*?)</a>\s*<span>(.*?)</span>\s*</li>',
        html, re.S,
    ):
        href, title, date = m.group(1), m.group(2), m.group(3)
        title = re.sub(r"<[^>]+>", "", title)
        title = re.sub(r"\s+", " ", title).strip()
        url = urljoin(page_url, href)
        items.append({
            "title": title,
            "source_url": url,
            "list_date": date.strip(),
            "list_page": page_url,
        })
    return items


def discover_qwfb() -> list[dict]:
    cat = ROOT / CC / "raw" / "catalog.jsonl"
    if cat.exists() and cat.stat().st_size > 2000:
        items = []
        with cat.open(encoding="utf-8") as f:
            for line in f:
                try:
                    items.append(json.loads(line))
                except Exception:
                    continue
        if len(items) >= 100:
            log.info("resume qwfb listing %s", len(items))
            return items
    items = []
    seen = set()
    # index.html then index_1.html ... until empty/redirect
    for n in range(0, 90):
        url = QWFB_INDEX if n == 0 else f"http://www.npc.gov.cn/npc/c2/c12435/index_{n}.html"
        r = npc_get(url, sleep=0.4, retries=3, allow_empty=True)
        if r.status_code in (404, 410) or (r.status_code in (301, 302) and len(r.content) < 400):
            log.info("qwfb stop n=%s status=%s", n, r.status_code)
            break
        if r.status_code != 200 or len(r.content) < 500:
            log.info("qwfb skip n=%s status=%s bytes=%s", n, r.status_code, len(r.content or b""))
            if n > 5:
                break
            continue
        batch = listing_items_from_html(r.text, url)
        newc = 0
        for it in batch:
            u = it["source_url"]
            if u in seen:
                continue
            seen.add(u)
            items.append(it)
            append_catalog(CC, it)
            newc += 1
        log.info("qwfb page n=%s new=%s total=%s", n, newc, len(items))
        if newc == 0 and n > 0:
            break
    return items


def is_instrument_title(title: str, catalog_norms: set[str]) -> bool:
    nt = norm_title(title)
    if nt in catalog_norms:
        return True
    if SKIP_TITLE_RE.search(title or ""):
        return False
    if title.startswith("中华人民共和国主席令"):
        return False
    return False


def extract_main_text(html: str) -> tuple[str, str, Optional[str]]:
    title = ""
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S | re.I)
    if m:
        title = re.sub(r"<[^>]+>", "", m.group(1))
        title = re.sub(r"\s+", " ", title).strip()
    if not title:
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
        if m:
            title = re.sub(r"<[^>]+>", "", m.group(1)).split("_")[0].strip()
    date = None
    m = re.search(r"<h3[^>]*>(.*?)</h3>", html, re.S | re.I)
    subtitle = re.sub(r"<[^>]+>", " ", m.group(1)) if m else ""
    date = parse_zh_date(subtitle) or parse_zh_date(html[:8000])
    chunk = ""
    selectors = [
        r'<div id="Zoom"[^>]*>(.*?)</div>\s*<div class="editor"',
        r'<div[^>]*id="UCAP-CONTENT"[^>]*>(.*?)</div>',
        r'<div[^>]*class="[^"]*pages_content[^"]*"[^>]*>(.*?)</div>',
        r'<div[^>]*class="[^"]*(?:TRS_Editor|article-content|content|zhengce_content|pages_content)[^"]*"[^>]*>(.*?)</div>',
        r'<td[^>]*id="zoom"[^>]*>(.*?)</td>',
        r'<div[^>]*class="[^"]*article[^"]*"[^>]*>(.*?)</div>',
        r'<div[^>]*id="content"[^>]*>(.*?)</div>',
    ]
    for pat in selectors:
        m = re.search(pat, html, re.S | re.I)
        if m and len(m.group(1) or "") > 80:
            chunk = m.group(1)
            break
    text = html_to_text(chunk or html)
    alt = html_to_text(html) if html else text
    if alt.count("第") > text.count("第") and len(alt) > len(text) + 100:
        text = alt
    return title, text, date


def looks_like_statute(text: str) -> bool:
    if not text or len(text) < 200:
        return False
    if text.count("第") < 2:
        return False
    n_tiao = len(re.findall(r"第[一二三四五六七八九十百千万零〇两0-9]+条", text))
    return n_tiao >= 3 or (n_tiao >= 1 and "宪法" in text[:200] and len(text) > 1500)


def parse_instrument_html(html: str) -> tuple[str, str, Optional[str], str]:
    if not html or len(html) < 200:
        return "", "", None, "empty_html"
    title, text, date = extract_main_text(html)
    if not looks_like_statute(text):
        return title, text, date, "not_statute_text"
    return title, text, date, "ok"


def _zh_score(s: str) -> int:
    if not s:
        return -1
    return s.count("第") + s.count("条") + (20 if "中华人民共和国" in s else 0) + (10 if "主席令" in s else 0)


def _fix_mojibake(s: str) -> str:
    if not s or _zh_score(s) >= 4:
        return s
    for enc in ("latin-1", "cp1252", "iso-8859-1"):
        try:
            fixed = s.encode(enc).decode("utf-8")
        except Exception:
            continue
        if _zh_score(fixed) > _zh_score(s):
            return fixed
    return s


def html_from_archive(rec: dict) -> str:
    text = rec.get("text") or ""
    body = rec.get("content") or b""
    if isinstance(body, str):
        body = body.encode("utf-8", "replace")
    cands = []
    if text:
        cands.append(text)
        cands.append(_fix_mojibake(text))
    if body:
        cleaned = body.replace(b"\xa0", b"\xc2\xa0")
        for raw in (cleaned, body):
            for enc in ("utf-8", "gb18030", "gbk"):
                try:
                    s = raw.decode(enc, "replace")
                except Exception:
                    continue
                cands.append(s)
                cands.append(_fix_mojibake(s))
    best = text
    best_sc = -1
    for s in cands:
        sc = _zh_score(s)
        if sc > best_sc:
            best, best_sc = s, sc
    return best or text


def official_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host in ("npc.gov.cn", "gov.cn") or host.endswith(".npc.gov.cn") or host.endswith(".gov.cn"):
        if "flk.npc.gov.cn" in (urlparse(url).hostname or ""):
            return False
        return True
    return False


def law_like_url(url: str) -> bool:
    if not url or not url.startswith("http"):
        return False
    if not official_host(url):
        return False
    if ASSET_RE.search(url) or SKIP_URL_RE.search(url):
        return False
    path = urlparse(url).path or ""
    if path in ("", "/", "/npc/", "/npc") or path.count("/") < 2:
        return False
    return bool(LAW_PATH_RE.search(url) or url.rstrip("/").endswith(".html") or url.rstrip("/").endswith(".htm"))


def fetch_html_instrument(url: str) -> tuple[str, str, Optional[str], str]:
    r = npc_get(url, retries=3, timeout=(20, 90))
    if r.status_code != 200 or not r.text:
        return "", "", None, f"http_{r.status_code}"
    return parse_instrument_html(r.text)


def fetch_archive_of_official(url: str) -> tuple[str, str, Optional[str], str, dict]:
    """Wayback then Common Crawl of an official npc.gov.cn / gov.cn URL."""
    extra: dict = {}
    if not url or not official_host(url):
        return "", "", None, "archive_skip_host", extra
    with _archive_lock:
        try:
            rec = get_wayback_content(url)
        except Exception as exc:
            rec = {"status": "error", "error": repr(exc)}
        if rec.get("status") == "success":
            html = html_from_archive(rec)
            title, text, date, st = parse_instrument_html(html)
            if st == "ok":
                extra = {
                    "method": "archive-of-official",
                    "archive_method": "wayback",
                    "wayback_url": rec.get("wayback_url"),
                    "original_url": rec.get("original_url") or url,
                    "capture_timestamp": rec.get("capture_timestamp"),
                    "archive": True,
                    "text_extraction": {"source": "archive-of-official", "backend": "wayback"},
                }
                return title, text, date, "ok", extra
        try:
            hits = search_cc_cached(url, limit=6)
        except Exception:
            hits = []
        for hit in hits:
            try:
                rec = fetch_common_crawl_warc(hit)
            except Exception:
                continue
            if rec.get("status") != "success":
                continue
            html = html_from_archive(rec)
            title, text, date, st = parse_instrument_html(html)
            if st == "ok":
                extra = {
                    "method": "archive-of-official",
                    "archive_method": "common_crawl",
                    "original_url": rec.get("original_url") or url,
                    "cc_record": rec.get("cc_record"),
                    "archive": True,
                    "text_extraction": {"source": "archive-of-official", "backend": "common_crawl"},
                }
                return title, text, date, "ok", extra
    return "", "", None, "archive_miss", extra


def govcn_search(title: str) -> Optional[str]:
    """Use official gov.cn 政策文件库 JSON search; pick exact-title hits on gov.cn."""
    url = "https://sousuo.www.gov.cn/search-gov/data"
    params = {
        "t": "zhengcelibrary",
        "q": title,
        "searchfield": "title",
        "sort": "pubtime",
        "sortType": "1",
        "p": "0",
        "n": "8",
    }
    try:
        r = http_get(url, ua=UA, sleep=SLEEP, params=params, retries=2, timeout=(20, 40),
                     headers={"Accept": "application/json", "Accept-Language": "zh-CN,zh;q=0.9"})
        if r.status_code != 200:
            return None
        data = r.json()
    except Exception:
        return None
    sv = data.get("searchVO") or {}
    cands = []
    lv = sv.get("listVO")
    if isinstance(lv, list):
        cands.extend(lv)
    cat = sv.get("catMap") or {}
    if isinstance(cat, dict):
        for blob in cat.values():
            if isinstance(blob, dict):
                cands.extend(blob.get("listVO") or [])
    want = norm_title(title)
    best = None
    for row in cands:
        if not isinstance(row, dict):
            continue
        rt = norm_title(row.get("title") or "")
        href = row.get("url") or ""
        if not href or "gov.cn" not in href:
            continue
        if rt == want or want in rt:
            best = href
            if rt == want:
                break
    return best


def write_law(title: str, text: str, source_url: str, cat: dict, extra_meta: Optional[dict] = None) -> str:
    ident = "law-" + title_key(title)
    date = parse_zh_date(cat.get("catalog_note") or "") or parse_zh_date(text[:800])
    rec = base_record(
        cc=CC,
        country=COUNTRY,
        language="zh",
        ident=ident,
        title=title,
        text=text,
        source_url=source_url,
        source_type=SOURCE_TYPE,
        license_text=LICENSE,
        collector="cn-npc-qwfb",
        eli=None,
        date=date,
        official_identifier=title,
        document_type=cat.get("document_type") or "statute",
        law_status="current",
        is_current=True,
        documents=split_articles_zh(text, slug_id(CC, ident), source_url, date),
        extra_meta={
            "discovery": {
                "method": extra_meta.get("method") if extra_meta else "npc_qwfb",
                "catalog_title": cat.get("title"),
                "department": cat.get("department"),
            },
            "official_metadata": {
                "catalog_note": cat.get("catalog_note"),
                "catalog_url": CATALOG_PDF_URL,
                "department": cat.get("department"),
            },
            **({} if not extra_meta else {k: v for k, v in extra_meta.items() if k != "method"}),
        },
        extra_fields={
            "date_issued": date,
            "publication_date": date,
            "canonical_title": title,
        },
    )
    write_instrument(CC, rec)
    return rec["id"]


def match_listing_to_catalog(listings: list[dict], catalog: list[dict]) -> dict[str, dict]:
    """Map catalog norm title -> best listing item (latest date, exact title preferred)."""
    cat_by = {c["norm"]: c for c in catalog}
    best: dict[str, dict] = {}
    for it in listings:
        nt = norm_title(it["title"])
        if nt in cat_by:
            prev = best.get(nt)
            if not prev or (it.get("list_date") or "") >= (prev.get("list_date") or ""):
                best[nt] = {**it, "match": "exact"}
            continue
        m = re.search(r"关于修改《(.+?)》的决定", it["title"])
        if m:
            nt2 = norm_title(m.group(1))
            if nt2 in cat_by and nt2 not in best:
                best[nt2] = {**it, "match": "amendment_decision"}
    return best


def match_page_to_catalog(title: str, text: str, cat_by_norm: dict[str, dict]) -> Optional[dict]:
    if SKIP_TITLE_RE.search(title or "") and norm_title(title) not in cat_by_norm:
        return None
    nt = norm_title(title)
    if nt in cat_by_norm:
        return cat_by_norm[nt]
    best = None
    best_len = 0
    blob = (title or "") + "\n" + (text or "")[:1800]
    for m in re.finditer(r"《([^》]{4,80})》", blob):
        k = norm_title(m.group(1))
        if k in cat_by_norm and len(k) > best_len:
            best, best_len = cat_by_norm[k], len(k)
    if best:
        return best
    for k, cat in cat_by_norm.items():
        if len(k) >= 8 and k in nt and len(k) > best_len:
            best, best_len = cat, len(k)
    return best


def fetch_one(job: dict, done: set[str]) -> str:
    cat = job["cat"]
    ident = slug_id(CC, "law-" + title_key(cat["title"]))
    if ident in done:
        return "skip"
    url = job.get("source_url")
    method = job.get("method") or "npc_qwfb"
    title_l, text, date, st = "", "", None, "no_url"
    extra: dict = {}
    if url:
        title_l, text, date, st = fetch_html_instrument(url)
        if st != "ok" and "gov.cn" not in (url or ""):
            gurl = govcn_search(cat["title"])
            if gurl:
                url = gurl
                method = "govcn_search"
                title_l, text, date, st = fetch_html_instrument(url)
    elif job.get("try_govcn"):
        gurl = govcn_search(cat["title"])
        if gurl:
            url = gurl
            method = "govcn_search"
            title_l, text, date, st = fetch_html_instrument(url)
        else:
            st = "no_url"
    if st != "ok" or not text:
        cands = []
        for u in (job.get("source_url"), url):
            if u and u not in cands:
                cands.append(u)
        if cat.get("norm") == "中华人民共和国宪法":
            for seed in CONSTITUTION_SEEDS:
                if seed not in cands:
                    cands.append(seed)
        for cand in cands:
            t2, x2, d2, st2, extra2 = fetch_archive_of_official(cand)
            if st2 == "ok" and x2:
                title_l, text, date, st = t2, x2, d2, "ok"
                method = "archive-of-official"
                url = extra2.get("wayback_url") or cand
                extra = extra2
                extra["list_title"] = title_l
                extra["list_date"] = job.get("list_date")
                break
    if st != "ok" or not text:
        log_failure(CC, {
            "identifier": cat["title"],
            "source_url": url,
            "status": "failed",
            "reason": st or "empty_text",
        })
        return "fail"
    use_title = cat["title"]
    if not extra:
        extra = {"method": method, "list_title": title_l, "list_date": job.get("list_date")}
        if method.startswith("archive"):
            extra["archive"] = True
            extra["text_extraction"] = {"source": "archive-of-official", "backend": extra.get("archive_method") or "collector"}
    else:
        extra.setdefault("method", method)
        extra.setdefault("list_title", title_l)
        extra.setdefault("list_date", job.get("list_date"))
    write_law(use_title, text, url, cat, extra)
    done.add(ident)
    return "ok"


def _cdx_unique(hits: list[dict]) -> list[dict]:
    out = []
    seen = set()
    for rec in hits:
        orig = rec.get("original") or rec.get("url") or ""
        orig = orig.split("#")[0]
        if not law_like_url(orig):
            continue
        key = orig.rstrip("/")
        prev = None
        if key in seen:
            continue
        seen.add(key)
        rec = dict(rec)
        rec["original"] = orig
        out.append(rec)
    out.sort(key=lambda r: (str(r.get("timestamp") or ""), len(r.get("original") or "")), reverse=True)
    return out


def wayback_fill(missing: list[dict], done: set[str]) -> tuple[int, int]:
    """CDX prefix search of official NPC/gov.cn hosts; match captures to catalog titles."""
    ok = fail = 0
    miss_norms = {m["norm"]: m for m in missing}
    if not miss_norms:
        return 0, 0
    cdx_path = ROOT / CC / "raw" / "cdx_hits.jsonl"
    hits: list[dict] = []
    for spec in CDX_PREFIXES:
        url = spec["url"]
        try:
            batch = search_wayback_machine(
                url,
                match_type=spec.get("match_type") or "prefix",
                limit=spec.get("limit") or 200,
                mime_prefix="text/html",
                collapse="urlkey",
                from_date=spec.get("from_date"),
                to_date=spec.get("to_date"),
            )
        except Exception as exc:
            log.info("wayback cdx failed %s: %s", url, exc)
            batch = []
        log.info("wayback cdx %s n=%s", url, len(batch))
        hits.extend(batch)
        try:
            cc_batch = search_cc_cached(url if url.endswith("*") else url.rstrip("/") + "*", limit=80)
        except Exception as exc:
            log.info("cc cdx failed %s: %s", url, exc)
            cc_batch = []
        log.info("commoncrawl cdx %s n=%s", url, len(cc_batch))
        hits.extend(cc_batch)
    uniq = _cdx_unique(hits)
    with cdx_path.open("w", encoding="utf-8") as handle:
        for rec in uniq:
            handle.write(json.dumps({
                "original": rec.get("original"),
                "timestamp": rec.get("timestamp"),
                "source": rec.get("source"),
                "wayback_url": rec.get("wayback_url"),
                "mimetype": rec.get("mimetype"),
            }, ensure_ascii=False) + "\n")
    log.info("cdx unique law-like urls=%s missing_catalog=%s", len(uniq), len(miss_norms))
    seeds = [{"original": u, "timestamp": "", "source": "seed"} for u in CONSTITUTION_SEEDS]
    # Prefer article-like NPC captures, then gov.cn zhengce, then the rest.
    def _rank(rec):
        u = rec.get("original") or ""
        score = 0
        if "/wxzl/gongbao" in u or "/wxzl/wxzl" in u:
            score += 8
        if "/banshi/" in u:
            score += 7
        if "/flfg/" in u:
            score += 6
        if "gongbao/content" in u or re.search(r"/gongbao/(19|200)", u):
            score += 5
        if "/zhengce/" in u:
            score += 3
        if "/xinwen/" in u:
            score += 2
        if "/c12435/" in u or "/c30834/" in u:
            score += 1
        if "/kgfb/" in u:
            score -= 2
        ts = rec.get("timestamp") or ""
        return (score, ts)
    uniq.sort(key=_rank, reverse=True)
    queue = seeds + uniq
    MAX_CDX_FETCH = 1800
    queue = queue[:MAX_CDX_FETCH]
    fetched = 0
    write_lock = threading.Lock()

    def _ingest(rec, html, extra, src_url):
        nonlocal ok, fail, fetched
        title_l, text, date, st = parse_instrument_html(html)
        fetched += 1
        if st != "ok":
            return
        cat = match_page_to_catalog(title_l, text, miss_norms)
        if not cat:
            return
        ident = slug_id(CC, "law-" + title_key(cat["title"]))
        with write_lock:
            if ident in done or cat["norm"] not in miss_norms:
                return
            extra["list_title"] = title_l
            write_law(cat["title"], text, src_url, cat, extra)
            done.add(ident)
            miss_norms.pop(cat["norm"], None)
            ok += 1
        log.info("cdx fill ok %s via %s (%s)", cat["title"], extra.get("archive_method"), (rec.get("original") or "")[:90])

    def _one(rec):
        orig = rec.get("original") or ""
        if not orig:
            return rec, {"status": "error", "error": "no_url"}
        if rec.get("source") == "common_crawl" and (rec.get("filename") or rec.get("warc_filename")):
            try:
                payload = fetch_common_crawl_warc(rec)
            except Exception as exc:
                payload = {"status": "error", "error": repr(exc)}
            if payload.get("status") == "success":
                return rec, payload
        ts = rec.get("timestamp") or None
        try:
            payload = get_wayback_content(orig, timestamp=ts)
        except Exception as exc:
            payload = {"status": "error", "error": repr(exc)}
        return rec, payload

    for batch_i in range(0, len(queue), 32):
        if not miss_norms:
            break
        batch = queue[batch_i: batch_i + 32]
        with ThreadPoolExecutor(max_workers=4) as ex:
            futs = [ex.submit(_one, rec) for rec in batch]
            for fut in as_completed(futs):
                rec, payload = fut.result()
                orig = rec.get("original") or ""
                if payload.get("status") != "success":
                    fail += 1
                    continue
                html = html_from_archive(payload)
                extra = {
                    "method": "archive-of-official",
                    "archive_method": payload.get("method") or rec.get("source") or "wayback",
                    "wayback_url": payload.get("wayback_url"),
                    "original_url": orig,
                    "capture_timestamp": payload.get("capture_timestamp") or rec.get("timestamp"),
                    "archive": True,
                    "text_extraction": {
                        "source": "archive-of-official",
                        "backend": payload.get("method") or "wayback",
                    },
                }
                src_url = payload.get("wayback_url") or orig
                try:
                    _ingest(rec, html, extra, src_url)
                except Exception as exc:
                    fail += 1
                    log.info("cdx ingest error %s: %s", orig[:80], exc)
        log.info(
            "cdx fetch progress n=%s ok=%s fail=%s remaining=%s",
            min(batch_i + 32, len(queue)), ok, fail, len(miss_norms),
        )
    log.info("wayback_fill done ok=%s fail=%s fetched=%s remaining=%s", ok, fail, fetched, len(miss_norms))
    return ok, fail


def main():
    setup()
    t0 = utcnow()
    robots = check_flk_robots()
    pdf = download_catalog_pdf()
    catalog = parse_catalog(pdf)
    catalog_norms = {c["norm"] for c in catalog}
    listings = discover_qwfb()
    matched = match_listing_to_catalog(listings, catalog)
    log.info("qwfb listings=%s catalog=%s matches=%s sample=%s",
             len(listings), len(catalog), len(matched), list(matched)[:6])
    jobs = []
    for cat in catalog:
        hit = matched.get(cat["norm"])
        jobs.append({
            "cat": cat,
            "source_url": (hit or {}).get("source_url"),
            "list_date": (hit or {}).get("list_date"),
            "method": "npc_qwfb" if hit and hit.get("match") == "exact" else (
                "npc_qwfb_amendment" if hit else "pending_govcn"
            ),
            "try_govcn": hit is None,
        })
    done = existing_ids(CC)
    ok = skip = fail = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = [ex.submit(fetch_one, job, done) for job in jobs]
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
            if n % 25 == 0:
                log.info("progress %s/%s ok=%s skip=%s fail=%s", n, len(jobs), ok, skip, fail)
                write_summary(
                    CC, country=COUNTRY, source="NPC 权威发布 + 现行有效法律目录",
                    source_urls=[CATALOG_PDF_URL, QWFB_INDEX, "https://flk.npc.gov.cn/ (robots Disallow: /; not crawled)"],
                    license_text=LICENSE, discovered=len(catalog), fetched=ok, skipped=skip, failed=fail,
                    coverage="in-progress", notes="in-force 法律 via NPC catalog + 权威发布",
                    last_run=utcnow(),
                )
    # wayback fill for remaining misses
    done2 = existing_ids(CC)
    still = []
    for cat in catalog:
        ident = slug_id(CC, "law-" + title_key(cat["title"]))
        if ident not in done2:
            still.append(cat)
    wb_ok, wb_fail = (0, 0)
    if still:
        log.info("missing after live fetch: %s; trying archive-of-official", len(still))
        w1, w2 = wayback_fill(still, done2)
        wb_ok, wb_fail = w1, w2
        ok += wb_ok
        fail += wb_fail
    n_json = len(list((ROOT / CC / "instruments").glob("*.json")))
    coverage = "full" if n_json >= len(catalog) and fail == 0 else "catalog-backed incomplete"
    notes = (
        f"In-force national 法律 per NPC 现行有效法律目录 PDF (advertised 301, parsed {len(catalog)}, cutoff 2026-08-15). "
        f"flk.npc.gov.cn robots.txt Disallow: / so the National Database JSON API was not crawled "
        f"(reason={robots.get('reason')}). "
        f"Live texts from NPC 权威发布 HTML; gov.cn search fallback for catalog misses; "
        f"Wayback of official NPC/gov.cn URLs labeled archive-of-official as last resort. "
        f"Administrative regulations (行政法规) not harvested in this snapshot. "
        f"No machine translation. Not legal advice; official gazette / NPC text prevails."
    )
    write_summary(
        CC, country=COUNTRY,
        source="NPC 现行有效法律目录 + 权威发布 (flk.npc.gov.cn skipped: robots Disallow /)",
        source_urls=[
            CATALOG_PDF_URL,
            QWFB_INDEX,
            "http://www.npc.gov.cn/",
            "https://www.gov.cn/zhengce/",
            "https://flk.npc.gov.cn/ (not crawled; robots Disallow: /)",
        ],
        license_text=LICENSE, discovered=len(catalog), fetched=ok, skipped=skip, failed=fail,
        coverage=coverage, notes=notes, last_run=utcnow(), extra=f"started {t0} instruments_json={n_json}",
    )
    log.info("done ok=%s skip=%s fail=%s instruments=%s catalog=%s", ok, skip, fail, n_json, len(catalog))


if __name__ == "__main__":
    if "--fill-only" in sys.argv:
        setup()
        pdf = download_catalog_pdf()
        catalog = parse_catalog(pdf)
        done = existing_ids(CC)
        still = []
        for cat in catalog:
            ident = slug_id(CC, "law-" + title_key(cat["title"]))
            if ident not in done:
                still.append(cat)
        log.info("fill-only missing=%s instruments=%s", len(still), len(done))
        wayback_fill(still, done)
        n_json = len(list((ROOT / CC / "instruments").glob("*.json")))
        log.info("fill-only done instruments=%s", n_json)
    else:
        main()
