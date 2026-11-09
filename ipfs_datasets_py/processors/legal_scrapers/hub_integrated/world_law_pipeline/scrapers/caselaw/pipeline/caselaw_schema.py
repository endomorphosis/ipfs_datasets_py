"""caselaw-raw/v0 -- pinned pyarrow schemas, id rule, caster, writer and validator.

Conventions follow world-laws-raw/v1 ($IPFS_DATASETS_LEGAL_WORKSPACE/legal_scrapers/SCHEMA.md) and world-courts-raw/v1
($IPFS_DATASETS_LEGAL_WORKSPACE/courts/normalized/SCHEMA_COURTS.md). See $IPFS_DATASETS_LEGAL_WORKSPACE/case_law/schema_caselaw_v0.md.
Version stays v0 (unfrozen); this is doc revision r8 (schema_caselaw_v6.md). All text columns are pa.string() (never large_string).
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import hashlib, json, re, unicodedata, calendar
import pyarrow as pa
import pyarrow.parquet as pq

SCHEMA_VERSION = "caselaw-raw/v0"
SCHEMA_DOC_VERSION = "caselaw-raw/v0-r8"  # doc file: schema_caselaw_v6.md; `schema` stays caselaw-raw/v0 (unfrozen)
COURTS_DATASET_REVISION = "ef54093beb695b17e8a2676d287717b19aedc274"  # ipfs_court_data @ ef54093beb
RECORD_TYPES = ("decision", "opinion", "docket", "citation_edge")
JURISDICTION_LEVELS = ("national", "state", "regional", "municipal", "local")
DEFAULT_ADMIN_LEVEL = {"national": 2, "state": 4, "regional": 6, "municipal": 8, "local": 10}
FETCH_MODES = ("live", "wayback", "commoncrawl", "bulk", "api", "hf_dataset")
URL_REQUIRED_MODES = ("live", "wayback", "commoncrawl")
MATCH_STATUSES = ("matched", "ambiguous", "unmatched")
REDACTION_STATUSES = ("source_pseudonymised", "source_anonymised", "as_published", "unknown")
OPINION_TYPES = ("lead", "majority", "concurrence", "dissent", "per_curiam", "plurality", "judgment", "other")
LICENCE_CLASSES = ("open", "NC", "gated", "unknown")
TEXT_FORMATS = ("plain", "html", "xhtml", "xml", "akn_xml", "pdf")
DECISION_TYPES = ("judgment", "order", "decree", "ruling", "advocate_general_opinion", "other")
TREATMENTS = ("cites", "follows", "applies", "distinguishes", "criticizes", "overrules", "other")
SENSITIVITY_FLAGS = ("criminal", "family", "juvenile", "immigration", "mental_health", "tax", "personal_contact")  # (sealed records are never ingested; there is no `sealed` flag)
BODY_TYPES = ("court", "executive_body", "administrative_authority", "commission_or_regulator", "collection")  # r6: issuing body; NULL = not assessed / mixed
PLACEHOLDER_LABELS = frozenset(("undefined", "null", "none", "n/a", "na", "nan", "unknown", "-", "--", "?", "tbd", "nil"))
EMAIL_TOKEN = "[email redacted]"
DATE_PLACEHOLDER_EVIDENCE = ("source_id_year_only", "source_id_nodate", "source_id_no_date_and_no_1_january_in_text", "source_id_dec31_not_in_text", "source_id_zero_date")   # r7: + dec31; r8: + zero date (id ends _0000-00-00)
TOMBSTONE_REASONS = ("takedown_request", "sealed", "redaction_failure", "source_withdrawn", "licence_change", "other")
TOMBSTONE_ACTIONS = ("drop", "purge_text")
ID_RULE = "repo_unique_v1"
# ISO-639-1 (184 two-letter codes): the language column must be a member. Languages without a 2-letter code => language NULL, ISO-639-3 code in metadata_json.extras.language_639_3.
ISO639_1 = frozenset("""aa ab ae af ak am an ar as av ay az ba be bg bh bi bm bn bo br bs ca ce ch co cr cs cu cv cy da de dv dz ee el en eo es et eu fa ff fi fj fo fr fy ga gd gl gn gu gv ha he hi ho hr ht hu hy hz ia id ie ig ii ik io is it iu ja jv ka kg ki kj kk kl km kn ko kr ks ku kv kw ky la lb lg li ln lo lt lu lv mg mh mi mk ml mn mr ms mt my na nb nd ne ng nl nn no nr nv ny oc oj om or os pa pi pl ps pt qu rm rn ro ru rw sa sc sd se sg si sk sl sm sn so sq sr ss st su sv sw ta te tg th ti tk tl tn to tr ts tt tw ty ug uk ur uz ve vi vo wa wo xh yi yo za zh zu""".split())
# privacy: keys that may carry litigant names. Dropped from extras/metadata by cast_rows, rejected by the validator.
# r4: case-insensitive SUBSTRING match on the key with separators/camelCase collapsed (partyName, nameOfParties, CaseTitle, plaintiff_name -> match).
PARTY_KEY_TOKENS = ("casename", "casetitle", "nameofcase", "title", "titel", "titre", "caption", "party", "parties", "partij", "partei", "plaintiff", "defendant", "appellant", "appellee",
                    "respondent", "applicant", "petitioner", "claimant", "complainant", "litigant", "accused", "versus", "opponent", "victim", "heading",
                    "eiser", "verweerder", "gedaagde", "klager", "beklagter", "demandeur", "defendeur", "requerant", "ricorrente", "demandante", "recorrente", "rubrum", "zaaknaam",
                    "debtor", "creditor", "witness", "surname", "otherside",
                    # r6: recourant (fr), beschwerdefuhrer (de), recorrido (es/pt) + safe siblings; substring-safe
                    "recourant", "beschwerdefuhrer", "recorrido", "beklagte", "angeklagte", "beschuldigte", "agravante", "impetrante", "paciente", "requerente",
                    # r7: Beschwerdegegner (de), apelante/resistente (pt/es), querelant(e) (nl/pt/it), imputato (it), convenuto (it)
                    "beschwerdegegner", "apelante", "resistente", "querelant", "imputato", "imputati", "convenut")
# r6: short role words that collide with ordinary words as substrings (department, autorite, preuve) match only as a WHOLE WORD of the key (camelCase / separators split it)
PARTY_KEY_WORDS = ("partie", "parte", "partes", "autor", "autores", "reu", "reus", "intime")
PARTY_KEY_EXACT = ("vs", "v", "case", "name", "fullname", "naam")   # r5: generic name keys match only as a whole key (courtName / fileName stay legal)


class _PartyKeyRe:
    """Duck-typed stand-in for a compiled regex: .search(key) is truthy when the key may hold litigant names.
    r5: NFKC (full-width/compat forms) then NFKD with combining marks removed (defendeur == d\u00e9fendeur), lowercase, separators/zero-width stripped, substring match."""
    @staticmethod
    def search(key):
        k0 = unicodedata.normalize("NFKD", unicodedata.normalize("NFKC", str(key)))
        k0 = "".join(ch for ch in k0 if not unicodedata.combining(ch))
        k = re.sub(r"[^a-z0-9]", "", k0.lower())
        if any(t in k for t in PARTY_KEY_TOKENS) or k in PARTY_KEY_EXACT: return True
        words = [w.lower() for w in re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+", k0)]   # r6: whole-word match for the short role words
        return any(w in PARTY_KEY_WORDS for w in words)


RE_PARTY_KEY = _PartyKeyRe()
PARTY_KEY_ALLOW = {"parties_redaction_status"}
_CASE_BASE = (r"(\s(?:versus|against|contre|contra|tegen|gegen|contro|gegen\u00fcber|przeciwko|proti|mot|mod|\u043f\u0440\u043e\u0442\u0438\u0432)\s"
    r"|(?<!\d)\s(?:v|vs|c)\.?\s+(?!\d)|(?<!\d)\s(?:v|vs|c)\.(?-i:(?=[A-Z\u00c0-\u00dd]))|\sc/\s|\s\./\.\s|\s-v-\s|\sex\s+parte\s|^\s*(?:in\s+re|re|matter\s+of|ex\s+parte)\s|,\s*in\s+re\s*$)")
# r6: Portuguese/Spanish/Italian "A x B", "A e B", "A y B": lower-case conjunction, a LETTER before it (never a digit), a CAPITAL letter after it (case-sensitive).
# Not applied to court_name_raw (Italian/Spanish court names legitimately contain " e " / " y ").
_CASE_CONJ = r"(?<=[^\W\d_])\s(?-i:[xey])\s+(?-i:(?=[A-Z\u00c0-\u00dd\u0141\u015a\u0179\u017b\u0106\u0143]))"
# (?<!\d) before the v/vs/c forms: Swiss BGE/ATF cites carry the Roman numeral V ("BGE 116 V 182", "BGE 116 V Erw. 3") and must not look like "A v B".
RE_CASE_NAME_VALUE = re.compile(_CASE_BASE[:-1] + "|" + _CASE_CONJ + ")", re.I)
RE_COURT_NAME_CASE = re.compile(_CASE_BASE, re.I)
# r5 forms: "A v. B", "A c. B", "A c/ B", "A ./. B", "A -v- B", contra, tegen, gegen, przeciwko, proti, mot, mod, "In re X", "Smith, In re"; NOT "Case C 123/20", "Re-opened", ECLI. r6: against, " x ", " e ", " y ".
# r7: Unicode-aware (accented / IDN local parts and domains), full-width and small commercial at (U+FF20, U+FE6B), and the spaced form "name @ domain" (exactly one space/NBSP on BOTH sides).
# Still NOT matched (documented non-addresses): "[placeholder] @s.whatsapp.net" (no local part), "@ [handle]", "C@b_ag.com" (underscore in domain), "aon@rnait" (no dotted TLD).
_AT = "[@\uff20\ufe6b]"
RE_EMAIL = re.compile(r"[\w.%+\-]+(?:" + _AT + r"|[ \u00a0]" + _AT + r"[ \u00a0])(?:[^\W_]|-)+(?:\.(?:[^\W_]|-)+)*\.[^\W\d_]{2,}")


def clean_label(v):
    """r6 normaliser for docket_number / court_name_raw: control chars and any whitespace run -> one space, strip, placeholder strings (undefined, null, n/a ...) -> None."""
    if v is None: return None
    s_ = re.sub(r"[\x00-\x1f\x7f\s]+", " ", str(v)).strip()
    return None if (not s_ or s_.lower() in PLACEHOLDER_LABELS) else s_


def redact_emails(text):
    """r6: -> (text with every e-mail address replaced by EMAIL_TOKEN, number replaced)."""
    return RE_EMAIL.subn(EMAIL_TOKEN, text) if text else (text, 0)


PRIVACY_DROPPED: dict[str, int] = {}

RE_ENTITY_KEY = re.compile(r"^wc1e:court:[0-9a-f]{24}$")
RE_PROVISIONAL = re.compile(r"^wcc1:[A-Z]{2}:([A-Z]{2}-[A-Z0-9]{1,3}|-):[0-9a-f]{16}$")
RE_ID = re.compile(r"^wc1:(decision|opinion|docket|citation_edge):[0-9a-f]{24}$")
class _DateRe:
    """Shape + real-calendar check (2026-02-31 and 2026-13-40 are rejected). full=True: YYYY[-MM[-DD]]; False: YYYY-MM-DD."""
    def __init__(self, pat, full): self.p = re.compile(pat); self.full = full
    def match(self, v):
        if not isinstance(v, str) or not self.p.match(v): return None
        parts = [int(x) for x in v.split("-")]
        if parts[0] < 1: return None
        if len(parts) >= 2 and not 1 <= parts[1] <= 12: return None
        if len(parts) == 3 and not 1 <= parts[2] <= calendar.monthrange(parts[0], parts[1])[1]: return None
        return True
RE_DATE = _DateRe(r"^\d{4}(-\d{2}(-\d{2})?)?$", True)
RE_RDATE = _DateRe(r"^\d{4}-\d{2}-\d{2}$", False)
RE_ISO2 = re.compile(r"^[A-Z]{2}$")
RE_ADMIN1 = re.compile(r"^[A-Z]{2}-[A-Z0-9]{1,3}$")
RE_LANG = re.compile(r"^[a-z]{2}$")  # and membership in ISO639_1
RE_JUDGE_KEY = re.compile(r"^wc1e:judge:[0-9a-f]{24}$")
RE_ECLI = re.compile(r"^ECLI:[A-Z]{2}:[A-Za-z0-9.]{1,7}:\d{4}:[A-Za-z0-9.\-]{1,25}$")
RE_SHA256 = re.compile(r"^[0-9a-f]{64}$")

S = pa.string()


def _f(name, typ=S, nullable=True):
    return pa.field(name, typ, nullable=nullable)


# common prefix (courts order, S1/S2), identical for all four record types
COMMON_FIELDS = [
    _f("id", nullable=False), _f("record_type", nullable=False), _f("schema_version", nullable=False),
    _f("country_iso", nullable=False), _f("jurisdiction_level", nullable=False),
    _f("admin_level", pa.int64()), _f("admin1"), _f("municipality"), _f("municipality_code"),
    _f("jurisdiction_raw", nullable=False),
    _f("source_name", nullable=False),      # stable source key, e.g. nl_rechtspraak (was plan `source_id`); hashed into id
    _f("source_type", nullable=False),      # collector tag, e.g. nl_rechtspraak_api; `*_archive` for replay
    _f("source_record_id", nullable=False), # native id (ECLI, CELEX, cluster id, uri)
    _f("source_url"),                       # ORIGINAL page/API URL (courts convention)
    _f("found_on"),                         # archive replay URL / discovery page (courts convention)
    _f("fetch_mode", nullable=False), _f("retrieval_date"), _f("licence"),
    _f("phase", nullable=False), _f("source_file", nullable=False),
]
COURT_FIELDS = [
    _f("court_entity_key"),                 # ONLY ^wc1e:court:[0-9a-f]{24}$ or null
    _f("court_key_provisional"),            # wcc1:<ISO>:<admin1|->:<16hex> when status != matched
    _f("court_match_status", nullable=False),
    _f("court_name_raw"),
    _f("body_type"),                        # r6: court / executive_body / administrative_authority / commission_or_regulator / collection; NULL = not assessed
]
COMPLIANCE_COMMON = [_f("parties_redaction_status", nullable=False)]

DECISION_FIELDS = COURT_FIELDS + [
    _f("docket_number"), _f("decision_date"), _f("filing_date"), _f("decision_year", pa.int64()),
    _f("ecli"), _f("neutral_citation"), _f("other_citations"),  # json list[str]
    _f("canonical_key"),                     # normalised ECLI / neutral citation for cross-source dedupe (S6)
    _f("decision_type"), _f("language"),
    _f("judges_raw"),                        # json list of {"name","role"} (exactly these two keys)
    _f("judge_entity_keys"),                 # optional json list aligned by index with judges_raw: wc1e:judge:<hash> or null
    _f("opinion_count", pa.int64()),
    _f("text_sha256"),                       # = text_sha256 of the lead opinion (cross-checked by validate_cross)
    _f("restricted_ai_training", pa.bool_(), nullable=False),
    _f("ocr", pa.bool_()),
    _f("sensitivity_flags"),                 # json list over SENSITIVITY_FLAGS: criminal/family/juvenile/immigration/mental_health/tax/personal_contact
    _f("licence_class", nullable=False),     # open / NC / gated / unknown
] + COMPLIANCE_COMMON

OPINION_FIELDS = [
    _f("decision_id", nullable=False),       # FK decision.id
    _f("opinion_type"), _f("author_raw"),
    _f("text"), _f("text_format"),           # text is ALWAYS plain text; text_format = SOURCE format
    _f("page_count", pa.int64()), _f("language"),
    _f("ocr", pa.bool_(), nullable=False), _f("text_backend"),
    _f("text_sha256"),                       # sha256 of UTF-8 `text` exactly as stored
    _f("restricted_ai_training", pa.bool_(), nullable=False),
    _f("licence_class", nullable=False),
] + COMPLIANCE_COMMON

DOCKET_FIELDS = COURT_FIELDS + [
    _f("docket_number", nullable=False), _f("filing_date"), _f("termination_date"),
    _f("restricted_ai_training", pa.bool_(), nullable=False),
    _f("licence_class", nullable=False),
] + COMPLIANCE_COMMON

EDGE_FIELDS = [
    _f("citing_id", nullable=False), _f("cited_id", nullable=False),   # FK ids (deterministic, may be un-ingested)
    _f("depth", pa.int64()), _f("treatment"),
]
META = [_f("metadata_json", nullable=False)]

def _schema(kind, extra):
    return pa.schema(COMMON_FIELDS + extra + META, metadata={
        b"schema": SCHEMA_VERSION.encode(), b"record_type": kind.encode(),
        b"schema_doc_version": SCHEMA_DOC_VERSION.encode(), b"layer": b"raw_caselaw",
        b"courts_dataset_revision": COURTS_DATASET_REVISION.encode()})

SCHEMAS = {"decision": _schema("decision", DECISION_FIELDS), "opinion": _schema("opinion", OPINION_FIELDS),
           "docket": _schema("docket", DOCKET_FIELDS), "citation_edge": _schema("citation_edge", EDGE_FIELDS)}


def make_id(record_type: str, source_name: str, source_record_id: str) -> str:
    if record_type not in RECORD_TYPES or not source_name or not source_record_id:
        raise ValueError("make_id: need record_type, source_name, source_record_id (never invent ids)")
    return f"wc1:{record_type}:{hashlib.sha256(f'{source_name}|{source_record_id}'.encode()).hexdigest()[:24]}"


def dedupe_id(old_id: str, phase: str) -> str:
    """fix1 rule (ID_RULE repo_unique_v1): later duplicate -> wc1:<type>:sha256(old_id|phase)[:24]."""
    typ = old_id.split(":")[1]
    return f"wc1:{typ}:{hashlib.sha256(f'{old_id}|{phase}'.encode()).hexdigest()[:24]}"


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def provisional_key(country_iso: str, admin1: str | None, norm_name: str, source_name: str | None = None, discriminator: str | None = None) -> str:
    """wcc1:<ISO>:<admin1|->:<16hex>. Named courts: hash(norm_name) -> shared across sources for the same (iso, admin1, name).
    Unnamed courts: hash("unnamed|source_name|discriminator") so they cannot collapse into one key per (iso, admin1);
    without source_name/discriminator they fall back to a NON-UNIQUE 'unknown' key (documented)."""
    basis = norm_name if norm_name else f"unnamed|{source_name or ''}|{discriminator or 'unknown'}"
    return f"wcc1:{country_iso}:{admin1 or '-'}:{hashlib.sha256(basis.encode()).hexdigest()[:16]}"


def _scrub_party_keys(obj, path=""):
    """Recursively drop dict keys that may hold litigant names; returns (clean, dropped_key_paths)."""
    dropped = []
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k not in PARTY_KEY_ALLOW and RE_PARTY_KEY.search(str(k)):
                dropped.append(f"{path}{k}"); continue
            c, d = _scrub_party_keys(v, f"{path}{k}.")
            out[k] = c; dropped += d
        return out, dropped
    if isinstance(obj, list):
        out = []
        for i, v in enumerate(obj):
            c, d = _scrub_party_keys(v, path); out.append(c); dropped += d
        return out, dropped
    return obj, dropped


def _party_key_paths(obj, path=""):
    bad = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k not in PARTY_KEY_ALLOW and RE_PARTY_KEY.search(str(k)): bad.append(f"{path}{k}")
            bad += _party_key_paths(v, f"{path}{k}.")
    elif isinstance(obj, list):
        for v in obj: bad += _party_key_paths(v, path)
    return bad


def cast_rows(rows: list[dict], kind: str) -> pa.Table:
    """dict rows -> pinned table. Missing nullable -> null. Missing NOT NULL -> SchemaError (fail closed).
    Unknown keys are folded into metadata_json['extras'] (no widening). metadata_json may be dict or str."""
    sch = SCHEMAS[kind]
    names = sch.names
    cols = {n: [] for n in names}
    for r in rows:
        r = dict(r)
        r.setdefault("record_type", kind); r.setdefault("schema_version", SCHEMA_VERSION)
        lvl = r.get("jurisdiction_level")
        if r.get("admin_level") is None and lvl in DEFAULT_ADMIN_LEVEL:
            r["admin_level"] = DEFAULT_ADMIN_LEVEL[lvl]
        if r.get("decision_year") is None and kind == "decision" and r.get("decision_date"):
            try: r["decision_year"] = int(str(r["decision_date"])[:4])
            except ValueError: pass
        meta = r.get("metadata_json") or {}
        if isinstance(meta, str):
            try: meta = json.loads(meta)
            except Exception: meta = {"_orig_metadata_raw": meta}
        extra = {k: v for k, v in r.items() if k not in names and v is not None}
        if extra:
            ex = meta.setdefault("extras", {})
            for k, v in extra.items(): ex.setdefault(k, v)
        meta, dropped = _scrub_party_keys(meta)          # r3: no litigant-name keys, at any depth
        if dropped:
            meta["privacy_dropped_keys"] = sorted(set(meta.get("privacy_dropped_keys", []) + dropped))
            for k in dropped: PRIVACY_DROPPED[k] = PRIVACY_DROPPED.get(k, 0) + 1
        # r3 fail-safe defaults
        if "parties_redaction_status" in names and r.get("parties_redaction_status") is None:
            r["parties_redaction_status"] = "unknown"
        if "restricted_ai_training" in names and r.get("restricted_ai_training") is None:
            r["restricted_ai_training"] = True            # unknown => restricted; False needs metadata_json.terms evidence
        if "licence_class" in names and r.get("licence_class") is None:
            r["licence_class"] = "unknown"
        r["metadata_json"] = json.dumps(meta, sort_keys=True, ensure_ascii=False)
        for f in sch:
            v = r.get(f.name)
            if isinstance(v, (list, dict)) and f.type == S: v = json.dumps(v, ensure_ascii=False, sort_keys=True)
            if v == "" and f.type == S: v = None
            if v is None and not f.nullable:
                raise ValueError(f"SchemaError: NOT NULL column {f.name} missing in {kind} row {r.get('source_record_id')}")
            cols[f.name].append(v)
    return pa.table({n: pa.array(cols[n], type=sch.field(n).type) for n in names}, schema=sch)


def _pending_outside_terms(obj, top=True):
    """r6: True if the key pending_legal_review occurs anywhere except as a direct child of the top-level metadata_json.terms object."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "pending_legal_review": return True
            if k == "terms" and top and isinstance(v, dict):
                if any(_pending_outside_terms(x, False) for kk, x in v.items() if kk != "pending_legal_review"): return True
                continue
            if _pending_outside_terms(v, False): return True
    elif isinstance(obj, list):
        return any(_pending_outside_terms(v, False) for v in obj)
    return False


def _bad(vals, pred):
    return sum(1 for v in vals if v is not None and not pred(v))


def validate_caselaw_table(t: pa.Table, kind: str) -> list[str]:
    """Return a list of problems (empty == valid)."""
    P: list[str] = []
    sch = SCHEMAS[kind]
    if t.schema.names != sch.names:
        return [f"column set/order differs: extra={[n for n in t.schema.names if n not in sch.names]} "
                f"missing={[n for n in sch.names if n not in t.schema.names]}"]
    for f in t.schema:
        p = sch.field(f.name)
        if f.type != p.type: P.append(f"dtype {f.name}: {f.type} != pinned {p.type}")
        if not p.nullable and t.column(f.name).null_count: P.append(f"NOT NULL {f.name} has {t.column(f.name).null_count} nulls")
    md = t.schema.metadata or {}
    if md.get(b"schema") != SCHEMA_VERSION.encode(): P.append("kv metadata schema != caselaw-raw/v0")
    if md.get(b"record_type") != kind.encode(): P.append("kv metadata record_type mismatch")
    if md.get(b"courts_dataset_revision") != COURTS_DATASET_REVISION.encode(): P.append("kv metadata courts_dataset_revision missing/!= pinned revision")
    if md.get(b"schema_doc_version") != SCHEMA_DOC_VERSION.encode(): P.append(f"kv metadata schema_doc_version != {SCHEMA_DOC_VERSION}")
    if md.get(b"layer") != b"raw_caselaw": P.append("kv metadata layer != raw_caselaw")
    c = {n: t.column(n).to_pylist() for n in t.schema.names}
    n = t.num_rows
    if len(set(c["id"])) != n: P.append(f"id not unique in table ({n - len(set(c['id']))} duplicates)")
    if _bad(c["id"], lambda v: RE_ID.match(v) and v.split(":")[1] == kind): P.append(f"id format != wc1:{kind}:<24hex>")
    if any(v != kind for v in c["record_type"]): P.append("record_type != kind")
    if any(v != SCHEMA_VERSION for v in c["schema_version"]): P.append("schema_version != caselaw-raw/v0")
    if _bad(c["country_iso"], RE_ISO2.match): P.append("country_iso not upper-case alpha-2")
    if _bad(c["jurisdiction_level"], lambda v: v in JURISDICTION_LEVELS): P.append(f"jurisdiction_level not in {JURISDICTION_LEVELS}")
    if _bad(c["fetch_mode"], lambda v: v in FETCH_MODES): P.append(f"fetch_mode not in {FETCH_MODES}")
    bad_admin = sum(1 for a, iso in zip(c["admin1"], c["country_iso"]) if a is not None and not (RE_ADMIN1.match(a) and a[:2] == iso))
    if bad_admin: P.append(f"admin1 not ISO 3166-2 / prefix != country_iso in {bad_admin} rows")
    if _bad(c["retrieval_date"], RE_RDATE.match): P.append("retrieval_date not YYYY-MM-DD")
    nodate = sum(1 for m, d in zip(c["fetch_mode"], c["retrieval_date"]) if m in URL_REQUIRED_MODES and not d)
    if nodate: P.append(f"{nodate} live/wayback/commoncrawl rows lack retrieval_date")
    miss = sum(1 for m, u, f in zip(c["fetch_mode"], c["source_url"], c["found_on"]) if m in URL_REQUIRED_MODES and not (u or f))
    if miss: P.append(f"{miss} live/wayback/commoncrawl rows lack source_url and found_on")
    if _bad(c["metadata_json"], lambda v: isinstance(json.loads(v), dict)): P.append("metadata_json not a JSON object")
    metas = [json.loads(v) for v in c["metadata_json"]]
    leaks = sorted({p for m in metas for p in _party_key_paths(m)})
    if leaks: P.append(f"litigant-name keys in metadata_json: {leaks[:8]}")
    for col in ("other_citations", "canonical_key", "court_name_raw", "docket_number", "neutral_citation"):
        if col in c:
            rx = RE_COURT_NAME_CASE if col == "court_name_raw" else RE_CASE_NAME_VALUE
            nbad = 0
            for v in c[col]:
                if v is None: continue
                vals = json.loads(v) if col == "other_citations" else [v]
                nbad += sum(1 for x in vals if isinstance(x, str) and rx.search(x))
            if nbad: P.append(f"{col}: {nbad} values look like they carry a case name (A v. B); use a citation-only form")
    if "licence_class" in c and _bad(c["licence_class"], lambda v: v in LICENCE_CLASSES): P.append(f"licence_class not in {LICENCE_CLASSES}")
    if "restricted_ai_training" in c:
        bad_terms = bad_flag = bad_nc = bad_pend = bad_unk = bad_loc = bad_ptype = 0
        lcs = c["licence_class"] if "licence_class" in c else [None] * len(metas)
        for rt, m, lc in zip(c["restricted_ai_training"], metas, lcs):
            if lc in ("NC", "gated") and rt is not True: bad_nc += 1
            if lc == "unknown" and rt is not True: bad_unk += 1
            if _pending_outside_terms(m): bad_loc += 1
            if isinstance(m.get("terms"), dict) and "pending_legal_review" in m["terms"] and not isinstance(m["terms"]["pending_legal_review"], bool): bad_ptype += 1
            if rt is not True and isinstance(m.get("terms"), dict) and m["terms"].get("pending_legal_review") is True: bad_pend += 1
            if rt is False:
                tm = m.get("terms")
                urls = tm.get("evidence_url") if isinstance(tm, dict) else None
                urls = [urls] if isinstance(urls, str) else urls
                if not (isinstance(tm, dict) and isinstance(tm.get("basis"), str) and tm["basis"].strip()
                        and isinstance(urls, list) and urls and all(isinstance(u, str) and re.match(r"^https?://", u) for u in urls)
                        and isinstance(tm.get("checked"), str) and RE_RDATE.match(tm["checked"])):
                    bad_terms += 1
                elif not isinstance(tm.get("pending_legal_review"), bool): bad_flag += 1
        if bad_terms: P.append(f"{bad_terms} rows: restricted_ai_training=false needs metadata_json.terms {{basis, evidence_url(http urls), checked}}")
        if bad_flag: P.append(f"{bad_flag} rows: restricted_ai_training=false needs boolean metadata_json.terms.pending_legal_review")
        if bad_pend: P.append(f"{bad_pend} rows: terms.pending_legal_review=true requires restricted_ai_training=true until review is done")
        if bad_nc: P.append(f"{bad_nc} rows: licence_class NC/gated requires restricted_ai_training=true")
        if bad_unk: P.append(f"{bad_unk} rows: licence_class unknown requires restricted_ai_training=true")
        if bad_loc: P.append(f"{bad_loc} rows: pending_legal_review must sit only under metadata_json.terms (found elsewhere in metadata)")
        if bad_ptype: P.append(f"{bad_ptype} rows: metadata_json.terms.pending_legal_review must be a boolean")
    if "court_match_status" in c:
        for i, (st, k, pk) in enumerate(zip(c["court_match_status"], c["court_entity_key"], c["court_key_provisional"])):
            if st not in MATCH_STATUSES: P.append(f"row {i}: court_match_status {st!r}"); break
            if k is not None and not RE_ENTITY_KEY.match(k): P.append(f"row {i}: court_entity_key not wc1e:court:<24hex>"); break
            if st == "matched" and (k is None or pk is not None): P.append(f"row {i}: matched needs key and no provisional"); break
            if st == "matched":
                cand = metas[i].get("court_entity_key_candidates")
                if not (isinstance(cand, list) and cand and k in cand and min(cand) == k and metas[i].get("courts_dataset_revision") == COURTS_DATASET_REVISION):
                    P.append(f"row {i}: matched row needs metadata_json.court_entity_key_candidates (contains key, min == key) and courts_dataset_revision"); break
            if st != "matched" and (k is not None or pk is None or not RE_PROVISIONAL.match(pk)):
                P.append(f"row {i}: {st} needs null key and a valid wcc1 provisional key"); break
    for col in ("docket_number", "court_name_raw"):
        if col in c:
            nbad = sum(1 for v in c[col] if v is not None and clean_label(v) != v)
            if nbad: P.append(f"{col}: {nbad} values not normalised (leading/trailing/multiple whitespace, control chars) or a placeholder (undefined/null/n/a ...); use clean_label")
    if "body_type" in c and _bad(c["body_type"], lambda v: v in BODY_TYPES): P.append(f"body_type not in {BODY_TYPES}")
    if "parties_redaction_status" in c and _bad(c["parties_redaction_status"], lambda v: v in REDACTION_STATUSES):
        P.append(f"parties_redaction_status not in {REDACTION_STATUSES}")
    for col in ("decision_date", "filing_date", "termination_date"):
        if col in c and _bad(c[col], RE_DATE.match): P.append(f"{col} not YYYY[-MM[-DD]]")
    if "ecli" in c and _bad(c["ecli"], RE_ECLI.match): P.append("ecli format")
    if "language" in c and _bad(c["language"], lambda v: v in ISO639_1):
        P.append("language not a member of ISO-639-1")
    if "decision_type" in c and _bad(c["decision_type"], lambda v: v in DECISION_TYPES): P.append(f"decision_type not in {DECISION_TYPES}")
    if "sensitivity_flags" in c and _bad(c["sensitivity_flags"], lambda v: all(x in SENSITIVITY_FLAGS for x in json.loads(v))):
        P.append(f"sensitivity_flags values not in {SENSITIVITY_FLAGS} (no sealed flag: sealed records are never ingested)")
    if "treatment" in c and _bad(c["treatment"], lambda v: v in TREATMENTS): P.append(f"treatment not in {TREATMENTS}")
    if "text_sha256" in c and kind == "decision" and _bad(c["text_sha256"], RE_SHA256.match): P.append("text_sha256 format")
    for col in ("other_citations", "judges_raw", "judge_entity_keys", "sensitivity_flags"):
        if col in c and _bad(c[col], lambda v: isinstance(json.loads(v), list)): P.append(f"{col} not a JSON list")
    if "other_citations" in c and _bad(c["other_citations"], lambda v: all(isinstance(x, str) for x in json.loads(v))):
        P.append("other_citations must be list of strings")
    if "judge_entity_keys" in c and _bad(c["judge_entity_keys"], lambda v: all(x is None or RE_JUDGE_KEY.match(x) for x in json.loads(v))):
        P.append("judge_entity_keys format (wc1e:judge:<24hex> or null)")
    if "judges_raw" in c:
        def _ok_judges(v):
            L = json.loads(v)
            return all(isinstance(j, dict) and set(j) == {"name", "role"} and isinstance(j["name"], str) and (j["role"] is None or isinstance(j["role"], str)) for j in L)
        if _bad(c["judges_raw"], _ok_judges): P.append("judges_raw entries must be exactly {name, role}")
        for jr, jk in zip(c["judges_raw"], c["judge_entity_keys"]):
            if jk is not None and (jr is None or len(json.loads(jk)) != len(json.loads(jr))):
                P.append("judge_entity_keys must align by index with judges_raw"); break
    if kind == "opinion":
        if _bad(c["decision_id"], lambda v: v.startswith("wc1:decision:") and RE_ID.match(v)): P.append("decision_id not a decision id")
        if _bad(c["text_sha256"], RE_SHA256.match): P.append("text_sha256 format")
        for i, (tx, h, m) in enumerate(zip(c["text"], c["text_sha256"], metas)):
            if tx is None or not tx.strip():
                if not m.get("text_missing"): P.append(f"row {i}: empty text without metadata text_missing"); break
            elif h != text_sha256(tx): P.append(f"row {i}: text_sha256 != sha256(text)"); break
        nem = sum(1 for tx in c["text"] if tx and RE_EMAIL.search(tx))
        if nem: P.append(f"{nem} opinions contain an unredacted e-mail address (replace with {EMAIL_TOKEN!r})")
        bred = sum(1 for tx, m in zip(c["text"], metas) if (m.get("contact_redaction") or {}).get("emails_redacted", 0) and (not tx or EMAIL_TOKEN not in tx))
        if bred: P.append(f"{bred} opinions claim emails_redacted but contain no {EMAIL_TOKEN!r}")
        if _bad(c["opinion_type"], lambda v: v in OPINION_TYPES): P.append(f"opinion_type not in {OPINION_TYPES}")
        if _bad(c["text_format"], lambda v: v in TEXT_FORMATS): P.append(f"text_format not in {TEXT_FORMATS}")
    if kind == "decision":
        bp = 0
        for d, m in zip(c["decision_date"], metas):
            dp = m.get("date_precision")
            if dp is not None and (dp not in ("year", "month", "day") or d is None or len(d) != {"year": 4, "month": 7, "day": 10}[dp]): bp += 1
        if bp: P.append(f"{bp} rows: metadata_json.date_precision must be year/month/day and match the shape of decision_date")
        # r7: not_decision flag (guideline / explanatory documents ingested by a decision source): object with a reason, and never combined with a body_type
        bt_col = c["body_type"] if "body_type" in c else [None] * len(metas)
        nd_bad = sum(1 for m, b in zip(metas, bt_col) if "not_decision" in m and not (isinstance(m["not_decision"], dict) and isinstance(m["not_decision"].get("reason"), str) and m["not_decision"]["reason"] and b is None))
        if nd_bad: P.append(f"{nd_bad} rows: metadata_json.not_decision must be an object with a non-empty reason, and the row's body_type must be NULL")
        # r7: date_placeholder: known evidence; a recovered_from_text full date must be YYYY-MM-DD in the same year with no date_precision; a NULL decision_date needs the flag and no precision
        dp_bad = 0; null_bad = 0
        for d, y, m in zip(c["decision_date"], c["decision_year"], metas):
            ph = m.get("date_placeholder")
            if ph is None:
                if d is None: null_bad += 1   # r8: a NULL decision_date always needs the flag
                continue
            if not (isinstance(ph, dict) and ph.get("evidence") in DATE_PLACEHOLDER_EVIDENCE and isinstance(ph.get("original_decision_date"), str)): dp_bad += 1; continue
            if ph.get("recovered_from_text") and not (d and len(d) == 10 and "date_precision" not in m): dp_bad += 1
            if d is None and (y is not None or "date_precision" in m or not ph.get("date_unknown")): dp_bad += 1
        if dp_bad: P.append(f"{dp_bad} rows: metadata_json.date_placeholder malformed (evidence in {DATE_PLACEHOLDER_EVIDENCE}; recovered_from_text needs a full date and no date_precision; NULL date needs date_unknown and NULL year)")
        if null_bad: P.append(f"{null_bad} rows: decision_date is NULL without metadata_json.date_placeholder.date_unknown=true (a NULL date must be flagged)")
        # r8: publication_year (ARGVP volume year) is a documented separate field: an int 1800-2100, only on rows whose decision_date/decision_year are NULL
        pub_bad = sum(1 for d, m in zip(c["decision_date"], metas) if "publication_year" in m and not (type(m["publication_year"]) is int and 1800 <= m["publication_year"] <= 2100 and d is None))
        if pub_bad: P.append(f"{pub_bad} rows: metadata_json.publication_year must be an integer 1800-2100 and decision_date must be NULL")
        bad = sum(1 for d, y in zip(c["decision_date"], c["decision_year"]) if d and y is not None and int(d[:4]) != y)
        if bad: P.append("decision_year != decision_date year")
    if kind == "citation_edge":
        if _bad(c["citing_id"], RE_ID.match) or _bad(c["cited_id"], RE_ID.match): P.append("edge ids malformed")
    # no litigant-name columns
    if any(RE_PARTY_KEY.search(n) and n not in PARTY_KEY_ALLOW for n in t.schema.names):
        P.append("litigant-name column present")
    return P


def validate_id_uniqueness(paths: list[str]) -> list[str]:
    """Cross-shard id uniqueness (stream ids only)."""
    seen: set[str] = set(); dups = 0
    for p in paths:
        for b in pq.ParquetFile(p).iter_batches(columns=["id"], batch_size=65536):
            for v in b.column(0).to_pylist():
                if v in seen: dups += 1
                seen.add(v)
    return [f"{dups} duplicate ids across shards"] if dups else []


RE_TOMBSTONE_ID = RE_ID


def validate_tombstone(rec: dict) -> list[str]:
    """One JSON object per line of out/<source>/tombstones.jsonl. Required: id, record_type, source_name, action, reason,
    requested_date (YYYY-MM-DD), tombstoned_date (YYYY-MM-DD). Optional: requester_ref (opaque ticket/ref, no personal data), note."""
    P = []
    req = {"id", "record_type", "source_name", "action", "reason", "requested_date", "tombstoned_date"}
    opt = {"requester_ref", "note"}
    if not req <= set(rec): P.append(f"missing {sorted(req - set(rec))}")
    if set(rec) - req - opt: P.append(f"unknown keys {sorted(set(rec) - req - opt)}")
    if "id" in rec and not (isinstance(rec["id"], str) and RE_ID.match(rec["id"])): P.append("id format")
    if "id" in rec and "record_type" in rec and isinstance(rec["id"], str) and RE_ID.match(rec["id"]) and rec["id"].split(":")[1] != rec["record_type"]:
        P.append("record_type != id type")
    if rec.get("action") not in TOMBSTONE_ACTIONS: P.append(f"action not in {TOMBSTONE_ACTIONS}")
    if rec.get("reason") not in TOMBSTONE_REASONS: P.append(f"reason not in {TOMBSTONE_REASONS}")
    for k in ("requested_date", "tombstoned_date"):
        if k in rec and not (isinstance(rec[k], str) and RE_RDATE.match(rec[k])): P.append(f"{k} not YYYY-MM-DD")
    return P


def validate_tombstones_file(path: str) -> list[str]:
    P = []
    for i, line in enumerate(open(path), 1):
        if line.strip():
            try: rec = json.loads(line)
            except ValueError: P.append(f"line {i}: not JSON"); continue
            P += [f"line {i}: {p}" for p in validate_tombstone(rec)]
    return P


def validate_cross(decision_paths: list[str], opinion_paths: list[str]) -> list[str]:
    """r5: decision.text_sha256 must be non-null and equal to one of its opinions' hashes; every opinion.decision_id exists;
    opinion restricted_ai_training / licence_class / terms.pending_legal_review equal the decision's (streaming, no text read)."""
    dec = {}; dflag = {}
    for p in decision_paths:
        t = pq.read_table(p, columns=["id", "text_sha256", "restricted_ai_training", "licence_class", "metadata_json", "sensitivity_flags"])
        for i, h, r, l, m, sf in zip(*(t.column(n).to_pylist() for n in t.column_names)):
            dec[i] = (h, r, l, (json.loads(m).get("terms") or {}).get("pending_legal_review"))
            dflag[i] = "personal_contact" in (json.loads(sf) if sf else [])
    P = []; orphans = 0; flag_mism = 0; seen: dict[str, set] = {}; nred: dict[str, int] = {}
    for p in opinion_paths:
        t = pq.read_table(p, columns=["decision_id", "text_sha256", "restricted_ai_training", "licence_class", "metadata_json"])
        for did, h, r, l, m in zip(*(t.column(n).to_pylist() for n in t.column_names)):
            if did not in dec: orphans += 1; continue
            seen.setdefault(did, set()).add(h)
            nred[did] = nred.get(did, 0) + int((json.loads(m).get("contact_redaction") or {}).get("emails_redacted", 0) or 0)
            if (r, l, (json.loads(m).get("terms") or {}).get("pending_legal_review")) != dec[did][1:]: flag_mism += 1
    null_h = sum(1 for v in dec.values() if v[0] is None)
    mism = sum(1 for d, v in dec.items() if v[0] is not None and d in seen and v[0] not in seen[d])
    pc_mism = sum(1 for d, f in dflag.items() if f != (nred.get(d, 0) > 0))
    if pc_mism: P.append(f"{pc_mism} decisions whose sensitivity flag personal_contact != (their opinions had e-mails redacted)")
    if orphans: P.append(f"{orphans} opinions without a decision row")
    if null_h: P.append(f"{null_h} decisions with NULL text_sha256")
    if mism: P.append(f"{mism} decisions whose text_sha256 matches none of their opinions")
    if flag_mism: P.append(f"{flag_mism} opinions whose restricted_ai_training/licence_class/pending_legal_review differ from their decision")
    return P


def write_shard(t: pa.Table, path: str, kind: str) -> int:
    probs = validate_caselaw_table(t, kind)
    if probs: raise ValueError("validate_caselaw_table failed: " + "; ".join(probs[:6]))
    pq.write_table(t, path, compression="zstd", row_group_size=4096)
    import os
    return os.path.getsize(path)


if __name__ == "__main__":  # smoke test
    did = make_id("decision", "nl_rechtspraak", "ECLI:NL:HR:2020:1")
    row = dict(id=did, country_iso="NL", jurisdiction_level="national", jurisdiction_raw="NL", source_name="nl_rechtspraak",
               source_type="nl_rechtspraak_api", source_record_id="ECLI:NL:HR:2020:1", source_url="https://x/y", fetch_mode="api",
               retrieval_date="2026-10-28", licence="CC0-1.0", phase="phaseA", source_file="smoke", court_match_status="unmatched",
               court_key_provisional=provisional_key("NL", None, "hoge raad"), court_name_raw="Hoge Raad", decision_date="2020-01-02",
               ecli="ECLI:NL:HR:2020:1", restricted_ai_training=False, parties_redaction_status="source_pseudonymised", odd="x", case_name="A v. B", licence_class="open",
               metadata_json={"terms": {"basis": "smoke", "evidence_url": "https://x", "checked": "2026-10-29", "pending_legal_review": False}, "x": {"respondent": "Z"}})
    t = cast_rows([row], "decision"); assert PRIVACY_DROPPED and "case_name" not in json.loads(t.column("metadata_json")[0].as_py()).get("extras", {})
    assert not validate_caselaw_table(t, "decision"), validate_caselaw_table(t, "decision")
    orow = dict(id=make_id("opinion", "nl_rechtspraak", "ECLI:NL:HR:2020:1#0"), decision_id=did, country_iso="NL", jurisdiction_level="national",
                jurisdiction_raw="NL", source_name="nl_rechtspraak", source_type="nl_rechtspraak_api", source_record_id="ECLI:NL:HR:2020:1#0",
                source_url="https://x/y", fetch_mode="api", phase="phaseA", source_file="smoke", text="hello", text_sha256=text_sha256("hello"),
                ocr=False, restricted_ai_training=False, licence_class="open", parties_redaction_status="source_pseudonymised", opinion_type="lead",
                metadata_json={"terms": {"basis": "smoke", "evidence_url": "https://x", "checked": "2026-10-29", "pending_legal_review": False}})
    o = cast_rows([orow], "opinion"); assert not validate_caselaw_table(o, "opinion"), validate_caselaw_table(o, "opinion")
    # negative tests
    def bad(rows, kind, needle, **upd):
        rr = [dict(rows[0], **upd)]
        try: tt = cast_rows(rr, kind)
        except ValueError as e: assert needle in str(e), e; return
        pr = validate_caselaw_table(tt, kind); assert any(needle in p for p in pr), (needle, pr)
    bad([row], "decision", "restricted_ai_training=false", metadata_json={})
    bad([row], "decision", "case name", canonical_key="Roe v. Wade, 410 U.S. 113")
    bad([row], "decision", "pending_legal_review", metadata_json={"terms": {"basis": "x", "evidence_url": "https://x", "checked": "2026-10-29"}})
    bad([row], "decision", "NC/gated", licence_class="NC", metadata_json={"terms": {"basis": "x", "evidence_url": "https://x", "checked": "2026-10-29", "pending_legal_review": False}})
    bad([row], "decision", "text_sha256", text_sha256="zz")
    bad([row], "decision", "language", language="eng")
    bad([row], "decision", "language", language="zz")
    for cn in ("Dupont c. Durand", "Jansen tegen Pietersen", "Müller gegen Schmidt", "In re Smith", "Smith v.Jones"):
        bad([row], "decision", "case name", canonical_key=cn)
    for pk in ("partyName", "plaintiffName", "CaseTitle", "nameOfParties", "appellee", "complainant"):
        assert RE_PARTY_KEY.search(pk), pk
        t_ = cast_rows([dict(row, metadata_json={"terms": row["metadata_json"]["terms"], pk: "x"})], "decision")
        assert pk not in json.loads(t_.column("metadata_json")[0].as_py())
        bad_md = t_.set_column(t_.schema.get_field_index("metadata_json"), "metadata_json", pa.array([json.dumps({"terms": row["metadata_json"]["terms"], pk: "x"})]))
        assert any("litigant-name keys" in p for p in validate_caselaw_table(bad_md, "decision")), pk
    bad([row], "decision", "decision_type", decision_type="weird")
    bad([row], "decision", "sensitivity_flags", sensitivity_flags=["sealed"])
    bad([row], "decision", "judges_raw", judges_raw=[{"name": "X", "role": "j", "judge_entity_key": "k"}])
    bad([orow], "opinion", "text_format", text_format="rtf")
    bad([orow], "opinion", "opinion_type", opinion_type="x")
    bad([orow], "opinion", "licence_class", licence_class="free")
    d0 = cast_rows([dict(row, source_url=None, fetch_mode="live")], "decision")
    assert any("retrieval" in p or "source_url" in p for p in validate_caselaw_table(d0, "decision"))
    d1 = cast_rows([dict(row, parties_redaction_status=None, restricted_ai_training=None)], "decision")
    assert d1.column("restricted_ai_training")[0].as_py() is True and d1.column("parties_redaction_status")[0].as_py() == "unknown"
    assert provisional_key("NL", None, "", "s", "a") != provisional_key("NL", None, "", "s", "b")
    # ---- r5 tests
    bad([row], "decision", "pending_legal_review=true requires", metadata_json={"terms": {"basis": "x", "evidence_url": "https://x", "checked": "2026-10-29", "pending_legal_review": True}})
    t5 = cast_rows([dict(row, restricted_ai_training=True, metadata_json={"terms": {"basis": "x", "evidence_url": "https://x", "checked": "2026-10-29", "pending_legal_review": True}})], "decision")
    assert not validate_caselaw_table(t5, "decision")
    drow = dict(row, id=make_id("docket", "nl_rechtspraak", "d1"), record_type="docket", docket_number="C/1", licence_class="NC", restricted_ai_training=False)
    drow = {k: v for k, v in drow.items() if k not in ("ecli", "decision_date", "odd", "case_name")}
    bad([drow], "docket", "NC/gated")
    for pk in ("partij", "Eiser", "Partei", "demandeur", "défendeur", "name", "fullName", "Full_Name", "\uff30\uff21\uff32\uff34\uff39", "ｐartyName", "party\u200bName"):
        assert RE_PARTY_KEY.search(pk), pk
    for ok_k in ("courtName", "filename", "court_name_raw", "hostname", "celex", "seat"):
        assert not RE_PARTY_KEY.search(ok_k), ok_k
    for cn in ("Smith contra Jones", "Smith c/ Jones", "Smith ./. Jones", "Smith -v- Jones", "Kowalski przeciwko Nowak", "Novak proti Svoboda", "Larsen mot Hansen", "Smith, In re", "Re Smith"):
        assert RE_CASE_NAME_VALUE.search(cn), cn
        bad([row], "decision", "case name", canonical_key=cn)
    for fine in ("Case C 123/20", "Re-opened", "C-123/20", "T-45/19 P", "ECLI:EU:C:2020:1", "[2020] UKSC 1", "410 U.S. 113", "C/9452/2025", "02-270462-20 (ontneming)"):
        assert not RE_CASE_NAME_VALUE.search(fine), fine
    for bd in ("2026-02-31", "2026-13-01", "2026-00-10", "2025-02-29"):
        assert not RE_RDATE.match(bd), bd
        bad([row], "decision", "retrieval_date", retrieval_date=bd)
    assert RE_RDATE.match("2024-02-29") and RE_DATE.match("2026") and RE_DATE.match("2026-05") and not RE_DATE.match("2026-02-30")
    # matched row needs candidates + revision
    mrow = dict(row, court_match_status="matched", court_key_provisional=None, court_entity_key="wc1e:court:" + "a" * 24)
    bad([mrow], "decision", "court_entity_key_candidates")
    mt = cast_rows([dict(mrow, metadata_json={**row["metadata_json"], "court_entity_key_candidates": ["wc1e:court:" + "a" * 24, "wc1e:court:" + "b" * 24], "courts_dataset_revision": COURTS_DATASET_REVISION})], "decision")
    assert not validate_caselaw_table(mt, "decision"), validate_caselaw_table(mt, "decision")
    ok = dict(id=did, record_type="decision", action="drop", reason="takedown_request", source_name="nl_rechtspraak", requested_date="2026-10-29", tombstoned_date="2026-10-29")
    assert not validate_tombstone(ok) and validate_tombstone(dict(ok, reason="x")) and validate_tombstone(dict(ok, extra=1))
    # ---- r6 tests
    for pk in ("partie", "parte", "Partes", "recourant", "Recourant_Name", "beschwerdef\u00fchrer", "Beschwerdef\u00fchrerin", "autor", "autorName", "AUTOR", "r\u00e9u", "reu_name", "recorrido", "recorridoNome", "beklagte", "agravante"):
        assert RE_PARTY_KEY.search(pk), pk
    for ok_k in ("department", "departement", "autorite", "autoridad", "preuve", "reuters", "partial", "particle", "participant", "author_url", "authority", "report_date", "aparte", "courtName"):
        assert not RE_PARTY_KEY.search(ok_k), ok_k
    for cn in ("Smith against Jones", "Silva x Souza", "Rossi e Bianchi", "Garcia y L\u00f3pez", "Silva Souza x Pereira Lima"):
        assert RE_CASE_NAME_VALUE.search(cn), cn
        bad([row], "decision", "case name", canonical_key=cn)
    for fine in ("BGE 116 V 182", "BGE 116 V Erw. 3", "ATF 140 V 12", "BGE 133 V", "BGE 133 V, E. 3", "5A_123/2020 BGE 120 Ia 5", "C-123/20 e 456", "AREsp 123 e 456", "REsp 12 y 13", "Art. 5 x 2", "x Smith", "Rossi E Bianchi"):
        assert not RE_CASE_NAME_VALUE.search(fine), fine
    assert not RE_COURT_NAME_CASE.search("Tribunale di Roma e Latina Corte") and not RE_COURT_NAME_CASE.search("Tribunal Superior y Audiencia Provincial")
    assert RE_COURT_NAME_CASE.search("Smith against Jones")
    for ok_name in ("Tribunale di Roma e Latina", "Tribunal Superior y Audiencia"):
        t_ = cast_rows([dict(row, court_name_raw=ok_name)], "decision"); assert not validate_caselaw_table(t_, "decision"), ok_name
    assert clean_label("  ZH 1 \r") == "ZH 1" and clean_label("A  B\tC") == "A B C" and clean_label("undefined") is None and clean_label(" Undefined ") is None and clean_label("  ") is None and clean_label(None) is None
    for col, v in (("docket_number", "undefined"), ("docket_number", " X 1"), ("docket_number", "X 1\r"), ("docket_number", "A  B"), ("court_name_raw", "Hof  van X"), ("court_name_raw", "null")):
        bad([row], "decision", "not normalised", **{col: v})
    bad([row], "decision", "licence_class unknown requires", licence_class="unknown")
    TERMS_OK = {"basis": "x", "evidence_url": "https://x", "checked": "2026-10-29", "pending_legal_review": False}
    bad([row], "decision", "must sit only under metadata_json.terms", metadata_json={"terms": TERMS_OK, "pending_legal_review": True})
    bad([row], "decision", "must sit only under metadata_json.terms", restricted_ai_training=True, metadata_json={"terms": TERMS_OK, "x": {"pending_legal_review": False}})
    bad([row], "decision", "must sit only under metadata_json.terms", restricted_ai_training=True, metadata_json={"terms": dict(TERMS_OK, sub={"pending_legal_review": True})})
    bad([row], "decision", "must be a boolean", restricted_ai_training=True, metadata_json={"terms": dict(TERMS_OK, pending_legal_review="yes")})
    assert not validate_caselaw_table(cast_rows([dict(row, restricted_ai_training=True, licence_class="unknown", metadata_json={"terms": dict(TERMS_OK, pending_legal_review=True)})], "decision"), "decision")
    bad([row], "decision", "body_type", body_type="tribunal")
    assert not validate_caselaw_table(cast_rows([dict(row, body_type="executive_body")], "decision"), "decision")
    bad([row], "decision", "date_precision", decision_date="2020-01-01", metadata_json={"terms": TERMS_OK, "date_precision": "year"})
    assert not validate_caselaw_table(cast_rows([dict(row, decision_date="2020", metadata_json={"terms": TERMS_OK, "date_precision": "year"})], "decision"), "decision")
    assert redact_emails("mail a.b@x.ch, c@y.org") == ("mail [email redacted], [email redacted]", 2) and redact_emails("none") == ("none", 0)
    bad([orow], "opinion", "unredacted e-mail", text="write to a@b.ch", text_sha256=text_sha256("write to a@b.ch"))
    bad([orow], "opinion", "emails_redacted", metadata_json={"terms": TERMS_OK, "contact_redaction": {"emails_redacted": 1}})
    assert not validate_caselaw_table(cast_rows([dict(orow, text="write to [email redacted]", text_sha256=text_sha256("write to [email redacted]"), metadata_json={"terms": TERMS_OK, "contact_redaction": {"emails_redacted": 1}})], "opinion"), "opinion")
    bad([row], "decision", "sensitivity_flags", sensitivity_flags=["email"])
    assert not validate_caselaw_table(cast_rows([dict(row, sensitivity_flags=["personal_contact"])], "decision"), "decision")
    # ---- r7 tests
    for pk in ("Beschwerdegegner", "beschwerdegegnerin", "apelante", "Apelante_Nome", "resistente", "querelant", "querelante", "imputato", "convenuto", "convenuti"):
        assert RE_PARTY_KEY.search(pk), pk
    for ok_k in ("resistance", "resistant_alloy", "convention", "impute_date", "apelacao", "querela_date"):
        assert not RE_PARTY_KEY.search(ok_k), ok_k
    for em in ("Jos\u00e9.M\u00fcller@universit\u00e4t-z\u00fcrich.ch", "m\u00fcller@b\u00fcro.ch", "anna @ example.org", "anna\u00a0@\u00a0example.org", "a.b\uff20x.ch", "john_doe@x.com", "info@\u00e9cole.fr", "x@y.org."):
        assert RE_EMAIL.search(em), em
    assert redact_emails("john_doe@x.com") == ("[email redacted]", 1) and redact_emails("Mail anna @ example.org.") == ("Mail [email redacted].", 1)
    for no in ("[telefoonnummer] @s.whatsapp.net", "@ [gebruikersnaam]", "C@b_ag.com", "aon@rnait", "@uvre", "ticker @ ct7", "St[at]es", "a @b.ch", "a@ b.ch"):
        assert not RE_EMAIL.search(no), no
    bad([orow], "opinion", "unredacted e-mail", text="a @ b.ch", text_sha256=text_sha256("a @ b.ch"))
    ND = {"terms": TERMS_OK, "not_decision": {"reason": "guideline"}}
    assert not validate_caselaw_table(cast_rows([dict(row, body_type=None, metadata_json=ND)], "decision"), "decision")
    bad([row], "decision", "not_decision", body_type="court", metadata_json=ND)
    bad([row], "decision", "not_decision", body_type=None, metadata_json={"terms": TERMS_OK, "not_decision": True})
    bad([row], "decision", "not_decision", body_type=None, metadata_json={"terms": TERMS_OK, "not_decision": {"reason": ""}})
    PH = {"evidence": "source_id_nodate", "original_decision_date": "2021-01-01", "year_unverified": True}
    assert not validate_caselaw_table(cast_rows([dict(row, decision_date=None, decision_year=None, metadata_json={"terms": TERMS_OK, "date_placeholder": dict(PH, date_unknown=True)})], "decision"), "decision")
    bad([row], "decision", "date_placeholder", decision_date=None, decision_year=None, metadata_json={"terms": TERMS_OK, "date_placeholder": PH})
    bad([row], "decision", "date_placeholder", metadata_json={"terms": TERMS_OK, "date_placeholder": dict(PH, evidence="made_up")})
    bad([row], "decision", "date_placeholder", decision_date="2020", metadata_json={"terms": TERMS_OK, "date_precision": "year", "date_placeholder": dict(PH, recovered_from_text={"snippet": "x"})})
    assert not validate_caselaw_table(cast_rows([dict(row, decision_date="2020-03-04", decision_year=2020, metadata_json={"terms": TERMS_OK, "date_placeholder": dict(PH, evidence="source_id_no_date_and_no_1_january_in_text", recovered_from_text={"snippet": "x"})})], "decision"), "decision")
    # ---- r8 tests
    bad([row], "decision", "decision_date is NULL without", decision_date=None, decision_year=None, metadata_json={"terms": TERMS_OK})
    PH0 = {"evidence": "source_id_zero_date", "original_decision_date": "0000-00-00", "date_unknown": True}
    assert not validate_caselaw_table(cast_rows([dict(row, decision_date=None, decision_year=None, metadata_json={"terms": TERMS_OK, "date_placeholder": PH0})], "decision"), "decision")
    PH1 = {"evidence": "source_id_nodate", "original_decision_date": "2021-01-01", "date_unknown": True, "year_basis": "publication_volume_year"}
    assert not validate_caselaw_table(cast_rows([dict(row, decision_date=None, decision_year=None, metadata_json={"terms": TERMS_OK, "date_placeholder": PH1, "publication_year": 1988})], "decision"), "decision")
    bad([row], "decision", "publication_year", decision_date=None, decision_year=None, metadata_json={"terms": TERMS_OK, "date_placeholder": PH1, "publication_year": "1988"})
    bad([row], "decision", "publication_year", metadata_json={"terms": TERMS_OK, "publication_year": 1988})
    for k in SCHEMAS: print(k, len(SCHEMAS[k]))
    print("ok")
