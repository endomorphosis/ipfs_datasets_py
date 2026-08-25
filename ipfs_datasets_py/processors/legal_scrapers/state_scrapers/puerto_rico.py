"""Official Puerto Rico OGP statute scraper.

Vaquill ingests PR from ``bvirtualogp.pr.gov`` consolidated PDFs (Apache-2.0
``ingest_pr_bulk.py``). This scraper is env-gated to a local dump and never
auto-downloads bulk PDFs. It is **not** registered in the exact-51
(50 states + DC) LCR-084 set.
"""

from typing import Dict, List, Optional

from .base_scraper import BaseStateScraper, NormalizedStatute
from .puerto_rico_ogp import OGP_BASE


class PuertoRicoScraper(BaseStateScraper):
    """Scraper for Puerto Rico codes from the official OGP Biblioteca Virtual."""

    OFFICIAL_DOMAIN = "bvirtualogp.pr.gov"
    OFFICIAL_ENTRY_PATH = "/ogp/Bvirtual/leyesreferencia/PDF"
    OFFICIAL_ENTRY_URL = OGP_BASE

    def get_base_url(self) -> str:
        return "https://bvirtualogp.pr.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        return [
            {
                "name": "Códigos de Puerto Rico (OGP)",
                "url": self.OFFICIAL_ENTRY_URL,
                "type": "Code",
            }
        ]

    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        from .puerto_rico_ogp import parse_configured_puerto_rico_ogp

        limit = self._effective_scrape_limit(max_statutes, default=160)
        local_rows = parse_configured_puerto_rico_ogp(
            code_name=code_name or "Códigos de Puerto Rico",
            max_statutes=limit,
        )
        if local_rows:
            return local_rows if limit is None else local_rows[: int(limit)]
        return []
