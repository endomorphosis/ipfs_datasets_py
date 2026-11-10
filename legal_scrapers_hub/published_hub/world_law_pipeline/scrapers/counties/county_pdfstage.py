"""2026-10-21 county lane: no more staging/counties/_raw.
 - text_of(data): pdftotext via a temp file that is deleted immediately (text-layer raws are not kept)
 - ScanStager: scanned PDFs go straight to staging/pdf/<CC>/<place_key>/<doc_id with :/\\ -> _>.pdf (.pdf.tmp -> rename)
   and to staging/pdf/_manifest/batch_NNNN.jsonl (+ empty .ready last), numbering after the highest existing batch."""
import os, re, json, hashlib, tempfile, subprocess
from pathlib import Path
import sys
sys.path.insert(0, "/workspace/world_law/pipeline")
from schema import place_key
PDF = Path("/workspace/world_law/staging/pdf"); MAN = PDF / "_manifest"
def text_of(data: bytes, layout=True) -> str:
    fd, tp = tempfile.mkstemp(suffix=".pdf", dir="/tmp")
    try:
        with os.fdopen(fd, "wb") as f: f.write(data)
        return subprocess.run(["pdftotext"] + (["-layout"] if layout else []) + [tp, "-"], capture_output=True, text=True).stdout
    finally: os.unlink(tp)
def quote_url(u: str) -> str:
    """2026-10-21 followup: percent-encode spaces/non-ASCII; keeps existing %XX escapes and URL delimiters."""
    from urllib.parse import quote
    return quote(u, safe=":/?&=%#;+,@!$~*()'[]")
def sniff(data: bytes, url: str = "", ctype: str = "") -> str:
    """Kind of fetched bytes: pdf | vcf | ole (xls/doc) | zip (xlsx/docx) | html | other. Only 'pdf' may be scanned_pdf."""
    head = data[:2048].lstrip(); u = url.lower().split("?")[0]; ct = (ctype or "").lower()
    if data.find(b"%PDF-", 0, 1024) >= 0: return "pdf"
    if head[:11].upper() == b"BEGIN:VCARD" or u.endswith(".vcf") or "vcard" in ct: return "vcf"
    if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1": return "ole"
    if data[:4] == b"PK\x03\x04": return "zip"
    if head[:1] == b"<" or "html" in ct: return "html"
    return "other"
def _next_batch():
    n = 272
    for p in MAN.iterdir():
        m = re.match(r"batch_(\d{4})\.", p.name)
        if m: n = max(n, int(m.group(1)))
    return n + 1
import sys as _sys; _sys.path.insert(0, "/workspace/world_law/pipeline/tools")
import batch_alloc as _BA
class ScanStager:
    def __init__(self, chunk=200): self.buf = []; self.chunk = chunk; self.batches = []
    def add(self, data: bytes, rec: dict, fetched_at: str):
        """data: PDF bytes; rec: staged row (doc_id, place_id, country_code, gnis, source_url, source_policy). Returns pdf path or None."""
        if sniff(data, rec.get("source_url", "")) != "pdf": return None  # never stage vcf/xls/html as scanned_pdf
        i = data.find(b"%PDF-")
        if i < 0 or i > 1024: return None
        data = data[i:]
        cc = rec["country_code"]; pk = place_key(rec["place_id"], rec.get("gnis"), cc)
        did = rec["doc_id"]
        if "?" in rec["source_url"] and "~" not in did: did += "~" + hashlib.sha1(rec["source_url"].encode()).hexdigest()[:8]  # doc_id drops the query; ?did= downloads collide
        od = PDF / cc / pk; od.mkdir(parents=True, exist_ok=True); out = od / (re.sub(r"[:/\\]", "_", did) + ".pdf"); tmp = out.with_name(out.name + ".tmp")
        with open(tmp, "wb") as f: f.write(data); f.flush(); os.fsync(f.fileno())
        os.rename(tmp, out)
        pol = rec.get("source_policy"); pol = pol if isinstance(pol, str) else ";".join(pol or [])
        self.buf.append(dict(doc_id=did, place_id=rec["place_id"], place_key=pk, country_code=cc, source_url=rec["source_url"],
                             sha256=hashlib.sha256(data).hexdigest(), bytes=len(data), fetched_at=fetched_at, source_policy=pol, lane="counties"))
        if len(self.buf) >= self.chunk: self.flush()
        return str(out)
    def flush(self):
        if not self.buf: return None
        n = _BA.write_batch(MAN, self.buf, floor=272)  # atomic, collision-safe (tools/batch_alloc.py)
        self.buf = []; self.batches.append(n); return n
