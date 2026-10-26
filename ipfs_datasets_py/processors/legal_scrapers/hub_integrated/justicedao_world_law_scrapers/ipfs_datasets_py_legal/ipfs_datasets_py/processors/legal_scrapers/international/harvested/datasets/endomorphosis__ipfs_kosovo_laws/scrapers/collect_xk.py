#!/usr/bin/env python3
"""Kosovo: Gazeta Zyrtare (gzk.rks-gov.net) official act PDFs via ASP.NET download."""
from __future__ import annotations
import io, logging, re, sys, time
from pathlib import Path
from bs4 import BeautifulSoup
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import env_int, save_instrument, setup_log, slug_id, live_get

CC, COUNTRY, LANG = "xk", "Kosovo", "sq"
SOURCE_TYPE = "gzk_kosovo"
LICENSE = (
    "Gazeta Zyrtare e Republikës së Kosovës (gzk.rks-gov.net). "
    "Official gazette text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://gzk.rks-gov.net/)"
ART = re.compile(r"(?im)^\s*((?:Neni|NENI|Član|Члан|Article)\s+\d+[a-zA-Z]?\.?)\b")
# Prefer substantive instruments; still allow regulations/decisions with text.
PREF = re.compile(r"(?i)\b(Ligj[ií]?|Kushtetut|Kod[ií]?|Rregullores?|Rregullore|Statut|Udhëzim|Udhezim)\b")
SKIP_TITLE = re.compile(r"(?i)NJOFTIM\s+P[ËE]R\s+TRASHEGIM")
log = logging.getLogger("xk")


def pdf_bytes_to_text(raw: bytes) -> str:
    """Prefer pdfplumber (IntegratedPDFProcessor path), then pdftotext."""
    if not raw or raw[:4] != b"%PDF":
        return ""
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            parts = []
            for page in pdf.pages[:150]:
                try:
                    parts.append(page.extract_text() or "")
                except Exception:
                    continue
            text = "\n".join(parts)
            text = re.sub(r"[ \t]+", " ", text)
            text = re.sub(r"\n{3,}", "\n\n", text).strip()
            if len(text) >= 80:
                return text
    except Exception as exc:
        log.info("pdfplumber: %s", exc)
    try:
        import tempfile, subprocess
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
            tmp.write(raw)
            tmp.flush()
            proc = subprocess.run(
                ["pdftotext", "-layout", "-enc", "UTF-8", tmp.name, "-"],
                check=False, capture_output=True, timeout=180,
            )
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout.decode("utf-8", "replace").strip()
    except Exception as exc:
        log.info("pdftotext: %s", exc)
    return ""


def discover_act_ids(limit: int = 400) -> list[tuple[int, str]]:
    log.info("discover start limit=%s", limit)
    """Return (act_id, title_hint) preferring Ligji/Kodi over inheritance notices."""
    ranked: list[tuple[int, int, str]] = []  # score, id, title
    seen = set()
    pages = env_int("SEARCH_PAGES", 12)
    for index in (1, 2):
        for page in range(1, pages + 1):
            url = f"https://gzk.rks-gov.net/SearchIn.aspx?Index={index}&so={page}"
            try:
                r = live_get(url, ua=UA)
            except Exception as exc:
                log.info("search fail %s: %s", url, exc)
                continue
            soup = BeautifulSoup(r.text or "", "html.parser")
            found = 0
            for a in soup.find_all("a", href=True):
                m = re.search(r"ActDetail\.aspx\?ActID=(\d+)", a.get("href") or "")
                if not m:
                    continue
                aid = int(m.group(1))
                title = a.get_text(" ", strip=True)[:240]
                found += 1
                if aid in seen:
                    continue
                seen.add(aid)
                if SKIP_TITLE.search(title or ""):
                    score = 0
                elif PREF.search(title or ""):
                    score = 3
                elif re.search(r"(?i)\b(Vendim|Aktvendim|Urdh[eë]r|Deklarat)", title or ""):
                    score = 2
                else:
                    score = 1
                ranked.append((score, aid, title))
            if not found:
                break
            if len(seen) >= limit * 2:
                break
        if len(seen) >= limit * 2:
            break
    # Seed historically useful / constitution-era IDs and walk bands near high IDs
    for seed in (18336, 2767, 124146, 100000, 95000, 90000, 85000, 80000, 75000,
                 70000, 65000, 60000, 55000, 50000, 45000, 40000, 35000, 30000,
                 25000, 20000, 15000, 12000, 10000, 8000, 5000, 3000, 2000, 1000):
        if seed not in seen:
            seen.add(seed)
            ranked.append((2, seed, ""))
    # Dense bands near known text-PDF acts (constitution-era / recent regs)
    for lo, hi in ((18200, 18450), (9900, 10100), (2700, 2900), (123800, 124160)):
        for seed in range(lo, hi + 1):
            if seed not in seen:
                seen.add(seed)
                ranked.append((2, seed, ""))
    ranked.sort(key=lambda x: (-x[0], -x[1]))
    # Prefer Ligji/Kodi/Rregullore (score>=2); include score-1 only to fill
    pref = [(aid, title) for score, aid, title in ranked if score >= 2]
    rest = [(aid, title) for score, aid, title in ranked if score == 1]
    out = (pref + rest)[:limit]
    log.info("preferential pref=%s rest=%s", len(pref), len(rest))
    log.info("catalog act ids %s (preferential)", len(out))
    return out


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
    if SKIP_TITLE.search(title or ""):
        # Skip inheritance notices unless ALLOW_NOTICES=1
        if env_int("ALLOW_NOTICES", 0) == 0:
            return b"", title, date
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
    max_new = env_int("MAX_NEW", 80)
    max_seconds = env_int("MAX_SECONDS", 2800)
    t_start = time.time()
    done = existing_ids(CC)
    ok = skip = fail = 0
    for act_id, _hint in discover_act_ids(env_int("ACT_LIMIT", 450)):
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
            log_failure(CC, {"identifier": ident, "reason": "no_pdf_or_skipped_notice"})
            continue
        text = pdf_bytes_to_text(raw)
        if len(text) < 120:
            fail += 1
            log_failure(CC, {"identifier": ident, "reason": "pdf_short_or_scan"})
            continue
        url = f"https://gzk.rks-gov.net/ActDetail.aspx?ActID={act_id}"
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=title or f"Act {act_id}", text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_xk.py",
            date=date or None, article_re=ART,
            extra_meta={"fetch_method": "aspnet_pdf_postback+pdfplumber", "act_id": act_id},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s chars=%s title=%s", ident, len(text), (title or "")[:60])
        else:
            fail += 1
        time.sleep(0.25)
    write_summary(
        CC, country=COUNTRY, source="Gazeta Zyrtare e Republikës së Kosovës",
        source_urls=["https://gzk.rks-gov.net/"],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (SearchIn preferential + ActDetail PDF)",
        notes="Official GZK act PDFs; inheritance notices skipped; pdfplumber+pdftotext. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
