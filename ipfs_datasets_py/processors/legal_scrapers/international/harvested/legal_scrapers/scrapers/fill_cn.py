#!/usr/bin/env python3
"""Second pass: Wayback/CC of official NPC/gov.cn URLs for NPC catalog misses.

The first live pass under-fetched older official hosts (NPC 公报 wxzl/gongbao,
gov.cn/flfg, gov.cn/banshi). This fill ranks those first, expands CDX prefixes,
then tries a looser gov.cn search per remaining title.

Does not crawl flk.npc.gov.cn (robots Disallow: /). No pkulaw / Cloudflare.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from archive_fallbacks import (  # noqa: E402
    WAYBACK_WEB,
    _sleep_wayback,
    fetch_common_crawl_warc,
    get_wayback_content,
    search_common_crawl,
    search_wayback_machine,
    session as wb_session,
)
from collect_cn import (  # noqa: E402
    CC,
    download_catalog_pdf,
    extract_main_text,
    html_from_archive,
    law_like_url,
    looks_like_statute,
    npc_get,
    norm_title,
    official_host,
    parse_catalog,
    parse_zh_date,
    title_key,
    write_law,
    SKIP_TITLE_RE,
)
from common import *  # noqa: F401,F403,E402

log = logging.getLogger("cn-fill")

EXTRA_CDX = [
    {"url": "http://www.gov.cn/banshi/", "limit": 400, "match_type": "prefix"},
    {"url": "http://www.npc.gov.cn/wxzl/gongbao/", "limit": 700, "match_type": "prefix"},
    {"url": "http://www.npc.gov.cn/wxzl/wxzl/", "limit": 400, "match_type": "prefix"},
    {"url": "http://www.gov.cn/flfg/", "limit": 500, "match_type": "prefix"},
    {"url": "https://www.gov.cn/flfg/", "limit": 300, "match_type": "prefix"},
    {"url": "http://www.gov.cn/gongbao/", "limit": 300, "match_type": "prefix"},
    {"url": "https://www.gov.cn/gongbao/content/", "limit": 300, "match_type": "prefix"},
    {"url": "https://www.gov.cn/xinwen/", "limit": 350, "match_type": "prefix", "from_date": "20160101", "to_date": "20181231"},
    {"url": "https://www.gov.cn/xinwen/", "limit": 350, "match_type": "prefix", "from_date": "20190101", "to_date": "20221231"},
    {"url": "https://www.gov.cn/zhengce/", "limit": 350, "match_type": "prefix", "from_date": "20160101", "to_date": "20191231"},
    {"url": "https://www.gov.cn/zhengce/", "limit": 350, "match_type": "prefix", "from_date": "20200101", "to_date": "20221231"},
    {"url": "http://www.gov.cn/zhengce/", "limit": 250, "match_type": "prefix"},
    {"url": "http://www.npc.gov.cn/npc/xinwen/", "limit": 200, "match_type": "prefix"},
]

SEED_URLS = [
    "http://www.gov.cn/banshi/2005-05/25/content_980.htm",
    "http://www.gov.cn/gongbao/content/2005/content_121488.htm",
    "http://www.npc.gov.cn/wxzl/wxzl/2000-12/10/content_4364.htm",
    "http://www.npc.gov.cn/wxzl/gongbao/2000-12/05/content_5007226.htm",
    "http://www.gov.cn/flfg/2005-08/05/content_20921.htm",
    "https://www.gov.cn/xinwen/2021-06/11/content_5616919.htm",
    "https://www.gov.cn/xinwen/2021-06/11/content_5616918.htm",
    "https://www.gov.cn/xinwen/2017-09/05/content_5222714.htm",
    "https://www.gov.cn/xinwen/2018-08/31/content_5318048.htm",
    "https://www.gov.cn/xinwen/2020-10/18/content_5552109.htm",
    "https://www.gov.cn/xinwen/2021-06/10/content_5616624.htm",
    "https://www.gov.cn/xinwen/2020-12/26/content_5573635.htm",
    "https://www.gov.cn/xinwen/2018-09/01/content_5318602.htm",
    "https://www.gov.cn/xinwen/2021-06/11/content_5616930.htm",
    "https://www.gov.cn/xinwen/2016-09/05/content_5103482.htm",
    "https://www.gov.cn/xinwen/2021-04/29/content_5604001.htm",
    "https://www.gov.cn/xinwen/2020-12/26/content_5573634.htm",
    "https://www.gov.cn/xinwen/2021-06/11/content_5616928.htm",
    "https://www.gov.cn/xinwen/2018-09/04/content_5319185.htm",
    "https://www.gov.cn/xinwen/2016-11/07/content_5129779.htm",
    "https://www.gov.cn/xinwen/2017-11/05/content_5237327.htm",
    "https://www.gov.cn/xinwen/2020-11/11/content_5560462.htm",
    "https://www.gov.cn/xinwen/2021-01/23/content_5581963.htm",
    "https://www.gov.cn/xinwen/2016-12/26/content_5152771.htm",
    "https://www.gov.cn/xinwen/2016-07/05/content_5088328.htm",
    "https://www.gov.cn/xinwen/2020-11/11/content_5560489.htm",
    "https://www.gov.cn/xinwen/2017-11/05/content_5237325.htm",
    "https://www.gov.cn/xinwen/2018-04/28/content_5286559.htm",
    "https://www.gov.cn/xinwen/2021-06/11/content_5616915.htm",
    "https://www.gov.cn/xinwen/2020-06/01/content_5516568.htm",
]

MAX_FETCH = 1600
LIVE_HOST_SKIP = re.compile(r"/banshi/|/flfg/|/wxzl/", re.I)


def setup():
    ensure_dirs(CC)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(ROOT / CC / "logs" / "fill.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def utf8_html(rec: dict) -> str:
    body = rec.get("content")
    if isinstance(body, (bytes, bytearray)) and body:
        try:
            return body.decode("utf-8")
        except UnicodeDecodeError:
            return body.decode("utf-8", "replace")
    return rec.get("text") or ""


def pdf_to_text(content: bytes) -> str:
    if not content or not content.startswith(b"%PDF"):
        return ""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(content)
        path = tmp.name
    try:
        return subprocess.check_output(
            ["pdftotext", "-layout", path, "-"],
            text=True, encoding="utf-8", errors="replace",
        )
    except Exception as exc:
        log.info("pdftotext fail %s", exc)
        return ""
    finally:
        Path(path).unlink(missing_ok=True)


def canon_url(url: str) -> str:
    u = (url or "").split("#")[0].strip()
    u = u.replace("www.gov.cn:80", "www.gov.cn").replace("www.npc.gov.cn:80", "www.npc.gov.cn")
    u = u.replace("http://www.gov.cn:80/", "http://www.gov.cn/")
    if u.startswith("https://www.gov.cn:80/"):
        u = "https://www.gov.cn/" + u.split("/", 3)[-1] if False else u.replace("https://www.gov.cn:80/", "https://www.gov.cn/")
    return u.rstrip("/")


def rank_url(u: str) -> int:
    u = u or ""
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
    return score


def accept_body(text: str, title: str, cat_title: str) -> bool:
    if looks_like_statute(text):
        return True
    if not text or len(text) < 220:
        return False
    ck = norm_title(cat_title)
    nt = norm_title(title)
    head = (title or "") + "\n" + (text or "")[:500]
    if not ck:
        return False
    if ck != nt and ck not in nt and ck not in norm_title(head):
        return False
    n_tiao = len(re.findall(r"第[一二三四五六七八九十百千万零〇两0-9]+条", text))
    if n_tiao >= 1:
        return True
    if any(x in cat_title for x in ("决定", "决议", "规定", "办法", "条例")) and len(text) >= 350:
        return True
    return False


def match_missing(title: str, text: str, miss_norms: dict) -> Optional[dict]:
    nt = norm_title(title)
    if SKIP_TITLE_RE.search(title or "") and nt not in miss_norms:
        return None
    if nt in miss_norms:
        return miss_norms[nt]
    nt2 = re.sub(r"（.*$", "", nt)
    if nt2 in miss_norms:
        return miss_norms[nt2]
    blob = nt + "\n" + (text or "")[:900]
    best = None
    best_len = 0
    for k, cat in miss_norms.items():
        if k and len(k) >= 8 and k in blob and len(k) > best_len:
            best, best_len = cat, len(k)
    return best


def parse_payload(html_or_text: str, is_pdf: bool = False) -> tuple[str, str, Optional[str]]:
    if is_pdf:
        text = html_or_text or ""
        title = ""
        m = re.search(r"中华人民共和国[^\n]{2,40}", text)
        if m:
            title = m.group(0).strip()
        return title, text, parse_zh_date(text[:1200]) if text else None
    return extract_main_text(html_or_text)


def try_live(url: str) -> tuple[str, str, Optional[str], str, str]:
    try:
        r = npc_get(url, retries=2, timeout=(20, 60), sleep=0.25)
    except Exception as exc:
        return "", "", None, f"live_err:{exc}", "live"
    if r.status_code != 200 or not r.content:
        return "", "", None, f"http_{r.status_code}", "live"
    if r.content[:4] == b"%PDF" or url.lower().endswith(".pdf"):
        text = pdf_to_text(r.content)
        title = ""
        m = re.search(r"中华人民共和国[^\n]{2,40}", text)
        if m:
            title = m.group(0).strip()
        st = "ok" if looks_like_statute(text) else "not_statute_text"
        return title, text, parse_zh_date(text[:1200]) if text else None, st, "live-pdf"
    title, text, date = extract_main_text(r.text)
    st = "ok" if looks_like_statute(text) else "not_statute_text"
    return title, text, date, st, "live"


def replay_wayback(url: str, timestamp: Optional[str] = None) -> dict:
    """Polite Wayback replay via archive_fallbacks session (shorter delay than default)."""
    if timestamp:
        wb = f"{WAYBACK_WEB}/{timestamp}id_/{url}"
    else:
        wb = f"{WAYBACK_WEB}/2id_/{url}"
    r = None
    last_err = None
    for attempt in range(1, 4):
        _sleep_wayback(0.45 if attempt == 1 else min(8.0, 1.8 * attempt))
        try:
            r = wb_session().get(wb, timeout=(20, 80), allow_redirects=True)
        except Exception as exc:
            last_err = str(exc)
            continue
        if r.status_code in (403, 429, 503, 502, 504) and attempt < 3:
            continue
        break
    if r is None:
        return {"status": "error", "error": last_err or "no_response"}
    cap_ts = timestamp or ""
    m = re.search(r"/web/(\d{14})", r.url or "")
    if m:
        cap_ts = m.group(1)
    body = r.content or b""
    if r.status_code != 200 or not body:
        return {"status": "error", "error": f"http_{r.status_code}", "wayback_url": r.url}
    text = ""
    ctype = r.headers.get("content-type") or ""
    if "html" in ctype or "xml" in ctype or "text/" in ctype or not ctype:
        try:
            text = body.decode(r.encoding or "utf-8", "replace")
        except Exception:
            text = body.decode("utf-8", "replace")
    return {
        "status": "success",
        "content": body,
        "text": text,
        "wayback_url": r.url,
        "capture_timestamp": cap_ts,
        "original_url": url,
        "method": "wayback",
    }


def fetch_one_url(url: str, ts: Optional[str] = None) -> tuple[str, str, Optional[str], str, dict]:
    extra: dict = {}
    live_ok = official_host(url) and not LIVE_HOST_SKIP.search(url or "")
    if live_ok:
        title, text, date, st, method = try_live(url)
        if st == "ok":
            extra = {"method": "govcn_live" if "gov.cn" in url else "npc_qwfb_fill", "list_title": title}
            return title, text, date, "ok", extra
    rec = replay_wayback(url, timestamp=ts)
    if rec.get("status") != "success":
        try:
            rec = get_wayback_content(url, timestamp=ts)
        except Exception as exc:
            rec = {"status": "error", "error": repr(exc)}
    if rec.get("status") == "success":
        body = rec.get("content") or b""
        if isinstance(body, (bytes, bytearray)) and bytes(body[:4]) == b"%PDF":
            text = pdf_to_text(bytes(body))
            title, date = "", parse_zh_date(text[:1200]) if text else None
            extra = {
                "method": "archive-of-official",
                "archive_method": "wayback",
                "wayback_url": rec.get("wayback_url"),
                "original_url": url,
                "capture_timestamp": rec.get("capture_timestamp") or ts,
                "archive": True,
                "text_extraction": {"source": "archive-of-official", "backend": "wayback-pdf"},
            }
            return title, text, date, ("ok" if looks_like_statute(text) else "not_statute_text"), extra
        html = html_from_archive(rec)
        title, text, date = extract_main_text(html)
        extra = {
            "method": "archive-of-official",
            "archive_method": "wayback",
            "wayback_url": rec.get("wayback_url"),
            "original_url": url,
            "capture_timestamp": rec.get("capture_timestamp") or ts,
            "archive": True,
            "text_extraction": {"source": "archive-of-official", "backend": "wayback"},
            "list_title": title,
        }
        return title, text, date, ("ok" if looks_like_statute(text) else "not_statute_text"), extra
    try:
        hits = search_common_crawl(url, limit=3)
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
        title, text, date = extract_main_text(html)
        if looks_like_statute(text):
            extra = {
                "method": "archive-of-official",
                "archive_method": "common_crawl",
                "original_url": rec.get("original_url") or url,
                "cc_record": rec.get("cc_record"),
                "archive": True,
                "text_extraction": {"source": "archive-of-official", "backend": "common_crawl"},
                "list_title": title,
            }
            return title, text, date, "ok", extra
    return "", "", None, "miss", extra


def load_existing_cdx() -> list[dict]:
    path = ROOT / CC / "raw" / "cdx_hits.jsonl"
    out = []
    if not path.exists():
        return out
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            orig = rec.get("original") or rec.get("url") or ""
            if orig:
                rec["original"] = orig
                out.append(rec)
    return out


def merge_cdx(existing: list[dict], extra: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for rec in existing + extra:
        orig = canon_url(rec.get("original") or rec.get("url") or "")
        if not orig:
            continue
        if orig in seen:
            continue
        if not law_like_url(orig) and not orig.lower().endswith((".htm", ".html", ".pdf")):
            if not official_host(orig):
                continue
        if not official_host(orig):
            continue
        host = (urlparse(orig).hostname or "").lower()
        if "flk.npc.gov.cn" in host:
            continue
        seen.add(orig)
        rec = dict(rec)
        rec["original"] = orig
        out.append(rec)
    out.sort(key=lambda r: (rank_url(r.get("original") or ""), r.get("timestamp") or ""), reverse=True)
    return out


def search_extra_cdx() -> list[dict]:
    hits = []
    for spec in EXTRA_CDX:
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
            log.info("extra cdx fail %s: %s", url, exc)
            batch = []
        log.info("extra cdx %s n=%s", url, len(batch))
        hits.extend(batch)
        try:
            cc_batch = search_common_crawl(url if url.endswith("*") else url.rstrip("/") + "*", limit=40)
        except Exception:
            cc_batch = []
        if cc_batch:
            log.info("extra cc %s n=%s", url, len(cc_batch))
            hits.extend(cc_batch)
    return hits


def listing_map() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    path = ROOT / CC / "raw" / "catalog.jsonl"
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            it = json.loads(line)
        except Exception:
            continue
        out.setdefault(norm_title(it.get("title") or ""), []).append(it)
    return out


def govcn_search_loose(title: str) -> list[str]:
    """Broader gov.cn policy-library search; keep official gov.cn URLs whose title mentions the law."""
    url = "https://sousuo.www.gov.cn/search-gov/data"
    want = norm_title(title)
    short = want.replace("中华人民共和国", "")
    found: list[str] = []
    seen = set()
    for q in (title, f"《{title}》", short):
        if not q or len(q) < 3:
            continue
        params = {
            "t": "zhengcelibrary",
            "q": q,
            "searchfield": "title",
            "sort": "pubtime",
            "sortType": "1",
            "p": "0",
            "n": "12",
        }
        try:
            r = http_get(
                url, ua=DEFAULT_UA, sleep=0.35, params=params, retries=2, timeout=(20, 40),
                headers={"Accept": "application/json", "Accept-Language": "zh-CN,zh;q=0.9"},
            )
            if r.status_code != 200:
                continue
            data = r.json()
        except Exception:
            continue
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
        for row in cands:
            if not isinstance(row, dict):
                continue
            rt = re.sub(r"<[^>]+>", "", row.get("title") or "")
            rt_n = norm_title(rt)
            href = row.get("url") or ""
            if not href or "gov.cn" not in href:
                continue
            if "flk.npc.gov.cn" in href:
                continue
            if want in rt_n or rt_n == want or (len(short) >= 4 and short in rt_n):
                cu = canon_url(href)
                if cu not in seen:
                    seen.add(cu)
                    found.append(cu)
    return found[:6]


def ingest(title: str, text: str, date: Optional[str], extra: dict, used_url: str,
           miss_norms: dict, done: set[str], write_lock: threading.Lock) -> bool:
    if SKIP_TITLE_RE.search(title or "") and norm_title(title) not in miss_norms:
        # still allow exact catalog title in body
        pass
    cat = match_missing(title, text, miss_norms)
    if not cat:
        return False
    if not accept_body(text, title, cat["title"]):
        return False
    ident = slug_id(CC, "law-" + title_key(cat["title"]))
    with write_lock:
        if ident in done or cat["norm"] not in miss_norms:
            return False
        extra = dict(extra or {})
        extra.setdefault("list_title", title)
        src = extra.get("wayback_url") or used_url
        write_law(cat["title"], text, src, cat, extra)
        done.add(ident)
        miss_norms.pop(cat["norm"], None)
    log.info("fill ok %s via %s chars=%s url=%s", cat["title"][:40], extra.get("method"), len(text or ""), (used_url or "")[:90])
    return True


def dump_missing(miss_norms: dict) -> None:
    titles = [c["title"] for c in miss_norms.values()]
    items = list(miss_norms.values())
    atomic_write(
        ROOT / CC / "raw" / "missing_titles.json",
        json.dumps(titles, ensure_ascii=False, indent=2) + "\n",
    )
    atomic_write(
        ROOT / CC / "raw" / "missing.json",
        json.dumps(items, ensure_ascii=False, indent=2) + "\n",
    )


def main():
    setup()
    catalog = parse_catalog(download_catalog_pdf())
    done = existing_ids(CC)
    miss_list = []
    for cat in catalog:
        ident = slug_id(CC, "law-" + title_key(cat["title"]))
        if ident not in done:
            miss_list.append(cat)
    miss_norms = {c["norm"]: c for c in miss_list}
    log.info("fill start missing=%s have=%s catalog=%s", len(miss_norms), len(done), len(catalog))

    write_lock = threading.Lock()
    ok = 0
    fail = 0

    # --- A. leftover listing URLs (cheap) ---
    listings = listing_map()
    for cat in list(miss_list):
        if cat["norm"] not in miss_norms:
            continue
        urls = []
        for it in listings.get(cat["norm"], []):
            u = it.get("source_url")
            if u and u not in urls:
                urls.append(u)
        if not urls:
            continue
        got = False
        for url in urls[:4]:
            title, text, date, st, extra = fetch_one_url(url)
            if st == "ok" and ingest(title, text, date, extra, url, miss_norms, done, write_lock):
                ok += 1
                got = True
                break
        if not got:
            fail += 1
    log.info("after listing pass ok=%s fail=%s remaining=%s", ok, fail, len(miss_norms))

    # --- B. CDX remaining + extra prefixes ---
    existing = load_existing_cdx()
    log.info("loaded existing cdx %s", len(existing))
    extra = search_extra_cdx()
    merged = merge_cdx(existing, extra)
    for seed in SEED_URLS:
        merged.append({"original": canon_url(seed), "timestamp": "", "source": "seed"})
    merged = merge_cdx(merged, [])
    cdx_path = ROOT / CC / "raw" / "cdx_hits.jsonl"
    with cdx_path.open("w", encoding="utf-8") as handle:
        for rec in merged:
            handle.write(json.dumps({
                "original": rec.get("original"),
                "timestamp": rec.get("timestamp"),
                "source": rec.get("source"),
                "wayback_url": rec.get("wayback_url"),
                "mimetype": rec.get("mimetype"),
            }, ensure_ascii=False) + "\n")
    log.info("merged cdx unique=%s missing=%s", len(merged), len(miss_norms))

    queue = merged[:MAX_FETCH]
    fetched = 0
    seen_url = set()

    def _one(rec):
        orig = rec.get("original") or ""
        ts = rec.get("timestamp") or None
        if rec.get("source") == "common_crawl" and (rec.get("filename") or rec.get("warc_filename")):
            try:
                payload = fetch_common_crawl_warc(rec)
            except Exception as exc:
                payload = {"status": "error", "error": repr(exc)}
            if payload.get("status") == "success":
                html = html_from_archive(payload)
                title, text, date = extract_main_text(html)
                extra = {
                    "method": "archive-of-official",
                    "archive_method": "common_crawl",
                    "original_url": orig,
                    "archive": True,
                    "text_extraction": {"source": "archive-of-official", "backend": "common_crawl"},
                    "list_title": title,
                }
                return orig, title, text, date, extra, ("ok" if looks_like_statute(text) else "not_statute")
        title, text, date, st, extra = fetch_one_url(orig, ts)
        return orig, title, text, date, extra, st

    for batch_i in range(0, len(queue), 24):
        if not miss_norms:
            break
        batch = []
        for rec in queue[batch_i: batch_i + 24]:
            orig = canon_url(rec.get("original") or "")
            if not orig or orig in seen_url:
                continue
            seen_url.add(orig)
            batch.append(rec)
        if not batch:
            continue
        with ThreadPoolExecutor(max_workers=5) as ex:
            futs = [ex.submit(_one, rec) for rec in batch]
            for fut in as_completed(futs):
                fetched += 1
                try:
                    orig, title, text, date, extra, st = fut.result()
                except Exception as exc:
                    fail += 1
                    log.info("fetch err %s", exc)
                    continue
                if not text:
                    fail += 1
                    continue
                if ingest(title, text, date, extra, orig, miss_norms, done, write_lock):
                    ok += 1
                else:
                    # relaxed: try match even if looks_like_statute was false
                    cat = match_missing(title, text, miss_norms)
                    if cat and accept_body(text, title, cat["title"]):
                        extra = extra or {"method": "archive-of-official"}
                        if ingest(title, text, date, extra, orig, miss_norms, done, write_lock):
                            ok += 1
        log.info(
            "cdx progress n=%s ok=%s fail=%s remaining=%s fetched=%s",
            min(batch_i + 24, len(queue)), ok, fail, len(miss_norms), fetched,
        )

    # --- C. per-title gov.cn search for leftovers ---
    leftover = list(miss_norms.values())
    log.info("govcn loose search leftover=%s", len(leftover))
    for i, cat in enumerate(leftover, 1):
        if cat["norm"] not in miss_norms:
            continue
        urls = govcn_search_loose(cat["title"])
        got = False
        for url in urls:
            title, text, date, st, extra = fetch_one_url(url)
            extra = extra or {}
            if extra.get("method") == "govcn_live":
                extra["method"] = "govcn_search"
            if (st == "ok" or accept_body(text, title or cat["title"], cat["title"])) and ingest(
                title or cat["title"], text, date, extra, url, miss_norms, done, write_lock
            ):
                ok += 1
                got = True
                break
        if not got:
            log_failure(CC, {"identifier": cat["title"], "status": "failed", "reason": "fill:no_official_body"})
        if i % 10 == 0:
            log.info("govcn leftover progress %s/%s ok=%s remaining=%s", i, len(leftover), ok, len(miss_norms))

    dump_missing(miss_norms)
    n_json = len(list((ROOT / CC / "instruments").glob("*.json")))
    methods = {}
    for p in (ROOT / CC / "instruments").glob("*.json"):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        md = rec.get("metadata") or {}
        disc = md.get("discovery") or {}
        m = disc.get("method") or rec.get("source_type") or "?"
        methods[m] = methods.get(m, 0) + 1
    atomic_write(
        ROOT / CC / "raw" / "method_counts.json",
        json.dumps({"methods": methods, "instruments": n_json, "missing": len(miss_norms)}, ensure_ascii=False, indent=2) + "\n",
    )
    log.info("fill done ok=%s fail=%s instruments=%s remaining=%s methods=%s", ok, fail, n_json, len(miss_norms), methods)


if __name__ == "__main__":
    main()
