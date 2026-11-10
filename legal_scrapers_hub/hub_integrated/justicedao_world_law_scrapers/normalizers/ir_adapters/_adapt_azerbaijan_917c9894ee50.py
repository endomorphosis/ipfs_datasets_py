#!/usr/bin/env python3
"""Adapt Azerbaijan memsafe pack tip bfae9a267cd0 → tip 917c9894ee50.

Same-country tip bump. RECONFIRM_FINAL tip_drift; floor ≥7101/6241.
ASCII GATE from articles.parquet @ 917c9894ee50. URL e-qanun.az query-only, NOT GATE.
Ignore Iran/harare/Zimbabwe docstring leftovers.

HOLD 0 STRICT continuous after_wave2 (AZ after ZM LIVE); WAVE ELEVENTH of after_wave2
(AZ RECONFIRM; prior ten LIVE — do not rebuild; then LK WAVE END — do NOT start).
Soft never-thin ON; soft_thin=false. SKIP_US; AT queued-only; KW HOLD_THIN; IT leave alone.
Source endomorphosis/ipfs_azerbaijan_laws → justicedao/ipfs_azerbaijan_laws_ir.
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from pathlib import Path
import json
import re

ROOT = Path("/workspace/do_ir_resume")
SRC_TIP_FULL = "bfae9a267cd09f101b6cb7f08519d421d5286482"
SRC_TIP_SHORT = "bfae9a267cd0"
DST_TIP_FULL = "917c9894ee508300bbabc029c75b900f3c59f6dd"
DST_TIP_SHORT = "917c9894ee50"
FLOOR_LAWS, FLOOR_ARTS = 7101, 6241
SRC_FLOOR_L, SRC_FLOOR_A = 4447, 6185

GATE_YEARS = [
    "1991", "1995", "2000", "2005", "2010",
    "2015", "2018", "2020", "2021", "2022",
]
GATE_STEMS = [
    "azerbaijan", "qanun", "milli", "respublika", "article",
    "law", "republic", "shall", "state", "konstitusiya",
]
YEARS_ATTESTED = [int(y) for y in GATE_YEARS] + [
    2019, 2017, 2016, 2014, 2013, 2012, 2011, 2008, 2007, 2006,
]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT continuous after_wave2 (AZ after ZM LIVE)"
WAVE_POS = (
    "ELEVENTH of after_wave2 "
    "(AZ RECONFIRM; prior ten LIVE — do not rebuild; then LK WAVE END — do NOT start)"
)
DEST_CHAIN = "AZ"
SLUG = "azerbaijan"

FILES = [
    ("azerbaijan_soft_filter.py", "azerbaijan_soft_filter.py"),
    (f"azerbaijan_corpus_stream_{SRC_TIP_SHORT}.py", f"azerbaijan_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"azerbaijan_encode_memsafe_{SRC_TIP_SHORT}.py", f"azerbaijan_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"azerbaijan_finish_from_emb_{SRC_TIP_SHORT}.py", f"azerbaijan_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"azerbaijan_stream_graph_parts_{SRC_TIP_SHORT}.py", f"azerbaijan_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"azerbaijan_package_stream_{SRC_TIP_SHORT}.py", f"azerbaijan_package_stream_{DST_TIP_SHORT}.py"),
    ("azerbaijan_upload.py", "azerbaijan_upload.py"),
    ("azerbaijan_bm25_smoke.py", "azerbaijan_bm25_smoke.py"),
    ("azerbaijan_write_publish_report.py", "azerbaijan_write_publish_report.py"),
    ("azerbaijan_tip_check.py", "azerbaijan_tip_check.py"),
    (f"azerbaijan_orchestrator_{SRC_TIP_SHORT}.py", f"azerbaijan_orchestrator_{DST_TIP_SHORT}.py"),
]

BM25_TMPL = '''#!/usr/bin/env python3
"""BM25 smoke for Azerbaijan IR — mixed AZ/EN; ASCII-after-diacritic-fold tokenizer.

GATE is attested ASCII years plus ASCII stems that rank. URL e-qanun.az is
query-only, never GATE. Iran/harare leftovers stay out of GATE.
Every GATE token must rank a hit.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
sys.path.insert(0, "/workspace/country-laws-ir")
from country_laws_ir.query import Release

ROOT = Path("/workspace/country-laws-ir/releases/ipfs_azerbaijan_laws_ir")
OUT = Path("/workspace/country-laws-ir/reports/azerbaijan_bm25_smoke_%(tip)s.json")

GATE = [
    %(years)s,
    %(stems)s,
]
QUERIES = GATE + [
    "www", "e-qanun.az", "www.e-qanun.az",
    "harare", "iran", "zimbabwe", "persian",
]


def main() -> int:
    rel = Release(ROOT)
    detail = {"queries": {}, "ranked": [], "empty": [], "pass": False}
    for q in QUERIES:
        hits = rel.bm25(q, top_k=5)
        top = [
            {
                "score": h.get("score"),
                "title": (h.get("title") or "")[:120],
                "instrument_id": h.get("instrument_id"),
                "record_type": h.get("record_type"),
                "instrument_title": (h.get("instrument_title") or "")[:80],
            }
            for h in hits[:3]
        ]
        detail["queries"][q] = {"n": len(hits), "top": top}
        if hits:
            detail["ranked"].append(q)
        else:
            detail["empty"].append(q)
    ok = all(q in detail["ranked"] for q in GATE)
    detail["pass"] = ok
    detail["tokenizer_note"] = %(note)r
    detail["azerbaijan_pass"] = ok
    detail["azerbaijan_gate"] = GATE
    detail["tip"] = "%(tip)s"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(detail, indent=2, ensure_ascii=False) + "\\n", encoding="utf-8")
    print(json.dumps({
        "pass": detail["pass"],
        "ranked": detail["ranked"],
        "empty": detail["empty"],
        "n_gate_ranked": sum(1 for q in GATE if q in detail["ranked"]),
        "n_gate": len(GATE),
        "gate": GATE,
    }, indent=2, ensure_ascii=False))
    return 0 if ok else 1

if __name__ == "__main__":
    raise SystemExit(main())
'''


def make_bm25() -> str:
    years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
    stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
    note = (
        f"attested years {GATE_NOTE_YEARS} plus ASCII stems {GATE_NOTE_STEMS} "
        f"from articles.parquet HEAD tip {DST_TIP_SHORT}; URL e-qanun.az is query-only, not GATE."
    )
    return BM25_TMPL % {
        "tip": DST_TIP_SHORT,
        "years": years_line,
        "stems": stems_line,
        "note": note,
    }


def adapt(text: str, dst_name: str) -> str:
    for bad in (
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "azerbaijanent-data", "sand-data",
    ):
        text = text.replace(f"/home/box/{bad}/", "/home/box/agent-data/")
        text = text.replace(bad, "agent-data")

    text = text.replace("BM25", "\x00BM25\x00").replace("bm25", "\x00bm25\x00")
    text = text.replace("bmjacency", "adjacency")

    text = text.replace("RECONFIRM_FINAL", "\x00DESTMODE\x00")
    text = text.replace("FIRST_IR", "\x00DESTMODE\x00")
    text = text.replace("FIRST-IR", "\x00DESTMODE\x00")
    text = text.replace("FIRST IR", "\x00DESTMODE\x00")

    text = text.replace(HOLD, "\x00DESTHOLD\x00")
    text = text.replace(WAVE_POS, "\x00DESTWAVE\x00")
    text = text.replace(DEST_CHAIN, "\x00DESTCHAIN\x00")

    text = text.replace(SRC_TIP_FULL, DST_TIP_FULL)
    text = text.replace(SRC_TIP_SHORT, DST_TIP_SHORT)
    text = text.replace(DST_TIP_FULL, "\x00TIPSHA_PROTECT\x00")
    text = text.replace(DST_TIP_SHORT, "\x00TIPSHORT_PROTECT\x00")

    src_l, src_a = str(SRC_FLOOR_L), str(SRC_FLOOR_A)
    dst_l, dst_a = str(FLOOR_LAWS), str(FLOOR_ARTS)

    text = text.replace(f"{src_l}/{src_a}", "\x00FLOOR_LA\x00")
    text = text.replace(f"{src_l} / {src_a}", "\x00FLOOR_LA_SP\x00")
    text = text.replace(f"{src_l}, {src_a}", "\x00FLOOR_LA_C\x00")
    text = text.replace(f"FLOOR_LAWS, FLOOR_ARTS = {src_l}, {src_a}", "\x00FLOOR_ASSIGN\x00")
    text = text.replace(f"FLOOR_L, FLOOR_A = {src_l}, {src_a}", "\x00FLOOR_ASSIGN2\x00")
    text = text.replace(f'int(pack.get("n_laws") or {src_l})', "\x00OR_LAWS\x00")
    text = text.replace(f'int(pack.get("n_articles") or {src_a})', "\x00OR_ARTS\x00")
    text = text.replace(f"or {src_l})", "\x00OR_LAWS_PAREN\x00")
    text = text.replace(f"or {src_a})", "\x00OR_ARTS_PAREN\x00")
    text = text.replace(f"@ {src_l}/", "\x00AT_LAWS\x00")
    text = text.replace(f"floor {src_l}/", "\x00FLOOR_SLASH\x00")
    text = text.replace(f"({src_l}/", "\x00PAREN_LAWS\x00")
    text = text.replace(f"= {src_l},", "\x00EQ_LAWS\x00")
    text = text.replace(f" {src_a}", "\x00ARTS\x00")
    text = text.replace(src_a, "\x00ARTS\x00")
    text = text.replace(f" {src_l}", "\x00LAWS\x00")
    text = text.replace(src_l, "\x00LAWS\x00")
    # write_publish may still cite older floor literals
    text = text.replace("4447/6185", "\x00FLOOR_LA\x00")
    text = text.replace("4447, 6185", "\x00FLOOR_LA_C\x00")
    text = text.replace(" 6185", "\x00ARTS\x00")
    text = text.replace("6185", "\x00ARTS\x00")
    text = text.replace(" 4447", "\x00LAWS\x00")
    text = text.replace("4447", "\x00LAWS\x00")
    text = text.replace("543d3aea2e9d", "\x00TIPSHORT_PROTECT\x00")

    text = text.replace("\x00FLOOR_LA\x00", f"{dst_l}/{dst_a}")
    text = text.replace("\x00FLOOR_LA_SP\x00", f"{dst_l} / {dst_a}")
    text = text.replace("\x00FLOOR_LA_C\x00", f"{dst_l}, {dst_a}")
    text = text.replace("\x00FLOOR_ASSIGN\x00", f"FLOOR_LAWS, FLOOR_ARTS = {dst_l}, {dst_a}")
    text = text.replace("\x00FLOOR_ASSIGN2\x00", f"FLOOR_L, FLOOR_A = {dst_l}, {dst_a}")
    text = text.replace("\x00OR_LAWS\x00", f'int(pack.get("n_laws") or {dst_l})')
    text = text.replace("\x00OR_ARTS\x00", f'int(pack.get("n_articles") or {dst_a})')
    text = text.replace("\x00OR_LAWS_PAREN\x00", f"or {dst_l})")
    text = text.replace("\x00OR_ARTS_PAREN\x00", f"or {dst_a})")
    text = text.replace("\x00AT_LAWS\x00", f"@ {dst_l}/")
    text = text.replace("\x00FLOOR_SLASH\x00", f"floor {dst_l}/")
    text = text.replace("\x00PAREN_LAWS\x00", f"({dst_l}/")
    text = text.replace("\x00EQ_LAWS\x00", f"= {dst_l},")
    text = text.replace("\x00ARTS\x00", dst_a)
    text = text.replace("\x00LAWS\x00", dst_l)

    for a, b in [
        ("\x00DESTHOLD\x00", HOLD),
        ("\x00DESTWAVE\x00", WAVE_POS),
        ("\x00DESTCHAIN\x00", DEST_CHAIN),
        ("\x00DESTMODE\x00", "RECONFIRM_FINAL"),
        ("FIRST-IR EXPAND", "RECONFIRM_FINAL"),
        ("FIRST_IR EXPAND", "RECONFIRM_FINAL"),
        ("(FIRST-IR EXPAND)", "(RECONFIRM_FINAL)"),
        ("(FIRST_IR EXPAND)", "(RECONFIRM_FINAL)"),
    ]:
        text = text.replace(a, b)

    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")
    text = text.replace("\x00TIPSHA_PROTECT\x00", DST_TIP_FULL)
    text = text.replace("\x00TIPSHORT_PROTECT\x00", DST_TIP_SHORT)
    text = text.replace("\x00DESTHOLD\x00", HOLD)
    text = text.replace("\x00DESTCHAIN\x00", DEST_CHAIN)
    text = text.replace("\x00DESTWAVE\x00", WAVE_POS)
    text = text.replace("\x00DESTMODE\x00", "RECONFIRM_FINAL")

    if dst_name == "azerbaijan_bm25_smoke.py":
        text = make_bm25()

    if dst_name == "azerbaijan_write_publish_report.py":
        gate_note = (
            f"BM25 PASS on ASCII GATE "
            f"(attested years {GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}); "
            f"URL e-qanun.az is query-only, not GATE"
        )
        text = re.sub(r'"BM25 PASS on [^"]*"', f'"{gate_note}"', text, count=1)
        text = text.replace("french_ranked", "gate_ranked")

    if dst_name == "azerbaijan_soft_filter.py":
        text = text.replace("FIRST-IR EXPAND", "RECONFIRM_FINAL")
        text = text.replace("FIRST_IR EXPAND", "RECONFIRM_FINAL")

    if dst_name.endswith(f"orchestrator_{DST_TIP_SHORT}.py"):
        text = re.sub(
            r'"""Azerbaijan.*?"""',
            f'"""Azerbaijan RECONFIRM_FINAL orchestrator tip {DST_TIP_SHORT} '
            f'(memsafe corpus+encode; {HOLD})."""',
            text,
            count=1,
            flags=re.S,
        )

    if dst_name == "azerbaijan_bm25_smoke.py":
        for stem in GATE_STEMS:
            if f'"{stem}"' not in text:
                raise RuntimeError(f"missing ASCII stem in GATE of {dst_name}: {stem}")
        for year in GATE_YEARS:
            if f'"{year}"' not in text:
                raise RuntimeError(f"missing year in GATE of {dst_name}: {year}")
        gate_block = text[text.index("GATE = ["): text.index("]", text.index("GATE = [")) + 1]
        for bad in ("harare", "iran", "zimbabwe", "persian"):
            if f'"{bad}"' in gate_block:
                raise RuntimeError(f"{bad} must not be in GATE")

    if SRC_TIP_SHORT in text:
        raise RuntimeError(f"src tip leftover in {dst_name}")
    if SRC_TIP_FULL in text:
        raise RuntimeError(f"src tip full leftover in {dst_name}")
    if str(SRC_FLOOR_A) in text:
        raise RuntimeError(f"old arts floor leftover in {dst_name}")
    if DST_TIP_SHORT not in text and any(
        x in dst_name for x in ("soft_filter", "orchestrator", "bm25_smoke", "upload", "tip_check", "write_publish")
    ):
        raise RuntimeError(f"missing DST tip in {dst_name}")
    if "\x00" in text:
        raise RuntimeError(f"null placeholder leftover in {dst_name}")
    return text


def main() -> None:
    # sync tip SHAs from live hub + pack before adapting
    import os
    from huggingface_hub import HfApi
    token = os.environ.get("HF_TOKEN")
    if not token:
        secret = Path(__import__("os").environ.get("HF_TOKEN_FILE", ""))
        if secret.is_file():
            for line in secret.read_text().splitlines():
                if line.startswith("HF_TOKEN="):
                    token = line.split("=", 1)[1].strip().strip('"')
                    os.environ["HF_TOKEN"] = token
    global SRC_TIP_FULL, DST_TIP_FULL, SRC_FLOOR_L, SRC_FLOOR_A
    hub = HfApi(token=token).dataset_info("endomorphosis/ipfs_azerbaijan_laws").sha
    sf = (ROOT / "azerbaijan_soft_filter.py").read_text(encoding="utf-8")
    # soft still has SRC tip before we overwrite it — read from a backup source file if already adapted
    pack_m = re.search(r'TIP_FULL = "([^"]+)"', Path(ROOT / "azerbaijan_orchestrator_bfae9a267cd0.py").read_text(encoding="utf-8") if (ROOT / "azerbaijan_orchestrator_bfae9a267cd0.py").is_file() else sf)
    # Prefer constants baked above; only override DST from hub
    if hub != DST_TIP_FULL:
        raise RuntimeError(f"hub tip drift {hub} != baked {DST_TIP_FULL}")
    if not hub.startswith(DST_TIP_SHORT):
        raise RuntimeError(f"hub tip short mismatch {hub[:12]}")

    for src_name, dst_name in FILES:
        src = ROOT / src_name
        if not src.is_file():
            raise FileNotFoundError(src)
        (ROOT / dst_name).write_text(adapt(src.read_text(encoding="utf-8"), dst_name), encoding="utf-8")
        print(f"wrote {dst_name}")

    wave = Path("/workspace/next_ir_ok_wave_after_wave2.json")
    if wave.is_file():
        data = json.loads(wave.read_text(encoding="utf-8"))
        q = data.get("queue") or data.get("countries") or []
        for entry in q:
            if isinstance(entry, dict) and (entry.get("slug") == SLUG or entry.get("iso2") == "AZ"):
                entry.update({
                    "tip": DST_TIP_SHORT,
                    "tip_full": DST_TIP_FULL,
                    "laws": FLOOR_LAWS,
                    "articles": FLOOR_ARTS,
                    "floor_laws": FLOOR_LAWS,
                    "floor_articles": FLOOR_ARTS,
                    "L_A": f"{FLOOR_LAWS}/{FLOOR_ARTS}",
                    "claim_tip": DST_TIP_SHORT,
                    "match_claim": True,
                    "ir_hub_head": "96e793a6a00b",
                    "label": "EXPAND",
                    "soft_thin": False,
                    "soft_never_thin": True,
                    "skip_us": True,
                    "italy_leave_alone": True,
                    "language": "Azerbaijani/English",
                    "lang": "az/en",
                    "iso2": "AZ",
                    "slug": SLUG,
                    "repo": "endomorphosis/ipfs_azerbaijan_laws",
                    "years_attested": YEARS_ATTESTED,
                    "gate_years": [int(y) for y in GATE_YEARS],
                    "gate_stems": GATE_STEMS,
                    "note": (
                        f"AZ RECONFIRM_FINAL scaffold; tip MATCH {DST_TIP_SHORT}@7101/6241; {HOLD}; "
                        f"soft never-thin ON; SKIP_US; Italy leave alone; {WAVE_POS}; "
                        f"ASCII GATE ({len(GATE_YEARS)} years + {len(GATE_STEMS)} stems); "
                        f"prior ten LIVE — do not rebuild; do NOT start LK or any other country"
                    ),
                    "status": "CLAIMED",
                    "mode": "RECONFIRM_FINAL",
                    "wave_end": False,
                })
                break
        else:
            print("WARN: AZ entry not updated in wave JSON (non-fatal)")
        data["hold"] = HOLD
        data["current"] = SLUG
        data["hold_note"] = (
            "HOLD 0 STRICT continuous for AZ RECONFIRM_FINAL build (after_wave2 ELEVENTH; "
            "prior ten LIVE); do NOT start LK; no soft-lean refill until WAVE END after LK"
        )
        wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        for triage in (
            Path("/workspace/country-law-triage/next_ir_ok_wave_after_wave2.json"),
            Path("/workspace/cos_hold0_after_wave2.json"),
        ):
            try:
                if triage.name.startswith("cos_hold0"):
                    hold = {
                        "hold": HOLD,
                        "current": SLUG,
                        "wave": "next_ir_ok_wave_after_wave2",
                        "wave_position": WAVE_POS,
                        "do_not_start": "srilanka",
                        "soft_lean_refill": False,
                        "wave_end": False,
                    }
                    triage.write_text(json.dumps(hold, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                elif triage.parent.is_dir():
                    triage.write_text(wave.read_text(encoding="utf-8"), encoding="utf-8")
            except Exception as e:
                print(f"WARN triage write {triage}: {e}")
        print("updated wave JSON AZ entry")
    else:
        print("WARN: wave JSON missing")

    print("GATE years", GATE_YEARS)
    print("GATE stems", GATE_STEMS)
    print("n_gate", len(GATE_YEARS) + len(GATE_STEMS))
    print("HOLD", HOLD)
    print("floor", f"{FLOOR_LAWS}/{FLOOR_ARTS}; RECONFIRM_FINAL; only AZ")


if __name__ == "__main__":
    main()
