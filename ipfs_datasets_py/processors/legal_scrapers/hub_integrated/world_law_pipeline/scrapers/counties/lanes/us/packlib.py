"""Shared pack builder: laws/articles parquet in the ipfs_kenya_municipal_laws schema (zstd)."""
import json,hashlib,re,datetime
import pyarrow as pa, pyarrow.parquet as pq
LAW_COLS=["id","title","text","source_url","source_type","jurisdiction","country","language","eli","date","date_issued","retrieved_at","license","law_status","identifier","official_identifier","article_count","json_path","metadata_json","municipality_id","municipality_name","wikidata_qid"]
ART_COLS=["law_id","id","title","text","source_url","document_number","article_number","record_type","metadata_json","municipality_id","municipality_name","wikidata_qid"]
def now(): return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
def sha256(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(1<<20),b''): h.update(b)
    return h.hexdigest()
def split_sections(text, min_len=1, start_no=1):
    """Split on 'N.' section starts (strictly sequential numbering) after the enacting formula.
    Handles side-heading layouts where the number is mid-line ('Short title and 1. This Act ...')."""
    m=re.search(r'(?im)^\s*(ENACTED by|BE IT ENACTED)[^\n]*',text) or re.search(r'(?im)^\s*AN ACT (of|to)[^\n]*',text)
    start=m.start() if m else 0
    lines=text[start:].split('\n'); out=[]; expect=start_no; cur=None; prev=''
    rx=re.compile(r'^(?P<pre>[^\d]{0,60}?)(?<!\d)(?P<n>\d{1,3})\s*[\.\-\u2014]\s*(?P<rest>\S.*)$')
    for l in lines:
        l=re.sub(r'^[\s|»>•_~\]\[]+','',l)
        mm=rx.match(l)
        if mm and int(mm.group('n'))==expect and (not mm.group('pre').strip() or mm.group('pre').strip()[0].isupper() or mm.group('pre').rstrip().endswith('follows') ) and re.match(r'[A-Z(\u201c"\']',mm.group('rest')):
            if cur: out.append(cur)
            pre=mm.group('pre').strip()
            if pre and pre[0].isupper() and not pre.endswith('follows'): heading=pre
            elif prev.strip() and len(prev.strip())<90 and not re.match(r'^\(?\d',prev.strip()) and not prev.strip().endswith(('—','-',';',',')): heading=prev.strip()
            else: heading=''
            cur={'n':expect,'heading':heading,'lines':[f"{expect}. {mm.group('rest').strip()}"]}; expect+=1
        elif cur is not None: cur['lines'].append(l.strip())
        if l.strip(): prev=l
    if cur: out.append(cur)
    return [(c['n'],c['heading'],'\n'.join(x for x in c['lines'] if x).strip()) for c in out if len('\n'.join(c['lines']))>=min_len]
def write_pack(outdir, laws, arts, laws_name, arts_name):
    import os
    os.makedirs(outdir+'/data',exist_ok=True)
    lt=pa.Table.from_pylist([{k:(int(r[k]) if k=='article_count' else (r.get(k) or '')) for k in LAW_COLS} for r in laws],schema=pa.schema([(c,pa.int32() if c=='article_count' else pa.string()) for c in LAW_COLS]))
    at=pa.Table.from_pylist([{k:(r.get(k) or '') for k in ART_COLS} for r in arts],schema=pa.schema([(c,pa.string()) for c in ART_COLS]))
    pq.write_table(lt,f"{outdir}/data/{laws_name}",compression='zstd')
    pq.write_table(at,f"{outdir}/data/{arts_name}",compression='zstd')
    return lt.num_rows,at.num_rows
