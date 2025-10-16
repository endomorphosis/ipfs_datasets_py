"""All US state law scrapers.

This module contains scrapers for all 50 US states plus DC.
Each scraper goes to the official state legislative website.
"""

from typing import List, Dict, Optional
import re
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


# Alabama
class AlabamaScraper(BaseStateScraper):
    """Scraper for Alabama state laws."""
    
    def get_base_url(self) -> str:
        return "http://alisondb.legislature.state.al.us"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        return [{"name": "Alabama Code", "url": f"{self.get_base_url()}/alison/CodeOfAlabama/1975/", "type": "Code"}]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return await self._generic_scrape(code_name, code_url, "Ala. Code")


# Alaska
class AlaskaScraper(BaseStateScraper):
    """Scraper for Alaska state laws."""
    
    def get_base_url(self) -> str:
        return "http://www.legis.state.ak.us"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        return [{"name": "Alaska Statutes", "url": f"{self.get_base_url()}/basis/statutes.asp", "type": "Statutes"}]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return await self._generic_scrape(code_name, code_url, "Alaska Stat.")


# Arizona
class ArizonaScraper(BaseStateScraper):
    """Scraper for Arizona state laws."""
    
    def get_base_url(self) -> str:
        return "https://www.azleg.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        return [{"name": "Arizona Revised Statutes", "url": f"{self.get_base_url()}/ArizonaRevisedStatutes.asp", "type": "ARS"}]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return await self._generic_scrape(code_name, code_url, "Ariz. Rev. Stat.")


# Arkansas
class ArkansasScraper(BaseStateScraper):
    """Scraper for Arkansas state laws."""
    
    def get_base_url(self) -> str:
        return "https://www.arkleg.state.ar.us"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        return [{"name": "Arkansas Code", "url": f"{self.get_base_url()}/Bills/FTPDocument?path=/acts/", "type": "Code"}]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return await self._generic_scrape(code_name, code_url, "Ark. Code Ann.")


# Colorado
class ColoradoScraper(BaseStateScraper):
    """Scraper for Colorado state laws."""
    
    def get_base_url(self) -> str:
        return "https://leg.colorado.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        return [{"name": "Colorado Revised Statutes", "url": f"{self.get_base_url()}/agencies/", "type": "CRS"}]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return await self._generic_scrape(code_name, code_url, "Colo. Rev. Stat.")


# Connecticut
class ConnecticutScraper(BaseStateScraper):
    """Scraper for Connecticut state laws."""
    
    def get_base_url(self) -> str:
        return "https://www.cga.ct.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        return [{"name": "Connecticut General Statutes", "url": f"{self.get_base_url()}/current/pub/", "type": "CGS"}]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return await self._generic_scrape(code_name, code_url, "Conn. Gen. Stat.")


# Delaware
class DelawareScraper(BaseStateScraper):
    """Scraper for Delaware state laws."""
    
    def get_base_url(self) -> str:
        return "https://delcode.delaware.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        return [{"name": "Delaware Code", "url": f"{self.get_base_url()}/", "type": "Code"}]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return await self._generic_scrape(code_name, code_url, "Del. Code")


# Georgia
class GeorgiaScraper(BaseStateScraper):
    """Scraper for Georgia state laws."""
    
    def get_base_url(self) -> str:
        return "http://www.legis.ga.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        return [{"name": "Official Code of Georgia", "url": f"{self.get_base_url()}/legislation/", "type": "OCGA"}]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return await self._generic_scrape(code_name, code_url, "Ga. Code Ann.")


# Hawaii
class HawaiiScraper(BaseStateScraper):
    """Scraper for Hawaii state laws."""
    
    def get_base_url(self) -> str:
        return "https://www.capitol.hawaii.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        return [{"name": "Hawaii Revised Statutes", "url": f"{self.get_base_url()}/hrscurrent/", "type": "HRS"}]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return await self._generic_scrape(code_name, code_url, "Haw. Rev. Stat.")


# Idaho
class IdahoScraper(BaseStateScraper):
    """Scraper for Idaho state laws."""
    
    def get_base_url(self) -> str:
        return "https://legislature.idaho.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        return [{"name": "Idaho Statutes", "url": f"{self.get_base_url()}/statutesrules/idstat/", "type": "Idaho Code"}]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return await self._generic_scrape(code_name, code_url, "Idaho Code")


# Illinois
class IllinoisScraper(BaseStateScraper):
    """Scraper for Illinois state laws."""
    
    def get_base_url(self) -> str:
        return "https://www.ilga.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        return [{"name": "Illinois Compiled Statutes", "url": f"{self.get_base_url()}/legislation/ilcs/ilcs.asp", "type": "ILCS"}]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return await self._generic_scrape(code_name, code_url, "Ill. Comp. Stat.")


# Indiana
class IndianaScraper(BaseStateScraper):
    """Scraper for Indiana state laws."""
    
    def get_base_url(self) -> str:
        return "http://iga.in.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        return [{"name": "Indiana Code", "url": f"{self.get_base_url()}/legislative/laws/", "type": "IC"}]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return await self._generic_scrape(code_name, code_url, "Ind. Code")


# Iowa
class IowaScraper(BaseStateScraper):
    """Scraper for Iowa state laws."""
    
    def get_base_url(self) -> str:
        return "https://www.legis.iowa.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        return [{"name": "Iowa Code", "url": f"{self.get_base_url()}/law/", "type": "Iowa Code"}]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return await self._generic_scrape(code_name, code_url, "Iowa Code")


# Kansas
class KansasScraper(BaseStateScraper):
    """Scraper for Kansas state laws."""
    
    def get_base_url(self) -> str:
        return "http://www.kslegislature.org"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        return [{"name": "Kansas Statutes", "url": f"{self.get_base_url()}/li/", "type": "K.S.A."}]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return await self._generic_scrape(code_name, code_url, "Kan. Stat. Ann.")


# Kentucky
class KentuckyScraper(BaseStateScraper):
    """Scraper for Kentucky state laws."""
    
    def get_base_url(self) -> str:
        return "https://legislature.ky.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        return [{"name": "Kentucky Revised Statutes", "url": f"{self.get_base_url()}/Law/statutes/", "type": "KRS"}]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return await self._generic_scrape(code_name, code_url, "Ky. Rev. Stat.")


# Louisiana
class LouisianaScraper(BaseStateScraper):
    """Scraper for Louisiana state laws."""
    
    def get_base_url(self) -> str:
        return "http://www.legis.la.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        return [{"name": "Louisiana Revised Statutes", "url": f"{self.get_base_url()}/Legis/Laws_Toc.aspx", "type": "La. R.S."}]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return await self._generic_scrape(code_name, code_url, "La. Rev. Stat.")


# Maine
class MaineScraper(BaseStateScraper):
    """Scraper for Maine state laws."""
    
    def get_base_url(self) -> str:
        return "http://legislature.maine.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        return [{"name": "Maine Revised Statutes", "url": f"{self.get_base_url()}/legis/statutes/", "type": "Me. Rev. Stat."}]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return await self._generic_scrape(code_name, code_url, "Me. Rev. Stat.")


# Maryland
class MarylandScraper(BaseStateScraper):
    """Scraper for Maryland state laws."""
    
    def get_base_url(self) -> str:
        return "http://mgaleg.maryland.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        return [{"name": "Maryland Code", "url": f"{self.get_base_url()}/mgawebsite/Laws/StatuteCodes", "type": "Md. Code"}]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return await self._generic_scrape(code_name, code_url, "Md. Code Ann.")


# Massachusetts
class MassachusettsScraper(BaseStateScraper):
    """Scraper for Massachusetts state laws."""
    
    def get_base_url(self) -> str:
        return "https://malegislature.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        return [{"name": "Massachusetts General Laws", "url": f"{self.get_base_url()}/Laws/GeneralLaws", "type": "Mass. Gen. Laws"}]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return await self._generic_scrape(code_name, code_url, "Mass. Gen. Laws")


# Michigan
class MichiganScraper(BaseStateScraper):
    """Scraper for Michigan state laws."""
    
    def get_base_url(self) -> str:
        return "http://www.legislature.mi.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        return [{"name": "Michigan Compiled Laws", "url": f"{self.get_base_url()}/", "type": "MCL"}]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return await self._generic_scrape(code_name, code_url, "Mich. Comp. Laws")


# Minnesota
class MinnesotaScraper(BaseStateScraper):
    """Scraper for Minnesota state laws."""
    
    def get_base_url(self) -> str:
        return "https://www.revisor.mn.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        return [{"name": "Minnesota Statutes", "url": f"{self.get_base_url()}/statutes/", "type": "Minn. Stat."}]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return await self._generic_scrape(code_name, code_url, "Minn. Stat.")


# Mississippi
class MississippiScraper(BaseStateScraper):
    """Scraper for Mississippi state laws."""
    
    def get_base_url(self) -> str:
        return "http://www.legislature.ms.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        return [{"name": "Mississippi Code", "url": f"{self.get_base_url()}/", "type": "Miss. Code"}]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return await self._generic_scrape(code_name, code_url, "Miss. Code Ann.")


# Missouri
class MissouriScraper(BaseStateScraper):
    """Scraper for Missouri state laws."""
    
    def get_base_url(self) -> str:
        return "http://www.moga.mo.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        return [{"name": "Missouri Revised Statutes", "url": f"{self.get_base_url()}/mostatutes/", "type": "Mo. Rev. Stat."}]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return await self._generic_scrape(code_name, code_url, "Mo. Rev. Stat.")


# Montana
class MontanaScraper(BaseStateScraper):
    """Scraper for Montana state laws."""
    
    def get_base_url(self) -> str:
        return "https://leg.mt.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        return [{"name": "Montana Code Annotated", "url": f"{self.get_base_url()}/bills/mca/", "type": "MCA"}]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return await self._generic_scrape(code_name, code_url, "Mont. Code Ann.")


# Nebraska
class NebraskaScraper(BaseStateScraper):
    """Scraper for Nebraska state laws."""
    
    def get_base_url(self) -> str:
        return "https://nebraskalegislature.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        return [{"name": "Nebraska Revised Statutes", "url": f"{self.get_base_url()}/laws/", "type": "Neb. Rev. Stat."}]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return await self._generic_scrape(code_name, code_url, "Neb. Rev. Stat.")


# Nevada
class NevadaScraper(BaseStateScraper):
    """Scraper for Nevada state laws."""
    
    def get_base_url(self) -> str:
        return "https://www.leg.state.nv.us"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        return [{"name": "Nevada Revised Statutes", "url": f"{self.get_base_url()}/NRS/", "type": "Nev. Rev. Stat."}]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return await self._generic_scrape(code_name, code_url, "Nev. Rev. Stat.")


# New Hampshire
class NewHampshireScraper(BaseStateScraper):
    """Scraper for New Hampshire state laws."""
    
    def get_base_url(self) -> str:
        return "http://www.gencourt.state.nh.us"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        return [{"name": "New Hampshire Revised Statutes", "url": f"{self.get_base_url()}/rsa/html/indexes/", "type": "N.H. Rev. Stat."}]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return await self._generic_scrape(code_name, code_url, "N.H. Rev. Stat.")


# New Jersey
class NewJerseyScraper(BaseStateScraper):
    """Scraper for New Jersey state laws."""
    
    def get_base_url(self) -> str:
        return "https://www.njleg.state.nj.us"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        return [{"name": "New Jersey Statutes", "url": f"{self.get_base_url()}/", "type": "N.J. Stat."}]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return await self._generic_scrape(code_name, code_url, "N.J. Stat. Ann.")


# New Mexico
class NewMexicoScraper(BaseStateScraper):
    """Scraper for New Mexico state laws."""
    
    def get_base_url(self) -> str:
        return "https://www.nmlegis.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        return [{"name": "New Mexico Statutes", "url": f"{self.get_base_url()}/", "type": "N.M. Stat."}]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return await self._generic_scrape(code_name, code_url, "N.M. Stat. Ann.")


# North Carolina
class NorthCarolinaScraper(BaseStateScraper):
    """Scraper for North Carolina state laws."""
    
    def get_base_url(self) -> str:
        return "https://www.ncleg.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        return [{"name": "North Carolina General Statutes", "url": f"{self.get_base_url()}/Laws/GeneralStatutes", "type": "N.C. Gen. Stat."}]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return await self._generic_scrape(code_name, code_url, "N.C. Gen. Stat.")


# North Dakota
class NorthDakotaScraper(BaseStateScraper):
    """Scraper for North Dakota state laws."""
    
    def get_base_url(self) -> str:
        return "https://www.legis.nd.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        return [{"name": "North Dakota Century Code", "url": f"{self.get_base_url()}/cencode", "type": "N.D. Cent. Code"}]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return await self._generic_scrape(code_name, code_url, "N.D. Cent. Code")


# Ohio
class OhioScraper(BaseStateScraper):
    """Scraper for Ohio state laws."""
    
    def get_base_url(self) -> str:
        return "https://codes.ohio.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        return [{"name": "Ohio Revised Code", "url": f"{self.get_base_url()}/ohio-revised-code", "type": "Ohio Rev. Code"}]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return await self._generic_scrape(code_name, code_url, "Ohio Rev. Code Ann.")


# Oklahoma
class OklahomaScraper(BaseStateScraper):
    """Scraper for Oklahoma state laws."""
    
    def get_base_url(self) -> str:
        return "http://www.oklegislature.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        return [{"name": "Oklahoma Statutes", "url": f"{self.get_base_url()}/", "type": "Okla. Stat."}]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return await self._generic_scrape(code_name, code_url, "Okla. Stat.")


# Oregon
class OregonScraper(BaseStateScraper):
    """Scraper for Oregon state laws."""
    
    def get_base_url(self) -> str:
        return "https://www.oregonlegislature.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        return [{"name": "Oregon Revised Statutes", "url": f"{self.get_base_url()}/bills_laws", "type": "Or. Rev. Stat."}]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return await self._generic_scrape(code_name, code_url, "Or. Rev. Stat.")


# Pennsylvania
class PennsylvaniaScraper(BaseStateScraper):
    """Scraper for Pennsylvania state laws."""
    
    def get_base_url(self) -> str:
        return "https://www.legis.state.pa.us"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        return [{"name": "Pennsylvania Consolidated Statutes", "url": f"{self.get_base_url()}/cfdocs/legis/LI/Public/", "type": "Pa. Cons. Stat."}]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return await self._generic_scrape(code_name, code_url, "Pa. Cons. Stat.")


# Rhode Island
class RhodeIslandScraper(BaseStateScraper):
    """Scraper for Rhode Island state laws."""
    
    def get_base_url(self) -> str:
        return "http://webserver.rilin.state.ri.us"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        return [{"name": "Rhode Island General Laws", "url": f"{self.get_base_url()}/Statutes/", "type": "R.I. Gen. Laws"}]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return await self._generic_scrape(code_name, code_url, "R.I. Gen. Laws")


# South Carolina
class SouthCarolinaScraper(BaseStateScraper):
    """Scraper for South Carolina state laws."""
    
    def get_base_url(self) -> str:
        return "https://www.scstatehouse.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        return [{"name": "South Carolina Code of Laws", "url": f"{self.get_base_url()}/code/statmast.php", "type": "S.C. Code"}]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return await self._generic_scrape(code_name, code_url, "S.C. Code Ann.")


# South Dakota
class SouthDakotaScraper(BaseStateScraper):
    """Scraper for South Dakota state laws."""
    
    def get_base_url(self) -> str:
        return "https://sdlegislature.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        return [{"name": "South Dakota Codified Laws", "url": f"{self.get_base_url()}/Statutes/Codified_Laws", "type": "S.D. Codified Laws"}]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return await self._generic_scrape(code_name, code_url, "S.D. Codified Laws")


# Tennessee
class TennesseeScraper(BaseStateScraper):
    """Scraper for Tennessee state laws."""
    
    def get_base_url(self) -> str:
        return "https://www.tn.gov/tga"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        return [{"name": "Tennessee Code", "url": f"{self.get_base_url()}/", "type": "Tenn. Code"}]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return await self._generic_scrape(code_name, code_url, "Tenn. Code Ann.")


# Utah
class UtahScraper(BaseStateScraper):
    """Scraper for Utah state laws."""
    
    def get_base_url(self) -> str:
        return "https://le.utah.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        return [{"name": "Utah Code", "url": f"{self.get_base_url()}/xcode/code.html", "type": "Utah Code"}]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return await self._generic_scrape(code_name, code_url, "Utah Code Ann.")


# Vermont
class VermontScraper(BaseStateScraper):
    """Scraper for Vermont state laws."""
    
    def get_base_url(self) -> str:
        return "https://legislature.vermont.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        return [{"name": "Vermont Statutes", "url": f"{self.get_base_url()}/statutes/", "type": "Vt. Stat. Ann."}]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return await self._generic_scrape(code_name, code_url, "Vt. Stat. Ann.")


# Virginia
class VirginiaScraper(BaseStateScraper):
    """Scraper for Virginia state laws."""
    
    def get_base_url(self) -> str:
        return "https://law.lis.virginia.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        return [{"name": "Code of Virginia", "url": f"{self.get_base_url()}/vacode", "type": "Va. Code"}]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return await self._generic_scrape(code_name, code_url, "Va. Code Ann.")


# Washington
class WashingtonScraper(BaseStateScraper):
    """Scraper for Washington state laws."""
    
    def get_base_url(self) -> str:
        return "https://app.leg.wa.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        return [{"name": "Revised Code of Washington", "url": f"{self.get_base_url()}/rcw/", "type": "Wash. Rev. Code"}]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return await self._generic_scrape(code_name, code_url, "Wash. Rev. Code")


# West Virginia
class WestVirginiaScraper(BaseStateScraper):
    """Scraper for West Virginia state laws."""
    
    def get_base_url(self) -> str:
        return "http://www.wvlegislature.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        return [{"name": "West Virginia Code", "url": f"{self.get_base_url()}/wvcode/code.cfm", "type": "W. Va. Code"}]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return await self._generic_scrape(code_name, code_url, "W. Va. Code")


# Wisconsin
class WisconsinScraper(BaseStateScraper):
    """Scraper for Wisconsin state laws."""
    
    def get_base_url(self) -> str:
        return "https://docs.legis.wisconsin.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        return [{"name": "Wisconsin Statutes", "url": f"{self.get_base_url()}/statutes/", "type": "Wis. Stat."}]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return await self._generic_scrape(code_name, code_url, "Wis. Stat.")


# Wyoming
class WyomingScraper(BaseStateScraper):
    """Scraper for Wyoming state laws."""
    
    def get_base_url(self) -> str:
        return "https://www.wyoleg.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        return [{"name": "Wyoming Statutes", "url": f"{self.get_base_url()}/", "type": "Wyo. Stat."}]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return await self._generic_scrape(code_name, code_url, "Wyo. Stat.")


# District of Columbia
class DistrictOfColumbiaScraper(BaseStateScraper):
    """Scraper for District of Columbia laws."""
    
    def get_base_url(self) -> str:
        return "https://code.dccouncil.us"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        return [{"name": "District of Columbia Official Code", "url": f"{self.get_base_url()}/", "type": "D.C. Code"}]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return await self._generic_scrape(code_name, code_url, "D.C. Code")


# Helper method for all scrapers
async def _generic_scrape_helper(self, code_name: str, code_url: str, citation_prefix: str) -> List[NormalizedStatute]:
    """Generic scraping implementation used by all state scrapers."""
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError as e:
        self.logger.error(f"Required library not available: {e}")
        return []
    
    statutes = []
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = requests.get(code_url, headers=headers, timeout=30)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Find section links
        section_links = soup.find_all('a', href=True)[:100]  # Limit for performance
        
        for link in section_links:
            section_text = link.get_text(strip=True)
            section_url = link.get('href', '')
            
            if not section_text or len(section_text) < 5:
                continue
            
            if not section_url.startswith('http'):
                section_url = f"{self.get_base_url()}{section_url}"
            
            section_number = self._extract_section_number(section_text)
            
            statute = NormalizedStatute(
                state_code=self.state_code,
                state_name=self.state_name,
                statute_id=f"{code_name} § {section_number}" if section_number else section_text,
                code_name=code_name,
                section_number=section_number,
                section_name=section_text,
                source_url=section_url,
                legal_area=self._identify_legal_area(code_name),
                official_cite=f"{citation_prefix} § {section_number}" if section_number else None,
                metadata=StatuteMetadata()
            )
            
            statutes.append(statute)
        
        self.logger.info(f"Scraped {len(statutes)} sections from {code_name}")
        
    except Exception as e:
        self.logger.error(f"Failed to scrape {code_name}: {e}")
    
    return statutes


# Add the helper method to BaseStateScraper
BaseStateScraper._generic_scrape = _generic_scrape_helper


# Register all scrapers
StateScraperRegistry.register("AL", AlabamaScraper)
StateScraperRegistry.register("AK", AlaskaScraper)
StateScraperRegistry.register("AZ", ArizonaScraper)
StateScraperRegistry.register("AR", ArkansasScraper)
StateScraperRegistry.register("CO", ColoradoScraper)
StateScraperRegistry.register("CT", ConnecticutScraper)
StateScraperRegistry.register("DE", DelawareScraper)
# FL is registered in florida.py
StateScraperRegistry.register("GA", GeorgiaScraper)
StateScraperRegistry.register("HI", HawaiiScraper)
StateScraperRegistry.register("ID", IdahoScraper)
StateScraperRegistry.register("IL", IllinoisScraper)
StateScraperRegistry.register("IN", IndianaScraper)
StateScraperRegistry.register("IA", IowaScraper)
StateScraperRegistry.register("KS", KansasScraper)
StateScraperRegistry.register("KY", KentuckyScraper)
StateScraperRegistry.register("LA", LouisianaScraper)
StateScraperRegistry.register("ME", MaineScraper)
StateScraperRegistry.register("MD", MarylandScraper)
StateScraperRegistry.register("MA", MassachusettsScraper)
StateScraperRegistry.register("MI", MichiganScraper)
StateScraperRegistry.register("MN", MinnesotaScraper)
StateScraperRegistry.register("MS", MississippiScraper)
StateScraperRegistry.register("MO", MissouriScraper)
StateScraperRegistry.register("MT", MontanaScraper)
StateScraperRegistry.register("NE", NebraskaScraper)
StateScraperRegistry.register("NV", NevadaScraper)
StateScraperRegistry.register("NH", NewHampshireScraper)
StateScraperRegistry.register("NJ", NewJerseyScraper)
StateScraperRegistry.register("NM", NewMexicoScraper)
StateScraperRegistry.register("NC", NorthCarolinaScraper)
StateScraperRegistry.register("ND", NorthDakotaScraper)
StateScraperRegistry.register("OH", OhioScraper)
StateScraperRegistry.register("OK", OklahomaScraper)
StateScraperRegistry.register("OR", OregonScraper)
StateScraperRegistry.register("PA", PennsylvaniaScraper)
StateScraperRegistry.register("RI", RhodeIslandScraper)
StateScraperRegistry.register("SC", SouthCarolinaScraper)
StateScraperRegistry.register("SD", SouthDakotaScraper)
StateScraperRegistry.register("TN", TennesseeScraper)
StateScraperRegistry.register("UT", UtahScraper)
StateScraperRegistry.register("VT", VermontScraper)
StateScraperRegistry.register("VA", VirginiaScraper)
StateScraperRegistry.register("WA", WashingtonScraper)
StateScraperRegistry.register("WV", WestVirginiaScraper)
StateScraperRegistry.register("WI", WisconsinScraper)
StateScraperRegistry.register("WY", WyomingScraper)
StateScraperRegistry.register("DC", DistrictOfColumbiaScraper)
