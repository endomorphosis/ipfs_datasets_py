"""Federal local rules (district, bankruptcy, circuit) from each court's official site: find the 'Local Rules' page from the home page,
download current local-rules PDFs/HTML (robots + crawl delay; no archive fallback, no bypass), split into rules, crosswalk rule set -> us-fed-* body
and its courthouses. Output: rules/out/us_rules_FD.jsonl + us_rules_crosswalk_FD.jsonl (world_courts only; upstream ipfs_court_rules is per-state STATE-XX, so not contributed)."""
import re, json, sys, os, hashlib, datetime, urllib.parse, urllib.request, collections, subprocess
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, "/workspace/world_courts/scrapers/courts"); sys.path.insert(0, "/workspace/world_courts/scrapers/courts/rules")
import us_cos_ingest as I
from rules_common import html_text, pdf_text, PDFDIR, ROOT
from rules_build import extract, eff_date
from robots_policy import UA
OUT = ROOT + "/rules/out"; B = [json.loads(l) for l in open(I.D + "us_federal_courts.jsonl")]
FED_HEAD = re.compile(r"^\s*(?:(?:LOCAL\s+)?(?:CIVIL\s+|CRIMINAL\s+|BANKRUPTCY\s+|APPELLATE\s+|PATENT\s+|ADMIRALTY\s+)?RULE|(?:Local\s+)?(?:Civil\s+|Criminal\s+|Bankruptcy\s+)?Rule|L\.?\s?[BCRA]?\.?\s?R\.?|LR|LCvR|LCrR|LBR|Cir\.\s?R\.|(?:Local\s+)?Circuit\s+Rule|I\.?O\.?P\.?)\s*(?P<num>\d{1,4}(?:[.\-]\d+){0,3}[A-Za-z]?(?:\.\d+)?)\.?[ ]*(?P<rest>(?:[A-Z(\[][^\n]{0,160})?)$", re.M)
def binget(u, n=40_000_000):
    cp = ROOT + "/rules/raw/fed/" + hashlib.md5(u.encode()).hexdigest()
    if os.path.exists(cp): return open(cp, "rb").read(), open(cp + ".pol").read()
    b, pol = _binget(u, n)
    if b: os.makedirs(os.path.dirname(cp), exist_ok=True); open(cp, "wb").write(b); open(cp + ".pol", "w").write(pol)
    return b, pol
def _binget(u, n):
    host = urllib.parse.urlsplit(u).netloc; lk = I._lk.setdefault(host, __import__("threading").Lock())
    with lk:
        pol, delay = I.robots(u)
        if pol == "robots_disallowed": return None, pol
        w = I._last.get(host, 0) + delay - __import__("time").time()
        if w > 0: __import__("time").sleep(w)
        try: b = urllib.request.urlopen(urllib.request.Request(u.replace(" ", "%20"), headers={"User-Agent": UA}), timeout=90).read(n)
        except Exception: b = None
        I._last[host] = __import__("time").time()
    return b, pol
def links(h, base): return [(urllib.parse.urljoin(base, x), re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", t)).strip()) for x, t in re.findall(r'href="([^"#]+)"[^>]*>(.*?)</a>', h, re.S)]
BAD = re.compile(r"amend|propos|redline|comment|notice|order|archiv|prior|former|previous|histor|track|red-?line|summary|chang", re.I)
def one(b):
    h, pol, err = I.fetch(b["website"])
    if not h: return b, [], err
    host = urllib.parse.urlsplit(b["website"]).netloc
    cand = [u for u, t in links(h, b["website"]) if re.search(r"local[- _]?rules|^rules|rules[- ]and[- ]|court rules|circuit rules|rules-?procedures|rules-orders", t + " " + urllib.parse.urlsplit(u).path, re.I) and host in u]
    docs = []
    for lp in list(dict.fromkeys(cand))[:2]:
        if lp.lower().split("?")[0].endswith(".pdf"): docs.append((lp, "Local Rules", lp)); continue
        hh, pp, ee = I.fetch(lp)
        if not hh: continue
        for u, t in links(hh, lp):
            if not re.search(r"\.pdf($|\?)", u, re.I) or BAD.search(t + " " + u): continue
            if re.search(r"local|rule|L\.?R\.?|appendix|internal operating", t + " " + u, re.I): docs.append((u, t, lp))
        if not docs and len(html_text(hh.encode())) > 20000: docs.append((lp, "Local Rules (HTML)", lp))
    docs = list({d[0]: d for d in docs}.values())[:6]; rows = []
    for u, t, idx in docs:
        isp = not u.lower().split("?")[0].endswith(("htm", "html", "/")) and ".pdf" in u.lower()
        bb, pol2 = binget(u)
        if not bb: continue
        sha = hashlib.sha256(bb).hexdigest()
        if isp:
            if not bb.startswith(b"%PDF"): continue
            d = f"{PDFDIR}/FED"; os.makedirs(d, exist_ok=True); pp = f"{d}/{sha}.pdf"
            if not os.path.exists(pp): open(pp, "wb").write(bb)
            try: text = pdf_text(pp)
            except Exception: continue
        else: text = html_text(bb); pp = None
        rs = extract(text, FED_HEAD, False, True, True, False)
        best = {}
        for r in rs:
            if len(r["body"]) > len(best.get(r["num"], {"body": ""})["body"]): best[r["num"]] = r
        rs = [r for r in best.values() if len(r["body"]) >= 40]
        if len(rs) < 3: continue
        abbr = re.sub(r"[^A-Za-z0-9]+", "-", (t or "LR"))[:40].strip("-") or "LR"; rsid = f"US-FED:{b['court_id'][7:]}:{abbr}:{sha[:8]}"
        now = datetime.datetime.now(datetime.UTC).isoformat()
        for r in rs:
            rows.append({"rule_id": f"{rsid}:{r['num']}", "rule_set_id": rsid, "court_id": b["court_id"], "jurisdiction": "US-federal", "rule_set": f"{b['name']} — {t}",
                "rule_set_abbrev": abbr, "rule_family": "local_court_rules", "rule_level": b["court_type"], "rule_number": r["num"], "rule_label": f"{b['court_id'][7:].upper()} LR {r['num']}",
                "title": r.get("title"), "part_heading": None, "text": r["body"], "effective_date": eff_date(r["body"][-400:]), "pdf_path": f"rules/pdf/FED/{sha}.pdf" if pp else None,
                "pdf_sha256": sha if pp else None, "source_sha256": sha, "source_file": None, "source_url": u, "index_url": idx, "site_policy": pol2, "retrieved_at": now,
                "external_ref": None, "needs_review": True, "parser_warnings": []})
    return b, rows, None if rows else ("no_local_rules_link" if not cand else "no_parsable_rules")
if __name__ == "__main__":
    todo = [b for b in B if b["court_type"] in ("district", "bankruptcy", "circuit", "cofc", "cit")]
    with ThreadPoolExecutor(16) as ex: res = list(ex.map(one, todo))
    rows = [r for _, rs, _ in res for r in rs]; seen = set(); uniq = []
    for r in rows:
        if r["rule_id"] not in seen: seen.add(r["rule_id"]); uniq.append(r)
    with open(OUT + "/us_rules_FD.jsonl", "w") as f:
        for r in uniq: f.write(json.dumps(r, ensure_ascii=False) + "\n")
    ch = collections.defaultdict(list)
    for l in open(I.D + "us_courthouses.jsonl"):
        c = json.loads(l)
        if c.get("parent_court_id", "") and str(c["parent_court_id"]).startswith("us-fed-") and c.get("record_type") != "court_body": ch[c["parent_court_id"]].append(c)
    xw = []
    for rsid, cid in sorted({(r["rule_set_id"], r["court_id"]) for r in uniq}):
        nm = next(b["name"] for b in B if b["court_id"] == cid)
        xw.append({"rule_set_id": rsid, "court_id": cid, "court_name": nm, "link_basis": "federal:issuing_court", "link_confidence": "high"})
        for c in ch[cid]: xw.append({"rule_set_id": rsid, "court_id": c["court_id"], "court_name": c.get("official_name") or c["name"], "link_basis": "federal:courthouse_of_issuing_court", "link_confidence": "high"})
    with open(OUT + "/us_rules_crosswalk_FD.jsonl", "w") as f:
        for x in xw: f.write(json.dumps(x) + "\n")
    blk = collections.Counter(e for _, _, e in res if e)
    print("rules", len(uniq), "rule_sets", len({r["rule_set_id"] for r in uniq}), "courts_with_rules", len({r["court_id"] for r in uniq}), "of", len(todo), "xwalk", len(xw), dict(blk))
    json.dump([{"court_id": b["court_id"], "reason": e} for b, _, e in res if e], open(OUT + "/us_rules_FD_blockers.json", "w"), indent=0)
