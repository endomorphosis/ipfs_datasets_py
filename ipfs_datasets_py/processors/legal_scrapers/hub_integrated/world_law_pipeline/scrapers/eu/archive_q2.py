#!/usr/bin/env python3
"""Second-wave archive targets (lane eu, Wayback only, shared ArchiveFetcher + box-wide limiter), queued after the
AT/PL archive jobs of archive_jobs.py.

  cz   sbirkapp.gov.cz  (network_blocked: TCP timeout)  Sbírka právních předpisů ÚSC - /detail/<SPP>/text (PDF/ODT) +
       /detail/<SPP> metadata page. Only acts with an archived /text capture (~2,510 of 13,261 archived detail ids).
  be   www.ejustice.just.fgov.be/eli/ (robots_disallowed live) - regional acts (Flemish/Walloon/Brussels governments and
       parliaments) from archived Justel pages, tagged source_policy=archived_robots_disallowed. Never crawled live.
  lt   www.e-tar.lt (network_blocked: Cloudflare 403 incl. robots.txt) - municipal council decisions (savivaldybės
       tarybos sprendimai) from archived /rs/legalact/<id>/ text (DOCX/ODT/PDF fallback). Queued after czfirst.
  (hu  or.njt.hu: archived ELI pages carry title/metadata only - the act body is loaded by JavaScript - and NJT states
       "minden jogot fenntart"; not built, see README.)

Usage: python3 archive_q2.py discover|fetch|all|status <cz|be|lt> [--limit N] [--test N]
       python3 archive_q2.py queue      # waits for archive_jobs.py at/pl to exit, then runs cz, then be
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
import io
import json
import os
import random
import re
import subprocess
import sys
import time
import unicodedata
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
sys.path.insert(0, str(HERE))
os.environ.setdefault("ARCHIVE_LANE", "eu")
import archive_jobs as AJ  # noqa: E402  (helpers: pdf_to_text, html_to_text, atomic_write, robots_for, utcnow)
from archive import ArchiveFetcher, StagedWriter, provenance_fields  # noqa: E402
from archive.core import Capture  # noqa: E402
import schema  # noqa: E402

STAGE, STATE, UNM, CAND = AJ.STAGE, AJ.STATE, AJ.UNM, AJ.CAND
log = AJ.log
BATCH = 50
FLUSH_SECS = 900   # time-based flush (see archive_jobs.py)


def fold(s):
    s = unicodedata.normalize("NFKD", s or "")
    return " ".join("".join(c for c in s if not unicodedata.combining(c)).lower().replace("-", " ").split())


def strip(t):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"<(script|style).*?</\1>", " ", t, flags=re.S))).strip()


def odt_to_text(b: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(b)) as z:
        names = z.namelist()
        x = z.read("content.xml" if "content.xml" in names else "word/document.xml").decode("utf-8", "replace")
    x = re.sub(r"</(text:p|text:h|w:p)>", "\n", x)
    x = re.sub(r"<text:tab/>", "\t", x)
    x = re.sub(r"<[^>]+>", "", x)
    import html
    return re.sub(r"\n{3,}", "\n\n", html.unescape(x)).strip()


def d8(s):
    m = re.match(r"(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{4})", s or "")
    return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else None


# ------------------------------------------------------------------ CZ
class CZPlaces:
    def __init__(self):
        self.by = defaultdict(list)
        for r in csv.DictReader(CAND.open(encoding="utf-8")):
            if r["country_code"] == "CZ" and r["admin_level"] == "municipality":
                self.by[fold(r["place_name"])].append(r)
        self.by["praha"] = self.by.get("prague", [])

    def resolve(self, publisher: str) -> dict:
        res = dict(place_id=None, qid=None, place_name=None, match=None, level="municipality")
        p = publisher or ""
        if re.match(r"(Kraj|.*\bkraj\b)", p, re.I) and not re.match(r"(Obec|Město|Městys)", p):
            res.update(match="regional_publisher", level="region")
            return res
        base = re.sub(r"^(Statutární město|Hlavní město|Město|Městys|Obec|Městská část|Městský obvod)\s+", "", p.strip())
        cs = self.by.get(fold(base), [])
        if len(cs) == 1:
            c = cs[0]
            res.update(place_id=c["place_id"], qid=c["qid"], place_name=c["place_name"], match="publisher_name->candidate(unique)")
        else:
            res["match"] = "ambiguous_name" if cs else "publisher_not_in_candidate"
            res["place_name"] = base
        return res


def cz_discover(fx):
    caps = AJ._wb_list(fx, "sbirkapp.gov.cz/", "prefix", collapse="urlkey")   # round 3: transient -> ArchiveDeferred
    ids = defaultdict(lambda: {"detail": [], "text": []})
    for c in caps:
        m = re.search(r"sbirkapp\.gov\.cz/detail/(SPP[A-Z0-9]+)(/text)?/?$", c.original_url.split("?")[0])
        if m:
            ids[m.group(1)]["text" if m.group(2) else "detail"].append(c.original_url)
    d = STATE / "cz"
    d.mkdir(parents=True, exist_ok=True)
    n = 0
    with (d / "candidates.jsonl").open("w", encoding="utf-8") as f:
        for k, v in sorted(ids.items()):
            if v["text"]:
                f.write(json.dumps({"key": k, "detail": sorted(set(v["detail"])) or [f"https://sbirkapp.gov.cz/detail/{k}"],
                                    "text": sorted(set(v["text"]))}) + "\n")
                n += 1
    info = {"detail_ids": len(ids), "with_text": n, "at": AJ.utcnow()}
    (d / "discover.json").write_text(json.dumps(info))
    return info


def cz_one(fx, cand, pm):
    tcaps = AJ.lookup_caps(fx, cand["text"])
    tcaps.sort(key=lambda c: c.timestamp, reverse=True)
    dt = AJ.fbest(fx, tcaps, max_tries=3, validator=lambda d: d.body[:4] == b"%PDF" or d.body[:2] == b"PK")
    if not dt:
        return None, "no_good_capture"
    text = AJ.pdf_to_text(dt.body) if dt.body[:4] == b"%PDF" else odt_to_text(dt.body)
    if len(text) < 80:
        return None, "empty_text"
    meta = {}
    n_def = AJ.ITEM_DEF[0]
    dcaps = AJ.lookup_caps(fx, cand["detail"])
    dcaps.sort(key=lambda c: c.timestamp, reverse=True)
    dd = AJ.fbest(fx, dcaps, max_tries=2, validator=lambda d: b"Publikuj" in d.body)
    if dd is None and AJ.ITEM_DEF[0] > n_def:
        return None, AJ.DEFERRED      # text found but the metadata page needs Wayback: wait (publisher -> place)
    if dd:
        h = dd.text()
        s = strip(h)
        t1 = re.search(r"<h1>(.*?)</h1>", h, re.S)
        pub = re.search(r"<h4>Publikující</h4>\s*<p>\s*<a[^>]*>(.*?)</a>", h, re.S)
        g = lambda rx: (re.search(rx, s).group(1).strip() if re.search(rx, s) else None)  # noqa: E731
        meta = {"title": strip(t1.group(1)) if t1 else None, "publisher": strip(pub.group(1)) if pub else g(r"Publikující:? (.+?) (?:ID DS|IČO|Datum)"),
                "ico": g(r"IČO: (\d+)"), "kind": g(r"Druh právního předpisu (.+?) Číslo právního předpisu"),
                "number": g(r"Číslo právního předpisu (\S+)"), "published": d8(g(r"zveřejnění ve sbírce (\d{2}\.\d{2}\.\d{4})")),
                "effective": d8(g(r"Datum nabytí účinnosti (\d{2}\.\d{2}\.\d{4})")),
                "issued": d8(g(r"Datum vydání (\d{2}\.\d{2}\.\d{4})")), "validity": g(r"Platnost (\S+)")}
    pl = pm.resolve(meta.get("publisher"))
    if pl["level"] == "region":
        return None, "regional_publisher"
    kind = (meta.get("kind") or "").lower()
    rec = {
        "place_id": pl["place_id"], "country_code": "CZ", "doc_id": f"cz_sbirkapp:{cand['key']}",
        "source_platform": "cz_sbirkapp", "source_url": f"https://sbirkapp.gov.cz/detail/{cand['key']}",
        "doc_type": "ordinance" if "vyhláška" in kind else "regulation" if "nařízení" in kind else "gazette_act",
        "language": "cs", "title_native": " ".join(x for x in (meta.get("kind"), meta.get("number"), meta.get("title")) if x) or cand["key"],
        "number": meta.get("number") or cand["key"], "adopted_date": meta.get("issued"), "published_date": meta.get("published"),
        "effective_date": meta.get("effective"), "in_force": (meta.get("validity") == "Platné") if meta.get("validity") else None,
        "consolidated": False, "content_format": "pdf_text" if dt.body[:4] == b"%PDF" else "docx_text", "text": text,
        "retrieved_at": AJ.utcnow(), "place_name": pl["place_name"], "qid": pl["qid"], "iso_3166_2": None,
        "admin_level": "municipality", "platform": "sbirkapp", "platform_place_id": meta.get("ico"),
        "issuing_body_name": meta.get("publisher"), "issuing_body_ico": meta.get("ico"), "level": pl["level"],
        "place_match": pl["match"], "act_kind": meta.get("kind"), "metadata_capture": bool(dd),
        "rights": "official act; not protected by copyright (§ 3 zák. 121/2000 Sb.)",
        **provenance_fields(dt),
    }
    return rec, "ok"


# ------------------------------------------------------------------ BE (regional acts, robots-disallowed host)
BE_REG = [(re.compile(r"Vlaamse (Regering|Overheid|Gemeenschap|Parlement)|VLAAMSE OVERHEID|Région flamande", re.I), "wd:Q9337", "Flemish Region", "BE-VLG"),
          (re.compile(r"Région wallonne|SERVICE PUBLIC DE WALLONIE|Gouvernement wallon|Waals Gewest|Parlement wallon", re.I), "wd:Q231", "Wallonia", "BE-WAL"),
          (re.compile(r"Bruxelles-Capitale|Brussels Hoofdstedelijk|BRUSSELS HOOFDSTEDELIJK|REGION DE BRUXELLES", re.I), "wd:Q240", "Brussels-Capital Region", "BE-BRU")]


def be_discover(fx):
    caps = AJ._wb_list(fx, "www.ejustice.just.fgov.be/eli/", "prefix", collapse="urlkey")
    acts = defaultdict(list)
    for c in caps:
        m = re.search(r"/eli/(decret|decreet|ordonnance|ordonnantie|arrete|besluit)/(\d{4})/(\d{2})/(\d{2})/(\d{10})/(justel|moniteur|staatsblad)$",
                      c.original_url.split("?")[0])
        if m:
            acts[m.group(5)].append(c.original_url)
    d = STATE / "be"
    d.mkdir(parents=True, exist_ok=True)
    with (d / "candidates.jsonl").open("w", encoding="utf-8") as f:
        for k, us in sorted(acts.items()):
            f.write(json.dumps({"key": k, "urls": sorted(set(us), key=lambda u: (not u.endswith("justel"), u))}) + "\n")
    info = {"captures": len(caps), "acts": len(acts), "at": AJ.utcnow(),
            "policy": "archived_robots_disallowed (live robots.txt disallows /eli/, /cgi_loi/ ...)"}
    (d / "discover.json").write_text(json.dumps(info))
    return info


def be_one(fx, cand):
    caps = AJ.lookup_caps(fx, cand["urls"][:3])
    caps.sort(key=lambda c: (c.original_url.endswith("justel"), c.timestamp), reverse=True)
    d = AJ.fbest(fx, caps, max_tries=3, validator=lambda d: len(d.body) > 2000)
    if not d:
        return None, "no_good_capture"
    text = AJ.html_to_text(d.body)
    head = text[:4000]
    reg = next(((pid, nm, iso) for rx, pid, nm, iso in BE_REG if rx.search(head)), None)
    if not reg:
        return None, "not_regional"
    pid, nm, iso = reg
    m = re.search(r"/eli/(\w+)/(\d{4})/(\d{2})/(\d{2})/", d.original_url)
    title = next((ln.strip() for ln in text.splitlines() if re.match(r"\s*\d{1,2} \w+ \d{4}\.?\s*[-–]", ln)), None)
    lang = "nl" if re.search(r"/(decreet|ordonnantie|besluit)/", d.original_url) else "fr"
    rec = {
        "place_id": pid, "country_code": "BE", "doc_id": f"be_justel:{cand['key']}:{lang}", "source_platform": "be_justel",
        "source_url": d.original_url, "doc_type": {"decret": "statute", "decreet": "statute", "ordonnance": "statute",
                                                    "ordonnantie": "statute"}.get(m.group(1) if m else "", "regulation"),
        "act_kind": m.group(1) if m else None,
        "language": lang, "title_native": (title or cand["key"])[:1000], "number": cand["key"],
        "adopted_date": f"{m.group(2)}-{m.group(3)}-{m.group(4)}" if m else None, "published_date": None,
        "effective_date": None, "in_force": None, "consolidated": d.original_url.endswith("justel"),
        "content_format": "html", "text": text, "retrieved_at": AJ.utcnow(), "place_name": nm, "qid": pid.split(":")[1],
        "iso_3166_2": iso, "admin_level": "region", "platform": "ejustice", "platform_place_id": None,
        "level": "region", "place_match": "issuer_text->region", "numac": cand["key"],
        "rights": "official act; not protected by copyright (art. XI.172 CDE)",
        **provenance_fields(d, source_policy="archived_robots_disallowed",
                            robots_basis="live robots.txt of www.ejustice.just.fgov.be disallows /eli/ for User-agent: *"),
    }
    return rec, "ok"



# ------------------------------------------------------------------ LT (e-TAR municipal council decisions, network-blocked host)
# www.e-tar.lt answers a Cloudflare 403 challenge to the box (robots.txt included), so it is never crawled live.
# Archived act text lives at /rs/legalact/<id>/ (the portal page's iframe) plus /format/MSO2010_DOCX|OO3_ODT|ISO_PDF/.
LT_GEN = {  # genitive issuer stem (as printed "<STEM> SAVIVALDYBĖS TARYBA") -> candidate place_id
    "vilniaus rajono": "wd:Q118903", "kauno rajono": "wd:Q1351722", "klaipedos rajono": "wd:Q141132",
    "marijampoles": "wd:Q1931377", "mazeikiu rajono": "wd:Q313132", "kedainiu rajono": "wd:Q46786",
    "jonavos rajono": "wd:Q1351768", "siauliu rajono": "wd:Q1417346", "telsiu rajono": "wd:Q588916",
    "silutes rajono": "wd:Q282098", "taurages rajono": "wd:Q2071640", "utenos rajono": "wd:Q2089798",
    "kretingos rajono": "wd:Q156560", "panevezio rajono": "wd:Q1351758", "vilkaviskio rajono": "wd:Q2021318",
    "radviliskio rajono": "wd:Q1755961", "ukmerges rajono": "wd:Q68929", "traku rajono": "wd:Q1987743",
    "plunges rajono": "wd:Q404943", "raseiniu rajono": "wd:Q2069355", "salcininku rajono": "wd:Q1799182",
    "kaisiadoriu rajono": "wd:Q2069320", "rokiskio rajono": "wd:Q766969", "sakiu rajono": "wd:Q2021307",
    "alytaus rajono": "wd:Q769940", "prienu rajono": "wd:Q47090", "kelmes rajono": "wd:Q1387044",
    "jurbarko rajono": "wd:Q2089815", "elektrenu": "wd:Q2089777", "anyksciu rajono": "wd:Q2089772",
    "birzu rajono": "wd:Q763504", "pasvalio rajono": "wd:Q1461920", "svencioniu rajono": "wd:Q1813849",
    "silales rajono": "wd:Q677400", "joniskio rajono": "wd:Q610133", "varenos rajono": "wd:Q1351747",
    "druskininku": "wd:Q669649", "visagino": "wd:Q2558824", "akmenes rajono": "wd:Q1023041",
    "pakruojo rajono": "wd:Q1657116", "lazdiju rajono": "wd:Q2069342", "moletu rajono": "wd:Q2089785",
    "kupiskio rajono": "wd:Q2089791", "skuodo rajono": "wd:Q219115", "sirvintu rajono": "wd:Q58882",
    "zarasu rajono": "wd:Q664415", "ignalinos rajono": "wd:Q2069330", "kazlu rudos": "wd:Q1461972",
    "kalvarijos": "wd:Q1461987", "rietavo": "wd:Q712011", "pagegiu": "wd:Q2283574", "birstono": "wd:Q2015893",
    "neringos": "wd:Q9305847",
}
LT_MON = {m: i for i, m in enumerate(("sausio", "vasario", "kovo", "balandzio", "geguzes", "birzelio", "liepos",
                                      "rugpjucio", "rugsejo", "spalio", "lapkricio", "gruodzio"), 1)}
LT_HDR = re.compile(r"((?:[A-ZĄČĘĖĮŠŲŪŽ\-]+ ){0,3}[A-ZĄČĘĖĮŠŲŪŽ\-]+) SAVIVALDYB[ĖE]S TARYBA (?:SPRENDIMAS|POSĖDŽIO)\b")


class LTPlaces:
    def __init__(self):
        self.cand = {}
        for r in csv.DictReader(CAND.open(encoding="utf-8")):
            if r["country_code"] == "LT":
                self.cand[r["place_id"]] = r

    def resolve(self, stem: str) -> dict:
        w = fold(stem).replace(" r ", " rajono ").split()
        city = "miesto" in w
        for n in (2, 1, 3):  # "VILNIAUS RAJONO", "KALVARIJOS", "KAZLŲ RŪDOS"; extra leading words are ignored
            if len(w) >= n:
                pid = LT_GEN.get(" ".join(w[-n:]))
                if pid and pid in self.cand and not city:
                    c = self.cand[pid]
                    return dict(place_id=pid, qid=c["qid"], place_name=c["place_name"], match="issuer_genitive->candidate",
                                stem=" ".join(stem.split()[-n:]))
        keep = stem.split()[-2:] if city or "RAJONO" in stem.upper() else stem.split()[-1:]
        return dict(place_id=None, qid=None, place_name=" ".join(keep).title() + " savivaldybė", stem=" ".join(keep),
                    match="city_municipality_not_in_candidate" if city else "issuer_not_in_candidate")


def lt_discover(fx):
    ids = defaultdict(lambda: {"text": [], "docx": [], "odt": [], "pdf": []})
    n = 0
    for pre in ("www.e-tar.lt/rs/legalact/", "e-tar.lt/rs/legalact/"):
        caps = AJ._wb_list(fx, pre, "prefix", collapse="urlkey")
        n += len(caps)
        for c in caps:
            m = re.search(r"/rs/legalact/([0-9a-f]{32}|TAR\.[0-9A-F]{12})/(format/(MSO2010_DOCX|OO3_ODT|ISO_PDF)/?)?$",
                          c.original_url.split("?")[0])
            if m:
                kind = {"MSO2010_DOCX": "docx", "OO3_ODT": "odt", "ISO_PDF": "pdf"}.get(m.group(3) or "", "text")
                ids[m.group(1)][kind].append(c.original_url)
    d = STATE / "lt"
    d.mkdir(parents=True, exist_ok=True)
    with (d / "candidates.jsonl").open("w", encoding="utf-8") as f:
        for k, v in sorted(ids.items()):
            f.write(json.dumps({"key": k, **{x: sorted(set(u)) for x, u in v.items() if u}}) + "\n")
    info = {"captures": n, "acts": len(ids), "at": AJ.utcnow(),
            "policy": "network_blocked live (Cloudflare 403 on www.e-tar.lt incl. robots.txt); Wayback only"}
    (d / "discover.json").write_text(json.dumps(info))
    return info


def lt_text(fx, cand):
    for kind in ("text", "docx", "odt", "pdf"):
        caps = AJ.lookup_caps(fx, cand.get(kind, [])[:2])
        if not caps:
            continue
        caps.sort(key=lambda c: c.timestamp, reverse=True)
        if kind == "text":
            d = AJ.fbest(fx, caps, max_tries=2, validator=lambda d: len(d.body) > 600 and b"<" in d.body[:2000])
            t = AJ.html_to_text(d.body) if d else ""
        elif kind == "pdf":
            d = AJ.fbest(fx, caps, max_tries=2, validator=lambda d: d.body[:4] == b"%PDF")
            t = AJ.pdf_to_text(d.body) if d else ""
        else:
            d = AJ.fbest(fx, caps, max_tries=2, validator=lambda d: d.body[:2] == b"PK")
            t = odt_to_text(d.body) if d else ""
        if d and len(t.strip()) >= 80:
            return d, t, {"text": "html", "docx": "docx_text", "odt": "docx_text", "pdf": "pdf_text"}[kind]
        # a short or non-municipal body: no need to try other formats unless nothing usable came back
        if d and len(t.strip()) >= 30:
            return d, t, "html" if kind == "text" else "docx_text"
    return None, "", None


def lt_one(fx, cand, pm):
    d, text, fmt = lt_text(fx, cand)
    if not d:
        return None, "no_good_capture"
    head = re.sub(r"\s+", " ", text[:600]).strip().upper()
    m = LT_HDR.search(head[:400])
    if not m:
        return None, "not_municipal_council"
    if len(text) < 80:
        return None, "empty_text"
    pl = pm.resolve(m.group(1))
    stem = pl["stem"]
    after = re.sub(r"\s+", " ", text[:1500]).strip()
    after = after[len(head[:m.end()]):] if len(after) >= m.end() else after
    fh = fold(after)
    dm = re.search(r"(\d{4}) m\. (\w+) (\d{1,2}) d\.", fh)
    adopted = f"{dm.group(1)}-{LT_MON[dm.group(2)]:02d}-{int(dm.group(3)):02d}" if dm and dm.group(2) in LT_MON else None
    nm = re.search(r"\bNr\.\s*([A-Za-z0-9ĄČĘĖĮŠŲŪŽąčęėįšųūž\-/.]+)", after)
    tm = re.search(r"^\s*(.*?)\s+\d{4}\s*m\.", after, re.S)
    title = (tm.group(1) if tm else after[:200]).strip()
    rec = {
        "place_id": pl["place_id"], "country_code": "LT", "doc_id": f"lt_etar:{cand['key']}", "source_platform": "lt_etar",
        "source_url": f"https://www.e-tar.lt/portal/lt/legalAct/{cand['key']}", "doc_type": "decision",
        "language": "lt", "title_native": (title or cand["key"])[:1000], "number": nm.group(1).rstrip(".") if nm else cand["key"],
        "adopted_date": adopted, "published_date": None, "effective_date": None, "in_force": None, "consolidated": False,
        "content_format": fmt, "text": text, "retrieved_at": AJ.utcnow(), "place_name": pl["place_name"], "qid": pl["qid"],
        "iso_3166_2": None, "admin_level": "municipality", "platform": "e-tar", "platform_place_id": None,
        "issuing_body_name": f"{stem.strip().title()} savivaldybės taryba", "level": "municipality", "place_match": pl["match"],
        "act_kind": "Savivaldybės tarybos sprendimas", "etar_id": cand["key"],
        "rights": "official act; not an object of copyright (Lietuvos autorių teisių ir gretutinių teisių įstatymas, 5 str.)",
        **provenance_fields(d),
    }
    return rec, "ok"


# ------------------------------------------------------------------ driver
def new_fx():
    """Common Crawl on (the breaker's fallback while Wayback is down) + Wayback via the shared v4 limiter/breaker."""
    return AJ.new_fx()          # EU Wayback policy (common/eu_wayback.py, 2026-10-18)


def fetch(target, limit, test, skip=frozenset()):
    """Returns {"todo", "deferred": [keys], "stopped"}. Deferred items are neither done nor failed."""
    fx = new_fx()
    deferred = []
    import signal
    signal.signal(signal.SIGTERM, AJ._on_term)
    sfx = "_test" if test else ""
    d = STATE / target
    done_p = d / f"done{sfx}.txt"
    done = AJ.load_done(done_p)
    todo = [ln for ln in (d / "candidates.jsonl").open(encoding="utf-8")
            if json.loads(ln)["key"] not in done and json.loads(ln)["key"] not in skip]
    if test:
        todo = random.Random(5).sample(todo, min(test, len(todo)))
    if limit:
        todo = todo[:limit]
    pm = CZPlaces() if target == "cz" else LTPlaces() if target == "lt" else None
    rb = None
    if target == "hu":                    # hu_njt.py (2026-10-18): or.njt.hu local decrees, archived robots.txt
        import hu_njt
        pm = hu_njt.HUPlaces()
        try:
            rb = AJ.robots_for(fx, "or.njt.hu") if todo else None
        except Exception as e:  # noqa: BLE001  ArchiveTransient/Deferred: robots unknown -> defer the whole pass
            log.info("hu: archived robots.txt deferred (%s); pass deferred", str(e)[:120])
            return {"todo": len(todo), "deferred": [], "stopped": False, "paused_until": AJ.defer_info(e)[0],
                    "deferred_nb": {}}
        rb = rb if rb and rb[0] is not None else None
    cc = target.upper()
    log.info("%s fetch: todo=%d done=%d", target, len(todo), len(done))
    rows, keys, why = [], [], Counter()
    stage = (STAGE / ("_test_hu" if target == "hu" else "_test_archive")) if test else STAGE
    tf = time.time()
    paused = 0.0     # 2026-10-18 v3: an item deferred on Wayback (ArchiveDeferred) -> flush, return, resume after not_before
    dnb = {}         # key -> not_before of deferred items (runner skips them until then)
    with done_p.open("a") as df, (d / f"failed{sfx}.jsonl").open("a") as ff:
        for i, ln in enumerate(todo, 1):
            if AJ.STOP[0] or paused:
                break
            cand = json.loads(ln)
            AJ.item_reset()
            try:
                rec, w = (cz_one(fx, cand, pm) if target == "cz" else lt_one(fx, cand, pm) if target == "lt"
                          else hu_njt.hu_one(fx, cand, pm, rb) if target == "hu" else be_one(fx, cand))
                if w == "no_good_capture" and AJ.ITEM_DEFS:
                    raise AJ.item_deferral()       # lookups were throttled: not a genuine miss
                if w == "no_good_capture" and AJ.ITEM_DEF[0]:
                    w = AJ.DEFERRED
                why[w] += 1
                if w == AJ.DEFERRED:       # Wayback breaker open: not done, not failed -> later pass
                    deferred.append(cand["key"])
                    AJ.defer_log(target, cand["key"], f"wayback breaker open ({AJ.ITEM_DEF[0]} skipped)")
                else:
                    if rec:
                        rows.append(rec)
                    keys.append(cand["key"])
                    if w == "no_good_capture":
                        ff.write(json.dumps({"key": cand["key"], "why": w, "at": AJ.utcnow()}) + "\n")
                        ff.flush()
            except Exception as e:  # noqa: BLE001  (not marked done -> retried on resume)
                from archive.core import ArchiveTransient
                if isinstance(e, ArchiveTransient) and AJ.unknown_capped(target, cand["key"], e):
                    why["unknown_error_cap"] += 1          # round 5: done-with-gaps after N unknown_error requeues
                    keys.append(cand["key"])
                    ff.write(json.dumps({"key": cand["key"], "why": "unknown_error_cap", "error": str(e)[:300],
                                         "at": AJ.utcnow()}) + "\n")
                    ff.flush()
                elif isinstance(e, ArchiveTransient) or AJ.ITEM_DEF[0]:
                    nb, wbk = AJ.defer_info(e)
                    why[AJ.DEFERRED] += 1
                    deferred.append(cand["key"])
                    dnb[cand["key"]] = nb
                    AJ.defer_log(target, cand["key"], f"until {time.strftime('%H:%M:%S', time.localtime(nb))} {str(e)[:110]}")
                    if wbk:
                        paused = nb
                        log.info("%s: Wayback deferred until %s; pausing target at %d/%d", target,
                                 time.strftime("%H:%M:%S %Z", time.localtime(nb)), i, len(todo))
                else:
                    why["error"] += 1
                    log.warning("%s %s: %s", target, cand["key"], str(e)[:200])
                    ff.write(json.dumps({"key": cand["key"], "error": str(e)[:300], "at": AJ.utcnow()}) + "\n")
                    ff.flush()
            if not keys and why and time.time() - tf >= FLUSH_SECS:
                tf = time.time()
                log.info("%s progress %s | %d/%d", target, dict(why), i, len(todo))
                why = Counter()
            if keys and (len(keys) >= BATCH or i == len(todo) or AJ.STOP[0] or time.time() - tf >= FLUSH_SECS):
                tf = time.time()
                tag = f"{ {'cz': 'czspp', 'lt': 'ltetar', 'hu': 'hunjt'}.get(target, 'bejustel') }_archive_"
                by, unm = defaultdict(list), []
                for r in rows:
                    (by[r["place_id"]] if r["place_id"] else unm).append(r)
                ok = 0
                for pid, rs in by.items():
                    w = StagedWriter(stage, cc, pid, batch_prefix=tag, chunk=10 ** 9)
                    for r in rs:
                        err = w.add(r)
                        if err:
                            log.warning("invalid %s: %s", r["doc_id"], err)
                        else:
                            ok += 1
                    w.flush()
                if unm:
                    u = (stage / "_unmatched") if test else UNM
                    u.mkdir(parents=True, exist_ok=True)
                    AJ.atomic_write(u / f"{target}_archive_unmatched_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}p0001.jsonl", unm)
                for k in keys:
                    df.write(k + "\n")
                df.flush()
                os.fsync(df.fileno())
                log.info("%s batch matched=%d unmatched=%d %s | %d/%d", target, ok, len(unm), dict(why), i, len(todo))
                rows, keys, why = [], [], Counter()
        if keys:      # SIGTERM / early stop: flush what is buffered
            AJ.STOP[0] = AJ.STOP[0]
    if keys:
        _flush_q2(target, test, rows, keys, why, stage, cc, len(todo))
    stopped = AJ.STOP[0]
    log.info("%s fetch %s (deferred %d)", target, "stopped by SIGTERM" if stopped else
             "paused (Wayback deferred)" if paused else "finished", len(deferred))
    return {"todo": len(todo), "deferred": deferred, "stopped": stopped, "paused_until": paused, "deferred_nb": dnb}


def _flush_q2(target, test, rows, keys, why, stage, cc, n):
    tag = f"{ {'cz': 'czspp', 'lt': 'ltetar', 'hu': 'hunjt'}.get(target, 'bejustel') }_archive_"
    by, unm = defaultdict(list), []
    for r in rows:
        (by[r["place_id"]] if r["place_id"] else unm).append(r)
    ok = 0
    for pid, rs in by.items():
        w = StagedWriter(stage, cc, pid, batch_prefix=tag, chunk=10 ** 9)
        for r in rs:
            if not w.add(r):
                ok += 1
        w.flush()
    if unm:
        u = (stage / "_unmatched") if test else UNM
        u.mkdir(parents=True, exist_ok=True)
        AJ.atomic_write(u / f"{target}_archive_unmatched_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}p0001.jsonl", unm)
    sfx = "_test" if test else ""
    with (STATE / target / f"done{sfx}.txt").open("a") as df:
        for k in keys:
            df.write(k + "\n")
        df.flush()
        os.fsync(df.fileno())
    log.info("%s final batch matched=%d unmatched=%d %s | %d", target, ok, len(unm), dict(why), n)


def queue(args):
    """Wait until no archive_jobs.py at/pl process is alive, then run cz and be in turn (same lane/limiter)."""
    def busy():
        out = subprocess.run(["pgrep", "-f", r"archive_jobs\.py (all|fetch) (at|pl)"], capture_output=True, text=True).stdout
        return bool(out.strip())
    while busy():
        time.sleep(600)
    for t in ("cz", "be"):
        AJ.setup_logging(t)
        if not (STATE / t / "candidates.jsonl").exists():
            fx = new_fx()
            log.info("%s discover: %s", t, cz_discover(fx) if t == "cz" else be_discover(fx))
        fetch(t, None, None)


def czfirst(args):
    """CZ to the front (2026-10-12): run cz now, then resume archive_jobs at+pl (checkpointed) and wait, then be."""
    t = "cz"
    AJ.setup_logging(t)
    if not (STATE / t / "candidates.jsonl").exists():
        fx = new_fx()
        log.info("%s discover: %s", t, cz_discover(fx))
    fetch(t, None, None)
    py, here = sys.executable, Path(__file__).resolve().parent
    procs = []
    for cc in ("at", "pl"):
        lf = open(STAGE / "_logs" / f"archive_{cc}.nohup.out", "a")
        procs.append(subprocess.Popen([py, "-u", "archive_jobs.py", "all", cc], cwd=here, stdout=lf,
                                      stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL))
        log.info("resumed archive_jobs %s pid %d", cc, procs[-1].pid)
    for p in procs:
        p.wait()
    t = "be"
    AJ.setup_logging(t)
    if not (STATE / t / "candidates.jsonl").exists():
        fx = new_fx()
        log.info("%s discover: %s", t, be_discover(fx))
    fetch(t, None, None)


_RUNNER_LOCK = None
RUN_ORDER = ["lt", "cz", "at", "pl", "be", "op", "cee"]   # hu (hu_njt.py) is NOT queued: rights decision pending (2026-10-18)   # op = Opole (archive_request_OP.json); cee = SK/CZ/AT
# municipal sites the live council_docs.py runs could not use (cee_archive.py, 2026-10-18), last


def run(args):
    """THE single EU archive runner (2026-10-13). Targets in RUN_ORDER, one process, shared limiter + Wayback breaker.
    - Items deferred because the breaker is open are neither done nor failed; while it stays open they are skipped
      (no CC-only re-tries every loop); once Wayback is available again every target is re-run from its checkpoint.
    - Discovery that needs a Wayback prefix listing (lt; cz/be if candidates are missing) waits for the breaker.
    - The runner exits when every target has no remaining and no deferred items. State: _state/archive/runner.json."""
    from archive import ratelimit
    import fcntl
    import signal
    from common.eu_wayback import gate_status, deferred_until
    signal.signal(signal.SIGTERM, AJ._on_term)
    AJ.setup_logging("runner")
    global _RUNNER_LOCK                   # 2026-10-18: exactly ONE runner (kernel releases the flock when it exits)
    _RUNNER_LOCK = open(STATE / "runner.lock", "a")
    try:
        fcntl.flock(_RUNNER_LOCK, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log.error("runner: another archive_q2.py run holds _state/archive/runner.lock - not starting a second runner")
        return
    log.info("runner pid %d start: lane %s, ONE thread / ONE EU Wayback request in flight (common/eu_wayback.py); 429/5xx -> "
             "shared ArchiveDeferred: target paused until not_before, other targets continue; cee = Common Crawl first",
             os.getpid(), os.environ.get("ARCHIVE_LANE"))
    resume_at = {}                        # target -> epoch: not re-entered before (Wayback ArchiveDeferred.not_before)
    hhmm = lambda t: time.strftime("%H:%M:%S %Z", time.localtime(t))  # noqa: E731
    order = [t for t in (args.order.split(",") if args.order else RUN_ORDER)]
    dnb = {t: {} for t in order}          # target -> {item key: not_before} (deferred items requeued for not_before)
    disc = {"cz": cz_discover, "be": be_discover, "lt": lt_discover}
    pending, deferred, info = list(order), {t: set() for t in order}, {}
    dtime = {t: 0.0 for t in order}       # when the current deferred set was formed
    CC_RETRY_SECS = 3 * 3600              # CC-only re-try of deferred items every 3 h even while Wayback stays down
    qf = STATE / "runner_queue.txt"      # 2026-10-18: extra targets (one per line) picked up each round, no restart
    while pending and not AJ.STOP[0]:
        if not args.order and qf.exists():
            for t in [x.strip() for x in qf.read_text().splitlines() if x.strip() and not x.startswith("#")]:
                if t in RUN_ORDER and t not in order:
                    order.append(t); pending.append(t); deferred[t] = set(); dtime[t] = 0.0; dnb[t] = {}
                    log.info("runner: %s added from runner_queue.txt", t)
        attempted = 0
        for t in list(pending):
            if AJ.STOP[0]:
                break
            nb = resume_at.get(t, 0.0)
            if nb > time.time():          # deferred, not failed: other targets go on; this one waits for not_before
                info[t] = f"wayback deferred until {hhmm(nb)}"
                log.info("runner: %s skipped: %s", t, info[t])
                continue
            wb = ratelimit.wayback_available()
            if t in disc and not (STATE / t / "candidates.jsonl").exists():
                if not wb:
                    info[t] = "discovery waits for the Wayback breaker"
                    log.info("%s: %s", t, info[t])
                    continue
                try:
                    log.info("%s discover: %s", t, disc[t](new_fx()))
                except Exception as e:  # noqa: BLE001
                    info[t] = f"discovery deferred: {str(e)[:150]}"
                    if deferred_until(e):
                        resume_at[t] = deferred_until(e)
                    log.warning("%s %s", t, info[t])
                    continue
            if t == "hu":                   # paged CDX discovery, resumable per page; no-op once all pages are listed
                if not wb:
                    info[t] = "discovery waits for the Wayback breaker"
                    continue
                try:
                    import hu_njt
                    log.info("hu discover: %s", hu_njt.discover(new_fx()))
                except Exception as e:  # noqa: BLE001
                    info[t] = f"discovery deferred: {str(e)[:150]}"
                    if deferred_until(e):
                        resume_at[t] = deferred_until(e)
                    log.warning("hu %s", info[t])
                    if not (STATE / "hu" / "candidates.jsonl").exists():
                        continue
            retry_cc = time.time() - dtime[t] >= CC_RETRY_SECS
            now = time.time()
            dnb[t] = {k: v for k, v in dnb[t].items() if v > now}
            skip = (frozenset() if (wb or retry_cc) else frozenset(deferred[t])) | frozenset(dnb[t])
            log.info("runner: %s start (wayback %s, skipping %d deferred)", t, "up" if wb else "BREAKER OPEN", len(skip))
            if t in ("at", "pl"):
                res = AJ.fetch(t, None, None, skip=skip)
            elif t == "cee":
                import cee_archive
                res = cee_archive.fetch(None, None, skip=skip)
            elif t == "op":
                log.info("op candidates rebuilt: %d remaining live OP acts", AJ.op_candidates())
                res = AJ.fetch("pl", None, None, wojs=("OP",), skip=skip)
            else:
                res = fetch(t, None, None, skip=skip)
            attempted += res["todo"]
            dnb[t].update(res.get("deferred_nb") or {})
            if res.get("paused_until"):
                resume_at[t] = res["paused_until"]
                log.info("runner: %s paused until %s (Wayback deferred); continuing with other targets", t, hhmm(resume_at[t]))
            deferred[t] = (set() if (wb or retry_cc) else deferred[t]) | set(res["deferred"])
            if wb or retry_cc:
                dtime[t] = time.time()
            info[t] = {"attempted": res["todo"], "deferred_now": len(deferred[t]), "requeued_for_not_before": len(dnb[t]),
                       "paused_until": hhmm(resume_at[t]) if resume_at.get(t, 0) > time.time() else None}
            (STATE / "runner.json").write_text(json.dumps({"at": AJ.utcnow(), "pid": os.getpid(), "order": order,
                                                           "pending": pending, "targets": info, "wayback_workers": 1,
                                                           "eu_wayback_gate": gate_status(),
                                                           "accepted_incomplete_docs": dict(AJ.INCOMPLETE)}, indent=1, default=str))
            if res["stopped"]:
                return
            if res["todo"] == 0 and not deferred[t] and not res.get("paused_until") and not dnb[t]:
                pending.remove(t)
                log.info("runner: %s complete", t)
        if pending and attempted == 0:      # only deferred work left: idle until the breaker closes / a not_before passes
            st = ratelimit.breaker_status()
            now = time.time()
            due = [resume_at[t] for t in pending if resume_at.get(t, 0.0) > now] + \
                  [v for t in pending for v in dnb.get(t, {}).values() if v > now]
            nxt = min(due) if due else now + 1800
            wb0 = ratelimit.wayback_available()
            log.info("runner: idle (breaker %s, next probe in %ss); next deferred item/target due %s; pending %s",
                     st.get("state"), st.get("next_probe_in"), hhmm(nxt), pending)
            for _ in range(60):             # <= 30 min idle (not a retry loop: nothing is requested while waiting)
                if AJ.STOP[0]:
                    break
                wbn = ratelimit.wayback_available()
                if time.time() >= nxt and wbn or (wbn and not wb0):   # something due, or the breaker just closed
                    break
                time.sleep(30)
    log.info("runner finished: %s", info)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["discover", "fetch", "all", "status", "queue", "czfirst", "run"])
    ap.add_argument("--order", help="comma list for `run` (default lt,cz,at,pl,be,op,cee)")
    ap.add_argument("target", nargs="?", choices=["cz", "be", "lt", "hu"])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--test", type=int)
    a = ap.parse_args()
    if a.cmd == "queue":
        return queue(a)
    if a.cmd == "czfirst":
        return czfirst(a)
    if a.cmd == "run":
        return run(a)
    if a.cmd == "status":
        for t in ("cz", "be", "lt", "hu"):
            dj = STATE / t / "discover.json"
            print(t, dj.read_text() if dj.exists() else "-", "done", len(AJ.load_done(STATE / t / "done.txt")))
        return
    AJ.setup_logging(a.target)
    fx = new_fx()
    if a.cmd == "discover" or (a.cmd == "all" and not (STATE / a.target / "candidates.jsonl").exists()):
        if a.target == "hu":
            import hu_njt
            log.info("hu discover: %s", hu_njt.discover(fx, max_pages=a.limit if a.cmd == "discover" else None))
        else:
            disc = {"cz": cz_discover, "be": be_discover, "lt": lt_discover}[a.target]
            log.info("%s discover: %s", a.target, disc(fx))
    if a.cmd in ("fetch", "all"):
        fetch(a.target, a.limit, a.test)


if __name__ == "__main__":
    main()
