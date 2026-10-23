#!/usr/bin/env python3
"""legislation.gov.uk local legislation for the ukie lane (official API, OGL v3.0; robots Crawl-delay 5 honoured).

  ukla   UK Local Acts: Atom /ukla/data.feed?page=N -> CLML /ukla/<y>/<n>/enacted/data.xml
  lsi    local SIs/SSIs/WSIs/NISRs (title-feed queries, e.g. byelaws confirmation, parking designation, electoral
         changes, local traffic/harbour orders naming a council) -> /<type>/<y>/<n>/made/data.xml
CLML -> text with ipfs_datasets_py's national_collectors/collect_legislation_gov_uk.parse_clml (imported read-only
from /workspace/ipfs_datasets_py_latest; its Wayback helper module is stubbed so it can never make archive requests).
doc_id: uk_ukla:<y>/<n> (identical to scrapers/eu/uk_ukla.py so already-published acts merge, never duplicate);
        uk_<type>:<y>/<n> for SIs.
Place: council named in the title -> candidate place (phase 1), with a small successor table; acts for several
councils (London Local Authorities Acts, TfL) -> _state/unmatched_legislation.jsonl with the reason.
Usage: python3 legislation_uk.py ukla --pages 1-3 [--ids 2012/2,1998/2] | lsi --queries q1,q2 --max N | status
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))

import argparse
import json
import re
import sys
import types
from pathlib import Path

from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.util import LANE, STAGE, STATE_DIR, PoliteSession, State, StopRun, append_jsonl, get_logger, guard, utcnow  # noqa: E402,E501
from places import Places, fold, place_codes  # noqa: E402
from archive.staging import StagedWriter  # noqa: E402

sys.modules.setdefault("archive_fallbacks", types.ModuleType("archive_fallbacks"))


def _load_ipfs_uk():
    """Import the ipfs collector with ITS OWN 'common' module (ours shares the name), then restore ours."""
    import importlib
    nc = "/workspace/ipfs_datasets_py_latest/ipfs_datasets_py/processors/legal_scrapers/national_collectors"
    saved = {k: v for k, v in sys.modules.items() if k == "common" or k.startswith("common.")}
    for k in saved:
        del sys.modules[k]
    sys.path.insert(0, nc)
    try:
        return importlib.import_module("collect_legislation_gov_uk")
    finally:
        sys.path.remove(nc)
        ipfs_common = sys.modules.pop("common", None)
        sys.modules.update(saved)
        sys.modules["_ipfs_nc_common"] = ipfs_common


ipfs_uk = _load_ipfs_uk()

BASE = "https://www.legislation.gov.uk"
log = get_logger("ukie_legislation")
NS = {"a": "http://www.w3.org/2005/Atom", "ukm": "http://www.legislation.gov.uk/namespaces/metadata"}
UNMATCHED = STATE_DIR / "unmatched_legislation.jsonl"
MULTI = re.compile(r"^(?:The\s+)?London\b|London Local Authorities|Transport for London|Greater London|London Docklands|"
                   r"London Regional Transport|London Underground|London Transport", re.I)
COUNCIL = re.compile(r"^(?:The\s+)?(.+?)\s+(?:(?:City|County|Borough|District|Metropolitan Borough|Regional|Islands|"
                     r"Town)\s+)?(?:Council|Corporation)\b", re.I)
SUCCESSOR = {  # dissolved promoter -> current principal council (candidate place name)
    "shrewsbury and atcham": "Shropshire", "highland": "Highland", "western isles": "Outer Hebrides",
    "comhairle nan eilean siar": "Outer Hebrides", "south lakeland": "Westmorland and Furness",
    # pre-1996/2019 promoters -> current principal council (ukie, 2026-10-18)
    "orkney": "Orkney Islands", "orkney islands": "Orkney Islands", "shetland": "Shetland Islands",
    "shetlands islands": "Shetland Islands", "shetlands": "Shetland Islands", "zetland": "Shetland Islands", "bath": "Bath and North East Somerset",
    "brighton": "Brighton and Hove", "hove": "Brighton and Hove", "huddersfield": "Kirklees",
    "poole": "Bournemouth, Christchurch and Poole", "bournemouth": "Bournemouth, Christchurch and Poole",
    "christchurch": "Bournemouth, Christchurch and Poole", "blackburn": "Blackburn with Darwen",
}
AMBIGUOUS = {"strathclyde", "lothian", "grampian", "tayside", "central", "fife regional", "greater manchester",
             "merseyside", "west midlands", "south yorkshire", "tyne and wear", "west yorkshire", "cheshire",
             "humberside", "avon", "cleveland", "berkshire", "dyfed", "gwent", "clwyd", "gwynedd county",
             "mid glamorgan", "south glamorgan", "west glamorgan", "borders regional", "dumfries and galloway regional",
             "highland regional", "central regional"}


NONMUNI = re.compile(r"\b(Company|Companies|Railway|Canal|Dock|Docks|Harbour Trust|Water|Gas|Electric|Tramways?|Bank|"
                     r"Estates?|Church|Chapel|College|University|Hospital|Charity|Charities|Society|Trust|Navigation|"
                     r"Insurance|Building Society|Port|Pier|Bridge|Turnpike|Inclosure|Enclosure|Harbour|Board|Agency|Authority|Freemen|Commons|Conservators|Commissioners)\b", re.I)
PREFIX = re.compile(r"^(?:The\s+)?(?:City and County of|City of|Royal Borough of|London Borough of|Borough of|County of|"
                    r"District of)?\s*(.+?)\s*(?:\(|\bAct\b|\bOrder\b|$)")


def _prefix_place(P, title):
    m = PREFIX.match(title)
    if not m:
        return None
    words = m.group(1).split()
    for k in range(min(len(words), 6), 0, -1):
        r = P.find("GB", " ".join(words[:k]), phase=1)
        if r and r["phase"] == 1:
            return r
    return None


ALIAS = {r"^Greater Nottingham\b": "City of Nottingham"}   # LGR 'upcoming' names in act titles -> current council


# Single-purpose authorities (Normalizer 2026-10-18): acts promoted by/for such a body are placed under the
# current council(s) where it operates, and the record names the body in `issuing_body` (-> extra_metadata).
BODY_BY_KEY = {"ukla/2013/6": "Humber Bridge Board", "ukla/2002/5": "Milford Haven Port Authority",
               "ukla/2003/1": "London Development Agency"}
SPA = re.compile(r"((?:(?:[A-Z][\w'’.-]*|and|of|upon|on)\s+)*?[A-Z][\w'’.-]*\s+(?:Port Authority|Port Trust|Harbour Board|"
                 r"Harbour Commissioners|Harbour Trust|Bridge Board|Bridge Trust|Conservators|Conservancy|"
                 r"Development Corporation|Development Agency|Passenger Transport Executive|Passenger Transport Authority|"
                 r"Fire Authority|Police Authority|Waste Disposal Authority|Transport Authority|Water Board|Drainage Board))")


def issuing_body(key, title):
    if key in BODY_BY_KEY:
        return BODY_BY_KEY[key]
    if re.search(r"Transport for London", title):
        return "Transport for London" if not re.search(r"London Local Authorities", title) else \
            "London local authorities and Transport for London"
    m = re.search(r"(Port of [A-Z][\w ]+? Authority)", title) or SPA.search(title)
    return re.sub(r"^The\s+", "", m.group(1)).strip() if m else None


def place_for(P: Places, title: str):
    for rx, nm in ALIAS.items():
        if re.search(rx, title):
            r = P.find("GB", nm, phase=1)
            if r:
                return r, "alias:" + nm
    if MULTI.search(title):          # Normalizer 2026-10-17: London-wide acts -> Greater London (wd:Q23306)
        if re.search(r"Hydraulic Power|Company", title, re.I):
            return None, "no_council_in_title"
        r = P.get("wd:Q23306")
        return (r, "greater_london") if r else (None, "multi_place:greater_london")
    m = None
    for par in re.findall(r"\(([^()]{3,90})\)", title):      # "The Traffic Management (Derbyshire County Council) ..."
        mo = re.match(r"^(?:The\s+)?(?:Borough|County|City|District|County Borough)?\s*Council of (?:the\s+)?(.+)$", par.strip())
        if mo:
            r = P.find("GB", mo.group(1), phase=1)
            if r and r["phase"] == 1:
                return r, "title_council"
        if re.search(r"\b(Council|Corporation)\b", par):
            m = COUNCIL.search(par)
            break
    m = m or COUNCIL.search(title)
    if m and "(" in m.group(1):
        m = None
    if not m:
        if NONMUNI.search(title):
            return None, "no_council_in_title"
        r = _prefix_place(P, title)
        if r:
            return r, "title_place_prefix"
        for par in re.findall(r"\(([^()]{3,80})\)", title):   # "... Contraventions (County of Herefordshire) ..."
            par = re.sub(r"\s+(Council|Borough Council|County Council|City Council|District Council)$", "", par.strip())
            par = re.sub(r"^(County|Borough|District|City|Royal Borough|London Borough) of\s+", "", par)
            if " and " in par and not P.find("GB", par, phase=1):
                return None, f"multi_place:{par}"
            r = P.find("GB", par, phase=1)
            if r and r["phase"] == 1:
                return r, "title_parenthetical"
        return None, "no_council_in_title"
    name = re.sub(r"\s*\(.*$", "", m.group(1)).strip()
    f = fold(name)
    if f in AMBIGUOUS or f.replace(" regional", "") in AMBIGUOUS:
        return None, f"ambiguous_successor:{name}"
    for cand in (SUCCESSOR.get(f), name, name.replace(" and ", " & ")):
        if cand:
            r = P.find("GB", cand, phase=1)
            if r:
                return r, ("successor:" + name) if SUCCESSOR.get(f) else "title_council"
    dup = [r["place_id"] for r in P.by_name.get(("GB", fold(name)), []) if r["phase"] == 1]
    if len(dup) > 1:
        return None, f"ambiguous_duplicate_places:{name}:{'|'.join(dup)}"
    return None, f"council_not_in_candidates:{name}"


def feed(ps, url):
    r = ps.get(url)
    root = etree.fromstring(r.content)
    out = []
    for e in root.findall("a:entry", NS):
        out.append({"id": e.findtext("a:id", namespaces=NS), "title": (e.findtext("a:title", namespaces=NS) or "").strip(),
                    "updated": e.findtext("a:updated", namespaces=NS),
                    "xml": [l.get("href") for l in e.findall("a:link", NS) if (l.get("type") or "").endswith("xml")
                            and l.get("href", "").endswith("/data.xml") and "/welsh/" not in l.get("href", "")]})
    more = root.findtext("{http://www.legislation.gov.uk/namespaces/legislation}morePages")
    return out, int(more or 0)


def meta(raw: bytes):
    root = etree.fromstring(raw)
    g = lambda xp: (str(root.xpath(xp, namespaces=NS)) or None)  # noqa: E731  (string() xpath -> str)
    return {"made": g("string(//ukm:Made/@Date)") or None, "enacted": g("string(//ukm:EnactmentDate/@Date)") or None,
            "minor_type": g("string(//ukm:DocumentMinorType/@Value)") or None,
            "status": g("string(//ukm:DocumentStatus/@Value)") or None,
            "subject": [s for s in root.xpath("//ukm:Subject/@Value | //ukm:SIheading/text()", namespaces=NS)][:6]}


class Run:
    def __init__(self):
        self.ps = PoliteSession(log, min_interval=5.0)
        self.st, self.P, self.codes = State(), Places(), place_codes()
        self.w = {}
        self.n = {"staged": 0, "unmatched": 0, "skipped": 0, "no_text": 0}

    def stage(self, kind, it, place, how):
        key = re.sub(r"^.*/id/", "", it["id"])          # ukla/2012/2
        typ, rest = key.split("/", 1)
        url = (it["xml"] or [f"{BASE}/{key}/{'enacted' if typ in ('ukla',) else 'made'}/data.xml"])[0]
        url = url.replace("http://", "https://", 1)
        raw = self.ps.get(url).content
        title, text, _secs, m0 = ipfs_uk.parse_clml(raw.decode("utf-8", "replace"), key, url, None)
        md = meta(raw)
        title = it["title"] or title
        if len(text) < 300:
            self.st.mark_item(key, kind, "no_digitised_text", place["place_id"] if place else None)
            self.n["no_text"] += 1
            return
        did = f"uk_{typ}:{rest}"
        date = md["enacted"] or md["made"]
        rec = {"place_id": place["place_id"], "country_code": "GB", "doc_id": did, "source_platform": "legislation_gov_uk",
               "source_url": f"{BASE}/{key}/{'enacted' if typ == 'ukla' else 'made'}", "doc_type":
                   "statute" if typ == "ukla" else "regulation", "language": "en", "title_native": title,
               "number": f"{rest.split('/')[0]} c. {rest.split('/')[1]}" if typ == "ukla" else f"{typ.upper()} {rest}",
               "adopted_date": date, "published_date": None, "effective_date": None, "in_force": None,
               "consolidated": False, "content_format": "xml", "text": text, "retrieved_at": utcnow(),
               "place_name": place["place_name"], "qid": place["qid"], "iso_3166_2": place.get("iso_3166_2") or None,
               "admin_level": place["admin_level"], "platform": "legislation_gov_uk", "platform_place_id": None,
               "source_official": True, "source_org": "The National Archives (legislation.gov.uk)",
               "license_note": "Open Government Licence v3.0", "act_kind": "UK Local Act" if typ == "ukla" else
               "local statutory instrument", "place_match": how, "clml_meta": md, "lane": LANE,
               "place_codes": self.codes.get(place["place_id"]) or None}
        body = issuing_body(key, title)
        if body:
            rec["issuing_body"] = body
            rec["issuing_body_kind"] = "single_purpose_authority" if body != "London local authorities and Transport for London" \
                else "joint_promoters"
        w = self.w.get(place["place_id"])
        if not w:
            w = self.w[place["place_id"]] = StagedWriter(STAGE, "GB", place["place_id"], batch_prefix="ukie-leg", chunk=200)
        err = w.add(rec)
        if err:
            log.warning("invalid %s %s", key, err)
            self.st.mark_item(key, kind, "invalid", place["place_id"], err)
            return
        self.st.mark_item(key, kind, "staged", place["place_id"], {"how": how})
        self.n["staged"] += 1

    def restage(self, key, place_ids, how):
        """Stage one act (e.g. 'ukla/1994/15') under explicit current place(s), ignoring earlier item state."""
        typ = key.split("/")[0]
        it = {"id": f"{BASE}/id/{key}", "title": "", "xml": []}
        raw = self.ps.get(f"{BASE}/{key}/{'enacted' if typ == 'ukla' else 'made'}/data.xml").content
        it["title"] = (etree.fromstring(raw).xpath("string(//*[local-name()='title'][1])") or "").strip()
        for pid in place_ids:
            self.stage("ukla" if typ == "ukla" else "lsi", it, self.P.get(pid), how)
        self.st.mark_item(key, "ukla" if typ == "ukla" else "lsi", "staged", ",".join(place_ids), {"how": how})

    def handle(self, kind, it, require_council=True):
        key = re.sub(r"^.*/id/", "", it["id"])
        if self.st.item(key):
            return
        guard()
        place, how = place_for(self.P, it["title"])
        if place is None:
            if how == "no_council_in_title" and require_council:
                self.st.mark_item(key, kind, "non_municipal", None, {"title": it["title"]})
                self.n["skipped"] += 1
                return
            append_jsonl(UNMATCHED, {"key": key, "kind": kind, "title": it["title"], "reason": how, "at": utcnow()})
            self.st.mark_item(key, kind, "unmatched", None, {"title": it["title"], "reason": how})
            self.n["unmatched"] += 1
            return
        try:
            self.stage(kind, it, place, how)
        except StopRun:
            raise
        except Exception as e:  # noqa: BLE001
            log.info("fail %s: %s", key, str(e)[:150])
            self.st.mark_item(key, kind, "error", place["place_id"], str(e)[:200])

    def flush(self):
        files = []
        for w in self.w.values():
            w.flush()
            files += w.written
        self.w = {}
        return files


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["ukla", "lsi", "status"])
    ap.add_argument("--pages", default="1-1")
    ap.add_argument("--ids", default="")
    ap.add_argument("--queries", default="")
    ap.add_argument("--types", default="uksi,ssi,wsi")
    ap.add_argument("--max", type=int, default=100000)
    a = ap.parse_args()
    if a.cmd == "status":
        print(json.dumps(State().summary()["items"], indent=1))
        return
    R = Run()
    try:
        if a.cmd == "ukla":
            for ident in [i for i in a.ids.split(",") if i]:
                it = {"id": f"{BASE}/id/ukla/{ident}", "title": "", "xml": []}
                # title from the act's own CLML metadata
                raw = R.ps.get(f"{BASE}/ukla/{ident}/enacted/data.xml").content
                it["title"] = (etree.fromstring(raw).xpath("string(//*[local-name()='title'][1])") or "").strip()
                R.handle("ukla", it, require_council=False)
            lo, hi = (int(x) for x in a.pages.split("-"))
            p = lo
            while p <= hi:
                pk = f"page:ukla:{p}"
                if R.st.item(pk) == "done" and p > 3:      # newest pages are always re-read (new acts)
                    p += 1
                    continue
                items, more = feed(R.ps, f"{BASE}/ukla/data.feed?page={p}")
                for it in items:
                    R.handle("ukla", it)
                R.st.mark_item(pk, "feedpage", "done", None, {"n": len(items), "more": more})
                if p % 10 == 0:
                    R.flush()
                    R.st.summary()
                log.info("ukla page %d: %s (more=%d)", p, R.n, more)
                if not items or more == 0:
                    break
                p += 1
        else:
            done = 0
            for q in [q for q in a.queries.split(",") if q]:
                for typ in a.types.split(","):
                    page = 1
                    while done < a.max:
                        pk = f"page:lsi:{typ}:{q}:{page}"
                        if R.st.item(pk) == "done" and page > 1:
                            page += 1
                            continue
                        try:
                            items, more = feed(R.ps, f"{BASE}/{typ}/data.feed?title={q}&page={page}")
                        except Exception as e:  # noqa: BLE001
                            log.info("lsi feed %s %s p%d: %s", typ, q, page, str(e)[:120])
                            break
                        for it in items:
                            before = R.n["staged"]
                            R.handle("lsi", it)
                            done += R.n["staged"] - before
                        R.st.mark_item(pk, "feedpage", "done", None, {"n": len(items), "more": more})
                        R.flush()
                        R.st.summary()
                        log.info("lsi %s %s p%d: %s (more=%d)", typ, q, page, R.n, more)
                        if not items or more == 0:
                            break
                        page += 1
    finally:
        files = R.flush()
        log.info("flushed %d files; %s", len(files), R.n)
        print(json.dumps({"files": [Path(f).name for f in files], **R.n}))
        R.st.summary()


if __name__ == "__main__":
    main()
