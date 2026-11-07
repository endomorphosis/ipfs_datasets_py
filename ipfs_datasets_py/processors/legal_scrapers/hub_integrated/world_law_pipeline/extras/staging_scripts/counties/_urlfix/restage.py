# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import json,glob,os,re,hashlib,shutil,sys,time,collections,urllib.robotparser,urllib.request,urllib.parse
from datetime import datetime,timezone
sys.path.insert(0,(_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/pipeline")); sys.path.insert(0,(_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/pipeline/scrapers/counties"))
from schema import validate_file
from county_pdfstage import ScanStager
W=_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)); UA="world_law-counties/1.0 (+research; robots respected)"
def ts(f):
    m=re.search(r"(\d{8}T\d{4,6})Z",os.path.basename(f)); return (m.group(1) if m else "0", f)
def sfx(u): return hashlib.sha1(u.encode()).hexdigest()[:8]
files=sorted(glob.glob(f"{W}/processed/counties/*/*.jsonl")+glob.glob(f"{W}/staging/counties/*/*.jsonl"),key=ts)
rows=collections.defaultdict(dict); plainids=collections.defaultdict(set)
for f in files:
    cc=f.split('/')[-2]; pk=os.path.basename(f).split('.')[0]
    for l in open(f):
        r=json.loads(l); u=r.get("source_url","")
        if "?" in u and "~" not in r["doc_id"]: rows[(cc,pk)][u]=r
        else: plainids[(cc,pk)].add(r["doc_id"])
man=set()
for f in glob.glob(f"{W}/staging/pdf/_manifest/batch_*.jsonl"):
    for l in open(f):
        try: man.add(json.loads(l)["doc_id"])
        except Exception: pass
rp={}
def allowed(u):
    h=urllib.parse.urlsplit(u); base=f"{h.scheme}://{h.netloc}"
    if base not in rp:
        p=urllib.robotparser.RobotFileParser(); 
        try:
            req=urllib.request.Request(base+"/robots.txt",headers={"User-Agent":UA})
            with urllib.request.urlopen(req,timeout=20) as x: p.parse(x.read().decode("utf-8","replace").splitlines()); st="ok"
        except urllib.error.HTTPError as e: st="404" if e.code in (404,410) else "unreach"; p.parse([])
        except Exception: st="unreach"; p.parse([])
        rp[base]=(p,st)
    p,st=rp[base]; return st!="unreach" and p.can_fetch(UA,u), st
def get(u):
    req=urllib.request.Request(u,headers={"User-Agent":UA})
    with urllib.request.urlopen(req,timeout=60) as x: return x.read()
stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
stager=ScanStager(); report={}; failed=[]; overrides=[]
for (cc,pk),d in sorted(rows.items()):
    if shutil.disk_usage("/workspace").free/1e9<45: print("DISK<45GB stop"); break
    out=[]; st=collections.Counter()
    for u,r in d.items():
        old=r["doc_id"]; r=dict(r); new=old+"~"+sfx(u); r["doc_id"]=new
        raw=r.pop("raw_path",None); r.pop("raw_xml_path",None)
        if r.get("text") or r.get("html"): st["existing_text"]+=1
        elif new in man: st["scan_pdf_already_suffixed"]+=1
        else:
            data=None; pol=None
            if raw and os.path.exists(raw): data=open(raw,"rb").read(); st["pdf_from_raw"]+=1
            else:
                ok,rs=allowed(u)
                try:
                    if ok: data=get(u); time.sleep(1); st["refetched_live"]+=1
                    else: raise Exception("robots "+rs)
                except Exception as e:
                    try:
                        data=get("https://web.archive.org/web/2026id_/"+u); time.sleep(1); st["refetched_archive"]+=1
                        r["archive_source"]="wayback"; r["archive_url"]="https://web.archive.org/web/2026id_/"+u; r["original_url"]=u
                    except Exception as e2: failed.append((cc,pk,u,f"{e} | archive: {e2}")); data=None
            if data is not None:
                if stager.add(data,dict(r,doc_id=old),r.get("retrieved_at") or stamp) is None:
                    failed.append((cc,pk,u,"fetched bytes are not a PDF")); 
        out.append(r)
        if old not in plainids[(cc,pk)]: overrides.append(dict(country_code=cc,place_key=pk,doc_id=old,source_file="hub:world_municipal_law",reason=f"counties urlfix: collapsed query-less doc_id superseded by ~urlhash ids in {pk}.*urlfix{stamp}",added="2026-10-21"))
    plat=out[0]["source_platform"]; fin=f"{W}/staging/counties/{cc}/{pk}.{plat}-urlfix{stamp}p0001.jsonl"; tmp=fin+".tmp"
    with open(tmp,"w",encoding="utf-8") as f:
        for r in out: f.write(json.dumps(r,ensure_ascii=False)+"\n")
        f.flush(); os.fsync(f.fileno())
    chk=f"{W}/staging/counties/_urlfix/_check.jsonl"; shutil.copy(tmp,chk); v=validate_file(chk,expect_place_key=pk); v={k:v[k] for k in v if k in ("ok","n_ok","n_err","errors","rows","n_rows")} if isinstance(v,dict) else v
    os.rename(tmp,fin); report[f"{cc}/{pk}"]=dict(rows=len(out),file=os.path.basename(fin),validate=str(v)[:200],**st); print(report[f"{cc}/{pk}"],flush=True)
stager.flush()
json.dump(dict(report=report,failed=failed,pdf_batches=stager.batches,overrides=sorted({o["doc_id"]+"|"+o["place_key"] for o in overrides})),open(f"{W}/staging/counties/_urlfix/report_{stamp}.json","w"),indent=1)
json.dump(overrides,open(f"{W}/staging/counties/_urlfix/overrides_{stamp}.json","w"))
print("FAILED",len(failed),"PDF batches",stager.batches,"overrides",len({(o['place_key'],o['doc_id']) for o in overrides}))
