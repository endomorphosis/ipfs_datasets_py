#!/usr/bin/env python3
"""Slovenia: Uradni list RS (official gazette, archive to 28.2.2026) - section OBČINE (municipal acts).

Allowed paths only (robots.txt: Disallow /_pdf/*/*a/ only; checked per request via common/rfc9309.py):
  issue index  https://www.uradni-list.si/glasilo-uradni-list-rs/celotno-kazalo/<YYYY><issue>   (e.g. 202610 = 10/2026)
               -> <th id="groupTitle-OBČINE"> section, <h3> municipality headers, act links /vsebina/<YYYY-01-NNNN>/<slug>
  act          https://www.uradni-list.si/glasilo-uradni-list-rs/vsebina/<YYYY-01-NNNN>/<slug>  (div#divSection text)
Terms (splošni pogoji 2.1): use restrictions "ne veljajo za Uradni list RS in v njem objavljene vsebine"; the ban on
automated systematic crawling applies only to the razglasni del (announcements), which is not touched.
Issues after 28.2.2026 are published on PISRS, whose API needs a permit (not used: no logins).
Usage: python3 si_ul.py catalog | fetch [--limit N] [--test N] | all | status
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
import unicodedata
from pathlib import Path

import lxml.html

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.live import STAGE, Done, PoliteSession, Stager, get_logger, utcnow  # noqa: E402

BASE = "https://www.uradni-list.si"
STATE = STAGE / "_state" / "si"
CAT = STATE / "catalog.jsonl"
CAND = Path((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + "/global_municipalities_candidate.csv"))
FIRST_YEAR, LAST_YEAR = 1991, 2026
log = get_logger("si_ul")
DTYPE = [("odlok", "ordinance"), ("pravilnik", "regulation"), ("statut", "statute"), ("poslovnik", "regulation"),
         ("sklep", "decision"), ("odločba", "decision"), ("navodilo", "regulation")]   # schema.DOC_TYPES only


def fold(s):
    s = unicodedata.normalize("NFC", s or "").lower()
    s = re.sub(r"[\u2013\u2014-]", "-", s)
    s = re.sub(r"\s*-\s*", "-", s)
    return " ".join(s.split())


def base_name(n):
    n = re.sub(r"^(City|Urban)?\s*Municipality of\s+", "", n.strip(), flags=re.I)
    n = re.sub(r"\s+(City\s+)?Municipality$", "", n, flags=re.I)
    n = re.sub(r"^(Mestna\s+)?Občina\s+", "", n, flags=re.I)
    return fold(n)


class Places:
    def __init__(self):
        self.by = {}
        for r in csv.DictReader(CAND.open(encoding="utf-8")):
            if r["country_code"] == "SI" and r["admin_level"] == "municipality":
                if not re.search(r"municipality|občina", r["place_name"], re.I) and \
                        r["place_name"] not in ("Novo Mesto",):
                    continue   # local communities (KS, settlements) mislabelled as municipality
                self.by.setdefault(base_name(r["place_name"]), r)

    def resolve(self, header: str) -> dict:
        c = self.by.get(base_name(header))
        if c:
            return dict(place_id=c["place_id"], qid=c["qid"], place_name=c["place_name"], match="gazette_header->candidate")
        return dict(place_id=None, qid=None, place_name=header, match="header_not_in_candidate")


def clean(s):
    return " ".join(htmlmod.unescape(re.sub(r"<[^>]+>", " ", s or "")).split())


def parse_issue(t: str):
    m = re.search(r"Uradni list RS, št\. (\d+)/(\d{4}) z dne (\d{1,2})\. ?(\d{1,2})\. ?(\d{4})", t)
    pub = f"{m.group(5)}-{int(m.group(4)):02d}-{int(m.group(3)):02d}" if m else None
    out = []
    for sec in re.finditer(r'id="groupTitle-([^"]+)"(.*?)(?=id="groupTitle-|\Z)', t, re.S):
        if fold(sec.group(1)) != "občine":
            continue
        cur = None
        for row in re.finditer(r'<h3 class="h5">(.*?)</h3>|<td>(\d+)\.</td>\s*<td><a href="(/glasilo-uradni-list-rs/vsebina/([^"/]+)/[^"]*)"[^>]*>(.*?)</a>',
                               sec.group(2), re.S):
            if row.group(1) is not None:
                cur = clean(row.group(1))
            else:
                out.append({"sop": row.group(4), "no": row.group(2), "path": row.group(3), "title": clean(row.group(5)),
                            "municipality": cur, "published": pub,
                            "issue": f"{m.group(1)}/{m.group(2)}" if m else None})
    return out


def catalog(sess) -> int:
    STATE.mkdir(parents=True, exist_ok=True)
    stp = STATE / "catalog.state.json"
    st = json.loads(stp.read_text()) if stp.exists() else {"year": FIRST_YEAR, "issue": 0, "misses": 0, "rows": 0}
    with CAT.open("a", encoding="utf-8") as f:
        while st["year"] <= LAST_YEAR:
            iss = st["issue"] + 1
            r = sess.get(f"{BASE}/glasilo-uradni-list-rs/celotno-kazalo/{st['year']}{iss}", ok=(200, 500))
            t = r.text if r.status_code == 200 else ""   # some non-existent issues answer HTTP 500 instead of a redirect
            if r.status_code == 500:
                log.info("issue %d/%d: HTTP 500 (treated as missing)", iss, st["year"])
            if "/glasilo-uradni-list-rs/vsebina/" not in t:
                st["misses"] += 1
                st["issue"] = iss
                if st["misses"] >= 5:
                    log.info("year %d done at issue %d", st["year"], iss - 5)
                    st.update(year=st["year"] + 1, issue=0, misses=0)
                stp.write_text(json.dumps(st))
                continue
            rows = parse_issue(t)
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            st.update(issue=iss, misses=0, rows=st["rows"] + len(rows))
            stp.write_text(json.dumps(st))
            log.info("issue %d/%d: %d municipal acts (total %d)", iss, st["year"], len(rows), st["rows"])
    st["complete"] = True
    stp.write_text(json.dumps(st))
    return st["rows"]


def act_text(content: bytes) -> str:
    d = lxml.html.fromstring(content)
    b = d.xpath('//div[@id="divSection"]')
    if not b:
        return ""
    el = b[0]
    for bad in el.xpath(".//script|.//style"):
        bad.drop_tree()
    for br in el.xpath(".//br"):
        br.tail = "\n" + (br.tail or "")
    for p in el.xpath(".//p|.//div|.//tr|.//li|.//h1|.//h2|.//h3|.//h4"):
        p.tail = "\n" + (p.tail or "")
    t = re.sub(r"[ \t\u00a0]+", " ", el.text_content())
    t = re.sub(r" *\n *", "\n", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def doc_type(title):
    t = fold(title)
    for k, v in DTYPE:
        if t.startswith(k):
            return v
    return "gazette_act"


def build(a, text, pl, url) -> dict:
    return {
        "place_id": pl["place_id"], "country_code": "SI", "doc_id": f"si_ul:{a['sop']}", "source_platform": "si_uradni_list",
        "source_url": url, "doc_type": doc_type(a["title"]), "language": "sl", "title_native": a["title"],
        "number": f"{a.get('no')}/{a.get('issue')}", "adopted_date": None, "published_date": a.get("published"),
        "effective_date": None, "in_force": None, "consolidated": False, "content_format": "html", "text": text,
        "retrieved_at": utcnow(), "place_name": pl["place_name"], "qid": pl["qid"], "iso_3166_2": None,
        "admin_level": "municipality", "platform": "uradni-list.si", "platform_place_id": None,
        "issuing_body_name": a.get("municipality"), "level": "municipality", "place_match": pl["match"],
        "act_kind": (a["title"].split() or [""])[0], "gazette": f"Uradni list RS, št. {a.get('issue')}", "sop_id": a["sop"],
        "rights": "official act; not protected by copyright (ZASP 9. člen); Uradni list RS terms exempt gazette content",
    }


def fetch(sess, limit=None, test=None):
    done = Done(STATE / ("done_test.sqlite" if test else "done.sqlite"))
    pm = Places()
    stg = Stager("SI", "siul", log, max_docs=300, stage=(STAGE / "_test_si") if test else STAGE)
    it = random.Random(7).sample(CAT.read_text(encoding="utf-8").splitlines(), test) if test else CAT.open(encoding="utf-8")
    n, seen = 0, set()
    for ln in it:
        a = json.loads(ln)
        did = a["sop"]
        if did in seen or done.has(did):
            continue
        seen.add(did)
        if limit and n >= limit:
            break
        n += 1
        url = BASE + a["path"]
        try:
            r = sess.get(url)
            text = act_text(r.content)
            del r
            if len(text) < 30:
                raise RuntimeError("empty text")
            stg.add(build(a, text, pm.resolve(a.get("municipality") or ""), url), did)
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
    print("catalog", json.loads(stp.read_text()) if stp.exists() else {}, "done", Done(STATE / "done.sqlite").count())


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
