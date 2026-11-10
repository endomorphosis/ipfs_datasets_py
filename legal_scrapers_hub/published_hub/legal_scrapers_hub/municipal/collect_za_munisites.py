"""ZA municipal supplement: collector for official municipal websites.

For each municipality host (seeds JSON: [{code, name, province, hosts:[...], seeds:[urls]}]):
  robots.txt first (fail closed on TLS reset / cert failure / 5xx); BFS over same-host HTML pages whose URL or link text
  looks like a by-law / legislation / documents page (depth <= 2, <= ZA_MAX_PAGES pages, by-law pages first); document
  links (.pdf/.docx) are kept when the link text / file name says by-law, or when they sit on a by-law page and are not
  drafts / policies / tenders / IDPs / budgets etc. Documents are fetched one at a time per host
  (delay = max(ZA_MIN_DELAY, robots Crawl-delay)), text-extracted (pdftotext; docx XML), and appended to
  <STATE>/munisites/<code>.docs.jsonl. Image-only PDFs (no text layer) are kept under <STATE>/image_only_pdfs/ for a
  later OCR pass and flagged image_only=true. Resumable: URLs already in docs.jsonl are skipped; HTML pages are cached.
Env: ZA_STATE, ZA_SEEDS, ZA_THREADS (hosts in parallel, default 8), ZA_MAX_PAGES (30), ZA_MAX_DOCS (500), ZA_ONLY (codes).
Stop cleanly: touch <STATE>/STOP_munisites.
"""
import os, sys, re, json, time, hashlib, zipfile, io, subprocess, threading, urllib.parse, html
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import za_common as zc
from bs4 import BeautifulSoup
import warnings
warnings.filterwarnings("ignore")

STATE = os.environ.get("ZA_STATE", "za_build_state")
SEEDS = os.environ.get("ZA_SEEDS", os.path.join(STATE, "seeds", "za_sites.json"))
OUT = os.path.join(STATE, "munisites"); os.makedirs(OUT, exist_ok=True)
IMG = os.path.join(STATE, "image_only_pdfs"); os.makedirs(IMG, exist_ok=True)
STOP = os.path.join(STATE, "STOP_munisites")
THREADS = int(os.environ.get("ZA_THREADS", "8"))
MAX_PAGES = int(os.environ.get("ZA_MAX_PAGES", "30"))
MAX_DOCS = int(os.environ.get("ZA_MAX_DOCS", "500"))
ONLY = set(x for x in os.environ.get("ZA_ONLY", "").split(",") if x)
LOG = open(os.path.join(STATE, "logs", "munisites.log"), "a")
_ll = threading.Lock()


def log(*a):
    with _ll:
        LOG.write(zc.now_utc() + " " + " ".join(str(x) for x in a) + "\n"); LOG.flush()


BYLAW = re.compile(r"by[\s_\-\.]*laws?|bylaw|byelaw|verordening|umthetho|by-wet", re.I)
NAV = re.compile(r"by[\s_\-\.]*laws?|bylaw|legislation|regulations|policies|documents?|publications|gazette|"
                 r"resources|downloads?|library|notices", re.I)
NAV_BAD = re.compile(r"tender|vacanc|career|job|news|event|gallery|photo|video|contact|login|wp-admin|feed|calendar|"
                     r"facebook|twitter|instagram|youtube|linkedin|whatsapp|mailto:|tel:|\.(jpg|png|gif|zip|xlsx?|pptx?)$", re.I)
DOC_EXT = re.compile(r"\.(pdf|docx)(\?|#|$)", re.I)
DOC_HINT = re.compile(r"/download|wpdm|getfile|file\.php|attachment|\?file=|/storage/|task=file\.download|wpfd_file_id|"
                      r"download\.php|[?&]download=|wpdmdl=|/documents/download|docman|/dl/|fileadmin", re.I)
STRONG_DOC = re.compile(r"task=file\.download|wpfd_file_id|wpdmdl=|[?&]download=|download\.php|docman/.*/file|getfile", re.I)
HARD_EXCL = re.compile(r"draft|proposed|for comment|comments|participation|invitation|fines?[\s_\-]*list|list[\s_\-]*of[\s_\-]*fines|"
                       r"schedule[\s_\-]*of[\s_\-]*fines|flyer|presentation|summary|notice[\s_\-]*of[\s_\-]*intent|explanatory|\bfaqs?\b|"
                       r"application[\s_\-]*form|checklist", re.I)
EXCL = re.compile(r"draft|proposed|for comment|comments|public participation|participation|invitation|tender|\bbid\b|\bidp\b|"
                  r"budget|sdbip|annual report|vacanc|minutes|agenda|presentation|newsletter|application form|\bform\b|"
                  r"advert|notice of intention|\brfq\b|quotation|annual financial|audit|performance|organogram|"
                  r"strategy|framework|plan\b|report|register|indigent application|checklist|guideline|brochure|pamphlet|"
                  r"\bpolicy\b(?!.*by[\s_\-]*law)", re.I)


def extract(body, ctype, url):
    """-> (text, pages, method)"""
    if body[:5] == b"%PDF-" or "pdf" in ctype.lower():
        try:
            p = subprocess.run(["pdftotext", "-enc", "UTF-8", "-", "-"], input=body, capture_output=True, timeout=180)
            t = p.stdout.decode("utf-8", "replace")
        except Exception as e:
            return "", 0, f"pdftotext-error:{type(e).__name__}"
        return t, t.count("\f") or 1, "pdftotext"
    if body[:2] == b"PK":
        try:
            z = zipfile.ZipFile(io.BytesIO(body)); x = z.read("word/document.xml").decode("utf-8", "replace")
            x = re.sub(r"</w:p>", "\n", x); x = re.sub(r"<w:tab/>", "\t", x); x = re.sub(r"<[^>]+>", "", x)
            return html.unescape(x), 0, "docx-xml"
        except Exception:
            return "", 0, "docx-error"
    return "", 0, "unsupported:" + (ctype or "?")[:40]


class Host:
    def __init__(self, site, P):
        self.site = site; self.P = P; self.code = site["code"]
        self.fn = os.path.join(OUT, f"{self.code}.docs.jsonl")
        self.pfn = os.path.join(OUT, f"{self.code}.pages.jsonl")
        self.done = set()
        if os.path.exists(self.fn):
            for l in open(self.fn):
                try: self.done.add(json.loads(l)["url"])
                except Exception: pass

    def write(self, fn, rec):
        with open(fn, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n"); f.flush(); os.fsync(f.fileno())

    def run(self):
        hosts = self.site.get("hosts") or []
        status = dict(code=self.code, hosts=hosts, reachable=[], blocked={})
        start = list(self.site.get("seeds") or [])
        for h in hosts:
            base = "https://" + h
            rr = self.P._robots(base)
            if rr is None:
                status["blocked"][h] = self.P.robots_raw.get(base, "")[:200]; continue
            r = self.P.get(base + "/")
            if r is None or r["status"] != 200:
                status["blocked"][h] = f"home {None if r is None else r['status']} {'' if r is None else r.get('error','')[:150]}"; continue
            status["reachable"].append(h); start.append(r["url"])
        allowed_hosts = set(status["reachable"]) | {urllib.parse.urlsplit(u).netloc for u in self.site.get("seeds") or []}
        allowed_hosts |= {h[4:] if h.startswith("www.") else "www." + h for h in list(allowed_hosts)}
        if not status["reachable"] and not self.site.get("seeds"):
            log(self.code, "UNREACHABLE", json.dumps(status["blocked"])[:400]); return status
        # BFS
        queue = [(0, 3 if u in (self.site.get("seeds") or []) else 1, u, "", "") for u in dict.fromkeys(start)]
        seen = set(u for _, _, u, _, _ in queue); pages = 0; docs = {}; found_bylaw_page = False
        while queue and pages < MAX_PAGES:
            if os.path.exists(STOP): return status
            queue.sort(key=lambda x: (-x[1], x[0]))
            depth, score, url, anchor, _ = queue.pop(0)
            r = self.P.get(url)
            if r is None or r["status"] != 200 or not re.search(r"html|xml", r["ctype"], re.I):
                continue
            pages += 1
            s = BeautifulSoup(r["body"], "html.parser")
            title = (s.title.get_text(" ", strip=True) if s.title else "")[:200]
            h1 = " ".join(x.get_text(" ", strip=True) for x in s.find_all(["h1", "h2"])[:3])[:300]
            page_is_bylaw = bool(BYLAW.search(url + " " + title + " " + h1 + " " + anchor))
            page_is_draft = bool(re.search(r"draft|proposed|for comment|public participation|\bfaqs?\b", title + " " + h1, re.I))
            found_bylaw_page = found_bylaw_page or page_is_bylaw
            if score < 3 and found_bylaw_page and depth >= 1 and not page_is_bylaw:
                pass
            nd = 0
            for a in s.find_all("a", href=True):
                href = a["href"].strip()
                if href.startswith(("mailto:", "tel:", "javascript:", "#")): continue
                u = urllib.parse.urljoin(r["url"], href).split("#")[0]
                pu = urllib.parse.urlsplit(u)
                if pu.scheme not in ("http", "https"): continue
                t = a.get_text(" ", strip=True)[:300] or (a.get("title") or "")[:300]
                fname = urllib.parse.unquote(pu.path.rsplit("/", 1)[-1] + " " + pu.query)
                is_doc = bool(DOC_EXT.search(pu.path) or DOC_EXT.search(pu.query) or STRONG_DOC.search(u)) or \
                    bool(DOC_HINT.search(u) and BYLAW.search(t + " " + fname) and not NAV.search(pu.path.rsplit("/", 1)[-1] or "x"))
                if is_doc:
                    if page_is_draft: continue
                    label = t + " " + fname
                    keep = bool(BYLAW.search(label)) and not HARD_EXCL.search(label)
                    if not keep and page_is_bylaw and not EXCL.search(label) and not HARD_EXCL.search(label): keep = True
                    if keep and u not in docs:
                        docs[u] = dict(anchor=t, page_url=r["url"], page_title=title, page_is_bylaw=page_is_bylaw); nd += 1
                    continue
                if pu.netloc not in allowed_hosts or u in seen or depth >= 2 or NAV_BAD.search(u): continue
                sc = 3 if BYLAW.search(u + " " + t) else (1 if NAV.search(u + " " + t) else 0)
                if sc == 0 or (sc == 1 and found_bylaw_page and depth >= 1): continue
                seen.add(u); queue.append((depth + 1, sc, u, t, r["url"]))
            self.write(self.pfn, dict(url=r["url"], title=title, depth=depth, bylaw_page=page_is_bylaw, docs_found=nd, t=zc.now_utc()))
        log(self.code, "pages", pages, "doc candidates", len(docs))
        status["pages"] = pages; status["doc_candidates"] = len(docs)
        n = 0
        for u, meta in list(docs.items())[:MAX_DOCS]:
            if os.path.exists(STOP): return status
            if u in self.done: continue
            if not zc.wait_resources(log=log, stop_file=STOP): return status
            r = self.P.get(u, doc=True, max_bytes=40_000_000)
            if r is None:
                self.write(self.fn, dict(url=u, code=self.code, status="robots-disallowed", **meta)); continue
            rec = dict(url=u, final_url=r["url"], code=self.code, status=r["status"], ctype=r["ctype"], retrieved_at=r.get("retrieved_at"),
                       n_bytes=len(r["body"]), truncated=r.get("truncated", False), **meta)
            if r["status"] == 200 and r["body"] and not (r["body"][:5] == b"%PDF-" or r["body"][:2] == b"PK"):
                rec["skip"] = "not a pdf/docx response"
            elif r["status"] == 200 and r["body"]:
                rec["sha256_bytes"] = hashlib.sha256(r["body"]).hexdigest()
                text, pages_, method = extract(r["body"], r["ctype"], r["url"])
                rec.update(text=text, pages=pages_, method=method, chars=len(text.strip()))
                if r["body"][:5] == b"%PDF-" and len(re.sub(r"\s+", "", text)) < max(200, 40 * pages_):
                    rec["image_only"] = True
                    p = os.path.join(IMG, self.code); os.makedirs(p, exist_ok=True)
                    fp = os.path.join(p, rec["sha256_bytes"][:20] + ".pdf")
                    if os.environ.get("ZA_KEEP_IMAGE_PDFS", "0") == "1" and not os.path.exists(fp) and not r.get("truncated"):
                        open(fp, "wb").write(r["body"])
                    rec["image_only_path"] = fp if os.path.exists(fp) else None   # URL + sha256 recorded; refetch for OCR
            self.write(self.fn, rec); self.done.add(u); n += 1
        log(self.code, "docs fetched", n)
        return status


def main():
    sites = json.load(open(SEEDS))
    if ONLY: sites = [s for s in sites if s["code"] in ONLY]
    P = zc.Polite()
    stfn = os.path.join(OUT, "_host_status.jsonl")
    def one(site):
        try:
            st = Host(site, P).run()
        except Exception as e:
            st = dict(code=site["code"], error=f"{type(e).__name__}: {e}"[:300]); log(site["code"], "ERROR", st["error"])
        st["t"] = zc.now_utc()
        with _ll:
            with open(stfn, "a") as f: f.write(json.dumps(st) + "\n")
        log(site["code"], "HOST DONE")
    log("START", len(sites), "sites, threads", THREADS)
    with ThreadPoolExecutor(THREADS) as ex:
        list(ex.map(one, sites))
    log("ALL DONE" if not os.path.exists(STOP) else "STOPPED")


if __name__ == "__main__":
    main()
