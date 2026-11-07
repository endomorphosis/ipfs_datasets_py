#!/usr/bin/env python3
"""Idempotent code sync: world-law lane scrapers + pipeline code -> HF model repo endomorphosis/world_law_pipeline.

Each run: inventory -> scrub (path env-ification + secret scan) -> stage into a temp dir -> compare with the Hub
(git blob sha1 / LFS sha256 of every remote file) and state/code_sync_state.json -> upload ONLY new or changed
files in ONE commit (CommitOperationAdd only; never deletes anything on the Hub). No changes -> no commit.

Refuses to upload (exit 3) if the secret scan of the staged tree finds anything.

Layout on the Hub (same as the 2026-10 hand-curated bundle, commit a37e6c1f):
  pipeline/*.py, SCHEMA.md, PDF_STAGING.md       -> /
  pipeline/{tools,tests,world}/                   -> tools/, tests/, world/   (no *_draft.py)
  pipeline/codes/*.py                              -> codes/                   (data/csv/parquet are not touched)
  pipeline/archive/                                -> archive_fetcher/
  state/doc_overrides.json                         -> state/doc_overrides.json
  pipeline/scrapers/<lane>/**                      -> scrapers/<lane>/**
  out/afme_*.{py,sh,json,md}                       -> scrapers/afme/
  out/eap/** (code)                                -> scrapers/eap/
  ocr/** (code)                                    -> scrapers/ocr/
  codes_ext/build_ph_cities.py / build_kg_*.py     -> scrapers/ph/codes_ext/, scrapers/sasia_ru/codes_ext/
  ~/.ipfs_datasets/world_law/<lane>*/ , ~/.ipfs_datasets/world_law_<lane>*/  -> scrapers/<lane>/<dir>/
  EXTRA_DIRS (ad-hoc probe dirs in /workspace)     -> scrapers/<lane>/_adhoc/<dir>/
  staging/<lane>/** (code only)                    -> extras/staging_scripts/<lane>/**
  generated: scrapers/README.md (index), README.md (marked "lane scrapers" block in the Hub README)

Usage:
  /workspace/hf-venv/bin/python ~/.ipfs_datasets/world_law/pipeline/tools/sync_code.py [--dry-run] [--list] [--json out.json]
Exit: 0 ok (uploaded or nothing to do), 2 lock busy, 3 secret scan refused, 4 Hub error.
HF_TOKEN is read from the environment by huggingface_hub; it is never printed or written.
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))

import argparse, ast, warnings, fcntl, hashlib, io, json, os, re, shutil, sys, tempfile, time, tokenize
from collections import Counter, defaultdict
from pathlib import Path

warnings.filterwarnings("ignore", category=SyntaxWarning)  # ast.parse of scraper files with old-style escapes
REPO_ID = "endomorphosis/world_law_pipeline"
REPO_TYPE = "model"
WL = Path(os.environ.get("WORLD_LAW_ROOT", str(_WORLD)))
WS = WL.parent
PIPE = WL / "pipeline"
STATE = WL / "state"
STATE_FILE = STATE / "code_sync_state.json"
LOCK_FILE = STATE / "code_sync.lock"   # own lock; never touches state/run_loop.lock

LANES = ["eu", "web", "national", "asia_latam", "afme", "sasia_ru", "eap", "ph", "id_jdih", "ocr", "states", "ukie", "counties"]
# ad-hoc probe dirs elsewhere in /workspace that clearly belong to a lane (reviewed 2026-10-17)
EXTRA_DIRS = {WS / "tmp_bop": "asia_latam",   # ES BOP probes / restart helper (imports scrapers/asia_latam/es)
              WS / "tmp_ls": "asia_latam"}    # JP Legal Square session probe (imports asia_latam/common)
UNATTRIBUTED_DIRS = [WS / "plgr_work"]  # PL/GR place-code Wikidata helper (codes/ work, not a lane)
CODES_EXT = {"build_ph_cities.py": "ph", "build_kg_aiyl_aimaks.py": "sasia_ru"}
WL_HANDLED = {"ocr", "out", "out_national", "staging", "state", "pipeline", "codes", "codes_ext", "processed",
              "publish", "quarantine", "held", "logs", "_state", "_watchdog"}
NEVER = [WS / "municipal_law", WS / "ipfs_datasets_py", WS / "ipfs_datasets_py_latest", WS / "hf-venv"]

SKIP_DIRS = {"__pycache__", "venv", ".venv", "site-packages", "node_modules", ".git", "data", "raw", "_raw",
             "_sitemaps", "cache", "_cache", "_logs", "logs", "_ratelimit", "arch_ckpt", "hub", ".ipynb_checkpoints"}
SKIP_DIR_RE = re.compile(r"^(_?venv.*|.*-venv|_cache.*|_bak.*|\.bak.*|.*\.bak.*|_restage.*|_test.*|_tmp.*|tmp)$")
CODE_EXT = {".py", ".sh"}
CFG_EXT = {".json", ".yaml", ".yml", ".toml"}
CFG_MAX = 64 * 1024
CFG_DATA_RE = re.compile(r"(^seeds_|^wd_|^hub_|catalog|_items|inventory|manifest|^_report|^_unmapped|ckpt|"
                         r"\.queue\.json$|_raw|^_|state|status|progress|checkpoint|^cc_|_caps)", re.I)
DOC_RE = re.compile(r"^(README.*|.*NOTES.*|.*_sources|PROVENANCE)\.(md|txt)$", re.I)
CODE_MAX = 3 * 1024 * 1024
BACKUP_RE = re.compile(r"(\.bak|^_bak|^\.bak|\.orig$|~$|\.swp$|\.pyc$|_draft\.py$)")

# ---------------------------------------------------------------------------------------------- secrets
SECRET_PATTERNS = [
    ("hf_token", re.compile(r"hf_[A-Za-z0-9]{30,}")),
    ("github_token", re.compile(r"(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}")),
    ("openai_style_key", re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_\-]{20,}")),
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("bearer_literal", re.compile(r"Bearer\s+(?!\{)[A-Za-z0-9._~+/\-]{16,}=*")),
    ("password_literal", re.compile(r"(?i)\b(pass(word|wd)?|pwd)\s*[=:]\s*[\"'](?!\s*[\"'])(?!<REDACTED>)[^\"'\s{}$]{3,}[\"']")),
    ("api_key_literal", re.compile(r"(?i)\b(api[_-]?key|apikey|secret|access[_-]?token|auth[_-]?token)\s*[=:]\s*[\"'](?!<REDACTED>)[A-Za-z0-9_\-./+=]{12,}[\"']")),
    ("cookie_header_literal", re.compile(r"(?i)[\"']Cookie[\"']\s*:\s*[\"'][^\"'{}]*=[^\"'{}]{6,}[\"']|^\s*Cookie:\s*\S+=\S{6,}", re.M)),
    ("credentials_in_url", re.compile(r"[a-z][a-z0-9+.\-]*://[^/\s:@\"'{}]+:[^/\s@\"'{}]{3,}@[A-Za-z0-9.\-]+")),
    ("private_key_block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("jwt_literal", re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")),
]
# local credential file paths: reported (informational), not blocking, values are never read
CRED_PATH_RE = re.compile(r"(\.cache/huggingface/token|\.netrc|\.aws/credentials|\.ssh/id_[a-z0-9]+|\.git-credentials|"
                          r"\.docker/config\.json|cookies?\.txt|cookie_?jar|\.pgpass|/\.env\b|credentials\.json|"
                          r"service_account[^\s\"']*\.json|[\"']huggingface[\"']\s*/\s*[\"']token[\"'])", re.I)
PLACEHOLDER_RE = re.compile(r"(?i)(x{4,}|\.\.\.|<[^>]+>|example|changeme|your[_-]|dummy|placeholder|test)")


SPLIT_ENV = {"collect_td.py": "TD_SUPABASE_ANON_KEY"}  # env var name used when a split-literal secret is redacted


def split_literal_runs(text: str):
    """Runs of >= 2 adjacent plain string literals (implicit concatenation) in Python source -> (start, end, value)."""
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, SyntaxError, IndentationError):
        return []
    lines = text.splitlines(keepends=True)
    offs = [0]
    for ln in lines:
        offs.append(offs[-1] + len(ln))
    pos = lambda rc: offs[rc[0] - 1] + rc[1]  # noqa: E731
    runs, cur = [], []
    for t in toks:
        if t.type == tokenize.STRING:
            cur.append(t)
        elif t.type in (tokenize.NL, tokenize.COMMENT) or (t.type == tokenize.NEWLINE and False):
            continue
        else:
            if len(cur) >= 2:
                runs.append(cur)
            cur = []
    if len(cur) >= 2:
        runs.append(cur)
    out = []
    for r in runs:
        try:
            val = "".join(str(ast.literal_eval(t.string)) for t in r)
        except Exception:
            continue
        out.append((pos(r[0].start), pos(r[-1].end), val))
    return out


def scan_secrets(text: str, is_py: bool = False):
    hits = []
    if is_py and "eyJ" in text or is_py and re.search(r"hf_|ghp_|sk-|AKIA", text):
        for a, b, val in split_literal_runs(text):
            for kind, rx in SECRET_PATTERNS:
                if kind in ("hf_token", "github_token", "openai_style_key", "aws_access_key", "jwt_literal") \
                        and rx.search(val) and not rx.search(text[a:b]):
                    hits.append((kind + "_split_literal", text.count("\n", 0, a) + 1, a, b))
                    break
    for kind, rx in SECRET_PATTERNS:
        for m in rx.finditer(text):
            val = m.group(0)
            if kind in ("password_literal", "api_key_literal", "credentials_in_url", "cookie_header_literal") \
                    and PLACEHOLDER_RE.search(val):
                continue
            line = text.count("\n", 0, m.start()) + 1
            hits.append((kind, line, m.start(), m.end()))
    return hits


def redact(text: str, hits, env_name: str = "WL_REDACTED_SECRET"):
    """Replace each secret VALUE span with <REDACTED> (keeps quotes/keys so the code still parses)."""
    for kind, _line, a, b in sorted(hits, key=lambda h: -h[2]):
        seg = text[a:b]
        if kind.endswith("_split_literal"):
            text = text[:a] + f'__import__("os").environ.get("{env_name}", "")' + text[b:]
            continue
        if kind in ("password_literal", "api_key_literal"):
            q = re.search(r"[=:]\s*([\"'])", seg)
            i = q.end()
            seg = seg[:i] + "<REDACTED>" + seg[-1]
        elif kind == "cookie_header_literal":
            seg = re.sub(r"(Cookie[\"']?\s*:\s*[\"']?).*", lambda m: m.group(1) + "<REDACTED>" + (seg[-1] if seg[-1] in "\"'" else ""), seg, flags=re.I)
        elif kind == "credentials_in_url":
            seg = re.sub(r"(://)[^@]+@", r"\1<REDACTED>@", seg)
        elif kind == "bearer_literal":
            seg = "Bearer <REDACTED>"
        else:
            seg = "<REDACTED>"
        text = text[:a] + seg + text[b:]
    return text


# ---------------------------------------------------------------------------------------------- env-ification
ROOTS = [(_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)), "WORLD_LAW_ROOT"), (_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities"), "GLOBAL_MUNICIPALITIES_ROOT")]
IMPORT_LINE = "import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths\n"
_STR_HEAD = re.compile(r"^([rRuU]?)('|\")")


def envify(src: str) -> str:
    """Same transform as the published bundle: plain (non-f, non-triple-quoted) string literals that start with
    ~/.ipfs_datasets/world_law or /workspace/global_municipalities become env lookups with the old path as default.
    Falls back to the original source if the result does not compile."""
    if not any(r in src for r, _ in ROOTS):
        return src
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except (tokenize.TokenError, SyntaxError, IndentationError):
        return src
    sig = [t for t in toks if t.type not in (tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT, tokenize.INDENT,
                                               tokenize.DEDENT)]
    strish = {tokenize.STRING} | ({tokenize.FSTRING_START} if hasattr(tokenize, "FSTRING_START") else set())
    lines = src.splitlines(keepends=True)
    offs = [0]
    for ln in lines:
        offs.append(offs[-1] + len(ln))
    edits = []
    for i, t in enumerate(sig):
        if t.type != tokenize.STRING or t.start[0] != t.end[0]:
            continue
        m = _STR_HEAD.match(t.string)
        if not m or t.string[len(m.group(1)):len(m.group(1)) + 3] in ('"""', "'''"):
            continue
        pre, q = m.groups()
        body = t.string[len(pre) + 1:-1]
        for root, env in ROOTS:
            if body == root or body.startswith(root + "/"):
                if (i > 0 and sig[i - 1].type in strish) or (i + 1 < len(sig) and sig[i + 1].type in strish):
                    break  # implicit concatenation: leave as is
                if i >= 4 and sig[i - 1].string == "," and sig[i - 2].type == tokenize.STRING \
                        and sig[i - 3].string == "(" and sig[i - 4].string in ("get", "getenv", "setdefault"):
                    break  # already the default of an env lookup
                rest = body[len(root):]
                base = f'_wl_os.environ.get("{env}", "{root}")'
                new = f"({base} + {pre}{q}{rest}{q})" if rest else base
                a = offs[t.start[0] - 1] + t.start[1]
                b = offs[t.end[0] - 1] + t.end[1]
                edits.append((a, b, new))
                break
    if not edits:
        return src
    out = src
    for a, b, new in sorted(edits, key=lambda e: -e[0]):
        out = out[:a] + new + out[b:]
    if "_wl_os" not in src:
        try:
            tree = ast.parse(src)
            after = 0
            for k, node in enumerate(tree.body):
                if k == 0 and isinstance(node, ast.Expr) and isinstance(getattr(node, "value", None), ast.Constant) \
                        and isinstance(node.value.value, str):
                    after = node.end_lineno
                elif isinstance(node, ast.ImportFrom) and node.module == "__future__":
                    after = node.end_lineno
                else:
                    break
            if after == 0:  # after shebang / coding comments
                ol = out.splitlines(keepends=True)
                while after < len(ol) and (ol[after].startswith("#!") or re.match(r"#.*coding[:=]", ol[after])):
                    after += 1
            ol = out.splitlines(keepends=True)
            # edits never change line counts (single-line tokens), so line numbers still match
            out = "".join(ol[:after]) + IMPORT_LINE + "".join(ol[after:])
        except SyntaxError:
            return src
    try:
        compile(out, "<envify>", "exec")
    except SyntaxError:
        return src
    return out


# ---------------------------------------------------------------------------------------------- inventory
def keep_file(p: Path, docs: bool, vendor: bool) -> bool:
    n = p.name
    if n.startswith(".") or BACKUP_RE.search(n):
        return False
    try:
        size = p.stat().st_size
    except OSError:
        return False
    if p.suffix in CODE_EXT:
        return size <= CODE_MAX
    if vendor and n not in ("RECORD", "WHEEL", "INSTALLER", "REQUESTED"):
        return size <= 256 * 1024
    if p.suffix in CFG_EXT:
        return size <= CFG_MAX and not CFG_DATA_RE.search(n)
    if docs and DOC_RE.match(n):
        return size <= 256 * 1024
    return False


def walk(root: Path, docs=True, code_only=False):
    for dp, dn, fn in os.walk(root):
        dn[:] = sorted(d for d in dn if d not in SKIP_DIRS and not SKIP_DIR_RE.match(d) and not d.startswith("."))
        vendor = "vendor" in Path(dp).relative_to(root).parts
        for f in sorted(fn):
            p = Path(dp) / f
            if p.is_symlink():
                continue
            if code_only:
                if p.suffix in CODE_EXT and not f.startswith(".") and not BACKUP_RE.search(f):
                    yield p
            elif keep_file(p, docs, vendor):
                yield p


def inventory():
    """-> (items, unattributed). item = dict(src, dest, lane|None, group)."""
    items, unattr = [], []

    def add(src, dest, lane, group):
        items.append({"src": Path(src), "dest": dest, "lane": lane, "group": group})

    # core pipeline (normalizer/uploader, tools, tests, world, codes builders, archive fetcher)
    for p in sorted(PIPE.glob("*")):
        if p.is_file() and (p.suffix == ".py" or p.name in ("SCHEMA.md", "PDF_STAGING.md")) and not BACKUP_RE.search(p.name):
            add(p, p.name, None, "pipeline")
    for sub, dest in (("tools", "tools"), ("tests", "tests"), ("world", "world")):
        for p in sorted((PIPE / sub).glob("*")):
            if p.is_file() and not BACKUP_RE.search(p.name) and (p.suffix == ".py" or p.suffix == ".md"):
                add(p, f"{dest}/{p.name}", None, "pipeline")
    for p in sorted((PIPE / "codes").glob("*.py")):
        if not BACKUP_RE.search(p.name):
            add(p, f"codes/{p.name}", None, "pipeline")
    arch = PIPE / "archive"
    for p in walk(arch, docs=True):
        rel = p.relative_to(arch).as_posix()
        if p.suffix in (".py", ".md") or "vendor/" in rel:
            add(p, f"archive_fetcher/{rel}", None, "pipeline")
    if (STATE / "doc_overrides.json").exists():
        add(STATE / "doc_overrides.json", "state/doc_overrides.json", None, "pipeline")

    # lane code
    sc = PIPE / "scrapers"
    for d in sorted(sc.iterdir()) if sc.exists() else []:
        if not d.is_dir() or d.name.startswith(("_", ".")) or d.name == "__pycache__":
            continue
        lane = d.name if d.name in LANES else None
        for p in walk(d):
            rel = p.relative_to(d).as_posix()
            if lane:
                add(p, f"scrapers/{lane}/{rel}", lane, "scrapers")
            else:
                unattr.append(str(p))
    out = WL / "out"
    for p in sorted(out.glob("afme_*")):
        if p.is_file() and keep_file(p, docs=False, vendor=False) or (p.is_file() and p.name == "afme_sources.md"):
            add(p, f"scrapers/afme/{p.name}", "afme", "out")
    if (out / "eap").exists():
        for p in walk(out / "eap", docs=False):
            add(p, f"scrapers/eap/{p.relative_to(out / 'eap').as_posix()}", "eap", "out")
    for p in sorted(out.glob("*")):
        if p.is_file() and p.suffix in CODE_EXT and not p.name.startswith("afme_") and not BACKUP_RE.search(p.name):
            unattr.append(str(p))
    ocr = WL / "ocr"
    if ocr.exists():
        for p in walk(ocr, docs=True):
            add(p, f"scrapers/ocr/{p.relative_to(ocr).as_posix()}", "ocr", "ocr")
    ce = WL / "codes_ext"
    for p in sorted(ce.glob("*")) if ce.exists() else []:
        if p.suffix in CODE_EXT and not BACKUP_RE.search(p.name):
            lane = CODES_EXT.get(p.name)
            if lane:
                add(p, f"scrapers/{lane}/codes_ext/{p.name}", lane, "codes_ext")
            else:
                unattr.append(str(p))
    # lane code dirs: ~/.ipfs_datasets/world_law/<lane>*/ and ~/.ipfs_datasets/world_law_<lane>*/
    for base, pat in ((WL, "*"), (WS, "world_law_*")):
        for d in sorted(base.glob(pat)):
            if not d.is_dir() or d == WL:
                continue
            nm = d.name[len("world_law_"):] if base == WS else d.name
            lane = next((ln for ln in sorted(LANES, key=len, reverse=True) if nm == ln or nm.startswith(ln + "_")
                         or nm.startswith(ln + "-")), None)
            if base == WL and (not lane or nm in WL_HANDLED):
                continue  # world_law/{out,ocr,staging,state,...} handled above / not code
            for p in walk(d):
                if lane:
                    add(p, f"scrapers/{lane}/{d.name}/{p.relative_to(d).as_posix()}", lane, "lane_dir")
                else:
                    unattr.append(str(p))
    for pat in ("*jdih*", "*ocr*"):
        for d in sorted(WS.glob(pat)):
            if d.is_dir() and d not in NEVER:
                lane = "id_jdih" if "jdih" in d.name else "ocr"
                for p in walk(d):
                    add(p, f"scrapers/{lane}/{d.name}/{p.relative_to(d).as_posix()}", lane, "lane_dir")
    for d, lane in EXTRA_DIRS.items():
        if d.is_dir():
            for p in walk(d, docs=False):
                add(p, f"scrapers/{lane}/_adhoc/{d.name}/{p.relative_to(d).as_posix()}", lane, "adhoc")
    # code inside staging/<lane>/ (kept under the existing extras/staging_scripts/ layout)
    st = WL / "staging"
    for d in sorted(st.iterdir()) if st.exists() else []:
        if not d.is_dir():
            continue
        lane = d.name if d.name in LANES else None
        for dp, dn, fn in os.walk(d):
            dn[:] = [x for x in dn if x not in ("__pycache__", "_cache", "cache", "raw", "_raw") and not x.startswith(".")]
            for f in fn:
                p = Path(dp) / f
                if p.suffix in CODE_EXT and not f.startswith(".") and not BACKUP_RE.search(f) and not p.is_symlink():
                    if lane:
                        add(p, f"extras/staging_scripts/{lane}/{p.relative_to(d).as_posix()}", lane, "staging")
                    else:
                        unattr.append(str(p))
    # code that is world-law related but belongs to no lane: listed, never uploaded
    for p in sorted(STATE.glob("*.py")) + sorted(STATE.glob("memprof/*.py")) + sorted(STATE.glob("incidents/*/*.py")):
        unattr.append(str(p))
    for d in UNATTRIBUTED_DIRS:
        if d.is_dir():
            unattr.extend(str(p) for p in walk(d, docs=False, code_only=True))
    # safety: never anything from excluded trees
    items = [it for it in items if not any(str(it["src"]).startswith(str(n) + "/") for n in NEVER)]
    # dedupe by dest (first wins) and report collisions
    seen, out_items, coll = {}, [], []
    for it in items:
        if it["dest"] in seen:
            if seen[it["dest"]] != str(it["src"]):
                coll.append((it["dest"], str(it["src"])))
            continue
        seen[it["dest"]] = str(it["src"])
        out_items.append(it)
    return out_items, sorted(set(unattr)), coll


# ---------------------------------------------------------------------------------------------- index / README
URL_RE = re.compile(r"https?://([A-Za-z0-9.\-]+\.[A-Za-z]{2,})")
NOISE_HOSTS = re.compile(r"(^|\.)(example\.(com|org)|localhost|w3\.org|schema\.org|github\.com|githubusercontent\.com|"
                         r"huggingface\.co|python\.org|mozilla\.org|purl\.org|xmlns\.com|ogp\.me|json-schema\.org|"
                         r"googleapis\.com|gstatic\.com|google\.com|cloudflare\.com|jquery\.com|opengis\.net)$", re.I)


def describe(path: Path, text: str):
    purpose = ""
    if path.suffix == ".py":
        try:
            doc = ast.get_docstring(ast.parse(text)) or ""
        except SyntaxError:
            doc = ""
        purpose = next((ln.strip() for ln in doc.splitlines() if ln.strip()), "")
    if not purpose:
        for ln in text.splitlines()[:25]:
            s = ln.strip()
            if s.startswith("#!") or s.startswith("# -*-") or s.lower().startswith("# noqa") or not s.startswith("#"):
                continue
            s = s.lstrip("#").strip()
            if len(s) > 8:
                purpose = s
                break
    if not purpose and path.suffix in (".json", ".yaml", ".yml", ".toml"):
        purpose = "config / source list"
    if not purpose and path.suffix == ".md":
        purpose = next((ln.lstrip("# ").strip() for ln in text.splitlines() if ln.strip()), "docs")
    if not purpose:
        purpose = path.stem.replace("_", " ")
    purpose = re.sub(r"\s+", " ", purpose).replace("|", "\\|")
    if len(purpose) > 140:
        purpose = purpose[:137] + "..."
    hosts = Counter(h.lower().rstrip(".") for h in URL_RE.findall(text) if not NOISE_HOSTS.search(h))
    src = ", ".join(h for h, _ in hosts.most_common(3))
    return src.replace("|", "\\|"), purpose


LANE_TITLES = {
    "eu": "EU member states (NL CVDR/GMB, PL e-dzienniki, BE, EE, ES BOE autonómico, GR Diavgeia, IT statuti, LV, PT DRE, SI, UK LA)",
    "web": "Web crawlers for municipal by-laws (DE Ortsrecht + archive pass, FR actes, IT, CH, CA)",
    "national": "National/subnational collectors (`shared/collect_*.py`, ~230 jurisdictions), archive emitters",
    "asia_latam": "JP reiki, ES BOP/sede, BR LexML/SAPL, PE, MX, CL, ID, ZA, AU, archive jobs (`arch/`)",
    "afme": "Africa & Middle East gazettes/LII/live sites, Common Crawl index jobs (`afme_cfg_*.json` source lists)",
    "sasia_ru": "South Asia & Russia/CIS: RU gosweb, BY pravo, KG CBD, NP palika, PK Sindh, IN MCGM, UZ lex, VN VBPL",
    "eap": "East Asia & Pacific archive runner (KR, TW, NZ, PG, SB, TO, VU, WS)",
    "ph": "Philippines LGU sites + Wayback pass",
    "id_jdih": "Indonesia JDIH (regional legal documentation networks)",
    "ocr": "OCR passes for scanned PDFs (afme, GB, PH, RO, South Asia) + sweep tools",
    "states": "States & provinces lane (staging/states/)",
    "ukie": "UK & Ireland lane (staging/ukie/)",
}
BLOCK_START, BLOCK_END = "<!-- lane-scrapers:start (tools/sync_code.py) -->", "<!-- lane-scrapers:end -->"


def build_index(rows):
    by_lane = defaultdict(list)
    for r in rows:
        by_lane[r["lane"]].append(r)
    L = ["# scrapers/ — lane code index", "",
         "Generated by `tools/sync_code.py` (do not edit by hand). One directory per scraper lane (bot); each lane",
         "writes only to `staging/<lane>/<CC>/<place_key>[.<batch>].jsonl` (see `../SCHEMA.md` §1) and the",
         "normalizer/uploader `run_loop.py` publishes it. Code found in `staging/<lane>/` is under",
         "`extras/staging_scripts/<lane>/`. Backups (`*.bak*`), caches, logs, raw downloads and data are not included;",
         "secrets are scanned for and refused before every upload.", "",
         "| lane | files | what |", "|---|---:|---|"]
    for ln in LANES:
        if by_lane.get(ln):
            L.append(f"| [`{ln}`](#{ln}) | {len(by_lane[ln])} | {LANE_TITLES.get(ln, '')} |")
    L.append("")
    for ln in LANES:
        rs = by_lane.get(ln)
        if not rs:
            continue
        L += [f"## {ln}", "", "| file | lane | source / platform | purpose |", "|---|---|---|---|"]
        for r in sorted(rs, key=lambda r: r["dest"]):
            rel = r["dest"][len("scrapers/"):] if r["dest"].startswith("scrapers/") else "../" + r["dest"]
            L.append(f"| [`{r['dest']}`]({rel}) | {ln} | {r['src_hosts']} | {r['purpose']} |")
        L.append("")
    return "\n".join(L) + "\n"


def readme_block(lane_counts):
    rows = "\n".join(f"| `scrapers/{ln}/` | {lane_counts[ln]} | {LANE_TITLES.get(ln, '')} |" for ln in LANES if lane_counts.get(ln))
    return f"""{BLOCK_START}
## Datasets

| dataset | contents |
|---|---|
| [`endomorphosis/world_municipal_law`](https://huggingface.co/datasets/endomorphosis/world_municipal_law) | municipal / local law texts (one parquet per place) |
| [`endomorphosis/world_national_law`](https://huggingface.co/datasets/endomorphosis/world_national_law) | national, subdivision and supranational (`iso:*`) law texts |
| [`endomorphosis/world_law_scanned_pdfs`](https://huggingface.co/datasets/endomorphosis/world_law_scanned_pdfs) | raw image-only scanned PDFs: loose `pdfs/` (before 2026-10-18) + per-country tar shards `shards/<CC>/<YYYY>/<MM>/<CC>_<seq>.tar`; `manifest.parquet`; `world_law_loader.fetch_pdf(pdf_ref)` reads one PDF (shards via HTTP Range) |

## Lane scrapers

All scraper / runner code of the world-law lanes is under [`scrapers/`](scrapers/README.md); the
[index](scrapers/README.md) lists every file with its lane, the source/platform it covers and a one-line purpose.
Synced hourly by `tools/sync_code.py` (only new/changed files; secret scan must be clean).

| path | files | lane |
|---|---:|---|
{rows}

How to run a lane scraper:
* Python 3.13 in a virtualenv: `python3.13 -m venv venv && venv/bin/pip install requests pyarrow beautifulsoup4 lxml huggingface_hub`
  (+ `tesseract` / `pdftotext` for OCR lanes, `playwright` for `collect_spa_playwright.py`). On the build box the
  interpreter is `~/.ipfs_datasets/world_law/pipeline/venv/bin/python`.
* Set `WORLD_LAW_ROOT` (default `~/.ipfs_datasets/world_law`) and, for scrapers that read the candidate list,
  `GLOBAL_MUNICIPALITIES_ROOT`. Lane scripts are run from their own directory, e.g.
  `cd scrapers/eu && ../../venv/bin/python cvdr.py --help`, or via the lane's `run_*.sh`.
* Staging contract ([`SCHEMA.md`](SCHEMA.md) §1): a lane writes only `staging/<lane>/<CC>/<place_key>[.<batch>].jsonl`
  (`<CC>` = ISO 3166-1 alpha-2 uppercase, `<place_key>` = `schema.place_key(place_id)`, a UTC timestamp
  `YYYYMMDDTHHMMSSZ` in `<batch>`, write to a `.tmp` and rename). Anything under `staging/<lane>/_*` is ignored.
  `run_loop.py --once --dry-run` validates and shows what would be published; `iso:*` places go to
  `world_national_law`, everything else to `world_municipal_law`.
{BLOCK_END}
"""


def merge_readme(remote: str, block: str) -> str:
    if BLOCK_START in remote and BLOCK_END in remote:
        a = remote.index(BLOCK_START)
        b = remote.index(BLOCK_END) + len(BLOCK_END)
        rest = remote[b:]
        if rest.startswith("\n"):
            rest = rest[1:]
        return remote[:a] + block + rest
    anchor = "\n## world_law_loader.py"
    if anchor in remote:
        i = remote.index(anchor) + 1
        return remote[:i] + block + "\n" + remote[i:]
    return remote.rstrip("\n") + "\n\n" + block


# ---------------------------------------------------------------------------------------------- hashing
def git_blob_sha1(b: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(b) + b).hexdigest()


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ---------------------------------------------------------------------------------------------- main
def stage(items, tmp: Path, log):
    rows, findings, cred_refs, envified = [], [], [], 0
    for it in items:
        p = it["src"]
        try:
            raw = p.read_bytes()
        except OSError as e:
            log(f"skip unreadable {p}: {e}")
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("utf-8", errors="surrogateescape")
        if p.suffix == ".py":
            t2 = envify(text)
            if t2 != text:
                envified += 1
                text = t2
        hits = scan_secrets(text, p.suffix == ".py")
        # drop plain hits that sit inside a split-literal hit
        sp = [(a, b) for k, _l, a, b in hits if k.endswith("_split_literal")]
        hits = [h for h in hits if h[0].endswith("_split_literal") or not any(a <= h[2] < b for a, b in sp)]
        if hits:
            for kind, line, _a, _b in hits:
                findings.append({"file": str(p), "dest": it["dest"], "type": kind, "line": line, "action": "redacted"})
            text = redact(text, hits, SPLIT_ENV.get(p.name, "WL_REDACTED_SECRET"))
        for m in CRED_PATH_RE.finditer(text):
            cred_refs.append({"file": str(p), "dest": it["dest"], "type": "credential_path_ref:" + m.group(1),
                              "line": text.count("\n", 0, m.start()) + 1})
        data = text.encode("utf-8", errors="surrogateescape")
        dst = tmp / it["dest"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
        if os.access(p, os.X_OK):
            dst.chmod(0o755)
        hosts, purpose = describe(p, text)
        rows.append({**it, "src": str(p), "bytes": len(data), "src_hosts": hosts, "purpose": purpose})
    return rows, findings, cred_refs, envified


def final_scan(tmp: Path):
    bad = []
    for p in sorted(tmp.rglob("*")):
        if p.is_file():
            t = p.read_bytes().decode("utf-8", errors="replace")
            for kind, line, _a, _b in scan_secrets(t, p.suffix == ".py"):
                bad.append({"dest": p.relative_to(tmp).as_posix(), "type": kind, "line": line})
    return bad


def remote_tree(api):
    info = api.repo_info(REPO_ID, repo_type=REPO_TYPE)
    tree = {}
    for e in api.list_repo_tree(REPO_ID, repo_type=REPO_TYPE, recursive=True, revision=info.sha):
        if getattr(e, "blob_id", None) is None and not hasattr(e, "size"):
            continue
        lfs = getattr(e, "lfs", None)
        tree[e.path] = {"blob_id": getattr(e, "blob_id", None),
                        "lfs_sha256": (lfs.sha256 if lfs is not None and hasattr(lfs, "sha256") else
                                       (lfs.get("sha256") if isinstance(lfs, dict) else None))}
    return info.sha, tree


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="inventory/scrub/stage/compare only; no upload, no state write")
    ap.add_argument("--list", action="store_true", help="print every file to upload")
    ap.add_argument("--json", help="write a JSON report here")
    ap.add_argument("--keep-stage", help="copy the staged tree to this dir (for inspection)")
    ap.add_argument("--message", default=None, help="commit message")
    a = ap.parse_args(argv)
    log = lambda *x: print("[sync_code]", *x, flush=True)  # noqa: E731

    STATE.mkdir(parents=True, exist_ok=True)
    lockf = open(LOCK_FILE, "a")
    try:
        fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log("another sync_code run holds state/code_sync.lock; exiting")
        return 2

    items, unattr, coll = inventory()
    tmp = Path(tempfile.mkdtemp(prefix="wl_code_sync_"))
    try:
        rows, findings, cred_refs, envified = stage(items, tmp, log)
        lane_counts = Counter(r["lane"] for r in rows if r["lane"])
        lane_rows = [r for r in rows if r["lane"]]
        (tmp / "scrapers").mkdir(exist_ok=True)
        (tmp / "scrapers" / "README.md").write_text(build_index(lane_rows))

        from huggingface_hub import HfApi, CommitOperationAdd, hf_hub_download
        api = HfApi()
        try:
            head, tree = remote_tree(api)
            rp = hf_hub_download(REPO_ID, "README.md", repo_type=REPO_TYPE, revision=head,
                                 local_dir=str(tmp / "_remote"))
            remote_readme = Path(rp).read_text()
            shutil.rmtree(tmp / "_remote", ignore_errors=True)
        except Exception as e:  # noqa: BLE001
            log(f"Hub error: {type(e).__name__}: {str(e)[:200]}")
            return 4
        (tmp / "README.md").write_text(merge_readme(remote_readme, readme_block(lane_counts)))

        bad = final_scan(tmp)
        if a.keep_stage:
            shutil.copytree(tmp, a.keep_stage, dirs_exist_ok=True)

        state = {}
        if STATE_FILE.exists():
            try:
                state = json.loads(STATE_FILE.read_text())
            except Exception:
                state = {}
        files_state = state.get("files", {})
        changed, new = [], []
        local = {}
        for p in sorted(tmp.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(tmp).as_posix()
            b = p.read_bytes()
            s256, s1 = sha256(b), git_blob_sha1(b)
            local[rel] = s256
            r = tree.get(rel)
            if r is None:
                new.append(rel)
            elif not (r["blob_id"] == s1 or (r["lfs_sha256"] and r["lfs_sha256"] == s256)):
                changed.append(rel)
        todo = new + changed
        report = {"repo": REPO_ID, "remote_head": head, "files_staged": len(local), "new": len(new),
                  "changed": len(changed), "per_lane_staged": dict(lane_counts),
                  "per_lane_todo": dict(Counter((t.split("/")[1] if t.startswith(("scrapers/", "extras/staging_scripts/"))
                                                 and len(t.split("/")) > 2 and not t.startswith("extras") else
                                                 (t.split("/")[2] if t.startswith("extras/staging_scripts/") else "pipeline"))
                                                for t in todo)),
                  "unattributed": unattr, "dest_collisions": coll, "envified_py_files": envified,
                  "secret_findings_redacted": findings, "credential_path_refs": cred_refs,
                  "final_scan_hits": bad, "dry_run": a.dry_run, "todo": todo, "commit": None}
        log(f"remote {REPO_ID}@{head[:8]}: staged {len(local)} files, {len(new)} new, {len(changed)} changed; "
            f"lanes {dict(sorted(lane_counts.items()))}")
        log(f"secret findings (redacted in staged copy): {len(findings)}; credential-path refs (info): {len(cred_refs)}; "
            f"unattributed: {len(unattr)}; dest collisions: {len(coll)}")
        for f in findings:
            log(f"  secret {f['type']} in {f['file']}:{f['line']} -> redacted")
        if a.list:
            for t in todo:
                log(("  NEW " if t in new else "  CHG ") + t)
        if bad:
            for h in bad:
                log(f"  FINAL SCAN HIT {h['type']} in {h['dest']}:{h['line']}")
            log("REFUSING to upload: final secret scan is not clean")
            report["refused"] = True
            if a.json:
                Path(a.json).write_text(json.dumps(report, indent=1))
            return 3
        log("final secret scan: clean")
        if not todo:
            log("no changes; nothing to upload")
        elif a.dry_run:
            log(f"dry run: would upload {len(todo)} files in one commit")
        else:
            ops = [CommitOperationAdd(path_in_repo=t, path_or_fileobj=str(tmp / t)) for t in todo]
            msg = a.message or f"sync_code: {len(new)} new, {len(changed)} updated code files (lanes: " \
                               f"{', '.join(sorted(k for k in report['per_lane_todo']))})"
            try:
                ci = api.create_commit(REPO_ID, repo_type=REPO_TYPE, operations=ops, commit_message=msg,
                                       parent_commit=head)
            except Exception as e:  # noqa: BLE001
                log(f"Hub commit failed: {type(e).__name__}: {str(e)[:300]}")
                return 4
            sha = getattr(ci, "oid", None) or str(ci.commit_url).rstrip("/").split("/")[-1]
            report["commit"] = sha
            log(f"committed {len(todo)} files: {sha}")
            for t in todo:
                files_state[t] = {"sha256": local[t], "commit": sha}
        if not a.dry_run:
            for t, s in local.items():
                files_state.setdefault(t, {"sha256": s, "commit": None})
                if files_state[t]["sha256"] != s and t not in todo:
                    files_state[t]["sha256"] = s  # equal on the Hub already
            state = {"repo": REPO_ID, "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                     "last_remote_head": report["commit"] or head, "last_commit": report["commit"] or state.get("last_commit"),
                     "files": files_state}
            tmpf = STATE_FILE.with_suffix(".tmp")
            tmpf.write_text(json.dumps(state, indent=1, sort_keys=True))
            tmpf.replace(STATE_FILE)
        if a.json:
            Path(a.json).write_text(json.dumps(report, indent=1, default=str))
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        fcntl.flock(lockf, fcntl.LOCK_UN)
        lockf.close()


if __name__ == "__main__":
    sys.exit(main())
