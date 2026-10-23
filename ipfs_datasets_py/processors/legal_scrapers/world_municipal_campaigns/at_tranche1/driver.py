#!/usr/bin/env python3
"""Austria/Carinthia tranche-1 driver (amtstafel.at hub).

Reuses the pilot adapter (at_pilot/harvest_at_pilot.py) — same listing
parse, download pacing (>=2 s), section-split, world_municipal rows and
fail-closed validation — re-pointed at at_tranche1/ for its raw cache
and outputs. Two extensions over the pilot:

1. Extraction chain gains a final OCR stage: documents whose digital
   text is <300 chars are rendered (pdftoppm 300 dpi) and OCR'd with
   the persistent tessroot tesseract (deu). OCR text is used only if
   it yields >=300 chars with alpha ratio >=0.5; otherwise the
   document stays deferred (counted scanned_or_empty by the pilot
   harvester), never forced.
2. Per-Gemeinde publish + remote verification against
   endomorphosis/ipfs_austria_municipal_laws (fresh listing before
   each publish; refuses to overwrite a remote file of a different
   size, except coverage_report.md which this program owns).

Checkpointing: at_tranche1/state.json after every survey batch and
every Gemeinde. Statuses: pending -> harvested -> published_verified |
invalid | failed. Re-running resumes; published_verified Gemeinden
are skipped (the pilot harvester also caches PDFs on disk).

Scope: the next 24 Carinthian Gemeinden by listing size ascending
(surveyed by this driver over the pilot-verified 132-registry),
excluding the 6 pilot Gemeinden; Klagenfurt 20101 included as the
24th (largest) member; Villach 20201 deferred to its own tranche.
"""
import json
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
os.environ["TQDM_DISABLE"] = "1"
TOOLS_BIN = str(Path.home() / "workspace" / "tools" / "bin")
if TOOLS_BIN not in os.environ.get("PATH", "").split(":"):
    os.environ["PATH"] = TOOLS_BIN + ":" + os.environ.get("PATH", "")

HERE = Path(__file__).resolve().parent
AT_PILOT = HERE.parent / "at_pilot"
RAW = HERE / "raw"
OUT = HERE / "out"
OCR_TMP = HERE / "ocr_tmp"
STATE_PATH = HERE / "state.json"
for d in (RAW, OUT, OCR_TMP):
    d.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(AT_PILOT))
import harvest_at_pilot as H  # noqa: E402

H.RAW = RAW
H.OUT = OUT

REPO = "endomorphosis/ipfs_austria_municipal_laws"
PILOT_GKZ = ["20911", "20503", "21001", "20701", "20802", "20302"]
PILOT_ROWS = {"20911": 215, "20503": 369, "21001": 642,
              "20701": 535, "20802": 581, "20302": 784}
KLAGENFURT = "20101"
VILLACH = "20201"
SCOPE_N = 24
PACING_S = 2.0
OCR_MAX_PAGES = 80

# ---------------------------------------------------------------- OCR stage
_orig_extract = H.extract_text
OCR_LOG = []  # entries for the Gemeinde currently being harvested


def _alpha_ratio(text: str) -> float:
    chars = [c for c in text if not c.isspace()]
    if not chars:
        return 0.0
    return sum(c.isalpha() for c in chars) / len(chars)


def ocr_pdf_text(pdf_path: Path, pages: int) -> str:
    """pdftoppm 300 dpi -> tessroot tesseract deu, page by page."""
    prefix = OCR_TMP / pdf_path.stem.replace(" ", "_")[:80]
    subprocess.run(
        ["pdftoppm", "-r", "300", "-png", str(pdf_path), str(prefix)],
        capture_output=True, timeout=1800, check=True)
    parts = []
    for png in sorted(OCR_TMP.glob(prefix.name + "-*.png")):
        out = subprocess.run(
            ["tesseract", str(png), "stdout", "-l", "deu"],
            capture_output=True, timeout=600)
        parts.append(out.stdout.decode("utf-8", errors="replace"))
        png.unlink(missing_ok=True)
    return "\n".join(parts)


def extract_with_ocr(pdf_path):
    text, method, pages = _orig_extract(pdf_path)
    if len(text.strip()) >= 300:
        return text, method, pages
    entry = {"pdf": pdf_path.name, "digital_chars": len(text.strip())}
    if pages and pages > OCR_MAX_PAGES:
        entry.update({"ocr": "skipped_too_many_pages", "used": False})
        OCR_LOG.append(entry)
        return text, method, pages
    try:
        otext = ocr_pdf_text(pdf_path, pages)
    except Exception as e:  # OCR failure -> stay deferred, never force
        entry.update({"ocr": f"error: {e}", "used": False})
        OCR_LOG.append(entry)
        return text, method, pages
    entry["ocr_chars"] = len(otext.strip())
    entry["alpha_ratio"] = round(_alpha_ratio(otext), 3)
    if len(otext.strip()) >= 300 and entry["alpha_ratio"] >= 0.5:
        entry["used"] = True
        OCR_LOG.append(entry)
        return otext, "tesseract-deu", pages
    entry["used"] = False
    OCR_LOG.append(entry)
    return text, method, pages


H.extract_text = extract_with_ocr

# -------------------------------------------------------------------- state

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"started": now_iso(), "survey": {}, "scope": [],
            "gemeinden": {}, "villach_deferred": VILLACH}


def save_state(state: dict) -> None:
    state["updated"] = now_iso()
    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=1, ensure_ascii=False),
                   encoding="utf-8")
    tmp.replace(STATE_PATH)


# ------------------------------------------------------------------- survey

def survey(state: dict, registry: dict) -> None:
    todo = [g for g in registry
            if g not in PILOT_GKZ and g not in state["survey"]]
    if not todo:
        print(f"survey complete: {len(state['survey'])} Gemeinden", flush=True)
        return
    print(f"survey: {len(todo)} listings to fetch", flush=True)
    for i, gkz in enumerate(todo):
        cached = RAW / f"listing_{gkz}.html"
        pilot_cached = AT_PILOT / "raw" / f"listing_{gkz}.html"
        try:
            if cached.exists():
                html_text = cached.read_text(encoding="utf-8")
            elif pilot_cached.exists():
                html_text = pilot_cached.read_text(encoding="utf-8")
                cached.write_text(html_text, encoding="utf-8")
            else:
                html_text = H.fetch(f"{H.BASE}/Gemeindeverordnungen_Ktn/{gkz}")
                cached.write_text(html_text, encoding="utf-8")
                time.sleep(PACING_S)
            docs = H.parse_listing(gkz, html_text)
            state["survey"][gkz] = {"name": registry[gkz], "docs": len(docs)}
        except Exception as e:
            state["survey"][gkz] = {"name": registry[gkz], "docs": -1,
                                    "error": str(e)}
            print(f"survey FAIL {gkz}: {e}", flush=True)
        if (i + 1) % 10 == 0:
            save_state(state)
            print(f"survey {i + 1}/{len(todo)}", flush=True)
    save_state(state)
    print(f"survey done: {len(state['survey'])} Gemeinden", flush=True)


def build_scope(state: dict) -> None:
    if state["scope"]:
        return
    cands = [(v["docs"], g) for g, v in state["survey"].items()
             if v.get("docs", -1) >= 0 and g != VILLACH]
    cands.sort()
    picked = [g for _, g in cands[:SCOPE_N - 1]]
    if KLAGENFURT not in picked:
        picked.append(KLAGENFURT)
    else:
        picked = [g for _, g in cands[:SCOPE_N]]
    picked.sort(key=lambda g: (state["survey"][g]["docs"], g))
    state["scope"] = picked
    for g in picked:
        state["gemeinden"].setdefault(
            g, {"name": state["survey"][g]["name"],
                "docs_listed_survey": state["survey"][g]["docs"],
                "status": "pending"})
    save_state(state)
    print("scope: " + ", ".join(
        f"{g}({state['survey'][g]['docs']})" for g in picked), flush=True)


# ------------------------------------------------------------------ publish

sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
from dynamic_credentials import dynamic_credential_entry  # noqa: E402
from huggingface_hub import HfApi, hf_hub_download  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402


def make_api():
    entry = dynamic_credential_entry("custom.huggingface")
    token = entry.get("surrogate") if isinstance(entry, dict) else None
    if not token:
        raise RuntimeError("no surrogate from dynamic_credential_entry")
    return HfApi(token=token), token


def remote_files(api) -> dict:
    info = api.dataset_info(REPO, files_metadata=True)
    return {f.rfilename: f.size for f in (info.siblings or [])}


def write_coverage(state: dict) -> Path:
    lines = ["# Coverage — ipfs_austria_municipal_laws", "",
             "Carinthia (Kärnten) via the amtstafel.at hub "
             "(authentic Gemeindeverordnungen, 2017–present), "
             "world_municipal 19-column schema + sachgebiet.", "",
             "## Pilot (2026-10-13, incl. OCR merge 2026-10-14)", ""]
    for g in PILOT_GKZ:
        lines.append(f"- {g}: {PILOT_ROWS[g]} rows")
    lines += ["", "## Tranche 1 (2026-10-14)", ""]
    done = [(g, v) for g, v in state["gemeinden"].items()
            if v.get("status") in ("published_verified",
                                   "published_incomplete")]
    for g, v in sorted(done):
        note = "" if v["status"] == "published_verified" else \
            f" (incomplete: {v['stats']['download_failed']} downloads " \
            "outstanding, retry pending)"
        lines.append(f"- {g} {v['name']}: {v['rows']} rows "
                     f"({v['stats']['docs_listed']} docs listed){note}")
    lines += ["", f"Tranche-1 Gemeinden published: {len(done)} / "
              f"{len(state['scope'])} scoped. Villach (20201) deferred "
              "to its own tranche (listing ~1,130 docs).", ""]
    p = OUT / "coverage_report.md"
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


def publish_gemeinde(api, token, state: dict, gkz: str, name: str,
                     rows_local: int) -> dict:
    uploads = [(OUT / f"{gkz}_html.parquet", f"data/{gkz}_html.parquet"),
               (OUT / f"{gkz}_validation.json", f"data/{gkz}_validation.json")]
    # so the regenerated coverage report counts this Gemeinde too;
    # main() only persists state after verification succeeds.
    state["gemeinden"][gkz]["status"] = "published_verified" \
        if state["gemeinden"][gkz].get("stats", {}).get(
            "download_failed", 0) == 0 else "published_incomplete"
    existing = remote_files(api)
    prior_own = bool(state["gemeinden"][gkz].get("publish")) or \
        state["gemeinden"][gkz].get("status") in (
            "published_verified", "published_incomplete")
    for local, remote in uploads:
        if remote in existing:
            if existing[remote] == local.stat().st_size:
                print(f"  publish skip (same size): {remote}", flush=True)
                continue
            if prior_own:
                # Completion rebuild of our own tranche parquet
                # (cache-resume recovered previously failed downloads):
                # supersede in place, Spain-Murcia / AT-OCR precedent.
                print(f"  supersede own {remote} "
                      f"({existing[remote]} -> {local.stat().st_size} B)",
                      flush=True)
            else:
                raise RuntimeError(
                    f"remote {remote} exists with different size "
                    f"({existing[remote]} vs local {local.stat().st_size}) — "
                    "refusing to overwrite")
        api.upload_file(path_or_fileobj=str(local), path_in_repo=remote,
                        repo_id=REPO, repo_type="dataset")
        print(f"  uploaded {remote} ({local.stat().st_size} B)", flush=True)
    # remote verification: fresh listing + re-download + full validation
    after = remote_files(api)
    problems = []
    for local, remote in uploads:
        if after.get(remote) != local.stat().st_size:
            problems.append(f"size mismatch/missing: {remote}")
    path = hf_hub_download(REPO, f"data/{gkz}_html.parquet",
                           repo_type="dataset", token=token,
                           force_download=True)
    table = pq.read_table(path)
    if table.num_rows != rows_local:
        problems.append(f"remote rows {table.num_rows} != local {rows_local}")
    rep = H.wm_schema.validation_report(
        table, jurisdiction_id=gkz, jurisdiction_name=name, country="AT")
    if not rep["valid"]:
        problems.append(f"remote validation errors: {rep['errors']}")
    if problems:
        raise RuntimeError("; ".join(problems))
    # Coverage report (this program's own file) is refreshed LAST and
    # best-effort: an egress stall on this cosmetic upload hung a
    # driver for 13+ min on 2026-10-14 after the parquet commit had
    # already landed; it must never block a verified publish.
    try:
        cov = write_coverage(state)
        api.upload_file(path_or_fileobj=str(cov),
                        path_in_repo="coverage_report.md",
                        repo_id=REPO, repo_type="dataset")
    except Exception as e:
        print(f"  coverage upload deferred (best-effort): {e}", flush=True)
    return {"remote_rows": table.num_rows, "remote_files": len(after)}


# --------------------------------------------------------------------- main

def main():
    registry = {r["gkz"]: r["name"] for r in json.loads(
        (AT_PILOT / "raw" / "statistik_at_carinthia.json")
        .read_text(encoding="utf-8"))}
    state = load_state()
    save_state(state)
    survey(state, registry)
    build_scope(state)
    api, token = make_api()
    print(f"HF baseline: {len(remote_files(api))} remote files", flush=True)
    for gkz in state["scope"]:
        g = state["gemeinden"][gkz]
        if g.get("status") == "published_verified" and \
                g.get("stats", {}).get("download_failed", 0) == 0:
            print(f"skip {gkz} (published_verified, complete)", flush=True)
            continue
        name = registry[gkz]
        print(f"=== {gkz} {name} ===", flush=True)
        try:
            # Cache-resume retry (pilot precedent): transient SSL bursts
            # fail individual downloads; re-running the harvester only
            # re-fetches what is missing from the on-disk PDF cache.
            stats = None
            for attempt in range(1, 5):
                OCR_LOG.clear()
                time.sleep(PACING_S)
                stats = H.harvest_gemeinde(gkz, name)
                if stats["download_failed"] == 0 or attempt == 4:
                    break
                print(f"  retry {gkz}: {stats['download_failed']} downloads "
                      f"failed (attempt {attempt}/4), resuming in 30 s",
                      flush=True)
                time.sleep(30)
            g["stats"] = stats
            g["rows"] = stats["rows"]
            g["ocr"] = list(OCR_LOG)
            g["status"] = "harvested"
            save_state(state)
            if not stats["valid"]:
                g["status"] = "invalid"
                g["error"] = f"validation errors: {stats['errors']}"
                save_state(state)
                print(f"  INVALID {gkz}: {stats['errors']}", flush=True)
                continue
            res = publish_gemeinde(api, token, state, gkz, name,
                                   stats["rows"])
            g["publish"] = res
            g["status"] = "published_verified" \
                if stats["download_failed"] == 0 else "published_incomplete"
            g["published_at"] = now_iso()
            save_state(state)
            print(f"  PUBLISHED {gkz} ({g['status']}): {res}", flush=True)
        except Exception as e:
            g["status"] = "failed"
            g["error"] = f"{type(e).__name__}: {e}"
            g["traceback"] = traceback.format_exc(limit=5)
            save_state(state)
            print(f"  FAILED {gkz}: {e}", flush=True)
    done = [g for g in state["scope"]
            if state["gemeinden"][g]["status"] == "published_verified"]
    inc = [g for g in state["scope"]
           if state["gemeinden"][g]["status"] == "published_incomplete"]
    print(f"DRIVER DONE: {len(done)}/{len(state['scope'])} published_verified"
          f", {len(inc)} published_incomplete (rerun driver to complete)",
          flush=True)


if __name__ == "__main__":
    main()
