#!/usr/bin/env python3
"""Wave 11 CI targeted retry: the Code des Douanes files on douanes.ci
(Code_des_Douanes_Partie_Legis / _Reglementaire) whose sampler fetches
failed (trailing-%20 URLs, likely very large snapshots). Streams the
Wayback snapshot to disk with a long timeout, digital-extracts, and
saves the customs-code parts as ci instruments if they carry legal
text. Also tries the decret 2019-829 origin-rules PDFs.
Stats -> wave11/stats/ci_douanes.json.
"""
import importlib.util, json, os, re, sys, time
import requests
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ci_collect import enumerate_pdfs, LEGAL_MARKERS
from common11 import WAVE11

spec = importlib.util.spec_from_file_location('h11', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'faolex_cdx_harvest11.py'))
h = importlib.util.module_from_spec(spec); spec.loader.exec_module(h)

INST_BASE = os.path.expanduser('~/.ipfs_datasets/legal-corpora')
TODAY = time.strftime('%Y-%m-%d', time.gmtime())
S = requests.Session(); S.headers.update({'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) legal-data-research/1.0'})

def fetch_big(url, timeout=900):
    try:
        with S.get(url, timeout=timeout, stream=True) as r:
            if r.status_code != 200:
                return None, f'http {r.status_code}'
            chunks = []
            for ch in r.iter_content(1 << 20):
                chunks.append(ch)
            data = b''.join(chunks)
            return (data, 'ok') if data[:4] == b'%PDF' else (None, f'not pdf ({len(data)}B)')
    except Exception as e:
        return None, f'{type(e).__name__}: {e}'[:140]

def main():
    files = enumerate_pdfs('douanes.ci')
    want = {o: t for o, t in files.items()
            if 'code_de_douanes' in o.lower() or 'decret' in o.lower()}
    print('douanes filtered:', len(want), flush=True)
    out = []
    inst_dir = os.path.join(INST_BASE, 'ci', 'instruments')
    os.makedirs(inst_dir, exist_ok=True)
    for orig, ts in sorted(want.items()):
        data, note = fetch_big(f"https://web.archive.org/web/{ts}id_/{orig}")
        rec = {'url': orig, 'fetch': note, 'bytes': 0 if data is None else len(data)}
        print(orig[-60:], note, rec['bytes'], flush=True)
        if data:
            text, pages, meta = h.pdf_to_text_and_pages(data)
            text = text.strip()
            rec.update({'pages': pages, 'chars': len(text)})
            slug = re.sub(r'[^a-z0-9]+', '-', orig.split('/')[-1].lower().replace('.pdf', '')).strip('-')[:70]
            iid = f"ci-wayback-douanes-{slug}"
            if len(text) >= 300 and LEGAL_MARKERS.search(text[:6000]):
                title = h.derive_title(text, meta)
                ym = re.search(r'\b(19|20)\d{2}\b', text[:1500])
                r2 = {'id': iid, 'title': title, 'text': text, 'source_url': orig,
                      'source_type': 'wayback-official-ci', 'jurisdiction': "Côte d'Ivoire",
                      'country': 'ci', 'language': 'fr', 'eli': None,
                      'date': ym.group(0) if ym else None,
                      'retrieved_at': TODAY + 'T00:00:00Z', 'license': 'public-domain',
                      'law_status': 'unknown', 'identifier': iid, 'official_identifier': '',
                      'article_count': h.count_articles(text)}
                json.dump(r2, open(os.path.join(inst_dir, iid + '.json'), 'w'), ensure_ascii=False)
                rec['saved'] = iid
                print(' SAVED', iid, len(text), flush=True)
        out.append(rec)
    json.dump(out, open(os.path.join(WAVE11, 'stats', 'ci_douanes.json'), 'w'), indent=1)
    print('saved ci_douanes.json')

if __name__ == '__main__':
    main()
