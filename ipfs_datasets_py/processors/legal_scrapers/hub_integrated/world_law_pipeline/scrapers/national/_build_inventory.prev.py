# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import json, csv, re
from pathlib import Path
S=Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/national'))
meta=json.load(open(S/'_collector_meta.json'))
hf=json.load(open(S/'_hf_by_cc.json'))
rc={json.loads(l)['id']:json.loads(l) for l in open(S/'hf_rowcounts.jsonl')}
R={json.loads(l)['cc']:json.loads(l) for l in open(S/'_logs/smoke/results.jsonl')}
# GB sharded parquet fix
for cc,o in hf.items():
    for ds in o['datasets']:
        r=rc.get(ds)
        if r and not r.get('laws.parquet'):
            o['laws']+=sum(v for k,v in r.items() if k.startswith('laws') and k.endswith('.parquet'))
            o['articles']+=sum(v for k,v in r.items() if k.startswith('articles') and k.endswith('.parquet'))
# Hosts that ALSO carry subnational / local law (V = seen in collector code; K = known from the portal, not exercised by collector)
LOCAL={
 'KR':'YES (law.go.kr carries 자치법규 local ordinances; collector explicitly SKIPS 조례/자치법규) [V]',
 'GB':'YES (legislation.gov.uk: UK Local Acts (ukla) + devolved Scotland/Wales/NI legislation; HF has ipfs_uk_local_acts) [K]',
 'NZ':'YES (legislation.govt.nz act/local + act/provincial classes are in collector regex) [V]',
 'ES':'YES (BOE legislación consolidada includes autonomous-community laws; ámbito autonómico) [K]',
 'AT':'YES (RIS: Landesrecht + Gemeinderecht applications) [K]',
 'DE':'PARTIAL (GII federal only; HF ipfs_germany_laws already appended Landesrecht DE-BB/NW/SN from other hosts) [V via PACK_META]',
 'BE':'YES (Justel carries regional/community decrees & ordinances) [K]',
 'NL':'YES (overheid.nl SRU also serves CVDR local regulations; HF has netherlands_municipal_laws) [K]',
 'IN':'YES (India Code hosts State Acts sections; collector does Central Acts only) [K]',
 'ID':'YES (peraturan.bpk.go.id hosts Perda regional/local regulations; collector UU only) [K]',
 'BR':'YES (LexML aggregates estadual + municipal norms; collector federal only) [K]',
 'MX':'NO on LeyesBiblio (collector notes: state/municipal not included); OJN ordenjuridico.gob.mx carries state+municipal [V/K]',
 'AR':'NO (InfoLEG national; collector: provincial excluded); SAIJ carries provincial [V]',
 'PK':'NO (collector: not provincial; provincial codes on separate punjabcode etc.) [V]',
 'EE':'YES (Riigi Teataja RT IV = local government acts) [K]',
 'LV':'YES (likumi.lv publishes municipal binding regulations) [K]',
 'LT':'YES (e-TAR includes municipal acts) [K]',
 'SI':'YES (Uradni list RS has Občine section with municipal acts) [K]',
 'HU':'YES (NJT hosts önkormányzati rendeletek / local decrees) [K]',
 'NO':'YES (Lovdata has lokale forskrifter; public dataset covers central laws) [K]',
 'RU':'YES (pravo.gov.ru / publication.pravo.gov.ru include regional acts of federal subjects) [K]',
 'KZ':'YES (adilet.zan.kz includes maslikhat/akimat regional normative acts) [K]',
 'CN':'YES (flk.npc.gov.cn includes 地方性法规 local regulations) [K]',
 'VN':'YES (vbpl.vn includes provincial-level documents) [K]',
 'KE':'YES (Kenya Law hosts county legislation) [K]',
 'PT':'PARTIAL (Diário da República includes Açores/Madeira regional legislation) [K]',
 'IT':'PARTIAL (Normattiva: national; regional laws only partially) [K]',
 'KN':'YES-ish (Nevis Island ordinances collected) [V]',
 'DM':'YES (Government Printery By-Laws category collected) [V]',
 'TC':'ordinances collected (territory-level) [V]',
 'US':'state: on HF (ipfs_state_laws, state_admin_rules); municipal handled elsewhere',
}
QMAP={'works':'works','works-discovery-only':'works (discovery only in window)','slow-no-docs-in-window':'unverified (no docs in 150s; mostly Wayback-dependent)',
      'broken':'broken','blocked':'blocked','ran-0-new-docs':'broken (ran, 0 docs)'}
rows=[]
for cc,m in sorted(meta.items()):
    r=R.get(cc,{}); h=hf.get(cc,{})
    err=' / '.join(r.get('err_sample',[])[-1:])[:160]
    notes=[]
    if r: notes.append(f"smoke: {r.get('docs',0)} docs in {r.get('seconds')}s, staged {r.get('emitted',0)}")
    if m['wayback']: notes.append('uses Wayback/CC fallbacks (web.archive.org unreachable from box 2026-10-10)')
    if r.get('status') in ('broken','blocked','ran-0-new-docs') and r.get('last_lines'): notes.append('last: '+r['last_lines'][-1][24:160])
    on_hf=f"yes: {h.get('quality')} laws={h.get('laws')} articles={h.get('articles')} raw_MB={h.get('mb')} upd={h.get('last')}" if h.get('datasets') else 'no'
    rows.append(dict(country=m['country'],CC=cc,collector=m['collector'],source=', '.join(m['hosts'][:3]),
        **{'works/broken/blocked':QMAP.get(r.get('status'),r.get('status','untested'))},coverage=m['doc'][:220],
        local_law_available=LOCAL.get(cc,'not identified'),on_HF=on_hf,notes='; '.join(notes)))
P3=json.load(open(S/'_phase3_status.json')) if (S/'_phase3_status.json').exists() else {}
for r in rows:
    p=P3.get(r['CC'])
    if not p: continue
    if p.get('status'): r['works/broken/blocked']=p['status']
    if p.get('source'): r['source']=p['source']
    if p.get('note'): r['notes']=p['note']+' | '+r['notes']
    if p.get('note_sub'): r['local_law_available']+=' | subnational '+p.get('status_sub','')+': '+p['note_sub']
with open(S/'INVENTORY.csv','w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=['country','CC','collector','source','works/broken/blocked','coverage','local_law_available','on_HF','notes'])
    w.writeheader(); [w.writerow(x) for x in rows]
json.dump(rows,open(S/'_inventory_rows.json','w'),indent=1,ensure_ascii=False)
print(len(rows))
