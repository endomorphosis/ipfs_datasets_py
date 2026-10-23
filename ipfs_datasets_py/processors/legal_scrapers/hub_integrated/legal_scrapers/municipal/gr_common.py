#!/usr/bin/env python3
"""Shared helpers for the Greek municipal collectors (copy of sk_common.py with its own cache): polite session (robots.txt via urllib.robotparser, 1 req/s per host),
document fetch with a disk cache, text extraction (pdftotext, no OCR; docx via zipfile; html), JSONL writer."""
import hashlib, html as H, io, json, os, re, subprocess, tempfile, time, unicodedata, zipfile, datetime
from urllib import robotparser
from urllib.parse import urlparse
import requests

UA = "world-laws-municipal-collector/0.1 (research; polite)"
CACHE = os.environ.get("GR_CACHE", os.path.join(os.environ.get("GR_BUILD", "gr_build"), "cache"))
os.makedirs(CACHE, exist_ok=True)

class Polite:
    def __init__(self, delay=1.0):
        self.s = requests.Session(); self.s.headers["User-Agent"] = UA
        self.delay, self.last, self.rp = delay, {}, {}
    def allowed(self, url):
        host = urlparse(url).scheme + "://" + urlparse(url).netloc
        if host not in self.rp:
            rp = robotparser.RobotFileParser()
            try:
                r = self.s.get(host + "/robots.txt", timeout=20)
                rp.parse(r.text.splitlines() if r.status_code == 200 else [])
            except Exception: rp.parse([])
            self.rp[host] = rp
        return self.rp[host].can_fetch(UA, url)
    def get(self, url, timeout=60, cache=True, **kw):
        fn = os.path.join(CACHE, hashlib.sha1(url.encode()).hexdigest())
        if cache and os.path.exists(fn):
            return open(fn, "rb").read(), json.load(open(fn + ".json"))
        if not self.allowed(url): raise PermissionError("robots.txt disallows " + url)
        host = urlparse(url).netloc
        w = self.delay - (time.time() - self.last.get(host, 0))
        if w > 0: time.sleep(w)
        for attempt in range(3):
            try:
                r = self.s.get(url, timeout=timeout, **kw); break
            except requests.RequestException:
                if attempt == 2: raise
                time.sleep(3)
        self.last[host] = time.time()
        r.raise_for_status()
        if r.is_redirect: raise RuntimeError("redirect not followed: " + r.headers.get("location", ""))   # old documents -> static.old.diavgeia.gov.gr/doc/ (robots-disallowed path, host unreachable)
        meta = {"url": url, "final": r.url, "ctype": r.headers.get("content-type", ""), "retrieved_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        if cache:
            open(fn, "wb").write(r.content); json.dump(meta, open(fn + ".json", "w"))
        return r.content, meta

def pdf_text(data):
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(data); f.flush()
        try: t = subprocess.run(["pdftotext", "-enc", "UTF-8", f.name, "-"], capture_output=True, timeout=180).stdout.decode("utf-8", "replace")
        except subprocess.TimeoutExpired: t = ""
    return t

def docx_text(data):
    try: z = zipfile.ZipFile(io.BytesIO(data)); x = z.read("word/document.xml").decode("utf-8", "replace")
    except Exception: return ""
    x = re.sub(r"</w:p>", "\n", x); x = re.sub(r"<w:tab/>", "\t", x); x = re.sub(r"<[^>]+>", "", x)
    return H.unescape(x)

def decode_html(data, ctype=""):
    """Charset from the HTTP header or <meta charset>, else strict UTF-8, else windows-1250 (old Slovak pages)."""
    m = re.search(r"charset=([\w-]+)", ctype or "", re.I) or re.search(rb'(?i)<meta[^>]+charset=["\']?([\w-]+)', data[:4000])
    cs = (m.group(1).decode() if isinstance(m.group(1), bytes) else m.group(1)).lower() if m else None
    for enc in ([cs] if cs else []) + ["utf-8", "cp1250"]:
        try: return data.decode(enc)
        except (LookupError, UnicodeDecodeError): continue
    return data.decode("cp1250", "replace")

def html_text(s):
    s = re.sub(r"(?is)<(script|style|nav|header|footer)[^>]*>.*?</\1>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>|</(p|div|h\d|li|tr)>", "\n", s); s = re.sub(r"<[^>]+>", " ", s)
    return H.unescape(s)

def office_text(data, suffix):
    """RTF / legacy .doc via LibreOffice headless (txt export, UTF-8). No OCR."""
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "in" + suffix); open(src, "wb").write(data)
        prof = "file://" + os.path.join(td, "lo_profile")
        try:
            subprocess.run(["soffice", f"-env:UserInstallation={prof}", "--headless", "--convert-to", "txt:Text (encoded):UTF8", "--outdir", td, src],
                           capture_output=True, timeout=240)
        except subprocess.TimeoutExpired: return ""
        out = os.path.join(td, "in.txt")
        return open(out, encoding="utf-8", errors="replace").read() if os.path.exists(out) else ""

def doc_text(data, meta):
    ct, url = meta.get("ctype", "").lower(), meta.get("final", meta.get("url", "")).lower()
    if data[:4] == b"%PDF": return pdf_text(data), "pdftotext"
    if data[:2] == b"PK": return docx_text(data), "docx-xml"
    if data[:5] == b"{\\rtf": return office_text(data, ".rtf"), "libreoffice-rtf"
    if data[:4] == b"\xd0\xcf\x11\xe0": return office_text(data, ".doc"), "libreoffice-doc"
    if "html" in ct or re.match(rb"(?is)\s*<(!doctype|html)", data[:200]): return html_text(decode_html(data, ct)), "html"
    if url.endswith(".doc") or data[:4] == b"\xd0\xcf\x11\xe0":
        return "", "doc-binary-unsupported"
    return data.decode("utf-8", "replace"), "text"

def clean(t):
    t = unicodedata.normalize("NFKC", t or "")
    t = t.replace("\u00ad", "").replace("\ufeff", "").replace("\x0c", "\n")
    t = re.sub(r"[\x00-\x08\x0b\x0e-\x1f\x7f\ufffd]", " ", t)
    t = re.sub(r"[ \t]+\n", "\n", t); t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()

def sha(t): return hashlib.sha256(t.encode()).hexdigest()

def write_jsonl(path, recs):
    with open(path, "w") as f:
        for r in recs: f.write(json.dumps(r, ensure_ascii=False) + "\n")
