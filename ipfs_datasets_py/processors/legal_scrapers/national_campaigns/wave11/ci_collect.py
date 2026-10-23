#!/usr/bin/env python3
"""Wave 11 Côte d'Ivoire collector — non-FAOLEX route.

Enumerates archived PDFs on official CI hosts via the Wayback CDX API
(matchType=domain, collapse=urlkey), downloads the archived snapshot,
digital-extracts (fitz -> pdfplumber -> pdftotext; NO OCR), and keeps
documents whose text (>=300 chars) carries legal-instrument markers.
Kept docs become instruments in ~/.ipfs_datasets/legal-corpora/ci/
instruments/ with source_type 'wayback-official-ci', ready for the
standard stage_wave11 merge (dedupe by ID + normalized-title guard
against the live repo).

Usage: ci_collect.py <host> [<host> ...] [--max-seconds N]
Stats -> wave11/stats/ci_collect_stats.json; OCR-deferred inventory
(scanned, <300 chars) -> wave11/stats/ci_ocr_inventory.json.
"""
import argparse, importlib.util, json, os, re, sys, time, urllib.parse
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common11 import WAVE11, norm

spec = importlib.util.spec_from_file_location('h11', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'faolex_cdx_harvest11.py'))
h = importlib.util.module_from_spec(spec); spec.loader.exec_module(h)

INST_BASE = os.path.expanduser('~/.ipfs_datasets/legal-corpora')
TODAY = time.strftime('%Y-%m-%d', time.gmtime())
UA = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) legal-data-research/1.0'}
S = requests.Session(); S.headers.update(UA)
LEGAL_MARKERS = re.compile(r"(loi\s+n|décret|decret|arrêté|arrete|ordonnance|constitution|"
                           r"journal officiel|code\s+(électoral|electoral|civil|pénal|penal|"
                           r"de\s|des\s|du\s)|république de côte d'ivoire|republique de cote d'ivoire|"
                           r"assemblée nationale|assemblee nationale)", re.I)

def enumerate_pdfs(host):
    url = ('https://web.archive.org/cdx/search/cdx?url=' + host +
           '&matchType=domain&output=json&limit=8000&collapse=urlkey'
           '&fl=original,timestamp&filter=original:.*\\.pdf')
    r = S.get(url, timeout=120)
    rows = r.json()[1:] if r.status_code == 200 and r.text.strip().startswith('[') else []
    out = {}
    for orig, ts in rows:
        out[orig] = ts  # collapse=urlkey: one (latest-listed) snapshot per URL
    return out

def slugify(url):
    path = urllib.parse.urlparse(url).path
    fn = urllib.parse.unquote(path.split('/')[-1])
    fn = re.sub(r'\.pdf$', '', fn, flags=re.I)
    fn = fn.lower()
    fn = re.sub(r'[^a-z0-9]+', '-', fn).strip('-')[:80]
    return fn or 'doc'

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('hosts', nargs='+')
    ap.add_argument('--max-seconds', type=int, default=2400)
    args = ap.parse_args()
    t0 = time.time()
    inst_dir = os.path.join(INST_BASE, 'ci', 'instruments')
    os.makedirs(inst_dir, exist_ok=True)
    local_ids = {f[:-5] for f in os.listdir(inst_dir) if f.endswith('.json')}
    seen_slugs = {}  # iid -> orig url, for slug-collision disambiguation
    for f in os.listdir(inst_dir):
        if f.endswith('.json'):
            try:
                r0 = json.load(open(os.path.join(inst_dir, f)))
                seen_slugs[r0['id']] = r0.get('source_url', '')
            except Exception:
                pass
    stats = {'hosts': {}, 'kept': 0, 'dropped_no_marker': 0, 'short_text': 0,
             'fetch_fail': 0, 'dup_local': 0}
    ocr_inv = []
    for host in args.hosts:
        label = host.replace('.gouv.ci', '').replace('.', '-')
        files = enumerate_pdfs(host)
        stats['hosts'][host] = {'enumerated': len(files), 'kept': 0}
        print(host, 'enumerated', len(files), flush=True)
        for orig, ts in sorted(files.items()):
            if time.time() - t0 > args.max_seconds:
                stats['stopped_early'] = True
                break
            iid = f"ci-wayback-{label}-{slugify(orig)}"
            if iid in seen_slugs and seen_slugs[iid] != orig:
                k = 2
                while f"{iid}-{k}" in seen_slugs and seen_slugs[f"{iid}-{k}"] != orig:
                    k += 1
                iid = f"{iid}-{k}"
            if iid in local_ids:
                stats['dup_local'] += 1
                continue
            seen_slugs[iid] = orig
            data = h.get_binary(f"https://web.archive.org/web/{ts}id_/{orig}", timeout=150)
            if not (data and data[:4] == b'%PDF'):
                stats['fetch_fail'] += 1
                continue
            text, pages, meta = h.pdf_to_text_and_pages(data)
            text = text.strip()
            if len(text) < 300:
                stats['short_text'] += 1
                ocr_inv.append({'id': iid, 'url': orig, 'pages': pages,
                                'extracted_chars': len(text)})
                continue
            if not LEGAL_MARKERS.search(text[:6000]):
                stats['dropped_no_marker'] += 1
                continue
            title = h.derive_title(text, meta)
            ym = re.search(r'\b(19|20)\d{2}\b', text[:1500])
            rec = {'id': iid, 'title': title, 'text': text,
                   'source_url': orig, 'source_type': 'wayback-official-ci',
                   'jurisdiction': "Côte d'Ivoire", 'country': 'ci',
                   'language': 'fr', 'eli': None,
                   'date': ym.group(0) if ym else None,
                   'retrieved_at': TODAY + 'T00:00:00Z',
                   'license': 'public-domain', 'law_status': 'unknown',
                   'identifier': iid, 'official_identifier': '',
                   'article_count': h.count_articles(text)}
            with open(os.path.join(inst_dir, iid + '.json'), 'w') as f:
                json.dump(rec, f, ensure_ascii=False)
            local_ids.add(iid)
            stats['kept'] += 1
            stats['hosts'][host]['kept'] += 1
            print('kept', iid, len(text), flush=True)
    json.dump(stats, open(os.path.join(WAVE11, 'stats', 'ci_collect_stats.json'), 'w'), indent=1)
    json.dump(ocr_inv, open(os.path.join(WAVE11, 'stats', 'ci_ocr_inventory.json'), 'w'), indent=1)
    print(json.dumps(stats))

if __name__ == '__main__':
    main()
