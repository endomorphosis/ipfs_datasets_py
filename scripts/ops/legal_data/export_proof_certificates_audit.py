#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from ipfs_datasets_py.processors.legal_data.reasoner.serialization import load_proof_store


def _write_json(path: str, payload: Dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def build_proof_certificate_audit(proof_store: Dict[str, Any]) -> Dict[str, Any]:
    entries: List[Dict[str, Any]] = []
    backend_counts: Dict[str, int] = {}
    format_counts: Dict[str, int] = {}
    certificate_ids = set()
    duplicate_certificate_ids = set()
    missing_trace_map = 0

    for proof_id in sorted(proof_store.keys()):
        proof = proof_store[proof_id]
        certs = list(getattr(proof, "certificates", []) or [])
        trace_map = dict(getattr(proof, "certificate_trace_map", {}) or {})

        proof_entry: Dict[str, Any] = {
            "proof_id": proof_id,
            "proof_hash": str(getattr(proof, "proof_hash", "") or ""),
            "certificate_count": len(certs),
            "certificates": [],
        }

        for cert in certs:
            cid = str(getattr(cert, "certificate_id", "") or "")
            backend = str(getattr(cert, "backend", "") or "")
            fmt = str(getattr(cert, "format", "") or "")
            normalized_hash = str(getattr(cert, "normalized_hash", "") or "")

            if cid in certificate_ids:
                duplicate_certificate_ids.add(cid)
            certificate_ids.add(cid)

            backend_counts[backend] = backend_counts.get(backend, 0) + 1
            format_counts[fmt] = format_counts.get(fmt, 0) + 1

            refs = trace_map.get(cid) or []
            if not refs:
                missing_trace_map += 1

            proof_entry["certificates"].append(
                {
                    "certificate_id": cid,
                    "backend": backend,
                    "format": fmt,
                    "normalized_hash": normalized_hash,
                    "trace_ref_count": len(refs),
                    "trace_refs": [{"kind": r.kind, "id": r.id} for r in refs],
                }
            )

        entries.append(proof_entry)

    return {
        "summary": {
            "proof_count": len(proof_store),
            "certificate_count": len(certificate_ids),
            "duplicate_certificate_id_count": len(duplicate_certificate_ids),
            "missing_trace_map_count": missing_trace_map,
            "backend_counts": dict(sorted(backend_counts.items(), key=lambda kv: kv[0])),
            "format_counts": dict(sorted(format_counts.items(), key=lambda kv: kv[0])),
        },
        "duplicate_certificate_ids": sorted(duplicate_certificate_ids),
        "proofs": entries,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Export proof certificate + trace-map audit artifact")
    ap.add_argument(
        "--proof-store",
        default="artifacts/formal_logic_tmp_verify/federal/proofs.json",
        help="Proof store JSON path",
    )
    ap.add_argument(
        "--output",
        default="artifacts/formal_logic_tmp_verify/federal/proof_certificate_audit.json",
        help="Output audit JSON path",
    )
    args = ap.parse_args()

    proofs = load_proof_store(args.proof_store)
    audit = build_proof_certificate_audit(proofs)
    _write_json(args.output, audit)

    summary = audit.get("summary") or {}
    print(f"proof_count={summary.get('proof_count')}")
    print(f"certificate_count={summary.get('certificate_count')}")
    print(f"duplicate_certificate_id_count={summary.get('duplicate_certificate_id_count')}")
    print(f"missing_trace_map_count={summary.get('missing_trace_map_count')}")
    print(f"output={args.output}")


if __name__ == "__main__":
    main()
