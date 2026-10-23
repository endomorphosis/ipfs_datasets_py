#!/usr/bin/env python3
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import gzip, json
B = '{_CORPORA}/ca_subnational'
out = []
for st in 'ON MB SK NS NB NT NU'.split():
    arts = {}
    for l in gzip.open(f'{B}/parsed/{st}_articles_sample.jsonl.gz', 'rt'):
        a = json.loads(l); arts.setdefault(a['law_id'], []).append(a)
    for l in gzip.open(f'{B}/parsed/{st}_laws_sample.jsonl.gz', 'rt'):
        L = json.loads(l); m = json.loads(L['metadata_json']); nc = m['metadata']['numbering_check']; A = arts.get(L['id'], [])
        om = m['metadata']['official_metadata']; pm = om.get('page_meta', {})
        cur = pm.get('consolidation_period') if st == 'ON' else om.get('note')
        issues = []
        if not A: issues.append('0 articles (no numbered sections; full text kept on law row)')
        if nc['nonmonotonic']: issues.append(f"{nc['nonmonotonic']} non-monotonic steps (source decimal numbering, e.g. ON Rules 2.1.01 after 2.02 / NB 14.11 before 14.2)")
        if nc['int_gaps']: issues.append(f"{nc['int_gaps']} integer gaps {nc['gap_sample']} (repealed/omitted sections)")
        if L['identifier'] == om.get('src_id'): issues.append('identifier fell back to source id')
        out.append(dict(jurisdiction=L['jurisdiction'], kind=m['document_type'], law_id=L['id'], title=L['title'], identifier=L['identifier'], date=L['date'], currency_or_note=cur,
                        source_url=L['source_url'], article_count=L['article_count'], article_rows=len(A), first=nc['first'], last=nc['last'],
                        first_article=(A[0]['title'][:80] if A else None), text_chars=len(L['text']), issues=issues,
                        verdict='PASS' if A and L['article_count'] == len(A) and L['identifier'] != om.get('src_id') else ('PASS_WITH_NOTE' if L['article_count'] == len(A) else 'FAIL')))
fixes = ['SK: product format type "PDF " (trailing space) -> SK items reported no_pdf_format; match fixed and the 892 affected SK items re-fetched',
         'PDF/HTML generic splitter: two-column tables of contents poisoned the monotonic section filter (SK Land Titles Act 131 -> 220 sections); multi-start parse keeps best',
         'SK: right-margin amendment-history lines ("24 Sept 2004 SR ...") were parsed as sections; rejected (S-61.1 Reg 5: 8 -> 13 sections, 1..11)',
         'SK: section style "3(1)" without space recognised; wrapped cross-references like "26(1)(b)," rejected (NU Condominium Act 7 -> 31 sections)',
         'NT: wrapped line "Schedule A" no longer stops section parsing (NT Financial Administration Act 34 -> 187 sections); NT/NU margin-note lines handled',
         'ON: e-Laws Y* classes (amendments not yet in force) excluded so rows reflect current in-force text (HTA duplicate section numbers 6 -> 0); integer numbering restarts inside schedules/agreements kept as schedule articles',
         'MB: control characters in some HTML broke lxml (7 acts incl. Income Tax Act, Planning Act); stripped. Convention/agreement schedules with restarted numbering stored as schedule articles',
         'NB: section ids 8_1 -> 8.1; identifiers prefixed (S.N.B. / N.B. Reg.)',
         'NT/NU: base citation = earliest citation in raw PDF header (was amendment or enabling-act citation); NU consolidation date parsed',
         'NU: bilingual two-column PDFs (199/620) -> English (left) column only; listing now includes nested regulations (200 acts-only -> 223 acts + 397 regs)',
         'NS: regulation identifier trimmed to base "N.S. Reg. X/YYYY"; statute citation built from "CHAPTER n OF THE REVISED STATUTES, yyyy"; long repealed ranges allowed (Community Colleges Act 1 -> many sections)',
         'PDF running footers with page tokens + citation (e.g. "81 R.S.N.W.T. 1988,c.M-16") removed']
json.dump(dict(generated='2026-10-01 PT', n=len(out), laws=out, summary={v: sum(1 for x in out if x['verdict'] == v) for v in ('PASS', 'PASS_WITH_NOTE', 'FAIL')},
               fixes_applied_after_first_pass=fixes), open(f'{B}/handcheck_20.json', 'w'), indent=1, ensure_ascii=False)
for x in out: print(x['verdict'], x['jurisdiction'], x['kind'], '|', x['title'][:45], '|', x['identifier'], '|', x['date'], '|', x['article_count'], x['first'], x['last'])
