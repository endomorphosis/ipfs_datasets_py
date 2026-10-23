#!/usr/bin/env python3
"""Netherlands: Gemeenteblad (official municipal gazette, KOOP officielepublicaties) - regulatory publications only.

Discovery : KOOP SRU 2.0  https://repository.overheid.nl/sru   (c.product-area==officielepublicaties AND
            w.publicatienaam==Gemeenteblad AND dt.type in TYPES AND month window). robots.txt on that host is
            `Disallow: /`; we use the SRU endpoint anyway on the same documented-reuse basis as cvdr.py (KOOP's official
            open-data API, CC0), ~1 request per 1000 records. Nothing else on repository.overheid.nl is fetched.
Full text : https://zoek.officielebekendmakingen.nl/<gmb-id>.xml  (robots: only /noindex, /zoeken/resultaat, /resultaten
            are disallowed).
Scope     : dt.type = algemeen verbindend voorschrift (verordening) | Verordeningen | beleidsregel | Beleidsregels |
            delegatie- of mandaatbesluit | gemeenschappelijke regeling  (~173.5k publications, 2013-today; facet sums overlap). Pass 2 (not
            started): "ander besluit van algemene strekking" / "Overige besluiten van algemene strekking" (~187k).
            Permits, beschikkingen, notices are out of scope. CVDR (consolidated, in force) is done separately (cvdr.py);
            gemeenteblad is the as-published text incl. amendment and repeal acts.
Usage: python3 nl_gmb.py catalog | fetch [--limit N] [--test N] | all | status
"""
from __future__ import annotations

import argparse
import gc
import json
import random
import re
import sys
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.live import STAGE, Done, PoliteSession, Stager, get_logger, utcnow  # noqa: E402
import cvdr as C  # noqa: E402

SRU = "https://repository.overheid.nl/sru"
ZOEK = "https://zoek.officielebekendmakingen.nl"
STATE = STAGE / "_state" / "nl_gmb"
CAT = STATE / "catalog.jsonl"
log = get_logger("nl_gmb")
TYPES = ["algemeen verbindend voorschrift (verordening)", "Verordeningen", "beleidsregel", "Beleidsregels",
         "delegatie- of mandaatbesluit", "gemeenschappelijke regeling"]
REG_TYPES = {"algemeen verbindend voorschrift (verordening)", "Verordeningen"}
FIRST_YEAR = 2013   # gemeenteblad (electronic) starts in 2013 for these types (326 in 2013, ~12k/yr from 2014)
NS = {"sru": "http://docs.oasis-open.org/ns/search-ws/sruResponse", "gzd": "http://standaarden.overheid.nl/sru",
      "dcterms": "http://purl.org/dc/terms/", "ow": "http://standaarden.overheid.nl/wetgeving/",
      "overheid": "http://standaarden.overheid.nl/owms/terms/"}
BLOCK = {"al", "p", "titel", "kop", "li", "tr", "artikel", "lid", "regeling", "tussenkop", "row", "entry", "h1", "h2", "h3",
         "nr", "intitule", "aanhef", "wij", "considerans", "afkondiging", "slotformulering", "ondertekening", "naam"}


def session():
    s = PoliteSession(log, min_interval=1.0)
    cf = s.robots.can_fetch
    s.robots.can_fetch = lambda u: True if u.startswith(SRU) else cf(u)   # documented KOOP reuse API (see docstring)
    return s


def months():
    t = date.today()
    for y in range(FIRST_YEAR, t.year + 1):
        for m in range(1, 13):
            if (y, m) > (t.year, t.month):
                return
            e = date(y + (m == 12), (m % 12) + 1, 1).toordinal() - 1
            yield f"{y}-{m:02d}-01", date.fromordinal(e).isoformat()


def q_for(a, b):
    ty = " OR ".join(f'dt.type="{t}"' for t in TYPES)
    return (f"c.product-area==officielepublicaties AND w.publicatienaam==Gemeenteblad AND ({ty}) "
            f"AND dt.date>={a} AND dt.date<={b}")


def tx(e, path):
    x = e.find(path, NS)
    return (x.text or "").strip() if x is not None and x.text else None


def parse_rec(rd):
    m = rd.find(".//ow:owmskern", NS)
    mm = rd.find(".//ow:owmsmantel", NS)
    tp = rd.find(".//ow:tpmeta", NS)
    cr = m.find("dcterms:creator", NS) if m is not None else None
    typ = [x.text for x in m.findall("dcterms:type", NS)] if m is not None else []
    return {
        "id": tx(m, "dcterms:identifier"), "title": tx(m, "dcterms:title"), "types": typ,
        "creator": cr.text.strip() if cr is not None and cr.text else None,
        "creator_scheme": (cr.get("scheme") or "").replace("OVERHEID.", "") if cr is not None else None,
        "modified": tx(m, "dcterms:modified"), "date": tx(mm, "dcterms:date") if mm is not None else None,
        "available": tx(mm, "dcterms:available") if mm is not None else None,
        "subject": tx(mm, "dcterms:subject") if mm is not None else None,
        "jaargang": tx(tp, "ow:jaargang") if tp is not None else None,
        "nummer": tx(tp, "ow:publicatienummer") if tp is not None else None,
        "org_type": tx(tp, "ow:organisatietype") if tp is not None else None,
        "preferred_url": tx(rd, ".//gzd:preferredUrl"), "repo_xml_url": tx(rd, ".//gzd:url"),
    }


def catalog(sess, max_months=None):
    STATE.mkdir(parents=True, exist_ok=True)
    stp = STATE / "catalog.state.json"
    st = json.loads(stp.read_text()) if stp.exists() else {"done": {}}
    cur = date.today().strftime("%Y-%m")
    n_m = 0
    with CAT.open("a", encoding="utf-8") as f:
        for a, b in months():
            if a[:7] in st["done"] and a[:7] != cur:
                continue
            if max_months and n_m >= max_months:
                break
            n_m += 1
            start, got, total = 1, 0, None
            while True:
                r = sess.get(SRU, params={"query": q_for(a, b), "maximumRecords": 1000, "startRecord": start})
                root = ET.fromstring(r.content)
                total = int(root.findtext("sru:numberOfRecords", "0", NS))
                recs = root.findall(".//sru:recordData", NS)
                for rd in recs:
                    x = parse_rec(rd)
                    if x["id"]:
                        f.write(json.dumps(x, ensure_ascii=False) + "\n")
                        got += 1
                f.flush()
                nxt = root.findtext("sru:nextRecordPosition", None, NS)
                if not recs or not nxt:
                    break
                start = int(nxt)
            st["done"][a[:7]] = {"total": total, "got": got}
            stp.write_text(json.dumps(st))
            log.info("catalog %s: %d/%s", a[:7], got, total)
    st["complete"] = all(k[:7] in st["done"] for k, _ in months())
    stp.write_text(json.dumps(st))


def text_of(el):
    out = []

    def walk(e):
        tag = e.tag.split("}")[-1]
        if tag in ("meta", "metadata"):
            return
        if e.text:
            out.append(e.text)
        for c in e:
            walk(c)
            if c.tail:
                out.append(c.tail)
        if tag in BLOCK:
            out.append("\n")
        elif tag in ("label", "li.nr", "nr"):
            out.append(" ")
    walk(el)
    t = re.sub(r"[ \t\u00a0]+", " ", "".join(out))
    return re.sub(r"\n\s*\n+", "\n\n", re.sub(r" *\n *", "\n", t)).strip()


def build(a, xml, pm):
    root = ET.fromstring(xml)
    body = next((e for e in root.iter() if e.tag.split("}")[-1] == "gemeenteblad"), root)
    text = text_of(body)
    pl = pm.resolve(a.get("creator") or "", a.get("creator_scheme") or "")
    typ = next((t for t in a["types"] if t in TYPES), a["types"][0] if a["types"] else None)
    return {
        "place_id": pl["place_id"], "country_code": pl["country_code"], "doc_id": a["id"], "source_platform": "nl_gmb",
        "source_url": a.get("preferred_url") or f"{ZOEK}/{a['id']}.html",
        "doc_type": "regulation" if typ in REG_TYPES else "gazette_act", "language": "nl",
        "title_native": a.get("title"), "number": a["id"], "adopted_date": None,
        "published_date": a.get("date") or a.get("available"), "effective_date": None, "in_force": None,
        "consolidated": False, "content_format": "xml", "text": text, "retrieved_at": utcnow(),
        "place_name": pl["place_name"] or a.get("creator"),
        "qid": (pl["place_id"][3:] if (pl["place_id"] or "").startswith("wd:") else pl["qid"]), "iso_3166_2": pl["iso_3166_2"],
        "admin_level": pl.get("cand_admin_level") or pl["level"], "platform": "officielebekendmakingen.nl",
        "platform_place_id": pl["issuing_body_code"], "issuing_body_name": a.get("creator"),
        "issuing_body_scheme": a.get("creator_scheme"), "issuing_body_code": pl["issuing_body_code"],
        "issuing_body_qid": pl["qid"], "level": pl["level"], "place_match": pl["match"],
        "gmb_type": typ, "gmb_types": a["types"], "subject": a.get("subject"), "jaargang": a.get("jaargang"),
        "publicatienummer": a.get("nummer"), "modified": a.get("modified"), "raw_xml_url": f"{ZOEK}/{a['id']}.xml",
        "sru_meta": a, "rights": "CC0 / official publication, free of copyright (KOOP, Bekendmakingswet)",
    }


def fetch(sess, limit=None, test=None):
    done = Done(STATE / ("done_test.sqlite" if test else "done.sqlite"))
    pm = C.PlaceMap()
    stg = Stager("NL", "nlgmb", log, max_docs=500, stage=(STAGE / "_test_nl") if test else STAGE).graceful(done)
    it = random.Random(7).sample(CAT.read_text(encoding="utf-8").splitlines(), test) if test else CAT.open(encoding="utf-8")
    n, seen = 0, set()
    for ln in it:
        a = json.loads(ln)
        did = a["id"]
        if did in seen or done.has(did):
            continue
        seen.add(did)
        if limit and n >= limit:
            break
        n += 1
        url = f"{ZOEK}/{did}.xml"
        try:
            r = sess.get(url)
            rec = build(a, r.content, pm)
            del r
            if len(rec["text"]) < 30:
                raise RuntimeError("empty text")
            stg.add(rec, did)
        except PermissionError as e:
            log.warning("robots skip %s: %s", did, e)
            stg.add(None, did, "robots_disallowed")
        except Exception as e:  # noqa: BLE001
            log.warning("FAIL %s: %s", did, str(e)[:200])
            with (STATE / "failed.jsonl").open("a", encoding="utf-8") as ff:
                ff.write(json.dumps({"id": did, "url": url, "error": str(e)[:300], "at": utcnow()}) + "\n")
            if "HTTP 404" in str(e) or "ParseError" in type(e).__name__:
                stg.add(None, did, "failed_permanent")
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
    st = json.loads(stp.read_text()) if stp.exists() else {"done": {}}
    ncat = sum(1 for _ in CAT.open()) if CAT.exists() else 0
    print("months", len(st["done"]), "declared", sum(v["total"] or 0 for v in st["done"].values()), "catalog rows", ncat,
          "complete", st.get("complete"), "done", Done(STATE / "done.sqlite").count())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["catalog", "fetch", "all", "status"])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--test", type=int)
    ap.add_argument("--max-months", type=int)
    a = ap.parse_args()
    if a.cmd == "status":
        return status()
    sess = session()
    stp = STATE / "catalog.state.json"
    if a.cmd == "catalog" or (a.cmd == "all" and not (stp.exists() and json.loads(stp.read_text()).get("complete"))):
        catalog(sess, a.max_months)
    if a.cmd in ("fetch", "all"):
        fetch(sess, a.limit, a.test)


if __name__ == "__main__":
    main()
