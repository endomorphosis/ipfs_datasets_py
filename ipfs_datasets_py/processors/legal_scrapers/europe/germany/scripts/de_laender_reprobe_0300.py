import time,json,requests,datetime
UA='justicedao-legal-corpus/1.0 (+https://huggingface.co/justicedao; polite municipal-law archiver)'
P={'BE':'https://gesetze.berlin.de','HE':'https://www.rv.hessenrecht.hessen.de','HH':'https://www.landesrecht-hamburg.de','MV':'https://www.landesrecht-mv.de','RP':'https://landesrecht.rlp.de','SH':'https://www.gesetze-rechtsprechung.sh.juris.de','SL':'https://recht.saarland.de','ST':'https://www.landesrecht.sachsen-anhalt.de','TH':'https://landesrecht.thueringen.de'}
out=open('/workspace/legal-corpora/de_laender_20261102/reprobe_20261103_0300.jsonl','a')
for k,u in P.items():
    r=dict(land=k,url=u+'/',at=datetime.datetime.now().astimezone().isoformat(timespec='seconds'))
    try: x=requests.get(u+'/',headers={'User-Agent':UA},timeout=30,verify=True,allow_redirects=True); r.update(status=x.status_code,final_url=x.url,bytes=len(x.content),tdm='tdm-reservation' in x.text[:5000])
    except Exception as e: r.update(status=None,error=type(e).__name__+': '+str(e)[:200])
    out.write(json.dumps(r)+'\n'); out.flush(); print(r,flush=True); time.sleep(6)
