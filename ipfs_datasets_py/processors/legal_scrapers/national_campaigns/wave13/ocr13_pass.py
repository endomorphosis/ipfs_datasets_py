"""Wave 13 OCR pass over banked no-text FAOLEX PDFs.

Sources (all page-checkpointed via ocr13_engine):
 - wave12/ocr_pdfs/{by,ge,ne,sz,ba}/  banked short_text files (wave-12 walks)
 - wave13/ocr_pdfs/{cc}/              new short_text files from wave-13 walks
 - wave11/ocr_pdfs/sv/                the 39 deferred files of the wave-11
                                      sv OCR queue (wave 12 recovered 4/43)

Tesseract languages fetched at wave start into wave13/tessdata:
by->rus, ge->kat, ba->bos, ne->fra, sz->eng, sv->spa.
A file is written as an instrument ONLY if it clears the engine's
quality bar (chars>=300, alpha ratio, script/stopword check) — garbage
stays excluded and is recorded in the stats. Instruments use the
wave<=12 OCR convention: source_type 'faolex-ecolex-ocr',
official_identifier LEX-FAOC<num>.

Usage: ocr13_pass.py <group>   group in {bank12, walk13, svqueue}
Stats: wave13/stats/ocr13_<group>.json (rewritten after every file).
"""
import json, os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common13 import TARGETS, WAVE13, WAVE12, WAVE11, norm
from ocr13_engine import ocr_pdf_pages, quality

INST_BASE = os.path.expanduser('~/.ipfs_datasets/legal-corpora')
TODAY = time.strftime('%Y-%m-%d', time.gmtime())
TESS_LANG = {'by': 'rus', 'ge': 'kat', 'ba': 'bos', 'ne': 'fra', 'sz': 'eng', 'sv': 'spa'}
REC_LANG = {'by': 'ru', 'ge': 'ka', 'ba': 'bs', 'ne': 'fr', 'sz': 'en', 'sv': 'es'}

def count_articles(text):
    pats = [r'(?m)^\s*Article\s+\d+', r'(?m)^\s*ARTICLE\s+\d+',
            r'(?m)^\s*Art\.\s*\d+', r'(?m)^\s*Section\s+\d+']
    return max((len(re.findall(p, text)) for p in pats), default=0)

def derive_title(text):
    for line in text.splitlines():
        line = re.sub(r'\s+', ' ', line).strip()
        if len(line) >= 18 and not re.fullmatch(r'[\d\s\.\-_/]+', line):
            return line[:240]
    return 'Untitled FAOLEX document (OCR)'

def save(cc, iid, fn, text):
    _repo, _disp, _e, jurisdiction, _dl = TARGETS[cc]
    num = re.search(r'\d+', fn[:-4]).group(0) if re.search(r'\d+', fn[:-4]) else iid
    ym = re.search(r'\b(19|20)\d{2}\b', text[:1500])
    rec = {'id': iid, 'title': derive_title(text), 'text': text,
           'source_url': f"https://faolex.fao.org/docs/pdf/{fn}",
           'source_type': 'faolex-ecolex-ocr',
           'jurisdiction': jurisdiction, 'country': cc,
           'language': REC_LANG[cc], 'eli': None,
           'date': ym.group(0) if ym else None,
           'retrieved_at': TODAY + 'T00:00:00Z',
           'license': 'public-domain', 'law_status': 'unknown',
           'identifier': iid, 'official_identifier': f'LEX-FAOC{num}',
           'article_count': count_articles(text)}
    d = os.path.join(INST_BASE, cc, 'instruments'); os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, iid + '.json'), 'w') as f:
        json.dump(rec, f, ensure_ascii=False)

def jobs_for(group):
    jobs = []  # (cc, fn, pdf_path)
    if group == 'bank12':
        for cc in ('by', 'ge', 'ne', 'sz', 'ba'):
            d = os.path.join(WAVE12, 'ocr_pdfs', cc)
            if os.path.isdir(d):
                for fn in sorted(os.listdir(d)):
                    if fn.endswith('.pdf'):
                        jobs.append((cc, fn, os.path.join(d, fn)))
    elif group == 'walk13':
        for cc in ('ba', 'sz', 'sv', 'by', 'ge', 'ne'):
            d = os.path.join(WAVE13, 'ocr_pdfs', cc)
            if os.path.isdir(d):
                for fn in sorted(os.listdir(d)):
                    if fn.endswith('.pdf'):
                        jobs.append((cc, fn, os.path.join(d, fn)))
    elif group == 'svqueue':
        d = os.path.join(WAVE11, 'ocr_pdfs', 'sv')
        for fn in sorted(os.listdir(d)):
            if fn.endswith('.pdf'):
                jobs.append(('sv', fn, os.path.join(d, fn)))
    else:
        raise SystemExit(f'unknown group {group}')
    return jobs

def main():
    group = sys.argv[1]
    max_files = int(sys.argv[2]) if len(sys.argv) > 2 else 100000
    stats_path = os.path.join(WAVE13, 'stats', f'ocr13_{group}.json')
    stats = {'group': group, 'items': [], 'recovered': 0, 'quality_reject': 0,
             'dup_skip': 0, 'errors': 0}
    if os.path.isfile(stats_path):
        stats = json.load(open(stats_path))
    done_files = {it['file'] + '|' + it['cc'] for it in stats['items']}
    jobs = jobs_for(group)
    print(group, 'jobs:', len(jobs), flush=True)
    n = 0
    for cc, fn, path in jobs:
        if n >= max_files:
            break
        iid = f"{cc}-faolex-{fn[:-4]}"
        key = fn + '|' + cc
        if key in done_files:
            continue
        dedupe = json.load(open(os.path.join(WAVE13, 'dedupe', f'{cc}_dedupe.json')))
        hf_ids = {r['id'] for r in dedupe}
        hf_titles = {r['norm_title'] for r in dedupe if r['norm_title']}
        inst_dir = os.path.join(INST_BASE, cc, 'instruments')
        local_ids = {f[:-5] for f in os.listdir(inst_dir)} if os.path.isdir(inst_dir) else set()
        if iid in hf_ids or iid in local_ids:
            stats['dup_skip'] += 1
            stats['items'].append({'cc': cc, 'file': fn, 'outcome': 'dup_skip'})
            json.dump(stats, open(stats_path, 'w'), indent=1)
            continue
        n += 1
        try:
            text, npages, attempted = ocr_pdf_pages(path, f"{cc}__{fn[:-4]}", TESS_LANG[cc])
        except Exception as e:
            stats['errors'] += 1
            stats['items'].append({'cc': cc, 'file': fn, 'outcome': f'error: {type(e).__name__}: {e}'[:160]})
            json.dump(stats, open(stats_path, 'w'), indent=1)
            continue
        ok, metrics = quality(text, TESS_LANG[cc])
        item = {'cc': cc, 'file': fn, 'pages': npages, 'pages_attempted': attempted, **metrics}
        if ok and attempted == npages:
            if norm(derive_title(text)) in hf_titles:
                item['outcome'] = 'dup_title'
                stats['quality_reject'] += 0  # not a reject; just not new
            else:
                save(cc, iid, fn, text)
                item['outcome'] = 'recovered'
                stats['recovered'] += 1
        elif ok and attempted < npages:
            item['outcome'] = 'incomplete_pages_not_staged'
            stats['quality_reject'] += 1
        else:
            item['outcome'] = 'quality_reject'
            stats['quality_reject'] += 1
        stats['items'].append(item)
        json.dump(stats, open(stats_path, 'w'), indent=1)
        print(cc, fn, item['outcome'], metrics, flush=True)
    json.dump(stats, open(stats_path, 'w'), indent=1)
    print(json.dumps({k: v for k, v in stats.items() if k != 'items'}))

if __name__ == '__main__':
    main()
