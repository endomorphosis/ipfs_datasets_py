"""Wave 13 Palau OCR-bank repair v2.

16 of the 43 banked 'scans' are exactly 1,048,576 bytes with zero
readable pages. Diagnosis (CDX listing for RPPL 10-29): the
earliest Wayback capture of these URLs is itself a ~1 MiB-truncated
capture (digest A), while later captures are complete (digest B,
~6.9 MB). The harvest used the earliest capture / live fetch and
banked the truncated bytes. Repair: for every zero-page banked
file, list ALL snapshots (both host variants), pick the largest
CDX length with status 200, fetch it, and replace only if the
assembled file parses with >0 pages.

Stats: wave13/stats/pw_refetch.json.
"""
import json, os, sys, urllib.parse
import requests
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common13 import WAVE13
import importlib.util
spec = importlib.util.spec_from_file_location('pw', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pw_harvest13.py'))
pw = importlib.util.module_from_spec(spec); spec.loader.exec_module(pw)
import fitz

S = requests.Session(); S.headers.update({'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) legal-data-research/1.0'})

def pages(path):
    try:
        d = fitz.open(path); n = len(d); d.close(); return n
    except Exception:
        return -1

def snapshots(url):
    api = ('https://web.archive.org/cdx/search/cdx?url=' + url +
           '&output=json&fl=timestamp,length,statuscode')
    try:
        r = S.get(api, timeout=120)
        if r.status_code == 200:
            return [row for row in r.json()[1:] if row[2] == '200']
    except Exception:
        pass
    return []

def main():
    cands = {c['fn']: c for c in json.load(open(os.path.join(WAVE13, 'stats', 'pw_candidates.json')))}
    bank = os.path.join(WAVE13, 'ocr_pdfs', 'pw')
    out = {'items': []}
    for fn in sorted(os.listdir(bank)):
        if not fn.endswith('.pdf'):
            continue
        path = os.path.join(bank, fn)
        if pages(path) > 0:
            continue
        c = cands[fn]
        variants = {c['orig']}
        p = urllib.parse.urlparse(c['orig'])
        if p.netloc == 'www.palaugov.pw':
            variants.add(p._replace(netloc='palaugov.pw').geturl())
        elif p.netloc == 'palaugov.pw':
            variants.add(p._replace(netloc='www.palaugov.pw').geturl())
        rows = []
        for v in variants:
            for ts, length, _sc in snapshots(v):
                rows.append((int(length or 0), ts, v))
        item = {'fn': fn, 'old_size': os.path.getsize(path), 'snapshots_found': len(rows)}
        if not rows:
            item['outcome'] = 'no_snapshots'
            out['items'].append(item); print(item, flush=True); continue
        rows.sort(reverse=True)
        length, ts, v = rows[0]
        item['chosen_ts'] = ts; item['chosen_length'] = length
        tmp = path + '.wayback'
        n = pw.stream_download(f"https://web.archive.org/web/{ts}id_/{v}", tmp, timeout=600)
        item['fetched'] = n
        if n and pw.is_pdf(tmp) and pages(tmp) > 0:
            item['new_pages'] = pages(tmp)
            os.replace(tmp, path)
            item['outcome'] = 'replaced_with_complete_capture'
        else:
            item['outcome'] = 'largest_capture_unusable'
            try: os.unlink(tmp)
            except Exception: pass
        out['items'].append(item)
        print(item, flush=True)
    json.dump(out, open(os.path.join(WAVE13, 'stats', 'pw_refetch.json'), 'w'), indent=1)
    ok = sum(1 for i in out['items'] if i['outcome'] == 'replaced_with_complete_capture')
    print('repaired', ok, '/', len(out['items']))

if __name__ == '__main__':
    main()
