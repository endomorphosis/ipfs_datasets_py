"""Hungary: NJT Önkormányzati Rendelettár (or.njt.hu) local decrees from the Wayback Machine — target `hu` of
`archive_q2.py run` (2026-10-18, CEE pass). Tag `hunjt`.

Live or.njt.hu / njt.hu reset TLS from the box (network_blocked since 2026-10-12), so archive only (shared
ArchiveFetcher, ARCHIVE_LANE=eu). Recheck 2026-10-18: archived /eli/v01/<issuer>/r/<year>/<no>[/<yyyy-mm-dd>] pages
are server-rendered and carry the FULL consolidated decree text (e.g. 735782/r/2023/5 @ 20250807103044: 27 §§).
The NJT footer reserves rights ("minden jogot fenntart", MKIFK) for its texts; the decrees themselves are
jogszabályok (Jat. 2. §) and excluded from copyright (Szjt. 1. § (4)) — recorded in `rights`.

Discovery: paged Wayback CDX (zipnum pages, pageSize=1, resumable per page) over `or.njt.hu/eli/v01/`; the plain
collapsed prefix query times out server-side. Robots: newest archived or.njt.hu robots.txt via AJ.robots_for;
disallowed URLs are kept only as `source_policy=archived_robots_disallowed`.
Places: issuer heading -> toponym -> unique folded name among HU candidate rows (municipality; counties via
"<X> Vármegye/Megye"); Budapest districts and unknown names -> _unmatched with issuer + NJT issuer id.
    python3 hu_njt.py discover | status
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import csv, json, os, re, sys, time
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
sys.path.insert(0, str(HERE))
os.environ.setdefault("ARCHIVE_LANE", "eu")
import archive_jobs as AJ  # noqa: E402
from archive import provenance_fields  # noqa: E402
from archive.core import WB_CDX, Capture  # noqa: E402

log = AJ.log
STATE = AJ.STAGE / "_state" / "archive" / "hu"
CAND = Path((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + "/global_municipalities_candidate.csv"))
UA_TOKEN = "world-municipal-law-research/1.0"
URLRX = re.compile(r"^https?://or\.njt\.hu(?::\d+)?/eli/v01/(\d+)/r/(\d{4})/(\d+)(?:/(\d{4}-\d{2}-\d{2}))?/?$")
PREFIX = "or.njt.hu/eli/v01/"


def _cdx(fx, extra):
    base = [("url", PREFIX), ("matchType", "prefix")]
    if not any(k == "showNumPages" for k, _ in extra):   # showNumPages answers a bare integer only without output/fl
        base += [("output", "json"), ("fl", "timestamp,original,mimetype,statuscode,digest,length"),
                 ("filter", "statuscode:200")]
    q = "&".join(f"{k}={quote(v, safe=':/*,!')}" for k, v in base + extra)
    # round 3: raw _get -> typed errors normalised to ArchiveDeferred (not_before) by AJ.as_deferral; non-200 / bad JSON
    # are errors (never written as a page), so discover() never records a partial or garbage CDX page
    from archive import ratelimit
    from archive.core import ArchiveBreakerOpen, ArchiveError, ArchiveTransient
    url = f"{WB_CDX}?{q}"
    scope = getattr(fx, "_call_scope", None)
    try:
        if not ratelimit.wayback_available():
            raise ArchiveBreakerOpen("wayback breaker open (box-wide); skipped")
        if scope is not None:
            with scope():
                r = fx._get("wayback", url, ok_status=(200,))   # shared fetcher: box-wide limiter + breaker
        else:
            r = fx._get("wayback", url, ok_status=(200,))
        if r.status_code != 200:
            raise ArchiveError(f"hu cdx {r.status_code}", status=r.status_code)
        if "showNumPages" not in q:
            try:
                json.loads(r.text) if r.text.strip() else []
            except ValueError:
                raise ArchiveTransient("hu cdx non-json", kind="bad_response")
    except ArchiveError as e:
        d = AJ.as_deferral(fx, e, "wayback", url)
        raise (d if d is not None else e)
    return r.text


def discover(fx, max_pages=None):
    """Resumable: _state/archive/hu/cdx_pages/<n>.json per page; candidates.jsonl rebuilt from all pages."""
    pdir = STATE / "cdx_pages"
    pdir.mkdir(parents=True, exist_ok=True)
    npf = STATE / "num_pages2.txt"     # num_pages.txt (first try) holds a JSON answer, kept as is
    if not npf.exists():
        npf.write_text(_cdx(fx, [("showNumPages", "true"), ("pageSize", "1")]).strip())
    n = int(npf.read_text().strip() or 0)
    got = 0
    for p in range(n):
        f = pdir / f"{p:05d}.json"
        if f.exists():
            continue
        if max_pages is not None and got >= max_pages:
            break
        txt = _cdx(fx, [("pageSize", "1"), ("page", str(p))])
        rows = json.loads(txt) if txt.strip() else []
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps([r for r in rows if r and r[0] != "timestamp"]))
        tmp.replace(f)
        got += 1
        log.info("hu cdx page %d/%d: %d rows", p + 1, n, len(rows))
    return build(n)


def build(n=None):
    acts = defaultdict(list)
    pages = sorted((STATE / "cdx_pages").glob("*.json"))
    for f in pages:
        for ts, orig, mime, st, dg, ln in (r[:6] for r in json.loads(f.read_text()) if len(r) >= 6):
            m = URLRX.match(orig.split("?")[0].split("#")[0])
            if m and "html" in (mime or "html"):
                acts[f"{m.group(1)}/r/{m.group(2)}/{m.group(3)}"].append((ts, orig, mime, dg))
    tmp = STATE / ".candidates.tmp"
    with tmp.open("w", encoding="utf-8") as fo:
        for k in sorted(acts):
            caps = sorted(set(acts[k]), reverse=True)[:4]
            fo.write(json.dumps({"key": k, "issuer_id": k.split("/")[0], "caps": caps}) + "\n")
    tmp.replace(STATE / "candidates.jsonl")
    # 2026-10-18 v3: a throttled CDX page raises ArchiveDeferred out of discover() (shared fetcher; no partial page is
    # written); "complete" is True only when every page is on disk - the candidates are a prefix of the listing otherwise.
    info = {"pages_done": len(pages), "pages_total": n, "complete": bool(n) and len(pages) >= n, "acts": len(acts),
            "issuers": len({k.split('/')[0] for k in acts}), "at": AJ.utcnow()}
    (STATE / "discover.json").write_text(json.dumps(info))
    return info


def fold(s):
    import unicodedata
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


SUFFIX = re.compile(r"\b(megyei jogu varos|varmegyei jogu varos|nagykozseg|kozseg|varos|onkormanyzata|onkormanyzat|"
                    r"kepviselo ?testulete|kozgyulese|fovarosi|fovaros|nemzetisegi.*)\b")


class HUPlaces:
    def __init__(self):
        self.by, self.cnty = defaultdict(list), {}
        for r in csv.DictReader(CAND.open(encoding="utf-8")):
            if r["country_code"] != "HU":
                continue
            if r["admin_level"] == "county":
                self.cnty[fold(re.sub(r"\b(County|vármegye|megye)\b", "", r["place_name"], flags=re.I))] = r
            else:
                self.by[fold(r["place_name"])].append(r)

    def resolve(self, issuer):
        f = fold(issuer)
        m = re.match(r"(.+?) (var)?megye(i)?\b", f)
        if m and "jogu" not in f:
            r = self.cnty.get(m.group(1).strip())
            if r:
                return r, "issuer_county->candidate"
        if f.startswith("budapest") and re.search(r"\b[ivxl]+ ?kerulet", f):
            return None, "budapest_district_not_in_candidate"
        if "nemzetisegi" in f:
            return None, "minority_self_government"
        top = re.sub(r"\s+", " ", SUFFIX.sub(" ", f)).strip()
        hits = self.by.get(top, [])
        if len(hits) == 1:
            return hits[0], "issuer_toponym->candidate"
        return None, "ambiguous_name" if hits else "issuer_not_in_candidate"


HDR = re.compile(r"(.+?)\s+(Képviselő-?\s?testületének|Közgyűlésének)\s+(\d+/\d{4})\.?\s*\(([^)]*)\)\s*önkormányzati rendelete",
                 re.S)
RIGHTS = ("önkormányzati rendelet = jogszabály (2010. évi CXXX. tv. 2. §), not protected by copyright (1999. évi LXXVI. tv. "
          "1. § (4)); NJT (MKIFK) reserves rights on its text presentation")


def page_text(b: bytes):
    from bs4 import BeautifulSoup
    s = BeautifulSoup(b, "lxml")
    for x in s(["script", "style", "nav", "header", "footer", "noscript"]):
        x.decompose()
    h1 = s.find("h1")
    h1t = re.sub(r"\s+", " ", h1.get_text(" ")).strip() if h1 else ""
    h2 = s.find("h2")
    h2t = re.sub(r"\s+", " ", h2.get_text(" ")).strip() if h2 else ""
    t = (s.body or s).get_text("\n")
    t = re.sub(r"[ \t\xa0]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n\n", t)
    if h1t:
        i = t.find(h1t.split(" önkormányzati")[0][:60])
        if i > 0:
            t = t[i:]
    for stop in ("Impresszum", "A Nemzeti Jogszabálytár mindenki számára", "A cookie-k segítenek"):
        j = t.find(stop)
        if j > 0:
            t = t[:j]
    return h1t, h2t, t.strip()


def hu_one(fx, cand, pm, rb):
    caps = [Capture("wayback", "wayback", ts, orig, 200, mime, dg) for ts, orig, mime, dg in cand["caps"]]
    pol, basis = "network_blocked", "or.njt.hu TLS reset from the box (2026-10-12, re-checked 2026-10-18)"
    if rb is not None and not rb[0].can_fetch(UA_TOKEN, caps[0].original_url):
        pol = "robots_disallowed"
    d = AJ.fbest(fx, caps, max_tries=2, validator=lambda d: b"rendelet" in d.body and "§".encode() in d.body)
    if not d:
        return None, "no_good_capture"
    h1, h2, text = page_text(d.body)
    m = HDR.search(h1 or text[:800])
    if not m or len(re.findall(r"\d+\. ?§", text)) < 1 or len(text) < 300:
        return None, "no_decree_text"
    issuer = re.sub(r"\s+", " ", m.group(1)).strip()
    row, how = pm.resolve(issuer)
    num, dpart = m.group(3), m.group(4)
    yr = num.split("/")[1]
    adopted = None
    dm = re.match(r"\s*([IVX]+)\.?\s*(\d{1,2})\.?", dpart or "")
    if dm:
        mon = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"]
        if dm.group(1) in mon:
            adopted = f"{yr}-{mon.index(dm.group(1)) + 1:02d}-{int(dm.group(2)):02d}"
    hv = re.search(r"Hatályos:\s*(\d{4})\.\s*(\d{2})\.\s*(\d{2})", text[:1500])
    k = cand["key"]
    src = f"https://or.njt.hu/eli/v01/{k}"
    rec = {
        "place_id": row["place_id"] if row else None, "country_code": "HU", "doc_id": f"hu_njt:{k}",
        "source_platform": "hu_njt_or", "source_url": src, "doc_type": "ordinance", "language": "hu",
        "title_native": (f"{h1} {h2}".strip() or k)[:1000], "number": f"{num}. ({dpart})",
        "adopted_date": adopted, "published_date": None, "effective_date": None, "in_force": None, "consolidated": True,
        "version_date": f"{hv.group(1)}-{hv.group(2)}-{hv.group(3)}" if hv else None,
        "content_format": "html", "text": text, "retrieved_at": AJ.utcnow(),
        "place_name": row["place_name"] if row else issuer, "qid": row["qid"] if row else None,
        "iso_3166_2": (row.get("iso_3166_2") or None) if row else None,
        "admin_level": row["admin_level"] if row else "municipality", "level": "municipality",
        "platform": "njt_onkormanyzati_rendelettar", "platform_place_id": cand["issuer_id"],
        "issuing_body_name": issuer, "place_match": how, "act_kind": "önkormányzati rendelet",
        "rights": RIGHTS, "access_basis": basis, "source_official": True,
    }
    rec.update(provenance_fields(d, source_policy="archived_robots_disallowed", robots_basis=f"archived robots.txt ({rb[1]}) disallows; live: {basis}")
               if pol == "robots_disallowed" else provenance_fields(d))
    if pol != "robots_disallowed":
        rec["extra_metadata"]["archive"]["live_access"] = f"network_blocked: {basis}"
    return rec, "ok"


if __name__ == "__main__":
    AJ.setup_logging("hu")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    STATE.mkdir(parents=True, exist_ok=True)
    if cmd == "discover":
        mp = int(sys.argv[2]) if len(sys.argv) > 2 else None
        print(discover(AJ.new_fx(), max_pages=mp))   # EU Wayback policy (common/eu_wayback.py)
    elif cmd == "build":
        print(build())
    else:
        print((STATE / "discover.json").read_text() if (STATE / "discover.json").exists() else "-",
              "done", len(AJ.load_done(STATE / "done.txt")) if (STATE / "done.txt").exists() else 0)
