"""Offline classification of the 2026-10-14 legal Hub snapshot.

``load_inventory`` reads the frozen fixture. ``list_public_datasets`` is the
live lister. Tests must pass an opener and must not call the network. The
lister sends no Authorization header and does not read ``HF_TOKEN``,
``HF_TOKEN_FILE``, or the Hugging Face token cache.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Callable, Mapping
from urllib.parse import quote

from ipfs_datasets_py.processors.legal_scrapers.world_law.export_norm import (
    choose_export_command,
    is_world_v11_shard,
)

FIXTURE_PATH = Path(__file__).with_name("hub_inventory_20261014.json")

_Fetch = Callable[[str], tuple[object, str | None]]


def load_inventory(path: Path | None = None) -> dict[str, object]:
    fixture = FIXTURE_PATH if path is None else path
    document = json.loads(fixture.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("inventory fixture must be a JSON object")
    return document


def classify_inventory(document: Mapping[str, object] | None = None) -> dict[str, object]:
    """Apply the family rules to the frozen snapshot."""

    doc = load_inventory() if document is None else document
    municipal = [_classify_municipal(row) for row in _rows(doc, "municipal")]
    return {
        "orgs": doc["orgs"],
        "family_partition": doc["family_partition"],
        "municipal": municipal,
        "missing_municipal_irs": [
            row["slug"] for row in municipal if row["ir_present"] is False
        ],
        "ir_creates": [row["slug"] for row in municipal if row["ir_action"] == "create"],
        "html_norm_exports": [
            row["slug"] for row in municipal if row["ir_action"] == "export_norm_html"
        ],
        "calendar_stale": list(doc["calendar_stale_slugs"]),
        "alias_pairs": list(doc["alias_pairs"]),
        "subnational_exact": list(doc["subnational_exact"]),
        "uk_local_acts": dict(doc["uk_local_acts"]),
        "common_crawl": list(doc["common_crawl"]),
        "non_corpus": list(doc["non_corpus"]),
        "world": _classify_world(doc["world"]),
        "norm_destinations": list(doc["norm_destinations"]),
        "blocked_repos": list(doc["blocked_repos"]),
        "legacy_american": dict(doc["legacy_american"]),
        "models": list(doc["models"]),
    }


def list_public_datasets(org: str, *, opener: _Fetch | None = None) -> list[dict[str, object]]:
    """List public datasets for one org.

    The default opener talks to the Hub. Callers in tests pass ``opener`` and
    do not use this default. No token is read and no Authorization header is set.
    """

    if not org or any(char in org for char in "/\\ "):
        raise ValueError("org must be a single public namespace")
    fetch = opener or _fetch_public
    url: str | None = f"https://huggingface.co/api/datasets?author={quote(org)}&limit=100"
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    while url and url not in seen:
        seen.add(url)
        payload, nxt = fetch(url)
        if not isinstance(payload, list):
            raise ValueError("dataset list response must be a JSON array")
        for item in payload:
            if isinstance(item, dict):
                rows.append(item)
        url = nxt
    return rows


def _fetch_public(url: str) -> tuple[object, str | None]:
    request = urllib.request.Request(url, method="GET")
    request.add_header("Accept", "application/json")
    if request.has_header("Authorization"):
        raise RuntimeError("inventory lister must not send Authorization")
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
        link = response.headers.get("Link")
    return payload, _next_link(link)


def _next_link(link: str | None) -> str | None:
    if not link:
        return None
    for part in link.split(","):
        if 'rel="next"' not in part:
            continue
        start = part.find("<")
        end = part.find(">")
        if start >= 0 and end > start:
            return part[start + 1 : end]
    return None


def _classify_municipal(row: Mapping[str, object]) -> dict[str, object]:
    slug = str(row["slug"])
    siblings = _siblings(str(row["layout"]))
    command = choose_export_command(slug, siblings)
    ir_present = bool(row["ir_present"])
    if ir_present:
        action = "present"
    elif command == "export_norm_html":
        action = "export_norm_html"
    elif command == "load_sharded_laws":
        action = "create"
    else:
        action = command
    classified = dict(row)
    classified["command"] = command
    classified["ir_action"] = action
    classified["default_query_repo"] = f"justicedao/ipfs_{slug}_laws_ir"
    classified["sha_gap"] = "unproven"
    return classified


def _classify_world(world: object) -> dict[str, object]:
    if not isinstance(world, dict):
        raise ValueError("world inventory must be an object")
    classified = dict(world)
    samples = world.get("sample_basenames")
    if not isinstance(samples, list):
        raise ValueError("world inventory needs sample_basenames")
    classified["law_shards"] = [name for name in samples if is_world_v11_shard(str(name))]
    classified["ignored"] = [name for name in samples if not is_world_v11_shard(str(name))]
    return classified


def _siblings(layout: str) -> list[str]:
    if layout == "exact":
        return ["data/laws.parquet"]
    if layout == "text":
        return ["data/laws-00001.parquet"]
    if layout == "html":
        return ["data/example_html.parquet"]
    if layout == "mixed":
        return ["data/laws-00001.parquet", "data/example_html.parquet"]
    raise ValueError(f"unknown municipal layout: {layout}")


def _rows(document: Mapping[str, object], key: str) -> list[Mapping[str, object]]:
    rows = document[key]
    if not isinstance(rows, list):
        raise ValueError(f"{key} must be a list")
    return [row for row in rows if isinstance(row, dict)]
