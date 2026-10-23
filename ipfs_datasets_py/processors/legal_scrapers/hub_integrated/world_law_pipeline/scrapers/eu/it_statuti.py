#!/usr/bin/env python3
"""Italy: Ministero dell'Interno (DAIT) Raccolta ufficiale degli statuti comunali e provinciali.

  list    https://dait.interno.gov.it/territorio-e-autonomie-locali/statuti?page=N   (~415 pages x 20)
  detail  https://dait.interno.gov.it/territorio-e-autonomie-locali/statuti/<slug>   (Anno delibera, PDF link)
  pdf     https://dait.interno.gov.it/documenti/statuti/statuto-comune-<pv>-<slug>.pdf  -> pdftotext
robots.txt allows these paths (/search/, /admin/, /user/* disallowed, not used). 1 req/s, single thread.
Places: comune name -> candidate CSV (IT municipality, unique name); ambiguous names / province statutes -> unmatched.
Usage: python3 it_statuti.py catalog | fetch [--limit N] [--test N] | all | status
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths

import argparse
import csv
import gc
import html
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import unicodedata
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.live import STAGE, Done, PoliteSession, Stager, get_logger, utcnow  # noqa: E402

BASE = "https://dait.interno.gov.it"
LIST = BASE + "/territorio-e-autonomie-locali/statuti"
STATE = STAGE / "_state" / "it"
CAT = STATE / "catalog.jsonl"
CAND = Path((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + "/global_municipalities_candidate.csv"))
log = get_logger("it_statuti")
MAX_PDF = 40 * 1024 * 1024


def fold(s):
    s = unicodedata.normalize("NFKD", html.unescape(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s).split())


class Places:
    def __init__(self):
        self.by = defaultdict(list)
        for r in csv.DictReader(CAND.open(encoding="utf-8")):
            if r["country_code"] == "IT" and r["admin_level"] == "municipality":
                self.by[fold(r["place_name"])].append(r)
        for k, v in (("roma", "rome"), ("milano", "milan"), ("napoli", "naples"), ("torino", "turin"),
                     ("firenze", "florence"), ("venezia", "venice"), ("genova", "genoa"), ("padova", "padua"),
                     ("mantova", "mantua"), ("siracusa", "syracuse")):
            if v in self.by and k not in self.by:
                self.by[k] = self.by[v]

    def resolve(self, name, kind):
        res = dict(place_id=None, qid=None, place_name=html.unescape(name), match=None)
        if (kind or "").lower() != "comune":
            res["match"] = f"ente_{fold(kind) or 'unknown'}"
            return res
        cs = self.by.get(fold(name), [])
        if len(cs) == 1:
            res.update(place_id=cs[0]["place_id"], qid=cs[0]["qid"], place_name=cs[0]["place_name"], match="name->candidate(unique)")
        else:
            res["match"] = "ambiguous_name" if cs else "not_in_candidate"
        return res


def catalog(sess):
    STATE.mkdir(parents=True, exist_ok=True)
    stp = STATE / "catalog.state.json"
    st = json.loads(stp.read_text()) if stp.exists() else {"page": -1, "rows": 0, "last_page": None}
    with CAT.open("a", encoding="utf-8") as f:
        while True:
            page = st["page"] + 1
            t = sess.get(LIST, params={"page": page} if page else None).text
            if st["last_page"] is None:
                st["last_page"] = max([int(x) for x in re.findall(r"[?&]page=(\d+)", t)] or [0])
            n = 0
            for m in re.finditer(r'<h2>\s*<a href="(https://dait\.interno\.gov\.it/territorio-e-autonomie-locali/statuti/[^"]+)"[^>]*>(.*?)</a>'
                                 r'.*?Tipologia ente:\s*<span>(.*?)</span>\s*</h3>\s*<p>\s*\((.*?)\)', t, re.S):
                f.write(json.dumps({"url": m.group(1), "name": html.unescape(m.group(2).strip()), "kind": m.group(3).strip(),
                                    "province": html.unescape(m.group(4).strip())}, ensure_ascii=False) + "\n")
                n += 1
            f.flush()
            st.update(page=page, rows=st["rows"] + n)
            stp.write_text(json.dumps(st))
            log.info("list page %d/%s: %d (total %d)", page, st["last_page"], n, st["rows"])
            if page >= st["last_page"] or n == 0:
                break
    st["complete"] = True
    stp.write_text(json.dumps(st))


def pdf_text(sess, url):
    r = sess.get(url, stream=True)
    if int(r.headers.get("Content-Length") or 0) > MAX_PDF:
        r.close()
        raise RuntimeError("pdf too large")
    with tempfile.NamedTemporaryFile(suffix=".pdf") as tf:
        size = 0
        for ch in r.iter_content(1 << 16):
            size += len(ch)
            if size > MAX_PDF:
                raise RuntimeError("pdf too large")
            tf.write(ch)
        tf.flush()
        p = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", tf.name, "-"], capture_output=True, timeout=300)
    t = p.stdout.decode("utf-8", "replace").replace("\f", "\n")
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def fetch(sess, limit=None, test=None):
    done = Done(STATE / ("done_test.sqlite" if test else "done.sqlite"))
    pm = Places()
    stg = Stager("IT", "itstat", log, max_docs=100, stage=(STAGE / "_test_it") if test else STAGE)
    it = random.Random(13).sample(CAT.read_text(encoding="utf-8").splitlines(), test) if test else CAT.open(encoding="utf-8")
    n = 0
    for ln in it:
        a = json.loads(ln)
        key = a["url"].rsplit("/", 1)[-1]
        if done.has(key):
            continue
        if limit and n >= limit:
            break
        n += 1
        try:
            d = sess.get(a["url"]).text
            pdf = re.search(r'href="([^"]*/documenti/statuti/[^"]+\.pdf)"', d)
            anno = re.search(r"Anno delibera.{0,200}?>(\d{4})</time>", d, re.S)
            if not pdf:
                stg.add(None, key, "no_pdf")
                continue
            purl = pdf.group(1) if pdf.group(1).startswith("http") else BASE + pdf.group(1)
            text = pdf_text(sess, purl)
            if len(text) < 200:
                stg.add(None, key, "no_text_layer")
                continue
            pl = pm.resolve(a["name"], a["kind"])
            stg.add({
                "place_id": pl["place_id"], "country_code": "IT", "doc_id": f"it_statuti:{key}", "source_platform": "it_dait_statuti",
                "source_url": a["url"], "doc_type": "statute", "language": "it",
                "title_native": f"Statuto {'del Comune di' if a['kind'].lower() == 'comune' else 'di'} {a['name'].title()}",
                "number": anno.group(1) if anno else key, "adopted_date": None, "published_date": None, "effective_date": None,
                "in_force": True, "consolidated": True, "content_format": "pdf_text", "text": text, "retrieved_at": utcnow(),
                "place_name": pl["place_name"], "qid": pl["qid"], "iso_3166_2": None, "admin_level": "municipality",
                "platform": "dait.interno.gov.it", "platform_place_id": key, "level": "municipality", "place_match": pl["match"],
                "ente_type": a["kind"], "province": a["province"], "delibera_year": anno.group(1) if anno else None, "pdf_url": purl,
                "rights": "official act; not protected by copyright (art. 5 L. 633/1941)",
            }, key)
        except Exception as e:  # noqa: BLE001
            log.warning("FAIL %s: %s", key, str(e)[:200])
        if stg.due():
            log.info("flush %s | done %d", dict(stg.flush(done)), done.count())
            gc.collect()
    if stg.keys:
        log.info("flush %s | done %d", dict(stg.flush(done)), done.count())
    log.info("fetch finished: %s places=%d", dict(stg.total), len(stg.places))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["catalog", "fetch", "all", "status"])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--test", type=int)
    a = ap.parse_args()
    if a.cmd == "status":
        st = STATE / "catalog.state.json"
        print("catalog", st.read_text() if st.exists() else "-", "done", Done(STATE / "done.sqlite").count())
        return
    sess = PoliteSession(log, min_interval=1.0)
    stp = STATE / "catalog.state.json"
    if a.cmd == "catalog" or (a.cmd == "all" and not (stp.exists() and json.loads(stp.read_text()).get("complete"))):
        catalog(sess)
    if a.cmd in ("fetch", "all"):
        fetch(sess, a.limit, a.test)


if __name__ == "__main__":
    main()
