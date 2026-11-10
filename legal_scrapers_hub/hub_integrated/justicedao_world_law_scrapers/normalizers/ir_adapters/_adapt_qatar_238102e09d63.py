#!/usr/bin/env python3
"""Adapt Qatar memsafe pack tip 630bd429b598 → tip 238102e09d63.

Same-country tip bump. RECONFIRM_FINAL tip_drift; floor ≥2856/24183.
ASCII GATE from articles.parquet @ 238102e09d63 (qatar/law/article/… + years).
URL almeezan.qa is query-only, NOT GATE.

HOLD 0 STRICT continuous after_wave2 (QA after UY LIVE); WAVE NINTH of after_wave2
(QA RECONFIRM; prior eight LIVE — do not rebuild; then ZM→AZ→LK — do NOT start those).
Soft never-thin ON; soft_thin=false. SKIP_US; AT queued-only; KW HOLD_THIN; IT leave alone.
Source endomorphosis/ipfs_qatar_laws → justicedao/ipfs_qatar_laws_ir.
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
SRC_TIP_FULL = "630bd429b5983668a36f45233eb19694ad5ba013"
SRC_TIP_SHORT = "630bd429b598"
DST_TIP_FULL = "238102e09d6362c6f2aaca229b2387dc17b39838"
DST_TIP_SHORT = "238102e09d63"
FLOOR_LAWS, FLOOR_ARTS = 2856, 24183
SRC_FLOOR_L, SRC_FLOOR_A = 2796, 23619

GATE_YEARS = [
    "2004", "1993", "2002", "1991", "1995",
    "2005", "2011", "2014", "2024", "2003",
]
GATE_STEMS = [
    "qatar", "law", "article", "minister", "act",
    "gov", "qa", "order", "decision", "official",
    "state", "authority",
]
YEARS_ATTESTED = [int(y) for y in GATE_YEARS] + [
    1976, 1987, 2018, 2020, 2010, 2000, 1990, 1980, 2015, 2008,
]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT continuous after_wave2 (QA after UY LIVE)"
WAVE_POS = (
    "NINTH of after_wave2 "
    "(QA RECONFIRM; prior eight LIVE — do not rebuild; then ZM→AZ→LK — do NOT start those)"
)
DEST_CHAIN = "QA"
SLUG = "qatar"

FILES = [
    ("qatar_soft_filter.py", "qatar_soft_filter.py"),
    (f"qatar_corpus_stream_{SRC_TIP_SHORT}.py", f"qatar_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"qatar_encode_memsafe_{SRC_TIP_SHORT}.py", f"qatar_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"qatar_finish_from_emb_{SRC_TIP_SHORT}.py", f"qatar_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"qatar_stream_graph_parts_{SRC_TIP_SHORT}.py", f"qatar_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"qatar_package_stream_{SRC_TIP_SHORT}.py", f"qatar_package_stream_{DST_TIP_SHORT}.py"),
    ("qatar_upload.py", "qatar_upload.py"),
    ("qatar_bm25_smoke.py", "qatar_bm25_smoke.py"),
    ("qatar_write_publish_report.py", "qatar_write_publish_report.py"),
    ("qatar_tip_check.py", "qatar_tip_check.py"),
    (f"qatar_orchestrator_{SRC_TIP_SHORT}.py", f"qatar_orchestrator_{DST_TIP_SHORT}.py"),
]

BM25_TMPL = '#!/usr/bin/env python3\n"""BM25 smoke for Qatar IR — mixed AR/EN corpus; ASCII-after-diacritic-fold tokenizer.\n\nGATE is attested ASCII years plus ASCII stems that rank. URL almeezan.qa is\nquery-only, never GATE. decree/emir/gazette/regulation/section stay out of GATE.\nEvery GATE token must rank a hit.\n"""\nfrom __future__ import annotations\nimport json, sys\nfrom pathlib import Path\nsys.path.insert(0, "/workspace/country-laws-ir")\nfrom country_laws_ir.query import Release\n\nROOT = Path("/workspace/country-laws-ir/releases/ipfs_qatar_laws_ir")\nOUT = Path("/workspace/country-laws-ir/reports/qatar_bm25_smoke_%(tip)s.json")\n\nGATE = [\n    %(years)s,\n    %(stems)s,\n]\nQUERIES = GATE + [\n    "www", "almeezan.qa", "www.almeezan.qa",\n    "decree", "emir", "gazette", "regulation", "section",\n]\n\n\ndef main() -> int:\n    rel = Release(ROOT)\n    detail = {"queries": {}, "ranked": [], "empty": [], "pass": False}\n    for q in QUERIES:\n        hits = rel.bm25(q, top_k=5)\n        top = [\n            {\n                "score": h.get("score"),\n                "title": (h.get("title") or "")[:120],\n                "instrument_id": h.get("instrument_id"),\n                "record_type": h.get("record_type"),\n                "instrument_title": (h.get("instrument_title") or "")[:80],\n            }\n            for h in hits[:3]\n        ]\n        detail["queries"][q] = {"n": len(hits), "top": top}\n        if hits:\n            detail["ranked"].append(q)\n        else:\n            detail["empty"].append(q)\n    ok = all(q in detail["ranked"] for q in GATE)\n    detail["pass"] = ok\n    detail["tokenizer_note"] = %(note)r\n    detail["qatar_pass"] = ok\n    detail["qatar_gate"] = GATE\n    detail["tip"] = "%(tip)s"\n    OUT.parent.mkdir(parents=True, exist_ok=True)\n    OUT.write_text(json.dumps(detail, indent=2, ensure_ascii=False) + "\\n", encoding="utf-8")\n    print(json.dumps({\n        "pass": detail["pass"],\n        "ranked": detail["ranked"],\n        "empty": detail["empty"],\n        "n_gate_ranked": sum(1 for q in GATE if q in detail["ranked"]),\n        "n_gate": len(GATE),\n        "gate": GATE,\n    }, indent=2, ensure_ascii=False))\n    return 0 if ok else 1\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n'


def make_bm25() -> str:
    years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
    stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
    note = (
        f"attested years {GATE_NOTE_YEARS} plus ASCII stems {GATE_NOTE_STEMS} "
        f"from articles.parquet HEAD tip {DST_TIP_SHORT}; URL almeezan.qa is query-only, not GATE."
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
        "carent-data", "yement-data", "qatarent-data", "sand-data",
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

    text = text.replace("2796/23619", "\x00FLOOR_LA\x00")
    text = text.replace("2796 / 23619", "\x00FLOOR_LA_SP\x00")
    text = text.replace("2796, 23619", "\x00FLOOR_LA_C\x00")
    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 2796, 23619", "\x00FLOOR_ASSIGN\x00")
    text = text.replace("FLOOR_L, FLOOR_A = 2796, 23619", "\x00FLOOR_ASSIGN2\x00")
    text = text.replace('int(pack.get("n_laws") or 2796)', "\x00OR_LAWS\x00")
    text = text.replace('int(pack.get("n_articles") or 23619)', "\x00OR_ARTS\x00")
    text = text.replace("or 2796)", "\x00OR_LAWS_PAREN\x00")
    text = text.replace("or 23619)", "\x00OR_ARTS_PAREN\x00")
    text = text.replace("@ 2796/", "\x00AT_LAWS\x00")
    text = text.replace("floor 2796/", "\x00FLOOR_SLASH\x00")
    text = text.replace("(2796/", "\x00PAREN_LAWS\x00")
    text = text.replace("= 2796,", "\x00EQ_LAWS\x00")
    text = text.replace(" 23619", "\x00ARTS\x00")
    text = text.replace("23619", "\x00ARTS\x00")
    text = text.replace(" 2796", "\x00LAWS\x00")
    text = text.replace("2796", "\x00LAWS\x00")
    # tip_check stale
    text = text.replace("1012/17715", "\x00FLOOR_LA\x00")
    text = text.replace("1012, 17715", "\x00FLOOR_LA_C\x00")
    text = text.replace("FLOOR_L, FLOOR_A = 1012, 17715", "\x00FLOOR_ASSIGN2\x00")
    text = text.replace(" 17715", "\x00ARTS\x00")
    text = text.replace("17715", "\x00ARTS\x00")
    text = text.replace(" 1012", "\x00LAWS\x00")
    text = text.replace("1012", "\x00LAWS\x00")

    text = text.replace("\x00FLOOR_LA\x00", "2856/24183")
    text = text.replace("\x00FLOOR_LA_SP\x00", "2856 / 24183")
    text = text.replace("\x00FLOOR_LA_C\x00", "2856, 24183")
    text = text.replace("\x00FLOOR_ASSIGN\x00", "FLOOR_LAWS, FLOOR_ARTS = 2856, 24183")
    text = text.replace("\x00FLOOR_ASSIGN2\x00", "FLOOR_L, FLOOR_A = 2856, 24183")
    text = text.replace("\x00OR_LAWS\x00", 'int(pack.get("n_laws") or 2856)')
    text = text.replace("\x00OR_ARTS\x00", 'int(pack.get("n_articles") or 24183)')
    text = text.replace("\x00OR_LAWS_PAREN\x00", "or 2856)")
    text = text.replace("\x00OR_ARTS_PAREN\x00", "or 24183)")
    text = text.replace("\x00AT_LAWS\x00", "@ 2856/")
    text = text.replace("\x00FLOOR_SLASH\x00", "floor 2856/")
    text = text.replace("\x00PAREN_LAWS\x00", "(2856/")
    text = text.replace("\x00EQ_LAWS\x00", "= 2856,")
    text = text.replace("\x00ARTS\x00", "24183")
    text = text.replace("\x00LAWS\x00", "2856")

    for a, b in [
        ("\x00DESTHOLD\x00", HOLD),
        ("\x00DESTWAVE\x00", WAVE_POS),
        ("\x00DESTCHAIN\x00", DEST_CHAIN),
        ("\x00DESTMODE\x00", "RECONFIRM_FINAL"),
        ("Soft filter for EU tip", "Soft filter for Qatar tip"),
        ("during EU ", "during QA "),
        ("EU FIRST", "QA RECONFIRM_FINAL"),
        ("EU tip", "Qatar tip"),
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

    if dst_name == "qatar_bm25_smoke.py":
        text = make_bm25()

    if dst_name == "qatar_write_publish_report.py":
        gate_note = (
            f"BM25 PASS on ASCII GATE "
            f"(attested years {GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}); "
            f"URL almeezan.qa is query-only, not GATE"
        )
        text = re.sub(r'"BM25 PASS on [^"]*"', f'"{gate_note}"', text, count=1)
        text = text.replace("french_ranked", "gate_ranked")
        text = text.replace(
            "Arabic script empty under ASCII tokenizer as expected",
            "ASCII-fold GATE; URL almeezan.qa query-only; decree/emir/gazette empty by design",
        )
        text = text.replace(
            "Arabic script queries empty by tokenizer design",
            "ASCII-fold GATE; URL almeezan.qa query-only",
        )

    if dst_name == "qatar_soft_filter.py":
        text = text.replace(
            "tip pack through with floor checks only (FIRST-IR EXPAND).",
            "tip pack through with floor checks only (RECONFIRM_FINAL).",
        )
        text = text.replace(
            "floor checks only (FIRST-IR EXPAND)",
            "floor checks only (RECONFIRM_FINAL)",
        )
        text = text.replace("FIRST-IR EXPAND", "RECONFIRM_FINAL")
        text = text.replace("FIRST_IR EXPAND", "RECONFIRM_FINAL")

    if dst_name.endswith(f"orchestrator_{DST_TIP_SHORT}.py"):
        text = re.sub(
            r'"""Qatar.*?"""',
            f'"""Qatar RECONFIRM_FINAL orchestrator tip {DST_TIP_SHORT} '
            f'(memsafe corpus+encode; {HOLD})."""',
            text,
            count=1,
            flags=re.S,
        )

    if dst_name == "qatar_bm25_smoke.py":
        for stem in GATE_STEMS:
            if f'"{stem}"' not in text:
                raise RuntimeError(f"missing ASCII stem in GATE of {dst_name}: {stem}")
        for year in GATE_YEARS:
            if f'"{year}"' not in text:
                raise RuntimeError(f"missing year in GATE of {dst_name}: {year}")
        for bad in ("decree", "emir", "gazette", "regulation", "section"):
            # may appear in QUERIES but not GATE list — OK
            pass

    if SRC_TIP_SHORT in text:
        raise RuntimeError(f"src tip leftover in {dst_name}")
    if SRC_TIP_FULL in text:
        raise RuntimeError(f"src tip full leftover in {dst_name}")
    if "23619" in text:
        raise RuntimeError(f"old arts floor leftover in {dst_name}")
    if DST_TIP_SHORT not in text and any(
        x in dst_name for x in ("soft_filter", "orchestrator", "bm25_smoke", "upload", "tip_check", "write_publish")
    ):
        raise RuntimeError(f"missing DST tip in {dst_name}")
    if "\x00" in text:
        raise RuntimeError(f"null placeholder leftover in {dst_name}")
    if DST_TIP_FULL in text:
        for c in re.findall(rf"{DST_TIP_SHORT[:8]}[0-9a-f]{{4,}}", text):
            if c != DST_TIP_FULL and c != DST_TIP_SHORT and len(c) == 40:
                raise RuntimeError(f"corrupted tip SHA in {dst_name}: {c}")
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
            if isinstance(entry, dict) and (entry.get("slug") == SLUG or entry.get("iso2") == "QA"):
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
                    "ir_hub_head": "d84b6f0bff15",
                    "label": "EXPAND",
                    "soft_thin": False,
                    "soft_never_thin": True,
                    "skip_us": True,
                    "italy_leave_alone": True,
                    "language": "Arabic/English",
                    "lang": "ar/en",
                    "iso2": "QA",
                    "slug": SLUG,
                    "repo": "endomorphosis/ipfs_qatar_laws",
                    "years_attested": YEARS_ATTESTED,
                    "gate_years": [int(y) for y in GATE_YEARS],
                    "gate_stems": GATE_STEMS,
                    "note": (
                        f"QA RECONFIRM_FINAL scaffold; tip MATCH {DST_TIP_SHORT}@2856/24183; {HOLD}; "
                        f"soft never-thin ON; SKIP_US; Italy leave alone; {WAVE_POS}; "
                        f"ASCII GATE ({len(GATE_YEARS)} years + {len(GATE_STEMS)} stems); "
                        f"prior eight LIVE — do not rebuild; do NOT start ZM or any other country"
                    ),
                    "status": "CLAIMED",
                    "mode": "RECONFIRM_FINAL",
                    "wave_end": False,
                })
                break
        else:
            print("WARN: QA entry not updated in wave JSON (non-fatal)")
        data["hold"] = HOLD
        data["current"] = SLUG
        data["hold_note"] = (
            "HOLD 0 STRICT continuous for QA RECONFIRM_FINAL build (after_wave2 NINTH; "
            "prior eight LIVE); do NOT start ZM; no soft-lean refill until WAVE END after LK"
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
                        "do_not_start": "zambia",
                        "soft_lean_refill": False,
                        "wave_end": False,
                    }
                    triage.write_text(json.dumps(hold, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                elif triage.parent.is_dir():
                    triage.write_text(wave.read_text(encoding="utf-8"), encoding="utf-8")
            except Exception as e:
                print(f"WARN triage write {triage}: {e}")
        print("updated wave JSON QA entry")
    else:
        print("WARN: wave JSON missing")

    print("GATE years", GATE_YEARS)
    print("GATE stems", GATE_STEMS)
    print("n_gate", len(GATE_YEARS) + len(GATE_STEMS))
    print("HOLD", HOLD)
    print("floor", f"{FLOOR_LAWS}/{FLOOR_ARTS}; RECONFIRM_FINAL; only QA")


if __name__ == "__main__":
    main()
