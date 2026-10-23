"""Wave 13 Palau content_reject re-verification under a corrected rule.

The harvest pass required 'palau' in the first 4,000 chars on top of a
legal marker. Post-pass inspection proved that over-strict: two
rejects are tabular RPPLs whose head is 'RPPL NO. 11-40 / THE NATIONAL
GOVERNMENT SALARY AND WAGE ACT OF 2025' followed by pure number
tables (the word Palau never appears), and the class is already in
the corpus (pw-2015-payscale-rppl-9-39). The corrected rule is applied
UNIFORMLY to all six rejects; a file is verified if ANY holds:
 (a) legal marker in head AND 'palau' anywhere in the full text;
 (b) head matches /RPPL NO. <n>/ (numbered public-law header);
 (c) head matches /EXECUTIVE ORDER NO. <n>/.
Outcomes -> wave13/stats/pw_reverify.json; ledger dispositions in
walk_pw.jsonl are superseded by appended 'written' entries for
recovered files (the harvester's terminal set reads the LAST entry
per file — this script appends, matching that convention's intent;
staging dedupe by ID/title is the final guard either way).
"""
import json, os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common13 import WAVE13, norm
import importlib.util
spec = importlib.util.spec_from_file_location('pw', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pw_harvest13.py'))
pw = importlib.util.module_from_spec(spec); spec.loader.exec_module(pw)

INST_DIR = pw.INST_DIR
TODAY = time.strftime('%Y-%m-%d', time.gmtime())
HDR_RPPL = re.compile(r'RPPL\s+NO\.\s*\d+', re.I)
HDR_EO = re.compile(r'EXECUTIVE ORDER NO\.\s*\d+', re.I)

def verified(text):
    # v3 (2026-10-13, after the fabricated-delivery audit — see report
    # §6): clause (a) marker window widened from 4,000 to 20,000 chars.
    # Chapter excerpts of the EQPB Regulations open with a multi-page
    # table of contents, pushing the first 'Republic of Palau' past
    # char 4,000 — a head-window artifact, not an identity failure.
    # The rule stays uniform across every reject it is applied to.
    head = text[:4000]
    if pw.MARKER.search(text[:20000]) and 'palau' in text.lower():
        return 'a_marker20k+palau_fulltext'
    if HDR_RPPL.search(head):
        return 'b_rppl_header'
    if HDR_EO.search(head):
        return 'c_eo_header'
    return None

def main():
    cands = {c['fn']: c for c in json.load(open(os.path.join(WAVE13, 'stats', 'pw_candidates.json')))}
    import pandas as pd
    remote = pd.read_parquet(os.path.join(WAVE13, 'dedupe', 'pw_remote.parquet'))
    have_titles = {norm(t) for t in remote['title'].astype(str)}
    local_titles = set()
    if os.path.isdir(INST_DIR):
        for f in os.listdir(INST_DIR):
            if f.endswith('.json'):
                local_titles.add(norm(json.load(open(os.path.join(INST_DIR, f))).get('title', '')))
    rejects = []
    for line in open(os.path.join(WAVE13, 'stats', 'walk_pw.jsonl')):
        e = json.loads(line)
        if e['disp'] == 'content_reject':
            rejects.append(e['fn'])
    rejects = sorted(set(rejects))
    cache_dir = os.path.join(WAVE13, 'pdf_cache', 'pw')
    out = {'rule': 'a: marker(head)+palau(fulltext); b: RPPL NO. header; c: EXECUTIVE ORDER NO. header',
           'items': []}
    lf = open(os.path.join(WAVE13, 'stats', 'walk_pw.jsonl'), 'a')
    for fn in rejects:
        c = cands[fn]
        dest = os.path.join(cache_dir, fn)
        item = {'fn': fn}
        if not (os.path.isfile(dest) and pw.is_pdf(dest)):
            n = pw.stream_download(c['live_url'], dest, timeout=180)
            if not (n and pw.is_pdf(dest)):
                item['outcome'] = 'refetch_failed'
                out['items'].append(item); continue
        got = pw.extract(dest)
        if got is None:
            item['outcome'] = 'extract_failed'
            out['items'].append(item); continue
        text, pages, meta = got
        text = text.strip()
        item['chars'] = len(text)
        clause = verified(text) if len(text) >= 300 else None
        item['clause'] = clause
        if not clause:
            item['outcome'] = 'still_rejected'
            out['items'].append(item)
            print(fn, 'still_rejected', len(text), flush=True)
            continue
        title = ''
        if meta and len(meta.strip()) >= 15 and 'untitled' not in meta.lower():
            title = re.sub(r'\s+', ' ', meta).strip()[:240]
        if not title:
            for line in text.splitlines():
                line = re.sub(r'\s+', ' ', line).strip()
                if len(line) >= 18 and not re.fullmatch(r'[\d\s\.\-_/]+', line):
                    title = line[:240]; break
        if not title:
            title = re.sub(r'[-_]+', ' ', c['stem']).strip()[:240]
        if norm(title) in have_titles or norm(title) in local_titles:
            item['outcome'] = 'dup_title'
            out['items'].append(item)
            print(fn, 'dup_title', flush=True)
            continue
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
               'metadata': {'collector': 'wave13 palaugov harvest (palaugov.pw) — reverify pass',
                            'schema': 'collection_record.v1',
                            'source_host': 'www.palaugov.pw'}}
        with open(os.path.join(INST_DIR, c['id'] + '.json'), 'w') as f:
            json.dump(rec, f, ensure_ascii=False)
        lf.write(json.dumps({'fn': fn, 'disp': 'written'}) + '\n'); lf.flush()
        item['outcome'] = 'recovered'
        out['items'].append(item)
        print(fn, 'recovered via', clause, len(text), flush=True)
    json.dump(out, open(os.path.join(WAVE13, 'stats', 'pw_reverify.json'), 'w'), indent=1)
    print(json.dumps(out, indent=1))

if __name__ == '__main__':
    main()
