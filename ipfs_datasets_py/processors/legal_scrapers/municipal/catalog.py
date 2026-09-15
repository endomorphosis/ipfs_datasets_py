"""US municipal jurisdiction catalog from Hugging Face and local GNIS inventory."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache
import json
import time
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

HUB_DATASET_ID = "endomorphosis/american_municipal_law"
JUSTICEDAO_DATASET_ID = "justicedao/american_municipal_law"
USER_AGENT = "ipfs-datasets-municipal-catalog/1.0"

_PACKAGE_DIR = Path(__file__).resolve().parent
_DATA_DIR = _PACKAGE_DIR / "data"
_HUB_CATALOG_PATH = _DATA_DIR / "hub_jurisdictions.jsonl"
_LOCAL_TOWNS_PATH = _PACKAGE_DIR.parent / "us_towns_and_counties_urls.jsonl"

# Legacy short codes from the 23-city placeholder, mapped to GNIS.
LEGACY_CITY_ALIASES = {
    "NYC": "2395220",
    "LAX": "2410877",
    "CHI": "428803",
    "HOU": "2410796",
    "PHX": "2411414",
    "PHI": "2389618",
    "SAN": "2411777",
    "DAL": "2410290",
    "SJC": "2411794",
    "AUS": "2409841",
    "JAX": "2405059",
    "FTW": "2410531",
    "CLT": "2404034",
    "SEA": "2411856",
    "DEN": "2410342",
    "BOS": "617401",
    "DET": "2392321",
    "NSH": "1653961",
    "PDX": "2411471",
    "MIA": "2404209",
    "ATL": "2403163",
    "SFO": "2411786",
    "WDC": "531871",
}


@dataclass(frozen=True)
class MunicipalJurisdiction:
    gnis: str
    place_name: str
    state_code: str
    source_urls: tuple[str, ...] = ()
    on_hub: bool = False
    hub_sections: int = 0
    hub_dataset_id: str = HUB_DATASET_ID
    status: str = "unknown"

    @property
    def key(self) -> str:
        return self.gnis

    @property
    def display_name(self) -> str:
        if self.state_code:
            return f"{self.place_name}, {self.state_code}"
        return self.place_name

    def html_parquet_path(self) -> str:
        return f"american_law/data/{self.gnis}_html.parquet"

    def citation_parquet_path(self) -> str:
        return f"american_law/data/{self.gnis}_citation.parquet"

    def metadata_path(self) -> str:
        return f"american_law/metadata/{self.gnis}.json"


def _http_json(url: str) -> Any:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=120) as response:
        payload = json.loads(response.read().decode("utf-8"))
        link = response.headers.get("Link") or ""
    return payload, link


def list_hub_metadata_paths() -> list[str]:
    items: list[str] = []
    url = (
        "https://huggingface.co/api/datasets/endomorphosis/american_municipal_law/"
        "tree/main/american_law/metadata?recursive=1&expand=false"
    )
    seen: set[str] = set()
    while url and url not in seen:
        seen.add(url)
        payload, link = _http_json(url)
        if not isinstance(payload, list):
            break
        for item in payload:
            path = str(item.get("path") or "")
            if item.get("type") == "file" and path.endswith(".json"):
                items.append(path)
        nxt = None
        for part in link.split(","):
            if 'rel="next"' in part:
                nxt = part.split(";")[0].strip().strip("<>")
        if nxt is None and payload:
            last = quote(str(payload[-1].get("path") or ""), safe="/")
            nxt = (
                "https://huggingface.co/api/datasets/endomorphosis/american_municipal_law/"
                f"tree/main/american_law/metadata?recursive=1&expand=false&after={last}"
            )
        url = nxt
        if payload and len(payload) < 1000:
            break
    return items


def harvest_hub_municipal_catalog(
    *,
    dest: Path | None = None,
    max_workers: int = 16,
) -> Path:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    dest_path = dest or _HUB_CATALOG_PATH
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    paths = list_hub_metadata_paths()

    existing = {str(row.get("gnis") or ""): row for row in _load_jsonl(dest_path)}

    def _one(path: str) -> dict[str, Any] | None:
        gnis = Path(path).stem
        if gnis in existing:
            return existing[gnis]
        url = f"https://huggingface.co/datasets/{HUB_DATASET_ID}/resolve/main/{path}"
        last_error: Exception | None = None
        for attempt in range(1, 5):
            request = Request(url, headers={"User-Agent": USER_AGENT})
            try:
                with urlopen(request, timeout=60) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if not isinstance(payload, dict):
                    return None
                gnis = str(payload.get("gnis") or Path(path).stem)
                return {
                    "gnis": gnis,
                    "place_name": str(payload.get("place_name") or ""),
                    "state_code": str(payload.get("state_code") or "").upper(),
                    "hub_sections": int(payload.get("total_sections") or 0),
                    "on_hub": True,
                    "hub_dataset_id": str(payload.get("source") or HUB_DATASET_ID),
                }
            except HTTPError as exc:
                last_error = exc
                if exc.code in {404, 410}:
                    return None
                time.sleep(min(8, 0.4 * attempt))
            except (URLError, TimeoutError, OSError) as exc:
                last_error = exc
                time.sleep(min(8, 0.4 * attempt))
        return None

    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futs = {pool.submit(_one, path): path for path in paths}
        for fut in as_completed(futs):
            row = fut.result()
            if row:
                rows.append(row)
    by_gnis = {str(row.get("gnis") or ""): row for row in rows if row.get("gnis")}
    ordered = sorted(by_gnis.values(), key=lambda item: (item.get("state_code") or "", item.get("place_name") or "", item.get("gnis") or ""))
    with dest_path.open("w", encoding="utf-8") as handle:
        for row in ordered:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return dest_path


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def _urls_from_row(row: Mapping[str, Any]) -> tuple[str, ...]:
    values: list[str] = []
    raw_list = row.get("source_urls")
    if isinstance(raw_list, list):
        values.extend(str(item).strip() for item in raw_list if str(item).strip())
    raw = str(row.get("source_url") or "").strip()
    if raw:
        values.extend(part.strip() for part in raw.split(",") if part.strip())
    seen: set[str] = set()
    ordered: list[str] = []
    for item in values:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return tuple(ordered)


@lru_cache(maxsize=1)
def load_municipal_jurisdictions() -> tuple[MunicipalJurisdiction, ...]:
    by_gnis: dict[str, MunicipalJurisdiction] = {}
    for row in _load_jsonl(_LOCAL_TOWNS_PATH):
        gnis = str(row.get("gnis") or "").strip()
        if not gnis:
            continue
        by_gnis[gnis] = MunicipalJurisdiction(
            gnis=gnis,
            place_name=str(row.get("place_name") or ""),
            state_code=str(row.get("state_code") or "").upper(),
            source_urls=_urls_from_row(row),
            on_hub=False,
            status=str(row.get("status") or "not_scraped"),
        )
    for row in _load_jsonl(_HUB_CATALOG_PATH):
        gnis = str(row.get("gnis") or "").strip()
        if not gnis:
            continue
        existing = by_gnis.get(gnis)
        by_gnis[gnis] = MunicipalJurisdiction(
            gnis=gnis,
            place_name=str(row.get("place_name") or (existing.place_name if existing else "")),
            state_code=str(row.get("state_code") or (existing.state_code if existing else "")).upper(),
            source_urls=existing.source_urls if existing else (),
            on_hub=True,
            hub_sections=int(row.get("hub_sections") or 0),
            hub_dataset_id=str(row.get("hub_dataset_id") or HUB_DATASET_ID),
            status="on_hub",
        )
    return tuple(sorted(by_gnis.values(), key=lambda item: (item.state_code, item.place_name.lower(), item.gnis)))


def municipal_catalog_summary() -> dict[str, Any]:
    entries = load_municipal_jurisdictions()
    on_hub = [item for item in entries if item.on_hub]
    by_state: dict[str, int] = {}
    hub_by_state: dict[str, int] = {}
    for item in entries:
        by_state[item.state_code] = by_state.get(item.state_code, 0) + 1
        if item.on_hub:
            hub_by_state[item.state_code] = hub_by_state.get(item.state_code, 0) + 1
    return {
        "dataset_id": HUB_DATASET_ID,
        "jurisdiction_count": len(entries),
        "hub_jurisdiction_count": len(on_hub),
        "local_inventory_count": sum(1 for item in entries if item.source_urls),
        "state_count": len([code for code in by_state if code]),
        "by_state": dict(sorted(by_state.items())),
        "hub_by_state": dict(sorted(hub_by_state.items())),
        "not_legal_advice": True,
    }


def get_municipal_jurisdiction(key: str) -> MunicipalJurisdiction:
    text = str(key or "").strip()
    if not text:
        raise KeyError("Unknown municipal jurisdiction: ")
    alias = LEGACY_CITY_ALIASES.get(text.upper())
    if alias:
        text = alias
    entries = load_municipal_jurisdictions()
    for item in entries:
        if item.gnis == text:
            return item
    needle = text.lower()
    matches = [
        item
        for item in entries
        if needle == item.place_name.lower()
        or needle == item.display_name.lower()
        or needle in item.place_name.lower()
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        # Prefer exact place name, then Hub-published.
        exact = [item for item in matches if item.place_name.lower() == needle]
        pool = exact or [item for item in matches if item.on_hub] or matches
        return pool[0]
    raise KeyError(f"Unknown municipal jurisdiction: {key}")


def list_municipal_jurisdictions(
    *,
    state: Optional[str] = None,
    on_hub: Optional[bool] = None,
    query: Optional[str] = None,
    limit: Optional[int] = None,
) -> list[MunicipalJurisdiction]:
    entries = list(load_municipal_jurisdictions())
    if state:
        code = state.strip().upper()
        entries = [item for item in entries if item.state_code == code]
    if on_hub is not None:
        entries = [item for item in entries if item.on_hub is on_hub]
    if query:
        needle = query.strip().lower()
        entries = [
            item
            for item in entries
            if needle in item.place_name.lower()
            or needle in item.display_name.lower()
            or needle == item.gnis
        ]
    if limit is not None:
        entries = entries[: max(0, int(limit))]
    return entries


def jurisdiction_to_dict(item: MunicipalJurisdiction) -> dict[str, Any]:
    payload = asdict(item)
    payload["key"] = item.key
    payload["display_name"] = item.display_name
    payload["html_parquet_path"] = item.html_parquet_path()
    payload["citation_parquet_path"] = item.citation_parquet_path()
    return payload


__all__ = [
    "HUB_DATASET_ID",
    "JUSTICEDAO_DATASET_ID",
    "LEGACY_CITY_ALIASES",
    "MunicipalJurisdiction",
    "get_municipal_jurisdiction",
    "harvest_hub_municipal_catalog",
    "jurisdiction_to_dict",
    "list_hub_metadata_paths",
    "list_municipal_jurisdictions",
    "load_municipal_jurisdictions",
    "municipal_catalog_summary",
]
