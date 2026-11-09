#!/usr/bin/env python3
"""STJ open data (CKAN, CC-BY): metadadosYYYYMMDD.json + textosYYYYMMDD.zip -> world_caselaw rows.
Resumable via state/amea-br-stj_done.txt (dates). 1 connection, 2 s delay."""
import sys, json, os, re, time, zipfile, io, html, datetime, shutil, requests
UA="world_caselaw-bot/0.1 (legal research dataset; huggingface.co/endomorphosis)"
B="/workspace/world_caselaw"; A=B+"/amea"; SRC="amea-br-stj"; API="https://dadosabertos.web.stj.jus.br/api/3/action/package_show?id="
PKGS=["integras-de-decisoes-terminativas-e-acordaos-do-diario-da-justica","integras-de-decisoes-terminativas-e-acordaos-2008-2020"]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from peachjam import wait_for_space, next_part, save_part
S=requests.Session(); S.headers["User-Agent"]=UA
def log(*a): print(datetime.datetime.now().isoformat(timespec="seconds"),*a,flush=True)
def get(u):
    for i in range(5):
        time.sleep(2)
        try:
            r=S.get(u,timeout=300)
            if r.status_code==200: return r
            log("HTTP",r.status_code,u)
        except Exception as e: log("ERR",e)
        time.sleep(10*2**i)
def clean(t):
    t=re.sub(r"<br\s*/?>|</p>","\n",t); t=html.unescape(re.sub(r"<[^>]+>","",t)); return t.strip()
def next_part(src, d):
    import os, glob, json
    pf = f"/workspace/world_caselaw/amea/state/{src}_part.txt"
    n = int(open(pf).read()) if os.path.exists(pf) else 0
    loc = [int(re.search(r"_part(\d+)", f).group(1)) + 1 for f in glob.glob(f"{d}/{src}_part*.jsonl")]
    return max([n] + loc)
def save_part(src, n):
    open(f"/workspace/world_caselaw/amea/state/{src}_part.txt", "w").write(str(n))

def main():
    os.makedirs(B+"/data/br",exist_ok=True); sf=f"{A}/state/{SRC}_done.txt"
    done=set(open(sf).read().split()) if os.path.exists(sf) else set()
    part=next_part(SRC,B+"/data/br"); buf=[]; bdates=[]
    def flush():
        nonlocal part,buf,bdates
        if not buf: return
        p=f"{B}/data/br/{SRC}_part{part:04d}.jsonl"
        with open(p+".tmp","w") as f:
            for r in buf: f.write(json.dumps(r,ensure_ascii=False)+"\n")
        os.rename(p+".tmp",p); open(sf,"a").write("\n".join(bdates)+"\n"); done.update(bdates)
        log("wrote",p,len(buf)); part+=1; save_part(SRC,part); buf=[]; bdates=[]
    for pkg in PKGS:
        res=get(API+pkg).json()["result"]["resources"]
        meta={}; zips={}
        for r in res:
            m=re.search(r"metadados(\d{8})\.json$",r["url"]); z=re.search(r"textos(\d{8})\.zip$",r["url"]) or re.search(r"/(\d{8})\.zip$",r["url"])
            if m: meta[m.group(1)]=r["url"]
            elif z: zips[z.group(1)]=r["url"]
        for d in sorted(set(meta)&set(zips)):
            if d in done: continue
            wait_for_space()
            mr=get(meta[d]); zr=get(zips[d])
            if not mr or not zr: continue
            try: md=mr.json(); z=zipfile.ZipFile(io.BytesIO(zr.content))
            except Exception as e: log("bad",d,e); continue
            names={n.split("/")[-1].split(".")[0]:n for n in z.namelist()}
            for m in md:
                sq=str(m.get("SeqDocumento")); n=names.get(sq)
                txt=clean(z.read(n).decode("utf8","replace")) if n else None
                buf.append({"id":f"{SRC}:{sq}","court":"Superior Tribunal de Justiça","court_id":"br-national-supreme-stj","jurisdiction_cc":"br","place_id":None,
                 "decision_date":m.get("dataPublicacao"),"case_number":re.sub(r"\s+"," ",m.get("processo") or "") or None,"parties":None,
                 "judges":[m["NM_MINISTRO"]] if m.get("NM_MINISTRO") else None,"citation":None,"text":txt,"source_url":zips[d],
                 "license":"CC-BY-4.0","site_policy":"open-license;robots-allowed","language":"pt","title":f'{m.get("tipoDocumento")} {m.get("processo")}',
                 "source":SRC,"retrieved_at":datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "x_date_kind":"publication","x_doc_type":m.get("tipoDocumento"),"x_registro":m.get("numeroRegistro"),"x_teor":m.get("teor"),"x_assuntos":m.get("assuntos"),"x_metadata_url":meta[d]})
            bdates.append(d)
            if len(buf)>=20000: flush()
    flush(); log("finished")
if __name__=="__main__": main()
