#!/usr/bin/env python3
"""Spain provincial / uniprovincial official gazettes (BOP, BOCM, ...) -> municipal ordinances & regulations.

Targets anuncios of the "Administración Local / Ayuntamientos" sections whose title mentions an ordenanza,
reglamento, normas reguladoras or estatutos (incl. modifications / approvals), attributed to the issuing
ayuntamiento (name + province -> INE (Wikidata P772) -> place_id). Gazette notices: consolidated=false.

Politeness: every host's robots.txt is checked with the RFC 9309 matcher (common/rfc9309.py) before each URL;
unreachable / 5xx robots.txt -> gazette skipped; Crawl-delay honoured (min 1 s/host); identifying UA.
Resumable: per-gazette cursor + done-ids in staging/asia_latam/_state/es_bop/<gazette>.json, updated only after
the staged batch files are renamed. Output: SCHEMA.md v1 jsonl in staging/asia_latam/ES/ (dot-tmp, fsync,
validate_file, rename); unmatched docs -> staging/asia_latam/_unmatched/ES/ + _unmatched_es_bop.csv.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import argparse, csv, hashlib, json, logging, os, re, subprocess, sys, tempfile, threading, time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
import html as html_lib
import requests
from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/pipeline"))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import schema as S  # noqa: E402
from common.rfc9309 import Robots  # noqa: E402
from common import robots_policy as RP  # noqa: E402  (RESPECT_ROBOTS switch, owner policy 2026-11-01)
from es_places import Resolver  # noqa: E402

STAGE = Path((_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/staging/asia_latam"))
OUT, UNM, QUAR = STAGE / "ES", STAGE / "_unmatched" / "ES", STAGE / "_quarantine" / "ES"
STATE, ROBOTS_DIR = STAGE / "_state" / "es_bop", STAGE / "_robots"
UA = "JusticeDAO-WorldLaw/1.0 (+https://github.com/endomorphosis/ipfs_datasets_py; municipal law research crawler; polite)"
log = logging.getLogger("es_bop")
TARGET_RE = re.compile(r"\b(ordenan[cz]a|reglament|regulamento|erregelamendu|normas? reguladoras?|normes? reguladores?|ordenança|ordenantza|ordenanza)", re.I)
EXCLUDE_RE = re.compile(r"\b(padr[oó]n|padr[oó]|convocatoria|bases (espec|gener)|oferta de empleo|licitaci|contrataci|subvenci)", re.I)


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Blocked(Exception):
    pass


class DayUnavailable(IOError):
    """The bulletin service answered 200 with a body that is not a sumario (error/maintenance page). Retried quickly,
    then the day is recorded in st['error_days'] + _logs/_skipped_days_es_bop.csv and re-tried at the next run start."""


class CaptchaChallenge(Exception):
    """Bot-protection challenge (e.g. Radware/ShieldSquare captcha page) instead of content. Never solved or worked around:
    the day is recorded as an error day, we cool down, and after repeated challenges the gazette pauses (status error,
    resumes from its checkpoint on the next launch; error days are re-tried at run start)."""


def log_skipped_day(key, day, err):
    p = STAGE / "_logs" / "_skipped_days_es_bop.csv"
    new = not p.exists()
    with open(p, "a", encoding="utf8") as fh:
        if new:
            fh.write("logged_at,gazette,day,error\n")
        fh.write(f"{datetime.now():%Y-%m-%d %H:%M:%S},{key},{day},\"{str(err).replace(chr(34), chr(39))}\"\n")


class Fetcher:
    """One fetcher per gazette host family; robots + crawl-delay per host."""
    def __init__(self, min_interval=1.0):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "es,ca;q=0.8,en;q=0.5"})
        self.robots, self.next, self.min = {}, {}, min_interval
        self.nreq = 0
        self.last_status = None

    def _robots(self, url):
        p = urlparse(url)
        key = f"{p.scheme}://{p.netloc}"
        if key not in self.robots:
            try:
                r = self.s.get(key + "/robots.txt", timeout=25)
                self.nreq += 1
            except requests.RequestException as e:
                self.robots[key] = self._unreach(p.netloc, f"robots_unreachable: {type(e).__name__}")
                return self.robots[key]
            if r.status_code >= 500:
                self.robots[key] = self._unreach(p.netloc, f"robots_unreachable: HTTP {r.status_code}")
            elif r.status_code >= 400 or "<html" in r.text[:600].lower():
                self.robots[key] = (Robots(allow_all=True), None)
            else:
                ROBOTS_DIR.mkdir(parents=True, exist_ok=True)
                (ROBOTS_DIR / f"{p.netloc}.txt").write_text(r.text)
                self.robots[key] = (Robots(r.text), None)
        return self.robots[key]

    @staticmethod
    def _unreach(host, err):
        """robots.txt unreachable/5xx: skip under RESPECT_ROBOTS; otherwise (owner policy) proceed - min interval
        still applies - and tag the host's records (robots_policy.TAG)."""
        if RP.RESPECT:
            return ("unreachable", err)
        RP.note_host(host, err)
        return (Robots(allow_all=True), None)

    def allowed(self, url):
        rb, err = self._robots(url)
        if rb == "unreachable":
            return False, err
        return (True, None) if rb.can_fetch(UA, url) else (False, f"robots_disallow: {urlparse(url).path}")

    def get(self, url, tries=3):
        ok, why = self.allowed(url)
        if not ok:
            raise Blocked(why)
        host = urlparse(url).netloc
        rb = self.robots[f"{urlparse(url).scheme}://{host}"][0]
        interval = max(self.min, rb.crawl_delay(UA) or 0)
        last = None
        for i in range(tries):
            d = self.next.get(host, 0) - time.time()
            if d > 0:
                time.sleep(d)
            self.next[host] = time.time() + interval
            try:
                r = self._get_follow(url)
                self.last_status = r.status_code
                if r.status_code in (429, 503):
                    last = f"HTTP {r.status_code}"; time.sleep(60 * (i + 1)); continue
                return r
            except requests.RequestException as e:
                last = type(e).__name__; time.sleep(10 * (i + 1))
        raise IOError(f"{url}: {last}")

    def _get_follow(self, url, hops=5):
        cur = url
        for _ in range(hops + 1):
            r = self.s.get(cur, timeout=60, allow_redirects=False)
            self.nreq += 1
            loc = r.headers.get("location")
            if r.status_code in (301, 302, 303, 307, 308) and loc:
                nxt = urljoin(cur, loc)
                ok, why = self.allowed(nxt)
                if not ok:
                    raise Blocked(f"redirect to {nxt}: {why}")
                if RP.ignored(nxt) and not RP.ignored(url):      # disallowed redirect target -> tag the record URL too
                    RP.note(url, "robots_disallow_redirect_target")
                cur = nxt
                continue
            return r
        raise IOError(f"too many redirects: {url}")


def pdf_text(b):
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(b); f.flush()
        r = subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True, timeout=180)
        return r.stdout.decode("utf-8", "replace").strip()


def classify_title(t):
    tl = t.lower()
    dt = "ordinance" if re.search(r"ordenan[cz]a|ordenança|ordenantza", tl) else "regulation"
    stage = ("definitive" if re.search(r"definitiv", tl) else "initial" if re.search(r"inicial|provisional", tl)
             else "modification" if re.search(r"modific", tl) else None)
    return dt, stage


# ----------------------------------------------------------------------------- staging
class Stager:
    def __init__(self, gazette, st):
        self.g, self.st = gazette, st
        self.buf = {}  # place_key -> rows
        self.unm = []

    def add(self, rec, matched):
        if matched:
            self.buf.setdefault(S.place_key(rec["place_id"], None, "ES"), []).append(rec)
        else:
            self.unm.append(rec)

    def pending(self):
        return sum(len(v) for v in self.buf.values()) + len(self.unm)

    def _write(self, d, name, rows, pk=None):
        d.mkdir(parents=True, exist_ok=True)
        final = d / name
        tmp = final.with_name("." + final.name + ".tmp.jsonl")
        with tmp.open("w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            fh.flush(); os.fsync(fh.fileno())
        if pk:
            v = S.validate_file(tmp, expect_place_key=pk)
            if not v["ok"]:
                raise RuntimeError(f"validate_file {final.name}: {v['errors'][:3]}")
        os.rename(tmp, final)

    def flush(self):
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.st["batch"] = self.st.get("batch", 0) + 1
        b = f"{self.g}-p{self.st['batch']:05d}-{ts}"
        for pk, rows in self.buf.items():
            good = [r for r in rows if not S.validate_record(r)]
            bad = [r for r in rows if S.validate_record(r)]
            if bad:
                QUAR.mkdir(parents=True, exist_ok=True)
                with open(QUAR / f"{pk}.{b}.jsonl", "a") as q:
                    for r in bad:
                        q.write(json.dumps({"reasons": S.validate_record(r), "record": r}, ensure_ascii=False) + "\n")
            if good:
                self._write(OUT, f"{pk}.{b}.jsonl", good, pk)
                self.st["n_docs"] = self.st.get("n_docs", 0) + len(good)
                self.st.setdefault("places", {})[pk] = self.st.get("places", {}).get(pk, 0) + len(good)
        if self.unm:
            self._write(UNM, f"{b}.jsonl", self.unm)
            with open(STAGE / "_unmatched_es_bop.csv", "a", newline="") as fh:
                w = csv.writer(fh)
                for r in self.unm:
                    w.writerow([self.g, r["doc_id"], r.get("issuer_name"), r.get("province_code"), r.get("match"), r["source_url"]])
            self.st["n_unmatched"] = self.st.get("n_unmatched", 0) + len(self.unm)
        for rows in list(self.buf.values()) + [self.unm]:
            for r in rows:
                self.st["done"][r["doc_id"]] = 1
        self.buf, self.unm = {}, []


def load_state(g):
    p = STATE / f"{g}.json"
    return json.loads(p.read_text()) if p.exists() else {"gazette": g, "done": {}}


def save_state(g, st):
    STATE.mkdir(parents=True, exist_ok=True)
    p = STATE / f"{g}.json"
    t = p.with_suffix(".json.tmp")
    t.write_text(json.dumps(st, ensure_ascii=False))
    os.replace(t, p)


def base_record(g, place, doc_id, url, title, text, fmt, pub, extra):
    dt, stage = classify_title(title)
    rec = {"place_id": place.get("place_id"), "country_code": "ES", "doc_id": doc_id, "source_platform": f"es_bop_{g}",
           "source_url": url, "doc_type": dt, "language": "es", "html_title": title, "title_native": title,
           "number": doc_id, "published_date": pub, "in_force": None, "consolidated": False, "content_format": fmt,
           "text": text, "retrieved_at": now_utc(),
           "place_name": place.get("place_name"), "qid": place.get("qid"), "admin_level": place.get("admin_level") or "municipality",
           "platform": f"es_bop_{g}", "platform_place_id": place.get("ine"), "ine_code": place.get("ine"),
           "approval_stage": stage, "source_policy": RP.policy(url, "robots_allowed_rfc9309"), "match": place.get("match"),
           "content_sha256": hashlib.sha256((text or "").encode()).hexdigest()}
    rec.update(extra)
    return {k: v for k, v in rec.items() if v is not None or k == "place_id"}


# ----------------------------------------------------------------------------- adapters
class BOCM:
    """Boletín Oficial de la Comunidad de Madrid (uniprovincial, prov 28). Walks bulletins by (date, number);
    Sección III Administración Local. Full text from the open XML (2025-01-15+) else PDF (pdftotext)."""
    key, prov, home = "bocm", "28", "https://www.bocm.es/"

    def bulletin(self, f, d, n):
        u = f"https://www.bocm.es/boletin-completo/BOCM-{d:%Y%m%d}/{n}"
        r = f.get(u)
        return (r.text, u) if r.status_code == 200 and "node-orden" in r.text else (None, u)

    def items(self, html):
        soup = BeautifulSoup(html, "lxml")
        out, in_local = [], False
        for el in soup.find_all(["h3", "article"]):
            if el.name == "h3":
                t = el.get_text(" ", strip=True).upper()
                if "ADMINISTRACIÓN LOCAL" in t:
                    in_local = True
                elif in_local and ("JUSTICIA" in t or "OTROS ANUNCIOS" in t or "ADMINISTRACIÓN DEL ESTADO" in t or "COMUNIDAD DE MADRID" in t):
                    in_local = False
                continue
            if not in_local or "node-orden" not in " ".join(el.get("class", [])):
                continue
            did = el.get("about", "").strip("/").upper()
            desc = el.select_one(".field-name-field-short-description")
            title = re.sub(r"^[–\-\s]+", "", desc.get_text(" ", strip=True)) if desc else ""
            pdf = el.select_one(".field-name-field-pdf-file a")
            xml = el.select_one(".field-name-orden-xml a")
            out.append({"doc_id": did, "title": title, "pdf": pdf["href"] if pdf else None,
                        "xml": ("https://www.bocm.es" + xml["href"]) if xml and xml["href"].startswith("/") else (xml["href"] if xml else None)})
        return out

    def run(self, f, st, stager, res, a):
        years = st.setdefault("years", {})
        y0, y1 = a.bocm_to_year, a.bocm_from_year
        for y in range(y0, y1 - 1, -1):          # newest year first
            ys = years.setdefault(str(y), {"next_date": f"{y}-01-01", "next_num": 1, "done": False})
            if ys["done"]:
                continue
            d = date.fromisoformat(ys["next_date"]); n = ys["next_num"]; misses = 0
            since_flush = 0
            while d.year == y and d <= date.today():
                if d.weekday() == 6:
                    d += timedelta(days=1); continue
                html, bu = self.bulletin(f, d, n)
                if html is None:
                    misses += 1
                    d += timedelta(days=1)
                    if misses > 12:          # number sequence lost (e.g. extraordinary issue): try n+1 on same window
                        n += 1; d -= timedelta(days=misses); misses = 0
                        if n > ys["next_num"] + 3:
                            log.warning("bocm %s: lost sequence at %s n=%s", y, d, n); break
                    continue
                misses = 0
                for it in self.items(html):
                    if it["doc_id"] in st["done"] or not TARGET_RE.search(it["title"]) or EXCLUDE_RE.search(it["title"]):
                        continue
                    issuer = it["title"].split(".")[0].strip()
                    place = res.resolve(issuer, self.prov)
                    try:
                        text, fmt, src = None, None, None
                        if it["xml"]:
                            r = f.get(it["xml"])
                            if r.status_code == 200 and "<texto" in r.text:
                                text = BeautifulSoup(r.content, "xml").find("texto").get_text("\n").strip(); fmt, src = "xml", it["xml"]
                        if not text and it["pdf"]:
                            r = f.get(it["pdf"])
                            if r.status_code == 200 and r.content[:4] == b"%PDF":
                                text, fmt, src = pdf_text(r.content), "pdf_text", it["pdf"]
                        if not text:
                            st.setdefault("doc_errors", {})[it["doc_id"]] = "no content"; continue
                    except Blocked as e:
                        st.setdefault("robots_skipped", []).append(it["doc_id"]); log.info("bocm robots skip %s %s", it["doc_id"], e); continue
                    rec = base_record(self.key, place, it["doc_id"], src, it["title"], text, fmt, d.isoformat(),
                                      {"issuer_name": issuer, "province_code": self.prov, "bulletin_number": n, "bulletin_url": bu,
                                       "html_url": f"https://www.bocm.es/{it['doc_id'].lower()}"})
                    stager.add(rec, bool(place.get("place_id")))
                n += 1; d += timedelta(days=1); since_flush += 1
                if since_flush >= a.flush_days or stager.pending() >= 200:
                    stager.flush(); ys.update(next_date=d.isoformat(), next_num=n); save_state(self.key, st); since_flush = 0
                    log.info("bocm checkpoint %s n=%s docs=%s unmatched=%s", d, n, st.get("n_docs", 0), st.get("n_unmatched", 0))
            stager.flush()
            ys.update(next_date=d.isoformat(), next_num=n, done=(d.year > y))
            save_state(self.key, st)
            if a.max_days and a.validate:
                break


# ----------------------------------------------------------------------------- day-walker adapters (2026-10-10 round 2)
def html_text(h):
    soup = BeautifulSoup(h, "lxml")
    for t in soup(["script", "style"]):
        t.decompose()
    for br in soup.find_all(["br"]):
        br.replace_with("\n")
    txt = soup.get_text("\n")
    return re.sub(r"\n\s*\n+", "\n\n", re.sub(r"[ \t\xa0]+", " ", txt)).strip()


class DayWalker:
    """Generic walker: newest day first (today -> floor), one sumario per day. Subclasses implement
    day(f, d) -> (bulletin_meta | None, [item]) where item = dict(doc_id, issuer, title, local, ...)
    and text(f, it) -> (text, content_format, source_url, extra)."""
    key = prov = home = None
    floor = "2010-01-01"
    max_misses = 45            # consecutive days without a bulletin -> history ends here
    skip_weekdays = (6,)       # Sunday

    def is_target(self, it):
        t = it["title"]
        return it.get("local") and TARGET_RE.search(t) and not EXCLUDE_RE.search(t)

    def handle_items(self, f, st, stager, res, cur, meta, items):
        for it in items:
            if it["doc_id"] in st["done"] or not self.is_target(it):
                continue
            place = res.resolve(it["issuer"], self.prov)
            try:
                text, fmt, src, extra = self.text(f, it)
            except Blocked as e:
                st.setdefault("robots_skipped", []).append(it["doc_id"]); log.info("%s robots skip %s %s", self.key, it["doc_id"], e); continue
            except CaptchaChallenge:
                raise                    # never stage a challenge page; the day is redone from the last checkpoint
            except Exception as e:  # noqa: BLE001
                st.setdefault("doc_errors", {})[it["doc_id"]] = f"{type(e).__name__}: {e}"[:200]; continue
            if not text or len(text) < 40:
                st.setdefault("doc_errors", {})[it["doc_id"]] = "no content"; continue
            ex = {"issuer_name": it["issuer"], "province_code": self.prov, "bulletin_number": (meta or {}).get("number"),
                  "bulletin_url": (meta or {}).get("url"), "html_url": it.get("html_url"), "gazette": self.key}
            ex.update(extra or {})
            rec = base_record(self.key, place, it["doc_id"], src, it["title"], text, fmt, cur.isoformat(), ex)
            if it.get("language"):
                rec["language"] = it["language"]
            stager.add(rec, bool(place.get("place_id")))

    def _captcha_cooldown(self, cur):
        """Escalating pause after bot-protection challenges (15, 30, 45, 60 min ...). Never solved or worked around."""
        self._n_captcha = getattr(self, "_n_captcha", 0) + 1
        wait = min(900 * self._n_captcha, 3600)
        log.warning("%s CAPTCHA challenge #%d at %s (not circumvented) -> cooldown %d min", self.key, self._n_captcha, cur, wait // 60)
        time.sleep(wait)

    def retry_error_days(self, f, st, stager, res):
        """One attempt per recorded error day; success removes it from error_days (so no day is silently lost)."""
        ed = st.get("error_days") or {}
        if not ed:
            return
        log.info("%s retrying %d error days", self.key, len(ed))
        fixed = 0
        for ds in sorted(ed):
            d = date.fromisoformat(ds)
            try:
                f.last_status = None
                meta, items = self.day(f, d)
                if meta is None and f.last_status not in (None, 200, 404):
                    raise IOError(f"HTTP {f.last_status}")
            except Blocked as e:
                st.setdefault("robots_skipped_days", []).append(ds); ed.pop(ds, None); log.info("%s robots skip day %s %s", self.key, ds, e); continue
            except CaptchaChallenge as e:
                log.warning("%s captcha challenge during error-day retry at %s -> stop retrying for now", self.key, ds); break
            except Exception as e:  # noqa: BLE001
                ed[ds] = f"{type(e).__name__}: {e}"[:160]; continue
            try:
                self.handle_items(f, st, stager, res, d, meta, items)
            except CaptchaChallenge:
                log.warning("%s captcha challenge during error-day retry at %s -> stop retrying for now", self.key, ds); break
            ed.pop(ds, None); fixed += 1
            if stager.pending() >= 200:
                stager.flush(); save_state(self.key, st)
        stager.flush(); save_state(self.key, st)
        log.info("%s error-day retry: %d recovered, %d still failing %s", self.key, fixed, len(ed), sorted(ed)[:5])

    def run(self, f, st, stager, res, a):
        today = date.today()
        self.retry_error_days(f, st, stager, res)
        cur = date.fromisoformat(st.get("cursor") or today.isoformat())
        floor = date.fromisoformat(getattr(a, "floor", None) or self.floor)
        misses = st.get("misses", 0); since = 0; n_days = 0
        while cur >= floor:
            if cur.weekday() in self.skip_weekdays:
                cur -= timedelta(days=1); continue
            meta, items, err = None, [], None
            for attempt in range(3):
                try:
                    f.last_status = None
                    meta, items = self.day(f, cur)
                    err = None
                    if meta is None and f.last_status not in (None, 200, 404):
                        err = f"HTTP {f.last_status}"
                except Blocked as e:
                    st.setdefault("robots_skipped_days", []).append(cur.isoformat()); log.info("%s robots skip day %s %s", self.key, cur, e)
                    meta, items, err = None, [], None
                except CaptchaChallenge as e:
                    err = f"captcha_challenge: {e}"[:160]
                    break
                except DayUnavailable as e:
                    err = f"{type(e).__name__}: {e}"[:160]
                    if attempt < 2:
                        log.warning("%s day %s %s (attempt %d) -> quick retry", self.key, cur, err, attempt + 1)
                        time.sleep(5 * (attempt + 1))
                    continue
                except Exception as e:  # noqa: BLE001
                    err = f"{type(e).__name__}: {e}"[:160]
                if not err:
                    break
                log.warning("%s day %s error %s (attempt %d) -> backoff", self.key, cur, err, attempt + 1)
                time.sleep(60 * (attempt + 1))
            if err and err.startswith("captcha_challenge"):
                st.setdefault("error_days", {})[cur.isoformat()] = err
                log_skipped_day(self.key, cur.isoformat(), err)
                stager.flush(); st.update(cursor=(cur - timedelta(days=1)).isoformat(), misses=misses); save_state(self.key, st)
                self._captcha_cooldown(cur)
                cur -= timedelta(days=1); continue
            if err:
                st.setdefault("error_days", {})[cur.isoformat()] = err     # not a 'miss': re-tried at the next run start
                log.warning("%s SKIPPED day %s after 3 attempts: %s (recorded in error_days + _skipped_days_es_bop.csv)", self.key, cur, err)
                log_skipped_day(self.key, cur.isoformat(), err)
            elif meta is None:
                misses += 1
            else:
                misses = 0; n_days += 1
            try:
                self.handle_items(f, st, stager, res, cur, meta, items)
            except CaptchaChallenge as e:          # challenge on an anuncio: keep what we have, redo this day after a cooldown
                log.warning("%s day %s doc fetch hit CAPTCHA (%s) -> day will be redone", self.key, cur, e)
                stager.flush(); st.update(cursor=cur.isoformat(), misses=misses); save_state(self.key, st)
                self._captcha_cooldown(cur)
                continue
            self._n_captcha = 0
            cur -= timedelta(days=1); since += 1
            if since >= a.flush_days or stager.pending() >= 200:
                stager.flush(); st.update(cursor=cur.isoformat(), misses=misses); save_state(self.key, st); since = 0
                log.info("%s checkpoint cursor=%s docs=%s unmatched=%s", self.key, cur, st.get("n_docs", 0), st.get("n_unmatched", 0))
            if misses > self.max_misses:
                log.info("%s: %d consecutive days without bulletin before %s -> history start reached", self.key, misses, cur)
                st["history_start_reached"] = cur.isoformat(); break
            if a.max_days and n_days >= a.max_days:
                break
        stager.flush(); st.update(cursor=cur.isoformat(), misses=misses); save_state(self.key, st)
        self.retry_error_days(f, st, stager, res)


class BORM(DayWalker):
    """Boletín Oficial de la Región de Murcia: public JSON/XML services used by borm.es itself
    (services/boletin/fecha/DD-MM-YYYY/sumario; services/anuncio/<id>/txt). Sección IV Administración Local."""
    key, prov, home = "borm", "30", "https://www.borm.es/"
    min_interval = 3.0         # Radware bot protection challenges bursts (2026-10-11): slower than the 1 req/s default
    B = "https://www.borm.es/services"

    def day(self, f, d):
        r = f.get(f"{self.B}/boletin/fecha/{d:%d-%m-%Y}/sumario")
        if r.status_code == 200 and "<anunciosBoletin>" not in r.text and "<SumarioBoletinDTO" not in r.text and "<ArrayList" not in r.text:
            sd = STAGE / "_logs" / "_samples"; sd.mkdir(parents=True, exist_ok=True)
            if len(list(sd.glob("borm_sumario_*"))) < 5:
                (sd / f"borm_sumario_{d:%Y%m%d}_{len(r.content)}b.txt").write_bytes(
                    f"content-type: {r.headers.get('content-type')}\n\n".encode() + r.content)
            if re.search(r"captcha|perfdrive|shieldsquare", r.text[:3000], re.I):
                raise CaptchaChallenge(f"Radware captcha page ({len(r.content)} bytes) for sumario {d}")
            raise DayUnavailable(f"unexpected sumario response ({len(r.content)} bytes)")
        if r.status_code != 200 or "<anunciosBoletin>" not in r.text:
            return None, []
        x = BeautifulSoup(r.content, "xml")
        root = x.find("SumarioBoletinDTO")
        meta = {"number": root.find("numero", recursive=False).text if root and root.find("numero", recursive=False) else None,
                "url": f"https://www.borm.es/#/home/sumario/{d:%d-%m-%Y}"}
        out = []
        for a in x.find_all("anunciosBoletin"):
            if a.find("id") is None or a.find("sumario") is None:
                continue
            apartado = a.find("apartado").text if a.find("apartado") else ""
            out.append({"doc_id": f"BORM-{a.find('ano').text}-{a.find('numero').text}", "id": a.find("id").text,
                        "issuer": (a.find("anunciante").text or "").strip(), "title": a.find("sumario").text.strip(),
                        "local": "Administración Local" in apartado,
                        "html_url": f"https://www.borm.es/#/home/anuncio/{d:%d-%m-%Y}/{a.find('numero').text}",
                        "category": (a.find("categoriaCompleta").text if a.find("categoriaCompleta") else None) or None})
        return meta, out

    def text(self, f, it):
        u = f"{self.B}/anuncio/{it['id']}/txt"
        r = f.get(u)
        if r.status_code != 200:
            raise IOError(f"HTTP {r.status_code}")
        if "text/html" in (r.headers.get("content-type") or "") and re.search(r"captcha|perfdrive|shieldsquare", r.text[:3000], re.I):
            raise CaptchaChallenge(f"Radware captcha page for anuncio {it['id']}")
        r.encoding = r.encoding or "utf-8"
        return r.text.strip(), "html", u, {"borm_id": it["id"], "category": it.get("category"), "source_format": "txt"}


class Caceres(DayWalker):
    """BOP Cáceres: the site's own JSON service /bop/services/anuncios/fechaPublicacion?fechaPublic=MM/DD/YYYY returns
    every anuncio of the day incl. contenidoHtml. Anuncios individually disallowed in robots.txt are skipped."""
    key, prov, home = "caceres", "10", "https://bop.dip-caceres.es/bop/index.html"
    B = "https://bop.dip-caceres.es/bop"

    def day(self, f, d):
        r = f.get(f"{self.B}/services/anuncios/fechaPublicacion?fechaPublic={d:%m/%d/%Y}")
        try:
            data = (r.json() or {}).get("data") or []
        except ValueError:
            data = []
        if r.status_code != 200 or not data:
            return None, []
        meta = {"number": data[0].get("numBop"), "url": f"{self.B}/sumario.html?busqueda=numBop&id={data[0].get('idboletin')}"}
        out = []
        for a in data:
            csv_ = a.get("csv") or str(a.get("idAnuncio"))
            title = re.sub(r"^BOP-\d{4}-\d+\s*", "", a.get("tituloAnuncio") or "").strip()
            out.append({"doc_id": f"BOPCC-{csv_}", "csv": csv_, "issuer": a.get("nombreEntidad") or "", "title": title,
                        "local": "Administración Local" in (a.get("nombreTipoEntidad") or ""),
                        "group": a.get("nombreGrupoEntidad"), "html": a.get("contenidoHtml") or "",
                        "html_url": f"{self.B}/anuncio.html?csv={csv_}"})
        return meta, out

    def text(self, f, it):
        ok, why = f.allowed(it["html_url"])
        if not ok:
            raise Blocked(why)
        t = html_text(it["html"]) if it["html"] else ""
        src, fmt = it["html_url"], "html"
        if len(t) < 300:                                   # body is only "se adjunta anexo" -> signed PDF
            u = f"{self.B}/services/anuncios/contenidoPdfIdAnuncio?csv={it['csv']}"
            r = f.get(u)
            if r.status_code == 200 and r.content[:4] == b"%PDF":
                pt = pdf_text(r.content)
                if len(pt) > len(t):
                    t, src, fmt = pt, u, "pdf_text"
        return t, fmt, src, {"entity_group": it.get("group"), "html": it["html"] if fmt == "html" else None}


class Gipuzkoa(DayWalker):
    """Gipuzkoako Aldizkari Ofiziala / BOG: static daily sumario gao-bog/castell/bog/YYYY/MM/DD/bcYYMMDD.htm,
    static HTML per anuncio (cYYNNNNN.htm). Sección 3 Administración Local (Spanish version)."""
    key, prov, home = "gipuzkoa", "20", "https://egoitza.gipuzkoa.eus/es/bog"
    B = "https://egoitza.gipuzkoa.eus/gao-bog/castell/bog"

    def day(self, f, d):
        u = f"{self.B}/{d:%Y/%m/%d}/bc{d:%y%m%d}.htm"
        r = f.get(u)
        if r.status_code != 200 or "secciones" not in r.text:
            return None, []
        soup = BeautifulSoup(r.content.decode("iso-8859-15", "replace"), "lxml")
        m = re.search(r"N[úu]mero\s*(?:&nbsp;|\s)*(\d+)", soup.get_text(" "))
        meta = {"number": m.group(1) if m else None, "url": u}
        out = []
        for sec in soup.select("li.seccion"):
            sname = sec.find("p").get_text(" ", strip=True) if sec.find("p") else ""
            local = "ADMINISTRACI" in sname.upper() and "LOCAL" in sname.upper()
            for org in sec.select("li.organismo"):
                issuer = org.find("a").get_text(" ", strip=True) if org.find("a") else ""
                for an in org.select("ul.anuncios > li"):
                    t = an.select_one(".titulo_anuncio")
                    h = an.select_one("a.descarga_html")
                    pdf = an.select_one("a.descarga_pdf")
                    if not t or not (h or pdf):
                        continue
                    href = urljoin(u, (h or pdf)["href"])
                    did = re.search(r"/(c\d+)\.(?:htm|pdf)$", href)
                    out.append({"doc_id": f"BOG-{d:%Y}-{did.group(1) if did else href.rsplit('/', 1)[-1]}", "issuer": issuer,
                                "title": t.get_text(" ", strip=True), "local": local,
                                "html": urljoin(u, h["href"]) if h else None, "pdf": urljoin(u, pdf["href"]) if pdf else None,
                                "html_url": urljoin(u, h["href"]) if h else urljoin(u, pdf["href"])})
        return meta, out

    def text(self, f, it):
        if it["html"]:
            r = f.get(it["html"])
            if r.status_code == 200:
                raw = r.content.decode("iso-8859-15", "replace")
                soup = BeautifulSoup(raw, "lxml")
                body = soup.find(id="edukia") or soup.body or soup
                t = html_text(str(body))
                if len(t) > 80:
                    return t, "html", it["html"], {"html": str(body)}
        if it["pdf"]:
            r = f.get(it["pdf"])
            if r.status_code == 200 and r.content[:4] == b"%PDF":
                return pdf_text(r.content), "pdf_text", it["pdf"], {}
        return None, None, None, {}


class Cordoba(DayWalker):
    """BOP Córdoba (Next.js site): /dia/DD-MM-YYYY lists every anuncio by section (h1) and emisor (h2);
    full text from the per-anuncio PDF /visor-pdf/DD-MM-YYYY/BOP-A-YYYY-N.pdf."""
    key, prov, home = "cordoba", "14", "https://bop.dipucordoba.es/"
    B = "https://bop.dipucordoba.es"

    def day(self, f, d):
        u = f"{self.B}/dia/{d:%d-%m-%Y}"
        r = f.get(u)
        if r.status_code != 200:
            return None, []
        soup = BeautifulSoup(r.content, "lxml")
        lis = soup.select("li.announcement")
        if not lis:
            return None, []
        m = re.search(r"BOP-S-\d{4}-(\d+)", r.text)
        meta = {"number": m.group(1) if m else None, "url": u}
        out = []
        for li in lis:
            a = li.find("a", href=re.compile(r"/visor-pdf/.*\.pdf"))
            if not a:
                continue
            h1, h2 = li.find_previous("h1"), li.find_previous("h2")
            did = re.search(r"(BOP-A-\d{4}-\d+)", a["href"])
            out.append({"doc_id": f"CO-{did.group(1) if did else a['href'].rsplit('/', 1)[-1]}",
                        "issuer": h2.get_text(" ", strip=True) if h2 else "", "title": li.p.get_text(" ", strip=True) if li.p else "",
                        "local": bool(h1 and "ADMINISTRACIÓN LOCAL" in h1.get_text(" ", strip=True).upper()),
                        "pdf": urljoin(self.B, a["href"]), "html_url": urljoin(self.B, a["href"])})
        return meta, out

    def text(self, f, it):
        r = f.get(it["pdf"])
        if r.status_code == 200 and r.content[:4] == b"%PDF":
            return pdf_text(r.content), "pdf_text", it["pdf"], {}
        raise IOError(f"HTTP {r.status_code}")


NONLOCAL_RE = re.compile(r"servicio provincial|consejo|junta |junta$|juzgado|tribunal|ministerio|confederaci|subdelegaci|delegaci[oó]n|consejer[ií]a|gobierno|"
                         r"diputaci[oó]n|direcci[oó]n general|instituto|agencia|universidad|comunidad de regantes|sociedad|s\.?l\.?$|s\.?a\.?$|notar|registro", re.I)


class Saga(DayWalker):
    """SAGA/OpenCms 'consulta-de-bops' platform shared by BOP Granada, León and Huesca:
    /publica/consulta-de-bops/buscador/BOP-DD-MM-YYYY/ lists all anuncios (title, issuer, CVE);
    detail page -> signed PDF (pdftotext)."""
    max_misses = 30

    def __init__(self, key, prov, base):
        self.key, self.prov, self.B = key, prov, base
        self.home = base + "/"

    def day(self, f, d):
        u = f"{self.B}/publica/consulta-de-bops/buscador/BOP-{d:%d-%m-%Y}/"
        r = f.get(u)
        if r.status_code != 200:
            return None, []
        soup = BeautifulSoup(r.content, "lxml")
        lis = soup.select("li.elementoListado")
        if not lis:
            return None, []
        m = re.search(r"BOP\s*n[ºo°]\s*(\d+)", soup.get_text(" "), re.I)
        meta = {"number": m.group(1) if m else None, "url": u}
        out = []
        for li in lis:
            a = li.select_one("a.enlace_elemento")
            t = li.select_one(".titulo_elemento")
            iss = li.select_one(".campo_1")
            cve = li.select_one(".campo_3")
            if not a or not t:
                continue
            issuer = iss.get_text(" ", strip=True) if iss else ""
            code = cve.get_text(" ", strip=True) if cve else a["href"].strip("/").rsplit("/", 1)[-1]
            out.append({"doc_id": code, "issuer": issuer, "title": t.get_text(" ", strip=True),
                        "local": bool(issuer) and not NONLOCAL_RE.search(issuer),
                        "detail": urljoin(self.B, a["href"]), "html_url": urljoin(self.B, a["href"])})
        return meta, out

    def text(self, f, it):
        r = f.get(it["detail"])
        if r.status_code != 200:
            raise IOError(f"detail HTTP {r.status_code}")
        soup = BeautifulSoup(r.content, "lxml")
        pdfs = [a["href"] for a in soup.find_all("a", href=True) if re.search(r"\.pdf($|\?)", a["href"], re.I) and "Sumario" not in a["href"] and "Documentos-BOPs" not in a["href"]]
        summary = ""
        h = soup.find(["h1", "h2"], string=re.compile(re.escape(it["title"][:30]), re.I)) if it["title"] else None
        nxt = h.find_next("p") if h else None
        if nxt:
            summary = nxt.get_text(" ", strip=True)
        if pdfs:
            pu = urljoin(it["detail"], pdfs[0])
            rp = f.get(pu)
            if rp.status_code == 200 and rp.content[:4] == b"%PDF":
                return pdf_text(rp.content), "pdf_text", pu, {"summary": summary or None}
        raise IOError("no pdf")


class Soria(DayWalker):
    """BOP Soria: /index.php/mod.boloficial/mem.listadodia/fecha.DD-MM-YYYY -> bulletin detail (mem.detalle/id.N)
    whose 'Sumario' tree (section / subsection / issuer / title) links one PDF per anuncio."""
    key, prov, home = "soria", "42", "https://bop.dipsoria.es/"
    B = "https://bop.dipsoria.es"
    skip_weekdays = (5, 6)

    def day(self, f, d):
        u = f"{self.B}/index.php/mod.boloficial/mem.listadodia/fecha.{d:%d-%m-%Y}"
        r = f.get(u)
        if r.status_code != 200:
            return None, []
        m = re.search(r'href="(/index\.php/mod\.boloficial/mem\.detalle/id\.\d+/relcategoria\.\d+)"[^>]*>\s*BOP\s*(\d+)', r.text)
        if not m:
            return None, []
        du = self.B + m.group(1)
        r2 = f.get(du)
        if r2.status_code != 200:
            return None, []
        soup = BeautifulSoup(r2.content, "lxml")
        meta = {"number": m.group(2), "url": du}
        lv = ["", "", "", ""]
        out = []
        ul = soup.select_one("ul.lst")
        for li in (ul.find_all("li", recursive=False) if ul else []):
            divs = li.find_all("div", recursive=False)
            for i, dv in enumerate(divs[:4]):
                p = dv.find("p")
                t = p.get_text(" ", strip=True).lstrip("- ").strip() if p else ""
                if t:
                    lv[i] = t
                    for j in range(i + 1, 4):
                        lv[j] = ""
            a = li.find("a", href=re.compile(r"mem\.descargar/fichero\."))
            if not a:
                continue
            fid = re.search(r"fichero\.documentos_([^%]+)", a["href"])
            out.append({"doc_id": f"SO-{d:%Y}-{fid.group(1) if fid else a['href'][-20:]}", "issuer": lv[2], "title": lv[3],
                        "local": "ADMINISTRACI" in lv[0].upper() and "LOCAL" in lv[0].upper() and "AYUNTAMIENTO" in lv[1].upper(),
                        "pdf": a["href"].replace("http://", "https://"), "html_url": du})
        return meta, out

    def text(self, f, it):
        r = f.get(it["pdf"])
        if r.status_code == 200 and r.content[:4] == b"%PDF":
            return pdf_text(r.content), "pdf_text", it["pdf"], {}
        raise IOError(f"HTTP {r.status_code}")


def pdf_pages_text(b, first, last):
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(b); f.flush()
        r = subprocess.run(["pdftotext", "-layout", "-f", str(first), "-l", str(last), f.name, "-"], capture_output=True, timeout=180)
        return r.stdout.decode("utf-8", "replace")


def _norm_txt(t):
    import unicodedata
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().upper()
    return re.sub(r"\s+", " ", t)


class Avila(DayWalker):
    """BOP Ávila: /boletin-oficial/YYYY/DD-MM-YYYY.html lists every anuncio grouped by issuer (div.listado > span),
    one PDF per anuncio (/bops/YYYY/DD-MM-YYYY/DD-MM-YYYY_NNNNNN.pdf). robots.txt Crawl-delay 10 honoured."""
    key, prov, home = "avila", "05", "https://www.diputacionavila.es/boletin-oficial/"
    B = "https://www.diputacionavila.es"
    skip_weekdays = (5, 6)

    def day(self, f, d):
        u = f"{self.B}/boletin-oficial/{d:%Y}/{d:%d-%m-%Y}.html"
        r = f.get(u)
        if r.status_code != 200 or "listado" not in r.text:
            return None, []
        soup = BeautifulSoup(r.content, "lxml")
        m = re.search(r"B\.O\.P\.\s*(\d+)/\d+", soup.get_text(" "))
        meta = {"number": m.group(1) if m else None, "url": u}
        out = []
        for blk in soup.select("div.listado"):
            sp = blk.find("span")
            issuer = sp.get_text(" ", strip=True) if sp else ""
            for li in blk.find_all("li"):
                a = li.find("a", href=re.compile(r"\.pdf$"))
                if not a:
                    continue
                num = li.select_one("p.num")
                code = re.search(r"_(\d+)\.pdf$", a["href"])
                out.append({"doc_id": f"AV-{d:%Y%m%d}-{code.group(1) if code else re.sub(r'[^A-Za-z0-9]+', '', a['href'].rsplit('/', 1)[-1])}", "issuer": issuer,
                            "title": a.get_text(" ", strip=True), "local": issuer.upper().startswith("AYUNTAMIENTO"),
                            "pdf": a["href"], "html_url": u, "anuncio_number": num.get_text(" ", strip=True) if num else None})
        return meta, out

    def text(self, f, it):
        r = f.get(it["pdf"])
        if r.status_code == 200 and r.content[:4] == b"%PDF":
            return pdf_text(r.content), "pdf_text", it["pdf"], {"anuncio_number": it.get("anuncio_number")}
        raise IOError(f"HTTP {r.status_code}")


class Guadalajara(DayWalker):
    """BOP Guadalajara (Joomla K2): /boletin/index.php/buscar-k2-menu/date/YYYY/M/D (?start=N pages of 6) lists the
    anuncios of the day with their 'Municipios' field; the item page carries the full text (HTML) + issuer + PDF link."""
    key, prov, home = "guadalajara", "19", "https://boletin.dguadalajara.es/boletin/"
    B = "https://boletin.dguadalajara.es"

    def day(self, f, d):
        base = f"{self.B}/boletin/index.php/buscar-k2-menu/date/{d.year}/{d.month}/{d.day}"
        out, start, seen = [], 0, set()
        while True:
            r = f.get(base + (f"?start={start}" if start else ""))
            if r.status_code != 200:
                break
            soup = BeautifulSoup(r.content, "lxml")
            items = soup.select(".catItemView, .genericItemView, .itemContainer .catItemView")
            new = 0
            for it in items:
                a = it.find("a", href=re.compile(r"/buscar-k2-menu/\d+-anuncio/\d+"))
                if not a:
                    continue
                m = re.search(r"/(\d+)-anuncio/(\d+)", a["href"])
                if m.group(2) in seen:
                    continue
                seen.add(m.group(2)); new += 1
                txt = it.get_text(" | ", strip=True)
                mun = re.search(r"Municipios \| ([^|]+)", txt)
                mun = mun.group(1).strip() if mun else ""
                title = it.select_one(".catItemTitle, .genericItemTitle, h3")
                title = title.get_text(" ", strip=True) if title else a.get_text(" ", strip=True)
                out.append({"doc_id": f"GU-{m.group(2)}", "issuer": mun, "title": title,
                            "local": bool(mun) and not re.search(r"provincia|varios", mun, re.I),
                            "detail": urljoin(self.B, a["href"]), "html_url": urljoin(self.B, a["href"])})
            if new == 0 or not re.search(r"\?start=%d\b" % (start + 6), r.text):
                break
            start += 6
        if not out:
            return None, []
        return {"number": None, "url": base}, out

    def text(self, f, it):
        r = f.get(it["detail"])
        if r.status_code != 200:
            raise IOError(f"HTTP {r.status_code}")
        soup = BeautifulSoup(r.content, "lxml")
        body = soup.select_one(".itemFullText") or soup.select_one(".itemBody") or soup.select_one(".itemView")
        iss = re.search(r"\b(AYUNTAMIENTO DE [^\n|]+|MANCOMUNIDAD [^\n|]+|ENTIDAD LOCAL [^\n|]+)", soup.get_text("\n"))
        pdf = soup.find("a", href=re.compile(r"/boletin/pdf/.+\.pdf$"))
        ex = {"issuer_detail": iss.group(1).strip()[:200] if iss else None, "pdf_url": urljoin(self.B, pdf["href"]) if pdf else None}
        if iss and not iss.group(1).upper().startswith("AYUNTAMIENTO"):
            ex["issuer_name_detail_nonmunicipal"] = True
        return html_text(str(body)) if body else "", "html", it["detail"], ex


class Lugo(DayWalker):
    """BOP Lugo (Drupal): the public list view /gl/boletin-oficial-da-provincia-de-lugo/bop filtered by publication
    date (plain GET filter of the public listing) -> bulletin node, whose sumario tree (section > CONCELLOS > concello >
    anuncio) links the whole-bulletin PDF with #page=N. Each anuncio is cut out of the whole PDF: pages N..next N,
    trimmed to the segment that ends with its registry reference 'R. NNNN'."""
    key, prov, home = "lugo", "27", "https://www.deputacionlugo.gal/boletin-oficial-da-provincia-de-lugo"
    B = "https://www.deputacionlugo.gal"
    skip_weekdays = (5, 6)

    def __init__(self):
        self._pdf = (None, None)

    def day(self, f, d):
        u = (f"{self.B}/gl/boletin-oficial-da-provincia-de-lugo/bop?fecha_publicacion%5Bmin%5D={d:%d}%2F{d:%m}%2F{d:%Y}"
             f"&fecha_publicacion%5Bmax%5D={d:%d}%2F{d:%m}%2F{d:%Y}")
        r = f.get(u)
        if r.status_code != 200:
            return None, []
        nodes = list(dict.fromkeys(re.findall(r'href="(/gl/node/\d+)"', r.text.split("views-row", 1)[-1] if "views-row" in r.text else r.text)))
        rows = BeautifulSoup(r.content, "lxml").select("tr")
        nodes = []
        for tr in rows:
            a = tr.find("a", href=re.compile(r"/node/\d+"))
            if a and f"{d:%d/%m/%Y}" in tr.get_text(" "):
                nodes.append(urljoin(self.B, a["href"]))
        if not nodes:
            return None, []
        out, meta = [], None
        for nu in dict.fromkeys(nodes):
            r2 = f.get(nu)
            if r2.status_code != 200:
                continue
            soup = BeautifulSoup(r2.content, "lxml")
            box = soup.select_one(".field--name-field-ail-bop-contenido")
            if not box:
                continue
            num = soup.select_one(".field--name-field-ail-bop-numero .field__item")
            meta = meta or {"number": num.get_text(strip=True) if num else None, "url": nu}
            links = box.find_all("a", href=re.compile(r"\.pdf#page=\d+"))
            pages = [int(re.search(r"#page=(\d+)", a["href"]).group(1)) for a in links]
            for i, a in enumerate(links):
                anc = [x.find("strong", recursive=False) for x in a.find_parents("li")]
                anc = [x.get_text(" ", strip=True) for x in anc if x]
                title = a.get_text(" ", strip=True)
                ref = re.search(r"R\.\s*(\d+)\)", title)
                pdfu = urljoin(self.B, a["href"].split("#")[0])
                nxt = next((p for p in pages[i + 1:] if p >= pages[i]), None)
                out.append({"doc_id": f"LU-{d:%Y%m%d}-{ref.group(1) if ref else pages[i]}", "issuer": anc[0] if anc else "",
                            "title": re.sub(r"\s*\(P[ÁA]X\..*\)\s*$", "", title), "local": any(x.upper().startswith("CONCELLOS") for x in anc),
                            "pdf": pdfu, "page": pages[i], "page_to": nxt or pages[i] + 3, "ref": ref.group(1) if ref else None,
                            "html_url": nu, "language": "gl"})
        return (meta, out) if out else (None, [])

    def text(self, f, it):
        if self._pdf[0] != it["pdf"]:
            r = f.get(it["pdf"])
            if r.status_code != 200 or r.content[:4] != b"%PDF":
                raise IOError(f"HTTP {r.status_code}")
            self._pdf = (it["pdf"], r.content)
        t = pdf_pages_text(self._pdf[1], it["page"], it["page_to"])
        seg = split_by_ref(t, it.get("ref"), it["issuer"])
        return seg, "pdf_text", f"{it['pdf']}#page={it['page']}", {"pdf_pages": f"{it['page']}-{it['page_to']}", "split_method": "page_range+registry_ref"}


class Ourense(DayWalker):
    """BOP Ourense (Angular portal): the portal's own public JSON API (/portalapi/api), exactly the calls the browser
    makes: boletin/getFecha/YYYYMMDD (bulletins of the day), boletin/publicado/<n>/<YYYYMMDD>/es/<N|S> (sumario tree
    section > issuer > edictos) and edicto/descargar/html/<id>/es (per-anuncio HTML; PDF fallback).
    NOTE: boletin/getDetalle is deliberately NOT used (it exposes advertiser contact records)."""
    key, prov, home = "ourense", "32", "https://bop.depourense.es/portal/"
    B = "https://bop.depourense.es/portalapi/api"

    def day(self, f, d):
        r = f.get(f"{self.B}/boletin/getFecha/{d:%Y%m%d}")
        if r.status_code != 200:
            return None, []
        bols = [x.get("boletin") or {} for x in (r.json() or [])]
        bols = [b for b in bols if b.get("fechaPublicacion") == f"{d:%Y%m%d}"]
        if not bols:
            return None, []
        out, meta = [], None
        for b in bols:
            exc = b.get("excepcional") or "N"
            u = f"{self.B}/boletin/publicado/{b['numeroBop']}/{d:%Y%m%d}/CAS/{exc}"
            r2 = f.get(u)
            if r2.status_code != 200:
                continue
            meta = meta or {"number": str(b.get("numeroBop")), "url": f"https://bop.depourense.es/portal/boletin?fecha={d:%Y%m%d}"}
            sm = (r2.json() or {}).get("sumario") or {}
            pdfu = f"{self.B}/boletin/descargar/{b['id']}/idioma/es"
            rows = []
            for sec, issuers in sm.items():
                if not isinstance(issuers, dict):
                    continue
                for iss, eds in issuers.items():
                    for e in eds or []:
                        rows.append((sec, iss, e))
            pages = sorted({int(e["pagina"]) for _, _, e in rows if str(e.get("pagina") or "").isdigit()})
            for sec, iss, e in rows:
                iu = iss.strip().upper()
                t0 = (e.get("sumarioEdicto") or "").strip()
                ref = re.search(r"\[(\d+)/(\d{4})\]\s*$", t0)
                pg = int(e["pagina"]) if str(e.get("pagina") or "").isdigit() else None
                nxt = next((p for p in pages if pg and p > pg), None)
                did = f"OU-{e['idEdicto']}" if e.get("idEdicto") else f"OU-{b['id']}-{ref.group(1) if ref else pg}"
                out.append({"doc_id": did, "id": e.get("idEdicto"), "issuer": re.sub(r"\s*-\s*[A-Z][a-zà-ú].*$", "", iss.strip()),
                            "title": re.sub(r"\s*\[\d+/\d+\]\s*$", "", t0),
                            "local": "LOCA" in sec.upper() and (iu.startswith("AYUNTAMIENTO") or iu.startswith("CONCELLO")),
                            "page": pg, "page_to": nxt or (pg + 3 if pg else None), "ref": ref.group(1) if ref else None,
                            "pdf": pdfu, "bis": exc == "S", "html_url": meta["url"]})
        return (meta, out) if out else (None, [])

    def __init__(self):
        self._pdf = (None, None)

    def text(self, f, it):
        if not it.get("id"):
            if not it.get("page"):
                raise IOError("no edicto id and no page")
            if self._pdf[0] != it["pdf"]:
                r = f.get(it["pdf"])
                if r.status_code != 200 or r.content[:4] != b"%PDF":
                    raise IOError(f"HTTP {r.status_code}")
                self._pdf = (it["pdf"], r.content)
            with tempfile.NamedTemporaryFile(suffix=".pdf") as tf:
                tf.write(self._pdf[1]); tf.flush()
                t = subprocess.run(["pdftotext", "-f", str(it["page"]), "-l", str(it["page_to"]), tf.name, "-"],
                                   capture_output=True, timeout=180).stdout.decode("utf-8", "replace")
            seg = t.strip()
            if it.get("ref"):
                rx = r"\b[Rr]\.\s*%s\b" % re.escape(f"{int(it['ref']):,}".replace(",", ".")) if int(it["ref"]) >= 1000 else None
                m = re.search(rx, t) if rx else None
                m = m or re.search(r"\b[Rr]\.\s*%s\b" % re.escape(it["ref"]), t)
                if m:
                    prev = list(re.finditer(r"\b[Rr]\.\s*\d{1,2}\.?\d{3}\b|\b[Rr]\.\s*\d{1,3}\b", t[:m.start()]))
                    seg = t[(prev[-1].end() if prev else 0):m.end()].strip()
            return seg, "pdf_text", f"{it['pdf']}#page={it['page']}", {"pdf_pages": f"{it['page']}-{it['page_to']}",
                                                                      "split_method": "page_range+registry_ref", "registry_ref": it.get("ref")}
        u = f"{self.B}/edicto/descargar/html/{it['id']}/es"
        r = f.get(u)
        if r.status_code == 200 and "<" in r.text[:200]:
            r.encoding = "utf-8"
            return html_text(r.text), "html", u, {"ourense_edicto_id": it["id"], "page": it.get("page")}
        u = f"{self.B}/edicto/descargar/pdf/{it['id']}/idioma/es"
        r = f.get(u)
        if r.status_code == 200 and r.content[:4] == b"%PDF":
            return pdf_text(r.content), "pdf_text", u, {"ourense_edicto_id": it["id"], "page": it.get("page")}
        raise IOError(f"HTTP {r.status_code}")


def pdf_columns_text(b, first, last, ncols=2):
    """Reading-order text of a multi-column PDF page range: each page is cropped into ncols vertical strips
    (pdftotext -x/-y/-W/-H) read left to right, pages in order."""
    out = []
    with tempfile.NamedTemporaryFile(suffix=".pdf") as tf:
        tf.write(b); tf.flush()
        for p in range(int(first), int(last) + 1):
            info = subprocess.run(["pdfinfo", "-f", str(p), "-l", str(p), tf.name], capture_output=True, timeout=60).stdout.decode("utf-8", "replace")
            m = re.search(r"Page\s+%d size:\s*([\d.]+) x ([\d.]+)" % p, info) or re.search(r"Page size:\s*([\d.]+) x ([\d.]+)", info)
            if not m:
                break
            w, h = float(m.group(1)), float(m.group(2))
            for c in range(ncols):
                x0 = int(w * c / ncols); cw = int(w / ncols) + 1
                r = subprocess.run(["pdftotext", "-f", str(p), "-l", str(p), "-r", "72", "-x", str(x0), "-y", "0", "-W", str(cw), "-H", str(int(h) + 1),
                                    tf.name, "-"], capture_output=True, timeout=120)
                out.append(r.stdout.decode("utf-8", "replace"))
    return "\n".join(out)


MESES = {m: i + 1 for i, m in enumerate("enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split())}


class Cadiz(DayWalker):
    """BOP Cádiz (OpenCms): the public bulletin list /boletin/?page=N&sortModifier=desc (date -> bulletin page,
    back to 2001) and the bulletin page's sumario (section > 'NNN.NNN.- Issuer.' title, linking the whole PDF #page=N).
    Each anuncio is cut out of the whole-bulletin PDF: pages N..next anuncio's page, ending at its 'Nº NNN.NNN'
    marker and starting after the previous one; attributed to the issuing ayuntamiento from the sumario."""
    key, prov, home = "cadiz", "11", "https://www.bopcadiz.es/"
    B = "https://www.bopcadiz.es"
    max_misses = 120

    def __init__(self):
        self._idx, self._page, self._oldest, self._end, self._pdf = {}, 0, None, False, (None, None)

    def _more(self, f):
        self._page += 1
        r = f.get(f"{self.B}/boletin/?page={self._page}&sortModifier=desc")
        if r.status_code != 200:
            raise IOError(f"list HTTP {r.status_code}")
        soup = BeautifulSoup(r.content, "lxml")
        n = 0
        for e in soup.select(".listWEntry a[href*='/boletin/Boletin-numero-']"):
            dm = e.select_one(".dayAndMonth"); yy = e.select(".dayOfTheWeek")
            if not dm or len(yy) < 2:
                continue
            dd, mm = dm.get_text(" ", strip=True).replace("\xa0", " ").split()[:2]
            try:
                dt = date(int(yy[-1].get_text(strip=True)), MESES[mm.lower()], int(dd))
            except Exception:  # noqa: BLE001
                continue
            self._idx.setdefault(dt, []).append(urljoin(self.B, e["href"])); n += 1
            self._oldest = dt if self._oldest is None or dt < self._oldest else self._oldest
        if n == 0:
            self._end = True

    def day(self, f, d):
        if self._page == 0 and (date.today() - d).days > 60:     # resume: jump near the cursor instead of paging from today
            self._page = max(0, int((date.today() - d).days * 0.068) - 4)
            while self._page > 0:
                self._more(f)
                newest = max(self._idx) if self._idx else None
                if newest and newest >= d:
                    break
                self._idx, self._oldest, self._end = {}, None, False
                self._page = max(0, self._page - 11)
        while not self._end and (self._oldest is None or self._oldest >= d):
            self._more(f)
            if self._oldest and self._oldest < d:
                break
        for k in [k for k in self._idx if k > d + timedelta(days=3)]:
            del self._idx[k]
        urls = list(dict.fromkeys(self._idx.get(d, [])))
        if not urls:
            return None, []
        out, meta = [], None
        for bu in urls:
            r = f.get(bu)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.content, "lxml")
            num = re.search(r"Boletin-numero-0*(\d+)-del-ano", bu)
            meta = meta or {"number": num.group(1) if num else None, "url": bu}
            links, sec = [], ""
            for el in soup.find_all(["h3", "a"]):
                if el.name == "h3":
                    sec = el.get_text(" ", strip=True); continue
                h = el.get("href") or ""
                m = re.search(r"(\.pdf)#page=(\d+)", h)
                if not m:
                    continue
                st = el.find("strong")
                if st:
                    head = st.get_text(" ", strip=True)
                    mm_ = re.match(r"(\d{1,3}(?:\.\d{3})*)\s*\.?-\s*(.+?)\.?$", head)
                    title = el.get_text(" ", strip=True)[len(head):].strip()
                else:   # older sumarios: ' 13.155.- Ayuntamiento de Rota. Bases reguladoras ...'
                    mm_ = re.match(r"\s*(\d{1,3}(?:\.\d{3})*)\s*\.?-\s*(.+?)\.\s+(.*)$", el.get_text(" ", strip=True))
                    title = mm_.group(3).strip() if mm_ else ""
                if not mm_:
                    continue
                links.append((sec, mm_.group(1), mm_.group(2).strip(), title, urljoin(self.B, h.split("#")[0]), int(m.group(2))))
            pages = sorted({x[5] for x in links})
            for sec, ref, iss, title, pdfu, pg in links:
                nxt = next((p for p in pages if p > pg), pg + 2) + 1   # '#page=' offsets are not reliably 1-based
                out.append({"doc_id": f"CA-{d:%Y%m%d}-{ref.replace('.', '')}", "issuer": re.sub(r"\b([A-ZÁÉÍÓÚÑ]) ([a-zñ]{2,})", r"\1\2", iss), "title": title or iss,
                            "local": "LOCAL" in sec.upper() and iss.upper().startswith("AYUNTAMIENTO"),
                            "pdf": pdfu, "page": max(1, pg), "page_to": nxt, "ref": ref, "html_url": bu})
        return (meta, out) if out else (None, [])

    def text(self, f, it):
        if self._pdf[0] != it["pdf"]:
            r = f.get(it["pdf"])
            if r.status_code != 200 or r.content[:4] != b"%PDF":
                raise IOError(f"HTTP {r.status_code}")
            self._pdf = (it["pdf"], r.content)
        t = pdf_columns_text(self._pdf[1], it["page"], it["page_to"])
        m = re.search(r"N[º°o]\s*%s\b" % re.escape(it["ref"]), t)
        if not m:
            raise IOError("anuncio marker not found in page range")
        prev = list(re.finditer(r"N[º°o]\s*\d{1,3}(?:\.\d{3})+\b", t[:m.start()]))
        seg = t[(prev[-1].end() if prev else 0):m.end()].strip()
        return seg, "pdf_text", f"{it['pdf']}#page={it['page']}", {"pdf_pages": f"{it['page']}-{it['page_to']}",
                                                                  "split_method": "page_range+columns+anuncio_number", "anuncio_number": it["ref"]}


class Castellon(DayWalker):
    """BOP Castellón (PrimeFaces portal), FORWARD-ONLY: the public home page (plain GET) carries the latest bulletin's
    sumario (section > issuer (titulo3) > anuncio PDF link /PortalBOP/api/descargarAnuncio?idAnuncio=N + title (titulo4)).
    Older bulletins are only reachable through JSF AJAX postbacks of the search/carousel form -> not walked backwards."""
    key, prov, home = "castellon", "12", "https://bop.dipcas.es/PortalBOP/"
    floor = "2026-10-01"
    forward_only = True        # run_forward checks bulletin-number continuity and logs any gap (missed issue)
    max_misses = 10

    def day(self, f, d):
        r = f.get(self.home)
        if r.status_code != 200:
            return None, []
        soup = BeautifulSoup(r.content, "lxml")
        lab = soup.find("label", string=re.compile(r"Sumario BOP"))
        dl = lab.find_parent("tr").get_text(" ", strip=True) if lab else ""
        m = re.search(r"N[º°]\s*(\d+).*?(\d{2})/(\d{2})/(\d{4})", dl)
        if not m or date(int(m.group(4)), int(m.group(3)), int(m.group(2))) != d:
            return None, []
        meta = {"number": m.group(1), "url": self.home}
        out, sec, iss, pend = [], "", "", None
        for el in soup.find_all(["span", "a"]):
            cls_ = el.get("class") or []
            if el.name == "span" and ("titulo1" in cls_ or "titulo2" in cls_):
                sec = el.get_text(" ", strip=True)
            elif el.name == "span" and "titulo3" in cls_:
                iss = el.get_text(" ", strip=True)
            elif el.name == "a" and "descargarAnuncio" in (el.get("href") or ""):
                pend = re.search(r"idAnuncio=(\d+)", el["href"]).group(1)
            elif el.name == "span" and "titulo4" in cls_ and pend:
                t = el.get_text(" ", strip=True)
                out.append({"doc_id": f"CS-{pend}", "issuer": iss.split("/")[-1].strip() if "/" in iss else iss, "issuer_raw": iss, "title": t,
                            "local": bool(re.search(r"ajuntament|ayuntamiento", sec + " " + iss, re.I)) and bool(re.match(r"(AJUNTAMENT|AYUNTAMIENTO)", iss.upper())),
                            "pdf": f"https://bop.dipcas.es/PortalBOP/api/descargarAnuncio?idAnuncio={pend}&idioma=es", "html_url": self.home})
                pend = None
        return (meta, out) if out else (None, [])

    def text(self, f, it):
        r = f.get(it["pdf"])
        if r.status_code == 200 and r.content[:4] == b"%PDF":
            return pdf_text(r.content), "pdf_text", it["pdf"], {"issuer_raw": it.get("issuer_raw")}
        raise IOError(f"HTTP {r.status_code}")


def split_by_ref(t, ref, issuer=None):
    """Cut one anuncio out of a page-range text: ends at 'R. <ref>' (registry ref printed under each anuncio),
    starts after the previous 'R. NNNN' marker (or the issuer heading)."""
    if not ref:
        return t.strip()
    m = re.search(r"R\.\s*%s\b" % re.escape(ref), t)
    if not m:
        return t.strip()
    head = t[:m.end()]
    prev = list(re.finditer(r"\bR\.\s*\d{3,5}\b", head[:m.start()]))
    start = prev[-1].end() if prev else 0
    if issuer and start == 0:
        k = _norm_txt(head).find(_norm_txt(issuer)[:25])
        start = 0 if k < 0 else 0
    return head[start:].strip()


class BOCMDay(DayWalker):
    """Day-interface wrapper over BOCM for the forward (new issues) pass: keeps a (date, number) pointer in state;
    initialised from the latest bulletin link on the BOCM home page."""
    key, prov, home = "bocm", "28", "https://www.bocm.es/"
    skip_weekdays = (6,)

    def __init__(self):
        self.b = BOCM()
        self.st = None

    def init_ptr(self, f, st):
        if "ptr" not in st:
            r = f.get(self.home)
            m = re.search(r'href="/boletin/bocm-(\d{8})-(\d+)"', r.text)
            if not m:
                raise IOError("bocm home: latest bulletin link not found")
            st["ptr"] = {"date": datetime.strptime(m.group(1), "%Y%m%d").date().isoformat(), "num": int(m.group(2))}
            st.setdefault("head", st["ptr"]["date"])
        self.st = st

    def day(self, f, d):
        ptr = self.st["ptr"]
        n = 1 if d.year != date.fromisoformat(ptr["date"]).year else ptr["num"] + 1
        html, bu = self.b.bulletin(f, d, n)
        if html is None:
            return None, []
        ptr.update(date=d.isoformat(), num=n)
        out = []
        for it in self.b.items(html):
            out.append(dict(it, issuer=it["title"].split(".")[0].strip(), local=True, html_url=f"https://www.bocm.es/{it['doc_id'].lower()}"))
        return {"number": n, "url": bu}, out

    def text(self, f, it):
        if it.get("xml"):
            r = f.get(it["xml"])
            if r.status_code == 200 and "<texto" in r.text:
                return BeautifulSoup(r.content, "xml").find("texto").get_text("\n").strip(), "xml", it["xml"], {}
        if it.get("pdf"):
            r = f.get(it["pdf"])
            if r.status_code == 200 and r.content[:4] == b"%PDF":
                return pdf_text(r.content), "pdf_text", it["pdf"], {}
        return None, None, None, {}


def run_forward(g, a):
    """New-issues pass: walks forward from state 'head' (default --forward-from) to today. Separate state/batch label
    (<g>_fwd) so it never races the backward walker that owns _state/es_bop/<g>.json."""
    sk = f"{g}_fwd"
    st = load_state(sk)
    f, res = Fetcher(), Resolver()
    ad = BOCMDay() if g == "bocm" else ADAPTERS[g]
    f.min = max(f.min, getattr(ad, "min_interval", 0))
    ok, why = f.allowed(ad.home)
    if not ok:
        st.update(status="blocked", reason=why); save_state(sk, st); return
    if g == "bocm":
        ad.init_ptr(f, st)
    stager = Stager(sk, st)
    head = date.fromisoformat(st.get("head") or a.forward_from)
    d = head + timedelta(days=1)
    n_new = 0
    try:
        while d <= date.today():
            if d.weekday() not in ad.skip_weekdays:
                try:
                    meta, items = ad.day(f, d)
                except Blocked as e:
                    meta, items = None, []; log.info("%s fwd robots skip %s %s", g, d, e)
                if meta is None and d >= date.today() - timedelta(days=1):
                    break                       # today's/yesterday's issue not out yet: retry next pass
                before = stager.pending()
                if meta and getattr(ad, "forward_only", False) and str(meta.get("number") or "").isdigit():
                    num, last = int(meta["number"]), st.get("last_number")
                    if last and num > last + 1:   # home page only shows the latest issue: earlier ones cannot be fetched
                        for missing in range(last + 1, num):
                            log.warning("%s fwd GAP: bulletin no. %d was never seen (forward pass down too long)", g, missing)
                            log_skipped_day(g, f"bulletin_no_{missing}", "forward-only adapter missed this issue")
                    if not last or num > last:
                        st["last_number"] = num; st["last_bulletin_date"] = d.isoformat()
                ad.handle_items(f, st, stager, res, d, meta, items)
                n_new += stager.pending() - before
            st["head"] = d.isoformat()
            d += timedelta(days=1)
            if stager.pending() >= 50:
                stager.flush(); save_state(sk, st)
        stager.flush()
        st.update(status="ok", last_pass=now_utc())
    except Exception as e:  # noqa: BLE001
        log.exception("%s forward failed", g); st.update(status="error", reason=f"{type(e).__name__}: {e}"[:300])
        try:
            stager.flush()
        except Exception:  # noqa: BLE001
            pass
    st["requests"] = st.get("requests", 0) + f.nreq
    save_state(sk, st)
    log.info("%s forward pass: head=%s new_docs=%d total=%s", g, st.get("head"), n_new, st.get("n_docs"))


MESES_GL = {m: i + 1 for i, m in enumerate("xaneiro febreiro marzo abril maio xuño xullo agosto setembro outubro novembro decembro".split())}


class ACoruna(DayWalker):
    """BOP A Coruña (bop.dacoruna.gal): /bopportal/cambioBoletin?fechaInput=DD/MM/YYYY renders the day's sumario
    (HTTP 500 when there is no bulletin that day); sections h1 Administración Local > Municipal; issuer = h3;
    per-anuncio HTML (gl original + machine es translation) and signed PDF under /bopportal/publicado/YYYY/MM/DD/.
    robots.txt disallows /bopportal/publicado/ -> fetched under the owner policy 2026-11-01 (records tagged)."""
    key, prov, home = "acoruna", "15", "https://bop.dacoruna.gal/bopportal/"
    min_interval = 1.5
    B = "https://bop.dacoruna.gal/bopportal"

    def day(self, f, d):
        u = f"{self.B}/cambioBoletin?fechaInput={d:%d}%2f{d:%m}%2f{d:%Y}"
        r = f.get(u)
        if r.status_code == 500 and "bloqueAnuncio" not in r.text:
            f.last_status = 404; return None, []            # no bulletin that day
        if r.status_code != 200:
            return None, []
        t = r.content.decode("utf-8", "replace")
        if re.search(r"captcha|cf-chl|challenge-platform", t[:5000], re.I):
            raise CaptchaChallenge(f"challenge page for {d}")
        m = re.search(r"Bolet[ií]n N&ordm;\s*(\d+)\s*-\s*\w+,\s*(\d+) de (\w+) de (\d{4})", t)
        if not m or (int(m.group(2)), MESES_GL.get(m.group(3).lower()), int(m.group(4))) != (d.day, d.month, d.year):
            return None, []                                  # page shows another day's bulletin
        meta = {"number": m.group(1), "url": u}
        base = f"{self.B}/publicado/{d:%Y/%m/%d}/"
        out, local, h1 = [], False, ""
        for tok in re.finditer(r'<h1 class = "(\w+)">([^<]*)|<div id ="(\d+)" class = "bloqueAnuncio">(.*?)</div>', t, re.S):
            if tok.group(1):
                if tok.group(1) == "administracion":
                    local = "Local" in tok.group(2)
                else:
                    h1 = tok.group(2).strip()
                continue
            b = tok.group(4)
            h3 = re.search(r'<h3 class = "tituloEdicto">([^<]*)', b)
            pdf = re.search(r'href = "(\d{4}_\d+)\.pdf"', b)
            tt = re.findall(r'title = "Ver texto completo">([^<]*)</a>', b)
            if not (h3 and pdf and tt):
                continue
            fn = pdf.group(1); y, n = fn.split("_")
            out.append({"doc_id": f"BOPC-{y}-{int(n)}", "issuer": html_lib.unescape(h3.group(1).strip()),
                        "title": html_lib.unescape(" ".join(tt[-1].split())), "local": local and h1 == "Municipal",
                        "html": base + fn + ".html", "pdf": base + fn + ".pdf", "html_url": base + fn + ".html",
                        "subsection": h1, "language": "gl"})
        return meta, out

    def text(self, f, it):
        r = f.get(it["html"])
        if r.status_code == 200 and "text/html" in (r.headers.get("content-type") or ""):
            raw = r.content.decode("utf-8", "replace")
            t = html_text(raw)
            if len(t) > 200:
                return t, "html", it["html"], {"pdf_url": it["pdf"], "subsection": it.get("subsection")}
        r = f.get(it["pdf"])
        if r.status_code == 200 and r.content[:4] == b"%PDF":
            return pdf_text(r.content), "pdf_text", it["pdf"], {"subsection": it.get("subsection")}
        return None, None, None, {}


class Pontevedra(DayWalker):
    """BOP Pontevedra (boppo.depo.gal, Liferay), FORWARD-ONLY: the home page carries the latest bulletin's sumario
    (h2 numero + span fecha 'venres 30 de outubro de 2026'; h4 section > p.Org (Provincial/Municipal/...) > li: span.pub
    issuer, PDF + /web/boppo/detalle/-/boppo/YYYY/MM/DD/ID). The calendar has no per-day links and the search form
    answers 'erro interno' -> no date listing; history is left to the Wayback archive step (es_arch robots set)."""
    key, prov, home = "pontevedra", "36", "https://boppo.depo.gal/"
    floor = "2026-10-01"
    forward_only = True
    max_misses = 10
    min_interval = 1.5
    B = "https://boppo.depo.gal"

    def day(self, f, d):
        r = f.get(self.home)
        if r.status_code != 200:
            return None, []
        t = r.content.decode("utf-8", "replace")
        if re.search(r"captcha|cf-chl|challenge-platform", t[:5000], re.I):
            raise CaptchaChallenge(f"challenge page for {d}")
        m = re.search(r'class="numero">.*?n[uú]mero\s*(\d+)</span>.*?class="fecha">\s*\w+\s+(\d+) de (\w+) de (\d{4})', t, re.S)
        if not m or (int(m.group(2)), MESES_GL.get(m.group(3).lower()), int(m.group(4))) != (d.day, d.month, d.year):
            return None, []
        meta = {"number": m.group(1), "url": self.home}
        i = t.find('id="contSumario"'); j = t.find('class="masCalendarios"', i)
        body = t[i:j if j > i else None]
        out, sec, org = [], "", ""
        for tok in re.finditer(r'<h4 class="tit">([^<]*)</h4>|<p class="Org">([^<]*)</p>|<li[^>]*><span class="pub">([^<]*)</span>(.*?)</li>', body, re.S):
            if tok.group(1) is not None:
                sec = html_lib.unescape(tok.group(1)); continue
            if tok.group(2) is not None:
                org = html_lib.unescape(tok.group(2)).strip(); continue
            a = re.search(r'<p class="sumario"><a href="(/web/boppo/detalle/-/boppo/(\d{4})/\d\d/\d\d/(\d+))">(.*?)</a>', tok.group(4), re.S)
            pdf = re.search(r'href="([^"]+\.pdf)"', tok.group(4))
            if not a:
                continue
            out.append({"doc_id": f"BOPPO-{a.group(2)}-{a.group(3)}", "issuer": html_lib.unescape(tok.group(3).strip()),
                        "title": html_lib.unescape(" ".join(re.sub(r"<[^>]+>", " ", a.group(4)).split())),
                        "local": "LOCAL" in sec.upper() and org == "Municipal", "html": self.B + a.group(1),
                        "pdf": self.B + pdf.group(1) if pdf else None, "html_url": self.B + a.group(1), "subsection": org, "language": "gl"})
        return (meta, out) if out else (None, [])

    def text(self, f, it):
        r = f.get(it["html"])
        if r.status_code == 200 and "text/html" in (r.headers.get("content-type") or ""):
            raw = r.content.decode("utf-8", "replace")
            k = raw.find('class="contDetalle"')
            t = html_text(raw[raw.rfind("<", 0, k):] if k > 0 else raw)
            if len(t) > 200:
                return t, "html", it["html"], {"pdf_url": it["pdf"], "subsection": it.get("subsection")}
        if it.get("pdf"):
            r = f.get(it["pdf"])
            if r.status_code == 200 and r.content[:4] == b"%PDF":
                return pdf_text(r.content), "pdf_text", it["pdf"], {"subsection": it.get("subsection")}
        return None, None, None, {}


class Alava(DayWalker):
    """BOTHA Álava (www.araba.eus/botha): /Inicio/SGBO5001.aspx?FechaBotha=DD/MM/YYYY renders that day's sumario
    ('Sumario del Boletin nº N del <weekday>, D de mes de YYYY'; '1 de enero de 0001' when there is none). Bilingual rows
    (eu td then es td); section titles TitSeccion1/2/3 printed on change; es anuncio = Hyperlink1 -> 
    /Busquedas/Resultado.aspx?File=Boletines/YYYY/NNN/YYYY_NNN_NNNNN_C.xml (HTML) + same-name .pdf."""
    key, prov, home = "alava", "01", "https://www.araba.eus/botha/Inicio/SGBO5001.aspx"
    min_interval = 1.5
    B = "https://www.araba.eus/botha"

    def day(self, f, d):
        u = f"{self.B}/Inicio/SGBO5001.aspx?FechaBotha={d:%d/%m/%Y}"
        r = f.get(u)
        if r.status_code != 200:
            return None, []
        t = r.content.decode("utf-8", "replace")
        if re.search(r"captcha|cf-chl|challenge-platform", t[:5000], re.I):
            raise CaptchaChallenge(f"challenge page for {d}")
        m = re.search(r"Sumario del Boletin n\S*\s*(\d+) del \w+, (\d+) de (\w+) de (\d{4})", t)
        if not m or (int(m.group(2)), MESES.get(m.group(3).lower()), int(m.group(4))) != (d.day, d.month, d.year):
            return None, []
        meta = {"number": m.group(1), "url": u}
        out, sec = [], {}
        for tok in re.finditer(r"id='TitSeccion(\d)'>(?:<a[^>]*></a>)?([^<]*)|id=\"[^\"]*_Hyperlink1\" href=\"\.\./Busquedas/Resultado\.aspx\?File=(Boletines/(\d{4})/\d+/\d+_\d+_(\d+)_C)\.xml[^\"]*\"[^>]*>([^<]*)</a>", t):
            if tok.group(1):
                lv = int(tok.group(1)); sec[lv] = html_lib.unescape(tok.group(2)).strip()
                for k in [k for k in sec if k > lv]:
                    sec.pop(k)
                continue
            fb, y, n = tok.group(3), tok.group(4), tok.group(5)
            s1, s2, s3 = sec.get(1, ""), sec.get(2, ""), sec.get(3, "")
            out.append({"doc_id": f"BOTHA-{y}-{int(n)}", "issuer": s3 or s2, "title": html_lib.unescape(" ".join(tok.group(6).split())),
                        "local": s1.startswith("Administración Local") and s2 in ("Municipios", "Concejos"),
                        "html": f"{self.B}/Busquedas/Resultado.aspx?File={fb}.xml", "pdf": f"{self.B}/{fb}.pdf",
                        "html_url": f"{self.B}/Busquedas/Resultado.aspx?File={fb}.xml", "subsection": s2})
        return meta, out

    def text(self, f, it):
        r = f.get(it["html"])
        if r.status_code == 200 and "text/html" in (r.headers.get("content-type") or ""):
            t = html_text(r.content.decode("utf-8", "replace"))
            if len(t) > 400:
                return t, "html", it["html"], {"pdf_url": it["pdf"], "subsection": it.get("subsection")}
        r = f.get(it["pdf"])
        if r.status_code == 200 and r.content[:4] == b"%PDF":
            return pdf_text(r.content), "pdf_text", it["pdf"], {"subsection": it.get("subsection")}
        return None, None, None, {}


class Bizkaia(DayWalker):
    """BOB Bizkaia (www.bizkaia.eus/es/bob, Liferay portlet IYBIWBCC): the calendar resource (POST year/month, the
    portal's own read-only AJAX call) lists that month's bulletins {fechaBoletin, numeroBoletin}; the day sumario is
    /es/bob/resultados?...mvcRenderCommandName=/detail&bdate=YYYYMMDD&bnum=N: li.row > h4 issuer (carried over when
    absent) + p summary + PDF /lehendakaritza/Bao_bob/YYYY/MM/DD/<SEC>-<n>_cas.pdf (SEC II = Administración Local)."""
    key, prov, home = "bizkaia", "48", "https://www.bizkaia.eus/es/bob"
    min_interval = 1.5
    CAL = ("https://www.bizkaia.eus/es/bob?p_p_id=IYBIWBCC&p_p_lifecycle=2&p_p_state=normal&p_p_mode=view"
           "&p_p_resource_id=%2Fiybiwbcc%2FresourceBoletin&p_p_cacheability=cacheLevelPage")
    DET = ("https://www.bizkaia.eus/es/bob/resultados?p_p_id=IYBIWBCC&p_p_lifecycle=0&p_p_state=normal&p_p_mode=view"
           "&_IYBIWBCC_mvcRenderCommandName=%2Fdetail&_IYBIWBCC_bdate={}&_IYBIWBCC_bnum={}")

    def __init__(self):
        self._cal = {}

    def month(self, f, y, m):
        k = (y, m)
        if k not in self._cal:
            f.allowed(self.CAL)
            dl = f.next.get("www.bizkaia.eus", 0) - time.time()
            if dl > 0:
                time.sleep(dl)
            f.next["www.bizkaia.eus"] = time.time() + f.min
            r = f.s.post(self.CAL, data={"_IYBIWBCC_year": str(y), "_IYBIWBCC_month": str(m)}, timeout=60); f.nreq += 1
            f.last_status = r.status_code
            if r.status_code != 200:
                raise DayUnavailable(f"calendar HTTP {r.status_code}")
            try:
                ev = json.loads(r.text) if r.text.strip() else []
            except ValueError:
                raise DayUnavailable("calendar: non-JSON answer")
            if len(self._cal) > 24:
                self._cal.clear()
            self._cal[k] = {e["fechaBoletin"]: e for e in ev if e.get("fechaBoletin")}
        return self._cal[k]

    def day(self, f, d):
        e = self.month(f, d.year, d.month).get(f"{d:%Y%m%d}")
        if not e:
            f.last_status = 404; return None, []
        u = self.DET.format(f"{d:%Y%m%d}", e.get("numeroBoletin"))
        r = f.get(u)
        if r.status_code != 200:
            return None, []
        t = r.content.decode("utf-8", "replace")
        if re.search(r"captcha|cf-chl|challenge-platform", t[:5000], re.I):
            raise CaptchaChallenge(f"challenge page for {d}")
        meta = {"number": str(e.get("numeroBoletin")), "url": u}
        out, iss = [], ""
        for li in re.finditer(r'<li class="row">(.*?)</li>', t, re.S):
            b = li.group(1)
            h4 = re.search(r'<h4 id="emisorEntidad[^"]*">([^<]*)</h4>', b)
            if h4:
                iss = html_lib.unescape(h4.group(1).strip())
            pr = re.search(r'<p id="emisorResumen[^"]*">(.*?)</p>', b, re.S)
            pdf = re.search(r'href="(https?://www\.bizkaia\.eus/lehendakaritza/Bao_bob/[^"]*?/([IVX]+)-(\d+)_cas\.pdf)"', b)
            oldp = None if pdf else re.search(r'href="(https?://www\.bizkaia\.eus/lehendakaritza/Bao_bob/\d{4}/\d\d/\d{8}a\d+\.pdf)#page=(\d+)"', b)
            if pr and oldp:              # pre-2015 format: one bulletin PDF, anuncio = #page=N (until the next anuncio's page)
                out.append({"doc_id": f"BOB-{d.year}-{int(meta['number'])}-{len(out) + 1:03d}", "issuer": iss,
                            "title": html_lib.unescape(" ".join(re.sub(r"<[^>]+>", " ", pr.group(1)).split())),
                            "local": bool(re.match(r"(Ayuntamiento|Udala|Concejo|Junta Administrativa)", iss, re.I)),
                            "bulletin_pdf": oldp.group(1).replace("http://", "https://"), "page": int(oldp.group(2)),
                            "pdf": f"{oldp.group(1).replace('http://', 'https://')}#page={oldp.group(2)}", "html_url": u})
                continue
            if not (pr and pdf):
                continue
            sec = pdf.group(2)
            out.append({"doc_id": f"BOB-{d.year}-{sec}-{int(pdf.group(3))}", "issuer": iss,
                        "title": html_lib.unescape(" ".join(re.sub(r"<[^>]+>", " ", pr.group(1)).split())),
                        "local": sec == "II" and bool(re.match(r"(Ayuntamiento|Udala|Concejo|Junta Administrativa)", iss, re.I)),
                        "pdf": pdf.group(1).replace("http://", "https://"), "html_url": u, "subsection": sec})
        if not out:
            raise DayUnavailable(f"bulletin {meta['number']} listed but sumario empty")
        pages = [x for x in out if x.get("page")]
        for a_, b_ in zip(pages, pages[1:] + [None]):
            a_["last_page"] = max(a_["page"], b_["page"]) if b_ else a_["page"] + 3
        return meta, out

    def text(self, f, it):
        if it.get("bulletin_pdf"):
            bu = it["bulletin_pdf"]
            if getattr(self, "_bpdf", (None,))[0] != bu:
                r = f.get(bu)
                if r.status_code != 200 or r.content[:4] != b"%PDF":
                    raise IOError(f"HTTP {r.status_code}")
                self._bpdf = (bu, r.content)
            t = pdf_pages_text(self._bpdf[1], it["page"], it["last_page"])
            return t, "pdf_text", it["pdf"], {"pdf_pages": [it["page"], it["last_page"]], "page_range_approx": True}
        r = f.get(it["pdf"])
        if r.status_code == 200 and r.content[:4] == b"%PDF":
            return pdf_text(r.content), "pdf_text", it["pdf"], {"subsection": it.get("subsection")}
        raise IOError(f"HTTP {r.status_code}")


class Barcelona(DayWalker):
    """BOP Barcelona (bop.diba.cat): /anteriors/YYYY-MM-DD[/page]?bopb_dia[tipologiaAnunciant]=177 lists that day's
    anuncis of 'Ajuntaments Província de Barcelona' (20 per page, "S'han trobat N resultats ... mostrant del a al b");
    card: h3 > a /anunci/<id>/<slug> (issuer) + p summary + Registre; text = /anunci/descarrega-pdf/<id> (PDF).
    robots.txt disallows /anteriors/ -> fetched under the owner policy 2026-11-01 (records tagged)."""
    key, prov, home = "barcelona", "08", "https://bop.diba.cat/"
    min_interval = 2.0
    B = "https://bop.diba.cat"
    TIP, PFX = ("177",), "BOPB"            # Ajuntaments Província de Barcelona

    def __init__(self, key=None, prov=None, base=None, tip=None, pfx=None):
        if key:                            # same Drupal 'bopb' platform reused by other provinces (e.g. Tarragona)
            self.key, self.prov, self.B, self.home, self.TIP, self.PFX = key, prov, base, base + "/", tip, pfx

    def day(self, f, d):
        out = []
        for tip in self.TIP:
            meta, o = self.day_tip(f, d, tip)
            if meta is None and f.last_status not in (None, 200, 404):
                return None, []
            out += o
        return (meta, out) if meta else (None, [])

    def day_tip(self, f, d, tip):
        out, page, meta = [], 1, None
        while page < 60:
            u = f"{self.B}/anteriors/{d:%Y-%m-%d}" + (f"/{page}" if page > 1 else "") + f"?bopb_dia%5BtipologiaAnunciant%5D={tip}"
            r = f.get(u)
            if r.status_code == 500 and page == 1:
                f.last_status = 404; return None, []        # the portal answers 500 for days without a bulletin
            if r.status_code != 200:
                return (meta, out) if out else (None, [])
            t = r.content.decode("utf-8", "replace")
            if re.search(r"captcha|cf-chl|challenge-platform", t[:5000], re.I):
                raise CaptchaChallenge(f"challenge page for {d}")
            if page == 1:
                if f"{d:%d/%m/%Y}" not in t[:3000] and "Data de publicaci" not in t:
                    return None, []
                meta = {"number": None, "url": u}
            for c in re.finditer(r'<h3 class="card-title h6">\s*<a href="([^"]*/anunci/(\d+)/[^"]*)"[^>]*>([^<]*)</a>\s*</h3>\s*<p>(.*?)</p>(.*?)</ul>', t, re.S):
                if f"{d:%d/%m/%Y}" not in c.group(5):
                    continue
                reg = re.search(r"Registre</span>:\s*(\d+)", c.group(5))
                iss = html_lib.unescape(c.group(3).strip())
                iss = re.sub(r"^(.*?)\s+([^,]+),\s*(EL|LA|LES|ELS|L')$", lambda m_: m_.group(1) + " " + m_.group(3) + ("" if m_.group(3).endswith("'") else " ") + m_.group(2), iss, flags=re.I)   # 'AJUNTAMENT MASROIG, EL' -> 'AJUNTAMENT EL MASROIG' 
                out.append({"doc_id": f"{self.PFX}-{c.group(2)}", "issuer": iss,
                            "title": html_lib.unescape(" ".join(re.sub(r"<[^>]+>", " ", c.group(4)).split())), "local": True,
                            "pdf": f"{self.B}/anunci/descarrega-pdf/{c.group(2)}", "html_url": urljoin(self.B + "/", c.group(1)),
                            "registre": reg.group(1) if reg else None, "language": "ca"})
            m = re.search(r"trobat (\d+) resultats.*?mostrant del \d+ al (\d+)", t)
            if not m or int(m.group(2)) >= int(m.group(1)):
                break
            page += 1
        if meta is None or not out:
            return (None, []) if meta is None else (meta, [])
        return meta, out

    def text(self, f, it):
        r = f.get(it["pdf"])
        if r.status_code == 200 and r.content[:4] == b"%PDF":
            return pdf_text(r.content), "pdf_text", it["pdf"], {"registre": it.get("registre")}
        r = f.get(it["html_url"])
        if r.status_code == 200:
            t = html_text(r.content.decode("utf-8", "replace"))
            if len(t) > 400:
                return t, "html", it["html_url"], {"registre": it.get("registre")}
        raise IOError(f"HTTP {r.status_code}")


class Girona(DayWalker):
    """BOP Girona (www.ddgi.cat/bop): bulletins are addressed by year + number only (/bop/mostra-bop/<any-date>/YYYY/N;
    the date segment is ignored, no per-date listing) -> day(d) locates N by a local search around an estimate (cache
    year/N -> date read from 'Bop número: N/x - DD/MM/YYYY'). Sumario: h2.seccioTau section > li.edicte >
    a PDF ssl4.ddgi.cat/bopV1/pdf/YYYY/N/<id>.pdf 'NNNN - <span>ISSUER</span> - title'."""
    key, prov, home = "girona", "17", "https://www.ddgi.cat/bop/"
    min_interval = 2.0
    B = "https://www.ddgi.cat/bop/mostra-bop"

    def __init__(self):
        self._nd, self._ptr, self._html = {}, {}, {}

    def bul(self, f, y, n):
        k = (y, n)
        if k not in self._nd:
            if n < 1:
                self._nd[k] = None; return None
            u = f"{self.B}/{y}-01-01/{y}/{n}"
            try:
                r = f.get(u)
            except IOError as e:
                if "too many redirects" not in str(e):
                    raise
                self._nd[k] = None; return None
            t = r.content.decode("utf-8", "replace") if r.status_code == 200 else ""
            if re.search(r"captcha|cf-chl|challenge-platform", t[:5000], re.I):
                raise CaptchaChallenge(f"challenge page for {y}/{n}")
            m = re.search(r"Bop n[uú]mero:\s*(\d+)/\d+\s*-\s*(\d\d)/(\d\d)/(\d{4})", t)
            if r.status_code >= 500:
                raise DayUnavailable(f"HTTP {r.status_code} for {y}/{n}")
            self._nd[k] = date(int(m.group(4)), int(m.group(3)), int(m.group(2))) if m and int(m.group(1)) == n else None
            if self._nd[k]:
                if len(self._html) > 8:
                    self._html.clear()
                self._html[k] = (u, t)
            if len(self._nd) > 5000:
                self._nd.clear()
        return self._nd[k]

    def day(self, f, d):
        y = d.year
        n = self._ptr.get(y) or max(1, int(sum(1 for i in range((d - date(y, 1, 1)).days + 1)
                                               if (date(y, 1, 1) + timedelta(days=i)).weekday() < 5) * 0.97))
        for _ in range(60):
            dn = self.bul(f, y, n)
            if dn is None:                       # past the year's last number (or a gap): step down
                if n <= 1:
                    f.last_status = 404; return None, []
                n -= 1; continue
            if dn > d:
                n -= 1; continue
            if dn == d:
                break
            nx = self.bul(f, y, n + 1)           # dn < d: is there a bulletin between?
            if nx is None or nx > d:
                self._ptr[y] = n; f.last_status = 404; return None, []
            n += 1
        else:
            raise DayUnavailable(f"could not locate bulletin for {d}")
        self._ptr[y] = n
        u, t = self._html.get((y, n)) or (None, None)
        if t is None:
            self._nd.pop((y, n), None); self.bul(f, y, n); u, t = self._html[(y, n)]
        meta = {"number": str(n), "url": u}
        out, sec = [], ""
        for tok in re.finditer(r'<h2 class="seccioTau">\s*([^<]*?)\s*</h2>|<li class="edicte">\s*<a href="(https://ssl4\.ddgi\.cat/bopV1/pdf/[^"]*/(\d+)\.pdf)"[^>]*>(.*?)</a>', t, re.S):
            if tok.group(1) is not None:
                sec = html_lib.unescape(tok.group(1)); continue
            body = tok.group(4)
            iss = re.search(r"<span>([^<]*)</span>", body)
            title = re.sub(r"^\s*\d+\s*-\s*<span>[^<]*</span>\s*-\s*", "", body, flags=re.S)
            out.append({"doc_id": f"BOPG-{tok.group(3)}", "issuer": html_lib.unescape(iss.group(1).strip()) if iss else "",
                        "title": html_lib.unescape(" ".join(re.sub(r"<[^>]+>", " ", title).split())),
                        "local": bool(re.search(r"Ajuntament", sec, re.I)), "pdf": tok.group(2), "html_url": u,
                        "subsection": sec, "language": "ca"})
        return meta, out

    def text(self, f, it):
        r = f.get(it["pdf"])
        if r.status_code == 200 and r.content[:4] == b"%PDF":
            return pdf_text(r.content), "pdf_text", it["pdf"], {"subsection": it.get("subsection")}
        raise IOError(f"HTTP {r.status_code}")


class Alicante(DayWalker):
    """BOP Alicante: the sede's own read-only JSON service (wseConsultaAjax.php, nemo BOP_CON, fechaPub DD/MM/YYYY,
    tipoorganismo 4 = III. Administración Local) lists that day's edictos {nBop, ampliacion, denominacion, extracto,
    edicto, ubicacion}. ubicacion = per-edicto PDF (www.dip-alicante.es/bop2/pdftotal/...) or, for older bulletins,
    the full bulletin PDF '#page=N' (page range up to the next edicto's page)."""
    key, prov, home = "alicante", "03", "https://sede.diputacionalicante.es/consultas-bop/"
    min_interval = 1.5
    WS = "https://sede.diputacionalicante.es/wp-content/themes/Desarrollo-Diputacion/webservices/wseConsultaAjax.php"

    def day(self, f, d):
        from urllib.parse import urlencode
        u = self.WS + "?" + urlencode({"nemo": "BOP_CON", "usuario": "-", "param": "<raiz><entrada><registro><fechaPub>"
                                       f"{d:%d/%m/%Y}</fechaPub><tipoorganismo>4</tipoorganismo></registro></entrada></raiz>"})
        r = f.get(u)
        if r.status_code != 200:
            return None, []
        try:
            j = json.loads(r.text)
        except ValueError:
            if re.search(r"captcha|cf-chl|challenge-platform", r.text[:5000], re.I):
                raise CaptchaChallenge(f"challenge page for {d}")
            raise DayUnavailable("non-JSON answer")
        bj = j.get("boletin") if isinstance(j.get("boletin"), dict) else j
        regs = [x for b in (bj.get("bop") or j.get("bop") or []) for x in (b.get("registro") or [])]
        if not regs:
            return None, []
        g = lambda x, k: (x.get(k) or [""])[0]
        meta = {"number": g(regs[0], "nBop"), "url": u}
        out = []
        for x in regs:
            if g(x, "fechaPublica") != f"{d:%d/%m/%Y}":
                continue
            loc = g(x, "ubicacion")
            m = re.search(r"#page=(\d+)", loc)
            out.append({"doc_id": f"BOPA-{d.year}-{int(g(x, 'edicto') or 0)}", "issuer": g(x, "ampliacion") or g(x, "denominacion"),
                        "place_hint": g(x, "denominacion"), "title": " ".join(g(x, "extracto").split()),
                        "local": g(x, "csecun") == "1000" or g(x, "abreviatura").upper() == "AYUNTAMIENTO",
                        "pdf": loc, "bulletin_pdf": loc.split("#")[0] if m else None, "page": int(m.group(1)) if m else None,
                        "html_url": loc, "subsection": g(x, "desecun")})
        pages = sorted({x["page"] for x in out if x["page"]})
        for x in out:
            if x["page"]:
                nxt = [p_ for p_ in pages if p_ > x["page"]]
                x["last_page"] = nxt[0] if nxt else x["page"] + 3
        return meta, out

    def text(self, f, it):
        if it.get("bulletin_pdf"):
            bu = it["bulletin_pdf"]
            if getattr(self, "_bpdf", (None,))[0] != bu:
                r = f.get(bu)
                if r.status_code != 200 or r.content[:4] != b"%PDF":
                    raise IOError(f"HTTP {r.status_code}")
                self._bpdf = (bu, r.content)
            return (pdf_pages_text(self._bpdf[1], it["page"], it["last_page"]), "pdf_text", it["pdf"],
                    {"pdf_pages": [it["page"], it["last_page"]], "page_range_approx": True})
        r = f.get(it["pdf"])
        if r.status_code == 200 and r.content[:4] == b"%PDF":
            return pdf_text(r.content), "pdf_text", it["pdf"], {"subsection": it.get("subsection")}
        raise IOError(f"HTTP {r.status_code}")


class Toledo(DayWalker):
    """BOP Toledo (bop.diputoledo.es/webEbop): ebopResumen.jsp?publication_date=DD/MM/YYYY&publication_date_to=same
    ('Boletín número N publicado el día DD/MM/YYYY'); h2 'Tipo Anunciante : X' > h3 publisherBlock 'Anunciante : ISSUER'
    > div.announce: DocGet?id=...&insert_number=N&insert_year=Y (PDF) + 'Resumen/Asunto'. Publishes on weekends too.
    robots.txt Disallow: / -> fetched under the owner policy 2026-11-01 (records tagged)."""
    key, prov, home = "toledo", "45", "https://bop.diputoledo.es/webEbop/"
    min_interval = 1.5
    skip_weekdays = ()
    B = "https://bop.diputoledo.es/webEbop/"

    def day(self, f, d):
        u = f"{self.B}ebopResumen.jsp?publication_date={d:%d/%m/%Y}&publication_date_to={d:%d/%m/%Y}"
        r = f.get(u)
        if r.status_code != 200:
            return None, []
        t = r.content.decode("utf-8", "replace")
        if re.search(r"captcha|cf-chl|challenge-platform", t[:5000], re.I):
            raise CaptchaChallenge(f"challenge page for {d}")
        m = re.search(r"Bolet[ií]n n[uú]mero\s*(\d+)\s*publicado el d[ií]a\s*(\d\d/\d\d/\d{4})", t)
        if not m or m.group(2) != f"{d:%d/%m/%Y}":
            return None, []
        meta = {"number": m.group(1), "url": u}
        out, typ, iss = [], "", ""
        for tok in re.finditer(r"<h2>Tipo Anunciante\s*:\s*([^<]*)</h2>|<h3 class=\"publisherBlock\">Anunciante\s*:\s*([^<]*)</h3>|class=\"announce\">(.*?)</ul>", t, re.S):
            if tok.group(1) is not None:
                typ = html_lib.unescape(tok.group(1)).strip(); continue
            if tok.group(2) is not None:
                iss = html_lib.unescape(tok.group(2)).strip(); continue
            b = tok.group(3)
            a = re.search(r'href="(DocGet\?id=[^"]*insert_number=(\d+)&(?:amp;)?insert_year=(\d{4}))"', b)
            ra = re.search(r"Resumen/Asunto\s*:\s*</strong>(.*?)</li>", b, re.S)
            if not (a and ra):
                continue
            out.append({"doc_id": f"BOPTO-{a.group(3)}-{int(a.group(2))}", "issuer": iss,
                        "title": html_lib.unescape(" ".join(re.sub(r"<[^>]+>", " ", ra.group(1)).split())),
                        "local": typ.lower().startswith("ayuntamiento") or iss.upper().startswith("AYUNTAMIENTO"),
                        "pdf": self.B + html_lib.unescape(a.group(1)), "html_url": u, "subsection": typ})
        return meta, out

    def text(self, f, it):
        r = f.get(it["pdf"])
        if r.status_code == 200 and r.content[:4] == b"%PDF":
            return pdf_text(r.content), "pdf_text", it["pdf"], {"subsection": it.get("subsection")}
        raise IOError(f"HTTP {r.status_code}")


class LasPalmas(DayWalker):
    """BOP Las Palmas (www.boplaspalmas.net/nbop2): sumario.php?codigopub=1&fecha_mas_reciente=YYYY-MM-DD (empty
    'Nº' -> no bulletin that day) -> whole-bulletin PDF boletines/YYYY/D-M-YY/D-M-YY.pdf. The PDF's own sumario lists
    '<id> <title>....<printed page>' under issuer headings; section III = Administración Local. Each anuncio is cut out
    of the whole PDF by printed-page range (printed page -> PDF page via the running header). The PDF is only
    downloaded when the HTML sumario has a target title. robots.txt Disallow: / -> fetched under owner policy 2026-11-01."""
    key, prov, home = "laspalmas", "35", "https://www.boplaspalmas.net/nbop2/index.php"
    B = "https://www.boplaspalmas.net/"
    min_interval = 1.5
    skip_weekdays = (5, 6)

    def __init__(self):
        self._pdf = (None, None, None)

    def _load_pdf(self, f, u):
        if self._pdf[0] != u:
            r = f.get(u)
            if r.status_code != 200 or r.content[:4] != b"%PDF":
                raise DayUnavailable(f"pdf HTTP {r.status_code}")
            pages = pdf_text(r.content).split("\f")
            if len("".join(pages).strip()) < 200:
                from common import scanned_pdfs as SP
                SP.append([SP.record(f"BOPLP-{u.rsplit('/', 1)[-1]}", "es_bop_laspalmas", "ES", u, RP.policy(u, "robots_allowed_rfc9309"))])
                raise DayUnavailable(f"scanned pdf (no text layer) {u} -> _scanned_pdfs_manifest")
            pmap = {}
            for i, pg in enumerate(pages):
                head = pg.strip()[:300]
                m = (re.match(r"^(\d{1,6})\s+Bolet[ií]n Oficial de la Provincia", head)
                     or re.match(r"^Bolet[ií]n Oficial de la Provincia[^\n]*?de \d{4}\s+(\d{1,6})\s*\n", head))
                if m:
                    pmap.setdefault(int(m.group(1)), i + 1)
            full = "\f".join(pages)
            marks = [m.start() for m in re.finditer(r"(?m)^\s*\d{1,2}\.\d{3}\s*$", full)]
            self._pdf = (u, r.content, (pages, pmap, full, marks))
        return self._pdf

    def day(self, f, d):
        u = f"{self.B}nbop2/sumario.php?codigopub=1&fecha_mas_reciente={d:%Y-%m-%d}"
        r = f.get(u)
        if r.status_code != 200:
            return None, []
        t = r.content.decode("utf-8", "replace")
        if re.search(r"captcha|cf-chl|challenge-platform", t[:5000], re.I):
            raise CaptchaChallenge(f"challenge page for {d}")
        plain = html_lib.unescape(re.sub(r"<[^>]+>", " ", t))
        m = re.search(r"SUMARIO DEL BOLET[ÍI]N\s+Nº\s*(\d+)\s*,", plain)
        pm = re.search(r'href="\.\./(boletines/[^"]+\.pdf)"', t)
        if not m or not pm:
            return None, []
        pdfu = self.B + pm.group(1)
        meta = {"number": m.group(1), "url": u}
        if not TARGET_RE.search(plain):
            return meta, []
        _, _, (pages, pmap, full, marks) = self._load_pdf(f, pdfu)
        head = "\n".join(pages[:6])
        rows, sec, iss = [], "", ""
        lines = head.split("\n")
        i = 0
        while i < len(lines):
            ln = lines[i]
            s = ln.strip()
            ms = re.match(r"^([IVX]+)\.\s+([A-ZÁÉÍÓÚÑ ,]+)$", s)
            mi = re.match(r"^(\d{3,8}(?:-?[A-Z])?)\s+(.+)$", s)
            if ms:
                sec = ms.group(1)
            elif mi:
                title = mi.group(2)
                while not re.search(r"\s(\d{2,6})$", title) and i + 1 < len(lines) and lines[i + 1].strip() and not re.match(r"^\d{3,8}(?:-?[A-Z])?\s", lines[i + 1].strip()):
                    i += 1; title += " " + lines[i].strip()
                mp = re.search(r"[\s.…]*\s(\d{2,6})$", title)
                if mp:
                    rows.append((mi.group(1), re.sub(r"[.…\s]+$", "", title[:mp.start()]), int(mp.group(1)), sec, iss))
            elif s and s == s.upper() and re.search(r"[A-ZÁÉÍÓÚÑ]{4}", s) and len(s) < 120 and not re.search(r"\d{3,}", s):
                iss = s
            i += 1
        if not rows:
            raise DayUnavailable(f"no sumario rows parsed in {pdfu}")
        out, exact = [], len(marks) == len(rows)
        for k, (rid, title, pg, sec_, iss_) in enumerate(rows):
            nxt = next((p for (_, _, p, _, _) in rows[k + 1:] if p >= pg), None)
            out.append({"doc_id": f"BOPLP-{d:%Y}-{rid}", "issuer": re.sub(r"^(ILUSTRE|ILTRE\.?|M\.\s*I\.)\s+", "", iss_), "issuer_raw": iss_, "title": " ".join(title.split()), "local": sec_ == "III",
                        "pdf": pdfu, "page": pg, "page_to": nxt or pg + 3, "html_url": u, "subsection": sec_, "seq": k if exact else None})
        return meta, out

    def text(self, f, it):
        _, _, (pages, pmap, full, marks) = self._load_pdf(f, it["pdf"])
        if it.get("seq") is not None:
            k = it["seq"]
            seg = full[marks[k]:marks[k + 1] if k + 1 < len(marks) else len(full)]
            seg = re.sub(r"(?m)^\s*Bolet[ií]n Oficial de la Provincia de Las Palmas\. N[uú]mero.*$|^\s*\d{1,6}\s+Bolet[ií]n Oficial de la Provincia de Las Palmas.*$", "", seg)
            rid = re.sub(r"^BOPLP-\d{4}-", "", it["doc_id"])
            fid = re.sub(r"(\d)(?=(\d{3})+(?!\d))", r"\1.", re.match(r"\d+", rid).group(0)) + (("-" + rid[-1]) if rid[-1].isalpha() else "") if len(re.match(r"\d+", rid).group(0)) > 3 else re.match(r"\d+", rid).group(0)
            j = seg.rfind(fid)
            if j > 0:
                seg = seg[:j + len(fid)]
            a = pmap.get(it["page"])
            return (f"{it['issuer']}\n{it['title']}\n{seg.replace(chr(12), chr(10)).strip()}", "pdf_text", f"{it['pdf']}#page={a}" if a else it["pdf"],
                    {"anuncio_number": seg.strip().split()[0], "printed_page": it["page"], "split_method": "anuncio_seq_marker(sumario_count==marker_count)", "id_footer_matched": j > 0})
        a, b = pmap.get(it["page"]), pmap.get(it["page_to"])
        if not a:
            raise IOError(f"printed page {it['page']} not found in pdf")
        b = b or min(a + 3, len(pages))
        t = "\n".join(pages[a - 1:b]).strip()
        k = _norm_txt(t).find(_norm_txt(it["issuer"])) if it.get("issuer") else -1
        if k > 0:              # drop the tail of the previous anuncio on the first page (offset on normalized text ~ raw)
            j = t.upper().find(it["issuer"].split()[-1].upper(), max(0, k - 200))
            t = t[max(0, t.rfind("\n", 0, j)):].strip() if j >= 0 else t
        return t, "pdf_text", f"{it['pdf']}#page={a}", {"pdf_pages": f"{a}-{b}", "printed_pages": f"{it['page']}-{it['page_to']}", "split_method": "printed_page_range"}


class Valencia(DayWalker):
    """BOP València (bop.dival.es, JSF 2 / PrimeFaces 8). No GET listing: the portal's own AJAX postbacks are replayed
    politely (same requests the browser makes, one session, >= min_interval between requests, no captcha/WAF):
      1. GET /bop/ (session + ViewState)
      2. DatePicker 'calen' viewChange (calen_month 0-based, calen_year) when the month changes, then dateSelect
         (calen_input=DD/MM/YYYY) -> 'boletines3' (Butlletí Núm. N of that day) + 'edictos' (DataGrid 'list')
      3. DataGrid 'list' page event (list_first=0, list_rows=100, further pages if >100)
      4. per target anuncio: commandLink 'list:i:j_idtNNN' -> 'dlgPDF' with a PrimeFaces dynamiccontent URL -> GET PDF.
    Items: seccion 'Municipis' (+ 'Mancomunitats Municipals') whose title matches TARGET_RE. doc_id = BOPV-<núm. registre>."""
    key, prov, home = "valencia", "46", "https://bop.dival.es/bop/"
    B = "https://bop.dival.es/bop/xhtml/portal.xhtml"
    min_interval = 1.5
    skip_weekdays = (5, 6)
    floor = "2002-01-01"

    def __init__(self):
        self.vs, self.month, self.cur_items = None, None, {}

    def _ajax(self, f, form, src, ev=None, execute=None, render=None, extra=None):
        d = {"javax.faces.partial.ajax": "true", "javax.faces.source": src, "javax.faces.partial.execute": execute or src,
             form: form, "javax.faces.ViewState": self.vs}
        if render:
            d["javax.faces.partial.render"] = render
        if ev:
            d["javax.faces.behavior.event"] = ev; d["javax.faces.partial.event"] = ev
        d.update(extra or {})
        host = "bop.dival.es"
        w = f.next.get(host, 0) - time.time()
        if w > 0:
            time.sleep(w)
        f.next[host] = time.time() + max(f.min, self.min_interval)
        r = f.s.post(self.B, data=d, timeout=120, headers={"Faces-Request": "partial/ajax", "X-Requested-With": "XMLHttpRequest"})
        f.nreq += 1
        if r.status_code != 200 or "<partial-response" not in r.text[:300]:
            if re.search(r"captcha|cf-chl|challenge-platform", r.text[:5000], re.I):
                raise CaptchaChallenge("challenge on postback")
            self.vs = None
            raise DayUnavailable(f"postback HTTP {r.status_code}")
        if "ViewExpiredException" in r.text[:3000]:
            self.vs = None; raise DayUnavailable("view expired")
        m = re.search(r'<update id="[^"]*ViewState[^"]*"><!\[CDATA\[([^\]]+)\]\]>', r.text)
        if m:
            self.vs = m.group(1)
        return r.text

    def _session(self, f):
        r = f.get(self.home)
        m = re.search(r'name="javax.faces.ViewState"[^>]*value="([^"]+)"', r.text)
        if not m:
            raise DayUnavailable("no ViewState")
        self.vs, self.month = m.group(1), None

    @staticmethod
    def _txt(h):
        return " ".join(html_lib.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<script.*?</script>", "", h, flags=re.S))).split())

    def _parse(self, x):
        out = []
        for blk in re.split(r'<div class="ui-datagrid-column', x)[1:]:
            sec = re.search(r'corner-all seccion[^"]*"[^>]*><div[^>]*>(.*?)</div></div>', blk, re.S)
            ent = re.search(r'corner-all entidad[^"]*"[^>]*><div[^>]*>(.*?)</div></div>', blk, re.S)
            a = re.search(r'id="(list:\d+:j_idt\d+)" href="#" class="ui-commandlink ui-widget enlace" aria-label="Anunci en PDF"[^>]*>(.*?)</a>', blk, re.S)
            reg = re.search(r'N[úu]m\. registre:\s*</span>\s*([\d/]+)', blk)
            if a:
                out.append({"sec": self._txt(sec.group(1)) if sec else "", "issuer": self._txt(ent.group(1)) if ent else "",
                            "title": self._txt(a.group(2)), "cmd": a.group(1), "reg": reg.group(1) if reg else None})
        return out

    def day(self, f, d):
        if not self.vs:
            self._session(f)
        if self.month != (d.year, d.month):
            self._ajax(f, "j_idt128", "calen", "viewChange", extra={"calen_month": str(d.month - 1), "calen_year": str(d.year), "calen_view": "date"})
            self.month = (d.year, d.month)
        x = self._ajax(f, "j_idt128", "calen", "dateSelect", render="busqueda boletines3 edictos", extra={"calen_input": f"{d:%d/%m/%Y}"})
        b = re.search(r'<update id="boletines3"><!\[CDATA\[(.*?)\]\]>', x, re.S)
        bt = self._txt(b.group(1)) if b else ""
        n = re.search(r"Butllet[ií] N[úu]m\.\s*(\d+)", bt)
        dm = re.search(r"\b(\d{1,2}) (?:de |d’|d')(\w+) de (\d{4})", bt)
        MES = {m: i + 1 for i, m in enumerate("gener febrer març abril maig juny juliol agost setembre octubre novembre desembre".split())}
        if not n or not dm or (int(dm.group(1)), MES.get(dm.group(2).lower()), int(dm.group(3))) != (d.day, d.month, d.year):
            return None, []                                   # no bulletin that day (portal falls back to latest)
        tot = re.search(r"Mostrant del \d+ al \d+ de (\d+)", x)
        total = int(tot.group(1)) if tot else 0
        items, first = [], 0
        while first < max(total, 1):
            y = self._ajax(f, "j_idt235", "list", "page", render="list",
                           extra={"list_pagination": "true", "list_first": str(first), "list_rows": "100", "list_encodeFeature": "true"})
            items += self._parse(y); first += 100
        out = []
        for it in items:
            local = it["sec"].startswith("Municipis") or it["sec"].startswith("Mancomunitats")
            out.append({"doc_id": f"BOPV-{(it['reg'] or '').replace('/', '-') or it['cmd']}", "issuer": it["issuer"].split(" / ")[0],
                        "issuer_raw": it["issuer"], "title": it["title"], "local": local, "cmd": it["cmd"], "subsection": it["sec"],
                        "ref": it["reg"], "html_url": self.home, "day": d.isoformat()})
        self._cur = d
        return {"number": n.group(1), "url": f"{self.home}#{d:%d/%m/%Y}"}, out

    def text(self, f, it):
        x = self._ajax(f, "j_idt235", it["cmd"], render="dlgPDF", execute="j_idt235", extra={it["cmd"]: it["cmd"]})
        m = re.search(r"file=([^&\"']+?)(?:#|&amp;|\")", x)
        if "Document no trobat" in x or not m:
            raise IOError("document not found")
        from urllib.parse import unquote
        u = urljoin(self.B, unquote(html_lib.unescape(m.group(1))))
        r = f.get(u)
        if r.status_code != 200 or r.content[:4] != b"%PDF":
            raise IOError(f"pdf HTTP {r.status_code}")
        t = pdf_text(r.content)
        if len(t.strip()) < 200:
            from common import scanned_pdfs as SP
            SP.append([SP.record(it["doc_id"], "es_bop_valencia", "ES", u, RP.policy(self.home, "robots_allowed_rfc9309"))])
        fn = re.search(r"download=([^&]+)", u)
        return t, "pdf_text", f"{self.home}#registre={it.get('ref')}", {"pdf_filename": fn.group(1) if fn else None,
                                                                      "fetch_method": "jsf_postback_replay"}


ADAPTERS = {"valencia": Valencia(), "laspalmas": LasPalmas(), "acoruna": ACoruna(), "alicante": Alicante(), "toledo": Toledo(), "pontevedra": Pontevedra(), "alava": Alava(), "bizkaia": Bizkaia(), "barcelona": Barcelona(),
            "tarragona": Barcelona("tarragona", "43", "https://www.dipta.cat/bopt/web", ("418", "428"), "BOPT"), "girona": Girona(), "bocm": BOCM(), "soria": Soria(), "borm": BORM(), "caceres": Caceres(), "gipuzkoa": Gipuzkoa(), "cordoba": Cordoba(),
            "granada": Saga("granada", "18", "https://bop.dipgra.es"), "leon": Saga("leon", "24", "https://bop.dipuleon.es"),
            "huesca": Saga("huesca", "22", "https://bop.dphuesca.es"),
            "avila": Avila(), "guadalajara": Guadalajara(), "lugo": Lugo(), "ourense": Ourense(), "cadiz": Cadiz(), "castellon": Castellon()}


def run_gazette(g, a):
    st = load_state(g)
    f, res = Fetcher(), Resolver()
    ad = ADAPTERS[g]
    f.min = max(f.min, getattr(ad, "min_interval", 0))
    ok, why = f.allowed(ad.home)
    if not ok:
        st.update(status="blocked", reason=why); save_state(g, st); log.info("%s blocked: %s", g, why); return
    stager = Stager(g, st)
    st["status"] = "running"; st["started"] = st.get("started") or now_utc(); save_state(g, st)
    try:
        ad.run(f, st, stager, res, a)
        st["status"] = "done_through_today"
    except Exception as e:  # noqa: BLE001
        log.exception("%s failed", g)
        st.update(status="error", reason=f"{type(e).__name__}: {e}"[:300])
    finally:
        try:
            stager.flush()
        except Exception:  # noqa: BLE001
            log.exception("final flush failed")
        st["requests"] = st.get("requests", 0) + f.nreq
        save_state(g, st)
    log.info("%s finished status=%s docs=%s unmatched=%s", g, st["status"], st.get("n_docs"), st.get("n_unmatched"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gazettes", default="bocm")
    ap.add_argument("--bocm-to-year", type=int, default=date.today().year)
    ap.add_argument("--bocm-from-year", type=int, default=2010)
    ap.add_argument("--flush-days", type=int, default=5)
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--max-days", type=int, default=0)
    ap.add_argument("--floor", default=None, help="oldest date (YYYY-MM-DD) for day-walker gazettes")
    ap.add_argument("--forward", action="store_true", help="new-issues pass (head -> today) instead of the backward walk")
    ap.add_argument("--forward-from", default="2026-10-10")
    ap.add_argument("--every-hours", type=float, default=0, help="with --forward: repeat the pass every N hours")
    a = ap.parse_args()
    if a.forward:
        while True:
            ths = [threading.Thread(target=run_forward, args=(g, a)) for g in a.gazettes.split(",")]
            for t in ths:
                t.start()
            for t in ths:
                t.join()
            if not a.every_hours:
                return
            time.sleep(a.every_hours * 3600)
    ths = [threading.Thread(target=run_gazette, args=(g, a)) for g in a.gazettes.split(",")]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    bad = [g for g in a.gazettes.split(",") if load_state(g).get("status") == "error"]
    if bad:                     # non-zero exit -> the supervisor relaunches from checkpoint (with its back-off)
        log.warning("gazettes ended in error: %s", bad); sys.exit(3)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    main()
