"""NP: Supreme Court Rules 2074 (156 pp) and District Court Rules 2075 (48 pp), scanned Nepal Gazette PDFs from supremecourt.gov.np
(saved in rules/raw/np/). Earlier plain-text OCR lost the rule numbers printed in the left margin (hanging-indent layout), so this
re-OCRs each page with tesseract 5.5 (nep, 200 dpi) in TSV mode and uses line x-positions: margin numbers are re-attached to their
heading line, misread digits are corrected against the expected monotonic sequence, and rules with no OCR'd number are recovered
from margin/paragraph-start headings ("title: (1) ...") when their count exactly fills the gap. Schedules (अनुसूची) are excluded.
All rows source_kind=official_ocr, needs_review. Append-only, dedupe on rule_id. Usage: np_courtrules_ocr_layout.py [--write]"""
import sys, os, re, glob, json, hashlib, datetime, subprocess, csv, collections
ROOT = "/workspace/world_courts"; RAWD = f"{ROOT}/rules/raw/np"; WORK = "/tmp/npc"
NOW = datetime.datetime.now(datetime.timezone.utc).isoformat()
NP_POL = "robots_none|supremecourt.gov.np/robots.txt returns no rules (no restrictions); official Supreme Court of Nepal website, no terms of use stated"
DOCS = [("sc", "sc_rules_2074.pdf", "np-sc-rules-2074", "सर्वोच्च अदालत नियमावली, २०७४ (Supreme Court Rules, 2074)", 166, 80, "2017"),
        ("dc", "dc_rules_2075.pdf", "np-dc-rules-2075", "जिल्ला अदालत नियमावली, २०७५ (District Court Rules, 2075)", 127, 150, "2018")]
def ocr(tag, pdf):
    os.makedirs(f"{WORK}/{tag}", exist_ok=True); n = int(re.search(r"Pages:\s+(\d+)", subprocess.run(["pdfinfo", pdf], capture_output=True, text=True).stdout).group(1))
    for p in range(1, n + 1):
        f = f"{WORK}/{tag}/p{p:04d}"
        if os.path.exists(f + ".tsv") and os.path.getsize(f + ".tsv"): continue
        subprocess.run(["pdftoppm", "-r", "200", "-gray", "-f", str(p), "-l", str(p), "-singlefile", pdf, f], timeout=120)
        subprocess.run(["tesseract", f + ".pgm", f, "-l", "nep", "tsv"], capture_output=True, timeout=300); os.remove(f + ".pgm")
def page_lines(f):
    L=collections.OrderedDict()
    for r in csv.DictReader(open(f),delimiter='\t',quoting=csv.QUOTE_NONE):
        if r['level']!='5' or not r['text'].strip(): continue
        k=(int(r['block_num']),int(r['par_num']),int(r['line_num']))
        L.setdefault(k,[]).append((int(r['left']),int(r['top']),int(r['width']),r['text']))
    out=[]
    for k,ws in L.items():
        out.append((min(w[0] for w in ws),min(w[1] for w in ws)," ".join(w[3] for w in ws)))
    out.sort(key=lambda x:x[1]); return out
LD=str.maketrans("०१२३४५६७८९","0123456789")
SKIP=re.compile(r'(राजपत्र|आधिकारिकता|मुद्रण विभाग)')
def near(a,b): a,b=str(a),str(b); return len(a)==len(b) and sum(x!=y for x,y in zip(a,b))<=1
def lines(tag):
    L=[]
    for f in sorted(glob.glob(f'/tmp/npc/{tag}/p*.tsv')):
        pg=int(f[-8:-4]); ls=[l for l in page_lines(f) if not SKIP.search(l[2]) and not (re.fullmatch(r'[०-९0-9\s\-]+',l[2].strip()) and not re.search(r'[.,।]',l[2]))]
        if not ls: continue
        body=collections.Counter(round(l[0]/10) for l in ls).most_common(1)[0][0]*10
        k=0; ls=list(ls)
        while k<len(ls):
            x,y,t=ls[k]
            if k>0 and re.fullmatch(r'\s*[०-९]{1,3}\s*[.,।]\s*',t) and abs(y-ls[k-1][1])<35 and ls[k-1][0]>x:
                px,py,pt=ls[k-1]; L[-1]=(pg,x,t.strip()+' '+pt,body)
            else: L.append((pg,x,t,body))
            k+=1
    return L
NUM=re.compile(r'^\s*([०-९]{1,3})\s*[.,।]\s*')
TH=80
def ishead(L,j):
    t=L[j][2].strip()
    if t.startswith('(') or t.startswith('“') or t.startswith('"'): return False
    m=re.match(r'^([^:ः।]{3,80}?)\s*[:ः]\s*(\([१1]\)|[^\s\-–]|$)',t)
    if not m or len(m.group(1).split())>10 or re.search(r'(भन्नाले|देहाय|बमोजिम|हुनेछ|सक्नेछ)',m.group(1)): return False
    if L[j][1]<L[j][3]-60: return True
    p=L[j-1][2].strip() if j else ''
    return p.endswith(('।','|')) or L[j-1][1]>L[j][3]+TH or 'परिच्छेद' in p
def rules(tag,maxn):
    L=lines(tag)
    for i,(pg,x,t,b) in enumerate(L):
        if re.match(r'^\s*अनुसूची\s*[-–—]?\s*[१1]\s*$',t.strip()) and i>200: L=L[:i]; break
    acc=[]; prev=0
    for i,(pg,x,t,b) in enumerate(L):
        if t.lstrip().startswith('('): continue
        m=NUM.match(t)
        if not m: continue
        n=int(m.group(1).translate(LD))
        if n>maxn: n=int(str(n)[1:]) if len(str(n))>1 and int(str(n)[1:])>prev else -1
        if prev<n<=prev+10:
            # avoid jumping when the next numbered line is prev+1
            acc.append([i,n]); prev=n
        else:
            for d in (1,2):
                if near(n,prev+d): acc.append([i,prev+d]); prev+=d; break
    # fill gaps by margin headings
    full=[]; notes={}
    for k,(i,n) in enumerate(acc):
        p_i,p_n=(acc[k-1] if k else (0,0))
        g=n-p_n-1
        if g>0:
            c=[j for j in range(p_i+1 if k else 0,i) if ishead(L,j)]
            if len(c)==g:
                for q,j in enumerate(c): full.append((j,p_n+1+q,'margin'))
            elif full: notes[full[-1][1]]=f"may also contain rules {p_n+1}-{n-1} (OCR missed their boundaries)"
        full.append((i,n,'num'))
    full.sort()
    out=[]
    for k,(i,n,how) in enumerate(full):
        end=full[k+1][0] if k+1<len(full) else len(L)
        body="\n".join(l[2] for l in L[i:end]); body=re.sub(NUM,'',body,count=1)
        out.append(dict(n=n,page=L[i][0],body=body,how=how,note=notes.get(n)))
    return out
out = []
for tag, pdf, rsid, rsname, maxn, th, yr in DOCS:
    pdfp = f"{RAWD}/{pdf}"; sha = hashlib.sha256(open(pdfp, "rb").read()).hexdigest(); ocr(tag, pdfp); TH = th
    rs = rules(tag, maxn)
    for x in rs:
        body = re.sub(r"\n{2,}", "\n", x["body"]).strip(); title = re.split(r"[:ः]", body.split("\n", 1)[0], maxsplit=1)[0].strip(" .")[:120]
        vn = f"tesseract 5.5 TSV OCR (nep, 200 dpi) of scanned official Nepal Gazette PDF; year {yr}; rule boundary from {'OCR margin number' if x['how']=='num' else 'heading position (number not OCR-legible)'}; OCR errors likely; page {x['page']}"
        if x["note"]: vn += "; " + x["note"]
        out.append({"rule_id": f"{rsid}:{x['n']}", "rule_set_id": rsid, "court_id": None, "jurisdiction": "NP", "rule_set": rsname,
            "rule_number": f"नियम {x['n']}", "title": title, "part": None, "text": body[:20000], "effective_date": None,
            "pdf_path": os.path.relpath(pdfp, ROOT), "pdf_sha256": sha, "source_sha256": sha,
            "source_url": "https://supremecourt.gov.np/web/courtrules", "index_url": "https://supremecourt.gov.np/web/courtrules",
            "site_policy": NP_POL, "retrieved_at": NOW, "license": "Nepal court rules (public law), official Supreme Court publication; no licence stated",
            "language": "ne", "source_kind": "official_ocr", "version_note": vn, "needs_review": True})
    print(tag, len(rs), file=sys.stderr)
f = f"{ROOT}/data/np/np_rules.jsonl"; have = {json.loads(l)["rule_id"] for l in open(f)}
new = [r for r in out if r["rule_id"] not in have]
if "--write" in sys.argv:
    with open(f, "a") as fh:
        for r in new: fh.write(json.dumps(r, ensure_ascii=False) + "\n")
print("np new", len(new), file=sys.stderr)
