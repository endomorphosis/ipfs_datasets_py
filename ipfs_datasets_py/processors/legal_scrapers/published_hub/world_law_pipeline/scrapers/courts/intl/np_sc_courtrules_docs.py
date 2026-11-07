"""NP: Supreme Court of Nepal 'courtrules' page (supremecourt.gov.np/web/courtrules, official; live 2026-11-02): current court rules
(नियमावली: Supreme Court Rules 2074, High Court Rules 2073 (+1st amendment 2075), District Court Rules 2075, SC 2nd amendment notice),
Administration of Justice Act 2073 and Supreme Court directives/procedures (निर्देशिका / कार्यविधि: live-broadcast hearings, video-conference
hearings, judgment execution, service of summons, court management (bail/deposit), inspection, child justice, diversion, confidentiality,
access to information, online dates, case notes). Repealed rules (2048/2049/2052), substantive codes and the procedure codes already
ingested are skipped. One document-level row per PDF with extracted text (Unicode text layer, or Preeti legacy font converted with npttf2utf);
scanned PDFs without a text layer, and PDFs whose legacy-font text layer extracts garbled (quality gate), are skipped. All rows needs_review. Append-only. Usage: np_sc_courtrules_docs.py [--dry]"""
import json, re, html, os, sys, time, hashlib, datetime, subprocess, shutil, urllib.parse
ROOT = "/workspace/world_courts"; RAW = f"{ROOT}/rules/raw/np/courtrules"; os.makedirs(RAW, exist_ok=True)
UA = "world_courts/0.1 (open court-data research; github.com/endomorphosis)"; B = "https://supremecourt.gov.np/web/courtrules"; dry = "--dry" in sys.argv
OUT = f"{ROOT}/data/np/np_rules.jsonl"; now = datetime.datetime.now(datetime.timezone.utc).isoformat()
POL = "robots_none|supremecourt.gov.np/robots.txt returns no rules (no restrictions); official Supreme Court of Nepal website, no terms of use stated"
NPV = "/tmp/npv/bin/python"  # venv with npttf2utf (pip install npttf2utf)
def get(u, out=None):
    r = subprocess.run(["curl", "-sk", "-L", "-g", "-m", "240", "-A", UA] + (["-o", out] if out else []) + [u], capture_output=True); time.sleep(2); return r.stdout
t = get(B).decode("utf-8", "replace"); s = t[t.find('class="entry"'):t.find("col-md-4 sidebar")]
links = []
for m in re.finditer(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', s, re.S):
    u = re.sub(r"/web/index\.php/\.\./", "/web/", urllib.parse.urljoin(B, m.group(1).strip())); ti = re.sub(r"\s+", " ", html.unescape(re.sub("<[^>]+>", "", m.group(2)))).strip()
    if u.lower().endswith(".pdf"): links.append((u, ti))
KEEP = re.compile(r"नियमा?वली|निर्देशिका|कार्यविधि|न्यायप्रशासन ऐन|प्रत्यक्ष प्रसारण|निरीक्षण|संसोधन\] नियमावली")
DROP = re.compile(r"२०४८|२०४९|२०५२|बाह्रौं|देवानी कार्यविधि|फौजदारी कार्यविधि|संहिता|संविधान|वरिष्ठ अधिवक्ता|बैतानिक|सञ्चार प्रविधि नीति|केही नेपाल कानून")
DV = re.compile(r"[\u0900-\u097F]")
old = [json.loads(l) for l in open(OUT) if l.strip()]; ids = {r["rule_id"] for r in old}; srcs = {r.get("source_url") for r in old}
# quality gate: many PDFs use legacy fonts whose text layer extracts with broken conjuncts / wrong glyphs. Score = share of Devanagari tokens
# found in a vocabulary built from the already-ingested NP procedure codes; rows below MINQ are skipped (not ingested) and reported.
import collections; _vc = collections.Counter(w for r in old if not r["rule_id"].startswith("np-sc-") for w in re.findall(r"[\u0900-\u097F]+", r["text"]))
VOC = {w for w, c in _vc.items() if c >= 3}; MINQ = 0.6
def qscore(x): toks = re.findall(r"[\u0900-\u097F]+", x); return sum(t in VOC for t in toks) / max(1, len(toks))
rows = []; rep = []
for u, ti in links:
    if not KEEP.search(ti) or DROP.search(ti): continue
    if u in srcs: rep.append((ti[:40], "already")); continue
    fn = hashlib.sha1(u.encode()).hexdigest()[:12] + ".pdf"; p = f"{RAW}/{fn}"
    if not os.path.exists(p):
        if shutil.disk_usage("/workspace").free < 20 * 2**30: raise SystemExit("disk < 20 GB, pausing downloads")
        get(urllib.parse.quote(u, safe=":/%"), p)
    b = open(p, "rb").read() if os.path.exists(p) else b""
    if not b.startswith(b"%PDF"): rep.append((ti[:40], "not pdf")); continue
    sha = hashlib.sha256(b).hexdigest()
    txt = subprocess.run(["pdftotext", p, "-"], capture_output=True, text=True).stdout.replace("\f", "\n")
    enc = "unicode"
    if len(DV.findall(txt)) < 300:
        if len(re.findall(r"[A-Za-z;\]\[/]", txt)) > 1500:
            txt = subprocess.run([NPV, "-c", "import sys,os,npttf2utf as n;m=n.FontMapper(os.path.join(os.path.dirname(n.__file__),'map.json'));"
                                  "print(m.map_to_unicode(sys.stdin.read(),from_font='Preeti',unescape_html_input=False,escape_html_output=False))"],
                                 input=txt, capture_output=True, text=True).stdout; enc = "preeti->unicode (npttf2utf)"
        else: rep.append((ti[:40], "no text layer (scan)")); continue
    txt = re.sub(r"[ \t]+", " ", txt); txt = re.sub(r"\n\s*\n+", "\n", txt).strip()
    if len(DV.findall(txt)) < 300: rep.append((ti[:40], "text not Devanagari")); continue
    q = qscore(txt)
    if q < MINQ: rep.append((ti[:40], f"garbled text layer (quality {q:.2f} < {MINQ}), skipped", enc)); continue
    sid = "np-sc-" + hashlib.sha1(u.encode()).hexdigest()[:10]; rid = f"{sid}:doc"
    if rid in ids: continue
    kind = "rules" if "नियमा" in ti else "act" if "ऐन" in ti else "directive"
    rows.append({"rule_id": rid, "rule_set_id": sid, "court_id": "np-supreme-court" if kind != "act" else None, "jurisdiction": "NP", "rule_set": ti,
        "rule_number": None, "title": ti, "part": None, "text": txt[:150000], "effective_date": None, "pdf_path": f"rules/raw/np/courtrules/{fn}",
        "pdf_sha256": sha, "source_sha256": sha, "source_url": u, "index_url": B, "source_kind": "official", "site_policy": POL,
        "license": "Nepal court rules/directives (Supreme Court of Nepal); laws and official documents are excluded from copyright (Copyright Act 2059 s.4)",
        "retrieved_at": now, "language": "ne", "needs_review": True,
        "version_note": f"document-level row ({kind}); text {enc}; vocabulary quality score {q:.2f}; listed on {B}" + ("; text truncated at 150k chars" if len(txt) > 150000 else "")})
    rep.append((ti[:40], "ok", enc, len(txt)))
if not dry and rows:
    with open(OUT, "a") as f:
        for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("rules new", len(rows)); [print(x) for x in rep]
