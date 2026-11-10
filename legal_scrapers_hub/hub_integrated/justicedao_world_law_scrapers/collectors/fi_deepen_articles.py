#!/usr/bin/env python3
"""Finland: deepen Hub tip arts from Finlex open-data AKN statute-consolidated.

Never thins laws below Hub floor 106244 (tip a3003b989e32). Soft never-thin.
Do NOT Hub-publish from this script — deepen only.
SKIP_US.
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
from pathlib import Path
from xml.etree import ElementTree as ET

import pyarrow as pa
import pyarrow.parquet as pq
import requests

ROOT = _CORPORA / "fi"
REL = Path("{_CORPORA}-releases/finland")
LAWS_PQ = REL / "data" / "laws.parquet"
ARTS_PQ = REL / "data" / "articles.parquet"
DEEPEN = ROOT / "deepen"
ARTS_JSONL = DEEPEN / "articles.jsonl"
DONE_PATH = DEEPEN / "done_law_ids.txt"
STATE_PATH = DEEPEN / "state.json"
PID_PATH = DEEPEN / "fi_deepen_articles.pid"
LOG_PATH = _CORPORA / "_wave_logs" / "fi_deepen_articles.md"

BASE = "https://opendata.finlex.fi/finlex/avoindata/v1/akn/fi/act/statute-consolidated"
UA = "CountryLawScraper/fi-deepen (+https://huggingface.co/endomorphosis)"
FLOOR_LAWS = 106244
HUB_TIP = "a3003b989e32"
MAX_ARTS_PER_LAW = 500
FETCH_SLEEP = 0.25
CHECKPOINT_EVERY = 25
ID_RE = re.compile(r"^fi-(\d{4})-(\d+)-(fi|sv)$")
LANG_MAP = {"fi": "fin", "sv": "swe", "fin": "fin", "swe": "swe"}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("fi_deepen")


def ensure() -> None:
    DEEPEN.mkdir(parents=True, exist_ok=True)
    REL.joinpath("data").mkdir(parents=True, exist_ok=True)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


def write_pid() -> None:
    PID_PATH.write_text(str(os.getpid()) + "\n", encoding="utf-8")


def load_done() -> set[str]:
    if not DONE_PATH.exists():
        return set()
    return {ln.strip() for ln in DONE_PATH.read_text(encoding="utf-8").splitlines() if ln.strip()}


def mark_done(law_id: str) -> None:
    with DONE_PATH.open("a", encoding="utf-8") as f:
        f.write(law_id + "\n")


def localtag(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def akn_text(el: ET.Element) -> str:
    parts: list[str] = []
    skip = {
        "meta",
        "identification",
        "references",
        "classification",
        "proprietary",
        "presentation",
        "workflow",
        "analysis",
    }

    def walk(e: ET.Element) -> None:
        tag = localtag(e.tag)
        if tag in skip:
            return
        if e.text and e.text.strip():
            parts.append(e.text.strip())
        for c in list(e):
            walk(c)
            if c.tail and c.tail.strip():
                parts.append(c.tail.strip())
        if tag in {"p", "article", "chapter", "section", "subsection", "paragraph"}:
            parts.append("\n")

    walk(el)
    t = " ".join(parts)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r" *\n *", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def expression_lang(act: ET.Element) -> str:
    lang = ""
    for el in act.iter():
        tag = localtag(el.tag)
        if tag == "FRBRlanguage" and el.get("language"):
            lang = (el.get("language") or "").lower()
        if tag == "FRBRthis" and el.get("value"):
            v = el.get("value") or ""
            if "/swe@" in v:
                lang = "swe"
            elif "/fin@" in v:
                lang = "fin"
    return lang


def pick_act(root: ET.Element, want_lang: str) -> ET.Element | None:
    want = LANG_MAP.get(want_lang, want_lang)
    acts: list[tuple[str, ET.Element]] = []
    for akn in root.iter():
        if localtag(akn.tag) != "akomaNtoso":
            continue
        act = None
        for child in list(akn):
            if localtag(child.tag) in {"act", "doc", "document"}:
                act = child
                break
        if act is None:
            continue
        acts.append((expression_lang(act), act))
    for lang, act in acts:
        if lang == want or LANG_MAP.get(lang) == want:
            return act
    return acts[0][1] if acts else None


def content_absent(act: ET.Element) -> bool:
    for e in act.iter():
        if localtag(e.tag) == "hcontainer" and (e.get("name") or "") == "contentAbsent":
            return True
    return False


def extract_sections(act: ET.Element) -> list[dict]:
    """Extract Finnish pykälä / section units (not nested under another section)."""
    out: list[dict] = []
    # Prefer direct body descendants under chapter/body; still walk all sections
    # whose parent is not a section (chapters wrap sections).
    for e in act.iter():
        if localtag(e.tag) != "section":
            continue
        parent = None  # ElementTree has no parent map; detect nesting via eId depth
        # Skip nested section-in-section by eId pattern .../sec_x/sec_y
        eid = e.get("eId") or ""
        if eid.count("sec_") > 1 or "/sec_" in eid.replace("sec_", "X", 1):
            # if more than one sec_ component, nested — skip
            if len(re.findall(r"sec_", eid)) > 1:
                continue
        num = ""
        heading = ""
        for ch in list(e):
            t = localtag(ch.tag)
            if t == "num":
                num = "".join(ch.itertext()).strip()
            elif t == "heading":
                heading = "".join(ch.itertext()).strip()
        text = akn_text(e)
        if not text or len(text) < 40:
            continue
        label = num or eid or f"section-{len(out)+1}"
        out.append({"num": label, "heading": heading, "text": text, "eid": eid})
        if len(out) >= MAX_ARTS_PER_LAW:
            break
    return out



def candidate_nums(row, num: str) -> list[str]:
    """Prefer hub num, then ELI statute id suffix like 21-000."""
    out: list[str] = []
    for n in (num,):
        if n and n not in out:
            out.append(n)
    eli = str(row.get("eli") or row.get("source_url") or "")
    m = re.search(r"/eli/sd/\d{4}/([0-9]+-[0-9]+)", eli)
    if m and m.group(1) not in out:
        out.append(m.group(1))
    m2 = re.search(r"/eli/sd/\d{4}/(\d+)", eli)
    if m2 and m2.group(1) not in out:
        out.append(m2.group(1))
    return out


def fetch_act_xml(session: requests.Session, year: str, num: str) -> str:
    """Fetch AKN; returns xml text, '' if empty/absent, or raises RuntimeError on hard rate-limit exhaustion."""
    url = f"{BASE}/{year}/{num}"
    backoff = 2.0
    for attempt in range(8):
        try:
            r = session.get(url, timeout=(20, 120), headers={"User-Agent": UA})
        except Exception as exc:
            log.info("fetch err %s/%s %s", year, num, exc)
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)
            continue
        if r.status_code == 429:
            log.info("429 %s/%s attempt=%s sleep=%.1fs", year, num, attempt + 1, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 90)
            continue
        if r.status_code == 200 and r.content and b"<akomaNtoso" in r.content:
            return r.text
        if r.status_code == 200 and b"<Results/>" in r.content:
            return ""  # definitive empty
        if r.status_code == 404:
            return ""
        # other statuses: brief backoff then give up empty
        if r.status_code >= 500:
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)
            continue
        return ""
    raise RuntimeError(f"rate_limited:{year}/{num}")


def para_slug(para: str) -> str:
    s = re.sub(r"\s+", " ", para or "").strip().lower()
    s = re.sub(r"[^a-z0-9§]+", "-", s).strip("-")
    return s or "para"


def append_articles(rows: list[dict]) -> None:
    if not rows:
        return
    with ARTS_JSONL.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def empty_schema_table() -> pa.Table:
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


def seed_hub_articles_if_needed() -> int:
    """Seed existing Hub/release arts into jsonl once so rebuild never drops below tip."""
    if ARTS_JSONL.exists() and ARTS_JSONL.stat().st_size > 0:
        return 0
    if not ARTS_PQ.exists():
        return 0
    t = pq.read_table(ARTS_PQ)
    if t.num_rows == 0:
        return 0
    rows = t.to_pylist()
    append_articles(rows)
    log.info("seeded %s hub/release articles into jsonl", len(rows))
    return len(rows)


def rebuild_articles_parquet() -> int:
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
    # normalize columns
    cols = [
        "law_id",
        "id",
        "title",
        "text",
        "source_url",
        "document_number",
        "article_number",
        "record_type",
        "metadata_json",
    ]
    norm = []
    for r in rows:
        norm.append({c: (r.get(c) if r.get(c) is not None else "") for c in cols})
        if not norm[-1]["record_type"]:
            norm[-1]["record_type"] = "article"
        if isinstance(norm[-1].get("metadata_json"), dict):
            norm[-1]["metadata_json"] = json.dumps(norm[-1]["metadata_json"], ensure_ascii=False)
    table = pa.Table.from_pylist(norm)
    # soft never-thin arts vs previous parquet
    prev = 0
    if ARTS_PQ.exists():
        try:
            prev = pq.read_table(ARTS_PQ).num_rows
        except Exception:
            prev = 0
    if prev and len(norm) < prev:
        log.warning("refuse arts thin %s -> %s; keeping previous parquet", prev, len(norm))
        return prev
    tmp = ARTS_PQ.with_suffix(".parquet.tmp")
    pq.write_table(table, tmp)
    tmp.replace(ARTS_PQ)
    return len(norm)


def update_law_article_counts(counts: dict[str, int]) -> None:
    """Update article_count in working laws parquet; never drop rows."""
    t = pq.read_table(LAWS_PQ)
    if t.num_rows < FLOOR_LAWS:
        raise RuntimeError(f"laws rows {t.num_rows} < floor {FLOOR_LAWS} — abort")
    d = t.to_pandas()
    if len(d) < FLOOR_LAWS:
        raise RuntimeError(f"laws rows {len(d)} < floor {FLOOR_LAWS} — abort")
    d["article_count"] = d.apply(
        lambda r: max(int(r.get("article_count") or 0), int(counts.get(r["id"], r.get("article_count") or 0))),
        axis=1,
    )
    tmp = LAWS_PQ.with_suffix(".parquet.tmp")
    pq.write_table(pa.Table.from_pandas(d, preserve_index=False), tmp)
    # re-check floor before replace
    if pq.read_table(tmp).num_rows < FLOOR_LAWS:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("refusing to write thinned laws parquet")
    tmp.replace(LAWS_PQ)


def main() -> None:
    ensure()
    write_pid()
    if not LAWS_PQ.exists():
        log.error("missing %s", LAWS_PQ)
        sys.exit(1)
    laws = pq.read_table(LAWS_PQ).to_pandas()
    if len(laws) < FLOOR_LAWS:
        log.error("laws %s < floor %s — refuse", len(laws), FLOOR_LAWS)
        sys.exit(2)
    seed_hub_articles_if_needed()
    done = load_done()
    session = requests.Session()
    counts: dict[str, int] = {}
    processed = 0
    arts_added = 0
    empty_body = 0
    fetch_fail = 0
    t0 = time.time()
    log.info(
        "start laws=%s done=%s floor=%s tip=%s jsonl_exists=%s",
        len(laws),
        len(done),
        FLOOR_LAWS,
        HUB_TIP,
        ARTS_JSONL.exists(),
    )

    # Prefer recent consolidations first (older decades often empty on year/num endpoint).
    laws = laws.copy()
    laws["_year"] = laws["id"].astype(str).str.extract(r"^fi-(\d{4})-", expand=False).astype(float)
    laws = laws.sort_values(["_year", "id"], ascending=[False, True])

    for _, row in laws.iterrows():
        law_id = str(row["id"])
        if law_id in done:
            continue
        m = ID_RE.match(law_id)
        if not m:
            mark_done(law_id)
            processed += 1
            continue
        year, num, lang = m.group(1), m.group(2), m.group(3)
        xml = ""
        rate_hit = False
        for cand in candidate_nums(row, num):
            try:
                xml = fetch_act_xml(session, year, cand)
            except RuntimeError as exc:
                if str(exc).startswith("rate_limited"):
                    rate_hit = True
                    log.info("defer %s after rate limit", law_id)
                    break
                raise
            time.sleep(FETCH_SLEEP)
            if xml:
                break
        if rate_hit:
            # do NOT mark done — resume later
            time.sleep(5)
            continue
        if not xml:
            fetch_fail += 1
            mark_done(law_id)
            processed += 1
            if processed % CHECKPOINT_EVERY == 0:
                log.info("checkpoint processed=%s fetch_fail=%s empty=%s arts_added~=%s", processed, fetch_fail, empty_body, arts_added)
            continue
        try:
            root = ET.fromstring(xml)
        except ET.ParseError as exc:
            log.info("parse err %s %s", law_id, exc)
            fetch_fail += 1
            mark_done(law_id)
            processed += 1
            continue
        act = pick_act(root, lang)
        if act is None or content_absent(act):
            empty_body += 1
            mark_done(law_id)
            processed += 1
        else:
            sections = extract_sections(act)
            art_rows = []
            src = str(row.get("source_url") or f"{BASE}/{year}/{num}")
            title_base = str(row.get("title") or f"{num}/{year}")
            for sec in sections:
                slug = para_slug(sec["num"])
                aid = f"{law_id}-{slug}"[:180]
                art_title = f"{title_base} — {sec['num']}"
                if sec.get("heading"):
                    art_title = f"{sec['num']} {sec['heading']}".strip()
                art_rows.append(
                    {
                        "law_id": law_id,
                        "id": aid,
                        "title": art_title[:500],
                        "text": sec["text"],
                        "source_url": src,
                        "document_number": sec["num"],
                        "article_number": sec["num"],
                        "record_type": "article",
                        "metadata_json": json.dumps(
                            {
                                "collector": "fi_deepen_articles",
                                "hub_tip": HUB_TIP,
                                "hub_tip_floor_laws": FLOOR_LAWS,
                                "finlex_year": year,
                                "finlex_num": num,
                                "lang": lang,
                                "eid": sec.get("eid"),
                                "heading": sec.get("heading"),
                            },
                            ensure_ascii=False,
                        ),
                    }
                )
            if art_rows:
                append_articles(art_rows)
                counts[law_id] = len(art_rows)
                arts_added += len(art_rows)
                log.info("law %s year=%s num=%s arts=%s", law_id, year, num, len(art_rows))
            else:
                empty_body += 1
            mark_done(law_id)
            processed += 1

        if processed % CHECKPOINT_EVERY == 0:
            n = rebuild_articles_parquet()
            if counts:
                try:
                    update_law_article_counts(counts)
                except Exception as exc:
                    log.error("laws update failed: %s", exc)
                counts.clear()
            STATE_PATH.write_text(
                json.dumps(
                    {
                        "processed": processed,
                        "arts_jsonl_estimate": arts_added,
                        "articles_parquet_rows": n,
                        "laws_rows": int(len(laws)),
                        "empty_body": empty_body,
                        "fetch_fail": fetch_fail,
                        "elapsed_s": int(time.time() - t0),
                        "hub_tip": HUB_TIP,
                        "floor_laws": FLOOR_LAWS,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            log.info(
                "checkpoint processed=%s arts_added~=%s parquet_arts=%s empty=%s fail=%s elapsed=%ss",
                processed,
                arts_added,
                n,
                empty_body,
                fetch_fail,
                int(time.time() - t0),
            )

    n = rebuild_articles_parquet()
    if counts:
        update_law_article_counts(counts)
    STATE_PATH.write_text(
        json.dumps(
            {
                "processed": processed,
                "arts_jsonl_estimate": arts_added,
                "articles_parquet_rows": n,
                "laws_rows": int(len(laws)),
                "empty_body": empty_body,
                "fetch_fail": fetch_fail,
                "elapsed_s": int(time.time() - t0),
                "hub_tip": HUB_TIP,
                "floor_laws": FLOOR_LAWS,
                "done": True,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    log.info(
        "DONE processed=%s arts_parquet=%s laws=%s empty=%s fail=%s",
        processed,
        n,
        len(laws),
        empty_body,
        fetch_fail,
    )


if __name__ == "__main__":
    main()
