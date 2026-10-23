#!/usr/bin/env python3
"""Japan: Gyosei Super Reiki-Base on *.legal-square.com (HAS-Shohin JSF app), 86 bodies.

Access = exactly what an anonymous visitor's browser does (coordinator decision 2026-10-10; gyosei.jp terms of use
contain no ban on automated access; ordinances are not copyrighted, Copyright Act art. 13):
  GET SJSrbLogin.jsf -> the page's onload auto-submit of frm01 ('yougo') with its ViewState -> 例規一覧 (no credentials,
  no account, no captcha) -> 体系 tab -> each top-level 類 (全検索) -> paged list (A4J pager) -> viewer
  OpenEditor.jsf?selectedIdxForEditor=<row> -> SVDocumentView -> /action/get-honmon-info (paged honmon HTML).
Politeness: robots.txt per host via RFC 9309 (unreachable/5xx -> skip host), max 1 request/second per host, at most
--workers hosts in parallel (default 2), identified UA. Resumable: _state/jp_legal_square/<seed>.json (done doc_ids +
per-class progress). Staging: JP/<place_key>.<seed>-legalsquare-pNNNN-<ts>.jsonl (atomic, validate_file before rename).
"""
import unicodedata
import argparse, concurrent.futures as cf, hashlib, html as htmlmod, json, logging, math, os, re, sys, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import jp_reiki as J  # noqa: E402  (schema S, jdate, doc_type_for, html_to_text, Robots, UA)
S = J.S
STATE = J.STAGE / "_state" / "jp_legal_square"
LOG = logging.getLogger("legal_square")
PLATFORM = "jp_legal_square_reikibase"


def vs(h):
    m = re.search(r'name="javax\.faces\.ViewState"[^>]*value="([^"]*)"', h) or re.search(r'value="([^"]*)"[^>]*name="javax\.faces\.ViewState"', h)
    return m.group(1) if m else None


class SessionLost(Exception):
    pass


class Blocked(Exception):
    pass


class LS:
    def __init__(self, host, interval=1.05):
        self.host, self.interval = host, interval
        self.base = f"https://{host}/HAS-Shohin/page/"
        self.s = requests.Session(); self.s.headers["User-Agent"] = J.UA
        self.t = 0.0; self.nreq = 0
        self.robots = None

    def _check(self, url):
        if self.robots is None:
            try:
                r = self.s.get(f"https://{self.host}/robots.txt", timeout=60, allow_redirects=True); self.nreq += 1; self.t = time.time()
            except requests.RequestException as e:
                raise Blocked(f"robots_unreachable: {type(e).__name__}")
            if r.status_code >= 500:
                raise Blocked(f"robots_http_{r.status_code}")
            ok_txt = r.status_code == 200 and "text/plain" in (r.headers.get("content-type") or "")
            self.robots = J.Robots(r.text) if ok_txt else J.Robots(allow_all=True)
        if not self.robots.can_fetch(J.UA, url):
            raise Blocked(f"robots_disallow: {urlparse(url).path}")

    def req(self, method, url, data=None, redirects=True):
        self._check(url)
        d = time.time() - self.t
        if d < self.interval:
            time.sleep(self.interval - d)
        for attempt in range(3):
            try:
                r = self.s.request(method, url, data=data, timeout=90, allow_redirects=redirects)
                self.t = time.time(); self.nreq += 1
                if r.status_code >= 500 and attempt < 2:
                    time.sleep(30 * (attempt + 1)); continue
                return r
            except requests.RequestException:
                self.t = time.time()
                if attempt == 2:
                    raise
                time.sleep(30 * (attempt + 1))

    def start(self):
        r = self.req("GET", self.base + "SJSrbLogin.jsf")
        v = vs(r.text)
        if not v or "frm01" not in r.text:
            raise IOError("no landing form")
        r2 = self.req("POST", self.base + "SJSrbLogin.jsf", {"frm01_SUBMIT": "1", "javax.faces.ViewState": v, "frm01:_idcl": "yougo", "frm01_link_hidden_": "yougo"})
        m = re.search(r"'containerId':'([^']+)'", r2.text)
        if r2.status_code != 200 or not m or "SJReikiList" not in r2.text:
            raise IOError(f"landing auto-submit failed HTTP {r2.status_code}")
        self.A, self.v = m.group(1), vs(r2.text)
        self.as_of = (re.search(r"内容現在：\s*([^<\s]+)", r2.text) or [None, None])[1]
        r3 = self.ajax("form-tab", {"struct": "struct"})
        tops = re.findall(r'id="(j_id_jsp_\d+_\d+_(\d+)_structIndex)"[^>]*>([^<]+)</a>', r3)
        self.classes = [(k, htmlmod.unescape(lbl).replace("\u3000", " ").strip()) for k, _, lbl in tops]
        return self.classes

    def ajax(self, form, params, extra=None):
        d = {"AJAXREQUEST": self.A, f"{form}_SUBMIT": "1", "appl-id": "SJ0010", "javax.faces.ViewState": self.v}
        d.update(extra or {}); d.update(params)
        r = self.req("POST", self.base + "SJReikiList.jsf", d)
        if r.status_code != 200 or "SJSrbLogin" in r.url:
            raise SessionLost(f"ajax {form} HTTP {r.status_code}")
        self.v = vs(r.text) or self.v
        return r.text

    @staticmethod
    def rows(h):
        out = []
        for m in re.finditer(r'id="dl02_(\d+)_reikiNameSearchResults" class="viewerOpener">(.*?)</a></td><td>(.*?)</td><td>(.*?)</td><td>(.*?)</td>', h, flags=re.S):
            cl = lambda x: htmlmod.unescape(re.sub(r"<[^>]+>", "", x)).replace("\xa0", " ").strip()
            out.append({"idx": m.group(1), "title": cl(m.group(2)), "date": cl(m.group(3)), "number": cl(m.group(4)), "mishikou": bool(cl(m.group(5)))})
        tot = re.search(r"件目/(\d+)件", h)
        return out, int(tot.group(1)) if tot else 0

    def open_class(self, key):
        return self.ajax("form-taikei", {key: key}, {"searchRangeClassTaikei": "0"})

    def page(self, p):
        return self.ajax("form-list", {"pager": "pager", "first": str(p)})

    def document(self, idx):
        r = self.req("GET", self.base + f"OpenEditor.jsf?appl-id=SJ0010&currentForEditor=SJReikiList.jsf&selectedIdxForEditor={idx}"
                                         f"&typeForEditor=viewer&openParam=&ccpopup=true&parentProtocol=https%3A")
        m = re.search(r'id="outputid"[^>]*value="(\d+)"', r.text)
        if r.status_code != 200 or not m:
            raise SessionLost(f"viewer HTTP {r.status_code}")
        oid = m.group(1)
        head = r.text
        U = f"https://{self.host}/HAS-Shohin/action/get-honmon-info"
        pages, page, npages = [], 1, 1
        while page <= npages and page <= 300:
            base = {"outputid": oid, "executeId": "1", "async": "true", "perPage": "100", "id": "honmon", "matchstyle": "",
                    "quoteFunction": "quoteFunction", "currentPage": str(page), "pagingType": "1", "wait-time": "0"}
            chunks, first = [], True
            for _ in range(80):
                d = dict(base)
                if first:
                    d["reset"] = "true"
                rr = self.req("POST", U, d, redirects=False); first = False
                if rr.status_code != 200:
                    raise SessionLost(f"honmon HTTP {rr.status_code}")
                chunks.append(rr.text)
                if '<span id="eod"' in rr.text:
                    break
            h = "".join(chunks)
            m2 = re.search(r'id="page-count"[^>]*value="(\d+)"', h)
            npages = int(m2.group(1)) if m2 else npages
            pages.append(h); page += 1
        return head, "".join(pages)


def load_state(sid):
    p = STATE / f"{sid}.json"
    return json.loads(p.read_text()) if p.exists() else {"seed_id": sid, "status": "new", "done": {}, "classes_done": []}


def save_state(sid, st):
    STATE.mkdir(parents=True, exist_ok=True)
    p = STATE / f"{sid}.json"; t = p.with_suffix(".json.tmp")
    t.write_text(json.dumps(st, ensure_ascii=False)); os.replace(t, p)


class Writer:
    def __init__(self, seed, st):
        self.seed, self.st, self.buf = seed, st, []
        self.pkey = S.place_key(seed["place_id"], None, "JP")

    def add(self, rec):
        self.buf.append(rec)
        if len(self.buf) >= 100:
            self.flush()

    def flush(self):
        if not self.buf:
            save_state(self.seed["seed_id"], self.st); return
        good = [r for r in self.buf if not S.validate_record(r)]
        bad = [r for r in self.buf if S.validate_record(r)]
        if bad:
            J.QUAR.mkdir(parents=True, exist_ok=True)
            with open(J.QUAR / f"{self.pkey}.{self.seed['seed_id']}-legalsquare.jsonl", "a", encoding="utf-8") as q:
                for r in bad:
                    q.write(json.dumps({"reasons": S.validate_record(r), "record": r}, ensure_ascii=False) + "\n")
        if good:
            self.st["batch"] = self.st.get("batch", 0) + 1
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%MZ")
            final = J.OUT / f"{self.pkey}.{self.seed['seed_id']}-legalsquare-p{self.st['batch']:04d}-{ts}.jsonl"
            tmp = final.with_name("." + final.name + ".tmp.jsonl")
            with tmp.open("w", encoding="utf-8") as fh:
                for r in good:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
                fh.flush(); os.fsync(fh.fileno())
            v = S.validate_file(tmp, expect_place_key=self.pkey)
            if not v["ok"]:
                raise RuntimeError(f"validate_file failed: {v['errors'][:3]} {v['file_errors']}")
            os.rename(tmp, final)
        for r in good + bad:
            self.st["done"][r["doc_id"]] = 1
        self.st["n_docs"] = self.st.get("n_docs", 0) + len(good); self.st["n_bad"] = self.st.get("n_bad", 0) + len(bad)
        self.buf = []
        save_state(self.seed["seed_id"], self.st)


def make_record(seed, ls, row, cls_label, head, body):
    title = row["title"]
    text = J.html_to_text(body)
    raw = body
    did = "LS-" + ls.host.split(".")[0] + "-" + hashlib.sha1(f"{title}|{row['number']}|{row['date']}".encode()).hexdigest()[:16]
    rec = {"place_id": seed["place_id"], "country_code": "JP", "doc_id": did, "source_platform": PLATFORM,
           "source_url": f"https://{ls.host}/HAS-Shohin/jsp/SVDocumentView", "doc_type": J.doc_type_for(row["number"], title),
           "language": "ja", "html_title": title, "title_native": title, "number": row["number"] or None,
           "adopted_date": J.jdate(row["date"]), "published_date": None, "effective_date": None,
           "in_force": not row["mishikou"] and True, "consolidated": True, "content_format": "html", "html": body, "text": text,
           "retrieved_at": J.now_utc(), "place_name": seed["name"], "qid": seed.get("qid"), "iso_3166_2": f"JP-{seed['pref_code']}",
           "admin_level": seed.get("admin_level") or "municipality", "platform": PLATFORM, "platform_place_id": ls.host,
           "jis_code": seed.get("jis_code"), "vendor": "legal_square", "prefecture": seed["pref"], "seed_url": seed["url"],
           "collection_as_of": ls.as_of, "taikei_class": cls_label, "not_yet_in_force": row["mishikou"] or None,
           "access_path": "anonymous visitor session: SJSrbLogin auto-submit -> 体系 -> list -> viewer (OpenEditor) -> get-honmon-info",
           "content_sha256": hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest(), "raw_bytes": len(raw.encode("utf-8", "replace"))}
    if not text or len(text) < 20:
        return None
    return {k: v for k, v in rec.items() if v is not None or k == "place_id"}


def _tn(x):
    """Normalise a title for viewer/list comparison: NFKC (full/half width), drop whitespace, katakana->hiragana,
    unify small kana and long-vowel/dash variants."""
    x = unicodedata.normalize("NFKC", htmlmod.unescape(x or ""))
    x = re.sub(r"\s+", "", x)
    x = "".join(chr(ord(c) - 0x60) if "\u30a1" <= c <= "\u30f6" else c for c in x)
    x = x.translate(str.maketrans("ぁぃぅぇぉっゃゅょゎー－‐−―", "あいうえおつやゆよわ-----"))
    return x


def _strip_bracket_suffix(x):
    return re.sub(r"[(（\[［〔【][^()（）\[\]［］〔〕【】]*[)）\]］〕】]$", "", x)


def viewer_matches(head, row):
    """True when the opened viewer document is the list row we asked for. The viewer truncates long titles with '…'
    (e.g. 君津市 jp0605, 2026-10-11), so a truncated viewer title must be a prefix of the list title; the viewer's
    公布 line (date + number) is checked too when present."""
    vt = re.search(r"<title>(.*?)</title>", head, flags=re.S)
    vt = htmlmod.unescape(vt.group(1)).strip() if vt else ""
    if not vt:
        return True, vt
    a, b = _tn(vt), _tn(row["title"])
    trunc = re.search(r"(…|\.\.\.|・・・)$", a)
    if trunc:
        a = a[:trunc.start()]
        title_ok = len(a) >= 8 and b.startswith(a)
    else:
        title_ok = a == b or _strip_bracket_suffix(a) == _strip_bracket_suffix(b)
    pl = re.search(r'<p class="mt04">([^<]*)</p>', head)
    if pl and (row.get("date") or row.get("number")):
        line = _tn(pl.group(1))
        meta_ok = all(_tn(x) in line for x in (row.get("date"), row.get("number")) if x)
        if not meta_ok:
            return False, vt
    return title_ok, vt


def crawl_seed(seed, max_docs=None):
    sid = seed["seed_id"]; st = load_state(sid)
    if st.get("status") in ("done", "blocked"):
        return sid, st.get("status"), st.get("n_docs", 0)
    host = urlparse(seed["url"]).hostname
    w = Writer(seed, st); n_new = 0; restarts = 0
    st["status"] = "running"; st["host"] = host; save_state(sid, st)
    ls = LS(host)
    while True:
        try:
            classes = ls.start()
            st["n_classes"] = len(classes); st["as_of"] = ls.as_of
            for ci, (key, label) in enumerate(classes):
                if ci in st["classes_done"]:
                    continue
                h = ls.open_class(key)
                rows, total = ls.rows(h)
                npg = max(1, math.ceil(total / 10))
                start_p = st.get("cls_page", {}).get(str(ci), 1)
                for p in range(1, npg + 1):
                    if p < start_p:
                        continue
                    if p > 1:
                        h = ls.page(p); rows, _ = ls.rows(h)
                    for row in rows:
                        did = "LS-" + host.split(".")[0] + "-" + hashlib.sha1(f"{row['title']}|{row['number']}|{row['date']}".encode()).hexdigest()[:16]
                        if did in st["done"]:
                            continue
                        head, body = ls.document(row["idx"])
                        ok, vt = viewer_matches(head, row)
                        if not ok:
                            raise SessionLost(f"viewer/list mismatch: {vt[:60]!r} vs {row['title'][:60]!r} ({row['number']} {row['date']})")
                        rec = make_record(seed, ls, row, label, head, body)
                        if rec:
                            w.add(rec); n_new += 1
                        else:
                            st.setdefault("empty", []).append(row["title"][:80])
                        if max_docs and n_new >= max_docs:
                            w.flush(); st["status"] = "partial"; save_state(sid, st); return sid, "partial", st.get("n_docs", 0)
                    st.setdefault("cls_page", {})[str(ci)] = p + 1
                    w.flush()
                st["classes_done"].append(ci); w.flush()
                LOG.info("%s %s class %d/%d %s done (total %d listed) docs=%s req=%d", sid, seed["name"], ci + 1, len(classes), label, total, st.get("n_docs", 0), ls.nreq)
            st["status"] = "done"; st["finished"] = J.now_utc(); w.flush()
            return sid, "done", st.get("n_docs", 0)
        except Blocked as e:
            st.update(status="blocked", reason=str(e)); w.flush(); return sid, "blocked", st.get("n_docs", 0)
        except (SessionLost, IOError, requests.RequestException) as e:
            restarts += 1; w.flush()
            LOG.warning("%s session restart %d after %s: %s", sid, restarts, type(e).__name__, str(e)[:150])
            if restarts > 8:
                st.update(status="error", reason=f"{type(e).__name__}: {e}"[:300]); save_state(sid, st); return sid, "error", st.get("n_docs", 0)
            time.sleep(60 * restarts); ls = LS(host)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--only", default="")
    ap.add_argument("--max-docs", type=int, default=0)
    ap.add_argument("--retry-errors", action="store_true")
    ap.add_argument("--first", default="", help="comma list of seed ids to schedule first")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    seeds = [s for s in json.load(open(HERE / "seeds_places.json")) if "legal-square.com" in (s.get("url") or "") and s.get("place_id")]
    if a.only:
        seeds = [s for s in seeds if s["seed_id"] in a.only.split(",")]
    if a.retry_errors:
        for s in seeds:
            st = load_state(s["seed_id"])
            if st.get("status") == "error":
                st["status"] = "retry"; save_state(s["seed_id"], st)
    pri = {"running": 0, "partial": 0, "retry": 1}            # resume interrupted seeds first, then re-tries, then new
    first = [x for x in a.first.split(",") if x]
    seeds.sort(key=lambda s: (first.index(s["seed_id"]) if s["seed_id"] in first else len(first), pri.get(load_state(s["seed_id"]).get("status"), 2)))
    LOG.info("legal-square seeds: %d (workers=%d, 1 req/s per host)", len(seeds), a.workers)
    with cf.ThreadPoolExecutor(a.workers) as ex:
        futs = {ex.submit(crawl_seed, s, a.max_docs or None): s for s in seeds}
        for f in cf.as_completed(futs):
            s = futs[f]
            try:
                LOG.info("seed %s %s -> %s", s["seed_id"], s["name"], f.result())
            except Exception:  # noqa: BLE001
                LOG.exception("seed %s failed", s["seed_id"])
                st = load_state(s["seed_id"]); st.update(status="error", reason="exception"); save_state(s["seed_id"], st)


if __name__ == "__main__":
    main()
