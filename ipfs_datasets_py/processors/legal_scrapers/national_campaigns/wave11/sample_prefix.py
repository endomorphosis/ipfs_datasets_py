#!/usr/bin/env python3
"""Wave 11 prefix content verification (MANDATORY before any harvest):
enumerate the FAOLEX prefix via Wayback CDX, fetch the first N files
(archive-first, live fallback), digital-extract, and print title +
text head + script shares so a human/agent can confirm the prefix
really belongs to the target country and see the document language.

Usage: sample_prefix.py <cc> [n=4]
Reads prefix from common11 PREFIX (targets.json). Does NOT write
instruments; prints a JSON summary to stdout and saves it to
wave11/stats/sample_{cc}.json.
"""
import importlib.util, json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common11 import WAVE11, PREFIX, TARGETS

spec = importlib.util.spec_from_file_location('h11', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'faolex_cdx_harvest11.py'))
h = importlib.util.module_from_spec(spec); spec.loader.exec_module(h)

def script_shares(text):
    s = text[:8000]
    n = max(len(s), 1)
    def cnt(rng): return len(re.findall(rng, s))
    return {'latin': round(cnt(r'[A-Za-z]') / n, 3),
            'cyrillic': round(cnt(r'[\u0400-\u04FF]') / n, 3),
            'georgian': round(cnt(r'[\u10A0-\u10FF]') / n, 3),
            'arabic': round(cnt(r'[\u0600-\u06FF]') / n, 3),
            'khmer': round(cnt(r'[\u1780-\u17FF]') / n, 3)}

def main():
    cc = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    prefix = PREFIX[cc]
    files = h.cdx_files(prefix, cc)
    print(f'{cc} prefix={prefix} enumerated_unique_files={len(files)}', flush=True)
    out = {'cc': cc, 'prefix': prefix, 'repo': TARGETS[cc][0], 'enumerated': len(files), 'samples': []}
    for fn, (orig, ts) in list(sorted(files.items()))[:n]:
        data = h.get_binary(f"https://web.archive.org/web/{ts}id_/{orig}", timeout=150)
        via = 'archive'
        if not (data and data[:4] == b'%PDF'):
            data = None
            for cand in (f"https://extwprlegs1.fao.org/docs/pdf/{fn}", f"https://faolex.fao.org/docs/pdf/{fn}"):
                data = h.get_binary(cand, timeout=30)
                if data and data[:4] == b'%PDF':
                    via = 'live'; break
                data = None
        if data is None:
            out['samples'].append({'file': fn, 'fetch': 'FAILED'})
            print(fn, 'FETCH FAILED', flush=True)
            continue
        text, pages, meta = h.pdf_to_text_and_pages(data)
        text = text.strip()
        rec = {'file': fn, 'via': via, 'pages': pages, 'chars': len(text),
               'title': h.derive_title(text, meta) if text else '',
               'head': re.sub(r'\s+', ' ', text[:700]),
               'scripts': script_shares(text)}
        out['samples'].append(rec)
        print(json.dumps(rec, ensure_ascii=False), flush=True)
    json.dump(out, open(os.path.join(WAVE11, 'stats', f'sample_{cc}.json'), 'w'), indent=1, ensure_ascii=False)
    print('saved sample_' + cc + '.json')

if __name__ == '__main__':
    main()
