"""Build rules rows (world_courts 'rules' config), rule-set->court crosswalk, and upstream files for justicedao/ipfs_court_rules.
Usage: build_state.py NV   (needs <st>_sources.py with SETS and cached raw files via rules_common.cached)."""
import sys,os,re,json,importlib,hashlib,datetime
import pandas as pd
from rules_common import *
from rules_build import *
OUT=ROOT+"/rules/out";UP=OUT+"/upstream";os.makedirs(UP+"/state_court_rules_jsonld",exist_ok=True);os.makedirs(UP+"/state_court_rules_parquet_cid",exist_ok=True)
CLASS_RE={"district":r"judicial district|district court|circuit court|superior court|county courthouse|regional justice center|courthouse|justice center","justice":r"justice court|justice center|township|county courthouse|courthouse|regional justice center","municipal":r"municipal"}
def load_courts(st):
    out=[]
    for l in open(ROOT+"/data/us/us_courthouses.jsonl"):
        r=json.loads(l)
        if r["subdivision"]!="US-"+st: continue
        out.append(r)
    return out
def classify(c,cls):
    n=(c.get("name") or "")+" "+(c.get("official_name") or "")
    if c.get("court_system")=="federal" or c.get("level") in ("federal_district","other"): return False
    if cls=="supreme": return c.get("level") in ("supreme","appellate")
    if cls=="justice" and re.search(r"municipal",n,re.I): return False
    if cls=="district" and re.search(r"justice court|municipal",n,re.I) and not re.search(r"district",n,re.I): return False
    return bool(re.search(CLASS_RE[cls],n,re.I)) or (c.get("level") is None and cls in("district","justice") and bool(re.search(r"court",n,re.I)))
def crosswalk(st,rs_id,scope,courts):
    rows=[]
    for c in courts:
        for cls in scope["classes"]:
            if not classify(c,cls): continue
            fips=c.get("county_fips")
            if scope.get("fips") and fips not in scope["fips"]: continue
            if scope.get("fips_exclude") and fips in scope["fips_exclude"]: continue
            n=(c.get("name") or "")+" "+(c.get("official_name") or "")
            if cls=="supreme": basis,conf="statewide:supreme_court","high"
            elif scope.get("name_re") and re.search(scope["name_re"],n,re.I): basis,conf=f"local_rule:name_match+county","high"
            elif scope.get("fips"): basis,conf="local_rule:county_fips+court_class","medium"
            else: basis,conf=f"statewide:{cls}_courts","medium" if re.search(CLASS_RE[cls].split("|")[0],n,re.I) else "low"
            rows.append({"rule_set_id":rs_id,"court_id":c["court_id"],"court_name":c.get("name"),"link_basis":basis,"link_confidence":conf});break
    return rows
def upstream_record(st,sname,rs,r,part,pol,url,src_file,date):
    ident=r["identifier"];fam=rs["family"]
    ch=r.get("part");capsh=r.get("caps_heading")
    obj={"@context":{"@vocab":"https://schema.org/","state":f"https://www.usa.gov/states/{st.lower()}","stateCode":"state:code","sectionNumber":"state:sectionNumber","sourceUrl":"state:sourceUrl"},
     "@type":"Legislation","@id":f"urn:state:{st.lower()}:court-rule:{ident}","identifier":ident,"name":r["title"] or f"{rs['abbr']} Rule {r['num']}",
     "isPartOf":{"@type":"CreativeWork","name":rs["name"],"identifier":f"{st}-{rs['abbr']}-rules"},"legislationType":"court_rule","stateCode":st,"stateName":sname,
     "titleNumber":None,"titleName":rs["name"],"chapterNumber":ch[0] if ch else None,"chapterName":(ch[1] if ch else capsh),"sectionNumber":f"{rs['abbr']} {r['num']}","sectionName":r["title"] or None,
     "dateModified":date,"sourceUrl":url,"chapter":None,"preamble":None,"citations":None,"legislativeHistory":None,
     "text":r["upstream_text"],"subsections":[],"parser_warnings":r["warnings"],"procedureFamily":fam,"datasetFamily":fam,"code_name":rs["name"],"ipfs_cid":None,
     "source_file":src_file,"source_kind":"world_courts:"+("html" if src_file.endswith(("html","htm")) else "pdf")+":"+pol}
    return obj
def main(st):
    S=importlib.import_module(st.lower()+"_sources");sname=STATES[st];courts=load_courts(st)
    rows=[];xw=[];ups=[];stats=[]
    for ent in S.SETS:
        fname,name,abbr,fam,level,scope=ent[:6];opts=ent[6] if len(ent)>6 else {}
        PG=None
        if opts.get("pages"):
            PG=getattr(S,opts["pages"])();key=abbr;url=None;pol=None;sha=None;pdf_rel=None;meta={"fetched":None}
            rules=[{"num":p["num"],"title":p["title"],"body":p["body"],"part":p.get("part"),"caps_heading":p.get("caps"),"start":i,"_p":p} for i,p in enumerate(PG)]
        else:
            full=fname if fname.startswith("http") else S.B+fname
            ispdf=opts.get("kind")=="pdf" or full.lower().split("?")[0].endswith(".pdf")
            key=st.lower()+"_"+(fname if not fname.startswith("http") else abbr+(".pdf" if ispdf else ".html"))
            key=key.replace("/","_");b,url,pol=cached(full,key)
            if b is None: print("MISSING",fname);continue
            meta=json.load(open(RAW+"/"+key+".meta"));sha=hashlib.sha256(b).hexdigest()
            pdf_rel=None
            if ispdf:
                os.makedirs(f"{PDFDIR}/{st}",exist_ok=True);pp=f"{PDFDIR}/{st}/{sha}.pdf"
                if not os.path.exists(pp): open(pp,"wb").write(b)
                pdf_rel=f"rules/pdf/{st}/{sha}.pdf";text=re.sub(r"\n\d{1,3}(?=\n)","",pdf_text(pp,layout=opts.get("layout",False),mode=opts.get("pdfmode")))
            else: text=html_text(b)
            if opts.get('noise'): text=re.sub(opts['noise'],'',text,flags=re.M); text=re.sub(r'\n{2,}','\n',text)
            if opts.get("segments"):
                parts_=[]
                for a_,z_ in opts["segments"]:
                    ma=re.search(a_,text,re.M);mz=re.search(z_,text[ma.end():],re.M) if ma else None
                    if ma: parts_.append(text[ma.start():(ma.end()+mz.start()) if mz else len(text)])
                text="\n".join(parts_)
            if opts.get("cut_before"):
                m0=re.search(opts["cut_before"],text,re.M)
                if m0: text=text[m0.start():]
            head=re.compile(opts["head"],re.M) if opts.get("head") else HEAD
            rules=extract(text,head,opts.get('capsfilter',False),opts.get('dropshort',st!='NV'),opts.get('titlewrap',st not in ('NV','HI','NC','TX')),opts.get('capswrap',False));
        if opts.get('toctitles'):
            tt={}
            for mm in re.finditer(r"^RULE\s+(\d+\.\d+)\.\s+([A-Z][^\n]*)\n?([^\n]*)",text,re.M):
                a,b_=mm.group(2),mm.group(3)
                if not re.search(r"\.{4,}\s*\d+\s*$",a): continue
                if not re.search(r"\.{4,}\s*\d+\s*$",a) : continue
                t=re.sub(r"\s*\.{4,}\s*\d+\s*$","",a).strip()
                tt.setdefault(mm.group(1),t)
            for mm in re.finditer(r"^RULE\s+(\d+\.\d+)\.\s+([A-Z][^\n.]*[^\n.\d ])\n([A-Z][^\n]*?)\s*\.{4,}\s*\d+\s*$",text,re.M):
                tt[mm.group(1)]=(mm.group(2)+" "+mm.group(3)).strip()
            for r in rules:
                if not r['title'] and r['num'] in tt: r['title']=tt[r['num']]
        if opts.get('stripeff'):
            for r in rules: r['title']=re.sub(r'\s*Effective\s+[A-Z][a-z]+ \d{1,2}, \d{4}\s*$','',r['title']).strip()
        if opts.get('dropdots'): rules=[r for r in rules if not re.search(r'(?:\.\s?){12,}',r['body'])]
        if opts.get('droptitlebr'): rules=[r for r in rules if not re.match(r'^\[(?:Rescinded|Reserved|Abrogated|Repealed|Deleted|Vacated|Omitted|Transferred)',r['title'] or '',re.I)]
        if opts.get('dropempty'): rules=[r for r in rules if r['body'].strip()]
        if opts.get('mergedup'):
            seen={};outr=[]
            for r in rules:
                if r['num'] in seen:
                    p=seen[r['num']];p['body']=(p['body']+"\n"+(r['title']+". " if r['title'] else "")+r['body']).strip()
                else: seen[r['num']]=r;outr.append(r)
            rules=outr
        if opts.get('dropbracket'):
            rules=[r for r in rules if not (len(r['body'])<160 and re.match(r"^\W*\[?\(?(?:Repealed|Transferred|Reserved|Rescinded|Deleted|Abrogated|Omitted)",r['body'],re.I)) and not re.match(r"^(?:CHAPTER\s+\d|SUPERIOR COURT|SUPREME COURT|APPELLATE COURT|RULES OF )",r['title'])]
        if opts.get('longestdup'):
            best={}
            for i_,r in enumerate(rules):
                if r['num'] not in best or len(r['body'])>len(rules[best[r['num']]]['body']): best[r['num']]=i_
            rules=[r for i_,r in enumerate(rules) if best[r['num']]==i_]
        if opts.get('bestdup'):
            from collections import defaultdict
            grp=defaultdict(list)
            for i_,r in enumerate(rules): grp[r['num']].append(i_)
            real={}
            for n_,ix in grp.items():
                if len(ix)>1: real[n_]=min(ix,key=lambda i_:(len(rules[i_]['title']) if len(rules[i_]['title'])>=8 and rules[i_]['title'][0].isupper() else 999,i_))
            outr=[]
            for i_,r in enumerate(rules):
                if r['num'] in real and real[r['num']]!=i_ and outr:
                    outr[-1]['body']=(outr[-1]['body']+"\n"+(r['title']+". " if r['title'] else "")+r['body']).strip()
                else: outr.append(r)
            rules=outr
        if opts.get('trimpart'):
            for r in rules: r['body']=re.sub(r"(?:\n|^)[IVXL]{1,5}\.[ \n][A-Z][^\n]{3,120}$","",r['body']).strip()
        q=qa(rules)
        rs_id=f"US-{st}:{abbr}";rs={"name":name,"abbr":abbr,"family":fam}
        xw+=crosswalk(st,rs_id,scope,courts)
        counts={}
        for r in rules: counts[r["num"]]=counts.get(r["num"],0)+1
        seen={}
        for r in rules:
            slug=re.sub(r"[^a-z0-9]+","-",(r.get("caps_heading") or "").lower()).strip("-")[:30]
            dup=counts[r["num"]]>1
            k=(r["num"],slug if dup else "");seen[k]=seen.get(k,0)+1
            suffix=(("-"+slug) if dup and slug else "")+(f"-v{seen[k]}" if seen[k]>1 else "")
            r["identifier"]=f"{st}-{fam}-{abbr}-{r['num']}{suffix}";r["rule_id"]=f"{rs_id}:{r['num']}{suffix}"
            r["warnings"]=[]
            if dup and not slug: r["warnings"].append("duplicate_rule_number_unresolved")
            if len(r["body"])<30: r["warnings"].append("short_text")
            head=f"{abbr} Rule {r['num']}"+(f". {r['title']}" if r["title"] else "")
            r["upstream_text"]=(head+"\n"+r["body"]).strip()
            ed=eff_date(r["body"][-400:]) or eff_date(r["body"])
            P=r.get("_p") or {}
            ts=P.get("fetched") or meta["fetched"];ru=P.get("url") or url;rp=P.get("pol") or pol;rsha=P.get("sha") or sha;rpdf=P.get("pdf_path") or pdf_rel;rpsha=P.get("pdf_sha256") or (sha if pdf_rel else None);rkey=P.get("key") or key
            rows.append({"rule_id":r["rule_id"],"rule_set_id":rs_id,"court_id":None,"jurisdiction":f"US-{st}","rule_set":name,"rule_set_abbrev":abbr,"rule_family":fam,"rule_level":level,
              "rule_number":r["num"],"rule_label":f"{abbr} {r['num']}","title":r["title"],"part_heading":(r["part"][1] if r["part"] else r.get("caps_heading")),"text":r["body"],"effective_date":ed,
              "pdf_path":rpdf,"pdf_sha256":rpsha,"source_sha256":rsha,"source_file":f"rules/raw/{rkey}","source_url":ru,"site_policy":rp,"retrieved_at":ts,
              "external_ref":None,"needs_review":bool(r["warnings"]),"parser_warnings":r["warnings"]})
            ups.append(upstream_record(st,sname,rs,r,r["part"],rp,ru,f"world_courts/rules/raw/{rkey}",ed))
        stats.append({"file":fname,"abbr":abbr,"rules":len(rules),**q})
        print(fname,q)
    # dedupe vs existing upstream
    ex=json.load(open(ROOT+"/data/ref/upstream_existing_keys.json")) if os.path.exists(ROOT+"/data/ref/upstream_existing_keys.json") else {}
    exid=set(ex.get("identifier",[]));exsrc=set(ex.get("source_id",[]));excid=set(ex.get("ipfs_cid",[]));exu=set(map(tuple,ex.get("state_sec_url",[])))
    keep=[];dropped=0
    for rw,u in zip(rows,ups):
        cid=dagjson_cid({k:v for k,v in u.items() if k!="ipfs_cid"})
        k2=(st,u["sectionNumber"],u["sourceUrl"])
        if u["identifier"] in exid or u["@id"] in exsrc or cid in excid or k2 in exu: dropped+=1;continue
        u["_cid"]=cid;rw["external_ref"]=json.dumps({"dataset":"justicedao/ipfs_court_rules","ipfs_cid":cid,"identifier":u["identifier"]});keep.append((rw,u))
    print("rows",len(rows),"kept",len(keep),"dropped_dups",dropped)
    json.dump(stats,open(f"{OUT}/us_rules_{st}_stats.json","w"),indent=1)
    with open(f"{OUT}/us_rules_{st}.jsonl","w") as f:
        for rw,u in keep: f.write(json.dumps(rw,ensure_ascii=False)+"\n")
    with open(f"{OUT}/us_rules_crosswalk_{st}.jsonl","w") as f:
        for x in xw: f.write(json.dumps(x)+"\n")
    # upstream files
    with open(f"{UP}/state_court_rules_jsonld/STATE-{st}.jsonld","w") as f:
        for rw,u in keep:
            o=dict(u);o.pop("_cid");f.write(json.dumps(o,ensure_ascii=False)+"\n")
    recs=[]
    for rw,u in keep:
        o={k:v for k,v in u.items() if k!="_cid"};cid=u["_cid"]
        recs.append({"ipfs_cid":cid,"state_code":st,"source_id":o["@id"],"identifier":o["identifier"],"name":o["name"],"legislation_type":"court_rule","legislation_jurisdiction":"",
            "source_url":o["sourceUrl"],"text":o["text"] or "","jsonld":json.dumps(o,sort_keys=True,separators=(",",":"),ensure_ascii=False)})
    pd.DataFrame(recs).to_parquet(f"{UP}/state_court_rules_parquet_cid/STATE-{st}.parquet",index=False)
    print("wrote upstream",len(recs),"xw",len(xw))
if __name__=="__main__": main(sys.argv[1])
