# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, collections, statistics as st, math, time, os
B='{_CORPORA}/id_bpk'; TS=time.strftime('%Y%m%dT%H%M%S')
L=json.load(open(f'{B}/index/sitemap_details_classified.json')); RC=json.load(open(f'{B}/ref/region_codes.json'))
S=[e for e in json.load(open(f'{B}/index/sample_layer.json'))]; ok=[e for e in S if e.get('pages')]
H=json.load(open(f'{B}/handcheck_prerun.json'))
lvl=collections.Counter(d.get('lvl') for d in L)
typ=collections.Counter(f"{d.get('type')}-{d.get('lvl')}" for d in L if d.get('lvl') in ('prov','kab','kota'))
provnames={c:n for c,n in [l.strip().split(',',1) for l in open(f'{B}/ref/provinces.csv')]}
provnames.update({'93':'PAPUA SELATAN','94':'PAPUA TENGAH','95':'PAPUA PEGUNUNGAN','96':'PAPUA BARAT DAYA'})
byprov=collections.Counter()
for k,v in RC['map'].items(): byprov[v['code'][:2]]+=v['docs']
N=lvl['prov']+lvl['kab']+lvl['kota']
def wilson(k,n,z=1.96):
    p=k/n; d=1+z*z/n; c=p+z*z/(2*n); h=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n)); return round((c-h)/d,3), round((c+h)/d,3)
nl=len(ok); n_tl=sum(e['layer']=='text_layer' for e in ok); n_emb=sum(e['layer']=='text_layer' and e['embedded_ocr_suspect'] for e in ok)
n_scan=sum(e['layer']=='scan' for e in ok); n_poor=sum(e['layer']=='mixed_or_poor_text' for e in ok); n_ocr=n_scan+n_poor
weak=[e for e in ok if e['layer']=='text_layer' and e['dict_ratio']<0.85]
b=sorted(e['pdf_bytes'] for e in ok); pg=sorted(e['pages'] for e in ok)
ocrpages_mean=st.mean(e['pages'] for e in ok if e['layer']!='text_layer')
weak_pages_mean=st.mean(e['pages'] for e in weak if e['pages']<1000)
dl_per_doc=sum(e['n_downloads'] for e in S)/len(S); req_per_doc=1+dl_per_doc
sec_doc_meas=round((16*60+3.5-(15*60+55.7))*60/60,1)  # 60 docs 15:55:44 -> 16:03:30
ocr_docs=N*n_ocr/nl; ocr_pages=ocr_docs*ocrpages_mean; reocr_pages=N*len(weak)/nl*weak_pages_mean
def days(cpu_s, w): return round(cpu_s/w/86400,1)
est=dict(
 population_regional=N, statistik_daerah=268443,
 requests_per_doc=round(req_per_doc,3), requests_total=round(N*req_per_doc), 
 fetch_runtime=dict(floor_2s_spacing_days=round(N*req_per_doc*2/86400,1), measured_s_per_doc=sec_doc_meas, measured_based_days=round(N*sec_doc_meas/86400,1),
                    note='probe measured 60 docs (detail+PDF) in 466 s = 7.8 s/doc (2 s floor + PDF transfer, mean 4.6 MB); 2 s floor alone = 4.0 s/doc'),
 transfer_tb=dict(mean_based=round(N*st.mean(b)/1e12,2), trimmed_excl_largest=round(N*st.mean(b[:-1])/1e12,2), median_based=round(N*st.median(b)/1e12,2)),
 ocr=dict(needs_ocr_share=round(n_ocr/nl,3), needs_ocr_ci95=wilson(n_ocr,nl), docs=round(ocr_docs), pages=round(ocr_pages), cpu_s_per_page_assumed=7,
          cpu_days=round(ocr_pages*7/86400,1), wall_days_1_worker=days(ocr_pages*7,1), wall_days_2_workers=days(ocr_pages*7,2),
          measured='hand check: 123 OCR pages; normal scans 6.1 CPU-s/page (3.1 s wall @2 workers); phone-scan PDF with oversized page box 14 CPU-s/page incl. native-image fallback',
          optional_reocr_weak_embedded=dict(share=round(len(weak)/nl,3), pages=round(reocr_pages), cpu_days=round(reocr_pages*7/86400,1), wall_days_2_workers=days(reocr_pages*7,2))),
 disk=dict(full_pdf_set_tb=round(N*st.mean(b[:-1])/1e12,2), box_free_gb=40, plan='stream: keep text (+gz detail HTML) only; delete PDF after text extraction unless queued for OCR (queue cap 8 GB, IDB_OCRQ_GB)',
           text_gb_raw=round(N*st.mean(pg[:-1])*1.4e3/1e9,1), text_gb_gz=round(N*st.mean(pg[:-1])*1.4e3/1e9/3.5,1), detail_html_gz_gb=round(N*9e3/1e9,1), parquet_gb_est='3-6', peak_gb_est='15-25'))
hc=[dict(id=e['id'],type=e['type'],lvl=e['lvl'],region=e['region'],jurisdiction=RC['map'][f"{e['lvl']}:{e['region']}"]['jurisdiction'],year=e['year'],title=e.get('title'),
         pages=e['pages'],pdf_bytes=e['pdf_bytes'],method=e['method'],chars=e['final']['chars'],chars_per_page=e['final']['chars_per_page'],dict_ratio=e['final']['dict_ratio'],
         garbage_ratio=e['final']['garbage_ratio'],pasal_split=e['split_articles'],pasal_own_last=e['own_last_number'],pasal_gaps=e['split_gaps'],empty=e['empty'],
         truncated_suspect=e['truncated_suspect'],verdict=e['verdict'],issues=e['issues'],embedded_vs_tesseract_p1_3=({'embedded_dict':e['cmp']['embedded']['dict_ratio'],'tesseract_dict':e['cmp']['tesseract']['dict_ratio']} if e.get('cmp') else None),
         ocr_secs=e.get('ocr_secs'),pdf_url=e.get('pdf_url')) for e in H]
manual={125468:'manual review: split is CORRECT (5 Pasal); Pasal 5 heading is OCR-misread "Pasa15" in the embedded layer so the clean-heading check sees max 4 -> effectively PASS',
        34028:'amending Perda (Perubahan Kedua): "Pasal I" OCR-read as "Pasal 1" and "Pasal II" lost in weak embedded OCR layer (dict 0.79; tesseract 0.92 on p1-3) -> all amendments land in one article row; fix = re-OCR weak embedded layers + title-based amending detection',
        215305:'weak embedded OCR layer (dict 0.64; tesseract re-OCR 0.94 on p1-3); 2 headings lost -> re-OCR would fix',
        293823:'scan; tesseract lost the "Pasal 5" heading at a page break (text kept inside Pasal 4); 13/14 split, gap recorded',
        341227:'born-digital/embedded layer missing the "Pasal 16" heading line; 27/28 split, gap recorded',
        225354:'1st OCR pass failed on 56/69 pages (phone-scanner PDF, oversized page box); native-image fallback -> 69/69 pages, dict 0.94; 77/82 headings found, 5 gaps (OCR)'}
for r in hc:
    if r['id'] in manual: r['manual_note']=manual[r['id']]
verd=collections.Counter(r['verdict'] for r in hc)
rep=dict(job='ID regional regulations probe - peraturan.bpk.go.id (JDIH BPK)', generated_pt=time.strftime('%Y-%m-%d %H:%M %Z'), cos_go='probe only, 2026-10-04 15:49 PT',
 gate=dict(robots='PASS', robots_evidence=f'{B}/robots/robots.txt', robots_summary='Disallow only /Admin/ /Identity/ /Account/ /Manage/ /health /Error; no Crawl-delay; Sitemap /sitemap.xml',
  terms='PASS', terms_evidence=[f'{B}/terms/TERMS_EVIDENCE.md',f'{B}/terms/home.html',f'{B}/terms/home.txt'],
  terms_summary="no separate Ketentuan/Syarat page; footer: access 'secara gratis dan tanpa syarat'; DISCLAIMER = accuracy only; (c) Badan Binbangkum BPK (site); no scraping/bulk prohibition, no registration/contact requirement",
  copyright='UU 28/2014 Hak Cipta Pasal 42: no copyright on peraturan perundang-undangan (Perda/Pergub/Perbup/Perwal are peraturan perundang-undangan per UU 12/2011 Pasal 7-8) -> public-domain text; cite source + issuing authority',
  api_bulk='no public API or bulk dump on BPK; data.go.id none; JDIHN jdihn.go.id/api/search = public metadata API on another host, NOT contacted (optional cross-check)'),
 requests=dict(total=213, by_kind={'robots':1,'homepage/terms':1,'sitemaps+Statistik/Jenis/Perwakilan':86,'detail pages + search/list pages':65,'PDF downloads':60},
  http={'200':211,'404':1,'520':1}, consecutive_403_429_503_max=0, spacing='>=2.0 s between request starts, single process, honest UA', window_pt='15:50-16:05'),
 enumeration=dict(method='year sitemaps from /sitemap.xml (83 year files) -> 309,878 /Details/<id>/<slug> URLs; slug regex <type>-(prov|kab|kota)-<region>-no-<n>-tahun-<yyyy> classifies type/level/region; detail page -> /Download/<fileid>/<name>.pdf (file id != detail id; 59/60 one file, 1/60 two)',
  search_listing='/Search?jenis=<id> (19 Perda, 20 Pergub, 23 Perbup, 30 Perwali, 34 Qanun, 35 Perdasus Papua, 38 Perdais), 10-20 results/page via &p=N, HARD CAP 10,000 results per query -> not usable for full enumeration; /List?id=<perwakilan> gives per kab/kota x year counts',
  statistik={'daerah':268443,'daerah_berlaku':248163,'daerah_tidak_berlaku':20280,'pusat':17375,'kementerian_lembaga':24057,'bpk':49},
  sitemap_by_level=dict(lvl), regional_by_type=dict(typ.most_common()), sitemap_regional_total=N, sitemap_vs_statistik_gap=268443-N,
  regions=dict(total=len(RC['map']), prov=sum(k.startswith('prov:') for k in RC['map']), kab=sum(k.startswith('kab:') for k in RC['map']), kota=sum(k.startswith('kota:') for k in RC['map'])),
  by_province={f'ID-{c} {provnames.get(c,c)}':n for c,n in byprov.most_common()}),
 sample=dict(n=len(S), design='stratified random by type/level, distinct regions, seed 20261004', pdf_ok=nl, pdf_failed={'520':1,'404':1},
  text_layer=n_tl, of_which_born_digital=n_tl-n_emb, of_which_embedded_ocr_layer=n_emb, scan_no_text=n_scan, poor_text_layer=n_poor,
  usable_text_layer_share=round(n_tl/nl,3), needs_ocr_share=round(n_ocr/nl,3), needs_ocr_ci95=wilson(n_ocr,nl), weak_embedded_layer_share=round(len(weak)/nl,3),
  text_layer_median_dict_ratio=st.median(e['dict_ratio'] for e in ok if e['layer']=='text_layer'), text_layer_median_chars_per_page=st.median(e['chars_per_page'] for e in ok if e['layer']=='text_layer'),
  pdf_mb=dict(mean=round(st.mean(b)/1e6,2), median=round(st.median(b)/1e6,2), p90=round(b[int(.9*len(b))]/1e6,2), max=round(b[-1]/1e6,1)),
  pages=dict(mean=round(st.mean(pg),1), mean_excl_largest=round(st.mean(pg[:-1]),1), median=st.median(pg), p90=pg[int(.9*len(pg))], max=pg[-1]),
  per_doc_fetch=dict(detail_html_kb=43, pdf_mb_mean=round(st.mean(b)/1e6,2), pdf_mb_median=round(st.median(b)/1e6,2)), artifact=f'{B}/index/sample_layer.json'),
 handcheck=dict(n=len(hc), verdicts=dict(verd), provinces=len({r['jurisdiction'].split('-')[1] for r in hc}), years=sorted({r['year'] for r in hc}), docs=hc,
  ocr_docs=sum(r['method'].startswith('ocr') for r in hc), artifact=[f'{B}/handcheck_prerun.json', f'{B}/handcheck_prerun.md', f'{B}/handcheck_text/']),
 estimates=est,
 collector_draft=dict(path='/workspace/scripts/id_bpk_collect.py', modes='selftest | sample N(<=200) | full --cos-go TOKEN (refuses without id_bpk/COS_GO_FULL) | ocr | build', schema='national hub schema copied from NL staging parquet (laws 19 cols, articles 9 cols)',
   jurisdiction='ID-<BPS prov> / ID-<prov>-<BPS kab/kota 2-digit>, e.g. ID-33 Jawa Tengah, ID-33-01 Kab. Cilacap; map id_bpk/ref/region_codes.json, 557/557 region slugs mapped (pre-2022 BPS list + Papua 93-96 added)',
   articles='Pasal-level rows <law_id>-pasal-<n>, OCR-tolerant heading matcher guided by own numbering; amending regs split on Pasal I/II; gaps recorded in metadata', not_run_full=True),
 risks=['Volume/bandwidth: ~1.1-1.2 TB of PDF transfer over ~3-4 weeks from a government site; polite but long-running',
  'Disk: full PDF set does not fit (box ~40 GB free) -> must stream (text-only retention); OCR queue must stay bounded',
  'OCR CPU: ~10% scans (CI 5-21%) -> ~45 CPU-days at 7 s/page; shares CPU with NL-M; phone-scanner PDFs need native-image fallback (2x cost)',
  '~57% of PDFs carry uploader-made embedded OCR of uneven quality; ~12% weak (dict<0.85) -> Pasal headings lost unless re-OCR (+~55 CPU-days)',
  'Pasal split is heuristic on OCR text: 14/20 PASS; 6/20 WARN (4 with 1-5 OCR-lost Pasal headings, gaps recorded, text kept; 1 amending Perda collapsed to one row; 1 false alarm)',
  'Rare 5xx (1x 520) and 404 PDFs (1/60 each) -> retry pass + index-only rows',
  'Sitemap (267,673 regional) vs /Statistik (268,443): ~770 regional docs not in sitemaps or not classifiable by slug (~0.3%)',
  'Very large APBD Perda (e.g. 4,070 pages) inflate pages/bytes; consider cap/skip of lampiran-only mega-PDFs for OCR'],
 recommendation=('LIMITED GO recommended: (1) metadata-first pass of all ~268k detail pages (~268k req, ~6-7 days at 2 s) -> complete index with status/T.E.U./dates; '
  '(2) PDF+text in tranches by province (streaming, text-only retention, OCR queue <=8 GB, 2 OCR workers), starting with 2-3 provinces (~30-40k docs, ~3-4 days) for a tranche-1 build + review; '
  'then continue province by province. Full PDF run as one block (~3-4 weeks, ~1.1 TB) only after tranche-1 review. Gate/terms are clean; data quality is good (90% usable text layer, median dict 0.94).')
)
out=f'/workspace/country-law-triage/id_bpk_probe_{TS}'
json.dump(rep,open(out+'.json','w'),indent=1,ensure_ascii=False)
# --- md ---
E=est; m=[]
m.append(f"# ID regional regulations probe — peraturan.bpk.go.id (JDIH BPK)\n\nGenerated {rep['generated_pt']} · CoS GO: probe only (15:49 PT) · JSON: `{out}.json`\n")
g=rep['gate']; m.append(f"## Gate: robots and terms both PASS\n- **robots.txt**: {g['robots_summary']} — `{g['robots_evidence']}`\n- **Terms**: {g['terms_summary']} — `{g['terms_evidence'][0]}` (+ home.html/home.txt)\n- **Copyright**: {g['copyright']}\n- **API/bulk**: {g['api_bulk']}\n")
r=rep['requests']; m.append(f"## Requests made to the host\n- Total **{r['total']}** ({r['window_pt']} PT): " + ', '.join(f'{k} {v}' for k,v in r['by_kind'].items()) + f"\n- HTTP: {r['http']}; consecutive 403/429/503 max = 0; {r['spacing']}\n")
en=rep['enumeration']; m.append(f"## Enumeration and yield\n- **Method**: {en['method']}\n- **Search/listing pages**: {en['search_listing']}\n- **/Statistik**: Daerah {en['statistik']['daerah']:,} ({en['statistik']['daerah_berlaku']:,} berlaku / {en['statistik']['daerah_tidak_berlaku']:,} tidak), Pusat {en['statistik']['pusat']:,}, K/L {en['statistik']['kementerian_lembaga']:,}, BPK {en['statistik']['bpk']}\n- **Sitemap detail URLs by level**: kab {lvl['kab']:,} · kota {lvl['kota']:,} · prov {lvl['prov']:,} → regional **{N:,}**; pusat/other {lvl['pusat_or_other']:,}\n- **Regional by type**: " + ', '.join(f'{k} {v:,}' for k,v in list(typ.most_common())[:14]) + f"\n- **Regions**: {en['regions']['total']} (prov {en['regions']['prov']}, kab {en['regions']['kab']}, kota {en['regions']['kota']}), all mapped to BPS codes\n- **Top provinces (sitemap docs)**: " + ', '.join(f'{k} {v:,}' for k,v in list(en['by_province'].items())[:10]) + "\n")
s=rep['sample']; m.append(f"## Completeness and text layer (stratified sample of {s['n']})\n- PDFs fetched OK {s['pdf_ok']}/60 (1× HTTP 520, 1× 404)\n- **Usable text layer {s['text_layer']}/{s['pdf_ok']} ({s['usable_text_layer_share']:.0%})**: {s['of_which_born_digital']} born-digital, {s['of_which_embedded_ocr_layer']} scans that already carry an embedded OCR layer; median dictionary ratio {s['text_layer_median_dict_ratio']}, median {s['text_layer_median_chars_per_page']} chars/page\n- **Needs OCR: {s['scan_no_text']} pure scans + {s['poor_text_layer']} poor layers = {s['needs_ocr_share']:.1%}** (95% CI {s['needs_ocr_ci95']}); weak embedded layers (dict <0.85) {s['weak_embedded_layer_share']:.0%} (optional re-OCR)\n- **PDF size** mean {s['pdf_mb']['mean']} MB / median {s['pdf_mb']['median']} MB / p90 {s['pdf_mb']['p90']} MB / max {s['pdf_mb']['max']} MB; **pages** median {s['pages']['median']}, mean {s['pages']['mean_excl_largest']} (excluding one 4,070-page APBD Perda), p90 {s['pages']['p90']}\n- Per-doc fetch: detail page ~43 KB + PDF(s) (59/60 one file)\n")
h=rep['handcheck']; m.append(f"## 20-doc hand check: {h['verdicts'].get('PASS',0)} PASS / {h['verdicts'].get('WARN',0)} WARN / {h['verdicts'].get('FAIL',0)} FAIL\nCovers {h['provinces']} provinces and years {h['years'][0]}–{h['years'][-1]}. {h['ocr_docs']} docs were OCR'd with tesseract ind+eng; the rest use the PDF text layer. Pasal = article rows from the collector splitter vs the highest clean 'Pasal n' heading in the document.\n\n| id | type | jurisdiction | year | pages | method | chars | chars/pg | dict | garbage | Pasal split/own | gaps | verdict |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|")
for x in hc: m.append(f"| {x['id']} | {x['type']}-{x['lvl']} | {x['jurisdiction']} | {x['year']} | {x['pages']} | {'OCR' if x['method'].startswith('ocr') else 'text layer'} | {x['chars']:,} | {x['chars_per_page']} | {x['dict_ratio']} | {x['garbage_ratio']} | {x['pasal_split']}/{x['pasal_own_last']} | {x['pasal_gaps'] or ''} | {x['verdict']} |")
m.append("\nNotes on the WARN docs:\n" + '\n'.join(f"- {k}: {v}" for k,v in manual.items()))
m.append("\nEmbedded OCR layer vs fresh tesseract (pages 1–3, dictionary ratio): " + '; '.join(f"{x['id']} {x['embedded_vs_tesseract_p1_3']['embedded_dict']}→{x['embedded_vs_tesseract_p1_3']['tesseract_dict']}" for x in hc if x['embedded_vs_tesseract_p1_3']) + ". Tesseract is equal or better, and much better on weak layers.\nEmpty documents: 0. Truncated (no closing formula): 0.\n")
m.append(f"## Estimates for a full regional run ({N:,} docs)\n- **Requests**: about {E['requests_total']:,} ({E['requests_per_doc']}/doc: one detail page plus PDFs). Sitemaps are already done.\n- **Fetch runtime**: at least {E['fetch_runtime']['floor_2s_spacing_days']} days from the 2 s spacing alone. Measured {E['fetch_runtime']['measured_s_per_doc']} s/doc including PDF transfer gives **about {E['fetch_runtime']['measured_based_days']} days**. A metadata-only pass would take about {round(N*2.3/86400,1)} days.\n- **Transfer**: about {E['transfer_tb']['trimmed_excl_largest']}–{E['transfer_tb']['mean_based']} TB of PDFs (median-based {E['transfer_tb']['median_based']} TB).\n- **OCR, scans only**: about {E['ocr']['docs']:,} docs / {E['ocr']['pages']:,} pages × 7 CPU-s = **{E['ocr']['cpu_days']} CPU-days**. That is {E['ocr']['wall_days_1_worker']} days wall with 1 worker or **{E['ocr']['wall_days_2_workers']} days with 2 workers**, which keeps pace with fetching. {E['ocr']['measured']}.\n- **Optional re-OCR of weak embedded layers**: about {E['ocr']['optional_reocr_weak_embedded']['pages']:,} pages, +{E['ocr']['optional_reocr_weak_embedded']['cpu_days']} CPU-days ({E['ocr']['optional_reocr_weak_embedded']['wall_days_2_workers']} days with 2 workers).\n- **Disk**: the full PDF set (about {E['disk']['full_pdf_set_tb']} TB) does **not** fit; the box has about 40 GB free. {E['disk']['plan']}. Text about {E['disk']['text_gb_raw']} GB raw / {E['disk']['text_gb_gz']} GB gz, detail HTML gz about {E['disk']['detail_html_gz_gb']} GB, parquet {E['disk']['parquet_gb_est']} GB, peak about {E['disk']['peak_gb_est']} GB.\n")
m.append("## Collector draft (not run in full)\n" + '\n'.join(f"- {k}: {v}" for k,v in rep['collector_draft'].items()) + "\n")
m.append("## Risks\n" + '\n'.join(f"- {x}" for x in rep['risks']) + f"\n\n## Recommendation\n{rep['recommendation']}\n")
open(out+'.md','w').write('\n'.join(m))
# handcheck md
hm=[f"# ID BPK hand check (pre-run): 20 regional documents\n\nVerdicts {dict(verd)}. Source JSON `{B}/handcheck_prerun.json`; texts in `{B}/handcheck_text/`.\nMetrics: dict = share of alphabetic tokens found in the hunspell id_ID dictionary (spylls) or the English wordlist; garbage = share of junk tokens; Pasal split = rows from id_bpk_collect.split_pasal; own = highest clean 'Pasal n' heading in the text.\n"]
hm+= m[m.index(next(x for x in m if x.startswith('## 20-doc'))):m.index(next(x for x in m if x.startswith('## Estimates')))]
for x in hc: hm.append(f"- **{x['id']}** {x['title']} ({x['jurisdiction']}, {x['pages']} pp, {x['pdf_bytes']/1e6:.1f} MB): {x['verdict']} {'; '.join(x['issues'])} {x.get('manual_note','')}")
open(f'{B}/handcheck_prerun.md','w').write('\n'.join(hm))
print(out); print(json.dumps(est,indent=0)[:2500]); print(verd)
