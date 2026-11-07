"""2026-10-21 county followup to urlfix report_20261021T215745Z: text layers for empty rows (RO Q191717, DE Q10408, Q5970),
encoded source_url for 4 RO rows. Never touches state/doc_overrides.json."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import json,os,re,sys,time,shutil,hashlib,collections,urllib.request,urllib.parse
from datetime import datetime,timezone
sys.path.insert(0,(_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/pipeline")); sys.path.insert(0,(_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/pipeline/scrapers/counties"))
from schema import validate_file, validate_record
from county_pdfstage import ScanStager, text_of, quote_url, sniff
from archive import ArchiveFetcher, provenance_fields
W=_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)); UA="Mozilla/5.0 (world_law county lane)"; P=f"{W}/processed/counties"; S="urlfix20261021T215745Z"
OUT=f"{W}/staging/counties/_urlfix/followup"
src={("RO","wd_Q191717"):f"{P}/RO/wd_Q191717.ro_cj_hcj-{S}p0001.jsonl",("DE","wd_Q10408"):f"{P}/DE/wd_Q10408.de_by_kreisrecht-{S}p0001.jsonl",
     ("DE","wd_Q5970"):f"{P}/DE/wd_Q5970.de_nds_kreisrecht-{S}p0001.jsonl",("RO","wd_Q179779"):f"{P}/RO/wd_Q179779.ro_cj_hcj-{S}p0001.jsonl",
     ("RO","wd_Q191065"):f"{P}/RO/wd_Q191065.ro_cj_hcj-{S}p0001.jsonl"}
ENC={"ro_cj_hcj:9ce7542d8a0856cc~737d3d68","ro_cj_hcj:f8a301d48133b804~4553a75f","ro_cj_hcj:234c42da37ae55ff~d8a184d7","ro_cj_hcj:48329170772e3731~5ef9ceee"}
rawmap=json.load(open("/tmp/rawmap.json"))
man={}
for f in os.listdir(f"{W}/staging/pdf/_manifest"):
    if f.endswith(".jsonl"):
        for l in open(f"{W}/staging/pdf/_manifest/{f}"):
            try: r=json.loads(l); man.setdefault(r["doc_id"],set()).add(r["sha256"])
            except Exception: pass
sys.path.insert(0,OUT); from robots import robots
fx=None; stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
ss=ScanStager(chunk=100000); rep={}; detail=[]
for (cc,pk),f in src.items():
    rows=[json.loads(l) for l in open(f)]; out=[]; st=collections.Counter()
    for r in rows:
        if shutil.disk_usage("/workspace").free/1e9<45: print("DISK<45GB STOP"); sys.exit(2)
        enc = r["doc_id"] in ENC
        if pk in ("wd_Q179779","wd_Q191065") and not enc: continue
        if not enc and (r.get("text") or r.get("html")): continue
        u0=r["source_url"]; u=quote_url(u0); r=dict(r); r["source_url"]=u; data=None; how=None; prov={}
        for p in rawmap.get(u0,[]):
            if os.path.exists(p): data=open(p,"rb").read(); how="raw"; break
        if data is None:
            pol=robots(u)
            if pol in ("robots_allowed_rfc9309","robots_404_allow_rfc9309"):
                try:
                    with urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":UA}),timeout=120) as x: data=x.read(); ct=x.headers.get("Content-Type","")
                    how="live"; time.sleep(2)
                    if sniff(data,u,ct)!="pdf": how="live_notpdf:"+sniff(data,u,ct); data=None
                except Exception as e: how=f"live_fail:{e}"[:80]
            if data is None:
                try:
                    fx=fx or ArchiveFetcher(cc_crawls=8); d=fx.fetch_newest(u0 if " " in u0 else u)
                    if d is not None and sniff(d.body,u)=="pdf":
                        data=d.body; prov=provenance_fields(d); how="archive"; r.update(prov); r["source_policy"]="archived_"+pol if not str(pol).startswith("archived") else pol
                    else: how=(how or "")+"|archive_none"
                except Exception as e: how=(how or "")+f"|archive_fail:{e}"[:80]
        if data is None:
            st["still_empty"]+=1; detail.append((cc,pk,r["doc_id"],u,how))
            if enc: out.append(r); st["encoded_only"]+=1
            continue
        txt=text_of(data)
        if len(txt.strip())>=200:
            for k in ("scanned_pdf","content_complete","pdf_bytes","pdf_path"): r.pop(k,None)
            r["text"]=txt; r["content_format"]="pdf_text"; st["text_"+how]+=1; out.append(r)
        else:
            if r.get("text"): out.append(r); st["kept_text"]+=1; continue
            r.update(content_complete=False,scanned_pdf=True,pdf_bytes=len(data)); r.pop("text",None)
            base=r["doc_id"]; sha=hashlib.sha256(data[data.find(b"%PDF-"):]).hexdigest()
            if sha in man.get(base,()):
                st["scan_already_in_manifest"]+=1
                if enc: out.append(r)
            else:
                pth=ss.add(data,r,r.get("retrieved_at") or stamp); st["scan_staged"]+=1 if pth else 0
                if enc: out.append(r)
            detail.append((cc,pk,base,u,"scan:"+how))
    if out:
        plat=out[0]["source_platform"]; fin=f"{W}/staging/counties/{cc}/{pk}.{plat}-textfix{stamp}p0001.jsonl"; tmp=fin+".tmp"
        os.makedirs(os.path.dirname(fin),exist_ok=True)
        with open(tmp,"w",encoding="utf-8") as fh:
            for x in out: fh.write(json.dumps(x,ensure_ascii=False)+"\n")
            fh.flush(); os.fsync(fh.fileno())
        chk=f"{OUT}/_check.jsonl"; shutil.copy(tmp,chk); v=validate_file(chk,expect_place_key=pk)
        if v.get("bad_rows") or v.get("file_errors"): print("VALIDATE FAIL",pk,v["errors"][:3]); os.unlink(tmp); st["validate_fail"]=1
        else: os.rename(tmp,fin); st["file"]=os.path.basename(fin)
        st["rows_staged"]=len(out)
    rep[f"{cc}/{pk}"]=dict(st); print(cc,pk,dict(st),flush=True)
ss.flush()
json.dump(dict(report=rep,batches=ss.batches,detail=detail),open(f"{OUT}/report_{stamp}.json","w"),indent=1,ensure_ascii=False)
print("BATCHES",ss.batches)
