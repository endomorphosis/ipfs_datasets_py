# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import gzip, json, glob, re, hashlib, collections, os, sys
import pyarrow as pa, pyarrow.parquet as pq
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from strict_mem_guard import memavail
OUT = '/workspace/packaging/out/lu_rc2_review_20261023'; os.makedirs(f'{OUT}/data', exist_ok=True)
def nt(t): return hashlib.sha256(' '.join((t or '').lower().split()).encode()).hexdigest()
refL = pq.read_table('/workspace/packaging/ref/ipfs_luxembourg_laws/data/laws.parquet', columns=['eli', 'identifier', 'source_url', 'text']).to_pylist()
refM = pq.read_table('/workspace/packaging/ref/ipfs_luxembourg_municipal_laws/data/laws.parquet', columns=['eli', 'source_url', 'text']).to_pylist()
def ek(u): return re.sub(r'^https?://(data\.)?legilux\.public\.lu', '', u or '').rstrip('/')
refE = {ek(r['eli']) for r in refL + refM if r['eli'] and r['eli'] != 'None'} | {('/eli/' + r['identifier']) for r in refL if r['identifier']}
refU = {ek(r['source_url']) for r in refL + refM if r['source_url']}
refT = {nt(r['text']) for r in refL + refM if r['text'] and len(r['text']) > 200}; del refL, refM
S = pa.schema([('id', pa.string()), ('eli', pa.string()), ('date_document', pa.string()), ('format', pa.string()), ('formats_available', pa.string()), ('file_url', pa.string()),
               ('sha256', pa.string()), ('bytes', pa.int64()), ('text', pa.large_string()), ('text_chars', pa.int64()), ('memorial_issue_sha256', pa.string()), ('needs_split', pa.bool_()),
               ('status', pa.string()), ('retrieved_at', pa.string()), ('robots_disallowed', pa.bool_()), ('route', pa.string()), ('licence', pa.string())])
SM = pa.schema([('memorial_issue_sha256', pa.string()), ('file_url', pa.string()), ('bytes', pa.int64()), ('text', pa.large_string()), ('text_chars', pa.int64()), ('n_works', pa.int64())])
W = pq.ParquetWriter(f'{OUT}/data/rc_works.parquet', S, compression='zstd'); WM = pq.ParquetWriter(f'{OUT}/data/memorial_issues.parquet', SM, compression='zstd')
c = collections.Counter(); seen = set(); memo = {}; memn = collections.Counter(); buf = []
for f in sorted(glob.glob(str(_CORPORA) + '/lu_legilux/rc2/chunks/*.jsonl.gz')):
    while memavail() < 3584: import time; time.sleep(5)
    for l in gzip.open(f):
        r = json.loads(l); c['raw'] += 1
        if not r.get('s', '').startswith('ok'): c['drop_fetch_fail'] += 1; continue
        c['normalized'] += 1; e = ek(r['work'])
        if e in seen: c['dup_within'] += 1; continue
        seen.add(e)
        mem = bool(r.get('whole_memorial_issue')); txt = None if mem else re.sub(r'[ \t]+', ' ', re.sub(r'\s*\n\s*', '\n', r.get('text') or '')).strip()
        if e in refE or (not mem and ek(r['file_url']) in refU): c['dup_vs_benjamin_eli_url'] += 1; continue
        if txt and nt(txt) in refT: c['dup_vs_benjamin_text'] += 1; continue
        if mem:
            sh = r['sha256']; memn[sh] += 1
            if sh not in memo and r.get('text'): memo[sh] = 1; WM.write_table(pa.Table.from_pylist([dict(memorial_issue_sha256=sh, file_url=r['file_url'], bytes=r['bytes'], text=r['text'], text_chars=r['text_chars'], n_works=0)], SM))
        m = re.search(r'/rc/(\d{4})/(\d{2})/(\d{2})/', e)
        buf.append(dict(id='lu-rc-' + e.split('/rc/')[1].replace('/', '-'), eli='http://data.legilux.public.lu' + e, date_document='-'.join(m.groups()) if m else None, format=r['picked'],
                        formats_available=','.join(sorted(r['formats'])), file_url=r['file_url'], sha256=r.get('sha256'), bytes=r.get('bytes'), text=txt, text_chars=len(txt) if txt else None,
                        memorial_issue_sha256=r['sha256'] if mem else None, needs_split=mem, status=r['s'], retrieved_at=r['provenance']['retrieved_at'], robots_disallowed=True,
                        route='LEGILUX_SPARQL_FILESTORE', licence=r['provenance']['licence']))
        c['final'] += 1; c['fmt_' + r['picked']] += 1; c['needs_split'] += mem
        if len(buf) >= 500: W.write_table(pa.Table.from_pylist(buf, S)); buf = []
if buf: W.write_table(pa.Table.from_pylist(buf, S))
W.close(); WM.close(); c['memorial_issues'] = len(memo)
json.dump(dict(c), open(f'{OUT}/summary.json', 'w'), indent=1); print(dict(c))
