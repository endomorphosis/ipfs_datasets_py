#!/usr/bin/env python3
"""Belarus: pravo.by (National Legal Internet Portal) - local normative acts (register 9: R9YY*/D9YY* = decisions of local
Councils of Deputies / executive committees), official publication PDFs.

Discovery: the public "Новые поступления" lists (/ofitsialnoe-opublikovanie/novye-postupleniya/, /natsionalnyy-reestr/novye-postupleniya/)
  only show recent days, so this is a POLLER: run it daily (cron/loop) and it accumulates every new local act. /search/ is
  robots-disallowed and not used. Historical backfill would need archived listings (not queued; see cee_notes 2026-10-30).
Doc: /document/?guid=12551&p0=<id> -> title "Решение <issuer> от DD.MM.YYYY г. № N «...»" + /upload/docs/op/<id>_<ts>.pdf
Place: issuer genitive stem + type (районного->район, сельского->сельсовет, городского->город, областного->область) matched to ru
  labels/aliases of candidate BY rows (data/wd_by_labels.csv from Wikidata; SOATO P1667 recorded when present). Else _unmatched.
Usage: python3 by_pravo.py poll [--loop HOURS] | status
"""
from __future__ import annotations
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths

import argparse, csv, html as H, json, re, subprocess, sys, tempfile, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.rfc9309 import IGNORE_ROBOTS  # noqa: E402
from common.live import STAGE, Done, PoliteSession, Stager, get_logger, utcnow  # noqa: E402

BASE = "https://pravo.by"
LISTS = ["/ofitsialnoe-opublikovanie/novye-postupleniya/", "/natsionalnyy-reestr/novye-postupleniya/"]
STATE = STAGE / "_state" / "by"
CAND = Path((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + "/global_municipalities_candidate.csv"))
LAB = Path(__file__).resolve().parent / "data" / "wd_by_labels.csv"
log = get_logger("by_pravo")
TYPES = [("районн", ("район",)), ("сельск", ("сельсовет",)), ("поселков", ("поселков", "посёлок")), ("городск", ("",)),
         ("областн", ("област",))]


def clean(s):
    return " ".join(H.unescape(re.sub(r"<[^>]+>", " ", s or "")).split())


class Places:
    def __init__(self):
        cand = {r["qid"]: r for r in csv.DictReader(CAND.open(encoding="utf-8")) if r["country_code"] == "BY"}
        self.rows = []
        for r in csv.DictReader(LAB.open(encoding="utf-8")):
            if r["qid"] in cand:
                for lab in r["ru"].split("|"):
                    if lab:
                        self.rows.append((lab.lower(), cand[r["qid"]], r["soato"]))

    def resolve(self, issuer):
        w = issuer.split()
        if not w:
            return dict(place_id=None, qid=None, place_name=issuer, match="no_issuer")
        stem = re.sub(r"(ского|ского|цкого|ого|его)$", "", w[0].lower())
        stem = stem[:-1] if len(stem) > 5 else stem
        kind = next((t for k, t in TYPES if len(w) > 1 and w[1].lower().startswith(k)), None)
        hits = []
        for lab, c, so in self.rows:
            if lab.startswith(stem) and (kind is None or any(k in lab for k in kind)):
                if kind == ("",) and ("район" in lab or "сельсовет" in lab):
                    continue
                hits.append((c, so))
        qids = {c["qid"] for c, _ in hits}
        if len(qids) == 1:
            c, so = hits[0]
            return dict(place_id=c["place_id"], qid=c["qid"], place_name=c["place_name"], match="issuer_ru_label", soato=so or None)
        return dict(place_id=None, qid=None, place_name=issuer, match=f"issuer_{'ambiguous' if qids else 'not_in_candidate'}")


def text_of_pdf(b):
    with tempfile.NamedTemporaryFile(suffix=".pdf") as tf:
        tf.write(b); tf.flush()
        o = subprocess.run(["pdftotext", "-q", "-enc", "UTF-8", tf.name, "-"], capture_output=True, timeout=300)
        return o.stdout.decode("utf-8", "replace").strip()


def poll(sess):
    STATE.mkdir(parents=True, exist_ok=True)
    done, pm = Done(STATE / "done.sqlite"), Places()
    stg = Stager("BY", "bypravo", log, max_docs=100)
    ids = []
    for p in LISTS:
        t = sess.get(BASE + p).text
        for g, i in re.findall(r"guid=(\d+)&(?:amp;)?p0=([A-Za-z0-9]+)", t):
            if re.match(r"[RD]9\d\d", i) and i not in dict(ids):
                ids.append((i, g))
    log.info("listed %d local act ids", len(ids))
    run_ids(sess, ids, done, pm, stg)


def pdftext(sess):
    """2026-11-01 (EU_IGNORE_ROBOTS): re-fetch acts already done metadata-only and add the /upload/ official PDF text.
    Resumable via done key pdf:<id>."""
    done, pm = Done(STATE / "done.sqlite"), Places()
    stg = Stager("BY", "bypravo", log, max_docs=50)
    ids = [(r[0], "12551") for r in done.c.execute("select id from done where why='ok' and id not like 'pdf%'")]
    ids = [x for x in ids if not done.has("pdf2:" + x[0])]
    log.info("pdftext: %d acts to re-fetch with PDF text", len(ids))
    run_ids(sess, ids, done, pm, stg, key_prefix="pdf2:")  # pdf: = 2026-11-01 first try (content_format pdf rejected by schema)


def run_ids(sess, ids, done, pm, stg, key_prefix=""):
    for did, guid in ids:
        if done.has(key_prefix + did):
            continue
        url = f"{BASE}/document/?guid={guid}&p0={did}"
        try:
            t = sess.get(url).text
            plain = clean(re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", t))
            title = clean(re.search(r"(?s)<title>(.*?)</title>", t).group(1)).split(" – Pravo.by")[0]
            m = re.search(r"(Решение|Распоряжение|Постановление)\s+(.*?)\s+от\s+(\d{1,2})[. ]([а-я]+|\d{2})[. ]\s*(\d{4})\s*г?\.?\s*№\s*([\w\-/]+)", plain)
            nm = re.search(r"Название акта (.*?) Вид акта", plain)
            if nm:
                title = f"{m.group(0) if m else ''} «{nm.group(1)}»".strip()
            reg = re.search(r"Регистрационный номер Национального реестра ([\d/\-]+)", plain)
            # official text is only in /upload/docs/op/*.pdf, which robots.txt disallows -> metadata-only record
            pdf, text = None, ""
            if IGNORE_ROBOTS:   # 2026-11-01: robots.txt not respected for legal texts (EU_IGNORE_ROBOTS=1)
                pdf = re.search(r"""(/upload/docs/op/[^"'<>\s]+\.pdf)""", t)
                if pdf:
                    try:
                        text = text_of_pdf(sess.get(BASE + pdf.group(1)).content)
                    except Exception as e:  # noqa: BLE001
                        log.warning("pdf FAIL %s: %s", did, str(e)[:200])
            mon = {"января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6, "июля": 7, "августа": 8,
                   "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12}
            pl = pm.resolve(m.group(2) if m else "")
            rec = {"place_id": pl["place_id"], "country_code": "BY", "doc_id": f"by_pravo:{did}", "source_platform": "by_pravo",
                   "source_url": url, "doc_type": "decision", "language": "ru", "title_native": title,
                   "number": m.group(6) if m else None, "adopted_date": f"{m.group(5)}-{int(mon.get(m.group(4), m.group(4))):02d}-{int(m.group(3)):02d}" if m else None,
                   "consolidated": False, "content_format": "pdf_text" if text else "html", "text": text or None, "registry_number": reg.group(1) if reg else None, "text_blocked": None if text else ("no /upload/ PDF text" if IGNORE_ROBOTS else "robots.txt disallows /upload/ (official PDF)"),
                   "content_complete": len(text) > 200, "retrieved_at": utcnow(), "place_name": pl["place_name"], "qid": pl["qid"],
                   "platform": "pravo.by", "platform_place_id": did, "issuing_body_name": m.group(2) if m else None,
                   "place_match": pl["match"], "soato": pl.get("soato"), "pdf_url": BASE + pdf.group(1) if pdf else None,
                   "source_official": True, "rights": "official publication of a normative legal act (Law 262-Z art. 8: not copyright objects)"}
            stg.add(rec, key_prefix + did)
        except Exception as e:  # noqa: BLE001
            log.warning("FAIL %s: %s", did, str(e)[:200])
    if stg.keys:
        log.info("flush %s | done %d", dict(stg.flush(done)), done.count())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["poll", "pdftext", "status"])
    ap.add_argument("--loop", type=float, help="repeat every N hours")
    a = ap.parse_args()
    if a.cmd == "status":
        print("done", Done(STATE / "done.sqlite").count()); return
    sess = PoliteSession(log, min_interval=2.0)
    if a.cmd == "pdftext":
        pdftext(sess); return
    while True:
        poll(sess)
        if not a.loop:
            break
        time.sleep(a.loop * 3600)


if __name__ == "__main__":
    main()
