#!/usr/bin/env python3
"""Greece: official National Printing House search.et.gr Azure API + FEK Α' PDFs."""
from __future__ import annotations
import json, logging, os, re, subprocess, sys, tempfile, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *

CC, COUNTRY, SOURCE_TYPE = "gr", "Greece", "et_gr"
LICENSE = "National Printing Office (Εθνικό Τυπογραφείο) search.et.gr / et.gr official gazette FEK."
UA = DEFAULT_UA + " source=https://search.et.gr/"
API = "https://searchetv99.azurewebsites.net/api"
BLOB = "https://ia37rg02wpsa01.blob.core.windows.net/fek"
CORS = {"Origin": "https://search.et.gr", "Referer": "https://search.et.gr/"}
log = logging.getLogger("gr")


def setup():
    ensure_dirs(CC)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
                                  logging.StreamHandler(sys.stdout)])


def api_post(path: str, body: dict) -> list:
    last = None
    for attempt in range(1, 5):
        try:
            time.sleep(0.35)
            r = get_session(UA).post(
                f"{API}/{path.lstrip('/')}", json=body, timeout=(20, 60),
                headers={**CORS, "Content-Type": "application/json", "User-Agent": UA},
            )
            if r.status_code in (429, 500, 502, 503, 504) and attempt < 4:
                time.sleep(min(20, 2 ** attempt)); last = r; continue
            if r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code} {r.text[:160]}")
            wrap = r.json()
            if wrap.get("status") != "ok":
                raise RuntimeError(f"api status {wrap.get('status')} {wrap.get('message')}")
            data = wrap.get("data") or "[]"
            if isinstance(data, str):
                return json.loads(data) if data and data != "[]" else []
            return data if isinstance(data, list) else []
        except Exception as exc:
            last = exc
            time.sleep(min(12, 1.5 * attempt))
    raise RuntimeError(f"api fail {path}: {last}")


def discover() -> list[dict]:
    catp = ROOT / CC / "raw" / "catalog_fek.jsonl"
    items, seen = [], set()
    if catp.exists() and catp.stat().st_size > 200:
        for line in catp.open(encoding="utf-8"):
            try:
                row = json.loads(line)
            except Exception:
                continue
            nid = row.get("norm_id")
            if nid and nid not in seen:
                seen.add(nid); items.append(row)
        if items:
            log.info("resume fek catalog %s", len(items))
            return items
    # ΦΕΚ Α' (laws / PDs) 2000–2026 — born-digital PDFs on official blob
    for year in range(2000, 2027):
        hits = api_post("simplesearch", {
            "selectYear": [str(year)],
            "selectIssue": ["1"],
            "documentNumber": "",
            "searchText": "",
            "datePublished": "",
            "dateReleased": "",
        })
        n_new = 0
        for h in hits or []:
            year_s = str(year)
            num = str(h.get("search_DocumentNumber") or "").strip()
            ig = str(h.get("search_IssueGroupID") or "1").strip()
            if not num:
                continue
            nid = f"FEK-A-{num}-{year_s}"
            if nid in seen:
                continue
            seen.add(nid)
            rec = {
                "norm_id": nid,
                "year": year,
                "issue_group": int(ig) if ig.isdigit() else 1,
                "doc_number": int(num) if num.isdigit() else num,
                "label": h.get("search_PrimaryLabel") or nid,
                "search_id": h.get("search_ID"),
                "pages": h.get("search_Pages"),
                "issue_date": h.get("search_IssueDate"),
            }
            items.append(rec)
            with (ROOT / CC / "raw" / "catalog_fek.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n_new += 1
        log.info("year %s hits=%s new=%s catalog=%s", year, len(hits or []), n_new, len(items))
    log.info("discovered %s", len(items))
    return items


def pdf_text(pdf_bytes: bytes) -> str:
    fd, tmp = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    try:
        Path(tmp).write_bytes(pdf_bytes[:12_000_000])
        out = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", tmp, "-"],
                             capture_output=True, timeout=45)
        return (out.stdout or b"").decode("utf-8", "replace")
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def fetch_one(row: dict, done: set[str]) -> str:
    nid = row["norm_id"]
    rid = slug_id(CC, nid)
    if rid in done:
        return "skip"
    year = int(row["year"])
    ig = int(row.get("issue_group") or 1)
    num = int(row["doc_number"])
    blob = f"{BLOB}/{ig:02d}/{year}/{year}{ig:02d}{num:05d}.pdf"
    time.sleep(0.25)
    r = get_session(UA).get(blob, timeout=(20, 90), headers={**CORS, "User-Agent": UA})
    if r.status_code != 200 or not r.content or r.content[:4] != b"%PDF":
        log_failure(CC, {"identifier": nid, "source_url": blob, "status": "failed",
                         "reason": f"pdf_http_{r.status_code}_len_{len(r.content or b'')}"})
        return "fail"
    text = pdf_text(r.content)
    if not text or len(text) < 80:
        log_failure(CC, {"identifier": nid, "source_url": blob, "status": "failed", "reason": "empty_pdf_text"})
        return "fail"
    title = row.get("label") or nid
    date = None
    idate = row.get("issue_date") or ""
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", idate)
    if m:
        date = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    rec = base_record(
        cc=CC, country=COUNTRY, language="el", ident=nid, title=title, text=text,
        source_url=blob, source_type=SOURCE_TYPE, license_text=LICENSE, collector="gr-et-searchetv99",
        eli=None, date=date, official_identifier=title, document_type="gazette_act",
        law_status="unknown", is_current=None,
        extra_meta={"discovery": {"method": "searchetv99_simplesearch", "search_id": row.get("search_id"),
                                  "pages": row.get("pages")}},
    )
    write_instrument(CC, rec)
    done.add(rid)
    return "ok"


def main():
    setup(); t0 = utcnow()
    try:
        items = discover()
    except Exception as exc:
        log.exception("discover failed")
        write_summary(CC, country=COUNTRY, source="Εθνικό Τυπογραφείο search.et.gr Azure API",
                      source_urls=["https://search.et.gr/", "https://www.et.gr/",
                                   "https://searchetv99.azurewebsites.net/api"],
                      license_text=LICENSE, discovered=0, fetched=0, skipped=0, failed=1,
                      coverage="catalog-backed incomplete",
                      notes=f"simplesearch discovery failed: {exc}", last_run=utcnow())
        return
    done = existing_ids(CC)
    ok = skip = fail = 0
    log.info("fetching %s FEK A (resume done=%s)", len(items), len(done))
    for n, it in enumerate(items, 1):
        try:
            st = fetch_one(it, done)
        except Exception as exc:
            st = "fail"
            log_failure(CC, {"identifier": it.get("norm_id"), "status": "failed", "reason": repr(exc)})
        ok += st == "ok"; skip += st == "skip"; fail += st == "fail"
        if n == 1 or n % 20 == 0:
            log.info("progress %s/%s ok=%s fail=%s skip=%s", n, len(items), ok, fail, skip)
        if n % 40 == 0:
            write_summary(CC, country=COUNTRY, source="Εθνικό Τυπογραφείο FEK Α' (search.et.gr / Azure blob)",
                          source_urls=["https://search.et.gr/", "https://www.et.gr/",
                                       "https://searchetv99.azurewebsites.net/api",
                                       "https://ia37rg02wpsa01.blob.core.windows.net/fek/"],
                          license_text=LICENSE, discovered=len(items), fetched=ok, skipped=skip, failed=fail,
                          coverage="catalog-backed incomplete",
                          notes="Official searchetv99 simplesearch + FEK Α' PDFs from National Printing House Azure blob. pdftotext.",
                          last_run=utcnow())
    write_summary(CC, country=COUNTRY, source="Εθνικό Τυπογραφείο FEK Α' (search.et.gr / Azure blob)",
                  source_urls=["https://search.et.gr/", "https://www.et.gr/",
                               "https://searchetv99.azurewebsites.net/api",
                               "https://ia37rg02wpsa01.blob.core.windows.net/fek/"],
                  license_text=LICENSE, discovered=len(items), fetched=ok, skipped=skip, failed=fail,
                  coverage="catalog-backed incomplete",
                  notes="Official searchetv99 simplesearch (ΦΕΚ Α' 2000–2026) + PDFs from ia37rg02wpsa01.blob.core.windows.net/fek (same backend as search.et.gr). Text via pdftotext. DownloadFeksApi TLS mismatch avoided.",
                  last_run=utcnow(), extra=f"started {t0}")
    log.info("done disc=%s ok=%s fail=%s", len(items), ok, fail)


if __name__ == "__main__":
    main()
