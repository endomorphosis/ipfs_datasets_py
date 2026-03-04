#!/usr/bin/env python3
"""Build a consolidated Oregon court-rules embeddings parquet via embeddings_router.

Inputs:
- ORCP indexed parquet
- ORCrP indexed parquet
- Oregon local court rules indexed parquet

Output:
- Single parquet file with one embedding vector per `ipfs_cid` using gte-small.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

import pandas as pd

from ipfs_datasets_py import embeddings_router


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return " ".join(value.split()).strip()
    if isinstance(value, (list, tuple)):
        return " ".join(_normalize_text(v) for v in value if v is not None).strip()
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value).strip()


def _build_embedding_text(row: Dict[str, Any]) -> str:
    # Compose semantic context + primary rule text.
    fields = [
        row.get("dataset_family"),
        row.get("name"),
        row.get("titleName"),
        row.get("chapterName"),
        row.get("sectionName"),
        row.get("text"),
    ]
    parts = [_normalize_text(v) for v in fields]
    parts = [p for p in parts if p]
    return "\n".join(parts)


def _load_inputs(paths: Iterable[Path]) -> pd.DataFrame:
    frames: List[pd.DataFrame] = []
    for path in paths:
        df = pd.read_parquet(path)
        frames.append(df)
    merged = pd.concat(frames, ignore_index=True)
    merged = merged.drop_duplicates(subset=["ipfs_cid"], keep="first")
    return merged


def build_embeddings_parquet(
    input_paths: List[Path],
    output_path: Path,
    model: str,
    provider: str | None,
    device: str,
    batch_size: int,
) -> Dict[str, Any]:
    df = _load_inputs(input_paths)

    records = df.to_dict(orient="records")
    payload_rows: List[Dict[str, Any]] = []
    texts: List[str] = []

    for row in records:
        text = _build_embedding_text(row)
        if not text:
            continue
        payload_rows.append(row)
        texts.append(text)

    vectors = embeddings_router.embed_texts_batched(
        texts,
        batch_size=batch_size,
        model_name=model,
        provider=provider,
        device=device,
    )

    if len(vectors) != len(payload_rows):
        raise RuntimeError(f"Embedding count mismatch: {len(vectors)} != {len(payload_rows)}")

    out_rows: List[Dict[str, Any]] = []
    for row, text, vec in zip(payload_rows, texts, vectors):
        out_rows.append(
            {
                "ipfs_cid": row.get("ipfs_cid"),
                "dataset_family": row.get("dataset_family"),
                "name": row.get("name"),
                "titleName": row.get("titleName"),
                "chapterName": row.get("chapterName"),
                "sectionName": row.get("sectionName"),
                "sourceUrl": row.get("sourceUrl"),
                "text": row.get("text"),
                "embedding_text": text,
                "embedding": vec,
                "embedding_model": model,
                "embedding_provider": provider or "auto",
                "embedding_device": device,
                "embedding_dim": len(vec),
            }
        )

    out_df = pd.DataFrame(out_rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_parquet(output_path, compression="gzip", index=False)

    return {
        "status": "success",
        "output": str(output_path),
        "rows": int(len(out_df)),
        "embedding_dim": int(out_df["embedding_dim"].iloc[0]) if len(out_df) else 0,
        "model": model,
        "provider": provider or "auto",
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Embed Oregon court rules into one parquet with gte-small")
    parser.add_argument(
        "--orcp-parquet",
        default="/home/barberb/.ipfs_datasets/state_laws/OR/parsed/parquet/oregon_rules_of_civil_procedure_indexed.parquet",
    )
    parser.add_argument(
        "--orcrp-parquet",
        default="/home/barberb/.ipfs_datasets/state_laws/OR/parsed/parquet/oregon_rules_of_criminal_procedure_indexed.parquet",
    )
    parser.add_argument(
        "--local-parquet",
        default="/home/barberb/.ipfs_datasets/state_laws/OR/parsed/parquet/oregon_local_court_rules_indexed.parquet",
    )
    parser.add_argument(
        "--output-parquet",
        default="/home/barberb/.ipfs_datasets/state_laws/OR/parsed/parquet/oregon_court_rules_gte_small_embeddings.parquet",
    )
    parser.add_argument("--model", default="thenlper/gte-small")
    parser.add_argument("--provider", default="local_adapter")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--batch-size", type=int, default=64)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    report = build_embeddings_parquet(
        input_paths=[
            Path(args.orcp_parquet).expanduser().resolve(),
            Path(args.orcrp_parquet).expanduser().resolve(),
            Path(args.local_parquet).expanduser().resolve(),
        ],
        output_path=Path(args.output_parquet).expanduser().resolve(),
        model=str(args.model),
        provider=(str(args.provider).strip() or None),
        device=str(args.device),
        batch_size=int(args.batch_size),
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
