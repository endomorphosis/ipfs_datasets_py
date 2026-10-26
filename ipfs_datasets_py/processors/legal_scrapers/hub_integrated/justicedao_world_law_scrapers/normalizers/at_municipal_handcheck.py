"""Gate / sample / handcheck drivers for at_municipal_collect.py (small, manual-comparable request volumes)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import datetime as dt, gzip, json, os, shutil, sys, time
sys.path.insert(0, '/workspace/scripts')
import at_municipal_collect as C

B = C.BASE
EV = '/workspace/country-law-triage/municipal_evidence_20261004/at'

def mode_gate(args):
    log = C.mk_logger(f'{B}/probe/gate.log')
    cli = C.Client(log, status_file=f'{B}/probe/status_lines.txt')
    out = {'started_pt': dt.datetime.now().astimezone().isoformat(timespec='seconds'), 'window_open_vienna': C.window_open()}
    if not C.window_open(): log('office hours -> abort gate'); sys.exit(2)
    # robots: data.bka.gv.at + www.ris.bka.gv.at fetched 12:54 PT today (copy); ogd.ris.bka.gv.at fetched now
    shutil.copy(f'{EV}/robots_data_bka_gv_at.txt', f'{B}/robots/data.bka.gv.at_robots.txt')
    shutil.copy(f'{EV}/robots_www_ris_bka_gv_at.txt', f'{B}/robots/www.ris.bka.gv.at_robots.txt')
    rob = {}
    for host in ['ogd.ris.bka.gv.at', 'www.statistik.at']:
        rp = f'{B}/robots/{host}_robots.txt'
        if os.path.exists(rp):
            rob[host] = {'status': 200, 'fetched_pt': '2026-10-04T14:28 PT', 'text': open(rp).read()}; continue
        st, hdr, body = cli.get(f'https://{host}/robots.txt')
        with open(f'{B}/robots/{host}_robots.txt', 'wb') as f: f.write(body)
        rob[host] = {'status': st, 'ctype': hdr.get('Content-Type'), 'text': body.decode('utf-8', 'replace')[:3000]}
    out['robots_fetched'] = rob
    counts = {}
    samples = {}
    for app in ('Gr', 'GrA'):
        for iso, vgr, vgra, d in C.LAENDER:
            land = vgr if app == 'Gr' else vgra
            try:
                hits, refs, body = C.api_search(cli, app, page=1, size='Ten', Bundesland=land)
            except C.ApiError as e:
                counts.setdefault(app, {})[iso + ' ' + vgra] = f'API_ERROR {str(e)[-160:]}'; log(f'{app} {land}: {e}'); continue
            counts.setdefault(app, {})[iso + ' ' + vgra] = hits
            with gzip.open(f'{B}/probe/search_{app}_{iso}_p1.json.gz', 'wb') as f: f.write(body)
            log(f'{app} {land}: {hits}')
        hits, refs, body = C.api_search(cli, app, page=1, size='Ten')
        counts[app]['TOTAL_unfiltered'] = hits
    out['counts'] = counts
    out['nreq'] = cli.nreq
    with open(f'{B}/probe/gate_raw.json', 'w') as f: json.dump(out, f, indent=1, ensure_ascii=False)
    log(f'gate done nreq={cli.nreq}')

def mode_extra(args):
    """A few extra listing requests: FassungVom (in-force filter) for Gr, random pages for type diversity."""
    log = C.mk_logger(f'{B}/probe/gate.log')
    cli = C.Client(log, status_file=f'{B}/probe/status_lines.txt')
    if not C.window_open(): log('office hours -> abort'); sys.exit(2)
    res = {}
    for spec in json.loads(args[0]):
        app = spec.pop('Applikation'); page = spec.pop('Seitennummer', 1); size = spec.pop('DokumenteProSeite', 'Twenty')
        hits, refs, body = C.api_search(cli, app, page=page, size=size, **spec)
        tag = spec.pop('tag')
        with gzip.open(f'{B}/probe/extra_{tag}.json.gz', 'wb') as f: f.write(body)
        res[tag] = hits; log(f'extra {tag}: hits={hits} refs={len(refs)}')
    p = f'{B}/probe/extra_counts.json'
    old = json.load(open(p)) if os.path.exists(p) else {}
    old.update(res); json.dump(old, open(p, 'w'), indent=1)

SAMPLE_IDS = [
 'GEMRE_KA_20701_000__902__2020_me_', 'GEMRE_KA_20511_17_2006', 'GEMRE_NI_31716_VO_01_2026', 'GEMRE_NI_31516_1_2014',
 'GEMRE_OB_40101_0011262_2026', 'GEMRE_OB_40101_0017118_2025_BBV_BeG', 'GEMRE_SA_50311_14480', 'GEMRE_SA_50311_14983',
 'GEMRE_ST_60101__A7_LM091739_2021_0022', 'GEMRE_ST_60101_F_006230_2005_0055', 'GEMRE_WI_90101_B080_040_2026', 'GEMRE_WI_90101_B020_080',
 'GEMREA_OB_40411_20261002_3', 'GEMREA_OB_41223_20261002_6', 'GEMREA_OB_40801_20261002_6', 'GEMREA_TI_70509_20261002_11',
 'GEMREA_TI_70604_20261001_13', 'GEMREA_VO_80231_20261001_4', 'GEMREA_VO_80203_20260930_23', 'GEMREA_VO_80111_20261002_4']

def all_probe_refs():
    import glob
    refs = {}
    for p in sorted(glob.glob(f'{B}/probe/search_*.json.gz')) + sorted(glob.glob(f'{EV}/api_gemeinden_*_count.json')):
        op = gzip.open if p.endswith('.gz') else open
        d = json.load(op(p, 'rt'))
        for x in C.aslist(d['OgdSearchResult']['OgdDocumentResults'].get('OgdDocumentReference')):
            refs.setdefault(x['Data']['Metadaten']['Technisch']['ID'], x)
    return refs

def mode_sample(args):
    log = C.mk_logger(f'{B}/probe/gate.log')
    cli = C.Client(log, status_file=f'{B}/probe/status_lines.txt')
    refs = all_probe_refs(); bez = C.load_bezirke()
    for rid in SAMPLE_IDS:
        md = C.parse_meta(refs[rid], bez)
        kind, raw, url, cp = C.fetch_main(cli, md)
        log(f'sample {rid}: {kind} {len(raw) if raw else 0} bytes')
        if md['application'] == 'Gr':
            h = C.fetch_html_ref(cli, md); log(f'  html ref {len(h) if h else 0}')
    log(f'sample done nreq={cli.nreq}')

DEDUP_PAIR = ['GEMRE_OB_40101_0051832_2026', 'GEMREA_OB_40101_20260925_21']  # Linz "EVO 2024 1. Aenderungsverordnung" in Gr and GrA

def _toks(s):
    import re, collections
    return collections.Counter(w for w in re.findall(r'[0-9a-zäöüß]+', s.lower()) if len(w) >= 2)

BOILER = {'www.ris.bka.gv.at', 'gemeinderecht'}

def _src_ref(md, kind, raw, cli):
    import re
    if md['application'] == 'Gr':
        h = C.fetch_html_ref(cli, md)
        t = C.html_text(h) if h else ''
        lines = [l for l in t.split('\n') if l.strip() and l.strip().lower() not in BOILER and not re.fullmatch(r'Seite \d+ von \d+', l.strip())]
        return '\n'.join(lines), 'html'
    return C.pdf_to_text(raw), 'pdftotext_raw'

def _name_match(a, b):
    import re
    n = lambda x: re.sub(r'[^a-zäöüß]', '', (x or '').lower().replace('st.', 'sankt'))
    return bool(a and b) and (n(a) in n(b) or n(b) in n(a))

def mode_handcheck(args):
    import re, statistics
    log = C.mk_logger(f'{B}/probe/gate.log')
    cli = C.Client(log, status_file=f'{B}/probe/status_lines.txt')
    refs = all_probe_refs(); bez = C.load_bezirke()
    laws, arts, rows = [], [], []
    now = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    for rid in SAMPLE_IDS + DEDUP_PAIR:
        md = C.parse_meta(refs[rid], bez)
        kind, raw, url, cp = C.fetch_main(cli, md)
        law, a = C.build_record(md, raw, kind, url, cp, now)
        src, srckind = _src_ref(md, kind, raw, cli)
        ts, to = _toks(src), _toks(law['text'])
        cov = sum((ts & to).values()) / max(1, sum(ts.values()))
        rev = sum((ts & to).values()) / max(1, sum(to.values()))
        src_heads = []
        for ln in src.split('\n'):
            lab = C.head_label(ln.strip())
            if lab: lab = re.sub(r'^§\s*', '§ ', lab)
            if lab and lab not in src_heads: src_heads.append(lab)
        out_heads = []
        for x in a:
            if x['record_type'] == 'article' and x['document_number'] not in out_heads: out_heads.append(x['document_number'])
        n_art_rows = sum(1 for x in a if x['record_type'] == 'article')
        rec = {'ris_id': rid, 'application': md['application'], 'role': 'dedup_pair' if rid in DEDUP_PAIR else 'sample',
               'bundesland': md['bundesland'], 'bezirk': md['bezirk'], 'gemeinde': md['gemeinde'], 'gkz': md['gkz'],
               'gemeinde_statistik_austria': md['gemeinde_statistik_austria'],
               'mapping_ok': _name_match(md['gemeinde'], md['gemeinde_statistik_austria']),
               'jurisdiction': law['jurisdiction'], 'typ': md['typ'], 'title': law['title'][:120], 'law_status': law['law_status'],
               'date': law['date'], 'content_kind': kind, 'source_url': url, 'src_bytes': len(raw), 'text_chars': len(law['text']),
               'ref_kind': srckind, 'ref_chars': len(src), 'token_coverage_ref_in_text': round(cov, 4), 'token_precision_text_in_ref': round(rev, 4),
               'src_section_heads': len(src_heads), 'articles': n_art_rows, 'distinct_article_labels': len(out_heads), 'preamble': sum(1 for x in a if x['record_type'] == 'preamble'),
               'annex': sum(1 for x in a if x['record_type'] == 'annex'), 'heads_match': set(src_heads) == set(out_heads),
               'empty_articles': sum(1 for x in a if not x['text'].strip()), 'attachments': len(md['attachments']),
               'text_head': law['text'][:220].replace('\n', ' / ')}
        rows.append(rec)
        if rid not in DEDUP_PAIR:
            laws.append(law); arts += a
        else:
            rec['_text'] = law['text']
        log(f"hc {rid} cov={rec['token_coverage_ref_in_text']} prec={rec['token_precision_text_in_ref']} heads {rec['src_section_heads']}/{rec['articles']} map={rec['mapping_ok']}")
    # dedup pair similarity
    pa_, pb = [r for r in rows if r['role'] == 'dedup_pair']
    ta, tb = _toks(pa_.pop('_text')), _toks(pb.pop('_text'))
    jacc = sum((ta & tb).values()) / max(1, sum((ta | tb).values()))
    contain = sum((ta & tb).values()) / max(1, min(sum(ta.values()), sum(tb.values())))
    ids = [l['id'] for l in laws] + [x['id'] for x in arts]
    summary = {
        'generated_pt': dt.datetime.now().astimezone().isoformat(timespec='seconds'), 'n_regulations': len(laws), 'n_articles': len(arts),
        'by_application': {k: sum(1 for r in rows if r['role'] == 'sample' and r['application'] == k) for k in ('Gr', 'GrA')},
        'by_bundesland': {}, 'by_typ': {},
        'empty_law_text': sum(1 for l in laws if not l['text'].strip()), 'empty_article_text': sum(1 for x in arts if not x['text'].strip()),
        'unique_ids': len(ids) == len(set(ids)), 'n_ids': len(ids),
        'mapping_ok': sum(1 for r in rows if r['role'] == 'sample' and r['mapping_ok']),
        'min_token_coverage': min(r['token_coverage_ref_in_text'] for r in rows if r['role'] == 'sample'),
        'median_token_coverage': statistics.median(r['token_coverage_ref_in_text'] for r in rows if r['role'] == 'sample'),
        'heads_match': sum(1 for r in rows if r['role'] == 'sample' and r['heads_match']),
        'dedup_pair': {'gr': DEDUP_PAIR[0], 'gra': DEDUP_PAIR[1], 'token_jaccard': round(jacc, 4), 'token_containment': round(contain, 4)},
        'nreq_this_step': cli.nreq,
    }
    for r in rows:
        if r['role'] != 'sample': continue
        summary['by_bundesland'][r['bundesland']] = summary['by_bundesland'].get(r['bundesland'], 0) + 1
        summary['by_typ'][r['typ']] = summary['by_typ'].get(r['typ'], 0) + 1
    # dedup linking test: run link_gr_gra over samples + the Linz pair
    pair_laws = [dict(l) for l in laws]
    for rid in DEDUP_PAIR:
        md = C.parse_meta(refs[rid], bez); kind, raw, url, cp = C.fetch_main(cli, md)
        pair_laws.append(C.build_record(md, raw, kind, url, cp, now)[0])
    summary['dedup_linked_pairs_in_sample_plus_pair'] = C.link_gr_gra(pair_laws)
    outdir = f'{B}/handcheck/data'
    C.write_parquet(laws, arts, outdir)
    json.dump({'summary': summary, 'rows': rows}, open(f'{B}/probe/handcheck_raw.json', 'w'), indent=1, ensure_ascii=False)
    print(json.dumps(summary, indent=1, ensure_ascii=False))
