"""Hand check for gb_ukla_collect.py: 20 items across eras; independent reference = AKN (data.akn) for XML items,
raw pdftotext for PDF items."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import collections, datetime as dt, gzip, json, os, re, statistics, sys
sys.path.insert(0, '/workspace/scripts')
import gb_ukla_collect as C, gb_ukla_client as G
B = C.BASE

def toks(s):
    return collections.Counter(w for w in re.findall(r'[0-9a-z]+', (s or '').lower()) if len(w) >= 2)

def akn_ref(cli, e):
    url = C.https(e['akn']) if e.get('akn') else None
    if not url: return None, None
    cp = f"{B}/cache/akn/{C.law_id(e)}.akn.gz"
    if os.path.exists(cp): raw = gzip.open(cp).read()
    else:
        st, h, raw = cli.get(url)
        if st != 200: return None, url
        os.makedirs(os.path.dirname(cp), exist_ok=True); gzip.open(cp, 'wb').write(raw)
    return raw, url

def akn_stats(raw):
    from xml.etree import ElementTree as ET
    r = ET.fromstring(raw)
    ln = lambda x: x.tag.rsplit('}', 1)[-1]
    body = next((x for x in r.iter() if ln(x) == 'body'), None)
    secs = [x for x in (body.iter() if body is not None else []) if ln(x) == 'section']
    scheds = set()
    for x in r.iter():
        eid = x.get('eId') or ''
        m = re.match(r'^schedule(?:-([0-9A-Za-z]+))?$', eid)
        if m and ln(x) in ('hcontainer', 'attachment', 'doc', 'mainBody'): scheds.add(eid)
    for x in r.iter():
        if ln(x) == 'attachment': scheds.add(x.get('eId') or f'att{len(scheds)}')
    # text of body + schedules (skip notes/metadata)
    SKIP = {'meta', 'notes', 'note', 'authorialNote', 'proprietary', 'references', 'analysis', 'lifecycle', 'identification'}
    parts = []
    def rec(x):
        if ln(x) in SKIP: return
        if x.text: parts.append(x.text)
        for ch in x:
            rec(ch)
            if ch.tail: parts.append(ch.tail)
    rec(r)
    return len(secs), len(scheds), ' '.join(parts)

def run(args):
    log = C.mk_logger(f'{B}/probe/handcheck.log')
    cli = G.Client(log=log)
    uris = json.load(open(args[0] if args else f'{B}/probe/handcheck_ids.json'))
    ents = {e['uri']: e for e in C.load_feed_entries(None)}
    now = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    laws, arts, rows = [], [], []
    for u in uris:
        e = ents[u]
        kind, raw, url, cp = C.fetch_item(cli, e)
        law, a = C.build_record(e, kind, raw, url, cp, now)
        m = json.loads(law['metadata_json'])
        row = {'id': law['id'], 'uri_path': law['identifier'], 'year': e['year'], 'title': e['title'], 'availability': e['availability'],
               'content_kind': kind, 'law_status': law['law_status'], 'metadata_only': m.get('metadata_only'), 'text_source': m.get('text_source'),
               'text_chars': len(law['text']), 'sections_out': sum(1 for x in a if x['record_type'] == 'article'),
               'schedules_out': sum(1 for x in a if x['record_type'] == 'schedule'), 'empty_articles': sum(1 for x in a if not x['text'].strip()),
               'locality_guess': m.get('locality_guess'), 'source_url': url}
        if kind == 'xml':
            ar, aurl = akn_ref(cli, e)
            if ar:
                ns, nsch, at = akn_stats(ar)
                ta, tl = toks(at), toks(law['text'])
                row.update({'ref': 'AKN ' + aurl, 'sections_ref': ns, 'schedules_ref': nsch,
                            'coverage_ref_in_text': round(sum((ta & tl).values()) / max(1, sum(ta.values())), 4),
                            'precision_text_in_ref': round(sum((ta & tl).values()) / max(1, sum(tl.values())), 4)})
        elif kind == 'pdf':
            row.update({'pdf_pages': m.get('pdf_pages'), 'pdf_text_words': m.get('pdf_text_words'), 'pdf_text_layer': m.get('pdf_text_layer'),
                        'pdf_bytes': len(raw)})
        row['text_head'] = law['text'][:200].replace('\n', ' / ')
        rows.append(row); laws.append(law); arts += a
        log(f"hc {law['id']} {kind} status={law['law_status']} chars={len(law['text'])} sec={row['sections_out']}/{row.get('sections_ref')} sch={row['schedules_out']}/{row.get('schedules_ref')} cov={row.get('coverage_ref_in_text')} layer={row.get('pdf_text_layer')}")
    ids = [l['id'] for l in laws] + [x['id'] for x in arts]
    json.dump({'rows': rows, 'nreq': cli.nreq, 'unique_ids': len(ids) == len(set(ids)), 'n_ids': len(ids)},
              open(f'{B}/probe/handcheck_raw.json', 'w'), indent=1, ensure_ascii=False)
    C.write_parquet(laws, arts, f'{B}/handcheck/data')
    log(f'handcheck done nreq={cli.nreq} unique_ids={len(ids) == len(set(ids))}')
