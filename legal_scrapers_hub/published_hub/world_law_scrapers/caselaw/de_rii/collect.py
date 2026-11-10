"""DE Rechtsprechung im Internet collector -> zstd parquet staging. Text only, 0.5 req/s, resumable."""
import os,io,re,sys,json,time,zipfile,shutil,datetime,logging
import requests,lxml.etree as ET,lxml.html as LH,pyarrow as pa,pyarrow.parquet as pq
OUT='/workspace/caselaw/staging/ipfs_germany_caselaw/de_bund'; ST='/workspace/caselaw/staging/ipfs_germany_caselaw/state.json'
TOC='https://www.rechtsprechung-im-internet.de/rii-toc.xml'; UA='justicedao-caselaw-research/0.1 (Benjamin Barber; 0.5 req/s)'
LIC='Free use and re-use (rechtsprechung-im-internet.de, BMJ/BfJ); attribution: Rechtsprechung im Internet'
DISK=10.5e9; MEM=4.2e9; BATCH=2000; GAP=2.0
logging.basicConfig(filename='/workspace/caselaw/logs/de_rii.log',level=logging.INFO,format='%(asctime)s %(message)s')
os.makedirs(OUT,exist_ok=True); S=requests.Session(); S.headers['User-Agent']=UA; last=[0.0]
def get(u):
    for a in range(8):
        w=GAP-(time.time()-last[0]); time.sleep(max(0,w)); last[0]=time.time()
        try:
            r=S.get(u,timeout=120)
            if r.status_code==200: return r.content
            if r.status_code in (403,429) or b'captcha' in r.content[:5000].lower(): logging.info('BLOCK %s %s',r.status_code,u); sys.exit(3)
            logging.info('HTTP %s %s',r.status_code,u)
            if r.status_code==404: return None
        except Exception as e: logging.info('ERR %s %s',u,e)
        time.sleep(min(600,5*2**a))
    return None
def guards():
    while True:
        free=shutil.disk_usage('/workspace').free
        if free<DISK: logging.info('DISK GUARD %.2fG stop',free/1e9); sys.exit(2)
        m=int([l for l in open('/proc/meminfo') if l.startswith('MemAvailable')][0].split()[1])*1024
        if m>=MEM: return
        logging.info('MEM GUARD %.2fG wait',m/1e9); time.sleep(60)
def txt(el):
    if el is None: return ''
    s=ET.tostring(el,encoding='unicode',method='html')
    try: return LH.fromstring('<div>'+s+'</div>').text_content().strip()
    except Exception: return ''
def parse(b,link):
    z=zipfile.ZipFile(io.BytesIO(b)); x=[n for n in z.namelist() if n.endswith('.xml')][0]
    d=ET.fromstring(z.read(x),ET.XMLParser(load_dtd=False,no_network=True,resolve_entities=False))
    g=lambda t:(d.findtext(t) or '').strip()
    parts=[]
    for t,h in [('leitsatz','Leitsatz'),('sonstosatz','Orientierungssatz'),('tenor','Tenor'),('tatbestand','Tatbestand'),('entscheidungsgruende','Entscheidungsgründe'),('gruende','Gründe'),('abwmeinung','Abweichende Meinung'),('sonstlt','Sonstiger Langtext')]:
        v=txt(d.find(t))
        if v: parts.append(h+'\n'+v)
    dt=g('entsch-datum'); dt=f'{dt[:4]}-{dt[4:6]}-{dt[6:8]}' if len(dt)==8 else dt
    court=(g('gertyp')+' '+g('spruchkoerper')).strip()
    return dict(ecli=g('ecli') or None,jurisdiction='de',court=court,chamber=g('spruchkoerper') or None,date=dt,number=g('aktenzeichen'),
        title=txt(d.find('titelzeile')) or (g('doktyp')+' '+g('aktenzeichen')).strip(),text='\n\n'.join(parts),source_url=link,
        archive_name=None,is_archive=False,licence=LIC,retrieved_at=datetime.datetime.utcnow().isoformat()+'Z',court_id=None,
        rii_doknr=g('doknr'),doctype=g('doktyp'),norm=g('norm'),config='de_bund')
def save(st):
    t=ST+'.tmp'; json.dump(st,open(t,'w')); os.replace(t,ST)
def flush(rows,st):
    if not rows: return
    fn=f'{OUT}/de_bund.part{st["part"]:05d}.parquet'; tmp=fn+'.tmp'
    pq.write_table(pa.Table.from_pylist(rows),tmp,compression='zstd'); os.replace(tmp,fn)
    st['part']+=1; st['rows']+=len(rows); st['done']=st['pending']; save(st); logging.info('wrote %s rows=%d total=%d',fn,len(rows),st['rows'])
def main():
    st=json.load(open(ST)) if os.path.exists(ST) else {'part':0,'rows':0,'done':0}
    toc=get(TOC); links=[re.sub('^http:','https:',l.decode()) for l in re.findall(rb'<link>([^<]+)</link>',toc)]
    logging.info('toc %d items, resume at %d',len(links),st['done']); rows=[]
    for i in range(st['done'],len(links)):
        guards(); b=get(links[i])
        if b:
            try: rows.append(parse(b,links[i]))
            except Exception as e: logging.info('PARSE %s %s',links[i],e)
        st['pending']=i+1
        if len(rows)>=BATCH: flush(rows,st); rows=[]
    st['pending']=len(links); flush(rows,st); st['done']=len(links); save(st); logging.info('DONE rows=%d',st['rows'])
main()
