#!/usr/bin/env python3
"""Italy: deepen article bodies from staging_union + local instrument text.

Fail-closed Hub/IR until arts ≥ 12246 (tip aac325c8). Soft never-thin.
Prefer unpacking staging_union articles.parquet when material (≥1000 rows).
Else/also split_articles on existing {_CORPORA}/it/instruments.

- Resume-safe (done_law_ids.txt, articles.jsonl, state.json)
- Periodically rebuild deepen_articles/articles.parquet
- NEVER Hub-publish
- NEVER delete instruments
- NEVER thin existing deeper packs / release data/
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))

import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, "{_SCRAPERS.parent}/scrapers")
from common import split_articles, utcnow  # noqa: E402

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "pyarrow required — run with /workspace/venv/bin/python: " + str(exc)
    ) from exc

ROOT = _CORPORA / "it"
DEEPEN = ROOT / "deepen_articles"
INST_DIR = ROOT / "instruments"
ARTS_JSONL = DEEPEN / "articles.jsonl"
DONE_PATH = DEEPEN / "done_law_ids.txt"
STATE_PATH = DEEPEN / "state.json"
ARTS_PQ = DEEPEN / "articles.parquet"

REL = Path("{_CORPORA}-releases/italy")
STAGING_ARTS = REL / "staging_union" / "data" / "articles.parquet"
STAGING_LAWS = REL / "staging_union" / "data" / "laws.parquet"
RELEASE_ARTS = REL / "data" / "articles.parquet"

WAVE = _CORPORA / "_wave_logs" / "it_article_body_deepen.md"
LOGP = ROOT / "logs" / "it_article_body_deepen.out"
PIDP = ROOT / "logs" / "it_article_body_deepen.pid"

FLOOR_ARTS = 12246
HUB_TIP = "aac325c8"
MAX_ARTS_PER_LAW = 400
SLEEP_S = 0.01
STAGING_MIN_ROWS = 1000
CHECKPOINT_EVERY = 50
CHROME_RE = re.compile(
    r"(?is)^\s*(cookie|privacy|javascript|enable cookies|accesso|login)\b"
)

PT = timezone(timedelta(hours=-7))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOGP, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("it_article_body_deepen")


def now_pt() -> str:
    return datetime.now(PT).strftime("%Y-%m-%d %H:%M:%S PT")


def ensure() -> None:
    DEEPEN.mkdir(parents=True, exist_ok=True)
    LOGP.parent.mkdir(parents=True, exist_ok=True)
    WAVE.parent.mkdir(parents=True, exist_ok=True)


def write_pid() -> None:
    PIDP.write_text(str(os.getpid()) + "\n", encoding="utf-8")


def load_done() -> set[str]:
    if not DONE_PATH.exists():
        return set()
    return {ln.strip() for ln in DONE_PATH.read_text(encoding="utf-8").splitlines() if ln.strip()}


def mark_done(law_id: str) -> None:
    with DONE_PATH.open("a", encoding="utf-8") as f:
        f.write(law_id + "\n")


def append_articles(rows: list[dict]) -> None:
    if not rows:
        return
    with ARTS_JSONL.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def empty_schema_table():
    return pa.table(
        {
            "law_id": pa.array([], type=pa.string()),
            "id": pa.array([], type=pa.string()),
            "title": pa.array([], type=pa.string()),
            "text": pa.array([], type=pa.string()),
            "source_url": pa.array([], type=pa.string()),
            "document_number": pa.array([], type=pa.string()),
            "article_number": pa.array([], type=pa.string()),
            "record_type": pa.array([], type=pa.string()),
            "metadata_json": pa.array([], type=pa.string()),
        }
    )


def normalize_art_row(row: dict, source_tag: str) -> dict | None:
    """Map staging or split_articles output into deepen parquet schema."""
    law_id = str(row.get("law_id") or row.get("law_identifier") or "").strip()
    aid = str(row.get("id") or "").strip()
    text = (row.get("text") or "").strip()
    if not law_id or not aid:
        return None
    if not text or len(text) < 40:
        return None
    if CHROME_RE.match(text):
        return None
    title = (row.get("title") or "").strip() or aid
    doc_num = str(row.get("document_number") or row.get("article_number") or "").strip()
    art_num = str(row.get("article_number") or doc_num).strip()
    meta = row.get("metadata_json")
    if isinstance(meta, dict):
        meta_json = json.dumps(meta, ensure_ascii=False)
    elif isinstance(meta, str) and meta.strip():
        meta_json = meta
    else:
        meta_json = json.dumps(
            {
                "collector": "it_article_body_deepen",
                "source": source_tag,
                "hub_tip_floor_arts": FLOOR_ARTS,
                "hub_tip": HUB_TIP,
            },
            ensure_ascii=False,
        )
    return {
        "law_id": law_id,
        "id": aid[:180],
        "title": title[:500],
        "text": text,
        "source_url": str(row.get("source_url") or ""),
        "document_number": doc_num,
        "article_number": art_num,
        "record_type": str(row.get("record_type") or "article"),
        "metadata_json": meta_json,
    }


def rebuild_articles_parquet() -> int:
    """Rebuild deepen articles.parquet from jsonl; never touch release data/."""
    if not ARTS_JSONL.exists():
        pq.write_table(empty_schema_table(), ARTS_PQ)
        return 0
    by_id: dict[str, dict] = {}
    with ARTS_JSONL.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            rid = row.get("id")
            if not rid:
                continue
            by_id[rid] = row
    rows = list(by_id.values())
    if not rows:
        pq.write_table(empty_schema_table(), ARTS_PQ)
        return 0
    table = pa.Table.from_pylist(rows)
    # soft never-thin: if prior parquet was larger, keep max by merging last
    if ARTS_PQ.exists():
        try:
            prev = pq.read_table(ARTS_PQ)
            if prev.num_rows > len(rows):
                log.warning(
                    "rebuild would thin %s -> %s; merging prior rows (soft never-thin)",
                    prev.num_rows,
                    len(rows),
                )
                for r in prev.to_pylist():
                    rid = r.get("id")
                    if rid and rid not in by_id:
                        by_id[rid] = r
                rows = list(by_id.values())
                table = pa.Table.from_pylist(rows)
        except Exception as exc:
            log.info("prior parquet read skipped: %s", exc)
    pq.write_table(table, ARTS_PQ)
    return len(rows)


def write_state(extra: dict) -> None:
    payload = {
        "updated_at": now_pt(),
        "updated_at_utc": utcnow() if callable(utcnow) else datetime.now(timezone.utc).isoformat(),
        "floor_arts": FLOOR_ARTS,
        "hub_tip": HUB_TIP,
        "hub_publish": False,
        **extra,
    }
    STATE_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_wave(extra: dict) -> None:
    lines = [
        "# Italy article-body deepen",
        "",
        f"- updated_at: {now_pt()} / {utcnow()}",
        f"- goal: local deepen arts ≥ {FLOOR_ARTS} (Hub tip {HUB_TIP}); soft never-thin; **NO Hub publish**",
        f"- instruments: `{INST_DIR}`",
        f"- deepen out: `{DEEPEN}` (articles.jsonl + articles.parquet)",
        f"- staging_union preferred: `{STAGING_ARTS}`",
        f"- release arts (do not thin/overwrite): `{RELEASE_ARTS}`",
        "",
        "## README / launch",
        "",
        "Do **not** Hub-upload from this job. Soft never-thin vs deepen parquet + Hub floor.",
        "Catalog deepen `it_deepen_1908_2026.py` may run separately; this job only unpacks/splits bodies.",
        "",
        "```bash",
        "nohup /workspace/venv/bin/python -u /workspace/scripts/it_article_body_deepen.py \\",
        "  >> {_CORPORA}/it/logs/it_article_body_deepen.out 2>&1 &",
        "echo $! > {_CORPORA}/it/logs/it_article_body_deepen.pid",
        "```",
        "",
        "## Progress",
        "",
    ]
    for k, v in extra.items():
        lines.append(f"- {k}: {v}")
    lines.append("")
    WAVE.write_text("\n".join(lines), encoding="utf-8")


def parquet_rows(path: Path) -> int | None:
    if not path.exists():
        return None
    try:
        return pq.read_table(path).num_rows
    except Exception as exc:
        log.info("cannot read %s: %s", path, exc)
        return None


def unpack_staging(done: set[str]) -> tuple[int, int, set[str]]:
    """Copy staging_union articles into deepen jsonl. Returns (arts_added, laws_touched, staging_law_ids)."""
    n = parquet_rows(STAGING_ARTS)
    if n is None or n < STAGING_MIN_ROWS:
        log.info(
            "staging_union arts not material (rows=%s < %s) — skip unpack",
            n,
            STAGING_MIN_ROWS,
        )
        return 0, 0, set()

    log.info("unpacking staging_union articles.parquet rows=%s", n)
    table = pq.read_table(STAGING_ARTS)
    cols = set(table.column_names)
    needed = ["law_id", "id", "title", "text", "source_url", "document_number", "article_number", "record_type"]
    missing = [c for c in needed if c not in cols]
    if missing:
        log.warning("staging missing cols %s — will coerce", missing)

    rows_raw = table.to_pylist()
    by_law: dict[str, list[dict]] = {}
    for raw in rows_raw:
        law_id = str(raw.get("law_id") or "").strip()
        if not law_id:
            continue
        norm = normalize_art_row(raw, "staging_union")
        if not norm:
            continue
        by_law.setdefault(law_id, []).append(norm)

    arts_added = 0
    laws_touched = 0
    staging_law_ids = set(by_law.keys())
    batch: list[dict] = []
    for law_id, arts in by_law.items():
        if law_id in done:
            continue
        # soft cap per law (staging tip packs can be long)
        use = arts[:MAX_ARTS_PER_LAW]
        batch.extend(use)
        arts_added += len(use)
        laws_touched += 1
        mark_done(law_id)
        done.add(law_id)
        if laws_touched % 200 == 0:
            append_articles(batch)
            batch = []
            n_pq = rebuild_articles_parquet()
            write_state(
                {
                    "phase": "staging_unpack",
                    "laws_touched": laws_touched,
                    "arts_added": arts_added,
                    "articles_parquet_rows": n_pq,
                    "done_ids": len(done),
                }
            )
            log.info(
                "staging checkpoint laws=%s arts_added=%s parquet=%s",
                laws_touched,
                arts_added,
                n_pq,
            )
    if batch:
        append_articles(batch)
    return arts_added, laws_touched, staging_law_ids


def is_chrome_or_empty(text: str) -> bool:
    if not text or len(text.strip()) < 40:
        return True
    if CHROME_RE.match(text.strip()):
        return True
    return False


def split_from_instruments(done: set[str], t0: float, arts_so_far: int) -> tuple[int, int]:
    """Walk instrument JSON and split_articles. Returns (processed, arts_added)."""
    files = sorted(INST_DIR.glob("*.json"))
    log.info("instrument walk: %s files; done=%s", len(files), len(done))
    processed = 0
    arts_added = 0
    counts_batch = 0

    for path in files:
        law_id = path.stem
        if law_id in done:
            continue
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            log.info("skip bad json %s: %s", path.name, exc)
            mark_done(law_id)
            done.add(law_id)
            processed += 1
            continue

        text = rec.get("text") or ""
        # Prefer pre-split documents if present and material
        docs = rec.get("documents") or []
        art_rows: list[dict] = []
        source_url = str(rec.get("source_url") or rec.get("canonical_law_url") or "")
        date = rec.get("date") or rec.get("date_issued")

        if isinstance(docs, list) and len(docs) >= 2:
            for d in docs[:MAX_ARTS_PER_LAW]:
                if not isinstance(d, dict):
                    continue
                merged = dict(d)
                merged.setdefault("law_id", law_id)
                merged.setdefault("law_identifier", law_id)
                merged.setdefault("source_url", source_url)
                norm = normalize_art_row(merged, "instrument_documents")
                if norm:
                    art_rows.append(norm)
        elif not is_chrome_or_empty(text):
            try:
                split = split_articles(text, law_id, source_url, date)
            except Exception as exc:
                log.info("split err %s: %s", law_id, exc)
                split = []
            for d in (split or [])[:MAX_ARTS_PER_LAW]:
                merged = dict(d)
                merged["law_id"] = law_id
                norm = normalize_art_row(merged, "split_articles")
                if norm:
                    art_rows.append(norm)

        if art_rows:
            append_articles(art_rows)
            arts_added += len(art_rows)
            counts_batch += len(art_rows)

        mark_done(law_id)
        done.add(law_id)
        processed += 1
        time.sleep(SLEEP_S)

        if processed % CHECKPOINT_EVERY == 0:
            n_pq = rebuild_articles_parquet()
            write_state(
                {
                    "phase": "instrument_split",
                    "processed": processed,
                    "arts_added_split": arts_added,
                    "arts_added_total_estimate": arts_so_far + arts_added,
                    "articles_parquet_rows": n_pq,
                    "done_ids": len(done),
                    "elapsed_s": int(time.time() - t0),
                    "floor_met": bool(n_pq >= FLOOR_ARTS),
                }
            )
            write_wave(
                {
                    "phase": "instrument_split",
                    "processed": processed,
                    "arts_added_split": arts_added,
                    "articles_parquet_rows": n_pq,
                    "done_ids": len(done),
                    "floor_arts": FLOOR_ARTS,
                    "floor_met": n_pq >= FLOOR_ARTS,
                    "elapsed_s": int(time.time() - t0),
                }
            )
            log.info(
                "checkpoint processed=%s arts_split=%s parquet=%s elapsed=%ss",
                processed,
                arts_added,
                n_pq,
                int(time.time() - t0),
            )

    return processed, arts_added


def main() -> int:
    ensure()
    write_pid()
    t0 = time.time()

    staging_laws_n = parquet_rows(STAGING_LAWS)
    staging_arts_n = parquet_rows(STAGING_ARTS)
    release_arts_n = parquet_rows(RELEASE_ARTS)
    n_inst = len(list(INST_DIR.glob("*.json"))) if INST_DIR.exists() else 0

    log.info(
        "start staging_laws=%s staging_arts=%s release_arts=%s instruments=%s floor=%s",
        staging_laws_n,
        staging_arts_n,
        release_arts_n,
        n_inst,
        FLOOR_ARTS,
    )
    write_wave(
        {
            "phase": "start",
            "staging_union_laws": staging_laws_n,
            "staging_union_arts": staging_arts_n,
            "release_arts": release_arts_n,
            "instruments": n_inst,
            "floor_arts": FLOOR_ARTS,
            "hub_tip": HUB_TIP,
            "max_arts_per_law": MAX_ARTS_PER_LAW,
            "pid": os.getpid(),
        }
    )

    done = load_done()
    arts_added = 0
    laws_staging = 0

    # Phase 1: prefer staging_union unpack (clears floor when present)
    a1, l1, staging_ids = unpack_staging(done)
    arts_added += a1
    laws_staging = l1
    n_pq = rebuild_articles_parquet()
    write_state(
        {
            "phase": "after_staging",
            "staging_arts_unpacked": a1,
            "staging_laws_touched": l1,
            "staging_unique_law_ids": len(staging_ids),
            "articles_parquet_rows": n_pq,
            "done_ids": len(done),
            "floor_met": bool(n_pq >= FLOOR_ARTS),
            "elapsed_s": int(time.time() - t0),
        }
    )
    write_wave(
        {
            "phase": "after_staging",
            "staging_union_laws": staging_laws_n,
            "staging_union_arts": staging_arts_n,
            "staging_arts_unpacked": a1,
            "staging_laws_touched": l1,
            "articles_parquet_rows": n_pq,
            "release_arts": release_arts_n,
            "instruments": n_inst,
            "floor_arts": FLOOR_ARTS,
            "floor_met": n_pq >= FLOOR_ARTS,
            "done_ids": len(done),
        }
    )
    log.info(
        "after staging: unpacked_arts=%s laws=%s parquet=%s floor_met=%s",
        a1,
        l1,
        n_pq,
        n_pq >= FLOOR_ARTS,
    )

    # Phase 2: also walk instruments (fills gaps; Kingdom stubs rarely yield ≥2 headings)
    processed, a2 = split_from_instruments(done, t0, arts_added)
    arts_added += a2
    n_pq = rebuild_articles_parquet()

    write_state(
        {
            "phase": "done",
            "staging_arts_unpacked": a1,
            "staging_laws_touched": laws_staging,
            "instrument_processed": processed,
            "instrument_arts_added": a2,
            "arts_added_total": arts_added,
            "articles_parquet_rows": n_pq,
            "done_ids": len(done),
            "floor_met": bool(n_pq >= FLOOR_ARTS),
            "elapsed_s": int(time.time() - t0),
            "hub_publish": False,
        }
    )
    write_wave(
        {
            "phase": "done",
            "staging_union_laws": staging_laws_n,
            "staging_union_arts": staging_arts_n,
            "staging_arts_unpacked": a1,
            "instrument_processed": processed,
            "instrument_arts_added": a2,
            "articles_parquet_rows": n_pq,
            "release_arts_untouched": release_arts_n,
            "floor_arts": FLOOR_ARTS,
            "floor_met": n_pq >= FLOOR_ARTS,
            "hub_publish": False,
            "elapsed_s": int(time.time() - t0),
            "note": "Release data/ and Hub tip untouched. Deepen pack only under deepen_articles/.",
        }
    )
    log.info(
        "DONE staging_arts=%s split_arts=%s parquet=%s floor_met=%s elapsed=%ss",
        a1,
        a2,
        n_pq,
        n_pq >= FLOOR_ARTS,
        int(time.time() - t0),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
