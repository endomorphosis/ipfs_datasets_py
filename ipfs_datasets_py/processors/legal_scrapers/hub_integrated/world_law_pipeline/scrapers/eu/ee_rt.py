#!/usr/bin/env python3
"""Estonia: Riigi Teataja RT IV (kohaliku omavalitsuse määrused), current consolidated texts.

Endpoints (official, open data; robots.txt allows /api/ and /public-api/):
  list  https://www.riigiteataja.ee/api/oigusakt_otsing/1/otsi?kov=true&kehtiv=2026-10-11&leht=N&limiit=500
        (kov=true -> only local-government acts; kehtiv=<date> -> texts valid on that date. Rows with
        kehtivKehtetus=true are "Kehtetu" (repealed) marker texts and are skipped without fetching.)
  XML   https://www.riigiteataja.ee/public-api/api/v1/akt/<globaalID>/xml   (the old /akt/<id>.xml is gone since 2026-06-01)
Usage: python3 ee_rt.py catalog | fetch [--limit N] [--test N] | all | status
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
import unicodedata
from pathlib import Path

from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.live import STAGE, Done, PoliteSession, Stager, get_logger, utcnow  # noqa: E402
from common.xwalk import ADDITIONS, SUCCESSORS, denied  # noqa: E402

BASE = "https://www.riigiteataja.ee"
STATE = STAGE / "_state" / "ee"
CAT = STATE / "catalog.jsonl"
VALID_ON = "2026-10-11"   # list = texts valid on this date (kehtiv=); kehtivKehtetus=true rows are "Kehtetu" (repealed) stubs -> skipped
CAND = Path((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + "/global_municipalities_candidate.csv"))
log = get_logger("ee_rt")
BLOCK = {"pealkiri", "paragrahvPealkiri", "loige", "alampunkt", "tavatekst", "sisuTekst", "preambul", "paragrahv",
         "jagu", "peatykk", "osa", "allkiri", "lisa", "lisaViide", "kuvatavNr"}
ISSUER = re.compile(r"^(?P<base>.+?)\s+(?P<org>Vallavolikogu|Vallavalitsus|Linnavolikogu|Linnavalitsus|"
                    r"Vallavanem|Linnapea|Volikogu|valla(?:volikogu|valitsus)|linna(?:volikogu|valitsus))\b", re.I)
CITY_GEN = {"tallinna": "Tallinn", "tartu": "Tartu", "narva": "Narva", "pärnu": "Pärnu", "kohtla-järve": "Kohtla-Järve",
            "viljandi": "Viljandi", "maardu": "Maardu", "rakvere": "Rakvere", "kuressaare": "Kuressaare",
            "sillamäe": "Sillamäe", "valga": "Valga", "võru": "Võru", "jõhvi": "Jõhvi", "haapsalu": "Haapsalu",
            "keila": "Keila", "paide": "Paide", "narva-jõesuu": "Narva-Jõesuu", "loksa": "Loksa"}


CURRENT_CITIES = {"tallinn", "tartu", "narva", "pärnu", "kohtla-järve", "viljandi", "rakvere", "maardu", "sillamäe",
                  "võru", "keila", "haapsalu", "paide", "narva-jõesuu", "loksa"}


def fold(s):
    return " ".join(unicodedata.normalize("NFC", s or "").lower().split())


class Places:
    def __init__(self):
        self.vald, self.any = {}, {}
        for r in csv.DictReader(CAND.open(encoding="utf-8")):
            if r["country_code"] != "EE":
                continue
            n = r["place_name"]
            base = re.sub(r"\s+(Rural Municipality|Parish|vald|linn|City|Town|County)$", "", n)
            if r["admin_level"] == "municipality":
                self.vald.setdefault(fold(base), r)
            self.any.setdefault(fold(n), r)
        self.by_pid = {}
        for r in csv.DictReader(CAND.open(encoding="utf-8")):
            if r["country_code"] == "EE":
                self.by_pid.setdefault(r["place_id"], r)
        # shared place_additions.csv: the 15 current town municipalities (linnad) missing from the candidate CSV
        self.add_linn = {}
        for r in ADDITIONS.rows("EE"):
            self.by_pid.setdefault(r["place_id"], dict(r, place_name=r["name"]))
            self.add_linn[fold(re.sub(r"\s+linn$", "", r["name"]))] = r

    def _place(self, pid):
        r = self.by_pid.get(pid)
        if r:
            return r
        a = ADDITIONS.row(pid)
        return dict(a, place_name=a["name"]) if a else None

    def resolve(self, issuer: str) -> dict:
        res = dict(place_id=None, qid=None, place_name=None, admin_level="municipality", level="municipality",
                   match=None, issuer_base=None)
        m = ISSUER.match(issuer or "")
        if not m:
            res["match"], res["level"] = "issuer_unparsed", "other"
            return res
        base, org = m.group("base"), m.group("org").lower()
        res["issuer_base"] = base
        kind = "linn" if org.startswith("linn") else "vald"
        key = fold(CITY_GEN.get(fold(base), base)) if kind == "linn" else fold(base)
        # the 15 current cities (linnad) are separate municipalities, not the same-named vald (Viljandi linn != Viljandi vald);
        # other "<X> Linnavolikogu" issuers are towns merged in 2017 into the same-named vald (Valga, Elva, Jõhvi, ...)
        c = None if (kind == "linn" and key in CURRENT_CITIES) else self.vald.get(key)
        if c and denied(c["place_id"]):
            c = None
        if c:
            res.update(place_id=c["place_id"], qid=c["qid"], place_name=c["place_name"], match=f"issuer->{kind}->candidate")
            return res
        old = f"{CITY_GEN.get(fold(base), base)} {kind}"
        res["place_name"] = old
        if kind == "linn" and key in self.add_linn:          # current town municipality from place_additions.csv
            a = self.add_linn[key]
            res.update(place_id=a["place_id"], qid=a.get("qid") or a["place_id"][3:], place_name=a["name"],
                       match="issuer->linn->additions", ehak=a.get("official_code") or None)
            return res
        sc = SUCCESSORS.lookup("EE", name=old)
        if sc["status"] == "ok" and not denied(sc["place_id"]):
            t = self._place(sc["place_id"])
            res.update(place_id=sc["place_id"], qid=(t or {}).get("qid") or sc["place_id"][3:],
                       place_name=(t or {}).get("place_name") or sc["successor_name"], match=f"{kind}->successor",
                       mapped_via="successor", former_name=sc["old_name"], former_code=sc["old_code"],
                       dissolved_date=sc["dissolved_date"], ehak=sc.get("successor_code"))
            return res
        if sc["status"] == "ambiguous":
            res["match"] = f"{kind}->successor_ambiguous"
            res["successor_candidates"] = sc["candidates"]
            return res
        res["match"] = f"{kind}_not_in_candidate"  # pre-2017 municipalities without a successor row
        return res


def xml_text(b: bytes) -> tuple[str, dict]:
    root = etree.fromstring(b, etree.XMLParser(huge_tree=True, resolve_entities=False, no_network=True))
    for el in root.iter():   # drop embedded base64 blobs (images/attachments) that are not legal text
        if isinstance(el.tag, str) and el.text and len(el.text) > 200_000 and " " not in el.text[:2000]:
            el.text = ""
    for el in root.iter():
        if isinstance(el.tag, str):
            el.tag = etree.QName(el).localname
    meta = {}
    md = root.find("metaandmed")
    if md is not None:
        for k in ("valjaandja", "dokumentLiik", "tekstiliik", "aktikuupaev", "aktiNr", "RTosa", "avaldamineKuupaev",
                  "RTaasta", "RTartikkel", "kehtivuseAlgus", "kehtivuseLopp", "globaalID", "terviktekstiGrupiID"):
            e = md.find(f".//{k}")
            if e is not None and (e.text or "").strip():
                meta[k] = e.text.strip()
        md.getparent().remove(md)
    parts = []

    def walk(el):
        if el.tag == "kuvatavNr":
            parts.append((el.text or "").strip() + " ")
            return
        if el.text and el.text.strip():
            parts.append(el.text.strip() + " ")
        for ch in el:
            if isinstance(ch.tag, str):
                walk(ch)
            if ch.tail and ch.tail.strip():
                parts.append(ch.tail.strip() + " ")
        if el.tag in BLOCK and el.tag != "kuvatavNr":
            parts.append("\n")
    walk(root)
    t = "".join(parts)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r" *\n *", "\n", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip(), meta


def catalog(sess) -> int:
    STATE.mkdir(parents=True, exist_ok=True)
    stp = STATE / "catalog.state.json"
    st = json.loads(stp.read_text()) if stp.exists() else {"page": 0, "total": None}
    with CAT.open("a", encoding="utf-8") as f:
        while True:
            page = st["page"] + 1
            r = sess.get(f"{BASE}/api/oigusakt_otsing/1/otsi", params={"kov": "true", "kehtiv": VALID_ON,
                                                                       "leht": page, "limiit": 500})
            d = r.json()
            st["total"] = d["metaandmed"]["kokku"]
            acts = d.get("aktid") or []
            for a in acts:
                f.write(json.dumps(a, ensure_ascii=False) + "\n")
            f.flush()
            st["page"] = page
            stp.write_text(json.dumps(st))
            log.info("catalog page %d: %d acts (total %s)", page, len(acts), st["total"])
            if not acts or page * 500 >= st["total"]:
                st["complete"] = True
                stp.write_text(json.dumps(st))
                return st["total"]


def d10(v):
    """'2019-01-08+02:00' / '2019-01-08T00:00:00+02:00' -> '2019-01-08' (schema wants plain ISO dates)."""
    m = re.match(r"\d{4}-\d{2}-\d{2}", v or "")
    return m.group(0) if m else None


def build(a, text, meta, pl, url) -> dict:
    gid = str(a["globaalID"])
    rt = f"{meta.get('RTosa', 'RT IV')}, {meta.get('avaldamineKuupaev', '')}, {meta.get('RTartikkel', '')}".strip(", ")
    return {
        "place_id": pl["place_id"], "country_code": "EE", "doc_id": f"ee_rt:{gid}", "source_platform": "ee_riigiteataja",
        "source_url": f"{BASE}/akt/{gid}", "doc_type": "regulation", "language": "et", "title_native": a.get("pealkiri"),
        "number": meta.get("aktiNr") or gid, "adopted_date": d10(meta.get("aktikuupaev")),
        "published_date": d10(meta.get("avaldamineKuupaev")), "effective_date": d10(meta.get("kehtivuseAlgus")),
        "in_force": not a.get("mitteJoustunud"), "consolidated": "terviktekst" in (a.get("tekst") or ""), "content_format": "xml",
        "text": text, "retrieved_at": utcnow(), "place_name": pl["place_name"], "qid": pl["qid"],
        "iso_3166_2": None, "admin_level": pl["admin_level"], "platform": "ee_riigiteataja", "platform_place_id": None,
        "issuing_body_name": a.get("valjaandja"), "level": pl["level"], "place_match": pl["match"],
        **{k: pl[k] for k in ("mapped_via", "former_name", "former_code", "dissolved_date", "successor_candidates", "ehak") if pl.get(k)},
        "rt_reference": rt, "terviktekst_group_id": a.get("terviktekstID"), "valid_from": (a.get("kehtivus") or {}).get("algus"),
        "xml_url": f"{BASE}/public-api/api/v1/akt/{gid}/xml", "act_type": a.get("liik"), "text_kind": a.get("tekst"),
        "rights": "official act; free reuse (Riigi Teataja open data, Autoriõiguse seadus § 5)",
    }


def fetch(sess, limit=None, test=None):
    done = Done(STATE / ("done_test.sqlite" if test else "done.sqlite"))
    pm = Places()
    stg = Stager("EE", "eert", log, stage=(STAGE / "_test_ee") if test else STAGE)
    stg.graceful(done)
    lines = None
    if test:
        lines = random.Random(3).sample(CAT.read_text(encoding="utf-8").splitlines(), test)
    it = lines if lines is not None else CAT.open(encoding="utf-8")
    n = 0
    seen = set()
    for ln in it:
        a = json.loads(ln)
        gid = str(a["globaalID"])
        if gid in seen or done.has(gid):
            continue
        seen.add(gid)
        if a.get("kehtivKehtetus"):
            stg.add(None, gid, "repealed_stub")
            continue
        if limit and n >= limit:
            break
        n += 1
        url = f"{BASE}/public-api/api/v1/akt/{gid}/xml"
        try:
            r = sess.get(url)
            text, meta = xml_text(r.content)
            del r
            if len(text) < 30:
                raise RuntimeError("empty text")
            stg.add(build(a, text, meta, pm.resolve(a.get("valjaandja")), url), gid)
        except Exception as e:  # noqa: BLE001
            log.warning("FAIL %s: %s", gid, str(e)[:200])
            with (STATE / "failed.jsonl").open("a", encoding="utf-8") as ff:
                ff.write(json.dumps({"id": gid, "error": str(e)[:300], "at": utcnow()}) + "\n")
        if stg.due():
            s = stg.flush(done)
            log.info("flush %s | done %d", dict(s), done.count())
            gc.collect()
    if stg.keys:
        s = stg.flush(done)
        log.info("flush %s | done %d", dict(s), done.count())
    log.info("fetch finished: %s places=%d", dict(stg.total), len(stg.places))


def status():
    st = json.loads((STATE / "catalog.state.json").read_text()) if (STATE / "catalog.state.json").exists() else {}
    print("catalog", st, "done", Done(STATE / "done.sqlite").count())


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
