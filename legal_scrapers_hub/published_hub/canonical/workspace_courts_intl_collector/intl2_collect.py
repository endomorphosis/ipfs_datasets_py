#!/usr/bin/env python3
"""Intl collector 2 (IE courts.ie under PSI licence; EU CJEU curia 'reproduce with source acknowledged'). Live official, keyless, polite (>=10s/host, robots Crawl-delay), stop host on 403/429/challenge. Stage only. GO: COS_GO_INTL2_20261103"""
import sys,os,re,json,time,html
sys.path.insert(0,'/workspace/courts/intl/collector')
import intl_collect as ic
ic.LOG=ic.ROOT+'/logs/intl2_collect.log'
def fin(marker,why):
    marker={'STOPPED_INTL':'STOPPED_INTL2','INTL_DONE':'INTL2_DONE'}.get(marker,marker)
    open(f'{ic.ROOT}/{marker}','w').write(f'{ic.now()} {why}\n'); ic.log('FINISH',marker,why)
    import subprocess; subprocess.run([sys.executable,ic.ROOT+'/collector/intl2_review.py']); sys.exit(0 if 'DONE' in marker else 3)
ic.finish=fin
FORMCAP=250
def locs(u):
    r=ic.fetch(u); return re.findall(r'<loc>\s*([^<\s]+)\s*</loc>',r[0].decode('utf-8','ignore')) if r else []
def h1(b):
    m=re.search(r'(?s)<h1[^>]*>(.*?)</h1>',b); return ic.txt(m.group(1)) if m else None
IEB='https://www.courts.ie'
IECOURTS=[('supreme','Supreme Court','supreme'),('court-of-appeal','Court of Appeal','appellate'),('high','High Court','high'),('circuit','Circuit Court','first_instance'),('district','District Court','first_instance')]
def ie_courts(o):
    r=ic.fetch(IEB+'/explore/courts')
    if not r: return 'partial'
    b=r[0]
    for s,n,l in IECOURTS:
        o.w('courts',{**ic.base('IE',None,IEB+'/explore/courts','Courts Service of Ireland','en',b),'court_id':f'IE-NAT-{s}','name':n,'name_en':n,'level':l,'jurisdiction_type':None,'parent_court_id':None,'license':'Irish PSI Licence (CC BY 4.0-compatible); © Courts Service'})
def ie_courthouses(o):
    for u in locs(IEB+'/sitemaps/sitemap-offices.xml'):
        r=ic.fetch(u)
        if not r: continue
        b=r[0].decode('utf-8','ignore'); t=ic.txt(b); name=h1(b) or u.rsplit('/',1)[1]
        a=re.search(r'Address (.*?) (?:Eircode (\S+ ?\S+)|Telephone number|Email|Head of office|Opening)',t)
        if not a: ic.log('IE no address',u); continue
        ph=re.search(r'Telephone number ([\d +()-]{6,20})',t); em=re.search(r'Email (\S+@courts\.ie)',t)
        addr=a.group(1).strip().rstrip(',')
        o.w('courthouses',{**ic.base('IE',None,u,'Courts Service of Ireland','en',r[0]),'courthouse_id':'IE-NAT-'+u.rstrip('-').rsplit('/',1)[1][:80],'court_id':None,'name':name,
            'street':addr,'locality':None,'postal_code':a.group(2),'region':None,'lat':None,'lon':None,'phone':ph.group(1).strip() if ph else None,'email':em.group(1) if em else None,
            'license':'Irish PSI Licence; © Courts Service','note':'office/venue page; serves multiple court jurisdictions'})
def ie_rules(o):
    for u in locs(IEB+'/sitemaps/sitemap-court-rules.xml'):
        if 'full-court-rule' not in u: continue
        r=ic.fetch(u)
        if not r: continue
        b=r[0].decode('utf-8','ignore'); slug=u.split('url=',1)[-1]
        rs='Rules of the Superior Courts' if 'Superior' in slug else 'Circuit Court Rules' if 'Circuit' in slug else 'District Court Rules' if 'District' in slug else 'Court Rules'
        o.w('rules',{**ic.base('IE',None,u,'Courts Service of Ireland','en',r[0]),'rule_set':rs,'section':slug,'title':h1(b) or slug.replace('-',' '),'url':u,'effective_date':None,'license':'Irish PSI Licence; © Courts Service'})
def ie_forms(o):
    us=locs(IEB+'/sitemaps/sitemap-forms.xml'); n=0
    for u in us[:FORMCAP]:
        r=ic.fetch(u)
        if not r: continue
        b=r[0].decode('utf-8','ignore'); t=h1(b) or u.rsplit('/',1)[1]
        m=re.match(r'(?:No\.\s*)?([0-9]+[A-Z]?\.[0-9]+[A-Z]?)',t)
        o.w('forms',{**ic.base('IE',None,u,'Courts Service of Ireland','en',r[0]),'form_id':'IE-'+u.rsplit('/',1)[1][:90],'form_number':m.group(1) if m else None,'title':t,'court_id':None,'url':u,'format':'html',
            'note':'form landing page hashed; files under /docs/ are robots-disallowed and not fetched','license':'Irish PSI Licence; © Courts Service'}); n+=1
    if len(us)>FORMCAP: return f'partial_capped_{FORMCAP}_of_{len(us)}'
CU='https://curia.europa.eu'
def eu_courts(o):
    for cid,n,l in (('EU-NAT-court-of-justice','Court of Justice','supreme'),('EU-NAT-general-court','General Court','first_instance')):
        o.w('courts',{**ic.base('EU',None,CU,'Court of Justice of the European Union','en'),'court_id':cid,'name':n,'name_en':n,'level':l,'jurisdiction_type':'EU','parent_court_id':None,'sha256':None,'license':'Source: Court of Justice of the European Union'})
    r=ic.fetch(CU+'/jcms/jcms/Jo2_7039/en/')
    if r:
        t=ic.txt(r[0]); a=re.search(r'Registry of the Court of Justice (.*?L-\d{4} Luxembourg)',t)
        if a: o.w('courthouses',{**ic.base('EU',None,r[1],'Court of Justice of the European Union','en',r[0]),'courthouse_id':'EU-NAT-court-of-justice-registry','court_id':'EU-NAT-court-of-justice','name':'Registry of the Court of Justice',
              'street':a.group(1).split(' L-')[0],'locality':'Luxembourg','postal_code':re.search(r'L-\d{4}',a.group(1)).group(),'region':None,'lat':None,'lon':None,'phone':None,'email':None,'license':'Source: Court of Justice of the European Union'})
def eu_judges(o):
    r=ic.fetch(CU+'/jcms/jcms/Jo2_7026/en/')
    if not r: return 'partial'
    b=r[0].decode('utf-8','ignore')
    for m in re.finditer(r'(?s)<h3 class="curia-cv-item-title">(.*?)</h3>(.{0,400})',b):
        nm=ic.txt(m.group(1)); tl=re.match(r'\s*(.*?)\s+Biography',ic.txt(m.group(2)))
        title=tl.group(1) if tl and len(tl.group(1))<80 else None
        rt='advocate_general' if title and 'Advocate' in title else 'judge'
        o.w('judges',{**ic.base('EU',None,r[1],'Court of Justice of the European Union','en',r[0]),'name':nm,'court_id':'EU-NAT-court-of-justice','title':title,'role_type':rt,'license':'Source: Court of Justice of the European Union'})
def eu_rules(o):
    r=ic.fetch(CU+'/jcms/d2_5104/en/case-procedure') or ic.fetch(CU+'/site/jcms/d2_5104/en/case-procedure')
    if not r: return 'partial'
    b=r[0].decode('utf-8','ignore'); seen=set()
    for href,tx in re.findall(r'(?s)<a[^>]+href="([^"]+\.pdf)"[^>]*>(.*?)</a>',b):
        u=href if href.startswith('http') else CU+'/'+href.lstrip('/'); t=ic.txt(tx)
        if u in seen or not re.search(r'rule|statute|instruction|practice|recommendation',t+u,re.I) or len(seen)>=30: continue
        seen.add(u); g=ic.fetch(u,binary=True)
        if g: o.w('rules',{**ic.base('EU',None,u,'Court of Justice of the European Union','en',g[0]),'rule_set':'CJEU procedural texts','section':None,'title':t,'url':g[1],'effective_date':None,'source_page':r[1],'license':'Source: Court of Justice of the European Union'})
if __name__=='__main__':
    ic.log('START pid',os.getpid(),'memavail %.2fG'%ic.memavail())
    plan=[('EU',[('eu_courts',eu_courts),('eu_judges',eu_judges),('eu_rules',eu_rules)]),('IE',[('ie_courts',ie_courts),('ie_courthouses',ie_courthouses),('ie_rules',ie_rules),('ie_forms',ie_forms)])]
    for cc,ts in plan:
        o=ic.Out(cc)
        for n,f in ts: ic.task(o,n,lambda f=f,o=o:f(o))
        open(f'{ic.ST}/{cc}/DONE','w').write(ic.now())
    ic.finish('INTL_DONE','IE+EU planned tasks done; NZ/SG skipped (terms forbid reuse w/o permission); KE/IN/US territories pending terms')
