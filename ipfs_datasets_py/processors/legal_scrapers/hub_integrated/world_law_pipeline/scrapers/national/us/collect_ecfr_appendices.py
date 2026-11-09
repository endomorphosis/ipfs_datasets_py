# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import shutil, sys, time, requests
from lxml import etree
import pyarrow as pa, pyarrow.parquet as pq
OUT=(str(_LEGAL_WS) + "/regs_eo/out/ecfr_appendices")
S=requests.Session(); S.headers["User-Agent"]="endomorphosis-world-laws research"
schema=pa.schema([(k,pa.string()) for k in ["title","part","subpart","kind","label","heading","text","raw_xml","as_of_date"]])
def guard(n):
    free=shutil.disk_usage("/").free/2**30
    mem=[int(l.split()[1]) for l in open("/proc/meminfo") if l.startswith("MemAvailable")][0]/2**20
    print(f"title {n} guard free={free:.2f}G memavail={mem:.2f}Gi",flush=True)
    if free<11 or mem<4.5: print("STOP guard",flush=True); sys.exit(3)
txt=lambda e:" ".join(" ".join(e.itertext()).split())
titles=[t for t in S.get("https://www.ecfr.gov/api/versioner/v1/titles.json",timeout=60).json()["titles"] if not t.get("reserved")]
for t in titles:
    n=t["number"]; d=t["up_to_date_as_of"]; guard(n)
    for a in range(4):
        r=S.get(f"https://www.ecfr.gov/api/versioner/v1/full/{d}/title-{n}.xml",stream=True,timeout=300)
        if r.status_code in (429,500,502,503,504): r.close(); time.sleep(10*(a+1)); continue
        break
    if r.status_code==403 or "xml" not in r.headers.get("content-type",""): print("BOTWALL",n,r.status_code,flush=True); sys.exit(4)
    r.raise_for_status(); r.raw.decode_content=True
    rows=[]; part=subpart=None
    for ev,el in etree.iterparse(r.raw,events=("start","end"),huge_tree=True):
        typ=el.get("TYPE")
        if ev=="start":
            if typ=="PART": part=el.get("N"); subpart=None
            elif typ=="SUBPART": subpart=el.get("N")
            continue
        if el.tag=="DIV8": el.clear()
        elif el.tag=="DIV9":
            h=el.find("HEAD"); raw=etree.tostring(el,encoding="unicode")
            rows.append(dict(title=str(n),part=part,subpart=subpart,kind="appendix",label=el.get("N"),heading=txt(h) if h is not None else None,
                text=txt(el),raw_xml=raw if len(raw)<20000 else None,as_of_date=d)); el.clear()
        elif el.tag=="DIV5":
            bits=[c for c in el if not c.tag.startswith("DIV") and c.tag!="HEAD"]
            if bits:
                h=el.find("HEAD"); raw="".join(etree.tostring(c,encoding="unicode") for c in bits)
                rows.append(dict(title=str(n),part=el.get("N"),subpart=None,kind="part_level",label=el.get("N"),heading=txt(h) if h is not None else None,
                    text=" ".join(txt(c) for c in bits),raw_xml=raw if len(raw)<20000 else None,as_of_date=d))
            el.clear()
            while el.getprevious() is not None: del el.getparent()[0]
    pq.write_table(pa.Table.from_pylist(rows,schema=schema),f"{OUT}/title-{n:02d}.parquet",compression="zstd")
    print(f"title {n} rows={len(rows)} app={sum(r['kind']=='appendix' for r in rows)}",flush=True); time.sleep(2)
print("DONE",flush=True)
