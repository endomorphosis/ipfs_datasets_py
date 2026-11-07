import csv,json,os,re,time,datetime,gzip,io,urllib.parse as up,hashlib,sys
import requests,certifi
from bs4 import BeautifulSoup
UA="endomorphosis-world-laws-courts/0.1 (+https://github.com/endomorphosis; polite research bot)"
OUT="data/phase1";LOG=f"{OUT}/progress.log";ST=f"{OUT}/progress.json"
S=requests.Session();S.headers["User-Agent"]=UA;S.verify=certifi.where()
KW={"judge":r"judge|justice|judiciary|bench|members|magistrat|juges|richter|jueces|ministros|juizes|rechters","form":r"\bforms?\b|formul|formular","rule":r"rules?|procedure|practice.?direction|reglement|verfahrens|reglamento|regimento","court":r"locat|contact|address|court.?finder|directory|find.?a.?court|courthouse|visit|tribunais|adressen"}
last=[0.0];TODAY=datetime.date.today().isoformat()
def log(m): open(LOG,"a").write(f"{datetime.datetime.now().isoformat(timespec='seconds')} {m}\n");print(m,flush=True)
def res():
  ma=int(open("/proc/meminfo").read().split("MemAvailable:")[1].split()[0])/1048576;st=os.statvfs("/workspace");return ma,st.f_bavail*st.f_frsize/2**30
def gate():
  ma,df=res()
  if ma<4.5 or df<23: log(f"STOP resource gate MemAvail={ma:.1f}Gi free={df:.1f}G");sys.exit(3)
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
    txt=" ".join(a.get_text(" ").split())[:200];href=up.urljoin(u,a["href"]);href=re.sub(r"^https?://web\.archive\.org/web/\d+[a-z_]*/","",href);hu=up.urlsplit(href)
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
  done[key]={"status":"ok" if pages else "failed","mode":mode,"pages":pages,"counts":sink.cnt,"cdx_captures":len(caps),"file":fn,"retry":"phase1b"}
  json.dump(done,open(ST,"w"),indent=1);ma,df=res();log(f"RETRY {key} {mode} cdx={len(caps)} pages={pages} {sink.cnt} mem={ma:.1f} disk={df:.1f}")
def uk_fact(done):
  key="UK court finder locations";
  if done.get(key,{}).get("status")=="ok": return
  sink=Sink(f"{OUT}/UK_FaCT_locations.jsonl",{"jurisdiction":"UK","source_name":key,"license":"OGL v3","retrieval_mode":"live"})
  st=f"{OUT}/uk_fact_done.txt";dn=set(open(st).read().split()) if os.path.exists(st) else set()
  slugs=open(f"{OUT}/raw/uk_fact_slugs.txt").read().split()
  for s in slugs:
    if s in dn: continue
    gate();u=f"https://www.find-court-tribunal.service.gov.uk/courts/{s}"
    try: r=get(u)
    except Exception as e: continue
    if r.status_code==200:
      soup=BeautifulSoup(r.text,"lxml");h1=soup.find("h1");name=h1.get_text(" ",strip=True) if h1 else s
      if name.lower().startswith("page not found"): open(st,"a").write(s+"\n");continue
      addrs=[];
      for hd in soup.find_all(["h2","h3"]):
        if re.search(r"address",hd.get_text(),re.I):
          nx=hd.find_next(["p","div"])
          if nx: addrs.append(" ".join(nx.get_text(" ").split()))
      t=soup.get_text(" ");pc=re.findall(r"\b[A-Z]{1,2}\d[A-Z\d]? ?\d[A-Z]{2}\b",t)
      typ=next((k for k in ["Crown Court","Magistrates","County Court","Family Court","Tribunal","High Court","Court of Appeal","Justice Centre","Combined Court"] if k.lower() in (name+" "+t[:5000]).lower()),"")
      sink.emit({"type":"court","name":name,"slug":s,"address":addrs[0] if addrs else "","postcodes":sorted(set(pc))[:3],"court_type_hint":typ,"source_url":u})
    open(st,"a").write(s+"\n")
  done[key]={"status":"ok","mode":"live","counts":sink.cnt,"file":sink.f.name};json.dump(done,open(ST,"w"),indent=1);log(f"DONE {key} {sink.cnt}")
def us_finder(done):
  key="US Courts court locator (Wayback)"
  if done.get(key,{}).get("status")=="ok": return
  sink=Sink(f"{OUT}/US_court_finder_wayback.jsonl",{"jurisdiction":"US","source_name":key,"license":"US public domain","retrieval_mode":"wayback-cdx"})
  caps=cdx("www.uscourts.gov","federal-court-finder/",limit=2000);caps+=cdx("www.uscourts.gov","about-federal-courts/court-website-links",limit=50)
  log(f"US finder cdx={len(caps)}");n=0
  for c in sorted(caps,key=lambda c:len(c["original"]))[:120]:
    gate()
    try: html,src=wb(c["timestamp"],c["original"])
    except Exception: html=None
    if not html: continue
    n+=1;soup=BeautifulSoup(html,"lxml")
    for blk in soup.select("div.views-row, article, li, tr"):
      t=" ".join(blk.get_text(" ").split())
      if 20<len(t)<400 and re.search(r"(Court|Courthouse|Bankruptcy|District)",t) and re.search(r"\b\d{5}(-\d{4})?\b",t):
        sink.emit({"type":"court","name":t.split("  ")[0][:120],"address":t,"found_on":src})
    for a in soup.find_all("a",href=True):
      tx=a.get_text(" ",strip=True)
      if re.search(r"(District Court|Bankruptcy Court|Court of Appeals|Circuit)",tx) and re.search(r"\.uscourts\.gov",a["href"]): sink.emit({"type":"court","name":tx,"website":re.sub(r'^https?://web\.archive\.org/web/\d+[a-z_]*/','',a["href"]),"found_on":src})
  done[key]={"status":"ok" if sink.cnt else "failed","pages":n,"cdx_captures":len(caps),"counts":sink.cnt,"file":sink.f.name};json.dump(done,open(ST,"w"),indent=1);log(f"DONE {key} pages={n} {sink.cnt}")
def main():
  done=json.load(open(ST));gate();log(f"START phase1b res={res()}")
  rows={r["source_name"]:r for r in csv.DictReader(open("sources.csv"))}
  targets=[k for k,v in done.items() if v.get("mode")=="wayback" and v["status"]!="ok"]
  log(f"wayback retry targets {len(targets)}")
  for k in targets: archive_source(k,rows[k],done)
  us_finder(done);uk_fact(done);log("FINISHED phase1b")
main()
