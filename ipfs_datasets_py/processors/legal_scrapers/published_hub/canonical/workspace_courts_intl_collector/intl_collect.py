#!/usr/bin/env python3
"""Intl courts collector (light, live official sites only, stage only). GO: COS_GO_COURTS_INTL_20261102"""
import os,sys,re,json,time,html,hashlib,io,zipfile,shutil,urllib.request,urllib.error,urllib.parse,urllib.robotparser
import xml.etree.ElementTree as ET
ROOT='/workspace/courts/intl'; ST=ROOT+'/staging'; sys.path.insert(0,ROOT+'/collector'); LOG=ROOT+'/logs/intl_collect.log'
UA='ipfs_datasets_py-courts/1.0 (justicedao research; polite 1req/10s)'
MINGAP=10.0; MEMFLOOR=4.2; STRIKES=3; DISKMIN=10.0
last={}; stopped=set(); robots={}; strikes=0
def log(*a):
    s=time.strftime('%Y-%m-%dT%H:%M:%S%z')+' '+' '.join(str(x) for x in a)
    open(LOG,'a').write(s+'\n')
def memavail():
    for l in open('/proc/meminfo'):
        if l.startswith('MemAvailable'): return int(l.split()[1])/1048576
def guard():
    global strikes
    if shutil.disk_usage('/workspace').free/1e9<DISKMIN: finish('STOPPED_INTL','disk<10G')
    m=memavail()
    if m<MEMFLOOR:
        strikes+=1; log('MEMSTRIKE',strikes,'%.2fG'%m)
        if strikes>=STRIKES: finish('STOPPED_INTL','memguard %.2fG'%m)
        time.sleep(60)
    else: strikes=0
class HostStop(Exception): pass
def rp(host,scheme):
    if host not in robots:
        r=urllib.robotparser.RobotFileParser()
        try:
            req=urllib.request.Request(f'{scheme}://{host}/robots.txt',headers={'User-Agent':UA})
            body=urllib.request.urlopen(req,timeout=30).read().decode('utf-8','ignore'); r.parse(body.splitlines())
        except Exception: r.parse([])
        last[host]=time.time(); robots[host]=r
    return robots[host]
def fetch(url,binary=False):
    guard()
    u=urllib.parse.urlparse(url); host=u.netloc
    if host in stopped: raise HostStop(host)
    r=rp(host,u.scheme)
    if not r.can_fetch(UA,url): log('ROBOTS_DISALLOW',url); return None
    gap=max(MINGAP,float(r.crawl_delay(UA) or 0))
    w=last.get(host,0)+gap-time.time()
    if w>0: time.sleep(w)
    last[host]=time.time()
    try:
        resp=urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':UA}),timeout=60)
        data=resp.read(); final=resp.geturl()
    except urllib.error.HTTPError as e:
        if e.code in (403,429): stopped.add(host); log('HOST_STOP',host,e.code,url); raise HostStop(host)
        log('HTTP',e.code,url); return None
    except Exception as e: log('ERR',type(e).__name__,url); return None
    if not binary:
        t=data[:20000].decode('utf-8','ignore').lower()
        if any(k in t for k in ('captcha','cf-challenge','just a moment...','attention required','are you a robot')):
            stopped.add(host); log('HOST_STOP_CHALLENGE',host,url); raise HostStop(host)
    return data,final
def txt(b):
    t=html.unescape(re.sub(r'(?s)<script.*?</script>|<style.*?</style>','',b if isinstance(b,str) else b.decode('utf-8','ignore')))
    return re.sub(r'\s+',' ',re.sub('<[^>]+>',' ',t)).strip()
sha=lambda b:hashlib.sha256(b if isinstance(b,bytes) else b.encode()).hexdigest()
now=lambda:time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
def base(cc,sub,url,pub,lang,b=None):
    return dict(country_iso=cc,subdivision_iso=sub,source_url=url,publisher=pub,official='y',transport=urllib.parse.urlparse(url).scheme,
                retrieved_at=now(),sha256=sha(b) if b is not None else None,source='live',coverage='complete',language=lang)
class Out:
    def __init__(s,cc):
        s.d=f'{ST}/{cc}'; os.makedirs(s.d,exist_ok=True); s.ck=s.d+'/ckpt.json'
        s.state=json.load(open(s.ck)) if os.path.exists(s.ck) else {'done_tasks':[]}
    def w(s,cfg,row): open(f'{s.d}/{cfg}.jsonl','a').write(json.dumps(row,ensure_ascii=False)+'\n')
    def done(s,t): return t in s.state['done_tasks']
    def mark(s,t,cov='complete'):
        s.state['done_tasks'].append(t); s.state.setdefault('coverage',{})[t]=cov; json.dump(s.state,open(s.ck,'w'),indent=1)
def task(o,name,fn):
    if o.done(name): log('SKIP_DONE',name); return
    log('TASK_START',name)
    try: cov=fn() or 'complete'
    except HostStop as h: cov='partial_host_stopped'; log('TASK_HOSTSTOP',name,h)
    o.mark(name,cov); log('TASK_END',name,cov)
# ---------------- GB
def gb_courts(o):
    B='https://www.find-court-tribunal.service.gov.uk'; slugs=set()
    for q in ['court','tribunal','centre','justice','hearing','house','office','law','county','magistrates','crown','family']:
        r=fetch(f'{B}/courts?search={q}')
        if r: slugs|=set(re.findall(r'href="/courts/([a-z0-9-]+)"',r[0].decode('utf-8','ignore')))
    log('GB slugs',len(slugs))
    for s in sorted(slugs):
        r=fetch(f'{B}/courts/{s}')
        if not r: continue
        b=r[0].decode('utf-8','ignore'); t=txt(b)
        m=re.search(r'<h1[^>]*>(.*?)</h1>',b,re.S); name=txt(m.group(1)) if m else s
        from gb_geo import sub_from,parse_addresses
        addrs,ll=parse_addresses(b); pc=next((x['postal_code'] for x in addrs if x.get('postal_code')),None)
        sub,how=sub_from(pc,t)
        cid=f'GB-{sub[3:]}-{s}'
        lvl='tribunal' if 'ribunal' in name else ('first_instance')
        o.w('courts',{**base('GB',sub,f'{B}/courts/{s}','HMCTS','en',b),'court_id':cid,'name':name,'name_en':name,'level':lvl,'jurisdiction_type':None,'parent_court_id':None,'subdivision_method':how})
        for i,x in enumerate(addrs):
            o.w('courthouses',{**base('GB',sub,f'{B}/courts/{s}','HMCTS','en',b),'courthouse_id':cid+('-visit' if i==0 else f'-addr{i+1}'),'court_id':cid,'name':name,
                'street':x['street'],'locality':x['locality'],'postal_code':x['postal_code'],'region':sub,'lat':ll[0] if i==0 else None,'lon':ll[1] if i==0 else None,'phone':None,'email':None,'address_source':x['kind']})
def gb_forms(o):
    r=fetch('https://www.gov.uk/api/content/government/collections/court-and-tribunal-forms')
    if not r: return 'blocked'
    j=json.loads(r[0]); docs=[]
    for k,v in j.get('links',{}).items():
        if k=='documents': docs+= [d['base_path'] for d in v]
    log('GB form docs',len(docs)); n=0; cap=250
    for p in docs:
        if n>=cap: return 'forms_cap250'
        rr=fetch('https://www.gov.uk/api/content'+p)
        if not rr: continue
        d=json.loads(rr[0]); atts=d.get('details',{}).get('attachments',[]) or []
        for a in atts:
            u=a.get('url'); 
            if not u or n>=cap: continue
            if u.startswith('/'): u='https://www.gov.uk'+u
            fr=fetch(u,binary=True)
            o.w('forms',{**base('GB','GB-ENG',u,'HMCTS','en',fr[0] if fr else None),'form_id':(a.get('title') or '')[:40] if not re.match(r'\w',d.get('title','')) else d.get('title','').split()[0],
                'title':a.get('title') or d.get('title'),'court_id':None,'issuing_body':'HMCTS','url':u,'format':a.get('content_type'),'parent_page':'https://www.gov.uk'+p})
            n+=1
def gb_rules(o):
    for rs,idx,pref in [('CPR','https://www.justice.gov.uk/courts/procedure-rules/civil/rules','/courts/procedure-rules/civil/rules/'),
                        ('FPR','https://www.justice.gov.uk/courts/procedure-rules/family/rules_pd_menu','/courts/procedure-rules/family/'),
                        ('CrimPR','https://www.justice.gov.uk/courts/procedure-rules/criminal/rulesmenu','/courts/procedure-rules/criminal/')]:
        r=fetch(idx)
        if not r: log('GB rules idx miss',idx); continue
        links=sorted(set(urllib.parse.urljoin(idx,h) for h in re.findall(r'href="([^"#]+)"',r[0].decode('utf-8','ignore'))))
        links=[l for l in links if urllib.parse.urlparse(l).path.startswith(pref) and l.rstrip('/')!=idx.rstrip('/') and urllib.parse.urlparse(l).netloc=='www.justice.gov.uk' and not l.lower().endswith('.pdf')][:150]
        for l in links:
            rr=fetch(l)
            if not rr: continue
            b=rr[0].decode('utf-8','ignore'); m=re.search(r'<h1[^>]*>(.*?)</h1>',b,re.S)
            o.w('rules',{**base('GB','GB-ENG',l,'Ministry of Justice','en',rr[0]),'rule_set':rs,'section':l.rstrip('/').rsplit('/',1)[-1],'title':txt(m.group(1)) if m else None,'url':l,'effective_date':None})
# ---------------- DE
def de_zpo(o):
    r=fetch('https://www.gesetze-im-internet.de/zpo/xml.zip',binary=True)
    if not r: return 'blocked'
    z=zipfile.ZipFile(io.BytesIO(r[0])); x=ET.fromstring(z.read([n for n in z.namelist() if n.endswith('.xml')][0]))
    for nm in x.iter('norm'):
        md=nm.find('metadaten'); e=md.findtext('enbez') if md is not None else None
        if not e or not e.startswith('§'): continue
        ti=md.findtext('titel'); body=ET.tostring(nm,encoding='unicode')
        num=e.replace('§','').strip()
        u=f'https://www.gesetze-im-internet.de/zpo/__{num}.html'
        o.w('rules',{**base('DE',None,u,'BMJ / gesetze-im-internet.de','de',body),'rule_set':'ZPO','section':e,'title':ti,'url':u,'effective_date':None,'note':'sha256 of norm XML from zpo/xml.zip'})
# ---------------- CA
def ca_laws(o):
    for code,rs in [('SOR-98-106','Federal Courts Rules'),('SOR-2002-156','Rules of the Supreme Court of Canada'),('SOR-90-688a','Tax Court of Canada Rules (General Procedure)')]:
        u=f'https://laws-lois.justice.gc.ca/eng/XML/{code}.xml'; r=fetch(u,binary=True)
        if not r: log('CA miss',u); continue
        x=ET.fromstring(r[0])
        for s in x.iter('Section'):
            lab=s.findtext('Label'); mn=s.findtext('MarginalNote')
            if not lab: continue
            o.w('rules',{**base('CA',None,f'https://laws-lois.justice.gc.ca/eng/regulations/{code}/',('Department of Justice Canada'),'en',ET.tostring(s)),'rule_set':rs,'section':lab,'title':mn,'url':f'https://laws-lois.justice.gc.ca/eng/regulations/{code}/','effective_date':None})
def ca_scc(o):
    u='https://www.scc-csc.ca/about-apropos/judges-juges/list-liste/'; r=fetch(u)
    if not r: return 'blocked'
    b=r[0].decode('utf-8','ignore'); seen=set()
    for href,inner in re.findall(r'href="(/about-apropos/judges-juges/list-liste/[a-z0-9-]+/)"[^>]*>(.*?)</a>',b,re.S):
        nm=txt(inner)
        if not nm or href in seen or len(nm)>80: continue
        seen.add(href); title='Chief Justice of Canada' if 'Chief' in nm else 'Puisne Justice'
        clean=re.sub(r'^(The )?(Right )?Honourable |,? ?(Chief Justice of Canada|P\.C\.)','',nm).strip()
        o.w('judges',{**base('CA',None,u,'Supreme Court of Canada','en',b),'name':clean,'court_id':'CA-NAT-supreme-court-of-canada','title':title,'role_type':'justice','profile_url':'https://www.scc-csc.ca'+href})
    if not seen: return 'blocked'
def finish(marker,why):
    open(f'{ROOT}/{marker}','w').write(f'{now()} {why}\n'); log('FINISH',marker,why)
    import subprocess; subprocess.run([sys.executable,ROOT+'/collector/intl_review.py']); sys.exit(0 if marker=='INTL_DONE' else 5)
if __name__=='__main__':
    log('START pid',os.getpid(),'memavail %.2fG'%memavail())
    plan=[('GB',[('gb_courts',gb_courts),('gb_forms',gb_forms),('gb_rules',gb_rules)]),('DE',[('de_zpo',de_zpo)]),('CA',[('ca_laws',ca_laws),('ca_scc',ca_scc)])]
    for cc,ts in plan:
        o=Out(cc)
        for n,f in ts: task(o,n,lambda f=f,o=o:f(o))
        open(f'{ST}/{cc}/DONE','w').write(now())
    finish('INTL_DONE','all planned tasks; FR/NG/SCTS/Ontario skipped per TERMS_REVIEW.md')
