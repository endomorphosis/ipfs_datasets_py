"""Post-clean regex-extracted judge rows: trim trailing non-name tokens, drop emeritus/history/non-person hits."""
import json,re,sys,collections
TRAIL={"Position","Name","Justice","Open","Back","Judge","Chief","Read","More","Biography","Bio","View","Profile","Email","Phone","Term","Seat","District","Elected","Appointed","Retired","Associate","Senior","Presiding","Vice","Click","Learn","Contact","Office","Chambers","The","And","Of","Supreme","Court","Appeals","Home"}
BAD=re.compile(r"history|former|past-|memorial|archive|oral_arguments|news",re.I)
NONPERSON={"Initiatives","Directives","Self","Access","Service","Affidavits","Orders","Rules","Opinions","Assistant","Administrative","Program","Education","Selection","Nominating","Evaluation","Performance"}
def clean(n):
    t=n.split()
    while t and t[-1].strip(".,") in TRAIL: t.pop()
    return " ".join(t)
rows=[json.loads(l) for l in open(sys.argv[1])];out=[];seen=set()
for r in rows:
    if BAD.search(r["source_url"]) or "Emeritus" in r["name"]: continue
    n=clean(r["name"]);parts=n.split()
    if len(parts)<2 or set(parts)&NONPERSON or not all(re.match(r"^([A-Z][a-z'\-]+|[A-Z]\.|[A-Z]\.[A-Z]\.|Mc[A-Z]\w+|Jr\.?|Sr\.?|I+V?|de|van|von|[A-Z][a-z]+-[A-Z][a-z]+),?$",p) for p in parts): continue
    k=(r["subdivision"],parts[-1].lower(),parts[0].lower())
    if k in seen: continue
    seen.add(k);r["name"]=n;out.append(r)
with open(sys.argv[2],"w") as f:
    for r in out: f.write(json.dumps(r)+"\n")
c=collections.Counter(r["subdivision"] for r in out);print(len(rows),len(out),len(c),dict(c))
