"""OCR-based rule rows for Laos procedure laws (Lao Official Gazette scans) and Nepal
Supreme Court Rules 2074 / District Court Rules 2075 (supremecourt.gov.np scans).
OCR: tesseract 5.5 (lao / nep traineddata 4.1.0), 250 dpi, pages in /tmp/ocr/<tag>/pNNNN.txt.
Splits into articles/rules by a monotonic heading sequence; all rows needs_review (OCR)."""
import re,glob,json,hashlib,os,datetime,sys
ROOT="/workspace/world_courts"; RAW=f"{ROOT}/rules/raw"
LD=str.maketrans("໐໑໒໓໔໕໖໗໘໙०१२३४५६७८९","01234567890123456789")
NOW=datetime.datetime.now(datetime.timezone.utc).isoformat()
LA_POL="robots_ignored_per_user_authorization|laoofficialgazette.gov.la official Lao Official Gazette (Ministry of Justice), no restrictive terms found|live fetch 2026-11-02, polite delays"
NP_POL="robots_none|supremecourt.gov.np/robots.txt returns no rules (no restrictions); official Supreme Court of Nepal website, no terms of use stated"
DOCS=[
 ("la","la1","la_1.pdf","la-civil-procedure-2025","ກົດໝາຍວ່າດ້ວຍການດຳເນີນຄະດີແພ່ງ (ສະບັບປັບປຸງ) / Law on Civil Procedure (amended, promulgated 22 Dec 2025)","2025","lo",2,"ມາດຕາ"),
 ("la","la2","la_2.pdf","la-criminal-procedure-2017","ກົດໝາຍວ່າດ້ວຍການດຳເນີນຄະດີອາຍາ (ສະບັບປັບປຸງ) / Law on Criminal Procedure (amended 2017)","2017","lo",2,"ມາດຕາ"),
 ("la","la3","la_3.pdf","la-juvenile-procedure","ກົດໝາຍວ່າດ້ວຍການດຳເນີນຄະດີເດັກ / Law on Juvenile Criminal Procedure","","lo",2,"ມາດຕາ"),
 ("la","la4","la_4.pdf","la-court-fees-2019","ກົດໝາຍວ່າດ້ວຍຄ່າທຳນຽມສານ (ສະບັບປັບປຸງ) / Law on Court Fees (amended, promulgated 6 Aug 2019)","2019","lo",2,"ມາດຕາ"),
 ("la","la5","la_5.pdf","la-peoples-court-law","ກົດໝາຍວ່າດ້ວຍສານປະຊາຊົນ (ສະບັບປັບປຸງ) / Law on the People's Courts (amended)","","lo",2,"ມາດຕາ"),
 ("la","la6","la_6.pdf","la-peoples-court-law-amendment-2025","ກົດໝາຍວ່າດ້ວຍການປັບປຸງບາງມາດຕາຂອງກົດໝາຍວ່າດ້ວຍສານປະຊາຊົນ / Law amending certain articles of the Law on the People's Courts (2025)","2025","lo",2,"ມາດຕາ"),
 ("np","npsc","np/sc_rules_2074.pdf","np-sc-rules-2074","सर्वोच्च अदालत नियमावली, २०७४ (Supreme Court Rules, 2074)","2017","ne",0,None),
 ("np","npdc","np/dc_rules_2075.pdf","np-dc-rules-2075","जिल्ला अदालत नियमावली, २०७५ (District Court Rules, 2075)","2018","ne",0,None),
]
def near(a,b): a,b=str(a),str(b); return len(a)==len(b) and sum(x!=y for x,y in zip(a,b))<=1
out={"la":[],"np":[]}
for cc,tag,pdf,rsid,rsname,yr,lang,skip,kw in DOCS:
    pdfp=f"{RAW}/{pdf}" if "/" in pdf else f"{RAW}/la/{pdf}"
    sha=hashlib.sha256(open(pdfp,"rb").read()).hexdigest()
    pages=sorted(glob.glob(f"/tmp/ocr/{tag}/p*.txt")); txt="\n".join(open(p).read() for p in pages)
    if cc=="np":
        cut=re.search(r'(?m)^\s*अनुसूची\s*[-–—]?\s*[१1]\b',txt)
        if cut: txt=txt[:cut.start()]
        pat=re.compile(r'(?m)^\s*([०-९]{1,3})\.\s*(?=\S)')
    else:
        pat=re.compile(r'(?m)^\s*ມາດຕາ\s*([0-9໐-໙][0-9໐-໙!\]|#]{0,2}|[!\]|#][0-9໐-໙]{0,2})(?=\s)')
    hs=list(pat.finditer(txt)); ones=[i for i,m in enumerate(hs) if m.group(1).translate(LD) in ("1","!","|","]")]
    if len(ones)<=skip: hs=hs[ones[-1]:] if ones else hs
    else: hs=hs[ones[skip]:]
    acc=[]; prev=0
    for i,m in enumerate(hs):
        g=m.group(1).translate(LD)
        if not g.isdigit():
            if prev>0 and len(g)==len(str(prev+1)): acc.append((prev+1,m)); prev+=1
            continue
        n=int(g)
        if prev+1<=n<=prev+3: acc.append((n,m)); prev=n
        elif prev>0 and near(n,prev+1): acc.append((prev+1,m)); prev+=1
    rows=[]
    for k,(n,m) in enumerate(acc):
        end=acc[k+1][1].start() if k+1<len(acc) else len(txt)
        body=txt[m.end():end].strip(); body=re.sub(r'\n{2,}','\n',body)
        first=body.split("\n",1)[0].strip(" .:()")
        title=re.split(r'[:：]',first,maxsplit=1)[0][:120] if cc=="np" else first[:120]
        rows.append({"rule_id":f"{rsid}:{n}","rule_set_id":rsid,"court_id":None,"jurisdiction":cc.upper(),"rule_set":rsname,
          "rule_number":(f"ມາດຕາ {n}" if cc=="la" else f"नियम {n}"),"title":title,"part":None,"text":body[:20000],
          "effective_date":None,"pdf_path":os.path.relpath(pdfp,ROOT),"pdf_sha256":sha,"source_sha256":sha,
          "source_url":("https://laoofficialgazette.gov.la/" if cc=="la" else "https://supremecourt.gov.np/web/courtrules"),
          "index_url":("https://laoofficialgazette.gov.la/" if cc=="la" else "https://supremecourt.gov.np/web/courtrules"),
          "site_policy":LA_POL if cc=="la" else NP_POL,"retrieved_at":NOW,
          "license":("Lao PDR legislation (public law), official gazette scan; no licence stated" if cc=="la" else "Nepal court rules (public law), official Supreme Court publication; no licence stated"),
          "language":lang,"source_kind":"official_ocr","version_note":f"tesseract 5.5 OCR ({lang}) of scanned official PDF; year {yr or 'unknown'}; article boundaries detected automatically; OCR errors likely","needs_review":True})
    print(tag,len(rows),rows[-1]["rule_number"] if rows else None, file=sys.stderr)
    out[cc]+=rows
# NP: two-column gazette layout loses rule numbers in OCR; NP rows disabled until segmentation is fixed (OCR text kept in rules/raw/np/*.ocr.txt)
out['np']=[]
for cc,rows in out.items():
    f=f"{ROOT}/data/{cc}/{cc}_rules.jsonl"; have=set()
    if os.path.exists(f): have={json.loads(l)["rule_id"] for l in open(f)}
    new=[r for r in rows if r["rule_id"] not in have]
    if "--write" in sys.argv:
        with open(f,"a") as fh:
            for r in new: fh.write(json.dumps(r,ensure_ascii=False)+"\n")
    print(cc,"new",len(new),file=sys.stderr)
