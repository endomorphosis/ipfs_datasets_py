#!/usr/bin/env python3
"""Post-stage: spot-check, numbering summary, gap list, README Known limitations, triage JSONs. No upload."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, gzip, os, re, random, collections, time, sys
import pyarrow.parquet as pq, pyarrow.compute as pc, threading
def _mg():
    while True:
        for ln in open('/proc/meminfo'):
            if ln.startswith('MemAvailable:') and int(ln.split()[1]) // 1024 <= 3584:
                print('MEMGUARD TERM', flush=True); os._exit(3)
        time.sleep(30)
threading.Thread(target=_mg, daemon=True).start()
sys.path.insert(0, '/workspace/scripts')
BASE = '{_CORPORA}/au_subnational'
STAGE = open(f'{BASE}/last_stage_path.txt').read().strip()
META = json.load(open(f'{STAGE}/PACK_META.json'))
TRI = '/workspace/country-law-triage'
JURS = ['NSW', 'QLD', 'TAS', 'WA', 'NT']
OFFICIAL = {'NSW': 'legislation.nsw.gov.au', 'QLD': 'www.legislation.qld.gov.au', 'TAS': 'www.legislation.tas.gov.au', 'WA': 'www.legislation.wa.gov.au', 'NT': 'legislation.nt.gov.au'}
R = '{_CORPORA}/au_subnational/robots'
SKIPPED = {
 'AU-VIC': {'status': 'BLOCKED', 'block_type': 'robots.txt', 'site': 'www.legislation.vic.gov.au (texts on content.legislation.vic.gov.au)', 'attempted_collection': False,
            'evidence': [
              'recheck 01:44:06 PT: https://content.legislation.vic.gov.au/robots.txt HTTP 200 -> "User-agent: *" / "Disallow: /" (only Twitterbot allowed /sites/default/files) [robots/recheck_content.legislation.vic.gov.au.txt]',
              'www.legislation.vic.gov.au/robots.txt (2026-09-27 PT): Crawl-delay: 2; Disallow: /sites/default/files/*.pdf, *.doc, *.rtf ... [robots/vic.txt]',
              'probe/vic_v.html (/in-force/acts/eastlink-project-act-2004/055): only download links https://content.legislation.vic.gov.au/sites/default/files/2026-04/04-39aa055-authorised.pdf and .../04-39a055.docx; no HTML text of the Act on the page',
              'sitemap (allowed) lists 826 in-force/acts + 462 in-force/statutory-rules pages (probe/vic_sm*.txt), but every text file is under the disallowed content host'],
            'reason': 'The law texts exist only as PDF/DOCX on a host that disallows all crawlers. Not collected.'},
 'AU-SA': {'status': 'BLOCKED', 'block_type': '403 (Cloudflare challenge), BLOCKED_SOURCE', 'site': 'www.legislation.sa.gov.au', 'attempted_collection': False,
           'evidence': [
              'probing on 2026-09-27 ~20:21 PT: robots.txt, / and /browse/legislation each returned HTTP 403 with a Cloudflare "Just a moment..." challenge page (3 consecutive 403s) [robots/sa.txt, probe/sa_home.html, probe/sa2.html]',
              'recheck 01:44:06 PT: https://www.legislation.sa.gov.au/robots.txt HTTP 403 text/html "Just a moment..." [robots/recheck_www.legislation.sa.gov.au.txt]'],
           'reason': '3 consecutive 403s, recorded as BLOCKED_SOURCE. No mirrors, no UA tricks, no contact.'},
 'AU-ACT': {'status': 'BLOCKED', 'block_type': 'robots.txt (listing and text views disallowed); a PDF-only route would need a separate adapter plus an allowed listing source', 'site': 'www.legislation.act.gov.au', 'attempted_collection': False,
            'evidence': [
              'recheck 01:44:07 PT: https://www.legislation.act.gov.au/robots.txt HTTP 200 -> Crawl-delay: 10; Disallow: /results, /View/, /html/, /LegViewer/, /Redirect/, /Scripts/, /Content/, /Subscription/ [robots/recheck_www.legislation.act.gov.au.txt]',
              'probe/act_home.html: the in-force browse lists link to /results?category=...&action=browse, which is disallowed',
              'probe/act_a.html (/a/2001-14/): HTML text links are /View/a/2001-14/.../html/2001-14.html (disallowed); /DownloadFile/a/2001-14/current/PDF/2001-14.PDF is allowed and returned HTTP 200 application/pdf (probe/act_cur.pdf, 1 test fetch)'],
            'reason': 'The only listing endpoint (/results) and the HTML text views are robots-disallowed, and the order says to skip a site that forbids listing. A /DownloadFile PDF adapter would need an allowed enumeration source (none found) and a 10 s crawl delay, so NEEDS_SEPARATE_ADAPTER if CoS wants to pursue it.'},
}

def jl(p):
    with gzip.open(p, 'rt') as f:
        for l in f: yield json.loads(l)

# ---------- counts from staged parquet ----------
lp = pq.ParquetFile(f'{STAGE}/data/laws.parquet'); ap = pq.ParquetFile(f'{STAGE}/data/articles.parquet')
jur_laws = collections.Counter(); art_count = {}; law_jur = {}
for b in lp.iter_batches(batch_size=20000, columns=['id', 'jurisdiction', 'article_count', 'document_type' if False else 'id']):
    for i, j, c in zip(b.column('id').to_pylist(), b.column('jurisdiction').to_pylist(), b.column('article_count').to_pylist()):
        jur_laws[j] += 1
        if j != 'AU': art_count[i] = c; law_jur[i] = j
jur_arts = collections.Counter(); real = collections.Counter()
for b in ap.iter_batches(batch_size=50000, columns=['law_id']):
    for lid in b.column('law_id').to_pylist():
        j = law_jur.get(lid, 'AU'); jur_arts[j] += 1
        if j != 'AU': real[lid] += 1
ac_mismatch = [i for i, c in art_count.items() if real.get(i, 0) != c]

# ---------- per-jurisdiction stats / gaps ----------
per = {}; gaps = []; numbering = {}
for st in JURS:
    s = json.load(open(f'{BASE}/parsed/{st}_stats.json'))
    listed = [json.loads(l) for l in open(f'{BASE}/index/{st}_list.jsonl')]
    built = {i.split(f'au-{st.lower()}-', 1)[1] for i in law_jur if law_jur[i] == f'AU-{st}'}
    missing = [x for x in listed if x['src_id'].lower() not in built]
    for x in missing:
        r = next((g['reason'] for g in s['gaps'] if g['src_id'] == x['src_id']), 'not_built')
        gaps.append(dict(jurisdiction=f'AU-{st}', src_id=x['src_id'], title=x.get('title'), reason=r))
    if st in ('NSW', 'QLD', 'TAS'):
        vv = lambda x, k: (x.get(k) or {}).get('__value__') if isinstance(x.get(k), dict) else x.get(k)
        for x in json.load(open(f'{BASE}/index/{st}_pit_all.json')):
            i = vv(x, 'id') or ''
            if vv(x, 'repealed') == 'N' and not re.match(r'^[a-z]+-\d{4}-[0-9a-z]+$', i):
                missing.append({'src_id': i, 'title': vv(x, 'title')})
                gaps.append(dict(jurisdiction=f'AU-{st}', src_id=i, title=vv(x, 'title'), reason='in force but excluded from the fetch list by a lowercase-only id filter (mixed-case ids such as act-1994-84A, SL-1879-qcipa); not fetched because the collector was not to be restarted. Can be fetched in a follow-up run.'))
    ft = [g for g in s['gaps'] if g['reason'].startswith('no_sections')]
    per[f'AU-{st}'] = dict(listed_in_force=len(listed) + (len(missing) - len([x for x in listed if x['src_id'].lower() not in built])), laws=jur_laws.get(f'AU-{st}', 0), articles=jur_arts.get(f'AU-{st}', 0),
                           acts=s['stats'].get('acts', 0), regulations_subordinate=s['stats'].get('regulations', 0),
                           fulltext_only_no_sections=len(ft), not_collected=len(missing), source=OFFICIAL[st])
    numbering[f'AU-{st}'] = s['numbering']
    for g in ft:
        gaps.append(dict(jurisdiction=f'AU-{st}', src_id=g['src_id'], title=g['title'], reason='law row present with full text; no section units parsed (e.g. proclamation/order without numbered sections)'))

# ---------- numbering explanation (classify non-monotonic steps / duplicates / gaps) ----------
sys.path.insert(0, '/workspace/scripts'); import au_parse as P
explain = {}
for st in JURS:
    by = collections.defaultdict(list)
    for a in jl(f'{BASE}/parsed/{st}_articles.jsonl.gz'):
        if json.loads(a['metadata_json'])['unit'] == 'section': by[a['law_id']].append(a['document_number'])
    c = collections.Counter(); laws_c = collections.defaultdict(set); dup_laws = set(); dup_kind = collections.Counter()
    for lid, v in by.items():
        for a, b in zip(v, v[1:]):
            ka, kb = P._key(a), P._key(b)
            if kb <= ka:
                if ka[0][0] == kb[0][0] and len(ka) == len(kb): k = 'inserted_section_letter_convention (e.g. 5AA before 5A, 57D then 57AA)'
                elif kb[0][0] <= 1: k = 'numbering_restart (rules per Order/Part, embedded scheduled Act/agreement, Part.section numbering)'
                else: k = 'other_out_of_order (embedded schedules/transitional provisions or parse artefact)'
                c[k] += 1; laws_c[k].add(lid)
        cnt = collections.Counter(v)
        if any(n > 1 for n in cnt.values()):
            dup_laws.add(lid)
    gl = 0
    for l in jl(f'{BASE}/parsed/{st}_laws.jsonl.gz'):
        if json.loads(l['metadata_json'])['metadata']['numbering_check']['int_gaps']: gl += 1
    explain[f'AU-{st}'] = dict(nonmonotonic_steps={k: dict(steps=n, laws=len(laws_c[k])) for k, n in c.items()},
                               laws_with_repeated_section_numbers_after_exact_dedupe=len(dup_laws),
                               repeated_numbers_note='exact duplicate units (same number and identical text) were dropped at build time; remaining repeats have different text (numbering restarts in rules/Orders or embedded schedule Acts) and get unique ids with -2/-3 suffixes',
                               laws_with_integer_gaps=gl,
                               integer_gaps_note='gaps are expected: repealed/omitted sections are removed from reprints (NT, WA "Omitted under the Reprints Act"), Part.section numbering, and ranges of repealed provisions')

# ---------- text-extraction empty/short rates ----------
rates = {}
for st in JURS:
    n = z = s200 = s1000 = 0
    for l in jl(f'{BASE}/parsed/{st}_laws.jsonl.gz'):
        n += 1; L = len(l['text']) - len(l['title'])
        z += l['article_count'] == 0; s200 += L < 200; s1000 += L < 1000
    rates[f'AU-{st}'] = dict(laws=n, zero_articles=z, zero_articles_pct=round(100 * z / n, 2), body_text_under_200_chars=s200, under_200_pct=round(100 * s200 / n, 2), body_text_under_1000_chars=s1000,
                             note={'TAS': 'zero-article rows are mostly proclamations/orders with no numbered sections (full text kept)'}.get(st, ''))

# ---------- 20-law spot check (from staged parquet) ----------
random.seed(20260927)
new_ids = sorted(law_jur)
per_j = collections.defaultdict(list)
for i in new_ids: per_j[law_jur[i]].append(i)
sample = []
for j in sorted(per_j):
    sample += random.sample(per_j[j], 4)
sset = set(sample); rows = {}
for b in lp.iter_batches(batch_size=5000, columns=['id', 'title', 'text', 'source_url', 'jurisdiction', 'identifier', 'law_status', 'date']):
    for r in b.to_pylist():
        if r['id'] in sset: rows[r['id']] = r
arts = collections.defaultdict(list)
for b in ap.iter_batches(batch_size=50000, columns=['law_id', 'id', 'title', 'article_number']):
    m = pc.is_in(b.column('law_id'), value_set=__import__('pyarrow').array(sample))
    for r in b.filter(m).to_pylist(): arts[r['law_id']].append(r)
spot = []
for i in sample:
    r = rows[i]; a = arts.get(i, [])
    host = re.match(r'https?://([^/]+)', r['source_url'] or '').group(1) if r['source_url'] else None
    st = r['jurisdiction'].split('-')[1]
    ok_host = host == OFFICIAL[st] or (st == 'WA' and host == 'www.legislation.wa.gov.au')
    first_ok = (not a) or bool(re.match(r'^\[?\s*(\d|Schedule|SCHEDULE|Sch)', a[0]['title']))
    spot.append(dict(id=i, jurisdiction=r['jurisdiction'], title=r['title'], identifier=r['identifier'], date=r['date'], law_status=r['law_status'],
                     articles=len(a), article_count_field=art_count[i], first_article=(a[0]['title'][:80] if a else None),
                     text_starts_with_title=r['text'].startswith(r['title']), official_host=ok_host, first_article_numbered=first_ok,
                     ok=bool(ok_host and first_ok and r['text'].startswith(r['title']) and len(a) == art_count[i])))

handcheck = json.load(open(f'{BASE}/handcheck_20.json'))
nt = META['never_thin']
old_l, old_a = nt['laws']['old_rows'], nt['articles']['old_rows']
new_l, new_a = nt['laws']['new_rows'], nt['articles']['new_rows']
cstate = json.load(open(f'{BASE}/collector_state.json'))

extract = dict(staging_parquet=dict(laws=f'{STAGE}/data/laws.parquet', articles=f'{STAGE}/data/articles.parquet'), text_extraction_rates=rates, handcheck_20_ok=f"{sum(1 for h in handcheck if h['ok'])}/{len(handcheck)}",
    country='Australia (subnational: states & territories)', repo=META['repo'], old_tip=META['base_tip'], published=False, staged=True,
    staging_path=STAGE, staged_at=META['staged_at'],
    per_jurisdiction=per, skipped_or_blocked=SKIPPED,
    totals=dict(old=dict(laws=old_l, articles=old_a), new=dict(laws=new_l, articles=new_a), added=dict(laws=new_l - old_l, articles=new_a - old_a)),
    never_thin_PASS=nt['PASS'], collector=dict(status=cstate.get('status'), started=cstate.get('started'), ended=cstate.get('ended'), blocked_hosts=cstate.get('blocked'), mem_term=cstate.get('mem_term')),
    id_scheme='laws: au-<state>-<official id lower> (e.g. au-nsw-act-2023-054, au-wa-a2089, au-nt-crimes-at-sea-act-2000); articles: <law_id>-s-<section> / <law_id>-sch-<n> (dup -> -2,-3)',
)
gap_list = dict(repo=META['repo'], generated=time.strftime('%Y-%m-%dT%H:%M:%S%z'), skipped_jurisdictions=SKIPPED,
                coverage_notes=[
                    'NSW: in-force Acts (act.reprint) + in-force statutory rules/regulations (reprint, type sl) from projectdata point-in-time 2026-09-28. Environmental planning instruments (EPIs, epi-*) were not returned by the browse data source and are NOT included.',
                    'QLD: in-force Acts + in-force subordinate legislation (sl) from projectdata point-in-time; 4 SL flagged repealed=Y excluded.',
                    'TAS: in-force Acts + in-force statutory rules (GOVMINRULES/BODYRULES/SCRULES incl. proclamations/orders) from projectdata point-in-time; many proclamations/orders have no numbered sections (full text kept, 0 articles).',
                    'WA: Acts in force (actsif_*) + subsidiary legislation in force (subsif_*) from statutes.nsf lists; text = official consolidated HTML rendition (mrdoc_*.htm), not the authorised PDF; date/date_issued left null (not in listing).',
                    'NT: current Acts + subordinate legislation from Legislation Portal By-Title lists; text = pdftotext of the current consolidated PDF (Word is legacy .doc); section splitting is line-start regex with monotonic filter.'],
                per_jurisdiction={k: dict(listed_in_force=v['listed_in_force'], laws=v['laws'], not_collected=v['not_collected'], fulltext_only_no_sections=v['fulltext_only_no_sections']) for k, v in per.items()},
                numbering_explained=explain,
                gaps=gaps)
checks = dict(text_extraction_rates=rates, repo=META['repo'], old_tip=META['base_tip'], numbering_explained=explain, handcheck_20=dict(ok=sum(1 for h in handcheck if h['ok']), n=len(handcheck), rows=handcheck),
              numbering_toc=numbering, article_count_field_vs_rows=dict(new_laws=len(art_count), mismatches=len(ac_mismatch), sample=ac_mismatch[:10]),
              spot_check_20=dict(ok=sum(1 for s in spot if s['ok']), n=len(spot), rows=spot), never_thin=nt,
              jurisdiction_counts_staged=dict(laws=dict(jur_laws), articles=dict(jur_arts)))
os.makedirs(TRI, exist_ok=True)
json.dump(extract, open(f'{TRI}/australia_subnational_extract_result.json', 'w'), indent=1, ensure_ascii=False)
json.dump(gap_list, open(f'{TRI}/australia_subnational_gap_list.json', 'w'), indent=1, ensure_ascii=False)
json.dump(checks, open(f'{TRI}/australia_subnational_checks.json', 'w'), indent=1, ensure_ascii=False)

# ---------- README (append section, keep original text) ----------
rd = open(f'{STAGE}/README.md').read()
if '## State and territory legislation (subnational append)' not in rd:
    tbl = '\n'.join(f"| {k} | {v['source']} | {v['laws']:,} | {v['acts']:,} | {v['regulations_subordinate']:,} | {v['articles']:,} |" for k, v in per.items())
    sk = '\n'.join(f"- **{k}** ({v['site']}): {v['status']}. {v['reason']}" for k, v in SKIPPED.items())
    rd += f"""

## State and territory legislation (subnational append)

Staged {time.strftime('%Y-%m-%d')} on top of hub tip `{META['base_tip'][:12]}`. Commonwealth rows are unchanged and come first;
state/territory rows are appended with `jurisdiction = AU-<STATE>` and `source_type = au_<state>_legislation`.
Totals: {new_l:,} laws (was {old_l:,}), {new_a:,} articles (was {old_a:,}).

| Jurisdiction | Official source | Laws | Acts | Subordinate | Articles |
| --- | --- | ---: | ---: | ---: | ---: |
{tbl}

## Known limitations

{sk}
- NSW environmental planning instruments (EPIs) are not included (not exposed by the in-force browse data source used).
- NSW/QLD/TAS text comes from the official "whole" HTML view of the current in-force version; history notes are stripped. WA text is the official consolidated HTML rendition (the PDF is the official version). NT text is extracted from the current consolidated PDF with pdftotext, so layout artefacts (running headers, hyphenation, tables) can remain.
- Articles are sections/clauses/rules/regulations plus whole schedules; numbering checks flag non-monotonic steps (mostly legitimate inserted-section conventions such as 5AA before 5A) and integer gaps (repealed/omitted provisions).
- Laws without numbered sections (many TAS proclamations/orders, a few rules) have full text in `laws` and 0 articles.
- WA rows have no `date`/`date_issued` (not in the in-force listing). NT `date` is the "As in force at" date from the PDF.
- NT legislation is used under the NT copyright policy (not CC BY): unofficial reproduction, not an official version, no NT arms.
- Not legal advice. The authorised texts on each state/territory legislation website prevail.
"""
    open(f'{STAGE}/README.md', 'w').write(rd)
man = dict(repo=META['repo'], base_tip=META['base_tip'], staged_at=META['staged_at'], per_jurisdiction=per, skipped=SKIPPED,
           totals=extract['totals'], collectors=['scrapers/au_collect.py', 'scrapers/au_parse.py', 'scrapers/au_build.py'])
json.dump(man, open(f'{STAGE}/subnational_manifest.json', 'w'), indent=1, ensure_ascii=False)
print(json.dumps(dict(per=per, totals=extract['totals'], never_thin=nt['PASS'], spot=checks['spot_check_20']['ok'], ac_mismatch=len(ac_mismatch), gaps=len(gaps)), indent=1))
