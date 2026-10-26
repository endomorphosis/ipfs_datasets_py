"""Wave 13 Palau completeness audit for written instruments.

The 1 MiB-truncated-capture defect (pw_refetch13) raises the
question for the 20 instruments already written from digital
extraction: could any be silently partial (truncated source PDF
that still yielded >300 chars of front matter)? For each written
instrument, fetch the LARGEST Wayback capture of its source URL,
extract with the capped child, and compare char counts:
instrument >= 98% of the audit extraction -> complete (no change);
otherwise REPLACE the instrument's text (and article_count) with
the audit extraction and record it. Instruments whose capture
cannot be fetched are flagged 'unverifiable' — still staged, but
documented here and in the report.

Stats: wave13/stats/pw_audit.json.
"""
import json, os, sys, urllib.parse
import requests
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common13 import WAVE13
import importlib.util
spec = importlib.util.spec_from_file_location('pw', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pw_harvest13.py'))
pw = importlib.util.module_from_spec(spec); spec.loader.exec_module(pw)

S = requests.Session(); S.headers.update({'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) legal-data-research/1.0'})
INST_DIR = pw.INST_DIR

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
    cands = {c['id']: c for c in json.load(open(os.path.join(WAVE13, 'stats', 'pw_candidates.json')))}
    audit_dir = os.path.join(WAVE13, 'pdf_cache', 'pw_audit'); os.makedirs(audit_dir, exist_ok=True)
    out = {'items': []}
    for fn in sorted(os.listdir(INST_DIR)):
        if not fn.endswith('.json'):
            continue
        iid = fn[:-5]
        rec = json.load(open(os.path.join(INST_DIR, fn)))
        c = cands.get(iid)
        item = {'id': iid, 'inst_chars': len(rec.get('text', ''))}
        if c is None:
            item['outcome'] = 'no_candidate_record'
            out['items'].append(item); print(item, flush=True); continue
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
        if not rows:
            item['outcome'] = 'unverifiable_no_snapshots'
            out['items'].append(item); print(item, flush=True); continue
        rows.sort(reverse=True)
        length, ts, v = rows[0]
        item['largest_capture'] = length
        dest = os.path.join(audit_dir, c['fn'])
        if not (os.path.isfile(dest) and pw.is_pdf(dest)):
            n = pw.stream_download(f"https://web.archive.org/web/{ts}id_/{v}", dest, timeout=600)
            if not (n and pw.is_pdf(dest)):
                item['outcome'] = 'unverifiable_fetch_failed'
                out['items'].append(item); print(item, flush=True); continue
        got = pw.extract(dest)
        if got is None:
            item['outcome'] = 'unverifiable_extract_failed'
            out['items'].append(item); print(item, flush=True); continue
        text, pages, _meta = got
        text = text.strip()
        item['audit_chars'] = len(text)
        if len(rec['text']) >= 0.98 * len(text):
            item['outcome'] = 'complete'
        elif len(text) >= 300:
            rec['text'] = text
            rec['article_count'] = pw.count_articles(text)
            rec.setdefault('metadata', {})['completeness_audit'] = 'text replaced from largest Wayback capture (wave13 pw_audit13)'
            json.dump(rec, open(os.path.join(INST_DIR, fn), 'w'), ensure_ascii=False)
            item['outcome'] = 'REPLACED_with_complete_text'
        else:
            item['outcome'] = 'audit_copy_shorter_kept_instrument'
        out['items'].append(item)
        print(item, flush=True)
    json.dump(out, open(os.path.join(WAVE13, 'stats', 'pw_audit.json'), 'w'), indent=1)
    from collections import Counter
    print(Counter(i['outcome'] for i in out['items']))

if __name__ == '__main__':
    main()
