"""Shared schema for courts, judges, forms, rules tables (pyarrow)."""
import re, unicodedata
import pyarrow as pa

LEVELS = {"supreme","appellate","trial_general","trial_limited","specialized","administrative","municipal","customary"}
COURT_TYPES = {"civil","criminal","family","labour","admin","tax","constitutional","mixed"}
JUDGE_ROLES = {"chief","presiding","associate","magistrate","registrar"}
JUDGE_STATUS = {"sitting","retired","unknown"}
FORM_CATEGORIES = {"civil","family","probate","small_claims","criminal","appeal","general"}
RULE_STATUS = {"in_force","repealed"}
LEVEL_CODE = {"supreme":"supreme","appellate":"appellate","trial_general":"trial","trial_limited":"trial-limited",
              "specialized":"specialized","administrative":"admin","municipal":"municipal","customary":"customary"}

S, L, F = pa.string(), pa.list_(pa.string()), pa.float64()
TS = pa.timestamp("s", tz="UTC")
M = pa.map_(pa.string(), pa.string())
PROV = [("source_url",S),("source_retrieved_at",TS)]

COURTS = pa.schema([("court_id",S),("parent_court_id",S),("country",S),("jurisdiction_path",L),("jurisdiction_name",S),
 ("level",S),("court_type",S),("name",S),("name_local",S),("language",S),("courthouse_id",S),("address_street",S),
 ("locality",S),("region",S),("postcode",S),("lat",F),("lon",F),("geo_source",S),("phones",L),("fax",S),
 ("email_institutional",S),("urls",L),("hours",S),("ecli_code",S),("external_ids",M),*PROV,("source_sha256",S),("license",S)])
JUDGES = pa.schema([("judge_id",S),("court_id",S),("full_name",S),("title",S),("role",S),("chamber_or_division",S),
 ("appointed_date",pa.date32()),("term_end_date",pa.date32()),("appointing_authority",S),("status",S),
 ("official_bio_url",S),("external_ids",M),*PROV])
FORMS = pa.schema([("form_id",S),("court_id",S),("jurisdiction_path",L),("form_number",S),("title",S),("title_local",S),
 ("language",S),("category",S),("file_format",S),("url",S),("file_sha256",S),("text",S),("version_date",pa.date32()),
 *PROV,("license",S)])
RULES = pa.schema([("rule_id",S),("rule_set_id",S),("rule_set_name",S),("jurisdiction_path",L),("court_id",S),
 ("court_level",S),("rule_number",S),("heading",S),("text",S),("parent_rule_id",S),("effective_date",pa.date32()),
 ("amended_date",pa.date32()),("status",S),("language",S),*PROV,
 ("law_pack_ref",S),("source_sha256",S),("license",S)])
SCHEMAS = {"courts":COURTS,"judges":JUDGES,"forms":FORMS,"rules":RULES}
ENUMS = {"courts":{"level":LEVELS,"court_type":COURT_TYPES},"judges":{"role":JUDGE_ROLES,"status":JUDGE_STATUS},
         "forms":{"category":FORM_CATEGORIES},"rules":{"status":RULE_STATUS,"court_level":LEVELS}}
REQUIRED = {"courts":["court_id","country","level","name","source_url","source_retrieved_at"],
            "judges":["judge_id","full_name","source_url"],"forms":["form_id","title","source_url"],
            "rules":["rule_id","rule_set_id","source_url"]}

def slugify(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii","ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+","-",s).strip("-") or "x"

COURT_ID_RE = re.compile(r"^[a-z]{2}-[a-z0-9]+(?:-[a-z0-9]+)*$")
def court_id(iso2, subdiv, level, name):
    """<iso2>-<subdiv>-<level>-<slug>; subdiv 'national' if none."""
    iso2 = iso2.lower()
    if not re.fullmatch(r"[a-z]{2}", iso2): raise ValueError("bad iso2")
    if level not in LEVEL_CODE: raise ValueError("bad level")
    sub = slugify(subdiv) if subdiv else "national"
    if sub.startswith(iso2+"-"): sub = sub[3:]
    return f"{iso2}-{sub}-{LEVEL_CODE[level]}-{slugify(name)}"

def make_id(prefix, *parts): return prefix + "-" + "-".join(slugify(p) for p in parts if p)

def validate_rows(table, rows):
    errs=[]; schema=SCHEMAS[table]; names=set(schema.names)
    for i,r in enumerate(rows):
        extra=set(r)-names
        if extra: errs.append((i,f"unknown cols {sorted(extra)}"))
        for c in REQUIRED[table]:
            if r.get(c) in (None,""): errs.append((i,f"missing {c}"))
        for c,allowed in ENUMS[table].items():
            v=r.get(c)
            if v is not None and v not in allowed: errs.append((i,f"bad {c}={v}"))
        cid=r.get("court_id")
        if cid and not COURT_ID_RE.match(cid): errs.append((i,"bad court_id"))
    return errs

def to_table(table, rows):
    return pa.Table.from_pylist(rows, schema=SCHEMAS[table])
