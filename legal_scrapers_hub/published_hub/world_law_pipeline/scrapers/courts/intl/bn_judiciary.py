"""BN: Judiciary of Brunei Darussalam (judiciary.gov.bn; robots.txt 404 => robots_unknown).
1) 'Judges and Judicial Officers' page: name (h3) + primary appointment (first h6) only; additional appointments kept as a short note.
2) 'Forms' page: every PDF/DOC(X) form, stored by sha256 under forms/bn (forms_offload handles upload/offload)."""
import json, sys, re, datetime, hashlib, os, time, shutil, html, requests, urllib.parse, unicodedata
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from bs4 import BeautifulSoup as B
ROOT = "/workspace/world_courts"; H = {"User-Agent": "Mozilla/5.0 (world_courts research; public court data)"}
POL = "robots_unknown:robots_404|judiciary.gov.bn terms (no licence stated)"
now = datetime.datetime.now(datetime.UTC).isoformat()
def slug(s): return re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()).strip("-")
def rjl(p): return [json.loads(l) for l in open(p)] if os.path.exists(p) else []
# ---- judges
JO = "https://www.judiciary.gov.bn/about-brunei-civil-courts/judicial_officers/"; OUTJ = f"{ROOT}/data/bn/bn_judges.jsonl"
r = requests.get(JO, headers=H, timeout=60); r.raise_for_status(); sha = hashlib.sha256(r.content).hexdigest()
s = B(r.text, "html.parser"); people = []; cur = None
for el in s.find_all(["h3", "h4", "h6", "p"]):
    tx = re.sub(r"\s+", " ", el.get_text(" ", strip=True))
    if not tx: continue
    st = el.find("strong") if el.name == "p" else None
    tx = tx.replace("\u200b", "").strip()
    if el.name in ("h3", "h4") or (el.name == "h6" and cur is not None and cur[1]): cur = [tx, []]; people.append(cur); continue
    stx = re.sub(r"\s+", " ", st.get_text(" ", strip=True)).replace("\u200b", "").strip() if st else ""
    if stx and tx.startswith(stx) and len(tx) > len(stx) + 3:
        nm = stx; cur = [nm, [tx[len(nm):].strip()]]; people.append(cur); continue
    if cur is None: continue
    if tx.lower().startswith("additional appointment"):
        cur[1] += ["Additional Appointment"] + [tx.split(" ", 2)[-1] if ":" not in tx else tx.split(":", 1)[1].strip()]
    elif not cur[1]: cur[1].append(tx)
people = [(n, t) for n, t in people if t and t[0]]
def court(t):
    t = t.lower()
    if "chief justice" in t: return "bn-supreme-court", "chief"
    if "court of appeal" in t: return "bn-court-of-appeal", "associate"
    if "supreme court" in t and "registrar" not in t: return "bn-high-court-of-brunei", "associate"
    if "intermediate" in t: return "bn-intermediate-courts", "judge"
    if "magistrate" in t: return "bn-magistrates-courts", "magistrate"
    if "registrar" in t: return "bn-supreme-court", "registrar"
    return "bn-supreme-court", None
have = {slug(o["name"]) for o in rjl(OUTJ)}; nj = 0
with open(OUTJ, "a") as f:
    for nm, titles in people:
        nm = nm.replace("\u200b", "").strip()
        if slug(nm) in have: continue
        cid, pt = court(titles[0]); extra = [t for t in titles[1:] if not t.lower().startswith("additional appointment")]
        f.write(json.dumps({"judge_id": f"bn-{slug(nm)}", "court_id": cid, "name": nm, "title": titles[0], "position_type": pt,
            "term_start": None, "term_end": None, "status": "sitting", "roster_url": JO, "source_url": JO, "site_policy": POL, "retrieved_at": now,
            "needs_review": False, "extraction": "judiciary.gov.bn Judges and Judicial Officers page (names/official titles only)",
            "record_note": ("Additional appointments: " + "; ".join(extra)) if extra else None,
            "license": "official public information; no licence stated", "source_sha256": sha}, ensure_ascii=False) + "\n"); nj += 1; have.add(slug(nm))
print("judges parsed", len(people), "added", nj)
# ---- forms
IDX = "https://www.judiciary.gov.bn/information/forms/"; OUT = f"{ROOT}/data/bn/bn_forms.jsonl"; FD = f"{ROOT}/forms/bn"; os.makedirs(FD, exist_ok=True)
old = rjl(OUT); osha = {o["pdf_sha256"] for o in old}; osrc = {o["source_url"] for o in old}; n = nb = 0; fail = []; seen = set()
s = B(requests.get(IDX, headers=H, timeout=60).text, "html.parser")
for a in s.find_all("a", href=True):
    src = urllib.parse.urljoin(IDX, a["href"])
    if not re.search(r"\.(pdf|docx?)$", src, re.I) or src in seen or src in osrc: continue
    seen.add(src)
    if shutil.disk_usage("/workspace").free < 20 * 2**30: print("disk < 20 GB, pausing"); break
    row_el = a.find_parent("tr"); ctx = re.sub(r"\s+", " ", row_el.get_text(" ", strip=True)) if row_el else ""
    title = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
    if len(title) < 6 or title.lower() in ("form", "here", "download", "checklist"): title = (ctx[:200] or title or os.path.basename(src))
    sec = a.find_previous(["h1", "h2", "h3", "h4"]); sec = sec.get_text(" ", strip=True) if sec else None
    time.sleep(2)
    try: r = requests.get(src, headers=H, timeout=120)
    except requests.RequestException as e: fail.append((src, str(e)[:50])); continue
    if r.status_code != 200 or len(r.content) < 500: fail.append((src, r.status_code)); continue
    ext = src.rsplit(".", 1)[-1].lower(); sha = hashlib.sha256(r.content).hexdigest()
    if sha in osha: continue
    open(f"{FD}/{sha}.{ext}", "wb").write(r.content)
    m = re.search(r"\b(?:FORM|Form)\s+([0-9]+[A-Z]?|[A-Z])\b", title + " " + ctx); lang = "ms" if re.search(r"\b(borang|permohonan|penyata)\b", title, re.I) else "en"
    row = {"form_id": f"bn-{sha[:16]}", "court_id": None, "jurisdiction": "BN", "form_number": m.group(1) if m else None,
           "title": title, "category": slug(sec) if sec else "judiciary-forms", "language": lang, "revision_date": None, "file_format": ext,
           "pdf_path": f"forms/bn/{sha}.{ext}", "pdf_sha256": sha, "file_bytes": len(r.content), "source_url": src, "index_url": IDX,
           "license": "Judiciary of Brunei Darussalam published forms; no licence stated", "site_policy": POL, "retrieved_at": now,
           "record_note": f"index row text: {ctx[:300]}" if ctx else None}
    with open(OUT, "a") as f: f.write(json.dumps(row, ensure_ascii=False) + "\n")
    osha.add(sha); n += 1; nb += len(r.content)
print("forms added", n, "bytes", nb, "fail", fail)
