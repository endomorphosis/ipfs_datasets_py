#!/usr/bin/env python3
"""Japan local-government rule databases (例規集) crawler — asia_latam lane.

Vendors (template families):
  gyosei     Gyosei Reiki-Base static export  (.../reiki_menu.html -> reiki_kana/r_50_*.html -> reiki_honbun/*.html)
             (own-site hosts, reiki.* hosts, g-reiki.net)
  d1w        Daiichi Hoki D1-Law static export (.../d1w_reiki/reiki.html -> mokuji_index_index.html -> index_NNN.html -> H.../H..._j.html)
  d1ops      Daiichi Hoki opensearch app       (ops-jg.d1-law.com/opensearch/SrMjF01/init?jctcd=...)
  joureikun  Joureikun / LegalCRUD             (lg|public.joureikun.jp/<body>/reiki/urllist.txt -> act/*.html)
Not yet: legal-square (Gyosei JSF app), h-chosonkai (unreachable from box).

Writes SCHEMA.md v1 staged jsonl to /workspace/world_law/staging/asia_latam/JP/<place_key>.<batch>.jsonl
(atomic .tmp + fsync + rename, validated with schema.validate_record). State/logs under staging/asia_latam/_*.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import argparse, concurrent.futures as cf, hashlib, html as htmlmod, json, logging, os, re, sys, threading, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
import schema as S  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.rfc9309 import Robots  # noqa: E402  (urllib.robotparser ignores * and $ wildcards)

HERE = Path(__file__).resolve().parent
STAGE = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/asia_latam"))
OUT = STAGE / "JP"
UNMATCHED = STAGE / "_unmatched" / "JP"
QUAR = STAGE / "_quarantine" / "JP"
STATE = STAGE / "_state" / "jp"
ROBOTS_DIR = STAGE / "_robots"
UA = "JusticeDAO-WorldLaw/1.0 (+https://github.com/endomorphosis/ipfs_datasets_py; municipal law research crawler; polite 1 req/s/host)"
BATCH_SIZE = 250
log = logging.getLogger("jp_reiki")

# ----------------------------------------------------------------------------- helpers
ERA = {"明治": 1867, "大正": 1911, "昭和": 1925, "平成": 1988, "令和": 2018}
Z2H = str.maketrans("０１２３４５６７８９", "0123456789")


def jdate(s):
    """'平成3年9月30日' / '令和５年１２月１３日' / '平成元年1月17日' -> ISO date (or YYYY-MM / YYYY)."""
    if not s:
        return None
    s = s.translate(Z2H).replace("元年", "1年")
    m = re.search(r"(明治|大正|昭和|平成|令和)\s*(\d+)年(?:\s*(\d+)月(?:\s*(\d+)日)?)?", s)
    if not m:
        m2 = re.search(r"((?:18|19|20)\d\d)年(?:(\d+)月(?:(\d+)日)?)?", s)
        if not m2:
            return None
        y, mo, d = int(m2.group(1)), m2.group(2), m2.group(3)
    else:
        y, mo, d = ERA[m.group(1)] + int(m.group(2)), m.group(3), m.group(4)
    if mo and d:
        return f"{y:04d}-{int(mo):02d}-{int(d):02d}"
    if mo:
        return f"{y:04d}-{int(mo):02d}"
    return f"{y:04d}"


def doc_type_for(number, title=""):
    s = (number or "") + " " + (title or "")
    if re.search(r"条例", number or "") or (not number and title.endswith("条例")):
        return "ordinance"
    if "告示" in (number or "") or "公告" in (number or ""):
        return "decision"
    return "regulation"


BLOCK_TAGS = ["p", "div", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "dt", "dd", "ul", "ol", "blockquote", "pre"]


def html_to_text(h):
    soup = BeautifulSoup(h, "lxml")
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for t in soup.find_all(BLOCK_TAGS):
        t.insert_after("\n")
    txt = soup.get_text("")
    txt = re.sub(r"[ \t]+", " ", txt)
    txt = re.sub(r"[ \t\u3000]*\n[ \t\u3000\n]*", "\n", txt)
    return txt.strip()


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# Coordinator decision 2026-10-10 15:34 PT (RFC 9309): an unreachable robots.txt == disallow-all.
# Coordinator update 2026-10-10 15:49 PT: ops-jg.d1-law.com serves a real HTTP 404 for /robots.txt (RFC 9309: allow),
# so that ONE exact host is re-enabled (max 1 req/s). Every other *.d1-law.com host (en3-jg, en5-jg, any other)
# stays blocked. Redirects are followed manually and re-checked against this list, so nothing can slip in via 3xx.
ROBOTS_NOT_SERVED = set()
ALLOWED_EXACT_HOSTS = {"ops-jg.d1-law.com"}
HOST_MIN_INTERVAL = {"ops-jg.d1-law.com": 1.0}
BLOCKED_HOST_SUFFIXES = {
    "d1-law.com": "robots_unreachable",      # en3-jg/en5-jg drop /robots.txt -> RFC 9309 disallow-all
    "g-reiki.net": "unreachable",            # TLS dropped from box egress; do not work around
    "h-chosonkai.gr.jp": "unreachable",      # connect timeouts from box; do not work around
}


def blocked_reason(url):
    host = urlparse(url).netloc.lower().split(":")[0]
    if host in ALLOWED_EXACT_HOSTS:
        return None
    for suf, why in BLOCKED_HOST_SUFFIXES.items():
        if host == suf or host.endswith("." + suf):
            return why
    return None


class Unreachable(Exception):
    pass


class RobotsDisallowed(Exception):
    pass


class HostBlocked(Exception):
    pass


# ----------------------------------------------------------------------------- polite fetcher
class HostGate:
    def __init__(self, interval):
        self.interval = interval
        self.lock = threading.Lock()
        self.next = {}
        self.hostlocks = {}
        self.dead = {}  # host -> reason
        self.robots = {}

    def hostlock(self, host):
        with self.lock:
            return self.hostlocks.setdefault(host, threading.Lock())

    def wait(self, host):
        hl = self.hostlock(host)
        with hl:
            t = self.next.get(host, 0)
            d = t - time.time()
            if d > 0:
                time.sleep(d)
            self.next[host] = time.time() + max(self.interval, HOST_MIN_INTERVAL.get(host.lower().split(':')[0], 0))


GATE = None


class Fetcher:
    def __init__(self, timeout=40):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "ja,en;q=0.5"})
        self.timeout = timeout
        self.nreq = 0

    def robots_ok(self, url):
        p = urlparse(url)
        host = p.netloc
        key = f"{p.scheme}://{host}"
        rp = GATE.robots.get(key)
        if rp is None:
            try:
                GATE.wait(host)
                r = self.s.get(key + "/robots.txt", timeout=20, allow_redirects=True)
                self.nreq += 1
                if any(blocked_reason(h.url) for h in r.history) or blocked_reason(r.url):
                    raise HostBlocked(f"robots.txt redirected to blocked host: {r.url}")
                if r.status_code >= 500:
                    rp = Robots(disallow_all=True)          # RFC 9309: server error -> disallow all
                elif r.status_code >= 400:
                    rp = Robots(allow_all=True)             # RFC 9309: 4xx (unavailable) -> allow
                elif "<html" in r.text[:500].lower():
                    rp = Robots(allow_all=True)             # HTML soft-404 instead of a robots file
                else:
                    rp = Robots(r.text)
                    ROBOTS_DIR.mkdir(parents=True, exist_ok=True)
                    (ROBOTS_DIR / f"{host}.txt").write_text(r.text)
            except requests.RequestException as e:
                GATE.dead[host] = f"robots fetch failed: {type(e).__name__}"
                GATE.robots[key] = "dead"
                raise Unreachable(host)
            GATE.robots[key] = rp
        if rp == "dead":
            raise Unreachable(host)
        return rp.can_fetch(UA, url) and rp.can_fetch("*", url)

    def get(self, url, method="GET", data=None, headers=None, tries=3, check_robots=True):
        host = urlparse(url).netloc
        why = blocked_reason(url)
        if why:
            raise HostBlocked(f"{why}: {host}")
        if host in GATE.dead:
            raise Unreachable(host)
        if check_robots and not self.robots_ok(url):
            raise RobotsDisallowed(url)
        last = None
        for i in range(tries):
            GATE.wait(host)
            try:
                r = self._request_checked(method, url, data, headers, check_robots)
                if r.status_code in (429, 503):
                    time.sleep(30 * (i + 1))
                    last = f"HTTP {r.status_code}"
                    continue
                return r
            except (requests.ConnectionError, requests.Timeout) as e:
                last = type(e).__name__
                time.sleep(5 * (i + 1))
        if host in ROBOTS_NOT_SERVED:
            raise IOError(f"{url}: {last} (host drops unknown paths)")
        if last in ("ConnectTimeout", "ConnectionError"):
            GATE.dead[host] = last
        raise Unreachable(f"{url}: {last}")

    def _request_checked(self, method, url, data, headers, check_robots, max_hops=5):
        """Follow redirects manually; every hop is re-checked against the block list and robots.txt."""
        cur, m, d = url, method, data
        for _ in range(max_hops + 1):
            r = self.s.request(m, cur, data=d, headers=headers, timeout=self.timeout, allow_redirects=False)
            self.nreq += 1
            if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                nxt = urljoin(cur, r.headers["location"])
                why = blocked_reason(nxt)
                if why:
                    raise HostBlocked(f"{why}: {urlparse(nxt).netloc}")
                if check_robots and not self.robots_ok(nxt):
                    raise RobotsDisallowed(nxt)
                if r.status_code in (301, 302, 303) and m == "POST":
                    m, d = "GET", None
                cur = nxt
                GATE.wait(urlparse(cur).netloc)
                continue
            return r
        raise IOError(f"too many redirects: {url}")

    @staticmethod
    def decode(r):
        b = r.content
        enc = None
        ct = r.headers.get("content-type", "")
        m = re.search(r"charset=([\w-]+)", ct, re.I)
        if m:
            enc = m.group(1)
        if not enc:
            m = re.search(rb'charset=["\']?([\w-]+)', b[:3000], re.I)
            if m:
                enc = m.group(1).decode()
        enc = (enc or "utf-8").lower()
        if enc in ("shift_jis", "sjis", "x-sjis", "shift-jis", "windows-31j"):
            enc = "cp932"
        try:
            return b.decode(enc)
        except (UnicodeDecodeError, LookupError):
            for e in ("utf-8", "cp932", "euc_jp"):
                try:
                    return b.decode(e)
                except UnicodeDecodeError:
                    pass
            return b.decode("utf-8", "replace")

    def text(self, url, **kw):
        r = self.get(url, **kw)
        if r.status_code != 200:
            raise IOError(f"HTTP {r.status_code} {url}")
        return self.decode(r)


# ----------------------------------------------------------------------------- vendor adapters
# Each adapter: list_docs(f, seed) -> (meta, [listing dicts with 'doc_id','url', ...]); fetch_doc(f, seed, item) -> dict


def _clean(s):
    return re.sub(r"\s+", " ", htmlmod.unescape(re.sub(r"<[^>]+>", "", s or ""))).strip()


class Gyosei:
    platform = "jp_reiki_gyosei"

    def base(self, url):
        u = url.split("#")[0].split("?")[0]
        if u.endswith(".html") or u.endswith(".htm"):
            u = u.rsplit("/", 1)[0] + "/"
        if not u.endswith("/"):
            u += "/"
        return u

    def list_docs(self, f, seed):
        b = seed.get("base") or self.base(seed["url"])
        try:
            kana = f.text(b + "reiki_kana/kana_default.html")
        except IOError:
            kana = ""
        pages = sorted(set(re.findall(r'href="(r_50_[a-z]+\.html)"', kana)))
        src = "reiki_kana/"
        if not pages:
            tk = f.text(b + "reiki_taikei/taikei_default.html")
            pages = sorted(set(re.findall(r'href="(r_taikei_[\d_]+\.html)"', tk)))
            src = "reiki_taikei/"
        items = {}
        asof = None
        for p in pages:
            t = f.text(b + src + p)
            if not asof:
                m = re.search(r"内容現在\s*([^<&]+)", t)
                asof = jdate(m.group(1)) if m else None
            for row in re.findall(r"<tr>(.*?)</tr>", t, re.S):
                m = re.search(r'<a href="\.\./reiki_honbun/([^"#]+?)\.html"[^>]*>(.*?)</a>', row, re.S)
                if not m:
                    continue
                tds = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
                did = m.group(1)
                items.setdefault(did, dict(doc_id=did, url=b + "reiki_honbun/" + did + ".html", title=_clean(m.group(2)),
                                           date_raw=_clean(tds[1]).lstrip("◆") if len(tds) > 1 else None,
                                           number=_clean(tds[2]) if len(tds) > 2 else None))
        return {"as_of": asof, "base": b}, list(items.values())

    def fetch_doc(self, f, seed, it):
        r = f.get(it["url"])
        if r.status_code != 200:
            raise IOError(f"HTTP {r.status_code}")
        raw = f.decode(r)
        soup = BeautifulSoup(raw, "lxml")
        main = soup.find(id="primary") or soup.body or soup
        sec = soup.find(id="secondary")
        eff = None
        if sec:
            for p in sec.find_all("p", class_="datenumber-area"):
                if "施行" in p.get_text():
                    eff = jdate(p.get_text())
        title = it.get("title") or (soup.title.get_text(strip=True) if soup.title else None)
        number = it.get("number")
        if number in ("種別なし", ""):
            number = None
        return dict(raw=raw, html=str(main), title=title, number=number, adopted=jdate(it.get("date_raw")), version_effective=eff)


class D1W:
    platform = "jp_reiki_d1law"

    def base(self, url):
        u = url.split("?")[0]
        return u.rsplit("/", 1)[0] + "/"

    def list_docs(self, f, seed):
        b = self.base(seed["url"])
        try:
            idx = f.text(b + "mokuji_index_index.html")
        except IOError:
            idx = f.text(seed["url"])  # variant top pages (e.g. reiki.htm) link index_NNN.html directly
        pages = list(dict.fromkeys(re.findall(r'href=["\']?(index_\d+\.html)', idx, re.I)))
        items = {}
        for p in pages:
            t = f.text(b + p)
            for row in re.findall(r"<TR>(.*?)</TR>", t, re.S | re.I):
                m = re.search(r"OpenResDataWin\('([A-Za-z0-9]+)'\)[^>]*>(.*?)</A>", row, re.S | re.I)
                if not m:
                    continue
                tds = re.findall(r"<TD[^>]*>(.*?)</TD>", row, re.S | re.I)
                did = m.group(1)
                items.setdefault(did, dict(doc_id=did, url=f"{b}{did}/{did}_j.html", title=_clean(m.group(2)),
                                           date_raw=_clean(tds[2]) if len(tds) > 2 else None,
                                           number=_clean(tds[3]) if len(tds) > 3 else None,
                                           dept=_clean(tds[4]) if len(tds) > 4 else None))
        top = f.text(b + "reiki.html") if not seed.get("_top") else seed["_top"]
        m = re.search(r"内容現在[：:]\s*([^<]+)", top)
        return {"as_of": jdate(m.group(1)) if m else None, "base": b}, list(items.values())

    def fetch_doc(self, f, seed, it):
        r = f.get(it["url"])
        if r.status_code != 200:
            raise IOError(f"HTTP {r.status_code}")
        raw = f.decode(r)
        soup = BeautifulSoup(raw, "lxml")
        for t in soup(["script", "style"]):
            t.decompose()
        main = soup.body or soup
        return dict(raw=raw, html=str(main), title=it.get("title"), number=it.get("number"), adopted=jdate(it.get("date_raw")), dept=it.get("dept"))


class Joureikun:
    platform = "jp_reiki_joureikun"

    def base(self, url):
        p = urlparse(url)
        parts = [x for x in p.path.split("/") if x]
        body = parts[0]
        return f"{p.scheme}://{p.netloc}/{body}/reiki/"

    def list_docs(self, f, seed):
        p = urlparse(seed["url"])
        parts = [x for x in p.path.split("/") if x]
        cands = [self.base(seed["url"]), seed["url"].split("?")[0].rsplit("/", 1)[0] + "/"]
        if parts:
            cands.append(f"{p.scheme}://{p.netloc}/{parts[0]}/")
        t = None
        for b in dict.fromkeys(cands):
            r = f.get(b + "urllist.txt")
            if r.status_code == 200 and "/act/" in r.text:
                t = f.decode(r)
                break
        if t is None:
            raise IOError("joureikun urllist.txt not found (seed URL may be stale)")
        items = {}
        for line in t.splitlines():
            m = re.search(r"/act/(\d+)\.html$", line.strip())
            if m:
                did = m.group(1)
                items.setdefault(did, dict(doc_id=did, url=f"{b}act/{did}.html"))
        return {"as_of": None, "base": b}, list(items.values())

    def fetch_doc(self, f, seed, it):
        r = f.get(it["url"])
        if r.status_code != 200:
            raise IOError(f"HTTP {r.status_code}")
        raw = f.decode(r)
        soup = BeautifulSoup(raw, "lxml")
        title = soup.select_one(".mainTitle")
        title = title.get_text(strip=True) if title else None
        dn = soup.select_one("nav .date")
        dn = dn.get_text(strip=True) if dn else ""
        m = re.match(r"(.*?日)(.*)$", dn)
        number = m.group(2).strip() if m else None
        adopted = jdate(m.group(1)) if m else None
        for t in soup(["script", "style", "nav"]):
            t.decompose()
        main = soup.select_one(".mainWrap") or soup.body or soup
        return dict(raw=raw, html=str(main), title=title, number=number or None, adopted=adopted)


class D1Ops:
    platform = "jp_reiki_d1law_opensearch"
    B = "https://ops-jg.d1-law.com/opensearch"

    def list_docs(self, f, seed):
        jct = re.search(r"jctcd=([A-Za-z0-9]+)", seed["url"]).group(1)
        init = f.text(f"{self.B}/SrMjF01/init?jctcd={jct}")
        codes = list(dict.fromkeys(re.findall(r"mkjG\('([0-9:_]+)'\)", init)))
        leaves = [c for c in codes if not any(o.startswith(c + "_") for o in codes)]
        form = dict(re.findall(r'<input type="hidden" name="([^"]+)" id="[^"]*" value="([^"]*)"', init))
        items = {}
        hdr = {"X-Requested-With": "XMLHttpRequest"}
        for c in leaves:
            fd = dict(form, typeSearch="SrMj_Genko", typeSearchFacet="SrMj_Genko", mokujicd=c)
            t = f.text(f"{self.B}/SrMjF01/search?ajax=1", method="POST", data=fd, headers=hdr)
            pages_seen = 0
            while True:
                self._parse(t, jct, items, c)
                total = re.search(r"該当例規：\s*(\d+)\s*件", t)
                total = int(total.group(1)) if total else 0
                offs = sorted(set(int(x) for x in re.findall(r"doPaging\('(\d+)'\)", t)))
                nxt = [o for o in offs if o > pages_seen]
                if not nxt or pages_seen > 200:
                    break
                pages_seen = nxt[0]
                t = f.text(f"{self.B}/SrMjF01/paging?ajax=1", method="POST", data={"offset": str(pages_seen)}, headers=hdr)
        m = re.search(r"(令和\S+?日)\s*時点", init)
        return {"as_of": jdate(m.group(1)) if m else None, "jctcd": jct}, list(items.values())

    def _parse(self, t, jct, items, cat):
        for row in re.findall(r"<tr\s*>(.*?)</tr>", t, re.S):
            m = re.search(r"doViewJobunFromJsp\('([^']+)',\s*'([^']+)'.*?>(.*?)</a>(.*?)</p>", row, re.S)
            if not m:
                continue
            houcd = m.group(2)
            sub = _clean(m.group(4))
            mm = re.match(r"[（(](.*?日)(.*?)[）)]", sub)
            tds = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
            items.setdefault(houcd, dict(doc_id=houcd, url=f"{self.B}/SrJbF01/init?jctcd={jct}&houcd={houcd}",
                                         title=_clean(m.group(3)), date_raw=mm.group(1) if mm else None,
                                         number=(mm.group(2).strip() if mm else None),
                                         last_amended=jdate(_clean(tds[3])) if len(tds) > 3 else None, category=cat))

    def fetch_doc(self, f, seed, it):
        r = f.get(it["url"])
        if r.status_code != 200:
            raise IOError(f"HTTP {r.status_code}")
        raw = f.decode(r)
        soup = BeautifulSoup(raw, "lxml")
        main = soup.find(id="result")
        if main is None:
            raise IOError("no #result")
        for t in main.select(".searchexclude"):
            t.decompose()
        return dict(raw=raw, html=str(main), title=it.get("title"), number=it.get("number"), adopted=jdate(it.get("date_raw")),
                    last_amended=it.get("last_amended"))


VENDORS = {"gyosei": Gyosei(), "d1w": D1W(), "joureikun": Joureikun(), "d1ops": D1Ops()}


def classify(url):
    p = urlparse(url)
    h, path = p.netloc, p.path
    if "ops-jg.d1-law.com" in h:
        return "d1ops"
    if "d1w_reiki" in path:
        return "d1w"
    if "joureikun" in h:
        return "joureikun"
    if "legal-square" in h:
        return "legal_square"
    if "h-chosonkai" in h:
        return "h_chosonkai"
    if path.endswith("reiki_menu.html"):
        return "gyosei"
    return "unknown"


def detect(f, seed):
    """Fetch an unknown seed URL and look for a known template."""
    url = seed["url"]
    seen = set()
    for _ in range(4):
        if url in seen:
            break
        seen.add(url)
        r = f.get(url)
        t = f.decode(r)
        final = r.url
        if 'id="gyosei_reikibase"' in t or "Reiki-Base" in t:
            if "reiki_kana/kana_default.html" in t or "reiki_taikei/taikei_default.html" in t:
                return "gyosei", final
        if "mokuji_index.html" in t or "mokuji_bunya.html" in t:
            return "d1w", final
        if "SJSrbLogin" in final or "legal-square" in final:
            return "legal_square", final
        # follow frames / meta-refresh / obvious reiki links
        cand = re.findall(r'<frame[^>]+src="([^"]+)"', t, re.I) + re.findall(r'url=([^"\'>;]+)', " ".join(re.findall(r'<meta[^>]+refresh[^>]*>', t, re.I)), re.I)
        cand += [h for h in re.findall(r'href="([^"]+)"', t) if re.search(r"reiki_menu\.html|d1w_reiki/reiki\.html|joureikun|ops-jg\.d1-law|legal-square", h)]
        if not cand:
            break
        nxt = urljoin(final, cand[0].strip())
        k = classify(nxt)
        if k not in ("unknown",):
            return k, nxt
        url = nxt
    return "unknown", url


# ----------------------------------------------------------------------------- staging writer
class PlaceWriter:
    def __init__(self, seed, vendor, state):
        self.seed, self.vendor, self.state = seed, vendor, state
        self.buf = []
        pid = seed.get("place_id")
        if pid:
            self.pkey = S.place_key(pid, None, "JP")
            self.dir = OUT
        else:
            self.pkey = seed["seed_id"]
            self.dir = UNMATCHED
        self.dir.mkdir(parents=True, exist_ok=True)

    def add(self, rec):
        self.buf.append(rec)
        if len(self.buf) >= BATCH_SIZE:
            self.flush()

    def flush(self):
        if not self.buf:
            return
        good, bad = [], []
        for r in self.buf:
            errs = S.validate_record(r) if self.seed.get("place_id") else []
            (bad if errs else good).append((r, errs))
        if bad:
            QUAR.mkdir(parents=True, exist_ok=True)
            with open(QUAR / f"{self.pkey}.{self.seed['seed_id']}.jsonl", "a", encoding="utf-8") as q:
                for r, e in bad:
                    q.write(json.dumps({"reasons": e, "record": r}, ensure_ascii=False) + "\n")
        if good:
            self.state["batch"] = self.state.get("batch", 0) + 1
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%MZ")
            final = self.dir / f"{self.pkey}.{self.seed['seed_id']}-{self.vendor}-p{self.state['batch']:04d}-{ts}.jsonl"
            # temp name is a dot-file (ignored by run_loop) with .jsonl suffix so schema.validate_file can read it
            tmp = final.with_name("." + final.name + ".tmp.jsonl")
            with tmp.open("w", encoding="utf-8") as fh:
                for r, _ in good:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            if self.seed.get("place_id"):
                v = S.validate_file(tmp, expect_place_key=self.pkey)
                if not v["ok"]:
                    raise RuntimeError(f"validate_file failed: {v['errors'][:3]} {v['file_errors']}")
            os.rename(tmp, final)
            self.state.setdefault("files", []).append(final.name)
        for r, _ in good + bad:
            self.state["done"][r["doc_id"]] = 1
        self.state["n_docs"] = self.state.get("n_docs", 0) + len(good)
        self.state["n_bad"] = self.state.get("n_bad", 0) + len(bad)
        self.buf = []
        save_state(self.seed["seed_id"], self.state)


def load_state(sid):
    p = STATE / f"{sid}.json"
    if p.exists():
        return json.loads(p.read_text())
    return {"seed_id": sid, "status": "new", "done": {}}


def save_state(sid, st):
    STATE.mkdir(parents=True, exist_ok=True)
    p = STATE / f"{sid}.json"
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False))
    os.replace(tmp, p)


def make_record(seed, vendor_key, adapter, it, d, meta):
    pid = seed.get("place_id")
    raw = d.pop("raw")
    text = html_to_text(d["html"])
    rec = {
        "place_id": pid,
        "country_code": "JP",
        "doc_id": it["doc_id"],
        "source_platform": adapter.platform,
        "source_url": it["url"],
        "doc_type": doc_type_for(d.get("number"), d.get("title") or ""),
        "language": "ja",
        "html_title": d.get("title") or d.get("number"),
        "title_native": d.get("title"),
        "number": d.get("number"),
        "adopted_date": d.get("adopted"),
        "published_date": None,
        "effective_date": None,
        "in_force": True,
        "consolidated": True,
        "content_format": "html",
        "html": d["html"],
        "text": text,
        "retrieved_at": now_utc(),
        # place-level
        "place_name": seed["name"],
        "qid": seed.get("qid"),
        "iso_3166_2": f"JP-{seed['pref_code']}",
        "admin_level": seed.get("admin_level") or ("adm1" if seed.get("is_pref") else "municipality"),
        "platform": adapter.platform,
        "platform_place_id": meta.get("jctcd") or meta.get("base") or seed["url"],
        # extras (ignored by normalizer; kept for provenance)
        "jis_code": seed.get("jis_code"),
        "vendor": vendor_key,
        "prefecture": seed["pref"],
        "seed_url": seed["url"],
        "collection_as_of": meta.get("as_of"),
        "version_effective_date": d.get("version_effective"),
        "last_amended_date": d.get("last_amended"),
        "department": d.get("dept"),
        "content_sha256": hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest(),
        "raw_bytes": len(raw.encode("utf-8", "replace")),
    }
    return {k: v for k, v in rec.items() if v is not None or k in ("place_id",)}


def crawl_seed(seed, max_docs=None):
    sid = seed["seed_id"]
    st = load_state(sid)
    why = blocked_reason(seed["url"])
    if why:
        if st.get("status") != "blocked":
            st.update(status="blocked", reason=why, blocked_host=urlparse(seed["url"]).netloc, blocked_at=now_utc())
            save_state(sid, st)
        return st
    if st.get("status") in ("done", "skipped", "blocked") and not max_docs:
        return st
    f = Fetcher()
    vendor = seed.get("vendor") or classify(seed["url"])
    t0 = time.time()
    try:
        if vendor == "unknown":
            vendor, newurl = detect(f, seed)
            seed = dict(seed, url=newurl)
            st["detected_url"] = newurl
        st["vendor"] = vendor
        if vendor not in VENDORS:
            st.update(status="skipped", reason=f"vendor {vendor} not supported")
            save_state(sid, st)
            return st
        ad = VENDORS[vendor]
        meta, items = ad.list_docs(f, seed)
        st.update(n_listed=len(items), as_of=meta.get("as_of"), status="running", started=st.get("started") or now_utc())
        save_state(sid, st)
        w = PlaceWriter(seed, vendor, st)
        n = 0
        errs = 0
        for it in items:
            if it["doc_id"] in st["done"]:
                continue
            if max_docs and n >= max_docs:
                break
            try:
                d = ad.fetch_doc(f, seed, it)
                w.add(make_record(seed, vendor, ad, it, d, meta))
                n += 1
            except RobotsDisallowed:
                st.setdefault("robots_disallowed", []).append(it["url"])
                st["done"][it["doc_id"]] = 1
            except (Unreachable, HostBlocked):
                raise
            except Exception as e:  # noqa: BLE001
                errs += 1
                st.setdefault("doc_errors", {})[it["doc_id"]] = f"{type(e).__name__}: {e}"[:200]
                if errs > 50 and errs > n:
                    raise RuntimeError(f"too many doc errors ({errs})")
        w.flush()
        st["status"] = "partial" if max_docs else "done"
        st["finished"] = now_utc()
    except HostBlocked as e:
        st.update(status="blocked", reason=str(e).split(":")[0], blocked_host=str(e).split(": ", 1)[-1])
    except RobotsDisallowed as e:
        st.update(status="skipped", reason=f"robots.txt disallow: {e}")
    except Unreachable as e:
        st.update(status="unreachable", reason=str(e)[:300])
    except Exception as e:  # noqa: BLE001
        st.update(status="error", reason=f"{type(e).__name__}: {e}"[:300])
    st["elapsed_s"] = round(st.get("elapsed_s", 0) + time.time() - t0, 1)
    st["requests"] = st.get("requests", 0) + f.nreq
    save_state(sid, st)
    log.info("%s %s %s vendor=%s listed=%s docs=%s status=%s %s", sid, seed["pref"], seed["name"], st.get("vendor"),
             st.get("n_listed"), st.get("n_docs"), st["status"], st.get("reason", ""))
    return st


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default=str(HERE / "seeds_places.json"))
    ap.add_argument("--vendors", default="", help="comma list: gyosei,d1w,d1ops,joureikun,unknown")
    ap.add_argument("--ids", default="", help="comma list of seed ids")
    ap.add_argument("--per-vendor", type=int, default=0, help="only first N seeds per vendor")
    ap.add_argument("--max-docs", type=int, default=0, help="validation: cap docs per seed (state=partial)")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--interval", type=float, default=1.0, help="seconds between requests per host")
    ap.add_argument("--per-host", type=int, default=2)
    ap.add_argument("--retry-errors", action="store_true")
    a = ap.parse_args()
    global GATE
    GATE = HostGate(a.interval)
    STAGE.mkdir(parents=True, exist_ok=True)
    seeds = json.load(open(a.seeds))
    for s in seeds:
        s["vendor0"] = classify(s["url"])
    if a.ids:
        ids = set(a.ids.split(","))
        seeds = [s for s in seeds if s["seed_id"] in ids]
    if a.vendors:
        vs = set(a.vendors.split(","))
        seeds = [s for s in seeds if s["vendor0"] in vs]
    if a.per_vendor:
        c = {}
        keep = []
        for s in seeds:
            if c.get(s["vendor0"], 0) < a.per_vendor:
                keep.append(s)
                c[s["vendor0"]] = c.get(s["vendor0"], 0) + 1
        seeds = keep
    if a.retry_errors:
        for s in seeds:
            st = load_state(s["seed_id"])
            if st.get("status") in ("error", "unreachable", "running", "partial"):
                st["status"] = "retry"
                save_state(s["seed_id"], st)
    # host-aware scheduler: at most --per-host seeds active per host (shared vendor hosts are serialized by HostGate anyway)
    pending = list(seeds)
    active = {}
    cv = threading.Condition()

    def host_of(s):
        return urlparse(s["url"]).netloc

    def worker():
        while True:
            with cv:
                while True:
                    if not pending:
                        return
                    pick = next((s for s in pending if active.get(host_of(s), 0) < a.per_host), None)
                    if pick:
                        pending.remove(pick)
                        active[host_of(pick)] = active.get(host_of(pick), 0) + 1
                        break
                    cv.wait(10)
            try:
                crawl_seed(pick, a.max_docs or None)
            except Exception as e:  # noqa: BLE001
                log.exception("seed %s crashed: %s", pick["seed_id"], e)
            finally:
                with cv:
                    active[host_of(pick)] -= 1
                    cv.notify_all()

    log.info("seeds=%d workers=%d interval=%.2fs per_host=%d", len(pending), a.workers, a.interval, a.per_host)
    ths = [threading.Thread(target=worker, daemon=True) for _ in range(a.workers)]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    log.info("finished; dead hosts: %s", json.dumps(GATE.dead, ensure_ascii=False))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    main()
