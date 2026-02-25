"""Build per-jurisdiction Common Crawl pointer inventories for US states and territories.

This script maps pointer rows to jurisdictions using the agency domain inventory
(`artifacts/state_agencies_all.jsonl`) and writes:
  - summary counts by jurisdiction
  - optional partitioned parquet pointer dataset (partitioned by jurisdiction)
  - run manifest with coverage details
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Set, Tuple

import duckdb


STATE_AND_TERRITORY_CODES: Set[str] = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC", "AS", "GU", "MP", "PR", "VI",
}


def _norm(text: str) -> str:
    return (text or "").strip().lower()


def _load_jurisdiction_domains(agencies_jsonl: Path) -> Tuple[Dict[str, Set[str]], Dict[str, List[str]]]:
    by_jurisdiction: Dict[str, Set[str]] = {code: set() for code in STATE_AND_TERRITORY_CODES}
    domain_to_codes: Dict[str, Set[str]] = {}

    with agencies_jsonl.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            jurisdiction = (row.get("jurisdiction") or "").strip().upper()
            if jurisdiction not in STATE_AND_TERRITORY_CODES:
                continue

            domain = _norm(str(row.get("domain") or ""))
            if not domain:
                continue

            by_jurisdiction[jurisdiction].add(domain)
            domain_to_codes.setdefault(domain, set()).add(jurisdiction)

    ambiguous: Dict[str, List[str]] = {}
    for domain, codes in domain_to_codes.items():
        if len(codes) > 1:
            ambiguous[domain] = sorted(codes)

    if ambiguous:
        ambiguous_domains = set(ambiguous.keys())
        for code in by_jurisdiction:
            by_jurisdiction[code] = {d for d in by_jurisdiction[code] if d not in ambiguous_domains}

    return by_jurisdiction, ambiguous


def _flatten_domains(mapping: Dict[str, Set[str]]) -> List[Tuple[str, str]]:
    rows: List[Tuple[str, str]] = []
    for jurisdiction, domains in sorted(mapping.items()):
        for domain in sorted(domains):
            rows.append((jurisdiction, domain))
    return rows


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_csv(path: Path, headers: Sequence[str], rows: Iterable[Sequence[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [",".join(headers)]
    for row in rows:
        vals = []
        for value in row:
            cell = str(value)
            if any(ch in cell for ch in [",", '"', "\n"]):
                cell = '"' + cell.replace('"', '""') + '"'
            vals.append(cell)
        lines.append(",".join(vals))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build per-jurisdiction pointer inventories from pointers.parquet")
    parser.add_argument(
        "--pointers-parquet",
        type=Path,
        required=True,
        help="Path to pointers.parquet",
    )
    parser.add_argument(
        "--agencies-jsonl",
        type=Path,
        default=Path("artifacts/state_agencies_all.jsonl"),
        help="Path to state/territory agency JSONL with jurisdiction + domain fields",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("artifacts/jurisdiction_pointer_inventory"),
        help="Output directory",
    )
    parser.add_argument(
        "--write-partitioned-parquet",
        action="store_true",
        help="Write partitioned parquet dataset by jurisdiction",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output parquet dataset directory if present",
    )
    parser.add_argument(
        "--write-url-lists",
        action="store_true",
        help="Write one cleaned URL list (.txt) per jurisdiction",
    )
    return parser


def _write_jurisdiction_url_lists(
    con: duckdb.DuckDBPyConnection,
    *,
    matched_query: str,
    out_dir: Path,
    jurisdiction_codes: Sequence[str],
    overwrite: bool,
) -> Dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    output_map: Dict[str, str] = {}

    for code in jurisdiction_codes:
        out_path = out_dir / f"{code.lower()}_urls_from_pointers_cleaned.txt"
        if out_path.exists() and not overwrite:
            output_map[code] = str(out_path)
            continue

        query = f"""
            SELECT DISTINCT lower(url) AS url
            FROM ({matched_query})
            WHERE jurisdiction = '{code}'
              AND url IS NOT NULL
            ORDER BY 1
        """
        cursor = con.execute(query)

        with out_path.open("w", encoding="utf-8") as handle:
            while True:
                batch = cursor.fetchmany(100_000)
                if not batch:
                    break
                for row in batch:
                    value = (row[0] or "").strip()
                    if value:
                        handle.write(value)
                        handle.write("\n")

        output_map[code] = str(out_path)

    return output_map


def run(argv: Sequence[str] | None = None) -> Dict[str, object]:
    args = _build_parser().parse_args(argv)

    pointers_parquet = args.pointers_parquet.expanduser().resolve()
    agencies_jsonl = args.agencies_jsonl.expanduser().resolve()
    out_dir = args.out_dir.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if not pointers_parquet.exists():
        raise FileNotFoundError(f"Pointers parquet not found: {pointers_parquet}")
    if not agencies_jsonl.exists():
        raise FileNotFoundError(f"Agencies JSONL not found: {agencies_jsonl}")

    domains_by_jurisdiction, ambiguous_domains = _load_jurisdiction_domains(agencies_jsonl)
    domain_rows = _flatten_domains(domains_by_jurisdiction)

    if not domain_rows:
        raise RuntimeError("No jurisdiction domain mappings found from agencies JSONL")

    con = duckdb.connect()
    con.execute("CREATE TEMP TABLE jurisdiction_domains (jurisdiction VARCHAR, domain VARCHAR)")
    con.executemany("INSERT INTO jurisdiction_domains VALUES (?, ?)", domain_rows)

    pointers_parquet_sql = str(pointers_parquet).replace("'", "''")
    matched_query = f"""
        SELECT
            p.*,
            jd.jurisdiction
        FROM read_parquet('{pointers_parquet_sql}') p
        JOIN jurisdiction_domains jd
          ON lower(p.domain) = jd.domain
    """

    summary_rows = con.execute(
        f"""
        SELECT
            jurisdiction,
            count(*) AS pointer_count,
            count(DISTINCT lower(domain)) AS matched_domain_count,
            count(DISTINCT lower(url)) AS distinct_url_count
        FROM ({matched_query})
        GROUP BY 1
        ORDER BY 1
        """
    ).fetchall()

    summary_map = {
        str(row[0]): {
            "pointer_count": int(row[1]),
            "matched_domain_count": int(row[2]),
            "distinct_url_count": int(row[3]),
        }
        for row in summary_rows
    }

    domain_count_map = {code: len(domains_by_jurisdiction.get(code, set())) for code in sorted(STATE_AND_TERRITORY_CODES)}
    missing_jurisdictions = [code for code in sorted(STATE_AND_TERRITORY_CODES) if summary_map.get(code, {}).get("pointer_count", 0) == 0]

    summary_csv = out_dir / "jurisdiction_pointer_counts.csv"
    _write_csv(
        summary_csv,
        headers=["jurisdiction", "agency_domain_count", "matched_domain_count", "pointer_count", "distinct_url_count"],
        rows=[
            (
                code,
                domain_count_map.get(code, 0),
                summary_map.get(code, {}).get("matched_domain_count", 0),
                summary_map.get(code, {}).get("pointer_count", 0),
                summary_map.get(code, {}).get("distinct_url_count", 0),
            )
            for code in sorted(STATE_AND_TERRITORY_CODES)
        ],
    )

    parquet_dataset_dir = out_dir / "pointers_by_jurisdiction"
    if args.write_partitioned_parquet:
        if parquet_dataset_dir.exists() and args.overwrite:
            import shutil

            shutil.rmtree(parquet_dataset_dir)
        con.execute(
            f"""
            COPY ({matched_query})
            TO '{str(parquet_dataset_dir).replace("'", "''")}'
            (FORMAT PARQUET, PARTITION_BY (jurisdiction), COMPRESSION ZSTD)
            """
        )

    url_list_outputs: Dict[str, str] = {}
    url_lists_dir = out_dir / "url_lists"
    if args.write_url_lists:
        url_list_outputs = _write_jurisdiction_url_lists(
            con,
            matched_query=matched_query,
            out_dir=url_lists_dir,
            jurisdiction_codes=sorted(STATE_AND_TERRITORY_CODES),
            overwrite=args.overwrite,
        )

    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    manifest = {
        "run_id": run_id,
        "pointers_parquet": str(pointers_parquet),
        "agencies_jsonl": str(agencies_jsonl),
        "out_dir": str(out_dir),
        "write_partitioned_parquet": bool(args.write_partitioned_parquet),
        "partitioned_parquet_dir": str(parquet_dataset_dir) if args.write_partitioned_parquet else None,
        "write_url_lists": bool(args.write_url_lists),
        "url_lists_dir": str(url_lists_dir) if args.write_url_lists else None,
        "url_list_files": url_list_outputs,
        "jurisdiction_count": len(STATE_AND_TERRITORY_CODES),
        "coverage": {
            "with_pointers": len(STATE_AND_TERRITORY_CODES) - len(missing_jurisdictions),
            "missing": missing_jurisdictions,
        },
        "ambiguous_domains_removed": ambiguous_domains,
        "agency_domain_count_by_jurisdiction": domain_count_map,
        "summary_by_jurisdiction": summary_map,
        "summary_csv": str(summary_csv),
    }

    manifest_path = out_dir / f"jurisdiction_pointer_inventory_{run_id}.json"
    _write_json(manifest_path, manifest)

    print(
        json.dumps(
            {
                "manifest": str(manifest_path),
                "summary_csv": str(summary_csv),
                "with_pointers": manifest["coverage"]["with_pointers"],
                "missing_jurisdictions": missing_jurisdictions,
                "partitioned_parquet_dir": str(parquet_dataset_dir) if args.write_partitioned_parquet else None,
                "url_lists_dir": str(url_lists_dir) if args.write_url_lists else None,
            },
            indent=2,
        )
    )

    return manifest


if __name__ == "__main__":
    run()
