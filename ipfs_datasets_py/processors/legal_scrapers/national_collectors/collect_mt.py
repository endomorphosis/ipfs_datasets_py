#!/usr/bin/env python3
"""Malta: legislation.mt ELI chapters + subsidiary legislation."""
from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *

CC = "mt"
COUNTRY = "Malta"
SOURCE_TYPE = "legislation_mt"
LICENSE = (
    "Maltese legislation on legislation.mt is official; reuse of public sector "
    "information. ELI: https://legislation.mt/eli/ (EUR-Lex ELI register: Malta)."
)
UA = DEFAULT_UA + " source=https://legislation.mt/eli/"
log = logging.getLogger("mt")


def setup():
    ensure_dirs(CC)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
                                  logging.StreamHandler(sys.stdout)])


def fetch_pdf_text(url: str) -> str:
    import tempfile, subprocess
    r = http_get(url, ua=UA, sleep=0.4, headers={"Accept": "application/pdf"})
    if r.status_code != 200 or r.content[:4] != b"%PDF":
        return ""
    with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
        tmp.write(r.content); tmp.flush()
        try:
            out = subprocess.run(["pdftotext", "-layout", "-q", tmp.name, "-"], capture_output=True, timeout=60)
            return out.stdout.decode("utf-8", "replace").strip()
        except Exception:
            return ""


def fetch_eli(coord: str, done: set[str]) -> str:
    ident = coord.replace("/", "-")
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    # prefer English
    page = f"https://legislation.mt/eli/{coord}/eng"
    r = http_get(page, ua=UA, sleep=0.45)
    title = ident
    text = ""
    src = page
    if r.status_code == 200 and r.content:
        raw = r.text
        m = re.search(r"<title>([^<]+)</title>", raw, re.I)
        if m:
            title = re.sub(r"\s+", " ", m.group(1)).strip()
        # JSON-LD
        for jm in re.finditer(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', raw, re.S | re.I):
            try:
                jd = json.loads(jm.group(1))
                if isinstance(jd, dict):
                    title = jd.get("name") or jd.get("headline") or title
            except Exception:
                pass
        text = html_to_text(raw)
        if len(text) < 80:
            pdf = f"https://legislation.mt/eli/{coord}/eng/pdf"
            text = fetch_pdf_text(pdf)
            src = pdf
    if not text or len(text) < 40:
        log_failure(CC, {"identifier": ident, "source_url": page, "status": "failed", "reason": "empty_text"})
        return "fail"
    rec = base_record(
        cc=CC, country=COUNTRY, language="en", ident=ident, title=title, text=text,
        source_url=src, source_type=SOURCE_TYPE, license_text=LICENSE, collector="mt-legislation-eli",
        eli=page, date=None, official_identifier=coord, document_type="statute",
        law_status="current", is_current=True,
        extra_meta={"discovery": {"method": "eli_cap_scan"}},
    )
    rec["languages"] = ["en", "mt"]
    write_instrument(CC, rec)
    return "ok"


def main():
    import json
    globals()["json"] = json
    setup()
    t0 = utcnow()
    done = existing_ids(CC)
    coords = ["const"] + [f"cap/{n}" for n in range(1, 650)]
    # also list page
    r = http_get("https://legislation.mt/eli/cap", ua=UA, sleep=0.3)
    if r.status_code == 200:
        extra = re.findall(r"eli/(cap/\d+|sl/[\d.]+|act/\d+/\d+|ln/\d+/\d+)", r.text)
        for e in extra:
            if e not in coords:
                coords.append(e)
    ok = skip = fail = 0
    discovered = len(coords)
    for c in coords:
        try:
            st = fetch_eli(c, done)
        except Exception as exc:
            st = "fail"
            log_failure(CC, {"identifier": c, "status": "failed", "reason": repr(exc)})
        ok += st == "ok"; skip += st == "skip"; fail += st == "fail"
        if (ok + fail) % 50 == 0:
            log.info("ok=%s fail=%s / %s", ok, fail, discovered)
            write_summary(CC, country=COUNTRY, source="legislation.mt ELI",
                          source_urls=["https://legislation.mt/eli/"],
                          license_text=LICENSE, discovered=discovered, fetched=ok, skipped=skip, failed=fail,
                          coverage="catalog-backed incomplete", notes="cap 1-649 + const", last_run=utcnow())
    write_summary(CC, country=COUNTRY, source="legislation.mt ELI (Chapters of the Laws of Malta)",
                  source_urls=["https://legislation.mt/eli/", "https://eur-lex.europa.eu/eli-register/malta.html"],
                  license_text=LICENSE, discovered=discovered, fetched=ok, skipped=skip, failed=fail,
                  coverage="catalog-backed incomplete",
                  notes="Primary chapters (cap/N) and Constitution via official ELI. Subsidiary legislation harvested when listed. English version preferred.",
                  last_run=utcnow(), extra=f"started {t0}")
    log.info("done ok=%s fail=%s", ok, fail)


if __name__ == "__main__":
    main()
