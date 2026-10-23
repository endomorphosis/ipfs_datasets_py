#!/usr/bin/env python3
"""Targeted Wayback of official npc.gov.cn/gov.cn URLs for leftover catalog titles.
Skips Common Crawl (indexes SSL-fail). Does not crawl flk.npc.gov.cn.
"""
from __future__ import annotations

import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from collect_cn import (
    CC, download_catalog_pdf, parse_catalog, title_key, looks_like_statute,
)
from common import *
from fill_cn import (
    setup, fetch_one_url, ingest, dump_missing, accept_body, log as fill_log,
)
import threading

log = logging.getLogger("cn-leftover")

# Remaining catalog titles -> official npc.gov.cn / gov.cn URLs (live often 404; Wayback of same URL).
SEEDS: dict[str, list[str]] = {
    "中华人民共和国国歌法": [
        "http://www.gov.cn/xinwen/2017-09/05/content_5222714.htm",
        "https://www.gov.cn/xinwen/2017-09/05/content_5222714.htm",
    ],
    "中华人民共和国人民陪审员法": [
        "http://www.gov.cn/xinwen/2018-04/28/content_5286643.htm",
        "https://www.gov.cn/xinwen/2018-04/28/content_5286643.htm",
    ],
    "中华人民共和国英雄烈士保护法": [
        "http://www.gov.cn/xinwen/2018-04/28/content_5286644.htm",
        "https://www.gov.cn/xinwen/2018-04/27/content_5286325.htm",
    ],
    "中华人民共和国涉外民事关系法律适用法": [
        "http://www.gov.cn/flfg/2010-10/28/content_1732970.htm",
        "https://www.gov.cn/flfg/2010-10/28/content_1732970.htm",
    ],
    "中华人民共和国驻外外交人员法": [
        "http://www.gov.cn/flfg/2009-10/31/content_1433387.htm",
        "http://www.npc.gov.cn/wxzl/gongbao/2009-12/16/content_1543774.htm",
    ],
    "中华人民共和国精神卫生法": [
        "http://www.gov.cn/flfg/2012-10/26/content_2252122.htm",
        "https://www.gov.cn/xinwen/2018-10/26/content_5334834.htm",
        "http://www.gov.cn/xinwen/2018-10/26/content_5334834.htm",
    ],
    "中华人民共和国国防交通法": [
        "http://www.gov.cn/xinwen/2016-09/03/content_5105267.htm",
        "https://www.gov.cn/xinwen/2016-09/03/content_5105267.htm",
    ],
    "中华人民共和国电影产业促进法": [
        "http://www.gov.cn/xinwen/2016-11/07/content_5129783.htm",
        "https://www.gov.cn/xinwen/2016-11/07/content_5129783.htm",
    ],
    "中华人民共和国国家情报法": [
        "http://www.gov.cn/xinwen/2017-06/28/content_5206186.htm",
        "https://www.gov.cn/xinwen/2018-06/12/content_5298400.htm",
        "http://www.gov.cn/xinwen/2018-06/27/content_5301640.htm",
    ],
    "中华人民共和国消防救援衔条例": [
        "http://www.gov.cn/xinwen/2018-10/27/content_5335037.htm",
        "https://www.gov.cn/xinwen/2018-10/27/content_5335037.htm",
    ],
    "中华人民共和国海警法": [
        "http://www.gov.cn/xinwen/2021-01/23/content_5581963.htm",
        "https://www.gov.cn/xinwen/2021-01/23/content_5581963.htm",
    ],
    "中华人民共和国反食品浪费法": [
        "http://www.gov.cn/xinwen/2021-04/29/content_5603720.htm",
        "https://www.gov.cn/xinwen/2021-04/29/content_5603720.htm",
    ],
    "中华人民共和国军人地位和权益保障法": [
        "http://www.gov.cn/xinwen/2021-06/10/content_5616837.htm",
        "https://www.gov.cn/xinwen/2021-06/10/content_5616837.htm",
    ],
    "中华人民共和国石油天然气管道保护法": [
        "http://www.gov.cn/flfg/2010-06/25/content_1637651.htm",
        "https://www.gov.cn/flfg/2010-06/25/content_1637651.htm",
    ],
    "中华人民共和国航道法": [
        "http://www.gov.cn/xinwen/2014-12/29/content_2798074.htm",
        "https://www.gov.cn/xinwen/2016-07/02/content_5085854.htm",
        "http://www.gov.cn/xinwen/2016-07/02/content_5085854.htm",
    ],
    "中华人民共和国资产评估法": [
        "http://www.gov.cn/xinwen/2016-07/03/content_5087646.htm",
        "https://www.gov.cn/xinwen/2016-07/03/content_5087646.htm",
    ],
    "中华人民共和国烟叶税法": [
        "http://www.gov.cn/xinwen/2017-12/27/content_5250811.htm",
        "https://www.gov.cn/xinwen/2017-12/27/content_5250811.htm",
    ],
    "中华人民共和国电子商务法": [
        "http://www.gov.cn/xinwen/2018-08/31/content_5317951.htm",
        "https://www.gov.cn/xinwen/2018-08/31/content_5317951.htm",
        "https://www.gov.cn/xinwen/2018-08/31/content_5318048.htm",
    ],
    "中华人民共和国城市维护建设税法": [
        "http://www.gov.cn/xinwen/2020-08/11/content_5534079.htm",
        "https://www.gov.cn/xinwen/2020-08/11/content_5534079.htm",
    ],
    "中华人民共和国出口管制法": [
        "http://www.gov.cn/xinwen/2020-10/18/content_5552111.htm",
        "https://www.gov.cn/xinwen/2020-10/18/content_5552111.htm",
    ],
    "中华人民共和国数据安全法": [
        "http://www.gov.cn/xinwen/2021-06/11/content_5616919.htm",
        "https://www.gov.cn/xinwen/2021-06/11/content_5616919.htm",
    ],
    "中华人民共和国海南自由贸易港法": [
        "http://www.gov.cn/xinwen/2021-06/11/content_5616918.htm",
        "https://www.gov.cn/xinwen/2021-06/11/content_5616918.htm",
    ],
    "中华人民共和国红十字会法": [
        "http://www.gov.cn/xinwen/2017-05/25/content_5196779.htm",
        "https://www.gov.cn/xinwen/2017-05/25/content_5196779.htm",
        "http://www.npc.gov.cn/wxzl/gongbao/1993-10/31/content_1481303.htm",
    ],
    "中华人民共和国军人保险法": [
        "http://www.gov.cn/flfg/2012-04/27/content_2148531.htm",
        "https://www.gov.cn/flfg/2012-04/27/content_2148531.htm",
    ],
    "中华人民共和国反家庭暴力法": [
        "http://www.gov.cn/xinwen/2015-12/28/content_5028402.htm",
        "https://www.gov.cn/xinwen/2015-12/28/content_5028402.htm",
    ],
    "中华人民共和国境外非政府组织境内活动管理法": [
        "http://www.gov.cn/xinwen/2016-04/29/content_5069136.htm",
        "https://www.gov.cn/xinwen/2017-11/04/content_5237321.htm",
        "http://www.gov.cn/xinwen/2017-11/04/content_5237321.htm",
    ],
    "中华人民共和国退役军人保障法": [
        "http://www.gov.cn/xinwen/2020-11/11/content_5560401.htm",
        "https://www.gov.cn/xinwen/2020-11/11/content_5560401.htm",
    ],
    "中华人民共和国水土保持法": [
        "http://www.gov.cn/flfg/2010-12/25/content_1773570.htm",
        "https://www.gov.cn/flfg/2010-12/25/content_1773570.htm",
        "http://www.npc.gov.cn/wxzl/gongbao/2011-02/24/content_1625671.htm",
    ],
    "中华人民共和国煤炭法": [
        "http://www.gov.cn/xinwen/2016-11/07/content_5129589.htm",
        "https://www.gov.cn/xinwen/2016-11/07/content_5129589.htm",
        "http://www.gov.cn/flfg/2011-04/22/content_1851695.htm",
    ],
    "中华人民共和国海岛保护法": [
        "http://www.gov.cn/flfg/2009-12/26/content_1497461.htm",
        "https://www.gov.cn/flfg/2009-12/26/content_1497461.htm",
    ],
    "中华人民共和国深海海底区域资源勘探开发法": [
        "http://www.gov.cn/xinwen/2016-02/26/content_5046540.htm",
        "https://www.gov.cn/xinwen/2016-02/26/content_5046540.htm",
    ],
    "中华人民共和国农村土地承包经营纠纷调解仲裁法": [
        "http://www.gov.cn/flfg/2009-06/27/content_1351686.htm",
        "https://www.gov.cn/flfg/2009-06/27/content_1351686.htm",
    ],
    "中华人民共和国人民调解法": [
        "http://www.gov.cn/flfg/2010-08/28/content_1690713.htm",
        "https://www.gov.cn/flfg/2010-08/28/content_1690713.htm",
    ],
    "中华人民共和国领事特权与豁免条例": [
        "http://www.gov.cn/ziliao/flfg/2005-05/25/content_947.htm",
        "http://www.npc.gov.cn/wxzl/gongbao/2000-12/06/content_5004475.htm",
        "http://www.npc.gov.cn/wxzl/wxzl/2000-12/05/content_4549.htm",
        "http://www.gov.cn/banshi/2005-08/21/content_25051.htm",
    ],
    "中华人民共和国戒严法": [
        "http://www.npc.gov.cn/wxzl/gongbao/2000-12/05/content_5004546.htm",
        "http://www.npc.gov.cn/wxzl/wxzl/2000-12/05/content_4560.htm",
        "http://www.gov.cn/banshi/2005-08/21/content_25050.htm",
        "http://www.gov.cn/ziliao/flfg/2005-05/25/content_927.htm",
    ],
    "中华人民共和国国家勋章和国家荣誉称号法": [
        "http://www.gov.cn/xinwen/2015-12/27/content_5028162.htm",
        "https://www.gov.cn/xinwen/2015-12/27/content_5028162.htm",
        "http://www.gov.cn/xinwen/2021-03/09/content_5591890.htm",
    ],
    "中国人民解放军选举全国人民代表大会和县级以上地方各级人民代表大会代表的办法": [
        "http://www.npc.gov.cn/wxzl/gongbao/2000-12/05/content_5004471.htm",
        "http://www.npc.gov.cn/wxzl/wxzl/2000-12/10/content_4269.htm",
        "http://www.gov.cn/banshi/2005-05/25/content_980.htm",
    ],
    "全国人民代表大会常务委员会关于在沿海港口城市设立海事法院的决定": [
        "http://www.npc.gov.cn/wxzl/gongbao/2000-12/05/content_5004472.htm",
        "http://www.npc.gov.cn/wxzl/wxzl/2000-12/05/content_4500.htm",
    ],
    "全国人民代表大会常务委员会关于批准中央军事委员会《关于授予军队离休干部中国人民解放军功勋荣誉章的规定》的决定": [
        "http://www.npc.gov.cn/wxzl/gongbao/2000-12/05/content_5004476.htm",
        "http://www.npc.gov.cn/wxzl/wxzl/2000-12/05/content_4501.htm",
    ],
    "全国人民代表大会常务委员会关于批准《国务院关于安置老弱病残干部的暂行办法》的决议": [
        "http://www.npc.gov.cn/wxzl/gongbao/2000-12/10/content_5004310.htm",
        "http://www.npc.gov.cn/wxzl/wxzl/2000-12/10/content_4270.htm",
    ],
    "全国人民代表大会常务委员会关于批准《国务院关于老干部离职休养的暂行规定》的决议": [
        "http://www.npc.gov.cn/wxzl/gongbao/2000-12/10/content_5004311.htm",
        "http://www.npc.gov.cn/wxzl/wxzl/2000-12/10/content_4271.htm",
    ],
    "全国人民代表大会常务委员会关于批准《广东省经济特区条例》的决议": [
        "http://www.npc.gov.cn/wxzl/gongbao/2000-12/10/content_5004312.htm",
        "http://www.npc.gov.cn/wxzl/wxzl/2000-12/05/content_4502.htm",
    ],
    "全国人民代表大会常务委员会关于批准《国务院关于工人退休、退职的暂行办法》的决议": [
        "http://www.npc.gov.cn/wxzl/gongbao/2000-12/10/content_5004313.htm",
        "http://www.npc.gov.cn/wxzl/wxzl/2000-12/10/content_4272.htm",
    ],
    "全国人民代表大会常务委员会关于批准《国务院关于职工探亲待遇的规定》的决议": [
        "http://www.npc.gov.cn/wxzl/gongbao/2000-12/10/content_5004314.htm",
        "http://www.npc.gov.cn/wxzl/wxzl/2000-12/10/content_4273.htm",
    ],
    "全国人民代表大会常务委员会关于中国人民解放军现役士兵衔级制度的决定": [
        "http://www.gov.cn/xinwen/2022-03/02/content_5676450.htm",
        "https://www.gov.cn/xinwen/2022-03/02/content_5676450.htm",
        "http://www.gov.cn/xinwen/2022-02/28/content_5676088.htm",
    ],
}


def main():
    setup()
    logging.getLogger("cn-leftover").handlers = logging.getLogger("cn-fill").handlers
    logging.getLogger("cn-leftover").setLevel(logging.INFO)
    catalog = parse_catalog(download_catalog_pdf())
    done = existing_ids(CC)
    miss_norms = {}
    for cat in catalog:
        ident = slug_id(CC, "law-" + title_key(cat["title"]))
        if ident not in done:
            miss_norms[cat["norm"]] = cat
    log.info("leftover start missing=%s have=%s", len(miss_norms), len(done))
    write_lock = threading.Lock()
    ok = fail = 0
    jobs = []
    for title, urls in SEEDS.items():
        from collect_cn import norm_title
        nt = norm_title(title)
        cat = miss_norms.get(nt)
        if not cat:
            continue
        for u in urls:
            jobs.append((cat, u))
    log.info("jobs=%s", len(jobs))

    def _one(job):
        cat, url = job
        title, text, date, st, extra = fetch_one_url(url)
        extra = extra or {"method": "archive-of-official"}
        return cat, url, title, text, date, st, extra

    # sequential-ish batches; skip CC is already attempted inside fetch_one_url
    # but CC SSL is slow. Monkeypatch search_common_crawl to no-op for this run.
    import archive_fallbacks as af
    import fill_cn as fc
    af.search_common_crawl = lambda *a, **k: []
    fc.search_common_crawl = lambda *a, **k: []

    seen = set()
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = []
        for job in jobs:
            url = job[1]
            if url in seen:
                continue
            seen.add(url)
            futs.append(ex.submit(_one, job))
        n = 0
        for fut in as_completed(futs):
            n += 1
            try:
                cat, url, title, text, date, st, extra = fut.result()
            except Exception as exc:
                fail += 1
                log.info("err %s", exc)
                continue
            if cat["norm"] not in miss_norms:
                continue
            if not text:
                fail += 1
                log.info("empty %s %s", cat["title"][:20], url[-50:])
                continue
            if ingest(title or cat["title"], text, date, extra, url, miss_norms, done, write_lock):
                ok += 1
            else:
                fail += 1
                log.info("no-match %s tiao? title=%r url=%s chars=%s", cat["title"][:18], (title or "")[:40], url[-60:], len(text or ""))
            if n % 10 == 0:
                log.info("progress %s/%s ok=%s remaining=%s", n, len(futs), ok, len(miss_norms))
    dump_missing(miss_norms)
    n_json = len(list((ROOT / CC / "instruments").glob("*.json")))
    log.info("leftover done ok=%s fail=%s instruments=%s remaining=%s", ok, fail, n_json, len(miss_norms))


if __name__ == "__main__":
    main()
