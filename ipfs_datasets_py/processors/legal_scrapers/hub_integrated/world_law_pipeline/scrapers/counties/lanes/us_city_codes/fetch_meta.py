import json,re,time,sys,os,urllib.request
from concurrent.futures import ThreadPoolExecutor
s=json.load(open('raw/aml.json'))['siblings']
paths=[x['rfilename'] for x in s if re.search(r'metadata/\d+\.json$',x['rfilename'])]
B='https://huggingface.co/datasets/endomorphosis/american_municipal_law/resolve/main/'
def go(p):
    out='raw/meta/'+p.replace('/','__')
    if os.path.exists(out): return 0
    for i in range(4):
        try:
            r=urllib.request.Request(B+p,headers={'User-Agent':'world-laws-planning/0.1 (read-only metadata)'})
            d=urllib.request.urlopen(r,timeout=30).read()
            open(out,'wb').write(d); return 0
        except Exception as e:
            if '429' in str(e): time.sleep(20*(i+1))
            else: time.sleep(2)
    return 1
with ThreadPoolExecutor(6) as ex: errs=sum(ex.map(go,paths))
print('done',len(paths),'errs',errs)
