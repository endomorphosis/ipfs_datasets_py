#!/usr/bin/env python3
"""Harder fill of remaining NPC catalog 法律 from official sources only.

Live gov.cn/xinwen 2016–2022 pages now 404; latest Wayback captures are those
404 shells. This pass uses per-URL CDX (not prefix hammer of xinwen 2019–2022)
plus publication-year replay, HTTP Common Crawl index, archive.is, xzfg.moj.gov.cn
title search, and gov.cn search. Exact catalog title match. No flk.npc.gov.cn.
Does not mix parquet/china 行政法规.
"""
from __future__ import annotations

import json
import logging
import re
import sys
import threading
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from archive_fallbacks import (  # noqa: E402
    fetch_common_crawl_warc,
    get_archive_is_content,
    get_wayback_content,
    session as wb_session,
)
from collect_cn import (  # noqa: E402
    CC,
    download_catalog_pdf,
    extract_main_text,
    html_from_archive,
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
from fill_cn import dump_missing, pdf_to_text, canon_url  # noqa: E402
from fill_cn_leftover import SEEDS as LEFTOVER_SEEDS  # noqa: E402

log = logging.getLogger("cn-harder")

EXTRA_SEEDS: dict[str, list[str]] = {
    "中华人民共和国全国人民代表大会组织法": [
        "http://www.gov.cn/xinwen/2021-03/13/content_5592682.htm",
        "https://www.gov.cn/xinwen/2021-03/13/content_5592682.htm",
        "http://www.npc.gov.cn/wxzl/gongbao/1982-12/09/content_1478462.htm",
        "http://www.npc.gov.cn/wxzl/wxzl/2000-12/10/content_4307.htm",
    ],
    "中华人民共和国海关法": [
        "http://www.gov.cn/xinwen/2021-04/29/content_5604002.htm",
        "https://www.gov.cn/xinwen/2021-04/29/content_5604002.htm",
        "http://www.gov.cn/flfg/2005-06/27/content_9809.htm",
        "http://www.gov.cn/banshi/2005-06/08/content_4898.htm",
        "http://www.npc.gov.cn/wxzl/gongbao/2000-12/05/content_5004689.htm",
    ],
    "中华人民共和国教育法": [
        "http://www.gov.cn/xinwen/2021-04/30/content_5603937.htm",
        "https://www.gov.cn/xinwen/2021-04/30/content_5603937.htm",
        "http://www.gov.cn/xinwen/2021-04/30/content_5603935.htm",
        "http://www.gov.cn/flfg/2006-06/30/content_323138.htm",
        "http://www.npc.gov.cn/wxzl/gongbao/1995-03/18/content_1481296.htm",
    ],
    "中华人民共和国行政处罚法": [
        "http://www.gov.cn/xinwen/2021-01/23/content_5582011.htm",
        "https://www.gov.cn/xinwen/2021-01/23/content_5582011.htm",
        "http://www.gov.cn/xinwen/2021-01/22/content_5581914.htm",
        "http://www.npc.gov.cn/wxzl/gongbao/1996-03/17/content_1481297.htm",
        "http://www.gov.cn/banshi/2005-08/31/content_24858.htm",
    ],
    "中华人民共和国气象法": [
        "http://www.gov.cn/flfg/2005-08/05/content_20921.htm",
        "http://www.gov.cn/banshi/2005-08/31/content_24849.htm",
        "http://www.npc.gov.cn/wxzl/gongbao/2000-12/05/content_5004693.htm",
        "http://www.npc.gov.cn/wxzl/gongbao/2016-08/22/content_1995723.htm",
        "http://www.gov.cn/xinwen/2016-11/07/content_5129779.htm",
    ],
    "中华人民共和国铁路法": [
        "http://www.gov.cn/flfg/2005-08/06/content_20909.htm",
        "https://www.gov.cn/flfg/2005-08/06/content_20909.htm",
        "http://www.npc.gov.cn/wxzl/gongbao/2015-07/03/content_1942870.htm",
        "http://www.npc.gov.cn/wxzl/gongbao/2000-12/05/content_5004686.htm",
        "http://www.gov.cn/banshi/2005-08/31/content_26781.htm",
    ],
    "中华人民共和国农业技术推广法": [
        "http://www.gov.cn/flfg/2012-08/31/content_2215983.htm",
        "https://www.gov.cn/flfg/2012-08/31/content_2215983.htm",
        "http://www.npc.gov.cn/wxzl/gongbao/2012-11/08/content_1745518.htm",
        "http://www.npc.gov.cn/wxzl/gongbao/2000-12/05/content_5004656.htm",
        "http://www.gov.cn/xinwen/2024-11/08/content_6985756.htm",
    ],
    "中华人民共和国中国人民银行法": [
        "http://www.gov.cn/ziliao/flfg/2005-09/12/content_31158.htm",
        "http://www.gov.cn/flfg/2003-12/27/content_121855.htm",
        "http://www.npc.gov.cn/wxzl/gongbao/2004-01/12/content_5327203.htm",
        "http://www.npc.gov.cn/wxzl/gongbao/2000-12/05/content_5004700.htm",
        "http://www.gov.cn/banshi/2005-08/31/content_26841.htm",
    ],
    "中华人民共和国印花税法": [
        "http://www.gov.cn/xinwen/2021-06/10/content_5616624.htm",
        "https://www.gov.cn/xinwen/2021-06/10/content_5616624.htm",
        "http://www.gov.cn/xinwen/2021-06/11/content_5616913.htm",
        "https://www.gov.cn/xinwen/2021-06/11/content_5616913.htm",
        "http://www.npc.gov.cn/npc/c2/c30834/202106/t20210611_312036.html",
    ],
    "中华人民共和国生物安全法": [
        "http://www.gov.cn/xinwen/2020-10/18/content_5552108.htm",
        "https://www.gov.cn/xinwen/2020-10/18/content_5552108.htm",
        "http://www.gov.cn/xinwen/2024-04/27/content_6946300.htm",
        "https://www.gov.cn/xinwen/2024-04/27/content_6946300.htm",
        "http://www.npc.gov.cn/npc/c2/c30834/202010/t20201018_308251.html",
    ],
    "中华人民共和国刑法": [
        "http://www.npc.gov.cn/zgrdw/npc/xinwen/2015-08/31/content_1945587.htm",
        "http://www.npc.gov.cn/npc/xinwen/2015-08/31/content_1945587.htm",
        "http://www.npc.gov.cn/wxzl/wxzl/2000-12/17/content_4680.htm",
        "http://www.npc.gov.cn/wxzl/gongbao/2000-12/17/content_5004371.htm",
        "http://www.gov.cn/flfg/2011-03/10/content_1828147.htm",
        "http://www.gov.cn/banshi/2005-05/27/content_1160.htm",
        "http://www.npc.gov.cn/zgrdw/npc/xinwen/2021-03/01/content_2103672.htm",
    ],
    "中华人民共和国行政诉讼法": [
        "http://www.npc.gov.cn/wxzl/gongbao/2017-05/24/content_2022263.htm",
        "http://www.gov.cn/xinwen/2017-06/28/content_5206328.htm",
        "https://www.gov.cn/xinwen/2017-06/28/content_5206328.htm",
        "http://www.gov.cn/xinwen/2015-05/27/content_2868854.htm",
        "http://www.gov.cn/flfg/2015-05/27/content_2868854.htm",
        "http://www.npc.gov.cn/wxzl/gongbao/1989-04/04/content_1481263.htm",
        "http://www.gov.cn/banshi/2005-08/31/content_24859.htm",
    ],
    "中华人民共和国澳门特别行政区基本法": [
        "http://www.npc.gov.cn/wxzl/wxzl/2000-12/05/content_4498.htm",
        "http://www.npc.gov.cn/wxzl/gongbao/2000-12/05/content_5004595.htm",
        "http://www.gov.cn/test/2005-07/29/content_18296.htm",
        "http://www.gov.cn/zhengce/2017-11/09/content_5238154.htm",
        "http://www.npc.gov.cn/zgrdw/wxzl/gongbao/2000-12/05/content_5004595.htm",
        "http://www.npc.gov.cn/npc/c2/c30834/201711/t20171115_288733.html",
    ],
}

# fill_cn.py seed URLs that are known official statute pages
GENERIC_SEEDS = [
    "http://www.gov.cn/xinwen/2021-06/11/content_5616919.htm",
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
    "http://www.gov.cn/banshi/2005-05/25/content_980.htm",
    "http://www.npc.gov.cn/wxzl/wxzl/2000-12/10/content_4364.htm",
    "http://www.gov.cn/flfg/2005-08/05/content_20921.htm",
]

CC_HTTP_INDEXES = [
    "http://index.commoncrawl.org/CC-MAIN-2021-31-index",
    "http://index.commoncrawl.org/CC-MAIN-2022-27-index",
    "http://index.commoncrawl.org/CC-MAIN-2024-33-index",
]

TIAO_RE = re.compile(r"第[一二三四五六七八九十百千万零〇两0-9]+条")
YEAR_PATH_RE = re.compile(r"/(19\d{2}|20\d{2})[-/](\d{1,2})[-/](\d{1,2})/")
ABOUT_RE = re.compile(r"关于(?:增加|批准|修改|解释)?《([^》]{4,80})》")
REJECT_HEAD = re.compile(r"(草案|解读|答记者问|优惠公告|宣传周|新闻发布|的说明|工作报告)")


def setup():
    ensure_dirs(CC)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(ROOT / CC / "logs" / "fill.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def ts_from_url(url: str) -> Optional[str]:
    m = YEAR_PATH_RE.search(url or "")
    if m:
        return f"{m.group(1)}{int(m.group(2)):02d}{int(m.group(3)):02d}120000"
    m = re.search(r"/t(19\d{2}|20\d{2})(\d{2})(\d{2})_", url or "")
    if m:
        return f"{m.group(1)}{m.group(2)}{m.group(3)}120000"
    return None


def heading_norms(title: str, text: str) -> list[str]:
    """Standalone headings only. Do not mine 书名号 inside reports."""
    out = []
    seen = set()

    def add(s: str):
        n = norm_title(s)
        if "草案" in n or "审查报告" in n or "的说明" in n or "解读" in n:
            return
        n2 = re.sub(r"（.*$", "", n)
        if n2 and n2 not in seen and 4 <= len(n2) <= 90:
            seen.add(n2)
            out.append(n2)

    if title:
        add(title)
        add(re.sub(r"_.*$", "", title))
    head = (text or "")[:2500]
    for line in re.split(r"[\n\r]+", head):
        line = line.strip().strip("《》　 ").strip()
        if not line or line.startswith("新华社") or len(line) > 90:
            continue
        if "，" in line or "。" in line or "、" in line:
            continue
        if 4 <= len(line) <= 90:
            add(line)
    return out


def is_about_not_the_law(title: str, text: str, cat_title: str) -> bool:
    """Drop 决定/决议 ABOUT a law when the catalog wants the law itself."""
    if any(x in cat_title for x in ("决定", "决议")):
        return False
    blob = (title or "") + "\n" + (text or "")[:600]
    if REJECT_HEAD.search(title or ""):
        return True
    m = ABOUT_RE.search(blob)
    if m and norm_title(m.group(1)) == norm_title(cat_title):
        # page is 关于《X》的决定, catalog is X
        if "决定" in (title or "") or (title or "").startswith("关于"):
            return True
    if "主席令" in (title or "") and "关于修改" in blob[:400]:
        # amendment decision published under 主席令 — still the 决定, not the law
        if "通过" not in (text or "")[:800] and TIAO_RE.search((text or "")[:800]) is None:
            return True
    return False


def exact_heading(cat: dict, title: str, text: str) -> bool:
    want = cat["norm"]
    if is_about_not_the_law(title, text, cat["title"]):
        return False
    heads = heading_norms(title, text)
    if want in heads:
        return True
    # 主席令 pages: catalog title as its own line in the body
    for h in heads:
        if h == want:
            return True
        if h.endswith(want) and h != want:
            # substring trap: 高等教育法 must not match 教育法
            return False
    return False


def quality_ok(cat: dict, text: str) -> bool:
    if not text:
        return False
    n_tiao = len(TIAO_RE.findall(text))
    title = cat["title"]
    if title == "中华人民共和国刑法":
        return n_tiao >= 80 and len(text) >= 20000
    if "澳门特别行政区基本法" in title and "驻军" not in title:
        return n_tiao >= 40 and len(text) >= 8000
    if any(x in title for x in ("决定", "决议")):
        return len(text) >= 250
    if title.endswith("条例") or title.endswith("办法") or title.endswith("规定"):
        return (n_tiao >= 3 or len(text) >= 800) and len(text) >= 400
    if not looks_like_statute(text) and n_tiao < 3:
        return False
    # Short but complete tax 法律 (烟叶税法 ~10条/565字, 城市维护建设税法 ~11条/999字)
    if n_tiao >= 8:
        return True
    return n_tiao >= 3 and len(text) >= 1200


def parse_rec(rec: dict, url: str) -> tuple[str, str, Optional[str]]:
    body = rec.get("content") or b""
    if isinstance(body, (bytes, bytearray)) and bytes(body[:4]) == b"%PDF":
        text = pdf_to_text(bytes(body))
        title = ""
        m = re.search(r"中华人民共和国[^\n]{2,60}", text or "")
        if m:
            title = m.group(0).strip()
        return title, text, parse_zh_date((text or "")[:1200])
    html = html_from_archive(rec)
    if not html and rec.get("text"):
        html = rec["text"]
    return extract_main_text(html or "")


def live_fetch(url: str) -> Optional[dict]:
    try:
        r = npc_get(url, retries=1, timeout=(15, 40), sleep=0.2)
    except Exception as exc:
        log.info("live err %s %s", url[-70:], exc)
        return None
    if r.status_code != 200 or not r.content or len(r.content) < 400:
        return None
    rec = {"status": "success", "content": r.content, "text": r.text or "", "original_url": url, "method": "live"}
    title, text, date = parse_rec(rec, url)
    if "中国人大网" == (title or "") and "第一条" not in (text or "")[:500]:
        return None
    if "中国政府网" in (title or "") and len(text or "") < 400:
        return None
    rec["parsed"] = (title, text, date)
    rec["final_url"] = getattr(r, "url", url)
    return rec


def per_url_cdx(url: str) -> list[str]:
    """Per-URL CDX only (not prefix). Prefer HTTP to avoid TLS flakes."""
    hostpath = url
    for prefix in ("https://", "http://"):
        if hostpath.startswith(prefix):
            hostpath = hostpath[len(prefix):]
            break
    timestamps = []
    params = {
        "url": hostpath,
        "output": "json",
        "filter": "statuscode:200",
        "limit": 12,
        "fl": "timestamp,original,statuscode,mimetype,length",
        "collapse": "digest",
    }
    last_err = None
    global _SKIP_CDX
    if _SKIP_CDX:
        return []
    for cdx in ("http://web.archive.org/cdx/search/cdx",):
        time.sleep(0.4)
        try:
            r = wb_session().get(cdx, params=params, timeout=(8, 15))
        except Exception as exc:
            last_err = exc
            _SKIP_CDX = True
            log.info("cdx disable %s", exc)
            return []
        if r.status_code == 429:
            log.info("cdx 429 %s", url[-60:])
            time.sleep(4)
            continue
        if r.status_code != 200 or not r.content:
            last_err = f"http_{r.status_code}"
            continue
        try:
            data = r.json()
        except Exception:
            continue
        rows = data[1:] if isinstance(data, list) and data and data[0] and data[0][0] == "timestamp" else data
        for row in rows or []:
            ts = row[0] if isinstance(row, list) else (row.get("timestamp") if isinstance(row, dict) else None)
            if ts and str(ts).isdigit() and len(str(ts)) >= 8:
                timestamps.append(str(ts)[:14].ljust(14, "0"))
        if timestamps:
            break
    if last_err and not timestamps:
        log.info("cdx miss %s %s", url[-60:], last_err)
    # earliest 200 first (publication-era, before 404 shells)
    timestamps = sorted(set(timestamps))
    return timestamps[:6]


def wayback_at(url: str, ts: Optional[str]) -> Optional[dict]:
    """HTTP Wayback replay only (HTTPS currently SSLEOF from this host)."""
    ts = ts or "20190101120000"
    wb = f"http://web.archive.org/web/{ts}id_/{url}"
    try:
        r = wb_session().get(wb, timeout=(12, 40), allow_redirects=True)
    except Exception as exc:
        log.info("wb http fail %s", exc)
        return None
    if r.status_code != 200 or not r.content or len(r.content) < 400:
        return None
    cap_ts = ts
    m = re.search(r"/web/(\d{14})", r.url or "")
    if m:
        cap_ts = m.group(1)
    rec = {
        "status": "success",
        "content": r.content,
        "text": r.text or "",
        "wayback_url": r.url,
        "capture_timestamp": cap_ts,
        "original_url": url,
        "method": "wayback",
        "archive_method": "wayback",
    }
    title, text, date = parse_rec(rec, url)
    if not text or len(text) < 200:
        return None
    rec["parsed"] = (title, text, date)
    return rec


def search_cc_http(url: str, limit: int = 3) -> list[dict]:
    hostpath = url
    for prefix in ("https://", "http://"):
        if hostpath.startswith(prefix):
            hostpath = hostpath[len(prefix):]
            break
    out = []
    for idx in CC_HTTP_INDEXES:
        time.sleep(0.3)
        try:
            r = wb_session().get(idx, params={"url": hostpath, "output": "json", "limit": str(limit)}, timeout=(12, 22))
        except Exception as exc:
            log.info("cc http fail %s %s", idx.split("/")[-1], exc)
            continue
        if r.status_code != 200 or not r.content:
            continue
        for line in r.text.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            st = str(rec.get("status") or "200")
            if st not in ("200", "201", "206"):
                continue
            rec["original"] = rec.get("url") or url
            rec["source"] = "common_crawl"
            out.append(rec)
        if out:
            break
    return out[:limit]


def cc_fetch(url: str) -> Optional[dict]:
    hits = search_cc_http(url, limit=3)
    for hit in hits:
        try:
            rec = fetch_common_crawl_warc(hit)
        except Exception as exc:
            log.info("warc fail %s", exc)
            continue
        if rec.get("status") != "success":
            continue
        title, text, date = parse_rec(rec, url)
        if text and len(text) >= 200:
            rec["parsed"] = (title, text, date)
            rec["archive_method"] = "common_crawl"
            return rec
    return None


def archive_is_fetch(url: str) -> Optional[dict]:
    try:
        rec = get_archive_is_content(url)
    except Exception:
        return None
    if rec.get("status") != "success":
        return None
    title, text, date = parse_rec(rec, url)
    if text and len(text) >= 200:
        rec["parsed"] = (title, text, date)
        rec["archive_method"] = "archive_is"
        return rec
    return None


def xzfg_search(title: str) -> list[str]:
    urls = []
    q = title.replace("中华人民共和国", "")[:30]
    for endpoint, typ in (("https://xzfg.moj.gov.cn/SearchTitleFront", "1"), ("http://xzfg.moj.gov.cn/SearchTitleFront", "1")):
        try:
            r = wb_session().get(
                endpoint,
                params={"SiteID": "122", "Query": q, "Type": typ},
                timeout=(12, 20),
            )
        except Exception:
            continue
        if r.status_code != 200 or not r.content:
            continue
        html = r.text or ""
        want = norm_title(title)
        for href, lab in re.findall(r'href="([^"]+LawID=\d+)"[^>]*>([^<]{2,80})', html):
            if want == norm_title(lab) or want == norm_title(re.sub(r"<[^>]+>", "", lab)):
                if href.startswith("http"):
                    urls.append(href)
                else:
                    urls.append("https://xzfg.moj.gov.cn" + href)
        if urls:
            break
    return urls[:4]


def govcn_exact_search(title: str) -> list[str]:
    want = norm_title(title)
    found = []
    seen = set()
    api = "https://sousuo.www.gov.cn/search-gov/data"
    for tparam in ("zhengcelibrary", "gongwen"):
        params = {
            "t": tparam,
            "q": f"《{title}》" if tparam == "gongwen" else title,
            "searchfield": "title",
            "sort": "pubtime",
            "sortType": "1",
            "p": "0",
            "n": "10",
        }
        try:
            r = http_get(
                api, ua=DEFAULT_UA, sleep=0.3, params=params, retries=1, timeout=(15, 25),
                headers={"Accept": "application/json", "Accept-Language": "zh-CN,zh;q=0.9"},
            )
        except Exception:
            continue
        if r.status_code != 200:
            continue
        try:
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
            rt_n = re.sub(r"（.*$", "", norm_title(rt))
            href = row.get("url") or ""
            if not href or "gov.cn" not in href or "flk.npc.gov.cn" in href:
                continue
            if rt_n != want and norm_title(rt) != want:
                continue
            cu = canon_url(href)
            if cu not in seen:
                seen.add(cu)
                found.append(cu)
    return found[:6]


def candidate_urls(cat: dict) -> list[str]:
    title = cat["title"]
    urls = []
    seen = set()

    def add(u: str):
        u = canon_url(u)
        if not u or u in seen:
            return
        if "flk.npc.gov.cn" in u:
            return
        if not official_host(u) and "xzfg.moj.gov.cn" not in u:
            return
        seen.add(u)
        urls.append(u)

    for u in EXTRA_SEEDS.get(title, []):
        add(u)
    for u in LEFTOVER_SEEDS.get(title, []):
        add(u)
    def _rank(u):
        s = 0
        if "/wxzl/gongbao" in u or "/wxzl/wxzl" in u:
            s += 8
        if "/banshi/" in u or "/flfg/" in u or "/ziliao/" in u:
            s += 6
        if "/zhengce/" in u:
            s += 4
        if "/xinwen/" in u:
            s += 2
        return -s
    urls.sort(key=_rank)
    return urls


def extra_for(rec: dict, url: str, live: bool) -> dict:
    method = rec.get("method") or rec.get("archive_method") or ""
    if live and method in ("live", "http", ""):
        host = (urlparse(url).hostname or "")
        meth = "govcn_live" if "gov.cn" in host else ("moj_xzfg" if "moj.gov.cn" in host else "npc_qwfb_fill")
        return {"method": meth, "list_title": (rec.get("parsed") or ("",))[0], "original_url": url}
    backend = rec.get("archive_method") or rec.get("method") or "wayback"
    extra = {
        "method": "archive-of-official",
        "archive_method": backend,
        "wayback_url": rec.get("wayback_url") or rec.get("archive_url"),
        "original_url": rec.get("original_url") or url,
        "capture_timestamp": rec.get("capture_timestamp"),
        "archive": True,
        "text_extraction": {"source": "archive-of-official", "backend": backend},
        "list_title": (rec.get("parsed") or ("",))[0],
    }
    return extra


_SKIP_ARCHIVE_IS = True
_SKIP_CDX = True
_SKIP_CC = True

def try_url(url: str, cat: dict) -> Optional[tuple[str, str, Optional[str], dict, str]]:
    """Return title, text, date, extra, used_url if this URL is the catalog law."""
    global _SKIP_ARCHIVE_IS, _SKIP_CDX, _SKIP_CC
    rec = live_fetch(url)
    if rec:
        title, text, date = rec["parsed"]
        if exact_heading(cat, title, text) and quality_ok(cat, text):
            return title, text, date, extra_for(rec, url, True), rec.get("final_url") or url
    # Timestamped Wayback FIRST (publication-era). Latest captures of xinwen are 404 shells.
    hint = ts_from_url(url)
    stamps = []
    if hint:
        y = int(hint[:4])
        if y < 2012:
            # NPC wxzl/gongbao live-404s were archived around 2018-2020, not in 2000.
            stamps.extend(["20180601120000", "20190101120000", "20200601120000"])
        else:
            stamps.append(hint)
            stamps.append(f"{min(y+1,2024):04d}0101120000")
            stamps.append(f"{y}0701120000")
    else:
        stamps.extend(["20190101120000", "20200601120000"])
    seen_ts = set()
    alts = [url]
    alt = url.replace("https://www.gov.cn", "http://www.gov.cn").replace("https://www.npc.gov.cn", "http://www.npc.gov.cn")
    if alt != url:
        alts.append(alt)
    for ts in stamps[:4]:
        key = ts or "latest"
        if key in seen_ts:
            continue
        seen_ts.add(key)
        rec = None
        for u in alts:
            rec = wayback_at(u, ts)
            if rec:
                break
        if not rec:
            continue
        title, text, date = rec["parsed"]
        if exact_heading(cat, title, text) and quality_ok(cat, text):
            rec["archive_method"] = "wayback"
            used = rec.get("wayback_url") or url
            return title, text, date, extra_for(rec, url, False), used
    if not _SKIP_CC:
        rec = cc_fetch(url)
        if rec:
            title, text, date = rec["parsed"]
            if exact_heading(cat, title, text) and quality_ok(cat, text):
                return title, text, date, extra_for(rec, url, False), url
    if not _SKIP_ARCHIVE_IS:
        rec = archive_is_fetch(url)
        if rec is None:
            # SSL/timeout: do not retry archive.is for the rest of the run
            _SKIP_ARCHIVE_IS = True
        elif rec:
            title, text, date = rec["parsed"]
            if exact_heading(cat, title, text) and quality_ok(cat, text):
                return title, text, date, extra_for(rec, url, False), rec.get("archive_url") or url
    return None


def ingest(cat: dict, title: str, text: str, extra: dict, used_url: str, miss_norms: dict, done: set, lock: threading.Lock) -> bool:
    ident = slug_id(CC, "law-" + title_key(cat["title"]))
    with lock:
        if ident in done or cat["norm"] not in miss_norms:
            return False
        extra = dict(extra or {})
        extra.setdefault("list_title", title)
        write_law(cat["title"], text, used_url, cat, extra)
        done.add(ident)
        miss_norms.pop(cat["norm"], None)
    log.info(
        "fill ok %s via %s chars=%s tiao=%s url=%s",
        cat["title"][:36], extra.get("method"), len(text or ""),
        len(TIAO_RE.findall(text or "")), (used_url or "")[:90],
    )
    return True


def main():
    setup()
    catalog = parse_catalog(download_catalog_pdf())
    done = existing_ids(CC)
    miss_norms = {}
    for cat in catalog:
        ident = slug_id(CC, "law-" + title_key(cat["title"]))
        if ident not in done:
            miss_norms[cat["norm"]] = cat
    log.info("harder start missing=%s have=%s catalog=%s", len(miss_norms), len(done), len(catalog))
    lock = threading.Lock()
    ok = fail = 0
    leftover = list(miss_norms.values())
    for i, cat in enumerate(leftover, 1):
        if cat["norm"] not in miss_norms:
            continue
        urls = candidate_urls(cat)
        log.info("title %s/%s %s urls=%s", i, len(leftover), cat["title"][:28], len(urls))
        got = False
        for url in urls:
            if cat["norm"] not in miss_norms:
                break
            try:
                hit = try_url(url, cat)
            except Exception as exc:
                log.info("try err %s %s", url[-50:], exc)
                hit = None
            if not hit:
                continue
            title, text, date, extra, used = hit
            if ingest(cat, title, text, extra, used, miss_norms, done, lock):
                ok += 1
                got = True
                break
        if not got:
            fail += 1
            log.info("miss %s", cat["title"][:40])
            log_failure(CC, {"identifier": cat["title"], "status": "failed", "reason": "harder:no_official_body"})
        if i % 5 == 0:
            log.info("progress %s/%s ok=%s remaining=%s", i, len(leftover), ok, len(miss_norms))

    dump_missing(miss_norms)
    n_json = len(list((ROOT / CC / "instruments").glob("*.json")))
    methods = {}
    backends = {}
    live = wayback = cc = 0
    for p in (ROOT / CC / "instruments").glob("*.json"):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        md = rec.get("metadata") or {}
        disc = md.get("discovery") or {}
        m = disc.get("method") or rec.get("source_type") or "?"
        methods[m] = methods.get(m, 0) + 1
        be = md.get("archive_method") or (md.get("text_extraction") or {}).get("backend")
        if be:
            backends[be] = backends.get(be, 0) + 1
        if m in ("npc_qwfb", "npc_qwfb_fill", "npc_qwfb_amendment", "govcn_search", "govcn_seed", "govcn_live", "npc_pdf", "moj_xzfg"):
            live += 1
        elif m == "archive-of-official":
            if be == "common_crawl":
                cc += 1
            else:
                wayback += 1
    atomic_write(
        ROOT / CC / "raw" / "method_counts.json",
        json.dumps({
            "methods": methods,
            "archive_backend": backends,
            "live_vs_archive": {"live_npc_qwfb_or_govcn": live, "wayback": wayback, "commoncrawl": cc},
            "instruments": n_json,
            "missing": len(miss_norms),
        }, ensure_ascii=False, indent=2) + "\n",
    )
    log.info("harder done ok=%s fail=%s instruments=%s remaining=%s methods=%s", ok, fail, n_json, len(miss_norms), methods)


if __name__ == "__main__":
    main()
