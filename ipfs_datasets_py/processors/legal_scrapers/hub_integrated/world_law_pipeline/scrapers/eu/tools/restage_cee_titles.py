#!/usr/bin/env python3
"""2026-10-18: council_docs.py sk/cz first-run rows (01:04-01:28 PT) carried titles decoded as ISO-8859-1 (pages with no
charset header) or generic link text ("Stiahnuť"), and kept some non-act PDFs found on act listing pages.
Staged files are never modified: rows whose title changes go to NEW batches <pk>.<src>fix_<UTC>p0001.jsonl (same doc_id,
newer batch supersedes); rows that fail the profile's act test are listed in _state/council_<cc>/not_act_staged.jsonl
for the Normalizer (drop by doc_id). Usage: python3 tools/restage_cee_titles.py [--dry-run]"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import argparse, glob, json, os, re, sys
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import unquote
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
import council_docs as C  # noqa: E402
import schema  # noqa: E402
from common.live import utc_tag  # noqa: E402

ST = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/eu"))
MOJI = re.compile(r"[ÃÄÅÆÐÑØ][\x80-\xbf\u0080-\u00ff]|Â|è|ì|ø")
GENERIC = re.compile(r"(?i)\s*(stiahnu|stiahn|download|st[áa]hnout|zobrazit|herunterladen|pdf|docx?|otvori|soubor|s[úu]bor)\b")


def fix_moji(t):
    for enc in ("latin-1", "cp1252"):
        try:
            u = t.encode(enc).decode("utf-8")
            if u != t:
                return u
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    if re.search(r"[ìèøù]", t):          # cp1250 bytes read as latin-1 (ì=ě, è=č, ø=ř, ù=ů)
        try:
            return t.encode("latin-1").decode("cp1250")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return t


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--dry-run", action="store_true"); a = ap.parse_args()
    st = Counter()
    for prof, cc, src in (("sk", "SK", "skvzn"), ("cz", "CZ", "czozv")):
        P = C.PROFILES[prof]
        fixed, notact = defaultdict(list), []
        for f in sorted(glob.glob(str(ST / cc / f"*.{src}_*.jsonl"))):
            for ln in open(f, encoding="utf-8"):
                r = json.loads(ln)
                t0 = r["title_native"] or ""
                t = fix_moji(t0)
                if len(t) < 8 or GENERIC.match(t):
                    first = next((x.strip() for x in r["text"].splitlines() if len(x.strip()) > 25), "")
                    fn = re.sub(r"\.(pdf|docx?)$", "", unquote(r["source_url"].rsplit("/", 1)[-1].split("?")[0]), flags=re.I)
                    t = (first or fn)[:300]
                if not (P["doc"].search(t) or P["doc"].search(r["source_url"]) or P["text_req"].search(r["text"][:3000])):
                    notact.append({"doc_id": r["doc_id"], "place_id": r["place_id"], "file": Path(f).name,
                                   "title": t[:150], "source_url": r["source_url"], "reason": "not_act (no act-type cue in link, URL or text)"})
                    st[f"{cc}_not_act"] += 1
                if t != t0:
                    r["title_native"] = t
                    r["title_fix"] = "2026-10-18 restage_cee_titles: charset / generic link text"
                    fixed[r["place_id"]].append(r)
                    st[f"{cc}_title_fixed"] += 1
                st[f"{cc}_rows"] += 1
        if a.dry_run:
            continue
        for pid, rows in fixed.items():
            pk = schema.place_key(pid)
            out = ST / cc / f"{pk}.{src}fix_{utc_tag()}p0001.jsonl"
            tmp = out.with_name("." + out.name[:-len(".jsonl")] + ".tmp.jsonl")
            with tmp.open("w", encoding="utf-8") as fh:
                for r in rows:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
                fh.flush(); os.fsync(fh.fileno())
            v = schema.validate_file(tmp, expect_place_key=pk)
            if not v["ok"]:
                os.unlink(tmp); print("INVALID", out.name, v["errors"][:2], v["file_errors"]); continue
            os.rename(tmp, out)
        lp = ST / "_state" / f"council_{prof}" / "not_act_staged.jsonl"
        with lp.open("w", encoding="utf-8") as fh:
            for x in notact:
                fh.write(json.dumps(x, ensure_ascii=False) + "\n")
    print(dict(st))


if __name__ == "__main__":
    main()
