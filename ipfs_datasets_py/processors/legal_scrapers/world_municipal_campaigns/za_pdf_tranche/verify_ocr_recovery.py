"""Remote verification for the ZA OCR-recovery publish (2026-10-13).

Fresh listing + download of all 11 data/<MDB>_html.parquet files;
row counts vs run_manifest.json rows_after; preservation check of the
remote CPT file against this morning's cached live baseline
(live_recovery/); full world_municipal gate re-validation of the remote
CPT (metro) and WC015 (local, control) parquets; coverage_report.md
content checks. Read-only against HF.
"""
import json
import os
import sys
from pathlib import Path

os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"

sys.path.insert(0, ".")
import za_pdf_tranche_build as B
from world_municipal.parquet_io import read_html_parquet
from world_municipal.schema import validation_report

Z = Path(".")
REPO_ID = "endomorphosis/ipfs_south_africa_municipal_laws"
DL = Z / "live_verify2"
DL.mkdir(exist_ok=True)

from huggingface_hub import HfApi, hf_hub_download
api = HfApi()
info = api.dataset_info(REPO_ID)
files = sorted(s.rfilename for s in info.siblings or [])
print(f"LISTING: {len(files)} files")
assert "README.md" in files
assert "manifests/za_overlap_crosswalk.jsonl" in files
assert any(f.startswith("data/laws-") for f in files)
assert "coverage_report.md" in files

manifest = json.load(open("run_manifest.json"))
muns = manifest["municipalities"]
total = 0
counts = {}
for code in B.CODES_ALL if hasattr(B, "CODES_ALL") else [
        "CPT", "ETH", "JHB", "EC443", "WC011", "WC012", "WC013",
        "WC015", "WC023", "WC033", "WC041"]:
    p = hf_hub_download(REPO_ID, f"data/{code}_html.parquet",
                        repo_type="dataset", local_dir=str(DL))
    rows = read_html_parquet(p).to_pylist()
    counts[code] = len(rows)
    exp = muns[code]["rows_after"]
    total += len(rows)
    status = "OK" if len(rows) == exp else "MISMATCH"
    print(f"{code}: remote {len(rows)} vs manifest {exp} {status}")
    assert len(rows) == exp, code
print(f"TOTAL remote rows: {total}")

# preservation: CPT unchanged in this stage — live_recovery baseline was
# refreshed to the current 2,135-row live file by this stage's write, so
# remote must equal it row-for-row in full.
base = read_html_parquet(Z / "live_recovery" / "data" / "CPT_html.parquet").to_pylist()
remote_cpt = read_html_parquet(DL / "data" / "CPT_html.parquet").to_pylist()
assert len(base) == 2135 and len(remote_cpt) == 2135
for a, b in zip(base, remote_cpt):
    for k in a:
        assert str(a[k]) == str(b[k]), (k, a.get("doc_id"))
print("CPT preservation: remote identical to 2,135-row baseline OK")
new = remote_cpt[-1]
assert new["doc_id"] == "2011-sub-council-further-amendment-document", new["doc_id"]
assert new["regeling_work_id"] == "/akn/za-cpt/act/by-law/2011/sub-council-further-amendment"
print(f"CPT OCR row present remotely: {new['doc_id']} ({len(new['text'])} chars)")

# preservation: WC023 unchanged in this stage — baseline refreshed to the
# current 1,594-row live file; remote must equal it row-for-row in full.
base23 = read_html_parquet(Z / "live_recovery" / "data" / "WC023_html.parquet").to_pylist()
remote_23 = read_html_parquet(DL / "data" / "WC023_html.parquet").to_pylist()
assert len(base23) == 1594 and len(remote_23) == 1594, (len(base23), len(remote_23))
for a, b in zip(base23, remote_23):
    for k in a:
        assert str(a[k]) == str(b[k]), (k, a.get("doc_id"))
print("WC023 preservation: remote identical to 1,594-row baseline OK")
new23 = [r for r in remote_23 if r["regeling_work_id"] == "/akn/za-wc023/act/by-law/2007/rules-of-order-regulating-the-conduct-of-meetings"]
assert len(new23) == 7, len(new23)
print(f"WC023 OCR rows present remotely: {[r['doc_id'] for r in new23]}")

# preservation: remote ETH first 1868 rows == pre-publish live baseline
# (live_recovery/data/ETH_html.parquet holds the 1,868-row live file from
# before the water-supply stage publish; refreshed by this stage's write)
base_eth = read_html_parquet(Z / "live_recovery" / "data" / "ETH_html.parquet").to_pylist()
remote_eth = read_html_parquet(DL / "data" / "ETH_html.parquet").to_pylist()
assert len(base_eth) == 1868 and len(remote_eth) == 1869, (len(base_eth), len(remote_eth))
for a, b in zip(base_eth, remote_eth):
    for k in a:
        assert str(a[k]) == str(b[k]), (k, a.get("doc_id"))
print("ETH preservation: all 1868 baseline rows identical in remote file OK")
new_eth = remote_eth[len(base_eth):]
assert [r["regeling_work_id"] for r in new_eth] == [
    "/akn/za-eth/act/by-law/1996/water-supply"], [r["doc_id"] for r in new_eth]
assert len(new_eth) == 1, len(new_eth)
assert new_eth[0]["doc_id"] == "1996-water-supply-document"
assert len(new_eth[0]["text"]) > 200000, len(new_eth[0]["text"])
for _m in ["Kwa-Dukuza", "Stanger", "105, 1996", "103, 1996"]:
    assert _m.upper() not in new_eth[0]["text"].upper(), _m
print(f"ETH new rows present remotely: {[r['doc_id'] for r in new_eth]}")

# full gate re-validation: ETH + WC023 (changed) + CPT (metro) + WC015 (local, control)
for code in ["ETH", "WC023", "CPT", "WC015"]:
    jname = B.PLACES[[k for k, v in B.PLACES.items() if v[0] == code][0]][1]
    table = read_html_parquet(DL / "data" / f"{code}_html.parquet")
    rep = validation_report(table, jurisdiction_id=B.ZA.normalize(code),
                            jurisdiction_name=jname, country="ZA")
    print(f"{code} remote validation: valid={rep['valid']} rows={rep['rows']}")
    assert rep["valid"], rep

# coverage report content
cr = hf_hub_download(REPO_ID, "coverage_report.md", repo_type="dataset",
                     local_dir=str(DL))
txt = open(cr).read()
assert "16143 rows" in txt, "total in coverage report"
assert "of the 8 works that were OCR-pending at the end of the PDF tranche, 8 were" in txt
assert "`ocr_tesseract300` (9 works in total" in txt
assert "| **Total** | **11 municipalities** | **576** | **471** | **98** | **7** | **16143** |" in txt
print("coverage_report.md: totals 16,143 / recovered 98 / excluded 7 / OCR-of-8 = 8 OK")
print("REMOTE VERIFY DONE — all checks pass")
