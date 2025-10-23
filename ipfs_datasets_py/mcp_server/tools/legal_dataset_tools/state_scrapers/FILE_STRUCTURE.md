# State Scraper Files - Complete Directory Structure

This document shows the complete file structure of the state_scrapers directory, with **51 individual scraper files** - one for each US jurisdiction.

## Directory Structure

```
state_scrapers/
├── __init__.py                      # Imports all 51 state scrapers
├── base_scraper.py                  # BaseStateScraper abstract class
├── registry.py                      # StateScraperRegistry for managing scrapers
├── generic.py                       # GenericStateScraper fallback
│
├── alabama.py                       # Alabama Code scraper
├── alaska.py                        # Alaska Statutes scraper
├── arizona.py                       # Arizona Revised Statutes scraper
├── arkansas.py                      # Arkansas Code scraper
├── california.py                    # California codes scraper (29 codes)
├── colorado.py                      # Colorado Revised Statutes scraper
├── connecticut.py                   # Connecticut General Statutes scraper
├── delaware.py                      # Delaware Code scraper
├── district_of_columbia.py          # D.C. Official Code scraper
├── florida.py                       # Florida Statutes scraper
├── georgia.py                       # Official Code of Georgia scraper
├── hawaii.py                        # Hawaii Revised Statutes scraper
├── idaho.py                         # Idaho Statutes scraper
├── illinois.py                      # Illinois Compiled Statutes scraper
├── indiana.py                       # Indiana Code scraper
├── iowa.py                          # Iowa Code scraper
├── kansas.py                        # Kansas Statutes scraper
├── kentucky.py                      # Kentucky Revised Statutes scraper
├── louisiana.py                     # Louisiana Revised Statutes scraper
├── maine.py                         # Maine Revised Statutes scraper
├── maryland.py                      # Maryland Code scraper
├── massachusetts.py                 # Massachusetts General Laws scraper
├── michigan.py                      # Michigan Compiled Laws scraper
├── minnesota.py                     # Minnesota Statutes scraper
├── mississippi.py                   # Mississippi Code scraper
├── missouri.py                      # Missouri Revised Statutes scraper
├── montana.py                       # Montana Code Annotated scraper
├── nebraska.py                      # Nebraska Revised Statutes scraper
├── nevada.py                        # Nevada Revised Statutes scraper
├── new_hampshire.py                 # New Hampshire Revised Statutes scraper
├── new_jersey.py                    # New Jersey Statutes scraper
├── new_mexico.py                    # New Mexico Statutes scraper
├── new_york.py                      # New York Consolidated Laws scraper (23+ laws)
├── north_carolina.py                # North Carolina General Statutes scraper
├── north_dakota.py                  # North Dakota Century Code scraper
├── ohio.py                          # Ohio Revised Code scraper
├── oklahoma.py                      # Oklahoma Statutes scraper
├── oregon.py                        # Oregon Revised Statutes scraper
├── pennsylvania.py                  # Pennsylvania Consolidated Statutes scraper
├── rhode_island.py                  # Rhode Island General Laws scraper
├── south_carolina.py                # South Carolina Code of Laws scraper
├── south_dakota.py                  # South Dakota Codified Laws scraper
├── tennessee.py                     # Tennessee Code scraper
├── texas.py                         # Texas codes scraper (24+ codes)
├── utah.py                          # Utah Code scraper
├── vermont.py                       # Vermont Statutes scraper
├── virginia.py                      # Code of Virginia scraper
├── washington.py                    # Revised Code of Washington scraper
├── west_virginia.py                 # West Virginia Code scraper
├── wisconsin.py                     # Wisconsin Statutes scraper
└── wyoming.py                       # Wyoming Statutes scraper

Total: 56 files
- 51 individual state scraper files
- 4 infrastructure files (__init__.py, base_scraper.py, registry.py, generic.py)
- 1 README.md
```

## File Count by Type

```
Infrastructure files:    4
State scraper files:    51
Documentation:           1
------------------------
Total:                  56
```

## Official State Legislative Websites

Each scraper file targets the official state legislative website:

| State | Code | Website |
|-------|------|---------|
| Alabama | AL | alisondb.legislature.state.al.us |
| Alaska | AK | legis.state.ak.us |
| Arizona | AZ | azleg.gov |
| Arkansas | AR | arkleg.state.ar.us |
| California | CA | leginfo.legislature.ca.gov |
| Colorado | CO | leg.colorado.gov |
| Connecticut | CT | cga.ct.gov |
| Delaware | DE | delcode.delaware.gov |
| District of Columbia | DC | code.dccouncil.us |
| Florida | FL | leg.state.fl.us |
| Georgia | GA | legis.ga.gov |
| Hawaii | HI | capitol.hawaii.gov |
| Idaho | ID | legislature.idaho.gov |
| Illinois | IL | ilga.gov |
| Indiana | IN | iga.in.gov |
| Iowa | IA | legis.iowa.gov |
| Kansas | KS | kslegislature.org |
| Kentucky | KY | legislature.ky.gov |
| Louisiana | LA | legis.la.gov |
| Maine | ME | legislature.maine.gov |
| Maryland | MD | mgaleg.maryland.gov |
| Massachusetts | MA | malegislature.gov |
| Michigan | MI | legislature.mi.gov |
| Minnesota | MN | revisor.mn.gov |
| Mississippi | MS | legislature.ms.gov |
| Missouri | MO | moga.mo.gov |
| Montana | MT | leg.mt.gov |
| Nebraska | NE | nebraskalegislature.gov |
| Nevada | NV | leg.state.nv.us |
| New Hampshire | NH | gencourt.state.nh.us |
| New Jersey | NJ | njleg.state.nj.us |
| New Mexico | NM | nmlegis.gov |
| New York | NY | nysenate.gov |
| North Carolina | NC | ncleg.gov |
| North Dakota | ND | legis.nd.gov |
| Ohio | OH | codes.ohio.gov |
| Oklahoma | OK | oklegislature.gov |
| Oregon | OR | oregonlegislature.gov |
| Pennsylvania | PA | legis.state.pa.us |
| Rhode Island | RI | webserver.rilin.state.ri.us |
| South Carolina | SC | scstatehouse.gov |
| South Dakota | SD | sdlegislature.gov |
| Tennessee | TN | tn.gov/tga |
| Texas | TX | statutes.capitol.texas.gov |
| Utah | UT | le.utah.gov |
| Vermont | VT | legislature.vermont.gov |
| Virginia | VA | law.lis.virginia.gov |
| Washington | WA | app.leg.wa.gov |
| West Virginia | WV | wvlegislature.gov |
| Wisconsin | WI | docs.legis.wisconsin.gov |
| Wyoming | WY | wyoleg.gov |

## Example State Scraper File

Each file follows this structure (example: `illinois.py`):

```python
"""Scraper for Illinois state laws.

This module contains the scraper for Illinois statutes from the official state legislative website.
"""

from typing import List, Dict
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class IllinoisScraper(BaseStateScraper):
    """Scraper for Illinois state laws from https://www.ilga.gov"""
    
    def get_base_url(self) -> str:
        """Return the base URL for Illinois's legislative website."""
        return "https://www.ilga.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Illinois."""
        return [{
            "name": "Illinois Compiled Statutes",
            "url": f"{self.get_base_url()}/",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from Illinois's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        return await self._generic_scrape(code_name, code_url, "Ill. Comp. Stat.")


# Register this scraper with the registry
StateScraperRegistry.register("IL", IllinoisScraper)
```

## Validation

Run the comprehensive validation script:

```bash
cd ipfs_datasets_py/mcp_server/tools/legal_dataset_tools
python3 validate_all_state_scrapers.py
```

This validates:
1. ✅ All 51 state scraper files exist
2. ✅ All 51 scrapers are registered
3. ✅ All scrapers implement required methods
4. ✅ All scrapers output normalized schema

## Benefits of Individual Files

1. **Clarity**: Crystal clear that each state has a dedicated scraper
2. **Maintainability**: Changes to one state don't affect others
3. **Extensibility**: Easy to enhance individual state scrapers
4. **Transparency**: Can see exactly what's implemented for each state
5. **Testability**: Can test each state scraper independently
6. **Documentation**: Each file is self-documenting

## Next Steps

To enhance a specific state's scraper:
1. Open the state's file (e.g., `california.py`)
2. Customize the scraping logic in `scrape_code()` method
3. Add state-specific parsing for HTML structure
4. Update `get_code_list()` with detailed code information
5. Add more metadata extraction as needed

All scrapers inherit from `BaseStateScraper` and use the `_generic_scrape()` helper method, making it easy to share common logic while allowing state-specific customization.
