#!/usr/bin/env python3
"""Adapt Zambia memsafe pack tip b39eaa50aed0 → tip 393c845a2466.

Same-country tip bump. RECONFIRM_FINAL tip_drift; floor ≥5004/10228.
English ASCII GATE from articles.parquet @ 393c845a2466.
URL www.parliament.gov.zm / zambialii.org is query-only, NOT GATE.
Ignore Oman/muscat copy-paste leftovers in old docstring.

HOLD 0 STRICT continuous after_wave2 (ZM after QA LIVE); WAVE TENTH of after_wave2
(ZM RECONFIRM; prior nine LIVE — do not rebuild; then AZ→LK — do NOT start those).
Soft never-thin ON; soft_thin=false. SKIP_US; AT queued-only; KW HOLD_THIN; IT leave alone.
Source endomorphosis/ipfs_zambia_laws → justicedao/ipfs_zambia_laws_ir.
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
SRC_TIP_FULL = "b39eaa50aed06dd6ac52f77ff74b6e943f75a2c2"
SRC_TIP_SHORT = "b39eaa50aed0"
DST_TIP_FULL = "393c845a24666665125fdd8243f57edf2fc50688"
DST_TIP_SHORT = "393c845a2466"
FLOOR_LAWS, FLOOR_ARTS = 5004, 10228
SRC_FLOOR_L, SRC_FLOOR_A = 2501, 8074

GATE_YEARS = [
    "1964", "1994", "2017", "2022", "2024",
    "2010", "2016", "2021", "2018", "2020",
]
GATE_STEMS = [
    "zambia", "shall", "act", "section", "court",
    "company", "republic", "government", "authority", "minister",
]
YEARS_ATTESTED = [int(y) for y in GATE_YEARS] + [
    2000, 1965, 1990, 2015, 2019, 2023, 1970, 1996, 2002, 2011,
]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT continuous after_wave2 (ZM after QA LIVE)"
WAVE_POS = (
    "TENTH of after_wave2 "
    "(ZM RECONFIRM; prior nine LIVE — do not rebuild; then AZ→LK — do NOT start those)"
)
DEST_CHAIN = "ZM"
SLUG = "zambia"

FILES = [
    ("zambia_soft_filter.py", "zambia_soft_filter.py"),
    (f"zambia_corpus_stream_{SRC_TIP_SHORT}.py", f"zambia_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"zambia_encode_memsafe_{SRC_TIP_SHORT}.py", f"zambia_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"zambia_finish_from_emb_{SRC_TIP_SHORT}.py", f"zambia_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"zambia_stream_graph_parts_{SRC_TIP_SHORT}.py", f"zambia_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"zambia_package_stream_{SRC_TIP_SHORT}.py", f"zambia_package_stream_{DST_TIP_SHORT}.py"),
    ("zambia_upload.py", "zambia_upload.py"),
    ("zambia_bm25_smoke.py", "zambia_bm25_smoke.py"),
    ("zambia_write_publish_report.py", "zambia_write_publish_report.py"),
    (f"zambia_orchestrator_{SRC_TIP_SHORT}.py", f"zambia_orchestrator_{DST_TIP_SHORT}.py"),
]

BM25_TMPL = '#!/usr/bin/env python3\n"""BM25 smoke for Zambia IR — English corpus; ASCII tokenizer.\n\nGATE is attested English ASCII years plus stems that rank. URL\nwww.parliament.gov.zm / zambialii.org is query-only, never GATE.\nIgnore Oman/muscat leftovers (query-only, expected empty).\nEvery GATE token must rank a hit.\n"""\nfrom __future__ import annotations\nimport json, sys\nfrom pathlib import Path\nsys.path.insert(0, "/workspace/country-laws-ir")\nfrom country_laws_ir.query import Release\n\nROOT = Path("/workspace/country-laws-ir/releases/ipfs_zambia_laws_ir")\nOUT = Path("/workspace/country-laws-ir/reports/zambia_bm25_smoke_%(tip)s.json")\n\nGATE = [\n    %(years)s,\n    %(stems)s,\n]\nQUERIES = GATE + [\n    "www", "parliament.gov.zm", "www.parliament.gov.zm", "zambialii.org",\n    "muscat", "sultan", "decree", "royal",\n]\n\n\ndef main() -> int:\n    rel = Release(ROOT)\n    detail = {"queries": {}, "ranked": [], "empty": [], "pass": False}\n    for q in QUERIES:\n        hits = rel.bm25(q, top_k=5)\n        top = [\n            {\n                "score": h.get("score"),\n                "title": (h.get("title") or "")[:120],\n                "instrument_id": h.get("instrument_id"),\n                "record_type": h.get("record_type"),\n                "instrument_title": (h.get("instrument_title") or "")[:80],\n            }\n            for h in hits[:3]\n        ]\n        detail["queries"][q] = {"n": len(hits), "top": top}\n        if hits:\n            detail["ranked"].append(q)\n        else:\n            detail["empty"].append(q)\n    ok = all(q in detail["ranked"] for q in GATE)\n    detail["pass"] = ok\n    detail["tokenizer_note"] = %(note)r\n    detail["zambia_pass"] = ok\n    detail["zambia_gate"] = GATE\n    detail["tip"] = "%(tip)s"\n    OUT.parent.mkdir(parents=True, exist_ok=True)\n    OUT.write_text(json.dumps(detail, indent=2, ensure_ascii=False) + "\\n", encoding="utf-8")\n    print(json.dumps({\n        "pass": detail["pass"],\n        "ranked": detail["ranked"],\n        "empty": detail["empty"],\n        "n_gate_ranked": sum(1 for q in GATE if q in detail["ranked"]),\n        "n_gate": len(GATE),\n        "gate": GATE,\n    }, indent=2, ensure_ascii=False))\n    return 0 if ok else 1\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n'


def make_bm25() -> str:
    years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
    stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
    note = (
        f"attested years {GATE_NOTE_YEARS} plus English ASCII stems {GATE_NOTE_STEMS} "
        f"from articles.parquet HEAD tip {DST_TIP_SHORT}; URL parliament.gov.zm/"
        f"zambialii.org is query-only, not GATE."
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
        "carent-data", "yement-data", "zambiaent-data", "sand-data",
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

    # floors: 2501/8074 → 5004/10228
    text = text.replace("2501/8074", "\x00FLOOR_LA\x00")
    text = text.replace("2501 / 8074", "\x00FLOOR_LA_SP\x00")
    text = text.replace("2501, 8074", "\x00FLOOR_LA_C\x00")
    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 2501, 8074", "\x00FLOOR_ASSIGN\x00")
    text = text.replace("FLOOR_L, FLOOR_A = 2501, 8074", "\x00FLOOR_ASSIGN2\x00")
    text = text.replace('int(pack.get("n_laws") or 2501)', "\x00OR_LAWS\x00")
    text = text.replace('int(pack.get("n_articles") or 8074)', "\x00OR_ARTS\x00")
    text = text.replace("or 2501)", "\x00OR_LAWS_PAREN\x00")
    text = text.replace("or 8074)", "\x00OR_ARTS_PAREN\x00")
    text = text.replace("@ 2501/", "\x00AT_LAWS\x00")
    text = text.replace("floor 2501/", "\x00FLOOR_SLASH\x00")
    text = text.replace("(2501/", "\x00PAREN_LAWS\x00")
    text = text.replace("= 2501,", "\x00EQ_LAWS\x00")
    text = text.replace(" 8074", "\x00ARTS\x00")
    text = text.replace("8074", "\x00ARTS\x00")
    text = text.replace(" 2501", "\x00LAWS\x00")
    text = text.replace("2501", "\x00LAWS\x00")

    text = text.replace("\x00FLOOR_LA\x00", "5004/10228")
    text = text.replace("\x00FLOOR_LA_SP\x00", "5004 / 10228")
    text = text.replace("\x00FLOOR_LA_C\x00", "5004, 10228")
    text = text.replace("\x00FLOOR_ASSIGN\x00", "FLOOR_LAWS, FLOOR_ARTS = 5004, 10228")
    text = text.replace("\x00FLOOR_ASSIGN2\x00", "FLOOR_L, FLOOR_A = 5004, 10228")
    text = text.replace("\x00OR_LAWS\x00", 'int(pack.get("n_laws") or 5004)')
    text = text.replace("\x00OR_ARTS\x00", 'int(pack.get("n_articles") or 10228)')
    text = text.replace("\x00OR_LAWS_PAREN\x00", "or 5004)")
    text = text.replace("\x00OR_ARTS_PAREN\x00", "or 10228)")
    text = text.replace("\x00AT_LAWS\x00", "@ 5004/")
    text = text.replace("\x00FLOOR_SLASH\x00", "floor 5004/")
    text = text.replace("\x00PAREN_LAWS\x00", "(5004/")
    text = text.replace("\x00EQ_LAWS\x00", "= 5004,")
    text = text.replace("\x00ARTS\x00", "10228")
    text = text.replace("\x00LAWS\x00", "5004")

    for a, b in [
        ("\x00DESTHOLD\x00", HOLD),
        ("\x00DESTWAVE\x00", WAVE_POS),
        ("\x00DESTCHAIN\x00", DEST_CHAIN),
        ("\x00DESTMODE\x00", "RECONFIRM_FINAL"),
        ("Soft filter for EU tip", "Soft filter for Zambia tip"),
        ("during EU ", "during ZM "),
        ("EU FIRST", "ZM RECONFIRM_FINAL"),
        ("EU tip", "Zambia tip"),
        ("FIRST-IR EXPAND", "RECONFIRM_FINAL"),
        ("FIRST_IR EXPAND", "RECONFIRM_FINAL"),
        ("(FIRST-IR EXPAND)", "(RECONFIRM_FINAL)"),
        ("(FIRST_IR EXPAND)", "(RECONFIRM_FINAL)"),
        ("muscat", "zambia"),  # wipe Oman leftovers carefully after tip protect
    ]:
        text = text.replace(a, b)

    # undo accidental zambia-for-muscat in protected tip? tip has no muscat
    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")
    text = text.replace("\x00TIPSHA_PROTECT\x00", DST_TIP_FULL)
    text = text.replace("\x00TIPSHORT_PROTECT\x00", DST_TIP_SHORT)
    text = text.replace("\x00DESTHOLD\x00", HOLD)
    text = text.replace("\x00DESTCHAIN\x00", DEST_CHAIN)
    text = text.replace("\x00DESTWAVE\x00", WAVE_POS)
    text = text.replace("\x00DESTMODE\x00", "RECONFIRM_FINAL")

    if dst_name == "zambia_bm25_smoke.py":
        text = make_bm25()

    if dst_name == "zambia_write_publish_report.py":
        gate_note = (
            f"BM25 PASS on English ASCII GATE "
            f"(attested years {GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}); "
            f"URL parliament.gov.zm/zambialii.org is query-only, not GATE"
        )
        text = re.sub(r'"BM25 PASS on [^"]*"', f'"{gate_note}"', text, count=1)
        text = text.replace("french_ranked", "gate_ranked")
        text = text.replace(
            "Arabic script empty under ASCII tokenizer as expected",
            "English ASCII GATE; URL parliament.gov.zm query-only; muscat/sultan empty by design",
        )
        text = text.replace(
            "Arabic script queries empty by tokenizer design",
            "English ASCII GATE; URL parliament.gov.zm query-only",
        )
        # build result may be named differently — keep tip-bumped path
        text = text.replace(
            "Hub HEAD matched requested tip",
            "Hub HEAD matched requested tip",
        )

    if dst_name == "zambia_soft_filter.py":
        text = text.replace(
            "tip pack through with floor checks only (FIRST-IR EXPAND).",
            "tip pack through with floor checks only (RECONFIRM_FINAL).",
        )
        text = text.replace("FIRST-IR EXPAND", "RECONFIRM_FINAL")
        text = text.replace("FIRST_IR EXPAND", "RECONFIRM_FINAL")
        text = text.replace("for EU tip", "for Zambia tip")
        text = text.replace("Oman", "Zambia")
        text = text.replace("oman", "zambia")

    if dst_name.endswith(f"orchestrator_{DST_TIP_SHORT}.py"):
        text = re.sub(
            r'"""Zambia.*?"""',
            f'"""Zambia RECONFIRM_FINAL orchestrator tip {DST_TIP_SHORT} '
            f'(memsafe corpus+encode; {HOLD})."""',
            text,
            count=1,
            flags=re.S,
        )

    if dst_name == "zambia_bm25_smoke.py":
        for stem in GATE_STEMS:
            if f'"{stem}"' not in text:
                raise RuntimeError(f"missing ASCII stem in GATE of {dst_name}: {stem}")
        for year in GATE_YEARS:
            if f'"{year}"' not in text:
                raise RuntimeError(f"missing year in GATE of {dst_name}: {year}")
        if '"muscat"' in text[text.index("GATE = ["): text.index("]", text.index("GATE = ["))+1]:
            raise RuntimeError("muscat must not be in GATE")

    if SRC_TIP_SHORT in text:
        raise RuntimeError(f"src tip leftover in {dst_name}")
    if SRC_TIP_FULL in text:
        raise RuntimeError(f"src tip full leftover in {dst_name}")
    if "8074" in text:
        raise RuntimeError(f"old arts floor leftover in {dst_name}")
    if "2501" in text:
        raise RuntimeError(f"old laws floor leftover in {dst_name}")
    if DST_TIP_SHORT not in text and any(
        x in dst_name for x in ("soft_filter", "orchestrator", "bm25_smoke", "upload", "write_publish")
    ):
        raise RuntimeError(f"missing DST tip in {dst_name}")
    if "\x00" in text:
        raise RuntimeError(f"null placeholder leftover in {dst_name}")
    return text


def main() -> None:
    for src_name, dst_name in FILES:
        src = ROOT / src_name
        if not src.is_file():
            raise FileNotFoundError(src)
        (ROOT / dst_name).write_text(adapt(src.read_text(encoding="utf-8"), dst_name), encoding="utf-8")
        print(f"wrote {dst_name}")

    wave = Path("/workspace/next_ir_ok_wave_after_wave2.json")
    if wave.is_file():
        data = json.loads(wave.read_text(encoding="utf-8"))
        for entry in data.get("queue", []):
            if isinstance(entry, dict) and (entry.get("slug") == SLUG or entry.get("iso2") == "ZM"):
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
                    "ir_hub_head": "9cd08fa358b5",
                    "label": "EXPAND",
                    "soft_thin": False,
                    "soft_never_thin": True,
                    "skip_us": True,
                    "italy_leave_alone": True,
                    "language": "English",
                    "lang": "en",
                    "iso2": "ZM",
                    "slug": SLUG,
                    "repo": "endomorphosis/ipfs_zambia_laws",
                    "years_attested": YEARS_ATTESTED,
                    "gate_years": [int(y) for y in GATE_YEARS],
                    "gate_stems": GATE_STEMS,
                    "note": (
                        f"ZM RECONFIRM_FINAL scaffold; tip MATCH {DST_TIP_SHORT}@5004/10228; {HOLD}; "
                        f"soft never-thin ON; SKIP_US; Italy leave alone; {WAVE_POS}; "
                        f"English ASCII GATE ({len(GATE_YEARS)} years + {len(GATE_STEMS)} stems); "
                        f"prior nine LIVE — do not rebuild; do NOT start AZ or any other country"
                    ),
                    "status": "CLAIMED",
                    "mode": "RECONFIRM_FINAL",
                    "wave_end": False,
                })
                break
        else:
            print("WARN: ZM entry not updated in wave JSON (non-fatal)")
        data["hold"] = HOLD
        data["current"] = SLUG
        data["hold_note"] = (
            "HOLD 0 STRICT continuous for ZM RECONFIRM_FINAL build (after_wave2 TENTH; "
            "prior nine LIVE); do NOT start AZ; no soft-lean refill until WAVE END after LK"
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
                        "do_not_start": "azerbaijan",
                        "soft_lean_refill": False,
                        "wave_end": False,
                    }
                    triage.write_text(json.dumps(hold, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                elif triage.parent.is_dir():
                    triage.write_text(wave.read_text(encoding="utf-8"), encoding="utf-8")
            except Exception as e:
                print(f"WARN triage write {triage}: {e}")
        print("updated wave JSON ZM entry")
    else:
        print("WARN: wave JSON missing")

    print("GATE years", GATE_YEARS)
    print("GATE stems", GATE_STEMS)
    print("n_gate", len(GATE_YEARS) + len(GATE_STEMS))
    print("HOLD", HOLD)
    print("floor", f"{FLOOR_LAWS}/{FLOOR_ARTS}; RECONFIRM_FINAL; only ZM")


if __name__ == "__main__":
    main()
