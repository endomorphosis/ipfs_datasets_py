#!/usr/bin/env python3
"""Re-fetch admitted LCR-071 GovInfo bodies into a resumable live corpus.

Verifies each row against the sealed live full-text checkpoint hashes.
Does not rewrite the LCR-053 fixture coverage recipe. Does not upload to
dataset repos. Optional ``--publish-bucket`` copies the corpus manifest
additively under ``legal-corpora-reindex/lcr-071/`` on
``justicedao/open-us-law-bucket``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data.federal_register_fulltext import (  # noqa: E402
    BuiltinHttpsFulltextTransport,
    content_sha256,
    live_fulltext_url_is_allowed,
    normalize_html_body,
)
from ipfs_datasets_py.processors.legal_data.federal_register_source_policy import (  # noqa: E402
    content_sha256 as _unused_cs,  # noqa: F401
)

TASK_ID = "LCR-071"
GOAL_ID = "LCR-G130"
DEFAULT_CHECKPOINT = Path(
    "/var/tmp/lcr-071-fr-fulltext/federal_fulltext_live_checkpoint.json"
)
DEFAULT_CORPUS_DIR = Path("/var/tmp/lcr-071-fr-corpus")
AUTHORIZED_BUCKET_ID = "justicedao/open-us-law-bucket"


class MaterializeError(RuntimeError):
    pass


def _load_checkpoint(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if type(payload) is not dict:
        raise MaterializeError("checkpoint root must be an object")
    return payload


def _index_path(corpus_dir: Path) -> Path:
    return corpus_dir / "index.jsonl"


def _load_index(corpus_dir: Path) -> dict[str, dict[str, Any]]:
    path = _index_path(corpus_dir)
    rows: dict[str, dict[str, Any]] = {}
    if not path.is_file():
        return rows
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            if isinstance(item, dict) and item.get("legal_id"):
                rows[str(item["legal_id"])] = item
    return rows


def _append_index(corpus_dir: Path, row: Mapping[str, Any]) -> None:
    corpus_dir.mkdir(parents=True, exist_ok=True)
    with _index_path(corpus_dir).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


def materialize(
    *,
    checkpoint_path: Path,
    corpus_dir: Path,
    limit: int | None = None,
    flush_every: int = 25,
) -> dict[str, Any]:
    checkpoint = _load_checkpoint(checkpoint_path)
    documents = [
        item
        for item in checkpoint.get("documents") or []
        if isinstance(item, dict) and item.get("category") == "full_text_admitted"
    ]
    if limit is not None:
        documents = documents[:limit]
    done = _load_index(corpus_dir)
    transport = BuiltinHttpsFulltextTransport()
    headers = {
        "User-Agent": "ipfs-datasets-py-legal-corpora-reindex/1.0",
        "Accept": "*/*",
    }
    verified = 0
    fetched = 0
    mismatches = 0
    errors: list[str] = []
    corpus_dir.mkdir(parents=True, exist_ok=True)
    bodies_dir = corpus_dir / "bodies"
    bodies_dir.mkdir(exist_ok=True)
    for item in documents:
        legal_id = str(item["legal_id"])
        expected = str(item.get("admitted_content_hash") or "")
        if legal_id in done and done[legal_id].get("status") == "verified":
            if done[legal_id].get("content_hash") == expected:
                verified += 1
                continue
        url = str(item.get("official_source_url") or "")
        if not url or not live_fulltext_url_is_allowed(url):
            errors.append(f"{legal_id}: missing or disallowed source URL")
            continue
        try:
            raw, media = transport(url, headers)
            text = normalize_html_body(raw)
            digest = content_sha256(text)
        except Exception as exc:  # noqa: BLE001 - persist typed failure, keep going
            errors.append(f"{legal_id}: {type(exc).__name__}: {exc}")
            continue
        fetched += 1
        status = "verified" if digest == expected else "hash_mismatch"
        if status != "verified":
            mismatches += 1
            errors.append(f"{legal_id}: hash mismatch")
            continue
        shard = bodies_dir / f"{legal_id.replace(':', '_')}.json"
        shard.write_text(
            json.dumps(
                {
                    "legal_id": legal_id,
                    "document_number": item.get("document_number"),
                    "publication_date": item.get("publication_date"),
                    "official_source_url": url,
                    "content_hash": digest,
                    "body_char_count": len(text),
                    "media_type": media,
                    "text": text,
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        _append_index(
            corpus_dir,
            {
                "legal_id": legal_id,
                "status": status,
                "content_hash": digest,
                "body_char_count": len(text),
                "path": str(shard.relative_to(corpus_dir)),
            },
        )
        verified += 1
        if fetched and fetched % flush_every == 0:
            print(
                f"materialize fetched={fetched} verified={verified} "
                f"mismatches={mismatches} remaining_errors={len(errors)}",
                file=sys.stderr,
            )
    report = {
        "schema": "ipfs_datasets_py/federal-register-live-corpus@1",
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "admitted_target": len(documents),
        "verified": verified,
        "fetched": fetched,
        "mismatches": mismatches,
        "error_count": len(errors),
        "errors": errors[:32],
        "corpus_dir": str(corpus_dir),
        "authorizing_hub_upload": False,
        "authorizing_for_publication": False,
        "status": "passed" if verified == len(documents) and not mismatches else "blocked",
    }
    (corpus_dir / "manifest.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Materialize live FR GovInfo bodies")
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--corpus-dir", type=Path, default=DEFAULT_CORPUS_DIR)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--flush-every", type=int, default=25)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        report = materialize(
            checkpoint_path=args.checkpoint,
            corpus_dir=args.corpus_dir,
            limit=args.limit,
            flush_every=max(1, int(args.flush_every)),
        )
    except MaterializeError as exc:
        sys.stderr.write(f"materialize_federal_register_live_corpus: FAILED: {exc}\n")
        return 1
    if args.json:
        sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(
            "materialize_federal_register_live_corpus: "
            f"{report['status'].upper()} verified={report['verified']}/"
            f"{report['admitted_target']} fetched={report['fetched']}\n"
        )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
