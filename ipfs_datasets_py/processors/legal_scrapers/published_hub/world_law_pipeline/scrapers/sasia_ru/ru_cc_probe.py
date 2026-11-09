"""Retry Common Crawl index for RU regional NPA portals; logs capture counts per host/crawl."""
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import requests,json,time
HOSTS=["pravo.gov66.ru","pravo.samregion.ru","pravo.tatarstan.ru","pravo.orb.ru","publication.pravo.gov.ru","pravo.gov.ru","pravo-search.minjust.ru","docs.cntd.ru","pravo.e-dag.ru","pravo.nso.ru","pravo.mosreg.ru","publication.krasnodar.ru","law.admtyumen.ru","pravo.kamgov.ru"]
CR=["CC-MAIN-2026-34","CC-MAIN-2026-30","CC-MAIN-2026-26"]
out=open((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/sasia_ru/_ru/cc_probe.jsonl'),'a')
for h in HOSTS:
    for c in CR:
        res=None
        for att in range(4):
            try:
                r=requests.get(f"https://index.commoncrawl.org/{c}-index",params={"url":h+"/*","output":"json","filter":"status:200","limit":"1000"},timeout=90)
                if r.status_code==200: 
                    L=[json.loads(l) for l in r.text.splitlines() if l.startswith('{')]
                    res={"n":len(L),"mimes":sorted({x.get('mime') for x in L})[:5],"sample":[x['url'] for x in L[:3]]};break
                if r.status_code==404: res={"n":0};break
            except Exception as e: pass
            time.sleep(30*(att+1))
        out.write(json.dumps({"host":h,"crawl":c,"res":res,"ts":time.strftime('%FT%T')})+"\n"); out.flush(); time.sleep(5)
