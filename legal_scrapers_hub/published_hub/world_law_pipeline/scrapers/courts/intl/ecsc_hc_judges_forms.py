"""ECSC High Court judges and masters per member state/territory (official 'High Court Judges' page, ACF sections)
and ECSC court forms (CPR 2000 appendix forms, Court of Appeal Rules 1968 criminal appeal forms, mediation PD forms)
via the public WordPress REST API at cms.eccourts.org (backs www.eccourts.org; robots allows all).
Judges -> data/<cc>/<cc>_judges.jsonl (court_id <cc>-high-court); forms -> data/lc/lc_forms.jsonl (seat), applies_to all members.
Skips any name already present in any member's judges file. Names and official titles only."""
import json, re, sys, os, html, hashlib, datetime, time, urllib.request
ROOT = "/workspace/world_courts"
API = "https://cms.eccourts.org/wp-json/wp/v2"
UA = {"User-Agent": "Mozilla/5.0 world-courts-research (public court data)"}
MEMBERS = ["AG", "DM", "GD", "KN", "LC", "VC", "AI", "MS", "VG"]
SEC = {"anguilla": "ai", "antigua": "ag", "dominica": "dm", "grenada": "gd", "montserrat": "ms", "kitts": "kn",
       "saint lucia": "lc", "vincent": "vc", "virgin islands": "vg"}
now = datetime.datetime.now(datetime.UTC).isoformat()
dry = "--dry" in sys.argv
def get(url):
    time.sleep(1.0)
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90).read()
def rjl(p): return [json.loads(l) for l in open(p)] if os.path.exists(p) else []
def append(p, rows):
    with open(p, "a") as f:
        for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
def norm(n): return re.sub(r"[^a-z]", "", n.lower())
# ---------- judges
seen = set()
for cc in [m.lower() for m in MEMBERS]:
    for r in rjl(f"{ROOT}/data/{cc}/{cc}_judges.jsonl"): seen.add(norm(r["name"]))
raw = get(f"{API}/pages/42623"); pg = json.loads(raw); sha = hashlib.sha256(raw).hexdigest()
out = {}
for s in pg["acf"]["documents"]:
    st = s["section_title"].lower(); cc = next((v for k, v in SEC.items() if k in st), None)
    if not cc: print("unmapped section", st); continue
    master = False
    for p in re.findall(r"<p[^>]*>(.*?)</p>", s["document_details"] or "", re.S):
        t = html.unescape(re.sub(r"<[^>]+>", "", p)).replace("\xa0", " ").strip()
        if not t: continue
        if re.fullmatch(r"Masters?", t, re.I): master = True; continue
        acting = "[Ag.]" in t; circuit = re.search(r"\(([^)]*Circuit)\)", t)
        n = re.sub(r"\[Ag\.\]|\([^)]*\)", "", t)
        n = re.sub(r"^(His Lordship|Her Ladyship),?\s*the\s+Hon\.?\s*Justice\s+|^Master\s+(Hon\.\s*)?", "", n).strip()
        n = re.sub(r",?\s*KC$", "", n.strip(" ,")).strip()
        if not n or norm(n) in seen: continue
        seen.add(norm(n))
        title = ("Master of the High Court" if master else "Puisne Judge, High Court of Justice") + (" (Acting)" if acting else "")
        jid = f"{cc}-high-court-" + re.sub(r"[^a-z0-9]+", "-", n.lower()).strip("-")
        out.setdefault(cc, []).append({"judge_id": jid, "court_id": f"{cc}-high-court", "name": n, "title": title,
            "position_type": "master" if master else "trial", "term_start": None, "term_end": None,
            "status": "acting" if acting else "sitting", "jurisdiction": cc.upper(), "court_system": "ECSC",
            "notes": circuit.group(1) if circuit else None,
            "roster_url": "https://www.eccourts.org/judicial-officers/high-court-judges", "source_url": pg["link"],
            "source_kind": "official", "site_policy": "robots_allowed", "retrieved_at": now, "source_modified": pg["modified"],
            "needs_review": False, "extraction": "official ECSC 'High Court Judges' page, section per member state",
            "license": "Eastern Caribbean Supreme Court website (facts)", "source_sha256": sha})
# ---------- forms
FOUT = f"{ROOT}/data/lc/lc_forms.jsonl"; fold = {r.get("pdf_sha256") for r in rjl(FOUT)} | {r.get("source_url") for r in rjl(FOUT)}
os.makedirs(f"{ROOT}/forms/lc", exist_ok=True); forms = []; fails = []
for pid in (628, 61893):
    p = json.loads(get(f"{API}/pages/{pid}?_fields=link,acf"))
    for s in p["acf"].get("documents") or []:
        cat = "criminal-appeal" if "criminal appeal" in s["section_title"].lower() else ("mediation" if pid == 61893 else "civil")
        for lr in s.get("linked_resources") or []:
            try:
                url = lr.get("doc_url") or json.loads(get(f"{API}/media/{lr['file_upload']}?_fields=source_url"))["source_url"]
                if url in fold: continue
                b = get(url); h = hashlib.sha256(b).hexdigest()
                if h in fold: continue
                ext = url.rsplit(".", 1)[-1].lower()[:5]; path = f"forms/lc/{h}.{ext}"
                if not dry: open(f"{ROOT}/{path}", "wb").write(b)
                fold.add(h); title = html.unescape(lr["resource_title"]).strip()
                m = re.match(r"(Form\s+[\w.]+)", title)
                forms.append({"form_id": f"ecsc-{h[:16]}", "court_id": "lc-high-court" if cat != "criminal-appeal" else "lc-court-of-appeal",
                    "jurisdiction": "ECSC", "applies_to": MEMBERS, "form_number": m.group(1) if m else None, "title": title,
                    "category": cat, "language": "en", "file_format": ext, "pdf_path": path, "pdf_sha256": h, "file_bytes": len(b),
                    "source_url": url, "index_url": p["link"], "license": "Eastern Caribbean Supreme Court published forms; official court forms, no licence stated",
                    "site_policy": "robots_allowed", "retrieved_at": now})
            except Exception as e: fails.append((lr.get("resource_title"), str(e)[:80]))
if not dry:
    for cc, rows in out.items(): append(f"{ROOT}/data/{cc}/{cc}_judges.jsonl", rows)
    append(FOUT, forms)
print("judges", {k: len(v) for k, v in out.items()}, "forms", len(forms), "fails", fails)
for cc, rows in out.items():
    for r in rows: print(" ", cc, r["name"], "|", r["title"])
