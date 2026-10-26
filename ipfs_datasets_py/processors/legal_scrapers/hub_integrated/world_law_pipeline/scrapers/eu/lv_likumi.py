#!/usr/bin/env python3
"""Latvia: likumi.lv (official publisher Latvijas Vēstnesis) - pašvaldību domes saistošie noteikumi (binding regulations).

Allowed paths only (robots.txt checked per request via common/rfc9309.py; /search.php, /doc.php, /rss/, /js/ and
/*/redakcijas-datums/ are disallowed and never used):
  index    https://likumi.lv/ta/veids                        -> 44 links /ta/veids/<x>-pasvaldibas-dome/saistosie-noteikumi
  listing  https://likumi.lv/ta/veids/<slug>/saistosie-noteikumi  -> hidden izd_id / veids_id
  rows     https://likumi.lv/ajax/ties_akti_pec_veida.php?piece=N&mode=n&izd_id=..&veids_id=..&spe=1&vnspe=1&oby=0&odir=0
           (the same JSON the listing page loads; spe=1 in force, vnspe=1 not yet in force; 50 rows per piece)
  act      https://likumi.lv/ta/id/<doc_id>   (current consolidated text in div.doc-body)
Terms: free public access (portala lietošanas noteikumi); polite 1 req/s single thread.
Usage: python3 lv_likumi.py catalog | fetch [--limit N] [--test N] | all | status
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
import html as htmlmod
import json
import random
import re
import sys
from pathlib import Path

import lxml.html

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.live import STAGE, Done, PoliteSession, Stager, get_logger, utcnow  # noqa: E402

BASE = "https://likumi.lv"
STATE = STAGE / "_state" / "lv"
CAT = STATE / "catalog.jsonl"
CAND = Path((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + "/global_municipalities_candidate.csv"))
log = get_logger("lv_likumi")

# likumi.lv issuer slug stem -> candidate place_name (English, as in the candidate CSV)
SLUG2NAME = {
    "rigas-valstspilsetas": "Riga", "daugavpils-valstspilsetas": "Daugavpils", "jelgavas-valstspilsetas": "Jelgava",
    "jurmalas-valstspilsetas": "Jūrmala", "liepajas-valstspilsetas": "Liepāja", "rezeknes-valstspilsetas": "Rēzekne",
    "ventspils-valstspilsetas": "Ventspils",
    "aizkraukles-novada": "Aizkraukle Municipality", "aluksnes-novada": "Alūksne Municipality",
    "augsdaugavas-novada": "Augšdaugava Municipality", "adazu-novada": "Ādaži Municipality",
    "balvu-novada": "Balvi Municipality", "bauskas-novada": "Bauska Municipality", "cesu-novada": "Cēsis Municipality",
    "dienvidkurzemes-novada": "South Kurzeme Municipality", "dobeles-novada": "Dobele Municipality",
    "gulbenes-novada": "Gulbene Municipality", "jelgavas-novada": "Jelgava Municipality",
    "jekabpils-novada": "Jēkabpils Municipality", "kraslavas-novada": "Krāslava Municipality",
    "kuldigas-novada": "Kuldīga Municipality", "kekavas-novada": "Ķekava Municipality",
    "limbazu-novada": "Limbaži Municipality", "livanu-novada": "Līvāni Municipality", "ludzas-novada": "Ludza Municipality",
    "madonas-novada": "Madona Municipality", "marupes-novada": "Mārupe Municipality", "ogres-novada": "Ogre Municipality",
    "olaines-novada": "Olaine Municipality", "preilu-novada": "Preiļi Municipality", "rezeknes-novada": "Rēzekne Municipality",
    "ropazu-novada": "Ropaži Municipality", "salaspils-novada": "Salaspils Municipality", "saldus-novada": "Saldus Municipality",
    "saulkrastu-novada": "Saulkrasti Municipality", "siguldas-novada": "Sigulda Municipality",
    "smiltenes-novada": "Smiltene Municipality", "talsu-novada": "Talsi Municipality", "tukuma-novada": "Tukums Municipality",
    "valkas-novada": "Valka Municipality", "valmieras-novada": "Valmiera Municipality",
    "ventspils-novada": "Ventspils Municipality",
    # varaklanu-novada (Varakļāni, re-established 2024) is not in the candidate CSV -> unmatched
}


class Places:
    def __init__(self):
        self.by = {}
        for r in csv.DictReader(CAND.open(encoding="utf-8")):
            if r["country_code"] == "LV":
                self.by.setdefault(r["place_name"], r)

    def resolve(self, slug: str) -> dict:
        stem = re.sub(r"-pasvaldibas-dome$", "", slug)
        name = SLUG2NAME.get(stem)
        c = self.by.get(name) if name else None
        if c:
            lvl = "municipality"   # state cities (valstspilsētas) are municipalities too
            return dict(place_id=c["place_id"], qid=c["qid"], place_name=c["place_name"], admin_level=c["admin_level"],
                        level=lvl, match="issuer_slug->candidate")
        return dict(place_id=None, qid=None, place_name=stem, admin_level="municipality", level="municipality",
                    match="issuer_not_in_candidate")


def strip_tags(s):
    return htmlmod.unescape(re.sub(r"<[^>]+>", " ", s or "")).strip()


def ddmmyyyy(v):
    m = re.match(r"(\d{2})\.(\d{2})\.(\d{4})", v or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def catalog(sess) -> int:
    STATE.mkdir(parents=True, exist_ok=True)
    stp = STATE / "catalog.state.json"
    st = json.loads(stp.read_text()) if stp.exists() else {"issuers": None, "done": []}
    if not st["issuers"]:
        t = sess.get(f"{BASE}/ta/veids").text
        st["issuers"] = sorted(set(re.findall(r"/ta/veids/([a-z0-9-]+-pasvaldibas-dome)/saistosie-noteikumi", t)))
        stp.write_text(json.dumps(st))
        log.info("index: %d municipal councils", len(st["issuers"]))
    total = 0
    with CAT.open("a", encoding="utf-8") as f:
        for slug in st["issuers"]:
            if slug in st["done"]:
                continue
            t = sess.get(f"{BASE}/ta/veids/{slug}/saistosie-noteikumi").text
            izd = re.search(r"<span id='izd_id'>(\d+)</span>", t)
            vei = re.search(r"<span id='veids_id'>(\d+)</span>", t)
            if not (izd and vei):
                log.warning("no izd_id/veids_id for %s", slug)
                continue
            q = dict(mode="n", izd_id=izd.group(1), veids_id=vei.group(1), spe=1, vnspe=1, oby=0, odir=0)
            meta = sess.get(f"{BASE}/ajax/ties_akti_pec_veida.php", params=dict(q, piece=0, qwstats=1),
                            headers={"X-Requested-With": "XMLHttpRequest"}).json()
            n = 0
            for piece in range(int(meta.get("pieces") or 0)):
                rows = sess.get(f"{BASE}/ajax/ties_akti_pec_veida.php", params=dict(q, piece=piece),
                                headers={"X-Requested-With": "XMLHttpRequest"}).json()
                for r in rows:
                    tm = re.search(r"href='(/ta/id/[^']+)'", r.get("title") or "")
                    stat = re.search(r"Statuss: </font><font class='fcw3'>([^<]+)<", r.get("status") or "")
                    f.write(json.dumps({"doc_id": r["doc_id"], "issuer_slug": slug, "izd_id": izd.group(1),
                                        "title": strip_tags(r.get("title")), "path": tm.group(1) if tm else None,
                                        "number": r.get("numurs_txt") or r.get("numurs"),
                                        "adopted": ddmmyyyy(r.get("izd_dat")), "effective": ddmmyyyy(r.get("sst_dat")),
                                        "ends": ddmmyyyy(r.get("end_dat")), "published": ddmmyyyy(r.get("pub_dat")),
                                        "status": stat.group(1).strip() if stat else None}, ensure_ascii=False) + "\n")
                    n += 1
            f.flush()
            st["done"].append(slug)
            stp.write_text(json.dumps(st))
            total += n
            log.info("catalog %s: %d acts (site says %s)", slug, n, meta.get("rows"))
    st["complete"] = len(st["done"]) == len(st["issuers"])
    stp.write_text(json.dumps(st))
    return total


def act_text(content: bytes) -> tuple[str, str]:
    d = lxml.html.fromstring(content)
    b = d.xpath('//div[contains(concat(" ",normalize-space(@class)," ")," doc-body ")]')
    if not b:
        return "", ""
    el = b[0]
    for bad in el.xpath('.//script|.//style|.//div[contains(@class,"tooltip")]'):
        bad.drop_tree()
    for br in el.xpath(".//br"):
        br.tail = "\n" + (br.tail or "")
    for p in el.xpath(".//p|.//div|.//tr|.//li|.//h1|.//h2|.//h3|.//h4"):
        p.tail = "\n" + (p.tail or "")
    t = el.text_content()
    t = re.sub(r"[ \t\u00a0]+", " ", t)
    t = re.sub(r" *\n *", "\n", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip(), lxml.html.tostring(el, encoding="unicode")


def build(a, text, pl, url) -> dict:
    return {
        "place_id": pl["place_id"], "country_code": "LV", "doc_id": f"lv_likumi:{a['doc_id']}",
        "source_platform": "lv_likumi", "source_url": url, "doc_type": "regulation", "language": "lv",
        "title_native": a.get("title"), "number": a.get("number") or a["doc_id"], "adopted_date": a.get("adopted"),
        "published_date": a.get("published"), "effective_date": a.get("effective"),
        "in_force": (a.get("status") or "").startswith("spēkā"), "consolidated": True, "content_format": "html",
        "text": text, "retrieved_at": utcnow(), "place_name": pl["place_name"], "qid": pl["qid"], "iso_3166_2": None,
        "admin_level": pl["admin_level"], "platform": "likumi.lv", "platform_place_id": a.get("izd_id"),
        "issuing_body_name": a.get("issuer_slug"), "level": pl["level"], "place_match": pl["match"],
        "status_native": a.get("status"), "expires_date": a.get("ends"),
        "vestnesis_url": f"https://www.vestnesis.lv/ta/id/{a['doc_id']}",
        "rights": "official act; not subject to copyright (Autortiesību likums 6. pants); likumi.lv free access",
    }


def fetch(sess, limit=None, test=None):
    done = Done(STATE / ("done_test.sqlite" if test else "done.sqlite"))
    pm = Places()
    stg = Stager("LV", "lvlik", log, max_docs=200, stage=(STAGE / "_test_lv") if test else STAGE)
    it = random.Random(5).sample(CAT.read_text(encoding="utf-8").splitlines(), test) if test else CAT.open(encoding="utf-8")
    n, seen = 0, set()
    for ln in it:
        a = json.loads(ln)
        did = str(a["doc_id"])
        if did in seen or done.has(did):
            continue
        seen.add(did)
        if limit and n >= limit:
            break
        n += 1
        url = f"{BASE}{a.get('path') or '/ta/id/' + did}"
        try:
            r = sess.get(url)
            text, _ = act_text(r.content)
            del r
            if len(text) < 30:
                raise RuntimeError("empty text")
            stg.add(build(a, text, pm.resolve(a["issuer_slug"]), url), did)
        except PermissionError as e:
            log.warning("robots skip %s: %s", did, e)
            stg.add(None, did, "robots_disallowed")
        except Exception as e:  # noqa: BLE001
            log.warning("FAIL %s: %s", did, str(e)[:200])
            with (STATE / "failed.jsonl").open("a", encoding="utf-8") as ff:
                ff.write(json.dumps({"id": did, "error": str(e)[:300], "at": utcnow()}) + "\n")
        if stg.due():
            s = stg.flush(done)
            log.info("flush %s | done %d", dict(s), done.count())
            gc.collect()
    if stg.keys:
        s = stg.flush(done)
        log.info("flush %s | done %d", dict(s), done.count())
    log.info("fetch finished: %s places=%d", dict(stg.total), len(stg.places))


def status():
    stp = STATE / "catalog.state.json"
    st = json.loads(stp.read_text()) if stp.exists() else {}
    ncat = sum(1 for _ in CAT.open()) if CAT.exists() else 0
    print("issuers", len(st.get("issuers") or []), "catalogued", len(st.get("done") or []), "rows", ncat,
          "done", Done(STATE / "done.sqlite").count())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["catalog", "fetch", "all", "status"])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--test", type=int)
    a = ap.parse_args()
    if a.cmd == "status":
        return status()
    sess = PoliteSession(log, min_interval=1.0)
    stp = STATE / "catalog.state.json"
    if a.cmd == "catalog" or (a.cmd == "all" and not (stp.exists() and json.loads(stp.read_text()).get("complete"))):
        catalog(sess)
    if a.cmd in ("fetch", "all"):
        fetch(sess, a.limit, a.test)


if __name__ == "__main__":
    main()
