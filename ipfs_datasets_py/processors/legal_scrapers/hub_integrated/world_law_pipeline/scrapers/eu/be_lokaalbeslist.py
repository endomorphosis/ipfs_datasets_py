#!/usr/bin/env python3
"""Flanders (BE): Lokaal Beslist public harvester SPARQL endpoints - municipal regulations (reglementen/verordeningen).

Endpoints (public, read-only SPARQL; robots.txt of the hosts serve the app shell = no rules):
  https://lokaalbeslist-harvester-{0,1,2,3}.s.redhost.be/sparql   besluit:Besluit with eli:title / prov:value / eli:passed_by
  https://centrale-vindplaats.lblod.info/sparql                     bestuursorgaan -> bestuurseenheid (label, classificatie)
Scope: besluiten whose eli:title contains "reglement" or "verordening" (incl. aanvullende verkeersreglementen,
belasting-/retributiereglementen, politieverordeningen) and that carry decision text (prov:value).
Polite: one query at a time, >= 3 s between queries, paged (keyset on ?r).
Usage: python3 be_lokaalbeslist.py orgs | catalog | fetch [--limit N] [--test N] | all | status
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
import time
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.live import STAGE, Done, PoliteSession, Stager, get_logger, utcnow  # noqa: E402
from common.xwalk import ADDITIONS, SUCCESSORS, denied  # noqa: E402

HARVESTERS = [f"https://lokaalbeslist-harvester-{i}.s.redhost.be/sparql" for i in range(4)]
CV = "https://centrale-vindplaats.lblod.info/sparql"
STATE = STAGE / "_state" / "be_lb"
CAND = Path((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + "/global_municipalities_candidate.csv"))
log = get_logger("be_lokaalbeslist")
PFX = """PREFIX besluit: <http://data.vlaanderen.be/ns/besluit#> PREFIX eli: <http://data.europa.eu/eli/ontology#>
PREFIX prov: <http://www.w3.org/ns/prov#> PREFIX mandaat: <http://data.vlaanderen.be/ns/mandaat#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#> PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> """
PAGE = 2000
VALUES_BATCH = 10          # was 25: smaller VALUES lists per POST
POST_READ_TIMEOUT = 180    # was 600
POST_TRIES = 3             # was 6; a harvester that fails a batch after 3 tries is parked (see Health)
HEALTH = STATE / "harvester_health.json"
DOWN_STEPS_H = [1, 2]          # parking time after consecutive failures (hours); capped at 2 h (2026-10-13)
MAX_PARK_S = 2 * 3600
HEARTBEAT_S = 1800
EXONYM = {"antwerpen": "antwerp", "gent": "ghent", "brugge": "bruges", "oostende": "ostend", "brussel": "brussels",
          "leuven": "leuven", "mechelen": "mechelen", "kortrijk": "kortrijk", "ieper": "ypres"}
P_TITLE = "http://data.europa.eu/eli/ontology#title"
P_DESC = "http://data.europa.eu/eli/ontology#description"
P_VAL = "http://www.w3.org/ns/prov#value"
P_PB = "http://data.europa.eu/eli/ontology#passed_by"
P_SRC = "http://www.w3.org/ns/prov#wasDerivedFrom"
P_PUB = "http://data.europa.eu/eli/ontology#date_publication"
P_MOT = "http://data.vlaanderen.be/ns/besluit#motivering"


def fold(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


class Sparql:
    def __init__(self):
        self.sess = PoliteSession(log, min_interval=3.0, headers={"Accept": "application/sparql-results+json"})

    def q(self, endpoint, query):
        """Short queries: PoliteSession.get (robots + backoff). Long VALUES queries (HTTP 431 on GET): form POST
        with the same robots check, >= 3 s spacing and exponential backoff."""
        if len(query) < 1500:
            return self.sess.get(endpoint, params={"query": PFX + query}).json()["results"]["bindings"]
        if not self.sess.robots.can_fetch(endpoint):
            raise PermissionError(f"robots.txt disallows {endpoint}")
        import time
        for a in range(POST_TRIES):
            w = 3.0 - (time.monotonic() - self.sess.last.get(endpoint.split("/")[2], 0))
            if w > 0:
                time.sleep(w)
            self.sess.last[endpoint.split("/")[2]] = time.monotonic()
            try:
                r = self.sess.s.post(endpoint, data={"query": PFX + query}, timeout=(20, POST_READ_TIMEOUT))
                if r.status_code == 200:
                    return r.json()["results"]["bindings"]
                err = f"HTTP {r.status_code}"
            except Exception as e:  # noqa: BLE001
                err = str(e)[:200]
            log.warning("POST retry %d/%d %s", a + 1, POST_TRIES, err)
            time.sleep(min(30 * 2 ** a, 600))
        raise RuntimeError(f"SPARQL POST failed: {err}")


class Health:
    """Per-harvester circuit breaker persisted in _state/be_lb/harvester_health.json.
    A harvester is probed with a trivial ASK (60 s) before use; a failed probe or a failed batch parks it for
    1/3/6/12 h (escalating); it is logged to _logs/blocked_sources.jsonl as temporarily_down."""

    def __init__(self, sp):
        self.sp = sp
        self.st = json.loads(HEALTH.read_text()) if HEALTH.exists() else {}
        for v in self.st.values():      # old 6-12 h parks: clamp to the 2 h cap
            if isinstance(v, dict) and float(v.get("until", 0)) > time.time() + MAX_PARK_S:
                v["until"] = time.time() + MAX_PARK_S

    def save(self):
        HEALTH.write_text(json.dumps(self.st, indent=1))

    def parked_until(self, h):
        return float(self.st.get(str(h), {}).get("until", 0))

    def probe(self, h):
        import time
        ep = HARVESTERS[h]
        t0 = time.time()
        try:
            r = self.sp.sess.s.get(ep, params={"query": "ASK { ?s ?p ?o }"}, timeout=(20, 60))
            ok = r.status_code == 200 and '"boolean"' in r.text
            why = f"HTTP {r.status_code}"
        except Exception as e:  # noqa: BLE001
            ok, why = False, str(e)[:120]
        log.info("health h%d ASK -> %s (%s, %.1fs)", h, "up" if ok else "DOWN", why, time.time() - t0)
        if ok:
            self.st[str(h)] = {"until": 0, "fails": 0, "last_ok": utcnow()}
            self.save()
        else:
            self.park(h, f"ASK probe failed: {why}")
        return ok

    def park(self, h, why):
        import time
        e = self.st.get(str(h), {})
        fails = int(e.get("fails", 0)) + 1
        hrs = DOWN_STEPS_H[min(fails, len(DOWN_STEPS_H)) - 1]
        until = time.time() + hrs * 3600
        self.st[str(h)] = {"until": until, "fails": fails, "why": why, "since": e.get("since") or utcnow(),
                           "until_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(until))}
        self.save()
        log.warning("harvester h%d parked for %dh (fail #%d): %s", h, hrs, fails, why)
        with (STAGE / "_logs" / "blocked_sources.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"source": f"be_lokaalbeslist:h{h}", "endpoint": HARVESTERS[h], "status": "temporarily_down",
                                "reason": why, "retry_after_utc": self.st[str(h)]["until_utc"], "at": utcnow()}) + "\n")


def v(b, k):
    return b[k]["value"] if k in b else None


def orgs(sp):
    STATE.mkdir(parents=True, exist_ok=True)
    out, last = {}, ""
    while True:
        rows = sp.q(CV, f"""SELECT ?o ?eh ?lab ?cl ?wg WHERE {{ ?o a besluit:Bestuursorgaan .
            OPTIONAL{{?o mandaat:isTijdspecialisatieVan ?o2}} BIND(COALESCE(?o2,?o) AS ?ob) ?ob besluit:bestuurt ?eh .
            ?eh skos:prefLabel ?lab . OPTIONAL{{?eh besluit:classificatie/skos:prefLabel ?cl}}
            OPTIONAL{{?eh besluit:werkingsgebied/rdfs:label ?wg}} FILTER(STR(?o) > "{last}") }} ORDER BY ?o LIMIT 5000""")
        if not rows:
            break
        for b in rows:
            out.setdefault(v(b, "o"), {"eh": v(b, "eh"), "label": v(b, "lab"), "class": v(b, "cl"), "wg": v(b, "wg")})
        last = v(rows[-1], "o")
        log.info("orgs: %d", len(out))
        if len(rows) < 5000:
            break
    (STATE / "orgs.json").write_text(json.dumps(out, ensure_ascii=False))
    return len(out)


def catalog(sp):
    STATE.mkdir(parents=True, exist_ok=True)
    stp = STATE / "catalog.state.json"
    st = json.loads(stp.read_text()) if stp.exists() else {"h": 0, "last": "", "rows": 0}
    with (STATE / "catalog.jsonl").open("a", encoding="utf-8") as f:
        while st["h"] < len(HARVESTERS):
            ep = HARVESTERS[st["h"]]
            rows = sp.q(ep, f"""SELECT DISTINCT ?r WHERE {{ ?r a besluit:Besluit ; eli:title ?t ; prov:value ?v .
                FILTER(CONTAINS(LCASE(STR(?t)),"reglement") || CONTAINS(LCASE(STR(?t)),"verordening"))
                FILTER(STR(?r) > "{st['last']}") }} ORDER BY ?r LIMIT {PAGE}""")
            for b in rows:
                f.write(json.dumps({"r": v(b, "r"), "h": st["h"]}) + "\n")
            f.flush()
            st["rows"] += len(rows)
            if len(rows) < PAGE:
                log.info("harvester %d done", st["h"])
                st.update(h=st["h"] + 1, last="")
            else:
                st["last"] = v(rows[-1], "r")
            stp.write_text(json.dumps(st))
            log.info("catalog h%d +%d (total %d)", st["h"], len(rows), st["rows"])
    st["complete"] = True
    stp.write_text(json.dumps(st))


class Places:
    def __init__(self):
        self.by = {}
        for r in csv.DictReader(CAND.open(encoding="utf-8")):
            if r["country_code"] == "BE" and r["admin_level"] == "municipality":
                self.by.setdefault(fold(r["place_name"]), r)
                # candidate rows whose place_name is non-Latin (Борнем, Зотегем, וילון): fold() empties them, so also
                # key them by their official-site domain label (bornem.be -> bornem) -- fix 2026-10-12 (Bornem NIS 12007)
                if re.search(r"[^\x00-\u024f]", r["place_name"] or "") and r.get("source_url"):
                    lab = re.sub(r"^www\.", "", urlparse(r["source_url"]).netloc.lower()).split(".")[0]
                    if lab:
                        self.by.setdefault(fold(lab), r)
        p = STATE / "orgs.json"
        self.orgs = json.loads(p.read_text()) if p.exists() else {}
        self.toks = sorted(self.by, key=len, reverse=True)

    def cand(self, name):
        k = fold(name)
        c = self.by.get(EXONYM.get(k, k)) or self.by.get(k)
        return None if (c and denied(c["place_id"])) else c

    def _place(self, pid):
        if not hasattr(self, "by_pid"):
            self.by_pid = {}
            for r in csv.DictReader(CAND.open(encoding="utf-8")):
                if r["country_code"] == "BE":
                    self.by_pid.setdefault(r["place_id"], r)
        r = self.by_pid.get(pid)
        if r:
            return r
        a = ADDITIONS.row(pid)
        return dict(a, place_name=a["name"]) if a else None

    def by_name(self, name, res, via):
        """candidate (denylist applied) -> place_successors.csv (single successor only). Fills res; True if mapped."""
        c = self.cand(name)
        if c:
            res.update(place_id=c["place_id"], qid=c["qid"], place_name=c["place_name"], match=f"{via}->candidate")
            return True
        sc = SUCCESSORS.lookup("BE", name=name)
        if sc["status"] == "ok" and not denied(sc["place_id"]):
            t = self._place(sc["place_id"]) or {}
            res.update(place_id=sc["place_id"], qid=t.get("qid") or sc["place_id"][3:],
                       place_name=t.get("place_name") or sc["successor_name"], match=f"{via}->successor",
                       mapped_via="successor", former_name=sc["old_name"], former_code=sc["old_code"],
                       dissolved_date=sc["dissolved_date"], nis=sc.get("successor_code"))
            return True
        if sc["status"] == "ambiguous":
            res["successor_candidates"] = sc["candidates"]
            res["match"] = f"{via}->successor_ambiguous"
        return False

    def resolve(self, pb, urls) -> dict:
        res = dict(place_id=None, qid=None, place_name=None, match=None, body=None, body_class=None)
        o = self.orgs.get(pb or "")
        if o:
            res.update(body=o["label"], body_class=o["class"])
            if (o["class"] or "") in ("Gemeente", "OCMW"):
                if self.by_name(o["wg"] or o["label"], res, "passed_by->eenheid"):
                    return res
                res["match"] = res["match"] or "eenheid_not_in_candidate"
                return res
            res["match"] = f"non_municipal:{o['class']}"
            return res
        for u in urls:   # fallback: gelinkt-notuleren path /<Bestuurseenheid>/<Gemeente|OCMW>/...
            m = re.match(r"https?://publicatie\.gelinkt-notuleren\.vlaanderen\.be/([^/]+)/(Gemeente|OCMW)/", u or "")
            if m:
                from urllib.parse import unquote
                if self.by_name(unquote(m.group(1)), res, "source_path"):
                    return res
        for u in urls:   # fallback: publication host (besluitvorming.leuven.be, gemeente.meetingburger.net, x-echo.cipalschaubroeck.be)
            host = urlparse(u or "").hostname or ""
            parts = [p for p in re.split(r"[.\-]", host) if p not in ("www", "be", "net", "com", "besluitvorming", "echo",
                                                                        "cipalschaubroeck", "meetingburger", "id", "lblod",
                                                                        "info", "data", "gemeente", "stad", "ebesluit",
                                                                        "raadpleegomgeving", "besluiten", "publicatie",
                                                                        "raadpleeg", "onlinesmartcities", "csecho")]
            for n in (5, 4, 3, 2, 1):   # 4-5 tokens: heist-op-den-berg; by_name also applies 2025 merger successors
                for i in range(len(parts) - n + 1):
                    r2 = dict(res)
                    if self.by_name("-".join(parts[i:i + n]), r2, "source_host"):
                        res.update(r2)
                        return res
        res["match"] = "unresolved"
        return res


def clean(s):
    s = htmlmod.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    s = re.sub(r"[ \t\u00a0]+", " ", s)
    s = re.sub(r" *\n *", "\n", s)
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def art_no(t):
    m = re.search(r"Artikel\s+(\d+)", t[:200])
    return int(m.group(1)) if m else 10 ** 6


def doc_type(t):
    t = t.lower()
    if "aanvullend reglement" in t or "verkeer" in t:
        return "traffic_regulation"
    if "belasting" in t or "retributie" in t:
        return "tax_regulation"
    if "politie" in t:
        return "police_ordinance"
    return "regulation"


def fetch(sp, limit=None, test=None):
    done = Done(STATE / ("done_test.sqlite" if test else "done.sqlite"))
    pm = Places()
    stg = Stager("BE", "belb", log, max_docs=400, stage=(STAGE / "_test_be") if test else STAGE)
    stg.graceful(done)
    cat = STATE / "catalog.jsonl"
    lines = random.Random(11).sample(cat.read_text().splitlines(), test) if test else cat.open()
    batch, n = [], 0

    def run(batch):
        by_h = {}
        for a in batch:
            by_h.setdefault(a["h"], []).append(a["r"])
        for h, rs in by_h.items():
            vals = " ".join(f"<{r}>" for r in rs)
            rows = sp.q(HARVESTERS[h], f"""SELECT ?r ?p ?o WHERE {{ VALUES ?r {{ {vals} }} ?r ?p ?o .
                FILTER(?p IN (eli:title, eli:description, prov:value, eli:passed_by, prov:wasDerivedFrom, eli:date_publication,
                besluit:motivering)) }}""")
            got = {}
            for b in rows:
                got.setdefault(v(b, "r"), {}).setdefault(v(b, "p"), []).append(v(b, "o"))
            for r in rs:
                d = got.get(r)
                if not d or not d.get(P_VAL):
                    stg.add(None, r, "no_text")
                    continue
                title = clean((d.get(P_TITLE) or [""])[0])
                parts = sorted({clean(x) for x in d[P_VAL] if clean(x)}, key=art_no)
                desc = clean((d.get(P_DESC) or [""])[0])
                text = "\n\n".join([title] + ([desc] if desc else []) + parts)
                src = (d.get(P_SRC) or [None])[0]
                pl = pm.resolve((d.get(P_PB) or [None])[0], [src, r])
                if pl["match"] and pl["match"].startswith("non_municipal"):
                    stg.add(None, r, "non_municipal")
                    continue
                uid = r.rstrip("/").rsplit("/", 1)[-1]
                pub = (d.get(P_PUB) or [None])[0]
                stg.add({
                    "place_id": pl["place_id"], "country_code": "BE", "doc_id": f"be_lb:{uid}",
                    "source_platform": "be_lokaalbeslist", "source_url": src or r, "doc_type": "regulation", "regulation_kind": doc_type(title),
                    "language": "nl", "title_native": title, "number": uid, "adopted_date": None,
                    "published_date": pub[:10] if pub and re.match(r"\d{4}-\d\d-\d\d", pub) else None,
                    "effective_date": None, "in_force": None, "consolidated": False, "content_format": "html",
                    "text": text, "retrieved_at": utcnow(), "place_name": pl["place_name"], "qid": pl["qid"],
                    "iso_3166_2": "BE-VLG", "admin_level": "municipality", "platform": "lokaalbeslist",
                    "platform_place_id": None, "issuing_body_name": pl["body"], "issuing_body_class": pl["body_class"],
                    "level": "municipality", "place_match": pl["match"], "besluit_uri": r,
                    **{k: pl[k] for k in ("mapped_via", "former_name", "former_code", "dissolved_date", "successor_candidates", "nis") if pl.get(k)},
                    "sparql_endpoint": HARVESTERS[h],
                    "rights": "official decision; Flemish open data (Modellicentie Gratis Hergebruik / CC0 LBLOD)",
                }, r)

    if test:
        for ln in lines:
            a = json.loads(ln)
            if not done.has(a["r"]):
                batch.append(a)
            if len(batch) >= VALUES_BATCH:
                run(batch)
                batch = []
        if batch:
            run(batch)
        if stg.keys:
            log.info("flush %s | done %d", dict(stg.flush(done)), done.count())
        log.info("fetch finished: %s places=%d", dict(stg.total), len(stg.places))
        return
    import time
    hl = Health(sp)
    finished = set()
    while len(finished) < len(HARVESTERS):
        progressed = False
        for h in range(len(HARVESTERS)):
            if h in finished or time.time() < hl.parked_until(h):
                continue
            # anything left for this harvester? (streamed; the catalog is never held in memory)
            if not any(json.loads(ln)["h"] == h and not done.has(json.loads(ln)["r"]) for ln in cat.open()):
                finished.add(h)
                continue
            if not hl.probe(h):
                continue
            fails_in_row = 0
            for ln in cat.open():
                a = json.loads(ln)
                if a["h"] != h or done.has(a["r"]):
                    continue
                if limit and n >= limit:
                    break
                n += 1
                batch.append(a)
                if len(batch) >= VALUES_BATCH:
                    try:
                        run(batch)
                        fails_in_row = 0
                        progressed = True
                    except Exception as e:  # noqa: BLE001
                        fails_in_row += 1
                        log.warning("batch FAIL h%d (%d in a row): %s", h, fails_in_row, str(e)[:200])
                    batch = []
                    if stg.due():
                        log.info("flush %s | done %d", dict(stg.flush(done)), done.count())
                        gc.collect()
                    if fails_in_row >= 2:
                        hl.park(h, "2 consecutive batch failures (HTTP 5xx / timeouts)")
                        break
            else:
                if batch:
                    try:
                        run(batch)
                    except Exception as e:  # noqa: BLE001
                        log.warning("batch FAIL h%d: %s", h, str(e)[:200])
                finished.add(h)
            batch = []
            if stg.keys:
                log.info("flush %s | done %d", dict(stg.flush(done)), done.count())
            if limit and n >= limit:
                return
        if len(finished) < len(HARVESTERS) and not progressed:
            wake = min(hl.parked_until(h) for h in range(len(HARVESTERS)) if h not in finished)
            nap = max(300, min(wake - time.time(), MAX_PARK_S))
            log.warning("all remaining harvesters parked %s; sleeping %.1fh (temporarily down)",
                        sorted(set(range(len(HARVESTERS))) - finished), nap / 3600)
            if stg.keys:
                log.info("flush %s | done %d", dict(stg.flush(done)), done.count())
            wall_sleep(nap, "harvesters parked " + str(sorted(set(range(len(HARVESTERS))) - finished)))
    log.info("fetch finished: %s places=%d", dict(stg.total), len(stg.places))


def wall_sleep(secs, why):
    """Sleep until a wall-clock deadline in <= 60 s chunks (a box suspend cannot stretch it; time.sleep does not count
    suspended time), heartbeat every 30 min, exit cleanly on SIGTERM."""
    from common import live
    end = time.time() + secs
    hb = time.time()
    while True:
        left = end - time.time()
        if left <= 0:
            return
        if live._STOP[0]:
            log.info("SIGTERM while sleeping: exiting (resume with the same command)")
            sys.exit(0)
        time.sleep(min(60, left))
        if time.time() - hb >= HEARTBEAT_S:
            hb = time.time()
            log.info("heartbeat: sleeping (%s), wake at %s", why, time.strftime("%H:%M %Z", time.localtime(end)))


def status():
    stp = STATE / "catalog.state.json"
    print("catalog", json.loads(stp.read_text()) if stp.exists() else {}, "done", Done(STATE / "done.sqlite").count())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["orgs", "catalog", "fetch", "all", "status"])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--test", type=int)
    a = ap.parse_args()
    if a.cmd == "status":
        return status()
    sp = Sparql()
    if a.cmd == "orgs" or (a.cmd == "all" and not (STATE / "orgs.json").exists()):
        orgs(sp)
    stp = STATE / "catalog.state.json"
    if a.cmd == "catalog" or (a.cmd == "all" and not (stp.exists() and json.loads(stp.read_text()).get("complete"))):
        catalog(sp)
    if a.cmd in ("fetch", "all"):
        fetch(sp, a.limit, a.test)


if __name__ == "__main__":
    main()
