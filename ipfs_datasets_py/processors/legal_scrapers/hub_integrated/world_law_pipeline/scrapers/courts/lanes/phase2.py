# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import csv,json,os,re,time,datetime,gzip,io,urllib.parse as up,hashlib,sys
import requests,certifi
from bs4 import BeautifulSoup
UA="endomorphosis-world-laws-courts/0.1 (+https://github.com/endomorphosis; polite research bot)"
OUT="data/phase2";LOG=f"{OUT}/progress.log";ST=f"{OUT}/progress.json"
S=requests.Session();S.headers["User-Agent"]=UA;S.verify=certifi.where()
KW={"judge":r"judge|justice|judiciary|bench|members|magistrat|juges|richter|jueces|ministros|juizes|rechters","form":r"\bforms?\b|formul|formular","rule":r"rules?|procedure|practice.?direction|reglement|verfahrens|reglamento|regimento","court":r"locat|contact|address|court.?finder|directory|find.?a.?court|courthouse|visit|tribunais|adressen"}
last=[0.0];TODAY=datetime.date.today().isoformat()
def log(m): open(LOG,"a").write(f"{datetime.datetime.now().isoformat(timespec='seconds')} {m}\n");print(m,flush=True)
def res():
  ma=int(open("/proc/meminfo").read().split("MemAvailable:")[1].split()[0])/1048576;st=os.statvfs((str(_LEGAL_WS)));return ma,st.f_bavail*st.f_frsize/2**30
def gate():
  ma,df=res()
  if ma<4.5 or df<22: log(f"STOP resource gate MemAvail={ma:.1f}Gi free={df:.1f}G");sys.exit(3)
def get(url,**kw):
  d=time.time()-last[0]
  if d<2.2: time.sleep(2.2-d)
  last[0]=time.time();return S.get(url,timeout=kw.pop("timeout",30),**kw)
def classify(t): return [k for k,p in KW.items() if re.search(p,t,re.I)]
class Sink:
  def __init__(s,fn,base): s.f=open(fn,"a");s.seen=set();s.cnt={};s.base=base
  def emit(s,rec):
    k=hashlib.sha1(json.dumps(rec,sort_keys=True).encode()).hexdigest()
    if k in s.seen: return
    s.seen.add(k);rec.update(s.base);rec["retrieval_date"]=TODAY;s.f.write(json.dumps(rec,ensure_ascii=False)+"\n");s.f.flush();s.cnt[rec["type"]]=s.cnt.get(rec["type"],0)+1
def extract(html,u,src,sink,name):
  soup=BeautifulSoup(html,"lxml");title=soup.title.string if soup.title and soup.title.string else "";ptype=classify(u+" "+title)
  for a in soup.find_all("a",href=True):
    try:
      txt=" ".join(a.get_text(" ").split())[:200];href=up.urljoin(u,a["href"]);href=re.sub(r"^https?://web\.archive\.org/web/\d+[a-z_]*/","",href);hu=up.urlsplit(href)
    except ValueError: continue
    if hu.scheme not in("http","https"): continue
    c=classify(txt+" "+hu.path);isdoc=re.search(r"\.(pdf|docx?|rtf|odt)$",hu.path,re.I)
    if "form" in c and (isdoc or re.search(r"form",txt,re.I)): sink.emit({"type":"form","title":txt,"file_url":href,"file_format":(isdoc.group(1).lower() if isdoc else "html"),"found_on":src})
    elif "rule" in c and len(txt)>3: sink.emit({"type":"rule","title":txt,"url":href,"found_on":src})
  text=soup.get_text("\n")
  if "judge" in ptype:
    for line in text.split("\n"):
      l=" ".join(line.split())
      if 6<len(l)<90 and re.match(r"^(The\s+)?(Hon'?ble|Honourable|Hon\.|Chief Justice|Justice|Judge|Mr\.? Justice|Mrs\.? Justice|Ms\.? Justice|Lord|Lady|Dame|Sir|Juge|Richter|Ministro|Ministra|Juez|Jueza)\b",l): sink.emit({"type":"judge","full_name":l,"roster_url":src})
  for ad in soup.find_all("address"): sink.emit({"type":"court","name":name,"address":" ".join(ad.get_text(" ").split())[:300],"found_on":src})
  if "court" in ptype:
    for line in text.split("\n"):
      l=" ".join(line.split())
      if 12<len(l)<160 and re.search(r"\d",l) and re.search(r"\b(street|st\.|road|rd\.|avenue|ave|marg|lane|place|square|building|house|strasse|straße|rue|calle|via|plein|PO Box|[A-Z]{1,2}\d{1,2} ?\d[A-Z]{2}|\d{5,6})\b",l,re.I): sink.emit({"type":"court","name":name,"address":l,"found_on":src})
# ---- archive helpers
def cdx(host,prefix="",limit=3000):
  out=[]
  for h in ([host,"www."+host] if not host.startswith("www.") else [host,host[4:]]):
    q={"url":h+"/"+prefix,"matchType":"prefix","output":"json","fl":"timestamp,original,mimetype,statuscode","filter":["statuscode:200","mimetype:text/html"],"collapse":"urlkey","from":"2023","limit":str(limit)}
    try:
      r=get("https://web.archive.org/cdx/search/cdx",params=q,timeout=90)
      if r.status_code==200 and r.text.strip(): out+= [dict(zip(r.json()[0],x)) for x in r.json()[1:]]
    except Exception as e: log(f"cdx err {h} {type(e).__name__}")
  return out
def wb(ts,orig):
  r=get(f"https://web.archive.org/web/{ts}id_/{orig}",allow_redirects=True,timeout=40)
  if r.status_code==200 and "html" in r.headers.get("content-type","html"): return r.text,r.url
  return None,None
CCID=[None]
def cc_index():
  if not CCID[0]: CCID[0]=get("https://index.commoncrawl.org/collinfo.json").json()[0]["id"];log(f"Common Crawl index {CCID[0]}")
  return CCID[0]
def cc_list(host,limit=300):
  try:
    r=get(f"https://index.commoncrawl.org/{cc_index()}-index",params={"url":host+"/*","output":"json","filter":["status:200","mime:text/html"],"limit":str(limit)},timeout=90)
    return [json.loads(l) for l in r.text.splitlines() if l.startswith("{")] if r.status_code==200 else []
  except Exception as e: log(f"cc err {host} {type(e).__name__}");return []
def cc_fetch(rec):
  o,l=int(rec["offset"]),int(rec["length"])
  r=get("https://data.commoncrawl.org/"+rec["filename"],headers={"Range":f"bytes={o}-{o+l-1}"},timeout=60)
  if r.status_code!=206: return None
  raw=gzip.decompress(r.content);parts=raw.split(b"\r\n\r\n",2)
  return parts[2].decode("utf-8","replace") if len(parts)==3 else None
def pick(urls,home):
  ks=[u for u in urls if classify(up.urlsplit(u).path)];ks.sort(key=lambda u:len(u))
  sel=[home] if home else []
  for cat in KW:
    sel+=[u for u in ks if cat in classify(up.urlsplit(u).path)][:4]
  seen=[];[seen.append(x) for x in sel if x and x not in seen];return seen[:14]
def archive_source(key,r,done):
  h=up.urlsplit(r["url"]).netloc;fn=f"{OUT}/{re.sub(r'[^A-Za-z0-9]+','_',key)[:80]}.jsonl"
  sink=Sink(fn,{"jurisdiction":r["jurisdiction"],"source_name":key,"license":"see TERMS.md"});pages=0;mode="wayback-cdx"
  caps=cdx(h);bymap={}
  for c in caps: bymap[c["original"]]=c["timestamp"]
  if bymap:
    home=min(bymap,key=len);
    for u in pick(list(bymap),home):
      gate()
      try: html,src=wb(bymap[u],u)
      except Exception as e: html=None
      if html: pages+=1;sink.base["retrieval_mode"]=mode;extract(html,u,src,sink,key)
  if not pages:
    mode="commoncrawl";recs=cc_list(h) or cc_list("www."+h if not h.startswith("www.") else h[4:])
    bym={x["url"]:x for x in recs}
    for u in pick(list(bym),min(bym,key=len) if bym else None):
      gate()
      try: html=cc_fetch(bym[u])
      except Exception as e: html=None
      if html: pages+=1;sink.base["retrieval_mode"]=mode;src=f"cc:{CCID[0]}:{bym[u]['filename']}@{bym[u]['offset']}#{u}";extract(html,u,src,sink,key)
  done[key]={"status":"ok" if pages else "failed","mode":mode,"pages":pages,"counts":sink.cnt,"cdx_captures":len(caps),"file":fn,"phase":"2"}
  json.dump(done,open(ST,"w"),indent=1);ma,df=res();log(f"ARCH {key} {mode} cdx={len(caps)} pages={pages} {sink.cnt} mem={ma:.1f} disk={df:.1f}")
import urllib.robotparser as urp
RP={}
def robots(base):
  if base not in RP:
    rp=urp.RobotFileParser()
    try:
      r=get(base+"/robots.txt",timeout=20)
      if r.status_code==200 and "html" not in r.headers.get("content-type","").lower(): rp.parse(r.text.splitlines())
      elif r.status_code in(404,410): rp.parse([])
      else: rp=None
    except Exception as e: log(f"robots err {base} {type(e).__name__}");rp=None
    RP[base]=rp
  return RP[base]
def live_source(key,r,done):
  sp=up.urlsplit(r["url"]);base=f"{sp.scheme}://{sp.netloc}";rp=robots(base)
  if rp is None or not rp.can_fetch(UA,r["url"]): return 0,None
  cd=rp.crawl_delay(UA) or 0
  if cd>10: return 0,None
  fn=f"{OUT}/{re.sub(r'[^A-Za-z0-9]+','_',key)[:80]}.jsonl"
  sink=Sink(fn,{"jurisdiction":r["jurisdiction"],"source_name":key,"license":"see TERMS.md","retrieval_mode":"live"})
  try: h=get(r["url"])
  except Exception as e: log(f"live err {key} {type(e).__name__}");return 0,sink
  if h.status_code!=200 or "html" not in h.headers.get("content-type","html") or re.search(r"cf-chl|captcha|Just a moment",h.text[:3000],re.I): log(f"live blocked {key} {h.status_code}");return 0,sink
  pages=1;extract(h.text,h.url,h.url,sink,key)
  links=set()
  for a in BeautifulSoup(h.text,"lxml").find_all("a",href=True):
    try: u=up.urljoin(h.url,a["href"]).split("#")[0];us=up.urlsplit(u)
    except ValueError: continue
    if us.netloc.replace("www.","")==up.urlsplit(h.url).netloc.replace("www.","") and not re.search(r"\.(pdf|docx?|jpe?g|png|zip|xlsx?)$",us.path,re.I): links.add(u)
  for u in pick(sorted(links),None)[:13]:
    gate()
    if not rp.can_fetch(UA,u): continue
    if cd: time.sleep(max(0,cd-2.2))
    try: x=get(u)
    except Exception: continue
    if x.status_code==200 and "html" in x.headers.get("content-type",""): pages+=1;extract(x.text,x.url,x.url,sink,key)
  done[key]={"status":"ok","mode":"live","pages":pages,"counts":sink.cnt,"file":fn,"phase":"2"}
  json.dump(done,open(ST,"w"),indent=1);ma,df=res();log(f"LIVE {key} pages={pages} {sink.cnt} mem={ma:.1f} disk={df:.1f}")
  return pages,sink
def main():
  done=json.load(open(ST)) if os.path.exists(ST) else {};gate();log(f"START phase2 res={res()}")
  rows=[r for r in csv.DictReader(open("sources.csv")) if (r["level"] in("state","provincial") and not r["jurisdiction"].startswith("IN-")) or r["jurisdiction"] in("UK-Scotland","UK-Northern Ireland")]
  log(f"targets {len(rows)}")
  for r in rows:
    k=r["source_name"]
    if done.get(k,{}).get("status") in("ok","failed"): continue
    if re.search(r"canlii|austlii|cornell",r["url"],re.I): done[k]={"status":"skipped","reason":"excluded bulk source"};continue
    gate();p,_=live_source(k,r,done)
    if not p: archive_source(k,r,done)
  json.dump(done,open(ST,"w"),indent=1);log("FINISHED phase2")
main()
