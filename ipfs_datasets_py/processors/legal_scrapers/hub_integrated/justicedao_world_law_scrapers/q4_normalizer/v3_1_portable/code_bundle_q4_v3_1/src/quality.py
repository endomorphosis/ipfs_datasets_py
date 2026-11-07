"""Canonical-table quality BUILD RULES (2026-10-25 PT). Pure, offline, streaming. No network, no Hub calls.
RULE H (heading-only article rows), row is DROPPED iff not protected and any of:
  H1  norm(text) == ''                                   (no content at all)
  H2  norm(text) == norm(title)                          (text just repeats the heading)
  H3  norm(text) == norm(article_number + ' ' + title) or norm(text) == norm(article_number)
  H4  norm(text) matches LABEL (bare label: 'article', 'section 5', 'schedule', 'part ii', 'chapter 3' ...)
  norm(s)= NFKC, casefold, collapse whitespace, strip leading/trailing punctuation/space.
  PROTECTED (kept, tagged metadata_json.quality_tag='repealed_heading'): text or title matches REPEAL
  (repealed/deleted/abrogated/derogated/revoked/spent/omitted/lapsed + es/fr/pt/it/de/nl forms).
RULE U (unique article ids, whole pack, all articles files in sorted order): first occurrence keeps id;
  the k-th later occurrence of the same id gets id+'#k' (k=2,3..; bumped further if that string exists
  anywhere in the pack); metadata_json gets original_id. Unique id => unique (law_id,id) too.
  laws.parquet: same rule on its 'id' column."""
import re,json,unicodedata,csv,os,pyarrow as pa,pyarrow.parquet as pq
REPEAL=re.compile(r'(?i)\b(repeal|deleted|abrogat|derogad|derogat|revoked|spent\b|omitted|lapsed|aufgehoben|weggefallen|abrog[ée]|supprim[ée]|revogad|vervallen|ingetrokken|sin contenido|abrogat[oa])')
LABEL=re.compile(r'(?i)^(?:article|art|section|sec|schedule|part|chapter|title|annex|appendix|artículo|articulo|capítulo|capitulo|título|titulo|anexo|chapitre|annexe|artigo|§)?\s*[0-9ivxlcdm]*[a-z]?$')
def norm(s):
  s=unicodedata.normalize('NFKC',s or '').casefold();s=re.sub(r'\s+',' ',s)
  return s.strip(' \t\n.:;,-–—()[]*')
NUMPFX=re.compile(r'^(?:(?:§+|art(?:icle|ículo|iculo|igo)?\.?|section|sec\.?|rule|regulation|reg\.?|schedule|part|chapter)\s*)?[0-9०-९ivxlcdm]+[a-z]?(?:\.[0-9०-९]+)*[.)]?\s*',re.I)
SUBSEC=re.compile(r'\(\s*(?:[0-9०-९]{1,3}|[a-z]|[ivx]{1,4})\s*\)')
def has_content(text):
  """Content guard (q2): text is real provision content, never a heading, if after stripping a leading number/label it
  has >20 words, or >150 chars, or a subsection marker like (1)/(a)/(१), or ends with . ; : ? । and has >6 words."""
  r=re.sub(r'\s+',' ',unicodedata.normalize('NFKC',text or '')).strip()
  r=NUMPFX.sub('',r,count=1).strip();w=len(r.split())
  if w>20 or len(r)>150 or SUBSEC.search(r): return True
  if w>6 and r.endswith(('.',';',':','?','।','؛','。')): return True
  return False
TOC=re.compile(r'(?i)(table of (contents|provisions)|arrangement of (sections|regulations|rules)|^\W*contents\W*$|índice|indice general|sommaire|inhaltsverzeichnis|विषय ?सूची|\.{4,}\s*\d*\s*$|…{2,})')
RULE=os.environ.get('QRULE','q2')
TOCHDR=re.compile(r'(?i)^(table of (contents|provisions)|arrangement of (sections|regulations|rules)|contents|índice|indice general|sommaire|inhaltsverzeichnis|विषय ?सूची)$')
LEADER=re.compile(r'^(?=.{0,300}$).{1,200}?(?:(?:\.\s?){4,}|…{2,})\s*\d{1,6}\s*$',re.S)
def is_toc_line(text):
  """q3b TOC: whole text (after number prefix, <=60 chars) is a TOC header, or one dotted-leader line ending in a page number, total <=300 chars,
  no subsection marker. Form lines with blanks (no page number) and long articles are never TOC."""
  r=re.sub(r'\s+',' ',unicodedata.normalize('NFKC',text or '')).strip()
  if not r: return False
  h=NUMPFX.sub('',r,count=1).strip(' .:-')
  if len(h)<=60 and TOCHDR.match(h): return True
  return bool(LEADER.match(r)) and not SUBSEC.search(r)
def narrow_reason(text,title,artno):
  """q3 (CoS ruling): drop only exact text==title (raw, stripped) or TOC lines; repealed kept; content guard kept."""
  if REPEAL.search(text or '') or REPEAL.search(title or ''): return None
  if is_toc_line(text): return 'T_toc_line'
  if has_content(text): return None
  if (text or '').strip()!='' and (text or '').strip()==(title or '').strip(): return 'E_text_eq_title_exact'
  return None

SUBSEC2=re.compile(r'(\(\s*(?:[0-9०-९]{1,3}|[a-z]|[ivx]{1,4})\s*\)|(?:^|\s)(?:[ivx]{1,4}|[a-z])\.\s)',re.I)
DATE=re.compile(r'(?i)\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b|\b(1[89]|20)\d{2}\b|\b(jan(uary)?|feb(ruary)?|march|april|june|july|august|sept(ember)?|oct(ober)?|nov(ember)?|dec(ember)?|enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre|janvier|février|avril|juillet|août|décembre)\b')
AMOUNT=re.compile(r'[£$€¥₹%]|\b\d+[.,]\d{2}\b|\b\d{1,3}(?:[ ,.]\d{3})+\b|\b(rs|usd|gnf|kes|bwp|nio|npr|jmd|ec\$)\b',re.I)
MODAL=re.compile(r'(?i)\b(shall|may|must|will|is|are|was|were|be|hereby|deber[áa]n?|podr[áa]n?|ser[áa]n?|est[áa]|doit|doivent|peut|peuvent|sont|est|soll|muss|wird|हुनेछ|गर्नेछ|सक्नेछ)\b')
LISTY=re.compile(r'…|_{3,}|\.{4,}|\s-\s|;|\bYes\b.*\bNo\b|:\s*$')
def short_heading(text):
  """q4 keep rule (CoS 2026-10-26): True only for a clear short heading; any doubt -> False (row kept)."""
  r=re.sub(r'\s+',' ',unicodedata.normalize('NFKC',text or '')).strip()
  r=NUMPFX.sub('',r,count=1).strip()
  if not r: return False
  if len(r.split())>8 or r.endswith(('.',';',':','?','!','।','؛','。')): return False
  if SUBSEC2.search(r) or DATE.search(r) or AMOUNT.search(r) or MODAL.search(r) or LISTY.search(r): return False
  return True
def q4_reason(text,title,artno):
  if REPEAL.search(text or '') or REPEAL.search(title or ''): return None
  if is_toc_line(text): return 'T_toc_line'
  t=(text or '').strip();ti=(title or '').strip()
  if t=='': return 'H_empty_text_heading_title' if ti and short_heading(ti) else None
  if t==ti and short_heading(t): return 'H_short_heading_exact'
  nt=norm(t)
  if LABEL.match(nt) and (ti=='' or norm(ti)==nt): return 'H_bare_label'
  return None
def heading_reason(text,title,artno):
  if RULE=='q4': return q4_reason(text,title,artno)
  if RULE=='q3': return narrow_reason(text,title,artno)
  if REPEAL.search(text or '') or REPEAL.search(title or ''): return None
  t=norm(text)
  if t=='': return 'H1_empty'
  if has_content(text): return None
  if t==norm(title): return 'H2_text_eq_title'
  if t==norm(artno) or t==norm((artno or '')+' '+(title or '')): return 'H3_text_eq_number_title'
  if LABEL.match(t): return 'H4_bare_label'
  return None
def _meta(mj,**kv):
  try: m=json.loads(mj) if mj else {}
  except Exception: m={'metadata_raw':mj}
  if not isinstance(m,dict): m={'metadata_raw':m}
  m.update(kv);return json.dumps(m,ensure_ascii=False)
def all_ids(paths):
  s=set()
  for p in paths:
    for b in pq.ParquetFile(p).iter_batches(batch_size=20000,columns=['id']): s.update(x for x in b.column(0).to_pylist() if x is not None)
  return s
def apply(src_paths,dst_dir,kind,gaps_writer,samples,sample_n=20):
  """src_paths sorted; writes same basenames into dst_dir. Returns stats."""
  st={'rows_before':0,'rows_after':0,'dropped':{},'protected_repealed':0,'id_suffixed':0}
  exist=all_ids(src_paths);seen={}
  for sp in src_paths:
    pf=pq.ParquetFile(sp);sch=pf.schema_arrow;dp=os.path.join(dst_dir,os.path.basename(sp))
    with pq.ParquetWriter(dp,sch,compression='zstd') as w:
      for b in pf.iter_batches(batch_size=500 if kind=="articles" else 50):
        d=b.to_pydict();n=b.num_rows;st['rows_before']+=n;keep=[]
        for i in range(n):
          if kind=='articles':
            r=heading_reason(d['text'][i],d['title'][i],d.get('article_number',[None]*n)[i])
            if r:
              st['dropped'][r]=st['dropped'].get(r,0)+1;gaps_writer.writerow([d['law_id'][i],d['id'][i],r])
              if len(samples)<sample_n: samples.append((d['id'][i],r,(d['title'][i] or '')[:120],(d['text'][i] or '')[:200]))
              continue
            if REPEAL.search(d['text'][i] or '') and norm(d['text'][i])==norm(d['title'][i]):
              d['metadata_json'][i]=_meta(d['metadata_json'][i],quality_tag='repealed_heading');st['protected_repealed']+=1
          oid=d['id'][i]
          if oid is not None:
            k=seen.get(oid,0)+1;seen[oid]=k
            if k>1:
              j=k;nid=f'{oid}#{j}'
              while nid in exist: j+=1;nid=f'{oid}#{j}'
              exist.add(nid);d['id'][i]=nid;d['metadata_json'][i]=_meta(d['metadata_json'][i],original_id=oid);st['id_suffixed']+=1
          keep.append(i)
        cols={c:[d[c][i] for i in keep] for c in sch.names}
        w.write_table(pa.table(cols,schema=sch));st['rows_after']+=len(keep)
  return st
def check(paths,kind):
  """returns (dup_id, dup_law_id_id, heading_left)"""
  ids=set();pairs=set();di=dp=h=0
  for p in paths:
    for b in pq.ParquetFile(p).iter_batches(batch_size=2000 if kind=="articles" else 50):
      d=b.to_pydict()
      for i in range(b.num_rows):
        x=d['id'][i]
        if x in ids: di+=1
        ids.add(x)
        if kind=='articles':
          pr=(d['law_id'][i],x)
          if pr in pairs: dp+=1
          pairs.add(pr)
          if heading_reason(d['text'][i],d['title'][i],d['article_number'][i]): h+=1
  return di,dp,h
