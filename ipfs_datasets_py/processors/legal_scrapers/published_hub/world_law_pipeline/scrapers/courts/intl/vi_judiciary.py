"""US Virgin Islands judiciary (vicourts.org, official): judges, forms and court rules.
 - Judges: Supreme Court 'Justices' page and Superior Court 'Judges' / 'Magistrate Judges' pages (names + titles from the tab titles only).
 - Forms: Superior Court 'Forms' document library (CivicLive content-item listing the page itself loads via
   /portal/svc/ContentItemSvc.asmx/GetItemList); PDFs saved under forms/vi/<sha256>.pdf, deduped by sha256.
 - Rules: 'Rules' library: VI Rules of Civil / Criminal / Appellate Procedure, Evidence, Family Division, Probate and Fiduciary,
   Small Claims, Habeas Corpus, Superior Court Rules, Rules of Judicial Administration; rule-level split of pdftotext output (needs_review).
robots.txt on *.vicourts.org returns 301 -> HTTP 500 (robots_unreachable); polite 1.5-2 s delays. Dedupe by ids; re-runs add 0."""
import json, re, os, sys, time, hashlib, datetime, subprocess, html, requests
ROOT = "/workspace/world_courts"; D = f"{ROOT}/data/vi"; RAW = f"{ROOT}/rules/raw/vi"; FD = f"{ROOT}/forms/vi"
os.makedirs(RAW, exist_ok=True); os.makedirs(FD, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (WorldCourtsResearchBot/1.0; public court directory research; polite crawl)"}
POL = "robots_unreachable|vicourts.org: Judiciary of the U.S. Virgin Islands website; no licence or terms stated"
now = datetime.datetime.now(datetime.UTC).isoformat()
S = requests.Session()
def get(u, **k):
    for i in range(3):
        try:
            r = S.get(u, headers=UA, timeout=120, **k); time.sleep(1.5); r.raise_for_status(); return r
        except Exception as e:
            last = e; time.sleep(5 * (i + 1))
    raise last
def load(p, key): return {json.loads(l)[key] for l in open(p)} if os.path.exists(p) else set()
def slug(s): return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
def write(p, rows):
    with open(p, "a") as f:
        for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")

# ---------- judges ----------
def judges():
    P = f"{D}/vi_judges.jsonl"; old = load(P, "judge_id"); rows = []
    pages = [("https://supreme.vicourts.org/about_us/justices", "vi-supreme-court", "Supreme Court of the Virgin Islands"),
             ("https://superior.vicourts.org/about_us/judicial_officers/judges", "vi-high-court", "Superior Court of the Virgin Islands"),
             ("https://superior.vicourts.org/about_us/judicial_officers/magistrate_judges", "vi-high-court", "Superior Court of the Virgin Islands")]
    for url, cid, cname in pages:
        r = get(url); h = r.text; sha = hashlib.sha256(r.content).hexdigest()
        names = []
        if "justices" in url:
            names = [(m.group(1), None) for m in re.finditer(r'href="/about_us/justices/[^"]+"[^>]*>\s*((?:Chief|Associate) Justice [^<]+?)\s*</a>', h)]
            names = list(dict.fromkeys(names))
        else:
            dist = None
            for m in re.finditer(r'>\s*(Judicial District of [^<]+?)\s*</|"title":"((?:Magistrate )?Judge [^"]+)"', h):
                if m.group(1): dist = html.unescape(m.group(1)).strip()
                else: names.append((html.unescape(m.group(2)).strip(), dist))
        for label, dist in names:
            m = re.match(r"(Chief Justice|Associate Justice|Magistrate Judge|Judge)\s+(.+)", label); t, name = m.group(1), m.group(2).strip()
            name = re.sub(r"\.(?=[A-Z])", ". ", name)
            title = {"Judge": "Judge of the Superior Court"}.get(t, t)
            pos = {"Chief Justice": "chief", "Associate Justice": "associate", "Magistrate Judge": "magistrate", "Judge": "judge"}[t]
            if t == "Judge" and "Gallivan" in name and "Presiding Judge" in h: title, pos = "Presiding Judge of the Superior Court", "president"
            jid = f"{cid}-{slug(name)}"
            if jid in old: continue
            old.add(jid)
            row = {"judge_id": jid, "court_id": cid, "court_name": cname, "name": name, "name_as_listed": label, "title": title, "position_type": pos,
                   "term_start": None, "term_end": None, "status": "sitting", "jurisdiction": "VI", "judicial_district": dist,
                   "roster_url": url, "source_url": url, "source_kind": "official", "site_policy": POL, "retrieved_at": now,
                   "needs_review": False, "extraction": "official roster page tab/link titles (name + title only)",
                   "license": "official public roster; no licence stated", "source_sha256": sha, "language": "en"}
            if t == "Chief Justice":
                row["note"] = "Press Release 2026-0024 (13 Oct 2026): Associate Justice Harold W. L. Willocks elected Chief Justice for a five-year term commencing 13 Dec 2026"
            rows.append(row)
    write(P, rows); return len(rows)

# ---------- CivicLive document library ----------
def library(page_url, delay=1.5):
    h = get(page_url).text; base = re.match(r"https?://[^/]+", page_url).group(0); res = []
    for m in re.finditer(r"new ContentItemListUI\('(\d+)', null, '\[\]', (\{.*?\}), selectMulti", h):
        obj = json.loads(m.group(2)); P = json.dumps(obj)
        def ls(pid):
            r = S.post(base + "/portal/svc/ContentItemSvc.asmx/GetItemList", headers={**UA, "requestFrom": "contentItem", "Content-Type": "application/json; charset=utf-8"},
                       data=json.dumps({"parentId": pid, "Params": P}), timeout=60)
            time.sleep(delay); return r.json()["d"]["DataObject"] or []
        stack, seen = [(obj["ContextId"], [])], set()
        while stack:
            pid, path = stack.pop()
            if pid in seen: continue
            seen.add(pid)
            for it in ls(pid):
                if it["Type"] == "content_folder": stack.append((it["ItemId"], path + ([it["Name"]] if it["Name"] != "Document Container" else [])))
                elif it.get("DownloadLink"): res.append({"path": path, "name": html.unescape(it["Name"]), "ext": it.get("Extension"), "url": html.unescape(it["DownloadLink"]), "modified": it.get("ModifiedDateString"), "item_id": it["ItemId"]})
    return res

def forms():
    P = f"{D}/vi_forms.jsonl"; old = load(P, "form_id"); oldurl = load(P, "source_url"); rows = []
    idx = "https://superior.vicourts.org/forms"
    skip = re.compile(r"Self-Help Guide|^Rules-|Expungement Rule|Rising Stars", re.I)
    for it in library(idx):
        if skip.search(it["name"]) or it["url"] in oldurl: continue
        b = get(it["url"]).content
        if not b.startswith(b"%PDF"): print("not pdf", it["name"]); continue
        sha = hashlib.sha256(b).hexdigest(); fid = f"vi-{sha[:16]}"
        cat = " / ".join(it["path"]) or None
        if fid in old:
            for r in rows:
                if r["form_id"] == fid and cat and cat not in r["category"]: r["category"] += "; " + cat
            continue
        old.add(fid); p = f"{FD}/{sha}.pdf"
        if not os.path.exists(p): open(p, "wb").write(b)
        title = re.sub(r"\s+I$", "", it["name"]).strip()
        rows.append({"form_id": fid, "court_id": "vi-high-court", "court_name": "Superior Court of the Virgin Islands", "jurisdiction": "VI", "form_number": None,
                     "title": title, "category": cat, "language": "en", "revision_date": None, "file_format": "pdf", "pdf_path": f"forms/vi/{sha}.pdf",
                     "pdf_sha256": sha, "file_bytes": len(b), "source_url": it["url"], "index_url": idx, "source_kind": "official", "site_policy": POL,
                     "license": "official court form; no licence stated", "retrieved_at": now, "library_modified": it["modified"]})
    write(P, rows); return len(rows)

# ---------- rules ----------
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
H = re.compile(r"^\s{0,8}(?:RULE|Rule)\s+(\d+(?:\.\d+)*)([A-Z]?)\.?\s+([A-Z\[“\"(].*)$")
def key(num, let): return tuple(int(x) for x in num.split(".")) + ((ord(let) if let else 0),)
def split_rules(txt):
    L = txt.splitlines(); cands = []
    for i, l in enumerate(L):
        if "...." in l or ". . ." in l: continue
        m = H.match(l)
        if not m or re.match(r"(of|and|or|to|in)\b", m.group(3)): continue
        cands.append((i, m.group(1), m.group(2), m.group(3).strip()))
    if not cands: return []
    lead = [i for i, l in enumerate(L[:max(60, len(L) // 6)]) if "...." in l or ". . ." in l]
    if len(lead) >= 3: start = lead[-1] + 1
    else:
        occ = [c for c in cands if (c[1], c[2]) == (cands[0][1], cands[0][2])]; start = occ[1][0] if len(occ) > 1 else occ[0][0]
    out, last = [], None
    for c in cands:
        if c[0] < start: continue
        k = key(c[1], c[2])
        if last is not None and (k <= last or (k[0] > last[0] + 12 and not (k[0] // 100 == last[0] // 100 + 1 and k[0] % 100 <= 2))): continue
        out.append(c); last = k
    res = []
    for j, (i, num, let, title) in enumerate(out):
        e = out[j + 1][0] if j + 1 < len(out) else len(L)
        body = [x.rstrip() for x in L[i:e] if not re.fullmatch(r"\s*(Page )?\d{1,3}( of \d+)?\s*", x.replace("\f", ""))]
        res.append((num + let, title, re.sub(r"\n{3,}", "\n\n", "\n".join(body)).replace("\f", "").strip()))
    return res
SETS = {"VI Rules of Civil Procedure (001)": ("vi-rcp", "Virgin Islands Rules of Civil Procedure", "vi-high-court"),
        "VI Rules of Criminal Procedure": ("vi-rcrp", "Virgin Islands Rules of Criminal Procedure", "vi-high-court"),
        "VI Rules of Evidence": ("vi-re", "Virgin Islands Rules of Evidence", None),
        "VI Family Rules": ("vi-rfdp", "Virgin Islands Rules of Family Division Procedure", "vi-high-court"),
        "Probate Rules": ("vi-rpfp", "Virgin Islands Rules of Probate and Fiduciary Procedure", "vi-high-court"),
        "VI Small Claims Rules": ("vi-scr", "Virgin Islands Small Claims Rules", "vi-high-court"),
        "VI Habeas Corpus Rules": ("vi-hcr", "Virgin Islands Habeas Corpus Rules", "vi-high-court"),
        "VI Rules of Appellate Procedure": ("vi-rap", "Virgin Islands Rules of Appellate Procedure", "vi-supreme-court"),
        "VI Superior Court Rules": ("vi-scrules", "Rules of the Superior Court of the Virgin Islands", "vi-high-court"),
        "VI Rules of Judicial Administration": ("vi-rja", "Virgin Islands Rules of Judicial Administration (Supreme Court Rules)", "vi-supreme-court")}
def rules():
    P = f"{D}/vi_rules.jsonl"; old = load(P, "rule_id"); rows = []; idx = "https://www.vicourts.org/rules"
    for it in library(idx):
        if it["name"] not in SETS: continue
        sid, sname, cid = SETS[it["name"]]
        p = f"{RAW}/{re.sub(r'\W+', '_', it['name']).strip('_')}.pdf"
        if not os.path.exists(p): open(p, "wb").write(get(it["url"]).content)
        sha = hashlib.sha256(open(p, "rb").read()).hexdigest()
        txt = subprocess.run(["pdftotext", "-layout", p, "-"], capture_output=True, text=True).stdout
        n0 = len(rows); seen = set()
        for num, title, text in split_rules(txt):
            rid = f"{sid}:r{num}"
            if rid in old or rid in seen: continue
            seen.add(rid)
            rows.append({"rule_id": rid, "rule_set_id": sid, "court_id": cid, "jurisdiction": "VI", "rule_set": sname, "rule_number": f"Rule {num}",
                         "title": re.sub(r"\s+", " ", title).strip(), "text": text, "effective_date": None, "pdf_path": None, "pdf_sha256": sha,
                         "source_sha256": sha, "source_url": it["url"], "index_url": idx, "source_kind": "official", "site_policy": POL, "retrieved_at": now,
                         "granularity": "rule", "license": "official court rules published by the Judiciary of the Virgin Islands; no licence stated",
                         "language": "en", "library_modified": it["modified"], "needs_review": True,
                         "extraction": "pdftotext -layout split at 'Rule N.' headings after the table of contents; titles may be truncated where headings wrap"})
        print(sid, "new", len(rows) - n0)
    write(P, rows); return len(rows)

if __name__ == "__main__":
    what = sys.argv[1:] or ["judges", "forms", "rules"]
    for w in what: print(w, "added", globals()[w]())
