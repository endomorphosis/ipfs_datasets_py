"""Thailand Courts of Justice executives (ผู้บริหารศาลยุติธรรม) from the official coj.go.th page id/346295,
whose content is a single infographic image (updated 1 Oct 2569/2026). Names were transcribed from the
image (manual visual transcription; needs_review). '*' on the image = awaiting royal appointment."""
import os,json,hashlib,datetime,time,urllib.request
ROOT="/workspace/world_courts"; UA="WorldCourtsResearchBot/1.0 (court-data research; contact via Benjamin Barber)"
PAGE="https://www.coj.go.th/th/content/page/index/id/346295"; IMG="https://www.coj.go.th/cms/s1//about_coj/deeka69c.png"
POL="robots_allowed(page path not disallowed)|coj.go.th official Courts of Justice website; Website Policy page, no restrictive reuse terms found|polite 3 s/request"
ROWS=[("th-supreme-court","วีระพงศ์ สุดาวงศ์","ประธานศาลฎีกา (President of the Supreme Court)","chief",False),
 ("th-court-of-appeal","วิฐูร คลองมีคุณ","ประธานศาลอุทธรณ์ (President of the Court of Appeal)","chief",True),
 ("th-supreme-court","วรวุฒิ ทวาทศิน","รองประธานศาลฎีกา (Vice President of the Supreme Court)","associate",True),
 ("th-supreme-court","ประชา งามลำยวง","รองประธานศาลฎีกา (Vice President of the Supreme Court)","associate",True),
 ("th-supreme-court","อำนาจ โชติชะวารานนท์","รองประธานศาลฎีกา (Vice President of the Supreme Court)","associate",True),
 ("th-supreme-court","วิทยา พรหมประสิทธิ์","รองประธานศาลฎีกา (Vice President of the Supreme Court)","associate",True),
 ("th-supreme-court","จรูญ โชครุ่งวรานนท์","รองประธานศาลฎีกา (Vice President of the Supreme Court)","associate",True),
 ("th-supreme-court","สุพัฒน์ พงษ์ทัดศิริกุล","รองประธานศาลฎีกา (Vice President of the Supreme Court)","associate",True)]
img=urllib.request.urlopen(urllib.request.Request(IMG,headers={"User-Agent":UA}),timeout=60).read(); sha=hashlib.sha256(img).hexdigest()
f=f"{ROOT}/data/th/th_judges.jsonl"; have={(json.loads(l)["court_id"],json.loads(l)["name"]) for l in open(f)}
now=datetime.datetime.now(datetime.timezone.utc).isoformat(); n=0
with open(f,"a") as fh:
    for cid,name,title,pt,pending in ROWS:
        if (cid,name) in have: continue
        fh.write(json.dumps({"judge_id":f"{cid}-{hashlib.sha1(name.encode()).hexdigest()[:10]}","court_id":cid,"name":name,
          "title":title+(" — awaiting royal appointment (รอโปรดเกล้าฯ แต่งตั้ง) per page note" if pending else ""),"position_type":pt,
          "term_start":None,"term_end":None,"status":"sitting","roster_url":PAGE,"source_url":IMG,"site_policy":POL,"retrieved_at":now,
          "needs_review":True,"extraction":f"official_image_transcription: COJ executives infographic (updated 1 Oct 2569/2026), image sha256 {sha}; names transcribed visually from image",
          "license":"official public information; no licence stated"},ensure_ascii=False)+"\n"); n+=1
print("TH judges new",n)
