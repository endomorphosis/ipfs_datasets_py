#!/usr/bin/env python3
"""Last-10 NPC catalog 法律 fill. Official npc.gov.cn/gov.cn (+ ministry .gov.cn) only.

Does not crawl flk.npc.gov.cn. No pkulaw. No WAF bypass. Exact title match.
Does not mix 行政法规. Does not restage. Does not touch UK / PH / EU.
"""
from __future__ import annotations

import json
import logging
import re
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urljoin, quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, "/workspace/legal-corpora/hf-staging/ipfs_china_laws/scrapers")

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
)
from common import *  # noqa: F401,F403,E402
from fill_cn import dump_missing, pdf_to_text, canon_url  # noqa: E402
from fill_cn_leftover import SEEDS as LEFTOVER_SEEDS  # noqa: E402
import fill_cn_harder as H  # noqa: E402
from archive_fallbacks import (  # noqa: E402
    fetch_common_crawl_warc,
    get_archive_is_content,
    session as wb_session,
)

log = logging.getLogger("cn-last10")

# Ministry / gazette / 权威发布 URLs not previously tried (or previously 404 on old flfg).
NEW_SEEDS: dict[str, list[str]] = {
    "中华人民共和国气象法": [
        "http://fj.cma.gov.cn/zwgk/flfg/fl/201703/t20170313_4193.htm",
        "http://fj.cma.gov.cn/fzsqxj/zwgk/zfxxgkzl/zfxxgkml/zcfg/202009/t20200909_2076024.htm",
        "http://fj.cma.gov.cn/qzsqxj/zwgk/flfg/fl_1919/202312/t20231213_5948643.htm",
        "http://fj.cma.gov.cn/ptsqxj/zwgk/flfg/fl_1820/201812/t20181221_101264.htm",
        "https://www.cma.gov.cn/zfxxgk/gknr/flfgbz/fl/202005/t20200528_1694158.html",
        "http://www.cma.gov.cn/2011zwxx/2011flfg/2011flfgzcfg/201110/t20111027_135157.html",
        "https://www.cma.gov.cn/zfxxgk/gknr/flfgbz/flfg/201212/t20121219_194425.html",
        "http://gd.cma.gov.cn/yfsqxj/zwgk_3346/fgbz_3361/201808/t20180824_73779.html",
        "http://www.npc.gov.cn/zgrdw/npc/xinwen/2016-11/07/content_2003143.htm",
        "http://www.npc.gov.cn/npc/xinwen/2016-11/07/content_2003143.htm",
        "http://www.gov.cn/banshi/2005-08/31/content_24849.htm",
        "http://www.gov.cn/flfg/2005-08/05/content_20921.htm",
        "http://www.npc.gov.cn/wxzl/gongbao/2000-12/05/content_5004693.htm",
        "http://www.npc.gov.cn/wxzl/gongbao/2016-08/22/content_1995723.htm",
        "http://www.npc.gov.cn/englishnpc/Law/2007-12/12/content_1384215.htm",
    ],
    "中华人民共和国铁路法": [
        "https://www.nra.gov.cn/jglz/ysjg/fgys/202105/t20210519_198790.shtml",
        "https://www.nra.gov.cn/jglz/apjc/zcfg/202106/t20210624_198491.shtml",
        "http://www.nra.gov.cn/jglz/ysjg/fgys/202105/t20210519_198790.shtml",
        "http://www.gov.cn/banshi/2005-08/31/content_26781.htm",
        "http://www.gov.cn/flfg/2005-08/06/content_20909.htm",
        "http://www.npc.gov.cn/wxzl/gongbao/2015-07/03/content_1942870.htm",
        "http://www.npc.gov.cn/wxzl/gongbao/2000-12/05/content_5004686.htm",
        "http://www.npc.gov.cn/zgrdw/npc/xinwen/2015-04/24/content_1934598.htm",
        "http://www.npc.gov.cn/englishnpc/Law/2007-12/12/content_1383966.htm",
    ],
    "中华人民共和国中国人民银行法": [
        "https://www.pbc.gov.cn/tiaofasi/144941/144951/2817256/index.html",
        "http://www.pbc.gov.cn/fxqzhongxin/3558093/3558113/3557487/index.html",
        "https://www.pbc.gov.cn/tiaofasi/144941/144957/2817255/index.html",
        "http://www.pbc.gov.cn/tiaofasi/144941/144957/2817255/index.html",
        "http://www.gov.cn/ziliao/flfg/2005-09/12/content_31158.htm",
        "http://www.gov.cn/flfg/2003-12/27/content_121855.htm",
        "http://www.gov.cn/banshi/2005-08/31/content_26841.htm",
        "http://www.npc.gov.cn/wxzl/gongbao/2004-01/12/content_5327203.htm",
        "http://www.npc.gov.cn/wxzl/gongbao/2000-12/05/content_5004700.htm",
        "http://www.npc.gov.cn/englishnpc/Law/2007-12/12/content_1383938.htm",
    ],
    "全国人民代表大会常务委员会关于在沿海港口城市设立海事法院的决定": [
        "https://english.court.gov.cn/2016-04/14/c_1170191.htm",
        "http://english.court.gov.cn/2016-04/14/c_1170191.htm",
        "http://www.npc.gov.cn/wxzl/gongbao/2000-12/05/content_5004472.htm",
        "http://www.npc.gov.cn/wxzl/wxzl/2000-12/05/content_4500.htm",
        "http://www.npc.gov.cn/zgrdw/wxzl/gongbao/2000-12/05/content_5004472.htm",
        "http://www.npc.gov.cn/zgrdw/wxzl/wxzl/2000-12/05/content_4500.htm",
        "http://www.npc.gov.cn/englishnpc/Law/2007-12/12/content_1384072.htm",
        "http://www.npc.gov.cn/zgrdw/englishnpc/Law/2007-12/12/content_1384072.htm",
        "http://www.gov.cn/test/2006-02/24/content_212247.htm",
        "http://www.gov.cn/banshi/2005-08/05/content_20968.htm",
    ],
    "全国人民代表大会常务委员会关于批准中央军事委员会《关于授予军队离休干部中国人民解放军功勋荣誉章的规定》的决定": [
        "http://www.npc.gov.cn/wxzl/gongbao/2000-12/05/content_5004476.htm",
        "http://www.npc.gov.cn/wxzl/wxzl/2000-12/05/content_4501.htm",
        "http://www.npc.gov.cn/zgrdw/wxzl/gongbao/2000-12/05/content_5004476.htm",
        "http://www.npc.gov.cn/zgrdw/wxzl/wxzl/2000-12/05/content_4501.htm",
        "http://www.npc.gov.cn/englishnpc/Law/2007-12/12/content_1384073.htm",
        "http://www.gov.cn/test/2006-02/24/content_212248.htm",
    ],
    "全国人民代表大会常务委员会关于批准《国务院关于安置老弱病残干部的暂行办法》的决议": [
        "http://www.npc.gov.cn/wxzl/gongbao/2000-12/10/content_5004310.htm",
        "http://www.npc.gov.cn/wxzl/wxzl/2000-12/10/content_4270.htm",
        "http://www.npc.gov.cn/zgrdw/wxzl/gongbao/2000-12/10/content_5004310.htm",
        "http://www.npc.gov.cn/zgrdw/wxzl/wxzl/2000-12/10/content_4270.htm",
        "http://www.gov.cn/test/2006-02/24/content_212249.htm",
        "http://fgk.mof.gov.cn/ui/src/views/law_html/72931.html",
    ],
    "全国人民代表大会常务委员会关于批准《国务院关于老干部离职休养的暂行规定》的决议": [
        "http://www.npc.gov.cn/wxzl/gongbao/2000-12/10/content_5004311.htm",
        "http://www.npc.gov.cn/wxzl/wxzl/2000-12/10/content_4271.htm",
        "http://www.npc.gov.cn/zgrdw/wxzl/gongbao/2000-12/10/content_5004311.htm",
        "http://www.npc.gov.cn/zgrdw/wxzl/wxzl/2000-12/10/content_4271.htm",
        "http://www.gov.cn/test/2006-02/24/content_212250.htm",
    ],
    "全国人民代表大会常务委员会关于批准《广东省经济特区条例》的决议": [
        "http://fgk.mof.gov.cn/ui/src/views/law_html/72931.html",
        "http://www.npc.gov.cn/wxzl/gongbao/2000-12/10/content_5004312.htm",
        "http://www.npc.gov.cn/wxzl/wxzl/2000-12/05/content_4502.htm",
        "http://www.npc.gov.cn/zgrdw/wxzl/gongbao/2000-12/10/content_5004312.htm",
        "http://www.npc.gov.cn/zgrdw/wxzl/wxzl/2000-12/05/content_4502.htm",
        "http://www.gov.cn/test/2006-02/19/content_204600.htm",
        "http://www.gov.cn/test/2006-02/24/content_212251.htm",
        "http://www.npc.gov.cn/englishnpc/Law/2007-12/13/content_1383944.htm",
    ],
    "全国人民代表大会常务委员会关于批准《国务院关于工人退休、退职的暂行办法》的决议": [
        "http://www.npc.gov.cn/wxzl/gongbao/2000-12/10/content_5004313.htm",
        "http://www.npc.gov.cn/wxzl/wxzl/2000-12/10/content_4272.htm",
        "http://www.npc.gov.cn/zgrdw/wxzl/gongbao/2000-12/10/content_5004313.htm",
        "http://www.npc.gov.cn/zgrdw/wxzl/wxzl/2000-12/10/content_4272.htm",
        "http://www.gov.cn/test/2006-02/24/content_212252.htm",
        "http://www.gov.cn/banshi/2005-08/04/content_20213.htm",
    ],
    "全国人民代表大会常务委员会关于批准《国务院关于职工探亲待遇的规定》的决议": [
        "https://english.court.gov.cn/2015-08/17/c_1170098.htm",
        "http://www.npc.gov.cn/wxzl/gongbao/2000-12/10/content_5004314.htm",
        "http://www.npc.gov.cn/wxzl/wxzl/2000-12/10/content_4273.htm",
        "http://www.npc.gov.cn/zgrdw/wxzl/gongbao/2000-12/10/content_5004314.htm",
        "http://www.npc.gov.cn/zgrdw/wxzl/wxzl/2000-12/10/content_4273.htm",
        "http://www.gov.cn/test/2006-02/24/content_212253.htm",
        "http://www.gov.cn/banshi/2005-08/04/content_20255.htm",
        "https://www.gqb.gov.cn/news/2019/0604/46259.shtml",
        "http://www.npc.gov.cn/englishnpc/Law/2007-12/13/content_1383945.htm",
    ],
}

# Early gazette captures — 2018–2020 leftover snapshots were empty/wrong.
EARLY_TS = [
    "20080601120000",
    "20100601120000",
    "20120601120000",
    "20140601120000",
    "20160601120000",
    "20170601120000",
]
CC_INDEXES = [
    "http://index.commoncrawl.org/CC-MAIN-2014-41-index",
    "http://index.commoncrawl.org/CC-MAIN-2016-50-index",
    "http://index.commoncrawl.org/CC-MAIN-2017-51-index",
    "http://index.commoncrawl.org/CC-MAIN-2018-51-index",
    "http://index.commoncrawl.org/CC-MAIN-2019-51-index",
    "http://index.commoncrawl.org/CC-MAIN-2021-31-index",
]
GONGBAO_PDF_CANDIDATES = [
    # 国务院公报 historical PDFs (gov.cn). Issue numbers are best-effort.
    "http://www.gov.cn/gongbao/shuju/1978/gwyb197807.pdf",
    "http://www.gov.cn/gongbao/shuju/1978/gwyb197808.pdf",
    "http://www.gov.cn/gongbao/shuju/1980/gwyb198016.pdf",
    "http://www.gov.cn/gongbao/shuju/1980/gwyb198017.pdf",
    "http://www.gov.cn/gongbao/shuju/1981/gwyb198106.pdf",
    "http://www.gov.cn/gongbao/shuju/1981/gwyb198107.pdf",
    "http://www.gov.cn/gongbao/shuju/1984/gwyb198423.pdf",
    "http://www.gov.cn/gongbao/shuju/1984/gwyb198424.pdf",
    "http://www.gov.cn/gongbao/shuju/1988/gwyb198814.pdf",
    "http://www.gov.cn/gongbao/shuju/1988/gwyb198815.pdf",
]


def setup():
    H.setup()
    logging.getLogger("cn-last10").handlers = logging.getLogger("cn-harder").handlers
    logging.getLogger("cn-last10").setLevel(logging.INFO)


def alts(url: str) -> list[str]:
    out = [url]
    if url.startswith("https://"):
        out.append("http://" + url[len("https://"):])
    if url.startswith("http://"):
        out.append("https://" + url[len("http://"):])
    u2 = url.replace("://www.", "://")
    if u2 not in out:
        out.append(u2)
    return list(dict.fromkeys(out))


def parse_any(rec: dict, url: str) -> tuple[str, str, Optional[str]]:
    return H.parse_rec(rec, url)


def try_live(url: str) -> Optional[dict]:
    rec = H.live_fetch(url)
    return rec


def try_early_wayback(url: str) -> Optional[dict]:
    for ts in EARLY_TS:
        rec = H.wayback_at(url, ts)
        if rec:
            title, text, date = rec.get("parsed") or ("", "", None)
            # skip 404 shells / JS challenge / empty gazette chrome
            if not text or len(text) < 200:
                continue
            if "Just a moment" in (text or "")[:400]:
                continue
            if "Please enable JavaScript" in (text or "")[:800] and "第一条" not in (text or ""):
                continue
            # 2018-2020 empty/wrong leftover: skip if capture is in that window AND body is a listing/404
            cap = rec.get("capture_timestamp") or ts
            if cap[:4] in ("2018", "2019", "2020") and "第一条" not in (text or "") and "批准" not in (text or "")[:400]:
                continue
            return rec
    return None


def try_cc(url: str) -> Optional[dict]:
    hostpath = url
    for prefix in ("https://", "http://"):
        if hostpath.startswith(prefix):
            hostpath = hostpath[len(prefix):]
            break
    for idx in CC_INDEXES:
        time.sleep(0.35)
        try:
            r = wb_session().get(
                idx,
                params={"url": hostpath, "output": "json", "limit": "3", "filter": "status:200"},
                timeout=(12, 22),
            )
        except Exception as exc:
            log.info("cc idx fail %s %s", idx.split("/")[-1], exc)
            continue
        if r.status_code != 200 or not r.content:
            continue
        hits = []
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
            hits.append(rec)
        for hit in hits[:2]:
            try:
                rec = fetch_common_crawl_warc(hit)
            except Exception as exc:
                log.info("warc fail %s", exc)
                continue
            if rec.get("status") != "success":
                continue
            title, text, date = parse_any(rec, url)
            if text and len(text) >= 200:
                rec["parsed"] = (title, text, date)
                rec["archive_method"] = "common_crawl"
                return rec
        if hits:
            break
    return None


def try_archive_is(url: str) -> Optional[dict]:
    try:
        rec = get_archive_is_content(url)
    except Exception as exc:
        log.info("archive.is err %s", exc)
        return None
    if rec.get("status") != "success":
        return None
    title, text, date = parse_any(rec, url)
    if text and len(text) >= 200:
        rec["parsed"] = (title, text, date)
        rec["archive_method"] = "archive_is"
        return rec
    return None


def accept(cat: dict, title: str, text: str) -> bool:
    if not H.exact_heading(cat, title, text):
        return False
    if not H.quality_ok(cat, text):
        return False
    # Do not ingest a 行政法规 暂行办法/规定 as if it were the NPC 决议.
    if any(x in cat["title"] for x in ("决议", "决定")):
        blob = (title or "") + "\n" + (text or "")[:800]
        if "全国人民代表大会" not in blob and "全国人大常委会" not in blob:
            return False
    return True


def try_url_all(url: str, cat: dict) -> Optional[tuple]:
    if "flk.npc.gov.cn" in (url or ""):
        return None
    if not official_host(url) and "xzfg.moj.gov.cn" not in url and "fgk.mof.gov.cn" not in url:
        # fgk.mof.gov.cn is .gov.cn so official_host should accept
        if not official_host(url):
            return None
    rec = try_live(url)
    if rec:
        title, text, date = rec["parsed"]
        if accept(cat, title, text):
            return title, text, date, H.extra_for(rec, url, True), rec.get("final_url") or url
    rec = try_early_wayback(url)
    if rec:
        title, text, date = rec["parsed"]
        if accept(cat, title, text):
            rec["archive_method"] = "wayback"
            return title, text, date, H.extra_for(rec, url, False), rec.get("wayback_url") or url
    rec = try_cc(url)
    if rec:
        title, text, date = rec["parsed"]
        if accept(cat, title, text):
            return title, text, date, H.extra_for(rec, url, False), url
    rec = try_archive_is(url)
    if rec:
        title, text, date = rec["parsed"]
        if accept(cat, title, text):
            return title, text, date, H.extra_for(rec, url, False), rec.get("archive_url") or url
    return None


def mof_fgk_search(title: str) -> list[str]:
    urls = []
    q = title[:40]
    for endpoint in (
        "http://fgk.mof.gov.cn/ui/src/views/lawSearch.html",
        "https://fgk.mof.gov.cn/ui/src/views/lawSearch.html",
    ):
        try:
            r = wb_session().get(endpoint, params={"title": q}, timeout=(12, 20))
        except Exception:
            continue
        if r.status_code != 200:
            continue
        html = r.text or ""
        for href in re.findall(r'href="([^"]*law_html/\d+\.html)"', html):
            if href.startswith("http"):
                urls.append(href)
            else:
                urls.append(urljoin("http://fgk.mof.gov.cn", href))
        if urls:
            break
    return urls[:6]


def npc_english_listing() -> list[tuple[str, str]]:
    """NPC English laws index — look for Chinese PDF / 中文 links."""
    pages = [
        "http://www.npc.gov.cn/englishnpc/lawsoftheprc/",
        "http://www.npc.gov.cn/englishnpc/lawsoftheprc/index.html",
        "http://www.npc.gov.cn/englishnpc/Law/",
        "http://www.npc.gov.cn/zgrdw/englishnpc/Law/node_8237.htm",
        "http://www.npc.gov.cn/englishnpc/c23934/list.shtml",
    ]
    links = []
    for page in pages:
        try:
            r = npc_get(page, retries=1, timeout=(12, 25), sleep=0.3)
        except Exception as exc:
            log.info("en list err %s %s", page[-40:], exc)
            continue
        if r.status_code != 200 or not r.content:
            continue
        html = r.text or ""
        for href, lab in re.findall(r'href="([^"]+)"[^>]*>([^<]{3,120})', html):
            full = urljoin(page, href)
            if "flk.npc.gov.cn" in full:
                continue
            if not official_host(full):
                continue
            links.append((full, lab.strip()))
        # PDFs
        for href in re.findall(r'href="([^"]+\.pdf)"', html, re.I):
            full = urljoin(page, href)
            if official_host(full):
                links.append((full, href.split("/")[-1]))
    return links


def gongbao_pdf_try(cat: dict) -> Optional[tuple]:
    want = cat["norm"]
    for url in GONGBAO_PDF_CANDIDATES:
        try:
            r = npc_get(url, retries=1, timeout=(12, 30), sleep=0.3)
        except Exception as exc:
            log.info("gb pdf err %s %s", url[-40:], exc)
            continue
        if r.status_code != 200 or not r.content:
            continue
        if r.content[:4] != b"%PDF":
            continue
        text = pdf_to_text(r.content)
        if not text or want not in norm_title(text[:2500]) and want not in norm_title(text):
            # still check heading_norms
            title = ""
            m = re.search(r"全国人民代表大会常务委员会关于[^\n]{8,80}", text or "")
            if m:
                title = m.group(0).strip()
            if not accept(cat, title, text):
                log.info("gb pdf no-match %s chars=%s", url[-40:], len(text or ""))
                continue
        title = cat["title"]
        # prefer a heading from the PDF
        m = re.search(re.escape(cat["title"][:20]) + r"[^\n]{0,60}", text or "")
        if m:
            title = m.group(0).strip()
        if accept(cat, title, text) or (want in heading_norms(title, text) and H.quality_ok(cat, text)):
            rec = {"parsed": (title, text, parse_zh_date(text[:1200])), "method": "live", "content": r.content}
            extra = H.extra_for(rec, url, True)
            extra["method"] = "govcn_live"
            return title, text, rec["parsed"][2], extra, url
    return None


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
        seen.add(u)
        urls.append(u)

    for u in NEW_SEEDS.get(title, []):
        add(u)
    for u in LEFTOVER_SEEDS.get(title, []):
        add(u)
    for u in H.EXTRA_SEEDS.get(title, []):
        add(u)
    for u in H.candidate_urls(cat):
        add(u)
    return urls


def main():
    setup()
    H._SKIP_CC = False
    H._SKIP_CDX = True
    H._SKIP_ARCHIVE_IS = False

    catalog = parse_catalog(download_catalog_pdf())
    done = existing_ids(CC)
    miss_norms = {}
    for cat in catalog:
        ident = slug_id(CC, "law-" + title_key(cat["title"]))
        if ident not in done:
            miss_norms[cat["norm"]] = cat
    log.info("last10 start missing=%s have=%s", len(miss_norms), len(done))
    lock = threading.Lock()
    ok = 0

    leftover = list(miss_norms.values())

    # 1) live ministry / new seeds first (no archive hammer)
    for i, cat in enumerate(leftover, 1):
        if cat["norm"] not in miss_norms:
            continue
        urls = candidate_urls(cat)
        log.info("title %s/%s %s urls=%s", i, len(leftover), cat["title"][:36], len(urls))
        got = False
        # live first
        for url in urls:
            if cat["norm"] not in miss_norms:
                break
            rec = try_live(url)
            if not rec:
                continue
            title, text, date = rec["parsed"]
            if accept(cat, title, text):
                extra = H.extra_for(rec, url, True)
                if H.ingest(cat, title, text, extra, rec.get("final_url") or url, miss_norms, done, lock):
                    ok += 1
                    got = True
                    break
            else:
                log.info("live no-match %s title=%r chars=%s tiao=%s url=%s",
                         cat["title"][:18], (title or "")[:40], len(text or ""),
                         len(H.TIAO_RE.findall(text or "")), url[-55:])
        if got:
            continue
        # searches
        try:
            for u in H.xzfg_search(cat["title"]):
                urls.append(u) if u not in urls else None
        except Exception as exc:
            log.info("xzfg err %s", exc)
        try:
            for u in H.govcn_exact_search(cat["title"]):
                if u not in urls:
                    urls.append(u)
        except Exception as exc:
            log.info("govcn search err %s", exc)
        try:
            for u in mof_fgk_search(cat["title"]):
                if u not in urls:
                    urls.append(u)
        except Exception as exc:
            log.info("mof err %s", exc)
        # archives for remaining urls (polite, few)
        archive_urls = urls[:12]
        for url in archive_urls:
            if cat["norm"] not in miss_norms:
                break
            try:
                hit = try_url_all(url, cat)
            except Exception as exc:
                log.info("try err %s %s", url[-50:], exc)
                hit = None
            if not hit:
                continue
            title, text, date, extra, used = hit
            if H.ingest(cat, title, text, extra, used, miss_norms, done, lock):
                ok += 1
                got = True
                break
        if not got:
            log.info("miss after seeds %s", cat["title"][:40])

    # 2) NPC English listing -> Chinese PDFs / 中文 links
    if miss_norms:
        log.info("npc english listing remaining=%s", len(miss_norms))
        try:
            links = npc_english_listing()
        except Exception as exc:
            log.info("en listing fail %s", exc)
            links = []
        log.info("en links n=%s", len(links))
        for href, lab in links:
            if not miss_norms:
                break
            nt = norm_title(lab)
            cat = miss_norms.get(nt) or miss_norms.get(re.sub(r"（.*$", "", nt))
            # English titles won't match; still fetch PDFs
            if href.lower().endswith(".pdf") or cat:
                targets = list(miss_norms.values()) if href.lower().endswith(".pdf") else [cat]
                try:
                    rec = try_live(href)
                except Exception:
                    rec = None
                if not rec:
                    continue
                title, text, date = rec["parsed"]
                for c in targets:
                    if c["norm"] not in miss_norms:
                        continue
                    if accept(c, title, text):
                        extra = H.extra_for(rec, href, True)
                        if H.ingest(c, title, text, extra, rec.get("final_url") or href, miss_norms, done, lock):
                            ok += 1
                            break

    # 3) 国务院公报 PDFs for remaining 决议
    if miss_norms:
        log.info("gongbao pdf remaining=%s", len(miss_norms))
        for cat in list(miss_norms.values()):
            if cat["norm"] not in miss_norms:
                continue
            if not any(x in cat["title"] for x in ("决议", "决定")):
                continue
            try:
                hit = gongbao_pdf_try(cat)
            except Exception as exc:
                log.info("gb pdf try err %s", exc)
                hit = None
            if not hit:
                continue
            title, text, date, extra, used = hit
            if H.ingest(cat, title, text, extra, used, miss_norms, done, lock):
                ok += 1

    dump_missing(miss_norms)
    n_json = len(list((ROOT / CC / "instruments").glob("*.json")))
    log.info("last10 done ok=%s instruments=%s remaining=%s", ok, n_json, len(miss_norms))
    for t in miss_norms.values():
        log.info("  still %s", t["title"])
    landed = []
    # report via stdout as well
    print(json.dumps({
        "ok": ok,
        "instruments": n_json,
        "remaining": [t["title"] for t in miss_norms.values()],
        "remaining_n": len(miss_norms),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
