#!/usr/bin/env python3
"""Colombia Corte Constitucional: metadata from datos.gov.co Socrata v2k4-2t8s, full text from
relatoria HTML (robots: Allow /relatoria/). 1 conn, 3 s delay. Resumable via state/amea-co-cc_done.txt."""
import json, os, re, time, html, datetime, shutil, requests, sys
sys.path.insert(0, os.path.dirname(__file__))
from peachjam import wait_for_space, next_part, save_part, log
UA="world_caselaw-bot/0.1 (legal research dataset; huggingface.co/endomorphosis)"
B="/workspace/world_caselaw"; A=B+"/amea"; SRC="amea-co-cc"; D=B+"/data/co"
S=requests.Session(); S.headers["User-Agent"]=UA
def get(u, delay=3):
    for i in range(4):
        time.sleep(delay)
        try:
            r=S.get(u,timeout=90)
            if r.status_code==200: return r
            if r.status_code==404: return None
            log("HTTP",r.status_code,u)
        except Exception as e: log("ERR",e)
        time.sleep(10*2**i)
def text_of(h):
    h=re.sub(r"(?is)<(script|style|head)[^>]*>.*?</\1>|<!--.*?-->","",h)
    h=re.sub(r"(?i)</(p|div|h\d|li|tr)>|<br\s*/?>","\n",h)
    t=html.unescape(re.sub(r"<[^>]+>","",h)); return "\n".join(l.strip() for l in t.splitlines() if l.strip())
def main():
    os.makedirs(D,exist_ok=True); sf=f"{A}/state/{SRC}_done.txt"
    done=set(open(sf).read().split()) if os.path.exists(sf) else set()
    part=next_part(SRC,D); buf=[]
    def flush():
        nonlocal part,buf
        if not buf: return
        p=f"{D}/{SRC}_part{part:04d}.jsonl"
        with open(p+".tmp","w") as f:
            for r in buf: f.write(json.dumps(r,ensure_ascii=False)+"\n")
        os.rename(p+".tmp",p); open(sf,"a").write("\n".join(r["case_number"] for r in buf)+"\n")
        log("wrote",p,len(buf)); part+=1; save_part(SRC,part); buf=[]
    off=0; n=0
    while True:
        r=get(f"https://www.datos.gov.co/resource/v2k4-2t8s.json?$order=fecha_sentencia&$limit=1000&$offset={off}",1)
        rows=r.json() if r else []
        if not rows: break
        off+=len(rows)
        for m in rows:
            s=m.get("sentencia");
            if not s or s in done: continue
            wait_for_space()
            date=(m.get("fecha_sentencia") or "")[:10] or None
            mm=re.match(r"([A-Za-z]+)-(\d+[A-Za-z]?)/(\d{2,4})",s.strip())
            url=None; txt=None
            if mm:
                yy=mm.group(3); yr=date[:4] if date else (("19" if int(yy[-2:])>90 else "20")+yy[-2:])
                url=f"https://www.corteconstitucional.gov.co/relatoria/{yr}/{mm.group(1)}-{mm.group(2)}-{yy[-2:]}.htm"
                rr=get(url)
                if rr: rr.encoding=rr.apparent_encoding or "latin-1"; txt=text_of(rr.text)
            buf.append({"id":f"{SRC}:{s}","court":"Corte Constitucional","court_id":"co-corte-constitucional","jurisdiction_cc":"co","place_id":None,
              "decision_date":date,"case_number":s,"parties":None,"judges":[m["magistrado_a"]] if m.get("magistrado_a") else None,"citation":f"Sentencia {s}",
              "text":txt,"source_url":url or "https://www.datos.gov.co/resource/v2k4-2t8s","license":"unknown","site_policy":"robots-allowed",
              "language":"es","title":f'Sentencia {s} ({m.get("proceso")})',"source":SRC,"retrieved_at":datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "x_proceso":m.get("proceso"),"x_expediente":f'{m.get("expediente_tipo")}{m.get("expediente_numero")}',"x_sala":m.get("sala"),
              "x_metadata_source":"https://www.datos.gov.co/d/v2k4-2t8s","x_text_status":"ok" if txt else "not-found"})
            n+=1
            if n%50==0: log("progress",n,s)
            if len(buf)>=500: flush()
    flush(); log("finished",n)
if __name__=="__main__": main()
