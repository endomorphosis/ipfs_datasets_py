"""DE Rechtsprechung im Internet collector. Text only, 0.5 req/s, resumable.

Promoted from ``justicedao/world_law_scrapers`` ``caselaw/de_rii/collect.py`` at
``e8169767dcb69aff9e09e27f13e7450a031d95dc``. This module does not replace
``collect_gii`` and does not change the Germany statute query route.
Importing this module does not fetch the TOC.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CASELAW = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_CASELAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "caselaw")))
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))

import io, re, sys, json, time, zipfile, shutil, datetime, logging
import requests, lxml.etree as ET, lxml.html as LH

TOC = "https://www.rechtsprechung-im-internet.de/rii-toc.xml"
UA = "justicedao-caselaw-research/0.1 (Benjamin Barber; 0.5 req/s)"
LIC = "Free use and re-use (rechtsprechung-im-internet.de, BMJ/BfJ); attribution: Rechtsprechung im Internet"
DISK = 10.5e9
MEM = 4.2e9
BATCH = 2000
GAP = 2.0


def _paths():
    root = _CASELAW
    out = root / "staging" / "ipfs_germany_caselaw" / "de_bund"
    state = root / "staging" / "ipfs_germany_caselaw" / "state.json"
    log = root / "logs" / "de_rii.log"
    return out, state, log


def get(session, last, url):
    for attempt in range(8):
        wait = GAP - (time.time() - last[0])
        time.sleep(max(0, wait))
        last[0] = time.time()
        try:
            response = session.get(url, timeout=120)
            if response.status_code == 200:
                return response.content
            if response.status_code in (403, 429) or b"captcha" in response.content[:5000].lower():
                logging.info("BLOCK %s %s", response.status_code, url)
                sys.exit(3)
            logging.info("HTTP %s %s", response.status_code, url)
            if response.status_code == 404:
                return None
        except Exception as exc:
            logging.info("ERR %s %s", url, exc)
        time.sleep(min(600, 5 * 2 ** attempt))
    return None


def guards():
    while True:
        free = shutil.disk_usage(str(_CASELAW)).free
        if free < DISK:
            logging.info("DISK GUARD %.2fG stop", free / 1e9)
            sys.exit(2)
        available = int([line for line in open("/proc/meminfo") if line.startswith("MemAvailable")][0].split()[1]) * 1024
        if available >= MEM:
            return
        logging.info("MEM GUARD %.2fG wait", available / 1e9)
        time.sleep(60)


def txt(el):
    if el is None:
        return ""
    raw = ET.tostring(el, encoding="unicode", method="html")
    try:
        return LH.fromstring("<div>" + raw + "</div>").text_content().strip()
    except Exception:
        return ""


def parse(payload, link):
    archive = zipfile.ZipFile(io.BytesIO(payload))
    name = [item for item in archive.namelist() if item.endswith(".xml")][0]
    document = ET.fromstring(archive.read(name), ET.XMLParser(load_dtd=False, no_network=True, resolve_entities=False))

    def field(tag):
        return (document.findtext(tag) or "").strip()

    parts = []
    for tag, heading in (
        ("leitsatz", "Leitsatz"),
        ("sonstosatz", "Orientierungssatz"),
        ("tenor", "Tenor"),
        ("tatbestand", "Tatbestand"),
        ("entscheidungsgruende", "Entscheidungsgründe"),
        ("gruende", "Gründe"),
        ("abwmeinung", "Abweichende Meinung"),
        ("sonstlt", "Sonstiger Langtext"),
    ):
        value = txt(document.find(tag))
        if value:
            parts.append(heading + "\n" + value)
    decided = field("entsch-datum")
    if len(decided) == 8:
        decided = f"{decided[:4]}-{decided[4:6]}-{decided[6:8]}"
    court = (field("gertyp") + " " + field("spruchkoerper")).strip()
    return dict(
        ecli=field("ecli") or None,
        jurisdiction="de",
        court=court,
        chamber=field("spruchkoerper") or None,
        date=decided,
        number=field("aktenzeichen"),
        title=txt(document.find("titelzeile")) or (field("doktyp") + " " + field("aktenzeichen")).strip(),
        text="\n\n".join(parts),
        source_url=link,
        archive_name=None,
        is_archive=False,
        licence=LIC,
        retrieved_at=datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        court_id=None,
        rii_doknr=field("doknr"),
        doctype=field("doktyp"),
        norm=field("norm"),
        config="de_bund",
    )


def main():
    out, state_path, log_path = _paths()
    out.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    _CASELAW.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=str(log_path), level=logging.INFO, format="%(asctime)s %(message)s")
    session = requests.Session()
    session.headers["User-Agent"] = UA
    last = [0.0]
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {"part": 0, "rows": 0, "done": 0}

    def save(current):
        temporary = state_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(current), encoding="utf-8")
        os.replace(temporary, state_path)

    def flush(rows, current):
        if not rows:
            return
        import pyarrow as pa
        import pyarrow.parquet as pq
        destination = out / f"de_bund.part{current['part']:05d}.parquet"
        temporary = destination.with_suffix(".parquet.tmp")
        pq.write_table(pa.Table.from_pylist(rows), temporary, compression="zstd")
        os.replace(temporary, destination)
        current["part"] += 1
        current["rows"] += len(rows)
        current["done"] = current["pending"]
        save(current)
        logging.info("wrote %s rows=%d total=%d", destination, len(rows), current["rows"])

    toc = get(session, last, TOC)
    links = [re.sub("^http:", "https:", item.decode()) for item in re.findall(rb"<link>([^<]+)</link>", toc)]
    logging.info("toc %d items, resume at %d", len(links), state["done"])
    rows = []
    for index in range(state["done"], len(links)):
        guards()
        payload = get(session, last, links[index])
        if payload:
            try:
                rows.append(parse(payload, links[index]))
            except Exception as exc:
                logging.info("PARSE %s %s", links[index], exc)
        state["pending"] = index + 1
        if len(rows) >= BATCH:
            flush(rows, state)
            rows = []
    state["pending"] = len(links)
    flush(rows, state)
    state["done"] = len(links)
    save(state)
    logging.info("DONE rows=%d", state["rows"])


if __name__ == "__main__":
    main()
