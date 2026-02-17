"""Search CLI.

Minimal CLI surface for `ipfs_datasets_py.search`.

This intentionally uses the package-level `search_tools_api` functions which
return mock results when no vector service is provided.
"""

from __future__ import annotations

import argparse
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
        prog='ipfs-datasets search',
        description='Search helpers (semantic/similarity/faceted)',
    )
    parser.add_argument('--json', action='store_true', help='Output JSON')

    sub = parser.add_subparsers(dest='command', required=True)

    p_sem = sub.add_parser('semantic', help='Semantic search (mock if no vector service)')
    p_sem.add_argument('query')
    p_sem.add_argument('--model', default='sentence-transformers/all-MiniLM-L6-v2')
    p_sem.add_argument('--top-k', type=int, default=5)
    p_sem.add_argument('--collection', default='default')
    p_sem.add_argument('--filters-json', default=None, help='Optional filters JSON object')

    p_sim = sub.add_parser('similarity', help='Similarity search (placeholder)')
    p_sim.add_argument('--embedding-json', required=True, help='Embedding as JSON array of numbers')
    p_sim.add_argument('--top-k', type=int, default=10)
    p_sim.add_argument('--threshold', type=float, default=0.5)
    p_sim.add_argument('--collection', default='default')

    p_fac = sub.add_parser('faceted', help='Faceted search (placeholder)')
    p_fac.add_argument('--query', default='')
    p_fac.add_argument('--facets-json', default=None, help='Facets JSON object mapping facet->list[str]')
    p_fac.add_argument('--aggs-json', default=None, help='Aggregations JSON array of strings')
    p_fac.add_argument('--top-k', type=int, default=20)
    p_fac.add_argument('--collection', default='default')

    return parser


async def _run_async(ns: argparse.Namespace) -> Dict[str, Any]:
    from ipfs_datasets_py.search.search_tools_api import (
        faceted_search_from_parameters,
        semantic_search_from_parameters,
        similarity_search_from_parameters,
    )

    if ns.command == 'semantic':
        filters = json.loads(ns.filters_json) if ns.filters_json else None
        return await semantic_search_from_parameters(
            vector_service=None,
            query=ns.query,
            model=ns.model,
            top_k=ns.top_k,
            collection=ns.collection,
            filters=filters,
        )

    if ns.command == 'similarity':
        embedding = json.loads(ns.embedding_json)
        if not isinstance(embedding, list):
            raise ValueError('embedding-json must be a JSON array')
        return await similarity_search_from_parameters(
            vector_service=None,
            embedding=embedding,
            top_k=ns.top_k,
            threshold=ns.threshold,
            collection=ns.collection,
        )

    if ns.command == 'faceted':
        facets = json.loads(ns.facets_json) if ns.facets_json else None
        aggs = json.loads(ns.aggs_json) if ns.aggs_json else None
        return await faceted_search_from_parameters(
            vector_service=None,
            query=ns.query,
            facets=facets,
            aggregations=aggs,
            top_k=ns.top_k,
            collection=ns.collection,
        )

    raise ValueError(f'unknown command: {ns.command}')


def main(argv: Optional[List[str]] = None) -> int:
    ns = create_parser().parse_args(argv)
    try:
        data = anyio.run(_run_async, ns)
        _print(data, json_output=bool(ns.json))
        return 0
    except KeyboardInterrupt:
        return 1
    except Exception as e:
        _print({'status': 'error', 'error': str(e)}, json_output=True)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
