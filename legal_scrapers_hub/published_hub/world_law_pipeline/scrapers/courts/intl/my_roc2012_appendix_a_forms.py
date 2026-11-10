#!/usr/bin/env python3
"""Malaysia Rules of Court 2012 (P.U.(A) 205/2012) Appendix A prescribed forms.
Source: official Attorney General's Chambers LOM PDF
https://lom.agc.gov.my/ilims/upload/portal/akta/outputp/pua_20120702_RULES%20OF%20COURT%202012%20(FINAL)%20-%201%20July%202012.pdf
(already cached at rules/raw/my/roc2012.pdf by the MY rules scraper). Native text layer (not OCR).
One row per form number from the 'APPENDIX A / LIST OF FORMS' table (title, Order, rule), with the form body
text taken from the 'No. N' sections. As-gazetted 2012 text: later amendments (e.g. P.U.(A) 2013-2023) are NOT
applied, so rows carry revision_date 2012-07-02. Append-only, dedupe by form_id."""
import json, re, os, hashlib, subprocess, datetime, shutil, urllib.request
W="/workspace/world_courts"; RAW=f"{W}/rules/raw/my/roc2012.pdf"
SRC="https://lom.agc.gov.my/ilims/upload/portal/akta/outputp/pua_20120702_RULES%20OF%20COURT%202012%20(FINAL)%20-%201%20July%202012.pdf"
UA="WorldCourtsResearchBot/1.0 (court-data research; contact via Benjamin Barber)"
POL="robots_ignored_per_user_authorization|lom.agc.gov.my official AGC Laws of Malaysia portal; federal subsidiary legislation, public; no licence stated"
if not os.path.exists(RAW):
    os.makedirs(os.path.dirname(RAW),exist_ok=True)
    open(RAW,"wb").write(urllib.request.urlopen(urllib.request.Request(SRC,headers={"User-Agent":UA}),timeout=180).read())
b=open(RAW,"rb").read(); sha=hashlib.sha256(b).hexdigest()
dst=f"{W}/forms/my/{sha}.pdf"
if not os.path.exists(dst): shutil.copy(RAW,dst)
pages=subprocess.run(["pdftotext","-layout",RAW,"-"],capture_output=True,text=True).stdout.split("\f")
# list of forms
li=next(i for i,p in enumerate(pages) if "LIST OF FORMS" in p and "APPENDIX A" in p)
fi=next(i for i,p in enumerate(pages) if i>li and re.search(r"APPENDIX A\s*\n\s*FORMS\s*\n",p))
lst="\n".join(pages[li:fi])
lst=lst[lst.index("LIST OF FORMS"):]
entries=[]; cur=None
ent=re.compile(r"^\s{0,3}(\d{1,3}[A-Z]{0,2})\.\s{2,}(.*)$")
for l in lst.split("\n"):
    if re.match(r"^\s*(\d{3}|P\.U\. \(A\) 205|Form No\.|LIST OF FORMS|APPENDIX A)",l) and not ent.match(l): continue
    m=ent.match(l)
    if m:
        cur={"no":m.group(1),"raw":m.group(2),"refs":[]}; entries.append(cur)
    elif cur is not None and l.strip():
        cur["raw"]+=" "+l.strip()
LEAD=re.compile(r"(?:\s?…\s?|\s?\.{2,}\s?){2,}\.*")
PAIR=re.compile(r"(?<![\w,\[])(\d{1,3}[A-Z]?)(?:\s*…\s*|\s{3,})(\d{1,3}[A-Z]{0,2})(?![\w\]])")
for e in entries:
    r=LEAD.sub(" ¦ ",e["raw"])
    pairs=PAIR.findall(r)
    t=PAIR.sub(" ",r)
    t=re.sub(r"\s+"," ",t.replace("¦"," ")).strip(" .…,")
    e["title"]=t; e["order_rule"]=[f"O. {o}, r. {q}" for o,q in pairs]
# bodies
body={}; curk=None
for pi in range(fi,len(pages)):
    for l in pages[pi].split("\n"):
        m=re.match(r"^\s{20,}No\.\s?(\d{1,3}[A-Z]{0,2})\s*$",l)
        if m:
            curk=m.group(1); body.setdefault(curk,{"page":pi+1,"lines":[]}); continue
        if curk and not re.match(r"^\s*(\d{3}|P\.U\. \(A\) 205)\s*$",l): body[curk]["lines"].append(l.rstrip())
now=datetime.datetime.now(datetime.timezone.utc).isoformat()
out=f"{W}/data/my/my_forms.jsonl"; have=set()
if os.path.exists(out): have={json.loads(l)["form_id"] for l in open(out) if l.strip()}
rows=[]; seen=set()
for e in entries:
    fid=f"my-roc2012-form-{e['no'].lower()}"
    if fid in have or fid in seen: continue
    seen.add(fid)
    deleted=e["title"].lower().startswith("(deleted")
    bd=body.get(e["no"])
    txt=re.sub(r"\n{3,}","\n\n","\n".join(bd["lines"]).strip()) if bd else None
    rows.append({"form_id":fid,"court_id":None,"jurisdiction":"MY","form_number":f"Form {e['no']}","title":e["title"],
      "category":"Rules of Court 2012, Appendix A (Forms)","language":"en","revision_date":"2012-07-02","file_format":"pdf",
      "pdf_path":f"forms/my/{sha}.pdf","pdf_sha256":sha,"file_bytes":len(b),"pdf_start_page":bd["page"] if bd else None,
      "rule_reference":"; ".join(e["order_rule"]) or None,"rule_set_id":"my-roc2012","status":"deleted" if deleted else "prescribed",
      "text":(txt[:20000] if txt else None),"applies_to":["High Court","Sessions Court","Magistrates' Court"],
      "source_url":SRC,"issuer":"Rules Committee and Subordinate Courts Rules Committee (Malaysia); published by Attorney General's Chambers",
      "license":"official gazette (P.U.(A) 205/2012); no licence stated","site_policy":POL,"retrieved_at":now,
      "needs_review":bool(deleted or not bd),"notes":"as gazetted 2 July 2012; later amendments not applied"})
with open(out,"a") as fh:
    for r in rows: fh.write(json.dumps(r,ensure_ascii=False)+"\n")
print("MY RoC2012 forms list",len(entries),"bodies",len(body),"new rows",len(rows))
