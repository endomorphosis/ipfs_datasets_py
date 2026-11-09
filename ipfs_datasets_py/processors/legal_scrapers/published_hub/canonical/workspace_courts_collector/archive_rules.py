#!/usr/bin/env python3
"""Archive recovery of state court rules via Common Crawl (CDX + WARC range). Stage only. Wayback content host unreachable (probe 2026-10-27)."""
import sys,os,json,re,time,zlib,hashlib,urllib.request,urllib.parse,datetime
sys.path.insert(0,'/workspace/courts/collector')
import us_fed as U
from us_fed import log,memguard,sid,now
O='/workspace/courts/staging/state_rules_archive';os.makedirs(O+'/files',exist_ok=True)
UA='Mozilla/5.0 (compatible; court-research-collector/0.1)'
IDX=['CC-MAIN-2026-43','CC-MAIN-2026-30','CC-MAIN-2025-51']
STATES={'TN':['tncourts.gov/rules'],'OK':['oscn.net/applications/oscn/'],'LA':['lasc.org/rules','lasc.org/Rules'],'MI':['courts.michigan.gov/rules-administrative-orders-and-jury-instructions','courts.michigan.gov/siteassets/rules-instructions-administrative-orders'],'SD':['sdlegislature.gov/Statutes/15','sdlegislature.gov/api/Statutes/15'],'DE':['courts.delaware.gov/rules','courts.delaware.gov/forms/download.aspx'],'WY':['courts.state.wy.us/court-rules','wyocourts.gov/court-rules','www.wyocourts.gov/court_rules']}
OKSEL={'OK':re.compile(r'STOKRU|ftdb=STOKRU|DocumentID',re.I)}
CAP=int(os.environ.get('ARCH_CAP','300'));DELAY=6;last=0
def get(u,rng=None,tries=5):
  global last
  for i in range(tries):
    memguard();w=last+DELAY-time.time()
    if w>0:time.sleep(w)
    last=time.time();h={'User-Agent':UA}
    if rng:h['Range']=rng
    try:return urllib.request.urlopen(urllib.request.Request(u,headers=h),timeout=120)
    except urllib.error.HTTPError as e:
      if e.code in(429,500,502,503,504):b=60*(2**i);log('BACKOFF',e.code,b,u[:100]);time.sleep(b);continue
      if e.code==404:return None
      log('HTTP_ERR',e.code,u[:120]);return None
    except Exception as e:log('NET_ERR',repr(e)[:120],u[:100]);time.sleep(30)
  return None
def cdx(idx,pat):
  u=f'https://index.commoncrawl.org/{idx}-index?'+urllib.parse.urlencode(dict(url=pat+'*',output='json',filter='status:200'))
  r=get(u)
  if not r:return
  for l in r:
    try:yield json.loads(l)
    except Exception:pass
def fetch_warc(c,fn):
  off,ln=int(c['offset']),int(c['length'])
  r=get('https://data.commoncrawl.org/'+c['filename'],rng=f'bytes={off}-{off+ln-1}')
  if not r:return None
  d=zlib.decompressobj(16+zlib.MAX_WBITS);buf=b'';hdr_done=False;h=hashlib.sha256();n=0;out=open(fn,'wb')
  while True:
    ch=r.read(65536)
    if not ch:break
    x=d.decompress(ch)
    if not hdr_done:
      buf+=x;p=buf.find(b'\r\n\r\n')
      q=buf.find(b'\r\n\r\n',p+4) if p>=0 else -1
      if q<0:continue
      x=buf[q+4:];hdr_done=True;buf=b''
    h.update(x);out.write(x);n+=len(x)
  out.close();return h.hexdigest(),n
if __name__=='__main__':
  only=sys.argv[1:] or list(STATES)
  log('ARCHIVE START pid',os.getpid(),only,'cap',CAP)
  sk=open(O+'/skips.jsonl','a');sk.write(json.dumps(dict(source='wayback',reason='web.archive.org unreachable from box (probe 2026-10-27 19:48 PT: connection fail); archive.org availability API reachable but content host not; Wayback not used'))+'\n');sk.flush()
  for st in only:
    best={}
    for idx in IDX:
      for pat in STATES[st]:
        for c in cdx(idx,pat):
          u=c['url']
          if not u.startswith('https://'):continue
          if st in OKSEL and not OKSEL[st].search(u):continue
          if not re.search(r'rule|pdf|download|Statutes|STOKRU|DocumentID',u,re.I):continue
          k=u.split('#')[0]
          if k not in best or c['timestamp']>best[k]['timestamp']:best[k]=dict(c,_idx=idx)
    log('STATE',st,'cdx unique urls',len(best))
    if not best:sk.write(json.dumps(dict(state=st,reason='no Common Crawl captures matched'))+'\n');sk.flush();continue
    n=0
    with open(f'{O}/{st}.jsonl','a') as o:
      for k,c in sorted(best.items(),key=lambda kv:kv[0])[:CAP]:
        fn=f'{O}/files/{st}_{sid(k)}';g=fetch_warc(c,fn)
        if not g:continue
        sha,nb=g;ts=c['timestamp'];cap=datetime.datetime.strptime(ts,'%Y%m%d%H%M%S').replace(tzinfo=datetime.timezone.utc).isoformat()
        o.write(json.dumps(dict(rule_id=sid(st,k),rule_set=f'{st} court rules',citation='',title='',text=None,court_id=None,subdivision_iso='US-'+st,effective_date=None,version='',file_url=k,original_url=k,file_sha256=sha,file_bytes=nb,mime=c.get('mime'),local_path=fn,content_sha256=sha,source='archive',source_url=k,fetched_at=now(),archive_source='commoncrawl',archive_timestamp=cap,archive_index=c['_idx'],warc_filename=c['filename'],warc_offset=int(c['offset']),warc_length=int(c['length']),cc_digest=c.get('digest'),license='see source terms (state-specific; archived copy)',terms_note='Common Crawl terms of use apply to archive access',robots_note='archive fetch (CC); original site robots not applicable',transport='https'))+'\n');o.flush();n+=1
    log('STATE',st,'rows',n)
  log('ARCHIVE DONE')
