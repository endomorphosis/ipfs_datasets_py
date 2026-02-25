"""Deduplicate state raw HTML outputs.

Supports:
- exact hashing (SHA-256 content equality)
- semantic hashing (SimHash over normalized visible text)

Default behavior is conservative: keep canonical ORS filenames and remove only
non-canonical duplicates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Sequence

SCRIPT_STYLE_PAT = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
TAG_PAT = re.compile(r"<[^>]+>")
WS_PAT = re.compile(r"\s+")
WORD_PAT = re.compile(r"[a-z0-9]+")

CANONICAL_PAT = re.compile(r"^ors\d{3}[a-z]?\.html$", re.IGNORECASE)


def _is_canonical(name: str) -> bool:
    return bool(CANONICAL_PAT.match(name))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _normalize_visible_text(path: Path) -> str:
    try:
        html = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""
    html = SCRIPT_STYLE_PAT.sub(" ", html)
    text = TAG_PAT.sub(" ", html)
    text = text.lower()
    text = WS_PAT.sub(" ", text).strip()
    return text


def _simhash64_from_text(text: str) -> int:
    tokens = WORD_PAT.findall(text)
    if not tokens:
        return 0

    if len(tokens) == 1:
        shingles = [tokens[0]]
    elif len(tokens) == 2:
        shingles = [tokens[0] + " " + tokens[1]]
    else:
        shingles = [" ".join(tokens[i : i + 3]) for i in range(len(tokens) - 2)]

    vec = [0] * 64
    for shingle in shingles:
        h = int(hashlib.sha1(shingle.encode("utf-8")).hexdigest()[:16], 16)
        for bit in range(64):
            if (h >> bit) & 1:
                vec[bit] += 1
            else:
                vec[bit] -= 1

    out = 0
    for bit, weight in enumerate(vec):
        if weight >= 0:
            out |= 1 << bit
    return out


def _hamming_distance(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def _cluster_by_simhash(paths: List[Path], max_distance: int) -> Dict[str, List[Path]]:
    simhash_values: List[int] = []
    for path in paths:
        text = _normalize_visible_text(path)
        simhash_values.append(_simhash64_from_text(text))

    parent = list(range(len(paths)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra = find(a)
        rb = find(b)
        if ra != rb:
            parent[rb] = ra

    for i in range(len(paths)):
        for j in range(i + 1, len(paths)):
            if _hamming_distance(simhash_values[i], simhash_values[j]) <= max_distance:
                union(i, j)

    grouped: Dict[int, List[Path]] = defaultdict(list)
    for i, path in enumerate(paths):
        grouped[find(i)].append(path)

    out: Dict[str, List[Path]] = {}
    for _, group_paths in grouped.items():
        key = hashlib.sha1("\n".join(sorted(str(p) for p in group_paths)).encode("utf-8")).hexdigest()
        out[key] = group_paths
    return out


def _select_keep(paths: List[Path]) -> Path:
    canonical = [p for p in paths if _is_canonical(p.name)]
    if canonical:
        return sorted(canonical, key=lambda p: p.name)[0]
    return sorted(paths, key=lambda p: (0 if _is_canonical(p.name) else 1, len(p.name), p.name))[0]


def _apply_conservative_removals(groups: Dict[str, List[Path]], dry_run: bool) -> Dict[str, Any]:
    removed: List[Dict[str, str]] = []
    kept: List[Dict[str, str]] = []

    for group_id, paths in groups.items():
        keep = _select_keep(paths)
        kept.append({"file": str(keep), "group": group_id})

        for path in paths:
            if path == keep:
                continue
            if _is_canonical(path.name):
                continue
            removed.append({"file": str(path), "group": group_id, "kept": str(keep)})
            if not dry_run:
                path.unlink(missing_ok=True)

    return {"removed": removed, "kept": kept}


def _dedupe_noncanonical_exact(raw_html_dir: Path, dry_run: bool = False) -> Dict[str, Any]:
    files = sorted([p for p in raw_html_dir.iterdir() if p.is_file() and p.suffix.lower() == ".html"])

    by_hash: Dict[str, List[Path]] = defaultdict(list)
    for path in files:
        by_hash[_sha256(path)].append(path)
    applied = _apply_conservative_removals(by_hash, dry_run=dry_run)

    remaining_files = sorted([p for p in raw_html_dir.iterdir() if p.is_file() and p.suffix.lower() == ".html"])

    return {
        "mode": "noncanonical_only_exact",
        "dry_run": dry_run,
        "before_count": len(files),
        "after_count": len(remaining_files),
        "removed_count": len(applied["removed"]),
        "removed": applied["removed"],
    }


def _dedupe_noncanonical_semantic(
    raw_html_dir: Path,
    *,
    dry_run: bool = False,
    semantic_distance: int = 3,
) -> Dict[str, Any]:
    files = sorted([p for p in raw_html_dir.iterdir() if p.is_file() and p.suffix.lower() == ".html"])
    groups = _cluster_by_simhash(files, max_distance=max(0, int(semantic_distance)))
    applied = _apply_conservative_removals(groups, dry_run=dry_run)
    remaining_files = sorted([p for p in raw_html_dir.iterdir() if p.is_file() and p.suffix.lower() == ".html"])

    return {
        "mode": "noncanonical_only_semantic",
        "dry_run": dry_run,
        "semantic_distance": int(semantic_distance),
        "before_count": len(files),
        "after_count": len(remaining_files),
        "removed_count": len(applied["removed"]),
        "removed": applied["removed"],
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Deduplicate state raw HTML output files")
    parser.add_argument("--raw-html-dir", type=Path, required=True)
    parser.add_argument("--manifests-dir", type=Path, required=True)
    parser.add_argument("--strategy", choices=["exact", "semantic"], default="exact")
    parser.add_argument(
        "--semantic-distance",
        type=int,
        default=3,
        help="SimHash max Hamming distance for semantic grouping (semantic strategy only)",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser


def run(argv: Sequence[str] | None = None) -> Dict[str, Any]:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.strategy == "semantic":
        result = _dedupe_noncanonical_semantic(
            args.raw_html_dir,
            dry_run=args.dry_run,
            semantic_distance=args.semantic_distance,
        )
    else:
        result = _dedupe_noncanonical_exact(args.raw_html_dir, dry_run=args.dry_run)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = args.manifests_dir / f"html_dedupe_{run_id}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(json.dumps({"report": str(out_path), **result}, indent=2))
    return result


if __name__ == "__main__":
    run()
