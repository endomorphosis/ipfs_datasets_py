"""US municipal code scrapers backed by the Hugging Face American Municipal Law corpus."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from .catalog import (
    HUB_DATASET_ID,
    LEGACY_CITY_ALIASES,
    get_municipal_jurisdiction,
    harvest_hub_municipal_catalog,
    jurisdiction_to_dict,
    list_municipal_jurisdictions,
    load_municipal_jurisdictions,
    municipal_catalog_summary,
)


@dataclass(frozen=True)
class MunicipalLaws:
    """US municipal ordinance and city-code scrapers."""

    region_id: str = "municipal"
    display_name: str = "United States Municipal Laws"
    country_code: str = "US"
    hub_dataset_id: str = HUB_DATASET_ID

    def jurisdictions(
        self,
        *,
        state: Optional[str] = None,
        on_hub: Optional[bool] = None,
        query: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        return [
            jurisdiction_to_dict(item)
            for item in list_municipal_jurisdictions(
                state=state,
                on_hub=on_hub,
                query=query,
                limit=limit,
            )
        ]

    def cities(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for item in load_municipal_jurisdictions():
            payload = {
                "name": item.place_name,
                "state": item.state_code,
                "gnis": item.gnis,
                "on_hub": item.on_hub,
            }
            result[item.gnis] = payload
        for alias, gnis in LEGACY_CITY_ALIASES.items():
            if gnis in result:
                result[alias] = result[gnis]
        return result

    def get(self, key: str) -> dict[str, Any]:
        return jurisdiction_to_dict(get_municipal_jurisdiction(key))

    def sources(self, **kwargs: Any) -> list[dict[str, Any]]:
        return [
            {
                "key": item["gnis"],
                "display_name": item["display_name"],
                "state": item["state_code"],
                "country_code": "US",
                "kind": "municipal",
                "on_hub": item["on_hub"],
                "region": self.region_id,
                "dataset_id": self.hub_dataset_id if item["on_hub"] else None,
            }
            for item in self.jurisdictions(**kwargs)
        ]

    def summary(self) -> dict[str, Any]:
        payload = municipal_catalog_summary()
        payload.update(
            {
                "region_id": self.region_id,
                "display_name": self.display_name,
                "country_code": self.country_code,
                "city_count": payload["jurisdiction_count"],
                "handlers": ("municipal_laws", "municipal_codes", "american_municipal_law"),
            }
        )
        return payload

    def scrape(
        self,
        cities: Sequence[str] | str | None = None,
        *,
        parameters: Optional[Mapping[str, Any]] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        from ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api import (
            scrape_municipal_codes_from_parameters,
        )
        import anyio

        params = dict(parameters or {})
        params.update(kwargs)
        if cities is not None:
            selected = [cities] if isinstance(cities, str) else list(cities)
            resolved = []
            for city in selected:
                try:
                    resolved.append(get_municipal_jurisdiction(city).gnis)
                except KeyError:
                    resolved.append(city)
            params["cities"] = resolved
        return anyio.run(scrape_municipal_codes_from_parameters, params)

    def search(
        self,
        city_name: Optional[str] = None,
        keywords: Optional[str] = None,
        limit: int = 100,
        *,
        state: Optional[str] = None,
        on_hub: Optional[bool] = None,
    ) -> dict[str, Any]:
        query = city_name or keywords
        matches = list_municipal_jurisdictions(
            state=state,
            on_hub=on_hub,
            query=query,
            limit=limit,
        )
        return {
            "status": "success",
            "count": len(matches),
            "jurisdictions": [jurisdiction_to_dict(item) for item in matches],
            "dataset_id": self.hub_dataset_id,
            "not_legal_advice": True,
        }

    def harvest_catalog(self, **kwargs: Any) -> dict[str, Any]:
        path = harvest_hub_municipal_catalog(**kwargs)
        load_municipal_jurisdictions.cache_clear()
        summary = self.summary()
        summary["catalog_path"] = str(path)
        return summary


Municipal = MunicipalLaws()

__all__ = ["Municipal", "MunicipalLaws"]
