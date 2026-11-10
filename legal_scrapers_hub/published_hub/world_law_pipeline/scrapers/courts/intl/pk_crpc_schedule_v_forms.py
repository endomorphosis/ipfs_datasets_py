#!/usr/bin/env python3
"""Pakistan Code of Criminal Procedure 1898, Schedule V (s.555) prescribed forms I-LIII.
Source: official PDF https://www.fmu.gov.pk/docs/laws/Code_of_criminal_procedure_1898.pdf (Financial Monitoring
Unit, Govt of Pakistan; same copy as the PK CrPC rules rows; cached at rules/raw/pk/crpc.pdf). Native text layer.
One row per roman-numbered form; omitted forms kept with status omitted. Append-only, dedupe by form_id."""
import json, re, os, hashlib, subprocess, datetime, shutil, urllib.request
W="/workspace/world_courts"; RAW=f"{W}/rules/raw/pk/crpc.pdf"
SRC="https://www.fmu.gov.pk/docs/laws/Code_of_criminal_procedure_1898.pdf"
UA="WorldCourtsResearchBot/1.0 (court-data research; contact via Benjamin Barber)"
POL="robots_ignored_per_user_authorization|fmu.gov.pk official Government of Pakistan site; public statute text, no licence stated"
if not os.path.exists(RAW):
    open(RAW,"wb").write(urllib.request.urlopen(urllib.request.Request(SRC,headers={"User-Agent":UA}),timeout=180).read())
b=open(RAW,"rb").read(); sha=hashlib.sha256(b).hexdigest(); os.makedirs(f"{W}/forms/pk",exist_ok=True)
dst=f"{W}/forms/pk/{sha}.pdf"
if not os.path.exists(dst): shutil.copy(RAW,dst)
pages=subprocess.run(["pdftotext","-layout",RAW,"-"],capture_output=True,text=True).stdout.split("\f")
def rom(s):
    v={"I":1,"V":5,"X":10,"L":50}; t=0
    for i,c in enumerate(s):
        t+= -v[c] if i+1<len(s) and v[c]<v[s[i+1]] else v[c]
    return t
HDR=re.compile(r"^\s*(1|[IVXL]{1,7})\s*(?:\.\s*)?(?:[-—–]+\s*)?(?<=[\.\-—– ])\s*([A-Z\[].{3,})$")
start=None; forms=[]; cur=None; last=0
for pi,p in enumerate(pages):
    for l in p.split("\n"):
        if start is None:
            if re.match(r"^\s*SCHEDULE\s*-\s*V\s*$",l): start=pi
            continue
        m=HDR.match(l)
        if m:
            n=1 if m.group(1)=="1" else rom(m.group(1))
            if n==last+1 or (n>last and n-last<=3 and cur and len(cur["lines"])>5):
                cur={"n":n,"roman":m.group(1) if m.group(1)!="1" else "I","title":m.group(2).strip(),"page":pi+1,"lines":[]}; forms.append(cur); last=n; continue
        if cur: cur["lines"].append(l.rstrip())
now=datetime.datetime.now(datetime.timezone.utc).isoformat()
out=f"{W}/data/pk/pk_forms.jsonl"; have=set()
if os.path.exists(out): have={json.loads(l)["form_id"] for l in open(out) if l.strip()}
rows=[]
for f in forms:
    fid=f"pk-crpc-sch5-form-{f['n']}"
    if fid in have: continue
    body="\n".join(f["lines"]); first=[x.strip() for x in f["lines"] if x.strip()][:2]
    t=f["title"]
    if first and not re.match(r"^\(See",first[0]) and not t.endswith(".") and first[0][:1].islower(): t+=" "+first[0]
    sec=re.search(r"\(See (Sections?[^)]*)\)",body[:400])
    omitted=bool(re.search(r"^\s*\[?Omitted",body.strip()[:60],re.I))
    t=re.sub(r"\s+"," ",t).strip(" .-—")
    rows.append({"form_id":fid,"court_id":None,"jurisdiction":"PK","form_number":f"Form {f['roman']}","title":t,
      "category":"Code of Criminal Procedure 1898, Schedule V (Forms)","language":"en","revision_date":None,"file_format":"pdf",
      "pdf_path":f"forms/pk/{sha}.pdf","pdf_sha256":sha,"file_bytes":len(b),"pdf_start_page":f["page"],
      "rule_reference":sec.group(1) if sec else None,"rule_set_id":"pk-crpc","status":"omitted" if omitted else "prescribed",
      "text":re.sub(r"\n{3,}","\n\n",body.strip())[:20000],"applies_to":["criminal courts of Pakistan"],
      "source_url":SRC,"issuer":"Government of Pakistan (statute text as published by FMU)","license":"public statute; no licence stated",
      "site_policy":POL,"retrieved_at":now,"needs_review":True,"notes":"unofficial-consolidation formatting; headers parsed heuristically"})
if os.environ.get("DRY"):
    for r in rows: print(r["form_number"],"|",r["title"],"|",r["rule_reference"],"|",r["status"])
else:
    with open(out,"a") as fh:
        for r in rows: fh.write(json.dumps(r,ensure_ascii=False)+"\n")
print("PK CrPC Sch V forms parsed",len(forms),"new",len(rows))
