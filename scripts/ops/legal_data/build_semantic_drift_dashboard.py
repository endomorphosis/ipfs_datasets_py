#!/usr/bin/env python3
"""Build a semantic drift dashboard from historical batch manifests.

This script scans batch manifest files produced by `run_formal_logic_corpus_batches.py`
and generates JSON + Markdown summaries for trend monitoring.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class RunRow:
    ts: datetime
    manifest_path: str
    output_root: str
    profile: str
    semantic_mean: Optional[float]
    semantic_by_modality: Dict[str, Optional[float]]
    theorem_candidates: int
    theorems_ingested: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build semantic drift dashboard from batch manifests.")
    parser.add_argument(
        "--manifests-glob",
        default="artifacts/formal_logic_batches*/batch_manifest.json",
        help="Glob pattern to locate manifest files.",
    )
    parser.add_argument(
        "--output-json",
        default="artifacts/formal_logic_drift/dashboard.json",
        help="Output JSON dashboard path.",
    )
    parser.add_argument(
        "--output-md",
        default="artifacts/formal_logic_drift/dashboard.md",
        help="Output Markdown dashboard path.",
    )
    return parser.parse_args()


def _as_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def collect_rows(manifest_paths: List[Path]) -> List[RunRow]:
    rows: List[RunRow] = []
    for manifest in manifest_paths:
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except Exception:
            continue

        ts = datetime.fromtimestamp(manifest.stat().st_mtime, tz=timezone.utc)
        output_root = str(data.get("output_root", ""))
        profiles = data.get("profiles", []) or []

        for p in profiles:
            rows.append(
                RunRow(
                    ts=ts,
                    manifest_path=str(manifest),
                    output_root=output_root,
                    profile=str(p.get("profile", "unknown")),
                    semantic_mean=_as_float(p.get("semantic_similarity_mean")),
                    semantic_by_modality={
                        k: _as_float(v)
                        for k, v in (p.get("semantic_similarity_by_modality", {}) or {}).items()
                    },
                    theorem_candidates=_as_int(p.get("theorem_candidate_count", 0)),
                    theorems_ingested=_as_int(p.get("theorems_ingested_count", 0)),
                )
            )

    rows.sort(key=lambda r: (r.profile, r.ts))
    return rows


def build_dashboard(rows: List[RunRow]) -> Dict[str, Any]:
    by_profile: Dict[str, List[RunRow]] = {}
    for row in rows:
        by_profile.setdefault(row.profile, []).append(row)

    profiles_summary: Dict[str, Any] = {}
    for profile, plist in by_profile.items():
        plist.sort(key=lambda r: r.ts)
        latest = plist[-1]
        prev = plist[-2] if len(plist) > 1 else None

        delta_mean = None
        if prev and latest.semantic_mean is not None and prev.semantic_mean is not None:
            delta_mean = latest.semantic_mean - prev.semantic_mean

        modality_trend: Dict[str, Optional[float]] = {}
        if prev:
            keys = set(latest.semantic_by_modality.keys()) | set(prev.semantic_by_modality.keys())
            for k in sorted(keys):
                lv = latest.semantic_by_modality.get(k)
                pv = prev.semantic_by_modality.get(k)
                if lv is None or pv is None:
                    modality_trend[k] = None
                else:
                    modality_trend[k] = lv - pv

        profiles_summary[profile] = {
            "runs": len(plist),
            "latest": {
                "timestamp_utc": latest.ts.isoformat(),
                "manifest_path": latest.manifest_path,
                "output_root": latest.output_root,
                "semantic_similarity_mean": latest.semantic_mean,
                "semantic_similarity_by_modality": latest.semantic_by_modality,
                "theorem_candidate_count": latest.theorem_candidates,
                "theorems_ingested_count": latest.theorems_ingested,
            },
            "trend_vs_previous": {
                "semantic_similarity_mean_delta": delta_mean,
                "semantic_similarity_by_modality_delta": modality_trend,
            },
        }

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "manifest_count": len({r.manifest_path for r in rows}),
        "profile_count": len(by_profile),
        "profiles": profiles_summary,
        "rows": [
            {
                "timestamp_utc": r.ts.isoformat(),
                "manifest_path": r.manifest_path,
                "output_root": r.output_root,
                "profile": r.profile,
                "semantic_similarity_mean": r.semantic_mean,
                "semantic_similarity_by_modality": r.semantic_by_modality,
                "theorem_candidate_count": r.theorem_candidates,
                "theorems_ingested_count": r.theorems_ingested,
            }
            for r in rows
        ],
    }


def render_markdown(dashboard: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# Semantic Drift Dashboard")
    lines.append("")
    lines.append(f"Generated: `{dashboard.get('generated_at_utc')}`")
    lines.append("")
    lines.append("## Latest By Profile")
    lines.append("")
    lines.append("| Profile | Runs | Mean Similarity | Delta vs Prev | Theorems (cand/ingested) |")
    lines.append("|---|---:|---:|---:|---:|")

    profiles = dashboard.get("profiles", {}) or {}
    for profile in sorted(profiles.keys()):
        p = profiles[profile]
        latest = p.get("latest", {})
        trend = p.get("trend_vs_previous", {})
        mean_val = latest.get("semantic_similarity_mean")
        delta_val = trend.get("semantic_similarity_mean_delta")
        cand = latest.get("theorem_candidate_count", 0)
        ing = latest.get("theorems_ingested_count", 0)
        lines.append(
            f"| {profile} | {p.get('runs', 0)} | "
            f"{mean_val if mean_val is not None else 'n/a'} | "
            f"{delta_val if delta_val is not None else 'n/a'} | "
            f"{cand}/{ing} |"
        )

    lines.append("")
    lines.append("## Modality Deltas")
    lines.append("")
    for profile in sorted(profiles.keys()):
        lines.append(f"### {profile}")
        trend = profiles[profile].get("trend_vs_previous", {})
        md = trend.get("semantic_similarity_by_modality_delta", {}) or {}
        if not md:
            lines.append("No prior run to compare.")
            lines.append("")
            continue
        lines.append("| Modality | Delta |")
        lines.append("|---|---:|")
        for mod, delta in sorted(md.items()):
            lines.append(f"| {mod} | {delta if delta is not None else 'n/a'} |")
        lines.append("")

    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    manifest_paths = sorted(Path(".").glob(args.manifests_glob))

    rows = collect_rows(manifest_paths)
    dashboard = build_dashboard(rows)

    out_json = Path(args.output_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(dashboard, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    out_md = Path(args.output_md)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(render_markdown(dashboard), encoding="utf-8")

    print(json.dumps({
        "manifest_count": dashboard.get("manifest_count", 0),
        "profile_count": dashboard.get("profile_count", 0),
        "output_json": str(out_json),
        "output_md": str(out_md),
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
