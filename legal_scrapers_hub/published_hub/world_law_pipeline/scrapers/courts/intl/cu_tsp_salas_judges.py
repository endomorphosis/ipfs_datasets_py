"""Cuba Tribunal Supremo Popular (tsp.gob.cu, live): magistrados listed on each Sala page (name + role).
Public names/titles only. Dedupe on normalized name against existing cu_judges rows."""
import json,re,html,time,datetime,urllib.request,unicodedata
ROOT="/workspace/world_courts"; UA="WorldCourtsResearchBot/1.0 (court-data research; contact via Benjamin Barber)"
B="https://www.tsp.gob.cu/"
SALAS=[("sala-de-lo-penal","Sala de lo Penal"),("sala-de-lo-civil-familia-y-administrativo","Sala de lo Civil, de Familia y de lo Administrativo"),
       ("sala-de-lo-mercantil","Sala de lo Mercantil"),("sala-del-trabajo-y-de-la-seguridad-social","Sala del Trabajo y de la Seguridad Social"),
       ("sala-de-los-delitos-contra-la-seguridad-del-estado","Sala de los Delitos contra la Seguridad del Estado"),("sala-de-lo-militar","Sala de lo Militar")]
POL="robots_ignored_per_user_authorization|tsp.gob.cu official Tribunal Supremo Popular website; Términos y condiciones page, public information|polite 3 s/request"
def norm(x): return re.sub(r"[^a-z]","",unicodedata.normalize("NFKD",x).encode("ascii","ignore").decode().lower())
f=f"{ROOT}/data/cu/cu_judges.jsonl"; have={norm(json.loads(l)["name"]) for l in open(f)}
now=datetime.datetime.now(datetime.timezone.utc).isoformat(); n=0
with open(f,"a") as fh:
    for slug,sala in SALAS:
        import subprocess
        s=""
        for k in range(3):  # python TLS to tsp.gob.cu is flaky (UNEXPECTED_EOF); curl with same UA as fallback
            r=subprocess.run(["curl","-s","-m","60","-A",UA,B+slug],capture_output=True); s=r.stdout.decode("utf-8","replace")
            if "<main" in s: break
            time.sleep(5)
        if "<main" not in s: print("fail",slug); continue
        time.sleep(3)
        s=s[s.find("<main"):]
        t=re.sub(r"<style.*?</style>|<script.*?</script>","",s,flags=re.S)
        t=re.sub(r'<a[^>]*href="(/[^"]*)"[^>]*>',r" [A \1] ",t); t=html.unescape(re.sub(r"\s+"," ",re.sub(r"<[^>]+>"," ",t)))
        for m in re.finditer(r"\[A (/[^\]]+)\] \[A \1\] (.+?) (Presidente?a? de la Sala[^\[]*?|Magistrad[oa]|Vicepresident[ea])(?= \[A | Sobrescribir|$| [A-ZÁÉÍÓÚÑ]\w+ )",t):
            url,name,role=m.group(1),m.group(2).strip(),m.group(3).strip()
            if len(name)>60 or norm(name) in have: continue
            have.add(norm(name)); chief=role.lower().startswith("president")
            fh.write(json.dumps({"judge_id":f"cu-supreme-court-{norm(name)[:40]}","court_id":"cu-supreme-court","name":name,
              "title":f"{role} — {sala}, Tribunal Supremo Popular" if not role.endswith(sala.replace('Sala ','')) else f"{role}, Tribunal Supremo Popular",
              "position_type":"presiding" if chief else "associate","term_start":None,"term_end":None,"status":"sitting","roster_url":B+slug,"source_url":"https://www.tsp.gob.cu"+url,
              "site_policy":POL,"retrieved_at":now,"needs_review":False,"extraction":f"TSP {sala} page member list (live HTML)","license":"official public information; no licence stated"},ensure_ascii=False)+"\n"); n+=1
print("CU judges new",n)
