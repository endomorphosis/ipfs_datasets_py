"""Phase 4 step 6: add missing US courts from crosswalk/cl_courts_without_entity.csv (highest unmatched_rows_weight first).
Official court sites only (live if robots allow & no challenge, else Wayback id_ copy); court records carry courtlistener_id."""
import sys,os;sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)));import phase4 as P
import csv,json,re,time,urllib.parse as up
from bs4 import BeautifulSoup
OVR={ # official site overrides (current domains); CSV court_url used as extra fallback
"tax":["https://www.ustaxcourt.gov/contact_us.html","https://www.ustaxcourt.gov/"],
"nyappdiv":["https://www.nycourts.gov/courts/appellatedivisions.shtml","https://www.nycourts.gov/courts/ad1/","https://www.nycourts.gov/courts/ad2/","https://www.nycourts.gov/courts/ad3/","https://www.nycourts.gov/courts/ad4/"],
"fladistctapp":["https://www.flcourts.gov/Florida-Courts/District-Courts-of-Appeal"],
"ohioctapp":["https://www.supremecourt.ohio.gov/courts/court-of-appeals/"],
"texapp":["https://www.txcourts.gov/courts-of-appeals/"],
"bia":["https://www.justice.gov/eoir/board-of-immigration-appeals"],
"lactapp":["https://www.la-fcca.org/","https://www.lasc.org/Court_of_Appeal"],
"calctapp":["https://courts.ca.gov/courts/courts-appeal"],
"la":["https://www.lasc.org/","https://www.lasc.org/About_The_Court"],
"pasuperct":["https://www.pacourts.us/courts/superior-court"],
"cadc":["https://www.cadc.uscourts.gov/"],
"tenncrimapp":["https://www.tncourts.gov/courts/court-criminal-appeals"],
"illappct":["https://www.illinoiscourts.gov/courts/appellate-court/"],
"njsuperctappdiv":["https://www.njcourts.gov/courts/appellate"],
"ala":["https://judicial.alabama.gov/Courts/Supreme-Court"],
"mich":["https://www.courts.michigan.gov/courts/michigan-supreme-court/"],
"gactapp":["https://www.gaappeals.us/"],
"tennctapp":["https://www.tncourts.gov/courts/court-appeals"],
"fla":["https://supremecourt.flcourts.gov/"],
"washctapp":["https://www.courts.wa.gov/appellate_trial_courts/"],
"uscfc":["https://www.uscfc.uscourts.gov/"],
"prapp":["https://www.ramajudicial.pr/"],
"pa":["https://www.pacourts.us/courts/supreme-court"],
"miss":["https://courts.ms.gov/"],
"wva":["https://www.courtswv.gov/supreme-court"],
"iowactapp":["https://www.iowacourts.gov/iowa-courts/court-of-appeals/"],
"cafc":["https://www.cafc.uscourts.gov/"],
"wash":["https://www.courts.wa.gov/appellate_trial_courts/"],
"mont":["https://courts.mt.gov/"],
"ncbizct":["https://www.nccourts.gov/courts/business-court"],
"pacommwct":["https://www.pacourts.us/courts/commonwealth-court"],
"kyctapp":["https://kycourts.gov/Courts/Court-of-Appeals/Pages/default.aspx"],
"ill":["https://www.illinoiscourts.gov/"],
"vactapp":["https://www.vacourts.gov/courts/cav/home"],
"delsuperct":["https://courts.delaware.gov/superior/"],
"michctapp":["https://www.courts.michigan.gov/courts/court-of-appeals/"],
"texcrimapp":["https://www.txcourts.gov/cca/"],
"wisctapp":["https://www.wicourts.gov/courts/appeals/"],
"moctapp":["https://www.courts.mo.gov/page.jsp?id=261"],
}
SKIP={"oklaag":"Oklahoma Attorney General Reports are opinions of the AG, not a court; no courthouse to locate."}
N=int(os.environ.get("US_N","60"))
rows=[r for r in csv.DictReader(open("crosswalk/cl_courts_without_entity.csv"))]
rows.sort(key=lambda r:-int(r["unmatched_rows_weight"] or 0))
rows=[r for r in rows if r["system"] in("federal","state","")][:N]
done=json.load(open(P.ST))
def lines_of(html):
  s=BeautifulSoup(html,"lxml")
  for t in s(["script","style","nav"]): t.decompose()
  return [" ".join(l.split()) for l in s.get_text("\n").split("\n") if l.strip()]
def fetch(u,doc):
  sp=up.urlsplit(u);base=f"{sp.scheme}://{sp.netloc}";rp=P.robots(base)
  if rp is not None and rp.can_fetch(P.UA,u):
    try:
      x=P.get(u)
      if x.status_code==200 and "html" in x.headers.get("content-type","html") and not re.search(r"cf-chl|captcha|Just a moment",x.text[:3000],re.I): return x.text,x.url,"live"
      doc["blocked"].append(f"{u} http {x.status_code}")
    except Exception as e: doc["blocked"].append(f"{u} {type(e).__name__}")
  else: doc["blocked"].append(f"{u} robots-disallow/unreadable ({P.RST.get(base)})")
  # Wayback fallback (CDX 200 capture of exact URL, id_ replay)
  try:
    r=P.get("https://web.archive.org/cdx/search/cdx",params={"url":u,"output":"json","fl":"timestamp,original","filter":"statuscode:200","from":"2022","limit":"-1"},timeout=90)
    j=r.json() if r.status_code==200 and r.text.strip() else []
    if len(j)>1:
      html,src=P.wb(j[-1][0],j[-1][1])
      if html: return html,src,"wayback-cdx"
  except Exception as e: doc["blocked"].append(f"wayback {u} {type(e).__name__}")
  return None,None,None
sink=P.Sink(f"{P.OUT}/US_missing_courts_crosswalk.jsonl",{"jurisdiction":"US","source_name":"US missing courts (CourtListener crosswalk)","license":"see TERMS.md","retrieval_mode":"live-or-wayback"})
key="US missing courts (CourtListener crosswalk)"
for r in rows:
  cid=r["courtlistener_id"]
  if cid in SKIP: sink.emit({"type":"court","name":r["cl_full_name"],"courtlistener_id":cid,"address":None,"address_status":"skipped: "+SKIP[cid],"found_on":r["court_url"]});continue
  P.gate();P.signal.alarm(240);doc={"blocked":[]};urls=OVR.get(cid,[])+([r["court_url"]] if r["court_url"] else []);n=0;found=0
  try:
    for u in urls[:5]:
      html,src,mode=fetch(u,doc)
      if not html: continue
      n+=1;L=lines_of(html)
      for i,l in enumerate(L):
        if len(l)<160 and P.ADDR.search(l) and re.search(r"[A-Za-z]{3}",l):
          ctx=[x for x in L[max(0,i-3):i] if len(x)<120]
          nm=next((x for x in reversed(ctx) if re.search(r"court|tribunal|board|justice|district|department|appeal",x,re.I)),r["cl_full_name"])
          sink.emit({"type":"court","name":nm,"courtlistener_id":cid,"cl_full_name":r["cl_full_name"],"address":" ".join(ctx[-2:]+[l])[:300],"found_on":src,"fetch_mode":mode});found+=1
      if found>=1 and n>=2: break
  except P.Cap: doc["blocked"].append("timeout")
  finally: P.signal.alarm(0)
  sink.emit({"type":"court","name":r["cl_full_name"],"courtlistener_id":cid,"address":None,"address_status":"found %d address lines"%found if found else "no address parsed from official pages","website":(urls[0] if urls else None),"found_on":(urls[0] if urls else None),"blocked_notes":doc["blocked"][:4]})
  P.log(f"US {cid} pages={n} addr={found} blocked={len(doc['blocked'])}")
done[key]={"status":"ok","mode":"live-or-wayback","counts":sink.cnt,"file":sink.f.name,"phase":"4","robots_txt_status":"per host; see progress.log"}
json.dump(done,open(P.ST,"w"),indent=1);P.log(f"DONE US additions {sink.cnt}")
