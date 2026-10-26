"""world_municipal_law schema (WORLDWIDE_SCRAPE_PLAN.md §1.2 / §4.2).

Single source of truth for scraper bots, the normalizer (run_loop.py) and the
uploader. Only stdlib is needed for place_key()/cid()/validate_record();
pyarrow is imported lazily for html_schema()/validate_file() on parquet.

    import sys; sys.path.insert(0, "/workspace/world_law/pipeline")
    from schema import place_key, html_cid, validate_record, validate_file

See SCHEMA.md next to this file for the staging convention.
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# Re-use the EXISTING US cid function (copied verbatim from
# ipfs_datasets_py .../municipal_law_database_scrapers/hub/parquet_writer.py)
# so US CIDs stay byte-identical.
from world.parquet_writer import cid_v1_raw_sha256  # noqa: E402

SCHEMA_VERSION = "1.2.0"  # 1.1.0: optional provenance columns + extra_metadata (appended); 1.2.0: pdf_ref (appended)
PDF_REPO_ID = "endomorphosis/world_law_scanned_pdfs"  # raw image-only scanned PDFs awaiting OCR
REPO_ID = "endomorphosis/world_municipal_law"
NATIONAL_REPO_ID = "endomorphosis/world_national_law"   # national + subnational (iso:* places), split 2026-10-11
NATIONAL_LEVELS = ("country", "adm1", "supranational")


def is_national_key(pkey: str) -> bool:
    """iso:* places (country / first-level subdivision / supranational, SCHEMA.md §3) live in NATIONAL_REPO_ID;
    everything else (municipal, county, water board, ...) in REPO_ID."""
    return str(pkey).startswith("iso_")
ROOT = "world_law"  # top-level dir inside the dataset repo

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
DOC_TYPES = ("code_section", "ordinance", "regulation", "statute", "gazette_act", "decision")
CONTENT_FORMATS = ("html", "xml", "pdf_text", "docx_text")

# Jurisdiction levels. National / subnational law uses the "iso:" place_id
# scheme (see SCHEMA.md §3). Municipal levels reuse the labels already in
# global_municipalities_candidate.csv (municipality, county, township, ...).
NATIONAL_LEVEL = "country"          # place_id iso:{CC}           e.g. iso:FR
SUBNATIONAL_LEVEL = "adm1"          # place_id iso:{ISO 3166-2}   e.g. iso:US-CA, iso:DE-BY
SUPRANATIONAL_LEVEL = "supranational"  # place_id iso:EU (country_code EU)
KNOWN_ADMIN_LEVELS = {
    NATIONAL_LEVEL, SUBNATIONAL_LEVEL, SUPRANATIONAL_LEVEL, "adm2",
    "municipality", "gram_panchayat", "township", "parish", "district", "union",
    "county", "town", "subcounty", "province", "community", "block", "department",
    "region", "sector", "state", "governorate", "chiefdom", "territory",
    "prefecture", "unitary_authority", "canton", "council_area", "oblast",
    "principal_area", "voivodeship", "emirate", "city",
    "water_board",   # NL waterschap / hoogheemraadschap (codes/place_additions.csv); PL powiats use "county"
}

# ---------------------------------------------------------------------------
# Columns
# ---------------------------------------------------------------------------
US_HTML_COLUMNS = ["cid", "doc_id", "doc_order", "html_title", "html"]  # unchanged, first, same order
WORLD_HTML_COLUMNS = [
    "place_id", "country_code", "gnis", "source_platform", "source_url", "doc_type",
    "language", "title_native", "number", "adopted_date", "published_date",
    "effective_date", "in_force", "consolidated", "content_format", "text", "retrieved_at",
]
LEGACY_HTML_COLUMNS = US_HTML_COLUMNS + WORLD_HTML_COLUMNS  # v1.0.0 files (22 columns)
# v1.1.0: optional provenance columns, appended so the first 22 columns keep their order.
# Read from the record's top level, else extra_metadata, else extra_metadata.archive.
PROVENANCE_STR = ["archive_source", "archive_crawl_id", "archive_timestamp", "archive_url", "original_url",
                  "source_policy", "source_org", "license_note"]
PROVENANCE_BOOL = ["content_complete", "possibly_stale", "source_official"]
PROVENANCE_COLUMNS = ["archive_source", "archive_crawl_id", "archive_timestamp", "archive_url", "original_url",
                      "content_complete", "possibly_stale", "source_policy", "source_official", "source_org",
                      "license_note", "extra_metadata"]  # extra_metadata = JSON string of all other staged keys
V11_HTML_COLUMNS = LEGACY_HTML_COLUMNS + PROVENANCE_COLUMNS  # v1.1.0 files (34 columns)
# v1.2.0: pdf_ref = "<PDF_REPO_ID>:pdfs/<CC>/[<b>/]<place_key>/<sha256>.pdf" (loose) or, since 2026-10-18,
# "<PDF_REPO_ID>:shards/<CC>/<YYYY>/<MM>/<CC>_<seq>.tar#member=..&offset=..&size=..&sha256=.." (tools/pdf_shards.py) when the source document is an
# image-only scanned PDF published in PDF_REPO_ID (else null). Set by the pipeline from state/pdf_refs/, never by bots.
PDF_COLUMNS = ["pdf_ref"]
HTML_COLUMNS = V11_HTML_COLUMNS + PDF_COLUMNS
# Staged keys never published (local filesystem paths of the scraper box).
DROP_KEYS = {"raw_path", "raw_xml_path"}

# ---------------------------------------------------------------------------
# Source policy: rows that must NEVER be published (held locally in held/<bot>/<CC>/)
# ---------------------------------------------------------------------------
# HOLD: live fetches whose robots.txt was unreachable/disallowed (RFC 9309: treat as disallow-all),
#       and any NON-archive-sourced record flagged robots_disallowed=true (or robots_txt_disallowed=true).
# ALLOW: noarchive_meta, archived_robots_disallowed, robots_404_allow_rfc9309, robots_allowed_rfc9309,
#        *_archive_fallback, any other value, or no source_policy.  (policy decision 2026-10-10)
HOLD_SOURCE_POLICIES = frozenset({"robots_unreachable", "robots_disallowed"})
ROBOTS_FLAG_KEYS = ("robots_disallowed", "robots_txt_disallowed")
ARCHIVE_KEYS = ("archive_source", "archive_url", "archive_timestamp", "archive_crawl_id")

# Place-level fields a bot may put on staged records (taken from the first
# record that has them); they go to metadata JSON / places.parquet, NOT to the
# html parquet.
PLACE_FIELDS = ["place_name", "qid", "iso_3166_2", "admin_level", "state_code",
                "platform", "platform_place_id"]

# Staged-record requirements (what a bot MUST provide).
REQUIRED_STAGED = ["place_id", "country_code", "doc_id", "source_platform", "source_url",
                   "doc_type", "language", "content_format", "consolidated"]
# Derived by the pipeline if the bot leaves them out.
DERIVED = {"cid", "doc_order", "text", "html", "html_title", "retrieved_at", "gnis"}

METADATA_FIELDS = ["place_id", "place_key", "qid", "gnis", "country_code", "iso_3166_2",
                   "admin_level", "place_name", "state_code", "platform", "platform_place_id",
                   "total_docs", "total_sections", "last_updated", "schema_version"]

PLACES_COLUMNS = ["place_id", "place_key", "qid", "gnis", "country_code", "iso_3166_2",
                  "admin_level", "place_name", "platform", "platform_place_id",
                  "total_docs", "html_path", "metadata_path", "last_updated", "n_shards",
                  "source_repo", "source_paths", "has_local_data"]
# source_repo/source_paths/has_local_data: has_local_data=false rows are POINTERS to places whose documents live in
# another dataset (US: endomorphosis/american_municipal_law; see world_law_loader.py); html_path is then a path in
# source_repo and source_paths lists every copy there.
# Sharding: a place over SHARD_MAX_ROWS rows or ~SHARD_MAX_BYTES on disk is split into
# world_law/data/{CC}/{place_key}.s0001_html.parquet, .s0002_..., (html_path then holds a glob).
SHARD_MAX_ROWS = 20_000
SHARD_MAX_BYTES = 200 * 1024 * 1024

MANIFEST_FIELDS = ["path_in_repo", "sha256", "bytes", "rows", "place_id", "place_key",
                   "country_code", "source_files", "built_at", "schema_version"]


def html_schema():
    """pyarrow schema of world_law/data/{CC}/{place_key}_html.parquet."""
    import pyarrow as pa
    s = pa.string()
    return pa.schema([
        pa.field("cid", s, nullable=False),
        pa.field("doc_id", s, nullable=False),
        pa.field("doc_order", pa.uint32(), nullable=False),  # same type as US files
        pa.field("html_title", s),
        pa.field("html", s),
        pa.field("place_id", s, nullable=False),
        pa.field("country_code", s, nullable=False),
        pa.field("gnis", s),                 # nullable; US only
        pa.field("source_platform", s, nullable=False),
        pa.field("source_url", s, nullable=False),
        pa.field("doc_type", s, nullable=False),
        pa.field("language", s, nullable=False),
        pa.field("title_native", s),
        pa.field("number", s),
        pa.field("adopted_date", s),         # ISO 8601 YYYY[-MM[-DD]]
        pa.field("published_date", s),
        pa.field("effective_date", s),
        pa.field("in_force", pa.bool_()),    # nullable = unknown
        pa.field("consolidated", pa.bool_(), nullable=False),
        pa.field("content_format", s, nullable=False),
        pa.field("text", s),
        pa.field("retrieved_at", s, nullable=False),  # ISO 8601 UTC, e.g. 2026-10-10T22:00:00Z
        # --- v1.1.0 optional provenance (all nullable) ---
        pa.field("archive_source", s),       # wayback | commoncrawl | ... (null = live fetch)
        pa.field("archive_crawl_id", s),
        pa.field("archive_timestamp", s),
        pa.field("archive_url", s),
        pa.field("original_url", s),
        pa.field("content_complete", pa.bool_()),  # false = metadata-only / partial record (valid)
        pa.field("possibly_stale", pa.bool_()),
        pa.field("source_policy", s),        # lower-case; several values joined with ';'
        pa.field("source_official", pa.bool_()),
        pa.field("source_org", s),
        pa.field("license_note", s),
        pa.field("extra_metadata", s),       # JSON object (string) of all other staged keys
        # --- v1.2.0 (nullable) ---
        pa.field("pdf_ref", s),              # "<PDF_REPO_ID>:<path>" of the scanned source PDF, or null
    ], metadata={b"schema": b"world_municipal_law", b"schema_version": SCHEMA_VERSION.encode()})


def places_schema():
    import pyarrow as pa
    s = pa.string()
    return pa.schema([
        ("place_id", s), ("place_key", s), ("qid", s), ("gnis", s), ("country_code", s),
        ("iso_3166_2", s), ("admin_level", s), ("place_name", s), ("platform", s),
        ("platform_place_id", s), ("total_docs", pa.int64()), ("html_path", s),
        ("metadata_path", s), ("last_updated", pa.int64()), ("n_shards", pa.int64()),
        ("source_repo", s), ("source_paths", pa.list_(s)), ("has_local_data", pa.bool_()),
    ])


# ---------------------------------------------------------------------------
# Keys / CIDs / paths
# ---------------------------------------------------------------------------
_CC_RE = re.compile(r"^[A-Z]{2}$")
# KG-kg_cbd:<organ id>: Kyrgyz aiyl aimaks / councils without a Wikidata item, keyed by the CBD (cbd.minjust.gov.kg)
# issuing-organ id (codes/proposed/KG_aiyl_aimaks.csv, id_scheme=kg_cbd). Only valid with country_code KG. The id is
# permanent: a Wikidata QID found later goes into the alias column (place_codes kg_cbd_body / qid), never replaces it.
KG_CBD_PREFIX = "KG-kg_cbd:"
_KG_CBD_ORGAN_RE = re.compile(r"^[0-9A-Za-z-]+$")
_PLACE_ID_RE = re.compile(r"^(gnis:\d+|wd:Q\d+|iso:[A-Z]{2}(-[A-Z0-9]{1,3})?|KG-kg_cbd:[0-9A-Za-z-]+)$")
_PLACE_KEY_RE = re.compile(r"^[A-Za-z0-9_\-]+$")
_DATE_RE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")
_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})$")
_LANG_RE = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$")


def place_key(place_id: Optional[str] = None, gnis: Optional[str] = None,
              country_code: Optional[str] = None) -> str:
    """File stem / todo key / log key for a jurisdiction.

    US municipal rows -> the bare GNIS (so US file names and CIDs are unchanged).
    Everything else  -> place_id with ':' -> '_' (wd:Q90 -> wd_Q90, iso:US-CA -> iso_US-CA).
    """
    pid = (place_id or "").strip()
    g = str(gnis or "").strip()
    if pid.startswith("gnis:"):
        return pid.split(":", 1)[1]
    if not pid and g and (country_code or "US").upper() == "US":
        return g
    if not pid:
        raise ValueError("place_key needs place_id (or a US gnis)")
    if pid.startswith(KG_CBD_PREFIX) and not _KG_CBD_ORGAN_RE.match(pid[len(KG_CBD_PREFIX):]):
        raise ValueError(f"bad kg_cbd organ id in {pid!r} (want [0-9A-Za-z-]+)")
    return pid.replace(":", "_")


def kg_cbd_place_id(organ_id: str) -> str:
    """KG-kg_cbd:<organ id> for a CBD issuing-organ id ([0-9A-Za-z-]+ only; raises otherwise)."""
    oid = str(organ_id or "").strip()
    if not _KG_CBD_ORGAN_RE.match(oid):
        raise ValueError(f"bad kg_cbd organ id {organ_id!r} (want [0-9A-Za-z-]+)")
    return KG_CBD_PREFIX + oid


def place_id_from_key(pkey: str) -> str:
    """Inverse of place_key() for non-US keys: wd_Q90 -> wd:Q90, iso_US-CA -> iso:US-CA,
    KG-kg_cbd_<organ> -> KG-kg_cbd:<organ> (organ ids never contain '_')."""
    k = str(pkey)
    kp = KG_CBD_PREFIX.replace(":", "_")
    if k.startswith(kp):
        return KG_CBD_PREFIX + k[len(kp):]
    return k.replace("_", ":", 1)


def html_cid(pkey: str, doc_id: str) -> str:
    """cid_v1_raw_sha256(f"{place_key}_{doc_id}.json") -- identical to US html_cid(gnis, doc_id)."""
    return cid_v1_raw_sha256(f"{pkey}_{doc_id}.json")


cid = html_cid  # alias


# ---------------------------------------------------------------------------
# Repo layout (SINGLE SOURCE OF TRUTH for every data / metadata path).
# HF allows at most 10,000 files per directory. Countries with more than BUCKET_THRESHOLD places are listed in
# BUCKETED_COUNTRIES and use 256 hash buckets:
#     world_law/data/<CC>/<b>/<place_key>_html.parquet   world_law/metadata/<CC>/<b>/<place_key>.json
#     b = sha256(place_key)[:2] (lower-case hex, "00".."ff")
# every other country stays flat (world_law/data/<CC>/<place_key>_html.parquet). iso_* keys (world_national_law,
# a handful of places per country) are never bucketed. Add a country here (and migrate it with
# tools/migrate_buckets.py) when it passes BUCKET_THRESHOLD places.
# ---------------------------------------------------------------------------
BUCKET_THRESHOLD = 5_000
BUCKETED_COUNTRIES = frozenset({"FR", "IT", "DE"})
BUCKET_HEX = 2  # 16**2 = 256 buckets


def place_bucket(pkey: str) -> str:
    import hashlib
    return hashlib.sha256(str(pkey).encode("utf-8")).hexdigest()[:BUCKET_HEX]


def is_bucketed(cc: str, pkey: str) -> bool:
    return str(cc).upper() in BUCKETED_COUNTRIES and not is_national_key(pkey)


def place_dir(sub: str, cc: str, pkey: str, bucketed: Optional[bool] = None) -> str:
    """Repo dir holding a place's files: sub is "data" or "metadata". bucketed=None: the current layout."""
    b = is_bucketed(cc, pkey) if bucketed is None else bucketed
    return f"{ROOT}/{sub}/{cc}/{place_bucket(pkey)}" if b else f"{ROOT}/{sub}/{cc}"


def place_dirs(sub: str, cc: str, pkey: str) -> List[str]:
    """Current dir first, then the other (legacy) layout's dir: readers and stale-file checks accept both."""
    cur = place_dir(sub, cc, pkey)
    other = place_dir(sub, cc, pkey, bucketed=not is_bucketed(cc, pkey))
    return [cur] if other == cur or is_national_key(pkey) else [cur, other]


def html_path(cc: str, pkey: str) -> str:
    return f"{place_dir('data', cc, pkey)}/{pkey}_html.parquet"


def shard_path(cc: str, pkey: str, i: int) -> str:
    """i is 1-based: world_law/data/{CC}[/{b}]/{place_key}.s0001_html.parquet"""
    return f"{place_dir('data', cc, pkey)}/{pkey}.s{i:04d}_html.parquet"


def shard_glob(cc: str, pkey: str) -> str:
    return f"{place_dir('data', cc, pkey)}/{pkey}.s*_html.parquet"


def is_place_data_file(path_in_repo: str, cc: str, pkey: str, legacy: bool = True) -> bool:
    """True for the single-file or any shard path of this place (current layout; legacy=True: either layout)."""
    for d in (place_dirs("data", cc, pkey) if legacy else [place_dir("data", cc, pkey)]):
        pre = f"{d}/{pkey}"
        if path_in_repo == pre + "_html.parquet" or re.fullmatch(re.escape(pre) + r"\.s\d{4,}_html\.parquet",
                                                                  path_in_repo):
            return True
    return False


def metadata_path(cc: str, pkey: str) -> str:
    return f"{place_dir('metadata', cc, pkey)}/{pkey}.json"


def legacy_metadata_paths(cc: str, pkey: str) -> List[str]:
    return [f"{d}/{pkey}.json" for d in place_dirs("metadata", cc, pkey)[1:]]


def file_dir(path_in_repo: str) -> str:
    """The repo dir a file sits in (the unit HF's 10,000-files limit applies to)."""
    return path_in_repo.rsplit("/", 1)[0]


def local_place_files(out_dir, cc: str, pkey: str, legacy: bool = True) -> List[Path]:
    """Local data parquet of one place under out_dir (both layouts unless legacy=False), sorted, current first."""
    res: List[Path] = []
    for d in (place_dirs("data", cc, pkey) if legacy else [place_dir("data", cc, pkey)]):
        dd = Path(out_dir) / d
        if dd.is_dir():
            res += sorted(p for p in dd.glob(f"{pkey}*_html.parquet")
                          if is_place_data_file(f"{d}/{p.name}", cc, pkey, legacy))
    return res


def iter_local_metadata(root) -> Iterator[Path]:
    """Every metadata JSON under <out>/world_law/metadata (flat and bucketed), sorted by (cc, file name)."""
    m = Path(root) / "metadata"
    if not m.is_dir():
        return iter(())
    return iter(sorted(list(m.glob("*/*.json")) + list(m.glob("*/??/*.json")),
                       key=lambda p: (p.relative_to(m).parts[0], p.name)))


def iter_local_data(root) -> Iterator[Tuple[str, Path]]:
    """(cc, path) of every data parquet under <out>/world_law/data (flat and bucketed)."""
    d = Path(root) / "data"
    if not d.is_dir():
        return iter(())
    return iter(sorted(((p.relative_to(d).parts[0], p) for p in
                        list(d.glob("*/*_html.parquet")) + list(d.glob("*/??/*_html.parquet"))),
                       key=lambda t: (t[0], t[1].name)))


# ---------------------------------------------------------------------------
# Scanned-PDF repo layout (PDF_REPO_ID): pdfs/<CC>/[<b>/]<place_key>/<sha256>.pdf
# b = place_bucket(place_key) for PDF_BUCKETED_COUNTRIES (same rule as the law repos: >~9,000 place folders under
# one country would break HF's 10,000-entries-per-directory limit). A single place folder holding > PDF_PLACE_MAX
# files is split into <place_key>/<sha256[:2]>/<sha256>.pdf (PDF_SPLIT_PLACES, decided by the uploader).
# ---------------------------------------------------------------------------
PDF_ROOT = "pdfs"
PDF_BUCKETED_COUNTRIES = BUCKETED_COUNTRIES
PDF_PLACE_MAX = 9_000


def pdf_path(cc: str, pkey: str, sha256: str, split: bool = False) -> str:
    cc = str(cc).upper()
    d = f"{PDF_ROOT}/{cc}/{place_bucket(pkey)}/{pkey}" if is_bucketed(cc, pkey) else f"{PDF_ROOT}/{cc}/{pkey}"
    return f"{d}/{sha256[:2]}/{sha256}.pdf" if split else f"{d}/{sha256}.pdf"


def pdf_ref(path_in_repo: str, repo: str = PDF_REPO_ID) -> str:
    return f"{repo}:{path_in_repo}"


def national_place_id(cc: str) -> str:
    return f"iso:{cc.upper()}"


def subnational_place_id(iso_3166_2: str) -> str:
    return f"iso:{iso_3166_2.upper()}"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Source-policy hold
# ---------------------------------------------------------------------------
def _sub_dicts(rec: Dict[str, Any]) -> List[Dict[str, Any]]:
    """[record, extra_metadata, extra_metadata.archive] (extra_metadata may be a JSON string)."""
    out = [rec]
    em = rec.get("extra_metadata")
    if isinstance(em, str) and em.strip().startswith("{"):
        try:
            em = json.loads(em)
        except ValueError:
            em = None
    if isinstance(em, dict):
        out.append(em)
        if isinstance(em.get("archive"), dict):
            out.append(em["archive"])
    return out


def _policy_tokens(v: Any) -> List[str]:
    if v is None:
        return []
    vals = v if isinstance(v, (list, tuple, set)) else re.split(r"[;,|]", str(v))
    return [re.sub(r"[\s\-]+", "_", str(x).strip().lower()) for x in vals if str(x).strip()]


def source_policies(rec: Dict[str, Any]) -> List[str]:
    """All source_policy tokens (lower-case, top level + extra_metadata[.archive]), de-duplicated, ordered."""
    seen: List[str] = []
    for d in _sub_dicts(rec):
        for t in _policy_tokens(d.get("source_policy")):
            if t not in seen:
                seen.append(t)
    return seen


def _truthy(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v == 1
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes", "y", "t")
    if isinstance(v, (list, tuple)):
        return len(v) > 0  # e.g. a list of disallowed URLs
    return False


def is_archive_sourced(rec: Dict[str, Any]) -> bool:
    """Record content came from a web archive (Wayback, Common Crawl, ...) rather than a live fetch."""
    for d in _sub_dicts(rec):
        if any(d.get(k) not in (None, "") for k in ARCHIVE_KEYS):
            return True
    em = _sub_dicts(rec)
    if len(em) > 1 and isinstance(em[1].get("archive"), dict) and em[1]["archive"]:
        return True
    return any(p.startswith("archived_") for p in source_policies(rec))


def hold_reason(rec: Dict[str, Any]) -> Optional[str]:
    """Return why this staged record must be held back from public upload, or None if it may pass."""
    for p in source_policies(rec):
        if p in HOLD_SOURCE_POLICIES:
            return f"source_policy:{p}"
    if not is_archive_sourced(rec):
        for d in _sub_dicts(rec):
            for k in ROBOTS_FLAG_KEYS:
                if _truthy(d.get(k)):
                    return f"{k}=true (live fetch)"
    return None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate_record(rec: Dict[str, Any], *, normalized: bool = False) -> List[str]:
    """Return a list of problems (empty list == valid).

    normalized=False checks a STAGED record (what bots write);
    normalized=True checks a final html-parquet row (all derived columns present).
    """
    errs: List[str] = []
    req = list(REQUIRED_STAGED) + (["cid", "doc_order", "retrieved_at"] if normalized else [])
    for k in req:
        v = rec.get(k)
        if v is None or (isinstance(v, str) and not v.strip()):
            errs.append(f"missing:{k}")
    cc = rec.get("country_code")
    if cc and not _CC_RE.match(str(cc)):
        errs.append(f"bad_country_code:{cc!r}")
    pid = rec.get("place_id")
    if pid and not _PLACE_ID_RE.match(str(pid)):
        errs.append(f"bad_place_id:{pid!r} (want gnis:N | wd:QN | iso:CC | iso:CC-SUB | KG-kg_cbd:<organ id>)")
    if pid and str(pid).startswith(KG_CBD_PREFIX) and cc and cc != "KG":
        errs.append(f"kg_cbd_place_id_non_kg:{pid}/{cc}")
    if pid and cc and str(pid).startswith("iso:") and not str(pid)[4:].startswith(str(cc)):
        errs.append(f"place_id_country_mismatch:{pid}/{cc}")
    if pid and str(pid).startswith("gnis:") and cc and cc != "US":
        errs.append("gnis_place_id_non_us")
    g = rec.get("gnis")
    if g not in (None, "") and not re.match(r"^\d+$", str(g)):
        errs.append(f"bad_gnis:{g!r}")
    dt = rec.get("doc_type")
    if dt and dt not in DOC_TYPES:
        errs.append(f"bad_doc_type:{dt!r}")
    cf = rec.get("content_format")
    if cf and cf not in CONTENT_FORMATS:
        errs.append(f"bad_content_format:{cf!r}")
    lang = rec.get("language")
    if lang and not _LANG_RE.match(str(lang)):
        errs.append(f"bad_language:{lang!r} (BCP-47, lowercase primary tag)")
    for k in ("adopted_date", "published_date", "effective_date"):
        v = rec.get(k)
        if v not in (None, "") and not _DATE_RE.match(str(v)):
            errs.append(f"bad_date:{k}={v!r}")
    ra = rec.get("retrieved_at")
    if ra not in (None, "") and not _TS_RE.match(str(ra)):
        errs.append(f"bad_retrieved_at:{ra!r}")
    if rec.get("in_force") not in (None, True, False):
        errs.append("bad_in_force (bool|null)")
    if rec.get("consolidated") not in (None, True, False):
        errs.append("bad_consolidated (bool)")
    su = rec.get("source_url")
    if su and not str(su).startswith(("http://", "https://")):
        errs.append("bad_source_url")
    did = rec.get("doc_id")
    if did is not None and not isinstance(did, (str, int)):
        errs.append("bad_doc_id_type")
    for k in PROVENANCE_BOOL:
        if rec.get(k) not in (None, True, False) and normalized:
            errs.append(f"bad_{k} (bool|null)")
    metadata_only = rec.get("content_complete") is False or (
        isinstance(rec.get("content_complete"), str) and rec["content_complete"].strip().lower() == "false")
    if not metadata_only and not any((rec.get(k) or "").strip() if isinstance(rec.get(k), str) else rec.get(k)
                                     for k in ("html", "text")):
        errs.append("empty_content (need html or text, or content_complete=false)")
    if not any(isinstance(rec.get(k), str) and rec.get(k).strip()
               for k in ("html_title", "title_native", "number")):
        errs.append("no_title (need html_title, title_native or number)")
    if normalized:
        do = rec.get("doc_order")
        if not isinstance(do, int) or do < 0 or do > 2**32 - 1:
            errs.append("bad_doc_order")
        try:
            pk = place_key(rec.get("place_id"), rec.get("gnis"), rec.get("country_code"))
            if rec.get("cid") != html_cid(pk, str(rec.get("doc_id"))):
                errs.append("cid_mismatch")
        except ValueError as e:
            errs.append(str(e))
    return errs


def iter_staged_records(path: Path) -> Iterator[Tuple[int, Any]]:
    """Yield (line_no/row_idx, record-or-error-string) from a .jsonl or .parquet file."""
    path = Path(path)
    if path.suffix == ".jsonl":
        with path.open("r", encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as e:
                    yield i, f"json_error:{e}"
                    continue
                yield i, obj if isinstance(obj, dict) else "not_an_object"
    elif path.suffix == ".parquet":
        import pyarrow.parquet as pq
        i = 0
        for batch in pq.ParquetFile(str(path)).iter_batches(batch_size=64):  # streaming, not to_pylist()
            for rec in batch.to_pylist():
                i += 1
                yield i, rec
    else:
        raise ValueError(f"unsupported staged file type: {path}")


def validate_file(path, *, normalized: Optional[bool] = None, expect_place_key: Optional[str] = None
                  ) -> Dict[str, Any]:
    """Validate a staged .jsonl/.parquet or a final *_html.parquet.

    Returns {"ok", "rows", "bad_rows", "errors": [(row, [reasons])...], "place_ids"}.
    Final parquets (name ends _html.parquet) also get a column/type check.
    """
    path = Path(path)
    if normalized is None:
        normalized = path.name.endswith("_html.parquet")
    out: Dict[str, Any] = {"path": str(path), "rows": 0, "bad_rows": 0, "errors": [],
                           "place_ids": set(), "file_errors": []}
    if normalized and path.suffix == ".parquet":
        import pyarrow.parquet as pq
        got = pq.read_schema(str(path))
        want = html_schema()
        if got.names != want.names:
            out["file_errors"].append(f"columns {got.names} != {want.names}")
        else:
            for f in want:
                if not got.field(f.name).type.equals(f.type):
                    out["file_errors"].append(f"type {f.name}: {got.field(f.name).type} != {f.type}")
    seen = set()
    for i, rec in iter_staged_records(path):
        out["rows"] += 1
        if isinstance(rec, str):
            errs = [rec]
        else:
            errs = validate_record(rec, normalized=normalized)
            out["place_ids"].add(rec.get("place_id"))
            key = (rec.get("place_id"), str(rec.get("doc_id")))
            if normalized and key in seen:
                errs.append("duplicate_doc_id")
            seen.add(key)
            if expect_place_key and not errs:
                try:
                    if place_key(rec.get("place_id"), rec.get("gnis"), rec.get("country_code")) != expect_place_key:
                        errs.append(f"place_key_mismatch_with_filename:{expect_place_key}")
                except ValueError:
                    pass
        if errs:
            out["bad_rows"] += 1
            if len(out["errors"]) < 200:
                out["errors"].append((i, errs))
    out["place_ids"] = sorted(p for p in out["place_ids"] if p)
    out["ok"] = out["bad_rows"] == 0 and not out["file_errors"] and out["rows"] > 0
    return out


# ---------------------------------------------------------------------------
# Tiny example (python schema.py)
# ---------------------------------------------------------------------------
EXAMPLE_RECORD = {
    "place_id": "wd:Q727", "country_code": "NL", "doc_id": "CVDR123456_1",
    "source_platform": "nl_cvdr", "source_url": "https://lokaleregelgeving.overheid.nl/CVDR123456/1",
    "doc_type": "regulation", "language": "nl", "title_native": "Algemene plaatselijke verordening Amsterdam",
    "number": "CVDR123456", "adopted_date": "2024-01-25", "published_date": "2024-02-01",
    "effective_date": "2024-02-02", "in_force": True, "consolidated": True,
    "content_format": "xml", "html": "<div class=\"chunk-content\"><p>Artikel 1 ...</p></div>",
    "retrieved_at": "2026-10-10T22:00:00Z",
    # optional place-level fields (go to metadata JSON, not the parquet):
    "place_name": "Amsterdam", "qid": "Q727", "iso_3166_2": "NL-NH", "admin_level": "municipality",
    "platform": "nl_cvdr", "platform_place_id": "gm0363",
}

if __name__ == "__main__":
    r = dict(EXAMPLE_RECORD)
    pk = place_key(r["place_id"])
    print("place_key", pk, "cid", html_cid(pk, r["doc_id"]))
    print("errors", validate_record(r))
    print("US example 1008538 / doc 'x':", place_key("gnis:1008538"), html_cid(place_key("gnis:1008538"), "x"))
    print("national FR:", place_key(national_place_id("FR")), " subnational US-CA:", place_key(subnational_place_id("US-CA")))
    print("html columns:", len(HTML_COLUMNS), HTML_COLUMNS)
