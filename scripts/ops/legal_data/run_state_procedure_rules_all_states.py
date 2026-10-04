#!/usr/bin/env python3
"""Run state procedure-rules scraping for all supported states (50 + DC)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from ipfs_datasets_py.processors.legal_scrapers.state_procedure_rules_scraper import (
    scrape_state_procedure_rules,
)


async def _main() -> int:
    result = await scrape_state_procedure_rules(
        states=["all"],
        include_metadata=True,
        rate_limit_delay=0.2,
        output_dir=str(Path.home() / ".ipfs_datasets" / "state_procedure_rules"),
        write_jsonld=True,
        strict_full_text=False,
        min_full_text_chars=300,
        hydrate_rule_text=True,
        parallel_workers=10,
        per_state_retry_attempts=2,
        retry_zero_rule_states=True,
    )

    metadata = result.get("metadata") or {}
    print(
        json.dumps(
            {
                "status": result.get("status"),
                "states_count": metadata.get("states_count"),
                "rules_count": metadata.get("rules_count"),
                "family_counts": metadata.get("family_counts"),
                "zero_rule_states_count": len(metadata.get("zero_rule_states") or []),
                "jsonld_dir": metadata.get("jsonld_dir"),
            },
            indent=2,
        )
    )
    return 0


def main() -> int:
    return asyncio.run(_main())


if __name__ == "__main__":
    raise SystemExit(main())
