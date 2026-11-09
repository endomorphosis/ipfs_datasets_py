# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import signal,csv,json,os,re,time,datetime,gzip,io,urllib.parse as up,hashlib,sys
import requests,certifi
from bs4 import BeautifulSoup
UA="endomorphosis-world-laws-courts/0.1 (+https://github.com/endomorphosis; polite research bot)"
OUT="data/phase4";LOG=f"{OUT}/progress.log";ST=f"{OUT}/progress.json"
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
  _META=("jurisdiction","source_name","license","retrieval_mode","retrieval_date")
  def __init__(s,fn,base):
    s.seen=set();s.cnt={};s.base=base
    # resume: reload keys of records already on disk so a re-run does not append duplicates
    if os.path.exists(fn):
      for l in open(fn,encoding="utf-8"):
        try: r=json.loads(l)
        except ValueError: continue
        s.cnt[r.get("type")]=s.cnt.get(r.get("type"),0)+1
        r0={a:b for a,b in r.items() if a not in Sink._META}
        s.seen.add(hashlib.sha1(json.dumps(r0,sort_keys=True).encode()).hexdigest())
    s.f=open(fn,"a")
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
  done[key]={"status":"ok" if pages else "failed","mode":mode,"pages":pages,"counts":sink.cnt,"cdx_captures":len(caps),"file":fn,"phase":"3"}
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
  for u in pick(sorted(links),None)[:21]:
    gate()
    if not rp.can_fetch(UA,u): continue
    if cd: time.sleep(max(0,cd-2.2))
    try: x=get(u)
    except Exception: continue
    if x.status_code==200 and "html" in x.headers.get("content-type",""): pages+=1;extract(x.text,x.url,x.url,sink,key)
  done[key]={"status":"ok","mode":"live","pages":pages,"counts":sink.cnt,"file":fn,"phase":"3"}
  json.dump(done,open(ST,"w"),indent=1);ma,df=res();log(f"LIVE {key} pages={pages} {sink.cnt} mem={ma:.1f} disk={df:.1f}")
  return pages,sink
# phase3: prefer court-location pages, deeper
KW["court"]=r"locat|contact|address|court.?finder|directory|find.?a.?court|find.?my.?court|courthouse|visit|county|district|circuit|trial|local|magistrat|municipal|justice.?court|palais|offices"
ADDR=re.compile(r"(,\s*[A-Z]{2}\s+\d{5}(-\d{4})?\b|\b[A-Z]\d[A-Z] ?\d[A-Z]\d\b|\b(NSW|VIC|QLD|WA|SA|TAS|ACT|NT)\s+\d{4}\b|\b\d{3} ?\d{3}\b.*(india|pin)|pin\s*[-:]?\s*\d{6})",re.I)
_ex=extract
def extract(html,u,src,sink,name):
  _ex(html,u,src,sink,name)
  soup=BeautifulSoup(html,"lxml");lines=[" ".join(l.split()) for l in soup.get_text("\n").split("\n")];lines=[l for l in lines if l]
  for i,l in enumerate(lines):
    if len(l)<160 and ADDR.search(l):
      ctx=[x for x in lines[max(0,i-3):i] if len(x)<120]
      nm=next((x for x in reversed(ctx) if re.search(r"court|courthouse|tribunal|justice|palais|district|county",x,re.I)),name)
      sink.emit({"type":"court","name":nm,"address":" ".join(ctx[-2:]+[l])[:300],"found_on":src})
_pick=pick
def pick(urls,home):
  ks=[u for u in urls if re.search(KW["court"],up.urlsplit(u).path,re.I)];ks.sort(key=len)
  rest=_pick(urls,home);out=([home] if home else [])+ks[:14]+rest
  s=[];[s.append(x) for x in out if x and x not in s];return s[:22]
# ======================= phase4 additions (Americas + Oceania) =======================
os.environ.setdefault("TMPDIR",(str(_LEGAL_WS) + "/courts/.tmp"))
sys.path.insert(0,os.environ.get("IPFS_DATASETS_PY",(str(_LEGAL_WS) + "/ipfs_datasets_py_fresh")))
# multilingual keywords (pt/es/fr) on top of phase3 patterns
KW["judge"]=KW["judge"]+r"|desembargador|ministr|magistrad|vocales|jueces|juízes|corte.?suprema|plenário|pleno|integrantes|composi"
KW["form"]=KW["form"]+r"|formul[aá]rio|modelos?|peticion|petici[oó]n|solicitud|requerimento|impresos"
KW["rule"]=KW["rule"]+r"|regimento|reglamento|c[oó]digo.?(de.?)?(proceso|processo|procesal)|acordos?|acuerdos?|normativ|legisla|regras"
KW["court"]=KW["court"]+r"|comarca|f[oó]rum|foros|unidades|juzgado|sedes?|ubicaci|ubica[cç]|endere[cç]o|dire[cç][aã]o|dependencias|tribunales|salas"
ADDR=re.compile(ADDR.pattern+r"|\b\d{5}-\d{3}\b|\bC\.?P\.? ?\d{5}\b|\bCEP:? ?\d{5}-?\d{3}\b|\b(av\.|avenida|rua|calle|carrera|jr\.|jir[oó]n|pasaje|boulevard|blvd)\b.*\d",re.I)
class Cap(BaseException): pass
def _to(*a): raise Cap()
signal.signal(signal.SIGALRM,_to)
JT=r"(Hon'?ble|Honourable|Hon\.|Chief Justice|Justice|Judge|Magistrate|Presidente|Desembargador[a]?|Juiz[a]?|Juez[a]?|Jueza|Ministr[oa]|Magistrad[oa]|Vocal|Dr\.?|Dra\.?)"
_ex4=extract
def extract(html,u,src,sink,name):
  _ex4(html,u,src,sink,name)
  soup=BeautifulSoup(html,"lxml")
  # official-roster judge lines in pt/es (only from pages classified as judge/roster pages)
  if "judge" in classify(u+" "+(soup.title.string if soup.title and soup.title.string else "")):
    for line in soup.get_text("\n").split("\n"):
      l=" ".join(line.split())
      if 6<len(l)<90 and re.match(r"^(Desembargador[a]?|Juiz[a]?|Juez[a]?|Jueza|Ministr[oa]|Magistrad[oa]|Presidente)\b",l,re.I): sink.emit({"type":"judge","full_name":l,"roster_url":src})
# throttled GET with 429/503 backoff (never verify=False; never bypasses challenges)
def get(url,**kw):
  tmo=kw.pop("timeout",30)
  for att in range(4):
    d=time.time()-last[0]
    if d<2.2: time.sleep(2.2-d)
    last[0]=time.time();r=S.get(url,timeout=tmo,**kw)
    if r.status_code in(429,503) and ("web.archive.org" in url or "commoncrawl" in url) and att<3:
      w=min(240,int(r.headers.get("Retry-After","0") or 0) or 30*(att+1));log(f"backoff {r.status_code} {w}s {url[:80]}");time.sleep(w);continue
    return r
  return r
# robots (records a status string per host for progress.json / sources.csv)
RST={}
def robots(base):
  if base not in RP:
    rp=urp.RobotFileParser();st="error"
    try:
      r=get(base+"/robots.txt",timeout=20);ct=r.headers.get("content-type","").lower()
      if r.status_code==200 and ("html" in ct or re.search(r"cloudflare|captcha|<html",r.text[:300],re.I)): rp=None;st="non-robots response (possible WAF/HTML)"
      elif r.status_code==200:
        rp.parse(r.text.splitlines());cd=rp.crawl_delay(UA)
        st=("200; Disallow for UA on / (live fetch skipped; archive copies only)" if not rp.can_fetch(UA,base+"/") else "200; allows * (path limits may apply)")+(f"; crawl-delay {cd}" if cd else "")
      elif r.status_code in(404,410): rp.parse([]);st="HTTP %d (no robots.txt)"%r.status_code
      else: rp=None;st="HTTP %d%s"%(r.status_code," (blocked/WAF)" if r.status_code in(403,429,503) else "")
    except Exception as e: log(f"robots err {base} {type(e).__name__}");rp=None;st="error: "+type(e).__name__
    RP[base]=rp;RST[base]=st+" ("+TODAY+")"
  return RP[base]
def keyfn(k): return re.sub(r'[^A-Za-z0-9]+','_',k)[:80]
def oscn_wayback_pass(done):
  """Oklahoma: one Wayback CDX pass for oscn.net court-location pages, via ipfs_datasets_py web_archiving engine (fetch_wayback_cdx_rows)."""
  import asyncio,urllib.parse as u2
  k="Oklahoma OSCN court locations (Wayback)"
  if done.get(k,{}).get("status") in("ok","failed"): return
  from ipfs_datasets_py.processors.web_archiving import wayback_machine_engine as W
  q=u2.urlencode([("url","oscn.net"),("matchType","domain"),("output","json"),("fl","timestamp,original,statuscode,mimetype"),("filter","statuscode:200"),("filter","mimetype:text/html"),("collapse","urlkey"),("from","2015"),("limit","4000")])
  time.sleep(3);res_=asyncio.run(W.fetch_wayback_cdx_rows("https://web.archive.org/cdx/search/cdx?"+q,timeout_seconds=120))
  rows=res_.get("results") or []
  log(f"OSCN engine CDX status={res_.get('status')} rows={len(rows)} err={str(res_.get('error'))[:100]}")
  with open(f"{OUT}/oscn_cdx_captures.jsonl","w") as f:
    for r in rows: f.write(json.dumps(r,ensure_ascii=False)+"\n")
  loc=[r for r in rows if re.search(r"court|county|location|judges|address|contact|clerk|rules|forms|directory",r.get("original",""),re.I)]
  loc.sort(key=lambda r:(len(r["original"]),r["original"]));seen=set();pick_=[]
  for r in loc:
    if r["original"] not in seen: seen.add(r["original"]);pick_.append(r)
  home=[r for r in rows if re.fullmatch(r"https?://(www\.)?oscn\.net(:80|:443)?/?",r["original"])]
  pick_=(home[-1:]+pick_)[:30]
  sink=Sink(f"{OUT}/{keyfn(k)}.jsonl",{"jurisdiction":"US-OK","source_name":k,"license":"see TERMS.md","retrieval_mode":"wayback-cdx(engine)"});pages=0
  for r in pick_:
    gate()
    try: html,src=wb(r["timestamp"],r["original"])
    except Exception as e: html=None
    if html: pages+=1;extract(html,r["original"],src,sink,"Oklahoma courts (OSCN)")
  done[k]={"status":"ok" if pages else "failed","mode":"wayback-cdx(engine)","pages":pages,"counts":sink.cnt,"cdx_captures":len(rows),"file":sink.f.name,"phase":"4","robots_txt_status":"200; Disallow: / for * (live fetch skipped; Wayback copies only) (2026-10-30)"}
  json.dump(done,open(ST,"w"),indent=1);log(f"OSCN pass pages={pages} {sink.cnt}")
def main():
  done=json.load(open(ST)) if os.path.exists(ST) else {};gate();log(f"START phase4 res={res()}")
  rows=[r for r in csv.DictReader(open("sources.csv")) if r["notes"].startswith("phase4")]
  for r in rows:
    k=r["source_name"]
    if done.get(k,{}).get("status") in("ok","failed","skipped"): continue
    gate();signal.alarm(420);sp=up.urlsplit(r["url"]);base=f"{sp.scheme}://{sp.netloc}"
    try:
      if k.startswith("Oklahoma OSCN"): robots(base);oscn_wayback_pass(done);continue
      p,_=live_source(k,r,done)
      if not p: archive_source(k,r,done)
      done[k]["robots_txt_status"]=RST.get(base,"not checked");done[k]["phase"]="4"
      json.dump(done,open(ST,"w"),indent=1)
    except Cap:
      done[k]={"status":"failed","mode":"timeout-420s","counts":{},"phase":"4","robots_txt_status":RST.get(base,"")};json.dump(done,open(ST,"w"),indent=1);log(f"TIMEOUT {k}")
    except Exception as e:
      done[k]={"status":"failed","mode":"error "+type(e).__name__+" "+str(e)[:80],"counts":{},"phase":"4","robots_txt_status":RST.get(base,"")};json.dump(done,open(ST,"w"),indent=1);log(f"ERR {k} {type(e).__name__}")
    finally: signal.alarm(0)
  json.dump(done,open(ST,"w"),indent=1);log("FINISHED phase4")
if __name__=="__main__": main()
