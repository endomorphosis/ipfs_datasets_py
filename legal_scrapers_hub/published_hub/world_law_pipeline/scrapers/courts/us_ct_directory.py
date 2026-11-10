"""Connecticut: parse court locations from the official Judicial Directory PDF (jud.ct.gov/directory/JudDir.pdf).
Address lines look like '90 Washington Street, Hartford 06106'; the court name is the page's heading line."""
import re,sys,json,subprocess,urllib.request,datetime,os
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from robots_policy import policy,UA
U="https://www.jud.ct.gov/directory/JudDir.pdf"
def run(out):
    pdf="/workspace/world_courts/data/us/cache/ct_JudDir.pdf"
    open(pdf,"wb").write(urllib.request.urlopen(urllib.request.Request(U,headers={"User-Agent":UA}),timeout=60).read())
    pol=policy(U);now=datetime.datetime.now(datetime.UTC).isoformat()
    pages=subprocess.run(["pdftotext","-layout",pdf,"-"],capture_output=True,text=True).stdout.split("\f")
    recs={}
    for i,p in enumerate(pages):
        lines=[l.strip() for l in p.split("\n") if l.strip()]
        if not lines: continue
        head=next((l for l in lines[:4] if re.search(r"Court|Judicial District|G\.A\.|Juvenile|Session|Housing|Division|Center",l)),lines[0])
        head=re.sub(r"\s{2,}.*","",head)
        for l in lines:
            m=re.match(r"^(\d{1,5}[A-Za-z]?\s+[A-Z][\w .'&-]+?(?:Street|St\.?|Avenue|Ave\.?|Road|Rd\.?|Boulevard|Blvd\.?|Drive|Square|Place|Lane|Way|Highway|Turnpike|Plaza|Pike)\b)[^,]*,\s*([A-Z][A-Za-z .]+?)\s+(0\d{4})\b",l)
            if m and i>=70 and not re.search(r"Division|Administrat|Services|Technology|Operations",head):
                k=(m.group(1).lower(),m.group(3))
                recs.setdefault(k,{"court_id":None,"name":head,"level":None,"court_system":"state","country_code":"US","subdivision":"US-CT","jurisdiction":None,"parent_court_id":None,
                 "address":{"street":m.group(1),"city":m.group(2).strip(),"postcode":m.group(3),"region":"CT","country":"US"},"geo":None,"place_ids":[],
                 "source_url":f"{U}#page={i+1}","source_kind":"official","site_policy":pol,"retrieved_at":now,"parser":"us_ct_directory"})
    with open(out,"w") as f:
        for r in recs.values(): f.write(json.dumps(r)+"\n")
    print("CT",len(recs))
if __name__=="__main__": run(sys.argv[1])
