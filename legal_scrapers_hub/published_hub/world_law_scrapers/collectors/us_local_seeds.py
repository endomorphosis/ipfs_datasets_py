#!/usr/bin/env python3
"""Build US local seed queue v2 (offline; CoS 2026-10-20 16:29 PT). Order: county gov > municipal gov > ambiguous-resolved.
Sources: /workspace/coverage/ipfs_missing_municipal_county_20261020.json (county gaps; municipal gaps gap_reason=no_scraper) merged by qid with
/workspace/coverage/us_local_disambig_urls_20261020.json rows_found (CISA dotgov registry name+state matches -> cisa_matched=True, fetch-time
jurisdiction check) and ambiguous_resolved (Wikidata P131*->P300 single state + host). Classes kept: skip_vendor, hold_private (municipal.codes,
Sterling, ...), hold_tls (verifier TLS HOLD hosts), exclude_nonofficial (Wikidata P856 social/non-official, facebook), http_only_pending
(hosts in us_local/http_only_pending.jsonl), no_url. Previous v1 backed up as *.bak_pre_v2_*."""
import json, sys, os, collections, urllib.parse
sys.path.insert(0, '/workspace/scripts')
from us_local_collect import classify_host, host_of, SEEDS, B, HTTP_ONLY_PENDING
SRC = '/workspace/coverage/ipfs_missing_municipal_county_20261020.json'; DIS = '/workspace/coverage/us_local_disambig_urls_20261020.json'; TRI = '/workspace/coverage/us_local_triage_20261020.json'
SOCIAL = ('facebook.com', 'fb.com', 'twitter.com', 'x.com', 'instagram.com', 'linkedin.com', 'youtube.com', 'wixsite.com', 'blogspot.com', 'nextdoor.com')
def cls_of(h, tls, hop):
    if not h: return 'no_url'
    if h in tls: return 'hold_tls'
    if any(h == s or h.endswith('.' + s) for s in SOCIAL): return 'exclude_nonofficial'
    if h in hop: return 'http_only_pending'
    return classify_host(h)[0]
def build():
    d = json.load(open(SRC)); D = json.load(open(DIS)); T = json.load(open(TRI))
    tls = {host_of('https://' + x['host']) for x in T['gov_sample'] if 'TLS' in (x.get('advisory') or '')}
    hop = {host_of(json.loads(l)['url']) for l in open(HTTP_ONLY_PENDING)} if os.path.exists(HTTP_ONLY_PENDING) else set()
    rows = [x for x in d['rows'] if x['country'] == 'US']
    fams = {'county': [x for x in rows if x['source_path'].endswith('US_county_gaps.jsonl')],
            'municipal': [x for x in rows if x['source_path'].endswith('US_municipality_gaps.jsonl') and x['gap_reason'] == 'no_scraper']}
    found = collections.defaultdict(list)
    for r in D['rows_found']: found[r['tier']].append(r)
    by = {}  # (family, qid or name|state) -> seed
    def key(f, q, n, s): return (f, q or f'{n}|{s}')
    def add(f, n, s, q, urls, src, cisa=False, extra=None):
        k = key(f, q, n, s); e = by.get(k)
        if e is None: e = by[k] = dict(family=f, jurisdiction=n, state_code=s, qid=q, all_urls=[], sources=[], cisa_matched=False, **(extra or {}))
        for u in urls:
            if u and u.startswith('http') and u not in e['all_urls']: e['all_urls'].append(u)
        e['sources'].append(src); e['cisa_matched'] |= cisa
        if not e.get('jurisdiction') and n: e['jurisdiction'] = n
        if not e.get('state_code') and s: e['state_code'] = s
    for f in ('county', 'municipal'):
        for x in fams[f]: add(f, x['jurisdiction'], x.get('state_code'), x.get('qid'), x.get('source_urls') or [], 'ipfs_gap', extra=dict(admin_level=x.get('admin_level'), population=x.get('population')))
        for r in found[f]: add(f, r['name'], r['state'], r['qid'], [r.get('url')], r['source'], cisa='dotgov' in r['source'])
    for r in D['ambiguous_resolved']: add('municipal_ambiguous', r['name'], r['state'], r['qid'], ['https://' + r['host'] + '/'], 'ambiguous_resolved_wikidata', extra=dict(gnis=r.get('gnis')))
    for r in found['municipal_ambiguous']: add('municipal_ambiguous', r['name'], r['state'], r['qid'], [r.get('url')], r['source'], cisa='dotgov' in r['source'])
    # CoS 16:35 PT: 5 official .st.us URLs from the verifier DNS search pass (no site fetched by verifier) -> jurisdiction check at fetch
    for r in D.get('search_pass', {}).get('found', []):
        f = r['tier']; mm = [v for v in by.values() if v['family'] == f and v['jurisdiction'] == r['name'] and v['state_code'] == r['state']]
        if mm: e = mm[0]; e['all_urls'].insert(0, r['url']); e['sources'].append('search_pass_dns_st_us'); e['jur_check'] = True
        else: add(f, r['name'], r['state'], None, [r['url']], 'search_pass_dns_st_us', extra=dict(jur_check=True))
    out = []; C = collections.Counter()
    for f in ('county', 'municipal', 'municipal_ambiguous'):
        for e in [v for v in by.values() if v['family'] == f]:
            urls = e['all_urls']; cl = [cls_of(host_of(u), tls, hop) for u in urls]
            entry = next((u for u, c in zip(urls, cl) if c in ('self_hosted_gov', 'unknown_selfhosted')), None)
            k = cls_of(host_of(entry), tls, hop) if entry else (cl[0] if cl else 'no_url')
            # cisa flag only matters if the entry URL itself came from CISA
            cisa_entry = e['cisa_matched'] and entry is not None and any(entry == r.get('url') for r in found[f]) if f != 'municipal_ambiguous' else e['cisa_matched'] and entry is not None and any(entry == r.get('url') for r in found['municipal_ambiguous'])
            C[(f, k)] += 1
            out.append(dict(e, i=len(out), entry_url=entry, host=host_of(entry) if entry else None, seed_class=k, cisa_matched=bool(cisa_entry), url_classes=cl))
    with open(SEEDS + '.tmp', 'w') as fh:
        for r in out: fh.write(json.dumps(r, ensure_ascii=False) + '\n')
    os.replace(SEEDS + '.tmp', SEEDS)
    summ = {f'{a}/{b}': v for (a, b), v in sorted(C.items())}
    run = [r for r in out if r['seed_class'] in ('self_hosted_gov', 'unknown_selfhosted')]
    summ.update(st_us_added=sum(1 for r in out if r.get('jur_check')), jur_check_runnable=sum(1 for r in run if r.get('jur_check') or r['cisa_matched']), seeds_written=len(out), runnable=len(run), runnable_by_family=dict(collections.Counter(r['family'] for r in run)), cisa_matched_runnable=sum(r['cisa_matched'] for r in run),
                hosts_distinct=len({r['host'] for r in run}), tls_hold_hosts=sorted(tls), http_only_pending_hosts=len(hop))
    json.dump(summ, open(f'{B}/seeds/seed_summary.json', 'w'), indent=1); print(json.dumps(summ, indent=1))
if __name__ == '__main__': build()
