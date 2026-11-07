#!/usr/bin/env python3
"""UA_LOCAL bulk zip (CoS 17:55 PT Oct 22): stream to disk, no 300MB cap (this source only), memguard, zip -T, extract legal-text files only. Stage only."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os, sys, time, json, subprocess, zipfile, requests
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from strict_mem_guard import memavail
B = str(_CORPORA) + '/ua_local'; URL = json.load(open(f'{B}/jobs.json'))['jobs'][0]['urls'][0]
Z = f'{B}/zip/25-edrnpa.zip'; UA = 'justicedao-legal-corpus/1.0 (+https://huggingface.co/justicedao; polite municipal-law archiver)'
STOPS = [f'{B}/STOP_UA_LOCAL', '/workspace/logs/STOP_UA_LOCAL', f'{B}/HOLD_UA', '/workspace/logs/HOLD_UA']
KEEP = ('.xml', '.json', '.csv', '.txt', '.html', '.htm', '.rtf', '.doc', '.docx', '.pdf', '.odt')
def log(*a): print(time.strftime('%F %T'), *a, flush=True)
def guard():
    for s in STOPS:
        if os.path.exists(s): log('STOP', s); sys.exit(2)
    m = memavail()
    if m < 1000: log('MEMTERM instant', m); sys.exit(3)
    if m < 3584:
        log('PAUSE mem', m); t0 = time.time(); ok = None; low = None
        while True:
            m = memavail()
            if m < 1500: low = low or time.time()
            else: low = None
            if low and time.time() - low >= 10: log('MEMTERM', m); sys.exit(3)
            if m >= 4200: ok = ok or time.time()
            else: ok = None
            if ok and time.time() - ok >= 30: log('RESUME', m); return
            if time.time() - t0 > 900: log('MEMTERM pause>900s'); sys.exit(3)
            time.sleep(2)
def main():
    if not (os.path.exists(Z) and zipfile.is_zipfile(Z)):
        guard(); time.sleep(10)  # Crawl-delay 10
        r = requests.get(URL, headers={'User-Agent': UA}, stream=True, timeout=(15, 120), verify=True)
        log('GET', r.status_code, r.headers.get('Content-Length'))
        if r.status_code in (403, 429, 503):
            for h in json.load(open(f'{B}/jobs.json'))['jobs'][0]['hold_on_403']: open(h, 'a').write(time.strftime('%F %T ') + f'HTTP {r.status_code} on zip\n')
            log('HOLD_UA written'); sys.exit(4)
        r.raise_for_status(); n = 0; last = time.time()
        with open(Z + '.part', 'wb') as f:
            for c in r.iter_content(1 << 20):
                f.write(c); n += len(c)
                if time.time() - last > 5: guard(); last = time.time()
        os.replace(Z + '.part', Z); log('downloaded bytes', n)
    t = subprocess.run(['unzip', '-tq', Z], capture_output=True, text=True); log('zip -T', t.returncode, t.stdout.strip()[-300:], t.stderr.strip()[-300:])
    if t.returncode != 0: log('CRC FAIL'); sys.exit(5)
    zf = zipfile.ZipFile(Z); kept = skipped = 0; man = []
    for i in zf.infolist():
        if i.is_dir(): continue
        if i.filename.lower().endswith(KEEP): zf.extract(i, f'{B}/extracted'); kept += 1; man.append(dict(f=i.filename, size=i.file_size, crc=i.CRC, kept=True))
        else: skipped += 1; man.append(dict(f=i.filename, size=i.file_size, kept=False))
        if (kept + skipped) % 500 == 0: guard()
    json.dump(man, open(f'{B}/extract_manifest.json', 'w'), ensure_ascii=False, indent=0)
    open(f'{B}/UA_LOCAL_DONE', 'w').write(time.strftime('%F %T ') + json.dumps(dict(kept=kept, skipped=skipped, zip_bytes=os.path.getsize(Z))) + '\n'); log('DONE kept', kept, 'skipped', skipped)


if __name__ == '__main__':
    main()
