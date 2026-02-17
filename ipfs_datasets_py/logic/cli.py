"""Logic CLI.

Minimal CLI surface for the `ipfs_datasets_py.logic` feature.

Design constraints:
- Keep module import light (import feature code inside handlers)
- Prefer stable wrapper functions where available
"""

from __future__ import annotations

import argparse
import inspect
import json
from typing import Any, Dict, List, Optional

import anyio


def _print(data: Any, *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(data, indent=2, default=str))
    else:
        print(data)


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ipfs-datasets logic",
        description="Logic tools (FOL + deontic + temporal-deontic helpers)",
    )
    parser.add_argument("--json", action="store_true", help="Output JSON")

    sub = parser.add_subparsers(dest="command", required=True)

    p_fol = sub.add_parser("convert-fol", help="Convert text to FOL")
    p_fol.add_argument("text", help="Input text")

    p_deontic = sub.add_parser("convert-deontic", help="Convert legal text to deontic form")
    p_deontic.add_argument("text", help="Input legal text")

    p_norm = sub.add_parser("analyze-normative", help="Analyze a normative sentence")
    p_norm.add_argument("sentence", help="Sentence to analyze")
    p_norm.add_argument("--document-type", default="legal")

    p_add = sub.add_parser("add-theorem", help="Add a temporal-deontic theorem")
    p_add.add_argument("--operator", required=True, choices=["OBLIGATION", "PERMISSION", "PROHIBITION"])
    p_add.add_argument("--proposition", required=True)
    p_add.add_argument("--agent-name", default="Unspecified Party")
    p_add.add_argument("--jurisdiction", default="Federal")
    p_add.add_argument("--legal-domain", default="general")
    p_add.add_argument("--source-case", default="CLI")
    p_add.add_argument("--precedent-strength", type=float, default=0.8)
    p_add.add_argument("--start-date", default=None)
    p_add.add_argument("--end-date", default=None)

    p_query = sub.add_parser("query-theorems", help="Query temporal-deontic theorems")
    p_query.add_argument("query", help="Query string")
    p_query.add_argument("--operator-filter", default="all")
    p_query.add_argument("--jurisdiction", default="all")
    p_query.add_argument("--legal-domain", default="all")
    p_query.add_argument("--limit", type=int, default=10)
    p_query.add_argument("--min-relevance", type=float, default=0.5)

    p_check = sub.add_parser("check-document", help="Check a document for consistency")
    p_check.add_argument("document_text", help="Document text")
    p_check.add_argument("--document-id", default=None)
    p_check.add_argument("--jurisdiction", default="Federal")
    p_check.add_argument("--legal-domain", default="general")
    p_check.add_argument("--temporal-context", default="current_time")

    return parser


async def _run_async(ns: argparse.Namespace) -> Dict[str, Any]:
    cmd = ns.command

    if cmd == "convert-fol":
        from ipfs_datasets_py.logic.api import convert_text_to_fol

        result = convert_text_to_fol(ns.text)
        if inspect.isawaitable(result):
            result = await result
        return result

    if cmd == "convert-deontic":
        from ipfs_datasets_py.logic.api import convert_legal_text_to_deontic

        result = convert_legal_text_to_deontic(ns.text)
        if inspect.isawaitable(result):
            result = await result
        return result

    if cmd == "analyze-normative":
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import analyze_normative_sentence

        return {
            "sentence": ns.sentence,
            "document_type": ns.document_type,
            "analysis": analyze_normative_sentence(ns.sentence, ns.document_type),
        }

    if cmd == "add-theorem":
        from ipfs_datasets_py.logic.integration.domain.temporal_deontic_api import add_theorem_from_parameters

        params: Dict[str, Any] = {
            "operator": ns.operator,
            "proposition": ns.proposition,
            "agent_name": ns.agent_name,
            "jurisdiction": ns.jurisdiction,
            "legal_domain": ns.legal_domain,
            "source_case": ns.source_case,
            "precedent_strength": ns.precedent_strength,
        }
        if ns.start_date:
            params["start_date"] = ns.start_date
        if ns.end_date:
            params["end_date"] = ns.end_date
        return await add_theorem_from_parameters(params)

    if cmd == "query-theorems":
        from ipfs_datasets_py.logic.integration.domain.temporal_deontic_api import query_theorems_from_parameters

        params = {
            "query": ns.query,
            "operator_filter": ns.operator_filter,
            "jurisdiction": ns.jurisdiction,
            "legal_domain": ns.legal_domain,
            "limit": ns.limit,
            "min_relevance": ns.min_relevance,
        }
        return await query_theorems_from_parameters(params)

    if cmd == "check-document":
        from ipfs_datasets_py.logic.integration.domain.temporal_deontic_api import (
            check_document_consistency_from_parameters,
        )

        params = {
            "document_text": ns.document_text,
            "document_id": ns.document_id,
            "jurisdiction": ns.jurisdiction,
            "legal_domain": ns.legal_domain,
            "temporal_context": ns.temporal_context,
        }
        return await check_document_consistency_from_parameters(params)

    raise ValueError(f"Unknown command: {cmd}")


def main(argv: Optional[List[str]] = None) -> int:
    ns = create_parser().parse_args(argv)
    try:
        data = anyio.run(_run_async, ns)
        _print(data, json_output=bool(ns.json))
        return 0
    except KeyboardInterrupt:
        return 1
    except Exception as e:
        _print({"success": False, "error": str(e)}, json_output=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
