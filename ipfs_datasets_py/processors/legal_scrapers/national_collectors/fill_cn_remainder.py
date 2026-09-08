#!/usr/bin/env python3
"""Remainder fill: live NPC statute pages + 2018-2020 gongbao Wayback.

Does not crawl flk.npc.gov.cn. Exact catalog title. Do not restage here.
"""
from __future__ import annotations

import json
import logging
import re
import sys
import threading
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from collect_cn import (  # noqa: E402
    CC,
    download_catalog_pdf,
    npc_get,
    norm_title,
    parse_catalog,
    title_key,
)
from common import *  # noqa: F401,F403,E402
from fill_cn import dump_missing  # noqa: E402
from fill_cn_leftover import SEEDS as LEFTOVER_SEEDS  # noqa: E402
import fill_cn_harder as H  # noqa: E402

log = logging.getLogger("cn-remainder")

MORE_SEEDS: dict[str, list[str]] = {
    "中华人民共和国城市维护建设税法": [
        "http://www.npc.gov.cn/npc/c2/c30834/202008/t20200811_307180.html",
        "http://www.npc.gov.cn/c2/c30834/202008/t20200811_307180.html",
    ],
    "中华人民共和国烟叶税法": [
        "http://www.npc.gov.cn/c2/c12435/c12488/201905/t20190521_271474.html",
        "http://www.npc.gov.cn/npc/c2/c12435/c12488/201905/t20190521_271474.html",
        "http://www.npc.gov.cn/zgrdw/npc/xinwen/2017-12/27/content_2035710.htm",
        "http://www.npc.gov.cn/npc/xinwen/2017-12/27/content_2035710.htm",
    ],
    "中华人民共和国水土保持法": [
        "http://www.npc.gov.cn/c1773/c2518/c27694/c27698/201905/t20190521_178403.html",
        "http://www.npc.gov.cn/npc/c1773/c2518/c27694/c27698/201905/t20190521_178403.html",
    ],
    "中华人民共和国戒严法": [
        "http://www.npc.gov.cn/zgrdw/huiyi/lfzt/rmwzjcf/2009-04/16/content_1497945.htm",
        "http://www.npc.gov.cn/huiyi/lfzt/rmwzjcf/2009-04/16/content_1497945.htm",
    ],
    "中华人民共和国煤炭法": [
        "http://www.npc.gov.cn/npc/c1772/c21116/c21297/c21305/201905/t20190521_180141.html",
        "http://www.npc.gov.cn/c1772/c21116/c21297/c21305/201905/t20190521_180141.html",
        "http://www.npc.gov.cn/npc/c2/c12435/c12488/201905/t20190522_71132.html",
        "http://www.npc.gov.cn/zgrdw/npc/xinwen/2011-04/25/content_1653737.htm",
    ],
    "中华人民共和国人民调解法": [
        "http://www.npc.gov.cn/npc/c2/c10134/201905/t20190522_175671.html",
        "http://www.npc.gov.cn/cwhhdbdh/c4186/c13942/c13947/201905/t20190523_399453.html",
        "http://www.npc.gov.cn/npc/cwhhdbdh/c4186/c13942/c13947/201905/t20190523_399453.html",
    ],
    "中华人民共和国领事特权与豁免条例": [
        "http://www.npc.gov.cn/npc/c34354/xgjbfwyh/xgjbfwyh002/xgjbfwyh005/202210/t20221013_45460.html",
        "http://www.npc.gov.cn/npc/c2597/c1776/c2797/201905/t20190522_21579.html",
        "http://www.npc.gov.cn/c2597/c1776/c2797/201905/t20190522_21579.html",
    ],
    "中华人民共和国驻外外交人员法": [
        "http://www.npc.gov.cn/c2/c183/c198/201905/t20190522_75686.html",
        "http://www.npc.gov.cn/npc/c2/c183/c198/201905/t20190522_75686.html",
        "http://www.npc.gov.cn/c2/c12435/c12488/201905/t20190522_64192.html",
        "http://www.npc.gov.cn/cwhhdbdh/c4186/c10957/c10962/201905/t20190523_398532.html",
    ],
    "中华人民共和国农村土地承包经营纠纷调解仲裁法": [
        "http://www.npc.gov.cn/zgrdw/npc/lfzt/rlyw/2017-11/02/content_2031277.htm",
        "http://www.npc.gov.cn/npc/c2/c12435/c12488/201905/t20190522_61926.html",
        "http://www.npc.gov.cn/npc/c1773/c1848/c21114/c33374/c33377/201905/t20190521_261041.html",
        "http://www.npc.gov.cn/c1773/c1848/c21114/c33374/c33377/201905/t20190521_261041.html",
    ],
    "中华人民共和国石油天然气管道保护法": [
        "http://www.npc.gov.cn/zgrdw/huiyi/cwh/1115/2010-06/25/content_1579552.htm",
        "http://www.npc.gov.cn/c2/c10134/201905/t20190522_175388.html",
        "http://www.npc.gov.cn/npc/c2/c10134/201905/t20190522_175388.html",
    ],
    "中华人民共和国气象法": [
        "http://www.npc.gov.cn/npc/c2/c12435/c12488/201905/t20190521_271200.html",
        "http://www.npc.gov.cn/zgrdw/npc/xinwen/2016-11/07/content_2003143.htm",
    ],
    "中华人民共和国铁路法": [
        "http://www.npc.gov.cn/npc/c2/c12435/c12488/201905/t20190522_71000.html",
        "http://www.npc.gov.cn/zgrdw/npc/xinwen/2015-04/24/content_1934598.htm",
    ],
    "中华人民共和国中国人民银行法": [
        "http://www.npc.gov.cn/npc/c2/c12435/c12488/201905/t20190521_222000.html",
        "http://www.pbc.gov.cn/tiaofasi/144941/144957/2817255/index.html",
    ],
}

LISTINGS = [
    "http://www.npc.gov.cn/npc/c2/c12435/c12488/index.html",
    "http://www.npc.gov.cn/npc/c2/c12435/c12489/index.html",
]

REJECT_LIST = re.compile(r"(草案|审议结果|修改意见|的说明|解读|答记者问|新闻发布)")


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self._href = None
        self._buf = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            d = dict(attrs)
            self._href = d.get("href")
            self._buf = []

    def handle_data(self, data):
        if self._href is not None:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            t = "".join(self._buf).strip()
            self.links.append((self._href, t))
            self._href = None


def parse_links(html: str, base: str) -> list[tuple[str, str]]:
    p = LinkParser()
    try:
        p.feed(html or "")
    except Exception:
        pass
    out = []
    for href, t in p.links:
        if not href or href.startswith("javascript"):
            continue
        out.append((urljoin(base, href), t))
    return out


def listing_pages(index_url: str) -> list[str]:
    urls = [index_url]
    if index_url.endswith("index.html"):
        stem = index_url[: -len("index.html")]
        for i in range(2, 50):
            urls.append(f"{stem}index_{i}.html")
    return urls


def try_ingest(cat, url, miss_norms, done, lock) -> bool:
    hit = H.try_url(url, cat)
    if not hit:
        return False
    title, text, date, extra, used = hit
    return H.ingest(cat, title, text, extra, used, miss_norms, done, lock)


def main():
    H.setup()
    logging.getLogger("cn-remainder").handlers = logging.getLogger("cn-harder").handlers
    logging.getLogger("cn-remainder").setLevel(logging.INFO)
    H._SKIP_CC = False
    H._SKIP_CDX = True
    H._SKIP_ARCHIVE_IS = True

    catalog = parse_catalog(download_catalog_pdf())
    done = existing_ids(CC)
    miss_norms = {}
    for cat in catalog:
        ident = slug_id(CC, "law-" + title_key(cat["title"]))
        if ident not in done:
            miss_norms[cat["norm"]] = cat
    log.info("remainder start missing=%s have=%s", len(miss_norms), len(done))
    lock = threading.Lock()
    ok = 0

    leftover = list(miss_norms.values())
    for i, cat in enumerate(leftover, 1):
        if cat["norm"] not in miss_norms:
            continue
        urls = []
        seen = set()

        def add(u):
            u = H.canon_url(u)
            if not u or u in seen or "flk.npc.gov.cn" in u:
                return
            seen.add(u)
            urls.append(u)

        for u in MORE_SEEDS.get(cat["title"], []):
            add(u)
        for u in H.candidate_urls(cat):
            add(u)
        log.info("title %s/%s %s urls=%s", i, len(leftover), cat["title"][:32], len(urls))
        got = False
        for url in urls:
            if cat["norm"] not in miss_norms:
                break
            try:
                if try_ingest(cat, url, miss_norms, done, lock):
                    ok += 1
                    got = True
                    break
            except Exception as exc:
                log.info("try err %s %s", url[-60:], exc)
        if not got:
            log.info("miss seeds %s", cat["title"][:40])

    # listing crawl for remaining
    remaining_by_norm = dict(miss_norms)
    for index_url in LISTINGS:
        if not remaining_by_norm:
            break
        log.info("listing %s", index_url)
        for page in listing_pages(index_url):
            if not remaining_by_norm:
                break
            try:
                r = npc_get(page, retries=1, timeout=(15, 40), sleep=0.25)
            except Exception as exc:
                log.info("list err %s %s", page[-40:], exc)
                continue
            if r.status_code != 200 or not r.content:
                continue
            if len(r.content) > 80000:
                log.info("homepage-size stop %s bytes=%s", page, len(r.content))
                break
            html = r.text or ""
            if "Please enable JavaScript" in html[:2000] and "第一条" not in html:
                log.info("js challenge %s", page[-50:])
                continue
            links = parse_links(html, page)
            hits = []
            for href, lab in links:
                if REJECT_LIST.search(lab or ""):
                    continue
                nt = norm_title(lab)
                nt2 = re.sub(r"（.*$", "", nt)
                cat = remaining_by_norm.get(nt) or remaining_by_norm.get(nt2)
                if cat:
                    hits.append((cat, href, lab))
            if hits:
                log.info("page hits %s n=%s", page[-40:], len(hits))
            for cat, href, lab in hits:
                if cat["norm"] not in miss_norms:
                    continue
                try:
                    if try_ingest(cat, href, miss_norms, done, lock):
                        ok += 1
                        remaining_by_norm.pop(cat["norm"], None)
                except Exception as exc:
                    log.info("list ingest err %s", exc)

    dump_missing(miss_norms)
    n_json = len(list((ROOT / CC / "instruments").glob("*.json")))
    log.info("remainder done ok=%s instruments=%s remaining=%s", ok, n_json, len(miss_norms))
    for t in miss_norms.values():
        log.info("  still %s", t["title"])


if __name__ == "__main__":
    main()
