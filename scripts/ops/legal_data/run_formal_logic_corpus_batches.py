#!/usr/bin/env python3
"""Run federal/state formal-logic conversion batches with separate metadata outputs.

This orchestrator runs `convert_legal_corpus_to_formal_logic.py` twice:
- Federal corpus profile
- State corpus profile

Each profile writes to separate artifact directories so theorem-candidate stores and
reports are split by jurisdiction/domain.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List


@dataclass
class BatchProfile:
    name: str
    inputs: List[str]
    jurisdiction: str
    legal_domain: str
    source_case: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run separate federal/state formal-logic conversion batches.",
    )
    parser.add_argument(
        "--converter-script",
        default="scripts/ops/convert_legal_corpus_to_formal_logic.py",
        help="Path to converter script.",
    )
    parser.add_argument(
        "--output-root",
        default="artifacts/formal_logic_batches",
        help="Root output directory for batch artifacts.",
    )
    parser.add_argument(
        "--glob",
        default="**/*.jsonld",
        help="Glob pattern passed to converter script.",
    )
    parser.add_argument(
        "--max-sentences-per-segment",
        type=int,
        default=2,
        help="Chunking parameter forwarded to converter script.",
    )
    parser.add_argument(
        "--max-chars-per-segment",
        type=int,
        default=420,
        help="Chunking parameter forwarded to converter script.",
    )
    parser.add_argument(
        "--enable-clause-decomposition",
        action="store_true",
        help="Enable clause-level decomposition before conversion.",
    )
    parser.add_argument(
        "--clause-min-chars",
        type=int,
        default=45,
        help="Minimum clause chars when decomposition is enabled.",
    )
    parser.add_argument(
        "--clause-max-chars",
        type=int,
        default=260,
        help="Target max clause chars when decomposition is enabled.",
    )
    parser.add_argument(
        "--limit-files",
        type=int,
        default=0,
        help="Optional file cap for each profile (0 = no cap).",
    )
    parser.add_argument(
        "--limit-segments",
        type=int,
        default=0,
        help="Optional segment cap for each profile (0 = no cap).",
    )
    parser.add_argument(
        "--add-to-theorem-store",
        action="store_true",
        help="If set, request theorem ingestion during each profile run.",
    )
    parser.add_argument(
        "--enable-tdfol",
        action="store_true",
        help="Enable TDFOL parsing in converter profiles.",
    )
    parser.add_argument(
        "--enable-cec",
        action="store_true",
        help="Enable CEC conversions in converter profiles.",
    )
    parser.add_argument(
        "--enable-semantic-roundtrip",
        action="store_true",
        help="Enable embedding-based semantic conservation scoring in converter profiles.",
    )
    parser.add_argument(
        "--embedding-dim",
        type=int,
        default=1024,
        help="Embedding dimension for hashing-based semantic scoring.",
    )
    parser.add_argument(
        "--embedding-backend",
        choices=["hash", "sentence-transformers"],
        default="hash",
        help="Embedding backend for semantic scoring.",
    )
    parser.add_argument(
        "--embedding-model",
        default="sentence-transformers/all-MiniLM-L6-v2",
        help="Embedding model for semantic scoring when backend is sentence-transformers.",
    )
    parser.add_argument(
        "--strict-embedding-backend",
        action="store_true",
        help="Fail profile runs when the requested embedding backend cannot be used.",
    )
    parser.add_argument(
        "--enable-roundtrip-optimizer",
        action="store_true",
        help="Enable optimizer-guided roundtrip decode strategy selection.",
    )
    parser.add_argument(
        "--roundtrip-optimizer-min-uses",
        type=int,
        default=3,
        help="Minimum observations before optimizer recommends global prompt by modality.",
    )
    parser.add_argument(
        "--roundtrip-optimizer-exploration-rate",
        type=float,
        default=0.0,
        help="Exploration rate for prompt optimizer candidate selection (default: 0.0).",
    )
    parser.add_argument(
        "--roundtrip-optimizer-export",
        default="",
        help="Optional path prefix for optimizer-library exports (profile name will be appended).",
    )
    parser.add_argument(
        "--allow-source-conditioned-roundtrip",
        action="store_true",
        help="Allow decoder candidates to reuse source text (off by default to avoid leakage).",
    )
    parser.add_argument(
        "--enable-focused-retry-optimizer",
        action="store_true",
        help="Enable focused retry optimization for weak deontic/FOL conversions.",
    )
    parser.add_argument(
        "--enable-encoder-quality-retry",
        action="store_true",
        help="Enable encoder-quality retry using focused and prior-context windows.",
    )
    parser.add_argument(
        "--encoder-context-window-prior",
        type=int,
        default=1,
        help="Number of prior segments used for encoder retry context.",
    )
    parser.add_argument(
        "--encoder-retry-max-attempts",
        type=int,
        default=3,
        help="Maximum encoder retry candidate texts per segment.",
    )
    parser.add_argument(
        "--encoder-quality-retry-profiles",
        default="federal,state",
        help="Comma-separated profiles to apply encoder-quality retry to (e.g., state).",
    )
    parser.add_argument(
        "--enable-fragment-merging",
        action="store_true",
        help="Enable merged theorem propositions from small adjacent formula fragments.",
    )
    parser.add_argument(
        "--fragment-merge-max-prior",
        type=int,
        default=1,
        help="Number of prior merged propositions to keep per segment stream.",
    )
    parser.add_argument(
        "--federal-fragment-merge-max-prior",
        type=int,
        default=-1,
        help="Per-profile override for federal fragment merge context depth (-1 uses global setting).",
    )
    parser.add_argument(
        "--state-fragment-merge-max-prior",
        type=int,
        default=-1,
        help="Per-profile override for state fragment merge context depth (-1 uses global setting).",
    )
    parser.add_argument("--semantic-threshold-deontic", type=float, default=-1.0)
    parser.add_argument("--semantic-threshold-fol", type=float, default=-1.0)
    parser.add_argument("--semantic-threshold-tdfol", type=float, default=-1.0)
    parser.add_argument("--semantic-threshold-cec-bridge", type=float, default=-1.0)
    parser.add_argument("--semantic-threshold-cec-compile", type=float, default=-1.0)
    parser.add_argument("--federal-semantic-threshold-deontic", type=float, default=-1.0)
    parser.add_argument("--federal-semantic-threshold-fol", type=float, default=-1.0)
    parser.add_argument("--federal-semantic-threshold-tdfol", type=float, default=-1.0)
    parser.add_argument("--federal-semantic-threshold-cec-bridge", type=float, default=-1.0)
    parser.add_argument("--federal-semantic-threshold-cec-compile", type=float, default=-1.0)
    parser.add_argument("--state-semantic-threshold-deontic", type=float, default=-1.0)
    parser.add_argument("--state-semantic-threshold-fol", type=float, default=-1.0)
    parser.add_argument("--state-semantic-threshold-tdfol", type=float, default=-1.0)
    parser.add_argument("--state-semantic-threshold-cec-bridge", type=float, default=-1.0)
    parser.add_argument("--state-semantic-threshold-cec-compile", type=float, default=-1.0)
    parser.add_argument("--semantic-floor-deontic", type=float, default=-1.0)
    parser.add_argument("--semantic-floor-fol", type=float, default=-1.0)
    parser.add_argument("--semantic-floor-cec-compile", type=float, default=-1.0)
    parser.add_argument(
        "--allow-missing-semantic-modalities",
        default="tdfol,cec_bridge",
        help="Comma-separated modalities allowed to be missing for theorem gating.",
    )
    parser.add_argument(
        "--update-drift-dashboard",
        action="store_true",
        help="If set, update semantic drift dashboard after batch completion.",
    )
    parser.add_argument(
        "--drift-dashboard-script",
        default="scripts/ops/build_semantic_drift_dashboard.py",
        help="Path to drift dashboard generator script.",
    )
    parser.add_argument(
        "--drift-manifests-glob",
        default="artifacts/formal_logic_batches*/batch_manifest.json",
        help="Manifest glob passed to drift dashboard generator.",
    )
    parser.add_argument(
        "--drift-output-json",
        default="artifacts/formal_logic_drift/dashboard.json",
        help="Drift dashboard JSON output path.",
    )
    parser.add_argument(
        "--drift-output-md",
        default="artifacts/formal_logic_drift/dashboard.md",
        help="Drift dashboard Markdown output path.",
    )
    return parser.parse_args()


def load_summary(path: Path) -> Dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("summary", {})


def run_profile(args: argparse.Namespace, profile: BatchProfile) -> Dict[str, object]:
    profile_dir = Path(args.output_root) / profile.name
    profile_dir.mkdir(parents=True, exist_ok=True)

    report_json = profile_dir / "report.json"
    report_jsonl = profile_dir / "records.jsonl"
    report_logic_jsonld = profile_dir / "logic.jsonld"

    cmd = [
        sys.executable,
        args.converter_script,
        "--input",
        *profile.inputs,
        "--glob",
        args.glob,
        "--max-sentences-per-segment",
        str(args.max_sentences_per_segment),
        "--max-chars-per-segment",
        str(args.max_chars_per_segment),
        "--jurisdiction",
        profile.jurisdiction,
        "--legal-domain",
        profile.legal_domain,
        "--source-case",
        profile.source_case,
        "--output-json",
        str(report_json),
        "--output-jsonl",
        str(report_jsonl),
        "--output-logic-jsonld",
        str(report_logic_jsonld),
    ]

    if args.enable_clause_decomposition:
        cmd.append("--enable-clause-decomposition")
        cmd.extend(["--clause-min-chars", str(args.clause_min_chars)])
        cmd.extend(["--clause-max-chars", str(args.clause_max_chars)])

    # Start from shared thresholds and allow per-profile overrides.
    thresholds = {
        "deontic": float(args.semantic_threshold_deontic),
        "fol": float(args.semantic_threshold_fol),
        "tdfol": float(args.semantic_threshold_tdfol),
        "cec_bridge": float(args.semantic_threshold_cec_bridge),
        "cec_compile": float(args.semantic_threshold_cec_compile),
    }
    prefix = f"{profile.name}_semantic_threshold_"
    for key in list(thresholds.keys()):
        override_attr = f"{prefix}{key}"
        override_value = float(getattr(args, override_attr, -1.0))
        if override_value >= 0.0:
            thresholds[key] = override_value

    if args.limit_files > 0:
        cmd.extend(["--limit-files", str(args.limit_files)])
    if args.limit_segments > 0:
        cmd.extend(["--limit-segments", str(args.limit_segments)])
    if args.add_to_theorem_store:
        cmd.append("--add-to-theorem-store")
    if args.enable_tdfol:
        cmd.append("--enable-tdfol")
    if args.enable_cec:
        cmd.append("--enable-cec")
    if args.enable_semantic_roundtrip:
        cmd.append("--enable-semantic-roundtrip")
        cmd.extend(["--embedding-dim", str(args.embedding_dim)])
        cmd.extend(["--embedding-backend", str(args.embedding_backend)])
        cmd.extend(["--embedding-model", str(args.embedding_model)])
        if args.strict_embedding_backend:
            cmd.append("--strict-embedding-backend")
        if args.enable_focused_retry_optimizer:
            cmd.append("--enable-focused-retry-optimizer")
        if args.enable_encoder_quality_retry:
            retry_profiles = {
                x.strip()
                for x in str(args.encoder_quality_retry_profiles).split(",")
                if x.strip()
            }
            if profile.name in retry_profiles:
                cmd.append("--enable-encoder-quality-retry")
                cmd.extend(["--encoder-context-window-prior", str(args.encoder_context_window_prior)])
                cmd.extend(["--encoder-retry-max-attempts", str(args.encoder_retry_max_attempts)])
        if args.enable_fragment_merging:
            cmd.append("--enable-fragment-merging")
            merge_depth = int(args.fragment_merge_max_prior)
            profile_override = int(
                getattr(args, f"{profile.name}_fragment_merge_max_prior", -1)
            )
            if profile_override >= 0:
                merge_depth = profile_override
            cmd.extend(["--fragment-merge-max-prior", str(merge_depth)])
        if args.enable_roundtrip_optimizer:
            cmd.append("--enable-roundtrip-optimizer")
            cmd.extend(["--roundtrip-optimizer-min-uses", str(args.roundtrip_optimizer_min_uses)])
            cmd.extend(["--roundtrip-optimizer-exploration-rate", str(float(getattr(args, "roundtrip_optimizer_exploration_rate", 0.0)))])
            if args.allow_source_conditioned_roundtrip:
                cmd.append("--allow-source-conditioned-roundtrip")
            if args.roundtrip_optimizer_export:
                export_base = Path(args.roundtrip_optimizer_export)
                export_path = export_base.parent / f"{export_base.stem}_{profile.name}{export_base.suffix or '.json'}"
                cmd.extend(["--roundtrip-optimizer-export", str(export_path)])
        cmd.extend(["--semantic-threshold-deontic", str(thresholds["deontic"])])
        cmd.extend(["--semantic-threshold-fol", str(thresholds["fol"])])
        cmd.extend(["--semantic-threshold-tdfol", str(thresholds["tdfol"])])
        cmd.extend(["--semantic-threshold-cec-bridge", str(thresholds["cec_bridge"])])
        cmd.extend(["--semantic-threshold-cec-compile", str(thresholds["cec_compile"])])
        cmd.extend(["--semantic-floor-deontic", str(args.semantic_floor_deontic)])
        cmd.extend(["--semantic-floor-fol", str(args.semantic_floor_fol)])
        cmd.extend(["--semantic-floor-cec-compile", str(args.semantic_floor_cec_compile)])
        cmd.extend(["--allow-missing-semantic-modalities", str(args.allow_missing_semantic_modalities)])

    subprocess.run(cmd, check=True)

    summary = load_summary(report_json)
    summary["profile"] = profile.name
    summary["report_json"] = str(report_json)
    summary["report_jsonl"] = str(report_jsonl)
    summary["report_logic_jsonld"] = str(report_logic_jsonld)
    return summary


def main() -> None:
    args = parse_args()

    profiles = [
        BatchProfile(
            name="federal",
            inputs=["data/federal_laws"],
            jurisdiction="Federal",
            legal_domain="federal_law",
            source_case="Federal Corpus Batch",
        ),
        BatchProfile(
            name="state",
            inputs=["data/state_laws"],
            jurisdiction="State",
            legal_domain="state_law",
            source_case="State Corpus Batch",
        ),
    ]

    results: List[Dict[str, object]] = []
    for profile in profiles:
        results.append(run_profile(args, profile))

    manifest_path = Path(args.output_root) / "batch_manifest.json"
    manifest = {
        "output_root": args.output_root,
        "profiles": results,
        "totals": {
            "input_file_count": sum(int(p.get("input_file_count", 0)) for p in results),
            "segment_count": sum(int(p.get("segment_count", 0)) for p in results),
            "theorem_candidate_count": sum(int(p.get("theorem_candidate_count", 0)) for p in results),
            "theorems_ingested_count": sum(int(p.get("theorems_ingested_count", 0)) for p in results),
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if args.update_drift_dashboard:
        subprocess.run(
            [
                sys.executable,
                args.drift_dashboard_script,
                "--manifests-glob",
                args.drift_manifests_glob,
                "--output-json",
                args.drift_output_json,
                "--output-md",
                args.drift_output_md,
            ],
            check=True,
        )

    print(json.dumps(manifest, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
