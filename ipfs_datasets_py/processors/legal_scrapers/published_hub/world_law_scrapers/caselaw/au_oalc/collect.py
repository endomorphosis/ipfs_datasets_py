"""AU decisions from isaacus/open-australian-legal-corpus@ef45e3f (keyless). Streams corpus.jsonl with HTTP Range resume.
Decisions only. HCA -> au_hca (non-commercial, kept separate). FCA -> au_fca. NSW skipped (blocked_needs_benjamin). zstd parquet, 2000-row parts."""
import os,sys,json,time,shutil,logging,datetime,requests,pyarrow as pa,pyarrow.parquet as pq
REV='ef45e3fec41a960919a31149eee6dab9aa39f725'
URL=f'https://huggingface.co/datasets/isaacus/open-australian-legal-corpus/resolve/{REV}/corpus.jsonl'
BASE='/workspace/caselaw/staging/ipfs_australia_caselaw'; ST=BASE+'/state.json'
DISK=10.5e9; MEM=4.2e9; BATCH=2000
MAP={'federal_court_of_australia':'au_fca','high_court_of_australia':'au_hca'}
SKIP={'nsw_caselaw':'blocked_needs_benjamin'}
LIC={'au_fca':'Federal Court of Australia copyright (https://www.fedcourt.gov.au/copyright): judgments may be reproduced unaltered incl. commercially, acknowledged as decisions of the Court, source acknowledged; corpus compilation CC BY 4.0 (Isaacus open-australian-legal-corpus)',
     'au_hca':'NON-COMMERCIAL: High Court of Australia copyright (https://www.hcourt.gov.au/disclaimers/copyright): unaltered reproduction for personal, non-commercial or in-organisation use only, retain HCA notice; corpus compilation CC BY 4.0 (Isaacus)'}
os.makedirs(BASE,exist_ok=True)
logging.basicConfig(filename='/workspace/caselaw/logs/au_oalc.log',level=logging.INFO,format='%(asctime)s %(message)s')
def guard():
    free=shutil.disk_usage('/workspace').free
    m=int([l for l in open('/proc/meminfo') if l.startswith('MemAvailable')][0].split()[1])*1024
    if free<DISK: logging.info('DISK GUARD %.2fG stop',free/1e9); sys.exit(2)
    if m<MEM: logging.info('MEM GUARD %.2fG stop',m/1e9); sys.exit(2)
st=json.load(open(ST)) if os.path.exists(ST) else dict(offset=0,parts={},rows={},skipped={},done=False)
if st.get('done'): logging.info('already done'); sys.exit(0)
def save():
    tmp=ST+'.tmp'; json.dump(st,open(tmp,'w')); os.replace(tmp,ST)
buf={c:[] for c in MAP.values()}; pend_skip={}
def flush_all(off):
    for c,rows in buf.items():
        if not rows: continue
        os.makedirs(f'{BASE}/{c}',exist_ok=True); n=st['parts'].get(c,0)
        p=f'{BASE}/{c}/{c}.part{n:05d}.parquet'
        pq.write_table(pa.Table.from_pylist(rows),p+'.tmp',compression='zstd'); os.replace(p+'.tmp',p)
        st['parts'][c]=n+1; st['rows'][c]=st['rows'].get(c,0)+len(rows); logging.info('wrote %s rows=%d total=%d',p,len(rows),st['rows'][c]); buf[c]=[]
    for k,v in pend_skip.items(): st['skipped'][k]=st['skipped'].get(k,0)+v
    pend_skip.clear(); st['offset']=off; save(); guard()
def row(d,c):
    return dict(ecli=None,jurisdiction='au',court=d.get('source'),chamber=None,date=d.get('date'),number=None,title=d.get('citation'),text=d.get('text'),
        source_url=d.get('url'),archive_name='isaacus/open-australian-legal-corpus@'+REV[:7],is_archive=False,licence=LIC[c],
        retrieved_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),court_id=None,version_id=d.get('version_id'),
        au_jurisdiction=d.get('jurisdiction'),mime=d.get('mime'),when_scraped=d.get('when_scraped'),
        licence_flag='non_commercial' if c=='au_hca' else 'commercial_ok_unaltered_with_attribution',config=c)
guard(); logging.info('start offset=%d',st['offset'])
off=st['offset']; tries=0; S=requests.Session(); S.headers['User-Agent']='justicedao-caselaw-research/0.1'
while True:
    pos=off
    try:
        r=S.get(URL,headers={'Range':f'bytes={off}-'},stream=True,timeout=120)
        if r.status_code==416: break
        if r.status_code not in (200,206): raise Exception(f'HTTP {r.status_code}')
        if off and r.status_code==200: raise Exception('range not honoured')
        rest=b''
        for chunk in r.iter_content(1<<20):
            rest+=chunk; lines=rest.split(b'\n'); rest=lines.pop()
            for l in lines:
                pos+=len(l)+1
                if b'"decision"' not in l[:600]: continue
                d=json.loads(l)
                if d.get('type')!='decision': continue
                s=d.get('source')
                if s in SKIP: pend_skip[s]=pend_skip.get(s,0)+1; continue
                c=MAP.get(s)
                if not c: k='unknown:'+str(s); pend_skip[k]=pend_skip.get(k,0)+1; continue
                buf[c].append(row(d,c))
                if len(buf[c])>=BATCH: flush_all(pos)
            tries=0
        if rest.strip(): pos+=len(rest)  # last line without newline
        if rest.strip():
            d=json.loads(rest)
            if d.get('type')=='decision' and d.get('source') in MAP: c=MAP[d['source']]; buf[c].append(row(d,c))
        off=pos; break
    except SystemExit: raise
    except Exception as e:
        tries+=1; logging.info('ERR %s retry %d from committed offset %d',e,tries,st['offset'])
        buf={c:[] for c in MAP.values()}; pend_skip.clear(); off=st['offset']
        if tries>10: logging.info('giving up'); sys.exit(1)
        time.sleep(min(600,10*2**tries))
flush_all(off); st['done']=True; save(); logging.info('DONE rows=%s skipped=%s',st['rows'],st['skipped'])
