#!/usr/bin/env python3
"""UK Local Acts (ukla) from legislation.gov.uk (official API; Open Government Licence v3.0).

  list  https://www.legislation.gov.uk/ukla/data.feed?page=N   (Atom; acts with digitised text)
  text  https://www.legislation.gov.uk/ukla/<year>/<n>/enacted/data.xml   (CLML; text from the Body/Schedules)
robots.txt: Crawl-delay 5 -> honoured by PoliteSession (>= 5 s between requests).
Scope: acts promoted by or for local authorities (title names a Council / Corporation / City / Borough / County /
"London Local Authorities"); company, harbour, railway and estate acts are marked done as non_municipal.
Usage: python3 uk_ukla.py catalog | fetch [--limit N] [--test N] | all | status
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
import json
import random
import re
import sys
from pathlib import Path

from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.live import STAGE, Done, PoliteSession, Stager, get_logger, utcnow  # noqa: E402

BASE = "https://www.legislation.gov.uk"
STATE = STAGE / "_state" / "uk"
CAT = STATE / "catalog.jsonl"
CAND = Path((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + "/global_municipalities_candidate.csv"))
log = get_logger("uk_ukla")
MUNI = re.compile(r"\b(Council|Corporation|City of London|London Local Authorities|Borough|County|District|"
                  r"Metropolitan|Greater London|Mayor|Transport for London)\b", re.I)
LEVEL_PREF = {"unitary_authority": 0, "municipality": 0, "council_area": 0, "principal_area": 0, "county": 1,
              "district": 1, "community": 3, "parish": 4}


def norm(s):
    s = re.sub(r"^(London Borough of|Royal Borough of|City and County of|City of|Borough of|County of|Metropolitan Borough of)\s+",
               "", s.strip(), flags=re.I)
    s = re.sub(r"\s+(City|Borough|District|County|Metropolitan Borough|Council)$", "", s, flags=re.I)
    return " ".join(s.lower().replace("&", "and").split())


class Places:
    def __init__(self):
        self.by = {}
        for r in csv.DictReader(CAND.open(encoding="utf-8")):
            if r["country_code"] != "GB":
                continue
            k = norm(r["place_name"])
            if k not in self.by or LEVEL_PREF.get(r["admin_level"], 5) < LEVEL_PREF.get(self.by[k]["admin_level"], 5):
                self.by[k] = r

    def resolve(self, title: str) -> dict:
        res = dict(place_id=None, qid=None, place_name=None, admin_level=None, match=None)
        m = re.match(r"^(.*?)\s+(?:(?:City|Borough|County|District|Metropolitan Borough|Metropolitan District|"
                     r"County Borough|Town|Parish)\s+)?(?:Council|Corporation)\b", title)
        name = m.group(1) if m else None
        if not name:
            m = re.match(r"^(City of London)\b", title)
            name = m.group(1) if m else None
        if name:
            name = re.sub(r"^(The|Royal|London Borough of|City of)\s+", "", name, flags=re.I)
            c = self.by.get(norm(name))
            if c:
                res.update(place_id=c["place_id"], qid=c["qid"], place_name=c["place_name"], admin_level=c["admin_level"],
                           match="title_council->candidate")
                return res
            res.update(place_name=name, match="council_not_in_candidate")
        else:
            res["match"] = "multi_or_unparsed"
        return res


def catalog(sess):
    STATE.mkdir(parents=True, exist_ok=True)
    stp = STATE / "catalog.state.json"
    st = json.loads(stp.read_text()) if stp.exists() else {"page": 0, "rows": 0}
    ns = {"a": "http://www.w3.org/2005/Atom", "ukm": "http://www.legislation.gov.uk/namespaces/metadata"}
    with CAT.open("a", encoding="utf-8") as f:
        while True:
            page = st["page"] + 1
            r = sess.get(f"{BASE}/ukla/data.feed", params={"page": page})
            root = etree.fromstring(r.content)
            ents = root.findall("a:entry", ns)
            for e in ents:
                g = lambda p: e.find(p, ns)  # noqa: E731
                f.write(json.dumps({"id": g("a:id").text, "title": g("a:title").text,
                                    "year": g("ukm:Year").get("Value") if g("ukm:Year") is not None else None,
                                    "number": g("ukm:Number").get("Value") if g("ukm:Number") is not None else None,
                                    "created": g("ukm:CreationDate").get("Date") if g("ukm:CreationDate") is not None else None,
                                    "summary": g("a:summary").text if g("a:summary") is not None else None},
                                   ensure_ascii=False) + "\n")
            st.update(page=page, rows=st["rows"] + len(ents))
            stp.write_text(json.dumps(st))
            more = root.find("{http://www.legislation.gov.uk/namespaces/legislation}morePages")
            log.info("feed page %d: %d (total %d)", page, len(ents), st["rows"])
            if not ents or more is None or int(more.text or 0) == 0:
                break
    st["complete"] = True
    stp.write_text(json.dumps(st))


def clml_text(b: bytes) -> str:
    root = etree.fromstring(b, etree.XMLParser(huge_tree=True, resolve_entities=False, no_network=True))
    parts = []
    for tag in ("Primary", "Body", "Schedules"):
        for el in root.iter("{http://www.legislation.gov.uk/namespaces/legislation}" + tag):
            for x in el.iter():
                if not isinstance(x.tag, str):
                    continue
                ln = etree.QName(x).localname
                if x.text and x.text.strip():
                    parts.append(x.text.strip() + " ")
                if ln in ("P1", "P2", "P3", "Pnumber", "Title", "Text", "Para", "Row") :
                    parts.append("\n")
                if x.tail and x.tail.strip():
                    parts.append(x.tail.strip() + " ")
            break
    t = re.sub(r"[ \t]+", " ", "".join(parts))
    t = re.sub(r" *\n *", "\n", t)
    return re.sub(r"\n{2,}", "\n", t).strip()


def fetch(sess, limit=None, test=None):
    done = Done(STATE / ("done_test.sqlite" if test else "done.sqlite"))
    pm = Places()
    stg = Stager("GB", "ukla", log, max_docs=50, stage=(STAGE / "_test_uk") if test else STAGE)
    it = random.Random(9).sample(CAT.read_text().splitlines(), test) if test else CAT.open(encoding="utf-8")
    n = 0
    for ln in it:
        a = json.loads(ln)
        key = f"{a['year']}/{a['number']}"
        if done.has(key):
            continue
        if not MUNI.search(a["title"] or ""):
            stg.add(None, key, "non_municipal")
            continue
        if limit and n >= limit:
            break
        n += 1
        url = f"{BASE}/ukla/{key}/enacted/data.xml"
        try:
            r = sess.get(url)
            text = clml_text(r.content)
            if len(text) < 80:   # older acts: metadata only (no digitised text) -> done, not retried
                stg.add(None, key, "no_digitised_text")
                continue
            pl = pm.resolve(a["title"])
            stg.add({
                "place_id": pl["place_id"], "country_code": "GB", "doc_id": f"uk_ukla:{key}", "source_platform": "uk_legislation",
                "source_url": f"{BASE}/ukla/{key}/enacted", "doc_type": "statute", "act_kind": "UK Local Act", "language": "en",
                "title_native": a["title"], "number": f"{a['year']} c. {a['number']}", "adopted_date": a.get("created"),
                "published_date": None, "effective_date": None, "in_force": None, "consolidated": False,
                "content_format": "xml", "text": text, "retrieved_at": utcnow(), "place_name": pl["place_name"],
                "qid": pl["qid"], "iso_3166_2": None, "admin_level": pl["admin_level"] or "municipality",
                "platform": "legislation.gov.uk", "platform_place_id": None, "level": "municipality",
                "place_match": pl["match"], "summary": a.get("summary"), "xml_url": url,
                "rights": "Open Government Licence v3.0 (Crown / Parliamentary copyright)",
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
    sess = PoliteSession(log, min_interval=5.0)
    stp = STATE / "catalog.state.json"
    if a.cmd == "catalog" or (a.cmd == "all" and not (stp.exists() and json.loads(stp.read_text()).get("complete"))):
        catalog(sess)
    if a.cmd in ("fetch", "all"):
        fetch(sess, a.limit, a.test)


if __name__ == "__main__":
    main()
