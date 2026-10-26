#!/usr/bin/env python3
"""Adapt the Maldives English memsafe FIRST_IR pack to Aruba AW tip 06c2b343c859.

Dutch (Aruba); FIRST_IR; HOLD 0 STRICT after-MV (AW→VC→VU).
Soft never-thin ON; SKIP_US; Italy BLOCKED. Wave after_mv: AW→VC→VU (AW only).
GATE: attested years + Dutch legal stems from data/articles.parquet tip 06c2b343c859
(ARTIKEL/wet/besluit style; include aruba/koninkrijk/landsverordening).
URL overheid.aw / gobierno.aw query-only, NOT GATE.
Source tip 7c8f75f3868a (Maldives English memsafe with data/ paths)
— flip language English→Dutch (Aruba).
Keep data/articles.parquet + data/laws.parquet; agent-data not cient-data.
Do NOT start VC/Saint Vincent or VU/Vanuatu. Floors 175 laws / 1419 articles.
"""
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
SRC_TIP_FULL = "7c8f75f3868a7168ab564df0c838458f921c14c3"
SRC_TIP_SHORT = "7c8f75f3868a"
DST_TIP_FULL = "06c2b343c85997d75dcc1ee98bd76e249c21ca09"
DST_TIP_SHORT = "06c2b343c859"
FLOOR_LAWS, FLOOR_ARTS = 175, 1419
SRC_FLOOR_L, SRC_FLOOR_A = 2535, 1678

# Sampled from data/articles.parquet @ 06c2b343c859 (~10 years + Dutch stems)
# Whole-word ASCII-fold FTS hits; laws=175 articles=1419.
GATE_YEARS = [
    "2023", "2024", "2025", "2026", "2004",
    "2020", "2017", "1996", "2021", "2022",
]
GATE_STEMS = [
    "artikel", "wet", "besluit", "landsverordening", "verordening", "code",
    "aruba", "koninkrijk", "regering", "persoon", "minister",
]
YEARS_ATTESTED = [int(y) for y in GATE_YEARS] + [
    2016, 2019, 2009, 1989, 2010, 2011, 2015, 2018, 2001, 1997,
]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT after-MV (AW→VC→VU)"
WAVE_POS = (
    "first country of after_mv wave "
    "(after MV LIVE → AW → VC → VU; NOT wave end)"
)
DEST_CHAIN = "AW→VC→VU"
SRC_HOLD = "HOLD 0 STRICT after-SO (MV WAVE END)"
SRC_WAVE = (
    "WAVE END of after_dj wave "
    "(after MH→KI→BI→SZ→NU→GW→SR→GQ→GY→BJ→SO LIVE)"
)
SRC_CHAIN = "MV WAVE END"

FILES = [
    ("maldives_soft_filter.py", "aruba_soft_filter.py"),
    (f"maldives_corpus_stream_{SRC_TIP_SHORT}.py", f"aruba_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"maldives_encode_memsafe_{SRC_TIP_SHORT}.py", f"aruba_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"maldives_finish_from_emb_{SRC_TIP_SHORT}.py", f"aruba_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"maldives_stream_graph_parts_{SRC_TIP_SHORT}.py", f"aruba_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"maldives_package_memsafe_{SRC_TIP_SHORT}.py", f"aruba_package_memsafe_{DST_TIP_SHORT}.py"),
    ("maldives_upload.py", "aruba_upload.py"),
    ("maldives_bm25_smoke.py", "aruba_bm25_smoke.py"),
    ("maldives_write_publish_report.py", "aruba_write_publish_report.py"),
    (f"maldives_orchestrator_{SRC_TIP_SHORT}.py", f"aruba_orchestrator_{DST_TIP_SHORT}.py"),
]


def adapt(text: str, dst_name: str) -> str:
    # Repair path corruption from prior adapts
    for bad in (
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
        "kiribatient-data", "burundient-data", "eswatinient-data", "niueent-data",
        "guineabissauent-data", "surinameent-data", "equatorialguineaent-data",
        "guyanaent-data", "beninent-data", "somaliaent-data", "maldivesent-data",
        "arubaent-data",
    ):
        text = text.replace(f"/home/box/{bad}/", "/home/box/agent-data/")
        text = text.replace(bad, "agent-data")

    # Protect BM25
    text = text.replace("BM25", "\x00BM25\x00").replace("bm25", "\x00bm25\x00")
    text = text.replace("bmjacency", "adjacency")

    # Protect HOLD / wave / chains BEFORE ISO/slug swaps
    text = text.replace(SRC_HOLD, "\x00DESTHOLD\x00")
    text = text.replace(SRC_WAVE, "\x00DESTWAVE\x00")
    text = text.replace(SRC_CHAIN, "\x00DESTCHAIN\x00")
    text = text.replace(HOLD, "\x00DESTHOLD\x00")
    text = text.replace(DEST_CHAIN, "\x00DESTCHAIN\x00")
    text = text.replace(WAVE_POS, "\x00DESTWAVE\x00")
    text = text.replace("after-SO", "\x00AFTERMV\x00")
    text = text.replace("after SO ", "\x00AFTERMV_SP\x00")
    text = text.replace("after_dj", "\x00AFTERDJ_US\x00")
    text = text.replace("after_mv", "\x00AFTERMV_US\x00")
    text = text.replace(
        "after MH→KI→BI→SZ→NU→GW→SR→GQ→GY→BJ→SO LIVE",
        "\x00SRCCHAIN_FULL\x00",
    )
    text = text.replace("MV FIRST_IR", "\x00DESTFIRST\x00")
    text = text.replace("MV WAVE END", "\x00DESTCHAIN\x00")
    text = text.replace("WAVE END", "\x00NOTWE\x00")

    reps = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        ("endomorphosis/ipfs_maldives_laws", "endomorphosis/ipfs_aruba_laws"),
        ("justicedao/ipfs_maldives_laws_ir", "justicedao/ipfs_aruba_laws_ir"),
        ("ipfs_maldives_laws_ir", "ipfs_aruba_laws_ir"),
        ("ipfs_maldives_laws", "ipfs_aruba_laws"),
        # HOLD / wave restore
        ("\x00DESTHOLD\x00", HOLD),
        ("\x00DESTWAVE\x00", WAVE_POS),
        ("\x00DESTCHAIN\x00", DEST_CHAIN),
        ("\x00SRCCHAIN_FULL\x00", "after MV LIVE → AW → VC → VU"),
        ("\x00AFTERMV\x00", "after-MV"),
        ("\x00AFTERMV_SP\x00", "after MV "),
        ("\x00DESTFIRST\x00", "AW FIRST_IR"),
        ("\x00NOTWE\x00", "NOT wave end"),
        ("MV FIRST_IR (WAVE END)", "AW FIRST_IR (not wave end)"),
        ("www/gazette.gov.mv", "www/overheid.aw"),
        ("gazette.gov.mv", "overheid.aw"),
        ("www.gazette.gov.mv", "www.overheid.aw"),
        ("mira.gov.mv", "gobierno.aw"),
        ("www/gov.mv", "www/overheid.aw"),
        ("gov.mv", "overheid.aw"),
        ("www.gov.mv", "www.overheid.aw"),
        # Language / country
        ("English (Maldives)", "Dutch (Aruba)"),
        ("English Maldives", "Dutch Aruba"),
        ("English legal", "Dutch legal"),
        ("ASCII-fold English", "ASCII-fold Dutch"),
        ("English GATE", "Dutch GATE"),
        ("English stems", "Dutch stems"),
        ("keep language English", "language Dutch"),
        ("Maldives", "Aruba"),
        # slug / path forms BEFORE bare maldives
        ("maldives_ranked", "aruba_ranked"),
        ("maldives_gate", "aruba_gate"),
        ("maldives_pass", "aruba_pass"),
        ("maldives_encode_memsafe", "aruba_encode_memsafe"),
        ("maldives_package_memsafe", "aruba_package_memsafe"),
        ("maldives_corpus_stream", "aruba_corpus_stream"),
        ("maldives_encode_done", "aruba_encode_done"),
        ("maldives_filtered_", "aruba_filtered_"),
        ("maldives_", "aruba_"),
        # ISO whole-token / path forms only (MV already protected in HOLD)
        ('"MV"', '"AW"'),
        ("MV-attested", "AW-attested"),
        ("(MV)", "(AW)"),
        ('"mv"', '"aw"'),
        # floors 2535/1678 → 175/1419 — compound ONLY first
        ("2535/1678", "175/1419"),
        ("2535 / 1678", "175 / 1419"),
        ("2535, 1678", "175, 1419"),
        ("FLOOR_LAWS, FLOOR_ARTS = 2535, 1678", "FLOOR_LAWS, FLOOR_ARTS = 175, 1419"),
        ('int(pack.get("n_laws") or 2535)', 'int(pack.get("n_laws") or 175)'),
        ('int(pack.get("n_articles") or 1678)', 'int(pack.get("n_articles") or 1419)'),
        ("@ 2535/", "@ 175/"),
        ("floor 2535/", "floor 175/"),
        ("(2535/", "(175/"),
        (" 1678", " 1419"),
        ("1678", "1419"),
        ("= 2535,", "= 175,"),
        ("or 2535)", "or 175)"),
        ("2535", "175"),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    # Bare slug "maldives" → "aruba"
    text = re.sub(r"(?<![A-Za-z0-9_])maldives(?![A-Za-z0-9_])", "aruba", text)

    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")
    text = text.replace("\x00AFTERDJ_US\x00", "after_dj")
    text = text.replace("\x00AFTERMV_US\x00", "after_mv")
    text = text.replace("\x00DESTHOLD\x00", HOLD)
    text = text.replace("\x00DESTCHAIN\x00", DEST_CHAIN)
    text = text.replace("\x00DESTWAVE\x00", WAVE_POS)

    # display name / slug fixes
    text = text.replace('"name": "aruba"', '"name": "Aruba"')
    text = text.replace('"name": "Aruba"', '"name": "Aruba"')
    text = text.replace('"slug": "Aruba"', '"slug": "aruba"')
    text = text.replace('SLUG = "Aruba"', 'SLUG = "aruba"')
    text = text.replace('SLUG = "aruba"', 'SLUG = "aruba"')
    text = text.replace('"country": "Aruba"', '"country": "aruba"')
    text = text.replace('"country": "maldives"', '"country": "aruba"')

    # Ensure agent-data survived
    for bad in (
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
        "kiribatient-data", "burundient-data", "eswatinient-data", "niueent-data",
        "guineabissauent-data", "surinameent-data", "equatorialguineaent-data",
        "guyanaent-data", "beninent-data", "somaliaent-data", "maldivesent-data",
        "arubaent-data",
    ):
        text = text.replace(f"/home/box/{bad}/", "/home/box/agent-data/")
        text = text.replace(bad, "agent-data")

    if dst_name == "aruba_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        gate = f"GATE = [\n    {years_line},\n    {stems_line},\n]"
        text = text[:start] + gate + text[end:]
        text = re.sub(
            r"QUERIES = GATE \+ \[[^\]]*\]",
            'QUERIES = GATE + ["www", "overheid.aw", "www.overheid.aw", "gobierno.aw", "www.gobierno.aw", "afkondigingsblad", "landsbesluit", "staatsblad", "lid", "hoofdstuk"]',
            text,
            count=1,
        )
        text = re.sub(
            r'"""BM25 smoke for Aruba IR.*?"""',
            '"""BM25 smoke for Aruba IR — Dutch legal corpus; years + Dutch legal stems FTS gate.\n\n'
            "GATE is attested ASCII years plus Dutch legal stems (ASCII-fold). URL www/overheid.aw\n"
            "gobierno.aw is query-only, never GATE. Every GATE token must rank a hit.\n"
            '"""',
            text,
            count=1,
            flags=re.S,
        )
        note = (
            f"attested years {GATE_NOTE_YEARS} plus Dutch legal stems {GATE_NOTE_STEMS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; URL www/overheid.aw "
            f"gobierno.aw is query-only, not GATE."
        )
        text = re.sub(
            r'"tokenizer_note":\s*"[^"]*"',
            f'"tokenizer_note": "{note}"',
            text,
            count=1,
        )
        text = re.sub(
            r"GATE = attested years [^\"\n]+",
            f"GATE = {note}",
            text,
            count=1,
        )

    if dst_name == "aruba_write_publish_report.py":
        gate_note = (
            f"BM25 PASS on Aruba ASCII-fold Dutch GATE "
            f"(attested years {GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}); "
            f"URL www/overheid.aw gobierno.aw is query-only, not GATE"
        )
        text = re.sub(
            r'BM25 PASS on Aruba[^"]*"',
            gate_note + '"',
            text,
            count=1,
        )
        text = re.sub(
            r'BM25 PASS on [^"]*GATE[^"]*"',
            gate_note + '"',
            text,
            count=1,
        )
        text = text.replace("www/gov.mv is query-only", "www/overheid.aw is query-only")
        text = text.replace("www/overheid.aw is query-only", "www/overheid.aw is query-only")
        text = re.sub(
            r"HOLD 0 STRICT after-SO[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = re.sub(
            r"HOLD 0 STRICT after-MV[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = re.sub(r"[ \t]{2,}", " ", text)

    leftovers = (
        "Maldives", "maldives",
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
        "kiribatient-data", "burundient-data", "eswatinient-data", "niueent-data",
        "guineabissauent-data", "surinameent-data", "equatorialguineaent-data",
        "guyanaent-data", "beninent-data", "somaliaent-data", "maldivesent-data",
        "gov.mv", "www.gov.mv", "gazette.gov.mv", "mira.gov.mv",
    )
    found = []
    for x in leftovers:
        if x == "maldives":
            if re.search(r"(?<![A-Za-z0-9_])maldives(?![A-Za-z0-9_])", text):
                found.append(x)
            continue
        if x in text:
            found.append(x)
    if found:
        raise RuntimeError(f"language/country leftovers in {dst_name}: {found}")

    # Reject non-AW tokens in GATE; require Dutch stems
    if dst_name.endswith("_bm25_smoke.py"):
        gate_slice = text[text.index("GATE = ["): text.index("]", text.index("GATE = [")) + 1]
        for bad in (
            "maldives", "maldivian",
            "act", "article", "section", "law", "ordinance", "republic", "government", "person", "order", "ruling",
            "loi", "decret", "ordonnance", "republique", "benin", "gouvernement", "personne", "ministre",
            "articulo", "ley", "decreto", "codigo", "seccion",
            "artigo", "lei", "suriname", "curacao",
        ):
            if f'"{bad}"' in gate_slice:
                raise RuntimeError(f"non-AW token in GATE of {dst_name}: {bad}")
        for stem in GATE_STEMS:
            if f'"{stem}"' not in gate_slice:
                raise RuntimeError(f"missing Dutch stem in GATE of {dst_name}: {stem}")
        for year in GATE_YEARS:
            if f'"{year}"' not in gate_slice:
                raise RuntimeError(f"missing year in GATE of {dst_name}: {year}")
        if '", "mv"' in text or '", "MV"' in text:
            raise RuntimeError(f"leftover mv query token in {dst_name}")
        if "gov.mv" in text:
            raise RuntimeError(f"leftover gov.mv in {dst_name}")

    # reject bare maldives / MV leftovers outside protected HOLD/wave
    scrub = text
    scrub = scrub.replace(WAVE_POS, "XX")
    scrub = scrub.replace(HOLD, "XX")
    scrub = scrub.replace(DEST_CHAIN, "XX")
    scrub = scrub.replace(SRC_CHAIN, "XX")
    scrub = scrub.replace(SRC_HOLD, "XX")
    scrub = scrub.replace(SRC_WAVE, "XX")
    scrub = scrub.replace("after-MV", "after-XX")
    scrub = scrub.replace("after MV ", "after XX ")
    scrub = scrub.replace("after_mv", "after_xx")
    scrub = scrub.replace("after_dj", "after_xx")
    scrub = scrub.replace("MV LIVE", "XX LIVE")
    scrub = scrub.replace("→MV ", "→XX ")
    scrub = scrub.replace("SO→MV", "XX")
    scrub = scrub.replace("MV WAVE END", "XX")
    if re.search(r"(?<![A-Za-z0-9_])maldives(?![A-Za-z0-9_])", scrub):
        m = re.search(r"(?<![A-Za-z0-9_])maldives(?![A-Za-z0-9_])", scrub)
        raise RuntimeError(
            f"leftover maldives in {dst_name}: ...{scrub[max(0, m.start()-20):m.start()+20]}..."
        )
    if re.search(r"(?<![A-Za-z%])MV(?![A-Za-z])", scrub):
        m = re.search(r"(?<![A-Za-z%])MV(?![A-Za-z])", scrub)
        raise RuntimeError(
            f"leftover MV in {dst_name}: ...{scrub[max(0, m.start()-30):m.start()+30]}..."
        )
    if "ipfs_maldives" in text:
        raise RuntimeError(f"leftover maldives path in {dst_name}")
    if "agent-data" not in text and "SECRET" in text.upper():
        if any(x in dst_name for x in ("soft_filter", "upload", "orchestrator")):
            if "/home/box/" in text and "agent-data" not in text:
                raise RuntimeError(f"missing agent-data secret path in {dst_name}")
    # data/ paths must survive
    if "soft_filter" in dst_name or "corpus_stream" in dst_name:
        if "data/laws.parquet" not in text and 'data" / "laws.parquet"' not in text:
            if '"data"' not in text and "/data/" not in text:
                raise RuntimeError(f"missing data/ parquet paths in {dst_name}")
    # tip integrity
    if SRC_TIP_SHORT in text:
        raise RuntimeError(f"src tip leftover in {dst_name}")
    if "67930c3f-c86b-" in text:
        raise RuntimeError(f"UUID c94b corrupted to c86b in {dst_name}")
    if DST_TIP_SHORT not in text and any(x in dst_name for x in ("soft_filter", "orchestrator", "bm25_smoke")):
        raise RuntimeError(f"missing DST tip in {dst_name}")
    # dutch language must remain for AW
    if "write_publish" in dst_name or "bm25_smoke" in dst_name:
        if re.search(r"ASCII-fold English|English legal", text):
            raise RuntimeError(f"leftover English phrasing in {dst_name}")
        if re.search(r"ASCII-fold French|French legal", text):
            raise RuntimeError(f"leftover French phrasing in {dst_name}")
    return text


for src_name, dst_name in FILES:
    src = ROOT / src_name
    if not src.is_file():
        raise FileNotFoundError(src)
    (ROOT / dst_name).write_text(
        adapt(src.read_text(encoding="utf-8"), dst_name), encoding="utf-8"
    )
    print(f"wrote {dst_name}")

wave = Path("/workspace/country-law-triage/next_ir_ok_wave_after_mv.json")
data = json.loads(wave.read_text(encoding="utf-8"))
for entry in data["queue"]:
    if entry.get("slug") == "aruba" or entry.get("iso2") == "AW":
        entry.update({
            "tip": DST_TIP_SHORT,
            "tip_full": DST_TIP_FULL,
            "laws": FLOOR_LAWS,
            "articles": FLOOR_ARTS,
            "floor_laws": FLOOR_LAWS,
            "floor_articles": FLOOR_ARTS,
            "claim_tip": DST_TIP_SHORT,
            "match_claim": True,
            "ir_hub_head": None,
            "true_first_ir": True,
            "thin": False,
            "label": "EXPAND",
            "soft_never_thin": True,
            "skip_us": True,
            "italy_blocked": True,
            "language": "Dutch",
            "lang": "Dutch",
            "iso2": "AW",
            "slug": "aruba",
            "repo": "endomorphosis/ipfs_aruba_laws",
            "years_attested": YEARS_ATTESTED,
            "gate_years": [int(y) for y in GATE_YEARS],
            "gate_stems": GATE_STEMS,
            "note": (
                f"AW FIRST_IR scaffold; tip MATCH {DST_TIP_SHORT}@175/1419; {HOLD}; "
                f"soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}; "
                f"Dutch GATE ({len(GATE_YEARS)} years + {len(GATE_STEMS)} stems); do NOT start VC/VU"
            ),
            "status": "CLAIMED",
            "mode": "FIRST_IR",
            "wave_end": False,
        })
        break
else:
    raise RuntimeError("Aruba/AW entry missing from wave JSON")

data["wave_status"] = "IN_PROGRESS_AW"
data["hold"] = HOLD
data["current"] = "aruba"
data["do_not_start_next"] = "saint_vincent_grenadines"
data["next"] = "saint_vincent_grenadines"
data["hold_note"] = (
    "HOLD 0 STRICT for AW FIRST_IR build in progress; collectors/deepeners dead; "
    "do NOT start VC or VU until AW LIVE and separately green-lit"
)
wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("updated wave JSON Aruba entry")
print("GATE years", GATE_YEARS)
print("GATE stems", GATE_STEMS)
print("n_gate", len(GATE_YEARS) + len(GATE_STEMS))
print("HOLD", HOLD)
print("GATE language: Dutch years+stems")
