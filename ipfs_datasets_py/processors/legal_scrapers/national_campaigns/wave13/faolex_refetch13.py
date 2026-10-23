"""Wave 13 repair of 1 MiB-truncated banked FAOLEX PDFs.

Wave-12's walk downloads truncated at exactly 1,048,576 bytes for
some files through this egress; the truncated bytes were banked as
'short_text' and OCR to 0 pages. For each target: list Wayback
snapshots of the FAOLEX URL, try up to 3 (largest CDX length
first), stream to disk, and replace the banked file only if the
assembled copy parses with >0 pages.

Usage: faolex_refetch13.py <bank_dir> <file.pdf> [...]
Stats: wave13/stats/faolex_refetch.json (append-merge by file).
"""
import json, os, sys
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

def main():
    bank_dir = sys.argv[1]
    files = sys.argv[2:]
    stats_path = os.path.join(WAVE13, 'stats', 'faolex_refetch.json')
    out = json.load(open(stats_path)) if os.path.isfile(stats_path) else {'items': {}}
    for fn in files:
        path = os.path.join(bank_dir, fn)
        item = {'old_size': os.path.getsize(path) if os.path.isfile(path) else None,
                'old_pages': pages(path)}
        if item['old_pages'] > 0:
            item['outcome'] = 'already_fine'
            out['items'][fn] = item; print(fn, item, flush=True); continue
        url = f'https://faolex.fao.org/docs/pdf/{fn}'
        api = ('https://web.archive.org/cdx/search/cdx?url=' + url +
               '&output=json&fl=timestamp,length,statuscode')
        rows = []
        try:
            r = S.get(api, timeout=120)
            if r.status_code == 200:
                rows = [(int(x[1] or 0), x[0]) for x in r.json()[1:] if x[2] == '200']
        except Exception:
            pass
        rows.sort(reverse=True)
        item['snapshots'] = len(rows)
        item['outcome'] = 'no_usable_capture'
        for length, ts in rows[:3]:
            tmp = path + '.wayback'
            n = pw.stream_download(f'https://web.archive.org/web/{ts}id_/{url}', tmp, timeout=600)
            if n and pw.is_pdf(tmp) and pages(tmp) > 0:
                item.update({'outcome': 'replaced_with_complete_capture', 'ts': ts,
                             'new_size': n, 'new_pages': pages(tmp)})
                os.replace(tmp, path)
                break
            try: os.unlink(tmp)
            except Exception: pass
        out['items'][fn] = item
        json.dump(out, open(stats_path, 'w'), indent=1)
        print(fn, item, flush=True)
    print('done')

if __name__ == '__main__':
    main()
