"""Improve the row normalizer, then let that script normalize every row.

``scan`` and ``apply`` only call ``normalize_legal_text``. They do not import
the LLM router, so one subprocess per country does not boot a model.

``improve`` imports ``llm_router`` once. Each pass sends a short batch of
lines the current script still leaves in place. The model proposes whole-line
patterns. A pattern is stored only when it matches one of those lines, misses
every held-out legal sentence, and the script then actually drops the line.
Accepted patterns live in ``data/learned_line_patterns.json`` and are applied
by the same script that normalizes the rows. The model never rewrites a row.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Sequence

from .catalog import EXCLUDED_SLUGS
from .structure import learned_patterns_path, normalize_legal_text

GenerateText = Callable[[str], str]

# Sentences the learned rules must not delete. Whole-line patterns that
# full-match any of these are discarded.
KEEP_LINES = (
    "Article 1 The present Act applies throughout the territory and binds every person.",
    "The court in Malawi shall apply the Public Roads Act throughout the territory.",
    "2. Amendment of section 5 of Cap. 122A",
    "publié au Journal Officiel et entre en vigueur sur tout le territoire.",
    "10 dicembre 1948",
    "Quarta-Feira de Cinzas continua a ser feriado nacional.",
    "Phone: +1 202 555 0100 is the number appointed under this section.",
    "Troubleshoot faulty system.",
    "100 GENERAL PROVISIONS",
    "applicable rule applies throughout the territory.",
    "The register is published at www.example.com for public inspection under this Act.",
    "بسم الله الرحمن الرحيم",
    "Done at Brussels, 25 June 1999.",
    "2",
    "10",
    "published in the Gazette.",
    "Gazetted 1 October 2009",
    "Lycée : séries ES, L et S",
    "au Journal Officiel",
    "Subs. ibid., for “local official Gazette”.",
    "(a) books (excluding printed music and periodicals) ;",
    "Act 19 Copyright and Neighbouring Rights Act 2006",
)

# One local-model window is 1024 tokens. Keep the prompt well under that.
PROMPT_CHAR_BUDGET = 1600
_PROMPT_PREFIX = (
    "These lines survived legal-text normalization. "
    'Propose JSON only: {"line_patterns": ["^...$"]}. '
    "Each pattern must match one whole chrome line (page header, site footer, "
    "printer stamp) and must not match a legal sentence. Do not write legal text. "
    'If none are safe, return {"line_patterns": []}.\n'
)


def cache_packs(cache_dir: Path, slug: str | None = None) -> list[tuple[str, Path]]:
    packs: list[tuple[str, Path]] = []
    for path in sorted(cache_dir.glob("*_corpus.parquet")):
        name = path.name[: -len("_corpus.parquet")]
        if name in EXCLUDED_SLUGS or not name:
            continue
        if slug is not None and name != slug:
            continue
        packs.append((name, path))
    return packs


_HEADING_LINE = re.compile(
    r"(?i)^(article|art\.|section|chapter|part|subtopic|§)\b"
)
_CHROME_HINT = re.compile(
    r"(?i)(translated|serial number|copyright|gazette|https?://|www\.|"
    r"\bpage\b|printed|journal officiel|série|series\b)"
)
# Repeated lines that are still the law, not a banner. The router must not see them.
_PROVISION_LINE = re.compile(
    r"(?i)(publi[eé]|lycée|lycee|newspaper|days after|série cei|série en |"
    r"\bshall\b|\bmust\b|inserted sig|the gazette\.$|in the gazette\.$|"
    r"\bgazetted\b|\bau journal officiel\b|subs\.\s*ibid|"
    r"excluding printed|whether or not printed|neighbouring rights|"
    r"série de classe|note de bas de page|communaut[eé]s europ)"
)


def scan_pack(path: Path, *, sample_lines: int = 40) -> dict[str, Any]:
    """Count rows and keep the repeated short lines the script did not remove."""
    import pyarrow.parquet as pq

    pf = pq.ParquetFile(path)
    if "body" not in set(pf.schema_arrow.names):
        raise ValueError(f"{path.name} has no body column")
    short: Counter[str] = Counter()
    n = 0
    n_changed = 0
    n_unstable = 0
    for batch in pf.iter_batches(batch_size=512, columns=["body"]):
        for body in batch.column("body").to_pylist():
            if body is None:
                continue
            original = body if isinstance(body, str) else str(body)
            n += 1
            normalized = normalize_legal_text(original)
            if normalized != original:
                n_changed += 1
            if normalize_legal_text(normalized) != normalized:
                n_unstable += 1
            for line in normalized.splitlines():
                stripped = line.strip()
                if not stripped or len(stripped) > 60 or _HEADING_LINE.match(stripped):
                    continue
                if not _CHROME_HINT.search(stripped):
                    continue
                if stripped in short or len(short) < 20000:
                    short[stripped] += 1
    leftovers = [
        {"line": line, "count": count}
        for line, count in short.most_common(sample_lines)
        if count >= 3
    ]
    return {
        "n": n,
        "n_changed": n_changed,
        "n_unstable": n_unstable,
        "leftovers": leftovers,
    }


def apply_pack(path: Path, out_path: Path) -> dict[str, Any]:
    """Rewrite every body with the current script. No model is loaded."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    pf = pq.ParquetFile(path)
    if "body" not in set(pf.schema_arrow.names):
        raise ValueError(f"{path.name} has no body column")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".partial")
    writer = pq.ParquetWriter(tmp, pf.schema_arrow)
    n = 0
    n_changed = 0
    try:
        for batch in pf.iter_batches(batch_size=256):
            bodies = batch.column("body").to_pylist()
            rewritten: list[Any] = []
            for body in bodies:
                if body is None:
                    rewritten.append(None)
                    continue
                original = body if isinstance(body, str) else str(body)
                n += 1
                normalized = normalize_legal_text(original)
                if normalized != original:
                    n_changed += 1
                rewritten.append(normalized)
            index = batch.schema.get_field_index("body")
            arrays = [batch.column(i) for i in range(batch.num_columns)]
            arrays[index] = pa.array(rewritten, type=batch.schema.field("body").type)
            writer.write_batch(pa.record_batch(arrays, schema=batch.schema))
    except Exception:
        writer.close()
        tmp.unlink(missing_ok=True)
        raise
    writer.close()
    tmp.replace(out_path)
    return {"n": n, "n_changed": n_changed}


def _safe_pattern(pattern: str) -> bool:
    if not isinstance(pattern, str) or not pattern.startswith("^") or not pattern.endswith("$"):
        return False
    if not 4 <= len(pattern) <= 180:
        return False
    if len(re.findall(r"\.\*|\.\+", pattern)) > 2:
        return False
    if re.search(r"\([^)]*[+*][^)]*\)[+*{]", pattern):
        return False
    try:
        re.compile(pattern, re.IGNORECASE)
    except re.error:
        return False
    return True


def _blocked_candidate(line: str) -> bool:
    """Publication sentences, headings, and mid-sentence fragments stay in the row."""
    if _PROVISION_LINE.search(line) or _HEADING_LINE.match(line):
        return True
    if len(line) <= 3:
        return True
    return line.endswith((",", ";", " or", " and"))


def accept_line_patterns(
    proposals: Sequence[str],
    leftovers: Sequence[str],
    existing: Sequence[str] = (),
    *,
    must_hit: Sequence[str] | None = None,
) -> list[str]:
    """Keep a proposal only when it hits a leftover and misses every held-out sentence."""
    accepted: list[str] = []
    seen = set(existing)
    pool = [line.strip() for line in leftovers if line and str(line).strip()]
    required = pool if must_hit is None else [line.strip() for line in must_hit if line and str(line).strip()]
    for pattern in proposals:
        if pattern in seen or not _safe_pattern(pattern):
            continue
        compiled = re.compile(pattern, re.IGNORECASE)
        if any(compiled.fullmatch(line.strip()) for line in KEEP_LINES):
            continue
        if compiled.fullmatch("2") or compiled.fullmatch("10"):
            continue
        hits = [line for line in pool if compiled.fullmatch(line)]
        if not hits:
            continue
        if required and not any(compiled.fullmatch(line) for line in required):
            continue
        if any(_blocked_candidate(line) for line in hits):
            continue
        accepted.append(pattern)
        seen.add(pattern)
    return accepted


def line_still_present(line: str) -> bool:
    """True when the current script still leaves this exact line in place."""
    probe = (
        line
        + "\nArticle 1 The present Act applies throughout the territory and binds every person."
    )
    normalized = normalize_legal_text(probe)
    return line in normalized.splitlines()


def router_candidates(
    leftovers: Sequence[dict[str, Any]],
    limit: int = 40,
    *,
    skip: set[str] | None = None,
    presence: dict[str, bool] | None = None,
) -> list[dict[str, Any]]:
    """Banners the script still keeps, in leftover order, excluding provision lines."""
    chosen: list[dict[str, Any]] = []
    seen: set[str] = set()
    held = skip or set()
    known = presence if presence is not None else {}
    for item in leftovers:
        line = str(item.get("line") or "").strip()
        if not line or line in seen or line in held:
            continue
        if line not in known:
            known[line] = line_still_present(line)
        if not known[line] or _blocked_candidate(line):
            continue
        seen.add(line)
        chosen.append({"line": line, "count": int(item.get("count") or 0)})
        if len(chosen) >= limit:
            break
    return chosen


def _cluster_key(line: str) -> str:
    shape = re.sub(r"\d+", "0", line.casefold())
    shape = re.sub(r"[^\w\s]+", " ", shape, flags=re.UNICODE)
    shape = re.sub(r"\s+", " ", shape).strip()
    return " ".join(shape.split()[:4])


def largest_cluster(candidates: Sequence[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """The repeated family with the highest total count, capped to one prompt."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in candidates:
        groups.setdefault(_cluster_key(str(item["line"])), []).append(item)
    best = max(groups.values(), key=lambda group: sum(int(item["count"]) for item in group))
    best.sort(key=lambda item: int(item["count"]), reverse=True)
    return best[:limit]


_BARE_PATTERN = re.compile(r"\^[^\n]{1,180}\$")


def _patterns_from_model_text(raw: str) -> list[str]:
    """Read whole-line patterns from JSON, or from a model that skipped the JSON."""
    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        try:
            payload = json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            payload = None
        found = payload.get("line_patterns") if isinstance(payload, dict) else None
        if isinstance(found, list):
            return [item for item in found if isinstance(item, str)]
    seen: set[str] = set()
    bare: list[str] = []
    for item in _BARE_PATTERN.findall(raw):
        if item not in seen and item != "^...$":
            seen.add(item)
            bare.append(item)
    return bare


def propose_line_patterns(
    leftovers: Sequence[dict[str, Any]],
    generate_text: GenerateText,
    *,
    char_budget: int = PROMPT_CHAR_BUDGET,
) -> list[str]:
    """One router call. The model proposes whole-line patterns, not statute text."""
    if not leftovers:
        return []
    body: list[str] = []
    used = len(_PROMPT_PREFIX)
    for item in leftovers:
        row = f"- {item['count']}× {item['line']}\n"
        if used + len(row) > char_budget:
            break
        body.append(row)
        used += len(row)
    if not body:
        room = max(0, char_budget - len(_PROMPT_PREFIX) - 16)
        snippet = str(leftovers[0]["line"])[:room]
        body.append(f"- {leftovers[0]['count']}× {snippet}\n")
    raw = str(generate_text(_PROMPT_PREFIX + "".join(body)))
    return _patterns_from_model_text(raw)


def load_learned_patterns() -> list[str]:
    path = learned_patterns_path()
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [item for item in payload.get("patterns") or [] if isinstance(item, str)]


def save_learned_patterns(patterns: Sequence[str]) -> None:
    path = learned_patterns_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"patterns": list(patterns)}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    # The structure cache keys on mtime; the write updates it.


def unresolved_path(report_dir: Path) -> Path:
    return report_dir / "_unresolved.json"


def load_unresolved(report_dir: Path) -> set[str]:
    path = unresolved_path(report_dir)
    if not path.is_file():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return {item.strip() for item in payload.get("lines") or [] if isinstance(item, str) and item.strip()}


def save_unresolved(report_dir: Path, lines: set[str]) -> None:
    path = unresolved_path(report_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"lines": sorted(lines)}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def collect_leftovers(report_dir: Path) -> list[dict[str, Any]]:
    """Merge per-country residual lines. Counts for the same line are summed."""
    counts: Counter[str] = Counter()
    if not report_dir.is_dir():
        return []
    for path in sorted(report_dir.glob("*.json")):
        if path.name.startswith("_"):
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for item in payload.get("leftovers") or []:
            if isinstance(item, dict) and isinstance(item.get("line"), str):
                line = item["line"].strip()
                if line:
                    counts[line] += int(item.get("count") or 0)
    return [{"line": line, "count": count} for line, count in counts.most_common()]


def improve_from_reports(
    report_dir: Path,
    generate_text: GenerateText,
    *,
    max_passes: int = 40,
    batch_size: int = 12,
    char_budget: int = PROMPT_CHAR_BUDGET,
    on_pass: Callable[[dict[str, Any]], None] | None = None,
    reset_unresolved: bool = False,
) -> dict[str, Any]:
    """Ask the router, one short batch at a time, for rules the script can apply.

    A batch is one repeated family. Patterns that do not remove a line, or that
    also match a publication sentence, are not stored. Families the model cannot
    safely pattern are remembered so the next batch is a different family.
    """
    merged = collect_leftovers(report_dir)
    pool_lines = [str(item["line"]) for item in merged]
    presence: dict[str, bool] = {}
    skip = set() if reset_unresolved else load_unresolved(report_dir)
    existing = load_learned_patterns()
    accepted_all: list[str] = []
    removed_lines: list[str] = []
    proposed = 0
    passes = 0

    def _emit(row: dict[str, Any]) -> None:
        if on_pass is not None:
            on_pass(row)

    for pass_no in range(1, max(1, max_passes) + 1):
        pending = router_candidates(merged, limit=100_000, skip=skip, presence=presence)
        if not pending:
            break
        batch = largest_cluster(pending, batch_size)
        cluster = _cluster_key(str(batch[0]["line"]))
        _emit({
            "event": "prompt",
            "pass": pass_no,
            "cluster": cluster,
            "batch_id": hashlib.sha256(cluster.encode("utf-8")).hexdigest()[:8],
            "candidates": len(batch),
            "lines": [str(item["line"]) for item in batch],
        })
        try:
            proposals = propose_line_patterns(batch, generate_text, char_budget=char_budget)
        except Exception as exc:
            passes += 1
            _emit({"event": "pass", "pass": pass_no, "cluster": cluster, "error": str(exc)})
            break
        proposed += len(proposals)
        accepted = accept_line_patterns(proposals, pool_lines, existing, must_hit=[str(item["line"]) for item in batch])
        before = list(existing)
        kept: list[str] = []
        removed_now: list[str] = []
        if accepted:
            save_learned_patterns([*before, *accepted])
            for pattern in accepted:
                compiled = re.compile(pattern, re.IGNORECASE)
                hits = [line for line in pool_lines if compiled.fullmatch(line)]
                dropped = [line for line in hits if not line_still_present(line)]
                if not dropped:
                    continue
                kept.append(pattern)
                removed_now.extend(dropped)
            if kept != accepted:
                save_learned_patterns([*before, *kept])
        if not kept:
            skip.update(str(item["line"]) for item in batch)
        else:
            for line in removed_now:
                presence[line] = False
                skip.discard(line)
                if line not in removed_lines:
                    removed_lines.append(line)
            existing = [*before, *kept]
            accepted_all.extend(kept)
        passes += 1
        _emit({
            "event": "pass",
            "pass": pass_no,
            "cluster": cluster,
            "proposed": len(proposals),
            "accepted": kept,
            "removed": len(removed_now),
        })

    save_unresolved(report_dir, skip)
    withheld = 0
    for item in merged:
        line = str(item["line"])
        if line not in presence:
            presence[line] = line_still_present(line)
        if presence[line] and _blocked_candidate(line):
            withheld += 1
    remaining = router_candidates(merged, limit=100_000, skip=skip, presence=presence)
    return {
        "proposed": proposed,
        "accepted": accepted_all,
        "leftover_lines": len(merged),
        "removed": len(removed_lines),
        "removed_lines": removed_lines[:40],
        "unresolved": len(skip),
        "withheld": withheld,
        "remaining": len(remaining),
        "passes": passes,
    }


def worker_count(requested: int | None) -> int:
    if requested is not None:
        return max(1, int(requested))
    return max(1, os.cpu_count() or 1)


def _scan_job(job: tuple[str, str, str]) -> dict[str, Any]:
    slug, path, report_dir = job
    stats = scan_pack(Path(path))
    write_scan(Path(report_dir), slug, stats)
    return {"slug": slug, "n": stats["n"], "n_changed": stats["n_changed"], "n_unstable": stats["n_unstable"], "leftovers": len(stats["leftovers"])}


def _apply_job(job: tuple[str, str, str]) -> dict[str, Any]:
    slug, path, out_dir = job
    out_path = Path(out_dir) / Path(path).name
    stats = apply_pack(Path(path), out_path)
    return {"slug": slug, "out": str(out_path), **stats}


def run_parallel(
    jobs: Sequence[tuple[str, str, str]],
    worker,
    workers: int | None,
    *,
    progress_path: Path | None = None,
    on_done: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """One process per batch of countries. Each country writes its own file.

    Progress is recorded in the parent as each country finishes, so a later
    run can skip those slugs.
    """
    count = worker_count(workers)

    def _finish(row: dict[str, Any]) -> dict[str, Any]:
        if progress_path is not None:
            append_progress(progress_path, row)
        if on_done is not None:
            on_done(row)
        return row

    if count == 1 or len(jobs) <= 1:
        return [_finish(worker(job)) for job in jobs]
    rows: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=min(count, len(jobs))) as pool:
        futures = {pool.submit(worker, job): job[0] for job in jobs}
        for future in as_completed(futures):
            slug = futures[future]
            try:
                row = future.result()
            except Exception as exc:
                row = {"slug": slug, "error": str(exc)}
            rows.append(_finish(row))
    rows.sort(key=lambda row: str(row.get("slug") or ""))
    return rows


def write_scan(report_dir: Path, slug: str, stats: dict[str, Any]) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"{slug}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"slug": slug, **stats}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def scan_done(report_dir: Path, slug: str) -> bool:
    path = report_dir / f"{slug}.json"
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(payload.get("n"), int)


def apply_done(out_dir: Path, slug: str) -> bool:
    path = out_dir / f"{slug}_corpus.parquet"
    if not path.is_file() or path.stat().st_size < 12:
        return False
    with path.open("rb") as handle:
        if handle.read(4) != b"PAR1":
            return False
        handle.seek(-4, 2)
        return handle.read(4) == b"PAR1"


def append_progress(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        handle.flush()


def load_generate_text() -> GenerateText:
    """Import the router once per process. Scan and apply never call this."""
    from ipfs_datasets_py.llm_router import generate_text

    return generate_text


def default_paths(root: Path) -> dict[str, Path]:
    return {
        "cache": root / "cache",
        "reports": root / "reports" / "residuals",
        "out": root / "llm-normalized",
    }
