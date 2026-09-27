"""Check a local legacy stage in a throwaway catalog. Does not migrate live data."""

from __future__ import annotations

import argparse
import json

from ipfs_datasets_py.ducklake.legal_search_catalog import (
    LegalSearchCatalogError,
    assert_legal_search_path,
    open_legal_search_catalog,
)
from ipfs_datasets_py.ducklake.legal_search_legacy import (
    register_legacy_pins,
    vector_spaces_for,
)
from ipfs_datasets_py.processors.legal_data.justicedao_release_registry import (
    build_release_registry,
)

_REPOS = (
    "justicedao/american_municipal_law",
    "justicedao/ipfs_caselaw_access_project",
    "justicedao/Caselaw_Access_Project_embeddings",
    "justicedao/ipfs_netherlands_laws",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staging-root", required=True)
    parser.add_argument("--catalog", required=True)
    args = parser.parse_args()
    try:
        assert_legal_search_path(args.catalog)
    except LegalSearchCatalogError as exc:
        raise SystemExit(str(exc)) from exc
    releases = build_release_registry(_REPOS)
    connection = open_legal_search_catalog(args.catalog)
    try:
        results = register_legacy_pins(connection, releases, args.staging_root)
        payload = {
            "pins": [
                {"hf_repo": item.hf_repo, "status": item.status, "records": item.records}
                for item in results
            ],
            "municipal_spaces": [
                {"space": space, "fuse_with_bm25": fuse}
                for space, fuse in vector_spaces_for(connection, "us:municipal")
            ],
            "research_only": True,
            "authoritative": False,
        }
    finally:
        connection.close()
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
