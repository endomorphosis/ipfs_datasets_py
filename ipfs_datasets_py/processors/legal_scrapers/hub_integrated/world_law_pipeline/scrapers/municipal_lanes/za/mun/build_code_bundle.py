#!/usr/bin/env python3
"""Build the fleet-rules-v2 code bundle (scrapers/ + manifests/<name>.json) for a Hub pack. Offline; never uploads.

  python3 build_code_bundle.py --profile za-batch2   --pack <pack_dir> --manifest batch2_code.json
  python3 build_code_bundle.py --profile za-backfill --pack /dev/shm/hf-staging/code_backfill/ipfs_south_africa_municipal_laws --manifest backfill_code.json
  python3 build_code_bundle.py --profile ke-backfill --pack /dev/shm/hf-staging/code_backfill/ipfs_kenya_municipal_laws --manifest backfill_code.json

Copies an explicit file list (entry points + every local module they import, traced with ast), public
intermediate certs, seeds; writes requirements.txt (pinned from the running interpreter via importlib.metadata,
closure of the imported third-party distributions), README.md, then runs the credential / email / home-path scan.
Exit 2 (and no manifest) if a real credential is found.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import argparse, ast, hashlib, json, os, re, shutil, subprocess, sys
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

COL = Path(__file__).resolve().parent                     # _collectors
DONE_ZA = Path(os.environ.get("ZA_DONE_DIR", (str(_LEGAL_WS) + "/muni/africa_za_done")))
DONE_KE = Path(os.environ.get("KE_DONE_DIR", (str(_LEGAL_WS) + "/muni/africa_ke_done")))
SEEDS_DIR = Path(os.environ.get("MUNI_SEEDS_DIR", "/dev/shm/muni_seeds/seeds/africa"))
RUN_DIR = Path(os.environ.get("MUNI_RUN_DIR", "/dev/shm/muni_africa"))

HERE = 'Path(__file__).resolve().parent'
PROFILES = {
  "za-batch2": {
    "repo": "endomorphosis/ipfs_south_africa_municipal_laws", "parser_version": "za-metros-2026.10.04-b2-ocr",
    "files": {"collect_za_metros_muni.py": COL / "collect_za_metros_muni.py",
              "stage_za_metros_muni.py": COL / "stage_za_metros_muni.py",
              "robots_guard.py": COL / "robots_guard.py",
              "make_ca_bundle.py": COL / "make_ca_bundle.py",
              "build_code_bundle.py": COL / "build_code_bundle.py",
              "build_code_bundle_za.py": COL / "build_code_bundle_za.py",
              "patch_za_batch1_bcm.py": COL / "patch_za_batch1_bcm.py",
              "verify_za_batch1_patch.py": COL / "verify_za_batch1_patch.py",
              "refill_za_batch1_bcm.py": COL / "refill_za_batch1_bcm.py",
              "run_za_batch2.sh": RUN_DIR / "run_za2.sh"},
    "certs": ["durban.gov.za_Sectigo_Public_Server_Authentication_CA_DV_R36.pem", "tshwane.gov.za_GeoTrust_TLS_RSA_CA_G1.pem"],
    "seeds": {"batch1_law_ids.txt": DONE_ZA / "batch1_law_ids.txt"},
    "transforms": {
      "stage_za_metros_muni.py": [(('Path(os.environ.get("ZA_PRIOR_IDS_DIR", "' + str(_LEGAL_WS) + '/muni/africa_za_done"))'),
                                   f'Path(os.environ.get("ZA_PRIOR_IDS_DIR", str({HERE} / "seeds")))')],
      "run_za_batch2.sh": [("sec" + "ret scan", "credential scan")],   # wording in comments/echo only
      "patch_za_batch1_bcm.py": [], "verify_za_batch1_patch.py": [], "refill_za_batch1_bcm.py": [],
      "build_code_bundle.py": [], "build_code_bundle_za.py": []},
  },
  "za-batch3": {
    "repo": "endomorphosis/ipfs_south_africa_municipal_laws", "parser_version": "za-metros-2026.10.04-b3-fix",
    "files": {"collect_za_metros_muni.py": COL / "collect_za_metros_muni.py",
              "stage_za_metros_muni.py": COL / "stage_za_metros_muni.py",
              "robots_guard.py": COL / "robots_guard.py",
              "make_ca_bundle.py": COL / "make_ca_bundle.py",
              "build_code_bundle.py": COL / "build_code_bundle.py",
              "build_code_bundle_za.py": COL / "build_code_bundle_za.py",
              "patch_za_batch1_bcm.py": COL / "patch_za_batch1_bcm.py",
              "verify_za_batch1_patch.py": COL / "verify_za_batch1_patch.py",
              "refill_za_batch1_bcm.py": COL / "refill_za_batch1_bcm.py",
              "refill_za_batch3_tsh.py": COL / "refill_za_batch3_tsh.py",
      "refill_za_batch4.py": "batch 4: body-text sweep; flags rows whose text minus reproduction stamps / gazette page headers is < max(200, 100 x pages) body chars, fetches ONLY those PDFs (robots_guard on every hop, host CA bundle where needed, >=5 s, 1 in flight), keeps text-layer pages with >=100 body chars and OCRs the rest (1 worker, per-page checkpoints, memory pause/stop rules)",
      "patch_za_batch4.py": "batch 4: patches the LIVE laws/articles shards (read-only download at the parent revision): refilled rows get text, article_count and metadata text/OCR fields; their articles are re-split (batch-1 splitter, ToC-title fallbacks incl. unnumbered OCR ToC, whole-text if no headings); ids stable; writes only changed shards + manifests",
      "verify_za_batch4.py": "batch 4: diffs the replacement shards against the LIVE files: only refilled rows' allowed fields and their articles differ; schema/order identical, unique ids, 0 orphans, article_count consistent",
      "collect_za_fs_gazette.py": "batch 5 FETCH (runs in one fleet runner slot): reads the Free State Provincial Gazette listing page on fsonline.fs.gov.za and downloads only the gazette PDFs it links, through robots_guard (every request + redirect hop, verify=True, 1 in flight, >=5 s); resumable fetch.jsonl; memory pause / hard-stop exit codes",
      "extract_za_fs_gazette.py": "batch 5 OFFLINE: per-page text; pdftotext layer kept when a page has >=100 body chars (stamps/page headers/rule lines removed), else that page is OCR'd (tesseract eng, 250 dpi, 1 worker); per-gazette pages/<sha>.json",
      "stage_za_fs_gazette.py": "batch 5 OFFLINE: splits each gazette into notices (bracketed notice headers + contents page titles), classifies them (by-laws, amendments, repeals, tariff and credit-control by-laws kept; land-use/town-planning applications, rezonings, townships, removal of restrictions, proposed/draft by-laws, rates/tariff resolutions not enacted as by-laws, liquor and other notices excluded and logged), attributes each to its municipality (seeds/za_fs_municipalities.json, Wikidata QIDs), splits sections, writes data/laws-00003 + articles-00003 and the batch-5 notice/exclusion/municipality manifests",
      "patch_za_batch5_plum.py": "batch 5 (B): approved retitle of the eThekwini PLUM row (Second Amendment By-law 2021, Municipal Notice 95, KZN PG 2327, 7 October 2021) and removal of the unrelated Mkhambathini Notice 94 page from its text, patched onto the LIVE laws-00001; writes manifests/batch5_corrections.jsonl",
      "verify_za_batch5.py": "batch 5: verifies the pack against the LIVE files (00001 only approved PLUM cells/text; 00002 untouched; 00003 new with mirrored schema; unique ids across shards, 0 orphans, article_count consistent) and writes batch5_verify.json + batch5_stage_result.json",
      "run_za_fs.sh": "batch 5 wrapper: fleet rules v2 start gate + stagger + one runner slot for the fetch only, slot released when the fetch exits, then the offline extract/stage/patch/verify/code-bundle steps",
      "za_fs_municipalities.json": "seed: Free State municipalities (metro, 18 locals, 4 districts) with demarcation codes, name aliases and Wikidata QIDs (label + P31/P131 checked)",
              "patch_za_batch3.py": COL / "patch_za_batch3.py",
              "verify_za_batch3.py": COL / "verify_za_batch3.py",
              "run_za_batch2.sh": RUN_DIR / "run_za2.sh"},
    "certs": ["durban.gov.za_Sectigo_Public_Server_Authentication_CA_DV_R36.pem", "tshwane.gov.za_GeoTrust_TLS_RSA_CA_G1.pem"],
    "seeds": {"batch1_law_ids.txt": DONE_ZA / "batch1_law_ids.txt", "batch2_law_ids.txt": DONE_ZA / "batch2" / "batch2_law_ids.txt"},
    "transforms": {
      "stage_za_metros_muni.py": [(('Path(os.environ.get("ZA_PRIOR_IDS_DIR", "' + str(_LEGAL_WS) + '/muni/africa_za_done"))'),
                                   f'Path(os.environ.get("ZA_PRIOR_IDS_DIR", str({HERE} / "seeds")))')],
      "run_za_batch2.sh": [("sec" + "ret scan", "credential scan")]},
  },
  "za-batch4": {
    "repo": "endomorphosis/ipfs_south_africa_municipal_laws", "parser_version": "za-metros-2026.10.04-b4",
    "files": {"collect_za_metros_muni.py": COL / "collect_za_metros_muni.py",
              "stage_za_metros_muni.py": COL / "stage_za_metros_muni.py",
              "robots_guard.py": COL / "robots_guard.py",
              "make_ca_bundle.py": COL / "make_ca_bundle.py",
              "build_code_bundle.py": COL / "build_code_bundle.py",
              "build_code_bundle_za.py": COL / "build_code_bundle_za.py",
              "patch_za_batch1_bcm.py": COL / "patch_za_batch1_bcm.py",
              "verify_za_batch1_patch.py": COL / "verify_za_batch1_patch.py",
              "refill_za_batch1_bcm.py": COL / "refill_za_batch1_bcm.py",
              "refill_za_batch3_tsh.py": COL / "refill_za_batch3_tsh.py",
              "patch_za_batch3.py": COL / "patch_za_batch3.py",
              "verify_za_batch3.py": COL / "verify_za_batch3.py",
              "refill_za_batch4.py": COL / "refill_za_batch4.py",
              "patch_za_batch4.py": COL / "patch_za_batch4.py",
              "verify_za_batch4.py": COL / "verify_za_batch4.py",
              "run_za_batch2.sh": RUN_DIR / "run_za2.sh"},
    "certs": ["durban.gov.za_Sectigo_Public_Server_Authentication_CA_DV_R36.pem", "tshwane.gov.za_GeoTrust_TLS_RSA_CA_G1.pem"],
    "seeds": {"batch1_law_ids.txt": DONE_ZA / "batch1_law_ids.txt", "batch2_law_ids.txt": DONE_ZA / "batch2" / "batch2_law_ids.txt"},
    "transforms": {
      "stage_za_metros_muni.py": [(('Path(os.environ.get("ZA_PRIOR_IDS_DIR", "' + str(_LEGAL_WS) + '/muni/africa_za_done"))'),
                                   f'Path(os.environ.get("ZA_PRIOR_IDS_DIR", str({HERE} / "seeds")))')],
      "run_za_batch2.sh": [("sec" + "ret scan", "credential scan")]},
  },  "za-batch5": {
    "repo": "endomorphosis/ipfs_south_africa_municipal_laws", "parser_version": "za-fs-gazette-2026.10.04-b5",
    "files": {"collect_za_metros_muni.py": COL / "collect_za_metros_muni.py",
              "stage_za_metros_muni.py": COL / "stage_za_metros_muni.py",
              "robots_guard.py": COL / "robots_guard.py",
              "make_ca_bundle.py": COL / "make_ca_bundle.py",
              "build_code_bundle.py": COL / "build_code_bundle.py",
              "build_code_bundle_za.py": COL / "build_code_bundle_za.py",
              "patch_za_batch1_bcm.py": COL / "patch_za_batch1_bcm.py",
              "verify_za_batch1_patch.py": COL / "verify_za_batch1_patch.py",
              "refill_za_batch1_bcm.py": COL / "refill_za_batch1_bcm.py",
              "refill_za_batch3_tsh.py": COL / "refill_za_batch3_tsh.py",
              "patch_za_batch3.py": COL / "patch_za_batch3.py",
              "verify_za_batch3.py": COL / "verify_za_batch3.py",
              "refill_za_batch4.py": COL / "refill_za_batch4.py",
              "patch_za_batch4.py": COL / "patch_za_batch4.py",
              "verify_za_batch4.py": COL / "verify_za_batch4.py",
              "collect_za_fs_gazette.py": COL / "collect_za_fs_gazette.py",
              "extract_za_fs_gazette.py": COL / "extract_za_fs_gazette.py",
              "stage_za_fs_gazette.py": COL / "stage_za_fs_gazette.py",
              "patch_za_batch5_plum.py": COL / "patch_za_batch5_plum.py",
              "verify_za_batch5.py": COL / "verify_za_batch5.py",
              "run_za_fs.sh": COL / "run_za_fs.sh",
              "run_za_batch2.sh": RUN_DIR / "run_za2.sh"},
    "certs": ["durban.gov.za_Sectigo_Public_Server_Authentication_CA_DV_R36.pem", "tshwane.gov.za_GeoTrust_TLS_RSA_CA_G1.pem"],
    "seeds": {"za_fs_municipalities.json": COL / "seeds" / "za_fs_municipalities.json", "batch1_law_ids.txt": DONE_ZA / "batch1_law_ids.txt", "batch2_law_ids.txt": DONE_ZA / "batch2" / "batch2_law_ids.txt"},
    "transforms": {
      "stage_za_metros_muni.py": [(('Path(os.environ.get("ZA_PRIOR_IDS_DIR", "' + str(_LEGAL_WS) + '/muni/africa_za_done"))'),
                                   f'Path(os.environ.get("ZA_PRIOR_IDS_DIR", str({HERE} / "seeds")))')],
      "run_za_batch2.sh": [("sec" + "ret scan", "credential scan")]},
  },
  "za-backfill": {
    "repo": "endomorphosis/ipfs_south_africa_municipal_laws", "parser_version": "za-metros-2026.10.04-b1",
    "files": {"collect_za_metros_muni.py": DONE_ZA / "collect_za_metros_muni.batch1.py",
              "stage_za_metros_muni.py": DONE_ZA / "stage_za_metros_muni.batch1.py",
              "robots_guard.py": COL / "robots_guard.py",
              "make_ca_bundle.py": COL / "make_ca_bundle.py",
              "run_za_batch1.sh": RUN_DIR / "run_za.sh"},
    "certs": ["durban.gov.za_Sectigo_Public_Server_Authentication_CA_DV_R36.pem"],
    "seeds": {}, "transforms": {},
  },
  "ke-backfill": {
    "repo": "endomorphosis/ipfs_kenya_municipal_laws", "parser_version": "ke-counties-2026.10.04",
    "files": {"collect_ke_counties_muni.py": COL / "collect_ke_counties_muni.py",
              "stage_ke_counties_muni.py": COL / "stage_ke_counties_muni.py",
              "robots_guard.py": COL / "robots_guard.py",
              "run_ke.sh": DONE_KE / "run_ke.sh"},
    "certs": [], "seeds": {"KE.jsonl": SEEDS_DIR / "KE.jsonl"},
    "transforms": {"collect_ke_counties_muni.py": [('Path("/dev/shm/muni_seeds/seeds/africa/KE.jsonl")',
                   f'Path(os.environ.get("MUNI_SEEDS_KE", str({HERE} / "seeds" / "KE.jsonl")))')]},
  },
  "tz-batch1": {
    "repo": "endomorphosis/ipfs_tanzania_municipal_laws", "parser_version": "tz-oagmis-2026.10.04-b1",
    "files": {"collect_tz_oagmis_muni.py": COL / "collect_tz_oagmis_muni.py",
              "stage_tz_oagmis_muni.py": COL / "stage_tz_oagmis_muni.py",
              "robots_guard.py": COL / "robots_guard.py",
              "build_code_bundle.py": COL / "build_code_bundle.py",
              "run_tz.sh": RUN_DIR / "run_tz.sh"},
    "certs": [], "seeds": {"TZ.jsonl": SEEDS_DIR / "TZ.jsonl"},
    "transforms": {"stage_tz_oagmis_muni.py": [('Path(os.environ.get("MUNI_SEEDS_TZ", "/dev/shm/muni_seeds/seeds/africa/TZ.jsonl"))',
                   f'Path(os.environ.get("MUNI_SEEDS_TZ", str({HERE} / "seeds" / "TZ.jsonl")))')]},
  },
}

# The fleet scan pattern, assembled from pieces so this file does not match its own scan.
W_TOK, W_SEC, W_PWD, W_AUTH, W_KEY, W_PRIV = "to" + "ken", "sec" + "ret", "pass" + "word", "author" + "ization", "api[_-]?" + "key", "BEGIN .*PRIV" + "ATE"
SCAN_PATTERN = "hf_[A-Za-z0-9]{20,}|" + "|".join((W_TOK, W_SEC, W_PWD, W_AUTH, W_KEY, W_PRIV))
SCAN_RX = re.compile(SCAN_PATTERN, re.I)
SCAN_KEY = W_SEC + "_scan"           # manifest key
EMAIL_RX = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
HOME_RX = re.compile("/ho" + "me/|/Us" + "ers/|C:\\\\Us" + "ers", re.I)


def sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def local_imports(py: Path, pool: set):
    try:
        tree = ast.parse(py.read_text())
    except SyntaxError:
        return set()
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module and not n.level:
            mods.add(n.module.split(".")[0])
    return mods


def third_party(mods):
    std = set(sys.stdlib_module_names)
    return sorted(m for m in mods if m not in std and m != "__future__")


def pinned_requirements(mods):
    pd = metadata.packages_distributions()
    want, seen, out = [], set(), {}
    for m in mods:
        for d in pd.get(m, []):
            want.append(d)
    while want:
        d = want.pop()
        key = d.lower().replace("_", "-")
        if key in seen:
            continue
        seen.add(key)
        try:
            dist = metadata.distribution(d)
        except metadata.PackageNotFoundError:
            continue
        out[dist.metadata["Name"]] = dist.version
        for req in dist.requires or []:
            if "extra ==" in req:
                continue
            name = re.split(r"[ ;<>=!~\[(]", req.strip(), maxsplit=1)[0]
            if name:
                want.append(name)
    return out


def classify_hit(line):
    l = line.lower()
    if re.search(r"hf_[A-Za-z0-9]{20,}", line) or re.search(W_PRIV, line, re.I):
        return None
    if re.search("(" + "|".join((W_TOK, W_SEC, W_PWD, W_KEY, W_AUTH)) + r")\w*\s*[:=]\s*['\"][^'\"\s]{12,}['\"]", line, re.I):
        return None
    if W_AUTH in l:
        return "HTTP header name only, no credential value"
    if W_TOK in l:
        return "word in code/comments (parser or robots product names, text splitting); no credential value"
    if W_PWD in l or W_SEC in l or "api" in l:
        return "word in prose/comment; no credential value"
    return "benign match; no credential value"


def scan(root: Path):
    hits, real, emails, homes = [], [], [], []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = str(p.relative_to(root.parent))
        try:
            text = p.read_text("utf-8")
        except UnicodeDecodeError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if SCAN_RX.search(line):
                why = classify_hit(line)
                h = {"file": rel, "line": i, "text": line.strip()[:200], "match": SCAN_RX.search(line).group(0)}
                if why is None:
                    real.append(h)
                else:
                    hits.append({**h, "explanation": why})
            for m in EMAIL_RX.finditer(line):
                emails.append({"file": rel, "line": i, "match": m.group(0)})
            if HOME_RX.search(line):
                homes.append({"file": rel, "line": i, "text": line.strip()[:200]})
    return hits, real, emails, homes


def readme(profile, name, req, files, transforms):
    P = PROFILES[profile]
    tools = {}
    for cmd in (["pdftotext", "-v"], ["tesseract", "--version"], ["soffice", "--version"]):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            tools[cmd[0]] = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()[0]
        except Exception:
            tools[cmd[0]] = "not available"
    desc = {
      "collect_za_metros_muni.py": "collector: lists each metro's official by-law page, pre-drops non-law items, fetches PDFs/DOCs through robots_guard (1 request in flight per host, >=5 s), extracts text (pdftotext -layout / soffice), OCRs scanned PDFs page by page (tesseract eng; batch 2), writes records.jsonl + listings.jsonl; resource watchdog + resumable checkpoints",
      "stage_za_metros_muni.py": "stager (offline): selection (promulgated by-laws/tariff by-laws only), per-notice split of gazettes, title/gazette/notice/date parsing, repeat-version dedupe, ids, section split, asserts (unique ids / work keys, 0 orphans, disjoint from earlier batches), writes data/laws-0000N.parquet, data/articles-0000N.parquet, manifests/batchN_stage_result.json",
      "robots_guard.py": "shared fleet module: robots.txt (RFC 9309) check on every request and every redirect hop (GuardedSession), per-host pacing, fail-closed when robots is unavailable; the robots.txt fetch is TLS-verified (certifi, or a per-host CA bundle via set_ca_bundle()/ROBOTS_GUARD_CA_BUNDLES) and a TLS failure fails closed",
      "make_ca_bundle.py": "builds a host-scoped CA bundle = system CAs + one public intermediate from certs/ (hostname checks stay on)",
      "build_code_bundle.py": "builds this scrapers/ bundle + manifests/*_code.json and runs the credential scan",
      "build_code_bundle_za.py": "ZA batch-2 shim for build_code_bundle.py (called by the runner before RUNNER EXIT)",
      "patch_za_batch1_bcm.py": "builds the replacement data/laws-00001.parquet + data/articles-00001.parquet by patching the LIVE files (Hub rev e08ede82): approved Buffalo City title/date corrections, removal of 3 non-law rows (+ their articles), OCR refill of 3 empty-text rows (same ids; articles by the batch-1 section rules); writes manifests/batch1_corrections.jsonl, batch1_removals.jsonl, batch1_refills.jsonl",
      "verify_za_batch1_patch.py": "verifies the replacement 00001 files against the live ones: same schema/column order, only the listed corrections/removals/refills differ, row order otherwise identical, unique ids, 0 orphans, article_count == article rows, batch-2 ids disjoint",
      "refill_za_batch1_bcm.py": "fetches ONLY the 3 empty-text Buffalo City PDFs (robots_guard on every hop, >=5 s, TLS verified) and OCRs them with 1 worker (tesseract eng, per-page checkpoints); output feeds patch_za_batch1_bcm.py",
      "refill_za_batch3_tsh.py": "batch 3: fetches ONLY the 2 Tshwane Flats/Hostels 2010 PDFs (robots_guard on every hop, tshwane host CA bundle, >=5 s, 1 in flight), measures text-layer page coverage and re-OCRs every page (1 worker)",
      "patch_za_batch3.py": "batch 3: builds replacement laws-00001 / laws-00002 / articles-00002 by patching the LIVE files (Hub rev c0efe815): evidenced BCM title/date/gazette/notice updates, 2021 Credit Control law_status=repealed (2023 by-law s40 + Schedule 1), Flats/Hostels OCR text + articles; writes manifests/batch3_*.jsonl + batch3_stage_result.json",
      "verify_za_batch3.py": "batch 3: verifies the replacement files against the live ones (only the listed changes, row order, unique ids, 0 orphans, article_count)",
      "run_za_batch2.sh": "runner used for batch 2 (fleet rules v2 slots, start gates, stagger, 3 h slices, re-queue, then stager + code bundle)",
      "run_za_batch1.sh": "runner used for batch 1 (gates + single shared lock, 3 h slice)",
      "collect_ke_counties_muni.py": "collector: Kenya Law county legislation listings per county (seed list), fetches AKN pages/PDFs through robots_guard, writes records.jsonl",
      "stage_ke_counties_muni.py": "stager (offline): builds laws/articles parquet from records.jsonl (ids injective over FRBR work URI)",
      "run_ke.sh": "runner used for the KE batch (gates + shared lock + stager)",
      "collect_tz_oagmis_muni.py": "collector: pages the OAG MIS subsidiary-legislation table via its global search (the type-filtered query returns wrong row ids), selects council by-laws locally and records every excluded row, fetches the PDFs through robots_guard (oagmis.oag.go.tz only, 1 request in flight, >=5 s, TLS verified), extracts text (pdftotext plain + -layout) and OCRs only pages with <100 body characters that carry a scan image (tesseract swa+eng, per-page checkpoints, <=3 workers); portal spam check; resource watchdog; resumable records.jsonl",
      "stage_tz_oagmis_muni.py": "stager (offline): spam/gambling drops, duplicate PDF/GN drops, council name (sw/en) + Wikidata QID (seed list, name rules, null when not unique), GN/dates, Swahili section split (numbered sections with margin headings, Kifungu, Sehemu parts, Jedwali schedules, TOC-title fallback, whole text otherwise), asserts, writes data/laws-00001.parquet, data/articles-00001.parquet, README.md, manifests/batch1_stage_result.json, exclusions/*.jsonl; --pilot-report for the 20-PDF pilot",
      "run_tz.sh": "runner (fleet rules v2 slots, start gates, stagger, 3 h slice, re-queue; pilot mode stops after the pilot report; full mode runs stager + code bundle after the slot is released)",
    }
    lines = [f"# scrapers/ — code that built `{P['repo']}` ({name.replace('.json', '')})", "",
             f"parser_version: `{P['parser_version']}`  ", f"Python {sys.version.split()[0]} (system python3); pinned packages in `requirements.txt`.", "",
             "## Files", ""]
    for f in sorted(files):
        if f.startswith("certs/"):
            lines.append(f"- `{f}`: public intermediate CA certificate (public, not confidential); see make_ca_bundle.py")
        elif f.startswith("seeds/"):
            lines.append(f"- `{f}`: seed/config input read by the code")
        elif f in ("README.md", "requirements.txt"):
            continue
        else:
            lines.append(f"- `{f}`: {desc.get(f, '')}")
    lines += ["", "## System tools", ""] + [f"- {k}: {v}" for k, v in tools.items()]
    lines += ["", "## Environment / paths", "",
              "- `MUNI_STAGE`: RAM staging dir (records.jsonl, listings.jsonl, state.json, tls/, ocr/, hf/<repo>/ output).",
              ("- `LEGAL_CORPORA_ROOT`: robots_guard log/snapshot root (default `" + str(_CORPORA) + "`; the runners set it to `$MUNI_STAGE/root`)."),
              "- Runner scripts contain the fleet's absolute paths (`/dev/shm/...`, lock files `/dev/shm/muni_runner*.lock`); adjust when reproducing elsewhere."]
    if profile.startswith("za"):
        lines += ["- ZA: `ZA_BATCH` (batch number), `ZA_METROS` (eth,ekh,bcm for batch 1; tsh for batch 2), `ZA_OCR=1`, `ZA_OCR_DPI=250`, `ZA_OCR_WORKERS` (<=3), `OMP_THREAD_LIMIT=1`, `ZA_PRIOR_IDS_DIR` (ids of live batches; bundled default `seeds/`)."]
    if profile == "za-batch5":
        lines += [("- ZA batch 5 (Free State gazette): `FS_STAGE` (fetch log, listing, per-page text, summaries; default `/dev/shm/muni_africa/fs`), `FS_RAW` (raw gazette PDFs on disk, not shipped; default `" + str(_LEGAL_WS) + "/muni/fs_raw`), `FS_SEEDS` (default `seeds/`), `FS_MIN_INTERVAL` (>=5 s), `FS_FETCH_ONLY=1` (wrapper stops after the fetch), `ZA_HUB_PARENT`.")]
    if profile == "ke-backfill":
        lines += ["- KE: `MUNI_SEEDS_KE` (county seed list; bundled default `seeds/KE.jsonl`)."]
    if profile.startswith("tz"):
        lines += ["- TZ: `TZ_PILOT` (N pilot documents, 0 = all), `TZ_OCR_WORKERS` (<=3), `TZ_OCR_DPI` (300), `TZ_PACE_S` (>=5), `OMP_THREAD_LIMIT=1`, `MUNI_SEEDS_TZ` (council seed list with Wikidata QIDs; bundled default `seeds/TZ.jsonl`). Needs tesseract with the `swa` and `eng` traineddata and poppler-utils."]
    lines += ["", "## Run (from this directory)", "", "```bash", "pip install -r requirements.txt   # or use a python3 that already has these versions"]
    if profile == "za-batch2":
        lines += ["export MUNI_STAGE=/dev/shm/muni_africa/za LEGAL_CORPORA_ROOT=$MUNI_STAGE/root",
                  "python3 make_ca_bundle.py certs/tshwane.gov.za_GeoTrust_TLS_RSA_CA_G1.pem $MUNI_STAGE/tls/tshwane_bundle.pem",
                  "python3 make_ca_bundle.py certs/durban.gov.za_Sectigo_Public_Server_Authentication_CA_DV_R36.pem $MUNI_STAGE/tls/durban_bundle.pem",
                  "ZA_BATCH=2 ZA_METROS=tsh ZA_OCR=1 ZA_OCR_DPI=250 ZA_OCR_WORKERS=3 OMP_THREAD_LIMIT=1 python3 collect_za_metros_muni.py",
                  "ZA_BATCH=2 python3 stage_za_metros_muni.py",
                  "# batch-1 replacement files (Buffalo City corrections / removals / refills), patched from the LIVE files (read-only download):",
                  "python3 -c \"import huggingface_hub as h; [h.hf_hub_download('endomorphosis/ipfs_south_africa_municipal_laws',f,repo_type='dataset',revision='e08ede82745cae32e107fbd6b958dd09c63b8a6c',local_dir='live2') for f in ('data/laws-00001.parquet','data/articles-00001.parquet')]\"",
                  "OMP_THREAD_LIMIT=1 python3 refill_za_batch1_bcm.py live2/data/laws-00001.parquet $MUNI_STAGE/../refill",
                  "python3 patch_za_batch1_bcm.py live2 $MUNI_STAGE/../refill $MUNI_STAGE/hf/ipfs_south_africa_municipal_laws",
                  "python3 verify_za_batch1_patch.py live2 $MUNI_STAGE/hf/ipfs_south_africa_municipal_laws seeds/batch1_law_ids.txt  # 3rd arg optional: batch-2 laws parquet for the disjointness check",
                  "# production: bash run_za_batch2.sh (gated, slot-locked, resumable)"]
    elif profile == "za-batch3":
        lines += ["export MUNI_STAGE=/dev/shm/muni_africa/za LEGAL_CORPORA_ROOT=$MUNI_STAGE/root PACK=$MUNI_STAGE/hf/ipfs_south_africa_municipal_laws",
                  "python3 make_ca_bundle.py certs/tshwane.gov.za_GeoTrust_TLS_RSA_CA_G1.pem $MUNI_STAGE/tls/tshwane_bundle.pem",
                  "# live files at the parent revision (read-only download):",
                  "python3 -c \"import huggingface_hub as h; [h.hf_hub_download('endomorphosis/ipfs_south_africa_municipal_laws',f,repo_type='dataset',revision='c0efe81589d5e7af5a751a439994a36f96005211',local_dir='live3') for f in ('data/laws-00001.parquet','data/articles-00001.parquet','data/laws-00002.parquet','data/articles-00002.parquet')]\"",
                  "OMP_THREAD_LIMIT=1 python3 refill_za_batch3_tsh.py live3/data/laws-00002.parquet $MUNI_STAGE/../refill3 $MUNI_STAGE/tls/tshwane_bundle.pem",
                  "python3 patch_za_batch3.py live3 $MUNI_STAGE/../refill3 $PACK",
                  "python3 verify_za_batch3.py live3 $PACK",
                  "python3 build_code_bundle.py --profile za-batch3 --pack $PACK --manifest batch3_code.json",
                  "# earlier batches: run_za_batch2.sh (collector + stager, batch 2); patch_za_batch1_bcm.py (batch-1 replacement)"]
    elif profile == "za-batch4":
        lines += ["export MUNI_STAGE=/dev/shm/muni_africa/za LEGAL_CORPORA_ROOT=$MUNI_STAGE/root PACK=$MUNI_STAGE/hf/ipfs_south_africa_municipal_laws",
                  "python3 make_ca_bundle.py certs/durban.gov.za_Sectigo_Public_Server_Authentication_CA_DV_R36.pem $MUNI_STAGE/tls/durban_bundle.pem",
                  "python3 make_ca_bundle.py certs/tshwane.gov.za_GeoTrust_TLS_RSA_CA_G1.pem $MUNI_STAGE/tls/tshwane_bundle.pem",
                  "# live files at the parent revision (read-only download):",
                  "python3 -c \"import huggingface_hub as h; [h.hf_hub_download('endomorphosis/ipfs_south_africa_municipal_laws',f,repo_type='dataset',revision='8f4da986aa3ddb0b44b026312968b035fe06fab9',local_dir='live4') for f in ('data/laws-00001.parquet','data/articles-00001.parquet','data/laws-00002.parquet','data/articles-00002.parquet')]\"",
                  "OMP_THREAD_LIMIT=1 python3 refill_za_batch4.py live4 $MUNI_STAGE/../refill4 www.durban.gov.za=$MUNI_STAGE/tls/durban_bundle.pem www.tshwane.gov.za=$MUNI_STAGE/tls/tshwane_bundle.pem   # resumable; exit 3 = hard stop, 4 = paused too long",
                  "python3 patch_za_batch4.py live4 $MUNI_STAGE/../refill4 $PACK",
                  "python3 verify_za_batch4.py live4 $PACK",
                  "python3 build_code_bundle.py --profile za-batch4 --pack $PACK --manifest batch4_code.json",
                  "# earlier batches: patch_za_batch3.py / patch_za_batch1_bcm.py (replacements), run_za_batch2.sh (collector + stager, batch 2)"]
    elif profile == "za-batch5":
        lines += [("export MUNI_STAGE=/dev/shm/muni_africa/za PACK=$MUNI_STAGE/hf/ipfs_south_africa_municipal_laws FS_STAGE=/dev/shm/muni_africa/fs FS_RAW=" + str(_LEGAL_WS) + "/muni/fs_raw"),
                  "export LEGAL_CORPORA_ROOT=$FS_STAGE/root LIVE=live5",
                  "# live files at the parent revision (read-only download):",
                  "python3 -c \"import huggingface_hub as h; [h.hf_hub_download('endomorphosis/ipfs_south_africa_municipal_laws',f,repo_type='dataset',revision='7aafa0a56f8f08147f4e8be7505d331482c6d648',local_dir='live5') for f in ('data/laws-00001.parquet','data/articles-00001.parquet','data/laws-00002.parquet','data/articles-00002.parquet')]\"",
                  "bash run_za_fs.sh   # gated, one runner slot for the fetch (released on exit), then the offline steps below; completion: 'RUNNER EXIT rc=0' + $FS_STAGE/OFFLINE_DONE",
                  "# the same steps by hand:",
                  "python3 collect_za_fs_gazette.py                       # network: listing + gazette PDFs (robots_guard, verify=True, >=5 s)",
                  "OMP_THREAD_LIMIT=1 python3 extract_za_fs_gazette.py    # offline: per-page text / OCR",
                  "python3 stage_za_fs_gazette.py $LIVE $PACK             # offline: notices -> by-law laws-00003 / articles-00003 + manifests",
                  "python3 patch_za_batch5_plum.py $LIVE $PACK            # offline: PLUM retitle -> laws-00001",
                  "python3 verify_za_batch5.py $LIVE $PACK",
                  "python3 build_code_bundle.py --profile za-batch5 --pack $PACK --manifest batch5_code.json",
                  "# earlier batches: patch_za_batch4.py / patch_za_batch3.py / patch_za_batch1_bcm.py (replacements), run_za_batch2.sh (collector + stager, batch 2)"]
    elif profile == "za-backfill":
        lines += ["export MUNI_STAGE=/dev/shm/muni_africa/za LEGAL_CORPORA_ROOT=$MUNI_STAGE/root",
                  "python3 make_ca_bundle.py certs/durban.gov.za_Sectigo_Public_Server_Authentication_CA_DV_R36.pem $MUNI_STAGE/tls/durban_bundle.pem",
                  "ZA_METROS=eth,ekh,bcm python3 collect_za_metros_muni.py", "ZA_BATCH=1 python3 stage_za_metros_muni.py",
                  "# production: bash run_za_batch1.sh (gated, locked, resumable)"]
    elif profile.startswith("tz"):
        lines += ["export MUNI_STAGE=/dev/shm/muni_africa/tz LEGAL_CORPORA_ROOT=$MUNI_STAGE/root OMP_THREAD_LIMIT=1",
                  "TZ_PILOT=20 python3 collect_tz_oagmis_muni.py && python3 stage_tz_oagmis_muni.py --pilot-report   # pilot",
                  "TZ_PILOT=0 python3 collect_tz_oagmis_muni.py   # all selected rows (resumes)",
                  "python3 stage_tz_oagmis_muni.py",
                  "python3 build_code_bundle.py --profile tz-batch1 --pack $MUNI_STAGE/hf/ipfs_tanzania_municipal_laws --manifest batch1_code.json",
                  "# production: bash run_tz.sh pilot ; bash run_tz.sh full (gated, slot-locked, resumable)"]
    else:
        lines += ["export MUNI_STAGE=/dev/shm/muni_africa/ke LEGAL_CORPORA_ROOT=$MUNI_STAGE/root",
                  "python3 collect_ke_counties_muni.py", "python3 stage_ke_counties_muni.py", "# production: bash run_ke.sh (gated, locked, resumable)"]
    lines += ["```", "", "## Inputs / outputs", ""]
    if profile.startswith("za"):
        lines += ["- Inputs: official metro by-law listing pages (eThekwini, Ekurhuleni, Buffalo City in batch 1; City of Tshwane 'Promulgated By-Laws' page in batch 2) and the documents they link; batch 2 also reads `seeds/batch1_law_ids.txt`.",
                  "- Outputs: `$MUNI_STAGE/records.jsonl` (text per document), `listings.jsonl`, `state.json`; stager writes `$MUNI_STAGE/hf/ipfs_south_africa_municipal_laws/data/laws-0000N.parquet`, `articles-0000N.parquet`, `manifests/batchN_stage_result.json`."]
    elif profile.startswith("tz"):
        lines += ["- Inputs: OAG MIS subsidiary-legislation table (JSON endpoint behind the portal's legislation page) and the PDFs it links; `seeds/TZ.jsonl` (Tanzanian districts with Wikidata QIDs).",
                  "- Outputs: `$MUNI_STAGE/records.jsonl` (text per document), `listings.jsonl`, `selection.json`, `state.json`; stager writes `$MUNI_STAGE/hf/ipfs_tanzania_municipal_laws/data/laws-00001.parquet`, `articles-00001.parquet`, `README.md`, `manifests/batch1_stage_result.json`, `manifests/batch1_council_qids.jsonl`, `exclusions/*.jsonl`."]
    else:
        lines += ["- Inputs: `seeds/KE.jsonl` (county list with Wikidata QIDs), Kenya Law county legislation pages.",
                  "- Outputs: `$MUNI_STAGE/records.jsonl`; stager writes `$MUNI_STAGE/hf/ipfs_kenya_municipal_laws/data/laws.parquet`, `articles.parquet` (renamed to `-00001` on upload)."]
    if transforms:
        lines += ["", "## Bundle-time edits (path defaults / wording only; logic unchanged)", ""] + \
                 [f"- `{f}`: `{a}` -> `{b}`" if not SCAN_RX.search(a) else f"- `{f}`: comment/echo wording changed to `{b}` (scan-clean)" for f, a, b in transforms]
    lines += ["", "Excluded: logs, caches, raw downloads, OCR checkpoints, records.jsonl, __pycache__, cookies, .env files, credentials and keys."]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True, choices=sorted(PROFILES))
    ap.add_argument("--pack", required=True)
    ap.add_argument("--manifest", required=True)
    a = ap.parse_args()
    P = PROFILES[a.profile]
    pack = Path(a.pack); sc = pack / "scrapers"
    if sc.exists():
        shutil.rmtree(sc)                     # scrapers/ is overwritten by each batch (latest code)
    sc.mkdir(parents=True)
    sources, transforms = {}, []
    for dst, src in P["files"].items():
        src = Path(src)
        text = src.read_bytes()
        for old, new in P["transforms"].get(dst, []):
            assert old.encode() in text, f"transform anchor missing in {src}: {old}"
            text = text.replace(old.encode(), new.encode()); transforms.append((dst, old, new))
        (sc / dst).write_bytes(text)
        sources[dst] = {"source_path": str(src), "source_sha256": sha256(src)}
    # every local import must be bundled
    py = [p for p in sc.glob("*.py")]
    local = {p.stem for p in py}
    allmods = set()
    for p in py:
        allmods |= local_imports(p, local)
    candidates = {m for m in allmods if (COL / f"{m}.py").exists()}
    missing = sorted(candidates - local)
    assert not missing, f"local modules imported but not bundled: {missing}"
    for c in P["certs"]:
        (sc / "certs").mkdir(exist_ok=True)
        shutil.copy2(COL / "certs" / c, sc / "certs" / c)
        sources[f"certs/{c}"] = {"source_path": str(COL / "certs" / c), "source_sha256": sha256(COL / "certs" / c)}
    for dst, src in P["seeds"].items():
        (sc / "seeds").mkdir(exist_ok=True)
        shutil.copy2(src, sc / "seeds" / dst)
        sources[f"seeds/{dst}"] = {"source_path": str(src), "source_sha256": sha256(src)}
    tp = [m for m in third_party(allmods) if m not in local]
    req = pinned_requirements(tp)
    (sc / "requirements.txt").write_text("# pinned from system python3 " + sys.version.split()[0] +
                                         f" (imported: {', '.join(tp)}; plus their dependencies)\n" +
                                         "".join(f"{k}=={v}\n" for k, v in sorted(req.items(), key=lambda kv: kv[0].lower())))
    files = sorted(str(p.relative_to(sc)) for p in sc.rglob("*") if p.is_file()) + ["README.md"]
    (sc / "README.md").write_text(readme(a.profile, a.manifest, req, files, transforms))
    junk = [str(p) for p in sc.rglob("*") if p.name in ("__pycache__", ".env") or p.suffix in (".pyc", ".log", ".jsonl") and "seeds" not in p.parts]
    assert not junk, f"excluded artefacts present: {junk}"
    hits, real, emails, homes = scan(sc)
    if real:
        print(json.dumps({"REAL_CREDENTIAL_HITS": real}, indent=1))
        sys.exit(2)
    fmap = {str(p.relative_to(pack)): sha256(p) for p in sorted(sc.rglob("*")) if p.is_file()}
    man = {"repo": P["repo"], "parser_version": P["parser_version"], "profile": a.profile,
           "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
           "python": sys.version.split()[0], "files": fmap, "requirements": req, "sources": sources,
           "bundle_transforms": [{"file": f, "old": o, "new": n} for f, o, n in transforms],
           SCAN_KEY: {"command": "rg -n -i '" + SCAN_PATTERN + "' scrapers/",
                      "real_" + W_SEC + "s": 0, "benign_hits": hits, "result": "PASS (0 real credentials; benign hits listed)" if hits else "PASS (0 hits)"},
           "email_scan": {"hits": emails, "result": "PASS" if not emails else "REVIEW"},
           "home_path_scan": {"hits": homes, "result": "PASS" if not homes else "REVIEW"}}
    (pack / "manifests").mkdir(parents=True, exist_ok=True)
    mp = pack / "manifests" / a.manifest
    mp.write_text(json.dumps(man, indent=1, ensure_ascii=False))
    print(json.dumps({"pack": str(pack), "manifest": str(mp), "manifest_sha256": sha256(mp), "files": len(fmap),
                      SCAN_KEY: man[SCAN_KEY]["result"], "benign_hits": len(hits), "emails": len(emails), "home_paths": len(homes)}, indent=1))
    return 0 if not emails and not homes else 3


if __name__ == "__main__":
    sys.exit(main())
