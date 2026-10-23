#!/usr/bin/env python3
"""Poland: 16 voivodeship official journals (Dzienniki Urzędowe Województw, ABC PRO e-Dziennik, ELI API).

Endpoints (same on every host, prefix /api/eli, no key, GET only):
  /api/eli/acts                                   publisher + years
  /api/eli/acts/{pub}/{year}                      full yearly list (no `limit` = complete; never limit=100000)
  /api/eli/acts/{pub}/{year}/{pos}/text.pdf       official PDF (full text)
  /api/eli/acts/{pub}/{year}/{pos}/text.html      HTML (usually only page 1; fallback only)

Pass 1 scope: gmina/powiat (+ voivodeship sejmik/wojewoda) organs; types Uchwała/Zarządzenie/Rozporządzenie
(+ Obwieszczenie of consolidated text); status 'obowiązujący'; budget/financial-report resolutions deferred
to a later pass. Newest years first. All other catalogued acts stay in _state/pl/catalog_<WOJ>.jsonl.

    python pl_dzienniki.py catalog            # build/resume yearly catalogs for all reachable hosts
    python pl_dzienniki.py fetch [--woj SK] [--limit N] [--test N]
    python pl_dzienniki.py all                # catalog + fetch (one thread per host)
    python pl_dzienniki.py status
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
import hashlib
import json
import logging
import os
import random
import re
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))

HOSTS = {  # code: (voivodeship, host, ISO 3166-2)
    "DS": ("dolnośląskie", "edzienniki.duw.pl", "PL-02"),
    "KP": ("kujawsko-pomorskie", "edzienniki.bydgoszcz.uw.gov.pl", "PL-04"),
    "LB": ("lubelskie", "edziennik.lublin.uw.gov.pl", "PL-06"),
    "LS": ("lubuskie", "dzienniki.luw.pl", "PL-08"),
    "LD": ("łódzkie", "dziennik.lodzkie.eu", "PL-10"),
    "MP": ("małopolskie", "edziennik.malopolska.uw.gov.pl", "PL-12"),
    "MZ": ("mazowieckie", "edziennik.mazowieckie.pl", "PL-14"),
    "OP": ("opolskie", "duwo.opole.uw.gov.pl", "PL-16"),
    "PK": ("podkarpackie", "edziennik.rzeszow.uw.gov.pl", "PL-18"),
    "PL": ("podlaskie", "edziennik.bialystok.uw.gov.pl", "PL-20"),
    "PM": ("pomorskie", "edziennik.gdansk.uw.gov.pl", "PL-22"),
    "SL": ("śląskie", "dzienniki.slask.eu", "PL-24"),
    "SK": ("świętokrzyskie", "edziennik.kielce.uw.gov.pl", "PL-26"),
    "WM": ("warmińsko-mazurskie", "edzienniki.olsztyn.uw.gov.pl", "PL-28"),
    "WP": ("wielkopolskie", "edziennik.poznan.uw.gov.pl", "PL-30"),
    "ZP": ("zachodniopomorskie", "e-dziennik.szczecin.uw.gov.pl", "PL-32"),
}
TERYT_WOJ = {v[2][3:]: k for k, v in HOSTS.items()}  # "26" -> "SK"
UA = "world-municipal-law-research/1.0 (EU lane; open-data reuse of ELI API; ~1 req/s per host)"
HEADERS = {"User-Agent": UA, "Accept": "application/json, application/pdf, */*", "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.5"}
OUT = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/eu"))
PL_DIR = OUT / "PL"
UNM_DIR = OUT / "_unmatched"
STATE = OUT / "_state" / "pl"
LOGS = OUT / "_logs"
CA_BUNDLE = OUT / "_state" / "pl_certs" / "ca_bundle_plus.pem"  # certifi + Certum intermediates (AIA) for MP/LS/LD
MIN_INTERVAL = 0.7
RETRIES = 6
BATCH_DOCS = 500
MAX_PDF = 40 * 1024 * 1024
CAND = Path((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + "/global_municipalities_candidate.csv"))
WD_CSV = HERE / "data" / "wd_pl_teryt.csv"

log = logging.getLogger("pl")
sys.path.insert(0, str(HERE))
from common.rfc9309 import RobotsCache  # noqa: E402


def _robots_session(_base):
    s = requests.Session()
    s.headers.update(HEADERS)
    s.verify = str(CA_BUNDLE) if CA_BUNDLE.exists() else True
    return s


ROBOTS = RobotsCache(_robots_session, UA, log=log)
_tls = threading.local()


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def setup_logging() -> None:
    for d in (PL_DIR, UNM_DIR, STATE, LOGS):
        d.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s [%(threadName)s] %(message)s", "%Y-%m-%dT%H:%M:%S%z")
    log.setLevel(logging.INFO)
    if not log.handlers:
        for h in (logging.FileHandler(LOGS / "pl_dzienniki.log", encoding="utf-8"), logging.StreamHandler(sys.stdout)):
            h.setFormatter(fmt)
            log.addHandler(h)


HOST_HEALTH = STATE / "host_health.json"
PARK_STEPS_H = [2, 4, 6, 6]         # persistent 401/403 => park host for hours (escalating)
ARCHIVE_AFTER_H = 6                  # 403 persisting longer than this => request an archive pass for the host


class HostParked(RuntimeError):
    pass


def _health() -> dict:
    try:
        return json.loads(HOST_HEALTH.read_text())
    except Exception:  # noqa: BLE001
        return {}


class Host:
    def __init__(self, woj: str):
        self.woj = woj
        self.name, self.host, self.iso = HOSTS[woj]
        self.base = f"https://{self.host}"
        self.pub = f"POL_WOJ_{woj}"
        self.s = requests.Session()
        self.s.headers.update(HEADERS)
        self.s.verify = str(CA_BUNDLE) if CA_BUNDLE.exists() else True
        self.last = 0.0
        self.c403 = 0

    @property
    def parked_until(self) -> float:
        return float(_health().get(self.woj, {}).get("until", 0))

    def _park(self, status, url):
        hh = _health()
        st = hh.get(self.woj, {})
        k = int(st.get("parks", 0))
        hrs = PARK_STEPS_H[min(k, len(PARK_STEPS_H) - 1)]
        first = st.get("first_403") or utcnow()
        st.update(until=time.time() + hrs * 3600, parks=k + 1, first_403=first, last_status=status, last_url=url,
                  last_at=utcnow())
        hh[self.woj] = st
        HOST_HEALTH.write_text(json.dumps(hh, indent=1))
        rec = {"source": "pl_dzienniki", "url": self.base, "status": "temporarily_blocked_403",
               "detail": f"HTTP {status} x{self.c403} consecutive (last {url}); first 403 {first}; parked {hrs}h (#{k + 1})",
               "at": utcnow(), "action": f"host parked {hrs}h; archive pass requested if >{ARCHIVE_AFTER_H}h"}
        with (LOGS / "blocked_sources.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        log.error("%s host parked %dh after %d consecutive HTTP %s (first 403 %s)", self.woj, hrs, self.c403, status, first)
        try:
            t0 = time.mktime(time.strptime(first, "%Y-%m-%dT%H:%M:%SZ")) - time.timezone
            if time.time() - t0 > ARCHIVE_AFTER_H * 3600:
                req = STATE / f"archive_request_{self.woj}.json"
                if not req.exists():
                    req.write_text(json.dumps({"woj": self.woj, "host": self.host, "first_403": first, "at": utcnow(),
                                               "reason": f"HTTP 403 > {ARCHIVE_AFTER_H}h"}))
                    log.error("%s 403 for >%dh: archive pass requested (%s)", self.woj, ARCHIVE_AFTER_H, req.name)
        except Exception:  # noqa: BLE001
            pass
        self.c403 = 0

    def get(self, path: str, params=None, stream=False, retries=RETRIES) -> requests.Response:
        url = path if path.startswith("http") else self.base + path
        waited = 0
        while not ROBOTS.can_fetch(url):
            st = ROBOTS.cache.get(self.base, (None, 0, None))[2]
            if isinstance(st, int) and st < 500:
                raise PermissionError(f"robots.txt (RFC 9309) disallows {url}")
            # robots.txt unreachable/5xx => RFC 9309 says assume full disallow: wait, then re-check
            if waited >= retries * 600:
                raise PermissionError(f"robots.txt unavailable ({st}) for {self.base}; not fetching {url}")
            log.warning("%s robots.txt unavailable (%s); waiting 10 min", self.woj, st)
            time.sleep(600)
            waited += 600
            ROBOTS.cache.pop(self.base, None)
        if self.parked_until > time.time():
            raise HostParked(f"{self.woj} parked until {time.strftime('%H:%M', time.localtime(self.parked_until))}")
        cd = ROBOTS.get(url).crawl_delay(UA)
        gap = max(MIN_INTERVAL, cd or 0)
        err: Any = None
        for a in range(retries):
            w = gap - (time.monotonic() - self.last)
            if w > 0:
                time.sleep(w)
            self.last = time.monotonic()
            try:
                r = self.s.get(url, params=params, timeout=(20, 180), stream=stream, allow_redirects=True)
                if r.status_code == 200:
                    if self.c403 or _health().get(self.woj):
                        hh = _health()
                        hh.pop(self.woj, None)
                        HOST_HEALTH.write_text(json.dumps(hh, indent=1))
                    self.c403 = 0
                    return r
                if r.status_code in (400, 404, 406, 410):
                    r.raise_for_status()
                if r.status_code in (401, 403):
                    self.c403 += 1
                    log.error("BLOCKED? HTTP %s %s (%d consecutive)", r.status_code, url, self.c403)
                    if self.c403 >= 3:
                        self._park(r.status_code, url)
                        raise HostParked(f"{self.woj} HTTP {r.status_code}: host parked")
                    if a >= 1:   # no long retry loops on 403
                        raise RuntimeError(f"HTTP {r.status_code} {url}")
                err = RuntimeError(f"HTTP {r.status_code} {url}")
                ra = r.headers.get("Retry-After")
                back = float(ra) if ra and ra.isdigit() else min(2 ** (a + 1), 300)
            except requests.HTTPError:
                raise
            except requests.RequestException as e:
                err, back = e, min(2 ** (a + 1), 300)
            log.warning("%s retry %d/%d %s; sleep %.0fs", self.woj, a + 1, retries, str(err)[:200], back)
            time.sleep(back)
        raise err


def lowerkeys(o):
    if isinstance(o, dict):
        return {(k[:1].lower() + k[1:]): lowerkeys(v) for k, v in o.items()}
    if isinstance(o, list):
        return [lowerkeys(v) for v in o]
    return o


# ----------------------------------------------------------------------------- catalog
def catalog_host(woj: str) -> Optional[Path]:
    h = Host(woj)
    cat = STATE / f"catalog_{woj}.jsonl"
    stp = STATE / f"catalog_{woj}.state.json"
    st = json.loads(stp.read_text()) if stp.exists() else {"years_done": {}, "blocked": None}
    try:
        info = lowerkeys(h.get("/api/eli/acts", retries=3).json())
    except Exception as e:  # noqa: BLE001
        st["blocked"] = f"{utcnow()} {type(e).__name__}: {str(e)[:300]}"
        stp.write_text(json.dumps(st, ensure_ascii=False))
        log.error("%s (%s) UNREACHABLE/BLOCKED: %s", woj, h.host, st["blocked"])
        return None
    st["blocked"] = None
    pubinfo = next((p for p in info if p.get("code") == h.pub), info[0] if info else {})
    st["publisher"] = {k: pubinfo.get(k) for k in ("code", "shortName", "name", "deedsCount", "count")}
    years = sorted(pubinfo.get("years") or [], reverse=True)
    cur = str(datetime.now().year)
    with cat.open("a", encoding="utf-8") as f:
        for y in years:
            if str(y) in st["years_done"] and str(y) != cur:
                continue
            if str(y) == cur and str(y) in st["years_done"]:
                continue  # current year: refreshed by a later incremental pass
            paged = False
            try:
                r = h.get(f"/api/eli/acts/{h.pub}/{y}", retries=3)
                d = lowerkeys(r.json())
                items, total = d.get("items") or [], d.get("totalCount")
            except Exception as e:  # noqa: BLE001  (slow backends 504 on a full year: page instead)
                log.warning("%s %s full-year list failed (%s); paging limit=1000", woj, y, str(e)[:120])
                items, total, off, paged = [], None, 0, True
                while True:
                    d = lowerkeys(h.get(f"/api/eli/acts/{h.pub}/{y}", params={"limit": 1000, "offset": off}).json())
                    page = d.get("items") or []
                    total = d.get("totalCount", total)
                    items.extend(page)
                    off += len(page)
                    if not page or (total and off >= total):
                        break
                seen_pos, uniq = set(), []
                for it in items:
                    if it.get("pos") not in seen_pos:
                        seen_pos.add(it.get("pos"))
                        uniq.append(it)
                items = uniq
            if total and len(items) < total and not paged:
                r = h.get(f"/api/eli/acts/{h.pub}/{y}", params={"limit": total + 500})
                d2 = lowerkeys(r.json())
                if len(d2.get("items") or []) > len(items):
                    items = d2["items"]
            for it in items:
                if not it.get("title") or not it.get("pos"):
                    continue  # technical positions
                it["_woj"] = woj
                f.write(json.dumps(it, ensure_ascii=False) + "\n")
            f.flush()
            st["years_done"][str(y)] = {"items": len(items), "totalCount": total, "at": utcnow()}
            stp.write_text(json.dumps(st, ensure_ascii=False))
            log.info("%s catalog %s: %d items (totalCount %s)%s", woj, y, len(items), total,
                     "  SHORT!" if total and len(items) < total else "")
    return cat


# ----------------------------------------------------------------------------- scope / issuer parsing
ORG = (r"(Rad[ayęz]\w*|Sejmik\w*|Wójt\w*|Burmistrz\w*|Prezydent\w*|Starost\w*|Zarząd\w*|Wojewod\w*|Marszał\w*|"
       r"Zgromadzeni\w*|Komisarz\w*|Regionaln\w*|Dyrektor\w*|Komendant\w*|Państwow\w*|Kolegium|Przewodnicząc\w*|"
       r"Komisj\w*|Okręgow\w*|Powiatow\w*|Wojewódzk\w*|Prezes\w*|Kierownik\w*|Nadleśnicz\w*|Sąd\w*|Międzygminn\w*|Związ\w*)")
BUDGET = re.compile(r"bud[żz]e|wieloletni\w* prognoz|sprawozdani|absolutori|wotum zaufania|zaciągnięci\w* (kredytu|pożyczki)|"
                    r"emisji obligacji|udzieleni\w* pomocy finansowej|dotacji celowej", re.I)
TYPES_P1 = {"uchwała", "zarządzenie", "rozporządzenie", "rozporządzenie porządkowe", "zarządzenie porządkowe"}


def issuer_from_title(title: str, typ: str) -> Optional[str]:
    t = " ".join((title or "").replace("\xa0", " ").split())
    pre = re.split(r"\s+z dnia\s+", t, maxsplit=1, flags=re.I)[0]
    rest = pre[len(typ or ""):] if typ and pre.lower().startswith((typ or "").lower()) else pre
    m = re.search(r"\b" + ORG + r"\b.*$", rest, flags=re.I)
    return m.group(0).strip(" ,") if m else None


def organ_level(org: str) -> str:
    o = (org or "").lower()
    if re.match(r"(rad\w* |zarząd\w* |)(sejmik|województw)|^(zarząd\w*|marszał\w*) województw|^sejmik", o):
        return "voivodeship"
    if re.match(r"wojewod", o):
        return "voivode"
    if re.match(r"(rad\w*|zarząd\w*) powiatu|starost", o):
        return "powiat"
    if re.match(r"rad\w* (gminy|miasta|miejsk|gminy i miasta|miasta i gminy|dzielnicy|m\.|st\.)|"
                r"rad\w* miejskiej|wójt|burmistrz|prezydent\w* (m\.|miasta)|rad\w* m\.", o):
        return "gmina"
    return "other"


def in_pass1(it: dict) -> tuple[bool, str, Optional[str], str]:
    typ = (it.get("type") or "").strip()
    org = issuer_from_title(it.get("title"), typ)
    lvl = organ_level(org) if org else "unknown"
    tl = typ.lower()
    title = it.get("title") or ""
    cons = tl == "obwieszczenie" and re.search(r"jednolit", title, re.I)
    if not (tl in TYPES_P1 or cons):
        return False, "type", org, lvl
    if (it.get("status") or "").lower() != "obowiązujący":
        return False, "status", org, lvl
    if lvl not in ("gmina", "powiat", "voivodeship", "voivode"):
        return False, "organ", org, lvl
    if not cons and BUDGET.search(title):
        return False, "budget", org, lvl
    return True, "ok", org, lvl


# ----------------------------------------------------------------------------- places
def fold(s: str) -> str:
    s = s.lower().replace("ł", "l")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]+", " ", s).strip()


def norm_teryt(v: str) -> Optional[str]:
    """Wikidata P1653 holds 7-digit TERYT (WWPPGGT) or 10-digit NTS-style (R WW SS PP GG T) / 4-digit powiat."""
    d = re.sub(r"\D", "", v or "")
    if len(d) == 10:
        return d[1:3] + d[5:7] + d[7:9] + d[9]
    if len(d) in (4, 7):
        return d
    return None


def cpre(a: str, b: str) -> int:
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def word_match(tok: str, name: str) -> int:
    """score how well an inflected toponym word sequence `tok` matches a nominative `name` (0 = no)."""
    tw, nw = tok.split(), name.split()
    if len(tw) < len(nw) or not nw:
        return 0
    tw = tw[:len(nw)]
    score = 0
    for a, b in zip(tw, nw):
        p = cpre(a, b)
        need = max(3, min(len(b), len(a)) - 3) if len(b) > 4 else min(len(b), 3)
        if b in ("st",) and a.startswith("st"):
            p = len(b)
        if p < need:
            return 0
        score += p + (1 if a == b else 0)   # exact nominative beats a longer name sharing the prefix (Baranów vs Baranowo)
    return score


IRREG = {"bialymstoku": "bialystok", "bialymstok": "bialystok", "zielonej gorze": "zielona gora",
         "gorzowie wielkopolskim": "gorzow wielkopolski", "nowym saczu": "nowy sacz", "nowym targu": "nowy targ",
         "nowym dworze": "nowy dwor", "nowym miescie": "nowe miasto", "starym saczu": "stary sacz"}


from common.xwalk import XWALK, ADDITIONS  # noqa: E402  shared crosswalk, preferred over own tables


class PlaceMap:
    def __init__(self) -> None:
        self.anchors = {}
        self.cand = {r["qid"]: r for r in csv.DictReader(CAND.open(encoding="utf-8")) if r["country_code"] == "PL"}
        self.by_teryt: dict[str, list] = defaultdict(list)
        self.gminas: dict[str, list] = defaultdict(list)   # woj -> [(name_fold, teryt7, type_digit)]
        self.powiats: dict[str, list] = defaultdict(list)  # woj -> [(adj/name fold, teryt4)]
        self.label: dict[str, str] = {}
        self.by_t6: dict[str, list] = defaultdict(list)
        for r in csv.DictReader(WD_CSV.open(encoding="utf-8")):
            if r["end"]:
                continue
            q = r["item"].rsplit("/", 1)[-1]
            t = norm_teryt(r["teryt"])
            if not t:
                continue
            self.by_teryt[t].append(q)
            woj = TERYT_WOJ.get(t[:2])
            if not woj:
                continue
            types = r["types"]
            names = {r["pl"], *(r["alts"] or "").split("|")}
            if len(t) == 7 and t[-1] in "12345":
                self.by_t6[t[:6]].append(q)
                if t[-1] == "5":
                    continue
                gt = t[:6] + ("3" if t[-1] == "4" else t[-1])   # town of urban-rural gmina -> the gmina
                for nm in names:
                    f = fold(re.sub(r"^(gmina|miasto|gmina miejska|gmina wiejska|miasto i gmina)\s+", "", nm or "", flags=re.I))
                    if f:
                        self.gminas[woj].append((f, gt, gt[-1]))
                if t[-1] != "4" or gt not in self.label:
                    self.label.setdefault(gt, r["pl"])
            elif len(t) == 4 and "Q247073" in types:
                for nm in names:
                    f = fold(re.sub(r"^powiat\s+", "", nm or "", flags=re.I))
                    if f:
                        self.powiats[woj].append((f, t))
                self.label[t] = r["pl"]
        for woj in self.gminas:
            self.gminas[woj] = sorted(set(self.gminas[woj]))
        self.cache: dict = {}

    _POW = None

    def powiat_row(self, t: str) -> Optional[dict]:
        """codes/proposed/PL_powiaty.csv (GUS BDL level 5 + place_additions + city gminas), 2026-10-17."""
        if PlaceMap._POW is None:
            pp = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/codes/proposed/PL_powiaty.csv"))
            PlaceMap._POW = {r["teryt"]: r for r in csv.DictReader(pp.open(encoding="utf-8"))} if pp.exists() else {}
        r = PlaceMap._POW.get(t)
        return r if r and r["place_id"] and r["kind"] != "historical" else None

    def cand_for_teryt(self, t: str) -> Optional[dict]:
        if len(t) == 4:
            pr = self.powiat_row(t)
            if pr:
                q = pr["place_id"][3:] if pr["place_id"].startswith("wd:") else None
                c = self.cand.get(q) if q else None
                if pr["kind"] == "city_county" and c:      # city county = the city gmina (same council)
                    return dict(c, _via="powiaty_city_county")
                ad = ADDITIONS.row(pr["place_id"]) or {}
                return {"place_id": pr["place_id"], "qid": q, "place_name": ad.get("name_native") or pr["name"],
                        "admin_level": ad.get("admin_level") or "county", "iso_3166_2": pr["iso_3166_2"],
                        "_via": "powiaty_csv"}
        # 1) shared crosswalk (pipeline/codes/place_codes.csv: pl_teryt_terc / pl_nts), 2) own Wikidata table
        for k in ([t, t[:6] + "3", t[:6] + "1", t[:6] + "2"] if len(t) == 7 else [t]):
            pid = XWALK.get("PL", k)
            if pid:
                q = pid[3:] if pid.startswith("wd:") else None
                c = self.cand.get(q) if q else None
                if c:
                    return dict(c, _via="crosswalk")
                ad = ADDITIONS.row(pid)   # e.g. the 314 land powiats (admin_level=county) from codes/place_additions.csv
                if ad:
                    return {"place_id": pid, "qid": ad.get("qid") or q, "place_name": ad.get("name_native") or ad.get("name")
                            or self.label.get(t), "admin_level": ad.get("admin_level") or "county",
                            "iso_3166_2": ad.get("iso_3166_2") or None, "_via": "crosswalk+additions"}
                return {"place_id": pid, "qid": q, "place_name": self.label.get(t), "admin_level":
                        "county" if len(t) == 4 else "gmina", "_via": "crosswalk"}
        qs = [q for q in self.by_teryt.get(t, []) if q in self.cand]
        if not qs and len(t) == 7:   # same gmina under another type digit (city item / town part)
            qs = [q for q in self.by_t6.get(t[:6], []) if q in self.cand]
        return self.cand[qs[0]] if qs else None

    NOMIN = re.compile(r"\b(?:[Gg]min(?:y|ie|ą|a)|GMIN(?:Y|IE|A)|[Mm]iasta i [Gg]miny|[Mm]iasta|MIASTA)\s+(?:[Mm]iejskiej\s+|[Ww]iejskiej\s+)?"
                       r"((?:[A-ZŁŚŻŹĆÓĘĄŃ][\wąęółśżźćńĄĘÓŁŚŻŹĆŃ.-]*)(?:[ -](?:[A-ZŁŚŻŹĆÓĘĄŃ][\wąęółśżźćńĄĘÓŁŚŻŹĆŃ.-]*|nad|pod|w|we|i))*)")
    POW_ADJ = re.compile(r"\b(?:powiat\w*|POWIAT\w*|[Ss]tarost\w*\s+[Pp]owiat\w*)\s+([a-ząęółśżźćńA-ZŁŚŻŹĆÓĘĄŃ-]{4,})")

    def _pow_adj_stems(self, woj):
        out = {}
        self.powiat_row("0000")
        for t, lab in ([(k, v["name"]) for k, v in PlaceMap._POW.items() if v["kind"] != "historical"] or self.label.items()):
            if len(t) == 4 and TERYT_WOJ.get(t[:2]) == woj:
                f = fold(re.sub(r"^powiat\s+", "", lab or "", flags=re.I))
                if f:
                    out[t] = re.sub(r"(ski|cki|dzki|ny|ni|wy|ki|i|y)$", lambda m: m.group(1)[:-1] if len(m.group(1)) > 1 else "", f.split()[0])
        return out

    _FILL = None
    EXT_IRREG = [(r"\bbia[łl]egostoku\b", "Białystok"), (r"\bw dobrym mie[śs]cie\b", "Dobre Miasto"), (r"\bw ujeździe\b", "Ujazd"),
                 (r"\bg[łl]ogowie m[łl]p\.?", "Głogów Małopolski"), (r"\bn\.\s*odr[ąa]\b", "nad Odrą"), (r"\buzdrowiskow\w*\s+", ""),
                 (r"\bkuczbork\b(?!-)", "Kuczbork-Osada"), (r"\brumi\b", "Rumia")]

    # 2026-10-17 review (codes/proposed/PL_gmina_fill_reviewed.csv): rejected rows keep their name for matching, but
    # resolve through the CORRECT code below (crosswalk, else place_successors.csv), never through the rejected place_id.
    #   Żory 2479011 is the city with powiat rights wd:Q393171 (not the bare gmina item wd:Q33732308);
    #   Rumia is TERC 2215021 (2215011 is Reda wd:Q936933);
    #   rural gmina Zielona Góra 0809102 = former wd:Q2426631 (not a place) -> successor city wd:Q104720 (0862011).
    REJECT_FIX = {("SL", "Żory"): "2479011", ("PM", "Rumia"): "2215021", ("LS", "Zielona Góra (gmina wiejska)"): "0809102"}

    def fill_row(self, woj, top=None, teryt=None):
        """codes/proposed/PL_gmina_fill_reviewed.csv (decision accept|reject) for gminas missing from wd_pl_teryt.csv /
        the candidate CSV. Accepted rows match by teryt or name; rejected rows match by name only (their teryt/place
        may be wrong) and carry decision=reject so the caller resolves them via REJECT_FIX."""
        if PlaceMap._FILL is None:
            pp = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/codes/proposed/PL_gmina_fill_reviewed.csv"))
            PlaceMap._FILL = list(csv.DictReader(pp.open(encoding="utf-8"))) if pp.exists() else []
        for r in PlaceMap._FILL:
            if r["voivodeship"] != woj:
                continue
            acc = r.get("decision") == "accept"
            if acc and teryt and r["teryt"] == teryt:
                return r
            nm = fold(re.sub(r"\s*\(.*\)", "", r["name"]))
            if top and word_match(top, nm) and (not teryt or (not acc and r["teryt"] == teryt) or
                                                 (not acc and (woj, r["name"]) in self.REJECT_FIX)):
                return r
        return None

    def fill_reject_fix(self, fr) -> Optional[dict]:
        """place for a REJECTED fill row: corrected code -> crosswalk/candidate, else the single successor."""
        t = self.REJECT_FIX.get((fr["voivodeship"], fr["name"]))
        if not t:
            return None
        c = self.cand_for_teryt(t)
        if c and c.get("place_id"):
            return dict(place_id=c["place_id"], qid=c["qid"], place_name=re.sub(r"\s*\(.*\)", "", fr["name"]), teryt=t,
                        admin_level=c.get("admin_level") or "municipality", match="PL_gmina_fill_reviewed:code_fix")
        from common.xwalk import SUCCESSORS
        sc = SUCCESSORS.lookup("PL", code=t)
        if sc.get("status") == "ok":
            q = sc["place_id"][3:]
            c = self.cand.get(q) or {}
            return dict(place_id=sc["place_id"], qid=q, place_name=c.get("place_name") or sc.get("successor_name"),
                        teryt=sc.get("successor_code") or None, admin_level=c.get("admin_level") or "municipality",
                        match="PL_gmina_fill_reviewed:former_code->successor", mapped_via="successor",
                        former_name=sc.get("old_name"), former_code=sc.get("old_code"), dissolved_date=sc.get("dissolved_date"))
        return None

    _VIL = None

    VIL_STOP = {"Miejsce", "Laski", "Kolonia", "Polana", "Lipie", "Borki", "Huta", "Zalesie", "Podlesie", "Grabina",
                "Dąbrówka", "Dąbrówki", "Borowa", "Wola Mała", "Krążek", "Sołectwo", "Osiedle", "Centrum", "Kąty", "Górki"}

    def village_vote(self, ts, blob):
        """villages (sołectwa) of each same-name gmina, from pl.wikipedia (tools/pl_gmina_villages.py cache): pick the
        candidate whose exclusive villages are named in the act (>=2 distinct hits, and no hits for the others)."""
        if PlaceMap._VIL is None:
            pp = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/eu/_state/pl/wiki_villages.json"))
            PlaceMap._VIL = json.loads(pp.read_text()) if pp.exists() else {}
        vs = {t: set(PlaceMap._VIL.get(t, {}).get("villages") or []) for t in ts}
        if not all(vs.values()):    # every same-name gmina needs a village list, else absence of hits means nothing
            return None
        names = {re.sub(r"^gmina\s+", "", (self.label.get(t) or ""), flags=re.I) for t in ts}
        sc = {}
        for t in ts:
            excl = {v for v in vs[t] if v not in names and v not in ("Sołectwo", "Kolonia", "Gmina", "Wieś", "Osada")
                    and not any(v in vs[u] for u in ts if u != t)}
            excl = {v for v in excl if len(v) >= 5 and v not in self.VIL_STOP and v.lower() not in blob}   # drop common nouns
            sc[t] = {v for v in excl if re.search(r"(?<![\wąęółśżźćń])" + re.escape(v) + r"(?![\wąęółśżźćń-])", blob)}
        win = [t for t in ts if len(sc[t]) >= 2]
        if len(win) == 1 and all(not sc[u] for u in ts if u != win[0]):
            return win[0], len(sc[win[0]])
        return None

    SIGN_SKIP = re.compile(r"rad[ayz]|gmin|przewodnicz|w[óo]jt|burmistrz|wice|zast[eę]pca|miast|uchwa|za\s+zgodno|podpis|"
                           r"\bz up\b|dzienni|wojew|starost|prezydent|sekretarz|skarbnik|\bmgr\b|\binż\b|\bdr\b", re.I)

    @classmethod
    def signer(cls, text: str) -> Optional[str]:
        """last personal name in the act's signature block (e.g. 'Aneta Feret'); None if not found."""
        for ln in reversed([x.strip(" .,") for x in (text or "")[-600:].splitlines() if x.strip()][-8:]):
            ln = re.sub(r"^(mgr|inż\.?|dr|ks\.)\s+", "", ln, flags=re.I)
            if (re.fullmatch(r"[A-ZŁŚŻŹĆÓĘĄŃ][a-ząęółśżźćń]+(?:-[A-ZŁŚŻŹĆÓĘĄŃ][a-ząęółśżźćń]+)?\s+[A-ZŁŚŻŹĆÓĘĄŃ][a-ząęółśżźćń]+(?:-[A-ZŁŚŻŹĆÓĘĄŃ][a-ząęółśżźćń]+)?", ln)
                    and not cls.SIGN_SKIP.search(ln)):
                return fold(ln)
        return None

    def add_anchor(self, res: dict, text: str) -> None:
        """remember (same-name candidate set, signer) -> teryt for docs disambiguated by an explicit cue."""
        if res.get("place_id") and res.get("amb_cands"):
            sg = self.signer(text)
            if sg:
                self.anchors.setdefault((res["amb_cands"], sg), Counter())[res["teryt"]] += 1

    def propagate(self, res: dict, text: str) -> dict:
        """unresolved same-name gmina doc signed by the same person as >=3 (>=90 %) cue-resolved docs -> that gmina."""
        if res.get("place_id") or not res.get("amb_cands"):
            return res
        sg = self.signer(text)
        cn = self.anchors.get((res["amb_cands"], sg)) if sg else None
        if cn:
            (t, k), tot = cn.most_common(1)[0], sum(cn.values())
            if k >= 3 and k / tot >= 0.9:
                c = self.cand_for_teryt(t)
                if c:
                    res = dict(res, place_id=c["place_id"], qid=c["qid"], place_name=c["place_name"], teryt=t,
                               admin_level=c["admin_level"], match=f"ambiguous->signer({sg};{k}/{tot})->candidate")
        return res

    def resolve_ext(self, woj: str, org: Optional[str], lvl: str, title: str = "", text: str = "") -> dict:
        o0 = " ".join((org or "").split())
        o1 = o0
        for a, b in self.EXT_IRREG:
            o1 = re.sub(a, b, o1, flags=re.I)
        o1 = re.sub(r"\((?:pow\.|powiat)[^)]*\)", "", o1, flags=re.I).strip()
        res = self._resolve_ext(woj, o1, lvl, title, text, qual=o0)
        if not res.get("place_id") and lvl == "gmina":
            fr = self.fill_row(woj, res.get("toponym"), res.get("teryt")) if (res.get("teryt") or res.get("toponym")) else None
            if fr and fr.get("decision") != "accept":
                fx = self.fill_reject_fix(fr)
                if fx:
                    m0 = res.get("match")
                    res.update(fx)
                    res["match"] = f"{m0}->{fx['match']}"
                else:
                    res["match"] = f"{res.get('match')}|PL_gmina_fill_rejected:{fr['name']}"
            elif fr and fr["place_id"] and (res.get("teryt") in (None, fr["teryt"]) or not fr["teryt"]):
                ad = ADDITIONS.row(fr["place_id"]) or {}
                res.update(place_id=fr["place_id"], qid=fr["place_id"][3:], place_name=ad.get("name_native") or fr["name"],
                           teryt=fr["teryt"] or res.get("teryt"), admin_level="municipality",
                           match=str(res.get("match")) + "->PL_gmina_fill_reviewed")
                if fr.get("is_current") == "False":    # former place (Ostrowice): map to the former place itself
                    res.update(mapped_via="former_place", valid_to=fr.get("valid_to") or None)
            elif fr:
                res["match"] = f"{res.get('match')}|not_in_candidates:{fr.get('suggested_place_key') or fr['name']}"
        if not res.get("place_id") and lvl == "powiat":
            r2 = self.resolve(woj, "Rady Gminy w " + re.sub(r"^.*?\b(?:w|we)\s+", "", o1, flags=re.I), "gmina")
            t7 = r2.get("teryt") or (re.findall(r"'(\d{7})'", str(r2.get("match"))) or [None])[0]
            t4 = None
            if t7 and int(t7[2:4]) < 61:
                t4 = t7[:4]
            elif t7:   # seat is a city county (Kielce): the land powiat seated there has the matching adjective
                seat = fold(self.label.get(t7) or "")
                st = [t for t, a in self._pow_adj_stems(woj).items() if int(t[2:4]) < 61 and seat and cpre(a, seat) >= 4]
                t4 = st[0] if len(st) == 1 else None
            c = self.cand_for_teryt(t4) if t4 else None
            if c:
                res.update(place_id=c["place_id"], qid=c["qid"], place_name=c["place_name"], teryt=t4,
                           admin_level=c["admin_level"], match="powiat_seat->gmina->" + t4 + "->powiaty_csv")
            if not c:   # misspelt adjective in the organ ("Rady Powiatu Stargarodzkiego" = starogardzki)
                import difflib
                m = re.search(r"powiatu\s+(\w+)", fold(o1))
                if m:
                    st = self._pow_adj_stems(woj)
                    sc = sorted(((difflib.SequenceMatcher(None, m.group(1)[:len(a_) + 1], a_).ratio(), t) for t, a_ in st.items()), reverse=True)
                    if sc and sc[0][0] >= 0.8 and (len(sc) == 1 or sc[1][0] < sc[0][0] - 0.1):
                        c = self.cand_for_teryt(sc[0][1])
                        if c:
                            res.update(place_id=c["place_id"], qid=c["qid"], place_name=c["place_name"], teryt=sc[0][1],
                                       admin_level=c["admin_level"], match=f"powiat_adjective_fuzzy({sc[0][0]:.2f})->powiaty_csv")
        return res

    def _resolve_ext(self, woj: str, org: Optional[str], lvl: str, title: str = "", text: str = "", qual: str = "") -> dict:
        """resolve() + (2026-10-17 rematch) nominative names from title/text for unresolved gminas, powiat seat via the
        gmina in the text, and disambiguation of ambiguous gminas by '(powiat X)' qualifiers / 'powiatu X' mentions."""
        res = dict(self.resolve(woj, org, lvl))
        if res.get("place_id"):
            return res
        blob = (title or "") + "\n" + (text or "")[:4000]
        o = " ".join((org or "").split())
        if lvl == "gmina" and str(res.get("match")).startswith("ambiguous"):
            ts = list(dict.fromkeys(re.findall(r"'(\d{7})'", res["match"])))
            res["amb_cands"] = tuple(sorted(ts))
            # (1) longest full name present (Słupia vs Słupia Konecka, Józefów vs Józefów nad Wisłą)
            of = fold(o + " " + (title or "")[:200])
            nm = {t: fold(re.sub(r"^gmina\s+", "", self.label.get(t) or "", flags=re.I)).split() for t in ts}
            fit = [t for t in ts if nm[t] and all(any(cpre(w, x) >= max(3, len(x) - 3) for w in of.split()) for x in nm[t])]
            if fit:
                mx = max(len(nm[t]) for t in fit)
                fit = [t for t in fit if len(nm[t]) == mx]
                if len(fit) < len(ts):
                    ts = fit
            # (2) gmina type from the organ: Rada Gminy/Wójt -> rural (2); Rada Miejska/Miasta/Burmistrz -> 1/3
            if len(ts) > 1:
                if re.search(r"\b(rad\w* gminy|w[óo]jt\w*)\b", o, re.I) and not re.search(r"miejsk|miasta|burmistrz", o, re.I):
                    tt = [t for t in ts if t[-1] == "2"]
                elif re.search(r"miejsk|miasta|burmistrz", o, re.I):
                    tt = [t for t in ts if t[-1] in "13"]
                else:
                    tt = ts
                if tt and len(tt) < len(ts):
                    ts = tt
            if len(ts) == 1:
                c = self.cand_for_teryt(ts[0])
                if c:
                    res.update(place_id=c["place_id"], qid=c["qid"], place_name=c["place_name"], teryt=ts[0],
                               admin_level=c["admin_level"], match="ambiguous->name_or_type->candidate")
                    return res
            blob = (title or "") + "\n" + (text or "")
            stems = self._pow_adj_stems(woj)
            qual = fold(" ".join(re.findall(r"\(([^)]*pow(?:iat|\.)[^)]*)\)", (qual or o) + " " + (title or ""), re.I)))
            words = [fold(w) for w in self.POW_ADJ.findall(blob)] + qual.split()
            hits = {t for t in ts if t[:4] in stems and any(w.startswith(stems[t[:4]]) and len(stems[t[:4]]) >= 4 for w in words)}
            if len(hits) == 1:
                t = hits.pop()
                c = self.cand_for_teryt(t)
                if c:
                    res.update(place_id=c["place_id"], qid=c["qid"], place_name=c["place_name"], teryt=t,
                               admin_level=c["admin_level"], match="ambiguous->powiat_mention->candidate")
            else:
                vt = self.village_vote(ts, blob) if not hits else None
                if vt:
                    c = self.cand_for_teryt(vt[0])
                    if c:
                        res.update(place_id=c["place_id"], qid=c["qid"], place_name=c["place_name"], teryt=vt[0],
                                   admin_level=c["admin_level"], match=f"ambiguous->villages{vt[1]}->candidate")
                        return res
                res["match"] = res["match"] + (f"|powiat_mention:{sorted(hits)}" if hits else "|no_powiat_mention")
            return res
        if lvl == "gmina" and not res.get("teryt"):
            for nm in dict.fromkeys(m.strip() for m in self.NOMIN.findall(blob)):
                r2 = self.resolve(woj, "Rady Gminy " + nm, "gmina")
                if not r2.get("teryt") and re.search(r"miejsk|miasta", o, re.I):
                    r2 = self.resolve(woj, "Rady Miasta " + nm, "gmina")
                if r2.get("place_id"):
                    res.update({k: r2[k] for k in ("place_id", "qid", "place_name", "teryt", "admin_level")},
                               match="text_nominative->" + str(r2["match"]), toponym_text=nm)
                    return res
                if str(r2.get("match")).startswith("ambiguous"):
                    res["match"] = "text_nominative->" + r2["match"]
                    return res
            return res
        if lvl == "powiat" and not res.get("teryt"):
            stems = self._pow_adj_stems(woj)
            words = [fold(w) for w in self.POW_ADJ.findall(blob)]
            hits = {t for t, st in stems.items() if len(st) >= 4 and any(w.startswith(st) for w in words)}
            if len(hits) == 1:
                t = hits.pop()
                c = self.cand_for_teryt(t)
                if c:
                    res.update(place_id=c["place_id"], qid=c["qid"], place_name=c["place_name"], teryt=t,
                               admin_level=c["admin_level"], match="text_powiat_adjective->powiaty_csv")
            else:
                res["match"] = f"powiat_unresolved:{sorted(hits)[:4]}" if hits else "powiat_unresolved"
        return res

    def resolve(self, woj: str, org: Optional[str], lvl: str) -> dict:
        key = (woj, org, lvl)
        if key in self.cache:
            return self.cache[key]
        iso = HOSTS[woj][2]
        res = {"place_id": None, "qid": None, "teryt": None, "level": lvl, "match": None, "place_name": None,
               "admin_level": None, "iso_3166_2": None}
        o = " ".join((org or "").split())
        if lvl in ("voivodeship", "voivode"):
            res.update(place_id=f"iso:{iso}", teryt=iso[3:], match="voivodeship_iso", admin_level="adm1",
                       iso_3166_2=iso, place_name=f"województwo {HOSTS[woj][0]}")
            q = next((qq for qq, r in self.cand.items() if r["iso_3166_2"] == iso and r["admin_level"] in ("voivodeship", "adm1")), None)
            res["qid"] = q
        elif lvl in ("gmina", "powiat"):
            # toponym = text after organ phrase
            m = re.match(r"^\S+\s+(?:(?:gminy|miasta|miejsk\w*|powiatu|dzielnicy)\s*)?(?:i\s+(?:gminy|miasta)\s+)?"
                         r"(?:(?:gminy|miasta)\s+)?(?:st\.\s*|stołecznego\s+|m\.\s*(?:st\.\s*)?)?(?:(?:w|we)\s+)?(.*)$", o, re.I)
            top = fold(m.group(1)) if m else fold(o)
            top = re.sub(r"^(w|we)\s+", "", top)
            for k, v in IRREG.items():
                if top.startswith(k):
                    top = v + top[len(k):]
            res["toponym"] = top
            if lvl == "gmina":
                rural = bool(re.match(r"(rad\w*|wójt\w*) gminy(?! i miasta)", o.lower())) or o.lower().startswith("wójt")
                urban = bool(re.match(r"(rad\w* miasta|rad\w* miejsk|prezydent|burmistrz)", o.lower()))
                best = []
                for f, t, d in self.gminas.get(woj, []):
                    s = word_match(top, f)
                    if s:
                        bonus = (2 if (rural and d in "23") or (urban and d in "13") else 0)
                        best.append((s + bonus, len(f), t))
                if best:
                    best.sort(reverse=True)
                    top_s = best[0][:2]
                    ts = {t for s, l, t in best if (s, l) == top_s}
                    if len({t[:6] for t in ts}) == 1 and len(ts) > 1:   # same gmina, type digit changed over time
                        ts = {max(ts, key=lambda t: t[-1] == "3")}
                    if len(ts) == 1:
                        t = ts.pop()
                        res["teryt"] = t
                        res["match"] = "toponym->teryt"
                    else:
                        res["match"] = f"ambiguous:{sorted(ts)[:4]}"
            else:
                best = []
                for f, t in self.powiats.get(woj, []):
                    s = word_match(top, f)
                    if not s:  # "Rady Powiatu w Starachowicach" -> seat town vs adjective
                        p = cpre(top.split()[0] if top else "", f.split()[0])
                        s = p if p >= max(5, len(f.split()[0]) - 4) else 0
                    if s:
                        best.append((s, t))
                if best:
                    best.sort(reverse=True)
                    ts = {t for s, t in best if s == best[0][0]}
                    if len(ts) == 1:
                        res["teryt"] = ts.pop()
                        res["match"] = "toponym->teryt"
                    else:
                        res["match"] = f"ambiguous:{sorted(ts)[:4]}"
            if res["teryt"]:
                res["place_name"] = self.label.get(res["teryt"])
                qs = self.by_teryt.get(res["teryt"], [])
                res["qid"] = qs[0] if qs else None
                c = self.cand_for_teryt(res["teryt"])
                if c:
                    res.update(place_id=c["place_id"], qid=c["qid"], place_name=c["place_name"] or res["place_name"],
                               admin_level=c["admin_level"],
                               match="toponym->teryt->crosswalk" if c.get("_via") else "toponym->teryt->candidate")
        self.cache[key] = res
        return res


# ----------------------------------------------------------------------------- text
HDR = re.compile(r"^\s*(DZIENNIK URZĘDOWY|WOJEWÓDZTWA\s+\S+\s*$|Dziennik Urzędowy Województwa .*–\s*\d+\s*–\s*Poz\.|"
                 r"Id:\s*[0-9A-F-]{20,}|Strona \d+$|Podpisany\b|Data:\s*\d|Poz\.\s*\d+\s*$)", re.I)


SPLIT6 = re.compile(r" {6,}")
SIG = re.compile(r"^(Podpisany przez:|Elektronicznie podpisany|Data:\s*\d|[A-ZŁŚŻŹĆ][a-ząęółśżźćń]+ [A-ZŁŚŻŹĆ][a-ząęółśżźćń-]+(; \w+)?$)")


def pdf_text(pdf: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".pdf") as tf:
        tf.write(pdf)
        tf.flush()
        return pdf_text_file(tf.name)


def pdf_text_file(path: str) -> str:
    p = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", path, "-"], capture_output=True, timeout=300)
    raw = p.stdout.decode("utf-8", "replace")
    del p
    lines = []
    for page in raw.split("\f"):
        for k, ln in enumerate(page.splitlines()):
            ln = ln.rstrip()
            # drop the e-signature column (far right, first lines of page 1) -- linear split, no regex backtracking
            if k < 15 and "      " in ln:
                parts = SPLIT6.split(ln)
                if len(parts) > 1 and SIG.match(parts[-1].strip()):
                    ln = "      ".join(parts[:-1]).rstrip()
            s = ln.strip()
            if len(s) < 200 and HDR.match(s):
                continue
            lines.append(ln)
    t = "\n".join(lines)
    t = re.sub(r"[ \t]+", " ", t)
    t = t.replace("\n ", "\n")
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def html_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>|</(p|div|li|tr|h\d)>", "\n", html)
    t = re.sub(r"<[^>]+>", " ", html)
    import html as H
    t = H.unescape(t)
    t = re.sub(r"[ \t\xa0]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n\n", t).strip()


def d10(v) -> Optional[str]:
    v = (v or "")[:10]
    return v if re.match(r"^\d{4}-\d{2}-\d{2}$", v) and not v.startswith("0001") else None


# ----------------------------------------------------------------------------- write
_schema = None


def get_schema():
    global _schema
    if _schema is None:
        try:
            import schema as s
            _schema = s
        except Exception as e:  # noqa: BLE001
            log.warning("schema import failed: %s", e)
    return _schema


def atomic_write(path: Path, rows: list[dict], pk: Optional[str] = None) -> None:
    tmp = path.with_name("." + path.name[:-len(".jsonl")] + ".tmp.jsonl")
    with tmp.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    if pk:
        v = get_schema().validate_file(tmp, expect_place_key=pk)
        if not v["ok"]:
            raise RuntimeError(f"validate_file failed {path.name}: {v['errors'][:3]} {v['file_errors']}")
    os.rename(tmp, path)


def flush_utc(woj: str, rows: list[dict]) -> Counter:
    """Write one batch with a UTC-timestamped name (uploader: newer timestamp wins per doc_id). No done-marking."""
    return _flush(woj, rows, None)


def flush(woj: str, bno: int, rows: list[dict], done_f) -> Counter:
    return _flush(woj, rows, done_f)


def _flush(woj: str, rows: list[dict], done_f) -> Counter:
    sch = get_schema()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    tag = f"pldz_{woj}_{ts}p0001"
    while any(PL_DIR.glob(f"*.{tag}.jsonl")) or (UNM_DIR / f"pl_{woj}_unmatched_{ts}p0001.jsonl").exists():
        time.sleep(1.1)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        tag = f"pldz_{woj}_{ts}p0001"
    by: dict[str, list] = defaultdict(list)
    unm = []
    for r in rows:
        (by[r["place_id"]] if r["place_id"] else unm).append(r)
    st = Counter()
    for pid, rs in by.items():
        pk = sch.place_key(pid) if sch else pid.replace(":", "_")
        if sch:
            bad = {r["doc_id"]: e for r in rs for e in [sch.validate_record(r)] if e}
            if bad:
                (OUT / "_invalid").mkdir(exist_ok=True)
                atomic_write(OUT / "_invalid" / f"{pk}.{tag}.jsonl", [dict(r, _errors=bad[r["doc_id"]]) for r in rs if r["doc_id"] in bad])
                log.warning("%s %d invalid rows: %s", pk, len(bad), list(bad.items())[:1])
                rs = [r for r in rs if r["doc_id"] not in bad]
            if not rs:
                continue
        atomic_write(PL_DIR / f"{pk}.{tag}.jsonl", rs, pk if sch else None)
        st["matched"] += len(rs)
    if unm:
        atomic_write(UNM_DIR / f"pl_{woj}_unmatched_{ts}p0001.jsonl", unm)
        st["unmatched"] += len(unm)
    if done_f is not None:
        for r in rows:
            done_f.write(r["doc_id"] + "\n")
        done_f.flush()
        os.fsync(done_f.fileno())
    return st


def build(h: Host, it: dict, org, lvl, pl: dict, text: str, src: str, pdf_meta: dict) -> dict:
    eli = it.get("eli") or it.get("address") or f"{h.pub}/{it['year']}/{it['pos']}"
    act_url = f"{h.base}/api/eli/acts/{eli}"
    # list endpoint: promulgation = act date, announcementDate = publication timestamp
    a, p = d10(it.get("promulgation")), d10(it.get("announcementDate"))
    if a and p and a > p:
        a, p = p, a
    title = " ".join((it.get("title") or "").replace("\xa0", " ").split())
    m = re.search(r"\bnr\.?\s+(\S+)", title[:120], re.I)
    cons = (it.get("type") or "").lower() == "obwieszczenie"
    return {
        "place_id": pl["place_id"], "country_code": "PL", "doc_id": eli, "source_platform": "pl_edziennik",
        "source_url": act_url, "doc_type": "gazette_act", "language": "pl", "title_native": title,
        "number": f"{it.get('displayAddress') or ''}".strip() or eli,
        "adopted_date": a, "published_date": p, "effective_date": None,
        "in_force": (it.get("status") or "").lower() == "obowiązujący" or None,
        "consolidated": bool(cons), "content_format": "pdf_text" if src == "pdf" else "html",
        "text": text, "retrieved_at": utcnow(),
        "place_name": pl["place_name"], "qid": pl["qid"], "iso_3166_2": pl["iso_3166_2"],
        "admin_level": pl["admin_level"] or pl["level"], "platform": "pl_edziennik",
        "platform_place_id": pl["teryt"],
        # extras
        "act_type": it.get("type"), "act_number": m.group(1) if m else None, "status": it.get("status"),
        "issuing_body_name": org, "issuing_body_code": pl["teryt"], "issuing_body_qid": pl["qid"],
        "level": pl["level"], "place_match": pl["match"], "toponym": pl.get("toponym"),
        "voivodeship": h.woj, "journal": h.host, "eli": eli, "display_address": it.get("displayAddress"),
        "pdf_url": f"{act_url}/text.pdf", "html_url": f"{act_url}/text.html", "text_source": src,
        **pdf_meta, "list_meta": {k: v for k, v in it.items() if not k.startswith("_")},
        "withdrawn_date": None, "rights": "official act; not subject to copyright (art. 4 Polish Copyright Act)",
    }


def fetch_host(woj: str, pm: PlaceMap, limit: Optional[int] = None, sample: Optional[int] = None) -> None:
    h = Host(woj)
    cat = STATE / f"catalog_{woj}.jsonl"
    if not cat.exists():
        log.error("%s: no catalog", woj)
        return
    KEEP = ("eli", "address", "publisher", "year", "pos", "type", "title", "status", "displayAddress",
            "promulgation", "announcementDate", "changeDate")
    seen: set = set()
    sel = []
    why = Counter()
    n_cat = 0
    for ln in cat.open(encoding="utf-8"):
        it = json.loads(ln)
        eli = it.get("eli") or f"{h.pub}/{it['year']}/{it['pos']}"
        if eli in seen:
            continue
        seen.add(eli)
        n_cat += 1
        ok, reason, org, lvl = in_pass1(it)
        why[reason] += 1
        if ok:
            it = {k: it.get(k) for k in KEEP}
            it["eli"] = eli
            # compact: store the item as a JSON string (dicts cost ~4x more RAM; box memory is shared)
            sel.append((-int(it["year"] or 0), -int(it["pos"] or 0), eli, json.dumps(it, ensure_ascii=False), org, lvl))
    del seen
    items = range(n_cat)  # only len() is used below
    sel.sort(key=lambda x: (x[0], x[1]))
    sfx = "" if sample is None else "_test"
    done_p = STATE / f"done_{woj}{sfx}.txt"
    done = set(done_p.read_text().split()) if done_p.exists() else set()
    bno_p = STATE / f"batchno_{woj}{sfx}.txt"
    bno = int(bno_p.read_text()) if bno_p.exists() else 0
    n_sel = len(sel)
    todo = [x for x in sel if x[2] not in done]
    del sel
    if sample:
        random.seed(11)
        todo = random.sample(todo, min(sample, len(todo)))
    if limit:
        todo = todo[:limit]
    log.info("%s fetch: catalog=%d pass1=%d (filter %s) done=%d todo=%d", woj, len(items), n_sel, dict(why), len(done), len(todo))
    (STATE / f"scope_{woj}.json").write_text(json.dumps({"catalog": len(items), "pass1": n_sel, "filter": why}, default=dict))
    rows: list[dict] = []
    t0 = time.time()
    with done_p.open("a", encoding="utf-8") as df, (STATE / f"failed_{woj}.jsonl").open("a", encoding="utf-8") as ff:
        for i, (_, _, eli, it_js, org, lvl) in enumerate(todo, 1):
            it = json.loads(it_js)
            try:
                pl = pm.resolve(woj, org, lvl)
                text, src, meta = "", "pdf", {}
                try:
                    r = h.get(f"/api/eli/acts/{eli}/text.pdf", stream=True)
                    buf = bytearray()
                    clen = int(r.headers.get("Content-Length") or 0)
                    if clen > MAX_PDF:  # don't pull huge map-PDFs just to discard them
                        r.close()
                        raise requests.HTTPError(f"pdf too large ({clen} bytes), skipped")
                    for chunk in r.iter_content(65536):
                        buf.extend(chunk)
                        if len(buf) > MAX_PDF:
                            break
                    r.close()
                    meta = {"pdf_bytes": len(buf), "pdf_sha256": hashlib.sha256(buf).hexdigest(),
                            "pdf_truncated": len(buf) > MAX_PDF}
                    if not meta["pdf_truncated"] and buf[:4] == b"%PDF":
                        text = pdf_text(bytes(buf))
                except requests.HTTPError as e:
                    meta = {"pdf_error": str(e)[:200]}
                if len(text) < 200:
                    try:
                        hr = h.get(f"/api/eli/acts/{eli}/text.html", retries=3)
                        ht = html_text(hr.text)
                        if len(ht) > len(text):
                            text, src = ht, "html_first_page_only"
                    except Exception as e:  # noqa: BLE001
                        meta["html_error"] = str(e)[:200]
                if not text.strip():
                    raise RuntimeError("no text (scanned PDF without text layer?)")
                rows.append(build(h, it, org, lvl, pl, text, src, meta))
            except Exception as e:  # noqa: BLE001
                log.warning("%s FAIL %s: %s", woj, eli, str(e)[:300])
                ff.write(json.dumps({"eli": eli, "error": str(e)[:500], "at": utcnow()}, ensure_ascii=False) + "\n")
                ff.flush()
            if len(rows) >= BATCH_DOCS or (i == len(todo) and rows):
                bno += 1
                st = flush(woj, bno, rows, df) if not sample else flush_test(woj, rows)
                bno_p.write_text(str(bno))
                rows = []
                rate = i / max(time.time() - t0, 1)
                log.info("%s batch %05d matched=%d unmatched=%d | %d/%d (%.2f doc/s, ETA %.1fh)", woj, bno,
                         st["matched"], st["unmatched"], i, len(todo), rate, (len(todo) - i) / rate / 3600)
    log.info("%s fetch finished", woj)


def flush_test(woj, rows):
    d = OUT / "_test_pl"
    d.mkdir(exist_ok=True)
    p = d / f"test_{woj}.jsonl"
    with p.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return Counter(matched=sum(1 for r in rows if r["place_id"]), unmatched=sum(1 for r in rows if not r["place_id"]))


def run_host(woj: str, pm: PlaceMap, do_cat: bool, do_fetch: bool, limit=None, sample=None) -> None:
    threading.current_thread().name = woj
    for attempt in range(48 if do_cat else 1):
        try:
            if do_cat:
                if catalog_host(woj) is None:
                    log.info("%s blocked; re-probe in 1h (attempt %d/48)", woj, attempt + 1)
                    time.sleep(3600)
                    continue
            if do_fetch:
                fetch_host(woj, pm, limit, sample)
            return
        except Exception as e:  # noqa: BLE001
            log.exception("%s crashed: %s; retry in 10 min", woj, e)
            time.sleep(600)


def status() -> None:
    tot = Counter()
    places, unm = Counter(), Counter()
    for p in PL_DIR.glob("*.pldz_*.jsonl"):
        for l in p.open(encoding="utf-8"):
            r = json.loads(l)
            places[r["place_id"]] += 1
    for p in UNM_DIR.glob("pl_*_unmatched_*.jsonl"):
        for l in p.open(encoding="utf-8"):
            r = json.loads(l)
            unm[(r["voivodeship"], r["level"], r["issuing_body_name"])] += 1
    for woj in HOSTS:
        sp = STATE / f"catalog_{woj}.state.json"
        sc = STATE / f"scope_{woj}.json"
        dp = STATE / f"done_{woj}.txt"
        st = json.loads(sp.read_text()) if sp.exists() else {}
        scope = json.loads(sc.read_text()) if sc.exists() else {}
        nd = len(dp.read_text().split()) if dp.exists() else 0
        print(f"{woj} {HOSTS[woj][1]:35s} blocked={bool(st.get('blocked'))} years={len(st.get('years_done', {}))} "
              f"catalog={scope.get('catalog')} pass1={scope.get('pass1')} done={nd}")
        tot["pass1"] += scope.get("pass1") or 0
        tot["catalog"] += scope.get("catalog") or 0
        tot["done"] += nd
    print("TOTAL", dict(tot))
    print(f"matched docs={sum(places.values())} distinct places={len(places)}; unmatched docs={sum(unm.values())} distinct bodies={len(unm)}")
    print("unmatched by level:", Counter(k[1] for k in unm for _ in range(unm[k])))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["catalog", "fetch", "all", "status"])
    ap.add_argument("--woj", nargs="*", default=list(HOSTS))
    ap.add_argument("--limit", type=int)
    ap.add_argument("--test", type=int, help="random N pass-1 docs per host into staging/eu/_test_pl/")
    a = ap.parse_args()
    setup_logging()
    if a.cmd == "status":
        return status()
    log.info("start %s woj=%s pid=%d", a.cmd, a.woj, os.getpid())
    pm = PlaceMap() if a.cmd in ("fetch", "all") else None
    ths = [threading.Thread(target=run_host, name=w, args=(w, pm, a.cmd in ("catalog", "all"), a.cmd in ("fetch", "all"),
                                                             a.limit, a.test)) for w in a.woj]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    log.info("all hosts finished")


if __name__ == "__main__":
    main()
