"""Find Gosweb doc attachments with no text layer (same item discovery/filter as ru_gosweb). Up to N items/host. -> _ocr/ru_gosweb_notext.jsonl"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import sys,json,re,html as H
sys.path.insert(0,(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/pipeline/scrapers/sasia_ru'))
sys.path.insert(0,(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
import ru_gosweb as G
from schema import place_key
N=12; D=(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/sasia_ru/_ru/')
hosts=[json.loads(l) for f in ('gosweb_hosts_verified.jsonl','gosweb_hosts_verified2.jsonl') for l in open(D+f)]
out=open((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/sasia_ru/_ocr/ru_gosweb_notext.jsonl'),'a')
for h in hosts:
    base='https://'+h['host']
    try:
        rr=G.S.get(base+'/robots.txt',timeout=(10,30)); rb=G.Robots(rr.text) if rr.status_code==200 else G.Robots(allow_all=True)
        r=G.get(base+'/ofitsialno/dokumenty/',rb)
        if not r or r.status_code!=200: continue
        ITEM=r'href="(/ofitsialno/dokumenty/[^"?#]+?_\d+\.html)"'; SUB=r'href="(/ofitsialno/dokumenty/[^"?#.]+/)"'
        items=set(re.findall(ITEM,r.text))
        for sub in list(dict.fromkeys(re.findall(SUB,r.text)))[:4]:
            if len(items)>=N*3: break
            rs=G.get(base+sub,rb); items|=set(re.findall(ITEM,rs.text)) if rs and rs.status_code==200 else set()
        items=sorted(items,key=lambda u:-int(re.search(r'_(\d+)\.html$',u).group(1)))[:N*3]; seen=0
        for u in items:
            if seen>=N: break
            rd=G.get(base+u,rb)
            if not rd or rd.status_code!=200: continue
            m=re.search(r'gw-document-page__title">(.*?)</h1>',rd.text,re.S)
            title=re.sub(r'\s+',' ',H.unescape(re.sub(r'<[^>]+>','',m.group(1)))).strip() if m else ''
            kind,dt,num=G.parse_title(title)
            if not kind or kind not in ('Решен','Поста','Устав') or G.EXCLUDE.search(title): continue
            seen+=1
            files=list(dict.fromkeys(re.findall(r'href="(/netcat_files/[^"]+\.(?:pdf|docx|doc|rtf|odt))"',rd.text,re.I)))
            if not files: continue
            texts=[]
            for f in files[:2]:
                rf=G.get(base+f,rb)
                if not rf or rf.status_code!=200: continue
                try: t,_=G.extract(rf.content,f.rsplit('.',1)[1].lower())
                except Exception: t=''
                texts.append((f,len(t.strip()),len(rf.content)))
            if texts and all(n<200 for _,n,_ in texts):
                f,_,sz=texts[0]; did=re.search(r'_(\d+)\.html$',u).group(1)
                out.write(json.dumps({'source_url':base+f,'doc_page_url':base+u,'archive_url':None,'place_id':h['place_id'],'place_key':place_key(h['place_id']),
                  'doc_id':f'gosweb:{h["host"]}:{did}','country_code':'RU','language':'ru','script':'Cyrl','source':'ru_gosweb','title':title,'number':num,'adopted_date':dt,
                  'file_type':f.rsplit('.',1)[1].lower(),'bytes':sz,'reason':'no_text_layer'},ensure_ascii=False)+'\n'); out.flush()
        print(h['host'],'done',flush=True)
    except Exception as e: print(h['host'],'err',type(e).__name__,flush=True)
