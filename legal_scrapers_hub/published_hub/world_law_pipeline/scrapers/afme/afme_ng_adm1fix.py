"""NG ID fix: wave-11 NG files are STATE-level (admin_level=state, wd:Q<state>) so they can never match the 819 NG municipal (LGA) places.
Per SCHEMA.md s3 first-level subdivisions use place_id iso:NG-XX, admin_level adm1, qid=state QID. Writes corrected copies afme/NG/iso_NG-XX.ng_<live|arch>_w11a1.jsonl
(originals kept; the staged wd_Q* copies are superseded, see README Wave 12)."""
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import json,glob,os,sys,shutil
sys.path.insert(0,(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline")); from schema import validate_file
if shutil.disk_usage("/workspace").free<38*2**30: print("STOP disk floor"); sys.exit(3)
ISO={"Q117714":"AN","Q145793":"ZA","Q320852":"AB","Q376241":"GO","Q387745":"KO","Q503905":"OY","Q506808":"EB","Q532153":"BY","Q534917":"EK","Q682571":"KN","Q682777":"YO","Q748523":"KE","Q836645":"NA"}
D=(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/out/afme/NG"); n=0
for f in sorted(glob.glob(f"{D}/wd_Q*.ng_*_w11.jsonl")):
    q=os.path.basename(f).split(".")[0][3:]; iso=ISO[q]; kind=os.path.basename(f).split("_")[-2]
    out=f"{D}/iso_NG-{iso}.ng_{kind}_w11a1.jsonl"; rows=[]
    for l in open(f):
        d=json.loads(l); d.update(place_id=f"iso:NG-{iso}",qid=q,admin_level="adm1",iso_3166_2=f"NG-{iso}"); rows.append(d)
    open(out+".tmp","w").write("".join(json.dumps(r,ensure_ascii=False)+"\n" for r in rows)); os.rename(out+".tmp",out)
    v=validate_file(out); print(os.path.basename(out),len(rows),v.get("ok"),v.get("bad",""),flush=True); n+=1
print("files",n)
