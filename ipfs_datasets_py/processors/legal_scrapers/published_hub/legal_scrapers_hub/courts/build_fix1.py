#!/usr/bin/env python3
"""fix-forward 1 for endomorphosis/ipfs_court_data (local only). Streams one parquet at a time."""
import os,sys,json,re,shutil,hashlib,collections
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
import pyarrow as pa,pyarrow.parquet as pq
from addrlib import is_junk,clean,recover_name
SRC='/workspace/courts/hf_stage/dataset'; OUT='/workspace/courts/hf_stage/fix1/dataset'
def gate():
    st=os.statvfs('/workspace'); free=st.f_bavail*st.f_frsize/2**30
    mem=[int(l.split()[1]) for l in open('/proc/meminfo') if l.startswith('MemAvailable')][0]/2**20
    assert free>=22,f'disk {free:.2f} GiB < 22'; assert mem>=4.5,f'mem {mem:.2f} GiB < 4.5'
PH=['phase1','phase2','phase3']; TY=['court','rule','form','judge']
SC_NOTE="sccourts.org robots.txt: Disallow: / for User-agent * (checked 2026-10-26); South Carolina records obtained only from web.archive.org id_ replay, no live fetch; Wayback-only (TERMS.md)"
ID_RULE="repo_unique_v1: first occurrence (phase order 1,2,3) keeps its id; a later duplicate gets wc1:<type>:sha256(old_id|<phase>)[:24]"
RESTORE_KEYS=['Office of the Chief Financial Officer The Supreme Court of Ohio','Supreme Court Board on Continuing Legal Education Richard J. Hughes','The Court of Appeal is located in the Victoria Avenue Courthouse','C H Smith Building, 18 Charles Street, Launceston','No 66 Marshall Street','Durham Justice Centre Green Lane','Teesside Justice Centre Teesside Magistrates','Office of the Ombudsman 6 Earlsfort Terrace']  # real addresses wrongly nulled; restored after audit
SUSPECT_NAME=re.compile(r"^(Please use the Court forms|Effective April 1, 2026)|^(Home Page|Contact Information) - Louisiana Supreme Court$")
LBL_NAME_NOTE="`name` was the generic source label (not a court name)"
st=collections.Counter(); seen=set(); ids_changed=collections.Counter()
os.makedirs(OUT,exist_ok=True)
def md(r):
    try: m=json.loads(r['metadata_json']) if r['metadata_json'] else {}
    except Exception: m={}
    return m
for ph in PH:
  for ty in TY:
    gate()
    p=f'{SRC}/data/{ph}/{ty}/part-0000.parquet'
    tb=pq.read_table(p); schema=tb.schema; rows=tb.to_pylist(); n_in=len(rows)
    srcs={r['source_name'] for r in rows} if ty=='court' else set()
    for r in rows:
        m=md(r); dirty=False
        # fix 1: repo-unique ids
        if r['id'] in seen:
            new='wc1:%s:%s'%(ty,hashlib.sha256(f"{r['id']}|{ph}".encode()).hexdigest()[:24]); assert new not in seen
            m['id_original']=r['id']; m['id_rule']=ID_RULE; r['id']=new; st[f'id_changed:{ph}/{ty}']+=1; dirty=True
        seen.add(r['id'])
        # fix 3: wayback-only SC (phase 2) / FL (phase 2)
        if ph=='phase2' and ty in('court','rule','form') and r['jurisdiction_raw'] in('US-South Carolina','US-Florida'):
            assert r['fetch_mode']=='wayback'
            m['wayback_only']=True
            if r['jurisdiction_raw']=='US-South Carolina':
                m['robots_note']=SC_NOTE; r['licence']=(r['licence'] or '')+' | '+SC_NOTE
            else: assert 'robots_note' in m and 'Wayback-only' in (r['licence'] or '')
            st[f'wayback_flagged:{r["jurisdiction_raw"]}:{ty}']+=1; dirty=True
        if ty=='court':
            # fix 4: empty phase 1 court rows
            if ph=='phase1' and not r['name'] and not r['address'] and not r['website']:
                m['empty_court_row']=True; st['empty_court_p1']+=1; dirty=True
            if ph=='phase3':
                for c in('name','address'):
                    if r[c] and '\ufeff' in r[c]: r[c]=r[c].replace('\ufeff','').strip(); st[f'bom_stripped:{c}']+=1; dirty=True
                orig_addr=r['address']
                # fix 2a: generic source-label names
                if r['name'] is not None and r['name']==r['source_name']:
                    st['label_names']+=1; rn=recover_name(orig_addr) if orig_addr else None
                    m['name_original']=r['name']
                    if rn: r['name']=rn; m['name_recovered_from']='address_prefix'; st['label_recovered']+=1
                    else: r['name']=None; m['name_is_source_label']=True; st['label_nulled']+=1
                    dirty=True
                elif r['name'] and (re.search(r'\bAct\b.*\b(19|20)\d\d\b',r['name']) or r['name'].rstrip().endswith(':') or r['name']=='[email removed]' or SUSPECT_NAME.search(r['name'])):
                    m['name_suspect']=True; st['name_suspect']+=1; dirty=True
                # fix 2b: page-junk addresses
                if orig_addr and is_junk(orig_addr):
                    c=clean(orig_addr)
                    if any(k in orig_addr for k in RESTORE_KEYS):
                        m['address_kept_after_review']=True; st['addr_restored']+=1; dirty=True
                    else:
                      m['address_junk']=True; m['address_original']=orig_addr
                    if any(k in orig_addr for k in RESTORE_KEYS): pass
                    elif c: r['address']=c; m['address_action']='extracted'; st['addr_extracted']+=1
                    else: r['address']=None; m['address_action']='nulled'; st['addr_nulled']+=1
                    dirty=True
        if ty=='judge':
            fn=r['full_name']
            if fn is not None and fn!=fn.rstrip():
                r['full_name']=fn.rstrip(); m['full_name_trimmed']=True; st[f'judge_trimmed:{ph}']+=1; dirty=True
            if ph=='phase3': st['p3_judge_rows']+=1
        if dirty: r['metadata_json']=json.dumps(m,ensure_ascii=False,sort_keys=True)
    out=pa.Table.from_pylist(rows,schema=schema)
    assert out.num_rows==n_in
    od=f'{OUT}/data/{ph}/{ty}'; os.makedirs(od,exist_ok=True)
    pq.write_table(out,f'{od}/part-0000.parquet',compression='zstd')
    st[f'rows:{ph}/{ty}']=n_in
    del tb,rows,out
p3=pq.read_table(f'{OUT}/data/phase3/court/part-0000.parquet',columns=['name','address']).to_pylist()
st['p3_court_no_name_no_addr']=sum(1 for r in p3 if r['name'] is None and r['address'] is None)
st['p3_court_addr_over120']=sum(1 for r in p3 if r['address'] and len(r['address'])>120)
j1=pq.read_table(f'{OUT}/data/phase1/judge/part-0000.parquet',columns=['full_name']).column('full_name').to_pylist()
st['p1_judge_internal_double_space']=sum(1 for n in j1 if n and '  ' in n)
# residual counts for README
json.dump(dict(st),open('/workspace/courts/hf_stage/fix1/_stats.json','w'),indent=1,sort_keys=True)
print(json.dumps(dict(st),indent=1,sort_keys=True))
