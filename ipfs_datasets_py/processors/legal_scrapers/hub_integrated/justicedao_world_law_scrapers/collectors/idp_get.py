#!/usr/bin/env python3
"""Polite single-request probe helper for peraturan.bpk.go.id only. >= DELAY s between requests (shared ts file, default 2.0; raised to Crawl-delay if set).
Honest UA; no redirects off-host; saves body+headers under id_bpk/probe (or given dir). Stops (exit 9) after 3 consecutive 403/429/503 (counter file).
Usage: idp_get.py [--dir D] [--name N] URL"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import sys, os, time, json, re, requests
HOST = 'peraturan.bpk.go.id'; B = '{_CORPORA}/id_bpk'
UA = 'legal-corpora-id-probe/1.0 (research corpus of official Indonesian regulations; polite, low-rate probe; contact via huggingface.co/endomorphosis)'
TS = f'{B}/probe/.last_req'; BAD = f'{B}/probe/.consec_bad'; DELAY = float(os.environ.get('IDP_DELAY', '2.0'))
args = sys.argv[1:]; d = f'{B}/probe'; name = None
while args and args[0].startswith('--'):
    k = args.pop(0)
    if k == '--dir': d = args.pop(0)
    elif k == '--name': name = args.pop(0)
url = args[0]
assert re.match(rf'https?://{re.escape(HOST)}(/|$)', url), 'off-host refused'
try: last = float(open(TS).read())
except Exception: last = 0
w = DELAY - (time.time() - last)
if w > 0: time.sleep(w)
open(TS, 'w').write(str(time.time()))
try: r = requests.get(url, headers={'User-Agent': UA}, timeout=(20, 120), allow_redirects=False)
except Exception as e: print('ERR', url, repr(e)[:200]); sys.exit(2)
try: bad = int(open(BAD).read())
except Exception: bad = 0
bad = bad + 1 if r.status_code in (403, 429, 503) else 0; open(BAD, 'w').write(str(bad))
name = name or (re.sub(r'[^A-Za-z0-9._-]+', '_', url.split(HOST, 1)[1].lstrip('/'))[:150] or 'root')
open(f'{d}/{name}', 'wb').write(r.content)
open(f'{d}/{name}.headers', 'w').write(f'GET {url}\nHTTP {r.status_code}\n' + json.dumps(dict(r.headers), indent=1))
print(r.status_code, url, 'len', len(r.content), 'ctype', r.headers.get('content-type'), 'loc', r.headers.get('location'), '->', f'{d}/{name}', flush=True)
if bad >= 3: print('STOP: 3 consecutive 403/429/503'); sys.exit(9)
