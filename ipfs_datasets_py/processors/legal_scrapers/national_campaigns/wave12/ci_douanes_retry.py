#!/usr/bin/env python3
"""Wave 12 CI douanes retry — the two décret 2019-829 origin-rules PDFs
whose wave-11 Wayback downloads truncated at exactly 1 MiB through this
egress (wave11/stats/ci_douanes.json: fetch 'ok', 1,048,576 bytes,
0 chars). ONE retry each, per the wave-12 brief: pick the largest
archived snapshot from the full (uncollapsed) CDX listing, stream it,
and if the stream still dies at exactly 1 MiB, resume with HTTP Range
requests on the replay URL (bounded). A file counts as recovered only
if the assembled bytes parse as a complete PDF (fitz opens it, page
count > 0) and extract >=300 chars carrying legal markers; then it is
saved as a ci instrument with the wave-11 douanes ID scheme.
Results -> wave12/stats/ci_douanes_retry.json.
"""
import importlib.util, json, os, re, sys, time
import requests
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ci_collect import LEGAL_MARKERS
from common12 import WAVE12

spec = importlib.util.spec_from_file_location('h12', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'faolex_cdx_harvest12.py'))
h = importlib.util.module_from_spec(spec); spec.loader.exec_module(h)

INST_BASE = os.path.expanduser('~/.ipfs_datasets/legal-corpora')
TODAY = time.strftime('%Y-%m-%d', time.gmtime())
S = requests.Session(); S.headers.update({'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) legal-data-research/1.0'})
TRUNC = 1048576

URLS = [
    'http://www.douanes.ci/sites/default/files/annexe_decret_ndeg2019-829_du_09_octobre_2019_sur_les_regles_1.pdf',
    'http://www.douanes.ci/sites/default/files/decret_num_2019-829_du_09_octobre_2019_sur_les_regles_d_origines.pdf',
]

def snapshots(url):
    api = ('https://web.archive.org/cdx/search/cdx?url=' + url +
           '&output=json&fl=timestamp,length,statuscode,digest')
    r = S.get(api, timeout=120)
    if r.status_code != 200 or not r.text.strip().startswith('['):
        return []
    return [row for row in r.json()[1:] if row[2] == '200']

def stream_get(url, headers=None, timeout=600):
    with S.get(url, timeout=timeout, stream=True, headers=headers or {}) as r:
        if r.status_code not in (200, 206):
            return None, f'http {r.status_code}', 0
        chunks = []
        for ch in r.iter_content(1 << 16):
            chunks.append(ch)
        return b''.join(chunks), 'ok', r.status_code

def fetch_with_resume(ts, orig):
    """One bounded attempt: full stream; on an exact 1 MiB cut, Range-resume."""
    url = f'https://web.archive.org/web/{ts}id_/{orig}'
    data, note, _sc = stream_get(url)
    if data is None:
        return None, f'stream failed: {note}'
    resumes = 0
    while len(data) % TRUNC == 0 and len(data) > 0 and resumes < 10:
        more, note2, sc = stream_get(url, headers={'Range': f'bytes={len(data)}-'})
        if more is None or sc != 206 or len(more) == 0:
            break
        data += more
        resumes += 1
    return data, f'stream ok ({resumes} range resumes)'

def main():
    out = []
    inst_dir = os.path.join(INST_BASE, 'ci', 'instruments')
    os.makedirs(inst_dir, exist_ok=True)
    for orig in URLS:
        rec = {'url': orig}
        snaps = snapshots(orig)
        rec['snapshots'] = [{'ts': s[0], 'length': s[1], 'digest': s[3]} for s in snaps]
        print(orig[-70:], 'snapshots:', len(snaps), flush=True)
        if not snaps:
            rec['result'] = 'no archived snapshot — left documented'
            out.append(rec); continue
        # largest compressed length first (most likely the complete capture)
        snaps.sort(key=lambda s: int(s[1] or 0), reverse=True)
        ts = snaps[0][0]
        rec['chosen_ts'] = ts
        data, note = fetch_with_resume(ts, orig)
        rec['fetch'] = note
        rec['bytes'] = 0 if data is None else len(data)
        print(' fetched:', note, rec['bytes'], flush=True)
        if data and data[:4] == b'%PDF':
            text, pages, meta = h.pdf_to_text_and_pages(data)
            text = text.strip()
            rec.update({'pages': pages, 'chars': len(text)})
            slug = re.sub(r'[^a-z0-9]+', '-', orig.split('/')[-1].lower().replace('.pdf', '')).strip('-')[:70]
            iid = f'ci-wayback-douanes-{slug}'
            rec['iid'] = iid
            if len(text) >= 300 and LEGAL_MARKERS.search(text[:6000]):
                if os.path.isfile(os.path.join(inst_dir, iid + '.json')):
                    rec['result'] = 'already an instrument locally (not overwritten)'
                else:
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
                    rec['result'] = 'RECOVERED and saved as instrument'
                    print(' SAVED', iid, len(text), flush=True)
            else:
                rec['result'] = 'fetched but text/markers insufficient — left documented'
        else:
            rec['result'] = 'download still incomplete/not a PDF — left documented'
        out.append(rec)
    json.dump(out, open(os.path.join(WAVE12, 'stats', 'ci_douanes_retry.json'), 'w'), indent=1)
    print('saved ci_douanes_retry.json')

if __name__ == '__main__':
    main()
