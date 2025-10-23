"""Individual state law scrapers.

This package contains dedicated scrapers for each US state's official
legislative website, with state-specific parsing logic.

All 51 US jurisdictions (50 states + DC) have individual scraper files.
"""

from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry, get_scraper_for_state
from .generic import GenericStateScraper

# Import all 51 state-specific scrapers (alphabetically)
from . import alabama
from . import alaska
from . import arizona
from . import arkansas
from . import california
from . import colorado
from . import connecticut
from . import delaware
from . import district_of_columbia
from . import florida
from . import georgia
from . import hawaii
from . import idaho
from . import illinois
from . import indiana
from . import iowa
from . import kansas
from . import kentucky
from . import louisiana
from . import maine
from . import maryland
from . import massachusetts
from . import michigan
from . import minnesota
from . import mississippi
from . import missouri
from . import montana
from . import nebraska
from . import nevada
from . import new_hampshire
from . import new_jersey
from . import new_mexico
from . import new_york
from . import north_carolina
from . import north_dakota
from . import ohio
from . import oklahoma
from . import oregon
from . import pennsylvania
from . import rhode_island
from . import south_carolina
from . import south_dakota
from . import tennessee
from . import texas
from . import utah
from . import vermont
from . import virginia
from . import washington
from . import west_virginia
from . import wisconsin
from . import wyoming

# Export scraper classes for direct import
from .alabama import AlabamaScraper
from .alaska import AlaskaScraper
from .arizona import ArizonaScraper
from .arkansas import ArkansasScraper
from .california import CaliforniaScraper
from .colorado import ColoradoScraper
from .connecticut import ConnecticutScraper
from .delaware import DelawareScraper
from .district_of_columbia import DistrictOfColumbiaScraper
from .florida import FloridaScraper
from .georgia import GeorgiaScraper
from .hawaii import HawaiiScraper
from .idaho import IdahoScraper
from .illinois import IllinoisScraper
from .indiana import IndianaScraper
from .iowa import IowaScraper
from .kansas import KansasScraper
from .kentucky import KentuckyScraper
from .louisiana import LouisianaScraper
from .maine import MaineScraper
from .maryland import MarylandScraper
from .massachusetts import MassachusettsScraper
from .michigan import MichiganScraper
from .minnesota import MinnesotaScraper
from .mississippi import MississippiScraper
from .missouri import MissouriScraper
from .montana import MontanaScraper
from .nebraska import NebraskaScraper
from .nevada import NevadaScraper
from .new_hampshire import NewHampshireScraper
from .new_jersey import NewJerseyScraper
from .new_mexico import NewMexicoScraper
from .new_york import NewYorkScraper
from .north_carolina import NorthCarolinaScraper
from .north_dakota import NorthDakotaScraper
from .ohio import OhioScraper
from .oklahoma import OklahomaScraper
from .oregon import OregonScraper
from .pennsylvania import PennsylvaniaScraper
from .rhode_island import RhodeIslandScraper
from .south_carolina import SouthCarolinaScraper
from .south_dakota import SouthDakotaScraper
from .tennessee import TennesseeScraper
from .texas import TexasScraper
from .utah import UtahScraper
from .vermont import VermontScraper
from .virginia import VirginiaScraper
from .washington import WashingtonScraper
from .west_virginia import WestVirginiaScraper
from .wisconsin import WisconsinScraper
from .wyoming import WyomingScraper

__all__ = [
    'BaseStateScraper',
    'NormalizedStatute',
    'StatuteMetadata',
    'StateScraperRegistry',
    'get_scraper_for_state',
    'GenericStateScraper',
    # State scrapers
    'AlabamaScraper',
    'AlaskaScraper',
    'ArizonaScraper',
    'ArkansasScraper',
    'CaliforniaScraper',
    'ColoradoScraper',
    'ConnecticutScraper',
    'DelawareScraper',
    'DistrictOfColumbiaScraper',
    'FloridaScraper',
    'GeorgiaScraper',
    'HawaiiScraper',
    'IdahoScraper',
    'IllinoisScraper',
    'IndianaScraper',
    'IowaScraper',
    'KansasScraper',
    'KentuckyScraper',
    'LouisianaScraper',
    'MaineScraper',
    'MarylandScraper',
    'MassachusettsScraper',
    'MichiganScraper',
    'MinnesotaScraper',
    'MississippiScraper',
    'MissouriScraper',
    'MontanaScraper',
    'NebraskaScraper',
    'NevadaScraper',
    'NewHampshireScraper',
    'NewJerseyScraper',
    'NewMexicoScraper',
    'NewYorkScraper',
    'NorthCarolinaScraper',
    'NorthDakotaScraper',
    'OhioScraper',
    'OklahomaScraper',
    'OregonScraper',
    'PennsylvaniaScraper',
    'RhodeIslandScraper',
    'SouthCarolinaScraper',
    'SouthDakotaScraper',
    'TennesseeScraper',
    'TexasScraper',
    'UtahScraper',
    'VermontScraper',
    'VirginiaScraper',
    'WashingtonScraper',
    'WestVirginiaScraper',
    'WisconsinScraper',
    'WyomingScraper',
]
