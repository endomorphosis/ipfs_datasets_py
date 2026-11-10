import sys, re, json, collections, os
sys.path.insert(0, '/workspace/packaging/lib'); from ua_xml import docs
import pyarrow as pa, pyarrow.parquet as pq
OUT='/workspace/packaging/out/ipfs_ukraine_laws_supplement_review_20261023'; os.makedirs(f'{OUT}/data',exist_ok=True)
X='/workspace/legal-corpora/ua_local/extracted/'
def nid(x): return re.sub(r'[/\s]+','-',(x or '').strip().lower())
def nt(x): return ' '.join(re.sub(r'[«»"“”\'’`]','',(x or '').lower()).split())
def nd(d):
    m=re.match(r'(\d{1,2})\.(\d{1,2})\.(\d{2,4})',d or '')
    if not m: return None
    y=m.group(3); y=('19'+y if int(y)>30 else '20'+y) if len(y)==2 else y
    return f'{y}-{int(m.group(2)):02d}-{int(m.group(1)):02d}'
ref=pq.read_table('/workspace/packaging/ref/ipfs_ukraine_laws/data/laws.parquet',columns=['identifier','official_identifier','title','date']).to_pylist()
refI={nid(r[k]) for r in ref for k in ('identifier','official_identifier') if r[k]}
refT={(nt(r['title']),r['date']) for r in ref}
SUF={'Кабінет Міністрів України':{'Постанова':'п','Розпорядження':'р'}}
def ids(d):
    n=nid(d.get('number')); dt=nd(d.get('date_acc')); out={n}
    s=SUF.get(d.get('publisher'),{}).get(d.get('type'))
    if s and dt and n: out.add(f'{n}-{dt[2:4]}-{s}')
    return out
c=collections.Counter(); keep={}; seen=set()
for d in docs(X+'edrnpa_cards_2026-10-18.xml'):
    c['raw_cards']+=1; k=d.get('reestr_code')
    if not k or k in seen: c['dup_or_nocode_in_source']+=1; continue
    seen.add(k)
    if ids(d)&refI: c['id_dups']+=1; continue
    if (nt(d.get('name')),nd(d.get('date_acc'))) in refT: c['title_date_dups']+=1; continue
    keep[k]=d
sch=pa.schema([(n,pa.string()) for n in ['id','reestr_code','reestr_date','title','date','number','publisher','type','law_status','publication','keywords','text','source','license']])
w=pq.ParquetWriter(f'{OUT}/data/ua_supplement.parquet',sch,compression='zstd'); buf=[]; done=set()
def flush():
    global buf
    if buf: w.write_table(pa.Table.from_pylist(buf,schema=sch)); buf=[]
for t in docs(X+'edrnpa_texts_2026-10-18.xml'):
    c['raw_texts']+=1; k=t.get('reestr_kod'); d=keep.get(k)
    if not d or k in done: continue
    done.add(k); txt=re.sub(r'[ \t]+',' ',re.sub(r'\s*\n\s*','\n',t.get('TEXT_ED') or '')).strip()
    buf.append(dict(id='ua-edrnpa-'+k.replace('/','-'),reestr_code=k,reestr_date=nd(d.get('reestr_date')),title=d.get('name'),date=nd(d.get('date_acc')),number=d.get('number'),publisher=d.get('publisher'),type=d.get('type'),law_status=d.get('status'),publication=d.get('publication'),keywords=d.get('keywords'),text=txt or None,source='data.gov.ua EDRNPA 25-edrnpa.zip 2026-10-18',license='data.gov.ua open data (verify)'))
    if len(buf)>=2000: flush()
for k,d in keep.items():
    if k not in done:
        c['final_card_only_no_text']+=1
        buf.append(dict(id='ua-edrnpa-'+k.replace('/','-'),reestr_code=k,reestr_date=nd(d.get('reestr_date')),title=d.get('name'),date=nd(d.get('date_acc')),number=d.get('number'),publisher=d.get('publisher'),type=d.get('type'),law_status=d.get('status'),publication=d.get('publication'),keywords=d.get('keywords'),text=None,source='data.gov.ua EDRNPA 25-edrnpa.zip 2026-10-18',license='data.gov.ua open data (verify)'))
flush(); w.close(); c['final']=len(keep); c['final_with_text']=len(done)
json.dump(dict(c),open(f'{OUT}/summary.json','w'),indent=1); print(dict(c))
