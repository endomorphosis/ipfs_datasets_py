"""State civil/criminal procedure-rules scraper orchestration.

This module reuses the state-laws scraping pipeline, then keeps only
records that match civil/criminal procedure rule patterns.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import time
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import requests

try:
    from .canonical_legal_corpora import get_canonical_legal_corpus
except ImportError:  # pragma: no cover - file-based test imports
    import importlib.util
    import sys

    _CANONICAL_MODULE_PATH = Path(__file__).with_name("canonical_legal_corpora.py")
    _CANONICAL_SPEC = importlib.util.spec_from_file_location(
        "canonical_legal_corpora",
        _CANONICAL_MODULE_PATH,
    )
    if _CANONICAL_SPEC is None or _CANONICAL_SPEC.loader is None:
        raise
    _CANONICAL_MODULE = importlib.util.module_from_spec(_CANONICAL_SPEC)
    sys.modules.setdefault("canonical_legal_corpora", _CANONICAL_MODULE)
    _CANONICAL_SPEC.loader.exec_module(_CANONICAL_MODULE)
    get_canonical_legal_corpus = _CANONICAL_MODULE.get_canonical_legal_corpus
from .state_laws_scraper import US_STATES, list_state_jurisdictions, scrape_state_laws
from .state_scrapers.base_scraper import BaseStateScraper, NormalizedStatute

logger = logging.getLogger(__name__)
_DIRECT_FETCH_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

_RI_COURT_RULES_HUB_URL = "https://www.courts.ri.gov/Legal-Resources/Pages/court-rules.aspx"
_RI_COURT_RULES_PAGE_RE = re.compile(
    r"/Legal-Resources/Pages/(?:Supreme|Superior|Family|District|Workers'-Compensation|Rhode-Island-Traffic-Tribunal)-Court-Rules\.aspx$",
    re.IGNORECASE,
)
_RI_COURT_RULES_DOC_RE = re.compile(r"\.pdf(?:$|[?#])", re.IGNORECASE)
_RI_COURT_RULES_ALLOWED_DOC_PATH_RE = re.compile(r"^/(?:Courts/|Legal-Resources/Documents/)", re.IGNORECASE)
_RI_COURT_RULE_SIGNAL_RE = re.compile(
    r"\b(rule|rules|procedure|practice|evidence|tribunal|arbitration|domestic|juvenile|disciplinary)\b",
    re.IGNORECASE,
)
_RI_COURT_RULE_EXCLUDED_TEXT_RE = re.compile(
    r"\b(instructions?|forms?|notice\s+of\s+suit|complaint|answer|attorney)\b",
    re.IGNORECASE,
)
_MI_COURT_RULES_CHAPTERS: List[Dict[str, str]] = [
    {
        "name": "Michigan Court Rules Chapter 2. Civil Procedure",
        "url": "https://www.courts.michigan.gov/siteassets/rules-instructions-administrative-orders/"
        "michigan-court-rules/court-rules-book-ch-2-responsive-html5.zip/"
        "Court_Rules_Book_Ch_2/Court_Rules_Chapter_2/Court_Rules_Chapter_2.htm",
        "procedure_family": "civil_procedure",
        "legal_area": "civil_procedure",
    },
    {
        "name": "Michigan Court Rules Chapter 6. Criminal Procedure",
        "url": "https://www.courts.michigan.gov/siteassets/rules-instructions-administrative-orders/"
        "michigan-court-rules/court-rules-book-ch-6-responsive-html5.zip/"
        "Court_Rules_Book_Ch_6/Court_Rules_Chapter_6/Court_Rules_Chapter_6.htm",
        "procedure_family": "criminal_procedure",
        "legal_area": "criminal_procedure",
    },
]
_MI_RULE_HEADING_RE = re.compile(r"^Rule\s+(\d+\.\d{3}[A-Za-z]?)\s+(.+)$")
_MI_UPDATED_RE = re.compile(
    r"Chapter\s+Updated\s+with\s+MSC\s+Order\(s\)\s+Effective\s+on\s+(.+)$",
    re.IGNORECASE,
)
_CA_RULE_TITLES: List[Dict[str, str]] = [
    {
        "title_name": "Title Three. Civil Rules",
        "url": "https://courts.ca.gov/cms/rules/index/three",
        "procedure_family": "civil_procedure",
        "legal_area": "civil_procedure",
    },
    {
        "title_name": "Title Four. Criminal Rules",
        "url": "https://courts.ca.gov/cms/rules/index/four",
        "procedure_family": "criminal_procedure",
        "legal_area": "criminal_procedure",
    },
]
_CA_RULE_LINK_RE = re.compile(r"^/cms/rules/index/(three|four)/rule[0-9_]+(?:#.*)?$", re.IGNORECASE)
_CA_RULE_HEADING_RE = re.compile(r"^Rule\s+(\d+\.\d+)\.\s+(.+)$")
_CA_CURRENT_AS_OF_RE = re.compile(r"^Current\s+as\s+of\s+(.+)$", re.IGNORECASE)
_OH_RULE_DOCUMENTS: List[Dict[str, str]] = [
    {
        "title_name": "Ohio Rules of Civil Procedure",
        "url": "https://www.supremecourt.ohio.gov/docs/LegalResources/Rules/civil/CivilProcedure.pdf",
        "procedure_family": "civil_procedure",
        "legal_area": "civil_procedure",
        "effective_date": "July 1, 2025",
    },
    {
        "title_name": "Ohio Rules of Criminal Procedure",
        "url": "https://www.supremecourt.ohio.gov/docs/LegalResources/Rules/criminal/CriminalProcedure.pdf",
        "procedure_family": "criminal_procedure",
        "legal_area": "criminal_procedure",
        "effective_date": "July 1, 2025",
    },
]
_OH_RULE_BLOCK_RE = re.compile(
    r"RULE\s+(\d+(?:\.\d+)?)\.\s+(.+?)(?=(?:\sRULE\s+\d+(?:\.\d+)?\.)|\Z)",
    re.DOTALL,
)
_AZ_RULE_DOCUMENTS: List[Dict[str, str]] = [
    {
        "title_name": "Arizona Rules of Civil Procedure",
        "url": "https://www.azcourts.gov/DesktopModules/ActiveForums/viewer.aspx?attachmentid=3200&moduleid=23621&portalid=0",
        "procedure_family": "civil_procedure",
        "legal_area": "civil_procedure",
        "effective_date": "2017 amendments restyled text reflected in official PDF",
        "start_marker": "Rule 1. Scope and Purpose",
    },
    {
        "title_name": "Arizona Rules of Criminal Procedure",
        "url": "https://rulesforum.azcourts.gov/DesktopModules/ActiveForums/viewer.aspx?attachmentid=4820&moduleid=9811&portalid=4",
        "procedure_family": "criminal_procedure",
        "legal_area": "criminal_procedure",
        "effective_date": "Attachment A official compiled criminal rules PDF",
        "start_marker": "Rule 1.1. Scope",
    },
]
_AZ_RULE_BLOCK_RE = re.compile(
    r"Rule\s+(\d+(?:\.\d+)?)\.\s+(.+?)(?=(?:\sRule\s+\d+(?:\.\d+)?\.)|\Z)",
    re.DOTALL,
)
_WA_RULE_LIST_PAGES: List[Dict[str, str]] = [
    {
        "title_name": "Washington Superior Court Civil Rules",
        "url": "https://www.courts.wa.gov/court_rules/?fa=court_rules.list&group=sup&set=CR",
        "procedure_family": "civil_procedure",
        "legal_area": "civil_procedure",
        "official_cite_prefix": "CR",
    },
    {
        "title_name": "Washington Superior Court Criminal Rules",
        "url": "https://www.courts.wa.gov/court_rules/?fa=court_rules.list&group=sup&set=CrR",
        "procedure_family": "criminal_procedure",
        "legal_area": "criminal_procedure",
        "official_cite_prefix": "CrR",
    },
]
_WA_RULE_SECTION_NUMBER_RE = re.compile(r"^\d+(?:\.\d+)?(?:[A-Za-z]+)?(?:\s+[A-Za-z]+)?$")
_WA_EFFECTIVE_DATE_RE = re.compile(r"\b(?:Adopted|Amended)\s+effective\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})", re.IGNORECASE)
_NJ_RULE_PARTS: List[Dict[str, str]] = [
    {
        "section": "Part 3",
        "title_name": "New Jersey Court Rules Part III. Criminal Practice",
        "procedure_family": "criminal_procedure",
        "legal_area": "criminal_procedure",
    },
    {
        "section": "Part 4",
        "title_name": "New Jersey Court Rules Part IV. Civil Practice",
        "procedure_family": "civil_procedure",
        "legal_area": "civil_procedure",
    },
]
_NJ_EFFECTIVE_DATE_RE = re.compile(r"effective\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})", re.IGNORECASE)
_NJ_RULE_TITLE_RE = re.compile(r"^([0-9]+:[0-9A-Za-z.]+(?:-[0-9A-Za-z.]+)*)-(.+)$")
_NH_RULE_SOURCES: List[Dict[str, Any]] = [
    {
        "title_name": "New Hampshire Rules of Criminal Procedure",
        "url": "https://www.courts.nh.gov/new-hampshire-rules-criminal-procedure",
        "procedure_family": "criminal_procedure",
        "legal_area": "criminal_procedure",
        "official_cite_prefix": "N.H. R. Crim. P.",
        "rule_number_max": 99,
    },
    {
        "title_name": "Rules of The Superior Court of the State of New Hampshire",
        "url": "https://www.courts.nh.gov/rules-superior-court-state-new-hampshire",
        "procedure_family": "civil_procedure",
        "legal_area": "civil_procedure",
        "official_cite_prefix": "N.H. Super. Ct. R.",
        "rule_number_max": 99,
    },
]
_NH_RULE_HEADING_RE = re.compile(r"^Rule\s+([0-9]+[A-Za-z]?(?:\.[0-9A-Za-z]+)?)\.?\s+(.+)$")
_NH_EFFECTIVE_DATE_RE = re.compile(
    r"(?:take effect on|effective)\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})",
    re.IGNORECASE,
)
_NV_RULE_SOURCES: List[Dict[str, str]] = [
    {
        "title_name": "Nevada Rules of Civil Procedure",
        "url": "https://www.leg.state.nv.us/Division/Legal/LawLibrary/CourtRules/NRCP.html",
        "procedure_family": "civil_procedure",
        "legal_area": "civil_procedure",
        "official_cite_prefix": "NRCP",
    },
    {
        "title_name": "Nevada Rules of Criminal Practice",
        "url": "https://www.leg.state.nv.us/Division/Legal/LawLibrary/CourtRules/NRCrP.html",
        "procedure_family": "criminal_procedure",
        "legal_area": "criminal_procedure",
        "official_cite_prefix": "NRCrP",
    },
]
_NV_RULE_HEADING_RE = re.compile(r"^Rule\s+([0-9]+(?:\.[0-9]+)?(?:\([a-z]\))?)\s*\.\s*(.+)$", re.IGNORECASE)
_NV_EFFECTIVE_DATE_RE = re.compile(r"effective\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})", re.IGNORECASE)
_CT_PRACTICE_BOOK_URL = "https://jud.ct.gov/Publications/PracticeBook/PB.pdf"
_CT_OFFICIAL_EDITION_RE = re.compile(r"OFFICIAL\s+(\d{4})\s+CONNECTICUT\s+PRACTICE\s+BOOK", re.IGNORECASE)
_CT_AREA_HEADER_RE = re.compile(r"^SUPERIOR COURT—PROCEDURE IN (CIVIL|CRIMINAL) MATTERS\b", re.IGNORECASE)
_CT_SECTION_HEADING_RE = re.compile(r"^Sec\.\s((?:1[1-9]|2[0-5]|3[6-9]|4[0-4])-\d+[A-Za-z]?)\.\s*(.*)$")
_CT_BODY_START_PREFIXES = (
    "A ",
    "An ",
    "Any ",
    "At ",
    "After ",
    "Before ",
    "Except ",
    "For ",
    "If ",
    "In ",
    "Matters ",
    "Motions ",
    "No ",
    "On ",
    "Such ",
    "The ",
    "These ",
    "This ",
    "To ",
    "Upon ",
    "Unless ",
    "Whenever ",
    "When ",
    "Where ",
    "Within ",
)
_ID_RULE_LIST_PAGES: List[Dict[str, str]] = [
    {
        "title_name": "Idaho Rules of Civil Procedure",
        "url": "https://isc.idaho.gov/ircp-new",
        "procedure_family": "civil_procedure",
        "legal_area": "civil_procedure",
        "official_cite_prefix": "I.R.C.P.",
    },
    {
        "title_name": "Idaho Criminal Rules",
        "url": "https://isc.idaho.gov/icr",
        "procedure_family": "criminal_procedure",
        "legal_area": "criminal_procedure",
        "official_cite_prefix": "I.C.R.",
    },
]
_ID_RULE_LINK_RE = re.compile(r"^Rule\s+(\d+(?:\.\d+)?)\.\s+(.+)$", re.IGNORECASE)
_ID_EFFECTIVE_DATE_RE = re.compile(r"effective\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})", re.IGNORECASE)
_ME_CIVIL_RULES_INDEX_URL = "https://www.courts.maine.gov/rules/rules-civil.html"
_ME_CRIMINAL_RULES_ONLY_URL = "https://www.courts.maine.gov/rules/text/mru_crim_p_only_2025-05-01.pdf"
_ME_CIVIL_REVIEWED_RE = re.compile(r"Last\s+reviewed\s+and\s+edited\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})", re.IGNORECASE)
_ME_CIVIL_AMENDMENTS_RE = re.compile(r"Includes amendments effective\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})", re.IGNORECASE)
_ME_CRIMINAL_EDITED_RE = re.compile(r"Last\s+reviewed\s+and\s+edited\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})", re.IGNORECASE)
_ME_CRIMINAL_AMENDMENTS_RE = re.compile(r"Including amendments effective\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})", re.IGNORECASE)
_ME_RULE_LINK_RE = re.compile(r"^Rule[s]?\s+([0-9]+(?:[A-Z]|\.[0-9A-Z]+| through Rule [0-9A-Z&\s.-]+)?)\s*-\s*(.+)$", re.IGNORECASE)
_ME_CRIMINAL_RULE_HEADING_RE = re.compile(r"^RULE\s+(\d+(?:[A-Z]|\.[0-9A-Z]+)?)\.\s+(.+)$")
_MD_RULE_TITLES: List[Dict[str, str]] = [
    {
        "title_name": "Title 2. Civil Procedure--Circuit Court",
        "url": "https://govt.westlaw.com/mdc/Browse/Home/Maryland/MarylandCodeCourtRules"
        "?guid=ND78623909CCE11DB9BCF9DAC28345A2A&originationContext=documenttoc"
        "&transitionType=Default&contextData=(sc.Default)",
        "procedure_family": "civil_procedure",
        "legal_area": "civil_procedure",
    },
    {
        "title_name": "Title 3. Civil Procedure--District Court",
        "url": "https://govt.westlaw.com/mdc/Browse/Home/Maryland/MarylandCodeCourtRules"
        "?guid=NDFFF2D009CCE11DB9BCF9DAC28345A2A&originationContext=documenttoc"
        "&transitionType=Default&contextData=(sc.Default)",
        "procedure_family": "civil_procedure",
        "legal_area": "civil_procedure",
    },
    {
        "title_name": "Title 4. Criminal Causes",
        "url": "https://govt.westlaw.com/mdc/Browse/Home/Maryland/MarylandCodeCourtRules"
        "?guid=NE57641109CCE11DB9BCF9DAC28345A2A&originationContext=documenttoc"
        "&transitionType=Default&contextData=(sc.Default)",
        "procedure_family": "criminal_procedure",
        "legal_area": "criminal_procedure",
    },
]
_MD_CHAPTER_LINK_RE = re.compile(r"^Chapter\s+(\d+)\.\s+(.+)$", re.IGNORECASE)
_MD_RULE_LINK_RE = re.compile(r"^Rule\s+([234]-\d+[A-Za-z]?(?:\.\d+)?)\.\s+(.+)$", re.IGNORECASE)
_MD_EFFECTIVE_DATE_RE = re.compile(r"Effective:\s*([A-Za-z]+\s+\d{1,2},\s+\d{4})", re.IGNORECASE)
_MD_CURRENT_AS_OF_RE = re.compile(
    r"Current\s+with\s+amendments\s+received\s+through\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})",
    re.IGNORECASE,
)
_SC_RULE_LIST_PAGES: List[Dict[str, str]] = [
    {
        "title_name": "South Carolina Rules of Civil Procedure",
        "url": "https://www.sccourts.org/resources/judicial-community/court-rules/civil/",
        "procedure_family": "civil_procedure",
        "legal_area": "civil_procedure",
        "official_cite_prefix": "SCRCP",
    },
    {
        "title_name": "South Carolina Rules of Criminal Procedure",
        "url": "https://www.sccourts.org/resources/judicial-community/court-rules/criminal/",
        "procedure_family": "criminal_procedure",
        "legal_area": "criminal_procedure",
        "official_cite_prefix": "SCRCrimP",
    },
]
_SC_RULE_LINK_RE = re.compile(r"^(\d+(?:\.\d+)?)\s+(.+)$")
_AK_RULE_DOCUMENTS: List[Dict[str, str]] = [
    {
        "title_name": "Alaska Rules of Civil Procedure",
        "url": "https://courts.alaska.gov/rules/docs/civ.pdf",
        "procedure_family": "civil_procedure",
        "legal_area": "civil_procedure",
        "official_cite_prefix": "Alaska R. Civ. P.",
        "start_marker": "Rule\n1 Scope of Rules",
    },
    {
        "title_name": "Alaska Rules of Criminal Procedure",
        "url": "https://courts.alaska.gov/rules/docs/crpro.pdf",
        "procedure_family": "criminal_procedure",
        "legal_area": "criminal_procedure",
        "official_cite_prefix": "Alaska R. Crim. P.",
        "start_marker": "Rule\n1 Scope.",
    },
]
_AK_RULE_BLOCK_RE = re.compile(
    r"^\s*Rule\s+(\d+(?:\.\d+)?)\.?\s+(.+?)(?=^\s*Rule\s+\d+(?:\.\d+)?\.?\s+|\Z)",
    re.DOTALL | re.IGNORECASE | re.MULTILINE,
)
_HI_RULE_SOURCES: List[Dict[str, str]] = [
    {
        "title_name": "Hawai‘i Rules of Civil Procedure",
        "url": "https://www.courts.state.hi.us/wp-content/uploads/2024/09/hrcp_ada.htm",
        "procedure_family": "civil_procedure",
        "legal_area": "civil_procedure",
        "official_cite_prefix": "HRCP Rule",
        "effective_date": "January 1, 2026",
    },
    {
        "title_name": "Hawai‘i Rules of Penal Procedure",
        "url": "https://www.courts.state.hi.us/wp-content/uploads/2024/12/hrpp.htm",
        "procedure_family": "criminal_procedure",
        "legal_area": "criminal_procedure",
        "official_cite_prefix": "HRPP Rule",
        "effective_date": "January 1, 2026",
    },
]
_HI_RULE_HEADING_RE = re.compile(r"^Rule\s+(\d+(?:\.\d+)*)(?:\.\s*(.*)|\s+(.*))?$")
_UT_RULE_LIST_PAGES: List[Dict[str, str]] = [
    {
        "title_name": "Utah Rules of Civil Procedure",
        "url": "https://legacy.utcourts.gov/rules/urcp.php",
        "procedure_family": "civil_procedure",
        "legal_area": "civil_procedure",
        "official_cite_prefix": "Utah R. Civ. P.",
        "type_code": "urcp",
    },
    {
        "title_name": "Utah Rules of Criminal Procedure",
        "url": "https://legacy.utcourts.gov/rules/urcrp.php",
        "procedure_family": "criminal_procedure",
        "legal_area": "criminal_procedure",
        "official_cite_prefix": "Utah R. Crim. P.",
        "type_code": "urcrp",
    },
]
_UT_RULE_LINK_RE = re.compile(r"^Rule\s+([0-9]+(?:\.[0-9]+|[A-Z])?)\.?\s+(.+?)(?:\.)?$", re.IGNORECASE)
_UT_RULE_PAGE_HEADING_RE = re.compile(r"^Rule\s+([0-9]+(?:\.[0-9]+|[A-Z])?)\.\s+(.+?)(?:\.)?$", re.IGNORECASE)
_UT_EFFECTIVE_DATE_RE = re.compile(r"^Effective:\s*(.+)$", re.IGNORECASE)
_NM_RULE_DOCUMENTS: List[Dict[str, str]] = [
    {
        "title_name": "New Mexico Rules of Civil Procedure for the District Courts",
        "url": "https://www.nmonesource.com/nmos/nmra/en/5687/1/document.do",
        "procedure_family": "civil_procedure",
        "legal_area": "civil_procedure",
        "official_cite_prefix": "Rule",
        "first_rule_number": "1-001",
    },
    {
        "title_name": "New Mexico Rules of Criminal Procedure for the District Courts",
        "url": "https://www.nmonesource.com/nmos/nmra/en/5672/1/document.do",
        "procedure_family": "criminal_procedure",
        "legal_area": "criminal_procedure",
        "official_cite_prefix": "Rule",
        "first_rule_number": "5-101",
    },
]
_NM_RULE_HEADING_RE = re.compile(r"^((?:1|5)-\d{3}(?:\.\d+)?[A-Za-z]?)\.\s+(.+)$")
_NM_EFFECTIVE_DATE_RE = re.compile(
    r"effective(?:\s+for\s+cases\s+filed\s+on\s+or\s+after)?\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})",
    re.IGNORECASE,
)
_WV_RULE_SOURCES: List[Dict[str, str]] = [
    {
        "title_name": "West Virginia Rules of Civil Procedure",
        "url": "https://www.courtswv.gov/sites/default/pubfilesmnt/2025-04/RCP%20Final%204-28-2025.pdf",
        "procedure_family": "civil_procedure",
        "legal_area": "civil_procedure",
        "official_cite_prefix": "W. Va. R. Civ. P.",
        "source_kind": "pdf",
    },
    {
        "title_name": "West Virginia Rules of Criminal Procedure",
        "url": "https://www.courtswv.gov/legal-community/court-rules/rules-criminal-procedure-contents",
        "procedure_family": "criminal_procedure",
        "legal_area": "criminal_procedure",
        "official_cite_prefix": "W. Va. R. Crim. P.",
        "source_kind": "html",
    },
]
_WV_RULE_HEADING_RE = re.compile(r"^Rule\s+(\d+(?:\.\d+)?)\.\s+(.+?)(?:\.)?$", re.IGNORECASE)
_WV_EFFECTIVE_DATE_RE = re.compile(r"\[.*?effective.*?([A-Za-z]+\s+\d{1,2},\s+\d{4}).*?\]", re.IGNORECASE)
_ND_RULE_LIST_PAGES: List[Dict[str, str]] = [
    {
        "title_name": "North Dakota Rules of Civil Procedure",
        "url": "https://www.ndcourts.gov/legal-resources/rules/ndrcivp",
        "procedure_family": "civil_procedure",
        "legal_area": "civil_procedure",
        "official_cite_prefix": "N.D.R.Civ.P.",
    },
    {
        "title_name": "North Dakota Rules of Criminal Procedure",
        "url": "https://www.ndcourts.gov/legal-resources/rules/ndrcrimp",
        "procedure_family": "criminal_procedure",
        "legal_area": "criminal_procedure",
        "official_cite_prefix": "N.D.R.Crim.P.",
    },
]
_ND_RULE_LINK_RE = re.compile(r"^Rule\s+(\d+(?:\.\d+)?)\.?\s+(.+?)(?:\.)?$", re.IGNORECASE)
_ND_EFFECTIVE_DATE_RE = re.compile(r"^Effective Date:\s*(.+)$", re.IGNORECASE)
_MN_RULE_LIST_PAGES: List[Dict[str, str]] = [
    {
        "title_name": "Minnesota Rules of Civil Procedure",
        "url": "https://www.revisor.mn.gov/court_rules/rule/cp-toh",
        "procedure_family": "civil_procedure",
        "legal_area": "civil_procedure",
        "official_cite_prefix": "Minn. R. Civ. P.",
    },
    {
        "title_name": "Minnesota Rules of Criminal Procedure",
        "url": "https://www.revisor.mn.gov/court_rules/rule/cr-toh",
        "procedure_family": "criminal_procedure",
        "legal_area": "criminal_procedure",
        "official_cite_prefix": "Minn. R. Crim. P.",
    },
]
_MN_RULE_LINK_RE = re.compile(r"^Rule\s+([0-9]+(?:\.[0-9]+)?[A-Za-z]?)\.$", re.IGNORECASE)
_MN_EFFECTIVE_TEXT_RE = re.compile(r"effective\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})", re.IGNORECASE)
_IA_RULE_DOCUMENTS: List[Dict[str, str]] = [
    {
        "title_name": "Iowa Rules of Civil Procedure",
        "url": "https://www.legis.iowa.gov/docs/ACO/CR/LINC/02-27-2026.chapter.1.pdf",
        "procedure_family": "civil_procedure",
        "legal_area": "civil_procedure",
        "official_cite_prefix": "Iowa R. Civ. P.",
        "first_rule_number": "1.101",
    },
    {
        "title_name": "Iowa Rules of Criminal Procedure",
        "url": "https://www.legis.iowa.gov/docs/ACO/CR/LINC/02-27-2026.chapter.2.pdf",
        "procedure_family": "criminal_procedure",
        "legal_area": "criminal_procedure",
        "official_cite_prefix": "Iowa R. Crim. P.",
        "first_rule_number": "2.1",
    },
]
_IA_EFFECTIVE_DATE_RE = re.compile(r"effective\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})", re.IGNORECASE)
_IA_RULE_HEADING_RE = re.compile(
    r"Rule\s+((?:1|2)\.\d(?:[\d ]*\d)?(?:\([a-z]\))?)\s+(.+?)"
    r"(?=Rule\s+(?:1|2)\.\d(?:[\d ]*\d)?(?:\([a-z]\))?\s|"
    r"Rules\s+(?:1|2)\.\d(?:[\d ]*\d)?\s+to\s+(?:1|2)\.\d(?:[\d ]*\d)?\s+Reserved|\Z)",
    re.DOTALL,
)
_AR_RULE_DOCUMENTS: List[Dict[str, str]] = [
    {
        "title_name": "Arkansas Rules of Civil Procedure",
        "url": "https://opinions.arcourts.gov/ark/cr/en/16712/1/document.do",
        "procedure_family": "civil_procedure",
        "legal_area": "civil_procedure",
        "official_cite_prefix": "Ark. R. Civ. P.",
        "first_rule_number": "1",
    },
    {
        "title_name": "Arkansas Rules of Criminal Procedure",
        "url": "https://opinions.arcourts.gov/ark/cr/en/1879/1/document.do",
        "procedure_family": "criminal_procedure",
        "legal_area": "criminal_procedure",
        "official_cite_prefix": "Ark. R. Crim. P.",
        "first_rule_number": "1.1",
    },
]
_AR_RULE_HEADING_LINE_RE = re.compile(r"^Rule\s+(\d+(?:\.\d+)?)\.\s+(.+)$")
_AR_EFFECTIVE_DATE_RE = re.compile(r"effective\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})", re.IGNORECASE)
_AL_RULE_LIST_PAGES: List[Dict[str, str]] = [
    {
        "title_name": "Alabama Rules of Civil Procedure",
        "url": "https://judicial.alabama.gov/library/CivilProcedure",
        "procedure_family": "civil_procedure",
        "legal_area": "civil_procedure",
        "official_cite_prefix": "Ala. R. Civ. P.",
        "url_prefix": "cv",
    },
    {
        "title_name": "Alabama Rules of Criminal Procedure",
        "url": "https://judicial.alabama.gov/library/criminalprocedure",
        "procedure_family": "criminal_procedure",
        "legal_area": "criminal_procedure",
        "official_cite_prefix": "Ala. R. Crim. P.",
        "url_prefix": "cr",
    },
]
_AL_RULE_LABEL_RE = re.compile(r"^Rules?\s+([0-9]+(?:\.[0-9]+)?[A-Za-z]?)\.\s*$", re.IGNORECASE)
_AL_EFFECTIVE_DATE_RE = re.compile(r"eff\.\s*([0-9-]+)|effective\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})", re.IGNORECASE)
_TN_RULE_LIST_PAGES: List[Dict[str, str]] = [
    {
        "title_name": "Tennessee Rules of Civil Procedure",
        "url": "https://www.tncourts.gov/courts/supreme-court/rules/rules-civil-procedure",
        "procedure_family": "civil_procedure",
        "legal_area": "civil_procedure",
        "official_cite_prefix": "Tenn. R. Civ. P.",
    },
    {
        "title_name": "Tennessee Rules of Criminal Procedure",
        "url": "https://www.tncourts.gov/courts/court-rules/rules-criminal-procedure",
        "procedure_family": "criminal_procedure",
        "legal_area": "criminal_procedure",
        "official_cite_prefix": "Tenn. R. Crim. P.",
    },
]
_TN_RULE_LINK_RE = re.compile(
    r"^Rule\s+([0-9]+(?:\.[0-9]+)?(?:[A-Za-z](?:\.\d+)?)?(?:\.\d+)?)[:.]?\s*(.+?)?\.?$",
    re.IGNORECASE,
)
_TN_RULE_HEADING_RE = re.compile(
    r"^Rule\s+([0-9]+(?:\.[0-9]+)?(?:[A-Za-z](?:\.\d+)?)?(?:\.\d+)?)[:.]?\s+(.+?)\.?$",
    re.IGNORECASE,
)
_TN_EFFECTIVE_DATE_RE = re.compile(r"effective\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})", re.IGNORECASE)
_VA_RULES_PDF_URL = "https://www.vacourts.gov/courts/scv/rulesofcourt.pdf"
_VA_RULE_SOURCES: List[Dict[str, str]] = [
    {
        "title_name": "Rules of Supreme Court of Virginia - Civil Procedure",
        "procedure_family": "civil_procedure",
        "legal_area": "civil_procedure",
        "official_cite_prefix": "Va. Sup. Ct. R.",
        "rule_prefix": "3:",
    },
    {
        "title_name": "Rules of Supreme Court of Virginia - Criminal Procedure",
        "procedure_family": "criminal_procedure",
        "legal_area": "criminal_procedure",
        "official_cite_prefix": "Va. Sup. Ct. R.",
        "rule_prefix": "3A:",
    },
]
_VA_EFFECTIVE_DATE_RE = re.compile(r"effective\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})", re.IGNORECASE)
_IN_RULE_SET_PAGES: List[Dict[str, str]] = [
    {
        "title_name": "Indiana Rules of Trial Procedure",
        "url": "https://rules.incourts.gov/Content/trial/default.htm",
        "procedure_family": "civil_procedure",
        "legal_area": "civil_procedure",
        "official_cite_prefix": "Ind. Trial Rule",
    },
    {
        "title_name": "Indiana Rules of Criminal Procedure",
        "url": "https://rules.incourts.gov/Content/criminal/default.htm",
        "procedure_family": "criminal_procedure",
        "legal_area": "criminal_procedure",
        "official_cite_prefix": "Ind. Crim. Rule",
    },
]
_IN_RULE_LINK_RE = re.compile(r"^Rule\s+([0-9]+(?:\.[0-9]+)?)\.\s+(.+?)$", re.IGNORECASE)
_IN_RULE_HEADING_RE = re.compile(r"^Rule\s+([0-9]+(?:\.[0-9]+)?)\.\s+(.+?)$", re.IGNORECASE)
_IN_EFFECTIVE_DATE_RE = re.compile(r"Effective\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})", re.IGNORECASE)
_IL_RULE_SET_PAGES: List[Dict[str, str]] = [
    {
        "title_name": "Illinois Supreme Court Rules - Civil Proceedings in the Trial Court",
        "url": "https://www.illinoiscourts.gov/rules/supreme-court-rules?a=ii",
        "procedure_family": "civil_procedure",
        "legal_area": "civil_procedure",
        "official_cite_prefix": "Ill. S. Ct. R.",
        "article_code": "II",
    },
    {
        "title_name": "Illinois Supreme Court Rules - Criminal Proceedings in the Trial Court",
        "url": "https://www.illinoiscourts.gov/rules/supreme-court-rules?a=iv",
        "procedure_family": "criminal_procedure",
        "legal_area": "criminal_procedure",
        "official_cite_prefix": "Ill. S. Ct. R.",
        "article_code": "IV",
    },
]
_IL_RULE_NUMBER_RE = re.compile(r"^Rule(?:s)?\s+([0-9]+(?:\.[0-9]+)?[A-Za-z]?)$", re.IGNORECASE)
_IL_PDF_HEADING_RE = re.compile(r"^Rule\s+([0-9]+(?:\.[0-9]+)?[A-Za-z]?)\.\s+(.+)$", re.IGNORECASE)
_IL_EFFECTIVE_DATE_RE = re.compile(
    r"(?:effective|eff\.)\s+([A-Za-z]+\s+\d{1,2},\s+\d{4}|immediately)",
    re.IGNORECASE,
)
_GA_RULE_DOCUMENTS: List[Dict[str, str]] = [
    {
        "title_name": "Uniform Superior Court Rules of Georgia",
        "url": "https://www.gasupreme.us/wp-content/uploads/2026/03/UNIFORM-SUPERIOR-COURT-RULES-2026_03_19.pdf",
        "procedure_family": "civil_and_criminal_procedure",
        "legal_area": "civil_and_criminal_procedure",
        "official_cite_prefix": "Ga. Unif. Super. Ct. R.",
        "first_rule_number": "1",
        "current_as_of": "March 19, 2026",
    },
    {
        "title_name": "Uniform State Court Rules of Georgia",
        "url": "https://www.gasupreme.us/wp-content/uploads/2024/01/UNIFORM-STATE-COURT-RULES-2024_01_18.pdf",
        "procedure_family": "civil_and_criminal_procedure",
        "legal_area": "civil_and_criminal_procedure",
        "official_cite_prefix": "Ga. Unif. State Ct. R.",
        "first_rule_number": "6",
        "current_as_of": "July 28, 2022",
    },
]
_GA_RULE_HEADING_RE = re.compile(r"^Rule\s+(\d+(?:\.\d+)*)\.\s*(.+?)\s*$", re.IGNORECASE)
_GA_EFFECTIVE_DATE_RE = re.compile(r"effective\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})", re.IGNORECASE)
_PA_RULE_CHAPTER_PAGES: List[Dict[str, str]] = [
    {
        "title_name": "Pennsylvania Rules of Civil Procedure",
        "url": "https://www.pacodeandbulletin.gov/Display/pacode?file=/secure/pacode/data/231/chapter100/chap100toc.html&d=reduce",
        "procedure_family": "civil_procedure",
        "legal_area": "civil_procedure",
        "official_cite_prefix": "Pa.R.Civ.P.",
        "first_rule_number": "51",
        "current_as_of": "January 3, 2026",
    },
    {
        "title_name": "Pennsylvania Rules of Criminal Procedure",
        "url": "https://www.pacodeandbulletin.gov/Display/pacode?file=/secure/pacode/data/234/chapter1/chap1toc.html&d=reduce",
        "procedure_family": "criminal_procedure",
        "legal_area": "criminal_procedure",
        "official_cite_prefix": "Pa.R.Crim.P.",
        "first_rule_number": "100",
        "current_as_of": "January 3, 2026",
    },
]
_PA_RULE_HEADING_RE = re.compile(r"^Rule\s+(\d+(?:\.\d+)*)\.\s*(.+?)\s*$", re.IGNORECASE)
_PA_SOURCE_RE = re.compile(r"^Source\s*$", re.IGNORECASE)
_NE_RULE_ARTICLES: List[Dict[str, str]] = [
    {
        "title_name": "Nebraska Court Rules of Pleading in Civil Cases",
        "url": "https://nebraskajudicial.gov/supreme-court-rules/chapter-6-trial-courts/"
        "article-11-nebraska-court-rules-pleading-civil-cases-effective-january-1-2025",
        "procedure_family": "civil_procedure",
        "legal_area": "civil_procedure",
        "official_cite_prefix": "Neb. Ct. R. Pldg.",
    },
    {
        "title_name": "Uniform County Court Rules of Practice and Procedure",
        "url": "https://nebraskajudicial.gov/supreme-court-rules/chapter-6-trial-courts/"
        "article-14-uniform-county-court-rules-practice-and-procedure",
        "procedure_family": "civil_and_criminal_procedure",
        "legal_area": "civil_and_criminal_procedure",
        "official_cite_prefix": "Neb. Ct. R. §",
    },
    {
        "title_name": "Uniform District Court Rules of Practice and Procedure",
        "url": "https://nebraskajudicial.gov/supreme-court-rules/chapter-6-trial-courts/"
        "article-15-uniform-district-court-rules-practice-and-procedure",
        "procedure_family": "civil_and_criminal_procedure",
        "legal_area": "civil_and_criminal_procedure",
        "official_cite_prefix": "Neb. Ct. R. §",
    },
]
_NE_SECTION_LINK_RE = re.compile(r"^§\s*(6-\d+(?:\.\d+)?)\.\s+(.+?)(?:\.)?$", re.IGNORECASE)
_NE_EFFECTIVE_DATE_RE = re.compile(r"effective\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})", re.IGNORECASE)

_CIVIL_PATTERNS = [
    re.compile(r"rules?\s+of\s+civil\s+procedure", re.IGNORECASE),
    re.compile(r"civil\s+procedure", re.IGNORECASE),
    re.compile(r"code\s+of\s+civil\s+procedure", re.IGNORECASE),
    re.compile(r"civil\s+practice", re.IGNORECASE),
    re.compile(r"civil\s+actions?", re.IGNORECASE),
    re.compile(r"rules?\s+of\s+court", re.IGNORECASE),
]

_CRIMINAL_PATTERNS = [
    re.compile(r"rules?\s+of\s+criminal\s+procedure", re.IGNORECASE),
    re.compile(r"criminal\s+procedure", re.IGNORECASE),
    re.compile(r"code\s+of\s+criminal\s+procedure", re.IGNORECASE),
    re.compile(r"criminal\s+practice", re.IGNORECASE),
    re.compile(r"criminal\s+actions?", re.IGNORECASE),
]


def _signal_text(statute: Dict[str, Any]) -> str:
    fields: List[str] = []
    is_part_of = statute.get("isPartOf")
    if isinstance(is_part_of, dict):
        name = is_part_of.get("name")
        if isinstance(name, str):
            fields.append(name)

    for key in [
        "code_name",
        "name",
        "titleName",
        "chapterName",
        "sectionName",
        "legislationType",
        "official_cite",
        "section_name",
        "full_text",
        "text",
        "source_url",
    ]:
        value = statute.get(key)
        if isinstance(value, str):
            fields.append(value)

    return "\n".join(v for v in fields if v)


def _classify_procedure_family(statute: Dict[str, Any]) -> Optional[str]:
    signal = _signal_text(statute)
    civil = any(pattern.search(signal) for pattern in _CIVIL_PATTERNS)
    criminal = any(pattern.search(signal) for pattern in _CRIMINAL_PATTERNS)

    if civil and criminal:
        return "civil_and_criminal_procedure"
    if civil:
        return "civil_procedure"
    if criminal:
        return "criminal_procedure"
    return None


class _ProcedureRulesSupplementFetcher(BaseStateScraper):
    def get_base_url(self) -> str:
        return "https://www.courts.ri.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        return []

    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return []


class _MichiganProcedureRulesSupplementFetcher(BaseStateScraper):
    def get_base_url(self) -> str:
        return "https://www.courts.michigan.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        return []

    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return []


class _CaliforniaProcedureRulesSupplementFetcher(BaseStateScraper):
    def get_base_url(self) -> str:
        return "https://courts.ca.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        return []

    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return []


class _OhioProcedureRulesSupplementFetcher(BaseStateScraper):
    def get_base_url(self) -> str:
        return "https://www.supremecourt.ohio.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        return []

    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return []


class _ArizonaProcedureRulesSupplementFetcher(BaseStateScraper):
    def get_base_url(self) -> str:
        return "https://www.azcourts.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        return []

    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return []


class _WashingtonProcedureRulesSupplementFetcher(BaseStateScraper):
    def get_base_url(self) -> str:
        return "https://www.courts.wa.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        return []

    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return []


class _NewJerseyProcedureRulesSupplementFetcher(BaseStateScraper):
    def get_base_url(self) -> str:
        return "https://www.njcourts.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        return []

    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return []


class _NewHampshireProcedureRulesSupplementFetcher(BaseStateScraper):
    def get_base_url(self) -> str:
        return "https://www.courts.nh.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        return []

    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return []


class _NevadaProcedureRulesSupplementFetcher(BaseStateScraper):
    def get_base_url(self) -> str:
        return "https://www.leg.state.nv.us"

    def get_code_list(self) -> List[Dict[str, str]]:
        return []

    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return []


class _ConnecticutProcedureRulesSupplementFetcher(BaseStateScraper):
    def get_base_url(self) -> str:
        return "https://jud.ct.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        return []

    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return []


class _IdahoProcedureRulesSupplementFetcher(BaseStateScraper):
    def get_base_url(self) -> str:
        return "https://isc.idaho.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        return []

    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return []


class _MaineProcedureRulesSupplementFetcher(BaseStateScraper):
    def get_base_url(self) -> str:
        return "https://www.courts.maine.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        return []

    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return []


class _MarylandProcedureRulesSupplementFetcher(BaseStateScraper):
    def get_base_url(self) -> str:
        return "https://govt.westlaw.com"

    def get_code_list(self) -> List[Dict[str, str]]:
        return []

    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return []


class _SouthCarolinaProcedureRulesSupplementFetcher(BaseStateScraper):
    def get_base_url(self) -> str:
        return "https://www.sccourts.org"

    def get_code_list(self) -> List[Dict[str, str]]:
        return []

    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return []


class _AlaskaProcedureRulesSupplementFetcher(BaseStateScraper):
    def get_base_url(self) -> str:
        return "https://courts.alaska.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        return []

    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return []


class _NebraskaProcedureRulesSupplementFetcher(BaseStateScraper):
    def get_base_url(self) -> str:
        return "https://nebraskajudicial.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        return []

    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return []


class _HawaiiProcedureRulesSupplementFetcher(BaseStateScraper):
    def get_base_url(self) -> str:
        return "https://www.courts.state.hi.us"

    def get_code_list(self) -> List[Dict[str, str]]:
        return []

    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return []


class _UtahProcedureRulesSupplementFetcher(BaseStateScraper):
    def get_base_url(self) -> str:
        return "https://legacy.utcourts.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        return []

    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return []


class _NewMexicoProcedureRulesSupplementFetcher(BaseStateScraper):
    def get_base_url(self) -> str:
        return "https://www.nmonesource.com"

    def get_code_list(self) -> List[Dict[str, str]]:
        return []

    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return []


class _WestVirginiaProcedureRulesSupplementFetcher(BaseStateScraper):
    def get_base_url(self) -> str:
        return "https://www.courtswv.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        return []

    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return []


class _NorthDakotaProcedureRulesSupplementFetcher(BaseStateScraper):
    def get_base_url(self) -> str:
        return "https://www.ndcourts.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        return []

    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return []


class _MinnesotaProcedureRulesSupplementFetcher(BaseStateScraper):
    def get_base_url(self) -> str:
        return "https://www.revisor.mn.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        return []

    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return []


class _IowaProcedureRulesSupplementFetcher(BaseStateScraper):
    def get_base_url(self) -> str:
        return "https://www.legis.iowa.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        return []

    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return []


class _ArkansasProcedureRulesSupplementFetcher(BaseStateScraper):
    def get_base_url(self) -> str:
        return "https://opinions.arcourts.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        return []

    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return []


class _AlabamaProcedureRulesSupplementFetcher(BaseStateScraper):
    def get_base_url(self) -> str:
        return "https://judicial.alabama.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        return []

    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return []


class _TennesseeProcedureRulesSupplementFetcher(BaseStateScraper):
    def get_base_url(self) -> str:
        return "https://www.tncourts.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        return []

    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return []


class _VirginiaProcedureRulesSupplementFetcher(BaseStateScraper):
    def get_base_url(self) -> str:
        return "https://www.vacourts.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        return []

    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return []


class _IndianaProcedureRulesSupplementFetcher(BaseStateScraper):
    def get_base_url(self) -> str:
        return "https://rules.incourts.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        return []

    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return []


class _IllinoisProcedureRulesSupplementFetcher(BaseStateScraper):
    def get_base_url(self) -> str:
        return "https://www.illinoiscourts.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        return []

    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return []


class _GeorgiaProcedureRulesSupplementFetcher(BaseStateScraper):
    def get_base_url(self) -> str:
        return "https://www.gasupreme.us"

    def get_code_list(self) -> List[Dict[str, str]]:
        return []

    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return []


class _PennsylvaniaProcedureRulesSupplementFetcher(BaseStateScraper):
    def get_base_url(self) -> str:
        return "https://www.pacodeandbulletin.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        return []

    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return []


def _extract_rhode_island_rule_links(html_text: str, page_url: str) -> List[Dict[str, str]]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    soup = BeautifulSoup(html_text, "html.parser")
    discovered: List[Dict[str, str]] = []
    seen = set()

    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        if not href:
            continue

        text = " ".join(anchor.get_text(" ", strip=True).split())
        absolute_url = urljoin(page_url, href)
        parsed = urlparse(absolute_url)
        if parsed.scheme not in {"http", "https"}:
            continue
        if parsed.netloc.lower() != "www.courts.ri.gov":
            continue

        is_rule_page = bool(_RI_COURT_RULES_PAGE_RE.search(parsed.path))
        is_pdf = bool(_RI_COURT_RULES_DOC_RE.search(absolute_url))
        if not is_rule_page and not is_pdf:
            continue
        if is_pdf and not _RI_COURT_RULES_ALLOWED_DOC_PATH_RE.search(parsed.path):
            continue

        signal_text = " ".join(
            value for value in [text, absolute_url.rsplit("/", 1)[-1].replace("-", " ")] if value
        )
        if not _RI_COURT_RULE_SIGNAL_RE.search(signal_text):
            continue
        if _RI_COURT_RULE_EXCLUDED_TEXT_RE.search(signal_text):
            continue

        key = absolute_url.lower()
        if key in seen:
            continue
        seen.add(key)
        discovered.append(
            {
                "label": text or Path(parsed.path).stem.replace("-", " "),
                "url": absolute_url,
                "kind": "pdf" if is_pdf else "page",
            }
        )

    return discovered


def _extract_washington_rule_links(
    html_text: str,
    *,
    page_url: str,
    procedure_family: str,
    legal_area: str,
    official_cite_prefix: str,
) -> List[Dict[str, str]]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    soup = BeautifulSoup(html_text, "html.parser")
    discovered: List[Dict[str, str]] = []
    seen = set()

    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) != 2:
            continue

        section_number = " ".join(cells[0].get_text(" ", strip=True).split())
        if not section_number or not _WA_RULE_SECTION_NUMBER_RE.match(section_number):
            continue

        anchor = cells[1].find("a", href=True)
        if anchor is None:
            continue

        href = str(anchor.get("href") or "").strip()
        section_name = " ".join(anchor.get_text(" ", strip=True).split())
        if not href or not section_name:
            continue

        absolute_url = urljoin(page_url, href)
        if not absolute_url.lower().endswith(".pdf"):
            continue

        key = absolute_url.lower()
        if key in seen:
            continue
        seen.add(key)
        discovered.append(
            {
                "section_number": section_number,
                "section_name": section_name,
                "url": absolute_url,
                "procedure_family": procedure_family,
                "legal_area": legal_area,
                "official_cite_prefix": official_cite_prefix,
            }
        )

    return discovered


def _extract_new_jersey_rule_from_description(
    description_html: str,
    *,
    section_number: str,
    section_name: str,
    source_url: str,
    title_name: str,
    procedure_family: str,
    legal_area: str,
) -> Optional[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None

    soup = BeautifulSoup(description_html or "", "html.parser")
    text_lines = [" ".join(line.split()) for line in soup.get_text("\n", strip=True).splitlines()]
    text_lines = [line for line in text_lines if line]
    if not text_lines:
        return None

    full_text = "\n".join(text_lines).strip()
    if len(full_text) < 40:
        return None

    effective_dates = [
        " ".join(match.group(1).split())
        for match in _NJ_EFFECTIVE_DATE_RE.finditer(full_text)
        if match.group(1)
    ]
    effective_date = effective_dates[-1] if effective_dates else None

    return NormalizedStatute(
        state_code="NJ",
        state_name=US_STATES["NJ"],
        statute_id=f"N.J. Ct. R. {section_number}",
        code_name=title_name,
        title_name=title_name,
        chapter_name=title_name,
        section_number=section_number,
        section_name=section_name,
        short_title=section_name,
        full_text=full_text,
        summary=section_name,
        source_url=source_url,
        official_cite=f"N.J. Ct. R. {section_number}",
        legal_area=legal_area,
        structured_data={
            "effective_date": effective_date,
            "source_kind": "njcourts_rules_api",
            "procedure_family": procedure_family,
        },
    )


def _extract_new_hampshire_rules_from_online_book_html(
    html_text: str,
    *,
    source_url: str,
    title_name: str,
    procedure_family: str,
    legal_area: str,
    official_cite_prefix: str,
    rule_number_max: int = 99,
) -> List[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    soup = BeautifulSoup(html_text or "", "html.parser")
    pages = soup.select("div.online__book__page")
    if not pages:
        return []

    page_text = " ".join(soup.get_text(" ", strip=True).split())
    effective_matches = [
        " ".join(match.group(1).split())
        for match in _NH_EFFECTIVE_DATE_RE.finditer(page_text)
        if match.group(1)
    ]
    effective_date = effective_matches[0] if effective_matches else None

    statutes: List[NormalizedStatute] = []
    seen = set()

    for page in pages:
        heading = page.select_one(".online__book__page__header h4")
        content = page.select_one(".online__book__page__content")
        if heading is None or content is None:
            continue

        heading_text = " ".join(heading.get_text(" ", strip=True).split())
        match = _NH_RULE_HEADING_RE.match(heading_text)
        if not match:
            continue

        section_number = match.group(1).strip()
        section_name = match.group(2).strip().rstrip(".")
        if not section_number or not section_name:
            continue

        numeric_match = re.match(r"^(\d+)", section_number)
        if numeric_match and int(numeric_match.group(1)) > int(rule_number_max):
            continue

        content_lines = [
            " ".join(str(line or "").split())
            for line in content.get_text("\n", strip=True).splitlines()
        ]
        content_lines = [line for line in content_lines if line and line.lower() != "back to top" and line != "--"]
        full_text = "\n".join([heading_text, *content_lines]).strip()
        if len(full_text) < 80:
            continue

        page_id = str(page.get("id") or "").strip()
        anchor_url = f"{source_url}#{page_id}" if page_id else source_url
        statute = NormalizedStatute(
            state_code="NH",
            state_name=US_STATES["NH"],
            statute_id=f"{official_cite_prefix} {section_number}",
            code_name=title_name,
            title_name=title_name,
            chapter_name=title_name,
            section_number=section_number,
            section_name=section_name,
            short_title=section_name,
            full_text=full_text,
            summary=section_name,
            source_url=anchor_url,
            official_cite=f"{official_cite_prefix} {section_number}",
            legal_area=legal_area,
            structured_data={
                "effective_date": effective_date,
                "source_kind": "nh_online_book_html",
                "procedure_family": procedure_family,
            },
        )
        key = (section_number.lower(), section_name.lower())
        if key in seen:
            continue
        seen.add(key)
        statutes.append(statute)

    return statutes


def _extract_nevada_rules_from_html(
    html_text: str,
    *,
    source_url: str,
    title_name: str,
    procedure_family: str,
    legal_area: str,
    official_cite_prefix: str,
) -> List[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    soup = BeautifulSoup(html_text or "", "html.parser")
    effective_matches = [
        " ".join(match.group(1).split())
        for match in _NV_EFFECTIVE_DATE_RE.finditer(" ".join(soup.get_text(" ", strip=True).split()))
        if match.group(1)
    ]
    effective_date = effective_matches[-1] if effective_matches else None

    statutes: List[NormalizedStatute] = []
    seen = set()
    current_number = ""
    current_name = ""
    current_anchor = ""
    buffer: List[str] = []
    current_effective_date = effective_date

    def flush() -> None:
        nonlocal current_number, current_name, current_anchor, buffer, current_effective_date
        if not current_number or not current_name:
            current_number = ""
            current_name = ""
            current_anchor = ""
            buffer = []
            current_effective_date = effective_date
            return

        full_text = "\n".join(buffer).strip()
        if len(full_text) < 60:
            current_number = ""
            current_name = ""
            current_anchor = ""
            buffer = []
            current_effective_date = effective_date
            return

        key = (current_number.lower(), current_name.lower())
        if key not in seen:
            seen.add(key)
            statutes.append(
                NormalizedStatute(
                    state_code="NV",
                    state_name=US_STATES["NV"],
                    statute_id=f"{official_cite_prefix} {current_number}",
                    code_name=title_name,
                    title_name=title_name,
                    chapter_name=title_name,
                    section_number=current_number,
                    section_name=current_name,
                    short_title=current_name,
                    full_text=full_text,
                    summary=current_name,
                    source_url=f"{source_url}#{current_anchor}" if current_anchor else source_url,
                    official_cite=f"{official_cite_prefix} {current_number}",
                    legal_area=legal_area,
                    structured_data={
                        "effective_date": current_effective_date,
                        "source_kind": "nevada_legislature_html",
                        "procedure_family": procedure_family,
                    },
                )
            )

        current_number = ""
        current_name = ""
        current_anchor = ""
        buffer = []
        current_effective_date = effective_date

    for paragraph in soup.find_all("p"):
        classes = set(paragraph.get("class") or [])
        text = " ".join(paragraph.get_text(" ", strip=True).split())
        if not text:
            continue

        heading_match = _NV_RULE_HEADING_RE.match(text)
        if "SectBody" in classes and heading_match:
            flush()
            current_number = heading_match.group(1).strip()
            current_name = heading_match.group(2).strip().rstrip(".")
            anchor = paragraph.find("a")
            current_anchor = str(anchor.get("name") or anchor.get("id") or "").strip() if anchor else ""
            buffer = [f"Rule {current_number}. {current_name}"]
            continue

        if not current_number:
            continue

        if "SourceNote" in classes:
            buffer.append(text)
            source_effective_matches = [
                " ".join(match.group(1).split())
                for match in _NV_EFFECTIVE_DATE_RE.finditer(text)
                if match.group(1)
            ]
            if source_effective_matches:
                current_effective_date = source_effective_matches[-1]
            continue

        if "SectBody" in classes:
            buffer.append(text)

    flush()
    return statutes


def _extract_idaho_rule_links(
    html_text: str,
    *,
    page_url: str,
    procedure_family: str,
    legal_area: str,
    official_cite_prefix: str,
) -> List[Dict[str, str]]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    soup = BeautifulSoup(html_text or "", "html.parser")
    content = soup.select_one("div.field-name-body")
    if content is None:
        return []

    discovered: List[Dict[str, str]] = []
    seen = set()
    for anchor in content.select("a[href]"):
        href = str(anchor.get("href") or "").strip()
        parent = anchor.find_parent("p")
        label_source = parent.get_text(" ", strip=True) if parent is not None else anchor.get_text(" ", strip=True)
        label = " ".join(str(label_source or "").split())
        if not href or "Rule " not in label:
            continue
        match = _ID_RULE_LINK_RE.match(label)
        if not match:
            continue
        absolute_url = urljoin(page_url, href)
        key = absolute_url.lower()
        if key in seen:
            continue
        seen.add(key)
        discovered.append(
            {
                "section_number": match.group(1).strip(),
                "section_name": match.group(2).strip().rstrip("."),
                "url": absolute_url,
                "procedure_family": procedure_family,
                "legal_area": legal_area,
                "official_cite_prefix": official_cite_prefix,
            }
        )

    return discovered


def _extract_idaho_rule_from_html(
    html_text: str,
    *,
    rule_url: str,
    title_name: str,
    procedure_family: str,
    legal_area: str,
    official_cite_prefix: str,
) -> Optional[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None

    soup = BeautifulSoup(html_text or "", "html.parser")
    content = soup.select_one("div.field-name-body div.field-item")
    if content is None:
        return None

    text_lines = []
    for node in content.find_all(["p", "h2", "h3"]):
        text = " ".join(node.get_text(" ", strip=True).split())
        if not text or text == "\u00a0":
            continue
        if text.startswith("Members of the ") or text == "TERMS OF OFFICE":
            break
        text_lines.append(text)

    if not text_lines:
        return None

    heading = text_lines[0]
    heading_match = re.search(r"Rule\s+(\d+(?:\.\d+)?)\.\s+(.+)$", heading, re.IGNORECASE)
    if not heading_match:
        return None

    section_number = heading_match.group(1).strip()
    section_name = heading_match.group(2).strip().rstrip(".")
    full_text = "\n".join(text_lines).strip()
    if len(full_text) < 40:
        return None

    effective_dates = [
        " ".join(match.group(1).split())
        for match in _ID_EFFECTIVE_DATE_RE.finditer(full_text)
        if match.group(1)
    ]
    effective_date = effective_dates[-1] if effective_dates else None

    return NormalizedStatute(
        state_code="ID",
        state_name=US_STATES["ID"],
        statute_id=f"{official_cite_prefix} {section_number}",
        code_name=title_name,
        title_name=title_name,
        chapter_name=title_name,
        section_number=section_number,
        section_name=section_name,
        short_title=section_name,
        full_text=full_text,
        summary=section_name,
        source_url=f"{rule_url}#rule-{section_number.lower()}",
        official_cite=f"{official_cite_prefix} {section_number}",
        legal_area=legal_area,
        structured_data={
            "effective_date": effective_date,
            "source_kind": "idaho_supreme_court_rule_page",
            "procedure_family": procedure_family,
        },
    )


def _extract_maine_civil_rule_links(
    html_text: str,
    *,
    index_url: str,
) -> tuple[List[Dict[str, str]], Optional[str], Optional[str]]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return [], None, None

    soup = BeautifulSoup(html_text or "", "html.parser")
    content = soup.select_one("#maincontent2")
    if content is None:
        return [], None, None

    page_text = " ".join(content.get_text(" ", strip=True).split())
    reviewed_match = _ME_CIVIL_REVIEWED_RE.search(page_text)
    amendments_match = _ME_CIVIL_AMENDMENTS_RE.search(page_text)
    reviewed_date = reviewed_match.group(1) if reviewed_match else None
    amendments_effective = amendments_match.group(1) if amendments_match else None

    discovered: List[Dict[str, str]] = []
    seen = set()
    for anchor in content.select("a[href]"):
        href = str(anchor.get("href") or "").strip()
        label = " ".join(anchor.get_text(" ", strip=True).split())
        if not href or not label.startswith("Rule"):
            continue
        match = _ME_RULE_LINK_RE.match(label)
        if not match:
            continue
        absolute_url = urljoin(index_url, href)
        if not absolute_url.lower().endswith(".pdf"):
            continue
        key = absolute_url.lower()
        if key in seen:
            continue
        seen.add(key)
        discovered.append(
            {
                "section_number": match.group(1).strip(),
                "section_name": match.group(2).strip(),
                "url": absolute_url,
                "procedure_family": "civil_procedure",
                "legal_area": "civil_procedure",
                "official_cite_prefix": "Me. R. Civ. P.",
            }
        )

    return discovered, reviewed_date, amendments_effective


def _extract_maine_civil_rule_from_text(
    text: str,
    *,
    source_url: str,
    section_number: str,
    section_name: str,
    reviewed_date: Optional[str],
    amendments_effective: Optional[str],
) -> Optional[NormalizedStatute]:
    normalized_text = " ".join(str(text or "").replace("\r", " ").replace("\n", " ").split())
    if len(normalized_text) < 60:
        return None

    start_marker = f"RULE {section_number}".upper()
    start_index = normalized_text.upper().find(start_marker)
    full_text = normalized_text[start_index:].strip() if start_index != -1 else normalized_text
    if len(full_text) < 60:
        return None

    return NormalizedStatute(
        state_code="ME",
        state_name=US_STATES["ME"],
        statute_id=f"Me. R. Civ. P. {section_number}",
        code_name="Maine Rules of Civil Procedure",
        title_name="Maine Rules of Civil Procedure",
        chapter_name="Maine Rules of Civil Procedure",
        section_number=section_number,
        section_name=section_name,
        short_title=section_name,
        full_text=full_text,
        summary=section_name,
        source_url=f"{source_url}#rule-{section_number.lower().replace(' ', '-')}",
        official_cite=f"Me. R. Civ. P. {section_number}",
        legal_area="civil_procedure",
        structured_data={
            "reviewed_date": reviewed_date,
            "effective_date": amendments_effective,
            "source_kind": "maine_civil_rule_pdf",
            "procedure_family": "civil_procedure",
        },
    )


def _extract_maine_criminal_rules_from_page_texts(
    page_texts: List[tuple[int, str]],
    *,
    source_url: str,
) -> List[NormalizedStatute]:
    combined_intro = " ".join(text for page_num, text in page_texts[:4] if page_num <= 4)
    reviewed_match = _ME_CRIMINAL_EDITED_RE.search(combined_intro)
    amendments_match = _ME_CRIMINAL_AMENDMENTS_RE.search(combined_intro)
    reviewed_date = reviewed_match.group(1) if reviewed_match else None
    amendments_effective = amendments_match.group(1) if amendments_match else None

    statutes: List[NormalizedStatute] = []
    seen = set()
    current_number = ""
    current_name_parts: List[str] = []
    current_lines: List[str] = []
    current_page = 0
    collecting = False

    def flush() -> None:
        nonlocal current_number, current_name_parts, current_lines, current_page
        if not current_number:
            current_number = ""
            current_name_parts = []
            current_lines = []
            current_page = 0
            return
        section_name = " ".join(part.strip() for part in current_name_parts if part.strip()).strip().rstrip(".")
        full_text = "\n".join(current_lines).strip()
        key = (current_number.lower(), section_name.lower())
        if section_name and len(full_text) >= 60 and key not in seen:
            seen.add(key)
            statutes.append(
                NormalizedStatute(
                    state_code="ME",
                    state_name=US_STATES["ME"],
                    statute_id=f"Me. R. U. Crim. P. {current_number}",
                    code_name="Maine Rules of Unified Criminal Procedure",
                    title_name="Maine Rules of Unified Criminal Procedure",
                    chapter_name="Maine Rules of Unified Criminal Procedure",
                    section_number=current_number,
                    section_name=section_name,
                    short_title=section_name,
                    full_text=full_text,
                    summary=section_name,
                    source_url=f"{source_url}#page={current_page}" if current_page else source_url,
                    official_cite=f"Me. R. U. Crim. P. {current_number}",
                    legal_area="criminal_procedure",
                    structured_data={
                        "reviewed_date": reviewed_date,
                        "effective_date": amendments_effective,
                        "source_kind": "maine_criminal_rules_only_pdf",
                        "procedure_family": "criminal_procedure",
                        "page_start": current_page or None,
                    },
                )
            )
        current_number = ""
        current_name_parts = []
        current_lines = []
        current_page = 0

    for page_number, page_text in page_texts:
        if page_number < 17:
            continue
        for raw_line in str(page_text or "").splitlines():
            line = " ".join(raw_line.replace("\x00", " ").split())
            if not line or line.isdigit():
                continue
            if line in {"MAINE RULES OF UNIFIED CRIMINAL PROCEDURE", "I. SCOPE, PURPOSE, AND CONSTRUCTION"}:
                continue
            if re.match(r"^[IVXLC]+\.\s", line):
                continue
            match = _ME_CRIMINAL_RULE_HEADING_RE.match(line)
            if match:
                collecting = True
                flush()
                current_number = match.group(1).strip()
                current_name_parts = [match.group(2).strip()]
                current_lines = [f"RULE {current_number}. {match.group(2).strip()}"]
                current_page = page_number
                continue
            if not collecting or not current_number:
                continue
            if current_name_parts and current_name_parts[-1].endswith(("OF", "THE", "TO", "WITH", "AS")):
                current_name_parts.append(line)
                current_lines[0] = f"RULE {current_number}. {' '.join(current_name_parts)}"
                continue
            current_lines.append(line)
    flush()
    return statutes


def _connecticut_procedure_family_for_section(section_number: str) -> Optional[str]:
    numeric_prefix = int(str(section_number or "0").split("-", 1)[0] or 0)
    if 11 <= numeric_prefix <= 25:
        return "civil_procedure"
    if 36 <= numeric_prefix <= 44:
        return "criminal_procedure"
    return None


def _join_connecticut_heading_parts(parts: List[str]) -> str:
    joined = ""
    for part in parts:
        cleaned = " ".join(str(part or "").split())
        if not cleaned:
            continue
        if joined.endswith("-"):
            joined = joined[:-1] + cleaned.lstrip()
        else:
            joined = f"{joined} {cleaned}".strip()
    return joined.strip().rstrip(".")


def _looks_like_connecticut_body_start(line: str) -> bool:
    normalized = " ".join(str(line or "").split())
    if not normalized:
        return False
    if normalized.startswith(("(", "[", '"', "'")):
        return True
    if re.match(r"^[A-Za-z0-9]+\)", normalized):
        return True
    for prefix in _CT_BODY_START_PREFIXES:
        if normalized.startswith(prefix):
            return True
    return normalized.endswith(".")


def _split_connecticut_heading_and_body(text: str) -> tuple[str, List[str]]:
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return "", []
    starts_like_body = normalized.startswith(("(", "[", '"', "'")) or bool(re.match(r"^[A-Za-z0-9]+\)", normalized))
    if not starts_like_body:
        starts_like_body = any(normalized.startswith(prefix) for prefix in _CT_BODY_START_PREFIXES)
    if starts_like_body:
        return "", [normalized]

    split_points: List[int] = []
    for prefix in _CT_BODY_START_PREFIXES:
        marker = f" {prefix}"
        index = normalized.find(marker)
        if index > 0:
            split_points.append(index)
    pattern_match = re.search(r"\s(\([a-z0-9]+\))\s", normalized)
    if pattern_match and pattern_match.start() > 0:
        split_points.append(pattern_match.start())

    if not split_points:
        return normalized, []

    split_at = min(split_points)
    heading = normalized[:split_at].strip()
    body = normalized[split_at:].strip()
    return heading, [body] if body else []


def _extract_connecticut_rules_from_page_texts(
    page_texts: List[tuple[int, str]],
    *,
    source_url: str,
) -> List[NormalizedStatute]:
    edition_year = None
    for _page_number, text in page_texts[:12]:
        match = _CT_OFFICIAL_EDITION_RE.search(str(text or ""))
        if match:
            edition_year = match.group(1)
            break

    code_name = "Connecticut Practice Book"
    title_lookup = {
        "civil_procedure": f"Connecticut Practice Book {edition_year} - Superior Court Procedure in Civil Matters"
        if edition_year
        else "Connecticut Practice Book - Superior Court Procedure in Civil Matters",
        "criminal_procedure": f"Connecticut Practice Book {edition_year} - Superior Court Procedure in Criminal Matters"
        if edition_year
        else "Connecticut Practice Book - Superior Court Procedure in Criminal Matters",
    }

    statutes: List[NormalizedStatute] = []
    seen = set()
    current_family: Optional[str] = None
    current_number = ""
    current_page = 0
    heading_parts: List[str] = []
    content_lines: List[str] = []
    heading_mode = False

    def flush() -> None:
        nonlocal current_family, current_number, current_page, heading_parts, content_lines, heading_mode
        if not current_family or not current_number:
            current_number = ""
            current_page = 0
            heading_parts = []
            content_lines = []
            heading_mode = False
            return

        section_name = _join_connecticut_heading_parts(heading_parts)
        full_lines = [f"Sec. {current_number}. {section_name}" if section_name else f"Sec. {current_number}."]
        full_lines.extend(line for line in content_lines if line)
        full_text = "\n".join(full_lines).strip()
        if section_name and len(full_text) >= 40:
            key = (current_number.lower(), section_name.lower())
            if key not in seen:
                seen.add(key)
                title_name = title_lookup[current_family]
                statutes.append(
                    NormalizedStatute(
                        state_code="CT",
                        state_name=US_STATES["CT"],
                        statute_id=f"Conn. Practice Book § {current_number}",
                        code_name=code_name,
                        title_name=title_name,
                        chapter_name=title_name,
                        section_number=current_number,
                        section_name=section_name,
                        short_title=section_name,
                        full_text=full_text,
                        summary=section_name,
                        source_url=f"{source_url}#page={current_page}" if current_page else source_url,
                        official_cite=f"Conn. Practice Book § {current_number}",
                        legal_area=current_family,
                        structured_data={
                            "edition_year": edition_year,
                            "source_kind": "ct_practice_book_pdf",
                            "procedure_family": current_family,
                            "page_start": current_page or None,
                        },
                    )
                )

        current_number = ""
        current_page = 0
        heading_parts = []
        content_lines = []
        heading_mode = False

    for page_number, page_text in page_texts:
        for raw_line in str(page_text or "").splitlines():
            line = " ".join(raw_line.replace("\x00", " ").split())
            if not line or line.isdigit() or line.startswith("© Copyrighted by the Secretary of the State"):
                continue

            area_match = _CT_AREA_HEADER_RE.match(line)
            if area_match:
                current_family = "civil_procedure" if area_match.group(1).lower() == "civil" else "criminal_procedure"
                continue

            if line.startswith("CHAPTER ") or line == "Sec. Sec." or line.startswith("For previous Histories"):
                continue

            section_match = _CT_SECTION_HEADING_RE.match(line)
            if section_match:
                flush()
                current_number = section_match.group(1).strip()
                current_family = _connecticut_procedure_family_for_section(current_number) or current_family
                current_page = page_number
                heading_part, initial_body_lines = _split_connecticut_heading_and_body(section_match.group(2))
                heading_parts = [heading_part] if heading_part else []
                content_lines = initial_body_lines
                heading_mode = not initial_body_lines
                continue

            if not current_number or not current_family:
                continue

            if heading_mode:
                if heading_parts and heading_parts[-1].endswith("-"):
                    heading_parts.append(line)
                    continue
                if _looks_like_connecticut_body_start(line):
                    heading_mode = False
                    content_lines.append(line)
                else:
                    heading_part, initial_body_lines = _split_connecticut_heading_and_body(line)
                    if heading_part:
                        heading_parts.append(heading_part)
                    if initial_body_lines:
                        heading_mode = False
                        content_lines.extend(initial_body_lines)
                continue

            content_lines.append(line)

    flush()
    return statutes


def _derive_rhode_island_rule_locator(label: str, source_url: str, ordinal: int) -> str:
    normalized_label = re.sub(r"[^A-Za-z0-9]+", "-", str(label or "").strip()).strip("-")
    if normalized_label:
        return normalized_label[:120]
    stem = Path(urlparse(source_url).path).stem
    stem = re.sub(r"[^A-Za-z0-9]+", "-", stem).strip("-")
    if stem:
        return stem[:120]
    return f"RI-RULE-{ordinal}"


def _extract_michigan_rules_from_html(
    html_text: str,
    *,
    chapter_url: str,
    code_name: str,
    procedure_family: str,
    legal_area: str,
) -> List[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    soup = BeautifulSoup(html_text, "html.parser")
    lines: List[str] = []
    for raw_line in soup.get_text("\n", strip=True).splitlines():
        line = " ".join(str(raw_line or "").split())
        if line:
            lines.append(line)

    if not lines:
        return []

    chapter_title = ""
    updated_effective_date = ""
    for line in lines[:40]:
        if not chapter_title and line.lower().startswith("chapter "):
            chapter_title = line
        if not updated_effective_date:
            match = _MI_UPDATED_RE.search(line)
            if match:
                updated_effective_date = " ".join(match.group(1).split())

    statutes: List[NormalizedStatute] = []
    current_number = ""
    current_name = ""
    buffer: List[str] = []

    def flush() -> None:
        nonlocal current_number, current_name, buffer
        if not current_number or not current_name:
            current_number = ""
            current_name = ""
            buffer = []
            return

        full_text = "\n".join(buffer).strip()
        if len(full_text) < 40:
            current_number = ""
            current_name = ""
            buffer = []
            return

        statute = NormalizedStatute(
            state_code="MI",
            state_name=US_STATES["MI"],
            statute_id=f"MCR {current_number}",
            code_name=code_name,
            title_name=chapter_title or code_name,
            chapter_name=chapter_title or code_name,
            section_number=current_number,
            section_name=current_name,
            short_title=current_name,
            full_text=full_text,
            summary=current_name,
            source_url=f"{chapter_url}#rule-{current_number.lower()}",
            official_cite=f"MCR {current_number}",
            legal_area=legal_area,
            structured_data={
                "effective_date": updated_effective_date or None,
                "source_kind": "html_chapter",
            },
        )
        statutes.append(statute)
        current_number = ""
        current_name = ""
        buffer = []

    for line in lines:
        match = _MI_RULE_HEADING_RE.match(line)
        if match:
            flush()
            current_number = match.group(1).strip()
            current_name = match.group(2).strip()
            buffer = [line]
            continue
        if current_number:
            buffer.append(line)

    flush()

    deduped: List[NormalizedStatute] = []
    seen = set()
    for statute in statutes:
        key = (
            str(statute.section_number or "").lower(),
            str(statute.section_name or "").lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(statute)

    return deduped


def _extract_california_rule_links(
    html_text: str,
    *,
    title_url: str,
    procedure_family: str,
    legal_area: str,
) -> tuple[List[Dict[str, str]], Optional[str]]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return [], None

    soup = BeautifulSoup(html_text, "html.parser")
    main = soup.select_one("main")
    if main is None:
        return [], None

    current_as_of = None
    for raw_line in main.get_text("\n", strip=True).splitlines():
        line = " ".join(str(raw_line or "").split())
        if not line:
            continue
        match = _CA_CURRENT_AS_OF_RE.match(line)
        if match:
            current_as_of = match.group(1).strip()
            break

    discovered: List[Dict[str, str]] = []
    seen = set()
    for anchor in main.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        text = " ".join(anchor.get_text(" ", strip=True).split())
        if not href or not text.startswith("Rule "):
            continue
        if not _CA_RULE_LINK_RE.match(href):
            continue

        absolute_url = urljoin(title_url, href)
        key = absolute_url.lower()
        if key in seen:
            continue
        seen.add(key)
        discovered.append(
            {
                "label": text,
                "url": absolute_url,
                "procedure_family": procedure_family,
                "legal_area": legal_area,
            }
        )

    return discovered, current_as_of


def _extract_california_rule_from_html(
    html_text: str,
    *,
    rule_url: str,
    code_name: str,
    title_name: str,
    procedure_family: str,
    legal_area: str,
    current_as_of: Optional[str],
) -> Optional[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None

    soup = BeautifulSoup(html_text, "html.parser")
    main = soup.select_one("main")
    if main is None:
        return None

    lines = [" ".join(str(line or "").split()) for line in main.get_text("\n", strip=True).splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return None

    start_index = None
    section_number = ""
    section_name = ""
    for index, line in enumerate(lines):
        match = _CA_RULE_HEADING_RE.match(line)
        if match:
            start_index = index
            section_number = match.group(1).strip()
            section_name = match.group(2).strip()
            break

    if start_index is None or not section_number or not section_name:
        return None

    full_text = "\n".join(lines[start_index:]).strip()
    if len(full_text) < 80:
        return None

    return NormalizedStatute(
        state_code="CA",
        state_name=US_STATES["CA"],
        statute_id=f"Cal. Rules of Court, rule {section_number}",
        code_name=code_name,
        title_name=title_name,
        chapter_name=title_name,
        section_number=section_number,
        section_name=section_name,
        short_title=section_name,
        full_text=full_text,
        summary=section_name,
        source_url=rule_url,
        official_cite=f"Cal. Rules of Court, rule {section_number}",
        legal_area=legal_area,
        structured_data={
            "current_as_of": current_as_of or None,
            "source_kind": "html_rule_page",
            "procedure_family": procedure_family,
        },
    )


async def _fetch_html_with_direct_fallback(
    fetcher: BaseStateScraper,
    url: str,
    *,
    validator,
    timeout_seconds: int = 120,
) -> str:
    payload = await fetcher._fetch_page_content_with_archival_fallback(url, timeout_seconds=timeout_seconds)
    html = payload.decode("utf-8", errors="replace") if payload else ""
    if validator(html):
        return html

    try:
        response = requests.get(
            url,
            timeout=timeout_seconds,
            headers={"User-Agent": _DIRECT_FETCH_USER_AGENT},
        )
    except Exception as exc:
        fetcher._record_fetch_event(provider="direct", success=False, error=str(exc))
        response = None

    if response is not None and response.status_code == 200 and response.text:
        direct_html = response.text
        if validator(direct_html):
            fetcher._record_fetch_event(provider="direct", success=True)
            await fetcher._store_page_bytes_in_ipfs_cache(
                url=url,
                payload=response.content,
                provider="direct",
            )
            return direct_html
        fetcher._record_fetch_event(provider="direct", success=False, error="validator_failed")
    elif response is not None:
        fetcher._record_fetch_event(provider="direct", success=False, error=f"http {response.status_code}")

    curl_bytes, curl_error = _fetch_url_via_curl(url, timeout_seconds=timeout_seconds)
    if curl_bytes:
        curl_html = curl_bytes.decode("utf-8", errors="replace")
        if validator(curl_html):
            fetcher._record_fetch_event(provider="curl", success=True)
            await fetcher._store_page_bytes_in_ipfs_cache(
                url=url,
                payload=curl_bytes,
                provider="curl",
            )
            return curl_html
        fetcher._record_fetch_event(provider="curl", success=False, error="validator_failed")
    elif curl_error:
        fetcher._record_fetch_event(provider="curl", success=False, error=curl_error)

    return html


async def _fetch_pdf_bytes_with_direct_fallback(
    fetcher: BaseStateScraper,
    url: str,
    *,
    timeout_seconds: int = 180,
) -> bytes:
    payload = await fetcher._fetch_page_content_with_archival_fallback(url, timeout_seconds=timeout_seconds)
    if isinstance(payload, (bytes, bytearray)) and bytes(payload).startswith(b"%PDF-"):
        return bytes(payload)

    try:
        response = requests.get(
            url,
            timeout=timeout_seconds,
            headers={"User-Agent": _DIRECT_FETCH_USER_AGENT},
        )
    except Exception as exc:
        fetcher._record_fetch_event(provider="direct", success=False, error=str(exc))
        response = None

    if response is not None and response.status_code == 200 and response.content:
        direct_bytes = bytes(response.content)
        if direct_bytes.startswith(b"%PDF-"):
            fetcher._record_fetch_event(provider="direct", success=True)
            await fetcher._store_page_bytes_in_ipfs_cache(
                url=url,
                payload=response.content,
                provider="direct",
            )
            return direct_bytes
        fetcher._record_fetch_event(provider="direct", success=False, error="not_pdf")
    elif response is not None:
        fetcher._record_fetch_event(provider="direct", success=False, error=f"http {response.status_code}")

    curl_bytes, curl_error = _fetch_url_via_curl(url, timeout_seconds=timeout_seconds)
    if curl_bytes and curl_bytes.startswith(b"%PDF-"):
        fetcher._record_fetch_event(provider="curl", success=True)
        await fetcher._store_page_bytes_in_ipfs_cache(
            url=url,
            payload=curl_bytes,
            provider="curl",
        )
        return curl_bytes
    if curl_bytes:
        fetcher._record_fetch_event(provider="curl", success=False, error="not_pdf")
    elif curl_error:
        fetcher._record_fetch_event(provider="curl", success=False, error=curl_error)
    return b""


async def _fetch_json_with_direct_fallback(
    fetcher: BaseStateScraper,
    url: str,
    *,
    timeout_seconds: int = 120,
) -> Any:
    prefer_direct = "/njcourts_rules_of_court/" in url
    if not prefer_direct:
        payload = await fetcher._fetch_page_content_with_archival_fallback(url, timeout_seconds=timeout_seconds)
        if payload:
            try:
                return json.loads(payload.decode("utf-8", errors="replace"))
            except Exception:
                pass

    try:
        response = requests.get(
            url,
            timeout=timeout_seconds,
            headers={"User-Agent": _DIRECT_FETCH_USER_AGENT, "Accept": "application/json"},
        )
    except Exception as exc:
        fetcher._record_fetch_event(provider="direct", success=False, error=str(exc))
        response = None

    if response is not None and response.status_code == 200 and response.text:
        try:
            parsed = response.json()
        except Exception:
            fetcher._record_fetch_event(provider="direct", success=False, error="invalid_json")
        else:
            fetcher._record_fetch_event(provider="direct", success=True)
            await fetcher._store_page_bytes_in_ipfs_cache(
                url=url,
                payload=response.content,
                provider="direct",
            )
            return parsed
    elif response is not None:
        fetcher._record_fetch_event(provider="direct", success=False, error=f"http {response.status_code}")

    curl_bytes, curl_error = _fetch_url_via_curl(
        url,
        timeout_seconds=timeout_seconds,
        accept="application/json",
    )
    if curl_bytes:
        try:
            parsed = json.loads(curl_bytes.decode("utf-8", errors="replace"))
        except Exception:
            fetcher._record_fetch_event(provider="curl", success=False, error="invalid_json")
        else:
            fetcher._record_fetch_event(provider="curl", success=True)
            await fetcher._store_page_bytes_in_ipfs_cache(
                url=url,
                payload=curl_bytes,
                provider="curl",
            )
            return parsed
    elif curl_error:
        fetcher._record_fetch_event(provider="curl", success=False, error=curl_error)
    return None


def _fetch_url_via_curl(
    url: str,
    *,
    timeout_seconds: int,
    accept: Optional[str] = None,
) -> tuple[bytes, Optional[str]]:
    curl_path = shutil.which("curl")
    if not curl_path:
        return b"", "curl_missing"

    command = [
        curl_path,
        "--silent",
        "--show-error",
        "--location",
        "--fail",
        "--compressed",
        "--max-time",
        str(int(timeout_seconds)),
        "--user-agent",
        _DIRECT_FETCH_USER_AGENT,
    ]
    if accept:
        command.extend(["--header", f"Accept: {accept}"])
    command.append(url)

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            check=False,
            timeout=max(int(timeout_seconds) + 5, 5),
        )
    except subprocess.TimeoutExpired:
        return b"", "curl_timeout"
    except Exception as exc:
        return b"", str(exc)

    if result.returncode != 0 or not result.stdout:
        error_text = (result.stderr or b"").decode("utf-8", errors="replace").strip()
        return b"", error_text or f"curl_exit_{result.returncode}"
    return bytes(result.stdout), None


def _extract_ohio_rules_from_text(
    text: str,
    *,
    source_url: str,
    title_name: str,
    procedure_family: str,
    legal_area: str,
    effective_date: Optional[str],
) -> List[NormalizedStatute]:
    normalized_text = " ".join(str(text or "").replace("\r", " ").replace("\n", " ").split())
    body_start = normalized_text.find("TITLE I.")
    if body_start != -1:
        normalized_text = normalized_text[body_start:]
    statutes: List[NormalizedStatute] = []
    seen = set()
    for match in _OH_RULE_BLOCK_RE.finditer(normalized_text):
        section_number = str(match.group(1) or "").strip()
        body = str(match.group(2) or "").strip()
        if not section_number or not body:
            continue
        full_text = f"RULE {section_number}. {body}".strip()
        if len(full_text) < 80:
            continue

        section_name = body
        for marker in [". (", ". Effective Date", ". Staff Note", ". "]:
            marker_index = section_name.find(marker)
            if marker_index != -1:
                section_name = section_name[:marker_index]
                break
        section_name = section_name.strip().rstrip(".")
        if not section_name:
            continue

        key = (section_number.lower(), section_name.lower())
        if key in seen:
            continue
        seen.add(key)

        statutes.append(
            NormalizedStatute(
                state_code="OH",
                state_name=US_STATES["OH"],
                statute_id=f"{title_name} Rule {section_number}",
                code_name=title_name,
                title_name=title_name,
                chapter_name=title_name,
                section_number=section_number,
                section_name=section_name,
                short_title=section_name,
                full_text=full_text,
                summary=section_name,
                source_url=f"{source_url}#rule-{section_number.lower()}",
                official_cite=f"{title_name} Rule {section_number}",
                legal_area=legal_area,
                structured_data={
                    "effective_date": effective_date or None,
                    "source_kind": "pdf_rule_book",
                    "procedure_family": procedure_family,
                },
            )
        )

    return statutes


def _normalize_maryland_text(text: str) -> str:
    return (
        str(text or "")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u2011", "-")
        .replace("\xa0", " ")
    )


def _extract_maryland_chapter_links(
    html_text: str,
    *,
    page_url: str,
    procedure_family: str,
    legal_area: str,
) -> List[Dict[str, str]]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    soup = BeautifulSoup(html_text or "", "html.parser")
    discovered: List[Dict[str, str]] = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        label = " ".join(_normalize_maryland_text(anchor.get_text(" ", strip=True)).split())
        if not href or not label.startswith("Chapter "):
            continue
        match = _MD_CHAPTER_LINK_RE.match(label)
        if not match:
            continue
        absolute_url = urljoin(page_url, href)
        key = absolute_url.lower()
        if key in seen:
            continue
        seen.add(key)
        discovered.append(
            {
                "chapter_number": match.group(1).strip(),
                "chapter_name": match.group(2).strip().rstrip("."),
                "url": absolute_url,
                "procedure_family": procedure_family,
                "legal_area": legal_area,
            }
        )

    return discovered


def _extract_maryland_rule_links(
    html_text: str,
    *,
    page_url: str,
    title_name: str,
    chapter_name: str,
    procedure_family: str,
    legal_area: str,
) -> List[Dict[str, str]]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    soup = BeautifulSoup(html_text or "", "html.parser")
    discovered: List[Dict[str, str]] = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        label = " ".join(_normalize_maryland_text(anchor.get_text(" ", strip=True)).split())
        if not href or not label.startswith("Rule "):
            continue
        match = _MD_RULE_LINK_RE.match(label)
        if not match:
            continue
        absolute_url = urljoin(page_url, href)
        key = absolute_url.lower()
        if key in seen:
            continue
        seen.add(key)
        discovered.append(
            {
                "section_number": match.group(1).strip(),
                "section_name": match.group(2).strip().rstrip("."),
                "url": absolute_url,
                "title_name": title_name,
                "chapter_name": chapter_name,
                "procedure_family": procedure_family,
                "legal_area": legal_area,
            }
        )

    return discovered


def _extract_maryland_rule_from_html(
    html_text: str,
    *,
    rule_url: str,
    title_name: str,
    chapter_name: str,
    procedure_family: str,
    legal_area: str,
) -> Optional[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None

    soup = BeautifulSoup(html_text or "", "html.parser")
    document = soup.select_one("#co_document") or soup.select_one(".co_document")
    if document is None:
        return None

    lines = [
        " ".join(_normalize_maryland_text(line).split())
        for line in document.get_text("\n", strip=True).splitlines()
    ]
    lines = [line for line in lines if line]
    if not lines:
        return None

    heading_index = next((idx for idx, line in enumerate(lines) if line.startswith("RULE ")), None)
    if heading_index is None:
        return None

    heading = lines[heading_index]
    heading_match = re.match(r"^RULE\s+([234]-\d+[A-Za-z]?(?:\.\d+)?)\.\s+(.+)$", heading, re.IGNORECASE)
    if not heading_match:
        return None

    section_number = heading_match.group(1).strip()
    section_name = heading_match.group(2).strip().rstrip(".")

    content_lines: List[str] = [heading]
    for line in lines[heading_index + 1 :]:
        if line.startswith("MD Rules, Rule "):
            break
        if line.startswith("Current with amendments received through "):
            break
        if line == "End of Document":
            break
        content_lines.append(line)

    full_text = "\n".join(content_lines).strip()
    if len(full_text) < 40:
        return None

    effective_matches = [
        " ".join(match.group(1).split())
        for match in _MD_EFFECTIVE_DATE_RE.finditer("\n".join(lines[: heading_index + 5]))
        if match.group(1)
    ]
    current_as_of_matches = [
        " ".join(match.group(1).split())
        for match in _MD_CURRENT_AS_OF_RE.finditer("\n".join(lines))
        if match.group(1)
    ]

    return NormalizedStatute(
        state_code="MD",
        state_name=US_STATES["MD"],
        statute_id=f"Md. Rule {section_number}",
        code_name="Maryland Rules",
        title_name=title_name,
        chapter_name=chapter_name,
        section_number=section_number,
        section_name=section_name,
        short_title=section_name,
        full_text=full_text,
        summary=section_name,
        source_url=f"{rule_url}#rule-{section_number.lower()}",
        official_cite=f"Md. Rule {section_number}",
        legal_area=legal_area,
        structured_data={
            "effective_date": effective_matches[-1] if effective_matches else None,
            "current_as_of": current_as_of_matches[-1] if current_as_of_matches else None,
            "source_kind": "maryland_public_westlaw_rule_page",
            "procedure_family": procedure_family,
        },
    )


def _extract_south_carolina_rule_links(
    html_text: str,
    *,
    page_url: str,
    procedure_family: str,
    legal_area: str,
    official_cite_prefix: str,
) -> List[Dict[str, str]]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    page_path = urlparse(page_url).path.rstrip("/")
    soup = BeautifulSoup(html_text or "", "html.parser")
    discovered: List[Dict[str, str]] = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        label = " ".join(anchor.get_text(" ", strip=True).split())
        if not href or not label:
            continue
        absolute_url = urljoin(page_url, href)
        path = urlparse(absolute_url).path.rstrip("/")
        if not path.startswith(page_path + "/rule-"):
            continue
        match = _SC_RULE_LINK_RE.match(label)
        if not match:
            continue
        key = absolute_url.lower()
        if key in seen:
            continue
        seen.add(key)
        discovered.append(
            {
                "section_number": match.group(1).strip(),
                "section_name": match.group(2).strip().rstrip("."),
                "url": absolute_url,
                "procedure_family": procedure_family,
                "legal_area": legal_area,
                "official_cite_prefix": official_cite_prefix,
            }
        )
    return discovered


def _extract_south_carolina_rule_from_html(
    html_text: str,
    *,
    rule_url: str,
    title_name: str,
    procedure_family: str,
    legal_area: str,
    official_cite_prefix: str,
) -> Optional[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None

    soup = BeautifulSoup(html_text or "", "html.parser")
    content_section = None
    for section in soup.select("main#main-content section.content-section"):
        text = " ".join(section.get_text(" ", strip=True).split())
        if "Back To Court Rules" in text and ("Prev" in text or "Next" in text):
            content_section = section
    if content_section is None:
        return None

    container = content_section.select_one("div.container")
    if container is None:
        return None

    paragraphs = container.find_all("p")
    if not paragraphs:
        return None

    heading_text = ""
    body_lines: List[str] = []
    for paragraph in paragraphs:
        text = " ".join(paragraph.get_text(" ", strip=True).split())
        if not text:
            continue
        if text in {"Back To Court Rules", "Prev", "Next"}:
            continue
        if text.startswith("RULE "):
            heading_text = text
            body_lines.append(text)
            continue
        if heading_text:
            body_lines.append(text)

    if not heading_text or len(body_lines) < 2:
        return None

    heading_match = re.match(r"^RULE\s+(\d+(?:\.\d+)?)\s+(.+)$", heading_text, re.IGNORECASE)
    if not heading_match:
        return None

    section_number = heading_match.group(1).strip()
    section_name = heading_match.group(2).strip().rstrip(".")
    full_text = "\n".join(body_lines).strip()
    if len(full_text) < 40:
        return None

    return NormalizedStatute(
        state_code="SC",
        state_name=US_STATES["SC"],
        statute_id=f"{official_cite_prefix} Rule {section_number}",
        code_name=title_name,
        title_name=title_name,
        chapter_name=title_name,
        section_number=section_number,
        section_name=section_name,
        short_title=section_name,
        full_text=full_text,
        summary=section_name,
        source_url=f"{rule_url}#rule-{section_number}",
        official_cite=f"{official_cite_prefix} Rule {section_number}",
        legal_area=legal_area,
        structured_data={
            "source_kind": "south_carolina_judicial_branch_rule_page",
            "procedure_family": procedure_family,
        },
    )


def _extract_alaska_rules_from_text(
    text: str,
    *,
    source_url: str,
    title_name: str,
    procedure_family: str,
    legal_area: str,
    official_cite_prefix: str,
    start_marker: str,
) -> List[NormalizedStatute]:
    normalized = str(text or "").replace("\xa0", " ")
    start_index = normalized.rfind(start_marker)
    if "Table of Contents" in normalized:
        rule_one_matches = list(re.finditer(r"Rule\s+1(?:\s|\.)", normalized, re.IGNORECASE))
        if len(rule_one_matches) >= 2:
            start_index = rule_one_matches[1].start()
    if start_index >= 0:
        normalized = normalized[start_index:]

    statutes: List[NormalizedStatute] = []
    seen = set()
    for match in _AK_RULE_BLOCK_RE.finditer(normalized):
        section_number = " ".join(match.group(1).split())
        block = " ".join(match.group(2).split())
        if not section_number or not block:
            continue
        pieces = block.split(". ", 1)
        section_name = pieces[0].strip().rstrip(".")
        if not section_name:
            continue
        full_text = f"Rule {section_number}. {block}".strip()
        if len(full_text) < 50:
            continue
        key = (section_number.lower(), section_name.lower())
        if key in seen:
            continue
        seen.add(key)
        statutes.append(
            NormalizedStatute(
                state_code="AK",
                state_name=US_STATES["AK"],
                statute_id=f"{official_cite_prefix} {section_number}",
                code_name=title_name,
                title_name=title_name,
                chapter_name=title_name,
                section_number=section_number,
                section_name=section_name,
                short_title=section_name,
                full_text=full_text,
                summary=section_name,
                source_url=f"{source_url}#rule-{section_number}",
                official_cite=f"{official_cite_prefix} {section_number}",
                legal_area=legal_area,
                structured_data={
                    "source_kind": "alaska_court_rules_pdf",
                    "procedure_family": procedure_family,
                },
            )
        )
    return statutes


def _extract_alaska_rules_from_page_texts(
    page_texts: List[str],
    *,
    source_url: str,
    title_name: str,
    procedure_family: str,
    legal_area: str,
    official_cite_prefix: str,
) -> List[NormalizedStatute]:
    body_start = 0
    for index, page_text in enumerate(page_texts):
        normalized_page = " ".join(str(page_text or "").split())
        if "Table of Contents" in normalized_page:
            continue
        if "Rule 1." in normalized_page and ("Scope of Rules" in normalized_page or "Scope." in normalized_page):
            body_start = index
            break

    heading_re = re.compile(r"^(?:Rule\s+)?(\d+(?:\.\d+)?)\.?\s+(.+)$")
    skip_exact = {
        "ALASKA COURT RULES",
        "RULES OF CIVIL PROCEDURE",
        "RULES OF CRIMINAL PROCEDURE",
    }
    statutes: List[NormalizedStatute] = []
    seen = set()
    current_number = ""
    current_name = ""
    buffer: List[str] = []

    def flush() -> None:
        nonlocal current_number, current_name, buffer
        if not current_number or not current_name:
            current_number = ""
            current_name = ""
            buffer = []
            return

        full_text = "\n".join(buffer).strip()
        if len(full_text) < 50:
            current_number = ""
            current_name = ""
            buffer = []
            return

        key = (current_number.lower(), current_name.lower())
        if key not in seen:
            seen.add(key)
            statutes.append(
                NormalizedStatute(
                    state_code="AK",
                    state_name=US_STATES["AK"],
                    statute_id=f"{official_cite_prefix} {current_number}",
                    code_name=title_name,
                    title_name=title_name,
                    chapter_name=title_name,
                    section_number=current_number,
                    section_name=current_name,
                    short_title=current_name,
                    full_text=full_text,
                    summary=current_name,
                    source_url=f"{source_url}#rule-{current_number}",
                    official_cite=f"{official_cite_prefix} {current_number}",
                    legal_area=legal_area,
                    structured_data={
                        "source_kind": "alaska_court_rules_pdf",
                        "procedure_family": procedure_family,
                    },
                )
            )

        current_number = ""
        current_name = ""
        buffer = []

    for page_text in page_texts[body_start:]:
        for raw_line in str(page_text or "").splitlines():
            line = " ".join(raw_line.split())
            if not line or line in skip_exact:
                continue
            if line.isdigit() or line in {"CR", "CrR"} or line.startswith("PART "):
                continue
            if line.startswith("("):
                if current_number:
                    buffer.append(line)
                continue

            match = heading_re.match(line)
            if match and len(line) <= 140 and not line.startswith("RuleComments@"):
                heading_number = match.group(1).strip()
                heading_name = match.group(2).strip().rstrip(".")
                if (
                    heading_name
                    and not heading_name.startswith("(")
                    and "ALASKA COURT RULES" not in heading_name
                    and heading_name not in skip_exact
                    and not heading_name.startswith("SLA ")
                    and (
                        line.startswith("Rule ")
                        or (
                            heading_name[0].isupper()
                            and not re.match(r"^\d{4}\b", heading_name)
                        )
                    )
                ):
                    flush()
                    current_number = heading_number
                    current_name = heading_name
                    buffer = [f"Rule {current_number}. {current_name}"]
                    continue

            if current_number:
                buffer.append(line)

    flush()
    return statutes


def _extract_hawaii_rules_from_html(
    html_text: str,
    *,
    source_url: str,
    title_name: str,
    procedure_family: str,
    legal_area: str,
    official_cite_prefix: str,
    effective_date: Optional[str],
) -> List[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    soup = BeautifulSoup(html_text or "", "html.parser")
    lines = [" ".join(line.split()) for line in soup.get_text("\n", strip=True).splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return []

    heading_indexes = [index for index, line in enumerate(lines) if _HI_RULE_HEADING_RE.match(line)]
    if not heading_indexes:
        return []

    body_start = heading_indexes[0]
    if "Table of Contents" in lines:
        rule_one_indexes = [
            index
            for index in heading_indexes
            if re.match(r"^Rule\s+1\.\s*$", lines[index])
        ]
        if len(rule_one_indexes) >= 2:
            body_start = rule_one_indexes[1]
        else:
            for heading_index in heading_indexes:
                context_lines = lines[max(0, heading_index - 3) : heading_index]
                if any(re.match(r"^[IVXLC]+\.\s", value) for value in context_lines):
                    body_start = heading_index
                    break
            else:
                if len(heading_indexes) >= 2:
                    body_start = heading_indexes[1]

    def _is_heading_fragment(value: str) -> bool:
        if not value or value.startswith("("):
            return False
        alpha_chars = [char for char in value if char.isalpha()]
        if not alpha_chars:
            return False
        return "".join(alpha_chars) == "".join(alpha_chars).upper()

    statutes: List[NormalizedStatute] = []
    seen = set()
    current_number = ""
    current_name = ""
    buffer: List[str] = []

    def flush() -> None:
        nonlocal current_number, current_name, buffer
        if not current_number or not current_name:
            current_number = ""
            current_name = ""
            buffer = []
            return

        full_text = "\n".join(buffer).strip()
        if len(full_text) < 50:
            current_number = ""
            current_name = ""
            buffer = []
            return

        key = (current_number.lower(), current_name.lower())
        if key not in seen:
            seen.add(key)
            statutes.append(
                NormalizedStatute(
                    state_code="HI",
                    state_name=US_STATES["HI"],
                    statute_id=f"{official_cite_prefix} {current_number}",
                    code_name=title_name,
                    title_name=title_name,
                    chapter_name=title_name,
                    section_number=current_number,
                    section_name=current_name,
                    short_title=current_name,
                    full_text=full_text,
                    summary=current_name,
                    source_url=f"{source_url}#rule-{current_number}",
                    official_cite=f"{official_cite_prefix} {current_number}",
                    legal_area=legal_area,
                    structured_data={
                        "effective_date": effective_date,
                        "source_kind": "hawaii_judiciary_rule_html",
                        "procedure_family": procedure_family,
                    },
                )
            )

        current_number = ""
        current_name = ""
        buffer = []

    index = body_start
    while index < len(lines):
        line = lines[index]
        heading_match = _HI_RULE_HEADING_RE.match(line)
        if heading_match:
            flush()
            current_number = heading_match.group(1).strip()
            name_parts: List[str] = []
            inline_name = (heading_match.group(2) or heading_match.group(3) or "").strip()
            if inline_name:
                inline_name_clean = inline_name.rstrip(".").strip()
                if inline_name_clean and not _is_heading_fragment(inline_name_clean):
                    current_number = ""
                    index += 1
                    continue
                name_parts.append(inline_name)
                if inline_name.endswith("."):
                    current_name = " ".join(part.strip().rstrip(".") for part in name_parts if part.strip()).strip()
                    if current_name:
                        buffer = [f"Rule {current_number}. {current_name}"]
                        index += 1
                        continue

            lookahead = index + 1
            while lookahead < len(lines):
                next_line = lines[lookahead]
                if _HI_RULE_HEADING_RE.match(next_line) or next_line.startswith("("):
                    break
                if not _is_heading_fragment(next_line):
                    break
                name_parts.append(next_line)
                lookahead += 1
                if next_line.endswith("."):
                    break

            current_name = " ".join(part.strip().rstrip(".") for part in name_parts if part.strip()).strip()
            current_name = re.split(r"\s+[IVXLC]+\.\s+", current_name, maxsplit=1)[0].strip()
            if not current_name:
                current_number = ""
                index += 1
                continue

            buffer = [f"Rule {current_number}. {current_name}"]
            index = lookahead
            continue

        if current_number:
            if re.match(r"^[IVXLC]+\.\s", line):
                flush()
                index += 1
                continue
            buffer.append(line)

        index += 1

    flush()
    return statutes


def _extract_nebraska_rule_links(
    html_text: str,
    *,
    page_url: str,
    procedure_family: str,
    legal_area: str,
    official_cite_prefix: str,
) -> List[Dict[str, str]]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    soup = BeautifulSoup(html_text or "", "html.parser")
    content = soup.select_one("article.node .node__content") or soup

    discovered: List[Dict[str, str]] = []
    seen = set()
    for anchor in content.select("a[href]"):
        href = str(anchor.get("href") or "").strip()
        label = " ".join(anchor.get_text(" ", strip=True).split())
        if not href or not label.startswith("§ "):
            continue
        match = _NE_SECTION_LINK_RE.match(label)
        if not match:
            continue
        absolute_url = urljoin(page_url, href)
        key = absolute_url.lower()
        if key in seen:
            continue
        seen.add(key)
        discovered.append(
            {
                "section_number": match.group(1).strip(),
                "section_name": match.group(2).strip().rstrip("."),
                "url": absolute_url,
                "procedure_family": procedure_family,
                "legal_area": legal_area,
                "official_cite_prefix": official_cite_prefix,
            }
        )

    return discovered


def _extract_utah_rule_links(
    html_text: str,
    *,
    page_url: str,
    procedure_family: str,
    legal_area: str,
    official_cite_prefix: str,
    type_code: str,
) -> List[Dict[str, str]]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    soup = BeautifulSoup(html_text or "", "html.parser")
    discovered: List[Dict[str, str]] = []
    seen = set()

    for anchor in soup.find_all("a", href=True):
        label = " ".join(anchor.get_text(" ", strip=True).split())
        href = str(anchor.get("href") or "").strip()
        if not label.startswith("Rule ") or not href:
            continue
        match = _UT_RULE_LINK_RE.match(label)
        if not match:
            continue
        absolute_url = urljoin(page_url, href)
        parsed = urlparse(absolute_url)
        if parsed.path.rstrip("/").lower() != "/rules/view.php":
            continue
        query = parsed.query.lower()
        if f"type={type_code.lower()}" not in query or "rule=" not in query:
            continue

        section_number = match.group(1).strip()
        section_name = match.group(2).strip().rstrip(".")
        key = absolute_url.lower()
        if key in seen:
            continue
        seen.add(key)
        discovered.append(
            {
                "section_number": section_number,
                "section_name": section_name,
                "url": absolute_url,
                "procedure_family": procedure_family,
                "legal_area": legal_area,
                "official_cite_prefix": official_cite_prefix,
            }
        )

    return discovered


def _extract_utah_rule_from_html(
    html_text: str,
    *,
    rule_url: str,
    title_name: str,
    procedure_family: str,
    legal_area: str,
    official_cite_prefix: str,
) -> Optional[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None

    soup = BeautifulSoup(html_text or "", "html.parser")
    lines = [" ".join(line.split()) for line in soup.get_text("\n", strip=True).splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return None

    if any("This Rule has been repealed." in line for line in lines):
        return None

    heading_index = next(
        (index for index, line in enumerate(lines) if _UT_RULE_PAGE_HEADING_RE.match(line)),
        None,
    )
    if heading_index is None:
        return None

    heading_match = _UT_RULE_PAGE_HEADING_RE.match(lines[heading_index])
    if heading_match is None:
        return None

    section_number = heading_match.group(1).strip()
    section_name = heading_match.group(2).strip().rstrip(".")
    effective_date = None
    body_lines: List[str] = [lines[heading_index]]

    for line in lines[heading_index + 1 :]:
        effective_match = _UT_EFFECTIVE_DATE_RE.match(line)
        if effective_match:
            effective_date = effective_match.group(1).strip()
            body_lines.append(line)
            continue
        if line.startswith("Rule printed on "):
            continue
        if line in {
            "Back to Rules of Civil Procedure",
            "Back to Rules of Criminal Procedure",
            "Next Rule >>",
            "<< Previous Rule",
            "Empty Table",
            "Close",
            "×",
        }:
            continue
        if line == "Utah Courts":
            continue
        if line == "https://www.utcourts.gov/rules" or line == "for current rules.":
            continue
        if line.startswith("© "):
            break
        body_lines.append(line)

    full_text = "\n".join(body_lines).strip()
    if len(full_text) < 60:
        return None

    return NormalizedStatute(
        state_code="UT",
        state_name=US_STATES["UT"],
        statute_id=f"{official_cite_prefix} {section_number}",
        code_name=title_name,
        title_name=title_name,
        chapter_name=title_name,
        section_number=section_number,
        section_name=section_name,
        short_title=section_name,
        full_text=full_text,
        summary=section_name,
        source_url=f"{rule_url}#rule-{section_number.lower()}",
        official_cite=f"{official_cite_prefix} {section_number}",
        legal_area=legal_area,
        structured_data={
            "effective_date": effective_date,
            "source_kind": "utah_courts_rule_page",
            "procedure_family": procedure_family,
        },
    )


def _extract_new_mexico_rules_from_page_texts(
    page_texts: List[tuple[int, str]],
    *,
    source_url: str,
    title_name: str,
    procedure_family: str,
    legal_area: str,
    official_cite_prefix: str,
    first_rule_number: str,
    max_rules: Optional[int] = None,
) -> List[NormalizedStatute]:
    statutes: List[NormalizedStatute] = []
    seen = set()
    current_number = ""
    current_name = ""
    current_page = 0
    current_effective_date: Optional[str] = None
    body_lines: List[str] = []
    start_found = False
    capture_body = True
    stop_markers = (
        "ANNOTATIONS",
        "Committee commentary.",
        "Committee commentary. —",
        "Cross references.",
        "Cross references. —",
        "Compiler's notes.",
        "Compiler's notes. —",
        "Law reviews.",
        "Am. Jur. 2d, A.L.R. and C.J.S. references.",
    )

    def flush() -> None:
        nonlocal current_number, current_name, current_page, current_effective_date, body_lines, capture_body
        if not current_number or not current_name:
            current_number = ""
            current_name = ""
            current_page = 0
            current_effective_date = None
            body_lines = []
            capture_body = True
            return

        full_text = "\n".join(line for line in body_lines if line).strip()
        normalized_text = " ".join(full_text.split())
        effective_matches = _NM_EFFECTIVE_DATE_RE.findall(normalized_text)
        if effective_matches:
            current_effective_date = " ".join(effective_matches[-1].split())
        if len(full_text) < 40:
            current_number = ""
            current_name = ""
            current_page = 0
            current_effective_date = None
            body_lines = []
            capture_body = True
            return

        key = (current_number.lower(), current_name.lower())
        if key not in seen:
            seen.add(key)
            statutes.append(
                NormalizedStatute(
                    state_code="NM",
                    state_name=US_STATES["NM"],
                    statute_id=f"{official_cite_prefix} {current_number} NMRA",
                    code_name=title_name,
                    title_name=title_name,
                    chapter_name=title_name,
                    section_number=current_number,
                    section_name=current_name,
                    short_title=current_name,
                    full_text=full_text,
                    summary=current_name,
                    source_url=f"{source_url}#rule-{current_number.lower()}",
                    official_cite=f"{official_cite_prefix} {current_number} NMRA",
                    legal_area=legal_area,
                    structured_data={
                        "effective_date": current_effective_date,
                        "source_kind": "new_mexico_court_rules_pdf",
                        "procedure_family": procedure_family,
                        "page_start": current_page or None,
                    },
                )
            )

        current_number = ""
        current_name = ""
        current_page = 0
        current_effective_date = None
        body_lines = []
        capture_body = True

    for page_number, page_text in page_texts:
        for raw_line in str(page_text or "").splitlines():
            line = " ".join(raw_line.replace("\x00", " ").split())
            if not line or line.isdigit():
                continue

            heading_match = _NM_RULE_HEADING_RE.match(line)
            if heading_match:
                heading_number = heading_match.group(1).strip()
                if not start_found:
                    if heading_number != first_rule_number:
                        continue
                    start_found = True

                flush()
                current_number = heading_number
                current_name = heading_match.group(2).strip().rstrip(".")
                if current_name.lower() == "withdrawn":
                    current_number = ""
                    current_name = ""
                    current_page = 0
                    body_lines = []
                    capture_body = True
                    continue
                current_page = page_number
                current_effective_date = None
                body_lines = [f"{current_number}. {current_name}."]
                capture_body = True
                continue

            if not start_found or not current_number:
                continue

            if any(line.startswith(marker) for marker in stop_markers):
                capture_body = False
                continue

            if capture_body:
                if (
                    len(body_lines) == 1
                    and (
                        current_name.lower().endswith(("by", "and", "or", "of", "for", "to", "with", "under", "in"))
                        or line[:1].islower()
                    )
                    and not re.match(r"^(?:[A-Z]\.|[A-Z]\)|\([A-Za-z0-9]+\)|ARTICLE\b|PART\b)", line)
                ):
                    current_name = f"{current_name} {line.rstrip('.')}".strip()
                    body_lines[0] = f"{current_number}. {current_name}."
                    continue
                effective_matches = _NM_EFFECTIVE_DATE_RE.findall(line)
                if effective_matches:
                    current_effective_date = " ".join(effective_matches[-1].split())
                body_lines.append(line)

        if max_rules is not None and len(statutes) >= max_rules:
            break

    flush()
    if max_rules is not None and max_rules > 0:
        return statutes[:max_rules]
    return statutes


def _extract_west_virginia_civil_rules_from_page_texts(
    page_texts: List[tuple[int, str]],
    *,
    source_url: str,
    title_name: str,
    procedure_family: str,
    legal_area: str,
    official_cite_prefix: str,
) -> List[NormalizedStatute]:
    statutes: List[NormalizedStatute] = []
    seen = set()
    current_number = ""
    current_name = ""
    current_page = 0
    current_effective_date: Optional[str] = None
    body_lines: List[str] = []
    body_started = False

    def flush() -> None:
        nonlocal current_number, current_name, current_page, current_effective_date, body_lines
        if not current_number or not current_name:
            current_number = ""
            current_name = ""
            current_page = 0
            current_effective_date = None
            body_lines = []
            return

        full_text = "\n".join(line for line in body_lines if line).strip()
        if len(full_text) >= 40:
            key = (current_number.lower(), current_name.lower())
            if key not in seen:
                seen.add(key)
                statutes.append(
                    NormalizedStatute(
                        state_code="WV",
                        state_name=US_STATES["WV"],
                        statute_id=f"{official_cite_prefix} {current_number}",
                        code_name=title_name,
                        title_name=title_name,
                        chapter_name=title_name,
                        section_number=current_number,
                        section_name=current_name,
                        short_title=current_name,
                        full_text=full_text,
                        summary=current_name,
                        source_url=f"{source_url}#rule-{current_number}",
                        official_cite=f"{official_cite_prefix} {current_number}",
                        legal_area=legal_area,
                        structured_data={
                            "effective_date": current_effective_date,
                            "source_kind": "west_virginia_civil_rules_pdf",
                            "procedure_family": procedure_family,
                            "page_start": current_page or None,
                        },
                    )
                )

        current_number = ""
        current_name = ""
        current_page = 0
        current_effective_date = None
        body_lines = []

    for page_number, page_text in page_texts:
        normalized_page = " ".join(str(page_text or "").split())
        if not body_started:
            if "Rule 1. Scope and purpose." in normalized_page:
                body_started = True
            else:
                continue

        for raw_line in str(page_text or "").splitlines():
            line = " ".join(raw_line.replace("\x00", " ").split())
            if not line or line.isdigit():
                continue
            if line.startswith("West Virginia Rules of Civil Procedure") or line == "Table of Contents":
                continue
            if re.match(r"^[IVXLC]+\.\s", line):
                continue

            heading_match = _WV_RULE_HEADING_RE.match(line)
            if heading_match:
                flush()
                current_number = heading_match.group(1).strip()
                current_name = heading_match.group(2).strip().rstrip(".")
                current_page = page_number
                body_lines = [f"Rule {current_number}. {current_name}."]
                current_effective_date = None
                continue

            if not current_number:
                continue

            effective_match = _WV_EFFECTIVE_DATE_RE.search(line)
            if effective_match:
                current_effective_date = effective_match.group(1).strip()

            body_lines.append(line)

    flush()
    return statutes


def _extract_west_virginia_criminal_rules_from_html(
    html_text: str,
    *,
    source_url: str,
    title_name: str,
    procedure_family: str,
    legal_area: str,
    official_cite_prefix: str,
) -> List[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    soup = BeautifulSoup(html_text or "", "html.parser")
    statutes: List[NormalizedStatute] = []
    seen = set()

    for heading in soup.find_all("h5", id=True):
        heading_text = " ".join(heading.get_text(" ", strip=True).split())
        heading_match = _WV_RULE_HEADING_RE.match(heading_text)
        if not heading_match:
            continue

        section_number = heading_match.group(1).strip()
        section_name = heading_match.group(2).strip().rstrip(".")
        body_lines = [f"Rule {section_number}. {section_name}."]
        effective_date = None

        sibling = heading.find_next_sibling()
        while sibling is not None:
            sibling_name = getattr(sibling, "name", None)
            if sibling_name in {"h4", "h5"}:
                break
            text = " ".join(sibling.get_text(" ", strip=True).split()) if hasattr(sibling, "get_text") else ""
            if text:
                effective_match = _WV_EFFECTIVE_DATE_RE.search(text)
                if effective_match:
                    effective_date = effective_match.group(1).strip()
                body_lines.append(text)
            sibling = sibling.find_next_sibling()

        full_text = "\n".join(body_lines).strip()
        if len(full_text) < 40:
            continue

        key = (section_number.lower(), section_name.lower())
        if key in seen:
            continue
        seen.add(key)
        statutes.append(
            NormalizedStatute(
                state_code="WV",
                state_name=US_STATES["WV"],
                statute_id=f"{official_cite_prefix} {section_number}",
                code_name=title_name,
                title_name=title_name,
                chapter_name=title_name,
                section_number=section_number,
                section_name=section_name,
                short_title=section_name,
                full_text=full_text,
                summary=section_name,
                source_url=f"{source_url}#rule{section_number}",
                official_cite=f"{official_cite_prefix} {section_number}",
                legal_area=legal_area,
                structured_data={
                    "effective_date": effective_date,
                    "source_kind": "west_virginia_criminal_rules_html",
                    "procedure_family": procedure_family,
                },
            )
        )

    return statutes


def _extract_north_dakota_rule_links(
    html_text: str,
    *,
    page_url: str,
    procedure_family: str,
    legal_area: str,
    official_cite_prefix: str,
) -> List[Dict[str, str]]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    soup = BeautifulSoup(html_text or "", "html.parser")
    discovered: List[Dict[str, str]] = []
    seen = set()
    base_path = urlparse(page_url).path.rstrip("/").lower()

    for anchor in soup.find_all("a", href=True):
        label = " ".join(anchor.get_text(" ", strip=True).split())
        href = str(anchor.get("href") or "").strip()
        if not label.startswith("Rule ") or not href:
            continue
        match = _ND_RULE_LINK_RE.match(label)
        if not match:
            continue
        absolute_url = urljoin(page_url, href)
        parsed = urlparse(absolute_url)
        if parsed.netloc.lower() != "www.ndcourts.gov":
            continue
        parsed_path = parsed.path.rstrip("/").lower()
        if not parsed_path.startswith(f"{base_path}/"):
            continue
        section_number = match.group(1).strip()
        section_name = match.group(2).strip().rstrip(".")
        key = absolute_url.lower()
        if key in seen:
            continue
        seen.add(key)
        discovered.append(
            {
                "section_number": section_number,
                "section_name": section_name,
                "url": absolute_url,
                "procedure_family": procedure_family,
                "legal_area": legal_area,
                "official_cite_prefix": official_cite_prefix,
            }
        )

    return discovered


def _extract_north_dakota_rule_from_html(
    html_text: str,
    *,
    rule_url: str,
    title_name: str,
    procedure_family: str,
    legal_area: str,
    official_cite_prefix: str,
) -> Optional[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None

    soup = BeautifulSoup(html_text or "", "html.parser")
    article = soup.select_one("article.rule")
    if article is None:
        return None

    heading = article.find("h1")
    if heading is None:
        return None
    heading_text = " ".join(heading.get_text(" ", strip=True).split())
    heading_match = re.match(r"^RULE\s+(\d+(?:\.\d+)?)\.\s+(.+)$", heading_text, re.IGNORECASE)
    if heading_match is None:
        return None

    section_number = heading_match.group(1).strip()
    section_name = heading_match.group(2).strip().rstrip(".")
    effective_date = None
    body_lines: List[str] = [f"Rule {section_number}. {section_name}."]

    for child in article.find_all(["h4", "p"], recursive=False):
        text = " ".join(child.get_text(" ", strip=True).split())
        if not text:
            continue
        effective_match = _ND_EFFECTIVE_DATE_RE.match(text)
        if effective_match:
            effective_date = effective_match.group(1).strip()
            body_lines.append(text)
            continue
        if text in {"Explanatory Note", "Version History"}:
            break
        body_lines.append(text)

    full_text = "\n".join(body_lines).strip()
    if len(full_text) < 40:
        return None

    return NormalizedStatute(
        state_code="ND",
        state_name=US_STATES["ND"],
        statute_id=f"{official_cite_prefix} {section_number}",
        code_name=title_name,
        title_name=title_name,
        chapter_name=title_name,
        section_number=section_number,
        section_name=section_name,
        short_title=section_name,
        full_text=full_text,
        summary=section_name,
        source_url=f"{rule_url}#rule-{section_number}",
        official_cite=f"{official_cite_prefix} {section_number}",
        legal_area=legal_area,
        structured_data={
            "effective_date": effective_date,
            "source_kind": "north_dakota_rule_page",
            "procedure_family": procedure_family,
        },
    )


def _extract_minnesota_rule_links(
    html_text: str,
    *,
    page_url: str,
    procedure_family: str,
    legal_area: str,
    official_cite_prefix: str,
) -> List[Dict[str, str]]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    soup = BeautifulSoup(html_text or "", "html.parser")
    discovered: List[Dict[str, str]] = []
    seen = set()
    page_path = urlparse(page_url).path.lower()
    expected_prefix = "/court_rules/cp/id/" if "/cp" in page_path else "/court_rules/cr/id/"

    for anchor in soup.find_all("a", href=True):
        label = " ".join(anchor.get_text(" ", strip=True).split())
        href = str(anchor.get("href") or "").strip()
        if not href:
            continue
        match = _MN_RULE_LINK_RE.match(label)
        if not match:
            continue
        absolute_url = urljoin(page_url, href)
        parsed = urlparse(absolute_url)
        if parsed.netloc.lower() != "www.revisor.mn.gov":
            continue
        if not parsed.path.lower().startswith(expected_prefix):
            continue
        section_number = match.group(1).strip()
        key = absolute_url.lower()
        if key in seen:
            continue
        seen.add(key)
        discovered.append(
            {
                "section_number": section_number,
                "section_name": "",
                "url": absolute_url,
                "procedure_family": procedure_family,
                "legal_area": legal_area,
                "official_cite_prefix": official_cite_prefix,
            }
        )

    return discovered


def _extract_minnesota_rule_from_html(
    html_text: str,
    *,
    rule_url: str,
    title_name: str,
    procedure_family: str,
    legal_area: str,
    official_cite_prefix: str,
) -> Optional[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None

    soup = BeautifulSoup(html_text or "", "html.parser")
    heading = None
    for candidate in soup.find_all("h3"):
        text = " ".join(candidate.get_text(" ", strip=True).split())
        if text.startswith("Rule "):
            heading = candidate
            break
    if heading is None:
        return None

    heading_text = " ".join(heading.get_text(" ", strip=True).split())
    heading_match = re.match(r"^Rule\s+([0-9]+(?:\.[0-9]+)?[A-Za-z]?)\.\s+(.+)$", heading_text, re.IGNORECASE)
    if heading_match is None:
        return None

    section_number = heading_match.group(1).strip()
    section_name = heading_match.group(2).strip().rstrip(".")
    effective_date = None
    body_lines: List[str] = [f"Rule {section_number}. {section_name}."]

    for sibling in heading.find_next_siblings():
        sibling_name = getattr(sibling, "name", None)
        if sibling_name in {"h3", "h5"}:
            break
        text = " ".join(sibling.get_text(" ", strip=True).split()) if hasattr(sibling, "get_text") else ""
        if not text:
            continue
        effective_matches = _MN_EFFECTIVE_TEXT_RE.findall(text)
        if effective_matches:
            effective_date = effective_matches[-1].strip()
        body_lines.append(text)

    full_text = "\n".join(body_lines).strip()
    if len(full_text) < 40:
        return None

    return NormalizedStatute(
        state_code="MN",
        state_name=US_STATES["MN"],
        statute_id=f"{official_cite_prefix} {section_number}",
        code_name=title_name,
        title_name=title_name,
        chapter_name=title_name,
        section_number=section_number,
        section_name=section_name,
        short_title=section_name,
        full_text=full_text,
        summary=section_name,
        source_url=f"{rule_url}#rule-{section_number.lower()}",
        official_cite=f"{official_cite_prefix} {section_number}",
        legal_area=legal_area,
        structured_data={
            "effective_date": effective_date,
            "source_kind": "minnesota_rule_page",
            "procedure_family": procedure_family,
        },
    )


def _extract_iowa_rules_from_page_texts(
    page_texts: List[tuple[int, str]],
    *,
    source_url: str,
    title_name: str,
    procedure_family: str,
    legal_area: str,
    official_cite_prefix: str,
    first_rule_number: str,
    max_rules: Optional[int] = None,
) -> List[NormalizedStatute]:
    statutes: List[NormalizedStatute] = []
    seen = set()
    first_marker = f"Rule {first_rule_number}"
    start_found = False

    for page_number, page_text in page_texts:
        normalized_page = " ".join(str(page_text or "").replace("\x00", " ").split())
        if not normalized_page:
            continue
        if not start_found:
            marker_index = normalized_page.find(first_marker)
            if marker_index < 0:
                continue
            candidate_page = normalized_page[marker_index:]
            next_rule_index = candidate_page.find(" Rule ", len(first_marker))
            first_rule_block = candidate_page[:next_rule_index] if next_rule_index > 0 else candidate_page
            has_body_sentence = re.search(
                r"\.\s+(?:The|Every|When|In|An|A|No|On|If|This|These|Any|Unless|After|Before|Upon)\b",
                first_rule_block,
            )
            if not has_body_sentence:
                continue
            start_found = True
            normalized_page = candidate_page

        for match in _IA_RULE_HEADING_RE.finditer(normalized_page):
            section_number = match.group(1).replace(" ", "").strip()
            block = " ".join(match.group(2).split())
            if not block:
                continue

            title_match = re.match(r"(.+?\.)\s+(.*)", block, re.DOTALL)
            if title_match:
                section_name = title_match.group(1).strip().rstrip(".")
                body = title_match.group(2).strip()
            else:
                section_name = block.rstrip(".")
                body = ""

            if not section_name or section_name.lower() == "reserved":
                continue

            full_text = f"Rule {section_number} {section_name}."
            if body:
                full_text = f"{full_text}\n{body}"
            if len(full_text) < 40:
                continue

            effective_matches = _IA_EFFECTIVE_DATE_RE.findall(full_text)
            effective_date = effective_matches[-1].strip() if effective_matches else None
            key = (section_number.lower(), section_name.lower())
            if key in seen:
                continue
            seen.add(key)
            statutes.append(
                NormalizedStatute(
                    state_code="IA",
                    state_name=US_STATES["IA"],
                    statute_id=f"{official_cite_prefix} {section_number}",
                    code_name=title_name,
                    title_name=title_name,
                    chapter_name=title_name,
                    section_number=section_number,
                    section_name=section_name,
                    short_title=section_name,
                    full_text=full_text,
                    summary=section_name,
                    source_url=f"{source_url}#rule-{section_number.lower()}",
                    official_cite=f"{official_cite_prefix} {section_number}",
                    legal_area=legal_area,
                    structured_data={
                        "effective_date": effective_date,
                        "source_kind": "iowa_court_rules_pdf",
                        "procedure_family": procedure_family,
                        "page_start": page_number,
                    },
                )
            )
            if max_rules is not None and len(statutes) >= max_rules:
                return statutes[:max_rules]

    return statutes


def _extract_arkansas_rules_from_page_texts(
    page_texts: List[tuple[int, str]],
    *,
    source_url: str,
    title_name: str,
    procedure_family: str,
    legal_area: str,
    official_cite_prefix: str,
    first_rule_number: str,
    max_rules: Optional[int] = None,
) -> List[NormalizedStatute]:
    statutes: List[NormalizedStatute] = []
    seen = set()
    current_number = ""
    current_name = ""
    current_page = 0
    current_effective_date: Optional[str] = None
    body_lines: List[str] = []
    start_found = False
    capture_body = True
    stop_markers = (
        "Reporter’s Notes",
        "Reporter's Notes",
        "Addition to Reporter’s Notes",
        "Addition to Reporter's Notes",
    )

    def flush() -> None:
        nonlocal current_number, current_name, current_page, current_effective_date, body_lines, capture_body
        if not current_number or not current_name:
            current_number = ""
            current_name = ""
            current_page = 0
            current_effective_date = None
            body_lines = []
            capture_body = True
            return

        full_text = "\n".join(line for line in body_lines if line).strip()
        if len(full_text) < 40:
            current_number = ""
            current_name = ""
            current_page = 0
            current_effective_date = None
            body_lines = []
            capture_body = True
            return

        effective_matches = _AR_EFFECTIVE_DATE_RE.findall(full_text)
        if effective_matches:
            current_effective_date = effective_matches[-1].strip()

        key = (current_number.lower(), current_name.lower())
        if key not in seen:
            seen.add(key)
            statutes.append(
                NormalizedStatute(
                    state_code="AR",
                    state_name=US_STATES["AR"],
                    statute_id=f"{official_cite_prefix} {current_number}",
                    code_name=title_name,
                    title_name=title_name,
                    chapter_name=title_name,
                    section_number=current_number,
                    section_name=current_name,
                    short_title=current_name,
                    full_text=full_text,
                    summary=current_name,
                    source_url=f"{source_url}#rule-{current_number}",
                    official_cite=f"{official_cite_prefix} {current_number}",
                    legal_area=legal_area,
                    structured_data={
                        "effective_date": current_effective_date,
                        "source_kind": "arkansas_court_rules_pdf",
                        "procedure_family": procedure_family,
                        "page_start": current_page or None,
                    },
                )
            )

        current_number = ""
        current_name = ""
        current_page = 0
        current_effective_date = None
        body_lines = []
        capture_body = True

    for page_number, page_text in page_texts:
        for raw_line in str(page_text or "").splitlines():
            line = " ".join(raw_line.replace("\x00", " ").split())
            if not line:
                continue
            if line in {"Rules of Civil Procedure", "Rules of Criminal Procedure"}:
                continue

            heading_match = _AR_RULE_HEADING_LINE_RE.match(line)
            if heading_match:
                heading_number = heading_match.group(1).strip()
                if not start_found:
                    if heading_number != first_rule_number:
                        continue
                    start_found = True
                flush()
                current_number = heading_number
                current_name = heading_match.group(2).strip().rstrip(".")
                current_page = page_number
                current_effective_date = None
                body_lines = [f"Rule {current_number}. {current_name}."]
                capture_body = True
                continue

            if not start_found or not current_number:
                continue

            if any(line.startswith(marker) for marker in stop_markers):
                capture_body = False
                continue

            if line == "HISTORY":
                body_lines.append(line)
                continue

            if capture_body:
                body_lines.append(line)

        if max_rules is not None and len(statutes) >= max_rules:
            break

    flush()
    if max_rules is not None and max_rules > 0:
        return statutes[:max_rules]
    return statutes


def _extract_alabama_rule_links(
    html_text: str,
    *,
    page_url: str,
    procedure_family: str,
    legal_area: str,
    official_cite_prefix: str,
    url_prefix: str,
) -> List[Dict[str, str]]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    soup = BeautifulSoup(html_text or "", "html.parser")
    discovered: List[Dict[str, str]] = []
    seen = set()

    for anchor in soup.find_all("a", href=True):
        label = " ".join(anchor.get_text(" ", strip=True).split())
        href = str(anchor.get("href") or "").strip()
        if not label or not href:
            continue
        match = _AL_RULE_LABEL_RE.match(label)
        if not match:
            continue
        absolute_url = urljoin(page_url, href)
        parsed = urlparse(absolute_url)
        if parsed.netloc.lower() != "judicial.alabama.gov":
            continue
        filename = Path(parsed.path).name.lower()
        if not filename.startswith(url_prefix.lower()):
            continue
        section_number = match.group(1).strip()
        key = absolute_url.lower()
        if key in seen:
            continue
        seen.add(key)
        discovered.append(
            {
                "section_number": section_number,
                "section_name": "",
                "url": absolute_url,
                "procedure_family": procedure_family,
                "legal_area": legal_area,
                "official_cite_prefix": official_cite_prefix,
            }
        )

    return discovered


def _extract_alabama_rule_from_text(
    text: str,
    *,
    source_url: str,
    title_name: str,
    section_number: str,
    official_cite_prefix: str,
    procedure_family: str,
    legal_area: str,
) -> Optional[NormalizedStatute]:
    raw_text = str(text or "")
    normalized_text = " ".join(raw_text.replace("\r", " ").replace("\n", " ").split())
    if len(normalized_text) < 60:
        return None

    section_name = ""
    lines = [" ".join(raw_line.split()).strip() for raw_line in raw_text.splitlines()]
    for index, line in enumerate(lines):
        if not line:
            continue
        if re.fullmatch(rf"Rule\s+{re.escape(section_number)}\.", line, re.IGNORECASE):
            for candidate in lines[index + 1 :]:
                if candidate:
                    section_name = candidate.rstrip(".")
                    break
            if section_name:
                break
        heading_match = re.match(rf"^Rule\s+{re.escape(section_number)}\.\s+(.+)$", line, re.IGNORECASE)
        if heading_match:
            section_name = " ".join(heading_match.group(1).split()).strip()
            if ". " in section_name:
                section_name = section_name.split(". ", 1)[0].strip()
            else:
                repeated_word_match = re.match(r"^(.+?\b([A-Z][A-Za-z]+))\s+\2\s+[a-z].*$", section_name)
                if repeated_word_match:
                    section_name = repeated_word_match.group(1).strip()
            section_name = section_name.rstrip(".")
            break
    if not section_name:
        heading_match = re.search(
            rf"Rule\s+{re.escape(section_number)}\.\s+(.+?)(?=\s+\([a-z]\)\s+|\s+Committee Comments|\s+\[|$)",
            normalized_text,
            re.IGNORECASE,
        )
        if heading_match is None:
            return None
        section_name = " ".join(heading_match.group(1).split()).strip().rstrip(".")
    if not section_name:
        return None

    body_start = normalized_text.lower().find(f"rule {section_number}.".lower())
    full_text = normalized_text[body_start:].strip()
    stop_markers = ["Committee Comments", "Committee Notes", "Court Comment", "Appendix to Rule"]
    stop_positions = [full_text.find(marker) for marker in stop_markers if full_text.find(marker) != -1]
    if stop_positions:
        full_text = full_text[: min(stop_positions)].strip()
    if len(full_text) < 60:
        return None

    effective_date = None
    for match in _AL_EFFECTIVE_DATE_RE.finditer(full_text):
        effective_date = next((group for group in match.groups() if group), effective_date)

    return NormalizedStatute(
        state_code="AL",
        state_name=US_STATES["AL"],
        statute_id=f"{official_cite_prefix} {section_number}",
        code_name=title_name,
        title_name=title_name,
        chapter_name=title_name,
        section_number=section_number,
        section_name=section_name,
        short_title=section_name,
        full_text=full_text,
        summary=section_name,
        source_url=f"{source_url}#rule-{section_number.lower()}",
        official_cite=f"{official_cite_prefix} {section_number}",
        legal_area=legal_area,
        structured_data={
            "effective_date": effective_date,
            "source_kind": "pdf_rule_page",
            "procedure_family": procedure_family,
        },
    )


def _extract_tennessee_rule_links(
    html_text: str,
    *,
    page_url: str,
    procedure_family: str,
    legal_area: str,
    official_cite_prefix: str,
) -> List[Dict[str, str]]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    soup = BeautifulSoup(html_text or "", "html.parser")
    content = soup.select_one("div.region-content") or soup.select_one("div.view-content")
    if content is None:
        return []

    discovered: List[Dict[str, str]] = []
    seen = set()
    for anchor in content.select("a[href]"):
        href = str(anchor.get("href") or "").strip()
        label = " ".join(anchor.get_text(" ", strip=True).split())
        if not href or "/rule-" not in href or not label.startswith("Rule "):
            continue
        match = _TN_RULE_LINK_RE.match(label)
        if not match:
            continue
        absolute_url = urljoin(page_url, href)
        key = absolute_url.lower()
        if key in seen:
            continue
        seen.add(key)
        discovered.append(
            {
                "section_number": match.group(1).strip(),
                "section_name": str(match.group(2) or "").strip().rstrip("."),
                "url": absolute_url,
                "procedure_family": procedure_family,
                "legal_area": legal_area,
                "official_cite_prefix": official_cite_prefix,
            }
        )

    return discovered


def _extract_tennessee_rule_from_html(
    html_text: str,
    *,
    rule_url: str,
    title_name: str,
    procedure_family: str,
    legal_area: str,
    official_cite_prefix: str,
) -> Optional[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None

    soup = BeautifulSoup(html_text or "", "html.parser")
    heading_node = soup.find("h1")
    heading = " ".join((heading_node.get_text(" ", strip=True) if heading_node else "").split())
    heading_match = _TN_RULE_HEADING_RE.match(heading)
    if not heading_match:
        return None

    section_number = heading_match.group(1).strip()
    section_name = heading_match.group(2).strip().rstrip(".")
    content = soup.select_one("div.field--name-field-rules-rule-content")
    if content is None:
        return None

    body_lines: List[str] = [f"Rule {section_number}. {section_name}"]
    effective_date: Optional[str] = None
    for paragraph in content.find_all(["p", "li"]):
        text = " ".join(paragraph.get_text(" ", strip=True).split())
        if not text:
            continue
        if text.lower().startswith("advisory commission comment"):
            break
        body_lines.append(text)
        for match in _TN_EFFECTIVE_DATE_RE.finditer(text):
            effective_date = " ".join(match.group(1).split())

    full_text = "\n".join(body_lines).strip()
    if len(full_text) < 60:
        return None

    return NormalizedStatute(
        state_code="TN",
        state_name=US_STATES["TN"],
        statute_id=f"{official_cite_prefix} {section_number}",
        code_name=title_name,
        title_name=title_name,
        chapter_name=title_name,
        section_number=section_number,
        section_name=section_name,
        short_title=section_name,
        full_text=full_text,
        summary=section_name,
        source_url=f"{rule_url}#rule-{section_number.lower()}",
        official_cite=f"{official_cite_prefix} {section_number}",
        legal_area=legal_area,
        structured_data={
            "effective_date": effective_date,
            "source_kind": "tennessee_judiciary_html",
            "procedure_family": procedure_family,
        },
    )


def _extract_virginia_rules_from_page_texts(
    page_texts: List[tuple[int, str]],
    *,
    source_url: str,
    title_name: str,
    procedure_family: str,
    legal_area: str,
    official_cite_prefix: str,
    rule_prefix: str,
    max_rules: Optional[int] = None,
) -> List[NormalizedStatute]:
    prefix_pattern = re.escape(rule_prefix)
    heading_re = re.compile(
        rf"^Rule\s+({prefix_pattern}\d+(?:\.\d+)?[A-Za-z]?)\.\s+(.+?)\.?$",
        re.IGNORECASE,
    )
    skip_exact = {
        "RULES OF SUPREME COURT OF VIRGINIA",
        "RULES OF THE SUPREME COURT OF VIRGINIA",
        "PRACTICE AND PROCEDURE IN CIVIL ACTIONS",
        "CRIMINAL PRACTICE AND PROCEDURE",
        "PART THREE",
        "PART THREE A",
    }
    stop_markers = ("PART THREE B", "PART FOUR")
    statutes: List[NormalizedStatute] = []
    seen = set()
    current_number = ""
    current_name = ""
    current_page = 0
    buffer: List[str] = []

    def flush() -> None:
        nonlocal current_number, current_name, current_page, buffer
        if not current_number or not current_name:
            current_number = ""
            current_name = ""
            current_page = 0
            buffer = []
            return

        full_text = "\n".join(buffer).strip()
        if len(full_text) < 50:
            current_number = ""
            current_name = ""
            current_page = 0
            buffer = []
            return

        effective_date = None
        for match in _VA_EFFECTIVE_DATE_RE.finditer(full_text):
            effective_date = " ".join(match.group(1).split())

        key = (current_number.lower(), current_name.lower())
        if key not in seen:
            seen.add(key)
            statutes.append(
                NormalizedStatute(
                    state_code="VA",
                    state_name=US_STATES["VA"],
                    statute_id=f"{official_cite_prefix} {current_number}",
                    code_name=title_name,
                    title_name=title_name,
                    chapter_name=title_name,
                    section_number=current_number,
                    section_name=current_name,
                    short_title=current_name,
                    full_text=full_text,
                    summary=current_name,
                    source_url=f"{source_url}#page={current_page}",
                    official_cite=f"{official_cite_prefix} {current_number}",
                    legal_area=legal_area,
                    structured_data={
                        "effective_date": effective_date,
                        "source_kind": "virginia_rules_pdf",
                        "procedure_family": procedure_family,
                    },
                )
            )

        current_number = ""
        current_name = ""
        current_page = 0
        buffer = []

    for page_number, page_text in page_texts:
        for raw_line in str(page_text or "").splitlines():
            line = " ".join(raw_line.replace("\x00", " ").split())
            if not line:
                continue
            if any(marker in line for marker in stop_markers):
                flush()
                return statutes[: max_rules or None]
            heading_match = heading_re.match(line)
            if heading_match:
                flush()
                current_number = heading_match.group(1).strip()
                current_name = heading_match.group(2).strip().rstrip(".")
                current_page = page_number
                buffer = [f"Rule {current_number}. {current_name}."]
                continue
            if not current_number:
                continue
            if line in skip_exact:
                continue
            if line.isdigit():
                continue
            buffer.append(line)
        if max_rules and len(statutes) >= int(max_rules):
            break

    flush()
    return statutes[: max_rules or None]


def _extract_indiana_rule_links(
    html_text: str,
    *,
    page_url: str,
    procedure_family: str,
    legal_area: str,
    official_cite_prefix: str,
) -> tuple[List[Dict[str, str]], Optional[str]]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return [], None

    soup = BeautifulSoup(html_text or "", "html.parser")
    content = soup.select_one("#mc-main-content") or soup
    current_as_of = None
    page_text = " ".join(content.get_text(" ", strip=True).split())
    match = re.search(r"Updated,\s+Effective\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})", page_text, re.IGNORECASE)
    if match is None:
        match = re.search(r"current\s+as\s+of\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})", page_text, re.IGNORECASE)
    if match:
        current_as_of = " ".join(match.group(1).split())

    discovered: List[Dict[str, str]] = []
    seen = set()
    for anchor in content.select("a[href]"):
        href = str(anchor.get("href") or "").strip()
        label = " ".join(anchor.get_text(" ", strip=True).split())
        if not href or "current.htm" not in href.lower() or not label.startswith("Rule "):
            continue
        match = _IN_RULE_LINK_RE.match(label)
        if not match:
            continue
        absolute_url = urljoin(page_url, href)
        key = absolute_url.lower()
        if key in seen:
            continue
        seen.add(key)
        discovered.append(
            {
                "section_number": match.group(1).strip(),
                "section_name": match.group(2).strip().rstrip("."),
                "url": absolute_url,
                "procedure_family": procedure_family,
                "legal_area": legal_area,
                "official_cite_prefix": official_cite_prefix,
            }
        )

    return discovered, current_as_of


def _extract_indiana_rule_from_html(
    html_text: str,
    *,
    rule_url: str,
    title_name: str,
    procedure_family: str,
    legal_area: str,
    official_cite_prefix: str,
    current_as_of: Optional[str] = None,
) -> Optional[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None

    soup = BeautifulSoup(html_text or "", "html.parser")
    content = soup.select_one("#mc-main-content") or soup
    heading_node = content.find("h1")
    heading = " ".join((heading_node.get_text(" ", strip=True) if heading_node else "").split())
    heading_match = _IN_RULE_HEADING_RE.match(heading)
    if not heading_match:
        return None

    section_number = heading_match.group(1).strip()
    section_name = heading_match.group(2).strip().rstrip(".")
    effective_date = None
    body_lines: List[str] = [f"Rule {section_number}. {section_name}"]

    effective_node = content.select_one("p.effective")
    if effective_node is not None:
        effective_text = " ".join(effective_node.get_text(" ", strip=True).split())
        match = _IN_EFFECTIVE_DATE_RE.search(effective_text)
        if match:
            effective_date = " ".join(match.group(1).split())

    for node in content.find_all(["p", "ol", "ul", "table"], recursive=False):
        if node is effective_node:
            continue
        if getattr(node, "get", None) and str(node.get("id") or "").strip().lower() == "history":
            break
        text = " ".join(node.get_text(" ", strip=True).split())
        if not text:
            continue
        if text == heading:
            continue
        if text.startswith("Version History"):
            break
        body_lines.append(text)

    history = content.find(id="history")
    if history is not None and len(body_lines) == 1:
        for sibling in history.find_previous_siblings():
            text = " ".join(sibling.get_text(" ", strip=True).split())
            if not text or text == heading:
                continue
            body_lines.insert(1, text)

    full_text = "\n".join(body_lines).strip()
    if len(full_text) < 40:
        return None

    return NormalizedStatute(
        state_code="IN",
        state_name=US_STATES["IN"],
        statute_id=f"{official_cite_prefix} {section_number}",
        code_name=title_name,
        title_name=title_name,
        chapter_name=title_name,
        section_number=section_number,
        section_name=section_name,
        short_title=section_name,
        full_text=full_text,
        summary=section_name,
        source_url=f"{rule_url}#rule-{section_number}",
        official_cite=f"{official_cite_prefix} {section_number}",
        legal_area=legal_area,
        structured_data={
            "effective_date": effective_date,
            "current_as_of": current_as_of,
            "source_kind": "indiana_rules_html",
            "procedure_family": procedure_family,
        },
    )


def _extract_illinois_rule_links(
    html_text: str,
    *,
    page_url: str,
    article_code: str,
    procedure_family: str,
    legal_area: str,
    official_cite_prefix: str,
) -> List[Dict[str, str]]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    soup = BeautifulSoup(html_text or "", "html.parser")
    table = soup.find("table", id="ctl04_gvRules")
    if table is None:
        return []

    discovered: List[Dict[str, str]] = []
    seen = set()
    for row in table.find_all("tr")[1:]:
        cells = row.find_all("td")
        if len(cells) < 3:
            continue
        article = " ".join(cells[0].get_text(" ", strip=True).split())
        if article.upper() != article_code.upper():
            continue
        rule_label = " ".join(cells[1].get_text(" ", strip=True).split())
        match = _IL_RULE_NUMBER_RE.match(rule_label)
        if not match:
            continue
        section_number = match.group(1).strip()
        link = cells[2].find("a", href=True)
        if link is None:
            continue
        href = str(link.get("href") or "").strip()
        title = " ".join(link.get_text(" ", strip=True).split()).rstrip(".")
        if not href or not title:
            continue
        absolute_url = urljoin(page_url, href)
        key = absolute_url.lower()
        if key in seen:
            continue
        seen.add(key)
        discovered.append(
            {
                "section_number": section_number,
                "section_name": title,
                "url": absolute_url,
                "procedure_family": procedure_family,
                "legal_area": legal_area,
                "official_cite_prefix": official_cite_prefix,
            }
        )
    return discovered


def _extract_illinois_rule_from_text(
    text: str,
    *,
    source_url: str,
    title_name: str,
    section_number: str,
    official_cite_prefix: str,
    procedure_family: str,
    legal_area: str,
) -> Optional[NormalizedStatute]:
    normalized = "\n".join(" ".join(line.split()) for line in str(text or "").splitlines() if line.strip())
    heading_match = None
    for line in normalized.splitlines()[:10]:
        match = _IL_PDF_HEADING_RE.match(line.strip())
        if match:
            heading_match = match
            break
    if heading_match is None:
        return None
    if heading_match.group(1).strip() != section_number:
        return None

    section_name = heading_match.group(2).strip().rstrip(".")
    full_text = normalized
    stop_markers = ["Committee Comments", "Committee Commentary", "Adopted "]
    positions = [full_text.find(marker) for marker in stop_markers if full_text.find(marker) > 0]
    if positions:
        full_text = full_text[: min(positions)].strip()
    if len(full_text) < 40:
        return None

    effective_date = None
    for match in _IL_EFFECTIVE_DATE_RE.finditer(normalized):
        effective_date = " ".join(match.group(1).split())

    return NormalizedStatute(
        state_code="IL",
        state_name=US_STATES["IL"],
        statute_id=f"{official_cite_prefix} {section_number}",
        code_name=title_name,
        title_name=title_name,
        chapter_name=title_name,
        section_number=section_number,
        section_name=section_name,
        short_title=section_name,
        full_text=full_text,
        summary=section_name,
        source_url=f"{source_url}#rule-{section_number}",
        official_cite=f"{official_cite_prefix} {section_number}",
        legal_area=legal_area,
        structured_data={
            "effective_date": effective_date,
            "source_kind": "illinois_rule_pdf",
            "procedure_family": procedure_family,
        },
    )


def _extract_georgia_rules_from_page_texts(
    page_texts: Sequence[tuple[int, str]],
    *,
    source_url: str,
    title_name: str,
    procedure_family: str,
    legal_area: str,
    official_cite_prefix: str,
    first_rule_number: str,
    current_as_of: Optional[str] = None,
    max_rules: Optional[int] = None,
) -> List[NormalizedStatute]:
    statutes: List[NormalizedStatute] = []
    collecting = False
    current_number: Optional[str] = None
    current_name: Optional[str] = None
    current_page: Optional[int] = None
    buffer: List[str] = []
    current_effective_date: Optional[str] = None

    def flush() -> None:
        nonlocal current_number, current_name, current_page, buffer, current_effective_date
        if not current_number or not current_name:
            current_number = None
            current_name = None
            current_page = None
            buffer = []
            current_effective_date = None
            return
        full_text = "\n".join(line for line in buffer if line).strip()
        if len(full_text) < 40:
            current_number = None
            current_name = None
            current_page = None
            buffer = []
            current_effective_date = None
            return
        statutes.append(
            NormalizedStatute(
                state_code="GA",
                state_name=US_STATES["GA"],
                statute_id=f"{official_cite_prefix} {current_number}",
                code_name=title_name,
                title_name=title_name,
                chapter_name=title_name,
                section_number=current_number,
                section_name=current_name,
                short_title=current_name,
                full_text=full_text,
                summary=current_name,
                source_url=f"{source_url}#page={current_page}&rule={current_number}",
                official_cite=f"{official_cite_prefix} {current_number}",
                legal_area=legal_area,
                structured_data={
                    "effective_date": current_effective_date,
                    "current_as_of": current_as_of,
                    "source_kind": "georgia_rules_pdf",
                    "procedure_family": procedure_family,
                },
            )
        )
        current_number = None
        current_name = None
        current_page = None
        buffer = []
        current_effective_date = None

    for page_number, page_text in page_texts:
        if max_rules and len(statutes) >= int(max_rules):
            break
        for raw_line in str(page_text or "").splitlines():
            line = " ".join(raw_line.split())
            if not line:
                continue
            if re.fullmatch(r"[ivxlcdm]+", line, re.IGNORECASE):
                continue
            if re.fullmatch(r"\d+", line):
                continue
            if "................................................................" in line:
                continue
            if not collecting:
                heading = _GA_RULE_HEADING_RE.match(line)
                if heading and heading.group(1).strip() == first_rule_number:
                    collecting = True
                else:
                    continue
            heading = _GA_RULE_HEADING_RE.match(line)
            if heading:
                flush()
                current_number = heading.group(1).strip()
                current_name = heading.group(2).strip().rstrip(".")
                current_page = page_number
                buffer = [f"Rule {current_number}. {current_name}"]
                continue
            if current_number is None:
                continue
            effective_dates = [
                " ".join(match.group(1).split())
                for match in _GA_EFFECTIVE_DATE_RE.finditer(line)
                if match.group(1)
            ]
            if effective_dates:
                current_effective_date = effective_dates[-1]
            buffer.append(line)
        if max_rules and len(statutes) >= int(max_rules):
            break

    flush()
    return statutes[: max_rules or None]


def _extract_pennsylvania_rules_from_html(
    html_text: str,
    *,
    source_url: str,
    title_name: str,
    procedure_family: str,
    legal_area: str,
    official_cite_prefix: str,
    first_rule_number: str,
    current_as_of: Optional[str] = None,
    max_rules: Optional[int] = None,
) -> List[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    soup = BeautifulSoup(html_text or "", "html.parser")
    lines = [
        " ".join(line.split())
        for line in soup.get_text("\n", strip=True).splitlines()
    ]
    lines = [line for line in lines if line]

    statutes: List[NormalizedStatute] = []
    collecting = False
    current_number: Optional[str] = None
    current_name: Optional[str] = None
    buffer: List[str] = []
    pending_number: Optional[str] = None

    def flush() -> None:
        nonlocal current_number, current_name, buffer
        if not current_number or not current_name:
            current_number = None
            current_name = None
            buffer = []
            return
        full_text = "\n".join(buffer).strip()
        if len(full_text) < 40:
            current_number = None
            current_name = None
            buffer = []
            return
        statutes.append(
            NormalizedStatute(
                state_code="PA",
                state_name=US_STATES["PA"],
                statute_id=f"{official_cite_prefix} {current_number}",
                code_name=title_name,
                title_name=title_name,
                chapter_name=title_name,
                section_number=current_number,
                section_name=current_name,
                short_title=current_name,
                full_text=full_text,
                summary=current_name,
                source_url=f"{source_url}#rule-{current_number}",
                official_cite=f"{official_cite_prefix} {current_number}",
                legal_area=legal_area,
                structured_data={
                    "current_as_of": current_as_of,
                    "source_kind": "pennsylvania_rules_html",
                    "procedure_family": procedure_family,
                },
            )
        )
        current_number = None
        current_name = None
        buffer = []

    for line in lines:
        if pending_number is not None:
            flush()
            current_number = pending_number
            current_name = line.strip().rstrip(".")
            buffer = [f"Rule {current_number}. {current_name}"]
            pending_number = None
            if max_rules and len(statutes) >= int(max_rules):
                break
            continue
        heading = _PA_RULE_HEADING_RE.match(line)
        if not collecting:
            if heading and heading.group(1).strip() == first_rule_number:
                collecting = True
            elif re.fullmatch(r"Rule\s+%s\.\s*" % re.escape(first_rule_number), line, re.IGNORECASE):
                collecting = True
            else:
                continue
        if heading:
            flush()
            current_number = heading.group(1).strip()
            current_name = heading.group(2).strip().rstrip(".")
            buffer = [f"Rule {current_number}. {current_name}"]
            if max_rules and len(statutes) >= int(max_rules):
                break
            continue
        split_heading = re.fullmatch(r"Rule\s+(\d+(?:\.\d+)*)\.\s*", line, re.IGNORECASE)
        if split_heading:
            pending_number = split_heading.group(1).strip()
            continue
        if current_number is None:
            continue
        if line in {"Comment", "Official Note"} or _PA_SOURCE_RE.match(line):
            flush()
            if max_rules and len(statutes) >= int(max_rules):
                break
            continue
        if line.startswith("Title 231") or line.startswith("Title 234") or line.startswith("Chapter "):
            continue
        if line == "Rule":
            continue
        buffer.append(line)

    flush()
    return statutes[: max_rules or None]


def _extract_nebraska_rule_from_html(
    html_text: str,
    *,
    rule_url: str,
    title_name: str,
    section_number: str,
    section_name: str,
    procedure_family: str,
    legal_area: str,
    official_cite_prefix: str,
) -> Optional[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None

    soup = BeautifulSoup(html_text or "", "html.parser")
    body = soup.select_one("article.node .node__content .field--name-body.field__item")
    if body is None:
        body = soup.select_one("article.node .field--name-body")
    if body is None:
        return None

    text_lines = [
        " ".join(line.split())
        for line in body.get_text("\n", strip=True).splitlines()
    ]
    text_lines = [line for line in text_lines if line and line != "Printer-Friendly Version"]
    if not text_lines:
        return None

    full_text = "\n".join([f"§ {section_number}. {section_name}", *text_lines]).strip()
    if len(full_text) < 40:
        return None

    effective_dates = [
        " ".join(match.group(1).split())
        for match in _NE_EFFECTIVE_DATE_RE.finditer(full_text)
        if match.group(1)
    ]
    effective_date = effective_dates[-1] if effective_dates else None
    official_cite = (
        f"{official_cite_prefix} {section_number}"
        if official_cite_prefix.endswith("§")
        else f"{official_cite_prefix} § {section_number}"
    )

    return NormalizedStatute(
        state_code="NE",
        state_name=US_STATES["NE"],
        statute_id=official_cite,
        code_name=title_name,
        title_name=title_name,
        chapter_name=title_name,
        section_number=section_number,
        section_name=section_name,
        short_title=section_name,
        full_text=full_text,
        summary=section_name,
        source_url=f"{rule_url}#section-{section_number}",
        official_cite=official_cite,
        legal_area=legal_area,
        structured_data={
            "effective_date": effective_date,
            "source_kind": "nebraska_judicial_branch_rule_page",
            "procedure_family": procedure_family,
        },
    )


def _extract_arizona_rules_from_text(
    text: str,
    *,
    source_url: str,
    title_name: str,
    procedure_family: str,
    legal_area: str,
    effective_date: Optional[str],
    start_marker: str,
) -> List[NormalizedStatute]:
    normalized_text = " ".join(str(text or "").replace("\r", " ").replace("\n", " ").split())
    start_index = normalized_text.rfind(start_marker)
    if start_index != -1:
        normalized_text = normalized_text[start_index:]

    statutes: List[NormalizedStatute] = []
    seen = set()
    for match in _AZ_RULE_BLOCK_RE.finditer(normalized_text):
        section_number = str(match.group(1) or "").strip()
        body = str(match.group(2) or "").strip()
        if not section_number or not body:
            continue
        full_text = f"Rule {section_number}. {body}".strip()
        if len(full_text) < 80:
            continue

        section_name = body
        for marker in [". (", ". [", ". Comment", ". Comment to", ". "]:
            marker_index = section_name.find(marker)
            if marker_index != -1:
                section_name = section_name[:marker_index]
                break
        section_name = section_name.strip().rstrip(".")
        if not section_name:
            continue

        key = (section_number.lower(), section_name.lower())
        if key in seen:
            continue
        seen.add(key)

        statutes.append(
            NormalizedStatute(
                state_code="AZ",
                state_name=US_STATES["AZ"],
                statute_id=f"{title_name} Rule {section_number}",
                code_name=title_name,
                title_name=title_name,
                chapter_name=title_name,
                section_number=section_number,
                section_name=section_name,
                short_title=section_name,
                full_text=full_text,
                summary=section_name,
                source_url=f"{source_url}#rule-{section_number.lower()}",
                official_cite=f"{title_name} Rule {section_number}",
                legal_area=legal_area,
                structured_data={
                    "effective_date": effective_date or None,
                    "source_kind": "pdf_rule_book",
                    "procedure_family": procedure_family,
                },
            )
        )

    return statutes


def _extract_washington_rule_from_text(
    text: str,
    *,
    source_url: str,
    title_name: str,
    section_number: str,
    section_name: str,
    official_cite_prefix: str,
    procedure_family: str,
    legal_area: str,
) -> Optional[NormalizedStatute]:
    normalized_text = " ".join(str(text or "").replace("\r", " ").replace("\n", " ").split())
    if len(normalized_text) < 60:
        return None

    upper_cite = f"{official_cite_prefix} {section_number}".upper()
    body_start = normalized_text.upper().find(upper_cite)
    full_text = normalized_text[body_start:].strip() if body_start != -1 else normalized_text
    if len(full_text) < 60:
        return None

    effective_dates = [
        " ".join(match.group(1).split())
        for match in _WA_EFFECTIVE_DATE_RE.finditer(full_text)
        if match.group(1)
    ]
    effective_date = effective_dates[-1] if effective_dates else None

    return NormalizedStatute(
        state_code="WA",
        state_name=US_STATES["WA"],
        statute_id=f"{official_cite_prefix} {section_number}",
        code_name=title_name,
        title_name=title_name,
        chapter_name=title_name,
        section_number=section_number,
        section_name=section_name,
        short_title=section_name,
        full_text=full_text,
        summary=section_name,
        source_url=f"{source_url}#rule-{section_number.lower().replace(' ', '-')}",
        official_cite=f"{official_cite_prefix} {section_number}",
        legal_area=legal_area,
        structured_data={
            "effective_date": effective_date,
            "source_kind": "pdf_rule_page",
            "procedure_family": procedure_family,
        },
    )


def _merge_fetch_analytics(
    base_fetch_analytics_by_state: Dict[str, Dict[str, Any]],
    supplemental_fetch_analytics_by_state: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}

    for state_code in sorted(set(base_fetch_analytics_by_state) | set(supplemental_fetch_analytics_by_state)):
        base_metrics = base_fetch_analytics_by_state.get(state_code) or {}
        supplemental_metrics = supplemental_fetch_analytics_by_state.get(state_code) or {}

        attempted = int(base_metrics.get("attempted", 0) or 0) + int(supplemental_metrics.get("attempted", 0) or 0)
        success = int(base_metrics.get("success", 0) or 0) + int(supplemental_metrics.get("success", 0) or 0)
        fallback_count = int(base_metrics.get("fallback_count", 0) or 0) + int(
            supplemental_metrics.get("fallback_count", 0) or 0
        )
        cache_hits = int(base_metrics.get("cache_hits", 0) or 0) + int(supplemental_metrics.get("cache_hits", 0) or 0)
        cache_writes = int(base_metrics.get("cache_writes", 0) or 0) + int(
            supplemental_metrics.get("cache_writes", 0) or 0
        )

        providers: Dict[str, int] = {}
        for provider_metrics in [base_metrics.get("providers"), supplemental_metrics.get("providers")]:
            if not isinstance(provider_metrics, dict):
                continue
            for provider, count in provider_metrics.items():
                providers[str(provider)] = int(providers.get(str(provider), 0) or 0) + int(count or 0)

        merged[state_code] = {
            "attempted": attempted,
            "success": success,
            "success_ratio": round((success / attempted), 3) if attempted > 0 else 0.0,
            "fallback_count": fallback_count,
            "cache_hits": cache_hits,
            "cache_writes": cache_writes,
            "providers": providers,
            "last_error": supplemental_metrics.get("last_error") or base_metrics.get("last_error"),
        }

    return merged


async def _scrape_rhode_island_court_rules_supplement(
    *,
    existing_source_urls: Optional[set[str]] = None,
    max_rules: Optional[int] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    fetcher = _ProcedureRulesSupplementFetcher("RI", US_STATES["RI"])
    existing_urls = {
        str(url or "").strip().lower()
        for url in (existing_source_urls or set())
        if str(url or "").strip()
    }
    remaining = int(max_rules) if max_rules and int(max_rules) > 0 else None

    discovered_pdfs: List[Dict[str, str]] = []
    queued_pages = [_RI_COURT_RULES_HUB_URL]
    seen_pages = set()
    seen_pdf_urls = set()

    while queued_pages:
        page_url = queued_pages.pop(0)
        if page_url in seen_pages:
            continue
        seen_pages.add(page_url)

        page_bytes = await fetcher._fetch_page_content_with_archival_fallback(page_url)
        page_text = page_bytes.decode("utf-8", errors="replace") if page_bytes else ""
        page_links = _extract_rhode_island_rule_links(page_text, page_url) if page_text else []
        if not page_links:
            try:
                response = requests.get(
                    page_url,
                    timeout=20,
                    headers={"User-Agent": "Mozilla/5.0"},
                )
            except Exception as exc:
                fetcher._record_fetch_event(provider="direct", success=False, error=str(exc))
                continue
            if response.status_code != 200 or not response.content:
                fetcher._record_fetch_event(
                    provider="direct",
                    success=False,
                    error=f"http {response.status_code}",
                )
                continue
            page_bytes = response.content
            await fetcher._store_page_bytes_in_ipfs_cache(
                url=page_url,
                payload=page_bytes,
                provider="direct",
            )
            fetcher._record_fetch_event(provider="direct", success=True)
            page_text = page_bytes.decode("utf-8", errors="replace")
            page_links = _extract_rhode_island_rule_links(page_text, page_url)

        if not page_links:
            continue

        for link in page_links:
            if link["kind"] == "page":
                if link["url"] not in seen_pages:
                    queued_pages.append(link["url"])
                continue

            pdf_key = link["url"].lower()
            if pdf_key in seen_pdf_urls or pdf_key in existing_urls:
                continue
            seen_pdf_urls.add(pdf_key)
            discovered_pdfs.append(link)

    supplemental_rules: List[Dict[str, Any]] = []
    for ordinal, rule_doc in enumerate(discovered_pdfs, start=1):
        if remaining is not None and len(supplemental_rules) >= remaining:
            break

        raw_bytes = await fetcher._fetch_page_content_with_archival_fallback(rule_doc["url"])
        if not raw_bytes:
            continue

        document = await fetcher._extract_text_from_document_bytes(
            source_url=rule_doc["url"],
            raw_bytes=raw_bytes,
        )
        if not isinstance(document, dict):
            continue

        cleaned_text = fetcher._normalize_legal_text(str(document.get("text") or ""))
        if len(cleaned_text) < 160:
            continue

        family = _classify_procedure_family(
            {
                "name": rule_doc["label"],
                "sectionName": rule_doc["label"],
                "text": cleaned_text,
                "source_url": rule_doc["url"],
            }
        )
        if not family:
            continue

        locator = _derive_rhode_island_rule_locator(rule_doc["label"], rule_doc["url"], ordinal)
        statute = NormalizedStatute(
            state_code="RI",
            state_name=US_STATES["RI"],
            statute_id=f"Rhode Island Court Rule {locator}",
            code_name="Rhode Island Court Rules",
            title_name="Rhode Island Judiciary Court Rules",
            section_number=locator,
            section_name=rule_doc["label"],
            full_text=cleaned_text,
            source_url=rule_doc["url"],
            official_cite=rule_doc["label"],
            legal_area="criminal" if family == "criminal_procedure" else "civil",
            structured_data={
                "method_used": str(document.get("method") or ""),
                "source_content_type": str(document.get("content_type") or ""),
            },
        )
        statute = fetcher._enrich_statute_structure(statute)
        row = statute.to_dict()
        row["procedure_family"] = family
        supplemental_rules.append(row)
        existing_urls.add(rule_doc["url"].lower())

    return supplemental_rules, fetcher.get_fetch_analytics_snapshot()


async def _scrape_oregon_court_rules_supplement(
    *,
    existing_source_urls: Optional[set[str]] = None,
    max_rules: Optional[int] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    from .state_scrapers.oregon import (
        LOCAL_RULES_INDEX_URL,
        ORCP_PRIMARY_URL,
        OregonScraper,
    )

    scraper = OregonScraper("OR", US_STATES["OR"])
    existing_urls = {
        str(url or "").strip().lower()
        for url in (existing_source_urls or set())
        if str(url or "").strip()
    }
    remaining = int(max_rules) if max_rules and int(max_rules) > 0 else None

    async def _collect(
        code_name: str,
        code_url: str,
        method_name: str,
    ) -> List[NormalizedStatute]:
        nonlocal remaining
        if remaining is not None and remaining <= 0:
            return []

        scrape_method = getattr(scraper, method_name)
        rows = await scrape_method(code_name, code_url) if code_url else await scrape_method(code_name)
        deduped: List[NormalizedStatute] = []
        for row in rows:
            source_url = str(getattr(row, "source_url", "") or "").strip().lower()
            if source_url and source_url in existing_urls:
                continue
            if source_url:
                existing_urls.add(source_url)
            deduped.append(row)
            if remaining is not None:
                remaining -= 1
                if remaining <= 0:
                    break
        return deduped

    supplemental_statutes: List[NormalizedStatute] = []
    supplemental_statutes.extend(
        await _collect(
            "Oregon Rules of Civil Procedure",
            ORCP_PRIMARY_URL,
            "_scrape_civil_procedure_rules",
        )
    )
    supplemental_statutes.extend(
        await _collect(
            "Oregon Rules of Criminal Procedure",
            "",
            "_scrape_criminal_procedure_rules",
        )
    )
    supplemental_statutes.extend(
        await _collect(
            "Oregon Local Court Rules",
            LOCAL_RULES_INDEX_URL,
            "_scrape_local_court_rules",
        )
    )

    supplemental_rules: List[Dict[str, Any]] = []
    for statute in supplemental_statutes:
        enriched = scraper._enrich_statute_structure(statute).to_dict()
        family = _classify_procedure_family(enriched)
        if not family:
            legal_area = str(enriched.get("legal_area") or "").strip().lower()
            if "criminal" in legal_area:
                family = "criminal_procedure"
            elif any(token in legal_area for token in ["civil", "court_rules"]):
                family = "civil_procedure"
        if not family:
            continue
        enriched["procedure_family"] = family
        supplemental_rules.append(enriched)

    return supplemental_rules, scraper.get_fetch_analytics_snapshot()


async def _scrape_michigan_court_rules_supplement(
    *,
    existing_source_urls: Optional[set[str]] = None,
    max_rules: Optional[int] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    fetcher = _MichiganProcedureRulesSupplementFetcher("MI", US_STATES["MI"])
    existing_urls = {
        str(url or "").strip().lower()
        for url in (existing_source_urls or set())
        if str(url or "").strip()
    }
    remaining = int(max_rules) if max_rules and int(max_rules) > 0 else None
    supplemental_rules: List[Dict[str, Any]] = []

    for chapter in _MI_COURT_RULES_CHAPTERS:
        if remaining is not None and remaining <= 0:
            break

        chapter_url = str(chapter["url"])
        chapter_key = chapter_url.strip().lower()
        if chapter_key in existing_urls:
            continue

        raw_bytes = await fetcher._fetch_page_content_with_archival_fallback(chapter_url, timeout_seconds=120)
        if not raw_bytes:
            continue

        html_text = raw_bytes.decode("utf-8", errors="replace")
        statutes = _extract_michigan_rules_from_html(
            html_text,
            chapter_url=chapter_url,
            code_name="Michigan Court Rules",
            procedure_family=str(chapter["procedure_family"]),
            legal_area=str(chapter["legal_area"]),
        )
        if not statutes:
            continue

        for statute in statutes:
            if remaining is not None and remaining <= 0:
                break
            enriched = fetcher._enrich_statute_structure(statute).to_dict()
            family = _classify_procedure_family(enriched) or str(chapter["procedure_family"])
            enriched["procedure_family"] = family
            supplemental_rules.append(enriched)
            remaining = None if remaining is None else remaining - 1

        existing_urls.add(chapter_key)

    return supplemental_rules, fetcher.get_fetch_analytics_snapshot()


async def _scrape_california_court_rules_supplement(
    *,
    existing_source_urls: Optional[set[str]] = None,
    max_rules: Optional[int] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    fetcher = _CaliforniaProcedureRulesSupplementFetcher("CA", US_STATES["CA"])
    existing_urls = {
        str(url or "").strip().lower()
        for url in (existing_source_urls or set())
        if str(url or "").strip()
    }
    remaining = int(max_rules) if max_rules and int(max_rules) > 0 else None
    supplemental_rules: List[Dict[str, Any]] = []

    for title in _CA_RULE_TITLES:
        if remaining is not None and remaining <= 0:
            break

        title_html = await _fetch_html_with_direct_fallback(
            fetcher,
            str(title["url"]),
            validator=lambda html: len(
                _extract_california_rule_links(
                    html,
                    title_url=str(title["url"]),
                    procedure_family=str(title["procedure_family"]),
                    legal_area=str(title["legal_area"]),
                )[0]
            )
            > 0,
            timeout_seconds=120,
        )
        if not title_html:
            continue
        rule_links, current_as_of = _extract_california_rule_links(
            title_html,
            title_url=str(title["url"]),
            procedure_family=str(title["procedure_family"]),
            legal_area=str(title["legal_area"]),
        )

        for rule in rule_links:
            if remaining is not None and remaining <= 0:
                break

            rule_url = str(rule["url"])
            rule_key = rule_url.strip().lower()
            if rule_key in existing_urls:
                continue

            rule_html = await _fetch_html_with_direct_fallback(
                fetcher,
                rule_url,
                validator=lambda html: _extract_california_rule_from_html(
                    html,
                    rule_url=rule_url,
                    code_name="California Rules of Court",
                    title_name=str(title["title_name"]),
                    procedure_family=str(rule["procedure_family"]),
                    legal_area=str(rule["legal_area"]),
                    current_as_of=current_as_of,
                )
                is not None,
                timeout_seconds=120,
            )
            if not rule_html:
                continue

            statute = _extract_california_rule_from_html(
                rule_html,
                rule_url=rule_url,
                code_name="California Rules of Court",
                title_name=str(title["title_name"]),
                procedure_family=str(rule["procedure_family"]),
                legal_area=str(rule["legal_area"]),
                current_as_of=current_as_of,
            )
            if statute is None:
                continue

            enriched = fetcher._enrich_statute_structure(statute).to_dict()
            family = str(rule["procedure_family"])
            enriched["procedure_family"] = family
            structured_data = enriched.get("structured_data")
            if isinstance(structured_data, dict):
                structured_data["procedure_family"] = family
            supplemental_rules.append(enriched)
            existing_urls.add(rule_key)
            remaining = None if remaining is None else remaining - 1

    return supplemental_rules, fetcher.get_fetch_analytics_snapshot()


async def _scrape_ohio_court_rules_supplement(
    *,
    existing_source_urls: Optional[set[str]] = None,
    max_rules: Optional[int] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    fetcher = _OhioProcedureRulesSupplementFetcher("OH", US_STATES["OH"])
    existing_urls = {
        str(url or "").strip().lower()
        for url in (existing_source_urls or set())
        if str(url or "").strip()
    }
    remaining = int(max_rules) if max_rules and int(max_rules) > 0 else None
    supplemental_rules: List[Dict[str, Any]] = []

    for document in _OH_RULE_DOCUMENTS:
        if remaining is not None and remaining <= 0:
            break

        source_url = str(document["url"])
        if source_url.lower() in existing_urls:
            continue

        raw_bytes = await fetcher._fetch_page_content_with_archival_fallback(source_url, timeout_seconds=180)
        if not raw_bytes:
            continue

        extracted = await fetcher._extract_text_from_document_bytes(
            source_url=source_url,
            raw_bytes=raw_bytes,
        )
        if not isinstance(extracted, dict):
            continue

        cleaned_text = fetcher._normalize_legal_text(str(extracted.get("text") or ""))
        if len(cleaned_text) < 400:
            continue

        statutes = _extract_ohio_rules_from_text(
            cleaned_text,
            source_url=source_url,
            title_name=str(document["title_name"]),
            procedure_family=str(document["procedure_family"]),
            legal_area=str(document["legal_area"]),
            effective_date=str(document.get("effective_date") or "") or None,
        )
        if not statutes:
            continue

        for statute in statutes:
            if remaining is not None and remaining <= 0:
                break
            enriched = fetcher._enrich_statute_structure(statute).to_dict()
            family = _classify_procedure_family(enriched) or str(document["procedure_family"])
            enriched["procedure_family"] = family
            supplemental_rules.append(enriched)
            remaining = None if remaining is None else remaining - 1

        existing_urls.add(source_url.lower())

    return supplemental_rules, fetcher.get_fetch_analytics_snapshot()


async def _scrape_arizona_court_rules_supplement(
    *,
    existing_source_urls: Optional[set[str]] = None,
    max_rules: Optional[int] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    fetcher = _ArizonaProcedureRulesSupplementFetcher("AZ", US_STATES["AZ"])
    existing_urls = {
        str(url or "").strip().lower()
        for url in (existing_source_urls or set())
        if str(url or "").strip()
    }
    remaining = int(max_rules) if max_rules and int(max_rules) > 0 else None
    supplemental_rules: List[Dict[str, Any]] = []

    for document in _AZ_RULE_DOCUMENTS:
        if remaining is not None and remaining <= 0:
            break

        source_url = str(document["url"])
        if source_url.lower() in existing_urls:
            continue

        raw_bytes = await _fetch_pdf_bytes_with_direct_fallback(
            fetcher,
            source_url,
            timeout_seconds=180,
        )
        if not raw_bytes:
            continue

        extracted = await fetcher._extract_text_from_document_bytes(
            source_url=source_url,
            raw_bytes=raw_bytes,
        )
        if not isinstance(extracted, dict):
            continue

        cleaned_text = fetcher._normalize_legal_text(str(extracted.get("text") or ""))
        if len(cleaned_text) < 400:
            continue

        statutes = _extract_arizona_rules_from_text(
            cleaned_text,
            source_url=source_url,
            title_name=str(document["title_name"]),
            procedure_family=str(document["procedure_family"]),
            legal_area=str(document["legal_area"]),
            effective_date=str(document.get("effective_date") or "") or None,
            start_marker=str(document["start_marker"]),
        )
        if not statutes:
            continue

        for statute in statutes:
            if remaining is not None and remaining <= 0:
                break
            enriched = fetcher._enrich_statute_structure(statute).to_dict()
            family = _classify_procedure_family(enriched) or str(document["procedure_family"])
            enriched["procedure_family"] = family
            supplemental_rules.append(enriched)
            remaining = None if remaining is None else remaining - 1

        existing_urls.add(source_url.lower())

    return supplemental_rules, fetcher.get_fetch_analytics_snapshot()


async def _scrape_washington_court_rules_supplement(
    *,
    existing_source_urls: Optional[set[str]] = None,
    max_rules: Optional[int] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    fetcher = _WashingtonProcedureRulesSupplementFetcher("WA", US_STATES["WA"])
    existing_urls = {
        str(url or "").strip().lower()
        for url in (existing_source_urls or set())
        if str(url or "").strip()
    }
    remaining = int(max_rules) if max_rules and int(max_rules) > 0 else None
    supplemental_rules: List[Dict[str, Any]] = []

    for list_page in _WA_RULE_LIST_PAGES:
        if remaining is not None and remaining <= 0:
            break

        list_url = str(list_page["url"])
        list_html = await _fetch_html_with_direct_fallback(
            fetcher,
            list_url,
            validator=lambda html: len(
                _extract_washington_rule_links(
                    html,
                    page_url=list_url,
                    procedure_family=str(list_page["procedure_family"]),
                    legal_area=str(list_page["legal_area"]),
                    official_cite_prefix=str(list_page["official_cite_prefix"]),
                )
            )
            > 0,
            timeout_seconds=120,
        )
        if not list_html:
            continue

        rule_links = _extract_washington_rule_links(
            list_html,
            page_url=list_url,
            procedure_family=str(list_page["procedure_family"]),
            legal_area=str(list_page["legal_area"]),
            official_cite_prefix=str(list_page["official_cite_prefix"]),
        )
        for rule in rule_links:
            if remaining is not None and remaining <= 0:
                break

            source_url = str(rule["url"])
            if source_url.lower() in existing_urls:
                continue

            raw_bytes = await _fetch_pdf_bytes_with_direct_fallback(
                fetcher,
                source_url,
                timeout_seconds=180,
            )
            if not raw_bytes:
                continue

            extracted = await fetcher._extract_text_from_document_bytes(
                source_url=source_url,
                raw_bytes=raw_bytes,
            )
            if not isinstance(extracted, dict):
                continue

            statute = _extract_washington_rule_from_text(
                str(extracted.get("text") or ""),
                source_url=source_url,
                title_name=str(list_page["title_name"]),
                section_number=str(rule["section_number"]),
                section_name=str(rule["section_name"]),
                official_cite_prefix=str(rule["official_cite_prefix"]),
                procedure_family=str(rule["procedure_family"]),
                legal_area=str(rule["legal_area"]),
            )
            if statute is None:
                continue

            enriched = fetcher._enrich_statute_structure(statute).to_dict()
            family = str(rule["procedure_family"])
            enriched["procedure_family"] = family
            structured_data = enriched.get("structured_data")
            if isinstance(structured_data, dict):
                structured_data["procedure_family"] = family
            supplemental_rules.append(enriched)
            existing_urls.add(source_url.lower())
            remaining = None if remaining is None else remaining - 1

    return supplemental_rules, fetcher.get_fetch_analytics_snapshot()


async def _scrape_new_jersey_court_rules_supplement(
    *,
    existing_source_urls: Optional[set[str]] = None,
    max_rules: Optional[int] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    fetcher = _NewJerseyProcedureRulesSupplementFetcher("NJ", US_STATES["NJ"])
    existing_urls = {
        str(url or "").strip().lower()
        for url in (existing_source_urls or set())
        if str(url or "").strip()
    }
    remaining = int(max_rules) if max_rules and int(max_rules) > 0 else None
    supplemental_rules: List[Dict[str, Any]] = []

    tree_url = "https://www.njcourts.gov/njcourts_rules_of_court/tree"
    tree_data = await _fetch_json_with_direct_fallback(fetcher, tree_url, timeout_seconds=120)
    if not isinstance(tree_data, list):
        return supplemental_rules, fetcher.get_fetch_analytics_snapshot()

    part_lookup = {row["section"]: row for row in _NJ_RULE_PARTS}
    top_level_rules = [row for row in tree_data if str(row.get("section") or "") in part_lookup]

    for top_rule in top_level_rules:
        if remaining is not None and remaining <= 0:
            break

        section = str(top_rule.get("section") or "")
        rule_meta = part_lookup.get(section)
        if not rule_meta:
            continue

        rule_entries = [top_rule]
        if bool(top_rule.get("lazy")):
            subtree_url = f"https://www.njcourts.gov/njcourts_rules_of_court/subtree?tid={top_rule.get('key')}"
            subtree_data = await _fetch_json_with_direct_fallback(fetcher, subtree_url, timeout_seconds=120)
            if isinstance(subtree_data, list) and subtree_data:
                rule_entries = subtree_data

        for entry in rule_entries:
            if remaining is not None and remaining <= 0:
                break

            key = str(entry.get("key") or "").strip()
            title = str(entry.get("title") or "").strip()
            if not key or not title:
                continue

            match = _NJ_RULE_TITLE_RE.match(title)
            if match:
                section_number = match.group(1).strip()
                section_name = match.group(2).strip()
            elif "-" in title:
                section_number, section_name = title.split("-", 1)
                section_number = section_number.strip()
                section_name = section_name.strip()
            else:
                continue
            if not section_number or not section_name:
                continue

            source_url = f"https://www.njcourts.gov/njcourts_rules_of_court/get-term?tid={key}"
            if source_url.lower() in existing_urls:
                continue

            term_data = await _fetch_json_with_direct_fallback(fetcher, source_url, timeout_seconds=120)
            description_html = ""
            if isinstance(term_data, dict):
                description_html = str(term_data.get("description") or "")
            if not description_html.strip():
                continue

            statute = _extract_new_jersey_rule_from_description(
                description_html,
                section_number=section_number,
                section_name=section_name,
                source_url=f"{source_url}#rule-{section_number.lower().replace(':', '-').replace(' ', '-')}",
                title_name=str(rule_meta["title_name"]),
                procedure_family=str(rule_meta["procedure_family"]),
                legal_area=str(rule_meta["legal_area"]),
            )
            if statute is None:
                continue

            enriched = fetcher._enrich_statute_structure(statute).to_dict()
            family = _classify_procedure_family(enriched) or str(rule_meta["procedure_family"])
            enriched["procedure_family"] = family
            supplemental_rules.append(enriched)
            existing_urls.add(source_url.lower())
            remaining = None if remaining is None else remaining - 1

    return supplemental_rules, fetcher.get_fetch_analytics_snapshot()


async def _scrape_new_hampshire_court_rules_supplement(
    *,
    existing_source_urls: Optional[set[str]] = None,
    max_rules: Optional[int] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    fetcher = _NewHampshireProcedureRulesSupplementFetcher("NH", US_STATES["NH"])
    existing_urls = {
        str(url or "").strip().lower()
        for url in (existing_source_urls or set())
        if str(url or "").strip()
    }
    remaining = int(max_rules) if max_rules and int(max_rules) > 0 else None
    supplemental_rules: List[Dict[str, Any]] = []

    for source in _NH_RULE_SOURCES:
        if remaining is not None and remaining <= 0:
            break

        source_url = str(source["url"])
        html = await _fetch_html_with_direct_fallback(
            fetcher,
            source_url,
            validator=lambda raw_html: len(
                _extract_new_hampshire_rules_from_online_book_html(
                    raw_html,
                    source_url=source_url,
                    title_name=str(source["title_name"]),
                    procedure_family=str(source["procedure_family"]),
                    legal_area=str(source["legal_area"]),
                    official_cite_prefix=str(source["official_cite_prefix"]),
                    rule_number_max=int(source.get("rule_number_max", 99) or 99),
                )
            )
            > 0,
            timeout_seconds=120,
        )
        if not html:
            continue

        statutes = _extract_new_hampshire_rules_from_online_book_html(
            html,
            source_url=source_url,
            title_name=str(source["title_name"]),
            procedure_family=str(source["procedure_family"]),
            legal_area=str(source["legal_area"]),
            official_cite_prefix=str(source["official_cite_prefix"]),
            rule_number_max=int(source.get("rule_number_max", 99) or 99),
        )
        for statute in statutes:
            if remaining is not None and remaining <= 0:
                break

            if str(statute.source_url or "").strip().lower() in existing_urls:
                continue

            enriched = fetcher._enrich_statute_structure(statute).to_dict()
            family = _classify_procedure_family(enriched) or str(source["procedure_family"])
            enriched["procedure_family"] = family
            supplemental_rules.append(enriched)
            existing_urls.add(str(statute.source_url or "").strip().lower())
            remaining = None if remaining is None else remaining - 1

    return supplemental_rules, fetcher.get_fetch_analytics_snapshot()


async def _scrape_nevada_court_rules_supplement(
    *,
    existing_source_urls: Optional[set[str]] = None,
    max_rules: Optional[int] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    fetcher = _NevadaProcedureRulesSupplementFetcher("NV", US_STATES["NV"])
    existing_urls = {
        str(url or "").strip().lower()
        for url in (existing_source_urls or set())
        if str(url or "").strip()
    }
    remaining = int(max_rules) if max_rules and int(max_rules) > 0 else None
    supplemental_rules: List[Dict[str, Any]] = []

    for source in _NV_RULE_SOURCES:
        if remaining is not None and remaining <= 0:
            break

        source_url = str(source["url"])
        html = await _fetch_html_with_direct_fallback(
            fetcher,
            source_url,
            validator=lambda raw_html: len(
                _extract_nevada_rules_from_html(
                    raw_html,
                    source_url=source_url,
                    title_name=str(source["title_name"]),
                    procedure_family=str(source["procedure_family"]),
                    legal_area=str(source["legal_area"]),
                    official_cite_prefix=str(source["official_cite_prefix"]),
                )
            )
            > 0,
            timeout_seconds=120,
        )
        if not html:
            continue

        statutes = _extract_nevada_rules_from_html(
            html,
            source_url=source_url,
            title_name=str(source["title_name"]),
            procedure_family=str(source["procedure_family"]),
            legal_area=str(source["legal_area"]),
            official_cite_prefix=str(source["official_cite_prefix"]),
        )
        for statute in statutes:
            if remaining is not None and remaining <= 0:
                break

            if str(statute.source_url or "").strip().lower() in existing_urls:
                continue

            enriched = fetcher._enrich_statute_structure(statute).to_dict()
            family = _classify_procedure_family(enriched) or str(source["procedure_family"])
            enriched["procedure_family"] = family
            supplemental_rules.append(enriched)
            existing_urls.add(str(statute.source_url or "").strip().lower())
            remaining = None if remaining is None else remaining - 1

    return supplemental_rules, fetcher.get_fetch_analytics_snapshot()


async def _scrape_connecticut_court_rules_supplement(
    *,
    existing_source_urls: Optional[set[str]] = None,
    max_rules: Optional[int] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    fetcher = _ConnecticutProcedureRulesSupplementFetcher("CT", US_STATES["CT"])
    existing_urls = {
        str(url or "").strip().lower()
        for url in (existing_source_urls or set())
        if str(url or "").strip()
    }
    remaining = int(max_rules) if max_rules and int(max_rules) > 0 else None
    supplemental_rules: List[Dict[str, Any]] = []

    raw_bytes = await _fetch_pdf_bytes_with_direct_fallback(
        fetcher,
        _CT_PRACTICE_BOOK_URL,
        timeout_seconds=180,
    )
    if not raw_bytes:
        return supplemental_rules, fetcher.get_fetch_analytics_snapshot()

    try:
        from pypdf import PdfReader
    except ImportError:
        return supplemental_rules, fetcher.get_fetch_analytics_snapshot()

    reader = PdfReader(BytesIO(raw_bytes))
    page_texts = [(index + 1, page.extract_text() or "") for index, page in enumerate(reader.pages)]
    statutes = _extract_connecticut_rules_from_page_texts(
        page_texts,
        source_url=_CT_PRACTICE_BOOK_URL,
    )

    for statute in statutes:
        if remaining is not None and remaining <= 0:
            break

        source_key = str(statute.source_url or "").strip().lower()
        if source_key in existing_urls:
            continue

        enriched = fetcher._enrich_statute_structure(statute).to_dict()
        family = _classify_procedure_family(enriched) or str(
            statute.structured_data.get("procedure_family") or ""
        ).strip()
        if not family:
            continue
        enriched["procedure_family"] = family
        supplemental_rules.append(enriched)
        existing_urls.add(source_key)
        remaining = None if remaining is None else remaining - 1

    return supplemental_rules, fetcher.get_fetch_analytics_snapshot()


async def _scrape_idaho_court_rules_supplement(
    *,
    existing_source_urls: Optional[set[str]] = None,
    max_rules: Optional[int] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    fetcher = _IdahoProcedureRulesSupplementFetcher("ID", US_STATES["ID"])
    existing_urls = {
        str(url or "").strip().lower()
        for url in (existing_source_urls or set())
        if str(url or "").strip()
    }
    remaining = int(max_rules) if max_rules and int(max_rules) > 0 else None
    supplemental_rules: List[Dict[str, Any]] = []

    for list_page in _ID_RULE_LIST_PAGES:
        if remaining is not None and remaining <= 0:
            break

        list_url = str(list_page["url"])
        list_html = await _fetch_html_with_direct_fallback(
            fetcher,
            list_url,
            validator=lambda html: len(
                _extract_idaho_rule_links(
                    html,
                    page_url=list_url,
                    procedure_family=str(list_page["procedure_family"]),
                    legal_area=str(list_page["legal_area"]),
                    official_cite_prefix=str(list_page["official_cite_prefix"]),
                )
            )
            > 0,
            timeout_seconds=120,
        )
        if not list_html:
            continue

        rule_links = _extract_idaho_rule_links(
            list_html,
            page_url=list_url,
            procedure_family=str(list_page["procedure_family"]),
            legal_area=str(list_page["legal_area"]),
            official_cite_prefix=str(list_page["official_cite_prefix"]),
        )
        for rule in rule_links:
            if remaining is not None and remaining <= 0:
                break

            rule_url = str(rule["url"])
            if rule_url.lower() in existing_urls:
                continue

            rule_html = await _fetch_html_with_direct_fallback(
                fetcher,
                rule_url,
                validator=lambda html: _extract_idaho_rule_from_html(
                    html,
                    rule_url=rule_url,
                    title_name=str(list_page["title_name"]),
                    procedure_family=str(rule["procedure_family"]),
                    legal_area=str(rule["legal_area"]),
                    official_cite_prefix=str(rule["official_cite_prefix"]),
                )
                is not None,
                timeout_seconds=120,
            )
            if not rule_html:
                continue

            statute = _extract_idaho_rule_from_html(
                rule_html,
                rule_url=rule_url,
                title_name=str(list_page["title_name"]),
                procedure_family=str(rule["procedure_family"]),
                legal_area=str(rule["legal_area"]),
                official_cite_prefix=str(rule["official_cite_prefix"]),
            )
            if statute is None:
                continue

            enriched = fetcher._enrich_statute_structure(statute).to_dict()
            enriched["procedure_family"] = str(rule["procedure_family"])
            supplemental_rules.append(enriched)
            existing_urls.add(rule_url.lower())
            remaining = None if remaining is None else remaining - 1

    return supplemental_rules, fetcher.get_fetch_analytics_snapshot()


async def _scrape_maine_court_rules_supplement(
    *,
    existing_source_urls: Optional[set[str]] = None,
    max_rules: Optional[int] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    fetcher = _MaineProcedureRulesSupplementFetcher("ME", US_STATES["ME"])
    existing_urls = {
        str(url or "").strip().lower()
        for url in (existing_source_urls or set())
        if str(url or "").strip()
    }
    remaining = int(max_rules) if max_rules and int(max_rules) > 0 else None
    supplemental_rules: List[Dict[str, Any]] = []

    civil_html = await _fetch_html_with_direct_fallback(
        fetcher,
        _ME_CIVIL_RULES_INDEX_URL,
        validator=lambda html: len(_extract_maine_civil_rule_links(html, index_url=_ME_CIVIL_RULES_INDEX_URL)[0]) > 0,
        timeout_seconds=120,
    )
    if civil_html:
        civil_links, reviewed_date, amendments_effective = _extract_maine_civil_rule_links(
            civil_html,
            index_url=_ME_CIVIL_RULES_INDEX_URL,
        )
        for rule in civil_links:
            if remaining is not None and remaining <= 0:
                break
            rule_url = str(rule["url"])
            if rule_url.lower() in existing_urls:
                continue
            raw_bytes = await _fetch_pdf_bytes_with_direct_fallback(
                fetcher,
                rule_url,
                timeout_seconds=180,
            )
            if not raw_bytes:
                continue
            extracted = await fetcher._extract_text_from_document_bytes(
                source_url=rule_url,
                raw_bytes=raw_bytes,
            )
            if not isinstance(extracted, dict):
                continue
            statute = _extract_maine_civil_rule_from_text(
                str(extracted.get("text") or ""),
                source_url=rule_url,
                section_number=str(rule["section_number"]),
                section_name=str(rule["section_name"]),
                reviewed_date=reviewed_date,
                amendments_effective=amendments_effective,
            )
            if statute is None:
                continue
            enriched = fetcher._enrich_statute_structure(statute).to_dict()
            enriched["procedure_family"] = "civil_procedure"
            supplemental_rules.append(enriched)
            existing_urls.add(rule_url.lower())
            remaining = None if remaining is None else remaining - 1

    if remaining is None or remaining > 0:
        raw_bytes = await _fetch_pdf_bytes_with_direct_fallback(
            fetcher,
            _ME_CRIMINAL_RULES_ONLY_URL,
            timeout_seconds=180,
        )
        if raw_bytes:
            try:
                from pypdf import PdfReader
                reader = PdfReader(BytesIO(raw_bytes))
            except Exception:
                reader = None
            if reader is not None:
                page_texts = [(index + 1, page.extract_text() or "") for index, page in enumerate(reader.pages)]
                statutes = _extract_maine_criminal_rules_from_page_texts(
                    page_texts,
                    source_url=_ME_CRIMINAL_RULES_ONLY_URL,
                )
                for statute in statutes:
                    if remaining is not None and remaining <= 0:
                        break
                    source_key = str(statute.source_url or "").strip().lower()
                    if source_key in existing_urls:
                        continue
                    enriched = fetcher._enrich_statute_structure(statute).to_dict()
                    enriched["procedure_family"] = "criminal_procedure"
                    supplemental_rules.append(enriched)
                    existing_urls.add(source_key)
                    remaining = None if remaining is None else remaining - 1

    return supplemental_rules, fetcher.get_fetch_analytics_snapshot()


async def _scrape_maryland_court_rules_supplement(
    *,
    existing_source_urls: Optional[set[str]] = None,
    max_rules: Optional[int] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    fetcher = _MarylandProcedureRulesSupplementFetcher("MD", US_STATES["MD"])
    existing_urls = {
        str(url or "").strip().lower()
        for url in (existing_source_urls or set())
        if str(url or "").strip()
    }
    remaining = int(max_rules) if max_rules and int(max_rules) > 0 else None
    supplemental_rules: List[Dict[str, Any]] = []

    for title in _MD_RULE_TITLES:
        if remaining is not None and remaining <= 0:
            break

        title_url = str(title["url"])
        title_html = await _fetch_html_with_direct_fallback(
            fetcher,
            title_url,
            validator=lambda html: len(
                _extract_maryland_chapter_links(
                    html,
                    page_url=title_url,
                    procedure_family=str(title["procedure_family"]),
                    legal_area=str(title["legal_area"]),
                )
            )
            > 0,
            timeout_seconds=120,
        )
        if not title_html:
            continue

        chapter_links = _extract_maryland_chapter_links(
            title_html,
            page_url=title_url,
            procedure_family=str(title["procedure_family"]),
            legal_area=str(title["legal_area"]),
        )
        for chapter in chapter_links:
            if remaining is not None and remaining <= 0:
                break

            chapter_url = str(chapter["url"])
            chapter_html = await _fetch_html_with_direct_fallback(
                fetcher,
                chapter_url,
                validator=lambda html: len(
                    _extract_maryland_rule_links(
                        html,
                        page_url=chapter_url,
                        title_name=str(title["title_name"]),
                        chapter_name=str(chapter["chapter_name"]),
                        procedure_family=str(chapter["procedure_family"]),
                        legal_area=str(chapter["legal_area"]),
                    )
                )
                > 0,
                timeout_seconds=120,
            )
            if not chapter_html:
                continue

            rule_links = _extract_maryland_rule_links(
                chapter_html,
                page_url=chapter_url,
                title_name=str(title["title_name"]),
                chapter_name=str(chapter["chapter_name"]),
                procedure_family=str(chapter["procedure_family"]),
                legal_area=str(chapter["legal_area"]),
            )
            for rule in rule_links:
                if remaining is not None and remaining <= 0:
                    break

                rule_url = str(rule["url"])
                if rule_url.lower() in existing_urls:
                    continue

                rule_html = await _fetch_html_with_direct_fallback(
                    fetcher,
                    rule_url,
                    validator=lambda html: _extract_maryland_rule_from_html(
                        html,
                        rule_url=rule_url,
                        title_name=str(rule["title_name"]),
                        chapter_name=str(rule["chapter_name"]),
                        procedure_family=str(rule["procedure_family"]),
                        legal_area=str(rule["legal_area"]),
                    )
                    is not None,
                    timeout_seconds=120,
                )
                if not rule_html:
                    continue

                statute = _extract_maryland_rule_from_html(
                    rule_html,
                    rule_url=rule_url,
                    title_name=str(rule["title_name"]),
                    chapter_name=str(rule["chapter_name"]),
                    procedure_family=str(rule["procedure_family"]),
                    legal_area=str(rule["legal_area"]),
                )
                if statute is None:
                    continue

                enriched = fetcher._enrich_statute_structure(statute).to_dict()
                family = _classify_procedure_family(enriched) or str(rule["procedure_family"])
                enriched["procedure_family"] = family
                supplemental_rules.append(enriched)
                existing_urls.add(rule_url.lower())
                remaining = None if remaining is None else remaining - 1

    return supplemental_rules, fetcher.get_fetch_analytics_snapshot()


async def _scrape_south_carolina_court_rules_supplement(
    *,
    existing_source_urls: Optional[set[str]] = None,
    max_rules: Optional[int] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    fetcher = _SouthCarolinaProcedureRulesSupplementFetcher("SC", US_STATES["SC"])
    existing_urls = {
        str(url or "").strip().lower()
        for url in (existing_source_urls or set())
        if str(url or "").strip()
    }
    remaining = int(max_rules) if max_rules and int(max_rules) > 0 else None
    supplemental_rules: List[Dict[str, Any]] = []

    for list_page in _SC_RULE_LIST_PAGES:
        if remaining is not None and remaining <= 0:
            break

        list_url = str(list_page["url"])
        list_html = await _fetch_html_with_direct_fallback(
            fetcher,
            list_url,
            validator=lambda html: len(
                _extract_south_carolina_rule_links(
                    html,
                    page_url=list_url,
                    procedure_family=str(list_page["procedure_family"]),
                    legal_area=str(list_page["legal_area"]),
                    official_cite_prefix=str(list_page["official_cite_prefix"]),
                )
            )
            > 0,
            timeout_seconds=120,
        )
        if not list_html:
            continue

        rule_links = _extract_south_carolina_rule_links(
            list_html,
            page_url=list_url,
            procedure_family=str(list_page["procedure_family"]),
            legal_area=str(list_page["legal_area"]),
            official_cite_prefix=str(list_page["official_cite_prefix"]),
        )
        for rule in rule_links:
            if remaining is not None and remaining <= 0:
                break

            rule_url = str(rule["url"])
            if rule_url.lower() in existing_urls:
                continue

            rule_html = await _fetch_html_with_direct_fallback(
                fetcher,
                rule_url,
                validator=lambda html: _extract_south_carolina_rule_from_html(
                    html,
                    rule_url=rule_url,
                    title_name=str(list_page["title_name"]),
                    procedure_family=str(rule["procedure_family"]),
                    legal_area=str(rule["legal_area"]),
                    official_cite_prefix=str(rule["official_cite_prefix"]),
                )
                is not None,
                timeout_seconds=120,
            )
            if not rule_html:
                continue

            statute = _extract_south_carolina_rule_from_html(
                rule_html,
                rule_url=rule_url,
                title_name=str(list_page["title_name"]),
                procedure_family=str(rule["procedure_family"]),
                legal_area=str(rule["legal_area"]),
                official_cite_prefix=str(rule["official_cite_prefix"]),
            )
            if statute is None:
                continue

            enriched = fetcher._enrich_statute_structure(statute).to_dict()
            family = _classify_procedure_family(enriched) or str(rule["procedure_family"])
            enriched["procedure_family"] = family
            supplemental_rules.append(enriched)
            existing_urls.add(rule_url.lower())
            remaining = None if remaining is None else remaining - 1

    return supplemental_rules, fetcher.get_fetch_analytics_snapshot()


async def _scrape_alaska_court_rules_supplement(
    *,
    existing_source_urls: Optional[set[str]] = None,
    max_rules: Optional[int] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    fetcher = _AlaskaProcedureRulesSupplementFetcher("AK", US_STATES["AK"])
    existing_urls = {
        str(url or "").strip().lower()
        for url in (existing_source_urls or set())
        if str(url or "").strip()
    }
    remaining = int(max_rules) if max_rules and int(max_rules) > 0 else None
    supplemental_rules: List[Dict[str, Any]] = []

    for document in _AK_RULE_DOCUMENTS:
        if remaining is not None and remaining <= 0:
            break

        raw_bytes = await _fetch_pdf_bytes_with_direct_fallback(
            fetcher,
            str(document["url"]),
            timeout_seconds=180,
        )
        if not raw_bytes:
            continue

        try:
            from pypdf import PdfReader

            reader = PdfReader(BytesIO(raw_bytes))
            page_texts = [page.extract_text() or "" for page in reader.pages]
        except Exception:
            page_texts = []

        statutes = _extract_alaska_rules_from_page_texts(
            page_texts,
            source_url=str(document["url"]),
            title_name=str(document["title_name"]),
            procedure_family=str(document["procedure_family"]),
            legal_area=str(document["legal_area"]),
            official_cite_prefix=str(document["official_cite_prefix"]),
        )
        for statute in statutes:
            if remaining is not None and remaining <= 0:
                break
            source_key = str(statute.source_url or "").strip().lower()
            if source_key in existing_urls:
                continue
            enriched = fetcher._enrich_statute_structure(statute).to_dict()
            family = _classify_procedure_family(enriched) or str(
                statute.structured_data.get("procedure_family") or ""
            ).strip()
            if not family:
                continue
            enriched["procedure_family"] = family
            supplemental_rules.append(enriched)
            existing_urls.add(source_key)
            remaining = None if remaining is None else remaining - 1

    return supplemental_rules, fetcher.get_fetch_analytics_snapshot()


async def _scrape_nebraska_court_rules_supplement(
    *,
    existing_source_urls: Optional[set[str]] = None,
    max_rules: Optional[int] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    fetcher = _NebraskaProcedureRulesSupplementFetcher("NE", US_STATES["NE"])
    existing_urls = {
        str(url or "").strip().lower()
        for url in (existing_source_urls or set())
        if str(url or "").strip()
    }
    remaining = int(max_rules) if max_rules and int(max_rules) > 0 else None
    supplemental_rules: List[Dict[str, Any]] = []

    for article in _NE_RULE_ARTICLES:
        if remaining is not None and remaining <= 0:
            break

        article_url = str(article["url"])
        article_html = await _fetch_html_with_direct_fallback(
            fetcher,
            article_url,
            validator=lambda html: len(
                _extract_nebraska_rule_links(
                    html,
                    page_url=article_url,
                    procedure_family=str(article["procedure_family"]),
                    legal_area=str(article["legal_area"]),
                    official_cite_prefix=str(article["official_cite_prefix"]),
                )
            )
            > 0,
            timeout_seconds=120,
        )
        if not article_html:
            continue

        rule_links = _extract_nebraska_rule_links(
            article_html,
            page_url=article_url,
            procedure_family=str(article["procedure_family"]),
            legal_area=str(article["legal_area"]),
            official_cite_prefix=str(article["official_cite_prefix"]),
        )
        for rule in rule_links:
            if remaining is not None and remaining <= 0:
                break

            rule_url = str(rule["url"])
            if rule_url.lower() in existing_urls:
                continue

            rule_html = await _fetch_html_with_direct_fallback(
                fetcher,
                rule_url,
                validator=lambda html: _extract_nebraska_rule_from_html(
                    html,
                    rule_url=rule_url,
                    title_name=str(article["title_name"]),
                    section_number=str(rule["section_number"]),
                    section_name=str(rule["section_name"]),
                    procedure_family=str(rule["procedure_family"]),
                    legal_area=str(rule["legal_area"]),
                    official_cite_prefix=str(rule["official_cite_prefix"]),
                )
                is not None,
                timeout_seconds=120,
            )
            if not rule_html:
                continue

            statute = _extract_nebraska_rule_from_html(
                rule_html,
                rule_url=rule_url,
                title_name=str(article["title_name"]),
                section_number=str(rule["section_number"]),
                section_name=str(rule["section_name"]),
                procedure_family=str(rule["procedure_family"]),
                legal_area=str(rule["legal_area"]),
                official_cite_prefix=str(rule["official_cite_prefix"]),
            )
            if statute is None:
                continue

            enriched = fetcher._enrich_statute_structure(statute).to_dict()
            family = _classify_procedure_family(enriched) or str(rule["procedure_family"])
            enriched["procedure_family"] = family
            supplemental_rules.append(enriched)
            existing_urls.add(rule_url.lower())
            remaining = None if remaining is None else remaining - 1

    return supplemental_rules, fetcher.get_fetch_analytics_snapshot()


async def _scrape_hawaii_court_rules_supplement(
    *,
    existing_source_urls: Optional[set[str]] = None,
    max_rules: Optional[int] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    fetcher = _HawaiiProcedureRulesSupplementFetcher("HI", US_STATES["HI"])
    existing_urls = {
        str(url or "").strip().lower()
        for url in (existing_source_urls or set())
        if str(url or "").strip()
    }
    remaining = int(max_rules) if max_rules and int(max_rules) > 0 else None
    supplemental_rules: List[Dict[str, Any]] = []

    for source in _HI_RULE_SOURCES:
        if remaining is not None and remaining <= 0:
            break

        source_url = str(source["url"])
        source_html = await _fetch_html_with_direct_fallback(
            fetcher,
            source_url,
            validator=lambda html: len(
                _extract_hawaii_rules_from_html(
                    html,
                    source_url=source_url,
                    title_name=str(source["title_name"]),
                    procedure_family=str(source["procedure_family"]),
                    legal_area=str(source["legal_area"]),
                    official_cite_prefix=str(source["official_cite_prefix"]),
                    effective_date=str(source["effective_date"]),
                )
            )
            > 0,
            timeout_seconds=120,
        )
        if not source_html:
            continue

        statutes = _extract_hawaii_rules_from_html(
            source_html,
            source_url=source_url,
            title_name=str(source["title_name"]),
            procedure_family=str(source["procedure_family"]),
            legal_area=str(source["legal_area"]),
            official_cite_prefix=str(source["official_cite_prefix"]),
            effective_date=str(source["effective_date"]),
        )
        for statute in statutes:
            if remaining is not None and remaining <= 0:
                break
            source_key = str(statute.source_url or "").strip().lower()
            if source_key in existing_urls:
                continue
            enriched = fetcher._enrich_statute_structure(statute).to_dict()
            family = _classify_procedure_family(enriched) or str(
                statute.structured_data.get("procedure_family") or ""
            ).strip()
            if not family:
                continue
            enriched["procedure_family"] = family
            supplemental_rules.append(enriched)
            existing_urls.add(source_key)
            remaining = None if remaining is None else remaining - 1

    return supplemental_rules, fetcher.get_fetch_analytics_snapshot()


async def _scrape_utah_court_rules_supplement(
    *,
    existing_source_urls: Optional[set[str]] = None,
    max_rules: Optional[int] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    fetcher = _UtahProcedureRulesSupplementFetcher("UT", US_STATES["UT"])
    existing_urls = {
        str(url or "").strip().lower()
        for url in (existing_source_urls or set())
        if str(url or "").strip()
    }
    remaining = int(max_rules) if max_rules and int(max_rules) > 0 else None
    supplemental_rules: List[Dict[str, Any]] = []

    for list_page in _UT_RULE_LIST_PAGES:
        if remaining is not None and remaining <= 0:
            break

        list_url = str(list_page["url"])
        list_html = await _fetch_html_with_direct_fallback(
            fetcher,
            list_url,
            validator=lambda html: len(
                _extract_utah_rule_links(
                    html,
                    page_url=list_url,
                    procedure_family=str(list_page["procedure_family"]),
                    legal_area=str(list_page["legal_area"]),
                    official_cite_prefix=str(list_page["official_cite_prefix"]),
                    type_code=str(list_page["type_code"]),
                )
            )
            > 0,
            timeout_seconds=120,
        )
        if not list_html:
            continue

        rule_links = _extract_utah_rule_links(
            list_html,
            page_url=list_url,
            procedure_family=str(list_page["procedure_family"]),
            legal_area=str(list_page["legal_area"]),
            official_cite_prefix=str(list_page["official_cite_prefix"]),
            type_code=str(list_page["type_code"]),
        )
        for rule in rule_links:
            if remaining is not None and remaining <= 0:
                break

            rule_url = str(rule["url"])
            if rule_url.lower() in existing_urls:
                continue

            rule_html = await _fetch_html_with_direct_fallback(
                fetcher,
                rule_url,
                validator=lambda html: (
                    "This Rule has been repealed." in html
                    or _extract_utah_rule_from_html(
                        html,
                        rule_url=rule_url,
                        title_name=str(list_page["title_name"]),
                        procedure_family=str(rule["procedure_family"]),
                        legal_area=str(rule["legal_area"]),
                        official_cite_prefix=str(rule["official_cite_prefix"]),
                    )
                    is not None
                ),
                timeout_seconds=120,
            )
            if not rule_html:
                continue

            statute = _extract_utah_rule_from_html(
                rule_html,
                rule_url=rule_url,
                title_name=str(list_page["title_name"]),
                procedure_family=str(rule["procedure_family"]),
                legal_area=str(rule["legal_area"]),
                official_cite_prefix=str(rule["official_cite_prefix"]),
            )
            if statute is None:
                continue

            enriched = fetcher._enrich_statute_structure(statute).to_dict()
            family = _classify_procedure_family(enriched) or str(rule["procedure_family"])
            enriched["procedure_family"] = family
            supplemental_rules.append(enriched)
            existing_urls.add(rule_url.lower())
            remaining = None if remaining is None else remaining - 1

    return supplemental_rules, fetcher.get_fetch_analytics_snapshot()


async def _scrape_new_mexico_court_rules_supplement(
    *,
    existing_source_urls: Optional[set[str]] = None,
    max_rules: Optional[int] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    fetcher = _NewMexicoProcedureRulesSupplementFetcher("NM", US_STATES["NM"])
    existing_urls = {
        str(url or "").strip().lower()
        for url in (existing_source_urls or set())
        if str(url or "").strip()
    }
    remaining = int(max_rules) if max_rules and int(max_rules) > 0 else None
    supplemental_rules: List[Dict[str, Any]] = []

    for document in _NM_RULE_DOCUMENTS:
        if remaining is not None and remaining <= 0:
            break

        raw_bytes = await _fetch_pdf_bytes_with_direct_fallback(
            fetcher,
            str(document["url"]),
            timeout_seconds=180,
        )
        if not raw_bytes:
            continue

        try:
            from pypdf import PdfReader

            reader = PdfReader(BytesIO(raw_bytes))
        except Exception:
            continue

        parse_limit = remaining
        page_texts: List[tuple[int, str]] = []
        for index, page in enumerate(reader.pages):
            page_texts.append((index + 1, page.extract_text() or ""))
            if parse_limit is not None and index >= 79:
                trial_statutes = _extract_new_mexico_rules_from_page_texts(
                    page_texts,
                    source_url=str(document["url"]),
                    title_name=str(document["title_name"]),
                    procedure_family=str(document["procedure_family"]),
                    legal_area=str(document["legal_area"]),
                    official_cite_prefix=str(document["official_cite_prefix"]),
                    first_rule_number=str(document["first_rule_number"]),
                    max_rules=parse_limit,
                )
                if len(trial_statutes) >= parse_limit:
                    break

        statutes = _extract_new_mexico_rules_from_page_texts(
            page_texts,
            source_url=str(document["url"]),
            title_name=str(document["title_name"]),
            procedure_family=str(document["procedure_family"]),
            legal_area=str(document["legal_area"]),
            official_cite_prefix=str(document["official_cite_prefix"]),
            first_rule_number=str(document["first_rule_number"]),
            max_rules=parse_limit,
        )

        for statute in statutes:
            if remaining is not None and remaining <= 0:
                break
            source_key = str(statute.source_url or "").strip().lower()
            if source_key in existing_urls:
                continue
            enriched = fetcher._enrich_statute_structure(statute).to_dict()
            family = _classify_procedure_family(enriched) or str(
                statute.structured_data.get("procedure_family") or ""
            ).strip()
            if not family:
                continue
            enriched["procedure_family"] = family
            supplemental_rules.append(enriched)
            existing_urls.add(source_key)
            remaining = None if remaining is None else remaining - 1

    return supplemental_rules, fetcher.get_fetch_analytics_snapshot()


async def _scrape_west_virginia_court_rules_supplement(
    *,
    existing_source_urls: Optional[set[str]] = None,
    max_rules: Optional[int] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    fetcher = _WestVirginiaProcedureRulesSupplementFetcher("WV", US_STATES["WV"])
    existing_urls = {
        str(url or "").strip().lower()
        for url in (existing_source_urls or set())
        if str(url or "").strip()
    }
    remaining = int(max_rules) if max_rules and int(max_rules) > 0 else None
    supplemental_rules: List[Dict[str, Any]] = []

    for source in _WV_RULE_SOURCES:
        if remaining is not None and remaining <= 0:
            break

        source_url = str(source["url"])
        source_kind = str(source["source_kind"])
        statutes: List[NormalizedStatute] = []

        if source_kind == "pdf":
            raw_bytes = await _fetch_pdf_bytes_with_direct_fallback(
                fetcher,
                source_url,
                timeout_seconds=180,
            )
            if not raw_bytes:
                continue
            try:
                from pypdf import PdfReader

                reader = PdfReader(BytesIO(raw_bytes))
            except Exception:
                continue
            page_texts = [(index + 1, page.extract_text() or "") for index, page in enumerate(reader.pages)]
            statutes = _extract_west_virginia_civil_rules_from_page_texts(
                page_texts,
                source_url=source_url,
                title_name=str(source["title_name"]),
                procedure_family=str(source["procedure_family"]),
                legal_area=str(source["legal_area"]),
                official_cite_prefix=str(source["official_cite_prefix"]),
            )
        else:
            html_text = await _fetch_html_with_direct_fallback(
                fetcher,
                source_url,
                validator=lambda html: len(
                    _extract_west_virginia_criminal_rules_from_html(
                        html,
                        source_url=source_url,
                        title_name=str(source["title_name"]),
                        procedure_family=str(source["procedure_family"]),
                        legal_area=str(source["legal_area"]),
                        official_cite_prefix=str(source["official_cite_prefix"]),
                    )
                )
                > 0,
                timeout_seconds=120,
            )
            if not html_text:
                continue
            statutes = _extract_west_virginia_criminal_rules_from_html(
                html_text,
                source_url=source_url,
                title_name=str(source["title_name"]),
                procedure_family=str(source["procedure_family"]),
                legal_area=str(source["legal_area"]),
                official_cite_prefix=str(source["official_cite_prefix"]),
            )

        for statute in statutes:
            if remaining is not None and remaining <= 0:
                break
            source_key = str(statute.source_url or "").strip().lower()
            if source_key in existing_urls:
                continue
            enriched = fetcher._enrich_statute_structure(statute).to_dict()
            family = _classify_procedure_family(enriched) or str(
                statute.structured_data.get("procedure_family") or ""
            ).strip()
            if not family:
                continue
            enriched["procedure_family"] = family
            supplemental_rules.append(enriched)
            existing_urls.add(source_key)
            remaining = None if remaining is None else remaining - 1

    return supplemental_rules, fetcher.get_fetch_analytics_snapshot()


async def _scrape_north_dakota_court_rules_supplement(
    *,
    existing_source_urls: Optional[set[str]] = None,
    max_rules: Optional[int] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    fetcher = _NorthDakotaProcedureRulesSupplementFetcher("ND", US_STATES["ND"])
    existing_urls = {
        str(url or "").strip().lower()
        for url in (existing_source_urls or set())
        if str(url or "").strip()
    }
    remaining = int(max_rules) if max_rules and int(max_rules) > 0 else None
    supplemental_rules: List[Dict[str, Any]] = []

    for list_page in _ND_RULE_LIST_PAGES:
        if remaining is not None and remaining <= 0:
            break

        list_url = str(list_page["url"])
        list_html = await _fetch_html_with_direct_fallback(
            fetcher,
            list_url,
            validator=lambda html: len(
                _extract_north_dakota_rule_links(
                    html,
                    page_url=list_url,
                    procedure_family=str(list_page["procedure_family"]),
                    legal_area=str(list_page["legal_area"]),
                    official_cite_prefix=str(list_page["official_cite_prefix"]),
                )
            )
            > 0,
            timeout_seconds=120,
        )
        if not list_html:
            continue

        rule_links = _extract_north_dakota_rule_links(
            list_html,
            page_url=list_url,
            procedure_family=str(list_page["procedure_family"]),
            legal_area=str(list_page["legal_area"]),
            official_cite_prefix=str(list_page["official_cite_prefix"]),
        )
        for rule in rule_links:
            if remaining is not None and remaining <= 0:
                break
            rule_url = str(rule["url"])
            if rule_url.lower() in existing_urls:
                continue

            rule_html = await _fetch_html_with_direct_fallback(
                fetcher,
                rule_url,
                validator=lambda html: _extract_north_dakota_rule_from_html(
                    html,
                    rule_url=rule_url,
                    title_name=str(list_page["title_name"]),
                    procedure_family=str(rule["procedure_family"]),
                    legal_area=str(rule["legal_area"]),
                    official_cite_prefix=str(rule["official_cite_prefix"]),
                )
                is not None,
                timeout_seconds=120,
            )
            if not rule_html:
                continue

            statute = _extract_north_dakota_rule_from_html(
                rule_html,
                rule_url=rule_url,
                title_name=str(list_page["title_name"]),
                procedure_family=str(rule["procedure_family"]),
                legal_area=str(rule["legal_area"]),
                official_cite_prefix=str(rule["official_cite_prefix"]),
            )
            if statute is None:
                continue

            enriched = fetcher._enrich_statute_structure(statute).to_dict()
            family = _classify_procedure_family(enriched) or str(rule["procedure_family"])
            enriched["procedure_family"] = family
            supplemental_rules.append(enriched)
            existing_urls.add(rule_url.lower())
            remaining = None if remaining is None else remaining - 1

    return supplemental_rules, fetcher.get_fetch_analytics_snapshot()


async def _scrape_minnesota_court_rules_supplement(
    *,
    existing_source_urls: Optional[set[str]] = None,
    max_rules: Optional[int] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    fetcher = _MinnesotaProcedureRulesSupplementFetcher("MN", US_STATES["MN"])
    existing_urls = {
        str(url or "").strip().lower()
        for url in (existing_source_urls or set())
        if str(url or "").strip()
    }
    remaining = int(max_rules) if max_rules and int(max_rules) > 0 else None
    supplemental_rules: List[Dict[str, Any]] = []

    for list_page in _MN_RULE_LIST_PAGES:
        if remaining is not None and remaining <= 0:
            break
        list_url = str(list_page["url"])
        list_html = await _fetch_html_with_direct_fallback(
            fetcher,
            list_url,
            validator=lambda html: len(
                _extract_minnesota_rule_links(
                    html,
                    page_url=list_url,
                    procedure_family=str(list_page["procedure_family"]),
                    legal_area=str(list_page["legal_area"]),
                    official_cite_prefix=str(list_page["official_cite_prefix"]),
                )
            )
            > 0,
            timeout_seconds=120,
        )
        if not list_html:
            continue

        rule_links = _extract_minnesota_rule_links(
            list_html,
            page_url=list_url,
            procedure_family=str(list_page["procedure_family"]),
            legal_area=str(list_page["legal_area"]),
            official_cite_prefix=str(list_page["official_cite_prefix"]),
        )
        for rule in rule_links:
            if remaining is not None and remaining <= 0:
                break
            rule_url = str(rule["url"])
            if rule_url.lower() in existing_urls:
                continue

            rule_html = await _fetch_html_with_direct_fallback(
                fetcher,
                rule_url,
                validator=lambda html: _extract_minnesota_rule_from_html(
                    html,
                    rule_url=rule_url,
                    title_name=str(list_page["title_name"]),
                    procedure_family=str(rule["procedure_family"]),
                    legal_area=str(rule["legal_area"]),
                    official_cite_prefix=str(rule["official_cite_prefix"]),
                )
                is not None,
                timeout_seconds=120,
            )
            if not rule_html:
                continue

            statute = _extract_minnesota_rule_from_html(
                rule_html,
                rule_url=rule_url,
                title_name=str(list_page["title_name"]),
                procedure_family=str(rule["procedure_family"]),
                legal_area=str(rule["legal_area"]),
                official_cite_prefix=str(rule["official_cite_prefix"]),
            )
            if statute is None:
                continue

            enriched = fetcher._enrich_statute_structure(statute).to_dict()
            family = _classify_procedure_family(enriched) or str(rule["procedure_family"])
            enriched["procedure_family"] = family
            supplemental_rules.append(enriched)
            existing_urls.add(rule_url.lower())
            remaining = None if remaining is None else remaining - 1

    return supplemental_rules, fetcher.get_fetch_analytics_snapshot()


async def _scrape_iowa_court_rules_supplement(
    *,
    existing_source_urls: Optional[set[str]] = None,
    max_rules: Optional[int] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    fetcher = _IowaProcedureRulesSupplementFetcher("IA", US_STATES["IA"])
    existing_urls = {
        str(url or "").strip().lower()
        for url in (existing_source_urls or set())
        if str(url or "").strip()
    }
    remaining = int(max_rules) if max_rules and int(max_rules) > 0 else None
    supplemental_rules: List[Dict[str, Any]] = []

    for source in _IA_RULE_DOCUMENTS:
        if remaining is not None and remaining <= 0:
            break
        source_url = str(source["url"])
        raw_bytes = await _fetch_pdf_bytes_with_direct_fallback(fetcher, source_url)
        if not raw_bytes:
            continue

        try:
            from pypdf import PdfReader

            reader = PdfReader(BytesIO(raw_bytes))
            page_texts = [(index + 1, page.extract_text() or "") for index, page in enumerate(reader.pages)]
        except Exception:
            extracted = await fetcher._extract_text_from_document_bytes(
                raw_bytes,
                source_url=source_url,
                content_type="application/pdf",
            )
            if not extracted:
                continue
            page_texts = [(index + 1, page) for index, page in enumerate(extracted.pages)]

        statutes = _extract_iowa_rules_from_page_texts(
            page_texts,
            source_url=source_url,
            title_name=str(source["title_name"]),
            procedure_family=str(source["procedure_family"]),
            legal_area=str(source["legal_area"]),
            official_cite_prefix=str(source["official_cite_prefix"]),
            first_rule_number=str(source["first_rule_number"]),
            max_rules=remaining,
        )
        for statute in statutes:
            if remaining is not None and remaining <= 0:
                break
            source_key = str(statute.source_url or "").strip().lower()
            if source_key in existing_urls:
                continue
            enriched = fetcher._enrich_statute_structure(statute).to_dict()
            family = _classify_procedure_family(enriched) or str(
                statute.structured_data.get("procedure_family") or ""
            ).strip()
            if not family:
                continue
            enriched["procedure_family"] = family
            supplemental_rules.append(enriched)
            existing_urls.add(source_key)
            remaining = None if remaining is None else remaining - 1

    return supplemental_rules, fetcher.get_fetch_analytics_snapshot()


async def _scrape_arkansas_court_rules_supplement(
    *,
    existing_source_urls: Optional[set[str]] = None,
    max_rules: Optional[int] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    fetcher = _ArkansasProcedureRulesSupplementFetcher("AR", US_STATES["AR"])
    existing_urls = {
        str(url or "").strip().lower()
        for url in (existing_source_urls or set())
        if str(url or "").strip()
    }
    remaining = int(max_rules) if max_rules and int(max_rules) > 0 else None
    supplemental_rules: List[Dict[str, Any]] = []

    for source in _AR_RULE_DOCUMENTS:
        if remaining is not None and remaining <= 0:
            break
        source_url = str(source["url"])
        raw_bytes = await _fetch_pdf_bytes_with_direct_fallback(fetcher, source_url)
        if not raw_bytes:
            continue

        try:
            from pypdf import PdfReader

            reader = PdfReader(BytesIO(raw_bytes))
            page_texts = [(index + 1, page.extract_text() or "") for index, page in enumerate(reader.pages)]
        except Exception:
            extracted = await fetcher._extract_text_from_document_bytes(
                raw_bytes,
                source_url=source_url,
                content_type="application/pdf",
            )
            if not extracted:
                continue
            page_texts = [(index + 1, page) for index, page in enumerate(extracted.pages)]

        statutes = _extract_arkansas_rules_from_page_texts(
            page_texts,
            source_url=source_url,
            title_name=str(source["title_name"]),
            procedure_family=str(source["procedure_family"]),
            legal_area=str(source["legal_area"]),
            official_cite_prefix=str(source["official_cite_prefix"]),
            first_rule_number=str(source["first_rule_number"]),
            max_rules=remaining,
        )
        for statute in statutes:
            if remaining is not None and remaining <= 0:
                break
            source_key = str(statute.source_url or "").strip().lower()
            if source_key in existing_urls:
                continue
            enriched = fetcher._enrich_statute_structure(statute).to_dict()
            family = _classify_procedure_family(enriched) or str(
                statute.structured_data.get("procedure_family") or ""
            ).strip()
            if not family:
                continue
            enriched["procedure_family"] = family
            supplemental_rules.append(enriched)
            existing_urls.add(source_key)
            remaining = None if remaining is None else remaining - 1

    return supplemental_rules, fetcher.get_fetch_analytics_snapshot()


async def _scrape_alabama_court_rules_supplement(
    *,
    existing_source_urls: Optional[set[str]] = None,
    max_rules: Optional[int] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    fetcher = _AlabamaProcedureRulesSupplementFetcher("AL", US_STATES["AL"])
    existing_urls = {
        str(url or "").strip().lower()
        for url in (existing_source_urls or set())
        if str(url or "").strip()
    }
    remaining = int(max_rules) if max_rules and int(max_rules) > 0 else None
    supplemental_rules: List[Dict[str, Any]] = []

    for list_page in _AL_RULE_LIST_PAGES:
        if remaining is not None and remaining <= 0:
            break
        list_url = str(list_page["url"])
        list_html = await _fetch_html_with_direct_fallback(
            fetcher,
            list_url,
            validator=lambda html: len(
                _extract_alabama_rule_links(
                    html,
                    page_url=list_url,
                    procedure_family=str(list_page["procedure_family"]),
                    legal_area=str(list_page["legal_area"]),
                    official_cite_prefix=str(list_page["official_cite_prefix"]),
                    url_prefix=str(list_page["url_prefix"]),
                )
            )
            > 0,
            timeout_seconds=120,
        )
        if not list_html:
            continue

        rule_links = _extract_alabama_rule_links(
            list_html,
            page_url=list_url,
            procedure_family=str(list_page["procedure_family"]),
            legal_area=str(list_page["legal_area"]),
            official_cite_prefix=str(list_page["official_cite_prefix"]),
            url_prefix=str(list_page["url_prefix"]),
        )
        for rule in rule_links:
            if remaining is not None and remaining <= 0:
                break
            rule_url = str(rule["url"])
            if rule_url.lower() in existing_urls:
                continue

            raw_bytes = await _fetch_pdf_bytes_with_direct_fallback(fetcher, rule_url)
            if not raw_bytes:
                continue
            try:
                from pypdf import PdfReader

                reader = PdfReader(BytesIO(raw_bytes))
                text = "\n".join(str(page.extract_text() or "") for page in reader.pages)
            except Exception:
                extracted = await fetcher._extract_text_from_document_bytes(
                    source_url=rule_url,
                    raw_bytes=raw_bytes,
                )
                if not isinstance(extracted, dict):
                    continue
                text = str(extracted.get("text") or "")
            statute = _extract_alabama_rule_from_text(
                text,
                source_url=rule_url,
                title_name=str(list_page["title_name"]),
                section_number=str(rule["section_number"]),
                official_cite_prefix=str(rule["official_cite_prefix"]),
                procedure_family=str(rule["procedure_family"]),
                legal_area=str(rule["legal_area"]),
            )
            if statute is None:
                continue

            enriched = fetcher._enrich_statute_structure(statute).to_dict()
            family = _classify_procedure_family(enriched) or str(rule["procedure_family"])
            enriched["procedure_family"] = family
            supplemental_rules.append(enriched)
            existing_urls.add(rule_url.lower())
            remaining = None if remaining is None else remaining - 1

    return supplemental_rules, fetcher.get_fetch_analytics_snapshot()


async def _scrape_tennessee_court_rules_supplement(
    *,
    existing_source_urls: Optional[set[str]] = None,
    max_rules: Optional[int] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    fetcher = _TennesseeProcedureRulesSupplementFetcher("TN", US_STATES["TN"])
    existing_urls = {
        str(url or "").strip().lower()
        for url in (existing_source_urls or set())
        if str(url or "").strip()
    }
    remaining = int(max_rules) if max_rules and int(max_rules) > 0 else None
    supplemental_rules: List[Dict[str, Any]] = []

    for list_page in _TN_RULE_LIST_PAGES:
        if remaining is not None and remaining <= 0:
            break

        list_url = str(list_page["url"])
        list_html = await _fetch_html_with_direct_fallback(
            fetcher,
            list_url,
            validator=lambda html: len(
                _extract_tennessee_rule_links(
                    html,
                    page_url=list_url,
                    procedure_family=str(list_page["procedure_family"]),
                    legal_area=str(list_page["legal_area"]),
                    official_cite_prefix=str(list_page["official_cite_prefix"]),
                )
            )
            > 0,
            timeout_seconds=120,
        )
        if not list_html:
            continue

        rule_links = _extract_tennessee_rule_links(
            list_html,
            page_url=list_url,
            procedure_family=str(list_page["procedure_family"]),
            legal_area=str(list_page["legal_area"]),
            official_cite_prefix=str(list_page["official_cite_prefix"]),
        )
        for rule in rule_links:
            if remaining is not None and remaining <= 0:
                break

            rule_url = str(rule["url"])
            if rule_url.lower() in existing_urls:
                continue

            rule_html = await _fetch_html_with_direct_fallback(
                fetcher,
                rule_url,
                validator=lambda html: _extract_tennessee_rule_from_html(
                    html,
                    rule_url=rule_url,
                    title_name=str(list_page["title_name"]),
                    procedure_family=str(rule["procedure_family"]),
                    legal_area=str(rule["legal_area"]),
                    official_cite_prefix=str(rule["official_cite_prefix"]),
                )
                is not None,
                timeout_seconds=120,
            )
            if not rule_html:
                continue

            statute = _extract_tennessee_rule_from_html(
                rule_html,
                rule_url=rule_url,
                title_name=str(list_page["title_name"]),
                procedure_family=str(rule["procedure_family"]),
                legal_area=str(rule["legal_area"]),
                official_cite_prefix=str(rule["official_cite_prefix"]),
            )
            if statute is None:
                continue

            enriched = fetcher._enrich_statute_structure(statute).to_dict()
            family = _classify_procedure_family(enriched) or str(rule["procedure_family"])
            enriched["procedure_family"] = family
            supplemental_rules.append(enriched)
            existing_urls.add(rule_url.lower())
            remaining = None if remaining is None else remaining - 1

    return supplemental_rules, fetcher.get_fetch_analytics_snapshot()


async def _scrape_virginia_court_rules_supplement(
    *,
    existing_source_urls: Optional[set[str]] = None,
    max_rules: Optional[int] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    fetcher = _VirginiaProcedureRulesSupplementFetcher("VA", US_STATES["VA"])
    existing_urls = {
        str(url or "").strip().lower()
        for url in (existing_source_urls or set())
        if str(url or "").strip()
    }
    supplemental_rules: List[Dict[str, Any]] = []
    remaining = int(max_rules) if max_rules and int(max_rules) > 0 else None

    raw_bytes = await _fetch_pdf_bytes_with_direct_fallback(
        fetcher,
        _VA_RULES_PDF_URL,
        timeout_seconds=240,
    )
    if not raw_bytes:
        return supplemental_rules, fetcher.get_fetch_analytics_snapshot()

    try:
        from pypdf import PdfReader
    except ImportError:
        return supplemental_rules, fetcher.get_fetch_analytics_snapshot()

    reader = PdfReader(BytesIO(raw_bytes))
    page_texts = [(index + 1, page.extract_text() or "") for index, page in enumerate(reader.pages)]

    for source in _VA_RULE_SOURCES:
        if remaining is not None and remaining <= 0:
            break
        statutes = _extract_virginia_rules_from_page_texts(
            page_texts,
            source_url=_VA_RULES_PDF_URL,
            title_name=str(source["title_name"]),
            procedure_family=str(source["procedure_family"]),
            legal_area=str(source["legal_area"]),
            official_cite_prefix=str(source["official_cite_prefix"]),
            rule_prefix=str(source["rule_prefix"]),
            max_rules=remaining,
        )
        for statute in statutes:
            if remaining is not None and remaining <= 0:
                break
            source_key = str(statute.source_url or "").strip().lower()
            if source_key in existing_urls:
                continue
            enriched = fetcher._enrich_statute_structure(statute).to_dict()
            family = _classify_procedure_family(enriched) or str(source["procedure_family"])
            enriched["procedure_family"] = family
            supplemental_rules.append(enriched)
            existing_urls.add(source_key)
            remaining = None if remaining is None else remaining - 1

    return supplemental_rules, fetcher.get_fetch_analytics_snapshot()


async def _scrape_indiana_court_rules_supplement(
    *,
    existing_source_urls: Optional[set[str]] = None,
    max_rules: Optional[int] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    fetcher = _IndianaProcedureRulesSupplementFetcher("IN", US_STATES["IN"])
    existing_urls = {
        str(url or "").strip().lower()
        for url in (existing_source_urls or set())
        if str(url or "").strip()
    }
    remaining = int(max_rules) if max_rules and int(max_rules) > 0 else None
    supplemental_rules: List[Dict[str, Any]] = []

    for rule_set in _IN_RULE_SET_PAGES:
        if remaining is not None and remaining <= 0:
            break

        list_url = str(rule_set["url"])
        list_html = await _fetch_html_with_direct_fallback(
            fetcher,
            list_url,
            validator=lambda html: len(
                _extract_indiana_rule_links(
                    html,
                    page_url=list_url,
                    procedure_family=str(rule_set["procedure_family"]),
                    legal_area=str(rule_set["legal_area"]),
                    official_cite_prefix=str(rule_set["official_cite_prefix"]),
                )[0]
            )
            > 0,
            timeout_seconds=120,
        )
        if not list_html:
            continue

        rule_links, current_as_of = _extract_indiana_rule_links(
            list_html,
            page_url=list_url,
            procedure_family=str(rule_set["procedure_family"]),
            legal_area=str(rule_set["legal_area"]),
            official_cite_prefix=str(rule_set["official_cite_prefix"]),
        )
        for rule in rule_links:
            if remaining is not None and remaining <= 0:
                break

            rule_url = str(rule["url"])
            if rule_url.lower() in existing_urls:
                continue

            rule_html = await _fetch_html_with_direct_fallback(
                fetcher,
                rule_url,
                validator=lambda html: (
                    lambda statute: statute is not None
                    and str(statute.section_number or "").strip() == str(rule["section_number"])
                )(
                    _extract_indiana_rule_from_html(
                        html,
                        rule_url=rule_url,
                        title_name=str(rule_set["title_name"]),
                        procedure_family=str(rule["procedure_family"]),
                        legal_area=str(rule["legal_area"]),
                        official_cite_prefix=str(rule["official_cite_prefix"]),
                        current_as_of=current_as_of,
                    )
                ),
                timeout_seconds=120,
            )
            if not rule_html:
                continue

            statute = _extract_indiana_rule_from_html(
                rule_html,
                rule_url=rule_url,
                title_name=str(rule_set["title_name"]),
                procedure_family=str(rule["procedure_family"]),
                legal_area=str(rule["legal_area"]),
                official_cite_prefix=str(rule["official_cite_prefix"]),
                current_as_of=current_as_of,
            )
            if statute is None:
                continue
            if str(statute.section_number or "").strip() != str(rule["section_number"]):
                continue

            enriched = fetcher._enrich_statute_structure(statute).to_dict()
            family = _classify_procedure_family(enriched) or str(rule["procedure_family"])
            enriched["procedure_family"] = family
            supplemental_rules.append(enriched)
            existing_urls.add(rule_url.lower())
            remaining = None if remaining is None else remaining - 1

    return supplemental_rules, fetcher.get_fetch_analytics_snapshot()


async def _scrape_illinois_court_rules_supplement(
    *,
    existing_source_urls: Optional[set[str]] = None,
    max_rules: Optional[int] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    fetcher = _IllinoisProcedureRulesSupplementFetcher("IL", US_STATES["IL"])
    existing_urls = {
        str(url or "").strip().lower()
        for url in (existing_source_urls or set())
        if str(url or "").strip()
    }
    remaining = int(max_rules) if max_rules and int(max_rules) > 0 else None
    supplemental_rules: List[Dict[str, Any]] = []

    for rule_set in _IL_RULE_SET_PAGES:
        if remaining is not None and remaining <= 0:
            break
        list_url = str(rule_set["url"])
        list_html = await _fetch_html_with_direct_fallback(
            fetcher,
            list_url,
            validator=lambda html: len(
                _extract_illinois_rule_links(
                    html,
                    page_url=list_url,
                    article_code=str(rule_set["article_code"]),
                    procedure_family=str(rule_set["procedure_family"]),
                    legal_area=str(rule_set["legal_area"]),
                    official_cite_prefix=str(rule_set["official_cite_prefix"]),
                )
            )
            > 0,
            timeout_seconds=120,
        )
        if not list_html:
            continue

        rule_links = _extract_illinois_rule_links(
            list_html,
            page_url=list_url,
            article_code=str(rule_set["article_code"]),
            procedure_family=str(rule_set["procedure_family"]),
            legal_area=str(rule_set["legal_area"]),
            official_cite_prefix=str(rule_set["official_cite_prefix"]),
        )
        for rule in rule_links:
            if remaining is not None and remaining <= 0:
                break
            rule_url = str(rule["url"])
            if rule_url.lower() in existing_urls:
                continue

            raw_bytes = await _fetch_pdf_bytes_with_direct_fallback(fetcher, rule_url)
            if not raw_bytes:
                continue
            try:
                from pypdf import PdfReader

                reader = PdfReader(BytesIO(raw_bytes))
                text = "\n".join(str(page.extract_text() or "") for page in reader.pages)
            except Exception:
                extracted = await fetcher._extract_text_from_document_bytes(
                    source_url=rule_url,
                    raw_bytes=raw_bytes,
                )
                if not isinstance(extracted, dict):
                    continue
                text = str(extracted.get("text") or "")

            statute = _extract_illinois_rule_from_text(
                text,
                source_url=rule_url,
                title_name=str(rule_set["title_name"]),
                section_number=str(rule["section_number"]),
                official_cite_prefix=str(rule["official_cite_prefix"]),
                procedure_family=str(rule["procedure_family"]),
                legal_area=str(rule["legal_area"]),
            )
            if statute is None:
                continue

            enriched = fetcher._enrich_statute_structure(statute).to_dict()
            family = str(rule["procedure_family"])
            enriched["procedure_family"] = family
            structured_data = enriched.get("structured_data")
            if isinstance(structured_data, dict):
                structured_data["procedure_family"] = family
            supplemental_rules.append(enriched)
            existing_urls.add(rule_url.lower())
            remaining = None if remaining is None else remaining - 1

    return supplemental_rules, fetcher.get_fetch_analytics_snapshot()


async def _scrape_georgia_court_rules_supplement(
    *,
    existing_source_urls: Optional[set[str]] = None,
    max_rules: Optional[int] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    fetcher = _GeorgiaProcedureRulesSupplementFetcher("GA", US_STATES["GA"])
    existing_urls = {
        str(url or "").strip().lower()
        for url in (existing_source_urls or set())
        if str(url or "").strip()
    }
    remaining = int(max_rules) if max_rules and int(max_rules) > 0 else None
    supplemental_rules: List[Dict[str, Any]] = []

    for source in _GA_RULE_DOCUMENTS:
        if remaining is not None and remaining <= 0:
            break
        source_url = str(source["url"])
        raw_bytes = await _fetch_pdf_bytes_with_direct_fallback(fetcher, source_url, timeout_seconds=240)
        if not raw_bytes:
            continue

        try:
            from pypdf import PdfReader

            reader = PdfReader(BytesIO(raw_bytes))
            page_texts = [(index + 1, page.extract_text() or "") for index, page in enumerate(reader.pages)]
        except Exception:
            extracted = await fetcher._extract_text_from_document_bytes(
                raw_bytes,
                source_url=source_url,
                content_type="application/pdf",
            )
            if not extracted:
                continue
            page_texts = [(index + 1, page) for index, page in enumerate(extracted.pages)]

        statutes = _extract_georgia_rules_from_page_texts(
            page_texts,
            source_url=source_url,
            title_name=str(source["title_name"]),
            procedure_family=str(source["procedure_family"]),
            legal_area=str(source["legal_area"]),
            official_cite_prefix=str(source["official_cite_prefix"]),
            first_rule_number=str(source["first_rule_number"]),
            current_as_of=str(source["current_as_of"]),
            max_rules=remaining,
        )
        for statute in statutes:
            if remaining is not None and remaining <= 0:
                break
            source_key = str(statute.source_url or "").strip().lower()
            if source_key in existing_urls:
                continue
            enriched = fetcher._enrich_statute_structure(statute).to_dict()
            family = str(statute.structured_data.get("procedure_family") or "").strip()
            if not family:
                continue
            enriched["procedure_family"] = family
            supplemental_rules.append(enriched)
            existing_urls.add(source_key)
            remaining = None if remaining is None else remaining - 1

    return supplemental_rules, fetcher.get_fetch_analytics_snapshot()


async def _scrape_pennsylvania_court_rules_supplement(
    *,
    existing_source_urls: Optional[set[str]] = None,
    max_rules: Optional[int] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    fetcher = _PennsylvaniaProcedureRulesSupplementFetcher("PA", US_STATES["PA"])
    existing_urls = {
        str(url or "").strip().lower()
        for url in (existing_source_urls or set())
        if str(url or "").strip()
    }
    remaining = int(max_rules) if max_rules and int(max_rules) > 0 else None
    supplemental_rules: List[Dict[str, Any]] = []

    for chapter in _PA_RULE_CHAPTER_PAGES:
        if remaining is not None and remaining <= 0:
            break
        chapter_url = str(chapter["url"])
        chapter_html = await _fetch_html_with_direct_fallback(
            fetcher,
            chapter_url,
            validator=lambda html: len(
                _extract_pennsylvania_rules_from_html(
                    html,
                    source_url=chapter_url,
                    title_name=str(chapter["title_name"]),
                    procedure_family=str(chapter["procedure_family"]),
                    legal_area=str(chapter["legal_area"]),
                    official_cite_prefix=str(chapter["official_cite_prefix"]),
                    first_rule_number=str(chapter["first_rule_number"]),
                    current_as_of=str(chapter["current_as_of"]),
                    max_rules=1,
                )
            )
            > 0,
            timeout_seconds=180,
        )
        if not chapter_html:
            continue
        statutes = _extract_pennsylvania_rules_from_html(
            chapter_html,
            source_url=chapter_url,
            title_name=str(chapter["title_name"]),
            procedure_family=str(chapter["procedure_family"]),
            legal_area=str(chapter["legal_area"]),
            official_cite_prefix=str(chapter["official_cite_prefix"]),
            first_rule_number=str(chapter["first_rule_number"]),
            current_as_of=str(chapter["current_as_of"]),
            max_rules=remaining,
        )
        for statute in statutes:
            if remaining is not None and remaining <= 0:
                break
            source_key = str(statute.source_url or "").strip().lower()
            if source_key in existing_urls:
                continue
            enriched = fetcher._enrich_statute_structure(statute).to_dict()
            family = str(statute.structured_data.get("procedure_family") or "").strip()
            if not family:
                continue
            enriched["procedure_family"] = family
            supplemental_rules.append(enriched)
            existing_urls.add(source_key)
            remaining = None if remaining is None else remaining - 1

    return supplemental_rules, fetcher.get_fetch_analytics_snapshot()


def _resolve_output_dir(output_dir: Optional[str] = None) -> Path:
    if output_dir:
        return Path(output_dir).expanduser().resolve()
    return get_canonical_legal_corpus("state_court_rules").default_local_root()


def _write_jsonld_files(filtered_data: List[Dict[str, Any]], output_dir: Path) -> List[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written: List[str] = []

    for state_block in filtered_data:
        state_code = str(state_block.get("state_code") or "").strip().upper()
        statutes = state_block.get("statutes") or []
        if not state_code or not isinstance(statutes, list):
            continue

        out_path = output_dir / f"STATE-{state_code}.jsonld"
        lines = 0
        with out_path.open("w", encoding="utf-8") as handle:
            for statute in statutes:
                if not isinstance(statute, dict):
                    continue
                payload = dict(statute)
                payload["procedure_family"] = _classify_procedure_family(statute)
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
                lines += 1

        if lines > 0:
            written.append(str(out_path))
        else:
            out_path.unlink(missing_ok=True)

    return written


async def list_state_procedure_rule_jurisdictions() -> Dict[str, Any]:
    return await list_state_jurisdictions()


async def scrape_state_procedure_rules(
    states: Optional[List[str]] = None,
    output_format: str = "json",
    include_metadata: bool = True,
    rate_limit_delay: float = 2.0,
    max_rules: Optional[int] = None,
    output_dir: Optional[str] = None,
    write_jsonld: bool = True,
    strict_full_text: bool = False,
    min_full_text_chars: int = 300,
    hydrate_rule_text: bool = True,
    parallel_workers: int = 6,
    per_state_retry_attempts: int = 1,
    retry_zero_rule_states: bool = True,
    per_state_timeout_seconds: float = 480.0,
) -> Dict[str, Any]:
    try:
        selected_states = [s.upper() for s in (states or []) if s and str(s).upper() in US_STATES]
        if not selected_states or "ALL" in selected_states:
            selected_states = list(US_STATES.keys())

        start = time.time()
        base_result = await scrape_state_laws(
            states=selected_states,
            legal_areas=None,
            output_format=output_format,
            include_metadata=include_metadata,
            rate_limit_delay=rate_limit_delay,
            max_statutes=None,
            output_dir=None,
            write_jsonld=False,
            strict_full_text=strict_full_text,
            min_full_text_chars=min_full_text_chars,
            hydrate_statute_text=hydrate_rule_text,
            parallel_workers=parallel_workers,
            per_state_retry_attempts=per_state_retry_attempts,
            retry_zero_statute_states=retry_zero_rule_states,
            per_state_timeout_seconds=per_state_timeout_seconds,
        )

        raw_data = list(base_result.get("data") or [])
        filtered_data: List[Dict[str, Any]] = []
        rules_count = 0
        zero_rule_states: List[str] = []
        supplemental_fetch_analytics_by_state: Dict[str, Dict[str, Any]] = {}
        family_counts: Dict[str, int] = {
            "civil_procedure": 0,
            "criminal_procedure": 0,
            "civil_and_criminal_procedure": 0,
        }

        for state_block in raw_data:
            if not isinstance(state_block, dict):
                continue

            state_code = str(state_block.get("state_code") or "").upper()
            statutes = list(state_block.get("statutes") or [])
            procedure_statutes: List[Dict[str, Any]] = []
            seen_source_urls = {
                str(statute.get("source_url") or statute.get("sourceUrl") or "").strip().lower()
                for statute in statutes
                if isinstance(statute, dict)
            }

            for statute in statutes:
                if not isinstance(statute, dict):
                    continue
                family = _classify_procedure_family(statute)
                if not family:
                    continue
                enriched = dict(statute)
                enriched["procedure_family"] = family
                procedure_statutes.append(enriched)
                family_counts[family] = int(family_counts.get(family, 0)) + 1

            if state_code == "RI":
                remaining_rule_budget = None
                if max_rules and max_rules > 0:
                    remaining_rule_budget = max(int(max_rules) - len(procedure_statutes), 0)
                ri_supplement, ri_fetch_analytics = await _scrape_rhode_island_court_rules_supplement(
                    existing_source_urls=seen_source_urls,
                    max_rules=remaining_rule_budget,
                )
                if ri_supplement:
                    procedure_statutes.extend(ri_supplement)
                    for rule in ri_supplement:
                        family = str(rule.get("procedure_family") or "").strip()
                        if family:
                            family_counts[family] = int(family_counts.get(family, 0)) + 1
                if ri_fetch_analytics:
                    supplemental_fetch_analytics_by_state[state_code] = ri_fetch_analytics

            if state_code == "OR":
                remaining_rule_budget = None
                if max_rules and max_rules > 0:
                    remaining_rule_budget = max(int(max_rules) - len(procedure_statutes), 0)
                or_supplement, or_fetch_analytics = await _scrape_oregon_court_rules_supplement(
                    existing_source_urls=seen_source_urls,
                    max_rules=remaining_rule_budget,
                )
                if or_supplement:
                    procedure_statutes.extend(or_supplement)
                    for rule in or_supplement:
                        family = str(rule.get("procedure_family") or "").strip()
                        if family:
                            family_counts[family] = int(family_counts.get(family, 0)) + 1
                if or_fetch_analytics:
                    supplemental_fetch_analytics_by_state[state_code] = or_fetch_analytics

            if state_code == "MI":
                remaining_rule_budget = None
                if max_rules and max_rules > 0:
                    remaining_rule_budget = max(int(max_rules) - len(procedure_statutes), 0)
                mi_supplement, mi_fetch_analytics = await _scrape_michigan_court_rules_supplement(
                    existing_source_urls=seen_source_urls,
                    max_rules=remaining_rule_budget,
                )
                if mi_supplement:
                    procedure_statutes.extend(mi_supplement)
                    for rule in mi_supplement:
                        family = str(rule.get("procedure_family") or "").strip()
                        if family:
                            family_counts[family] = int(family_counts.get(family, 0)) + 1
                if mi_fetch_analytics:
                    supplemental_fetch_analytics_by_state[state_code] = mi_fetch_analytics

            if state_code == "CA":
                remaining_rule_budget = None
                if max_rules and max_rules > 0:
                    remaining_rule_budget = max(int(max_rules) - len(procedure_statutes), 0)
                ca_supplement, ca_fetch_analytics = await _scrape_california_court_rules_supplement(
                    existing_source_urls=seen_source_urls,
                    max_rules=remaining_rule_budget,
                )
                if ca_supplement:
                    procedure_statutes.extend(ca_supplement)
                    for rule in ca_supplement:
                        family = str(rule.get("procedure_family") or "").strip()
                        if family:
                            family_counts[family] = int(family_counts.get(family, 0)) + 1
                if ca_fetch_analytics:
                    supplemental_fetch_analytics_by_state[state_code] = ca_fetch_analytics

            if state_code == "OH":
                remaining_rule_budget = None
                if max_rules and max_rules > 0:
                    remaining_rule_budget = max(int(max_rules) - len(procedure_statutes), 0)
                oh_supplement, oh_fetch_analytics = await _scrape_ohio_court_rules_supplement(
                    existing_source_urls=seen_source_urls,
                    max_rules=remaining_rule_budget,
                )
                if oh_supplement:
                    procedure_statutes.extend(oh_supplement)
                    for rule in oh_supplement:
                        family = str(rule.get("procedure_family") or "").strip()
                        if family:
                            family_counts[family] = int(family_counts.get(family, 0)) + 1
                if oh_fetch_analytics:
                    supplemental_fetch_analytics_by_state[state_code] = oh_fetch_analytics

            if state_code == "AZ":
                remaining_rule_budget = None
                if max_rules and max_rules > 0:
                    remaining_rule_budget = max(int(max_rules) - len(procedure_statutes), 0)
                az_supplement, az_fetch_analytics = await _scrape_arizona_court_rules_supplement(
                    existing_source_urls=seen_source_urls,
                    max_rules=remaining_rule_budget,
                )
                if az_supplement:
                    procedure_statutes.extend(az_supplement)
                    for rule in az_supplement:
                        family = str(rule.get("procedure_family") or "").strip()
                        if family:
                            family_counts[family] = int(family_counts.get(family, 0)) + 1
                if az_fetch_analytics:
                    supplemental_fetch_analytics_by_state[state_code] = az_fetch_analytics

            if state_code == "WA":
                remaining_rule_budget = None
                if max_rules and max_rules > 0:
                    remaining_rule_budget = max(int(max_rules) - len(procedure_statutes), 0)
                wa_supplement, wa_fetch_analytics = await _scrape_washington_court_rules_supplement(
                    existing_source_urls=seen_source_urls,
                    max_rules=remaining_rule_budget,
                )
                if wa_supplement:
                    procedure_statutes.extend(wa_supplement)
                    for rule in wa_supplement:
                        family = str(rule.get("procedure_family") or "").strip()
                        if family:
                            family_counts[family] = int(family_counts.get(family, 0)) + 1
                if wa_fetch_analytics:
                    supplemental_fetch_analytics_by_state[state_code] = wa_fetch_analytics

            if state_code == "NJ":
                remaining_rule_budget = None
                if max_rules and max_rules > 0:
                    remaining_rule_budget = max(int(max_rules) - len(procedure_statutes), 0)
                nj_supplement, nj_fetch_analytics = await _scrape_new_jersey_court_rules_supplement(
                    existing_source_urls=seen_source_urls,
                    max_rules=remaining_rule_budget,
                )
                if nj_supplement:
                    procedure_statutes.extend(nj_supplement)
                    for rule in nj_supplement:
                        family = str(rule.get("procedure_family") or "").strip()
                        if family:
                            family_counts[family] = int(family_counts.get(family, 0)) + 1
                if nj_fetch_analytics:
                    supplemental_fetch_analytics_by_state[state_code] = nj_fetch_analytics

            if state_code == "NH":
                remaining_rule_budget = None
                if max_rules and max_rules > 0:
                    remaining_rule_budget = max(int(max_rules) - len(procedure_statutes), 0)
                nh_supplement, nh_fetch_analytics = await _scrape_new_hampshire_court_rules_supplement(
                    existing_source_urls=seen_source_urls,
                    max_rules=remaining_rule_budget,
                )
                if nh_supplement:
                    procedure_statutes.extend(nh_supplement)
                    for rule in nh_supplement:
                        family = str(rule.get("procedure_family") or "").strip()
                        if family:
                            family_counts[family] = int(family_counts.get(family, 0)) + 1
                if nh_fetch_analytics:
                    supplemental_fetch_analytics_by_state[state_code] = nh_fetch_analytics

            if state_code == "NV":
                remaining_rule_budget = None
                if max_rules and max_rules > 0:
                    remaining_rule_budget = max(int(max_rules) - len(procedure_statutes), 0)
                nv_supplement, nv_fetch_analytics = await _scrape_nevada_court_rules_supplement(
                    existing_source_urls=seen_source_urls,
                    max_rules=remaining_rule_budget,
                )
                if nv_supplement:
                    procedure_statutes.extend(nv_supplement)
                    for rule in nv_supplement:
                        family = str(rule.get("procedure_family") or "").strip()
                        if family:
                            family_counts[family] = int(family_counts.get(family, 0)) + 1
                if nv_fetch_analytics:
                    supplemental_fetch_analytics_by_state[state_code] = nv_fetch_analytics

            if state_code == "CT":
                remaining_rule_budget = None
                if max_rules and max_rules > 0:
                    remaining_rule_budget = max(int(max_rules) - len(procedure_statutes), 0)
                ct_supplement, ct_fetch_analytics = await _scrape_connecticut_court_rules_supplement(
                    existing_source_urls=seen_source_urls,
                    max_rules=remaining_rule_budget,
                )
                if ct_supplement:
                    procedure_statutes.extend(ct_supplement)
                    for rule in ct_supplement:
                        family = str(rule.get("procedure_family") or "").strip()
                        if family:
                            family_counts[family] = int(family_counts.get(family, 0)) + 1
                if ct_fetch_analytics:
                    supplemental_fetch_analytics_by_state[state_code] = ct_fetch_analytics

            if state_code == "ID":
                remaining_rule_budget = None
                if max_rules and max_rules > 0:
                    remaining_rule_budget = max(int(max_rules) - len(procedure_statutes), 0)
                id_supplement, id_fetch_analytics = await _scrape_idaho_court_rules_supplement(
                    existing_source_urls=seen_source_urls,
                    max_rules=remaining_rule_budget,
                )
                if id_supplement:
                    procedure_statutes.extend(id_supplement)
                    for rule in id_supplement:
                        family = str(rule.get("procedure_family") or "").strip()
                        if family:
                            family_counts[family] = int(family_counts.get(family, 0)) + 1
                if id_fetch_analytics:
                    supplemental_fetch_analytics_by_state[state_code] = id_fetch_analytics

            if state_code == "ME":
                remaining_rule_budget = None
                if max_rules and max_rules > 0:
                    remaining_rule_budget = max(int(max_rules) - len(procedure_statutes), 0)
                me_supplement, me_fetch_analytics = await _scrape_maine_court_rules_supplement(
                    existing_source_urls=seen_source_urls,
                    max_rules=remaining_rule_budget,
                )
                if me_supplement:
                    procedure_statutes.extend(me_supplement)
                    for rule in me_supplement:
                        family = str(rule.get("procedure_family") or "").strip()
                        if family:
                            family_counts[family] = int(family_counts.get(family, 0)) + 1
                if me_fetch_analytics:
                    supplemental_fetch_analytics_by_state[state_code] = me_fetch_analytics

            if state_code == "MD":
                remaining_rule_budget = None
                if max_rules and max_rules > 0:
                    remaining_rule_budget = max(int(max_rules) - len(procedure_statutes), 0)
                md_supplement, md_fetch_analytics = await _scrape_maryland_court_rules_supplement(
                    existing_source_urls=seen_source_urls,
                    max_rules=remaining_rule_budget,
                )
                if md_supplement:
                    procedure_statutes.extend(md_supplement)
                    for rule in md_supplement:
                        family = str(rule.get("procedure_family") or "").strip()
                        if family:
                            family_counts[family] = int(family_counts.get(family, 0)) + 1
                if md_fetch_analytics:
                    supplemental_fetch_analytics_by_state[state_code] = md_fetch_analytics

            if state_code == "SC":
                remaining_rule_budget = None
                if max_rules and max_rules > 0:
                    remaining_rule_budget = max(int(max_rules) - len(procedure_statutes), 0)
                sc_supplement, sc_fetch_analytics = await _scrape_south_carolina_court_rules_supplement(
                    existing_source_urls=seen_source_urls,
                    max_rules=remaining_rule_budget,
                )
                if sc_supplement:
                    procedure_statutes.extend(sc_supplement)
                    for rule in sc_supplement:
                        family = str(rule.get("procedure_family") or "").strip()
                        if family:
                            family_counts[family] = int(family_counts.get(family, 0)) + 1
                if sc_fetch_analytics:
                    supplemental_fetch_analytics_by_state[state_code] = sc_fetch_analytics

            if state_code == "AK":
                remaining_rule_budget = None
                if max_rules and max_rules > 0:
                    remaining_rule_budget = max(int(max_rules) - len(procedure_statutes), 0)
                ak_supplement, ak_fetch_analytics = await _scrape_alaska_court_rules_supplement(
                    existing_source_urls=seen_source_urls,
                    max_rules=remaining_rule_budget,
                )
                if ak_supplement:
                    procedure_statutes.extend(ak_supplement)
                    for rule in ak_supplement:
                        family = str(rule.get("procedure_family") or "").strip()
                        if family:
                            family_counts[family] = int(family_counts.get(family, 0)) + 1
                if ak_fetch_analytics:
                    supplemental_fetch_analytics_by_state[state_code] = ak_fetch_analytics

            if state_code == "NE":
                remaining_rule_budget = None
                if max_rules and max_rules > 0:
                    remaining_rule_budget = max(int(max_rules) - len(procedure_statutes), 0)
                ne_supplement, ne_fetch_analytics = await _scrape_nebraska_court_rules_supplement(
                    existing_source_urls=seen_source_urls,
                    max_rules=remaining_rule_budget,
                )
                if ne_supplement:
                    procedure_statutes.extend(ne_supplement)
                    for rule in ne_supplement:
                        family = str(rule.get("procedure_family") or "").strip()
                        if family:
                            family_counts[family] = int(family_counts.get(family, 0)) + 1
                if ne_fetch_analytics:
                    supplemental_fetch_analytics_by_state[state_code] = ne_fetch_analytics

            if state_code == "HI":
                remaining_rule_budget = None
                if max_rules and max_rules > 0:
                    remaining_rule_budget = max(int(max_rules) - len(procedure_statutes), 0)
                hi_supplement, hi_fetch_analytics = await _scrape_hawaii_court_rules_supplement(
                    existing_source_urls=seen_source_urls,
                    max_rules=remaining_rule_budget,
                )
                if hi_supplement:
                    procedure_statutes.extend(hi_supplement)
                    for rule in hi_supplement:
                        family = str(rule.get("procedure_family") or "").strip()
                        if family:
                            family_counts[family] = int(family_counts.get(family, 0)) + 1
                if hi_fetch_analytics:
                    supplemental_fetch_analytics_by_state[state_code] = hi_fetch_analytics

            if state_code == "UT":
                remaining_rule_budget = None
                if max_rules and max_rules > 0:
                    remaining_rule_budget = max(int(max_rules) - len(procedure_statutes), 0)
                ut_supplement, ut_fetch_analytics = await _scrape_utah_court_rules_supplement(
                    existing_source_urls=seen_source_urls,
                    max_rules=remaining_rule_budget,
                )
                if ut_supplement:
                    procedure_statutes.extend(ut_supplement)
                    for rule in ut_supplement:
                        family = str(rule.get("procedure_family") or "").strip()
                        if family:
                            family_counts[family] = int(family_counts.get(family, 0)) + 1
                if ut_fetch_analytics:
                    supplemental_fetch_analytics_by_state[state_code] = ut_fetch_analytics

            if state_code == "NM":
                remaining_rule_budget = None
                if max_rules and max_rules > 0:
                    remaining_rule_budget = max(int(max_rules) - len(procedure_statutes), 0)
                nm_supplement, nm_fetch_analytics = await _scrape_new_mexico_court_rules_supplement(
                    existing_source_urls=seen_source_urls,
                    max_rules=remaining_rule_budget,
                )
                if nm_supplement:
                    procedure_statutes.extend(nm_supplement)
                    for rule in nm_supplement:
                        family = str(rule.get("procedure_family") or "").strip()
                        if family:
                            family_counts[family] = int(family_counts.get(family, 0)) + 1
                if nm_fetch_analytics:
                    supplemental_fetch_analytics_by_state[state_code] = nm_fetch_analytics

            if state_code == "WV":
                remaining_rule_budget = None
                if max_rules and max_rules > 0:
                    remaining_rule_budget = max(int(max_rules) - len(procedure_statutes), 0)
                wv_supplement, wv_fetch_analytics = await _scrape_west_virginia_court_rules_supplement(
                    existing_source_urls=seen_source_urls,
                    max_rules=remaining_rule_budget,
                )
                if wv_supplement:
                    procedure_statutes.extend(wv_supplement)
                    for rule in wv_supplement:
                        family = str(rule.get("procedure_family") or "").strip()
                        if family:
                            family_counts[family] = int(family_counts.get(family, 0)) + 1
                if wv_fetch_analytics:
                    supplemental_fetch_analytics_by_state[state_code] = wv_fetch_analytics

            if state_code == "ND":
                remaining_rule_budget = None
                if max_rules and max_rules > 0:
                    remaining_rule_budget = max(int(max_rules) - len(procedure_statutes), 0)
                nd_supplement, nd_fetch_analytics = await _scrape_north_dakota_court_rules_supplement(
                    existing_source_urls=seen_source_urls,
                    max_rules=remaining_rule_budget,
                )
                if nd_supplement:
                    procedure_statutes.extend(nd_supplement)
                    for rule in nd_supplement:
                        family = str(rule.get("procedure_family") or "").strip()
                        if family:
                            family_counts[family] = int(family_counts.get(family, 0)) + 1
                if nd_fetch_analytics:
                    supplemental_fetch_analytics_by_state[state_code] = nd_fetch_analytics

            if state_code == "MN":
                remaining_rule_budget = None
                if max_rules and max_rules > 0:
                    remaining_rule_budget = max(int(max_rules) - len(procedure_statutes), 0)
                mn_supplement, mn_fetch_analytics = await _scrape_minnesota_court_rules_supplement(
                    existing_source_urls=seen_source_urls,
                    max_rules=remaining_rule_budget,
                )
                if mn_supplement:
                    procedure_statutes.extend(mn_supplement)
                    for rule in mn_supplement:
                        family = str(rule.get("procedure_family") or "").strip()
                        if family:
                            family_counts[family] = int(family_counts.get(family, 0)) + 1
                if mn_fetch_analytics:
                    supplemental_fetch_analytics_by_state[state_code] = mn_fetch_analytics

            if state_code == "IA":
                remaining_rule_budget = None
                if max_rules and max_rules > 0:
                    remaining_rule_budget = max(int(max_rules) - len(procedure_statutes), 0)
                ia_supplement, ia_fetch_analytics = await _scrape_iowa_court_rules_supplement(
                    existing_source_urls=seen_source_urls,
                    max_rules=remaining_rule_budget,
                )
                if ia_supplement:
                    for rule in procedure_statutes:
                        family = str(rule.get("procedure_family") or "").strip()
                        if family:
                            family_counts[family] = max(int(family_counts.get(family, 0)) - 1, 0)
                    procedure_statutes = []
                    procedure_statutes.extend(ia_supplement)
                    for rule in ia_supplement:
                        family = str(rule.get("procedure_family") or "").strip()
                        if family:
                            family_counts[family] = int(family_counts.get(family, 0)) + 1
                if ia_fetch_analytics:
                    supplemental_fetch_analytics_by_state[state_code] = ia_fetch_analytics

            if state_code == "AR":
                remaining_rule_budget = None
                if max_rules and max_rules > 0:
                    remaining_rule_budget = max(int(max_rules) - len(procedure_statutes), 0)
                ar_supplement, ar_fetch_analytics = await _scrape_arkansas_court_rules_supplement(
                    existing_source_urls=seen_source_urls,
                    max_rules=remaining_rule_budget,
                )
                if ar_supplement:
                    for rule in procedure_statutes:
                        family = str(rule.get("procedure_family") or "").strip()
                        if family:
                            family_counts[family] = max(int(family_counts.get(family, 0)) - 1, 0)
                    procedure_statutes = []
                    procedure_statutes.extend(ar_supplement)
                    for rule in ar_supplement:
                        family = str(rule.get("procedure_family") or "").strip()
                        if family:
                            family_counts[family] = int(family_counts.get(family, 0)) + 1
                if ar_fetch_analytics:
                    supplemental_fetch_analytics_by_state[state_code] = ar_fetch_analytics

            if state_code == "AL":
                remaining_rule_budget = None
                if max_rules and max_rules > 0:
                    remaining_rule_budget = max(int(max_rules) - len(procedure_statutes), 0)
                al_supplement, al_fetch_analytics = await _scrape_alabama_court_rules_supplement(
                    existing_source_urls=seen_source_urls,
                    max_rules=remaining_rule_budget,
                )
                if al_supplement:
                    for rule in procedure_statutes:
                        family = str(rule.get("procedure_family") or "").strip()
                        if family:
                            family_counts[family] = max(int(family_counts.get(family, 0)) - 1, 0)
                    procedure_statutes = []
                    procedure_statutes.extend(al_supplement)
                    for rule in al_supplement:
                        family = str(rule.get("procedure_family") or "").strip()
                        if family:
                            family_counts[family] = int(family_counts.get(family, 0)) + 1
                if al_fetch_analytics:
                    supplemental_fetch_analytics_by_state[state_code] = al_fetch_analytics

            if state_code == "TN":
                remaining_rule_budget = None
                if max_rules and max_rules > 0:
                    remaining_rule_budget = max(int(max_rules) - len(procedure_statutes), 0)
                tn_supplement, tn_fetch_analytics = await _scrape_tennessee_court_rules_supplement(
                    existing_source_urls=seen_source_urls,
                    max_rules=remaining_rule_budget,
                )
                if tn_supplement:
                    for rule in procedure_statutes:
                        family = str(rule.get("procedure_family") or "").strip()
                        if family:
                            family_counts[family] = max(int(family_counts.get(family, 0)) - 1, 0)
                    procedure_statutes = []
                    procedure_statutes.extend(tn_supplement)
                    for rule in tn_supplement:
                        family = str(rule.get("procedure_family") or "").strip()
                        if family:
                            family_counts[family] = int(family_counts.get(family, 0)) + 1
                if tn_fetch_analytics:
                    supplemental_fetch_analytics_by_state[state_code] = tn_fetch_analytics

            if state_code == "VA":
                remaining_rule_budget = None
                if max_rules and max_rules > 0:
                    remaining_rule_budget = max(int(max_rules) - len(procedure_statutes), 0)
                va_supplement, va_fetch_analytics = await _scrape_virginia_court_rules_supplement(
                    existing_source_urls=seen_source_urls,
                    max_rules=remaining_rule_budget,
                )
                if va_supplement:
                    for rule in procedure_statutes:
                        family = str(rule.get("procedure_family") or "").strip()
                        if family:
                            family_counts[family] = max(int(family_counts.get(family, 0)) - 1, 0)
                    procedure_statutes = []
                    procedure_statutes.extend(va_supplement)
                    for rule in va_supplement:
                        family = str(rule.get("procedure_family") or "").strip()
                        if family:
                            family_counts[family] = int(family_counts.get(family, 0)) + 1
                if va_fetch_analytics:
                    supplemental_fetch_analytics_by_state[state_code] = va_fetch_analytics

            if state_code == "IN":
                remaining_rule_budget = None
                if max_rules and max_rules > 0:
                    remaining_rule_budget = max(int(max_rules) - len(procedure_statutes), 0)
                in_supplement, in_fetch_analytics = await _scrape_indiana_court_rules_supplement(
                    existing_source_urls=seen_source_urls,
                    max_rules=remaining_rule_budget,
                )
                if in_supplement:
                    for rule in procedure_statutes:
                        family = str(rule.get("procedure_family") or "").strip()
                        if family:
                            family_counts[family] = max(int(family_counts.get(family, 0)) - 1, 0)
                    procedure_statutes = []
                    procedure_statutes.extend(in_supplement)
                    for rule in in_supplement:
                        family = str(rule.get("procedure_family") or "").strip()
                        if family:
                            family_counts[family] = int(family_counts.get(family, 0)) + 1
                if in_fetch_analytics:
                    supplemental_fetch_analytics_by_state[state_code] = in_fetch_analytics

            if state_code == "IL":
                remaining_rule_budget = None
                if max_rules and max_rules > 0:
                    remaining_rule_budget = max(int(max_rules) - len(procedure_statutes), 0)
                il_supplement, il_fetch_analytics = await _scrape_illinois_court_rules_supplement(
                    existing_source_urls=seen_source_urls,
                    max_rules=remaining_rule_budget,
                )
                if il_supplement:
                    for rule in procedure_statutes:
                        family = str(rule.get("procedure_family") or "").strip()
                        if family:
                            family_counts[family] = max(int(family_counts.get(family, 0)) - 1, 0)
                    procedure_statutes = []
                    procedure_statutes.extend(il_supplement)
                    for rule in il_supplement:
                        family = str(rule.get("procedure_family") or "").strip()
                        if family:
                            family_counts[family] = int(family_counts.get(family, 0)) + 1
                if il_fetch_analytics:
                    supplemental_fetch_analytics_by_state[state_code] = il_fetch_analytics

            if state_code == "GA":
                remaining_rule_budget = None
                if max_rules and max_rules > 0:
                    remaining_rule_budget = max(int(max_rules) - len(procedure_statutes), 0)
                ga_supplement, ga_fetch_analytics = await _scrape_georgia_court_rules_supplement(
                    existing_source_urls=seen_source_urls,
                    max_rules=remaining_rule_budget,
                )
                if ga_supplement:
                    for rule in procedure_statutes:
                        family = str(rule.get("procedure_family") or "").strip()
                        if family:
                            family_counts[family] = max(int(family_counts.get(family, 0)) - 1, 0)
                    procedure_statutes = []
                    procedure_statutes.extend(ga_supplement)
                    for rule in ga_supplement:
                        family = str(rule.get("procedure_family") or "").strip()
                        if family:
                            family_counts[family] = int(family_counts.get(family, 0)) + 1
                if ga_fetch_analytics:
                    supplemental_fetch_analytics_by_state[state_code] = ga_fetch_analytics

            if state_code == "PA":
                remaining_rule_budget = None
                if max_rules and max_rules > 0:
                    remaining_rule_budget = max(int(max_rules) - len(procedure_statutes), 0)
                pa_supplement, pa_fetch_analytics = await _scrape_pennsylvania_court_rules_supplement(
                    existing_source_urls=seen_source_urls,
                    max_rules=remaining_rule_budget,
                )
                if pa_supplement:
                    for rule in procedure_statutes:
                        family = str(rule.get("procedure_family") or "").strip()
                        if family:
                            family_counts[family] = max(int(family_counts.get(family, 0)) - 1, 0)
                    procedure_statutes = []
                    procedure_statutes.extend(pa_supplement)
                    for rule in pa_supplement:
                        family = str(rule.get("procedure_family") or "").strip()
                        if family:
                            family_counts[family] = int(family_counts.get(family, 0)) + 1
                if pa_fetch_analytics:
                    supplemental_fetch_analytics_by_state[state_code] = pa_fetch_analytics

            if max_rules and max_rules > 0:
                procedure_statutes = procedure_statutes[: int(max_rules)]

            out_block = dict(state_block)
            out_block["title"] = f"{US_STATES.get(state_code, state_code)} Court Rules"
            out_block["source"] = "Official State Legislative/Judicial Sources"
            out_block["statutes"] = procedure_statutes
            out_block["rules_count"] = len(procedure_statutes)
            filtered_data.append(out_block)

            rules_count += len(procedure_statutes)
            if len(procedure_statutes) == 0 and state_code:
                zero_rule_states.append(state_code)

        canonical_corpus = get_canonical_legal_corpus("state_court_rules")
        jsonld_paths: List[str] = []
        jsonld_dir: Optional[str] = None
        if write_jsonld:
            output_root = _resolve_output_dir(output_dir)
            jsonld_root = canonical_corpus.jsonld_dir(str(output_root))
            jsonld_paths = _write_jsonld_files(filtered_data, jsonld_root)
            jsonld_dir = str(jsonld_root)

        elapsed = time.time() - start
        metadata = {
            "states_scraped": selected_states,
            "states_count": len(selected_states),
            "rules_count": rules_count,
            "canonical_dataset": canonical_corpus.key,
            "canonical_hf_dataset_id": canonical_corpus.hf_dataset_id,
            "family_counts": family_counts,
            "elapsed_time_seconds": elapsed,
            "scraped_at": datetime.now().isoformat(),
            "rate_limit_delay": rate_limit_delay,
            "parallel_workers": int(parallel_workers),
            "per_state_retry_attempts": int(per_state_retry_attempts),
            "retry_zero_rule_states": bool(retry_zero_rule_states),
            "strict_full_text": bool(strict_full_text),
            "min_full_text_chars": int(min_full_text_chars),
            "hydrate_rule_text": bool(hydrate_rule_text),
            "zero_rule_states": sorted(set(zero_rule_states)) if zero_rule_states else None,
            "jsonld_dir": jsonld_dir,
            "jsonld_files": jsonld_paths if jsonld_paths else None,
            "fetch_analytics_by_state": _merge_fetch_analytics(
                (base_result.get("metadata") or {}).get("fetch_analytics_by_state") or {},
                supplemental_fetch_analytics_by_state,
            ),
            "supplemental_fetch_analytics_by_state": supplemental_fetch_analytics_by_state or None,
            "base_status": base_result.get("status"),
            "base_metadata": base_result.get("metadata") if include_metadata else None,
        }

        status = "success"
        if base_result.get("status") in {"error", "partial_success"}:
            status = "partial_success"
        if rules_count == 0:
            status = "partial_success"

        return {
            "status": status,
            "data": filtered_data,
            "metadata": metadata,
            "output_format": output_format,
        }

    except Exception as exc:
        logger.error("State procedure-rules scraping failed: %s", exc)
        return {
            "status": "error",
            "error": str(exc),
            "data": [],
            "metadata": {},
        }


__all__ = [
    "list_state_procedure_rule_jurisdictions",
    "scrape_state_procedure_rules",
]
