"""Wave 13 Palau OCR — the scanned candidates banked by pw_harvest13
(wave13/ocr_pdfs/pw/). Page-checkpointed (ocr13_engine), eng.
A file is saved as an instrument only if every page was attempted,
the text clears the engine quality bar, AND the corrected Palau
verification (pw_reverify13.verified) passes on the OCR text.
Records use the repo's palaugov_pw convention.
Stats: wave13/stats/pw_ocr.json.
Usage: pw_ocr13.py [max_files]
"""
import json, os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common13 import WAVE13, norm
from ocr13_engine import ocr_pdf_pages, quality
import importlib.util
spec = importlib.util.spec_from_file_location('pw', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pw_harvest13.py'))
pw = importlib.util.module_from_spec(spec); spec.loader.exec_module(pw)
spec2 = importlib.util.spec_from_file_location('pwr', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pw_reverify13.py'))
pwr = importlib.util.module_from_spec(spec2); spec2.loader.exec_module(pwr)

INST_DIR = pw.INST_DIR
TODAY = time.strftime('%Y-%m-%d', time.gmtime())

def main():
    max_files = int(sys.argv[1]) if len(sys.argv) > 1 else 100000
    cands = {c['fn']: c for c in json.load(open(os.path.join(WAVE13, 'stats', 'pw_candidates.json')))}
    import pandas as pd
    remote = pd.read_parquet(os.path.join(WAVE13, 'dedupe', 'pw_remote.parquet'))
    have_ids = set(remote['id'].astype(str))
    have_titles = {norm(t) for t in remote['title'].astype(str)}
    local_ids = {f[:-5] for f in os.listdir(INST_DIR)} if os.path.isdir(INST_DIR) else set()
    stats_path = os.path.join(WAVE13, 'stats', 'pw_ocr.json')
    stats = json.load(open(stats_path)) if os.path.isfile(stats_path) else {'items': [], 'recovered': 0, 'reject': 0, 'dup_skip': 0}
    done = {it['fn'] for it in stats['items']}
    ocr_dir = os.path.join(WAVE13, 'ocr_pdfs', 'pw')
    files = sorted(f for f in os.listdir(ocr_dir) if f.endswith('.pdf')) if os.path.isdir(ocr_dir) else []
    print('pw ocr jobs:', len(files), flush=True)
    n = 0
    for fn in files:
        if n >= max_files: break
        if fn in done: continue
        c = cands.get(fn)
        if c is None:
            stats['items'].append({'fn': fn, 'outcome': 'no_candidate_record'})
            continue
        if c['id'] in have_ids or c['id'] in local_ids:
            stats['dup_skip'] += 1
            stats['items'].append({'fn': fn, 'outcome': 'dup_skip'})
            json.dump(stats, open(stats_path, 'w'), indent=1)
            continue
        n += 1
        path = os.path.join(ocr_dir, fn)
        try:
            text, npages, attempted = ocr_pdf_pages(path, f"pw__{fn[:-4]}", 'eng')
        except Exception as e:
            stats['items'].append({'fn': fn, 'outcome': f'error: {type(e).__name__}: {e}'[:140]})
            json.dump(stats, open(stats_path, 'w'), indent=1)
            continue
        ok, metrics = quality(text, 'eng')
        clause = pwr.verified(text) if ok else None
        item = {'fn': fn, 'pages': npages, 'pages_attempted': attempted, 'clause': clause, **metrics}
        if ok and clause and attempted == npages:
            title = ''
            for line in text.splitlines():
                line = re.sub(r'\s+', ' ', line).strip()
                if len(line) >= 18 and not re.fullmatch(r'[\d\s\.\-_/]+', line):
                    title = line[:240]; break
            if not title:
                title = re.sub(r'[-_]+', ' ', c['stem']).strip()[:240]
            if norm(title) in have_titles:
                item['outcome'] = 'dup_title'
                stats['reject'] += 1
            else:
                ym = re.search(r'\b(19|20)\d{2}\b', text[:2000]) or re.search(r'\b(19|20)\d{2}\b', fn)
                doc_type = 'statute' if c['pattern'] in ('rppl', 'public_law') else \
                           ('executive_order' if c['pattern'] in ('executive_order', 'eo') else 'document')
                rec = {'id': c['id'], 'title': title, 'text': text,
                       'source_url': c['live_url'], 'source_type': 'palaugov_pw',
                       'jurisdiction': 'PW', 'country': 'Palau', 'language': 'en',
                       'eli': None, 'date': f'{ym.group(0)}-01-01' if ym else None,
                       'retrieved_at': TODAY + 'T00:00:00Z', 'license': pw.LICENSE,
                       'law_status': 'current', 'identifier': c['stem'],
                       'official_identifier': c['stem'],
                       'article_count': pw.count_articles(text),
                       'schema_version': 'collection_record.v1', 'record_type': 'law',
                       'law_identifier': c['stem'], 'document_type': doc_type,
                       'is_current': True, 'canonical_law_url': c['live_url'],
                       'article_extraction_status': 'missing',
                       'metadata': {'collector': 'wave13 palaugov harvest (palaugov.pw) — OCR pass',
                                    'schema': 'collection_record.v1',
                                    'source_host': 'www.palaugov.pw'}}
                with open(os.path.join(INST_DIR, c['id'] + '.json'), 'w') as f:
                    json.dump(rec, f, ensure_ascii=False)
                local_ids.add(c['id']); have_titles.add(norm(title))
                item['outcome'] = 'recovered'
                stats['recovered'] += 1
        elif ok and clause and attempted < npages:
            item['outcome'] = 'incomplete_pages_not_staged'
            stats['reject'] += 1
        else:
            item['outcome'] = 'quality_or_verify_reject'
            stats['reject'] += 1
        stats['items'].append(item)
        json.dump(stats, open(stats_path, 'w'), indent=1)
        print(fn, item['outcome'], metrics.get('chars'), clause, flush=True)
    json.dump(stats, open(stats_path, 'w'), indent=1)
    print(json.dumps({k: v for k, v in stats.items() if k != 'items'}))

if __name__ == '__main__':
    main()
