"""Shared helpers for the 2026-10-17 global scanned-PDF sweep (World Law OCR). Read-only on every lane dir."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import json, re, sys
from pathlib import Path
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
from schema import place_key as _pk  # noqa: E402

WL = Path(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law")); PDF = WL / "staging/pdf"
WORK = PDF / "_state/sweep_work"; SWEEP = PDF / "_state/sweep_20261017.jsonl"
SHORT, SHORT_INCOMPLETE = 200, 1000
PDF_RE = re.compile(r"\.pdf($|[?#&;/]|%3f)", re.I)
PDFISH_RE = re.compile(r"(DownloadDocument\.aspx|[?&](file|f|doc)=[^&]*\.pdf|/pdf/|[?&]format=pdf|application/pdf|getpdf|pdfviewer|\bpdf\b)", re.I)
GDRIVE_RE = re.compile(r"(drive|docs)\.google\.com|accounts\.google\.com", re.I)
ROBOTS_POL = {"robots_unreachable", "robots_disallowed"}; CF_POL = "metadata_only_cloudflare_challenge"

def pols(p):
    if not p: return set()
    if isinstance(p, (list, tuple)): return set(p)
    return set(x.strip() for x in str(p).split(";") if x.strip())

def pdf_url(r):
    """Return the most direct PDF URL of a row, or None."""
    em = r.get("extra_metadata")
    if isinstance(em, str):
        try: em = json.loads(em)
        except ValueError: em = None
    em = em if isinstance(em, dict) else {}
    cands = [r.get("source_url"), r.get("original_url"), em.get("pdf_url"), r.get("archive_url")]
    for u in cands:
        if isinstance(u, str) and u.startswith("http") and PDF_RE.search(u): return u
    cf = (r.get("content_format") or "").lower()
    for u in cands:
        if isinstance(u, str) and u.startswith("http") and (PDFISH_RE.search(u) and ("pdf" in cf or "pdf" in u.lower())): return u
    return None

def classify(r, text_len):
    """-> None (not a candidate) or reason string."""
    if r.get("pdf_ref"): return None
    cc = r.get("content_complete")
    if text_len is None:                # unknown text length (Hub chunk too big): only trust content_complete=false
        return "incomplete_text_unknown" if cc is False else None
    if text_len < SHORT: return "empty" if text_len == 0 else "near_empty"
    if cc is False and text_len < SHORT_INCOMPLETE: return "incomplete_short"
    return None

def load_exclusions():
    led = set(); led_pairs = set()
    for ln in open(WL / "state/pdf_ledger.jsonl", encoding="utf-8"):
        try: r = json.loads(ln)
        except ValueError: continue
        led.add(r["doc_id"]); led_pairs.add((r.get("place_key"), r["doc_id"]))
    fet = set()
    for ln in open(PDF / "_logs/fetched.jsonl", encoding="utf-8"):
        try: fet.add(json.loads(ln)["doc_id"])
        except (ValueError, KeyError): pass
    done = set()
    for ln in open(PDF / "_state/done.txt", encoding="utf-8"):
        p = ln.rstrip("\n").split("|", 3)
        if len(p) >= 3: done.add(p[2])
    capped = set()
    try:
        att = json.load(open(PDF / "_state/attempts.json"))
        capped = {k.split("|", 3)[2] for k, v in att.items() if v >= 5}
    except Exception: pass
    return led, fet, done, capped

def place_key(pid): return _pk(pid)
