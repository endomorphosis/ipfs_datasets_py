# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, collections, statistics as st, math, time, re, random
B = '{_CORPORA}/cz_sbirkapp'; TS = time.strftime('%Y%m%dT%H%M%S')
Q = json.load(open(f'{B}/index/sample_quality.json')); CNT = json.load(open(f'{B}/index/counts.json'))['counts']
LS = json.load(open(f'{B}/index/listing_sample.json')); ICO = json.load(open(f'{B}/ref/ico_map.json'))['map']
# ---- hand-check selection (20): every kraj, all formats, both druhy, OCR + numbering-skip cases
must = [e['id'] for e in Q if e['gaps']] + [e['id'] for e in Q if e['method'].startswith('pdf_ocr')][:4]
sel = list(dict.fromkeys(must))
random.seed(11); rest = [e for e in Q if e['id'] not in sel]; random.shuffle(rest)
def cov(ids):
    E = [e for e in Q if e['id'] in ids]; return ({e['kraj'] for e in E}, {e['method'] for e in E}, {e['druh'] for e in E})
for e in sorted(rest, key=lambda e: (e['kraj'] in cov(sel)[0], e['method'] in cov(sel)[1], e['druh'] in cov(sel)[2])):
    if len(sel) >= 20: break
    k, m, d = cov(sel)
    if e['kraj'] not in k or e['method'] not in m or e['druh'] not in d or len(sel) >= 14: sel.append(e['id'])
SWAP = {'SPPRFAZWC3KIW4BM': 'SPPX6A6HLXWFW3WA', 'SPPLIRUWJVVMOPL2': 'SPPD42DZIIF7THYE', 'SPPOYVQQUH7GI7RU': 'SPPU2GMVCMH4LPIW'}  # cover all 14 kraje + more ODT
sel = [SWAP.get(i, i) for i in sel]
H = []
notes = {'SPP7BXMITG66DGX2': 'source document itself skips Čl. 7 (Čl. 6 -> Čl. 8); split follows the document',
         'SPPWSZL7KLXJ64X6': 'source document itself skips Čl. 12 (Čl. 11 -> Čl. 13); split follows the document',
         'SPPDWGXS22VCQG4O': 'source document itself jumps Čl. 8 -> Čl. 11; split follows the document',
         'SPPHBOHDXUF7NAIU': '1-page scan: OCR lost the "Čl. 1" heading (text kept in preamble)',
         'SPPE45OHSDYCCI4Y': 'weak uploader-OCR text layer (dict<0.8) -> re-OCR; "Čl. 1" and "Čl. 3" headings lost by OCR (text kept in preceding article)',
         'SPPHDQYPVQQ73EDA': 'PDF text layer with broken font encoding ("pohYebnictví", "msta") detected by dictionary check -> re-OCR; 8/8 articles',
         'SPPF5BXONS4ZHPS4': 'Strict-OOXML DOCX (purl.oclc.org namespace) - initially 0 chars, fixed with namespace-agnostic extractor'}
for i in sel:
    e = dict(next(x for x in Q if x['id'] == i))
    src_skip = i in ('SPP7BXMITG66DGX2', 'SPPWSZL7KLXJ64X6', 'SPPDWGXS22VCQG4O')
    issues = []
    if e['chars'] < 200: issues.append('empty')
    if e['dict_ratio'] < 0.85: issues.append(f"dict {e['dict_ratio']}")
    if e['garbage_ratio'] > 0.05: issues.append(f"garbage {e['garbage_ratio']}")
    if not e['articles']: issues.append('no article split')
    if e['gaps'] and not src_skip: issues.append(f"lost headings {e['gaps']}")
    if e['split_last'] != e['own_last_number']: issues.append(f"split_last {e['split_last']} != own {e['own_last_number']}")
    e['issues'] = issues; e['note'] = notes.get(i)
    e['verdict'] = 'FAIL' if ('empty' in issues or 'no article split' in issues) else ('PASS' if not issues else 'WARN')
    H.append(e)
V = collections.Counter(e['verdict'] for e in H)
json.dump(dict(generated_pt=time.strftime('%Y-%m-%d %H:%M %Z'), verdicts=dict(V), docs=H), open(f'{B}/handcheck_prerun.json', 'w'), indent=1, ensure_ascii=False)
# ---- issuer shares from listing sample
def form(ico): v = ICO.get(ico); return v['pf_name'] if v else 'unmapped'
icos = [re.search(r'IČO:\s*(\d+)', d['cells'][0]).group(1) for d in LS]
fc = collections.Counter(form(i) for i in icos)
def nm(p):
    p = p.lower()
    for k, v in [('statutární město', 'statutární město'), ('hlavní město praha', 'hl. m. Praha'), ('městys', 'městys'), ('město', 'město'), ('obec', 'obec')]:
        if k in p: return v
    return 'other'
subt = collections.Counter(nm(d['cells'][0]) for d, i in zip(LS, icos) if form(i) == 'Obec')
TOT = 78885; typed = CNT['pp_ozv'] + CNT['pp_narizeni']
issuer_est = {k: round(TOT * v / len(LS)) for k, v in fc.items()}
VUSC = {'19': 'CZ-10 Hlavní město Praha', '27': 'CZ-20 Středočeský', '35': 'CZ-31 Jihočeský', '43': 'CZ-32 Plzeňský', '51': 'CZ-41 Karlovarský', '60': 'CZ-42 Ústecký', '78': 'CZ-51 Liberecký',
        '86': 'CZ-52 Královéhradecký', '94': 'CZ-53 Pardubický', '108': 'CZ-63 Vysočina', '116': 'CZ-64 Jihomoravský', '124': 'CZ-71 Olomoucký', '141': 'CZ-72 Zlínský', '132': 'CZ-80 Moravskoslezský'}
by_kraj = dict(sorted(((VUSC[k.split('_')[-1]], v) for k, v in CNT.items() if k.startswith('pp_vusc_')), key=lambda x: -x[1]))
def wilson(k, n, z=1.96):
    p = k / n; d = 1 + z * z / n; c = p + z * z / (2 * n); h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)); return round((c - h) / d, 3), round((c + h) / d, 3)
n = len(Q); kinds = collections.Counter(e['file_kind'] for e in Q); meth = collections.Counter(e['method'] for e in Q)
ocr = [e for e in Q if e['method'].startswith('pdf_ocr')]; b = sorted(e['bytes'] for e in Q)
ocr_pages_mean = st.mean(e['pages'] for e in ocr); ocr_spp = sum(e['extract_secs'] for e in ocr) / sum(e['pages'] for e in ocr)
ocr_docs = TOT * len(ocr) / n; ocr_pages = ocr_docs * ocr_pages_mean
att_rate = sum(e['attachments'] for e in Q) / n
req_full = 1580 + TOT * 2; req_att = round(TOT * att_rate)
est = dict(population_podani=TOT, typed_ozv_narizeni=typed, other_acts=CNT['oa_all'],
  requests=dict(listing_pages=1580, detail=TOT, text=TOT, total=req_full, optional_attachments=req_att),
  runtime=dict(floor_2s_days=round(req_full * 2 / 86400, 1), measured_s_per_doc=5.4, measured_days=round((TOT * 5.4 + 1580 * 2.2) / 86400, 1),
               with_attachments_days=round((TOT * 5.4 + 1580 * 2.2 + req_att * 2.7) / 86400, 1), note='probe: 60 docs (detail + original file) in 326 s = 5.4 s/doc'),
  ocr=dict(share=round(len(ocr) / n, 3), ci95=wilson(len(ocr), n), docs=round(ocr_docs), pages=round(ocr_pages), measured_cpu_s_per_page=round(ocr_spp, 1),
           cpu_hours_measured=round(ocr_pages * ocr_spp / 3600, 1), cpu_hours_at_7s=round(ocr_pages * 7 / 3600, 1),
           wall_days_1_worker_at_7s=round(ocr_pages * 7 / 86400, 1), wall_days_2_workers_at_7s=round(ocr_pages * 7 / 2 / 86400, 1)),
  disk=dict(originals_gb=round(TOT * st.mean(b) / 1e9, 1), originals_median_based_gb=round(TOT * st.median(b) / 1e9, 1), detail_html_gz_gb=round(TOT * 10e3 / 1e9, 1),
            text_gb=round(TOT * st.mean(e['chars'] for e in Q) * 1.15 / 1e9, 2), attachments_gb='unknown (index-only by default)', parquet_gb_est='0.3-0.6', fits_box='tight if all originals kept (box ~40 GB free, shared): keep text + sha256 for all, keep originals <=1 MB and PDFs pending OCR (~5 GB)'))
G = dict(robots='PASS (HTTP 404 = no robots rules; not 5xx)', robots_evidence=f'{B}/robots/robots.txt(+.headers)',
  terms='PASS', terms_evidence=[f'{B}/terms/TERMS_EVIDENCE.md', f'{B}/terms/home.html', f'{B}/terms/tiraz_pristupnost.txt', f'{B}/terms/tiraz_zadost-o-vymaz-vkladu.txt', f'{B}/terms/blob_obsah_zakladni-informace-o-sbirce.txt', f'{B}/terms/informace_metodicke-materialy.txt'],
  terms_summary='No terms-of-use/licence page exists (footer: přístupnost, kontakty, překážky, žádost o výmaz vkladu); no clause on automated access, bulk download, registration, API key or notification. Captcha only on the e-mail notification signup (not used).',
  statute_access='zákon č. 35/2021 Sb. § 1 odst. 3: "Sbírka právních předpisů je bezplatně a neomezeně veřejně přístupná způsobem umožňujícím dálkový přístup."',
  copyright='zákon č. 121/2000 Sb. § 3 písm. a): úřední dílo - právní předpis - not protected by copyright',
  api='No SPP API/open-data dump. Site offers CSV/XLSX export of search results, but it is an asynchronous server job (/export/<token>/prubeh) that stalled at 617/78,874 rows over ~8 min -> not usable. The e-Sbírka REST API (national Sbírka zákonů, different system) requires registration via datová schránka -> not used and not needed.',
  reference_data='IČO -> kód obce/kraj from the official Czech POINT Seznam OVM XML (www.czechpoint.gov.cz, 1 request; NKOD: no copyright/database right) -> cz_sbirkapp/ref/ico_map.json')
REQ = dict(total=170, by_kind={'robots': 1, 'homepage + terms/info pages': 5, 'search page 1 + 2 forms': 3, 'count queries': 21, 'random listing pages': 12, 'detail pages': 61, 'original text files': 61, 'CSV export start + 5 progress polls': 6},
  http={'200': 168, '302': 1, '404': 1}, consecutive_403_429_503_max=0, window_pt='16:42-16:51', other_hosts='czechpoint.gov.cz x1 (Seznam OVM reference file)')
rep = dict(job='CZ municipal/regional legal acts probe - sbirkapp.gov.cz (SPP)', generated_pt=time.strftime('%Y-%m-%d %H:%M %Z'), scope='probe + 20-doc hand check; national CZ parked; nothing published',
  gate=G, requests=REQ,
  enumeration=dict(method='listing /vyhledavani/vysledek?hlavni_typ=pp&kod_vusc=<VÚSC>&page=N (50 rows/page, ~1,514 pages over 14 regions; region known from the slice) + hlavni_typ=oa (137); detail /detail/<SPPID>; original /detail/<SPPID>/text; attachments /detail/<SPPID>/prilohy/<n>',
    ids='opaque SPP IDs (SPP + 13 base32 chars); not sequential -> listing pages are required (or the stalled export)',
    counts=dict(pravni_predpisy_podani=TOT, ozv=CNT['pp_ozv'], narizeni=CNT['pp_narizeni'], untyped_or_removed=TOT - typed, platne=CNT['pp_platne'], zrusene=CNT['pp_zruseno'],
                published_by_transitional_rule_pre2022=CNT['pp_transitional'], alternate_publication=CNT['pp_alternate'], ostatni_akty=CNT['oa_all']),
    by_kraj=by_kraj, issuer_type_sample=dict(n=len(LS), by_legal_form=dict(fc), obce_subtypes_by_name=dict(subt)), issuer_type_estimate=issuer_est),
  formats=dict(sample_n=n, file_kinds=dict(kinds), methods=dict(meth), structured_note='Originals are uploaded office files: ODT 35% / DOCX 33% / PDF 25% / DOC 7% - no structured XML/HTML. ODT/DOCX/DOC give clean digital text (0 OCR); PDFs: 7/15 good text layer, 6/15 scans, 2/15 bad layers (weak uploader OCR, broken font encoding) -> OCR.',
    ocr_share=round(len(ocr) / n, 3), ocr_ci95=wilson(len(ocr), n), median_dict_ratio=st.median(e['dict_ratio'] for e in Q), max_garbage=max(e['garbage_ratio'] for e in Q),
    chars=dict(mean=round(st.mean(e['chars'] for e in Q)), median=st.median(e['chars'] for e in Q)), article_split=dict(docs_with_articles=sum(1 for e in Q if e['articles']), articles_total=sum(e['articles'] for e in Q),
    split_equals_own_numbering=sum(1 for e in Q if e['articles'] and e['split_last'] == e['own_last_number']), docs_with_gaps=sum(1 for e in Q if e['gaps'])),
    per_doc_size=dict(original_kb_mean=round(st.mean(b) / 1e3), original_kb_median=round(st.median(b) / 1e3), original_kb_p90=round(b[int(.9 * n)] / 1e3), detail_html_kb=58, attachments_per_doc=round(att_rate, 2)),
    artifact=f'{B}/index/sample_quality.json'),
  handcheck=dict(n=len(H), verdicts=dict(V), kraje=len({e['kraj'] for e in H}), methods=dict(collections.Counter(e['method'] for e in H)), druh=dict(collections.Counter(e['druh'] for e in H)),
    years=sorted({(e['vyhlaseno'] or '')[-4:] for e in H}), artifact=[f'{B}/handcheck_prerun.json', f'{B}/handcheck_prerun.md', f'{B}/handcheck_text/'],
    docs=[{k: e[k] for k in ('id', 'jurisdiction', 'publisher', 'druh', 'cislo', 'vyhlaseno', 'file_kind', 'method', 'pages', 'bytes', 'chars', 'dict_ratio', 'garbage_ratio', 'articles', 'own_last_number', 'gaps', 'verdict', 'issues', 'note')} for e in H]),
  estimates=est,
  collector_draft=dict(path='/workspace/scripts/cz_sbirkapp_collect.py', selftest='offline only: 60/60 cached docs -> 60 law rows; schema == NL hub (laws 19 cols, articles 9 cols); output cz_sbirkapp/selftest_rows.json',
    modes='selftest | full --cos-go TOKEN (refuses without cz_sbirkapp/COS_GO_FULL) | build OUTDIR', jurisdiction='CZ-<ISO 3166-2 kraj> (kraje) / CZ-<kraj>-<RÚIAN kód obce> (obce; e.g. CZ-20-539902) / CZ-10-MC<IČO> (Prague districts) / fallback CZ-<kraj>-ICO<IČO> (137 obce without ObecKod in Seznam OVM)',
    articles='one row per článek (Čl./Článek, arabic or Roman) or § (whichever matches the document own sequence); ids CZ-SPP-<SPPID>-cl-<n> / -par-<n>; OCR-tolerant headings (ČI./Cl./C13); gaps recorded',
    extraction='ODT/DOCX (incl. Strict OOXML) via XML, DOC/RTF via LibreOffice headless, PDF text layer accepted only if >=200 chars/page and cs dictionary ratio >=0.80 else tesseract ces+eng'),
  risks=['No bulk route: listing pages (~1,580 req) needed for IDs; CSV export job stalled (do not hammer it)',
    'Originals are heterogeneous office files; 13% need OCR (scans, weak OCR layers, broken PDF font encodings) - dictionary-gated text-layer check is essential',
    'DOCX automatic list numbering is not stored in XML -> odstavec/bod numbers may be missing in DOCX text (headings unaffected)',
    'Pasal/článek gaps: 3/60 documents skip numbers in the source itself; 2/60 lose headings to OCR (text not lost)',
    '"Počet podání" (78,885) includes ~3.2k entries that are neither OZV nor nařízení (removed "VYŘAZENO"/other) -> filter by druh/platnost; versions (Verze) may duplicate an act',
    'Attachments (přílohy: 10% of acts have them, 0.17 per act on average) often carry maps/tables/fee lists - index-only by default; some acts are mostly annex',
    'Original texts, not consolidated; repealed acts included (platnost) - keep law_status',
    'Prague districts / 137 obce without RÚIAN code in Seznam OVM need a secondary RÚIAN name match for full jurisdiction codes'],
  recommendation=('GO for a full run (after CoS GO): gate is clean (no robots rules, no terms, statutory free unrestricted access, no copyright on právní předpisy); volume is small (~78.9k acts, '
    '~159k requests, ~5 days at >=2 s, ~27 GB if every original is kept, ~1 GB text-only), text quality is high (median dict 0.96, 87% clean digital text, 13% OCR ~ '
    f"{est['ocr']['cpu_hours_at_7s']} CPU-h at 7 s/page). Suggested: enumerate per region (14 slices), fetch detail+text, keep text for all and originals only <=1 MB or pending OCR (~5 GB), OCR 1 worker, "
    'attachments index-only; tranche-1 = 1-2 regions (e.g. CZ-41 Karlovarský 2.1k + CZ-51 Liberecký 2.9k, ~7 h) for a build + review before the rest.'))
out = f'/workspace/country-law-triage/cz_sbirkapp_probe_{TS}'
json.dump(rep, open(out + '.json', 'w'), indent=1, ensure_ascii=False)
E = est; m = []
m.append(f"# CZ municipal/regional legal acts probe — sbirkapp.gov.cz (SPP)\n\nGenerated {rep['generated_pt']} · {rep['scope']} · JSON: `{out}.json`\n")
m.append(f"## Gate: robots, terms and licence all PASS\n- **robots.txt**: {G['robots']} — `{G['robots_evidence']}`\n- **Terms**: {G['terms_summary']} — `{G['terms_evidence'][0]}` (+ raw pages)\n- **Access by statute**: {G['statute_access']}\n- **Copyright**: {G['copyright']}\n- **API/open data**: {G['api']}\n- **Reference data**: {G['reference_data']}\n")
m.append(f"## Requests made\n- sbirkapp.gov.cz: **{REQ['total']}** ({REQ['window_pt']} PT): " + ', '.join(f'{k} {v}' for k, v in REQ['by_kind'].items()) + f"\n- HTTP {REQ['http']}; consecutive 403/429/503 max 0; at least 2 s between requests, one process\n- Other host: {REQ['other_hosts']}\n")
c = rep['enumeration']['counts']
m.append(f"## Enumeration and totals\n- **Method**: {rep['enumeration']['method']}\n- **IDs**: {rep['enumeration']['ids']}\n- **Legal regulations (podání)**: {c['pravni_predpisy_podani']:,}. OZV {c['ozv']:,} · nařízení {c['narizeni']:,} · other/removed about {c['untyped_or_removed']:,}. In force {c['platne']:,} · repealed {c['zrusene']:,}. {c['published_by_transitional_rule_pre2022']:,} are pre-2022 acts inserted under the transitional rule. Ostatní akty: {c['ostatni_akty']}\n- **By kraj**: " + ', '.join(f'{k} {v:,}' for k, v in by_kraj.items()) +
         f"\n- **Issuer type** (legal form in Seznam OVM, listing sample n={len(LS)}): " + ', '.join(f'{k} {v}' for k, v in fc.items()) + f". Obce by name: {dict(subt)}. Estimated over {TOT:,}: " + ', '.join(f'{k} ~{v:,}' for k, v in issuer_est.items()) + "\n")
f = rep['formats']
m.append(f"## Text format and OCR need (random sample of {n})\n- {f['structured_note']}\n- File kinds {f['file_kinds']}; methods {f['methods']}\n- **OCR needed: {f['ocr_share']:.1%}** (95% CI {f['ocr_ci95']}); median Czech dictionary ratio {f['median_dict_ratio']}; max garbage {f['max_garbage']}\n- Chars per act: mean {f['chars']['mean']:,}, median {f['chars']['median']:,}. Article split: {f['article_split']}\n- **Per-doc size**: original mean {f['per_doc_size']['original_kb_mean']} KB / median {f['per_doc_size']['original_kb_median']} KB / p90 {f['per_doc_size']['original_kb_p90']} KB; detail page about 58 KB; {f['per_doc_size']['attachments_per_doc']} attachments per act\n")
m.append(f"## 20-doc hand check: {V.get('PASS', 0)} PASS / {V.get('WARN', 0)} WARN / {V.get('FAIL', 0)} FAIL\nCovers {rep['handcheck']['kraje']} kraje; methods {rep['handcheck']['methods']}; {rep['handcheck']['druh']}; years published {rep['handcheck']['years'][0]}–{rep['handcheck']['years'][-1]}. dict = share of words found in hunspell cs_CZ; articles = rows from the collector splitter vs own = highest článek/§ heading in the text.\n\n| SPP id | jurisdiction | publisher | druh | č. | file | method | pp | KB | chars | dict | garbage | articles/own | gaps | verdict |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
for e in H: m.append(f"| {e['id']} | {e['jurisdiction']} | {e['publisher'][:28]} | {'OZV' if e['druh'].startswith('Obecně') else e['druh']} | {e['cislo']} | {e['file_kind']} | {e['method']} | {e['pages'] or ''} | {round(e['bytes'] / 1e3)} | {e['chars']:,} | {e['dict_ratio']} | {e['garbage_ratio']} | {e['articles']}/{e['own_last_number']} | {e['gaps'] or ''} | {e['verdict']} |")
m.append('\nNotes:\n' + '\n'.join(f"- {e['id']}: {e['note']}" for e in H if e['note']) + '\n')
m.append(f"## Full-run estimates ({TOT:,} acts)\n- **Requests**: about {E['requests']['total']:,} (1,580 listing + {TOT:,} detail + {TOT:,} originals), plus about {E['requests']['optional_attachments']:,} if attachments are included\n- **Runtime**: at least {E['runtime']['floor_2s_days']} days from the 2 s spacing; measured 5.4 s/act gives **about {E['runtime']['measured_days']} days** ({E['runtime']['with_attachments_days']} days with attachments)\n- **OCR**: about {E['ocr']['docs']:,} acts / {E['ocr']['pages']:,} pages. Measured {E['ocr']['measured_cpu_s_per_page']} CPU-s/page = {E['ocr']['cpu_hours_measured']} CPU-h; at 7 s/page {E['ocr']['cpu_hours_at_7s']} CPU-h = {E['ocr']['wall_days_1_worker_at_7s']} days with 1 worker / {E['ocr']['wall_days_2_workers_at_7s']} days with 2\n- **Disk**: originals about {E['disk']['originals_gb']} GB (median-based {E['disk']['originals_median_based_gb']} GB), detail HTML gz about {E['disk']['detail_html_gz_gb']} GB, text about {E['disk']['text_gb']} GB, parquet {E['disk']['parquet_gb_est']} GB. Keeping every original would be tight on the box, so keep text for all and originals only up to 1 MB or pending OCR.\n")
cd = rep['collector_draft']; m.append("## Collector draft (offline self-test only)\n" + '\n'.join(f'- {k}: {v}' for k, v in cd.items()) + "\n")
m.append("## Risks\n" + '\n'.join(f'- {x}' for x in rep['risks']) + f"\n\n## Recommendation\n{rep['recommendation']}\n")
open(out + '.md', 'w').write('\n'.join(m))
hm = [f"# CZ SPP hand check (pre-run): 20 acts\n\nVerdicts {dict(V)}. JSON `{B}/handcheck_prerun.json`; extracted texts `{B}/handcheck_text/`; full 60-doc metrics `{B}/index/sample_quality.json`.\n"]
hm += m[[i for i, x in enumerate(m) if x.startswith('## 20-doc')][0]:[i for i, x in enumerate(m) if x.startswith('## Full-run')][0]]
for e in H: hm.append(f"- **{e['id']}** {e['title']} — {e['publisher']} ({e['jurisdiction']}), {e['filename']}: {e['verdict']} {'; '.join(e['issues'])}")
open(f'{B}/handcheck_prerun.md', 'w').write('\n'.join(hm))
print(out, dict(V)); print(json.dumps(est, ensure_ascii=False)[:1500]); print(fc, subt)
