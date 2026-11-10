#!/usr/bin/env python3
"""India Code of Civil Procedure 1908, First Schedule Appendices A-H (prescribed forms: pleadings, process,
discovery, decrees, execution, supplemental proceedings, appeal/reference/review, miscellaneous).
Source: official India Code PDF https://www.indiacode.nic.in/bitstream/123456789/2191/1/A1908-05.pdf
via Wayback 20251206201807 (same copy as the IN CPC rules rows; cached at rules/raw/in/cpc.pdf).
Native Word text layer (no OCR). One row per 'No. N' form; form_id in-cpc-app<letter>-<section>-<n>.
Append-only, dedupe by form_id."""
import json, re, os, hashlib, subprocess, datetime, shutil, urllib.request
W="/workspace/world_courts"; RAW=f"{W}/rules/raw/in/cpc.pdf"
ORIG="https://www.indiacode.nic.in/bitstream/123456789/2191/1/A1908-05.pdf"
SRC="https://web.archive.org/web/20251206201807/"+ORIG
UA="WorldCourtsResearchBot/1.0 (court-data research; contact via Benjamin Barber)"
POL="robots_ignored_per_user_authorization|indiacode.nic.in official Legislative Department portal (archived copy via web.archive.org); public statute, no licence stated"
if not os.path.exists(RAW):
    open(RAW,"wb").write(urllib.request.urlopen(urllib.request.Request(SRC.replace("/https:","id_/https:"),headers={"User-Agent":UA}),timeout=180).read())
b=open(RAW,"rb").read(); sha=hashlib.sha256(b).hexdigest(); os.makedirs(f"{W}/forms/in",exist_ok=True)
dst=f"{W}/forms/in/{sha}.pdf"
if not os.path.exists(dst): shutil.copy(RAW,dst)
pages=subprocess.run(["pdftotext","-layout",RAW,"-"],capture_output=True,text=True).stdout.split("\f")
APP=re.compile(r"^\s{20,}APPENDIX ([A-H])\s*$"); SEC=re.compile(r"^\s{15,}\(\s?(\d{1,2})\)\s+(\S.*?)\s*$")
NO=re.compile(r"^\s{10,}(?:\d\s*)?\[?No\.\s?(\d{1,3}[A-Z]?)\.?\s*$"); END=re.compile(r"^\s{15,}(THE SECOND SCHEDULE|SECOND SCHEDULE)")
forms=[]; app=None; apptitle=None; sec=None; sectitle=None; cur=None; started=False; want_apptitle=False
for pi,p in enumerate(pages):
    for l in p.split("\n"):
        m=APP.match(l)
        if m: app=m.group(1); started=True; want_apptitle=True; sec=None; sectitle=None; cur=None; continue
        if not started: continue
        if END.match(l): started=False; break
        if want_apptitle and l.strip():
            apptitle=re.sub(r"\s+"," ",l.strip()); apptitle=re.sub(r"^P LEADINGS","PLEADINGS",apptitle); want_apptitle=False; continue
        m=SEC.match(l)
        if m and not re.match(r"^\d",m.group(2)) and len(m.group(2))<80:
            sec=m.group(1); sectitle=m.group(2); continue
        m=NO.match(l)
        if m:
            cur={"app":app,"apptitle":apptitle,"sec":sec,"sectitle":sectitle,"no":m.group(1),"page":pi+1,"title":[],"lines":[],"tdone":False}
            forms.append(cur); continue
        if cur is None: continue
        if re.match(r"^\s*\d{1,3}\s*$",l): continue
        if not cur["tdone"]:
            s=l.strip()
            if not s: 
                if cur["title"]: cur["tdone"]=True
                continue
            if ((len(l)-len(l.lstrip()))>=15 or ((len(l)-len(l.lstrip()))>=2 and len(s)>4 and sum(c.isupper() for c in s)>0.6*sum(c.isalpha() for c in s))) and s!="(Title)" and not s.startswith("(Title") and len(cur["title"])<3 and not re.match(r"^\d+\.",s):
                cur["title"].append(s); continue
            cur["tdone"]=True
        cur["lines"].append(l.rstrip())
now=datetime.datetime.now(datetime.timezone.utc).isoformat()
out=f"{W}/data/in/in_forms.jsonl"; have=set()
if os.path.exists(out): have={json.loads(l)["form_id"] for l in open(out) if l.strip()}
rows=[]; seen=set()
for f in forms:
    fid=f"in-cpc-app{f['app'].lower()}-{f['sec'] or 0}-{f['no'].lower()}"
    if fid in seen: fid+=f"-p{f['page']}"
    if fid in have or fid in seen: continue
    seen.add(fid)
    title=re.sub(r"\s+"," "," ".join(f["title"])).strip(" .—-") or None
    txt=re.sub(r"\n{3,}","\n\n","\n".join(f["lines"]).strip())
    rows.append({"form_id":fid,"court_id":None,"jurisdiction":"IN","form_number":f"Appendix {f['app']}"+(f" ({f['sec']})" if f["sec"] else "")+f" No. {f['no']}",
      "title":(title.title() if title and title.isupper() else title),"category":f"Code of Civil Procedure 1908, First Schedule, Appendix {f['app']}: {f['apptitle']}"+(f" — {f['sectitle']}" if f["sectitle"] else ""),
      "language":"en","revision_date":None,"file_format":"pdf","pdf_path":f"forms/in/{sha}.pdf","pdf_sha256":sha,"file_bytes":len(b),
      "pdf_start_page":f["page"],"rule_set_id":"in-cpc","text":txt[:20000],"applies_to":["civil courts of India"],
      "source_url":SRC,"original_url":ORIG,"issuer":"Legislative Department, Ministry of Law and Justice (India Code)",
      "license":"public statute; no licence stated","site_policy":POL,"retrieved_at":now,"needs_review":not bool(title)})
if os.environ.get("DRY"): 
    for r in rows: print(r["form_number"],"|",r["title"],"|",r["pdf_start_page"])
else:
    with open(out,"a") as fh:
        for r in rows: fh.write(json.dumps(r,ensure_ascii=False)+"\n")
print("IN CPC appendix forms parsed",len(forms),"new rows",len(rows))
