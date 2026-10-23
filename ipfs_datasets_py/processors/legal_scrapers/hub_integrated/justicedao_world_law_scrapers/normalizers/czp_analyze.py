# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, importlib.util, time, re, os, collections, statistics as st, random
sp = importlib.util.spec_from_file_location('czc', '/workspace/scripts/cz_sbirkapp_collect.py'); C = importlib.util.module_from_spec(sp); sp.loader.exec_module(C)
B = '{_CORPORA}/cz_sbirkapp'
recs = [json.loads(l) for l in open(f'{B}/index/sample.jsonl')]
out = []; os.makedirs(f'{B}/handcheck_text', exist_ok=True)
for r in recs:
    p = f"{B}/docs/{r['id']}"; meta = C.parse_detail(open(f"{B}/probe/detail_{r['id']}.html", encoding='utf-8', errors='replace').read(), r['id'])
    kind = C.sniff(p); t0 = time.time(); text, method, pages = C.extract(p); secs = round(time.time() - t0, 1)
    layer_q = None
    if kind == 'pdf':
        tl = __import__('subprocess').run(['pdftotext', p, '-'], capture_output=True, text=True).stdout; layer_q = C.text_quality(tl, pages)
    q = C.text_quality(text, pages)
    arts, info = C.split_articles(text)
    rx = C.H_CL if info['scheme'] in (None, 'clanek') else C.H_PAR
    cands = C._candidates(text.split('\n'), rx); own = max([n for _, n, _, _ in cands], default=0)
    lastn = C._num(arts[-1]['num']) if arts else 0
    jur, reg = C.jurisdiction(meta.get('ico'))
    e = dict(id=r['id'], url=f"https://sbirkapp.gov.cz/detail/{r['id']}", title=meta.get('title'), publisher=re.sub(r'\s*ID DS:.*$', '', meta.get('Publikující') or ''), ico=meta.get('ico'),
             publisher_form=(reg or {}).get('pf_name'), jurisdiction=jur, kraj=(reg or {}).get('kraj'), druh=meta.get('Druh právního předpisu'), cislo=meta.get('Číslo právního předpisu'),
             vyhlaseno=(r['cells'][4] if len(r['cells']) > 4 else None), platnost=meta.get('Platnost'), file_kind=kind, filename=r.get('filename'), bytes=r.get('bytes'),
             attachments=len(meta.get('attachments', [])), pages=pages, method=method, extract_secs=secs, text_layer_quality=layer_q, **q,
             articles=len(arts), scheme=info['scheme'], gaps=info['gaps'], own_last_number=own, split_last=lastn,
             empty_articles=sum(1 for a in arts if len(a['text']) < 20), max_article_chars=max([len(a['text']) for a in arts], default=0))
    e['numbering_consistent'] = bool(arts) and lastn == own and not info['gaps']
    open(f"{B}/handcheck_text/{r['id']}.txt", 'w').write(text)
    out.append(e); print(e['id'], kind, method, pages, q['chars'], q['dict_ratio'], q['garbage_ratio'], 'art', len(arts), own, info['gaps'], jur, flush=True)
json.dump(out, open(f'{B}/index/sample_quality.json', 'w'), indent=1, ensure_ascii=False)
