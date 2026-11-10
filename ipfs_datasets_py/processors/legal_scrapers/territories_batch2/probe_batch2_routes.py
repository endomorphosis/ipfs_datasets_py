"""Conservative official portal discovery, robots and terms evidence."""
import json,pathlib,time
from urllib.parse import urlparse,urljoin
from bs4 import BeautifulSoup
from batch2_common import ROOT,Polite,guard,install_guard,write_json
install_guard();guard(True)
seeds=[('NO_API','https://api.lovdata.no/list'),('NO_TERMS','https://lovdata.no/info/api'),('MP','https://www.cnmilaw.org/'),('TK','https://www.tokelau.org.nz/Tokelau+Government/Government+Departments/Office+of+the+Council+for+the+Ongoing+Government+OCOG/Tokelau+National+Statistics+Office/Tokelau+Statistics+Rules+2013.html'),('AQ_TERMS','https://www.ats.aq/e/imprint.html'),('AQ','https://www.ats.aq/e/key-documents.html'),('VI','https://legvi.org/')]
hosts={urlparse(u).netloc for c,u in seeds}|{'cnmilaw.org','www.cnmilaw.gov','cnmilaw.gov','documents.ats.aq'};client=Polite(hosts);results=[]
for code,url in seeds:
 try:
  if urlparse(url).netloc not in client.policies:rob=client.setup(url)
  body,meta=client.get(url);soup=BeautifulSoup(body,'html.parser');text=soup.get_text(' ',strip=True);links=[{'title':a.get_text(' ',strip=True)[:200],'url':urljoin(meta['requested_url'],a['href'])} for a in soup.select('a[href]')]
  r={'code':code,'page':meta,'title':soup.title.get_text(' ',strip=True) if soup.title else '', 'text':text,'links':links}
  write_json(ROOT/(code+'_portal.json'),r);results.append({'code':code,'status':meta['status'],'title':r['title'],'text_length':len(text),'links':len(links)});print('PROBE',results[-1],flush=True)
 except Exception as e:results.append({'code':code,'error':type(e).__name__+':'+str(e)[:300]});print('PROBE',results[-1],flush=True)
write_json(ROOT/'probe_results.json',results);print('PROBES_DONE',flush=True)
