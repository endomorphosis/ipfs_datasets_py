#!/usr/bin/env python3
"""Portugal: Diário da República 1.ª série act PDFs (files.diariodarepublica.pt).

The live DRE (diariodarepublica.pt / dre.pt / data.dre.pt) is an OutSystems SPA
whose detail pages and ELI endpoints render client-side and are not scriptable.
The official per-act PDFs of the 1.ª série remain directly fetchable at
https://files.diariodarepublica.pt/1s/{yyyy}/{mm}/{code}/{file}.pdf
(enumerated via Wayback CDX of that host; fetched live from the official host).

Each PDF holds one act (Lei, Decreto-Lei, Portaria, ...) with born-digital text
for recent decades. Ordering is newest-first so the corpus gets current law.

Idempotent: skips instrument ids already present.
"""
from __future__ import annotations
import concurrent.futures
import io
import logging
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *  # noqa

CC, COUNTRY, SOURCE_TYPE = "pt", "Portugal", "dre"
LICENSE = ("Diário da República 1.ª série (files.diariodarepublica.pt). Official gazette "
           "of the Portuguese Republic (INCM). Not legal advice.")
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
log = logging.getLogger("pt-1s")

MAX_NEW = int(os.environ.get("MAX_NEW", "800"))
MAX_SECONDS = int(os.environ.get("MAX_SECONDS", "3600"))
FETCH_BUDGET = int(os.environ.get("PT_FETCH_BUDGET", "1400"))
WORKERS = int(os.environ.get("PT_WORKERS", "4"))

MONTHS = {"janeiro": "01", "fevereiro": "02", "março": "03", "marco": "03",
          "abril": "04", "maio": "05", "junho": "06", "julho": "07",
          "agosto": "08", "setembro": "09", "outubro": "10",
          "novembro": "11", "dezembro": "12"}

ACT_PATTERNS = [
    (r"Lei Orgânica n\.º\s*([0-9]+[0-9A-Za-z/\-.]*)", "lei orgânica", "statute"),
    (r"Decreto-Lei n\.º\s*([0-9]+[0-9A-Za-z/\-.]*)", "decreto-lei", "statute"),
    (r"Decreto Legislativo Regional n\.º\s*([0-9]+[0-9A-Za-z/\-.]*)",
     "decreto legislativo regional", "statute"),
    (r"Decreto Regulamentar Regional n\.º\s*([0-9]+[0-9A-Za-z/\-.]*)",
     "decreto regulamentar regional", "decree"),
    (r"Decreto Regulamentar n\.º\s*([0-9]+[0-9A-Za-z/\-.]*)",
     "decreto regulamentar", "decree"),
    (r"Decreto do Presidente da República n\.º\s*([0-9]+[0-9A-Za-z/\-.]*)",
     "decreto", "decree"),
    (r"Decreto n\.º\s*([0-9]+[0-9A-Za-z/\-.]*)", "decreto", "decree"),
    (r"Resolução do Conselho de Ministros n\.º\s*([0-9]+[0-9A-Za-z/\-.]*)",
     "resolução do conselho de ministros", "resolution"),
    (r"Resolução da Assembleia da República n\.º\s*([0-9]+[0-9A-Za-z/\-.]*)",
     "resolução da assembleia da república", "resolution"),
    (r"Portaria n\.º\s*([0-9]+[0-9A-Za-z/\-.]*)", "portaria", "regulation"),
    (r"Lei n\.º\s*([0-9]+[0-9A-Za-z/\-.]*)", "lei", "statute"),
]


def discover_urls() -> list[str]:
    cache = ROOT / CC / "raw" / "pt_1s_pdfs.txt"
    urls = [u.strip() for u in cache.read_text(encoding="utf-8").split()
            if u.strip().endswith(".pdf")]
    def year(u: str) -> int:
        m = re.search(r"/1s/(\d{4})/", u)
        return int(m.group(1)) if m else 0
    urls.sort(key=lambda u: (year(u), u), reverse=True)
    return urls


def pdf_text(data: bytes) -> str:
    import pymupdf
    doc = pymupdf.open(stream=data, filetype="pdf")
    parts = []
    for page in doc:
        parts.append(page.get_text())
        if sum(len(p) for p in parts) > 400000:
            break
    return "\n".join(parts)


def parse_act(text: str, url: str) -> dict | None:
    if len(text) < 800:
        return None
    head = text[:3000]
    # DR issue header: "Diário da República, 1.ª série — N.º 45 — 3 de março de 2017"
    date = dr_no = None
    m = re.search(r"N\.º\s*(\d+)[^\n]{0,40}?(\d{1,2})\s+de\s+([a-zç]+)\s+de\s+(\d{4})",
                  head, re.I)
    if m:
        dr_no = m.group(1)
        mon = MONTHS.get(m.group(3).lower(), "01")
        date = f"{m.group(4)}-{mon}-{int(m.group(2)):02d}"
    # emitter: first all-caps line(s) after the header
    emitter = None
    lines = [l.strip() for l in head.splitlines() if l.strip()]
    for i, l in enumerate(lines[:12]):
        if re.match(r"Diário da República", l):
            for l2 in lines[i + 1:i + 6]:
                if re.match(r"^[A-ZÀ-Ú0-9 .,\-()&/]{6,}$", l2) and not re.match(r"^\d+$", l2):
                    emitter = l2.strip()
                    break
            break
    act_type = act_num = doc_type = None
    act_idx = -1
    for pat, tname, dtype in ACT_PATTERNS:
        m = re.search(pat, text[:6000], re.I)
        if m:
            act_type, act_num, doc_type = tname, m.group(1).strip(), dtype
            act_idx = m.start()
            break
    if not act_type:
        return None
    title = f"{act_type.capitalize()} n.º {act_num}"
    # summary: text right after the act heading line
    summary = ""
    seg = text[act_idx:act_idx + 2500]
    seg_lines = [l.strip() for l in seg.splitlines() if l.strip()]
    if len(seg_lines) > 2:
        summary = " ".join(seg_lines[2:6])[:600]
    official = f"PT {title}" + (f" (DR 1.ª série n.º {dr_no})" if dr_no else "")
    return {"title": title, "act_type": act_type, "act_num": act_num,
            "doc_type": doc_type, "date": date, "dr_no": dr_no,
            "emitter": emitter, "summary": summary, "text": text.strip(),
            "url": url}


def fetch_pdf(session, url: str):
    for attempt in range(2):
        try:
            r = session.get(url, timeout=90)
            if r.status_code != 200:
                return url, None, f"http_{r.status_code}"
            ctype = r.headers.get("content-type", "")
            if len(r.content) < 20000 or "pdf" not in ctype:
                return url, None, "not_pdf"
            try:
                text = pdf_text(r.content)
            except Exception as exc:
                return url, None, f"pdf_error:{str(exc)[:60]}"
            if len(text) < 800:
                return url, None, "image_pdf"
            parsed = parse_act(text, url)
            if not parsed:
                return url, None, "unparseable"
            return url, parsed, None
        except Exception as exc:
            err = str(exc)[:80]
            time.sleep(2 + attempt * 2)
    return url, None, err


def main():
    ensure_dirs(CC)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(ROOT / CC / "logs" / "pt_1s.log", encoding="utf-8"),
                                  logging.StreamHandler(sys.stdout)])
    t0 = time.time()
    notes = []
    session = get_session(ua=UA, pool=WORKERS + 2)

    urls = discover_urls()
    notes.append(f"discovery: {len(urls)} DR 1.ª série act PDFs (newest first)")
    done = existing_ids(CC)
    notes.append(f"already existing instruments: {len(done)}")

    fetched = failed = skipped = written = 0
    image_pdfs = 0
    deadline = t0 + MAX_SECONDS
    _warned = {"v": False}

    def keep(parsed: dict, ident: str):
        nonlocal written
        rid = slug_id(CC, ident)
        if rid in done:
            return "skip"
        rec = base_record(
            cc=CC, country=COUNTRY, language="pt", ident=ident, title=parsed["title"],
            text=parsed["text"], source_url=parsed["url"], source_type=SOURCE_TYPE,
            license_text=LICENSE, collector="pt-1s-pdf",
            date=parsed["date"], official_identifier=parsed["title"] + " (Diário da República, 1.ª série)",
            document_type=parsed["doc_type"], law_status="current", is_current=True,
            extra_meta={"act_type": parsed["act_type"], "act_number": parsed["act_num"],
                        "dr_issue": parsed["dr_no"], "emitter": parsed["emitter"],
                        "summary": parsed["summary"]},
        )
        try:
            err = validate_record(rec)
        except Exception as exc:
            err = str(exc)
        if err and ("_templates" in err or "jsonschema" in err or "No module named" in err):
            if not _warned["v"]:
                notes.append("validation skipped: schema file not shipped in this environment")
                _warned["v"] = True
            err = None
        if err:
            log_failure(CC, {"url": parsed["url"], "error": f"validate: {err[:120]}"})
            return "fail"
        write_instrument(CC, rec)
        done.add(rid)
        return "ok"

    idx = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        pending = {}

        def feed():
            nonlocal idx, skipped
            while idx < len(urls) and len(pending) < WORKERS * 2 \
                    and fetched + failed < FETCH_BUDGET and written < MAX_NEW \
                    and time.time() < deadline:
                url = urls[idx]; idx += 1
                ident = "1s-" + Path(url).stem
                if slug_id(CC, ident) in done:
                    skipped += 1
                    continue
                pending[ex.submit(fetch_pdf, session, url)] = (url, ident)

        feed()
        while pending and written < MAX_NEW and time.time() < deadline:
            for fut in concurrent.futures.as_completed(list(pending)):
                url, ident = pending.pop(fut)
                try:
                    _u, parsed, err = fut.result()
                except Exception as exc:
                    parsed, err = None, str(exc)[:80]
                if parsed is None:
                    failed += 1
                    if err == "image_pdf":
                        image_pdfs += 1
                    elif failed <= 30:
                        log_failure(CC, {"url": url, "error": err})
                else:
                    fetched += 1
                    res = keep(parsed, ident)
                    if res == "ok":
                        written += 1
                    elif res == "fail":
                        failed += 1
                    else:
                        skipped += 1
                feed()
                if (fetched + failed) % 100 == 0:
                    log.info("progress ok=%d written=%d failed=%d skipped=%d",
                             fetched, written, failed, skipped)
            feed()

    notes.append(f"fetch: parsed_ok={fetched} written={written} failed={failed} "
                 f"(image_pdf={image_pdfs}) skipped={skipped}")
    notes.append("Image-only PDFs (mostly pre-1990 scans) skipped without OCR: "
                 "no Portuguese tesseract traineddata in this environment.")
    notes.append("Blockers: diariodarepublica.pt/dre.pt/data.dre.pt are an OutSystems SPA; "
                 "used official per-act PDFs on files.diariodarepublica.pt instead.")
    write_summary(
        CC, country=COUNTRY,
        source="Diário da República 1.ª série — official per-act PDFs (files.diariodarepublica.pt)",
        source_urls=["https://files.diariodarepublica.pt/", "https://diariodarepublica.pt/"],
        license_text=LICENSE, discovered=len(urls), fetched=written,
        skipped=skipped, failed=failed, coverage="official-hosted",
        notes="\n".join(notes), last_run=utcnow(),
        extra=f"started {utcnow()} (run t0 epoch {int(t0)}); collector=pt-1s-pdf",
    )
    log.info("done discovered=%d written=%d failed=%d skipped=%d", len(urls), written, failed, skipped)


if __name__ == "__main__":
    main()
