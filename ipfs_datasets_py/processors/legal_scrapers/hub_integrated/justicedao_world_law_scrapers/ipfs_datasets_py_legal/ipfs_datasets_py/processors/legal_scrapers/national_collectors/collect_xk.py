#!/usr/bin/env python3
"""Kosovo: Gazeta Zyrtare (gzk.rks-gov.net) official act PDFs via ASP.NET download."""
from __future__ import annotations
import logging, re, sys, time
from pathlib import Path
from bs4 import BeautifulSoup
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import env_int, pdf_to_text, save_instrument, setup_log, slug_id, live_get

CC, COUNTRY, LANG = "xk", "Kosovo", "sq"
SOURCE_TYPE = "gzk_kosovo"
LICENSE = (
    "Gazeta Zyrtare e Republikës së Kosovës (gzk.rks-gov.net). "
    "Official gazette text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://gzk.rks-gov.net/)"
ART = re.compile(r"(?im)^\s*((?:Neni|Član|Article)\s+\d+[a-zA-Z]?\.?)\b")
log = logging.getLogger("xk")


def discover_act_ids(limit: int = 200) -> list[int]:
    ids, seen = [], set()
    for index in (1, 2):
        for page in range(1, 8):
            url = f"https://gzk.rks-gov.net/SearchIn.aspx?Index={index}&so=1"
            if page > 1:
                url = f"https://gzk.rks-gov.net/SearchIn.aspx?Index={index}&so={page}"
            try:
                r = live_get(url, ua=UA)
            except Exception as exc:
                log.info("search fail %s: %s", url, exc)
                continue
            found = [int(x) for x in re.findall(r"ActDetail\.aspx\?ActID=(\d+)", r.text or "")]
            for aid in found:
                if aid not in seen:
                    seen.add(aid)
                    ids.append(aid)
            if not found:
                break
            if len(ids) >= limit:
                break
        if len(ids) >= limit:
            break
    # Walk recent numeric IDs downward from newest search hit
    if ids:
        top = max(ids)
        for aid in range(top, max(1, top - 250), -1):
            if aid not in seen:
                seen.add(aid)
                ids.append(aid)
            if len(ids) >= limit:
                break
    for seed in (18336, 2767, 124146, 100000, 90000, 80000, 70000, 60000, 50000, 40000, 30000, 20000, 10000):
        if seed not in seen:
            ids.append(seed)
            seen.add(seed)
    log.info("catalog act ids %s", len(ids))
    return ids[:limit]


def download_act_pdf(act_id: int) -> tuple[bytes, str, str]:
    import requests
    from requests.packages.urllib3.exceptions import InsecureRequestWarning
    requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
    sess = requests.Session()
    sess.headers.update({"User-Agent": UA, "Accept": "application/pdf,text/html,*/*"})
    url = f"https://gzk.rks-gov.net/ActDetail.aspx?ActID={act_id}"
    r = sess.get(url, timeout=(20, 90))
    if r.status_code != 200 or not r.text:
        return b"", "", ""
    if "Nuk u gjet" in r.text or "not found" in r.text.lower():
        return b"", "", ""
    soup = BeautifulSoup(r.text, "html.parser")
    title_el = soup.find("title")
    title = (title_el.get_text(strip=True) if title_el else "")[:240]
    date = ""
    m = re.search(r"Data e publikimit:\s*(\d{2}\.\d{2}\.\d{4})", soup.get_text(" ", strip=True))
    if m:
        d, mo, y = m.group(1).split(".")
        date = f"{y}-{mo}-{d}"
    vs = soup.find("input", {"name": "__VIEWSTATE"})
    vsg = soup.find("input", {"name": "__VIEWSTATEGENERATOR"})
    ev = soup.find("input", {"name": "__EVENTVALIDATION"})
    if not vs:
        return b"", title, date
    btn_name = None
    for inp in soup.find_all("input"):
        name = inp.get("name") or ""
        iid = inp.get("id") or ""
        if "imgDownload" in iid or "imgDownload" in name:
            if "Related" in iid or "Related" in name:
                continue
            btn_name = name
            break
    data = {
        "__EVENTTARGET": "",
        "__EVENTARGUMENT": "",
        "__VIEWSTATE": vs.get("value") or "",
        "__VIEWSTATEGENERATOR": vsg.get("value") if vsg else "",
        "__EVENTVALIDATION": ev.get("value") if ev else "",
    }
    if btn_name:
        data[f"{btn_name}.x"] = "8"
        data[f"{btn_name}.y"] = "8"
    else:
        data["__EVENTTARGET"] = "ctl00$MainContent$rAktet$ctl00$imgDownload"
    rr = sess.post(url, data=data, timeout=(20, 120))
    if rr.content and rr.content[:4] == b"%PDF":
        return rr.content, title, date
    return b"", title, date


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 45)
    max_seconds = env_int("MAX_SECONDS", 2400)
    t_start = time.time()
    done = existing_ids(CC)
    ok = skip = fail = 0
    for act_id in discover_act_ids(env_int("ACT_LIMIT", 220)):
        if max_new and ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        ident = str(act_id)
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        try:
            raw, title, date = download_act_pdf(act_id)
        except Exception as exc:
            fail += 1
            log_failure(CC, {"identifier": ident, "reason": f"download:{exc}"})
            continue
        if not raw:
            fail += 1
            log_failure(CC, {"identifier": ident, "reason": "no_pdf"})
            continue
        text = pdf_to_text(raw)
        if len(text) < 120:
            fail += 1
            log_failure(CC, {"identifier": ident, "reason": "pdf_short"})
            continue
        url = f"https://gzk.rks-gov.net/ActDetail.aspx?ActID={act_id}"
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=title or f"Act {act_id}", text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_xk.py",
            date=date or None, article_re=ART,
            extra_meta={"fetch_method": "aspnet_pdf_postback", "act_id": act_id},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s chars=%s title=%s", ident, len(text), (title or "")[:60])
        else:
            fail += 1
        time.sleep(0.3)
    write_summary(
        CC, country=COUNTRY, source="Gazeta Zyrtare e Republikës së Kosovës",
        source_urls=["https://gzk.rks-gov.net/"],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (SearchIn + ActDetail PDF)",
        notes="Official GZK act PDFs via portal download. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
