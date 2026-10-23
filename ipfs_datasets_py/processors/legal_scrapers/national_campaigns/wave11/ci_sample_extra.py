#!/usr/bin/env python3
"""Wave 11 CI extra-host sampling: douanes.ci + dgi.gouv.ci (+ presidence.ci
/downloads only). Enumerate via CDX, fetch a handful of PDFs (filename-
heuristic picks first: code/loi/decret/tarif in the name, then the first
few others), digital-extract, print title + head for a content-class call.
Read-only; writes nothing but wave11/stats/ci_sample_extra.json.
"""
import importlib.util, json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ci_collect import enumerate_pdfs

spec = importlib.util.spec_from_file_location('h11', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'faolex_cdx_harvest11.py'))
h = importlib.util.module_from_spec(spec); spec.loader.exec_module(h)
from common11 import WAVE11

def pick(files, k=5):
    items = sorted(files.items())
    pri = [(o, t) for o, t in items if re.search(r'(code|loi|decret|décret|tarif|arrete|arrêté|convention)', o, re.I)]
    rest = [(o, t) for o, t in items if (o, t) not in pri]
    return (pri + rest)[:k]

def main():
    out = {}
    targets = [('douanes.ci', None), ('dgi.gouv.ci', None),
               ('presidence.ci', '/downloads/')]
    for host, must in targets:
        files = enumerate_pdfs(host)
        if must:
            files = {o: t for o, t in files.items() if must in o}
        print(host, 'filtered_enumerated', len(files), flush=True)
        recs = []
        for orig, ts in pick(files):
            data = h.get_binary(f"https://web.archive.org/web/{ts}id_/{orig}", timeout=150)
            if not (data and data[:4] == b'%PDF'):
                recs.append({'url': orig, 'fetch': 'FAILED'})
                print(' FAILED', orig[:100], flush=True)
                continue
            text, pages, meta = h.pdf_to_text_and_pages(data)
            text = text.strip()
            rec = {'url': orig, 'pages': pages, 'chars': len(text),
                   'title': h.derive_title(text, meta) if text else '',
                   'head': re.sub(r'\s+', ' ', text[:500])}
            recs.append(rec)
            print(json.dumps(rec, ensure_ascii=False)[:600], flush=True)
        out[host] = {'enumerated': len(files), 'samples': recs}
    json.dump(out, open(os.path.join(WAVE11, 'stats', 'ci_sample_extra.json'), 'w'), indent=1, ensure_ascii=False)
    print('saved ci_sample_extra.json')

if __name__ == '__main__':
    main()
