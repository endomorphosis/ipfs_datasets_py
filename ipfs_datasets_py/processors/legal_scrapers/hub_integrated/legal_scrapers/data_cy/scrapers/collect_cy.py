#!/usr/bin/env python3
"""Cyprus: official GPO gazette (mof.gov.cy). legislation.gov.cy does not resolve. Not cylaw.org."""
from __future__ import annotations
import logging, re, sys
from pathlib import Path
from urllib.parse import urljoin
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *

CC, COUNTRY, SOURCE_TYPE = "cy", "Cyprus", "gpo_gazette"
LICENSE = "Official Gazette of the Republic of Cyprus, Government Printing Office (mof.gov.cy/gpo). cylaw.org is unofficial and is NOT used."
UA = DEFAULT_UA + " source=https://www.mof.gov.cy/mof/gpo/"
log = logging.getLogger("cy")


def setup():
    ensure_dirs(CC)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
                                  logging.StreamHandler(sys.stdout)])


def try_get(url):
    # Official GPO presents an incomplete cert chain from this network; still the official host.
    last = None
    for verify in (True, False):
        try:
            time.sleep(0.35)
            r = get_session(UA).get(url, timeout=(15, 40), verify=verify,
                                    headers={"User-Agent": UA, "Accept": "text/html, application/pdf, */*"})
            return r, verify
        except Exception as exc:
            last = exc
    return last, None


def main():
    import time
    globals()["time"] = time
    setup(); t0 = utcnow()
    notes = []
    items = []
    seeds = [
        "https://www.mof.gov.cy/mof/gpo/gazette.nsf/officialgazette-el/officialgazette-el?OpenDocument",
        "https://www.mof.gov.cy/mof/gpo/gazette.nsf/dmlgaz_NEW_gr/dmlgaz_NEW_gr?OpenDocument",
        "https://www.mof.gov.cy/mof/gpo/gpo.nsf/index_gr/index_gr?OpenDocument",
        "https://www.gov.cy/en/service/episimi-efimerida-tis-dimokratias/",
        "https://www.legislation.gov.cy/",
    ]
    for url in seeds:
        r, verify = try_get(url)
        if not hasattr(r, "status_code"):
            notes.append(f"seed {url} ERROR {r}")
            continue
        notes.append(f"seed {url} -> HTTP {r.status_code} bytes={len(r.content or b'')} verify={verify}")
        (ROOT / CC / "raw" / (re.sub(r"[^a-z0-9]+","_", url)[:90] + ".bin")).write_bytes((r.content or b"")[:25000])
        if r.status_code == 200 and r.content:
            for href in re.findall(r'href="([^"]+)"', r.text):
                href = urljoin(url, href)
                if any(x in href.lower() for x in (".pdf", "gazette", "opendocument", "$file")):
                    items.append(href)
    done = existing_ids(CC); ok = skip = fail = 0
    seen=set(); uniq=[]
    for h in items:
        if h in seen: continue
        seen.add(h); uniq.append(h)
    for href in uniq[:250]:
        ident = re.sub(r"^https?://", "", href)
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1; continue
        r, _ = try_get(href)
        if not hasattr(r, "status_code") or r.status_code != 200 or not r.content:
            fail += 1; continue
        if r.content[:5] == b"%PDF-":
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": href, "status": "failed", "reason": "pdf_not_extracted"})
            continue
        text = html_to_text(r.text if isinstance(r.text, str) else r.content.decode("utf-8","replace"))
        if len(text) < 80:
            fail += 1; continue
        rec = base_record(cc=CC, country=COUNTRY, language="el", ident=ident, title=ident, text=text,
                          source_url=href, source_type=SOURCE_TYPE, license_text=LICENSE,
                          collector="cy-gpo-gazette", eli=None, date=None, official_identifier=ident,
                          document_type="gazette", law_status="unknown", is_current=None)
        write_instrument(CC, rec); ok += 1
    if not ok:
        notes.append(
            "Blocker: www.legislation.gov.cy does not resolve (NXDOMAIN). Official GPO at mof.gov.cy presents "
            "an incomplete TLS certificate chain from this network (unable to get local issuer). "
            "cylaw.org is unofficial and was not used as primary. Maximum legal slice this run: none unless GPO HTML yielded texts."
        )
    write_summary(CC, country=COUNTRY, source="Cyprus Government Printing Office gazette",
                  source_urls=["https://www.mof.gov.cy/mof/gpo/gazette.nsf/officialgazette-el/officialgazette-el?OpenDocument",
                               "https://www.gov.cy/en/service/episimi-efimerida-tis-dimokratias/"],
                  license_text=LICENSE, discovered=len(uniq), fetched=ok, skipped=skip, failed=fail,
                  coverage="catalog-backed incomplete", notes="\n".join(notes), last_run=utcnow(), extra=f"started {t0}")
    log.info("done disc=%s ok=%s fail=%s", len(uniq), ok, fail)


if __name__ == "__main__":
    main()
