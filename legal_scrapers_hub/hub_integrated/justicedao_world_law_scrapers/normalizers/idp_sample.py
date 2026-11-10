#!/usr/bin/env python3
"""ID BPK probe sample: stratified random regional regulations -> detail page + first PDF. Sequential, via idp_get.py (>=2s spacing, 3x403/429/503 stop).
MemAvail <=3700MB -> 'MEMGUARD TERM'. Output: id_bpk/index/sample.jsonl, id_bpk/pdf/<detail_id>.pdf"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, random, re, subprocess, html, os, sys, time, urllib.parse
B = '{_CORPORA}/id_bpk'
L = json.load(open(f'{B}/index/sitemap_details_classified.json'))
def mem():
    return int(open('/proc/meminfo').read().split('MemAvailable:')[1].split()[0]) // 1024
STRATA = {('kab', 'perbup'): 18, ('kab', 'perda'): 12, ('kota', 'perwali'): 8, ('prov', 'pergub'): 8, ('kota', 'perda'): 5, ('prov', 'perda'): 5, ('kab', 'qanun'): 2, ('kota', 'qanun'): 1, ('prov', 'qanun'): 1}
random.seed(20261004); pick = []
for (k, t), n in STRATA.items():
    pool = [d for d in L if d.get('lvl') == k and d.get('type') == t]
    regs = {}
    for d in pool: regs.setdefault(d['region'], []).append(d)
    for r in random.sample(sorted(regs), min(n, len(regs))): pick.append(random.choice(regs[r]))
done = set()
if os.path.exists(f'{B}/index/sample.jsonl'): done = {json.loads(l)['id'] for l in open(f'{B}/index/sample.jsonl')}
out = open(f'{B}/index/sample.jsonl', 'a')
def get(url, d, name):
    if mem() <= 3700: print('MEMGUARD TERM', mem(), flush=True); sys.exit(3)
    r = subprocess.run(['python3', '/workspace/scripts/idp_get.py', '--dir', d, '--name', name, url], capture_output=True, text=True)
    print(r.stdout.strip(), r.stderr.strip()[-300:], flush=True)
    if r.returncode == 9: sys.exit(9)
    return r.stdout.split()[0] if r.stdout else None
FIELDS = ['Tipe Dokumen', 'Judul', 'T.E.U.', 'Nomor', 'Bentuk', 'Bentuk Singkat', 'Tahun', 'Tempat Penetapan', 'Tanggal Penetapan', 'Tanggal Pengundangan', 'Tanggal Berlaku', 'Sumber', 'Subjek', 'Status', 'Bahasa', 'Lokasi', 'Bidang']
for d in pick:
    if d['id'] in done: continue
    st = get(d['url'], f'{B}/probe', f"detail_{d['id']}.html")
    rec = dict(id=d['id'], slug=d['slug'], lvl=d['lvl'], type=d['type'], region=d['region'], detail_http=st)
    if st == '200':
        s = open(f"{B}/probe/detail_{d['id']}.html", encoding='utf-8', errors='replace').read()
        t = re.sub(r'<script.*?</script>|<style.*?</style>', '', s, flags=re.S); t = html.unescape(re.sub(r'<[^>]+>', '\n', t)); lines = [x.strip() for x in t.split('\n') if x.strip()]
        meta = {}
        if 'METADATA' in lines:
            i0 = lines.index('METADATA')
            for k in FIELDS:
                if k in lines[i0:i0 + 80]: j = lines.index(k, i0); meta[k] = lines[j + 1]
        rec['meta'] = meta
        dl = [x for x in dict.fromkeys(re.findall(r'href="(/Download/[^"]+)"', s))]
        rec['downloads'] = dl
        if dl:
            u = 'https://peraturan.bpk.go.id' + dl[0]
            rec['pdf_http'] = get(u, f'{B}/pdf', f"{d['id']}.pdf"); rec['pdf_url'] = u
            p = f"{B}/pdf/{d['id']}.pdf"
            if os.path.exists(p): rec['pdf_bytes'] = os.path.getsize(p)
    out.write(json.dumps(rec, ensure_ascii=False) + '\n'); out.flush()
print('DONE', len(pick))
