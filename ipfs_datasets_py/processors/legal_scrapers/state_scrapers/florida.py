"""Florida state law scraper.

Scrapes laws from the Florida Legislature website
(http://www.leg.state.fl.us/).
"""

from typing import List, Dict
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class FloridaScraper(BaseStateScraper):
    """Scraper for Florida state laws."""
    
    def get_base_url(self) -> str:
        """Get base URL for Florida statutes."""
        return "http://www.leg.state.fl.us"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Get list of Florida statutes."""
        base_url = self.get_base_url()
        
        codes = [
            {"name": "Florida Statutes", "url": f"{base_url}/Statutes/", "type": "FS"},
        ]
        
        return codes
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape Florida statutes from statutes index + representative title pages."""
        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/Statutes/",
            f"{self.get_base_url()}/statutes/index.cfm?App_mode=Display_Statute&URL=0000-0099/0001/0001.html",
            f"{self.get_base_url()}/statutes/index.cfm?App_mode=Display_Statute&URL=0100-0199/0119/0119.html",
            f"{self.get_base_url()}/statutes/index.cfm?App_mode=Display_Statute&URL=0700-0799/0776/0776.html",
        ]

        seen = set()
        best: List[NormalizedStatute] = []
        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)
            statutes = await self._generic_scrape(code_name, candidate, "Fla. Stat.", max_sections=260)
            if len(statutes) > len(best):
                best = statutes
            if len(statutes) >= 30:
                return statutes

        return best


# Register the scraper
StateScraperRegistry.register("FL", FloridaScraper)
