# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import json,os,glob,hashlib,datetime,collections
import pyarrow.parquet as pq
R=(str(_CORPORA) + '/county/GB')
def sha(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(1<<20),b''): h.update(b)
    return h.hexdigest()
def rows(n): return pq.read_table(f'{R}/data/{n}').num_rows
L=pq.read_table(f'{R}/data/laws-00001.parquet').to_pylist()
M1=pq.read_table(f'{R}/data/metadata_only_acts-00001.parquet').to_pylist(); M2=pq.read_table(f'{R}/data/metadata_only_acts-00002.parquet').to_pylist()
files=[dict(path=os.path.relpath(p,R),rows=rows(os.path.basename(p)),bytes=os.path.getsize(p),sha256=sha(p)) for p in sorted(glob.glob(f'{R}/data/*.parquet'))]
by=collections.Counter(r['municipality_name'] for r in L)
man=dict(pack="county/GB (county councils: byelaws + legislation.gov.uk local Acts) - PARTIAL",built=datetime.datetime.now().astimezone().isoformat(timespec='seconds'),upload=False,
 counts=dict(laws_with_text=len(L),articles=rows('articles-00001.parquet'),metadata_only_acts=len(M1)+len(M2),local_acts_text=sum(1 for r in L if r['source_type']=='legislation_gov_uk_local_act'),byelaw_sets=sum(1 for r in L if r['source_type']!='legislation_gov_uk_local_act'),by_council=dict(by)),
 files=files,
 sources=["https://www.legislation.gov.uk (ukla data.xml; /search/data.feed title queries; Crawl-delay 5 s honoured; data.pdf/docx never fetched)","westsussex.gov.uk, countryparks.buckinghamshire.gov.uk, leicscountryparks.org.uk, devon.gov.uk, eastsussex.gov.uk, surreycc open-spaces (byelaw pages/PDFs; robots snapshots in _state/)"],
 terms=dict(legislation_gov_uk="OGL v3.0, Crown/King's Printer copyright; no AI content-signal in robots.txt",devon_gov_uk="robots Content-Signal ai-train=no (RESTRICTED for training; restricted_ai_training=true on that row)",
            buckinghamshire="page footer links OGL v3.0",other_councils="no licence/terms statement found; treat as council copyright, clearance needed before redistribution"),
 ocr=dict(performed=False,reason="tesseract absent after box restore (apt repos unsigned/unavailable, not bypassed); legislation.gov.uk holds image-only PDFs for pre-~1992 local Acts"),
 notes=["metadata_only_acts-00001/00002: 170 local Acts naming county councils/counties whose XML has no body text (image-only PDFs); rows carry title/date/source_url/eli only, text empty, NOT OCR-ed.",
        "laws-00002.parquet/articles-00002.parquet are EMPTY (0 rows) - created by build_gb_pack_b2.py when the 45 remaining Acts all proved to be image-only; add-only rule prevents deletion. Use shard 00003+ for the next batch.",
        "raw/ukla/ also contains 3 stray pip wheels (pytesseract, pillow, packaging) dropped by mistake; not data.",
        "Byelaw coverage is 6 sources for 6 councils (country parks / canal / open spaces) - far from all non-metropolitan counties."])
json.dump(man,open(f'{R}/MANIFEST.json','w'),indent=1,ensure_ascii=False)
print(json.dumps(man['counts']))
