#!/usr/bin/env python3
"""Timor-Leste: enrich existing district / Court of Appeal courthouse rows with street,
phone, and email published on www.tribunais.tl district pages (public contact blocks).
Does NOT add new court rows; rewrites matching court_id lines in place. Judges unchanged.
robots.txt allows (only /wp-admin/ disallowed). Polite 2s delay."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_COURTS = _ipfs_Path(_ipfs_os.environ.get("WORLD_COURTS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_courts")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, re, os, html, time, urllib.request, datetime, hashlib, tempfile

W = str(_COURTS)
OUT = f"{W}/data/tl/tl_courthouses.jsonl"
UA = {"User-Agent": "WorldCourtsResearchBot/1.0 (court-data research; contact via Benjamin Barber)"}
POL = "robots_allowed|tribunais.tl termos-de-uso; polite 2s; public contact info only"
NOW = datetime.datetime.now(datetime.timezone.utc).isoformat()
B = "https://www.tribunais.tl/"

PAGES = {
    "tl-district-court-dili": "tribunal-distrital-de-dili/",
    "tl-district-court-baucau": "tribunal-distrital-de-baucau/",
    "tl-district-court-suai": "tribunal-distrital-de-suai/",
    "tl-district-court-oecusse": "tribunal-distrital-de-oecusse/",
}

def get(path):
    time.sleep(2)
    b = urllib.request.urlopen(urllib.request.Request(B + path, headers=UA), timeout=60).read()
    return b

def lines_of(raw):
    t = raw.decode("utf-8", "replace")
    i = t.find("You are here")
    x = html.unescape(re.sub(r"<[^>]+>", "\n", t[i:] if i >= 0 else t))
    return [l.strip() for l in x.splitlines() if l.strip() and "iframe" not in l and "function" not in l and "rocket" not in l]

def parse_contact(ls):
    street = phone = email = None
    recurso_street = recurso_phone = None
    in_recurso = False
    for l in ls:
        if re.search(r"ENDEREÇO\s*[–-]\s*TRIBUNAL\s+DE\s+RECURSO", l, re.I):
            in_recurso = True; continue
        if in_recurso:
            if street is None and re.match(r"^Rua\b", l, re.I):
                recurso_street = l
            m = re.search(r"(?:Telefone|Phone)\s*:?\s*(.+)$", l, re.I)
            if m and recurso_phone is None and "emerg" not in l.lower():
                recurso_phone = m.group(1).strip()
            continue
        if street is None and re.match(r"^Rua\b", l, re.I):
            street = l
        m = re.search(r"(?:Telefone|Phone)\s*:?\s*(.+)$", l, re.I)
        if m and phone is None and "emerg" not in l.lower() and "TJPI" not in l:
            phone = re.sub(r"\s+", " ", m.group(1)).strip()
        m = re.search(r"Email\s*:?\s*(\S+@\S+)", l, re.I)
        if m and email is None:
            email = m.group(1).strip().rstrip(".")
    return street, phone, email, recurso_street, recurso_phone

info = {}
recurso = None
for cid, path in PAGES.items():
    raw = get(path)
    sha = hashlib.sha256(raw).hexdigest()
    street, phone, email, rs, rp = parse_contact(lines_of(raw))
    info[cid] = dict(street=street, phone=phone, email=email, source_url=B + path, source_sha256=sha)
    if rs or rp:
        recurso = dict(street=rs, phone=rp, source_url=B + path, source_sha256=sha)
    print(cid, street, phone, email)

rows = [json.loads(l) for l in open(OUT)]
changed = 0
for r in rows:
    cid = r.get("court_id")
    if cid in info:
        d = info[cid]
        addr = r.get("address") or {}
        before = json.dumps(addr, sort_keys=True), r.get("phone"), r.get("email")
        if d["street"]:
            addr["street"] = d["street"]
            # city from street/page
            if "Baucau" in (d["street"] or "") or cid.endswith("baucau"):
                addr["city"] = "Baucau"
            elif cid.endswith("dili"):
                addr["city"] = "Dili"
            elif cid.endswith("suai"):
                addr["city"] = "Suai"
            elif cid.endswith("oecusse"):
                addr["city"] = "Oecusse"
            addr["country"] = "TL"
        r["address"] = addr
        if d["phone"]:
            r["phone"] = d["phone"]
        if d.get("email"):
            r["email"] = d["email"]
        r["website"] = B
        r["source_url"] = d["source_url"]
        r["source_kind"] = "official"
        r["site_policy"] = POL
        r["retrieved_at"] = NOW
        r["source_sha256"] = d["source_sha256"]
        r["record_note"] = (r.get("record_note") or "")
        note = "contact block from official Tribunal Judicial de Primeira Instância page"
        if note not in (r.get("record_note") or ""):
            r["record_note"] = ((r.get("record_note") + "; ") if r.get("record_note") else "") + note
        after = json.dumps(r.get("address") or {}, sort_keys=True), r.get("phone"), r.get("email")
        if after != before:
            changed += 1
    elif cid == "tl-court-of-appeal" and recurso:
        addr = r.get("address") or {}
        before = json.dumps(addr, sort_keys=True), r.get("phone")
        if recurso.get("street"):
            addr["street"] = recurso["street"]; addr["city"] = "Dili"; addr["country"] = "TL"
        r["address"] = addr
        if recurso.get("phone"):
            r["phone"] = recurso["phone"]
        r["website"] = B
        r["source_url"] = recurso["source_url"]
        r["source_kind"] = "official"
        r["site_policy"] = POL
        r["retrieved_at"] = NOW
        r["source_sha256"] = recurso["source_sha256"]
        after = json.dumps(r.get("address") or {}, sort_keys=True), r.get("phone")
        if after != before:
            changed += 1

# atomic rewrite
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(OUT), suffix=".tmp")
os.close(fd)
with open(tmp, "w") as fh:
    for r in rows:
        fh.write(json.dumps(r, ensure_ascii=False) + "\n")
os.replace(tmp, OUT)
print("TL courts enriched", changed, "of", len(info), "+ recurso", bool(recurso))
