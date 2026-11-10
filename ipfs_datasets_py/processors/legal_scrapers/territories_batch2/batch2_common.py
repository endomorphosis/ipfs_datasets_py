"""Additive territory collection helpers. No credentials, retries or uploads."""
import pathlib,sys,os,time,re,json,hashlib,resource
from urllib.parse import urlparse,urljoin
from urllib.robotparser import RobotFileParser
import requests
ROOT=pathlib.Path('/workspace/staging/territories_batch2_20261105')
UA='GrokBot-CountryLawCollector/1.0 (keyless official legislation; provenance archive; not model training)'
def guard(start=False):
 m=int(pathlib.Path('/proc/meminfo').read_text().split('MemAvailable:')[1].split()[0])/1024**2
 rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024
 if m<(4.2 if start else 3.2) or rss>290:raise SystemExit('MEMORY_HOLD')
def no_delete(event,args):
 if event in ['os.remove','os.rmdir','os.rename']:raise RuntimeError('ZERO_DELETE_REPLACE_GUARD')
def install_guard():sys.addaudithook(no_delete)
def write_json(path,value):
 path=pathlib.Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 with path.open('x') as f:json.dump(value,f,indent=2,ensure_ascii=False)
class Polite:
 def __init__(self,hosts):
  self.hosts=set(hosts);self.last={};self.delay={};self.policies={};self.hold=set();self.session=requests.Session();self.session.headers['User-Agent']=UA
 def request(self,url,robots=False):
  guard();host=urlparse(url).netloc
  if urlparse(url).scheme!='https' or host not in self.hosts or host in self.hold:raise ValueError('TLS_HOST_OR_ACCESS_HOLD')
  if not robots:
   if host not in self.policies:self.setup('https://'+host+'/')
   if not self.policies[host].can_fetch(UA,url):raise ValueError('ROBOTS_HOLD')
  time.sleep(max(0,self.delay.get(host,2)-(time.monotonic()-self.last.get(host,0))));self.last[host]=time.monotonic()
  r=self.session.get(url,timeout=(12,35),verify=True,allow_redirects=False,stream=True);body=bytearray()
  for chunk in r.iter_content(65536):
   body.extend(chunk)
   if len(body)>16*1024**2:r.close();raise ValueError('SIZE_HOLD')
  r.close();body=bytes(body)
  challenge=bool(re.search(rb'<title[^>]*>[^<]*(just a moment|access denied|captcha|attention required)|cf-chl-|g-recaptcha|hcaptcha|verify you are human',body[:120000],re.I))
  record={'requested_url':url,'status':r.status_code,'content_type':r.headers.get('Content-Type'),'location':r.headers.get('Location'),'sha256':hashlib.sha256(body).hexdigest(),'observed_local':time.strftime('%Y-%m-%d %H:%M:%S %Z'),'challenge':challenge}
  raw=ROOT/'evidence'/f'{record["sha256"]}.raw';raw.parent.mkdir(parents=True,exist_ok=True)
  if not raw.exists():raw.open('xb').write(body)
  record['raw_path']=str(raw)
  log=ROOT/'evidence'/'requests.jsonl'
  with log.open('a') as f:f.write(json.dumps(record)+'\n')
  if r.status_code in (403,429,503) or challenge:self.hold.add(host)
  return body,record
 def get(self,url,robots=False):
  for i in range(4):
   body,record=self.request(url,robots)
   if 300<=record['status']<400 and record.get('location'):
    nxt=urljoin(url,record['location'])
    if urlparse(nxt).scheme!='https' or urlparse(nxt).netloc not in self.hosts:return body,record
    url=nxt;continue
   return body,record
  raise ValueError('REDIRECT_LIMIT_HOLD')
 def setup(self,url):
  host=urlparse(url).netloc;body,record=self.get('https://'+host+'/robots.txt',True);rp=RobotFileParser()
  if record['status']==200:rp.parse(body.decode(errors='replace').splitlines())
  elif record['status']==404:rp.parse([])
  else:self.hold.add(host);raise ValueError('ROBOTS_UNAVAILABLE_'+str(record['status']))
  self.policies[host]=rp;self.delay[host]=max(2,rp.crawl_delay(UA) or rp.crawl_delay('*') or 0)
  return record
