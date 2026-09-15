"""US state statutory and administrative-rule scrapers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence


@dataclass(frozen=True)
class StateLaws:
    """US state-level legal scrapers (statutes, admin rules, court rules)."""

    region_id: str = "state"
    display_name: str = "United States State Laws"
    country_code: str = "US"

    def jurisdictions(self) -> dict[str, Any]:
        from ipfs_datasets_py.processors.legal_scrapers.state_laws_scraper import list_state_jurisdictions
        import anyio

        return anyio.run(list_state_jurisdictions)

    def sources(self) -> list[dict[str, Any]]:
        payload = self.jurisdictions()
        states = payload.get("states") or {}
        return [
            {
                "key": code,
                "display_name": name,
                "country_code": "US",
                "kind": "state",
                "region": self.region_id,
            }
            for code, name in sorted(states.items())
        ]

    def summary(self) -> dict[str, Any]:
        payload = self.jurisdictions()
        return {
            "region_id": self.region_id,
            "display_name": self.display_name,
            "country_code": self.country_code,
            "jurisdiction_count": payload.get("count") or len(payload.get("states") or {}),
            "handlers": ("state_laws", "state_admin_rules", "state_court_rules"),
            "not_legal_advice": True,
        }

    def scrape(
        self,
        states: Sequence[str] | str | None = None,
        *,
        parameters: Optional[Mapping[str, Any]] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        from ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api import (
            scrape_state_laws_from_parameters,
        )
        import anyio

        params = dict(parameters or {})
        params.update(kwargs)
        if states is not None:
            params["states"] = [states] if isinstance(states, str) else list(states)
        return anyio.run(scrape_state_laws_from_parameters, params)

    def scrape_admin_rules(
        self,
        states: Sequence[str] | str | None = None,
        *,
        parameters: Optional[Mapping[str, Any]] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        from ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api import (
            scrape_state_admin_rules_from_parameters,
        )
        import anyio

        params = dict(parameters or {})
        params.update(kwargs)
        if states is not None:
            params["states"] = [states] if isinstance(states, str) else list(states)
        return anyio.run(scrape_state_admin_rules_from_parameters, params)


State = StateLaws()

__all__ = ["State", "StateLaws"]
